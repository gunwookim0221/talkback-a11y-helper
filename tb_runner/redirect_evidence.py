"""Pure selected-frontier evidence contract, with no execution authority.

Completion of an inventory and readiness of one target are independent facts.
READY describes current evidence only; future execution must re-enter the
existing Phase4 gate/resolver and Phase5 FOCUS authorization at dispatch time.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

_KINDS = {"planner": ("ELIGIBLE", "PLANNER_BLOCKED"),
          "safety": ("ALLOWED", "SAFETY_BLOCKED"),
          "binding": ("RESOLVED", "TARGET_UNRESOLVED"),
          "presence": ("PRESENT", "TARGET_NOT_PRESENT")}
_BLOCKED = {"BLOCKED", "DENIED", "INELIGIBLE", "UNSUPPORTED", "UNSAFE", "RISKY", "FORBIDDEN", "MISSING", "ABSENT", "AMBIGUOUS", "UNRESOLVED"}
_SCOPE = ("scope_id", "state_id", "substate_ref", "observation_id", "observation_sequence",
          "action_epoch", "decision_watermark", "ownership_ref")
SOURCES = {"planner": "phase4b.execution_gate", "safety": "phase5b.authorize_focus_target",
           "binding": "phase4b.resolve_focus_target", "presence": "phase4b.resolve_focus_target"}


def evaluate_redirect_evidence(*, selected, sources=None, context=None):
    selected = selected if isinstance(selected, Mapping) else {}
    sources = sources if isinstance(sources, Mapping) else {}
    sources = {kind: sources.get(kind) if isinstance(sources.get(kind), Mapping) else {} for kind in _KINDS}
    context = context if isinstance(context, Mapping) else {}
    result = {
        "frontier_id": selected.get("frontier_id"), "candidate_id": selected.get("candidate_id"),
        "state_id": selected.get("state_id"), "edge_type": selected.get("edge_type", selected.get("action_type")),
        "target_identity": deepcopy(selected.get("target_identity") or {}),
        "decision_watermark": context.get("decision_watermark"),
        "scope_id": context.get("scope_id"),
        "active_scope_id": context.get("active_scope_id"),
        "action_epoch": context.get("action_epoch"), "observation_epoch": context.get("observation_epoch"),
        "observation_id": context.get("observation_id"), "observation_sequence": context.get("observation_sequence"),
        "substate_ref": context.get("substate_ref"),
        "action_ownership": deepcopy(context.get("action_ownership") or {}),
        "recommendation_owner": "SHADOW_ONLY", "execution_authority": "NONE",
        "requires_dispatch_time_revalidation": True,
        "revalidation_status": "REQUIRES_DISPATCH_TIME_REVALIDATION",
        "evidence_current": False, "selected_frontier_execution_ready": False,
        "status": "UNKNOWN", "reason_codes": [], "proofs": {},
        "frontier_target": deepcopy(selected.get("target_identity") or {}),
        "planner_revalidated_target": deepcopy((sources.get("planner") or {}).get("target_identity") or {}),
    }
    def fail(status, reason):
        result.update(status=status, reason_codes=[reason])
        return result
    # Copy only bounded references/statuses, never hierarchy or UI labels.
    for kind in _KINDS:
        proof = sources.get(kind)
        proof = proof if isinstance(proof, Mapping) else {}
        result["proofs"][kind] = {key: proof.get(key) for key in
            ("status", "source", "proof_ref", "policy_ref", "resolver_ref", "action_type", *_SCOPE)}
        result[kind + "_evidence_status"] = proof.get("status", "UNKNOWN")
        result[kind + "_evidence_ref"] = proof.get("proof_ref")
    result["planner_eligible"] = (sources.get("planner") or {}).get("status") == "ELIGIBLE"
    result["action_specific_safety"] = result["safety_evidence_status"]
    result["target_binding_status"] = result["binding_evidence_status"]
    result["target_present"] = (sources.get("presence") or {}).get("status") == "PRESENT"
    if (not selected.get("frontier_id") or not isinstance(selected.get("target_identity"), Mapping)
            or not selected["target_identity"].get("instance_id")):
        return fail("UNKNOWN", "SELECTED_FRONTIER_UNAVAILABLE")
    scope_id = context.get("scope_id")
    active_scope_id = context.get("active_scope_id")
    if (not isinstance(scope_id, str) or not scope_id
            or not isinstance(active_scope_id, str) or not active_scope_id):
        return fail("STALE", "OBSERVATION_SCOPE_UNAVAILABLE")
    if scope_id != active_scope_id:
        return fail("STALE", "OBSERVATION_SCOPE_MISMATCH")
    sequence = context.get("observation_sequence")
    if type(sequence) is not int or context.get("observation_id") != f"observation:{scope_id}:{sequence}":
        return fail("STALE", "OBSERVATION_SCOPE_MISMATCH")
    if context.get("evidence_current") is not True:
        return fail("STALE", "OBSERVATION_NOT_CURRENT")
    if (type(context.get("action_epoch")) is not int or type(context.get("observation_epoch")) is not int
            or context.get("observation_epoch") != context.get("action_epoch")):
        return fail("EPOCH_MISMATCH", "ACTION_OBSERVATION_EPOCH_MISMATCH")
    if any(type(context.get(key)) is not int for key in ("decision_watermark", "observation_sequence")):
        return fail("UNKNOWN", "DECISION_OR_OBSERVATION_SEQUENCE_UNAVAILABLE")
    if not context.get("state_id") or selected.get("state_id") != context.get("state_id"):
        return fail("STATE_MISMATCH", "SELECTED_STATE_MISMATCH")
    expected_action_id = f"dispatch:{active_scope_id}:{context.get('action_epoch')}"
    if (context.get("pending_action") is not False or not context.get("ownership_ref")
            or (context.get("action_ownership") or {}).get("ownership_status") != "KNOWN"
            or (context.get("action_ownership") or {}).get("action_id") != context.get("ownership_ref")
            or (context.get("action_ownership") or {}).get("action_epoch") != context.get("action_epoch")
            or context.get("ownership_ref") != expected_action_id
            or (context.get("action_ownership") or {}).get("action_id")
               != expected_action_id):
        return fail("OWNERSHIP_UNRESOLVED", "ACTION_OWNERSHIP_UNRESOLVED")
    if result["edge_type"] != "TARGETED_FOCUS":
        return fail("UNKNOWN", "ONLY_FOCUS_EVIDENCE_CONTRACT_SUPPORTED")
    for kind, (allowed, blocked) in _KINDS.items():
        proof = sources.get(kind) or {}
        if not isinstance(proof, Mapping) or not proof.get("proof_ref") or not proof.get("source"):
            return fail("UNKNOWN", kind.upper() + "_PROOF_UNAVAILABLE")
        if proof.get("source") != SOURCES[kind]:
            return fail("UNKNOWN", kind.upper() + "_PRODUCTION_SOURCE_UNPROVEN")
        if proof.get("status") != allowed:
            return fail(blocked if proof.get("status") in _BLOCKED else "UNKNOWN", kind.upper() + "_NOT_PROVEN")
        if proof.get("target_identity") != selected.get("target_identity"):
            return fail("PLANNER_BLOCKED" if kind == "planner" else "TARGET_UNRESOLVED", kind.upper() + "_TARGET_DISAGREEMENT")
        for key in _SCOPE:
            if (context.get(key) is None or context.get(key) == "" or proof.get(key) != context.get(key)
                    or type(proof.get(key)) is not type(context.get(key))):
                status = "EPOCH_MISMATCH" if key == "action_epoch" else "STATE_MISMATCH" if key in {"state_id", "substate_ref"} else "STALE"
                return fail(status, kind.upper() + "_" + key.upper() + "_MISMATCH")
        if kind in {"planner", "safety", "binding"}:
            policy = context.get(kind + "_policy_ref")
            if not policy or proof.get("policy_ref") != policy:
                return fail("STALE", kind.upper() + "_POLICY_NOT_CURRENT")
        if kind == "safety" and proof.get("action_type") != "FOCUS":
            return fail("SAFETY_BLOCKED", "ACTION_SPECIFIC_FOCUS_PROOF_REQUIRED")
        if kind in {"binding", "presence"} and not proof.get("resolver_ref"):
            return fail("TARGET_UNRESOLVED", "EXACT_RESOLVER_REFERENCE_REQUIRED")
    result.update(status="READY", evidence_current=True, selected_frontier_execution_ready=True)
    return result


def record_existing_proof(client, *, kind, status, instance, raw, step, proof, policy_ref):
    """Observe an already executed production gate/resolver; never run one here.

    Missing capture provenance is deliberately retained as UNKNOWN scope. In
    particular the producer must never stamp an old raw tree with the live epoch.
    A future active preparation must supply provenance from its own reacquisition.
    """
    from talkback_lib.exploration_evidence_clock import clock_for
    from tb_runner.canonical_json import canonical_sha256
    from tb_runner.state_graph import build_graph_state_identity
    clock = clock_for(client)
    if clock is None:
        return
    try:
        capture = raw.get("_exploration_observation") or {}
        state = build_graph_state_identity(raw)
        owner = capture.get("action_ownership") or {}
        context = dict(scope_id=capture.get("scope_id"), active_scope_id=clock.scope_id,
                       state_id=state.state_id, substate_ref=state.state_id,
                       observation_id=capture.get("observation_id"), observation_sequence=capture.get("observation_sequence"),
                       observation_epoch=capture.get("action_epoch"), action_epoch=capture.get("action_epoch"),
                       decision_watermark=step, ownership_ref=owner.get("action_id"),
                       action_ownership=deepcopy(owner), pending_action=False)
        sources = getattr(client, "_phase6_redirect_proofs", {})
        sources = dict(sources) if isinstance(sources, Mapping) else {}
        context_before = getattr(client, "_phase6_redirect_context", {})
        for key in ("planner_policy_ref", "safety_policy_ref", "binding_policy_ref"):
            if isinstance(context_before, Mapping) and key in context_before:
                context[key] = context_before[key]
        context[kind + "_policy_ref"] = policy_ref
        source_ref = SOURCES[kind] + ":" + canonical_sha256(proof)
        sources[kind] = {**{k: context.get(k) for k in _SCOPE}, "status": status,
                         "source": SOURCES[kind], "proof_ref": source_ref, "policy_ref": policy_ref,
                         "resolver_ref": source_ref if kind in {"binding", "presence"} else None,
                         "action_type": "FOCUS", "target_identity": {"instance_id": instance}}
        client._phase6_redirect_proofs = sources
        client._phase6_redirect_context = context
    except Exception:
        # Observability failure removes proof, never changes production behavior.
        client._phase6_redirect_proofs = {}


def current_execution_context(client, observation, *, state_id, watermark, production_state=None):
    """Pure projection from already available evidence; no acquisition or planning."""
    from talkback_lib.exploration_evidence_clock import clock_for
    clock = clock_for(client)
    context = dict(getattr(client, "_phase6_redirect_context", {}) or {})
    owner = observation.get("action_ownership") or {}
    context.update(scope_id=observation.get("scope_id"),
                   active_scope_id=clock.scope_id if clock else None,
                   state_id=state_id, substate_ref=state_id, decision_watermark=watermark,
                   action_epoch=clock.action_epoch if clock else None,
                   observation_epoch=observation.get("action_epoch"), observation_id=observation.get("observation_id"),
                   observation_sequence=observation.get("observation_sequence"), action_ownership=owner,
                   ownership_ref=owner.get("action_id"), evidence_current=clock.current(observation) if clock else False)
    # A cached proof cannot assert that the current production action queue is
    # idle. Project the existing in-memory recovery/tab/realignment state.
    pending_fields = ("food_scan_recovery_pending", "forced_local_tab_target_rid",
                      "forced_local_tab_target_action_label", "post_realign_pending_steps",
                      "pending_scroll_ready_cluster_signature")
    context["pending_action"] = (any(bool(getattr(production_state, key, False)) for key in pending_fields)
                                 if production_state is not None else None)
    return context
