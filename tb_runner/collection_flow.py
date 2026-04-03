import re
import time
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.anchor_logic import stabilize_anchor
from tb_runner.constants import (
    CHECKPOINT_SAVE_EVERY_STEPS,
    MAIN_ANNOUNCEMENT_WAIT_SECONDS,
    MAIN_STEP_WAIT_SECONDS,
)
from tb_runner.diagnostics import detect_step_mismatch, should_stop
from tb_runner.excel_report import save_excel
from tb_runner.image_utils import maybe_capture_focus_crop
from tb_runner.logging_utils import _should_log, log
from tb_runner.overlay_logic import (
    classify_post_click_result,
    expand_overlay,
    is_overlay_candidate,
    realign_focus_after_overlay,
)
from tb_runner.perf_stats import ScenarioPerfStats, format_perf_summary, save_excel_with_perf
from tb_runner.tab_logic import stabilize_tab_selection
from tb_runner.utils import make_main_fingerprint, make_overlay_entry_fingerprint

_VALID_SCREEN_CONTEXT_MODES = {"bottom_tab", "new_screen"}
_VALID_STABILIZATION_MODES = {"tab_context", "anchor_only", "anchor_then_context"}
_STRICT_MAIN_TAB_SCENARIOS = {"home_main", "devices_main", "life_main", "routines_main"}


def _resolve_screen_context_mode(tab_cfg: dict[str, Any]) -> str:
    raw_mode = str(tab_cfg.get("screen_context_mode", "bottom_tab") or "bottom_tab").strip().lower()
    if raw_mode in _VALID_SCREEN_CONTEXT_MODES:
        return raw_mode
    log(
        f"[SCENARIO][stabilization] invalid screen_context_mode='{raw_mode}' "
        f"scenario='{tab_cfg.get('scenario_id', '')}' fallback='bottom_tab'"
    )
    return "bottom_tab"


def _resolve_stabilization_mode(tab_cfg: dict[str, Any], screen_context_mode: str) -> str:
    raw_mode = str(tab_cfg.get("stabilization_mode", "") or "").strip().lower()
    if raw_mode in _VALID_STABILIZATION_MODES:
        return raw_mode
    if raw_mode:
        default_mode = "anchor_only" if screen_context_mode == "new_screen" else "anchor_then_context"
        log(
            f"[SCENARIO][stabilization] invalid stabilization_mode='{raw_mode}' "
            f"scenario='{tab_cfg.get('scenario_id', '')}' fallback='{default_mode}'"
        )
    if screen_context_mode == "new_screen":
        return "anchor_only"
    return "anchor_then_context"

def _get_retry_count(tab_cfg: dict[str, Any], key: str, fallback: int) -> int:
    value = tab_cfg.get(key, fallback)
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int) and value > 0:
        return value
    return fallback


def _get_wait_seconds(tab_cfg: dict[str, Any], key: str, fallback: float) -> float:
    value = tab_cfg.get(key, fallback)
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return fallback


def _run_pre_navigation_steps(client: A11yAdbClient, dev: str, tab_cfg: dict[str, Any]) -> bool:
    pre_navigation = tab_cfg.get("pre_navigation", [])
    if not isinstance(pre_navigation, list) or not pre_navigation:
        return True

    retry_count = _get_retry_count(tab_cfg, "pre_navigation_retry_count", 2)
    wait_seconds = _get_wait_seconds(tab_cfg, "pre_navigation_wait_seconds", MAIN_STEP_WAIT_SECONDS)

    for index, step in enumerate(pre_navigation, start=1):
        if not isinstance(step, dict):
            log(f"[SCENARIO][pre_nav] failed reason='invalid_step' step={index}")
            return False

        action = str(step.get("action", "") or "").strip().lower()
        target = str(step.get("target", "") or "").strip()
        type_ = str(step.get("type", "a") or "a").strip()
        if not action or not target:
            log(f"[SCENARIO][pre_nav] failed reason='invalid_step_config' step={index}")
            return False
        if action not in {
            "select",
            "touch",
            "touch_bounds_center",
            "select_and_click_focused",
            "tap_bounds_center_adb",
            "select_and_tap_bounds_center_adb",
        }:
            log(f"[SCENARIO][pre_nav] failed reason='unsupported_action' step={index} action='{action}'")
            return False

        log(f"[SCENARIO][pre_nav] step={index} action={action} target='{target}'")
        step_ok = False
        actual_reason = "unknown"
        for attempt in range(1, retry_count + 1):
            if action == "select":
                step_ok = bool(client.select(dev=dev, name=target, type_=type_, wait_=8))
            elif action == "touch":
                step_ok = bool(client.touch(dev=dev, name=target, type_=type_, wait_=8))
            elif action == "touch_bounds_center":
                step_ok = bool(client.touch_bounds_center(dev=dev, name=target, type_=type_, wait_=8))
            elif action == "tap_bounds_center_adb":
                dump_nodes = step.get("dump_tree_nodes", [])
                step_ok = bool(client.tap_bounds_center_adb(dev=dev, name=target, type_=type_, dump_nodes=dump_nodes))
                tap_result = getattr(client, "last_target_action_result", {}) if hasattr(client, "last_target_action_result") else {}
                if isinstance(tap_result, dict):
                    tap_target = tap_result.get("target", {})
                    bounds = str(tap_target.get("bounds", "") or "")
                    center = tap_target.get("center", {}) if isinstance(tap_target, dict) else {}
                    center_repr = ""
                    if isinstance(center, dict) and "x" in center and "y" in center:
                        center_repr = f"{center.get('x')},{center.get('y')}"
                    lazy_dump_used = bool(tap_target.get("lazy_dump_used")) if isinstance(tap_target, dict) else False
                    log(
                        f"[SCENARIO][pre_nav] action=tap_bounds_center_adb selector='{target}' type='{type_}' "
                        f"bounds='{bounds}' center='{center_repr}' lazy_dump_used={str(lazy_dump_used).lower()}"
                    )
            elif action == "select_and_tap_bounds_center_adb":
                tap_target = str(step.get("tap_target", target) or target).strip()
                tap_type = str(step.get("tap_type", type_) or type_).strip()
                select_ok = bool(client.select(dev=dev, name=target, type_=type_, wait_=8))
                if not select_ok:
                    step_ok = False
                else:
                    dump_nodes = step.get("dump_tree_nodes", [])
                    step_ok = bool(client.tap_bounds_center_adb(dev=dev, name=tap_target, type_=tap_type, dump_nodes=dump_nodes))
                    tap_result = getattr(client, "last_target_action_result", {}) if hasattr(client, "last_target_action_result") else {}
                    if isinstance(tap_result, dict):
                        tap_result_target = tap_result.get("target", {})
                        bounds = str(tap_result_target.get("bounds", "") or "")
                        center = tap_result_target.get("center", {}) if isinstance(tap_result_target, dict) else {}
                        center_repr = ""
                        if isinstance(center, dict) and "x" in center and "y" in center:
                            center_repr = f"{center.get('x')},{center.get('y')}"
                        lazy_dump_used = (
                            bool(tap_result_target.get("lazy_dump_used")) if isinstance(tap_result_target, dict) else False
                        )
                        log(
                            f"[SCENARIO][pre_nav] action=select_and_tap_bounds_center_adb select_target='{target}' select_type='{type_}' "
                            f"tap_target='{tap_target}' tap_type='{tap_type}' bounds='{bounds}' center='{center_repr}' "
                            f"lazy_dump_used={str(lazy_dump_used).lower()}"
                        )
            else:
                select_ok = bool(client.select(dev=dev, name=target, type_=type_, wait_=8))
                focus_confirmed = False
                if not select_ok:
                    for poll_idx in range(3):
                        last_result = getattr(client, "last_target_action_result", None) or {}
                        target_snapshot = last_result.get("target", {}) if isinstance(last_result, dict) else {}
                        focus_confirmed = bool(target_snapshot.get("accessibilityFocused")) if isinstance(target_snapshot, dict) else False
                        if focus_confirmed:
                            break
                        if poll_idx < 2:
                            time.sleep(0.12)
                    if focus_confirmed:
                        log("[SCENARIO][pre_nav] select returned false but accessibilityFocused=true; continuing with click_focused")
                    else:
                        log("[SCENARIO][pre_nav] select returned false and accessibilityFocused not confirmed")

                if select_ok or focus_confirmed:
                    step_ok = bool(client.click_focused(dev=dev, wait_=8))
                else:
                    step_ok = False

            result = getattr(client, "last_target_action_result", {})
            if isinstance(result, dict):
                actual_reason = str(result.get("reason", "unknown") or "unknown")
            else:
                actual_reason = "unknown"

            if step_ok:
                log(f"[SCENARIO][pre_nav] success step={index} reason='{actual_reason}'")
                break
            if attempt < retry_count:
                log(f"[SCENARIO][pre_nav] retry step={index} attempt={attempt}/{retry_count} reason='{actual_reason}'")

        if not step_ok:
            log(f"[SCENARIO][pre_nav] failed reason='action_failed' step={index}")
            log(f"[SCENARIO][pre_nav] failed reason='action_failed' detail='{actual_reason}' step={index}")
            return False

        client.collect_focus_step(
            dev=dev,
            step_index=-(700 + index),
            move=False,
            wait_seconds=wait_seconds,
            announcement_wait_seconds=wait_seconds,
        )
        time.sleep(wait_seconds)

    log("[SCENARIO][pre_nav] success")
    return True


def open_scenario(client: A11yAdbClient, dev: str, tab_cfg: dict) -> bool:
    tab_retry_count = _get_retry_count(tab_cfg, "tab_select_retry_count", 2)
    anchor_retry_count = _get_retry_count(tab_cfg, "anchor_retry_count", 2)
    main_step_wait_seconds = _get_wait_seconds(tab_cfg, "main_step_wait_seconds", MAIN_STEP_WAIT_SECONDS)
    screen_context_mode = _resolve_screen_context_mode(tab_cfg)
    stabilization_mode = _resolve_stabilization_mode(tab_cfg, screen_context_mode)
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    pre_navigation = tab_cfg.get("pre_navigation", [])
    has_pre_navigation = isinstance(pre_navigation, list) and bool(pre_navigation)
    is_transition_scenario = has_pre_navigation and (
        screen_context_mode == "new_screen" or stabilization_mode == "anchor_only"
    )
    is_strict_main_tab_scenario = scenario_id in _STRICT_MAIN_TAB_SCENARIOS
    log(
        f"[SCENARIO][stabilization] scenario='{scenario_id}' "
        f"screen_context_mode='{screen_context_mode}' stabilization_mode='{stabilization_mode}'"
    )

    tab_stabilize_cfg = tab_cfg
    if screen_context_mode == "new_screen":
        tab_stabilize_cfg = dict(tab_cfg)
        tab_stabilize_cfg["context_verify"] = {"type": "none"}
        log("[CONTEXT] skipped reason='new_screen_mode' phase='tab_select'")

    tab_stabilized = stabilize_tab_selection(
        client=client,
        dev=dev,
        tab_cfg=tab_stabilize_cfg,
        max_retries=tab_retry_count,
    )
    focus_align_result = tab_stabilized.get("focus_align", {}) if isinstance(tab_stabilized, dict) else {}
    focus_align_attempted = bool(focus_align_result.get("attempted"))
    focus_align_ok = bool(focus_align_result.get("ok"))
    if focus_align_attempted and not focus_align_ok:
        log(
            f"[TAB][focus_align] scenario='{scenario_id}' main_tab={str(is_strict_main_tab_scenario).lower()} "
            f"transition_scenario={str(is_transition_scenario).lower()} result='failed'"
        )
        if is_transition_scenario and not is_strict_main_tab_scenario:
            log(
                f"[TAB][focus_align] failed but proceeding (transition scenario) "
                f"scenario='{scenario_id}'"
            )
        elif is_strict_main_tab_scenario:
            log(f"[TAB][focus_align] strict failure scenario='{scenario_id}'")
            return False

    if not tab_stabilized.get("ok"):
        best = tab_stabilized.get("best", {}) if isinstance(tab_stabilized, dict) else {}
        best_score = int(best.get("score", 0) or 0) if isinstance(best, dict) else 0
        selected = bool(tab_stabilized.get("selected"))
        transition_fallback_ok = (
            is_transition_scenario
            and not is_strict_main_tab_scenario
            and selected
            and best_score > 0
        )
        if transition_fallback_ok:
            log(
                f"[TAB][select][warn] scenario='{scenario_id}' "
                "verify_failed_but_continue='transition_scenario' "
                f"selected={selected} score={best_score}"
            )
        else:
            log(f"[TAB][select] stabilization failed scenario='{scenario_id}'")
            return False

    time.sleep(main_step_wait_seconds)
    client.reset_focus_history(dev)
    time.sleep(0.5)

    pre_nav_ok = _run_pre_navigation_steps(client=client, dev=dev, tab_cfg=tab_cfg)
    if not pre_nav_ok:
        return False

    anchor_stabilize_cfg = dict(tab_cfg)
    anchor_stabilize_cfg["screen_context_mode"] = screen_context_mode
    anchor_stabilize_cfg["stabilization_mode"] = stabilization_mode

    stabilize_result = stabilize_anchor(
        client=client,
        dev=dev,
        tab_cfg=anchor_stabilize_cfg,
        phase="scenario_start",
        max_retries=anchor_retry_count,
        verify_reads=2,
    )
    if not stabilize_result.get("ok"):
        log(f"[ANCHOR][scenario_start] stabilization failed tab='{tab_cfg.get('tab_name', '')}'")
        return False
    time.sleep(main_step_wait_seconds)
    return True


def _get_positive_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int) and value > 0:
        return value
    return fallback


def open_tab_and_anchor(client: A11yAdbClient, dev: str, tab_cfg: dict) -> bool:
    return open_scenario(client, dev, tab_cfg)


def collect_tab_rows(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict,
    all_rows: list[dict],
    output_path: str,
    output_base_dir: str,
    scenario_perf: ScenarioPerfStats | None = None,
    checkpoint_save_every: int = CHECKPOINT_SAVE_EVERY_STEPS,
) -> list[dict]:
    rows: list[dict] = []
    main_step_wait_seconds = _get_wait_seconds(tab_cfg, "main_step_wait_seconds", MAIN_STEP_WAIT_SECONDS)
    main_announcement_wait_seconds = _get_wait_seconds(
        tab_cfg,
        "main_announcement_wait_seconds",
        MAIN_ANNOUNCEMENT_WAIT_SECONDS,
    )
    checkpoint_every = _get_positive_int(checkpoint_save_every, CHECKPOINT_SAVE_EVERY_STEPS)

    opened = open_scenario(client, dev, tab_cfg)
    if not opened:
        row = {
            "tab_name": tab_cfg["tab_name"],
            "step_index": -1,
            "status": "TAB_OPEN_FAILED",
            "stop_reason": "tab_or_anchor_failed",
            "crop_image": "",
            "crop_image_path": "",
            "crop_image_saved": False,
        }
        rows.append(row)
        all_rows.append(row)
        if scenario_perf is not None:
            scenario_perf.record_row(row)
            scenario_perf.finalize()
            log(format_perf_summary("scenario_summary", scenario_perf.summary_dict()))
        save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
        return rows

    anchor_start = time.perf_counter()
    anchor_row = client.collect_focus_step(
        dev=dev,
        step_index=0,
        move=False,
        wait_seconds=main_step_wait_seconds,
        announcement_wait_seconds=main_announcement_wait_seconds
    )
    anchor_elapsed = time.perf_counter() - anchor_start

    anchor_row["tab_name"] = tab_cfg["tab_name"]
    anchor_row["context_type"] = "main"
    anchor_row["parent_step_index"] = ""
    anchor_row["overlay_entry_label"] = ""
    anchor_row["overlay_recovery_status"] = ""
    anchor_row["status"] = "ANCHOR"
    anchor_row["stop_reason"] = ""
    anchor_row["step_elapsed_sec"] = round(anchor_elapsed, 3)
    anchor_row["crop_image"] = "IMAGE"
    anchor_row["_step_mono_start"] = time.monotonic() - float(anchor_row.get("t_step_start", 0.0) or 0.0)
    anchor_row = maybe_capture_focus_crop(client, dev, anchor_row, output_base_dir)
    anchor_row.pop("_step_mono_start", None)

    rows.append(anchor_row)
    all_rows.append(anchor_row)
    if scenario_perf is not None:
        scenario_perf.record_row(anchor_row)
    save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)

    prev_fingerprint = make_main_fingerprint(anchor_row)
    previous_step_row: dict[str, Any] | None = anchor_row
    fail_count = 0
    same_count = 0
    expanded_overlay_entries: set[str] = set()
    main_step_index_by_fingerprint: dict[tuple[str, str, str], int] = {
        prev_fingerprint: 0,
    }

    for step_idx in range(1, tab_cfg["max_steps"] + 1):
        log(f"[STEP] START tab='{tab_cfg['tab_name']}' step={step_idx}")
        step_start = time.perf_counter()

        row = client.collect_focus_step(
            dev=dev,
            step_index=step_idx,
            move=True,
            direction="next",
            wait_seconds=main_step_wait_seconds,
            announcement_wait_seconds=main_announcement_wait_seconds,
        )
        step_elapsed = time.perf_counter() - step_start

        row["tab_name"] = tab_cfg["tab_name"]
        row["context_type"] = "main"
        row["parent_step_index"] = ""
        row["overlay_entry_label"] = ""
        row["overlay_recovery_status"] = ""
        row["status"] = "OK"
        row["stop_reason"] = ""
        row["step_elapsed_sec"] = round(step_elapsed, 3)
        row["crop_image"] = "IMAGE"
        row["_step_mono_start"] = time.monotonic() - float(row.get("t_step_start", 0.0) or 0.0)
        row = maybe_capture_focus_crop(client, dev, row, output_base_dir)
        row.pop("_step_mono_start", None)
        row["step_total_elapsed_sec"] = round(time.perf_counter() - step_start, 3)

        move_result = str(row.get("move_result", "") or "")
        visible_label = str(row.get("visible_label", "") or "").strip()
        merged_announcement = str(row.get("merged_announcement", "") or "").strip()

        log(
            f"[STEP] END tab='{tab_cfg['tab_name']}' step={step_idx} "
            f"elapsed={step_elapsed:.2f}s move_result='{move_result}' "
            f"visible='{visible_label}' speech='{merged_announcement}' "
            f"crop='{row.get('crop_image_path', '')}' "
            f"timing(move={row.get('move_elapsed_sec', 0):.3f}s "
            f"ann={row.get('announcement_elapsed_sec', 0):.3f}s "
            f"get_focus={row.get('get_focus_elapsed_sec', 0):.3f}s "
            f"get_focus_fallback_dump={row.get('get_focus_fallback_dump_elapsed_sec', 0):.3f}s "
            f"step_dump={row.get('step_dump_tree_elapsed_sec', 0):.3f}s "
            f"crop={row.get('crop_elapsed_sec', 0):.3f}s total={row.get('step_total_elapsed_sec', 0):.3f}s) "
            f"focus_reason='{row.get('get_focus_empty_reason', '')}' "
            f"fallback_used={row.get('get_focus_fallback_used', False)} "
            f"fallback_found={row.get('get_focus_fallback_found', False)} "
            f"step_dump_used={row.get('step_dump_tree_used', False)} "
            f"step_dump_reason='{row.get('step_dump_tree_reason', '')}' "
            f"req_id='{row.get('get_focus_req_id', '')}'"
        )
        mismatch_reasons, low_confidence_reasons = detect_step_mismatch(row=row, previous_step=previous_step_row)
        if mismatch_reasons:
            log(
                f"[MISMATCH] step={step_idx} tab='{tab_cfg['tab_name']}' "
                f"reason='{','.join(mismatch_reasons)}' "
                f"speech='{merged_announcement}' visible='{visible_label}' "
                f"focus_bounds='{row.get('focus_bounds', '')}' source='{row.get('focus_payload_source', '')}'"
            )
        elif low_confidence_reasons:
            log(
                f"[LOW_CONFIDENCE] step={step_idx} tab='{tab_cfg['tab_name']}' "
                f"reason='{','.join(low_confidence_reasons)}' "
                f"speech='{merged_announcement}' visible='{visible_label}' "
                f"focus_bounds='{row.get('focus_bounds', '')}' source='{row.get('focus_payload_source', '')}'"
            )
        elif _should_log("DEBUG"):
            log(
                f"[DEBUG][diag] step={step_idx} speech_count={row.get('announcement_count', 0)} "
                f"window={row.get('announcement_window_sec', 0)} "
                f"focus_source='{row.get('focus_payload_source', '')}' "
                f"response_success={row.get('get_focus_response_success', False)} "
                f"t(after_move={row.get('t_after_move', 0)} "
                f"after_ann={row.get('t_after_ann', 0)} "
                f"after_focus={row.get('t_after_get_focus', 0)} "
                f"before_crop={row.get('t_before_crop', 0)} after_crop={row.get('t_after_crop', 0)})",
                level="DEBUG",
            )

        stop, fail_count, same_count, reason, prev_fingerprint = should_stop(
            row=row,
            prev_fingerprint=prev_fingerprint,
            fail_count=fail_count,
            same_count=same_count,
        )

        if stop:
            row["status"] = "END"
            row["stop_reason"] = reason

        rows.append(row)
        all_rows.append(row)
        if scenario_perf is not None:
            scenario_perf.record_row(row)
        row_fingerprint = make_main_fingerprint(row)
        if all(row_fingerprint):
            main_step_index_by_fingerprint[row_fingerprint] = step_idx
        if stop or (step_idx % checkpoint_every == 0):
            save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)

        is_candidate, candidate_reason = is_overlay_candidate(row, tab_cfg)
        if is_candidate:
            fingerprint = make_overlay_entry_fingerprint(tab_cfg["tab_name"], row)
            if fingerprint not in expanded_overlay_entries:
                log(
                    f"[OVERLAY] candidate matched scenario='{tab_cfg.get('scenario_id', '')}' "
                    f"tab='{tab_cfg.get('tab_name', '')}' step={row.get('step_index')} "
                    f"view_id='{row.get('focus_view_id', '')}' label='{row.get('visible_label', '')}' "
                    f"reason='{candidate_reason}'"
                )
                clicked = False
                row_view_id = str(row.get("focus_view_id", "") or "").strip()
                row_label = str(row.get("visible_label", "") or "").strip()
                if row_view_id:
                    clicked = client.touch(
                        dev=dev,
                        name=f"^{re.escape(row_view_id)}$",
                        type_="r",
                        wait_=3,
                    )
                elif row_label:
                    clicked = client.touch(
                        dev=dev,
                        name=f"^{re.escape(row_label)}$",
                        type_="a",
                        wait_=3,
                    )
                if not clicked:
                    log(
                        f"[OVERLAY] post_click classification='unchanged' scenario='{tab_cfg.get('scenario_id', '')}' "
                        f"tab='{tab_cfg.get('tab_name', '')}' step={row.get('step_index')} "
                        f"view_id='{row_view_id}' label='{row_label}' reason='entry_click_failed'"
                    )
                else:
                    time.sleep(0.8)
                    classification, post_click_step = classify_post_click_result(
                        client=client,
                        dev=dev,
                        tab_cfg=tab_cfg,
                        pre_click_step=row,
                    )
                    log(
                        f"[OVERLAY] post_click classification='{classification}' "
                        f"scenario='{tab_cfg.get('scenario_id', '')}' tab='{tab_cfg.get('tab_name', '')}' "
                        f"entry_view_id='{row_view_id}' entry_label='{row_label}' "
                        f"post_view_id='{post_click_step.get('focus_view_id', '')}' "
                        f"post_label='{post_click_step.get('visible_label', '')}'"
                    )

                    if classification == "overlay":
                        if scenario_perf is not None:
                            scenario_perf.overlay_count += 1
                        before_overlay_len = len(rows)
                        expand_overlay(
                            client=client,
                            dev=dev,
                            tab_cfg=tab_cfg,
                            entry_step=row,
                            rows=rows,
                            all_rows=all_rows,
                            output_path=output_path,
                            output_base_dir=output_base_dir,
                            skip_entry_click=True,
                            scenario_perf=scenario_perf,
                        )
                        if scenario_perf is not None:
                            for overlay_row in rows[before_overlay_len:]:
                                scenario_perf.record_row(overlay_row)
                        expanded_overlay_entries.add(fingerprint)

                        if scenario_perf is not None:
                            scenario_perf.realign_attempt_count += 1
                        realign_result = realign_focus_after_overlay(
                            client=client,
                            dev=dev,
                            entry_step=row,
                            known_step_index_by_fingerprint=main_step_index_by_fingerprint,
                            tab_cfg=tab_cfg,
                        )
                        if scenario_perf is not None and bool(realign_result.get("entry_reached")):
                            scenario_perf.realign_success_count += 1
                        log(
                            f"[OVERLAY] realign status='{realign_result.get('status')}' "
                            f"entry_reached={realign_result.get('entry_reached')} "
                            f"steps_taken={realign_result.get('steps_taken')} "
                            f"match_by='{realign_result.get('match_by', '')}'"
                        )
                        if realign_result.get("entry_reached"):
                            post_overlay_stabilized = stabilize_anchor(
                                client=client,
                                dev=dev,
                                tab_cfg=tab_cfg,
                                phase="overlay_realign",
                                max_retries=_get_retry_count(tab_cfg, "anchor_retry_count", 2),
                                verify_reads=1,
                            )
                            if not post_overlay_stabilized.get("ok"):
                                log(
                                    f"[ANCHOR][overlay_realign] stabilization failed "
                                    f"tab='{tab_cfg.get('tab_name', '')}'"
                                )
                    elif classification == "navigation":
                        log(
                            f"[OVERLAY] overlay routine skipped (navigation) scenario='{tab_cfg.get('scenario_id', '')}' "
                            f"step={row.get('step_index')}"
                        )
                    else:
                        log(
                            f"[OVERLAY] overlay routine skipped (unchanged) scenario='{tab_cfg.get('scenario_id', '')}' "
                            f"step={row.get('step_index')}"
                        )
            else:
                log(f"[OVERLAY] skip already expanded entry fingerprint='{fingerprint}'")
        elif "blocked" in candidate_reason:
            log(
                f"[OVERLAY] blocked by scenario policy scenario='{tab_cfg.get('scenario_id', '')}' "
                f"tab='{tab_cfg.get('tab_name', '')}' step={row.get('step_index')} "
                f"view_id='{row.get('focus_view_id', '')}' label='{row.get('visible_label', '')}'"
            )

        if stop:
            log(f"[INFO] stop tab={tab_cfg['tab_name']} step={step_idx} reason={reason}")
            break
        previous_step_row = row

    if scenario_perf is not None:
        scenario_perf.finalize()
        log(format_perf_summary("scenario_summary", scenario_perf.summary_dict()))

    return rows
