"""Offline revalidation gates used immediately before manual approval."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tb_runner.baseline_artifact_store import sha256_file
from tb_runner.baseline_candidate_schema import BASELINE_CANDIDATE_SCHEMA_VERSION
from tb_runner.baseline_candidate_validator import validate_baseline_candidate
from tb_runner.canonical_json import canonical_json_bytes, canonical_sha256
from tb_runner.environment_fingerprint import build_environment_fingerprint
from tb_runner.environment_profile import ENVIRONMENT_PROFILE_SCHEMA_VERSION


@dataclass(frozen=True)
class OfflineValidationResult:
    valid: bool
    candidate: dict[str, Any]
    candidate_digest: str | None
    environment_profile: dict[str, Any]
    artifact_paths: dict[str, Path]
    checks: tuple[dict[str, Any], ...]

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(item["check_id"] for item in self.checks if item["status"] == "FAIL")

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(item["check_id"] for item in self.checks if item["status"] == "WARNING")


def _digest_value(value: Any) -> str | None:
    if isinstance(value, Mapping):
        digest = str(value.get("value") or "").lower()
        return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else None
    return None


def _candidate_identity(candidate: Mapping[str, Any]) -> str:
    comparison = candidate.get("comparison_contract")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    runtime = comparison.get("runtime")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    identity_source = {
        "candidate_schema": candidate.get("candidate_schema"),
        "source_run_id": candidate.get("source_run_id"),
        "source_batch_id": candidate.get("source_batch_id"),
        "evidence_run_id": candidate.get("evidence_run_id"),
        "environment_fingerprint": candidate.get("environment_fingerprint"),
        "scenario_set": comparison.get("scenario_set"),
        "runtime": {
            "scenario_registry_hash": runtime.get("scenario_registry_hash"),
            "runtime_config_hash": runtime.get("runtime_config_hash"),
            "normalized_runtime_config_hash": runtime.get("normalized_runtime_config_hash"),
        },
    }
    return "candidate_" + canonical_sha256(identity_source)[:24]


def _artifact_path(run_root: Path, reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference.startswith("qa-run://"):
        return None
    name = reference.rsplit("/", 1)[-1]
    if not name or name in {".", ".."} or Path(name).name != name:
        return None
    if reference.endswith("/batch_summary.json"):
        return run_root.parent / name
    return run_root / name


def offline_revalidate_candidate(
    candidate_path: str | Path,
    *,
    expected_candidate_digest: str | None = None,
) -> OfflineValidationResult:
    path = Path(candidate_path)
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, message: str, **details: Any) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "message": message,
                "details": details,
            }
        )

    if not path.is_file():
        check("candidate_file", False, "candidate file is unavailable")
        return OfflineValidationResult(False, {}, None, {}, {}, tuple(checks))
    raw = path.read_bytes()
    digest = sha256_file(path)
    try:
        loaded = json.loads(raw.decode("utf-8"))
        candidate = loaded if isinstance(loaded, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        candidate = {}
    check("candidate_json", bool(candidate), "candidate is valid UTF-8 JSON")
    check(
        "candidate_canonical_bytes",
        bool(candidate) and raw == canonical_json_bytes(candidate),
        "candidate bytes use canonical JSON",
    )
    check(
        "candidate_document_digest",
        expected_candidate_digest is None or digest == str(expected_candidate_digest).lower(),
        "candidate document checksum matches the supplied review digest",
        actual=digest,
        expected=expected_candidate_digest,
    )
    check(
        "candidate_schema",
        candidate.get("candidate_schema") == BASELINE_CANDIDATE_SCHEMA_VERSION,
        "candidate schema is supported",
    )
    check(
        "candidate_identity",
        bool(candidate) and candidate.get("candidate_id") == _candidate_identity(candidate),
        "candidate ID matches its deterministic source identity",
    )

    report = validate_baseline_candidate(candidate)
    check(
        "candidate_validator",
        report.get("approval_eligible") is True,
        "current Candidate validator passes",
        failure_reasons=report.get("failure_reasons"),
    )
    eligibility = candidate.get("approval_eligibility")
    eligibility = eligibility if isinstance(eligibility, Mapping) else {}
    check(
        "candidate_approval_state",
        candidate.get("approval_state") == "CANDIDATE" and eligibility.get("eligible") is True,
        "candidate is explicitly eligible for manual review",
    )

    run_root = path.parent
    environment_reference = candidate.get("environment_reference")
    environment_reference = environment_reference if isinstance(environment_reference, Mapping) else {}
    environment_name = environment_reference.get("filename")
    environment_path = run_root / str(environment_name or "")
    environment: dict[str, Any] = {}
    if environment_name and environment_path.is_file() and environment_path.parent == run_root:
        try:
            loaded_environment = json.loads(environment_path.read_text(encoding="utf-8"))
            if isinstance(loaded_environment, dict):
                environment = loaded_environment
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    expected_environment_digest = _digest_value(candidate.get("document_digest"))
    check("environment_profile", bool(environment), "referenced EnvironmentProfile exists")
    check(
        "environment_profile_schema",
        environment.get("schema_version") == ENVIRONMENT_PROFILE_SCHEMA_VERSION,
        "EnvironmentProfile schema is supported",
    )
    check(
        "environment_document_digest",
        bool(environment)
        and expected_environment_digest is not None
        and sha256_file(environment_path) == expected_environment_digest
        and environment_path.read_bytes() == canonical_json_bytes(environment),
        "EnvironmentProfile canonical bytes and document digest match",
    )
    recomputed = build_environment_fingerprint(environment).to_dict() if environment else {}
    embedded = environment.get("environment_fingerprint") if environment else None
    candidate_fingerprint = candidate.get("environment_fingerprint")
    check(
        "environment_fingerprint",
        bool(recomputed)
        and recomputed.get("status") == "COMPLETE"
        and recomputed == embedded
        and recomputed == candidate_fingerprint,
        "EnvironmentFingerprint source, status and hash match the profile and Candidate",
    )

    artifact_paths: dict[str, Path] = {}
    manifest = candidate.get("artifact_manifest")
    manifest = manifest if isinstance(manifest, Mapping) else {}
    artifacts = manifest.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, list) else []
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        artifact_type = str(item.get("artifact_type") or "unknown")
        artifact_path = _artifact_path(run_root, item.get("relative_reference"))
        expected = _digest_value(item.get("document_digest"))
        available = artifact_path is not None and artifact_path.is_file()
        valid = (
            available
            and expected is not None
            and sha256_file(artifact_path) == expected
            and artifact_path.stat().st_size == item.get("size")
        )
        if available:
            artifact_paths[artifact_type] = artifact_path
        if item.get("required") is True:
            check(
                f"required_artifact:{artifact_type}",
                valid and item.get("availability") == "AVAILABLE",
                "required artifact exists and matches checksum",
            )
        elif available and expected is not None and not valid:
            checks.append(
                {
                    "check_id": f"optional_artifact:{artifact_type}",
                    "status": "WARNING",
                    "message": "optional artifact checksum does not match",
                    "details": {},
                }
            )
    return OfflineValidationResult(
        not any(item["status"] == "FAIL" for item in checks),
        copy.deepcopy(candidate),
        digest,
        environment,
        artifact_paths,
        tuple(checks),
    )


def validate_reviewed_limitations(
    candidate_limitations: Any,
    reviewed_limitations: Any,
    *,
    acceptance_result: str,
    explicitly_accepted: bool,
) -> tuple[str, ...]:
    candidate_items = candidate_limitations if isinstance(candidate_limitations, list) else []
    reviewed_items = reviewed_limitations if isinstance(reviewed_limitations, list) else []
    failures: list[str] = []
    if acceptance_result == "PASS":
        if candidate_items or reviewed_items:
            failures.append("pass_has_limitations")
        return tuple(failures)
    if acceptance_result != "PASS WITH LIMITATIONS":
        return ("unsupported_acceptance_result",)
    if not explicitly_accepted:
        failures.append("limitations_not_explicitly_accepted")
    if not reviewed_items:
        failures.append("reviewed_limitations_missing")
    if len(reviewed_items) < len(candidate_items):
        failures.append("candidate_limitations_not_fully_reviewed")
    for index, item in enumerate(reviewed_items):
        prefix = f"limitation_{index}"
        if not isinstance(item, Mapping):
            failures.append(f"{prefix}_not_object")
            continue
        scope = item.get("environment_scope")
        signature = item.get("match_signature")
        refs = item.get("evidence_references")
        if not str(item.get("owner") or "").strip():
            failures.append(f"{prefix}_owner")
        if not isinstance(scope, Mapping) or not scope:
            failures.append(f"{prefix}_environment_scope")
        if not str(item.get("scenario_id") or "").strip():
            failures.append(f"{prefix}_scenario_id")
        if not isinstance(signature, Mapping) or not signature:
            failures.append(f"{prefix}_match_signature")
        if not (item.get("review_at") or item.get("expires_at")):
            failures.append(f"{prefix}_review_date")
        if not isinstance(refs, list) or not refs:
            failures.append(f"{prefix}_evidence_references")
        serialized = json.dumps({"scope": scope, "signature": signature}, ensure_ascii=False)
        if "*" in serialized:
            failures.append(f"{prefix}_broad_wildcard")
    for index, candidate in enumerate(candidate_items):
        if not isinstance(candidate, Mapping):
            continue
        code = str(candidate.get("code") or "")
        scenario_id = candidate.get("scenario_id")
        matched = any(
            isinstance(reviewed, Mapping)
            and (not scenario_id or reviewed.get("scenario_id") == scenario_id)
            and isinstance(reviewed.get("match_signature"), Mapping)
            and reviewed["match_signature"].get("mismatch_type") == code
            for reviewed in reviewed_items
        )
        if not matched:
            failures.append(f"candidate_limitation_{index}_unmatched")
    return tuple(failures)


__all__ = [
    "OfflineValidationResult",
    "offline_revalidate_candidate",
    "validate_reviewed_limitations",
]
