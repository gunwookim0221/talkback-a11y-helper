import threading
import subprocess
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import traceback
from tb_runner.run_spec import RunSpec
from .paths import ROOT_DIR, RUN_LOG_DIR, SCRIPT_PATH, RUNTIME_CONFIG_PATH
from .runtime_dashboard import parse_runtime_log
from .runtime_config_selection import write_selected_runtime_config
from .device_locale import apply_language_mode, normalize_language_mode, format_language_log_lines
from .preflight import (
    run_surface_preflight as run_runtime_preflight,
    normalize_launch_mode,
    format_preflight_log_lines,
)
from .subprocess_executor import RunExecution, close_execution_log, start_execution, wait_for_execution
from .runtime_setup import prepare_runtime
from .crash_capture import start_crash_logcat_capture, stop_crash_logcat_capture
from .sleep_prevention import (
    disable_sleep_prevention,
    enable_device_stay_awake,
    enable_sleep_prevention,
    restore_device_stay_awake,
)
from .shadow_pipeline import run_shadow_validation_pipeline

def _json_safe(value):
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


CURRENT_STEP_LABEL_RE = re.compile(r"(?:visible|label|talkback_label)='([^']*)'")
CURRENT_STEP_ACTION_RE = re.compile(r"(?:action|move_result)=(?:'([^']*)'|([^\s]+))")
CURRENT_STEP_TARGET_RE = re.compile(r"(?:target|target_name|targetName)=(?:'([^']*)'|([^\s]+))")
CURRENT_FINAL_RESULT_RE = re.compile(r"final_result='([^']*)'")
CURRENT_STEP_RESULT_RE = re.compile(r"(?:\bmove_result|(?<!_)\bresult)='([^']*)'")
SMART_NAV_RESULT_RE = re.compile(r"last_smart_nav_result='([^']*)'")
SMART_NAV_DETAIL_RE = re.compile(r"last_smart_nav_detail='([^']*)'")
PREFLIGHT_STEP_RE = re.compile(r"\[PREFLIGHT\]\s+(device_connected|wake_screen|unlock_swipe|app_foreground)\s+([A-Z_]+)")
TALKBACK_STATUS_RE = re.compile(r"\[PREFLIGHT\]\s+talkback status='([^']*)'")


def _empty_live_status() -> dict:
    return {
        "runner_log_path": None,
        "current": {
            "current_device_serial": None,
            "current_device_model": None,
            "current_device_state": None,
            "current_scenario_id": None,
            "current_scenario_name": None,
            "current_scenario_runtime_state": None,
            "current_scenario_state": None,
            "latest_scenario_event": None,
            "current_step_index": None,
            "current_step_label": None,
            "current_step_action": None,
            "current_step_target": None,
            "current_step_result": None,
            "current_navigation_result": None,
            "current_navigation_detail": None,
            "latest_step_log": None,
            "current_step_log": None,
            "latest_runtime_event": None,
        },
        "progress": {
            "selected_scenarios": 0,
            "observed_scenarios": 0,
            "tail_observed_scenarios": 0,
            "total_scenarios": 0,
            "completed_scenarios": 0,
            "executed_scenarios": 0,
            "not_available_scenarios": 0,
            "not_available_candidate_scenarios": 0,
            "no_target_candidate_scenarios": 0,
            "availability_candidate_scenarios": 0,
            "passed_scenarios": 0,
            "failed_scenarios": 0,
            "warning_scenarios": 0,
            "observed_runtime_events": 0,
            "observed_steps": 0,
            "total_steps": 0,
            "completed_steps": 0,
            "pass_count": 0,
            "warn_count": 0,
            "fail_count": 0,
            "review_count": 0,
        },
        "logs": {
            "latest_log_line": None,
            "latest_preflight_status": {
                "device_connected": None,
                "screen_awake": None,
                "unlock_swipe": None,
                "app_foreground": None,
                "helper": None,
                "talkback": None,
            },
            "latest_quality_event": None,
        },
    }


def _parse_live_log(log_text: str, *, scenario_ids: list[str] | None = None) -> dict:
    live = _empty_live_status()
    lines = [line for line in log_text.splitlines() if line.strip()]
    if not lines:
        return live

    parsed = parse_runtime_log(log_text, scenario_ids=scenario_ids or [])
    current_scenario = _string_or_none(parsed.get("current_scenario"))
    current_step = parsed.get("current_step")
    scenario_state = _scenario_state(parsed.get("scenario_progress"), current_scenario)
    live["current"].update({
        "current_scenario_id": current_scenario,
        "current_scenario_name": current_scenario,
        "current_scenario_state": scenario_state,
        "latest_scenario_event": scenario_state,
        "current_step_index": current_step if isinstance(current_step, int) else None,
    })
    observed_step_count = _observed_step_count(lines)
    observed_runtime_events = _count_runtime_events(lines)
    tail_observed_ids = _observed_scenario_ids(lines)
    selected_scenarios = len(scenario_ids or [])
    live["progress"].update({
        "selected_scenarios": selected_scenarios,
        "observed_scenarios": len(tail_observed_ids),
        "tail_observed_scenarios": len(tail_observed_ids),
        "total_scenarios": selected_scenarios,
        "completed_scenarios": int(parsed.get("completed_scenarios") or 0),
        "executed_scenarios": int(parsed.get("executed_scenarios") or 0),
        "not_available_scenarios": int(parsed.get("not_available_scenarios") or 0),
        "not_available_candidate_scenarios": int(parsed.get("not_available_candidate_scenarios") or 0),
        "no_target_candidate_scenarios": int(parsed.get("no_target_candidate_scenarios") or 0),
        "availability_candidate_scenarios": int(parsed.get("availability_candidate_scenarios") or 0),
        "passed_scenarios": int(parsed.get("passed_scenarios") or 0),
        "failed_scenarios": int(parsed.get("failed_scenarios") or 0),
        "warning_scenarios": int(parsed.get("warning_scenarios") or 0),
        "observed_runtime_events": observed_runtime_events,
        "observed_steps": observed_step_count,
        "total_steps": max(int(parsed.get("total_step_count") or 0), observed_step_count),
        "completed_steps": _count_lines(lines, "[STEP] END"),
    })
    live["progress"]["completed_scenarios"] = int(
        parsed.get("completed_or_terminal_scenarios")
        or (
            live["progress"]["passed_scenarios"]
            + live["progress"]["warning_scenarios"]
            + live["progress"]["failed_scenarios"]
        )
        or 0
    )

    for line in lines:
        if _is_step_status_line(line):
            step_value = _extract_step_value(line)
            if step_value is not None:
                live["current"]["current_step_index"] = step_value
            live["current"]["current_step_label"] = _extract_first_group(CURRENT_STEP_LABEL_RE, line) or live["current"]["current_step_label"]
            live["current"]["current_step_action"] = _extract_first_group(CURRENT_STEP_ACTION_RE, line) or live["current"]["current_step_action"]
            live["current"]["current_step_target"] = _extract_first_group(CURRENT_STEP_TARGET_RE, line) or live["current"]["current_step_target"]
            live["current"]["current_step_result"] = (
                _extract_first_group(CURRENT_FINAL_RESULT_RE, line)
                or _extract_first_group(CURRENT_STEP_RESULT_RE, line)
                or live["current"]["current_step_result"]
            )
            live["current"]["current_navigation_result"] = (
                _extract_first_group(SMART_NAV_RESULT_RE, line)
                or _extract_first_group(CURRENT_STEP_RESULT_RE, line)
                or live["current"]["current_navigation_result"]
            )
            live["current"]["current_navigation_detail"] = (
                _extract_first_group(SMART_NAV_DETAIL_RE, line)
                or live["current"]["current_navigation_detail"]
            )
            live["current"]["latest_step_log"] = _trim_line(line)
            live["current"]["current_step_log"] = live["current"]["latest_step_log"]
        if _is_runtime_event_line(line):
            live["current"]["latest_runtime_event"] = _trim_line(line)
        scenario_event = _scenario_event_from_line(line)
        if scenario_event:
            live["current"]["latest_scenario_event"] = scenario_event
        if "[PREFLIGHT]" in line or "[QA_FRONTEND][preflight]" in line:
            _update_preflight_status(live["logs"]["latest_preflight_status"], line)
            live["logs"]["latest_preflight_status"]["last"] = _trim_line(line)
        if "[QUALITY]" in line:
            live["logs"]["latest_quality_event"] = _trim_line(line)
        result = _extract_first_group(CURRENT_FINAL_RESULT_RE, line)
        if result:
            normalized = result.upper()
            if normalized == "PASS":
                live["progress"]["pass_count"] += 1
            elif normalized == "WARN":
                live["progress"]["warn_count"] += 1
            elif normalized == "FAIL":
                live["progress"]["fail_count"] += 1
            elif normalized == "REVIEW":
                live["progress"]["review_count"] += 1

    live["logs"]["latest_log_line"] = _trim_line(lines[-1])
    if parsed.get("preflight_state") and not live["logs"]["latest_preflight_status"].get("last"):
        live["logs"]["latest_preflight_status"]["last"] = str(parsed["preflight_state"])
    return live


def _update_preflight_status(target: dict, line: str) -> None:
    match = PREFLIGHT_STEP_RE.search(line)
    if match:
        key = "screen_awake" if match.group(1) == "wake_screen" else match.group(1)
        target[key] = match.group(2)
    if "[PREFLIGHT][accessibility]" in line:
        target["helper"] = "PASS" if "helper_ready=true" in line else "WARN"
    talkback_match = TALKBACK_STATUS_RE.search(line)
    if talkback_match:
        target["talkback"] = talkback_match.group(1)
    if "[QA_FRONTEND][preflight][adb]" in line:
        target["device_connected"] = _status_from_qa_frontend_line(line)
    if "[QA_FRONTEND][preflight][helper]" in line:
        target["helper"] = _status_from_qa_frontend_line(line)
    if "[QA_FRONTEND][preflight][talkback]" in line:
        target["talkback"] = _status_from_qa_frontend_line(line)
    if "[QA_FRONTEND][preflight][launch_app]" in line and "foreground_package" in line:
        target["app_foreground"] = "observed"


def _status_from_qa_frontend_line(line: str) -> str | None:
    match = re.search(r"status='([^']*)'", line)
    return match.group(1) if match else None


def _device_runner_log_path(device: dict | None) -> Path | None:
    if not device:
        return None
    output_dir = str(device.get("output_dir") or "")
    if not output_dir:
        return None
    return ROOT_DIR / output_dir / "runner.log"


def _read_log_tail(path: Path | None, *, limit: int = 128 * 1024) -> str:
    if not path or not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _relative_path(path: Path | None) -> str | None:
    if not path:
        return None
    return str(path.relative_to(ROOT_DIR)) if path.is_relative_to(ROOT_DIR) else str(path)


def _extract_step_value(line: str) -> int | None:
    match = re.search(r"step=(\d+)", line)
    return int(match.group(1)) if match else None


def _is_step_status_line(line: str) -> bool:
    return (
        "[STEP]" in line
        or "[STOP][eval]" in line
        or ("[SCENARIO][pre_nav]" in line and "step=" in line)
    )


def _is_runtime_event_line(line: str) -> bool:
    if "[QUALITY]" in line:
        return False
    return (
        "[STEP]" in line
        or "[STOP][eval]" in line
        or "[SCENARIO]" in line
        or "[TAB]" in line
        or "final_result=" in line
        or "move_failed" in line
        or "global_nav_main failed" in line
    )


def _scenario_event_from_line(line: str) -> str | None:
    if "[QUALITY]" in line:
        return None
    result = _extract_first_group(CURRENT_FINAL_RESULT_RE, line)
    if result:
        return result.lower()
    lowered = line.lower()
    if " failed" in lowered or "failed " in lowered or "fail_stuck" in lowered:
        return "failed"
    if " warning" in lowered or "warn" in lowered:
        return "warning"
    if " success" in lowered or "passed" in lowered:
        return "pass"
    if "[scenario]" in lowered:
        return "observed"
    return None


def _scenario_state(scenario_progress: object, scenario_id: str | None) -> str | None:
    if not scenario_id or not isinstance(scenario_progress, list):
        return None
    for item in scenario_progress:
        if isinstance(item, dict) and item.get("id") == scenario_id:
            return _string_or_none(item.get("status"))
    return None


def _extract_first_group(pattern: re.Pattern[str], line: str) -> str | None:
    match = pattern.search(line)
    if not match:
        return None
    for value in match.groups():
        if value not in {None, ""}:
            return value
    return None


def _count_lines(lines: list[str], token: str) -> int:
    return sum(1 for line in lines if token in line)


def _observed_step_count(lines: list[str]) -> int:
    observed_steps = [
        step
        for line in lines
        if _is_step_status_line(line)
        for step in [_extract_step_value(line)]
        if step is not None
    ]
    if observed_steps:
        return max(observed_steps) + 1
    return sum(1 for line in lines if _is_step_status_line(line))


def _count_runtime_events(lines: list[str]) -> int:
    return sum(1 for line in lines if _is_runtime_event_line(line))


def _observed_scenario_ids(lines: list[str]) -> set[str]:
    return {
        scenario
        for line in lines
        if _is_scenario_observation_line(line)
        for scenario in [_extract_scenario_id(line)]
        if scenario
    }


def _is_scenario_observation_line(line: str) -> bool:
    if line.startswith("[CONFIG]") or "source='runtime'" in line or "base_enabled=" in line:
        return False
    return (
        "[STEP]" in line
        or "[STOP][eval]" in line
        or "[SCENARIO][entry_contract]" in line
        or "[SCENARIO][pre_nav]" in line
        or "[PERF][scenario_summary]" in line
        or "scenario_result" in line
    )


def _extract_scenario_id(line: str) -> str | None:
    match = re.search(r"scenario='([^']+)'|scenario=([A-Za-z0-9_]+)|scenario_id='([^']+)'|scenario_id=([A-Za-z0-9_]+)", line)
    if not match:
        return None
    for value in match.groups():
        if value:
            return value
    return None


def _string_or_none(value: object) -> str | None:
    return str(value) if value not in {None, ""} else None


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _trim_line(value: str, limit: int = 300) -> str:
    return value if len(value) <= limit else f"{value[:limit - 3]}..."


def _normalize_batch_state(state: str | None) -> str:
    if state == "error":
        return "failed"
    return state or "idle"

class BatchRunManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._batch_id = None
        self._state = "idle"  # idle, running, finished, error
        self._mode = None
        self._created_at = None
        self._devices = []
        self._current_device_idx = -1
        self._worker_thread = None
        self._stop_requested = False
        self._current_execution: RunExecution | None = None
        self._shadow_validation_requested = False

    def _sanitize_name(self, name: str) -> str:
        return re.sub(r'[^0-9a-zA-Z_-]+', '_', name)

    def start_batch(self, devices: list[dict], mode: str, launch_mode: str = "clean", language_mode: str = "current", scenario_ids: list[str] | None = None, enable_coverage_probe: bool = False, shadow_validation: bool = False) -> dict:
        with self._lock:
            if self._state == "running":
                raise RuntimeError("Batch run is already in progress")

            self._batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self._state = "running"
            self._stop_requested = False
            self._current_execution = None
            self._mode = mode
            self._launch_mode = normalize_launch_mode(launch_mode)
            self._language_mode = normalize_language_mode(language_mode)
            self._scenario_ids = scenario_ids or []
            self._enable_coverage_probe = enable_coverage_probe
            self._shadow_validation_requested = (
                shadow_validation is True and str(mode).lower() == "full"
            )
            self._created_at = datetime.now(timezone.utc).isoformat()
            
            batch_dir = RUN_LOG_DIR / self._batch_id
            batch_dir.mkdir(parents=True, exist_ok=True)
            
            self._devices = []
            for d in devices:
                safe_model = self._sanitize_name(d.get("model", "unknown"))
                safe_serial = self._sanitize_name(d.get("serial", "unknown"))
                dev_dir = batch_dir / f"device_{safe_model}_{safe_serial}"
                
                self._devices.append({
                    "serial": d.get("serial"),
                    "model": d.get("model"),
                    "state": "pending",
                    "output_dir": str(dev_dir.relative_to(ROOT_DIR)) if dev_dir.is_relative_to(ROOT_DIR) else str(dev_dir),
                    "return_code": None,
                    "started_at": None,
                    "finished_at": None,
                    "observed_scenario_ids": [],
                })
            
            self._current_device_idx = 0
            self._write_summary_locked()
            
            self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
            self._worker_thread.start()
            
            return self.get_status_locked()

    def stop_batch(self) -> dict:
        execution = None
        worker_thread = None
        with self._lock:
            if self._state != "running":
                return self.get_status_locked()
            self._stop_requested = True
            self._state = "stopped"
            execution = self._current_execution
            worker_thread = self._worker_thread
            self._write_summary_locked()

        process = execution.process if execution is not None else None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
        if worker_thread is not None and worker_thread is not threading.current_thread():
            worker_thread.join(timeout=15.0)
        return self.get_status()

    def get_status(self) -> dict:
        with self._lock:
            return self.get_status_locked()
            
    def get_status_locked(self) -> dict:
        current_serial = None
        current_device = None
        if 0 <= self._current_device_idx < len(self._devices):
            current_device = self._devices[self._current_device_idx]
            current_serial = current_device["serial"]

        device_statuses = [self._device_status_with_live_summary(device) for device in self._devices]
        if current_device:
            current_live = self._live_status_for_device(current_device)
        elif device_statuses:
            current_live = {
                "runner_log_path": device_statuses[-1].get("runner_log_path"),
                "current": _dict(device_statuses[-1].get("current")),
                "progress": _dict(device_statuses[-1].get("progress")),
                "logs": _dict(device_statuses[-1].get("logs")),
            }
        else:
            current_live = _empty_live_status()
        finished_devices = [device for device in device_statuses if device.get("state") in {"passed", "failed", "skipped", "error", "stopped"}]
        passed_devices = [device for device in device_statuses if device.get("state") == "passed"]
        failed_devices = [device for device in device_statuses if device.get("state") in {"failed", "error"}]
        warning_devices = [
            device for device in device_statuses
            if int(_dict(device.get("progress")).get("warning_scenarios") or 0) > 0
        ]
        status = {
            "batch_id": self._batch_id,
            "state": self._state,
            "mode": self._mode,
            "current_device": current_serial,
            "devices": device_statuses,
            "batch": {
                "batch_id": self._batch_id,
                "state": _normalize_batch_state(self._state),
                "started_at": self._created_at,
                "finished_at": self._batch_finished_at(device_statuses),
                "total_devices": len(device_statuses),
                "finished_devices": len(finished_devices),
                "passed_devices": len(passed_devices),
                "failed_devices": len(failed_devices),
                "warning_devices": len(warning_devices),
            },
            "current": current_live["current"],
            "progress": current_live["progress"],
            "logs": current_live["logs"],
        }
        return status

    def _device_status_with_live_summary(self, device: dict) -> dict:
        item = dict(device)
        live = self._live_status_for_device(device)
        item["runner_log_path"] = live.get("runner_log_path")
        item["current"] = live["current"]
        item["progress"] = live["progress"]
        item["logs"] = live["logs"]
        return item

    def _live_status_for_device(self, device: dict | None) -> dict:
        if not device:
            return _empty_live_status()
        log_path = _device_runner_log_path(device)
        log_text = _read_log_tail(log_path)
        parsed = _parse_live_log(log_text, scenario_ids=self._scenario_ids)
        observed_ids = self._accumulate_observed_scenario_ids(device, _observed_scenario_ids(log_text.splitlines()))
        parsed["progress"]["observed_scenarios"] = len(observed_ids)
        return {
            **parsed,
            "runner_log_path": _relative_path(log_path) if log_path else None,
            "current": {
                **parsed["current"],
                "current_device_serial": device.get("serial"),
                "current_device_model": device.get("model"),
                "current_device_state": device.get("state"),
                "current_scenario_runtime_state": self._scenario_runtime_state(device, parsed["current"]),
            },
        }

    @staticmethod
    def _scenario_runtime_state(device: dict | None, current: dict) -> str | None:
        if not current.get("current_scenario_id"):
            return None
        device_state = str((device or {}).get("state") or "")
        if device_state in {"running", "pending"}:
            return "running"
        if device_state in {"passed", "failed", "skipped", "error", "stopped"}:
            return "finished"
        return device_state or None

    def _observed_scenario_id_list(self, device: dict | None) -> list[str]:
        if not device:
            return []
        observed = device.get("observed_scenario_ids")
        return [str(item) for item in observed] if isinstance(observed, list) else []

    def _accumulate_observed_scenario_ids(self, device: dict, tail_ids: set[str]) -> list[str]:
        selected_ids = [str(item) for item in (self._scenario_ids or [])]
        selected_set = set(selected_ids)
        combined = set(self._observed_scenario_id_list(device))
        for scenario_id in tail_ids:
            if not selected_set or scenario_id in selected_set:
                combined.add(scenario_id)
        ordered = [scenario_id for scenario_id in selected_ids if scenario_id in combined]
        ordered.extend(sorted(scenario_id for scenario_id in combined if scenario_id not in set(ordered)))
        device["observed_scenario_ids"] = ordered
        return ordered

    def _mark_all_scenarios_observed(self, device: dict) -> None:
        if self._scenario_ids:
            device["observed_scenario_ids"] = [str(item) for item in self._scenario_ids]

    def _is_stop_requested(self) -> bool:
        with self._lock:
            return bool(self._stop_requested)

    def _mark_device_stopped_locked(self, device: dict) -> None:
        device["state"] = "stopped"
        device["error"] = "Batch stop requested"
        device["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._state = "stopped"
        self._current_device_idx = len(self._devices)
        self._write_summary_locked()

    @staticmethod
    def _batch_finished_at(devices: list[dict]) -> str | None:
        finished = [str(device.get("finished_at") or "") for device in devices if device.get("finished_at")]
        return max(finished) if finished else None

    def _write_summary_locked(self):
        if not self._batch_id:
            return
        summary_path = RUN_LOG_DIR / self._batch_id / "batch_summary.json"
        data = {
            "batch_id": self._batch_id,
            "mode": self._mode,
            "created_at": self._created_at,
            "state": self._state,
            "enable_coverage_probe": self._enable_coverage_probe,
            "shadow_validation": self._shadow_validation_requested,
            "devices": self._devices
        }
        try:
            summary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Failed to write batch_summary.json: {e}")

    def _write_device_summary(self, device_info, dev_output_dir):
        try:
            out_dir = Path(dev_output_dir)
            log_path = None
            xlsx_path = None
            runner_log_path = None
            if out_dir.is_dir():
                runner_log_file = out_dir / "runner.log"
                if runner_log_file.is_file():
                    runner_log_path = str(runner_log_file.relative_to(ROOT_DIR)) if runner_log_file.is_relative_to(ROOT_DIR) else str(runner_log_file)
                for f in out_dir.iterdir():
                    if f.is_file():
                        if f.name.endswith(".xlsx"):
                            xlsx_path = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                        elif f.name.endswith(".log") and ".normal" in f.name:
                            log_path = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                if not log_path and out_dir.is_dir():
                    for f in out_dir.iterdir():
                        if f.is_file() and f.name.endswith(".log") and f.name != "runner.log":
                            log_path = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                            break
            
            data = {}
            summary_path = out_dir / "summary.json"
            if summary_path.is_file():
                try:
                    data = json.loads(summary_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            parsed_summary = {}
            if log_path:
                abs_log_path = ROOT_DIR / log_path
                if abs_log_path.exists():
                    try:
                        from .run_summary import build_run_summary
                        parsed_summary = build_run_summary(
                            status={"state": device_info.get("state")},
                            log_path=abs_log_path,
                            scenario_ids=self._scenario_ids
                        )
                    except Exception as e:
                        print(f"Failed to parse log for summary: {e}")

            quality = parsed_summary.get("quality")
            if quality is None and xlsx_path:
                try:
                    from .mismatch_viewer import get_mismatch_summary_from_xlsx
                    mismatch_res = get_mismatch_summary_from_xlsx(ROOT_DIR / xlsx_path)
                    if "error" not in mismatch_res and "summary" in mismatch_res:
                        msummary = mismatch_res["summary"]
                        quality = {
                            "fail": msummary.get("fail_count", 0),
                            "issue": msummary.get("issue_count", 0),
                            "review": msummary.get("review_count", 0),
                            "clean": msummary.get("clean_count", 0)
                        }
                        data["shadow_quality"] = {
                            "pass": msummary.get("shadow_pass_count", 0),
                            "review": msummary.get("shadow_review_count", 0),
                            "warn": msummary.get("shadow_warn_count", 0),
                            "fail": msummary.get("shadow_fail_count", 0),
                        }
                        data["shadow_scenarios"] = [
                            {
                                "scenario_id": item.get("scenario_id", ""),
                                "scenario_shadow_verdict": item.get("scenario_shadow_verdict", ""),
                                "shadow_pass_count": item.get("shadow_pass_count", 0),
                                "shadow_review_count": item.get("shadow_review_count", 0),
                                "shadow_warn_count": item.get("shadow_warn_count", 0),
                                "shadow_fail_count": item.get("shadow_fail_count", 0),
                                "focusable_required_missed": item.get("focusable_required_missed", 0),
                                "focusable_review_unknown": item.get("focusable_review_unknown", 0),
                                "focusable_coverage_rate": item.get("focusable_coverage_rate"),
                            }
                            for item in mismatch_res.get("scenario_summary", [])
                        ]
                        data["focusable_coverage"] = mismatch_res.get("focusable_coverage")
                        data["focusable_issues"] = (mismatch_res.get("focusable_coverage") or {}).get("issues", [])
                        coverage_probe_summary = mismatch_res.get("coverage_probe_summary", mismatch_res.get("coverage_probe"))
                        data["coverage_probe_summary"] = coverage_probe_summary
                        data["coverage_probe"] = coverage_probe_summary
                        
                        quality_issues = []
                        for sig in mismatch_res.get("signals", []):
                            crop_thumb = sig.get("crop_thumbnail")
                            crop_path = None
                            if crop_thumb and xlsx_path:
                                compare_dir = Path(xlsx_path).with_suffix("")
                                crop_path = f"{compare_dir.as_posix()}/crops/{crop_thumb}"
                            
                            quality_issues.append({
                                "scenario_id": sig.get("scenario_id", ""),
                                "step": sig.get("step", ""),
                                "context_type": sig.get("context_type", ""),
                                "visible_label": sig.get("visible_label", ""),
                                "merged_announcement": sig.get("merged_announcement", ""),
                                "mismatch_type": sig.get("mismatch_type", ""),
                                "final_result": sig.get("final_result", ""),
                                "review_note": sig.get("review_note", ""),
                                "focus_confidence": sig.get("focus_confidence", ""),
                                "repeat_count": sig.get("repeat_count", 1),
                                "first_step": sig.get("first_step", ""),
                                "last_step": sig.get("last_step", ""),
                                "steps": sig.get("steps", ""),
                                "is_repeated_issue_group": sig.get("is_repeated_issue_group", False),
                                "shadow_verdict": sig.get("shadow_verdict", ""),
                                "shadow_verdict_reason": sig.get("shadow_verdict_reason", ""),
                                "shadow_verdict_source": sig.get("shadow_verdict_source", ""),
                                "scenario_shadow_verdict": sig.get("scenario_shadow_verdict", ""),
                                "crop_path": crop_path
                            })
                        data["quality_issues"] = quality_issues
                        
                except Exception as e:
                    print(f"Failed to extract quality from xlsx: {e}")

            if xlsx_path and "coverage_probe_summary" not in data:
                try:
                    from .mismatch_viewer import get_mismatch_summary_from_xlsx
                    mismatch_res = get_mismatch_summary_from_xlsx(ROOT_DIR / xlsx_path)
                    if "error" not in mismatch_res:
                        coverage_probe_summary = mismatch_res.get(
                            "coverage_probe_summary",
                            mismatch_res.get("coverage_probe"),
                        )
                        data["coverage_probe_summary"] = coverage_probe_summary
                        data["coverage_probe"] = coverage_probe_summary
                except Exception as e:
                    print(f"Failed to extract coverage probe summary from xlsx: {e}")

            data.update({
                "batch_id": self._batch_id,
                "serial": device_info.get("serial"),
                "model": device_info.get("model"),
                "state": device_info.get("state"),
                "output_dir": device_info.get("output_dir"),
                "return_code": device_info.get("return_code"),
                "started_at": device_info.get("started_at"),
                "finished_at": device_info.get("finished_at"),
                "runner_log_path": runner_log_path,
                "log_path": log_path,
                "xlsx_path": xlsx_path,
                "enable_coverage_probe": self._enable_coverage_probe,
                "shadow_validation": self._shadow_validation_requested,
                "quality": quality,
                "scenarios": parsed_summary.get("scenarios", []),
                "process_status": parsed_summary.get("process_status"),
                "scenario_result_status": parsed_summary.get("scenario_result_status"),
                "passed_scenarios": parsed_summary.get("passed_scenarios", 0),
                "warning_scenarios": parsed_summary.get("warning_scenarios", 0),
                "completed_scenarios": parsed_summary.get("completed_scenarios", 0),
                "executed_scenarios": parsed_summary.get("executed_scenarios", 0),
                "not_available_scenarios": parsed_summary.get("not_available_scenarios", 0),
                "not_available_candidate_scenarios": parsed_summary.get("not_available_candidate_scenarios", 0),
                "no_target_candidate_scenarios": parsed_summary.get("no_target_candidate_scenarios", 0),
                "availability_candidate_scenarios": parsed_summary.get("availability_candidate_scenarios", 0),
                "failed_scenarios": parsed_summary.get("failed_scenarios", 0)
            })
            safe_data = _json_safe(data)
            summary_path.write_text(json.dumps(safe_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            err_text = traceback.format_exc()
            print(f"Failed to write device summary.json: {e}")
            try:
                out_dir = Path(dev_output_dir)
                runner_log = out_dir / "runner.log"
                if runner_log.is_file():
                    with runner_log.open("a", encoding="utf-8", errors="replace") as f:
                        f.write("\n[SUMMARY ERROR] Failed to write device summary.json\n")
                        f.write(err_text)
                        f.write("\n")
                
                fallback_data = {
                    "summary_error": True,
                    "summary_error_message": str(e),
                    "batch_id": self._batch_id,
                    "serial": device_info.get("serial"),
                    "model": device_info.get("model"),
                    "state": device_info.get("state"),
                    "return_code": device_info.get("return_code", 0),
                    "output_dir": device_info.get("output_dir"),
                    "log_path": None,
                    "xlsx_path": None,
                    "quality": None,
                    "quality_issues": [],
                    "scenarios": []
                }
                summary_path = out_dir / "summary.json"
                summary_path.write_text(json.dumps(fallback_data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _run_loop(self):
        while True:
            with self._lock:
                if self._stop_requested:
                    self._state = "stopped"
                    self._write_summary_locked()
                    break
                if self._current_device_idx >= len(self._devices):
                    if self._state != "stopped":
                        self._state = "finished"
                    self._write_summary_locked()
                    break
                device_info = self._devices[self._current_device_idx]
                device_info["state"] = "running"
                device_info["started_at"] = datetime.now(timezone.utc).isoformat()
                self._write_summary_locked()
            
            dev_serial = device_info["serial"]
            dev_output_dir_rel = device_info["output_dir"]
            dev_output_dir = str(ROOT_DIR / dev_output_dir_rel)
            
            Path(dev_output_dir).mkdir(parents=True, exist_ok=True)
            
            log_path = Path(dev_output_dir) / "runner.log"
            log_file = log_path.open("w", encoding="utf-8", errors="replace")
            crash_capture = None
            sleep_prevention_enabled = False
            device_stay_awake_state = None
            execution = None

            def crash_log(line: str) -> None:
                log_file.write(f"{line}\n")
                log_file.flush()

            def restore_keep_awake() -> None:
                nonlocal device_stay_awake_state
                state = device_stay_awake_state
                device_stay_awake_state = None
                if state is None:
                    return
                result = restore_device_stay_awake(state)
                crash_log(
                    "[QA_FRONTEND][keep_awake] "
                    f"restored={result.get('original_setting')} "
                    f"ok='{str(bool(result.get('ok'))).lower()}' "
                    f"restored_ok='{str(bool(result.get('restored'))).lower()}' "
                    f"serial='{dev_serial}' reason='{result.get('reason', '')}' "
                    f"error='{result.get('error', '')}'"
                )
            
            try:
                enable_sleep_prevention()
                sleep_prevention_enabled = True
                device_stay_awake_state = enable_device_stay_awake(serial=dev_serial)
                crash_log(
                    "[QA_FRONTEND][keep_awake] "
                    f"original={device_stay_awake_state.get('original_setting')} "
                    f"serial='{dev_serial}'"
                )
                crash_log(
                    "[QA_FRONTEND][keep_awake] "
                    f"applied={device_stay_awake_state.get('applied_setting')} "
                    f"ok='{str(bool(device_stay_awake_state.get('ok'))).lower()}' "
                    f"serial='{dev_serial}' command='{device_stay_awake_state.get('command', '')}' "
                    f"error='{device_stay_awake_state.get('error', '')}'"
                )
                crash_capture = start_crash_logcat_capture(
                    serial=dev_serial,
                    output_dir=Path(dev_output_dir),
                    runner_log_path=log_path,
                    log_writer=crash_log,
                )
                # 1. Config copy
                runtime_config = write_selected_runtime_config(
                    source_path=RUNTIME_CONFIG_PATH,
                    output_path=Path(dev_output_dir) / "runtime_config.json",
                    scenario_ids=self._scenario_ids,
                    mode=self._mode,
                    shadow_validation=self._shadow_validation_requested,
                )
                log_file.write(f"[BATCH] Config generated for {dev_serial}\n")
                log_file.flush()
                spec = RunSpec(
                    serial=dev_serial,
                    mode=self._mode,
                    language_mode=self._language_mode,
                    launch_mode=self._launch_mode,
                    scenario_ids=tuple(self._scenario_ids),
                    output_dir=dev_output_dir,
                    runtime_config_path=str(runtime_config["path"]),
                    enable_coverage_probe=self._enable_coverage_probe,
                )
                language_status, preflight = prepare_runtime(
                    spec,
                    language_fn=apply_language_mode,
                    preflight_fn=run_runtime_preflight,
                )
                for line in format_language_log_lines(language_status):
                    log_file.write(f"{line}\n")
                if not language_status.get("ok"):
                    raise Exception(f"Language setup failed: {language_status}")
                    
                assert preflight is not None
                for line in format_preflight_log_lines(preflight):
                    log_file.write(f"{line}\n")
                if not preflight.get("ok"):
                    raise Exception(f"Preflight blocked: {preflight.get('reason')}")

                if self._is_stop_requested():
                    log_file.write("\n[BATCH] stop_requested before execution\n")
                    log_file.flush()
                    with self._lock:
                        self._mark_device_stopped_locked(device_info)
                    self._write_device_summary(device_info, dev_output_dir)
                    stop_crash_logcat_capture(crash_capture, log_writer=crash_log)
                    crash_capture = None
                    restore_keep_awake()
                    disable_sleep_prevention()
                    sleep_prevention_enabled = False
                    log_file.close()
                    break
                
            except Exception as e:
                with self._lock:
                    if self._stop_requested:
                        self._mark_device_stopped_locked(device_info)
                    else:
                        device_info["state"] = "failed"
                        device_info["error"] = f"Setup error: {str(e)}"
                        device_info["finished_at"] = datetime.now(timezone.utc).isoformat()
                        self._current_device_idx += 1
                        self._write_summary_locked()
                self._write_device_summary(device_info, dev_output_dir)
                log_file.write(f"\n[BATCH ERROR] {e}\n")
                stop_crash_logcat_capture(crash_capture, log_writer=crash_log)
                crash_capture = None
                restore_keep_awake()
                disable_sleep_prevention()
                sleep_prevention_enabled = False
                log_file.close()
                if self._is_stop_requested():
                    break
                continue

            try:
                if self._is_stop_requested():
                    log_file.write("\n[BATCH] stop_requested before start_execution\n")
                    log_file.flush()
                    with self._lock:
                        self._mark_device_stopped_locked(device_info)
                    self._write_device_summary(device_info, dev_output_dir)
                    break
                execution = start_execution(
                    spec=spec,
                    script_path=SCRIPT_PATH,
                    cwd=ROOT_DIR,
                    log_file=log_file,
                    log_path=log_path,
                    popen_factory=subprocess.Popen,
                )
                with self._lock:
                    self._current_execution = execution
                returncode = wait_for_execution(execution)
                with self._lock:
                    if self._current_execution is execution:
                        self._current_execution = None
                stop_crash_logcat_capture(crash_capture, log_writer=crash_log)
                crash_capture = None

                if (
                    self._shadow_validation_requested
                    and self._mode == "full"
                    and not self._is_stop_requested()
                ):
                    try:
                        shadow_result = run_shadow_validation_pipeline(
                            runtime_config_path=str(runtime_config["path"]),
                            requested=True,
                            output_dir=dev_output_dir,
                            scenario_ids=self._scenario_ids,
                            serial=dev_serial,
                            run_id=str(self._batch_id or ""),
                            device_name=str(device_info.get("model") or ""),
                        )
                        crash_log(
                            "[QA_FRONTEND][shadow] "
                            f"status='{shadow_result.get('status', 'unknown')}' "
                            f"artifact_dir='{shadow_result.get('artifact_dir', '')}' "
                            f"warning='{shadow_result.get('warning', '')}' "
                            "legacy_result_preserved=true"
                        )
                    except Exception as shadow_exc:
                        crash_log(
                            "[QA_FRONTEND][shadow] status='warning' "
                            f"error='{shadow_exc}' legacy_result_preserved=true"
                        )
                
                try:
                    file_size = log_path.stat().st_size
                    log_file.write(f"\n[BATCH] runner.log flushed bytes={file_size}\n")
                    log_file.flush()
                except Exception:
                    pass
                
                with self._lock:
                    if self._stop_requested:
                        self._mark_device_stopped_locked(device_info)
                    else:
                        device_info["state"] = "passed" if returncode == 0 else "failed"
                        device_info["return_code"] = returncode
                        device_info["finished_at"] = datetime.now(timezone.utc).isoformat()
                        if returncode == 0:
                            self._mark_all_scenarios_observed(device_info)
                        self._current_device_idx += 1
                        self._write_summary_locked()
                    device_info["return_code"] = returncode
                self._write_device_summary(device_info, dev_output_dir)
                restore_keep_awake()
                close_execution_log(execution)
                disable_sleep_prevention()
                sleep_prevention_enabled = False
                if self._is_stop_requested():
                    break
                    
            except Exception as e:
                stop_crash_logcat_capture(crash_capture, log_writer=crash_log)
                crash_capture = None
                with self._lock:
                    if execution is not None and self._current_execution is execution:
                        self._current_execution = None
                    if self._stop_requested:
                        self._mark_device_stopped_locked(device_info)
                    else:
                        device_info["state"] = "failed"
                        device_info["error"] = str(e)
                        device_info["finished_at"] = datetime.now(timezone.utc).isoformat()
                        self._current_device_idx += 1
                        self._write_summary_locked()
                self._write_device_summary(device_info, dev_output_dir)
                log_file.write(f"\n[BATCH ERROR] {e}\n")
                if self._is_stop_requested():
                    break
            finally:
                with self._lock:
                    if execution is not None and self._current_execution is execution:
                        self._current_execution = None
                stop_crash_logcat_capture(crash_capture, log_writer=crash_log)
                restore_keep_awake()
                if sleep_prevention_enabled:
                    disable_sleep_prevention()
                if not log_file.closed:
                    log_file.close()

global_batch_manager = BatchRunManager()


def get_recent_batches() -> list[dict]:
    batches = []
    if not RUN_LOG_DIR.exists():
        return batches
        
    for batch_dir in sorted(RUN_LOG_DIR.iterdir(), reverse=True):
        if not batch_dir.is_dir() or not batch_dir.name.startswith("batch_"):
            continue
            
        summary_path = batch_dir / "batch_summary.json"
        if not summary_path.exists():
            continue
            
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            devices = data.get("devices", [])
            passed_count = sum(1 for d in devices if d.get("state") == "passed")
            failed_count = sum(1 for d in devices if d.get("state") in ("failed", "error"))
            devices_info = []
            for d in devices:
                out_dir_str = d.get("output_dir")
                dev_info = {
                    "serial": d.get("serial"),
                    "model": d.get("model"),
                    "state": d.get("state"),
                    "return_code": d.get("return_code"),
                    "log_path": None,
                    "xlsx_path": None,
                    "quality": None
                }
                if out_dir_str:
                    out_dir = ROOT_DIR / out_dir_str
                    if out_dir.is_dir():
                        runner_log_file = out_dir / "runner.log"
                        if runner_log_file.is_file():
                            dev_info["runner_log_path"] = str(runner_log_file.relative_to(ROOT_DIR)) if runner_log_file.is_relative_to(ROOT_DIR) else str(runner_log_file)
                        for f in out_dir.iterdir():
                            if f.is_file():
                                if f.name.endswith(".xlsx"):
                                    dev_info["xlsx_path"] = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                                elif f.name.endswith(".log") and ".normal" in f.name:
                                    dev_info["log_path"] = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                        if not dev_info.get("log_path") and out_dir.is_dir():
                            for f in out_dir.iterdir():
                                if f.is_file() and f.name.endswith(".log") and f.name != "runner.log":
                                    dev_info["log_path"] = str(f.relative_to(ROOT_DIR)) if f.is_relative_to(ROOT_DIR) else str(f)
                                    break
                        
                        dev_summary_path = out_dir / "summary.json"
                        if dev_summary_path.exists():
                            try:
                                dev_data = json.loads(dev_summary_path.read_text(encoding="utf-8"))
                                dev_info["quality"] = dev_data.get("quality")
                                dev_info["shadow_quality"] = dev_data.get("shadow_quality")
                                dev_info["shadow_scenarios"] = dev_data.get("shadow_scenarios")
                                dev_info["quality_issues"] = dev_data.get("quality_issues")
                                dev_info["focusable_coverage"] = dev_data.get("focusable_coverage")
                                dev_info["focusable_issues"] = dev_data.get("focusable_issues")
                                coverage_probe_summary = dev_data.get(
                                    "coverage_probe_summary",
                                    dev_data.get("coverage_probe"),
                                )
                                dev_info["coverage_probe_summary"] = coverage_probe_summary
                                dev_info["coverage_probe"] = coverage_probe_summary
                                
                                from .recent_runs import _recent_run_from_summary
                                from datetime import datetime
                                parsed = _recent_run_from_summary(
                                    summary=dev_data,
                                    path=dev_summary_path,
                                    run_id=dev_data.get("run_id", "batch"),
                                    mode=dev_data.get("mode", "unknown"),
                                    started_at=datetime.fromtimestamp(dev_summary_path.stat().st_mtime),
                                    modified_at=datetime.fromtimestamp(dev_summary_path.stat().st_mtime),
                                    current_status=None,
                                )
                                dev_info.update(parsed)
                            except Exception:
                                pass
                        coverage_probe_summary = dev_info.get("coverage_probe_summary")
                        needs_probe_summary_refresh = not isinstance(coverage_probe_summary, dict) or (
                            coverage_probe_summary.get("available") is True
                            and "candidate_count" not in coverage_probe_summary
                        )
                        if needs_probe_summary_refresh and dev_info.get("xlsx_path"):
                            try:
                                from .mismatch_viewer import get_mismatch_summary_from_xlsx
                                mismatch_res = get_mismatch_summary_from_xlsx(ROOT_DIR / dev_info["xlsx_path"])
                                if "error" not in mismatch_res:
                                    coverage_probe_summary = mismatch_res.get(
                                        "coverage_probe_summary",
                                        mismatch_res.get("coverage_probe"),
                                    )
                                    dev_info["coverage_probe_summary"] = coverage_probe_summary
                                    dev_info["coverage_probe"] = coverage_probe_summary
                            except Exception:
                                pass
                        coverage_probe_summary = dev_info.get("coverage_probe_summary")
                        if not isinstance(coverage_probe_summary, dict):
                            coverage_probe_summary = {
                                "available": False,
                                "source": "none",
                                "results_artifact": None,
                                "validation_artifact": None,
                            }
                            dev_info["coverage_probe_summary"] = coverage_probe_summary
                            dev_info["coverage_probe"] = coverage_probe_summary
                        if "enable_coverage_probe" in data:
                            coverage_probe_summary["probe_enabled"] = bool(data.get("enable_coverage_probe"))
                devices_info.append(dev_info)

            batches.append({
                "batch_id": data.get("batch_id", batch_dir.name),
                "state": data.get("state", "unknown"),
                "mode": data.get("mode", "unknown"),
                "created_at": data.get("created_at"),
                "duration_seconds": _batch_duration_seconds(
                    data.get("created_at"),
                    BatchRunManager._batch_finished_at(devices),
                ),
                "device_count": len(devices),
                "passed_count": passed_count,
                "failed_count": failed_count,
                "summary_path": str(summary_path.relative_to(ROOT_DIR)) if summary_path.is_relative_to(ROOT_DIR) else str(summary_path),
                "devices": devices_info
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            continue
            
        if len(batches) >= 20:
            break
            
    return batches


def _batch_duration_seconds(started_at: object, finished_at: object) -> int | None:
    if not started_at or not finished_at:
        return None
    try:
        started = datetime.fromisoformat(str(started_at))
        finished = datetime.fromisoformat(str(finished_at))
    except ValueError:
        return None
    return max(0, int((finished - started).total_seconds()))
