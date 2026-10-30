from dataclasses import FrozenInstanceError, replace
import importlib

import pytest

from talkback_lib.native_dispatch_evidence import (
    DISPATCHED,
    NOT_DISPATCHED,
    UNKNOWN,
    NativeDispatchReceiptStore,
    native_dispatch_checkpoint,
    native_dispatch_evidence,
    native_dispatch_operation,
)
from tb_runner.phase3_context import resolve_phase3_context
from tb_runner.redirect_evidence import (
    CanonicalTargetIdentity,
    EvidenceStateReference,
    FrozenEvidenceMap,
    ProductionEvidenceFrame,
    ProductionRedirectProofProvider,
    RedirectEvidenceBundle,
    TargetProofSet,
    adapt_discovery_candidate_identity,
    adapt_production_frontier_identity,
    adapt_proof_target_identity,
    canonical_target_identity,
    compare_canonical_identities,
    evaluate_redirect_readiness,
    identity_bridge_evidence,
    proof_provenance_for,
    redirect_revalidation_stamp,
)


def _observation_fixture():
    import sys
    sys.path.insert(0, "tests")
    from test_phase4b_authority import value as make_value
    from talkback_lib.exploration_evidence_clock import EvidenceClock
    from tb_runner.phase4a_planner import plan_shadow
    from tb_runner.phase4b_authority import AuthorityEvidence
    from tb_runner.state_graph import build_graph_state_identity
    from test_state_graph import observation as graph_observation

    planner_input, raw = make_value(context="VERIFIED_PLUGIN_CONTEXT")
    graph_context = graph_observation()
    raw.update({key: graph_context[key] for key in (
        "package_name", "activity_name", "context_source", "navigation_context",
        "selected_tab", "observation_coverage")})
    # Rebind the exact root after fixture edits. The envelope proves hierarchy
    # capture only; it intentionally carries no Activity/component proof.
    from phase6d_capture_support import attach_capture_authority
    raw = attach_capture_authority(raw, production=True, sequence=901,
                                   request_id="rf1-capture-local-root")
    clock = EvidenceClock(scope_id="rf1-observation-scope")
    observation = clock.finish_observation(clock.begin_observation())
    from phase6d_capture_support import bind_observation_marker
    bind_observation_marker(raw, observation)
    graph_id = build_graph_state_identity(raw).state_id
    discovery_id = planner_input.snapshot.state_id
    frame = ProductionEvidenceFrame(
        run_id="rf1-run", decision_id="rf1-decision-1", decision_watermark=9,
        observation_id=observation["observation_id"],
        observation_sequence=observation["observation_sequence"],
        scope_id=observation["scope_id"], action_epoch=observation["action_epoch"],
        observation_epoch=observation["observation_epoch"],
        context_revision=observation["context_revision"],
        evidence_current=True, inventory_complete=True,
        graph_state_ref=EvidenceStateReference(
            "graph_state_ref_v1", graph_id, observation["observation_id"],
            observation["observation_sequence"], observation["scope_id"],
            observation["action_epoch"], observation["context_revision"]),
        discovery_state_ref=EvidenceStateReference(
            "discovery_state_scope_v1", discovery_id, observation["observation_id"],
            observation["observation_sequence"], observation["scope_id"],
            observation["action_epoch"], observation["context_revision"]),
        plugin_context=resolve_phase3_context(raw),
        substate=plan_shadow(planner_input).to_dict().get("semantic_substates", []),
        lifecycle_status="CLEAR", helper_status="READY",
        overlay_status="CLEAR", recovery_status="CLEAR", transition_status="CLEAR")
    authority = AuthorityEvidence(
        enabled=True, fresh=True, recovery_clear=True, lifecycle_clear=True,
        transport_clear=True, focus_coherent=True, structural_scope_proven=True,
        geometry_in_viewport=True)
    recommendation = plan_shadow(planner_input).to_dict()
    assert recommendation["recommended_action"] == "FOCUS_CANDIDATE"
    assert graph_id != discovery_id  # separate state namespaces/producers
    result = ProductionRedirectProofProvider().build_target_proof_set(
        frame, planner_input, raw, authority_evidence=authority)
    assert result.build_status == "UNKNOWN", result.reason
    assert result.reason == "CAPTURE_COMPONENT_UNKNOWN"
    return planner_input, raw, frame, result


def _ready_bundle():
    _planner_input, _raw, frame, result = _observation_fixture()
    from tb_runner.frontier_scheduler import build_frontier_id

    frontier_id = build_frontier_id(frame.graph_state_ref.state_id, "TARGETED_FOCUS",
                                    result.production_target.to_dict())
    return RedirectEvidenceBundle(
        run_id=frame.run_id, decision_id=frame.decision_id,
        frontier_id=frontier_id, frontier_state_id=frame.graph_state_ref.state_id,
        frontier_action="TARGETED_FOCUS", frame=frame,
        frontier_target=result.production_target,
        proof_set=result.proof_set,
        frontier_recommendation={"frontier_id": frontier_id,
                                 "edge_type": "TARGETED_FOCUS",
                                 "state_id": frame.graph_state_ref.state_id,
                                 "decision_watermark": frame.decision_watermark,
                                 "substate": list(frame.substate),
                                 "target_identity": result.production_target.to_dict()})


def test_component_unknown_capture_cannot_build_redirect_proofs_or_ready():
    bundle = _ready_bundle()
    assessment = evaluate_redirect_readiness(bundle)
    assert bundle.frame.plugin_context["status"] == "UNRESOLVED_CONTEXT"
    assert bundle.proof_set.proof_complete is False
    assert dict(bundle.proof_set.source_refs) == {}
    assert assessment.status == "UNKNOWN"
    assert "PLUGIN_CONTEXT_UNKNOWN" in assessment.reason_codes
    assert assessment.execution_authority == "NONE"
    assert assessment.phase5_permit_issued is False
    stamp = redirect_revalidation_stamp(bundle, assessment)
    assert stamp.readiness_status == "UNKNOWN"
    assert stamp.permit is False


def test_forged_verified_frame_cannot_override_component_unknown_capture():
    planner_input, raw, frame, _ = _observation_fixture()
    forged = replace(frame, plugin_context={
        "status": "VERIFIED_PLUGIN_CONTEXT",
        "proof_capture_id": raw["capture_id"],
    })
    result = ProductionRedirectProofProvider().build_target_proof_set(
        forged, planner_input, raw)
    assert result.build_status == "UNKNOWN"
    assert result.reason == "CAPTURE_COMPONENT_UNKNOWN"
    assert result.proof_set.proof_complete is False


def test_provider_missing_phase4_input_stays_unknown_and_does_not_invent_ready():
    planner_input, raw, frame, _ = _observation_fixture()
    result = ProductionRedirectProofProvider().build_target_proof_set(
        frame, planner_input, raw)
    assert result.proof_set.phase4_gate_status == "UNKNOWN"
    assert result.proof_set.proof_complete is False
    assert result.proof_set.safety_assessment_status == "UNKNOWN"
    assert result.reason == "CAPTURE_COMPONENT_UNKNOWN"


def test_provider_rejects_misaligned_observation_provenance():
    planner_input, raw, frame, _ = _observation_fixture()
    stale = replace(frame, observation_sequence=frame.observation_sequence + 1)
    result = ProductionRedirectProofProvider().build_target_proof_set(
        stale, planner_input, raw)
    assert result.build_status == "UNKNOWN"
    assert result.proof_set.phase4_gate_status == "UNKNOWN"
    assert result.reason == "PRODUCTION_OBSERVATION_PROVENANCE_MISMATCH"


def test_identity_adapters_keep_domains_and_never_equate_foreign_opaque_ids():
    production = adapt_production_frontier_identity({"target_identity": {
        "identity_domain": "production_scenario_scope_v1", "instance_id": "shared-opaque",
        "identity_attributes": {"resource_id": "id.x", "bounds": "1,2,10,20",
                              "class_name": "Button"}}})
    discovery = adapt_discovery_candidate_identity({"target_identity": {
        "identity_domain": "discovery_state_scope_v1", "instance_id": "shared-opaque",
        "resource_id": "id.x", "bounds": "1,2,10,20", "class_name": "Button"}})
    proof = adapt_proof_target_identity({"target_identity": {
        "identity_domain": "discovery_state_scope_v1", "instance_id": "proof-id",
        "resource_id": "id.x", "bounds": "1,2,10,20", "class_name": "Button"}})
    assert production.status == discovery.status == proof.status == "COMPLETE"
    assert production.identity_domain != discovery.identity_domain
    assert compare_canonical_identities(production, discovery) == "UNKNOWN"
    bridge = identity_bridge_evidence(
        production.to_dict(), {"status": "EXACT_ONE", "reason": "fixture",
                               "candidate": {"target_identity": discovery.to_dict()}})
    # A proof adapter also keeps its own opaque ID and domain.
    assert compare_canonical_identities(production, proof, bridge) == "UNKNOWN"
    assert compare_canonical_identities(production, discovery, bridge) == "COMPATIBLE_CURRENT_TARGET"


def test_nested_flat_identity_conflict_is_invalid_and_partial_is_not_exact():
    conflict = canonical_target_identity({
        "identity_domain": "production_scenario_scope_v1", "instance_id": "p-1",
        "identity_attributes": {"resource_id": "id.a", "bounds": "1,2,10,20",
                                "class_name": "Button"},
        "resource_id": "id.other", "bounds": "1,2,10,20", "class_name": "Button"})
    partial = adapt_discovery_candidate_identity({"target_identity": {
        "identity_domain": "discovery_state_scope_v1", "instance_id": "d-1",
        "resource_id": "id.a", "bounds": "1,2,10,20", "class_name": ""}})
    complete = adapt_production_frontier_identity({
        "identity_domain": "production_scenario_scope_v1", "instance_id": "p-1",
        "identity_attributes": {"resource_id": "id.a", "bounds": "1,2,10,20",
                                "class_name": "Button"}})
    assert conflict.status == "INVALID"
    assert conflict.reason == "IDENTITY_ATTRIBUTE_CONFLICT"
    assert partial.status == "PARTIAL"
    assert compare_canonical_identities(complete, partial) == "UNKNOWN"


def test_bundle_and_nested_contract_values_are_deeply_immutable():
    nested = {"top": {"items": [1, {"value": "before"}]}}
    frame = ProductionEvidenceFrame(plugin_context=nested, substate=nested["top"]["items"])
    nested["top"]["items"][1]["value"] = "after"
    assert frame.plugin_context["top"]["items"][1]["value"] == "before"
    assert frame.substate[1]["value"] == "before"
    with pytest.raises(TypeError):
        frame.plugin_context["top"]["items"][1]["value"] = "mutate"
    with pytest.raises(FrozenInstanceError):
        frame.lifecycle_status = "RESTARTED"

    source = {"nested": {"list": ["a"]}}
    frozen = FrozenEvidenceMap(tuple(source.items()))
    source["nested"]["list"].append("b")
    assert frozen["nested"]["list"] == ("a",)
    with pytest.raises(TypeError):
        frozen["nested"]["list"][0] = "changed"
    with pytest.raises(FrozenInstanceError):
        TargetProofSet().planner_status = "ELIGIBLE"
    bundle_source = {"decision": {"states": ["one"]}}
    bundle = RedirectEvidenceBundle(frontier_recommendation=bundle_source)
    bundle_source["decision"]["states"].append("two")
    assert bundle.frontier_recommendation["decision"]["states"] == ("one",)
    with pytest.raises(TypeError):
        bundle.frontier_recommendation["decision"]["states"][0] = "changed"
    with pytest.raises(TypeError):
        RedirectEvidenceBundle(frame={"mutable": []})


@pytest.mark.parametrize("field,value", [
    ("lifecycle_status", "RESTARTED"), ("lifecycle_status", "UNSETTLED"),
    ("helper_status", "UNAVAILABLE"), ("overlay_status", "BLOCKED"),
    ("recovery_status", "PENDING"), ("transition_status", "PENDING"),
])
def test_known_lifecycle_and_runtime_blockers_block_readiness(field, value):
    bundle = _ready_bundle()
    assessment = evaluate_redirect_readiness(replace(bundle, frame=replace(bundle.frame, **{field: value})))
    assert assessment.status == "BLOCKED"
    assert assessment.execution_authority == "NONE"


def test_missing_required_lifecycle_helper_overlay_recovery_or_transition_is_unknown():
    bundle = _ready_bundle()
    for field in ("plugin_context", "lifecycle_status", "helper_status", "overlay_status",
                  "recovery_status", "transition_status"):
        assessment = evaluate_redirect_readiness(replace(
            bundle, frame=replace(bundle.frame, **{field: None})))
        assert assessment.status == "UNKNOWN", field


def test_known_wrong_plugin_context_blocks_and_recommendation_substate_mismatch_is_unknown():
    bundle = _ready_bundle()
    assessment = evaluate_redirect_readiness(replace(
        bundle, frame=replace(bundle.frame, plugin_context={"status": "WRONG_CONTEXT"})))
    assert assessment.status == "BLOCKED"
    recommendation = dict(bundle.frontier_recommendation)
    recommendation["substate"] = ["other"]
    assert evaluate_redirect_readiness(replace(
        bundle, frontier_recommendation=recommendation)).status == "UNKNOWN"


@pytest.mark.parametrize("proof_field,value", [
    ("planner_status", "BLOCKED"), ("phase4_gate_status", "DENIED"),
    ("binding_status", "UNRESOLVED"), ("presence_status", "ABSENT"),
    ("safety_assessment_status", "RISKY"),
])
def test_explicit_negative_proofs_block_readiness(proof_field, value):
    bundle = _ready_bundle()
    proof = replace(bundle.proof_set, **{proof_field: value})
    assert evaluate_redirect_readiness(replace(bundle, proof_set=proof)).status == "BLOCKED"


@pytest.mark.parametrize("proof_field,value,expected", [
    ("planner_status", "UNKNOWN", "UNKNOWN"),
    ("phase4_gate_status", "UNKNOWN", "UNKNOWN"),
    ("binding_status", "STALE", "BLOCKED"),
    ("presence_status", "UNKNOWN", "UNKNOWN"),
    ("safety_assessment_status", "UNKNOWN", "UNKNOWN"),
    ("proof_complete", False, "UNKNOWN"),
])
def test_partial_or_unverifiable_proofs_fail_closed(proof_field, value, expected):
    bundle = _ready_bundle()
    proof = replace(bundle.proof_set, **{proof_field: value})
    assessment = evaluate_redirect_readiness(replace(bundle, proof_set=proof))
    assert assessment.status == expected


@pytest.mark.parametrize("status,expected", [
    ("NONE", "BLOCKED"), ("AMBIGUOUS", "UNKNOWN"), ("UNKNOWN", "UNKNOWN"),
])
def test_identity_bridge_status_is_fail_closed(status, expected):
    bundle = _ready_bundle()
    bridge = replace(bundle.proof_set.identity_bridge, status=status)
    proof = replace(bundle.proof_set, identity_bridge=bridge)
    assessment = evaluate_redirect_readiness(replace(bundle, proof_set=proof))
    assert assessment.status == expected


def test_component_unknown_cannot_be_promoted_by_target_identity_mutation():
    bundle = _ready_bundle()
    changed = replace(bundle.proof_set.target_identity, bounds="900,900,999,999")
    proof = replace(bundle.proof_set, target_identity=changed)
    assessment = evaluate_redirect_readiness(replace(bundle, proof_set=proof))
    assert assessment.status == "UNKNOWN"
    assert assessment.execution_authority == "NONE"
    assert assessment.phase5_permit_issued is False


@pytest.mark.parametrize("mutate", [
    lambda b: replace(b.frame, scope_id="foreign-scope"),
    lambda b: replace(b.frame, observation_epoch=b.frame.action_epoch + 1),
    lambda b: replace(b.frame, context_revision=None),
])
def test_scope_epoch_or_missing_context_provenance_is_unknown(mutate):
    bundle = _ready_bundle()
    assessment = evaluate_redirect_readiness(replace(bundle, frame=mutate(bundle)))
    assert assessment.status == "UNKNOWN"


def test_watermark_and_state_mismatches_are_unknown():
    bundle = _ready_bundle()
    proof = replace(bundle.proof_set,
                    provenance=replace(bundle.proof_set.provenance, decision_watermark=10))
    assert evaluate_redirect_readiness(replace(bundle, proof_set=proof)).status == "UNKNOWN"
    assert evaluate_redirect_readiness(replace(bundle,
        frontier_state_id="different-graph-state")).status == "UNKNOWN"
    proof = replace(bundle.proof_set, planner_state_id="different-discovery-state")
    assert evaluate_redirect_readiness(replace(bundle, proof_set=proof)).status == "UNKNOWN"
    recommendation = dict(bundle.frontier_recommendation)
    recommendation["decision_watermark"] += 1
    assert evaluate_redirect_readiness(replace(
        bundle, frontier_recommendation=recommendation)).status == "UNKNOWN"


def _focus_command(request_id="request-1"):
    return ["shell", "am", "broadcast", "-a",
            "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT",
            "--es", "reqId", request_id]


def _receipt(store, *, operation_id, request_id="request-1"):
    with native_dispatch_operation(operation_id):
        store.observe(_focus_command(request_id))


def test_native_dispatch_current_receipt_and_post_native_error_are_dispatched_graph_off():
    module = importlib.import_module("talkback_lib.native_dispatch_evidence")
    store = module.NativeDispatchReceiptStore()
    operation = "op-current"
    checkpoint = module.native_dispatch_checkpoint(store, operation_id=operation)
    _receipt(store, operation_id=operation)
    result = module.native_dispatch_evidence(
        checkpoint, store, request_id="request-1", native_boundary_entered=True)
    assert result.dispatch_status == DISPATCHED
    assert result.receipt_match is True
    assert result.operation_id == operation
    assert result.request_id == "request-1"
    assert result.receipt_seq == 1
    assert result.store_generation == store.generation_id

    later = module.native_dispatch_checkpoint(store, operation_id="op-error")
    _receipt(store, operation_id="op-error", request_id="request-error")
    after_error = module.native_dispatch_evidence(
        later, store, request_id="request-error", native_boundary_entered=True,
        operation_error=True)
    assert after_error.dispatch_status == DISPATCHED
    assert after_error.reason == "CURRENT_OPERATION_RECEIPT_AFTER_ERROR"


def test_native_dispatch_precheck_watermark_and_store_generation_fail_closed():
    store = NativeDispatchReceiptStore()
    operation = "op-precheck"
    checkpoint = native_dispatch_checkpoint(store, operation_id=operation)
    rejected = native_dispatch_evidence(checkpoint, store, request_id=None,
        native_boundary_entered=False, precheck_rejected=True)
    assert rejected.dispatch_status == NOT_DISPATCHED

    class BrokenWatermark(NativeDispatchReceiptStore):
        def receipt_watermark(self):
            raise RuntimeError("unavailable")

    broken = BrokenWatermark()
    unknown_checkpoint = native_dispatch_checkpoint(broken, operation_id="op-unknown")
    assert unknown_checkpoint.checkpoint_status == UNKNOWN
    unknown = native_dispatch_evidence(unknown_checkpoint, broken, request_id="request-1",
        native_boundary_entered=True)
    assert unknown.dispatch_status == UNKNOWN
    assert unknown.receipt_watermark_before is None

    current_checkpoint = native_dispatch_checkpoint(store, operation_id="op-replaced")
    replacement = NativeDispatchReceiptStore()
    mismatch = native_dispatch_evidence(current_checkpoint, replacement,
        request_id="request-1", native_boundary_entered=True)
    assert mismatch.dispatch_status == UNKNOWN
    assert mismatch.reason == "STORE_GENERATION_MISMATCH"

    reset_checkpoint = native_dispatch_checkpoint(store, operation_id="op-before-reset")
    store.reset()
    _receipt(store, operation_id="op-before-reset", request_id="request-after-reset")
    reset_mismatch = native_dispatch_evidence(reset_checkpoint, store,
        request_id="request-after-reset", native_boundary_entered=True)
    assert reset_mismatch.dispatch_status == UNKNOWN
    assert reset_mismatch.reason == "STORE_GENERATION_MISMATCH"


def test_native_dispatch_stale_unrelated_and_wrong_operation_receipts_never_prove_current_send():
    store = NativeDispatchReceiptStore()
    _receipt(store, operation_id="old-op", request_id="same-request")
    stale_checkpoint = native_dispatch_checkpoint(store, operation_id="old-op")
    stale = native_dispatch_evidence(stale_checkpoint, store, request_id="same-request",
        native_boundary_entered=False)
    assert stale.dispatch_status == UNKNOWN

    checkpoint = native_dispatch_checkpoint(store, operation_id="current-op")
    _receipt(store, operation_id="unrelated-op", request_id="current-request")
    unrelated = native_dispatch_evidence(checkpoint, store, request_id="current-request",
        native_boundary_entered=False, precheck_rejected=True)
    assert unrelated.dispatch_status == NOT_DISPATCHED

    operation_checkpoint = native_dispatch_checkpoint(store, operation_id="different-op")
    _receipt(store, operation_id="same-request-other-operation", request_id="request-1")
    wrong_operation = native_dispatch_evidence(operation_checkpoint, store,
        request_id="request-1", native_boundary_entered=False)
    assert wrong_operation.dispatch_status == UNKNOWN


def test_native_dispatch_receipt_sequence_survives_full_buffer_rollover():
    store = NativeDispatchReceiptStore()
    for index in range(2048):
        _receipt(store, operation_id=f"old-{index}", request_id=f"old-request-{index}")
    checkpoint = native_dispatch_checkpoint(store, operation_id="after-rollover")
    _receipt(store, operation_id="after-rollover", request_id="request-after-rollover")
    assert len(store.receipts) == 2048
    evidence = native_dispatch_evidence(checkpoint, store,
        request_id="request-after-rollover", native_boundary_entered=True)
    assert evidence.dispatch_status == DISPATCHED
    assert evidence.receipt_seq == 2049


def test_native_dispatch_checkpoint_and_result_contracts_are_immutable_and_clock_free():
    # This module's implementation imports only standard-library dependencies.
    source = importlib.import_module("talkback_lib.native_dispatch_evidence").__file__
    from pathlib import Path
    content = Path(source).read_text(encoding="utf-8")
    assert "exploration_evidence_clock" not in content
    store = NativeDispatchReceiptStore()
    checkpoint = native_dispatch_checkpoint(store, operation_id="op-immutable")
    evidence = native_dispatch_evidence(checkpoint, store, request_id="request-1",
        native_boundary_entered=False, precheck_rejected=True)
    with pytest.raises(FrozenInstanceError):
        checkpoint.receipt_watermark_before = 0
    with pytest.raises(FrozenInstanceError):
        evidence.dispatch_status = DISPATCHED
    queried = store.receipts_after(0)
    assert queried == []


def test_phase4_compatibility_checkpoint_passes_operation_id_to_receipt_context():
    from types import SimpleNamespace
    from tb_runner.phase4b_execution import _target_dispatch_checkpoint

    store = NativeDispatchReceiptStore()
    client = SimpleNamespace(_adb_device=SimpleNamespace(
        native_dispatch_receipts=store, shadow_evidence_clock=None))
    checkpoint_doc = _target_dispatch_checkpoint(client)
    typed = checkpoint_doc["native_dispatch_checkpoint"]
    assert typed.checkpoint_status == "VALID"
    assert checkpoint_doc["operation_id"] == typed.operation_id
    with native_dispatch_operation(checkpoint_doc["operation_id"]):
        store.observe(_focus_command("request-compatible"))
    receipt = store.receipts_after(typed.receipt_watermark_before)[0]
    assert receipt["operation_id"] == typed.operation_id
    assert receipt["request_id"] == "request-compatible"
