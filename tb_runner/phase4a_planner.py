"""Pure Phase 4A shadow decisions. No client, executor, clock or visit ledger.

Discovery IDs identify action observations; production instance-v1 identities
account for attempts/visits. History is an immutable projection of production
evidence. Recommendations never advance either ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json
from tb_runner.discovery_candidates import DiscoverySnapshot
from tb_runner.traversal_reliability import instance_id, normalized_bounds
from tb_runner.utils import parse_bounds_str


@dataclass(frozen=True)
class ProductionHistory:
    scenario_id: str
    known: bool = False
    attempts: tuple[tuple[str, int], ...] = ()
    visits: tuple[tuple[str, int], ...] = ()
    recent_attempts: tuple[str, ...] = ()
    last_attempt_steps: tuple[tuple[str, int], ...] = ()
    stale_ids: tuple[str, ...] = ()
    allowed_instance_ids: tuple[str, ...] | None = None
    source: str = "UNAVAILABLE"


@dataclass(frozen=True)
class PlannerInput:
    snapshot: DiscoverySnapshot
    context_status: str
    history: ProductionHistory
    scroll_exhausted: bool = False
    scroll_blocked: bool = False
    pending_transition: bool = False
    last_movement: str = "UNKNOWN"
    focus_plateau: bool = False
    # Only an explicitly verified exploration signal can promote a revisit.
    transition_value_ids: tuple[str, ...] = ()
    safety_blocked: bool = False


@dataclass(frozen=True)
class ShadowRecommendation:
    _json: str = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._json)

    def to_json(self) -> str:
        return self._json


def production_instance(target: Mapping[str, Any], scenario_id: str) -> str:
    """Re-scope a discovery target using the existing production oracle."""
    return instance_id(dict(scenario_id=scenario_id, view_id=target.get("resource_id", ""),
                            bounds=target.get("bounds", ""),
                            stable_node_path=target.get("stable_node_path", ""),
                            class_name=target.get("class_name", "")))


def _consecutive(identity: str, recent: tuple[str, ...]) -> int:
    count = 0
    for value in reversed(recent):
        if value != identity:
            break
        count += 1
    return count


def plan_shadow(value: PlannerInput) -> ShadowRecommendation:
    """Rank evidence, with zero side effects and no inferred visit credit."""
    snapshot = value.snapshot.to_dict()
    history = value.history
    attempts, visits = dict(history.attempts), dict(history.visits)
    last_steps = dict(history.last_attempt_steps)
    stale = set(history.stale_ids)
    allowed = None if history.allowed_instance_ids is None else set(history.allowed_instance_ids)
    current = snapshot.get("strict_current_focus", {})
    current_id = None
    if current.get("confirmed") is True and current.get("instance_id"):
        # Re-scope only the proven positional focus, never an input-focus flag.
        parts = json.loads(current["instance_id"])
        if len(parts) >= 5 and parts[3] == "bounds":
            current_id = production_instance(dict(resource_id=parts[2], bounds=parts[4]), history.scenario_id)
    nav_ids = {production_instance(c["target_identity"], history.scenario_id)
               for c in snapshot["candidates"] if c["action_kind"] == "BOTTOM_NAV"}
    ranked, excluded, scrolls = [], [], []
    for candidate in snapshot["candidates"]:
        kind = candidate["action_kind"]
        target = candidate["target_identity"]
        identity = production_instance(target, history.scenario_id)
        eligibility = candidate["eligibility"]
        evidence = candidate.get("evidence", {})
        flags = candidate.get("target_semantics", {}).get("flags", {})
        bounds = parse_bounds_str(normalized_bounds(target.get("bounds", "")))
        reason = None
        if kind == "SCROLL_FORWARD_VERTICAL":
            if (eligibility.get("availability") == "AVAILABLE"
                    and evidence.get("axis_contract") == "axis-v1"
                    and evidence.get("supporting_signals") and bounds
                    and candidate.get("safety_hint") == "READ_ONLY"):
                scrolls.append(candidate)
            else:
                excluded.append(dict(candidate_id=candidate["candidate_id"], eligible=False,
                                     exclusion_reason="UNVERIFIED_SCROLL_OPPORTUNITY"))
            continue
        if kind != "FOCUS_TARGET":
            reason = "ACTION_OUTSIDE_FOCUS_PLANNER"
        elif identity in stale or evidence.get("current_presence") is not True:
            reason = "STALE_CANDIDATE"
        elif (eligibility.get("availability") not in {"AVAILABLE", "UNKNOWN"}
              or flags.get("focusable") is not True or flags.get("enabled") is False):
            reason = "NOT_ACTIONABLE"
        elif not bounds or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            reason = "INVALID_GEOMETRY"
        elif candidate.get("safety_hint") != "READ_ONLY":
            reason = "EXPLICIT_SAFETY_BLOCK"
        elif identity in nav_ids or allowed is not None and identity not in allowed:
            reason = "OUTSIDE_TRAVERSAL_DOMAIN"
        if reason:
            excluded.append(dict(candidate_id=candidate["candidate_id"], instance_id=identity,
                                 eligible=False, exclusion_reason=reason))
            continue
        attempt_count = max(0, int(attempts.get(identity, 0)))
        visit_count = max(0, int(visits.get(identity, 0)))
        never = history.known and attempt_count == 0
        transition_value = identity in value.transition_value_ids
        reasons = []
        if visit_count:
            tier = 2 if transition_value else 3
            reasons.append("VERIFIED_TRANSITION_VALUE" if transition_value else "VISITED_DEPRIORITIZED")
        elif never:
            tier = 0
            reasons.extend(("NEVER_ATTEMPTED", "STARVATION_PRIORITY"))
        else:
            tier = 1
            reasons.append("ATTEMPTED_UNVISITED" if attempt_count else "HISTORY_UNKNOWN_STRUCTURAL_ONLY")
        if identity == current_id and not transition_value:
            tier = 3
            reasons.append("CURRENT_FOCUS_DEPRIORITIZED")
        consecutive = _consecutive(identity, history.recent_attempts)
        if consecutive:
            reasons.append("RECENT_REPEAT_DEPRIORITIZED")
        if eligibility.get("availability") == "UNKNOWN":
            tier = max(tier, 1)
            reasons.append("ACTIONABILITY_PARTIAL_EVIDENCE")
        # Older real attempts win a retry tie; no wall clock or shadow attempts.
        sort_key = (tier, identity == current_id and not transition_value,
                    consecutive, attempt_count, last_steps.get(identity, -1),
                    bounds[1], bounds[0], bounds[3], bounds[2], identity, candidate["candidate_id"])
        ranked.append(dict(candidate_id=candidate["candidate_id"], instance_id=identity,
                           eligible=True, priority_tier=tier, reason_codes=reasons,
                           attempt_count=attempt_count, visit_count=visit_count,
                           never_attempted=never, consecutive_recent_attempts=consecutive,
                           last_attempt_step=last_steps.get(identity), target_identity=target,
                           _sort_key=sort_key))
    ranked.sort(key=lambda row: row.pop("_sort_key"))
    for rank, row in enumerate(ranked, 1):
        row["candidate_rank"] = rank
    scrolls.sort(key=lambda row: row["candidate_id"])
    unsafe_context = value.context_status in {"WRONG_CONTEXT", "CONTRADICTORY_CONTEXT"}
    scroll_available = bool(scrolls and not value.scroll_exhausted and not value.scroll_blocked
                            and not value.pending_transition and not value.safety_blocked and not unsafe_context)
    selected = ranked[0] if ranked else None
    if value.safety_blocked or unsafe_context:
        action, selected, reasons = "RECOVERY_OR_NONE", None, ["EXPLICIT_SAFETY_BLOCK"]
    elif value.pending_transition:
        action, selected, reasons = "RECOVERY_OR_NONE", None, ["PENDING_TRANSITION"]
    elif selected and selected["priority_tier"] < 3:
        action, reasons = "FOCUS_CANDIDATE", list(selected["reason_codes"])
    elif scroll_available:
        action, selected, reasons = "SCROLL_FORWARD", None, ["SCROLL_AFTER_CANDIDATE_EXHAUSTION"]
    elif selected and selected["instance_id"] != current_id:
        action, reasons = "FOCUS_CANDIDATE", list(selected["reason_codes"])
    else:
        action, selected, reasons = "RECOVERY_OR_NONE", None, ["NO_VALID_ACTION"]
    if value.context_status in {"PARTIAL_CONTEXT", "UNRESOLVED_CONTEXT"}:
        reasons.append("STRUCTURAL_ONLY_CONTEXT")
    scroll = scrolls[0] if action == "SCROLL_FORWARD" else None
    document = dict(schema_version="phase4a-shadow-recommendation-v1",
                    planner_state_id=snapshot["state_id"], semantic_substates=snapshot.get("semantic_substates", []),
                    context_status=value.context_status, recommended_action=action,
                    recommended_candidate_id=selected["candidate_id"] if selected else scroll["candidate_id"] if scroll else None,
                    recommended_instance_id=selected["instance_id"] if selected else None,
                    recommended_target=selected["target_identity"] if selected else scroll["target_identity"] if scroll else None,
                    candidate_rank=selected["candidate_rank"] if selected else None, reason_codes=reasons,
                    candidate_count=len(snapshot["candidates"]), eligible_candidate_count=len(ranked),
                    never_attempted_count=sum(r["never_attempted"] and not r["visit_count"] for r in ranked),
                    attempted_unvisited_count=sum(r["attempt_count"] > 0 and not r["visit_count"] for r in ranked),
                    visited_count=sum(r["visit_count"] > 0 for r in ranked), history_source=history.source,
                    scroll_opportunity=dict(available=scroll_available, exhausted=value.scroll_exhausted,
                                            blocked=value.scroll_blocked, pending=value.pending_transition),
                    shadow_no_progress_assessment=("FOCUS_PLATEAU_SCROLL_AVAILABLE" if value.focus_plateau and scroll_available
                                                   else "CANDIDATES_REMAIN" if selected else "NO_VALID_ACTION"),
                    last_movement=value.last_movement, ranking=ranked,
                    excluded=sorted(excluded + [dict(r, eligible=False, exclusion_reason=r["reason"])
                                               for r in snapshot.get("excluded", [])], key=canonical_json),
                    mode="SHADOW_ONLY", action_executed=False, changes_traversal_order=False,
                    changes_termination=False, visit_credit=0, production_visit_authority=False)
    return ShadowRecommendation(canonical_json(document))


def compare_production(recommendation: ShadowRecommendation, action: str,
                       target_instance_id: str | None = None) -> dict[str, Any]:
    """Compare intended actions. An untargeted move is not an intended landing."""
    shadow = recommendation.to_dict()
    match = False
    if action in {"UNKNOWN", "FOCUS_NEXT", "COMPOSITE"}:
        classification = "INSUFFICIENT_EVIDENCE"
    elif action == shadow["recommended_action"] and (
            action == "RECOVERY_OR_NONE" or action == "FOCUS_CANDIDATE"
            and target_instance_id == shadow["recommended_instance_id"]):
        match, classification = True, "EQUIVALENT_CHOICE"
    elif action == "SCROLL_FORWARD" and shadow["recommended_action"] == action:
        # Direction equivalence is observed; exact container match is unknown.
        classification = "EQUIVALENT_CHOICE"
    else:
        production = next((r for r in shadow["ranking"] if r["instance_id"] == target_instance_id), None)
        chosen = next((r for r in shadow["ranking"] if r["candidate_rank"] == shadow["candidate_rank"]), None)
        if production and chosen:
            classification = ("EXPECTED_SMARTER_CHOICE" if chosen["priority_tier"] < production["priority_tier"]
                              else "EQUIVALENT_CHOICE" if chosen["priority_tier"] == production["priority_tier"]
                              else "POTENTIAL_REGRESSION")
        elif shadow["recommended_action"] == "SCROLL_FORWARD" and production and production["priority_tier"] == 3:
            classification = "EXPECTED_SMARTER_CHOICE"
        else:
            classification = "INSUFFICIENT_EVIDENCE"
    return dict(production_action=action, production_target=target_instance_id,
                shadow_action=shadow["recommended_action"], shadow_target=shadow["recommended_instance_id"] or shadow["recommended_candidate_id"],
                match=match, match_classification=classification)
