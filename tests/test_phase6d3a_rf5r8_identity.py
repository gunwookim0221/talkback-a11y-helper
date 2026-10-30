from copy import deepcopy
import json
from types import SimpleNamespace
from itertools import count

import pytest

from tb_runner import collection_flow as flow
from tb_runner.focus_reconciliation import reconcile_focus, apply_reconciliation_to_row
from tb_runner.frontier_shadow import snapshot_focus_cursor, FrontierShadowRuntime
from tb_runner.exploration_shadow import ExplorationShadowRuntime
from tb_runner.traversal_reliability import snapshot_actual_focus_identity, instance_id, focus_instance
from tools.focus_visit_identity_check import check_credited_visit


OLD = "com.samsung.android.oneconnect:id/more_menu_button_container"
NEW_BOUNDS = "78,768,373,912"


def node(rid=None, bounds=NEW_BOUNDS, label="Smoke sensor", **extra):
    return dict(viewIdResourceName=rid, boundsInScreen=bounds, talkbackLabel=label,
                className="android.view.View", accessibilityFocused=True, focused=False,
                clickable=True, focusable=True, visibleToUser=True, enabled=True, **extra)


def observed(n):
    row = {"scenario_id": "home_main", "step_index": 1, "move_result": "moved"}
    snapshot_actual_focus_identity(row, n)
    return row


def select(row, selected):
    return flow._apply_cta_node_to_row(row=row, selected_node=selected,
        selected_rid=selected.get("viewIdResourceName") or "",
        selected_label=selected.get("talkbackLabel") or "", selected_bounds=selected["boundsInScreen"],
        selected_class=selected["className"], normalized_label="smoke sensor")


def reconcile(row, previous=None, inventory=()):
    result = reconcile_focus(row=row, previous_row=previous or observed(node(OLD, "912,124,1044,268")),
        scenario_id="home_main", inventory=inventory, expected_candidates=inventory,
        physical_visit_confirmed=False, planning_consumed=True)
    apply_reconciliation_to_row(row, result)
    row["focus_reconciliation_evidence"] = dict(result)
    return result


_CURSOR_SEQUENCE = count(10_000)


def cursor(row, n):
    from phase6d_capture_support import attach_capture_authority, bind_observation_marker

    sequence = next(_CURSOR_SEQUENCE)
    marker = {"scope_id": "scope", "observation_id": f"observation-{sequence}",
              "observation_sequence": sequence, "action_epoch": 1,
              "observation_epoch": 1, "capture_end_action_epoch": 1,
              "context_revision": 0, "capture_complete": True}
    raw = dict(scenario_id="home_main", scenario_run_id="run", package_name="com.samsung.android.oneconnect",
               nodes=[deepcopy(n)], focus_node=deepcopy(n), observation_coverage="OBSERVED_FULL")
    attach_capture_authority(raw, production=True, sequence=sequence,
                             request_id=f"focus-cursor-{sequence}")
    capture_key = raw["capture_id"]
    raw["focus_capture_id"] = capture_key
    raw["geometry_capture_id"] = capture_key
    raw["production_observation_envelope"]["focus_capture_id"] = capture_key
    raw["production_observation_envelope"]["geometry_capture_id"] = capture_key
    bind_observation_marker(raw, marker)
    common = dict(scenario_id="home_main", scenario_run_id="run", capture_id=capture_key,
                  hierarchy_capture_id=capture_key, focus_capture_id=capture_key,
                  geometry_capture_id=capture_key)
    row.update(common, _exploration_observation=deepcopy(marker))
    return snapshot_focus_cursor(row, raw)


@pytest.mark.parametrize("rid", [None, "", "own-id"])
def test_exact_live_projection_and_visit_cursor_identity(rid):
    current = node(rid)
    previous = observed(node(OLD, "912,124,1044,268"))
    historical = deepcopy(previous)
    row = dict(previous, focus_view_id=OLD, focus_bounds="912,124,1044,268",
               actual_focus_node=current, actual_focus_resource_id="",
               actual_focus_payload_source="target_focus_commit_verified")
    select(row, current)
    result = reconcile(row, previous)
    expected = instance_id({"scenario_id": "home_main", "view_id": rid or "", "bounds": NEW_BOUNDS})
    assert row["actual_focus_resource_id"] == (rid or "")
    assert row["focus_view_id"] == (rid or "")
    assert result["reconciled_visit_instance_id"] == expected
    assert result["focus_transition_status"] == "CONFIRMED_MOVED"
    current_cursor = cursor(row, current)
    assert current_cursor == {"instance_id": expected, "confirmed": True}
    assert check_credited_visit(row, current_cursor)["status"] == "PASS"
    assert previous == historical


@pytest.mark.parametrize("status", ["TARGET_NOT_FOUND", "ERROR"])
def test_failed_target_does_not_override_real_anonymous_focus(status):
    actual = node()
    row = observed(actual)
    row.update(target_focus_status=status, target_focus_request_id="current-target-request")
    select(row, node("failed-target", "0,0,50,50", "Other"))
    result = reconcile(row)
    assert result["physical_visit_confirmed"] is True
    assert row["actual_focus_resource_id"] == ""
    assert json.loads(result["reconciled_visit_instance_id"])[2] == ""
    assert result["selected_candidate_consumed"] is False
    assert check_credited_visit(row, cursor(row, actual))["status"] == "PASS"


def test_authoritative_same_node_inventory_mapping_remains_strong_without_fabricating_id():
    row = observed(node())
    select(row, node("other", "0,0,50,50", "Other"))
    candidate = dict(rid="mapped-current-id", label="Smoke sensor", bounds=NEW_BOUNDS,
                     class_name="android.view.View", node=node("mapped-current-id"))
    result = reconcile(row, inventory=[candidate])
    assert result["mapping_confidence"] == "STRONG"
    assert json.loads(result["mapped_candidate_instance_id"])[2] == "mapped-current-id"
    assert json.loads(result["reconciled_visit_instance_id"])[2] == ""


def test_unchanged_anonymous_focus_does_not_create_visit():
    previous = observed(node())
    row = deepcopy(previous)
    select(row, node("expected-target", "0,0,50,50"))
    result = reconcile(row, previous)
    assert result["focus_transition_status"] == "CONFIRMED_UNCHANGED"
    assert result["physical_visit_confirmed"] is False
    assert result["reconciled_visit_instance_id"] == ""


def test_identity_projection_cannot_resolve_conflicting_focus_authority():
    row = observed(node())
    row["actual_focus_accessibility_focused"] = False
    select(row, node("candidate"))
    result = reconcile(row)
    assert row["actual_focus_accessibility_focused"] is False
    assert result["focus_transition_status"] == "AMBIGUOUS"
    assert result["physical_visit_confirmed"] is False


def test_all_structural_fields_are_from_current_node_and_missing_stays_missing():
    row = observed(node(OLD, "0,0,20,20", "Old", role="old-role", parentResourceId="old-parent", nodePath="old-path"))
    current = node()
    row["actual_focus_node"] = current
    select(row, node("candidate"))
    assert row["actual_focus_resource_id"] == ""
    assert row["actual_focus_visible"] == "Smoke sensor"
    for field in ["actual_focus_role", "actual_focus_container_id", "actual_focus_node_path"]:
        assert row[field] == ""


def test_inventory_registration_cannot_backfill_representative_identity(monkeypatch):
    items = []
    monkeypatch.setattr(flow, "_register_focusable_inventory_item", lambda *a, **kw: items.append(kw))
    row = observed(node())
    row.update(focus_view_id="candidate", focus_class_name="wrong-class", focus_bounds="0,0,50,50")
    flow._register_focusable_inventory_from_row(SimpleNamespace(), output_path="unused", row=row)
    assert items[0]["view_id"] == ""
    assert items[0]["bounds"] == NEW_BOUNDS
    assert items[0]["class_name"] == "android.view.View"


def test_prior_live_defect_is_rejected_by_new_artifact_check():
    row = observed(node())
    reconcile(row)
    current_cursor = cursor(row, node())
    row["actual_focus_resource_id"] = OLD
    synthetic = instance_id({"scenario_id": "home_main", "view_id": OLD, "bounds": NEW_BOUNDS})
    row["focus_reconciliation_evidence"]["reconciled_visit_instance_id"] = synthetic
    result = check_credited_visit(row, current_cursor)
    assert result["status"] == "FAIL"
    assert "ACTUAL_PROJECTION_RESOURCE_ID_MISMATCH" in result["reasons"]
    assert "VISIT_IDENTITY_MISMATCH" in result["reasons"]


@pytest.mark.parametrize("field,value", [("actual_focus_class_name", "wrong-class"),
                                         ("actual_focus_bounds", "0,0,10,10")])
def test_artifact_check_rejects_other_mixed_identity_fields(field, value):
    row = observed(node()); reconcile(row)
    row[field] = value
    assert check_credited_visit(row)["status"] == "FAIL"


def test_anonymous_visits_are_reused_by_frontier_and_phase6_history():
    row = observed(node()); reconcile(row)
    iid = row["reconciled_visit_instance_id"]
    runtime = FrontierShadowRuntime("run", "home_main")
    candidate = dict(candidate_id="anonymous", state_id="state", edge_type="TARGETED_FOCUS",
                     target_identity={"instance_id": iid}, currently_present=True,
                     target_binding_status="RESOLVED", stable_order_key=[0])
    runtime.capture_inventory(step=0, state_id="state", candidates=[candidate],
                              inventory_complete=True, observation_ref={"source_step": 0, "state_id": "state"})
    planners = {"anonymous": dict(state_id="state", action_type="TARGETED_FOCUS", edge_type="TARGETED_FOCUS",
                                 target_instance_id=iid, status="ELIGIBLE")}
    safeties = {"anonymous": dict(planners["anonymous"], status="SAFE")}
    def pre(step):
        return runtime.pre_decision(step=step, production_choice={"action_type": "FOCUS_NEXT_UNTARGETED"},
            focus_cursor={"instance_id": "another-current-node", "confirmed": True}, current_inventory=[candidate], state_id="state",
            inventory_complete=True, planner_evidence=planners, safety_evidence=safeties,
            observation_ref={"source_step": step-1, "state_id": "state"})
    decision = pre(1)
    row.update(phase6_current_action_type="SMART_NEXT", smart_nav_req_id="current-request")
    assert runtime.post_result(decision_id=decision, step=1, result=row, owner="SEQUENTIAL",
        ownership_status="EXACT_MATCH", result_id="current-request", action_type="FOCUS_NEXT", target_instance_id=iid)
    pre(2)
    item = runtime.evaluations[-1]["frontier_items"][0]
    assert item["state_visit_credit_count"] == 1
    assert item["visit_status"] == "RECORDED"
    assert item["status"] == "EXPLORED"
    # Feed the same production visit to the real plateau history consumer.
    shadow = ExplorationShadowRuntime("run", "home_main")
    did = "home:closed:1"
    common = dict(decision_id=did, evidence_watermark=1, evidence_stage="POST_ACTION")
    token = shadow.prepare_decision(decision_id=did, step=1, watermark=1,
        current_state=dict(common, state_id="state", state_resolution="RESOLVED"),
        frontier_evaluation=dict(common, decision_watermark=1, source_step=1, state_id="state",
            alignment_status="ALIGNED", frontier_exhausted="UNKNOWN", frontier_items=[], counts={},
            exhaustion_scope="CURRENT_STATE_CANDIDATE_FOCUS"),
        production_result=dict(decision_id=did, decision_step=1, decision_watermark=1,
            decision_closed=True, decision_stage="CLOSED_DECISION", actual_accessibility_focus_moved=True,
            accessibility_focus_authoritative=True, focus_authority="ACCESSIBILITY", visit_authority="PRODUCTION",
            new_visit_authoritative=True, visit_instance_id=iid, visit_record_status="RECORDED",
            focus_transition_status="CONFIRMED_MOVED"), repetition_state=common, scroll_evidence=common,
        safety_state={}, hard_bounds={}, recovery_budget={})
    assert shadow.finalize_decision(token=token, final_terminal=False)
    assert shadow.history.known_visit_ids == (iid,)


def test_instance_contract_keeps_distinct_bounds_and_anonymous_nodes():
    assert instance_id(focus_instance(observed(node()))) != instance_id(focus_instance(observed(node(bounds="0,0,50,50"))))
    assert instance_id(focus_instance(observed(node("same-id")))) != instance_id(focus_instance(observed(node("same-id", "0,0,50,50"))))


def test_real_local_tab_realign_update_clears_previous_identity(monkeypatch):
    current = node()
    client = SimpleNamespace(
        dump_tree=lambda **kw: [dict(className="android.widget.FrameLayout", boundsInScreen="0,0,1080,2200",
                                   visibleToUser=True, children=[deepcopy(current)])],
        target_focus_commit=lambda **kw: {"reqId": "target-current", "status": "TARGET_MATCHED", "success": True},
        get_focus=lambda **kw: deepcopy(current),
        normalize_for_comparison=lambda value: value.lower(),
    )
    previous = observed(node(OLD, "912,124,1044,268", "More options"))
    previous.update(focus_view_id=OLD, focus_bounds="912,124,1044,268", focus_class_name="android.view.View",
                    visible_label="More options", merged_announcement="More options",
                    focus_node=node(OLD, "912,124,1044,268", "More options"),
                    focus_clickable=True, focus_focusable=True, focus_effective_clickable=True)
    state = SimpleNamespace(recent_representative_signatures=[], consumed_representative_signatures=set(),
        local_tab_candidates_by_signature={}, visited_local_tabs_by_signature={},
        current_local_tab_signature="", current_local_tab_active_rid="")
    monkeypatch.setattr(flow, "log", lambda *a, **kw: None)
    row = flow._maybe_reprioritize_persistent_bottom_strip_row(row=deepcopy(previous), client=client,
        dev="OFFLINE", tab_cfg={"scenario_type": "content", "scenario_id": "home_main"}, state=state, step_idx=1)
    assert row["target_focus_request_id"] == "target-current"
    assert row["target_focus_status"] == "TARGET_MATCHED"
    assert row["actual_focus_resource_id"] == ""
    assert row["focus_view_id"] == ""
    result = reconcile(row, previous)
    assert result["reconciled_visit_instance_id"] == cursor(row, current)["instance_id"]
