from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import RUN_LOG_DIR
from .run_summary import (
    extract_saved_excel_filename,
    read_summary_file,
    resolve_process_status,
    resolve_scenario_result_status,
    summary_path_for_log,
)
from .runtime_dashboard import parse_runtime_log

RUN_LOG_PATTERN = re.compile(r"^(?P<run_id>\d{8}_\d{6})_(?P<mode>smoke|full)\.log$")
START_PATTERN = "%Y%m%d_%H%M%S"


def list_recent_runs(
    *,
    run_log_dir: Path = RUN_LOG_DIR,
    current_status: dict[str, object] | None = None,
    limit: int = 20,
) -> list[dict[str, object]]:
    if not run_log_dir.exists():
        return []

    runs: list[dict[str, object]] = []
    for path in sorted(run_log_dir.glob("*_*.log"), key=lambda item: item.stat().st_mtime, reverse=True):
        parsed = parse_recent_run(path, current_status=current_status)
        if parsed:
            runs.append(parsed)
        if len(runs) >= limit:
            break
    return runs


def safe_recent_run_log_path(run_id: str, *, run_log_dir: Path = RUN_LOG_DIR) -> Path:
    normalized_run_id = str(run_id or "").strip()
    if not re.fullmatch(r"\d{8}_\d{6}", normalized_run_id):
        raise ValueError("invalid run id")

    candidates = sorted(run_log_dir.glob(f"{normalized_run_id}_*.log"))
    if not candidates:
        raise FileNotFoundError(normalized_run_id)
    return candidates[0].resolve()


def parse_recent_run(path: Path, *, current_status: dict[str, object] | None = None) -> dict[str, object] | None:
    match = RUN_LOG_PATTERN.match(path.name)
    if not match or not path.is_file():
        return None

    run_id = match.group("run_id")
    mode = match.group("mode")
    started_at = _parse_started_at(run_id)
    modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    summary = read_summary_file(summary_path_for_log(path))
    if summary is not None:
        return _recent_run_from_summary(
            summary=summary,
            path=path,
            run_id=run_id,
            mode=mode,
            started_at=started_at,
            modified_at=modified_at,
            current_status=current_status,
        )

    log_text = path.read_text(encoding="utf-8", errors="replace")
    duration_seconds = max(0, int((modified_at - started_at).total_seconds()))
    xlsx_filename = extract_saved_excel_filename(log_text)
    process_status = _resolve_recent_process_status(log_text, run_id=run_id, current_status=current_status)
    runtime_summary = parse_runtime_log(log_text)
    scenario_result_status = resolve_scenario_result_status(process_status, runtime_summary)
    completed_scenarios = int(runtime_summary.get("completed_scenarios") or 0)
    passed_scenarios = int(runtime_summary.get("passed_scenarios") or 0)
    warning_scenarios = int(runtime_summary.get("warning_scenarios") or 0)
    failed_scenarios = int(runtime_summary.get("failed_scenarios") or 0)
    total_scenarios = len(runtime_summary.get("scenario_progress") or [])
    event_warning_count = _count_warning_events(runtime_summary)

    return {
        "run_id": run_id,
        "mode": mode,
        "language_mode": _string_or_none(runtime_summary.get("language_mode")) or "current",
        "device_locale": _string_or_none(runtime_summary.get("device_locale")),
        "status": process_status,
        "process_status": process_status,
        "scenario_result_status": scenario_result_status,
        "passed_scenarios": passed_scenarios,
        "warning_scenarios": warning_scenarios,
        "completed_scenarios": completed_scenarios,
        "failed_scenarios": failed_scenarios,
        "total_scenarios": total_scenarios,
        "event_warning_count": event_warning_count,
        "started_at": started_at.isoformat(timespec="seconds"),
        "duration_seconds": duration_seconds,
        "log_exists": True,
        "log_filename": path.name,
        "xlsx_exists": bool(xlsx_filename),
        "xlsx_filename": xlsx_filename,
        "summary_exists": False,
        "summary_source": "log_parse",
    }


def _parse_started_at(run_id: str) -> datetime:
    return datetime.strptime(run_id, START_PATTERN)


def _recent_run_from_summary(
    *,
    summary: dict[str, object],
    path: Path,
    run_id: str,
    mode: str,
    started_at: datetime,
    modified_at: datetime,
    current_status: dict[str, object] | None,
) -> dict[str, object]:
    process_status = str(summary.get("process_status") or "unknown")
    if current_status and current_status.get("run_id") == run_id:
        process_status = _resolve_recent_process_status("", run_id=run_id, current_status=current_status)
    xlsx_filename = _string_or_none(summary.get("xlsx_filename"))
    started_text = _string_or_none(summary.get("started_at")) or started_at.isoformat(timespec="seconds")
    duration_seconds = int(summary.get("elapsed_seconds") or max(0, int((modified_at - started_at).total_seconds())))

    return {
        "run_id": _string_or_none(summary.get("run_id")) or run_id,
        "mode": _string_or_none(summary.get("mode")) or mode,
        "language_mode": _string_or_none(summary.get("language_mode")) or "current",
        "device_locale": _string_or_none(summary.get("device_locale")),
        "status": process_status,
        "process_status": process_status,
        "scenario_result_status": str(summary.get("scenario_result_status") or "unknown"),
        "passed_scenarios": int(summary.get("passed_scenarios") or 0),
        "warning_scenarios": int(summary.get("warning_scenarios") or 0),
        "completed_scenarios": int(summary.get("completed_scenarios") or 0),
        "failed_scenarios": int(summary.get("failed_scenarios") or 0),
        "total_scenarios": int(summary.get("total_scenarios") or 0),
        "event_warning_count": int(summary.get("event_warning_count") or summary.get("warning_count") or 0),
        "started_at": started_text,
        "duration_seconds": duration_seconds,
        "log_exists": path.exists(),
        "log_filename": path.name,
        "xlsx_exists": bool(xlsx_filename),
        "xlsx_filename": xlsx_filename,
        "summary_exists": True,
        "summary_source": "summary_json",
    }


def _resolve_recent_process_status(log_text: str, *, run_id: str, current_status: dict[str, object] | None) -> str:
    current = current_status or {}
    if current.get("run_id") == run_id:
        return resolve_process_status(status=current, log_text=log_text)
    return resolve_process_status(status=None, log_text=log_text)


def _count_warning_events(runtime_summary: dict[str, object]) -> int:
    events = runtime_summary.get("event_feed")
    if not isinstance(events, list):
        return 0
    warning_types = {"scenario_failed", "traversal_terminal", "popup_uncleared", "stop_requested"}
    return sum(
        1
        for event in events
        if isinstance(event, dict) and str(event.get("type") or "") in warning_types
    )


def _string_or_none(value: object) -> str | None:
    return str(value) if value else None
