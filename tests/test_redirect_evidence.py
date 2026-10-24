from copy import deepcopy
from types import SimpleNamespace

import pytest

from tb_runner.redirect_evidence import SOURCES, evaluate_redirect_evidence, record_existing_proof
from talkback_lib.exploration_evidence_clock import EvidenceClock


def ready():
    # Reuse the actual proof producer, production frontier candidate, and
    # current observation bridge used by the Phase 6D3A integration fixture.
    # These contract tests must not reintroduce the old instance_id-only shape.
    from test_exploration_redirect import _real_frontier_discovery_fixture
    from tb_runner.redirect_evidence import current_execution_context

    _value, _raw, _recommendation, _production, record, clock, _current = (
        _real_frontier_discovery_fixture())
    selected = deepcopy(record["selected_frontier"])
    sources = deepcopy(record["actual_proof_sources"])
    client = SimpleNamespace(
        _adb_device=SimpleNamespace(shadow_evidence_clock=clock),
        _phase6_redirect_context={
            "planner_policy_ref": "planner-policy",
            "safety_policy_ref": "safety-policy",
            "binding_policy_ref": "binding-policy",
        },
    )
    context = current_execution_context(
        client, record["observation_alignment"], state_id=selected["state_id"],
        watermark=record["step"], production_state=SimpleNamespace())
    return dict(selected=selected, sources=sources, context=context)


def test_all_current_production_proofs_ready_without_execution():
    inputs = ready()
    before = deepcopy(inputs)
    result = evaluate_redirect_evidence(**inputs)
    assert result["status"] == "READY" and result["selected_frontier_execution_ready"]
    assert result["execution_authority"] == "NONE"
    assert result["requires_dispatch_time_revalidation"] is True
    assert inputs == before


@pytest.mark.parametrize("kind,status,expected", [
    ("planner", "UNKNOWN", "UNKNOWN"), ("planner", "BLOCKED", "PLANNER_BLOCKED"),
    ("safety", "UNKNOWN", "UNKNOWN"), ("safety", "RISKY", "SAFETY_BLOCKED"),
    ("safety", "FORBIDDEN", "SAFETY_BLOCKED"), ("binding", "UNRESOLVED", "TARGET_UNRESOLVED"),
    ("presence", "ABSENT", "TARGET_NOT_PRESENT")])
def test_missing_or_blocked_proof_not_ready(kind, status, expected):
    inputs = ready()
    inputs["sources"][kind]["status"] = status
    result = evaluate_redirect_evidence(**inputs)
    assert result["status"] == expected
    assert not result["selected_frontier_execution_ready"]


@pytest.mark.parametrize("kind", list(SOURCES))
def test_provenance_and_exact_target_required(kind):
    inputs = ready()
    del inputs["sources"][kind]["proof_ref"]
    assert evaluate_redirect_evidence(**inputs)["status"] == "UNKNOWN"
    inputs = ready()
    inputs["sources"][kind]["source"] = "graph_novelty"
    assert evaluate_redirect_evidence(**inputs)["status"] == "UNKNOWN"
    inputs = ready()
    inputs["sources"][kind]["target_identity"] = {"instance_id": "different"}
    assert not evaluate_redirect_evidence(**inputs)["selected_frontier_execution_ready"]


@pytest.mark.parametrize("kind,key,value,expected", [
    ("binding", "action_epoch", 0, "EPOCH_MISMATCH"),
    ("binding", "observation_id", "old", "STALE"),
    ("planner", "state_id", "different", "STATE_MISMATCH"),
    ("planner", "substate_ref", "different", "STATE_MISMATCH"),
    ("safety", "decision_watermark", 2, "STALE"),
    ("safety", "policy_ref", "old", "STALE"),
    ("safety", "action_type", "CLICK", "SAFETY_BLOCKED"),
    ("binding", "resolver_ref", None, "TARGET_UNRESOLVED"),
])
def test_alignment_contract(kind, key, value, expected):
    inputs = ready()
    inputs["sources"][kind][key] = value
    result = evaluate_redirect_evidence(**inputs)
    assert result["status"] == expected
    assert not result["selected_frontier_execution_ready"]


def test_no_ownership_pending_action_and_missing_epoch_cannot_be_ready():
    for patch in ({"ownership_ref": None}, {"pending_action": True}, {"action_epoch": None},
                  {"evidence_current": False}, {"observation_epoch": 0}):
        inputs = ready()
        inputs["context"].update(patch)
        assert not evaluate_redirect_evidence(**inputs)["selected_frontier_execution_ready"]


def test_foreign_observation_scope_blocks_redirect_even_when_other_proofs_match():
    inputs = ready()
    inputs["context"]["scope_id"] = "scope-b"
    inputs["context"]["observation_id"] = "observation:scope-b:1"
    result = evaluate_redirect_evidence(**inputs)
    assert result["selected_frontier_execution_ready"] is False
    assert result["status"] == "STALE"
    assert "OBSERVATION_SCOPE_MISMATCH" in result["reason_codes"]


def test_missing_scope_is_unknown_and_same_scope_remains_ready():
    inputs = ready()
    del inputs["context"]["scope_id"]
    result = evaluate_redirect_evidence(**inputs)
    assert result["selected_frontier_execution_ready"] is False
    assert result["reason_codes"] == ["OBSERVATION_SCOPE_UNAVAILABLE"]

    inputs = ready()
    result = evaluate_redirect_evidence(**inputs)
    assert result["selected_frontier_execution_ready"] is True


def test_live_context_projects_active_scope_and_rejects_foreign_observation():
    from tb_runner.redirect_evidence import current_execution_context

    active = EvidenceClock(scope_id="active-scope")
    foreign = EvidenceClock(scope_id="foreign-scope")
    observation = foreign.finish_observation(foreign.begin_observation())
    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=active))
    context = current_execution_context(client, observation, state_id="state-1", watermark=3)
    assert context["scope_id"] == "foreign-scope"
    assert context["active_scope_id"] == "active-scope"
    assert context["evidence_current"] is False

    inputs = ready()
    inputs["context"].update(context)
    result = evaluate_redirect_evidence(**inputs)
    assert result["selected_frontier_execution_ready"] is False
    assert "OBSERVATION_SCOPE_MISMATCH" in result["reason_codes"]


def test_frontier_planner_target_disagreement_is_explicit():
    inputs = ready()
    different = deepcopy(inputs["selected"]["target_identity"])
    different["instance_id"] += ":other"
    different["identity_attributes"]["resource_id"] += ":other"
    inputs["sources"]["planner"]["target_identity"] = different
    result = evaluate_redirect_evidence(**inputs)
    assert result["status"] == "PLANNER_BLOCKED"
    assert result["reason_codes"] == ["PLANNER_TARGET_DISAGREEMENT"]


def test_production_producer_never_restamps_unproven_old_raw(monkeypatch):
    clock = EvidenceClock(action_epoch=9)
    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=clock))
    from tb_runner import state_graph
    monkeypatch.setattr(state_graph, "build_graph_state_identity", lambda raw: SimpleNamespace(state_id="state-1"))
    record_existing_proof(client, kind="planner", status="ELIGIBLE", instance="instance-1",
                          raw={}, step=3, proof={"allowed": True}, policy_ref="planner-v1")
    assert client._phase6_redirect_proofs["planner"]["action_epoch"] is None
    assert client._phase6_redirect_proofs["planner"]["source"] == SOURCES["planner"]
    assert clock.action_epoch == 9


def test_runtime_completion_and_selected_execution_are_independent():
    from test_exploration_shadow import _inputs
    from tb_runner.exploration_shadow import ExplorationShadowRuntime
    inputs = ready()
    selected = inputs["selected"]
    step = inputs["context"]["decision_watermark"]
    kwargs = _inputs(step, state_id=selected["state_id"], items=[selected], evidence_complete=False, unknown_count=1)
    kwargs["frontier_evaluation"]["shadow_next_frontier"] = selected["frontier_id"]
    runtime = ExplorationShadowRuntime("run", "scenario")
    token = runtime.prepare_decision(**kwargs, execution_context=inputs["context"], selected_execution_sources=inputs["sources"])
    assert runtime.finalize_decision(token=token, final_terminal=False)
    record = runtime.decisions[-1]
    assert record["completion_evidence_complete"] is False
    assert record["selected_frontier_execution_ready"] is True
    runtime = ExplorationShadowRuntime("run", "scenario")
    kwargs = _inputs(1, frontier_status="YES", evidence_complete=True)
    token = runtime.prepare_decision(**kwargs)
    assert runtime.finalize_decision(token=token, final_terminal=False)
    assert runtime.decisions[-1]["completion_evidence_complete"] is True
    assert runtime.decisions[-1]["selected_frontier_execution_ready"] is False


def test_policy_change_before_finalize_revokes_selected_ready():
    from test_exploration_shadow import _inputs
    from tb_runner.exploration_shadow import ExplorationShadowRuntime
    inputs = ready()
    step = inputs["context"]["decision_watermark"]
    kwargs = _inputs(step, state_id=inputs["selected"]["state_id"], items=[inputs["selected"]], evidence_complete=False)
    kwargs["frontier_evaluation"]["shadow_next_frontier"] = inputs["selected"]["frontier_id"]
    runtime = ExplorationShadowRuntime("run", "scenario")
    token = runtime.prepare_decision(**kwargs, execution_context=inputs["context"], selected_execution_sources=inputs["sources"])
    inputs["context"]["safety_policy_ref"] = "new-policy"
    assert runtime.finalize_decision(token=token, final_terminal=False,
        current_execution_context=inputs["context"], current_execution_sources=inputs["sources"])
    assert runtime.decisions[-1]["selected_frontier_execution_evidence"]["status"] == "STALE"


def test_frontier_post_result_uses_current_proofs_without_granting_visits():
    from tb_runner.frontier_shadow import FrontierShadowRuntime
    inputs = ready()
    step = inputs["context"]["decision_watermark"]
    runtime = FrontierShadowRuntime("run", "scenario")
    runtime.capture_inventory(step=step, state_id=inputs["selected"]["state_id"],
                              candidates=[inputs["selected"]], inventory_complete=True,
                              observation_ref={"request_id": "action-current"})
    result = runtime.evaluate_post_action(step=step, decision_id=f"decision-{step}", decision_watermark=step,
        state_id=inputs["selected"]["state_id"], execution_sources=inputs["sources"], execution_context=inputs["context"],
        focus_cursor={"instance_id": "other", "confirmed": True}, result_request_id="action-current")
    assert result["counts"]["eligible_count"] == 1
    assert runtime.history["visit_events"] == []
    assert result["shadow_next_frontier"]
    inputs["sources"]["planner"]["status"] = "UNKNOWN"
    result = runtime.evaluate_post_action(step=step, decision_id=f"decision-{step}", decision_watermark=step,
        state_id=inputs["selected"]["state_id"], execution_sources=inputs["sources"], execution_context=inputs["context"],
        result_request_id="action-current")
    assert result["counts"]["eligible_count"] == 0


def test_pending_recovery_is_projected_from_live_production_state():
    from tb_runner.redirect_evidence import current_execution_context
    clock = EvidenceClock()
    clock.dispatch(["shell", "am", "broadcast", "-a", "com.iotpart.sqe.talkbackhelper.SMART_NEXT"])
    observation = clock.finish_observation(clock.begin_observation())
    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=clock),
                             _phase6_redirect_context={"pending_action": False})
    state = SimpleNamespace(food_scan_recovery_pending=True)
    context = current_execution_context(client, observation, state_id="state-1", watermark=3, production_state=state)
    assert context["pending_action"] is True
    assert context["evidence_current"] is True
    state.food_scan_recovery_pending = False
    context = current_execution_context(client, observation, state_id="state-1", watermark=3, production_state=state)
    assert context["pending_action"] is False
    assert clock.action_epoch == 1


def test_ready_cannot_be_rebound_to_a_different_decision_at_finalize():
    from test_exploration_shadow import _inputs
    from tb_runner.exploration_shadow import ExplorationShadowRuntime
    inputs = ready()
    step = inputs["context"]["decision_watermark"]
    kwargs = _inputs(step, state_id=inputs["selected"]["state_id"], items=[inputs["selected"]], evidence_complete=False)
    kwargs["frontier_evaluation"]["shadow_next_frontier"] = inputs["selected"]["frontier_id"]
    runtime = ExplorationShadowRuntime("run", "scenario")
    token = runtime.prepare_decision(**kwargs, execution_context=inputs["context"], selected_execution_sources=inputs["sources"])
    inputs["context"]["decision_watermark"] = 4
    for proof in inputs["sources"].values():
        proof["decision_watermark"] = 4
    runtime.finalize_decision(token=token, final_terminal=False,
        current_execution_context=inputs["context"], current_execution_sources=inputs["sources"])
    assert not runtime.decisions[-1]["selected_frontier_execution_ready"]
    assert runtime.decisions[-1]["selected_frontier_execution_evidence"]["status"] == "STALE"


def test_new_policy_and_new_matching_proof_still_invalidate_pending_evidence():
    from test_exploration_shadow import _inputs
    from tb_runner.exploration_shadow import ExplorationShadowRuntime
    inputs = ready()
    step = inputs["context"]["decision_watermark"]
    kwargs = _inputs(step, state_id=inputs["selected"]["state_id"], items=[inputs["selected"]], evidence_complete=False)
    kwargs["frontier_evaluation"]["shadow_next_frontier"] = inputs["selected"]["frontier_id"]
    runtime = ExplorationShadowRuntime("run", "scenario")
    token = runtime.prepare_decision(**kwargs, execution_context=inputs["context"], selected_execution_sources=inputs["sources"])
    inputs["context"]["safety_policy_ref"] = "new-policy"
    inputs["sources"]["safety"].update(policy_ref="new-policy", proof_ref="new-proof")
    runtime.finalize_decision(token=token, final_terminal=False,
        current_execution_context=inputs["context"], current_execution_sources=inputs["sources"])
    assert runtime.decisions[-1]["selected_frontier_execution_evidence"]["status"] == "STALE"
    assert not runtime.decisions[-1]["selected_frontier_execution_ready"]
