"""Offline-only snapshot-to-snapshot node reacquisition model (Phase 5D-B)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from time import perf_counter_ns
from typing import Any

from .node_equivalence import (
    NOT_SUPPORTED_BY_SOURCE,
    PARSE_FAILED,
    PRESENT,
    EquivalenceStatus,
    ReasonCode,
    compare_nodes,
)


SCHEMA_NAME = "talkback.read_only_hierarchy_identity"
SCHEMA_VERSION = "1.0"


class ReacquireStatus(str, Enum):
    PROVEN = "PROVEN"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ReacquireResult:
    status: ReacquireStatus
    reason_code: ReasonCode
    authorized_snapshot_id: str | None
    fresh_snapshot_id: str | None
    authorized_node_id: str | None
    matched_node_id: str | None
    candidate_count: int
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["reason_code"] = self.reason_code.value
        return value


def _is_metadata(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schema_name") == SCHEMA_NAME
        and value.get("schema_version") == SCHEMA_VERSION
        and isinstance(value.get("snapshot"), dict)
        and isinstance(value.get("snapshot", {}).get("snapshot_id"), str)
        and isinstance(value.get("nodes"), list)
    )


def _node_by_id(metadata: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    for node in metadata.get("nodes", []):
        if isinstance(node, dict) and node.get("node_local_id") == node_id:
            return node
    return None


def _field(node: dict[str, Any], name: str) -> dict[str, Any]:
    semantic = node.get("semantic_identifiers")
    value = semantic.get(name) if isinstance(semantic, dict) else None
    return value if isinstance(value, dict) else {"status": NOT_SUPPORTED_BY_SOURCE, "value": None}


def _candidate_prefilter_reason(authorized: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    for key in ("package", "resource_id", "class_name"):
        old, new = _field(authorized, key), _field(candidate, key)
        if old.get("status") == PRESENT and new.get("status") == PRESENT and old.get("value") != new.get("value"):
            return key
    return None


def _fingerprint(metadata: dict[str, Any]) -> Any:
    value = metadata.get("snapshot_fingerprint")
    return value.get("value") if isinstance(value, dict) else None


def reacquire_node(
    authorized_metadata: dict[str, Any],
    authorized_node_id: str,
    fresh_metadata: dict[str, Any],
) -> ReacquireResult:
    """Find a unique proven match, retaining ambiguity and rejection traces."""
    started = perf_counter_ns()
    auth_id = authorized_metadata.get("snapshot", {}).get("snapshot_id") if isinstance(authorized_metadata, dict) else None
    fresh_id = fresh_metadata.get("snapshot", {}).get("snapshot_id") if isinstance(fresh_metadata, dict) else None
    trace: dict[str, Any] = {
        "model": "phase5d_b_offline_node_reacquire_v1",
        "authorization_use": "none",
        "dispatch_performed": False,
        "candidate_count_before_filtering": len(fresh_metadata.get("nodes", [])) if isinstance(fresh_metadata, dict) and isinstance(fresh_metadata.get("nodes"), list) else 0,
        "filters": [],
        "candidate_evaluations": [],
        "matched_fields": [],
        "mismatched_fields": [],
        "unavailable_fields": [],
        "provenance_states": [],
        "lineage_comparison": [],
        "child_action_comparison": [],
        "snapshot_relation": {
            "authorized_snapshot_id": auth_id,
            "fresh_snapshot_id": fresh_id,
            "authorized_fingerprint": _fingerprint(authorized_metadata) if isinstance(authorized_metadata, dict) else None,
            "fresh_fingerprint": _fingerprint(fresh_metadata) if isinstance(fresh_metadata, dict) else None,
            "authorized_capture_sequence": authorized_metadata.get("snapshot", {}).get("capture_sequence") if isinstance(authorized_metadata, dict) else None,
            "fresh_capture_sequence": fresh_metadata.get("snapshot", {}).get("capture_sequence") if isinstance(fresh_metadata, dict) else None,
            "authorized_source": authorized_metadata.get("snapshot", {}).get("source") if isinstance(authorized_metadata, dict) else None,
            "fresh_source": fresh_metadata.get("snapshot", {}).get("source") if isinstance(fresh_metadata, dict) else None,
            "authorized_activity": authorized_metadata.get("snapshot", {}).get("activity") if isinstance(authorized_metadata, dict) else None,
            "fresh_activity": fresh_metadata.get("snapshot", {}).get("activity") if isinstance(fresh_metadata, dict) else None,
            "authorized_windows": authorized_metadata.get("snapshot", {}).get("windows") if isinstance(authorized_metadata, dict) else None,
            "fresh_windows": fresh_metadata.get("snapshot", {}).get("windows") if isinstance(fresh_metadata, dict) else None,
            "fingerprint_is_generation_proof": False,
        },
        "prefilter_exclusions": {"package": 0, "resource_id": 0, "class_name": 0},
    }

    def finish(status: ReacquireStatus, reason: ReasonCode, matched_node: str | None = None, count: int = 0) -> ReacquireResult:
        trace["final_reason"] = reason.value
        trace["elapsed_ns"] = perf_counter_ns() - started
        trace["candidate_count_after_all_filters"] = count
        return ReacquireResult(status, reason, auth_id if isinstance(auth_id, str) else None,
                               fresh_id if isinstance(fresh_id, str) else None, authorized_node_id,
                               matched_node, count, trace)

    if not _is_metadata(authorized_metadata) or not _is_metadata(fresh_metadata) or not isinstance(authorized_node_id, str):
        return finish(ReacquireStatus.REJECTED, ReasonCode.INVALID_METADATA)
    if auth_id == fresh_id:
        return finish(ReacquireStatus.REJECTED, ReasonCode.STALE_SNAPSHOT)
    auth_snapshot = authorized_metadata.get("snapshot", {})
    fresh_snapshot = fresh_metadata.get("snapshot", {})
    old_request = auth_snapshot.get("request_id", {})
    new_request = fresh_snapshot.get("request_id", {})
    if isinstance(old_request, dict) and isinstance(new_request, dict) and old_request.get("status") == PRESENT and new_request.get("status") == PRESENT and old_request.get("value") == new_request.get("value"):
        trace["stale_evidence"] = "same_source_request_id"
        return finish(ReacquireStatus.REJECTED, ReasonCode.STALE_SNAPSHOT)
    old_sequence = auth_snapshot.get("capture_sequence", {})
    new_sequence = fresh_snapshot.get("capture_sequence", {})
    if isinstance(old_sequence, dict) and isinstance(new_sequence, dict) and old_sequence.get("status") == PRESENT and new_sequence.get("status") == PRESENT:
        if type(old_sequence.get("value")) is int and type(new_sequence.get("value")) is int and new_sequence["value"] <= old_sequence["value"]:
            trace["stale_evidence"] = "fresh_capture_sequence_not_newer"
            return finish(ReacquireStatus.REJECTED, ReasonCode.STALE_SNAPSHOT)
    authorized = _node_by_id(authorized_metadata, authorized_node_id)
    if authorized is None:
        return finish(ReacquireStatus.REJECTED, ReasonCode.INVALID_METADATA)

    candidates = [node for node in fresh_metadata["nodes"] if isinstance(node, dict)]
    trace["candidate_count_before_filtering"] = len(candidates)
    trace["filters"].append({"name": "valid_node_records", "remaining": len(candidates)})

    package_filtered: list[dict[str, Any]] = []
    for node in candidates:
        reason = _candidate_prefilter_reason(authorized, node)
        if reason != "package":
            package_filtered.append(node)
        elif reason:
            trace["prefilter_exclusions"][reason] += 1
    trace["filters"].append({"name": "package", "remaining": len(package_filtered), "excluded": len(candidates) - len(package_filtered)})

    core_filtered: list[dict[str, Any]] = []
    for node in package_filtered:
        reason = _candidate_prefilter_reason(authorized, node)
        if reason not in ("resource_id", "class_name"):
            core_filtered.append(node)
        elif reason:
            trace["prefilter_exclusions"][reason] += 1
    trace["filters"].append({"name": "resource_id_and_class", "remaining": len(core_filtered), "excluded": len(package_filtered) - len(core_filtered)})

    proven: list[tuple[dict[str, Any], Any]] = []
    uncertain: list[tuple[dict[str, Any], Any]] = []
    for node in core_filtered:
        result = compare_nodes(authorized_metadata, authorized, fresh_metadata, node)
        evaluation = {
            "candidate_node_id": node.get("node_local_id"),
            "status": result.status.value,
            "reason_code": result.reason_code.value,
            "matched_fields": list(result.matched_fields),
            "mismatched_fields": list(result.mismatched_fields),
            "unavailable_fields": list(result.unavailable_fields),
            "provenance_states": [list(item) for item in result.provenance_states],
            "lineage_comparison": result.lineage_comparison,
            "child_comparison": result.child_comparison,
            "action_comparison": result.action_comparison,
            "evidence": result.evidence,
        }
        trace["candidate_evaluations"].append(evaluation)
        trace["matched_fields"].append({"candidate": node.get("node_local_id"), "fields": list(result.matched_fields)})
        trace["mismatched_fields"].append({"candidate": node.get("node_local_id"), "fields": list(result.mismatched_fields)})
        trace["unavailable_fields"].append({"candidate": node.get("node_local_id"), "fields": list(result.unavailable_fields)})
        trace["provenance_states"].append({"candidate": node.get("node_local_id"), "fields": [list(item) for item in result.provenance_states]})
        trace["lineage_comparison"].append({"candidate": node.get("node_local_id"), "comparison": result.lineage_comparison})
        trace["child_action_comparison"].append({"candidate": node.get("node_local_id"), "child": result.child_comparison, "actions": result.action_comparison})
        if result.status in (EquivalenceStatus.EXACT, EquivalenceStatus.STRONG_EQUIVALENT):
            proven.append((node, result))
        elif result.status == EquivalenceStatus.AMBIGUOUS:
            uncertain.append((node, result))

    trace["filters"].append({"name": "provenance_aware_equivalence", "proven": len(proven), "ambiguous": len(uncertain), "rejected": len(core_filtered) - len(proven) - len(uncertain)})
    if len(proven) > 1 or (proven and uncertain):
        return finish(ReacquireStatus.AMBIGUOUS, ReasonCode.MULTI_MATCH, count=len(proven) + len(uncertain))
    if len(proven) == 1:
        node = proven[0][0]
        trace["selected_candidate"] = node.get("node_local_id")
        return finish(ReacquireStatus.PROVEN, ReasonCode.STRONG_EVIDENCE_MATCH, node.get("node_local_id"), count=1)
    if uncertain:
        reason = ReasonCode.MULTI_MATCH if len(uncertain) > 1 else ReasonCode.INSUFFICIENT_EVIDENCE
        return finish(ReacquireStatus.AMBIGUOUS, reason, count=len(uncertain))

    auth_has_core = all(_field(authorized, key).get("status") == PRESENT for key in ("package", "resource_id", "class_name"))
    any_parse_failed = any(
        state == PARSE_FAILED
        for item in trace["candidate_evaluations"]
        for _name, old_state, new_state in item["provenance_states"]
        for state in (old_state, new_state)
    )
    rejected_reasons = {item.get("reason_code") for item in trace["candidate_evaluations"] if item.get("status") == EquivalenceStatus.REJECTED.value}
    reason_priority = (
        ReasonCode.PROVENANCE_PARSE_FAILURE, ReasonCode.PACKAGE_MISMATCH,
        ReasonCode.WINDOW_MISMATCH, ReasonCode.ACTION_SET_MISMATCH,
        ReasonCode.INDEPENDENT_CHILD_CHANGED, ReasonCode.LINEAGE_MISMATCH,
        ReasonCode.SEMANTIC_MISMATCH, ReasonCode.CRITICAL_FIELD_MISMATCH,
    )
    reason = next((item for item in reason_priority if item.value in rejected_reasons), None)
    if reason is None and trace["prefilter_exclusions"]["package"] and not core_filtered:
        reason = ReasonCode.PACKAGE_MISMATCH
    if reason is None:
        reason = ReasonCode.PROVENANCE_PARSE_FAILURE if any_parse_failed else (ReasonCode.NO_MATCH if auth_has_core else ReasonCode.UNSUPPORTED_SOURCE_IDENTITY)
    return finish(ReacquireStatus.REJECTED, reason, count=0)
