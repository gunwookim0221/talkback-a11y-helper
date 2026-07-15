"""Version constants and enums for Phase 10.1B baseline candidates."""

from __future__ import annotations

from enum import Enum


BASELINE_CANDIDATE_SCHEMA_VERSION = "talkback-baseline-candidate-v1"
ARTIFACT_MANIFEST_SCHEMA_VERSION = "talkback-baseline-artifact-manifest-v1"
COMPARISON_CONTRACT_VERSION = "talkback-comparison-input-v1"
SCENARIO_SET_SCHEMA_VERSION = "talkback-scenario-set-v1"
CANDIDATE_NORMALIZER_VERSION = "phase10.1b-normalizer-v1"


class ApprovalState(str, Enum):
    CANDIDATE = "CANDIDATE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class ValidationStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


__all__ = [
    "ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "BASELINE_CANDIDATE_SCHEMA_VERSION",
    "CANDIDATE_NORMALIZER_VERSION",
    "COMPARISON_CONTRACT_VERSION",
    "SCENARIO_SET_SCHEMA_VERSION",
    "ApprovalState",
    "ValidationStatus",
]
