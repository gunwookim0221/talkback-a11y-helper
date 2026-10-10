"""Launch and supervise one explicitly selected TalkBack validation batch."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.full32_acceptance_monitor import AcceptanceMonitor, MonitorHit
except ModuleNotFoundError:  # Running this file directly puts tools/ on sys.path.
    from full32_acceptance_monitor import AcceptanceMonitor, MonitorHit


FULL32_SCENARIOS = [
    "global_nav_main",
    "home_main",
    "home_safe_plugin",
    "life_food_plugin",
    "life_air_care_plugin",
    "life_home_care_plugin",
    "life_energy_plugin",
    "devices_main",
    "device_smoke_sensor_plugin",
    "device_water_leak_sensor_plugin",
    "device_motion_sensor_plugin",
    "device_door_lock_plugin",
    "device_air_purifier_plugin",
    "device_tv_plugin",
    "device_washer_plugin",
    "device_humidity_sensor_plugin",
    "device_temperature_humidity_sensor_plugin",
    "device_camera_plugin",
    "device_home_camera_plugin",
    "device_audio_plugin",
    "life_main",
    "routines_main",
    "menu_main",
    "settings_entry_example",
    "life_pet_care_plugin",
    "life_family_care_plugin",
    "life_plant_care_plugin",
    "life_clothing_care_plugin",
    "life_find_plugin",
    "life_video_plugin",
    "life_home_monitor_plugin",
    "life_music_sync_plugin",
]


def _request(
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 8,
    method: str | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method or ("POST" if data is not None else "GET"),
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8", "replace"))
        return parsed if isinstance(parsed, dict) else {"value": parsed}


def _pidof(serial: str, package: str) -> str | None:
    result = subprocess.run(
        ["adb", "-s", serial, "shell", "pidof", package],
        capture_output=True,
        text=True,
        timeout=6,
        check=False,
    )
    values = result.stdout.strip().split()
    return values[0] if result.returncode == 0 and values else None


def _read_new_lines(path: Path, offsets: dict[Path, int], pending: dict[Path, str]) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    offset = offsets.setdefault(path, 0)
    if size < offset:
        offset = 0
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read()
            offsets[path] = stream.tell()
    except OSError:
        return []
    if not data:
        return []
    text = pending.get(path, "") + data.decode("utf-8", "replace")
    parts = text.splitlines(keepends=True)
    complete = [part[:-1].removesuffix("\r") for part in parts if part.endswith(("\n", "\r"))]
    pending[path] = parts[-1] if parts and not parts[-1].endswith(("\n", "\r")) else ""
    return complete


def _status_snapshot(status: dict[str, Any]) -> dict[str, Any]:
    progress = status.get("progress") or {}
    current = status.get("current") or {}
    devices = status.get("devices") or []
    return {
        "state": status.get("state"),
        "scenario": current.get("current_scenario_id"),
        "step": current.get("current_step_index"),
        "completed": progress.get("completed_scenarios"),
        "terminal": progress.get("terminal_scenarios"),
        "observed": progress.get("observed_scenarios"),
        "devices": [{"serial": d.get("serial"), "state": d.get("state")} for d in devices if isinstance(d, dict)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--full32", action="store_true")
    selection.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--language-mode", choices=("ko-KR", "en-US"), default="ko-KR")
    parser.add_argument("--qa-runs-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--sample-file", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--max-hours", type=float, default=8.0)
    args = parser.parse_args()

    scenarios = FULL32_SCENARIOS if args.full32 else list(args.scenarios or [])
    if not scenarios:
        parser.error("at least one --scenario is required")
    if len(scenarios) != len(set(scenarios)):
        parser.error("scenario selection contains duplicates")

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    sample_path = args.evidence_dir / args.sample_file
    started_at = datetime.now(timezone.utc)
    talkback_pid = _pidof(args.serial, "com.samsung.android.accessibility.talkback")
    helper_pid = _pidof(args.serial, "com.iotpart.sqe.talkbackhelper")
    if not talkback_pid or not helper_pid:
        print(f"PREFLIGHT_FAILED=talkback_pid={talkback_pid},helper_pid={helper_pid}", flush=True)
        return 2
    monitor = AcceptanceMonitor(started_at, talkback_pid=talkback_pid, helper_pid=helper_pid)

    payload = {
        "scenario_ids": scenarios,
        "traversal_identity_v2": True,
        "enable_coverage_probe": True,
        "launch_mode": "clean",
        "mode": "full",
        "identity_shadow_v2": True,
        "shadow_validation": False,
        "evidence_ledger": True,
        "traversal_profiler": True,
        "devices": [{"serial": args.serial, "model": args.model}],
        "language_mode": args.language_mode,
    }
    print(f"MONITOR_START_TIMESTAMP={started_at.isoformat()}", flush=True)
    print(f"TALKBACK_BASELINE_PID={talkback_pid}", flush=True)
    print(f"HELPER_BASELINE_PID={helper_pid}", flush=True)
    print(f"LANGUAGE_MODE={args.language_mode}", flush=True)
    print(f"SELECTED_SCENARIOS={len(scenarios)}", flush=True)
    try:
        started = _request(args.base_url, "/api/batch/start", payload)
    except Exception as exc:
        print(f"START_REQUEST_FAILED={type(exc).__name__}:{exc}", flush=True)
        return 3

    batch_id = str(started.get("batch_id") or started.get("id") or "")
    if not batch_id:
        print("START_REQUEST_FAILED=batch_id missing from response", flush=True)
        return 4
    print(f"BATCH_ID={batch_id}", flush=True)
    batch_root = args.qa_runs_dir / batch_id
    device_root = batch_root / f"device_{args.model}_{args.serial}"
    offsets: dict[Path, int] = {}
    pending: dict[Path, str] = {}
    # The batch ID is unique and this directory did not exist before launch;
    # offset zero therefore admits all run records but no historical logs.
    for name in ("runner.log", "logcat.txt", "talkback_window_lifecycle.jsonl"):
        offsets[device_root / name] = 0

    deadline = time.monotonic() + args.max_hours * 3600
    terminal_states = {"finished", "stopped", "error"}
    consecutive_pid_errors = 0
    exit_code = 0
    with sample_path.open("a", encoding="utf-8") as samples:
        while time.monotonic() < deadline:
            try:
                status = _request(args.base_url, "/api/batch/status")
            except Exception as exc:
                reason = f"monitor_status_unavailable:{type(exc).__name__}:{exc}"
                print("MONITOR_FAILURE=" + reason, flush=True)
                try:
                    _request(args.base_url, "/api/batch/stop", timeout=12, method="POST")
                except Exception:
                    pass
                exit_code = 5
                break

            hits = []
            for source, name in (("runner", "runner.log"), ("logcat", "logcat.txt")):
                for line in _read_new_lines(device_root / name, offsets, pending):
                    hits.extend(monitor.feed_line(line, source=source))
            for path in device_root.rglob("talkback_window_lifecycle.jsonl") if device_root.exists() else []:
                for line in _read_new_lines(path, offsets, pending):
                    hits.extend(monitor.feed_lifecycle(line))

            now = datetime.now(timezone.utc)
            hits.extend(monitor.observe_scenario_failure_count(status, observed_at=now))
            current_pid = _pidof(args.serial, "com.samsung.android.accessibility.talkback")
            if current_pid:
                consecutive_pid_errors = 0
                hits.extend(monitor.observe_talkback_pid(current_pid, observed_at=now))
            else:
                consecutive_pid_errors += 1
                if consecutive_pid_errors >= 3:
                    hits.append(MonitorHit("talkback_pid_unavailable", "three consecutive fresh pidof reads returned no TalkBack PID", now.isoformat()))

            snapshot = _status_snapshot(status)
            sample = {
                "timestamp_utc": now.isoformat(timespec="seconds"),
                **snapshot,
                "talkback_pid": current_pid,
                "hard_blockers": [{"code": hit.code, "evidence": hit.evidence, "event_timestamp": hit.event_timestamp} for hit in hits],
            }
            samples.write(json.dumps(sample, separators=(",", ":")) + "\n")
            samples.flush()
            print("SAMPLE=" + json.dumps(sample, separators=(",", ":")), flush=True)

            if hits:
                reason = ",".join(sorted({hit.code for hit in hits}))
                print("HARD_BLOCKER_STOP_REQUEST=" + reason, flush=True)
                try:
                    response = _request(args.base_url, "/api/batch/stop", timeout=12, method="POST")
                    print("STOP_RESPONSE=" + json.dumps(response, separators=(",", ":")), flush=True)
                except Exception as exc:
                    print(f"STOP_REQUEST_FAILED={type(exc).__name__}:{exc}", flush=True)
                exit_code = 6
                break

            if str(status.get("state", "")).lower() in terminal_states:
                print("MONITOR_TERMINAL_STATE=" + str(status.get("state")), flush=True)
                break
            time.sleep(args.poll_seconds)
        else:
            print("MONITOR_DEADLINE_EXCEEDED=true", flush=True)
            try:
                _request(args.base_url, "/api/batch/stop", timeout=12, method="POST")
            except Exception:
                pass
            exit_code = 7

    final = _request(args.base_url, "/api/batch/status")
    print("FINAL_STATUS=" + json.dumps(_status_snapshot(final), separators=(",", ":")), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
