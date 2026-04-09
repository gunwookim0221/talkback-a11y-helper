import re
from typing import Any

from tb_runner.utils import normalize_semantic_text, parse_bounds_str


def _bounds_changed_significantly(prev_bounds: str, curr_bounds: str) -> bool:
    prev = parse_bounds_str(prev_bounds)
    curr = parse_bounds_str(curr_bounds)
    if not prev or not curr:
        return False
    pl, pt, pr, pb = prev
    cl, ct, cr, cb = curr
    center_dx = abs(((pl + pr) / 2.0) - ((cl + cr) / 2.0))
    center_dy = abs(((pt + pb) / 2.0) - ((ct + cb) / 2.0))
    return center_dx > 80 or center_dy > 80


def detect_step_mismatch(
    row: dict[str, Any],
    previous_step: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    mismatch_reasons: list[str] = []
    low_confidence_reasons: list[str] = []
    visible = str(row.get("normalized_visible_label", "") or "").strip()
    speech = str(row.get("normalized_announcement", "") or "").strip()
    focus_source = str(row.get("focus_payload_source", "") or "").strip().lower()
    response_success = bool(row.get("get_focus_response_success", False))
    top_level_suspicious = bool(row.get("get_focus_top_level_success_false", False))
    dump_skipped = bool(row.get("get_focus_success_false_top_level_dump_skipped", False))
    dump_skip_reason = str(row.get("get_focus_dump_skip_reason", "") or "").strip().lower()
    strong_top_level_policy_skip = dump_skipped and dump_skip_reason == "strong_top_level_payload"
    top_level_payload_sufficient = bool(row.get("get_focus_top_level_payload_sufficient", False))
    focus_view_id = str(row.get("focus_view_id", "") or "").strip()
    focus_bounds = str(row.get("focus_bounds", "") or "").strip()
    focus_class_name = str(row.get("focus_node", {}).get("className", "") or "").strip() if isinstance(row.get("focus_node"), dict) else ""
    normalized_visible_label = str(row.get("normalized_visible_label", "") or "").strip()
    context_type = str(row.get("context_type", "") or "").strip().lower()
    post_move_verdict_source = str(row.get("post_move_verdict_source", "") or "").strip().lower()

    top_level_usable = strong_top_level_policy_skip or top_level_payload_sufficient
    if (top_level_suspicious or (focus_source == "top_level" and not response_success)) and not top_level_usable:
        low_confidence_reasons.append("get_focus_top_level_success_false")

    visible_terms = [token for token in visible.split(" ") if token]
    speech_terms = [token for token in speech.split(" ") if token]
    speech_visible_compatible = (
        not visible
        or not speech
        or visible == speech
        or visible in speech
        or speech in visible
        or (
            bool(visible_terms)
            and bool(speech_terms)
            and (speech_terms[0] == visible_terms[0] or visible_terms[0] in speech_terms[:2])
        )
    )
    if visible and speech and not speech_visible_compatible and not post_move_verdict_source.startswith("smart_nav_result"):
        mismatch_reasons.append("speech_visible_diverged")

    if context_type == "overlay" and not focus_view_id and focus_bounds:
        low_confidence_reasons.append("overlay_bounds_only_focus")

    prev = previous_step or {}
    prev_speech = str(prev.get("normalized_announcement", "") or "").strip()
    prev_bounds = str(prev.get("focus_bounds", "") or "").strip()
    if prev_speech and speech and prev_speech == speech and _bounds_changed_significantly(prev_bounds, focus_bounds):
        mismatch_reasons.append("speech_bounds_diverged")

    if (
        context_type == "main"
        and str(row.get("overlay_recovery_status", "") or "").strip().lower().startswith("realign")
        and not focus_view_id
        and focus_bounds
        and visible
        and speech
        and not speech_visible_compatible
    ):
        mismatch_reasons.append("overlay_realign_bounds_only_then_label_mismatch")

    if bool(row.get("crop_focus_confidence_low", False)) and not strong_top_level_policy_skip:
        low_confidence_reasons.append("crop_low_confidence")

    fallback_found = bool(row.get("get_focus_fallback_found", False))
    success_false_top_level_dump_found = bool(row.get("get_focus_success_false_top_level_dump_found", False))
    if (
        focus_source == "top_level"
        and not fallback_found
        and not success_false_top_level_dump_found
        and not top_level_usable
    ):
        low_confidence_reasons.append("top_level_without_fallback_dump")
    if not focus_view_id and focus_bounds and not (top_level_usable and (focus_class_name or normalized_visible_label)):
        low_confidence_reasons.append("bounds_dependent_focus")

    return mismatch_reasons, low_confidence_reasons


_GLOBAL_NAV_HINT_TOKENS = ("home", "devices", "life", "routines", "menu", "favorites", "automations", "services")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_screen_size(row: dict[str, Any]) -> tuple[int, int]:
    width_candidates = ("screen_width", "display_width", "window_width")
    height_candidates = ("screen_height", "display_height", "window_height")
    width = next((int(row.get(key, 0) or 0) for key in width_candidates if isinstance(row.get(key), (int, float))), 0)
    height = next((int(row.get(key, 0) or 0) for key in height_candidates if isinstance(row.get(key), (int, float))), 0)
    return width, height


def _match_region_hint(row: dict[str, Any], region_hint: str) -> bool:
    bounds = parse_bounds_str(str(row.get("focus_bounds", "") or ""))
    if not bounds:
        return False
    width, height = _extract_screen_size(row)
    if width <= 0 or height <= 0:
        return False
    left, top, _, _ = bounds
    if region_hint == "bottom_tabs":
        return top >= int(height * 0.72)
    if region_hint == "left_rail":
        return left <= int(width * 0.28)
    return False


def is_global_nav_row(
    row: dict[str, Any],
    scenario_cfg: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    cfg = scenario_cfg or {}
    global_nav_cfg = cfg.get("global_nav", {})
    if not isinstance(global_nav_cfg, dict):
        global_nav_cfg = {}

    smart_resolved_id = _normalize_text(row.get("smart_nav_resolved_view_id", ""))
    smart_actual_id = _normalize_text(row.get("smart_nav_actual_view_id", ""))
    smart_requested_id = _normalize_text(row.get("smart_nav_requested_view_id", ""))
    focus_id = _normalize_text(row.get("focus_view_id", "") or row.get("resource_id", ""))
    focus_label = _normalize_text(row.get("visible_label", ""))
    normalized_label = _normalize_text(row.get("normalized_visible_label", ""))
    merged_announcement = _normalize_text(row.get("merged_announcement", "") or row.get("normalized_announcement", ""))
    context_text = " ".join([focus_label, normalized_label, merged_announcement]).strip()
    selected_state = bool(row.get("focus_selected", False) or row.get("selected", False))

    score = 0
    reasons: list[str] = []
    strong_signal = False

    resource_ids = [str(item).strip().lower() for item in global_nav_cfg.get("resource_ids", []) if isinstance(item, str)]
    smart_match = False
    if resource_ids:
        smart_match = any(
            candidate and any(resource == candidate or resource in candidate for resource in resource_ids)
            for candidate in (smart_resolved_id, smart_actual_id, smart_requested_id)
        )
    if smart_match:
        score += 4
        strong_signal = True
        reasons.append("smart_nav_resource_id")
    if focus_id and resource_ids and any(resource in focus_id for resource in resource_ids):
        score += 3
        strong_signal = True
        reasons.append("resource_id")
    elif focus_id and any(token in focus_id for token in _GLOBAL_NAV_HINT_TOKENS):
        score += 1
        reasons.append("resource_hint")

    labels = [str(item).strip().lower() for item in global_nav_cfg.get("labels", []) if isinstance(item, str)]
    if context_text and labels and any(label and label in context_text for label in labels):
        score += 2
        strong_signal = True
        reasons.append("label")
    elif context_text and any(token in context_text for token in _GLOBAL_NAV_HINT_TOKENS):
        score += 1
        reasons.append("label_hint")

    selected_pattern = str(global_nav_cfg.get("selected_pattern", "") or "").strip()
    if selected_pattern and context_text:
        try:
            if re.search(selected_pattern, context_text, flags=re.IGNORECASE):
                score += 2
                strong_signal = True
                reasons.append("selected_pattern")
        except re.error:
            pass

    if selected_state:
        score += 1
        reasons.append("selected_state")

    region_hint = str(global_nav_cfg.get("region_hint", "auto") or "auto").strip().lower()
    if region_hint in {"bottom_tabs", "left_rail"} and _match_region_hint(row, region_hint):
        score += 1
        reasons.append("region_hint")

    if strong_signal and score >= 3:
        return True, ",".join(reasons)
    return False, ",".join(reasons) if reasons else "none"


class StopEvaluator:
    _MOVE_FAILURE_RESULTS = {"failed"}
    _MOVE_TERMINAL_RESULTS = {"terminal", "end", "no_next", "no_focus", "cannot_move"}
    _REPEAT_STOP_REASONS = {"repeat_no_progress", "bounded_two_card_loop", "repeat_semantic_stall"}
    _DEFAULT_MIN_STEPS_BEFORE_REPEAT_STOP = 3

    def _signature(self, row: dict[str, Any]) -> tuple[str, str, str, str, str]:
        normalized_visible = str(row.get("normalized_visible_label", "") or "").strip()
        normalized_speech = str(row.get("normalized_announcement", "") or "").strip()
        focus_bounds = str(row.get("focus_bounds", "") or "").strip()
        resource_id = str(row.get("focus_view_id", "") or row.get("resource_id", "") or "").strip()
        view_id = str(row.get("focus_node", {}).get("viewIdResourceName", "") or "").strip() if isinstance(row.get("focus_node"), dict) else ""
        return normalized_visible, normalized_speech, focus_bounds, resource_id, view_id

    def _semantic_signature(self, row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            normalize_semantic_text(row.get("normalized_visible_label", "") or row.get("visible_label", "")),
            normalize_semantic_text(row.get("normalized_announcement", "") or row.get("merged_announcement", "")),
            normalize_semantic_text(row.get("focus_view_id", "") or row.get("resource_id", "")),
        )

    def _is_same_like(self, previous_signature: tuple[str, ...], current_signature: tuple[str, ...]) -> bool:
        if not any(current_signature):
            return False
        if previous_signature == current_signature:
            return True
        shared = sum(
            1
            for prev_value, curr_value in zip(previous_signature, current_signature)
            if prev_value and curr_value and prev_value == curr_value
        )
        return shared >= 3

    def evaluate_repeat(
        self,
        *,
        current_fingerprint: tuple[str, str, str],
        prev_fingerprint: tuple[str, str, str],
        current_signature: tuple[str, ...],
        previous_signature: tuple[str, ...],
        current_semantic_signature: tuple[str, ...],
        previous_semantic_signature: tuple[str, ...],
        recent_duplicate: bool,
        recent_semantic_duplicate: bool,
        recent_semantic_duplicate_distance: int,
        recent_semantic_unique_count: int,
    ) -> dict[str, Any]:
        strict_duplicate = False
        if previous_signature == current_signature and any(current_signature):
            strict_duplicate = True
        elif all(current_fingerprint) and current_fingerprint == prev_fingerprint:
            strict_duplicate = True

        semantic_duplicate = (
            bool(any(current_semantic_signature))
            and current_semantic_signature == previous_semantic_signature
            and not strict_duplicate
        )
        same_like = strict_duplicate or semantic_duplicate or self._is_same_like(previous_signature, current_signature)
        if not semantic_duplicate and bool(any(current_semantic_signature)) and current_semantic_signature == previous_semantic_signature:
            semantic_duplicate = True
            same_like = True

        bounded_two_card_loop = (
            recent_semantic_duplicate
            and 2 <= recent_semantic_duplicate_distance <= 4
            and 0 < recent_semantic_unique_count <= 2
        )
        if strict_duplicate and semantic_duplicate:
            repeat_class = "mixed_repeat"
        elif strict_duplicate:
            repeat_class = "strict_duplicate"
        elif semantic_duplicate:
            repeat_class = "semantic_duplicate"
        else:
            repeat_class = "none"
        harmful_loop = (
            strict_duplicate
            or bounded_two_card_loop
            or (semantic_duplicate and recent_semantic_duplicate and recent_semantic_unique_count <= 2)
            or (recent_duplicate and recent_semantic_duplicate and recent_semantic_unique_count <= 1)
        )
        benign_repeat = (
            not harmful_loop
            and semantic_duplicate
            and (recent_semantic_unique_count >= 3 or recent_semantic_duplicate_distance >= 5)
        )
        loop_classification = "harmful_loop" if harmful_loop else "benign_repeat" if benign_repeat else "none"
        return {
            "same_like": same_like,
            "strict_duplicate": strict_duplicate,
            "semantic_duplicate": semantic_duplicate,
            "repeat_class": repeat_class,
            "loop_classification": loop_classification,
            "bounded_two_card_loop": bounded_two_card_loop,
        }

    def evaluate_no_progress(
        self,
        *,
        same_like: bool,
        strict_duplicate: bool,
        semantic_duplicate: bool,
        bounded_two_card_loop: bool,
        move_failed: bool,
        move_terminal: bool,
        smart_nav_result: str,
        fail_count: int,
        same_count: int,
        recent_semantic_unique_count: int,
    ) -> dict[str, Any]:
        hard_no_progress = (
            (strict_duplicate and move_failed)
            or (same_like and move_terminal)
            or (strict_duplicate and fail_count >= 2)
        )
        soft_no_progress = (
            bounded_two_card_loop
            or (
                semantic_duplicate
                and recent_semantic_unique_count <= 2
                and (move_failed or smart_nav_result in {"failed", "unchanged"} or same_count >= 4)
            )
        )
        no_progress = hard_no_progress or soft_no_progress
        no_progress_class = "hard_no_progress" if hard_no_progress else "soft_no_progress" if soft_no_progress else "none"
        return {
            "no_progress": no_progress,
            "hard_no_progress": hard_no_progress,
            "soft_no_progress": soft_no_progress,
            "no_progress_class": no_progress_class,
        }

    def evaluate_overlay_context(self, row: dict[str, Any], repeat_class: str) -> dict[str, Any]:
        overlay_recovery_status = str(row.get("overlay_recovery_status", "") or "").strip().lower()
        after_realign = overlay_recovery_status.startswith("after_realign") or overlay_recovery_status.startswith("realign")
        realign_grace_active = after_realign and repeat_class in {"semantic_duplicate", "mixed_repeat"}
        return {
            "overlay_recovery_status": overlay_recovery_status,
            "after_realign": after_realign,
            "realign_grace_active": realign_grace_active,
        }

    def finalize_decision(
        self,
        *,
        stop: bool,
        reason: str,
        row: dict[str, Any],
        effective_stop_policy: dict[str, Any],
        repeat_class: str,
        strict_duplicate: bool,
        hard_no_progress: bool,
        overlay_ctx: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any]]:
        min_steps_before_repeat_stop = int(
            effective_stop_policy.get("min_steps_before_repeat_stop", self._DEFAULT_MIN_STEPS_BEFORE_REPEAT_STOP) or 0
        )
        step_index = int(row.get("step_index", 0) or 0)
        min_step_gate_blocked = (
            stop
            and reason in self._REPEAT_STOP_REASONS
            and step_index > 0
            and step_index < min_steps_before_repeat_stop
        )
        if min_step_gate_blocked:
            stop = False
            reason = ""

        realign_grace_suppressed = (
            stop
            and reason in self._REPEAT_STOP_REASONS
            and bool(overlay_ctx.get("realign_grace_active", False))
            and not (strict_duplicate and hard_no_progress)
        )
        if realign_grace_suppressed:
            stop = False
            reason = ""
        return stop, reason, {
            "min_steps_before_repeat_stop": min_steps_before_repeat_stop,
            "min_step_gate_blocked": min_step_gate_blocked,
            "realign_grace_suppressed": realign_grace_suppressed,
        }

    def evaluate_stop(
        self,
        *,
        row: dict[str, Any],
        previous_row: dict[str, Any] | None,
        scenario_cfg: dict[str, Any] | None,
        scenario_type: str,
        effective_stop_policy: dict[str, Any],
        terminal_signal: bool,
        move_failed: bool,
        move_terminal: bool,
        fail_count: int,
        same_count: int,
        recent_repeat: bool,
        repeat_eval: dict[str, Any],
        no_progress_eval: dict[str, Any],
    ) -> tuple[bool, str, bool, str]:
        normalized_scenario_type = str(scenario_type or "content").strip().lower()
        is_curr_global_nav, nav_reason = is_global_nav_row(row, scenario_cfg=scenario_cfg)
        is_prev_global_nav, _ = is_global_nav_row(previous_row or {}, scenario_cfg=scenario_cfg)
        reason = ""
        stop = False
        if normalized_scenario_type == "content" and bool(effective_stop_policy.get("stop_on_global_nav_entry", False)):
            if bool(previous_row) and is_curr_global_nav and not is_prev_global_nav:
                stop = True
                reason = "global_nav_entry"
        elif normalized_scenario_type == "global_nav" and bool(effective_stop_policy.get("stop_on_global_nav_exit", False)):
            if bool(previous_row) and is_prev_global_nav and not is_curr_global_nav:
                stop = True
                reason = "global_nav_exit"

        if not stop and terminal_signal and bool(effective_stop_policy.get("stop_on_terminal", True)):
            stop = True
            reason = "smart_nav_terminal"
        elif (
            not stop
            and normalized_scenario_type == "global_nav"
            and bool(effective_stop_policy.get("stop_on_repeat_no_progress", True))
            and is_curr_global_nav
            and move_failed
            and no_progress_eval["no_progress"]
            and recent_repeat
        ):
            stop = True
            reason = "global_nav_end"
        elif (
            not stop
            and move_terminal
            and repeat_eval["same_like"]
            and bool(effective_stop_policy.get("stop_on_terminal", True))
        ):
            stop = True
            reason = "move_terminal"
        elif not stop and bool(effective_stop_policy.get("stop_on_repeat_no_progress", True)):
            if repeat_eval["bounded_two_card_loop"]:
                stop = True
                reason = "bounded_two_card_loop"
            elif (
                same_count >= 8
                and bool(row.get("is_recent_duplicate_step", False))
                and bool(row.get("is_recent_semantic_duplicate_step", False))
                and int(row.get("recent_semantic_unique_count", 0) or 0) <= 1
                and repeat_eval["semantic_duplicate"]
            ):
                stop = True
                reason = "repeat_semantic_stall"
            elif no_progress_eval["hard_no_progress"] and repeat_eval["strict_duplicate"]:
                stop = True
                reason = "repeat_no_progress"
            elif (
                repeat_eval["semantic_duplicate"]
                and no_progress_eval["soft_no_progress"]
                and same_count >= 4
                and int(row.get("recent_semantic_unique_count", 0) or 0) <= 2
            ):
                stop = True
                reason = "repeat_no_progress"
        return stop, reason, is_curr_global_nav, nav_reason

    def evaluate(
        self,
        row: dict[str, Any],
        prev_fingerprint: tuple[str, str, str],
        fail_count: int,
        same_count: int,
        previous_row: dict[str, Any] | None = None,
        scenario_type: str = "content",
        stop_policy: dict[str, Any] | None = None,
        scenario_cfg: dict[str, Any] | None = None,
    ) -> tuple[bool, int, int, str, tuple[str, str, str], dict[str, Any]]:
        move_result = str(row.get("move_result", "") or "").strip().lower()
        smart_nav_result = str(row.get("last_smart_nav_result", "") or "").strip().lower()
        terminal_signal = bool(row.get("last_smart_nav_terminal", False))

        current_fingerprint = (
            str(row.get("normalized_visible_label", "") or "").strip(),
            str(row.get("focus_view_id", "") or "").strip(),
            str(row.get("focus_bounds", "") or "").strip(),
        )
        current_signature = self._signature(row)
        previous_signature = self._signature(previous_row or {})
        current_semantic_signature = self._semantic_signature(row)
        previous_semantic_signature = self._semantic_signature(previous_row or {})
        recent_duplicate = bool(row.get("is_recent_duplicate_step", False))
        recent_duplicate_distance = int(row.get("recent_duplicate_distance", 0) or 0)
        recent_semantic_duplicate = bool(row.get("is_recent_semantic_duplicate_step", False))
        recent_semantic_duplicate_distance = int(row.get("recent_semantic_duplicate_distance", 0) or 0)
        recent_semantic_unique_count = int(row.get("recent_semantic_unique_count", 0) or 0)
        repeat_eval = self.evaluate_repeat(
            current_fingerprint=current_fingerprint,
            prev_fingerprint=prev_fingerprint,
            current_signature=current_signature,
            previous_signature=previous_signature,
            current_semantic_signature=current_semantic_signature,
            previous_semantic_signature=previous_semantic_signature,
            recent_duplicate=recent_duplicate,
            recent_semantic_duplicate=recent_semantic_duplicate,
            recent_semantic_duplicate_distance=recent_semantic_duplicate_distance,
            recent_semantic_unique_count=recent_semantic_unique_count,
        )
        same_like = bool(repeat_eval["same_like"])
        semantic_same_like = bool(repeat_eval["semantic_duplicate"] or repeat_eval["repeat_class"] == "mixed_repeat")
        same_count = same_count + 1 if same_like else 0

        move_failed = move_result in self._MOVE_FAILURE_RESULTS
        if move_failed:
            fail_count += 1
        else:
            fail_count = 0

        move_terminal = smart_nav_result in self._MOVE_TERMINAL_RESULTS or move_result in self._MOVE_TERMINAL_RESULTS

        no_progress_eval = self.evaluate_no_progress(
            same_like=same_like,
            strict_duplicate=bool(repeat_eval["strict_duplicate"]),
            semantic_duplicate=bool(repeat_eval["semantic_duplicate"]),
            bounded_two_card_loop=bool(repeat_eval["bounded_two_card_loop"]),
            move_failed=move_failed,
            move_terminal=move_terminal,
            smart_nav_result=smart_nav_result,
            fail_count=fail_count,
            same_count=same_count,
            recent_semantic_unique_count=recent_semantic_unique_count,
        )
        no_progress = bool(previous_row) and bool(no_progress_eval["no_progress"])
        overlay_ctx = self.evaluate_overlay_context(row=row, repeat_class=str(repeat_eval["repeat_class"]))
        after_realign = bool(overlay_ctx["after_realign"])
        recent_repeat = (same_like and same_count >= 2) or bool(repeat_eval["bounded_two_card_loop"])

        effective_stop_policy = dict(
            {
                "stop_on_global_nav_entry": False,
                "stop_on_global_nav_exit": False,
                "stop_on_terminal": True,
                "stop_on_repeat_no_progress": True,
            }
        )
        normalized_scenario_type = str(scenario_type or "content").strip().lower()
        if isinstance(stop_policy, dict):
            effective_stop_policy.update(stop_policy)
        stop, reason, is_curr_global_nav, nav_reason = self.evaluate_stop(
            row=row,
            previous_row=previous_row,
            scenario_cfg=scenario_cfg,
            scenario_type=normalized_scenario_type,
            effective_stop_policy=effective_stop_policy,
            terminal_signal=terminal_signal,
            move_failed=move_failed,
            move_terminal=move_terminal,
            fail_count=fail_count,
            same_count=same_count,
            recent_repeat=recent_repeat,
            repeat_eval=repeat_eval,
            no_progress_eval=no_progress_eval,
        )
        stop, reason, decision_meta = self.finalize_decision(
            stop=stop,
            reason=reason,
            row=row,
            effective_stop_policy=effective_stop_policy,
            repeat_class=str(repeat_eval["repeat_class"]),
            strict_duplicate=bool(repeat_eval["strict_duplicate"]),
            hard_no_progress=bool(no_progress_eval["hard_no_progress"]),
            overlay_ctx=overlay_ctx,
        )

        details = {
            "terminal": terminal_signal,
            "same_like_count": same_count,
            "no_progress": no_progress,
            "reason": reason,
            "scenario_type": normalized_scenario_type,
            "is_global_nav": is_curr_global_nav,
            "global_nav_reason": nav_reason,
            "after_realign": after_realign,
            "recent_repeat": recent_repeat,
            "bounded_two_card_loop": bool(repeat_eval["bounded_two_card_loop"]),
            "recent_duplicate": recent_duplicate,
            "recent_duplicate_distance": recent_duplicate_distance,
            "recent_semantic_duplicate": recent_semantic_duplicate,
            "recent_semantic_duplicate_distance": recent_semantic_duplicate_distance,
            "recent_semantic_unique_count": recent_semantic_unique_count,
            "semantic_same_like": semantic_same_like,
            "strict_duplicate": bool(repeat_eval["strict_duplicate"]),
            "semantic_duplicate": bool(repeat_eval["semantic_duplicate"]),
            "repeat_class": str(repeat_eval["repeat_class"]),
            "loop_classification": str(repeat_eval["loop_classification"]),
            "hard_no_progress": bool(no_progress_eval["hard_no_progress"]),
            "soft_no_progress": bool(no_progress_eval["soft_no_progress"]),
            "no_progress_class": str(no_progress_eval["no_progress_class"]),
            "overlay_realign_grace_active": bool(overlay_ctx["realign_grace_active"]),
            "min_steps_before_repeat_stop": int(decision_meta["min_steps_before_repeat_stop"]),
            "min_step_gate_blocked": bool(decision_meta["min_step_gate_blocked"]),
            "realign_grace_suppressed": bool(decision_meta["realign_grace_suppressed"]),
            "repeat_stop_hit": reason in {"repeat_no_progress", "bounded_two_card_loop", "repeat_semantic_stall"},
            "raw_fingerprint": current_fingerprint,
            "semantic_signature": current_semantic_signature,
        }
        return stop, fail_count, same_count, reason, current_fingerprint, details


def should_stop(
    row: dict,
    prev_fingerprint: tuple[str, str, str],
    fail_count: int,
    same_count: int,
    previous_row: dict[str, Any] | None = None,
    scenario_type: str = "content",
    stop_policy: dict[str, Any] | None = None,
    scenario_cfg: dict[str, Any] | None = None,
) -> tuple[bool, int, int, str, tuple[str, str, str], dict[str, Any]]:
    evaluator = StopEvaluator()
    return evaluator.evaluate(
        row=row,
        prev_fingerprint=prev_fingerprint,
        fail_count=fail_count,
        same_count=same_count,
        previous_row=previous_row,
        scenario_type=scenario_type,
        stop_policy=stop_policy,
        scenario_cfg=scenario_cfg,
    )
