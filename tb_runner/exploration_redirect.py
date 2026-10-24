"""OFF-default, bounded Phase 6D3A redirect policy.

This module only validates a previously closed shadow frontier and accounts
for redirect budgets. It grants no action permit; the collection adapter must
rebuild current evidence and pass the existing Phase 4/5 gates immediately
before any targeted focus dispatch.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from tb_runner.traversal_reliability import (
    normalized_bounds,
    normalized as normalized_identity_text,
    redirect_identity_attributes,
)


MODE_ENV = "TB_EXPLORATION_REDIRECT_MODE"
MODES = {"OFF", "SHADOW", "ACTIVE"}
MAX_REDIRECTS_PER_STATE = 2
MAX_REDIRECTS_PER_RUN = 5
MAX_REDIRECT_FAILURE_STREAK = 2
REDIRECT_METRIC_NAMES = (
    "REDIRECT_RECOMMENDATION_COUNT", "REDIRECT_READY_COUNT",
    "REDIRECT_DISPATCH_ATTEMPT_COUNT", "REDIRECT_DISPATCH_COUNT",
    "REDIRECT_PREFLIGHT_BLOCK_COUNT",
    "REDIRECT_TARGET_REACHED_COUNT", "REDIRECT_NO_EFFECT_COUNT",
    "REDIRECT_WRONG_LANDING_COUNT", "REDIRECT_STALE_BLOCK_COUNT",
    "REDIRECT_PLANNER_BLOCK_COUNT", "REDIRECT_SAFETY_BLOCK_COUNT",
    "REDIRECT_BINDING_BLOCK_COUNT", "REDIRECT_SCOPE_EPOCH_BLOCK_COUNT",
    "REDIRECT_CONTROLLED_BUDGET_BLOCK_COUNT", "REDIRECT_BUDGET_BLOCK_COUNT",
    "REDIRECT_FALLBACK_COUNT", "REDIRECT_FALLBACK_ERROR_COUNT",
    "REDIRECT_DISABLED_AFTER_FAILURE_COUNT",
    "NEW_VISIT_AFTER_REDIRECT", "NEW_STATE_AFTER_REDIRECT",
    "SHADOW_RECOMMENDATION_COUNT", "SHADOW_READY_COUNT",
    "SHADOW_BLOCKED_COUNT", "SHADOW_UNKNOWN_COUNT",
    "SHADOW_PROOF_MATCH_COUNT", "SHADOW_PROOF_PARTIAL_COUNT",
    "SHADOW_PROOF_DISAGREEMENT_COUNT",
    "SHADOW_IDENTITY_EXACT_ONE_COUNT", "SHADOW_IDENTITY_NONE_COUNT",
    "SHADOW_IDENTITY_AMBIGUOUS_COUNT", "SHADOW_IDENTITY_UNKNOWN_COUNT",
    "SHADOW_PLANNER_ALLOWED_COUNT", "SHADOW_PLANNER_BLOCKED_COUNT",
    "SHADOW_PLANNER_UNKNOWN_COUNT", "SHADOW_SAFETY_ALLOWED_COUNT",
    "SHADOW_SAFETY_BLOCKED_COUNT", "SHADOW_SAFETY_UNKNOWN_COUNT",
    "SHADOW_LIFECYCLE_BLOCK_COUNT", "SHADOW_HELPER_BLOCK_COUNT",
    "SHADOW_OVERLAY_BLOCK_COUNT", "SHADOW_RECOVERY_BLOCK_COUNT",
    "SHADOW_TRANSITION_BLOCK_COUNT", "SHADOW_FRESHNESS_BLOCK_COUNT",
    "SHADOW_FALSE_READY_COUNT", "SHADOW_TRACE_DROPPED_COUNT",
)


def redirect_mode_from_environment(environ: Mapping[str, str] | None = None) -> str:
    """Return a strict opt-in mode. Missing and invalid values mean OFF."""
    if environ is None:
        import os
        environ = os.environ
    value = str(environ.get(MODE_ENV, "OFF") or "OFF").strip().upper()
    return value if value in MODES else "OFF"


def selected_redirect_hint(record: Any, *, scenario_id: str,
                           scenario_type: str, screen_context_mode: str = "",
                           require_execution_ready: bool = True) -> tuple[dict[str, Any] | None, str]:
    """Accept only a closed P0 plugin-content targeted-focus recommendation."""
    if str(scenario_type or "").strip().lower() != "content":
        return None, "CONTENT_SCENARIO_REQUIRED"
    if not str(scenario_id or "").strip().lower().endswith("_plugin"):
        return None, "PLUGIN_CONTENT_SCENARIO_REQUIRED"
    if screen_context_mode and str(screen_context_mode).strip().lower() != "new_screen":
        return None, "NEW_SCREEN_PLUGIN_SCOPE_REQUIRED"
    if not isinstance(record, Mapping):
        return None, "CLOSED_SHADOW_DECISION_UNAVAILABLE"
    if (record.get("decision_stage") != "POST_RESULT_N"
            or record.get("decision_evidence_usable") is not True
            or record.get("stale_status") != "NO"):
        return None, "CLOSED_CURRENT_DECISION_REQUIRED"
    if (type(record.get("decision_watermark")) is not int
            or record.get("decision_watermark") != record.get("step")):
        return None, "DECISION_WATERMARK_MISMATCH"
    if record.get("shadow_decision") != "REDIRECT_FRONTIER":
        return None, "SHADOW_REDIRECT_NOT_RECOMMENDED"
    if record.get("scope") != "CURRENT_STATE_CANDIDATE_FOCUS":
        return None, "CURRENT_PLUGIN_CONTENT_SCOPE_REQUIRED"
    production = record.get("production")
    if not isinstance(production, Mapping) or production.get("final_terminal") is True:
        return None, "PRODUCTION_TERMINAL_HAS_PRIORITY"
    selected = record.get("selected_frontier")
    if not isinstance(selected, Mapping):
        return None, "SELECTED_FRONTIER_UNAVAILABLE"
    if selected.get("priority_class") != "P0":
        return None, "P0_FRONTIER_REQUIRED"
    if selected.get("edge_type") != "TARGETED_FOCUS":
        return None, "TARGETED_FOCUS_ONLY"
    target = selected.get("target_identity")
    if not isinstance(target, Mapping) or not str(target.get("instance_id") or "").strip():
        return None, "STABLE_FRONTIER_TARGET_ID_REQUIRED"
    if require_execution_ready:
        ready_evidence = record.get("selected_frontier_execution_evidence")
        if (record.get("selected_frontier_execution_ready") is not True
                or not isinstance(ready_evidence, Mapping)
                or ready_evidence.get("selected_frontier_execution_ready") is not True
                or ready_evidence.get("status") != "READY"):
            return None, "SELECTED_FRONTIER_NOT_READY"
    state = record.get("state")
    if not isinstance(state, Mapping) or not str(state.get("state_id") or "").strip():
        return None, "RESOLVED_STATE_REQUIRED"
    if (str(selected.get("state_id") or "") != str(state.get("state_id") or "")
            or not str(selected.get("frontier_id") or "").strip()):
        return None, "SELECTED_FRONTIER_STATE_OR_ID_MISMATCH"
    alignment = record.get("observation_alignment")
    alignment = alignment if isinstance(alignment, Mapping) else {}
    return dict(
        decision_id=str(record.get("decision_id") or ""),
        decision_watermark=record.get("decision_watermark"),
        source_step=record.get("step"),
        state_id=str(state["state_id"]),
        frontier_id=str(selected.get("frontier_id") or ""),
        candidate_id=str(selected.get("candidate_id") or ""),
        edge_type="TARGETED_FOCUS",
        priority_class="P0",
        target_identity=dict(target),
        state_last_meaningful_progress_step=record.get("state_last_meaningful_progress_step"),
        run_last_meaningful_progress_step=record.get("run_last_meaningful_progress_step"),
        source_scope_id=str(alignment.get("scope_id") or ""),
        source_action_epoch=alignment.get("action_epoch"),
        source_observation_id=str(alignment.get("observation_id") or ""),
        source_observation_sequence=alignment.get("observation_sequence"),
        source_observation_epoch=alignment.get("observation_epoch"),
        source_context_revision=alignment.get("context_revision"),
    ), "REDIRECT_HINT_VALID"


@dataclass(frozen=True)
class IdentityBridgeResult:
    status: str
    candidate: dict[str, Any] | None = None
    reason: str = ""
    target_identity_source: str = ""
    candidate_identity_source: str = ""
    nested_identity_attributes_used: bool = False


def bridge_production_target_to_current_candidate(
        target_identity: Mapping[str, Any], inventory: Any) -> IdentityBridgeResult:
    """Bridge production scenario IDs to current state-scoped discovery IDs.

    The two ``instance_id`` values belong to different identity domains. This
    function intentionally never compares them. It filters to current focus
    execution candidates first, then matches stable resource/bounds/class data.
    The later Phase 4 resolver still binds the unique result to the current raw
    node immediately before dispatch.
    """
    target_identity = target_identity if isinstance(target_identity, Mapping) else {}
    if target_identity.get("identity_domain") != "production_scenario_scope_v1":
        return IdentityBridgeResult("UNKNOWN", reason="PRODUCTION_IDENTITY_DOMAIN_UNAVAILABLE")
    attrs, target_source, target_problem = redirect_identity_attributes(target_identity)
    if target_problem:
        return IdentityBridgeResult("UNKNOWN", reason=target_problem,
                                    target_identity_source=target_source,
                                    nested_identity_attributes_used=(
                                        target_source == "NESTED_IDENTITY_ATTRIBUTES"))
    resource_id = attrs.get("resource_id", "")
    bounds = attrs.get("bounds", "")
    class_name = attrs.get("class_name", "")
    if not resource_id or not bounds:
        return IdentityBridgeResult("UNKNOWN", reason="POSITIONAL_IDENTITY_ATTRIBUTES_INCOMPLETE",
                                    target_identity_source=target_source,
                                    nested_identity_attributes_used=(
                                        target_source == "NESTED_IDENTITY_ATTRIBUTES"))
    if not isinstance(inventory, (list, tuple)):
        return IdentityBridgeResult("UNKNOWN", reason="CURRENT_INVENTORY_UNAVAILABLE",
                                    target_identity_source=target_source,
                                    nested_identity_attributes_used=(
                                        target_source == "NESTED_IDENTITY_ATTRIBUTES"))
    matches = []
    insufficient_candidates = 0
    incomplete_source = ""
    for candidate in inventory:
        if not isinstance(candidate, Mapping):
            continue
        # Discovery snapshots may expose the same node as separate CLICK and
        # FOCUS_TARGET candidates. A P0 redirect is a targeted focus edge, so
        # only compare equivalent focus candidates. Cached frontier inventories
        # carry edge_type instead of action_kind.
        action_kind = str(candidate.get("action_kind") or candidate.get("action_type") or "").strip().upper()
        edge_type = str(candidate.get("edge_type") or "").strip().upper()
        if action_kind or edge_type:
            if action_kind and action_kind not in {"FOCUS_TARGET", "TARGETED_FOCUS"}:
                continue
            if edge_type and edge_type != "TARGETED_FOCUS":
                continue
        else:
            # Unknown candidate semantics cannot prove this focus target is
            # unique among same-instance click/activation alternatives.
            continue
        identity = candidate.get("target_identity")
        identity = identity if isinstance(identity, Mapping) else {}
        domain = identity.get("identity_domain")
        if domain not in {
                "discovery_state_scope_v1", "production_scenario_scope_v1"}:
            continue
        candidate_attrs, candidate_source, candidate_problem = redirect_identity_attributes(identity)
        if candidate_problem:
            return IdentityBridgeResult(
                "UNKNOWN", reason="CURRENT_" + candidate_problem,
                target_identity_source=target_source,
                candidate_identity_source=candidate_source,
                nested_identity_attributes_used=(
                    target_source == "NESTED_IDENTITY_ATTRIBUTES"
                    or candidate_source in {"NESTED_IDENTITY_ATTRIBUTES",
                                            "CONFLICTING_NESTED_AND_FLAT"}),
            )
        candidate_rid = candidate_attrs.get("resource_id", "")
        candidate_bounds = candidate_attrs.get("bounds", "")
        candidate_class = candidate_attrs.get("class_name", "")
        # A known disagreement proves this candidate is not the requested
        # target. Missing fields do not: a partially identified FOCUS node
        # sharing either stable anchor remains a possible competitor.
        if candidate_rid and candidate_rid != resource_id:
            continue
        if candidate_bounds and candidate_bounds != bounds:
            continue
        if class_name and candidate_class and candidate_class != class_name:
            continue
        shares_anchor = (candidate_rid == resource_id or candidate_bounds == bounds)
        if not shares_anchor:
            continue
        if not candidate_rid or not candidate_bounds or not candidate_class or not class_name:
            insufficient_candidates += 1
            incomplete_source = candidate_source
            continue
        matches.append((dict(candidate), candidate_source))
    nested_used = (target_source == "NESTED_IDENTITY_ATTRIBUTES"
                   or any(source == "NESTED_IDENTITY_ATTRIBUTES" for _, source in matches))
    if insufficient_candidates:
        return IdentityBridgeResult(
            "UNKNOWN", reason="CURRENT_IDENTITY_EVIDENCE_INCOMPLETE",
            target_identity_source=target_source,
            candidate_identity_source=incomplete_source,
            nested_identity_attributes_used=(nested_used or
                incomplete_source in {"NESTED_IDENTITY_ATTRIBUTES",
                                      "CONFLICTING_NESTED_AND_FLAT"}),
        )
    if not matches:
        return IdentityBridgeResult("NONE", reason="CURRENT_TARGET_ABSENT",
                                    target_identity_source=target_source,
                                    nested_identity_attributes_used=(
                                        target_source == "NESTED_IDENTITY_ATTRIBUTES"))
    if len(matches) != 1:
        return IdentityBridgeResult("AMBIGUOUS", reason="CURRENT_TARGET_AMBIGUOUS",
                                    target_identity_source=target_source,
                                    candidate_identity_source=matches[0][1],
                                    nested_identity_attributes_used=nested_used)
    candidate, candidate_source = matches[0]
    return IdentityBridgeResult(
        "EXACT_ONE", candidate=candidate, reason="CURRENT_TARGET_EXACT_ONE",
        target_identity_source=target_source,
        candidate_identity_source=candidate_source,
        nested_identity_attributes_used=nested_used,
    )


def evaluate_shadow_readiness_bundle(*, record: Any, scenario_id: str,
                                     scenario_type: str, screen_context_mode: str,
                                     run_id: str, frame: Any, planner_input: Any,
                                     raw: Mapping[str, Any], authority_evidence: Any,
                                     current_input: Any, actions_used: int = 0,
                                     degraded: bool = False, action_limit: int = 5,
                                     evaluation_duration_ms: float = 0.0) -> dict[str, Any]:
    """Build and evaluate one read-only RF1 bundle for the production SHADOW hook.

    This adapter only interprets evidence already collected by the production
    path.  It does not query a device, issue a Phase 5 permit, or dispatch.
    The legacy Phase 6 execution-ready flag is deliberately not a readiness
    input here; the common evaluator is the sole SHADOW readiness authority.
    """
    from dataclasses import asdict
    from tb_runner.redirect_evidence import (
        CanonicalTargetIdentity, ProductionEvidenceFrame,
        ProductionRedirectProofProvider, RedirectEvidenceBundle, TargetProofSet,
        adapt_production_frontier_identity, evaluate_redirect_readiness,
        proof_provenance_for, _evidence_document,
    )

    hint, hint_reason = selected_redirect_hint(
        record, scenario_id=scenario_id, scenario_type=scenario_type,
        screen_context_mode=screen_context_mode, require_execution_ready=False)
    provider_result = None
    proof_set = TargetProofSet(provenance=proof_provenance_for(frame))
    if isinstance(frame, ProductionEvidenceFrame) and planner_input is not None and isinstance(raw, Mapping):
        provider_result = ProductionRedirectProofProvider().build_target_proof_set(
            frame, planner_input, raw, authority_evidence=authority_evidence,
            current_input=current_input, actions_used=actions_used,
            degraded=degraded, action_limit=action_limit)
        proof_set = provider_result.proof_set

    selected = record.get("selected_frontier") if isinstance(record, Mapping) else None
    selected = selected if isinstance(selected, Mapping) else {}
    selected_target = selected.get("target_identity") if isinstance(selected.get("target_identity"), Mapping) else {}
    if hint is not None:
        frontier_target = adapt_production_frontier_identity(selected_target)
        recommendation = {
            "frontier_id": str(hint.get("frontier_id") or ""),
            "edge_type": "TARGETED_FOCUS",
            "state_id": str(hint.get("state_id") or ""),
            "decision_watermark": hint.get("decision_watermark"),
            "substate": list(frame.substate) if isinstance(frame, ProductionEvidenceFrame) else [],
            "target_identity": dict(selected_target),
        }
        frontier_id = str(hint.get("frontier_id") or "")
        frontier_state_id = str(hint.get("state_id") or "")
        decision_id = str(hint.get("decision_id") or "")
        watermark = hint.get("decision_watermark")
    else:
        frontier_target = CanonicalTargetIdentity()
        recommendation = {}
        frontier_id = frontier_state_id = ""
        decision_id = str(record.get("decision_id") or "") if isinstance(record, Mapping) else ""
        watermark = record.get("decision_watermark") if isinstance(record, Mapping) else None

    if not isinstance(frame, ProductionEvidenceFrame):
        frame = ProductionEvidenceFrame(run_id=str(run_id or ""), decision_id=decision_id,
                                        decision_watermark=watermark, evidence_current=False)
        proof_set = TargetProofSet(provenance=proof_provenance_for(frame))
    bundle = RedirectEvidenceBundle(
        run_id=frame.run_id, decision_id=frame.decision_id,
        frontier_id=frontier_id, frontier_state_id=frontier_state_id,
        frontier_action="TARGETED_FOCUS" if hint is not None else "",
        frame=frame, frontier_target=frontier_target, proof_set=proof_set,
        frontier_recommendation=recommendation,
    )
    assessment = evaluate_redirect_readiness(bundle)
    reason_codes = list(assessment.reason_codes)
    proof_disagreement = any("DISAGREEMENT" in reason or "PROOF_TARGET" in reason
                             or "PRODUCTION_TARGET" in reason for reason in reason_codes)
    proof_match = ("DISAGREEMENT" if proof_disagreement else
                   "MATCH" if proof_set.proof_complete and proof_set.identity_bridge.status == "EXACT_ONE"
                   else "PARTIAL")
    lifecycle_evidence = _evidence_document(frame.lifecycle_evidence)
    conditions = {
        "lifecycle_status": frame.lifecycle_status,
        "lifecycle_evidence": lifecycle_evidence,
        "decision_alignment": _evidence_document(frame.decision_alignment),
        "helper_status": frame.helper_status,
        "helper_evidence": _evidence_document(frame.helper_evidence),
        "overlay_status": frame.overlay_status,
        "recovery_status": frame.recovery_status,
        "transition_status": frame.transition_status,
        "evidence_current": frame.evidence_current,
    }
    known_invalid = (
        frame.evidence_current is not True
        or any(str(conditions[key] or "").upper() in {
            "BLOCKED", "RESTART", "RESTARTED", "UNSETTLED", "UNAVAILABLE", "NOT_READY",
            "FAILED", "MISMATCH", "PENDING", "ACTIVE", "PRESENT_BLOCKING",
        } for key in ("lifecycle_status", "helper_status", "overlay_status",
                      "recovery_status", "transition_status"))
        or not proof_set.proof_complete or proof_set.identity_bridge.status != "EXACT_ONE"
        or proof_disagreement
    )
    false_ready_reasons = (["COMMON_EVALUATOR_READY_WITH_INVALID_EVIDENCE"]
                           if assessment.status == "READY" and known_invalid else [])
    frame_doc = {
        "run_id": frame.run_id, "decision_id": frame.decision_id,
        "decision_watermark": frame.decision_watermark,
        "observation_id": frame.observation_id,
        "observation_sequence": frame.observation_sequence,
        "scope_id": frame.scope_id, "action_epoch": frame.action_epoch,
        "observation_epoch": frame.observation_epoch,
        "context_revision": frame.context_revision,
        "evidence_current": frame.evidence_current,
        "inventory_complete": frame.inventory_complete,
        "decision_alignment": _evidence_document(frame.decision_alignment),
        "graph_state_ref": asdict(frame.graph_state_ref) if frame.graph_state_ref else None,
        "discovery_state_ref": asdict(frame.discovery_state_ref) if frame.discovery_state_ref else None,
        "plugin_context": dict(frame.plugin_context) if isinstance(frame.plugin_context, Mapping)
                          else frame.plugin_context,
        "lifecycle_evidence": lifecycle_evidence,
        "substate": list(frame.substate) if isinstance(frame.substate, tuple) else frame.substate,
    }
    proof_doc = {
        "build_status": getattr(provider_result, "build_status", "UNKNOWN"),
        "build_reason": getattr(provider_result, "reason", ""),
        "planner_status": proof_set.planner_status,
        "phase4_gate_status": proof_set.phase4_gate_status,
        "safety_assessment_status": proof_set.safety_assessment_status,
        "binding_status": proof_set.binding_status,
        "presence_status": proof_set.presence_status,
        "proof_complete": proof_set.proof_complete,
        "target_identity": asdict(proof_set.target_identity),
        "production_target_identity": asdict(proof_set.production_target_identity),
        "proof_refs": dict(proof_set.proof_refs),
        "source_refs": dict(proof_set.source_refs),
        "provenance": asdict(proof_set.provenance),
        "reasons": list(proof_set.reasons),
    }
    identity_doc = asdict(proof_set.identity_bridge)
    event_id = "rf2-readiness:" + ":".join((str(run_id or ""), decision_id,
                                              frame.observation_id or "missing-observation"))
    trace_event = {
        "schema_version": "redirect-readiness-trace-v1",
        "event_id": event_id, "event_type": "SHADOW_READINESS_EVALUATED",
        "run_id": str(run_id or frame.run_id), "scenario_id": str(scenario_id or ""),
        "decision_id": decision_id, "decision_watermark": watermark,
        "observation_id": frame.observation_id,
        "observation_sequence": frame.observation_sequence,
        "scope_id": frame.scope_id, "action_epoch": frame.action_epoch,
        "observation_epoch": frame.observation_epoch,
        "context_revision": frame.context_revision,
        "frontier": {
            "frontier_id": frontier_id, "state_id": frontier_state_id,
            "priority_class": selected.get("priority_class"),
            "action_type": selected.get("edge_type"),
            "target_identity": dict(selected_target),
            "substate": list(frame.substate) if isinstance(frame.substate, tuple) else frame.substate,
        },
        "frame": frame_doc, "proof": proof_doc,
        "identity_bridge": identity_doc,
        "conditions": conditions,
        "readiness_status": assessment.status,
        "reason_codes": reason_codes,
        "evaluation_duration_ms": round(float(evaluation_duration_ms), 3),
        "execution_authority": assessment.execution_authority,
        "phase5_permit_issued": assessment.phase5_permit_issued,
        "dispatch_count": 0, "visit_credit": 0,
        "hint_status": hint_reason,
        "false_ready_reasons": false_ready_reasons,
    }
    return {
        "schema_version": "phase6d3a-redirect-readiness-rf2-v1",
        "readiness_schema": "redirect-readiness-rf2-v1",
        "mode": "SHADOW", "run_id": trace_event["run_id"],
        "scenario_id": str(scenario_id or ""),
        "decision_id": decision_id, "decision_watermark": watermark,
        "observation_id": frame.observation_id,
        "observation_sequence": frame.observation_sequence,
        "scope_id": frame.scope_id, "action_epoch": frame.action_epoch,
        "observation_epoch": frame.observation_epoch,
        "context_revision": frame.context_revision,
        "frontier_id": frontier_id, "state_id": frontier_state_id,
        "target_identity": dict(selected_target),
        "recommendation": hint is not None,
        "readiness_status": assessment.status, "status": assessment.status,
        "ready": assessment.status == "READY",
        "reason": ";".join(reason_codes) if reason_codes else "COMMON_EVALUATOR_READY",
        "reason_codes": reason_codes,
        "proof_match": proof_match, "proof": proof_doc,
        "identity_bridge": identity_doc, "conditions": conditions,
        "readiness_bundle_id": assessment.bundle_id,
        "readiness_evidence_current": assessment.evidence_current,
        "execution_authority": assessment.execution_authority,
        "phase5_permit_issued": assessment.phase5_permit_issued,
        "dispatch_count": 0, "dispatch_attempted": False,
        "visit_credit": 0, "attempt_credit": 0,
        "evaluation_duration_ms": round(float(evaluation_duration_ms), 3),
        "false_ready_reasons": false_ready_reasons,
        "readiness_trace": trace_event,
        "phase5_permit_separate": True,
    }


def unique_current_candidate(target_identity: Mapping[str, Any],
                             inventory: Any) -> tuple[dict[str, Any] | None, str]:
    """Compatibility-shaped wrapper around the explicit identity bridge."""
    result = bridge_production_target_to_current_candidate(target_identity, inventory)
    return result.candidate, result.status


def dispatch_provenance_current(*, record: Mapping[str, Any], hint: Mapping[str, Any],
                                clock: Any, current_observation: Mapping[str, Any],
                                current_state_id: str, current_substate_ref: str,
                                plugin_context_current: bool,
                                target_unique: bool, planner_agrees: bool,
                                phase4_allowed: bool, lifecycle_clear: bool,
                                helper_ready: bool, overlay_clear: bool,
                                recovery_clear: bool) -> tuple[bool, str]:
    """Fail-closed Phase 6 provenance check used immediately before dispatch.

    Phase 5 still performs its independent FOCUS permit/policy check at the
    native boundary. This validator only proves current decision provenance.
    """
    if not isinstance(record, Mapping) or not isinstance(hint, Mapping):
        return False, "CLOSED_DECISION_UNAVAILABLE"
    if (record.get("decision_id") != hint.get("decision_id")
            or record.get("decision_watermark") != hint.get("decision_watermark")
            or record.get("decision_stage") != "POST_RESULT_N"
            or record.get("decision_evidence_usable") is not True
            or record.get("stale_status") != "NO"):
        return False, "DECISION_WATERMARK_OR_CLOSED_STATUS_STALE"
    ready = record.get("selected_frontier_execution_evidence")
    if (record.get("selected_frontier_execution_ready") is not True
            or not isinstance(ready, Mapping)
            or ready.get("selected_frontier_execution_ready") is not True
            or ready.get("status") != "READY"):
        return False, "SELECTED_FRONTIER_READY_REQUIRED"
    selected = record.get("selected_frontier")
    selected_target = selected.get("target_identity") if isinstance(selected, Mapping) else None
    if (not isinstance(selected_target, Mapping)
            or selected_target.get("instance_id") != (hint.get("target_identity") or {}).get("instance_id")
            or ready.get("frontier_id") != hint.get("frontier_id")
            or ready.get("target_identity") != selected_target):
        return False, "SELECTED_FRONTIER_IDENTITY_CHANGED"
    alignment = record.get("observation_alignment")
    if not isinstance(alignment, Mapping) or clock is None:
        return False, "EVIDENCE_CLOCK_OR_ALIGNMENT_UNAVAILABLE"
    if not clock.current(dict(current_observation)):
        return False, "CURRENT_OBSERVATION_STALE"
    for alignment_key, hint_key in (
        ("scope_id", "source_scope_id"), ("observation_id", "source_observation_id"),
        ("observation_sequence", "source_observation_sequence"),
        ("observation_epoch", "source_observation_epoch"),
        ("context_revision", "source_context_revision"),
        ("action_epoch", "source_action_epoch"),
    ):
        if alignment.get(alignment_key) != hint.get(hint_key):
            return False, "SOURCE_" + alignment_key.upper() + "_MISMATCH"
    if (alignment.get("scope_id") != current_observation.get("scope_id")
            or alignment.get("action_epoch") != current_observation.get("action_epoch")
            or alignment.get("context_revision") != current_observation.get("context_revision")):
        return False, "CURRENT_SCOPE_EPOCH_OR_CONTEXT_REVISION_MISMATCH"
    if (current_state_id != hint.get("state_id")
            or current_substate_ref != ready.get("substate_ref")
            or ready.get("state_id") != hint.get("state_id")):
        return False, "STATE_OR_SUBSTATE_CHANGED"
    if plugin_context_current is not True:
        return False, "PLUGIN_CONTEXT_CHANGED_OR_UNVERIFIED"
    for valid, reason in (
        (target_unique, "TARGET_NOT_UNIQUELY_RESOLVABLE"),
        (planner_agrees, "PLANNER_DISAGREEMENT"),
        (phase4_allowed, "PHASE4_GATE_BLOCKED"),
        (lifecycle_clear, "LIFECYCLE_UNSTABLE"),
        (helper_ready, "HELPER_NOT_READY"),
        (overlay_clear, "OVERLAY_NOT_CLEARED"),
        (recovery_clear, "RECOVERY_OR_TRANSITION_PENDING"),
    ):
        if valid is not True:
            return False, reason
    return True, "FINAL_PROVENANCE_CURRENT"


def meaningful_condition_key(hint: Mapping[str, Any]) -> tuple[Any, ...]:
    """Exclude request/snapshot IDs so recapture alone cannot replenish budget."""
    return (
        str(hint.get("state_id") or ""),
        str(hint.get("frontier_id") or ""),
        hint.get("state_last_meaningful_progress_step"),
        hint.get("run_last_meaningful_progress_step"),
    )


@dataclass
class RedirectBudget:
    """Per-run action budget; recovery retains its separate production budget."""

    max_per_state: int = MAX_REDIRECTS_PER_STATE
    max_per_run: int = MAX_REDIRECTS_PER_RUN
    max_per_condition: int = 1
    failure_limit: int = MAX_REDIRECT_FAILURE_STREAK
    redirects_used: int = 0
    state_counts: Counter[str] = field(default_factory=Counter)
    condition_counts: Counter[tuple[Any, ...]] = field(default_factory=Counter)
    consecutive_failures: int = 0
    active_disabled: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)

    def available(self, hint: Mapping[str, Any], *, run_limit: int | None = None) -> tuple[bool, str]:
        state_id = str(hint.get("state_id") or "")
        frontier_id = str(hint.get("frontier_id") or "")
        condition = meaningful_condition_key(hint)
        effective_run_limit = self.max_per_run
        if type(run_limit) is int and run_limit > 0:
            effective_run_limit = min(effective_run_limit, run_limit)
        if self.active_disabled:
            return False, "ACTIVE_DISABLED_AFTER_FAILURE_STREAK"
        if not state_id or not frontier_id:
            return False, "STATE_OR_FRONTIER_ID_REQUIRED"
        if self.redirects_used >= effective_run_limit:
            return False, "RUN_REDIRECT_BUDGET_EXHAUSTED"
        if self.state_counts[state_id] >= self.max_per_state:
            return False, "STATE_REDIRECT_BUDGET_EXHAUSTED"
        if self.condition_counts[condition] >= self.max_per_condition:
            return False, "SAME_FRONTIER_CONDITION_ALREADY_USED"
        return True, "REDIRECT_BUDGET_AVAILABLE"

    def dispatch_attempt(self, hint: Mapping[str, Any], *, run_limit: int | None = None) -> tuple[bool, str]:
        """Consume an execution slot only at the pre-dispatch attempt boundary."""
        allowed, reason = self.available(hint, run_limit=run_limit)
        if not allowed:
            return False, reason
        state_id = str(hint.get("state_id") or "")
        self.redirects_used += 1
        self.state_counts[state_id] += 1
        self.condition_counts[meaningful_condition_key(hint)] += 1
        return True, "REDIRECT_DISPATCH_ATTEMPT_RECORDED"

    # Kept as a source-compatible alias; unlike the old reserve this is a
    # read-only availability check and does not spend an execution attempt.
    def reserve(self, hint: Mapping[str, Any], *, run_limit: int | None = None) -> tuple[bool, str]:
        return self.available(hint, run_limit=run_limit)

    def outcome(self, *, success: bool, hint: Mapping[str, Any], reason: str = "") -> None:
        if success:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.failure_limit:
                self.active_disabled = True
        if len(self.events) < 256:
            self.events.append({
                "event": "REDIRECT_OUTCOME",
                "state_id": hint.get("state_id"),
                "frontier_id": hint.get("frontier_id"),
                "decision_id": hint.get("decision_id"),
                "success": bool(success),
                "reason": str(reason or ("REDIRECT_RECONCILED" if success else "REDIRECT_FAILED")),
                "redirects_used": self.redirects_used,
                "state_redirects_used": self.state_counts[str(hint.get("state_id") or "")],
                "consecutive_failures": self.consecutive_failures,
                "active_disabled": self.active_disabled,
            })


@dataclass
class RedirectMetrics:
    """Bounded aggregate counters and timing samples for future SHADOW review."""

    counters: Counter[str] = field(default_factory=lambda: Counter({name: 0 for name in REDIRECT_METRIC_NAMES}))
    evaluation_ms: list[float] = field(default_factory=list)

    def observe(self, event: Mapping[str, Any]) -> None:
        if event.get("recommendation") is True:
            self.counters["REDIRECT_RECOMMENDATION_COUNT"] += 1
        if event.get("ready") is True:
            self.counters["REDIRECT_READY_COUNT"] += 1
        if event.get("dispatch_attempted") is True:
            self.counters["REDIRECT_DISPATCH_ATTEMPT_COUNT"] += 1
        if int(event.get("dispatch_count", 0) or 0) > 0:
            self.counters["REDIRECT_DISPATCH_COUNT"] += 1
        if event.get("fallback_used") is True:
            self.counters["REDIRECT_FALLBACK_COUNT"] += 1
        if event.get("fallback_error"):
            self.counters["REDIRECT_FALLBACK_ERROR_COUNT"] += 1
        if event.get("mode") == "SHADOW" and event.get("readiness_schema") == "redirect-readiness-rf2-v1":
            if event.get("recommendation") is True:
                self.counters["SHADOW_RECOMMENDATION_COUNT"] += 1
            readiness = str(event.get("readiness_status") or "UNKNOWN").upper()
            if readiness in {"READY", "BLOCKED", "UNKNOWN"}:
                self.counters["SHADOW_" + readiness + "_COUNT"] += 1
            proof = event.get("proof") if isinstance(event.get("proof"), Mapping) else {}
            bridge = event.get("identity_bridge") if isinstance(event.get("identity_bridge"), Mapping) else {}
            planner = str(proof.get("planner_status") or "UNKNOWN").upper()
            safety = str(proof.get("safety_assessment_status") or "UNKNOWN").upper()
            identity = str(bridge.get("status") or "UNKNOWN").upper()
            for value, prefix, allowed, blocked in (
                (planner, "SHADOW_PLANNER_", "ELIGIBLE", {"BLOCKED", "DENIED", "INELIGIBLE", "UNSUPPORTED"}),
                (safety, "SHADOW_SAFETY_", "ALLOWED", {"BLOCKED", "DENIED", "RISKY", "FORBIDDEN"}),
            ):
                suffix = "ALLOWED" if value == allowed else "BLOCKED" if value in blocked else "UNKNOWN"
                self.counters[prefix + suffix + "_COUNT"] += 1
            identity_counter = {
                "EXACT_ONE": "SHADOW_IDENTITY_EXACT_ONE_COUNT",
                "NONE": "SHADOW_IDENTITY_NONE_COUNT",
                "AMBIGUOUS": "SHADOW_IDENTITY_AMBIGUOUS_COUNT",
            }.get(identity, "SHADOW_IDENTITY_UNKNOWN_COUNT")
            self.counters[identity_counter] += 1
            proof_match = str(event.get("proof_match") or "PARTIAL").upper()
            proof_counter = {
                "MATCH": "SHADOW_PROOF_MATCH_COUNT",
                "DISAGREEMENT": "SHADOW_PROOF_DISAGREEMENT_COUNT",
            }.get(proof_match, "SHADOW_PROOF_PARTIAL_COUNT")
            self.counters[proof_counter] += 1
            conditions = event.get("conditions") if isinstance(event.get("conditions"), Mapping) else {}
            for key, counter in (
                ("lifecycle_status", "SHADOW_LIFECYCLE_BLOCK_COUNT"),
                ("helper_status", "SHADOW_HELPER_BLOCK_COUNT"),
                ("overlay_status", "SHADOW_OVERLAY_BLOCK_COUNT"),
                ("recovery_status", "SHADOW_RECOVERY_BLOCK_COUNT"),
                ("transition_status", "SHADOW_TRANSITION_BLOCK_COUNT"),
            ):
                if str(conditions.get(key) or "").upper() in {
                    "BLOCKED", "RESTART", "RESTARTED", "UNSETTLED", "UNAVAILABLE",
                    "NOT_READY", "FAILED", "MISMATCH", "PENDING", "ACTIVE", "PRESENT_BLOCKING",
                }:
                    self.counters[counter] += 1
            reasons = event.get("reason_codes") or ()
            if any(any(token in str(reason).upper() for token in ("STALE", "CURRENT", "FRESHNESS"))
                   for reason in reasons):
                self.counters["SHADOW_FRESHNESS_BLOCK_COUNT"] += 1
            if event.get("false_ready_reasons"):
                self.counters["SHADOW_FALSE_READY_COUNT"] += 1
        block = str(event.get("block_category") or "")
        block_map = {
            "STALE_BLOCK": "REDIRECT_STALE_BLOCK_COUNT",
            "PLANNER_BLOCK": "REDIRECT_PLANNER_BLOCK_COUNT",
            "SAFETY_BLOCK": "REDIRECT_SAFETY_BLOCK_COUNT",
            "PREFLIGHT_BLOCK": "REDIRECT_PREFLIGHT_BLOCK_COUNT",
            "BINDING_BLOCK": "REDIRECT_BINDING_BLOCK_COUNT",
            "SCOPE_EPOCH_BLOCK": "REDIRECT_SCOPE_EPOCH_BLOCK_COUNT",
            "CONTROLLED_BUDGET_BLOCK": "REDIRECT_CONTROLLED_BUDGET_BLOCK_COUNT",
            "REDIRECT_BUDGET_BLOCK": "REDIRECT_BUDGET_BLOCK_COUNT",
        }
        if block in block_map:
            self.counters[block_map[block]] += 1
        latency = event.get("evaluation_duration_ms")
        if isinstance(latency, (int, float)) and 0 <= float(latency) < 60_000:
            if len(self.evaluation_ms) < 2048:
                self.evaluation_ms.append(float(latency))

    def reconciled(self, *, reached: bool, no_effect: bool = False,
                   wrong_landing: bool = False, new_visit: bool = False,
                   new_state: bool = False) -> None:
        if reached:
            self.counters["REDIRECT_TARGET_REACHED_COUNT"] += 1
        if no_effect:
            self.counters["REDIRECT_NO_EFFECT_COUNT"] += 1
        if wrong_landing:
            self.counters["REDIRECT_WRONG_LANDING_COUNT"] += 1
        if new_visit:
            self.counters["NEW_VISIT_AFTER_REDIRECT"] += 1
        if new_state:
            self.counters["NEW_STATE_AFTER_REDIRECT"] += 1

    def latency_summary(self) -> dict[str, float | int | None]:
        if not self.evaluation_ms:
            return {"count": 0, "p50_ms": None, "p95_ms": None}
        values = sorted(self.evaluation_ms)
        def percentile(q: float) -> float:
            index = max(0, min(len(values) - 1, int((len(values) - 1) * q + 0.5)))
            return round(values[index], 3)
        return {"count": len(values), "p50_ms": percentile(.50), "p95_ms": percentile(.95)}


@dataclass
class ExplorationRedirectController:
    """Feature gate and bounded run state for Phase 6D3A.

    Owns only redirect mode, redirect budgets/history, failure streaks, and
    redirect diagnostics. It does not own Phase 4 controlled budget, Phase 5
    safety/permits, target binding, focus or visit reconciliation, new-state
    progress, or production termination.
    """

    mode: str = "OFF"
    graph_mode: str = "OFF"
    budget: RedirectBudget = field(default_factory=RedirectBudget)
    metrics: RedirectMetrics = field(default_factory=RedirectMetrics)
    events: list[dict[str, Any]] = field(default_factory=list)
    run_id: str = ""
    dispatch_operations: set[str] = field(default_factory=set)
    reconciled_operations: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.mode = str(self.mode or "OFF").strip().upper()
        if self.mode not in MODES:
            self.mode = "OFF"
        self.graph_mode = str(self.graph_mode or "OFF").strip().upper()

    @property
    def effective_mode(self) -> str:
        if self.mode == "OFF" or self.graph_mode != "SHADOW":
            return "OFF"
        return self.mode

    def record(self, event: Mapping[str, Any]) -> None:
        record = dict(event)
        started = record.pop("_evaluation_started", None)
        if isinstance(started, (int, float)):
            import time
            duration_ms = round(max(0.0, (time.perf_counter() - started) * 1000.0), 3)
            record["evaluation_duration_ms"] = duration_ms
            if isinstance(event, dict):
                event["evaluation_duration_ms"] = duration_ms
        self.metrics.observe(record)
        if len(self.events) < 512:
            self.events.append(record)
        elif record.get("readiness_schema") == "redirect-readiness-rf2-v1":
            self.metrics.counters["SHADOW_TRACE_DROPPED_COUNT"] += 1

    def reset_for_run(self, run_id: str) -> None:
        """Reset only 6D3A-owned state at the authoritative run boundary."""
        self.budget = RedirectBudget(
            max_per_state=self.budget.max_per_state,
            max_per_run=self.budget.max_per_run,
            max_per_condition=self.budget.max_per_condition,
            failure_limit=self.budget.failure_limit,
        )
        self.metrics = RedirectMetrics()
        self.events = []
        self.run_id = str(run_id or "")
        self.dispatch_operations.clear()
        self.reconciled_operations.clear()

    def account_dispatch(self, evidence, *, hint, run_limit=None) -> bool:
        """Observe typed Phase4 truth; own only redirect accounting, never permits."""
        from talkback_lib.native_dispatch_evidence import NativeDispatchEvidence, DISPATCHED, UNKNOWN
        if not isinstance(evidence, NativeDispatchEvidence):
            self.budget.active_disabled = True
            return False
        if evidence.dispatch_status == UNKNOWN:
            self.budget.active_disabled = True
            return False
        if evidence.dispatch_status != DISPATCHED:
            return False
        operation = evidence.operation_id
        if operation in self.dispatch_operations:
            return False
        allowed, reason = self.budget.dispatch_attempt(hint, run_limit=run_limit)
        if not allowed:
            self.budget.active_disabled = True
            raise RuntimeError("REDIRECT_ACCOUNTING_INVARIANT: " + reason)
        self.dispatch_operations.add(operation)
        return True

    def reconciled(self, *, hint: Mapping[str, Any], reached: bool, no_effect: bool,
                   wrong_landing: bool, new_visit: bool, new_state: bool,
                   reason: str, operation_id: str = "") -> None:
        if operation_id:
            if (operation_id not in self.dispatch_operations
                    or operation_id in self.reconciled_operations):
                return
            self.reconciled_operations.add(operation_id)
        attempted = int(self.budget.condition_counts[meaningful_condition_key(hint)] > 0)
        if not attempted:
            return
        was_disabled = self.budget.active_disabled
        self.metrics.reconciled(reached=reached, no_effect=no_effect,
                                wrong_landing=wrong_landing, new_visit=new_visit,
                                # State novelty is recorded separately from a
                                # finalized Phase6 progress event only.
                                new_state=False)
        self.budget.outcome(success=reached, hint=hint, reason=reason)
        if not was_disabled and self.budget.active_disabled:
            self.metrics.counters["REDIRECT_DISABLED_AFTER_FAILURE_COUNT"] += 1
        if len(self.events) < 512:
            self.events.append({
                "event": "POST_RESULT_RECONCILIATION",
                "decision_id": hint.get("decision_id"),
                "state_id": hint.get("state_id"),
                "frontier_id": hint.get("frontier_id"),
                "target_reached": bool(reached), "no_effect": bool(no_effect),
                "wrong_landing": bool(wrong_landing), "new_visit": bool(new_visit),
                "new_state": bool(new_state), "reason": str(reason or ""),
                "consecutive_failures": self.budget.consecutive_failures,
                "active_disabled": self.budget.active_disabled,
            })

    def record_verified_new_state(self, *, is_new: bool, state_id: str | None,
                                  evidence: str) -> None:
        """Record novelty supplied by the closed Phase 6 progress evaluator."""
        if is_new is True and state_id and evidence == "NEW_RESOLVED_STATE":
            self.metrics.counters["NEW_STATE_AFTER_REDIRECT"] += 1
            if len(self.events) < 512:
                self.events.append({"event": "VERIFIED_NEW_STATE_AFTER_REDIRECT",
                                    "state_id": state_id, "evidence": evidence})
