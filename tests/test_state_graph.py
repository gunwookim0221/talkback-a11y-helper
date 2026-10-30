from copy import deepcopy
import json
import pytest

from phase6d_capture_support import attach_capture_authority

from tb_runner.state_graph import (
    EdgeLifecycle, GraphLimits, GraphMode, GRAPH_MODE_ENV, REPLAY_SCHEMA_VERSION,
    StateGraphRecorder, VisitObservation, build_graph_state_identity,
    build_phase6e_scroll_evidence, graph_mode_from_environment, maybe_write_shadow_graph_from_rows,
    read_state_graph, recorder_from_existing_rows, replay_state_graph, write_state_graph,
)


PACKAGE = "com.samsung.android.oneconnect"
ACTIVITY = PACKAGE + ".ui.scmain.SCMainActivity"


def node(rid, bounds, text="", **extra):
    return {"viewIdResourceName": rid, "className": "android.widget.TextView",
            "boundsInScreen": bounds, "text": text, "visibleToUser": True,
            "enabled": True, "checked": False, "selected": False,
            "clickable": False, "focusable": False, "scrollable": False, **extra}


def observation(*, tab="home", focus="first", dynamic_text="Temperature 21°C", extra_node=False,
                overlay=None, semantic_substate=None, timestamp="2026-10-19T01:00:00Z"):
    if tab == "home":
        scenario = "home_main"
        context_resource = "dashboard_layout"
        tab_resource = "menu_favorites"
    else:
        scenario = "devices_main"
        context_resource = "card_recycler"
        tab_resource = "menu_devices"
    current = node(f"{PACKAGE}:id/{context_resource}", "[0,100][900,800]", "Home content")
    dynamic = node(f"{PACKAGE}:id/measurement", "[100,200][500,260]", dynamic_text)
    bottom_tab = node(f"{PACKAGE}:id/{tab_resource}", "[0,900][200,1000]", tab.title(), selected=True)
    nodes = [current, dynamic, bottom_tab]
    if extra_node:
        nodes.append(node(f"{PACKAGE}:id/extra_card", "[500,300][900,500]", "Other dynamic label"))
    focused = current if focus == "first" else dynamic
    focused = {**focused, "accessibilityFocused": True}
    result = {
        "scenario_id": scenario,
        "package_name": PACKAGE,
        "activity_name": ACTIVITY,
        "context_source": "helper_tree_component",
        "navigation_context": {"bottom_tab": tab},
        "selected_tab": {"name": tab, "verified": True, "source": "service_hierarchy_selected"},
        "display_bounds": [0, 0, 1000, 1000],
        "capture_root_bounds": [0, 0, 1000, 1000],
        "nodes": nodes,
        "focus_node": focused,
        "timestamp": timestamp,
        "observation_coverage": "OBSERVED_FULL",
        "overlay": overlay or {},
    }
    if semantic_substate:
        result["semantic_substates"] = [semantic_substate]
    return attach_capture_authority(result, production=True)


def evidence(*, focus="CONFIRMED_UNCHANGED", focus_id="candidate-a", visit="NO_VISIT",
             visit_id=None, action=None, **extra):
    return {"focus_transition_status": focus,
            "actual_focus_instance_id": focus_id,
            "visit_record_status": "RECORDED" if visit == "VISIT_GRANTED" else visit,
            "reconciled_visit_instance_id": visit_id,
            "action": action,
            **extra}


def _focus_row_for_attribution(action="TARGETED_FOCUS"):
    raw = observation(focus="second")
    actual = raw["focus_node"]
    return {
        "step_index": 1, "scenario_id": raw["scenario_id"],
        "state_graph_observation": raw, "actual_focus_node": actual,
        "actual_focus_accessibility_focused": True,
        "actual_focus_payload_source": "top_level",
        "actual_focus_instance_id": "actual-focused-node",
        "focus_transition_status": "CONFIRMED_MOVED",
        "visit_record_status": "RECORDED",
        "reconciled_visit_instance_id": "actual-focused-node",
        "phase6_current_action_type": action, "smart_nav_req_id": "earlier-smart-next",
        "target_focus_attempted": True, "target_focus_status": "TARGET_NOT_FOUND",
        "target_focus_request_id": "later-target",
        "target_focus_descriptor": {"resource_id": "different-target", "bounds": "[0,0][1,1]"},
    }


def test_failed_later_target_cannot_borrow_smart_next_focus_or_visit():
    row = _focus_row_for_attribution()
    graph = recorder_from_existing_rows([row], run_id="attribution", scenario_id=row["scenario_id"]).to_dict()
    edge, observed = graph["edges"][0], graph["observations"][0]
    assert edge["request_id"] == "later-target"
    assert "ATTEMPTED" in edge["lifecycle"]
    assert not {"EFFECT_OBSERVED", "STATE_CHANGED", "VISIT_CREDIT"} & set(edge["lifecycle"])
    assert edge["focus_observation"] == "FOCUS_UNKNOWN"
    assert edge["visit_outcome"] == "VISIT_UNKNOWN" and edge["visit_instance_id"] is None
    assert edge["destination_state_id"] is None
    assert observed["focus"]["observation"] == "FOCUS_MOVED"
    assert observed["focus"]["instance_id"] == "actual-focused-node"
    assert observed["visit_outcome"] == "VISIT_GRANTED"
    assert observed["edge_id"] is None


def test_failed_target_producer_through_reconciliation_and_graph_keeps_earlier_visit():
    from types import SimpleNamespace
    from talkback_lib.exploration_evidence_clock import EvidenceClock
    from tb_runner import collection_flow, focus_realign_logic

    row = _focus_row_for_attribution("SMART_NEXT")
    actual = row["actual_focus_node"]
    clock = EvidenceClock()
    clock.dispatch(["shell", "am", "broadcast", "-a",
                    "com.iotpart.sqe.talkbackhelper.SMART_NEXT", "--es", "reqId", "earlier-smart-next"])

    class Client:
        _adb_device = SimpleNamespace(shadow_evidence_clock=clock)

        def target_focus_commit(self, **_kwargs):
            clock.dispatch(["shell", "am", "broadcast", "-a",
                            "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
                            "--es", "reqId", "later-target"])
            return {"reqId": "later-target", "status": "TARGET_NOT_FOUND", "success": False}

        def get_focus(self, **_kwargs):
            return actual

    client = Client()
    target = node("different-target", "[0,0][50,50]", "Other")
    ok, _, _ = focus_realign_logic._maybe_realign_focus_to_representative_impl(
        client=client, dev="device", row=row, selected_node=target,
        selected_rid="different-target", selected_label="Other", selected_bounds="[0,0][50,50]",
        scenario_id=row["scenario_id"], step_idx=1, mismatch_logged=True, force_reason="",
        scenario_perf=None, focus_matches_fn=lambda **_kwargs: False,
        extract_label_fn=lambda value: value.get("text", ""), label_blob_fn=lambda _value: "",
        truncate_fn=lambda value, *_args: value, log_fn=lambda _message: None)
    assert not ok and row["actual_focus_node"] == actual
    row["_exploration_observation"] = clock.finish_observation(clock.begin_observation())
    payload = collection_flow._focus_reconciliation_event_payload(
        client=client, row=row, result={"focus_transition_status": "CONFIRMED_MOVED",
                                       "classification": "MATCHED", "visit_record_status": "RECORDED"})
    assert payload["primary_action_request_id"] == "earlier-smart-next"
    assert payload["action_request_id"] == ""
    graph = recorder_from_existing_rows([row], run_id="producer", scenario_id=row["scenario_id"]).to_dict()
    edge = graph["edges"][0]
    assert edge["request_id"] == "later-target"
    assert not {"EFFECT_OBSERVED", "STATE_CHANGED", "VISIT_CREDIT"} & set(edge["lifecycle"])
    assert graph["observations"][0]["focus"]["instance_id"] == "actual-focused-node"
    assert graph["observations"][0]["visit_outcome"] == "VISIT_GRANTED"


def test_smart_next_current_focus_still_credits_actual_focused_node():
    row = _focus_row_for_attribution("SMART_NEXT")
    graph = recorder_from_existing_rows([row], run_id="attribution", scenario_id=row["scenario_id"]).to_dict()
    edge = graph["edges"][0]
    assert edge["request_id"] == "earlier-smart-next"
    assert {"EFFECT_OBSERVED", "VISIT_CREDIT"} <= set(edge["lifecycle"])
    assert edge["visit_instance_id"] == "actual-focused-node"


def test_verified_current_target_focus_credits_its_actual_focused_node():
    from talkback_lib.exploration_evidence_clock import EvidenceClock

    row = _focus_row_for_attribution()
    actual = row["actual_focus_node"]
    clock = EvidenceClock()
    clock.dispatch(["shell", "am", "broadcast", "-a",
                    "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
                    "--es", "reqId", "later-target"])
    row.update(target_focus_status="TARGET_MATCHED",
               target_focus_descriptor={"resource_id": actual["viewIdResourceName"],
                                        "bounds": actual["boundsInScreen"]},
               actual_focus_payload_source="target_focus_commit_verified",
               _phase6_target_focus_observation=clock.finish_observation(clock.begin_observation()),
               _exploration_observation=clock.finish_observation(clock.begin_observation()))
    graph = recorder_from_existing_rows([row], run_id="attribution", scenario_id=row["scenario_id"]).to_dict()
    edge = graph["edges"][0]
    assert edge["request_id"] == "later-target"
    assert {"EFFECT_OBSERVED", "VISIT_CREDIT"} <= set(edge["lifecycle"])
    assert edge["visit_instance_id"] == "actual-focused-node"

    row["target_focus_request_id"] = "mismatched-later-request"
    graph = recorder_from_existing_rows([row], run_id="attribution", scenario_id=row["scenario_id"]).to_dict()
    assert "VISIT_CREDIT" not in graph["edges"][0]["lifecycle"]


def test_focus_only_change_reuses_same_graph_state_and_records_cursor():
    a = observation(focus="first")
    b = observation(focus="second")
    assert build_graph_state_identity(a).state_id == build_graph_state_identity(b).state_id
    recorder = StateGraphRecorder("run-focus")
    recorder.record(step=1, raw_observation=a, evidence=evidence(focus="CONFIRMED_MOVED", focus_id="candidate-a"))
    recorder.record(step=2, raw_observation=b, evidence=evidence(focus="CONFIRMED_MOVED", focus_id="candidate-b"))
    graph = recorder.to_dict()
    assert graph["summary"]["state_count"] == 1
    assert graph["summary"]["focus_move_count"] == 2
    assert graph["states"][0]["observation_count"] == 2
    assert graph["states"][0]["focus_instance_ids"] == ["candidate-a", "candidate-b"]


def test_focus_visit_and_timestamp_are_excluded_from_identity():
    a = observation(timestamp="2026-01-01T00:00:00Z")
    b = observation(focus="second", timestamp="2026-10-19T02:00:00Z")
    a["visited_set"] = ["candidate-a"]
    b["visited_set"] = ["candidate-a", "candidate-b"]
    assert build_graph_state_identity(a).state_id == build_graph_state_identity(b).state_id


def test_dynamic_observational_text_is_excluded_without_new_normalization_rules():
    a = observation(dynamic_text="Temperature 21°C")
    b = observation(dynamic_text="Unreviewed changing description 42")
    assert build_graph_state_identity(a).state_id == build_graph_state_identity(b).state_id


def test_verified_root_substate_change_creates_distinct_state():
    home = observation(tab="home")
    devices = observation(tab="devices")
    assert home["package_name"] == devices["package_name"]
    assert home["activity_name"] == devices["activity_name"]
    assert build_graph_state_identity(home).state_id != build_graph_state_identity(devices).state_id


def test_activity_and_overlay_diagnostics_do_not_change_state_identity():
    base = observation()
    diagnostic = observation(overlay={"kind": "dialog", "observed": True,
        "classification": "VERIFIED_MODAL", "source": "wms_diagnostic",
        "nodes": [node(f"{PACKAGE}:id/dialog_title", "[200,300][800,400]", "Confirm") ]})
    diagnostic["activity_name"] = "pkg.OtherDiagnosticActivity"
    diagnostic["window_evidence"] = {"focused_window_type": "APPLICATION_ATTACHED_DIALOG"}
    assert build_graph_state_identity(base).state_id == build_graph_state_identity(diagnostic).state_id


def test_meaningful_viewport_structure_changes_state_identity():
    base = observation()
    moved_viewport = observation(extra_node=True)
    assert build_graph_state_identity(base).state_id != build_graph_state_identity(moved_viewport).state_id


def test_graph_rejects_self_hashed_capture_mapping_but_accepts_decoder_token():
    from talkback_lib.reliable_hierarchy_schema import capture_canonical_sha256

    valid = observation()
    assert build_graph_state_identity(valid).status == "RESOLVED"

    forged = deepcopy(valid)
    authority = deepcopy(forged["capture_authority"])
    authority.pop("validation_seal", None)
    core_fields = (
        "schema_version", "canonicalization", "request_id", "process_epoch",
        "generation", "service_instance_id", "capture_sequence", "root_ref",
        "root_digest", "candidate_digest", "hierarchy_package_name", "hierarchy_window_id",
        "hierarchy_root_class_name", "hierarchy_root_source_node_id", "hierarchy_root_bounds",
    )
    authority["capture_key"] = capture_canonical_sha256(
        {key: authority[key] for key in core_fields})
    authority["validation_seal"] = capture_canonical_sha256(authority)
    forged["capture_authority"] = authority
    forged["production_observation_envelope"]["capture_authority"] = deepcopy(authority)

    assert build_graph_state_identity(forged).status == "UNRESOLVED"


def test_graph_identity_rejects_missing_capture_authority_and_envelope():
    raw = observation()
    for key in ("capture_authority", "capture_id", "hierarchy_capture_id",
                "production_observation_envelope", "production_observation_current"):
        raw.pop(key, None)
    identity = build_graph_state_identity(raw)
    assert identity.status == "UNRESOLVED"
    assert "PRODUCTION_OBSERVATION_NOT_CURRENT_OR_ALIGNED" in identity.reasons


def test_authority_root_package_mismatch_blocks_production_graph_identity():
    raw = observation()
    raw["package_name"] = "com.attacker.package"
    identity = build_graph_state_identity(raw)
    assert identity.status == "UNRESOLVED"
    assert identity.state_id is None
    assert "PRODUCTION_OBSERVATION_NOT_CURRENT_OR_ALIGNED" in identity.reasons


def test_traversal_root_reference_or_window_mismatch_blocks_graph_identity():
    for field, value in (("traversal_root_ref", "windows[1].root"),
                         ("traversal_root_window_id", 999)):
        raw = observation()
        raw[field] = value
        identity = build_graph_state_identity(raw)
        assert identity.status == "UNRESOLVED"
        assert identity.state_id is None


def test_missing_capture_bound_root_geometry_stays_unresolved():
    raw = observation()
    raw["nodes"] = []
    raw = attach_capture_authority(raw, production=True)
    assert build_graph_state_identity(raw).status == "UNRESOLVED"


def test_same_state_revisit_reuses_node_and_tracks_multiple_visits_separately():
    recorder = StateGraphRecorder("run-visits")
    raw = observation()
    recorder.record(step=1, raw_observation=raw,
        evidence=evidence(visit="VISIT_GRANTED", visit_id="candidate-1"))
    recorder.record(step=2, raw_observation=raw,
        evidence=evidence(visit="VISIT_GRANTED", visit_id="candidate-2"))
    state = recorder.to_dict()["states"][0]
    assert recorder.to_dict()["summary"]["state_count"] == 1
    assert state["observation_count"] == 2
    assert state["visit_instance_ids"] == ["candidate-1", "candidate-2"]


def test_visit_is_never_recomputed_from_physical_visited_flag():
    recorder = StateGraphRecorder("run-visit-authority")
    recorder.record(step=1, raw_observation=observation(), evidence={"physical_visited": True})
    row = recorder.to_dict()
    assert row["observations"][0]["visit_outcome"] == VisitObservation.VISIT_UNKNOWN.value
    assert row["states"][0]["visit_instance_ids"] == []


def test_ack_success_does_not_imply_effect_state_change_or_visit():
    recorder = StateGraphRecorder("run-ack")
    recorder.record(step=1, raw_observation=observation(), evidence=evidence(
        action={"type": "FOCUS_NEXT"}, planned=True, attempted=True, dispatched=True,
        command_ack="SUCCESS"))
    edge = recorder.to_dict()["edges"][0]
    assert edge["command_ack"] == "SUCCESS"
    assert EdgeLifecycle.STATE_CHANGED.value not in edge["lifecycle"]
    assert EdgeLifecycle.EFFECT_OBSERVED.value not in edge["lifecycle"]
    assert EdgeLifecycle.VISIT_CREDIT.value not in edge["lifecycle"]


def test_failed_ack_can_coexist_with_proven_focus_effect_without_visit():
    recorder = StateGraphRecorder("run-failed-ack-move")
    recorder.record(step=1, raw_observation=observation(), evidence=evidence(
        focus="CONFIRMED_MOVED", action={"type": "FOCUS_NEXT"}, attempted=True,
        dispatched=True, command_ack="FAILED"))
    edge = recorder.to_dict()["edges"][0]
    assert edge["command_ack"] == "FAILED"
    assert EdgeLifecycle.EFFECT_OBSERVED.value in edge["lifecycle"]
    assert EdgeLifecycle.STATE_CHANGED.value not in edge["lifecycle"]
    assert EdgeLifecycle.VISIT_CREDIT.value not in edge["lifecycle"]


def test_edge_lifecycle_keeps_attempt_dispatch_effect_state_and_visit_separate():
    raw_a = observation()
    raw_b = observation(extra_node=True)
    recorder = StateGraphRecorder("run-edge-lifecycle")
    recorder.record(step=1, raw_observation=raw_a, evidence={})
    recorder.record(step=2, raw_observation=raw_b, evidence=evidence(
        focus="CONFIRMED_MOVED", action={"type": "SAFE_ACTIVATION", "target": {"resource_id": "pkg:id/x"}},
        attempted=True, dispatched=True, command_ack="FAILED"))
    edge = recorder.to_dict()["edges"][0]
    assert edge["source_state_id"] != edge["destination_state_id"]
    assert EdgeLifecycle.ATTEMPTED.value in edge["lifecycle"]
    assert EdgeLifecycle.DISPATCHED.value in edge["lifecycle"]
    assert EdgeLifecycle.EFFECT_OBSERVED.value in edge["lifecycle"]
    assert EdgeLifecycle.STATE_CHANGED.value in edge["lifecycle"]
    assert EdgeLifecycle.VISIT_CREDIT.value not in edge["lifecycle"]
    assert "authorization" not in edge and "permit" not in edge


def test_attempted_but_not_dispatched_and_dispatched_without_effect_are_distinct():
    recorder = StateGraphRecorder("run-dispatch")
    raw = observation()
    recorder.record(step=1, raw_observation=raw,
        evidence=evidence(action={"type": "FOCUS_NEXT"}, planned=True, attempted=True, dispatched=False))
    recorder.record(step=2, raw_observation=raw,
        evidence=evidence(action={"type": "FOCUS_NEXT"}, attempted=True, dispatched=True,
                         focus="CONFIRMED_UNCHANGED", command_ack="SUCCESS"))
    first, second = recorder.to_dict()["edges"]
    assert first["lifecycle"] == [EdgeLifecycle.PLANNED.value, EdgeLifecycle.ATTEMPTED.value]
    assert EdgeLifecycle.DISPATCHED.value in second["lifecycle"]
    assert EdgeLifecycle.EFFECT_OBSERVED.value not in second["lifecycle"]


def test_visit_credit_can_exist_without_state_change():
    recorder = StateGraphRecorder("run-visit-self-edge")
    raw = observation()
    recorder.record(step=1, raw_observation=raw, evidence={})
    recorder.record(step=2, raw_observation=raw, evidence=evidence(
        action={"type": "FOCUS_NEXT"}, visit="VISIT_GRANTED", visit_id="candidate-2"))
    edge = recorder.to_dict()["edges"][0]
    assert edge["source_state_id"] == edge["destination_state_id"]
    assert EdgeLifecycle.VISIT_CREDIT.value in edge["lifecycle"]
    assert EdgeLifecycle.STATE_CHANGED.value not in edge["lifecycle"]


def test_self_edges_and_repeated_edges_are_supported():
    recorder = StateGraphRecorder("run-self-edge")
    raw = observation()
    recorder.record(step=1, raw_observation=raw, evidence={})
    recorder.record(step=2, raw_observation=raw, evidence=evidence(
        focus="CONFIRMED_MOVED", action={"type": "FOCUS_NEXT"}))
    edge = recorder.to_dict()["edges"][0]
    assert edge["source_state_id"] == edge["destination_state_id"]
    assert EdgeLifecycle.EFFECT_OBSERVED.value in edge["lifecycle"]


def test_scroll_evidence_is_recorded_without_capability_or_scheduling_decisions():
    recorder = StateGraphRecorder("run-scroll-shadow")
    recorder.record(step=1, raw_observation=observation(), evidence={
        "scroll_evidence": {"status": "UNKNOWN", "axis": "UNKNOWN", "direction": "FORWARD",
                            "owner_identity": None, "movement_status": "UNAVAILABLE"}})
    data = recorder.to_dict()
    assert data["states"][0]["scroll_observations"][0]["status"] == "UNKNOWN"
    assert data["terminal_evidence"] == {}
    assert data["decision_authority"] == "NONE"


def _phase6e_capture(*, sequence, changed=False, second_container=False, focus=False,
                     omit_owner=False, action_epoch=0, request_id=None, volatile_owner=False):
    raw = observation(extra_node=changed)
    owner = {
        "viewIdResourceName": f"{PACKAGE}:id/content_list",
        "className": "android.widget.ScrollView",
        "boundsInScreen": "[0,100][900,800]",
        "stable_node_path": "0.0.1",
        "scrollable": True, "visibleToUser": True, "enabled": True,
        "actions": [16908346], "scroll_down_supported": True,
    }
    if volatile_owner:
        owner.update(actions=[4096], scroll_down_supported=False)
    nodes = [owner]
    if second_container:
        nodes.append({**owner, "viewIdResourceName": f"{PACKAGE}:id/secondary_list",
                      "boundsInScreen": "[0,200][900,700]", "stable_node_path": "0.0.2"})
    if focus:
        raw["nodes"][1]["accessibilityFocused"] = True
    else:
        raw["nodes"][1]["focused"] = True  # input focus alone is not accessibility focus
    raw["nodes"] = [raw["nodes"][0], *([] if omit_owner else nodes), *raw["nodes"][1:]]
    selected = nodes[0]
    raw["capability"] = {
        "status": "SCROLL_CAPABLE", "source": "helper_metadata",
        "can_scroll_forward": True, "vertical_can_scroll_forward": True,
        "contradictory": False,
        "container": {**selected, "path": selected["stable_node_path"]},
        "containers": nodes,
    }
    raw = attach_capture_authority(raw, production=True, sequence=sequence)
    from talkback_lib.hierarchy_snapshot import flatten_service_hierarchy
    raw["nodes"] = flatten_service_hierarchy({"success": True, "windows": [
        {"active": True, "focused": True, "root": deepcopy(raw["_capture_root_tree"])}]})
    if action_epoch:
        marker = deepcopy(raw["_exploration_observation"])
        marker.update(action_epoch=action_epoch, observation_epoch=action_epoch,
                      capture_end_action_epoch=action_epoch)
        marker["action_ownership"] = {
            "action_epoch": action_epoch, "action_type": "SCROLL",
            "request_id": request_id, "ownership_status": "KNOWN",
        }
        raw["_exploration_observation"] = marker
        raw["production_observation_envelope"]["observation"] = deepcopy(marker)
    return raw


def _phase6e_transition(source, *, request_id="scroll-1", result_request_id=None,
                        target_path=None, target_bounds=None, changed=True,
                        boundary=False, action_epoch=1):
    owner = next((item for item in source["nodes"]
                  if item.get("scrollable") is True and item.get("stable_node_path") == (target_path or "0.0.1")), None)
    if target_bounds is None and owner is not None:
        target_bounds = owner["boundsInScreen"]
    return {
        "action_type": "SCROLL_FORWARD", "direction": "down",
        "action_request_id": request_id,
        "action_result_request_id": result_request_id or request_id,
        "action_result_correlated": bool(request_id and (result_request_id or request_id) == request_id),
        "action_success": True, "viewport_changed": changed,
        "new_count": 1 if changed else 0, "disappeared_count": 0,
        "viewport_end": boundary,
        "capability_after": {"can_scroll_forward": False if boundary else True,
                              "contradictory": False},
        "action_target": {"mode": "EXPLICIT_CONTAINER", "container_path": target_path or "0.0.1",
                          "container_bounds": target_bounds},
        "action_result": {"reqId": result_request_id or request_id,
                          "action": "SCROLL_FORWARD", "success": True,
                          "actionAttempted": True, "explicitTarget": True,
                          "scrollContainerPath": target_path or "0.0.1"},
    }


def _phase6e_row(source, result, transition):
    return {
        "step_index": 1, "scenario_id": source["scenario_id"],
        "scenario_run_id": source["scenario_run_id"],
        "state_graph_observation": source, "capture_id": source["capture_id"],
        "_exploration_observation": deepcopy(source["_exploration_observation"]),
        "phase6e_scroll_source_observation": source,
        "phase6e_scroll_source_marker": deepcopy(source["_exploration_observation"]),
        "phase6e_scroll_result_observation": result,
        "phase6e_scroll_result_marker": deepcopy(result["_exploration_observation"]),
        "scroll_transition": transition,
    }


def test_phase6e_resolves_explicit_current_scroll_owner_across_multiple_containers():
    identities = set()
    for path, bounds in (("0.0.1", "[0,100][900,800]"),
                         ("0.0.2", "[0,200][900,700]")):
        source = _phase6e_capture(sequence=10, second_container=True)
        result = _phase6e_capture(sequence=11, changed=True, second_container=True,
                                  focus=True, action_epoch=1, request_id="scroll-1")
        transition = _phase6e_transition(source, target_path=path, target_bounds=bounds)
        evidence_row = build_phase6e_scroll_evidence(
            source, result, transition,
            source_marker=source["_exploration_observation"],
            result_marker=result["_exploration_observation"],
        )
        assert evidence_row["classification"] == "SCROLL_MOVED"
        assert evidence_row["owner_status"] == "RESOLVED"
        assert evidence_row["owner"]["path"] == path
        identities.add(evidence_row["owner_identity"])
    assert len(identities) == 2


@pytest.mark.parametrize("target_path,target_bounds,result_path,expected", [
    ("missing", "[0,100][900,800]", "missing", "OWNER_NOT_IN_CURRENT_HIERARCHY"),
    ("0.0.1", "[1,100][900,800]", "0.0.1", "OWNER_TARGET_MISMATCH"),
    (None, "[0,100][900,800]", "0.0.1", "OWNER_TARGET_MISMATCH"),
])
def test_phase6e_rejects_stale_or_mismatched_owner(target_path, target_bounds, result_path, expected):
    source = _phase6e_capture(sequence=10, omit_owner=(target_path == "missing"))
    result = _phase6e_capture(sequence=11, changed=True, action_epoch=1, request_id="scroll-1")
    transition = _phase6e_transition(source, target_path=target_path,
                                     target_bounds=target_bounds)
    if target_path is None:
        transition["action_target"]["container_path"] = None
    transition["action_result"]["scrollContainerPath"] = result_path
    evidence_row = build_phase6e_scroll_evidence(
        source, result, transition,
        source_marker=source["_exploration_observation"],
        result_marker=result["_exploration_observation"],
    )
    assert evidence_row["classification"] == expected
    assert evidence_row["valid_for_edge"] is False


def test_phase6e_requires_current_matching_dispatch_receipt_and_result():
    source = _phase6e_capture(sequence=10)
    result = _phase6e_capture(sequence=11, changed=True, action_epoch=1,
                              request_id="different-dispatch")
    transition = _phase6e_transition(source, result_request_id="scroll-1")
    evidence_row = build_phase6e_scroll_evidence(
        source, result, transition,
        source_marker=source["_exploration_observation"],
        result_marker=result["_exploration_observation"],
    )
    assert evidence_row["classification"] == "STALE_INVOCATION_RESULT"
    assert evidence_row["dispatch_receipt_correlated"] is False
    assert evidence_row["valid_for_edge"] is False

    stale_result = _phase6e_capture(sequence=12, changed=True, action_epoch=2,
                                    request_id="scroll-1")
    stale = build_phase6e_scroll_evidence(
        source, stale_result, _phase6e_transition(source),
        source_marker=source["_exploration_observation"],
        result_marker=stale_result["_exploration_observation"],
    )
    assert stale["classification"] == "STALE_CAPTURE"
    assert stale["valid_for_edge"] is False


def test_phase6e_real_change_creates_edge_with_strict_after_scroll_focus_and_no_visit_credit():
    source = _phase6e_capture(sequence=10)
    result = _phase6e_capture(sequence=11, changed=True, focus=True,
                              action_epoch=1, request_id="scroll-1")
    transition = _phase6e_transition(source)
    evidence_row = build_phase6e_scroll_evidence(
        source, result, transition,
        source_marker=source["_exploration_observation"],
        result_marker=result["_exploration_observation"],
    )
    assert evidence_row["valid_for_edge"] is True
    assert evidence_row["focus_after_scroll"]["status"] == "CONFIRMED"
    graph = recorder_from_existing_rows([_phase6e_row(source, result, transition)],
                                        run_id="phase6e", scenario_id=source["scenario_id"]).to_dict()
    assert len(graph["edges"]) == 1
    edge = graph["edges"][0]
    assert EdgeLifecycle.EFFECT_OBSERVED.value in edge["lifecycle"]
    assert edge["request_id"] == "scroll-1"
    assert edge["visit_outcome"] == VisitObservation.VISIT_UNKNOWN.value
    assert EdgeLifecycle.VISIT_CREDIT.value not in edge["lifecycle"]


def test_phase6e_no_change_and_top_bottom_boundary_create_no_graph_edge():
    source = _phase6e_capture(sequence=10)
    unchanged = _phase6e_capture(sequence=11, focus=True, action_epoch=1,
                                 request_id="scroll-1")
    no_change = _phase6e_transition(source, changed=False)
    evidence_row = build_phase6e_scroll_evidence(
        source, unchanged, no_change,
        source_marker=source["_exploration_observation"],
        result_marker=unchanged["_exploration_observation"],
    )
    assert evidence_row["classification"] == "NO_PROGRESS"
    assert evidence_row["focus_after_scroll"]["status"] == "CONFIRMED"
    graph = recorder_from_existing_rows([_phase6e_row(source, unchanged, no_change)],
                                        run_id="phase6e-no-change", scenario_id=source["scenario_id"]).to_dict()
    assert graph["edges"] == []
    assert graph["states"][0]["scroll_observations"]

    boundary = _phase6e_transition(source, changed=False, boundary=True)
    unchanged["capability"].update(can_scroll_forward=False, vertical_can_scroll_forward=False)
    top = build_phase6e_scroll_evidence(
        source, unchanged, boundary,
        source_marker=source["_exploration_observation"],
        result_marker=unchanged["_exploration_observation"],
    )
    assert top["classification"] == "BOUNDARY"
    assert top["valid_for_edge"] is False


def test_phase6e_uses_bound_captures_not_claimed_transition_movement():
    source = _phase6e_capture(sequence=10)
    result = _phase6e_capture(sequence=11, action_epoch=1, request_id="scroll-1")
    evidence = build_phase6e_scroll_evidence(source, result, _phase6e_transition(source, changed=True))
    assert evidence["classification"] == "NO_PROGRESS"
    assert evidence["valid_for_edge"] is False


def test_phase6e_movement_at_boundary_still_records_actual_change():
    source = _phase6e_capture(sequence=10)
    result = _phase6e_capture(sequence=11, changed=True, action_epoch=1, request_id="scroll-1")
    result["capability"].update(can_scroll_forward=False, vertical_can_scroll_forward=False)
    evidence = build_phase6e_scroll_evidence(source, result, _phase6e_transition(source, boundary=True))
    assert evidence["classification"] == "SCROLL_MOVED"
    assert evidence["valid_for_edge"] is True


def test_phase6e_boundary_requires_matching_current_capability():
    source = _phase6e_capture(sequence=10)
    result = _phase6e_capture(sequence=11, action_epoch=1, request_id="scroll-1")
    evidence = build_phase6e_scroll_evidence(source, result, _phase6e_transition(source, changed=False, boundary=True))
    assert evidence["classification"] == "NO_PROGRESS"
    assert evidence["boundary"] is False


def test_phase6e_owner_identity_excludes_volatile_window_and_action_state():
    source = _phase6e_capture(sequence=10)
    result = _phase6e_capture(sequence=11, changed=True, action_epoch=1, request_id="scroll-1")
    original = build_phase6e_scroll_evidence(source, result, _phase6e_transition(source))
    revised_source = _phase6e_capture(sequence=10, volatile_owner=True)
    revised = build_phase6e_scroll_evidence(revised_source, result, _phase6e_transition(revised_source))
    assert original["owner_identity"] == revised["owner_identity"]


def test_phase6e_rejects_hierarchy_nodes_changed_after_capture():
    source = _phase6e_capture(sequence=10)
    result = _phase6e_capture(sequence=11, changed=True, action_epoch=1, request_id="scroll-1")
    transition = _phase6e_transition(source)
    next(node for node in source["nodes"] if node.get("scrollable"))["stable_node_path"] = "forged"
    evidence = build_phase6e_scroll_evidence(source, result, transition)
    assert evidence["classification"] == "STALE_CAPTURE"
    assert evidence["valid_for_edge"] is False


@pytest.mark.parametrize("mutation", ["not_attempted", "unknown_target", "wrong_direction", "context_revision"])
def test_phase6e_rejects_unbound_action_or_context(mutation):
    source = _phase6e_capture(sequence=10)
    result = _phase6e_capture(sequence=11, changed=True, action_epoch=1, request_id="scroll-1")
    transition = _phase6e_transition(source)
    if mutation == "not_attempted":
        transition["action_result"]["actionAttempted"] = False
    elif mutation == "unknown_target":
        transition["action_target"]["mode"] = "UNKNOWN"
    elif mutation == "wrong_direction":
        transition["direction"] = "up"
    else:
        result["_exploration_observation"]["context_revision"] += 1
        result["production_observation_envelope"]["observation"] = deepcopy(result["_exploration_observation"])
    evidence = build_phase6e_scroll_evidence(source, result, transition)
    assert evidence["valid_for_edge"] is False


def test_serialization_and_ordered_replay_are_deterministic():
    manifest = {"schema_version": REPLAY_SCHEMA_VERSION, "run_id": "fixture-run",
        "scenario_id": "home_main", "steps": [
            {"step": 1, "observation": observation(), "evidence": evidence(action={"type": "FOCUS_NEXT"})},
            {"step": 2, "observation": observation(focus="second"),
             "evidence": evidence(focus="CONFIRMED_MOVED", focus_id="candidate-b", action={"type": "FOCUS_NEXT"})},
        ]}
    first = replay_state_graph(manifest)
    second = replay_state_graph(manifest)
    assert first.to_json() == second.to_json()
    assert first.to_dict()["states"][0]["state_id"] == second.to_dict()["states"][0]["state_id"]
    assert first.to_dict()["edges"][0]["edge_id"] == second.to_dict()["edges"][0]["edge_id"]


def test_offline_replay_cli_writes_versioned_artifact(tmp_path):
    from tools import state_graph_replay

    manifest = {"schema_version": REPLAY_SCHEMA_VERSION, "run_id": "cli-run",
        "scenario_id": "home_main", "steps": [
            {"step": 1, "observation": observation(), "evidence": evidence()},
        ]}
    manifest_path = tmp_path / "manifest.json"
    artifact_path = tmp_path / "state_graph.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert state_graph_replay.main(["--manifest", str(manifest_path), "--output", str(artifact_path)]) == 0
    assert read_state_graph(artifact_path)["summary"]["state_count"] == 1


def test_off_is_default_noop_and_shadow_adds_only_graph_artifact(tmp_path):
    rows = [{"step_index": 1, "state_graph_observation": observation(),
             **evidence(focus="CONFIRMED_MOVED", action={"type": "FOCUS_NEXT"})}]
    before = deepcopy(rows)
    output = tmp_path / "scenario.xlsx"
    assert graph_mode_from_environment({}) == GraphMode.OFF
    assert maybe_write_shadow_graph_from_rows(rows=rows, output_path=output, run_id="r", scenario_id="home_main",
                                              environ={}) is None
    assert not (tmp_path / "scenario.state_graph.json").exists()
    assert rows == before
    graph_path = maybe_write_shadow_graph_from_rows(rows=rows, output_path=output, run_id="r", scenario_id="home_main",
        environ={GRAPH_MODE_ENV: "SHADOW"})
    assert graph_path == tmp_path / "scenario.state_graph.json"
    data = read_state_graph(graph_path)
    assert data["mode"] == "SHADOW" and data["decision_authority"] == "NONE"
    assert rows == before


def test_invalid_mode_fails_closed_to_off():
    assert graph_mode_from_environment({GRAPH_MODE_ENV: "ACTIVE"}) == GraphMode.OFF


def test_graph_shadow_reuses_row_snapshot_without_requesting_hierarchy(monkeypatch):
    from talkback_lib import A11yAdbClient

    def forbidden(*args, **kwargs):
        raise AssertionError("graph shadow must not request another hierarchy")

    monkeypatch.setattr(A11yAdbClient, "get_traversal_candidate_snapshot", forbidden)
    raw = observation()
    rows = [{"step_index": 1, "state_graph_observation": raw,
             "capture_id": raw["capture_id"], "scenario_id": raw["scenario_id"],
             "scenario_run_id": raw["scenario_run_id"],
             "_exploration_observation": deepcopy(raw["_exploration_observation"]),
             "focus_transition_status": "CONFIRMED_MOVED", "actual_focus_instance_id": "focus-1",
             "visit_record_status": "RECORDED", "reconciled_visit_instance_id": "visit-1"}]
    graph = recorder_from_existing_rows(rows, run_id="existing-snapshot", scenario_id="home_main")
    assert graph.to_dict()["summary"]["state_count"] == 1
    assert graph.to_dict()["summary"]["focus_move_count"] == 1


def test_row_projection_does_not_promote_non_authoritative_visit_fields():
    rows = [{"step_index": 1, "state_graph_observation": observation(), "physical_visited": True,
             "visit_record_status": "RECORDED", "actual_focus_instance_id": "focus-1"}]
    graph = recorder_from_existing_rows(rows, run_id="row-authority", scenario_id="home_main").to_dict()
    assert graph["observations"][0]["visit_outcome"] == VisitObservation.VISIT_UNKNOWN.value


def test_graph_limits_truncate_observation_only_and_do_not_change_input():
    raw = observation()
    original = deepcopy(raw)
    recorder = StateGraphRecorder("bounded", limits=GraphLimits(max_states=2, max_edges=2,
        max_observations=1, max_artifact_bytes=100000))
    recorder.record(step=1, raw_observation=raw, evidence={})
    assert recorder.record(step=2, raw_observation=raw, evidence={}) is None
    assert recorder.truncation_reasons == {"MAX_OBSERVATIONS"}
    assert raw == original


def test_write_read_roundtrip_is_versioned_and_authority_marked(tmp_path):
    recorder = StateGraphRecorder("run-roundtrip")
    recorder.record(step=1, raw_observation=observation(), evidence={})
    path = write_state_graph(tmp_path / "state_graph.json", recorder)
    restored = read_state_graph(path)
    assert restored["schema_version"] == "phase6-state-graph.v1"
    assert restored["identity_schema_version"] == "phase6-state-identity.v1"
    assert restored["authority"] == "OBSERVATIONAL_SHADOW_ONLY"
    assert restored["decision_authority"] == "NONE"
    assert json.loads(path.read_text(encoding="utf-8")) == restored


def test_artifact_byte_bound_marks_observational_truncation(tmp_path):
    many_nodes = observation()
    many_nodes["nodes"].extend(node(f"{PACKAGE}:id/extra-{index}",
        f"[{index},300][{index + 40},340]", f"label-{index}") for index in range(30))
    recorder = StateGraphRecorder("run-byte-bound", limits=GraphLimits(max_states=5, max_edges=5,
        max_observations=10, max_artifact_bytes=2400))
    recorder.record(step=1, raw_observation=many_nodes, evidence={})
    path = write_state_graph(tmp_path / "bounded.json", recorder)
    assert path.stat().st_size <= 2400
    data = read_state_graph(path)
    assert data["truncated"] is True
    assert "MAX_ARTIFACT_BYTES" in data["truncation_reasons"]
    assert data["artifact_truncated_from_counts"]["observations"] == 1


def test_c7_focus_summary_is_replayed_synthetically_without_claiming_live_state_count():
    # The preserved C7 summary has 54 strict focus moves but no raw state
    # snapshots. Reuse the count only; repeated screen input is deliberately
    # synthetic and demonstrates that cursor events alone do not split states.
    c7 = {"focus_moves": 54, "new_visit_credits": 16, "raw_state_snapshots_available": False}
    raw = observation()
    recorder = StateGraphRecorder("c7-synthetic", scenario_id="life_home_monitor_plugin")
    for index in range(c7["focus_moves"]):
        recorder.record(step=index + 1, raw_observation=raw, evidence=evidence(
            focus="CONFIRMED_MOVED", focus_id=f"candidate-{index:02d}",
            visit="VISIT_GRANTED" if index < c7["new_visit_credits"] else "NO_VISIT",
            visit_id=f"visit-{index:02d}" if index < c7["new_visit_credits"] else None))
    report = recorder.to_dict()
    assert report["summary"]["focus_move_count"] == 54
    assert report["summary"]["state_count"] == 1
    assert report["summary"]["visit_grant_observation_count"] == 16


def test_unknown_component_context_keeps_capture_local_identity_and_ignores_focus():
    raw = observation()
    raw.pop("selected_tab")
    raw.pop("navigation_context")
    for item in raw["nodes"]:
        item["selected"] = False
    identity = build_graph_state_identity(raw)
    assert identity.status == "RESOLVED"
    assert identity.context["status"] == "UNRESOLVED_CONTEXT"
    assert identity.context["verified"] is False
    recorder = StateGraphRecorder("capture-local-identity")
    recorder.record(step=1, raw_observation=raw, evidence=evidence(focus="CONFIRMED_MOVED"))
    assert recorder.to_dict()["summary"]["state_count"] == 1
    assert recorder.to_dict()["observations"][0]["context_evidence"]["verified"] is False
