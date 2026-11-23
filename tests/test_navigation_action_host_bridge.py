import json
import shlex
import hashlib
import time

import pytest

from talkback_lib.helper_bridge import (
    NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK,
    HelperBridge,
    NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
)
from talkback_lib.constants import ACTION_NAVIGATION_ACTION
from talkback_lib import A11yAdbClient
from talkback_lib.adb_device import AdbCommandFailure
from talkback_lib.exact_node_protocol import canonical_json
from tb_runner import collection_flow


def _lease():
    armed = {
        "runId": "run-1", "invocationId": "inv-1", "captureId": "capture-1",
        "invocationUriBound": True,
        "scenarioId": "scenario-1",
        "connectionId": "service-1", "ownerLeaseId": "owner-lease-1", "ownerWindowId": 44,
        "ownerPackageName": "com.example.app", "ownerPath": [0, 3],
        "ownerDescriptorDigest": "d" * 64, "sourceSnapshotId": "source-1",
        "helperSnapshotId": "helper-1", "baselineHierarchyDigest": "b" * 64,
        "sourceCaptureRequestId": "source-request-1", "sourceProcessEpoch": "process-1",
        "sourceGeneration": 8, "sourceServiceInstanceId": "service-1", "sourceCaptureSequence": 11,
        "sourceRootDigest": "a" * 64, "sourceCandidateDigest": "c" * 64,
        "sourceCaptureKey": "source-1", "sourceConnectionEpoch": "connection-epoch-1",
        "sourceBootEpoch": "boot:33", "ownerSourceNodeId": "owner-node-1",
        "ownerSourceNodeIdStatus": "FIELD_PRESENT",
    }
    current = dict(armed, transactionId="tx-1", ok=True, reason="TARGET_CURRENT")
    return ({"req_id": "capture-req-1", "armed": armed},
            {"ok": True, "reason": "TARGET_CURRENT", "result": current})


class _Client:
    package_name = "com.iotpart.sqe.talkbackhelper"

    def __init__(self, receipt, response_extra=None):
        self.receipt = receipt
        self.response_extra = response_extra if callable(response_extra) else dict(response_extra or {})
        self.calls = []
        self.req_id = None
        self.broadcast_stdout = ""

    def clear_logcat(self, dev=None):
        self.calls.append(("clear", dev))

    def _broadcast(self, dev, action, extras):
        self.calls.append(("broadcast", dev, action, list(extras)))
        self.req_id = extras[extras.index("reqId") + 1]
        return self.broadcast_stdout

    @staticmethod
    def _escape_adb_string(value):
        return "'" + str(value).replace("'", "'\\''") + "'"

    def _read_log_result(self, dev, prefix, req_id, **_kwargs):
        extra = self.response_extra(req_id) if callable(self.response_extra) else self.response_extra
        return {"reqId": req_id, "receipt": self.receipt(req_id), **extra}


def _readiness():
    return {
        "eligible": True,
        "scenario_id": "scenario-1",
        "contract_id": "reviewed-nav-1",
        "contract_digest": "a" * 64,
        "identity_check": {"helper_service_instance_id": "service-1",
                           "helper_connection_epoch": "connection-epoch-1", "boot_epoch": "boot:33"},
    }


def _receipt(req_id, owner_source_node_id="owner-node-1", owner_source_node_id_status="FIELD_PRESENT"):
    return {
        "status": "VERIFIED_NAVIGATION", "verified_navigation": True, "action_call_count": 1,
        "action": "ACTION_CLICK",
        "visit_authority": False, "c5_credit": False,
        "request_id": req_id, "transaction_id": "tx-1", "scenario_id": "scenario-1",
        "owner_capture_request_id": "capture-req-1", "owner_lease_id": "owner-lease-1",
        "run_id": "run-1", "invocation_id": "inv-1", "service_instance_id": "service-1",
        "connection_id": "service-1", "window_id": 44, "source_capture_id": "capture-1",
        "helper_snapshot_id": "helper-1", "effect_contract_id": "reviewed-nav-1",
        "effect_contract_digest": "a" * 64,
        "source_identity": {
            "request_id": "source-request-1", "process_epoch": "process-1", "generation": 8,
            "service_instance_id": "service-1", "capture_sequence": 11, "root_digest": "a" * 64,
            "candidate_digest": "c" * 64, "capture_key": "source-1",
            "connection_epoch": "connection-epoch-1", "boot_epoch": "boot:33",
            "owner_source_node_id": owner_source_node_id,
            "owner_source_node_id_status": owner_source_node_id_status,
        },
    }


def test_scenario_contract_selection_requires_validated_ready_default_off_capability(monkeypatch):
    import talkback_lib.helper_bridge as module

    monkeypatch.setattr(module, "helper_compatibility_allows_execution", lambda _check: True)
    client = _Client(lambda req: {})
    bridge = HelperBridge(client)
    check = {
        "helper_service_instance_id": "service-1",
        "helper_capabilities": ["navigation_action"],
        "navigation_action_state": {
            "supported": True, "enabled": True, "ready": True, "default_enabled": False,
            "visit_credit": False, "c5_credit": False, "exact_action_gate_independent": True,
            "service_instance_id": "service-1",
            "contracts": [{"contract_id": "reviewed-nav-1", "contract_digest": "a" * 64,
                           "scenario_ids": ["scenario-1"]}],
        },
    }
    bridge.precheck_helper_build_identity = lambda **_kwargs: check
    ready = bridge.navigation_action_contract_for_scenario("SERIAL", "scenario-1")
    assert ready["eligible"] is True
    assert ready["contract_digest"] == "a" * 64

    check["navigation_action_state"]["contracts"].append({
        "contract_id": "reviewed-nav-2", "contract_digest": "c" * 64,
        "scenario_ids": ["scenario-1"],
    })
    selected = bridge.navigation_action_contract_for_scenario(
        "SERIAL", "scenario-1", contract_id="reviewed-nav-2")
    assert selected["eligible"] is True
    assert selected["contract_id"] == "reviewed-nav-2"
    ambiguous = bridge.navigation_action_contract_for_scenario("SERIAL", "scenario-1")
    assert ambiguous["eligible"] is False
    assert ambiguous["reason"] == "NAVIGATION_CONTRACT_AMBIGUOUS"


def test_dispatch_binds_exact_owner_lease_and_sends_contract_reference_only():
    client = _Client(_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is True
    sent = result["request"]
    assert sent["owner_capture_request_id"] == "capture-req-1"
    assert sent["action"] == "ACTION_CLICK"
    assert "activation_mode" not in sent
    assert sent["owner_lease_id"] == "owner-lease-1"
    assert sent["node_path"] == [0, 3]
    assert sent["window_id"] == 44
    assert sent["effect_contract_id"] == "reviewed-nav-1"
    assert sent["effect_contract_digest"] == "a" * 64
    assert sent["source_identity"]["request_id"] == "source-request-1"
    assert sent["source_identity"]["connection_epoch"] == "connection-epoch-1"
    assert sent["source_identity"]["boot_epoch"] == "boot:33"
    assert sent["source_identity"]["owner_source_node_id"] == "owner-node-1"
    assert sent["source_identity"]["owner_source_node_id_status"] == "FIELD_PRESENT"
    assert not {"effect", "destination", "required_anchor", "target_class_pattern"}.intersection(sent)
    broadcast = next(call for call in client.calls if call[0] == "broadcast")
    assert broadcast[2] == "com.iotpart.sqe.talkbackhelper.NAVIGATION_ACTION"
    extras = broadcast[3]
    assert extras == [
        "--es", "reqId", result["reqId"],
        "--es", "navigationActionRequest", _Client._escape_adb_string(canonical_json(sent)),
    ]
    assert "-d" not in extras
    assert json.loads(shlex.split(extras[5])[0]) == sent


def test_focus_then_click_mode_is_explicit_and_receipt_correlated_to_exact_owner():
    def receipt(req_id):
        value = _receipt(req_id)
        value["activation_mode"] = NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
        return value

    client = _Client(receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness(),
        activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK)

    assert result["success"] is True
    assert result["request"]["activation_mode"] == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
    assert result["request"]["action"] == "ACTION_CLICK"
    assert result["receipt"]["activation_mode"] == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
    sent = result["request"]
    broadcast = next(call for call in client.calls if call[0] == "broadcast")
    extras = broadcast[3]
    assert json.loads(shlex.split(extras[5])[0]) == sent


def test_aircare_frame_layout_child_mode_is_explicit_diagnostic_and_never_navigation_credit():
    def diagnostic_receipt(req_id):
        value = _receipt(req_id)
        value.update(
            scenario_id="life_air_care_plugin",
            effect_contract_id="life_service_card_read_only_navigation",
            status="DIAGNOSTIC_ONLY",
            verified_navigation=False,
            visit_authority=False,
            c5_credit=False,
            traversal_credit=False,
            action_call_count=1,
            diagnostic_only=True,
            diagnostic_action_dispatched=True,
            activation_mode=NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK,
            diagnostic_target={
                "path": [0, 3, 0], "class_name": "android.widget.FrameLayout",
                "resource_id": "com.samsung.android.oneconnect:id/frameLayout", "window_id": 44,
                "source_snapshot_id": "source-1", "helper_snapshot_id": "helper-1",
                "baseline_hierarchy_digest": "b" * 64, "parent_path": [0, 3],
            },
            diagnostic_click_event={
                "exact_target_match": True, "event_type": 1, "request_id": req_id,
                "transaction_id": "tx-1", "service_instance_id": "service-1",
                "connection_id": "service-1", "window_id": 44,
            },
        )
        return value

    capture, current = _lease()
    capture["armed"].update(scenarioId="life_air_care_plugin",
                             ownerPackageName="com.samsung.android.oneconnect")
    current["result"].update(scenarioId="life_air_care_plugin",
                              ownerPackageName="com.samsung.android.oneconnect")
    readiness = _readiness()
    readiness.update(scenario_id="life_air_care_plugin",
                     contract_id="life_service_card_read_only_navigation")
    bridge = HelperBridge(_Client(diagnostic_receipt))
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="life_air_care_plugin", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=readiness,
        activation_mode=NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK)

    assert result["success"] is False
    assert result["status"] == "diagnostic_only"
    assert result["action_dispatched"] is True
    assert result["receipt"]["verified_navigation"] is False
    assert result["receipt"]["visit_authority"] is False
    assert result["receipt"]["c5_credit"] is False
    assert result["receipt"]["traversal_credit"] is False
    assert result["request"]["node_path"] == [0, 3]
    assert result["request"]["activation_mode"] == NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK


def test_aircare_frame_layout_diagnostic_rejects_wrong_child_projection():
    def wrong_child_receipt(req_id):
        value = _receipt(req_id)
        value.update(
            scenario_id="life_air_care_plugin",
            effect_contract_id="life_service_card_read_only_navigation",
            status="DIAGNOSTIC_ONLY", verified_navigation=False, visit_authority=False,
            c5_credit=False, traversal_credit=False, action_call_count=1, diagnostic_only=True,
            diagnostic_action_dispatched=True,
            activation_mode=NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK,
            diagnostic_target={
                "path": [0, 3, 1], "class_name": "android.widget.FrameLayout",
                "resource_id": "com.samsung.android.oneconnect:id/include", "window_id": 44,
                "source_snapshot_id": "source-1", "helper_snapshot_id": "helper-1",
                "baseline_hierarchy_digest": "b" * 64, "parent_path": [0, 3],
            },
            diagnostic_click_event={
                "exact_target_match": True, "event_type": 1, "request_id": req_id,
                "transaction_id": "tx-1", "service_instance_id": "service-1",
                "connection_id": "service-1", "window_id": 44,
            },
        )
        return value

    capture, current = _lease()
    capture["armed"].update(scenarioId="life_air_care_plugin",
                             ownerPackageName="com.samsung.android.oneconnect")
    current["result"].update(scenarioId="life_air_care_plugin",
                              ownerPackageName="com.samsung.android.oneconnect")
    readiness = _readiness()
    readiness.update(scenario_id="life_air_care_plugin",
                     contract_id="life_service_card_read_only_navigation")
    result = HelperBridge(_Client(wrong_child_receipt)).dispatch_navigation_action(
        "SERIAL", scenario_id="life_air_care_plugin", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=readiness,
        activation_mode=NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK)

    assert result["success"] is False
    assert result["status"] == "protocol_error"
    assert "diagnostic_target.path" in result["receipt_mismatch_fields"]
    assert "diagnostic_target.resource_id" in result["receipt_mismatch_fields"]


def test_aircare_frame_layout_diagnostic_mode_is_rejected_outside_exact_contract_scope():
    client = _Client(_receipt)
    capture, current = _lease()
    result = HelperBridge(client).dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness(),
        activation_mode=NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK)

    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_DIAGNOSTIC_MODE_SCOPE_MISMATCH"
    assert client.calls == []


def test_rejected_focus_revalidation_leaf_diagnostics_pass_through_unchanged():
    leaf_diagnostics = {
        "prepared_deadline_valid": True,
        "service_identity_matches": True,
        "connection_identity_matches": True,
        "window_identity_matches": True,
        "focus_event_owner_matches": True,
        "target_currentness": {
            "diagnostics_available": True,
            "capture_lease_fresh": True,
            "connection_identity_matches": True,
            "retained_node_refresh_succeeded": True,
            "window_identity_matches": True,
            "retained_node_accessibility_focused": True,
            "unique_active_window": True,
            "root_available": True,
            "node_at_path_resolved": True,
            "retained_node_identity_matches": True,
            "focus_neutral_descriptor_matches": True,
            "focus_neutral_hierarchy_digest_matches": False,
            "capture_complete": True,
            "first_failed_check": "focus_neutral_hierarchy_digest_matches",
            "aggregate_accepted": False,
        },
        "aggregate_accepted": False,
    }

    def rejected_receipt(req_id):
        receipt = _receipt(req_id)
        receipt.update(
            status="REJECTED",
            verified_navigation=False,
            action_call_count=0,
            failure_code="NAVIGATION_FOCUSED_TARGET_STALE",
            activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
            activation_diagnostics={"focus_revalidation": leaf_diagnostics},
        )
        return receipt

    result = HelperBridge(_Client(rejected_receipt)).dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=_lease()[0],
        current_lease=_lease()[1], readiness=_readiness(),
        activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK)

    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_ACTION_RECEIPT_UNVERIFIED"
    assert result["receipt"]["activation_diagnostics"]["focus_revalidation"] == leaf_diagnostics


def test_unknown_navigation_activation_mode_is_rejected_before_transport():
    client = _Client(_receipt)
    result = HelperBridge(client).dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=_lease()[0],
        current_lease=_lease()[1], readiness=_readiness(), activation_mode="COORDINATE_DOUBLE_TAP")

    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_ACTIVATION_MODE_NOT_ALLOWLISTED"
    assert client.calls == []


def test_focus_then_click_mode_is_not_sent_for_mismatched_exact_owner_lease():
    client = _Client(_receipt)
    capture, current = _lease()
    current["result"]["ownerDescriptorDigest"] = "f" * 64
    result = HelperBridge(client).dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness(),
        activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK)

    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_OWNER_LEASE_MISMATCH"
    assert client.calls == []


def test_dispatch_preserves_secondary_window_events_without_changing_strict_receipt():
    def diagnostics_for(req_id):
        return {"secondary_window_event_diagnostics": {
            "evidence_role": "SECONDARY_ONLY", "status": "RECORDED", "request_id": req_id,
            "transaction_id": "tx-1", "service_instance_id": "service-1", "connection_id": "service-1",
            "owner_window_id": 44, "action_dispatch_elapsed_realtime_ms": 1000,
            "dispatch_deadline_elapsed_realtime_ms": 6000, "event_count": 1,
            "events": [{"request_id": req_id, "transaction_id": "tx-1", "service_instance_id": "service-1",
                        "connection_id": "service-1", "owner_window_id": 44, "event_type": 32,
                        "event_package": "com.example.app", "event_window_id": 44,
                        "event_elapsed_realtime_ms": 1001}],
        }}
    for accepted in (True, False):
        def receipt(req_id):
            value = _receipt(req_id)
            if not accepted:
                value.update(status="REJECTED", verified_navigation=False, failure_code="POST_STATE_UNVERIFIED")
            return value

        client = _Client(receipt, diagnostics_for)
        bridge = HelperBridge(client)
        capture, current = _lease()
        result = bridge.dispatch_navigation_action(
            "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
            current_lease=current, readiness=_readiness())

        assert result["success"] is accepted
        diagnostics = result["secondary_window_event_diagnostics"]
        assert diagnostics["evidence_role"] == "SECONDARY_ONLY"
        assert diagnostics["request_id"] == result["reqId"]
        assert diagnostics["events"][0]["transaction_id"] == "tx-1"
        assert result["receipt"]["status"] == ("VERIFIED_NAVIGATION" if accepted else "REJECTED")
        assert result["receipt"]["visit_authority"] is False
        assert result["receipt"]["c5_credit"] is False


def test_dispatch_drops_mismatched_secondary_window_diagnostics_only():
    client = _Client(_receipt, {"secondary_window_event_diagnostics": {
        "evidence_role": "SECONDARY_ONLY", "request_id": "other-request", "transaction_id": "tx-1",
        "service_instance_id": "service-1", "connection_id": "service-1", "owner_window_id": 44,
        "action_dispatch_elapsed_realtime_ms": 1000, "dispatch_deadline_elapsed_realtime_ms": 6000,
        "event_count": 1, "events": [],
    }})
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())

    assert result["success"] is True
    assert result["receipt"]["status"] == "VERIFIED_NAVIGATION"
    assert "secondary_window_event_diagnostics" not in result


@pytest.mark.parametrize("field,value", [
    ("transaction_id", "tx-stale"), ("service_instance_id", "other-service"),
    ("connection_id", "other-connection"), ("owner_window_id", 45),
    ("event_window_id", 45), ("event_package", "com.other.app"),
    ("event_elapsed_realtime_ms", 6001), ("event_type", 16),
])
def test_dispatch_drops_unrelated_secondary_window_event_rows(field, value):
    def extra(req_id):
        event = {"request_id": req_id, "transaction_id": "tx-1", "service_instance_id": "service-1",
                 "connection_id": "service-1", "owner_window_id": 44, "event_type": 32,
                 "event_package": "com.example.app", "event_window_id": 44,
                 "event_elapsed_realtime_ms": 1001}
        event[field] = value
        return {"secondary_window_event_diagnostics": {
            "evidence_role": "SECONDARY_ONLY", "status": "RECORDED", "request_id": req_id,
            "transaction_id": "tx-1", "service_instance_id": "service-1", "connection_id": "service-1",
            "owner_window_id": 44, "action_dispatch_elapsed_realtime_ms": 1000,
            "dispatch_deadline_elapsed_realtime_ms": 6000, "event_count": 1, "events": [event],
        }}

    client = _Client(_receipt, extra)
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())

    assert result["success"] is True
    assert result["receipt"]["status"] == "VERIFIED_NAVIGATION"
    assert "secondary_window_event_diagnostics" not in result


def test_dispatch_allows_explicit_absent_source_id_with_exact_descriptor_lease():
    def absent_id_receipt(req_id):
        return _receipt(req_id, "", "FIELD_ABSENT")
    client = _Client(absent_id_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    for evidence in (capture["armed"], current["result"]):
        evidence["ownerSourceNodeId"] = ""
        evidence["ownerSourceNodeIdStatus"] = "FIELD_ABSENT"
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is True
    assert result["request"]["source_identity"]["owner_source_node_id"] == ""
    assert result["request"]["source_identity"]["owner_source_node_id_status"] == "FIELD_ABSENT"


def test_dispatch_rejects_absent_source_id_without_explicit_absence_marker():
    client = _Client(_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    for evidence in (capture["armed"], current["result"]):
        evidence["ownerSourceNodeId"] = ""
        evidence.pop("ownerSourceNodeIdStatus")
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_OWNER_SOURCE_IDENTITY_INVALID"
    assert not any(call[0] == "broadcast" for call in client.calls)


def test_dispatch_rejects_unbound_invocation_before_broadcast():
    for missing_from in ("armed", "current"):
        client = _Client(_receipt)
        bridge = HelperBridge(client)
        capture, current = _lease()
        if missing_from == "armed":
            capture["armed"].pop("invocationUriBound")
        else:
            current["result"]["invocationUriBound"] = False
        result = bridge.dispatch_navigation_action(
            "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
            current_lease=current, readiness=_readiness())
        assert result["success"] is False
        assert result["reason"] == "NAVIGATION_INVOCATION_NOT_BOUND"
        assert not any(call[0] == "broadcast" for call in client.calls)


def test_dispatch_rejects_stale_owner_lease_without_broadcast():
    client = _Client(_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    current["result"]["ownerLeaseId"] = "different-owner"
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_OWNER_LEASE_MISMATCH"
    assert not any(call[0] == "broadcast" for call in client.calls)


@pytest.mark.parametrize("field,value", [
    ("sourceConnectionEpoch", "old-connection"),
    ("sourceBootEpoch", "boot:stale"),
    ("ownerSourceNodeId", "other-node"),
])
def test_dispatch_rejects_stale_capture_identity_before_broadcast(field, value):
    client = _Client(_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    current["result"][field] = value
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_OWNER_LEASE_MISMATCH"
    assert not any(call[0] == "broadcast" for call in client.calls)


@pytest.mark.parametrize("field,value", [
    ("helper_connection_epoch", "new-connection"),
    ("boot_epoch", "boot:34"),
])
def test_dispatch_requires_source_lifecycle_identity_to_match_current_readiness(field, value):
    client = _Client(_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    readiness = _readiness()
    readiness["identity_check"][field] = value
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=readiness)
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_SOURCE_LIFECYCLE_IDENTITY_MISMATCH"
    assert not any(call[0] == "broadcast" for call in client.calls)


def test_dispatch_rejects_mismatched_helper_receipt_without_authority():
    def bad_receipt(req_id):
        receipt = _receipt(req_id)
        receipt["owner_lease_id"] = "wrong-lease"
        return receipt

    client = _Client(bad_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_ACTION_RECEIPT_UNVERIFIED"


def test_dispatch_surfaces_redacted_post_state_rejection_fields_without_authority():
    sample_payload = {
        "schema": "strict-post-capture-redacted-v1",
        "request_id": "nav-request-1",
        "transaction_id": "tx-1",
        "service_instance_id": "service-1",
        "connection_id": "service-1",
        "window_id": 44,
        "capture_id": "post-capture-1",
        "hierarchy_digest": "b" * 64,
        "captured_at_elapsed_realtime_ms": 1002,
        "node_count": 2, "persisted_node_count": 2, "completeness": "COMPLETE",
        "omitted_fields": ["text", "contentDescription", "action_labels", "sourceNodeId"],
        "diagnostic_only": True, "effect_contract_id": "life-plugin-back",
        "required_anchor_structural_match_count": 1,
        "nodes": [
            {"id": 0, "parent_id": None, "child_index": None, "path": [],
             "class_name": "android.widget.HorizontalScrollView", "package_name": "com.samsung.android.oneconnect",
             "resource_id": "com.samsung.android.oneconnect:id/bottom_navigation", "window_id": 44,
             "bounds": [0, 0, 100, 20], "text_present": False, "content_description_present": False,
             "resource_id_present": True, "clickable": False, "enabled": True, "focusable": False,
             "focused": False, "accessibility_focused": False, "selected": False, "scrollable": True,
             "visible_to_user": True, "action_ids": [], "action_count": 0, "action_ids_complete": True,
             "destination_label_match": False, "required_anchor_match_count": 0},
            {"id": 1, "parent_id": 0, "child_index": 0, "path": [0],
             "class_name": "android.widget.LinearLayout", "package_name": "com.samsung.android.oneconnect",
             "resource_id": "", "window_id": 44, "bounds": [0, 0, 20, 20], "text_present": True,
             "content_description_present": False, "resource_id_present": False, "clickable": True,
             "enabled": True, "focusable": True, "focused": False, "accessibility_focused": False,
             "selected": False, "scrollable": False, "visible_to_user": True, "action_ids": [16, 64],
             "action_count": 2, "action_ids_complete": True, "destination_label_match": True,
             "required_anchor_match_count": 1,
             "diagnostic_policy_match_ids": ["required_anchor_label", "required_anchor_structural_match"]},
        ],
    }
    sample_serialized = canonical_json(sample_payload).encode("utf-8")
    sample_artifact = {
        "result_channel": "NAVIGATION_ACTION_RESULT",
        "request_id": "nav-request-1",
        "receipt_field": "receipt.post_state_diagnostics.post_capture_sample_artifact.payload",
        "artifact_sha256": hashlib.sha256(sample_serialized).hexdigest(),
        "artifact_bytes": len(sample_serialized),
        "completeness": "COMPLETE",
        "node_count": 2,
        "persisted_node_count": 2,
        "payload": sample_payload,
    }
    diagnostics = {
        "event_source_status": "EXACT_RETAINED_NODE_MATCH",
        "event_source_connection_match": True,
        "post_capture_id": "post-capture-1",
        "focus_window_id": None,
        "focus_window_id_status": "FIELD_ABSENT",
        "accessibility_focused": False,
        "diagnostic_schema": "strict-post-action-v1",
        "request_id": "nav-request-1",
        "transaction_id": "tx-1",
        "dispatch_elapsed_realtime_ms": 1000,
        "capture_call_start_elapsed_realtime_ms": 1400,
        "capture_call_completion_elapsed_realtime_ms": 1800,
        "receipt_decision_elapsed_realtime_ms": 1800,
        "action_service_instance_id": "service-1",
        "action_connection_id": "service-1",
        "action_window_id": 44,
        "post_window_id": 44,
        "required_anchor_outcome": "NOT_EVALUATED",
        "post_capture_sample_persistence_status": "EMBEDDED_COMPLETE",
        "post_capture_sample_artifact": sample_artifact,
        "receipt_decision": "REJECTED",
        "receipt_failure_code": "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
        "failure_stages": ["accessibility_focus_missing", "focus_not_in_current_hierarchy"],
    }

    def stale_post_state_receipt(req_id):
        receipt = _receipt(req_id)
        receipt.update(status="REJECTED", verified_navigation=False, failure_code="NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
                       post_state_mismatch_fields=["accessibility_focus_missing", "focus_not_in_current_hierarchy"],
                       post_state_diagnostics=diagnostics)
        return receipt

    client = _Client(stale_post_state_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_ACTION_RECEIPT_UNVERIFIED"
    assert result["receipt_failure_code"] == "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE"
    assert result["post_state_mismatch_fields"] == [
        "accessibility_focus_missing", "focus_not_in_current_hierarchy"]
    assert result["post_state_diagnostics"] == diagnostics
    assert result["post_state_diagnostics"]["post_capture_sample_artifact"] == sample_artifact
    assert result["receipt"]["post_state_diagnostics"]["post_capture_sample_artifact"] == sample_artifact
    embedded = result["receipt"]["post_state_diagnostics"]["post_capture_sample_artifact"]
    serialized_payload = canonical_json(embedded["payload"]).encode("utf-8")
    assert hashlib.sha256(serialized_payload).hexdigest() == embedded["artifact_sha256"]
    assert len(serialized_payload) == embedded["artifact_bytes"]
    projected = collection_flow._navigation_action_evidence_projection(result)
    projected_post = projected["post_state_diagnostics"]
    projected_artifact = projected_post["post_capture_sample_artifact"]
    assert projected_post["post_capture_sample_projection_status"] == "RETAINED"
    assert projected_artifact == sample_artifact
    assert projected_artifact["payload"]["required_anchor_structural_match_count"] == 1
    assert projected_artifact["payload"]["nodes"][1]["diagnostic_policy_match_ids"] == [
        "required_anchor_label", "required_anchor_structural_match",
    ]
    assert projected["receipt_failure_code"] == "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE"
    assert "receipt" not in projected
    assert "visit_authority" not in projected
    assert "navigation_credit" not in projected
    assert result["receipt"]["visit_authority"] is False
    assert result["receipt"]["c5_credit"] is False


def test_delayed_exact_navigation_receipt_is_accepted_within_existing_bounded_wait():
    class DelayedClient(_Client):
        def _read_log_result(self, dev, prefix, req_id, **kwargs):
            self.wait_seconds = kwargs.get("wait_seconds")
            time.sleep(0.02)
            return {"reqId": req_id, "receipt": self.receipt(req_id)}

    client = DelayedClient(_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert client.wait_seconds == 8.0
    assert result["success"] is True
    assert result["receipt"]["status"] == "VERIFIED_NAVIGATION"


def test_missing_navigation_receipt_remains_rejected_after_bounded_wait():
    class MissingReceiptClient(_Client):
        def _read_log_result(self, dev, prefix, req_id, **kwargs):
            self.wait_seconds = kwargs.get("wait_seconds")
            return None

    client = MissingReceiptClient(_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert client.wait_seconds == 8.0
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_ACTION_RESULT_MISSING"


def test_navigation_result_reader_timeout_is_not_misclassified_as_helper_receipt():
    class TimeoutClient(_Client):
        def _read_log_result(self, dev, prefix, req_id, **_kwargs):
            return {"success": False, "reason": "NAVIGATION_ACTION_RESULT log not found", "reqId": req_id}

    client = TimeoutClient(_receipt)
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_ACTION_RESULT_MISSING"
    assert result["read_result_reason"] == "NAVIGATION_ACTION_RESULT log not found"
    assert result.get("receipt_present") is not True


def test_correlated_navigation_rejection_preserves_bounded_transport_diagnostics():
    class RejectedClient(_Client):
        def __init__(self):
            super().__init__(_receipt)
            self.broadcast_stdout = "Broadcast completed: result=0\n"

        def _read_log_result(self, dev, prefix, req_id, **_kwargs):
            return {"reqId": req_id, "status": "REJECTED", "failure_code": "HELPER_REACQUIRE_FAILED"}

    client = RejectedClient()
    bridge = HelperBridge(client)
    capture, current = _lease()
    result = bridge.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is False
    assert result["reason"] == "NAVIGATION_ACTION_RECEIPT_INVALID"
    assert result["response_req_id"] == result["reqId"]
    assert result["response_status"] == "REJECTED"
    assert result["response_failure_code"] == "HELPER_REACQUIRE_FAILED"
    assert result["response_keys"] == ["failure_code", "reqId", "status"]
    assert result["receipt_present"] is False
    assert result["broadcast_stdout"] == "Broadcast completed: result=0"


def test_navigation_broadcast_argv_keeps_request_and_correlation_fields_as_extras(monkeypatch):
    from types import SimpleNamespace

    import talkback_lib.adb_device as adb_device_module

    captured = []

    def capture_subprocess(command, **kwargs):
        captured.append((list(command), kwargs))
        return SimpleNamespace(returncode=0, stdout="Broadcast completed", stderr="")

    monkeypatch.setattr(adb_device_module.subprocess, "run", capture_subprocess)
    client = A11yAdbClient(adb_path="not-invoked-adb", start_monitor=False)
    client.clear_logcat = lambda dev=None: None
    client._evidence_correlation_extras = lambda: [
        "--es", "evidenceRunId", "run-1",
        "--es", "evidenceTransactionId", "tx-1",
    ]
    client._read_log_result = lambda dev, prefix, req_id, **_kwargs: {
        "reqId": req_id, "receipt": _receipt(req_id),
    }
    capture, current = _lease()
    result = HelperBridge(client).dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1", capture_session=capture,
        current_lease=current, readiness=_readiness())
    assert result["success"] is True
    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[:10] == [
        "not-invoked-adb", "-s", "SERIAL", "shell", "am", "broadcast", "-a",
        ACTION_NAVIGATION_ACTION, "-p", client.package_name,
    ]
    assert "-d" not in args
    extras = args[10:]
    assert len(extras) % 3 == 0
    assert all(extras[index] == "--es" for index in range(0, len(extras), 3))
    actual = {extras[index + 1]: extras[index + 2] for index in range(0, len(extras), 3)}
    assert actual == {
        "reqId": result["reqId"],
        "navigationActionRequest": client._escape_adb_string(canonical_json(result["request"])),
        "evidenceRunId": "run-1",
        "evidenceTransactionId": "tx-1",
    }
    decoded_request = shlex.split(actual["navigationActionRequest"])
    assert len(decoded_request) == 1
    sent_request = json.loads(decoded_request[0])
    assert sent_request == result["request"]
    assert sent_request["baseline_hierarchy_digest"] == "b" * 64
    assert kwargs.get("shell", False) is False


def test_navigation_broadcast_delivery_failure_is_not_swallowed():
    client = A11yAdbClient(adb_path="not-invoked-adb", start_monitor=False)
    client._evidence_correlation_extras = lambda: []
    failure = AdbCommandFailure("adb_command_failed", ["adb", "shell", "am"], 2.0, stderr="delivery failed")

    def fail_command(*_args, **kwargs):
        assert kwargs.get("raise_on_failure") is True
        raise failure

    client._adb_device._run_adb_command = fail_command
    with pytest.raises(AdbCommandFailure) as raised:
        client._broadcast("SERIAL", ACTION_NAVIGATION_ACTION, ["--es", "reqId", "request-1"])
    assert raised.value is failure


def test_kotlin_shaped_production_receipt_passes_host_validator_projection_and_ledger(tmp_path):
    from tb_runner import collection_flow
    from tb_runner.evidence import EvidenceRuntime

    authority_template = {
        "schema": "navigation-post-window-authority-v1",
        "transaction_id": "tx-1", "service_instance_id": "service-1", "connection_id": "service-1",
        "action_window_id": 44, "click_window_id": 44, "click_event_type": 1,
        "click_event_elapsed_realtime_ms": 1001, "post_window_id": 192,
        "active_type1_window_ids": [192], "observed_at_elapsed_realtime_ms": 1002,
        "root_window_id": 192, "root_package_name": "com.samsung.android.oneconnect",
        "root_class_name": "android.widget.FrameLayout",
    }

    def kotlin_receipt(req_id, action="ACTION_CLICK",
                       mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK, window_id=44):
        owner_click = {
            "schema": "navigation-owner-click-v1", "request_id": req_id, "transaction_id": "tx-1",
            "owner_lease_id": "owner-lease-1", "action_window_id": 44,
            "service_instance_id": "service-1", "connection_id": "service-1",
            "dispatch_marked_before_action": True, "dispatch_target_currentness_accepted": True,
            "dispatch_elapsed_realtime_ms": 1000, "eligible_exact_click_count": 1,
            "click_event_id": "owner-click-1", "click_event_type": 1,
            "click_event_elapsed_realtime_ms": 1001, "click_event_window_id": 44,
            "owner_exact": True, "authorization_owner_path": [0, 3],
            "action_target_path": [0, 3, 0], "authorization_owner_descriptor_digest": "a" * 64,
            "action_target_descriptor_digest": "d" * 64,
            "activation_owner_relation": {
                "kind": "direct_child", "child_index": 0,
                "child_class_pattern": r"^android\.widget\.FrameLayout$",
                "child_resource_id": "com.samsung.android.oneconnect:id/frameLayout",
            },
            "text": "MUST_NOT_PERSIST",
        }
        value = _receipt(req_id)
        value.update(
            status="VERIFIED_NAVIGATION", verified_navigation=True, visit_authority=False,
            c5_credit=False, action_call_count=1, action=action,
            activation_mode=mode, window_id=window_id,
            post_capture_id="post-capture-192", owner_click_provenance=owner_click,
            post_state_diagnostics={
                "diagnostic_schema": "strict-post-action-v1",
                "request_id": req_id, "transaction_id": "tx-1", "action": "ACTION_CLICK",
                "action_service_instance_id": "service-1", "action_connection_id": "service-1",
                "action_window_id": 44, "capture_request_id": req_id,
                "capture_transaction_id": "tx-1", "capture_service_instance_id": "service-1",
                "capture_connection_id": "service-1", "capture_window_id": 192,
                "post_window_id": 192, "post_capture_id": "post-capture-192",
                "post_captured_at_elapsed_realtime_ms": 1003,
                "post_capture_root_package": "com.samsung.android.oneconnect",
                "post_capture_root_class": "android.widget.FrameLayout",
                "required_destination_match": True, "required_anchor_match_count": 1,
                "required_anchor_outcome": "MATCHED", "receipt_decision": "VERIFIED_NAVIGATION",
                "activation_owner_relation": {
                    "kind": "direct_child", "child_index": 0,
                    "child_class_pattern": r"^android\.widget\.FrameLayout$",
                    "child_resource_id": "com.samsung.android.oneconnect:id/frameLayout",
                },
                "action_owner_path": [0, 3], "action_target_path": [0, 3, 0],
                "owner_click_provenance": owner_click,
                "post_window_authority": dict(authority_template, request_id=req_id),
                "post_structure_evidence": {
                    "exact_text_count": 1, "exact_text_within_webview": True,
                    "container_count": 1, "container_within_webview": False,
                    "webview_count": 2, "exact_back_anchor_count": 1,
                    "excluded_class_present": False, "anchor_path": [0, 1, 0],
                },
            },
        )
        return value

    capture, current = _lease()
    result = HelperBridge(_Client(kotlin_receipt)).dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1",
        capture_session=capture, current_lease=current, readiness=_readiness(),
        activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
    )
    assert result["success"] is True
    assert result["receipt"]["action"] == "ACTION_CLICK"
    assert result["receipt"]["activation_mode"] == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
    assert result["receipt"]["window_id"] == 44
    assert result["receipt"]["post_state_diagnostics"]["post_window_id"] == 192

    projected = collection_flow._navigation_action_evidence_projection(result)
    receipt = projected["receipt"]
    assert receipt["action"] == "ACTION_CLICK"
    assert receipt["activation_mode"] == NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK
    assert receipt["window_id"] == 44
    diagnostics = receipt["post_state_diagnostics"]
    assert diagnostics["action_window_id"] == 44 and diagnostics["post_window_id"] == 192
    assert diagnostics["action_owner_path"] == [0, 3]
    assert diagnostics["action_target_path"] == [0, 3, 0]
    owner_proof = receipt["owner_click_provenance"]
    assert owner_proof["dispatch_marked_before_action"] is True
    assert owner_proof["dispatch_target_currentness_accepted"] is True
    assert owner_proof["authorization_owner_path"] == [0, 3]
    assert owner_proof["action_target_path"] == [0, 3, 0]
    assert owner_proof["activation_owner_relation"]["child_index"] == 0
    assert "text" not in owner_proof
    assert diagnostics["owner_click_provenance"] == owner_proof
    assert diagnostics["post_window_authority"]["active_type1_window_ids"] == [192]
    assert diagnostics["post_structure_evidence"]["webview_count"] == 2

    runtime = EvidenceRuntime(output_path=tmp_path / "navigation-strict-receipt.xlsx",
                              run_id="run-kotlin-shaped-receipt")
    runtime.start_scenario("scenario-1", "test")
    tx = runtime.begin_transaction("NAVIGATION_ACTION", phase="strict_navigation")
    runtime.close_transaction(tx, status="completed", phase="strict_navigation",
        payload={"independent_post_action_observations": {
            "evidence_role": "SECONDARY_ONLY", "strict_navigation_result": projected,
        }})
    closed = next(event for event in runtime.events_for_transaction(tx["transaction_id"])
                  if event.event_type == "TRANSACTION_CLOSED")
    persisted = closed.payload["independent_post_action_observations"]["strict_navigation_result"]["receipt"]
    assert persisted["action"] == "ACTION_CLICK"
    assert persisted["window_id"] == 44
    assert persisted["post_state_diagnostics"]["post_window_id"] == 192
    assert persisted["owner_click_provenance"]["authorization_owner_path"] == [0, 3]
    assert persisted["owner_click_provenance"]["action_target_path"] == [0, 3, 0]
    assert persisted["owner_click_provenance"]["click_event_id"] == "owner-click-1"
    assert "MUST_NOT_PERSIST" not in runtime.ledger.path.read_text(encoding="utf-8")
    assert '"post_window_id":192' in runtime.ledger.path.read_text(encoding="utf-8")

    mismatch = HelperBridge(_Client(lambda req_id: kotlin_receipt(req_id, action="ACTION_LONG_CLICK")))
    rejected = mismatch.dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1",
        capture_session=_lease()[0], current_lease=_lease()[1], readiness=_readiness(),
        activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
    )
    assert rejected["success"] is False
    assert "action" in rejected["receipt_mismatch_fields"]

    for mismatch_field, wrong_mode, wrong_window in (
        ("activation_mode", "DIRECT_CLICK", 44),
        ("window_id", NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK, 192),
    ):
        invalid = HelperBridge(_Client(lambda req_id: kotlin_receipt(
            req_id, mode=wrong_mode, window_id=wrong_window)))
        invalid_result = invalid.dispatch_navigation_action(
            "SERIAL", scenario_id="scenario-1", transaction_id="tx-1",
            capture_session=_lease()[0], current_lease=_lease()[1], readiness=_readiness(),
            activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
        )
        assert invalid_result["success"] is False
        assert mismatch_field in invalid_result["receipt_mismatch_fields"]


def test_kotlin_owner_dispatch_mark_rejection_survives_projection_and_ledger(tmp_path):
    from tb_runner import collection_flow
    from tb_runner.evidence import EvidenceRuntime

    def kotlin_rejection(req_id):
        receipt = _receipt(req_id)
        receipt.update(
            status="REJECTED", verified_navigation=False, action_call_count=0,
            failure_code="NAVIGATION_OWNER_DISPATCH_MARK_UNVERIFIED",
            activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
            owner_dispatch_mark_reason="ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE",
            owner_dispatch_mark_ok=False, owner_dispatch_mark_lease_match=True,
            owner_dispatch_mark_target_match=False,
            owner_dispatch_mark_eligible_exact_click_count=1,
            owner_receipt_reason="OWNER_CLICK_EVENT_NOT_RECORDED",
            owner_receipt_eligible_exact_click_count=0,
            activation_diagnostics={"focus_revalidation": {
                "focus_event_owner_matches": True,
                "target_currentness": {
                    "diagnostics_available": True,
                    "aggregate_accepted": False,
                    "first_failed_check": "focus_neutral_hierarchy_digest_matches",
                    "focus_neutral_hierarchy_digest_matches": False,
                    "focus_neutral_action_ids_added": [128],
                    "focus_neutral_action_ids_removed": [64],
                    "focus_neutral_action_id_delta_complete": True,
                    "private_text": "MUST_NOT_PERSIST",
                },
            }},
        )
        return receipt

    capture, current = _lease()
    bridge_result = HelperBridge(_Client(kotlin_rejection)).dispatch_navigation_action(
        "SERIAL", scenario_id="scenario-1", transaction_id="tx-1",
        capture_session=capture, current_lease=current, readiness=_readiness(),
        activation_mode=NAVIGATION_ACTIVATION_EXACT_OWNER_FOCUS_THEN_CLICK,
    )
    assert bridge_result["success"] is False
    assert bridge_result["receipt"]["owner_dispatch_mark_reason"] == "ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE"
    assert bridge_result["receipt_owner_receipt_reason"] == "OWNER_CLICK_EVENT_NOT_RECORDED"
    assert bridge_result["receipt_owner_click_count"] == 0

    projected = collection_flow._navigation_action_evidence_projection(bridge_result)
    assert projected["owner_dispatch_mark_reason"] == "ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE"
    assert projected["owner_dispatch_mark_ok"] is False
    assert projected["owner_dispatch_mark_lease_match"] is True
    assert projected["owner_dispatch_mark_target_match"] is False
    assert projected["owner_dispatch_mark_eligible_exact_click_count"] == 1
    assert projected["receipt_owner_receipt_reason"] == "OWNER_CLICK_EVENT_NOT_RECORDED"
    assert projected["receipt_owner_click_count"] == 0
    focus = projected["activation_diagnostics"]["focus_revalidation"]
    assert focus["focus_event_owner_matches"] is True
    assert focus["target_currentness"]["first_failed_check"] == "focus_neutral_hierarchy_digest_matches"
    assert focus["target_currentness"]["focus_neutral_action_ids_added"] == [128]
    assert "private_text" not in focus["target_currentness"]

    runtime = EvidenceRuntime(output_path=tmp_path / "owner-dispatch-mark.xlsx",
                              run_id="run-owner-dispatch-mark")
    runtime.start_scenario("scenario-1", "test")
    tx = runtime.begin_transaction("NAVIGATION_ACTION", phase="strict_navigation")
    runtime.close_transaction(tx, status="completed", phase="strict_navigation",
        payload={"independent_post_action_observations": {
            "evidence_role": "SECONDARY_ONLY", "strict_navigation_result": projected,
        }})
    closed = next(event for event in runtime.events_for_transaction(tx["transaction_id"])
                  if event.event_type == "TRANSACTION_CLOSED")
    persisted = closed.payload["independent_post_action_observations"]["strict_navigation_result"]
    for key in ("owner_dispatch_mark_reason", "owner_dispatch_mark_ok",
                "owner_dispatch_mark_lease_match", "owner_dispatch_mark_target_match",
                "owner_dispatch_mark_eligible_exact_click_count", "receipt_owner_receipt_reason",
                "receipt_owner_click_count"):
        assert persisted[key] == projected[key]
    assert persisted["success"] is False and persisted["status"] == "rejected"
    assert "navigation_credit" not in persisted and "visit_authority" not in persisted
    ledger_text = runtime.ledger.path.read_text(encoding="utf-8")
    assert "MUST_NOT_PERSIST" not in ledger_text


def test_kotlin_shaped_diagnostic_receipt_passes_validator_and_remains_no_credit_in_projection():
    from tb_runner import collection_flow

    def diagnostic_receipt(req_id):
        value = _receipt(req_id)
        value.update(
            scenario_id="life_air_care_plugin",
            effect_contract_id="life_service_card_read_only_navigation",
            status="DIAGNOSTIC_ONLY", verified_navigation=False, visit_authority=False,
            c5_credit=False, traversal_credit=False, action_call_count=1, action="ACTION_CLICK",
            diagnostic_only=True, diagnostic_action_dispatched=True,
            activation_mode=NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK,
            diagnostic_target={
                "path": [0, 3, 0], "class_name": "android.widget.FrameLayout",
                "resource_id": "com.samsung.android.oneconnect:id/frameLayout", "window_id": 44,
                "source_snapshot_id": "source-1", "helper_snapshot_id": "helper-1",
                "baseline_hierarchy_digest": "b" * 64, "parent_path": [0, 3],
            },
            diagnostic_click_event={
                "exact_target_match": True, "event_type": 1, "request_id": req_id,
                "transaction_id": "tx-1", "service_instance_id": "service-1",
                "connection_id": "service-1", "window_id": 44,
            },
            post_state_diagnostics={
                "capture_polling": {"schema": "navigation-post-capture-poll-v1",
                    "request_id": req_id, "transaction_id": "tx-1", "service_instance_id": "service-1",
                    "connection_id": "service-1", "action_window_id": 44, "attempt_count": 2,
                    "complete_sample_count": 1, "observed_active_type1_window_ids": [192],
                    "skip_reason_counts": {"ACTION_WINDOW_NOT_ACTIVE_TYPE1": 1}},
                "post_window_authority": {"schema": "navigation-post-window-authority-v1",
                    "request_id": req_id, "transaction_id": "tx-1", "service_instance_id": "service-1",
                    "connection_id": "service-1", "action_window_id": 44, "post_window_id": 192,
                    "active_type1_window_ids": [192]},
            },
        )
        return value

    capture, current = _lease()
    capture["armed"].update(scenarioId="life_air_care_plugin",
                             ownerPackageName="com.samsung.android.oneconnect")
    current["result"].update(scenarioId="life_air_care_plugin",
                              ownerPackageName="com.samsung.android.oneconnect")
    readiness = _readiness()
    readiness.update(scenario_id="life_air_care_plugin",
                     contract_id="life_service_card_read_only_navigation")
    result = HelperBridge(_Client(diagnostic_receipt)).dispatch_navigation_action(
        "SERIAL", scenario_id="life_air_care_plugin", transaction_id="tx-1",
        capture_session=capture, current_lease=current, readiness=readiness,
        activation_mode=NAVIGATION_ACTIVATION_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK,
    )
    assert result["success"] is False and result["status"] == "diagnostic_only", result.get("receipt_mismatch_fields")
    projected = collection_flow._navigation_action_evidence_projection(result)
    assert projected["diagnostic_only"] is True and projected["navigation_credit"] is False
    receipt = projected["receipt"]
    assert receipt["action"] == "ACTION_CLICK"
    assert receipt["window_id"] == 44
    assert receipt["verified_navigation"] is False and receipt["visit_authority"] is False
    assert receipt["c5_credit"] is False and receipt["traversal_credit"] is False
    assert receipt["post_state_diagnostics"]["post_window_authority"]["post_window_id"] == 192
