"""Run six bounded Phase 4A shadow smoke scenarios with a clean, validated start each."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tb_runner.bottom_nav import annotate_bottom_nav_candidates, is_annotated_bottom_nav_candidate
from tools.full32_acceptance_monitor import AcceptanceMonitor, MonitorHit
from tools.clean_start_smartthings import clean_start_smartthings
from tools.state_fingerprint_diagnostic import capture_observation
from talkback_lib import A11yAdbClient


ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ.get("TB_PHASE4A_SMOKE_OUT", "../phase4a_shadow_smoke_20261011")).resolve()
SERIAL = "R3CX40QFDBP"
SCENARIOS = (
    "home_main",
    "devices_main",
    "life_food_plugin",
    "life_family_care_plugin",
    "life_find_plugin",
    "device_smoke_sensor_plugin",
)
TALKBACK_PACKAGE = "com.samsung.android.accessibility.talkback"
HELPER_PACKAGE = "com.iotpart.sqe.talkbackhelper"
SMARTTHINGS_PACKAGE = "com.samsung.android.oneconnect"
VALID_TABS = {"home", "devices", "life", "routines", "menu"}


def adb(*args: str) -> str:
    completed = subprocess.run(
        ["adb", "-s", SERIAL, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def device_state() -> dict[str, str]:
    return {
        "talkback_pid": adb("shell", "pidof", TALKBACK_PACKAGE),
        "helper_pid": adb("shell", "pidof", HELPER_PACKAGE),
        "locale": adb("shell", "getprop", "persist.sys.locale"),
    }


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_precondition(scenario: str, monitor: AcceptanceMonitor, baseline: dict[str, str]) -> dict:
    before = device_state()
    ready, commands, focus = clean_start_smartthings(serial=SERIAL, wait_seconds=8.0, max_attempts=2)
    observation = capture_observation(
        A11yAdbClient(start_monitor=False), SERIAL, scenario_id="smoke_precondition:" + scenario
    )
    state = device_state()
    nav_nodes = annotate_bottom_nav_candidates(observation["nodes"], expected_count=5)
    nav_candidates = [node for node in nav_nodes if is_annotated_bottom_nav_candidate(node)]
    selected_tab = (observation.get("selected_tab") or {}).get("name")
    foreground = observation.get("package_name") == SMARTTHINGS_PACKAGE
    stable_shell = str(observation.get("activity_name") or "").endswith("SCMainActivity")
    bottom_nav = len(nav_candidates) >= 5
    overlay = observation.get("overlay") or {}
    overlay_clear = overlay.get("observed") is False
    tab_valid = selected_tab in VALID_TABS
    tab_verified = bool((observation.get("selected_tab") or {}).get("verified"))
    talkback_stable = bool(baseline.get("talkback_pid")) and state["talkback_pid"] == baseline["talkback_pid"]
    helper_stable = bool(baseline.get("helper_pid")) and state["helper_pid"] == baseline["helper_pid"]
    locale_stable = bool(baseline.get("locale")) and state["locale"] == baseline["locale"]
    result = {
        "time": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "clean_start_succeeded": ready,
        "clean_start_commands": [
            {"command": list(item.command), "returncode": item.returncode, "stdout": item.stdout, "stderr": item.stderr}
            for item in commands
        ],
        "clean_start_focus": focus,
        "before_device_state": before,
        "after_device_state": state,
        "smartthings_foreground": foreground,
        "stable_shell_root": stable_shell,
        "bottom_nav_available": bottom_nav,
        "bottom_nav_candidate_count": len(nav_candidates),
        "current_tab": selected_tab,
        "selected_tab_verified": bool(observation.get("selected_tab", {}).get("verified")),
        "transient_overlay_present": overlay.get("observed"),
        "overlay_detector_source": overlay.get("source"),
        "start_state_valid": bool(
            ready and foreground and stable_shell and bottom_nav and overlay_clear and tab_valid
            and tab_verified and talkback_stable and helper_stable and locale_stable
        ),
        "talkback_pid_stable": talkback_stable,
        "helper_pid_stable": helper_stable,
        "locale_unchanged": locale_stable,
        "observation": observation,
    }
    save_json(OUT / "preconditions" / f"{scenario}.json", result)
    print(
        "[SMOKE_PRECONDITION] "
        + json.dumps(
            {
                "scenario": scenario,
                "SMOKE_PRECONDITION_READY": result["start_state_valid"],
                "SMARTTHINGS_FOREGROUND": foreground,
                "BOTTOM_NAV_AVAILABLE": bottom_nav,
                "TRANSIENT_OVERLAY_PRESENT": overlay.get("observed"),
                "CURRENT_TAB": selected_tab,
                "START_STATE_VALID": result["start_state_valid"],
            }
        ),
        flush=True,
    )
    if not talkback_stable:
        monitor.observe_talkback_pid(state["talkback_pid"], observed_at=datetime.now(timezone.utc))
    return result


def _consume_new(
    paths: dict[str, Path],
    offsets: dict[str, int],
    pending: dict[str, str],
    monitor: AcceptanceMonitor,
    badtoken_context: dict[str, int],
):
    hits = []
    for source, path in paths.items():
        with path.open("rb") as stream:
            stream.seek(offsets[source])
            data = stream.read()
            offsets[source] = stream.tell()
        block = pending[source] + data.decode("utf-8", errors="replace")
        lines = block.split("\n")
        pending[source] = lines.pop()
        for line in lines:
            observed_at = datetime.now(timezone.utc)
            hits.extend(monitor.feed_line(line, source=source, observed_at=observed_at))
            hits.extend(monitor.feed_lifecycle(line))
            if source == "runner" and re.search(r"\[CRASH_RECOVERY\]\s+state='RETRYING_SCENARIO'", line):
                hits.append(MonitorHit("scenario_retry_attempted", line.strip()))
            if source == "logcat":
                header = re.match(r"^\s*\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+(\d+)\s+", line)
                source_pid = header.group(1) if header else ""
                if source_pid:
                    if re.search(r"\bFATAL EXCEPTION\b", line, re.I):
                        badtoken_context[source_pid] = 40
                    elif "BadTokenException" in line and badtoken_context.get(source_pid, 0):
                        if source_pid == monitor.talkback_pid:
                            hits.append(MonitorHit("talkback_fatal_badtoken", line.strip(), observed_at.isoformat()))
                        badtoken_context[source_pid] = 0
                    elif source_pid in badtoken_context:
                        badtoken_context[source_pid] -= 1
                        if badtoken_context[source_pid] <= 0:
                            badtoken_context.pop(source_pid, None)
    return hits


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    device_state_before = device_state()
    service_list = adb("shell", "settings", "get", "secure", "enabled_accessibility_services")
    helper_path = adb("shell", "pm", "path", HELPER_PACKAGE)
    smartthings_path = adb("shell", "pm", "path", SMARTTHINGS_PACKAGE)
    device_status = adb("get-state")
    if (
        device_status != "device"
        or not device_state_before["talkback_pid"]
        or not device_state_before["helper_pid"]
        or "talkback" not in service_list.lower()
        or "talkbackhelper" not in service_list.lower()
        or not helper_path.startswith("package:")
        or not smartthings_path.startswith("package:")
        or not device_state_before["locale"]
    ):
        raise RuntimeError("device precheck failed; inspect precheck.json")

    start = datetime.now(timezone.utc)
    monitor = AcceptanceMonitor(
        start,
        talkback_pid=device_state_before["talkback_pid"],
        helper_pid=device_state_before["helper_pid"],
    )
    precheck = {
        "time": start.isoformat(),
        "serial": SERIAL,
        "device_status": device_status,
        "locale": device_state_before["locale"],
        "talkback_pid": device_state_before["talkback_pid"],
        "helper_pid": device_state_before["helper_pid"],
        "accessibility_services": service_list,
        "helper_package_path": helper_path,
        "smartthings_package_path": smartthings_path,
        "foreground_before_precondition": adb("shell", "dumpsys", "window"),
    }
    save_json(OUT / "precheck.json", precheck)
    logcat_path = OUT / "logcat.txt"
    runner_path = OUT / "runner.log"
    monitor_path = OUT / "monitor.jsonl"
    logcat_file = logcat_path.open("wb")
    logcat = subprocess.Popen(
        ["adb", "-s", SERIAL, "logcat", "-v", "threadtime", "-T", "1"],
        stdout=logcat_file,
        stderr=subprocess.STDOUT,
    )
    runner_file = runner_path.open("ab")
    paths = {"runner": runner_path, "logcat": logcat_path}
    offsets = {name: path.stat().st_size for name, path in paths.items()}
    pending = {"runner": "", "logcat": ""}
    badtoken_context: dict[str, int] = {}
    scenario_results = []
    all_hits = []
    helper_pid_change_count = 0
    talkback_pid_change_count = 0
    smoke_stopped = False

    runtime_config_path = OUT / "runtime_config.json"
    runtime_config = json.loads((ROOT / "config" / "runtime_config.json").read_text(encoding="utf-8"))
    for scenario in SCENARIOS:
        runtime_config.setdefault("scenarios", {}).setdefault(scenario, {})["max_steps"] = 5
    save_json(runtime_config_path, runtime_config)

    run_env = os.environ.copy()
    run_env["TB_PHASE4A_SMOKE_OUT"] = str(OUT)
    run_env["TB_RUNTIME_CONFIG_PATH"] = str(runtime_config_path)
    run_env["TB_EVIDENCE_LEDGER"] = "1"
    run_env["TB_TRAVERSAL_PROFILER"] = "1"
    run_env["TB_EVIDENCE_LEDGER_ENABLED"] = "1"
    run_env["TB_TRAVERSAL_PROFILER_ENABLED"] = "1"
    run_env["TB_TRAVERSAL_IDENTITY_V2_ENABLED"] = "1"

    try:
        with monitor_path.open("w", encoding="utf-8") as monitor_file:
            for scenario in SCENARIOS:
                precondition = validate_precondition(scenario, monitor, device_state_before)
                if not precondition["start_state_valid"]:
                    if not precondition["talkback_pid_stable"]:
                        talkback_pid_change_count += 1
                        all_hits.extend(monitor.observe_talkback_pid(
                            precondition["after_device_state"]["talkback_pid"],
                            observed_at=datetime.now(timezone.utc),
                        ))
                        scenario_results.append({"scenario": scenario, "precondition": precondition, "started": False, "reason": "talkback_pid_changed"})
                        smoke_stopped = True
                        break
                    if not precondition["helper_pid_stable"]:
                        helper_pid_change_count += 1
                        scenario_results.append({"scenario": scenario, "precondition": precondition, "started": False, "reason": "helper_pid_changed"})
                        smoke_stopped = True
                        break
                    # A second setup attempt repairs only the smoke start state; no scenario ran.
                    precondition = validate_precondition(scenario, monitor, device_state_before)
                if not precondition["start_state_valid"]:
                    scenario_results.append(
                        {"scenario": scenario, "precondition": precondition, "started": False, "reason": "invalid_smoke_precondition"}
                    )
                    smoke_stopped = True
                    break

                before_run_state = device_state()
                if before_run_state["talkback_pid"] != device_state_before["talkback_pid"]:
                    talkback_pid_change_count += 1
                    all_hits.extend(monitor.observe_talkback_pid(before_run_state["talkback_pid"], observed_at=datetime.now(timezone.utc)))
                    smoke_stopped = True
                    scenario_results.append({"scenario": scenario, "precondition": precondition, "started": False, "reason": "talkback_pid_changed"})
                    break
                if before_run_state["helper_pid"] != device_state_before["helper_pid"]:
                    helper_pid_change_count += 1
                    smoke_stopped = True
                    scenario_results.append({"scenario": scenario, "precondition": precondition, "started": False, "reason": "helper_pid_changed"})
                    break

                run_env["TB_PHASE4A_SMOKE_SCENARIO"] = scenario
                started_at = datetime.now(timezone.utc)
                runner_file.write((f"\n[PHASE4A_SMOKE_SUPERVISOR] scenario_start={scenario} time={started_at.isoformat()}\n").encode())
                runner_file.flush()
                process = subprocess.Popen(
                    [sys.executable, "-u", "-m", "tools.phase4a_shadow_smoke"],
                    cwd=ROOT,
                    env=run_env,
                    stdout=runner_file,
                    stderr=subprocess.STDOUT,
                )
                scenario_hits = []
                helper_changed = False
                with monitor_path.open("a", encoding="utf-8") as samples:
                    while process.poll() is None:
                        scenario_hits.extend(_consume_new(paths, offsets, pending, monitor, badtoken_context))
                        current = device_state()
                        if not current["talkback_pid"]:
                            scenario_hits.append(MonitorHit("talkback_pid_missing", f"{TALKBACK_PACKAGE} pidof returned empty"))
                        elif current["talkback_pid"] != monitor.talkback_pid:
                            scenario_hits.extend(monitor.observe_talkback_pid(current["talkback_pid"], observed_at=datetime.now(timezone.utc)))
                        if current["helper_pid"] != device_state_before["helper_pid"]:
                            helper_changed = True
                        record = {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "scenario": scenario,
                            "talkback_pid": current["talkback_pid"],
                            "helper_pid": current["helper_pid"],
                            "hard_blockers": [{"code": h.code, "evidence": h.evidence} for h in scenario_hits],
                        }
                        samples.write(json.dumps(record) + "\n")
                        samples.flush()
                        if scenario_hits or helper_changed:
                            if helper_changed:
                                helper_pid_change_count += 1
                            process.terminate()
                            smoke_stopped = True
                            break
                        time.sleep(2)
                    return_code = process.wait(timeout=20)
                scenario_hits.extend(_consume_new(paths, offsets, pending, monitor, badtoken_context))
                all_hits.extend(scenario_hits)
                talkback_pid_change_count = len(
                    {h.evidence for h in all_hits if h.code in {"talkback_pid_change", "talkback_restart", "talkback_pid_missing"}}
                )
                scenario_result = {
                    "scenario": scenario,
                    "precondition": precondition,
                    "started": True,
                    "start_time": started_at.isoformat(),
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "return_code": return_code,
                    "hard_hits": [{"code": h.code, "evidence": h.evidence} for h in scenario_hits],
                }
                scenario_results.append(scenario_result)
                print("[SMOKE_SCENARIO_RESULT] " + json.dumps({k: v for k, v in scenario_result.items() if k != "precondition"}), flush=True)
                if scenario_hits or helper_changed or return_code != 0:
                    smoke_stopped = True
                    break
    finally:
        runner_file.flush()
        runner_file.close()
        logcat.terminate()
        try:
            logcat.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logcat.kill()
        logcat_file.close()

    codes = [hit.code for hit in all_hits]
    gates = {
        "TALKBACK_PID_CHANGE_COUNT": talkback_pid_change_count + codes.count("talkback_pid_missing"),
        "HELPER_UNEXPECTED_PID_CHANGE_COUNT": helper_pid_change_count,
        "WINDOW_FATAL_COUNT": codes.count("talkback_window_fatal"),
        "FATAL_BADTOKEN_COUNT": codes.count("talkback_fatal_badtoken"),
        "HELPER_ANR_COUNT": codes.count("helper_anr"),
        "SMART_NEXT_TIMEOUT_COUNT": codes.count("smart_next_timeout") + codes.count("smart_next_transport_error"),
        "FOCUS_TIMEOUT_COUNT": codes.count("focus_transport_error"),
        "CHUNK_ERROR_COUNT": codes.count("chunk_corruption"),
        "INSPECTION_SUPPRESSION_COUNT": codes.count("old_suppressing_dump"),
        "TALKBACK_RECONNECT_COUNT": codes.count("inspection_reconnect"),
    }
    final_state = device_state()
    summary = {
        "start_time": start.isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat(),
        "serial": SERIAL,
        "locale_start": device_state_before["locale"],
        "locale_end": final_state["locale"],
        "talkback_pid_start": device_state_before["talkback_pid"],
        "talkback_pid_end": final_state["talkback_pid"],
        "helper_pid_start": device_state_before["helper_pid"],
        "helper_pid_end": final_state["helper_pid"],
        "scenarios_expected": len(SCENARIOS),
        "scenarios_started": sum(bool(item.get("started")) for item in scenario_results),
        "scenarios_completed": sum(bool(item.get("started")) and item.get("return_code") == 0 and not item.get("hard_hits") for item in scenario_results),
        "smoke_stopped": smoke_stopped,
        "hard_hits": [{"code": hit.code, "evidence": hit.evidence} for hit in all_hits],
        "lifecycle_gates": gates,
        "scenario_results": scenario_results,
    }
    save_json(OUT / "monitor_result.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    clean = summary["scenarios_completed"] == len(SCENARIOS) and not smoke_stopped and all(value == 0 for value in gates.values())
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
