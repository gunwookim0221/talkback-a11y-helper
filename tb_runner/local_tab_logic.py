from __future__ import annotations

import re
import time
from collections import deque
from typing import Any, Callable

from talkback_lib import A11yAdbClient
from tb_runner.logging_utils import log
from tb_runner.perf_stats import ScenarioPerfStats
from tb_runner.utils import parse_bounds_str

LOCAL_TAB_ACTIVE_TTL_STEPS = 3
_TRANSITION_FAST_ACTION_WAIT_SECONDS = 2
COLLECTION_FLOW_SCROLL_DECISION_DEBUG_VERSION = "pr108-local-tab-last-selected-hint-v1"
COLLECTION_FLOW_SCROLL_READY_VERSION = "pr79-scroll-ready-move-smart-v1"

def _scroll_state(state: Any) -> Any:
    return getattr(state, "scroll_state", state)

def _focus_realign_state(state: Any) -> Any:
    if hasattr(state, "focus_realign_state"):
        return state.focus_realign_state
    return state

def _clear_last_selected_local_tab_hint(state: Any, *, reason: str) -> None:
    active = _local_tab_state_display(
        rid=str(getattr(state, "last_selected_local_tab_rid", "") or ""),
        label=str(getattr(state, "last_selected_local_tab_label", "") or ""),
    )
    if active:
        log(
            f"[STEP][local_tab_hint_clear] active='{_truncate_debug_text(active, 96)}' "
            f"reason='{reason}'"
        )
    state.last_selected_local_tab_signature = ""
    state.last_selected_local_tab_rid = ""
    state.last_selected_local_tab_label = ""
    state.last_selected_local_tab_bounds = ""

def _write_last_selected_local_tab_hint(
    state: Any,
    *,
    signature: str,
    rid: str,
    label: str,
    bounds: str,
    reason: str,
) -> None:
    state.last_selected_local_tab_signature = str(signature or "").strip()
    state.last_selected_local_tab_rid = str(rid or "").strip()
    state.last_selected_local_tab_label = str(label or "").strip()
    state.last_selected_local_tab_bounds = str(bounds or "").strip()
    log(
        f"[STEP][local_tab_hint_write] selected='{_truncate_debug_text(label or rid, 96)}' "
        f"reason='{reason}'"
    )

def _build_local_tab_strip_signature(tab_candidates: list[dict[str, Any]]) -> str:
    candidate_keys: list[str] = []
    for candidate in tab_candidates:
        if not isinstance(candidate, dict):
            continue
        rid = str(candidate.get("rid", "") or "").strip().lower()
        if rid:
            candidate_keys.append(rid)
            continue
        label = _normalize_logical_text(str(candidate.get("label", "") or "").strip())
        bounds = str(candidate.get("bounds", "") or "").strip()
        candidate_keys.append(label or bounds)
    return "||".join(candidate_keys)

def _canonicalize_local_tab_label(label: str) -> str:
    value = re.sub(r"\s+", " ", str(label or "").strip())
    if not value:
        return ""
    stripped = re.sub(r"\s+\d+\s+new notifications?$", "", value, flags=re.IGNORECASE).strip()
    stripped = re.sub(r"\s+new notifications?$", "", stripped, flags=re.IGNORECASE).strip()
    return stripped or value

def _select_active_local_tab_candidate(
    *,
    tab_candidates: list[dict[str, Any]],
    row: dict[str, Any],
) -> dict[str, Any] | None:
    row_rid = str(row.get("focus_view_id", "") or "").strip().lower()
    row_label = _canonicalize_local_tab_label(
        str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    ).lower()
    for candidate in tab_candidates:
        node = candidate.get("node", {})
        if isinstance(node, dict) and bool(node.get("selected")):
            return candidate
    for candidate in tab_candidates:
        candidate_rid = str(candidate.get("rid", "") or "").strip().lower()
        candidate_label = _canonicalize_local_tab_label(str(candidate.get("label", "") or "").strip()).lower()
        if row_rid and candidate_rid and row_rid == candidate_rid:
            return candidate
        if row_label and candidate_label and row_label == candidate_label:
            return candidate
    return tab_candidates[0] if tab_candidates else None

def _sort_local_tab_candidates_left_to_right(tab_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed_candidates = list(enumerate(tab_candidates))

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, str]:
        index, candidate = item
        left = candidate.get("left", None)
        if left is None:
            node = candidate.get("node", {})
            if isinstance(node, dict):
                bounds = parse_bounds_str(str(node.get("boundsInScreen", "") or node.get("bounds", "") or "").strip())
                if bounds:
                    left = bounds[0]
        try:
            left_value = int(left)
        except Exception:
            left_value = index * 10000
        return (left_value, index, str(candidate.get("label", "") or candidate.get("rid", "") or ""))

    return [candidate for _, candidate in sorted(indexed_candidates, key=sort_key)]

def _local_tab_state_display(*, rid: str = "", label: str = "") -> str:
    return str(label or rid or "").strip()

def _is_viewport_exhausted_for_scroll_fallback(
    *,
    candidates: list[dict],
    representative_exists: bool,
) -> bool:
    return not bool(representative_exists)

def _normalize_local_tab_utility_text(value: str) -> str:
    try:
        normalized = _normalize_logical_text(value)
    except Exception:
        normalized = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    return normalized

def _is_active_location_local_tab(state: MainLoopState) -> bool:
    active_text = " ".join(
        str(value or "")
        for value in (
            getattr(state, "current_local_tab_active_rid", ""),
            getattr(state, "current_local_tab_active_label", ""),
            getattr(state, "last_selected_local_tab_rid", ""),
            getattr(state, "last_selected_local_tab_label", ""),
        )
    )
    return "location" in _normalize_local_tab_utility_text(active_text)

def _is_location_map_utility_candidate(candidate: dict[str, Any]) -> bool:
    label = str(candidate.get("label", "") or "").strip()
    node = candidate.get("node", {})
    rid = str(candidate.get("rid", "") or "").strip()
    if isinstance(node, dict):
        rid = str(rid or node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
        label = str(
            label
            or node.get("text", "")
            or node.get("contentDescription", "")
            or node.get("mergedLabel", "")
            or node.get("talkbackLabel", "")
            or ""
        ).strip()
    normalized_label = _normalize_local_tab_utility_text(label)
    normalized_rid = rid.lower()
    if normalized_label in {
        "place",
        "place place",
        "current location",
        "current location current location",
        "map",
        "change view",
        "naver",
    }:
        return True
    if normalized_label.startswith("last updated") or normalized_label.startswith("near "):
        return True
    if any(token in normalized_rid for token in (":id/time", ":id/position", ":id/layerbutton")):
        return True
    return False

def _filter_location_map_utility_exhaustion_candidates(
    *,
    state: MainLoopState,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not candidates or not _is_active_location_local_tab(state):
        return candidates
    if all(_is_location_map_utility_candidate(candidate) for candidate in candidates):
        return []
    return candidates

def _local_tab_candidate_matches_identity(
    candidate: dict[str, Any],
    *,
    rid: str,
    label: str,
    bounds: str = "",
) -> tuple[bool, str]:
    candidate_rid = str(candidate.get("rid", "") or "").strip().lower()
    candidate_label = str(candidate.get("label", "") or "").strip()
    normalized_candidate_label = _normalize_logical_text(_canonicalize_local_tab_label(candidate_label))
    normalized_label = _normalize_logical_text(_canonicalize_local_tab_label(label))
    rid = str(rid or "").strip().lower()
    if candidate_rid and rid and candidate_rid == rid:
        return True, "rid"
    compact_candidate_rid = re.sub(r"[^a-z0-9]+", "", candidate_rid)
    compact_rid = re.sub(r"[^a-z0-9]+", "", rid)
    if compact_candidate_rid and compact_rid and (compact_candidate_rid in compact_rid or compact_rid in compact_candidate_rid):
        return True, "rid"
    if normalized_candidate_label and normalized_label and normalized_candidate_label == normalized_label:
        return True, "label"
    if normalized_candidate_label and normalized_label and (
        normalized_candidate_label in normalized_label
        or normalized_label in normalized_candidate_label
    ):
        return True, "label_contains"
    candidate_bounds = str(candidate.get("bounds", "") or "").strip()
    if not candidate_bounds:
        node = candidate.get("node", {})
        if isinstance(node, dict):
            candidate_bounds = str(node.get("boundsInScreen", "") or node.get("bounds", "") or "").strip()
    if candidate_bounds and bounds and _representative_focus_matches(
        focus_node={"boundsInScreen": bounds},
        target_rid="",
        target_label="",
        target_bounds=candidate_bounds,
    ):
        return True, "bounds"
    return False, "none"

def _resolve_active_local_tab_candidate_for_progression(
    *,
    state: MainLoopState,
    sorted_tab_candidates: list[dict[str, Any]],
    row: dict[str, Any],
    previous_row: dict[str, Any],
) -> tuple[dict[str, Any] | None, str, str]:
    active_rid = str(getattr(state, "current_local_tab_active_rid", "") or "").strip()
    active_label = str(getattr(state, "current_local_tab_active_label", "") or "").strip()
    committed_active_age = int(getattr(state, "current_local_tab_active_age", 0) or 0)
    pending_rid = str(getattr(state, "pending_local_tab_rid", "") or "").strip()
    pending_label = str(getattr(state, "pending_local_tab_label", "") or "").strip()
    if len(sorted_tab_candidates) >= 2:
        log(
            f"[STEP][local_tab_active_state] committed='{_truncate_debug_text(_local_tab_state_display(rid=active_rid, label=active_label), 96)}' "
            f"committed_age={committed_active_age} "
            f"pending='{_truncate_debug_text(_local_tab_state_display(rid=pending_rid, label=pending_label), 96)}' "
            f"pending_age={int(getattr(state, 'pending_local_tab_age', 0) or 0)} "
            f"ttl={LOCAL_TAB_ACTIVE_TTL_STEPS} "
            f"candidate_order='{_truncate_debug_text(_summarize_candidate_labels(sorted_tab_candidates), 120)}'"
        )
    if (active_rid or active_label) and committed_active_age <= LOCAL_TAB_ACTIVE_TTL_STEPS:
        for candidate in sorted_tab_candidates:
            matched, _ = _local_tab_candidate_matches_identity(candidate, rid=active_rid, label=active_label)
            if matched:
                resolved_label = str(candidate.get("label", "") or candidate.get("rid", "") or active_label or active_rid).strip()
                log(
                    f"[STEP][local_tab_active_override] active='{_truncate_debug_text(resolved_label, 96)}' "
                    "reason='committed_state_used_for_progression'"
                )
                log(
                    f"[STEP][local_tab_active_keep] active='{_truncate_debug_text(resolved_label, 96)}' "
                    f"age={committed_active_age} reason='within_committed_ttl'"
                )
                state.current_local_tab_active_age = committed_active_age + 1
                return candidate, "committed", resolved_label
        log(
            f"[STEP][local_tab_active_resolve_fail] committed='{_truncate_debug_text(active_label or active_rid, 96)}' "
            "reason='not_found_in_sorted_candidates'"
        )
    elif active_rid or active_label:
        log(
            f"[STEP][local_tab_state_clear] target='committed' "
            f"active_before='{_truncate_debug_text(_local_tab_state_display(rid=active_rid, label=active_label), 96)}' "
            f"pending_before='{_truncate_debug_text(_local_tab_state_display(rid=pending_rid, label=pending_label), 96)}' "
            "reason='ttl_expired' caller='_resolve_active_local_tab_candidate_for_progression'"
        )
        log(
            f"[STEP][local_tab_active_clear] active='{_truncate_debug_text(active_label or active_rid, 96)}' "
            "reason='ttl_expired'"
        )
        state.current_local_tab_active_rid = ""
        state.current_local_tab_active_label = ""
        state.current_local_tab_active_age = 0
    hint_signature = str(getattr(state, "last_selected_local_tab_signature", "") or "").strip()
    hint_rid = str(getattr(state, "last_selected_local_tab_rid", "") or "").strip()
    hint_label = str(getattr(state, "last_selected_local_tab_label", "") or "").strip()
    hint_bounds = str(getattr(state, "last_selected_local_tab_bounds", "") or "").strip()
    current_signature = str(getattr(state, "current_local_tab_signature", "") or "").strip()
    if hint_rid or hint_label:
        if hint_signature and current_signature and hint_signature != current_signature:
            _clear_last_selected_local_tab_hint(state, reason="candidate_set_changed")
        else:
            for candidate in sorted_tab_candidates:
                matched, _ = _local_tab_candidate_matches_identity(
                    candidate,
                    rid=hint_rid,
                    label=hint_label,
                    bounds=hint_bounds,
                )
                if matched:
                    resolved_label = str(candidate.get("label", "") or candidate.get("rid", "") or hint_label or hint_rid).strip()
                    return candidate, "last_selected_hint", resolved_label
            _clear_last_selected_local_tab_hint(state, reason="hint_not_in_candidates")
    row_candidate = _select_active_local_tab_candidate(tab_candidates=sorted_tab_candidates, row=row)
    if isinstance(row_candidate, dict):
        return row_candidate, "current_row", str(row_candidate.get("label", "") or row_candidate.get("rid", "") or "").strip()
    if isinstance(previous_row, dict):
        previous_candidate = _select_active_local_tab_candidate(tab_candidates=sorted_tab_candidates, row=previous_row)
        if isinstance(previous_candidate, dict):
            return previous_candidate, "previous_row", str(previous_candidate.get("label", "") or previous_candidate.get("rid", "") or "").strip()
    if sorted_tab_candidates:
        return sorted_tab_candidates[0], "fallback", str(sorted_tab_candidates[0].get("label", "") or sorted_tab_candidates[0].get("rid", "") or "").strip()
    return None, "none", ""

def _recover_local_tab_state_from_bottom_strip(
    *,
    state: MainLoopState,
    row: dict[str, Any],
    previous_row: dict[str, Any],
    bottom_strip_candidates: list[dict[str, Any]],
    reason: str,
) -> tuple[str, list[dict[str, Any]]]:
    if not bottom_strip_candidates:
        log("[STEP][local_tab_recover_fail] reason='no_horizontal_strip_candidates'")
        return "", []
    sorted_candidates = _sort_local_tab_candidates_left_to_right(bottom_strip_candidates)
    local_tab_signature = _build_local_tab_strip_signature(sorted_candidates)
    if not local_tab_signature:
        log("[STEP][local_tab_recover_fail] reason='missing_signature'")
        return "", []
    active_candidate = _select_active_local_tab_candidate(tab_candidates=sorted_candidates, row=row)
    if (
        isinstance(active_candidate, dict)
        and sorted_candidates
        and active_candidate == sorted_candidates[0]
        and isinstance(previous_row, dict)
        and (str(previous_row.get("focus_view_id", "") or "") or str(previous_row.get("visible_label", "") or ""))
    ):
        previous_active = _select_active_local_tab_candidate(tab_candidates=sorted_candidates, row=previous_row)
        if isinstance(previous_active, dict):
            active_candidate = previous_active
    active_rid = str(active_candidate.get("rid", "") or "").strip() if isinstance(active_candidate, dict) else ""
    active_label = str(active_candidate.get("label", "") or "").strip() if isinstance(active_candidate, dict) else ""
    state.current_local_tab_signature = local_tab_signature
    state.local_tab_candidates_by_signature[local_tab_signature] = list(sorted_candidates)
    if active_rid:
        active_before = _local_tab_state_display(
            rid=str(getattr(state, "current_local_tab_active_rid", "") or ""),
            label=str(getattr(state, "current_local_tab_active_label", "") or ""),
        )
        pending_before = _local_tab_state_display(
            rid=str(getattr(state, "pending_local_tab_rid", "") or ""),
            label=str(getattr(state, "pending_local_tab_label", "") or ""),
        )
        if active_before and active_before != (active_label or active_rid):
            log(
                f"[STEP][local_tab_state_clear] target='committed' "
                f"active_before='{_truncate_debug_text(active_before, 96)}' "
                f"pending_before='{_truncate_debug_text(pending_before, 96)}' "
                "reason='state_recovery' caller='_recover_local_tab_state_from_bottom_strip'"
            )
        state.current_local_tab_active_rid = active_rid
        state.current_local_tab_active_label = active_label
        state.current_local_tab_active_age = 0
    log(
        f"[STEP][local_tab_recover] reason='{reason}' "
        f"candidates='{_truncate_debug_text(_summarize_candidate_labels(sorted_candidates), 120)}' "
        f"active='{_truncate_debug_text(active_label or active_rid, 96)}'"
    )
    return local_tab_signature, sorted_candidates

def _row_matches_pending_local_tab(
    row: dict[str, Any],
    *,
    pending_rid: str,
    pending_label: str,
    pending_bounds: str,
) -> tuple[bool, str]:
    row_rid = str(row.get("focus_view_id", "") or "").strip().lower()
    if row_rid and pending_rid and row_rid == pending_rid.strip().lower():
        return True, "rid"
    compact_row_rid = re.sub(r"[^a-z0-9]+", "", row_rid)
    compact_pending_rid = re.sub(r"[^a-z0-9]+", "", pending_rid.strip().lower())
    if compact_row_rid and compact_pending_rid and (compact_row_rid in compact_pending_rid or compact_pending_rid in compact_row_rid):
        return True, "rid"
    row_label = str(row.get("visible_label", "") or "").strip()
    row_announcement = str(row.get("merged_announcement", "") or "").strip()
    combined_label = " ".join(value for value in (row_label, row_announcement) if value).strip()
    normalized_row_label = _normalize_logical_text(combined_label)
    normalized_pending_label = _normalize_logical_text(pending_label)
    if normalized_row_label and normalized_pending_label and normalized_row_label == normalized_pending_label:
        return True, "label"
    if normalized_row_label and normalized_pending_label and (
        normalized_row_label in normalized_pending_label
        or normalized_pending_label in normalized_row_label
    ):
        return True, "label_contains"
    row_bounds = str(row.get("focus_bounds", "") or "").strip()
    if row_bounds and pending_bounds and _representative_focus_matches(
        focus_node={"boundsInScreen": row_bounds},
        target_rid="",
        target_label="",
        target_bounds=pending_bounds,
    ):
        return True, "bounds"
    return False, "none"

def _maybe_commit_pending_local_tab_progression(state: MainLoopState, row: dict[str, Any]) -> None:
    pending_rid = str(getattr(state, "pending_local_tab_rid", "") or "").strip()
    pending_label = str(getattr(state, "pending_local_tab_label", "") or "").strip()
    pending_signature = str(getattr(state, "pending_local_tab_signature", "") or "").strip()
    if not pending_rid and not pending_label:
        return
    matched, matched_by = _row_matches_pending_local_tab(
        row,
        pending_rid=pending_rid,
        pending_label=pending_label,
        pending_bounds=str(getattr(state, "pending_local_tab_bounds", "") or "").strip(),
    )
    current_label_for_log = str(row.get("visible_label", "") or row.get("merged_announcement", "") or row.get("focus_view_id", "") or "").strip()
    current_focus_for_log = str(row.get("focus_view_id", "") or "").strip()
    log(
        f"[STEP][local_tab_pending_eval] pending='{_truncate_debug_text(pending_label or pending_rid, 96)}' "
        f"current_row='{_truncate_debug_text(current_label_for_log, 96)}' "
        f"current_focus='{_truncate_debug_text(current_focus_for_log, 96)}' "
        f"age={int(getattr(state, 'pending_local_tab_age', 0) or 0)} "
        f"matched={str(matched).lower()} matched_by='{matched_by}'"
    )
    log(
        f"[STEP][local_tab_commit_match] pending='{_truncate_debug_text(pending_label or pending_rid, 96)}' "
        f"current='{_truncate_debug_text(current_label_for_log, 96)}' matched_by='{matched_by}'"
    )
    if matched:
        if pending_signature:
            state.current_local_tab_signature = pending_signature
            state.visited_local_tabs_by_signature.setdefault(pending_signature, set()).add(pending_rid)
        if pending_rid:
            state.current_local_tab_active_rid = pending_rid
        state.current_local_tab_active_label = pending_label
        state.current_local_tab_active_age = 0
        _write_last_selected_local_tab_hint(
            state,
            signature=pending_signature,
            rid=pending_rid,
            label=pending_label,
            bounds=str(getattr(state, "pending_local_tab_bounds", "") or "").strip(),
            reason="pending_resolved",
        )
        log(
            f"[STEP][local_tab_state_write] kind='committed' "
            f"active='{_truncate_debug_text(pending_label or pending_rid, 96)}' "
            "reason='pending_resolved'"
        )
        log(
            f"[STEP][local_tab_commit] active='{_truncate_debug_text(pending_label or pending_rid, 96)}' "
            "reason='pending_progression_resolved'"
        )
        log(
            f"[STEP][local_tab_state_clear] target='pending' "
            f"active_before='{_truncate_debug_text(_local_tab_state_display(rid=str(getattr(state, 'current_local_tab_active_rid', '') or ''), label=str(getattr(state, 'current_local_tab_active_label', '') or '')), 96)}' "
            f"pending_before='{_truncate_debug_text(pending_label or pending_rid, 96)}' "
            "reason='pending_resolved' caller='_maybe_commit_pending_local_tab_progression'"
        )
        state.pending_local_tab_signature = ""
        state.pending_local_tab_rid = ""
        state.pending_local_tab_label = ""
        state.pending_local_tab_bounds = ""
        state.pending_local_tab_age = 0
        _clear_forced_local_tab_navigation(state, reason="pending_resolved")
        return
    pending_age = int(getattr(state, "pending_local_tab_age", 0) or 0) + 1
    state.pending_local_tab_age = pending_age
    if pending_age > 2:
        log(
            f"[STEP][local_tab_state_clear] target='pending' "
            f"active_before='{_truncate_debug_text(_local_tab_state_display(rid=str(getattr(state, 'current_local_tab_active_rid', '') or ''), label=str(getattr(state, 'current_local_tab_active_label', '') or '')), 96)}' "
            f"pending_before='{_truncate_debug_text(pending_label or pending_rid, 96)}' "
            "reason='ttl_expired' caller='_maybe_commit_pending_local_tab_progression'"
        )
        log(
            f"[STEP][local_tab_pending_clear] pending='{_truncate_debug_text(pending_label or pending_rid, 96)}' "
            "reason='expired'"
        )
        state.pending_local_tab_signature = ""
        state.pending_local_tab_rid = ""
        state.pending_local_tab_label = ""
        state.pending_local_tab_bounds = ""
        state.pending_local_tab_age = 0
    else:
        log(
            f"[STEP][local_tab_pending_skip] pending='{_truncate_debug_text(pending_label or pending_rid, 96)}' "
            f"current='{_truncate_debug_text(current_label_for_log, 96)}' reason='not_yet_resolved'"
        )

def _record_pending_local_tab_progression(
    *,
    state: MainLoopState,
    signature: str,
    next_candidate: dict[str, Any],
    reason: str,
) -> tuple[str, str, str]:
    target_rid = str(next_candidate.get("rid", "") or "").strip()
    target_label = str(next_candidate.get("label", "") or "").strip()
    target_bounds = _format_bounds_for_log(_extract_local_tab_candidate_bounds(next_candidate))
    if not target_bounds:
        target_bounds = str(next_candidate.get("bounds", "") or "").strip()
    if not target_bounds:
        target_node = next_candidate.get("node", {})
        if isinstance(target_node, dict):
            target_bounds = _format_bounds_for_log(_extract_local_tab_candidate_bounds(target_node))
            if not target_bounds:
                target_bounds = str(target_node.get("boundsInScreen", "") or target_node.get("bounds", "") or "").strip()
    if not (target_rid or target_label):
        return target_rid, target_label, target_bounds
    state.pending_local_tab_signature = str(signature or "").strip()
    state.pending_local_tab_rid = target_rid
    state.pending_local_tab_label = target_label
    state.pending_local_tab_bounds = target_bounds
    state.pending_local_tab_age = 0
    state.forced_local_tab_target_signature = str(signature or "").strip()
    state.forced_local_tab_target_rid = target_rid
    state.forced_local_tab_target_label = target_label
    state.forced_local_tab_target_bounds = target_bounds
    state.forced_local_tab_attempt_count = 0
    log(
        f"[STEP][local_tab_state_write] kind='pending' "
        f"selected='{_truncate_debug_text(target_label or target_rid, 96)}' "
        f"signature='{_truncate_debug_text(str(signature or ''), 120)}' "
        f"rid='{_truncate_debug_text(target_rid, 96)}' "
        f"label='{_truncate_debug_text(target_label, 96)}' "
        f"bounds='{_truncate_debug_text(target_bounds, 96)}' "
        f"reason='{reason}'"
    )
    log(
        f"[STEP][local_tab_force_navigation_set] target='{_truncate_debug_text(target_label or target_rid, 96)}' "
        "reason='progression_next_tab'"
    )
    return target_rid, target_label, target_bounds

def _format_bounds_for_log(bounds: tuple[int, int, int, int] | None) -> str:
    if not bounds:
        return ""
    return ",".join(str(part) for part in bounds)

def _extract_local_tab_candidate_bounds(candidate: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(candidate, dict):
        return parse_bounds_str(candidate)
    for key in ("focus_bounds", "bounds", "boundsInScreen"):
        bounds = _parse_local_tab_bounds_value(candidate.get(key))
        if bounds:
            return bounds
    nested_candidate = candidate.get("candidate")
    if isinstance(nested_candidate, dict):
        bounds = _extract_local_tab_candidate_bounds(nested_candidate)
        if bounds:
            return bounds
    node = candidate.get("node")
    if isinstance(node, dict) and node is not candidate:
        bounds = _extract_local_tab_candidate_bounds(node)
        if bounds:
            return bounds
    return None

def _parse_local_tab_bounds_value(value: Any) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    parsed = parse_bounds_str(value)
    if parsed:
        return parsed
    if isinstance(value, dict):
        for keys in (("left", "top", "right", "bottom"), ("x1", "y1", "x2", "y2")):
            try:
                l, t, r, b = (int(value.get(key)) for key in keys)
            except Exception:
                continue
            if r > l and b > t:
                return l, t, r, b
        return None
    value_text = str(value).strip()
    if not value_text:
        return None
    numbers = [int(part) for part in re.findall(r"-?\d+", value_text)]
    if len(numbers) >= 4:
        l, t, r, b = numbers[:4]
        if r > l and b > t:
            return l, t, r, b
    return None

def _collect_local_tab_viewport_bounds(client: A11yAdbClient, dev: str, target_bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    max_right = max(target_bounds[2], 2)
    max_bottom = max(target_bounds[3], 2)
    dump_fn = getattr(client, "dump_tree", None)
    if not callable(dump_fn):
        return max_right, max_bottom
    try:
        nodes = dump_fn(dev=dev)
    except Exception:
        nodes = []
    stack = list(nodes) if isinstance(nodes, list) else []
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        bounds = _extract_local_tab_candidate_bounds(node)
        if bounds:
            max_right = max(max_right, bounds[2])
            max_bottom = max(max_bottom, bounds[3])
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(children)
    return max_right, max_bottom

def _tap_local_tab_bounds_center(
    *,
    client: A11yAdbClient,
    dev: str,
    target: str,
    target_bounds: tuple[int, int, int, int] | None,
) -> bool | None:
    if not target_bounds:
        log(
            f"[STEP][local_tab_target_activate_skip] method='tap_bounds_center' "
            "reason='bounds_missing'"
        )
        return None
    tap_xy_fn = getattr(client, "tap_xy_adb", None)
    if not callable(tap_xy_fn):
        log(
            f"[STEP][local_tab_target_activate_skip] method='tap_bounds_center' "
            "reason='tap_primitive_missing'"
        )
        return None
    viewport_width, viewport_height = _collect_local_tab_viewport_bounds(client, dev, target_bounds)
    if viewport_width <= 1 or viewport_height <= 1:
        log(
            f"[STEP][local_tab_target_activate_skip] method='tap_bounds_center' "
            "reason='viewport_unknown'"
        )
        return None
    l, t, r, b = target_bounds
    center_x = (l + r) // 2
    center_y = (t + b) // 2
    tap_x = min(max(center_x, 1), max(viewport_width - 1, 1))
    tap_y = min(max(center_y, 1), max(viewport_height - 1, 1))
    log(
        f"[STEP][local_tab_target_activate] target='{_truncate_debug_text(target, 96)}' "
        f"method='tap_bounds_center' bounds='{_format_bounds_for_log(target_bounds)}' tap='{tap_x},{tap_y}'"
    )
    try:
        return bool(tap_xy_fn(dev=dev, x=tap_x, y=tap_y))
    except Exception:
        return False

def _clear_forced_local_tab_navigation(state: MainLoopState, *, reason: str) -> None:
    target = _local_tab_state_display(
        rid=str(getattr(state, "forced_local_tab_target_rid", "") or ""),
        label=str(getattr(state, "forced_local_tab_target_label", "") or ""),
    )
    if target:
        log(
            f"[STEP][local_tab_force_navigation_clear] target='{_truncate_debug_text(target, 96)}' "
            f"reason='{reason}'"
        )
    state.forced_local_tab_target_signature = ""
    state.forced_local_tab_target_rid = ""
    state.forced_local_tab_target_label = ""
    state.forced_local_tab_target_bounds = ""
    state.forced_local_tab_attempt_count = 0

def _forced_local_tab_target_matches_row(state: MainLoopState, row: dict[str, Any]) -> bool:
    matched, _ = _row_matches_pending_local_tab(
        row,
        pending_rid=str(getattr(state, "forced_local_tab_target_rid", "") or ""),
        pending_label=str(getattr(state, "forced_local_tab_target_label", "") or ""),
        pending_bounds=str(getattr(state, "forced_local_tab_target_bounds", "") or ""),
    )
    return matched

def _reset_content_phase_after_tab_switch(
    state: MainLoopState,
    *,
    active_label: str,
    active_rid: str,
    active_signature: str = "",
    active_bounds: str = "",
) -> None:
    def clear_attr(name: str, default: Any) -> None:
        value = getattr(state, name, None)
        if hasattr(value, "clear"):
            value.clear()
        else:
            setattr(state, name, default)

    state.fail_count = 0
    state.same_count = 0
    state.prev_fingerprint = ("", "", "")
    state.previous_step_row = {}
    clear_attr("recent_representative_signatures", deque())
    clear_attr("consumed_representative_signatures", set())
    state.visited_logical_signatures = set()
    state.consumed_cluster_signatures = set()
    state.consumed_cluster_logical_signatures = set()
    focus_state = _focus_realign_state(state)
    if focus_state is state:
        clear_attr("recent_focus_realign_signatures", set())
        clear_attr("failed_focus_realign_signatures", set())
        clear_attr("recent_focus_realign_clusters", set())
        clear_attr("cluster_title_fallback_applied", set())
    else:
        focus_state.recent_focus_realign_signatures = set()
        focus_state.failed_focus_realign_signatures = set()
        focus_state.recent_focus_realign_clusters = set()
        focus_state.cluster_title_fallback_applied = set()
    scroll_state = _scroll_state(state)
    if scroll_state is state:
        clear_attr("recent_scroll_fallback_signatures", set())
        clear_attr("last_scroll_fallback_attempted_signatures", set())
    else:
        scroll_state.recent_scroll_fallback_signatures = set()
        scroll_state.last_scroll_fallback_attempted_signatures = set()
    _clear_active_container_group(state, reason="local_tab_transition")
    state.completed_container_groups = set()
    scroll_state.scroll_ready_retry_counts = {}
    scroll_state.pending_scroll_ready_cluster_signature = ""
    state.content_phase_grace_steps = 2
    _write_last_selected_local_tab_hint(
        state,
        signature=active_signature or str(getattr(state, "current_local_tab_signature", "") or ""),
        rid=active_rid,
        label=active_label,
        bounds=active_bounds,
        reason="activation_success",
    )
    log(
        f"[STEP][local_tab_content_phase_reset] "
        f"active='{_truncate_debug_text(active_label or active_rid, 96)}' reason='tab_switch'"
    )
    log(
        f"[STEP][content_phase_grace_start] steps=2 "
        f"active='{_truncate_debug_text(active_label or active_rid, 96)}'"
    )

def _commit_forced_local_tab_target_success(state: MainLoopState) -> None:
    target_signature = str(getattr(state, "forced_local_tab_target_signature", "") or "").strip()
    target_rid = str(getattr(state, "forced_local_tab_target_rid", "") or "").strip()
    target_label = str(getattr(state, "forced_local_tab_target_label", "") or "").strip()
    if target_signature and target_rid:
        state.visited_local_tabs_by_signature.setdefault(target_signature, set()).add(target_rid)
    if target_signature:
        state.current_local_tab_signature = target_signature
    if target_rid:
        state.current_local_tab_active_rid = target_rid
    state.current_local_tab_active_label = target_label
    state.current_local_tab_active_age = 0
    _reset_content_phase_after_tab_switch(
        state,
        active_label=target_label,
        active_rid=target_rid,
        active_signature=target_signature,
        active_bounds=str(getattr(state, "forced_local_tab_target_bounds", "") or "").strip(),
    )
    state.pending_local_tab_signature = ""
    state.pending_local_tab_rid = ""
    state.pending_local_tab_label = ""
    state.pending_local_tab_bounds = ""
    state.pending_local_tab_age = 0
    log(
        f"[STEP][local_tab_commit] active='{_truncate_debug_text(target_label or target_rid, 96)}' "
        "reason='target_activation_success'"
    )

def _activate_forced_local_tab_target(
    *,
    client: A11yAdbClient,
    dev: str,
    state: MainLoopState,
    step_idx: int,
    wait_seconds: float,
    announcement_wait_seconds: float,
    announcement_idle_wait_seconds: float,
    announcement_max_extra_wait_seconds: float,
) -> dict[str, Any] | None:
    target = _local_tab_state_display(
        rid=str(getattr(state, "forced_local_tab_target_rid", "") or ""),
        label=str(getattr(state, "forced_local_tab_target_label", "") or ""),
    )
    target_rid = str(getattr(state, "forced_local_tab_target_rid", "") or "").strip()
    target_label = str(getattr(state, "forced_local_tab_target_label", "") or "").strip()
    if not target:
        return None
    attempt = int(getattr(state, "forced_local_tab_attempt_count", 0) or 0) + 1
    if attempt > 2:
        _clear_forced_local_tab_navigation(state, reason="max_attempts_reached")
        return None
    state.forced_local_tab_attempt_count = attempt

    def collect_after_action() -> dict[str, Any]:
        return client.collect_focus_step(
            dev=dev,
            step_index=step_idx,
            move=False,
            direction="next",
            wait_seconds=wait_seconds,
            announcement_wait_seconds=announcement_wait_seconds,
            announcement_idle_wait_seconds=announcement_idle_wait_seconds,
            announcement_max_extra_wait_seconds=announcement_max_extra_wait_seconds,
        )

    last_row: dict[str, Any] | None = None
    raw_target_bounds = getattr(state, "forced_local_tab_target_bounds", "") or ""
    target_bounds = _parse_local_tab_bounds_value(raw_target_bounds)
    if raw_target_bounds and not target_bounds:
        log(
            f"[STEP][local_tab_target_activate_skip] method='tap_bounds_center' "
            "reason='bounds_parse_failed'"
        )
    tap_ok = _tap_local_tab_bounds_center(
        client=client,
        dev=dev,
        target=target,
        target_bounds=target_bounds,
    ) if target_bounds else None
    if tap_ok:
        last_row = collect_after_action()
        matched, matched_by = _row_matches_pending_local_tab(
            last_row,
            pending_rid=target_rid,
            pending_label=target_label,
            pending_bounds=str(getattr(state, "forced_local_tab_target_bounds", "") or ""),
        )
        if matched:
            log(
                f"[STEP][local_tab_target_activate_success] target='{_truncate_debug_text(target, 96)}' "
                f"matched_by='{matched_by}'"
            )
            _commit_forced_local_tab_target_success(state)
            log(
                f"[STEP][local_tab_force_navigation_resolved] target='{_truncate_debug_text(target, 96)}'"
            )
            _clear_forced_local_tab_navigation(state, reason="resolved")
            return last_row
        log(
            f"[STEP][local_tab_target_activate_no_match] target='{_truncate_debug_text(target, 96)}' "
            "method='tap_bounds_center' reason='focus_not_target_after_tap'"
        )
    elif not raw_target_bounds:
        log(
            f"[STEP][local_tab_target_activate_skip] method='tap_bounds_center' "
            "reason='bounds_missing'"
        )
    action_attempts: list[tuple[str, Callable[[], bool]]] = []
    select_fn = getattr(client, "select", None)
    if callable(select_fn) and target_rid:
        action_attempts.append(("select_rid", lambda: bool(select_fn(dev=dev, name=target_rid, type_="r", wait_=_TRANSITION_FAST_ACTION_WAIT_SECONDS))))
    if callable(select_fn) and target_label:
        action_attempts.append(("select_label", lambda: bool(select_fn(dev=dev, name=target_label, type_="a", wait_=_TRANSITION_FAST_ACTION_WAIT_SECONDS))))

    for method, action_fn in action_attempts:
        log(
            f"[STEP][local_tab_target_activate] target='{_truncate_debug_text(target, 96)}' "
            f"method='{method}'"
        )
        try:
            action_ok = bool(action_fn())
        except Exception:
            action_ok = False
        if not action_ok:
            continue
        last_row = collect_after_action()
        matched, matched_by = _row_matches_pending_local_tab(
            last_row,
            pending_rid=target_rid,
            pending_label=target_label,
            pending_bounds=str(getattr(state, "forced_local_tab_target_bounds", "") or ""),
        )
        if matched:
            log(
                f"[STEP][local_tab_target_activate_success] target='{_truncate_debug_text(target, 96)}' "
                f"matched_by='{matched_by}'"
            )
            _commit_forced_local_tab_target_success(state)
            log(
                f"[STEP][local_tab_force_navigation_resolved] target='{_truncate_debug_text(target, 96)}'"
            )
            _clear_forced_local_tab_navigation(state, reason="resolved")
            return last_row

    log(
        f"[STEP][local_tab_target_activate_fail] target='{_truncate_debug_text(target, 96)}' "
        "reason='no_match_after_all_methods' fallback='move_smart_next'"
    )
    move_fn = getattr(client, "move_focus_smart", None)
    if callable(move_fn):
        log(
            f"[STEP][local_tab_force_navigation_retry] target='{_truncate_debug_text(target, 96)}' "
            f"attempt={attempt}"
        )
        try:
            move_fn(dev=dev, direction="next")
        except Exception:
            pass
        last_row = collect_after_action()
        matched, matched_by = _row_matches_pending_local_tab(
            last_row,
            pending_rid=target_rid,
            pending_label=target_label,
            pending_bounds=str(getattr(state, "forced_local_tab_target_bounds", "") or ""),
        )
        if matched:
            log(
                f"[STEP][local_tab_target_activate_success] target='{_truncate_debug_text(target, 96)}' "
                f"matched_by='{matched_by}'"
            )
            _commit_forced_local_tab_target_success(state)
            log(
                f"[STEP][local_tab_force_navigation_resolved] target='{_truncate_debug_text(target, 96)}'"
            )
            _clear_forced_local_tab_navigation(state, reason="resolved")
            return last_row
    if attempt >= 2:
        _clear_forced_local_tab_navigation(state, reason="max_attempts_reached")
    return last_row

def _is_current_focus_on_local_tab_strip(state: MainLoopState, row: dict[str, Any]) -> bool:
    local_tab_signature = str(getattr(state, "current_local_tab_signature", "") or "").strip()
    if not local_tab_signature:
        return False
    tab_candidates = getattr(state, "local_tab_candidates_by_signature", {}).get(local_tab_signature, [])
    if not tab_candidates:
        return False
    row_rid = str(row.get("focus_view_id", "") or "").strip().lower()
    row_label = _canonicalize_local_tab_label(
        str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    ).lower()
    for candidate in tab_candidates:
        candidate_rid = str(candidate.get("rid", "") or "").strip().lower()
        candidate_label = _canonicalize_local_tab_label(str(candidate.get("label", "") or "").strip()).lower()
        if row_rid and candidate_rid and row_rid == candidate_rid:
            return True
        if row_label and candidate_label and row_label == candidate_label:
            return True
    return False

def _is_chrome_like_candidate(
    *,
    label: str,
    resource_id: str,
    class_name: str,
    actionable: bool,
    button_like: bool,
    card_like: bool,
    center_y: int,
    top_header_band: int,
    width_ratio: float,
) -> bool:
    normalized_label = re.sub(r"\s+", " ", str(label or "").strip()).lower()
    if not normalized_label:
        return False
    chrome_tokens = ("navigate up", "more options", "toolbar", "app bar", "overflow", "profile", "back")
    if any(token in normalized_label for token in chrome_tokens):
        return True
    chrome_resource_tokens = ("toolbar", "appbar", "action", "overflow", "navigate", "header", "menu")
    resource_chrome = any(token in resource_id or token in class_name for token in chrome_resource_tokens)
    if center_y > top_header_band:
        return False
    if resource_chrome:
        return True
    if actionable and (button_like or width_ratio <= 0.45):
        return True
    return bool(not card_like and len(normalized_label) <= 24)

def _is_row_top_chrome_candidate(row: dict[str, Any]) -> bool:
    label = str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    meta = _extract_cta_grace_focus_meta(row)
    bounds = parse_bounds_str(str(meta["bounds"]).strip())
    if not bounds or not label:
        return False
    left, top, right, bottom = bounds
    width = max(1, right - left)
    center_y = (top + bottom) // 2
    resource_id = str(meta["resource_id"]).lower()
    class_name = str(meta["class_name"]).lower()
    actionable = bool(meta["actionable"])
    button_like = bool(
        "button" in resource_id
        or "button" in class_name
        or "tab" in resource_id
        or "segment" in resource_id
        or "navigation" in resource_id
    )
    card_like = bool(
        "card" in resource_id
        or "card" in class_name
        or "item" in resource_id
        or "item" in class_name
        or "layout" in class_name
        or "frame" in class_name
        or bool(meta["descendant_actionable"])
    )
    return _is_chrome_like_candidate(
        label=label,
        resource_id=resource_id,
        class_name=class_name,
        actionable=actionable,
        button_like=button_like,
        card_like=card_like,
        center_y=center_y,
        top_header_band=220,
        width_ratio=min(1.0, width / 1080.0),
    )

def _is_passive_status_text(label: str) -> bool:
    normalized_label = re.sub(r"\s+", " ", str(label or "").strip()).lower()
    if not normalized_label:
        return False
    exact_status_phrases = (
        "active now",
        "inactive",
        "offline",
        "online",
        "connected",
        "disconnected",
        "available",
        "unavailable",
        "updated just now",
        "just now",
        "no activity",
        "no data",
        "no events",
        "no history",
        "nothing yet",
        "not available",
        "waiting",
        "loading",
        "pending",
    )
    if normalized_label in exact_status_phrases:
        return True
    if re.fullmatch(r"no\s+[a-z0-9][a-z0-9\s\-]{0,24}", normalized_label):
        return True
    passive_explanation_patterns = (
        r"\bwill be measured again after\b",
        r"\bavailable after\b",
        r"\bupdated later\b",
        r"\btry again later\b",
        r"\bwaiting for\b",
        r"\bwill be available after\b",
        r"\bmeasured again after\b",
    )
    if any(re.search(pattern, normalized_label) for pattern in passive_explanation_patterns):
        return True
    return bool(len(normalized_label) <= 18 and any(phrase in normalized_label for phrase in exact_status_phrases))

def _select_better_cluster_representative(
    *,
    selected_candidate: dict[str, Any],
    state: MainLoopState,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    cluster_signature = _candidate_cluster_signature(selected_candidate)
    if not cluster_signature:
        return None
    focus_state = _focus_realign_state(state)
    if cluster_signature in set(getattr(focus_state, "cluster_title_fallback_applied", set()) or set()):
        return None
    if str(selected_candidate.get("cluster_role", "") or "") != "title":
        return None
    if normalize_move_result(row) not in {"failed", "no_progress"}:
        return None
    cluster_members = selected_candidate.get("cluster_members")
    if not isinstance(cluster_members, list) or not cluster_members:
        return None
    selected_signature = _candidate_object_signature(selected_candidate)
    fallback_candidates = [
        candidate
        for candidate in cluster_members
        if _candidate_object_signature(candidate) != selected_signature
        and str(candidate.get("cluster_role", "") or "") in {"actionable", "descendant_actionable", "container"}
    ]
    if not fallback_candidates:
        return None
    return max(fallback_candidates, key=_cluster_candidate_sort_key)

def _local_tab_candidate_label(candidate: dict[str, Any]) -> str:
    label = str(candidate.get("label", "") or "").strip()
    if label:
        return label
    node = candidate.get("node", {})
    if isinstance(node, dict):
        for key in ("text", "contentDescription", "content_desc", "merged_announcement"):
            label = str(node.get(key, "") or "").strip()
            if label:
                return label
    return ""

def _local_tab_candidate_bool(candidate: dict[str, Any], keys: tuple[str, ...], default: bool = False) -> bool:
    values: list[Any] = [candidate.get(key) for key in keys]
    node = candidate.get("node", {})
    if isinstance(node, dict):
        values.extend(node.get(key) for key in keys)
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
    return default

def _is_global_bottom_nav_label(label: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(label or "").strip()).lower()
    normalized = re.sub(r"\bselected\b", "", normalized).strip()
    return normalized in {"home", "devices", "life", "routines", "menu"}

def _prepare_local_tab_strip_candidate(
    candidate: dict[str, Any],
    index: int,
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    bounds = _extract_local_tab_candidate_bounds(candidate)
    if not bounds:
        return None
    left, top, right, bottom = bounds
    if right <= left or bottom <= top:
        return None
    label = _local_tab_candidate_label(candidate)
    visible = _local_tab_candidate_bool(
        candidate,
        keys=("isVisibleToUser", "visibleToUser", "visible"),
        default=True,
    )
    clickable = _local_tab_candidate_bool(candidate, keys=("clickable", "effectiveClickable"), default=False)
    focusable = _local_tab_candidate_bool(candidate, keys=("focusable",), default=False)
    if not visible or not clickable:
        return None
    return {
        "index": index,
        "candidate": candidate,
        "label": label,
        "canonical_label": _canonicalize_local_tab_label(label),
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": max(1, right - left),
        "height": max(1, bottom - top),
        "center_x": (left + right) // 2,
        "center_y": (top + bottom) // 2,
        "focusable": focusable,
    }

def _local_tab_strip_group_is_structural(
    group: list[dict[str, Any]],
    *,
    viewport_width: int,
    viewport_bottom: int,
) -> bool:
    if not (2 <= len(group) <= 4):
        return False
    labels = [str(item.get("canonical_label", "") or item.get("label", "") or "").strip() for item in group]
    if labels and all(_is_global_bottom_nav_label(label) for label in labels):
        return False
    heights = [int(item["height"]) for item in group]
    widths = [int(item["width"]) for item in group]
    centers_y = [int(item["center_y"]) for item in group]
    tops = [int(item["top"]) for item in group]
    bottoms = [int(item["bottom"]) for item in group]
    avg_height = sum(heights) / float(max(1, len(heights)))
    if max(heights) > 240 or min(heights) < 36:
        return False
    if min(heights) and max(heights) / float(min(heights)) > 1.35:
        return False
    if max(centers_y) - min(centers_y) > max(32, int(avg_height * 0.30)):
        return False
    if min(tops) < max(880, int(viewport_bottom * 0.72)):
        return False
    if max(bottoms) < int(viewport_bottom * 0.88):
        return False
    if min(widths) and max(widths) / float(min(widths)) > 1.45:
        return False
    ordered = sorted(group, key=lambda item: (int(item["left"]), int(item["center_x"])))
    for previous, current in zip(ordered, ordered[1:]):
        overlap = int(previous["right"]) - int(current["left"])
        if overlap > max(12, int(min(previous["width"], current["width"]) * 0.08)):
            return False
    strip_left = min(int(item["left"]) for item in ordered)
    strip_right = max(int(item["right"]) for item in ordered)
    strip_width = max(1, strip_right - strip_left)
    if strip_width < int(max(1, viewport_width) * 0.55):
        return False
    center_gaps = [
        int(current["center_x"]) - int(previous["center_x"])
        for previous, current in zip(ordered, ordered[1:])
    ]
    if center_gaps and min(center_gaps) <= 0:
        return False
    if len(center_gaps) >= 2 and min(center_gaps) and max(center_gaps) / float(min(center_gaps)) > 1.55:
        return False
    identities = {
        (
            str(item["candidate"].get("rid", "") or "").strip().lower()
            or _normalize_logical_text(str(item.get("canonical_label", "") or item.get("label", "") or ""))
            or f"{item['left']},{item['top']},{item['right']},{item['bottom']}"
        )
        for item in ordered
    }
    if len(identities) < len(ordered):
        return False
    return True

def _filter_local_tab_strip_candidates(
    raw_candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared = [
        prepared_candidate
        for index, candidate in enumerate(raw_candidates)
        if (prepared_candidate := _prepare_local_tab_strip_candidate(candidate, index)) is not None
    ]
    if len(prepared) < 2:
        return [], list(raw_candidates)
    if (
        len(prepared) >= 5
        and sum(1 for candidate in prepared if _is_global_bottom_nav_label(str(candidate.get("label", "") or ""))) >= 4
    ):
        return [], list(raw_candidates)
    viewport_width = max(1080, *(int(candidate["right"]) for candidate in prepared))
    viewport_bottom = max(1200, *(int(candidate["bottom"]) for candidate in prepared))
    best_group: list[dict[str, Any]] = []
    best_key: tuple[int, int, int, int] = (-1, -1, -1, -1)
    for anchor in prepared:
        anchor_height = max(1, int(anchor["height"]))
        anchor_center_y = int(anchor["center_y"])
        group = [
            candidate
            for candidate in prepared
            if abs(int(candidate["center_y"]) - anchor_center_y) <= max(32, int(anchor_height * 0.30))
            and 0.74 <= (int(candidate["height"]) / float(anchor_height)) <= 1.35
        ]
        if len(group) > 4:
            group = sorted(group, key=lambda item: int(item["bottom"]), reverse=True)[:4]
        group = sorted(group, key=lambda item: int(item["left"]))
        if not _local_tab_strip_group_is_structural(
            group,
            viewport_width=viewport_width,
            viewport_bottom=viewport_bottom,
        ):
            continue
        strip_width = max(int(item["right"]) for item in group) - min(int(item["left"]) for item in group)
        focusable_count = sum(1 for item in group if bool(item.get("focusable")))
        bottom = max(int(item["bottom"]) for item in group)
        key = (len(group), strip_width, focusable_count, bottom)
        if key > best_key:
            best_key = key
            best_group = group
    if not best_group:
        return [], list(raw_candidates)
    accepted_indexes = {int(item["index"]) for item in best_group}
    accepted: list[dict[str, Any]] = []
    for item in sorted(best_group, key=lambda value: int(value["left"])):
        candidate = dict(item["candidate"])
        original_label = str(candidate.get("label", "") or item.get("label", "") or "").strip()
        canonical_label = str(item.get("canonical_label", "") or original_label).strip()
        candidate["label"] = canonical_label
        candidate["original_label"] = original_label
        if canonical_label != original_label:
            candidate["label_canonicalized"] = True
        candidate.setdefault("left", int(item["left"]))
        candidate.setdefault("right", int(item["right"]))
        candidate.setdefault("top", int(item["top"]))
        candidate.setdefault("bottom", int(item["bottom"]))
        candidate.setdefault("center_x", int(item["center_x"]))
        candidate.setdefault("center_y", int(item["center_y"]))
        candidate.setdefault("width", int(item["width"]))
        candidate.setdefault("height", int(item["height"]))
        accepted.append(candidate)
    rejected = [candidate for index, candidate in enumerate(raw_candidates) if index not in accepted_indexes]
    return accepted, rejected

def _is_row_persistent_bottom_strip_candidate(row: dict[str, Any]) -> bool:
    meta = _extract_cta_grace_focus_meta(row)
    label = str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    resource_id = str(meta["resource_id"]).lower()
    class_name = str(meta["class_name"]).lower()
    label_word_count = len([token for token in re.split(r"\s+", _canonicalize_local_tab_label(label)) if token])
    bounds = parse_bounds_str(str(meta["bounds"]).strip())
    if not meta["actionable"] or not bounds or not label:
        return False
    width = max(1, bounds[2] - bounds[0])
    height = max(1, bounds[3] - bounds[1])
    center_y = (bounds[1] + bounds[3]) // 2
    compact = width <= 520 and height <= 220
    button_like = bool(
        "button" in resource_id
        or "button" in class_name
        or "tab" in resource_id
        or "segment" in resource_id
        or "navigation" in resource_id
    )
    return bool(center_y >= 900 and compact and label_word_count <= 3 and (button_like or len(label.strip()) <= 24))

def _maybe_reprioritize_persistent_bottom_strip_row(
    *,
    row: dict[str, Any],
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    state: MainLoopState,
    step_idx: int,
    scenario_perf: ScenarioPerfStats | None = None,
) -> dict[str, Any]:
    _maybe_commit_pending_local_tab_progression(state, row)
    scenario_type = str(tab_cfg.get("scenario_type", "content") or "content").strip().lower()
    row_signature = _build_row_object_signature(row)
    current_row_is_passive_status = _is_passive_status_text(
        str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    )
    current_row_is_top_chrome = _is_row_top_chrome_candidate(row)
    current_row_is_low_value_leaf = _is_low_value_leaf_text(
        str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip(),
        actionable=bool(row.get("focus_clickable") or row.get("focus_focusable") or row.get("focus_effective_clickable")),
        descendant_actionable=bool(
            isinstance(row.get("focus_node", {}), dict)
            and (
                row.get("focus_node", {}).get("hasClickableDescendant")
                or row.get("focus_node", {}).get("hasFocusableDescendant")
            )
        ),
        width=max(1, (parse_bounds_str(str(row.get("focus_bounds", "") or "").strip()) or (0, 0, 1, 1))[2] - (parse_bounds_str(str(row.get("focus_bounds", "") or "").strip()) or (0, 0, 1, 1))[0]),
        height=max(1, (parse_bounds_str(str(row.get("focus_bounds", "") or "").strip()) or (0, 0, 1, 1))[3] - (parse_bounds_str(str(row.get("focus_bounds", "") or "").strip()) or (0, 0, 1, 1))[1]),
    )
    current_row_recent_revisit = bool(row_signature and row_signature in set(getattr(state, "recent_representative_signatures", []) or []))
    if scenario_type == "global_nav" or not (
        _is_row_persistent_bottom_strip_candidate(row)
        or current_row_is_low_value_leaf
        or current_row_recent_revisit
        or current_row_is_passive_status
        or current_row_is_top_chrome
    ):
        needs_detection_only = True
    else:
        needs_detection_only = False
    dump_tree_fn = getattr(client, "dump_tree", None)
    if not callable(dump_tree_fn):
        return row
    try:
        nodes = dump_tree_fn(dev=dev)
    except Exception:
        return row
    content_candidates, bottom_strip_candidates, candidate_groups_meta = _collect_step_candidate_priority_groups(
        nodes,
        consumed_cluster_signatures=set(getattr(state, "consumed_cluster_signatures", set()) or set()),
        consumed_cluster_logical_signatures=set(getattr(state, "consumed_cluster_logical_signatures", set()) or set()),
    )
    local_tab_signature = ""
    if content_candidates and bottom_strip_candidates:
        local_tab_signature = _build_local_tab_strip_signature(bottom_strip_candidates)
        if local_tab_signature:
            state.local_tab_candidates_by_signature[local_tab_signature] = list(bottom_strip_candidates)
            active_candidate = _select_active_local_tab_candidate(tab_candidates=bottom_strip_candidates, row=row)
            active_rid = str(active_candidate.get("rid", "") or "").strip() if isinstance(active_candidate, dict) else ""
            active_label = str(active_candidate.get("label", "") or "").strip() if isinstance(active_candidate, dict) else ""
            if active_rid:
                state.current_local_tab_signature = local_tab_signature
                committed_active_rid = str(getattr(state, "current_local_tab_active_rid", "") or "").strip()
                committed_active_age = int(getattr(state, "current_local_tab_active_age", 0) or 0)
                if committed_active_rid and committed_active_age <= LOCAL_TAB_ACTIVE_TTL_STEPS:
                    active_rid = committed_active_rid
                    active_label = str(getattr(state, "current_local_tab_active_label", "") or active_label)
                    log(
                        f"[STEP][local_tab_active_override] active='{_truncate_debug_text(active_label or active_rid, 96)}' "
                        "reason='committed_state_priority'"
                    )
                else:
                    active_before = _local_tab_state_display(
                        rid=str(getattr(state, "current_local_tab_active_rid", "") or ""),
                        label=str(getattr(state, "current_local_tab_active_label", "") or ""),
                    )
                    if active_before and active_before != (active_label or active_rid):
                        log(
                            f"[STEP][local_tab_state_clear] target='committed' "
                            f"active_before='{_truncate_debug_text(active_before, 96)}' "
                            f"pending_before='{_truncate_debug_text(_local_tab_state_display(rid=str(getattr(state, 'pending_local_tab_rid', '') or ''), label=str(getattr(state, 'pending_local_tab_label', '') or '')), 96)}' "
                            "reason='state_recovery' caller='_maybe_reprioritize_persistent_bottom_strip_row'"
                        )
                    state.current_local_tab_active_rid = active_rid
                    state.current_local_tab_active_label = active_label
                    state.current_local_tab_active_age = 0
                if (
                    local_tab_signature != str(row.get("local_tab_signature_logged", "") or "").strip()
                    or bool(_is_row_persistent_bottom_strip_candidate(row))
                ):
                    raw_tab_labels = candidate_groups_meta.get("raw_bottom_strip_candidates", [])
                    rejected_tab_labels = candidate_groups_meta.get("rejected_bottom_strip_candidates", [])
                    accepted_tab_labels = [str(candidate.get("label", "") or "").strip() for candidate in bottom_strip_candidates]
                    log(
                        f"[STEP][local_tab_strip_members] raw_candidates='{_truncate_debug_text('|'.join(raw_tab_labels[:5]), 120)}' "
                        f"accepted_tabs='{_truncate_debug_text('|'.join(accepted_tab_labels[:5]), 120)}' "
                        f"rejected='{_truncate_debug_text('|'.join(rejected_tab_labels[:5]), 120)}' "
                        "reason='non_tab_action_excluded'"
                    )
                    active_reason = "selected_or_focused_member" if isinstance(active_candidate, dict) and bool(active_candidate.get("node", {}).get("selected")) else "current_row_member_match"
                    if not active_label and accepted_tab_labels:
                        active_reason = "fallback_first_member"
                    log(
                        f"[STEP][local_tab_strip] tabs='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in bottom_strip_candidates[:4]), 120)}' "
                        f"active='{_truncate_debug_text(active_label or active_rid, 96)}' "
                        "deferred=true reason='local_tab_strip_separated_from_content'"
                    )
                    log(
                        f"[STEP][local_tab_active] tabs='{_truncate_debug_text('|'.join(accepted_tab_labels[:4]), 120)}' "
                        f"active='{_truncate_debug_text(active_label or active_rid, 96)}' "
                        f"reason='{active_reason}'"
                    )
                    row["local_tab_signature_logged"] = local_tab_signature
    if needs_detection_only:
        return row
    if not content_candidates:
        return row
    raw_cluster_candidates = [str(value or "").strip() for value in candidate_groups_meta.get("raw_cluster_candidates", []) if str(value or "").strip()]
    clustered_candidates = [str(value or "").strip() for value in candidate_groups_meta.get("clustered_candidates", []) if str(value or "").strip()]
    cluster_representatives = candidate_groups_meta.get("cluster_representatives", [])
    if raw_cluster_candidates and clustered_candidates and len(raw_cluster_candidates) > len(clustered_candidates):
        log(
            f"[STEP][cluster_candidates] all='{_truncate_debug_text('|'.join(raw_cluster_candidates[:5]), 120)}' "
            f"clustered='{_truncate_debug_text('|'.join(clustered_candidates[:5]), 120)}'"
        )
        for cluster_label, selected_cluster_label, cluster_reason in cluster_representatives[:3]:
            log(
                f"[STEP][cluster_representative] cluster='{_truncate_debug_text(str(cluster_label or ''), 96)}' "
                f"selected='{_truncate_debug_text(str(selected_cluster_label or ''), 96)}' "
                f"reason='{cluster_reason}'"
            )
    cluster_pre_filter_skipped = [
        str(value or "").strip()
        for value in candidate_groups_meta.get("cluster_pre_filter_skipped", [])
        if str(value or "").strip()
    ]
    if cluster_pre_filter_skipped:
        log(
            f"[STEP][cluster_pre_filter] skipped='{_truncate_debug_text('|'.join(cluster_pre_filter_skipped[:5]), 120)}' "
            f"count={len(cluster_pre_filter_skipped)} reason='consumed_cluster_early_skip'"
        )
    chrome_candidates = [str(value or "").strip() for value in candidate_groups_meta.get("chrome_excluded_candidates", []) if str(value or "").strip()]
    container_promoted = [str(value or "").strip() for value in candidate_groups_meta.get("container_promoted_candidates", []) if str(value or "").strip()]
    priority_containers = [str(value or "").strip() for value in candidate_groups_meta.get("top_priority_container_candidates", []) if str(value or "").strip()]
    filtered_meta = _filter_content_candidates_for_phase(content_candidates, state=state)
    filtered_candidates = list(filtered_meta["selection_candidates"])
    filtered_candidates, spatial_reason, continuity_reason = _apply_spatial_priority_to_candidates(
        filtered_candidates,
        row=row,
        state=state,
    )
    passive_status_candidates = [str(candidate.get("label", "") or "").strip() for candidate in filtered_meta["status_candidates"]]
    section_header_candidates = [str(candidate.get("label", "") or "").strip() for candidate in filtered_meta.get("section_header_deferred", [])]
    visited_rejected = [candidate for candidate in filtered_meta.get("visited_rejected", [])]
    leaf_candidates = [candidate for candidate in filtered_meta["leaf_rejected"]]
    revisit_rejected = [candidate for candidate in filtered_meta["revisit_rejected"]]
    cluster_consumed_rejected = [candidate for candidate in filtered_meta.get("cluster_consumed_rejected", [])]
    consumed_rejected = [candidate for candidate in filtered_meta["consumed_rejected"]]
    if chrome_candidates and filtered_candidates:
        log(
            f"[STEP][chrome_penalty] deprioritized='{_truncate_debug_text('|'.join(chrome_candidates[:4]), 120)}' "
            "reason='top_chrome_during_content_phase'"
        )
        log(
            f"[STEP][content_phase_eval] content_present={str(bool(filtered_candidates)).lower()} "
            f"chrome_present={str(bool(chrome_candidates)).lower()} chrome_excluded=true"
        )
    for promoted_label in container_promoted[:5]:
        log(
            f"[STEP][container_candidate_promoted] label='{_truncate_debug_text(promoted_label, 96)}' "
            f"reason='{'top_priority_container' if promoted_label in set(priority_containers) else 'clickable_container'}'"
        )
    if bool(row.get("content_phase_grace_active", False)):
        log(
            f"[STEP][content_candidates_after_grace] "
            f"candidates='{_truncate_debug_text(_summarize_candidate_labels(filtered_candidates), 120)}'"
        )
    if passive_status_candidates and filtered_candidates:
        log(
            f"[STEP][status_exhausted_excluded] rejected='{_truncate_debug_text('|'.join(passive_status_candidates[:4]), 120)}' "
            "reason='passive_status_or_empty_state'"
        )
    if section_header_candidates and filtered_candidates:
        log(
            f"[STEP][section_header_deferred] candidates='{_truncate_debug_text('|'.join(section_header_candidates[:4]), 120)}' "
            "reason='content_candidates_present'"
        )
    if leaf_candidates and filtered_candidates:
        log(
            f"[STEP][leaf_hard_filter] rejected='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in leaf_candidates[:4]), 120)}' "
            "reason='low_value_leaf'"
        )
    elif current_row_is_low_value_leaf:
        current_leaf_label = str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
        if current_leaf_label and filtered_candidates:
            log(
                f"[STEP][leaf_penalty] deprioritized='{_truncate_debug_text(current_leaf_label, 120)}' "
                f"reason='low_value_leaf_or_parent_consumed'"
            )
    if revisit_rejected:
        log(
            f"[STEP][revisit_guard] rejected='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in revisit_rejected[:4]), 120)}' "
            f"reason='recent_object_revisit'"
        )
    if visited_rejected:
        log(
            f"[STEP][visited_filter] rejected='{_truncate_debug_text(_summarize_candidate_labels(visited_rejected), 120)}' "
            "reason='visited_logical_signature'"
        )
    if cluster_consumed_rejected:
        cluster_signature = str(cluster_consumed_rejected[0].get("cluster_signature", "") or "").strip()
        rejected_roles = "|".join(
            str(candidate.get("cluster_role", "") or "leaf").strip() for candidate in cluster_consumed_rejected[:4]
        ) or "none"
        log(
            f"[STEP][cluster_consumed_filter] cluster='{_truncate_debug_text(cluster_signature, 120)}' "
            f"rejected='{_truncate_debug_text(rejected_roles, 120)}'"
        )
    if consumed_rejected:
        log(
            f"[STEP][representative_exhausted_guard] rejected='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in consumed_rejected[:4]), 120)}' "
            "reason='already_consumed_representative'"
        )
    if content_candidates and (revisit_rejected or consumed_rejected):
        all_selection_labels = "|".join(str(candidate.get('label', '') or '').strip() for candidate in content_candidates[:5]) or "none"
        filtered_selection_labels = "|".join(str(candidate.get('label', '') or '').strip() for candidate in filtered_candidates[:5]) or "none"
        revisit_labels = "|".join(str(candidate.get('label', '') or '').strip() for candidate in revisit_rejected[:5]) or "none"
        log(
            f"[STEP][selection_candidates] all='{_truncate_debug_text(all_selection_labels, 120)}' "
            f"after_filter='{_truncate_debug_text(filtered_selection_labels, 120)}' "
                f"rejected_by_revisit='{_truncate_debug_text(revisit_labels, 120)}'"
        )
    current_move_result = normalize_move_result(row) or str(row.get("move_result", "") or "").strip().lower()
    filtered_meta = dict(filtered_meta)
    filtered_meta["representative_candidates"] = _filter_location_map_utility_exhaustion_candidates(
        state=state,
        candidates=list(filtered_meta["representative_candidates"]),
    )
    viewport_exhausted = not bool(filtered_meta["representative_candidates"])
    strip_focus_context = _is_current_focus_on_local_tab_strip(state, row)
    row["strip_focus_context"] = strip_focus_context
    if viewport_exhausted:
        viewport_reason = "no_representative_candidates"
    elif filtered_meta["representative_candidates"]:
        viewport_reason = "representative_candidates_remaining"
    elif filtered_meta["selection_candidates"]:
        viewport_reason = "selection_without_representative"
    elif filtered_meta["all_candidates"]:
        viewport_reason = "filtered_by_guards"
    else:
        viewport_reason = "no_candidates"
    row["viewport_exhausted_eval_result"] = viewport_exhausted
    row["viewport_exhausted_eval_reason"] = viewport_reason
    viewport_debug_needed = bool(
        current_move_result in {"failed", "no_progress"}
        or viewport_exhausted
        or revisit_rejected
        or consumed_rejected
        or section_header_candidates
    )
    if viewport_debug_needed:
        log(
            f"[STEP][viewport_exhausted_eval] "
            f"all_candidates='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta['all_candidates']), 120)}' "
            f"selection_candidates='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta['selection_candidates']), 120)}' "
            f"representative_candidates='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta['representative_candidates']), 120)}' "
            f"status_excluded='{_truncate_debug_text('|'.join(passive_status_candidates[:4]) or 'none', 120)}' "
            f"chrome_excluded='{_truncate_debug_text('|'.join(chrome_candidates[:4]) or 'none', 120)}' "
            f"leaf_excluded='{_truncate_debug_text(_summarize_candidate_labels(leaf_candidates), 120)}' "
            f"revisit_rejected='{_truncate_debug_text(_summarize_candidate_labels(revisit_rejected), 120)}' "
            f"visited_rejected='{_truncate_debug_text(_summarize_candidate_labels(visited_rejected), 120)}' "
            f"cluster_consumed_rejected='{_truncate_debug_text(_summarize_candidate_labels(cluster_consumed_rejected), 120)}' "
            f"consumed_rejected='{_truncate_debug_text(_summarize_candidate_labels(consumed_rejected), 120)}' "
            f"result={str(viewport_exhausted).lower()} reason='{viewport_reason}' "
            f"version='{COLLECTION_FLOW_SCROLL_DECISION_DEBUG_VERSION}'"
        )
    if strip_focus_context and (viewport_exhausted or not filtered_meta["representative_candidates"]):
        current_focus_summary = str(row.get("visible_label", "") or row.get("focus_view_id", "") or "").strip()
        log(
            f"[STEP][strip_focus_phase_priority] current_focus='{_truncate_debug_text(current_focus_summary, 96)}' "
            f"viewport_exhausted={str(viewport_exhausted).lower()} "
            "action='skip_realign_evaluate_scroll_or_tab'"
        )
    if len(filtered_candidates) >= 2:
        selected_spatial = filtered_candidates[0]
        spatial_candidate_labels = "|".join(str(candidate.get("label", "") or "").strip() for candidate in filtered_candidates[:4]) or "none"
        spatial_selected = str(selected_spatial.get("label", "") or selected_spatial.get("rid", "") or "").strip()
        spatial_detail_reason = "higher_in_viewport"
        if current_bounds := parse_bounds_str(str(row.get("focus_bounds", "") or "").strip()):
            first_bounds = parse_bounds_str(str(filtered_candidates[0].get("bounds", "") or "").strip())
            second_bounds = parse_bounds_str(str(filtered_candidates[1].get("bounds", "") or "").strip()) if len(filtered_candidates) > 1 else None
            if first_bounds and second_bounds and abs(first_bounds[1] - second_bounds[1]) <= 120:
                spatial_detail_reason = "same_band_tiebreaker_left_to_right"
        log(
            f"[STEP][spatial_priority] candidates='{_truncate_debug_text(spatial_candidate_labels, 120)}' "
            f"selected='{_truncate_debug_text(spatial_selected, 96)}' "
            f"reason='{spatial_detail_reason if spatial_reason else 'higher_in_viewport'}'"
        )
        if continuity_reason:
            previous_label = str(
                getattr(state, "previous_step_row", {}).get("visible_label", "")
                or getattr(state, "previous_step_row", {}).get("merged_announcement", "")
                or getattr(state, "previous_step_row", {}).get("focus_view_id", "")
                or ""
            ).strip()
            log(
                f"[STEP][continuity_priority] previous='{_truncate_debug_text(previous_label, 96)}' "
                f"selected='{_truncate_debug_text(spatial_selected, 96)}' "
                f"reason='{continuity_reason}'"
            )
    if len(filtered_meta.get("selection_candidates_before_visited", [])) >= 2 or visited_rejected:
        traversal_selected = str(filtered_candidates[0].get("label", "") or filtered_candidates[0].get("rid", "") or "").strip() if filtered_candidates else "none"
        log(
            f"[STEP][traversal_order] "
            f"candidates='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta.get('selection_candidates_before_visited', []), limit=5), 120)}' "
            f"after_visited_filter='{_truncate_debug_text(_summarize_candidate_labels(filtered_candidates, limit=5), 120)}' "
            f"selected='{_truncate_debug_text(traversal_selected, 96)}' "
            "reason='top_to_bottom_after_visited_filter'"
        )
    if not filtered_candidates:
        return row
    if (
        not bottom_strip_candidates
        and not current_row_is_low_value_leaf
        and not current_row_recent_revisit
        and not current_row_is_top_chrome
        and not current_row_is_passive_status
    ):
        return row
    selected_candidate = filtered_candidates[0]
    selected_node = selected_candidate.get("node", {})
    if not isinstance(selected_node, dict):
        return row
    selected_label = str(selected_candidate.get("label", "") or "").strip()
    selected_rid = str(
        selected_candidate.get("rid", "")
        or selected_node.get("viewIdResourceName", "")
        or selected_node.get("resourceId", "")
        or ""
    ).strip()
    selected_bounds = str(selected_node.get("boundsInScreen", "") or selected_node.get("bounds", "") or "").strip()
    selected_class = str(selected_node.get("className", "") or selected_node.get("class", "") or "").strip()
    normalize_fn = getattr(client, "normalize_for_comparison", None)
    if callable(normalize_fn):
        normalized_label = normalize_fn(selected_label) if selected_label else ""
    else:
        normalized_label = re.sub(r"\s+", " ", str(selected_label or "").strip()).lower()
    if str(selected_candidate.get("cluster_role", "") or "") == "title":
        log(
            f"[STEP][cluster_representative_rank] cluster='{_truncate_debug_text(_cluster_display_name(selected_candidate), 96)}' "
            f"candidates='{_truncate_debug_text('|'.join(str(candidate.get('cluster_role', '') or '') for candidate in selected_candidate.get('cluster_members', [])[:4]), 120)}' "
            f"selected='{_truncate_debug_text(str(selected_candidate.get('cluster_role', '') or 'title'), 96)}' "
            "reason='title_selected_after_cluster_ranking'"
        )
    title_fallback_candidate = _select_better_cluster_representative(
        selected_candidate=selected_candidate,
        state=state,
        row=row,
    )
    selected_cluster_signature = _candidate_cluster_signature(selected_candidate)
    selected_logical_signature = _candidate_logical_signature(selected_candidate)
    if selected_logical_signature and selected_logical_signature != "none||none||none":
        log(
            f"[STEP][logical_signature] label='{_truncate_debug_text(selected_label or selected_rid, 96)}' "
            f"signature='{_truncate_debug_text(selected_logical_signature, 120)}'"
        )
    if len(filtered_candidates) >= 2 or visited_rejected:
        log(
            f"[STEP][duplicate_prevention] visited_count={len(set(getattr(state, 'visited_logical_signatures', set()) or set()))} "
            f"cluster_visited_count={len(set(getattr(state, 'consumed_cluster_signatures', set()) or set()))} "
            f"selected='{_truncate_debug_text(selected_label or selected_rid, 96)}'"
        )
    previous_cluster_signature = str(
        getattr(state, "previous_step_row", {}).get("focus_cluster_signature", "")
        or getattr(state, "previous_step_row", {}).get("scroll_ready_cluster_signature", "")
        or ""
    ).strip()
    move_result = normalize_move_result(row) or str(row.get("move_result", "") or "").strip().lower()
    cluster_candidates = [
        candidate for candidate in filtered_candidates
        if _candidate_cluster_signature(candidate) == selected_cluster_signature
    ]
    previous_representative = str(
        getattr(state, "previous_step_row", {}).get("visible_label", "")
        or getattr(state, "previous_step_row", {}).get("merged_announcement", "")
        or getattr(state, "previous_step_row", {}).get("focus_view_id", "")
        or ""
    ).strip()
    current_representative = selected_label or selected_rid
    same_cluster = bool(
        selected_cluster_signature
        and previous_cluster_signature
        and selected_cluster_signature == previous_cluster_signature
    )
    if same_cluster:
        log(
            f"[STEP][cluster_progress] previous_cluster='{_truncate_debug_text(previous_cluster_signature, 120)}' "
            f"current_cluster='{_truncate_debug_text(selected_cluster_signature, 120)}' "
            "same_cluster=true "
            f"previous_representative='{_truncate_debug_text(previous_representative, 96)}' "
            f"current_representative='{_truncate_debug_text(current_representative, 96)}' "
            f"version='{COLLECTION_FLOW_SCROLL_DECISION_DEBUG_VERSION}'"
        )
    no_better_candidate_in_cluster = bool(
        selected_cluster_signature
        and not title_fallback_candidate
        and len(cluster_candidates) <= 1
    )
    same_object_like = bool(
        int(getattr(state, "same_count", 0) or 0) > 0
        or _build_row_object_signature(row) == _build_row_object_signature(getattr(state, "previous_step_row", {}))
        or build_row_semantic_fingerprint(row) == build_row_semantic_fingerprint(getattr(state, "previous_step_row", {}))
    )
    focus_state = _focus_realign_state(state)
    scroll_ready_state = bool(
        selected_cluster_signature
        and previous_cluster_signature
        and selected_cluster_signature == previous_cluster_signature
        and move_result in {"failed", "no_progress"}
        and same_object_like
        and (
            selected_cluster_signature in set(getattr(focus_state, "cluster_title_fallback_applied", set()) or set())
            or no_better_candidate_in_cluster
        )
    )
    fallback_applied = bool(
        selected_cluster_signature
        and selected_cluster_signature in set(getattr(focus_state, "cluster_title_fallback_applied", set()) or set())
    )
    representative_preview = _summarize_candidate_labels(filtered_meta["representative_candidates"])
    recent_representative_count = len(list(getattr(state, "recent_representative_signatures", []) or []))
    consumed_cluster = bool(
        selected_cluster_signature
        and selected_cluster_signature in set(getattr(state, "consumed_cluster_signatures", set()) or set())
    )
    if scroll_ready_state:
        scroll_ready_eval_reason = "ready"
    elif move_result not in {"failed", "no_progress"}:
        scroll_ready_eval_reason = "move_not_failed"
    elif not same_cluster:
        scroll_ready_eval_reason = "cluster_not_stable"
    elif not same_object_like:
        scroll_ready_eval_reason = "same_like_count_too_low"
    elif not (fallback_applied or no_better_candidate_in_cluster):
        scroll_ready_eval_reason = (
            "representative_candidates_remaining" if len(cluster_candidates) > 1 else "fallback_not_applied"
        )
    else:
        scroll_ready_eval_reason = "blocked_by_unknown_condition"
    row["scroll_ready_eval_result"] = scroll_ready_state
    row["scroll_ready_eval_reason"] = scroll_ready_eval_reason
    scroll_ready_eval_needed = bool(
        move_result in {"failed", "no_progress"}
        or same_cluster
        or int(getattr(state, "same_count", 0) or 0) > 0
        or not filtered_meta["representative_candidates"]
    )
    if scroll_ready_eval_needed:
        log(
            f"[STEP][scroll_ready_eval] cluster='{_truncate_debug_text(selected_cluster_signature, 120)}' "
            f"representative='{_truncate_debug_text(current_representative, 96)}' "
            f"representative_candidates='{_truncate_debug_text(representative_preview, 120)}' "
            f"move_result='{_truncate_debug_text(move_result or 'none', 48)}' "
            f"same_like_count={int(getattr(state, 'same_count', 0) or 0)} "
            f"same_object={str(same_object_like).lower()} "
            f"cluster_title_fallback_applied={str(fallback_applied).lower()} "
            f"recent_representative_count={recent_representative_count} "
            f"consumed_cluster={str(consumed_cluster).lower()} "
            f"result={str(scroll_ready_state).lower()} reason='{scroll_ready_eval_reason}' "
            f"version='{COLLECTION_FLOW_SCROLL_DECISION_DEBUG_VERSION}'"
        )
    if scroll_ready_state:
        row["scroll_ready_state"] = True
        row["scroll_ready_cluster_signature"] = selected_cluster_signature
        row["scroll_ready_reason"] = "no_more_representative_in_cluster_allow_move_smart_scroll"
        row["focus_cluster_signature"] = selected_cluster_signature
        log(
            f"[STEP][scroll_ready] cluster='{_truncate_debug_text(selected_cluster_signature, 120)}' "
            "reason='no_more_representative_in_cluster_allow_move_smart_scroll' "
            f"move_result='{_truncate_debug_text(move_result, 48)}' "
            f"representative_candidates='{_truncate_debug_text(representative_preview, 120)}' "
            f"fallback_applied={str(fallback_applied).lower()} "
            f"same_like_hint={str(same_object_like).lower()} "
            f"version='{COLLECTION_FLOW_SCROLL_READY_VERSION}'"
        )
        return row
    if title_fallback_candidate is not None:
        cluster_signature = _candidate_cluster_signature(selected_candidate)
        fallback_sets = set(getattr(focus_state, "cluster_title_fallback_applied", set()) or set())
        if cluster_signature:
            fallback_sets.add(cluster_signature)
            focus_state.cluster_title_fallback_applied = fallback_sets
        log(
            f"[STEP][cluster_title_fallback] cluster='{_truncate_debug_text(_cluster_display_name(selected_candidate), 96)}' "
            f"current='{_truncate_debug_text(selected_label or selected_rid, 96)}' "
            f"fallback='{_truncate_debug_text(str(title_fallback_candidate.get('label', '') or title_fallback_candidate.get('rid', '') or ''), 96)}' "
            "reason='title_no_progress_fallback'"
        )
        selected_candidate = title_fallback_candidate
        selected_node = selected_candidate.get("node", {})
        if isinstance(selected_node, dict):
            selected_label = str(selected_candidate.get("label", "") or "").strip()
            selected_rid = str(
                selected_candidate.get("rid", "")
                or selected_node.get("viewIdResourceName", "")
                or selected_node.get("resourceId", "")
                or ""
            ).strip()
            selected_bounds = str(selected_node.get("boundsInScreen", "") or selected_node.get("bounds", "") or "").strip()
            selected_class = str(selected_node.get("className", "") or selected_node.get("class", "") or "").strip()
            if callable(normalize_fn):
                normalized_label = normalize_fn(selected_label) if selected_label else ""
            else:
                normalized_label = re.sub(r"\s+", " ", str(selected_label or "").strip()).lower()
    elif str(selected_candidate.get("cluster_role", "") or "") == "title" and normalize_move_result(row) in {"failed", "no_progress"}:
        log(
            f"[STEP][cluster_title_fallback_skip] cluster='{_truncate_debug_text(_cluster_display_name(selected_candidate), 96)}' "
            "current='title' reason='no_better_cluster_representative'"
        )
    current_rid = str(row.get("focus_view_id", "") or "").strip()
    current_label = str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    current_bounds = str(row.get("focus_bounds", "") or "").strip()
    focus_context_matches_selected, focus_anchor_reason = _focus_anchor_match_reason(
        row=row,
        selected_rid=selected_rid,
        selected_label=selected_label,
        selected_bounds=selected_bounds,
        selected_cluster_signature=selected_cluster_signature,
    )
    log(
        f"[STEP][focus_anchor] selected='{_truncate_debug_text(selected_label or selected_rid, 96)}' "
        f"current='{_truncate_debug_text(current_label or current_rid, 96)}' "
        f"matched={str(focus_context_matches_selected).lower()} reason='{focus_anchor_reason}'"
    )
    realign_ok = False
    realigned_focus_node: dict[str, Any] | None = None
    if not focus_context_matches_selected:
        log(
            f"[STEP][focus_context_mismatch] selected='{_truncate_debug_text(selected_label or selected_rid, 96)}' "
            f"current_focus='{_truncate_debug_text(current_label or current_rid, 96)}' "
            "reason='representative_differs_from_focus_context'"
        )
        realign_meta = _filter_realign_target_candidates(content_candidates, state=state)
        all_realign_labels = "|".join(str(candidate.get("label", "") or "").strip() for candidate in realign_meta["all"][:5]) or "none"
        eligible_realign_labels = "|".join(str(candidate.get("label", "") or "").strip() for candidate in realign_meta["eligible"][:5]) or "none"
        rejected_recent_labels = "|".join(str(candidate.get("label", "") or "").strip() for candidate in realign_meta["rejected_recent"][:5]) or "none"
        rejected_consumed_labels = "|".join(str(candidate.get("label", "") or "").strip() for candidate in realign_meta["rejected_consumed"][:5]) or "none"
        log(
            f"[STEP][focus_realign_candidates] all='{_truncate_debug_text(all_realign_labels, 120)}' "
            f"eligible='{_truncate_debug_text(eligible_realign_labels, 120)}' "
            f"rejected_recent='{_truncate_debug_text(rejected_recent_labels, 120)}' "
            f"rejected_consumed='{_truncate_debug_text(rejected_consumed_labels, 120)}'"
        )
        selected_signature = _candidate_object_signature(selected_candidate)
        selected_cluster_signature = _candidate_cluster_signature(selected_candidate)
        failed_realign_signatures = set(getattr(focus_state, "failed_focus_realign_signatures", set()) or set())
        force_reason = "anchor_mismatch"
        if strip_focus_context or current_row_is_low_value_leaf or current_row_recent_revisit:
            force_reason = "strip_or_stale_focus_context"
        if selected_signature in failed_realign_signatures:
            log(
                f"[STEP][focus_realign_skip] target='{_truncate_debug_text(selected_label or selected_rid, 96)}' "
                "reason='recent_realign_failed'"
            )
        elif selected_cluster_signature and selected_cluster_signature in set(getattr(focus_state, "recent_focus_realign_clusters", set()) or set()):
            log(
                f"[STEP][focus_realign_skip] cluster='{_truncate_debug_text(selected_cluster_signature, 120)}' "
                "reason='cluster_already_realign_resolved'"
            )
        elif selected_signature in set(getattr(focus_state, "recent_focus_realign_signatures", set()) or set()):
            log(
                f"[STEP][focus_realign_skip] target='{_truncate_debug_text(selected_label or selected_rid, 96)}' "
                "reason='already_realign_resolved_in_current_phase'"
            )
        else:
            realign_ok, _, realigned_focus_node = _maybe_realign_focus_to_representative(
                row=row,
                client=client,
                dev=dev,
                selected_node=selected_node,
                selected_rid=selected_rid,
                selected_label=selected_label,
                selected_bounds=selected_bounds,
                scenario_id=str(tab_cfg.get("scenario_id", "") or ""),
                step_idx=step_idx,
                mismatch_logged=True,
                force_reason=force_reason,
                scenario_perf=scenario_perf,
            )
            realign_signature = _candidate_object_signature(selected_candidate)
            realign_cluster_signature = _candidate_cluster_signature(selected_candidate)
            if realign_ok:
                if realign_signature:
                    resolved_signatures = set(getattr(focus_state, "recent_focus_realign_signatures", set()) or set())
                    resolved_signatures.add(realign_signature)
                    focus_state.recent_focus_realign_signatures = resolved_signatures
                    failed_realign_signatures.discard(realign_signature)
                    focus_state.failed_focus_realign_signatures = failed_realign_signatures
                if realign_cluster_signature:
                    resolved_clusters = set(getattr(focus_state, "recent_focus_realign_clusters", set()) or set())
                    resolved_clusters.add(realign_cluster_signature)
                    focus_state.recent_focus_realign_clusters = resolved_clusters
                log(
                    f"[STEP][focus_realign_record] target='{_truncate_debug_text(selected_label or selected_rid, 96)}' "
                    f"signature='{_truncate_debug_text(realign_signature, 120)}' "
                    f"phase='{_truncate_debug_text(_current_local_tab_phase_label(state), 48)}'"
                )
            elif realign_signature:
                failed_realign_signatures.add(realign_signature)
                focus_state.failed_focus_realign_signatures = failed_realign_signatures
    if realign_ok and isinstance(realigned_focus_node, dict):
        selected_node = realigned_focus_node
        selected_rid = str(
            realigned_focus_node.get("viewIdResourceName", "")
            or realigned_focus_node.get("resourceId", "")
            or selected_rid
        ).strip() or selected_rid
        selected_label = _extract_cta_node_label(realigned_focus_node) or _node_label_blob(realigned_focus_node) or selected_label
        selected_bounds = str(realigned_focus_node.get("boundsInScreen", "") or realigned_focus_node.get("bounds", "") or selected_bounds).strip() or selected_bounds
        selected_class = str(realigned_focus_node.get("className", "") or realigned_focus_node.get("class", "") or selected_class).strip() or selected_class
        if callable(normalize_fn):
            normalized_label = normalize_fn(selected_label) if selected_label else ""
        else:
            normalized_label = re.sub(r"\s+", " ", str(selected_label or "").strip()).lower()
    content_summary = "|".join(str(item.get("label", "") or "").strip() for item in content_candidates[:5])
    bottom_summary = "|".join(str(item.get("label", "") or "").strip() for item in bottom_strip_candidates[:3])
    chrome_summary = "|".join(chrome_candidates[:4])
    status_summary = "|".join(passive_status_candidates[:4])
    section_header_summary = "|".join(section_header_candidates[:4])
    selected_summary = selected_label or selected_rid or "none"
    reason = "representative_content_preferred"
    if _is_row_persistent_bottom_strip_candidate(row):
        reason = "content_candidate_preferred_over_bottom_strip"
    elif current_row_is_top_chrome:
        reason = "content_candidate_preferred_over_chrome"
    elif current_row_is_low_value_leaf:
        reason = "representative_content_preferred_over_leaf"
    elif current_row_recent_revisit:
        reason = "representative_content_preferred_over_revisit"
    if passive_status_candidates:
        log(
            f"[STEP][candidate_priority] content_candidates='{_truncate_debug_text(content_summary, 120)}' "
            f"status_candidates='{_truncate_debug_text(status_summary, 120)}' "
            f"selected='{_truncate_debug_text(selected_summary, 96)}' "
            "reason='representative_content_preferred_over_passive_status'"
        )
    elif section_header_candidates:
        log(
            f"[STEP][candidate_priority] content_candidates='{_truncate_debug_text(content_summary, 120)}' "
            f"section_header_candidates='{_truncate_debug_text(section_header_summary, 120)}' "
            f"selected='{_truncate_debug_text(selected_summary, 96)}' "
            "reason='representative_content_preferred_over_section_header'"
        )
    elif chrome_candidates:
        log(
            f"[STEP][candidate_priority] content_candidates='{_truncate_debug_text(content_summary, 120)}' "
            f"chrome_candidates='{_truncate_debug_text(chrome_summary, 120)}' "
            f"selected='{_truncate_debug_text(selected_summary, 96)}' "
            f"reason='{reason}'"
        )
    else:
        log(
            f"[STEP][candidate_priority] content_candidates='{_truncate_debug_text(content_summary, 120)}' "
            f"bottom_strip_candidates='{_truncate_debug_text(bottom_summary, 120)}' "
            f"selected='{_truncate_debug_text(selected_summary, 96)}' "
            f"reason='{reason}'"
        )
    if bottom_strip_candidates:
        log("[STEP][bottom_strip_policy] content_present=true bottom_strip_deferred=true")
    log(
        f"[STEP][candidate_sort_key] selected='{_truncate_debug_text(selected_summary, 96)}' "
        f"sort_key='score={int(selected_candidate.get('score', 0) or 0)},"
        f"top={int(parse_bounds_str(selected_bounds)[1] if parse_bounds_str(selected_bounds) else 0)},"
        f"left={int(parse_bounds_str(selected_bounds)[0] if parse_bounds_str(selected_bounds) else 0)}'"
    )
    row["bottom_strip_deferred"] = True
    row["bottom_strip_deferred_step"] = step_idx
    row["bottom_strip_deferred_reason"] = "content_candidate_preferred_over_bottom_strip"
    row["focus_payload_source"] = str(row.get("focus_payload_source", "") or "get_focus")
    updated_row = _apply_cta_node_to_row(
        row=row,
        selected_node=selected_node,
        selected_rid=selected_rid,
        selected_label=selected_label,
        selected_bounds=selected_bounds,
        selected_class=selected_class,
        normalized_label=normalized_label,
    )
    updated_row["focus_cluster_signature"] = str(selected_candidate.get("cluster_signature", "") or "").strip()
    updated_row["focus_cluster_logical_signature"] = _candidate_cluster_logical_signature(selected_candidate)
    return updated_row

def _maybe_select_next_local_tab(
    *,
    client: A11yAdbClient,
    dev: str,
    state: MainLoopState,
    row: dict[str, Any],
    scenario_id: str,
    step_idx: int,
) -> bool:
    _maybe_commit_pending_local_tab_progression(state, row)
    local_tab_signature = str(state.current_local_tab_signature or "").strip()
    dump_tree_fn = getattr(client, "dump_tree", None)
    content_candidates: list[dict[str, Any]] = []
    chrome_excluded: list[str] = []
    container_promoted: list[str] = []
    dump_bottom_strip_candidates: list[str] = []
    current_bottom_strip_candidates: list[dict[str, Any]] = []
    if callable(dump_tree_fn):
        try:
            nodes = dump_tree_fn(dev=dev)
            content_candidates, current_bottom_strip_candidates, candidate_groups_meta = _collect_step_candidate_priority_groups(
                nodes,
                consumed_cluster_signatures=set(getattr(state, "consumed_cluster_signatures", set()) or set()),
                consumed_cluster_logical_signatures=set(getattr(state, "consumed_cluster_logical_signatures", set()) or set()),
            )
            chrome_excluded = [str(value or "").strip() for value in candidate_groups_meta.get("chrome_excluded_candidates", []) if str(value or "").strip()]
            container_promoted = [
                str(value or "").strip()
                for value in candidate_groups_meta.get("container_promoted_candidates", [])
                if str(value or "").strip()
            ]
            priority_containers = [
                str(value or "").strip()
                for value in candidate_groups_meta.get("top_priority_container_candidates", [])
                if str(value or "").strip()
            ]
            dump_bottom_strip_candidates = [
                str(value or "").strip()
                for value in candidate_groups_meta.get("raw_bottom_strip_candidates", [])
                if str(value or "").strip()
            ]
        except Exception:
            content_candidates = []
            chrome_excluded = []
            container_promoted = []
            priority_containers = []
            dump_bottom_strip_candidates = []
            current_bottom_strip_candidates = []
    filtered_meta = _filter_content_candidates_for_phase(content_candidates, state=state)
    status_excluded = [str(candidate.get("label", "") or "").strip() for candidate in filtered_meta["status_candidates"]]
    section_header_deferred = [str(candidate.get("label", "") or "").strip() for candidate in filtered_meta.get("section_header_deferred", [])]
    consumed_representatives = [
        str(candidate.get("label", "") or "").strip()
        for candidate in [*filtered_meta["revisit_rejected"], *filtered_meta["consumed_rejected"]]
    ]
    effective_content_candidates = list(filtered_meta["exhaustion_candidates"])
    if consumed_representatives:
        log(
            f"[STEP][representative_exhausted_guard] rejected='{_truncate_debug_text('|'.join(consumed_representatives[:4]), 120)}' "
            "reason='already_consumed_representative'"
        )
    if filtered_meta["all_candidates"] and (filtered_meta["revisit_rejected"] or filtered_meta["consumed_rejected"]):
        log(
            f"[STEP][selection_candidates] all='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in filtered_meta['all_candidates'][:5]) or 'none', 120)}' "
            f"after_filter='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in filtered_meta['selection_candidates'][:5]) or 'none', 120)}' "
            f"rejected_by_revisit='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in filtered_meta['revisit_rejected'][:5]) or 'none', 120)}'"
        )
    if status_excluded:
        log(
            f"[STEP][status_exhausted_excluded] rejected='{_truncate_debug_text('|'.join(status_excluded[:4]), 120)}' "
            "reason='passive_status_or_empty_state'"
        )
    for promoted_label in container_promoted[:5]:
        log(
            f"[STEP][container_candidate_promoted] label='{_truncate_debug_text(promoted_label, 96)}' "
            f"reason='{'top_priority_container' if promoted_label in set(priority_containers) else 'clickable_container'}'"
        )
    if section_header_deferred and effective_content_candidates:
        log(
            f"[STEP][section_header_deferred] candidates='{_truncate_debug_text('|'.join(section_header_deferred[:4]), 120)}' "
            "reason='content_candidates_present'"
        )
    effective_content_candidates = _filter_location_map_utility_exhaustion_candidates(
        state=state,
        candidates=effective_content_candidates,
    )
    log(
        f"[STEP][representative_exhausted_eval] representative_candidates='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in effective_content_candidates[:4]), 120)}' "
        f"consumed_representatives='{_truncate_debug_text('|'.join(consumed_representatives[:4]), 120)}' "
        f"status_excluded='{_truncate_debug_text('|'.join(status_excluded[:4]), 120)}' "
        f"section_header_deferred='{_truncate_debug_text('|'.join(section_header_deferred[:4]), 120)}' "
        f"chrome_excluded='{_truncate_debug_text('|'.join(chrome_excluded[:4]), 120)}' "
        f"exhausted={str(not effective_content_candidates).lower()}"
    )
    log(
        f"[STEP][exhaustion_candidates] from_selection='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in filtered_meta['selection_candidates'][:4]) or 'none', 120)}' "
        f"after_consumed_filter='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in effective_content_candidates[:4]) or 'none', 120)}' "
        f"exhausted={str(not effective_content_candidates).lower()}"
    )
    viewport_exhausted = _is_viewport_exhausted_for_scroll_fallback(
        candidates=effective_content_candidates,
        representative_exists=bool(effective_content_candidates),
    )
    viewport_reason = "no_representative_candidates" if viewport_exhausted else "representative_candidates_remaining"
    row["viewport_exhausted_eval_result"] = viewport_exhausted
    row["viewport_exhausted_eval_reason"] = viewport_reason
    log(
        f"[STEP][viewport_exhausted_eval] "
        f"all_candidates='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta['all_candidates']), 120)}' "
        f"selection_candidates='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta['selection_candidates']), 120)}' "
        f"representative_candidates='{_truncate_debug_text(_summarize_candidate_labels(effective_content_candidates), 120)}' "
        f"status_excluded='{_truncate_debug_text('|'.join(status_excluded[:4]) or 'none', 120)}' "
        f"chrome_excluded='{_truncate_debug_text('|'.join(chrome_excluded[:4]) or 'none', 120)}' "
        f"leaf_excluded='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta['leaf_rejected']), 120)}' "
        f"revisit_rejected='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta['revisit_rejected']), 120)}' "
        f"consumed_rejected='{_truncate_debug_text(_summarize_candidate_labels(filtered_meta['consumed_rejected']), 120)}' "
        f"result={str(viewport_exhausted).lower()} reason='{viewport_reason}' "
        f"version='{COLLECTION_FLOW_SCROLL_DECISION_DEBUG_VERSION}'"
    )
    mismatch_labels = {
        str(candidate.get("label", "") or "").strip()
        for candidate in [*filtered_meta["revisit_rejected"], *filtered_meta["consumed_rejected"]]
    }.intersection({
        str(candidate.get("label", "") or "").strip()
        for candidate in effective_content_candidates
    })
    if mismatch_labels:
        log(
            f"[STEP][candidate_mismatch] selection_rejected_but_exhaustion_included='{_truncate_debug_text('|'.join(sorted(mismatch_labels)), 120)}'"
        )
    grace_active = bool(row.get("content_phase_grace_active", False) or int(getattr(state, "content_phase_grace_steps", 0) or 0) > 0)
    if grace_active:
        row["local_tab_gate_evaluated"] = True
        row["local_tab_block_reason"] = "content_phase_grace_active"
        log(
            f"[STEP][content_candidates_after_grace] "
            f"candidates='{_truncate_debug_text(_summarize_candidate_labels(effective_content_candidates), 120)}'"
        )
        if not effective_content_candidates:
            log(
                f"[STEP][content_phase_grace_block] reason='within_grace_window' "
                f"remaining={int(getattr(state, 'content_phase_grace_steps', 0) or 0)}"
            )
            return False
    if effective_content_candidates:
        row["scroll_fallback_allowed"] = False
        row["scroll_fallback_gate_evaluated"] = True
        row["scroll_fallback_gate_reason"] = "representative_still_exists"
        row["scroll_fallback_block_reason"] = "representative_still_exists"
        row["local_tab_gate_evaluated"] = True
        row["local_tab_block_reason"] = "content_not_exhausted"
        log(
            f"[STEP][scroll_fallback_gate] viewport_exhausted=false scrollable=false allowed=false "
            "signature='' reason='representative_still_exists' "
            f"version='{COLLECTION_FLOW_SCROLL_DECISION_DEBUG_VERSION}'"
        )
        log(
            f"[STEP][local_tab_gate] allowed=false reason='content_not_exhausted' "
            f"tabs='{_truncate_debug_text(_summarize_candidate_labels(state.local_tab_candidates_by_signature.get(local_tab_signature, [])), 120)}' "
            f"active='{_truncate_debug_text(str(state.current_local_tab_active_rid or ''), 96)}' "
            "unvisited='none'"
        )
        active_display = _local_tab_state_display(
            rid=str(getattr(state, "current_local_tab_active_rid", "") or ""),
            label=str(getattr(state, "current_local_tab_active_label", "") or ""),
        )
        if active_display:
            log(
                f"[STEP][local_tab_progression_block] reason='content_not_exhausted_after_tab_switch' "
                f"active='{_truncate_debug_text(active_display, 96)}'"
            )
        return False
    log("[STEP][viewport_exhausted] representative_candidates='' reason='no_representative_in_viewport'")
    active_display = _local_tab_state_display(
        rid=str(getattr(state, "current_local_tab_active_rid", "") or ""),
        label=str(getattr(state, "current_local_tab_active_label", "") or ""),
    )
    if active_display:
        log(
            f"[STEP][content_phase_exhausted] active='{_truncate_debug_text(active_display, 96)}'"
        )
    scroll_fallback_signature = _build_scroll_fallback_signature(
        local_tab_signature=local_tab_signature,
        active_rid=str(state.current_local_tab_active_rid or ""),
        content_candidates=content_candidates,
        chrome_excluded=chrome_excluded,
        current_focus_signature=_build_row_object_signature(row),
    )
    scrollable_nodes: list[str] = []
    content_area_bounds = ""
    if 'nodes' in locals():
        scrollable, scrollable_nodes, content_area_bounds = _describe_scrollable_content_phase(nodes)
    else:
        scrollable = False
    scroll_state = _scroll_state(state)
    attempted_signatures = set(getattr(scroll_state, "recent_scroll_fallback_signatures", set()) or set())
    scroll_allowed = bool(scrollable and scroll_fallback_signature and scroll_fallback_signature not in attempted_signatures)
    scroll_reason = "viewport_exhausted_direct_scroll"
    if not scrollable:
        scroll_reason = "not_scrollable"
    elif not scroll_fallback_signature:
        scroll_reason = "missing_signature"
    elif scroll_fallback_signature in attempted_signatures:
        scroll_reason = "already_attempted_same_signature"
    normal_scroll_allowed = scroll_allowed
    previous_row = getattr(state, "previous_step_row", {}) or {}
    current_focus_strip = _is_current_focus_on_local_tab_strip(state, row)
    current_row_strip = _is_row_persistent_bottom_strip_candidate(row)
    previous_row_strip = bool(
        isinstance(previous_row, dict)
        and (
            _is_current_focus_on_local_tab_strip(state, previous_row)
            or _is_row_persistent_bottom_strip_candidate(previous_row)
        )
    )
    recent_strip_seen = bool(current_focus_strip or previous_row_strip)
    dump_strip_seen = bool(dump_bottom_strip_candidates)
    bottom_strip_context = bool(current_focus_strip or current_row_strip or previous_row_strip or dump_strip_seen)
    row["strip_focus_context"] = bool(row.get("strip_focus_context", False) or bottom_strip_context)
    log(
        f"[STEP][bottom_strip_context_eval] current_focus_strip={str(current_focus_strip).lower()} "
        f"current_row_strip={str(current_row_strip).lower()} previous_row_strip={str(previous_row_strip).lower()} "
        f"recent_strip_seen={str(recent_strip_seen).lower()} dump_strip_seen={str(dump_strip_seen).lower()} "
        f"result={str(bottom_strip_context).lower()}"
    )
    last_attempted_signatures = set(getattr(scroll_state, "last_scroll_fallback_attempted_signatures", set()) or set())
    last_scroll_signature = scroll_fallback_signature or _build_row_object_signature(row) or local_tab_signature or "viewport_exhausted"
    last_scroll_evaluated = bool(viewport_exhausted and bottom_strip_context)
    scrollable_uncertain = bool(last_scroll_evaluated and not scrollable and (content_area_bounds or dump_strip_seen or previous_row_strip))
    last_scroll_allowed = bool(
        last_scroll_evaluated
        and last_scroll_signature
        and (scrollable or scrollable_uncertain)
        and scroll_reason in {"already_attempted_same_signature", "not_scrollable", "missing_signature"}
        and last_scroll_signature not in last_attempted_signatures
    )
    last_scroll_reason = "not_evaluated"
    if last_scroll_evaluated:
        if last_scroll_allowed:
            last_scroll_reason = (
                "bottom_strip_context_scrollable_uncertain"
                if scrollable_uncertain and not scrollable
                else "last_scroll_before_global_exhausted"
            )
        elif not bottom_strip_context:
            last_scroll_reason = "not_bottom_strip_context"
        elif not scrollable:
            last_scroll_reason = "not_scrollable"
        elif not scroll_fallback_signature:
            last_scroll_reason = "missing_signature"
        elif last_scroll_signature in last_attempted_signatures:
            last_scroll_reason = "last_scroll_already_attempted"
        else:
            last_scroll_reason = scroll_reason or "normal_scroll_available"
    row["last_scroll_fallback_evaluated"] = last_scroll_evaluated
    row["last_scroll_fallback_allowed"] = last_scroll_allowed
    row["last_scroll_block_reason"] = "" if last_scroll_allowed else last_scroll_reason
    if last_scroll_evaluated:
        log(
            f"[STEP][last_scroll_fallback_eval] viewport_exhausted=true "
            f"bottom_strip_context={str(bottom_strip_context).lower()} "
            f"normal_block_reason='{scroll_reason}' allowed={str(last_scroll_allowed).lower()} "
            f"scrollable_uncertain={str(scrollable_uncertain).lower()} reason='{last_scroll_reason}'"
        )
    if last_scroll_allowed:
        scroll_allowed = True
        scroll_reason = last_scroll_reason
    row["scroll_fallback_allowed"] = scroll_allowed
    row["scroll_fallback_gate_evaluated"] = True
    row["scroll_fallback_gate_reason"] = scroll_reason
    row["scroll_fallback_block_reason"] = "" if scroll_allowed else scroll_reason
    log(
        f"[STEP][scrollable_phase_debug] scrollable_nodes='{_truncate_debug_text('|'.join(scrollable_nodes[:4]), 120)}' "
        f"content_area_bounds='{_truncate_debug_text(content_area_bounds, 96)}' result={str(scrollable).lower()}"
    )
    log(
        f"[STEP][scroll_fallback_gate] viewport_exhausted=true "
        f"scrollable={str(scrollable).lower()} allowed={str(scroll_allowed).lower()} "
        f"signature='{_truncate_debug_text(scroll_fallback_signature, 120)}' reason='{scroll_reason}' "
        f"version='{COLLECTION_FLOW_SCROLL_DECISION_DEBUG_VERSION}'"
    )
    log(
        f"[STEP][scroll_fallback_eval] viewport_exhausted=true "
        f"scrollable={str(scrollable).lower()} allowed={str(scroll_allowed).lower()} "
        f"signature='{_truncate_debug_text(scroll_fallback_signature, 120)}' reason='{scroll_reason}'"
    )
    scroll_fn = getattr(client, "scroll", None)
    if scroll_allowed and callable(scroll_fn):
        if last_scroll_allowed:
            last_attempted_signatures.add(last_scroll_signature)
            scroll_state.last_scroll_fallback_attempted_signatures = last_attempted_signatures
            log("[STEP][last_scroll_fallback] attempt=1 reason='bottom_strip_viewport_exhausted'")
        else:
            attempted_signatures.add(scroll_fallback_signature)
            scroll_state.recent_scroll_fallback_signatures = attempted_signatures
            log("[STEP][scroll_fallback] reason='viewport_exhausted_before_local_tab' attempt=1")
        try:
            scrolled = bool(scroll_fn(dev=dev, direction="down"))
        except Exception:
            scrolled = False
        if scrolled:
            _clear_active_container_group(state, reason="scroll")
            state.completed_container_groups = set()
            time.sleep(0.25)
            refreshed_nodes = []
            if callable(dump_tree_fn):
                try:
                    refreshed_nodes = dump_tree_fn(dev=dev)
                except Exception:
                    refreshed_nodes = []
            refreshed_content, _, refreshed_meta = _collect_step_candidate_priority_groups(
                refreshed_nodes,
                consumed_cluster_signatures=set(getattr(state, "consumed_cluster_signatures", set()) or set()),
                consumed_cluster_logical_signatures=set(getattr(state, "consumed_cluster_logical_signatures", set()) or set()),
            )
            refreshed_filtered = _filter_content_candidates_for_phase(refreshed_content, state=state)
            refreshed_effective = list(refreshed_filtered["exhaustion_candidates"])
            new_representative = str(refreshed_effective[0].get("label", "") or refreshed_effective[0].get("rid", "") or "").strip() if refreshed_effective else ""
            resumed_content_phase = bool(refreshed_effective)
            if last_scroll_allowed:
                row["last_scroll_fallback_resumed_content"] = resumed_content_phase
                row["last_scroll_fallback_representative"] = new_representative
                row["last_scroll_global_exhausted"] = not resumed_content_phase
                log(
                    f"[STEP][last_scroll_fallback_result] new_representative='{_truncate_debug_text(new_representative, 120)}' "
                    f"resumed_content_phase={str(resumed_content_phase).lower()} "
                    f"global_exhausted={str(not resumed_content_phase).lower()}"
                )
            log(
                f"[STEP][scroll_fallback_result] new_representative='{_truncate_debug_text(new_representative, 120)}' "
                f"resumed_content_phase={str(resumed_content_phase).lower()}"
            )
            if resumed_content_phase:
                row["scroll_fallback_resumed_content"] = True
                row["scroll_fallback_representative"] = new_representative
                return False
    local_tab_gate_reason = "scroll_fallback_not_attempted"
    if scroll_allowed and not callable(scroll_fn):
        local_tab_gate_reason = "scroll_fallback_not_attempted"
    elif normal_scroll_allowed or last_scroll_allowed:
        local_tab_gate_reason = "scroll_fallback_attempted_no_resume"
    elif not local_tab_signature:
        local_tab_gate_reason = "local_tab_state_missing"
    elif scroll_reason in {"not_scrollable", "missing_signature", "already_attempted_same_signature"}:
        local_tab_gate_reason = scroll_reason
    if section_header_deferred:
        log(
            f"[STEP][section_header_allowed] candidates='{_truncate_debug_text('|'.join(section_header_deferred[:4]), 120)}' "
            "reason='content_exhausted_after_scroll'"
        )
    tab_candidates = state.local_tab_candidates_by_signature.get(local_tab_signature, [])
    if not tab_candidates and bottom_strip_context:
        recovered_signature, recovered_candidates = _recover_local_tab_state_from_bottom_strip(
            state=state,
            row=row,
            previous_row=previous_row if isinstance(previous_row, dict) else {},
            bottom_strip_candidates=current_bottom_strip_candidates,
            reason="state_missing_but_dump_strip_seen" if dump_strip_seen else "state_missing_but_strip_context",
        )
        if recovered_signature:
            local_tab_signature = recovered_signature
            tab_candidates = recovered_candidates
            local_tab_gate_reason = "recovered_local_tab_state"
    if not tab_candidates:
        _clear_last_selected_local_tab_hint(state, reason="local_tab_state_missing")
        row["local_tab_gate_evaluated"] = True
        row["local_tab_block_reason"] = "local_tab_state_missing" if not local_tab_signature else "strip_not_detected"
        log(
            f"[STEP][local_tab_gate] allowed=false reason='{row['local_tab_block_reason']}' "
            "tabs='none' "
            f"active='{_truncate_debug_text(str(state.current_local_tab_active_rid or ''), 96)}' "
            "unvisited='none'"
        )
        return False
    sorted_tab_candidates = _sort_local_tab_candidates_left_to_right(tab_candidates)
    log(
        f"[STEP][local_tab_candidates] candidates='{_truncate_debug_text(_summarize_candidate_labels(tab_candidates), 120)}'"
    )
    log(
        f"[STEP][local_tab_sorted] order='{_truncate_debug_text(_summarize_candidate_labels(sorted_tab_candidates), 120)}'"
    )
    visited_tabs = state.visited_local_tabs_by_signature.setdefault(local_tab_signature, set())
    if len(sorted_tab_candidates) > 5:
        row["local_tab_gate_evaluated"] = True
        row["local_tab_block_reason"] = "too_many_local_tab_candidates"
        log(
            f"[STEP][local_tab_gate] allowed=false reason='too_many_local_tab_candidates' "
            f"tabs='{_truncate_debug_text(_summarize_candidate_labels(tab_candidates), 120)}' "
            f"active='{_truncate_debug_text(str(state.current_local_tab_active_rid or ''), 96)}' "
            "unvisited='none'"
        )
        return False
    if len(sorted_tab_candidates) < 2:
        active_candidate, _active_source, _active_label = _resolve_active_local_tab_candidate_for_progression(
            state=state,
            sorted_tab_candidates=sorted_tab_candidates,
            row=row,
            previous_row=previous_row if isinstance(previous_row, dict) else {},
        )
        if isinstance(active_candidate, dict):
            state.current_local_tab_signature = local_tab_signature
            state.current_local_tab_active_rid = str(active_candidate.get("rid", "") or "").strip()
            state.current_local_tab_active_label = str(active_candidate.get("label", "") or "").strip()
            state.current_local_tab_active_age = 0
        row["local_tab_gate_evaluated"] = True
        row["local_tab_block_reason"] = "single_local_tab_no_progression"
        log(
            f"[STEP][local_tab_gate] allowed=false reason='single_local_tab_no_progression' "
            f"tabs='{_truncate_debug_text(_summarize_candidate_labels(tab_candidates), 120)}' "
            f"active='{_truncate_debug_text(str(state.current_local_tab_active_rid or ''), 96)}' "
            "unvisited='none'"
        )
        return False
    active_candidate, active_source, active_label = _resolve_active_local_tab_candidate_for_progression(
        state=state,
        sorted_tab_candidates=sorted_tab_candidates,
        row=row,
        previous_row=previous_row if isinstance(previous_row, dict) else {},
    )
    log(
        f"[STEP][local_tab_active_resolved] source='{active_source}' "
        f"active='{_truncate_debug_text(active_label, 96)}'"
    )
    active_index = sorted_tab_candidates.index(active_candidate) if active_candidate in sorted_tab_candidates else -1
    active_rid = str(active_candidate.get("rid", "") or "").strip().lower() if isinstance(active_candidate, dict) else ""
    if active_source not in {"committed", "last_selected_hint"} and active_rid:
        state.current_local_tab_active_rid = active_rid
        state.current_local_tab_active_label = str(active_candidate.get("label", "") or "").strip()
        state.current_local_tab_active_age = 0
    progression_tab = sorted_tab_candidates[active_index + 1] if 0 <= active_index < len(sorted_tab_candidates) - 1 else None
    remaining_tabs_by_visit = [
        candidate
        for candidate in sorted_tab_candidates
        if str(candidate.get("rid", "") or "").strip().lower()
        and str(candidate.get("rid", "") or "").strip().lower() not in {rid.lower() for rid in visited_tabs}
        and str(candidate.get("rid", "") or "").strip().lower() != active_rid
    ]
    remaining_tabs = list(remaining_tabs_by_visit)
    if progression_tab is not None:
        current_label = ""
        if 0 <= active_index < len(sorted_tab_candidates):
            current_label = str(sorted_tab_candidates[active_index].get("label", "") or sorted_tab_candidates[active_index].get("rid", "") or "").strip()
        next_label = str(progression_tab.get("label", "") or progression_tab.get("rid", "") or "").strip()
        next_rid = str(progression_tab.get("rid", "") or "").strip().lower()
        if not (next_rid and next_rid in {rid.lower() for rid in visited_tabs}):
            log(
                f"[STEP][local_tab_progression] current='{_truncate_debug_text(current_label or active_rid, 96)}' "
                f"next='{_truncate_debug_text(next_label, 96)}'"
            )
            remaining_tabs = [progression_tab]
        elif remaining_tabs:
            fallback_label = str(remaining_tabs[0].get("label", "") or remaining_tabs[0].get("rid", "") or "").strip()
            log(
                f"[STEP][local_tab_progression] current='{_truncate_debug_text(current_label or active_rid, 96)}' "
                f"next='{_truncate_debug_text(fallback_label, 96)}' reason='skip_visited_progression'"
            )
        else:
            log("[STEP][local_tab_skip_reason] reason='visited_progression_tab'")
    elif remaining_tabs:
        current_label = active_label
        if 0 <= active_index < len(sorted_tab_candidates):
            current_label = str(sorted_tab_candidates[active_index].get("label", "") or sorted_tab_candidates[active_index].get("rid", "") or active_label).strip()
        next_label = str(remaining_tabs[0].get("label", "") or remaining_tabs[0].get("rid", "") or "").strip()
        log(
            f"[STEP][local_tab_progression] current='{_truncate_debug_text(current_label or active_rid, 96)}' "
            f"next='{_truncate_debug_text(next_label, 96)}' reason='wrap_to_unvisited'"
        )
    if not remaining_tabs:
        row["local_tab_gate_evaluated"] = True
        row["local_tab_block_reason"] = "no_unvisited_local_tab"
        if progression_tab is None:
            log("[STEP][local_tab_skip_reason] reason='none'")
        log(
            f"[STEP][local_tab_gate] allowed=false reason='no_unvisited_local_tab' "
            f"tabs='{_truncate_debug_text(_summarize_candidate_labels(tab_candidates), 120)}' "
            f"active='{_truncate_debug_text(str(state.current_local_tab_active_rid or ''), 96)}' "
            "unvisited='none'"
        )
        return False
    row["local_tab_gate_evaluated"] = True
    row["local_tab_block_reason"] = ""
    log(
        f"[STEP][local_tab_gate] allowed=true reason='{local_tab_gate_reason}' "
        f"tabs='{_truncate_debug_text(_summarize_candidate_labels(tab_candidates), 120)}' "
        f"active='{_truncate_debug_text(str(state.current_local_tab_active_rid or ''), 96)}' "
        f"unvisited='{_truncate_debug_text(_summarize_candidate_labels(remaining_tabs_by_visit), 120)}'"
    )
    log(
        f"[STEP][local_tab_allowed] tabs='{_truncate_debug_text('|'.join(str(candidate.get('label', '') or '').strip() for candidate in (remaining_tabs_by_visit or remaining_tabs)[:4]), 120)}' "
        "reason='content_candidates_exhausted'"
    )
    next_tab = remaining_tabs[0]
    target_rid, target_label, target_bounds = _record_pending_local_tab_progression(
        state=state,
        signature=local_tab_signature,
        next_candidate=next_tab,
        reason="progression_selected",
    )
    select_ok = False
    try:
        select_ok = bool(client.select(dev=dev, name=target_rid, type_="r", wait_=_TRANSITION_FAST_ACTION_WAIT_SECONDS))
    except Exception:
        select_ok = False
    if not select_ok and target_label:
        try:
            select_ok = bool(client.select(dev=dev, name=target_label, type_="a", wait_=_TRANSITION_FAST_ACTION_WAIT_SECONDS))
        except Exception:
            select_ok = False
    if not select_ok:
        return False
    click_focused_fn = getattr(client, "click_focused", None)
    if callable(click_focused_fn):
        try:
            click_focused_fn(dev=dev, wait_=_TRANSITION_FAST_ACTION_WAIT_SECONDS)
        except Exception:
            pass
    visited_tabs.add(target_rid)
    state.current_local_tab_active_rid = target_rid
    state.current_local_tab_active_label = target_label
    state.current_local_tab_active_age = 0
    _reset_content_phase_after_tab_switch(
        state,
        active_label=target_label,
        active_rid=target_rid,
        active_signature=local_tab_signature,
        active_bounds=target_bounds,
    )
    row["local_tab_transition"] = True
    row["local_tab_selected"] = target_label or target_rid
    log(
        f"[STEP][local_tab_pending] selected='{_truncate_debug_text(target_label or target_rid, 96)}' "
        "reason='progression_selected'"
    )
    log(
        f"[STEP][local_tab_select] selected='{_truncate_debug_text(target_label or target_rid, 96)}' "
        "reason='next_unvisited_local_tab'"
    )
    return True
