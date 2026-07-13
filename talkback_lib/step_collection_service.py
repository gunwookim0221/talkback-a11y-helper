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
from talkback_lib.verification_wait_policy import (
    VerificationCompletionDecision,
    VerificationObservation,
    VerificationWaitPolicy,
)


class StepCollectionService:
    _FAST_PATH_MINIMUM_WINDOW_SECONDS = 1.05
    _REQUIRED_STABILITY_OFFSETS_MS = (100, 300, 1000)

    def __init__(self, client: Any) -> None:
        self.client = client

    @staticmethod
    def _profiler_counter(name: str, amount: int = 1) -> None:
        try:
            from tb_runner.traversal_profiler import active_profiler

            profiler = active_profiler()
            if profiler is not None:
                profiler.increment_counter(name, amount)
        except Exception:
            pass

    def _correlated_action_focus_observation(self, *, move: bool) -> dict[str, Any] | None:
        """Return only a strongly correlated Helper post-action focus snapshot."""
        transaction = getattr(self.client, "_evidence_active_transaction", None)
        transaction_id = str(transaction.get("transaction_id") or "") if isinstance(transaction, dict) else ""
        request_id = str(getattr(self.client, "_evidence_active_request_id", "") or "").strip()
        if not transaction_id or not request_id:
            return None
        result = self.client.last_smart_nav_result if move else self.client.last_target_action_result
        if not isinstance(result, dict) or not bool(result.get("success")):
            return None
        result_request_id = str(result.get("reqId") or result.get("requestId") or "").strip()
        if result_request_id != request_id:
            return None
        coerce_events = getattr(self.client, "_coerce_evidence_events", None)
        if not callable(coerce_events):
            return None
        events: list[Any] = coerce_events(result.get("evidenceEvents"))
        runtime = getattr(self.client, "evidence_runtime", None)
        runtime_events = getattr(runtime, "events_for_transaction", None)
        if callable(runtime_events):
            events.extend(runtime_events(transaction_id))
        required = {"ACTION_API_RESULT", "FOCUS_COMMIT_CLAIMED", "POST_ACTION_OBSERVATION"}
        matched: dict[str, Any] = {}
        delayed: dict[int, dict[str, Any]] = {}
        for event in events:
            if isinstance(event, dict):
                event_type = str(event.get("eventType") or event.get("event_type") or "")
                correlation = event.get("correlation")
                if not isinstance(correlation, dict) or str(correlation.get("transaction_id") or "") != transaction_id:
                    continue
            else:
                event_type = str(getattr(event, "event_type", "") or "")
                if str(getattr(event, "transaction_id", "") or "") != transaction_id:
                    continue
                if str(getattr(event, "producer", "") or "") != "helper":
                    continue
            if event_type in required:
                matched[event_type] = event
            if event_type == "DELAYED_OBSERVATION":
                payload = event.get("payload") if isinstance(event, dict) else getattr(event, "payload", None)
                if not isinstance(payload, dict):
                    continue
                try:
                    offset_ms = int(payload.get("offsetMs"))
                except (TypeError, ValueError):
                    continue
                delayed_observation = payload.get("observation")
                if isinstance(delayed_observation, dict):
                    delayed[offset_ms] = delayed_observation
        if set(matched) != required:
            return None
        action_event = matched["ACTION_API_RESULT"]
        action_payload = action_event.get("payload") if isinstance(action_event, dict) else getattr(action_event, "payload", None)
        if not isinstance(action_payload, dict) or not bool(action_payload.get("success")):
            return None
        observation_event = matched["POST_ACTION_OBSERVATION"]
        observation_payload = (
            observation_event.get("payload")
            if isinstance(observation_event, dict)
            else getattr(observation_event, "payload", None)
        )
        observation = observation_payload.get("observation") if isinstance(observation_payload, dict) else None
        if not isinstance(observation, dict) or not self.client._is_meaningful_focus_node(observation):
            return None
        if not bool(observation.get("accessibilityFocused") or observation.get("accessibility_focused")):
            return None
        immediate_signature = self._physical_focus_signature(observation)
        if immediate_signature is None:
            return None
        for offset_ms in self._REQUIRED_STABILITY_OFFSETS_MS:
            delayed_observation = delayed.get(offset_ms)
            if (
                not isinstance(delayed_observation, dict)
                or not bool(
                    delayed_observation.get("accessibilityFocused")
                    or delayed_observation.get("accessibility_focused")
                )
                or self._physical_focus_signature(delayed_observation) != immediate_signature
            ):
                return None
        return observation

    def _physical_focus_signature(self, observation: dict[str, Any]) -> tuple[str, ...] | None:
        bounds = str(self.client._normalize_bounds(observation) or "").strip()
        class_name = str(observation.get("className") or observation.get("class") or "").strip()
        package_name = str(observation.get("packageName") or observation.get("package") or "").strip()
        window_id = str(observation.get("windowId") or observation.get("window_id") or "").strip()
        resource_id = str(
            observation.get("viewIdResourceName")
            or observation.get("resourceId")
            or observation.get("resource_id")
            or ""
        ).strip()
        if not bounds or not class_name or not package_name:
            return None
        return package_name, window_id, class_name, resource_id, bounds

    @staticmethod
    def _snapshot_actual_focus_fields(step: dict[str, Any]) -> None:
        step["actual_focus_visible"] = str(step.get("visible_label", "") or "").strip()
        step["actual_focus_speech"] = str(step.get("merged_announcement", "") or "").strip()
        step["actual_focus_resource_id"] = str(step.get("focus_view_id", "") or "").strip()
        step["actual_focus_bounds"] = str(step.get("focus_bounds", "") or "").strip()
        step["actual_focus_payload_source"] = str(step.get("focus_payload_source", "none") or "none")
        step["row_source"] = str(step.get("row_source", "") or "actual_focus")
        step["crop_source"] = str(step.get("crop_source", "") or "actual_focus")

    def _collect_focus_anchor_labels(self, safe_focus_node: dict[str, Any], visible_label: str) -> list[str]:
        anchors: list[str] = []
        for value in (
            visible_label,
            safe_focus_node.get("talkbackLabel", "") if isinstance(safe_focus_node, dict) else "",
            safe_focus_node.get("mergedLabel", "") if isinstance(safe_focus_node, dict) else "",
            safe_focus_node.get("contentDescription", "") if isinstance(safe_focus_node, dict) else "",
            safe_focus_node.get("text", "") if isinstance(safe_focus_node, dict) else "",
        ):
            text = str(value or "").strip()
            if text and text not in anchors:
                anchors.append(text)
        return anchors

    def _focus_affinity_score(self, speech: str, focus_anchor_labels: list[str]) -> int:
        normalized_speech = self.client.normalize_for_comparison(speech)
        if not normalized_speech:
            return 0
        best = 0
        for label in focus_anchor_labels:
            normalized_label = self.client.normalize_for_comparison(label)
            if not normalized_label:
                continue
            if normalized_speech == normalized_label:
                return 4
            if normalized_speech.endswith(normalized_label) or normalized_speech.startswith(normalized_label):
                best = max(best, 3)
            elif normalized_label in normalized_speech:
                best = max(best, 2)
        return best

    def _trim_context_to_focus_anchor(
        self,
        speech: str,
        focus_anchor_labels: list[str],
        icon_only_focus: bool,
    ) -> tuple[str, bool, str]:
        raw_speech = str(speech or "").strip()
        normalized_speech = self.client.normalize_for_comparison(raw_speech)
        if not raw_speech or not normalized_speech:
            return raw_speech, False, "empty_speech"
        if not focus_anchor_labels:
            return raw_speech, False, "missing_focus_anchor"

        best_anchor = ""
        best_anchor_norm = ""
        for anchor in focus_anchor_labels:
            normalized_anchor = self.client.normalize_for_comparison(anchor)
            if not normalized_anchor or normalized_anchor not in normalized_speech:
                continue
            if len(normalized_anchor) > len(best_anchor_norm):
                best_anchor = str(anchor).strip()
                best_anchor_norm = normalized_anchor
        if not best_anchor:
            return raw_speech, False, "focus_anchor_not_in_speech"
        if normalized_speech == best_anchor_norm:
            return raw_speech, False, "already_focus_aligned"

        lower_speech = raw_speech.lower()
        lower_anchor = best_anchor.lower()
        anchor_index = lower_speech.rfind(lower_anchor)
        if anchor_index < 0:
            return raw_speech, False, "focus_anchor_raw_not_found"
        prefix = raw_speech[:anchor_index].strip(" \t,.;:-")
        suffix = raw_speech[anchor_index + len(best_anchor) :].strip(" \t,.;:-")
        prefix_norm = self.client.normalize_for_comparison(prefix)
        suffix_norm = self.client.normalize_for_comparison(suffix)
        extra_token_count = len((prefix_norm + " " + suffix_norm).strip().split()) if (prefix_norm or suffix_norm) else 0
        if extra_token_count < 2 and not (icon_only_focus and (prefix_norm or suffix_norm)):
            return raw_speech, False, "context_tokens_too_short"
        return best_anchor, True, "focus_anchor_context_trim"

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
        set_evidence_step = getattr(self.client, "_evidence_set_step", None)
        begin_evidence_action = getattr(self.client, "_evidence_begin_step_action", None)
        if callable(set_evidence_step):
            try:
                set_evidence_step(step_index, phase="main_loop")
            except Exception:
                pass

        if move:
            move_started = time.monotonic()
            try:
                if callable(begin_evidence_action):
                    action_type = "SMART_NEXT" if str(direction).strip().lower() == "next" else "SMART_PREVIOUS"
                    begin_evidence_action(action_type, direction=direction)
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
        focus_wait = wait_seconds if focus_wait_seconds is None else focus_wait_seconds
        focus_node: dict[str, Any] = {}
        safe_focus_node: dict[str, Any] = {}
        focus_elapsed_sec = 0.0
        focus_collected = False

        def collect_focus_once() -> None:
            nonlocal focus_node, safe_focus_node, focus_elapsed_sec, focus_collected
            if focus_collected:
                return
            focus_started = time.monotonic()
            focus_node = self.client._collect_focus_node_with_compat(
                dev=dev,
                focus_wait=focus_wait,
                allow_get_focus_fallback_dump=allow_get_focus_fallback_dump,
                get_focus_mode=get_focus_mode,
            )
            focus_elapsed_sec = round(time.monotonic() - focus_started, 3)
            safe_focus_node = self.client._json_safe_value(focus_node) if isinstance(focus_node, dict) else {}
            focus_collected = True
            self._profiler_counter("focus_snapshot_read_count")

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
            idle_wait = float(announcement_idle_wait_seconds or 0.0)
            max_extra_wait = float(announcement_max_extra_wait_seconds or 0.0)
            adaptive_enabled = idle_wait > 0 and max_extra_wait > 0
            verification_policy = VerificationWaitPolicy(
                minimum_window_seconds=min(
                    max(float(ann_wait), 0.0),
                    self._FAST_PATH_MINIMUM_WINDOW_SECONDS,
                ),
                announcement_idle_seconds=idle_wait,
            )
            initial_announcement_wait = (
                min(float(ann_wait), verification_policy.minimum_window_seconds)
                if adaptive_enabled
                else float(ann_wait)
            )
            self._profiler_counter("verification_poll_attempts")
            partial_announcements = self.client.get_partial_announcements(
                dev=dev,
                wait_seconds=initial_announcement_wait,
                only_new=True,
            )
            if adaptive_enabled:
                collect_helper_events = getattr(self.client, "_evidence_collect_helper_logcat_events", None)
                active_request_id = str(getattr(self.client, "_evidence_active_request_id", "") or "").strip()
                if callable(collect_helper_events) and active_request_id:
                    try:
                        collect_helper_events(dev, req_id=active_request_id)
                    except Exception:
                        pass
            stable_announcements = list(partial_announcements)
            stable_merged = self.client._merge_announcements(stable_announcements)
            stable_norm = self.client.normalize_for_comparison(stable_merged)
            newest_changed = bool(stable_norm and stable_norm != baseline_norm)
            self.client._debug_print(
                f"[ANN][poll] candidate='{stable_merged}' changed={newest_changed}"
            )
            stability_extra_wait = 0.0
            if idle_wait > 0 and max_extra_wait > 0:
                self.client._debug_print(
                    f"[ANN][stability] mode='step' idle_wait={idle_wait:.2f} max_extra={max_extra_wait:.2f}"
                )
                stability_started = time.monotonic()
                stable_seen = {msg for msg in stable_announcements if isinstance(msg, str) and msg.strip()}
                stable_last_change_at = stability_started if newest_changed else ann_started
                reason = "max_extra_wait"
                conservative_deadline = ann_started + float(ann_wait) + max_extra_wait
                fallback_counted = False
                while True:
                    now = time.monotonic()
                    elapsed_total = now - ann_started
                    deadline_reached = now >= conservative_deadline
                    action_focus = self._correlated_action_focus_observation(move=move)
                    focus_confirmed = action_focus is not None
                    evidence_correlated = action_focus is not None
                    ambiguous_focus = not focus_confirmed
                    decision = verification_policy.evaluate(
                        VerificationObservation(
                            elapsed_seconds=elapsed_total,
                            focus_confirmed=focus_confirmed,
                            evidence_correlated=evidence_correlated,
                            announcement_idle_seconds=max(0.0, now - stable_last_change_at),
                            announcement_active=False,
                            ambiguous_focus=ambiguous_focus,
                            deadline_reached=deadline_reached,
                        )
                    )
                    if decision is VerificationCompletionDecision.COMPLETE_FAST_PATH:
                        reason = "adaptive_fast_path"
                        self._profiler_counter("verification_fast_path_hits")
                        self._profiler_counter("verification_focus_stable_count")
                        self._profiler_counter("verification_announcement_idle_count")
                        active_transaction = getattr(self.client, "_evidence_active_transaction", None)
                        if isinstance(active_transaction, dict) and str(active_transaction.get("phase", "")) == "recovery":
                            self._profiler_counter("recovery_verification_fast_path_hits")
                        break
                    if decision is VerificationCompletionDecision.CONSERVATIVE_FALLBACK and not fallback_counted:
                        self._profiler_counter("verification_fallback_count")
                        fallback_counted = True
                    if deadline_reached:
                        reason = "max_extra_wait"
                        self._profiler_counter("verification_timeout_count")
                        break
                    remaining = max(conservative_deadline - now, 0.0)
                    poll_wait_seconds = min(0.15, remaining)
                    if poll_wait_seconds <= 0:
                        reason = "max_extra_wait"
                        break
                    delta_announcements = self.client.get_partial_announcements(
                        dev=dev,
                        wait_seconds=poll_wait_seconds,
                        only_new=True,
                    )
                    self._profiler_counter("verification_poll_attempts")
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

        collect_focus_once()
        step["get_focus_elapsed_sec"] = focus_elapsed_sec
        step["t_after_get_focus"] = round(time.monotonic() - step_started, 3)
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
        focus_anchor_labels = self._collect_focus_anchor_labels(safe_focus_node, visible_label)
        focus_tb_label = str(
            safe_focus_node.get("talkbackLabel", "")
            or safe_focus_node.get("mergedLabel", "")
            or safe_focus_node.get("contentDescription", "")
            or safe_focus_node.get("text", "")
            or ""
        ).strip()
        focus_class_name = str(
            safe_focus_node.get("className", "")
            or safe_focus_node.get("class", "")
            or ""
        ).strip()
        focus_resource_id = str(step.get("focus_view_id", "") or "").strip()
        icon_only_focus = bool(
            not self.client.normalize_for_comparison(visible_label)
            and (
                bool(focus_tb_label)
                or "button" in focus_class_name.lower()
                or "imagebutton" in focus_class_name.lower()
                or "setting_button" in focus_resource_id.lower()
            )
        )

        snapshot_contaminated, snapshot_reason = self.client._is_contaminated_announcement_candidate(
            raw_snapshot_announcement,
            visible_label,
        )
        if not snapshot_contaminated and focus_anchor_labels and raw_snapshot_announcement:
            trimmed_snapshot, trimmed_snapshot_applied, _ = self._trim_context_to_focus_anchor(
                raw_snapshot_announcement,
                focus_anchor_labels,
                icon_only_focus=icon_only_focus,
            )
            if trimmed_snapshot_applied:
                raw_snapshot_announcement = trimmed_snapshot
                snapshot_contaminated = True
                snapshot_reason = "focus_anchor_context_trim_candidate"

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

        if step["merged_announcement"] and focus_anchor_labels:
            trimmed_by_focus, focus_trim_applied, focus_trim_reason = self._trim_context_to_focus_anchor(
                str(step.get("merged_announcement", "") or ""),
                focus_anchor_labels,
                icon_only_focus=icon_only_focus,
            )
            if focus_trim_applied:
                trim_before_value = str(step.get("merged_announcement", "") or "")
                step["merged_announcement"] = trimmed_by_focus
                step["normalized_announcement"] = self.client.normalize_for_comparison(trimmed_by_focus)
                step["trim_considered"] = True
                step["trim_applied"] = True
                step["trim_before"] = trim_before_value
                step["trim_after"] = trimmed_by_focus
                step["trim_reason"] = focus_trim_reason
                step["trim_reject_reason"] = ""
                step["announcement_stable_reason"] = focus_trim_reason
                step["announcement_stable_source"] = "trimmed_candidate"
            elif not step.get("trim_reason"):
                step["trim_considered"] = True
                step["trim_reject_reason"] = focus_trim_reason

        used_snapshot = (
            self.client.normalize_for_comparison(str(step.get("merged_announcement", "") or ""))
            == self.client.normalize_for_comparison(raw_snapshot_announcement)
        )
        step["used_snapshot"] = bool(used_snapshot)
        step["snapshot_contaminated"] = bool(snapshot_contaminated)
        focus_final_affinity = self._focus_affinity_score(str(step.get("merged_announcement", "") or ""), focus_anchor_labels)
        if step["used_snapshot"] and focus_anchor_labels and (
            focus_final_affinity <= 1 or (icon_only_focus and focus_final_affinity < 3)
        ):
            fallback_focus_announcement = str(focus_tb_label or "").strip()
            if fallback_focus_announcement:
                step["merged_announcement"] = fallback_focus_announcement
                step["normalized_announcement"] = self.client.normalize_for_comparison(fallback_focus_announcement)
                step["used_snapshot"] = False
                step["trim_considered"] = True
                step["trim_applied"] = True
                step["trim_before"] = str(step.get("trim_before", "") or raw_snapshot_announcement)
                step["trim_after"] = fallback_focus_announcement
                step["trim_reason"] = "focus_anchor_snapshot_reject"
                step["trim_reject_reason"] = ""
                step["announcement_stable_reason"] = "focus_anchor_snapshot_reject"
                step["announcement_stable_source"] = "focus_label_fallback"
                step["snapshot_reason"] = "focus_affinity_mismatch_snapshot_rejected"
                step["snapshot_contaminated"] = True
        if snapshot_contaminated and not str(step.get("snapshot_reason", "") or "").strip():
            step["snapshot_reason"] = snapshot_reason if not step["used_snapshot"] else "no_better_recent_poll_candidate_contaminated"
        else:
            if not str(step.get("snapshot_reason", "") or "").strip():
                step["snapshot_reason"] = "no_better_recent_poll_candidate" if step["used_snapshot"] else "not_used"
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
        self._snapshot_actual_focus_fields(step)
        complete_evidence_action = getattr(self.client, "_evidence_complete_step_action", None)
        if callable(complete_evidence_action):
            try:
                complete_evidence_action(step, safe_focus_node, dev=dev)
            except Exception:
                # Evidence is a side channel and must not influence the production row.
                pass

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
