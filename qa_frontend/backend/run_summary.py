from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import OUTPUT_DIR
from .runtime_dashboard import parse_runtime_log

SUMMARY_SCHEMA_VERSION = 1
SAVED_EXCEL_PATTERN = re.compile(r"saved excel:\s+output/(?P<filename>[^/\s]+\.xlsx)", re.IGNORECASE)
RUN_LOG_PATTERN = re.compile(r"^(?P<run_id>\d{8}_\d{6})_(?P<mode>smoke|full)\.log$")


def summary_path_for_log(log_path: Path) -> Path:
    match = RUN_LOG_PATTERN.match(log_path.name)
    if match:
        return log_path.with_name(f"{match.group('run_id')}_summary.json")
    return log_path.with_suffix(".summary.json")


def build_run_summary(
    *,
    status: dict[str, object],
    log_path: Path,
    scenario_ids: list[str] | None = None,
) -> dict[str, object]:
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    parsed = _parse_runtime_log_safe(log_text, scenario_ids=scenario_ids)
    process_status = resolve_process_status(status=status, log_text=log_text)
    scenario_result_status = resolve_scenario_result_status(process_status, parsed)
    xlsx_filename = extract_saved_excel_filename(log_text)
    event_counts = _event_counts(parsed)
    warnings = _warnings_from_events(parsed)
    scenarios = _scenario_summaries(parsed)
    started_at = _string_or_none(status.get("started_at"))
    finished_at = _string_or_none(status.get("finished_at"))
    run_id, mode = _run_identity(status=status, log_path=log_path)

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "run_id": run_id,
        "mode": _string_or_none(status.get("mode")) or mode,
        "launch_mode": _string_or_none(status.get("launch_mode")) or parsed.get("launch_mode"),
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": _elapsed_seconds(started_at, finished_at),
        "process_status": process_status,
        "scenario_result_status": scenario_result_status,
        "completed_scenarios": int(parsed.get("completed_scenarios") or 0),
        "failed_scenarios": int(parsed.get("failed_scenarios") or 0),
        "total_scenarios": len(parsed.get("scenario_progress") or []),
        "total_steps": _total_steps(parsed),
        "overlay_count": int(parsed.get("overlay_count") or 0),
        "save_excel_count": int(parsed.get("save_excel_count") or 0),
        "popup_result": status.get("popup_result") or parsed.get("popup_result"),
        "preflight_state": status.get("preflight_state") or parsed.get("preflight_state"),
        "xlsx_path": str(OUTPUT_DIR / xlsx_filename) if xlsx_filename else None,
        "xlsx_filename": xlsx_filename,
        "log_path": str(log_path),
        "log_filename": log_path.name,
        "warnings": warnings,
        "warning_count": len(warnings),
        "event_counts": event_counts,
        "event_warning_count": len(warnings),
        "scenarios": scenarios,
        "parse_error": parsed.get("parse_error"),
    }


def write_summary_file(
    *,
    status: dict[str, object],
    log_path: Path,
    scenario_ids: list[str] | None = None,
    summary_path: Path | None = None,
) -> dict[str, object]:
    summary = build_run_summary(status=status, log_path=log_path, scenario_ids=scenario_ids)
    target = summary_path or summary_path_for_log(log_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp")
    tmp_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(target)
    return summary


def read_summary_file(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        return None
    return payload


def extract_saved_excel_filename(log_text: str) -> str | None:
    matches = SAVED_EXCEL_PATTERN.findall(log_text)
    return matches[-1] if matches else None


def resolve_process_status(*, status: dict[str, object] | None = None, log_text: str = "") -> str:
    current = status or {}
    state = str(current.get("state") or "")
    if state == "running":
        return "running"
    if state == "stopped":
        return "stopped"
    if state == "finished":
        return "success"
    if state == "error":
        return "failed"

    lowered = log_text.lower()
    if "[qa_frontend][run] final_state='stopped'" in lowered or "[qa_frontend][run] stop_requested=true" in lowered:
        return "stopped"
    if "script_test.py exited with code" in lowered:
        return "failed"
    if "reason='talkback_disabled'" in lowered or "reason='helper_not_ready'" in lowered or "reason='external_popup_uncleared'" in lowered:
        return "failed"
    if "reason='no_scenario_selected'" in lowered:
        return "failed"
    if "[main] script end" in lowered:
        return "success"
    return "unknown"


def resolve_scenario_result_status(process_status: str, runtime_summary: dict[str, object]) -> str:
    if process_status == "running":
        return "running"

    completed_scenarios = int(runtime_summary.get("completed_scenarios") or 0)
    failed_scenarios = int(runtime_summary.get("failed_scenarios") or 0)
    total_scenarios = len(runtime_summary.get("scenario_progress") or [])

    if failed_scenarios > 0:
        return "failed"
    if process_status == "stopped" and completed_scenarios > 0:
        return "partial"
    if process_status == "stopped" and completed_scenarios == 0:
        return "stopped"
    if completed_scenarios > 0 and failed_scenarios == 0:
        return "passed"
    if process_status == "failed" and total_scenarios > 0:
        return "failed"
    return "unknown"


def _parse_runtime_log_safe(log_text: str, *, scenario_ids: list[str] | None) -> dict[str, object]:
    try:
        return parse_runtime_log(log_text, scenario_ids=scenario_ids or [])
    except Exception as exc:
        return {
            "parse_error": str(exc),
            "scenario_progress": [],
            "completed_scenarios": 0,
            "failed_scenarios": 0,
            "total_step_count": 0,
            "overlay_count": 0,
            "save_excel_count": 0,
            "event_feed": [],
        }


def _run_identity(*, status: dict[str, object], log_path: Path) -> tuple[str | None, str | None]:
    match = RUN_LOG_PATTERN.match(log_path.name)
    run_id = _string_or_none(status.get("run_id")) or (match.group("run_id") if match else None)
    mode = match.group("mode") if match else None
    return run_id, mode


def _total_steps(parsed: dict[str, object]) -> int:
    progress = parsed.get("scenario_progress")
    if isinstance(progress, list) and progress:
        return sum(int(item.get("steps") or 0) for item in progress if isinstance(item, dict))
    return int(parsed.get("total_step_count") or 0)


def _scenario_summaries(parsed: dict[str, object]) -> list[dict[str, object]]:
    progress = parsed.get("scenario_progress")
    if not isinstance(progress, list):
        return []
    stop_reason = parsed.get("stop_reason")
    traversal_result = parsed.get("traversal_result")
    scenarios: list[dict[str, object]] = []
    for item in progress:
        if not isinstance(item, dict):
            continue
        scenarios.append(
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "steps": int(item.get("steps") or 0),
                "stop_reason": stop_reason,
                "traversal_result": traversal_result,
            }
        )
    return scenarios


def _event_counts(parsed: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    events = parsed.get("event_feed")
    if not isinstance(events, list):
        return counts
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if event_type:
            counts[event_type] = counts.get(event_type, 0) + 1
    return counts


def _warnings_from_events(parsed: dict[str, object]) -> list[dict[str, object]]:
    warning_types = {"scenario_failed", "traversal_terminal", "popup_uncleared", "stop_requested"}
    events = parsed.get("event_feed")
    if not isinstance(events, list):
        return []
    return [
        event
        for event in events
        if isinstance(event, dict) and str(event.get("type") or "") in warning_types
    ]


def _string_or_none(value: object) -> str | None:
    return str(value) if value else None


def _elapsed_seconds(started_at: str | None, finished_at: str | None) -> int:
    if not started_at:
        return 0
    try:
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at) if finished_at else datetime.now()
    except ValueError:
        return 0
    return max(0, int((finished - started).total_seconds()))
