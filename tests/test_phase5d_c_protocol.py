from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

import pytest

from talkback_lib.exact_node_protocol import (
    ACTION_TYPE,
    PROTOCOL_VERSION,
    AppendOnlyProtocolAudit,
    ExactNodeAck,
    ExactNodeRequest,
    FailureCode,
    HelperIdentityStatus,
    OneShotRequestRegistry,
    ProtocolValidationError,
    build_target_descriptor,
    create_resolve_request,
    precheck_helper_build_identity,
    resolve_exact_request,
)
from talkback_lib.helper_bridge import HelperBridge


PACKAGE = "com.example.smartthings"
WINDOW = {"id": 7, "type": 1}


def stamp(delta_seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def node(*, resource="com.example.smartthings:id/control", class_name="android.widget.Button", text="Open",
         description=None, bounds=(10, 20, 110, 70), source_id=None, children=None, actions=None):
    return {
        "packageName": PACKAGE,
        "viewIdResourceName": resource,
        "className": class_name,
        "text": text,
        "contentDescription": description,
        "sourceNodeId": source_id,
        "boundsInScreen": {"left": bounds[0], "top": bounds[1], "right": bounds[2], "bottom": bounds[3]},
        "clickable": True,
        "focusable": True,
        "enabled": True,
        "visibleToUser": True,
        "actions": actions if actions is not None else [{"id": 16, "name": "ACTION_CLICK", "label": None}],
        "children": children if children is not None else [],
    }


def raw_hierarchy(*, snapshot_id, target=None, root_class="android.widget.FrameLayout", extra_nodes=()):
    target = deepcopy(target or node())
    root = node(resource="com.example.smartthings:id/root", class_name=root_class, text=None,
                description=None, bounds=(0, 0, 400, 800), children=[target, *deepcopy(list(extra_nodes))],
                actions=[])
    root["clickable"] = False
    root["focusable"] = False
    return {
        "success": True,
        "snapshot_id": snapshot_id,
        "windows": [{"order": 0, "id": WINDOW["id"], "type": WINDOW["type"], "root": root}],
    }


def make_request(*, target_snapshot="B", target=None, now=None):
    target_hierarchy = raw_hierarchy(snapshot_id=target_snapshot, target=target)
    descriptor = build_target_descriptor(target_hierarchy, window_index=0, child_indices=[0], snapshot_id=target_snapshot)
    request = create_resolve_request(
        descriptor,
        request_id=f"req:{uuid.uuid4()}", transaction_id=f"tx:{uuid.uuid4()}",
        permit_id=f"permit:{uuid.uuid4()}", request_nonce=f"nonce:{uuid.uuid4()}",
        ownership={"run_id": "run:synthetic", "scenario_id": "scenario:synthetic",
                   "scenario_transaction_id": "scenario-tx:1", "step_action_id": "step:1", "parent_action_id": None},
        authorized_snapshot_id="A", helper_service_instance_id="helper:epoch:1", host_session_id="host:session:1",
        source_request_id="capture:B", stop_epoch="stop:0", created_at=now or stamp(-1), expires_at=stamp(30),
        window_type=WINDOW["type"],
    )
    return request


def current_hierarchy(*, snapshot_id="C", target=None, root_class="android.widget.FrameLayout", extra_nodes=()):
    result = raw_hierarchy(snapshot_id=snapshot_id, target=target, root_class=root_class, extra_nodes=extra_nodes)
    result["snapshotId"] = snapshot_id
    return result


def code(result):
    return result["failure_code"]


def test_request_schema_resolves_single_exact_node_and_ack_is_read_only():
    request = make_request()
    result = resolve_exact_request(request, current_hierarchy(target=node()))
    assert result["resolved"] is True
    assert result["candidate_count"] == 1
    assert result["perform_action_called"] is False
    assert result["perform_action_call_count"] == 0
    assert result["perform_action_return"] is None
    assert result["visit_authority"] is False
    ack = ExactNodeAck.parse(result, request)
    assert ack.data["reacquire_verdict"] == "RESOLVED"
    resolved_identity = ack.data["resolved_target_identity"]
    assert resolved_identity["snapshot_id"] == "C"
    assert resolved_identity["bounds"] == node()["boundsInScreen"]
    assert resolved_identity["node_local_id"] == "C:0:0"
    assert ack.data["resolved_lineage_summary"] == resolved_identity["lineage_signature"]
    assert ack.data["resolved_child_structure_summary"] == resolved_identity["child_structure_signature"]


def test_bounds_are_supporting_only_but_same_resource_other_instances_are_not_collapsed():
    request = make_request()
    moved = node(bounds=(75, 120, 175, 170))
    moved_result = resolve_exact_request(request, current_hierarchy(target=moved))
    assert moved_result["resolved"] is True
    assert moved_result["resolved_target_identity"]["bounds"] == moved["boundsInScreen"]
    duplicate_instance = node(bounds=(200, 120, 300, 170))
    result = resolve_exact_request(request, current_hierarchy(target=moved, extra_nodes=[duplicate_instance]))
    assert result["resolved"] is False
    assert code(result) == FailureCode.TARGET_MULTI_MATCH.value


def test_source_node_id_absence_is_not_fabricated_and_present_change_is_rejected():
    request_absent = make_request()
    fresh_id = node(source_id="platform-uid-C")
    result = resolve_exact_request(request_absent, current_hierarchy(target=fresh_id))
    assert result["resolved"] is True
    assert result["resolved_source_node_id"] == "platform-uid-C"
    request_present = make_request(target=node(source_id="platform-uid-B"))
    changed_id = resolve_exact_request(request_present, current_hierarchy(target=node(source_id="platform-uid-C")))
    assert code(changed_id) == FailureCode.SOURCE_NODE_ID_MISMATCH.value


def test_snapshot_changes_are_required_and_stale_capture_is_rejected():
    request = make_request()
    stale = resolve_exact_request(request, current_hierarchy(snapshot_id="B", target=node()))
    assert code(stale) == FailureCode.SNAPSHOT_STALE.value
    moved_capture = resolve_exact_request(request, current_hierarchy(snapshot_id="C", target=node()))
    assert moved_capture["resolved"] is True


def test_duplicate_resource_under_other_parent_fails_closed():
    request = make_request()
    other_parent_target = node()
    second_parent = node(resource="com.example.smartthings:id/other_parent", class_name="android.widget.LinearLayout",
                         text=None, description=None, children=[other_parent_target], actions=[])
    second_parent["clickable"] = False
    second_parent["focusable"] = False
    # The second target is also placed in the same current tree with the same resource/class.
    duplicate = node()
    current = current_hierarchy(target=duplicate, extra_nodes=[other_parent_target])
    current["windows"][0]["root"]["children"][1] = second_parent
    result = resolve_exact_request(request, current)
    assert result["resolved"] is False
    assert code(result) == FailureCode.TARGET_MULTI_MATCH.value


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("parent", FailureCode.TARGET_LINEAGE_MISMATCH.value),
        ("child", FailureCode.TARGET_CHILD_STRUCTURE_CHANGED.value),
        ("action", FailureCode.ACTION_SET_CHANGED.value),
        ("text", FailureCode.TARGET_IDENTITY_MISMATCH.value),
    ],
)
def test_semantic_lineage_child_and_action_changes_reject(mutation, expected):
    request = make_request()
    if mutation == "parent":
        current = current_hierarchy(target=node(), root_class="android.widget.LinearLayout")
    elif mutation == "child":
        current = current_hierarchy(target=node(children=[node(resource="com.example.smartthings:id/new_child")]))
    elif mutation == "action":
        current = current_hierarchy(target=node(actions=[{"id": 64, "name": "ACTION_ACCESSIBILITY_FOCUS", "label": None}]))
    else:
        current = current_hierarchy(target=node(text="Changed"))
    assert code(resolve_exact_request(request, current)) == expected


def test_zero_match_multi_match_and_wrong_package_window_fail_closed():
    request = make_request()
    assert code(resolve_exact_request(request, current_hierarchy(target=node(resource="other:id/no")))) == FailureCode.TARGET_NOT_FOUND.value
    duplicate = node()
    result = resolve_exact_request(request, current_hierarchy(target=node(), extra_nodes=[duplicate]))
    assert code(result) == FailureCode.TARGET_MULTI_MATCH.value
    wrong_package = current_hierarchy(target=node())
    wrong_package["packageName"] = "other.app"
    assert code(resolve_exact_request(request, wrong_package)) == FailureCode.PACKAGE_MISMATCH.value
    wrong_window = current_hierarchy(target=node())
    wrong_window["windows"][0]["id"] = 8
    assert code(resolve_exact_request(request, wrong_window)) == FailureCode.WINDOW_MISMATCH.value


def test_hard_stop_and_action_execution_requests_are_rejected():
    request = make_request()
    assert code(resolve_exact_request(request, current_hierarchy(target=node()), hard_stop_active=True)) == FailureCode.HARD_STOP_ACTIVE.value
    bad = deepcopy(request.data)
    bad["action_type"] = "ACTION_CLICK"
    from talkback_lib.exact_node_protocol import request_digest
    bad["request_digest"] = request_digest(bad)
    with pytest.raises(ProtocolValidationError) as raised:
        ExactNodeRequest.parse(bad)
    assert raised.value.code == FailureCode.ACTION_EXECUTION_DISABLED


def test_request_schema_rejects_unknown_duplicate_malformed_and_expired_fields():
    request = make_request()
    unknown = deepcopy(request.data)
    unknown["selector"] = "first match"
    with pytest.raises(ProtocolValidationError):
        ExactNodeRequest.parse(unknown)
    raw = json.dumps(request.data, separators=(",", ":"))
    dup_raw = raw[:-1] + ',"request_id":"shadow"}'
    with pytest.raises(ProtocolValidationError):
        ExactNodeRequest.parse(dup_raw)
    expired = deepcopy(request.data)
    expired["created_at"] = stamp(-10)
    expired["expires_at"] = stamp(-2)
    from talkback_lib.exact_node_protocol import request_digest
    expired["request_digest"] = request_digest(expired)
    with pytest.raises(ProtocolValidationError) as raised:
        ExactNodeRequest.parse(expired)
    assert raised.value.code == FailureCode.REQUEST_EXPIRED
    expired_permit = deepcopy(request.data)
    expired_permit["permit_created_at"] = stamp(-10)
    expired_permit["permit_expires_at"] = stamp(1)
    from talkback_lib.exact_node_protocol import request_digest
    expired_permit["request_digest"] = request_digest(expired_permit)
    with pytest.raises(ProtocolValidationError) as raised:
        ExactNodeRequest.parse(expired_permit, now=stamp(2))
    assert raised.value.code == FailureCode.PERMIT_EXPIRED


def test_one_shot_nonce_permit_transaction_and_stale_snapshot_gate():
    request = make_request()
    registry = OneShotRequestRegistry()
    args = dict(now=stamp(), expected_package=PACKAGE, expected_window=WINDOW,
                current_snapshot_id="B", hard_stop_active=False)
    registry.claim(request, **args)
    with pytest.raises(ProtocolValidationError) as raised:
        registry.claim(request, **args)
    assert raised.value.code == FailureCode.REQUEST_REPLAYED
    with pytest.raises(ProtocolValidationError) as raised:
        OneShotRequestRegistry().claim(request, **{**args, "current_snapshot_id": "A"})
    assert raised.value.code == FailureCode.SNAPSHOT_STALE
    with pytest.raises(ProtocolValidationError) as raised:
        OneShotRequestRegistry().claim(request, **{**args, "hard_stop_active": True})
    assert raised.value.code == FailureCode.HARD_STOP_ACTIVE


def test_ack_with_action_true_is_hard_failure_and_ack_correlation_is_exact():
    request = make_request()
    ack = resolve_exact_request(request, current_hierarchy(target=node()))
    unsafe = deepcopy(ack)
    unsafe["perform_action_called"] = True
    with pytest.raises(ProtocolValidationError) as raised:
        ExactNodeAck.parse(unsafe, request)
    assert raised.value.code == FailureCode.ACTION_EXECUTION_DISABLED
    mismatch = deepcopy(ack)
    mismatch["transaction_id"] = "tx:wrong"
    with pytest.raises(ProtocolValidationError):
        ExactNodeAck.parse(mismatch, request)


def test_ack_must_bind_helper_fresh_identity_structure_actions_and_snapshot():
    request = make_request()
    ack = resolve_exact_request(request, current_hierarchy(target=node()))
    tampered_target = deepcopy(ack)
    tampered_target["resolved_target_identity"]["resource_id"] = "other:id/control"
    tampered_target["resolved_resource_id"] = "other:id/control"
    with pytest.raises(ProtocolValidationError) as raised:
        ExactNodeAck.parse(tampered_target, request)
    assert raised.value.code == FailureCode.TARGET_IDENTITY_MISMATCH

    tampered_structure = deepcopy(ack)
    tampered_structure["resolved_lineage_summary"] = []
    with pytest.raises(ProtocolValidationError) as raised:
        ExactNodeAck.parse(tampered_structure, request)
    assert raised.value.code == FailureCode.REQUEST_INVALID

    stale_snapshot = deepcopy(ack)
    stale_snapshot["resolved_target_identity"]["snapshot_id"] = request.data["reacquire_snapshot_id"]
    with pytest.raises(ProtocolValidationError) as raised:
        ExactNodeAck.parse(stale_snapshot, request)
    assert raised.value.code == FailureCode.SNAPSHOT_STALE


def test_audit_is_append_only_correlated_and_never_visit_authority():
    request = make_request()
    audit = AppendOnlyProtocolAudit()
    source = audit.append(event_type="PYTHON_REACQUIRE", request=request, parent_event_id=None,
                          evidence={"snapshot": "B", "candidate_count": 1})
    child = audit.append(event_type="HELPER_RESOLUTION", request=request, parent_event_id=source.event_id,
                         evidence={"snapshot": "C", "perform_action_called": False})
    snapshot = audit.records
    child_evidence = child.evidence
    child_evidence["perform_action_called"] = True
    assert len(snapshot) == 2
    assert snapshot[1].evidence["perform_action_called"] is False
    assert all(record.visit_authority is False for record in snapshot)
    assert child.to_dict()["parent_event_id"] == source.event_id


def test_helper_build_identity_match_mismatch_unknown_and_legacy_compatibility():
    identity = {
        "helper_protocol_version": PROTOCOL_VERSION,
        "versionName": "1.0",
        "versionCode": 1,
        "build_id": "a" * 64,
        "git_commit": "b" * 40,
        "helper_input_digest": "c" * 64,
        "source_state": "CLEAN",
        "build_variant": "debug",
        "metadata_provenance": "GENERATED_AT_BUILD",
    }
    ping = {"reqId": "ping:1", "success": True, "status": "READY", "helper_build_identity": identity}
    match = precheck_helper_build_identity("b" * 40, ping, expected_build_id="a" * 64,
                                           expected_input_digest="c" * 64)
    assert match.status == HelperIdentityStatus.MATCH
    mismatch = precheck_helper_build_identity("d" * 40, ping, expected_build_id="a" * 64,
                                               expected_input_digest="c" * 64)
    assert mismatch.status == HelperIdentityStatus.MISMATCH
    unknown = precheck_helper_build_identity("b" * 40, ping)
    assert unknown.status == HelperIdentityStatus.UNKNOWN
    old = precheck_helper_build_identity("b" * 40, {"reqId": "old", "success": True, "status": "READY"})
    assert old.status == HelperIdentityStatus.UNKNOWN
    assert old.reason == "HELPER_BUILD_IDENTITY_UNAVAILABLE"


def test_new_helper_path_has_no_action_dispatch_dependency():
    root = Path(__file__).resolve().parents[1]
    resolver = (root / "app/src/main/java/com/iotpart/sqe/talkbackhelper/ExactNodeResolver.kt").read_text(encoding="utf-8")
    receiver = (root / "app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yCommandReceiver.kt").read_text(encoding="utf-8")
    assert ".performAction(" not in resolver
    assert "A11yTargetFinder" not in resolver
    start = receiver.index("private fun handleResolveExactNode")
    end = receiver.find("\n    private fun ", start + 10)
    handler = receiver[start:end if end >= 0 else len(receiver)]
    assert ".performAction(" not in handler
    assert "A11yTargetFinder" not in handler


def test_helper_bridge_sends_one_read_only_request_after_identity_precheck():
    request = make_request()

    class FakeClient:
        def __init__(self):
            self.broadcasts = []

        def clear_logcat(self, dev=None):
            return None

        def _broadcast(self, dev, action, extras):
            self.broadcasts.append((action, extras))
            return "broadcast-delivered"

        def _read_log_result(self, dev, prefix, req_id, wait_seconds):
            ack = resolve_exact_request(request, current_hierarchy(target=node()))
            return {"reqId": req_id, "success": True, "status": "ACK", "ack": ack}

    client = FakeClient()
    bridge = HelperBridge(client)
    bridge.precheck_helper_build_identity = lambda **_: {
        "status": "MATCH", "helper_service_instance_id": request.data["helper_service_instance_id"]
    }
    result = bridge.resolve_exact_node_read_only("synthetic-device", request)
    assert result["success"] is True
    assert result["ack"]["perform_action_called"] is False
    assert len(client.broadcasts) == 1
    from talkback_lib.constants import ACTION_RESOLVE_EXACT_NODE
    action, extras = client.broadcasts[0]
    assert action == ACTION_RESOLVE_EXACT_NODE
    assert "exactNodeRequest" in extras
    replay = bridge.resolve_exact_node_read_only("synthetic-device", request)
    assert replay["failure_code"] == FailureCode.REQUEST_REPLAYED.value
    assert len(client.broadcasts) == 1
