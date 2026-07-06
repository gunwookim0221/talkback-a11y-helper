from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .promotion_readiness import CAPABILITY_FAMILIES, SCENARIO_FAMILIES


CORPUS_SCHEMA_VERSION = "v10-shadow-corpus-v1"
ENTRY_SCHEMA_VERSION = "v10-shadow-corpus-entry-v1"
FAMILY_SUMMARY_SCHEMA_VERSION = "v10-shadow-family-summary-v1"
READINESS_SUMMARY_SCHEMA_VERSION = "v10-shadow-readiness-summary-v1"

REQUIRED_SHADOW_ARTIFACTS = (
    "shadow_inventory.json",
    "shadow_identify.json",
    "shadow_routing.json",
    "shadow_compare.json",
    "promotion_readiness.json",
)
REFERENCE_ARTIFACTS = REQUIRED_SHADOW_ARTIFACTS + (
    "shadow_report.md",
    "promotion_readiness.md",
)
COMPARISON_RESULTS = ("MATCH", "UNKNOWN", "AMBIGUOUS", "MISMATCH", "FAILED")
READINESS_STATUSES = (
    "READY",
    "HOLD",
    "BLOCKED",
    "INSUFFICIENT_DATA",
    "UNKNOWN_ONLY",
)
CAPABILITY_FAMILY_ALIASES = {
    "AudioCapabilitySet": "Audio",
    "CameraCapabilitySet": "Camera",
    "HomeCamera360CapabilitySet": "Home Camera",
    "AirPurifierCapabilitySet": "Air Purifier",
    "HumiditySensorCapability": "Humidity",
    "TemperatureHumiditySensorCapabilitySet": "Temperature / Humidity",
}


class ShadowCorpusError(ValueError):
    pass


def build_corpus_entry(
    run_dir: str | Path,
    *,
    shadow_dir: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir).expanduser().resolve()
    if not run_path.is_dir():
        raise ShadowCorpusError(f"run_dir_invalid:{run_path}")
    shadow_path = (
        Path(shadow_dir).expanduser().resolve()
        if shadow_dir is not None
        else run_path / "shadow"
    )
    artifacts = {
        name: _read_json_object(shadow_path / name)
        for name in REQUIRED_SHADOW_ARTIFACTS
    }
    summary = _read_optional_json(run_path / "summary.json")
    runtime_config = _read_optional_json(run_path / "runtime_config.json")

    inventory_payload = artifacts["shadow_inventory.json"]
    identify_payload = artifacts["shadow_identify.json"]
    compare_payload = artifacts["shadow_compare.json"]
    readiness_payload = artifacts["promotion_readiness.json"]
    inventory = _mapping(inventory_payload.get("inventory"))
    inventory_items = _mapping_list(inventory.get("items"))
    identify_results = _mapping_list(identify_payload.get("results"))
    comparisons = _mapping_list(compare_payload.get("comparisons"))
    metrics = _mapping(compare_payload.get("metrics"))
    readiness_families = {
        _text(item.get("plugin_family")): item
        for item in _mapping_list(readiness_payload.get("families"))
    }
    identify_by_card = {
        _text(item.get("runtime_card_id")): item for item in identify_results
    }

    entry_created_at = (
        created_at
        or _text(compare_payload.get("created_at"))
        or _text(readiness_payload.get("created_at"))
        or _utc_now()
    )
    batch_id = (
        _text(summary.get("batch_id"))
        or _text(compare_payload.get("run_id"))
        or _text(inventory_payload.get("run_id"))
        or run_path.parent.name
    )
    device_serial = (
        _text(summary.get("serial"))
        or _text(summary.get("device_serial"))
        or _text(inventory.get("device_serial"))
    )
    device_model = (
        _text(summary.get("model"))
        or _text(summary.get("device_model"))
        or _text(compare_payload.get("device_name"))
        or _text(inventory_payload.get("device_name"))
    )
    locale = _first_text(
        summary,
        runtime_config,
        keys=("device_locale", "locale", "language_mode", "target_locale"),
    )
    app_version = _first_text(
        summary,
        runtime_config,
        keys=("app_version", "application_version", "version_name"),
    )
    android_version = _first_text(
        summary,
        runtime_config,
        keys=("android_version", "os_version", "sdk_version"),
    )
    shadow_run_id = _text(compare_payload.get("shadow_run_id"))
    corpus_entry_id = _entry_id(
        entry_created_at,
        device_serial=device_serial,
        shadow_run_id=shadow_run_id,
        source_run_dir=run_path,
        shadow_dir=shadow_path,
    )

    family_results: list[dict[str, Any]] = []
    for comparison in comparisons:
        runtime_card_id = _text(comparison.get("runtime_card_id"))
        identify = identify_by_card.get(runtime_card_id, {})
        family = _family_name(comparison, identify)
        readiness = readiness_families.get(family, {})
        family_results.append(
            {
                "family": family,
                "legacy_scenario": _text(comparison.get("legacy_scenario")),
                "display_label": _text(comparison.get("display_label")),
                "stable_label": _text(comparison.get("stable_label")),
                "comparison_result": _comparison_result(
                    comparison.get("comparison_result")
                ),
                "confidence": _number(comparison.get("confidence")),
                "readiness": _text(readiness.get("status"))
                or "INSUFFICIENT_DATA",
                "reason": _text(comparison.get("comparison_reason"))
                or _text(readiness.get("reason")),
                "source_runtime_card_id": runtime_card_id,
            }
        )

    identify_decisions = Counter(
        _text(item.get("decision")).lower() for item in identify_results
    )
    comparison_counts = Counter(
        item["comparison_result"] for item in family_results
    )
    source_artifacts = {
        name: str((shadow_path / name).resolve())
        for name in REFERENCE_ARTIFACTS
        if (shadow_path / name).is_file()
    }
    return {
        "schema_version": ENTRY_SCHEMA_VERSION,
        "corpus_entry_id": corpus_entry_id,
        "created_at": entry_created_at,
        "source_run_dir": str(run_path),
        "source_shadow_dir": str(shadow_path),
        "source_artifacts": source_artifacts,
        "batch_id": batch_id,
        "device_serial": device_serial,
        "device_model": device_model,
        "app_version": app_version,
        "android_version": android_version,
        "locale": locale,
        "shadow_run_id": shadow_run_id,
        "inventory_count": _int_value(
            inventory.get("item_count"), default=len(inventory_items)
        ),
        "identify_count": len(identify_results),
        "identified_count": identify_decisions["identified"],
        "identify_unknown_count": identify_decisions["unknown"],
        "match_count": _metric_count(metrics, comparison_counts, "MATCH"),
        "unknown_count": _metric_count(metrics, comparison_counts, "UNKNOWN"),
        "mismatch_count": _metric_count(metrics, comparison_counts, "MISMATCH"),
        "failed_count": _metric_count(metrics, comparison_counts, "FAILED"),
        "ambiguous_count": _metric_count(metrics, comparison_counts, "AMBIGUOUS"),
        "promotion_eligible_count": _int_value(
            metrics.get("promotion_eligible_count"),
            default=sum(
                1
                for item in comparisons
                if item.get("promotion_eligible") is True
            ),
        ),
        "overall_readiness": _text(readiness_payload.get("overall_status"))
        or "INSUFFICIENT_DATA",
        "family_results": family_results,
    }


def update_shadow_corpus(
    *,
    corpus_dir: str | Path,
    run_dir: str | Path | None = None,
    shadow_dir: str | Path | None = None,
    rebuild: bool = False,
    dry_run: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    corpus_path = Path(corpus_dir).expanduser().resolve()
    entries_path = corpus_path / "entries"
    existing_entries = _load_entries(entries_path)
    entry = (
        build_corpus_entry(run_dir, shadow_dir=shadow_dir, created_at=created_at)
        if run_dir is not None
        else None
    )
    if entry is None and not rebuild:
        raise ShadowCorpusError("run_dir_required_without_rebuild")

    entries_by_id = {
        _text(item.get("corpus_entry_id")): item
        for item in existing_entries
        if _text(item.get("corpus_entry_id"))
    }
    operation = "rebuilt" if rebuild else "unchanged"
    if entry is not None:
        entry_id = entry["corpus_entry_id"]
        entry_operation = "updated" if entry_id in entries_by_id else "appended"
        operation = (
            f"rebuilt_and_{entry_operation}" if rebuild else entry_operation
        )
        entries_by_id[entry_id] = entry

    entries = sorted(
        entries_by_id.values(),
        key=lambda item: (
            _text(item.get("created_at")),
            _text(item.get("corpus_entry_id")),
        ),
    )
    generated_at = created_at or _utc_now()
    index = build_corpus_index(entries, updated_at=generated_at)
    family_summary = build_family_summary(entries, updated_at=generated_at)
    readiness_summary = build_readiness_summary(entries, updated_at=generated_at)

    if not dry_run:
        entries_path.mkdir(parents=True, exist_ok=True)
        (corpus_path / "summaries").mkdir(parents=True, exist_ok=True)
        if entry is not None:
            _write_json(
                entries_path / f"{entry['corpus_entry_id']}.json",
                entry,
            )
        _write_json(corpus_path / "index.json", index)
        _write_json(
            corpus_path / "summaries" / "family_summary.json",
            family_summary,
        )
        _write_json(
            corpus_path / "summaries" / "readiness_summary.json",
            readiness_summary,
        )

    return {
        "status": "dry_run" if dry_run else "completed",
        "operation": operation,
        "corpus_dir": str(corpus_path),
        "entry": entry,
        "index": index,
        "family_summary": family_summary,
        "readiness_summary": readiness_summary,
        "files_written": [] if dry_run else _written_paths(corpus_path, entry),
    }


def build_corpus_index(
    entries: Sequence[Mapping[str, Any]],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "updated_at": updated_at or _utc_now(),
        "entry_count": len(entries),
        "entries": [
            {
                "corpus_entry_id": _text(item.get("corpus_entry_id")),
                "created_at": _text(item.get("created_at")),
                "entry_path": f"entries/{_text(item.get('corpus_entry_id'))}.json",
                "source_run_dir": _text(item.get("source_run_dir")),
                "batch_id": _text(item.get("batch_id")),
                "device_serial": _text(item.get("device_serial")),
                "device_model": _text(item.get("device_model")),
                "locale": _text(item.get("locale")),
                "overall_readiness": _text(item.get("overall_readiness")),
            }
            for item in entries
        ],
    }


def build_family_summary(
    entries: Sequence[Mapping[str, Any]],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    observations: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = (
        defaultdict(list)
    )
    for entry in entries:
        for result in _mapping_list(entry.get("family_results")):
            observations[_text(result.get("family")) or "Unknown"].append(
                (entry, result)
            )

    families = []
    for family, records in sorted(observations.items()):
        result_counts = Counter(
            _comparison_result(result.get("comparison_result"))
            for _, result in records
        )
        readiness_by_run_family: dict[str, str] = {}
        for entry, result in records:
            readiness_by_run_family.setdefault(
                _text(entry.get("corpus_entry_id")),
                _text(result.get("readiness")) or "INSUFFICIENT_DATA",
            )
        readiness_distribution = Counter(readiness_by_run_family.values())
        labels = sorted(
            {
                _text(result.get("stable_label"))
                or _text(result.get("display_label"))
                for _, result in records
                if _text(result.get("stable_label"))
                or _text(result.get("display_label"))
            }
        )
        models = sorted(
            {
                _text(entry.get("device_model"))
                for entry, _ in records
                if _text(entry.get("device_model"))
            }
        )
        serials = {
            _text(entry.get("device_serial"))
            for entry, _ in records
            if _text(entry.get("device_serial"))
        }
        locales = sorted(
            {
                _text(entry.get("locale"))
                for entry, _ in records
                if _text(entry.get("locale"))
            }
        )
        app_versions = sorted(
            {
                _text(entry.get("app_version"))
                for entry, _ in records
                if _text(entry.get("app_version"))
            }
        )
        run_ids = {
            _text(entry.get("corpus_entry_id"))
            for entry, _ in records
            if _text(entry.get("corpus_entry_id"))
        }
        last_seen_at = max(
            (_text(entry.get("created_at")) for entry, _ in records),
            default="",
        )
        candidate = (
            result_counts["MATCH"] > 0
            and all(
                result_counts[result] == 0
                for result in ("UNKNOWN", "AMBIGUOUS", "MISMATCH", "FAILED")
            )
            and len(run_ids) >= 2
            and len(serials) >= 2
            and len(models) >= 2
            and len(locales) >= 2
            and readiness_distribution["READY"] > 0
        )
        families.append(
            {
                "family": family,
                "total_runs": len(run_ids),
                "total_observations": len(records),
                **{
                    f"{result.lower()}_count": result_counts[result]
                    for result in COMPARISON_RESULTS
                },
                "readiness_distribution": {
                    status: readiness_distribution[status]
                    for status in READINESS_STATUSES
                },
                "unique_device_labels": labels,
                "unique_device_label_count": len(labels),
                "unique_device_models": models,
                "unique_device_model_count": len(models),
                "unique_device_serial_count": len(serials),
                "unique_locales": locales,
                "unique_locale_count": len(locales),
                "unique_app_versions": app_versions,
                "unique_app_version_count": len(app_versions),
                "last_seen_at": last_seen_at,
                "candidate_for_v11_pilot": candidate,
            }
        )
    return {
        "schema_version": FAMILY_SUMMARY_SCHEMA_VERSION,
        "updated_at": updated_at or _utc_now(),
        "entry_count": len(entries),
        "family_count": len(families),
        "families": families,
    }


def build_readiness_summary(
    entries: Sequence[Mapping[str, Any]],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    overall = Counter(
        _text(entry.get("overall_readiness")) or "INSUFFICIENT_DATA"
        for entry in entries
    )
    family = build_family_summary(entries, updated_at=updated_at)
    return {
        "schema_version": READINESS_SUMMARY_SCHEMA_VERSION,
        "updated_at": updated_at or _utc_now(),
        "entry_count": len(entries),
        "overall_readiness_distribution": {
            status: overall[status] for status in READINESS_STATUSES
        },
        "family_readiness": [
            {
                "family": item["family"],
                "readiness_distribution": item["readiness_distribution"],
                "candidate_for_v11_pilot": item["candidate_for_v11_pilot"],
            }
            for item in family["families"]
        ],
        "v11_pilot_candidate_families": [
            item["family"]
            for item in family["families"]
            if item["candidate_for_v11_pilot"]
        ],
        "controlled_routing_enabled": False,
    }


def _load_entries(entries_dir: Path) -> list[dict[str, Any]]:
    if not entries_dir.is_dir():
        return []
    entries = []
    for path in sorted(entries_dir.glob("*.json")):
        payload = _read_optional_json(path)
        if (
            payload.get("schema_version") == ENTRY_SCHEMA_VERSION
            and _text(payload.get("corpus_entry_id"))
        ):
            entries.append(payload)
    return entries


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ShadowCorpusError(f"shadow_artifact_missing:{path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowCorpusError(f"shadow_artifact_invalid:{path.name}") from exc
    if not isinstance(payload, dict):
        raise ShadowCorpusError(f"shadow_artifact_invalid:{path.name}")
    return payload


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _written_paths(corpus_dir: Path, entry: Mapping[str, Any] | None) -> list[str]:
    paths = [
        corpus_dir / "index.json",
        corpus_dir / "summaries" / "family_summary.json",
        corpus_dir / "summaries" / "readiness_summary.json",
    ]
    if entry is not None:
        paths.insert(
            0,
            corpus_dir / "entries" / f"{entry['corpus_entry_id']}.json",
        )
    return [str(path) for path in paths]


def _entry_id(
    created_at: str,
    *,
    device_serial: str,
    shadow_run_id: str,
    source_run_dir: Path,
    shadow_dir: Path,
) -> str:
    timestamp = re.sub(r"[^0-9]", "", created_at)[:14] or "unknown_time"
    serial = re.sub(r"[^A-Za-z0-9_-]", "_", device_serial) or "unknown_device"
    identity = "\n".join(
        (str(source_run_dir), str(shadow_dir), shadow_run_id, created_at)
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    return f"{timestamp}_{serial}_{digest}"


def _family_name(
    comparison: Mapping[str, Any],
    identify: Mapping[str, Any],
) -> str:
    scenario = _text(
        comparison.get("shadow_candidate") or comparison.get("legacy_scenario")
    )
    if scenario in SCENARIO_FAMILIES:
        return SCENARIO_FAMILIES[scenario]
    candidate = _text(identify.get("plugin_family_candidate"))
    if candidate in CAPABILITY_FAMILIES:
        return CAPABILITY_FAMILIES[candidate]
    if candidate in CAPABILITY_FAMILY_ALIASES:
        return CAPABILITY_FAMILY_ALIASES[candidate]
    if candidate and candidate.lower() != "unknown":
        return (
            candidate.removesuffix("CapabilitySet")
            .removesuffix("Capability")
            .replace("_", " ")
        )
    if scenario:
        return (
            scenario.removeprefix("device_")
            .removesuffix("_plugin")
            .replace("_", " ")
            .title()
        )
    return "Unknown"


def _comparison_result(value: Any) -> str:
    result = _text(value).upper()
    return result if result in COMPARISON_RESULTS else "FAILED"


def _metric_count(
    metrics: Mapping[str, Any],
    counts: Mapping[str, int],
    result: str,
) -> int:
    return _int_value(
        metrics.get(f"{result.lower()}_count"),
        default=counts.get(result, 0),
    )


def _first_text(
    *sources: Mapping[str, Any],
    keys: Sequence[str],
) -> str:
    for source in sources:
        for key in keys:
            value = _text(source.get(key))
            if value:
                return value
    return ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _number(value: Any) -> int | float:
    return value if isinstance(value, (int, float)) else 0


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
