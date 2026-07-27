from __future__ import annotations

import json
from typing import Any, Mapping


_ALLOWED_AUTOMATION_DISPOSITIONS = frozenset(
    {
        "accepted_engine_limitation",
        "tracked_backlog",
        "non_blocking_terminal_diagnostic",
        "requires_engine_fix",
    }
)


def text(value: Any) -> str:
    return str(value or "").strip()


def records(value: Any) -> list[Mapping[str, Any]]:
    return (
        [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, list)
        else []
    )


def _signature(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("match_signature")
    return value if isinstance(value, Mapping) else {}


def _candidate_signature(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("source_signature")
    return value if isinstance(value, Mapping) else {}


def review_matches(candidate: Mapping[str, Any], reviewed: Mapping[str, Any]) -> bool:
    candidate_signature = _candidate_signature(candidate)
    reviewed_signature = _signature(reviewed)
    if text(reviewed.get("scenario_id")) != text(candidate.get("scenario_id")):
        return False
    if (
        text(reviewed_signature.get("mismatch_type")).upper()
        != text(candidate.get("mismatch_type") or candidate.get("code")).upper()
    ):
        return False
    candidate_step = text(candidate_signature.get("step") or candidate.get("step"))
    reviewed_step = text(reviewed.get("step") or reviewed_signature.get("step"))
    if candidate_step and reviewed_step != candidate_step:
        return False
    candidate_resource = text(
        candidate_signature.get("resource_id") or candidate.get("resource_id")
    )
    reviewed_resource = text(
        reviewed.get("resource_id") or reviewed_signature.get("resource_id")
    )
    if candidate_resource and reviewed_resource != candidate_resource:
        return False
    transaction_id = text(
        candidate_signature.get("transaction_id")
        or candidate.get("source_transaction_id")
    )
    refs = reviewed.get("evidence_references")
    evidence_references = refs if isinstance(refs, list) else []
    return not transaction_id or any(
        transaction_id in text(reference) for reference in evidence_references
    )


def matched_reviews(
    candidates: list[Mapping[str, Any]], reviewed: list[Mapping[str, Any]]
) -> list[Mapping[str, Any] | None]:
    unmatched = list(reviewed)
    matches: list[Mapping[str, Any] | None] = []
    for candidate in candidates:
        match_index = next(
            (
                reviewed_index
                for reviewed_index, reviewed_item in enumerate(unmatched)
                if review_matches(candidate, reviewed_item)
            ),
            None,
        )
        matches.append(None if match_index is None else unmatched.pop(match_index))
    return matches


def validate_qa_records(
    candidates: list[Mapping[str, Any]], reviewed: Any, *, label: str
) -> list[str]:
    reviewed_items = records(reviewed)
    failures: list[str] = []
    if not reviewed_items:
        return [f"{label}_missing"]
    if len(reviewed_items) != len(candidates):
        failures.append(f"{label}_count_mismatch")
    for index, item in enumerate(reviewed_items):
        prefix = f"{label}_{index}"
        scope = item.get("environment_scope")
        signature = item.get("match_signature")
        refs = item.get("evidence_references")
        if not text(item.get("owner")):
            failures.append(f"{prefix}_owner")
        if not isinstance(scope, Mapping) or not scope:
            failures.append(f"{prefix}_environment_scope")
        if not text(item.get("scenario_id")):
            failures.append(f"{prefix}_scenario_id")
        if not isinstance(signature, Mapping) or not signature:
            failures.append(f"{prefix}_match_signature")
        if not (item.get("review_at") or item.get("expires_at")):
            failures.append(f"{prefix}_review_date")
        if not isinstance(refs, list) or not refs:
            failures.append(f"{prefix}_evidence_references")
        serialized = json.dumps(
            {"scope": scope, "signature": signature}, ensure_ascii=False
        )
        if "*" in serialized:
            failures.append(f"{prefix}_broad_wildcard")
    for index, match in enumerate(matched_reviews(candidates, reviewed_items)):
        if match is None:
            failures.append(f"{label}_candidate_{index}_unmatched")
    return failures


def _automation_matches(
    diagnostic: Mapping[str, Any], acknowledgment: Mapping[str, Any]
) -> bool:
    if text(acknowledgment.get("domain")) != "automation_engine":
        return False
    if text(acknowledgment.get("scenario_id")) != text(diagnostic.get("scenario_id")):
        return False
    if text(acknowledgment.get("step")) != text(diagnostic.get("step")):
        return False
    if (
        text(acknowledgment.get("failure_reason")).lower()
        != text(diagnostic.get("failure_reason")).lower()
    ):
        return False
    transaction_id = text(diagnostic.get("source_transaction_id"))
    refs = acknowledgment.get("evidence_references")
    evidence_references = refs if isinstance(refs, list) else []
    return not transaction_id or any(
        transaction_id in text(reference) for reference in evidence_references
    )


def validate_automation_acknowledgments(
    diagnostics: list[Mapping[str, Any]], acknowledgments: Any
) -> list[str]:
    items = records(acknowledgments)
    failures: list[str] = []
    if not items:
        return ["automation_acknowledgments_missing"]
    if len(items) != len(diagnostics):
        failures.append("automation_acknowledgments_count_mismatch")
    for index, item in enumerate(items):
        prefix = f"automation_acknowledgment_{index}"
        for field in (
            "acknowledged_by",
            "acknowledged_at",
            "owner",
            "scenario_id",
            "step",
            "failure_reason",
        ):
            if not text(item.get(field)):
                failures.append(f"{prefix}_{field}")
        refs = item.get("evidence_references")
        if not isinstance(refs, list) or not refs:
            failures.append(f"{prefix}_evidence_references")
        disposition = text(item.get("disposition"))
        if disposition not in _ALLOWED_AUTOMATION_DISPOSITIONS:
            failures.append(f"{prefix}_disposition")
        if disposition == "requires_engine_fix":
            failures.append(f"{prefix}_requires_engine_fix")
    unmatched = list(items)
    for index, diagnostic in enumerate(diagnostics):
        match_index = next(
            (
                acknowledgment_index
                for acknowledgment_index, item in enumerate(unmatched)
                if _automation_matches(diagnostic, item)
            ),
            None,
        )
        if match_index is None:
            failures.append(f"automation_diagnostic_{index}_unmatched")
        else:
            unmatched.pop(match_index)
    return failures


__all__ = [
    "matched_reviews",
    "records",
    "text",
    "validate_automation_acknowledgments",
    "validate_qa_records",
]
