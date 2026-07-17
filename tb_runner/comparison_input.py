"""Canonical read-only adapters for Approved Baseline and Candidate inputs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from tb_runner.baseline_candidate_schema import (
    BASELINE_CANDIDATE_SCHEMA_VERSION,
    COMPARISON_CONTRACT_VERSION,
)
from tb_runner.baseline_repository_schema import (
    APPROVED_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    BASELINE_SCHEMA_VERSION,
)
from tb_runner.canonical_json import canonical_json_bytes, canonical_sha256
from tb_runner.comparator_schema import (
    AvailabilityStatus,
    COMPARATOR_INPUT_SCHEMA_VERSION,
    ComparatorContractError,
    ComparatorInput,
    SourceKind,
)
from tb_runner.environment_fingerprint import (
    ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
)
from tb_runner.environment_profile import ENVIRONMENT_PROFILE_SCHEMA_VERSION


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REFERENCE_PREFIXES = ("artifact://sha256/", "qa-run://")
_REQUIRED_AGGREGATES = (
    "run",
    "coverage",
    "identity",
    "recovery",
    "reconciliation",
    "profiler",
)
_OBSERVATION_ARTIFACT_TYPES = (
    "evidence_ledger",
    "xlsx",
    "focusable_inventory",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json_document(
    source: str | Path | Mapping[str, Any],
    *,
    label: str,
) -> tuple[dict[str, Any], str]:
    if isinstance(source, Mapping):
        payload = dict(source)
        return payload, canonical_sha256(payload)
    path = Path(source)
    try:
        raw = path.read_bytes()
        loaded = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComparatorContractError(
            f"{label.upper()}_CORRUPT",
            f"{label} is not readable canonical JSON",
        ) from exc
    if not isinstance(loaded, dict):
        raise ComparatorContractError(
            f"{label.upper()}_CORRUPT",
            f"{label} root must be an object",
        )
    if raw != canonical_json_bytes(loaded):
        raise ComparatorContractError(
            f"{label.upper()}_NON_CANONICAL",
            f"{label} bytes are not canonical JSON",
        )
    return loaded, _sha256_bytes(raw)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _profile_value(profile: Mapping[str, Any], *path: str) -> Any:
    value: Any = profile
    for name in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(name)
    if not isinstance(value, Mapping):
        return None
    if value.get("status") not in {"AVAILABLE", "BACKFILLED"}:
        return None
    return value.get("value")


def _major(value: Any) -> int | None:
    match = re.match(r"^(\d+)(?:\D|$)", str(value or "").strip())
    return int(match.group(1)) if match else None


def _validate_fingerprint(fingerprint: Mapping[str, Any]) -> None:
    if fingerprint.get("fingerprint_schema") != ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION:
        raise ComparatorContractError(
            "UNSUPPORTED_SCHEMA",
            "environment fingerprint schema is unsupported",
            actual=fingerprint.get("fingerprint_schema"),
        )
    source = fingerprint.get("fingerprint_source")
    if not isinstance(source, Mapping):
        raise ComparatorContractError(
            "CORRUPT_FINGERPRINT",
            "environment fingerprint source is unavailable",
        )
    if fingerprint.get("status") == "COMPLETE":
        actual = str(fingerprint.get("hash") or "").lower()
        expected = canonical_sha256(source)
        if not _SHA256.fullmatch(actual) or actual != expected:
            raise ComparatorContractError(
                "CORRUPT_FINGERPRINT",
                "environment fingerprint digest does not match its canonical source",
                actual=actual,
                expected=expected,
            )


def _environment(
    *,
    profile: Mapping[str, Any],
    comparison_environment: Mapping[str, Any],
    fingerprint: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    source = _mapping(fingerprint.get("fingerprint_source"))
    direct = _mapping(source.get("direct"))
    family = _mapping(source.get("family"))
    app_version_name = _profile_value(profile, "target_app", "version_name")
    if app_version_name is None:
        app_version_name = comparison_environment.get("target_app_version_name")
    app_version_code = _profile_value(profile, "target_app", "version_code")
    if app_version_code is None:
        app_version_code = comparison_environment.get("target_app_version_code")
    app_package = _profile_value(profile, "target_app", "package")
    if app_package is None:
        app_package = (
            comparison_environment.get("target_app_package")
            or direct.get("target_app_package")
        )
    locale = _profile_value(profile, "locale")
    if locale is None:
        locale = comparison_environment.get("locale") or direct.get("locale")
    feature_flags = direct.get("comparison_feature_flags")
    if not isinstance(feature_flags, Mapping):
        feature_flags = runtime.get("feature_flags")
    collection = runtime.get("collection_contract_versions")
    if not isinstance(collection, Mapping):
        collection = direct.get("collection_contract_versions")
    return {
        "app_package": app_package,
        "app_version_name": app_version_name,
        "app_version_code": app_version_code,
        "locale": locale,
        "android_major": family.get("android_major")
        or _major(_profile_value(profile, "android", "release")),
        "one_ui_major": family.get("one_ui_major")
        or _major(_profile_value(profile, "android", "one_ui_version")),
        "talkback_package": family.get("talkback_package")
        or _profile_value(profile, "talkback", "package"),
        "talkback_major": family.get("talkback_major")
        or _major(_profile_value(profile, "talkback", "version_name")),
        "device_family": family.get("device_family")
        or _profile_value(profile, "device", "device_family"),
        "form_factor": family.get("form_factor")
        or _profile_value(profile, "device", "form_factor"),
        "traversal_contract": runtime.get("traversal_contract")
        or direct.get("traversal_contract"),
        "identity_contract": runtime.get("identity_contract")
        or direct.get("identity_contract"),
        "collection_contract_versions": _mapping(collection),
        "runtime_config_hash": runtime.get("runtime_config_hash")
        or direct.get("runtime_config_hash"),
        "normalized_runtime_config_hash": runtime.get(
            "normalized_runtime_config_hash"
        ),
        "scenario_registry_hash": runtime.get("scenario_registry_hash")
        or direct.get("scenario_registry_hash"),
        "feature_flags": _mapping(feature_flags),
    }


def _scenario(
    scenario_set: Mapping[str, Any],
    run: Mapping[str, Any],
) -> dict[str, Any]:
    selected = scenario_set.get("selected_scenario_ids")
    selected_ids = [str(item) for item in selected] if isinstance(selected, list) else []
    return {
        "selected_ids": selected_ids,
        "execution_mode": scenario_set.get("run_kind"),
        "registry_hash": scenario_set.get("scenario_registry_hash"),
        "selected_hash": scenario_set.get("selected_scenario_hash"),
        "order_hash": scenario_set.get("scenario_order_hash"),
        "selected_count": scenario_set.get("selected_scenario_count"),
        "executed_count": run.get("executed_scenarios"),
        "terminal_count": run.get("terminal_scenarios"),
        "registry_version": scenario_set.get("scenario_registry_version"),
        "scenario_set_schema": scenario_set.get("scenario_set_schema"),
    }


def _normalize_artifacts(manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw_items = manifest.get("artifacts")
    items = raw_items if isinstance(raw_items, list) else []
    required: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        artifact_type = str(raw.get("artifact_type") or "")
        reference = raw.get("pinned_reference")
        if not isinstance(reference, str) or not reference:
            reference = raw.get("logical_reference") or raw.get("relative_reference")
        safe_reference = (
            reference
            if isinstance(reference, str)
            and reference.startswith(_SAFE_REFERENCE_PREFIXES)
            else None
        )
        if reference and safe_reference is None:
            diagnostics.append(
                {
                    "code": "UNSAFE_ARTIFACT_REFERENCE",
                    "artifact_type": artifact_type,
                }
            )
        digest_value = raw.get("content_digest") or raw.get("document_digest")
        digest = (
            str(digest_value.get("value") or "").lower()
            if isinstance(digest_value, Mapping)
            else None
        )
        entry = {
            "artifact_type": artifact_type,
            "availability": raw.get("availability"),
            "reference": safe_reference,
            "digest": digest if digest and _SHA256.fullmatch(digest) else None,
            "required": raw.get("required") is True,
            "schema_version": raw.get("schema_version"),
        }
        (required if entry["required"] else optional).append(entry)

    observations: dict[str, Any] = {}
    for artifact_type in _OBSERVATION_ARTIFACT_TYPES:
        match = next(
            (item for item in optional if item["artifact_type"] == artifact_type),
            None,
        )
        available = bool(
            match
            and match["availability"] == "AVAILABLE"
            and match["reference"]
            and match["digest"]
        )
        observations[artifact_type] = {
            "status": (
                AvailabilityStatus.AVAILABLE.value
                if available
                else AvailabilityStatus.DATA_UNAVAILABLE.value
            ),
            "reason": None if available else "OPTIONAL_ARTIFACT_UNAVAILABLE",
            "reference": match["reference"] if match else None,
        }
    return {
        "required": required,
        "optional": optional,
        "optional_observations": observations,
        "data_availability": {
            "aggregate": {
                "status": AvailabilityStatus.AVAILABLE.value,
                "reason": None,
            },
            "node_text_speech": {
                "status": AvailabilityStatus.DATA_UNAVAILABLE.value,
                "reason": "PHASE_10_3C_NOT_IMPLEMENTED",
            },
        },
        "diagnostics": diagnostics,
    }


def _validate_aggregates(aggregates: Mapping[str, Any]) -> None:
    missing = [
        name
        for name in _REQUIRED_AGGREGATES
        if not isinstance(aggregates.get(name), Mapping)
        or aggregates.get(name, {}).get("available") is False
    ]
    if missing:
        raise ComparatorContractError(
            "MISSING_REQUIRED_AGGREGATE",
            "one or more required aggregate summaries are unavailable",
            missing=missing,
        )


def _validate_required_artifact_refs(artifacts: Mapping[str, Any]) -> None:
    required = artifacts.get("required")
    items = required if isinstance(required, list) else []
    invalid = [
        str(item.get("artifact_type") or "unknown")
        for item in items
        if not isinstance(item, Mapping)
        or item.get("availability") != "AVAILABLE"
        or not item.get("reference")
        or not item.get("digest")
    ]
    if invalid:
        raise ComparatorContractError(
            "CORRUPT_REQUIRED_ARTIFACT_REFERENCE",
            "required artifact availability, reference or digest is invalid",
            artifacts=sorted(invalid),
        )


def adapt_approved_baseline(
    package_path: str | Path,
    *,
    repository_state: str = "APPROVED",
) -> ComparatorInput:
    package = Path(package_path)
    baseline, digest = _load_json_document(
        package / "baseline.json", label="baseline"
    )
    profile, _ = _load_json_document(
        package / "environment_profile.json", label="environment_profile"
    )
    manifest, _ = _load_json_document(
        package / "artifact_manifest.json", label="artifact_manifest"
    )
    if baseline.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise ComparatorContractError(
            "UNSUPPORTED_SCHEMA",
            "approved baseline schema is unsupported",
            actual=baseline.get("schema_version"),
        )
    if profile.get("schema_version") != ENVIRONMENT_PROFILE_SCHEMA_VERSION:
        raise ComparatorContractError(
            "UNSUPPORTED_SCHEMA",
            "environment profile schema is unsupported",
            actual=profile.get("schema_version"),
        )
    if manifest.get("manifest_schema") != APPROVED_ARTIFACT_MANIFEST_SCHEMA_VERSION:
        raise ComparatorContractError(
            "UNSUPPORTED_SCHEMA",
            "approved artifact manifest schema is unsupported",
            actual=manifest.get("manifest_schema"),
        )
    fingerprint = _mapping(baseline.get("environment_fingerprint"))
    _validate_fingerprint(fingerprint)
    embedded = profile.get("environment_fingerprint")
    if embedded != fingerprint:
        raise ComparatorContractError(
            "CORRUPT_FINGERPRINT",
            "baseline and EnvironmentProfile fingerprints differ",
        )
    baseline_key = _mapping(baseline.get("baseline_key"))
    key_digest = str(baseline.get("baseline_key_digest") or "").lower()
    if not _SHA256.fullmatch(key_digest) or canonical_sha256(baseline_key) != key_digest:
        raise ComparatorContractError(
            "CORRUPT_BASELINE_KEY",
            "BaselineKey digest does not match its canonical source",
        )
    summaries = _mapping(baseline.get("summaries"))
    _validate_aggregates(summaries)
    comparison_meta = _mapping(baseline.get("comparison_contract"))
    if comparison_meta.get("contract_version") != COMPARISON_CONTRACT_VERSION:
        raise ComparatorContractError(
            "UNSUPPORTED_SCHEMA",
            "comparison input contract is unsupported",
            actual=comparison_meta.get("contract_version"),
        )
    run = _mapping(summaries.get("run"))
    scenario_set = _mapping(baseline.get("scenario_set_contract"))
    direct = _mapping(baseline_key.get("direct"))
    runtime = {
        "scenario_registry_hash": direct.get("scenario_registry_hash"),
        "runtime_config_hash": direct.get("runtime_config_hash"),
        "normalized_runtime_config_hash": None,
        "traversal_contract": direct.get("traversal_contract"),
        "identity_contract": direct.get("identity_contract"),
        "collection_contract_versions": direct.get(
            "collection_contract_versions"
        ),
        "feature_flags": direct.get("comparison_feature_flags"),
    }
    artifacts = _normalize_artifacts(manifest)
    _validate_required_artifact_refs(artifacts)
    return ComparatorInput(
        input_schema=COMPARATOR_INPUT_SCHEMA_VERSION,
        source_kind=SourceKind.BASELINE,
        source_id=str(baseline.get("baseline_id") or ""),
        source_digest=digest,
        schema_versions={
            "source": baseline.get("schema_version"),
            "environment_profile": profile.get("schema_version"),
            "artifact_manifest": manifest.get("manifest_schema"),
            "comparison_contract": comparison_meta.get("contract_version"),
            "normalizer": comparison_meta.get("normalizer_version"),
            "fingerprint": fingerprint.get("fingerprint_schema"),
        },
        environment=_environment(
            profile=profile,
            comparison_environment={},
            fingerprint=fingerprint,
            runtime=runtime,
        ),
        environment_fingerprint=fingerprint,
        baseline_key=baseline_key,
        scenario=_scenario(scenario_set, run),
        aggregates=summaries,
        reviewed_limitations=tuple(
            item
            for item in (baseline.get("known_limitation_snapshot") or [])
            if isinstance(item, Mapping)
        ),
        artifacts=artifacts,
        provenance={
            "repository_state": repository_state,
            "revision": baseline.get("baseline_revision"),
            "approved_at": baseline.get("approved_at"),
            "source_candidate_id": baseline.get("source_candidate_id"),
            "source_repository": baseline.get("source_repository"),
        },
        diagnostics=tuple(artifacts.get("diagnostics") or []),
    )


def adapt_candidate(
    candidate_source: str | Path | Mapping[str, Any],
    *,
    environment_profile: str | Path | Mapping[str, Any] | None = None,
) -> ComparatorInput:
    candidate, digest = _load_json_document(candidate_source, label="candidate")
    if candidate.get("candidate_schema") != BASELINE_CANDIDATE_SCHEMA_VERSION:
        raise ComparatorContractError(
            "UNSUPPORTED_SCHEMA",
            "baseline candidate schema is unsupported",
            actual=candidate.get("candidate_schema"),
        )
    comparison = _mapping(candidate.get("comparison_contract"))
    if comparison.get("contract_version") != COMPARISON_CONTRACT_VERSION:
        raise ComparatorContractError(
            "UNSUPPORTED_SCHEMA",
            "candidate comparison contract is unsupported",
            actual=comparison.get("contract_version"),
        )
    fingerprint = _mapping(candidate.get("environment_fingerprint"))
    _validate_fingerprint(fingerprint)
    profile: dict[str, Any] = {}
    profile_digest: str | None = None
    if environment_profile is not None:
        profile, profile_digest = _load_json_document(
            environment_profile, label="environment_profile"
        )
        if profile.get("schema_version") != ENVIRONMENT_PROFILE_SCHEMA_VERSION:
            raise ComparatorContractError(
                "UNSUPPORTED_SCHEMA",
                "candidate EnvironmentProfile schema is unsupported",
                actual=profile.get("schema_version"),
            )
        if profile.get("environment_fingerprint") != fingerprint:
            raise ComparatorContractError(
                "CORRUPT_FINGERPRINT",
                "Candidate and EnvironmentProfile fingerprints differ",
            )
    aggregates = {
        name: _mapping(comparison.get(name)) for name in _REQUIRED_AGGREGATES
    }
    _validate_aggregates(aggregates)
    run = _mapping(aggregates.get("run"))
    scenario_set = _mapping(comparison.get("scenario_set"))
    artifacts = _normalize_artifacts(_mapping(candidate.get("artifact_manifest")))
    _validate_required_artifact_refs(artifacts)
    limitations = candidate.get("limitations")
    return ComparatorInput(
        input_schema=COMPARATOR_INPUT_SCHEMA_VERSION,
        source_kind=SourceKind.CANDIDATE,
        source_id=str(candidate.get("candidate_id") or ""),
        source_digest=digest,
        schema_versions={
            "source": candidate.get("candidate_schema"),
            "environment_profile": profile.get("schema_version"),
            "artifact_manifest": _mapping(
                candidate.get("artifact_manifest")
            ).get("manifest_schema"),
            "comparison_contract": comparison.get("contract_version"),
            "normalizer": comparison.get("normalizer_version"),
            "fingerprint": fingerprint.get("fingerprint_schema"),
        },
        environment=_environment(
            profile=profile,
            comparison_environment=_mapping(comparison.get("environment")),
            fingerprint=fingerprint,
            runtime=_mapping(comparison.get("runtime")),
        ),
        environment_fingerprint=fingerprint,
        baseline_key=None,
        scenario=_scenario(scenario_set, run),
        aggregates=aggregates,
        reviewed_limitations=tuple(
            item for item in (limitations or []) if isinstance(item, Mapping)
        ),
        artifacts=artifacts,
        provenance={
            "approval_state": candidate.get("approval_state"),
            "source_run_id": candidate.get("source_run_id"),
            "source_batch_id": candidate.get("source_batch_id"),
            "evidence_run_id": candidate.get("evidence_run_id"),
            "source_repository": comparison.get("repository"),
            "environment_profile_digest": profile_digest,
        },
        diagnostics=tuple(artifacts.get("diagnostics") or []),
    )


def candidate_input_from_baseline(
    baseline: ComparatorInput,
    *,
    source_id: str | None = None,
) -> ComparatorInput:
    """Build a read-only self-comparison fixture without changing a baseline."""
    return ComparatorInput(
        input_schema=baseline.input_schema,
        source_kind=SourceKind.CANDIDATE,
        source_id=source_id or f"candidate_from_{baseline.source_id}",
        source_digest=baseline.source_digest,
        schema_versions=dict(baseline.schema_versions),
        environment=dict(baseline.environment),
        environment_fingerprint=dict(baseline.environment_fingerprint),
        baseline_key=None,
        scenario=dict(baseline.scenario),
        aggregates=dict(baseline.aggregates),
        reviewed_limitations=tuple(baseline.reviewed_limitations),
        artifacts=dict(baseline.artifacts),
        provenance={"derived_for_self_compare": True},
        diagnostics=tuple(baseline.diagnostics),
    )


__all__ = [
    "adapt_approved_baseline",
    "adapt_candidate",
    "candidate_input_from_baseline",
]
