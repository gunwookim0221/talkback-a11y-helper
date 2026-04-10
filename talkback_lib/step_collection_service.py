"""PR14-C: collect_focus_step orchestration 보조 service."""

from __future__ import annotations

import time
from typing import Any

from talkback_lib.step_row_builder import (
    build_noise_trim_anchor_labels,
    compute_prev_speech_flags,
    create_base_step_row,
    extract_smart_nav_row_fields,
)


class StepCollectionService:
    def __init__(self, client: Any) -> None:
        self.client = client

    def collect_focus_step(
        self,
        dev: Any = None,
        step_index: int = 0,
        move: bool = True,
        direction: str = "next",
        wait_seconds: float = 1.5,
        announcement_wait_seconds: float | None = None,
        announcement_idle_wait_seconds: float = 0.0,
        announcement_max_extra_wait_seconds: float = 0.0,
        focus_wait_seconds: float | None = None,
        allow_get_focus_fallback_dump: bool = True,
        allow_step_dump: bool = True,
        get_focus_mode: str = "normal",
    ) -> dict[str, Any]:
        step_started = time.monotonic()
        baseline_announcement = str(self.client.last_merged_announcement or "").strip()
        baseline_announcement_ts = round(step_started, 3)
        baseline_norm = self.client.normalize_for_comparison(baseline_announcement)
        self.client._debug_print(
            f"[ANN][baseline] text='{baseline_announcement}' ts={baseline_announcement_ts:.3f}"
        )
        step: dict[str, Any] = create_base_step_row(step_index=step_index)

        if move:
            move_started = time.monotonic()
            try:
                if str(direction).strip().lower() == "next":
                    step["move_result"] = self.client.move_focus_smart(dev=dev, direction=direction)
                else:
                    step["move_result"] = self.client.move_focus(dev=dev, direction=direction)
            except Exception as exc:
                step["move_result"] = f"error: {exc}"
            step["move_elapsed_sec"] = round(time.monotonic() - move_started, 3)
        else:
            step["move_elapsed_sec"] = 0.0
        smart_nav_result = self.client.last_smart_nav_result if isinstance(self.client.last_smart_nav_result, dict) else {}
        step.update(
            extract_smart_nav_row_fields(
                smart_nav_result=smart_nav_result,
                last_smart_nav_terminal=self.client.last_smart_nav_terminal,
            )
        )
        smart_success = bool(step.get("smart_nav_success", False))
        if smart_success and move and str(direction).strip().lower() == "next":
            step["post_move_verdict_source"] = "smart_nav_result"
        step["t_after_move"] = round(time.monotonic() - step_started, 3)

        ann_wait = wait_seconds if announcement_wait_seconds is None else announcement_wait_seconds

        ann_started = time.monotonic()
        selected_merged_announcement = ""
        raw_snapshot_announcement = ""
        trim_considered = False
        trim_applied = False
        trim_before = ""
        trim_after = ""
        trim_reason = ""
        trim_reject_reason = ""
        selected_reason = "result_row_snapshot"
        selected_source = "result_row_snapshot"
        try:
            partial_announcements = self.client.get_partial_announcements(
                dev=dev,
                wait_seconds=ann_wait,
                only_new=True,
            )
            stable_announcements = list(partial_announcements)
            stable_merged = self.client._merge_announcements(stable_announcements)
            stable_norm = self.client.normalize_for_comparison(stable_merged)
            newest_changed = bool(stable_norm and stable_norm != baseline_norm)
            self.client._debug_print(
                f"[ANN][poll] candidate='{stable_merged}' changed={newest_changed}"
            )
            stability_extra_wait = 0.0
            idle_wait = float(announcement_idle_wait_seconds or 0.0)
            max_extra_wait = float(announcement_max_extra_wait_seconds or 0.0)
            if idle_wait > 0 and max_extra_wait > 0:
                self.client._debug_print(
                    f"[ANN][stability] mode='step' idle_wait={idle_wait:.2f} max_extra={max_extra_wait:.2f}"
                )
                stability_started = time.monotonic()
                stable_seen = {msg for msg in stable_announcements if isinstance(msg, str) and msg.strip()}
                stable_last_change_at = stability_started if newest_changed else 0.0
                reason = "max_extra_wait"
                while True:
                    elapsed_extra = time.monotonic() - stability_started
                    if elapsed_extra >= max_extra_wait:
                        reason = "max_extra_wait"
                        break
                    remaining = max(max_extra_wait - elapsed_extra, 0.0)
                    poll_wait_seconds = min(0.15, remaining)
                    if poll_wait_seconds <= 0:
                        reason = "max_extra_wait"
                        break
                    delta_announcements = self.client.get_partial_announcements(
                        dev=dev,
                        wait_seconds=poll_wait_seconds,
                        only_new=True,
                    )
                    changed = False
                    if isinstance(delta_announcements, list):
                        for message in delta_announcements:
                            if not isinstance(message, str):
                                continue
                            normalized = message.strip()
                            if not normalized or normalized in stable_seen:
                                continue
                            stable_seen.add(normalized)
                            stable_announcements.append(message)
                            changed = True
                    now = time.monotonic()
                    if changed:
                        stable_merged = self.client._merge_announcements(stable_announcements)
                        stable_norm = self.client.normalize_for_comparison(stable_merged)
                        newest_changed = bool(stable_norm and stable_norm != baseline_norm)
                        if newest_changed:
                            stable_last_change_at = now
                        self.client._debug_print(
                            f"[ANN][poll] candidate='{stable_merged}' changed={newest_changed}"
                        )
                    if newest_changed and stable_last_change_at > 0 and (now - stable_last_change_at >= idle_wait):
                        reason = "idle_stable"
                        break
                stability_extra_wait = round(time.monotonic() - stability_started, 3)
                partial_announcements = stable_announcements
                self.client.last_announcements = list(stable_announcements)
                self.client.last_merged_announcement = self.client._merge_announcements(stable_announcements)
                self.client._debug_print(
                    f"[ANN][stable] selected='{self.client.last_merged_announcement}' reason='{reason}' elapsed={stability_extra_wait:.2f}"
                )
            raw_snapshot_announcement = self.client._merge_announcements(partial_announcements)
            selected_merged_announcement = raw_snapshot_announcement
            selected_norm = self.client.normalize_for_comparison(selected_merged_announcement)
            trim_considered = True
            if (
                baseline_announcement
                and baseline_norm
                and selected_norm
                and selected_norm != baseline_norm
                and len(baseline_norm) >= 8
                and selected_norm.startswith(baseline_norm)
            ):
                trimmed_merged = selected_merged_announcement[len(baseline_announcement):].lstrip(" \t,.;:-")
                trimmed_norm = self.client.normalize_for_comparison(trimmed_merged)
                if trimmed_norm:
                    trim_applied = True
                    trim_before = selected_merged_announcement
                    selected_merged_announcement = trimmed_merged
                    trim_after = selected_merged_announcement
                    trim_reason = "baseline_prefix_trim"
                    trim_reject_reason = ""
                    selected_reason = "baseline_prefix_trim"
                    selected_source = "trimmed_candidate"
                else:
                    trim_reject_reason = "baseline_trimmed_empty"
            elif baseline_announcement:
                trim_reject_reason = "baseline_rule_not_matched"
            else:
                trim_reject_reason = "baseline_empty_visible_anchor_pending"
            self.client._debug_print(
                f"[ANN][trim] considered={str(trim_considered).lower()} applied={str(trim_applied).lower()} "
                f"before='{trim_before or selected_merged_announcement}' after='{trim_after or selected_merged_announcement}' "
                f"reject_reason='{trim_reject_reason}' reason='{trim_reason or 'baseline_trim_not_applied'}'"
            )
            used_snapshot = self.client.normalize_for_comparison(selected_merged_announcement) == self.client.normalize_for_comparison(raw_snapshot_announcement)
            self.client._debug_print(
                f"[ANN][select] previous='{baseline_announcement}' current='{raw_snapshot_announcement}' "
                f"final='{selected_merged_announcement}' used_snapshot={str(used_snapshot).lower()} "
                f"used_trimmed_candidate={str(not used_snapshot).lower()}"
            )
            step["partial_announcements"] = self.client._json_safe_value(partial_announcements)
            step["announcement_extra_wait_sec"] = stability_extra_wait
        except Exception:
            partial_announcements = []
            selected_merged_announcement = ""
            raw_snapshot_announcement = ""
        step["announcement_elapsed_sec"] = round(time.monotonic() - ann_started, 3)
        step["announcement_count"] = len(partial_announcements)
        step["announcement_window_sec"] = round(float(ann_wait) + float(step.get("announcement_extra_wait_sec", 0.0) or 0.0), 3)
        step["t_after_ann"] = round(time.monotonic() - step_started, 3)

        merged_announcement = str(selected_merged_announcement or self.client._merge_announcements(partial_announcements))
        step["merged_announcement"] = merged_announcement
        step["normalized_announcement"] = self.client.normalize_for_comparison(merged_announcement)
        step["trim_considered"] = bool(trim_considered)
        step["trim_applied"] = bool(trim_applied)
        step["trim_before"] = trim_before or raw_snapshot_announcement
        step["trim_after"] = trim_after or merged_announcement
        step["trim_reason"] = trim_reason
        step["trim_reject_reason"] = trim_reject_reason
        step["announcement_stable_reason"] = selected_reason if merged_announcement else "empty"
        step["announcement_stable_source"] = selected_source if merged_announcement else "none"

        saved_last_announcements = list(self.client.last_announcements)
        saved_last_merged = self.client.last_merged_announcement

        focus_wait = wait_seconds if focus_wait_seconds is None else focus_wait_seconds
        focus_started = time.monotonic()
        focus_node = self.client._collect_focus_node_with_compat(
            dev=dev,
            focus_wait=focus_wait,
            allow_get_focus_fallback_dump=allow_get_focus_fallback_dump,
            get_focus_mode=get_focus_mode,
        )
        step["get_focus_elapsed_sec"] = round(time.monotonic() - focus_started, 3)
        step["t_after_get_focus"] = round(time.monotonic() - step_started, 3)
        safe_focus_node = self.client._json_safe_value(focus_node) if isinstance(focus_node, dict) else {}
        self.client._populate_focus_fields_from_node(step=step, safe_focus_node=safe_focus_node)

        visible_label = self.client.extract_visible_label_from_focus(safe_focus_node)
        if not visible_label and isinstance(safe_focus_node, dict):
            for fallback_key in (
                "contentDescription",
                "content_desc",
                "content_description",
                "accessibilityLabel",
                "label",
                "talkback",
            ):
                fallback_value = safe_focus_node.get(fallback_key)
                if isinstance(fallback_value, str) and fallback_value.strip():
                    visible_label = fallback_value.strip()
                    break
        step["visible_label"] = visible_label
        step["normalized_visible_label"] = self.client.normalize_for_comparison(visible_label)

        snapshot_contaminated, snapshot_reason = self.client._is_contaminated_announcement_candidate(
            raw_snapshot_announcement,
            visible_label,
        )
        if step["merged_announcement"] and visible_label:
            trimmed_by_visible, visible_trim_applied, visible_trim_reason = self.client._try_trim_prefix_by_visible_anchor(
                step["merged_announcement"],
                visible_label,
            )
            if visible_trim_applied:
                trim_before_value = str(step.get("merged_announcement", "") or "")
                step["merged_announcement"] = trimmed_by_visible
                step["normalized_announcement"] = self.client.normalize_for_comparison(trimmed_by_visible)
                step["trim_considered"] = True
                step["trim_applied"] = True
                step["trim_before"] = trim_before_value
                step["trim_after"] = trimmed_by_visible
                step["trim_reason"] = "visible_anchor_prefix_trim"
                step["trim_reject_reason"] = ""
                step["announcement_stable_reason"] = "visible_anchor_prefix_trim"
                step["announcement_stable_source"] = "trimmed_candidate"
            elif not step.get("trim_reason"):
                step["trim_considered"] = True
                step["trim_reject_reason"] = visible_trim_reason

        used_snapshot = (
            self.client.normalize_for_comparison(str(step.get("merged_announcement", "") or ""))
            == self.client.normalize_for_comparison(raw_snapshot_announcement)
        )
        step["used_snapshot"] = bool(used_snapshot)
        step["snapshot_contaminated"] = bool(snapshot_contaminated)
        if snapshot_contaminated:
            step["snapshot_reason"] = snapshot_reason if not used_snapshot else "no_better_recent_poll_candidate_contaminated"
        else:
            step["snapshot_reason"] = "no_better_recent_poll_candidate" if used_snapshot else "not_used"
        self.client._debug_print(
            f"[ANN][trim] considered={str(step['trim_considered']).lower()} applied={str(step['trim_applied']).lower()} "
            f"before='{step['trim_before']}' after='{step['trim_after']}' reject_reason='{step['trim_reject_reason']}' "
            f"reason='{step['trim_reason'] or 'not_applied'}' strategy='visible_anchor_prefix_trim'"
        )
        self.client._debug_print(
            f"[ANN][select] used_snapshot={str(step['used_snapshot']).lower()} "
            f"used_trimmed_candidate={str(step['announcement_stable_source'] == 'trimmed_candidate').lower()} "
            f"snapshot_contaminated={str(step['snapshot_contaminated']).lower()} snapshot_reason='{step['snapshot_reason']}'"
        )

        trace = self.client.last_get_focus_trace if isinstance(self.client.last_get_focus_trace, dict) else {}
        self.client._resolve_step_dump_tree(
            step=step,
            trace=trace,
            safe_focus_node=safe_focus_node,
            allow_step_dump=allow_step_dump,
            dev=dev,
        )
        self.client._populate_get_focus_trace_fields(step=step, trace=trace)
        step["t_step_start"] = 0.0

        merged_announcement = str(step.get("merged_announcement", "") or "").strip()
        if not merged_announcement:
            top_level_payload_sufficient = bool(step.get("get_focus_top_level_payload_sufficient", False))
            final_payload_source = str(step.get("get_focus_final_payload_source", "") or "").strip().lower()
            if top_level_payload_sufficient and final_payload_source == "top_level":
                fallback_announcement = ""
                fallback_source = ""

                if isinstance(partial_announcements, list):
                    fallback_announcement = self.client._merge_announcements(partial_announcements).strip()
                    if fallback_announcement:
                        fallback_source = "partial_announcements"

                if not fallback_announcement:
                    fallback_announcement = str(saved_last_merged or "").strip()
                    if fallback_announcement:
                        fallback_source = "last_merged_announcement"

                if not fallback_announcement and isinstance(safe_focus_node, dict):
                    for source_key in ("talkbackLabel", "mergedLabel", "contentDescription", "text"):
                        candidate = str(safe_focus_node.get(source_key, "") or "").strip()
                        if candidate:
                            fallback_announcement = candidate
                            fallback_source = source_key
                            break

                if fallback_announcement:
                    step["merged_announcement"] = fallback_announcement
                    step["normalized_announcement"] = self.client.normalize_for_comparison(fallback_announcement)
                    step["used_snapshot"] = (
                        self.client.normalize_for_comparison(fallback_announcement)
                        == self.client.normalize_for_comparison(raw_snapshot_announcement)
                    )
                    if not step["used_snapshot"] and step.get("snapshot_reason") == "no_better_recent_poll_candidate":
                        step["snapshot_reason"] = "not_used"
                if fallback_source in {"talkbackLabel", "mergedLabel"}:
                    print(f"[ANN][fallback] source='{fallback_source}'")

        noise_trimmed, noise_trim_applied, noise_trim_reason = self.client._try_trim_battery_suffix_noise(
            step.get("merged_announcement", ""),
            build_noise_trim_anchor_labels(step=step, safe_focus_node=safe_focus_node),
        )
        if noise_trim_applied:
            before_value = str(step.get("merged_announcement", "") or "")
            step["merged_announcement"] = noise_trimmed
            step["normalized_announcement"] = self.client.normalize_for_comparison(noise_trimmed)
            step["trim_considered"] = True
            step["trim_applied"] = True
            step["trim_before"] = before_value
            step["trim_after"] = noise_trimmed
            step["trim_reason"] = noise_trim_reason
            step["trim_reject_reason"] = ""
            print(
                f"[ANN][noise_trim] reason='{noise_trim_reason}' before='{before_value}' after='{noise_trimmed}'"
            )

        step["last_announcements"] = self.client._json_safe_value(saved_last_announcements)
        step["last_merged_announcement"] = saved_last_merged
        prev_merged = str(self.client._prev_step_merged_announcement or "").strip()
        curr_merged = str(step.get("merged_announcement", "") or "").strip()
        prev_norm = self.client.normalize_for_comparison(prev_merged)
        curr_norm = self.client.normalize_for_comparison(curr_merged)
        (
            step["prev_speech_same"],
            step["prev_speech_similar"],
        ) = compute_prev_speech_flags(
            prev_norm=prev_norm,
            curr_norm=curr_norm,
        )
        self.client._prev_step_merged_announcement = curr_merged

        self.client._debug_print(
            f"[DEBUG][collect_focus_step] step={step_index} move={step['move_elapsed_sec']:.3f}s "
            f"ann={step['announcement_elapsed_sec']:.3f}s get_focus={step['get_focus_elapsed_sec']:.3f}s "
            f"get_focus_fallback_dump={step['get_focus_fallback_dump_elapsed_sec']:.3f}s "
            f"step_dump={step['step_dump_tree_elapsed_sec']:.3f}s "
            f"step_dump_used={step['step_dump_tree_used']} "
            f"step_dump_reason='{step['step_dump_tree_reason']}' "
            f"reason='{step['get_focus_empty_reason']}'"
        )
        req_id = ""
        if isinstance(smart_nav_result, dict):
            req_id = str(smart_nav_result.get("reqId", "") or "").strip()
        focus_label_for_trace = str(step.get("visible_label", "") or step.get("focus_content_description", "") or "").replace("\n", " ").strip()
        announcement_for_trace = str(step.get("merged_announcement", "") or "").replace("\n", " ").strip()
        print(
            f"[STEP][smart_next_trace] req_id='{req_id}' "
            f"last_smart_nav_result='{step.get('last_smart_nav_result', '')}' "
            f"last_smart_nav_detail='{step.get('last_smart_nav_detail', '')}' "
            f"smart_nav_requested_view_id='{step.get('smart_nav_requested_view_id', '')}' "
            f"smart_nav_resolved_view_id='{step.get('smart_nav_resolved_view_id', '')}' "
            f"smart_nav_actual_view_id='{step.get('smart_nav_actual_view_id', '')}' "
            f"post_move_verdict_source='{step.get('post_move_verdict_source', '')}' "
            f"focus_view_id='{step.get('focus_view_id', '')}' "
            f"focus_label='{focus_label_for_trace[:96]}' "
            f"announcement='{announcement_for_trace[:96]}' "
            f"focus_payload_req_id='{step.get('get_focus_req_id', '')}' "
            f"focus_payload_source='{step.get('focus_payload_source', '')}' "
            f"focus_payload_final_source='{step.get('get_focus_final_payload_source', '')}' "
            f"t_move_done={step.get('t_after_move', 0)} "
            f"t_ann_done={step.get('t_after_ann', 0)} "
            f"t_focus_done={step.get('t_after_get_focus', 0)}"
        )
        return step
