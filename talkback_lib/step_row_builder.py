"""PR14-B: collect_focus_step row 조립 책임 분리 유틸."""

from __future__ import annotations

from typing import Any


def create_base_step_row(step_index: int) -> dict[str, Any]:
    return {
        "step_index": step_index,
        "move_result": None,
        "last_smart_nav_result": "",
        "last_smart_nav_detail": "",
        "last_smart_nav_terminal": False,
        "smart_nav_req_id": "",
        "smart_nav_status": "",
        "smart_nav_detail": "",
        "smart_nav_requested_view_id": "",
        "smart_nav_requested_label": "",
        "smart_nav_resolved_view_id": "",
        "smart_nav_resolved_label": "",
        "smart_nav_actual_view_id": "",
        "smart_nav_actual_label": "",
        "smart_nav_success": False,
        "post_move_verdict_source": "focus_announcement",
        "focus_node": {},
        "focus_text": "",
        "focus_content_description": "",
        "visible_label": "",
        "normalized_visible_label": "",
        "partial_announcements": [],
        "merged_announcement": "",
        "normalized_announcement": "",
        "dump_tree_nodes": [],
        "focus_view_id": "",
        "focus_bounds": "",
        "last_announcements": [],
        "last_merged_announcement": "",
        "get_focus_fallback_dump_elapsed_sec": 0.0,
        "step_dump_tree_elapsed_sec": 0.0,
        "step_dump_tree_used": False,
        "step_dump_tree_reason": "",
        "t_step_start": 0.0,
        "t_after_move": 0.0,
        "t_after_ann": 0.0,
        "t_after_get_focus": 0.0,
        "announcement_count": 0,
        "announcement_window_sec": 0.0,
        "announcement_extra_wait_sec": 0.0,
        "prev_speech_same": False,
        "prev_speech_similar": False,
        "focus_payload_source": "none",
        "get_focus_response_success": False,
        "get_focus_top_level_success_false": False,
        "get_focus_success_false_top_level_dump_attempted": False,
        "get_focus_success_false_top_level_dump_found": False,
        "get_focus_success_false_top_level_dump_skipped": False,
        "get_focus_dump_skip_reason": "",
        "get_focus_top_level_signature": "",
        "get_focus_top_level_payload_sufficient": False,
        "get_focus_final_payload_source": "none",
        "get_focus_final_focus_reason": "",
        "get_focus_dump_replace_reason": "",
        "trim_considered": False,
        "trim_applied": False,
        "trim_before": "",
        "trim_after": "",
        "trim_reason": "",
        "trim_reject_reason": "",
        "announcement_stable_reason": "",
        "announcement_stable_source": "",
        "snapshot_reason": "",
        "used_snapshot": False,
        "snapshot_contaminated": False,
    }


def populate_focus_fields_from_node(step: dict[str, Any], safe_focus_node: dict[str, Any], normalize_bounds: Any) -> None:
    step["focus_node"] = safe_focus_node
    step["focus_text"] = safe_focus_node.get("text", "") if isinstance(safe_focus_node, dict) else ""
    step["focus_content_description"] = safe_focus_node.get("contentDescription", "") if isinstance(safe_focus_node, dict) else ""
    step["focus_view_id"] = safe_focus_node.get("viewIdResourceName", "") if isinstance(safe_focus_node, dict) else ""
    step["focus_bounds"] = normalize_bounds(safe_focus_node) if isinstance(safe_focus_node, dict) else ""


def populate_get_focus_trace_fields(step: dict[str, Any], trace: dict[str, Any]) -> None:
    step["get_focus_empty_reason"] = str(trace.get("empty_reason", "") or "")
    step["get_focus_fallback_used"] = bool(trace.get("fallback_used", False))
    step["get_focus_fallback_found"] = bool(trace.get("fallback_found", False))
    step["get_focus_req_id"] = str(trace.get("req_id", "") or "")
    step["get_focus_total_elapsed_sec"] = round(float(trace.get("total_elapsed_sec", 0.0) or 0.0), 3)
    step["focus_payload_source"] = str(trace.get("focus_payload_source", "none") or "none")
    step["get_focus_response_success"] = bool(trace.get("response_success", False))
    step["get_focus_top_level_success_false"] = bool(trace.get("accepted_with_success_false", False))
    step["get_focus_success_false_top_level_dump_attempted"] = bool(trace.get("success_false_top_level_dump_attempted", False))
    step["get_focus_success_false_top_level_dump_found"] = bool(trace.get("success_false_top_level_dump_found", False))
    step["get_focus_success_false_top_level_dump_skipped"] = bool(trace.get("success_false_top_level_dump_skipped", False))
    step["get_focus_dump_skip_reason"] = str(trace.get("dump_skip_reason", "") or "")
    step["get_focus_top_level_signature"] = str(trace.get("top_level_signature", "") or "")
    step["get_focus_top_level_payload_sufficient"] = bool(trace.get("top_level_payload_sufficient", False))
    step["get_focus_final_payload_source"] = str(trace.get("final_payload_source", "none") or "none")
    step["get_focus_final_focus_reason"] = str(trace.get("final_focus_reason", "") or "")
    step["get_focus_dump_replace_reason"] = str(trace.get("dump_replace_reason", "") or "")


def extract_smart_nav_row_fields(smart_nav_result: dict[str, Any], last_smart_nav_terminal: bool) -> dict[str, Any]:
    return {
        "last_smart_nav_result": str(smart_nav_result.get("status", "") or "").strip().lower(),
        "last_smart_nav_detail": str(smart_nav_result.get("detail", "") or "").strip().lower(),
        "last_smart_nav_terminal": bool(last_smart_nav_terminal),
        "smart_nav_req_id": str(smart_nav_result.get("req_id", "") or smart_nav_result.get("reqId", "") or "").strip(),
        "smart_nav_status": str(smart_nav_result.get("status", "") or "").strip().lower(),
        "smart_nav_detail": str(smart_nav_result.get("detail", "") or "").strip().lower(),
        "smart_nav_requested_view_id": str(
            smart_nav_result.get("requested_target_view_id", "")
            or smart_nav_result.get("requestedTargetViewId", "")
            or ""
        ).strip(),
        "smart_nav_requested_label": str(
            smart_nav_result.get("requested_target_label", "")
            or smart_nav_result.get("requestedTargetLabel", "")
            or ""
        ).strip(),
        "smart_nav_resolved_view_id": str(
            smart_nav_result.get("resolved_focus_view_id", "")
            or smart_nav_result.get("resolvedFocusViewId", "")
            or ""
        ).strip(),
        "smart_nav_resolved_label": str(
            smart_nav_result.get("resolved_focus_label", "")
            or smart_nav_result.get("resolvedFocusLabel", "")
            or ""
        ).strip(),
        "smart_nav_actual_view_id": str(
            smart_nav_result.get("actual_focused_view_id", "")
            or smart_nav_result.get("actualFocusedViewId", "")
            or ""
        ).strip(),
        "smart_nav_actual_label": str(
            smart_nav_result.get("actual_focused_label", "")
            or smart_nav_result.get("actualFocusedLabel", "")
            or ""
        ).strip(),
        "smart_nav_success": bool(smart_nav_result.get("success", False)),
    }


def build_noise_trim_anchor_labels(step: dict[str, Any], safe_focus_node: dict[str, Any]) -> list[str]:
    return [
        str(step.get("visible_label", "") or "").strip(),
        str(safe_focus_node.get("talkbackLabel", "") or "").strip() if isinstance(safe_focus_node, dict) else "",
        str(safe_focus_node.get("text", "") or "").strip() if isinstance(safe_focus_node, dict) else "",
        str(safe_focus_node.get("contentDescription", "") or "").strip() if isinstance(safe_focus_node, dict) else "",
    ]


def compute_prev_speech_flags(prev_norm: str, curr_norm: str) -> tuple[bool, bool]:
    prev_speech_same = bool(prev_norm and curr_norm and prev_norm == curr_norm)
    prev_speech_similar = bool(
        prev_norm and curr_norm and prev_norm != curr_norm and (prev_norm in curr_norm or curr_norm in prev_norm)
    )
    return prev_speech_same, prev_speech_similar
