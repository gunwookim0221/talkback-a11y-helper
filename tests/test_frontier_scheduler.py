from copy import deepcopy

import pytest

from tb_runner.frontier_scheduler import (
    ExhaustionResult,
    FrontierPolicy,
    FrontierStatus,
    PriorityTier,
    build_frontier_id,
    evaluate_frontier,
)


STATE = {"state_id": "state-a", "resolved": True, "inventory_complete": True}
CURSOR = {"instance_id": "focused-current", "confirmed": True}


def history(**changes):
    value = {
        "complete": True,
        "attempt_events": [],
        "visit_events": [],
        "exploration_events": [],
        "validated_aliases": {},
        "visits_by_instance": {},
    }
    value.update(changes)
    return value


def candidate(candidate_id, target, *, edge="TARGETED_FOCUS", state_id="state-a",
              order=None, present=True, binding="RESOLVED"):
    value = {
        "candidate_id": candidate_id,
        "edge_type": edge,
        "state_id": state_id,
        "target_identity": {"instance_id": target},
        "currently_present": present,
        "target_binding_status": binding,
    }
    if order is not None:
        value["stable_order_key"] = [order]
    return value


def evidence(candidate_row, *, state_id=None, planner_status="ELIGIBLE", safety_status="SAFE",
             stable_order_key=None, **planner_extra):
    state_id = state_id or candidate_row["state_id"]
    edge = candidate_row["edge_type"]
    target = ("focused-current" if edge == "FOCUS_NEXT"
              else candidate_row["target_identity"].get("instance_id", "no-production-id"))
    planner = {
        "state_id": state_id,
        "edge_type": edge,
        "action_type": edge,
        "target_instance_id": target,
        "status": planner_status,
        **planner_extra,
    }
    if stable_order_key is not None:
        planner["stable_order_key"] = stable_order_key
    safety = {
        "state_id": state_id,
        "edge_type": edge,
        "action_type": edge,
        "target_instance_id": target,
        "status": safety_status,
    }
    return planner, safety


def evaluate(rows, *, state=STATE, history_doc=None, planner_overrides=None,
             safety_overrides=None, focus_cursor=CURSOR, policy=None):
    planners, safeties = {}, {}
    for row in rows:
        planner, safety = evidence(row)
        planners[row["candidate_id"]] = planner
        safeties[row["candidate_id"]] = safety
    planners.update(planner_overrides or {})
    safeties.update(safety_overrides or {})
    return evaluate_frontier(state, rows, history_doc or history(), planners, safeties,
                             focus_cursor=focus_cursor, policy=policy).to_dict()


def item_by_candidate(result, candidate_id):
    return next(item for item in result["frontier_items"]
                if candidate_id in item.get("candidate_ids", [item["candidate_id"]]))


def visit(state_id, target, status="RECORDED", *, ownership=None):
    value = {
        "state_id": state_id,
        "target_instance_id": target,
        "production_authority": True,
        "accessibility_focus_confirmed": True,
        "focus_transition_status": "CONFIRMED_MOVED",
        "visit_record_status": status,
    }
    if ownership:
        value["ownership_status"] = ownership
    return value


def attempt(row, *, step=1, ownership="EXACT_MATCH", effect=False, moved=False,
            state_changed=False, before=True, after=True, complete=True,
            ack="ACKED", condition="same"):
    return {
        "state_id": row["state_id"],
        "frontier_id": build_frontier_id(row["state_id"], row["edge_type"], row["target_identity"]["instance_id"]),
        "action_type": row["edge_type"],
        "target_instance_id": row["target_identity"]["instance_id"],
        "attempted": True,
        "ownership_status": ownership,
        "step": step,
        "before_observation_valid": before,
        "after_observation_valid": after,
        "outcome_observation_complete": complete,
        "effect_observed": effect,
        "actual_focus_moved": moved,
        "state_changed": state_changed,
        "ack_status": ack,
        "condition_fingerprint": condition,
        # Request IDs are deliberately present in input but never become identity/output.
        "request_id": f"request-{step}",
    }


def test_frontier_identity_is_deterministic_state_scoped_and_ignores_labels_requests_and_order():
    target = {"instance_id": "production-instance-1"}
    first = build_frontier_id("state-a", "TARGETED_FOCUS", target)
    assert first == build_frontier_id("state-a", "TARGETED_FOCUS", dict(target))
    assert first != build_frontier_id("state-b", "TARGETED_FOCUS", target)
    assert first != build_frontier_id("state-a", "TARGETED_FOCUS", "production-instance-2")

    row = candidate("cand-1", "production-instance-1")
    changed_label = {**row, "label": "new dynamic label", "request_id": "different", "list_index": 42}
    base, changed = evaluate([row]), evaluate([changed_label])
    assert item_by_candidate(base, "cand-1")["frontier_id"] == item_by_candidate(changed, "cand-1")["frontier_id"]


def test_same_resource_id_with_distinct_production_instance_bounds_remains_distinct():
    one = {"resource_id": "device:power", "bounds": "[0,0][10,10]", "instance_id": "inst-1"}
    two = {"resource_id": "device:power", "bounds": "[0,20][10,30]", "instance_id": "inst-2"}
    assert build_frontier_id("state-a", "TARGETED_FOCUS", one["instance_id"]) != \
        build_frontier_id("state-a", "TARGETED_FOCUS", two["instance_id"])


def test_p0_never_attempted_candidates_outrank_visited_revisit_in_stable_order():
    rows = [candidate("a", "target-a", order=9),
            candidate("c", "target-c", order=3),
            candidate("b", "target-b", order=2)]
    result = evaluate(rows, history_doc=history(visit_events=[visit("state-a", "target-a", "ALREADY_VISITED")]))
    assert result["shadow_next_candidate_id"] == "b"
    assert [row["candidate_id"] for row in result["frontier_items"][:2]] == ["b", "c"]
    assert item_by_candidate(result, "a")["status"] == FrontierStatus.EXPLORED.value


def test_sequentially_visited_target_without_targeted_attempt_is_not_p0():
    row = candidate("visited", "target-v")
    result = evaluate([row], history_doc=history(visit_events=[visit("state-a", "target-v")]))
    item = item_by_candidate(result, "visited")
    assert item["attempt_count"] == 0
    assert item["visit_status"] == "RECORDED"
    assert item["status"] == FrontierStatus.EXPLORED.value
    assert item["priority_class"] is None


def test_state_change_reeligibility_does_not_create_a_new_production_visit():
    row = candidate("new-state", "target-v", state_id="state-b")
    result = evaluate([row], state={**STATE, "state_id": "state-b"},
                      history_doc=history(visit_events=[visit("state-a", "target-v")]))
    item = item_by_candidate(result, "new-state")
    assert item["status"] == FrontierStatus.ELIGIBLE.value
    assert item["priority_class"] == PriorityTier.P0.value
    assert item["visit_status"] == "UNVISITED"
    assert item["state_visit_credit_count"] == 0
    assert item["global_visit_count"] == 1
    assert "STATE_CHANGED_REELIGIBLE" in item["reason_codes"]


def test_return_to_same_state_reuses_prior_frontier_and_history():
    row = candidate("same", "target-v")
    history_doc = history(visit_events=[visit("state-a", "target-v")])
    first = evaluate([row], history_doc=history_doc)
    # A second identical evaluation models leaving and re-entering the same
    # canonical state while reusing the append-only production history.
    second = evaluate([row], history_doc=history_doc)
    assert first["frontier_items"] == second["frontier_items"]
    assert item_by_candidate(second, "same")["status"] == FrontierStatus.EXPLORED.value


def test_attempt_and_visit_are_separate_and_ack_failure_does_not_erase_focus_movement():
    a = candidate("attempt-only", "a")
    b = candidate("revisit", "b")
    c = candidate("new-visit", "c")
    d = candidate("failed-ack-moved", "d")
    events = [attempt(a, effect=False, moved=False),
              attempt(b, effect=True, moved=True),
              attempt(c, effect=True, moved=True),
              attempt(d, effect=True, moved=True, ack="FAILED")]
    visits = [visit("state-a", "b", "ALREADY_VISITED"),
              visit("state-a", "c", "RECORDED"),
              visit("state-a", "d", "RECORDED")]
    result = evaluate([a, b, c, d], history_doc=history(attempt_events=events, visit_events=visits))
    assert item_by_candidate(result, "attempt-only")["attempt_count"] == 1
    assert item_by_candidate(result, "attempt-only")["state_visit_credit_count"] == 0
    assert item_by_candidate(result, "attempt-only")["verified_no_effect_count"] == 1
    assert item_by_candidate(result, "revisit")["visit_status"] == "ALREADY_VISITED"
    assert item_by_candidate(result, "revisit")["state_visit_credit_count"] == 0
    assert item_by_candidate(result, "new-visit")["visit_status"] == "RECORDED"
    assert item_by_candidate(result, "failed-ack-moved")["visit_status"] == "RECORDED"
    assert item_by_candidate(result, "failed-ack-moved")["verified_no_effect_count"] == 0
    assert item_by_candidate(result, "failed-ack-moved")["effect_history"][0]["ack_status"] == "FAILED"


def test_no_effect_requires_exact_ownership_complete_before_after_and_no_effect():
    row = candidate("no-effect", "target-ne")
    exact = attempt(row, effect=False, moved=False, before=True, after=True, complete=True)
    result = evaluate([row], history_doc=history(attempt_events=[exact]))
    item = item_by_candidate(result, "no-effect")
    assert item["verified_no_effect_count"] == 1
    assert item["status"] == FrontierStatus.BLOCKED.value
    assert result["frontier_exhausted"] == ExhaustionResult.UNKNOWN.value

    for event in (attempt(row, ownership="AMBIGUOUS"),
                  attempt(row, after=False),
                  attempt(row, complete=False),
                  attempt(row, effect=True),
                  attempt(row, moved=True)):
        result = evaluate([row], history_doc=history(attempt_events=[event]))
        item = item_by_candidate(result, "no-effect")
        assert item["verified_no_effect_count"] == 0
        if event["ownership_status"] != "EXACT_MATCH":
            assert item["status"] == FrontierStatus.UNKNOWN.value


def test_meaningful_change_allows_only_bounded_p1_and_never_beats_p0():
    a, b = candidate("retry", "retry-target", order=1), candidate("fresh", "fresh-target", order=2)
    baseline = evaluate([a])
    frontier_id = item_by_candidate(baseline, "retry")["frontier_id"]
    old_condition = item_by_candidate(baseline, "retry")["condition_fingerprint"]
    changed_condition = "verified-condition-change"
    retry_event = {
        "status": "VERIFIED_MEANINGFUL_CHANGE", "state_id": "state-a",
        "frontier_id": frontier_id, "previous_condition_fingerprint": old_condition,
        "current_condition_fingerprint": changed_condition,
        "changed_dimensions": ["verified_context"], "basis_id": "context-change-1",
    }
    a_changed = {**a, "condition_fingerprint": changed_condition}
    planner_a, safety_a = evidence(a_changed, retry_evidence=retry_event)
    result = evaluate([a_changed, b], history_doc=history(attempt_events=[attempt(a, condition=old_condition)]),
                      planner_overrides={"retry": planner_a}, safety_overrides={"retry": safety_a})
    assert item_by_candidate(result, "retry")["priority_class"] == PriorityTier.P1.value
    assert item_by_candidate(result, "retry")["retry_eligible"] is True
    assert result["shadow_next_candidate_id"] == "fresh"


def test_fresh_snapshot_alone_does_not_enable_retry():
    row = candidate("retry", "retry-target")
    event = attempt(row)
    event["condition_fingerprint"] = "same"
    result = evaluate([row], history_doc=history(attempt_events=[event]))
    item = item_by_candidate(result, "retry")
    assert item["retry_eligible"] is False
    assert item["priority_class"] is None
    assert item["status"] == FrontierStatus.BLOCKED.value


def test_policy_limit_is_distinct_from_proven_exhaustion():
    row = candidate("limited", "target-limit")
    events = [attempt(row, step=1, effect=True), attempt(row, step=2, effect=True)]
    result = evaluate([row], history_doc=history(attempt_events=events))
    item = item_by_candidate(result, "limited")
    assert item["status"] == FrontierStatus.EXHAUSTED.value
    assert item["exhaustion_basis"] == "POLICY_LIMIT"
    assert result["frontier_exhausted"] == ExhaustionResult.UNKNOWN.value
    assert result["counts"]["policy_limited_count"] == 1


def test_unknown_candidate_is_not_selected_but_proven_p0_keeps_exhaustion_no():
    unknown, eligible = candidate("unknown", "target-u"), candidate("eligible", "target-e")
    result = evaluate([unknown, eligible], safety_overrides={"unknown": {"status": "SAFE"}})
    assert item_by_candidate(result, "unknown")["status"] == FrontierStatus.UNKNOWN.value
    assert result["shadow_next_candidate_id"] == "eligible"
    assert result["frontier_exhausted"] == ExhaustionResult.NO.value


def test_unknown_only_frontier_is_not_proven_exhausted():
    row = candidate("unknown", "target-u")
    result = evaluate([row], safety_overrides={"unknown": {"status": "SAFE"}})
    assert result["counts"]["eligible_count"] == 0
    assert result["frontier_exhausted"] == ExhaustionResult.UNKNOWN.value


def test_unsafe_novelty_never_becomes_eligible_and_explored_scope_can_be_exhausted():
    unsafe, explored = candidate("unsafe", "target-u"), candidate("explored", "target-e")
    planner_u, safety_u = evidence(unsafe, safety_status="UNSAFE")
    result = evaluate([unsafe, explored],
        history_doc=history(visit_events=[visit("state-a", "target-e", "ALREADY_VISITED")]),
        planner_overrides={"unsafe": planner_u}, safety_overrides={"unsafe": safety_u})
    assert item_by_candidate(result, "unsafe")["status"] == FrontierStatus.UNSAFE.value
    assert item_by_candidate(result, "explored")["status"] == FrontierStatus.EXPLORED.value
    assert result["shadow_next_frontier"] is None
    assert result["frontier_exhausted"] == ExhaustionResult.YES.value


def test_action_safety_scope_is_not_reused_for_another_edge_type():
    row = candidate("click", "target-click", edge="SAFE_ACTIVATION")
    planner, _ = evidence(row)
    focus_safety = {"state_id": "state-a", "edge_type": "TARGETED_FOCUS",
                    "action_type": "TARGETED_FOCUS", "target_instance_id": "target-click", "status": "SAFE"}
    result = evaluate([row], planner_overrides={"click": planner}, safety_overrides={"click": focus_safety})
    assert item_by_candidate(result, "click")["status"] == FrontierStatus.UNKNOWN.value


def test_explored_target_requires_explicit_followup_or_allowed_recovery_for_p2_p3():
    p2 = candidate("followup", "target-followup", order=1)
    p3 = candidate("recovery", "focused-current", order=2)
    p2_id = build_frontier_id("state-a", "TARGETED_FOCUS", "target-followup")
    p3_id = build_frontier_id("state-a", "TARGETED_FOCUS", "focused-current")
    planner_p2, safety_p2 = evidence(p2, followup_evidence={
        "verified": True, "state_id": "state-a", "frontier_id": p2_id,
        "distinct_unexplored_opportunity_id": "followup-1",
    })
    planner_p3, safety_p3 = evidence(p3, recovery_evidence={
        "verified": True, "policy_allowed": True, "state_id": "state-a",
        "frontier_id": p3_id, "purpose": "reacquire-context",
    })
    result = evaluate([p3, p2],
        history_doc=history(visit_events=[visit("state-a", "target-followup", "ALREADY_VISITED")]),
        planner_overrides={"followup": planner_p2, "recovery": planner_p3},
        safety_overrides={"followup": safety_p2, "recovery": safety_p3})
    assert item_by_candidate(result, "followup")["priority_class"] == PriorityTier.P2.value
    assert item_by_candidate(result, "recovery")["priority_class"] == PriorityTier.P3.value
    assert result["shadow_next_candidate_id"] == "followup"


def test_labels_or_bounds_alone_cannot_be_promoted_to_production_target_identity():
    row = candidate("unidentified", "ignored")
    row["target_identity"] = {"resource_id": "app:id/title", "bounds": "[0,0][1,1]", "label": "Settings"}
    result = evaluate([row])
    item = item_by_candidate(result, "unidentified")
    assert item["provisional_identity"] is True
    assert item["status"] == FrontierStatus.UNKNOWN.value
    assert result["shadow_next_frontier"] is None


def test_invalid_alias_cycle_makes_history_incomplete():
    row = candidate("alias-cycle", "new-instance")
    result = evaluate([row], history_doc=history(validated_aliases={"old": "new", "new": "old"}))
    assert result["history_complete"] is False
    assert item_by_candidate(result, "alias-cycle")["status"] == FrontierStatus.UNKNOWN.value


def test_current_focus_reselection_is_blocked_and_focus_next_has_no_promised_destination():
    current = candidate("current", "focused-current")
    result = evaluate([current])
    assert item_by_candidate(result, "current")["status"] == FrontierStatus.BLOCKED.value
    assert item_by_candidate(result, "current")["blocked_reason"] == "CURRENT_FOCUS_NO_NEW_OPPORTUNITY"

    next_row = {**candidate("next", "unused", edge="FOCUS_NEXT"), "target_identity": {}}
    next_planner = {"state_id": "state-a", "edge_type": "FOCUS_NEXT", "action_type": "FOCUS_NEXT",
                    "target_instance_id": "focused-current", "status": "ELIGIBLE"}
    next_safety = {**next_planner, "status": "SAFE"}
    next_result = evaluate([next_row], planner_overrides={"next": next_planner},
                           safety_overrides={"next": next_safety})
    assert next_result["focus_next_destination_guaranteed"] is False
    assert next_result["shadow_next_candidate_id"] == "next"
    assert next_result["shadow_next_action_type"] == "FOCUS_NEXT"


def test_missing_focus_cursor_is_unknown_for_focus_opportunities():
    row = candidate("target", "target-id")
    result = evaluate([row], focus_cursor=None)
    assert item_by_candidate(result, "target")["status"] == FrontierStatus.UNKNOWN.value


def test_scroll_is_deferred_to_6e_and_does_not_change_current_focus_exhaustion():
    row = candidate("scroll", "scroll-id", edge="SCROLL_FORWARD")
    result = evaluate([row])
    assert item_by_candidate(result, "scroll")["status"] == FrontierStatus.BLOCKED.value
    assert item_by_candidate(result, "scroll")["blocked_reason"] == "DEFERRED_TO_PHASE6E"
    assert result["counts"]["deferred_scroll_count"] == 1
    assert result["frontier_exhausted"] == ExhaustionResult.YES.value


def test_validated_alias_is_required_for_history_transfer():
    row = candidate("aliased", "new-instance")
    old_frontier = build_frontier_id("state-a", "TARGETED_FOCUS", "old-instance")
    event = {**attempt(row, effect=True), "target_instance_id": "old-instance",
             "frontier_id": old_frontier}
    doc = history(attempt_events=[event], validated_aliases={"old-instance": "new-instance"})
    result = evaluate([row], history_doc=doc)
    assert item_by_candidate(result, "aliased")["attempt_count"] == 1
    assert item_by_candidate(result, "aliased")["status"] == FrontierStatus.BLOCKED.value

    doc["validated_aliases"] = {}
    rejected = evaluate([row], history_doc=doc)
    # Without the existing alias proof, the old instance's attempt is not
    # transferred to the current instance.
    assert item_by_candidate(rejected, "aliased")["attempt_count"] == 0
    assert item_by_candidate(rejected, "aliased")["status"] == FrontierStatus.ELIGIBLE.value


def test_conflicting_duplicate_frontier_rows_become_unknown_deterministically():
    one = candidate("z-candidate", "same-target", order=1)
    two = {**candidate("a-candidate", "same-target", order=2), "currently_present": False}
    first = evaluate([one, two])
    second = evaluate([two, one])
    assert first["frontier_items"] == second["frontier_items"]
    assert first["frontier_items"][0]["status"] == FrontierStatus.UNKNOWN.value
    assert first["frontier_items"][0]["candidate_id"] == "a-candidate"


def test_history_truncation_and_inventory_truncation_are_visible_unknowns():
    row = candidate("one", "target-one")
    long_history = history(attempt_events=[attempt(row)], visit_events=[visit("state-a", "target-one")])
    result = evaluate([row], history_doc=long_history,
                      policy=FrontierPolicy(max_history_events=1))
    assert result["truncated"] is True
    assert result["history_complete"] is False
    assert result["frontier_exhausted"] == ExhaustionResult.UNKNOWN.value

    truncated = evaluate([row, candidate("two", "target-two")],
                         policy=FrontierPolicy(max_frontier_items=1))
    assert truncated["truncated"] is True
    assert truncated["shadow_next_frontier"] is None
    assert truncated["frontier_exhausted"] == ExhaustionResult.UNKNOWN.value


def test_ambiguous_or_stale_attempt_ownership_never_counts_as_attempt_or_no_effect():
    row = candidate("ambiguous", "target-a")
    event = attempt(row, ownership="AMBIGUOUS", effect=False, moved=False)
    event["possible_frontier_ids"] = [build_frontier_id("state-a", "TARGETED_FOCUS", "target-a")]
    result = evaluate([row], history_doc=history(attempt_events=[event]))
    item = item_by_candidate(result, "ambiguous")
    assert item["attempt_count"] == 0
    assert item["verified_no_effect_count"] == 0
    assert item["status"] == FrontierStatus.UNKNOWN.value


def test_repeated_calls_are_deterministic_and_do_not_consume_or_mutate_inputs():
    rows = [candidate("a", "target-a", order=2), candidate("b", "target-b", order=1)]
    history_doc = history(attempt_events=[attempt(rows[0], effect=False, moved=False)])
    planners, safeties = {}, {}
    for row in rows:
        planner, safety = evidence(row)
        planners[row["candidate_id"]] = planner
        safeties[row["candidate_id"]] = safety
    values = [STATE, rows, history_doc, planners, safeties, CURSOR, FrontierPolicy()]
    before = deepcopy(values)
    first = evaluate_frontier(STATE, rows, history_doc, planners, safeties, CURSOR).to_json()
    second = evaluate_frontier(STATE, rows, history_doc, planners, safeties, CURSOR).to_json()
    assert first == second
    assert values == before
    decoded = evaluate_frontier(STATE, rows, history_doc, planners, safeties, CURSOR)
    assert isinstance(decoded.frontier_items[0].to_dict(), dict)
    assert "request_id" not in decoded.to_json()


def test_candidate_incomplete_presence_or_binding_fails_closed():
    absent_evidence = candidate("missing-presence", "target-p")
    absent_evidence.pop("currently_present")
    result = evaluate([absent_evidence])
    assert item_by_candidate(result, "missing-presence")["status"] == FrontierStatus.UNKNOWN.value

    unavailable = candidate("unbound", "target-u", binding="UNAVAILABLE")
    result = evaluate([unavailable])
    assert item_by_candidate(result, "unbound")["status"] == FrontierStatus.BLOCKED.value


def test_invalid_policy_bounds_are_rejected():
    with pytest.raises(ValueError):
        FrontierPolicy(max_attempts_per_opportunity=3)
