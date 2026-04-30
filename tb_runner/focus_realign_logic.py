from __future__ import annotations

import re
from typing import Any, Callable

from tb_runner.container_group_logic import _normalize_logical_text
from tb_runner.utils import parse_bounds_str


def _node_label_blob(node: dict[str, Any]) -> str:
    return " ".join(
        [
            str(node.get("text", "") or "").strip(),
            str(node.get("contentDescription", "") or "").strip(),
            str(node.get("talkbackLabel", "") or "").strip(),
            str(node.get("label", "") or "").strip(),
        ]
    ).strip()


def _normalize_cta_candidate_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _extract_cta_node_label(node: dict[str, Any]) -> str:
    return _normalize_cta_candidate_label(
        str(node.get("text", "") or "").strip()
        or str(node.get("contentDescription", "") or "").strip()
        or str(node.get("talkbackLabel", "") or "").strip()
        or str(node.get("label", "") or "").strip()
    )


def _representative_focus_matches(
    *,
    focus_node: Any,
    target_rid: str,
    target_label: str,
    target_bounds: str,
) -> bool:
    if not isinstance(focus_node, dict):
        return False
    focus_rid = str(focus_node.get("viewIdResourceName", "") or focus_node.get("resourceId", "") or "").strip()
    if target_rid and focus_rid == target_rid:
        return True
    focus_label = _extract_cta_node_label(focus_node) or _node_label_blob(focus_node)
    if target_label and focus_label and target_label == focus_label:
        return True
    focus_bounds = str(focus_node.get("boundsInScreen", "") or focus_node.get("bounds", "") or "").strip()
    focus_bounds_tuple = parse_bounds_str(focus_bounds)
    target_bounds_tuple = parse_bounds_str(target_bounds)
    if not focus_bounds_tuple or not target_bounds_tuple:
        return False
    left = max(focus_bounds_tuple[0], target_bounds_tuple[0])
    top = max(focus_bounds_tuple[1], target_bounds_tuple[1])
    right = min(focus_bounds_tuple[2], target_bounds_tuple[2])
    bottom = min(focus_bounds_tuple[3], target_bounds_tuple[3])
    return right > left and bottom > top


def _focus_anchor_match_reason(
    *,
    row: dict[str, Any],
    selected_rid: str,
    selected_label: str,
    selected_bounds: str,
    selected_cluster_signature: str,
) -> tuple[bool, str]:
    current_rid = str(row.get("focus_view_id", "") or "").strip()
    current_label = str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    current_bounds = str(row.get("focus_bounds", "") or "").strip()
    current_cluster_signature = str(row.get("focus_cluster_signature", "") or "").strip()
    if current_rid and selected_rid and current_rid == selected_rid:
        return True, "resource_id_match"
    normalized_current = _normalize_logical_text(current_label)
    normalized_selected = _normalize_logical_text(selected_label)
    if normalized_current and normalized_selected and normalized_current == normalized_selected:
        return True, "normalized_label_match"
    if current_bounds and selected_bounds and _representative_focus_matches(
        focus_node={"boundsInScreen": current_bounds},
        target_rid="",
        target_label="",
        target_bounds=selected_bounds,
    ):
        return True, "bounds_overlap"
    if current_cluster_signature and selected_cluster_signature and current_cluster_signature == selected_cluster_signature:
        return True, "cluster_signature_match"
    return False, "representative_focus_mismatch"


def _maybe_realign_focus_to_representative_impl(
    *,
    client: Any,
    dev: str,
    row: dict[str, Any],
    selected_node: dict[str, Any],
    selected_rid: str,
    selected_label: str,
    selected_bounds: str,
    scenario_id: str,
    step_idx: int,
    mismatch_logged: bool,
    force_reason: str,
    scenario_perf: Any,
    focus_matches_fn: Callable[..., bool],
    extract_label_fn: Callable[[dict[str, Any]], str],
    label_blob_fn: Callable[[dict[str, Any]], str],
    truncate_fn: Callable[..., str],
    log_fn: Callable[[str], None],
) -> tuple[bool, str, dict[str, Any] | None]:
    current_rid = str(row.get("focus_view_id", "") or "").strip()
    current_label = str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    current_bounds = str(row.get("focus_bounds", "") or "").strip()
    if (
        current_rid == selected_rid
        or (current_label and selected_label and current_label == selected_label)
        or (
            current_bounds
            and selected_bounds
            and focus_matches_fn(
                focus_node={"boundsInScreen": current_bounds},
                target_rid="",
                target_label="",
                target_bounds=selected_bounds,
            )
        )
    ):
        return False, "already_aligned", None
    if not mismatch_logged:
        log_fn(
            f"[STEP][focus_context_mismatch] selected='{truncate_fn(selected_label or selected_rid, 96)}' "
            f"current_focus='{truncate_fn(current_label or current_rid, 96)}' "
            "reason='representative_differs_from_focus_context'"
        )
    get_focus_fn = getattr(client, "get_focus", None)
    select_fn = getattr(client, "select", None)
    if not callable(get_focus_fn) or not callable(select_fn):
        log_fn(
            f"[STEP][focus_realign_fail] target='{truncate_fn(selected_label or selected_rid, 96)}' "
            "reason='align_primitives_unavailable'"
        )
        return False, "align_primitives_unavailable", None
    attempts: list[tuple[str, str, str]] = []
    if selected_rid:
        attempts.append(("rid", "r", selected_rid))
    if selected_label:
        attempts.append(("label", "a", selected_label))
    attempts = attempts[:2]
    for attempt_index, (method, target_type, target_value) in enumerate(attempts, start=1):
        if force_reason:
            if scenario_perf is not None:
                scenario_perf.realign_attempt_count += 1
            log_fn(
                f"[STEP][focus_force_realign] target='{truncate_fn(selected_label or selected_rid, 96)}' "
                f"method='{method}' reason='{force_reason}'"
            )
        log_fn(
            f"[STEP][focus_realign] target='{truncate_fn(selected_label or selected_rid, 96)}' "
            f"method='{method}' attempt={attempt_index}"
        )
        try:
            select_fn(dev=dev, name=target_value, type_=target_type, wait_=1.2)
        except Exception:
            continue
        focus_node = get_focus_fn(
            dev=dev,
            wait_seconds=0.35,
            allow_fallback_dump=False,
            mode="fast",
        )
        if focus_matches_fn(
            focus_node=focus_node,
            target_rid=selected_rid,
            target_label=selected_label,
            target_bounds=selected_bounds,
        ):
            resolved_focus = extract_label_fn(focus_node) or label_blob_fn(focus_node) or selected_label or selected_rid
            log_fn(
                f"[STEP][focus_realign_success] target='{truncate_fn(selected_label or selected_rid, 96)}' "
                f"resolved_focus='{truncate_fn(resolved_focus, 96)}'"
            )
            if force_reason:
                if scenario_perf is not None:
                    scenario_perf.realign_success_count += 1
                log_fn(
                    f"[STEP][focus_force_realign_success] target='{truncate_fn(selected_label or selected_rid, 96)}' "
                    f"resolved_focus='{truncate_fn(resolved_focus, 96)}'"
                )
            return True, "matched", focus_node if isinstance(focus_node, dict) else selected_node
    log_fn(
        f"[STEP][focus_realign_fail] target='{truncate_fn(selected_label or selected_rid, 96)}' "
        "reason='no_match'"
    )
    if force_reason:
        log_fn(
            f"[STEP][focus_force_realign_fail] target='{truncate_fn(selected_label or selected_rid, 96)}' "
            "reason='no_match'"
        )
    return False, "no_match", None
