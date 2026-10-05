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


def _target_focus_matches(
    *,
    focus_node: Any,
    target_rid: str,
    target_label: str,
    target_bounds: str,
    target_class: str = "",
) -> bool:
    """Strong physical-instance match: exact bounds plus compatible metadata."""
    if not isinstance(focus_node, dict):
        return False
    focus_bounds = parse_bounds_str(focus_node.get("boundsInScreen") or focus_node.get("bounds") or "")
    expected_bounds = parse_bounds_str(target_bounds)
    if not focus_bounds or not expected_bounds or focus_bounds != expected_bounds:
        return False
    focus_rid = str(focus_node.get("viewIdResourceName", "") or focus_node.get("resourceId", "") or "").strip()
    focus_label = _extract_cta_node_label(focus_node) or _node_label_blob(focus_node)
    focus_class = str(focus_node.get("className", "") or focus_node.get("class", "") or "").strip()
    supplied = 0
    for expected, actual in ((target_rid, focus_rid), (target_label, focus_label), (target_class, focus_class)):
        if not expected:
            continue
        supplied += 1
        if _normalize_logical_text(expected) != _normalize_logical_text(actual):
            return False
    return supplied > 0


def _focus_anchor_match_reason(
    *,
    row: dict[str, Any],
    selected_rid: str,
    selected_label: str,
    selected_bounds: str,
    selected_cluster_signature: str,
) -> tuple[bool, str]:
    focus_node = row.get("actual_focus_node")
    if not isinstance(focus_node, dict):
        focus_node = row.get("focus_node")
    target_class = str(row.get("focus_class_name", "") or "").strip()
    if isinstance(focus_node, dict):
        if _target_focus_matches(
            focus_node=focus_node,
            target_rid=selected_rid,
            target_label=selected_label,
            target_bounds=selected_bounds,
            target_class=target_class,
        ) and focus_node.get("accessibilityFocused") is True:
            return True, "strong_instance_match"
        return False, "representative_focus_mismatch"
    current_rid = str(row.get("focus_view_id", "") or "").strip()
    current_label = str(row.get("visible_label", "") or row.get("merged_announcement", "") or "").strip()
    current_bounds = str(row.get("focus_bounds", "") or "").strip()
    current_cluster_signature = str(row.get("focus_cluster_signature", "") or "").strip()
    if current_rid and selected_rid and current_rid == selected_rid:
        return True, "resource_id_match"
    if (_normalize_logical_text(current_label) and
            _normalize_logical_text(current_label) == _normalize_logical_text(selected_label)):
        return True, "normalized_label_match"
    if current_bounds and selected_bounds and _representative_focus_matches(
        focus_node={"boundsInScreen": current_bounds}, target_rid="", target_label="", target_bounds=selected_bounds
    ):
        return True, "bounds_overlap"
    if current_cluster_signature and current_cluster_signature == selected_cluster_signature:
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
    actual_node = row.get("actual_focus_node") if isinstance(row.get("actual_focus_node"), dict) else row.get("focus_node")
    selected_class = str(selected_node.get("className", "") or selected_node.get("class", "") or "").strip()
    if not isinstance(actual_node, dict) and (
        current_rid == selected_rid or (current_label and selected_label and current_label == selected_label)
    ):
        return False, "already_aligned", None
    if _target_focus_matches(
        focus_node=actual_node,
        target_rid=selected_rid,
        target_label=selected_label,
        target_bounds=selected_bounds,
        target_class=selected_class,
    ) and isinstance(actual_node, dict) and actual_node.get("accessibilityFocused") is True:
        return False, "already_aligned", None
    if not mismatch_logged:
        log_fn(
            f"[STEP][focus_context_mismatch] selected='{truncate_fn(selected_label or selected_rid, 96)}' "
            f"current_focus='{truncate_fn(current_label or current_rid, 96)}' "
            "reason='representative_differs_from_focus_context'"
        )
    get_focus_fn = getattr(client, "get_focus", None)
    target_focus_fn = getattr(client, "target_focus_commit", None)
    legacy_select_fn = getattr(client, "select", None)
    if not callable(get_focus_fn) or (not callable(target_focus_fn) and not callable(legacy_select_fn)):
        log_fn(
            f"[STEP][focus_realign_fail] target='{truncate_fn(selected_label or selected_rid, 96)}' "
            "reason='target_focus_commit_unavailable'"
        )
        return False, "target_focus_commit_unavailable", None
    if not callable(target_focus_fn):
        attempts = []
        if selected_rid:
            attempts.append(("rid", "r", selected_rid))
        if selected_label:
            attempts.append(("label", "a", selected_label))
        for attempt_index, (method, target_type, target_value) in enumerate(attempts[:2], start=1):
            if scenario_perf is not None:
                scenario_perf.realign_attempt_count += 1
            if force_reason:
                log_fn(
                    f"[STEP][focus_force_realign] target='{truncate_fn(selected_label or selected_rid, 96)}' "
                    f"method='{method}' reason='{force_reason}'"
                )
            log_fn(
                f"[STEP][focus_realign] target='{truncate_fn(selected_label or selected_rid, 96)}' "
                f"method='{method}' attempt={attempt_index}"
            )
            try:
                legacy_select_fn(dev=dev, name=target_value, type_=target_type, wait_=1.2)
            except Exception:
                continue
            focus_node = get_focus_fn(dev=dev, wait_seconds=0.35, allow_fallback_dump=False, mode="fast")
            if focus_matches_fn(
                focus_node=focus_node, target_rid=selected_rid,
                target_label=selected_label, target_bounds=selected_bounds,
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
            f"[STEP][focus_realign_fail] target='{truncate_fn(selected_label or selected_rid, 96)}' reason='no_match'"
        )
        if force_reason:
            log_fn(
                f"[STEP][focus_force_realign_fail] target='{truncate_fn(selected_label or selected_rid, 96)}' reason='no_match'"
            )
        return False, "no_match", None
    target_descriptor = {
        "bounds": selected_bounds,
        "resource_id": selected_rid,
        "label": selected_label,
        "class_name": selected_class,
    }
    if scenario_perf is not None:
        scenario_perf.realign_attempt_count += 1
    if force_reason:
        log_fn(
            f"[STEP][focus_force_realign] target='{truncate_fn(selected_label or selected_rid, 96)}' "
            f"method='target_descriptor' reason='{force_reason}'"
        )
    log_fn(
        f"[TARGET_FOCUS][attempt] scenario='{scenario_id}' step={step_idx} "
        f"target='{truncate_fn(selected_label or selected_rid, 96)}' rid='{truncate_fn(selected_rid, 96)}' "
        f"bounds='{selected_bounds}' class='{truncate_fn(selected_class, 96)}'"
    )
    try:
        command_result = target_focus_fn(dev=dev, target=target_descriptor, wait_=2.0)
    except Exception as error:
        command_result = {"success": False, "status": "ERROR", "reason": type(error).__name__}
    helper_status = str(command_result.get("status", "") or "ERROR").strip().upper()
    row["target_focus_attempted"] = True
    row["target_focus_status"] = helper_status
    row["target_focus_descriptor"] = target_descriptor
    row["target_focus_fallback_used"] = False
    focus_node = get_focus_fn(dev=dev, wait_seconds=0.35, allow_fallback_dump=False, mode="fast")
    verified = _target_focus_matches(
        focus_node=focus_node,
        target_rid=selected_rid,
        target_label=selected_label,
        target_bounds=selected_bounds,
        target_class=selected_class,
    )
    # Actual accessibility focus evidence is authoritative over command ACK.
    if verified and isinstance(focus_node, dict) and focus_node.get("accessibilityFocused") is True:
        row["target_focus_status"] = "TARGET_MATCHED"
        resolved_focus = extract_label_fn(focus_node) or label_blob_fn(focus_node) or selected_label or selected_rid
        log_fn(
            f"[TARGET_FOCUS][verified] target='{truncate_fn(selected_label or selected_rid, 96)}' "
            f"resolved_focus='{truncate_fn(resolved_focus, 96)}' helper_status='{helper_status}'"
        )
        if scenario_perf is not None:
            scenario_perf.realign_success_count += 1
        return True, "TARGET_MATCHED", focus_node
    log_fn(
        f"[TARGET_FOCUS][failed] target='{truncate_fn(selected_label or selected_rid, 96)}' "
        f"status='{helper_status}' actual='{truncate_fn(extract_label_fn(focus_node) if isinstance(focus_node, dict) else '', 96)}'"
    )
    log_fn(
        f"[STEP][focus_realign_fail] target='{truncate_fn(selected_label or selected_rid, 96)}' "
        f"reason='{helper_status}'"
    )
    if force_reason:
        log_fn(
            f"[STEP][focus_force_realign_fail] target='{truncate_fn(selected_label or selected_rid, 96)}' "
            f"reason='{helper_status}'"
        )
    return False, helper_status, focus_node if isinstance(focus_node, dict) else None
