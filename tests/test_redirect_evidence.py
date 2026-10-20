from copy import deepcopy
from types import SimpleNamespace

import pytest

from tb_runner.redirect_evidence import SOURCES, evaluate_redirect_evidence, record_existing_proof
from talkback_lib.exploration_evidence_clock import EvidenceClock


def ready():
    selected = dict(frontier_id="frontier-1", candidate_id="candidate-1", state_id="state-1",
                    edge_type="TARGETED_FOCUS", action_type="TARGETED_FOCUS",
                    target_identity={"instance_id": "instance-1"}, status="ELIGIBLE")
    context = dict(state_id="state-1", substate_ref="substate-1", action_epoch=1, observation_epoch=1,
                   observation_id="observation:1", observation_sequence=1, decision_watermark=3,
                   ownership_ref="dispatch:1", action_ownership={"owner": "PRIMARY", "ownership_status": "KNOWN", "action_id": "dispatch:1", "action_epoch": 1},
                   evidence_current=True, pending_action=False,
                   planner_policy_ref="planner-v1", safety_policy_ref="safety-v1", binding_policy_ref="binding-v1")
    sources = {}
    for kind, status in [("planner", "ELIGIBLE"), ("safety", "ALLOWED"), ("binding", "RESOLVED"), ("presence", "PRESENT")]:
        sources[kind] = {**deepcopy(context), "status": status, "source": SOURCES[kind],
                         "proof_ref": kind + ":proof-1", "policy_ref": context.get(kind + "_policy_ref"),
                         "resolver_ref": "resolver:proof-1", "action_type": "FOCUS",
                         "target_identity": deepcopy(selected["target_identity"])}
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


def test_frontier_planner_target_disagreement_is_explicit():
    inputs = ready()
    inputs["sources"]["planner"]["target_identity"] = {"instance_id": "other"}
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
    kwargs = _inputs(3, state_id="state-1", items=[selected], evidence_complete=False, unknown_count=1)
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
    kwargs = _inputs(3, state_id="state-1", items=[inputs["selected"]], evidence_complete=False)
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
    runtime = FrontierShadowRuntime("run", "scenario")
    runtime.capture_inventory(step=3, state_id="state-1", candidates=[inputs["selected"]], inventory_complete=True)
    result = runtime.evaluate_post_action(step=3, decision_id="decision-3", decision_watermark=3,
        state_id="state-1", execution_sources=inputs["sources"], execution_context=inputs["context"],
        focus_cursor={"instance_id": "other", "confirmed": True})
    assert result["counts"]["eligible_count"] == 1
    assert runtime.history["visit_events"] == []
    assert result["shadow_next_frontier"]
    inputs["sources"]["planner"]["status"] = "UNKNOWN"
    result = runtime.evaluate_post_action(step=3, decision_id="decision-3", decision_watermark=3,
        state_id="state-1", execution_sources=inputs["sources"], execution_context=inputs["context"])
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
    kwargs = _inputs(3, state_id="state-1", items=[inputs["selected"]], evidence_complete=False)
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
    kwargs = _inputs(3, state_id="state-1", items=[inputs["selected"]], evidence_complete=False)
    kwargs["frontier_evaluation"]["shadow_next_frontier"] = inputs["selected"]["frontier_id"]
    runtime = ExplorationShadowRuntime("run", "scenario")
    token = runtime.prepare_decision(**kwargs, execution_context=inputs["context"], selected_execution_sources=inputs["sources"])
    inputs["context"]["safety_policy_ref"] = "new-policy"
    inputs["sources"]["safety"].update(policy_ref="new-policy", proof_ref="new-proof")
    runtime.finalize_decision(token=token, final_terminal=False,
        current_execution_context=inputs["context"], current_execution_sources=inputs["sources"])
    assert runtime.decisions[-1]["selected_frontier_execution_evidence"]["status"] == "STALE"
    assert not runtime.decisions[-1]["selected_frontier_execution_ready"]
