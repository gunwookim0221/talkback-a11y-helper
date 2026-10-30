from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from phase6d_capture_support import attach_capture_authority
from talkback_lib.native_dispatch_evidence import NativeDispatchReceiptStore
from tb_runner import collection_flow
from tb_runner.plugin_entry_provenance import (
    PluginEntryProvenanceTracker,
    selected_entity_evidence,
    source_capture_evidence,
    scroll_target_inventory,
    entry_operation_evidence,
    root_authority_is_current,
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _selected_node(*, entity=True):
    node = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/device_card",
        "className": "android.widget.FrameLayout",
        "boundsInScreen": "[0,0][600,600]",
        "text": "Air Purifier",
        "clickable": True,
        "visibleToUser": True,
    }
    if entity:
        node.update(device_id="runtime-purifier-7", device_type="AIR_PURIFIER")
    return node


class _EntryClient:
    def __init__(self, node):
        store = NativeDispatchReceiptStore()
        self._adb_device = SimpleNamespace(native_dispatch_receipts=store)
        self.evidence_runtime = SimpleNamespace(is_enabled=True, run_id="evidence-run")
        self._active_evidence_scenario_id = "device_air_purifier_plugin"
        self._active_evidence_scenario_tx_id = "scenario-tx-current"
        self.last_hierarchy_metadata = {
            "reqId": "source-request", "snapshotId": "source-snapshot", "captureSequence": 4,
        }
        self.last_dump_metadata = {
            "requestId": "source-request", "transportMode": "RELIABLE_FILE_PFD",
            "candidateSchemaVersion": "candidate-v2", "candidateContractVersion": "candidate-contract-v3",
        }
        self.node = node
        self.bind_nodes([deepcopy(node)])

    def bind_nodes(self, nodes):
        from talkback_lib.reliable_hierarchy_schema import CANDIDATE_CONTRACT_VERSION, CANDIDATE_SCHEMA_VERSION
        copied_nodes = deepcopy(nodes)
        source = attach_capture_authority({"nodes": copied_nodes}, sequence=4, request_id="source-request")
        candidate = SimpleNamespace(complete=True, schema_version=CANDIDATE_SCHEMA_VERSION,
                                   contract_version=CANDIDATE_CONTRACT_VERSION)
        decoded = SimpleNamespace(capture_authority=source["capture_authority"], request_id="source-request",
                                  capability_verified=True, traversal_candidates=candidate)
        self._last_traversal_candidate_snapshot = SimpleNamespace(
            decoded=decoded, candidates=tuple(deepcopy(copied_nodes)))

    def tap_xy_adb(self, *, dev, x, y):
        self._adb_device.native_dispatch_receipts.observe(["shell", "input", "tap", str(x), str(y)])
        return True


def _record_production_entry(*, entity=True):
    node = _selected_node(entity=entity)
    nodes = [node]
    client = _EntryClient(node)
    tracker = PluginEntryProvenanceTracker(
        "device_air_purifier_plugin", scenario_run_id="run-current",
    )
    tracker.record_source_capture(source_capture_evidence(client, nodes))
    client._phase6d3a_entity_root_tracker = tracker
    card = {
        "node": node,
        "label": "Air Purifier",
        "stable_label": "Air Purifier",
        "identity_source": "device_name_child",
        "rid": "com.samsung.android.oneconnect:id/device_card",
        "class_name": "android.widget.FrameLayout",
        "bounds": "0,0,600,600",
    }
    with __import__("tb_runner.plugin_entry_provenance", fromlist=["install_navigation_observer"]).install_navigation_observer(
        client, tracker,
    ):
        ok, reason = collection_flow._tap_device_card_safe(client, "serial", card, nodes=nodes)
    assert ok, reason
    assert tracker.provenance is not None
    return tracker, tracker.snapshot("run-current")


def _root(*, scenario="device_air_purifier_plugin", run="run-current", entity_id="runtime-purifier-7",
          entity_type="AIR_PURIFIER", request_id="root-request", resource_id="shared-plugin-content",
          evidence_run_id="evidence-run", scenario_tx_id="scenario-tx-current", generation=2,
          capture_id="current-composite-capture", plugin_body=True):
    node = {"resourceId": resource_id, "className": "android.widget.FrameLayout",
            "bounds": "0,0,600,2000", "visibleToUser": True}
    if entity_id is not None:
        node["device_id"] = entity_id
    if entity_type is not None:
        node["entity_type"] = entity_type
    raw = {
        "scenario_id": scenario,
        "scenario_run_id": run,
        "evidence_run_id": evidence_run_id,
        "scenario_tx_id": scenario_tx_id,
        "invocation_id": scenario_tx_id,
        "capture_id": capture_id,
        "hierarchy_capture_id": capture_id,
        "hierarchy_snapshot_id": "root-snapshot-5",
        "hierarchy_capture_sequence": 5,
        "hierarchy_request_id": request_id,
        "timestamp": _now(),
        "snapshot_coherent": True,
        "hierarchy_complete": True,
        "focus_capture_id": capture_id,
        "geometry_capture_id": capture_id,
        "package_name": "com.samsung.android.oneconnect",
        "activity_name": "com.samsung.android.oneconnect.webplugin.WebPluginActivity",
        "context_source": "helper_tree_component",
        "window_evidence": {"focused_window_component": "com.samsung.android.oneconnect.webplugin.WebPluginActivity"},
        "nodes": [node] + ([{
            "resourceId": "com.samsung.android.plugin.device:id/AirQualitySensorCapabilityCardView_header_title",
            "className": "android.widget.TextView", "text": "Air quality",
            "bounds": "84,564,822,636", "visibleToUser": True,
        }] if plugin_body else []),
    }
    return attach_capture_authority(raw, sequence=5, request_id=request_id, generation=generation)


def _mark_current_observation(raw):
    raw["production_observation_current"] = True
    raw["production_observation_envelope"] = {
        "capture_complete": True,
        "capture_id": raw["capture_id"],
        "capture_authority": deepcopy(raw["capture_authority"]),
        "hierarchy_capture_id": raw["hierarchy_capture_id"],
        "hierarchy_request_id": raw["hierarchy_request_id"],
        "scenario_run_id": raw["scenario_run_id"],
    }
    return raw


def _transition(provenance=None):
    result = {
        "open_completed": True,
        "entry_contract_reason": "success_verified",
        "entry_contract_detail": "plugin_open_verified",
        "anchor_matched": True,
        "plugin_open_verified": True,
        "post_open_state": "PLUGIN_BODY",
        "post_click_transition_same_screen": False,
        "post_click_transition_signal": "activity_transition",
    }
    if provenance is not None:
        result["entity_root_provenance"] = provenance
    return result


def test_production_entry_binds_selected_node_to_native_receipt_and_source_capture():
    tracker, proof = _record_production_entry()
    selected = proof["selected_entity"]
    action = proof["entry_operation"]
    assert selected["status"] == "OBSERVED"
    assert selected["source_hierarchy_request_id"] == "source-request"
    assert selected["selected_node_unique_in_source"] is True
    assert selected["visible_label_sha256"]
    assert "visible_label" not in selected
    assert selected["runtime_entity_references"][0]["value_sha256"]
    assert "runtime-purifier-7" not in repr(proof)
    assert action["action_type"] == "INPUT_TAP"
    assert action["operation_id"]
    assert action["receipt_match_count"] == 1
    assert action["dispatch_status"] == "DISPATCHED"
    assert action["request_id"] is None
    assert action["source_hierarchy_request_id"] == selected["source_hierarchy_request_id"]
    assert action["source_hierarchy_capture_id"] == selected["source_hierarchy_capture_id"]
    assert action["navigation_event_kind"] == "TAP"
    assert action["point_inside_selected_bounds"] is True
    assert action["operation_started_at"]
    assert action["operation_finished_at"]
    assert action["navigation_epoch"] == tracker.navigation_epoch == 1


def test_entity_reference_in_selected_card_descendant_is_bound_within_same_source_capture():
    parent = _selected_node(entity=False)
    parent["stable_node_path"] = "0.2"
    child = {
        "stable_node_path": "0.2.0",
        "ancestors": [{"path": "0.2", "resource_id": parent["viewIdResourceName"]}],
        "device_id": "runtime-purifier-7",
        "device_type": "AIR_PURIFIER",
    }
    nodes = [parent, child]
    client = _EntryClient(parent)
    client.bind_nodes(nodes)
    source = source_capture_evidence(client, nodes)
    evidence = selected_entity_evidence({
        "node": parent, "stable_label": "Air Purifier", "rid": parent["viewIdResourceName"],
        "class_name": parent["className"], "bounds": "0,0,600,600",
        "identity_source": "device_name_child",
    }, source, source_nodes=nodes)
    assert evidence["status"] == "OBSERVED"
    assert evidence["runtime_entity_references"][0]["field"] == "device_id"
    assert evidence["runtime_entity_types"] == ["airpurifier"]


def test_independent_current_root_can_be_bound_to_matching_runtime_entity():
    tracker, entry = _record_production_entry()
    result = tracker.bind_current_root(_root(), run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True)
    assert result["link_status"] == "VERIFIED_LINK"
    assert result["resulting_root"]["capture_status"] == "CURRENT_COMPLETE"
    assert result["resulting_root"]["hierarchy_request_id"] != entry["selected_entity"]["source_hierarchy_request_id"]
    assert result["resulting_root"]["hierarchy_snapshot_id"] == result["resulting_root"]["capture_id"]
    assert result["resulting_root"]["source_result_capture_distinct"] is True
    assert result["resulting_root"]["traversal_root_digest"]
    assert result["authority"] == "DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY"


@pytest.mark.parametrize(("field", "value"), [
    ("capture_id", "caller-capture"),
    ("hierarchy_capture_id", "caller-capture"),
    ("hierarchy_request_id", "caller-request"),
    ("hierarchy_snapshot_id", "caller-snapshot"),
    ("hierarchy_capture_sequence", 99),
    ("hierarchy_process_epoch", "caller-epoch"),
    ("hierarchy_generation", 99),
    ("hierarchy_service_instance_id", "caller-service"),
    ("package_name", "other.package"),
    ("traversal_root_ref", "windows[1].root"),
    ("traversal_root_window_id", 99),
    ("traversal_root_digest", "0" * 64),
    ("traversal_root_class_name", "forged.Root"),
    ("traversal_root_source_node_id", "forged-node"),
    ("traversal_root_bounds", [1, 1, 2, 2]),
    ("hierarchy_root_digest", "0" * 64),
    ("hierarchy_root_class_name", "forged.Root"),
    ("hierarchy_root_source_node_id", "forged-node"),
    ("hierarchy_root_bounds", [1, 1, 2, 2]),
])
def test_result_capture_identity_mismatch_never_becomes_current_complete(field, value):
    tracker, _ = _record_production_entry()
    raw = _root()
    raw[field] = value
    result = tracker.bind_current_root(
        raw, run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    assert result["resulting_root"]["capture_status"] == "INCOMPLETE_OR_STALE"
    assert result["link_status"] == "UNKNOWN"
    assert "RESULT_CAPTURE_INCOMPLETE_OR_STALE" in result["reason_codes"]


def test_mutated_result_authority_seal_cannot_complete_entity_root_capture():
    tracker, _ = _record_production_entry()
    raw = _root()
    raw["capture_authority"]["root_digest"] = "0" * 64
    result = tracker.bind_current_root(
        raw, run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    assert result["resulting_root"]["capture_status"] == "INCOMPLETE_OR_STALE"
    assert result["link_status"] == "UNKNOWN"


@pytest.mark.parametrize(("owner", "field", "value"), [
    ("selected_entity", "source_hierarchy_request_id", "caller-request"),
    ("selected_entity", "source_hierarchy_capture_id", "caller-capture"),
    ("selected_entity", "source_hierarchy_snapshot_id", "caller-snapshot"),
    ("selected_entity", "source_hierarchy_capture_sequence", 99),
    ("selected_entity", "source_hierarchy_process_epoch", "caller-epoch"),
    ("selected_entity", "source_hierarchy_generation", 99),
    ("selected_entity", "source_hierarchy_service_instance_id", "caller-service"),
    ("selected_entity", "source_hierarchy_root_ref", "windows[1].root"),
    ("selected_entity", "source_hierarchy_window_id", 99),
    ("selected_entity", "source_hierarchy_root_digest", "0" * 64),
    ("entry_operation", "source_hierarchy_request_id", "caller-request"),
    ("entry_operation", "source_hierarchy_capture_id", "caller-capture"),
    ("entry_operation", "source_hierarchy_snapshot_id", "caller-snapshot"),
    ("entry_operation", "source_hierarchy_capture_sequence", 99),
    ("entry_operation", "source_hierarchy_process_epoch", "caller-epoch"),
    ("entry_operation", "source_hierarchy_generation", 99),
    ("entry_operation", "source_hierarchy_service_instance_id", "caller-service"),
    ("entry_operation", "source_hierarchy_root_ref", "windows[1].root"),
    ("entry_operation", "source_hierarchy_window_id", 99),
    ("entry_operation", "source_hierarchy_root_digest", "0" * 64),
])
def test_source_capture_identity_mismatch_never_mints_entity_link(owner, field, value):
    tracker, _ = _record_production_entry()
    tracker.provenance[owner][field] = value
    result = tracker.bind_current_root(
        _root(), run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    assert result["link_status"] == "UNKNOWN"
    assert "ENTRY_OPERATION_SOURCE_CAPTURE_MISMATCH" in result["reason_codes"]


def test_mutated_source_capture_authority_cannot_mint_entity_link():
    tracker, _ = _record_production_entry()
    tracker.provenance["selected_entity"]["source_capture_authority"]["request_id"] = "caller-request"
    result = tracker.bind_current_root(
        _root(), run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    assert result["link_status"] == "UNKNOWN"
    assert "SOURCE_SELECTION_CAPTURE_INCOMPLETE" in result["reason_codes"]


def test_navigation_after_entry_invalidates_link_even_when_root_is_current():
    tracker, _ = _record_production_entry()
    tracker.invalidate()
    result = tracker.bind_current_root(_root(), run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True)
    assert result["link_status"] == "UNKNOWN"
    assert "NAVIGATION_EPOCH_CHANGED" in result["reason_codes"]


def test_navigation_invalidates_previously_bound_link_in_tracker_snapshot():
    tracker, _ = _record_production_entry()
    verified = tracker.bind_current_root(_root(), run_id="run-current",
                                         summary=_transition(tracker.snapshot("run-current")), capture_current=True)
    assert verified["link_status"] == "VERIFIED_LINK"
    tracker.invalidate()
    current = tracker.snapshot("run-current")
    assert current["link_status"] == "UNKNOWN"
    assert "NAVIGATION_EPOCH_CHANGED" in current["reason_codes"]


def test_air_purifier_entry_does_not_link_to_tv_entity_on_shared_component():
    tracker, _ = _record_production_entry()
    result = tracker.bind_current_root(
        _root(entity_id="runtime-tv-3", entity_type="TELEVISION"),
        run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    assert result["resulting_root"]["activity_name"] == ""
    assert result["resulting_root"]["focused_window_component"].endswith("WebPluginActivity")
    assert result["link_status"] == "CONTRADICTORY"
    assert "SELECTED_ENTITY_ROOT_IDENTITY_MISMATCH" in result["reason_codes"]


@pytest.mark.parametrize("kwargs", [
    {"entity_id": None, "entity_type": None},
    {"entity_id": None, "entity_type": "AIR_PURIFIER"},
])
def test_shared_component_and_resource_overlap_do_not_verify_without_entity_identity(kwargs):
    tracker, _ = _record_production_entry(entity=False)
    result = tracker.bind_current_root(
        _root(**kwargs), run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    assert result["link_status"] == "PARTIAL_LINK"
    assert "RUNTIME_ENTITY_OR_DESTINATION_TYPE_NOT_EXPOSED" in result["reason_codes"]


def test_config_digest_is_correlation_only_and_never_runtime_entity_identity():
    tracker, _ = _record_production_entry(entity=False)
    selected = tracker.provenance["selected_entity"]
    selected["entry_contract_digest"] = "same-config-hash"
    result = tracker.bind_current_root(
        {**_root(entity_id=None, entity_type=None), "entry_contract_digest": "same-config-hash"},
        run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    assert result["link_status"] == "PARTIAL_LINK"
    assert result["selected_entity"].get("runtime_entity_references") == []
    assert result["resulting_root"].get("runtime_entity_references") == []


def test_generic_device_card_resource_id_alone_is_not_sufficient():
    tracker, _ = _record_production_entry(entity=False)
    result = tracker.bind_current_root(
        _root(entity_id=None, entity_type=None, resource_id="com.samsung.android.oneconnect:id/device_card"),
        run_id="run-current", summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    assert result["link_status"] == "PARTIAL_LINK"


def test_missing_source_or_unlinked_capture_fails_closed():
    tracker, _ = _record_production_entry()
    same_request = _root(request_id="source-request")
    result = tracker.bind_current_root(same_request, run_id="run-current",
                                       summary=_transition(tracker.snapshot("run-current")), capture_current=True)
    assert result["link_status"] == "UNKNOWN"
    assert "SOURCE_AND_RESULT_CAPTURE_NOT_DISTINCT" in result["reason_codes"]


def test_currentness_rejects_foreign_run_and_incomplete_result_capture():
    tracker, _ = _record_production_entry()
    foreign_run = tracker.bind_current_root(_root(run="other-run"), run_id="run-current",
                                            summary=_transition(tracker.snapshot("run-current")), capture_current=True)
    assert foreign_run["link_status"] == "UNKNOWN"
    assert "RUN_MISMATCH" in foreign_run["reason_codes"]

    incomplete = _root()
    incomplete["geometry_capture_id"] = "different-capture"
    partial = tracker.bind_current_root(incomplete, run_id="run-current",
                                       summary=_transition(tracker.snapshot("run-current")), capture_current=True)
    assert partial["link_status"] == "UNKNOWN"
    assert "RESULT_CAPTURE_INCOMPLETE_OR_STALE" in partial["reason_codes"]


def test_provenance_remains_diagnostic_only_and_does_not_grant_visit_or_permit():
    tracker, _ = _record_production_entry()
    result = tracker.bind_current_root(_root(), run_id="run-current",
                                       summary=_transition(tracker.snapshot("run-current")), capture_current=True)
    assert result["authority"] == "DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY"
    assert "visit_credit" not in result
    assert "permit" not in result


def test_partial_plugin_body_reason_survives_production_observation_handoff(monkeypatch):
    from talkback_lib.exploration_evidence_clock import EvidenceClock
    from tb_runner.phase3_context import phase3_entry_evidence_from_main_loop, resolve_phase3_context
    from tb_runner.scenario_config import TAB_CONFIGS
    import tools.state_fingerprint_diagnostic as state_diagnostic

    scenario_id = "device_air_purifier_plugin"
    config = next(item for item in TAB_CONFIGS if item["scenario_id"] == scenario_id)
    timestamp = _now()
    entry = phase3_entry_evidence_from_main_loop(
        SimpleNamespace(tab_cfg=config, rows=[{
            "timestamp": timestamp,
            "actual_focus_accessibility_focused": True,
            "actual_focus_payload_source": "verified_pre_loop_anchor",
        }]),
        "run-current", timestamp,
    )
    client = SimpleNamespace(
        _phase6c2_frontier_shadow_runtime=object(),
        _phase6d3a_redirect_context={
            "scenario_run_id": "run-current", "entry_evidence": entry,
            "navigation_epoch": "run-current:entry", "registry": object(),
        },
        _adb_device=SimpleNamespace(shadow_evidence_clock=EvidenceClock()),
        last_start_open_summary=_transition(),
        last_hierarchy_metadata={"reqId": "body-capture", "snapshotId": "body-snapshot", "captureSequence": 1},
        last_post_click_transition_same_screen=False,
        last_post_click_transition_signal="activity_transition",
    )
    raw = {
        "scenario_id": scenario_id,
        "scenario_run_id": "run-current",
        "step": 1,
        "timestamp": _now(),
        "capture_id": "body-observation",
        "hierarchy_capture_id": "body-observation",
        "focus_capture_id": "body-observation",
        "geometry_capture_id": "body-observation",
        "hierarchy_request_id": "body-capture",
        "snapshot_coherent": True,
        "hierarchy_complete": True,
        "package_name": "com.samsung.android.oneconnect",
        "activity_name": "com.samsung.android.oneconnect.webplugin.WebPluginActivity",
        "context_source": "helper_tree_component",
        "nodes": [{"text": "Volume", "resourceId": "shared-plugin-content", "visibleToUser": True}],
        "observation_coverage": "OBSERVED_FULL",
    }
    attach_capture_authority(raw, sequence=1, request_id="body-capture")
    monkeypatch.setattr(state_diagnostic, "capture_observation", lambda *args, **kwargs: deepcopy(raw))
    row = {"scenario_id": scenario_id, "scenario_run_id": "run-current", "step_index": 1}
    observed = collection_flow._capture_phase6d3a_production_observation(
        client=client, dev="serial", row=row,
    )
    assert observed is not None
    result = resolve_phase3_context(row["state_graph_observation"])
    assert result["status"] == "UNRESOLVED_CONTEXT"
    assert result["reasons"] == ["CAPTURE_COMPONENT_UNKNOWN"]
    assert row["state_graph_observation"]["phase3_plugin_context_evidence"]
    assert row["state_graph_observation"]["phase3_plugin_context_evidence"]["context_contract_id"]

def test_entry_operation_evidence_keeps_missing_timestamps_unknown():
    evidence = entry_operation_evidence(
        operation_id="op-unknown-time", checkpoint=None, store=None,
        dispatch_succeeded=False, tap_point=None, selected_bounds=None,
    )

    assert evidence["operation_started_at"] == "UNKNOWN"
    assert evidence["operation_finished_at"] == "UNKNOWN"


def test_entry_diagnostic_snapshot_contains_card_tap_receipt_and_transition_event():
    tracker, provenance = _record_production_entry()
    tracker.record_diagnostic("post_tap_transition", {
        "transition_confirmed": False,
        "transition_signal": "none",
        "operation_id": provenance["entry_operation"]["operation_id"],
        "pre_observation": {"diagnostic_only": True, "currentness_status": "UNKNOWN_NOT_ESTABLISHED"},
        "post_observation": {"diagnostic_only": True, "currentness_status": "UNKNOWN_NOT_ESTABLISHED"},
    })
    diagnostic = tracker.diagnostic_snapshot("run-current")

    assert diagnostic["schema_version"] == "phase6d3a-entry-diagnostics-v1"
    assert diagnostic["diagnostic_only"] is True
    assert diagnostic["selected_card"]["bounds"] == provenance["selected_entity"]["bounds"]
    assert diagnostic["selected_card_coordinates"]["tap_point"] == provenance["entry_operation"]["tap_point"]
    assert diagnostic["entry_operation"]["operation_id"]
    assert diagnostic["entry_operation"]["action_type"] == "INPUT_TAP"
    assert diagnostic["entry_operation"]["receipt_match_count"] == 1
    assert diagnostic["entry_operation"]["native_receipt_status"] == "MATCHED"
    receipt = diagnostic["entry_operation"]["native_receipt"]
    assert receipt["operation_id"] == diagnostic["entry_operation"]["operation_id"]
    assert receipt["action_type"] == "INPUT_TAP"
    assert receipt["native_boundary_status"] == "ENTERED"
    assert receipt["dispatch_status"] == "NATIVE_DISPATCH_ATTEMPTED"
    assert diagnostic["entry_operation"]["dispatch_result_status"] == "CALL_RETURNED_TRUE"
    correlation = diagnostic["candidate_input_tap"]
    assert correlation["status"] == "CANDIDATE_OPERATION_CORRELATED"
    assert correlation["correlation_scope"] == "CANDIDATE_TO_OPERATION_ONLY"
    confirmation = correlation["dispatch_receipt_confirmation"]
    assert confirmation["status"] == "MATCHED"
    assert confirmation["action_type"] == "INPUT_TAP"
    assert confirmation["native_receipt"]["operation_id"] == confirmation["operation_id"]
    assert correlation["candidate"]["node_locator_sha256"] == (
        diagnostic["selected_card"]["node_locator_sha256"]
    )
    assert correlation["coordinates"]["tap_point"] == diagnostic["entry_operation"]["tap_point"]
    assert correlation["operation"]["operation_id"] == diagnostic["entry_operation"]["operation_id"]
    assert correlation["operation"]["native_receipt"]["operation_id"] == (
        diagnostic["entry_operation"]["operation_id"]
    )
    assert diagnostic["pre_post_observations"]["status"] == "OBSERVED"
    assert diagnostic["events"][-1]["payload"]["transition_signal"] == "none"


def test_entry_diagnostic_snapshot_marks_unobserved_tap_and_context_unknown():
    diagnostic = PluginEntryProvenanceTracker("device_air_purifier_plugin").diagnostic_snapshot()

    assert diagnostic["candidate_input_tap"]["status"] == "UNKNOWN"
    assert diagnostic["candidate_input_tap"]["candidate"]["status"] == "UNKNOWN"
    assert diagnostic["candidate_input_tap"]["coordinates"]["tap_point"] == "UNKNOWN"
    assert diagnostic["candidate_input_tap"]["operation"]["operation_id"] == "UNKNOWN"
    assert diagnostic["candidate_input_tap"]["operation"]["native_receipt_status"] == "UNKNOWN"
    assert diagnostic["candidate_input_tap"]["operation"]["result_status"] == "UNKNOWN"
    assert diagnostic["candidate_input_tap"]["dispatch_receipt_confirmation"]["status"] == "UNKNOWN"
    assert set(diagnostic["candidate_input_tap"]["dispatch_receipt_confirmation"]["native_receipt"].values()) == {
        "UNKNOWN",
    }
    assert diagnostic["pre_post_observations"] == {
        "status": "UNKNOWN", "pre": "UNKNOWN", "post": "UNKNOWN",
    }


def test_candidate_operation_correlation_does_not_imply_receipt_confirmation():
    tracker, _ = _record_production_entry()
    action = tracker.provenance["entry_operation"]
    action["native_receipt_status"] = "MATCHED"
    action["native_receipt"] = {"operation_id": action["operation_id"]}
    action["dispatch_status"] = "DISPATCHED"

    correlation = tracker.diagnostic_snapshot()["candidate_input_tap"]
    confirmation = correlation["dispatch_receipt_confirmation"]

    assert correlation["status"] == "CANDIDATE_OPERATION_CORRELATED"
    assert confirmation["status"] == "UNKNOWN"
    assert confirmation["dispatch_status"] == "DISPATCHED"
    assert confirmation["native_receipt"]["operation_id"] == confirmation["operation_id"]
    assert confirmation["native_receipt"]["action_type"] == "UNKNOWN"
    assert confirmation["native_receipt"]["native_boundary_status"] == "UNKNOWN"
    assert confirmation["native_receipt"]["dispatch_status"] == "UNKNOWN"
    assert confirmation["native_receipt"]["receipt_seq"] == "UNKNOWN"


def test_entry_abort_after_tap_preserves_pre_observation_and_unknown_post():
    tracker, _ = _record_production_entry()

    diagnostic = tracker.diagnostic_snapshot()
    observations = diagnostic["pre_post_observations"]

    assert observations["status"] == "PARTIAL"
    assert observations["pre"]["diagnostic_only"] is True
    assert observations["pre"]["package"] == "UNKNOWN"
    assert observations["pre"]["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED"
    assert observations["post"] == "UNKNOWN"


def test_scroll_target_inventory_is_bounded_and_diagnostic_only():
    inventory = scroll_target_inventory([
        {
            "className": "androidx.recyclerview.widget.RecyclerView",
            "resourceId": "com.example:id/device_list",
            "boundsInScreen": "[0,100][600,900]",
            "scrollable": True,
            "actions": ["SCROLL_FORWARD"],
        },
        {"className": "android.widget.TextView", "text": "Card"},
    ])

    assert len(inventory) == 1
    assert inventory[0]["resource_id"] == "com.example:id/device_list"
    assert inventory[0]["bounds"] == "[0,100][600,900]"
    assert inventory[0]["scroll_actions"] == ["SCROLL_FORWARD"]
    assert inventory[0]["node_locator_sha256"]
    assert scroll_target_inventory([], limit=0) == []


def test_transition_wrapper_preserves_result_and_records_post_tap_context(monkeypatch):
    events = []
    tracker = SimpleNamespace(
        provenance={"entry_operation": {"operation_id": "operation-1"}},
        source_capture={},
        navigation_epoch=3,
        diagnostic_events=[],
    )

    def record_diagnostic(name, payload):
        tracker.diagnostic_events.append({"event": name, "payload": payload})
        events.append((name, payload))

    tracker.record_diagnostic = record_diagnostic
    client = SimpleNamespace(
        _phase6d3a_entity_root_tracker=tracker,
        _last_traversal_candidate_snapshot=None,
    )
    monkeypatch.setattr(
        collection_flow, "_confirm_click_focused_transition_impl",
        lambda *args, **kwargs: (False, "none"),
    )
    window_calls = []

    def capture_window(*args, **kwargs):
        window_calls.append((args, kwargs))
        return {
            "sample_status": "CAPTURED",
            "foreground_package": "com.example.plugin",
            "foreground_activity_component": "com.example.plugin/.MainActivity",
        }

    monkeypatch.setattr(collection_flow, "capture_entry_window_diagnostic", capture_window)

    result = collection_flow._confirm_click_focused_transition(
        client, "serial", {"scenario_id": "plugin"},
        transition_fast_path=True, baseline_nodes=[{"text": "Device list"}],
    )

    assert result == (False, "none")
    assert events[0][0] == "post_tap_transition"
    assert events[0][1]["plugin_context_transition"]["foreground_activity_component"] == (
        "com.example.plugin/.MainActivity"
    )
    assert events[0][1]["plugin_context_transition"]["navigation_epoch"] == 3
    assert events[0][1]["operation_id"] == "operation-1"
    assert events[0][1]["pre_observation"]["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED"
    assert events[0][1]["post_observation"]["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED"
    assert events[0][1]["pre_observation"]["activity_component"] == "UNKNOWN"
    assert events[0][1]["post_observation"]["root"] == "UNKNOWN"

    second_result = collection_flow._confirm_click_focused_transition(
        client, "serial", {"scenario_id": "plugin"},
        transition_fast_path=True, baseline_nodes=[{"text": "Device list"}],
    )
    assert second_result == result
    assert len(window_calls) == 1
    assert len(events) == 1


def test_transition_event_does_not_correlate_incomplete_candidate(monkeypatch):
    tracker, _ = _record_production_entry()
    tracker.provenance["selected_entity"]["status"] = "INCOMPLETE"
    client = _EntryClient(_selected_node())
    client._phase6d3a_entity_root_tracker = tracker
    monkeypatch.setattr(
        collection_flow, "_confirm_click_focused_transition_impl",
        lambda *args, **kwargs: (False, "source_list_context"),
    )
    monkeypatch.setattr(
        collection_flow, "capture_entry_window_diagnostic",
        lambda *args, **kwargs: {"sample_status": "UNKNOWN"},
    )

    result = collection_flow._confirm_click_focused_transition(
        client, "serial", {"scenario_id": "plugin"},
        transition_fast_path=True, baseline_nodes=[{"text": "Device list"}],
    )

    assert result == (False, "source_list_context")
    transition = next(event["payload"] for event in reversed(tracker.diagnostic_events)
                      if event["event"] == "post_tap_transition")
    assert transition["candidate_input_tap"]["status"] == "UNKNOWN"
    assert transition["candidate_input_tap"]["dispatch_receipt_confirmation"]["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("transition_result", "expected_status"),
    [
        ((True, "no_expected_signal_configured"), "SKIPPED_NOT_CONFIGURED"),
        ((False, "none"), "NOT_CONFIRMED"),
    ],
    ids=["signal-skipped", "stale-pre-tap-snapshot"],
)
def test_transition_wrapper_never_promotes_pre_tap_snapshot(
    monkeypatch, transition_result, expected_status,
):
    node = _selected_node()
    source_client = _EntryClient(node)
    stale_snapshot = source_client._last_traversal_candidate_snapshot
    source_capture = source_capture_evidence(source_client, [node])
    provenance = {"entry_operation": {"operation_id": "operation-stale"}}
    attempts = [{"attempt": 1, "status": "UNCHANGED"}]
    tracker = SimpleNamespace(
        provenance=deepcopy(provenance),
        source_capture=deepcopy(source_capture),
        navigation_epoch=7,
        entry_attempts=deepcopy(attempts),
        diagnostic_events=[],
    )
    events = []

    def record_diagnostic(name, payload):
        tracker.diagnostic_events.append({"event": name, "payload": payload})
        events.append((name, payload))

    tracker.record_diagnostic = record_diagnostic
    dispatch_calls = []
    redirect_state = {"redirect": "unchanged"}
    visit_state = {"visit": "unchanged"}
    client = SimpleNamespace(
        _phase6d3a_entity_root_tracker=tracker,
        _last_traversal_candidate_snapshot=stale_snapshot,
        _phase6d3a_redirect_context=redirect_state,
        _phase6d3a_visit_state=visit_state,
        tap_xy_adb=lambda **kwargs: dispatch_calls.append(kwargs) or True,
    )
    provenance_before = deepcopy(tracker.provenance)
    source_capture_before = deepcopy(tracker.source_capture)
    attempts_before = deepcopy(tracker.entry_attempts)
    monkeypatch.setattr(
        collection_flow, "_confirm_click_focused_transition_impl",
        lambda *args, **kwargs: transition_result,
    )
    monkeypatch.setattr(
        collection_flow, "capture_entry_window_diagnostic",
        lambda *args, **kwargs: {"sample_status": "NOT_REQUESTED_IN_TEST"},
    )

    result = collection_flow._confirm_click_focused_transition(
        client, "serial", {"scenario_id": "plugin"},
        transition_fast_path=True, baseline_nodes=[deepcopy(node)],
    )

    assert result == transition_result
    assert events[0][0] == "post_tap_transition"
    payload = events[0][1]
    assert payload["transition_verification_status"] == expected_status
    assert payload["transition_confirmed"] is False
    capture = payload["source_list_context"]
    assert capture["post_tap_capture_status"] == "UNAVAILABLE_UNPROVEN"
    assert capture["post_tap_capture_id"] is None
    assert capture["post_tap_capture_complete"] is False
    assert capture["comparison_available"] is False
    assert capture["baseline_node_status"] == "AVAILABLE"
    assert capture["baseline_node_count"] == 1
    assert capture["post_tap_node_status"] == "UNAVAILABLE_UNPROVEN"
    assert capture["post_tap_candidate_node_count"] == "UNKNOWN"
    assert capture["post_tap_nodes_used_for_comparison"] == 0
    assert capture["comparison_unavailable_reason"] == "POST_TAP_CAPTURE_UNAVAILABLE_UNPROVEN"
    assert payload["transition_classifier_result"] == expected_status
    assert payload["transition_classifier_reason"] == transition_result[1]
    assert payload["scroll_target_inventory"] == []
    assert payload["plugin_context_transition"]["post_tap_hierarchy_package"] == ""
    source_root = payload["source_hierarchy_capture"]
    assert source_root["capture_status"] == "CAPTURED_COMPLETE"
    assert source_root["request_id"] == source_capture["hierarchy_request_id"]
    assert source_root["package_name"] == source_capture["capture_authority"].get(
        "hierarchy_package_name"
    )
    if source_root["package_name"] is None:
        assert source_root["package_unavailable_reason"]
    assert source_root["root"]["root_ref"]
    assert payload["post_tap_hierarchy_capture"]["capture_status"] == "UNAVAILABLE_UNPROVEN"
    assert payload["post_tap_hierarchy_capture"]["capture_id"] is None
    assert payload["post_tap_hierarchy_capture"]["root"] is None
    assert payload["post_tap_hierarchy_capture"]["activity_unavailable_reason"]
    assert payload["source_list_context"]["tap_operation_started_at"] is None
    assert payload["source_list_context"]["tap_operation_time_status"] == (
        "UNAVAILABLE_NOT_RECORDED"
    )
    assert payload["source_list_context"]["transition_finished_at"]
    assert payload["source_list_context"]["tap_operation_finished_at"] == "UNKNOWN"
    assert payload["pre_observation"]["navigation_epoch"] == "UNKNOWN"
    assert payload["post_observation"]["navigation_epoch"] == 7
    assert payload["post_observation"]["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED"
    assert tracker.provenance == provenance_before
    assert tracker.source_capture == source_capture_before
    assert tracker.entry_attempts == attempts_before
    assert tracker.navigation_epoch == 7
    assert client._phase6d3a_redirect_context is redirect_state
    assert client._phase6d3a_visit_state is visit_state
    assert dispatch_calls == []


def test_capture_completeness_diagnostic_preserves_unknown_and_explicit_false():
    assert collection_flow._phase6d3a_capture_completeness_diagnostic({}) == {
        "status": "UNKNOWN",
        "value": None,
        "unavailable_reason": "FIELD_NOT_RECORDED",
    }
    assert collection_flow._phase6d3a_capture_completeness_diagnostic(
        {"capture_complete": False}
    ) == {
        "status": "OBSERVED",
        "value": False,
        "unavailable_reason": None,
    }
    assert collection_flow._phase6d3a_capture_completeness_diagnostic(
        {"capture_complete": "false"}
    ) == {
        "status": "UNKNOWN",
        "value": None,
        "unavailable_reason": "INVALID_FIELD_TYPE",
    }


def test_transition_wrapper_binds_unknown_baseline_reason_to_source_capture(monkeypatch):
    source_capture = {
        "hierarchy_capture_id": "capture-baseline-source",
        "hierarchy_request_id": "request-baseline-source",
        "hierarchy_capture_sequence": 12,
        "captured_at": "2026-10-27T00:00:00.000Z",
        "capture_authority": {
            "root_ref": "root-baseline-source",
            "root_digest": "digest-baseline-source",
        },
    }
    tracker = SimpleNamespace(
        provenance={"entry_operation": {"operation_id": "operation-baseline-unknown"}},
        source_capture=deepcopy(source_capture),
        navigation_epoch=5,
        diagnostic_events=[],
    )
    tracker.record_diagnostic = lambda name, payload: tracker.diagnostic_events.append(
        {"event": name, "payload": payload}
    )
    client = SimpleNamespace(
        _phase6d3a_entity_root_tracker=tracker,
        _last_traversal_candidate_snapshot=None,
    )
    monkeypatch.setattr(
        collection_flow, "_confirm_click_focused_transition_impl",
        lambda *args, **kwargs: (False, "source_list_context"),
    )
    monkeypatch.setattr(
        collection_flow, "capture_entry_window_diagnostic",
        lambda *_args, **_kwargs: {"sample_status": "UNKNOWN"},
    )

    result = collection_flow._confirm_click_focused_transition(
        client, "serial", {"scenario_id": "plugin"},
        transition_fast_path=True, baseline_nodes=None,
    )

    assert result == (False, "source_list_context")
    payload = tracker.diagnostic_events[-1]["payload"]
    context = payload["source_list_context"]
    assert context["baseline_node_status"] == "UNKNOWN"
    assert context["baseline_node_count"] == "UNKNOWN"
    assert context["baseline_node_reason"] == (
        "BASELINE_NODES_ARGUMENT_NOT_PROVIDED_TO_DIAGNOSTIC_WRAPPER"
    )
    binding = context["baseline_source_capture_binding"]
    assert binding["status"] == "OBSERVED"
    assert binding["capture_id"] == "capture-baseline-source"
    assert binding["request_id"] == "request-baseline-source"
    assert binding["capture_complete"] is None
    assert binding["capture_complete_status"] == "UNKNOWN"
    assert binding["capture_complete_unavailable_reason"] == "FIELD_NOT_RECORDED"
    assert binding["root_ref"] == "root-baseline-source"
    assert binding["relationship_to_baseline_nodes"] == (
        "REFERENCE_ONLY_SOURCE_RELATION_NOT_PROVEN"
    )
    assert tracker.provenance["entry_operation"]["operation_id"] == (
        "operation-baseline-unknown"
    )


def test_all_devices_wrapper_records_timing_without_changing_result(monkeypatch):
    events = []
    tracker = SimpleNamespace(
        source_capture={
            "hierarchy_capture_id": "capture-all-devices-input",
            "hierarchy_request_id": "request-all-devices-input",
            "capture_complete": True,
            "capture_authority": {
                "root_ref": "root-all-devices-input",
                "root_digest": "digest-all-devices-input",
            },
        },
        diagnostic_events=[],
        record_diagnostic=lambda name, payload: (
            tracker.diagnostic_events.append({"event": name, "payload": payload}),
            events.append((name, payload)),
        ),
    )
    client = SimpleNamespace(
        _phase6d3a_entity_root_tracker=tracker,
        last_device_tab_context_verified=True,
    )
    nodes = [{
        "viewIdResourceName": "com.example:id/all_devices_location",
        "className": "android.widget.TextView",
        "boundsInScreen": "[0,0][200,80]",
        "text": "All devices",
        "clickable": True,
        "visibleToUser": True,
    }]
    expected = (True, nodes, "all_devices_selected")
    monkeypatch.setattr(
        collection_flow, "_ensure_all_devices_location_selected_impl",
        lambda *args, **kwargs: expected,
    )

    result = collection_flow._ensure_all_devices_location_selected(
        client, "serial", nodes, lambda **kwargs: nodes, step_wait_seconds=0,
    )

    assert result is expected
    selection_event = next(e for e in events if e[0] == "all_devices_location_selection")
    assert {name for name, _ in events} == {"all_devices_impl_input", "all_devices_location_selection"}
    assert selection_event[1]["elapsed_ms"] >= 0
    assert selection_event[1]["decision"] == "VERIFIED_SELECTED"
    assert selection_event[1]["reason"] == "all_devices_selected"
    assert selection_event[1]["result_status"] == "OBSERVED"
    assert selection_event[1]["input_tap"]["status"] == "UNKNOWN"
    lookup = selection_event[1]["lookup_input_inventory"]
    assert lookup["diagnostic_only"] is True
    assert lookup["hierarchy_nodes"] == {"status": "AVAILABLE", "count": 1}
    assert lookup["source_capture_binding"]["capture_id"] == "capture-all-devices-input"
    assert lookup["source_capture_binding"]["request_id"] == "request-all-devices-input"
    assert lookup["source_capture_binding"]["capture_complete"] is True
    assert lookup["source_capture_binding"]["capture_complete_status"] == "OBSERVED"
    assert lookup["source_capture_binding"]["capture_complete_unavailable_reason"] is None
    assert lookup["source_capture_binding"]["relationship_to_lookup_nodes"] == (
        "REFERENCE_ONLY_NODE_RELATION_NOT_PROVEN"
    )
    assert lookup["hierarchy_lookup_mirror"]["scope"] == (
        "INPUT_NODES_ONLY_DIAGNOSTIC_MIRROR"
    )
    assert lookup["hierarchy_lookup_mirror"]["candidate_status"] == "AVAILABLE"
    assert lookup["hierarchy_lookup_mirror"]["candidate"]["resource_id"] == (
        "com.example:id/all_devices_location"
    )
    assert lookup["device_tab_context_verified"] is True
    assert lookup["dump_tree_available"] is True
    assert selection_event[1]["source_list_context"]["started_at"] == selection_event[1]["started_at"]
    assert selection_event[1]["source_list_context"]["finished_at"] == selection_event[1]["finished_at"]
    assert selection_event[1]["pre_observation"]["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED"
    assert selection_event[1]["post_observation"]["activity_component"] == "UNKNOWN"


def test_candidate_pre_observation_failure_does_not_suppress_tap(monkeypatch):
    node = _selected_node()
    client = _EntryClient(node)
    tracker = PluginEntryProvenanceTracker("device_air_purifier_plugin")
    client._phase6d3a_entity_root_tracker = tracker
    candidate = {
        "node": node, "label": "Air Purifier", "stable_label": "Air Purifier",
        "rid": node["viewIdResourceName"], "bounds": "0,0,600,600",
    }
    calls = []

    def failing_observation(*_args, **_kwargs):
        raise RuntimeError("diagnostic observation unavailable")

    monkeypatch.setattr(collection_flow, "_phase6d3a_observed_context", failing_observation)
    monkeypatch.setattr(client, "tap_xy_adb", lambda **kwargs: calls.append(kwargs) or True)

    result = collection_flow._tap_device_candidate_center(
        client, "serial", candidate, reason="test_candidate",
    )

    assert result is True
    assert len(calls) == 1
    assert calls[0]["x"] == 300 and calls[0]["y"] == 300


def test_card_pre_observation_failure_does_not_suppress_tap(monkeypatch):
    node = _selected_node()
    nodes = [node]
    client = _EntryClient(node)
    tracker = PluginEntryProvenanceTracker("device_air_purifier_plugin")
    tracker.record_source_capture(source_capture_evidence(client, nodes))
    client._phase6d3a_entity_root_tracker = tracker
    calls = []
    original_tap = client.tap_xy_adb

    def counted_tap(**kwargs):
        calls.append(kwargs)
        return original_tap(**kwargs)

    def failing_observation(*_args, **_kwargs):
        raise RuntimeError("diagnostic observation unavailable")

    monkeypatch.setattr(collection_flow, "_phase6d3a_observed_context", failing_observation)
    monkeypatch.setattr(client, "tap_xy_adb", counted_tap)

    result = collection_flow._tap_device_card_with_provenance(
        client, "serial", {
            "node": node, "label": "Air Purifier", "stable_label": "Air Purifier",
            "rid": node["viewIdResourceName"], "bounds": "0,0,600,600",
        }, client.tap_xy_adb, x=300, y=300, selected_bounds="0,0,600,600", source_nodes=nodes,
    )

    assert result is True
    assert len(calls) == 1


def test_all_devices_copy_failure_does_not_suppress_selection(monkeypatch):
    class UncopyableDict(dict):
        def __deepcopy__(self, _memo):
            raise RuntimeError("diagnostic copy unavailable")

    events = []
    tracker = SimpleNamespace(
        source_capture=UncopyableDict(), navigation_epoch=0, diagnostic_events=[],
        record_diagnostic=lambda name, payload: events.append((name, payload)),
    )
    client = SimpleNamespace(_phase6d3a_entity_root_tracker=tracker)
    calls = []
    expected = (True, [], "all_devices_selected")

    def select_once(*_args, **_kwargs):
        calls.append("selected")
        return expected

    monkeypatch.setattr(collection_flow, "_ensure_all_devices_location_selected_impl", select_once)

    result = collection_flow._ensure_all_devices_location_selected(
        client, "serial", [], lambda **kwargs: [], step_wait_seconds=0,
    )

    assert result is expected
    assert calls == ["selected"]


def test_all_devices_tap_correlates_candidate_coordinates_receipt_and_result(monkeypatch):
    node = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/all_devices_location",
        "className": "android.widget.TextView", "boundsInScreen": "[0,0][200,80]",
        "text": "All devices", "clickable": True, "visibleToUser": True,
    }
    nodes = [node]
    client = _EntryClient(node)
    tracker = PluginEntryProvenanceTracker("device_air_purifier_plugin")
    tracker.record_source_capture(source_capture_evidence(client, nodes))
    client._phase6d3a_entity_root_tracker = tracker
    client.last_entry_source_window = "com.samsung.android.oneconnect/.DevicesActivity"
    monkeypatch.setattr(collection_flow, "capture_entry_window_diagnostic", lambda *_: {
        "diagnostic_only": True, "sample_status": "CAPTURED",
        "foreground_package": "com.samsung.android.oneconnect",
        "foreground_activity_component": "com.samsung.android.oneconnect/.DevicesActivity",
        "focused_window_component": "com.samsung.android.oneconnect/.DevicesActivity",
    })

    candidate = {
        "node": node, "label": "All devices", "stable_label": "All devices",
        "rid": node["viewIdResourceName"], "bounds": "0,0,200,80",
    }

    def select_all_devices(client_arg, _dev, source_nodes, _dump_tree_fn, **_kwargs):
        assert collection_flow._tap_device_candidate_center(
            client_arg, "serial", candidate, reason="select_all_devices",
        )
        return True, source_nodes, "all_devices_selected"

    monkeypatch.setattr(
        collection_flow, "_ensure_all_devices_location_selected_impl", select_all_devices,
    )
    result = collection_flow._ensure_all_devices_location_selected(
        client, "serial", nodes, lambda **_kwargs: nodes, step_wait_seconds=0,
    )

    assert result == (True, nodes, "all_devices_selected")
    selection = next(event["payload"] for event in reversed(tracker.diagnostic_events)
                     if event["event"] == "all_devices_location_selection")
    tap = selection["input_tap"]
    operation = tap["operation"]
    assert tap["candidate"]["label"] == "All devices"
    assert tap["coordinates"]["x"] == 100 and tap["coordinates"]["y"] == 40
    assert operation["action_type"] == "INPUT_TAP"
    assert operation["operation_id"] == tap["operation_id"]
    assert operation["native_receipt_status"] == "MATCHED"
    assert operation["native_receipt"]["operation_id"] == operation["operation_id"]
    assert operation["dispatch_result_status"] == "CALL_RETURNED_TRUE"
    assert selection["source_list_context"]["tap_operation_started_at"] == operation["operation_started_at"]
    assert selection["source_list_context"]["tap_operation_finished_at"] == operation["operation_finished_at"]
    assert selection["pre_observation"]["package"] == "com.samsung.android.oneconnect"
    assert selection["post_observation"]["activity_component"] == (
        "com.samsung.android.oneconnect/.DevicesActivity"
    )
    assert selection["pre_observation"]["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED"
    assert selection["post_observation"]["currentness_status"] == "UNKNOWN_NOT_ESTABLISHED"


def test_entry_diagnostics_row_attachment_includes_existing_recovery_decision():
    tracker = SimpleNamespace(
        diagnostic_snapshot=lambda: {
            "schema_version": "phase6d3a-entry-diagnostics-v1",
            "diagnostic_only": True,
        },
    )
    client = SimpleNamespace(
        _phase6d3a_entity_root_tracker=tracker,
        last_start_open_summary={
            "start_state_verified": False,
            "start_state_recovery_reason": "start_screen_not_ready",
        },
        last_recoverable_precondition={"outcome": "FAILED", "reason": "target_missing"},
    )
    row = {}

    result = collection_flow._phase6d3a_attach_entry_diagnostics(client, row)

    assert result["recovery_decision"]["start_state_verified"] is False
    assert result["recovery_decision"]["start_state_reason"] == "start_screen_not_ready"
    assert result["recovery_decision"]["recoverable_precondition"]["reason"] == "target_missing"
    assert result["recovery_decision"]["recovery_target"]["status"] == "UNKNOWN"
    assert result["recovery_decision"]["recovery_result"]["status"] == "OBSERVED"
    assert row["phase6d3a_entry_diagnostics"] == result


def test_entry_diagnostics_exposes_bounded_recovery_target_and_result():
    tracker = SimpleNamespace(diagnostic_snapshot=lambda: {"diagnostic_only": True})
    client = SimpleNamespace(
        _phase6d3a_entity_root_tracker=tracker,
        last_recoverable_precondition={"outcome": "RECOVERED_STABLE", "reason": "stable_normal_state"},
        last_recoverable_precondition_target={
            "viewIdResourceName": "com.example:id/retry", "className": "android.widget.Button",
            "boundsInScreen": "[1,2][30,40]", "text": "Retry",
        },
        last_recoverable_precondition_attempt_result={
            "outcome": "RECOVERED_STABLE", "detected": True, "attempted": True,
            "attempt_count": 1, "reason": "stable_normal_state", "action_dispatched": True,
            "initial_observation": {
                "target_present": True, "target_visible": True,
                "target_resource_id": "com.example:id/air_purifier",
                "error_resource_ids": ["com.example:id/error"],
                "visible_text": "ignored from bounded diagnostic result",
            },
        },
    )

    result = collection_flow._phase6d3a_attach_entry_diagnostics(client)
    recovery = result["recovery_decision"]

    assert recovery["recovery_target"] == {
        "status": "OBSERVED", "resource_id": "com.example:id/retry",
        "class_name": "android.widget.Button", "bounds": "[1,2][30,40]",
    }
    assert recovery["recovery_result"]["status"] == "OBSERVED"
    assert recovery["recovery_result"]["outcome"] == "RECOVERED_STABLE"
    assert recovery["recovery_result"]["initial_observation"]["error_resource_ids"] == [
        "com.example:id/error",
    ]
    assert "visible_text" not in recovery["recovery_result"]["initial_observation"]


def test_entry_recovery_scroll_uses_nonempty_existing_target_evidence():
    client = SimpleNamespace(
        _phase6d3a_entity_root_tracker=SimpleNamespace(
            diagnostic_events=[],
            record_diagnostic=lambda name, payload: client._phase6d3a_entity_root_tracker.diagnostic_events.append(
                {"event": name, "payload": payload}
            ),
        ),
    )
    inputs = {
        "status": "OBSERVED_INPUTS",
        "top_evidence_observations": [{
            "anchor": "Air Purifier",
            "anchor_resource_id": "com.example:id/device_name",
            "anchor_bounds": "1,2,30,40",
        }],
    }
    collection_flow._phase6d3a_record_entry_recovery_scroll(
        client,
        started_at="start",
        finished_at="finish",
        decision="VERIFIED_TOP",
        reason="reached_top",
        result={
            "reached_top": True,
            "reason": "verified_top",
            "anchor": None,
            "anchor_resource_id": "",
            "anchor_bounds": " ",
        },
        before={},
        after={},
        target_selection_inputs=inputs,
    )
    selection = client._phase6d3a_entity_root_tracker.diagnostic_events[-1]["payload"][
        "target_selection"
    ]
    assert selection["resolved_target_status"] == "OBSERVED"
    assert selection["resolved_target_source"] == "TOP_EVIDENCE_CALLBACK"
    assert selection["resolved_target"] == {
        "anchor": "Air Purifier",
        "anchor_resource_id": "com.example:id/device_name",
        "anchor_bounds": "1,2,30,40",
    }


def test_precollection_entry_diagnostics_are_emitted_to_evidence_ledger():
    events = []

    class Runtime:
        is_enabled = True

        def emit(self, event_type, **kwargs):
            events.append((event_type, kwargs))

    diagnostics = {
        "schema_version": "phase6d3a-entry-diagnostics-v1",
        "diagnostic_only": True,
        "entry_operation": {"operation_id": "tap-operation", "action_type": "INPUT_TAP"},
        "events": [{"event": "post_tap_transition", "payload": {
            "post_tap_capture_status": "UNAVAILABLE_UNPROVEN",
        }}],
    }

    emitted = collection_flow._phase6d3a_emit_entry_diagnostics(
        Runtime(), diagnostics, "device_list_top_unverified:scroll_failed",
    )

    assert emitted is True
    assert events[0][0] == "PHASE6D3A_ENTRY_DIAGNOSTICS"
    payload = events[0][1]["payload"]
    assert payload["diagnostic_only"] is True
    assert payload["terminal_reason"] == "device_list_top_unverified:scroll_failed"
    assert payload["diagnostics"] == diagnostics


def test_precollection_diagnostic_emit_failure_does_not_gate_existing_result():
    class Runtime:
        is_enabled = True

        def emit(self, *_args, **_kwargs):
            raise OSError("ledger unavailable")

    assert collection_flow._phase6d3a_emit_entry_diagnostics(
        Runtime(), {"diagnostic_only": True}, "anchor_abort",
    ) is False


def test_entry_recovery_scroll_records_existing_roots_targets_and_result():
    node = _selected_node()
    node["scrollable"] = True
    node["actions"] = ["SCROLL_BACKWARD"]
    nodes = [node]
    client = _EntryClient(node)
    tracker = PluginEntryProvenanceTracker("device_air_purifier_plugin")
    tracker.record_source_capture(source_capture_evidence(client, nodes))
    client._phase6d3a_entity_root_tracker = tracker
    before = collection_flow._phase6d3a_entry_scroll_capture(client, nodes)
    result = {
        "reached_top": False,
        "reason": "scroll_failed",
        "swipes": 2,
        "anchor": None,
        "anchor_resource_id": "",
        "anchor_bounds": "   ",
    }

    target_inputs = collection_flow._phase6d3a_entry_recovery_target_selection_inputs(
        nodes=nodes,
        source_capture=before,
        location_state={
            "selected": False,
            "reason": "all_devices_not_found",
            "candidate": None,
        },
        top_anchor_labels=["Air Purifier"],
        max_swipes_configured=5,
        top_evidence_observations=[{
            "ok": False, "reason": "top_anchor_not_visible",
            "anchor": "", "anchor_resource_id": "", "anchor_bounds": "",
        }],
    )
    collection_flow._phase6d3a_record_entry_recovery_scroll(
        client,
        started_at="2026-10-27T00:00:00.000Z",
        finished_at="2026-10-27T00:00:01.000Z",
        decision="ABORT_UNVERIFIED",
        reason="scroll_failed",
        result=result,
        before=before,
        after=before,
        target_selection_inputs=target_inputs,
    )

    event = tracker.diagnostic_events[-1]
    assert event["event"] == "entry_recovery_scroll"
    payload = event["payload"]
    assert payload["decision"] == "ABORT_UNVERIFIED"
    assert payload["reason"] == "scroll_failed"
    assert payload["result"] == result
    assert payload["before"]["hierarchy_capture"]["capture_status"] == "CAPTURED_COMPLETE"
    assert payload["before"]["hierarchy_capture"]["root"]["root_ref"]
    assert payload["before"]["scroll_targets"][0]["resource_id"] == (
        "com.samsung.android.oneconnect:id/device_card"
    )
    assert payload["after"] == payload["before"]
    selection = payload["target_selection"]
    assert selection["status"] == "OBSERVED_INPUTS"
    assert selection["inputs"]["selection_source"] == "top_anchor_stable_labels"
    assert selection["inputs"]["requested_stable_labels"] == ["Air Purifier"]
    assert selection["inputs"]["initial_hierarchy_nodes"]["capture"]["capture_id"] == (
        before["hierarchy_capture"]["capture_id"]
    )
    assert selection["inputs"]["initial_device_location"]["reason"] == "all_devices_not_found"
    assert selection["inputs"]["top_evidence_observations"][0]["reason"] == (
        "top_anchor_not_visible"
    )
    assert selection["scroll_result"]["reason"] == "scroll_failed"
    assert selection["scroll_result"]["reached_top"] is False
    assert selection["resolved_target_status"] == "NOT_RETURNED_BY_SCROLL_RESULT"
    assert selection["resolved_target_source"] == "UNKNOWN"
    assert selection["resolved_target"] is None


def test_current_selected_card_requestless_operation_receipt_and_post_entry_root_resolve_authority():
    tracker, _ = _record_production_entry(entity=False)
    raw = _mark_current_observation(_root(entity_id=None, entity_type=None))
    result = tracker.bind_current_root(
        raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["root_authority"] == "ENTRY_TRANSACTION_RESOLVED"
    assert result["entry_operation"]["native_receipt_status"] == "MATCHED"
    assert result["entry_operation"]["request_id"] is None
    assert result["entry_operation"]["request_id_status"] == "ADB_INPUT_TAP_HAS_NO_REQUEST_ID"
    assert result["entry_operation"]["action_id"] == result["entry_operation"]["operation_id"]
    assert result["entry_operation"]["checkpoint_operation_id"] == result["entry_operation"]["operation_id"]
    assert result["entry_operation"]["receipt_checkpoint_status"] == "VALID"
    assert result["entry_operation"]["native_receipt"]["operation_id"] == result["entry_operation"]["action_id"]
    proof = result["root_authority_evidence"]
    assert proof["action_id"] == proof["operation_id"] == result["entry_operation"]["action_id"]
    assert result["resulting_root"]["entry_action_id"] == proof["action_id"]
    assert result["resulting_root"]["entry_operation_id"] == proof["operation_id"]
    assert proof["invocation_id"] == result["entry_operation"]["invocation_id"]
    assert proof["invocation_id"] == result["selected_entity"]["source_invocation_id"]
    assert proof["invocation_id"] == raw["invocation_id"] == "scenario-tx-current"
    assert proof["invocation_id"] != raw["scenario_run_id"]
    assert proof["source_captured_at"] == result["selected_entity"]["source_capture_time"]
    assert proof["operation_started_at"] == result["entry_operation"]["operation_started_at"]
    assert proof["operation_finished_at"] == result["entry_operation"]["operation_finished_at"]
    assert proof["result_captured_at"] == raw["timestamp"]
    assert result["resulting_root"]["capture_status"] == "CURRENT_COMPLETE"
    assert root_authority_is_current(result, raw)


def test_current_root_consumer_rejects_action_id_mismatch():
    tracker, _ = _record_production_entry(entity=False)
    raw = _mark_current_observation(_root(entity_id=None, entity_type=None))
    result = tracker.bind_current_root(
        raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    result["entry_operation"]["action_id"] = "foreign-action"

    assert result["root_authority"] == "ENTRY_TRANSACTION_RESOLVED"
    assert not root_authority_is_current(result, raw)


def test_current_root_consumer_rejects_root_action_id_mismatch():
    tracker, _ = _record_production_entry(entity=False)
    raw = _mark_current_observation(_root(entity_id=None, entity_type=None))
    result = tracker.bind_current_root(
        raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    result["resulting_root"]["entry_action_id"] = "foreign-action"

    assert result["root_authority"] == "ENTRY_TRANSACTION_RESOLVED"
    assert not root_authority_is_current(result, raw)


def test_semantic_component_identity_stays_unknown_when_transaction_is_resolved():
    tracker, _ = _record_production_entry(entity=False)
    raw = _mark_current_observation(_root(entity_id=None, entity_type=None))
    result = tracker.bind_current_root(
        raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["root_authority"] == "ENTRY_TRANSACTION_RESOLVED"
    assert result["semantic_component_identity"] == "UNKNOWN"
    assert result["link_status"] == "PARTIAL_LINK"
    assert root_authority_is_current(result, raw)


def test_stale_entry_receipt_is_rejected_for_transaction_authority():
    tracker, _ = _record_production_entry()
    action = tracker.provenance["entry_operation"]
    action["receipt_watermark_before"] = action["receipt_sequence"]

    result = tracker.bind_current_root(
        _root(), run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["root_authority"] == "UNKNOWN"
    assert "STALE_ENTRY_OPERATION_RECEIPT" in result["root_authority_evidence"]["reason_codes"]


@pytest.mark.parametrize(("field", "value"), [
    ("action_id", "foreign-action"),
    ("operation_id", "foreign-operation"),
    ("request_id", "unexpected-request"),
])
def test_action_operation_or_supplied_request_mismatch_rejects_transaction_authority(field, value):
    tracker, _ = _record_production_entry()
    tracker.provenance["entry_operation"][field] = value

    result = tracker.bind_current_root(
        _root(), run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["root_authority"] == "UNKNOWN"
    assert "ENTRY_OPERATION_RECEIPT_MISMATCH" in result["root_authority_evidence"]["reason_codes"]


@pytest.mark.parametrize("stale_axis", ["same_generation", "non_advancing_sequence"])
def test_stale_or_ambiguous_capture_generation_rejects_transaction_authority(stale_axis):
    tracker, _ = _record_production_entry()
    source = tracker.provenance["selected_entity"]["source_capture_authority"]
    generation = source["generation"] if stale_axis == "same_generation" else source["generation"] + 1
    sequence = 5 if stale_axis == "same_generation" else source["capture_sequence"]
    raw = attach_capture_authority(
        _root(), sequence=sequence, request_id="root-request", generation=generation,
    )

    result = tracker.bind_current_root(
        raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["root_authority"] == "UNKNOWN"
    assert "POST_ENTRY_GENERATION_UNCLEAR_OR_NOT_DISTINCT" in result["root_authority_evidence"]["reason_codes"]


def test_intervening_navigation_rejects_transaction_authority():
    tracker, _ = _record_production_entry()
    tracker.invalidate()

    result = tracker.bind_current_root(
        _root(), run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["root_authority"] == "UNKNOWN"
    assert "ENTRY_NAVIGATION_GENERATION_UNCLEAR_OR_INTERVENED" in result["root_authority_evidence"]["reason_codes"]


def test_unrelated_tab_anchor_miss_does_not_reject_current_plugin_body_authority():
    tracker, _ = _record_production_entry()
    summary = _transition(tracker.snapshot("run-current"))
    summary["anchor_matched"] = False
    # Normal production initializes this legacy Phase5B-only flag false. The
    # current root capture carries its own plugin-body anchor evidence.
    summary["plugin_open_verified"] = False

    result = tracker.bind_current_root(
        _root(), run_id="run-current", summary=summary, capture_current=True,
    )

    assert result["root_authority"] == "ENTRY_TRANSACTION_RESOLVED"
    assert result["root_authority_evidence"]["plugin_body_anchor_verified"] is True
    assert result["root_authority_evidence"]["entry_transition_confirmed"] is True
    assert result["root_authority_evidence"]["plugin_body_anchor_evidence"]["capture_id"] == (
        result["resulting_root"]["capture_id"]
    )


def test_missing_current_plugin_body_anchor_rejects_transaction_authority():
    tracker, _ = _record_production_entry()
    result = tracker.bind_current_root(
        _root(plugin_body=False), run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["root_authority"] == "UNKNOWN"
    assert "ENTRY_TRANSITION_UNCONFIRMED" in result["root_authority_evidence"]["reason_codes"]
    assert result["root_authority_evidence"]["plugin_body_anchor_verified"] is False
    assert result["root_authority_evidence"]["plugin_body_anchor_evidence"]["status"] == "MISSING"


def test_explicit_non_plugin_post_open_state_remains_fail_closed():
    tracker, _ = _record_production_entry()
    summary = _transition(tracker.snapshot("run-current"))
    summary["post_open_state"] = "SOURCE_LIST_CONTEXT"

    result = tracker.bind_current_root(
        _root(), run_id="run-current", summary=summary, capture_current=True,
    )

    assert result["root_authority"] == "UNKNOWN"
    assert result["root_authority_evidence"]["plugin_body_anchor_verified"] is False
    assert "ENTRY_TRANSITION_UNCONFIRMED" in result["root_authority_evidence"]["reason_codes"]


def test_future_semantic_identity_outcome_does_not_control_transaction_authority():
    tracker, _ = _record_production_entry()
    raw = _mark_current_observation(_root(entity_id="runtime-tv-3", entity_type="TELEVISION"))
    result = tracker.bind_current_root(
        raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["link_status"] == "CONTRADICTORY"
    assert result["semantic_component_identity"] == "UNKNOWN"
    assert result["root_authority"] == "ENTRY_TRANSACTION_RESOLVED"
    assert root_authority_is_current(result, raw)


def test_transaction_authority_never_fabricates_semantic_identity():
    tracker, _ = _record_production_entry(entity=False)
    raw = _mark_current_observation(_root(entity_id=None, entity_type=None))
    result = tracker.bind_current_root(
        raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["semantic_component_identity"] == "UNKNOWN"
    assert result["selected_entity"]["runtime_entity_references"] == []
    assert result["resulting_root"]["runtime_entity_references"] == []
    assert result["resulting_root"]["runtime_entity_types"] == []
    assert "runtime-purifier-7" not in repr(result)


def test_resolved_transaction_proof_does_not_grant_visit_credit():
    tracker, _ = _record_production_entry(entity=False)
    raw = _mark_current_observation(_root(entity_id=None, entity_type=None))
    result = tracker.bind_current_root(
        raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )

    assert result["root_authority"] == "ENTRY_TRANSACTION_RESOLVED"
    assert result["authority"] == "DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY"
    assert "visit_credit" not in result
    assert "reconciled_visit_instance_id" not in result


def test_prior_root_evidence_cannot_be_reused_for_a_later_capture():
    tracker, _ = _record_production_entry(entity=False)
    first_raw = _mark_current_observation(_root(entity_id=None, entity_type=None))
    first = tracker.bind_current_root(
        first_raw, run_id="run-current",
        summary=_transition(tracker.snapshot("run-current")), capture_current=True,
    )
    later_raw = _mark_current_observation(_root(
        entity_id=None, entity_type=None, request_id="later-root-request",
        generation=3, capture_id="later-composite-capture",
    ))

    assert first["root_authority"] == "ENTRY_TRANSACTION_RESOLVED"
    assert not root_authority_is_current(first, later_raw)
