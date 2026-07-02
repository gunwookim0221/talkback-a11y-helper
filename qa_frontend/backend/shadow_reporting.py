from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .crash_summary import safe_device_run_dir
from .paths import ROOT_DIR, RUN_LOG_DIR


SHADOW_ARTIFACT_NAMES = {
    "report": "shadow_report.md",
    "compare": "shadow_compare.json",
}

SCENARIO_FAMILY_NAMES = {
    "device_motion_sensor_plugin": "Motion",
    "device_smoke_sensor_plugin": "Smoke",
    "device_water_leak_sensor_plugin": "Water Leak",
    "device_door_lock_plugin": "Door Lock",
    "device_washer_plugin": "Washer",
    "device_tv_plugin": "TV",
    "device_audio_plugin": "Audio",
    "device_camera_plugin": "Camera",
    "device_home_camera_plugin": "Home Camera",
    "device_air_purifier_plugin": "Air Purifier",
    "device_humidity_sensor_plugin": "Humidity",
    "device_temperature_humidity_sensor_plugin": "Temperature / Humidity",
    "device_security_system_plugin": "Security System",
}

CAPABILITY_FAMILY_NAMES = {
    "MotionSensorCapability": "Motion",
    "SmokeDetectorCapability": "Smoke",
    "LeakSensorCapability": "Water Leak",
    "GenericLockCapability": "Door Lock",
    "LaundryWasherCapability": "Washer",
    "TVCapability": "TV",
    "TVCapabilitySet": "TV",
    "AudioCapability": "Audio",
    "CameraCapability": "Camera",
    "HomeCameraCapability": "Home Camera",
    "AirPurifierCapability": "Air Purifier",
    "HumidityCapability": "Humidity",
    "TemperatureHumidityCapability": "Temperature / Humidity",
    "SecuritySystemCapability": "Security System",
}


def load_shadow_validation_summary(
    device_dir: Path,
    *,
    root_dir: Path = ROOT_DIR,
) -> dict[str, Any] | None:
    shadow_dir = device_dir / "shadow"
    if not shadow_dir.is_dir():
        return None

    inventory_payload = _read_json(shadow_dir / "shadow_inventory.json")
    identify_payload = _read_json(shadow_dir / "shadow_identify.json")
    compare_payload = _read_json(shadow_dir / "shadow_compare.json")
    error_payload = _read_json(shadow_dir / "shadow_error.json")

    if not any((inventory_payload, identify_payload, compare_payload, error_payload)):
        return None

    inventory = _mapping(inventory_payload.get("inventory"))
    inventory_items = _mapping_list(inventory.get("items"))
    identify_results = _mapping_list(identify_payload.get("results"))
    comparisons = _mapping_list(compare_payload.get("comparisons"))
    metrics = _mapping(compare_payload.get("metrics"))

    decision_counts = _count_by(identify_results, "decision")
    comparison_counts = _count_by(comparisons, "comparison_result")
    runtime_seconds = _runtime_seconds(inventory, identify_results, compare_payload)
    legacy_preserved = _legacy_preserved(compare_payload, comparisons, error_payload)

    status = "failed" if error_payload else "completed"
    if not compare_payload and not error_payload:
        status = "incomplete"

    return {
        "available": True,
        "status": status,
        "inventory_count": _int_or_default(inventory.get("item_count"), len(inventory_items)),
        "identified_count": decision_counts.get("identified", 0),
        "identify_unknown_count": decision_counts.get("unknown", 0),
        "match_count": _metric_count(metrics, comparison_counts, "match"),
        "unknown_count": _metric_count(metrics, comparison_counts, "unknown"),
        "ambiguous_count": _metric_count(metrics, comparison_counts, "ambiguous"),
        "mismatch_count": _metric_count(metrics, comparison_counts, "mismatch"),
        "failed_count": _metric_count(metrics, comparison_counts, "failed"),
        "promotion_eligible_count": _int_or_default(
            metrics.get("promotion_eligible_count"),
            sum(1 for item in comparisons if item.get("promotion_eligible") is True),
        ),
        "legacy_preserved": legacy_preserved,
        "runtime_seconds": runtime_seconds,
        "result_groups": _result_groups(comparisons, identify_results),
        "error": str(error_payload.get("error") or "") if error_payload else "",
        "error_stage": str(error_payload.get("stage") or "") if error_payload else "",
        "artifacts": {
            "report": _relative_artifact(shadow_dir / "shadow_report.md", root_dir),
            "compare": _relative_artifact(shadow_dir / "shadow_compare.json", root_dir),
            "folder_available": True,
        },
    }


def safe_shadow_dir(
    run_id: str,
    device_id: str,
    *,
    run_log_dir: Path = RUN_LOG_DIR,
) -> Path:
    device_dir = safe_device_run_dir(run_id, device_id, run_log_dir=run_log_dir)
    shadow_dir = (device_dir / "shadow").resolve()
    if not shadow_dir.is_relative_to(device_dir.resolve()):
        raise ValueError("invalid shadow path")
    if not shadow_dir.is_dir():
        raise FileNotFoundError("shadow artifacts not found")
    return shadow_dir


def open_shadow_folder(
    run_id: str,
    device_id: str,
    *,
    run_log_dir: Path = RUN_LOG_DIR,
    opener: Callable[[Path], None] | None = None,
) -> Path:
    shadow_dir = safe_shadow_dir(run_id, device_id, run_log_dir=run_log_dir)
    if opener is not None:
        opener(shadow_dir)
    elif os.name == "nt":
        os.startfile(str(shadow_dir))  # type: ignore[attr-defined]
    else:
        command = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen(
            [command, str(shadow_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return shadow_dir


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _count_by(items: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "").strip().lower()
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _metric_count(
    metrics: Mapping[str, Any],
    fallback: Mapping[str, int],
    name: str,
) -> int:
    return _int_or_default(metrics.get(f"{name}_count"), fallback.get(name, 0))


def _int_or_default(value: object, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _runtime_seconds(
    inventory: Mapping[str, Any],
    identify_results: list[Mapping[str, Any]],
    compare_payload: Mapping[str, Any],
) -> float | None:
    started_at = _parse_timestamp(inventory.get("captured_at"))
    completed_at = _parse_timestamp(compare_payload.get("created_at"))
    if started_at is not None and completed_at is not None and completed_at >= started_at:
        return round((completed_at - started_at).total_seconds(), 3)

    durations = [
        float(item.get("identify_duration") or 0)
        for item in identify_results
        if isinstance(item.get("identify_duration"), (int, float))
    ]
    return round(sum(durations), 3) if durations else None


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _legacy_preserved(
    report: Mapping[str, Any],
    comparisons: list[Mapping[str, Any]],
    error: Mapping[str, Any],
) -> bool:
    if error:
        return error.get("legacy_result_preserved") is True
    if report.get("legacy_authoritative") is not True:
        return False
    return all(item.get("legacy_authoritative") is True for item in comparisons)


def _result_groups(
    comparisons: list[Mapping[str, Any]],
    identify_results: list[Mapping[str, Any]],
) -> dict[str, list[str]]:
    identify_by_card = {
        str(item.get("runtime_card_id") or ""): str(item.get("plugin_family_candidate") or "")
        for item in identify_results
    }
    groups = {name: [] for name in ("MATCH", "UNKNOWN", "AMBIGUOUS", "MISMATCH", "FAILED")}
    for item in comparisons:
        result = str(item.get("comparison_result") or "").upper()
        if result not in groups:
            continue
        runtime_card_id = str(item.get("runtime_card_id") or "")
        candidate = identify_by_card.get(runtime_card_id, "")
        scenario = str(item.get("shadow_candidate") or item.get("legacy_scenario") or "")
        family = _family_name(
            candidate,
            scenario,
            str(item.get("stable_label") or item.get("display_label") or ""),
        )
        if family not in groups[result]:
            groups[result].append(family)
    return groups


def _family_name(candidate: str, scenario: str, label: str) -> str:
    if candidate and candidate.lower() != "unknown":
        if candidate in CAPABILITY_FAMILY_NAMES:
            return CAPABILITY_FAMILY_NAMES[candidate]
        return candidate.removesuffix("Capability").replace("_", " ")
    if scenario in SCENARIO_FAMILY_NAMES:
        return SCENARIO_FAMILY_NAMES[scenario]
    if scenario:
        return scenario.removeprefix("device_").removesuffix("_plugin").replace("_", " ").title()
    if label:
        return label
    return "Unknown"


def _relative_artifact(path: Path, root_dir: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.resolve().relative_to(root_dir.resolve()).as_posix()
    except ValueError:
        return None
