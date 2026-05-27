from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import RUN_LOG_DIR

RUN_LOG_PATTERN = re.compile(r"^(?P<run_id>\d{8}_\d{6})_(?P<mode>smoke|full)\.log$")
SAVED_EXCEL_PATTERN = re.compile(r"saved excel:\s+output/(?P<filename>[^/\s]+\.xlsx)", re.IGNORECASE)
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
    log_text = path.read_text(encoding="utf-8", errors="replace")
    duration_seconds = max(0, int((modified_at - started_at).total_seconds()))
    xlsx_filename = _extract_saved_excel_filename(log_text)
    status = _resolve_status(log_text, run_id=run_id, current_status=current_status)

    return {
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "started_at": started_at.isoformat(timespec="seconds"),
        "duration_seconds": duration_seconds,
        "log_exists": True,
        "log_filename": path.name,
        "xlsx_exists": bool(xlsx_filename),
        "xlsx_filename": xlsx_filename,
    }


def _parse_started_at(run_id: str) -> datetime:
    return datetime.strptime(run_id, START_PATTERN)


def _extract_saved_excel_filename(log_text: str) -> str | None:
    matches = SAVED_EXCEL_PATTERN.findall(log_text)
    if not matches:
        return None
    return matches[-1]


def _resolve_status(log_text: str, *, run_id: str, current_status: dict[str, object] | None) -> str:
    current = current_status or {}
    if current.get("run_id") == run_id:
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
    if "final_result='fail'" in lowered or "reason='no_scenario_selected'" in lowered:
        return "failed"
    if "[main] script end" in lowered:
        return "success"
    return "unknown"
