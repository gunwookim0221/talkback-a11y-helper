import re
import time
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.constants import (
    BACK_RECOVERY_WAIT_SECONDS,
    CHECKPOINT_SAVE_EVERY_STEPS,
    MAIN_ANNOUNCEMENT_WAIT_SECONDS,
    MAIN_STEP_WAIT_SECONDS,
    OVERLAY_ANNOUNCEMENT_WAIT_SECONDS,
    OVERLAY_MAX_STEPS,
    OVERLAY_REALIGN_MAX_STEPS,
    OVERLAY_STEP_WAIT_SECONDS,
)
from tb_runner.diagnostics import is_placeholder_row, should_stop
from tb_runner.excel_report import save_excel
from tb_runner.image_utils import maybe_capture_focus_crop
from tb_runner.logging_utils import log
from tb_runner.perf_stats import ScenarioPerfStats, save_excel_with_perf
from tb_runner.utils import build_row_fingerprint, make_main_fingerprint


OVERLAY_REALIGN_ROBUSTNESS_VERSION = "pr14-a-realign-robustness-v3"
OVERLAY_REPEAT_GUARD_VERSION = "pr66-overlay-repeat-guard-v3"
OVERLAY_ADVANCEMENT_GUARD_VERSION = "pr67-overlay-advance-on-duplicate-v3"
OVERLAY_ENTRY_ADVANCEMENT_VERSION = "pr68-overlay-entry-advancement-v3"
OVERLAY_ADVANCE_DEBUG_VERSION = "pr69-overlay-advance-debug-v2"


def _get_positive_int(tab_cfg: dict[str, Any], key: str, fallback: int) -> int:
    value = tab_cfg.get(key, fallback)
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int) and value > 0:
        return value
    return fallback


def _get_positive_float(tab_cfg: dict[str, Any], key: str, fallback: float) -> float:
    value = tab_cfg.get(key, fallback)
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return fallback


def _matches_overlay_candidate(step: dict[str, Any], entry: dict[str, Any]) -> bool:
    focus_view_id = str(step.get("focus_view_id", "") or "").strip()
    normalized_visible_label = str(step.get("normalized_visible_label", "") or "").strip()
    focus_node = step.get("focus_node")
    focus_class_name = str(
        step.get("focus_class_name", "")
        or step.get("class_name", "")
        or step.get("className", "")
        or (focus_node.get("className", "") if isinstance(focus_node, dict) else "")
        or ""
    ).strip()
    entry_view_id = str(entry.get("resource_id", "") or "").strip()
    entry_label = str(entry.get("label", "") or "").strip().lower()
    entry_class_name = str(entry.get("class_name", "") or entry.get("className", "") or "").strip()

    has_condition = bool(entry_view_id or entry_label or entry_class_name)
    if not has_condition:
        return False
    if entry_view_id and focus_view_id != entry_view_id:
        return False
    if entry_label and normalized_visible_label != entry_label:
        return False
    if entry_class_name and focus_class_name != entry_class_name:
        return False
    return True


def _get_overlay_policy_entries(tab_cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    policy = tab_cfg.get("overlay_policy")
    if not isinstance(policy, dict):
        return [], [], "no_overlay_policy"
    allow_candidates = list(policy.get("allow_candidates", []) or [])
    block_candidates = list(policy.get("block_candidates", []) or [])
    if not allow_candidates:
        return [], block_candidates, "empty_allow_list"
    return allow_candidates, block_candidates, "scenario_policy"


def is_overlay_candidate(step: dict[str, Any], tab_cfg: dict[str, Any]) -> tuple[bool, str]:
    allow_candidates, block_candidates, source = _get_overlay_policy_entries(tab_cfg)

    for entry in block_candidates:
        if _matches_overlay_candidate(step, entry):
            return False, f"blocked_by_{source}"

    if source == "no_overlay_policy":
        return False, "blocked_no_overlay_policy"
    if source == "empty_allow_list":
        return False, "blocked_empty_allow_list"

    for entry in allow_candidates:
        if _matches_overlay_candidate(step, entry):
            return True, f"matched_{source}"

    return False, f"not_in_{source}"


def _node_signature(step: dict[str, Any]) -> set[str]:
    signatures: set[str] = set()
    nodes = step.get("dump_tree_nodes", [])
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        view_id = str(node.get("viewIdResourceName", "") or "").strip()
        text = str(node.get("text", "") or "").strip().lower()
        desc = str(node.get("contentDescription", "") or "").strip().lower()
        marker = f"{view_id}|{text}|{desc}".strip("|")
        if marker:
            signatures.add(marker)
    return signatures


def classify_post_click_result(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    pre_click_step: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    post_click_step = client.collect_focus_step(
        dev=dev,
        step_index=int(pre_click_step.get("step_index", 0) or 0),
        move=False,
        wait_seconds=_get_positive_float(tab_cfg, "main_step_wait_seconds", MAIN_STEP_WAIT_SECONDS),
        announcement_wait_seconds=_get_positive_float(
            tab_cfg,
            "main_announcement_wait_seconds",
            MAIN_ANNOUNCEMENT_WAIT_SECONDS,
        ),
    )

    pre_fp = make_main_fingerprint(pre_click_step)
    post_fp = make_main_fingerprint(post_click_step)
    if pre_fp == post_fp and any(pre_fp):
        return "unchanged", post_click_step

    pre_signature = _node_signature(pre_click_step)
    post_signature = _node_signature(post_click_step)
    overlap_ratio = 0.0
    if pre_signature and post_signature:
        overlap_ratio = len(pre_signature & post_signature) / float(max(len(pre_signature), 1))

    entry_is_overlay_candidate, _ = is_overlay_candidate(pre_click_step, tab_cfg)
    post_label = str(post_click_step.get("visible_label", "") or "").strip().lower()
    post_announcement = str(post_click_step.get("merged_announcement", "") or "").strip().lower()
    post_view_id = str(post_click_step.get("focus_view_id", "") or "").strip().lower()
    navigation_cues = ("navigate up", "back", "up button")
    toolbar_cues = ("toolbar", "action_bar", "appbar", "title")
    explicit_navigation_cue = (
        any(cue in post_label for cue in navigation_cues)
        or any(cue in post_announcement for cue in navigation_cues)
    )
    toolbar_navigation_cue = any(cue in post_view_id for cue in toolbar_cues)
    navigation_cue = bool(explicit_navigation_cue or (toolbar_navigation_cue and not entry_is_overlay_candidate))
    overlap_navigation = bool(pre_signature and post_signature and overlap_ratio < 0.30)
    overlap_navigation_guarded = bool(
        overlap_navigation
        and entry_is_overlay_candidate
        and not explicit_navigation_cue
    )

    if navigation_cue:
        log(
            f"[OVERLAY][classify] overlap_ratio={overlap_ratio:.2f} "
            f"entry_is_overlay_candidate={entry_is_overlay_candidate} "
            f"navigation_cue={navigation_cue} overlap_navigation_guarded={overlap_navigation_guarded} "
            f"reason='navigation_cue' result='navigation'",
            level="DEBUG",
        )
        return "navigation", post_click_step

    if overlap_navigation and not overlap_navigation_guarded:
        log(
            f"[OVERLAY][classify] overlap_ratio={overlap_ratio:.2f} "
            f"entry_is_overlay_candidate={entry_is_overlay_candidate} "
            f"navigation_cue={navigation_cue} overlap_navigation_guarded={overlap_navigation_guarded} "
            f"reason='low_signature_overlap' result='navigation'",
            level="DEBUG",
        )
        return "navigation", post_click_step

    if pre_signature and post_signature and 0.30 <= overlap_ratio < 0.45:
        log(
            f"[WARN] overlay classification low-confidence "
            f"overlap_ratio={overlap_ratio:.2f} "
            f"pre_label='{pre_click_step.get('visible_label', '')}' "
            f"post_label='{post_click_step.get('visible_label', '')}'"
        )

    log(
        f"[OVERLAY][classify] overlap_ratio={overlap_ratio:.2f} "
        f"entry_is_overlay_candidate={entry_is_overlay_candidate} "
        f"navigation_cue={navigation_cue} overlap_navigation_guarded={overlap_navigation_guarded} "
        f"reason='default_overlay' result='overlay'",
        level="DEBUG",
    )
    return "overlay", post_click_step


def is_overlay_entry_focus(current_step: dict[str, Any], entry_step: dict[str, Any]) -> bool:
    current_view_id = str(current_step.get("focus_view_id", "") or "").strip()
    entry_view_id = str(entry_step.get("focus_view_id", "") or "").strip()
    if current_view_id and entry_view_id and current_view_id == entry_view_id:
        return True

    current_label = str(current_step.get("normalized_visible_label", "") or "").strip()
    entry_label = str(entry_step.get("normalized_visible_label", "") or "").strip()
    if current_label and entry_label and current_label == entry_label:
        return True

    current_bounds = str(current_step.get("focus_bounds", "") or "").strip()
    entry_bounds = str(entry_step.get("focus_bounds", "") or "").strip()
    return bool(current_bounds and entry_bounds and current_bounds == entry_bounds)


def get_overlay_entry_match_by(current_step: dict[str, Any], entry_step: dict[str, Any]) -> str:
    current_view_id = str(current_step.get("focus_view_id", "") or "").strip()
    entry_view_id = str(entry_step.get("focus_view_id", "") or "").strip()
    if current_view_id and entry_view_id and current_view_id == entry_view_id:
        return "view_id"

    current_label = str(current_step.get("normalized_visible_label", "") or "").strip()
    entry_label = str(entry_step.get("normalized_visible_label", "") or "").strip()
    if current_label and entry_label and current_label == entry_label:
        return "label"
    if current_label and entry_label and (current_label in entry_label or entry_label in current_label):
        return "label_partial"

    current_bounds = str(current_step.get("focus_bounds", "") or "").strip()
    entry_bounds = str(entry_step.get("focus_bounds", "") or "").strip()
    if current_bounds and entry_bounds and current_bounds == entry_bounds:
        return "bounds"
    if current_bounds and entry_bounds:
        try:
            current_left, current_top, current_right, current_bottom = [int(part) for part in current_bounds.split(",")]
            entry_left, entry_top, entry_right, entry_bottom = [int(part) for part in entry_bounds.split(",")]
        except ValueError:
            return ""

        overlap_left = max(current_left, entry_left)
        overlap_top = max(current_top, entry_top)
        overlap_right = min(current_right, entry_right)
        overlap_bottom = min(current_bottom, entry_bottom)
        overlap_width = max(0, overlap_right - overlap_left)
        overlap_height = max(0, overlap_bottom - overlap_top)
        overlap_area = overlap_width * overlap_height
        if overlap_area > 0:
            current_area = max(1, (current_right - current_left) * (current_bottom - current_top))
            entry_area = max(1, (entry_right - entry_left) * (entry_bottom - entry_top))
            overlap_ratio = overlap_area / float(max(1, min(current_area, entry_area)))
            if overlap_ratio >= 0.65:
                return "bounds_overlap"
    return ""


def collect_realign_probe(
    client: A11yAdbClient,
    dev: str,
    move: bool,
    probe_idx: int = 0,
    direction: str = "next",
    wait_seconds: float = MAIN_STEP_WAIT_SECONDS,
) -> dict[str, Any]:
    probe: dict[str, Any] = {
        "move_result": None,
        "move_elapsed_sec": 0.0,
        "get_focus_elapsed_sec": 0.0,
        "focus_view_id": "",
        "focus_bounds": "",
        "visible_label": "",
        "normalized_visible_label": "",
        "realign_probe_idx": probe_idx,
        "realign_move_result": "",
        "realign_focus_source": "none",
    }

    if move:
        move_started = time.monotonic()
        try:
            if str(direction).strip().lower() == "next":
                probe["move_result"] = client.move_focus_smart(dev=dev, direction=direction)
            else:
                probe["move_result"] = "moved" if client.move_focus(dev=dev, direction=direction) else "failed"
        except Exception as exc:  # defensive
            probe["move_result"] = f"error: {exc}"
        probe["move_elapsed_sec"] = round(time.monotonic() - move_started, 3)
    probe["realign_move_result"] = str(probe.get("move_result", "") or "")

    focus_started = time.monotonic()
    try:
        focus_node = client.get_focus(dev=dev, wait_seconds=wait_seconds)
    except Exception:
        focus_node = {}
    probe["get_focus_elapsed_sec"] = round(time.monotonic() - focus_started, 3)

    safe_focus_node = focus_node if isinstance(focus_node, dict) else {}
    probe["focus_view_id"] = str(safe_focus_node.get("viewIdResourceName", "") or "").strip()
    probe["visible_label"] = client.extract_visible_label_from_focus(safe_focus_node)
    probe["normalized_visible_label"] = client.normalize_for_comparison(probe["visible_label"])

    normalize_bounds = getattr(client, "_normalize_bounds", None)
    if callable(normalize_bounds):
        probe["focus_bounds"] = str(normalize_bounds(safe_focus_node) or "").strip()
    trace = getattr(client, "last_get_focus_trace", {})
    if isinstance(trace, dict):
        probe["realign_focus_source"] = str(trace.get("focus_payload_source", "none") or "none")

    log(
        f"[OVERLAY] realign probe move={move} "
        f"move_elapsed={probe['move_elapsed_sec']:.3f}s "
        f"focus_elapsed={probe['get_focus_elapsed_sec']:.3f}s "
        f"view_id='{probe['focus_view_id']}' "
        f"label='{probe['visible_label']}'",
        level="DEBUG",
    )
    return probe


def realign_focus_after_overlay(
    client: A11yAdbClient,
    dev: str,
    entry_step: dict[str, Any],
    known_step_index_by_fingerprint: dict[tuple[str, str, str], int],
    tab_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    realign_tab_cfg = tab_cfg or {}
    main_step_wait_seconds = _get_positive_float(realign_tab_cfg, "main_step_wait_seconds", MAIN_STEP_WAIT_SECONDS)

    current_step = collect_realign_probe(
        client=client,
        dev=dev,
        move=False,
        probe_idx=0,
        wait_seconds=main_step_wait_seconds,
    )
    current_fp = make_main_fingerprint(current_step)
    entry_idx = int(entry_step.get("step_index", 0) or 0)

    current_match_by = get_overlay_entry_match_by(current_step, entry_step)
    if current_match_by:
        if current_match_by == "bounds":
            log(
                f"[WARN] overlay realign matched by bounds only "
                f"probe_idx=0 entry_label='{entry_step.get('visible_label', '')}'",
            )
        return {
            "status": "already_on_entry",
            "steps_taken": 0,
            "entry_reached": True,
            "match_by": current_match_by,
            "current_step": current_step,
        }

    seen_idx = known_step_index_by_fingerprint.get(current_fp)
    if seen_idx is not None and seen_idx >= entry_idx:
        return {
            "status": "skip_realign_not_before_entry",
            "steps_taken": 0,
            "entry_reached": False,
            "current_step": current_step,
        }

    for direction in ("next", "prev"):
        for realign_idx in range(1, OVERLAY_REALIGN_MAX_STEPS + 1):
            probe_step = collect_realign_probe(
                client=client,
                dev=dev,
                move=True,
                probe_idx=realign_idx,
                direction=direction,
                wait_seconds=main_step_wait_seconds,
            )
            match_by = get_overlay_entry_match_by(probe_step, entry_step)
            if match_by:
                if match_by == "bounds":
                    log(
                        f"[WARN] overlay realign matched by bounds only "
                        f"probe_idx={realign_idx} entry_label='{entry_step.get('visible_label', '')}'",
                    )
                return {
                    "status": "realign_entry_reached",
                    "steps_taken": realign_idx,
                    "entry_reached": True,
                    "match_by": match_by,
                    "current_step": probe_step,
                }

    return {
        "status": "realign_entry_not_found",
        "steps_taken": OVERLAY_REALIGN_MAX_STEPS,
        "entry_reached": False,
        "match_by": "",
        "current_step": current_step,
    }


def expand_overlay(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    entry_step: dict[str, Any],
    rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    output_path: str,
    output_base_dir: str,
    skip_entry_click: bool = False,
    scenario_perf: ScenarioPerfStats | None = None,
    initial_overlay_step: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    overlay_rows: list[dict[str, Any]] = []
    overlay_step_wait_seconds = _get_positive_float(tab_cfg, "overlay_step_wait_seconds", OVERLAY_STEP_WAIT_SECONDS)
    overlay_announcement_wait_seconds = _get_positive_float(
        tab_cfg,
        "overlay_announcement_wait_seconds",
        OVERLAY_ANNOUNCEMENT_WAIT_SECONDS,
    )
    overlay_announcement_idle_wait_seconds = _get_positive_float(
        tab_cfg,
        "overlay_announcement_idle_wait_seconds",
        0.4,
    )
    overlay_announcement_max_extra_wait_seconds = _get_positive_float(
        tab_cfg,
        "overlay_announcement_max_extra_wait_seconds",
        1.0,
    )
    back_recovery_wait_seconds = _get_positive_float(tab_cfg, "back_recovery_wait_seconds", BACK_RECOVERY_WAIT_SECONDS)
    checkpoint_every = _get_positive_int(tab_cfg, "checkpoint_save_every", CHECKPOINT_SAVE_EVERY_STEPS)
    overlay_max_advancement_failures = _get_positive_int(tab_cfg, "overlay_max_advancement_failures", 4)
    overlay_min_rows_before_stall = max(2, _get_positive_int(tab_cfg, "overlay_min_rows_before_stall", 3))
    overlay_min_distinct_rows_before_stall = max(2, _get_positive_int(tab_cfg, "overlay_min_distinct_rows_before_stall", 2))
    overlay_duplicate_rescue_trigger = max(1, _get_positive_int(tab_cfg, "overlay_duplicate_rescue_trigger", 2))
    overlay_duplicate_rescue_budget = max(1, _get_positive_int(tab_cfg, "overlay_duplicate_rescue_budget", 3))

    entry_label = str(entry_step.get("visible_label", "") or "").strip()
    entry_view_id = str(entry_step.get("focus_view_id", "") or "").strip()

    clicked = skip_entry_click
    if not clicked and entry_view_id:
        clicked = client.touch(
            dev=dev,
            name=f"^{re.escape(entry_view_id)}$",
            type_="r",
            wait_=3,
        )
    elif not clicked and entry_label:
        clicked = client.touch(
            dev=dev,
            name=f"^{re.escape(entry_label)}$",
            type_="a",
            wait_=3,
        )

    recovery_status = "not_attempted"
    if not clicked:
        recovery_status = "entry_click_failed"
        return overlay_rows

    if not skip_entry_click:
        time.sleep(1.0)

    parent_step_index = entry_step.get("step_index")
    overlay_prev_fingerprint = ("", "", "")
    overlay_previous_row: dict[str, Any] | None = None
    overlay_fail_count = 0
    overlay_same_count = 0
    overlay_same_fingerprint_streak = 0
    overlay_same_focus_streak = 0
    overlay_duplicate_streak = 0
    overlay_advancement_fail_streak = 0
    overlay_seen_fingerprints: set[str] = set()
    overlay_seen_actionable_keys: set[str] = set()
    overlay_duplicate_rescue_count = 0
    overlay_title_repeat_streak = 0
    initial_candidate_saved = False
    initial_candidate_skipped_reason = ""
    post_label_seen = False

    def _to_boolish(value: Any) -> bool:
        return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y"}

    def _is_title_like_row(row: dict[str, Any]) -> bool:
        view_id = str(row.get("focus_view_id", "") or "").strip().lower()
        return any(token in view_id for token in ("tvheadertitle", ":id/title", ":id/label"))

    def _build_actionable_key(row: dict[str, Any]) -> str:
        return "|".join(
            [
                str(row.get("focus_view_id", "") or "").strip().lower(),
                str(row.get("focus_bounds", "") or "").strip(),
                str(row.get("focus_class_name", "") or row.get("class_name", "") or row.get("className", "") or "").strip(),
                str(_to_boolish(row.get("focus_clickable", "") or row.get("clickable", ""))).lower(),
                str(_to_boolish(row.get("focus_focusable", "") or row.get("focusable", ""))).lower(),
            ]
        )

    def _move_overlay_next_once() -> str:
        move_focus_smart = getattr(client, "move_focus_smart", None)
        if callable(move_focus_smart):
            return str(move_focus_smart(dev=dev, direction="next") or "").strip().lower()
        move_focus = getattr(client, "move_focus", None)
        if callable(move_focus):
            return "moved" if bool(move_focus(dev=dev, direction="next")) else "failed"
        return "unsupported"

    def _log_overlay_advance_debug(
        row: dict[str, Any],
        step_idx: int,
        *,
        same_focus_detected_value: bool,
        seen_overlay_row_value: bool,
        skip_duplicate_row_value: bool,
        duplicate_streak_value: int,
        advancement_fail_streak_value: int,
        post_label_value: str,
        is_initial_overlay_step: bool,
        row_fingerprint_value: str,
    ) -> None:
        log(
            f"[OVERLAY][advance_debug] scenario='{tab_cfg.get('tab_name', '')}' step={step_idx} "
            f"visible='{row.get('visible_label', '')}' speech='{row.get('merged_announcement', '')}' "
            f"resource_id='{row.get('focus_view_id', '')}' class_name='{row.get('focus_class_name', '') or row.get('class_name', '') or row.get('className', '')}' "
            f"bounds='{row.get('focus_bounds', '')}' clickable={str(_to_boolish(row.get('focus_clickable', row.get('clickable', '')))).lower()} "
            f"focusable={str(_to_boolish(row.get('focus_focusable', row.get('focusable', '')))).lower()} "
            f"selected={str(_to_boolish(row.get('focus_selected', row.get('selected', '')))).lower()} "
            f"fingerprint='{row_fingerprint_value}' main_fp='{make_main_fingerprint(row)}' "
            f"same_focus_detected={str(same_focus_detected_value).lower()} seen_overlay_row={str(seen_overlay_row_value).lower()} "
            f"skip_duplicate_row={str(skip_duplicate_row_value).lower()} duplicate_streak={duplicate_streak_value} "
            f"advancement_fail_streak={advancement_fail_streak_value} post_label='{post_label_value}' "
            f"initial_overlay_step={str(is_initial_overlay_step).lower()} debug_version='{OVERLAY_ADVANCE_DEBUG_VERSION}'",
            level="DEBUG",
        )

    def _prepare_overlay_row(row: dict[str, Any], step_index: int) -> dict[str, Any]:
        row["step_index"] = step_index
        row["tab_name"] = tab_cfg["tab_name"]
        row["context_type"] = "overlay"
        row["parent_step_index"] = parent_step_index
        row["overlay_entry_label"] = entry_label
        row["overlay_recovery_status"] = ""
        row["status"] = "OK"
        row["stop_reason"] = ""
        row["crop_image"] = "IMAGE"
        return row

    next_overlay_step_idx = 1
    if isinstance(initial_overlay_step, dict):
        post_label = str(initial_overlay_step.get("visible_label", "") or "").strip()
        post_label_seen = bool(post_label)
        initial_row = _prepare_overlay_row(dict(initial_overlay_step), next_overlay_step_idx)
        initial_row.setdefault("move_result", "post_click_probe")
        has_initial_payload = bool(
            str(initial_row.get("visible_label", "") or "").strip()
            or str(initial_row.get("merged_announcement", "") or "").strip()
        )
        initial_meaningful_item = bool(
            has_initial_payload
            and (
                str(initial_row.get("normalized_visible_label", "") or "").strip()
                or str(initial_row.get("visible_label", "") or "").strip()
                or str(initial_row.get("merged_announcement", "") or "").strip()
            )
        )
        if has_initial_payload and (initial_meaningful_item or not is_placeholder_row(initial_row)):
            overlay_context_matches = bool(
                str(initial_row.get("context_type", "") or "").strip() == "overlay"
                and str(initial_row.get("overlay_entry_label", "") or "").strip() == entry_label
            )
            if not overlay_context_matches:
                initial_candidate_skipped_reason = "context_mismatch"
            elif is_placeholder_row(initial_row):
                initial_candidate_skipped_reason = "placeholder_row"
            else:
                initial_row["_step_mono_start"] = time.monotonic() - float(initial_row.get("t_step_start", 0.0) or 0.0)
                initial_row = maybe_capture_focus_crop(client, dev, initial_row, output_base_dir)
                initial_row.pop("_step_mono_start", None)
                overlay_rows.append(initial_row)
                rows.append(initial_row)
                all_rows.append(initial_row)
                initial_overlay_fp = build_row_fingerprint(initial_row)
                if initial_overlay_fp:
                    overlay_seen_fingerprints.add(initial_overlay_fp)
                initial_actionable_key = _build_actionable_key(initial_row)
                if initial_actionable_key and not _is_title_like_row(initial_row):
                    overlay_seen_actionable_keys.add(initial_actionable_key)
                overlay_previous_row = initial_row
                next_overlay_step_idx = 2
                initial_candidate_saved = True
                _log_overlay_advance_debug(
                    initial_row,
                    next_overlay_step_idx - 1,
                    same_focus_detected_value=False,
                    seen_overlay_row_value=False,
                    skip_duplicate_row_value=False,
                    duplicate_streak_value=overlay_duplicate_streak,
                    advancement_fail_streak_value=overlay_advancement_fail_streak,
                    post_label_value=post_label,
                    is_initial_overlay_step=True,
                    row_fingerprint_value=build_row_fingerprint(initial_row),
                )
        else:
            initial_candidate_skipped_reason = "empty_payload" if not has_initial_payload else "placeholder_row"
        log(
            f"[OVERLAY][initial_candidate] scenario='{tab_cfg.get('tab_name', '')}' "
            f"post_label='{post_label}' initial_overlay_step.visible='{initial_row.get('visible_label', '')}' "
            f"initial_overlay_step.resource_id='{initial_row.get('focus_view_id', '')}' "
            f"initial_overlay_step.bounds='{initial_row.get('focus_bounds', '')}' "
            f"row_saved={str(initial_candidate_saved).lower()} "
            f"row_skipped_reason='{initial_candidate_skipped_reason or 'none'}' duplicate_with_next=false",
            level="DEBUG",
        )

    for overlay_step_idx in range(next_overlay_step_idx, OVERLAY_MAX_STEPS + 1):
        overlay_row = client.collect_focus_step(
            dev=dev,
            step_index=overlay_step_idx,
            move=True,
            direction="next",
            wait_seconds=overlay_step_wait_seconds,
            announcement_wait_seconds=overlay_announcement_wait_seconds,
            announcement_idle_wait_seconds=overlay_announcement_idle_wait_seconds,
            announcement_max_extra_wait_seconds=overlay_announcement_max_extra_wait_seconds,
        )
        overlay_row = _prepare_overlay_row(overlay_row, overlay_step_idx)

        previous_overlay_fingerprint = build_row_fingerprint(overlay_previous_row or {})
        current_overlay_fingerprint = build_row_fingerprint(overlay_row)
        previous_focus_fingerprint = make_main_fingerprint(overlay_previous_row or {})
        current_focus_fingerprint = make_main_fingerprint(overlay_row)
        same_overlay_fingerprint = bool(overlay_previous_row) and bool(current_overlay_fingerprint) and (
            current_overlay_fingerprint == previous_overlay_fingerprint
        )
        same_focus_triplet = bool(overlay_previous_row) and all(current_focus_fingerprint) and (
            current_focus_fingerprint == previous_focus_fingerprint
        )
        previous_visible = str((overlay_previous_row or {}).get("visible_label", "") or "").strip().lower()
        current_visible = str(overlay_row.get("visible_label", "") or "").strip().lower()
        previous_announcement = str((overlay_previous_row or {}).get("merged_announcement", "") or "").strip().lower()
        current_announcement = str(overlay_row.get("merged_announcement", "") or "").strip().lower()
        repeated_label_or_announcement = bool(overlay_previous_row) and (
            (previous_visible and previous_visible == current_visible)
            or (previous_announcement and previous_announcement == current_announcement)
        )
        same_focus_detected = same_focus_triplet or repeated_label_or_announcement
        same_resource_id = bool(overlay_previous_row) and (
            str((overlay_previous_row or {}).get("focus_view_id", "") or "").strip()
            == str(overlay_row.get("focus_view_id", "") or "").strip()
        )
        same_bounds = bool(overlay_previous_row) and (
            str((overlay_previous_row or {}).get("focus_bounds", "") or "").strip()
            == str(overlay_row.get("focus_bounds", "") or "").strip()
        )
        previous_class_name = str(
            (overlay_previous_row or {}).get("focus_class_name", "")
            or (overlay_previous_row or {}).get("class_name", "")
            or (overlay_previous_row or {}).get("className", "")
            or ""
        ).strip()
        current_class_name = str(
            overlay_row.get("focus_class_name", "")
            or overlay_row.get("class_name", "")
            or overlay_row.get("className", "")
            or ""
        ).strip()
        same_class_name = bool(overlay_previous_row) and (previous_class_name == current_class_name)
        previous_clickable = _to_boolish(
            (overlay_previous_row or {}).get("focus_clickable", "") or (overlay_previous_row or {}).get("clickable", "")
        )
        current_clickable = _to_boolish(overlay_row.get("focus_clickable", "") or overlay_row.get("clickable", ""))
        previous_focusable = _to_boolish(
            (overlay_previous_row or {}).get("focus_focusable", "") or (overlay_previous_row or {}).get("focusable", "")
        )
        current_focusable = _to_boolish(overlay_row.get("focus_focusable", "") or overlay_row.get("focusable", ""))
        title_like_focus = _is_title_like_row(overlay_row)
        actionable_changed = bool(overlay_previous_row) and any(
            [
                not same_resource_id,
                not same_bounds,
                not same_class_name,
                previous_clickable != current_clickable,
            ]
        )
        strong_same_focus_detected = same_focus_triplet and same_resource_id and same_bounds
        repeat_requires_stall = bool(
            strong_same_focus_detected
            and not actionable_changed
            and (not title_like_focus or (same_resource_id and same_bounds and same_class_name))
        )
        same_overlay_context = bool(overlay_previous_row) and (
            str((overlay_previous_row or {}).get("context_type", "") or "").strip()
            == str(overlay_row.get("context_type", "") or "").strip()
            and str((overlay_previous_row or {}).get("overlay_entry_label", "") or "").strip()
            == str(overlay_row.get("overlay_entry_label", "") or "").strip()
            and str((overlay_previous_row or {}).get("parent_step_index", "") or "").strip()
            == str(overlay_row.get("parent_step_index", "") or "").strip()
        )
        duplicate_overlay_row = bool(overlay_previous_row) and all(
            [
                same_overlay_fingerprint,
                same_overlay_context,
                same_resource_id,
                same_bounds,
                previous_visible == current_visible,
                previous_announcement == current_announcement,
            ]
        )
        move_result = str(overlay_row.get("move_result", "") or "").strip().lower()
        overlay_row_fingerprint = build_row_fingerprint(overlay_row)
        overlay_row_actionable_key = _build_actionable_key(overlay_row)
        seen_overlay_row = bool(overlay_row_fingerprint) and overlay_row_fingerprint in overlay_seen_fingerprints
        seen_actionable_row = bool(overlay_row_actionable_key) and overlay_row_actionable_key in overlay_seen_actionable_keys
        if title_like_focus and same_resource_id and same_bounds and repeated_label_or_announcement:
            overlay_title_repeat_streak += 1
        else:
            overlay_title_repeat_streak = 0
        has_min_distinct_overlay_rows = len(overlay_seen_actionable_keys) >= overlay_min_distinct_rows_before_stall
        rescue_pending = bool(
            (
                (same_focus_detected and overlay_duplicate_streak >= overlay_duplicate_rescue_trigger)
                or overlay_title_repeat_streak >= overlay_duplicate_rescue_trigger
            )
            and overlay_duplicate_rescue_count < overlay_duplicate_rescue_budget
        )
        can_stall_overlay = len(overlay_rows) >= 2 and has_min_distinct_overlay_rows
        advancement_failed = can_stall_overlay and (
            (move_result in {"failed", "no_progress"} and not actionable_changed)
            or (
                repeat_requires_stall
                and len(overlay_rows) >= overlay_min_rows_before_stall
                and not rescue_pending
            )
        )
        overlay_advancement_fail_streak = overlay_advancement_fail_streak + 1 if advancement_failed else 0
        overlay_same_fingerprint_streak = (
            overlay_same_fingerprint_streak + 1 if same_overlay_fingerprint else 0
        )
        overlay_same_focus_streak = overlay_same_focus_streak + 1 if same_focus_detected else 0
        overlay_duplicate_streak = overlay_duplicate_streak + 1 if duplicate_overlay_row else 0
        visible_same = bool(overlay_previous_row) and previous_visible == current_visible
        resource_same = same_resource_id
        bounds_same = same_bounds
        class_same = same_class_name
        fingerprint_same = bool(overlay_previous_row) and current_overlay_fingerprint == previous_overlay_fingerprint
        clickable_same = bool(overlay_previous_row) and previous_clickable == current_clickable
        focusable_same = bool(overlay_previous_row) and previous_focusable == current_focusable
        effective_same_node = bool(
            overlay_previous_row
            and resource_same
            and bounds_same
            and class_same
            and fingerprint_same
            and clickable_same
            and focusable_same
        )
        log(
            f"[OVERLAY][advance_diff] scenario='{tab_cfg.get('tab_name', '')}' step={overlay_step_idx} "
            f"prev_visible_eq_curr_visible={str(visible_same).lower()} "
            f"prev_resource_id_eq_curr_resource_id={str(resource_same).lower()} "
            f"prev_bounds_eq_curr_bounds={str(bounds_same).lower()} "
            f"prev_class_eq_curr_class={str(class_same).lower()} "
            f"prev_fingerprint_eq_curr_fingerprint={str(fingerprint_same).lower()} "
            f"prev_clickable_eq_curr_clickable={str(clickable_same).lower()} "
            f"prev_focusable_eq_curr_focusable={str(focusable_same).lower()} "
            f"effective_same_node={str(effective_same_node).lower()}",
            level="DEBUG",
        )
        _log_overlay_advance_debug(
            overlay_row,
            overlay_step_idx,
            same_focus_detected_value=same_focus_detected,
            seen_overlay_row_value=seen_overlay_row,
            skip_duplicate_row_value=bool(duplicate_overlay_row or seen_overlay_row),
            duplicate_streak_value=overlay_duplicate_streak,
            advancement_fail_streak_value=overlay_advancement_fail_streak,
            post_label_value=str((initial_overlay_step or {}).get("visible_label", "") or "").strip(),
            is_initial_overlay_step=False,
            row_fingerprint_value=overlay_row_fingerprint,
        )

        if same_focus_detected:
            log(
                f"[OVERLAY][repeat] same_focus_detected=true step={overlay_step_idx} "
                f"view_id='{overlay_row.get('focus_view_id', '')}' bounds='{overlay_row.get('focus_bounds', '')}' "
                f"normalized_visible_label='{overlay_row.get('normalized_visible_label', '')}' move_result='{move_result}'"
            )

        forced_overlay_break_reason = ""
        if overlay_advancement_fail_streak >= overlay_max_advancement_failures and (
            has_min_distinct_overlay_rows or overlay_duplicate_rescue_count >= overlay_duplicate_rescue_budget
        ):
            forced_overlay_break_reason = "overlay_advancement_stalled"

        if forced_overlay_break_reason:
            log(
                f"[OVERLAY][break_debug] reason='{forced_overlay_break_reason}' step={overlay_step_idx} "
                f"duplicate_streak={overlay_duplicate_streak} advancement_fail_streak={overlay_advancement_fail_streak} "
                f"unique_overlay_rows_saved={len(overlay_seen_fingerprints)} last_visible='{overlay_row.get('visible_label', '')}' "
                f"last_resource_id='{overlay_row.get('focus_view_id', '')}' last_bounds='{overlay_row.get('focus_bounds', '')}' "
                f"last_fingerprint='{overlay_row_fingerprint}' post_label_seen={str(post_label_seen).lower()} "
                f"initial_candidate_saved={str(initial_candidate_saved).lower()}",
                level="DEBUG",
            )
            log(f"[OVERLAY][break] reason='{forced_overlay_break_reason}' step={overlay_step_idx}")
            if overlay_previous_row:
                overlay_previous_row["status"] = "END"
                overlay_previous_row["stop_reason"] = forced_overlay_break_reason
            save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
            break

        title_repeat_needs_rescue = bool(title_like_focus and overlay_title_repeat_streak >= 1 and not actionable_changed)
        if duplicate_overlay_row or seen_overlay_row or seen_actionable_row or title_repeat_needs_rescue:
            if rescue_pending:
                rescue_result = _move_overlay_next_once()
                overlay_duplicate_rescue_count += 1
                log(
                    f"[OVERLAY][rescue] duplicate_streak={overlay_duplicate_streak} "
                    f"rescue_count={overlay_duplicate_rescue_count}/{overlay_duplicate_rescue_budget} "
                    f"view_id='{overlay_row.get('focus_view_id', '')}' move_result='{rescue_result}'",
                    level="DEBUG",
                )
            log(
                f"[OVERLAY][dedup] skip_duplicate_row=true step={overlay_step_idx} "
                f"view_id='{overlay_row.get('focus_view_id', '')}' bounds='{overlay_row.get('focus_bounds', '')}' "
                f"move_result='{move_result}' duplicate_streak={overlay_duplicate_streak} seen_before={str(seen_overlay_row).lower()} "
                f"title_repeat_streak={overlay_title_repeat_streak} seen_actionable={str(seen_actionable_row).lower()} "
                f"advancement_fail_streak={overlay_advancement_fail_streak}"
            )
            continue

        overlay_row["_step_mono_start"] = time.monotonic() - float(overlay_row.get("t_step_start", 0.0) or 0.0)
        overlay_row = maybe_capture_focus_crop(client, dev, overlay_row, output_base_dir)
        overlay_row.pop("_step_mono_start", None)

        overlay_rows.append(overlay_row)
        rows.append(overlay_row)
        all_rows.append(overlay_row)
        if overlay_row_fingerprint:
            overlay_seen_fingerprints.add(overlay_row_fingerprint)
        if overlay_row_actionable_key and not title_like_focus:
            overlay_seen_actionable_keys.add(overlay_row_actionable_key)

        (
            should_end_overlay,
            overlay_fail_count,
            overlay_same_count,
            overlay_reason,
            overlay_prev_fingerprint,
            _,
        ) = should_stop(
            row=overlay_row,
            prev_fingerprint=overlay_prev_fingerprint,
            fail_count=overlay_fail_count,
            same_count=overlay_same_count,
            previous_row=overlay_previous_row,
        )
        if should_end_overlay:
            overlay_row["status"] = "END"
            overlay_row["stop_reason"] = overlay_reason
            save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
            break
        if overlay_step_idx % checkpoint_every == 0:
            save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
        overlay_previous_row = overlay_row

    recovery_anchor = str(entry_step.get("normalized_visible_label", "") or "").strip()
    scenario_anchor = str(tab_cfg.get("anchor_name", "") or "").strip()
    expected_anchor: str | None = recovery_anchor or scenario_anchor or None

    recovery_result = client.press_back_and_recover_focus(
        dev=dev,
        expected_parent_anchor=expected_anchor,
        wait_seconds=back_recovery_wait_seconds,
        retry=1,
    )
    recovery_status = str(recovery_result.get("status", "") or "")
    if recovery_status != "ok" and scenario_anchor:
        select_ok = client.select(
            dev=dev,
            name=scenario_anchor,
            type_=str(tab_cfg.get("anchor_type", "a") or "a"),
            wait_=3,
        )
        recovery_status = "ok_select_fallback" if select_ok else f"{recovery_status}_select_fallback_failed"

    if overlay_rows:
        overlay_rows[-1]["overlay_recovery_status"] = recovery_status
    save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
    return overlay_rows
