from __future__ import annotations

from typing import Any, Mapping

from tb_runner.approval_disposition import (
    ApprovalValidationReport,
    is_review_completed,
    requires_known_limitation_snapshot,
    reviewer_decision,
)
from tb_runner.approval_record_validation import (
    matched_reviews,
    records,
    text,
    validate_automation_acknowledgments,
    validate_qa_records,
)


def validate_v2_approval_report(
    candidate: Mapping[str, Any],
    *,
    structured_limitations: Any,
    known_limitation_snapshot: Any,
    automation_acknowledgments: Any,
    acceptance_result: str,
    explicitly_accepted: bool,
) -> ApprovalValidationReport:
    limitations = records(candidate.get("limitations"))
    qa = [
        item
        for item in limitations
        if text(item.get("review_domain")) == "qa_accessibility"
    ]
    unknown = [
        item
        for item in limitations
        if text(item.get("review_domain")) != "qa_accessibility"
    ]
    automation = records(candidate.get("automation_diagnostics"))
    reviewed_items = records(structured_limitations)
    snapshot_items = records(known_limitation_snapshot)
    acknowledgment_items = records(automation_acknowledgments)
    matched = matched_reviews(qa, reviewed_items)
    decisions = [
        reviewer_decision(item) if item is not None else reviewer_decision({})
        for item in matched
    ]
    completed = sum(is_review_completed(decision) for decision in decisions)
    snapshot_candidates = [
        item
        for item, decision in zip(qa, decisions, strict=True)
        if requires_known_limitation_snapshot(decision)
    ]
    failures: list[str] = []
    if acceptance_result not in {"PASS", "PASS WITH LIMITATIONS"}:
        failures.append("unsupported_acceptance_result")
    if unknown:
        failures.append("unknown_review_domain")
    if qa:
        failures.extend(
            validate_qa_records(qa, reviewed_items, label="reviewed_limitations")
        )
        if completed != len(qa):
            failures.append("qa_review_incomplete")
        if snapshot_candidates and not explicitly_accepted:
            failures.append("limitations_not_explicitly_accepted")
        failures.extend(
            validate_qa_records(
                snapshot_candidates,
                snapshot_items,
                label="known_limitation_snapshot",
            )
            if snapshot_candidates
            else (
                []
                if not snapshot_items
                else ["known_limitation_snapshot_count_mismatch"]
            )
        )
    elif reviewed_items or snapshot_items:
        failures.append("qa_records_without_qa_limitations")
    if automation:
        failures.extend(
            validate_automation_acknowledgments(automation, acknowledgment_items)
        )
    elif acknowledgment_items:
        failures.append("automation_acknowledgments_without_diagnostics")
    if acceptance_result == "PASS" and snapshot_candidates:
        failures.append("pass_has_known_limitations")
    return ApprovalValidationReport(
        failures=tuple(failures),
        qa_review_rows=len(qa),
        qa_completed_rows=completed,
        qa_snapshot_required=len(snapshot_candidates),
        qa_snapshot_present=len(snapshot_items),
        automation_acknowledgments_required=len(automation),
        automation_acknowledgments_present=len(acknowledgment_items),
    )


def validate_v2_approval(
    candidate: Mapping[str, Any],
    *,
    structured_limitations: Any,
    known_limitation_snapshot: Any,
    automation_acknowledgments: Any,
    acceptance_result: str,
    explicitly_accepted: bool,
) -> tuple[str, ...]:
    return validate_v2_approval_report(
        candidate,
        structured_limitations=structured_limitations,
        known_limitation_snapshot=known_limitation_snapshot,
        automation_acknowledgments=automation_acknowledgments,
        acceptance_result=acceptance_result,
        explicitly_accepted=explicitly_accepted,
    ).failures


__all__ = ["validate_v2_approval", "validate_v2_approval_report"]
