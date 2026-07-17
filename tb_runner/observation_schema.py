"""Canonical contracts for Phase 10.3C node-level comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from tb_runner.canonical_json import normalize_canonical_value


OBSERVATION_SCHEMA_VERSION = "talkback-canonical-observation-v1"
OBSERVATION_SET_SCHEMA_VERSION = "talkback-comparison-observation-set-v1"
OBSERVATION_COMPARATOR_VERSION = "phase10.3c-observation-comparator-v1"


class ObservationAvailability(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    CORRUPT = "CORRUPT"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"


class MatchType(str, Enum):
    TIER_1_STABLE_EXACT = "TIER_1_STABLE_EXACT"
    TIER_2_SEMANTIC_STRUCTURE = "TIER_2_SEMANTIC_STRUCTURE"
    TIER_3_TRAVERSAL_NEIGHBORHOOD = "TIER_3_TRAVERSAL_NEIGHBORHOOD"
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    SPLIT = "SPLIT"
    MERGED = "MERGED"


class MatchConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class CanonicalObservation:
    observation_schema: str
    observation_id: str
    scenario_id: str
    step_index: int | None
    transaction_id: str
    request_id: str
    action_type: str
    terminal: bool
    package: str
    resource_id: str
    class_name: str
    role: str
    bounds: tuple[int, int, int, int] | None
    bounds_region: str
    accessibility_focused: bool | None
    focusable: bool | None
    clickable: bool | None
    enabled: bool | None
    selected: bool | None
    checked: bool | None
    scrollable: bool | None
    parent_signature: str
    ancestor_signature: str
    sibling_signature: str
    visible_text: str
    content_description: str
    hint: str
    state_description: str
    talkback_speech: str
    announcement: str
    locale: str
    normalized_text: dict[str, Any]
    normalized_speech: dict[str, Any]
    dynamic_value_markers: tuple[dict[str, Any], ...]
    mismatch_type: str
    raw_result: str
    identity_verdict: str
    progress_verdict: str
    visit_verdict: str
    stop_reason: str
    recovery_result: str
    duplicate_of_step: int | None
    coverage_signature: str
    coverage_status: str
    provenance: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))


@dataclass(frozen=True)
class ObservationSet:
    observation_set_schema: str
    source_kind: str
    source_id: str
    locale: str
    app_package: str
    app_version_name: str | None
    app_version_code: int | None
    availability: ObservationAvailability
    source_quality: str
    observations: tuple[CanonicalObservation, ...]
    artifacts: tuple[dict[str, Any], ...]
    observation_identity_digest: str | None
    diagnostics: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))

    def public_summary(self) -> dict[str, Any]:
        return normalize_canonical_value(
            {
                "observation_set_schema": self.observation_set_schema,
                "source_kind": self.source_kind,
                "source_id": self.source_id,
                "availability": self.availability.value,
                "source_quality": self.source_quality,
                "observation_count": len(self.observations),
                "observation_identity_digest": self.observation_identity_digest,
                "artifacts": self.artifacts,
                "diagnostics": self.diagnostics,
            }
        )


__all__ = [
    "CanonicalObservation",
    "MatchConfidence",
    "MatchType",
    "OBSERVATION_COMPARATOR_VERSION",
    "OBSERVATION_SCHEMA_VERSION",
    "OBSERVATION_SET_SCHEMA_VERSION",
    "ObservationAvailability",
    "ObservationSet",
]
