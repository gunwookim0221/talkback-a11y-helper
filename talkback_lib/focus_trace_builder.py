"""PR14-B: get_focus trace/payload 조립 책임 분리 유틸."""

from __future__ import annotations

from typing import Any


def build_initial_get_focus_trace(serial: str, req_id: str, mode: str) -> dict[str, Any]:
    return {
        "serial": serial,
        "req_id": req_id,
        "started_at": 0.0,
        "helper_status_ok": False,
        "response_received": False,
        "empty_reason": "",
        "fallback_used": False,
        "fallback_reason": "",
        "fallback_dump_elapsed_sec": 0.0,
        "fallback_found": False,
        "fallback_node_label": "",
        "fallback_node_view_id": "",
        "fallback_node_bounds": "",
        "fallback_dump_nodes": [],
        "elapsed_before_fallback_sec": 0.0,
        "total_elapsed_sec": 0.0,
        "focus_payload_source": "none",
        "final_payload_source": "none",
        "response_success": False,
        "success_field_present": False,
        "accepted_with_success_false": False,
        "success_false_top_level_dump_attempted": False,
        "success_false_top_level_dump_found": False,
        "success_false_top_level_dump_skipped": False,
        "dump_skip_reason": "",
        "top_level_signature": "",
        "final_focus_reason": "",
        "dump_replace_reason": "",
        "mode": "fast" if str(mode).strip().lower() == "fast" else "normal",
        "top_level_payload_sufficient": False,
    }


def extract_focus_payload_candidate(result: dict[str, Any]) -> tuple[dict[str, Any], str]:
    focus_node: dict[str, Any] = {}
    payload_candidate_source = "none"
    for key in ("node", "focusNode", "focusedNode", "focus"):
        node = result.get(key)
        if isinstance(node, dict):
            focus_node = node
            payload_candidate_source = "nested_node"
            break

    if not focus_node and any(
        k in result for k in ("text", "viewIdResourceName", "contentDescription", "boundsInScreen", "accessibilityFocused", "focused")
    ):
        focus_node = dict(result)
        payload_candidate_source = "top_level"

    return focus_node, payload_candidate_source
