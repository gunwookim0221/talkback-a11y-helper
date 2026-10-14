"""Conservative, offline-only node equivalence for Phase 5D-B.

Nothing in this module dispatches actions or grants production authority.  The
identifiers emitted by Phase 5D-A remain snapshot-local unless their provenance
explicitly documents a cross-capture stability scope (the current schema does
not do so for sourceNodeId).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


PRESENT = "PRESENT"
PARSE_FAILED = "PARSE_FAILED"
NOT_SUPPORTED_BY_SOURCE = "NOT_SUPPORTED_BY_SOURCE"


class EquivalenceStatus(str, Enum):
    EXACT = "EXACT"
    STRONG_EQUIVALENT = "STRONG_EQUIVALENT"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"


class ReasonCode(str, Enum):
    EXACT_SNAPSHOT_LOCAL_ID = "EXACT_SNAPSHOT_LOCAL_ID"
    STRONG_EVIDENCE_MATCH = "STRONG_EVIDENCE_MATCH"
    NO_MATCH = "NO_MATCH"
    MULTI_MATCH = "MULTI_MATCH"
    CRITICAL_FIELD_MISMATCH = "CRITICAL_FIELD_MISMATCH"
    SEMANTIC_MISMATCH = "SEMANTIC_MISMATCH"
    STRUCTURAL_MISMATCH = "STRUCTURAL_MISMATCH"
    ACTION_SET_MISMATCH = "ACTION_SET_MISMATCH"
    WINDOW_MISMATCH = "WINDOW_MISMATCH"
    PACKAGE_MISMATCH = "PACKAGE_MISMATCH"
    STALE_SNAPSHOT = "STALE_SNAPSHOT"
    LINEAGE_MISMATCH = "LINEAGE_MISMATCH"
    INDEPENDENT_CHILD_CHANGED = "INDEPENDENT_CHILD_CHANGED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSUPPORTED_SOURCE_IDENTITY = "UNSUPPORTED_SOURCE_IDENTITY"
    INVALID_METADATA = "INVALID_METADATA"
    PROVENANCE_PARSE_FAILURE = "PROVENANCE_PARSE_FAILURE"


@dataclass(frozen=True)
class EquivalenceResult:
    status: EquivalenceStatus
    reason_code: ReasonCode
    matched_fields: tuple[str, ...] = ()
    mismatched_fields: tuple[str, ...] = ()
    unavailable_fields: tuple[str, ...] = ()
    provenance_states: tuple[tuple[str, str, str], ...] = ()
    lineage_comparison: dict[str, Any] | None = None
    child_comparison: dict[str, Any] | None = None
    action_comparison: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["reason_code"] = self.reason_code.value
        return value


FIELD_STRENGTH_POLICY: dict[str, str] = {
    "snapshot_id": "HARD_FRESHNESS_ONLY",
    "package": "HARD_WHEN_BOTH_PRESENT",
    "window_type": "HARD_WHEN_BOTH_PRESENT",
    "window_title": "STRONG_CONTEXT",
    "resource_id": "STRONG_BUT_REUSABLE",
    "class_name": "STRONG_BUT_NON_UNIQUE",
    "semantic_role": "STRONG_IF_PRESENT",
    "text": "VOLATILE_SUPPORTING_ONLY",
    "content_description": "VOLATILE_SUPPORTING_ONLY",
    "source_node_id": "DIAGNOSTIC_ONLY_UNLESS_STABILITY_SCOPE_IS_DECLARED",
    "node_local_id": "DIAGNOSTIC_ONLY_SNAPSHOT_LOCAL",
    "hierarchy_path": "STRUCTURAL_CONTEXT_NOT_CROSS_CAPTURE_ID",
    "ancestor_chain": "STRONG_STRUCTURAL_CONTEXT",
    "sibling_index": "SUPPORTING_ORDER_CONTEXT",
    "descendant_structure": "STRONG_STRUCTURAL_CONTEXT",
    "action_set": "STRONG_WHEN_SOURCE_EXPOSES_IT",
    "bounds": "SUPPORTING_GEOMETRY_ONLY",
    "clickable": "SUPPORTING_CAPABILITY_FLAG_ONLY",
    "focusable": "SUPPORTING_CAPABILITY_FLAG_ONLY",
}


def _field(node: dict[str, Any], group: str, name: str) -> dict[str, Any]:
    value = node.get(group, {}).get(name) if isinstance(node.get(group), dict) else None
    if isinstance(value, dict) and isinstance(value.get("status"), str):
        return value
    return {"value": None, "status": NOT_SUPPORTED_BY_SOURCE}


def _simple(node: dict[str, Any], name: str) -> dict[str, Any]:
    value = node.get(name)
    if isinstance(value, dict) and isinstance(value.get("status"), str):
        return value
    return {"value": None, "status": NOT_SUPPORTED_BY_SOURCE}


def _ancestors(metadata: dict[str, Any], node: dict[str, Any]) -> list[dict[str, Any]] | None:
    lineage = node.get("lineage")
    if not isinstance(lineage, dict):
        return None
    ancestors_result = lineage.get("ancestor_ids_root_to_parent")
    if not isinstance(ancestors_result, dict) or ancestors_result.get("status") != PRESENT:
        return None
    ids = ancestors_result.get("value")
    if not isinstance(ids, list):
        return None
    by_id = {entry.get("node_local_id"): entry for entry in metadata.get("nodes", []) if isinstance(entry, dict)}
    if any(identifier not in by_id for identifier in ids):
        return None
    return [by_id[identifier] for identifier in ids]


def _action_ids(node: dict[str, Any]) -> tuple[str, tuple[tuple[int, str, str | None], ...] | None]:
    action_metadata = node.get("action_metadata")
    actions = action_metadata.get("actions") if isinstance(action_metadata, dict) else None
    if not isinstance(actions, dict):
        return NOT_SUPPORTED_BY_SOURCE, None
    status = actions.get("status", NOT_SUPPORTED_BY_SOURCE)
    raw = actions.get("value")
    if status != PRESENT:
        return str(status), None
    if not isinstance(raw, list):
        return PARSE_FAILED, None
    actions_out: list[tuple[int, str, str | None]] = []
    for item in raw:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            return PARSE_FAILED, None
        name = item.get("normalized_name")
        label = item.get("raw_label")
        if not isinstance(name, str) or (label is not None and not isinstance(label, str)):
            return PARSE_FAILED, None
        actions_out.append((item["id"], name, label))
    return PRESENT, tuple(sorted(actions_out))


def _raw_flag(node: dict[str, Any], name: str) -> dict[str, Any]:
    fields = node.get("provenance", {}).get("fields") if isinstance(node.get("provenance"), dict) else None
    value = fields.get(name) if isinstance(fields, dict) else None
    return value if isinstance(value, dict) else {"value": None, "status": NOT_SUPPORTED_BY_SOURCE}


def _node_signature(node: dict[str, Any], *, include_bounds: bool = False) -> dict[str, Any]:
    signature = {
        "resource_id": _field(node, "semantic_identifiers", "resource_id").get("value"),
        "class_name": _field(node, "semantic_identifiers", "class_name").get("value"),
        "semantic_role": _field(node, "semantic_identifiers", "semantic_role").get("value"),
        "text": _field(node, "semantic_identifiers", "text").get("value"),
        "content_description": _field(node, "semantic_identifiers", "content_description").get("value"),
        "clickable": _raw_flag(node, "clickable").get("value"),
        "focusable": _raw_flag(node, "focusable").get("value"),
    }
    if include_bounds:
        signature["bounds"] = _field(node, "geometric_identifiers", "bounds").get("value")
    return signature


def _subtree_signature(metadata: dict[str, Any], node: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    by_id = {entry.get("node_local_id"): entry for entry in metadata.get("nodes", []) if isinstance(entry, dict)}
    visited: set[str] = set()
    unavailable: list[str] = []

    def visit(current: dict[str, Any]) -> dict[str, Any] | None:
        identifier = current.get("node_local_id")
        if not isinstance(identifier, str) or identifier in visited:
            return None
        visited.add(identifier)
        semantic_fields = current.get("semantic_identifiers")
        for field_name in ("resource_id", "class_name", "semantic_role", "text", "content_description"):
            field_value = semantic_fields.get(field_name) if isinstance(semantic_fields, dict) else None
            if isinstance(field_value, dict) and field_value.get("status") == PARSE_FAILED:
                unavailable.append(f"parse_failed:{identifier}:{field_name}")
                return None
        for field_name in ("clickable", "focusable"):
            if _raw_flag(current, field_name).get("status") == PARSE_FAILED:
                unavailable.append(f"parse_failed:{identifier}:{field_name}")
                return None
        lineage = current.get("lineage")
        children_result = lineage.get("ordered_child_ids") if isinstance(lineage, dict) else None
        if not isinstance(children_result, dict) or children_result.get("status") != PRESENT or not isinstance(children_result.get("value"), list):
            unavailable.append(f"children:{identifier}")
            return None
        children: list[dict[str, Any]] = []
        for child_id in children_result["value"]:
            child = by_id.get(child_id)
            if child is None:
                unavailable.append(f"child_record:{child_id}")
                return None
            child_signature = visit(child)
            if child_signature is None:
                return None
            children.append(child_signature)
        signature = _node_signature(current)
        signature["children"] = children
        return signature

    return visit(node), unavailable


def _has_identifiable_child_context(signature: dict[str, Any] | None) -> bool:
    if not isinstance(signature, dict):
        return False
    children = signature.get("children")
    if not isinstance(children, list):
        return False
    for child in children:
        if any(child.get(key) for key in ("resource_id", "semantic_role", "text", "content_description")):
            return True
        if _has_identifiable_child_context(child):
            return True
    return False


def _compare_subtree_actions(
    authorized_metadata: dict[str, Any], authorized_node: dict[str, Any],
    fresh_metadata: dict[str, Any], fresh_node: dict[str, Any],
) -> dict[str, Any]:
    old_by_id = {entry.get("node_local_id"): entry for entry in authorized_metadata.get("nodes", []) if isinstance(entry, dict)}
    new_by_id = {entry.get("node_local_id"): entry for entry in fresh_metadata.get("nodes", []) if isinstance(entry, dict)}
    changes: list[dict[str, Any]] = []
    unavailable: list[str] = []
    parse_failures: list[str] = []

    def visit(old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        old_status, old_ids = _action_ids(old)
        new_status, new_ids = _action_ids(new)
        if PARSE_FAILED in (old_status, new_status):
            parse_failures.append(path)
        elif old_status == PRESENT and new_status == PRESENT and old_ids != new_ids:
            changes.append({"path": path, "authorized_ids": list(old_ids or ()), "fresh_ids": list(new_ids or ())})
        elif old_status != PRESENT or new_status != PRESENT:
            unavailable.append(path)
        old_children = old.get("lineage", {}).get("ordered_child_ids", {}).get("value")
        new_children = new.get("lineage", {}).get("ordered_child_ids", {}).get("value")
        if not isinstance(old_children, list) or not isinstance(new_children, list) or len(old_children) != len(new_children):
            return
        for index, (old_id, new_id) in enumerate(zip(old_children, new_children)):
            old_child, new_child = old_by_id.get(old_id), new_by_id.get(new_id)
            if old_child is not None and new_child is not None:
                visit(old_child, new_child, f"{path}/{index}")

    visit(authorized_node, fresh_node, "root")
    if parse_failures:
        return {"state": "PARSE_FAILED", "paths": parse_failures, "unavailable_paths": unavailable}
    if changes:
        return {"state": "MISMATCH", "changes": changes, "unavailable_paths": unavailable}
    return {"state": "MATCH" if not unavailable else "PARTIAL", "unavailable_paths": unavailable}


def _window_context(metadata: dict[str, Any], node: dict[str, Any]) -> dict[str, Any] | None:
    structural = node.get("structural_identifiers")
    index_field = structural.get("window_index") if isinstance(structural, dict) else None
    if not isinstance(index_field, dict) or type(index_field.get("value")) is not int:
        return None
    windows = metadata.get("snapshot", {}).get("windows")
    if not isinstance(windows, list) or index_field["value"] >= len(windows):
        return None
    return windows[index_field["value"]]


def _compare_lineage(auth_meta: dict[str, Any], auth: dict[str, Any], fresh_meta: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    old_chain = _ancestors(auth_meta, auth)
    new_chain = _ancestors(fresh_meta, fresh)
    if old_chain is None or new_chain is None:
        return {"state": "UNAVAILABLE", "reason": "ancestor_chain_not_complete", "old_depth": None if old_chain is None else len(old_chain), "new_depth": None if new_chain is None else len(new_chain)}
    if len(old_chain) != len(new_chain):
        return {"state": "MISMATCH", "reason": "ancestor_depth_changed", "old_depth": len(old_chain), "new_depth": len(new_chain)}
    for current in [*old_chain, *new_chain]:
        fields = current.get("semantic_identifiers", {})
        if any(isinstance(fields.get(name), dict) and fields[name].get("status") == PARSE_FAILED for name in ("resource_id", "class_name", "semantic_role", "text", "content_description")):
            return {"state": "UNAVAILABLE", "reason": "ancestor_identity_parse_failed"}
    old_signatures = [_node_signature(item) for item in old_chain]
    new_signatures = [_node_signature(item) for item in new_chain]
    old_siblings = [_simple(item.get("structural_identifiers", {}), "sibling_index").get("value") for item in old_chain]
    new_siblings = [_simple(item.get("structural_identifiers", {}), "sibling_index").get("value") for item in new_chain]
    if old_signatures != new_signatures:
        return {"state": "MISMATCH", "reason": "ancestor_identity_pattern_changed", "old": old_signatures, "new": new_signatures, "sibling_indices_old": old_siblings, "sibling_indices_new": new_siblings}
    if old_siblings != new_siblings:
        return {"state": "MISMATCH", "reason": "ancestor_sibling_order_changed", "sibling_indices_old": old_siblings, "sibling_indices_new": new_siblings}
    return {"state": "MATCH", "depth": len(old_chain), "signature": old_signatures, "sibling_indices": old_siblings}


def compare_nodes(
    authorized_metadata: dict[str, Any],
    authorized_node: dict[str, Any],
    fresh_metadata: dict[str, Any],
    candidate_node: dict[str, Any],
) -> EquivalenceResult:
    """Compare one authorized record with one candidate without fuzzy scoring."""
    def valid_metadata(metadata: Any) -> bool:
        return isinstance(metadata, dict) and metadata.get("schema_name") == "talkback.read_only_hierarchy_identity" and metadata.get("schema_version") == "1.0" and isinstance(metadata.get("snapshot"), dict) and isinstance(metadata.get("snapshot", {}).get("snapshot_id"), str) and isinstance(metadata.get("nodes"), list)

    if not valid_metadata(authorized_metadata) or not valid_metadata(fresh_metadata):
        return EquivalenceResult(EquivalenceStatus.REJECTED, ReasonCode.INVALID_METADATA)
    if not isinstance(authorized_node, dict) or not isinstance(candidate_node, dict):
        return EquivalenceResult(EquivalenceStatus.REJECTED, ReasonCode.INVALID_METADATA)
    auth_records = {item.get("node_local_id") for item in authorized_metadata["nodes"] if isinstance(item, dict)}
    fresh_records = {item.get("node_local_id") for item in fresh_metadata["nodes"] if isinstance(item, dict)}
    if authorized_node.get("node_local_id") not in auth_records or candidate_node.get("node_local_id") not in fresh_records:
        return EquivalenceResult(EquivalenceStatus.REJECTED, ReasonCode.INVALID_METADATA)
    matched: list[str] = []
    mismatched: list[str] = []
    unavailable: list[str] = []
    states: list[tuple[str, str, str]] = []
    auth_snapshot = authorized_metadata.get("snapshot", {}).get("snapshot_id")
    fresh_snapshot = fresh_metadata.get("snapshot", {}).get("snapshot_id")
    if auth_snapshot == fresh_snapshot:
        if authorized_node.get("node_local_id") == candidate_node.get("node_local_id"):
            return EquivalenceResult(EquivalenceStatus.EXACT, ReasonCode.EXACT_SNAPSHOT_LOCAL_ID, ("snapshot_id", "node_local_id"), evidence={"cross_capture": False})
        return EquivalenceResult(EquivalenceStatus.REJECTED, ReasonCode.STALE_SNAPSHOT, mismatched_fields=("distinct_node_local_id_in_same_snapshot",), evidence={"cross_capture": False})

    def compare_field(label: str, old: dict[str, Any], new: dict[str, Any]) -> None:
        old_status, new_status = old.get("status", NOT_SUPPORTED_BY_SOURCE), new.get("status", NOT_SUPPORTED_BY_SOURCE)
        states.append((label, str(old_status), str(new_status)))
        if old_status == PARSE_FAILED or new_status == PARSE_FAILED:
            mismatched.append(label)
            return
        if old_status == PRESENT and new_status == PRESENT:
            if old.get("value") != new.get("value"):
                mismatched.append(label)
                return
            matched.append(label)
            return
        unavailable.append(label)

    old_package = _field(authorized_node, "semantic_identifiers", "package")
    new_package = _field(candidate_node, "semantic_identifiers", "package")
    compare_field("package", old_package, new_package)
    old_resource = _field(authorized_node, "semantic_identifiers", "resource_id")
    new_resource = _field(candidate_node, "semantic_identifiers", "resource_id")
    compare_field("resource_id", old_resource, new_resource)
    old_class = _field(authorized_node, "semantic_identifiers", "class_name")
    new_class = _field(candidate_node, "semantic_identifiers", "class_name")
    compare_field("class_name", old_class, new_class)

    semantic_mismatch = False
    semantic_matched = False
    for key in ("semantic_role", "text", "content_description"):
        old, new = _field(authorized_node, "semantic_identifiers", key), _field(candidate_node, "semantic_identifiers", key)
        old_status, new_status = old.get("status", NOT_SUPPORTED_BY_SOURCE), new.get("status", NOT_SUPPORTED_BY_SOURCE)
        states.append((key, str(old_status), str(new_status)))
        if old_status == PARSE_FAILED or new_status == PARSE_FAILED:
            mismatched.append(key)
            semantic_mismatch = True
        elif old_status == PRESENT and new_status == PRESENT:
            if old.get("value") != new.get("value"):
                mismatched.append(key)
                semantic_mismatch = True
            else:
                matched.append(key)
                if key in ("semantic_role", "text", "content_description") and old.get("value"):
                    semantic_matched = True
        else:
            unavailable.append(key)

    old_window = _window_context(authorized_metadata, authorized_node)
    new_window = _window_context(fresh_metadata, candidate_node)
    window_comparison: dict[str, Any] = {"state": "UNAVAILABLE"}
    if old_window is not None and new_window is not None:
        window_mismatch = False
        for key in ("type", "title"):
            old, new = old_window.get(key, {}), new_window.get(key, {})
            old_status, new_status = old.get("status", NOT_SUPPORTED_BY_SOURCE), new.get("status", NOT_SUPPORTED_BY_SOURCE)
            states.append((f"window.{key}", str(old_status), str(new_status)))
            if old_status == PARSE_FAILED or new_status == PARSE_FAILED:
                mismatched.append(f"window.{key}")
                window_mismatch = True
            elif old_status == PRESENT and new_status == PRESENT:
                if old.get("value") != new.get("value"):
                    mismatched.append(f"window.{key}")
                    window_mismatch = True
                else:
                    matched.append(f"window.{key}")
            else:
                unavailable.append(f"window.{key}")
        # Numeric window IDs are intentionally not compared across captures.
        window_comparison = {"state": "MISMATCH" if window_mismatch else "MATCH", "numeric_window_id_comparison": "IGNORED_ACROSS_CAPTURES"}

    lineage = _compare_lineage(authorized_metadata, authorized_node, fresh_metadata, candidate_node)
    sibling_position_changed = False
    old_sibling = _simple(authorized_node.get("structural_identifiers", {}), "sibling_index")
    new_sibling = _simple(candidate_node.get("structural_identifiers", {}), "sibling_index")
    states.append(("sibling_index", str(old_sibling.get("status", NOT_SUPPORTED_BY_SOURCE)), str(new_sibling.get("status", NOT_SUPPORTED_BY_SOURCE))))
    if old_sibling.get("status") == PARSE_FAILED or new_sibling.get("status") == PARSE_FAILED:
        lineage = {"state": "MISMATCH", "reason": "sibling_index_parse_failed"}
    elif old_sibling.get("status") == PRESENT and new_sibling.get("status") == PRESENT and old_sibling.get("value") != new_sibling.get("value"):
        sibling_position_changed = True
        unavailable.append("sibling_index")
    elif old_sibling.get("status") != PRESENT or new_sibling.get("status") != PRESENT:
        unavailable.append("sibling_index")
    else:
        matched.append("sibling_index")
    if lineage["state"] == "MATCH":
        matched.append("lineage")
    elif lineage["state"] == "MISMATCH":
        mismatched.append("lineage")
    else:
        unavailable.append("lineage")

    old_subtree, old_subtree_unavailable = _subtree_signature(authorized_metadata, authorized_node)
    new_subtree, new_subtree_unavailable = _subtree_signature(fresh_metadata, candidate_node)
    child_comparison: dict[str, Any]
    if old_subtree is None or new_subtree is None:
        child_comparison = {"state": "UNAVAILABLE", "old_unavailable": old_subtree_unavailable, "new_unavailable": new_subtree_unavailable}
        unavailable.append("descendant_structure")
    else:
        # Root semantic fields were already compared. This full signature check
        # also protects independent descendants and their ordered ownership.
        if old_subtree == new_subtree:
            child_comparison = {"state": "MATCH", "authorized_signature": old_subtree}
            matched.append("descendant_structure")
        else:
            child_comparison = {"state": "MISMATCH", "reason": "subtree_signature_changed", "authorized_signature": old_subtree, "fresh_signature": new_subtree}
            mismatched.append("descendant_structure")

    subtree_actions = _compare_subtree_actions(authorized_metadata, authorized_node, fresh_metadata, candidate_node)
    if subtree_actions["state"] in ("MISMATCH", "PARSE_FAILED"):
        mismatched.append("descendant_actions")
    elif subtree_actions["state"] == "MATCH":
        matched.append("descendant_actions")
    else:
        unavailable.append("descendant_actions")

    old_actions, old_action_ids = _action_ids(authorized_node)
    new_actions, new_action_ids = _action_ids(candidate_node)
    states.append(("actions", old_actions, new_actions))
    if old_actions == PARSE_FAILED or new_actions == PARSE_FAILED:
        action_comparison = {"state": "PARSE_FAILED", "authorized_status": old_actions, "fresh_status": new_actions}
        mismatched.append("actions")
    elif old_actions == PRESENT and new_actions == PRESENT:
        if old_action_ids != new_action_ids:
            action_comparison = {"state": "MISMATCH", "authorized_ids": old_action_ids, "fresh_ids": new_action_ids}
            mismatched.append("actions")
        else:
            action_comparison = {"state": "MATCH", "ids": old_action_ids}
            matched.append("actions")
    else:
        action_comparison = {"state": "UNAVAILABLE", "authorized_status": old_actions, "fresh_status": new_actions}
        unavailable.append("actions")

    old_bounds = _field(authorized_node, "geometric_identifiers", "bounds")
    new_bounds = _field(candidate_node, "geometric_identifiers", "bounds")
    geometry_comparison = {
        "authorized": old_bounds,
        "fresh": new_bounds,
        "state": "UNCHANGED" if old_bounds.get("status") == PRESENT and new_bounds.get("status") == PRESENT and old_bounds.get("value") == new_bounds.get("value") else "CHANGED_OR_UNAVAILABLE",
        "identity_weight": "SUPPORTING_ONLY",
    }

    if mismatched:
        if any(PARSE_FAILED in state[1:] for state in states):
            reason = ReasonCode.PROVENANCE_PARSE_FAILURE
        elif "package" in mismatched:
            reason = ReasonCode.PACKAGE_MISMATCH
        elif any(item.startswith("window.") for item in mismatched):
            reason = ReasonCode.WINDOW_MISMATCH
        elif "actions" in mismatched or "descendant_actions" in mismatched:
            reason = ReasonCode.ACTION_SET_MISMATCH
        elif "descendant_structure" in mismatched:
            reason = ReasonCode.INDEPENDENT_CHILD_CHANGED
        elif "lineage" in mismatched:
            reason = ReasonCode.LINEAGE_MISMATCH
        elif any(item in ("text", "content_description", "semantic_role") for item in mismatched):
            reason = ReasonCode.SEMANTIC_MISMATCH
        else:
            reason = ReasonCode.CRITICAL_FIELD_MISMATCH
        return EquivalenceResult(EquivalenceStatus.REJECTED, reason, tuple(matched), tuple(mismatched), tuple(unavailable), tuple(states), lineage, child_comparison, action_comparison, {"window": window_comparison, "geometry": geometry_comparison})

    core_ready = old_package.get("status") == PRESENT and new_package.get("status") == PRESENT and old_resource.get("status") == PRESENT and new_resource.get("status") == PRESENT and old_class.get("status") == PRESENT and new_class.get("status") == PRESENT
    core_equal = old_package.get("value") == new_package.get("value") and old_resource.get("value") == new_resource.get("value") and old_class.get("value") == new_class.get("value")
    structural_ready = lineage.get("state") == "MATCH" and child_comparison.get("state") == "MATCH"
    # Equal semantic labels support identity only in combination with core and
    # full structural agreement. When labels are unavailable, a non-empty,
    # unchanged descendant structure can provide a separate contextual proof.
    child_context = _has_identifiable_child_context(old_subtree) and old_subtree == new_subtree
    if semantic_mismatch:
        return EquivalenceResult(EquivalenceStatus.REJECTED, ReasonCode.SEMANTIC_MISMATCH, tuple(matched), tuple(mismatched), tuple(unavailable), tuple(states), lineage, child_comparison, action_comparison, {"window": window_comparison, "geometry": geometry_comparison})
    if core_ready and core_equal and structural_ready and (semantic_matched or child_context) and not sibling_position_changed:
        return EquivalenceResult(EquivalenceStatus.STRONG_EQUIVALENT, ReasonCode.STRONG_EVIDENCE_MATCH, tuple(matched), tuple(mismatched), tuple(unavailable), tuple(states), lineage, child_comparison, action_comparison, {"window": window_comparison, "geometry": geometry_comparison, "semantic_evidence": semantic_matched, "child_context_evidence": child_context})
    if core_ready and core_equal:
        reason = ReasonCode.STRUCTURAL_MISMATCH if sibling_position_changed else ReasonCode.INSUFFICIENT_EVIDENCE
        evidence = {"window": window_comparison, "geometry": geometry_comparison, "required": ["matching_package_resource_class", "matching_lineage", "matching_child_structure", "semantic_or_nonempty_child_context"], "sibling_position_changed": sibling_position_changed}
        return EquivalenceResult(EquivalenceStatus.AMBIGUOUS, reason, tuple(matched), tuple(mismatched), tuple(unavailable), tuple(states), lineage, child_comparison, action_comparison, evidence)
    return EquivalenceResult(EquivalenceStatus.REJECTED, ReasonCode.INSUFFICIENT_EVIDENCE, tuple(matched), tuple(mismatched), tuple(unavailable), tuple(states), lineage, child_comparison, action_comparison, {"window": window_comparison, "geometry": geometry_comparison})
