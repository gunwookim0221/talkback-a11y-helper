"""Pure, bounded Phase 6C1 frontier policy.

The core consumes normalized state, candidate, planner, safety, and production
history evidence. It performs no I/O, dispatch, graph mutation, ledger update,
or visit crediting. Its recommendation is diagnostic only.

History input contract:
``attempt_events`` contain state_id, frontier_id, action_type,
target_instance_id, attempted, and ownership_status. ``visit_events`` contain
state_id, target_instance_id, production_authority,
accessibility_focus_confirmed, focus_transition_status, and
visit_record_status. ``exploration_events`` contain state/frontier/action/
target identity, production_authority, and exploration_status. Missing or
malformed authoritative history makes the result incomplete.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
from typing import Any, Mapping, Sequence

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.state_graph import EdgeType


FRONTIER_SCHEMA_VERSION = "phase6-frontier-evaluation.v1"
FRONTIER_IDENTITY_VERSION = "phase6-frontier-identity.v1"
EXHAUSTION_SCOPE = "CURRENT_STATE_CANDIDATE_FOCUS"
MAX_FRONTIER_ITEMS = 512
MAX_HISTORY_EVENTS = 16_384
MAX_REASON_CODES = 24
MAX_ID_LENGTH = 4_096
MAX_CANDIDATE_ID_LENGTH = 512
MAX_ORDER_KEY_LENGTH = 32
MAX_ORDER_STRING_LENGTH = 256
MAX_EVENT_BYTES = 65_536


class FrontierStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EXPLORED = "EXPLORED"
    BLOCKED = "BLOCKED"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"
    EXHAUSTED = "EXHAUSTED"


class PriorityTier(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ExhaustionResult(str, Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


_EDGE_ALIASES = {
    "FOCUS_TARGET": EdgeType.TARGETED_FOCUS.value,
    "TARGETED_FOCUS": EdgeType.TARGETED_FOCUS.value,
    "FOCUS_NEXT": EdgeType.FOCUS_NEXT.value,
    "FOCUS_PREVIOUS": EdgeType.FOCUS_PREVIOUS.value,
    "SAFE_ACTIVATION": EdgeType.SAFE_ACTIVATION.value,
    "CLICK": EdgeType.SAFE_ACTIVATION.value,
    "TAB_CHANGE": EdgeType.TAB_CHANGE.value,
    "BOTTOM_NAV": EdgeType.TAB_CHANGE.value,
    "BACK": EdgeType.BACK.value,
    "RECOVERY": EdgeType.RECOVERY.value,
    "SCROLL_FORWARD": EdgeType.SCROLL_FORWARD.value,
    "SCROLL_FORWARD_VERTICAL": EdgeType.SCROLL_FORWARD.value,
    "SCROLL_BACKWARD": EdgeType.SCROLL_BACKWARD.value,
    "SCROLL_BACKWARD_VERTICAL": EdgeType.SCROLL_BACKWARD.value,
    "OTHER": EdgeType.OTHER.value,
}
_SUPPORTED_EDGE_TYPES = {item.value for item in EdgeType}
_SCROLL_EDGE_TYPES = {EdgeType.SCROLL_FORWARD.value, EdgeType.SCROLL_BACKWARD.value}
_FOCUS_EDGE_TYPES = {EdgeType.FOCUS_NEXT.value, EdgeType.TARGETED_FOCUS.value}
_TERMINAL_BLOCKED_REASONS = {"CURRENT_FOCUS_NO_NEW_OPPORTUNITY"}
_MEANINGFUL_CHANGE_DIMENSIONS = {
    "planner_eligibility", "target_binding", "target_presence", "action_safety",
    "verified_substate", "verified_context", "verified_viewport", "recovery_precondition",
}
_ACK_VALUES = {"ACKED", "SUCCESS", "FAILED", "FAILURE", "TIMEOUT", "UNKNOWN"}


@dataclass(frozen=True)
class FrontierPolicy:
    """Passive resource bounds; per-opportunity attempts cannot exceed two."""

    max_attempts_per_opportunity: int = 2
    max_frontier_items: int = MAX_FRONTIER_ITEMS
    max_history_events: int = MAX_HISTORY_EVENTS

    def __post_init__(self) -> None:
        if type(self.max_attempts_per_opportunity) is not int or not 1 <= self.max_attempts_per_opportunity <= 2:
            raise ValueError("max_attempts_per_opportunity must be 1 or 2")
        if type(self.max_frontier_items) is not int or not 1 <= self.max_frontier_items <= MAX_FRONTIER_ITEMS:
            raise ValueError(f"max_frontier_items must be 1..{MAX_FRONTIER_ITEMS}")
        if type(self.max_history_events) is not int or not 1 <= self.max_history_events <= MAX_HISTORY_EVENTS:
            raise ValueError(f"max_history_events must be 1..{MAX_HISTORY_EVENTS}")


@dataclass(frozen=True)
class FrontierItem:
    """Immutable item view; callers receive detached JSON data."""

    _document_json: str

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._document_json)

    def to_json(self) -> str:
        return self._document_json


@dataclass(frozen=True)
class FrontierEvaluation:
    """Immutable deterministic evaluation result."""

    _document_json: str

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._document_json)

    def to_json(self) -> str:
        return self._document_json

    @property
    def frontier_items(self) -> tuple[FrontierItem, ...]:
        return tuple(FrontierItem(canonical_json(item)) for item in self.to_dict()["frontier_items"])


def _text(value: Any, limit: int = MAX_ID_LENGTH) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if value and len(value) <= limit else ""


def _sorted_reasons(*values: Any) -> list[str]:
    reasons: set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            reasons.add(value.strip().upper()[:256])
        elif isinstance(value, (list, tuple, set, frozenset)):
            reasons.update(str(item).strip().upper()[:256] for item in value if str(item).strip())
    return sorted(reasons)[:MAX_REASON_CODES]


def _edge_type(candidate: Mapping[str, Any]) -> str:
    raw = _text(candidate.get("edge_type") or candidate.get("action_kind") or candidate.get("action_type"), 128).upper()
    return _EDGE_ALIASES.get(raw, raw)


def _state_id(state: Mapping[str, Any]) -> str:
    value = _text(state.get("state_id"))
    if not value or state.get("resolved") is False:
        return ""
    if _text(state.get("identity_status"), 64).upper() in {"UNRESOLVED", "UNKNOWN", "INVALID"}:
        return ""
    return value


def _target_identity(candidate: Mapping[str, Any], edge_type: str,
                     focus_cursor: Mapping[str, Any] | None) -> tuple[str, dict[str, str], str]:
    if edge_type == EdgeType.FOCUS_NEXT.value:
        cursor = focus_cursor if isinstance(focus_cursor, Mapping) else {}
        instance = _text(cursor.get("instance_id"))
        if cursor.get("confirmed") is True and instance:
            return instance, {"source_cursor_instance_id": instance, "direction": "NEXT"}, "RESOLVED"
        return "", {}, "UNRESOLVED"
    raw = candidate.get("target_identity")
    if not isinstance(raw, Mapping):
        return "", {}, "UNRESOLVED"
    # Only an identity issued by the existing production identity/reconciliation
    # path is accepted. Labels, coordinates, XML indices, and generated UUIDs
    # cannot be promoted into a production instance identity here.
    instance = _text(raw.get("instance_id") or raw.get("production_instance_id")
                     or raw.get("candidate_instance_id"))
    return (instance, {"instance_id": instance}, "RESOLVED") if instance else ("", {}, "UNRESOLVED")


def build_frontier_id(state_id: str, edge_type: str,
                      target_identity: Mapping[str, Any] | str) -> str:
    """Hash the versioned state/edge/existing production target identity."""
    normalized_state = _text(state_id)
    normalized_edge = _text(edge_type, 128).upper()
    if not normalized_state or normalized_edge not in _SUPPORTED_EDGE_TYPES:
        raise ValueError("frontier identity requires a resolved state and supported edge type")
    if isinstance(target_identity, str):
        target: Any = {"instance_id": _text(target_identity)}
    elif isinstance(target_identity, Mapping):
        target = dict(target_identity)
    else:
        raise TypeError("target_identity must be a mapping or existing identity string")
    if not target:
        raise ValueError("frontier identity requires an existing target or edge identity")
    return "frontier_" + canonical_sha256({
        "schema_version": FRONTIER_IDENTITY_VERSION,
        "state_id": normalized_state,
        "edge_type": normalized_edge,
        "target_identity": target,
    })


def _unresolved_frontier_id(state_id: str, edge_type: str, candidate_id: str) -> str:
    # Diagnostic placeholder only. It is explicitly marked provisional and is
    # never eligible or used for production-history attribution.
    return "frontier_unresolved_" + canonical_sha256({
        "schema_version": FRONTIER_IDENTITY_VERSION,
        "state_id": state_id or "UNRESOLVED_STATE",
        "edge_type": edge_type or "UNKNOWN_EDGE",
        "candidate_id": candidate_id,
    })


def _resolve_alias(instance: str, aliases: Mapping[str, Any]) -> tuple[str, bool]:
    current = instance
    seen: set[str] = set()
    for _ in range(len(aliases) + 1):
        if current not in aliases:
            return current, True
        if current in seen:
            return instance, False
        seen.add(current)
        successor = _text(aliases.get(current))
        if not successor:
            return instance, False
        current = successor
    return instance, False


def _lookup_evidence(container: Mapping[str, Any], candidate_id: str,
                     frontier_id: str) -> tuple[Mapping[str, Any] | None, bool]:
    present = [container[key] for key in (candidate_id, frontier_id) if key and key in container]
    if not present:
        return None, False
    if any(not isinstance(item, Mapping) for item in present):
        return None, True
    try:
        signatures = {canonical_json(dict(item)) for item in present}
    except (TypeError, ValueError):
        return None, True
    if len(signatures) != 1:
        return None, True
    return present[0], False


def _evidence_scope_matches(record: Mapping[str, Any], *, state_id: str,
                            edge_type: str, target_instance_id: str) -> bool:
    raw_types = [_text(record.get(key), 128).upper()
                 for key in ("edge_type", "action_type") if _text(record.get(key), 128)]
    normalized_types = [_EDGE_ALIASES.get(value, value) for value in raw_types]
    target = _text(record.get("target_instance_id") or record.get("instance_id"))
    return (_text(record.get("state_id")) == state_id
            and bool(normalized_types) and all(value == edge_type for value in normalized_types)
            and target == target_instance_id)


def _history_target_matches(event: Mapping[str, Any], *, state_id: str,
                            action_type: str, target_instance_id: str,
                            aliases: Mapping[str, Any]) -> tuple[bool, str]:
    if (_text(event.get("state_id")) != state_id
            or _text(event.get("action_type") or event.get("edge_type"), 128).upper()
            not in {action_type, _EDGE_ALIASES.get(_text(event.get("action_type") or event.get("edge_type"), 128).upper(), "")}):
        return False, ""
    event_instance = _text(event.get("target_instance_id") or event.get("instance_id"))
    if not event_instance:
        return False, ""
    canonical, valid = _resolve_alias(event_instance, aliases)
    return valid and canonical == target_instance_id, event_instance


def _event_matches(event: Mapping[str, Any], *, state_id: str, frontier_id: str,
                   edge_type: str, action_type: str, target_instance_id: str,
                   aliases: Mapping[str, Any]) -> tuple[bool, bool]:
    """Return (exactly associated, ambiguous plausible association)."""
    target_match, event_instance = _history_target_matches(
        event, state_id=state_id, action_type=action_type,
        target_instance_id=target_instance_id, aliases=aliases,
    )
    if not target_match:
        return False, False
    recorded_frontier = _text(event.get("frontier_id"))
    if recorded_frontier == frontier_id:
        associated = True
    else:
        # Permit history transfer only when the event's original frontier hash
        # matches its original instance and that instance has a validated alias.
        try:
            old_frontier = build_frontier_id(state_id, edge_type, event_instance)
        except (TypeError, ValueError):
            old_frontier = ""
        associated = bool(event_instance in aliases and recorded_frontier == old_frontier)
    if not associated:
        return False, True
    return event.get("ownership_status") == "EXACT_MATCH", event.get("ownership_status") != "EXACT_MATCH"


def _valid_history_events(history: Mapping[str, Any], policy: FrontierPolicy
                          ) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]], bool, bool]:
    names = ("attempt_events", "visit_events", "exploration_events")
    raw = [history.get(name) for name in names]
    if any(not isinstance(value, (list, tuple)) for value in raw):
        return [], [], [], False, False
    total = sum(len(value) for value in raw)
    if total > policy.max_history_events:
        return [], [], [], False, True
    if any(not isinstance(event, Mapping) for value in raw for event in value):
        return [], [], [], False, False
    malformed = False
    arrays: list[list[Mapping[str, Any]]] = []
    for index, value in enumerate(raw):
        events = list(value)
        for event in events:
            try:
                if len(canonical_json(dict(event)).encode("utf-8")) > MAX_EVENT_BYTES:
                    malformed = True
            except (TypeError, ValueError):
                malformed = True
            if index == 0 and event.get("attempted") is True:
                required = (_text(event.get("state_id")), _text(event.get("frontier_id")),
                            _text(event.get("action_type") or event.get("edge_type"), 128),
                            _text(event.get("target_instance_id") or event.get("instance_id")),
                            _text(event.get("ownership_status"), 64))
                malformed |= not all(required)
            elif index == 1 and event.get("production_authority") is True:
                required = (_text(event.get("state_id")),
                            _text(event.get("target_instance_id") or event.get("instance_id")),
                            _text(event.get("focus_transition_status"), 64),
                            _text(event.get("visit_record_status"), 64))
                malformed |= not all(required)
            elif index == 2 and event.get("production_authority") is True:
                required = (_text(event.get("state_id")), _text(event.get("frontier_id")),
                            _text(event.get("action_type") or event.get("edge_type"), 128),
                            _text(event.get("target_instance_id") or event.get("instance_id")),
                            _text(event.get("exploration_status"), 64))
                malformed |= not all(required)
        events.sort(key=lambda event: (
            event.get("step") if type(event.get("step")) is int and event.get("step") >= 0 else -1,
            canonical_json(dict(event)) if _is_canonicalizable(event) else "~INVALID",
        ))
        arrays.append(events)
    return arrays[0], arrays[1], arrays[2], history.get("complete") is True and not malformed, False


def _is_canonicalizable(value: Mapping[str, Any]) -> bool:
    try:
        canonical_json(dict(value))
        return True
    except (TypeError, ValueError):
        return False


def _stable_order_key(value: Any) -> tuple[list[Any], tuple[tuple[int, Any], ...], bool]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_ORDER_KEY_LENGTH:
        return [], (), False
    normalized: list[Any] = []
    tagged: list[tuple[int, Any]] = []
    for item in value:
        if item is None:
            normalized.append(None)
            tagged.append((0, ""))
        elif isinstance(item, bool):
            normalized.append(item)
            tagged.append((1, int(item)))
        elif isinstance(item, int):
            normalized.append(item)
            tagged.append((2, item))
        elif isinstance(item, float) and math.isfinite(item):
            normalized.append(item)
            tagged.append((2, item))
        elif isinstance(item, str) and len(item) <= MAX_ORDER_STRING_LENGTH:
            normalized.append(item)
            tagged.append((3, item))
        else:
            return [], (), False
    return normalized, tuple(tagged), True


def _candidate_condition(candidate: Mapping[str, Any], *, state_id: str,
                         target_identity: Mapping[str, str], present: Any,
                         binding: str, planner_status: str, safety_status: str) -> str:
    supplied = _text(candidate.get("condition_fingerprint"), 256)
    if supplied:
        return supplied
    return canonical_sha256({"state_id": state_id, "target_identity": dict(target_identity),
                             "currently_present": present, "binding": binding,
                             "planner_status": planner_status, "safety_status": safety_status})


def _followup_priority(planner: Mapping[str, Any], *, state_id: str,
                       frontier_id: str) -> tuple[str, str] | None:
    followup = planner.get("followup_evidence")
    if (isinstance(followup, Mapping) and followup.get("verified") is True
            and _text(followup.get("state_id")) == state_id
            and _text(followup.get("frontier_id")) == frontier_id
            and _text(followup.get("distinct_unexplored_opportunity_id"), 256)):
        return PriorityTier.P2.value, "FOLLOWUP_VALUE"
    recovery = planner.get("recovery_evidence")
    if (isinstance(recovery, Mapping) and recovery.get("verified") is True
            and recovery.get("policy_allowed") is True
            and _text(recovery.get("state_id")) == state_id
            and _text(recovery.get("frontier_id")) == frontier_id
            and _text(recovery.get("purpose"), 256)):
        return PriorityTier.P3.value, "RECOVERY_PURPOSE"
    return None


def _valid_global_visit_counts(history: Mapping[str, Any], aliases: Mapping[str, Any]
                               ) -> tuple[dict[str, int], bool]:
    raw = history.get("visits_by_instance", {})
    if not isinstance(raw, Mapping) or len(raw) > MAX_HISTORY_EVENTS:
        return {}, False
    normalized: dict[str, int] = {}
    valid = True
    for instance, count in raw.items():
        instance_id = _text(instance)
        canonical, alias_valid = _resolve_alias(instance_id, aliases) if instance_id else ("", False)
        if not instance_id or not alias_valid or type(count) is not int or count < 0:
            valid = False
            continue
        normalized[canonical] = max(normalized.get(canonical, 0), count)
    return normalized, valid


def evaluate_frontier(
    state: Mapping[str, Any],
    current_inventory: Sequence[Mapping[str, Any]],
    production_history: Mapping[str, Any],
    planner_evidence: Mapping[str, Mapping[str, Any]],
    safety_evidence: Mapping[str, Mapping[str, Any]],
    focus_cursor: Mapping[str, Any] | None = None,
    policy: FrontierPolicy | Mapping[str, Any] | None = None,
) -> FrontierEvaluation:
    """Evaluate observed opportunities without mutation or action authority."""
    if not isinstance(state, Mapping) or not isinstance(production_history, Mapping):
        raise TypeError("state and production_history must be mappings")
    if not isinstance(current_inventory, Sequence) or isinstance(current_inventory, (str, bytes)):
        raise TypeError("current_inventory must be a sequence")
    if not isinstance(planner_evidence, Mapping) or not isinstance(safety_evidence, Mapping):
        raise TypeError("planner_evidence and safety_evidence must be mappings")
    if policy is None:
        policy_value = FrontierPolicy()
    elif isinstance(policy, FrontierPolicy):
        policy_value = policy
    elif isinstance(policy, Mapping):
        policy_value = FrontierPolicy(
            max_attempts_per_opportunity=policy.get("max_attempts_per_opportunity", 2),
            max_frontier_items=policy.get("max_frontier_items", MAX_FRONTIER_ITEMS),
            max_history_events=policy.get("max_history_events", MAX_HISTORY_EVENTS),
        )
    else:
        raise TypeError("policy must be FrontierPolicy, a mapping, or None")

    resolved_state = _state_id(state)
    attempts, visits, explorations, history_complete, history_truncated = _valid_history_events(
        production_history, policy_value)
    aliases_raw = production_history.get("validated_aliases", {})
    aliases: Mapping[str, Any] = aliases_raw if isinstance(aliases_raw, Mapping) else {}
    alias_map_valid = len(aliases) <= policy_value.max_history_events
    if alias_map_valid:
        alias_map_valid = all(_text(key) and _text(value) for key, value in aliases.items())
    if alias_map_valid:
        alias_map_valid = all(_resolve_alias(_text(key), aliases)[1] for key in aliases)
    if not alias_map_valid:
        aliases = {}
    visit_counts, visit_counts_valid = _valid_global_visit_counts(production_history, aliases)
    history_complete &= alias_map_valid and visit_counts_valid
    history_known = history_complete and production_history.get("complete") is True

    inventory_truncated = len(current_inventory) > policy_value.max_frontier_items
    invalid_count = sum(not isinstance(row, Mapping) for row in current_inventory)
    valid_candidates = [row for row in current_inventory if isinstance(row, Mapping)]
    if inventory_truncated:
        valid_candidates = []
    if invalid_count:
        history_known = False

    work: list[dict[str, Any]] = []
    for candidate in valid_candidates:
        candidate_id = _text(candidate.get("candidate_id"), MAX_CANDIDATE_ID_LENGTH)
        edge_type = _edge_type(candidate)
        target_instance, target_document, target_status = _target_identity(candidate, edge_type, focus_cursor)
        if not candidate_id:
            invalid_count += 1
            history_known = False
            continue
        if edge_type not in _SUPPORTED_EDGE_TYPES:
            target_status = "UNRESOLVED"
        if edge_type in _SCROLL_EDGE_TYPES:
            target_status = "DEFERRED_PHASE6E"
        canonical_target, alias_valid = _resolve_alias(target_instance, aliases) if target_instance else ("", False)
        identity_target = target_document if edge_type == EdgeType.FOCUS_NEXT.value else {"instance_id": canonical_target}
        if resolved_state and target_status == "RESOLVED" and identity_target and edge_type in _SUPPORTED_EDGE_TYPES:
            frontier_id = build_frontier_id(resolved_state, edge_type, identity_target)
            provisional = False
        else:
            frontier_id = _unresolved_frontier_id(resolved_state, edge_type, candidate_id)
            provisional = True

        planner, planner_conflict = _lookup_evidence(planner_evidence, candidate_id, frontier_id)
        safety, safety_conflict = _lookup_evidence(safety_evidence, candidate_id, frontier_id)
        planner = planner or {}
        safety = safety or {}
        binding = _text(candidate.get("target_binding_status"), 64).upper()
        if not binding and candidate.get("target_binding_resolved") is True:
            binding = "RESOLVED"
        present = candidate.get("currently_present")
        state_match = not candidate.get("state_id") or _text(candidate.get("state_id")) == resolved_state
        planner_status = _text(planner.get("status"), 64).upper()
        if not planner_status and planner.get("eligible") is True:
            planner_status = "ELIGIBLE"
        elif not planner_status and planner.get("eligible") is False:
            planner_status = "INELIGIBLE"
        safety_status = _text(safety.get("status"), 64).upper() or "UNKNOWN"
        planner_scope = _evidence_scope_matches(planner, state_id=resolved_state,
            edge_type=edge_type, target_instance_id=target_instance)
        safety_scope = _evidence_scope_matches(safety, state_id=resolved_state,
            edge_type=edge_type, target_instance_id=target_instance)

        matching_attempts: list[Mapping[str, Any]] = []
        ambiguous_ownership = False
        if target_status == "RESOLVED" and alias_valid:
            for event in attempts:
                matched, ambiguous = _event_matches(event, state_id=resolved_state,
                    frontier_id=frontier_id, edge_type=edge_type, action_type=edge_type,
                    target_instance_id=canonical_target, aliases=aliases)
                ambiguous_ownership |= ambiguous
                if matched and event.get("attempted") is True:
                    matching_attempts.append(event)
                if (_text(event.get("state_id")) == resolved_state
                        and frontier_id in (event.get("possible_frontier_ids") or [])
                        and event.get("ownership_status") != "EXACT_MATCH"):
                    ambiguous_ownership = True

        matching_visits: list[Mapping[str, Any]] = []
        if target_status == "RESOLVED" and alias_valid:
            for event in visits:
                event_instance = _text(event.get("target_instance_id") or event.get("instance_id"))
                event_canonical, event_alias_valid = _resolve_alias(event_instance, aliases) if event_instance else ("", False)
                if (_text(event.get("state_id")) == resolved_state and event_alias_valid
                        and event_canonical == canonical_target
                        and event.get("production_authority") is True
                        and event.get("accessibility_focus_confirmed") is True
                        and event.get("focus_transition_status") == "CONFIRMED_MOVED"
                        and event.get("visit_record_status") in {"RECORDED", "ALREADY_VISITED"}):
                    if event.get("ownership_status") not in (None, "EXACT_MATCH"):
                        ambiguous_ownership = True
                    else:
                        matching_visits.append(event)

        matching_explorations: list[Mapping[str, Any]] = []
        if target_status == "RESOLVED" and alias_valid:
            for event in explorations:
                matched, ambiguous = _event_matches(event, state_id=resolved_state,
                    frontier_id=frontier_id, edge_type=edge_type, action_type=edge_type,
                    target_instance_id=canonical_target, aliases=aliases)
                ambiguous_ownership |= ambiguous
                if (matched and event.get("production_authority") is True
                        and event.get("exploration_status") == "EXPLORED"):
                    matching_explorations.append(event)

        no_effect_events = [event for event in matching_attempts
            if event.get("ownership_status") == "EXACT_MATCH"
            and event.get("before_observation_valid") is True
            and event.get("after_observation_valid") is True
            and event.get("outcome_observation_complete") is True
            and event.get("effect_observed") is False
            and event.get("actual_focus_moved") is False
            and event.get("state_changed") is False]
        attempt_count = len(matching_attempts)
        no_effect_count = len(no_effect_events)
        state_visit_credits = sum(event.get("visit_record_status") == "RECORDED" for event in matching_visits)
        state_visited = bool(matching_visits) if edge_type in _FOCUS_EDGE_TYPES else False
        state_explored = state_visited or bool(matching_explorations)
        visit_status = ("RECORDED" if state_visit_credits else "ALREADY_VISITED" if state_visited
                        else "UNVISITED" if history_known else "UNKNOWN")

        global_visit_count = visit_counts.get(canonical_target, 0) if canonical_target else 0
        global_visit_count = max(global_visit_count, sum(
            event.get("production_authority") is True
            and event.get("accessibility_focus_confirmed") is True
            and event.get("focus_transition_status") == "CONFIRMED_MOVED"
            and event.get("visit_record_status") == "RECORDED"
            and _resolve_alias(_text(event.get("target_instance_id") or event.get("instance_id")), aliases)[0] == canonical_target
            for event in visits if canonical_target))
        global_attempt_count = sum(
            event.get("attempted") is True and event.get("ownership_status") == "EXACT_MATCH"
            and _text(event.get("action_type") or event.get("edge_type"), 128).upper() == edge_type
            and _resolve_alias(_text(event.get("target_instance_id") or event.get("instance_id")), aliases)[0] == canonical_target
            for event in attempts if canonical_target)
        last_attempt = matching_attempts[-1] if matching_attempts else None
        last_step = last_attempt.get("step") if last_attempt and type(last_attempt.get("step")) is int and last_attempt.get("step") >= 0 else None

        condition = _candidate_condition(candidate, state_id=resolved_state,
            target_identity=target_document, present=present, binding=binding,
            planner_status=planner_status, safety_status=safety_status) if resolved_state else ""
        retry_basis = ""
        retry = planner.get("retry_evidence")
        if isinstance(retry, Mapping) and last_attempt and no_effect_count:
            dims = retry.get("changed_dimensions")
            previous = _text(retry.get("previous_condition_fingerprint"), 256)
            current = _text(retry.get("current_condition_fingerprint"), 256)
            last_condition = _text(last_attempt.get("condition_fingerprint"), 256)
            if (retry.get("status") == "VERIFIED_MEANINGFUL_CHANGE"
                    and _text(retry.get("state_id")) == resolved_state
                    and _text(retry.get("frontier_id")) == frontier_id
                    and previous and previous == last_condition and current == condition and current != previous
                    and isinstance(dims, (list, tuple))
                    and any(_text(dim, 128).lower() in _MEANINGFUL_CHANGE_DIMENSIONS for dim in dims)):
                retry_basis = _text(retry.get("basis_id"), 128) or "VERIFIED_MEANINGFUL_CHANGE"

        stable_raw = planner.get("stable_order_key", candidate.get("stable_order_key"))
        stable_order, stable_sort, stable_valid = _stable_order_key(stable_raw)
        reasons: list[str] = []
        blocked_reason = ""
        exhaustion_basis = ""
        priority: str | None = None
        retry_eligible = False

        if edge_type in _SCROLL_EDGE_TYPES:
            status, blocked_reason = FrontierStatus.BLOCKED.value, "DEFERRED_TO_PHASE6E"
        elif not resolved_state or provisional or target_status != "RESOLVED" or not alias_valid:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "UNRESOLVED_FRONTIER_IDENTITY"))
        elif not state_match or planner_conflict or safety_conflict:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "EVIDENCE_SCOPE_MISMATCH" if not state_match else "CONFLICTING_EVIDENCE"))
        elif safety and safety_scope and safety_status in {"UNSAFE", "DENIED", "FORBIDDEN"}:
            status = FrontierStatus.UNSAFE.value
            reasons.extend(("UNSAFE_BLOCKED", *_sorted_reasons(safety.get("reason_codes"))))
        elif present is None:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "PRESENCE_UNKNOWN"))
        elif present is False:
            status, blocked_reason = FrontierStatus.BLOCKED.value, "NOT_CURRENTLY_PRESENT"
            reasons.append("NOT_CURRENTLY_PRESENT")
        elif binding in {"UNRESOLVED", "AMBIGUOUS", "UNAVAILABLE", "MISMATCH"}:
            status, blocked_reason = FrontierStatus.BLOCKED.value, "TARGET_BINDING_UNAVAILABLE"
            reasons.append("TARGET_BINDING_UNAVAILABLE")
        elif binding != "RESOLVED":
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "TARGET_BINDING_UNKNOWN"))
        elif not planner or not planner_scope:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "PLANNER_EVIDENCE_MISSING_OR_MISMATCHED"))
        elif planner_status in {"UNKNOWN", "UNAVAILABLE", ""}:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "PLANNER_ELIGIBILITY_UNKNOWN"))
        elif planner_status in {"INELIGIBLE", "BLOCKED", "UNSUPPORTED"}:
            terminal_basis = _text(planner.get("non_actionable_basis"), 64).upper()
            if terminal_basis in {"UNSUPPORTED", "EVIDENCE_CONFIRMED"} and planner.get("non_actionable_proven") is True:
                status, exhaustion_basis = FrontierStatus.EXHAUSTED.value, terminal_basis
                reasons.append("ALREADY_EXPLORED")
            else:
                status, blocked_reason = FrontierStatus.BLOCKED.value, _text(planner.get("blocked_reason"), 128) or "PLANNER_INELIGIBLE"
                reasons.append("PLANNER_INELIGIBLE")
        elif planner_status != "ELIGIBLE":
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "PLANNER_STATUS_UNRECOGNIZED"))
        elif not safety or not safety_scope:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "ACTION_SAFETY_EVIDENCE_MISSING_OR_MISMATCHED"))
        elif safety_status in {"UNKNOWN", "UNAVAILABLE", ""}:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "ACTION_SAFETY_UNKNOWN"))
        elif safety_status not in {"SAFE", "ALLOWED", "ELIGIBLE"}:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "ACTION_SAFETY_STATUS_UNRECOGNIZED"))
        elif not history_known or ambiguous_ownership:
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "ACTION_OWNERSHIP_AMBIGUOUS" if ambiguous_ownership else "HISTORY_INCOMPLETE"))
        elif edge_type in _FOCUS_EDGE_TYPES and not (
                isinstance(focus_cursor, Mapping) and focus_cursor.get("confirmed") is True
                and _text(focus_cursor.get("instance_id"))):
            status = FrontierStatus.UNKNOWN.value
            reasons.extend(("UNKNOWN_EVIDENCE", "FOCUS_CURSOR_UNRESOLVED"))
        elif edge_type == EdgeType.TARGETED_FOCUS.value and (
                _resolve_alias(_text(focus_cursor.get("instance_id")), aliases)[0] == canonical_target):
            revisit = _followup_priority(planner, state_id=resolved_state, frontier_id=frontier_id)
            if revisit:
                status, priority = FrontierStatus.ELIGIBLE.value, revisit[0]
                reasons.extend((revisit[1], "REVISIT_DEPRIORITIZED"))
            else:
                status, blocked_reason, exhaustion_basis = FrontierStatus.BLOCKED.value, "CURRENT_FOCUS_NO_NEW_OPPORTUNITY", "EVIDENCE_CONFIRMED"
                reasons.append("CURRENT_FOCUS_NO_NEW_OPPORTUNITY")
        elif state_explored:
            status = FrontierStatus.EXPLORED.value
            exhaustion_basis = "EVIDENCE_CONFIRMED"
            reasons.extend(("ALREADY_EXPLORED", "REVISIT_DEPRIORITIZED"))
            revisit = _followup_priority(planner, state_id=resolved_state, frontier_id=frontier_id)
            if revisit:
                status, priority = FrontierStatus.ELIGIBLE.value, revisit[0]
                reasons.append(revisit[1])
        elif attempt_count >= policy_value.max_attempts_per_opportunity:
            status, exhaustion_basis = FrontierStatus.EXHAUSTED.value, "POLICY_LIMIT"
            reasons.extend(("NO_EFFECT_POLICY_LIMIT", "REVISIT_DEPRIORITIZED"))
        elif attempt_count:
            if retry_basis and attempt_count < policy_value.max_attempts_per_opportunity:
                status, priority, retry_eligible = FrontierStatus.ELIGIBLE.value, PriorityTier.P1.value, True
                reasons.extend(("RETRY_AFTER_MEANINGFUL_CHANGE", "REVISIT_DEPRIORITIZED"))
            else:
                status, blocked_reason = FrontierStatus.BLOCKED.value, "RETRY_REQUIRES_MEANINGFUL_CHANGE"
                reasons.extend(("REVISIT_DEPRIORITIZED", "NO_EFFECT_POLICY_LIMIT" if no_effect_count else "RETRY_REQUIRES_MEANINGFUL_CHANGE"))
        else:
            status, priority = FrontierStatus.ELIGIBLE.value, PriorityTier.P0.value
            reasons.extend(("NEVER_ATTEMPTED", "UNVISITED"))
            if global_visit_count or global_attempt_count:
                reasons.append("STATE_CHANGED_REELIGIBLE")

        if ambiguous_ownership and status != FrontierStatus.UNSAFE.value:
            status, priority, blocked_reason = FrontierStatus.UNKNOWN.value, None, ""
            reasons.extend(("UNKNOWN_EVIDENCE", "ACTION_OWNERSHIP_AMBIGUOUS"))
        if status == FrontierStatus.ELIGIBLE.value and not priority:
            status, priority = FrontierStatus.UNKNOWN.value, None
            reasons.extend(("UNKNOWN_EVIDENCE", "PRIORITY_UNRESOLVED"))
        if status == FrontierStatus.ELIGIBLE.value and not stable_valid:
            reasons.append("STABLE_ORDER_KEY_FALLBACK")

        effect_history = [{
            "effect_observed": event.get("effect_observed") if isinstance(event.get("effect_observed"), bool) else None,
            "actual_focus_moved": event.get("actual_focus_moved") if isinstance(event.get("actual_focus_moved"), bool) else None,
            "ack_status": _text(event.get("ack_status"), 32).upper() if _text(event.get("ack_status"), 32).upper() in _ACK_VALUES else "UNKNOWN",
        } for event in matching_attempts]
        work.append({
            "candidate_id": candidate_id, "frontier_id": frontier_id, "provisional_identity": provisional,
            "state_id": resolved_state or None, "edge_type": edge_type or "UNKNOWN",
            "action_type": edge_type or "UNKNOWN", "target_instance_id": target_instance or None,
            "target_identity": target_document, "status": status, "priority_class": priority,
            "reason_codes": _sorted_reasons(reasons, planner.get("reason_codes"), safety.get("reason_codes")),
            "blocked_reason": blocked_reason, "exhaustion_basis": exhaustion_basis,
            "currently_present": present if isinstance(present, bool) else None,
            "planner_eligible": planner_status == "ELIGIBLE" if planner_status in {"ELIGIBLE", "INELIGIBLE"} else None,
            "safety_status": safety_status, "target_binding_status": binding or "UNKNOWN",
            "stable_order_key": stable_order, "_stable_sort_key": stable_sort,
            "history_complete": history_known, "attempt_count": attempt_count,
            "global_attempt_count": global_attempt_count, "last_attempt_step": last_step,
            "visit_status": visit_status, "global_visit_count": global_visit_count,
            "state_visit_credit_count": state_visit_credits, "state_exploration_observed": state_explored,
            "verified_no_effect_count": no_effect_count,
            "never_attempted": history_known and attempt_count == 0 and not state_explored,
            "retry_eligible": retry_eligible, "retry_basis_id": retry_basis or None,
            "condition_fingerprint": condition or None, "effect_history": effect_history,
            "_scope_included": edge_type not in _SCROLL_EDGE_TYPES,
        })

    # Collapse equivalent duplicate observations; conflicting records for one
    # identity become UNKNOWN. Representative IDs are lexical, not input-order based.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in work:
        grouped.setdefault(row["frontier_id"], []).append(row)
    normalized: list[dict[str, Any]] = []
    for frontier_id in sorted(grouped):
        rows = sorted(grouped[frontier_id], key=lambda row: row["candidate_id"])
        if len(rows) == 1:
            normalized.append(rows[0])
            continue
        signatures = {canonical_json({key: value for key, value in row.items()
                                      if key not in {"candidate_id", "_stable_sort_key"}}) for row in rows}
        representative = dict(rows[0])
        candidate_ids = sorted({row["candidate_id"] for row in rows})
        if len(signatures) == 1:
            representative["candidate_ids"] = candidate_ids
        else:
            representative.update(status=FrontierStatus.UNKNOWN.value, priority_class=None,
                reason_codes=_sorted_reasons("UNKNOWN_EVIDENCE", "DUPLICATE_FRONTIER_EVIDENCE_CONFLICT"),
                blocked_reason="", candidate_ids=candidate_ids)
            history_known = False
        normalized.append(representative)

    priority_order = {PriorityTier.P0.value: 0, PriorityTier.P1.value: 1,
                      PriorityTier.P2.value: 2, PriorityTier.P3.value: 3}
    normalized.sort(key=lambda row: (priority_order.get(row["priority_class"], 99),
                                     row["_stable_sort_key"], row["frontier_id"]))
    scoped = [row for row in normalized if row["_scope_included"]]
    eligible = [row for row in scoped if row["status"] == FrontierStatus.ELIGIBLE.value]
    unknown_count = sum(row["status"] == FrontierStatus.UNKNOWN.value for row in scoped) + invalid_count
    blocked_rows = [row for row in scoped if row["status"] == FrontierStatus.BLOCKED.value]
    policy_limited = any(row["status"] == FrontierStatus.EXHAUSTED.value
                         and row["exhaustion_basis"] == "POLICY_LIMIT" for row in scoped)
    material_blocked = any(row["blocked_reason"] not in _TERMINAL_BLOCKED_REASONS for row in blocked_rows)
    inventory_complete = (state.get("inventory_complete") is True and not inventory_truncated
                          and invalid_count == 0)
    evidence_complete = bool(resolved_state and history_known and inventory_complete
                             and unknown_count == 0 and not material_blocked and not policy_limited)
    if eligible:
        exhausted, exhaustion_reasons = ExhaustionResult.NO.value, ["ELIGIBLE_FRONTIER_REMAINS"]
    elif not evidence_complete:
        exhausted = ExhaustionResult.UNKNOWN.value
        exhaustion_reasons = []
        if unknown_count:
            exhaustion_reasons.append("MATERIAL_UNKNOWN_OPPORTUNITY")
        if not history_known:
            exhaustion_reasons.append("HISTORY_INCOMPLETE")
        if not inventory_complete:
            exhaustion_reasons.append("INVENTORY_INCOMPLETE_OR_TRUNCATED")
        if material_blocked:
            exhaustion_reasons.append("TEMPORARILY_BLOCKED_OPPORTUNITY")
        if policy_limited:
            exhaustion_reasons.append("POLICY_LIMIT_IS_NOT_COMPLETION_PROOF")
        if not exhaustion_reasons:
            exhaustion_reasons.append("INSUFFICIENT_COMPLETION_EVIDENCE")
    else:
        exhausted, exhaustion_reasons = ExhaustionResult.YES.value, ["ALL_IN_SCOPE_OPPORTUNITIES_NON_ACTIONABLE_OR_EXPLORED"]

    first = eligible[0] if eligible and not inventory_truncated else None
    counts = {
        "eligible_count": len(eligible),
        "never_attempted_count": sum(row["status"] == FrontierStatus.ELIGIBLE.value and row["never_attempted"] for row in scoped),
        "unvisited_count": sum(row["history_complete"] and row["visit_status"] == "UNVISITED" for row in scoped),
        "unknown_count": unknown_count,
        "retryable_count": sum(row["status"] == FrontierStatus.ELIGIBLE.value and row["retry_eligible"] for row in scoped),
        "revisit_only_count": sum(row["status"] == FrontierStatus.EXPLORED.value for row in scoped),
        "blocked_count": len(blocked_rows),
        "unsafe_count": sum(row["status"] == FrontierStatus.UNSAFE.value for row in scoped),
        "exhausted_count": sum(row["status"] == FrontierStatus.EXHAUSTED.value for row in scoped),
        "policy_limited_count": sum(row["exhaustion_basis"] == "POLICY_LIMIT" for row in scoped),
        "deferred_scroll_count": sum(row["edge_type"] in _SCROLL_EDGE_TYPES for row in normalized),
        "invalid_or_unidentified_count": invalid_count,
        "truncated_count": max(0, len(current_inventory) - policy_value.max_frontier_items),
    }
    blocked_summary: dict[str, int] = {}
    for row in blocked_rows:
        reason = row["blocked_reason"] or "BLOCKED_REASON_UNKNOWN"
        blocked_summary[reason] = blocked_summary.get(reason, 0) + 1
    output_items = [{key: value for key, value in row.items()
                     if not key.startswith("_")} for row in normalized]
    document = {
        "schema_version": FRONTIER_SCHEMA_VERSION,
        "identity_schema_version": FRONTIER_IDENTITY_VERSION,
        "mode": "SHADOW_ONLY", "decision_authority": "NONE",
        "state_id": resolved_state or None, "exhaustion_scope": EXHAUSTION_SCOPE,
        "frontier_exhausted": exhausted, "evidence_complete": evidence_complete,
        "exhaustion_reason_codes": _sorted_reasons(exhaustion_reasons),
        "frontier_items": output_items,
        "shadow_next_frontier": first["frontier_id"] if first else None,
        "shadow_next_candidate_id": first.get("candidate_id") if first else None,
        "shadow_next_action_type": first.get("action_type") if first else None,
        "shadow_next_reason_codes": list(first["reason_codes"]) if first else [],
        "focus_next_destination_guaranteed": False,
        "counts": counts, "blocked_reason_summary": dict(sorted(blocked_summary.items())),
        "history_complete": history_known, "inventory_complete": inventory_complete,
        "truncated": inventory_truncated or history_truncated,
        "max_frontier_items": policy_value.max_frontier_items,
        "max_history_events": policy_value.max_history_events,
        "max_attempts_per_opportunity": policy_value.max_attempts_per_opportunity,
    }
    return FrontierEvaluation(canonical_json(document))


__all__ = [
    "EXHAUSTION_SCOPE", "FRONTIER_IDENTITY_VERSION", "FRONTIER_SCHEMA_VERSION",
    "ExhaustionResult", "FrontierEvaluation", "FrontierItem", "FrontierPolicy",
    "FrontierStatus", "PriorityTier", "build_frontier_id", "evaluate_frontier",
]
