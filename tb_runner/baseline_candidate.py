"""Canonical BaselineCandidate data contract for Phase 10.1B."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from tb_runner.baseline_candidate_schema import ApprovalState
from tb_runner.canonical_json import canonical_json, canonical_sha256, normalize_canonical_value


@dataclass(frozen=True)
class ApprovalEligibility:
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BaselineCandidate:
    candidate_schema: str
    candidate_id: str
    created_at: str
    source_run_id: str
    source_batch: dict[str, Any]
    source_batch_id: str | None
    evidence_run_id: str | None
    environment_reference: dict[str, Any]
    environment_fingerprint: dict[str, Any]
    document_digest: dict[str, Any] | None
    approval_state: ApprovalState
    approval_eligibility: ApprovalEligibility
    limitations: tuple[dict[str, Any], ...]
    artifact_manifest: dict[str, Any]
    comparison_contract: dict[str, Any]
    validation_report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def document_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


__all__ = ["ApprovalEligibility", "BaselineCandidate"]
