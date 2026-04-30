from __future__ import annotations

import re
from typing import Any, Callable

from tb_runner.utils import parse_bounds_str


def _scroll_state(state: Any) -> Any:
    return getattr(state, "scroll_state", state)


def _node_label_blob(node: dict[str, Any]) -> str:
    return " ".join(
        [
            str(node.get("text", "") or "").strip(),
            str(node.get("contentDescription", "") or "").strip(),
            str(node.get("talkbackLabel", "") or "").strip(),
            str(node.get("label", "") or "").strip(),
        ]
    ).strip()


def _iter_tree_nodes_with_parent(nodes: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    flat: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    stack: list[tuple[Any, dict[str, Any] | None]] = [(node, None) for node in reversed(nodes)]
    while stack:
        node, parent = stack.pop()
        if not isinstance(node, dict):
            continue
        flat.append((node, parent))
        children = node.get("children")
        if isinstance(children, list):
            for child in reversed(children):
                stack.append((child, node))
    return flat


def _normalize_cta_candidate_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _extract_cta_node_label(node: dict[str, Any]) -> str:
    return _normalize_cta_candidate_label(
        str(node.get("text", "") or "").strip()
        or str(node.get("contentDescription", "") or "").strip()
        or str(node.get("talkbackLabel", "") or "").strip()
        or str(node.get("label", "") or "").strip()
    )


def _build_scroll_fallback_signature(
    *,
    local_tab_signature: str,
    active_rid: str,
    content_candidates: list[dict[str, Any]],
    chrome_excluded: list[str],
    current_focus_signature: str = "",
) -> str:
    visible_content = "|".join(str(candidate.get("label", "") or "").strip() for candidate in content_candidates[:4]) or "none"
    chrome = "|".join(chrome_excluded[:3]) or "none"
    return "||".join(
        [
            str(local_tab_signature or "").strip().lower(),
            str(active_rid or "").strip().lower(),
            visible_content.lower(),
            chrome.lower(),
            str(current_focus_signature or "").strip().lower(),
        ]
    )


def _describe_scrollable_content_phase(nodes: Any) -> tuple[bool, list[str], str]:
    if not isinstance(nodes, list):
        return False, [], ""
    flat_nodes = _iter_tree_nodes_with_parent(nodes)
    bounds_candidates = [
        parse_bounds_str(str(node.get("boundsInScreen", "") or node.get("bounds", "") or "").strip())
        for node, _ in flat_nodes
        if isinstance(node, dict)
    ]
    bounds_candidates = [bounds for bounds in bounds_candidates if bounds]
    if not bounds_candidates:
        return False, [], ""
    viewport_top = min(bounds[1] for bounds in bounds_candidates)
    viewport_bottom = max(bounds[3] for bounds in bounds_candidates)
    viewport_height = max(1, viewport_bottom - viewport_top)
    min_scroll_height = max(int(viewport_height * 0.24), 220)
    max_scroll_center_y = viewport_bottom - int(viewport_height * 0.06)
    scrollable_labels: list[str] = []
    content_bounds = ""
    for node, _ in flat_nodes:
        if not isinstance(node, dict) or node.get("visibleToUser", True) is False:
            continue
        bounds = parse_bounds_str(str(node.get("boundsInScreen", "") or node.get("bounds", "") or "").strip())
        if not bounds:
            continue
        resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip().lower()
        class_name = str(node.get("className", "") or node.get("class", "") or "").strip().lower()
        scrollable = bool(node.get("scrollable"))
        scroll_like = bool(
            scrollable
            or "recyclerview" in class_name
            or "scrollview" in class_name
            or "nestedscrollview" in class_name
            or "listview" in class_name
            or "recycler" in resource_id
            or "scroll" in resource_id
        )
        if not scroll_like:
            continue
        height = max(1, bounds[3] - bounds[1])
        center_y = (bounds[1] + bounds[3]) // 2
        label = _extract_cta_node_label(node) or _node_label_blob(node) or str(node.get("viewIdResourceName", "") or node.get("className", "") or "").strip()
        scrollable_labels.append(label or class_name or resource_id or "scrollable")
        explicit_scrollable = bool(node.get("scrollable"))
        if (
            (explicit_scrollable and height >= max(int(viewport_height * 0.18), 160))
            or (height >= min_scroll_height and center_y <= max_scroll_center_y)
        ):
            content_bounds = str(node.get("boundsInScreen", "") or node.get("bounds", "") or "").strip()
            return True, scrollable_labels[:4], content_bounds
    return False, scrollable_labels[:4], content_bounds


def _maybe_apply_scroll_ready_continue_impl(
    *,
    row: dict[str, Any],
    stop: bool,
    reason: str,
    stop_eval_inputs: dict[str, Any],
    state: Any,
    step_idx: int,
    scenario_id: str,
    log_fn: Callable[[str], None],
    truncate_fn: Callable[[Any, int], str],
    normalize_move_result_fn: Callable[[dict[str, Any]], str],
    scroll_ready_version: str,
) -> tuple[bool, str, bool]:
    cluster_signature = str(row.get("scroll_ready_cluster_signature", "") or "").strip()
    if not stop or not bool(row.get("scroll_ready_state", False)) or not cluster_signature:
        return stop, reason, False
    if reason not in {"repeat_no_progress", "bounded_two_card_loop", "repeat_semantic_stall", "repeat_semantic_stall_after_escape"}:
        return stop, reason, False
    if bool(stop_eval_inputs.get("terminal_signal", False)) or bool(stop_eval_inputs.get("is_global_nav", False)):
        return stop, reason, False
    scroll_state = _scroll_state(state)
    retry_counts = dict(getattr(scroll_state, "scroll_ready_retry_counts", {}) or {})
    attempt = int(retry_counts.get(cluster_signature, 0) or 0) + 1
    max_attempts = 2
    if attempt > max_attempts:
        scroll_state.pending_scroll_ready_cluster_signature = ""
        log_fn(
            f"[STEP][scroll_ready] cluster='{truncate_fn(cluster_signature, 120)}' "
            "reason='attempt_limit_reached' "
            f"attempt={attempt - 1}/{max_attempts} "
            f"version='{scroll_ready_version}'"
        )
        return stop, reason, False
    retry_counts[cluster_signature] = attempt
    scroll_state.scroll_ready_retry_counts = retry_counts
    scroll_state.pending_scroll_ready_cluster_signature = cluster_signature
    move_result = normalize_move_result_fn(row) or str(row.get("move_result", "") or "").strip().lower() or "none"
    log_fn(
        f"[STEP][scroll_ready_move] step={step_idx} scenario='{scenario_id}' "
        f"cluster='{truncate_fn(cluster_signature, 120)}' "
        f"result='{truncate_fn(move_result, 48)}' "
        f"attempt={attempt}/{max_attempts} "
        f"version='{scroll_ready_version}'"
    )
    return False, "", True


def _record_pending_scroll_ready_move_impl(
    *,
    row: dict[str, Any],
    state: Any,
    step_idx: int,
    scenario_id: str,
    log_fn: Callable[[str], None],
    truncate_fn: Callable[[Any, int], str],
    normalize_move_result_fn: Callable[[dict[str, Any]], str],
    scroll_ready_version: str,
) -> None:
    scroll_state = _scroll_state(state)
    pending_cluster_signature = str(getattr(scroll_state, "pending_scroll_ready_cluster_signature", "") or "").strip()
    if not pending_cluster_signature:
        return
    move_result = normalize_move_result_fn(row) or str(row.get("move_result", "") or "").strip().lower() or "none"
    log_fn(
        f"[STEP][scroll_ready_move] step={step_idx} scenario='{scenario_id}' "
        f"cluster='{truncate_fn(pending_cluster_signature, 120)}' "
        f"result='{truncate_fn(move_result, 48)}' "
        f"visible='{truncate_fn(row.get('visible_label', ''), 120)}' "
        f"version='{scroll_ready_version}'"
    )
    if move_result in {"moved", "scrolled", "edge_realign_then_moved"}:
        retry_counts = dict(getattr(scroll_state, "scroll_ready_retry_counts", {}) or {})
        retry_counts.pop(pending_cluster_signature, None)
        scroll_state.scroll_ready_retry_counts = retry_counts
        scroll_state.pending_scroll_ready_cluster_signature = ""
