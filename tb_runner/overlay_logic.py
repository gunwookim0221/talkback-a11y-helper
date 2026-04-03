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
    OVERLAY_ENTRY_CANDIDATES,
    OVERLAY_MAX_STEPS,
    OVERLAY_REALIGN_MAX_STEPS,
    OVERLAY_STEP_WAIT_SECONDS,
)
from tb_runner.diagnostics import should_stop
from tb_runner.excel_report import save_excel
from tb_runner.image_utils import maybe_capture_focus_crop
from tb_runner.logging_utils import log
from tb_runner.perf_stats import ScenarioPerfStats, save_excel_with_perf
from tb_runner.utils import make_main_fingerprint

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
    entry_view_id = str(entry.get("resource_id", "") or "").strip()
    entry_label = str(entry.get("label", "") or "").strip().lower()
    if entry_view_id and focus_view_id == entry_view_id:
        return True
    return bool(entry_label and normalized_visible_label == entry_label)


def _get_overlay_policy_entries(tab_cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    policy = tab_cfg.get("overlay_policy")
    if isinstance(policy, dict):
        allow_candidates = list(policy.get("allow_candidates", []) or [])
        block_candidates = list(policy.get("block_candidates", []) or [])
        return allow_candidates, block_candidates, "scenario_policy"
    return OVERLAY_ENTRY_CANDIDATES, [], "global_candidates"


def is_overlay_candidate(step: dict[str, Any], tab_cfg: dict[str, Any]) -> tuple[bool, str]:
    allow_candidates, block_candidates, source = _get_overlay_policy_entries(tab_cfg)

    for entry in block_candidates:
        if _matches_overlay_candidate(step, entry):
            return False, f"blocked_by_{source}"

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
    current_bounds = str(current_step.get("focus_bounds", "") or "").strip()
    entry_bounds = str(entry_step.get("focus_bounds", "") or "").strip()
    if current_bounds and entry_bounds and current_bounds == entry_bounds:
        return "bounds"
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
    if seen_idx is None or seen_idx >= entry_idx:
        return {
            "status": "skip_realign_not_before_entry",
            "steps_taken": 0,
            "entry_reached": False,
            "current_step": current_step,
        }

    for realign_idx in range(1, OVERLAY_REALIGN_MAX_STEPS + 1):
        probe_step = collect_realign_probe(
            client=client,
            dev=dev,
            move=True,
            probe_idx=realign_idx,
            direction="next",
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
    overlay_prev_fingerprint = ("", "", "")
    overlay_previous_row: dict[str, Any] | None = None
    overlay_fail_count = 0
    overlay_same_count = 0
    for overlay_step_idx in range(1, OVERLAY_MAX_STEPS + 1):
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
        overlay_row["tab_name"] = tab_cfg["tab_name"]
        overlay_row["context_type"] = "overlay"
        overlay_row["parent_step_index"] = parent_step_index
        overlay_row["overlay_entry_label"] = entry_label
        overlay_row["overlay_recovery_status"] = ""
        overlay_row["status"] = "OK"
        overlay_row["stop_reason"] = ""
        overlay_row["crop_image"] = "IMAGE"
        overlay_row["_step_mono_start"] = time.monotonic() - float(overlay_row.get("t_step_start", 0.0) or 0.0)
        overlay_row = maybe_capture_focus_crop(client, dev, overlay_row, output_base_dir)
        overlay_row.pop("_step_mono_start", None)

        overlay_rows.append(overlay_row)
        rows.append(overlay_row)
        all_rows.append(overlay_row)

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
