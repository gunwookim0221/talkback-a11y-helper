"""Reviewed exact-model device classification policy for EnvironmentProfile."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_sha256
from tb_runner.environment_profile import FieldStatus
from tb_runner.environment_validator import ValidationResult


DEVICE_CLASSIFICATION_POLICY_SCHEMA_VERSION = "talkback-device-classification-policy-v1"
ALLOWED_FORM_FACTORS = frozenset(
    {"slab_phone", "foldable_phone", "tablet", "wearable", "tv", "unknown"}
)
_FAMILY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DeviceClassificationPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceClassification:
    model: str
    device_family: str
    form_factor: str
    foldable: bool
    review_reason: str
    reviewed_at: str


@dataclass(frozen=True)
class PolicyLoadResult:
    status: FieldStatus
    policy: dict[str, Any] | None = None
    policy_hash: str | None = None
    revision: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class ClassificationResult:
    device_family: ValidationResult
    form_factor: ValidationResult
    source: str
    policy_hash: str | None
    revision: int | None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeviceClassificationPolicyError(f"duplicate_key:{key}")
        result[key] = value
    return result


def _as_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeviceClassificationPolicyError(f"{label}_must_be_object")
    return value


def _validate_policy(payload: Mapping[str, Any]) -> dict[str, DeviceClassification]:
    if payload.get("schema_version") != DEVICE_CLASSIFICATION_POLICY_SCHEMA_VERSION:
        raise DeviceClassificationPolicyError("unsupported_policy_schema")
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise DeviceClassificationPolicyError("invalid_policy_revision")
    devices = _as_object(payload.get("devices"), "devices")
    validated: dict[str, DeviceClassification] = {}
    for model, raw_entry in devices.items():
        if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
            raise DeviceClassificationPolicyError("invalid_device_model_key")
        if model in validated:
            raise DeviceClassificationPolicyError("duplicate_device_model")
        entry = _as_object(raw_entry, f"device:{model}")
        family = entry.get("device_family")
        form_factor = entry.get("form_factor")
        if not isinstance(family, str) or not _FAMILY_RE.fullmatch(family):
            raise DeviceClassificationPolicyError(f"invalid_device_family:{model}")
        if form_factor not in ALLOWED_FORM_FACTORS:
            raise DeviceClassificationPolicyError(f"invalid_form_factor:{model}")
        expected = _as_object(entry.get("expected_capabilities"), f"expected_capabilities:{model}")
        foldable = expected.get("foldable")
        if not isinstance(foldable, bool):
            raise DeviceClassificationPolicyError(f"invalid_foldable_capability:{model}")
        if (form_factor == "foldable_phone") != foldable:
            raise DeviceClassificationPolicyError(f"form_factor_capability_mismatch:{model}")
        review = _as_object(entry.get("review"), f"review:{model}")
        if review.get("status") != "REVIEWED":
            raise DeviceClassificationPolicyError(f"unreviewed_device_entry:{model}")
        reason = review.get("reason")
        reviewed_at = review.get("reviewed_at")
        if not isinstance(reason, str) or not reason.strip():
            raise DeviceClassificationPolicyError(f"invalid_review_reason:{model}")
        if not isinstance(reviewed_at, str) or not _DATE_RE.fullmatch(reviewed_at):
            raise DeviceClassificationPolicyError(f"invalid_reviewed_at:{model}")
        try:
            date.fromisoformat(reviewed_at)
        except ValueError as exc:
            raise DeviceClassificationPolicyError(f"invalid_reviewed_at:{model}") from exc
        validated[model] = DeviceClassification(
            model=model,
            device_family=family,
            form_factor=form_factor,
            foldable=foldable,
            review_reason=reason.strip(),
            reviewed_at=reviewed_at,
        )
    return validated


def load_device_classification_policy(path: str | Path | None) -> PolicyLoadResult:
    if path is None:
        return PolicyLoadResult(FieldStatus.MISSING, reason="policy_path_not_configured")
    policy_path = Path(path)
    if not policy_path.is_file():
        return PolicyLoadResult(FieldStatus.MISSING, reason="policy_file_unavailable")
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(payload, dict):
            raise DeviceClassificationPolicyError("policy_root_must_be_object")
        _validate_policy(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DeviceClassificationPolicyError) as exc:
        return PolicyLoadResult(FieldStatus.INVALID, reason=f"policy_invalid:{exc}")
    return PolicyLoadResult(
        FieldStatus.AVAILABLE,
        policy=payload,
        policy_hash=canonical_sha256(payload),
        revision=int(payload["revision"]),
    )


def _source(result: PolicyLoadResult) -> str:
    if result.status != FieldStatus.AVAILABLE:
        return "policy:device-classification:unavailable"
    return (
        "policy:device-classification:v1:"
        f"revision-{result.revision}:sha256-{result.policy_hash}:exact-model"
    )


def classify_device(
    model_result: ValidationResult,
    fold_capability_result: ValidationResult,
    *,
    policy_path: str | Path | None,
) -> ClassificationResult:
    """Classify an exact reviewed model while preserving capability evidence boundaries."""

    loaded = load_device_classification_policy(policy_path)
    source = _source(loaded)
    if model_result.status != FieldStatus.AVAILABLE:
        return ClassificationResult(model_result, model_result, source, loaded.policy_hash, loaded.revision)
    if loaded.status != FieldStatus.AVAILABLE:
        unavailable = ValidationResult(loaded.status, reason=loaded.reason)
        return ClassificationResult(unavailable, unavailable, source, loaded.policy_hash, loaded.revision)
    assert loaded.policy is not None
    entries = _validate_policy(loaded.policy)
    model = str(model_result.value).strip()
    entry = entries.get(model)
    if entry is None:
        missing = ValidationResult(FieldStatus.MISSING, reason="exact_model_not_in_reviewed_policy")
        return ClassificationResult(missing, missing, source, loaded.policy_hash, loaded.revision)
    family = ValidationResult(
        FieldStatus.AVAILABLE,
        entry.device_family,
        reason="exact_model_reviewed_policy_match",
    )
    if entry.form_factor == "unknown":
        return ClassificationResult(
            family,
            ValidationResult(FieldStatus.MISSING, reason="unknown_form_factor_not_eligible"),
            source,
            loaded.policy_hash,
            loaded.revision,
        )
    if fold_capability_result.status == FieldStatus.AVAILABLE:
        observed = fold_capability_result.value
        if not isinstance(observed, bool):
            invalid = ValidationResult(FieldStatus.INVALID, reason="fold_capability_not_boolean")
            return ClassificationResult(family, invalid, source, loaded.policy_hash, loaded.revision)
        if observed != entry.foldable:
            invalid = ValidationResult(FieldStatus.INVALID, reason="policy_capability_contradiction")
            return ClassificationResult(family, invalid, source, loaded.policy_hash, loaded.revision)
        return ClassificationResult(
            family,
            ValidationResult(FieldStatus.AVAILABLE, entry.form_factor, reason="exact_policy_capability_confirmed"),
            source,
            loaded.policy_hash,
            loaded.revision,
        )
    if fold_capability_result.status == FieldStatus.MISSING:
        return ClassificationResult(
            family,
            ValidationResult(FieldStatus.MISSING, reason="capability_unavailable_not_inferred"),
            source,
            loaded.policy_hash,
            loaded.revision,
        )
    return ClassificationResult(
        family,
        ValidationResult(FieldStatus.INVALID, reason="capability_evidence_invalid"),
        source,
        loaded.policy_hash,
        loaded.revision,
    )


__all__ = [
    "ALLOWED_FORM_FACTORS",
    "DEVICE_CLASSIFICATION_POLICY_SCHEMA_VERSION",
    "ClassificationResult",
    "DeviceClassification",
    "DeviceClassificationPolicyError",
    "PolicyLoadResult",
    "classify_device",
    "load_device_classification_policy",
]
