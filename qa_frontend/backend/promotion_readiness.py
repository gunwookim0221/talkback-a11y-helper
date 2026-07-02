from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


PROMOTION_READINESS_SCHEMA_VERSION = "v10-promotion-readiness-v1"
MIN_READY_OBSERVATIONS = 2
MIN_READY_CONFIDENCE = 80
ALLOWED_STATUSES = {
    "READY",
    "HOLD",
    "BLOCKED",
    "INSUFFICIENT_DATA",
    "UNKNOWN_ONLY",
}

SCENARIO_FAMILIES = {
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

CAPABILITY_FAMILIES = {
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


def evaluate_promotion_readiness(
    comparisons: Sequence[Mapping[str, Any]],
    *,
    identify_results: Sequence[Mapping[str, Any]] = (),
    legacy_preserved: bool,
    minimum_ready_observations: int = MIN_READY_OBSERVATIONS,
    minimum_ready_confidence: int = MIN_READY_CONFIDENCE,
    created_at: str | None = None,
) -> dict[str, Any]:
    identify_by_card = {
        _text(item.get("runtime_card_id")): _text(item.get("plugin_family_candidate"))
        for item in identify_results
    }
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in comparisons:
        family = _family_name(item, identify_by_card)
        grouped[family].append(item)

    families = [
        _evaluate_family(
            family,
            records,
            legacy_preserved=legacy_preserved,
            minimum_ready_observations=minimum_ready_observations,
            minimum_ready_confidence=minimum_ready_confidence,
        )
        for family, records in sorted(grouped.items())
    ]
    status_counts = Counter(item["status"] for item in families)
    overall_status = _overall_status(families, legacy_preserved=legacy_preserved)
    return {
        "schema_version": PROMOTION_READINESS_SCHEMA_VERSION,
        "mode": "evaluation_only",
        "created_at": created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "overall_status": overall_status,
        "legacy_preserved": legacy_preserved,
        "controlled_routing_enabled": False,
        "thresholds": {
            "minimum_ready_observations": minimum_ready_observations,
            "minimum_ready_confidence": minimum_ready_confidence,
        },
        "status_counts": {
            status: status_counts.get(status, 0)
            for status in (
                "READY",
                "HOLD",
                "BLOCKED",
                "INSUFFICIENT_DATA",
                "UNKNOWN_ONLY",
            )
        },
        "families": families,
    }


def write_promotion_readiness_artifacts(
    readiness: Mapping[str, Any],
    *,
    shadow_dir: str | Path,
) -> tuple[Path, Path]:
    output_dir = Path(shadow_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "promotion_readiness.json"
    markdown_path = output_dir / "promotion_readiness.md"
    json_path.write_text(
        json.dumps(dict(readiness), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_promotion_readiness_markdown(readiness),
        encoding="utf-8",
    )
    return json_path, markdown_path


def render_promotion_readiness_markdown(readiness: Mapping[str, Any]) -> str:
    counts = readiness.get("status_counts")
    counts = counts if isinstance(counts, Mapping) else {}
    families = readiness.get("families")
    families = families if isinstance(families, list) else []
    lines = [
        "# V10 Promotion Readiness",
        "",
        "Evaluation only. Controlled routing remains disabled.",
        "",
        "## Summary",
        "",
        f"- Overall status: `{_text(readiness.get('overall_status')) or 'HOLD'}`",
        f"- Legacy preserved: `{'YES' if readiness.get('legacy_preserved') is True else 'NO'}`",
        f"- READY: `{counts.get('READY', 0)}`",
        f"- HOLD: `{counts.get('HOLD', 0)}`",
        f"- BLOCKED: `{counts.get('BLOCKED', 0)}`",
        f"- INSUFFICIENT_DATA: `{counts.get('INSUFFICIENT_DATA', 0)}`",
        f"- UNKNOWN_ONLY: `{counts.get('UNKNOWN_ONLY', 0)}`",
        "",
        "## Family Readiness",
        "",
        "| Family | Status | Candidate | MATCH | UNKNOWN | AMBIGUOUS | MISMATCH | FAILED | Min Confidence | Reason |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in families:
        if not isinstance(item, Mapping):
            continue
        counts_by_result = item.get("counts")
        counts_by_result = counts_by_result if isinstance(counts_by_result, Mapping) else {}
        lines.append(
            "| {family} | {status} | {candidate} | {match} | {unknown} | {ambiguous} | "
            "{mismatch} | {failed} | {confidence} | {reason} |".format(
                family=_markdown(item.get("plugin_family")),
                status=_markdown(item.get("status")),
                candidate="READY CANDIDATE" if item.get("ready_candidate") is True else "-",
                match=counts_by_result.get("MATCH", 0),
                unknown=counts_by_result.get("UNKNOWN", 0),
                ambiguous=counts_by_result.get("AMBIGUOUS", 0),
                mismatch=counts_by_result.get("MISMATCH", 0),
                failed=counts_by_result.get("FAILED", 0),
                confidence=item.get("minimum_confidence", 0),
                reason=_markdown(item.get("reason")),
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Legacy remains authoritative.",
            "- V10 routing performed: `false`",
            "- V10 traversal allowed: `false`",
            "",
        ]
    )
    return "\n".join(lines)


def _evaluate_family(
    family: str,
    records: Sequence[Mapping[str, Any]],
    *,
    legacy_preserved: bool,
    minimum_ready_observations: int,
    minimum_ready_confidence: int,
) -> dict[str, Any]:
    counts = Counter(_text(item.get("comparison_result")).upper() for item in records)
    confidences = [
        int(item.get("confidence") or 0)
        for item in records
        if isinstance(item.get("confidence"), (int, float))
    ]
    minimum_confidence = min(confidences, default=0)
    promotion_eligible_count = sum(
        1 for item in records if item.get("promotion_eligible") is True
    )
    ready_candidate = (
        counts["MATCH"] > 0
        and counts["MISMATCH"] == 0
        and counts["FAILED"] == 0
        and counts["AMBIGUOUS"] == 0
        and counts["UNKNOWN"] == 0
        and promotion_eligible_count == counts["MATCH"]
        and minimum_confidence >= minimum_ready_confidence
    )

    if not legacy_preserved:
        status, reason = "BLOCKED", "legacy_result_not_preserved"
    elif counts["MISMATCH"] > 0:
        status, reason = "BLOCKED", "scenario_mismatch_observed"
    elif counts["FAILED"] > 0:
        status, reason = "BLOCKED", "shadow_failure_observed"
    elif counts["AMBIGUOUS"] > 0:
        status, reason = "HOLD", "ambiguous_evidence_observed"
    elif counts["MATCH"] == 0 and counts["UNKNOWN"] > 0:
        if family == "Unknown":
            status, reason = "UNKNOWN_ONLY", "plugin_family_unresolved"
        else:
            status, reason = "INSUFFICIENT_DATA", "unknown_observations_only"
    elif counts["MATCH"] == 0:
        status, reason = "INSUFFICIENT_DATA", "no_comparable_observations"
    elif counts["UNKNOWN"] > 0:
        status, reason = "HOLD", "family_has_unresolved_observations"
    elif minimum_confidence < minimum_ready_confidence:
        status, reason = "HOLD", "confidence_below_readiness_gate"
    elif promotion_eligible_count != counts["MATCH"]:
        status, reason = "HOLD", "not_all_matches_are_promotion_eligible"
    elif len(records) < minimum_ready_observations:
        status, reason = "HOLD", "insufficient_independent_observations"
    else:
        status, reason = "READY", "readiness_gates_satisfied"

    return {
        "plugin_family": family,
        "status": status,
        "reason": reason,
        "observation_count": len(records),
        "counts": {
            result: counts.get(result, 0)
            for result in ("MATCH", "UNKNOWN", "AMBIGUOUS", "MISMATCH", "FAILED")
        },
        "promotion_eligible_count": promotion_eligible_count,
        "minimum_confidence": minimum_confidence,
        "average_confidence": round(sum(confidences) / len(confidences), 2)
        if confidences
        else 0.0,
        "ready_candidate": ready_candidate,
    }


def _overall_status(
    families: Sequence[Mapping[str, Any]],
    *,
    legacy_preserved: bool,
) -> str:
    if not legacy_preserved or any(item.get("status") == "BLOCKED" for item in families):
        return "BLOCKED"
    if not families:
        return "INSUFFICIENT_DATA"
    if all(item.get("status") == "UNKNOWN_ONLY" for item in families):
        return "UNKNOWN_ONLY"
    if any(item.get("status") in {"HOLD", "INSUFFICIENT_DATA", "UNKNOWN_ONLY"} for item in families):
        return "HOLD"
    return "READY"


def _family_name(
    comparison: Mapping[str, Any],
    identify_by_card: Mapping[str, str],
) -> str:
    scenario = _text(
        comparison.get("shadow_candidate") or comparison.get("legacy_scenario")
    )
    if scenario in SCENARIO_FAMILIES:
        return SCENARIO_FAMILIES[scenario]
    candidate = identify_by_card.get(_text(comparison.get("runtime_card_id")), "")
    if candidate in CAPABILITY_FAMILIES:
        return CAPABILITY_FAMILIES[candidate]
    if candidate and candidate.lower() != "unknown":
        return candidate.removesuffix("Capability").replace("_", " ")
    if scenario:
        return scenario.removeprefix("device_").removesuffix("_plugin").replace("_", " ").title()
    return "Unknown"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _markdown(value: Any) -> str:
    return (_text(value) or "-").replace("|", "\\|")
