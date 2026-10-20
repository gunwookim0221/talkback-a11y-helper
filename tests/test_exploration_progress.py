from copy import deepcopy
from dataclasses import replace

import pytest

from tb_runner.exploration_progress import (
    CURRENT_SCOPE,
    ExplorationDecision as Decision,
    ExplorationHistory,
    ExplorationPolicy,
    ProgressKind,
    StatePlateau,
    evaluate_exploration_progress,
)


def _inputs(watermark, *, state_id="state-A", exhausted="UNKNOWN", items=(), counts=None,
            evidence_complete=None, state_stage="POST_ACTION", frontier_stage="POST_ACTION",
            frontier_watermark=None, decision_id=None, production=None, scroll=None,
            safety=None, bounds=None, repetition=None, truncated=False, scope=CURRENT_SCOPE):
    did = decision_id or f"decision-{watermark}"
    prod = {
        "decision_id": did,
        "decision_step": watermark,
        "decision_watermark": watermark,
        "decision_closed": True,
        "decision_stage": "CLOSED_DECISION",
    }
    prod.update(production or {})
    state = {
        "state_id": state_id,
        "state_resolution": "RESOLVED",
        "decision_id": did,
        "evidence_watermark": watermark,
        "evidence_stage": state_stage,
    }
    count_values = {
        "eligible_count": sum(item.get("status") == "ELIGIBLE" for item in items),
        "unknown_count": sum(item.get("status") == "UNKNOWN" for item in items),
        "never_attempted_count": 0,
        "retryable_count": 0,
        "revisit_only_count": 0,
        "policy_limited_count": 0,
        "deferred_scroll_count": 0,
        "blocked_count": sum(item.get("status") == "BLOCKED" for item in items),
    }
    count_values.update(counts or {})
    complete = exhausted == "YES" if evidence_complete is None else evidence_complete
    frontier = {
        "decision_id": did,
        "evidence_watermark": watermark if frontier_watermark is None else frontier_watermark,
        "evidence_stage": frontier_stage,
        "state_id": state_id,
        "exhaustion_scope": scope,
        "frontier_exhausted": exhausted,
        "evidence_complete": complete,
        "history_complete": True,
        "inventory_complete": True,
        "truncated": truncated,
        "frontier_items": [dict(item) for item in items],
        "counts": count_values,
        "exhaustion_reason_codes": [],
    }
    scroll_value = {
        "decision_id": did,
        "evidence_watermark": watermark,
        "evidence_stage": "POST_ACTION",
        "scope": scope,
        "status": "NOT_APPLICABLE",
        "applies_to_scope": False,
    }
    scroll_value.update(scroll or {})
    repetition_value = {"decision_id": did, "evidence_watermark": watermark}
    repetition_value.update(repetition or {})
    return {
        "current_state": state,
        "progress_history": None,
        "frontier_evaluation": frontier,
        "production_result": prod,
        "repetition_state": repetition_value,
        "scroll_evidence": scroll_value,
        "safety_state": dict(safety or {}),
        "hard_bounds": dict(bounds or {}),
        "policy": ExplorationPolicy(scope=scope),
    }


def _evaluate(args, history=None, **overrides):
    values = dict(args)
    values["progress_history"] = history if history is not None else _seeded_history()
    values.update(overrides)
    return evaluate_exploration_progress(**values)


def _seeded_history():
    """Known state-A baseline so most tests isolate the current decision."""
    return ExplorationHistory(
        last_decision_watermark=0,
        last_decision_id="decision-0",
        processed_decision_ids=("decision-0",),
        known_state_ids=("state-A",),
        state_plateaus=(StatePlateau("state-A", 0, None),),
        history_item_count=2,
    )


def _item(frontier_id="frontier-D", *, state_id="state-A", status="ELIGIBLE", priority="P0", **extra):
    result = {"frontier_id": frontier_id, "state_id": state_id,
              "status": status, "priority_class": priority, "provisional": False}
    result.update(extra)
    return result


def _committed_sequence(states, *, candidate_state="state-A", threshold=4, include_cursor=True):
    history = ExplorationHistory()
    result = None
    for index, state_id in enumerate(states, 1):
        items = [_item()] if state_id == candidate_state else []
        exhausted = "NO" if items else "UNKNOWN"
        counts = {"eligible_count": len(items), "unknown_count": 0 if items else 1}
        args = _inputs(index, state_id=state_id, exhausted=exhausted, items=items,
                       counts=counts, evidence_complete=False)
        production = dict(args["production_result"])
        if include_cursor and index > 1:
            production["actual_accessibility_focus_moved"] = True
        args["production_result"] = production
        result = _evaluate(args, history, policy=ExplorationPolicy(
            state_plateau_threshold=threshold, run_plateau_threshold=threshold))
        history = result.proposed_history
    return result, history


def test_cursor_only_focus_movement_does_not_reset_plateau_or_count_as_exploration():
    args = _inputs(1, state_id="state-A", exhausted="UNKNOWN")
    first = _evaluate(args)
    next_args = _inputs(2, state_id="state-A", exhausted="UNKNOWN",
                        production={"actual_accessibility_focus_moved": True})
    second = _evaluate(next_args, first.proposed_history)
    assert ProgressKind.CURSOR_PROGRESS in second.progress_types
    assert ProgressKind.EXPLORATION_PROGRESS not in second.progress_types
    assert second.state_plateau_age == 2
    assert second.run_plateau_age == 2
    assert dict(second.metrics_delta)["CURSOR_ONLY_PROGRESS_COUNT"] == 1


def test_production_new_visit_resets_state_and_run_plateau_without_extending_bound():
    history = ExplorationHistory(
        last_decision_watermark=2,
        last_decision_id="decision-2",
        processed_decision_ids=("decision-1", "decision-2"),
        known_state_ids=("state-A",),
        known_frontier_ids=("frontier-D",),
        state_plateaus=(),
        run_plateau_age=3,
        history_item_count=3,
    )
    args = _inputs(3, state_id="state-A", exhausted="UNKNOWN",
                   production={"visit_authority": "PRODUCTION", "visit_outcome": "NEW_VISIT",
                               "visit_instance_id": "visit-3"},
                   bounds={"authoritative": True, "absolute": True, "reached": False,
                           "usage": 9, "limit_value": 10, "limit_kind": "steps"})
    result = _evaluate(args, history)
    assert result.decision == Decision.CONTINUE
    assert ProgressKind.EXPLORATION_PROGRESS in result.progress_types
    assert result.state_plateau_age == 0
    assert result.run_plateau_age == 0
    assert result.state_last_meaningful_progress_step == 3
    assert result.run_last_meaningful_progress_step == 3
    assert dict(result.hard_bound_summary)["usage"] == 9


def test_duplicate_production_visit_identity_cannot_reset_plateau_twice():
    history = replace(_seeded_history(), known_visit_ids=("visit-A",), history_item_count=3,
                      run_plateau_age=2)
    args = _inputs(1, exhausted="UNKNOWN", production={
        "visit_authority": "PRODUCTION", "visit_outcome": "NEW_VISIT",
        "visit_instance_id": "visit-A",
    })
    result = _evaluate(args, history)
    assert ProgressKind.EXPLORATION_PROGRESS not in result.progress_types
    assert result.run_plateau_age == 3


def test_first_resolved_state_is_exploration_progress_and_reentry_is_not():
    first = _evaluate(_inputs(1, state_id="state-A", exhausted="UNKNOWN"), ExplorationHistory())
    assert "NEW_RESOLVED_STATE" in first.reason_codes
    revisit = _evaluate(_inputs(2, state_id="state-A", exhausted="UNKNOWN"), first.proposed_history)
    assert ProgressKind.EXPLORATION_PROGRESS not in revisit.progress_types
    assert revisit.run_plateau_age == 1


def test_new_stable_frontier_resets_run_plateau_but_unknown_does_not():
    unknown = _item(status="UNKNOWN")
    first = _evaluate(_inputs(1, exhausted="UNKNOWN", items=[unknown], counts={"unknown_count": 1}))
    assert ProgressKind.EXPLORATION_PROGRESS not in first.progress_types
    eligible = _item()
    second = _evaluate(_inputs(2, exhausted="NO", items=[eligible], counts={"eligible_count": 1}),
                       first.proposed_history)
    assert second.decision == Decision.CONTINUE
    assert "NEW_VALID_FRONTIER" in second.reason_codes
    assert second.run_plateau_age == 0


def test_ab_c_known_focus_cycle_with_p0_remaining_recommends_redirect():
    sequence = ["state-A", "state-B", "state-C", "state-A", "state-B", "state-C", "state-A"]
    result, history = _committed_sequence(sequence, threshold=4)
    assert history.run_plateau_age == 4
    assert result.plateau_established is True
    assert result.decision == Decision.REDIRECT_FRONTIER
    assert result.frontier_exhausted == "NO"
    assert result.eligible_count == 1
    assert result.scope == CURRENT_SCOPE
    assert dict(result.metrics_delta)["SHADOW_REDIRECT_RECOMMENDATION_COUNT"] == 1


def test_frontier_no_continues_before_plateau_and_never_completes():
    history = replace(_seeded_history(), known_frontier_ids=("frontier-D",), history_item_count=3)
    args = _inputs(1, exhausted="NO", items=[_item()], counts={"eligible_count": 1},
                   evidence_complete=False)
    result = _evaluate(args, history)
    assert result.decision == Decision.CONTINUE
    assert result.frontier_exhausted == "NO"
    assert "PLATEAU_THRESHOLD_NOT_REACHED" in result.reason_codes


def test_frontier_yes_completes_only_current_focus_scope_with_current_scroll_absence_proof():
    scroll = {"status": "SCROLL_ABSENT_PROVEN_FOR_SCOPE", "absence_proven": True,
              "scope": CURRENT_SCOPE}
    args = _inputs(1, exhausted="YES", scroll=scroll)
    result = _evaluate(args)
    assert result.decision == Decision.COMPLETE_CURRENT_SCOPE
    assert result.scope == CURRENT_SCOPE
    assert result.to_dict()["decision_authority"] == "NONE"
    assert result.to_dict()["scope"] != "RUN_SCOPE"


def test_frontier_yes_with_eligible_row_count_contradiction_cannot_complete():
    history = replace(_seeded_history(), known_frontier_ids=("frontier-D",), history_item_count=3)
    args = _inputs(1, exhausted="YES", items=[_item()],
                   counts={"eligible_count": 0, "unknown_count": 0}, evidence_complete=True,
                   scroll={"status": "SCROLL_ABSENT_PROVEN_FOR_SCOPE", "absence_proven": True,
                           "scope": CURRENT_SCOPE})
    result = _evaluate(args, history)
    assert result.eligible_count == 1
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN


def test_unresolved_current_state_cannot_use_frontier_yes_or_no_as_current_scope_evidence():
    args = _inputs(1, exhausted="YES")
    args["current_state"]["state_resolution"] = "UNRESOLVED"
    result = _evaluate(args)
    assert result.frontier_exhausted == "UNKNOWN"
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE


@pytest.mark.parametrize("status", ["UNKNOWN", "SCROLL_NOT_CAPABLE", "SCROLL_UNVERIFIED"])
def test_frontier_yes_with_unresolved_scroll_hands_off_without_completing(status):
    args = _inputs(1, exhausted="YES", scroll={"status": status, "scope": CURRENT_SCOPE})
    result = _evaluate(args)
    assert result.decision == Decision.CHECK_SCROLL
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE


def test_frontier_unknown_is_bounded_and_never_completes():
    args = _inputs(1, exhausted="UNKNOWN", counts={"unknown_count": 1})
    first = _evaluate(args, recovery_budget={"remaining": 1, "could_resolve": True})
    assert first.decision == Decision.RECOVER_EVIDENCE
    second_args = _inputs(2, exhausted="UNKNOWN", counts={"unknown_count": 1})
    second = _evaluate(second_args, first.proposed_history,
                       recovery_budget={"remaining": 1, "could_resolve": True})
    assert second.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN
    assert second.proposed_history.recovery_recommended_evidence_ids == first.proposed_history.recovery_recommended_evidence_ids


def test_recovery_recommendation_does_not_mutate_budget_or_consume_visits():
    budget = {"remaining": 2, "could_resolve": True}
    original = deepcopy(budget)
    result = _evaluate(_inputs(1, exhausted="UNKNOWN", counts={"unknown_count": 1}),
                       recovery_budget=budget)
    assert result.decision == Decision.RECOVER_EVIDENCE
    assert budget == original
    assert result.proposed_history.recovery_recommended_evidence_ids


def test_unknown_to_nonactionable_is_knowledge_progress_once_not_run_reset():
    history = ExplorationHistory(
        last_decision_watermark=1, last_decision_id="decision-1",
        processed_decision_ids=("decision-1",), known_state_ids=("state-A",),
        frontier_statuses=(("frontier-X", "UNKNOWN"),), run_plateau_age=2,
        history_item_count=1,
    )
    blocked = _item("frontier-X", status="UNSAFE", priority="P1")
    args = _inputs(2, exhausted="UNKNOWN", items=[blocked],
                   counts={"unknown_count": 1, "unsafe_count": 1})
    result = _evaluate(args, history)
    assert ProgressKind.KNOWLEDGE_PROGRESS in result.progress_types
    assert ProgressKind.EXPLORATION_PROGRESS not in result.progress_types
    assert result.run_plateau_age == 3
    next_args = _inputs(3, exhausted="UNKNOWN", items=[_item("frontier-X", status="UNKNOWN")],
                        counts={"unknown_count": 1})
    churn = _evaluate(next_args, result.proposed_history)
    again = _evaluate(_inputs(4, exhausted="UNKNOWN", items=[blocked],
                              counts={"unknown_count": 1}), churn.proposed_history)
    assert ProgressKind.KNOWLEDGE_PROGRESS not in churn.progress_types
    assert ProgressKind.KNOWLEDGE_PROGRESS not in again.progress_types
    assert again.run_plateau_age == 5


def test_verified_new_viewport_and_edge_count_once_but_repeat_does_not():
    args = _inputs(1, exhausted="UNKNOWN", scroll={
        "status": "SCROLL_MOVED", "new_viewport_id": "viewport-2",
        "scroll_opportunity_id": "opportunity-scroll-1", "scroll_edge_id": "edge-occurrence-1",
    }, production={"edge_verified": True, "edge_opportunity_id": "opportunity-1",
                   "edge_id": "edge-occurrence-1"})
    first = _evaluate(args)
    assert first.decision == Decision.CONTINUE
    assert first.run_plateau_age == 0
    assert first.reason_codes.count("NEW_VERIFIED_EDGE") == 1
    repeated = _evaluate(_inputs(2, exhausted="UNKNOWN", scroll={
        "status": "SCROLL_MOVED", "new_viewport_id": "viewport-2",
        "scroll_opportunity_id": "opportunity-scroll-1", "scroll_edge_id": "edge-occurrence-2",
    }, production={"edge_verified": True, "edge_opportunity_id": "opportunity-1",
                   "edge_id": "edge-occurrence-2"}), first.proposed_history)
    assert ProgressKind.EXPLORATION_PROGRESS not in repeated.progress_types
    assert repeated.run_plateau_age == 1


def test_local_progress_is_distinct_and_only_stable_novelty_resets_state_age():
    first = _evaluate(_inputs(1, exhausted="UNKNOWN"))
    local = _evaluate(_inputs(2, exhausted="UNKNOWN", production={
        "local_progress_verified": True, "local_progress_id": "substate-1",
    }), first.proposed_history)
    assert ProgressKind.LOCAL_PROGRESS in local.progress_types
    assert ProgressKind.EXPLORATION_PROGRESS not in local.progress_types
    assert local.state_plateau_age == 0
    assert local.run_plateau_age == 2
    repeat = _evaluate(_inputs(3, exhausted="UNKNOWN", production={
        "local_progress_verified": True, "local_progress_id": "substate-1",
    }), local.proposed_history)
    assert ProgressKind.LOCAL_PROGRESS not in repeat.progress_types
    assert repeat.state_plateau_age == 1


def test_known_state_loop_does_not_reset_run_plateau():
    sequence = ["modal-open", "modal-closed", "modal-open", "modal-closed"]
    history = ExplorationHistory()
    results = []
    for index, state_id in enumerate(sequence, 1):
        result = _evaluate(_inputs(index, state_id=state_id, exhausted="UNKNOWN"), history,
                           policy=ExplorationPolicy(state_plateau_threshold=2, run_plateau_threshold=2))
        results.append(result)
        history = result.proposed_history
    assert results[0].run_plateau_age == 0
    assert results[1].run_plateau_age == 0
    assert results[2].run_plateau_age == 1
    assert results[3].run_plateau_age == 2
    assert ProgressKind.EXPLORATION_PROGRESS not in results[2].progress_types


def test_recovery_to_same_known_state_does_not_reset_run_plateau():
    history = ExplorationHistory(
        last_decision_watermark=2, last_decision_id="decision-2",
        processed_decision_ids=("decision-1", "decision-2"),
        known_state_ids=("state-A",), run_plateau_age=2, history_item_count=2,
    )
    result = _evaluate(_inputs(3, exhausted="UNKNOWN", production={"recovery_succeeded": True}), history,
                       policy=ExplorationPolicy(run_plateau_threshold=3))
    assert ProgressKind.EXPLORATION_PROGRESS not in result.progress_types
    assert result.run_plateau_age == 3


def test_recovery_loop_eventually_plateaus_and_never_resets_for_same_state():
    history = _seeded_history()
    ages = []
    for index in range(1, 6):
        result = _evaluate(_inputs(index, exhausted="UNKNOWN", production={
            "recovery_succeeded": True,
        }), history, policy=ExplorationPolicy(run_plateau_threshold=3))
        ages.append(result.run_plateau_age)
        history = result.proposed_history
    assert ages == [1, 2, 3, 4, 5]
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN
    assert result.plateau_established is True


def test_policy_limit_never_becomes_complete():
    args = _inputs(1, exhausted="UNKNOWN", evidence_complete=False,
                   counts={"policy_limited_count": 1, "eligible_count": 0, "unknown_count": 0})
    result = _evaluate(args)
    assert result.decision == Decision.TERMINATE_INCOMPLETE_POLICY_LIMIT
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE


def test_material_truncation_prevents_completion_and_can_recommend_recovery():
    args = _inputs(1, exhausted="YES", truncated=True)
    result = _evaluate(args, recovery_budget={"remaining": 1, "could_resolve": True})
    assert result.decision == Decision.RECOVER_EVIDENCE
    exhausted = _evaluate(_inputs(1, exhausted="YES", truncated=True))
    assert exhausted.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN


def test_internal_history_truncation_prevents_completion():
    history = replace(ExplorationHistory(), truncated=True)
    result = _evaluate(_inputs(1, exhausted="YES"), history)
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN
    assert result.proposed_history.truncated is True


def test_terminal_blocked_only_frontier_can_complete_declared_focus_scope():
    item = _item("terminal-block", status="BLOCKED", priority="P3",
                 blocked_reason="CURRENT_FOCUS_NO_NEW_OPPORTUNITY")
    args = _inputs(1, exhausted="YES", items=[item],
                   counts={"blocked_count": 1, "eligible_count": 0, "unknown_count": 0},
                   scroll={"status": "SCROLL_ABSENT_PROVEN_FOR_SCOPE", "absence_proven": True,
                           "scope": CURRENT_SCOPE})
    result = _evaluate(args)
    assert result.decision == Decision.COMPLETE_CURRENT_SCOPE


def test_temporary_blocked_only_frontier_stays_unknown():
    item = _item("temporary-block", status="BLOCKED", priority="P3", blocked_reason="TRANSIENT")
    args = _inputs(1, exhausted="YES", items=[item], evidence_complete=True,
                   counts={"blocked_count": 1, "eligible_count": 0, "unknown_count": 0})
    result = _evaluate(args)
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN


def test_hard_absolute_bound_outranks_frontier_and_preserves_counts():
    args = _inputs(1, exhausted="NO", items=[_item()], counts={"eligible_count": 1},
                   bounds={"authoritative": True, "absolute": True, "reached": True,
                           "limit_kind": "steps", "usage": 100, "limit_value": 100})
    result = _evaluate(args)
    assert result.decision == Decision.TERMINATE_HARD_BOUND
    assert result.eligible_count == 1
    assert dict(result.hard_bound_summary)["usage"] == 100


def test_safety_denial_outranks_hard_bound_but_unknown_safety_is_not_denial():
    denied = _inputs(1, exhausted="NO", items=[_item()],
                     safety={"authoritative": True, "required_action_denied": True,
                             "safe_alternative_available": False},
                     bounds={"authoritative": True, "absolute": True, "reached": True})
    assert _evaluate(denied).decision == Decision.TERMINATE_SAFETY_LIMIT
    unknown = _inputs(1, exhausted="UNKNOWN", safety={"authoritative": True,
                         "status": "UNKNOWN", "required_action": True})
    assert _evaluate(unknown).decision != Decision.TERMINATE_SAFETY_LIMIT


def test_authoritative_error_has_highest_priority():
    args = _inputs(1, exhausted="NO", items=[_item()],
                   production={"authoritative_error": True, "error_code": "HELPER_TRANSPORT"},
                   safety={"authoritative": True, "required_action_denied": True,
                           "safe_alternative_available": False},
                   bounds={"authoritative": True, "absolute": True, "reached": True})
    result = _evaluate(args)
    assert result.decision == Decision.TERMINATE_ERROR
    assert "HELPER_TRANSPORT" in result.reason_codes


def test_input_focus_only_is_not_cursor_progress():
    args = _inputs(1, exhausted="UNKNOWN", production={"input_focus_moved": True})
    result = _evaluate(args)
    assert ProgressKind.CURSOR_PROGRESS not in result.progress_types
    assert result.run_plateau_age == 1


def test_stale_and_duplicate_decisions_do_not_consume_history_or_credit_progress():
    first = _evaluate(_inputs(1, exhausted="UNKNOWN"))
    duplicate = _evaluate(_inputs(1, exhausted="UNKNOWN", production={
        "new_visit_authoritative": True,
    }), first.proposed_history)
    assert duplicate.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN
    assert duplicate.proposed_history == first.proposed_history
    assert "DUPLICATE_DECISION_IGNORED" in duplicate.reason_codes
    stale = _evaluate(_inputs(0, exhausted="UNKNOWN", production={
        "new_visit_authoritative": True,
    }), first.proposed_history)
    assert stale.proposed_history == first.proposed_history
    assert ProgressKind.EXPLORATION_PROGRESS not in stale.progress_types


def test_frontier_watermark_and_stage_prevent_pre_action_completion_or_novelty():
    args = _inputs(1, exhausted="YES", frontier_stage="PRE_ACTION")
    result = _evaluate(args, ExplorationHistory())
    assert result.frontier_exhausted == "UNKNOWN"
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE
    assert ProgressKind.EXPLORATION_PROGRESS in result.progress_types  # current resolved state only
    stale = _inputs(2, exhausted="NO", items=[_item()], frontier_watermark=1,
                    counts={"eligible_count": 1}, state_id="state-A")
    first = _evaluate(_inputs(1, exhausted="UNKNOWN"))
    second = _evaluate(stale, first.proposed_history)
    assert second.frontier_exhausted == "UNKNOWN"
    assert "NEW_VALID_FRONTIER" not in second.reason_codes


def test_decision_watermark_must_be_closed_monotonic_and_post_action():
    args = _inputs(1, exhausted="YES")
    args["production_result"]["decision_stage"] = "PRE_ACTION"
    result = _evaluate(args, ExplorationHistory())
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN
    assert result.proposed_history == ExplorationHistory()
    args = _inputs(1, exhausted="YES")
    args["production_result"]["decision_closed"] = False
    assert _evaluate(args, ExplorationHistory()).proposed_history == ExplorationHistory()


def test_different_watermark_or_decision_id_cannot_be_combined():
    args = _inputs(1, exhausted="YES")
    args["frontier_evaluation"]["decision_id"] = "older-action"
    result = _evaluate(args)
    assert result.frontier_exhausted == "UNKNOWN"
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE


def test_scope_completion_does_not_inflate_to_content_or_run_scope():
    args = _inputs(1, exhausted="YES", scope="RUN_SCOPE",
                   scroll={"status": "SCROLL_ABSENT_PROVEN_FOR_SCOPE", "absence_proven": True,
                           "scope": "RUN_SCOPE"})
    result = _evaluate(args)
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN
    args["frontier_evaluation"]["scope_completion_proof"] = {
        "scope": "RUN_SCOPE", "complete": True, "decision_id": "decision-1",
        "evidence_watermark": 1, "evidence_stage": "POST_ACTION",
    }
    assert _evaluate(args).decision == Decision.COMPLETE_CURRENT_SCOPE


def test_run_scope_completion_cannot_reuse_one_state_scroll_absence_proof():
    args = _inputs(1, exhausted="YES", scope="RUN_SCOPE",
                   scroll={"status": "SCROLL_ABSENT_PROVEN_FOR_SCOPE", "absence_proven": True,
                           "scope_state_id": "state-A"})
    args["scroll_evidence"].pop("scope")
    args["frontier_evaluation"]["scope_completion_proof"] = {
        "scope": "RUN_SCOPE", "complete": True, "decision_id": "decision-1",
        "evidence_watermark": 1, "evidence_stage": "POST_ACTION",
    }
    result = _evaluate(args)
    assert result.decision == Decision.CHECK_SCROLL
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE


def test_state_graph_history_truncation_prevents_scope_completion():
    args = _inputs(1, exhausted="YES", scroll={
        "status": "SCROLL_ABSENT_PROVEN_FOR_SCOPE", "absence_proven": True,
        "scope": CURRENT_SCOPE,
    })
    args["current_state"]["identity_history_truncated"] = True
    result = _evaluate(args)
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN


def test_repeat_no_progress_is_preserved_as_input_not_completion_proof():
    history = ExplorationHistory(
        last_decision_watermark=4, last_decision_id="decision-4",
        processed_decision_ids=("decision-1", "decision-2", "decision-3", "decision-4"),
        known_state_ids=("state-A",), state_plateaus=(), run_plateau_age=4,
        history_item_count=4,
    )
    args = _inputs(5, exhausted="UNKNOWN", repetition={
        "legacy_stop_reason": "repeat_no_progress", "same_count": 8,
        "hard_no_progress": True,
    })
    result = _evaluate(args, history)
    assert result.legacy_repeat_reason == "repeat_no_progress"
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE
    assert "LEGACY_REPEAT_SIGNAL_INPUT_ONLY" in result.reason_codes


def test_configurable_plateau_threshold_is_a_policy_input():
    history = ExplorationHistory(
        last_decision_watermark=2, last_decision_id="decision-2",
        processed_decision_ids=("decision-1", "decision-2"),
        known_state_ids=("state-A",), run_plateau_age=1, history_item_count=2,
    )
    history = replace(history, known_frontier_ids=("frontier-D",), history_item_count=3)
    args = _inputs(3, exhausted="NO", items=[_item()], counts={"eligible_count": 1})
    not_plateau = _evaluate(args, history, policy=ExplorationPolicy(run_plateau_threshold=4))
    plateau = _evaluate(args, history, policy=ExplorationPolicy(run_plateau_threshold=2))
    assert not_plateau.decision == Decision.CONTINUE
    assert plateau.decision == Decision.REDIRECT_FRONTIER


def test_repeated_evaluation_is_deterministic_and_does_not_mutate_inputs():
    args = _inputs(1, exhausted="NO", items=[_item()], counts={"eligible_count": 1})
    args["production_result"]["actual_accessibility_focus_moved"] = True
    original = deepcopy(args)
    first = _evaluate(args)
    second = _evaluate(args)
    assert first == second
    assert first.to_dict() == second.to_dict()
    assert args == original
    assert first.proposed_history.last_decision_watermark == 1


def test_input_history_is_immutable_and_proposed_history_is_detached():
    history = ExplorationHistory()
    before = deepcopy(history)
    result = _evaluate(_inputs(1, exhausted="UNKNOWN"), history)
    assert history == before
    assert result.proposed_history is not history
    rendered = result.to_dict()
    rendered["proposed_history"]["known_state_ids"].append("caller-mutation")
    assert "caller-mutation" not in result.proposed_history.known_state_ids


def test_legacy_stop_reason_is_not_changed_in_output():
    args = _inputs(1, exhausted="UNKNOWN", repetition={"legacy_stop_reason": "bounded_two_card_loop"})
    result = _evaluate(args)
    assert result.legacy_repeat_reason == "bounded_two_card_loop"
    assert result.to_dict()["legacy_repeat_reason"] == "bounded_two_card_loop"


def test_new_frontier_with_incomplete_other_candidates_can_still_redirect_after_plateau():
    history = ExplorationHistory(
        last_decision_watermark=4, last_decision_id="decision-4",
        processed_decision_ids=("decision-1", "decision-2", "decision-3", "decision-4"),
        known_state_ids=("state-A",), known_frontier_ids=("old-frontier", "frontier-D"),
        run_plateau_age=3, history_item_count=7,
    )
    args = _inputs(5, exhausted="NO", items=[_item("frontier-D")],
                   counts={"eligible_count": 1, "unknown_count": 2}, evidence_complete=False)
    result = _evaluate(args, history, policy=ExplorationPolicy(run_plateau_threshold=4))
    assert result.decision == Decision.REDIRECT_FRONTIER
    assert result.unknown_count == 2


def test_new_resolved_state_c_appearing_in_known_run_is_exploration_progress():
    history = replace(_seeded_history(), run_plateau_age=3)
    result = _evaluate(_inputs(1, state_id="state-C", exhausted="UNKNOWN"), history)
    assert result.decision == Decision.CONTINUE
    assert "NEW_RESOLVED_STATE" in result.reason_codes
    assert result.state_plateau_age == 0
    assert result.run_plateau_age == 0


def test_known_state_plateau_age_persists_when_leaving_and_returning():
    history = ExplorationHistory()
    results = []
    for index, state_id in enumerate(("state-A", "state-B", "state-A"), 1):
        result = _evaluate(_inputs(index, state_id=state_id, exhausted="UNKNOWN"), history)
        results.append(result)
        history = result.proposed_history
    assert results[0].state_plateau_age == 0
    assert results[1].state_plateau_age == 0
    assert results[2].state_plateau_age == 1
    assert results[2].run_plateau_age == 1


def test_new_p0_does_not_itself_immediately_redirect_on_same_decision():
    args = _inputs(1, exhausted="NO", items=[_item()], counts={"eligible_count": 1}, evidence_complete=False)
    result = _evaluate(args)
    assert "NEW_VALID_FRONTIER" in result.reason_codes
    assert result.decision == Decision.CONTINUE


def test_snapshot_request_and_label_churn_for_known_state_and_frontier_is_not_progress():
    history = replace(_seeded_history(), known_frontier_ids=("frontier-D",), history_item_count=3)
    args = _inputs(1, exhausted="NO", items=[_item(
        label="renamed", observation_id="new-observation", request_id="new-request")],
        counts={"eligible_count": 1}, evidence_complete=False)
    result = _evaluate(args, history)
    assert ProgressKind.EXPLORATION_PROGRESS not in result.progress_types
    assert result.run_plateau_age == 1


def test_conflicting_duplicate_frontier_rows_are_unknown_and_order_independent():
    rows = [_item("same-id", status="ELIGIBLE", priority="P0"),
            _item("same-id", status="UNSAFE", priority="P0")]
    first_args = _inputs(1, exhausted="YES", items=rows,
                         counts={"eligible_count": 1, "unknown_count": 0},
                         scroll={"status": "SCROLL_ABSENT_PROVEN_FOR_SCOPE", "absence_proven": True,
                                 "scope": CURRENT_SCOPE})
    reversed_args = _inputs(1, exhausted="YES", items=list(reversed(rows)),
                            counts={"eligible_count": 1, "unknown_count": 0},
                            scroll={"status": "SCROLL_ABSENT_PROVEN_FOR_SCOPE", "absence_proven": True,
                                    "scope": CURRENT_SCOPE})
    first = _evaluate(first_args)
    second = _evaluate(reversed_args)
    assert first.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN
    assert first.unknown_count == 1
    assert first.to_dict() == second.to_dict()


def test_frontier_no_without_concrete_candidate_never_completes():
    history = ExplorationHistory(last_decision_watermark=3, last_decision_id="decision-3",
        processed_decision_ids=("decision-1", "decision-2", "decision-3"),
        known_state_ids=("state-A",), run_plateau_age=3, history_item_count=4)
    args = _inputs(4, exhausted="NO", counts={"eligible_count": 1}, evidence_complete=False)
    result = _evaluate(args, history, policy=ExplorationPolicy(run_plateau_threshold=3))
    assert result.decision == Decision.TERMINATE_INCOMPLETE_NO_PROGRESS
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE


def test_input_watermark_is_visible_in_audit_and_scope_is_explicit():
    result = _evaluate(_inputs(7, exhausted="YES"))
    audit = result.to_dict()
    assert audit["input_watermark"] == 7
    assert audit["decision_id"] == "decision-7"
    assert audit["decision_step"] == 7
    assert audit["scope"] == CURRENT_SCOPE
    assert audit["proposed_history"]["last_decision_watermark"] == 7


def test_history_memory_cap_fails_closed_without_novelty_credit():
    args = _inputs(1, exhausted="UNKNOWN")
    result = _evaluate(args, policy=ExplorationPolicy(max_history_items=1))
    # The decision identity fills the bounded history; the new state cannot be
    # recorded as novelty and the proposal becomes explicitly truncated.
    assert result.proposed_history.truncated is True
    assert ProgressKind.EXPLORATION_PROGRESS not in result.progress_types
    assert result.decision == Decision.TERMINATE_INCOMPLETE_UNKNOWN


def test_scroll_not_capable_is_not_treated_as_proven_scroll_absence():
    args = _inputs(1, exhausted="YES", scroll={
        "status": "SCROLL_NOT_CAPABLE", "scope": CURRENT_SCOPE,
    })
    result = _evaluate(args)
    assert result.decision == Decision.CHECK_SCROLL
    assert result.decision != Decision.COMPLETE_CURRENT_SCOPE


def test_safety_denial_with_safe_alternative_is_not_safety_limit():
    args = _inputs(1, exhausted="UNKNOWN", safety={
        "authoritative": True, "required_action_denied": True,
        "safe_alternative_available": True,
    })
    assert _evaluate(args).decision != Decision.TERMINATE_SAFETY_LIMIT
