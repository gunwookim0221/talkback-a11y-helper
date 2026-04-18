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

    def _pick_first_overlay_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        ranked_candidates: list[tuple[int, dict[str, Any]]] = []
        for idx, candidate in enumerate(candidates):
            prepared = _prepare_overlay_row(candidate, next_overlay_step_idx)
            if not _is_valid_first_overlay_row(prepared):
                continue
            has_view_id = bool(str(prepared.get("focus_view_id", "") or "").strip())
            has_label = bool(str(prepared.get("visible_label", "") or "").strip())
            has_speech = bool(str(prepared.get("merged_announcement", "") or "").strip())
            rank = 0
            if has_label:
                rank += 4
            if has_view_id:
                rank += 2
            if has_speech:
                rank += 1
            rank += max(0, 4 - idx)
            ranked_candidates.append((rank, prepared))
        if not ranked_candidates:
            return None
        ranked_candidates.sort(key=lambda item: item[0], reverse=True)
        return ranked_candidates[0][1]

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
    first_row = _pick_first_overlay_candidate(first_candidates)
    if first_row is not None:
        first_row.setdefault("move_result", "post_click_probe")
        _save_overlay_row(first_row, next_overlay_step_idx)
        overlay_previous_row = overlay_rows[-1]
        next_overlay_step_idx += 1
        first_saved = True

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
        if move_result.startswith("failed"):
            log(f"[OVERLAY][break] reason='move_failed' step={overlay_step_idx}")
            if overlay_previous_row:
                overlay_previous_row["status"] = "END"
                overlay_previous_row["stop_reason"] = "overlay_move_failed"
            save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
            break

        if _is_title_like_row(overlay_row):
            log(f"[OVERLAY][skip_title] step={overlay_step_idx} resource_id='{overlay_row.get('focus_view_id', '')}'", level="DEBUG")
            continue

        overlay_fp = build_row_fingerprint(overlay_row)
        if not overlay_fp:
            duplicate_streak += 1
            if duplicate_streak >= 3 and overlay_previous_row:
                overlay_previous_row["status"] = "END"
                overlay_previous_row["stop_reason"] = "overlay_duplicate_streak"
                save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
                break
            continue
        if overlay_fp in overlay_seen_fingerprints:
            duplicate_streak += 1
            if duplicate_streak >= 3:
                if overlay_previous_row:
                    overlay_previous_row["status"] = "END"
                    overlay_previous_row["stop_reason"] = "overlay_duplicate_streak"
                log(f"[OVERLAY][break] reason='duplicate_streak' step={overlay_step_idx} streak={duplicate_streak}")
                save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
                break
            log(
                f"[OVERLAY][dedup] skip_duplicate_row=true step={overlay_step_idx} fp='{overlay_fp}' streak={duplicate_streak}",
                level="DEBUG",
            )
            continue

        duplicate_streak = 0
        _save_overlay_row(overlay_row, overlay_step_idx)
        overlay_previous_row = overlay_rows[-1]

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
