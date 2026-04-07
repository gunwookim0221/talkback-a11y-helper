from __future__ import annotations

import time
import uuid
from typing import Any

from talkback_lib.utils import normalize_bounds, parse_bounds_tuple, safe_parse_json_payload


def parse_json_payload(payload: str, label: str) -> dict[str, Any]:
    return safe_parse_json_payload(payload=payload, label=label)


def normalize_focus_bounds(node: dict[str, Any]) -> str:
    return normalize_bounds(node)


def parse_focus_bounds_tuple(bounds: str) -> tuple[int, int, int, int] | None:
    return parse_bounds_tuple(bounds)


def is_meaningful_focus_node(node: Any) -> bool:
    if not isinstance(node, dict) or not node:
        return False

    text_value = node.get("text")
    if isinstance(text_value, str) and text_value.strip():
        return True

    content_desc = node.get("contentDescription")
    if isinstance(content_desc, str) and content_desc.strip():
        return True

    view_id = node.get("viewIdResourceName")
    if isinstance(view_id, str) and view_id.strip():
        return True

    bounds = node.get("boundsInScreen")
    if isinstance(bounds, dict) and any(key in bounds for key in ("l", "t", "r", "b", "left", "top", "right", "bottom")):
        return True

    if bool(node.get("accessibilityFocused")):
        return True

    if bool(node.get("focused")):
        return True

    return False


def find_focused_node_in_tree(nodes: Any) -> dict[str, Any]:
    def _walk(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}

        if bool(node.get("accessibilityFocused")):
            return node

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                found = _walk(child)
                if found:
                    return found
        return {}

    def _walk_focused(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}

        if bool(node.get("focused")):
            return node

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                found = _walk_focused(child)
                if found:
                    return found
        return {}

    if not isinstance(nodes, list):
        return {}

    for node in nodes:
        found = _walk(node)
        if found:
            return found

    for node in nodes:
        found = _walk_focused(node)
        if found:
            return found

    return {}


def get_focus(client: Any, dev: Any = None, wait_seconds: float = 2.0, allow_fallback_dump: bool = True, mode: str = "normal") -> dict[str, Any]:
    started = time.monotonic()
    serial = client._resolve_serial(dev) or "default"
    req_id = str(uuid.uuid4())[:8]
    client.last_get_focus_trace = {
        "serial": serial,
        "req_id": req_id,
        "started_at": time.time(),
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
    fast_mode = client.last_get_focus_trace["mode"] == "fast"
    helper_ok = client._has_recent_helper_ok(dev=dev) or client.check_helper_status(dev=dev)
    client.last_get_focus_trace["helper_status_ok"] = helper_ok
    client._debug_print(
        f"[DEBUG][get_focus] start serial={serial} req_id={req_id} "
        f"wait={wait_seconds:.2f}s helper_ok={helper_ok} mode={client.last_get_focus_trace['mode']}"
    )
    if not helper_ok:
        client.last_get_focus_trace["empty_reason"] = "helper_not_ready"
        client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
        return {}

    try:
        result = client._helper_bridge._request_get_focus(
            dev=dev,
            req_id=req_id,
            wait_seconds=wait_seconds,
            poll_interval_sec=0.2,
        )
    except RuntimeError as exc:
        client.last_get_focus_trace["response_received"] = False
        client.last_get_focus_trace["response_success"] = False
        client.last_get_focus_trace["empty_reason"] = "parse_error"
        client.last_get_focus_trace["fallback_used"] = bool(allow_fallback_dump)
        client.last_get_focus_trace["fallback_reason"] = "parse_error"
        client.last_get_focus_trace["elapsed_before_fallback_sec"] = time.monotonic() - started
        if not allow_fallback_dump:
            client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            client.last_get_focus_trace["final_payload_source"] = "none"
            client.last_get_focus_trace["final_focus_reason"] = "parse_error_fast_path_skip_dump"
            return {}
        client._debug_print(
            f"[DEBUG][get_focus] fallback_enter serial={serial} req_id={req_id} "
            f"reason=parse_error error={exc} "
            f"elapsed_before_fallback={client.last_get_focus_trace['elapsed_before_fallback_sec']:.3f}s"
        )
        fallback_started = time.monotonic()
        try:
            dump_nodes = client.dump_tree(dev=dev)
        except Exception as fallback_exc:
            client.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
            client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            client._debug_print(
                f"[DEBUG][get_focus] dump_tree fallback failed serial={serial} req_id={req_id} "
                f"error={fallback_exc} elapsed={client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s"
            )
            return {}
        client.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
        client.last_get_focus_trace["fallback_dump_nodes"] = dump_nodes if isinstance(dump_nodes, list) else []
        fallback_focus_node = client._find_focused_node_in_tree(dump_nodes)
        if fallback_focus_node:
            label = client.extract_visible_label_from_focus(fallback_focus_node)
            view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
            bounds = client._normalize_bounds(fallback_focus_node)
            client.last_get_focus_trace["fallback_found"] = True
            client.last_get_focus_trace["fallback_node_label"] = label
            client.last_get_focus_trace["fallback_node_view_id"] = view_id
            client.last_get_focus_trace["fallback_node_bounds"] = bounds
            client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            client.last_get_focus_trace["focus_payload_source"] = "fallback_dump"
            client.last_get_focus_trace["final_payload_source"] = "fallback_dump"
            client.last_get_focus_trace["final_focus_reason"] = "parse_error_fallback_dump_found"
            client._debug_print(
                f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=True "
                f"label='{label}' view_id='{view_id}' bounds='{bounds}' "
                f"dump_elapsed={client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
                f"total_elapsed={client.last_get_focus_trace['total_elapsed_sec']:.3f}s"
            )
            return fallback_focus_node

        client.last_get_focus_trace["fallback_found"] = False
        client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
        client.last_get_focus_trace["final_payload_source"] = "none"
        client.last_get_focus_trace["final_focus_reason"] = "parse_error_fallback_dump_not_found"
        client._debug_print(
            f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=False "
            f"dump_elapsed={client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
            f"total_elapsed={client.last_get_focus_trace['total_elapsed_sec']:.3f}s"
        )
        return {}

    client.last_get_focus_trace["response_received"] = bool(result)
    success_field_present = "success" in result
    response_success = bool(result.get("success"))
    client.last_get_focus_trace["response_success"] = response_success
    client.last_get_focus_trace["success_field_present"] = success_field_present
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
    client.last_get_focus_trace["focus_payload_source"] = payload_candidate_source

    major_keys = ("text", "contentDescription", "viewIdResourceName", "boundsInScreen")
    key_presence = {k: bool(str(result.get(k, "") or "").strip()) for k in major_keys}
    client._debug_print(
        f"[DEBUG][get_focus] response serial={serial} req_id={req_id} "
        f"success={response_success} keys={key_presence} result_keys={len(result.keys())} "
        f"payload_candidate_source={payload_candidate_source}"
    )

    if client._is_meaningful_focus_node(focus_node):
        accepted_with_success_false = (
            payload_candidate_source == "top_level"
            and not response_success
        )
        client.last_get_focus_trace["accepted_with_success_false"] = accepted_with_success_false
        client.last_get_focus_trace["empty_reason"] = ""
        if accepted_with_success_false:
            normalized_bounds = client._normalize_bounds(focus_node)
            parsed_bounds = client._parse_bounds_tuple(normalized_bounds)
            view_id = str(focus_node.get("viewIdResourceName", "") or "").strip()
            text_value = str(focus_node.get("text", "") or "").strip()
            content_desc = str(focus_node.get("contentDescription", "") or "").strip()
            merged_label = str(focus_node.get("mergedLabel", "") or "").strip()
            class_name = str(focus_node.get("className", "") or "").strip()
            label = client.extract_visible_label_from_focus(focus_node)
            has_focus_flag = bool(focus_node.get("accessibilityFocused")) or bool(focus_node.get("focused"))
            has_valid_bounds = bool(parsed_bounds)
            has_text_like_label = bool(text_value or content_desc or merged_label or label)
            has_identity = bool(view_id or class_name)
            top_level_signature = f"view_id='{view_id}' bounds='{normalized_bounds}' label='{label}'"
            client.last_get_focus_trace["top_level_signature"] = top_level_signature
            strong_top_level_payload = bool(
                has_valid_bounds and (
                    has_text_like_label
                    or (has_focus_flag and has_identity)
                    or (view_id and class_name)
                )
            )
            if not strong_top_level_payload and fast_mode:
                strong_top_level_payload = has_valid_bounds
            client.last_get_focus_trace["top_level_payload_sufficient"] = strong_top_level_payload
            client._debug_print(
                f"[DEBUG][get_focus] dump_skip_candidate={strong_top_level_payload} "
                f"{top_level_signature} has_focus_flag={has_focus_flag}"
            )
            if strong_top_level_payload:
                client.last_get_focus_trace["success_false_top_level_dump_skipped"] = True
                client.last_get_focus_trace["dump_skip_reason"] = "strong_top_level_payload"
                client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_policy_skip_dump"
                print(
                    f"[INFO][get_focus] success=False top_level payload kept without dump fallback "
                    f"serial={serial} req_id={req_id} reason='strong_top_level_payload'"
                )
                return focus_node
            if not allow_fallback_dump:
                client.last_get_focus_trace["success_false_top_level_dump_skipped"] = True
                client.last_get_focus_trace["dump_skip_reason"] = "fast_path_skip_dump"
                client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_fast_path_skip_dump"
                return focus_node
            print(
                f"[WARN][get_focus] success=False top_level payload accepted; trying dump fallback "
                f"serial={serial} req_id={req_id}"
            )
            client.last_get_focus_trace["success_false_top_level_dump_attempted"] = True
            fallback_started = time.monotonic()
            try:
                dump_nodes = client.dump_tree(dev=dev)
            except Exception as exc:
                client.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
                client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_kept_dump_error"
                client.last_get_focus_trace["dump_replace_reason"] = "dump_error"
                client._debug_print(
                    f"[DEBUG][get_focus] dump_tree fallback failed serial={serial} req_id={req_id} "
                    f"error={exc} elapsed={client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s"
                )
                print(
                    f"[INFO][get_focus] success=False top_level payload kept; dump fallback found nothing "
                    f"serial={serial} req_id={req_id}"
                )
                return focus_node
            client.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
            client.last_get_focus_trace["fallback_dump_nodes"] = dump_nodes if isinstance(dump_nodes, list) else []
            fallback_focus_node = client._find_focused_node_in_tree(dump_nodes)
            if fallback_focus_node and client._is_meaningful_focus_node(fallback_focus_node):
                label = client.extract_visible_label_from_focus(fallback_focus_node)
                view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
                bounds = client._normalize_bounds(fallback_focus_node)
                client.last_get_focus_trace["fallback_found"] = True
                client.last_get_focus_trace["success_false_top_level_dump_found"] = True
                client.last_get_focus_trace["fallback_node_label"] = label
                client.last_get_focus_trace["fallback_node_view_id"] = view_id
                client.last_get_focus_trace["fallback_node_bounds"] = bounds
                client.last_get_focus_trace["focus_payload_source"] = "fallback_dump"
                client.last_get_focus_trace["final_payload_source"] = "fallback_dump"
                client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_replaced_by_dump"
                client.last_get_focus_trace["dump_replace_reason"] = "focused_node_from_dump"
                print(
                    f"[INFO][get_focus] success=False top_level payload replaced by dump focused node "
                    f"serial={serial} req_id={req_id}"
                )
                return fallback_focus_node
            print(
                f"[INFO][get_focus] success=False top_level payload kept; dump fallback found nothing "
                f"serial={serial} req_id={req_id}"
            )
            client.last_get_focus_trace["fallback_found"] = False
            client.last_get_focus_trace["success_false_top_level_dump_found"] = False
            client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
            client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_kept_after_dump"
            client.last_get_focus_trace["dump_replace_reason"] = "dump_no_focused_node"
            return focus_node
        client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
        client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
        client.last_get_focus_trace["final_focus_reason"] = "accepted_meaningful_payload"
        return focus_node

    empty_reason = "no_response"
    if result:
        reason_text = str(result.get("reason", "") or "").lower()
        if "찾지 못했습니다" in reason_text:
            empty_reason = "timeout"
        elif not response_success:
            empty_reason = "empty_json"
        else:
            empty_reason = "missing_required_fields"
    client.last_get_focus_trace["empty_reason"] = empty_reason
    client.last_get_focus_trace["fallback_used"] = bool(allow_fallback_dump)
    client.last_get_focus_trace["fallback_reason"] = empty_reason
    client.last_get_focus_trace["elapsed_before_fallback_sec"] = time.monotonic() - started
    if not allow_fallback_dump:
        client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
        client.last_get_focus_trace["final_payload_source"] = "none"
        client.last_get_focus_trace["final_focus_reason"] = "fast_path_skip_dump"
        return {}
    client._debug_print(
        f"[DEBUG][get_focus] fallback_enter serial={serial} req_id={req_id} "
        f"reason={empty_reason} elapsed_before_fallback={client.last_get_focus_trace['elapsed_before_fallback_sec']:.3f}s"
    )
    fallback_started = time.monotonic()
    try:
        dump_nodes = client.dump_tree(dev=dev)
    except Exception as exc:
        client.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
        client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
        client._debug_print(
            f"[DEBUG][get_focus] dump_tree fallback failed serial={serial} req_id={req_id} "
            f"error={exc} elapsed={client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s"
        )
        return {}
    client.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
    client.last_get_focus_trace["fallback_dump_nodes"] = dump_nodes if isinstance(dump_nodes, list) else []

    fallback_focus_node = client._find_focused_node_in_tree(dump_nodes)
    if fallback_focus_node:
        label = client.extract_visible_label_from_focus(fallback_focus_node)
        view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
        bounds = client._normalize_bounds(fallback_focus_node)
        client.last_get_focus_trace["fallback_found"] = True
        client.last_get_focus_trace["fallback_node_label"] = label
        client.last_get_focus_trace["fallback_node_view_id"] = view_id
        client.last_get_focus_trace["fallback_node_bounds"] = bounds
        client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
        client.last_get_focus_trace["focus_payload_source"] = "fallback_dump"
        client.last_get_focus_trace["final_payload_source"] = "fallback_dump"
        client.last_get_focus_trace["final_focus_reason"] = "fallback_dump_found"
        client._debug_print(
            f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=True "
            f"label='{label}' view_id='{view_id}' bounds='{bounds}' "
            f"dump_elapsed={client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
            f"total_elapsed={client.last_get_focus_trace['total_elapsed_sec']:.3f}s"
        )
        return fallback_focus_node

    client.last_get_focus_trace["fallback_found"] = False
    client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
    client.last_get_focus_trace["final_payload_source"] = "none"
    client.last_get_focus_trace["final_focus_reason"] = "fallback_dump_not_found"
    print(
        f"[WARN][get_focus] empty focus result serial={serial} req_id={req_id} "
        f"reason={empty_reason} fallback_found=False"
    )
    client._debug_print(
        f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=False "
        f"dump_elapsed={client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
        f"total_elapsed={client.last_get_focus_trace['total_elapsed_sec']:.3f}s"
    )
    return {}
