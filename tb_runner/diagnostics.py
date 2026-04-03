from typing import Any

from tb_runner.utils import parse_bounds_str


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
    if visible and speech and not speech_visible_compatible:
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


class StopEvaluator:
    _MOVE_FAILURE_RESULTS = {"failed"}
    _MOVE_TERMINAL_RESULTS = {"terminal", "end", "no_next", "no_focus", "cannot_move"}

    def _signature(self, row: dict[str, Any]) -> tuple[str, str, str, str, str]:
        normalized_visible = str(row.get("normalized_visible_label", "") or "").strip()
        normalized_speech = str(row.get("normalized_announcement", "") or "").strip()
        focus_bounds = str(row.get("focus_bounds", "") or "").strip()
        resource_id = str(row.get("focus_view_id", "") or row.get("resource_id", "") or "").strip()
        view_id = str(row.get("focus_node", {}).get("viewIdResourceName", "") or "").strip() if isinstance(row.get("focus_node"), dict) else ""
        return normalized_visible, normalized_speech, focus_bounds, resource_id, view_id

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

    def evaluate(
        self,
        row: dict[str, Any],
        prev_fingerprint: tuple[str, str, str],
        fail_count: int,
        same_count: int,
        previous_row: dict[str, Any] | None = None,
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
        same_like = self._is_same_like(previous_signature, current_signature)
        if not same_like and all(current_fingerprint) and current_fingerprint == prev_fingerprint:
            same_like = True
        same_count = same_count + 1 if same_like else 0

        move_failed = move_result in self._MOVE_FAILURE_RESULTS
        if move_failed:
            fail_count += 1
        else:
            fail_count = 0

        move_terminal = smart_nav_result in self._MOVE_TERMINAL_RESULTS or move_result in self._MOVE_TERMINAL_RESULTS

        no_progress = bool(previous_row) and same_like and (move_failed or move_terminal or smart_nav_result in {"failed", "unchanged"})
        weak_repeat = same_count >= 2
        weak_move_failure = fail_count >= 2 or move_terminal
        weak_empty = not str(row.get("visible_label", "") or "").strip() and not str(row.get("merged_announcement", "") or "").strip()

        reason = ""
        stop = False

        if terminal_signal:
            stop = True
            reason = "smart_nav_terminal"
        elif move_terminal and same_like:
            stop = True
            reason = "move_terminal"
        else:
            weak_signals = sum([1 if weak_repeat else 0, 1 if no_progress else 0, 1 if weak_move_failure else 0, 1 if weak_empty else 0])
            if weak_signals >= 2 and (same_like or weak_repeat):
                stop = True
                reason = "repeat_no_progress"

        details = {
            "terminal": terminal_signal,
            "same_like_count": same_count,
            "no_progress": no_progress,
            "reason": reason,
        }
        return stop, fail_count, same_count, reason, current_fingerprint, details


def should_stop(
    row: dict,
    prev_fingerprint: tuple[str, str, str],
    fail_count: int,
    same_count: int,
    previous_row: dict[str, Any] | None = None,
) -> tuple[bool, int, int, str, tuple[str, str, str], dict[str, Any]]:
    evaluator = StopEvaluator()
    return evaluator.evaluate(
        row=row,
        prev_fingerprint=prev_fingerprint,
        fail_count=fail_count,
        same_count=same_count,
        previous_row=previous_row,
    )
