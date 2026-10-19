from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tb_runner import frontier_shadow as fs
from tb_runner.frontier_scheduler import build_frontier_id


STATE_ID = "state-shadow-a"


def candidate(cid, instance):
    return {
        "candidate_id": cid,
        "edge_type": "TARGETED_FOCUS",
        "state_id": STATE_ID,
        "target_identity": {"instance_id": instance},
        "currently_present": True,
        "target_binding_status": "RESOLVED",
        "stable_order_key": [1 if cid == "a" else 0],
    }


def evidence(cid, instance, *, status="ELIGIBLE", safety="SAFE"):
    return (
        {cid: {"state_id": STATE_ID, "edge_type": "TARGETED_FOCUS",
               "action_type": "TARGETED_FOCUS", "target_instance_id": instance,
               "status": status}},
        {cid: {"state_id": STATE_ID, "edge_type": "TARGETED_FOCUS",
               "action_type": "TARGETED_FOCUS", "target_instance_id": instance,
               "status": safety}},
    )


def complete_runtime():
    runtime = fs.FrontierShadowRuntime("run-shadow", "scenario-shadow")
    runtime.source_graph_path = "result.state_graph.json"
    runtime.capture_inventory(step=0, state_id=STATE_ID,
                              candidates=[candidate("a", "target-a"), candidate("b", "target-b")],
                              inventory_complete=True,
                              observation_ref={"source_step": 0, "state_id": STATE_ID})
    return runtime


def evidence_maps():
    planners, safeties = {}, {}
    for cid, target in (("a", "target-a"), ("b", "target-b")):
        p, s = evidence(cid, target)
        planners.update(p)
        safeties.update(s)
    return planners, safeties


def state_a_visit(target, status="ALREADY_VISITED", step=0):
    return {"state_id": STATE_ID, "target_instance_id": target,
            "production_authority": True, "accessibility_focus_confirmed": True,
            "focus_transition_status": "CONFIRMED_MOVED",
            "visit_record_status": status, "ownership_status": "EXACT_MATCH", "step": step}


def pre(runtime, step=1, *, choice=None, history=None, candidates=None,
        planners=None, safeties=None, state_id=STATE_ID, complete=True):
    if candidates is None:
        candidates = [candidate("a", "target-a"), candidate("b", "target-b")]
    default_planners, default_safeties = evidence_maps()
    if planners is None:
        planners = default_planners
    if safeties is None:
        safeties = default_safeties
    if history is not None:
        runtime.history = deepcopy(history)
    return runtime.pre_decision(
        step=step,
        production_choice=choice or {"action_type": "FOCUS_NEXT_UNTARGETED"},
        focus_cursor={"instance_id": "target-current", "confirmed": True},
        current_inventory=candidates,
        state_id=state_id,
        inventory_complete=complete,
        planner_evidence=planners,
        safety_evidence=safeties,
        observation_ref={"source_step": step - 1, "state_id": state_id},
    )


def post(runtime, decision_id, step=1, *, owner="SEQUENTIAL", exact="EXACT_MATCH",
         target="", result_id="req-1", visit_status="UNVISITED",
         transition="CONFIRMED_UNCHANGED", state_changed=False):
    row = {
        "focus_transition_status": transition,
        "actual_focus_instance_id": target,
        "reconciled_visit_instance_id": target if visit_status in {"RECORDED", "ALREADY_VISITED"} else "",
        "visit_record_status": visit_status,
        "command_ack_status": "ACKED",
    }
    return runtime.post_result(
        decision_id=decision_id, step=step, result=row,
        owner=owner, ownership_status=exact, result_id=result_id,
        action_type="TARGETED_FOCUS" if owner != "SEQUENTIAL" else "FOCUS_NEXT",
        target_instance_id=target,
        before_observation_valid=True, after_observation_valid=True,
        outcome_observation_complete=True, state_changed=state_changed,
    )


def test_shared_phase6b_gate_defaults_off_and_accepts_only_shadow():
    assert fs.shadow_enabled({}) is False
    assert fs.shadow_enabled({"TB_STATE_GRAPH_MODE": "OFF"}) is False
    assert fs.shadow_enabled({"TB_STATE_GRAPH_MODE": "bogus"}) is False
    assert fs.shadow_enabled({"TB_STATE_GRAPH_MODE": "SHADOW"}) is True
    assert fs.FrontierShadowRuntime.for_run(run_id="r", scenario_id="s", output_path="x.json",
                                            environ={"TB_STATE_GRAPH_MODE": "OFF"}) is None


def test_collection_step_wrapper_keeps_off_and_shadow_production_action_identical():
    from tb_runner.collection_flow import _run_main_step_with_frontier_shadow

    expected = {"move_result": "moved", "smart_nav_req_id": "request-1"}
    outcomes = []
    for enabled in (False, True):
        client = SimpleNamespace(_phase6c2_frontier_shadow_runtime=(complete_runtime() if enabled else None))
        state = SimpleNamespace(previous_step_row={"step_index": 0},
                                forced_local_tab_target_rid="", forced_local_tab_target_label="",
                                forced_local_tab_target_action_label="")
        calls = []

        def collect():
            calls.append("called")
            return deepcopy(expected)

        row, decision = _run_main_step_with_frontier_shadow(
            client=client, state=state, step_idx=1,
            tab_cfg={"scenario_type": "content"}, collect_step_fn=collect,
        )
        outcomes.append((row, len(calls), decision is not None))
    assert outcomes == [(expected, 1, False), (expected, 1, True)]


def test_recovery_owner_requires_recovery_scoped_request_id():
    from tb_runner.collection_flow import _frontier_shadow_recovery_owner

    reused_primary_ids = {
        "smart_nav_req_id": "primary-request",
        "phase5c_primary_action_request_id": "primary-action",
        "target_focus_attempt_id": "other-target-attempt",
    }
    assert _frontier_shadow_recovery_owner(
        recovered=True, result=reused_primary_ids, step_idx=7,
    ) == ("UNKNOWN", "UNKNOWN", "frontier-decision:7:recovery-unknown")
    assert _frontier_shadow_recovery_owner(
        recovered=True, result={"recovery_action_request_id": "recovery-request"}, step_idx=7,
    ) == ("RECOVERY", "EXACT_MATCH", "recovery-request")


def test_reconciliation_inventory_adapter_uses_existing_candidates_without_io(monkeypatch):
    from tb_runner import state_graph

    observation = {
        "scenario_id": "home_main", "package_name": "com.samsung.android.oneconnect",
        "activity_name": "com.samsung.android.oneconnect.ui.scmain.SCMainActivity",
        "context_source": "window_current_focus", "navigation_context": {"bottom_tab": "home"},
        "selected_tab": {"name": "home", "verified": True, "source": "service_hierarchy_selected"},
        "display_bounds": [0, 0, 1000, 1000], "observation_coverage": "OBSERVED_FULL",
        "focus_node": {"viewIdResourceName": "app:id/focus", "className": "android.widget.Button",
                       "boundsInScreen": "[10,10][50,50]", "accessibilityFocused": True},
            "nodes": [
                {"viewIdResourceName": "com.samsung.android.oneconnect:id/dashboard_layout", "className": "android.view.View",
             "boundsInScreen": "[0,100][900,800]", "visibleToUser": True},
            {"viewIdResourceName": "app:id/item", "className": "android.widget.Button",
             "boundsInScreen": "[10,200][200,260]", "focusable": True, "visibleToUser": True},
        ],
    }
    monkeypatch.setattr(state_graph, "_raw_observation_from_row", lambda _row: deepcopy(observation))
    runtime = fs.FrontierShadowRuntime("run", "home_main")
    candidate_row = {
        "node": {"viewIdResourceName": "app:id/item", "className": "android.widget.Button",
                 "boundsInScreen": "[10,200][200,260]", "focusable": True},
        "view_id": "app:id/item", "bounds": "[10,200][200,260]",
        "class_name": "android.widget.Button", "label": "item",
    }
    fs.capture_reconciled_inventory(runtime, row={"step_index": 4},
                                    candidates=[candidate_row], scenario_id="home_main",
                                    raw_nodes=observation["nodes"])
    assert runtime._latest_inventory["source_step"] == 4
    assert runtime._latest_inventory["state_id"]
    assert runtime._latest_inventory["inventory_complete"] is True
    assert len(runtime._latest_inventory["candidates"]) == 1
    assert runtime._latest_inventory["candidates"][0]["target_binding_status"] == "RESOLVED"


def test_off_runtime_does_not_evaluate_or_write_artifact(tmp_path):
    runtime = fs.FrontierShadowRuntime("r", "s", enabled=False)
    assert runtime.pre_decision(step=1, production_choice={"action_type": "FOCUS_NEXT_UNTARGETED"}) is None
    assert runtime.write(tmp_path / "off.xlsx").name == "off.frontier_shadow.json"
    assert not (tmp_path / "off.frontier_shadow.json").exists()


def test_pre_decision_inputs_are_detached_and_result_only_affects_next_evaluation():
    runtime = complete_runtime()
    planners, safeties = evidence_maps()
    decision = pre(runtime, planners=planners, safeties=safeties)
    first = runtime.evaluations[0]
    assert first["shadow_choice"] == "b"
    assert first["comparison"] == "NOT_COMPARABLE"
    assert post(runtime, decision, target="target-b", visit_status="RECORDED",
                transition="CONFIRMED_MOVED")
    # The stored decision does not get rewritten with the post-step visit.
    assert runtime.evaluations[0]["shadow_choice"] == "b"
    second = pre(runtime, 2, planners=planners, safeties=safeties)
    assert second
    b = next(item for item in runtime.evaluations[1]["frontier_items"] if item["candidate_id"] == "b")
    assert b["visit_status"] == "RECORDED"
    assert b["status"] == "EXPLORED"


def test_production_visit_history_is_state_scoped_and_reused():
    runtime = complete_runtime()
    d1 = pre(runtime, planners=evidence_maps()[0], safeties=evidence_maps()[1])
    post(runtime, d1, target="target-b", visit_status="RECORDED", transition="CONFIRMED_MOVED")
    d2 = pre(runtime, 2, planners=evidence_maps()[0], safeties=evidence_maps()[1])
    assert d2
    b = next(item for item in runtime.evaluations[-1]["frontier_items"] if item["candidate_id"] == "b")
    assert b["state_id"] == STATE_ID
    assert b["state_visit_credit_count"] == 1
    assert b["visit_status"] == "RECORDED"


@pytest.mark.parametrize("owner", ["PRIMARY", "FALLBACK", "RECOVERY"])
def test_exact_action_owners_are_bound_to_their_target_only(owner):
    runtime = complete_runtime()
    planners, safeties = evidence_maps()
    decision = pre(runtime, planners=planners, safeties=safeties)
    assert post(runtime, decision, owner=owner, target="target-a", result_id=f"{owner}-req")
    events = runtime.history["attempt_events"]
    assert len(events) == 1
    assert events[0]["target_instance_id"] == "target-a"
    assert events[0]["ownership_status"] == "EXACT_MATCH"
    assert events[0]["frontier_id"] == build_frontier_id(STATE_ID, "TARGETED_FOCUS", "target-a")


def test_unknown_ownership_cannot_create_attempt_no_effect_or_exhaustion():
    runtime = complete_runtime()
    decision = pre(runtime)
    post(runtime, decision, owner="UNKNOWN", exact="UNKNOWN", target="target-a",
         transition="CONFIRMED_UNCHANGED", visit_status="UNVISITED")
    assert runtime.history["attempt_events"] == []
    assert runtime.history["complete"] is False
    next_id = pre(runtime, 2)
    assert next_id
    assert runtime.evaluations[-1]["frontier_exhausted"] == "UNKNOWN"
    assert runtime.evaluations[-1]["evidence_complete"] is False


def test_stale_result_does_not_update_history_or_current_decision():
    runtime = complete_runtime()
    decision = pre(runtime)
    assert runtime.post_result(decision_id=decision, step=2,
                               result={"focus_transition_status": "CONFIRMED_MOVED"},
                               owner="SEQUENTIAL", ownership_status="EXACT_MATCH",
                               result_id="stale") is False
    assert not runtime.history["attempt_events"]
    assert runtime.history["complete"] is False


def test_duplicate_result_delivery_is_deduplicated():
    runtime = complete_runtime()
    decision = pre(runtime)
    assert post(runtime, decision, owner="PRIMARY", target="target-a", result_id="same-event")
    assert not post(runtime, decision, owner="PRIMARY", target="target-a", result_id="same-event")
    assert len(runtime.history["attempt_events"]) == 1


def test_untargeted_smart_next_revisit_is_not_a_frontier_miss():
    runtime = complete_runtime()
    decision = pre(runtime, choice={"action_type": "FOCUS_NEXT_UNTARGETED"})
    assert runtime.evaluations[0]["shadow_choice"] == "b"
    assert runtime.evaluations[0]["production_choice"]["action_type"] == "FOCUS_NEXT_UNTARGETED"
    assert runtime.evaluations[0]["comparison"] == "NOT_COMPARABLE"
    post(runtime, decision, target="target-a", visit_status="ALREADY_VISITED",
         transition="CONFIRMED_MOVED")
    assert runtime.metrics["OBSERVED_REVISIT_MOVE_COUNT"] == 1
    assert runtime.metrics["FRONTIER_MISS_COUNT"] == 0


def test_targeted_equal_and_different_comparisons():
    runtime = complete_runtime()
    planners, safeties = evidence_maps()
    # Make A already visited so B is the P0 recommendation.
    history = {"complete": True, "attempt_events": [],
               "visit_events": [state_a_visit("target-a")],
               "exploration_events": [], "validated_aliases": {}, "visits_by_instance": {}}
    same = pre(runtime, choice={"action_type": "TARGETED_FOCUS", "candidate_id": "b"},
               history=history, planners=planners, safeties=safeties)
    assert runtime.evaluations[-1]["shadow_choice"] == "b"
    assert runtime.evaluations[-1]["comparison"] == "SAME"
    runtime._pending.pop(same)
    runtime.history = deepcopy(history)
    different = pre(runtime, 2, choice={"action_type": "TARGETED_FOCUS", "candidate_id": "a"},
                    planners=planners, safeties=safeties)
    assert runtime.evaluations[-1]["comparison"] == "DIFFERENT"
    assert runtime.metrics["FRONTIER_MISS_COUNT"] == 1


def test_unknown_safety_keeps_candidate_unknown_and_exhaustion_unknown():
    runtime = complete_runtime()
    planners, _ = evidence_maps()
    decision = pre(runtime, candidates=[candidate("b", "target-b")],
                   planners={"b": planners["b"]}, safeties={})
    assert decision
    evaluation = runtime.evaluations[-1]
    assert evaluation["shadow_choice"] is None
    assert evaluation["unknown_count"] == 1
    assert evaluation["frontier_exhausted"] == "UNKNOWN"


def test_no_effect_repeat_requires_exact_owner_and_complete_before_after():
    runtime = complete_runtime()
    for step in (1, 2):
        decision = pre(runtime, step, choice={"action_type": "TARGETED_FOCUS", "candidate_id": "a"})
        row = {"focus_transition_status": "CONFIRMED_UNCHANGED",
               "actual_focus_instance_id": "target-current", "visit_record_status": "UNVISITED",
               "command_ack_status": "ACKED"}
        runtime.post_result(decision_id=decision, step=step, result=row,
                            owner="TARGETED", ownership_status="EXACT_MATCH",
                            result_id=f"target-{step}", action_type="TARGETED_FOCUS",
                            target_instance_id="target-a", before_observation_valid=True,
                            after_observation_valid=True, outcome_observation_complete=True,
                            state_changed=False)
    assert runtime.metrics["NO_EFFECT_REPEAT_COUNT"] == 1
    assert [event["ownership_status"] for event in runtime.history["attempt_events"]] == ["EXACT_MATCH"] * 2


def test_inventory_truncation_is_conservative(monkeypatch):
    monkeypatch.setattr(fs, "MAX_FRONTIER_ITEMS", 1)
    runtime = complete_runtime()
    # The capture cap is enforced before this pre-decision snapshot.
    cached = runtime._latest_inventory
    assert len(cached["candidates"]) == 1
    assert cached["inventory_complete"] is False
    assert "MAX_FRONTIER_ITEMS" in runtime.truncation_reasons
    pre(runtime)
    assert runtime.evaluations[-1]["frontier_exhausted"] == "UNKNOWN"


def test_evaluation_cap_preserves_unknown_and_does_not_raise(monkeypatch):
    monkeypatch.setattr(fs, "MAX_EVALUATIONS", 1)
    runtime = complete_runtime()
    assert pre(runtime, 1)
    assert pre(runtime, 2) is None
    doc = runtime.artifact()
    assert doc["truncated"] is True
    assert "MAX_EVALUATIONS" in doc["truncation_reasons"]
    assert doc["evaluations"][0]["frontier_exhausted"] == "UNKNOWN"


def test_artifact_contract_linkage_and_determinism(tmp_path):
    def create():
        runtime = complete_runtime()
        pre(runtime)
        runtime.post_result(decision_id=runtime.evaluations[0]["decision_id"], step=1,
                            result={"focus_transition_status": "CONFIRMED_UNCHANGED"},
                            owner="SEQUENTIAL", ownership_status="EXACT_MATCH", result_id="smart-1")
        return runtime

    first, second = create(), create()
    assert first.artifact() == second.artifact()
    path = first.write(tmp_path / "result.xlsx")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "result.frontier_shadow.json"
    assert doc["schema_version"] == "phase6-frontier-shadow.v1"
    assert doc["frontier_evaluation_schema_version"] == "phase6-frontier-evaluation.v1"
    assert doc["mode"] == doc["authority"] == "SHADOW_ONLY"
    assert doc["production_control"] is False
    assert doc["termination_control"] is False
    assert doc["scroll_control"] is False
    assert doc["safety_control"] is False
    assert doc["source_graph_artifact"] == "result.state_graph.json"


def test_artifact_byte_limit_truncates_without_claiming_exhaustion(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "MAX_ARTIFACT_BYTES", 2_000)
    runtime = complete_runtime()
    pre(runtime)
    runtime.evaluations[0]["reason_codes"] = ["X" * 1000 for _ in range(20)]
    path = runtime.write(tmp_path / "large.xlsx")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert path.stat().st_size <= 2_000
    assert doc["truncated"] is True
    assert doc["evidence_complete"] is False
    assert "MAX_ARTIFACT_BYTES" in doc["truncation_reasons"]


def test_shadow_evaluator_failure_isolated_from_production_action(monkeypatch):
    runtime = complete_runtime()
    monkeypatch.setattr(fs, "evaluate_frontier", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("shadow")))
    production = {"calls": 0}

    def production_action():
        production["calls"] += 1
        return {"result": "unchanged"}

    before = production_action()
    assert pre(runtime) is None
    after = production_action()
    assert before == after == {"result": "unchanged"}
    assert production["calls"] == 2
    assert runtime.failures[0]["phase"] == "pre_decision"
    assert runtime.artifact()["evidence_complete"] is False


def test_ambiguous_production_target_is_not_compared_as_candidate():
    runtime = complete_runtime()
    decision = pre(runtime, choice={"action_type": "TARGETED_FOCUS"})
    assert decision
    assert runtime.evaluations[-1]["comparison"] == "UNKNOWN"
    assert runtime.metrics["FRONTIER_MISS_COUNT"] == 0


@pytest.mark.parametrize("action", ["TAB_CHANGE_TARGETED", "OPTIONAL_EXPANSION", "OTHER"])
def test_out_of_scope_production_actions_are_not_comparable(action):
    runtime = complete_runtime()
    pre(runtime, choice={"action_type": action})
    assert runtime.evaluations[-1]["comparison"] == "NOT_COMPARABLE"


def test_production_candidate_adapter_reuses_instance_v1_identity():
    from tb_runner.traversal_reliability import instance_id

    candidate_row = {"view_id": "app:id/item", "bounds": "[1,2][30,40]",
                     "class_name": "android.widget.Button", "label": "Go"}
    adapted = fs.production_candidate(state_id=STATE_ID, scenario_id="scenario-shadow",
                                      candidate=candidate_row)
    assert adapted is not None
    assert adapted["target_identity"]["instance_id"] == instance_id({
        "scenario_id": "scenario-shadow", "view_id": "app:id/item",
        "bounds": "[1,2][30,40]", "class_name": "android.widget.Button",
    })
    assert fs.production_candidate(state_id=STATE_ID, scenario_id="scenario-shadow",
                                   candidate={"label": "Go"}) is None


def test_exact_revisit_with_never_attempted_p0_is_counted_only_when_comparable():
    runtime = complete_runtime()
    planners, safeties = evidence_maps()
    history = {"complete": True, "attempt_events": [],
               "visit_events": [state_a_visit("target-a")],
               "exploration_events": [], "validated_aliases": {}, "visits_by_instance": {}}
    pre(runtime, choice={"action_type": "TARGETED_FOCUS", "candidate_id": "a"},
        history=history, planners=planners, safeties=safeties)
    assert runtime.metrics["REVISIT_SELECTION_COUNT"] == 1
    assert runtime.metrics["COMPARABLE_REVISIT_SELECTION_COUNT"] == 1
    assert runtime.metrics["NEVER_ATTEMPTED_AVAILABLE_WHEN_REVISIT_SELECTED"] == 1
