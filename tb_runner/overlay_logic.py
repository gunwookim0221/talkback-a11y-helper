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
from tb_runner.diagnostics import is_placeholder_row
from tb_runner.excel_report import save_excel
from tb_runner.image_utils import maybe_capture_focus_crop
from tb_runner.logging_utils import log
from tb_runner.perf_stats import ScenarioPerfStats, save_excel_with_perf
from tb_runner.utils import build_row_fingerprint, make_main_fingerprint


OVERLAY_REALIGN_ROBUSTNESS_VERSION = "pr14-a-realign-robustness-v3"
OVERLAY_TRAVERSAL_CORE_VERSION = "pr70-overlay-traversal-core-v2"
OVERLAY_FIRST_ROW_DEBUG_VERSION = "pr70-overlay-first-row-debug-v3"


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
    overlay_previous_row: dict[str, Any] | None = None
    overlay_seen_fingerprints: set[str] = set()
    duplicate_streak = 0
    loop_break_reason = ""
    duplicate_break_reached = False

    def _to_boolish(value: Any) -> bool:
        return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y"}

    def _is_title_like_row(row: dict[str, Any]) -> bool:
        view_id = str(row.get("focus_view_id", "") or "").strip().lower()
        class_name = str(
            row.get("focus_class_name", "") or row.get("class_name", "") or row.get("className", "") or ""
        ).strip().lower()
        clickable = _to_boolish(row.get("focus_clickable", "") or row.get("clickable", ""))
        return bool(
            "title" in view_id and "textview" in class_name and not clickable
        )

    def _is_valid_first_overlay_row(row: dict[str, Any]) -> bool:
        has_payload = bool(
            str(row.get("visible_label", "") or "").strip()
            or str(row.get("merged_announcement", "") or "").strip()
        )
        if not has_payload or is_placeholder_row(row):
            return False
        row_context = str(row.get("context_type", "") or "").strip()
        row_overlay_label = str(row.get("overlay_entry_label", "") or "").strip()
        return row_context == "overlay" and row_overlay_label == entry_label

    def _pick_first_overlay_candidate(
        candidates: list[dict[str, Any]],
        post_click_row: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        rejected_reasons: list[str] = []
        candidate_debug_parts: list[str] = []
        for idx, candidate in enumerate(candidates):
            prepared = _prepare_overlay_row(candidate, next_overlay_step_idx)
            visible_label = str(prepared.get("visible_label", "") or "").strip()
            merged_announcement = str(prepared.get("merged_announcement", "") or "").strip()
            resource_id = str(prepared.get("focus_view_id", "") or "").strip()
            bounds = str(prepared.get("focus_bounds", "") or "").strip()
            class_name = str(prepared.get("focus_class_name", "") or prepared.get("class_name", "") or "").strip()
            clickable = _to_boolish(prepared.get("focus_clickable", "") or prepared.get("clickable", ""))
            placeholder = is_placeholder_row(prepared)
            row_context = str(prepared.get("context_type", "") or "").strip()
            row_overlay_label = str(prepared.get("overlay_entry_label", "") or "").strip()
            overlay_context_match = row_context == "overlay" and row_overlay_label == entry_label
            has_payload = bool(visible_label or merged_announcement)
            if not has_payload or placeholder or not overlay_context_match:
                if not has_payload:
                    rejected_reasons.append(f"candidate#{idx}:no_payload")
                elif placeholder:
                    rejected_reasons.append(f"candidate#{idx}:placeholder")
                else:
                    rejected_reasons.append(f"candidate#{idx}:overlay_context_mismatch")
                candidate_debug_parts.append(
                    f"candidate#{idx}(visible='{visible_label}',speech='{merged_announcement}',resource_id='{resource_id}',"
                    f"bounds='{bounds}',class_name='{class_name}',clickable={str(clickable).lower()},"
                    f"overlay_context_match={str(overlay_context_match).lower()},placeholder={str(placeholder).lower()},"
                    "score=0,chosen=false,why='invalid')"
                )
                continue
            candidate_debug_parts.append(
                f"candidate#{idx}(visible='{visible_label}',speech='{merged_announcement}',resource_id='{resource_id}',"
                f"bounds='{bounds}',class_name='{class_name}',clickable={str(clickable).lower()},"
                f"overlay_context_match={str(overlay_context_match).lower()},placeholder={str(placeholder).lower()},"
                "chosen=false,why='valid_priority_candidate')"
            )
            selected_row = prepared
            selected_fp = build_row_fingerprint(selected_row)
            log(
                f"[OVERLAY][first_row_pick] scenario='{tab_cfg.get('tab_name', '')}' post_label='{entry_label}' "
                f"candidate_count={len(candidates)} selected=true selected_visible='{selected_row.get('visible_label', '')}' "
                f"selected_speech='{selected_row.get('merged_announcement', '')}' "
                f"selected_resource_id='{selected_row.get('focus_view_id', '')}' "
                f"selected_bounds='{selected_row.get('focus_bounds', '')}' selected_fp='{selected_fp}' "
                f"selected_source='candidate#{idx}' candidates=[{'; '.join(candidate_debug_parts)}] "
                f"debug='{OVERLAY_FIRST_ROW_DEBUG_VERSION}'",
                level="DEBUG",
            )
            return selected_row

        if isinstance(post_click_row, dict):
            post_label = str(post_click_row.get("visible_label", "") or "").strip()
            post_speech = str(post_click_row.get("merged_announcement", "") or "").strip()
            if post_label or post_speech:
                synthetic_row = dict(post_click_row)
                synthetic_row["visible_label"] = post_label or post_speech
                synthetic_row["merged_announcement"] = post_speech or synthetic_row["visible_label"]
                synthetic_row["focus_view_id"] = str(synthetic_row.get("focus_view_id", "") or "").strip() or "synthetic:post_label_only"
                synthetic_row["focus_bounds"] = (
                    str(synthetic_row.get("focus_bounds", "") or "").strip()
                    or str(entry_step.get("focus_bounds", "") or "").strip()
                )
                synthetic_row = _prepare_overlay_row(synthetic_row, next_overlay_step_idx)
                if _is_valid_first_overlay_row(synthetic_row):
                    selected_fp = build_row_fingerprint(synthetic_row)
                    log(
                        f"[OVERLAY][first_row_pick] scenario='{tab_cfg.get('tab_name', '')}' post_label='{entry_label}' "
                        f"candidate_count={len(candidates)} selected=true selected_visible='{synthetic_row.get('visible_label', '')}' "
                        f"selected_speech='{synthetic_row.get('merged_announcement', '')}' "
                        f"selected_resource_id='{synthetic_row.get('focus_view_id', '')}' "
                        f"selected_bounds='{synthetic_row.get('focus_bounds', '')}' selected_fp='{selected_fp}' "
                        "selected_source='synthetic_post_label_only' "
                        f"candidates=[{'; '.join(candidate_debug_parts)}] rejected=[{', '.join(rejected_reasons)}] "
                        f"debug='{OVERLAY_FIRST_ROW_DEBUG_VERSION}'",
                        level="DEBUG",
                    )
                    return synthetic_row

        log(
            f"[OVERLAY][first_row_pick] scenario='{tab_cfg.get('tab_name', '')}' post_label='{entry_label}' "
            f"candidate_count={len(candidates)} selected=false reason='no_valid_candidate' "
            f"candidates=[{'; '.join(candidate_debug_parts)}] rejected=[{', '.join(rejected_reasons)}] "
            f"debug='{OVERLAY_FIRST_ROW_DEBUG_VERSION}'",
            level="DEBUG",
        )
        return None

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

    def _save_overlay_row(row: dict[str, Any], step_index: int) -> None:
        row["_step_mono_start"] = time.monotonic() - float(row.get("t_step_start", 0.0) or 0.0)
        row_with_crop = maybe_capture_focus_crop(client, dev, row, output_base_dir)
        row_with_crop.pop("_step_mono_start", None)
        overlay_rows.append(row_with_crop)
        rows.append(row_with_crop)
        all_rows.append(row_with_crop)
        overlay_fp = build_row_fingerprint(row_with_crop)
        if overlay_fp:
            overlay_seen_fingerprints.add(overlay_fp)
        log(
            f"[OVERLAY][save] step={step_index} fp='{overlay_fp}' visible='{row_with_crop.get('visible_label', '')}' "
            f"resource_id='{row_with_crop.get('focus_view_id', '')}' core='{OVERLAY_TRAVERSAL_CORE_VERSION}'",
            level="DEBUG",
        )

    next_overlay_step_idx = 1
    first_candidates: list[dict[str, Any]] = []
    post_click_step: dict[str, Any] | None = None
    if isinstance(initial_overlay_step, dict):
        first_candidates.append(dict(initial_overlay_step))
    if not skip_entry_click:
        post_click_step = client.collect_focus_step(
            dev=dev,
            step_index=next_overlay_step_idx,
            move=False,
            wait_seconds=overlay_step_wait_seconds,
            announcement_wait_seconds=overlay_announcement_wait_seconds,
            announcement_idle_wait_seconds=overlay_announcement_idle_wait_seconds,
            announcement_max_extra_wait_seconds=overlay_announcement_max_extra_wait_seconds,
        )
        first_candidates.append(post_click_step)

    first_saved = False
    first_selected = False
    first_row_saved_fp = ""
    first_row_saved_snapshot: dict[str, str] = {}
    first_row: dict[str, Any] | None = None
    if isinstance(post_click_step, dict):
        post_label = str(post_click_step.get("visible_label", "") or "").strip()
        post_speech = str(post_click_step.get("merged_announcement", "") or "").strip()
        post_view_id = str(post_click_step.get("focus_view_id", "") or "").strip()
        if (post_label or post_speech) and not post_view_id:
            first_selected = True
            first_row = _prepare_overlay_row(dict(post_click_step), next_overlay_step_idx)
            first_row["visible_label"] = post_label or post_speech
            first_row["merged_announcement"] = post_speech or first_row["visible_label"]
            first_row["focus_view_id"] = ""
            first_row["focus_bounds"] = (
                str(first_row.get("focus_bounds", "") or "").strip()
                or str(entry_step.get("focus_bounds", "") or "").strip()
            )
            first_row.setdefault("move_result", "post_click_probe")
            _save_overlay_row(first_row, next_overlay_step_idx)
            overlay_previous_row = overlay_rows[-1]
            first_row_saved_fp = build_row_fingerprint(overlay_previous_row)
            first_row_saved_snapshot = {
                "visible": str(overlay_previous_row.get("visible_label", "") or "").strip(),
                "resource_id": str(overlay_previous_row.get("focus_view_id", "") or "").strip(),
                "bounds": str(overlay_previous_row.get("focus_bounds", "") or "").strip(),
                "fingerprint": first_row_saved_fp,
            }
            next_overlay_step_idx += 1
            first_saved = True
            log(
                f"[OVERLAY][first_row_pick] scenario='{tab_cfg.get('tab_name', '')}' post_label='{entry_label}' "
                "candidate_count=0 selected=true selected_source='immediate_post_label_only_append' "
                f"selected_visible='{first_row_saved_snapshot.get('visible', '')}' "
                f"selected_speech='{str((overlay_previous_row or {}).get('merged_announcement', '') or '').strip()}' "
                f"selected_resource_id='{first_row_saved_snapshot.get('resource_id', '')}' "
                f"selected_bounds='{first_row_saved_snapshot.get('bounds', '')}' "
                f"selected_fp='{first_row_saved_snapshot.get('fingerprint', '')}' "
                f"debug='{OVERLAY_FIRST_ROW_DEBUG_VERSION}'",
                level="DEBUG",
            )

    if not first_saved:
        first_row = _pick_first_overlay_candidate(first_candidates, post_click_step)
        first_selected = first_row is not None
    log(
        f"[OVERLAY][first_row_save_attempt] scenario='{tab_cfg.get('tab_name', '')}' "
        f"selected={str(first_selected).lower()} visible='{str((first_row or {}).get('visible_label', '') or '').strip()}' "
        f"speech='{str((first_row or {}).get('merged_announcement', '') or '').strip()}' "
        f"resource_id='{str((first_row or {}).get('focus_view_id', '') or '').strip()}' "
        f"bounds='{str((first_row or {}).get('focus_bounds', '') or '').strip()}' "
        f"title_skip_applied=false dedup_applied=false append_attempted={str(first_selected).lower()} "
        f"append_allowed={str(first_selected).lower()} "
        f"save_block_reason='{'no_selected_candidate' if not first_selected else ''}' "
        f"debug='{OVERLAY_FIRST_ROW_DEBUG_VERSION}'",
        level="DEBUG",
    )
    if first_row is not None and not first_saved:
        first_row.setdefault("move_result", "post_click_probe")
        _save_overlay_row(first_row, next_overlay_step_idx)
        overlay_previous_row = overlay_rows[-1]
        first_row_saved_fp = build_row_fingerprint(overlay_previous_row)
        first_row_saved_snapshot = {
            "visible": str(overlay_previous_row.get("visible_label", "") or "").strip(),
            "resource_id": str(overlay_previous_row.get("focus_view_id", "") or "").strip(),
            "bounds": str(overlay_previous_row.get("focus_bounds", "") or "").strip(),
            "fingerprint": first_row_saved_fp,
        }
        next_overlay_step_idx += 1
        first_saved = True
    log(
        f"[OVERLAY][first_row_saved] scenario='{tab_cfg.get('tab_name', '')}' saved={str(first_saved).lower()} "
        f"saved_step_index={next_overlay_step_idx - 1 if first_saved else 0} "
        f"visible='{first_row_saved_snapshot.get('visible', '')}' "
        f"speech='{str((overlay_previous_row or {}).get('merged_announcement', '') or '').strip() if first_saved else ''}' "
        f"resource_id='{first_row_saved_snapshot.get('resource_id', '')}' bounds='{first_row_saved_snapshot.get('bounds', '')}' "
        f"fingerprint='{first_row_saved_snapshot.get('fingerprint', '')}' total_overlay_rows_after_save={len(overlay_rows)} "
        f"overlay_seen_fingerprints_size={len(overlay_seen_fingerprints)} debug='{OVERLAY_FIRST_ROW_DEBUG_VERSION}'",
        level="DEBUG",
    )

    log(
        f"[OVERLAY][first_row] scenario='{tab_cfg.get('tab_name', '')}' saved={str(first_saved).lower()} "
        f"entry='{entry_label}' core='{OVERLAY_TRAVERSAL_CORE_VERSION}'",
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
        move_result = str(overlay_row.get("move_result", "") or "").strip().lower()
        current_overlay_fp = build_row_fingerprint(overlay_row)
        skip_duplicate_row = False
        title_node = False
        if move_result.startswith("failed"):
            log(f"[OVERLAY][break] reason='move_failed' step={overlay_step_idx}")
            if overlay_previous_row:
                overlay_previous_row["status"] = "END"
                overlay_previous_row["stop_reason"] = "overlay_move_failed"
            loop_break_reason = "move_failed"
            save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
            break

        if _is_title_like_row(overlay_row):
            title_node = True
            log(f"[OVERLAY][skip_title] step={overlay_step_idx} resource_id='{overlay_row.get('focus_view_id', '')}'", level="DEBUG")
        else:
            if not current_overlay_fp:
                duplicate_streak += 1
                if duplicate_streak >= 3 and overlay_previous_row:
                    overlay_previous_row["status"] = "END"
                    overlay_previous_row["stop_reason"] = "overlay_duplicate_streak"
                    duplicate_break_reached = True
                    loop_break_reason = "duplicate_streak_empty_fingerprint"
                    save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
                    break
            elif current_overlay_fp in overlay_seen_fingerprints:
                skip_duplicate_row = True
                duplicate_streak += 1
                if duplicate_streak >= 3:
                    if overlay_previous_row:
                        overlay_previous_row["status"] = "END"
                        overlay_previous_row["stop_reason"] = "overlay_duplicate_streak"
                    duplicate_break_reached = True
                    loop_break_reason = "duplicate_streak"
                    log(f"[OVERLAY][break] reason='duplicate_streak' step={overlay_step_idx} streak={duplicate_streak}")
                    save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
                    break
                log(
                    f"[OVERLAY][dedup] skip_duplicate_row=true step={overlay_step_idx} fp='{current_overlay_fp}' streak={duplicate_streak}",
                    level="DEBUG",
                )
            else:
                duplicate_streak = 0
                _save_overlay_row(overlay_row, overlay_step_idx)
                overlay_previous_row = overlay_rows[-1]

        if first_saved and overlay_step_idx <= (next_overlay_step_idx + 1):
            first_row_preserved = bool(
                overlay_rows
                and build_row_fingerprint(overlay_rows[0]) == first_row_saved_snapshot.get("fingerprint", "")
            )
            log(
                f"[OVERLAY][post_first_loop_compare] scenario='{tab_cfg.get('tab_name', '')}' "
                f"just_saved_first_row_visible='{first_row_saved_snapshot.get('visible', '')}' "
                f"just_saved_first_row_resource_id='{first_row_saved_snapshot.get('resource_id', '')}' "
                f"just_saved_first_row_bounds='{first_row_saved_snapshot.get('bounds', '')}' "
                f"just_saved_first_row_fingerprint='{first_row_saved_snapshot.get('fingerprint', '')}' "
                f"current_loop_row_visible='{overlay_row.get('visible_label', '')}' "
                f"current_loop_row_resource_id='{overlay_row.get('focus_view_id', '')}' "
                f"current_loop_row_bounds='{overlay_row.get('focus_bounds', '')}' "
                f"current_loop_row_fingerprint='{current_overlay_fp}' "
                f"same_fingerprint={str(first_row_saved_fp == current_overlay_fp and bool(current_overlay_fp)).lower()} "
                f"skip_duplicate_row={str(skip_duplicate_row).lower()} title_node={str(title_node).lower()} "
                f"duplicate_streak={duplicate_streak} first_row_preserved={str(first_row_preserved).lower()} "
                f"debug='{OVERLAY_FIRST_ROW_DEBUG_VERSION}'",
                level="DEBUG",
            )

        if title_node or skip_duplicate_row or not current_overlay_fp:
            continue

        if overlay_step_idx % checkpoint_every == 0:
            save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)

    if not overlay_rows:
        log(
            f"[OVERLAY][warn] no_overlay_rows_collected entry='{entry_label}' core='{OVERLAY_TRAVERSAL_CORE_VERSION}'",
            level="DEBUG",
        )
    elif overlay_rows[-1].get("status", "") != "END":
        if duplicate_streak >= 3:
            overlay_rows[-1]["status"] = "END"
            overlay_rows[-1]["stop_reason"] = "overlay_duplicate_streak"
        elif overlay_rows[-1].get("stop_reason", "") == "":
            overlay_rows[-1]["status"] = "END"
            overlay_rows[-1]["stop_reason"] = "overlay_max_steps"

    if checkpoint_every > 0 and overlay_rows and (len(overlay_rows) % checkpoint_every == 0):
        save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
    if not loop_break_reason:
        loop_break_reason = str((overlay_rows[-1].get("stop_reason", "") if overlay_rows else "") or "completed")
    log(
        f"[OVERLAY][first_row_summary] scenario='{tab_cfg.get('tab_name', '')}' "
        f"first_row_selected={str(first_selected).lower()} first_row_saved={str(first_saved).lower()} "
        f"first_row_visible='{first_row_saved_snapshot.get('visible', '')}' distinct_overlay_rows_saved={len(overlay_rows)} "
        f"duplicate_break_reached={str(duplicate_break_reached).lower()} break_reason='{loop_break_reason}' "
        f"debug='{OVERLAY_FIRST_ROW_DEBUG_VERSION}'",
        level="DEBUG",
    )

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
