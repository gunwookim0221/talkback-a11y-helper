"""Pure Phase 6D1 exploration-progress and plateau evaluator.

This module produces recommendations only. It has no device, filesystem,
dispatch, scheduler, visit-ledger, or production-termination dependencies.
Every transition is tied to one closed production decision and its monotonic
numeric watermark. Callers commit ``proposed_history`` only with that closed
decision; evaluating the same input against the same prior history is pure and
deterministic.

State and frontier evidence used for a decision must be explicitly marked
POST_ACTION/CLOSED_DECISION and carry the decision watermark. In particular,
a PRE_ACTION frontier result is never completion evidence for the action that
followed it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
from typing import Any, Mapping


PLATEAU_SCHEMA_VERSION = "phase6-exploration-progress.v1"
CURRENT_SCOPE = "CURRENT_STATE_CANDIDATE_FOCUS"
SUPPORTED_SCOPES = {CURRENT_SCOPE, "CONTENT_SCOPE", "RUN_SCOPE"}
_POST_ACTION_STAGES = {"POST_ACTION", "CLOSED_DECISION", "AFTER_ACTION"}
_CONCLUSIVE_FRONTIER_STATUSES = {"ELIGIBLE", "EXPLORED", "BLOCKED", "UNSAFE", "EXHAUSTED"}
_TERMINAL_BLOCKED_REASONS = {"CURRENT_FOCUS_NO_NEW_OPPORTUNITY"}
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


class ProgressKind(str, Enum):
    CURSOR_PROGRESS = "CURSOR_PROGRESS"
    LOCAL_PROGRESS = "LOCAL_PROGRESS"
    EXPLORATION_PROGRESS = "EXPLORATION_PROGRESS"
    KNOWLEDGE_PROGRESS = "KNOWLEDGE_PROGRESS"
    NO_MEANINGFUL_PROGRESS = "NO_MEANINGFUL_PROGRESS"


class ExplorationDecision(str, Enum):
    CONTINUE = "CONTINUE"
    REDIRECT_FRONTIER = "REDIRECT_FRONTIER"
    RECOVER_EVIDENCE = "RECOVER_EVIDENCE"
    CHECK_SCROLL = "CHECK_SCROLL"
    COMPLETE_CURRENT_SCOPE = "COMPLETE_CURRENT_SCOPE"
    TERMINATE_INCOMPLETE_POLICY_LIMIT = "TERMINATE_INCOMPLETE_POLICY_LIMIT"
    TERMINATE_INCOMPLETE_UNKNOWN = "TERMINATE_INCOMPLETE_UNKNOWN"
    TERMINATE_INCOMPLETE_NO_PROGRESS = "TERMINATE_INCOMPLETE_NO_PROGRESS"
    TERMINATE_HARD_BOUND = "TERMINATE_HARD_BOUND"
    TERMINATE_SAFETY_LIMIT = "TERMINATE_SAFETY_LIMIT"
    TERMINATE_ERROR = "TERMINATE_ERROR"


@dataclass(frozen=True)
class StatePlateau:
    state_id: str
    age: int = 0
    last_meaningful_progress_step: int | None = None


@dataclass(frozen=True)
class ExplorationHistory:
    """Immutable, run-local evaluator history; no production authority."""

    last_decision_watermark: int = -1
    last_decision_id: str | None = None
    processed_decision_ids: tuple[str, ...] = ()
    known_state_ids: tuple[str, ...] = ()
    known_visit_ids: tuple[str, ...] = ()
    known_frontier_ids: tuple[str, ...] = ()
    known_edge_ids: tuple[str, ...] = ()
    known_viewport_ids: tuple[str, ...] = ()
    known_local_progress_ids: tuple[str, ...] = ()
    resolved_knowledge_ids: tuple[str, ...] = ()
    frontier_statuses: tuple[tuple[str, str], ...] = ()
    recovery_recommended_evidence_ids: tuple[str, ...] = ()
    recovery_attempted_evidence_ids: tuple[str, ...] = ()
    state_plateaus: tuple[StatePlateau, ...] = ()
    run_plateau_age: int = 0
    last_run_meaningful_progress_step: int | None = None
    closed_decision_count: int = 0
    history_item_count: int = 0
    truncated: bool = False

    def state_plateau(self, state_id: str | None) -> StatePlateau | None:
        if not state_id:
            return None
        return next((record for record in self.state_plateaus if record.state_id == state_id), None)


@dataclass(frozen=True)
class ExplorationPolicy:
    state_plateau_threshold: int = 4
    run_plateau_threshold: int = 4
    scope: str = CURRENT_SCOPE
    max_history_items: int = 10_000

    def __post_init__(self) -> None:
        for name, value in (("state_plateau_threshold", self.state_plateau_threshold),
                            ("run_plateau_threshold", self.run_plateau_threshold),
                            ("max_history_items", self.max_history_items)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.scope not in SUPPORTED_SCOPES:
            raise ValueError(f"scope must be one of {sorted(SUPPORTED_SCOPES)}")


@dataclass(frozen=True)
class ExplorationEvaluation:
    decision: ExplorationDecision
    reason_codes: tuple[str, ...]
    progress_types: tuple[ProgressKind, ...]
    state_id: str | None
    scope: str
    decision_id: str | None
    decision_step: int | None
    input_watermark: int | None
    frontier_exhausted: str
    evidence_complete: bool
    eligible_count: int
    unknown_count: int
    never_attempted_count: int
    retryable_count: int
    revisit_only_count: int
    policy_limited_count: int
    state_plateau_age: int | None
    run_plateau_age: int
    state_plateau_threshold: int
    run_plateau_threshold: int
    state_last_meaningful_progress_step: int | None
    run_last_meaningful_progress_step: int | None
    plateau_established: bool
    legacy_repeat_reason: str | None
    scroll_evidence_summary: tuple[tuple[str, Any], ...]
    hard_bound_summary: tuple[tuple[str, Any], ...]
    safety_summary: tuple[tuple[str, Any], ...]
    metrics_delta: tuple[tuple[str, int], ...]
    proposed_history: ExplorationHistory

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLATEAU_SCHEMA_VERSION,
            "decision": self.decision.value,
            "decision_authority": "NONE",
            "reason_codes": list(self.reason_codes),
            "progress_types": [item.value for item in self.progress_types],
            "decision_id": self.decision_id,
            "decision_step": self.decision_step,
            "input_watermark": self.input_watermark,
            "state_id": self.state_id,
            "scope": self.scope,
            "frontier_exhausted": self.frontier_exhausted,
            "evidence_complete": self.evidence_complete,
            "counts": {
                "eligible_count": self.eligible_count,
                "unknown_count": self.unknown_count,
                "never_attempted_count": self.never_attempted_count,
                "retryable_count": self.retryable_count,
                "revisit_only_count": self.revisit_only_count,
                "policy_limited_count": self.policy_limited_count,
            },
            "state_plateau_age": self.state_plateau_age,
            "run_plateau_age": self.run_plateau_age,
            "state_plateau_threshold": self.state_plateau_threshold,
            "run_plateau_threshold": self.run_plateau_threshold,
            "state_last_meaningful_progress_step": self.state_last_meaningful_progress_step,
            "run_last_meaningful_progress_step": self.run_last_meaningful_progress_step,
            "plateau_established": self.plateau_established,
            "legacy_repeat_reason": self.legacy_repeat_reason,
            "scroll_evidence_summary": dict(self.scroll_evidence_summary),
            "hard_bound_summary": dict(self.hard_bound_summary),
            "safety_summary": dict(self.safety_summary),
            "metrics_delta": dict(self.metrics_delta),
            "proposed_history": history_to_dict(self.proposed_history),
        }


def history_to_dict(history: ExplorationHistory) -> dict[str, Any]:
    """Return detached JSON-compatible history data."""
    return {
        "schema_version": PLATEAU_SCHEMA_VERSION,
        "last_decision_watermark": history.last_decision_watermark,
        "last_decision_id": history.last_decision_id,
        "processed_decision_ids": list(history.processed_decision_ids),
        "known_state_ids": list(history.known_state_ids),
        "known_visit_ids": list(history.known_visit_ids),
        "known_frontier_ids": list(history.known_frontier_ids),
        "known_edge_ids": list(history.known_edge_ids),
        "known_viewport_ids": list(history.known_viewport_ids),
        "known_local_progress_ids": list(history.known_local_progress_ids),
        "resolved_knowledge_ids": list(history.resolved_knowledge_ids),
        "frontier_statuses": {key: value for key, value in history.frontier_statuses},
        "recovery_recommended_evidence_ids": list(history.recovery_recommended_evidence_ids),
        "recovery_attempted_evidence_ids": list(history.recovery_attempted_evidence_ids),
        "state_plateaus": [
            {"state_id": item.state_id, "age": item.age,
             "last_meaningful_progress_step": item.last_meaningful_progress_step}
            for item in history.state_plateaus
        ],
        "run_plateau_age": history.run_plateau_age,
        "last_run_meaningful_progress_step": history.last_run_meaningful_progress_step,
        "closed_decision_count": history.closed_decision_count,
        "history_item_count": history.history_item_count,
        "truncated": history.truncated,
    }


def _plain_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _text(value: Any, limit: int = 512) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if value and len(value) <= limit else ""


def _upper(value: Any) -> str:
    return _text(value).upper()


def _integer(value: Any) -> int | None:
    return value if type(value) is int else None


def _policy(value: ExplorationPolicy | Mapping[str, Any] | None) -> ExplorationPolicy:
    if value is None:
        return ExplorationPolicy()
    if isinstance(value, ExplorationPolicy):
        return value
    if isinstance(value, Mapping):
        return ExplorationPolicy(
            state_plateau_threshold=value.get("state_plateau_threshold", 4),
            run_plateau_threshold=value.get("run_plateau_threshold", 4),
            scope=value.get("scope", CURRENT_SCOPE),
            max_history_items=value.get("max_history_items", 10_000),
        )
    raise TypeError("policy must be ExplorationPolicy, a mapping, or None")


def _evidence_watermark(value: Mapping[str, Any]) -> int | None:
    for key in ("evidence_watermark", "decision_watermark", "input_watermark", "watermark"):
        if key in value:
            return _integer(value.get(key))
    return None


def _aligned(value: Mapping[str, Any], *, watermark: int, decision_id: str,
             require_post_action: bool = True) -> bool:
    if _evidence_watermark(value) != watermark:
        return False
    evidence_decision_id = _text(value.get("decision_id"))
    if evidence_decision_id and evidence_decision_id != decision_id:
        return False
    stage = _upper(value.get("evidence_stage", value.get("stage")))
    return not require_post_action or stage in _POST_ACTION_STAGES


def _state_id(state: Mapping[str, Any], *, aligned: bool) -> str | None:
    if not aligned or _upper(state.get("state_resolution", state.get("resolution", state.get("status")))) != "RESOLVED":
        return None
    return _text(state.get("state_id")) or None


def _decision_identity(production: Mapping[str, Any]) -> tuple[str | None, int | None, int | None, bool]:
    decision_id = _text(production.get("decision_id")) or None
    step = _integer(production.get("decision_step", production.get("step")))
    watermark = _integer(production.get("decision_watermark", production.get("watermark")))
    closed = production.get("decision_closed") is True or production.get("closed") is True
    stage_ok = _upper(production.get("decision_stage", production.get("stage"))) in _POST_ACTION_STAGES
    valid = bool(decision_id and step is not None and step >= 0 and watermark is not None
                 and watermark >= 0 and closed and stage_ok)
    return decision_id, step, watermark, valid


def _history_contains(history: ExplorationHistory, field: str, value: str) -> bool:
    return value in getattr(history, field)


def _remember(history: ExplorationHistory, field: str, value: str,
              policy: ExplorationPolicy) -> tuple[ExplorationHistory, bool]:
    values = getattr(history, field)
    if value in values:
        return history, False
    if history.truncated or history.history_item_count >= policy.max_history_items:
        return replace(history, truncated=True), False
    updated = tuple(sorted((*values, value)))
    return replace(history, **{field: updated}, history_item_count=history.history_item_count + 1), True


def _status_map(history: ExplorationHistory) -> dict[str, str]:
    return dict(history.frontier_statuses)


def _frontier_counts(frontier: Mapping[str, Any]) -> dict[str, int]:
    raw = frontier.get("counts")
    counts = raw if isinstance(raw, Mapping) else frontier
    return {
        "eligible_count": max(0, _integer(counts.get("eligible_count")) or 0),
        "unknown_count": max(0, _integer(counts.get("unknown_count")) or 0),
        "never_attempted_count": max(0, _integer(counts.get("never_attempted_count")) or 0),
        "retryable_count": max(0, _integer(counts.get("retryable_count")) or 0),
        "revisit_only_count": max(0, _integer(counts.get("revisit_only_count")) or 0),
        "policy_limited_count": max(0, _integer(counts.get("policy_limited_count")) or 0),
        "deferred_scroll_count": max(0, _integer(counts.get("deferred_scroll_count")) or 0),
        "blocked_count": max(0, _integer(counts.get("blocked_count")) or 0),
    }


def _frontier_items(frontier: Mapping[str, Any], *, current_state_id: str | None
                    ) -> tuple[tuple[dict[str, Any], ...], int]:
    values = frontier.get("frontier_items", ())
    if not isinstance(values, (list, tuple)):
        return (), 0
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        frontier_id = _text(item.get("frontier_id"))
        if not frontier_id:
            continue
        item_state = _text(item.get("state_id"))
        if item_state and current_state_id and item_state != current_state_id:
            continue
        grouped.setdefault(frontier_id, []).append(item)
    result: list[dict[str, Any]] = []
    conflicts = 0
    critical_fields = ("state_id", "status", "priority_class", "priority", "provisional",
                       "evidence_sufficient", "stable_identity", "blocked_reason")
    for frontier_id in sorted(grouped):
        candidates = grouped[frontier_id]
        # Build signatures individually so input order cannot choose the winner.
        signatures = {
            json.dumps({name: item.get(name) for name in critical_fields}, sort_keys=True,
                       ensure_ascii=False, separators=(",", ":"), default=str)
            for item in candidates
        }
        if len(signatures) > 1:
            conflicts += 1
            result.append({"frontier_id": frontier_id, "state_id": current_state_id,
                           "status": "UNKNOWN", "priority_class": "P3",
                           "provisional": True,
                           "blocked_reason": "CONFLICTING_DUPLICATE_FRONTIER_EVIDENCE"})
            continue
        candidates.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False,
                                                     separators=(",", ":"), default=str))
        result.append(candidates[0])
    return tuple(result), conflicts


def _safe_scalar_summary(value: Mapping[str, Any], names: tuple[str, ...]) -> tuple[tuple[str, Any], ...]:
    pairs = []
    for name in names:
        item = value.get(name)
        if item is None or isinstance(item, (str, int, float, bool)):
            pairs.append((name, item))
    return tuple(pairs)


def _error_code(production: Mapping[str, Any]) -> str | None:
    if production.get("authoritative_error") is True or production.get("error_stop") is True:
        return _text(production.get("error_code")) or "AUTHORITATIVE_PRODUCTION_ERROR"
    for name in ("lifecycle_stop", "transport_stop", "audit_error"):
        if production.get(name) is True:
            return _text(production.get("error_code")) or name.upper()
    error = production.get("error")
    if isinstance(error, Mapping) and error.get("authoritative") is True:
        return _text(error.get("code")) or "AUTHORITATIVE_PRODUCTION_ERROR"
    return None


def _safety_denial(safety: Mapping[str, Any]) -> bool:
    return (safety.get("authoritative") is True
            and safety.get("required_action_denied") is True
            and safety.get("safe_alternative_available") is False)


def _hard_bound(hard_bounds: Mapping[str, Any]) -> bool:
    return (hard_bounds.get("authoritative") is True and hard_bounds.get("reached") is True
            and (hard_bounds.get("absolute") is True or hard_bounds.get("hard") is True))


def _cursor_moved(production: Mapping[str, Any]) -> bool:
    if production.get("actual_accessibility_focus_moved") is True:
        return True
    return (_upper(production.get("focus_transition_status")) == "CONFIRMED_MOVED"
            and (production.get("accessibility_focus_authoritative") is True
                 or _upper(production.get("focus_authority")) == "ACCESSIBILITY"))


def _new_visit(production: Mapping[str, Any]) -> bool:
    authoritative = (production.get("new_visit_authoritative") is True
                     or (_upper(production.get("visit_authority")) == "PRODUCTION"
                         and _upper(production.get("visit_outcome")) in {"NEW_VISIT", "VISIT_GRANTED"}))
    identity = _text(production.get("visit_instance_id")
                     or production.get("reconciled_visit_instance_id")
                     or production.get("visit_id"))
    return authoritative and bool(identity)


def _visit_identity(production: Mapping[str, Any]) -> str:
    return (_text(production.get("visit_instance_id"))
            or _text(production.get("reconciled_visit_instance_id"))
            or _text(production.get("visit_id")))


def _frontier_identifier(item: Mapping[str, Any]) -> str:
    frontier_id = _text(item.get("frontier_id"))
    priority = _upper(item.get("priority_class", item.get("priority")))
    status = _upper(item.get("status"))
    if not frontier_id or priority not in _PRIORITY_ORDER or status != "ELIGIBLE" or item.get("provisional") is True:
        return ""
    return frontier_id


def _frontier_fingerprint(frontier: Mapping[str, Any], items: tuple[dict[str, Any], ...],
                          state_id: str | None) -> str:
    # Status/label/request/timestamp churn cannot replenish recovery allowance.
    # Stable frontier identities plus stable reason codes identify the same
    # decision-critical uncertainty across repeated observations.
    stable_ids = sorted({_text(item.get("frontier_id")) for item in items
                         if _text(item.get("frontier_id"))})
    reasons = frontier.get("exhaustion_reason_codes", ())
    payload = {"state_id": state_id,
               "scope": _text(frontier.get("exhaustion_scope")),
               "frontier_ids": stable_ids,
               "reasons": sorted(_text(item) for item in reasons if _text(item))
               if isinstance(reasons, (list, tuple)) else []}
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _scroll_proof(scroll: Mapping[str, Any], *, aligned: bool, scope: str,
                  state_id: str | None) -> tuple[bool, bool, bool]:
    """Return (absence_proven, not_applicable, obligation_or_unknown)."""
    if not aligned:
        return False, False, True
    status = _upper(scroll.get("status", scroll.get("scroll_status")))
    proof_scope = _upper(scroll.get("scope"))
    proof_state = _text(scroll.get("scope_state_id", scroll.get("state_id")))
    scoped = (proof_scope == scope
              or (scope == CURRENT_SCOPE and state_id is not None and proof_state == state_id))
    absence = (status == "SCROLL_ABSENT_PROVEN_FOR_SCOPE"
               and scroll.get("absence_proven") is True and scoped)
    not_applicable = (status in {"NOT_APPLICABLE", "NOT_REQUIRED"}
                      and (scoped or scroll.get("applies_to_scope") is False))
    obligation = status in {
        "SCROLL_REQUIRED", "SCROLL_POSSIBLE", "SCROLL_UNKNOWN", "SCROLL_NOT_CAPABLE",
        "SCROLL_MOVED", "SCROLL_UNVERIFIED", "UNKNOWN",
    } or scroll.get("scroll_obligation") is True
    return absence, not_applicable, obligation or not (absence or not_applicable)


def _recovery_key(frontier: Mapping[str, Any], items: tuple[dict[str, Any], ...],
                  state_id: str | None) -> str:
    explicit = _text(frontier.get("unknown_evidence_key"))
    if explicit:
        return explicit
    return _frontier_fingerprint(frontier, items, state_id)


def _recovery_available(recovery_budget: Mapping[str, Any], history: ExplorationHistory,
                        evidence_key: str) -> bool:
    remaining = _integer(recovery_budget.get("remaining")) or 0
    plausible = recovery_budget.get("could_resolve") is True
    already_recommended = evidence_key in history.recovery_recommended_evidence_ids
    already_attempted = (evidence_key in history.recovery_attempted_evidence_ids
                         or recovery_budget.get("already_attempted") is True)
    return remaining > 0 and plausible and not already_recommended and not already_attempted


def _transition_history(*, history: ExplorationHistory, policy: ExplorationPolicy,
                        decision_id: str, decision_step: int, watermark: int,
                        state_id: str | None, state_fresh: bool,
                        current_state: Mapping[str, Any], frontier: Mapping[str, Any],
                        frontier_fresh: bool, frontier_items: tuple[dict[str, Any], ...],
                        scroll: Mapping[str, Any], scroll_fresh: bool,
                        production: Mapping[str, Any]) -> tuple[ExplorationHistory, tuple[ProgressKind, ...],
                                                             tuple[str, ...], int | None, int, int | None, int | None]:
    """Build the immutable proposal for exactly one new closed decision."""
    working = history
    reasons: list[str] = []
    kinds: set[ProgressKind] = set()
    if _cursor_moved(production):
        kinds.add(ProgressKind.CURSOR_PROGRESS)

    # A closed result is consumed once even if graph/frontier evidence is stale.
    working, _ = _remember(working, "processed_decision_ids", decision_id, policy)
    # processed_decision_ids is capped by the same memory bound; if it could not
    # be recorded, history becomes incomplete and cannot prove novelty/closure.
    if working.truncated:
        working = replace(working, last_decision_watermark=watermark,
                          last_decision_id=decision_id,
                          closed_decision_count=working.closed_decision_count + 1,
                          run_plateau_age=working.run_plateau_age + 1)
        return (working, tuple(sorted(kinds, key=lambda item: item.value)),
                ("HISTORY_TRUNCATED",), None, working.run_plateau_age, None,
                working.last_run_meaningful_progress_step)

    new_state = False
    if state_fresh and state_id and current_state.get("identity_history_truncated") is not True:
        if state_id not in working.known_state_ids:
            working, new_state = _remember(working, "known_state_ids", state_id, policy)
            if new_state:
                kinds.add(ProgressKind.EXPLORATION_PROGRESS)
                reasons.append("NEW_RESOLVED_STATE")

    visit_id = _visit_identity(production)
    new_visit = False
    if _new_visit(production) and visit_id not in working.known_visit_ids:
        working, new_visit = _remember(working, "known_visit_ids", visit_id, policy)
    if new_visit:
        kinds.add(ProgressKind.EXPLORATION_PROGRESS)
        reasons.append("MEANINGFUL_NEW_VISIT")

    new_frontiers: list[str] = []
    new_frontier_added = False
    previous_status = _status_map(working)
    knowledge_progress = False
    if frontier_fresh and frontier.get("truncated") is not True:
        for item in frontier_items:
            frontier_id = _text(item.get("frontier_id"))
            status = _upper(item.get("status"))
            if frontier_id and status:
                previous = previous_status.get(frontier_id)
                if (previous == "UNKNOWN" and status in _CONCLUSIVE_FRONTIER_STATUSES
                        and frontier_id not in working.resolved_knowledge_ids):
                    working, added = _remember(working, "resolved_knowledge_ids", frontier_id, policy)
                    knowledge_progress = knowledge_progress or added
                    if added:
                        reasons.append("UNKNOWN_FRONTIER_CLASSIFIED")
                previous_status[frontier_id] = status
            candidate_id = _frontier_identifier(item)
            item_state = _text(item.get("state_id"))
            same_scope = not item_state or not state_id or item_state == state_id
            if (candidate_id and same_scope and item.get("evidence_sufficient") is not False
                    and item.get("stable_identity") is not False
                    and candidate_id not in working.known_frontier_ids):
                new_frontiers.append(candidate_id)
        for frontier_id in sorted(set(new_frontiers)):
            working, added = _remember(working, "known_frontier_ids", frontier_id, policy)
            if added:
                new_frontier_added = True
                reasons.append("NEW_VALID_FRONTIER")

    edge = _plain_mapping(production.get("verified_edge"))
    if not edge and production.get("edge_verified") is True:
        edge = {"opportunity_id": production.get("edge_opportunity_id"),
                "stable_edge_id": production.get("stable_edge_id"),
                "edge_id": production.get("edge_id"),
                "stable_identity": production.get("edge_identity_stable") is True,
                "verified": True, "evidence_watermark": watermark}
    # GraphEdge.edge_id is occurrence-scoped. Prefer its stable opportunity
    # identity so revisiting the same known action edge cannot reset plateau.
    edge_id = (_text(edge.get("opportunity_id")) or _text(edge.get("stable_edge_id"))
               or (_text(edge.get("edge_id")) if edge.get("stable_identity") is True else ""))
    edge_fresh = (edge.get("verified") is True
                  and (_evidence_watermark(edge) == watermark or edge.get("evidence_watermark") is None
                       and edge.get("decision_id") is None))
    new_edge = False
    if edge_id and edge_fresh:
        working, new_edge = _remember(working, "known_edge_ids", edge_id, policy)
        if new_edge:
            reasons.append("NEW_VERIFIED_EDGE")

    new_viewport = False
    if scroll_fresh and _upper(scroll.get("status", scroll.get("scroll_status"))) in {
        "SCROLL_MOVED", "VERIFIED_MOVED",
    }:
        viewport_id = _text(scroll.get("new_viewport_id", scroll.get("viewport_id")))
        if viewport_id:
            working, new_viewport = _remember(working, "known_viewport_ids", viewport_id, policy)
            if new_viewport:
                reasons.append("NEW_VERIFIED_VIEWPORT")
        scroll_edge_id = (_text(scroll.get("scroll_opportunity_id"))
                          or (_text(scroll.get("scroll_edge_id"))
                              if scroll.get("scroll_edge_identity_stable") is True else ""))
        if scroll_edge_id:
            working, added_edge = _remember(working, "known_edge_ids", scroll_edge_id, policy)
            new_edge = new_edge or added_edge
            if added_edge:
                reasons.append("NEW_VERIFIED_EDGE")

    local_id = _text(production.get("local_progress_id"))
    local_verified = production.get("local_progress_verified") is True
    local_progress = production.get("local_progress") is True or local_verified
    new_local = False
    if local_verified and local_id:
        working, new_local = _remember(working, "known_local_progress_ids", local_id, policy)
        local_progress = new_local
        if new_local:
            reasons.append("NEW_LOCAL_PROGRESS")
    if local_progress:
        kinds.add(ProgressKind.LOCAL_PROGRESS)

    if knowledge_progress:
        kinds.add(ProgressKind.KNOWLEDGE_PROGRESS)

    run_progress = new_visit or new_state or new_frontier_added or new_edge or new_viewport
    state_progress = run_progress or new_local or knowledge_progress
    if run_progress:
        kinds.add(ProgressKind.EXPLORATION_PROGRESS)
    if not kinds:
        kinds.add(ProgressKind.NO_MEANINGFUL_PROGRESS)
    if kinds == {ProgressKind.CURSOR_PROGRESS}:
        reasons.append("CURSOR_ONLY_PROGRESS")

    # Actual visits remain production-authoritative; evaluator novelty never
    # changes visit ledgers. Unknown/label/snapshot churn cannot reset ages.
    old_run_age = history.run_plateau_age
    run_age = 0 if run_progress else old_run_age + 1
    last_run_step = decision_step if run_progress else history.last_run_meaningful_progress_step

    state_age: int | None = None
    state_last_step: int | None = None
    if state_fresh and state_id:
        records = {row.state_id: row for row in working.state_plateaus}
        prior = records.get(state_id, StatePlateau(state_id))
        state_age = 0 if state_progress else prior.age + 1
        state_last_step = decision_step if state_progress else prior.last_meaningful_progress_step
        records[state_id] = StatePlateau(state_id, state_age, state_last_step)
        working = replace(working, state_plateaus=tuple(records[key] for key in sorted(records)))

    # A recovery attempt is attributed to stable evidence identity, never to
    # request ID, observation ID, labels, or timestamps.
    attempted_key = _text(production.get("recovery_attempted_evidence_key"))
    if attempted_key:
        working, _ = _remember(working, "recovery_attempted_evidence_ids", attempted_key, policy)

    # Store latest frontier classifications as sorted immutable pairs.
    if frontier_fresh and frontier.get("truncated") is not True and not working.truncated:
        bounded_statuses = dict(history.frontier_statuses)
        for frontier_id, status in previous_status.items():
            if frontier_id not in bounded_statuses and len(bounded_statuses) >= policy.max_history_items:
                working = replace(working, truncated=True)
                break
            bounded_statuses[frontier_id] = status
        if not working.truncated:
            working = replace(working, frontier_statuses=tuple(sorted(bounded_statuses.items())))

    working = replace(
        working,
        last_decision_watermark=watermark,
        last_decision_id=decision_id,
        closed_decision_count=working.closed_decision_count + 1,
        run_plateau_age=run_age,
        last_run_meaningful_progress_step=last_run_step,
    )
    return (working, tuple(sorted(kinds, key=lambda item: item.value)), tuple(sorted(set(reasons))),
            state_age, run_age, state_last_step, last_run_step)


def _make_evaluation(*, decision: ExplorationDecision, reasons: list[str],
                     progress_types: tuple[ProgressKind, ...], state_id: str | None,
                     scope: str, decision_id: str | None, step: int | None, watermark: int | None,
                     exhausted: str, evidence_complete: bool, counts: Mapping[str, int],
                     state_age: int | None, run_age: int, state_threshold: int, run_threshold: int,
                     state_last_step: int | None, run_last_step: int | None,
                     legacy_repeat_reason: str | None, scroll: Mapping[str, Any],
                     hard_bounds: Mapping[str, Any], safety: Mapping[str, Any],
                     metrics: Mapping[str, int], history: ExplorationHistory) -> ExplorationEvaluation:
    plateau = bool((state_age is not None and state_age >= state_threshold)
                   or run_age >= run_threshold)
    return ExplorationEvaluation(
        decision=decision,
        reason_codes=tuple(dict.fromkeys(reasons)),
        progress_types=progress_types,
        state_id=state_id,
        scope=scope,
        decision_id=decision_id,
        decision_step=step,
        input_watermark=watermark,
        frontier_exhausted=exhausted,
        evidence_complete=evidence_complete,
        eligible_count=counts["eligible_count"],
        unknown_count=counts["unknown_count"],
        never_attempted_count=counts["never_attempted_count"],
        retryable_count=counts["retryable_count"],
        revisit_only_count=counts["revisit_only_count"],
        policy_limited_count=counts["policy_limited_count"],
        state_plateau_age=state_age,
        run_plateau_age=run_age,
        state_plateau_threshold=state_threshold,
        run_plateau_threshold=run_threshold,
        state_last_meaningful_progress_step=state_last_step,
        run_last_meaningful_progress_step=run_last_step,
        plateau_established=plateau,
        legacy_repeat_reason=legacy_repeat_reason,
        scroll_evidence_summary=_safe_scalar_summary(
            scroll, ("status", "scroll_status", "scope", "scope_state_id", "scroll_obligation",
                     "evidence_watermark", "evidence_stage")),
        hard_bound_summary=_safe_scalar_summary(
            hard_bounds, ("kind", "limit_kind", "usage", "limit_value", "reached", "absolute", "hard")),
        safety_summary=_safe_scalar_summary(
            safety, ("status", "authoritative", "required_action_denied", "safe_alternative_available",
                     "reason_code")),
        metrics_delta=tuple(sorted(metrics.items())),
        proposed_history=history,
    )


def evaluate_exploration_progress(*, current_state: Mapping[str, Any],
                                  progress_history: ExplorationHistory | None,
                                  frontier_evaluation: Mapping[str, Any],
                                  production_result: Mapping[str, Any],
                                  repetition_state: Mapping[str, Any] | None = None,
                                  scroll_evidence: Mapping[str, Any] | None = None,
                                  safety_state: Mapping[str, Any] | None = None,
                                  hard_bounds: Mapping[str, Any] | None = None,
                                  recovery_budget: Mapping[str, Any] | None = None,
                                  policy: ExplorationPolicy | Mapping[str, Any] | None = None
                                  ) -> ExplorationEvaluation:
    """Evaluate one closed decision without performing side effects.

    ``production_result`` must provide ``decision_id``, monotonically increasing
    ``decision_watermark``, ``decision_step``, ``decision_closed=True`` and a
    post-action decision stage. ``current_state``, ``frontier_evaluation`` and
    scroll evidence used to grant novelty or completion must carry that same
    watermark and an accepted post-action stage. A recovery budget is explicit
    and is never decremented here.
    """
    if not isinstance(current_state, Mapping) or not isinstance(production_result, Mapping):
        raise TypeError("current_state and production_result must be mappings")
    if not isinstance(frontier_evaluation, Mapping):
        raise TypeError("frontier_evaluation must be a mapping")
    history = progress_history or ExplorationHistory()
    if not isinstance(history, ExplorationHistory):
        raise TypeError("progress_history must be ExplorationHistory or None")
    policy_value = _policy(policy)
    production = dict(production_result)
    current = dict(current_state)
    frontier = dict(frontier_evaluation)
    repetition = dict(repetition_state or {})
    scroll = dict(scroll_evidence or {})
    safety = dict(safety_state or {})
    bounds = dict(hard_bounds or {})
    recovery = dict(recovery_budget or {})

    decision_id, step, watermark, valid_closed = _decision_identity(production)
    duplicate = bool(decision_id and decision_id in history.processed_decision_ids)
    stale = bool(watermark is not None and watermark <= history.last_decision_watermark)
    fresh_closed = valid_closed and not duplicate and not stale
    if duplicate:
        stale_reason = "DUPLICATE_DECISION_IGNORED"
    elif stale:
        stale_reason = "STALE_DECISION_IGNORED"
    elif not valid_closed:
        stale_reason = "CLOSED_DECISION_WATERMARK_REQUIRED"
    else:
        stale_reason = ""

    state_fresh = bool(fresh_closed and _aligned(current, watermark=watermark, decision_id=decision_id))
    resolved_state_id = _state_id(current, aligned=state_fresh)
    frontier_fresh = bool(fresh_closed and _aligned(frontier, watermark=watermark,
                                                     decision_id=decision_id))
    frontier_state_matches = (not resolved_state_id or not _text(frontier.get("state_id"))
                              or _text(frontier.get("state_id")) == resolved_state_id)
    frontier_fresh = frontier_fresh and state_fresh and bool(resolved_state_id) and frontier_state_matches
    scroll_fresh = bool(fresh_closed and _aligned(scroll, watermark=watermark,
                                                   decision_id=decision_id))
    repetition_fresh = bool(fresh_closed and (not _evidence_watermark(repetition)
                                               or _evidence_watermark(repetition) == watermark)
                             and (not _text(repetition.get("decision_id"))
                                  or _text(repetition.get("decision_id")) == decision_id))
    counts = _frontier_counts(frontier)
    items, duplicate_frontier_conflicts = _frontier_items(frontier, current_state_id=resolved_state_id)
    item_counts = {
        "eligible_count": sum(_upper(item.get("status")) == "ELIGIBLE" for item in items),
        "unknown_count": sum(_upper(item.get("status")) == "UNKNOWN" for item in items),
        "blocked_count": sum(_upper(item.get("status")) == "BLOCKED" for item in items),
        "policy_limited_count": sum(
            _upper(item.get("status")) == "EXHAUSTED"
            and _upper(item.get("exhaustion_basis")) == "POLICY_LIMIT" for item in items),
    }
    for key, item_count in item_counts.items():
        counts[key] = max(counts[key], item_count)
    counts["unknown_count"] = max(counts["unknown_count"], duplicate_frontier_conflicts)
    frontier_status = _upper(frontier.get("frontier_exhausted")) if frontier_fresh else "UNKNOWN"
    if frontier_status not in {"YES", "NO", "UNKNOWN"}:
        frontier_status = "UNKNOWN"
    frontier_scope = _upper(frontier.get("exhaustion_scope"))
    frontier_scope_compatible = (
        frontier_scope == policy_value.scope
        if policy_value.scope == CURRENT_SCOPE
        else frontier_scope in {CURRENT_SCOPE, policy_value.scope}
    )
    frontier_fresh = frontier_fresh and frontier_scope_compatible
    if not frontier_fresh:
        frontier_status = "UNKNOWN"
    evidence_complete = bool(frontier_fresh and frontier.get("evidence_complete") is True
                             and frontier.get("history_complete") is not False
                             and frontier.get("inventory_complete") is not False
                             and frontier.get("truncated") is not True
                             and counts["unknown_count"] == 0
                             and counts["eligible_count"] == 0)
    evidence_truncated = bool(history.truncated
                              or current.get("identity_history_truncated") is True
                              or current.get("state_history_truncated") is True
                              or frontier.get("truncated") is True
                              or frontier.get("history_complete") is False
                              or frontier.get("inventory_complete") is False)

    legacy_reason = None
    if repetition_fresh:
        legacy_reason = (_text(repetition.get("legacy_stop_reason"))
                         or _text(repetition.get("stop_reason"))
                         or None)
    recovery_key = _recovery_key(frontier, items, resolved_state_id)

    if fresh_closed:
        proposed_history, kinds, progress_reasons, state_age, run_age, state_last_step, run_last_step = (
            _transition_history(
                history=history, policy=policy_value, decision_id=decision_id, decision_step=step,
                watermark=watermark, state_id=resolved_state_id, state_fresh=state_fresh,
                current_state=current, frontier=frontier, frontier_fresh=frontier_fresh,
                frontier_items=items, scroll=scroll, scroll_fresh=scroll_fresh,
                production=production,
            )
        )
    else:
        proposed_history = history
        kinds = (ProgressKind.NO_MEANINGFUL_PROGRESS,)
        progress_reasons = ()
        previous_state = history.state_plateau(resolved_state_id)
        state_age = previous_state.age if previous_state else None
        run_age = history.run_plateau_age
        state_last_step = previous_state.last_meaningful_progress_step if previous_state else None
        run_last_step = history.last_run_meaningful_progress_step

    state_plateau = state_age is not None and state_age >= policy_value.state_plateau_threshold
    run_plateau = run_age >= policy_value.run_plateau_threshold
    plateau = state_plateau or run_plateau
    legacy_cycle = legacy_reason in {"repeat_no_progress", "bounded_two_card_loop", "repeat_semantic_stall"}
    if plateau:
        progress_reasons = (*progress_reasons, "STATE_PLATEAU" if state_plateau else "RUN_PLATEAU")
    if legacy_cycle and repetition_fresh:
        progress_reasons = (*progress_reasons, "LEGACY_REPEAT_SIGNAL_INPUT_ONLY")

    # Structured diagnostic deltas are observations only; no production metric
    # or attempt/visit counter is modified by this function.
    metrics = {
        "MEANINGFUL_PROGRESS_COUNT": int(ProgressKind.EXPLORATION_PROGRESS in kinds),
        "CURSOR_ONLY_PROGRESS_COUNT": int(kinds == (ProgressKind.CURSOR_PROGRESS,)),
        "REVISIT_WITH_FRONTIER_AVAILABLE_COUNT": int(
            ProgressKind.CURSOR_PROGRESS in kinds and frontier_status == "NO"
            and counts["eligible_count"] > 0
            and ProgressKind.EXPLORATION_PROGRESS not in kinds
            and ProgressKind.KNOWLEDGE_PROGRESS not in kinds
            and ProgressKind.LOCAL_PROGRESS not in kinds),
        "PLATEAU_ENTRY_COUNT": 0,
        "PLATEAU_EXIT_COUNT": 0,
        "SHADOW_REDIRECT_RECOMMENDATION_COUNT": 0,
        "SHADOW_TERMINATE_RECOMMENDATION_COUNT": 0,
    }
    previous_state_record = history.state_plateau(resolved_state_id)
    previously_plateaued = bool(
        (previous_state_record and previous_state_record.age >= policy_value.state_plateau_threshold)
        or history.run_plateau_age >= policy_value.run_plateau_threshold
    )
    if not previously_plateaued and plateau:
        metrics["PLATEAU_ENTRY_COUNT"] = 1
    elif previously_plateaued and not plateau:
        metrics["PLATEAU_EXIT_COUNT"] = 1

    scroll_absent, scroll_not_applicable, scroll_obligation = _scroll_proof(
        scroll, aligned=scroll_fresh, scope=policy_value.scope, state_id=resolved_state_id)
    deferred_scroll = counts["deferred_scroll_count"] > 0
    eligible_items = [item for item in items if _frontier_identifier(item)]
    eligible_items.sort(key=lambda item: (
        _PRIORITY_ORDER.get(_upper(item.get("priority_class", item.get("priority"))), 99),
        _text(item.get("frontier_id")),
    ))
    redirectable = bool(eligible_items)
    policy_only = bool(counts["policy_limited_count"] > 0 and counts["eligible_count"] == 0
                       and frontier_status != "NO")
    blocked_items = [item for item in items if _upper(item.get("status")) == "BLOCKED"]
    temporary_blocked = any(_text(item.get("blocked_reason")) not in _TERMINAL_BLOCKED_REASONS
                            for item in blocked_items)
    safety_watermark = _evidence_watermark(safety)
    bounds_watermark = _evidence_watermark(bounds)
    safety_aligned = safety_watermark is None or safety_watermark == watermark
    bounds_aligned = bounds_watermark is None or bounds_watermark == watermark
    if not safety_aligned:
        safety = {}
    if not bounds_aligned:
        bounds = {}
    safety_unknown = (_upper(safety.get("status")) in {"UNKNOWN", "UNVERIFIED"}
                      and safety.get("required_action") is True)

    error = _error_code(production) if fresh_closed else None
    if error:
        decision = ExplorationDecision.TERMINATE_ERROR
        reasons = ["ERROR_STOP", error]
    elif fresh_closed and _safety_denial(safety):
        decision = ExplorationDecision.TERMINATE_SAFETY_LIMIT
        reasons = ["SAFETY_LIMIT"]
    elif _hard_bound(bounds):
        decision = ExplorationDecision.TERMINATE_HARD_BOUND
        reasons = ["HARD_BOUND_REACHED"]
    elif not fresh_closed:
        if _safety_denial(safety):
            decision = ExplorationDecision.TERMINATE_SAFETY_LIMIT
            reasons = ["SAFETY_LIMIT"]
        elif _recovery_available(recovery, history, recovery_key):
            decision = ExplorationDecision.RECOVER_EVIDENCE
            reasons = [stale_reason, "RECOVERY_AVAILABLE"]
            if fresh_closed:
                proposed_history, _ = _remember(
                    proposed_history, "recovery_recommended_evidence_ids", recovery_key, policy_value)
        else:
            decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
            reasons = [stale_reason or "DECISION_EVIDENCE_UNAVAILABLE"]
    elif safety_unknown:
        if _recovery_available(recovery, proposed_history, recovery_key):
            decision = ExplorationDecision.RECOVER_EVIDENCE
            reasons = ["SAFETY_EVIDENCE_UNKNOWN", "RECOVERY_AVAILABLE"]
            proposed_history, _ = _remember(
                proposed_history, "recovery_recommended_evidence_ids", recovery_key, policy_value)
        else:
            decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
            reasons = ["SAFETY_EVIDENCE_UNKNOWN", "RECOVERY_BUDGET_EXHAUSTED"]
    elif (ProgressKind.EXPLORATION_PROGRESS in kinds
          or ProgressKind.KNOWLEDGE_PROGRESS in kinds
          or "NEW_LOCAL_PROGRESS" in progress_reasons):
        decision = ExplorationDecision.CONTINUE
        reasons = list(progress_reasons) or ["MEANINGFUL_PROGRESS"]
    elif frontier_status == "NO":
        if counts["eligible_count"] > 0 and redirectable:
            if plateau:
                decision = ExplorationDecision.REDIRECT_FRONTIER
                reasons = ["FRONTIER_REMAINS", "PLATEAU_REDIRECT_RECOMMENDED"]
                metrics["SHADOW_REDIRECT_RECOMMENDATION_COUNT"] = 1
            else:
                decision = ExplorationDecision.CONTINUE
                reasons = ["FRONTIER_REMAINS", "PLATEAU_THRESHOLD_NOT_REACHED"]
        elif counts["eligible_count"] > 0:
            decision = (ExplorationDecision.TERMINATE_INCOMPLETE_NO_PROGRESS if plateau
                        else ExplorationDecision.CONTINUE)
            reasons = ["FRONTIER_REMAINS_WITHOUT_SAFE_REDIRECT_ID"]
        elif evidence_truncated:
            if _recovery_available(recovery, proposed_history, recovery_key):
                decision = ExplorationDecision.RECOVER_EVIDENCE
                reasons = ["FRONTIER_HISTORY_TRUNCATED", "RECOVERY_AVAILABLE"]
                proposed_history, _ = _remember(
                    proposed_history, "recovery_recommended_evidence_ids", recovery_key, policy_value)
            else:
                decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
                reasons = ["FRONTIER_HISTORY_TRUNCATED", "RECOVERY_BUDGET_EXHAUSTED"]
        else:
            if _recovery_available(recovery, proposed_history, recovery_key):
                decision = ExplorationDecision.RECOVER_EVIDENCE
                reasons = ["FRONTIER_COUNT_CONTRADICTION", "RECOVERY_AVAILABLE"]
                proposed_history, _ = _remember(
                    proposed_history, "recovery_recommended_evidence_ids", recovery_key, policy_value)
            else:
                decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
                reasons = ["FRONTIER_COUNT_CONTRADICTION"]
    elif evidence_truncated:
        if _recovery_available(recovery, proposed_history, recovery_key):
            decision = ExplorationDecision.RECOVER_EVIDENCE
            reasons = ["FRONTIER_HISTORY_TRUNCATED", "RECOVERY_AVAILABLE"]
            proposed_history, _ = _remember(
                proposed_history, "recovery_recommended_evidence_ids", recovery_key, policy_value)
        else:
            decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
            reasons = ["FRONTIER_HISTORY_TRUNCATED", "RECOVERY_BUDGET_EXHAUSTED"]
    elif policy_only:
        decision = ExplorationDecision.TERMINATE_INCOMPLETE_POLICY_LIMIT
        reasons = ["POLICY_LIMIT_ONLY"]
    elif (frontier_status == "UNKNOWN" or not frontier_fresh or not evidence_complete
          or counts["unknown_count"] > 0 or temporary_blocked):
        if _recovery_available(recovery, proposed_history, recovery_key):
            decision = ExplorationDecision.RECOVER_EVIDENCE
            reasons = ["FRONTIER_UNKNOWN", "RECOVERY_AVAILABLE"]
            proposed_history, _ = _remember(
                proposed_history, "recovery_recommended_evidence_ids", recovery_key, policy_value)
        elif scroll_obligation or deferred_scroll:
            decision = ExplorationDecision.CHECK_SCROLL
            reasons = ["FRONTIER_UNKNOWN", "SCROLL_CHECK_REQUIRED"]
        else:
            decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
            reasons = ["FRONTIER_UNKNOWN", "RECOVERY_BUDGET_EXHAUSTED"]
    elif frontier_status == "YES":
        if policy_only:
            decision = ExplorationDecision.TERMINATE_INCOMPLETE_POLICY_LIMIT
            reasons = ["POLICY_LIMIT_ONLY"]
        elif temporary_blocked:
            decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
            reasons = ["TEMPORARY_BLOCKED_FRONTIER_REMAINS"]
        elif not (scroll_absent or scroll_not_applicable):
            decision = ExplorationDecision.CHECK_SCROLL if (scroll_obligation or deferred_scroll) else (
                ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN)
            reasons = ["SCROLL_CHECK_REQUIRED"] if decision == ExplorationDecision.CHECK_SCROLL else [
                "SCROLL_ABSENCE_NOT_PROVEN_FOR_SCOPE"]
        elif policy_value.scope != CURRENT_SCOPE:
            scope_proof = _plain_mapping(frontier.get("scope_completion_proof"))
            proof_ok = (_aligned(scope_proof, watermark=watermark, decision_id=decision_id)
                        and _upper(scope_proof.get("scope")) == policy_value.scope
                        and scope_proof.get("complete") is True)
            if proof_ok:
                decision = ExplorationDecision.COMPLETE_CURRENT_SCOPE
                reasons = ["DECLARED_SCOPE_EXHAUSTED"]
            else:
                decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
                reasons = ["HIGHER_SCOPE_COMPLETION_NOT_PROVEN"]
        else:
            decision = ExplorationDecision.COMPLETE_CURRENT_SCOPE
            reasons = ["FOCUS_SCOPE_EXHAUSTED"]
    elif scroll_obligation or deferred_scroll:
        decision = ExplorationDecision.CHECK_SCROLL
        reasons = ["SCROLL_CHECK_REQUIRED"]
    elif plateau and legacy_cycle:
        decision = ExplorationDecision.TERMINATE_INCOMPLETE_NO_PROGRESS
        reasons = ["STATE_OR_RUN_PLATEAU", "LEGACY_REPEAT_SIGNAL_INPUT_ONLY"]
    else:
        decision = ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN
        reasons = ["FRONTIER_DECISION_UNRESOLVED"]

    if decision in {
        ExplorationDecision.TERMINATE_INCOMPLETE_POLICY_LIMIT,
        ExplorationDecision.TERMINATE_INCOMPLETE_UNKNOWN,
        ExplorationDecision.TERMINATE_INCOMPLETE_NO_PROGRESS,
        ExplorationDecision.TERMINATE_HARD_BOUND,
        ExplorationDecision.TERMINATE_SAFETY_LIMIT,
        ExplorationDecision.TERMINATE_ERROR,
    }:
        metrics["SHADOW_TERMINATE_RECOMMENDATION_COUNT"] = 1

    if decision == ExplorationDecision.RECOVER_EVIDENCE and fresh_closed:
        proposed_history, _ = _remember(
            proposed_history, "recovery_recommended_evidence_ids", recovery_key, policy_value)

    if not state_fresh:
        state_id_for_audit = _text(current.get("state_id")) or None
    else:
        state_id_for_audit = resolved_state_id
    final_evidence_complete = bool(evidence_complete and not evidence_truncated)
    return _make_evaluation(
        decision=decision, reasons=[*progress_reasons, *reasons], progress_types=kinds,
        state_id=state_id_for_audit, scope=policy_value.scope, decision_id=decision_id,
        step=step, watermark=watermark, exhausted=frontier_status,
        evidence_complete=final_evidence_complete, counts=counts, state_age=state_age,
        run_age=run_age, state_threshold=policy_value.state_plateau_threshold,
        run_threshold=policy_value.run_plateau_threshold,
        state_last_step=state_last_step, run_last_step=run_last_step,
        legacy_repeat_reason=legacy_reason,
        scroll=scroll, hard_bounds=bounds, safety=safety, metrics=metrics,
        history=proposed_history,
    )


__all__ = [
    "CURRENT_SCOPE", "PLATEAU_SCHEMA_VERSION", "ExplorationDecision", "ExplorationEvaluation",
    "ExplorationHistory", "ExplorationPolicy", "ProgressKind", "StatePlateau",
    "evaluate_exploration_progress", "history_to_dict",
]
