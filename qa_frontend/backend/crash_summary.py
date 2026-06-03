from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from .paths import RUN_LOG_DIR


CRASH_RECOVERY_RESULTS = {"CRASH_CAPTURED", "CRASH_RECOVERED", "CRASH_REPEATED"}
CRASH_ARTIFACT_FILES = (
    "crash_event.json",
    "crash_context.json",
    "crash_repro.md",
    "crash_screenshot.png",
    "crash_window_dump.xml",
    "crash_helper_dump.json",
    "focus_state.json",
    "logcat_excerpt.txt",
)


def build_crash_summary(run_id: str, device_id: str, *, run_log_dir: Path | None = None) -> dict[str, object]:
    resolved_run_log_dir = run_log_dir or RUN_LOG_DIR
    device_dir = safe_device_run_dir(run_id, device_id, run_log_dir=resolved_run_log_dir)
    crashes = load_crash_events(device_dir)
    return {
        "crash_count": len(crashes),
        "crashes": crashes,
    }


def safe_device_run_dir(run_id: str, device_id: str, *, run_log_dir: Path | None = None) -> Path:
    resolved_run_log_dir = run_log_dir or RUN_LOG_DIR
    normalized_run_id = _safe_path_segment(run_id, label="run id")
    normalized_device_id = _safe_path_segment(device_id, label="device id")
    root = resolved_run_log_dir.resolve()
    target = (root / normalized_run_id / normalized_device_id).resolve()
    if not target.is_relative_to(root):
        raise ValueError("invalid device path")
    if not target.is_dir():
        raise FileNotFoundError(f"{normalized_run_id}/{normalized_device_id}")
    return target


def load_crash_events(device_dir: Path) -> list[dict[str, object]]:
    crashes_dir = device_dir / "crashes"
    if not crashes_dir.is_dir():
        return []
    events: list[dict[str, object]] = []
    for event_dir in sorted(crashes_dir.iterdir(), key=lambda item: item.name):
        if not event_dir.is_dir():
            continue
        events.append(load_crash_artifact_metadata(event_dir))
    return events


def load_crash_artifact_metadata(event_dir: Path) -> dict[str, object]:
    context = _read_json(event_dir / "crash_context.json")
    event = _read_json(event_dir / "crash_event.json")
    crash_event_id = _string_or_none(context.get("crash_event_id")) or _string_or_none(event.get("crash_event_id")) or event_dir.name
    crash_type = _string_or_none(context.get("crash_type")) or _string_or_none(event.get("crash_type")) or "unknown"
    return {
        "crash_event_id": crash_event_id,
        "crash_type": crash_type,
        "scenario": _scenario_name(context, event),
        "timestamp": _string_or_none(context.get("timestamp")) or _string_or_none(event.get("timestamp")),
        "recovery_result": _recovery_result(context),
        "repro_guide_exists": (event_dir / "crash_repro.md").is_file(),
        "screenshot_exists": (event_dir / "crash_screenshot.png").is_file(),
        "helper_dump_exists": (event_dir / "crash_helper_dump.json").is_file(),
        "window_dump_exists": (event_dir / "crash_window_dump.xml").is_file(),
    }


def build_crash_detail(run_id: str, device_id: str, crash_event_id: str, *, run_log_dir: Path | None = None) -> dict[str, object]:
    event_dir = safe_crash_event_dir(run_id, device_id, crash_event_id, run_log_dir=run_log_dir)
    metadata = load_crash_artifact_metadata(event_dir)
    repro_path = event_dir / "crash_repro.md"
    repro_guide = repro_path.read_text(encoding="utf-8", errors="replace") if repro_path.is_file() else None
    return {
        **metadata,
        "repro_guide": repro_guide,
        "artifacts": {
            "screenshot": (event_dir / "crash_screenshot.png").is_file(),
            "helper_dump": (event_dir / "crash_helper_dump.json").is_file(),
            "window_dump": (event_dir / "crash_window_dump.xml").is_file(),
        },
    }


def safe_crash_event_dir(
    run_id: str,
    device_id: str,
    crash_event_id: str,
    *,
    run_log_dir: Path | None = None,
) -> Path:
    device_dir = safe_device_run_dir(run_id, device_id, run_log_dir=run_log_dir)
    normalized_event_id = _safe_path_segment(crash_event_id, label="crash event id")
    crashes_dir = (device_dir / "crashes").resolve()
    event_dir = (crashes_dir / normalized_event_id).resolve()
    if not event_dir.is_relative_to(crashes_dir):
        raise ValueError("invalid crash event path")
    if not event_dir.is_dir():
        raise FileNotFoundError(normalized_event_id)
    return event_dir


def build_crash_artifact_zip(
    run_id: str,
    device_id: str,
    crash_event_id: str,
    *,
    run_log_dir: Path | None = None,
) -> tuple[bytes, str]:
    event_dir = safe_crash_event_dir(run_id, device_id, crash_event_id, run_log_dir=run_log_dir)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in CRASH_ARTIFACT_FILES:
            path = event_dir / filename
            if path.is_file():
                archive.write(path, arcname=filename)
    return buffer.getvalue(), f"{event_dir.name}_artifacts.zip"


def _safe_path_segment(value: str, *, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"invalid {label}")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError(f"invalid {label}")
    return normalized


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _scenario_name(context: dict[str, Any], event: dict[str, Any]) -> str | None:
    scenario = context.get("scenario")
    if isinstance(scenario, dict):
        name = _string_or_none(scenario.get("name")) or _string_or_none(scenario.get("id"))
        if name:
            return name
    return _string_or_none(context.get("scenario")) or _string_or_none(event.get("scenario_id"))


def _recovery_result(context: dict[str, Any]) -> str:
    recovery = context.get("recovery")
    if not isinstance(recovery, dict):
        return "unknown"
    status = _string_or_none(recovery.get("scenario_final_status"))
    if status in CRASH_RECOVERY_RESULTS:
        return status
    result = _string_or_none(recovery.get("result"))
    if result == "crash_recovered":
        return "CRASH_RECOVERED"
    if result == "crash_repeated":
        return "CRASH_REPEATED"
    if result:
        return "CRASH_CAPTURED"
    return "unknown"


def _string_or_none(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
