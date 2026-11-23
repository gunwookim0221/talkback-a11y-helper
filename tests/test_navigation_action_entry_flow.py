from copy import deepcopy
import base64
import hashlib
import json
from types import SimpleNamespace

from tb_runner import collection_flow, entry_safety


def test_secondary_window_event_diagnostics_log_as_separate_secondary_record():
    diagnostics = {
        "evidence_role": "SECONDARY_ONLY", "request_id": "request-1", "transaction_id": "tx-1",
        "service_instance_id": "service-1", "connection_id": "service-1", "owner_window_id": 26,
        "events": [{"event_type": 32, "event_window_id": 26}],
    }
    line = collection_flow._secondary_window_event_diagnostics_log_line(diagnostics)

    assert line is not None
    assert line.startswith("[NAVIGATION_ACTION][secondary_window_event_diagnostics] ")
    assert '"evidence_role":"SECONDARY_ONLY"' in line
    assert '"transaction_id":"tx-1"' in line
    assert collection_flow._secondary_window_event_diagnostics_log_line({"evidence_role": "STRICT"}) is None


def test_diagnostic_frame_layout_mode_requires_explicit_aircare_scenario_and_contract(monkeypatch):
    readiness = {"contract_id": "life_service_card_read_only_navigation"}
    monkeypatch.delenv("TB_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD", raising=False)
    assert collection_flow._navigation_entry_activation_mode("life_air_care_plugin", readiness) == \
        "EXACT_OWNER_FOCUS_THEN_CLICK"

    monkeypatch.setenv("TB_DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD", "1")
    assert collection_flow._navigation_entry_activation_mode("life_air_care_plugin", readiness) == \
        "DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK"
    assert collection_flow._navigation_entry_activation_mode("life_energy_plugin", readiness) == \
        "EXACT_OWNER_FOCUS_THEN_CLICK"
    assert collection_flow._navigation_entry_activation_mode(
        "life_air_care_plugin", {"contract_id": "other-contract"}) == \
        "EXACT_OWNER_FOCUS_THEN_CLICK"
    assert collection_flow._navigation_entry_activation_mode(
        "life_air_care_plugin", {"contract_id": "life_plugin_navigate_up_to_landing"}) == \
        "EXACT_OWNER_FOCUS_THEN_CLICK"


def _ready(scenario_id="life_air_care_plugin", contract_id="life_service_card_read_only_navigation"):
    service_id = "fixture-service-instance"
    tab_cfg = {"scenario_id": scenario_id, "entry_type": "card", "screen_context_mode": "new_screen"}
    policy_contract = collection_flow._navigation_action_policy_contract(tab_cfg, scenario_id, contract_id)
    contract = {
        "contract_id": policy_contract["id"] if policy_contract else "reviewed-navigation",
        "contract_digest": "a" * 64,
        "scenario_ids": [scenario_id],
    }
    return {
        "eligible": True,
        "scenario_id": scenario_id,
        "contract_id": contract["contract_id"],
        "contract_digest": contract["contract_digest"],
        "identity_check": {
            "status": "EXACT_MATCH",
            "helper_service_instance_id": service_id,
            "capability_service_instance_id": service_id,
            "capability_process_epoch": "fixture-process-epoch",
            "capability_generation": 7,
            "helper_connection_epoch": "fixture-connection-epoch",
            "boot_epoch": "boot:7",
            "navigation_action_state": {
                "supported": True,
                "enabled": True,
                "ready": True,
                "default_enabled": False,
                "visit_credit": False,
                "c5_credit": False,
                "exact_action_gate_independent": True,
                "service_instance_id": service_id,
                "contracts": [contract],
            },
        },
    }


def _trusted_capture_authority(nodes=None, *, request_id="hierarchy-request-1", sequence=7,
                               generation=7, window_id=45518):
    from phase6d_capture_support import attach_capture_authority
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority

    source = attach_capture_authority({
        "nodes": list(nodes or []),
        "package_name": "com.samsung.android.oneconnect",
        "capture_root_bounds": [0, 0, 1080, 2640],
        "traversal_root_class_name": "android.widget.FrameLayout",
    }, request_id=request_id, sequence=sequence, generation=generation, window_id=window_id)
    authority = validate_capture_authority(source["capture_authority"])
    assert authority is not None
    return authority, source["_capture_root_tree"]


def _owner():
    authority, _root = _trusted_capture_authority(window_id=45518)
    return {
        "_helperNodePath": [0, 1, 4],
        "_helperNodeDescriptorDigest": "b" * 64,
        "_helperSourceSnapshotId": authority.capture_key,
        "_helperCaptureRequestId": authority.request_id,
        "_helperCaptureAuthority": authority.to_dict(),
        "_helperConnectionEpoch": "fixture-connection-epoch",
        "_helperBootEpoch": "boot:7",
        "_helperOwnerSourceNodeId": "node-source-1",
        "_helperOwnerSourceNodeIdStatus": "FIELD_PRESENT",
        "sourceNodeId": "node-source-1",
        "windowId": 45518,
        "packageName": "com.samsung.android.oneconnect",
        "clickable": True,
        "effectiveClickable": True,
        "enabled": True,
        "checkable": False,
        "actions": [{"id": 16, "name": "ACTION_CLICK"}],
    }


def _capture(owner=None):
    owner = owner or _owner()
    authority = owner["_helperCaptureAuthority"]
    tx = "tx-1"
    lease_request_id = "capture-request-1"
    response_request_id = f"{lease_request_id}_begin_abc123"
    return {
        "req_id": lease_request_id,
        "transaction_id": tx,
        "armed": {
            "ok": True,
            "reqId": response_request_id,
            "responseReqId": response_request_id,
            "captureReqId": lease_request_id,
            "scenarioId": "life_air_care_plugin",
            "requestedTransactionId": tx,
            "ownerPath": owner["_helperNodePath"],
            "ownerDescriptorDigest": owner["_helperNodeDescriptorDigest"],
            "sourceSnapshotId": owner["_helperSourceSnapshotId"],
            "ownerWindowId": owner["windowId"],
            "ownerPackageName": owner["packageName"],
            "sourceCaptureRequestId": authority["request_id"],
            "sourceProcessEpoch": authority["process_epoch"],
            "sourceGeneration": authority["generation"],
            "sourceServiceInstanceId": authority["service_instance_id"],
            "sourceCaptureSequence": authority["capture_sequence"],
            "sourceRootDigest": authority["root_digest"],
            "sourceCandidateDigest": authority["candidate_digest"],
            "sourceCaptureKey": authority["capture_key"],
            "sourceConnectionEpoch": owner.get("_helperConnectionEpoch", "fixture-connection-epoch"),
            "sourceBootEpoch": owner.get("_helperBootEpoch", "boot:7"),
            "ownerSourceNodeId": owner.get("_helperOwnerSourceNodeId", owner.get("sourceNodeId", "node-source-1")),
            "ownerSourceNodeIdStatus": owner.get("_helperOwnerSourceNodeIdStatus", "FIELD_PRESENT"),
            "connectionId": "fixture-service-instance",
            "ownerLeaseId": "lease-1",
            "captureId": "capture-1",
            "runId": "run-1",
            "invocationId": "invoke-1",
            "helperSnapshotId": "helper-snapshot-1",
            "leaseDeadlineElapsedRealtimeMs": 123456,
        },
    }


def test_navigation_card_new_screen_requires_unique_ready_helper_contract():
    tab = {"scenario_id": "life_air_care_plugin", "entry_type": "card", "screen_context_mode": "new_screen"}
    ready = _ready()
    assert collection_flow._navigation_action_entry_required(tab)
    assert collection_flow._navigation_action_entry_gate_reason(
        tab, ready, "life_air_care_plugin", "life_service_card_read_only_navigation") is None
    assert collection_flow._navigation_action_entry_gate_reason(tab, None, "life_air_care_plugin") == \
        "NAVIGATION_ACTION_CONTRACT_NOT_READY"
    assert collection_flow._navigation_action_entry_gate_reason(
        {"entry_type": "button", "screen_context_mode": "new_screen"}, None, "life_air_care_plugin") is None


def test_navigation_contract_selection_uses_configured_id_when_scenario_has_multiple_routes():
    tab = {"scenario_id": "life_air_care_plugin", "entry_type": "card", "screen_context_mode": "new_screen"}
    card = _ready()
    card_contract = card["identity_check"]["navigation_action_state"]["contracts"][0]
    up = _ready(contract_id="life_plugin_navigate_up_to_landing")
    up_contract = up["identity_check"]["navigation_action_state"]["contracts"][0]
    card["identity_check"]["navigation_action_state"]["contracts"].append(up_contract)

    card_auth = collection_flow._navigation_action_effect_authorization(
        tab, card, "life_air_care_plugin", "life_service_card_read_only_navigation")
    up_auth = collection_flow._navigation_action_effect_authorization(
        tab, up, "life_air_care_plugin", "life_plugin_navigate_up_to_landing")
    assert card_auth["contract_id"] == card_contract["contract_id"]
    assert up_auth["contract_id"] == "life_plugin_navigate_up_to_landing"
    assert collection_flow._navigation_action_effect_authorization(tab, card, "life_air_care_plugin") is None


def test_navigation_recovery_authorization_is_data_configured_and_separate_from_card_entry():
    recovery = {
        "scenario_id": "life_air_care_plugin",
        "navigation_action_recovery": {
            "contract_id": "life_plugin_navigate_up_to_landing",
            "target": "(?i)^navigate up$",
        },
    }
    readiness = _ready(contract_id="life_plugin_navigate_up_to_landing")
    auth = collection_flow._navigation_action_effect_authorization(
        recovery, readiness, "life_air_care_plugin", "life_plugin_navigate_up_to_landing")
    assert auth is not None
    assert auth["effect"] == "read_only_navigation"
    assert auth["contract_id"] == "life_plugin_navigate_up_to_landing"
    assert collection_flow._navigation_action_effect_authorization(
        recovery, readiness, "life_air_care_plugin", "unconfigured-contract") is None
    assert collection_flow._navigation_action_entry_gate_reason(
        {"scenario_id": "life_air_care_plugin", "entry_type": "button"},
        None, "life_air_care_plugin") is None


def test_navigation_effect_authorization_requires_enabled_packaged_contract_and_matching_ready_helper(monkeypatch):
    tab = {"scenario_id": "life_air_care_plugin", "entry_type": "card", "screen_context_mode": "new_screen"}
    ready = _ready()
    permit = collection_flow._navigation_action_effect_authorization(
        tab, ready, "life_air_care_plugin", "life_service_card_read_only_navigation")
    assert permit is not None
    assert permit["effect"] == "read_only_navigation"
    assert permit["contract_id"] == ready["contract_id"]
    assert permit["contract_digest"] == ready["contract_digest"]
    assert permit["scenario_id"] == "life_air_care_plugin"
    assert permit["service_instance_id"] == "fixture-service-instance"
    assert collection_flow._navigation_action_effect_authorization(
        tab, None, "life_air_care_plugin", "life_service_card_read_only_navigation") is None
    assert collection_flow._navigation_action_effect_authorization(tab, ready, "life_air_care_plugin") is None

    stale = deepcopy(ready)
    stale["identity_check"]["status"] = "STALE"
    assert collection_flow._navigation_action_effect_authorization(
        tab, stale, "life_air_care_plugin", "life_service_card_read_only_navigation") is None

    mismatched = deepcopy(ready)
    mismatched["contract_id"] = "other-contract"
    mismatched["identity_check"]["navigation_action_state"]["contracts"][0]["contract_id"] = "other-contract"
    assert collection_flow._navigation_action_effect_authorization(
        tab, mismatched, "life_air_care_plugin", "life_service_card_read_only_navigation") is None

    mismatched_digest = deepcopy(ready)
    mismatched_digest["contract_digest"] = "b" * 64
    assert collection_flow._navigation_action_effect_authorization(
        tab, mismatched_digest, "life_air_care_plugin", "life_service_card_read_only_navigation") is None

    disabled_policy = deepcopy(collection_flow._load_navigation_action_policy())
    next(row for row in disabled_policy["contracts"]
         if row.get("id") == "life_service_card_read_only_navigation")["enabled"] = False
    monkeypatch.setattr(collection_flow, "_load_navigation_action_policy", lambda: disabled_policy)
    assert collection_flow._navigation_action_effect_authorization(
        tab, ready, "life_air_care_plugin", "life_service_card_read_only_navigation") is None

    missing_readiness = deepcopy(ready)
    missing_readiness["identity_check"]["navigation_action_state"]["contracts"] = []
    assert collection_flow._navigation_action_effect_authorization(
        tab, missing_readiness, "life_air_care_plugin", "life_service_card_read_only_navigation") is None


def test_navigation_readiness_rejects_missing_ambiguous_or_credit_bearing_contract():
    ready = _ready()
    assert collection_flow._navigation_action_readiness_valid(ready, "life_air_care_plugin")
    wrong_scenario = deepcopy(ready)
    wrong_scenario["scenario_id"] = "other"
    assert not collection_flow._navigation_action_readiness_valid(wrong_scenario, "life_air_care_plugin")
    duplicate = deepcopy(ready)
    duplicate["identity_check"]["navigation_action_state"]["contracts"].append(
        deepcopy(duplicate["identity_check"]["navigation_action_state"]["contracts"][0]))
    assert not collection_flow._navigation_action_readiness_valid(duplicate, "life_air_care_plugin")
    c5_credit = deepcopy(ready)
    c5_credit["identity_check"]["navigation_action_state"]["c5_credit"] = True
    assert not collection_flow._navigation_action_readiness_valid(c5_credit, "life_air_care_plugin")
    missing_digest = deepcopy(ready)
    missing_digest["contract_digest"] = ""
    assert not collection_flow._navigation_action_readiness_valid(missing_digest, "life_air_care_plugin")


def test_navigation_owner_lifecycle_identity_requires_current_connection_and_boot_epochs():
    ready = _ready()
    assert collection_flow._navigation_source_lifecycle_identity(ready) == ("fixture-connection-epoch", "boot:7")
    for key in ("helper_connection_epoch", "boot_epoch"):
        missing = deepcopy(ready)
        missing["identity_check"].pop(key)
        assert collection_flow._navigation_source_lifecycle_identity(missing) is None
    stale = deepcopy(ready)
    stale["identity_check"]["helper_connection_epoch"] = "UNKNOWN"
    assert collection_flow._navigation_source_lifecycle_identity(stale) is None
    stale = deepcopy(ready)
    stale["identity_check"]["boot_epoch"] = "boot:bad value"
    assert collection_flow._navigation_source_lifecycle_identity(stale) is None


def test_navigation_owner_reads_lifecycle_identity_from_correlated_ping_when_gates_are_off():
    ready = _ready()
    identity = ready["identity_check"]
    identity.pop("helper_connection_epoch")
    identity.pop("boot_epoch")
    identity["exact_action_state"] = {
        "connection_epoch": "ping-connection-epoch",
        "boot_epoch": "boot:8",
        "build_gate": False,
        "runtime_gate": False,
        "helper_stopped": True,
    }
    assert collection_flow._navigation_source_lifecycle_identity(ready) == (
        "ping-connection-epoch", "boot:8")


def test_navigation_owner_requires_action_click_and_current_exact_descriptor():
    owner = _owner()
    assert collection_flow._navigation_action_owner_has_current_identity(owner)
    wrong_action = deepcopy(owner)
    wrong_action["actions"] = [{"id": 32, "name": "ACTION_LONG_CLICK"}]
    assert not collection_flow._navigation_action_owner_has_current_identity(wrong_action)
    stale_descriptor = deepcopy(owner)
    stale_descriptor["_helperNodeDescriptorDigest"] = ""
    assert not collection_flow._navigation_action_owner_has_current_identity(stale_descriptor)
    missing_snapshot = deepcopy(owner)
    missing_snapshot["_helperSourceSnapshotId"] = None
    assert not collection_flow._navigation_action_owner_has_current_identity(missing_snapshot)
    missing_click = deepcopy(owner)
    missing_click["actions"] = []
    assert not collection_flow._navigation_action_owner_has_current_identity(missing_click)


def test_navigation_owner_capture_is_armed_only_for_the_selected_exact_parent():
    parent = _owner()
    child = deepcopy(parent)
    child["_helperNodePath"] = [0, 1, 4, 0]
    child["_helperNodeDescriptorDigest"] = "c" * 64
    ready = _ready()
    calls = []
    capture_options = []

    class Capture:
        @staticmethod
        def begin_transaction_click_capture(client, dev, *, transaction_id, target_node, scenario_id,
                                            include_talkback_baseline=True, result_wait_seconds=0.25,
                                            require_canonical_invocation=False):
            calls.append(target_node)
            capture_options.append((include_talkback_baseline, result_wait_seconds, require_canonical_invocation))
            return _capture(target_node)

    capture, ok, reason = collection_flow._arm_navigation_action_owner_lease(
        object(), "SERIAL", Capture, parent, "life_air_care_plugin", "tx-1", ready)
    assert ok is True
    assert reason == "NAVIGATION_OWNER_LEASE_ARMED"
    assert capture["armed"]["ownerPath"] == parent["_helperNodePath"]
    assert calls == [parent]
    assert capture_options == [(False, 0.25, True)]

    calls.clear()
    child_capture = _capture(child)
    child_capture["transaction_id"] = "tx-1"
    Capture.begin_transaction_click_capture = staticmethod(
        lambda *args, **kwargs: child_capture)
    capture, ok, reason = collection_flow._arm_navigation_action_owner_lease(
        object(), "SERIAL", Capture, parent, "life_air_care_plugin", "tx-1", ready)
    assert ok is False
    assert reason == "NAVIGATION_OWNER_LEASE_MISMATCH"
    assert capture is child_capture

    calls.clear()
    Capture.begin_transaction_click_capture = staticmethod(
        lambda *args, **kwargs: calls.append(kwargs["target_node"]) or _capture(kwargs["target_node"]))
    capture, ok, reason = collection_flow._arm_navigation_action_owner_lease(
        object(), "SERIAL", Capture, parent, "life_air_care_plugin", "tx-1", None)
    assert capture is None and ok is False
    assert reason == "NAVIGATION_ACTION_CONTRACT_NOT_READY"
    assert calls == []


def test_navigation_owner_lease_preserves_missing_begin_result_reason():
    parent = _owner()
    ready = _ready()
    capture = {
        "req_id": "entry_click_capture_miss",
        "transaction_id": "tx-1",
        "armed": {"ok": False, "reason": "ENTRY_CLICK_CAPTURE_RESULT_UNAVAILABLE"},
    }

    class Capture:
        @staticmethod
        def begin_transaction_click_capture(*_args, **_kwargs):
            return capture

    returned, ok, reason = collection_flow._arm_navigation_action_owner_lease(
        object(), "SERIAL", Capture, parent, "life_air_care_plugin", "tx-1", ready)
    assert returned is capture
    assert ok is False
    assert reason == "ENTRY_CLICK_CAPTURE_RESULT_UNAVAILABLE"


def test_navigation_capture_uses_canonical_runtime_ids_and_fails_closed_without_them(monkeypatch):
    owner = _owner()
    calls = []

    class Client:
        evidence_runtime = SimpleNamespace(run_id="run-trusted", is_enabled=True,
                                            _scenario_id="life_air_care_plugin",
                                            _scenario_tx_id="scenario-transaction")
        _active_evidence_scenario_id = "life_air_care_plugin"
        _active_evidence_scenario_tx_id = "scenario-transaction"

    def _begin(client, dev, **kwargs):
        calls.append(kwargs)
        return {"ok": True, "captureId": "capture-1", "connectionId": "fixture-service-instance"}

    monkeypatch.setattr(entry_safety, "_entry_capture_request", _begin)
    capture = entry_safety.begin_transaction_click_capture(
        Client(), "SERIAL", transaction_id="action-transaction", target_node=owner,
        scenario_id="life_air_care_plugin", include_talkback_baseline=False,
        require_canonical_invocation=True,
    )
    lease_request = calls[0]["owner_lease_request"]
    assert lease_request["run_id"] == "run-trusted"
    assert lease_request["invocation_id"] == "scenario-transaction"
    assert lease_request["invocation_id"] != f"life_air_care_plugin:{capture['req_id']}"
    assert lease_request["request_id"] == capture["req_id"]
    assert lease_request["transaction_id"] == "action-transaction"
    authority = owner["_helperCaptureAuthority"]
    assert lease_request["source_capture_request_id"] == authority["request_id"]
    assert lease_request["source_process_epoch"] == authority["process_epoch"]
    assert lease_request["source_generation"] == authority["generation"]
    assert lease_request["source_service_instance_id"] == authority["service_instance_id"]
    assert lease_request["source_capture_sequence"] == authority["capture_sequence"]
    assert lease_request["source_root_digest"] == authority["root_digest"]
    assert lease_request["source_candidate_digest"] == authority["candidate_digest"]
    assert lease_request["source_capture_key"] == authority["capture_key"]
    assert lease_request["source_connection_epoch"] == "fixture-connection-epoch"
    assert lease_request["source_boot_epoch"] == "boot:7"
    assert lease_request["owner_source_node_id"] == "node-source-1"
    assert calls[0]["invocation_id"] == lease_request["invocation_id"]

    calls.clear()

    class MissingRuntime:
        _active_evidence_scenario_id = ""
        _active_evidence_scenario_tx_id = ""

    denied = entry_safety.begin_transaction_click_capture(
        MissingRuntime(), "SERIAL", transaction_id="action-transaction", target_node=owner,
        scenario_id="life_air_care_plugin", include_talkback_baseline=False,
        require_canonical_invocation=True,
    )
    assert denied["armed"]["ok"] is False
    assert denied["armed"]["reason"] == "CANONICAL_INVOCATION_IDENTITY_UNAVAILABLE"
    assert calls == []

    class StaleRuntime:
        evidence_runtime = SimpleNamespace(run_id="run-trusted", is_enabled=True,
                                            _scenario_id="life_air_care_plugin",
                                            _scenario_tx_id="previous-scenario-transaction")
        _active_evidence_scenario_id = "life_air_care_plugin"
        _active_evidence_scenario_tx_id = "scenario-transaction"

    stale = entry_safety.begin_transaction_click_capture(
        StaleRuntime(), "SERIAL", transaction_id="action-transaction", target_node=owner,
        scenario_id="life_air_care_plugin", include_talkback_baseline=False,
        require_canonical_invocation=True,
    )
    assert stale["armed"]["ok"] is False
    assert stale["armed"]["reason"] == "CANONICAL_INVOCATION_IDENTITY_UNAVAILABLE"
    assert calls == []

    missing_source = dict(owner)
    missing_source.pop("_helperCaptureAuthority")
    rejected = entry_safety.begin_transaction_click_capture(
        Client(), "SERIAL", transaction_id="action-transaction", target_node=missing_source,
        scenario_id="life_air_care_plugin", include_talkback_baseline=False,
        require_canonical_invocation=True,
    )
    assert rejected["armed"]["ok"] is False
    assert rejected["armed"]["reason"] == "SOURCE_CAPTURE_AUTHORITY_UNAVAILABLE"
    assert calls == []


def test_navigation_capture_rejects_stale_transaction_connection_and_expiry():
    owner = _owner()
    capture = _capture(owner)
    assert collection_flow._navigation_action_capture_matches_owner(
        capture, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["requestedTransactionId"] = "old-tx"
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["connectionId"] = "old-service"
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["sourceCaptureSequence"] += 1
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["sourceConnectionEpoch"] = "old-connection-epoch"
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["sourceBootEpoch"] = "boot:stale"
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["ownerSourceNodeId"] = "different-node"
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["req_id"] = "wrong-capture-request"
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["captureReqId"] = "wrong-capture-request"
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["reqId"] = "wrong-response-request"
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["ownerWindowId"] = 999
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")
    stale = deepcopy(capture)
    stale["armed"]["leaseDeadlineElapsedRealtimeMs"] = 0
    assert not collection_flow._navigation_action_capture_matches_owner(
        stale, owner, "life_air_care_plugin", "tx-1", "fixture-service-instance")


def test_navigation_entry_selector_uses_validated_candidate_snapshot_for_owner_identity():
    target = {
        "className": "android.widget.RelativeLayout",
        "packageName": "com.example.app",
        "windowId": 44,
        "boundsInScreen": {"left": 10, "top": 20, "right": 110, "bottom": 120},
        "clickable": True,
        "enabled": True,
        "checkable": False,
        "actions": [{"id": 16, "name": "ACTION_CLICK"}],
        "children": [],
    }
    raw_hierarchy = {
        "success": True,
        "snapshotId": "current-helper-snapshot",
        "windows": [{
            "root": {
                "className": "android.widget.FrameLayout",
                "packageName": "com.example.app",
                "windowId": 44,
                "boundsInScreen": {"left": 0, "top": 0, "right": 120, "bottom": 140},
                "children": [target],
            },
            "active": True,
            "focused": True,
        }],
    }

    class Client:
        def get_traversal_candidate_snapshot(self, *, dev):
            assert dev == "SERIAL"
            return SimpleNamespace(raw_hierarchy=raw_hierarchy)

        def dump_hierarchy(self, **_kwargs):
            raise AssertionError("legacy dump must not replace a failed/current reliable snapshot")

    nodes, reason = collection_flow._load_scrolltouch_xml_nodes(Client(), "SERIAL")
    assert reason == "ok"
    owner = nodes[0]["children"][0]["children"][0]
    assert owner["_helperNodePath"] == [0]
    assert owner["_helperSourceSnapshotId"] == "current-helper-snapshot"
    assert len(owner["_helperNodeDescriptorDigest"]) == 64
    assert owner["windowId"] == 44 and owner["actions"][0]["name"] == "ACTION_CLICK"


def _navigation_helper_snapshot(*, targets=None, stale_identity=False, omit_raw_snapshot_id=False,
                                request_id="hierarchy-request-1", sequence=7, generation=7):
    targets = targets if targets is not None else [{
        "text": "Navigate to parent menu",
        "contentDescription": "",
        "viewIdResourceName": "back",
        "className": "android.widget.Button",
        "packageName": "com.samsung.android.oneconnect",
        "sourceNodeId": "10",
        "windowId": 45534,
        "boundsInScreen": {"left": 48, "top": 126, "right": 168, "bottom": 270},
        "clickable": True,
        "effectiveClickable": True,
        "enabled": True,
        "checkable": False,
        "actions": [{"id": 16, "name": "ACTION_CLICK"}],
        "children": [],
    }]
    authority, root = _trusted_capture_authority(
        targets, request_id=request_id, sequence=sequence, generation=generation, window_id=45534)
    snapshot_id = authority.capture_key
    raw = {
        "success": True,
        "reqId": request_id,
        "snapshotId": "stale-capture-key" if stale_identity else snapshot_id,
        "windows": [{
            "active": True,
            "focused": True,
            "root": root,
        }],
    }
    if omit_raw_snapshot_id:
        raw.pop("snapshotId")
    decoded = SimpleNamespace(capability_verified=True, raw_completion_valid=True,
                              request_id=request_id, capture_authority=authority)
    return SimpleNamespace(raw_hierarchy=raw, decoded=decoded)


def _aircare_parent_candidate(status="나쁨"):
    candidate = {
        "text": "", "contentDescription": "", "viewIdResourceName": "",
        "className": "android.widget.RelativeLayout", "packageName": "com.samsung.android.oneconnect",
        "sourceNodeId": None, "windowId": 45534, "boundsInScreen": {"left": 30, "top": 1437, "right": 1050, "bottom": 1941},
        "clickable": True, "effectiveClickable": True, "enabled": True, "checkable": False,
        "actions": [{"id": 16, "name": "ACTION_CLICK"}],
        "children": [{
            "text": "", "contentDescription": "", "viewIdResourceName": "com.samsung.android.oneconnect:id/frameLayout",
            "className": "android.widget.FrameLayout", "packageName": "com.samsung.android.oneconnect",
            "sourceNodeId": None, "windowId": 45534, "clickable": True, "enabled": True, "checkable": False,
            "longClickable": True, "actions": [{"id": 16, "name": "ACTION_CLICK"}, {"id": 32, "name": "ACTION_LONG_CLICK"}],
            "children": [{
                "text": "에어 케어", "contentDescription": "", "viewIdResourceName": "com.samsung.android.oneconnect:id/llCard",
                "className": "android.widget.LinearLayout", "packageName": "com.samsung.android.oneconnect",
                "sourceNodeId": None, "windowId": 45534, "clickable": False, "enabled": True, "checkable": False,
                "actions": [], "children": [
                    {"text": "우리 집 공기를 실외 공기만큼 깨끗하게 유지하고 싶다면 공기청정기나 에어컨을 추가하세요.",
                     "contentDescription": "", "viewIdResourceName": "com.samsung.android.oneconnect:id/tvHeaderTitle",
                     "className": "android.widget.TextView", "packageName": "com.samsung.android.oneconnect",
                     "sourceNodeId": None, "windowId": 45534, "clickable": False, "enabled": True, "checkable": False,
                     "actions": [], "children": []},
                    {"text": "", "contentDescription": f"\\n{status}\\n야외",
                     "viewIdResourceName": "com.samsung.android.oneconnect:id/include",
                     "className": "android.widget.LinearLayout", "packageName": "com.samsung.android.oneconnect",
                     "sourceNodeId": None, "windowId": 45534, "clickable": True, "enabled": True, "checkable": False,
                     "actions": [{"id": 16, "name": "ACTION_CLICK"}], "children": [
                         {"text": "사진", "contentDescription": "", "viewIdResourceName": "com.samsung.android.oneconnect:id/imageView",
                          "className": "android.widget.ImageView", "packageName": "com.samsung.android.oneconnect",
                          "sourceNodeId": None, "windowId": 45534, "clickable": False, "enabled": True, "checkable": False,
                          "actions": [], "children": []},
                         {"text": status, "contentDescription": status, "viewIdResourceName": "com.samsung.android.oneconnect:id/textView",
                          "className": "android.widget.TextView", "packageName": "com.samsung.android.oneconnect",
                          "sourceNodeId": None, "windowId": 45534, "clickable": False, "enabled": True, "checkable": False,
                          "actions": [], "children": []},
                         {"text": "야외", "contentDescription": "", "viewIdResourceName": "com.samsung.android.oneconnect:id/textView2",
                          "className": "android.widget.TextView", "packageName": "com.samsung.android.oneconnect",
                          "sourceNodeId": None, "windowId": 45534, "clickable": False, "enabled": True, "checkable": False,
                          "actions": [], "children": []},
                     ]},
                ]},
            ]},
        ]}
    # The production hierarchy adapter retains visible descendants by bounds;
    # model the bound-bearing Helper rows without changing action topology.
    def bind_visible_bounds(node):
        node.setdefault("boundsInScreen", {"left": 30, "top": 1437, "right": 1050, "bottom": 1941})
        for child in node.get("children", []):
            bind_visible_bounds(child)
    bind_visible_bounds(candidate)
    return candidate


def test_aircare_parent_resolves_with_observed_status_variant_and_explicit_absent_source_id():
    snapshot = _navigation_helper_snapshot(targets=[_aircare_parent_candidate()],
                                           request_id="aircare-status-variant", sequence=10, generation=10)
    authority = snapshot.decoded.capture_authority
    class Client:
        last_hierarchy_metadata = {
            "reqId": authority.request_id, "snapshotId": authority.capture_key,
            "captureSequence": authority.capture_sequence, "captureGeneration": authority.generation,
            "helperServiceInstanceId": authority.service_instance_id,
            "captureAuthority": authority.to_dict(),
        }
        def get_traversal_candidate_snapshot(self, *, dev):
            assert dev == "SERIAL"
            return snapshot

    tab = {"scenario_id": "life_air_care_plugin", "entry_type": "card", "screen_context_mode": "new_screen"}
    readiness = _ready(contract_id="life_service_card_read_only_navigation")
    owner, reason = collection_flow._resolve_navigation_owner_from_helper_snapshot(
        Client(), "SERIAL", tab, "life_air_care_plugin", "life_service_card_read_only_navigation", readiness)
    assert reason == "NAVIGATION_TARGET_RESOLVED"
    assert owner is not None
    assert owner["className"] == "android.widget.RelativeLayout"
    assert owner["sourceNodeId"] is None
    assert owner["_helperOwnerSourceNodeId"] == ""
    assert owner["_helperOwnerSourceNodeIdStatus"] == "FIELD_ABSENT"
    assert collection_flow._navigation_action_owner_has_current_identity(owner)
    assert collection_flow._navigation_owner_capture_authority_matches(owner, readiness)
    assert owner["_helperNodePath"] == [0]

    duplicate = _navigation_helper_snapshot(targets=[_aircare_parent_candidate(), _aircare_parent_candidate()],
                                            request_id="aircare-status-duplicate", sequence=11, generation=11)
    duplicate_authority = duplicate.decoded.capture_authority
    Client.last_hierarchy_metadata = {
        "reqId": duplicate_authority.request_id, "snapshotId": duplicate_authority.capture_key,
        "captureSequence": duplicate_authority.capture_sequence, "captureGeneration": duplicate_authority.generation,
        "helperServiceInstanceId": duplicate_authority.service_instance_id,
        "captureAuthority": duplicate_authority.to_dict(),
    }
    Client.get_traversal_candidate_snapshot = lambda self, *, dev: duplicate
    duplicate_owner, duplicate_reason = collection_flow._resolve_navigation_owner_from_helper_snapshot(
        Client(), "SERIAL", tab, "life_air_care_plugin", "life_service_card_read_only_navigation", readiness)
    assert duplicate_owner is None and duplicate_reason == "NAVIGATION_TARGET_AMBIGUOUS"

    unknown = _navigation_helper_snapshot(targets=[_aircare_parent_candidate(status="좋음")],
                                          request_id="aircare-status-unknown", sequence=12, generation=12)
    unknown_authority = unknown.decoded.capture_authority
    Client.last_hierarchy_metadata = {
        "reqId": unknown_authority.request_id, "snapshotId": unknown_authority.capture_key,
        "captureSequence": unknown_authority.capture_sequence, "captureGeneration": unknown_authority.generation,
        "helperServiceInstanceId": unknown_authority.service_instance_id,
        "captureAuthority": unknown_authority.to_dict(),
    }
    Client.get_traversal_candidate_snapshot = lambda self, *, dev: unknown
    unknown_owner, unknown_reason = collection_flow._resolve_navigation_owner_from_helper_snapshot(
        Client(), "SERIAL", tab, "life_air_care_plugin", "life_service_card_read_only_navigation", readiness)
    assert unknown_owner is None and unknown_reason == "NAVIGATION_TARGET_NOT_FOUND"

    missing_field = deepcopy(_aircare_parent_candidate())
    missing_field.pop("sourceNodeId")
    missing = _navigation_helper_snapshot(targets=[missing_field],
                                          request_id="aircare-source-id-missing", sequence=13, generation=13)
    missing_authority = missing.decoded.capture_authority
    Client.last_hierarchy_metadata = {
        "reqId": missing_authority.request_id, "snapshotId": missing_authority.capture_key,
        "captureSequence": missing_authority.capture_sequence, "captureGeneration": missing_authority.generation,
        "helperServiceInstanceId": missing_authority.service_instance_id,
        "captureAuthority": missing_authority.to_dict(),
    }
    Client.get_traversal_candidate_snapshot = lambda self, *, dev: missing
    missing_owner, missing_reason = collection_flow._resolve_navigation_owner_from_helper_snapshot(
        Client(), "SERIAL", tab, "life_air_care_plugin", "life_service_card_read_only_navigation", readiness)
    assert missing_owner is None and missing_reason == "NAVIGATION_TARGET_SOURCE_IDENTITY_UNAVAILABLE"


def _navigation_capture_for(owner, scenario_id, transaction_id):
    authority = owner["_helperCaptureAuthority"]
    lease_request_id = "capture-request-1"
    response_request_id = f"{lease_request_id}_begin_fixture"
    return {
        "req_id": lease_request_id,
        "transaction_id": transaction_id,
        "armed": {
            "ok": True,
            "reqId": response_request_id,
            "responseReqId": response_request_id,
            "captureReqId": lease_request_id,
            "scenarioId": scenario_id,
            "requestedTransactionId": transaction_id,
            "transactionId": transaction_id,
            "ownerPath": owner["_helperNodePath"],
            "ownerDescriptorDigest": owner["_helperNodeDescriptorDigest"],
            "sourceSnapshotId": owner["_helperSourceSnapshotId"],
            "ownerWindowId": owner["windowId"],
            "ownerPackageName": owner["packageName"],
            "sourceCaptureRequestId": authority["request_id"],
            "sourceProcessEpoch": authority["process_epoch"],
            "sourceGeneration": authority["generation"],
            "sourceServiceInstanceId": authority["service_instance_id"],
            "sourceCaptureSequence": authority["capture_sequence"],
            "sourceRootDigest": authority["root_digest"],
            "sourceCandidateDigest": authority["candidate_digest"],
            "sourceCaptureKey": authority["capture_key"],
            "sourceConnectionEpoch": owner["_helperConnectionEpoch"],
            "sourceBootEpoch": owner["_helperBootEpoch"],
            "ownerSourceNodeId": owner["_helperOwnerSourceNodeId"],
            "ownerSourceNodeIdStatus": owner["_helperOwnerSourceNodeIdStatus"],
            "connectionId": "fixture-service-instance",
            "ownerLeaseId": "owner-lease-1",
            "captureId": "capture-1",
            "runId": "run-1",
            "invocationId": "invocation-1",
            "helperSnapshotId": "helper-snapshot-1",
            "baselineHierarchyDigest": "d" * 64,
            "leaseDeadlineElapsedRealtimeMs": 123456,
        },
    }


def _current_navigation_lease(capture, transaction_id):
    armed = capture["armed"]
    current = deepcopy(armed)
    current.update({"ok": True, "reason": "TARGET_CURRENT", "transactionId": transaction_id})
    return {"ok": True, "result": current}


def _wire_navigation_client(monkeypatch, snapshot, *, dispatch_result=None):
    scenario_id = "life_air_care_plugin"
    contract_id = "life_plugin_navigate_up_to_landing"
    tab_cfg = {
        "scenario_id": scenario_id,
        "entry_type": "card",
        "screen_context_mode": "new_screen",
        "navigation_action_recovery": {"contract_id": contract_id, "target": "navigate up"},
    }
    readiness = _ready(contract_id=contract_id)
    calls = {"owners": [], "dispatch": [], "xml": [], "cleanup": [], "snapshots": 0}

    class Client:
        last_hierarchy_metadata = {}

        def get_traversal_candidate_snapshot(self, *, dev):
            assert dev == "SERIAL"
            calls["snapshots"] += 1
            return snapshot

        def navigation_action_contract_for_scenario(self, dev, scenario, *, contract_id=None):
            assert dev == "SERIAL" and scenario == scenario_id and contract_id == contract_id_expected
            return self.readiness

        def dispatch_navigation_action(self, dev, **kwargs):
            calls["dispatch"].append(kwargs)
            return dispatch_result or {"success": True, "status": "VERIFIED_NAVIGATION", "reqId": "nav-req"}

    contract_id_expected = contract_id
    client = Client()
    authority = snapshot.decoded.capture_authority
    client.readiness = readiness
    client.last_hierarchy_metadata = {
        "reqId": authority.request_id,
        "snapshotId": authority.capture_key,
        "captureSequence": authority.capture_sequence,
        "captureGeneration": authority.generation,
        "helperServiceInstanceId": authority.service_instance_id,
        "captureAuthority": authority.to_dict(),
    }

    def begin(_client, _dev, *, transaction_id, target_node, scenario_id, **_kwargs):
        calls["owners"].append(target_node)
        return _navigation_capture_for(target_node, scenario_id, transaction_id)

    def validate(_client, _dev, *, capture_session, transaction_id, **_kwargs):
        return _current_navigation_lease(capture_session, transaction_id)

    def end(_client, _dev, *, capture_session, transaction_id, **_kwargs):
        calls["cleanup"].append((capture_session["req_id"], transaction_id))
        return {"ok": True}

    monkeypatch.setattr(entry_safety, "begin_transaction_click_capture", begin)
    monkeypatch.setattr(entry_safety, "validate_transaction_click_capture", validate)
    monkeypatch.setattr(entry_safety, "end_transaction_click_capture", end)
    return client, tab_cfg, calls, contract_id


def test_configured_navigation_uses_unique_current_helper_owner_before_xml_and_exact_dispatch(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())

    def xml_forbidden(*_args, **_kwargs):
        calls["xml"].append(True)
        raise AssertionError("configured navigation must not require XML target selection")

    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", xml_forbidden)
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="(?i)^navigate up$", type_="a",
        max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )
    assert ok is True and reason == "VERIFIED_NAVIGATION"
    assert len(calls["owners"]) == 1
    owner = calls["owners"][0]
    assert owner["sourceNodeId"] == "10" and owner["windowId"] == 45534
    assert owner["_helperSourceSnapshotId"] == owner["_helperCaptureAuthority"]["capture_key"]
    assert owner["_helperCaptureRequestId"] == "hierarchy-request-1"
    assert owner["_helperCaptureAuthority"]["root_digest"]
    assert owner["_helperCaptureAuthority"]["candidate_digest"]
    assert owner["_helperConnectionEpoch"] == "fixture-connection-epoch"
    assert owner["_helperBootEpoch"] == "boot:7"
    assert owner["_helperOwnerSourceNodeId"] == "10"
    assert owner["_helperOwnerSourceNodeIdStatus"] == "FIELD_PRESENT"
    assert calls["snapshots"] == 1
    assert len(calls["dispatch"]) == 1
    assert calls["dispatch"][0]["current_lease"]["result"]["ownerPath"] == owner["_helperNodePath"]
    assert calls["xml"] == [] and len(calls["cleanup"]) == 1


def test_configured_navigation_registers_nested_evidence_transaction_and_restores_parent(monkeypatch, tmp_path):
    from tb_runner.evidence import EvidenceRuntime

    client, tab_cfg, _calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    runtime = EvidenceRuntime(output_path=tmp_path / "navigation.xlsx", run_id="run-nav-ledger")
    runtime.start_scenario("life_air_care_plugin", "life")
    parent = runtime.begin_transaction("SCENARIO_STEP", phase="pre_navigation")
    client.evidence_runtime = runtime
    client._evidence_active_transaction = parent
    client._evidence_active_request_id = "parent-request"
    observed = {}
    original_begin = entry_safety.begin_transaction_click_capture

    def checked_begin(_client, _dev, *, transaction_id, **kwargs):
        registered = runtime.transaction(transaction_id)
        assert registered is not None
        assert registered["action_type"] == "NAVIGATION_ACTION"
        assert registered["parent_transaction_id"] == parent["transaction_id"]
        assert registered["state"] == "open"
        observed["transaction_id"] = transaction_id
        return original_begin(_client, _dev, transaction_id=transaction_id, **kwargs)

    monkeypatch.setattr(entry_safety, "begin_transaction_click_capture", checked_begin)

    def correlated_dispatch(_dev, **kwargs):
        transaction_id = kwargs["transaction_id"]
        assert runtime.transaction(transaction_id) is not None
        observed["dispatch_transaction_id"] = transaction_id
        return {"success": True, "status": "VERIFIED_NAVIGATION", "reqId": "nav-request"}

    client.dispatch_navigation_action = correlated_dispatch
    ok, reason = collection_flow._run_helper_snapshot_navigation_action(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id)

    assert ok is True and reason == "VERIFIED_NAVIGATION"
    assert observed["dispatch_transaction_id"] == observed["transaction_id"]
    closed = runtime.transaction(observed["transaction_id"])
    assert closed is not None and closed["state"] == "closed"
    assert closed["parent_transaction_id"] == parent["transaction_id"]
    assert [event.event_type for event in runtime.events_for_transaction(observed["transaction_id"])] == [
        "TRANSACTION_OPENED", "TRANSACTION_CLOSED"]
    assert client._evidence_active_transaction == parent
    assert client._evidence_active_request_id == "parent-request"


def test_post_dispatch_observer_timing_and_full_record_are_durable_after_bridge_return(monkeypatch, tmp_path):
    import json
    import time

    from tb_runner.evidence import EvidenceRuntime

    client, tab_cfg, _calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    runtime = EvidenceRuntime(output_path=tmp_path / "navigation-observer.xlsx", run_id="run-observer-ledger")
    runtime.start_scenario("life_air_care_plugin", "life")
    client.evidence_runtime = runtime
    call_order = []
    log_lines = []
    dispatch_result = {
        "success": False,
        "status": "rejected",
        "reason": "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
        "reqId": "nav-request-observer",
        "receipt_status": "REJECTED",
        "post_state_mismatch_fields": ["accessibility_focus_missing"],
        "receipt": {
            "activation_diagnostics": {
                "activation_mode": "EXACT_OWNER_FOCUS_THEN_CLICK",
                "focus_event_status": "FOCUSED_HIERARCHY_REVALIDATION_FAILED",
                "focus_revalidation": {
                    "prepared_deadline_valid": True,
                    "service_identity_matches": True,
                    "connection_identity_matches": True,
                    "window_identity_matches": True,
                    "focus_event_owner_matches": True,
                    "aggregate_accepted": False,
                    "target_currentness": {
                        "diagnostics_available": True,
                        "capture_lease_fresh": True,
                        "retained_node_accessibility_focused": True,
                        "focus_neutral_descriptor_matches": True,
                        "focus_neutral_hierarchy_digest_matches": False,
                        "capture_complete": True,
                        "capture_lease_age_ms": 104,
                        "first_failed_check": "focus_neutral_hierarchy_digest_matches",
                        "expected_focus_neutral_hierarchy_digest": "a" * 64,
                        "current_focus_neutral_hierarchy_digest": "b" * 64,
                        "focus_neutral_descriptor_mismatch_fields": [
                            "boundsInScreen", "private_node_text",
                        ],
                        "private_node_text": "must not be persisted",
                    },
                    "private_node_text": "must not be persisted",
                },
            },
        },
    }
    dispatch_times = {}

    def fake_dispatch(_dev, **_kwargs):
        call_order.append("bridge_enter")
        dispatch_times["returned_ns"] = time.monotonic_ns()
        dispatch_times["transaction_id"] = _kwargs["transaction_id"]
        call_order.append("bridge_return")
        return dispatch_result

    client.dispatch_navigation_action = fake_dispatch

    def fake_observer(_client, _dev, *, request_id, transaction_id, navigation_action_result,
                      action_context, action_result_received_monotonic_ns):
        assert call_order[-1] == "bridge_return"
        call_order.append("observer_start")
        assert request_id == dispatch_result["reqId"]
        assert transaction_id == action_context["transaction_id"]
        assert action_result_received_monotonic_ns >= dispatch_times["returned_ns"]
        assert action_context["connection_id"] == "fixture-service-instance"
        assert action_context["window_id"] == 45534
        assert action_context["source_capture_key"]
        assert action_context["source_generation"] is not None
        assert action_context["source_capture_sequence"] is not None
        assert navigation_action_result is dispatch_result
        record = {
            "evidence_role": "SECONDARY_ONLY",
            "action_request_id": request_id,
            "transaction_id": transaction_id,
            "action_result_received_monotonic_ns": action_result_received_monotonic_ns,
            "started_monotonic_ns": action_result_received_monotonic_ns + 1,
            "completed_monotonic_ns": action_result_received_monotonic_ns + 2,
            "observer_delay_from_result_ns": 1,
            "action_context": dict(action_context),
            "strict_navigation_result": collection_flow._navigation_action_evidence_projection(
                navigation_action_result),
            "observer_status": "PARTIAL",
            "observer_error_stages": ["sealed_helper_hierarchy"],
            "bounded_test_record": "x" * 6000,
        }
        call_order.append("observer_complete")
        return record

    monkeypatch.setattr(collection_flow, "_capture_navigation_independent_observations", fake_observer)
    monkeypatch.setattr(collection_flow, "log", lambda line: log_lines.append(line))

    ok, reason = collection_flow._run_helper_snapshot_navigation_action(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id)

    assert ok is False and reason == "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE"
    assert call_order == ["bridge_enter", "bridge_return", "observer_start", "observer_complete"]
    observer_line = next(line for line in log_lines if line.startswith(
        "[NAVIGATION_ACTION][independent_post_action_observations] "))
    logged_record = json.loads(observer_line.split(" ", 1)[1])
    assert len(logged_record["bounded_test_record"]) == 6000
    assert logged_record["evidence_role"] == "SECONDARY_ONLY"

    closed_event = next(event for event in runtime.events_for_transaction(dispatch_times["transaction_id"])
                        if event.event_type == "TRANSACTION_CLOSED")
    persisted = closed_event.payload["independent_post_action_observations"]
    assert persisted["normal_log_persistence"] == "RECORDED"
    assert len(persisted["bounded_test_record"]) == 6000
    assert persisted["strict_navigation_result"]["success"] is False
    focus_diagnostics = persisted["strict_navigation_result"]["activation_diagnostics"]
    assert focus_diagnostics["activation_mode"] == "EXACT_OWNER_FOCUS_THEN_CLICK"
    assert focus_diagnostics["focus_event_status"] == "FOCUSED_HIERARCHY_REVALIDATION_FAILED"
    revalidation = focus_diagnostics["focus_revalidation"]
    assert revalidation["aggregate_accepted"] is False
    assert revalidation["target_currentness"]["first_failed_check"] == \
        "focus_neutral_hierarchy_digest_matches"
    assert revalidation["target_currentness"]["expected_focus_neutral_hierarchy_digest"] == "a" * 64
    assert revalidation["target_currentness"]["focus_neutral_descriptor_mismatch_fields"] == ["boundsInScreen"]
    assert "private_node_text" not in focus_diagnostics
    assert "private_node_text" not in revalidation["target_currentness"]
    assert persisted["action_request_id"] == "nav-request-observer"
    assert persisted["transaction_id"] == dispatch_times["transaction_id"]


def test_diagnostic_only_receipt_projection_preserves_child_provenance_without_credit():
    receipt = {
        "status": "DIAGNOSTIC_ONLY", "reason": "DIAGNOSTIC_ONLY_NO_NAVIGATION_CREDIT",
        "reqId": "diag-request", "transaction_id": "diag-tx", "activation_mode":
            "DIAGNOSTIC_AIRCARE_FRAME_LAYOUT_CHILD_CLICK",
        "service_instance_id": "service-a", "connection_id": "service-a", "window_id": 150,
        "capture_id": "capture-a", "diagnostic_only": True, "diagnostic_action_dispatched": True,
        "action_call_count": 1, "verified_navigation": False, "visit_authority": False,
        "c5_credit": False, "traversal_credit": False,
        "diagnostic_target": {"path": [0, 1, 4, 0], "class_name": "android.widget.FrameLayout",
                              "resource_id": "com.samsung.android.oneconnect:id/frameLayout",
                              "parent_path": [0, 1, 4], "window_id": 150},
        "diagnostic_click_event": {"event_type": 1, "request_id": "diag-request",
                                   "transaction_id": "diag-tx", "service_instance_id": "service-a",
                                   "connection_id": "service-a", "window_id": 150,
                                   "exact_target_match": True},
        "post_capture_sample_artifact": {"capture_id": "post-capture", "node_count": 57,
                                         "complete": True, "sha256": "a" * 64},
        "post_capture_sample_sha256": "a" * 64, "post_capture_completeness": "COMPLETE",
        "post_capture_node_count": 57, "post_capture_digest": "b" * 64,
        "post_state_diagnostics": {"required_destination_match": True,
                                   "required_anchor_match_count": 0, "accessibility_focused": True,
                                   "capture_polling": {
                                       "schema": "navigation-post-capture-poll-v1",
                                       "request_id": "diag-request", "transaction_id": "diag-tx",
                                       "service_instance_id": "service-a", "connection_id": "service-a",
                                       "action_window_id": 150, "attempt_count": 2,
                                       "complete_sample_count": 0,
                                       "first_attempt_elapsed_realtime_ms": 1100,
                                       "last_attempt_elapsed_realtime_ms": 1150,
                                       "observed_type1_window_states": [
                                           {"window_id": 150, "last_active": False,
                                            "active_observation_count": 0, "inactive_observation_count": 2},
                                           {"window_id": 151, "last_active": True,
                                            "active_observation_count": 2, "inactive_observation_count": 0},
                                       ],
                                       "observed_active_type1_window_ids": [151],
                                       "skip_reason_counts": {"ACTION_WINDOW_NOT_ACTIVE_TYPE1": 2},
                                       "service_changed": True, "deadline_reached": False,
                                       "termination_stage": "SERVICE_CHANGED_DURING_POLL",
                                       "root_package_name": None, "root_class_name": None,
                                       "private_node_text": "must not persist",
                                   }},
        "private_node_text": "must not persist",
    }
    projected = collection_flow._navigation_action_evidence_projection({
        "success": False, "status": "diagnostic_only", "reqId": "diag-request", "receipt": receipt,
    })
    kept = projected["receipt"]
    assert kept["diagnostic_target"]["path"] == [0, 1, 4, 0]
    assert kept["diagnostic_click_event"]["exact_target_match"] is True
    assert kept["post_capture_sample_artifact"]["sha256"] == "a" * 64
    assert kept["post_state_diagnostics"]["required_anchor_match_count"] == 0
    polling = kept["post_state_diagnostics"]["capture_polling"]
    assert polling["action_window_id"] == 150
    assert polling["attempt_count"] == 2 and polling["complete_sample_count"] == 0
    assert polling["observed_active_type1_window_ids"] == [151]
    assert polling["skip_reason_counts"] == {"ACTION_WINDOW_NOT_ACTIVE_TYPE1": 2}
    assert polling["service_changed"] is True
    assert polling["termination_stage"] == "SERVICE_CHANGED_DURING_POLL"
    assert "private_node_text" not in polling
    assert projected["diagnostic_only"] is True and projected["navigation_credit"] is False
    assert kept["verified_navigation"] is False and kept["visit_authority"] is False
    assert kept["c5_credit"] is False and kept["traversal_credit"] is False
    assert "private_node_text" not in kept


def test_owner_dispatch_mark_projection_drops_raw_text_and_foreign_types():
    receipt = {
        "status": "REJECTED",
        "owner_dispatch_mark_reason": {"label": "private UI text"},
        "owner_dispatch_mark_ok": 0,
        "owner_dispatch_mark_lease_match": "true",
        "owner_dispatch_mark_target_match": None,
        "owner_dispatch_mark_eligible_exact_click_count": True,
        "owner_dispatch_mark_private_text": "private UI text",
        "owner_receipt_ok": 0,
        "owner_receipt_event_match": "false",
        "owner_receipt_click_event_elapsed_realtime_ms": True,
        "owner_click_event_elapsed_realtime_ms": 10_000_000_000_001,
        "activation_diagnostics": {"focus_revalidation": {
            "focus_event_owner_matches": "true",
            "target_currentness": {
                "aggregate_accepted": "false",
                "first_failed_check": "private UI text",
                "private_label": "private UI text",
            },
        }},
    }
    projected = collection_flow._navigation_action_evidence_projection({
        "success": False, "status": "rejected", "reason": "NAVIGATION_ACTION_RECEIPT_UNVERIFIED",
        "receipt": receipt,
        "receipt_owner_receipt_reason": {"label": "private UI text"},
        "receipt_owner_click_count": True,
    })
    for key in ("owner_dispatch_mark_reason", "owner_dispatch_mark_ok",
                "owner_dispatch_mark_lease_match", "owner_dispatch_mark_target_match",
                "owner_dispatch_mark_eligible_exact_click_count", "receipt_owner_receipt_reason",
                "receipt_owner_click_count", "receipt_owner_ok", "receipt_owner_event_match",
                "receipt_owner_click_event_elapsed_realtime_ms", "owner_click_event_elapsed_realtime_ms",
                "activation_diagnostics"):
        assert key not in projected
    assert "private UI text" not in repr(projected)

    receipt["owner_dispatch_mark_reason"] = "PRIVATE UI TEXT"
    receipt["owner_dispatch_mark_ok"] = False
    receipt["owner_dispatch_mark_lease_match"] = True
    receipt["owner_dispatch_mark_target_match"] = False
    receipt["owner_dispatch_mark_eligible_exact_click_count"] = 10_001
    receipt.update({
        "owner_receipt_ok": True,
        "owner_receipt_lease_match": True,
        "owner_receipt_target_match": True,
        "owner_receipt_event_match": False,
        "owner_receipt_click_event_present": True,
        "owner_receipt_eligible_exact_click_count": 1,
        "owner_receipt_click_event_elapsed_realtime_ms": 723_775_740,
        "owner_click_event_elapsed_realtime_ms": 723_775_760,
    })
    bounded = collection_flow._navigation_action_evidence_projection({
        "success": False, "status": "rejected", "receipt": receipt,
        "receipt_owner_receipt_reason": "PRIVATE UI TEXT",
        "receipt_owner_click_count": 10_001,
    })
    assert bounded["owner_dispatch_mark_ok"] is False
    assert bounded["owner_dispatch_mark_lease_match"] is True
    assert bounded["owner_dispatch_mark_target_match"] is False
    assert bounded["receipt_owner_ok"] is True
    assert bounded["receipt_owner_lease_match"] is True
    assert bounded["receipt_owner_target_match"] is True
    assert bounded["receipt_owner_event_match"] is False
    assert bounded["receipt_owner_click_event_present"] is True
    assert bounded["receipt_owner_eligible_exact_click_count"] == 1
    assert bounded["receipt_owner_click_event_elapsed_realtime_ms"] == 723_775_740
    assert bounded["owner_click_event_elapsed_realtime_ms"] == 723_775_760
    assert "owner_dispatch_mark_reason" not in bounded
    assert "owner_dispatch_mark_eligible_exact_click_count" not in bounded
    assert "receipt_owner_receipt_reason" not in bounded
    assert "receipt_owner_click_count" not in bounded


def test_click_source_diagnostics_are_bound_and_drop_raw_text_or_wrong_types():
    diagnostics = {
        "schema": "navigation-click-source-v1", "request_id": "click-req", "transaction_id": "click-tx",
        "service_instance_id": "service-1", "connection_id": "connection-1",
        "event_type": 1, "event_window_id": 2051, "event_elapsed_realtime_ms": 1234,
        "callback_elapsed_realtime_ms": 1200, "dispatch_elapsed_realtime_ms": 1000,
        "dispatch_deadline_elapsed_realtime_ms": 6000, "callback_source_status": "FIELD_ABSENT",
        "callback_source_window_id": None, "callback_source_window_status": "FIELD_ABSENT",
        "callback_source_node_id_status": "FIELD_ABSENT",
        "callback_source_resource_id_status": "FIELD_ABSENT",
        "callback_source_class_name_status": "FIELD_ABSENT", "callback_source_owner_exact": False,
        "first_click_selected": True, "strict_source_status": "FIELD_ABSENT",
        "strict_source_owner_exact": False, "first_failure_check": "CALLBACK_SOURCE_ABSENT",
        "request_binding_match": True, "transaction_binding_match": True, "service_binding_match": True,
        "connection_binding_match": True, "action_window_match": True, "dispatch_window_match": True,
        "private_node_text": "must not persist",
    }
    result = {"success": False, "status": "rejected", "request_id": "click-req",
              "transaction_id": "click-tx", "receipt": {"status": "REJECTED",
              "request_id": "click-req", "transaction_id": "click-tx",
              "failure_code": "NAVIGATION_EVENT_SOURCE_MISMATCH",
              "click_event_source_diagnostics": diagnostics}}
    projected = collection_flow._navigation_action_evidence_projection(result)
    kept = projected["click_event_source_diagnostics"]
    assert kept["callback_source_status"] == "FIELD_ABSENT"
    assert kept["first_failure_check"] == "CALLBACK_SOURCE_ABSENT"
    assert kept["request_id"] == "click-req" and kept["transaction_id"] == "click-tx"
    assert "private_node_text" not in kept and "private_node_text" not in repr(projected)

    foreign = dict(diagnostics, request_id="foreign-request")
    wrong_types = dict(diagnostics, callback_source_owner_exact="false", event_elapsed_realtime_ms=True)
    for malformed in (foreign, wrong_types):
        malformed_result = {**result, "receipt": {**result["receipt"],
                            "click_event_source_diagnostics": malformed}}
        bounded = collection_flow._navigation_action_evidence_projection(malformed_result)
        assert "click_event_source_diagnostics" not in bounded


def test_strict_post_failure_projection_keeps_only_hash_bound_redacted_sample():
    import hashlib

    payload = {
        "schema": "strict-post-capture-redacted-v1", "request_id": "strict-request",
        "transaction_id": "strict-tx", "service_instance_id": "service-a", "connection_id": "connection-a",
        "window_id": 1922, "capture_id": "post-capture", "captured_at_elapsed_realtime_ms": 1400,
        "hierarchy_digest": "b" * 64, "node_count": 1, "persisted_node_count": 1,
        "completeness": "COMPLETE", "omitted_fields": ["text", "contentDescription", "action_labels", "sourceNodeId"],
        "diagnostic_only": True, "effect_contract_id": "reviewed-contract",
        "required_anchor_structural_match_count": 1,
        "nodes": [{
            "id": 0, "parent_id": None, "child_index": None, "path": [0, 1],
            "class_name": "android.widget.Button", "package_name": "com.example.app", "resource_id": "ack",
            "window_id": 1922, "bounds": [0, 0, 20, 20], "text_present": False,
            "content_description_present": True, "resource_id_present": True, "clickable": True,
            "enabled": True, "focusable": True, "focused": True, "accessibility_focused": True,
            "selected": False, "scrollable": False, "visible_to_user": True, "action_ids": [16],
            "action_count": 1, "action_ids_complete": True, "destination_label_match": False,
            "required_anchor_match_count": 1,
            "diagnostic_policy_match_ids": [
                "required_anchor_label", "required_anchor_structural_match", "empty_state_anchor_candidate",
            ],
            "diagnostic_policy_matches": [{
                "contract_id": "reviewed-source", "contract_digest": "c" * 64,
                "match_ids": ["empty_state_anchor_candidate"], "anchor_semantic_status": "UNKNOWN",
            }],
            "diagnostic_anchor_semantic_status": "UNKNOWN",
        }],
    }

    def wrap(sample_payload):
        canonical = json.dumps(sample_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        encoded = canonical.encode("utf-8")
        return {
            "result_channel": "NAVIGATION_ACTION_RESULT", "request_id": "strict-request",
            "receipt_field": "receipt.post_state_diagnostics.post_capture_sample_artifact.payload",
            "artifact_sha256": hashlib.sha256(encoded).hexdigest(), "artifact_bytes": len(encoded),
            "completeness": "COMPLETE", "node_count": 1, "persisted_node_count": 1,
            "payload": sample_payload,
        }

    diagnostics = {
        "request_id": "strict-request", "transaction_id": "strict-tx",
        "post_request_id": "strict-request", "post_transaction_id": "strict-tx",
        "post_service_instance_id": "service-a", "post_connection_id": "connection-a",
        "post_window_id": 1922, "post_capture_id": "post-capture", "post_hierarchy_digest": "b" * 64,
        "receipt_decision": "REJECTED", "required_destination_match": False,
        "post_capture_sample_artifact": wrap(payload), "private_node_text": "must not persist",
    }
    projected = collection_flow._navigation_action_evidence_projection({
        "success": False, "status": "rejected", "reqId": "strict-request",
        "post_state_diagnostics": diagnostics,
    })
    kept = projected["post_state_diagnostics"]
    artifact = kept["post_capture_sample_artifact"]
    kept_node = artifact["payload"]["nodes"][0]
    assert kept_node["diagnostic_policy_match_ids"] == [
        "required_anchor_label", "required_anchor_structural_match", "empty_state_anchor_candidate",
    ]
    assert artifact["payload"]["required_anchor_structural_match_count"] == 1
    assert kept["post_capture_sample_projection_status"] == "RETAINED"
    assert kept_node["diagnostic_anchor_semantic_status"] == "UNKNOWN"
    assert kept_node["diagnostic_policy_matches"] == [{
        "contract_id": "reviewed-source", "contract_digest": "c" * 64,
        "match_ids": ["empty_state_anchor_candidate"], "anchor_semantic_status": "UNKNOWN",
    }]
    assert kept_node["path"] == [0, 1] and kept_node["resource_id"] == "ack"
    assert kept_node["focused"] and kept_node["accessibility_focused"] and kept_node["action_ids"] == [16]
    assert artifact["artifact_sha256"] == hashlib.sha256(json.dumps(
        artifact["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    assert "private_node_text" not in kept
    assert "navigation_credit" not in projected and "visit_authority" not in projected

    wrong_binding = dict(diagnostics, post_capture_id="different-capture")
    wrong_binding_projection = collection_flow._navigation_action_evidence_projection({
        "success": False, "status": "rejected", "post_state_diagnostics": wrong_binding,
    })
    assert "post_capture_sample_artifact" not in wrong_binding_projection["post_state_diagnostics"]
    assert wrong_binding_projection["post_state_diagnostics"]["post_capture_sample_projection_status"] == "REJECTED"

    malformed_payloads = []
    wrong_count = json.loads(json.dumps(payload))
    wrong_count["required_anchor_structural_match_count"] = 2
    malformed_payloads.append(wrong_count)
    boolean_count = json.loads(json.dumps(payload))
    boolean_count["required_anchor_structural_match_count"] = True
    malformed_payloads.append(boolean_count)
    missing_label = json.loads(json.dumps(payload))
    missing_label["nodes"][0]["diagnostic_policy_match_ids"].remove("required_anchor_label")
    malformed_payloads.append(missing_label)
    duplicate_marker = json.loads(json.dumps(payload))
    duplicate_marker["nodes"][0]["diagnostic_policy_match_ids"].append("required_anchor_structural_match")
    malformed_payloads.append(duplicate_marker)
    for malformed in malformed_payloads:
        rejected = collection_flow._navigation_action_evidence_projection({
            "success": False, "status": "rejected",
            "post_state_diagnostics": dict(diagnostics, post_capture_sample_artifact=wrap(malformed)),
        })
        rejected_post = rejected["post_state_diagnostics"]
        assert "post_capture_sample_artifact" not in rejected_post
        assert rejected_post["post_capture_sample_projection_status"] == "REJECTED"

    wrong_post_window = dict(diagnostics, post_window_authority={
        "post_window_id": 1999, "root_window_id": 1999, "active_type1_window_ids": [1999],
    })
    rejected_window = collection_flow._navigation_action_evidence_projection({
        "success": False, "status": "rejected",
        "post_state_diagnostics": wrong_post_window,
    })
    assert "post_capture_sample_artifact" not in rejected_window["post_state_diagnostics"]
    assert rejected_window["post_state_diagnostics"]["post_capture_sample_projection_status"] == "REJECTED"

    injected_payload = json.loads(json.dumps(payload))
    injected_payload["nodes"][0]["text"] = "private UI text"
    injected = dict(diagnostics, post_capture_sample_artifact=wrap(injected_payload))
    injected_projection = collection_flow._navigation_action_evidence_projection({
        "success": False, "status": "rejected", "post_state_diagnostics": injected,
    })
    assert "post_capture_sample_artifact" not in injected_projection["post_state_diagnostics"]

    injected_policy_label = json.loads(json.dumps(payload))
    injected_policy_label["nodes"][0]["diagnostic_policy_matches"][0]["private_label"] = "private ack meaning"
    injected = dict(diagnostics, post_capture_sample_artifact=wrap(injected_policy_label))
    rejected_policy_label = collection_flow._navigation_action_evidence_projection({
        "success": False, "status": "rejected", "post_state_diagnostics": injected,
    })
    assert "post_capture_sample_artifact" not in rejected_policy_label["post_state_diagnostics"]


def test_strict_projection_preserves_bounded_destination_anchor_focus_first_failure():
    result = collection_flow._navigation_action_evidence_projection({
        "success": False,
        "status": "rejected",
        "post_state_diagnostics": {
            "destination_anchor_focus": {
                "status": "FOCUS_NOT_DISPATCHED",
                "failure_stage": "destination_anchor_focus_target_unproven",
                "resolver_failure_code": "NAVIGATION_DESTINATION_ANCHOR_NOT_UNIQUE",
                "window_id": 1820,
                "focus_action_count": 0,
                "focus_action_acknowledged": False,
                "currentness_revalidation": {
                    "diagnostics_available": True,
                    "aggregate_accepted": False,
                    "first_failed_check": "retained_node_accessibility_focused",
                    "private_label": "must not persist",
                },
                "private_text": "must not persist",
            },
        },
    })
    focus = result["post_state_diagnostics"]["destination_anchor_focus"]
    assert focus["status"] == "FOCUS_NOT_DISPATCHED"
    assert focus["failure_stage"] == "destination_anchor_focus_target_unproven"
    assert focus["resolver_failure_code"] == "NAVIGATION_DESTINATION_ANCHOR_NOT_UNIQUE"
    assert focus["window_id"] == 1820 and focus["focus_action_count"] == 0
    assert focus["currentness_revalidation"]["first_failed_check"] == "retained_node_accessibility_focused"
    assert "private_text" not in focus and "private_label" not in focus["currentness_revalidation"]

    malformed = collection_flow._navigation_action_evidence_projection({
        "success": False,
        "status": "rejected",
        "post_state_diagnostics": {
            "destination_anchor_focus": {
                "status": "private UI text",
                "failure_stage": "private UI text",
                "resolver_failure_code": "private UI text",
                "window_id": "1820",
                "focus_action_count": True,
                "currentness_revalidation": {
                    "aggregate_accepted": 1,
                    "first_failed_check": "private UI text",
                },
            },
        },
    })
    assert "destination_anchor_focus" not in malformed["post_state_diagnostics"]


def test_post_dispatch_observer_exception_is_secondary_to_strict_rejection(monkeypatch, tmp_path):
    from tb_runner.evidence import EvidenceRuntime

    client, tab_cfg, _calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    runtime = EvidenceRuntime(output_path=tmp_path / "navigation-observer-error.xlsx", run_id="run-observer-error")
    runtime.start_scenario("life_air_care_plugin", "life")
    client.evidence_runtime = runtime
    strict_result = {
        "success": False,
        "status": "rejected",
        "reason": "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE",
        "reqId": "nav-request-error",
    }
    dispatched = {}

    def fake_dispatch(_dev, **kwargs):
        dispatched["transaction_id"] = kwargs["transaction_id"]
        return strict_result

    client.dispatch_navigation_action = fake_dispatch

    def raising_observer(*_args, **_kwargs):
        raise TimeoutError("observer timeout")

    monkeypatch.setattr(collection_flow, "_capture_navigation_independent_observations", raising_observer)
    monkeypatch.setattr(collection_flow, "log", lambda _line: None)

    ok, reason = collection_flow._run_helper_snapshot_navigation_action(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id)

    assert ok is False
    assert reason == "NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE"
    persisted = next(event for event in runtime.events_for_transaction(dispatched["transaction_id"])
                     if event.event_type == "TRANSACTION_CLOSED").payload[
                         "independent_post_action_observations"]
    assert persisted["evidence_role"] == "SECONDARY_ONLY"
    assert persisted["observer_status"] == "FAILED"
    assert persisted["observer_error_stages"] == ["collector"]
    assert persisted["strict_navigation_result"]["reason"] == strict_result["reason"]
    assert client.last_navigation_independent_post_action_observations == persisted


def test_configured_navigation_search_reacquires_fresh_sealed_owner_after_each_scroll(monkeypatch):
    unrelated = deepcopy(_navigation_helper_snapshot().raw_hierarchy["windows"][0]["root"]["children"][0])
    unrelated["text"] = "Unrelated card"
    snapshots = [
        _navigation_helper_snapshot(targets=[unrelated], request_id="hierarchy-missing", sequence=8, generation=8),
        _navigation_helper_snapshot(request_id="hierarchy-owner", sequence=9, generation=9),
    ]
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, snapshots[0])
    captured = []
    scrolls = []

    def fresh_snapshot(*, dev):
        assert dev == "SERIAL"
        snapshot = snapshots.pop(0)
        authority = snapshot.decoded.capture_authority
        client.last_hierarchy_metadata = {
            "reqId": authority.request_id,
            "snapshotId": authority.capture_key,
            "captureSequence": authority.capture_sequence,
            "captureGeneration": authority.generation,
            "helperServiceInstanceId": authority.service_instance_id,
            "captureAuthority": authority.to_dict(),
        }
        captured.append(authority.capture_key)
        return snapshot

    client.get_traversal_candidate_snapshot = fresh_snapshot
    container = _navigation_scroll_container(capture_id="scroll-source", request_id="scroll-source-request")
    monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot",
                        lambda *_args, **_kwargs: (container, "NAVIGATION_SCROLL_CONTAINER_RESOLVED"))

    def confirmed_scroll(**kwargs):
        scrolls.append(kwargs)
        client.last_scroll_request_id = "scroll-request-1"
        client.last_scroll_result = {
            "reqId": "scroll-request-1", "success": True, "explicitTarget": True,
            "scrollContainerPath": "0.1", "scrollableNodeFound": True,
            "actionSupported": True, "actionAttempted": True,
        }
        return True

    client.scroll = confirmed_scroll
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no XML fallback")))

    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="navigate up", type_="a",
        max_scroll_search_steps=2, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )

    assert ok is True and reason == "VERIFIED_NAVIGATION"
    assert len(captured) == 2 and captured[0] != captured[1]
    assert scrolls == [{"dev": "SERIAL", "direction": "down", "container_path": "0.1",
                        "container_bounds": "0,0,1080,2640"}]
    assert len(calls["owners"]) == 1 and len(calls["dispatch"]) == 1
    assert calls["owners"][0]["_helperCaptureRequestId"] == "hierarchy-owner"
    assert calls["owners"][0]["_helperSourceSnapshotId"] == captured[1]
    assert calls["xml"] == []


def test_configured_navigation_search_stops_on_ambiguity_without_scroll_or_xml(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    owner_checks = []
    scrolls = []

    def ambiguous(*_args, **_kwargs):
        owner_checks.append(True)
        return False, "NAVIGATION_TARGET_AMBIGUOUS"

    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action", ambiguous)
    client.scroll = lambda **kwargs: scrolls.append(kwargs) or True
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no XML fallback")))

    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="target", type_="a",
        max_scroll_search_steps=4, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )

    assert ok is False and reason == "NAVIGATION_TARGET_AMBIGUOUS"
    assert owner_checks == [True] and scrolls == []
    assert calls["dispatch"] == [] and calls["xml"] == []


def test_configured_navigation_search_stops_on_missing_stable_source_identity(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    scrolls = []
    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action",
                        lambda *_args, **_kwargs: (False, "NAVIGATION_TARGET_STABLE_IDENTITY_UNAVAILABLE"))
    client.scroll = lambda **kwargs: scrolls.append(kwargs) or True

    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="target", type_="a",
        max_scroll_search_steps=4, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )

    assert ok is False and reason == "NAVIGATION_TARGET_STABLE_IDENTITY_UNAVAILABLE"
    assert scrolls == [] and calls["dispatch"] == [] and calls["xml"] == []


def test_configured_navigation_search_stops_when_helper_scroll_is_not_confirmed(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    owner_checks = []
    scrolls = []

    def missing(*_args, **_kwargs):
        owner_checks.append(True)
        return False, "NAVIGATION_TARGET_NOT_FOUND"

    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action", missing)
    containers = [
        _navigation_scroll_container(capture_id="scroll-pre", request_id="scroll-pre-request", generation=30),
        _navigation_scroll_container(capture_id="scroll-post", request_id="scroll-post-request", generation=31),
    ]
    container_reads = []
    monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot",
                        lambda *_args, **_kwargs: (container_reads.append(True) or containers.pop(0),
                                                   "NAVIGATION_SCROLL_CONTAINER_RESOLVED"))

    def scroll_false(**kwargs):
        scrolls.append(kwargs)
        client.last_scroll_request_id = "scroll-not-confirmed"
        client.last_scroll_result = {
            "reqId": "scroll-not-confirmed", "success": False, "explicitTarget": True,
            "scrollContainerPath": "0.1", "scrollableNodeFound": True,
            "actionSupported": True, "actionAttempted": True,
        }
        return False

    client.scroll = scroll_false
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no XML fallback")))

    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="target", type_="a",
        max_scroll_search_steps=4, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )

    assert ok is False and reason == "NAVIGATION_SCROLL_NOT_CONFIRMED"
    assert len(owner_checks) == 2 and len(container_reads) == 2 and len(scrolls) == 1
    assert scrolls[0]["container_path"] == "0.1"
    assert calls["dispatch"] == [] and calls["xml"] == []


def test_unconfirmed_navigation_scroll_logs_correlated_helper_result_without_credit(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    owner_checks = []
    logs = []
    scroll_result = {
        "reqId": "scroll-request-7",
        "success": False,
        "scrollableNodeFound": True,
        "actionSupported": True,
        "actionAttempted": True,
        "topBoundaryEvidence": False,
        "reason": "action_not_supported",
        "status": "REJECTED",
        "explicitTarget": True,
        "scrollContainerPath": "0.1",
    }

    def missing(*_args, **_kwargs):
        owner_checks.append(True)
        return False, "NAVIGATION_TARGET_NOT_FOUND"

    def unconfirmed_scroll(**kwargs):
        assert kwargs == {"dev": "SERIAL", "direction": "down", "container_path": "0.1",
                          "container_bounds": "0,0,1080,2640"}
        client.last_scroll_request_id = "scroll-request-7"
        client.last_scroll_result = scroll_result
        return False

    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action", missing)
    monkeypatch.setattr(collection_flow, "log", logs.append)
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no XML fallback")))
    client.scroll = unconfirmed_scroll
    containers = [
        _navigation_scroll_container(capture_id="scroll-pre", request_id="scroll-pre-request", generation=40),
        _navigation_scroll_container(capture_id="scroll-post", request_id="scroll-post-request", generation=41),
    ]
    container_reads = []
    monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot",
                        lambda *_args, **_kwargs: (container_reads.append(True) or containers.pop(0),
                                                   "NAVIGATION_SCROLL_CONTAINER_RESOLVED"))

    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="target", type_="a",
        max_scroll_search_steps=4, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )

    assert ok is False and reason == "NAVIGATION_SCROLL_NOT_CONFIRMED"
    assert len(owner_checks) == 2 and len(container_reads) == 2
    assert calls["dispatch"] == [] and calls["xml"] == []
    diagnostic = next(line.split("[search_scroll_result] ", 1)[1]
                      for line in logs if "[search_scroll_result] " in line)
    record = json.loads(diagnostic)
    assert record["scroll_request_id"] == "scroll-request-7"
    assert record["scroll_confirmed"] is False
    assert record["explicit_target"] is True
    assert record["reported_path"] == "0.1"
    assert record["post_capture"]["capture_id"] == "scroll-post"
    assert record["post_capture"]["request_id"] == "scroll-post-request"
    assert record["container"]["bounds"] == "0,0,1080,2640"


def test_configured_navigation_search_respects_scroll_bound_and_keeps_missing_fail_closed(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    owner_checks = []
    scrolls = []

    def missing(*_args, **_kwargs):
        owner_checks.append(True)
        return False, "NAVIGATION_TARGET_NOT_FOUND"

    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action", missing)
    containers = [_navigation_scroll_container(capture_id=f"scroll-{i}", request_id=f"scroll-request-{i}",
                                               generation=20 + i)
                  for i in range(3)]
    monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot",
                        lambda *_args, **_kwargs: (containers.pop(0), "NAVIGATION_SCROLL_CONTAINER_RESOLVED"))

    def scroll_confirmed(**kwargs):
        scrolls.append(kwargs)
        req_id = f"scroll-actual-{len(scrolls)}"
        client.last_scroll_request_id = req_id
        client.last_scroll_result = {
            "reqId": req_id, "success": True, "explicitTarget": True,
            "scrollContainerPath": kwargs["container_path"], "scrollableNodeFound": True,
            "actionSupported": True, "actionAttempted": True,
        }
        return True

    client.scroll = scroll_confirmed
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no XML fallback")))

    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="target", type_="a",
        max_scroll_search_steps=2, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )

    assert ok is False and reason == "NAVIGATION_SCROLL_BOUND_EXHAUSTED_BEFORE_END"
    assert len(owner_checks) == 3 and len(scrolls) == 2
    assert calls["dispatch"] == [] and calls["xml"] == []


def _navigation_scroll_container(*, capture_id="capture-1", request_id="request-1",
                                generation=1, backward=False, forward=True,
                                path="0.1", bounds="0,0,1080,2640", window_id=45534,
                                service_instance_id="fixture-service-instance",
                                process_epoch="fixture-process-epoch",
                                package_name="com.samsung.android.oneconnect",
                                class_name="android.widget.GridView",
                                resource_id="com.samsung.android.oneconnect:id/recycler_view",
                                source_node_id=""):
    return {
        "path": path,
        "bounds": bounds,
        "window_id": window_id,
        "package_name": package_name,
        "class_name": class_name,
        "resource_id": resource_id,
        "descriptor_digest": "d" * 64,
        "source_node_id": source_node_id,
        "source_capture_id": capture_id,
        "source_request_id": request_id,
        "service_instance_id": service_instance_id,
        "process_epoch": process_epoch,
        "connection_epoch": "fixture-connection-epoch",
        "boot_epoch": "fixture-boot-epoch",
        "generation": generation,
        "capture_sequence": generation,
        "root_digest": "a" * 64,
        "candidate_digest": "b" * 64,
        "visible_node_count": 5,
        "visible_node_digest": f"visible-{generation}",
        "action_ids": ([8192] if backward else []) + ([4096] if forward else []),
        "forward_supported": forward,
        "backward_supported": backward,
    }


def test_scroll_container_is_resolved_from_one_current_sealed_hierarchy_and_rejects_ambiguous_stale(monkeypatch):
    owner_node = _navigation_helper_snapshot().raw_hierarchy["windows"][0]["root"]["children"][0]
    scroll_node = {
        "text": "", "contentDescription": "",
        "viewIdResourceName": "com.samsung.android.oneconnect:id/recycler_view",
        "className": "android.widget.GridView",
        "packageName": "com.samsung.android.oneconnect", "sourceNodeId": None,
        "windowId": 45534, "boundsInScreen": {"left": 0, "top": 0, "right": 1080, "bottom": 2640},
        "scrollable": True, "enabled": True, "visibleToUser": True,
        "actions": [{"id": 8192, "name": "ACTION_SCROLL_BACKWARD"}], "children": [],
    }
    snapshot = _navigation_helper_snapshot(targets=[owner_node, scroll_node])
    client, tab_cfg, _calls, contract_id = _wire_navigation_client(monkeypatch, snapshot)
    container, reason = collection_flow._resolve_navigation_scroll_container_from_helper_snapshot(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id, client.readiness)
    assert reason == "NAVIGATION_SCROLL_CONTAINER_RESOLVED"
    assert container["path"] == "0.1"
    assert container["bounds"] == "0,0,1080,2640"
    assert container["window_id"] == 45534
    assert container["source_capture_id"] == snapshot.decoded.capture_authority.capture_key
    assert container["source_request_id"] == "hierarchy-request-1"
    assert container["backward_supported"] is True and container["forward_supported"] is False

    ambiguous = _navigation_helper_snapshot(targets=[owner_node, scroll_node, {**scroll_node,
        "viewIdResourceName": "com.samsung.android.oneconnect:id/other_list",
        "boundsInScreen": {"left": 0, "top": 0, "right": 1080, "bottom": 1000}}])
    client, tab_cfg, _calls, contract_id = _wire_navigation_client(monkeypatch, ambiguous)
    container, reason = collection_flow._resolve_navigation_scroll_container_from_helper_snapshot(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id, client.readiness)
    assert container is None and reason == "NAVIGATION_SCROLL_CONTAINER_AMBIGUOUS"

    stale = _navigation_helper_snapshot(targets=[owner_node, scroll_node], stale_identity=True)
    client, tab_cfg, _calls, contract_id = _wire_navigation_client(monkeypatch, stale)
    container, reason = collection_flow._resolve_navigation_scroll_container_from_helper_snapshot(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id, client.readiness)
    assert container is None and "AUTHORITY" in reason


def test_configured_navigation_scroll_binds_explicit_container_and_rechecks_target_after_false(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    containers = [_navigation_scroll_container(capture_id="before", request_id="before-request")]
    container_reads = []
    monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot",
                        lambda *_args, **_kwargs: (container_reads.append(True) or containers.pop(0),
                                                   "NAVIGATION_SCROLL_CONTAINER_RESOLVED"))
    owner_checks = []

    def owner_then_success(*_args, **_kwargs):
        owner_checks.append(True)
        return (False, "NAVIGATION_TARGET_NOT_FOUND") if len(owner_checks) == 1 else (True, "VERIFIED_NAVIGATION")

    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action", owner_then_success)
    scroll_calls = []

    def unconfirmed(**kwargs):
        scroll_calls.append(kwargs)
        client.last_scroll_request_id = "scroll-r1"
        client.last_scroll_result = {
            "reqId": "scroll-r1", "success": False, "explicitTarget": True,
            "scrollContainerPath": "0.1", "scrollableNodeFound": True,
            "actionSupported": True, "actionAttempted": True,
        }
        return False

    client.scroll = unconfirmed
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)
    ok, reason = collection_flow._run_helper_snapshot_navigation_search(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id,
        max_scroll_search_steps=2, step_wait_seconds=0,
    )
    assert ok is True and reason == "VERIFIED_NAVIGATION"
    assert scroll_calls == [{"dev": "SERIAL", "direction": "down", "container_path": "0.1",
                             "container_bounds": "0,0,1080,2640"}]
    assert len(owner_checks) == 2 and len(container_reads) == 1
    assert calls["xml"] == []


def test_navigation_scroll_uses_fresh_path_and_bounds_when_unique_container_relocates(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    containers = [
        _navigation_scroll_container(capture_id="before", request_id="before-request", generation=10,
                                     bounds="0,286,1080,2640"),
        _navigation_scroll_container(capture_id="after", request_id="after-request", generation=11,
                                     path="0.2", bounds="0,0,1080,2640"),
    ]
    monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot",
                        lambda *_args, **_kwargs: (containers.pop(0),
                                                   "NAVIGATION_SCROLL_CONTAINER_RESOLVED"))
    owner_checks = []

    def owner_results(*_args, **_kwargs):
        owner_checks.append(True)
        return (False, "NAVIGATION_TARGET_NOT_FOUND") if len(owner_checks) < 3 else (True, "VERIFIED_NAVIGATION")

    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action", owner_results)
    scroll_calls = []
    logs = []
    monkeypatch.setattr(collection_flow, "log", logs.append)

    def scroll_success(**kwargs):
        scroll_calls.append(kwargs)
        req_id = f"scroll-bounds-{len(scroll_calls)}"
        client.last_scroll_request_id = req_id
        client.last_scroll_result = {
            "reqId": req_id, "success": True, "explicitTarget": True,
            "scrollContainerPath": kwargs["container_path"], "scrollableNodeFound": True,
            "actionSupported": True, "actionAttempted": True,
        }
        return True

    client.scroll = scroll_success
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)
    ok, reason = collection_flow._run_helper_snapshot_navigation_search(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id,
        max_scroll_search_steps=2, step_wait_seconds=0,
    )
    assert ok is True and reason == "VERIFIED_NAVIGATION"
    assert [call["container_path"] for call in scroll_calls] == ["0.1", "0.2"]
    assert [call["container_bounds"] for call in scroll_calls] == [
        "0,286,1080,2640", "0,0,1080,2640"]
    assert len(owner_checks) == 3 and calls["xml"] == []
    diagnostic = next(json.loads(line.split("[search_scroll_result] ", 1)[1])
                      for line in logs if "[search_scroll_result] " in line)
    assert diagnostic["post_capture"]["transport_ledger_ref_request_id"] == "after-request"
    assert diagnostic["post_capture"]["container"]["path"] == "0.2"
    assert diagnostic["post_capture"]["container"]["bounds"] == "0,0,1080,2640"
    assert diagnostic["post_capture"]["container"]["action_ids"] == [4096]
    assert diagnostic["container_identity_changed"] is False
    assert diagnostic["identity_changed_reasons"] == []
    assert [change["field"] for change in diagnostic["changed_fields"]] == ["path", "bounds"]
    assert diagnostic["target_match_count"] == {"before_scroll": 0, "after_scroll": 0}
    assert diagnostic["visible_node_count_delta"] == 0
    assert diagnostic["post_capture"]["connection_epoch"] == "fixture-connection-epoch"
    assert diagnostic["post_capture"]["boot_epoch"] == "fixture-boot-epoch"


def test_false_scroll_requires_fresh_container_boundary_evidence_and_only_then_reports_full_end(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    containers = [
        _navigation_scroll_container(capture_id="before", request_id="before-request", generation=10),
        _navigation_scroll_container(capture_id="after", request_id="after-request", generation=11,
                                     backward=False, forward=False),
    ]
    container_reads = []

    def resolve_container(*_args, **_kwargs):
        container_reads.append(True)
        return containers.pop(0), "NAVIGATION_SCROLL_CONTAINER_RESOLVED"

    monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot", resolve_container)
    owner_checks = []
    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action",
                        lambda *_args, **_kwargs: owner_checks.append(True) or
                        (False, "NAVIGATION_TARGET_NOT_FOUND"))
    logs = []
    monkeypatch.setattr(collection_flow, "log", logs.append)

    def false_at_boundary(**kwargs):
        assert kwargs["container_path"] == "0.1"
        client.last_scroll_request_id = "scroll-r2"
        client.last_scroll_result = {
            "reqId": "scroll-r2", "success": False, "explicitTarget": True,
            "scrollContainerPath": "0.1", "scrollableNodeFound": True,
            "actionSupported": True, "actionAttempted": True,
        }
        return False

    client.scroll = false_at_boundary
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)
    ok, reason = collection_flow._run_helper_snapshot_navigation_search(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id,
        max_scroll_search_steps=2, step_wait_seconds=0,
    )
    assert ok is False and reason == "NAVIGATION_TARGET_NOT_FOUND"
    assert len(owner_checks) == 2 and len(container_reads) == 2
    diagnostic = next(json.loads(line.split("[search_scroll_result] ", 1)[1])
                      for line in logs if "[search_scroll_result] " in line)
    assert diagnostic["response_request_id"] == "scroll-r2"
    assert diagnostic["container"]["path"] == "0.1"
    assert diagnostic["post_capture"]["capture_id"] == "after"
    assert diagnostic["post_capture"]["generation"] == 11
    assert diagnostic["visible_projection_changed"] is True
    assert diagnostic["boundary_action_absent"] is True
    assert calls["dispatch"] == [] and calls["xml"] == []


def test_navigation_scroll_stops_when_current_container_path_or_capture_is_stale(monkeypatch):
    cases = (
        (_navigation_scroll_container(capture_id="before", request_id="before-request", generation=1,
                                      resource_id=""),
         _navigation_scroll_container(capture_id="after", request_id="after-path", generation=2,
                                      path="0.2", resource_id=""),
         "NAVIGATION_SCROLL_CONTAINER_CHANGED", ["path"], []),
        (_navigation_scroll_container(capture_id="before", request_id="before-request", generation=1),
         _navigation_scroll_container(capture_id="after", request_id="after-resource", generation=2,
                                      path="0.2", resource_id="com.samsung.android.oneconnect:id/other_list"),
         "NAVIGATION_SCROLL_CONTAINER_CHANGED", ["resource_id"], []),
        (_navigation_scroll_container(capture_id="before", request_id="before-request", generation=1),
         _navigation_scroll_container(capture_id="after", request_id="after-window", generation=2,
                                      window_id=45535),
         "NAVIGATION_SCROLL_POST_CAPTURE_STALE", ["window_id"], ["window_id"]),
        (_navigation_scroll_container(capture_id="before", request_id="before-request", generation=1),
         _navigation_scroll_container(capture_id="after", request_id="after-service", generation=2,
                                      service_instance_id="different-service"),
         "NAVIGATION_SCROLL_POST_CAPTURE_STALE", [], ["service_instance_id"]),
        (_navigation_scroll_container(capture_id="before", request_id="before-request", generation=1),
         _navigation_scroll_container(capture_id="before", request_id="stale-capture", generation=1),
         "NAVIGATION_SCROLL_POST_CAPTURE_STALE", [], []),
    )
    for (before_container, post_container, expected_reason,
         expected_identity_changes, expected_capture_changes) in cases:
        client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
        containers = [before_container, post_container]
        monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot",
                            lambda *_args, **_kwargs: (containers.pop(0),
                                                       "NAVIGATION_SCROLL_CONTAINER_RESOLVED"))
        owner_checks = []
        monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action",
                            lambda *_args, **_kwargs: owner_checks.append(True) or
                            (False, "NAVIGATION_TARGET_NOT_FOUND"))
        scroll_calls = []

        def scroll_success(**kwargs):
            scroll_calls.append(kwargs)
            client.last_scroll_request_id = "scroll-stale-check"
            client.last_scroll_result = {
                "reqId": "scroll-stale-check", "success": True, "explicitTarget": True,
                "scrollContainerPath": kwargs["container_path"], "scrollableNodeFound": True,
                "actionSupported": True, "actionAttempted": True,
            }
            return True

        client.scroll = scroll_success
        monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)
        logs = []
        monkeypatch.setattr(collection_flow, "log", logs.append)
        ok, reason = collection_flow._run_helper_snapshot_navigation_search(
            client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id,
            max_scroll_search_steps=2, step_wait_seconds=0,
        )
        assert ok is False and reason == expected_reason
        assert len(owner_checks) == 2 and len(scroll_calls) == 1
        assert calls["dispatch"] == [] and calls["xml"] == []
        diagnostic = next(json.loads(line.split("[search_scroll_result] ", 1)[1])
                          for line in logs if "[search_scroll_result] " in line)
        assert diagnostic["identity_changed_reasons"] == expected_identity_changes
        assert diagnostic["capture_identity_changed_reasons"] == expected_capture_changes


def test_navigation_scroll_missing_post_container_is_recorded_and_fails_closed(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    containers = [
        (_navigation_scroll_container(capture_id="before", request_id="before-request", generation=10),
         "NAVIGATION_SCROLL_CONTAINER_RESOLVED"),
        (None, "NAVIGATION_SCROLL_CONTAINER_AMBIGUOUS"),
    ]
    monkeypatch.setattr(collection_flow, "_resolve_navigation_scroll_container_from_helper_snapshot",
                        lambda *_args, **_kwargs: containers.pop(0))
    monkeypatch.setattr(collection_flow, "_run_helper_snapshot_navigation_action",
                        lambda *_args, **_kwargs: (False, "NAVIGATION_TARGET_NOT_FOUND"))
    logs = []
    monkeypatch.setattr(collection_flow, "log", logs.append)

    def scroll_success(**kwargs):
        client.last_scroll_request_id = "scroll-missing-post"
        client.last_scroll_result = {
            "reqId": "scroll-missing-post", "success": True, "explicitTarget": True,
            "scrollContainerPath": kwargs["container_path"], "scrollableNodeFound": True,
            "actionSupported": True, "actionAttempted": True, "performedActionId": 4096,
        }
        return True

    client.scroll = scroll_success
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)
    ok, reason = collection_flow._run_helper_snapshot_navigation_search(
        client, "SERIAL", tab_cfg, "life_air_care_plugin", contract_id,
        max_scroll_search_steps=1, step_wait_seconds=0,
    )
    assert ok is False and reason == "NAVIGATION_SCROLL_CONTAINER_AMBIGUOUS"
    diagnostic = next(json.loads(line.split("[search_scroll_result] ", 1)[1])
                      for line in logs if "[search_scroll_result] " in line)
    assert diagnostic["post_capture_status"] == "CONTAINER_RESOLUTION_REJECTED"
    assert diagnostic["post_container_resolution_reason"] == "NAVIGATION_SCROLL_CONTAINER_AMBIGUOUS"
    assert diagnostic.get("post_capture") is None
    assert calls["dispatch"] == [] and calls["xml"] == []


def test_configured_navigation_presearch_skips_legacy_unsealed_top_reset(monkeypatch):
    calls = {"top_reset": [], "search": []}

    class Client:
        last_pre_nav_failure_reason = ""

        def scroll_to_top(self, **kwargs):
            calls["top_reset"].append(kwargs)
            return {"ok": True}

    def reject_with_current_miss(_client, _dev, **kwargs):
        calls["search"].append(kwargs)
        return False, "NAVIGATION_TARGET_NOT_FOUND"

    monkeypatch.setattr(collection_flow, "_run_xml_scroll_search_tap", reject_with_current_miss)
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_args: None)
    client = Client()
    ok = collection_flow._run_pre_navigation_steps(
        client, "SERIAL", {
            "scenario_id": "life_air_care_plugin",
            "entry_type": "card",
            "screen_context_mode": "new_screen",
            "stabilization_mode": "anchor_only",
            "pre_navigation": [{
                "action": "xml_scroll_search_tap", "target": "Air Care", "type": "a",
                "navigation_action_contract_id": "life_service_card_read_only_navigation",
            }],
            "pre_navigation_retry_count": 1,
        },
    )

    assert ok is False
    assert calls["top_reset"] == []
    assert len(calls["search"]) == 1
    assert calls["search"][0]["navigation_action_contract_id"] == "life_service_card_read_only_navigation"
    assert calls["search"][0]["max_scroll_search_steps"] == 5
    assert client.last_pre_nav_failure_reason == (
        "navigation_action_rejected:NAVIGATION_TARGET_NOT_FOUND"
    )


def test_navigation_rejection_log_preserves_helper_receipt_and_adb_boundary(monkeypatch, capsys):
    receipt = {
        "status": "REJECTED",
        "failure_code": "NAVIGATION_OWNER_RECEIPT_UNVERIFIED",
        "request_id": "nav-request-1",
        "transaction_id": "transaction-1",
        "owner_receipt_reason": "OWNER_CLICK_EVENT_NOT_RECORDED",
        "owner_receipt_eligible_exact_click_count": 0,
        "post_state_mismatch_fields": ["accessibility_focus_missing", "focus_window_mismatch"],
        "post_state_diagnostics": {
            "event_source_status": "EXACT_RETAINED_NODE_MATCH",
            "event_source_connection_match": True,
            "post_capture_id": "post-capture-redacted",
            "focus_window_id": None,
            "focus_window_id_status": "FIELD_ABSENT",
            "accessibility_focused": False,
        },
        "action_call_count": 1,
    }
    rejected = {
        "success": False,
        "status": "rejected",
        "reason": "NAVIGATION_ACTION_RECEIPT_UNVERIFIED",
        "reqId": "nav-request-1",
        "receipt": receipt,
        "receipt_mismatch_fields": ["status", "verified_navigation"],
        "post_state_mismatch_fields": receipt["post_state_mismatch_fields"],
        "post_state_diagnostics": receipt["post_state_diagnostics"],
        "receipt_status": receipt["status"],
        "receipt_failure_code": receipt["failure_code"],
        "receipt_owner_receipt_reason": receipt["owner_receipt_reason"],
        "receipt_owner_click_count": 0,
        "broadcast_argv": ["adb", "shell", "am", "broadcast", "-a", "NAVIGATION_ACTION"],
        "broadcast_stdout": "Broadcast completed: result=0",
    }
    client, tab_cfg, calls, contract_id = _wire_navigation_client(
        monkeypatch, _navigation_helper_snapshot(), dispatch_result=rejected)
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="(?i)^navigate up$", type_="a",
        max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )
    assert ok is False and reason == "NAVIGATION_ACTION_RECEIPT_UNVERIFIED"
    assert calls["dispatch"] and calls["xml"] == []
    log_output = capsys.readouterr().out
    assert "receipt_status='REJECTED'" in log_output
    assert "receipt_failure_code='NAVIGATION_OWNER_RECEIPT_UNVERIFIED'" in log_output
    assert "receipt_mismatch_fields='status,verified_navigation'" in log_output
    assert "receipt_owner_reason='OWNER_CLICK_EVENT_NOT_RECORDED'" in log_output
    assert "receipt_owner_click_count='0'" in log_output
    assert "post_state_mismatch_fields='accessibility_focus_missing,focus_window_mismatch'" in log_output
    assert '"event_source_status":"EXACT_RETAINED_NODE_MATCH"' in log_output
    assert '"focus_window_id_status":"FIELD_ABSENT"' in log_output
    assert '"post_capture_id":"post-capture-redacted"' in log_output
    assert "broadcast_argv=['adb', 'shell', 'am', 'broadcast', '-a', 'NAVIGATION_ACTION']" in log_output
    assert "broadcast_stdout='Broadcast completed: result=0'" in log_output


def test_navigation_contract_trims_outer_label_whitespace_without_changing_descriptor(monkeypatch, capsys):
    exact = _navigation_helper_snapshot()
    exact_client, exact_tab, exact_calls, exact_contract = _wire_navigation_client(monkeypatch, exact)
    exact_ok, exact_reason = collection_flow._run_xml_scroll_search_tap(
        exact_client, "SERIAL", tab_cfg=exact_tab, target="navigate up", type_="a",
        max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=exact_contract,
    )
    assert exact_ok is True and exact_reason == "VERIFIED_NAVIGATION"
    exact_owner = exact_calls["owners"][0]

    source_target = deepcopy(exact.raw_hierarchy["windows"][0]["root"]["children"][0])
    source_target["text"] = " \tNavigate to parent menu \n"
    whitespace = _navigation_helper_snapshot(targets=[source_target])
    client, tab, calls, contract_id = _wire_navigation_client(monkeypatch, whitespace)
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab, target="navigate up", type_="a",
        max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )

    assert ok is True and reason == "VERIFIED_NAVIGATION"
    owner = calls["owners"][0]
    assert owner["text"] == "Navigate to parent menu"
    assert whitespace.raw_hierarchy["windows"][0]["root"]["children"][0]["text"] == source_target["text"]
    assert owner["sourceNodeId"] == "10" and owner["windowId"] == 45534
    assert owner["_helperNodePath"] == exact_owner["_helperNodePath"]
    assert owner["_helperSourceSnapshotId"] == whitespace.decoded.capture_authority.capture_key
    assert owner["_helperSourceSnapshotId"] != exact_owner["_helperSourceSnapshotId"]
    assert owner["_helperNodeDescriptorDigest"] != exact_owner["_helperNodeDescriptorDigest"]
    assert calls["dispatch"] and calls["xml"] == []

    raw_descriptor_fields = (
        "text", "contentDescription", "viewIdResourceName", "className",
        "packageName", "sourceNodeId", "windowId", "boundsInScreen",
        "clickable", "effectiveClickable", "enabled", "focusable",
        "focused", "inputFocused", "accessibilityFocused", "selected",
        "scrollable", "isScrollable", "checkable", "checked",
        "visibleToUser", "isVisibleToUser", "actions",
    )
    raw_descriptor = {key: source_target.get(key) for key in raw_descriptor_fields}
    expected_raw_digest = hashlib.sha256(json.dumps(
        raw_descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    assert owner["_helperNodeDescriptorDigest"] == expected_raw_digest

    class BeginClient:
        evidence_runtime = SimpleNamespace(
            run_id="run-trusted", is_enabled=True,
            _scenario_id="life_air_care_plugin", _scenario_tx_id="scenario-current",
        )
        _active_evidence_scenario_id = "life_air_care_plugin"
        _active_evidence_scenario_tx_id = "scenario-current"

        def _broadcast(self, _dev, _action, extras):
            self.extras = list(extras)
            return "Broadcast completed: result=0"

        def _read_log_result(self, _dev, _prefix, response_req_id, **_kwargs):
            def extra(name):
                return self.extras[self.extras.index(name) + 1]

            return {
                "reqId": response_req_id,
                "captureReqId": extra("captureReqId"),
                "requestedTransactionId": extra("transactionId"),
                "transactionId": extra("transactionId"),
                "operation": "begin",
                "ok": True,
                "invocationUriBound": True,
                "invocationId": "scenario-current",
            }

    begin_client = BeginClient()
    # The route fixture replaces BEGIN with a deterministic lease response;
    # restore the real transport serializer for this request-payload assertion.
    monkeypatch.undo()
    capture = entry_safety.begin_transaction_click_capture(
        begin_client, "SERIAL", transaction_id="navigation-transaction", target_node=owner,
        scenario_id="life_air_care_plugin", include_talkback_baseline=False,
        require_canonical_invocation=True,
    )
    assert capture["armed"]["ok"] is True
    encoded_request = begin_client.extras[
        begin_client.extras.index("ownerLeaseRequestBase64") + 1
    ]
    lease_request = json.loads(base64.urlsafe_b64decode(encoded_request).decode("utf-8"))
    assert "text" not in lease_request
    assert lease_request["descriptor_digest"] == expected_raw_digest
    assert lease_request["node_path"] == owner["_helperNodePath"]
    assert lease_request["window_id"] == owner["windowId"]
    assert lease_request["package"] == owner["packageName"]
    assert lease_request["source_snapshot_id"] == owner["_helperSourceSnapshotId"]
    assert lease_request["source_capture_key"] == owner["_helperCaptureAuthority"]["capture_key"]
    source_trace = capsys.readouterr().out
    assert "[ENTRY_CLICK_CAPTURE][host][source_identity]" in source_trace
    assert f"sourceRequestId={lease_request['source_capture_request_id']}" in source_trace
    assert f"sourceProcessEpoch={lease_request['source_process_epoch']}" in source_trace
    assert f"sourceServiceInstanceId={lease_request['source_service_instance_id']}" in source_trace
    assert f"sourceCaptureSequence={lease_request['source_capture_sequence']}" in source_trace
    assert f"sourceCaptureKey={lease_request['source_capture_key']}" in source_trace
    assert f"ownerDescriptorDigest={expected_raw_digest}" in source_trace


def test_navigation_contract_rejects_substantive_label_and_stale_capture_without_dispatch(monkeypatch):
    exact = _navigation_helper_snapshot()
    source_target = deepcopy(exact.raw_hierarchy["windows"][0]["root"]["children"][0])
    source_target["text"] = "Navigate to parent menu (changed)"
    snapshots = [
        _navigation_helper_snapshot(targets=[source_target]),
        _navigation_helper_snapshot(stale_identity=True),
    ]
    for snapshot in snapshots:
        client, tab, calls, contract_id = _wire_navigation_client(monkeypatch, snapshot)
        ok, _reason = collection_flow._run_xml_scroll_search_tap(
            client, "SERIAL", tab_cfg=tab, target="navigate up", type_="a",
            max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
            navigation_action_contract_id=contract_id,
        )
        assert ok is False
        assert calls["owners"] == [] and calls["dispatch"] == [] and calls["xml"] == []


def test_navigation_contract_rejects_mismatched_lease_identity_before_dispatch(monkeypatch):
    snapshot = _navigation_helper_snapshot()
    for field, value in (
            ("ownerDescriptorDigest", "e" * 64),
            ("sourceSnapshotId", "stale-capture-key"),
            ("ownerPath", [0, 1, 4096])):
        client, tab, calls, contract_id = _wire_navigation_client(monkeypatch, snapshot)
        original_begin = entry_safety.begin_transaction_click_capture

        def mismatched_begin(*args, _field=field, _value=value, **kwargs):
            capture = original_begin(*args, **kwargs)
            capture["armed"][_field] = _value
            return capture

        monkeypatch.setattr(entry_safety, "begin_transaction_click_capture", mismatched_begin)
        ok, reason = collection_flow._run_xml_scroll_search_tap(
            client, "SERIAL", tab_cfg=tab, target="navigate up", type_="a",
            max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
            navigation_action_contract_id=contract_id,
        )

        assert ok is False and reason == "NAVIGATION_OWNER_LEASE_MISMATCH"
        assert len(calls["owners"]) == 1
        assert calls["dispatch"] == [] and calls["xml"] == []


def test_begin_result_log_miss_replay_is_preserved_and_never_dispatches_or_falls_back(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    raw_missing_result = {
        "success": False,
        "reason": "ENTRY_CLICK_CAPTURE_RESULT 로그를 찾지 못했습니다.",
    }
    response_ids = []

    class CaptureRpc:
        @staticmethod
        def _broadcast(_dev, action, _extras):
            return f"Broadcasting: Intent {{ act={action} }}\nBroadcast completed: result=0"

        @staticmethod
        def _read_log_result(_dev, _prefix, req_id, **_kwargs):
            response_ids.append(req_id)
            return {**raw_missing_result, "reqId": req_id}

    capture_req_id = "entry_click_replay"

    def begin(_client, dev, *, transaction_id, target_node, scenario_id, **_kwargs):
        calls["owners"].append(target_node)
        armed = entry_safety._entry_capture_request(
            CaptureRpc, dev, req_id=capture_req_id, transaction_id=transaction_id,
            operation="begin", owner_lease_request={"scenario_id": scenario_id},
        )
        return {
            "req_id": capture_req_id,
            "transaction_id": transaction_id,
            "armed": armed,
            "capture_id": "",
            "connection_id": "",
        }

    monkeypatch.setattr(entry_safety, "begin_transaction_click_capture", begin)
    monkeypatch.setattr(entry_safety, "validate_transaction_click_capture",
                        lambda *_args, **_kwargs: pytest.fail("failed arm must not validate"))
    monkeypatch.setattr(entry_safety, "end_transaction_click_capture",
                        lambda *_args, **_kwargs: calls["cleanup"].append("disarmed") or
                        {"ok": True, "reason": "DISARMED"})
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes",
                        lambda *_args, **_kwargs: pytest.fail("opted-in rejection must not use XML fallback"))

    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="(?i)^navigate up$", type_="a",
        max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )
    assert response_ids and response_ids[0].startswith("entry_click_replay_begin_")
    assert ok is False
    assert reason == "ENTRY_CLICK_CAPTURE_RESULT_UNAVAILABLE"
    assert calls["dispatch"] == []
    assert calls["xml"] == []
    assert calls["cleanup"] == ["disarmed"]


def test_configured_navigation_carries_validated_capture_key_when_raw_snapshot_projection_omits_it(monkeypatch):
    snapshot = _navigation_helper_snapshot(omit_raw_snapshot_id=True)
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, snapshot)
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="(?i)^navigate up$", type_="a",
        max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )
    assert ok is True and reason == "VERIFIED_NAVIGATION"
    owner = calls["owners"][0]
    assert owner["_helperSourceSnapshotId"] == owner["_helperCaptureAuthority"]["capture_key"]
    assert calls["dispatch"] and calls["xml"] == []


def test_navigation_capture_may_advance_past_precheck_generation_without_becoming_stale(monkeypatch):
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, _navigation_helper_snapshot())
    client.readiness["identity_check"]["capability_generation"] = 6
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="(?i)^navigate up$", type_="a",
        max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )
    assert ok is True and reason == "VERIFIED_NAVIGATION"
    assert len(calls["owners"]) == 1 and len(calls["dispatch"]) == 1


def test_first_sealed_capture_may_advance_from_zero_capability_generation(monkeypatch):
    snapshot = _navigation_helper_snapshot(generation=1)
    client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, snapshot)
    client.readiness["identity_check"]["capability_generation"] = 0
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=tab_cfg, target="(?i)^navigate up$", type_="a",
        max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
        navigation_action_contract_id=contract_id,
    )
    assert ok is True and reason == "VERIFIED_NAVIGATION"
    assert calls["owners"][0]["_helperCaptureAuthority"]["generation"] == 1
    assert len(calls["dispatch"]) == 1


def test_configured_navigation_rejects_stale_missing_ambiguous_and_actionable_child_before_dispatch(monkeypatch):
    valid = _navigation_helper_snapshot()
    missing_target = _navigation_helper_snapshot(targets=[{
        **valid.raw_hierarchy["windows"][0]["root"]["children"][0], "text": "Unrelated"
    }])
    duplicate = _navigation_helper_snapshot(targets=[
        valid.raw_hierarchy["windows"][0]["root"]["children"][0],
        valid.raw_hierarchy["windows"][0]["root"]["children"][0],
    ])
    stale = _navigation_helper_snapshot(stale_identity=True)
    actionable_child = _navigation_helper_snapshot(targets=[{
        **valid.raw_hierarchy["windows"][0]["root"]["children"][0],
        "children": [{
            "text": "child", "className": "android.widget.FrameLayout",
            "packageName": "com.samsung.android.oneconnect", "windowId": 45534,
            "boundsInScreen": {"left": 60, "top": 140, "right": 150, "bottom": 260},
            "clickable": True, "enabled": True, "checkable": False,
            "actions": [{"id": 16, "name": "ACTION_CLICK"}], "children": [],
        }],
    }])
    for snapshot in (stale, missing_target, duplicate, actionable_child):
        client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, snapshot)
        ok, reason = collection_flow._run_xml_scroll_search_tap(
            client, "SERIAL", tab_cfg=tab_cfg, target="(?i)^navigate up$", type_="a",
            max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
            navigation_action_contract_id=contract_id,
        )
        assert ok is False
        assert calls["owners"] == []
        assert calls["dispatch"] == []
        assert calls["xml"] == []


def test_configured_navigation_rejects_missing_or_mismatched_capture_authority_before_lease(monkeypatch):
    mutations = (
        "missing_metadata_authority", "missing_decoded_authority", "invalid_seal",
        "metadata_request", "raw_request", "service_id", "process_epoch", "generation",
        "negative_capability_generation",
        "capture_sequence", "snapshot_key", "missing_snapshot_key", "raw_snapshot_key", "root_bytes",
        "root_digest", "candidate_digest", "window_id", "source_node_id",
    )
    for mutation in mutations:
        snapshot = _navigation_helper_snapshot()
        client, tab_cfg, calls, contract_id = _wire_navigation_client(monkeypatch, snapshot)
        metadata = client.last_hierarchy_metadata
        authority = snapshot.decoded.capture_authority.to_dict()
        if mutation == "missing_metadata_authority":
            metadata.pop("captureAuthority")
        elif mutation == "missing_decoded_authority":
            snapshot.decoded.capture_authority = None
        elif mutation == "invalid_seal":
            authority["validation_seal"] = "0" * 64
            metadata["captureAuthority"] = authority
        elif mutation == "metadata_request":
            metadata["reqId"] = "other-request"
        elif mutation == "raw_request":
            snapshot.raw_hierarchy["reqId"] = "other-request"
        elif mutation == "service_id":
            client.readiness["identity_check"]["capability_service_instance_id"] = "other-service"
        elif mutation == "process_epoch":
            client.readiness["identity_check"]["capability_process_epoch"] = "other-process"
        elif mutation == "generation":
            client.readiness["identity_check"]["capability_generation"] = 8
        elif mutation == "negative_capability_generation":
            client.readiness["identity_check"]["capability_generation"] = -1
        elif mutation == "capture_sequence":
            metadata["captureSequence"] = 8
        elif mutation == "snapshot_key":
            metadata["snapshotId"] = "other-capture-key"
        elif mutation == "missing_snapshot_key":
            metadata.pop("snapshotId")
        elif mutation == "raw_snapshot_key":
            snapshot.raw_hierarchy["snapshotId"] = "other-capture-key"
        elif mutation == "root_bytes":
            snapshot.raw_hierarchy["windows"][0]["root"]["children"][0]["text"] = "Changed after capture"
        elif mutation == "root_digest":
            authority["root_digest"] = "f" * 64
            metadata["captureAuthority"] = authority
        elif mutation == "candidate_digest":
            authority["candidate_digest"] = "e" * 64
            metadata["captureAuthority"] = authority
        elif mutation == "window_id":
            snapshot.raw_hierarchy["windows"][0]["root"]["windowId"] = 45535
        elif mutation == "source_node_id":
            snapshot.raw_hierarchy["windows"][0]["root"]["children"][0]["sourceNodeId"] = None

        ok, reason = collection_flow._run_xml_scroll_search_tap(
            client, "SERIAL", tab_cfg=tab_cfg, target="(?i)^navigate up$", type_="a",
            max_scroll_search_steps=0, step_wait_seconds=0.2, transition_fast_path=False,
            navigation_action_contract_id=contract_id,
        )
        assert ok is False, mutation
        assert calls["owners"] == [], mutation
        assert calls["dispatch"] == [], mutation
        assert calls["xml"] == [], mutation
        if mutation != "source_node_id":
            assert any(token in reason for token in ("CAPTURE_AUTHORITY", "SNAPSHOT_IDENTITY", "TARGET")), (
                mutation, reason)
