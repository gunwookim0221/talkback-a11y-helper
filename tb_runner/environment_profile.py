"""Versioned EnvironmentProfile data contract for Phase 10.1A."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from tb_runner.canonical_json import canonical_json, canonical_sha256, normalize_canonical_value


ENVIRONMENT_PROFILE_SCHEMA_VERSION = "talkback-environment-profile-v1"
TRAVERSAL_CONTRACT_VERSION = "production-traversal-v2"


class FieldStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    REDACTED = "REDACTED"
    BACKFILLED = "BACKFILLED"


@dataclass(frozen=True)
class EnvironmentField:
    value: Any
    status: FieldStatus
    source: str
    captured_at: str
    reason: str = ""


@dataclass(frozen=True)
class DeviceEnvironment:
    model: EnvironmentField
    serial: EnvironmentField
    serial_token: EnvironmentField
    device_family: EnvironmentField
    form_factor: EnvironmentField


@dataclass(frozen=True)
class AndroidEnvironment:
    release: EnvironmentField
    sdk: EnvironmentField
    build_fingerprint: EnvironmentField
    one_ui_version: EnvironmentField


@dataclass(frozen=True)
class PackageEnvironment:
    package: EnvironmentField
    version_name: EnvironmentField
    version_code: EnvironmentField


@dataclass(frozen=True)
class HelperEnvironment:
    package: EnvironmentField
    version: EnvironmentField
    version_code: EnvironmentField
    apk_sha256: EnvironmentField


@dataclass(frozen=True)
class DisplayEnvironment:
    physical_size: EnvironmentField
    logical_size: EnvironmentField
    override_size: EnvironmentField
    density: EnvironmentField
    physical_density: EnvironmentField
    override_density: EnvironmentField


@dataclass(frozen=True)
class FoldEnvironment:
    capability: EnvironmentField
    posture: EnvironmentField
    active_display: EnvironmentField


@dataclass(frozen=True)
class RepositoryEnvironment:
    commit: EnvironmentField
    dirty: EnvironmentField


@dataclass(frozen=True)
class RuntimeEnvironment:
    scenario_registry_hash: EnvironmentField
    runtime_config_hash: EnvironmentField
    traversal_contract: EnvironmentField
    identity_contract: EnvironmentField
    feature_flags: EnvironmentField
    collection_schema_versions: EnvironmentField


@dataclass(frozen=True)
class EnvironmentProfile:
    schema_version: str
    captured_at: str
    device: DeviceEnvironment
    android: AndroidEnvironment
    talkback: PackageEnvironment
    target_app: PackageEnvironment
    helper: HelperEnvironment
    locale: EnvironmentField
    display: DisplayEnvironment
    fold: FoldEnvironment
    repository: RepositoryEnvironment
    runtime: RuntimeEnvironment

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def document_digest(self) -> str:
        """SHA-256 integrity digest of the complete canonical profile document."""
        return canonical_sha256(self.to_dict())

    def environment_hash(self) -> str:
        """Deprecated compatibility alias for document_digest()."""
        return self.document_digest()


def profile_status_counts(profile: EnvironmentProfile | dict[str, Any]) -> dict[str, int]:
    payload = profile.to_dict() if isinstance(profile, EnvironmentProfile) else profile
    counts = {status.value: 0 for status in FieldStatus}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            status = value.get("status")
            if status in counts:
                counts[str(status)] += 1
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return counts


__all__ = [
    "AndroidEnvironment",
    "DeviceEnvironment",
    "DisplayEnvironment",
    "ENVIRONMENT_PROFILE_SCHEMA_VERSION",
    "EnvironmentField",
    "EnvironmentProfile",
    "FieldStatus",
    "FoldEnvironment",
    "HelperEnvironment",
    "PackageEnvironment",
    "RepositoryEnvironment",
    "RuntimeEnvironment",
    "TRAVERSAL_CONTRACT_VERSION",
    "profile_status_counts",
]
