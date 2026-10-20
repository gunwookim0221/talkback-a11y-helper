from copy import deepcopy
import json
from types import SimpleNamespace

from tb_runner.exploration_progress import (
    CURRENT_SCOPE,
    ExplorationDecision,
    ExplorationHistory,
    ExplorationPolicy,
    StatePlateau,
)
from tb_runner.exploration_shadow import (
    EXPLORATION_SHADOW_SCHEMA_VERSION,
    ExplorationShadowRuntime,
    compare_production_and_shadow,
    normalize_production_decision,
)


STATE = "state-a"


def _inputs(step, *, state_id=STATE, frontier_status="UNKNOWN", items=None,
            unknown_count=0, evidence_complete=None, production=None,
            scroll_status="NOT_APPLICABLE", hard_bounds=None,
            safety_state=None, recovery_budget=None, current_stage="POST_ACTION",
            frontier_stage="POST_ACTION", current_watermark=None,
            frontier_watermark=None, current_decision_id=None,
            frontier_decision_id=None, source_step=None, alignment="ALIGNED"):
    decision_id = f"scenario:closed:{step}"
    items = list(items or [])
    counts = {
        "eligible_count": sum(item.get("status") == "ELIGIBLE" for item in items),
        "unknown_count": unknown_count + sum(item.get("status") == "UNKNOWN" for item in items),
        "never_attempted_count": 0,
        "retryable_count": 0,
        "revisit_only_count": 0,
        "policy_limited_count": 0,
        "blocked_count": sum(item.get("status") == "BLOCKED" for item in items),
    }
    complete = frontier_status == "YES" if evidence_complete is None else evidence_complete
    current = {
        "state_id": state_id,
        "state_resolution": "RESOLVED" if state_id else "UNRESOLVED",
        "decision_id": current_decision_id or decision_id,
        "evidence_watermark": step if current_watermark is None else current_watermark,
        "evidence_stage": current_stage,
    }
    frontier = {
        "decision_id": frontier_decision_id or decision_id,
        "evidence_watermark": step if frontier_watermark is None else frontier_watermark,
        "decision_watermark": step if frontier_watermark is None else frontier_watermark,
        "evidence_stage": frontier_stage,
        "source_step": step if source_step is None else source_step,
        "state_id": state_id,
        "alignment_status": alignment,
        "exhaustion_scope": CURRENT_SCOPE,
        "frontier_exhausted": frontier_status,
        "evidence_complete": complete,
        "history_complete": True,
        "inventory_complete": True,
        "truncated": False,
        "frontier_items": deepcopy(items),
        "counts": counts,
        "exhaustion_reason_codes": [],
        "exhaustion_proof": {"complete": complete},
    }
    prod = {
        "decision_id": decision_id,
        "decision_step": step,
        "decision_watermark": step,
        "decision_closed": True,
        "decision_stage": "CLOSED_DECISION",
        "outcome": "CONTINUE",
        "final_terminal": False,
        "final_terminal_reason": "",
        "actual_accessibility_focus_moved": False,
        "accessibility_focus_authoritative": False,
        "focus_authority": "UNKNOWN",
    }
    prod.update(production or {})
    scroll = {
        "decision_id": decision_id,
        "evidence_watermark": step,
        "evidence_stage": "POST_ACTION",
        "scope": CURRENT_SCOPE,
        "status": scroll_status,
        "absence_proven": scroll_status == "SCROLL_ABSENT_PROVEN_FOR_SCOPE",
        "applies_to_scope": scroll_status == "NOT_APPLICABLE",
    }
    return {
        "decision_id": decision_id,
        "step": step,
        "watermark": step,
        "current_state": current,
        "frontier_evaluation": frontier,
        "production_result": prod,
        "repetition_state": {"decision_id": decision_id, "evidence_watermark": step,
                             "evidence_stage": "POST_ACTION"},
        "scroll_evidence": scroll,
        "safety_state": dict(safety_state or {}),
        "hard_bounds": dict(hard_bounds or {}),
        "recovery_budget": dict(recovery_budget or {}),
    }


def _prepare(runtime, **kwargs):
    args = _inputs(**kwargs)
    return runtime.prepare_decision(
        decision_id=args["decision_id"], step=args["step"], watermark=args["watermark"],
        current_state=args["current_state"], frontier_evaluation=args["frontier_evaluation"],
        production_result=args["production_result"], repetition_state=args["repetition_state"],
        scroll_evidence=args["scroll_evidence"], safety_state=args["safety_state"],
        hard_bounds=args["hard_bounds"], recovery_budget=args["recovery_budget"],
    )


def _eligible(frontier_id="frontier-a", state_id=STATE):
    return {"frontier_id": frontier_id, "state_id": state_id, "status": "ELIGIBLE",
            "priority_class": "P0", "provisional": False,
            "stable_identity": True, "evidence_sufficient": True}


def test_runtime_is_shadow_gated_and_keeps_production_control_disabled():
    assert ExplorationShadowRuntime.for_run(run_id="r", scenario_id="s", environ={"TB_STATE_GRAPH_MODE": "OFF"}) is None
    runtime = ExplorationShadowRuntime.for_run(run_id="r", scenario_id="s", environ={"TB_STATE_GRAPH_MODE": "SHADOW"})
    assert runtime is not None
    artifact = runtime.artifact()
    assert artifact["mode"] == artifact["authority"] == "SHADOW_ONLY"
    assert artifact["production_control"] is False
    assert artifact["scheduler_control"] is False
    assert artifact["termination_control"] is False
    assert artifact["scroll_control"] is False
    assert artifact["safety_control"] is False


def test_closed_post_action_frontier_yes_can_recommend_current_scope_only():
    runtime = ExplorationShadowRuntime("r", "s", policy=ExplorationPolicy())
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
        state_plateaus=(StatePlateau(STATE, 0),), history_item_count=1)
    args = _inputs(1, frontier_status="YES", evidence_complete=True,
                   scroll_status="SCROLL_ABSENT_PROVEN_FOR_SCOPE")
    before_prod = deepcopy(args["production_result"])
    token = _prepare(runtime, step=1, frontier_status="YES", evidence_complete=True,
                     scroll_status="SCROLL_ABSENT_PROVEN_FOR_SCOPE")
    assert token.startswith("scenario:closed:1@1#")
    assert runtime.finalize_decision(token=token, final_terminal=False)
    item = runtime.decisions[0]
    assert item["shadow_decision"] == ExplorationDecision.COMPLETE_CURRENT_SCOPE.value
    assert item["scope"] == "CURRENT_STATE_CANDIDATE_FOCUS"
    assert item["production"]["outcome"] == "CONTINUE"
    assert item["production"]["final_terminal"] is False
    assert item["comparison_category"] == "SHADOW_COMPLETE_PRODUCTION_CONTINUED"
    assert runtime.metrics["SHADOW_SCOPE_COMPLETE_COUNT"] == 1
    assert runtime.history.closed_decision_count == 1
    assert before_prod == args["production_result"]


def test_post_action_stage_watermark_and_decision_identity_are_required():
    cases = [
        {"current_stage": "PRE_ACTION"},
        {"frontier_stage": "PRE_ACTION"},
        {"current_watermark": 0},
        {"frontier_watermark": 0},
        {"current_decision_id": "old-decision"},
        {"frontier_decision_id": "old-decision"},
        {"source_step": 0},
        {"alignment": "STALE"},
    ]
    for changes in cases:
        runtime = ExplorationShadowRuntime("r", "s")
        token = _prepare(runtime, step=1, **changes)
        assert token
        assert not runtime.finalize_decision(token=token, final_terminal=False)
        item = runtime.decisions[0]
        assert item["stale_status"] == "YES"
        assert item["decision_evidence_usable"] is False
        assert item["shadow_decision"] == "UNKNOWN"
        assert runtime.history.closed_decision_count == 0
        assert runtime.metrics["VALID_CLOSED_DECISION_COUNT"] == 0


def test_overlay_or_recovery_after_capture_invalidates_without_committing_history():
    runtime = ExplorationShadowRuntime("r", "s")
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
        state_plateaus=(StatePlateau(STATE, 0),), history_item_count=1)
    token = _prepare(runtime, step=1, frontier_status="YES", evidence_complete=True,
                     scroll_status="SCROLL_ABSENT_PROVEN_FOR_SCOPE")
    assert not runtime.finalize_decision(
        token=token, final_terminal=False, snapshot_invalidated=True,
        invalidation_reason="OPTIONAL_OVERLAY_ACTION",
    )
    record = runtime.decisions[0]
    assert record["original_shadow_decision"] == ExplorationDecision.COMPLETE_CURRENT_SCOPE.value
    assert record["shadow_decision"] == "UNKNOWN"
    assert record["comparison_category"] == "STALE_EVIDENCE"
    assert record["stale_reasons"] == ["OPTIONAL_OVERLAY_ACTION"]
    assert runtime.history.closed_decision_count == 0
    assert runtime.metrics["SHADOW_SCOPE_COMPLETE_COUNT"] == 0
    assert runtime.metrics["STALE_DECISION_COUNT"] == 1


def test_frontier_left_after_plateau_recommends_redirect_without_control():
    runtime = ExplorationShadowRuntime("r", "s", policy=ExplorationPolicy(
        state_plateau_threshold=3, run_plateau_threshold=3))
    for step in range(1, 5):
        token = _prepare(runtime, step=step, frontier_status="NO", items=[_eligible()], evidence_complete=False)
        assert token
        assert runtime.finalize_decision(token=token, final_terminal=False)
    record = runtime.decisions[-1]
    assert record["shadow_decision"] == ExplorationDecision.REDIRECT_FRONTIER.value
    assert record["frontier"]["frontier_exhausted"] == "NO"
    assert runtime.metrics["SHADOW_REDIRECT_RECOMMENDATION_COUNT"] == 1
    assert runtime.metrics["PRODUCTION_TERMINATED_WITH_FRONTIER_NO_COUNT"] == 0
    assert runtime.artifact()["termination_control"] is False


def test_unknown_frontier_recovery_is_bounded_by_stable_evidence_identity():
    runtime = ExplorationShadowRuntime("r", "s")
    runtime.history = ExplorationHistory(
        known_state_ids=(STATE,), state_plateaus=(StatePlateau(STATE, 0),), history_item_count=1)
    unknown = {"frontier_id": "unknown-a", "state_id": STATE, "status": "UNKNOWN",
               "priority_class": "P3", "provisional": True}
    first = _prepare(runtime, step=1, items=[unknown], unknown_count=1,
                     recovery_budget={"remaining": 1, "could_resolve": True})
    assert runtime.finalize_decision(token=first, final_terminal=False)
    assert runtime.decisions[-1]["shadow_decision"] == ExplorationDecision.RECOVER_EVIDENCE.value
    second = _prepare(runtime, step=2, items=[unknown], unknown_count=1,
                      recovery_budget={"remaining": 1, "could_resolve": True})
    assert runtime.finalize_decision(token=second, final_terminal=False)
    assert runtime.decisions[-1]["shadow_decision"] == ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN.value
    assert runtime.history.closed_decision_count == 2


def test_recovery_action_after_capture_marks_decision_stale_and_never_grants_completion():
    runtime = ExplorationShadowRuntime("r", "s")
    token = _prepare(runtime, step=1, frontier_status="YES", evidence_complete=True,
                     scroll_status="SCROLL_ABSENT_PROVEN_FOR_SCOPE")
    runtime.finalize_decision(token=token, final_terminal=True,
                              final_terminal_reason="safety_limit",
                              snapshot_invalidated=True,
                              invalidation_reason="RECOVERY_ACTION_AFTER_PRIMARY_RESULT")
    record = runtime.decisions[0]
    assert record["shadow_decision"] == "UNKNOWN"
    assert record["comparison_category"] == "STALE_EVIDENCE"
    assert runtime.metrics["SHADOW_SCOPE_COMPLETE_COUNT"] == 0
    assert runtime.metrics["VALID_CLOSED_DECISION_COUNT"] == 0


def test_foreign_scope_observation_cannot_complete_exploration_scope():
    from talkback_lib.exploration_evidence_clock import EvidenceClock

    active_clock = EvidenceClock(scope_id="active-scope")
    foreign_clock = EvidenceClock(scope_id="foreign-scope")
    foreign_observation = foreign_clock.finish_observation(foreign_clock.begin_observation())
    runtime = ExplorationShadowRuntime("r", "s", evidence_clock=active_clock)
    args = _inputs(1, frontier_status="YES", evidence_complete=True,
                   scroll_status="SCROLL_ABSENT_PROVEN_FOR_SCOPE")
    token = runtime.prepare_decision(**args, observation_evidence=foreign_observation)
    assert token
    assert not runtime.finalize_decision(token=token, final_terminal=False)
    record = runtime.decisions[-1]
    assert record["evidence_scope_id"] == "foreign-scope"
    assert record["stale_status"] == "YES"
    assert "OBSERVATION_SCOPE_MISMATCH" in record["stale_reasons"]
    assert record["completion_evidence_complete"] is False
    assert record["frontier"]["completion_evidence_complete"] is False
    assert record["shadow_decision"] == "UNKNOWN"


def test_same_scope_observation_remains_current_for_completion():
    from talkback_lib.exploration_evidence_clock import EvidenceClock

    clock = EvidenceClock(scope_id="current-scope")
    captured = clock.finish_observation(clock.begin_observation())
    runtime = ExplorationShadowRuntime("r", "s", evidence_clock=clock)
    args = _inputs(1, frontier_status="YES", evidence_complete=True,
                   scroll_status="SCROLL_ABSENT_PROVEN_FOR_SCOPE")
    token = runtime.prepare_decision(**args, observation_evidence=captured)
    assert token
    assert runtime.finalize_decision(token=token, final_terminal=False)
    record = runtime.decisions[-1]
    assert record["evidence_scope_id"] == "current-scope"
    assert record["completion_evidence_complete"] is True


def test_cursor_only_accessibility_focus_is_not_meaningful_progress_or_visit_credit():
    runtime = ExplorationShadowRuntime("r", "s")
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
                                         state_plateaus=(StatePlateau(STATE, 0),),
                                         history_item_count=1)
    for step in range(1, 3):
        token = _prepare(runtime, step=step, production={
            "actual_accessibility_focus_moved": True,
            "accessibility_focus_authoritative": True,
            "focus_authority": "ACCESSIBILITY",
        })
        runtime.finalize_decision(token=token, final_terminal=False)
    assert runtime.metrics["CURSOR_ONLY_PROGRESS_COUNT"] == 2
    assert runtime.metrics["MEANINGFUL_PROGRESS_COUNT"] == 0
    assert runtime.metrics["REVISIT_WITH_FRONTIER_AVAILABLE_COUNT"] == 0
    assert runtime.history.run_plateau_age == 2


def test_only_production_authoritative_new_visit_resets_plateau():
    runtime = ExplorationShadowRuntime("r", "s")
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
        state_plateaus=(StatePlateau(STATE, 3),), run_plateau_age=3, history_item_count=1)
    runtime.policy = ExplorationPolicy(state_plateau_threshold=3, run_plateau_threshold=3)
    token = _prepare(runtime, step=1, production={
        "visit_record_status": "RECORDED", "visit_outcome": "NEW_VISIT",
        "visit_authority": "PRODUCTION", "visit_instance_id": "visit-1",
        "new_visit_authoritative": True,
    })
    runtime.finalize_decision(token=token, final_terminal=False)
    assert runtime.decisions[0]["evaluation"]["progress_types"] == ["EXPLORATION_PROGRESS"]
    assert runtime.history.run_plateau_age == 0
    assert runtime.metrics["PLATEAU_EXIT_COUNT"] == 1
    assert runtime.metrics["STATE_PLATEAU_EXIT_COUNT"] == 1
    assert runtime.metrics["RUN_PLATEAU_EXIT_COUNT"] == 1


def test_unverified_visit_and_input_focus_do_not_create_progress():
    runtime = ExplorationShadowRuntime("r", "s")
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
        state_plateaus=(StatePlateau(STATE, 0),), history_item_count=1)
    token = _prepare(runtime, step=1, production={
        "new_visit_authoritative": False, "visit_outcome": "NEW_VISIT",
        "visit_authority": "UNKNOWN", "visit_instance_id": "fake-visit",
        "input_focused": True, "actual_accessibility_focus_moved": False,
    })
    runtime.finalize_decision(token=token, final_terminal=False)
    assert runtime.decisions[0]["evaluation"]["progress_types"] == ["NO_MEANINGFUL_PROGRESS"]
    assert runtime.history.run_plateau_age == 1


def test_duplicate_or_nonmonotonic_watermark_cannot_double_count_metrics():
    runtime = ExplorationShadowRuntime("r", "s")
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
        state_plateaus=(StatePlateau(STATE, 0),), history_item_count=1)
    first = _prepare(runtime, step=1, frontier_status="YES", evidence_complete=True,
                     scroll_status="SCROLL_ABSENT_PROVEN_FOR_SCOPE")
    duplicate = _prepare(runtime, step=1, frontier_status="YES", evidence_complete=True,
                         scroll_status="SCROLL_ABSENT_PROVEN_FOR_SCOPE")
    assert runtime.finalize_decision(token=first, final_terminal=False)
    assert not runtime.finalize_decision(token=duplicate, final_terminal=False)
    assert runtime.metrics["VALID_CLOSED_DECISION_COUNT"] == 1
    assert runtime.metrics["SHADOW_SCOPE_COMPLETE_COUNT"] == 1
    assert runtime.metrics["STALE_DECISION_COUNT"] == 1
    assert runtime.history.closed_decision_count == 1


def test_hard_bound_and_error_take_priority_in_comparison():
    hard = compare_production_and_shadow(
        production={"outcome": "PRODUCTION_TERMINATED", "final_terminal_reason": "safety_limit"},
        shadow_decision=ExplorationDecision.TERMINATE_HARD_BOUND.value,
        frontier_status="NO", hard_bound_reached=True)
    assert hard == ("SAME_INTENT", "MAX_STEPS_BOUND_MATCH")
    err = compare_production_and_shadow(
        production={"outcome": "PRODUCTION_TERMINATED", "authoritative_error": True},
        shadow_decision=ExplorationDecision.TERMINATE_ERROR.value,
        frontier_status="UNKNOWN")
    assert err == ("SAME_INTENT", "ERROR_TERMINAL_MATCH")
    late_error = compare_production_and_shadow(
        production={"outcome": "PRODUCTION_TERMINATED", "authoritative_error": True},
        shadow_decision=ExplorationDecision.CONTINUE.value,
        frontier_status="NO")
    assert late_error == ("SHADOW_ERROR_PRECEDENCE_MISMATCH", "PRODUCTION_ERROR_HAS_PRIORITY")


def test_finalized_hard_stop_error_is_not_hidden_by_shadow_continue():
    runtime = ExplorationShadowRuntime("r", "s")
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
        state_plateaus=(StatePlateau(STATE, 0),), history_item_count=1)
    token = _prepare(runtime, step=1, frontier_status="NO", items=[_eligible()],
                     evidence_complete=True)
    assert runtime.finalize_decision(token=token, final_terminal=True,
        final_terminal_reason="audit_chain_incomplete", final_error=True)
    record = runtime.decisions[0]
    assert record["error_evidence"]["authoritative_error"] is True
    assert record["production"]["authoritative_error"] is True
    assert record["comparison_category"] == "SHADOW_ERROR_PRECEDENCE_MISMATCH"
    assert record["comparison_reason"] == "PRODUCTION_ERROR_HAS_PRIORITY"


def test_production_stop_with_frontier_no_metric_excludes_hard_bound_and_error():
    runtime = ExplorationShadowRuntime("r", "s")
    for step, terminal_reason, bounds, error in (
        (1, "repeat_no_progress", {}, False),
        (2, "safety_limit", {"kind": "MAX_STEPS", "limit_kind": "MAX_STEPS",
                             "usage": 2, "limit_value": 2, "reached": True,
                             "absolute": True, "hard": True, "authoritative": True}, False),
        (3, "audit_chain_incomplete", {}, True),
    ):
        token = _prepare(runtime, step=step, frontier_status="NO", items=[_eligible()],
                         evidence_complete=True, hard_bounds=bounds,
                         production={"authoritative_error": error, "error_stop": error})
        runtime.finalize_decision(token=token, final_terminal=True,
                                  final_terminal_reason=terminal_reason)
    assert runtime.metrics["PRODUCTION_TERMINATED_WITH_FRONTIER_NO_COUNT"] == 1


def test_revisit_metric_requires_production_authority_and_confirmed_accessibility_focus():
    runtime = ExplorationShadowRuntime("r", "s")
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
        state_plateaus=(StatePlateau(STATE, 0),), history_item_count=1)
    token = _prepare(runtime, step=1, frontier_status="NO", items=[_eligible()], evidence_complete=True,
        production={"actual_accessibility_focus_moved": True,
                    "accessibility_focus_authoritative": True,
                    "focus_transition_status": "CONFIRMED_MOVED",
                    "visit_record_status": "ALREADY_VISITED",
                    "visit_authority": "PRODUCTION", "visit_instance_id": "visit-1"})
    runtime.finalize_decision(token=token, final_terminal=False)
    assert runtime.metrics["REVISIT_WITH_FRONTIER_AVAILABLE_COUNT"] == 1

    token = _prepare(runtime, step=2, frontier_status="NO", items=[_eligible()], evidence_complete=True,
        production={"actual_accessibility_focus_moved": True,
                    "accessibility_focus_authoritative": True,
                    "focus_transition_status": "CONFIRMED_MOVED",
                    "visit_record_status": "ALREADY_VISITED",
                    "visit_authority": "UNKNOWN", "visit_instance_id": "visit-2"})
    runtime.finalize_decision(token=token, final_terminal=False)
    assert runtime.metrics["REVISIT_WITH_FRONTIER_AVAILABLE_COUNT"] == 1


def test_normalization_reports_but_does_not_change_production_result():
    row = {"status": "END", "final_result": "STOPPED", "stop_reason": "repeat_no_progress"}
    original = deepcopy(row)
    result = normalize_production_decision(row=row, stop_candidate=True,
        stop_reason="repeat_no_progress", final_terminal=False)
    assert row == original
    assert result["outcome"] == "PRODUCTION_STOP_CANDIDATE"
    assert result["final_terminal"] is False


def test_shadow_artifact_is_additive_bounded_and_marks_unfinalized_decisions_stale(tmp_path):
    runtime = ExplorationShadowRuntime("run-1", "scenario-1")
    token = _prepare(runtime, step=1)
    assert token
    path = runtime.write(tmp_path / "scenario.json")
    assert path.name == "scenario.exploration_shadow.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == EXPLORATION_SHADOW_SCHEMA_VERSION
    assert document["authority"] == "SHADOW_ONLY"
    assert document["production_control"] is False
    assert document["decisions"][0]["stale_status"] == "YES"
    assert document["decisions"][0]["shadow_decision"] == "UNKNOWN"
    assert document["decisions"][0]["decision_evidence_usable"] is False
    assert path.stat().st_size <= runtime.artifact()["limits"]["max_artifact_bytes"]


def test_artifact_byte_limit_truncates_and_revokes_decision_usability(tmp_path, monkeypatch):
    import tb_runner.exploration_shadow as module

    monkeypatch.setattr(module, "MAX_ARTIFACT_BYTES", 9_000)
    runtime = ExplorationShadowRuntime("run-1", "scenario-1")
    runtime.decisions = [
        {"decision_id": str(index), "decision_evidence_usable": True,
         "shadow_decision": "COMPLETE_CURRENT_SCOPE",
         "frontier": {"frontier_exhausted": "YES", "evidence_complete": True},
         "padding": "x" * 3_500}
        for index in range(3)
    ]
    path = runtime.write(tmp_path / "bounded.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert path.stat().st_size <= 9_000
    assert document["truncated"] is True
    assert document["evidence_complete"] is False
    assert "MAX_ARTIFACT_BYTES" in document["truncation_reasons"]
    assert all(item["frontier"]["frontier_exhausted"] == "UNKNOWN"
               and item["decision_evidence_usable"] is False
               for item in document["decisions"])


def test_authoritative_safety_denial_precedes_frontier_redirect():
    runtime = ExplorationShadowRuntime("r", "s", policy=ExplorationPolicy(
        state_plateau_threshold=1, run_plateau_threshold=1))
    runtime.history = ExplorationHistory(known_state_ids=(STATE,),
        state_plateaus=(StatePlateau(STATE, 1),), run_plateau_age=1, history_item_count=1)
    token = _prepare(runtime, step=1, frontier_status="NO", items=[_eligible()],
        evidence_complete=True,
        safety_state={"authoritative": True, "required_action_denied": True,
                      "safe_alternative_available": False})
    runtime.finalize_decision(token=token, final_terminal=False)
    assert runtime.decisions[0]["shadow_decision"] == ExplorationDecision.TERMINATE_SAFETY_LIMIT.value
    assert runtime.metrics["SHADOW_REDIRECT_RECOMMENDATION_COUNT"] == 0
    assert runtime.history.closed_decision_count == 1


def test_runtime_evaluator_exception_is_isolated_from_caller(monkeypatch):
    import tb_runner.exploration_shadow as module

    runtime = ExplorationShadowRuntime("r", "s")
    def fail(**kwargs):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(module, "evaluate_exploration_progress", fail)
    row = {"status": "CONTINUE"}
    before = deepcopy(row)
    args = _inputs(1)
    token = runtime.prepare_decision(
        decision_id=args["decision_id"], step=1, watermark=1,
        current_state=args["current_state"], frontier_evaluation=args["frontier_evaluation"],
        production_result=args["production_result"],
    )
    assert token is None
    assert row == before
    assert runtime.decisions == []
    assert runtime.failures == [{"phase": "prepare_decision", "step": 1,
                                 "error_type": "RuntimeError"}]


def test_collection_hook_uses_closed_step_evidence_without_mutating_production_row(monkeypatch):
    from tb_runner import collection_flow, state_graph
    from tb_runner.frontier_shadow import FrontierShadowRuntime

    from talkback_lib.exploration_evidence_clock import EvidenceClock
    clock = EvidenceClock()
    observation = clock.finish_observation(clock.begin_observation())
    exploration = ExplorationShadowRuntime("run", "scenario", evidence_clock=clock)
    frontier = FrontierShadowRuntime("run", "scenario")
    frontier.capture_inventory(step=1, state_id=STATE, candidates=[],
        inventory_complete=True, observation_ref={"request_id": "request-1"})
    client = SimpleNamespace(_phase6d_exploration_shadow_runtime=exploration,
                             _phase6c2_frontier_shadow_runtime=frontier)
    client._adb_device = SimpleNamespace(shadow_evidence_clock=clock)
    identity = SimpleNamespace(state_id=STATE, status="RESOLVED", reasons=())
    monkeypatch.setattr(state_graph, "_raw_observation_from_row", lambda row: {})
    monkeypatch.setattr(state_graph, "build_graph_state_identity", lambda raw: identity)
    row = {
        "_exploration_observation": observation,
        "step_index": 1,
        "scenario_id": "scenario",
        "smart_nav_req_id": "request-1",
        "focus_transition_status": "UNKNOWN",
        "actual_focus_accessibility_focused": False,
        "actual_focus_node": {"accessibilityFocused": False},
        "visit_record_status": "RECORDED",
        "reconciled_visit_instance_id": "unconfirmed-visit",
        "status": "CONTINUE",
    }
    before = deepcopy(row)
    token = collection_flow._prepare_phase6d_exploration_decision(
        client=client, row=row, step_idx=1,
        tab_cfg={"scenario_id": "scenario", "scenario_type": "content", "max_steps": 5},
        stop_candidate=False, stop_reason="", stop_eval_inputs={}, pre_decision_ref="frontier-ref",
    )
    assert token
    pending = exploration._pending[token]
    assert pending.production["decision_id"] == "scenario:closed:1"
    assert pending.production["decision_watermark"] == 1
    assert pending.production["decision_stage"] == "CLOSED_DECISION"
    assert pending.production["pre_decision_ref"] == "frontier-ref"
    assert pending.production["visit_authority"] == "UNKNOWN"
    assert pending.production["new_visit_authoritative"] is False
    assert row == before
    assert exploration.finalize_decision(token=token, final_terminal=False)
    assert exploration.history.known_visit_ids == ()

    candidate_row = {**row, "step_index": 2, "smart_nav_req_id": "request-2"}
    frontier.capture_inventory(step=2, state_id=STATE, candidates=[],
        inventory_complete=True, observation_ref={"request_id": "request-2"})
    terminal_token = collection_flow._prepare_phase6d_exploration_decision(
        client=client, row=candidate_row, step_idx=2,
        tab_cfg={"scenario_id": "scenario", "scenario_type": "content", "max_steps": 5},
        stop_candidate=True, stop_reason="repeat_no_progress",
        stop_eval_inputs={"repeat_stop_hit": True}, pre_decision_ref="frontier-ref-2",
    )
    staged = exploration._pending[terminal_token].production
    assert staged["outcome"] == "PRODUCTION_STOP_CANDIDATE"
    assert staged["final_terminal"] is False
    assert exploration.finalize_decision(token=terminal_token, final_terminal=True,
                                         final_terminal_reason="repeat_no_progress")
    assert exploration.decisions[-1]["production"]["outcome"] == "PRODUCTION_TERMINATED"
    assert candidate_row["status"] == "CONTINUE"
