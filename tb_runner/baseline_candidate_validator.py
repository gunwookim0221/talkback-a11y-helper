"""Pure validation and approval-eligibility rules for BaselineCandidate."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from tb_runner.baseline_candidate_schema import (
    BASELINE_CANDIDATE_SCHEMA_VERSION,
    COMPARISON_CONTRACT_VERSION,
    ValidationStatus,
)
from tb_runner.environment_fingerprint import ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION


REQUIRED_ARTIFACT_TYPES = {
    "run_summary",
    "environment_profile",
    "evidence_manifest",
    "evidence_reconciliation",
    "focusable_coverage",
    "profiler_archive",
}


@dataclass(frozen=True)
class CandidateValidationCheck:
    check_id: str
    status: ValidationStatus
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status.value,
            "message": self.message,
            "details": dict(self.details),
        }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "")))


def validate_baseline_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    checks: list[CandidateValidationCheck] = []

    def add(check_id: str, passed: bool, message: str, **details: Any) -> None:
        checks.append(
            CandidateValidationCheck(
                check_id,
                ValidationStatus.PASS if passed else ValidationStatus.FAIL,
                message,
                details,
            )
        )

    def warn(check_id: str, condition: bool, message: str, **details: Any) -> None:
        checks.append(
            CandidateValidationCheck(
                check_id,
                ValidationStatus.WARNING if condition else ValidationStatus.PASS,
                message,
                details,
            )
        )

    add(
        "candidate_schema",
        candidate.get("candidate_schema") == BASELINE_CANDIDATE_SCHEMA_VERSION,
        "candidate schema is supported",
        actual=candidate.get("candidate_schema"),
    )
    fingerprint = _mapping(candidate.get("environment_fingerprint"))
    add(
        "environment_fingerprint_complete",
        fingerprint.get("status") == "COMPLETE" and _sha256(fingerprint.get("hash")),
        "environment fingerprint is COMPLETE and hashable",
        actual_status=fingerprint.get("status"),
    )
    add(
        "environment_fingerprint_schema",
        fingerprint.get("fingerprint_schema") == ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
        "environment fingerprint schema is supported",
        actual=fingerprint.get("fingerprint_schema"),
    )
    document_digest = _mapping(candidate.get("document_digest"))
    add(
        "environment_document_digest",
        document_digest.get("algorithm") == "SHA-256" and _sha256(document_digest.get("value")),
        "environment document digest is present",
    )

    comparison = _mapping(candidate.get("comparison_contract"))
    add(
        "comparison_contract",
        comparison.get("contract_version") == COMPARISON_CONTRACT_VERSION,
        "comparison input contract is supported",
        actual=comparison.get("contract_version"),
    )
    coverage = _mapping(comparison.get("coverage"))
    add("coverage_summary", coverage.get("available") is True, "coverage summary is present")
    identity = _mapping(comparison.get("identity"))
    add("identity_summary", identity.get("available") is True, "identity summary is present")
    profiler = _mapping(comparison.get("profiler"))
    add("profiler_summary", profiler.get("available") is True, "profiler summary is present")
    reconciliation = _mapping(comparison.get("reconciliation"))
    add(
        "reconciliation_pass",
        reconciliation.get("status") == "PASS",
        "evidence reconciliation passed",
        actual=reconciliation.get("status"),
    )
    add(
        "reconciliation_integrity",
        int(reconciliation.get("orphan_count") or 0) == 0
        and int(reconciliation.get("duplicate_event_count") or 0) == 0
        and int(reconciliation.get("write_failure_count") or 0) == 0
        and int(reconciliation.get("anchor_abort_count") or 0) == 0,
        "orphan, duplicate, write failure and anchor abort counts are zero",
    )

    runtime = _mapping(comparison.get("runtime"))
    add(
        "scenario_registry_hash",
        _sha256(runtime.get("scenario_registry_hash")),
        "scenario registry hash is present",
    )
    add(
        "runtime_config_hash",
        _sha256(runtime.get("runtime_config_hash")),
        "runtime config hash is present",
    )
    add(
        "known_contracts",
        bool(runtime.get("traversal_contract"))
        and bool(runtime.get("identity_contract"))
        and isinstance(runtime.get("collection_contract_versions"), Mapping),
        "traversal, identity and collection contracts are known",
    )

    environment = _mapping(comparison.get("environment"))
    add(
        "target_app_version",
        bool(environment.get("target_app_package"))
        and bool(environment.get("target_app_version_name")),
        "target app package and version are present",
    )
    repository = _mapping(comparison.get("repository"))
    add(
        "repository_commit",
        bool(re.fullmatch(r"[0-9a-fA-F]{40}", str(repository.get("commit") or ""))),
        "repository commit exists",
    )
    add(
        "working_tree_clean",
        repository.get("dirty") is False,
        "working tree is clean",
        actual=repository.get("dirty"),
    )

    scenario_set = _mapping(comparison.get("scenario_set"))
    add(
        "full_scenario_set",
        scenario_set.get("run_kind") == "FULL" and scenario_set.get("is_targeted") is False,
        "candidate represents the full scenario registry",
        run_kind=scenario_set.get("run_kind"),
        selected_count=scenario_set.get("selected_scenario_count"),
    )
    run = _mapping(comparison.get("run"))
    selected_count = int(scenario_set.get("selected_scenario_count") or 0)
    add(
        "scenario_terminal",
        selected_count > 0
        and int(run.get("executed_scenarios") or 0) == selected_count
        and int(run.get("terminal_scenarios") or 0) == selected_count,
        "all selected scenarios executed and reached terminal state",
        selected=selected_count,
        executed=run.get("executed_scenarios"),
        terminal=run.get("terminal_scenarios"),
    )

    artifact_manifest = _mapping(candidate.get("artifact_manifest"))
    add(
        "artifact_manifest_schema",
        artifact_manifest.get("manifest_schema") == "talkback-baseline-artifact-manifest-v1",
        "artifact manifest schema is supported",
        actual=artifact_manifest.get("manifest_schema"),
    )
    artifacts = artifact_manifest.get("artifacts")
    artifact_items = artifacts if isinstance(artifacts, list) else []
    evidence_present = any(
        _mapping(item).get("artifact_type") == "evidence_manifest"
        and _mapping(item).get("availability") == "AVAILABLE"
        for item in artifact_items
    )
    add("evidence_manifest", evidence_present, "evidence manifest artifact is present")
    present_required_types = {
        str(_mapping(item).get("artifact_type"))
        for item in artifact_items
        if _mapping(item).get("required") is True
    }
    missing_required = sorted(REQUIRED_ARTIFACT_TYPES - present_required_types)
    missing_required.extend(
        str(_mapping(item).get("artifact_type") or "unknown")
        for item in artifact_items
        if _mapping(item).get("required") is True
        and (
            _mapping(item).get("availability") != "AVAILABLE"
            or not _sha256(_mapping(_mapping(item).get("document_digest")).get("value"))
        )
    )
    missing_required = sorted(set(missing_required))
    add(
        "required_artifacts",
        not missing_required,
        "all required artifacts exist and have SHA-256 digests",
        missing=missing_required,
    )

    limitations = candidate.get("limitations")
    limitation_items = limitations if isinstance(limitations, list) else []
    warn(
        "limitations_present",
        bool(limitation_items),
        "candidate contains unreviewed limitations",
        count=len(limitation_items),
    )
    warn(
        "historical_backfill",
        any(_mapping(item).get("code") == "HISTORICAL_BACKFILL" for item in limitation_items),
        "candidate uses historical backfill provenance",
    )

    counts = {status.value: 0 for status in ValidationStatus}
    for check in checks:
        counts[check.status.value] += 1
    eligible = counts[ValidationStatus.FAIL.value] == 0
    failure_reasons = tuple(
        check.check_id for check in checks if check.status == ValidationStatus.FAIL
    )
    return {
        "validator_version": "phase10.1b-validator-v1",
        "status": "PASS" if eligible else "FAIL",
        "approval_eligible": eligible,
        "failure_reasons": list(failure_reasons),
        "counts": counts,
        "checks": [check.to_dict() for check in checks],
    }


__all__ = [
    "CandidateValidationCheck",
    "REQUIRED_ARTIFACT_TYPES",
    "validate_baseline_candidate",
]
