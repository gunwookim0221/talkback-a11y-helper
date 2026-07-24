import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl

from .source import read_review_rows
from .workbook import _contains_decisions, generate_review_checklist

_DIAGNOSTIC_NAME = "review_generation.json"


@dataclass(frozen=True, slots=True)
class AutoReviewResult:
    event: str
    output_path: Path | None
    qa_review_count: int
    automation_diagnostic_count: int


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_workbook(run_root: Path) -> Path | None:
    candidates = [path for path in run_root.glob("talkback_compare_*.xlsx") if ".review." not in path.name and ".qa-" not in path.name]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _record(run_root: Path, payload: dict[str, Any]) -> None:
    path = run_root / _DIAGNOSTIC_NAME
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    events = existing.get("events") if isinstance(existing, dict) else []
    document = {"schema_version": "qa-auto-review-generation-v1", "events": [*events, payload] if isinstance(events, list) else [payload]}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _event(name: str, *, batch_id: str, run_root: Path, run_mode: str, batch_state: str, device: dict[str, Any], source: Path | None = None, output: Path | None = None, qa_count: int = 0, diagnostic_count: int = 0, reason: str | None = None, error: Exception | None = None) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(), "event": name, "batch_id": batch_id,
        "run_id": run_root.name, "device_serial": device.get("serial"), "device_model": device.get("model"),
        "run_mode": run_mode, "batch_state": batch_state, "device_state": device.get("state"),
        "source_workbook": str(source) if source else None, "source_sha256": _sha256(source) if source and source.is_file() else None,
        "output_path": str(output) if output else None, "output_sha256": _sha256(output) if output and output.is_file() else None,
        "qa_review_count": qa_count, "automation_diagnostic_count": diagnostic_count,
        "skip_reason": reason, "exception_type": type(error).__name__ if error else None,
        "exception_message": str(error)[:500] if error else None,
    }


def auto_generate_review(run_root: Path, *, batch_id: str, run_mode: str, batch_state: str, device: dict[str, Any]) -> AutoReviewResult:
    if not run_root.is_dir():
        return AutoReviewResult("AUTO_REVIEW_SKIPPED", None, 0, 0)
    source = _source_workbook(run_root)
    try:
        _record(run_root, _event("AUTO_REVIEW_STARTED", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, source=source))
        if run_mode != "full" or batch_state != "finished":
            _record(run_root, _event("AUTO_REVIEW_SKIPPED", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, source=source, reason="run_not_finished_full"))
            return AutoReviewResult("AUTO_REVIEW_SKIPPED", None, 0, 0)
        if source is None:
            _record(run_root, _event("AUTO_REVIEW_SKIPPED", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, reason="source_workbook_missing"))
            return AutoReviewResult("AUTO_REVIEW_SKIPPED", None, 0, 0)
        workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
        workbook.close()
        metadata, rows, _warnings = read_review_rows(source)
        del metadata
        qa_count = sum(row.review_area == "QA" for row in rows)
        diagnostic_count = sum(row.review_area == "AUTOMATION" for row in rows)
        output = source.with_name(f"{source.stem}.review.generated.xlsx")
        _record(run_root, _event("AUTO_REVIEW_SOURCE_VALIDATED", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, source=source, output=output, qa_count=qa_count, diagnostic_count=diagnostic_count))
        if output.is_file() and _contains_decisions(output):
            _record(run_root, _event("AUTO_REVIEW_REVIEWED_FILE_PROTECTED", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, source=source, output=output, qa_count=qa_count, diagnostic_count=diagnostic_count))
            return AutoReviewResult("AUTO_REVIEW_REVIEWED_FILE_PROTECTED", output, qa_count, diagnostic_count)
        if output.is_file():
            _record(run_root, _event("AUTO_REVIEW_ALREADY_EXISTS", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, source=source, output=output, qa_count=qa_count, diagnostic_count=diagnostic_count))
            return AutoReviewResult("AUTO_REVIEW_ALREADY_EXISTS", output, qa_count, diagnostic_count)
        _record(run_root, _event("AUTO_REVIEW_WRITE_STARTED", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, source=source, output=output, qa_count=qa_count, diagnostic_count=diagnostic_count))
        generate_review_checklist(source, output=output)
        _record(run_root, _event("AUTO_REVIEW_WRITE_SUCCEEDED", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, source=source, output=output, qa_count=qa_count, diagnostic_count=diagnostic_count))
        return AutoReviewResult("AUTO_REVIEW_WRITE_SUCCEEDED", output, qa_count, diagnostic_count)
    except Exception as error:  # noqa: BLE001
        _record(run_root, _event("AUTO_REVIEW_FAILED", batch_id=batch_id, run_root=run_root, run_mode=run_mode, batch_state=batch_state, device=device, source=source, error=error))
        return AutoReviewResult("AUTO_REVIEW_FAILED", None, 0, 0)
