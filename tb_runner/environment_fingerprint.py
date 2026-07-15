"""Stable EnvironmentFingerprint contract derived from EnvironmentProfile values."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from tb_runner.canonical_json import canonical_sha256, normalize_canonical_value
from tb_runner.environment_profile import FieldStatus


ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION = "talkback-environment-fingerprint-v1"
DOCUMENT_DIGEST_SCOPE = "canonical-shared-environment-profile-v1"
NON_COMPARISON_FEATURE_FLAGS = frozenset({"runtime_profiler"})


class FingerprintStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNUSABLE = "UNUSABLE"


@dataclass(frozen=True)
class EnvironmentFingerprintSource:
    fingerprint_schema: str
    direct: dict[str, Any]
    family: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))


@dataclass(frozen=True)
class EnvironmentFingerprint:
    fingerprint_schema: str
    status: FingerprintStatus
    hash: str | None
    fingerprint_source: EnvironmentFingerprintSource
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))


def _field(payload: Mapping[str, Any], *path: str) -> Mapping[str, Any] | None:
    value: Any = payload
    for part in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value if isinstance(value, Mapping) else None


def _major(value: Any) -> int:
    match = re.match(r"^(\d+)(?:\D|$)", str(value or "").strip())
    if not match or int(match.group(1)) <= 0:
        raise ValueError("major version is unavailable")
    return int(match.group(1))


def _nonempty(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple, set)):
        raise ValueError("scalar value is required")
    text = str(value or "").strip()
    if not text:
        raise ValueError("value is empty")
    return text


def _sha256(value: Any) -> str:
    text = _nonempty(value).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError("SHA-256 value is invalid")
    return text


def _comparison_flags(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("feature flags are not an object")
    flags: dict[str, bool] = {}
    for name, flag in value.items():
        if not isinstance(name, str) or not isinstance(flag, bool):
            raise ValueError("feature flags must map string names to booleans")
        if name not in NON_COMPARISON_FEATURE_FLAGS:
            flags[name] = flag
    return flags


def _contract_versions(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("collection contracts are unavailable")
    contracts: dict[str, str] = {}
    for name, version in value.items():
        if not isinstance(name, str):
            raise ValueError("collection contract name is invalid")
        contracts[name] = _nonempty(version)
    return contracts


def build_environment_fingerprint(profile: Mapping[str, Any]) -> EnvironmentFingerprint:
    """Build a comparison key without capture time or field provenance.

    A hash is emitted only for a COMPLETE source. Missing critical fields produce
    INCOMPLETE; invalid fields or failed value normalization produce UNUSABLE.
    """

    direct: dict[str, Any] = {}
    family: dict[str, Any] = {}
    missing: list[str] = []
    invalid: list[str] = []

    def add(
        destination: dict[str, Any],
        name: str,
        source_field: Mapping[str, Any] | None,
        normalize: Callable[[Any], Any] = _nonempty,
    ) -> None:
        if source_field is None:
            destination[name] = None
            missing.append(name)
            return
        status = str(source_field.get("status") or "")
        if status == FieldStatus.INVALID.value:
            destination[name] = None
            invalid.append(name)
            return
        if status not in {FieldStatus.AVAILABLE.value, FieldStatus.BACKFILLED.value}:
            destination[name] = None
            missing.append(name)
            return
        try:
            destination[name] = normalize(source_field.get("value"))
        except (TypeError, ValueError):
            destination[name] = None
            invalid.append(name)

    add(direct, "target_app_package", _field(profile, "target_app", "package"))
    # Until an app-specific compatibility policy is approved, Architecture §6.1
    # requires the conservative full version to act as the release train.
    add(
        direct,
        "target_app_release_train",
        _field(profile, "target_app", "version_name"),
    )
    add(
        direct,
        "scenario_registry_hash",
        _field(profile, "runtime", "scenario_registry_hash"),
        _sha256,
    )
    add(
        direct,
        "runtime_config_hash",
        _field(profile, "runtime", "runtime_config_hash"),
        _sha256,
    )
    add(direct, "locale", _field(profile, "locale"))
    add(
        direct,
        "traversal_contract",
        _field(profile, "runtime", "traversal_contract"),
    )
    add(
        direct,
        "identity_contract",
        _field(profile, "runtime", "identity_contract"),
    )
    add(
        direct,
        "comparison_feature_flags",
        _field(profile, "runtime", "feature_flags"),
        _comparison_flags,
    )
    add(
        direct,
        "collection_contract_versions",
        _field(profile, "runtime", "collection_schema_versions"),
        _contract_versions,
    )

    add(family, "android_major", _field(profile, "android", "release"), _major)
    add(family, "one_ui_major", _field(profile, "android", "one_ui_version"), _major)
    add(family, "talkback_package", _field(profile, "talkback", "package"))
    add(family, "talkback_major", _field(profile, "talkback", "version_name"), _major)
    add(family, "form_factor", _field(profile, "device", "form_factor"))
    add(family, "device_family", _field(profile, "device", "device_family"))

    source = EnvironmentFingerprintSource(
        fingerprint_schema=ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
        direct=direct,
        family=family,
    )
    if invalid:
        status = FingerprintStatus.UNUSABLE
    elif missing:
        status = FingerprintStatus.INCOMPLETE
    else:
        status = FingerprintStatus.COMPLETE
    digest = canonical_sha256(source.to_dict()) if status == FingerprintStatus.COMPLETE else None
    return EnvironmentFingerprint(
        fingerprint_schema=ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
        status=status,
        hash=digest,
        fingerprint_source=source,
        missing_fields=tuple(sorted(set(missing))),
        invalid_fields=tuple(sorted(set(invalid))),
    )


def document_digest_reference(digest: str) -> dict[str, str]:
    return {
        "algorithm": "SHA-256",
        "scope": DOCUMENT_DIGEST_SCOPE,
        "value": str(digest),
    }


__all__ = [
    "DOCUMENT_DIGEST_SCOPE",
    "ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION",
    "EnvironmentFingerprint",
    "EnvironmentFingerprintSource",
    "FingerprintStatus",
    "NON_COMPARISON_FEATURE_FLAGS",
    "build_environment_fingerprint",
    "document_digest_reference",
]
