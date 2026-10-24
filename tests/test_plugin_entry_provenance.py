from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from talkback_lib.native_dispatch_evidence import NativeDispatchReceiptStore
from tb_runner import collection_flow
from tb_runner.plugin_entry_provenance import (
    PluginEntryProvenanceTracker,
    selected_entity_evidence,
    source_capture_evidence,
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
        self.last_hierarchy_metadata = {
            "reqId": "source-request", "snapshotId": "source-snapshot", "captureSequence": 4,
        }
        self.last_dump_metadata = {
            "requestId": "source-request", "transportMode": "RELIABLE_FILE_PFD",
            "candidateSchemaVersion": "candidate-v2", "candidateContractVersion": "candidate-contract-v3",
        }
        self.node = node

    def tap_xy_adb(self, *, dev, x, y):
        self._adb_device.native_dispatch_receipts.observe(["shell", "input", "tap", str(x), str(y)])
        return True


def _record_production_entry(*, entity=True):
    node = _selected_node(entity=entity)
    nodes = [node]
    client = _EntryClient(node)
    tracker = PluginEntryProvenanceTracker("device_air_purifier_plugin")
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
          entity_type="AIR_PURIFIER", request_id="root-request", resource_id="shared-plugin-content"):
    node = {"resourceId": resource_id, "className": "android.widget.FrameLayout",
            "bounds": "0,0,600,2000", "visibleToUser": True}
    if entity_id is not None:
        node["device_id"] = entity_id
    if entity_type is not None:
        node["entity_type"] = entity_type
    capture_id = "current-composite-capture"
    return {
        "scenario_id": scenario,
        "scenario_run_id": run,
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
        "context_source": "window_current_focus",
        "window_evidence": {"focused_window_component": "com.samsung.android.oneconnect.webplugin.WebPluginActivity"},
        "nodes": [node],
    }


def _transition():
    return {
        "open_completed": True,
        "entry_contract_reason": "success_verified",
        "entry_contract_detail": "plugin_open_verified",
        "post_click_transition_same_screen": False,
        "post_click_transition_signal": "activity_transition",
    }


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
    result = tracker.bind_current_root(_root(), run_id="run-current", summary=_transition(), capture_current=True)
    assert result["link_status"] == "VERIFIED_LINK"
    assert result["resulting_root"]["capture_status"] == "CURRENT_COMPLETE"
    assert result["resulting_root"]["hierarchy_request_id"] != entry["selected_entity"]["source_hierarchy_request_id"]
    assert result["resulting_root"]["hierarchy_snapshot_id"] == "root-snapshot-5"
    assert result["authority"] == "DIAGNOSTIC_ONLY_NO_CONTEXT_OR_VISIT_AUTHORITY"


def test_navigation_after_entry_invalidates_link_even_when_root_is_current():
    tracker, _ = _record_production_entry()
    tracker.invalidate()
    result = tracker.bind_current_root(_root(), run_id="run-current", summary=_transition(), capture_current=True)
    assert result["link_status"] == "UNKNOWN"
    assert "NAVIGATION_EPOCH_CHANGED" in result["reason_codes"]


def test_navigation_invalidates_previously_bound_link_in_tracker_snapshot():
    tracker, _ = _record_production_entry()
    verified = tracker.bind_current_root(_root(), run_id="run-current",
                                         summary=_transition(), capture_current=True)
    assert verified["link_status"] == "VERIFIED_LINK"
    tracker.invalidate()
    current = tracker.snapshot("run-current")
    assert current["link_status"] == "UNKNOWN"
    assert "NAVIGATION_EPOCH_CHANGED" in current["reason_codes"]


def test_air_purifier_entry_does_not_link_to_tv_entity_on_shared_component():
    tracker, _ = _record_production_entry()
    result = tracker.bind_current_root(
        _root(entity_id="runtime-tv-3", entity_type="TELEVISION"),
        run_id="run-current", summary=_transition(), capture_current=True,
    )
    assert result["resulting_root"]["activity_name"].endswith("WebPluginActivity")
    assert result["link_status"] == "CONTRADICTORY"
    assert "SELECTED_ENTITY_ROOT_IDENTITY_MISMATCH" in result["reason_codes"]


@pytest.mark.parametrize("kwargs", [
    {"entity_id": None, "entity_type": None},
    {"entity_id": None, "entity_type": "AIR_PURIFIER"},
])
def test_shared_component_and_resource_overlap_do_not_verify_without_entity_identity(kwargs):
    tracker, _ = _record_production_entry(entity=False)
    result = tracker.bind_current_root(
        _root(**kwargs), run_id="run-current", summary=_transition(), capture_current=True,
    )
    assert result["link_status"] == "PARTIAL_LINK"
    assert "RUNTIME_ENTITY_OR_DESTINATION_TYPE_NOT_EXPOSED" in result["reason_codes"]


def test_config_digest_is_correlation_only_and_never_runtime_entity_identity():
    tracker, _ = _record_production_entry(entity=False)
    selected = tracker.provenance["selected_entity"]
    selected["entry_contract_digest"] = "same-config-hash"
    result = tracker.bind_current_root(
        {**_root(entity_id=None, entity_type=None), "entry_contract_digest": "same-config-hash"},
        run_id="run-current", summary=_transition(), capture_current=True,
    )
    assert result["link_status"] == "PARTIAL_LINK"
    assert result["selected_entity"].get("runtime_entity_references") == []
    assert result["resulting_root"].get("runtime_entity_references") == []


def test_generic_device_card_resource_id_alone_is_not_sufficient():
    tracker, _ = _record_production_entry(entity=False)
    result = tracker.bind_current_root(
        _root(entity_id=None, entity_type=None, resource_id="com.samsung.android.oneconnect:id/device_card"),
        run_id="run-current", summary=_transition(), capture_current=True,
    )
    assert result["link_status"] == "PARTIAL_LINK"


def test_missing_source_or_unlinked_capture_fails_closed():
    tracker, _ = _record_production_entry()
    same_request = _root(request_id="source-request")
    result = tracker.bind_current_root(same_request, run_id="run-current",
                                       summary=_transition(), capture_current=True)
    assert result["link_status"] == "UNKNOWN"
    assert "SOURCE_AND_RESULT_CAPTURE_NOT_DISTINCT" in result["reason_codes"]


def test_currentness_rejects_foreign_run_and_incomplete_result_capture():
    tracker, _ = _record_production_entry()
    foreign_run = tracker.bind_current_root(_root(run="other-run"), run_id="run-current",
                                            summary=_transition(), capture_current=True)
    assert foreign_run["link_status"] == "UNKNOWN"
    assert "RUN_MISMATCH" in foreign_run["reason_codes"]

    incomplete = _root()
    incomplete["geometry_capture_id"] = "different-capture"
    partial = tracker.bind_current_root(incomplete, run_id="run-current",
                                       summary=_transition(), capture_current=True)
    assert partial["link_status"] == "UNKNOWN"
    assert "RESULT_CAPTURE_INCOMPLETE_OR_STALE" in partial["reason_codes"]


def test_provenance_remains_diagnostic_only_and_does_not_grant_visit_or_permit():
    tracker, _ = _record_production_entry()
    result = tracker.bind_current_root(_root(), run_id="run-current",
                                       summary=_transition(), capture_current=True)
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
        "context_source": "window_current_focus",
        "nodes": [{"text": "Volume", "resourceId": "shared-plugin-content", "visibleToUser": True}],
        "observation_coverage": "OBSERVED_FULL",
    }
    monkeypatch.setattr(state_diagnostic, "capture_observation", lambda *args, **kwargs: deepcopy(raw))
    row = {"scenario_id": scenario_id, "scenario_run_id": "run-current", "step_index": 1}
    observed = collection_flow._capture_phase6d3a_production_observation(
        client=client, dev="serial", row=row,
    )
    assert observed is not None
    result = resolve_phase3_context(row["state_graph_observation"])
    assert result["status"] == "PARTIAL_CONTEXT"
    assert result["reasons"] == ["PLUGIN_BODY_EVIDENCE_INCOMPLETE"]
    assert row["state_graph_observation"]["phase3_plugin_context_evidence"]
    assert row["state_graph_observation"]["phase3_plugin_context_evidence"]["context_contract_id"]
