"""Opt-in, bounded execution authority. No device I/O or visit ledger writes."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from tb_runner.phase4a_planner import PlannerInput, ShadowRecommendation, plan_shadow, production_instance
from tb_runner.utils import parse_bounds_str


@dataclass(frozen=True)
class AuthorityEvidence:
    # Unknown evidence is denied. Only the controlled adapter supplies these.
    enabled: bool = False
    fresh: bool | None = None
    recovery_clear: bool | None = None
    lifecycle_clear: bool | None = None
    transport_clear: bool | None = None
    focus_coherent: bool | None = None
    plugin_context_required: bool = False
    scroll_container_proven: bool | None = None
    structural_scope_proven: bool | None = None
    geometry_in_viewport: bool | None = None


@dataclass(frozen=True)
class AuthorityDecision:
    allowed: bool
    mode: str
    reason: str
    candidate_id: str | None = None

    def to_dict(self):
        return dict(allowed=self.allowed, mode=self.mode, reason=self.reason, candidate_id=self.candidate_id)


def execution_gate(original: PlannerInput, recommendation: ShadowRecommendation,
                   current: PlannerInput, evidence: AuthorityEvidence,
                   *, actions_used: int = 0, degraded: bool = False,
                   action_limit: int = 5) -> AuthorityDecision:
    """Revalidate the selected action against a fresh observation, fail closed."""
    def deny(reason, mode="FALLBACK_PRODUCTION"):
        return AuthorityDecision(False, mode, reason)

    if evidence.enabled is not True:
        return deny("EXECUTION_OPT_IN_REQUIRED", "SHADOW_ONLY")
    if degraded:
        return deny("PLANNER_DEGRADED_TO_PRODUCTION")
    if type(action_limit) is not int or not 1 <= action_limit <= 20:
        return deny("INVALID_CONTROLLED_ACTION_BUDGET")
    if actions_used >= action_limit:
        return deny("CONTROLLED_ACTION_BUDGET_EXHAUSTED")
    for flag, reason in ((evidence.fresh, "FRESH_OBSERVATION_REQUIRED"),
                         (evidence.recovery_clear, "RECOVERY_CONFLICT"),
                         (evidence.lifecycle_clear, "LIFECYCLE_BLOCKER_OR_UNKNOWN"),
                         (evidence.transport_clear, "TRANSPORT_BLOCKER_OR_UNKNOWN"),
                         (evidence.focus_coherent, "INDETERMINATE_FOCUS")):
        if flag is not True:
            return deny(reason)
    if current.safety_blocked or current.pending_transition:
        return deny("RECOVERY_CONFLICT")
    if current.context_status not in {"VERIFIED_ROOT_CONTEXT", "VERIFIED_PLUGIN_CONTEXT", "PARTIAL_CONTEXT"}:
        return deny("CONTEXT_INSUFFICIENT")
    if evidence.plugin_context_required and current.context_status != "VERIFIED_PLUGIN_CONTEXT":
        return deny("UNVERIFIED_PLUGIN_ASSUMPTION")
    old, now = original.snapshot.to_dict(), current.snapshot.to_dict()
    if original.history.scenario_id != current.history.scenario_id:
        return deny("SCENARIO_SCOPE_CHANGED")
    if (old.get("state_id") != now.get("state_id")
            or old.get("semantic_substates", []) != now.get("semantic_substates", [])):
        return deny("STATE_OR_SUBSTATE_CHANGED")
    if old.get("state_id") is None and (evidence.structural_scope_proven is not True
            or old.get("fingerprint_hash") != now.get("fingerprint_hash")
            or old.get("viewport_signature") != now.get("viewport_signature")):
        return deny("UNRESOLVED_STRUCTURAL_SCOPE_NOT_PROVEN")
    if now.get("strict_current_focus", {}).get("confirmed") is not True:
        return deny("INDETERMINATE_FOCUS")
    if evidence.geometry_in_viewport is not True:
        return deny("CURRENT_VIEWPORT_GEOMETRY_NOT_PROVEN")
    # Callers cannot forge a favorable recommendation or use an old ranking.
    selected = recommendation.to_dict()
    if selected != plan_shadow(original).to_dict():
        return deny("INVALID_PLANNER_RECOMMENDATION")
    def target_key(target):
        return {k: v for k, v in (target or {}).items() if k != "instance_id"}
    # Unresolved diagnostic observation IDs change on every capture. The
    # production positional identity, exact geometry/metadata and stable
    # observed scope remain independently checkable; no plugin inference.
    matching = [c for c in now["candidates"] if
                c["action_kind"] == ("FOCUS_TARGET" if selected["recommended_action"] == "FOCUS_CANDIDATE" else "SCROLL_FORWARD_VERTICAL")
                and target_key(c["target_identity"]) == target_key(selected["recommended_target"])]
    candidate = matching[0] if len(matching) == 1 else None
    if candidate is None and selected["recommended_action"] != "RECOVERY_OR_NONE":
        return deny("CANDIDATE_DISAPPEARED")
    fresh = plan_shadow(current).to_dict()
    if (selected["recommended_action"], target_key(selected["recommended_target"])) != (
            fresh["recommended_action"], target_key(fresh["recommended_target"])):
        return deny("STALE_CANDIDATE_OR_RANKING")
    action = selected["recommended_action"]
    if action == "FOCUS_CANDIDATE":
        target = candidate["target_identity"]
        identity = production_instance(target, current.history.scenario_id)
        if identity in current.history.stale_ids or candidate["evidence"].get("current_presence") is not True:
            return deny("STALE_CANDIDATE")
        flags = candidate["target_semantics"].get("flags", {})
        if (flags.get("enabled") is not True or flags.get("focusable") is not True
                or candidate["eligibility"].get("availability") != "AVAILABLE"):
            return deny("ACTIONABILITY_NOT_PROVEN")
        bounds = parse_bounds_str(target.get("bounds", ""))
        if not bounds or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            return deny("INVALID_GEOMETRY")
        focus = json.loads(now["strict_current_focus"]["instance_id"])
        focus_id = production_instance(dict(resource_id=focus[2], bounds=focus[4]), current.history.scenario_id)
        if identity == focus_id and identity not in current.transition_value_ids:
            return deny("CURRENT_FOCUS_WITHOUT_TRANSITION_VALUE")
        if candidate.get("safety_hint") != "READ_ONLY":
            return deny("ACTION_SAFETY_NOT_PROVEN")
        return AuthorityDecision(True, "CONTROLLED_TARGET_FOCUS", "CURRENT_STRUCTURAL_TARGET_PROVEN", candidate["candidate_id"])
    if action == "SCROLL_FORWARD":
        if current.scroll_exhausted or current.scroll_blocked:
            return deny("SCROLL_EXHAUSTED_OR_BLOCKED")
        if evidence.scroll_container_proven is not True:
            return deny("SCROLL_NOT_PROVEN_SAFE")
        if any(r["priority_tier"] < 3 for r in fresh["ranking"]):
            return deny("HIGHER_VALUE_FOCUS_REMAINS")
        if candidate["action_kind"] != "SCROLL_FORWARD_VERTICAL":
            return deny("SCROLL_NOT_PROVEN_SAFE")
        return AuthorityDecision(True, "CONTROLLED_SCROLL", "VERTICAL_CONTAINER_PROVEN", candidate["candidate_id"])
    return deny("NO_SAFE_PLANNER_ACTION")


@dataclass
class ExecutionBudget:
    max_actions: int = 5
    actions: int = 0
    failure_streak: int = 0
    degraded: bool = False
    degraded_reason: str = ""
    fallback_count: int = 0
    scroll_attempts: int = 0
    consecutive_selections: int = 0
    repeated_result_count: int = 0
    inventory_stable_count: int = 0
    state_stable_count: int = 0
    last_target: str | None = None
    last_result: str | None = None
    last_inventory: str | None = None
    last_state: Any = None
    target_attempts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if type(self.max_actions) is not int or not 1 <= self.max_actions <= 20:
            raise ValueError("controlled action budget must be 1..20")

    def reserve(self, mode: str, target: str | None, inventory: str, state: Any) -> None:
        if self.degraded or self.actions >= self.max_actions:
            raise RuntimeError("controlled action budget unavailable")
        self.actions += 1
        self.scroll_attempts += mode == "CONTROLLED_SCROLL"
        self.consecutive_selections = self.consecutive_selections + 1 if target == self.last_target else 1
        self.inventory_stable_count = self.inventory_stable_count + 1 if inventory == self.last_inventory else 0
        self.state_stable_count = self.state_stable_count + 1 if state == self.last_state else 0
        if target:
            self.target_attempts[target] = self.target_attempts.get(target, 0) + 1
        self.last_target, self.last_inventory, self.last_state = target, inventory, state

    def outcome(self, result: str, moved: bool) -> None:
        self.repeated_result_count = self.repeated_result_count + 1 if result == self.last_result else 1
        self.last_result = result
        self.failure_streak = 0 if moved else self.failure_streak + 1
        if self.failure_streak >= 2:
            self.degraded = True
            self.degraded_reason = "TWO_CONSECUTIVE_CONTROLLED_NO_PROGRESS_RESULTS"

    def production_outcome(self, *, new_visit: bool) -> None:
        if not new_visit and self.last_target and self.target_attempts.get(self.last_target, 0) >= 2:
            self.degraded = True
            self.degraded_reason = "REPEATED_TARGET_WITHOUT_NEW_PRODUCTION_VISIT"


def correlated_result(client, result: dict) -> bool:
    """Require the transport's exact active request, never an old ACK."""
    request = str(getattr(client, "_evidence_active_request_id", "") or "")
    return bool(request and request == str(result.get("reqId") or result.get("requestId") or ""))
