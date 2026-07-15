"""Versioned contracts for the Phase 10.2 baseline repository."""

from __future__ import annotations

from enum import Enum


BASELINE_SCHEMA_VERSION = "talkback-approved-baseline-v1"
BASELINE_KEY_SCHEMA_VERSION = "talkback-baseline-key-v1"
APPROVED_ARTIFACT_MANIFEST_SCHEMA_VERSION = "talkback-approved-artifact-manifest-v1"
LIFECYCLE_EVENT_SCHEMA_VERSION = "talkback-baseline-lifecycle-event-v1"
CATALOG_SCHEMA_VERSION = "talkback-baseline-catalog-v1"
APP_INDEX_SCHEMA_VERSION = "talkback-baseline-app-index-v1"
REPOSITORY_VERSION = "phase10.2-local-v1"
ARTIFACT_METADATA_SCHEMA_VERSION = "talkback-pinned-artifact-v1"


class LifecycleState(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class LifecycleEventType(str, Enum):
    CANDIDATE_VALIDATED = "CANDIDATE_VALIDATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    ARTIFACT_PINNED = "ARTIFACT_PINNED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class AcceptanceResult(str, Enum):
    PASS = "PASS"
    PASS_WITH_LIMITATIONS = "PASS WITH LIMITATIONS"


__all__ = [
    "APPROVED_ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "APP_INDEX_SCHEMA_VERSION",
    "ARTIFACT_METADATA_SCHEMA_VERSION",
    "BASELINE_KEY_SCHEMA_VERSION",
    "BASELINE_SCHEMA_VERSION",
    "CATALOG_SCHEMA_VERSION",
    "LIFECYCLE_EVENT_SCHEMA_VERSION",
    "REPOSITORY_VERSION",
    "AcceptanceResult",
    "LifecycleEventType",
    "LifecycleState",
]
