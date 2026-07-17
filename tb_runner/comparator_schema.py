"""Versioned, read-only contracts for the Phase 10.3B comparator core."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from tb_runner.canonical_json import normalize_canonical_value


COMPARATOR_INPUT_SCHEMA_VERSION = "talkback-comparator-input-v1"
COMPARISON_COMPATIBILITY_KEY_SCHEMA_VERSION = (
    "talkback-comparison-compatibility-key-v1"
)
COMPARISON_RESULT_SCHEMA_VERSION = "talkback-comparison-result-v1"
COMPARATOR_VERSION = "phase10.3b-comparator-v1"
ONECONNECT_VERSION_POLICY_ID = "oneconnect-version-policy-v1"


class SourceKind(str, Enum):
    BASELINE = "BASELINE"
    CANDIDATE = "CANDIDATE"


class VersionRelation(str, Enum):
    SAME = "SAME"
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"


class CompatibilityGrade(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    COMPATIBLE_PREDECESSOR = "COMPATIBLE_PREDECESSOR"
    COMPATIBLE_FAMILY = "COMPATIBLE_FAMILY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INCOMPARABLE = "INCOMPARABLE"


class AggregateStatus(str, Enum):
    UNCHANGED = "UNCHANGED"
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    STRUCTURAL_CHANGE = "STRUCTURAL_CHANGE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    CORRUPT = "CORRUPT"
    UNSUPPORTED = "UNSUPPORTED"


class CompatibilityKeyStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNUSABLE = "UNUSABLE"


@dataclass(frozen=True)
class ComparatorInput:
    input_schema: str
    source_kind: SourceKind
    source_id: str
    source_digest: str
    schema_versions: dict[str, Any]
    environment: dict[str, Any]
    environment_fingerprint: dict[str, Any]
    baseline_key: dict[str, Any] | None
    scenario: dict[str, Any]
    aggregates: dict[str, Any]
    reviewed_limitations: tuple[dict[str, Any], ...]
    artifacts: dict[str, Any]
    provenance: dict[str, Any]
    diagnostics: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))

    def semantic_source(self) -> dict[str, Any]:
        """Return comparison identity without document/path/time provenance."""
        return normalize_canonical_value(
            {
                "input_schema": self.input_schema,
                "source_kind": self.source_kind.value,
                "source_id": self.source_id,
                "schema_versions": self.schema_versions,
                "environment": self.environment,
                "environment_fingerprint_source": self.environment_fingerprint.get(
                    "fingerprint_source"
                ),
                "scenario": self.scenario,
                "aggregates": self.aggregates,
                "reviewed_limitations": self.reviewed_limitations,
                "artifact_availability": self.artifacts.get("data_availability", {}),
            }
        )


@dataclass(frozen=True)
class CompatibilityAssessment:
    grade: CompatibilityGrade
    version_relation: VersionRelation
    reasons: tuple[dict[str, Any], ...]
    review_items: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))


@dataclass(frozen=True)
class SelectionResult:
    selected: ComparatorInput | None
    selected_reference: dict[str, Any] | None
    assessment: CompatibilityAssessment
    rationale: tuple[dict[str, Any], ...]
    rejected: tuple[dict[str, Any], ...]
    tie: bool = False
    errors: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected"] = self.selected.to_dict() if self.selected else None
        return normalize_canonical_value(payload)


class ComparatorContractError(ValueError):
    """Structured comparator failure that never mutates source data."""

    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = normalize_canonical_value(details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


def reason(code: str, *, field: str | None = None, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code}
    if field is not None:
        payload["field"] = field
    payload.update(details)
    return normalize_canonical_value(payload)


__all__ = [
    "AggregateStatus",
    "AvailabilityStatus",
    "COMPARATOR_INPUT_SCHEMA_VERSION",
    "COMPARATOR_VERSION",
    "COMPARISON_COMPATIBILITY_KEY_SCHEMA_VERSION",
    "COMPARISON_RESULT_SCHEMA_VERSION",
    "CompatibilityAssessment",
    "CompatibilityGrade",
    "CompatibilityKeyStatus",
    "ComparatorContractError",
    "ComparatorInput",
    "ONECONNECT_VERSION_POLICY_ID",
    "SelectionResult",
    "SourceKind",
    "VersionRelation",
    "reason",
]
