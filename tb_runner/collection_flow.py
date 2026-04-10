import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.anchor_logic import stabilize_anchor
from tb_runner.constants import (
    CHECKPOINT_SAVE_EVERY_STEPS,
    MAIN_ANNOUNCEMENT_WAIT_SECONDS,
    MAIN_STEP_WAIT_SECONDS,
)
from tb_runner.diagnostics import detect_step_mismatch, should_stop
from tb_runner.diagnostics import is_global_nav_row
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
from tb_runner.utils import (
    _safe_regex_search,
    build_row_fingerprint,
    build_row_semantic_fingerprint,
    is_noise_row,
    make_main_fingerprint,
    make_overlay_entry_fingerprint,
    parse_bounds_str,
)

_VALID_SCREEN_CONTEXT_MODES = {"bottom_tab", "new_screen"}
_VALID_STABILIZATION_MODES = {"tab_context", "anchor_only", "anchor_then_context"}
_STRICT_MAIN_TAB_SCENARIOS = {"home_main", "devices_main", "life_main", "routines_main"}
_TRANSITION_FAST_STEP_WAIT_SECONDS = 0.25
_TRANSITION_FAST_ANNOUNCEMENT_WAIT_SECONDS = 0.2
_TRANSITION_FAST_FOCUS_WAIT_SECONDS = 0.8
_TRANSITION_FAST_ACTION_WAIT_SECONDS = 2
_PRE_NAV_CONFIRM_POLL_SLEEP_SECONDS = 0.12
_RECENT_DUPLICATE_WINDOW = 5
_STALL_ESCAPE_SAME_LIKE_THRESHOLD = 6
_STALL_ESCAPE_SEMANTIC_UNIQUE_MAX = 2
_PLUGIN_ENTRY_RETRY_COUNT = 2
_PLUGIN_TOP_VERIFY_RETRY_COUNT = 2
_LIFE_ROOT_APP_BAR_MIN_HITS = 2
_LIFE_ROOT_VISIBLE_CARD_MIN_HITS = 2
_LIFE_ROOT_SCORE_THRESHOLD = 3
_LIFE_ROOT_TRANSIENT_RECHECK_COUNT = 2
_LIFE_ROOT_TRANSIENT_RECHECK_SLEEP_SECONDS = 0.12
_PLUGIN_SCROLL_SEARCH_MAX_STEPS = 5
_LIFE_ENERGY_SCENARIO_ID = "life_energy_plugin"
_LIFE_ENERGY_FAMILY_CARE_REGEX = r"(?i)\b(family\s*care|add\s*family\s*member|me)\b"
_LIFE_ENERGY_NAVIGATE_UP_REGEX = r"(?i)^navigate\s*up$"
COLLECTION_FLOW_DECISION_DATA_VERSION = "pr6-phase-context-v1"
COLLECTION_FLOW_GUARD_VERSION = "life-energy-entry-recheck-v4"
COLLECTION_FLOW_OVERLAY_SEAM_VERSION = "pr14-overlay-realign-robustness-v2"




@dataclass
class MainLoopState:
    last_fingerprint: str
    fingerprint_repeat_count: int
    previous_step_row: dict[str, Any]
    prev_fingerprint: tuple[str, str, str]
    fail_count: int
    same_count: int
    expanded_overlay_entries: set[str]
    post_realign_pending_steps: int
    main_step_index_by_fingerprint: dict[tuple[str, str, str], int]
    recent_fingerprint_history: deque[tuple[int, str]]
    recent_semantic_fingerprint_history: deque[tuple[int, str]]
    stop_triggered: bool
    stop_reason: str
    stop_step: int
    stall_escape_attempted: bool


@dataclass
class CollectionPhaseContext:
    tab_cfg: dict[str, Any]
    rows: list[dict[str, Any]]
    all_rows: list[dict[str, Any]]
    output_path: str
    output_base_dir: str
    scenario_perf: ScenarioPerfStats | None
    checkpoint_every: int
    main_step_wait_seconds: float
    main_announcement_wait_seconds: float
    main_announcement_idle_wait_seconds: float
    main_announcement_max_extra_wait_seconds: float
    state: MainLoopState

@dataclass
class StartPipelineResult:
    success: bool
    failure_reason: str
    stabilization_mode: str
    context_ok: bool
    anchor_matched: bool
    anchor_stable: bool
    focus_align_attempted: bool
    focus_align_ok: bool
    focus_align_reason: str
    pre_navigation_attempted: bool
    pre_navigation_success: bool
    open_completed: bool
    post_open_focus_collected: bool
    should_enter_main_loop: bool
    start_row: dict[str, Any] | None
    needs_open_failed_row: bool
    anchor_fingerprint: str
    anchor_repeat_count: int
    prev_fingerprint: tuple[str, str, str]
    recent_fingerprint_history: deque[tuple[int, str]]
    recent_semantic_fingerprint_history: deque[tuple[int, str]]


@dataclass
class OverlayPhaseResult:
    candidate_checked: bool
    candidate_reason: str
    classification: str
    post_realign_pending_steps_delta: int


def _is_plugin_anchor_only_new_screen(tab_cfg: dict[str, Any], *, screen_context_mode: str, stabilization_mode: str) -> bool:
    scenario_id = str(tab_cfg.get("scenario_id", "") or "").strip().lower()
    pre_navigation = tab_cfg.get("pre_navigation", [])
    has_scrolltouch = isinstance(pre_navigation, list) and any(
        str(step.get("action", "") or "").strip().lower().replace("-", "").replace("_", "") == "scrolltouch"
        for step in pre_navigation
        if isinstance(step, dict)
    )
    return (
        screen_context_mode == "new_screen"
        and stabilization_mode == "anchor_only"
        and "plugin" in scenario_id
        and has_scrolltouch
    )


def _node_is_visible(node: dict[str, Any]) -> bool:
    if "visibleToUser" in node:
        return bool(node.get("visibleToUser"))
    if "isVisibleToUser" in node:
        return bool(node.get("isVisibleToUser"))
    return True


def _node_label_blob(node: dict[str, Any]) -> str:
    return " ".join(
        [
            str(node.get("text", "") or "").strip(),
            str(node.get("contentDescription", "") or "").strip(),
            str(node.get("talkbackLabel", "") or "").strip(),
            str(node.get("label", "") or "").strip(),
        ]
    ).strip()


def _iter_tree_nodes_with_parent(nodes: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    flat: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    stack: list[tuple[Any, dict[str, Any] | None]] = [(node, None) for node in reversed(nodes)]
    while stack:
        node, parent = stack.pop()
        if not isinstance(node, dict):
            continue
        flat.append((node, parent))
        children = node.get("children")
        if isinstance(children, list):
            for child in reversed(children):
                stack.append((child, node))
    return flat


def _life_root_state_snapshot(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(nodes, list):
        nodes = []
    flat_nodes = _iter_tree_nodes_with_parent(nodes)
    app_bar_hits = 0
    life_selected = False
    visible_card_hits = 0
    life_root_signature_present = False
    bottom_nav_life_visible = False
    service_title_hits = 0
    description_hits = 0
    structure_hits = 0
    navigate_up_hits = 0
    life_service_titles = {"food", "energy", "air care", "home care", "pet care"}
    life_description_contains = (
        "energy usage",
        "food preferences",
        "air quality",
        "home care",
        "pet care",
    )
    for node, _ in flat_nodes:
        if not _node_is_visible(node):
            continue
        label_blob = _node_label_blob(node)
        normalized_label_blob = re.sub(r"\s+", " ", label_blob).strip().lower()
        resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
        normalized_resource_id = resource_id.lower()
        selected = bool(node.get("selected"))
        if (
            _safe_regex_search(r"(?i)menu_services", resource_id)
            or _safe_regex_search(r"(?i)\blife\b", label_blob)
        ) and selected:
            life_selected = True
        if _safe_regex_search(r"(?i)menu_services", resource_id):
            bottom_nav_life_visible = True
        if _safe_regex_search(r"(?i)\b(add|more options|location|qr code)\b", label_blob):
            app_bar_hits += 1
        if _safe_regex_search(_LIFE_ENERGY_NAVIGATE_UP_REGEX, label_blob):
            navigate_up_hits += 1
        if _safe_regex_search(r"(?i)(preinstalledservicecard|servicecard|card)", resource_id):
            visible_card_hits += 1
        if "divider_text" in normalized_resource_id or "preinstalledservicecard" in normalized_resource_id:
            structure_hits += 1
        if "cardtitle" in normalized_resource_id or "carddescription" in normalized_resource_id:
            structure_hits += 1
        if normalized_label_blob in life_service_titles:
            service_title_hits += 1
        if normalized_label_blob == "more services":
            structure_hits += 1
        if any(token in normalized_label_blob for token in life_description_contains):
            description_hits += 1
    life_root_signature_present = bool(structure_hits > 0 or service_title_hits > 0 or description_hits > 0)
    final_score = 0
    if life_selected:
        final_score += 1
    if app_bar_hits >= _LIFE_ROOT_APP_BAR_MIN_HITS:
        final_score += 1
    if visible_card_hits >= _LIFE_ROOT_VISIBLE_CARD_MIN_HITS:
        final_score += 1
    if life_root_signature_present:
        final_score += 1
    if bottom_nav_life_visible:
        final_score += 1
    has_root_structure = app_bar_hits >= _LIFE_ROOT_APP_BAR_MIN_HITS or visible_card_hits >= _LIFE_ROOT_VISIBLE_CARD_MIN_HITS
    ok = bool(life_root_signature_present and has_root_structure and final_score >= _LIFE_ROOT_SCORE_THRESHOLD)
    if ok:
        pass_reason = "life_root_signature_and_structure_confirmed"
        fail_reason = ""
    else:
        pass_reason = ""
        fail_reason = "life_root_not_stable"
    return {
        "life_selected": life_selected,
        "app_bar_hits": app_bar_hits,
        "visible_card_hits": visible_card_hits,
        "life_root_signature_present": life_root_signature_present,
        "bottom_nav_life_visible": bottom_nav_life_visible,
        "navigate_up_hits": navigate_up_hits,
        "final_score": final_score,
        "pass_reason": pass_reason,
        "fail_reason": fail_reason,
        "ok": ok,
    }


def _verify_plugin_entry_root_state(
    client: A11yAdbClient,
    dev: str,
    *,
    phase: str,
    scenario_id: str = "",
) -> tuple[bool, str]:
    dump_tree_fn = getattr(client, "dump_tree", None)
    if not callable(dump_tree_fn):
        log(f"[SCENARIO][pre_nav][stabilization] phase='{phase}' ok=false reason='dump_tree_not_supported'")
        return False, "dump_tree_not_supported"

    last_reason = "root_state_unverified"
    for attempt in range(1, _PLUGIN_ENTRY_RETRY_COUNT + 1):
        try:
            nodes = dump_tree_fn(dev=dev)
        except Exception as exc:
            nodes = []
            last_reason = f"dump_failed:{exc}"
        snapshot = _life_root_state_snapshot(nodes)
        ok = bool(snapshot.get("ok"))
        family_care_signature_seen = any(
            _safe_regex_search(_LIFE_ENERGY_FAMILY_CARE_REGEX, _node_label_blob(node))
            for node, _ in _iter_tree_nodes_with_parent(nodes)
        )
        log(
            f"[SCENARIO][pre_nav][stabilization] phase='{phase}' attempt={attempt}/{_PLUGIN_ENTRY_RETRY_COUNT} "
            f"life_selected={str(snapshot.get('life_selected')).lower()} app_bar_hits={snapshot.get('app_bar_hits', 0)} "
            f"visible_card_hits={snapshot.get('visible_card_hits', 0)} "
            f"life_root_signature_present={str(snapshot.get('life_root_signature_present')).lower()} "
            f"navigate_up_hits={snapshot.get('navigate_up_hits', 0)} "
            f"family_care_signature_seen={str(family_care_signature_seen).lower()} "
            f"final_score={snapshot.get('final_score', 0)} ok={str(ok).lower()} "
            f"pass_reason='{snapshot.get('pass_reason', '')}' fail_reason='{snapshot.get('fail_reason', '')}'"
        )
        if ok:
            return True, "root_state_stable"
        last_reason = str(snapshot.get("fail_reason", "life_root_not_stable") or "life_root_not_stable")
        is_life_energy_before_pre_nav = (
            str(scenario_id or "").strip().lower() == _LIFE_ENERGY_SCENARIO_ID
            and phase == "before_pre_navigation"
        )
        if is_life_energy_before_pre_nav:
            relaxed_scrolltouch_entry_ok = bool(
                int(snapshot.get("navigate_up_hits", 0) or 0) == 0
                and bool(snapshot.get("life_selected") or snapshot.get("bottom_nav_life_visible"))
                and int(snapshot.get("app_bar_hits", 0) or 0) >= _LIFE_ROOT_APP_BAR_MIN_HITS
            )
            if relaxed_scrolltouch_entry_ok:
                log(
                    f"[SCENARIO][pre_nav][stabilization][life_energy_relaxed_gate] phase='{phase}' "
                    f"attempt={attempt}/{_PLUGIN_ENTRY_RETRY_COUNT} allow_scrolltouch=true reason='life_plugin_list_likely'"
                )
                return True, "root_state_scrolltouch_entry_relaxed"
            transient_candidate = bool(
                snapshot.get("life_selected")
                or snapshot.get("bottom_nav_life_visible")
                or int(snapshot.get("app_bar_hits", 0) or 0) >= _LIFE_ROOT_APP_BAR_MIN_HITS
                or int(snapshot.get("visible_card_hits", 0) or 0) >= _LIFE_ROOT_VISIBLE_CARD_MIN_HITS
            )
            if transient_candidate:
                for recheck_idx in range(1, _LIFE_ROOT_TRANSIENT_RECHECK_COUNT + 1):
                    time.sleep(_LIFE_ROOT_TRANSIENT_RECHECK_SLEEP_SECONDS)
                    try:
                        recheck_nodes = dump_tree_fn(dev=dev)
                    except Exception:
                        recheck_nodes = []
                    family_care_signature_seen = any(
                        _safe_regex_search(_LIFE_ENERGY_FAMILY_CARE_REGEX, _node_label_blob(node))
                        for node, _ in _iter_tree_nodes_with_parent(recheck_nodes)
                    )
                    recheck_snapshot = _life_root_state_snapshot(recheck_nodes)
                    recheck_ok = bool(recheck_snapshot.get("ok"))
                    relaxed_recheck_ok = bool(
                        int(recheck_snapshot.get("navigate_up_hits", 0) or 0) == 0
                        and bool(recheck_snapshot.get("life_selected") or recheck_snapshot.get("bottom_nav_life_visible"))
                        and int(recheck_snapshot.get("app_bar_hits", 0) or 0) >= _LIFE_ROOT_APP_BAR_MIN_HITS
                    )
                    log(
                        f"[SCENARIO][pre_nav][stabilization][recheck] phase='{phase}' "
                        f"attempt={attempt}/{_PLUGIN_ENTRY_RETRY_COUNT} recheck={recheck_idx}/{_LIFE_ROOT_TRANSIENT_RECHECK_COUNT} "
                        f"life_selected={str(recheck_snapshot.get('life_selected')).lower()} "
                        f"app_bar_hits={recheck_snapshot.get('app_bar_hits', 0)} "
                        f"visible_card_hits={recheck_snapshot.get('visible_card_hits', 0)} "
                        f"life_root_signature_present={str(recheck_snapshot.get('life_root_signature_present')).lower()} "
                        f"navigate_up_hits={recheck_snapshot.get('navigate_up_hits', 0)} "
                        f"final_score={recheck_snapshot.get('final_score', 0)} "
                        f"family_care_signature_seen={str(family_care_signature_seen).lower()} "
                        f"ok={str(recheck_ok).lower()} relaxed_ok={str(relaxed_recheck_ok).lower()}"
                    )
                    if recheck_ok:
                        return True, "root_state_stable_recheck"
                    if relaxed_recheck_ok:
                        return True, "root_state_scrolltouch_entry_relaxed_recheck"
                    last_reason = str(recheck_snapshot.get("fail_reason", last_reason) or last_reason)
        if attempt < _PLUGIN_ENTRY_RETRY_COUNT:
            time.sleep(0.2)
    return False, last_reason


def _is_meaningful_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    compact = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return len(compact) >= 2


def should_attempt_stall_escape(
    tab_cfg: dict[str, Any],
    row: dict[str, Any],
    stop_details: dict[str, Any],
    *,
    stop_reason: str,
    escape_attempted: bool,
) -> tuple[bool, str]:
    if stop_reason != "repeat_semantic_stall":
        return False, "not_repeat_semantic_stall"
    if escape_attempted:
        return False, "already_attempted"

    scenario_type = str(stop_details.get("scenario_type", tab_cfg.get("scenario_type", "content")) or "content").strip().lower()
    if scenario_type != "content":
        return False, "scenario_type_not_content"

    screen_context_mode = str(tab_cfg.get("screen_context_mode", "") or "").strip().lower()
    scenario_group = str(tab_cfg.get("group", "") or "").strip().lower()
    is_plugin_screen = screen_context_mode == "new_screen" or (scenario_group and scenario_group != "main_tabs")
    if not is_plugin_screen:
        return False, "not_plugin_screen"

    recent_duplicate = bool(stop_details.get("recent_duplicate", False))
    recent_semantic_duplicate = bool(stop_details.get("recent_semantic_duplicate", False))
    same_like_count = int(stop_details.get("same_like_count", 0) or 0)
    semantic_window_unique_count = int(stop_details.get("recent_semantic_unique_count", 0) or 0)
    semantic_same_like = bool(stop_details.get("semantic_same_like", False))
    move_result = str(row.get("move_result", "") or "").strip().lower()
    moved_like = move_result in {"moved", "scrolled", "edge_realign_then_moved"}
    if not moved_like:
        return False, "move_not_moved_like"
    if not recent_duplicate or not recent_semantic_duplicate:
        return False, "duplicate_signal_weak"
    if same_like_count < _STALL_ESCAPE_SAME_LIKE_THRESHOLD:
        return False, "same_like_below_threshold"
    if semantic_window_unique_count > _STALL_ESCAPE_SEMANTIC_UNIQUE_MAX:
        return False, "semantic_window_too_diverse"
    if not semantic_same_like:
        return False, "semantic_not_same_like"
    return True, "eligible"


def attempt_stall_escape(
    client: A11yAdbClient,
    dev: str,
    row: dict[str, Any],
    *,
    step_idx: int,
    announcement_wait_seconds: float,
    announcement_idle_wait_seconds: float,
    announcement_max_extra_wait_seconds: float,
) -> dict[str, Any]:
    baseline_semantic_fingerprint = build_row_semantic_fingerprint(row)
    baseline_fingerprint = build_row_fingerprint(row)
    baseline_bounds = str(row.get("focus_bounds", "") or "").strip()
    moved_prev = bool(client.move_focus(dev=dev, direction="prev"))
    if not moved_prev:
        return {"success": False, "reason": "move_prev_failed", "method": "refocus_or_realign"}

    probe_row = client.collect_focus_step(
        dev=dev,
        step_index=step_idx,
        move=False,
        wait_seconds=announcement_wait_seconds,
        announcement_wait_seconds=announcement_wait_seconds,
        announcement_idle_wait_seconds=announcement_idle_wait_seconds,
        announcement_max_extra_wait_seconds=announcement_max_extra_wait_seconds,
    )
    probe_semantic_fingerprint = build_row_semantic_fingerprint(probe_row)
    probe_fingerprint = build_row_fingerprint(probe_row)
    probe_bounds = str(probe_row.get("focus_bounds", "") or "").strip()
    semantic_changed = bool(probe_semantic_fingerprint) and probe_semantic_fingerprint != baseline_semantic_fingerprint
    fingerprint_changed = bool(probe_fingerprint) and probe_fingerprint != baseline_fingerprint
    bounds_changed = bool(probe_bounds) and probe_bounds != baseline_bounds
    success = semantic_changed or (fingerprint_changed and bounds_changed)
    if success:
        return {"success": True, "reason": "semantic_changed", "method": "refocus_or_realign"}
    return {"success": False, "reason": "same_semantic_object_after_escape", "method": "refocus_or_realign"}


def _is_new_screen_low_confidence_allowed(
    tab_cfg: dict[str, Any],
    stabilize_result: dict[str, Any],
    *,
    pre_nav_ok: bool,
    screen_context_mode: str,
) -> tuple[bool, str]:
    if not pre_nav_ok:
        return False, "pre_navigation_failed"
    if screen_context_mode != "new_screen":
        return False, "screen_context_mode_not_new_screen"
    stabilization_mode = _resolve_stabilization_mode(tab_cfg, screen_context_mode)
    scenario_group = str(tab_cfg.get("group", "") or "").strip().lower()
    scenario_id = str(tab_cfg.get("scenario_id", "") or "").strip().lower()
    is_plugin_scope = stabilization_mode == "anchor_only" or scenario_group == "plugin_screen" or "plugin" in scenario_id
    if not is_plugin_scope:
        return False, "not_plugin_new_screen_scope"

    fallback_used = bool(stabilize_result.get("fallback_candidate_used"))
    fallback_label = str(stabilize_result.get("fallback_candidate_label", "") or "").strip()
    fallback_resource_id = str(stabilize_result.get("fallback_candidate_resource_id", "") or "").strip()
    fallback_rejected_reason = str(stabilize_result.get("fallback_candidate_rejected_reason", "") or "").strip()
    if fallback_rejected_reason == "boilerplate_like":
        return False, "boilerplate_only_candidate"
    if not fallback_used:
        return False, "fallback_candidate_absent"

    verify_row = stabilize_result.get("verify_row", {})
    if not isinstance(verify_row, dict):
        verify_row = {}

    has_meaningful_fallback = _is_meaningful_text(fallback_label) or _is_meaningful_text(fallback_resource_id)
    has_meaningful_focus = _is_meaningful_text(verify_row.get("visible_label")) or _is_meaningful_text(
        verify_row.get("merged_announcement")
    )
    has_meaningful_talkback = _is_meaningful_text(verify_row.get("talkback_label")) or _is_meaningful_text(
        verify_row.get("focus_text")
    )
    has_post_announcement = _is_meaningful_text(verify_row.get("announcement")) or _is_meaningful_text(
        verify_row.get("normalized_announcement")
    )
    has_top_level_signal = bool(verify_row.get("get_focus_top_level_payload_sufficient")) or bool(
        verify_row.get("get_focus_fallback_found")
    )
    if has_meaningful_fallback and (
        has_meaningful_focus or has_meaningful_talkback or has_post_announcement or has_top_level_signal
    ):
        return True, "fallback_candidate_and_focus_evidence"
    return False, "insufficient_new_screen_evidence"


def _resolve_recovery_policy(tab_cfg: dict[str, Any]) -> dict[str, Any]:
    fallback_policy = {
        "enabled": True,
        "target_type": "bottom_tab",
        "target": "(?i).*home.*",
        "resource_id": "com.samsung.android.oneconnect:id/menu_favorites",
        "max_back_count": 5,
    }
    raw_policy = tab_cfg.get("recovery", {})
    if not isinstance(raw_policy, dict):
        raw_policy = {}
    policy = dict(fallback_policy)
    policy.update(raw_policy)
    policy["enabled"] = bool(policy.get("enabled", True))
    policy["target_type"] = str(policy.get("target_type", "bottom_tab") or "bottom_tab").strip().lower()
    if policy["target_type"] not in {"bottom_tab", "anchor", "resource_id"}:
        policy["target_type"] = "bottom_tab"
    policy["target"] = str(policy.get("target", "") or "")
    policy["resource_id"] = str(policy.get("resource_id", "") or "")
    max_back_count = policy.get("max_back_count", 5)
    if isinstance(max_back_count, bool) or not isinstance(max_back_count, int) or max_back_count <= 0:
        max_back_count = 5
    policy["max_back_count"] = max_back_count
    return policy


def _node_text_blob(node: dict[str, Any]) -> str:
    return " ".join(
        [
            str(node.get("text", "") or "").strip(),
            str(node.get("contentDescription", "") or "").strip(),
            str(node.get("talkbackLabel", "") or "").strip(),
        ]
    ).strip()


def _is_recovery_target_detected(nodes: list[dict[str, Any]], policy: dict[str, Any]) -> tuple[bool, bool]:
    target_type = str(policy.get("target_type", "bottom_tab") or "bottom_tab")
    target_pattern = str(policy.get("target", "") or "")
    resource_id = str(policy.get("resource_id", "") or "")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
        text_blob = _node_text_blob(node)
        resource_match = bool(resource_id) and _safe_regex_search(resource_id, node_resource_id)
        label_match = bool(target_pattern) and _safe_regex_search(target_pattern, text_blob)
        selected_match = _safe_regex_search(r"(selected|선택됨)", text_blob) or bool(node.get("selected"))

        if target_type == "resource_id":
            if resource_match:
                return True, False
            continue
        if target_type == "anchor":
            if label_match or resource_match:
                return True, False
            continue
        if resource_match or label_match:
            return True, not selected_match
    return False, False


def _select_recovery_target(client: A11yAdbClient, dev: str, policy: dict[str, Any]) -> bool:
    resource_id = str(policy.get("resource_id", "") or "").strip()
    target_pattern = str(policy.get("target", "") or "").strip()
    target_type = str(policy.get("target_type", "bottom_tab") or "bottom_tab")
    if resource_id:
        if bool(client.select(dev=dev, name=resource_id, type_="r", wait_=3)):
            return True
        if target_pattern:
            log("[RECOVER] resource select failed, trying label fallback")
            fallback_type = "a"
            if target_type == "resource_id":
                fallback_type = "r"
            if bool(client.select(dev=dev, name=target_pattern, type_=fallback_type, wait_=3)):
                log("[RECOVER] select fallback succeeded")
                return True
            log("[RECOVER] select fallback failed")
        return False
    if target_pattern:
        select_type = "a"
        if target_type == "resource_id":
            select_type = "r"
        return bool(client.select(dev=dev, name=target_pattern, type_=select_type, wait_=3))
    return False


def _resolve_global_nav_resource_ids(tab_cfg: dict[str, Any]) -> list[str]:
    global_nav_cfg = tab_cfg.get("global_nav", {})
    if not isinstance(global_nav_cfg, dict):
        return []
    raw_ids = global_nav_cfg.get("resource_ids", [])
    if not isinstance(raw_ids, list):
        return []
    return [str(item or "").strip() for item in raw_ids if str(item or "").strip()]


def _ensure_global_nav_start_focus(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    *,
    scenario_id: str,
    focused_view_id: str,
    wait_seconds: float,
) -> tuple[bool, dict[str, Any]]:
    bottom_tab_ids = _resolve_global_nav_resource_ids(tab_cfg)
    normalized_ids = {item.lower() for item in bottom_tab_ids}
    focused_norm = focused_view_id.lower()
    is_bottom_tab = bool(focused_norm) and focused_norm in normalized_ids
    log(
        f"[GLOBAL_NAV][start_gate] scenario='{scenario_id}' focused_view_id='{focused_view_id}' "
        f"is_bottom_tab={str(is_bottom_tab).lower()}"
    )
    if is_bottom_tab:
        log(f"[GLOBAL_NAV][start_gate] passed scenario='{scenario_id}'")
        return True, {}

    log(
        f"[GLOBAL_NAV][start_gate] retry_align scenario='{scenario_id}' "
        f"reason='focused_node_not_bottom_tab' focused_view_id='{focused_view_id}'"
    )
    retry_target = bottom_tab_ids[0] if bottom_tab_ids else "com.samsung.android.oneconnect:id/menu_favorites"
    client.select(dev=dev, name=retry_target, type_="r", wait_=3)
    time.sleep(min(max(wait_seconds, 0.2), 0.8))
    retry_focus = client.get_focus(
        dev=dev,
        wait_seconds=min(wait_seconds, 1.0),
        allow_fallback_dump=False,
        mode="fast",
    )
    retry_view_id = (
        str(retry_focus.get("viewIdResourceName", "") or retry_focus.get("resourceId", "") or "").strip()
        if isinstance(retry_focus, dict)
        else ""
    )
    retry_norm = retry_view_id.lower()
    retry_ok = bool(retry_norm) and retry_norm in normalized_ids
    log(
        f"[GLOBAL_NAV][start_gate] scenario='{scenario_id}' focused_view_id='{retry_view_id}' "
        f"is_bottom_tab={str(retry_ok).lower()}"
    )
    if retry_ok:
        log(f"[GLOBAL_NAV][start_gate] passed scenario='{scenario_id}'")
        return True, retry_focus if isinstance(retry_focus, dict) else {}
    log(f"[GLOBAL_NAV][start_gate] failed scenario='{scenario_id}' final_view_id='{retry_view_id}'")
    return False, retry_focus if isinstance(retry_focus, dict) else {}


def _send_back(client: A11yAdbClient, dev: str) -> bool:
    run_fn = getattr(client, "_run", None)
    if callable(run_fn):
        try:
            run_fn(["shell", "input", "keyevent", "4"], dev=dev, timeout=5.0)
            return True
        except Exception:
            return False
    return False


def recover_to_start_state(client: A11yAdbClient, dev: str, tab_cfg: dict[str, Any]) -> bool:
    policy = _resolve_recovery_policy(tab_cfg)
    if not policy.get("enabled", True):
        log("[RECOVER] skipped reason='disabled'")
        return True

    wait_seconds = _get_wait_seconds(tab_cfg, "back_recovery_wait_seconds", MAIN_STEP_WAIT_SECONDS)
    max_back_count = int(policy.get("max_back_count", 5) or 5)
    log("[RECOVER] start")

    dump_tree_fn = getattr(client, "dump_tree", None)
    if not callable(dump_tree_fn):
        log("[RECOVER] failed reason='dump_tree_unavailable'")
        return False

    for attempt in range(0, max_back_count + 1):
        if attempt > 0:
            log(f"[RECOVER] back attempt={attempt}/{max_back_count}", level="DEBUG")
            back_ok = _send_back(client, dev)
            if not back_ok:
                log("[RECOVER] failed reason='back_failed'")
                return False
            time.sleep(wait_seconds)

        try:
            nodes = dump_tree_fn(dev=dev)
        except Exception as exc:
            log(f"[RECOVER] failed reason='dump_tree_failed:{exc}'")
            return False

        detected, needs_select = _is_recovery_target_detected(nodes if isinstance(nodes, list) else [], policy)
        if not detected:
            continue

        log(f"[RECOVER] target detected type={policy.get('target_type', 'bottom_tab')}", level="DEBUG")
        if needs_select:
            log("[RECOVER] selecting target", level="DEBUG")
            if not _select_recovery_target(client, dev, policy):
                continue
            log("[RECOVER] verify after select", level="DEBUG")
            verify_sleeps = [wait_seconds, min(wait_seconds, 0.4)]
            verified = False
            verified_needs_select = True
            for sleep_seconds in verify_sleeps:
                time.sleep(sleep_seconds)
                try:
                    verify_nodes = dump_tree_fn(dev=dev)
                except Exception:
                    verify_nodes = []
                verified, verified_needs_select = _is_recovery_target_detected(
                    verify_nodes if isinstance(verify_nodes, list) else [],
                    policy,
                )
                if verified and not verified_needs_select:
                    break

            if not verified:
                continue
            if verified_needs_select and str(policy.get("target_type", "bottom_tab") or "bottom_tab") == "bottom_tab":
                log("[RECOVER] verify soft-success reason='target_present_after_select'", level="DEBUG")
            elif verified_needs_select:
                continue
            log("[RECOVER] success after select verify", level="DEBUG")

        log("[RECOVER] success")
        return True

    log("[RECOVER] failed reason='target_not_reached'")
    return False


def _make_dump_signature(nodes: Any) -> str:
    if not isinstance(nodes, list):
        return ""
    signature_parts: list[str] = []
    for node in nodes[:10]:
        if not isinstance(node, dict):
            continue
        signature_parts.append(
            "|".join(
                [
                    str(node.get("viewIdResourceName", "") or "").strip(),
                    str(node.get("text", "") or "").strip(),
                    str(node.get("contentDescription", "") or "").strip(),
                ]
            )
        )
    return "||".join(signature_parts)


def _extract_window_focus_line(client: A11yAdbClient, dev: str) -> str:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return ""
    try:
        output = run_fn(["shell", "dumpsys", "window", "windows"], dev=dev)
    except Exception:
        return ""
    for line in str(output or "").splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            return line.strip()
    return ""


def _build_transition_patterns(tab_cfg: dict[str, Any]) -> dict[str, str]:
    anchor_cfg = dict(tab_cfg.get("anchor", {}) or {})
    context_cfg = dict(tab_cfg.get("context_verify", {}) or {})
    anchor_text_pattern = str(anchor_cfg.get("text_regex", "") or "").strip()
    anchor_resource_pattern = str(anchor_cfg.get("resource_id_regex", "") or "").strip()
    if not anchor_text_pattern and not anchor_resource_pattern:
        anchor_name = str(tab_cfg.get("anchor_name", "") or "").strip()
        anchor_type = str(tab_cfg.get("anchor_type", "a") or "a").strip().lower()
        if anchor_name and anchor_type in {"t", "b", "a"}:
            anchor_text_pattern = anchor_name
        if anchor_name and anchor_type in {"r", "a"}:
            anchor_resource_pattern = anchor_name
    return {
        "anchor_text": anchor_text_pattern,
        "anchor_resource": anchor_resource_pattern,
        "context_text": str(context_cfg.get("text_regex", "") or "").strip(),
    }


def _node_matches_transition_pattern(node: Any, patterns: dict[str, str]) -> tuple[bool, str]:
    if not isinstance(node, dict):
        return False, ""
    text_blob = " ".join(
        [
            str(node.get("text", "") or "").strip(),
            str(node.get("contentDescription", "") or "").strip(),
            str(node.get("talkbackLabel", "") or "").strip(),
        ]
    ).strip()
    resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
    if patterns.get("anchor_text") and _safe_regex_search(patterns["anchor_text"], text_blob):
        return True, "anchor_match"
    if patterns.get("anchor_resource") and _safe_regex_search(patterns["anchor_resource"], resource_id):
        return True, "anchor_match"
    if patterns.get("context_text") and _safe_regex_search(patterns["context_text"], text_blob):
        return True, "screen_text"
    return False, ""


def _confirm_click_focused_transition(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    *,
    transition_fast_path: bool,
    baseline_nodes: list[dict[str, Any]] | None = None,
    baseline_window_focus: str = "",
) -> tuple[bool, str]:
    scenario_id = str(tab_cfg.get("scenario_id", "") or "").strip().lower()
    strict_life_energy_mode = scenario_id == _LIFE_ENERGY_SCENARIO_ID
    max_poll_count = 2 if transition_fast_path else 3
    focus_wait_seconds = 0.28 if transition_fast_path else 0.45
    patterns = _build_transition_patterns(tab_cfg)
    has_expected_signal = any(bool(patterns.get(key)) for key in ("anchor_text", "anchor_resource", "context_text"))
    if not has_expected_signal:
        return True, "no_expected_signal_configured"
    dump_tree_fn = getattr(client, "dump_tree", None)
    if not baseline_nodes and callable(dump_tree_fn):
        try:
            baseline_nodes = dump_tree_fn(dev=dev)
        except Exception:
            baseline_nodes = []
    baseline_signature = _make_dump_signature(baseline_nodes)
    if not baseline_window_focus:
        baseline_window_focus = _extract_window_focus_line(client, dev)
    saw_dump_change = False
    saw_focus_change = False
    saw_conflicting_screen_signature = False

    for poll_idx in range(max_poll_count):
        current_nodes: list[dict[str, Any]] = []
        if callable(dump_tree_fn):
            try:
                current_nodes = dump_tree_fn(dev=dev)
            except Exception:
                current_nodes = []
        energy_signature_seen = False
        for node in current_nodes:
            if strict_life_energy_mode and _safe_regex_search(patterns.get("context_text", ""), _node_label_blob(node)):
                energy_signature_seen = True
            matched, signal = _node_matches_transition_pattern(node, patterns)
            if matched:
                if strict_life_energy_mode and signal == "anchor_match" and not energy_signature_seen:
                    continue
                return True, signal
        if strict_life_energy_mode and not energy_signature_seen:
            for node, _ in _iter_tree_nodes_with_parent(current_nodes):
                if _safe_regex_search(_LIFE_ENERGY_FAMILY_CARE_REGEX, _node_label_blob(node)):
                    saw_conflicting_screen_signature = True
                    break

        current_signature = _make_dump_signature(current_nodes)
        if current_signature and baseline_signature and current_signature != baseline_signature:
            saw_dump_change = True

        get_focus_fn = getattr(client, "get_focus", None)
        if callable(get_focus_fn):
            focus_node = get_focus_fn(
                dev=dev,
                wait_seconds=focus_wait_seconds,
                allow_fallback_dump=not transition_fast_path,
            )
            focus_matched, _ = _node_matches_transition_pattern(focus_node, patterns)
            if focus_matched:
                if strict_life_energy_mode:
                    focus_label = _node_label_blob(focus_node)
                    focus_view_id = str(
                        focus_node.get("viewIdResourceName", "") or focus_node.get("resourceId", "") or ""
                    ).strip()
                    is_generic_navigate_up = bool(_safe_regex_search(_LIFE_ENERGY_NAVIGATE_UP_REGEX, focus_label))
                    if is_generic_navigate_up and not focus_view_id:
                        pass
                    else:
                        return True, "focus_shift"
                else:
                    return True, "focus_shift"

        current_window_focus = _extract_window_focus_line(client, dev)
        if current_window_focus and baseline_window_focus and current_window_focus != baseline_window_focus:
            saw_focus_change = True

        if poll_idx < max_poll_count - 1:
            time.sleep(_PRE_NAV_CONFIRM_POLL_SLEEP_SECONDS)

    if strict_life_energy_mode and saw_conflicting_screen_signature:
        return False, "conflicting_screen_signature"
    if strict_life_energy_mode and (saw_dump_change or saw_focus_change):
        return False, "weak_transition_signal_only"
    if saw_dump_change:
        return True, "dump_signature_changed"
    if saw_focus_change:
        return True, "window_focus_changed"
    return False, "none"


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


def _is_transition_entry_fast_path(tab_cfg: dict[str, Any]) -> bool:
    screen_context_mode = _resolve_screen_context_mode(tab_cfg)
    stabilization_mode = _resolve_stabilization_mode(tab_cfg, screen_context_mode)
    pre_navigation = tab_cfg.get("pre_navigation", [])
    has_pre_navigation = isinstance(pre_navigation, list) and bool(pre_navigation)
    return has_pre_navigation and screen_context_mode == "new_screen" and stabilization_mode == "anchor_only"


def _is_focus_target_match(focus_node: Any, target: str, type_: str) -> bool:
    if not isinstance(focus_node, dict):
        return False

    value_by_type = {
        "r": str(focus_node.get("viewIdResourceName", "") or focus_node.get("resourceId", "") or "").strip(),
        "t": str(focus_node.get("text", "") or "").strip(),
        "b": str(focus_node.get("contentDescription", "") or "").strip(),
        "a": " ".join(
            [
                str(focus_node.get("viewIdResourceName", "") or focus_node.get("resourceId", "") or "").strip(),
                str(focus_node.get("text", "") or "").strip(),
                str(focus_node.get("contentDescription", "") or "").strip(),
            ]
        ).strip(),
    }
    check_type = str(type_ or "a").strip().lower()
    match_value = value_by_type.get(check_type, value_by_type["a"])
    if not match_value:
        return False

    try:
        return re.search(target, match_value, re.IGNORECASE) is not None
    except re.error:
        return target in match_value


def _confirm_focus_target(
    client: A11yAdbClient,
    dev: str,
    target: str,
    type_: str,
    *,
    transition_fast_path: bool,
) -> tuple[bool, str]:
    max_poll_count = 2 if transition_fast_path else 3
    poll_sleep_seconds = 0.1
    focus_wait_seconds = 0.35 if transition_fast_path else 0.6
    for poll_idx in range(max_poll_count):
        last_result = getattr(client, "last_target_action_result", None) or {}
        target_snapshot = last_result.get("target", {}) if isinstance(last_result, dict) else {}
        if isinstance(target_snapshot, dict):
            focused_flag = bool(target_snapshot.get("accessibilityFocused")) or bool(target_snapshot.get("focused"))
            if focused_flag and _is_focus_target_match(target_snapshot, target=target, type_=type_):
                return True, "last_target_action_result"
        get_focus_fn = getattr(client, "get_focus", None)
        if callable(get_focus_fn):
            focus_node = get_focus_fn(
                dev=dev,
                wait_seconds=focus_wait_seconds,
                allow_fallback_dump=not transition_fast_path,
            )
            if _is_focus_target_match(focus_node, target=target, type_=type_):
                return True, "get_focus"
        if poll_idx < max_poll_count - 1:
            time.sleep(poll_sleep_seconds)
    return False, "unmatched"


def _verify_scroll_top_state(
    client: A11yAdbClient,
    dev: str,
    *,
    baseline_nodes: list[dict[str, Any]] | None = None,
) -> tuple[bool, str, list[dict[str, Any]]]:
    dump_tree_fn = getattr(client, "dump_tree", None)
    if not callable(dump_tree_fn):
        return False, "dump_tree_not_supported", []
    try:
        nodes = dump_tree_fn(dev=dev)
    except Exception as exc:
        return False, f"dump_failed:{exc}", []

    snapshot = _life_root_state_snapshot(nodes)
    if not nodes:
        return True, "empty_dump_skip", nodes
    if bool(snapshot.get("ok")):
        return True, "life_root_marker_visible", nodes
    if isinstance(baseline_nodes, list) and baseline_nodes:
        before_sig = _make_dump_signature(baseline_nodes)
        after_sig = _make_dump_signature(nodes)
        if before_sig and after_sig and before_sig != after_sig:
            return True, "dump_signature_changed_after_scroll_to_top", nodes
    return False, "top_marker_missing", nodes


def _select_visible_plugin_candidate(
    *,
    nodes: list[dict[str, Any]],
    target: str,
) -> tuple[dict[str, Any] | None, str, dict[str, int]]:
    stats = {"visible_candidate_count": 0, "partial_match_count": 0}
    if not isinstance(nodes, list) or not nodes:
        return None, "empty_dump", stats
    flat_nodes = _iter_tree_nodes_with_parent(nodes)
    parsed_bounds = [parse_bounds_str(str(node.get("boundsInScreen", "") or "").strip()) for node, _ in flat_nodes]
    parsed_bounds = [b for b in parsed_bounds if b and b[0] < b[2] and b[1] < b[3]]
    if not parsed_bounds:
        return None, "viewport_unavailable", stats
    viewport_top = min(b[1] for b in parsed_bounds)
    viewport_bottom = max(b[3] for b in parsed_bounds)
    viewport_center = (viewport_top + viewport_bottom) // 2

    normalized_target = str(target or "").strip().lower()
    target_tokens = [token for token in re.split(r"[^0-9a-zA-Z가-힣]+", normalized_target) if len(token) >= 3]

    descendants_by_container: dict[int, list[str]] = {}
    for node, parent in flat_nodes:
        if not isinstance(parent, dict):
            continue
        parent_key = id(parent)
        descendants = descendants_by_container.setdefault(parent_key, [])
        child_label = _node_label_blob(node)
        if child_label:
            descendants.append(child_label)

    candidates: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for node, parent in flat_nodes:
        raw_bounds = str(node.get("boundsInScreen", "") or "").strip()
        bounds = parse_bounds_str(raw_bounds)
        if not bounds:
            continue
        left, top, right, bottom = bounds
        if not (left < right and top < bottom):
            continue
        if bottom <= viewport_top or top >= viewport_bottom:
            continue
        if not _node_is_visible(node):
            continue
        label_blob = _node_label_blob(node)
        if not label_blob or not _safe_regex_search(target, label_blob):
            continue
        resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
        click_node = node
        if isinstance(parent, dict):
            parent_clickable = bool(parent.get("clickable")) or bool(parent.get("focusable"))
            parent_resource = str(parent.get("viewIdResourceName", "") or parent.get("resourceId", "") or "").strip()
            if parent_clickable or _safe_regex_search(r"(?i)(preinstalledservicecard|servicecard|card)", parent_resource):
                click_node = parent
        click_bounds = parse_bounds_str(str(click_node.get("boundsInScreen", "") or "").strip())
        if not click_bounds:
            continue
        c_left, c_top, c_right, c_bottom = click_bounds
        if not (c_left < c_right and c_top < c_bottom):
            continue
        if c_bottom <= viewport_top or c_top >= viewport_bottom:
            continue
        stats["visible_candidate_count"] += 1
        title_blob = " ".join(
            [
                str(click_node.get("text", "") or "").strip(),
                str(click_node.get("contentDescription", "") or "").strip(),
            ]
        ).strip()
        descendant_blob = " ".join(descendants_by_container.get(id(click_node), []))
        semantic_blob = " ".join(part for part in [label_blob, title_blob, descendant_blob] if part).strip()
        if not semantic_blob:
            continue
        if target_tokens and any(token in semantic_blob.lower() for token in target_tokens):
            stats["partial_match_count"] += 1
        if not (_safe_regex_search(target, title_blob) or _safe_regex_search(target, semantic_blob)):
            continue
        card_resource = str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or "")
        center_delta = abs(((c_top + c_bottom) // 2) - viewport_center)
        score = (
            1 if bool(click_node.get("clickable")) or bool(click_node.get("focusable")) else 0,
            1 if _safe_regex_search(r"(?i)(preinstalledservicecard|servicecard|card)", card_resource) else 0,
            -center_delta,
            -c_top,
        )
        candidates.append((score, click_node))

    if not candidates:
        return None, "no_visible_candidate", stats
    candidates.sort(reverse=True, key=lambda item: item[0])
    return candidates[0][1], f"candidate_count={len(candidates)}", stats


def _make_visible_plugin_search_signature(nodes: list[dict[str, Any]]) -> str:
    if not isinstance(nodes, list):
        return ""
    parts: list[str] = []
    for node, _ in _iter_tree_nodes_with_parent(nodes):
        if not _node_is_visible(node):
            continue
        label_blob = _node_label_blob(node)
        resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
        bounds = str(node.get("boundsInScreen", "") or "").strip()
        if not (label_blob or resource_id):
            continue
        parts.append(f"{resource_id}|{label_blob}|{bounds}")
        if len(parts) >= 25:
            break
    return "||".join(parts)


def _run_pre_navigation_steps(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    *,
    transition_fast_path: bool = False,
) -> bool:
    pre_navigation = tab_cfg.get("pre_navigation", [])
    if not isinstance(pre_navigation, list) or not pre_navigation:
        return True

    retry_count = _get_retry_count(tab_cfg, "pre_navigation_retry_count", 2)
    wait_seconds = _get_wait_seconds(tab_cfg, "pre_navigation_wait_seconds", MAIN_STEP_WAIT_SECONDS)
    action_wait_seconds = _TRANSITION_FAST_ACTION_WAIT_SECONDS if transition_fast_path else 8
    step_wait_seconds = min(wait_seconds, _TRANSITION_FAST_STEP_WAIT_SECONDS) if transition_fast_path else wait_seconds
    step_announcement_wait_seconds = (
        min(wait_seconds, _TRANSITION_FAST_ANNOUNCEMENT_WAIT_SECONDS) if transition_fast_path else wait_seconds
    )

    for index, step in enumerate(pre_navigation, start=1):
        if not isinstance(step, dict):
            log(f"[SCENARIO][pre_nav] failed reason='invalid_step' step={index}")
            return False

        action = str(step.get("action", "") or "").strip().lower()
        if action in {"scroll_touch", "scroll-touch"}:
            action = "scrolltouch"
        target = str(step.get("target", "") or "").strip()
        type_ = str(step.get("type", "a") or "a").strip()
        if not action or not target:
            log(f"[SCENARIO][pre_nav] failed reason='invalid_step_config' step={index}")
            return False
        if action not in {
            "select",
            "touch",
            "scrolltouch",
            "touch_bounds_center",
            "select_and_click_focused",
            "tap_bounds_center_adb",
            "select_and_tap_bounds_center_adb",
            "select_and_click_focused_or_tap_bounds_center_adb",
        }:
            log(f"[SCENARIO][pre_nav] failed reason='unsupported_action' step={index} action='{action}'")
            return False

        step_retry_count = retry_count
        if action == "scrolltouch":
            screen_context_mode = _resolve_screen_context_mode(tab_cfg)
            stabilization_mode = _resolve_stabilization_mode(tab_cfg, screen_context_mode)
            if _is_plugin_anchor_only_new_screen(
                tab_cfg,
                screen_context_mode=screen_context_mode,
                stabilization_mode=stabilization_mode,
            ):
                step_retry_count = 1

        log(f"[SCENARIO][pre_nav] step={index} action={action} target='{target}'")
        step_ok = False
        actual_reason = "unknown"
        for attempt in range(1, step_retry_count + 1):
            if action == "select":
                step_ok = bool(client.select(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
            elif action == "touch":
                step_ok = bool(client.touch(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
            elif action == "scrolltouch":
                screen_context_mode = _resolve_screen_context_mode(tab_cfg)
                stabilization_mode = _resolve_stabilization_mode(tab_cfg, screen_context_mode)
                use_cumulative_search = _is_plugin_anchor_only_new_screen(
                    tab_cfg,
                    screen_context_mode=screen_context_mode,
                    stabilization_mode=stabilization_mode,
                )
                max_scroll_search_steps = max(
                    1,
                    int(tab_cfg.get("max_scroll_search_steps", _PLUGIN_SCROLL_SEARCH_MAX_STEPS) or _PLUGIN_SCROLL_SEARCH_MAX_STEPS),
                )

                before_top_nodes: list[dict[str, Any]] = []
                dump_tree_fn = getattr(client, "dump_tree", None)
                if callable(dump_tree_fn):
                    try:
                        before_top_nodes = dump_tree_fn(dev=dev)
                    except Exception:
                        before_top_nodes = []
                top_nodes = before_top_nodes
                if attempt == 1:
                    log(
                        f"[SCENARIO][pre_nav] before scrolltouch, scroll_to_top invoked cumulative_mode={str(use_cumulative_search).lower()}"
                    )
                    scroll_to_top_fn = getattr(client, "scroll_to_top", None)
                    if callable(scroll_to_top_fn):
                        try:
                            scroll_top_result = scroll_to_top_fn(dev=dev, max_swipes=5, pause=0.6)
                            log(f"[SCENARIO][pre_nav] scroll_to_top result={scroll_top_result}")
                        except Exception as exc:
                            log(f"[SCENARIO][pre_nav] scroll_to_top failed reason='{exc}'")
                    else:
                        log("[SCENARIO][pre_nav] scroll_to_top skipped reason='method_not_supported'")
                    top_ok, top_reason, top_nodes = _verify_scroll_top_state(client, dev, baseline_nodes=before_top_nodes)
                    log(
                        f"[SCENARIO][pre_nav] top_state_verify ok={str(top_ok).lower()} reason='{top_reason}' "
                        f"scenario='{tab_cfg.get('scenario_id', '')}'"
                    )
                    if not top_ok:
                        for verify_retry in range(1, _PLUGIN_TOP_VERIFY_RETRY_COUNT + 1):
                            if callable(scroll_to_top_fn):
                                try:
                                    scroll_to_top_fn(dev=dev, max_swipes=2, pause=0.4)
                                except Exception as exc:
                                    log(f"[SCENARIO][pre_nav] scroll_to_top retry failed reason='{exc}'")
                            top_ok, top_reason, top_nodes = _verify_scroll_top_state(client, dev, baseline_nodes=before_top_nodes)
                            log(
                                f"[SCENARIO][pre_nav] top_state_verify retry={verify_retry}/{_PLUGIN_TOP_VERIFY_RETRY_COUNT} "
                                f"ok={str(top_ok).lower()} reason='{top_reason}'"
                            )
                            if top_ok:
                                break
                else:
                    try:
                        top_nodes = dump_tree_fn(dev=dev) if callable(dump_tree_fn) else []
                    except Exception:
                        top_nodes = []

                last_signature = _make_visible_plugin_search_signature(top_nodes)
                fallback_reason = "local_search_exhausted"
                for scroll_step in range(1, max_scroll_search_steps + 1):
                    selected_node, selected_reason, candidate_stats = _select_visible_plugin_candidate(nodes=top_nodes, target=target)
                    if selected_node is not None:
                        class_name = str(selected_node.get("className", "") or "").strip()
                        resource_id = str(selected_node.get("viewIdResourceName", "") or selected_node.get("resourceId", "") or "").strip()
                        bounds = str(selected_node.get("boundsInScreen", "") or "").strip()
                        visible = _node_is_visible(selected_node)
                        label_blob = _node_label_blob(selected_node)
                        log(
                            f"[SCENARIO][pre_nav][scrolltouch] candidate_select reason='{selected_reason}' class='{class_name}' "
                            f"resource='{resource_id}' bounds='{bounds}' visible={str(visible).lower()} label='{label_blob[:120]}' "
                            f"scroll_step={scroll_step}/{max_scroll_search_steps} cumulative_mode={str(use_cumulative_search).lower()}"
                        )
                        tap_target = resource_id if resource_id else label_blob
                        tap_type = "r" if resource_id else "a"
                        step_ok = bool(client.tap_bounds_center_adb(dev=dev, name=tap_target, type_=tap_type, dump_nodes=top_nodes))
                        if step_ok:
                            confirm_ok, confirm_signal = _confirm_click_focused_transition(
                                client=client,
                                dev=dev,
                                tab_cfg=tab_cfg,
                                transition_fast_path=transition_fast_path,
                            )
                            log(
                                f"[SCENARIO][pre_nav][scrolltouch] post_click_transition same_screen={str(not confirm_ok).lower()} "
                                f"signal='{confirm_signal}'"
                            )
                            step_ok = confirm_ok
                        break

                    if scroll_step >= max_scroll_search_steps:
                        fallback_reason = "max_scroll_search_steps_reached"
                        log(
                            f"[SCENARIO][pre_nav][scrolltouch] visible_candidate_count={candidate_stats.get('visible_candidate_count', 0)} "
                            f"partial_match_count={candidate_stats.get('partial_match_count', 0)} "
                            f"scroll_step={scroll_step}/{max_scroll_search_steps} "
                            "action='local_search_exhausted' scroll_performed=false "
                            f"cumulative_mode={str(use_cumulative_search).lower()}"
                        )
                        break

                    scrolled = bool(client.scroll(dev=dev, direction="down")) if hasattr(client, "scroll") else False
                    log(
                        f"[SCENARIO][pre_nav][scrolltouch] visible_candidate_count={candidate_stats.get('visible_candidate_count', 0)} "
                        f"partial_match_count={candidate_stats.get('partial_match_count', 0)} "
                        f"scroll_step={scroll_step}/{max_scroll_search_steps} "
                        "action='scroll_forward_and_retry_local_search' "
                        f"scroll_performed={str(scrolled).lower()} cumulative_mode={str(use_cumulative_search).lower()}"
                    )
                    if not scrolled:
                        fallback_reason = "scroll_forward_failed"
                        break
                    time.sleep(min(step_wait_seconds, 0.45))
                    try:
                        top_nodes = dump_tree_fn(dev=dev) if callable(dump_tree_fn) else []
                    except Exception:
                        top_nodes = []
                    current_signature = _make_visible_plugin_search_signature(top_nodes)
                    if current_signature and last_signature and current_signature == last_signature:
                        fallback_reason = "semantic_no_change_after_scroll"
                        break
                    last_signature = current_signature

                if not step_ok:
                    log(
                        f"[SCENARIO][pre_nav][scrolltouch] candidate_select reason='no_local_match' "
                        f"fallback='helper_scrollTouch' reason_detail='{fallback_reason}' "
                        f"cumulative_mode={str(use_cumulative_search).lower()}"
                    )
                    step_ok = bool(client.scrollTouch(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
                    if step_ok:
                        confirm_ok, confirm_signal = _confirm_click_focused_transition(
                            client=client,
                            dev=dev,
                            tab_cfg=tab_cfg,
                            transition_fast_path=transition_fast_path,
                        )
                        log(
                            f"[SCENARIO][pre_nav][scrolltouch] post_click_transition same_screen={str(not confirm_ok).lower()} "
                            f"signal='{confirm_signal}'"
                        )
                        step_ok = confirm_ok
            elif action == "touch_bounds_center":
                step_ok = bool(client.touch_bounds_center(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
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
                select_ok = bool(client.select(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
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
            elif action == "select_and_click_focused_or_tap_bounds_center_adb":
                tap_target = str(step.get("tap_target", target) or target).strip()
                tap_type = str(step.get("tap_type", type_) or type_).strip()
                select_ok = bool(client.select(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
                focus_ok, focus_source = _confirm_focus_target(
                    client=client,
                    dev=dev,
                    target=target,
                    type_=type_,
                    transition_fast_path=transition_fast_path,
                )
                log(
                    f"[SCENARIO][pre_nav][focus_check] step={index} target='{target}' type='{type_}' "
                    f"select_ok={str(select_ok).lower()} matched={str(focus_ok).lower()} source='{focus_source}'"
                )
                if select_ok and focus_ok:
                    click_ok = bool(client.click_focused(dev=dev, wait_=action_wait_seconds))
                    log(
                        f"[SCENARIO][pre_nav] enter_by='click_focused' step={index} "
                        f"target='{target}' type='{type_}'"
                    )
                    if click_ok:
                        confirm_ok, confirm_signal = _confirm_click_focused_transition(
                            client=client,
                            dev=dev,
                            tab_cfg=tab_cfg,
                            transition_fast_path=transition_fast_path,
                        )
                        log(
                            f"[SCENARIO][pre_nav][confirm] method='click_focused' signal='{confirm_signal}' "
                            f"success={str(confirm_ok).lower()} step={index}"
                        )
                        step_ok = confirm_ok
                    else:
                        confirm_signal = "click_focused_failed"
                        step_ok = False
                    if not step_ok:
                        log(
                            "[SCENARIO][pre_nav] fallback='tap_bounds_center_adb' "
                            f"reason='transition_not_confirmed:{confirm_signal}' "
                            f"step={index} target='{target}' tap_target='{tap_target}'"
                        )
                        dump_nodes = step.get("dump_tree_nodes", [])
                        step_ok = bool(
                            client.tap_bounds_center_adb(dev=dev, name=tap_target, type_=tap_type, dump_nodes=dump_nodes)
                        )
                else:
                    log(
                        f"[SCENARIO][pre_nav] focus_first_failed fallback='tap_bounds_center_adb' step={index} "
                        f"target='{target}' tap_target='{tap_target}'"
                    )
                    dump_nodes = step.get("dump_tree_nodes", [])
                    step_ok = bool(client.tap_bounds_center_adb(dev=dev, name=tap_target, type_=tap_type, dump_nodes=dump_nodes))
            else:
                select_ok = bool(client.select(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
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
                    step_ok = bool(client.click_focused(dev=dev, wait_=action_wait_seconds))
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
            if attempt < step_retry_count:
                log(f"[SCENARIO][pre_nav] retry step={index} attempt={attempt}/{step_retry_count} reason='{actual_reason}'")

        if not step_ok:
            log(f"[SCENARIO][pre_nav] failed reason='action_failed' step={index}")
            log(f"[SCENARIO][pre_nav] failed reason='action_failed' detail='{actual_reason}' step={index}")
            return False

        client.collect_focus_step(
            dev=dev,
            step_index=-(700 + index),
            move=False,
            wait_seconds=step_wait_seconds,
            announcement_wait_seconds=step_announcement_wait_seconds,
            focus_wait_seconds=_TRANSITION_FAST_FOCUS_WAIT_SECONDS if transition_fast_path else None,
            allow_get_focus_fallback_dump=not transition_fast_path,
            allow_step_dump=not transition_fast_path,
            get_focus_mode="fast" if transition_fast_path else "normal",
        )
        time.sleep(step_wait_seconds)

    log("[SCENARIO][pre_nav] success")
    return True


def open_scenario(client: A11yAdbClient, dev: str, tab_cfg: dict) -> bool:
    tab_retry_count = _get_retry_count(tab_cfg, "tab_select_retry_count", 2)
    anchor_retry_count = _get_retry_count(tab_cfg, "anchor_retry_count", 2)
    main_step_wait_seconds = _get_wait_seconds(tab_cfg, "main_step_wait_seconds", MAIN_STEP_WAIT_SECONDS)
    screen_context_mode = _resolve_screen_context_mode(tab_cfg)
    stabilization_mode = _resolve_stabilization_mode(tab_cfg, screen_context_mode)
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    tab_cfg["_scenario_start_mode"] = "anchor_stable"
    tab_cfg["_scenario_anchor_stable"] = True
    tab_cfg["_scenario_start_note"] = ""
    tab_cfg["_scenario_start_source"] = "explicit_anchor"
    pre_navigation = tab_cfg.get("pre_navigation", [])
    has_pre_navigation = isinstance(pre_navigation, list) and bool(pre_navigation)
    is_transition_scenario = has_pre_navigation and (
        screen_context_mode == "new_screen" or stabilization_mode == "anchor_only"
    )
    is_plugin_pre_nav_scenario = _is_plugin_anchor_only_new_screen(
        tab_cfg,
        screen_context_mode=screen_context_mode,
        stabilization_mode=stabilization_mode,
    )
    is_transition_entry_fast_path = _is_transition_entry_fast_path(tab_cfg)
    is_strict_main_tab_scenario = scenario_id in _STRICT_MAIN_TAB_SCENARIOS
    log(
        f"[SCENARIO][stabilization] scenario='{scenario_id}' "
        f"screen_context_mode='{screen_context_mode}' stabilization_mode='{stabilization_mode}'"
    )
    setattr(client, "last_tab_stabilization_result", {})
    setattr(client, "last_anchor_stabilize_result", {})
    setattr(
        client,
        "last_start_open_summary",
        {
            "stabilization_mode": stabilization_mode,
            "context_ok": False,
            "anchor_matched": False,
            "anchor_stable": False,
            "focus_align_attempted": False,
            "focus_align_ok": False,
            "focus_align_reason": "",
            "pre_navigation_attempted": bool(has_pre_navigation),
            "pre_navigation_success": False,
            "open_completed": False,
        },
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
    setattr(client, "last_tab_stabilization_result", tab_stabilized if isinstance(tab_stabilized, dict) else {})
    focus_align_result = tab_stabilized.get("focus_align", {}) if isinstance(tab_stabilized, dict) else {}
    focus_align_attempted = bool(focus_align_result.get("attempted"))
    focus_align_ok = bool(focus_align_result.get("ok"))
    focus_align_fast = bool(focus_align_result.get("fast_mode"))
    trace_context_ok = bool(tab_stabilized.get("context", {}).get("ok")) if isinstance(tab_stabilized, dict) else False
    log(
        f"[TRACE][open_scenario] scenario='{scenario_id}' stabilization_mode='{stabilization_mode}' "
        f"focus_align_attempted={focus_align_attempted} focus_align_ok={focus_align_ok} "
        f"focus_align_reason='{focus_align_result.get('reason', '')}' context_ok={trace_context_ok} "
        f"anchor_matched=False anchor_stable=False",
    )
    if focus_align_attempted and not focus_align_ok:
        focus_log_tag = "[TAB][focus_align_fast]" if focus_align_fast else "[TAB][focus_align]"
        log(
            f"{focus_log_tag} scenario='{scenario_id}' main_tab={str(is_strict_main_tab_scenario).lower()} "
            f"transition_scenario={str(is_transition_scenario).lower()} result='failed'"
        )
        if is_plugin_pre_nav_scenario:
            plugin_root_ok, plugin_root_reason = _verify_plugin_entry_root_state(
                client,
                dev,
                phase="focus_align_recheck",
                scenario_id=scenario_id,
            )
            if not plugin_root_ok:
                log(
                    f"{focus_log_tag} strict failure for plugin pre_navigation scenario='{scenario_id}' "
                    f"reason='{plugin_root_reason}'"
                )
                return False
            log(
                f"{focus_log_tag} failed but proceeding after plugin root recheck "
                f"scenario='{scenario_id}' reason='{plugin_root_reason}'"
            )
        elif is_transition_scenario and not is_strict_main_tab_scenario:
            log(
                f"{focus_log_tag} failed but proceeding (transition scenario) "
                f"scenario='{scenario_id}'"
            )
        elif is_strict_main_tab_scenario:
            log(f"{focus_log_tag} strict failure scenario='{scenario_id}'")
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

    if is_transition_entry_fast_path and not is_strict_main_tab_scenario:
        transition_wait = min(main_step_wait_seconds, _TRANSITION_FAST_STEP_WAIT_SECONDS)
        time.sleep(transition_wait)
    else:
        time.sleep(main_step_wait_seconds)
    client.reset_focus_history(dev)
    if is_transition_entry_fast_path and not is_strict_main_tab_scenario:
        time.sleep(0.1)
    else:
        time.sleep(0.5)

    if is_plugin_pre_nav_scenario:
        plugin_root_ok, plugin_root_reason = _verify_plugin_entry_root_state(
            client,
            dev,
            phase="before_pre_navigation",
            scenario_id=scenario_id,
        )
        if not plugin_root_ok:
            log(
                f"[SCENARIO][pre_nav][stabilization] failed scenario='{scenario_id}' "
                f"reason='{plugin_root_reason}'"
            )
            return False

    pre_nav_ok = _run_pre_navigation_steps(
        client=client,
        dev=dev,
        tab_cfg=tab_cfg,
        transition_fast_path=is_transition_entry_fast_path and not is_strict_main_tab_scenario,
    )
    start_open_summary = getattr(client, "last_start_open_summary", {})
    if isinstance(start_open_summary, dict):
        start_open_summary["context_ok"] = trace_context_ok
        start_open_summary["focus_align_attempted"] = focus_align_attempted
        start_open_summary["focus_align_ok"] = focus_align_ok
        start_open_summary["focus_align_reason"] = str(focus_align_result.get("reason", "") or "")
        start_open_summary["pre_navigation_success"] = bool(pre_nav_ok)
        setattr(client, "last_start_open_summary", start_open_summary)
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
        verify_reads=1 if is_transition_entry_fast_path and not is_strict_main_tab_scenario else 2,
    )
    trace_anchor_matched = bool(stabilize_result.get("matched")) if isinstance(stabilize_result, dict) else False
    trace_anchor_stable = bool(stabilize_result.get("ok")) if isinstance(stabilize_result, dict) else False
    setattr(client, "last_anchor_stabilize_result", stabilize_result if isinstance(stabilize_result, dict) else {})
    log(
        f"[TRACE][open_scenario] scenario='{scenario_id}' stabilization_mode='{stabilization_mode}' "
        f"focus_align_attempted={focus_align_attempted} focus_align_ok={focus_align_ok} "
        f"focus_align_reason='{focus_align_result.get('reason', '')}' context_ok={trace_context_ok} "
        f"anchor_matched={trace_anchor_matched} anchor_stable={trace_anchor_stable}",
    )
    if not stabilize_result.get("ok"):
        low_conf_allowed, low_conf_reason = _is_new_screen_low_confidence_allowed(
            tab_cfg=tab_cfg,
            stabilize_result=stabilize_result if isinstance(stabilize_result, dict) else {},
            pre_nav_ok=pre_nav_ok,
            screen_context_mode=screen_context_mode,
        )
        if not low_conf_allowed:
            log(
                f"[ANCHOR][scenario_start] stabilization failed tab='{tab_cfg.get('tab_name', '')}' "
                f"scenario='{tab_cfg.get('scenario_id', '')}' "
                f"low_confidence=true reason='{stabilize_result.get('reason', 'not_stable')}'"
            )
            if low_conf_reason == "insufficient_new_screen_evidence":
                log("[ANCHOR][plugin_fallback] skipped reason='insufficient_new_screen_evidence'")
            elif low_conf_reason == "boilerplate_only_candidate":
                log("[ANCHOR][plugin_fallback] rejected candidate reason='boilerplate_like'")
            log(
                f"[ANCHOR][scenario_start] abort low_confidence_fallback=false scenario='{scenario_id}' "
                f"reason='{low_conf_reason}'"
            )
            return False

        start_source = str(stabilize_result.get("start_candidate_source", "") or "fallback_top_content")
        tab_cfg["_scenario_start_mode"] = "low_confidence_fallback"
        tab_cfg["_scenario_anchor_stable"] = False
        tab_cfg["_scenario_start_source"] = start_source
        tab_cfg["_scenario_start_note"] = (
            "scenario start anchor unstable; proceeded with low-confidence fallback start"
        )
        log(
            f"[ANCHOR][scenario_start] stabilization failed but proceeding with low-confidence fallback start "
            f"scenario='{scenario_id}' source='{start_source}' reason='{low_conf_reason}'"
        )
        log(
            "[ANCHOR][plugin_fallback] candidate_label="
            f"'{stabilize_result.get('fallback_candidate_label', '')}' "
            f"candidate_view_id='{stabilize_result.get('fallback_candidate_resource_id', '')}' "
            "reason='new_screen_evidence_confirmed'"
        )
        stabilized_by = "selected" if bool(stabilize_result.get("selected")) else "post_focus_verified"
        log(f"[ANCHOR][plugin_fallback] stabilized_by='{stabilized_by}'")
        log(f"[SCENARIO][start_mode] scenario='{scenario_id}' mode='low_confidence_fallback'")
    if scenario_id == _LIFE_ENERGY_SCENARIO_ID:
        stabilize_reason = str(stabilize_result.get("reason", "") or "").strip().lower()
        should_recheck_entry = stabilize_reason in {"focus_shift", "verified_without_select"}
        recheck_attempts = 2 if should_recheck_entry else 1
        post_focus = client.get_focus(
            dev=dev,
            wait_seconds=min(main_step_wait_seconds, 0.8),
            allow_fallback_dump=False,
            mode="fast",
        )
        post_view_id = (
            str(post_focus.get("viewIdResourceName", "") or post_focus.get("resourceId", "") or "").strip()
            if isinstance(post_focus, dict)
            else ""
        )
        post_label = _node_label_blob(post_focus if isinstance(post_focus, dict) else {})
        generic_navigate_up_only = bool(_safe_regex_search(_LIFE_ENERGY_NAVIGATE_UP_REGEX, post_label)) and not post_view_id
        dump_tree_fn = getattr(client, "dump_tree", None)
        post_nodes: list[dict[str, Any]] = []
        energy_signature_seen = False
        family_signature_seen = False
        for recheck_idx in range(recheck_attempts):
            if callable(dump_tree_fn):
                try:
                    post_nodes = dump_tree_fn(dev=dev)
                except Exception:
                    post_nodes = []
            tree_nodes_with_parent = _iter_tree_nodes_with_parent(post_nodes)
            energy_signature_seen = any(
                _safe_regex_search(r"(?i).*energy.*", _node_label_blob(node)) for node, _ in tree_nodes_with_parent
            )
            family_signature_seen = any(
                _safe_regex_search(_LIFE_ENERGY_FAMILY_CARE_REGEX, _node_label_blob(node))
                for node, _ in tree_nodes_with_parent
            )
            if family_signature_seen and not energy_signature_seen:
                break
            if energy_signature_seen:
                break
            if recheck_idx < recheck_attempts - 1:
                log(
                    f"[SCENARIO][life_energy_guard] recheck scenario='{scenario_id}' "
                    f"attempt={recheck_idx + 1}/{recheck_attempts} reason='missing_energy_signature' "
                    f"stabilize_reason='{stabilize_reason or 'none'}'"
                )
                time.sleep(min(main_step_wait_seconds, 0.35))
        if (generic_navigate_up_only and not energy_signature_seen) or (family_signature_seen and not energy_signature_seen):
            log(
                f"[SCENARIO][life_energy_guard] failed scenario='{scenario_id}' "
                f"generic_navigate_up_only={str(generic_navigate_up_only).lower()} "
                f"family_signature_seen={str(family_signature_seen).lower()} "
                f"energy_signature_seen={str(energy_signature_seen).lower()} "
                "reason='entry_not_confirmed'"
            )
            return False
    if is_transition_entry_fast_path and not is_strict_main_tab_scenario:
        time.sleep(min(main_step_wait_seconds, _TRANSITION_FAST_STEP_WAIT_SECONDS))
    else:
        time.sleep(main_step_wait_seconds)
    start_open_summary = getattr(client, "last_start_open_summary", {})
    if isinstance(start_open_summary, dict):
        start_open_summary["anchor_matched"] = trace_anchor_matched
        start_open_summary["anchor_stable"] = bool(tab_cfg.get("_scenario_anchor_stable", trace_anchor_stable))
        start_open_summary["open_completed"] = True
        setattr(client, "last_start_open_summary", start_open_summary)
    return True


def _get_positive_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int) and value > 0:
        return value
    return fallback


def _normalize_step_index(raw_step_index: Any) -> int:
    if isinstance(raw_step_index, bool):
        return -1
    try:
        return int(raw_step_index)
    except (TypeError, ValueError):
        return -1


def _build_repeat_quality_snapshot(
    *,
    step_index: int,
    fingerprint: str,
    normalized_fingerprint: str,
    recent_fingerprint_history: deque[tuple[int, str]],
    recent_semantic_fingerprint_history: deque[tuple[int, str]],
) -> dict[str, Any]:
    is_recent_duplicate_step = False
    recent_duplicate_distance = 0
    recent_duplicate_of_step = -1
    for prev_step_index, prev_fingerprint in reversed(recent_fingerprint_history):
        if prev_fingerprint == fingerprint:
            is_recent_duplicate_step = True
            recent_duplicate_distance = max(step_index - prev_step_index, 0)
            recent_duplicate_of_step = prev_step_index
            break

    is_recent_semantic_duplicate_step = False
    recent_semantic_duplicate_distance = 0
    recent_semantic_duplicate_of_step = -1
    recent_semantic_unique_count = 1 if normalized_fingerprint else 0
    recent_window_keys: list[str] = []
    if normalized_fingerprint:
        recent_window_keys.append(normalized_fingerprint)
    for prev_step_index, prev_semantic_fingerprint in reversed(recent_semantic_fingerprint_history):
        if prev_semantic_fingerprint:
            recent_window_keys.append(prev_semantic_fingerprint)
        if not is_recent_semantic_duplicate_step and prev_semantic_fingerprint == normalized_fingerprint and normalized_fingerprint:
            is_recent_semantic_duplicate_step = True
            recent_semantic_duplicate_distance = max(step_index - prev_step_index, 0)
            recent_semantic_duplicate_of_step = prev_step_index
    if recent_window_keys:
        recent_semantic_unique_count = len(set(recent_window_keys))

    return {
        "is_recent_duplicate_step": is_recent_duplicate_step,
        "recent_duplicate_distance": recent_duplicate_distance,
        "recent_duplicate_of_step": recent_duplicate_of_step,
        "is_recent_semantic_duplicate_step": is_recent_semantic_duplicate_step,
        "recent_semantic_duplicate_distance": recent_semantic_duplicate_distance,
        "recent_semantic_duplicate_of_step": recent_semantic_duplicate_of_step,
        "recent_semantic_unique_count": recent_semantic_unique_count,
    }


def _normalize_row_decision_inputs(
    row: dict[str, Any],
    *,
    last_fingerprint: str,
    fingerprint_repeat_count: int,
    recent_fingerprint_history: deque[tuple[int, str]],
    recent_semantic_fingerprint_history: deque[tuple[int, str]],
) -> dict[str, Any]:
    fingerprint = build_row_fingerprint(row)
    normalized_fingerprint = build_row_semantic_fingerprint(row)
    if fingerprint == last_fingerprint:
        next_fingerprint_repeat_count = fingerprint_repeat_count + 1
    else:
        next_fingerprint_repeat_count = 0

    step_index = _normalize_step_index(row.get("step_index", -1))
    repeat_quality = _build_repeat_quality_snapshot(
        step_index=step_index,
        fingerprint=fingerprint,
        normalized_fingerprint=normalized_fingerprint,
        recent_fingerprint_history=recent_fingerprint_history,
        recent_semantic_fingerprint_history=recent_semantic_fingerprint_history,
    )
    is_noise_step, noise_reason = is_noise_row(row)
    return {
        "step_index": step_index,
        "fingerprint": fingerprint,
        "normalized_fingerprint": normalized_fingerprint,
        "fingerprint_repeat_count": next_fingerprint_repeat_count,
        "is_duplicate_step": next_fingerprint_repeat_count > 0,
        "is_noise_step": is_noise_step,
        "noise_reason": noise_reason,
        **repeat_quality,
    }


def _build_stop_evaluation_inputs(
    *,
    stop_details: dict[str, Any],
    row: dict[str, Any],
    tab_cfg: dict[str, Any],
) -> dict[str, Any]:
    scenario_type = str(stop_details.get("scenario_type", tab_cfg.get("scenario_type", "content")) or "content")
    is_global_nav_only_scenario = scenario_type == "global_nav"
    is_global_nav = bool(stop_details.get("is_global_nav", False))
    global_nav_reason = str(stop_details.get("global_nav_reason", "") or "")
    if is_global_nav_only_scenario:
        is_global_nav, global_nav_reason = is_global_nav_row(row, scenario_cfg=tab_cfg)
    stop_explain = stop_details.get("stop_explain", {})
    if not isinstance(stop_explain, dict):
        stop_explain = {}
    return {
        "terminal_signal": bool(stop_details.get("terminal", False)),
        "same_like_count": int(stop_details.get("same_like_count", 0) or 0),
        "no_progress": bool(stop_details.get("no_progress", False)),
        "scenario_type": scenario_type,
        "is_global_nav_only_scenario": is_global_nav_only_scenario,
        "is_global_nav": is_global_nav,
        "global_nav_reason": global_nav_reason,
        "after_realign": bool(stop_details.get("after_realign", False)),
        "recent_repeat": bool(stop_details.get("recent_repeat", False)),
        "bounded_two_card_loop": bool(stop_details.get("bounded_two_card_loop", False)),
        "semantic_same_like": bool(stop_details.get("semantic_same_like", False)),
        "recent_duplicate": bool(stop_details.get("recent_duplicate", False)),
        "recent_duplicate_distance": int(stop_details.get("recent_duplicate_distance", 0) or 0),
        "recent_semantic_duplicate": bool(stop_details.get("recent_semantic_duplicate", False)),
        "recent_semantic_duplicate_distance": int(stop_details.get("recent_semantic_duplicate_distance", 0) or 0),
        "recent_semantic_unique_count": int(stop_details.get("recent_semantic_unique_count", 0) or 0),
        "repeat_class": str(stop_details.get("repeat_class", "") or "none"),
        "loop_classification": str(stop_details.get("loop_classification", "") or "none"),
        "strict_duplicate": bool(stop_details.get("strict_duplicate", False)),
        "semantic_duplicate": bool(stop_details.get("semantic_duplicate", False)),
        "hard_no_progress": bool(stop_details.get("hard_no_progress", False)),
        "soft_no_progress": bool(stop_details.get("soft_no_progress", False)),
        "no_progress_class": str(stop_details.get("no_progress_class", "") or "none"),
        "overlay_realign_grace_active": bool(stop_details.get("overlay_realign_grace_active", False)),
        "min_step_gate_blocked": bool(stop_details.get("min_step_gate_blocked", False)),
        "realign_grace_suppressed": bool(stop_details.get("realign_grace_suppressed", False)),
        "repeat_stop_hit": bool(stop_details.get("repeat_stop_hit", False)),
        "eval_reason": str(stop_details.get("reason", "") or "none"),
        "stop_explain_version": str(stop_details.get("stop_explain_version", "") or ""),
        "stop_explain": stop_explain,
    }


def _format_stop_explain_log_fields(stop_eval_inputs: dict[str, Any], decision: str) -> str:
    stop_explain = stop_eval_inputs.get("stop_explain", {})
    if not isinstance(stop_explain, dict):
        stop_explain = {}
    repeat = stop_explain.get("repeat", {})
    if not isinstance(repeat, dict):
        repeat = {}
    no_progress = stop_explain.get("no_progress", {})
    if not isinstance(no_progress, dict):
        no_progress = {}
    overlay_context = stop_explain.get("overlay_context", {})
    if not isinstance(overlay_context, dict):
        overlay_context = {}
    gates = stop_explain.get("gates", {})
    if not isinstance(gates, dict):
        gates = {}
    inputs = stop_explain.get("inputs", {})
    if not isinstance(inputs, dict):
        inputs = {}
    return (
        f"stop_explain_version='{str(stop_eval_inputs.get('stop_explain_version', '') or 'none')}' "
        f"stop_explain_input='step:{int(inputs.get('step_index', 0) or 0)}|move:{str(inputs.get('move_result', '') or 'none')}|"
        f"smart:{str(inputs.get('smart_nav_result', '') or 'none')}|same:{int(inputs.get('same_like_count', 0) or 0)}|"
        f"fail:{int(inputs.get('fail_count', 0) or 0)}' "
        f"stop_explain_repeat='recent:{str(bool(repeat.get('recent_repeat', False))).lower()}|"
        f"class:{str(repeat.get('repeat_class', '') or 'none')}|strict:{str(bool(repeat.get('strict_duplicate', False))).lower()}|"
        f"semantic:{str(bool(repeat.get('semantic_duplicate', False))).lower()}|loop:{str(repeat.get('loop_classification', '') or 'none')}|"
        f"two_card:{str(bool(repeat.get('bounded_two_card_loop', False))).lower()}' "
        f"stop_explain_no_progress='hit:{str(bool(no_progress.get('no_progress', False))).lower()}|"
        f"class:{str(no_progress.get('no_progress_class', '') or 'none')}|hard:{str(bool(no_progress.get('hard_no_progress', False))).lower()}|"
        f"soft:{str(bool(no_progress.get('soft_no_progress', False))).lower()}' "
        f"stop_explain_gate='candidate:{str(bool(gates.get('repeat_trigger_candidate', False))).lower()}|"
        f"min_block:{str(bool(gates.get('min_step_gate_blocked', False))).lower()}|"
        f"realign_suppress:{str(bool(overlay_context.get('realign_grace_suppressed', False))).lower()}|"
        f"realign_active:{str(bool(overlay_context.get('realign_grace_active', False))).lower()}|"
        f"decision:{decision}'"
    )


def _annotate_row_quality(
    row: dict[str, Any],
    *,
    last_fingerprint: str,
    fingerprint_repeat_count: int,
    recent_fingerprint_history: deque[tuple[int, str]],
    recent_semantic_fingerprint_history: deque[tuple[int, str]],
) -> tuple[str, int]:
    decision_inputs = _normalize_row_decision_inputs(
        row,
        last_fingerprint=last_fingerprint,
        fingerprint_repeat_count=fingerprint_repeat_count,
        recent_fingerprint_history=recent_fingerprint_history,
        recent_semantic_fingerprint_history=recent_semantic_fingerprint_history,
    )
    row.update(decision_inputs)
    step_index = int(decision_inputs["step_index"])
    fingerprint = str(decision_inputs["fingerprint"])
    normalized_fingerprint = str(decision_inputs["normalized_fingerprint"])
    recent_fingerprint_history.append((step_index, fingerprint))
    recent_semantic_fingerprint_history.append((step_index, normalized_fingerprint))
    return fingerprint, int(decision_inputs["fingerprint_repeat_count"])


def open_tab_and_anchor(client: A11yAdbClient, dev: str, tab_cfg: dict) -> bool:
    return open_scenario(client, dev, tab_cfg)


def _execute_overlay_for_candidate(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    row: dict[str, Any],
    rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    *,
    output_path: str,
    output_base_dir: str,
    scenario_perf: ScenarioPerfStats | None,
    main_step_index_by_fingerprint: dict[tuple[str, str, str], int],
    expanded_overlay_entries: set[str],
    fingerprint: str,
    candidate_reason: str,
) -> OverlayPhaseResult:
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
        return OverlayPhaseResult(
            candidate_checked=True,
            candidate_reason=candidate_reason,
            classification="unchanged",
            post_realign_pending_steps_delta=0,
        )

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
            return OverlayPhaseResult(
                candidate_checked=True,
                candidate_reason=candidate_reason,
                classification=classification,
                post_realign_pending_steps_delta=2,
            )
        return OverlayPhaseResult(
            candidate_checked=True,
            candidate_reason=candidate_reason,
            classification=classification,
            post_realign_pending_steps_delta=0,
        )

    if classification == "navigation":
        log(
            f"[OVERLAY] overlay routine skipped (navigation) scenario='{tab_cfg.get('scenario_id', '')}' "
            f"step={row.get('step_index')}"
        )
    else:
        log(
            f"[OVERLAY] overlay routine skipped (unchanged) scenario='{tab_cfg.get('scenario_id', '')}' "
            f"step={row.get('step_index')}"
        )
    return OverlayPhaseResult(
        candidate_checked=True,
        candidate_reason=candidate_reason,
        classification=classification,
        post_realign_pending_steps_delta=0,
    )


def _overlay_phase(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    row: dict[str, Any],
    rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    *,
    output_path: str,
    output_base_dir: str,
    scenario_perf: ScenarioPerfStats | None,
    main_step_index_by_fingerprint: dict[tuple[str, str, str], int],
    expanded_overlay_entries: set[str],
) -> OverlayPhaseResult:
    is_global_nav_only_scenario = str(tab_cfg.get("scenario_type", "content") or "content").strip().lower() == "global_nav"
    is_candidate, candidate_reason = (False, "blocked_by_global_nav_only")
    if not is_global_nav_only_scenario:
        is_candidate, candidate_reason = is_overlay_candidate(row, tab_cfg)
    if is_candidate:
        fingerprint = make_overlay_entry_fingerprint(tab_cfg["tab_name"], row)
        if fingerprint not in expanded_overlay_entries:
            return _execute_overlay_for_candidate(
                client=client,
                dev=dev,
                tab_cfg=tab_cfg,
                row=row,
                rows=rows,
                all_rows=all_rows,
                output_path=output_path,
                output_base_dir=output_base_dir,
                scenario_perf=scenario_perf,
                main_step_index_by_fingerprint=main_step_index_by_fingerprint,
                expanded_overlay_entries=expanded_overlay_entries,
                fingerprint=fingerprint,
                candidate_reason=candidate_reason,
            )
        else:
            log(f"[OVERLAY] skip already expanded entry fingerprint='{fingerprint}'")
            return OverlayPhaseResult(
                candidate_checked=True,
                candidate_reason=candidate_reason,
                classification="unchanged",
                post_realign_pending_steps_delta=0,
            )
    elif candidate_reason == "blocked_no_overlay_policy":
        log(
            f"[OVERLAY] blocked no_overlay_policy scenario='{tab_cfg.get('scenario_id', '')}' "
            f"tab='{tab_cfg.get('tab_name', '')}' step={row.get('step_index')}"
        )
    elif candidate_reason == "blocked_empty_allow_list":
        log(
            f"[OVERLAY] blocked empty_allow_list scenario='{tab_cfg.get('scenario_id', '')}' "
            f"tab='{tab_cfg.get('tab_name', '')}' step={row.get('step_index')}"
        )
    elif "blocked" in candidate_reason:
        log(
            f"[OVERLAY] blocked by scenario policy scenario='{tab_cfg.get('scenario_id', '')}' "
            f"tab='{tab_cfg.get('tab_name', '')}' step={row.get('step_index')} "
            f"view_id='{row.get('focus_view_id', '')}' label='{row.get('visible_label', '')}'"
        )
    return OverlayPhaseResult(
        candidate_checked=not is_global_nav_only_scenario,
        candidate_reason=candidate_reason,
        classification="unchanged",
        post_realign_pending_steps_delta=0,
    )


def _main_loop_phase(
    client: A11yAdbClient,
    dev: str,
    phase_ctx: CollectionPhaseContext,
) -> MainLoopState:
    tab_cfg = phase_ctx.tab_cfg
    rows = phase_ctx.rows
    all_rows = phase_ctx.all_rows
    scenario_perf = phase_ctx.scenario_perf
    state = phase_ctx.state
    for step_idx in range(1, tab_cfg["max_steps"] + 1):
        log(f"[STEP] START tab='{tab_cfg['tab_name']}' step={step_idx}")
        step_start = time.perf_counter()

        row = client.collect_focus_step(
            dev=dev,
            step_index=step_idx,
            move=True,
            direction="next",
            wait_seconds=phase_ctx.main_step_wait_seconds,
            announcement_wait_seconds=phase_ctx.main_announcement_wait_seconds,
            announcement_idle_wait_seconds=phase_ctx.main_announcement_idle_wait_seconds,
            announcement_max_extra_wait_seconds=phase_ctx.main_announcement_max_extra_wait_seconds,
        )
        step_elapsed = time.perf_counter() - step_start

        row["tab_name"] = tab_cfg["tab_name"]
        row["context_type"] = "main"
        row["parent_step_index"] = ""
        row["overlay_entry_label"] = ""
        row["overlay_recovery_status"] = "after_realign" if state.post_realign_pending_steps > 0 else ""
        row["status"] = "OK"
        row["stop_reason"] = ""
        row["scenario_type"] = str(tab_cfg.get("scenario_type", "content") or "content")
        row["step_elapsed_sec"] = round(step_elapsed, 3)
        row["crop_image"] = "IMAGE"
        row["_step_mono_start"] = time.monotonic() - float(row.get("t_step_start", 0.0) or 0.0)
        row = maybe_capture_focus_crop(client, dev, row, phase_ctx.output_base_dir)
        row.pop("_step_mono_start", None)
        row["step_total_elapsed_sec"] = round(time.perf_counter() - step_start, 3)
        scenario_type = str(tab_cfg.get("scenario_type", "content") or "content").strip().lower()
        if scenario_type == "global_nav":
            expected_view_id = str(row.get("smart_nav_requested_view_id", "") or "").strip()
            resolved_view_id = str(row.get("smart_nav_resolved_view_id", "") or "").strip()
            actual_view_id = str(row.get("smart_nav_actual_view_id", "") or "").strip()
            resolved_label = str(row.get("smart_nav_resolved_label", "") or "").strip()
            actual_label = str(row.get("smart_nav_actual_label", "") or "").strip()
            expected_norm = expected_view_id.lower()
            resolved_norm = resolved_view_id.lower()
            actual_norm = actual_view_id.lower()
            smart_success = bool(row.get("smart_nav_success", False))
            resource_matched = bool(expected_norm and (resolved_norm == expected_norm or actual_norm == expected_norm))
            if smart_success and resource_matched:
                chosen_view_id = resolved_view_id or actual_view_id
                chosen_label = resolved_label or actual_label
                if chosen_view_id:
                    row["focus_view_id"] = chosen_view_id
                if chosen_label:
                    row["visible_label"] = chosen_label
                    row["normalized_visible_label"] = client.normalize_for_comparison(chosen_label)
                row["post_move_verdict_source"] = "smart_nav_result_resource_match"
            elif smart_success:
                row["post_move_verdict_source"] = "smart_nav_result"
        state.last_fingerprint, state.fingerprint_repeat_count = _annotate_row_quality(
            row,
            last_fingerprint=state.last_fingerprint,
            fingerprint_repeat_count=state.fingerprint_repeat_count,
            recent_fingerprint_history=state.recent_fingerprint_history,
            recent_semantic_fingerprint_history=state.recent_semantic_fingerprint_history,
        )
        log(
            f"[ROW] fingerprint='{row.get('fingerprint', '')}' "
            f"normalized_fingerprint='{row.get('normalized_fingerprint', '')}' "
            f"duplicate={str(bool(row.get('is_duplicate_step', False))).lower()} "
            f"recent_duplicate={str(bool(row.get('is_recent_duplicate_step', False))).lower()} "
            f"distance={int(row.get('recent_duplicate_distance', 0) or 0)} "
            f"recent_semantic_duplicate={str(bool(row.get('is_recent_semantic_duplicate_step', False))).lower()} "
            f"semantic_distance={int(row.get('recent_semantic_duplicate_distance', 0) or 0)} "
            f"semantic_window_unique={int(row.get('recent_semantic_unique_count', 0) or 0)} "
            f"noise={str(bool(row.get('is_noise_step', False))).lower()}"
        )

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
        mismatch_reasons, low_confidence_reasons = detect_step_mismatch(row=row, previous_step=state.previous_step_row)
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

        stop, state.fail_count, state.same_count, reason, state.prev_fingerprint, stop_details = should_stop(
            row=row,
            prev_fingerprint=state.prev_fingerprint,
            fail_count=state.fail_count,
            same_count=state.same_count,
            previous_row=state.previous_step_row,
            scenario_type=str(tab_cfg.get("scenario_type", "content") or "content"),
            stop_policy=tab_cfg.get("stop_policy", {}),
            scenario_cfg=tab_cfg,
        )
        stop_eval_inputs = _build_stop_evaluation_inputs(stop_details=stop_details, row=row, tab_cfg=tab_cfg)
        terminal_signal = bool(stop_eval_inputs["terminal_signal"])
        same_like_count = int(stop_eval_inputs["same_like_count"])
        no_progress = bool(stop_eval_inputs["no_progress"])
        scenario_type = str(stop_eval_inputs["scenario_type"])
        is_global_nav_only_scenario = bool(stop_eval_inputs["is_global_nav_only_scenario"])
        is_global_nav = bool(stop_eval_inputs["is_global_nav"])
        global_nav_reason = str(stop_eval_inputs["global_nav_reason"])
        after_realign = bool(stop_eval_inputs["after_realign"])
        recent_repeat = bool(stop_eval_inputs["recent_repeat"])
        bounded_two_card_loop = bool(stop_eval_inputs["bounded_two_card_loop"])
        semantic_same_like = bool(stop_eval_inputs["semantic_same_like"])
        recent_duplicate = bool(stop_eval_inputs["recent_duplicate"])
        recent_duplicate_distance = int(stop_eval_inputs["recent_duplicate_distance"])
        recent_semantic_duplicate = bool(stop_eval_inputs["recent_semantic_duplicate"])
        recent_semantic_duplicate_distance = int(stop_eval_inputs["recent_semantic_duplicate_distance"])
        recent_semantic_unique_count = int(stop_eval_inputs["recent_semantic_unique_count"])
        repeat_class = str(stop_eval_inputs["repeat_class"])
        loop_classification = str(stop_eval_inputs["loop_classification"])
        strict_duplicate = bool(stop_eval_inputs["strict_duplicate"])
        semantic_duplicate = bool(stop_eval_inputs["semantic_duplicate"])
        hard_no_progress = bool(stop_eval_inputs["hard_no_progress"])
        soft_no_progress = bool(stop_eval_inputs["soft_no_progress"])
        no_progress_class = str(stop_eval_inputs["no_progress_class"])
        overlay_realign_grace_active = bool(stop_eval_inputs["overlay_realign_grace_active"])
        min_step_gate_blocked = bool(stop_eval_inputs["min_step_gate_blocked"])
        realign_grace_suppressed = bool(stop_eval_inputs["realign_grace_suppressed"])
        repeat_stop_hit = bool(stop_eval_inputs["repeat_stop_hit"])
        decision = "stop" if stop else "continue"
        eval_reason = str(stop_eval_inputs["eval_reason"])
        explain_log_fields = _format_stop_explain_log_fields(stop_eval_inputs=stop_eval_inputs, decision=decision)
        row["is_global_nav"] = is_global_nav
        row["global_nav_reason"] = global_nav_reason
        log(
            f"[STOP][eval] step={step_idx} scenario='{tab_cfg.get('scenario_id', '')}' "
            f"terminal={str(terminal_signal).lower()} same_like_count={same_like_count} "
            f"no_progress={str(no_progress).lower()} scenario_type='{scenario_type}' "
            f"is_global_nav={str(is_global_nav).lower()} after_realign={str(after_realign).lower()} "
            f"recent_repeat={str(recent_repeat).lower()} bounded_two_card_loop={str(bounded_two_card_loop).lower()} "
            f"semantic_same_like={str(semantic_same_like).lower()} recent_duplicate={str(recent_duplicate).lower()} "
            f"recent_duplicate_distance={recent_duplicate_distance} "
            f"recent_semantic_duplicate={str(recent_semantic_duplicate).lower()} "
            f"recent_semantic_duplicate_distance={recent_semantic_duplicate_distance} "
            f"recent_semantic_unique_count={recent_semantic_unique_count} "
            f"strict_duplicate={str(strict_duplicate).lower()} "
            f"semantic_duplicate={str(semantic_duplicate).lower()} "
            f"repeat_class='{repeat_class}' loop_classification='{loop_classification}' "
            f"hard_no_progress={str(hard_no_progress).lower()} soft_no_progress={str(soft_no_progress).lower()} "
            f"no_progress_class='{no_progress_class}' "
            f"overlay_realign_grace_active={str(overlay_realign_grace_active).lower()} "
            f"min_step_gate_blocked={str(min_step_gate_blocked).lower()} "
            f"realign_grace_suppressed={str(realign_grace_suppressed).lower()} "
            f"repeat_stop_hit={str(repeat_stop_hit).lower()} "
            f"decision='{decision}' reason='{eval_reason}' "
            f"{explain_log_fields}"
        )

        if stop and reason == "repeat_semantic_stall":
            should_escape, escape_gate_reason = should_attempt_stall_escape(
                tab_cfg=tab_cfg,
                row=row,
                stop_details=stop_details,
                stop_reason=reason,
                escape_attempted=state.stall_escape_attempted,
            )
            if should_escape:
                log(
                    f"[STALL] detected scenario='{tab_cfg.get('scenario_id', '')}' step={step_idx} "
                    f"same_like_count={same_like_count} semantic_window_unique_count={recent_semantic_unique_count}"
                )
                state.stall_escape_attempted = True
                log(
                    f"[STALL] attempting escape scenario='{tab_cfg.get('scenario_id', '')}' "
                    f"method='refocus_or_realign'"
                )
                escape_result = attempt_stall_escape(
                    client=client,
                    dev=dev,
                    row=row,
                    step_idx=step_idx,
                    announcement_wait_seconds=phase_ctx.main_announcement_wait_seconds,
                    announcement_idle_wait_seconds=phase_ctx.main_announcement_idle_wait_seconds,
                    announcement_max_extra_wait_seconds=phase_ctx.main_announcement_max_extra_wait_seconds,
                )
                escape_success = bool(escape_result.get("success", False))
                escape_result_reason = str(escape_result.get("reason", "") or "")
                log(f"[STALL] escape result success={str(escape_success).lower()} reason='{escape_result_reason}'")
                row["stall_escape_attempted"] = True
                row["stall_escape_result"] = "success" if escape_success else "failed"
                row["stall_escape_reason"] = escape_result_reason
                if escape_success:
                    stop = False
                    reason = ""
                    log(
                        f"[STOP][eval] step={step_idx} scenario='{tab_cfg.get('scenario_id', '')}' "
                        f"repeat_stop_hit={str(repeat_stop_hit).lower()} but escape_attempted=true"
                    )
                else:
                    reason = "repeat_semantic_stall_after_escape"
                    stop = True
            else:
                if state.stall_escape_attempted or escape_gate_reason == "already_attempted":
                    reason = "repeat_semantic_stall_after_escape"
                log(
                    f"[STOP][eval] step={step_idx} scenario='{tab_cfg.get('scenario_id', '')}' "
                    f"repeat_stop_hit={str(repeat_stop_hit).lower()} but escape_attempted={str(state.stall_escape_attempted).lower()} "
                    f"escape_gate_reason='{escape_gate_reason}'"
                )

        if is_global_nav_only_scenario and not is_global_nav:
            log(
                f"[GLOBAL_NAV][skip] step={step_idx} scenario='{tab_cfg.get('scenario_id', '')}' "
                f"label='{row.get('visible_label', '')}' view_id='{row.get('focus_view_id', '')}' "
                f"nav_reason='{global_nav_reason or 'none'}'"
            )
            if stop and reason in {"global_nav_exit", "global_nav_end"}:
                stop = False
                state.stop_reason = ""
            if state.post_realign_pending_steps > 0:
                state.post_realign_pending_steps -= 1
            continue

        if stop:
            state.stop_triggered = True
            state.stop_reason = reason
            state.stop_step = step_idx
            if reason == "repeat_semantic_stall_after_escape":
                log(
                    f"[STOP][triggered] step={step_idx} scenario='{tab_cfg.get('scenario_id', '')}' "
                    "reason='repeat_semantic_stall_after_escape'"
                )
            row["status"] = "END"
            row["stop_reason"] = reason
            row["stop_triggered"] = True
            row["stop_step"] = step_idx

        rows.append(row)
        all_rows.append(row)
        if scenario_perf is not None:
            scenario_perf.record_row(row)
        row_fingerprint = make_main_fingerprint(row)
        if all(row_fingerprint):
            state.main_step_index_by_fingerprint[row_fingerprint] = step_idx
        if stop or (step_idx % phase_ctx.checkpoint_every == 0):
            save_excel_with_perf(save_excel, all_rows, phase_ctx.output_path, with_images=False, scenario_perf=scenario_perf)

        overlay_result = _overlay_phase(
            client=client,
            dev=dev,
            tab_cfg=tab_cfg,
            row=row,
            rows=rows,
            all_rows=all_rows,
            output_path=phase_ctx.output_path,
            output_base_dir=phase_ctx.output_base_dir,
            scenario_perf=scenario_perf,
            main_step_index_by_fingerprint=state.main_step_index_by_fingerprint,
            expanded_overlay_entries=state.expanded_overlay_entries,
        )
        if overlay_result.post_realign_pending_steps_delta > 0:
            state.post_realign_pending_steps = max(
                state.post_realign_pending_steps,
                overlay_result.post_realign_pending_steps_delta,
            )

        if state.post_realign_pending_steps > 0:
            state.post_realign_pending_steps -= 1

        if stop:
            log(
                f"[STOP][triggered] step={step_idx} scenario='{tab_cfg.get('scenario_id', '')}' "
                f"decision='stop' reason='{reason}'"
            )
            break
        state.previous_step_row = row
    return state


def _persist_phase(phase_ctx: CollectionPhaseContext) -> None:
    rows = phase_ctx.rows
    tab_cfg = phase_ctx.tab_cfg
    state = phase_ctx.state
    scenario_perf = phase_ctx.scenario_perf
    if not state.stop_triggered and rows:
        state.stop_step = int(rows[-1].get("step_index", -1) or -1)
        state.stop_reason = "safety_limit"
        rows[-1]["stop_triggered"] = False
        rows[-1]["stop_step"] = state.stop_step
    log(
        f"[STOP][summary] scenario='{tab_cfg.get('scenario_id', '')}' "
        f"stop_triggered={str(state.stop_triggered).lower()} stop_step={state.stop_step} "
        f"reason='{state.stop_reason or 'none'}'"
    )
    if scenario_perf is not None:
        scenario_perf.finalize()
        log(format_perf_summary("scenario_summary", scenario_perf.summary_dict()))


def _build_open_failed_row(tab_cfg: dict[str, Any], *, stop_reason: str) -> dict[str, Any]:
    row = {
        "tab_name": tab_cfg["tab_name"],
        "step_index": -1,
        "status": "TAB_OPEN_FAILED",
        "stop_reason": stop_reason,
        "crop_image": "",
        "crop_image_path": "",
        "crop_image_saved": False,
    }
    row["fingerprint"] = build_row_fingerprint(row)
    row["fingerprint_repeat_count"] = 0
    row["is_duplicate_step"] = False
    row["is_recent_duplicate_step"] = False
    row["recent_duplicate_distance"] = 0
    row["recent_duplicate_of_step"] = -1
    row["normalized_fingerprint"] = ""
    row["is_recent_semantic_duplicate_step"] = False
    row["recent_semantic_duplicate_distance"] = 0
    row["recent_semantic_duplicate_of_step"] = -1
    row["recent_semantic_unique_count"] = 0
    row["is_noise_step"] = False
    row["noise_reason"] = ""
    return row


def _collect_start_anchor_row(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    *,
    scenario_id: str,
    output_base_dir: str,
    main_step_wait_seconds: float,
    main_announcement_wait_seconds: float,
    main_announcement_idle_wait_seconds: float,
    main_announcement_max_extra_wait_seconds: float,
) -> dict[str, Any]:
    anchor_start = time.perf_counter()
    anchor_row = client.collect_focus_step(
        dev=dev,
        step_index=0,
        move=False,
        wait_seconds=main_step_wait_seconds,
        announcement_wait_seconds=main_announcement_wait_seconds,
        announcement_idle_wait_seconds=main_announcement_idle_wait_seconds,
        announcement_max_extra_wait_seconds=main_announcement_max_extra_wait_seconds,
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
    anchor_row["scenario_start_mode"] = str(tab_cfg.get("_scenario_start_mode", "anchor_stable") or "anchor_stable")
    anchor_row["scenario_start_source"] = str(tab_cfg.get("_scenario_start_source", "explicit_anchor") or "explicit_anchor")
    anchor_row["anchor_stable"] = bool(tab_cfg.get("_scenario_anchor_stable", True))
    anchor_row["review_note"] = str(tab_cfg.get("_scenario_start_note", "") or "")
    anchor_visible = str(anchor_row.get("visible_label", "") or "").strip()
    anchor_speech = str(anchor_row.get("merged_announcement", "") or "").strip()
    anchor_normalized_visible = str(anchor_row.get("normalized_visible_label", "") or "").strip()
    anchor_view_id = str(anchor_row.get("focus_view_id", "") or "").strip()
    anchor_is_global_nav = bool(anchor_row.get("is_global_nav", False))
    log(
        f"[TRACE][anchor_row] scenario='{scenario_id}' step=0 view_id='{anchor_view_id}' "
        f"visible='{anchor_visible}' speech='{anchor_speech}' "
        f"normalized_visible='{anchor_normalized_visible}' is_global_nav={anchor_is_global_nav}",
    )
    anchor_row["_step_mono_start"] = time.monotonic() - float(anchor_row.get("t_step_start", 0.0) or 0.0)
    anchor_row = maybe_capture_focus_crop(client, dev, anchor_row, output_base_dir)
    anchor_row.pop("_step_mono_start", None)
    return anchor_row


def _run_start_pipeline(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    *,
    output_base_dir: str,
    main_step_wait_seconds: float,
    main_announcement_wait_seconds: float,
    main_announcement_idle_wait_seconds: float,
    main_announcement_max_extra_wait_seconds: float,
) -> StartPipelineResult:
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    screen_context_mode = _resolve_screen_context_mode(tab_cfg)
    stabilization_mode = _resolve_stabilization_mode(tab_cfg, screen_context_mode)
    result = StartPipelineResult(
        success=False,
        failure_reason="",
        stabilization_mode=stabilization_mode,
        context_ok=False,
        anchor_matched=False,
        anchor_stable=False,
        focus_align_attempted=False,
        focus_align_ok=False,
        focus_align_reason="",
        pre_navigation_attempted=bool(tab_cfg.get("pre_navigation")),
        pre_navigation_success=False,
        open_completed=False,
        post_open_focus_collected=False,
        should_enter_main_loop=False,
        start_row=None,
        needs_open_failed_row=False,
        anchor_fingerprint="",
        anchor_repeat_count=0,
        prev_fingerprint=("", "", ""),
        recent_fingerprint_history=deque(maxlen=_RECENT_DUPLICATE_WINDOW),
        recent_semantic_fingerprint_history=deque(maxlen=_RECENT_DUPLICATE_WINDOW),
    )

    opened = open_scenario(client, dev, tab_cfg)
    open_summary = getattr(client, "last_start_open_summary", {})
    if isinstance(open_summary, dict):
        result.context_ok = bool(open_summary.get("context_ok"))
        result.anchor_matched = bool(open_summary.get("anchor_matched"))
        result.anchor_stable = bool(open_summary.get("anchor_stable"))
        result.focus_align_attempted = bool(open_summary.get("focus_align_attempted"))
        result.focus_align_ok = bool(open_summary.get("focus_align_ok"))
        result.focus_align_reason = str(open_summary.get("focus_align_reason", "") or "")
        result.pre_navigation_attempted = bool(open_summary.get("pre_navigation_attempted", result.pre_navigation_attempted))
        result.pre_navigation_success = bool(open_summary.get("pre_navigation_success"))
        result.open_completed = bool(open_summary.get("open_completed"))
    tab_trace = getattr(client, "last_tab_stabilization_result", {})
    if isinstance(tab_trace, dict) and not isinstance(open_summary, dict):
        context_payload = tab_trace.get("context", {})
        result.context_ok = bool(context_payload.get("ok")) if isinstance(context_payload, dict) else False
        focus_align_payload = tab_trace.get("focus_align", {})
        if isinstance(focus_align_payload, dict):
            result.focus_align_attempted = bool(focus_align_payload.get("attempted"))
            result.focus_align_ok = bool(focus_align_payload.get("ok"))
            result.focus_align_reason = str(focus_align_payload.get("reason", "") or "")
    if not opened:
        result.failure_reason = "tab_or_anchor_failed"
        result.needs_open_failed_row = True
        return result

    result.open_completed = True
    stabilize_trace = getattr(client, "last_anchor_stabilize_result", {})
    if isinstance(stabilize_trace, dict) and not isinstance(open_summary, dict):
        result.anchor_matched = bool(stabilize_trace.get("matched"))
        result.anchor_stable = bool(stabilize_trace.get("ok"))

    post_open_focus = client.get_focus(dev=dev, wait_seconds=min(main_step_wait_seconds, 1.0), allow_fallback_dump=False, mode="fast")
    post_open_trace = getattr(client, "last_get_focus_trace", {}) if isinstance(getattr(client, "last_get_focus_trace", {}), dict) else {}
    post_view_id = str(post_open_focus.get("viewIdResourceName", "") or post_open_focus.get("resourceId", "") or "").strip() if isinstance(post_open_focus, dict) else ""
    extract_visible_label = getattr(client, "extract_visible_label_from_focus", None)
    if callable(extract_visible_label) and isinstance(post_open_focus, dict):
        post_label = str(extract_visible_label(post_open_focus) or "")
    else:
        post_label = str(
            (post_open_focus.get("text", "") if isinstance(post_open_focus, dict) else "")
            or (post_open_focus.get("contentDescription", "") if isinstance(post_open_focus, dict) else "")
            or ""
        ).strip()
    post_speech = str(
        (post_open_focus.get("talkbackLabel", "") if isinstance(post_open_focus, dict) else "")
        or (post_open_focus.get("mergedLabel", "") if isinstance(post_open_focus, dict) else "")
        or (post_open_focus.get("contentDescription", "") if isinstance(post_open_focus, dict) else "")
        or (post_open_focus.get("text", "") if isinstance(post_open_focus, dict) else "")
        or ""
    ).strip()
    post_bounds = str(post_open_focus.get("boundsInScreen", "") or "").strip() if isinstance(post_open_focus, dict) else ""
    post_source = str(post_open_trace.get("final_payload_source", "none") or "none")
    post_top_level = bool(post_open_trace.get("accepted_with_success_false", False))
    log(
        f"[TRACE][post_open_focus] scenario='{scenario_id}' view_id='{post_view_id}' label='{post_label}' "
        f"speech='{post_speech}' bounds='{post_bounds}' source='{post_source}' top_level={post_top_level}",
    )
    result.post_open_focus_collected = True

    scenario_type = str(tab_cfg.get("scenario_type", "content") or "content").strip().lower()
    is_global_nav_start_gate = scenario_type == "global_nav" and screen_context_mode == "bottom_tab"
    if is_global_nav_start_gate:
        start_gate_ok, _gated_focus = _ensure_global_nav_start_focus(
            client=client,
            dev=dev,
            tab_cfg=tab_cfg,
            scenario_id=scenario_id,
            focused_view_id=post_view_id,
            wait_seconds=main_step_wait_seconds,
        )
        if not start_gate_ok:
            result.failure_reason = "global_nav_start_gate_failed"
            result.needs_open_failed_row = True
            return result

    anchor_row = _collect_start_anchor_row(
        client,
        dev,
        tab_cfg,
        scenario_id=scenario_id,
        output_base_dir=output_base_dir,
        main_step_wait_seconds=main_step_wait_seconds,
        main_announcement_wait_seconds=main_announcement_wait_seconds,
        main_announcement_idle_wait_seconds=main_announcement_idle_wait_seconds,
        main_announcement_max_extra_wait_seconds=main_announcement_max_extra_wait_seconds,
    )
    anchor_fingerprint, anchor_repeat_count = _annotate_row_quality(
        anchor_row,
        last_fingerprint="",
        fingerprint_repeat_count=0,
        recent_fingerprint_history=result.recent_fingerprint_history,
        recent_semantic_fingerprint_history=result.recent_semantic_fingerprint_history,
    )
    log(
        f"[ROW] fingerprint='{anchor_row.get('fingerprint', '')}' "
        f"normalized_fingerprint='{anchor_row.get('normalized_fingerprint', '')}' "
        f"duplicate={str(bool(anchor_row.get('is_duplicate_step', False))).lower()} "
        f"recent_duplicate={str(bool(anchor_row.get('is_recent_duplicate_step', False))).lower()} "
        f"distance={int(anchor_row.get('recent_duplicate_distance', 0) or 0)} "
        f"recent_semantic_duplicate={str(bool(anchor_row.get('is_recent_semantic_duplicate_step', False))).lower()} "
        f"semantic_distance={int(anchor_row.get('recent_semantic_duplicate_distance', 0) or 0)} "
        f"semantic_window_unique={int(anchor_row.get('recent_semantic_unique_count', 0) or 0)} "
        f"noise={str(bool(anchor_row.get('is_noise_step', False))).lower()}"
    )
    result.anchor_stable = bool(tab_cfg.get("_scenario_anchor_stable", result.anchor_stable))
    result.success = True
    result.start_row = anchor_row
    result.anchor_fingerprint = anchor_fingerprint
    result.anchor_repeat_count = anchor_repeat_count
    result.prev_fingerprint = make_main_fingerprint(anchor_row)
    result.should_enter_main_loop = True
    return result


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
    main_announcement_idle_wait_seconds = _get_wait_seconds(
        tab_cfg,
        "main_announcement_idle_wait_seconds",
        0.5,
    )
    main_announcement_max_extra_wait_seconds = _get_wait_seconds(
        tab_cfg,
        "main_announcement_max_extra_wait_seconds",
        1.5,
    )
    checkpoint_every = _get_positive_int(checkpoint_save_every, CHECKPOINT_SAVE_EVERY_STEPS)

    start_result = _run_start_pipeline(
        client,
        dev,
        tab_cfg,
        output_base_dir=output_base_dir,
        main_step_wait_seconds=main_step_wait_seconds,
        main_announcement_wait_seconds=main_announcement_wait_seconds,
        main_announcement_idle_wait_seconds=main_announcement_idle_wait_seconds,
        main_announcement_max_extra_wait_seconds=main_announcement_max_extra_wait_seconds,
    )
    if start_result.needs_open_failed_row:
        failed_row = _build_open_failed_row(
            tab_cfg,
            stop_reason=start_result.failure_reason or "tab_or_anchor_failed",
        )
        rows.append(failed_row)
        all_rows.append(failed_row)
        if scenario_perf is not None:
            scenario_perf.record_row(failed_row)
            scenario_perf.finalize()
            log(format_perf_summary("scenario_summary", scenario_perf.summary_dict()))
        save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
        return rows
    if not start_result.should_enter_main_loop or start_result.start_row is None:
        return rows

    anchor_row = start_result.start_row
    rows.append(anchor_row)
    all_rows.append(anchor_row)
    if scenario_perf is not None:
        scenario_perf.record_row(anchor_row)
    save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
    state = MainLoopState(
        last_fingerprint=start_result.anchor_fingerprint,
        fingerprint_repeat_count=start_result.anchor_repeat_count,
        previous_step_row=anchor_row,
        prev_fingerprint=start_result.prev_fingerprint,
        fail_count=0,
        same_count=0,
        expanded_overlay_entries=set(),
        post_realign_pending_steps=0,
        main_step_index_by_fingerprint={start_result.prev_fingerprint: 0},
        recent_fingerprint_history=start_result.recent_fingerprint_history,
        recent_semantic_fingerprint_history=start_result.recent_semantic_fingerprint_history,
        stop_triggered=False,
        stop_reason="",
        stop_step=-1,
        stall_escape_attempted=False,
    )
    phase_ctx = CollectionPhaseContext(
        tab_cfg=tab_cfg,
        rows=rows,
        all_rows=all_rows,
        output_path=output_path,
        output_base_dir=output_base_dir,
        scenario_perf=scenario_perf,
        checkpoint_every=checkpoint_every,
        main_step_wait_seconds=main_step_wait_seconds,
        main_announcement_wait_seconds=main_announcement_wait_seconds,
        main_announcement_idle_wait_seconds=main_announcement_idle_wait_seconds,
        main_announcement_max_extra_wait_seconds=main_announcement_max_extra_wait_seconds,
        state=state,
    )
    _main_loop_phase(client, dev, phase_ctx)
    _persist_phase(phase_ctx)

    return rows
