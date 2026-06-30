from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tb_runner.v10_preparation import V10_ARTIFACT_ROOT, V10VersionSchema

POLICY_REGISTRY_SCHEMA_VERSION = "v10-policy-registry-v1"
SCENARIO_CANDIDATE_SCHEMA_VERSION = "v10-scenario-candidate-v1"
ROUTING_CANDIDATE_ARTIFACT_VERSION = "v10-routing-candidate-artifact-v1"
ALLOWED_ELIGIBILITY = {
    "eligible",
    "shadow_only",
    "unsupported",
    "unknown",
    "ambiguous",
    "failed",
}

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class PolicyRegistryEntry:
    plugin_family: str
    supported_capabilities: tuple[str, ...]
    scenario_candidate: str
    confidence_gate: str
    eligibility: str
    notes: str


@dataclass(frozen=True)
class VersionedPolicyRegistry:
    registry_version: str
    policy_version: str
    mapping_revision: int
    entries: tuple[PolicyRegistryEntry, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": POLICY_REGISTRY_SCHEMA_VERSION,
            "registry_version": self.registry_version,
            "policy_version": self.policy_version,
            "mapping_revision": self.mapping_revision,
            "entries": [asdict(entry) for entry in self.entries],
        }


REGISTRY_ENTRIES = (
    PolicyRegistryEntry(
        "MotionSensorCapability",
        ("MotionSensorCapability",),
        "device_motion_sensor_plugin",
        "high",
        "eligible",
        "Motion is primary; temperature and vibration are supplemental.",
    ),
    PolicyRegistryEntry(
        "SmokeDetectorCapability",
        ("SmokeDetectorCapability",),
        "device_smoke_sensor_plugin",
        "high",
        "eligible",
        "Requires smoke detector structural evidence.",
    ),
    PolicyRegistryEntry(
        "LeakSensorCapability",
        ("LeakSensorCapability",),
        "device_water_leak_sensor_plugin",
        "high",
        "eligible",
        "Requires leak or wet/dry structural evidence.",
    ),
    PolicyRegistryEntry(
        "GenericLockCapability",
        ("GenericLockCapability",),
        "device_door_lock_plugin",
        "high",
        "eligible",
        "Requires lock state or control structure.",
    ),
    PolicyRegistryEntry(
        "LaundryWasherCapability",
        ("LaundryWasherCapability",),
        "device_washer_plugin",
        "high",
        "eligible",
        "Requires washer-specific cycle structure.",
    ),
    PolicyRegistryEntry(
        "TVCapabilitySet",
        ("TVCapabilitySet",),
        "device_tv_plugin",
        "high",
        "eligible",
        "TV primary structure takes precedence over supplemental audio controls.",
    ),
    PolicyRegistryEntry(
        "AudioCapabilitySet",
        ("AudioCapabilitySet",),
        "device_audio_plugin",
        "high",
        "eligible",
        "Requires audio structure that is not supplemental to a TV.",
    ),
    PolicyRegistryEntry(
        "CameraCapabilitySet",
        ("CameraCapabilitySet",),
        "device_camera_plugin",
        "high",
        "eligible",
        "Generic camera mapping requires no Home Camera discriminator.",
    ),
    PolicyRegistryEntry(
        "HomeCamera360CapabilitySet",
        ("HomeCamera360CapabilitySet",),
        "device_home_camera_plugin",
        "definite",
        "eligible",
        "More-specific Home Camera evidence is required.",
    ),
    PolicyRegistryEntry(
        "AirPurifierCapabilitySet",
        ("AirPurifierCapabilitySet",),
        "device_air_purifier_plugin",
        "high",
        "eligible",
        "Air quality measurement alone is insufficient.",
    ),
    PolicyRegistryEntry(
        "HumiditySensorCapability",
        ("HumiditySensorCapability",),
        "device_humidity_sensor_plugin",
        "high",
        "eligible",
        "Humidity must be the primary sensor family.",
    ),
    PolicyRegistryEntry(
        "TemperatureHumiditySensorCapabilitySet",
        ("TemperatureHumiditySensorCapabilitySet",),
        "device_temperature_humidity_sensor_plugin",
        "high",
        "eligible",
        "Temperature and humidity must share one primary sensor group.",
    ),
)

_CONFIDENCE_RANK = {
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "definite": 4,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def build_policy_registry(
    versions: V10VersionSchema | Mapping[str, Any] | None = None,
    *,
    entries: Sequence[PolicyRegistryEntry] = REGISTRY_ENTRIES,
) -> VersionedPolicyRegistry:
    if isinstance(versions, V10VersionSchema):
        resolved = versions
    else:
        resolved = V10VersionSchema.from_mapping(versions)
    return VersionedPolicyRegistry(
        registry_version=resolved.registry_version,
        policy_version=resolved.policy_version,
        mapping_revision=resolved.mapping_revision,
        entries=tuple(entries),
    )


def _matching_entries(
    registry: VersionedPolicyRegistry,
    plugin_family: str,
) -> list[PolicyRegistryEntry]:
    return [
        entry
        for entry in registry.entries
        if plugin_family == entry.plugin_family
        or plugin_family in entry.supported_capabilities
    ]


def _matching_quality_gate(result: Mapping[str, Any], plugin_family: str) -> bool:
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return True
    matching = [
        candidate
        for candidate in candidates
        if isinstance(candidate, Mapping)
        and _text(candidate.get("plugin_family")) == plugin_family
    ]
    return len(matching) == 1 and matching[0].get("quality_gate_passed") is True


def _base_candidate(
    result: Mapping[str, Any],
    registry: VersionedPolicyRegistry,
    *,
    clock: Clock,
) -> dict[str, Any]:
    return {
        "schema_version": SCENARIO_CANDIDATE_SCHEMA_VERSION,
        "artifact_version": ROUTING_CANDIDATE_ARTIFACT_VERSION,
        "candidate_id": f"candidate-{uuid.uuid4().hex[:12]}",
        "identify_run_id": _text(result.get("identify_run_id")),
        "inventory_id": _text(result.get("inventory_id")),
        "runtime_card_id": _text(result.get("runtime_card_id")),
        "plugin_family": "unknown",
        "scenario_candidate": "",
        "eligibility": "unknown",
        "confidence": int(result.get("confidence", 0) or 0),
        "confidence_band": _text(result.get("confidence_band")) or "unknown",
        "mapping_source": "versioned_policy_registry",
        "mapping_revision": registry.mapping_revision,
        "policy_version": registry.policy_version,
        "registry_version": registry.registry_version,
        "reason": "",
        "identify_decision": _text(result.get("decision")) or "unknown",
        "created_at": _timestamp(clock()),
        "traversal_allowed": False,
        "routing_performed": False,
    }


def map_quick_identify_result(
    identify_result: Mapping[str, Any],
    *,
    registry: VersionedPolicyRegistry | None = None,
    versions: V10VersionSchema | Mapping[str, Any] | None = None,
    clock: Clock = _utc_now,
) -> dict[str, Any]:
    resolved_registry = registry or build_policy_registry(versions)
    candidate = _base_candidate(identify_result, resolved_registry, clock=clock)
    decision = candidate["identify_decision"]

    if decision == "failed" or identify_result.get("restore_success") is not True:
        candidate["eligibility"] = "failed"
        candidate["reason"] = (
            "identify_failed"
            if decision == "failed"
            else "inventory_restore_not_confirmed"
        )
        return candidate
    if decision == "unknown":
        candidate["eligibility"] = "unknown"
        candidate["reason"] = "identify_result_unknown"
        return candidate
    if decision == "ambiguous":
        candidate["eligibility"] = "ambiguous"
        candidate["reason"] = "identify_result_ambiguous"
        return candidate
    if decision != "identified":
        candidate["eligibility"] = "failed"
        candidate["reason"] = "unsupported_identify_decision"
        return candidate

    plugin_family = _text(identify_result.get("plugin_family_candidate"))
    candidate["plugin_family"] = plugin_family or "unknown"
    if not plugin_family or plugin_family == "unknown":
        candidate["eligibility"] = "unknown"
        candidate["reason"] = "identified_result_missing_plugin_family"
        return candidate

    matches = _matching_entries(resolved_registry, plugin_family)
    if not matches:
        candidate["eligibility"] = "unsupported"
        candidate["reason"] = "registry_mapping_not_found"
        return candidate
    if len(matches) != 1:
        candidate["eligibility"] = "ambiguous"
        candidate["reason"] = "multiple_registry_mappings"
        return candidate

    entry = matches[0]
    candidate["scenario_candidate"] = entry.scenario_candidate
    if entry.eligibility != "eligible":
        candidate["eligibility"] = (
            entry.eligibility
            if entry.eligibility in ALLOWED_ELIGIBILITY
            else "unsupported"
        )
        candidate["reason"] = "registry_entry_not_eligible"
        return candidate

    confidence_band = candidate["confidence_band"]
    gate_passed = (
        _CONFIDENCE_RANK.get(confidence_band, 0)
        >= _CONFIDENCE_RANK.get(entry.confidence_gate, 4)
    )
    if not _matching_quality_gate(identify_result, plugin_family):
        candidate["eligibility"] = "shadow_only"
        candidate["reason"] = "identify_quality_gate_not_confirmed"
        return candidate
    if not gate_passed:
        candidate["eligibility"] = "shadow_only"
        candidate["reason"] = f"confidence_below_{entry.confidence_gate}_gate"
        return candidate

    candidate["eligibility"] = "eligible"
    candidate["reason"] = "exact_registry_mapping_and_confidence_gate_passed"
    return candidate


def write_routing_candidate_artifact(
    candidate: Mapping[str, Any],
    *,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "routing",
) -> Path:
    output_dir = Path(artifact_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{candidate.get('candidate_id', 'candidate-unknown')}.json"
    output_path.write_text(
        json.dumps(dict(candidate), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def run_policy_mapping_if_enabled(
    v10_config: Mapping[str, Any] | None,
    identify_result: Mapping[str, Any],
    *,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "routing",
    clock: Clock = _utc_now,
) -> dict[str, Any]:
    raw = v10_config if isinstance(v10_config, Mapping) else {}
    flags = raw.get("feature_flags") if isinstance(raw.get("feature_flags"), Mapping) else {}
    if flags.get("policy_mapping_enabled") is not True:
        return {"status": "disabled", "result": None, "artifact_path": ""}

    versions = V10VersionSchema.from_mapping(raw.get("versions"))
    candidate = map_quick_identify_result(
        identify_result,
        versions=versions,
        clock=clock,
    )
    path = write_routing_candidate_artifact(candidate, artifact_dir=artifact_dir)
    return {
        "status": candidate["eligibility"],
        "result": candidate,
        "artifact_path": str(path),
    }
