from __future__ import annotations

from typing import Any, Mapping, Sequence

from tb_runner.canonical_json import canonical_sha256


def review_source_signature(
    *,
    scenario_id: str,
    step: str,
    mismatch_type: str,
    resource_id: str,
    transaction_id: str,
    source_row: int | None,
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "step": step,
        "mismatch_type": mismatch_type,
        "resource_id": resource_id,
        "transaction_id": transaction_id,
        "source_row": source_row,
    }


def review_source_signature_digest(signature: Mapping[str, Any]) -> str:
    return canonical_sha256(signature)


def transaction_for_review_events(
    events: Sequence[Mapping[str, Any]],
    resource_id: str,
) -> str:
    fallback = ""
    for event in events:
        transaction_id = str(event.get("transaction_id") or "").strip()
        if not transaction_id:
            continue
        fallback = fallback or transaction_id
        if event.get("event_type") != "POST_FOCUS_OBSERVED":
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, Mapping) else {}
        observation = payload.get("observation")
        observation = observation if isinstance(observation, Mapping) else {}
        observed_resource = str(observation.get("resource_id") or "").strip()
        if not resource_id or observed_resource == resource_id:
            return transaction_id
    return fallback


__all__ = [
    "review_source_signature",
    "review_source_signature_digest",
    "transaction_for_review_events",
]
