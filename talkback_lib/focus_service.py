"""PR14-C: get_focus orchestration 보조 service."""

from __future__ import annotations

import time
import uuid
from typing import Any


class FocusService:
    def __init__(self, client: Any) -> None:
        self.client = client

    def get_focus(
        self,
        dev: Any = None,
        wait_seconds: float = 2.0,
        allow_fallback_dump: bool = True,
        mode: str = "normal",
    ) -> dict[str, Any]:
        started = time.monotonic()
        serial = self.client._resolve_serial(dev) or "default"
        req_id = str(uuid.uuid4())[:8]
        self.client._init_get_focus_trace(serial=serial, req_id=req_id, mode=mode)
        fast_mode = self.client.last_get_focus_trace["mode"] == "fast"
        helper_ok = self.client._has_recent_helper_ok(dev=dev) or self.client.check_helper_status(dev=dev)
        self.client.last_get_focus_trace["helper_status_ok"] = helper_ok
        self.client._debug_print(
            f"[DEBUG][get_focus] start serial={serial} req_id={req_id} "
            f"wait={wait_seconds:.2f}s helper_ok={helper_ok} mode={self.client.last_get_focus_trace['mode']}"
        )
        if not helper_ok:
            self.client.last_get_focus_trace["empty_reason"] = "helper_not_ready"
            self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            return {}

        try:
            result = self.client._helper_bridge._request_get_focus(
                dev=dev,
                req_id=req_id,
                wait_seconds=wait_seconds,
                poll_interval_sec=0.2,
            )
        except RuntimeError as exc:
            self.client.last_get_focus_trace["response_received"] = False
            self.client.last_get_focus_trace["response_success"] = False
            self.client.last_get_focus_trace["empty_reason"] = "parse_error"
            self.client.last_get_focus_trace["fallback_used"] = bool(allow_fallback_dump)
            self.client.last_get_focus_trace["fallback_reason"] = "parse_error"
            self.client.last_get_focus_trace["elapsed_before_fallback_sec"] = time.monotonic() - started
            if not allow_fallback_dump:
                self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                self.client.last_get_focus_trace["final_payload_source"] = "none"
                self.client.last_get_focus_trace["final_focus_reason"] = "parse_error_fast_path_skip_dump"
                return {}
            self.client._debug_print(
                f"[DEBUG][get_focus] fallback_enter serial={serial} req_id={req_id} "
                f"reason=parse_error error={exc} "
                f"elapsed_before_fallback={self.client.last_get_focus_trace['elapsed_before_fallback_sec']:.3f}s"
            )
            fallback_focus_node = self.client._run_get_focus_fallback_dump(
                dev=dev,
                serial=serial,
                req_id=req_id,
                started=started,
            )
            if fallback_focus_node:
                label = self.client.extract_visible_label_from_focus(fallback_focus_node)
                view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
                bounds = self.client._normalize_bounds(fallback_focus_node)
                self.client.last_get_focus_trace["final_focus_reason"] = "parse_error_fallback_dump_found"
                self.client._debug_print(
                    f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=True "
                    f"label='{label}' view_id='{view_id}' bounds='{bounds}' "
                    f"dump_elapsed={self.client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
                    f"total_elapsed={self.client.last_get_focus_trace['total_elapsed_sec']:.3f}s"
                )
                return fallback_focus_node

            self.client.last_get_focus_trace["fallback_found"] = False
            self.client.last_get_focus_trace["final_focus_reason"] = "parse_error_fallback_dump_not_found"
            self.client._debug_print(
                f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=False "
                f"dump_elapsed={self.client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
                f"total_elapsed={self.client.last_get_focus_trace['total_elapsed_sec']:.3f}s"
            )
            return {}

        self.client.last_get_focus_trace["response_received"] = bool(result)
        success_field_present = "success" in result
        response_success = bool(result.get("success"))
        self.client.last_get_focus_trace["response_success"] = response_success
        self.client.last_get_focus_trace["success_field_present"] = success_field_present
        focus_node, payload_candidate_source = self.client._extract_focus_payload_candidate(result=result)
        self.client.last_get_focus_trace["focus_payload_source"] = payload_candidate_source

        major_keys = ("text", "contentDescription", "viewIdResourceName", "boundsInScreen")
        key_presence = {k: bool(str(result.get(k, "") or "").strip()) for k in major_keys}
        self.client._debug_print(
            f"[DEBUG][get_focus] response serial={serial} req_id={req_id} "
            f"success={response_success} keys={key_presence} result_keys={len(result.keys())} "
            f"payload_candidate_source={payload_candidate_source}"
        )

        if self.client._is_meaningful_focus_node(focus_node):
            accepted_with_success_false = (
                payload_candidate_source == "top_level"
                and not response_success
            )
            self.client.last_get_focus_trace["accepted_with_success_false"] = accepted_with_success_false
            self.client.last_get_focus_trace["empty_reason"] = ""
            if accepted_with_success_false:
                normalized_bounds = self.client._normalize_bounds(focus_node)
                parsed_bounds = self.client._parse_bounds_tuple(normalized_bounds)
                view_id = str(focus_node.get("viewIdResourceName", "") or "").strip()
                text_value = str(focus_node.get("text", "") or "").strip()
                content_desc = str(focus_node.get("contentDescription", "") or "").strip()
                merged_label = str(focus_node.get("mergedLabel", "") or "").strip()
                class_name = str(focus_node.get("className", "") or "").strip()
                label = self.client.extract_visible_label_from_focus(focus_node)
                has_focus_flag = bool(focus_node.get("accessibilityFocused")) or bool(focus_node.get("focused"))
                has_valid_bounds = bool(parsed_bounds)
                has_text_like_label = bool(text_value or content_desc or merged_label or label)
                has_identity = bool(view_id or class_name)
                top_level_signature = f"view_id='{view_id}' bounds='{normalized_bounds}' label='{label}'"
                self.client.last_get_focus_trace["top_level_signature"] = top_level_signature
                strong_top_level_payload = bool(
                    has_valid_bounds and (
                        has_text_like_label
                        or (has_focus_flag and has_identity)
                        or (view_id and class_name)
                    )
                )
                if not strong_top_level_payload and fast_mode:
                    strong_top_level_payload = has_valid_bounds
                self.client.last_get_focus_trace["top_level_payload_sufficient"] = strong_top_level_payload
                self.client._debug_print(
                    f"[DEBUG][get_focus] dump_skip_candidate={strong_top_level_payload} "
                    f"{top_level_signature} has_focus_flag={has_focus_flag}"
                )
                if strong_top_level_payload:
                    self.client.last_get_focus_trace["success_false_top_level_dump_skipped"] = True
                    self.client.last_get_focus_trace["dump_skip_reason"] = "strong_top_level_payload"
                    self.client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                    self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                    self.client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_policy_skip_dump"
                    print(
                        f"[INFO][get_focus] success=False top_level payload kept without dump fallback "
                        f"serial={serial} req_id={req_id} reason='strong_top_level_payload'"
                    )
                    return focus_node
                if not allow_fallback_dump:
                    self.client.last_get_focus_trace["success_false_top_level_dump_skipped"] = True
                    self.client.last_get_focus_trace["dump_skip_reason"] = "fast_path_skip_dump"
                    self.client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                    self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                    self.client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_fast_path_skip_dump"
                    return focus_node
                print(
                    f"[WARN][get_focus] success=False top_level payload accepted; trying dump fallback "
                    f"serial={serial} req_id={req_id}"
                )
                self.client.last_get_focus_trace["success_false_top_level_dump_attempted"] = True
                fallback_started = time.monotonic()
                try:
                    dump_nodes = self.client.dump_tree(dev=dev)
                except Exception as exc:
                    self.client.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
                    self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                    self.client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                    self.client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_kept_dump_error"
                    self.client.last_get_focus_trace["dump_replace_reason"] = "dump_error"
                    self.client._debug_print(
                        f"[DEBUG][get_focus] dump_tree fallback failed serial={serial} req_id={req_id} "
                        f"error={exc} elapsed={self.client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s"
                    )
                    print(
                        f"[INFO][get_focus] success=False top_level payload kept; dump fallback found nothing "
                        f"serial={serial} req_id={req_id}"
                    )
                    return focus_node
                self.client.last_get_focus_trace["fallback_dump_elapsed_sec"] = time.monotonic() - fallback_started
                self.client.last_get_focus_trace["fallback_dump_nodes"] = dump_nodes if isinstance(dump_nodes, list) else []
                fallback_focus_node = self.client._find_focused_node_in_tree(dump_nodes)
                if fallback_focus_node and self.client._is_meaningful_focus_node(fallback_focus_node):
                    label = self.client.extract_visible_label_from_focus(fallback_focus_node)
                    view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
                    bounds = self.client._normalize_bounds(fallback_focus_node)
                    self.client.last_get_focus_trace["fallback_found"] = True
                    self.client.last_get_focus_trace["success_false_top_level_dump_found"] = True
                    self.client.last_get_focus_trace["fallback_node_label"] = label
                    self.client.last_get_focus_trace["fallback_node_view_id"] = view_id
                    self.client.last_get_focus_trace["fallback_node_bounds"] = bounds
                    self.client.last_get_focus_trace["focus_payload_source"] = "fallback_dump"
                    self.client.last_get_focus_trace["final_payload_source"] = "fallback_dump"
                    self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                    self.client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_replaced_by_dump"
                    self.client.last_get_focus_trace["dump_replace_reason"] = "focused_node_from_dump"
                    print(
                        f"[INFO][get_focus] success=False top_level payload replaced by dump focused node "
                        f"serial={serial} req_id={req_id}"
                    )
                    return fallback_focus_node
                print(
                    f"[INFO][get_focus] success=False top_level payload kept; dump fallback found nothing "
                    f"serial={serial} req_id={req_id}"
                )
                self.client.last_get_focus_trace["fallback_found"] = False
                self.client.last_get_focus_trace["success_false_top_level_dump_found"] = False
                self.client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
                self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
                self.client.last_get_focus_trace["final_focus_reason"] = "success_false_top_level_kept_after_dump"
                self.client.last_get_focus_trace["dump_replace_reason"] = "dump_no_focused_node"
                return focus_node
            self.client.last_get_focus_trace["final_payload_source"] = payload_candidate_source
            self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            self.client.last_get_focus_trace["final_focus_reason"] = "accepted_meaningful_payload"
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
        self.client.last_get_focus_trace["empty_reason"] = empty_reason
        self.client.last_get_focus_trace["fallback_used"] = bool(allow_fallback_dump)
        self.client.last_get_focus_trace["fallback_reason"] = empty_reason
        self.client.last_get_focus_trace["elapsed_before_fallback_sec"] = time.monotonic() - started
        if not allow_fallback_dump:
            self.client.last_get_focus_trace["total_elapsed_sec"] = time.monotonic() - started
            self.client.last_get_focus_trace["final_payload_source"] = "none"
            self.client.last_get_focus_trace["final_focus_reason"] = "fast_path_skip_dump"
            return {}
        self.client._debug_print(
            f"[DEBUG][get_focus] fallback_enter serial={serial} req_id={req_id} "
            f"reason={empty_reason} elapsed_before_fallback={self.client.last_get_focus_trace['elapsed_before_fallback_sec']:.3f}s"
        )
        fallback_focus_node = self.client._run_get_focus_fallback_dump(
            dev=dev,
            serial=serial,
            req_id=req_id,
            started=started,
        )
        if fallback_focus_node:
            label = self.client.extract_visible_label_from_focus(fallback_focus_node)
            view_id = str(fallback_focus_node.get("viewIdResourceName", "") or "")
            bounds = self.client._normalize_bounds(fallback_focus_node)
            self.client.last_get_focus_trace["final_focus_reason"] = "fallback_dump_found"
            self.client._debug_print(
                f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=True "
                f"label='{label}' view_id='{view_id}' bounds='{bounds}' "
                f"dump_elapsed={self.client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
                f"total_elapsed={self.client.last_get_focus_trace['total_elapsed_sec']:.3f}s"
            )
            return fallback_focus_node

        self.client.last_get_focus_trace["fallback_found"] = False
        self.client.last_get_focus_trace["final_focus_reason"] = "fallback_dump_not_found"
        print(
            f"[WARN][get_focus] empty focus result serial={serial} req_id={req_id} "
            f"reason={empty_reason} fallback_found=False"
        )
        self.client._debug_print(
            f"[DEBUG][get_focus] fallback_result serial={serial} req_id={req_id} found=False "
            f"dump_elapsed={self.client.last_get_focus_trace['fallback_dump_elapsed_sec']:.3f}s "
            f"total_elapsed={self.client.last_get_focus_trace['total_elapsed_sec']:.3f}s"
        )
        return {}
