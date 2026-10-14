from __future__ import annotations

import copy

import pytest

from talkback_lib.hierarchy_identity import build_hierarchy_identity_metadata
from talkback_lib.node_equivalence import EquivalenceStatus, ReasonCode, compare_nodes
from talkback_lib.node_reacquire import ReacquireStatus, reacquire_node


def _node(name: str, *, children=None, **overrides):
    value = {
        "sourceNodeId": f"unstable-source:{name}",
        "viewIdResourceName": f"com.example:id/{name}",
        "className": "android.widget.Button",
        "text": name.replace("_", " "),
        "contentDescription": None,
        "roleDescription": "button",
        "packageName": "com.example",
        "boundsInScreen": {"left": 10, "top": 20, "right": 110, "bottom": 70},
        "clickable": True,
        "focusable": True,
        "enabled": True,
        "selected": False,
        "accessibilityFocused": False,
        "inputFocused": False,
        "scrollable": False,
        "visibleToUser": True,
        "windowId": 7,
        "actions": [{"id": 16, "name": "ACTION_CLICK", "label": None}],
        "children": children or [],
    }
    value.update(overrides)
    return value


def _raw(root, *, package="com.example", window_type=1, window_title="Main", window_id=7):
    root = copy.deepcopy(root)

    def set_package(node):
        node["packageName"] = package
        for child in node.get("children", []):
            set_package(child)

    set_package(root)
    return {
        "reqId": "request",
        "success": True,
        "schemaVersion": "service-hierarchy-v1",
        "source": "accessibility_service_windows",
        "nodeMetadataCapabilities": {
            "source_node_id": True, "resource_id": True, "class_name": True,
            "text": True, "content_description": True, "semantic_role": True,
            "bounds": True, "clickable": True, "focusable": True,
            "enabled": True, "selected": True, "accessibility_focused": True,
            "input_focused": True, "actions": True, "window_id": True,
            "package": True, "semantic_role": True,
        },
        "windows": [{
            "order": 0, "id": window_id, "type": window_type, "title": window_title,
            "active": True, "focused": True,
            "boundsInScreen": {"left": 0, "top": 0, "right": 500, "bottom": 900},
            "root": root,
        }],
    }


def _meta(capture, root, **kwargs):
    raw = _raw(root, **kwargs)
    raw["reqId"] = f"request-{capture}"
    sequence = 1 if capture == "auth" else 2
    return build_hierarchy_identity_metadata(raw, capture_id=capture, capture_sequence=sequence)


def _by_text(metadata, text):
    return next(node for node in metadata["nodes"] if node["semantic_identifiers"]["text"]["value"] == text)


def _simple_pair(*, auth_root=None, fresh_root=None, fresh_kwargs=None):
    auth = _meta("auth", auth_root or _node("root", children=[_node("target")]))
    fresh = _meta("fresh", fresh_root or _node("root", children=[_node("target")]), **(fresh_kwargs or {}))
    return auth, fresh, _by_text(auth, "target")


def test_same_logical_node_with_moved_bounds_reacquires_proven():
    auth_root = _node("root", children=[_node("target", boundsInScreen="[10,20][110,70]")])
    fresh_root = _node("root", children=[_node("target", boundsInScreen="[10,420][110,470]")])
    auth, fresh = _meta("auth", auth_root), _meta("fresh", fresh_root, window_id=19)
    target = _by_text(auth, "target")

    result = reacquire_node(auth, target["node_local_id"], fresh)

    assert result.status == ReacquireStatus.PROVEN
    assert result.reason_code == ReasonCode.STRONG_EVIDENCE_MATCH
    evaluation = result.trace["candidate_evaluations"][0]
    assert evaluation["evidence"]["geometry"]["state"] == "CHANGED_OR_UNAVAILABLE"
    assert evaluation["evidence"]["geometry"]["identity_weight"] == "SUPPORTING_ONLY"
    assert result.trace["snapshot_relation"]["fingerprint_is_generation_proof"] is False


def test_capture_id_change_is_required_and_same_snapshot_is_stale():
    auth, fresh, target = _simple_pair()
    assert reacquire_node(auth, target["node_local_id"], fresh).status == ReacquireStatus.PROVEN
    same_capture = copy.deepcopy(auth)
    stale = reacquire_node(auth, target["node_local_id"], same_capture)
    assert stale.status == ReacquireStatus.REJECTED
    assert stale.reason_code == ReasonCode.STALE_SNAPSHOT


def test_exact_identity_is_only_snapshot_local_and_distinct_local_nodes_are_not_exact():
    auth, _fresh, target = _simple_pair()
    exact = compare_nodes(auth, target, auth, target)
    assert exact.status == EquivalenceStatus.EXACT
    other = next(node for node in auth["nodes"] if node["node_local_id"] != target["node_local_id"])
    not_exact = compare_nodes(auth, target, auth, other)
    assert not_exact.status == EquivalenceStatus.REJECTED
    assert not_exact.reason_code == ReasonCode.STALE_SNAPSHOT


def test_reused_source_request_or_nonincreasing_capture_sequence_is_stale():
    auth, fresh, target = _simple_pair()
    repeated_request = copy.deepcopy(fresh)
    repeated_request["snapshot"]["request_id"] = copy.deepcopy(auth["snapshot"]["request_id"])
    stale_request = reacquire_node(auth, target["node_local_id"], repeated_request)
    assert stale_request.reason_code == ReasonCode.STALE_SNAPSHOT
    assert stale_request.trace["stale_evidence"] == "same_source_request_id"

    repeated_sequence = copy.deepcopy(fresh)
    repeated_sequence["snapshot"]["capture_sequence"]["value"] = auth["snapshot"]["capture_sequence"]["value"]
    stale_sequence = reacquire_node(auth, target["node_local_id"], repeated_sequence)
    assert stale_sequence.reason_code == ReasonCode.STALE_SNAPSHOT


def test_duplicate_semantic_target_is_ambiguous_without_nearest_or_order_choice():
    auth = _meta("auth", _node("root", children=[_node("target")]))
    fresh = _meta("fresh", _node("root", children=[_node("target"), _node("target_duplicate")]))
    duplicate = fresh["nodes"][-1]
    duplicate["semantic_identifiers"]["resource_id"]["value"] = "com.example:id/target"
    duplicate["semantic_identifiers"]["text"]["value"] = "target"
    duplicate["source_node_id"]["value"] = "unstable-source:target"
    duplicate["strong_raw_identifiers"]["resource_id"]["value"] = "com.example:id/target"
    target = _by_text(auth, "target")

    result = reacquire_node(auth, target["node_local_id"], fresh)

    assert result.status == ReacquireStatus.AMBIGUOUS
    assert result.reason_code == ReasonCode.MULTI_MATCH
    assert result.matched_node_id is None


def test_resource_id_reuse_under_different_parent_is_rejected_by_lineage():
    auth = _meta("auth", _node("root", children=[_node("parent_a", children=[_node("target")])]))
    fresh = _meta("fresh", _node("root", children=[_node("parent_b", children=[_node("target")])]))
    target = _by_text(auth, "target")

    result = reacquire_node(auth, target["node_local_id"], fresh)

    assert result.status == ReacquireStatus.REJECTED
    assert result.reason_code == ReasonCode.LINEAGE_MISMATCH


def test_independent_child_change_rejects_parent_equivalence():
    auth_root = _node("root", children=[_node("card", children=[_node("control_a"), _node("control_b")])])
    fresh_root = _node("root", children=[_node("card", children=[_node("control_a"), _node("control_c")])])
    auth, fresh = _meta("auth", auth_root), _meta("fresh", fresh_root)
    card = _by_text(auth, "card")
    fresh_card = next(node for node in fresh["nodes"] if node["semantic_identifiers"]["resource_id"]["value"] == "com.example:id/card")

    comparison = compare_nodes(auth, card, fresh, fresh_card)
    result = reacquire_node(auth, card["node_local_id"], fresh)

    assert comparison.status == EquivalenceStatus.REJECTED
    assert result.reason_code == ReasonCode.INDEPENDENT_CHILD_CHANGED


def test_action_set_change_is_rejected_without_inference_from_clickable_flag():
    auth, fresh, target = _simple_pair()
    fresh_target = _by_text(fresh, "target")
    fresh_target["action_metadata"]["actions"]["value"] = [
        {"id": 16, "normalized_name": "ACTION_CLICK", "raw_name": "ACTION_CLICK", "raw_label": None, "exactness": "ID_NAME_LABEL"},
        {"id": 32, "normalized_name": "ACTION_LONG_CLICK", "raw_name": "ACTION_LONG_CLICK", "raw_label": None, "exactness": "ID_NAME_LABEL"},
    ]
    comparison = compare_nodes(auth, target, fresh, fresh_target)

    assert comparison.status == EquivalenceStatus.REJECTED
    assert comparison.reason_code == ReasonCode.ACTION_SET_MISMATCH
    assert comparison.action_comparison["state"] == "MISMATCH"


def test_accessibility_action_name_or_label_change_is_a_semantic_action_change():
    auth, fresh, target = _simple_pair()
    candidate = _by_text(fresh, "target")
    candidate["action_metadata"]["actions"]["value"][0]["raw_label"] = "Different operation"
    comparison = compare_nodes(auth, target, fresh, candidate)
    assert comparison.status == EquivalenceStatus.REJECTED
    assert comparison.reason_code == ReasonCode.ACTION_SET_MISMATCH


@pytest.mark.parametrize("case", ["recycled_text", "same_bounds_new_label", "same_label_new_resource"])
def test_recycled_or_rebound_items_never_match_by_single_field(case):
    auth_node = _node("target")
    fresh_node = _node("target")
    if case == "recycled_text":
        fresh_node["text"] = "different item"
    elif case == "same_bounds_new_label":
        fresh_node["text"] = "different label"
    else:
        fresh_node["viewIdResourceName"] = "com.example:id/other"
    auth, fresh = _meta("auth", _node("root", children=[auth_node])), _meta("fresh", _node("root", children=[fresh_node]))
    result = reacquire_node(auth, _by_text(auth, "target")["node_local_id"], fresh)
    assert result.status == ReacquireStatus.REJECTED


def test_reused_resource_id_multiple_instances_is_ambiguous():
    auth = _meta("auth", _node("root", children=[_node("target")]))
    fresh = _meta("fresh", _node("root", children=[_node("target"), _node("target")]))
    result = reacquire_node(auth, _by_text(auth, "target")["node_local_id"], fresh)
    assert result.status == ReacquireStatus.AMBIGUOUS


def test_sibling_reorder_and_inserted_wrapper_reject_structural_rebind():
    auth = _meta("auth", _node("root", children=[_node("target"), _node("other")]))
    reordered = _meta("reordered", _node("root", children=[_node("other"), _node("target")]))
    target = _by_text(auth, "target")
    assert reacquire_node(auth, target["node_local_id"], reordered).status != ReacquireStatus.PROVEN

    wrapped = _meta("wrapped", _node("root", children=[_node("wrapper", children=[_node("target")])]))
    result = reacquire_node(auth, target["node_local_id"], wrapped)
    assert result.status == ReacquireStatus.REJECTED


def test_window_and_package_change_reject_even_when_node_labels_match():
    auth, fresh, target = _simple_pair(fresh_kwargs={"window_type": 2, "window_title": "Dialog"})
    window = reacquire_node(auth, target["node_local_id"], fresh)
    assert window.status == ReacquireStatus.REJECTED
    assert window.reason_code == ReasonCode.WINDOW_MISMATCH

    package_changed = _meta("pkg", _node("root", children=[_node("target")]), package="other.package")
    package_result = reacquire_node(auth, target["node_local_id"], package_changed)
    assert package_result.status == ReacquireStatus.REJECTED
    assert package_result.reason_code == ReasonCode.PACKAGE_MISMATCH


def test_provenance_states_are_distinct_and_parse_failure_is_rejected():
    auth, fresh, target = _simple_pair()
    sparse = _by_text(fresh, "target")
    sparse["semantic_identifiers"]["content_description"] = {"value": None, "status": "NOT_SUPPORTED_BY_SOURCE"}
    comparison = compare_nodes(auth, target, fresh, sparse)
    assert comparison.status == EquivalenceStatus.STRONG_EQUIVALENT
    assert ("content_description", "ABSENT_IN_SOURCE", "NOT_SUPPORTED_BY_SOURCE") in comparison.provenance_states

    broken = copy.deepcopy(sparse)
    broken["semantic_identifiers"]["resource_id"] = {"value": None, "status": "PARSE_FAILED"}
    failed = compare_nodes(auth, target, fresh, broken)
    assert failed.status == EquivalenceStatus.REJECTED
    assert failed.reason_code == ReasonCode.PROVENANCE_PARSE_FAILURE


def test_unstable_source_node_id_is_not_used_as_cross_capture_proof():
    auth, fresh, target = _simple_pair()
    candidate = _by_text(fresh, "target")
    candidate["source_node_id"]["value"] = "different-unique-id"
    result = compare_nodes(auth, target, fresh, candidate)
    assert result.status == EquivalenceStatus.STRONG_EQUIVALENT
    assert "source_node_id" not in result.matched_fields


def test_not_supported_action_data_is_not_inferred_from_clickable():
    auth, fresh, target = _simple_pair()
    candidate = _by_text(fresh, "target")
    candidate["action_metadata"]["actions"] = {"value": None, "status": "NOT_SUPPORTED_BY_SOURCE"}
    comparison = compare_nodes(auth, target, fresh, candidate)
    assert comparison.status == EquivalenceStatus.STRONG_EQUIVALENT
    assert comparison.action_comparison["state"] == "UNAVAILABLE"
    assert candidate["provenance"]["fields"]["clickable"]["value"] is True


def test_candidate_trace_explains_counts_and_provenance():
    auth, fresh, target = _simple_pair()
    result = reacquire_node(auth, target["node_local_id"], fresh)
    assert result.trace["candidate_count_before_filtering"] == len(fresh["nodes"])
    assert result.trace["filters"][-1]["proven"] == 1
    assert result.trace["candidate_evaluations"][0]["provenance_states"]
    assert result.trace["candidate_evaluations"][0]["lineage_comparison"]["state"] == "MATCH"
