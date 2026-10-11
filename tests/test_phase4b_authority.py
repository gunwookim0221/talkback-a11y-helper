from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from state_model_fixtures import node, observation
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.phase4a_planner import PlannerInput, ProductionHistory, plan_shadow, production_instance
from tb_runner.phase4b_authority import AuthorityEvidence, ExecutionBudget, correlated_result, execution_gate
from tb_runner.phase4b_execution import coherent_focus, controlled_collect, focus_row
from tb_runner.traversal_reliability import focus_instance, instance_id
from tb_runner.state_registry import StateRegistry


def value(*, context="PARTIAL_CONTEXT", enabled=True, focusable=True, only_current=False, scroll=False):
    current = node("id.b", "B", "0,220,500,320", accessibilityFocused=True)
    nodes = [current] if only_current else [node("id.a", "A", enabled=enabled, focusable=focusable), current]
    raw = observation(nodes=nodes, focus_node=current)
    if scroll:
        raw["capability"] = dict(axis_contract="axis-v1", contradictory=False, containers=[
            dict(className="ScrollView", path="0.1", boundsInScreen="0,0,1000,900", axis="VERTICAL", scroll_forward_supported=True)])
    snapshot = build_discovery_snapshot(raw, StateRegistry("authority-test"))
    raw["snapshot_hash"] = snapshot.candidate_set_hash
    return PlannerInput(snapshot, context, ProductionHistory("synthetic", known=True)), raw


def trusted(**kwargs):
    return AuthorityEvidence(enabled=True, fresh=True, recovery_clear=True, lifecycle_clear=True,
        transport_clear=True, focus_coherent=True, structural_scope_proven=True, geometry_in_viewport=True, **kwargs)


def gate(v, *, current=None, evidence=None, **kwargs):
    return execution_gate(v, plan_shadow(v), current or v, evidence or trusted(), **kwargs)


def test_a_safe_target_allowed_and_no_authority_by_default():
    v, _ = value(context="VERIFIED_ROOT_CONTEXT")
    assert gate(v).mode == "CONTROLLED_TARGET_FOCUS"
    assert gate(v).allowed
    assert not gate(v, evidence=AuthorityEvidence()).allowed
    assert gate(v, evidence=AuthorityEvidence()).mode == "SHADOW_ONLY"


def test_b_stale_candidate_denied():
    v, _ = value()
    target = plan_shadow(v).to_dict()["recommended_instance_id"]
    current = replace(v, history=replace(v.history, stale_ids=(target,)))
    assert not gate(v, current=current).allowed


def test_c_safe_partial_context_allowed():
    v, _ = value()
    assert gate(v).allowed


def test_d_partial_plugin_assumption_denied():
    v, _ = value()
    assert gate(v, evidence=trusted(plugin_context_required=True)).reason == "UNVERIFIED_PLUGIN_ASSUMPTION"


def test_e_current_without_value_no_action():
    v, _ = value(only_current=True)
    assert not gate(v).allowed
    assert gate(v).reason == "NO_SAFE_PLANNER_ACTION"


def execute(monkeypatch, *, ack=True, actual="a", stale=False, sink=None):
    v, raw = value()
    selected = node("id.a", "A", accessibilityFocused=True) if actual == "a" else raw["focus_node"]
    if actual == "false":
        selected = node("id.a", "A", accessibilityFocused=False, focused=True)
    client = SimpleNamespace(last_target_action_result={}, _evidence_active_request_id="current",
        last_smart_nav_result={}, last_smart_nav_terminal=False,
        _evidence_set_step=lambda *a, **kw: None,
        _normalize_action_result=lambda **kw: kw,
        get_focus=lambda **kw: selected)
    def target_focus_commit(**kw):
        client.last_target_action_result = dict(success=ack, status="SUCCESS" if ack else "FAILED",
                                               reqId="old" if stale else "current")
        return client.last_target_action_result
    client.target_focus_commit = target_focus_commit
    calls = []
    def collect(**kwargs):
        calls.append(kwargs)
        return {**focus_row(selected, "synthetic"), "focus_node": selected}
    audit, budget = {}, ExecutionBudget()
    row = controlled_collect(client=client, dev="synthetic-device", scenario="synthetic", step=1,
        raw=raw, recommendation=plan_shadow(v), decision=gate(v), budget=budget, collect=collect,
        collect_kwargs=dict(move=True, direction="next", step_index=1), refresh=lambda: {},
        output_dir="", audit=audit, audit_sink=sink)
    return row, audit, calls, budget, client


def test_f_success_unchanged_has_no_credit_and_one_fallback(monkeypatch):
    _, audit, calls, budget, _ = execute(monkeypatch, actual="b")
    assert audit["focus_preview"]["focus_transition_status"] == "CONFIRMED_UNCHANGED"
    assert not audit["focus_preview"]["reconciled_visit_instance_id"]
    assert audit["classification"] == "PLANNER_FAILED_FALLBACK_USED"
    assert [c["move"] for c in calls] == [False, True]
    assert budget.actions == budget.fallback_count == 1


def test_g_failed_ack_actual_move_uses_production_reconcile(monkeypatch):
    row, audit, calls, _, _ = execute(monkeypatch, ack=False)
    assert audit["focus_preview"]["focus_transition_status"] == "CONFIRMED_MOVED"
    assert len(calls) == 1 and calls[0]["move"] is False
    assert row["phase4b_before_row"]["actual_focus_node"]["viewIdResourceName"] == "id.b"
    assert "visit_credit" not in row  # The adapter does not award any visit.


def test_h_false_focus_fallback_no_visit(monkeypatch):
    _, audit, calls, _, _ = execute(monkeypatch, actual="false")
    assert not audit["focus_preview"]["reconciled_visit_instance_id"]
    assert audit["fallback_used"] and len(calls) == 2


def test_i_stale_request_no_attribution(monkeypatch):
    row, audit, calls, _, client = execute(monkeypatch, stale=True)
    assert not correlated_result(client, client.last_target_action_result)
    assert not audit["helper_result_correlated"]
    assert audit["fallback_reason"] == "STALE_REQUEST_RESULT"
    assert "target_focus_descriptor" not in row
    assert len(calls) == 2


def test_j_disappearing_target_denied():
    v, _ = value()
    current, _ = value(only_current=True)
    assert not gate(v, current=current).allowed
    assert gate(v, current=current).reason == "CANDIDATE_DISAPPEARED"


def test_k_no_eligible_focus_valid_scroll_allowed():
    v, _ = value(only_current=True, scroll=True)
    assert plan_shadow(v).to_dict()["recommended_action"] == "SCROLL_FORWARD"
    assert gate(v, evidence=trusted(scroll_container_proven=True)).mode == "CONTROLLED_SCROLL"
    assert gate(v, evidence=trusted(scroll_container_proven=True)).allowed


def test_l_exhausted_scroll_denied():
    v, _ = value(only_current=True, scroll=True)
    assert not gate(v, current=replace(v, scroll_exhausted=True), evidence=trusted(scroll_container_proven=True)).allowed


def test_m_failures_degrade_and_budget_bounded():
    v, _ = value()
    budget = ExecutionBudget()
    for step in range(2):
        budget.reserve("CONTROLLED_TARGET_FOCUS", "a", "same", "same")
        budget.outcome("CONFIRMED_UNCHANGED", False)
    assert budget.degraded and budget.failure_streak == 2
    assert budget.consecutive_selections == budget.repeated_result_count == 2
    assert not gate(v, degraded=budget.degraded).allowed
    with pytest.raises(RuntimeError):
        budget.reserve("CONTROLLED_TARGET_FOCUS", "a", "same", "same")
    assert not gate(v, actions_used=5).allowed


def test_n_fallback_preserves_original_kwargs_and_row_identity():
    v, raw = value()
    expected, received = {}, []
    kwargs = dict(move=True, direction="next", wait_seconds=1.5, step_index=3)
    audit, budget = {}, ExecutionBudget()
    row = controlled_collect(client=SimpleNamespace(), dev="dev", scenario="synthetic", step=3,
        raw=raw, recommendation=plan_shadow(v), decision=gate(v, evidence=AuthorityEvidence()),
        budget=budget, collect=lambda **kw: received.append(kw) or expected, collect_kwargs=kwargs,
        refresh=lambda: pytest.fail("No refresh/action on fallback"), output_dir="", audit=audit)
    assert row is expected and received == [kwargs] and budget.actions == 0


@pytest.mark.parametrize("field", ["fresh", "recovery_clear", "lifecycle_clear", "transport_clear", "focus_coherent", "geometry_in_viewport"])
def test_unknown_authority_flags_fail_closed(field):
    v, _ = value()
    assert not gate(v, evidence=replace(trusted(), **{field: None})).allowed


def test_unknown_enabled_blocked_and_forged_recommendation_denied():
    v, _ = value(enabled=None)
    assert not gate(v).allowed
    v, _ = value()
    from tb_runner.phase4a_planner import ShadowRecommendation
    import json
    doc = plan_shadow(v).to_dict()
    doc["recommended_action"] = "CLICK"
    assert not execution_gate(v, ShadowRecommendation(json.dumps(doc)), v, trusted()).allowed


def test_coherence_requires_exact_single_accessibility_focus():
    _, raw = value()
    assert coherent_focus(raw)
    bad = deepcopy(raw)
    bad["nodes"][0]["accessibilityFocused"] = True
    assert not coherent_focus(bad)
    bad = deepcopy(raw)
    bad["focus_node"] = node("other", "Other", accessibilityFocused=True)
    assert not coherent_focus(bad)


@pytest.mark.parametrize("label_field", ["talkbackLabel", "mergedLabel"])
def test_real_helper_ridless_before_focus_preserves_label_and_production_identity(label_field):
    # Captured Home steps 1 and 3 proved this shape occurs in production.
    helper = dict(viewIdResourceName=None, text=None, contentDescription=None,
                  accessibilityFocused=True, focused=False, className="android.view.View",
                  boundsInScreen=dict(l=78, t=129, r=373, b=273, left=78, top=129, right=373, bottom=273),
                  **{label_field: "연기-거실"})
    adapted = focus_row(helper, "home_main")
    identity = focus_instance(adapted)
    assert identity is not None
    assert adapted["actual_focus_visible"] == "연기-거실"
    assert adapted["actual_focus_bounds"] == "78,129,373,273"
    assert instance_id(identity) == production_instance(dict(resource_id="", bounds="78,129,373,273"), "home_main")
    assert helper["text"] is None  # The producer observation is not rewritten.


def test_coherence_rejects_focus_without_production_identity():
    _, raw = value()
    raw["focus_node"] = node("", "", accessibilityFocused=True)
    raw["focus_node"]["className"] = ""
    raw["nodes"] = [raw["focus_node"]]
    assert not coherent_focus(raw)


@pytest.mark.parametrize("ack,stale", [(True,False),(False,False),(True,True)])
def test_anonymous_controlled_focus_uses_existing_move_and_request_contracts(monkeypatch,ack,stale):
    original_node=node
    def anonymous_target(rid,label,*args,**kw):
        if rid=="id.a": rid,label="",""
        return original_node(rid,label,*args,**kw)
    monkeypatch.setattr(__import__(__name__),"node",anonymous_target)
    row,audit,calls,_,_=execute(monkeypatch,ack=ack,stale=stale)
    assert audit["focus_preview"]["focus_transition_status"]=="CONFIRMED_MOVED"
    assert audit["planner_executed"]
    assert audit["fallback_used"] is stale
    assert len(calls)==(2 if stale else 1)
    assert "visit_credit" not in row


def test_repeated_movement_without_new_production_visit_degrades():
    budget = ExecutionBudget()
    for _ in range(2):
        budget.reserve("CONTROLLED_TARGET_FOCUS", "same", "same", "same")
        budget.outcome("CONFIRMED_MOVED", True)
        budget.production_outcome(new_visit=False)
    assert budget.degraded
    assert budget.degraded_reason == "REPEATED_TARGET_WITHOUT_NEW_PRODUCTION_VISIT"


def test_action_events_are_durable_before_final_row_persistence(monkeypatch):
    events = []
    execute(monkeypatch, actual="b", sink=events.append)
    assert [e["event"] for e in events] == ["BEFORE_CONTROLLED_TARGET_FOCUS",
        "AFTER_CONTROLLED_TARGET_FOCUS", "CONTROLLED_FOCUS_PREVIEW",
        "BEFORE_PRODUCTION_FALLBACK", "AFTER_PRODUCTION_FALLBACK"]
    assert events[0]["planner_executed"] is False
    assert events[1]["helper_request_id"] == "current"
    assert events[1]["planner_executed"] is True
    assert events[-1]["fallback_used"] is True


def test_foreign_scenario_history_cannot_authorize_target():
    v, _ = value()
    assert not gate(v, current=replace(v, history=replace(v.history, scenario_id="foreign"))).allowed


@pytest.mark.parametrize("status,valid,changed,expected", [
    ("SCROLL_MOVED", True, True, "SCROLL_MOVED"),
    ("SCROLL_NO_CHANGE", True, False, "SCROLL_NO_MOVEMENT"),
    ("SCROLL_NO_CHANGE", False, False, "SCROLL_INDETERMINATE")])
def test_scroll_reuses_production_and_refreshes_before_next_decision(monkeypatch, status, valid, changed, expected):
    v, raw = value(only_current=True, scroll=True)
    cap = dict(axis_contract="axis-v1", contradictory=False, can_scroll_forward=True,
               container=dict(path="0.1", boundsInScreen="0,0,1000,900", axis="VERTICAL"))
    from tb_runner import scroll_reliability
    monkeypatch.setattr(scroll_reliability, "capture", lambda *a, **kw: dict(capability=cap))
    result = dict(status=status, before=dict(valid=valid), after=dict(valid=valid), action_success=True, viewport_changed=changed)
    calls = []
    monkeypatch.setattr(scroll_reliability, "verified_scroll", lambda *a, **kw: (calls.append("production_scroll") or result, {}))
    audit = {}
    controlled_collect(client=SimpleNamespace(), dev="dev", scenario="synthetic", step=1, raw=raw,
        recommendation=plan_shadow(v), decision=gate(v, evidence=trusted(scroll_container_proven=True)),
        budget=ExecutionBudget(), collect=lambda **kw: calls.append("collect") or {}, collect_kwargs=dict(move=True),
        refresh=lambda: calls.append("fresh_hierarchy_state_candidates_focus_plan") or dict(new=True), output_dir="", audit=audit)
    assert audit["scroll_result"] == expected
    assert calls == ["production_scroll", "fresh_hierarchy_state_candidates_focus_plan", "collect"]
    assert audit["post_scroll_refresh"] == dict(new=True)
