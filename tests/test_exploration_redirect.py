from copy import deepcopy
from types import SimpleNamespace

import pytest

from talkback_lib.exploration_evidence_clock import (
    EvidenceClock, NativeDispatchReceiptStore, dispatch_owner,
)
from tb_runner.exploration_redirect import (
    MODE_ENV,
    ExplorationRedirectController,
    RedirectBudget,
    bridge_production_target_to_current_candidate,
    dispatch_provenance_current,
    redirect_mode_from_environment,
    selected_redirect_hint,
    unique_current_candidate,
)


def _scheduler_record(target_instance="instance-1", state_id="state-1", target_identity=None):
    """Construct a closed decision around the real scheduler's output shape."""
    from tb_runner.frontier_scheduler import evaluate_frontier
    from tb_runner.redirect_evidence import SOURCES, evaluate_redirect_evidence

    candidate_id = "candidate-1"
    target_identity = deepcopy(target_identity or {
        "identity_domain": "production_scenario_scope_v1",
        "instance_id": target_instance,
        "identity_attributes": {
            "resource_id": "id.focus",
            "bounds": "10,20,110,120",
            "class_name": "android.widget.Button",
        },
    })
    candidate = {
        "candidate_id": candidate_id,
        "edge_type": "TARGETED_FOCUS",
        "state_id": state_id,
        "target_identity": target_identity,
        "currently_present": True,
        "target_binding_status": "RESOLVED",
    }
    planner = {candidate_id: {
        "state_id": state_id, "edge_type": "TARGETED_FOCUS",
        "action_type": "TARGETED_FOCUS", "target_instance_id": target_instance,
        "status": "ELIGIBLE",
    }}
    safety = {candidate_id: {
        "state_id": state_id, "edge_type": "TARGETED_FOCUS",
        "action_type": "TARGETED_FOCUS", "target_instance_id": target_instance,
        "status": "SAFE",
    }}
    frontier_result = evaluate_frontier(
        {"state_id": state_id, "resolved": True, "inventory_complete": True},
        [candidate],
        {"complete": True, "attempt_events": [], "visit_events": [],
         "exploration_events": [], "validated_aliases": {}, "visits_by_instance": {}},
        planner, safety, focus_cursor={"instance_id": "other-current-focus", "confirmed": True},
    ).to_dict()
    selected = next(item for item in frontier_result["frontier_items"]
                    if item["frontier_id"] == frontier_result["shadow_next_frontier"])
    assert selected["priority_class"] == "P0"
    # This is the actual frontier_scheduler output. Its production identity
    # includes bounded stable attrs; its opaque ID remains scenario-scoped.
    assert selected["target_identity"] == target_identity

    clock = EvidenceClock(scope_id="scope-1")
    with dispatch_owner("SEQUENTIAL"):
        clock.dispatch(["shell", "am", "broadcast", "-a",
                        "com.iotpart.sqe.talkbackhelper.SMART_NEXT", "--es", "reqId", "request-1"])
    observation = clock.finish_observation(clock.begin_observation())
    owner = observation["action_ownership"]
    context = {
        "scope_id": observation["scope_id"], "active_scope_id": clock.scope_id,
        "state_id": state_id, "substate_ref": state_id,
        "observation_id": observation["observation_id"],
        "observation_sequence": observation["observation_sequence"],
        "observation_epoch": observation["action_epoch"], "action_epoch": observation["action_epoch"],
        "decision_watermark": 7, "ownership_ref": owner["action_id"],
        "action_ownership": owner, "pending_action": False,
        "evidence_current": clock.current(observation),
        "planner_policy_ref": "planner-policy", "safety_policy_ref": "safety-policy",
        "binding_policy_ref": "binding-policy",
    }
    sources = {}
    for kind, status in (("planner", "ELIGIBLE"), ("safety", "ALLOWED"),
                         ("binding", "RESOLVED"), ("presence", "PRESENT")):
        policy_ref = {"planner": "planner-policy", "safety": "safety-policy",
                      "binding": "binding-policy"}.get(kind)
        proof = {
            **{key: context.get(key) for key in (
                "scope_id", "state_id", "substate_ref", "observation_id",
                "observation_sequence", "action_epoch", "decision_watermark", "ownership_ref")},
            "status": status, "source": SOURCES[kind], "proof_ref": kind + "-proof",
            "policy_ref": policy_ref, "resolver_ref": kind + "-resolver"
                if kind in {"binding", "presence"} else None,
            "action_type": "FOCUS", "target_identity": deepcopy(selected["target_identity"]),
        }
        sources[kind] = proof
    evidence = evaluate_redirect_evidence(selected=selected, sources=sources, context=context)
    assert evidence["status"] == "READY"
    record = {
        "decision_id": "life_sample_plugin:closed:7", "decision_watermark": 7,
        "step": 7, "decision_stage": "POST_RESULT_N", "decision_evidence_usable": True,
        "stale_status": "NO", "shadow_decision": "REDIRECT_FRONTIER",
        "scope": "CURRENT_STATE_CANDIDATE_FOCUS",
        "state": {"state_id": state_id}, "production": {"final_terminal": False},
        "observation_alignment": observation,
        "current_action_epoch": clock.action_epoch,
        "state_last_meaningful_progress_step": 2,
        "run_last_meaningful_progress_step": 2,
        "selected_frontier": selected,
        "planner_eligible_count": sum(
            item.get("status") == "ELIGIBLE" for item in frontier_result["frontier_items"]),
        "selected_frontier_execution_ready": True,
        "selected_frontier_execution_evidence": evidence,
    }
    return record, clock


def _hint(record=None):
    record = record or _scheduler_record()[0]
    hint, reason = selected_redirect_hint(
        record, scenario_id="life_sample_plugin", scenario_type="content",
        screen_context_mode="new_screen",
    )
    assert reason == "REDIRECT_HINT_VALID"
    assert hint is not None
    return hint


def _inventory(target="instance-1"):
    return [{"candidate_id": "current-candidate", "action_kind": "FOCUS_TARGET",
             "edge_type": "TARGETED_FOCUS",
             "target_identity": {
                 "identity_domain": "discovery_state_scope_v1",
                 "instance_id": "discovery-state::" + str(target),
                 "resource_id": "id.focus", "bounds": "10,20,110,120",
                 "class_name": "android.widget.Button",
             }}]


def _real_frontier_discovery_fixture():
    """Build both identity domains through their production-side producers."""
    from dataclasses import replace

    from test_phase4b_authority import value as authority_value
    from tb_runner.frontier_shadow import production_candidate
    from tb_runner.phase4a_planner import plan_shadow

    scenario = "life_sample_plugin"
    value, raw = authority_value(context="VERIFIED_PLUGIN_CONTEXT")
    value = replace(value, history=replace(value.history, scenario_id=scenario))
    from test_state_graph import observation as graph_observation
    graph_context = graph_observation()
    raw.update({key: graph_context[key] for key in (
        "package_name", "activity_name", "context_source", "navigation_context",
        "selected_tab", "observation_coverage")})
    raw.update(scenario_id=scenario, step=8, overlay={"observed": False},
               display_bounds=[0, 0, 1000, 1000])
    from tb_runner.state_graph import build_graph_state_identity
    state_id = build_graph_state_identity(raw).state_id
    assert state_id
    # Keep this offline fixture's production graph identity aligned with its
    # current planner input so the integrated dispatch path tests real scope
    # agreement instead of an artificial registry-vs-graph mismatch.
    from tb_runner.canonical_json import canonical_json
    from tb_runner.discovery_candidates import DiscoverySnapshot
    snapshot_doc = value.snapshot.to_dict()
    snapshot_doc["state_id"] = state_id
    snapshot = DiscoverySnapshot(state_id, value.snapshot.candidate_set_hash,
                                 value.snapshot.candidates, canonical_json(snapshot_doc))
    value = replace(value, snapshot=snapshot)
    recommendation = plan_shadow(value).to_dict()
    target = recommendation["recommended_target"]
    target_node = next(node for node in raw["nodes"]
                       if (node.get("viewIdResourceName") or node.get("resourceId")) == target["resource_id"]
                       and node.get("boundsInScreen") == target["bounds"])
    production = production_candidate(state_id=state_id, scenario_id=scenario,
                                      candidate=target_node)
    assert production is not None
    record, clock = _scheduler_record(
        target_instance=production["target_identity"]["instance_id"],
        target_identity=production["target_identity"], state_id=state_id)
    raw["_exploration_observation"] = deepcopy(record["observation_alignment"])
    client, evidence = _record_actual_proofs(
        raw=raw, clock=clock, observation=record["observation_alignment"],
        state_id=state_id, step=record["step"],
        instance=production["target_identity"]["instance_id"],
        selected=record["selected_frontier"])
    record["selected_frontier_execution_evidence"] = evidence
    record["selected_frontier_execution_ready"] = evidence.get("selected_frontier_execution_ready") is True
    record["actual_proof_sources"] = client._phase6_redirect_proofs
    current_candidates = value.snapshot.to_dict()["candidates"]
    return value, raw, recommendation, production, record, clock, current_candidates


def _record_actual_proofs(*, raw, clock, observation, state_id, step, instance, selected):
    """Run the production proof recorder against an actual captured hierarchy."""
    from tb_runner.redirect_evidence import (
        current_execution_context, evaluate_redirect_evidence, record_existing_proof,
    )

    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=clock))
    policies = {"planner_policy_ref": "planner-policy", "safety_policy_ref": "safety-policy",
                "binding_policy_ref": "binding-policy"}
    client._phase6_redirect_context = policies
    proofs = (
        ("planner", "ELIGIBLE", "planner-policy", {"allowed": True, "mode": "CONTROLLED_TARGET_FOCUS"}),
        ("safety", "ALLOWED", "safety-policy", {"action_type": "FOCUS", "allowed": True}),
        ("binding", "RESOLVED", "binding-policy", {"resolver": "phase4b.resolve_focus_target"}),
        ("presence", "PRESENT", None, {"resolver": "phase4b.resolve_focus_target"}),
    )
    for kind, status, policy, proof in proofs:
        record_existing_proof(client, kind=kind, status=status, instance=instance,
                              raw=raw, step=step, proof=proof,
                              policy_ref=policy or "presence-policy")
    context = current_execution_context(
        client, observation, state_id=state_id, watermark=step,
        production_state=SimpleNamespace())
    evidence = evaluate_redirect_evidence(
        selected=selected,
        sources=client._phase6_redirect_proofs, context=context)
    # The caller's production frontier is independently checked. This function
    # returns the production records, while tests compare them to that frontier.
    return client, evidence


def test_redirect_mode_is_explicit_opt_in_and_graph_shadow_gated():
    assert redirect_mode_from_environment({}) == "OFF"
    assert redirect_mode_from_environment({MODE_ENV: "invalid"}) == "OFF"
    assert redirect_mode_from_environment({MODE_ENV: "shadow"}) == "SHADOW"
    assert ExplorationRedirectController(mode="ACTIVE", graph_mode="OFF").effective_mode == "OFF"
    assert ExplorationRedirectController(mode="ACTIVE", graph_mode="SHADOW").effective_mode == "ACTIVE"


def test_real_production_and_discovery_ids_bridge_without_opaque_id_equality():
    from tb_runner.redirect_evidence import _identity_agreement

    _value, _raw, _recommendation, production, record, _clock, current = (
        _real_frontier_discovery_fixture())
    assert record["selected_frontier_execution_evidence"]["status"] == "READY"
    assert record["planner_eligible_count"] > 0
    assert record["selected_frontier_execution_evidence"]["target_identity_agreement"]["planner"]["status"] == "EXACT_MATCH"
    for kind, proof in record["actual_proof_sources"].items():
        assert proof["target_identity_source"] == "PRODUCTION_FRONTIER_CANDIDATE"
        assert proof["target_identity"] == record["selected_frontier"]["target_identity"]
    hint = _hint(record)
    assert hint["target_identity"]["identity_domain"] == "production_scenario_scope_v1"
    assert hint["target_identity"] == production["target_identity"]
    focus = [item for item in current if item.get("action_kind") == "FOCUS_TARGET"
             and item.get("target_identity", {}).get("resource_id") ==
                 production["target_identity"]["identity_attributes"]["resource_id"]
             and item.get("target_identity", {}).get("bounds") ==
                 production["target_identity"]["identity_attributes"]["bounds"]]
    assert len(focus) == 1
    assert focus[0]["target_identity"]["identity_domain"] == "discovery_state_scope_v1"
    assert focus[0]["target_identity"]["instance_id"] != production["target_identity"]["instance_id"]
    bridged = bridge_production_target_to_current_candidate(hint["target_identity"], current)
    assert bridged.status == "EXACT_ONE"
    assert bridged.candidate["candidate_id"] == focus[0]["candidate_id"]
    cross_domain = _identity_agreement(
        production["target_identity"], focus[0]["target_identity"],
        identity_bridge={"status": "EXACT_ONE",
                         "target_identity": production["target_identity"],
                         "candidate_identity": focus[0]["target_identity"]})
    assert cross_domain["status"] == "COMPATIBLE_CURRENT_TARGET"

    # The real discovery producer exposes CLICK and FOCUS_TARGET for this same
    # logical node. The bridge filters CLICK before applying uniqueness.
    same_node_click = [item for item in current if item.get("action_kind") == "CLICK"
                       and item.get("target_identity", {}).get("instance_id") ==
                           focus[0]["target_identity"]["instance_id"]]
    if same_node_click:
        assert bridge_production_target_to_current_candidate(
            hint["target_identity"], current).status == "EXACT_ONE"
    assert bridge_production_target_to_current_candidate(
        hint["target_identity"], [*current, deepcopy(focus[0])]).status == "AMBIGUOUS"


def test_actual_proof_producer_disagreement_and_partial_identity_fail_closed():
    from tb_runner.frontier_shadow import production_candidate
    from tb_runner.redirect_evidence import (
        current_execution_context, evaluate_redirect_evidence, record_existing_proof,
    )

    _value, raw, _recommendation, production, record, clock, _current = (
        _real_frontier_discovery_fixture())
    selected = record["selected_frontier"]
    sources = record["actual_proof_sources"]
    other_node = next(node for node in raw["nodes"]
                      if (node.get("viewIdResourceName") or node.get("resourceId")) !=
                         production["target_identity"]["identity_attributes"]["resource_id"]
                      and node.get("boundsInScreen"))
    other = production_candidate(state_id=selected["state_id"],
                                 scenario_id="life_sample_plugin", candidate=other_node)
    assert other is not None
    assert other["target_identity"]["instance_id"] != production["target_identity"]["instance_id"]

    client = SimpleNamespace(_adb_device=SimpleNamespace(shadow_evidence_clock=clock),
                             _phase6_redirect_context={
                                 "planner_policy_ref": "planner-policy",
                                 "safety_policy_ref": "safety-policy",
                                 "binding_policy_ref": "binding-policy"})
    client._phase6_redirect_proofs = deepcopy(sources)
    record_existing_proof(client, kind="planner", status="ELIGIBLE",
                          instance=other["target_identity"]["instance_id"], raw=raw,
                          step=record["step"], proof={"target": "different"},
                          policy_ref="planner-policy")
    context = current_execution_context(client, record["observation_alignment"],
        state_id=selected["state_id"], watermark=record["step"],
        production_state=SimpleNamespace())
    disagreement = evaluate_redirect_evidence(selected=selected,
        sources=client._phase6_redirect_proofs, context=context)
    assert disagreement["status"] == "PLANNER_BLOCKED"
    assert disagreement["reason_codes"] == ["PLANNER_TARGET_DISAGREEMENT"]

    client._phase6_redirect_proofs = deepcopy(sources)
    missing_instance = '["instance-v1","life_sample_plugin","absent","bounds","1,1,2,2"]'
    record_existing_proof(client, kind="planner", status="ELIGIBLE",
                          instance=missing_instance, raw=raw, step=record["step"],
                          proof={"target": "unknown"}, policy_ref="planner-policy")
    partial = evaluate_redirect_evidence(selected=selected,
        sources=client._phase6_redirect_proofs, context=context)
    assert client._phase6_redirect_proofs["planner"]["target_identity_status"] == "PARTIAL_UNKNOWN"
    assert partial["status"] == "UNKNOWN"
    assert partial["reason_codes"] == ["PLANNER_TARGET_IDENTITY_UNKNOWN"]


@pytest.mark.parametrize("change", [
    {"decision_evidence_usable": False},
    {"stale_status": "YES"},
    {"selected_frontier_execution_ready": False},
    {"shadow_decision": "CONTINUE"},
    {"scope": "GLOBAL_NAV"},
    {"state": None},
])
def test_hint_fails_closed_for_nonready_or_out_of_scope_decisions(change):
    record, _clock = _scheduler_record()
    record.update(change)
    hint, _reason = selected_redirect_hint(
        record, scenario_id="life_sample_plugin", scenario_type="content",
        screen_context_mode="new_screen",
    )
    assert hint is None


@pytest.mark.parametrize("scenario_id,scenario_type,screen_mode", [
    ("global_nav", "global_nav", "new_screen"),
    ("life_sample_plugin", "global_nav", "new_screen"),
    ("life_sample_plugin", "content", "same_screen"),
])
def test_hint_excludes_global_nav_and_nonplugin_scope(scenario_id, scenario_type, screen_mode):
    record, _clock = _scheduler_record()
    hint, _ = selected_redirect_hint(record, scenario_id=scenario_id,
        scenario_type=scenario_type, screen_context_mode=screen_mode)
    assert hint is None


def test_current_candidate_lookup_rejects_missing_and_ambiguous_identity():
    record, _clock = _scheduler_record()
    hint = _hint(record)
    assert unique_current_candidate(hint["target_identity"], [])[1] == "NONE"
    assert unique_current_candidate(hint["target_identity"], _inventory() * 2)[1] == "AMBIGUOUS"


def test_current_candidate_lookup_ignores_same_node_nonfocus_action_candidate():
    record, _clock = _scheduler_record()
    hint = _hint(record)
    click = {"candidate_id": "same-node-click", "action_kind": "CLICK",
             "target_identity": _inventory()[0]["target_identity"]}
    candidate, reason = unique_current_candidate(hint["target_identity"], [click, *_inventory()])
    assert reason == "EXACT_ONE"
    assert candidate["candidate_id"] == "current-candidate"


def test_identity_bridge_rejects_insufficient_or_two_focus_matches_without_first_match():
    hint = _hint()
    target = hint["target_identity"]
    incomplete = [{"candidate_id": "missing-class", "action_kind": "FOCUS_TARGET",
                   "target_identity": {"identity_domain": "discovery_state_scope_v1",
                       "resource_id": "id.focus", "bounds": "10,20,110,120"}}]
    assert bridge_production_target_to_current_candidate(target, incomplete).status == "UNKNOWN"
    complete_plus_incomplete = [*_inventory(), *deepcopy(incomplete)]
    result = bridge_production_target_to_current_candidate(target, complete_plus_incomplete)
    assert result.status == "UNKNOWN"
    assert result.reason == "CURRENT_IDENTITY_EVIDENCE_INCOMPLETE"
    two_incomplete = [deepcopy(incomplete[0]), deepcopy(incomplete[0])]
    result = bridge_production_target_to_current_candidate(target, two_incomplete)
    assert result.status == "UNKNOWN"
    two_focus = deepcopy(_inventory()) + deepcopy(_inventory())
    assert bridge_production_target_to_current_candidate(target, two_focus).status == "AMBIGUOUS"
    two_focus[1]["target_identity"] = dict(two_focus[1]["target_identity"], class_name="android.widget.TextView")
    assert bridge_production_target_to_current_candidate(target, two_focus).status == "EXACT_ONE"


def test_nested_and_flat_candidate_conflict_fails_closed():
    from tb_runner.traversal_reliability import redirect_identity_attributes

    identity = {
        "identity_domain": "production_scenario_scope_v1",
        "identity_attributes": {
            "resource_id": "id.focus", "bounds": "10,20,110,120",
            "class_name": "android.widget.Button",
        },
        "resource_id": "id.stale",
        "bounds": "10,20,110,120",
        "class_name": "android.widget.Button",
    }
    attrs, source, error = redirect_identity_attributes(identity)
    assert attrs["resource_id"] == "id.focus"
    assert source == "CONFLICTING_NESTED_AND_FLAT"
    assert error == "IDENTITY_ATTRIBUTE_CONFLICT"
    result = bridge_production_target_to_current_candidate(
        _hint()["target_identity"], [{"candidate_id": "conflict", "edge_type": "TARGETED_FOCUS",
                                    "target_identity": identity}])
    assert result.status == "UNKNOWN"
    assert result.reason == "CURRENT_IDENTITY_ATTRIBUTE_CONFLICT"


def test_real_frontier_cache_shape_bridges_but_incomplete_rf2_readiness_stays_unknown():
    from tb_runner import collection_flow
    from tb_runner.frontier_shadow import FrontierShadowRuntime

    value, _raw, _recommendation, production, record, clock, discovery = (
        _real_frontier_discovery_fixture())
    state_id = record["state"]["state_id"]
    runtime = FrontierShadowRuntime(
        run_id="offline", scenario_id="life_sample_plugin", evidence_clock=clock)
    runtime.capture_inventory(
        step=record["step"], state_id=state_id, candidates=[production],
        inventory_complete=True, observation_ref=record["observation_alignment"])
    cache = runtime._latest_inventory
    cached_identity = cache["candidates"][0]["target_identity"]
    assert cached_identity["identity_domain"] == "production_scenario_scope_v1"
    assert isinstance(cached_identity.get("identity_attributes"), dict)
    assert "resource_id" not in cached_identity

    # Current discovery identity remains a separate domain with a real flat
    # schema. It resolves the same observed production target without opaque
    # instance-ID equality or fixture flattening.
    discovery_bridge = bridge_production_target_to_current_candidate(
        record["selected_frontier"]["target_identity"], discovery)
    assert discovery_bridge.status == "EXACT_ONE"
    assert discovery_bridge.candidate_identity_source == "DISCOVERY_FLAT"

    readiness = collection_flow._phase6d3a_shadow_readiness(
        record=record, inventory_record=cache,
        scenario_id="life_sample_plugin", scenario_type="content",
        screen_context_mode="new_screen",
        evidence_current=clock.current(record["observation_alignment"]))
    # Identity can bridge exactly, but this legacy fixture does not carry the
    # full RF1 production proof bundle required by the common evaluator.
    assert readiness["status"] == "UNKNOWN"
    assert readiness["ready"] is False
    assert readiness["readiness_trace"]["identity_bridge"]
    assert readiness["dispatch_count"] == 0


def test_real_frontier_cache_incomplete_or_conflicting_identity_never_ready():
    from tb_runner import collection_flow
    from tb_runner.frontier_shadow import FrontierShadowRuntime

    _value, _raw, _recommendation, production, record, clock, _discovery = (
        _real_frontier_discovery_fixture())
    state_id = record["state"]["state_id"]
    incomplete = deepcopy(production)
    incomplete["target_identity"]["identity_attributes"]["class_name"] = ""
    runtime = FrontierShadowRuntime(run_id="offline", scenario_id="life_sample_plugin",
                                    evidence_clock=clock)
    runtime.capture_inventory(step=record["step"], state_id=state_id,
                              candidates=[incomplete], inventory_complete=True,
                              observation_ref=record["observation_alignment"])
    readiness = collection_flow._phase6d3a_shadow_readiness(
        record=record, inventory_record=runtime._latest_inventory,
        scenario_id="life_sample_plugin", scenario_type="content",
        screen_context_mode="new_screen",
        evidence_current=clock.current(record["observation_alignment"]))
    assert readiness["status"] in {"BLOCKED", "UNKNOWN"}
    assert readiness["ready"] is False
    assert readiness["readiness_status"] in {"BLOCKED", "UNKNOWN"}
    assert readiness["dispatch_count"] == 0

    conflicting = deepcopy(production)
    conflicting["target_identity"]["resource_id"] = "id.stale"
    runtime.capture_inventory(step=record["step"], state_id=state_id,
                              candidates=[conflicting], inventory_complete=True,
                              observation_ref=record["observation_alignment"])
    readiness = collection_flow._phase6d3a_shadow_readiness(
        record=record, inventory_record=runtime._latest_inventory,
        scenario_id="life_sample_plugin", scenario_type="content",
        screen_context_mode="new_screen",
        evidence_current=clock.current(record["observation_alignment"]))
    assert readiness["status"] in {"BLOCKED", "UNKNOWN"}
    assert readiness["ready"] is False
    assert readiness["readiness_status"] in {"BLOCKED", "UNKNOWN"}
    assert readiness["dispatch_count"] == 0


def test_dispatch_evidence_rejects_prior_request_and_receipt_as_current_proof():
    from talkback_lib.exploration_evidence_clock import dispatch_owner
    from tb_runner.phase4b_execution import (
        _target_dispatch_checkpoint, _redirect_dispatch_evidence_compat,
    )

    clock = EvidenceClock(scope_id="dispatch-evidence-test")
    native = NativeDispatchReceiptStore()
    client = SimpleNamespace(
        _adb_device=SimpleNamespace(shadow_evidence_clock=clock,
                                    native_dispatch_receipts=native),
        _evidence_active_request_id="prior-request",
    )
    with dispatch_owner("TARGETED"):
        command = ["shell", "am", "broadcast", "-a",
                   "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
                   "--es", "reqId", "prior-request"]
        native.observe(command)
        clock.dispatch(command)
    before = _target_dispatch_checkpoint(client)
    proof = _redirect_dispatch_evidence_compat(client, before=before,
        result={"success": False, "status": "ERROR", "reason": "helper_unavailable",
                "reqId": "prior-request"})
    assert proof["dispatch_occurred"] is False
    assert proof["dispatch_evidence_source"] == "NONE"
    assert proof["current_request_id"] == ""
    assert proof["native_receipt_present"] is False
    assert proof["action_epoch_delta"] == 0
    assert proof["preflight_block_reason"] == "helper_unavailable"


@pytest.mark.parametrize("result_status", ["SUCCESS", "ERROR"])
def test_dispatch_evidence_accepts_only_new_matching_native_receipt(result_status):
    from talkback_lib.exploration_evidence_clock import dispatch_owner
    from tb_runner.phase4b_execution import (
        _target_dispatch_checkpoint, _redirect_dispatch_evidence_compat,
    )

    clock = EvidenceClock(scope_id="dispatch-evidence-current")
    native = NativeDispatchReceiptStore()
    client = SimpleNamespace(
        _adb_device=SimpleNamespace(shadow_evidence_clock=clock,
                                    native_dispatch_receipts=native),
        _evidence_active_request_id="previous",
    )
    before = _target_dispatch_checkpoint(client)
    client._evidence_active_request_id = "current-request"
    with dispatch_owner("TARGETED"):
        command = ["shell", "am", "broadcast", "-a",
                   "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
                   "--es", "reqId", "current-request"]
        native.observe(command)
        clock.dispatch(command)
    proof = _redirect_dispatch_evidence_compat(client, before=before,
        result={"success": result_status == "SUCCESS", "status": result_status,
                "reqId": "current-request"})
    assert proof["dispatch_occurred"] is True
    assert proof["dispatch_evidence_source"] == "BOTH"
    assert proof["current_request_id"] == "current-request"
    assert proof["native_receipt_present"] is True
    assert proof["action_epoch_delta"] == 1


def _native_target_command(request_id):
    return ["shell", "am", "broadcast", "-a",
            "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
            "--es", "reqId", request_id]


def test_native_receipt_sequence_detects_current_dispatch_after_full_buffer_rollover():
    from tb_runner.phase4b_execution import _target_dispatch_checkpoint, _redirect_dispatch_evidence_compat

    native = NativeDispatchReceiptStore()
    with dispatch_owner("TARGETED"):
        for index in range(2048):
            native.observe(_native_target_command(f"old-{index}"))
    assert len(native.receipts) == 2048
    client = SimpleNamespace(
        _adb_device=SimpleNamespace(shadow_evidence_clock=None,
                                    native_dispatch_receipts=native),
        _evidence_active_request_id="before-current",
    )
    before = _target_dispatch_checkpoint(client)
    client._evidence_active_request_id = "current-after-rollover"
    with dispatch_owner("TARGETED"):
        native.observe(_native_target_command("unrelated-a"))
        native.observe(_native_target_command("unrelated-b"))
        native.observe(_native_target_command("current-after-rollover"))
    assert len(native.receipts) == 2048
    proof = _redirect_dispatch_evidence_compat(client, before=before,
        result={"success": False, "status": "ERROR", "reqId": "current-after-rollover"})
    assert proof["dispatch_occurred"] is True
    assert proof["dispatch_evidence_source"] == "GENERIC_NATIVE_RECEIPT"
    assert proof["current_request_correlated"] is True
    assert native.receipt_sequence == 2051


def test_stale_and_unrelated_native_receipts_do_not_prove_current_dispatch():
    from tb_runner.phase4b_execution import _target_dispatch_checkpoint, _redirect_dispatch_evidence_compat

    native = NativeDispatchReceiptStore()
    client = SimpleNamespace(
        _adb_device=SimpleNamespace(shadow_evidence_clock=None,
                                    native_dispatch_receipts=native),
        _evidence_active_request_id="previous",
    )
    with dispatch_owner("TARGETED"):
        native.observe(_native_target_command("current-request"))
    before = _target_dispatch_checkpoint(client)
    client._evidence_active_request_id = "current-request"
    with dispatch_owner("TARGETED"):
        native.observe(_native_target_command("unrelated-request"))
    proof = _redirect_dispatch_evidence_compat(client, before=before,
        result={"success": True, "status": "SUCCESS", "reqId": "current-request"})
    assert proof["dispatch_occurred"] is False
    assert proof["dispatch_evidence_source"] == "NONE"
    assert proof["current_request_correlated"] is False


def test_evidence_clock_receipt_query_uses_sequence_across_rollover():
    clock = EvidenceClock(scope_id="clock-rollover")
    with dispatch_owner("TARGETED"):
        for index in range(2048):
            clock.dispatch(_native_target_command(f"old-{index}"))
    watermark = clock.receipt_watermark()
    with dispatch_owner("TARGETED"):
        clock.dispatch(_native_target_command("current-clock-request"))
    assert len(clock.receipts) == 2048
    receipts = clock.receipts_after(watermark, request_id="current-clock-request")
    assert len(receipts) == 1
    assert receipts[0]["receipt_seq"] == watermark + 1


def test_run_reset_reinitializes_only_redirect_owned_state_for_reused_client():
    from tb_runner.collection_flow import _phase6d3a_reset_run_state
    from tb_runner.phase4b_authority import ExecutionBudget

    hint = _hint()
    controller = ExplorationRedirectController(mode="ACTIVE", graph_mode="SHADOW")
    client = SimpleNamespace(_phase6d3a_redirect_controller=controller,
                             _phase6d3a_controlled_budget=ExecutionBudget())
    client.unrelated_cache = {"keep": True}
    assert controller.budget.dispatch_attempt(hint)[0]
    controller.reconciled(hint=hint, reached=False, no_effect=True,
                          wrong_landing=False, new_visit=False, new_state=False,
                          reason="RUN_ONE_FAILURE")
    client._phase6d3a_controlled_budget.reserve(
        "CONTROLLED_TARGET_FOCUS", "target", "inventory", "state")
    assert controller.budget.redirects_used == 1
    assert client._phase6d3a_controlled_budget.actions == 1
    assert controller.budget.consecutive_failures == 1

    _phase6d3a_reset_run_state(client=client, run_id="run-two")

    assert controller.run_id == "run-two"
    assert controller.budget.redirects_used == 0
    assert controller.budget.state_counts == {}
    assert controller.budget.condition_counts == {}
    assert controller.budget.consecutive_failures == 0
    assert controller.budget.active_disabled is False
    assert controller.metrics.counters["REDIRECT_DISPATCH_COUNT"] == 0
    assert controller.events == []
    assert client._phase6d3a_controlled_budget is None
    assert client._phase6d3a_run_identity == "run-two"
    assert client.unrelated_cache == {"keep": True}


def test_redirect_budget_is_consumed_only_at_dispatch_attempt():
    hint = _hint()
    budget = RedirectBudget(max_per_state=2, max_per_run=5)
    assert budget.available(hint)[0] is True
    assert budget.redirects_used == 0
    assert budget.condition_counts == {}
    assert budget.dispatch_attempt(hint)[0] is True
    assert budget.redirects_used == 1
    assert budget.state_counts[hint["state_id"]] == 1
    recaptured = dict(hint, source_observation_id="new-observation", request_id="new-request")
    assert budget.available(recaptured) == (False, "SAME_FRONTIER_CONDITION_ALREADY_USED")


def test_predispatch_blocks_do_not_count_as_failures_and_only_reconciled_attempts_disable():
    hint = _hint()
    controller = ExplorationRedirectController(mode="ACTIVE", graph_mode="SHADOW")
    controller.reconciled(hint=hint, reached=False, no_effect=False,
                          wrong_landing=False, new_visit=False, new_state=False,
                          reason="PREDISPATCH_STALE_BLOCK")
    assert controller.budget.consecutive_failures == 0
    assert controller.budget.active_disabled is False
    assert controller.budget.dispatch_attempt(hint)[0]
    controller.reconciled(hint=hint, reached=False, no_effect=True,
                          wrong_landing=False, new_visit=False, new_state=False,
                          reason="DISPATCHED_NO_EFFECT")
    assert controller.budget.consecutive_failures == 1
    second = dict(hint, frontier_id="frontier-2", state_last_meaningful_progress_step=3)
    assert controller.budget.dispatch_attempt(second)[0]
    controller.reconciled(hint=second, reached=False, no_effect=False,
                          wrong_landing=True, new_visit=False, new_state=False,
                          reason="WRONG_LANDING")
    assert controller.budget.active_disabled is True
    assert controller.metrics.counters["REDIRECT_DISABLED_AFTER_FAILURE_COUNT"] == 1
    assert controller.metrics.counters["REDIRECT_WRONG_LANDING_COUNT"] == 1


def test_reconciled_target_reached_resets_failure_streak_without_granting_visit():
    hint = _hint()
    controller = ExplorationRedirectController(mode="ACTIVE", graph_mode="SHADOW")
    controller.budget.dispatch_attempt(hint)
    controller.reconciled(hint=hint, reached=False, no_effect=True,
                          wrong_landing=False, new_visit=False, new_state=False, reason="NO_EFFECT")
    reached = dict(hint, frontier_id="frontier-2", state_last_meaningful_progress_step=3)
    controller.budget.dispatch_attempt(reached)
    controller.reconciled(hint=reached, reached=True, no_effect=False,
                          wrong_landing=False, new_visit=False, new_state=True,
                          reason="PRODUCTION_TARGET_REACHED")
    assert controller.budget.consecutive_failures == 0
    assert controller.metrics.counters["REDIRECT_TARGET_REACHED_COUNT"] == 1
    assert controller.metrics.counters["NEW_VISIT_AFTER_REDIRECT"] == 0
    assert controller.metrics.counters["NEW_STATE_AFTER_REDIRECT"] == 0


def test_new_state_metric_uses_finalized_progress_evaluator_novelty_only():
    from tb_runner.collection_flow import _phase6d3a_apply_progress_novelty
    from tb_runner.exploration_progress import ExplorationHistory, evaluate_exploration_progress
    from test_exploration_progress import _inputs

    history = ExplorationHistory()
    results = []
    for step, state_id in enumerate(("state-A", "state-B", "state-A", "state-B", "state-C"), 1):
        arguments = _inputs(step, state_id=state_id)
        arguments["progress_history"] = history
        evaluation = evaluate_exploration_progress(**arguments)
        results.append((state_id, evaluation))
        history = evaluation.proposed_history
    unknown_arguments = _inputs(6, state_id=None)
    unknown_arguments["progress_history"] = history
    unknown = evaluate_exploration_progress(**unknown_arguments)

    controller = ExplorationRedirectController(mode="ACTIVE", graph_mode="SHADOW")
    client = SimpleNamespace(_phase6d3a_redirect_controller=controller)

    def apply(state_id, evaluation, *, resolved=True):
        row = {"phase6d3a_redirect": {"mode": "ACTIVE", "dispatch_attempted": True}}
        decision = {
            "decision_evidence_usable": True,
            "state": {"identity_status": "RESOLVED" if resolved else "UNRESOLVED",
                      "state_id": state_id if resolved else ""},
            "progress_reasons": list(evaluation.reason_codes),
        }
        _phase6d3a_apply_progress_novelty(client=client, row=row, decision=decision)
        return row["phase6d3a_redirect"]

    known_b = apply("state-B", results[3][1])
    assert "NEW_RESOLVED_STATE" not in results[3][1].reason_codes
    assert known_b["new_state_after_redirect"] is False
    assert controller.metrics.counters["NEW_STATE_AFTER_REDIRECT"] == 0

    first_seen_c = apply("state-C", results[4][1])
    assert "NEW_RESOLVED_STATE" in results[4][1].reason_codes
    assert first_seen_c["new_state_after_redirect"] is True
    assert first_seen_c["state_progress_metric_source"] == "FINALIZED_PHASE6_PROGRESS_EVALUATOR"
    assert controller.metrics.counters["NEW_STATE_AFTER_REDIRECT"] == 1

    unresolved = apply("", unknown, resolved=False)
    assert unresolved["new_state_after_redirect"] is None
    assert controller.metrics.counters["NEW_STATE_AFTER_REDIRECT"] == 1


def test_final_dispatch_currentness_rejects_action_epoch_and_watermark_changes():
    record, clock = _scheduler_record()
    hint = _hint(record)
    observation = record["observation_alignment"]
    args = dict(
        record=record, hint=hint, clock=clock, current_observation=observation,
        current_state_id=hint["state_id"], current_substate_ref=hint["state_id"],
        plugin_context_current=True, target_unique=True, planner_agrees=True,
        phase4_allowed=True, lifecycle_clear=True, helper_ready=True,
        overlay_clear=True, recovery_clear=True,
    )
    assert dispatch_provenance_current(**args) == (True, "FINAL_PROVENANCE_CURRENT")
    clock.dispatch(["shell", "am", "broadcast", "-a",
                    "com.iotpart.sqe.talkbackhelper.SMART_NEXT", "--es", "reqId", "intervening"])
    assert dispatch_provenance_current(**args) == (False, "CURRENT_OBSERVATION_STALE")

    record2, clock2 = _scheduler_record()
    hint2 = _hint(record2)
    record2["decision_watermark"] += 1
    assert dispatch_provenance_current(**{**args, "record": record2, "hint": hint2,
        "clock": clock2, "current_observation": record2["observation_alignment"]}) == (
            False, "DECISION_WATERMARK_OR_CLOSED_STATUS_STALE")


def test_final_dispatch_negative_matrix_blocks_unknown_mismatch_and_unstable_inputs():
    record, clock = _scheduler_record()
    hint = _hint(record)
    base = dict(
        record=record, hint=hint, clock=clock,
        current_observation=record["observation_alignment"],
        current_state_id=hint["state_id"], current_substate_ref=hint["state_id"],
        plugin_context_current=True, target_unique=True, planner_agrees=True,
        phase4_allowed=True, lifecycle_clear=True, helper_ready=True,
        overlay_clear=True, recovery_clear=True,
    )
    for key, expected in (
        ("target_unique", "TARGET_NOT_UNIQUELY_RESOLVABLE"),
        ("planner_agrees", "PLANNER_DISAGREEMENT"),
        ("phase4_allowed", "PHASE4_GATE_BLOCKED"),
        ("lifecycle_clear", "LIFECYCLE_UNSTABLE"),
        ("helper_ready", "HELPER_NOT_READY"),
        ("overlay_clear", "OVERLAY_NOT_CLEARED"),
        ("recovery_clear", "RECOVERY_OR_TRANSITION_PENDING"),
        ("plugin_context_current", "PLUGIN_CONTEXT_CHANGED_OR_UNVERIFIED"),
    ):
        result, reason = dispatch_provenance_current(**{**base, key: False})
        assert result is False and reason == expected


def test_shadow_missing_rf1_proofs_stays_unknown_and_calls_production_once(monkeypatch):
    from tb_runner import collection_flow
    from tb_runner.frontier_shadow import FrontierShadowRuntime

    _value, _raw, _recommendation, production, record, clock, _current_candidates = (
        _real_frontier_discovery_fixture())
    controller = ExplorationRedirectController(mode="SHADOW", graph_mode="SHADOW")
    frontier_runtime = FrontierShadowRuntime(
        run_id="offline", scenario_id="life_sample_plugin", evidence_clock=clock)
    frontier_runtime.capture_inventory(
        step=record["step"], state_id=record["state"]["state_id"],
        candidates=[production], inventory_complete=True,
        observation_ref=record["observation_alignment"])
    assert frontier_runtime._latest_inventory["candidates"][0]["target_identity"].get(
        "identity_attributes")
    io = {"focus": 0, "hierarchy": 0, "adb": 0, "os_probe": 0, "capture_observation": 0}
    focus_node = {"accessibilityFocused": True, "resourceId": "id.focus"}

    def get_focus(**_kwargs):
        io["focus"] += 1
        return focus_node

    def dump_hierarchy(**_kwargs):
        io["hierarchy"] += 1
        return {"windows": []}

    def adb_command(command, **_kwargs):
        io["adb"] += 1
        if "getprop" in command:
            io["os_probe"] += 1
        return "offline-read"

    client = SimpleNamespace(
        _phase6d3a_redirect_controller=controller,
        _phase6d_exploration_shadow_runtime=SimpleNamespace(decisions=[record]),
        _phase6c2_frontier_shadow_runtime=frontier_runtime,
        _adb_device=SimpleNamespace(shadow_evidence_clock=clock),
        get_focus=get_focus, dump_hierarchy=dump_hierarchy,
    )
    client._run = lambda command, dev=None: client._adb_device._run_adb_command(command, dev=dev)
    client._adb_device._run_adb_command = adb_command
    calls = []
    io_at_collector_return = {}

    def capture(*_args, **_kwargs):
        io["capture_observation"] += 1
        pytest.fail("SHADOW must not call state_fingerprint_diagnostic.capture_observation")

    monkeypatch.setattr(collection_flow, "_phase6d3a_capture_current",
                        lambda **_kwargs: pytest.fail("SHADOW must not call active capture"))
    monkeypatch.setattr("tools.state_fingerprint_diagnostic.capture_observation", capture)

    def collect(**kwargs):
        calls.append(kwargs)
        # Exercise the actual callable boundaries used by the production
        # collector. SHADOW may observe their calls, but must add none after
        # the production collector returns.
        client.get_focus(dev="offline")
        client.dump_hierarchy(dev="offline")
        client._run(["shell", "getprop", "ro.build.version.sdk"], dev="offline")
        # Model the normal production SMART_NEXT dispatch after its existing
        # evidence was frozen for the read-only SHADOW comparison.
        clock.dispatch(["shell", "am", "broadcast", "-a",
                        "com.iotpart.sqe.talkbackhelper.SMART_NEXT", "--es", "reqId", "prod"])
        io_at_collector_return.update(io)
        return {"production_result": "R"}

    row = collection_flow._phase6d3a_intercept_focus_step(
        original_collect=collect, collect_kwargs={"move": True, "direction": "next"},
        client=client, dev="offline", state=SimpleNamespace(),
        phase_ctx=SimpleNamespace(), step_idx=8,
        tab_cfg={"scenario_id": "life_sample_plugin", "scenario_type": "content",
                 "screen_context_mode": "new_screen"},
    )
    assert row == {"production_result": "R"}
    assert len(calls) == 1
    assert client._phase6d3a_last_step_audit["status"] == "UNKNOWN"
    assert client._phase6d3a_last_step_audit["ready"] is False
    assert client._phase6d3a_last_step_audit["dispatch_count"] == 0
    assert client._phase6d3a_last_step_audit["visit_credit"] == 0
    assert io == io_at_collector_return
    assert io == {"focus": 1, "hierarchy": 1, "adb": 1, "os_probe": 1,
                  "capture_observation": 0}
    assert client._phase6d3a_last_step_audit["identity_bridge"]
    assert client._phase6d3a_last_step_audit["readiness_trace"]["proof"]["proof_complete"] is False


def test_shadow_diagnostic_exception_preserves_result_and_never_reexecutes_collector(monkeypatch):
    from tb_runner import collection_flow

    record, clock = _scheduler_record()
    controller = ExplorationRedirectController(mode="SHADOW", graph_mode="SHADOW")
    client = SimpleNamespace(
        _phase6d3a_redirect_controller=controller,
        _phase6d_exploration_shadow_runtime=SimpleNamespace(decisions=[record]),
        _phase6c2_frontier_shadow_runtime=SimpleNamespace(_latest_inventory={}),
        _adb_device=SimpleNamespace(shadow_evidence_clock=clock),
    )
    marker = object()
    calls = []
    monkeypatch.setattr(collection_flow, "_phase6d3a_shadow_readiness",
                        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("diagnostic")))
    result = collection_flow._phase6d3a_intercept_focus_step(
        original_collect=lambda **kwargs: calls.append(kwargs) or marker,
        collect_kwargs={"move": True, "direction": "next"}, client=client, dev="offline",
        state=SimpleNamespace(), phase_ctx=SimpleNamespace(), step_idx=8,
        tab_cfg={"scenario_id": "life_sample_plugin", "scenario_type": "content"},
    )
    assert result is marker
    assert len(calls) == 1
    assert client._phase6d3a_last_step_audit["status"] == "DIAGNOSTIC_ERROR"


def test_off_main_loop_hook_is_behaviorally_transparent():
    from tb_runner import collection_flow

    def production():
        return {"move_result": "MOVED", "focus_transition_status": "CONFIRMED_MOVED",
                "visit_record_status": "RECORDED", "stop_reason": "", "summary": "same"}

    direct = production()
    client = SimpleNamespace(_phase6d3a_redirect_controller=
                             ExplorationRedirectController(mode="OFF", graph_mode="SHADOW"))
    wrapped, decision_id = collection_flow._run_main_step_with_frontier_shadow(
        client=client, state=SimpleNamespace(previous_step_row={}), step_idx=1,
        tab_cfg={"scenario_id": "life_sample_plugin", "scenario_type": "content"},
        collect_step_fn=production, phase_ctx=SimpleNamespace(), dev="offline",
    )
    assert wrapped == direct
    assert decision_id is None
    assert not hasattr(client, "_phase6d3a_last_step_audit")


def test_production_reconciliation_is_only_source_for_redirect_success_and_visit_metrics():
    from tb_runner import collection_flow

    hint = _hint()
    controller = ExplorationRedirectController(mode="ACTIVE", graph_mode="SHADOW")
    controller.budget.dispatch_attempt(hint)
    client = SimpleNamespace(_phase6d3a_redirect_controller=controller)
    row = {"phase6d3a_redirect": {**hint, "mode": "ACTIVE", "dispatch_attempted": True,
                                  "target_identity": hint["target_identity"]},
           "focus_transition_status": "CONFIRMED_MOVED", "actual_focus_instance_id": "instance-1",
           "actual_focus_accessibility_focused": True,
           "actual_focus_node": {"accessibilityFocused": True},
           "visit_record_status": "RECORDED", "reconciled_visit_instance_id": "instance-1"}
    # State identity is intentionally unknown in this small fixture; focus and
    # visit truth still comes only from the production reconciliation row.
    collection_flow._phase6d3a_record_production_reconciliation(client=client, row=row)
    audit = row["phase6d3a_redirect"]
    assert audit["production_target_reached"] is True
    assert audit["new_visit_after_redirect"] is True
    assert audit["visit_credit"] == 0
    assert controller.budget.consecutive_failures == 0


@pytest.mark.parametrize("case", [
    "success", "epoch_mismatch", "two_preflight_blocks", "watermark_mismatch", "state_substate_mismatch",
    "controlled_budget_exhausted", "redirect_budget_exhausted", "no_effect_fallback",
    "helper_unavailable_prior_request", "post_dispatch_error",
    "post_dispatch_exception", "fallback_exception",
])
def test_active_adapter_enforces_dispatch_and_fallback_contracts(monkeypatch, tmp_path, case):
    """RF4: replace the legacy READY/capture seam with production evidence."""
    from test_phase6d3a_rf4_active import (
        test_active_positive_existing_production_authorities,
        test_active_negative_zero_native,
        test_active_exception_accounting_no_duplicate,
    )
    negatives = {"epoch_mismatch": "epoch", "two_preflight_blocks": "epoch",
        "watermark_mismatch": "watermark", "state_substate_mismatch": "substate",
        "controlled_budget_exhausted": "controlled_budget",
        "redirect_budget_exhausted": "budget"}
    exceptions = {"no_effect_fallback": "no_effect", "helper_unavailable_prior_request": "precheck",
        "post_dispatch_error": "ack_error", "post_dispatch_exception": "observation_exception",
        "fallback_exception": "fallback"}
    if case == "success":
        test_active_positive_existing_production_authorities(monkeypatch)
    elif case in negatives:
        test_active_negative_zero_native(monkeypatch, negatives[case])
    else:
        test_active_exception_accounting_no_duplicate(monkeypatch, exceptions[case])



def test_phase5_pre_dispatch_fallback_is_observation_only_and_exactly_once():
    from tb_runner.phase5b_navigation import SafeNavigationSession

    session = SafeNavigationSession("life_sample_plugin", lambda *_args: None)
    actions = []
    observed = {"viewIdResourceName": "id.focus", "className": "Button",
                "boundsInScreen": "0,0,100,100", "accessibilityFocused": True}
    client = SimpleNamespace(
        evidence_runtime=SimpleNamespace(is_enabled=False),
        last_smart_nav_result={}, last_smart_nav_terminal=False,
        _evidence_set_step=lambda *_args, **_kwargs: None,
        _evidence_begin_step_action=lambda *_args, **_kwargs: None,
        _read_log_result=lambda *_args, **_kwargs: {},
        _broadcast=lambda *_args, **_kwargs: None,
        _evidence_action_sent=lambda **_kwargs: None,
        _evidence_helper_ack=lambda *_args, **_kwargs: None,
        get_focus=lambda **_kwargs: observed,
    )

    def collect(**kwargs):
        actions.append(dict(kwargs))
        return {"actual_focus_node": observed, "get_focus_req_id": "readonly-observation"}

    result = session.collect(collect, {"move": True, "direction": "next", "step_index": 4},
                             {"planner_executed": False}, client)
    assert result["actual_focus_node"] is observed
    assert len(actions) == 1
    assert actions[0]["move"] is False
    assert not any(action.get("direction") == "next" and action.get("move") is True
                   for action in actions)
