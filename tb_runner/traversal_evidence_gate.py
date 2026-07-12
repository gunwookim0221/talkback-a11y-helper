"""Strict, default-off production promotion gate for Identity Shadow V2 facts.

The module is deliberately pure.  It neither performs navigation nor mutates
Runner state; collection code must explicitly apply each returned decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence


TRAVERSAL_IDENTITY_V2_ENABLED_ENV = "TB_TRAVERSAL_IDENTITY_V2_ENABLED"
ALLOWED_REDUCER_VERSIONS = frozenset({"target-relation-v2"})
TRAVERSAL_DIAGNOSTICS_SCHEMA = "traversal-identity-v2-diagnostics-v1"

_TRUTHY = {"1", "true", "yes", "on"}
_HIGH_CONFIDENCE = {"HIGH_CONFIDENCE", "CONFIRMED"}
_STRONG_TARGET_RELATIONS = {
    "EXACT_PHYSICAL_NODE",
    "STRONG_PHYSICAL_LINK",
    "TARGET_ANCESTOR",
    "TARGET_DESCENDANT",
    "CONTAINER_PARENT",
    "CONTAINER_CHILD",
}
_DIAGNOSTIC_COUNTERS = (
    "false_progress_suppressed",
    "representative_only_progress_ignored",
    "recovered_candidate_attempts",
    "recovered_visits",
    "premature_stop_prevented",
    "fallback_to_legacy_count",
    "indeterminate_count",
)


def traversal_identity_v2_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return str(source.get(TRAVERSAL_IDENTITY_V2_ENABLED_ENV, "") or "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class ProgressDecision:
    physical_progress: bool | None
    semantic_progress: bool | None
    representative_only: bool
    evidence_complete: bool
    accepted: bool
    gate_applied: bool
    legacy_progressed: bool
    verdict: str
    reason: str
    source: str
    used_legacy_fallback: bool
    confidence: str
    transaction_id: str
    reducer_version: str

    @property
    def progressed(self) -> bool:
        return self.accepted

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisitDecision:
    visited: bool
    consumed: bool
    representative_only: bool
    stable_landing: bool
    relation_compatible: bool
    reason: str
    visit_source: str
    consumption_source: str
    transaction_id: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryCandidate:
    candidate_id: str
    canonical_key: str
    scenario_id: str
    surface_id: str
    label: str
    resource_id: str
    class_name: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    focusable: bool
    enabled: bool | None
    taxonomy: str
    priority: int
    source_index: int

    def requested_observation(self) -> dict[str, Any]:
        left, top, right, bottom = self.bounds
        return {
            "viewIdResourceName": self.resource_id or None,
            "className": self.class_name or None,
            "text": self.label or None,
            "talkbackLabel": self.label or None,
            "boundsInScreen": {"l": left, "t": top, "r": right, "b": bottom},
            "captureSource": "canonical_recovery_candidate",
        }

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bounds"] = list(self.bounds)
        return payload


@dataclass(frozen=True)
class TraversalDiagnostics:
    false_progress_suppressed: int = 0
    representative_only_progress_ignored: int = 0
    recovered_candidate_attempts: int = 0
    recovered_visits: int = 0
    premature_stop_prevented: int = 0
    fallback_to_legacy_count: int = 0
    indeterminate_count: int = 0

    def record_gate(self, progress: ProgressDecision, visit: VisitDecision) -> "TraversalDiagnostics":
        return replace(
            self,
            false_progress_suppressed=self.false_progress_suppressed
            + int(progress.gate_applied and progress.verdict == "STATIC_FOCUS" and progress.legacy_progressed),
            representative_only_progress_ignored=self.representative_only_progress_ignored
            + int(visit.representative_only and progress.gate_applied and not progress.accepted),
            fallback_to_legacy_count=self.fallback_to_legacy_count + int(progress.used_legacy_fallback),
            indeterminate_count=self.indeterminate_count + int(progress.verdict == "INDETERMINATE"),
        )

    def record_recovery_attempt(self) -> "TraversalDiagnostics":
        return replace(self, recovered_candidate_attempts=self.recovered_candidate_attempts + 1)

    def record_recovery_visit(self) -> "TraversalDiagnostics":
        return replace(self, recovered_visits=self.recovered_visits + 1)

    def record_stop_prevented(self) -> "TraversalDiagnostics":
        return replace(self, premature_stop_prevented=self.premature_stop_prevented + 1)

    def to_payload(self) -> dict[str, Any]:
        return {"available": True, "schema": TRAVERSAL_DIAGNOSTICS_SCHEMA, **asdict(self)}


def detect_representative_only(row: Mapping[str, Any] | None) -> bool:
    if not isinstance(row, Mapping):
        return False
    source = str(row.get("row_source", "") or "").strip().lower()
    representative = (
        str(row.get("representative_observation_id", "") or "").strip(),
        str(row.get("representative_resource_id", "") or row.get("focus_view_id", "") or "").strip(),
        _bounds_text(row.get("representative_bounds", "") or row.get("focus_bounds", "")),
        _normalize_label(row.get("representative_visible", "") or row.get("visible_label", "")),
    )
    actual = (
        str(row.get("actual_focus_observation_id", "") or "").strip(),
        str(row.get("actual_focus_resource_id", "") or "").strip(),
        _bounds_text(row.get("actual_focus_bounds", "")),
        _normalize_label(row.get("actual_focus_visible", "")),
    )
    if source not in {"representative", "representative_fallback"} and not any(
        row.get(key) for key in ("representative_observation_id", "representative_visible", "representative_bounds")
    ):
        return False
    if representative[0] and actual[0]:
        return representative[0] != actual[0]
    pairs = [(left, right) for left, right in zip(representative[1:], actual[1:]) if left and right]
    return any(left != right for left, right in pairs) if pairs else True


def evaluate_traversal_gate(
    identity_result: Mapping[str, Any] | None,
    *,
    transaction_id: str,
    evidence_transaction_id: str,
    legacy_progressed: bool,
    legacy_visited: bool | None = None,
    legacy_consumed: bool | None = None,
    row: Mapping[str, Any] | None = None,
    enabled: bool | None = None,
) -> tuple[ProgressDecision, VisitDecision]:
    is_enabled = traversal_identity_v2_enabled() if enabled is None else bool(enabled)
    legacy_visit = bool(legacy_progressed if legacy_visited is None else legacy_visited)
    legacy_consume = bool(legacy_visit if legacy_consumed is None else legacy_consumed)
    result = identity_result if isinstance(identity_result, Mapping) else {}
    verdict = str(result.get("verdict") or "INDETERMINATE").strip().upper()
    reducer_version = str(result.get("reducer_version") or "").strip()
    confidence = str(result.get("confidence") or "INDETERMINATE").strip().upper()
    representative_only = detect_representative_only(row)

    failure = _common_gate_failure(
        result,
        enabled=is_enabled,
        transaction_id=str(transaction_id or ""),
        evidence_transaction_id=str(evidence_transaction_id or ""),
        reducer_version=reducer_version,
    )
    if failure:
        return _legacy_decisions(
            verdict, failure, transaction_id, reducer_version, confidence,
            legacy_progressed, legacy_visit, legacy_consume, representative_only, _evidence_complete(result)
        )

    # The main SMART transaction cannot describe a later successful direct
    # realign.  Falling back here prevents a closed-but-stale transaction from
    # being promoted after physical focus has changed again.
    if isinstance(row, Mapping) and (
        row.get("forced_local_tab_navigation") is True
        or (
            (row.get("cta_focus_align_requested") is True or row.get("cta_promote_kept_committed") is True)
            and row.get("cta_focus_align_success") is True
        )
    ):
        return _legacy_decisions(
            verdict, "post_transaction_navigation_applied", transaction_id, reducer_version, confidence,
            legacy_progressed, legacy_visit, legacy_consume, representative_only, True
        )

    if verdict not in {"STATIC_FOCUS", "MOVE_CONFIRMED"}:
        reason = {
            "INDETERMINATE": "identity_v2_indeterminate",
            "MOVE_TO_OTHER_NODE": "other_node_conservative_fallback",
            "SNAP_BACK": "snap_back_conservative_fallback",
        }.get(verdict, "unsupported_verdict")
        return _legacy_decisions(
            verdict, reason, transaction_id, reducer_version, confidence,
            legacy_progressed, legacy_visit, legacy_consume, representative_only, True
        )

    temporal = str(result.get("temporal_relation") or result.get("stability") or "").strip().upper()
    if temporal != "STABLE_LANDING":
        return _legacy_decisions(
            verdict, "landing_not_stable", transaction_id, reducer_version, confidence,
            legacy_progressed, legacy_visit, legacy_consume, representative_only, True
        )
    if confidence not in _HIGH_CONFIDENCE:
        return _legacy_decisions(
            verdict, "confidence_insufficient", transaction_id, reducer_version, confidence,
            legacy_progressed, legacy_visit, legacy_consume, representative_only, True
        )

    if verdict == "STATIC_FOCUS":
        legacy_move_result = str((row or {}).get("move_result") or "").strip().lower() if isinstance(row, Mapping) else ""
        if "scrolled" in legacy_move_result:
            return _legacy_decisions(
                verdict, "non_focus_scroll_progress_preserved", transaction_id, reducer_version, confidence,
                legacy_progressed, legacy_visit, legacy_consume, representative_only, True
            )
        action_api = str(result.get("action_api") or "").strip().upper()
        action_reason = str(result.get("action_reason") or "").strip()
        valid_action = action_api == "ACCEPTED" or (action_api == "REJECTED" and action_reason == "reached_end")
        if not valid_action or _contradictions(result):
            reason = "static_action_not_promotable" if not valid_action else "physical_contradictions_present"
            return _legacy_decisions(
                verdict, reason, transaction_id, reducer_version, confidence,
                legacy_progressed, legacy_visit, legacy_consume, representative_only, True
            )
        progress = ProgressDecision(
            False, False, representative_only, True, False, True, bool(legacy_progressed), verdict,
            "identity_v2_static_focus", "identity_v2", False, confidence, str(transaction_id or ""), reducer_version
        )
        visit = VisitDecision(
            False,
            bool(legacy_consume),
            representative_only,
            True,
            False,
            "static_focus_has_no_visit_credit",
            "identity_v2",
            "planning_attempt" if legacy_consume else "not_attempted",
            str(transaction_id or ""),
        )
        return progress, visit

    target = _target_landing(result)
    relation = str(target.get("aggregate_relation") or result.get("target_relation") or "").strip().upper()
    target_confidence = str(target.get("confidence") or confidence).strip().upper()
    compatible = (
        relation in _STRONG_TARGET_RELATIONS
        and target_confidence in _HIGH_CONFIDENCE
        and target.get("allows_move_confirmation") is True
        and not _string_tuple(target.get("contradictions"))
        and str(result.get("action_api") or "").strip().upper() == "ACCEPTED"
        and str(result.get("physical_focus_delta") or "").strip().upper() == "CHANGED"
    )
    if not compatible:
        return _legacy_decisions(
            verdict, "target_compatibility_not_strong", transaction_id, reducer_version, confidence,
            legacy_progressed, legacy_visit, legacy_consume, representative_only, True
        )
    progress = ProgressDecision(
        True, True, representative_only, True, True, True, bool(legacy_progressed), verdict,
        "identity_v2_move_confirmed", "identity_v2", False, confidence, str(transaction_id or ""), reducer_version
    )
    visit = VisitDecision(
        True, bool(legacy_consume), representative_only, True, True,
        "actual_focus_visited_planning_consumed" if representative_only else "stable_target_visit",
        "identity_v2_actual_focus", "planning_attempt" if legacy_consume else "not_attempted",
        str(transaction_id or ""),
    )
    return progress, visit


def select_recovery_candidate(
    inventory: Sequence[Mapping[str, Any]],
    *,
    scenario_id: str,
    surface_id: str = "",
    viewport_bounds: Any = None,
    visited: set[str] | frozenset[str] = frozenset(),
    hard_failed: set[str] | frozenset[str] = frozenset(),
    attempted: set[str] | frozenset[str] = frozenset(),
) -> RecoveryCandidate | None:
    expected_scenario = str(scenario_id or "").strip()
    expected_surface = str(surface_id or "").strip()
    viewport = _coerce_bounds(viewport_bounds)
    blocked = {str(value or "").strip() for value in (*visited, *hard_failed, *attempted) if str(value or "").strip()}
    blocked_keys: set[str] = set()
    seen_keys: set[str] = set()
    eligible: list[RecoveryCandidate] = []

    for index, raw in enumerate(inventory):
        if not isinstance(raw, Mapping):
            continue
        candidate_scenario = str(raw.get("scenario_id") or "").strip()
        candidate_surface = str(raw.get("surface_id") or raw.get("local_tab_signature") or "").strip()
        if expected_scenario and candidate_scenario != expected_scenario:
            continue
        if expected_surface and candidate_surface != expected_surface:
            continue
        if not expected_surface and candidate_surface:
            continue
        variants = [raw, *[item for item in raw.get("raw_records", []) if isinstance(item, Mapping)]]
        bounds = next((_coerce_bounds(item.get("bounds_screen") or item.get("bounds_normalized") or item.get("bounds")) for item in variants if _coerce_bounds(item.get("bounds_screen") or item.get("bounds_normalized") or item.get("bounds"))), None)
        if bounds is None or not _valid_bounds(bounds) or _is_fullscreen(raw, bounds, viewport):
            continue
        if variants and all(item.get("enabled") is False for item in variants):
            continue
        clickable = any(item.get("clickable") is True or item.get("actionable") is True for item in variants)
        focusable = any(item.get("focusable") is True for item in variants)
        class_name = next((str(item.get("class_name") or item.get("className") or "").strip() for item in variants if item.get("class_name") or item.get("className")), "")
        if "button" in class_name.lower():
            clickable = True
            focusable = True
        if not (clickable or focusable):
            continue
        taxonomy = str(raw.get("taxonomy") or "").strip().upper()
        if taxonomy == "IGNORE" or _is_ignored(raw) or _is_chrome(raw, variants):
            continue
        label = _normalize_label(next((item.get("talkback_label_normalized") or item.get("label") or item.get("text_normalized") for item in variants if item.get("talkback_label_normalized") or item.get("label") or item.get("text_normalized")), ""))
        resource_id = next((str(item.get("resource_id") or item.get("view_id") or item.get("viewIdResourceName") or "").strip() for item in variants if item.get("resource_id") or item.get("view_id") or item.get("viewIdResourceName")), "")
        if not label and not resource_id:
            continue
        canonical_key = _canonical_candidate_key(candidate_scenario, candidate_surface, resource_id, class_name, label, bounds)
        candidate_id = str(raw.get("canonical_id") or raw.get("canonical_candidate_id") or raw.get("candidate_id") or f"recovery:v1:{hashlib.sha256(canonical_key.encode('utf-8')).hexdigest()[:24]}").strip()
        aliases = {candidate_id, canonical_key, str(raw.get("canonical_id") or "").strip()}
        if blocked.intersection(value for value in aliases if value):
            blocked_keys.add(canonical_key)
            continue
        if canonical_key in blocked_keys or canonical_key in seen_keys:
            continue
        seen_keys.add(canonical_key)
        taxonomy_priority = {"REQUIRED": 30, "REVIEW": 20, "OPTIONAL": 10}.get(taxonomy, 0)
        enabled_values = [item.get("enabled") for item in variants if item.get("enabled") is not None]
        enabled_state = True if any(value is True for value in enabled_values) else None
        eligible.append(RecoveryCandidate(
            candidate_id, canonical_key, candidate_scenario, candidate_surface, label, resource_id, class_name,
            bounds, clickable, focusable, enabled_state,
            taxonomy or "UNCLASSIFIED", taxonomy_priority + int(bool(resource_id)), index,
        ))

    eligible.sort(key=lambda item: (-item.priority, -int(item.clickable), item.bounds[1], item.bounds[0], item.candidate_id))
    return eligible[0] if eligible else None


def diagnostics_payload_schema() -> dict[str, Any]:
    return {
        "schema": TRAVERSAL_DIAGNOSTICS_SCHEMA,
        "required": ["available", "schema", *_DIAGNOSTIC_COUNTERS],
        "counters": {name: {"type": "integer", "minimum": 0} for name in _DIAGNOSTIC_COUNTERS},
    }


def _common_gate_failure(result: Mapping[str, Any], *, enabled: bool, transaction_id: str, evidence_transaction_id: str, reducer_version: str) -> str:
    if not enabled:
        return "feature_disabled"
    if not result:
        return "identity_result_unavailable"
    if reducer_version not in ALLOWED_REDUCER_VERSIONS:
        return "reducer_version_not_allowed"
    if not transaction_id or transaction_id != evidence_transaction_id:
        return "transaction_mismatch"
    if str(result.get("runtime_transaction_id") or "") != transaction_id or str(result.get("runtime_transaction_state") or "") != "closed":
        return "transaction_not_closed"
    orphan_count = _safe_nonnegative_int(result.get("runtime_orphan_count"))
    malformed_count = _safe_nonnegative_int(result.get("runtime_malformed_count"))
    if orphan_count is None or malformed_count is None:
        return "transaction_evidence_invalid"
    if orphan_count or malformed_count:
        return "transaction_evidence_invalid"
    if not _evidence_complete(result):
        return "evidence_incomplete"
    if str(result.get("transport") or "").strip().upper() != "ACKED":
        return "helper_ack_missing"
    return ""


def _legacy_decisions(verdict: str, reason: str, transaction_id: str, reducer_version: str, confidence: str, legacy_progressed: bool, legacy_visited: bool, legacy_consumed: bool, representative_only: bool, complete: bool) -> tuple[ProgressDecision, VisitDecision]:
    progress = ProgressDecision(None, None, representative_only, complete, bool(legacy_progressed), False, bool(legacy_progressed), verdict, reason, "legacy_fallback", True, confidence, str(transaction_id or ""), reducer_version)
    visit = VisitDecision(bool(legacy_visited), bool(legacy_consumed), representative_only, False, False, reason, "legacy_fallback", "legacy_fallback", str(transaction_id or ""))
    return progress, visit


def _evidence_complete(result: Mapping[str, Any]) -> bool:
    return result.get("evidence_complete") is True and str(result.get("evidence_completeness") or "").strip().upper() == "COMPLETE"


def _target_landing(result: Mapping[str, Any]) -> Mapping[str, Any]:
    diagnostics = result.get("identity_diagnostics")
    target = diagnostics.get("target_landing") if isinstance(diagnostics, Mapping) else None
    return target if isinstance(target, Mapping) else {}


def _contradictions(result: Mapping[str, Any]) -> tuple[str, ...]:
    values = set(_string_tuple(result.get("contradicting_fields")))
    diagnostics = result.get("identity_diagnostics")
    pre_post = diagnostics.get("pre_post") if isinstance(diagnostics, Mapping) else None
    if isinstance(pre_post, Mapping):
        values.update(_string_tuple(pre_post.get("contradictions")))
    target_landing = diagnostics.get("target_landing") if isinstance(diagnostics, Mapping) else None
    if isinstance(target_landing, Mapping):
        values.update(_string_tuple(target_landing.get("contradictions")))
    return tuple(sorted(values))


def _safe_nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(sorted({str(item or "").strip() for item in value if str(item or "").strip()}))


def _normalize_label(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _bounds_text(value: Any) -> str:
    bounds = _coerce_bounds(value)
    return ",".join(str(part) for part in bounds) if bounds else str(value or "").strip()


def _coerce_bounds(value: Any) -> tuple[int, int, int, int] | None:
    if isinstance(value, Mapping):
        keys = ("l", "t", "r", "b") if any(key in value for key in ("l", "t", "r", "b")) else ("left", "top", "right", "bottom")
        parts = [value.get(key) for key in keys]
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        parts = list(value)
    elif isinstance(value, str):
        numbers = re.findall(r"-?\d+", value)
        if len(numbers) < 4:
            return None
        parts = numbers[:4]
    else:
        return None
    try:
        parsed = tuple(int(part) for part in parts)
    except (TypeError, ValueError):
        return None
    return parsed if len(parsed) == 4 else None  # type: ignore[return-value]


def _valid_bounds(bounds: tuple[int, int, int, int]) -> bool:
    return bounds[2] > bounds[0] and bounds[3] > bounds[1]


def _is_fullscreen(raw: Mapping[str, Any], bounds: tuple[int, int, int, int], viewport: tuple[int, int, int, int] | None) -> bool:
    if any(raw.get(key) is True for key in ("fullscreen", "full_screen", "is_fullscreen")):
        return True
    if viewport is None or not _valid_bounds(viewport):
        return False
    area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    viewport_area = (viewport[2] - viewport[0]) * (viewport[3] - viewport[1])
    contains = bounds[0] <= viewport[0] and bounds[1] <= viewport[1] and bounds[2] >= viewport[2] and bounds[3] >= viewport[3]
    return contains or area / float(max(1, viewport_area)) >= 0.82


def _is_ignored(raw: Mapping[str, Any]) -> bool:
    return any(str(raw.get(key) or "").strip().upper() == "IGNORE" for key in ("taxonomy", "disposition", "decision", "classification", "candidate_status", "audit_status"))


def _is_chrome(raw: Mapping[str, Any], variants: Sequence[Mapping[str, Any]]) -> bool:
    if any(raw.get(key) is True for key in ("chrome", "is_chrome", "chrome_like", "is_chrome_like")):
        return True
    normalized_labels = {
        _normalize_label(item.get("label") or item.get("talkback_label_normalized"))
        for item in variants
        if item.get("label") or item.get("talkback_label_normalized")
    }
    resource_values = {
        str(item.get("resource_id") or item.get("view_id") or "").strip().lower()
        for item in variants
        if item.get("resource_id") or item.get("view_id")
    }
    resources = " ".join(resource_values)
    return bool(
        any(token in resources for token in ("toolbar", "appbar", "action_bar", "more_menu", "home_button"))
        or resource_values.intersection({"back", "more", "navigate_up"})
        or normalized_labels.intersection({"navigate up", "more options", "상위 메뉴로 이동", "옵션 더보기"})
    )


def _canonical_candidate_key(scenario_id: str, surface_id: str, resource_id: str, class_name: str, label: str, bounds: tuple[int, int, int, int]) -> str:
    return json.dumps({"scenario_id": scenario_id, "surface_id": surface_id, "resource_id": resource_id, "class_name": class_name, "label": label, "bounds": bounds}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ALLOWED_REDUCER_VERSIONS", "ProgressDecision", "RecoveryCandidate", "TRAVERSAL_DIAGNOSTICS_SCHEMA",
    "TRAVERSAL_IDENTITY_V2_ENABLED_ENV", "TraversalDiagnostics", "VisitDecision",
    "detect_representative_only", "diagnostics_payload_schema", "evaluate_traversal_gate",
    "select_recovery_candidate", "traversal_identity_v2_enabled",
]
