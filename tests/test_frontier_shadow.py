from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from phase6d_capture_support import attach_capture_authority
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
    current_action = "SMART_NEXT" if owner == "SEQUENTIAL" else "TARGETED_FOCUS"
    row = {
        "phase6_current_action_type": current_action,
        "focus_transition_status": transition,
        "actual_focus_instance_id": target,
        "reconciled_visit_instance_id": target if visit_status in {"RECORDED", "ALREADY_VISITED"} else "",
        "visit_record_status": visit_status,
        "command_ack_status": "ACKED",
        "smart_nav_req_id": result_id if current_action == "SMART_NEXT" else "",
        "target_focus_request_id": result_id if current_action == "TARGETED_FOCUS" else "",
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


def test_canonical_request_selector_never_uses_attempt_or_operation_identity():
    assert fs.canonical_action_request_id({
        "target_focus_attempt_id": "attempt-1", "controlled_focus_operation_id": "operation-1",
    }) == ""
    assert fs.canonical_action_request_id({
        "controlled_focus_request_id": "controlled-1",
        "target_focus_attempt_id": "attempt-1",
        "phase6_current_action_type": "CONTROLLED_FOCUS",
    }) == "controlled-1"
    assert fs.canonical_action_request_id({
        "target_focus_request_id": "target-1", "target_focus_attempt_id": "attempt-1",
        "phase6_current_action_type": "TARGETED_FOCUS",
    }) == "target-1"
    assert fs.canonical_action_request_id(
        {"smart_nav_req_id": "smart-next-1"}, "SMART_NEXT"
    ) == "smart-next-1"


def test_action_scoped_request_selection_does_not_cross_borrow_mixed_row_receipts():
    mixed = {
        "phase6_current_action_type": "TARGETED_FOCUS",
        "smart_nav_req_id": "request-A",
        "target_focus_attempt_id": "attempt-B",
        "target_focus_request_id": "",
        "controlled_focus_operation_id": "operation-B",
    }
    assert fs.canonical_action_request_id(mixed) == ""
    assert fs.canonical_action_request_id(mixed, "TARGETED_FOCUS") == ""

    targeted = {**mixed, "target_focus_request_id": "request-B"}
    assert fs.canonical_action_request_id(targeted) == "request-B"

    smart_next_with_stale_target = {
        **targeted,
        "phase6_current_action_type": "SMART_NEXT",
        "smart_nav_req_id": "request-C",
    }
    assert fs.canonical_action_request_id(smart_next_with_stale_target) == "request-C"

    controlled = {
        "phase6_current_action_type": "CONTROLLED_FOCUS",
        "controlled_focus_request_id": "request-D",
        "target_focus_request_id": "stale-target-request",
    }
    assert fs.canonical_action_request_id(controlled) == "request-D"
    assert fs.canonical_action_request_id(
        {"phase6_current_action_type": "TARGETED_FOCUS", "target_focus_attempt_id": "attempt-E",
         "controlled_focus_operation_id": "operation-E", "smart_nav_req_id": "request-A"}
    ) == ""


def test_real_post_result_audit_and_history_share_request_identity_and_separate_attempt():
    runtime = complete_runtime()
    decision = runtime.pre_decision(
        step=1, production_choice={"action_type": "TARGETED_FOCUS"},
        current_inventory=[candidate("a", "target-a"), candidate("b", "target-b")],
        state_id=STATE_ID, inventory_complete=True,
        observation_ref={"source_step": 0, "state_id": STATE_ID,
                         "request_id": "request-current"},
    )
    assert decision
    runtime.capture_inventory(
        step=0, state_id=STATE_ID,
        candidates=[candidate("a", "target-a"), candidate("b", "target-b")],
        inventory_complete=True,
        observation_ref={"source_step": 0, "state_id": STATE_ID,
                         "request_id": "request-current"},
    )
    frontier_decision = runtime.evaluate_post_action(
        step=0, decision_id="closed-current", decision_watermark=1,
        state_id=STATE_ID, result_request_id="request-current",
    )
    assert frontier_decision["source_request_id"] == "request-current"
    result = {
        "controlled_focus_request_id": "request-current",
        "phase6_current_action_type": "CONTROLLED_FOCUS",
        "target_focus_attempt_id": "attempt-current",
        "controlled_focus_operation_id": "operation-current",
        "focus_transition_status": "CONFIRMED_MOVED",
        "actual_focus_instance_id": "target-a",
        "visit_record_status": "UNVISITED",
        "command_ack_status": "ACKED",
    }

    assert runtime.post_result(
        decision_id=decision, step=1, result=result, owner="TARGETED",
        ownership_status="EXACT_MATCH", result_id="request-current",
        action_type="TARGETED_FOCUS", target_instance_id="target-a",
        before_observation_valid=True, after_observation_valid=True,
        outcome_observation_complete=True, state_changed=False,
    )

    audit = runtime.evaluations[0]["action_result"]
    history = runtime.history["attempt_events"]
    assert audit["result_id"] == "request-current"
    assert audit["request_id"] == "request-current"
    assert audit["attempt_id"] == "attempt-current"
    assert audit["operation_id"] == "operation-current"
    assert runtime.evaluations[0]["observation_ref"]["request_id"] == "request-current"
    assert len(history) == 1
    assert history[0]["request_id"] == "request-current"
    assert history[0]["attempt_id"] == "attempt-current"
    assert history[0]["operation_id"] == "operation-current"


def test_attempt_only_post_result_is_unowned_and_request_alignment_is_incomplete(monkeypatch):
    runtime = fs.FrontierShadowRuntime("run-shadow", "scenario-shadow")
    runtime.capture_inventory(
        step=1, state_id=STATE_ID, candidates=[candidate("a", "target-a")],
        inventory_complete=True, observation_ref={"request_id": "request-inventory"},
    )
    monkeypatch.setattr("tb_runner.frontier_scheduler.evaluate_frontier",
                        lambda *args, **kwargs: pytest.fail("missing request must not evaluate"))
    result = runtime.evaluate_post_action(
        step=1, decision_id="closed-1", decision_watermark=1,
        state_id=STATE_ID, result_request_id="",
    )
    assert result["alignment_status"] == "INCOMPLETE"
    assert "POST_ACTION_REQUEST_ID_MISSING" in result["alignment_reasons"]
    assert result["source_request_id"] == "request-inventory"

    decision = runtime.pre_decision(
        step=2, production_choice={"action_type": "TARGETED_FOCUS"},
        current_inventory=[candidate("a", "target-a")], state_id=STATE_ID,
        inventory_complete=True,
    )
    assert decision
    assert runtime.post_result(
        decision_id=decision, step=2,
        result={"target_focus_attempt_id": "attempt-only"}, owner="TARGETED",
        ownership_status="EXACT_MATCH", result_id="decision-result",
        action_type="TARGETED_FOCUS", target_instance_id="target-a",
    )
    audit = runtime.evaluations[-1]["action_result"]
    assert audit["request_id"] is None
    assert audit["attempt_id"] == "attempt-only"
    assert audit["ownership_status"] == "UNKNOWN"
    assert runtime.history["attempt_events"] == []
    assert runtime.history["complete"] is False


def test_reconciliation_inventory_adapter_uses_existing_candidates_without_io(monkeypatch):
    from tb_runner import state_graph

    observation = {
        "scenario_id": "home_main", "package_name": "com.samsung.android.oneconnect",
        "activity_name": "com.samsung.android.oneconnect.ui.scmain.SCMainActivity",
        "context_source": "helper_tree_component", "navigation_context": {"bottom_tab": "home"},
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
    attach_capture_authority(observation, production=True)
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
    assert runtime._latest_inventory["candidates"][0]["target_binding_status"] == "UNKNOWN"


def test_frontier_authority_accepts_decoder_token_and_rejects_self_hashed_mapping():
    from talkback_lib.reliable_hierarchy_schema import capture_canonical_sha256

    raw = attach_capture_authority({
        "scenario_id": "home_main", "package_name": "com.samsung.android.oneconnect",
        "capture_root_bounds": [0, 0, 1000, 1000], "nodes": [],
    }, production=True)
    envelope = raw["production_observation_envelope"]
    assert fs._valid_capture_authority(raw, envelope, raw["capture_id"])

    forged = deepcopy(raw["capture_authority"])
    forged.pop("validation_seal", None)
    core_fields = (
        "schema_version", "canonicalization", "request_id", "process_epoch",
        "generation", "service_instance_id", "capture_sequence", "root_ref",
        "root_digest", "candidate_digest", "hierarchy_package_name", "hierarchy_window_id",
        "hierarchy_root_class_name", "hierarchy_root_source_node_id", "hierarchy_root_bounds",
    )
    forged["capture_key"] = capture_canonical_sha256(
        {key: forged[key] for key in core_fields})
    forged["validation_seal"] = capture_canonical_sha256(forged)
    raw["capture_authority"] = forged
    envelope["capture_authority"] = deepcopy(forged)

    assert not fs._valid_capture_authority(raw, envelope, raw["capture_id"])


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
               "phase6_current_action_type": "TARGETED_FOCUS",
               "command_ack_status": "ACKED", "target_focus_request_id": f"target-{step}"}
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


def test_post_action_frontier_reuses_only_same_step_state_and_action_request(monkeypatch):
    runtime = fs.FrontierShadowRuntime("run-shadow", "scenario-shadow")
    runtime.capture_inventory(
        step=7, state_id=STATE_ID,
        candidates=[candidate("a", "target-a")], inventory_complete=True,
        observation_ref={"request_id": "action-7", "source_step": 7},
    )
    calls = []

    class Evaluation:
        def to_dict(self):
            return {
                "decision_authority": "NONE", "state_id": STATE_ID,
                "frontier_exhausted": "NO", "evidence_complete": False,
                "history_complete": True, "inventory_complete": True,
                "truncated": False, "counts": {"eligible_count": 1},
                "frontier_items": [candidate("a", "target-a")],
            }

    def evaluate(state, candidates, history, planners, safeties, *, focus_cursor):
        calls.append((state, candidates, planners, safeties, focus_cursor))
        return Evaluation()

    monkeypatch.setattr("tb_runner.frontier_scheduler.evaluate_frontier", evaluate)
    result = runtime.evaluate_post_action(
        step=7, decision_id="closed-7", decision_watermark=7,
        state_id=STATE_ID, focus_cursor={"instance_id": "focus-7", "confirmed": True},
        result_request_id="action-7",
    )
    assert result["alignment_status"] == "ALIGNED"
    assert result["evidence_stage"] == "POST_ACTION"
    assert result["source_step"] == 7
    assert result["decision_id"] == "closed-7"
    assert result["evidence_watermark"] == 7
    assert result["frontier_exhausted"] == "NO"
    assert len(calls) == 1
    assert calls[0][2:4] == ({}, {})  # No planner/safety proof is manufactured.
    assert runtime.history["complete"] is True


def test_post_action_frontier_fails_closed_for_old_snapshot_or_mismatched_request(monkeypatch):
    runtime = fs.FrontierShadowRuntime("run-shadow", "scenario-shadow")
    runtime.capture_inventory(
        step=7, state_id=STATE_ID,
        candidates=[candidate("a", "target-a")], inventory_complete=True,
        observation_ref={"request_id": "action-7"},
    )
    monkeypatch.setattr("tb_runner.frontier_scheduler.evaluate_frontier",
                        lambda *args, **kwargs: pytest.fail("stale inventory must not be evaluated"))
    old_step = runtime.evaluate_post_action(
        step=8, decision_id="closed-8", decision_watermark=8,
        state_id=STATE_ID, result_request_id="action-8",
    )
    wrong_request = runtime.evaluate_post_action(
        step=7, decision_id="closed-7", decision_watermark=7,
        state_id=STATE_ID, result_request_id="other-request",
    )
    assert old_step["frontier_exhausted"] == "UNKNOWN"
    assert old_step["alignment_status"] == "INCOMPLETE"
    assert "POST_ACTION_INVENTORY_UNAVAILABLE" in old_step["alignment_reasons"]
    assert wrong_request["frontier_exhausted"] == "UNKNOWN"
    assert wrong_request["alignment_status"] == "INCOMPLETE"
    assert "POST_ACTION_REQUEST_ID_MISMATCH" in wrong_request["alignment_reasons"]


def test_post_action_snapshot_invalidation_is_stale_and_does_not_call_scheduler(monkeypatch):
    runtime = fs.FrontierShadowRuntime("run-shadow", "scenario-shadow")
    runtime.capture_inventory(step=2, state_id=STATE_ID,
        candidates=[candidate("a", "target-a")], inventory_complete=True)
    monkeypatch.setattr("tb_runner.frontier_scheduler.evaluate_frontier",
                        lambda *args, **kwargs: pytest.fail("invalidated snapshot must not be evaluated"))
    result = runtime.evaluate_post_action(
        step=2, decision_id="closed-2", decision_watermark=2,
        state_id=STATE_ID, snapshot_valid=False,
    )
    assert result["alignment_status"] == "STALE"
    assert result["evidence_stage"] == "STALE"
    assert result["frontier_exhausted"] == "UNKNOWN"
    assert result["evidence_complete"] is False
