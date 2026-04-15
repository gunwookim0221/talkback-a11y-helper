import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

from talkback_lib import A11yAdbClient
from tb_runner.anchor_logic import stabilize_anchor
from tb_runner.constants import (
    CHECKPOINT_SAVE_EVERY_STEPS,
    LOG_LEVEL,
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
COLLECTION_FLOW_GUARD_VERSION = "life-plugin-entry-contract-v8"
COLLECTION_FLOW_OVERLAY_SEAM_VERSION = "pr14-overlay-realign-robustness-v2"
COLLECTION_FLOW_SCROLLTOUCH_OBSERVABILITY_VERSION = "pr41-scrolltouch-semantic-alias-evidence-v1"
COLLECTION_FLOW_XML_ENTRY_VERSION = "pr47-life-plugin-xml-entry-strict-phrase-gate-v1"
COLLECTION_FLOW_PRE_NAV_FAILURE_CAPTURE_VERSION = "pr16-life-air-care-failure-capture-v2"
COLLECTION_FLOW_ENTRY_CONTRACT_VERSION = "pr59-entry-special-state-routing-consistency-v1"
COLLECTION_FLOW_LIFE_RECOVERY_VERSION = "pr58-life-reset-ready-gate-relax-v1"
COLLECTION_FLOW_LIFE_RESET_VERSION = "pr61-life-reset-strict-global-nav-v1"
COLLECTION_FLOW_SCROLLTOUCH_CAPTURE_GATE_VERSION = "pr51-scrolltouch-debug-capture-default-off-v2"
SCROLLTOUCH_DEBUG_CAPTURE_ENABLED = False
SCROLLTOUCH_DEBUG_VERBOSE_LOG_ENABLED = False
_LIFE_AIR_CARE_SCENARIO_ID = "life_air_care_plugin"
_LIFE_AIR_CARE_VERIFY_REGEX = r"(?i)\b(air\s*care|air\s*quality|air\s*comfort)\b"
_HOME_TAB_RESOURCE_ID = "com.samsung.android.oneconnect:id/menu_favorites"
_LIFE_TAB_RESOURCE_ID = "com.samsung.android.oneconnect:id/menu_services"
_PRE_NAV_CAPTURE_REASON_KEYS = {"life_root_not_stable", "action_failed", "no_local_match", "target node not found"}
_ENTRY_TYPE_CARD = "card"
_ENTRY_TYPE_DIRECT_SELECT = "direct_select"
_ENTRY_REASON_NO_MATCH = "no_match"
_ENTRY_REASON_TEXT_ONLY_NO_PROMOTION = "text_only_no_promotion"
_ENTRY_REASON_WRONG_OPEN = "wrong_open"
_ENTRY_REASON_FALSE_SUCCESS_GUARD = "false_success_guard"
_ENTRY_REASON_VERIFY_FAILED = "verify_failed"
_ENTRY_REASON_SUCCESS_VERIFIED = "success_verified"
_ENTRY_REASON_SPECIAL_STATE_HANDLED = "special_state_handled"
_CARD_ENTRY_VERIFY_RECHECK_COUNT = 2
_CARD_ENTRY_VERIFY_RECHECK_SLEEP_SECONDS = 0.2
_DIRECT_SELECT_VERIFY_RECHECK_COUNT = 2
_DIRECT_SELECT_VERIFY_RECHECK_SLEEP_SECONDS = 0.16
_DIRECT_SELECT_NEGATIVE_VERIFY_PERSIST_THRESHOLD = 2
_DIRECT_SELECT_DIAGNOSTIC_SCENARIOS = {"life_pet_care_plugin"}
STRICT_PLUGIN_ENTRY_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "life_air_care_plugin": {"strict": ("air care", "smart air care", "에어 케어"), "title_only": ()},
    "life_home_care_plugin": {"strict": ("home care", "smartthings home care", "홈 케어"), "title_only": ()},
    "life_family_care_plugin": {"strict": ("family care", "패밀리 케어"), "title_only": ()},
    "life_plant_care_plugin": {"strict": ("plant care", "plants", "식물"), "title_only": ()},
    "life_clothing_care_plugin": {"strict": ("clothing care", "shoe care", "의류"), "title_only": ()},
    "life_find_plugin": {"strict": ("smart find",), "title_only": ("find",)},
    "life_video_plugin": {"strict": ("smart video",), "title_only": ("video",)},
    "life_home_monitor_plugin": {"strict": ("home monitor",), "title_only": ("monitor",)},
    "life_music_sync_plugin": {"strict": ("music sync",), "title_only": ("sync",)},
    "life_pet_care_plugin": {"strict": ("pet care", "펫 케어"), "title_only": ()},
}


def _resolve_scrolltouch_debug_flags(tab_cfg: dict[str, Any]) -> tuple[bool, bool]:
    explicit_capture_enabled = bool(tab_cfg.get("scrolltouch_debug_capture_enabled", SCROLLTOUCH_DEBUG_CAPTURE_ENABLED))
    explicit_verbose_log_enabled = bool(
        tab_cfg.get("scrolltouch_debug_verbose_log_enabled", SCROLLTOUCH_DEBUG_VERBOSE_LOG_ENABLED)
    )
    debug_mode_enabled = LOG_LEVEL == "DEBUG"
    debug_capture_enabled = explicit_capture_enabled and debug_mode_enabled
    debug_verbose_log_enabled = explicit_verbose_log_enabled and debug_mode_enabled
    return debug_capture_enabled, debug_verbose_log_enabled




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
    entry_type: str
    entry_contract_reason: str
    entry_contract_detail: str
    special_state_detected: bool
    special_state_kind: str
    special_state_handling: str
    special_state_back_status: str
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


def _has_global_nav_signals(state: list[dict[str, Any]]) -> tuple[bool, int]:
    if not isinstance(state, list):
        return False, 0
    nav_id_tokens = ("menu_favorites", "menu_devices", "menu_services", "menu_automations", "menu_more")
    nav_hits_by_token: set[str] = set()
    for node, _ in _iter_tree_nodes_with_parent(state):
        if not _node_is_visible(node):
            continue
        resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip().lower()
        if "com.samsung.android.oneconnect:id/" not in resource_id:
            continue
        for token in nav_id_tokens:
            if token in resource_id:
                nav_hits_by_token.add(token)
                break
    nav_hits = len(nav_hits_by_token)
    return nav_hits >= 2, nav_hits


def _life_root_state_snapshot(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(nodes, list):
        nodes = []
    flat_nodes = _iter_tree_nodes_with_parent(nodes)
    app_bar_hits = 0
    life_selected = False
    visible_card_hits = 0
    life_root_signature_present = False
    bottom_nav_life_visible = False
    global_nav_visible, bottom_nav_hits = _has_global_nav_signals(nodes)
    service_title_hits = 0
    description_hits = 0
    structure_hits = 0
    navigate_up_hits = 0
    internal_toolbar_hits = 0
    internal_action_hits = 0
    plugin_signature_hits = 0
    action_label_regex = r"(?i)\b(add|more options|profile|member|menu|settings|edit|search|location|qr code)\b"
    toolbar_resource_regex = r"(?i)(toolbar|action_bar|appbar|actionmenu|topappbar)"
    internal_resource_regex = r"(?i)(detail|content_view|plugin|action_menu|overflow)"
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
        if _safe_regex_search(r"(?i)menu_services", resource_id) and selected:
            life_selected = True
        if _safe_regex_search(r"(?i)menu_services", resource_id):
            bottom_nav_life_visible = True
        if _safe_regex_search(r"(?i)\b(add|more options|location|qr code)\b", label_blob):
            app_bar_hits += 1
        if _safe_regex_search(action_label_regex, label_blob):
            internal_action_hits += 1
        if _safe_regex_search(toolbar_resource_regex, resource_id):
            internal_toolbar_hits += 1
        if _safe_regex_search(internal_resource_regex, resource_id):
            plugin_signature_hits += 1
        if _safe_regex_search(_LIFE_ENERGY_FAMILY_CARE_REGEX, label_blob):
            plugin_signature_hits += 1
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
    root_structure_stable = bool(
        (app_bar_hits >= _LIFE_ROOT_APP_BAR_MIN_HITS and (visible_card_hits > 0 or life_root_signature_present))
        or visible_card_hits >= _LIFE_ROOT_VISIBLE_CARD_MIN_HITS
    )
    top_bar_with_global_nav = bool(app_bar_hits >= _LIFE_ROOT_APP_BAR_MIN_HITS and global_nav_visible)
    detail_residue_present = bool(
        (global_nav_visible and navigate_up_hits > 0)
        or (
            global_nav_visible
            and internal_toolbar_hits > 0
            and internal_action_hits > visible_card_hits
            and not root_structure_stable
        )
        or (
            visible_card_hits == 0
            and (internal_toolbar_hits + internal_action_hits + plugin_signature_hits) >= 2
            and (navigate_up_hits > 0 or internal_action_hits > 0)
        )
    )
    life_root_fast_pass = bool(global_nav_visible and not detail_residue_present)
    ok = bool(
        life_root_fast_pass
        or root_structure_stable
        or (top_bar_with_global_nav and not detail_residue_present)
        or (life_root_signature_present and final_score >= _LIFE_ROOT_SCORE_THRESHOLD)
    )
    if ok:
        if life_root_fast_pass:
            pass_reason = "global_nav_visible_without_residue"
        elif root_structure_stable:
            pass_reason = "life_root_structure_stable"
        elif top_bar_with_global_nav:
            pass_reason = "top_bar_with_global_nav"
        else:
            pass_reason = "life_root_signature_and_structure_confirmed"
        fail_reason = ""
    else:
        pass_reason = ""
        fail_reason = "detail_residue_detected" if detail_residue_present else "life_root_not_stable"
    return {
        "life_selected": life_selected,
        "app_bar_hits": app_bar_hits,
        "visible_card_hits": visible_card_hits,
        "life_root_signature_present": life_root_signature_present,
        "bottom_nav_life_visible": bottom_nav_life_visible,
        "global_nav_visible": global_nav_visible,
        "bottom_nav_hits": bottom_nav_hits,
        "root_structure_stable": root_structure_stable,
        "top_bar_with_global_nav": top_bar_with_global_nav,
        "navigate_up_hits": navigate_up_hits,
        "internal_toolbar_hits": internal_toolbar_hits,
        "internal_action_hits": internal_action_hits,
        "plugin_signature_hits": plugin_signature_hits,
        "detail_residue_present": detail_residue_present,
        "life_root_fast_pass": life_root_fast_pass,
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
        detail_residue_present = bool(snapshot.get("detail_residue_present"))
        fast_pass_allowed = bool(snapshot.get("life_root_fast_pass"))
        log(f"[STATE][root_gate] global_nav_visible={str(bool(snapshot.get('global_nav_visible'))).lower()}")
        log(f"[STATE][root_gate] detail_residue_present={str(detail_residue_present).lower()}")
        log(f"[STATE][root_gate] fast_pass_allowed={str(fast_pass_allowed).lower()}")
        log(f"[STATE][residue] internal_toolbar_hits={int(snapshot.get('internal_toolbar_hits', 0) or 0)}")
        log(f"[STATE][residue] internal_action_hits={int(snapshot.get('internal_action_hits', 0) or 0)}")
        log(f"[STATE][residue] plugin_signature_hits={int(snapshot.get('plugin_signature_hits', 0) or 0)}")
        log(f"[STATE][residue] visible_card_hits={int(snapshot.get('visible_card_hits', 0) or 0)}")
        log(
            f"[SCENARIO][pre_nav][stabilization] phase='{phase}' attempt={attempt}/{_PLUGIN_ENTRY_RETRY_COUNT} "
            f"life_selected={str(snapshot.get('life_selected')).lower()} app_bar_hits={snapshot.get('app_bar_hits', 0)} "
            f"visible_card_hits={snapshot.get('visible_card_hits', 0)} "
            f"global_nav_visible={str(snapshot.get('global_nav_visible')).lower()} "
            f"bottom_nav_hits={snapshot.get('bottom_nav_hits', 0)} "
            f"root_structure_stable={str(snapshot.get('root_structure_stable')).lower()} "
            f"life_root_signature_present={str(snapshot.get('life_root_signature_present')).lower()} "
            f"navigate_up_hits={snapshot.get('navigate_up_hits', 0)} "
            f"detail_residue_present={str(detail_residue_present).lower()} "
            f"fast_pass_allowed={str(fast_pass_allowed).lower()} "
            f"family_care_signature_seen={str(family_care_signature_seen).lower()} "
            f"final_score={snapshot.get('final_score', 0)} ok={str(ok).lower()} "
            f"pass_reason='{snapshot.get('pass_reason', '')}' fail_reason='{snapshot.get('fail_reason', '')}'"
        )
        if ok:
            return True, "root_state_stable"
        last_reason = str(snapshot.get("fail_reason", "life_root_not_stable") or "life_root_not_stable")
        normalized_scenario_id = str(scenario_id or "").strip().lower()
        is_life_plugin_gate_phase = (
            phase in {"before_pre_navigation", "focus_align_recheck"}
            and normalized_scenario_id.startswith("life_")
            and normalized_scenario_id.endswith("_plugin")
        )
        if is_life_plugin_gate_phase:
            relaxed_scrolltouch_entry_ok = bool(
                int(snapshot.get("navigate_up_hits", 0) or 0) == 0
                and (
                    bool(snapshot.get("life_selected") or snapshot.get("bottom_nav_life_visible"))
                    or family_care_signature_seen
                )
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
                or family_care_signature_seen
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
                        and (
                            bool(recheck_snapshot.get("life_selected") or recheck_snapshot.get("bottom_nav_life_visible"))
                            or family_care_signature_seen
                        )
                        and int(recheck_snapshot.get("app_bar_hits", 0) or 0) >= _LIFE_ROOT_APP_BAR_MIN_HITS
                    )
                    log(
                        f"[SCENARIO][pre_nav][stabilization][recheck] phase='{phase}' "
                        f"attempt={attempt}/{_PLUGIN_ENTRY_RETRY_COUNT} recheck={recheck_idx}/{_LIFE_ROOT_TRANSIENT_RECHECK_COUNT} "
                        f"life_selected={str(recheck_snapshot.get('life_selected')).lower()} "
                        f"app_bar_hits={recheck_snapshot.get('app_bar_hits', 0)} "
                        f"visible_card_hits={recheck_snapshot.get('visible_card_hits', 0)} "
                        f"global_nav_visible={str(recheck_snapshot.get('global_nav_visible')).lower()} "
                        f"bottom_nav_hits={recheck_snapshot.get('bottom_nav_hits', 0)} "
                        f"root_structure_stable={str(recheck_snapshot.get('root_structure_stable')).lower()} "
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


def _is_life_plugin_scenario(scenario_id: str) -> bool:
    normalized_scenario_id = str(scenario_id or "").strip().lower()
    return bool(normalized_scenario_id.startswith("life_") and normalized_scenario_id.endswith("_plugin"))


def _detect_life_plugin_identity_mismatch(
    *,
    scenario_id: str,
    post_view_id: str,
    post_label: str,
    post_speech: str,
    nodes: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    normalized_scenario_id = str(scenario_id or "").strip().lower()
    expected_regex = ""
    if normalized_scenario_id == "life_plant_care_plugin":
        expected_regex = r"(?i)\bplant"
    elif normalized_scenario_id == "life_clothing_care_plugin":
        expected_regex = r"(?i)\bclothing"
    if not expected_regex:
        return False, ""

    evidence_blobs = [str(post_view_id or ""), str(post_label or ""), str(post_speech or "")]
    if isinstance(nodes, list):
        for node, _ in _iter_tree_nodes_with_parent(nodes):
            evidence_blobs.append(_node_label_blob(node))
            evidence_blobs.append(str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or ""))
    joined_blob = "\n".join(blob for blob in evidence_blobs if str(blob or "").strip())
    family_seen = bool(_safe_regex_search(_LIFE_ENERGY_FAMILY_CARE_REGEX, joined_blob))
    expected_seen = bool(_safe_regex_search(expected_regex, joined_blob))
    if family_seen and not expected_seen:
        return True, "family_care"
    return False, ""


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
        "max_back_count": 3,
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
    max_back_count = policy.get("max_back_count", 3)
    if isinstance(max_back_count, bool) or not isinstance(max_back_count, int) or max_back_count <= 0:
        max_back_count = 3
    policy["max_back_count"] = max(1, min(max_back_count, 3))
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


def _select_recovery_target(client: A11yAdbClient, dev: str, policy: dict[str, Any]) -> tuple[bool, bool, bool, str]:
    resource_id = str(policy.get("resource_id", "") or "").strip()
    target_pattern = str(policy.get("target", "") or "").strip()
    target_type = str(policy.get("target_type", "bottom_tab") or "bottom_tab")
    resource_select_success = False
    label_select_success = False
    if resource_id:
        try:
            resource_select_success = bool(client.select(dev=dev, name=resource_id, type_="r", wait_=3))
        except Exception as exc:
            log(f"[RECOVER][fallback] parse_error='{exc}'")
            return False, False, False, "fallback_result_parse_error"
    if not resource_select_success and target_pattern:
        fallback_type = "a"
        if target_type == "resource_id":
            fallback_type = "r"
        try:
            label_select_success = bool(client.select(dev=dev, name=target_pattern, type_=fallback_type, wait_=3))
        except Exception as exc:
            log(f"[RECOVER][fallback] parse_error='{exc}'")
            return False, False, False, "fallback_result_parse_error"
    return resource_select_success, label_select_success, bool(resource_select_success or label_select_success), "ok"


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


def _analyze_current_state(client: A11yAdbClient, dev: str) -> dict[str, Any]:
    dump_tree_fn = getattr(client, "dump_tree", None)
    if not callable(dump_tree_fn):
        return {
            "package_signature_present": False,
            "app_bar_hits": 0,
        }
    try:
        nodes = dump_tree_fn(dev=dev)
    except Exception:
        return {
            "package_signature_present": False,
            "app_bar_hits": 0,
        }
    node_list = nodes if isinstance(nodes, list) else []
    snapshot = _life_root_state_snapshot(node_list)
    package_signature_present = any(
        "com.samsung.android.oneconnect" in str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").lower()
        for node, _ in _iter_tree_nodes_with_parent(node_list)
    )
    return {
        "package_signature_present": bool(package_signature_present),
        "app_bar_hits": int(snapshot.get("app_bar_hits", 0) or 0),
        "global_nav_visible": bool(snapshot.get("global_nav_visible")),
    }


def _is_inside_smartthings(state: dict[str, Any]) -> bool:
    return bool(
        state.get("package_signature_present")
        or int(state.get("app_bar_hits", 0) or 0) >= 1
        or bool(state.get("global_nav_visible"))
    )


def _is_life_list_ready(snapshot: dict[str, Any]) -> bool:
    global_nav_visible = bool(snapshot.get("global_nav_visible"))
    life_tab_selected = bool(snapshot.get("life_selected") or snapshot.get("bottom_nav_life_visible"))
    return bool(global_nav_visible and life_tab_selected)


def _verify_fresh_life_list_state(
    client: A11yAdbClient,
    dev: str,
    *,
    phase: str,
) -> tuple[bool, str]:
    dump_tree_fn = getattr(client, "dump_tree", None)
    if not callable(dump_tree_fn):
        return False, "dump_tree_not_supported"
    last_reason = "life_list_not_ready"
    for attempt in range(1, _PLUGIN_ENTRY_RETRY_COUNT + 1):
        try:
            nodes = dump_tree_fn(dev=dev)
        except Exception as exc:
            nodes = []
            last_reason = f"dump_failed:{exc}"
        snapshot = _life_root_state_snapshot(nodes if isinstance(nodes, list) else [])
        life_list_ready = _is_life_list_ready(snapshot)
        plugin_card_list_visible = bool(
            int(snapshot.get("visible_card_hits", 0) or 0) > 0 or bool(snapshot.get("life_root_signature_present"))
        )
        log(
            f"[LIFE_RESET] verify phase='{phase}' attempt={attempt}/{_PLUGIN_ENTRY_RETRY_COUNT} "
            f"global_nav_visible={str(bool(snapshot.get('global_nav_visible'))).lower()} "
            f"life_tab_selected={str(bool(snapshot.get('life_selected') or snapshot.get('bottom_nav_life_visible'))).lower()} "
            f"plugin_card_list_visible={str(plugin_card_list_visible).lower()} "
            f"life_list_ready={str(life_list_ready).lower()}"
        )
        if life_list_ready:
            if not plugin_card_list_visible:
                log("[LIFE_RESET] plugin_card_list_visible=false (soft_only=true)")
                return True, "life_tab_ready"
            return True, "life_tab_ready_with_card_evidence"
        last_reason = "life_list_not_ready"
        if attempt < _PLUGIN_ENTRY_RETRY_COUNT:
            time.sleep(0.2)
    return False, last_reason


def _ensure_life_plugin_list_ready(client: A11yAdbClient, dev: str, tab_cfg: dict[str, Any]) -> tuple[bool, str]:
    wait_seconds = _get_wait_seconds(tab_cfg, "back_recovery_wait_seconds", MAIN_STEP_WAIT_SECONDS)
    max_attempts = 2
    scenario_id = str(tab_cfg.get("scenario_id", "") or "").strip() or "unknown"
    invocation_phase = str(tab_cfg.get("_recover_invocation_reason", "") or "").strip() or "default"
    pre_reset_state_logged = False
    log("[LIFE_RESET] start")

    def _read_snapshot() -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        try:
            raw_nodes = client.dump_tree(dev=dev)
        except Exception:
            raw_nodes = []
        nodes = raw_nodes if isinstance(raw_nodes, list) else []
        snapshot = _life_root_state_snapshot(nodes)
        package_signature_present = any(
            "com.samsung.android.oneconnect" in str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").lower()
            for node, _ in _iter_tree_nodes_with_parent(nodes)
        )
        app_inside = bool(
            package_signature_present
            or int(snapshot.get("app_bar_hits", 0) or 0) >= 1
            or bool(snapshot.get("global_nav_visible"))
        )
        return nodes, snapshot, app_inside

    for attempt in range(1, max_attempts + 1):
        current_nodes, snapshot, app_inside = _read_snapshot()
        if not pre_reset_state_logged and scenario_id == "life_plant_care_plugin":
            focused_node = next(
                (
                    node
                    for node, _ in _iter_tree_nodes_with_parent(current_nodes)
                    if bool(node.get("accessibilityFocused")) or bool(node.get("focused"))
                ),
                {},
            )
            focus_view_id = str(
                focused_node.get("viewIdResourceName", "")
                or focused_node.get("resourceId", "")
                or ""
            ).strip()
            focus_label = str(
                focused_node.get("text", "")
                or focused_node.get("contentDescription", "")
                or focused_node.get("talkbackLabel", "")
                or ""
            ).strip()
            log(
                "[RECOVER][pre_life_reset_state] "
                f"scenario='{scenario_id}' "
                f"focus_view_id='{focus_view_id}' "
                f"focus_label='{focus_label}' "
                f"is_global_nav={str(bool(snapshot.get('global_nav_visible'))).lower()} "
                f"back_button_visible={str(bool(snapshot.get('navigate_up_visible'))).lower()} "
                f"bottom_nav_candidates={int(snapshot.get('bottom_nav_hits', 0) or 0)} "
                f"life_tab_candidate_present={str(bool(snapshot.get('bottom_nav_life_visible'))).lower()} "
                f"life_tab_selected_candidate_present={str(bool(snapshot.get('life_selected'))).lower()}"
            )
            pre_reset_state_logged = True
        log(f"[LIFE_RESET] app_inside={str(app_inside).lower()}")
        for _ in range(2):
            if app_inside:
                break
            back_sent = _send_back(client, dev)
            if not back_sent:
                break
            time.sleep(min(max(wait_seconds, 0.2), 0.8))
            _, snapshot, app_inside = _read_snapshot()
            log(f"[LIFE_RESET] app_inside={str(app_inside).lower()}")

        if not app_inside:
            if attempt < max_attempts:
                continue
            log("[LIFE_RESET] success=false fail reason='outside_app'")
            return False, "outside_app"

        bottom_nav_ready = bool(snapshot.get("global_nav_visible"))
        for _ in range(2):
            if bottom_nav_ready:
                break
            back_sent = _send_back(client, dev)
            if not back_sent:
                break
            time.sleep(min(max(wait_seconds, 0.2), 0.8))
            _, snapshot, app_inside = _read_snapshot()
            if not app_inside:
                log("[LIFE_RESET] success=false fail reason='app_exited_after_back'")
                return False, "app_exited_after_back"
            bottom_nav_ready = bool(snapshot.get("global_nav_visible"))
        log(f"[LIFE_RESET] bottom_nav_ready={str(bottom_nav_ready).lower()}")
        if not bottom_nav_ready:
            if attempt < max_attempts:
                continue
            log("[LIFE_RESET] success=false fail reason='bottom_nav_not_ready'")
            return False, "bottom_nav_not_ready"

        try:
            client.select(dev=dev, name=_HOME_TAB_RESOURCE_ID, type_="r", wait_=3)
        except Exception:
            pass
        time.sleep(0.15)

        life_tab_reselected = False
        life_tab_select_mode = "resource_id"
        life_tab_target = _LIFE_TAB_RESOURCE_ID
        life_tab_select_raw: Any = None
        life_tab_verify_ok = bool(snapshot.get("life_selected") or snapshot.get("bottom_nav_life_visible"))
        life_tab_verify_actual = str(snapshot.get("life_selected_text", "") or "").strip()
        log(
            "[LIFE_RESET][tab_reselect_attempt] "
            f"scenario='{scenario_id}' phase='{invocation_phase}' attempt={attempt}/{max_attempts} "
            f"package_inside={str(app_inside).lower()} "
            f"global_nav_visible={str(bool(snapshot.get('global_nav_visible'))).lower()} "
            f"select_mode='{life_tab_select_mode}' target='{life_tab_target}'"
        )
        try:
            life_tab_select_raw = client.select(dev=dev, name=_LIFE_TAB_RESOURCE_ID, type_="r", wait_=3)
            life_tab_reselected = bool(life_tab_select_raw)
        except Exception:
            life_tab_select_raw = None
            life_tab_reselected = False
        if not life_tab_reselected:
            life_tab_select_mode = "announcement_regex_fallback"
            life_tab_target = "(?i).*life.*"
            try:
                life_tab_select_raw = client.select(dev=dev, name="(?i).*life.*", type_="a", wait_=3)
                life_tab_reselected = bool(life_tab_select_raw)
            except Exception:
                life_tab_select_raw = None
                life_tab_reselected = False
        life_tab_reselected_basis = (
            "select_success_only"
            if life_tab_reselected
            else ("select_failed_verify_ok" if life_tab_verify_ok else "select_failed_verify_failed")
        )
        log(
            "[LIFE_RESET][tab_reselect_result] "
            f"scenario='{scenario_id}' phase='{invocation_phase}' attempt={attempt}/{max_attempts} "
            f"select_mode='{life_tab_select_mode}' target='{life_tab_target}' "
            f"select_raw='{life_tab_select_raw}' select_success={str(life_tab_reselected).lower()} "
            f"verify_selected_bottom_tab_ok={str(life_tab_verify_ok).lower()} "
            f"verify_actual='{life_tab_verify_actual}' "
            "verify_source='pre_select_snapshot' "
            f"life_tab_reselected={str(life_tab_reselected).lower()} basis='{life_tab_reselected_basis}'"
        )
        log(f"[LIFE_RESET] life_tab_reselected={str(life_tab_reselected).lower()}")
        if not life_tab_reselected:
            if attempt < max_attempts:
                continue
            log("[LIFE_RESET] success=false fail reason='life_tab_select_failed'")
            return False, "life_tab_select_failed"

        time.sleep(min(max(wait_seconds, 0.2), 0.8))
        life_list_ready, verify_reason = _verify_fresh_life_list_state(client, dev, phase="life_reset")
        log(f"[LIFE_RESET] life_list_ready={str(life_list_ready).lower()}")
        if life_list_ready:
            log(f"[LIFE_RESET] success=true reason='{verify_reason}'")
            return True, verify_reason
        if attempt >= max_attempts:
            log(f"[LIFE_RESET] success=false fail reason='{verify_reason}'")
            return False, verify_reason
    log("[LIFE_RESET] success=false fail reason='unknown'")
    return False, "unknown"


def recover_to_start_state(client: A11yAdbClient, dev: str, tab_cfg: dict[str, Any]) -> bool:
    policy = _resolve_recovery_policy(tab_cfg)
    if not policy.get("enabled", True):
        log("[RECOVER] skipped reason='disabled'")
        return True

    reset_ok, reset_reason = _ensure_life_plugin_list_ready(client, dev, tab_cfg)
    if reset_ok:
        log("[RECOVER] success reason='life_reset_ready'")
        return True
    log(f"[RECOVER] failed reason='{reset_reason}'")
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


def _map_pre_nav_failure_reason_to_entry_reason(reason: str) -> str:
    normalized = str(reason or "").strip().lower()
    if "no_local_match" in normalized or "target node not found" in normalized:
        return _ENTRY_REASON_NO_MATCH
    if "non_actionable_without_promotion" in normalized:
        return _ENTRY_REASON_TEXT_ONLY_NO_PROMOTION
    return _ENTRY_REASON_VERIFY_FAILED


def _is_negative_post_open_focus_signal(view_id: str, label: str, speech: str) -> bool:
    blob = " ".join([str(view_id or "").lower(), str(label or "").lower(), str(speech or "").lower()]).strip()
    if not blob:
        return False
    return bool(
        _safe_regex_search(
            r"(?i)(home_button|\bqr\s*code\b|\bchange\s*location\b|\badd\b|\bmore options\b|menu_(favorites|devices|services|automations|more)|toolbar|actionbar|bottom\s*tab|top\s*chrome)",
            blob,
        )
    )


def _collect_air_list_screen_evidence(
    nodes: list[dict[str, Any]] | None,
    *,
    extra_blobs: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(nodes, list):
        nodes = []
    has_home_button = False
    has_tab_title = False
    has_add_menu_button = False
    has_more_menu_button = False
    has_change_location = False
    has_other_plugin_cards = False
    other_plugin_labels: list[str] = []
    list_container_hits = 0
    other_cards_regex = r"(?i)\b(plants|clothing\s*care|food|energy|pet\s*care|home\s*care)\b"
    for node, _ in _iter_tree_nodes_with_parent(nodes):
        if not _node_is_visible(node):
            continue
        resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip().lower()
        label_blob = _node_label_blob(node)
        if "home_button" in resource_id:
            has_home_button = True
        if "tab_title" in resource_id:
            has_tab_title = True
        if "add_menu_button" in resource_id:
            has_add_menu_button = True
        if "more_menu_button" in resource_id:
            has_more_menu_button = True
        if _safe_regex_search(r"(?i)\bchange\s*location\b", label_blob):
            has_change_location = True
        if _safe_regex_search(other_cards_regex, label_blob):
            has_other_plugin_cards = True
            normalized_label = " ".join(str(label_blob or "").split()).strip()
            if normalized_label and normalized_label not in other_plugin_labels and len(other_plugin_labels) < 5:
                other_plugin_labels.append(normalized_label)
        if _safe_regex_search(r"(?i)(preinstalledservicecard|servicecard|cardtitle|carddescription|divider_text)", resource_id):
            list_container_hits += 1
    if isinstance(extra_blobs, list):
        for blob in extra_blobs:
            if _safe_regex_search(other_cards_regex, str(blob or "")):
                has_other_plugin_cards = True
                break
    has_multi_card_container = list_container_hits >= 2
    has_list_screen_evidence = any(
        (
            has_home_button,
            has_tab_title,
            has_add_menu_button,
            has_more_menu_button,
            has_change_location,
            has_other_plugin_cards,
            has_multi_card_container,
        )
    )
    return {
        "has_home_button": has_home_button,
        "has_tab_title": has_tab_title,
        "has_add_menu_button": has_add_menu_button,
        "has_more_menu_button": has_more_menu_button,
        "has_change_location": has_change_location,
        "has_other_plugin_cards": has_other_plugin_cards,
        "other_plugin_labels_summary": ",".join(other_plugin_labels),
        "has_multi_card_container": has_multi_card_container,
        "has_list_screen_evidence": has_list_screen_evidence,
    }


def _matches_post_open_verify(
    tab_cfg: dict[str, Any],
    view_id: str,
    label: str,
    speech: str,
    *,
    extra_candidates: list[str] | None = None,
) -> bool:
    context_verify = dict(tab_cfg.get("context_verify", {}) or {})
    candidates = [str(view_id or ""), str(label or ""), str(speech or "")]
    if isinstance(extra_candidates, list):
        candidates.extend(str(value or "") for value in extra_candidates if str(value or "").strip())
    verify_tokens = tab_cfg.get("verify_tokens", [])
    if isinstance(verify_tokens, list):
        normalized_blob = " ".join(candidates).lower()
        normalized_tokens = [str(token or "").strip().lower() for token in verify_tokens if str(token or "").strip()]
        if normalized_tokens and any(token in normalized_blob for token in normalized_tokens):
            return True
    text_regex = str(context_verify.get("text_regex", "") or "").strip()
    announcement_regex = str(context_verify.get("announcement_regex", "") or "").strip()
    if text_regex and any(_safe_regex_search(text_regex, value) for value in candidates):
        return True
    if announcement_regex and any(_safe_regex_search(announcement_regex, value) for value in candidates):
        return True
    return False


def _extract_post_open_focus_fields(focus_node: Any) -> tuple[str, str, str]:
    if not isinstance(focus_node, dict):
        return "", "", ""
    view_id = str(focus_node.get("viewIdResourceName", "") or focus_node.get("resourceId", "") or "").strip()
    label = _node_label_blob(focus_node)
    speech = str(
        focus_node.get("talkbackLabel", "")
        or focus_node.get("mergedLabel", "")
        or focus_node.get("contentDescription", "")
        or focus_node.get("text", "")
        or ""
    ).strip()
    return view_id, label, speech


def _has_post_open_negative_verify_token(
    tab_cfg: dict[str, Any],
    view_id: str,
    label: str,
    speech: str,
    *,
    extra_candidates: list[str] | None = None,
) -> bool:
    negative_tokens = tab_cfg.get("negative_verify_tokens", [])
    if not isinstance(negative_tokens, list) or not negative_tokens:
        return False
    candidates = [str(view_id or ""), str(label or ""), str(speech or "")]
    if isinstance(extra_candidates, list):
        candidates.extend(str(value or "") for value in extra_candidates if str(value or "").strip())
    normalized_blob = " ".join(candidates).lower()
    normalized_tokens = [str(token or "").strip().lower() for token in negative_tokens if str(token or "").strip()]
    return bool(normalized_tokens and any(token in normalized_blob for token in normalized_tokens))


def _collect_token_hits(tokens: list[str], values: list[str]) -> list[str]:
    normalized_blob = " ".join(str(value or "") for value in values).lower()
    return [token for token in tokens if token and token in normalized_blob]


def _collect_post_open_visible_text(client: A11yAdbClient, dev: str) -> str:
    dump_tree_fn = getattr(client, "dump_tree", None)
    if not callable(dump_tree_fn):
        return ""
    try:
        nodes = dump_tree_fn(dev=dev)
    except Exception:
        return ""
    if not isinstance(nodes, list) or not nodes:
        return ""
    visible_fragments: list[str] = []
    for node, _ in _iter_tree_nodes_with_parent(nodes):
        if not _node_is_visible(node):
            continue
        label_blob = _node_label_blob(node)
        if not label_blob:
            continue
        visible_fragments.append(label_blob)
        if len(visible_fragments) >= 30:
            break
    return " ".join(visible_fragments).strip()


def _build_direct_select_verify_candidates(
    *,
    stabilize_result: dict[str, Any],
    visible_verify_text: str,
    transition_verify_hint: str,
    post_click_transition_same_screen: bool,
) -> list[str]:
    extra_candidates: list[str] = []
    if visible_verify_text:
        extra_candidates.extend([visible_verify_text, visible_verify_text.lower()])
    if not post_click_transition_same_screen and transition_verify_hint:
        extra_candidates.append(transition_verify_hint)
    fallback_label = str(stabilize_result.get("fallback_candidate_label", "") or "").strip()
    fallback_resource_id = str(stabilize_result.get("fallback_candidate_resource_id", "") or "").strip()
    if fallback_label:
        extra_candidates.append(fallback_label)
    if fallback_resource_id:
        extra_candidates.append(fallback_resource_id)
    verify_row = stabilize_result.get("verify_row", {})
    if isinstance(verify_row, dict):
        for key in (
            "visible_label",
            "merged_announcement",
            "talkback_label",
            "focus_text",
            "announcement",
            "normalized_announcement",
            "focus_view_id",
        ):
            value = str(verify_row.get(key, "") or "").strip()
            if value:
                extra_candidates.append(value)
    return extra_candidates


def _resolve_anchor_fallback_source(stabilize_result: dict[str, Any]) -> str:
    if not isinstance(stabilize_result, dict):
        return ""
    start_candidate_source = str(stabilize_result.get("start_candidate_source", "") or "").strip().lower()
    if start_candidate_source == "fallback_top_level":
        return "top_level_fallback"
    if start_candidate_source == "fallback_focus":
        return "focus_fallback"
    return ""


def _is_air_verified_entry_context(
    *,
    scenario_id: str,
    pre_navigation_success: bool,
    post_click_transition_signal: str,
    post_click_transition_same_screen: bool,
    post_view_id: str,
    post_label: str,
    post_speech: str,
    stabilize_result: dict[str, Any],
    anchor_fallback_source: str,
    air_anchor_fallback_accepted: bool,
    air_list_screen_evidence: dict[str, bool] | None = None,
) -> tuple[bool, str]:
    normalized_scenario_id = str(scenario_id or "").strip().lower()
    normalized_signal = str(post_click_transition_signal or "").strip().lower()
    normalized_fallback_source = str(anchor_fallback_source or "").strip().lower()
    has_transition_signal = bool(normalized_signal == "air_care_verify" or post_click_transition_same_screen is False)
    fallback_accepted = bool(
        normalized_fallback_source in {"top_level_fallback", "focus_fallback"} or bool(air_anchor_fallback_accepted)
    )
    if normalized_scenario_id != _LIFE_AIR_CARE_SCENARIO_ID:
        return False, "not_air_care_scenario"
    if not bool(pre_navigation_success):
        return False, "pre_navigation_not_verified"
    if isinstance(air_list_screen_evidence, dict) and bool(air_list_screen_evidence.get("has_list_screen_evidence")):
        log(
            "[VERIFY][air][reject_basis] reason='list_screen_evidence' "
            f"has_home_button={str(bool(air_list_screen_evidence.get('has_home_button'))).lower()} "
            f"has_change_location={str(bool(air_list_screen_evidence.get('has_change_location'))).lower()} "
            f"has_add_button={str(bool(air_list_screen_evidence.get('has_add_menu_button'))).lower()} "
            f"has_more_options={str(bool(air_list_screen_evidence.get('has_more_menu_button'))).lower()} "
            f"has_other_plugin_cards={str(bool(air_list_screen_evidence.get('has_other_plugin_cards'))).lower()} "
            f"other_plugin_labels_summary='{str(air_list_screen_evidence.get('other_plugin_labels_summary', '') or 'none')}'"
        )
        return False, "list_screen_evidence"

    verify_row = stabilize_result.get("verify_row", {}) if isinstance(stabilize_result, dict) else {}
    if not isinstance(verify_row, dict):
        verify_row = {}

    post_focus_is_top_chrome = _is_negative_post_open_focus_signal(post_view_id, post_label, post_speech)
    fallback_label = str(stabilize_result.get("fallback_candidate_label", "") or "").strip() if isinstance(stabilize_result, dict) else ""
    fallback_resource_id = (
        str(stabilize_result.get("fallback_candidate_resource_id", "") or "").strip() if isinstance(stabilize_result, dict) else ""
    )
    fallback_is_top_chrome = _is_negative_post_open_focus_signal(fallback_resource_id, fallback_label, "")
    list_screen_regex = (
        r"(?i)(preinstalledservicecard|servicecard|cardtitle|carddescription|divider_text|"
        r"\b(plants|clothing\s*care|food|energy|pet\s*care|home\s*care)\b)"
    )
    post_focus_blob = " ".join([post_view_id, post_label, post_speech]).strip()
    fallback_blob = " ".join([fallback_resource_id, fallback_label]).strip()
    if (
        post_focus_is_top_chrome
        or fallback_is_top_chrome
        or _safe_regex_search(list_screen_regex, post_focus_blob)
        or _safe_regex_search(list_screen_regex, fallback_blob)
    ):
        return False, "list_screen_focus"

    evidence_candidates: list[tuple[str, str, str]] = [
        (post_view_id, post_label, post_speech),
        (fallback_resource_id, fallback_label, ""),
        (
            str(verify_row.get("focus_view_id", "") or "").strip(),
            str(verify_row.get("visible_label", "") or "").strip(),
            str(verify_row.get("talkback_label", "") or verify_row.get("merged_announcement", "") or "").strip(),
        ),
    ]
    for evidence_view_id, evidence_label, evidence_speech in evidence_candidates:
        evidence_blob = " ".join([evidence_view_id, evidence_label, evidence_speech]).strip()
        if not _safe_regex_search(_LIFE_AIR_CARE_VERIFY_REGEX, evidence_blob):
            continue
        negative_evidence_summary: list[str] = []
        if _is_negative_post_open_focus_signal(evidence_view_id, evidence_label, evidence_speech):
            negative_evidence_summary.append("top_chrome_or_menu_signal")
        if _safe_regex_search(list_screen_regex, evidence_blob):
            negative_evidence_summary.append("list_screen_pattern")
        if negative_evidence_summary:
            continue
        has_plugin_body_focus = bool(evidence_label or evidence_speech) and not _is_negative_post_open_focus_signal(
            evidence_view_id,
            evidence_label,
            evidence_speech,
        )
        log(
            "[VERIFY][air][success_basis] "
            "reason='air_internal_content_signal' "
            f"same_screen={str(bool(post_click_transition_same_screen)).lower()} "
            f"signal='{normalized_signal or 'none'}' "
            f"has_air_text=true has_air_content_signal=true has_plugin_body_focus={str(has_plugin_body_focus).lower()} "
            "negative_evidence_present=false negative_evidence_summary='none'"
        )
        return True, "air_internal_content_signal"
    if not has_transition_signal:
        return False, "missing_transition_signal"
    if not fallback_accepted:
        return False, "fallback_not_accepted"
    return False, "air_internal_content_missing"


def _classify_special_post_open_state(
    tab_cfg: dict[str, Any],
    *,
    post_view_id: str,
    post_label: str,
    post_speech: str,
    visible_verify_text: str,
    matches_verify: bool,
    post_nodes: list[dict[str, Any]] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    if str(tab_cfg.get("entry_type", _ENTRY_TYPE_CARD) or _ENTRY_TYPE_CARD).strip().lower() != _ENTRY_TYPE_CARD:
        return False, "", {}
    handling = str(tab_cfg.get("special_state_handling", "") or "").strip().lower() or "back_after_read"

    special_tokens_raw = tab_cfg.get("special_state_tokens", [])
    cta_tokens_raw = tab_cfg.get("special_state_cta_tokens", [])
    intro_like_min_length = int(tab_cfg.get("special_state_intro_like_min_length", 80) or 80)
    special_tokens = [str(token or "").strip().lower() for token in special_tokens_raw if str(token or "").strip()]
    cta_tokens = [str(token or "").strip().lower() for token in cta_tokens_raw if str(token or "").strip()]
    if not isinstance(post_nodes, list):
        post_nodes = []

    blob_candidates = [post_view_id, post_label, post_speech, visible_verify_text]
    normalized_blob = " ".join(str(value or "") for value in blob_candidates).lower()
    if not normalized_blob.strip() and not post_nodes:
        return False, "", {}

    special_hits = [token for token in special_tokens if token in normalized_blob]
    cta_hits = [token for token in cta_tokens if token in normalized_blob]
    generic_cta_tokens = ("start", "get started", "connect", "set up", "setup", "continue", "next", "try")
    generic_cta_hits = [token for token in generic_cta_tokens if token in normalized_blob]
    if generic_cta_hits:
        cta_hits = sorted(set([*cta_hits, *generic_cta_hits]))

    verify_tokens_raw = tab_cfg.get("verify_tokens", [])
    verify_tokens = [str(token or "").strip().lower() for token in verify_tokens_raw if str(token or "").strip()]
    verify_hit = bool(matches_verify or (verify_tokens and any(token in normalized_blob for token in verify_tokens)))
    long_intro_like = len(visible_verify_text.strip()) >= intro_like_min_length or len(post_speech.strip()) >= intro_like_min_length
    if not long_intro_like and len(post_label.strip()) >= intro_like_min_length:
        long_intro_like = True
    special_hit_count = len(special_hits)
    cta_hit_count = len(cta_hits)

    flat_nodes = _iter_tree_nodes_with_parent(post_nodes)
    meaningful_texts: list[str] = []
    short_cta_nodes = 0
    chrome_hits = 0
    for node, _ in flat_nodes:
        if not _node_is_visible(node):
            continue
        view_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip().lower()
        if view_id and ("toolbar" in view_id or "appbar" in view_id or "action_bar" in view_id or "navigate_up" in view_id):
            chrome_hits += 1
        text_blob = _node_label_blob(node).strip()
        if not text_blob:
            continue
        lowered = text_blob.lower()
        meaningful_texts.append(lowered)
        token_len = len(lowered.split())
        if token_len <= 4 and any(token in lowered for token in generic_cta_tokens):
            short_cta_nodes += 1
    unique_text_count = len(set(meaningful_texts))
    low_content_diversity = bool(unique_text_count and unique_text_count <= 5)
    cta_pair = 1 <= short_cta_nodes <= 2
    intro_focus_like = bool(post_label.strip() and len(post_label.strip()) >= 24 and "list" not in post_view_id and "recycler" not in post_view_id)
    top_chrome_intro_cta = bool(chrome_hits >= 1 and (cta_hit_count >= 1 or cta_pair) and long_intro_like)

    detected = bool(
        ((verify_hit and cta_hit_count >= 1 and special_hit_count >= 1 and (long_intro_like or special_hit_count >= 2)))
        or (
            (cta_hit_count >= 1 or cta_pair)
            and long_intro_like
            and (low_content_diversity or top_chrome_intro_cta or intro_focus_like)
        )
    )
    signals: list[str] = []
    if long_intro_like:
        signals.append("long_intro")
    if cta_hit_count >= 1 or cta_pair:
        signals.append("cta")
    if low_content_diversity:
        signals.append("low_content_diversity")
    if top_chrome_intro_cta:
        signals.append("top_chrome_intro_cta")
    if intro_focus_like:
        signals.append("intro_focus")
    if verify_hit and special_hit_count >= 1:
        signals.append("verify_and_special_token")
    return detected, "setup_needed_or_empty_state" if detected else "", {
        "signals": signals,
        "special_hits": special_hits,
        "cta_hits": cta_hits,
        "verify_hit": verify_hit,
        "long_intro_like": long_intro_like,
        "low_content_diversity": low_content_diversity,
        "cta_pair": cta_pair,
        "top_chrome_intro_cta": top_chrome_intro_cta,
        "intro_focus_like": intro_focus_like,
        "handling": handling,
    }


def _get_card_entry_spec(tab_cfg: dict[str, Any], target: str) -> dict[str, Any]:
    entry_match = tab_cfg.get("entry_match", {})
    if not isinstance(entry_match, dict):
        entry_match = {}
    title_patterns = entry_match.get("title_patterns", [])
    if not isinstance(title_patterns, list):
        title_patterns = []
    description_patterns = entry_match.get("description_patterns", [])
    if not isinstance(description_patterns, list):
        description_patterns = []
    resource_patterns = entry_match.get("resource_patterns", [])
    if not isinstance(resource_patterns, list):
        resource_patterns = []
    semantic_probe_cfg = entry_match.get("semantic_probe", {})
    if not isinstance(semantic_probe_cfg, dict):
        semantic_probe_cfg = {}
    semantic_aliases = semantic_probe_cfg.get("aliases", [])
    if not isinstance(semantic_aliases, list):
        semantic_aliases = []
    semantic_hint_tokens = semantic_probe_cfg.get("hint_tokens", [])
    if not isinstance(semantic_hint_tokens, list):
        semantic_hint_tokens = []
    generic_weak_tokens = semantic_probe_cfg.get("generic_weak_tokens", [])
    if not isinstance(generic_weak_tokens, list):
        generic_weak_tokens = []
    normalized_target = str(target or "").strip()
    normalized_title_patterns = [str(pattern or "").strip() for pattern in title_patterns if str(pattern or "").strip()]
    if normalized_target and not normalized_title_patterns:
        normalized_title_patterns = [normalized_target]
    return {
        "title_patterns": normalized_title_patterns,
        "description_patterns": [str(pattern or "").strip() for pattern in description_patterns if str(pattern or "").strip()],
        "resource_patterns": [str(pattern or "").strip() for pattern in resource_patterns if str(pattern or "").strip()],
        "allow_description_match": bool(entry_match.get("allow_description_match")),
        "semantic_probe_aliases": [str(item or "").strip().lower() for item in semantic_aliases if str(item or "").strip()],
        "semantic_probe_hint_tokens": [str(item or "").strip().lower() for item in semantic_hint_tokens if str(item or "").strip()],
        "semantic_probe_generic_weak_tokens": [str(item or "").strip().lower() for item in generic_weak_tokens if str(item or "").strip()],
    }


def _capture_pre_navigation_failure_bundle(
    client: A11yAdbClient,
    dev: str,
    *,
    scenario_id: str,
    failure_phase: str,
    failure_reason: str,
    step_index: int,
    target_regex: str,
    capture_run_id: str = "",
    log_fn: Callable[..., None] = log,
) -> str:
    normalized_scenario_id = str(scenario_id or "").strip().lower()
    normalized_reason = str(failure_reason or "").strip().lower()
    if normalized_scenario_id != _LIFE_AIR_CARE_SCENARIO_ID:
        return ""
    if normalized_reason not in _PRE_NAV_CAPTURE_REASON_KEYS:
        return ""

    capture_root_id = str(capture_run_id or "").strip() or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle_dir = Path("output") / "capture_bundles" / normalized_scenario_id / capture_root_id / "final_failure"
    bundle_path = str(bundle_dir)
    log_fn(
        f"[CAPTURE][pre_nav_failure] start scenario='{normalized_scenario_id}' "
        f"phase='{str(failure_phase or '')}' reason='{str(failure_reason or '')}' step={max(step_index, 0)}"
    )
    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log_fn(
            f"[CAPTURE][pre_nav_failure] failed path='{bundle_path}' reason='mkdir_failed:{exc}' "
            "saved_files='' failed_files='bundle_dir'"
        )
        return ""

    screenshot_path = bundle_dir / "screenshot.png"
    window_dump_path = bundle_dir / "window_dump.xml"
    helper_dump_path = bundle_dir / "helper_dump.json"
    focus_payload_path = bundle_dir / "focus_payload.json"
    meta_path = bundle_dir / "meta.json"
    saved_files: list[str] = []
    failed_files: list[str] = []

    try:
        client._take_snapshot(dev, str(screenshot_path))
        saved_files.append("screenshot.png")
    except Exception as exc:
        failed_files.append(f"screenshot.png:{exc}")

    run_fn = getattr(client, "_run", None)
    if callable(run_fn):
        try:
            remote_xml = f"/sdcard/window_dump_{capture_root_id}.xml"
            run_fn(["shell", "uiautomator", "dump", remote_xml], dev=dev)
            run_fn(["pull", remote_xml, str(window_dump_path)], dev=dev)
            run_fn(["shell", "rm", "-f", remote_xml], dev=dev)
            saved_files.append("window_dump.xml")
        except Exception as exc:
            failed_files.append(f"window_dump.xml:{exc}")
    else:
        failed_files.append("window_dump.xml:_run_not_supported")

    helper_dump: Any = []
    dump_tree_fn = getattr(client, "dump_tree", None)
    if callable(dump_tree_fn):
        try:
            helper_dump = dump_tree_fn(dev=dev)
        except Exception as exc:
            helper_dump = {"error": f"dump_tree_failed:{exc}"}
    try:
        helper_dump_path.write_text(json.dumps(helper_dump, ensure_ascii=False, indent=2), encoding="utf-8")
        saved_files.append("helper_dump.json")
    except Exception as exc:
        failed_files.append(f"helper_dump.json:{exc}")

    focus_payload: dict[str, Any] = {}
    get_focus_fn = getattr(client, "get_focus", None)
    if callable(get_focus_fn):
        try:
            focus_payload["focus_node"] = get_focus_fn(dev=dev, wait_seconds=0.8, allow_fallback_dump=False, mode="fast")
        except Exception as exc:
            focus_payload["focus_error"] = f"get_focus_failed:{exc}"
    trace = getattr(client, "last_get_focus_trace", {})
    if isinstance(trace, dict):
        focus_payload["get_focus_trace"] = trace
    try:
        focus_payload_path.write_text(json.dumps(focus_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        saved_files.append("focus_payload.json")
    except Exception as exc:
        failed_files.append(f"focus_payload.json:{exc}")

    serial = ""
    try:
        serial = str(client._resolve_serial(dev) or "")
    except Exception:
        serial = ""
    meta = {
        "version": COLLECTION_FLOW_PRE_NAV_FAILURE_CAPTURE_VERSION,
        "scenario_id": normalized_scenario_id,
        "failure_phase": str(failure_phase or ""),
        "failure_reason": str(failure_reason or ""),
        "step_index": int(step_index),
        "target_regex": str(target_regex or ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "device_serial": serial,
    }
    try:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        saved_files.append("meta.json")
    except Exception as exc:
        failed_files.append(f"meta.json:{exc}")

    saved_summary = ",".join(saved_files) if saved_files else ""
    failed_summary = ",".join(failed_files) if failed_files else ""
    if failed_files:
        log_fn(
            f"[CAPTURE][pre_nav_failure] failed path='{bundle_path}' reason='partial_failure' "
            f"saved_files='{saved_summary}' failed_files='{failed_summary}'"
        )
    else:
        log_fn(
            f"[CAPTURE][pre_nav_failure] saved path='{bundle_path}' files='{saved_summary}'"
        )

    return bundle_path


def _capture_scrolltouch_step_bundle(
    client: A11yAdbClient,
    dev: str,
    *,
    scenario_id: str,
    capture_run_id: str,
    step_index: int,
    scroll_step: int,
    target_regex: str,
    selected: bool,
    selected_reason: str,
    candidate_stats: dict[str, Any] | None,
    selected_meta: dict[str, Any] | None = None,
    log_fn: Callable[..., None] = log,
) -> str:
    normalized_scenario_id = str(scenario_id or "").strip().lower()
    if normalized_scenario_id != _LIFE_AIR_CARE_SCENARIO_ID:
        return ""

    capture_root_id = str(capture_run_id or "").strip() or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stats_map = candidate_stats if isinstance(candidate_stats, dict) else {}
    selected_meta_map = selected_meta if isinstance(selected_meta, dict) else {}
    bundle_dir = Path("output") / "capture_bundles" / normalized_scenario_id / capture_root_id / f"step_{max(int(scroll_step), 0):02d}"
    bundle_path = str(bundle_dir)
    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log_fn(
            f"[CAPTURE][scrolltouch_step] failed path='{bundle_path}' step={max(int(scroll_step), 0)} reason='mkdir_failed:{exc}'"
        )
        return ""

    screenshot_path = bundle_dir / "screenshot.png"
    helper_dump_path = bundle_dir / "helper_dump.json"
    window_dump_path = bundle_dir / "window_dump.xml"
    promotion_debug_meta_path = bundle_dir / "promotion_debug_meta.json"
    meta_path = bundle_dir / "meta.json"
    first_failure_reason = ""

    try:
        client._take_snapshot(dev, str(screenshot_path))
    except Exception as exc:
        first_failure_reason = first_failure_reason or f"snapshot_failed:{exc}"

    helper_dump: Any = []
    dump_tree_fn = getattr(client, "dump_tree", None)
    if callable(dump_tree_fn):
        try:
            helper_dump = dump_tree_fn(dev=dev)
        except Exception as exc:
            first_failure_reason = first_failure_reason or f"dump_tree_failed:{exc}"
            helper_dump = {"error": f"dump_tree_failed:{exc}"}
    try:
        helper_dump_path.write_text(json.dumps(helper_dump, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        first_failure_reason = first_failure_reason or f"helper_dump_write_failed:{exc}"

    should_capture_xml = int(stats_map.get("partial_match_count", 0) or 0) > 0
    if should_capture_xml:
        run_fn = getattr(client, "_run", None)
        if callable(run_fn):
            remote_xml = f"/sdcard/window_dump_scrolltouch_step_{max(int(scroll_step), 0)}.xml"
            try:
                run_fn(["shell", "uiautomator", "dump", remote_xml], dev=dev)
                run_fn(["pull", remote_xml, str(window_dump_path)], dev=dev)
            except Exception as exc:
                first_failure_reason = first_failure_reason or f"window_dump_failed:{exc}"
            finally:
                try:
                    run_fn(["shell", "rm", "-f", remote_xml], dev=dev)
                except Exception:
                    pass
        else:
            first_failure_reason = first_failure_reason or "window_dump_failed:run_not_supported"

    promotion_debug_meta = {
        "version": COLLECTION_FLOW_SCROLLTOUCH_OBSERVABILITY_VERSION,
        "scroll_step": int(scroll_step),
        "partial_match_count": int(stats_map.get("partial_match_count", 0) or 0),
        "candidate_stats": stats_map,
        "selected_meta": selected_meta_map,
        "xml_snapshot_saved": bool(should_capture_xml and window_dump_path.exists()),
    }
    try:
        promotion_debug_meta_path.write_text(json.dumps(promotion_debug_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        first_failure_reason = first_failure_reason or f"promotion_debug_meta_write_failed:{exc}"

    rejection_counts = stats_map.get("rejection_counts", {})
    rejection_summary = ""
    if isinstance(rejection_counts, dict) and rejection_counts:
        sorted_rejections = sorted(rejection_counts.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))
        rejection_summary = ", ".join(f"{name}:{count}" for name, count in sorted_rejections[:6])
    visible_samples = stats_map.get("visible_samples", [])
    partial_samples = stats_map.get("partial_samples", [])
    serial = ""
    try:
        serial = str(client._resolve_serial(dev) or "")
    except Exception:
        serial = ""
    meta = {
        "version": COLLECTION_FLOW_SCROLLTOUCH_OBSERVABILITY_VERSION,
        "scenario_id": normalized_scenario_id,
        "phase": "scrolltouch_step",
        "scroll_step": int(scroll_step),
        "step_index": int(step_index),
        "target_regex": str(target_regex or ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "device_serial": serial,
        "visible_candidate_count": int(stats_map.get("visible_candidate_count", 0) or 0),
        "partial_match_count": int(stats_map.get("partial_match_count", 0) or 0),
        "exact_match_count": int(stats_map.get("exact_match_count", 0) or 0),
        "selected": bool(selected),
        "selected_reason": str(selected_reason or ""),
        "visible_top": " | ".join(visible_samples[:3]) if isinstance(visible_samples, list) else "",
        "partial_top": " | ".join(partial_samples[:3]) if isinstance(partial_samples, list) else "",
        "rejection_summary": rejection_summary,
        "selected_meta": selected_meta_map,
        "window_dump_saved": bool(window_dump_path.exists()),
        "promotion_debug_meta_saved": bool(promotion_debug_meta_path.exists()),
    }
    try:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        first_failure_reason = first_failure_reason or f"meta_write_failed:{exc}"

    if first_failure_reason:
        log_fn(
            f"[CAPTURE][scrolltouch_step] failed path='{bundle_path}' step={max(int(scroll_step), 0)} reason='{first_failure_reason}'"
        )
    else:
        log_fn(
            f"[CAPTURE][scrolltouch_step] saved path='{bundle_path}' step={max(int(scroll_step), 0)} "
            f"visible_candidate_count={int(stats_map.get('visible_candidate_count', 0) or 0)} "
            f"partial_match_count={int(stats_map.get('partial_match_count', 0) or 0)}"
        )
    return bundle_path


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
    strict_life_air_care_mode = scenario_id == _LIFE_AIR_CARE_SCENARIO_ID
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
    saw_air_care_signature = False
    saw_air_list_screen_evidence = False

    for poll_idx in range(max_poll_count):
        probe_index = poll_idx + 1
        current_nodes: list[dict[str, Any]] = []
        if callable(dump_tree_fn):
            try:
                current_nodes = dump_tree_fn(dev=dev)
            except Exception:
                current_nodes = []
        energy_signature_seen = False
        air_list_screen_evidence = _collect_air_list_screen_evidence(current_nodes) if strict_life_air_care_mode else {}
        has_air_text = False
        has_air_content_signal = False
        has_plugin_body_focus = False
        probe_signal = ""
        probe_decision = "neutral"
        for node in current_nodes:
            node_label_blob = _node_label_blob(node)
            if strict_life_air_care_mode and _safe_regex_search(_LIFE_AIR_CARE_VERIFY_REGEX, node_label_blob):
                saw_air_care_signature = True
                has_air_text = True
                node_view_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
                if not _is_negative_post_open_focus_signal(node_view_id, node_label_blob, ""):
                    has_air_content_signal = True
                if bool(air_list_screen_evidence.get("has_list_screen_evidence")):
                    saw_air_list_screen_evidence = True
                    probe_signal = "air_care_verify"
                    probe_decision = "reject_list_screen"
                    log(
                        "[VERIFY][air][reject_basis] reason='list_screen_evidence' "
                        f"has_home_button={str(bool(air_list_screen_evidence.get('has_home_button'))).lower()} "
                        f"has_change_location={str(bool(air_list_screen_evidence.get('has_change_location'))).lower()} "
                        f"has_add_button={str(bool(air_list_screen_evidence.get('has_add_menu_button'))).lower()} "
                        f"has_more_options={str(bool(air_list_screen_evidence.get('has_more_menu_button'))).lower()} "
                        f"has_other_plugin_cards={str(bool(air_list_screen_evidence.get('has_other_plugin_cards'))).lower()} "
                        f"other_plugin_labels_summary='{str(air_list_screen_evidence.get('other_plugin_labels_summary', '') or 'none')}'"
                    )
                    continue
                probe_signal = "air_care_verify"
                probe_decision = "candidate_air_success"
                log(
                    "[VERIFY][air][probe] "
                    f"probe_index={probe_index}/{max_poll_count} same_screen=false signal='{probe_signal}' "
                    f"has_home_button={str(bool(air_list_screen_evidence.get('has_home_button'))).lower()} "
                    f"has_change_location={str(bool(air_list_screen_evidence.get('has_change_location'))).lower()} "
                    f"has_add_button={str(bool(air_list_screen_evidence.get('has_add_menu_button'))).lower()} "
                    f"has_more_options={str(bool(air_list_screen_evidence.get('has_more_menu_button'))).lower()} "
                    f"has_other_plugin_cards={str(bool(air_list_screen_evidence.get('has_other_plugin_cards'))).lower()} "
                    f"has_air_text={str(has_air_text).lower()} has_air_content_signal={str(has_air_content_signal).lower()} "
                    f"has_plugin_body_focus={str(has_plugin_body_focus).lower()} decision='{probe_decision}'"
                )
                return True, "air_care_verify"
            if strict_life_energy_mode and _safe_regex_search(patterns.get("context_text", ""), node_label_blob):
                energy_signature_seen = True
            matched, signal = _node_matches_transition_pattern(node, patterns)
            if matched:
                if strict_life_air_care_mode and signal == "anchor_match":
                    continue
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
                if strict_life_air_care_mode:
                    focus_label = _node_label_blob(focus_node)
                    if _safe_regex_search(_LIFE_AIR_CARE_VERIFY_REGEX, focus_label):
                        saw_air_care_signature = True
                        has_air_text = True
                        focus_view_id = str(
                            focus_node.get("viewIdResourceName", "") or focus_node.get("resourceId", "") or ""
                        ).strip()
                        has_plugin_body_focus = not _is_negative_post_open_focus_signal(focus_view_id, focus_label, "")
                        has_air_content_signal = has_air_content_signal or has_plugin_body_focus
                        if bool(air_list_screen_evidence.get("has_list_screen_evidence")):
                            saw_air_list_screen_evidence = True
                            probe_signal = "air_care_focus_verify"
                            probe_decision = "reject_list_screen"
                            continue
                        probe_signal = "air_care_focus_verify"
                        probe_decision = "candidate_air_success"
                        log(
                            "[VERIFY][air][probe] "
                            f"probe_index={probe_index}/{max_poll_count} same_screen=false signal='{probe_signal}' "
                            f"has_home_button={str(bool(air_list_screen_evidence.get('has_home_button'))).lower()} "
                            f"has_change_location={str(bool(air_list_screen_evidence.get('has_change_location'))).lower()} "
                            f"has_add_button={str(bool(air_list_screen_evidence.get('has_add_menu_button'))).lower()} "
                            f"has_more_options={str(bool(air_list_screen_evidence.get('has_more_menu_button'))).lower()} "
                            f"has_other_plugin_cards={str(bool(air_list_screen_evidence.get('has_other_plugin_cards'))).lower()} "
                            f"has_air_text={str(has_air_text).lower()} has_air_content_signal={str(has_air_content_signal).lower()} "
                            f"has_plugin_body_focus={str(has_plugin_body_focus).lower()} decision='{probe_decision}'"
                        )
                        return True, "air_care_focus_verify"
                if strict_life_air_care_mode:
                    continue
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
            if strict_life_air_care_mode:
                log(
                    "[VERIFY][air][probe] "
                    f"probe_index={probe_index}/{max_poll_count} same_screen=true signal='{probe_signal or 'none'}' "
                    f"has_home_button={str(bool(air_list_screen_evidence.get('has_home_button'))).lower()} "
                    f"has_change_location={str(bool(air_list_screen_evidence.get('has_change_location'))).lower()} "
                    f"has_add_button={str(bool(air_list_screen_evidence.get('has_add_menu_button'))).lower()} "
                    f"has_more_options={str(bool(air_list_screen_evidence.get('has_more_menu_button'))).lower()} "
                    f"has_other_plugin_cards={str(bool(air_list_screen_evidence.get('has_other_plugin_cards'))).lower()} "
                    f"has_air_text={str(has_air_text).lower()} has_air_content_signal={str(has_air_content_signal).lower()} "
                    f"has_plugin_body_focus={str(has_plugin_body_focus).lower()} decision='{probe_decision}'"
                )
            time.sleep(_PRE_NAV_CONFIRM_POLL_SLEEP_SECONDS)
        elif strict_life_air_care_mode:
            log(
                "[VERIFY][air][probe] "
                f"probe_index={probe_index}/{max_poll_count} same_screen=true signal='{probe_signal or 'none'}' "
                f"has_home_button={str(bool(air_list_screen_evidence.get('has_home_button'))).lower()} "
                f"has_change_location={str(bool(air_list_screen_evidence.get('has_change_location'))).lower()} "
                f"has_add_button={str(bool(air_list_screen_evidence.get('has_add_menu_button'))).lower()} "
                f"has_more_options={str(bool(air_list_screen_evidence.get('has_more_menu_button'))).lower()} "
                f"has_other_plugin_cards={str(bool(air_list_screen_evidence.get('has_other_plugin_cards'))).lower()} "
                f"has_air_text={str(has_air_text).lower()} has_air_content_signal={str(has_air_content_signal).lower()} "
                f"has_plugin_body_focus={str(has_plugin_body_focus).lower()} decision='{probe_decision}'"
            )

    if strict_life_energy_mode and saw_conflicting_screen_signature:
        return False, "conflicting_screen_signature"
    if strict_life_energy_mode and (saw_dump_change or saw_focus_change):
        return False, "weak_transition_signal_only"
    if strict_life_air_care_mode and saw_air_list_screen_evidence:
        return False, "air_care_list_screen_evidence"
    if strict_life_air_care_mode and not saw_air_care_signature:
        return False, "air_care_verify_missing"
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


def _parse_uiautomator_bounds(bounds_raw: str) -> tuple[int, int, int, int] | None:
    match = re.match(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$", str(bounds_raw or "").strip())
    if not match:
        return None
    left, top, right, bottom = [int(group) for group in match.groups()]
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _load_scrolltouch_xml_nodes(client: A11yAdbClient, dev: str) -> tuple[list[dict[str, Any]], str]:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return [], "run_not_supported"
    remote_xml = "/sdcard/window_dump_scrolltouch.xml"
    try:
        run_fn(["shell", "uiautomator", "dump", remote_xml], dev=dev)
        xml_text = str(run_fn(["shell", "cat", remote_xml], dev=dev) or "").strip()
    except Exception as exc:
        return [], f"dump_failed:{exc}"
    finally:
        try:
            run_fn(["shell", "rm", "-f", remote_xml], dev=dev)
        except Exception:
            pass

    if not xml_text:
        return [], "empty_xml"
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        return [], f"parse_failed:{exc}"

    def _parse_element(element: ET.Element) -> dict[str, Any] | None:
        bounds_tuple = _parse_uiautomator_bounds(str(element.attrib.get("bounds", "") or ""))
        if not bounds_tuple:
            return None
        left, top, right, bottom = bounds_tuple
        node: dict[str, Any] = {
            "text": str(element.attrib.get("text", "") or "").strip(),
            "contentDescription": str(element.attrib.get("content-desc", "") or "").strip(),
            "viewIdResourceName": str(element.attrib.get("resource-id", "") or "").strip(),
            "className": str(element.attrib.get("class", "") or "").strip(),
            "clickable": str(element.attrib.get("clickable", "") or "").strip().lower() == "true",
            "focusable": str(element.attrib.get("focusable", "") or "").strip().lower() == "true",
            "effectiveClickable": str(element.attrib.get("clickable", "") or "").strip().lower() == "true",
            "visibleToUser": str(element.attrib.get("visible-to-user", "") or "").strip().lower() != "false",
            "boundsInScreen": f"{left},{top},{right},{bottom}",
            "children": [],
        }
        children: list[dict[str, Any]] = []
        for child in list(element):
            child_node = _parse_element(child)
            if isinstance(child_node, dict):
                children.append(child_node)
        node["children"] = children
        return node

    hierarchy_children: list[dict[str, Any]] = []
    for child in list(root):
        parsed_child = _parse_element(child)
        if isinstance(parsed_child, dict):
            hierarchy_children.append(parsed_child)

    if not hierarchy_children:
        return [], "no_parsed_nodes"
    return [{"children": hierarchy_children, "visibleToUser": True, "boundsInScreen": "0,0,1,1"}], "ok"


def _run_xml_scroll_search_tap(
    client: A11yAdbClient,
    dev: str,
    *,
    tab_cfg: dict[str, Any],
    target: str,
    type_: str,
    max_scroll_search_steps: int,
    step_wait_seconds: float,
    transition_fast_path: bool,
) -> tuple[bool, str]:
    scenario_id = str(tab_cfg.get("scenario_id", "") or "").strip().lower()
    strict_phrase_cfg = STRICT_PLUGIN_ENTRY_PHRASES.get(scenario_id, {})
    strict_phrases = tuple(str(phrase).strip().lower() for phrase in strict_phrase_cfg.get("strict", ()) if str(phrase).strip())
    title_only_phrases = tuple(
        str(phrase).strip().lower() for phrase in strict_phrase_cfg.get("title_only", ()) if str(phrase).strip()
    )
    strict_phrase_mode = bool(strict_phrases or title_only_phrases)
    negative_phrases: tuple[str, ...] = tuple(
        phrase
        for other_scenario_id, phrase_cfg in STRICT_PLUGIN_ENTRY_PHRASES.items()
        if other_scenario_id != scenario_id
        for phrase in (
            tuple(str(p).strip().lower() for p in phrase_cfg.get("strict", ()) if str(p).strip())
            + tuple(str(p).strip().lower() for p in phrase_cfg.get("title_only", ()) if str(p).strip())
        )
    )
    target_regex = re.compile(target) if target else re.compile(r"$^")
    target_tokens = {token for token in re.split(r"[^0-9a-zA-Z가-힣]+", target.lower()) if len(token) >= 3}
    target_phrase_seed = re.sub(r"[\^\$\|\(\)\[\]\{\}\?\*\+\\]", " ", str(target or ""))
    target_phrase = re.sub(r"\s+", " ", target_phrase_seed).strip().lower()
    excluded_regex = re.compile(
        r"(?i)(home_button|tab_title|\badd\b|\bmore\b|toolbar|actionbar|appbar|navigate up|location|"
        r"menu_(favorites|devices|services|automations|more)|recycler|viewpager)"
    )
    container_regex = re.compile(r"(?i)(card|container|item|layout|frame|linear|relative|constraint|service)")

    def _collect_descendant_blob(node_ref: dict[str, Any]) -> str:
        labels: list[str] = []
        children = node_ref.get("children")
        if not isinstance(children, list):
            return ""
        stack: list[Any] = list(children)
        while stack:
            current = stack.pop()
            if not isinstance(current, dict):
                continue
            labels.append(_node_label_blob(current))
            current_children = current.get("children")
            if isinstance(current_children, list):
                stack.extend(current_children)
        return " ".join(text for text in labels if text).strip()

    def _normalize_for_phrase(value: str) -> str:
        lowered = str(value or "").replace("\n", " ").replace("\r", " ").strip().lower()
        cleaned = re.sub(r"[^0-9a-zA-Z가-힣]+", " ", lowered)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _contains_phrase(value: str, phrase: str) -> bool:
        normalized_value = f" {_normalize_for_phrase(value)} "
        normalized_phrase = f" {_normalize_for_phrase(phrase)} "
        if normalized_phrase.strip() == "":
            return False
        return normalized_phrase in normalized_value

    def _match_source(text_value: str, *, min_phrase_len: int = 4) -> tuple[bool, str]:
        if strict_phrase_mode:
            return False, ""
        normalized_value = re.sub(r"\s+", " ", str(text_value or "")).strip().lower()
        if not normalized_value:
            return False, ""
        if target_regex.search(text_value):
            return True, text_value.strip()
        if target_phrase and len(target_phrase) >= min_phrase_len and target_phrase in normalized_value:
            return True, text_value.strip()
        token_hits = [token for token in target_tokens if token in normalized_value]
        if token_hits:
            return True, text_value.strip()
        return False, ""

    last_signature = ""
    failure_reason = "no_candidate_in_dump"
    for scroll_step in range(0, max_scroll_search_steps + 1):
        xml_nodes, xml_reason = _load_scrolltouch_xml_nodes(client=client, dev=dev)
        if not xml_nodes:
            log(f"[XMLENTRY][search] step={scroll_step}/{max_scroll_search_steps} candidate_count=0 reason='{xml_reason}'")
            failure_reason = "no_candidate_in_dump"
        candidate_samples: list[dict[str, Any]] = []
        chrome_rejects = 0
        root_rejects = 0
        parent_map: dict[int, dict[str, Any] | None] = {}
        for map_node, map_parent in _iter_tree_nodes_with_parent(xml_nodes):
            parent_map[id(map_node)] = map_parent if isinstance(map_parent, dict) else None
        for node, parent in _iter_tree_nodes_with_parent(xml_nodes):
            if not _node_is_visible(node):
                continue
            bounds = parse_bounds_str(str(node.get("boundsInScreen", "") or "").strip())
            if not bounds:
                continue
            label_blob = _node_label_blob(node)
            resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
            node_text = str(node.get("text", "") or "").strip()
            node_desc = str(node.get("contentDescription", "") or "").strip()
            descendant_blob = _collect_descendant_blob(node)
            title_match = False
            desc_match = False
            descendant_match = False
            target_match = False
            match_source = ""
            matched_phrase = ""
            negative_plugin_phrase = ""
            if strict_phrase_mode:
                for phrase in strict_phrases + title_only_phrases:
                    if _contains_phrase(node_text, phrase):
                        title_match = True
                        target_match = True
                        match_source = "title"
                        matched_phrase = phrase
                        break
                if not target_match:
                    for phrase in strict_phrases:
                        if _contains_phrase(node_desc, phrase):
                            desc_match = True
                            target_match = True
                            match_source = "content-desc"
                            matched_phrase = phrase
                            break
                if not target_match:
                    for phrase in strict_phrases:
                        if _contains_phrase(descendant_blob, phrase):
                            descendant_match = True
                            target_match = True
                            match_source = "descendant"
                            matched_phrase = phrase
                            break
                for phrase in negative_phrases:
                    if _contains_phrase(node_text, phrase) or _contains_phrase(node_desc, phrase) or _contains_phrase(descendant_blob, phrase):
                        negative_plugin_phrase = phrase
                        target_match = False
                        match_source = ""
                        matched_phrase = ""
                        break
            else:
                title_match, title_match_text = _match_source(node_text)
                desc_match, desc_match_text = _match_source(node_desc)
                descendant_match, descendant_match_text = _match_source(descendant_blob)
                resource_match, resource_match_text = _match_source(resource_id, min_phrase_len=3)
                target_match = bool(title_match or desc_match or descendant_match or resource_match)
                if title_match:
                    match_source, matched_phrase = "title", title_match_text
                elif desc_match:
                    match_source, matched_phrase = "content-desc", desc_match_text
                elif descendant_match:
                    match_source, matched_phrase = "descendant", descendant_match_text
                elif resource_match:
                    match_source, matched_phrase = "resource", resource_match_text
            promoted = node
            promoted_reason = "text_node_bounds"
            current = node
            parent_hops = 0
            while isinstance(parent, dict) and parent_hops < 6:
                parent_bounds = parse_bounds_str(str(parent.get("boundsInScreen", "") or "").strip())
                parent_resource = str(parent.get("viewIdResourceName", "") or parent.get("resourceId", "") or "").strip()
                parent_class = str(parent.get("className", "") or "").strip()
                is_actionable = bool(parent.get("clickable")) or bool(parent.get("focusable")) or bool(parent.get("effectiveClickable"))
                parent_card_like = bool(container_regex.search(parent_resource) or container_regex.search(parent_class))
                if parent_bounds and (is_actionable or parent_card_like):
                    promoted = parent
                    promoted_reason = "actionable_container" if is_actionable else "card_like_container"
                    break
                current = parent
                parent = parent_map.get(id(current))
                parent_hops += 1
            promoted_bounds = parse_bounds_str(str(promoted.get("boundsInScreen", "") or "").strip())
            if not promoted_bounds:
                failure_reason = "bounds_missing"
                continue
            width = max(1, promoted_bounds[2] - promoted_bounds[0])
            height = max(1, promoted_bounds[3] - promoted_bounds[1])
            promoted_area = width * height
            area_ratio = promoted_area / 2073600.0
            promoted_blob = f"{_node_label_blob(promoted)} {str(promoted.get('viewIdResourceName', '') or promoted.get('resourceId', '') or '')} {str(promoted.get('className', '') or '')}"
            if excluded_regex.search(promoted_blob):
                chrome_rejects += 1
                continue
            if area_ratio > 0.78:
                root_rejects += 1
                continue
            if area_ratio < 0.0015:
                continue
            score = (200 if target_match else 0) + (40 if "container" in promoted_reason else 0)
            candidate_samples.append(
                {
                    "score": score,
                    "node": promoted,
                    "reason": promoted_reason,
                    "sample_text": label_blob,
                    "area_ratio": f"{area_ratio:.4f}",
                    "target_match": target_match,
                    "match_source": match_source,
                    "matched_phrase": matched_phrase,
                    "negative_plugin_phrase": negative_plugin_phrase,
                }
            )
        candidate_samples.sort(key=lambda item: int(item.get("score", 0)), reverse=True)
        target_candidates = [sample for sample in candidate_samples if bool(sample.get("target_match"))]
        log(
            f"[XMLENTRY][search] step={scroll_step}/{max_scroll_search_steps} "
            f"visible_candidates={len(candidate_samples)} target_candidates={len(target_candidates)}"
        )
        for rank, sample in enumerate(candidate_samples[:3], start=1):
            sample_node = sample.get("node", {})
            sample_bounds = str(sample_node.get("boundsInScreen", "") or "").strip()
            sample_rid = str(sample_node.get("viewIdResourceName", "") or sample_node.get("resourceId", "") or "").strip()
            sample_cls = str(sample_node.get("className", "") or "").strip()
            sample_text = str(sample.get("sample_text", "") or "")
            sample_area_ratio = str(sample.get("area_ratio", "0") or "0")
            log(
                f"[XMLENTRY][search][top] rank={rank} reason='{sample.get('reason', '')}' text='{sample_text[:48]}' "
                f"rid='{sample_rid[:72]}' class='{sample_cls[:48]}' bounds='{sample_bounds}'"
                f" area_ratio='{sample_area_ratio or '0'}' target_match={str(bool(sample.get('target_match'))).lower()}"
                f" match_source='{str(sample.get('match_source', '') or '')}'"
                f" matched_phrase='{str(sample.get('matched_phrase', '') or '')[:80]}'"
                f" negative_plugin_phrase='{str(sample.get('negative_plugin_phrase', '') or '')[:80]}'"
            )
        if target_candidates:
            selected = target_candidates[0]
            selected_node = selected.get("node", {})
            selected_bounds = parse_bounds_str(str(selected_node.get("boundsInScreen", "") or "").strip())
            if not selected_bounds:
                failure_reason = "bounds_missing"
                break
            center_x = int((selected_bounds[0] + selected_bounds[2]) / 2)
            center_y = int((selected_bounds[1] + selected_bounds[3]) / 2)
            selected_resource = str(selected_node.get("viewIdResourceName", "") or selected_node.get("resourceId", "") or "").strip()
            selected_text = _node_label_blob(selected_node)
            log(
                f"[XMLENTRY][select] reason='{selected.get('reason', '')}' resource='{selected_resource[:96]}' "
                f"bounds='{selected_node.get('boundsInScreen', '')}' text='{selected_text[:80]}' "
                f"target_match=true match_source='{selected.get('match_source', '')}' "
                f"matched_phrase='{str(selected.get('matched_phrase', '') or '')[:80]}'"
            )
            tap_ok = False
            if hasattr(client, "tap_xy_adb"):
                tap_ok = bool(client.tap_xy_adb(dev=dev, x=center_x, y=center_y))
            else:
                run_fn = getattr(client, "_run", None)
                if callable(run_fn):
                    try:
                        run_fn(["shell", "input", "tap", str(center_x), str(center_y)], dev=dev)
                        tap_ok = True
                    except Exception:
                        tap_ok = False
            if not tap_ok:
                failure_reason = "bounds_missing"
                break
            confirm_ok, confirm_signal = _confirm_click_focused_transition(
                client=client,
                dev=dev,
                tab_cfg=tab_cfg,
                transition_fast_path=transition_fast_path,
            )
            setattr(client, "last_post_click_transition_same_screen", not confirm_ok)
            setattr(client, "last_post_click_transition_signal", str(confirm_signal or ""))
            if confirm_ok:
                log("[XMLENTRY][result] success=true reason='transition_confirmed'")
                return True, "xml_entry_success"
            failure_reason = "tap_dispatched_but_no_transition"
            log(
                f"[XMLENTRY][result] success=false reason='{failure_reason}' signal='{confirm_signal}' scenario='{scenario_id}' type='{type_}'"
            )
            break
        if chrome_rejects > 0 and not candidate_samples:
            failure_reason = "only_chrome_candidates"
        elif root_rejects > 0 and not candidate_samples:
            failure_reason = "only_root_candidates"
        elif candidate_samples and not target_candidates:
            failure_reason = "no_target_candidate_yet"
        if scroll_step >= max_scroll_search_steps:
            if failure_reason in {"no_candidate_in_dump", "no_target_candidate_yet", "max_scroll_reached"}:
                failure_reason = "target_not_found_after_scroll"
            break
        scrolled = bool(client.scroll(dev=dev, direction="down")) if hasattr(client, "scroll") else False
        scroll_reason = "no_strict_target_candidate" if strict_phrase_mode and not target_candidates else (
            "no_target_candidate" if not target_candidates else "search_continue"
        )
        log(
            f"[XMLENTRY][scroll] step={scroll_step}/{max_scroll_search_steps} "
            f"performed={str(scrolled).lower()} reason='{scroll_reason}'"
        )
        if not scrolled:
            break
        time.sleep(max(min(step_wait_seconds, 0.45), 0.2))
        current_signature = _make_visible_plugin_search_signature(xml_nodes)
        if current_signature and last_signature and current_signature == last_signature:
            failure_reason = "max_scroll_reached"
            break
        last_signature = current_signature
    log(f"[XMLENTRY][result] success=false reason='{failure_reason}'")
    return False, failure_reason


def _select_visible_plugin_candidate(
    *,
    nodes: list[dict[str, Any]],
    target: str,
    scenario_id: str = "",
    xml_nodes: list[dict[str, Any]] | None = None,
    entry_spec: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str, dict[str, Any], dict[str, Any]]:
    sample_limit = 10
    sample_text_limit = 72
    sample_id_limit = 48
    sample_class_limit = 36

    def _clip(value: Any, limit: int) -> str:
        return str(value or "").strip()[:limit]

    def _append_rejection(stats_map: dict[str, Any], reason: str) -> None:
        rejection_counts = stats_map.setdefault("rejection_counts", {})
        rejection_counts[reason] = int(rejection_counts.get(reason, 0) or 0) + 1

    def _is_actionable(node_ref: dict[str, Any]) -> bool:
        clickable = bool(node_ref.get("clickable"))
        focusable = bool(node_ref.get("focusable"))
        effective_clickable = bool(node_ref.get("effectiveClickable"))
        return clickable or focusable or effective_clickable

    def _normalize_phrase(value: str) -> str:
        lowered = str(value or "").replace("\n", " ").replace("\r", " ").strip().lower()
        cleaned = re.sub(r"[^\w가-힣]+", " ", lowered)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _tokenize_blob(value: str) -> set[str]:
        return {token for token in re.split(r"[^0-9a-zA-Z가-힣]+", str(value or "").lower()) if len(token) >= 3}

    def _tokenize_resource_id(value: str) -> set[str]:
        raw = str(value or "").strip()
        if not raw:
            return set()
        base = raw.split("/")[-1]
        split_camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", base)
        return _tokenize_blob(split_camel.replace("_", " "))

    def _record_inspect(
        stats_map: dict[str, Any],
        *,
        node_ref: dict[str, Any],
        promoted_click_node: dict[str, Any] | None,
        reject_reason: str,
        stage: str = "filtered",
        matched_text_node: str = "",
        promotion_reason: str = "none",
        promoted_from: str = "",
        promoted_to: str = "",
        filter_stage: str = "filtered_hard",
        hard_reject_reason: str = "none",
        probe_allowed: bool = False,
        probe_text_source: str = "none",
        probe_match_reason: str = "none",
        probe_guard_reason: str = "none",
        probe_promoted: bool = False,
        alias_hit_count: int = 0,
        alias_hit_top: str = "",
        resource_token_hit_count: int = 0,
        descendant_alias_hit_count: int = 0,
        semantic_evidence_class: str = "miss",
        probe_accept_reason: str = "none",
        probe_reject_reason: str = "none",
    ) -> None:
        samples = stats_map.setdefault("inspect_samples", [])
        if len(samples) >= sample_limit:
            return
        resource_id = _clip(node_ref.get("viewIdResourceName", "") or node_ref.get("resourceId", ""), sample_id_limit)
        class_name = _clip(node_ref.get("className", ""), sample_class_limit)
        label_blob = _clip(_node_label_blob(node_ref), sample_text_limit)
        visible = _node_is_visible(node_ref)
        clickable = bool(node_ref.get("clickable"))
        focusable = bool(node_ref.get("focusable"))
        effective_clickable = clickable or focusable
        promoted = isinstance(promoted_click_node, dict)
        samples.append(
            "label='{}' rid='{}' cls='{}' visible={} clickable={} focusable={} effectiveClickable={} matched_text_node='{}' promoted_container={} promotion_reason='{}' promoted_from='{}' promoted_to='{}' stage='{}' reason='{}' filter_stage='{}' hard_reject_reason='{}' probe_allowed={} probe_text_source='{}' probe_match_reason='{}' probe_guard_reason='{}' probe_promoted={} alias_hit_count={} alias_hit_top='{}' resource_token_hit_count={} descendant_alias_hit_count={} semantic_evidence_class='{}' probe_accept_reason='{}' probe_reject_reason='{}'".format(
                label_blob,
                resource_id,
                class_name,
                str(bool(visible)).lower(),
                str(clickable).lower(),
                str(focusable).lower(),
                str(effective_clickable).lower(),
                _clip(matched_text_node, sample_text_limit),
                str(promoted).lower(),
                _clip(promotion_reason, sample_text_limit),
                _clip(promoted_from, sample_id_limit),
                _clip(promoted_to, sample_id_limit),
                stage,
                reject_reason,
                filter_stage,
                hard_reject_reason,
                str(bool(probe_allowed)).lower(),
                _clip(probe_text_source, sample_text_limit),
                _clip(probe_match_reason, sample_text_limit),
                _clip(probe_guard_reason, sample_text_limit),
                str(bool(probe_promoted)).lower(),
                int(alias_hit_count),
                _clip(alias_hit_top, sample_text_limit),
                int(resource_token_hit_count),
                int(descendant_alias_hit_count),
                _clip(semantic_evidence_class, sample_text_limit),
                _clip(probe_accept_reason, sample_text_limit),
                _clip(probe_reject_reason, sample_text_limit),
            )
        )

    def _record_pre_candidate(
        stats_map: dict[str, Any],
        *,
        node_ref: dict[str, Any],
        promoted_click_node: dict[str, Any] | None,
        reason: str,
    ) -> None:
        samples = stats_map.setdefault("pre_candidate_fail_samples", [])
        if len(samples) >= sample_limit:
            return
        source_node = promoted_click_node if isinstance(promoted_click_node, dict) else node_ref
        label_blob = _clip(_node_label_blob(source_node), sample_text_limit)
        rid = _clip(source_node.get("viewIdResourceName", "") or source_node.get("resourceId", ""), sample_id_limit)
        cls = _clip(source_node.get("className", ""), sample_class_limit)
        samples.append(f"label='{label_blob}' rid='{rid}' cls='{cls}' reason='{reason}'")

    stats: dict[str, Any] = {
        "visible_candidate_count": 0,
        "partial_match_count": 0,
        "exact_match_count": 0,
        "relaxed_semantic_match_count": 0,
        "generic_guard_block_count": 0,
        "fallback_applied_count": 0,
        "hard_filter_reject_count": 0,
        "semantic_probe_pool_count": 0,
        "semantic_probe_match_count": 0,
        "semantic_probe_reject_count": 0,
        "candidate_from_probe_count": 0,
        "probe_guard_block_count": 0,
        "alias_hit_count": 0,
        "alias_hit_top": "",
        "resource_token_hit_count": 0,
        "resource_token_hit_top": "",
        "descendant_alias_hit_count": 0,
        "semantic_evidence_class": "miss",
        "probe_accept_reason": "none",
        "probe_reject_reason": "none",
        "helper_text_hit_count": 0,
        "xml_live_text_hit_count": 0,
        "descendant_text_hit_count": 0,
        "relaxed_semantic_samples": [],
        "probe_samples": [],
        "probe_reject_samples": [],
        "rejected_large_container_count": 0,
        "rejected_list_like_container_count": 0,
        "visible_samples": [],
        "partial_samples": [],
        "inspect_samples": [],
        "pre_candidate_fail_samples": [],
        "rejection_counts": {},
        "promotion_attempted": False,
        "matched_text_found": False,
        "xml_node_found": False,
        "xml_match_strategy": "none",
        "ancestor_chain_depth": 0,
        "actionable_ancestor_found": False,
        "candidate_committed": False,
        "last_promotion_result_reason": "none",
        "will_try_xml_live_fallback": False,
    }
    selected_meta: dict[str, Any] = {
        "promoted_container": False,
        "promotion_attempted": False,
        "promotion_source": "none",
        "promotion_reason": "none",
        "promoted_from": "",
        "promoted_to": "",
        "promotion_candidate_count": 0,
        "promotion_debug_summary": "",
        "selected_area": 0,
        "matched_text_area": 0,
        "selected_to_text_area_ratio": 0.0,
        "ancestor_distance": -1,
        "selected_ancestor_distance": -1,
        "selected_container_class": "",
        "selected_container_view_id": "",
        "tap_point": "",
        "tap_strategy": "center",
        "rank_summary_top3": "",
    }
    if not isinstance(nodes, list) or not nodes:
        return None, "empty_dump", stats, selected_meta
    flat_nodes = _iter_tree_nodes_with_parent(nodes)
    parsed_bounds = [parse_bounds_str(str(node.get("boundsInScreen", "") or "").strip()) for node, _ in flat_nodes]
    parsed_bounds = [b for b in parsed_bounds if b and b[0] < b[2] and b[1] < b[3]]
    if not parsed_bounds:
        return None, "viewport_unavailable", stats, selected_meta
    viewport_left = min(b[0] for b in parsed_bounds)
    viewport_top = min(b[1] for b in parsed_bounds)
    viewport_right = max(b[2] for b in parsed_bounds)
    viewport_bottom = max(b[3] for b in parsed_bounds)
    viewport_center = (viewport_top + viewport_bottom) // 2
    viewport_area = max(1, (viewport_right - viewport_left) * (viewport_bottom - viewport_top))

    card_entry_spec = dict(entry_spec or {})
    title_patterns = [str(pattern or "").strip() for pattern in card_entry_spec.get("title_patterns", []) if str(pattern or "").strip()]
    description_patterns = [str(pattern or "").strip() for pattern in card_entry_spec.get("description_patterns", []) if str(pattern or "").strip()]
    resource_patterns = [str(pattern or "").strip() for pattern in card_entry_spec.get("resource_patterns", []) if str(pattern or "").strip()]
    allow_description_match = bool(card_entry_spec.get("allow_description_match"))
    if not title_patterns:
        title_patterns = [str(target or "").strip()]
    target_tokens: list[str] = []
    for pattern in [*title_patterns, *description_patterns]:
        pattern_tokens = [token for token in re.split(r"[^0-9a-zA-Z가-힣]+", pattern.lower()) if len(token) >= 3]
        target_tokens.extend(pattern_tokens)
    target_tokens = sorted(set(target_tokens))
    normalized_target_phrases: set[str] = set()
    normalized_pattern_inputs = [*title_patterns, *description_patterns, str(target or "").strip()]
    for pattern in normalized_pattern_inputs:
        if not pattern:
            continue
        phrase_seed = str(pattern)
        phrase_seed = re.sub(r"\(\?i\)", " ", phrase_seed)
        phrase_seed = re.sub(r"\[sS]\*", " ", phrase_seed)
        phrase_seed = re.sub(r"\[sS]\+", " ", phrase_seed)
        phrase_seed = re.sub(r"[\^\$\|\(\)\[\]\{\}\?\*\+\\]", " ", phrase_seed)
        normalized_phrase = _normalize_phrase(phrase_seed)
        if len(normalized_phrase) >= 4:
            normalized_target_phrases.add(normalized_phrase)
    if target_tokens:
        normalized_target_phrases.add(_normalize_phrase(" ".join(target_tokens)))
    target_token_set = set(target_tokens)
    semantic_aliases = [str(item or "").strip().lower() for item in card_entry_spec.get("semantic_probe_aliases", []) if str(item or "").strip()]
    semantic_hint_tokens = {
        str(item or "").strip().lower() for item in card_entry_spec.get("semantic_probe_hint_tokens", []) if str(item or "").strip()
    }
    generic_weak_tokens = {
        str(item or "").strip().lower() for item in card_entry_spec.get("semantic_probe_generic_weak_tokens", []) if str(item or "").strip()
    }
    alias_phrase_map: list[tuple[str, set[str]]] = []
    alias_token_set: set[str] = set()
    for alias in semantic_aliases:
        alias_norm = _normalize_phrase(alias)
        if not alias_norm:
            continue
        alias_tokens = _tokenize_blob(alias_norm)
        alias_phrase_map.append((alias_norm, alias_tokens))
        alias_token_set.update(alias_tokens)
    combined_target_tokens = set(target_token_set)
    combined_target_tokens.update(alias_token_set)

    def _is_chrome_like_blob(blob: str) -> bool:
        return bool(_safe_regex_search(r"(?i)\b(add|more options|location|navigate up|home|back|button)\b", blob))

    def _is_large_or_list_like_node(node_ref: dict[str, Any], node_bounds: tuple[int, int, int, int]) -> bool:
        node_class_name = str(node_ref.get("className", "") or "")
        node_resource = str(node_ref.get("viewIdResourceName", "") or node_ref.get("resourceId", "") or "")
        node_area_local = max(1, (node_bounds[2] - node_bounds[0]) * (node_bounds[3] - node_bounds[1]))
        is_large_root = bool(node_area_local >= int(viewport_area * 0.92) and not _is_actionable(node_ref))
        is_list_like = bool(_safe_regex_search(r"(?i)(recycler.?view|grid.?view|list.?view)", f"{node_class_name} {node_resource}"))
        return is_large_root or is_list_like

    descendants_by_container: dict[int, list[str]] = {}
    for node, parent in flat_nodes:
        if not isinstance(parent, dict):
            continue
        parent_key = id(parent)
        descendants = descendants_by_container.setdefault(parent_key, [])
        child_label = _node_label_blob(node)
        if child_label:
            descendants.append(child_label)
    helper_text_hit_count = 0
    descendant_text_hit_count = 0
    for node, _ in flat_nodes:
        helper_blob = _node_label_blob(node)
        descendant_blob = " ".join(descendants_by_container.get(id(node), []))
        helper_norm = _normalize_phrase(helper_blob)
        descendant_norm = _normalize_phrase(descendant_blob)
        helper_hit = bool(
            helper_norm
            and (
                any(phrase in helper_norm or helper_norm in phrase for phrase in normalized_target_phrases if phrase)
                or bool(target_token_set and _tokenize_blob(helper_blob).intersection(target_token_set))
            )
        )
        descendant_hit = bool(
            descendant_norm
            and (
                any(phrase in descendant_norm or descendant_norm in phrase for phrase in normalized_target_phrases if phrase)
                or bool(target_token_set and _tokenize_blob(descendant_blob).intersection(target_token_set))
            )
        )
        if helper_hit:
            helper_text_hit_count += 1
        if descendant_hit:
            descendant_text_hit_count += 1
    stats["helper_text_hit_count"] = helper_text_hit_count
    stats["descendant_text_hit_count"] = descendant_text_hit_count

    actionable_nodes: list[tuple[dict[str, Any], tuple[int, int, int, int], bool]] = []
    for candidate_node, _ in flat_nodes:
        candidate_bounds = parse_bounds_str(str(candidate_node.get("boundsInScreen", "") or "").strip())
        if not candidate_bounds or not (candidate_bounds[0] < candidate_bounds[2] and candidate_bounds[1] < candidate_bounds[3]):
            continue
        if not _node_is_visible(candidate_node):
            continue
        candidate_clickable = _is_actionable(candidate_node)
        candidate_resource = str(candidate_node.get("viewIdResourceName", "") or candidate_node.get("resourceId", "") or "").strip()
        candidate_class_name = str(candidate_node.get("className", "") or "").strip()
        is_card_like = bool(
            _safe_regex_search(r"(?i)(preinstalledservicecard|servicecard|content_view|frameLayout|card|container|root)", candidate_resource)
            or _safe_regex_search(r"(?i)(card|frame.?layout)", candidate_class_name)
        )
        if candidate_clickable or is_card_like:
            actionable_nodes.append((candidate_node, candidate_bounds, is_card_like))

    parent_by_node_id: dict[int, dict[str, Any]] = {}
    for child, parent in flat_nodes:
        if isinstance(parent, dict):
            parent_by_node_id[id(child)] = parent

    xml_flat_nodes: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    xml_parent_by_node_id: dict[int, dict[str, Any]] = {}
    xml_actionable_nodes: list[tuple[dict[str, Any], tuple[int, int, int, int], bool]] = []
    if isinstance(xml_nodes, list) and xml_nodes:
        xml_text_hit_count = 0
        for xml_candidate_node, xml_parent in _iter_tree_nodes_with_parent(xml_nodes):
            xml_flat_nodes.append((xml_candidate_node, xml_parent if isinstance(xml_parent, dict) else None))
            if isinstance(xml_parent, dict):
                xml_parent_by_node_id[id(xml_candidate_node)] = xml_parent
            xml_bounds = parse_bounds_str(str(xml_candidate_node.get("boundsInScreen", "") or "").strip())
            if not xml_bounds or not (xml_bounds[0] < xml_bounds[2] and xml_bounds[1] < xml_bounds[3]):
                continue
            if not _node_is_visible(xml_candidate_node):
                continue
            xml_clickable = _is_actionable(xml_candidate_node)
            xml_resource = str(
                xml_candidate_node.get("viewIdResourceName", "") or xml_candidate_node.get("resourceId", "") or ""
            ).strip()
            xml_class_name = str(xml_candidate_node.get("className", "") or "").strip()
            xml_is_card_like = bool(
                _safe_regex_search(r"(?i)(preinstalledservicecard|servicecard|content_view|frameLayout|card|container|root|item|layout)", xml_resource)
                or _safe_regex_search(r"(?i)(card|frame.?layout|linear.?layout|relative.?layout)", xml_class_name)
            )
            if xml_clickable or xml_is_card_like:
                xml_actionable_nodes.append((xml_candidate_node, xml_bounds, xml_is_card_like))
            xml_blob = _node_label_blob(xml_candidate_node)
            xml_norm = _normalize_phrase(xml_blob)
            if xml_norm and (
                any(phrase in xml_norm or xml_norm in phrase for phrase in normalized_target_phrases if phrase)
                or bool(target_token_set and _tokenize_blob(xml_blob).intersection(target_token_set))
            ):
                xml_text_hit_count += 1
        stats["xml_live_text_hit_count"] = xml_text_hit_count

    def _select_promoted_container(
        *,
        matched_node: dict[str, Any],
        node_bounds: tuple[int, int, int, int],
        viewport_bounds: tuple[int, int],
        source_nodes: list[tuple[dict[str, Any], tuple[int, int, int, int], bool]],
        source_name: str,
        parent_map: dict[int, dict[str, Any]],
        source_flat_nodes: list[tuple[dict[str, Any], dict[str, Any] | None]] | None = None,
    ) -> tuple[dict[str, Any] | None, str, int, str, int, str]:
        left, top, right, bottom = node_bounds
        viewport_t, viewport_b = viewport_bounds
        node_area = max(1, (right - left) * (bottom - top))
        node_center_x = (left + right) // 2
        node_center_y = (top + bottom) // 2
        viewport_area = max(1, (viewport_right - viewport_left) * max(1, viewport_b - viewport_t))
        nearest_actionable_ancestor: dict[str, Any] | None = None
        ancestor_distance = -1
        ancestor_distance_by_node_id: dict[int, int] = {}
        trace_lines: list[str] = []
        matched_view_id = str(
            matched_node.get("viewIdResourceName", "") or matched_node.get("resourceId", "") or matched_node.get("className", "") or "node"
        ).strip()
        matched_label = _node_label_blob(matched_node)
        matched_bounds_repr = f"{left},{top},{right},{bottom}"
        stats["promotion_attempted"] = True
        stats["matched_text_found"] = True
        log(
            "[SCROLLTOUCH][promotion][enter] source_snapshot='{}' matched_text_node='{}' matched_text_view_id='{}' matched_text_label='{}' "
            "matched_text_bounds='{}' node_clickable={} node_focusable={} node_effective_clickable={} promotion_attempted=true".format(
                source_name,
                matched_view_id[:64],
                matched_view_id[:64],
                matched_label[:120],
                matched_bounds_repr,
                str(bool(matched_node.get("clickable"))).lower(),
                str(bool(matched_node.get("focusable"))).lower(),
                str(_is_actionable(matched_node)).lower(),
            )
        )

        matched_reference_node = matched_node
        xml_node_found = False
        xml_match_strategy = "none"
        if source_name == "xml_live" and source_flat_nodes:
            normalized_matched_label = re.sub(r"\s+", " ", matched_label).strip().lower()
            best_xml_node: dict[str, Any] | None = None
            best_xml_score = -1
            best_strategy = "none"
            best_has_view_id = False
            for xml_node, _ in source_flat_nodes:
                xml_bounds = parse_bounds_str(str(xml_node.get("boundsInScreen", "") or "").strip())
                if not xml_bounds or xml_bounds != node_bounds:
                    continue
                xml_label = _node_label_blob(xml_node)
                normalized_xml_label = re.sub(r"\s+", " ", xml_label).strip().lower()
                score = 1
                node_view_id = str(xml_node.get("viewIdResourceName", "") or xml_node.get("resourceId", "") or "").strip()
                matched_node_view_id = str(matched_node.get("viewIdResourceName", "") or matched_node.get("resourceId", "") or "").strip()
                has_view_id_match = bool(node_view_id and matched_node_view_id and node_view_id == matched_node_view_id)
                if normalized_matched_label and normalized_xml_label and normalized_matched_label == normalized_xml_label:
                    score += 2
                if has_view_id_match:
                    score += 3
                strategy = "bounds"
                if has_view_id_match and normalized_matched_label and normalized_xml_label and normalized_matched_label == normalized_xml_label:
                    strategy = "mixed"
                elif has_view_id_match:
                    strategy = "view_id"
                elif normalized_matched_label and normalized_xml_label and normalized_matched_label == normalized_xml_label:
                    strategy = "text"
                if score > best_xml_score:
                    best_xml_score = score
                    best_xml_node = xml_node
                    best_strategy = strategy
                    best_has_view_id = has_view_id_match
            if isinstance(best_xml_node, dict):
                matched_reference_node = best_xml_node
                xml_node_found = True
                xml_match_strategy = best_strategy if best_strategy != "none" else ("view_id" if best_has_view_id else "bounds")
                stats["xml_node_found"] = True
                stats["xml_match_strategy"] = xml_match_strategy
        if source_name == "xml_live":
            xml_class = str(matched_reference_node.get("className", "") or "").strip()
            xml_view_id = str(matched_reference_node.get("viewIdResourceName", "") or matched_reference_node.get("resourceId", "") or "").strip()
            xml_bounds_repr = str(matched_reference_node.get("boundsInScreen", "") or "").strip()
            log(
                "[SCROLLTOUCH][promotion][xml_resolve] matched_text_view_id='{}' matched_text_label='{}' matched_text_bounds='{}' "
                "xml_node_found={} xml_match_strategy='{}' xml_node_class='{}' xml_node_view_id='{}' xml_node_bounds='{}'".format(
                    matched_view_id[:64],
                    matched_label[:120],
                    matched_bounds_repr,
                    str(xml_node_found).lower(),
                    xml_match_strategy,
                    xml_class[:64],
                    xml_view_id[:64],
                    xml_bounds_repr[:64],
                )
            )

        def _is_excluded_ancestor(node: dict[str, Any], distance: int) -> bool:
            class_name = str(node.get("className", "") or "").strip()
            resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
            if _safe_regex_search(r"(?i)(recycler.?view|grid.?view|list.?view)", class_name) or _safe_regex_search(
                r"(?i)(recycler.?view|grid.?view|list.?view)", resource_id
            ):
                return True
            node_bounds = parse_bounds_str(str(node.get("boundsInScreen", "") or "").strip())
            if node_bounds:
                n_left, n_top, n_right, n_bottom = node_bounds
                node_area = max(1, (n_right - n_left) * (n_bottom - n_top))
                if node_area > int(viewport_area * 0.94):
                    return True
            if distance >= 7 and not resource_id and not _node_label_blob(node):
                return True
            return False

        def _ancestor_exclude_reason(node: dict[str, Any], distance: int) -> str:
            class_name = str(node.get("className", "") or "").strip()
            resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
            if _safe_regex_search(r"(?i)(recycler.?view|grid.?view|list.?view)", class_name) or _safe_regex_search(
                r"(?i)(recycler.?view|grid.?view|list.?view)", resource_id
            ):
                return "recycler_excluded"
            node_bounds = parse_bounds_str(str(node.get("boundsInScreen", "") or "").strip())
            if node_bounds:
                n_left, n_top, n_right, n_bottom = node_bounds
                node_area = max(1, (n_right - n_left) * (n_bottom - n_top))
                if node_area > int(viewport_area * 0.94):
                    return "oversized_root"
            if distance >= 7 and not resource_id and not _node_label_blob(node):
                return "root_excluded"
            return "none"

        cursor = parent_map.get(id(matched_reference_node))
        distance = 1
        while isinstance(cursor, dict) and distance <= 8:
            ancestor_distance_by_node_id[id(cursor)] = distance
            is_excluded = _is_excluded_ancestor(cursor, distance)
            exclude_reason = _ancestor_exclude_reason(cursor, distance) if is_excluded else "none"
            cursor_class = str(cursor.get("className", "") or "").strip()
            cursor_view_id = str(cursor.get("viewIdResourceName", "") or cursor.get("resourceId", "") or "").strip()
            cursor_bounds = str(cursor.get("boundsInScreen", "") or "").strip()
            trace_lines.append(
                "depth={} class={} view_id={} bounds={} clickable={} focusable={} effective_clickable={} excluded={} exclude_reason={}".format(
                    distance,
                    cursor_class or "-",
                    cursor_view_id or "-",
                    cursor_bounds or "-",
                    str(bool(cursor.get("clickable"))).lower(),
                    str(bool(cursor.get("focusable"))).lower(),
                    str(_is_actionable(cursor)).lower(),
                    str(bool(is_excluded)).lower(),
                    exclude_reason,
                )
            )
            log(
                "[SCROLLTOUCH][promotion][ancestor_trace] matched_text_view_id='{}' matched_text_bounds='{}' depth={} class='{}' view_id='{}' "
                "bounds='{}' clickable={} focusable={} effective_clickable={} excluded={} exclude_reason='{}'".format(
                    matched_view_id[:64],
                    matched_bounds_repr,
                    int(distance),
                    cursor_class[:64],
                    cursor_view_id[:64],
                    cursor_bounds[:64],
                    str(bool(cursor.get("clickable"))).lower(),
                    str(bool(cursor.get("focusable"))).lower(),
                    str(_is_actionable(cursor)).lower(),
                    str(bool(is_excluded)).lower(),
                    exclude_reason,
                )
            )
            if _is_actionable(cursor):
                nearest_actionable_ancestor = cursor
                ancestor_distance = distance
                break
            cursor = parent_map.get(id(cursor))
            distance += 1
        stats["ancestor_chain_depth"] = max(int(stats.get("ancestor_chain_depth", 0) or 0), len(trace_lines))
        if isinstance(nearest_actionable_ancestor, dict):
            stats["actionable_ancestor_found"] = True
        trace_summary = " | ".join(trace_lines) if trace_lines else "empty"

        def _log_promotion_exit(result_node: dict[str, Any] | None, result_reason: str) -> None:
            result = "selected" if isinstance(result_node, dict) else "none"
            stats["last_promotion_result_reason"] = result_reason
            result_class = ""
            result_view_id = ""
            result_bounds = ""
            if isinstance(result_node, dict):
                result_class = str(result_node.get("className", "") or "").strip()
                result_view_id = str(result_node.get("viewIdResourceName", "") or result_node.get("resourceId", "") or "").strip()
                result_bounds = str(result_node.get("boundsInScreen", "") or "").strip()
            log(
                "[SCROLLTOUCH][promotion][exit] source_snapshot='{}' matched_text_view_id='{}' matched_text_label='{}' matched_text_bounds='{}' "
                "promotion_attempted=true result='{}' result_reason='{}' selected_container_class='{}' selected_container_view_id='{}' selected_container_bounds='{}'".format(
                    source_name,
                    matched_view_id[:64],
                    matched_label[:120],
                    matched_bounds_repr,
                    result,
                    result_reason[:80],
                    result_class[:64],
                    result_view_id[:64],
                    result_bounds[:64],
                )
            )

        scored_candidates: list[tuple[tuple[int, int, int, int, int, int], dict[str, Any], str]] = []
        containment_candidates: list[tuple[tuple[int, int, int, int, int, int], dict[str, Any], str]] = []
        scored_summary: list[tuple[int, str]] = []
        for action_node, action_bounds, is_card_like in source_nodes:
            a_left, a_top, a_right, a_bottom = action_bounds
            action_resource = str(action_node.get("viewIdResourceName", "") or action_node.get("resourceId", "") or "").strip()
            action_class = str(action_node.get("className", "") or "").strip()
            action_depth = int(ancestor_distance_by_node_id.get(id(action_node), -1))
            if a_bottom <= viewport_t or a_top >= viewport_b:
                continue
            area = max(1, (a_right - a_left) * (a_bottom - a_top))
            if area > int(viewport_area * 0.92):
                log(
                    "[SCROLLTOUCH][promotion][ancestor_candidate] depth={} class='{}' view_id='{}' actionable={} accepted=false accepted_reason='none' rejected_reason='oversized_root'".format(
                        action_depth,
                        action_class[:64],
                        action_resource[:64],
                        str(_is_actionable(action_node)).lower(),
                    )
                )
                continue
            fully_contains = a_left <= left and a_top <= top and a_right >= right and a_bottom >= bottom
            overlap_w = max(0, min(right, a_right) - max(left, a_left))
            overlap_h = max(0, min(bottom, a_bottom) - max(top, a_top))
            overlap_area = overlap_w * overlap_h
            overlap_ratio = int((overlap_area / node_area) * 1000)
            if not fully_contains and overlap_ratio < 220:
                continue
            center_x = (a_left + a_right) // 2
            center_y = (a_top + a_bottom) // 2
            center_distance = abs(center_x - node_center_x) + abs(center_y - node_center_y)
            action_clickable = _is_actionable(action_node)
            if not action_clickable:
                log(
                    "[SCROLLTOUCH][promotion][ancestor_candidate] depth={} class='{}' view_id='{}' actionable=false accepted=false accepted_reason='none' rejected_reason='not_actionable'".format(
                        action_depth,
                        action_class[:64],
                        action_resource[:64],
                    )
                )
                continue
            action_label = _node_label_blob(action_node)
            lower_rid = action_resource.lower()
            lower_cls = action_class.lower()
            is_list_like_container = bool(
                _safe_regex_search(r"(?i)(recycler.?view|grid.?view|list.?view|viewpager|pager|scroll.?view)", action_resource)
                or _safe_regex_search(r"(?i)(recycler.?view|grid.?view|list.?view|viewpager|pager|scroll.?view)", action_class)
                or lower_rid.endswith("/recycler_view")
                or lower_rid.endswith(":id/recycler_view")
                or lower_cls.endswith("recyclerview")
            )
            if is_list_like_container:
                stats["rejected_list_like_container_count"] += 1
                log(
                    "[SCROLLTOUCH][promotion][ancestor_candidate] depth={} class='{}' view_id='{}' actionable=true accepted=false accepted_reason='none' rejected_reason='recycler_excluded'".format(
                        action_depth,
                        action_class[:64],
                        action_resource[:64],
                    )
                )
                continue
            has_container_hint = bool(
                _safe_regex_search(r"(?i)(card|container|layout|frame|root|item)", action_resource)
                or _safe_regex_search(r"(?i)(card|container|layout|frame|root|item)", action_class)
            )
            class_hint = bool(_safe_regex_search(r"(?i)(button|imagebutton|card|item|container)", action_class))
            width = max(1, a_right - a_left)
            height = max(1, a_bottom - a_top)
            text_area_ratio = area / float(node_area)
            width_ratio = width / max(1, viewport_right - viewport_left)
            height_ratio = height / max(1, viewport_bottom - viewport_top)
            candidate_ancestor_distance = int(ancestor_distance_by_node_id.get(id(action_node), 999))
            if candidate_ancestor_distance > 6:
                candidate_ancestor_distance = 999
            overly_large_generic = bool(
                text_area_ratio >= 8.0
                and width_ratio >= 0.86
                and height_ratio >= 0.30
                and not action_resource
                and not action_label
                and _safe_regex_search(r"(?i)relative.?layout", action_class)
            )
            is_large_container = bool(
                area > int(viewport_area * 0.70)
                or (width_ratio >= 0.95 and height_ratio >= 0.55)
                or text_area_ratio >= 10.0
                or overly_large_generic
            )
            if is_large_container:
                stats["rejected_large_container_count"] += 1
                log(
                    "[SCROLLTOUCH][promotion][ancestor_candidate] depth={} class='{}' view_id='{}' actionable=true accepted=false accepted_reason='none' rejected_reason='oversized_root'".format(
                        action_depth,
                        action_class[:64],
                        action_resource[:64],
                    )
                )
                continue
            if candidate_ancestor_distance == 999 and not (fully_contains and (has_container_hint or is_card_like)):
                log(
                    "[SCROLLTOUCH][promotion][ancestor_candidate] depth={} class='{}' view_id='{}' actionable=true accepted=false accepted_reason='none' rejected_reason='root_excluded'".format(
                        action_depth,
                        action_class[:64],
                        action_resource[:64],
                    )
                )
                continue
            reason = f"{source_name}_nearby_container"
            if fully_contains:
                reason = f"{source_name}_containment_container"
            if isinstance(nearest_actionable_ancestor, dict) and action_node is nearest_actionable_ancestor:
                reason = f"{source_name}_nearest_actionable_ancestor"
            specificity_score = 0
            if action_resource:
                specificity_score += 2
            if action_clickable:
                specificity_score += 2
            if class_hint or is_card_like:
                specificity_score += 1
            if action_label:
                specificity_score += 1
            if _safe_regex_search(r"(?i)relative.?layout", action_class) and not action_resource and not action_label:
                specificity_score -= 2
            area_penalty = 0
            if text_area_ratio >= 8.0:
                area_penalty -= 3
            elif text_area_ratio >= 5.0:
                area_penalty -= 2
            elif text_area_ratio >= 3.0:
                area_penalty -= 1
            ancestor_priority = 0
            if isinstance(nearest_actionable_ancestor, dict):
                if action_node is nearest_actionable_ancestor:
                    ancestor_priority = 4
                else:
                    ancestor_priority = -1
            card_size_delta = abs(text_area_ratio - 3.2)
            score = (
                1 if candidate_ancestor_distance < 999 else 0,
                -candidate_ancestor_distance,
                -int(card_size_delta * 100),
                1 if not is_large_container else 0,
                ancestor_priority + specificity_score + (1 if has_container_hint else 0),
                overlap_ratio + (area_penalty * 100) - center_distance,
            )
            scored_candidates.append((score, action_node, reason))
            log(
                "[SCROLLTOUCH][promotion][ancestor_candidate] depth={} class='{}' view_id='{}' actionable=true accepted=true accepted_reason='{}' rejected_reason='none'".format(
                    action_depth,
                    action_class[:64],
                    action_resource[:64],
                    reason[:64],
                )
            )
            if fully_contains:
                containment_candidates.append((score, action_node, reason))
            if len(scored_summary) < 12:
                summary_id = action_resource or action_class or "node"
                scored_summary.append(
                    (
                        sum(score),
                        f"{summary_id}:{reason}:ov={overlap_ratio}:ar={text_area_ratio:.2f}:sp={specificity_score}:ad={candidate_ancestor_distance}",
                    )
                )
        scored_summary.sort(key=lambda item: item[0], reverse=True)
        top3_summary = " | ".join(item[1] for item in scored_summary[:3])
        if containment_candidates:
            containment_candidates.sort(reverse=True, key=lambda item: item[0])
            best_node = containment_candidates[0][1]
            best_reason = containment_candidates[0][2]
            best_distance = int(ancestor_distance_by_node_id.get(id(best_node), ancestor_distance if ancestor_distance >= 0 else 999))
            _log_promotion_exit(best_node, best_reason)
            return (
                best_node,
                best_reason,
                len(containment_candidates),
                f"{source_name}:containment_candidate_count={len(containment_candidates)}:rejected_large={int(stats.get('rejected_large_container_count', 0) or 0)}:rejected_list_like={int(stats.get('rejected_list_like_container_count', 0) or 0)}",
                best_distance,
                top3_summary,
            )
        if isinstance(nearest_actionable_ancestor, dict) and source_name == "xml_live":
            if not _is_excluded_ancestor(nearest_actionable_ancestor, ancestor_distance):
                selected_class = str(nearest_actionable_ancestor.get("className", "") or "").strip()
                selected_view_id = str(
                    nearest_actionable_ancestor.get("viewIdResourceName", "") or nearest_actionable_ancestor.get("resourceId", "") or ""
                ).strip()
                log(
                    "[SCROLLTOUCH][promotion][ancestor_fallback] matched_text_view_id='{}' matched_text_bounds='{}' ancestor_depth={} "
                    "selected_class='{}' selected_view_id='{}' clickable={} focusable={} reason='closest_actionable_ancestor'".format(
                        matched_view_id[:64],
                        matched_bounds_repr,
                        int(ancestor_distance),
                        selected_class[:48],
                        selected_view_id[:64],
                        str(bool(nearest_actionable_ancestor.get("clickable"))).lower(),
                        str(bool(nearest_actionable_ancestor.get("focusable"))).lower(),
                    )
                )
                _log_promotion_exit(nearest_actionable_ancestor, "xml_live_closest_actionable_ancestor")
                return (
                    nearest_actionable_ancestor,
                    "xml_live_closest_actionable_ancestor",
                    1,
                    f"{source_name}:ancestor_fallback",
                    ancestor_distance,
                    trace_summary,
                )
        if not scored_candidates:
            if source_name == "xml_live":
                log(
                    "[SCROLLTOUCH][promotion][ancestor_trace] matched_text_view_id='{}' matched_text_bounds='{}' trace='{}'".format(
                        matched_view_id[:64],
                        matched_bounds_repr,
                        trace_summary[:400],
                    )
                )
            _log_promotion_exit(None, "none")
            return (
                None,
                "none",
                0,
                f"{source_name}:no_candidate:rejected_large={int(stats.get('rejected_large_container_count', 0) or 0)}:rejected_list_like={int(stats.get('rejected_list_like_container_count', 0) or 0)}",
                ancestor_distance,
                "",
            )
        scored_candidates.sort(reverse=True, key=lambda item: item[0])
        best_node = scored_candidates[0][1]
        best_reason = scored_candidates[0][2]
        best_distance = int(ancestor_distance_by_node_id.get(id(best_node), ancestor_distance if ancestor_distance >= 0 else 999))
        _log_promotion_exit(best_node, best_reason)
        return (
            best_node,
            best_reason,
            len(scored_candidates),
            f"{source_name}:candidate_count={len(scored_candidates)}:rejected_large={int(stats.get('rejected_large_container_count', 0) or 0)}:rejected_list_like={int(stats.get('rejected_list_like_container_count', 0) or 0)}",
            best_distance,
            top3_summary,
        )

    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for node, parent in flat_nodes:
        raw_bounds = str(node.get("boundsInScreen", "") or "").strip()
        bounds = parse_bounds_str(raw_bounds)
        if not bounds:
            _append_rejection(stats, "invalid_bounds")
            _record_inspect(stats, node_ref=node, promoted_click_node=None, reject_reason="invalid_bounds")
            continue
        left, top, right, bottom = bounds
        if not (left < right and top < bottom):
            _append_rejection(stats, "invalid_bounds_geometry")
            _record_inspect(stats, node_ref=node, promoted_click_node=None, reject_reason="invalid_bounds_geometry")
            continue
        if bottom <= viewport_top or top >= viewport_bottom:
            _append_rejection(stats, "outside_viewport")
            _record_inspect(stats, node_ref=node, promoted_click_node=None, reject_reason="outside_viewport")
            continue
        if not _node_is_visible(node):
            _append_rejection(stats, "invisible_node")
            _record_inspect(stats, node_ref=node, promoted_click_node=None, reject_reason="invisible_node")
            continue
        node_area = (right - left) * (bottom - top)
        if node_area >= int(viewport_area * 0.92) and not _is_actionable(node):
            _append_rejection(stats, "oversized_non_actionable_root")
            _record_inspect(stats, node_ref=node, promoted_click_node=None, reject_reason="oversized_non_actionable_root")
            continue
        click_node = node
        promoted_click_node: dict[str, Any] | None = None
        promotion_reason = "none"
        matched_text_node = (
            str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or node.get("className", "") or "node").strip()
        )
        if isinstance(parent, dict):
            parent_clickable = bool(parent.get("clickable")) or bool(parent.get("focusable"))
            parent_resource = str(parent.get("viewIdResourceName", "") or parent.get("resourceId", "") or "").strip()
            if parent_clickable or _safe_regex_search(r"(?i)(preinstalledservicecard|servicecard|card)", parent_resource):
                click_node = parent
                promoted_click_node = parent
                promotion_reason = "parent_clickable_or_card"
        label_blob = _node_label_blob(node)
        click_label_blob = _node_label_blob(click_node)
        click_descendant_blob = " ".join(descendants_by_container.get(id(click_node), []))
        if not (label_blob or click_label_blob or click_descendant_blob):
            _append_rejection(stats, "no_label_blob")
            _record_inspect(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reject_reason="no_label_blob",
                matched_text_node=matched_text_node,
                promotion_reason=promotion_reason,
            )
            continue
        pre_semantic_blob = " ".join(part for part in [label_blob, click_label_blob, click_descendant_blob] if part).strip()
        title_semantic_match = any(_safe_regex_search(pattern, pre_semantic_blob) for pattern in title_patterns)
        description_semantic_match = allow_description_match and any(
            _safe_regex_search(pattern, pre_semantic_blob) for pattern in description_patterns
        )
        label_normalized = _normalize_phrase(label_blob)
        click_label_normalized = _normalize_phrase(click_label_blob)
        descendant_normalized = _normalize_phrase(click_descendant_blob)
        pre_semantic_normalized = _normalize_phrase(pre_semantic_blob)
        semantic_contains_phrase = bool(
            pre_semantic_normalized
            and any(
                phrase in pre_semantic_normalized or pre_semantic_normalized in phrase
                for phrase in normalized_target_phrases
                if phrase
            )
        )
        semantic_tokens = _tokenize_blob(" ".join([label_blob, click_label_blob, click_descendant_blob]))
        overlap_tokens = semantic_tokens.intersection(target_token_set)
        combined_overlap_tokens = semantic_tokens.intersection(combined_target_tokens)
        required_overlap = len(target_token_set) if len(target_token_set) <= 2 else len(target_token_set) - 1
        token_cover_match = bool(target_token_set and len(overlap_tokens) >= max(1, required_overlap))
        click_node_resource = str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or "")
        click_node_class_name = str(click_node.get("className", "") or "")
        alias_hits: list[str] = []
        alias_token_pair_hits = 0
        descendant_alias_hit_count = 0
        content_desc_alias_hit_count = 0
        content_desc_normalized = _normalize_phrase(str(click_node.get("contentDescription", "") or ""))
        for alias_phrase, alias_tokens in alias_phrase_map:
            alias_in_any = bool(alias_phrase and pre_semantic_normalized and alias_phrase in pre_semantic_normalized)
            alias_in_descendant = bool(alias_phrase and descendant_normalized and alias_phrase in descendant_normalized)
            alias_in_content_desc = bool(alias_phrase and content_desc_normalized and alias_phrase in content_desc_normalized)
            if alias_in_any:
                alias_hits.append(alias_phrase)
            if alias_in_descendant:
                descendant_alias_hit_count += 1
            if alias_in_content_desc:
                content_desc_alias_hit_count += 1
            if len(alias_tokens) >= 2 and len(alias_tokens.intersection(semantic_tokens)) >= 2:
                alias_token_pair_hits += 1
        resource_tokens = set()
        resource_tokens.update(_tokenize_resource_id(node.get("viewIdResourceName", "") or node.get("resourceId", "")))
        resource_tokens.update(_tokenize_resource_id(click_node_resource))
        resource_token_alias_hits = resource_tokens.intersection(alias_token_set.union(semantic_hint_tokens))
        resource_token_hit_count = len(resource_token_alias_hits)
        resource_hint_combo_hit = bool(resource_token_hit_count and (alias_hits or semantic_hint_tokens.intersection(semantic_tokens)))
        weak_generic_tokens = generic_weak_tokens.intersection(combined_overlap_tokens)
        generic_single_token_target = bool(len(target_token_set) == 1 and next(iter(target_token_set), "") in {"find", "video"})
        generic_guard_checks = 0
        if bool(_is_actionable(click_node)) or bool(_safe_regex_search(r"(?i)(card|container|layout|item|content)", click_node_resource + " " + click_node_class_name)):
            generic_guard_checks += 1
        if descendant_normalized or click_label_normalized:
            generic_guard_checks += 1
        if bool(_safe_regex_search(r"(?i)(smart|servicecard|plugin|care|find|video)", pre_semantic_blob)):
            generic_guard_checks += 1
        if not bool(_safe_regex_search(r"(?i)\b(add|more options|location|navigate up|home|back|button)\b", pre_semantic_blob)):
            generic_guard_checks += 1
        if not bool(_safe_regex_search(r"(?i)(recycler.?view|grid.?view|list.?view)", click_node_class_name + " " + click_node_resource)):
            generic_guard_checks += 1
        strong_evidence_count = 0
        medium_evidence_count = 0
        weak_evidence_count = 0
        if semantic_contains_phrase or token_cover_match:
            strong_evidence_count += 1
        if alias_hits:
            strong_evidence_count += 1
        if alias_token_pair_hits > 0:
            strong_evidence_count += 1
        if descendant_alias_hit_count > 0:
            medium_evidence_count += 1
        if resource_hint_combo_hit:
            medium_evidence_count += 1
        if content_desc_alias_hit_count > 0:
            medium_evidence_count += 1
        if weak_generic_tokens:
            weak_evidence_count += 1
        if strong_evidence_count >= 1:
            semantic_evidence_class = "strong"
        elif medium_evidence_count >= 1:
            semantic_evidence_class = "medium"
        elif weak_evidence_count >= 1:
            semantic_evidence_class = "weak"
        else:
            semantic_evidence_class = "miss"
        alias_hit_count = len(alias_hits)
        alias_hit_top = alias_hits[0] if alias_hits else ""
        resource_token_hit_top = " + ".join(sorted(resource_token_alias_hits)[:2]) if resource_token_alias_hits else ""
        stats["alias_hit_count"] += alias_hit_count
        if alias_hit_top and not stats.get("alias_hit_top"):
            stats["alias_hit_top"] = alias_hit_top
        stats["resource_token_hit_count"] += resource_token_hit_count
        if resource_token_hit_top and not stats.get("resource_token_hit_top"):
            stats["resource_token_hit_top"] = resource_token_hit_top
        stats["descendant_alias_hit_count"] += descendant_alias_hit_count
        stats["semantic_evidence_class"] = semantic_evidence_class
        relaxed_gate_match = bool(
            semantic_contains_phrase
            or token_cover_match
            or alias_hit_count > 0
            or alias_token_pair_hits > 0
            or medium_evidence_count > 0
            or weak_evidence_count > 0
        )
        generic_guard_passed = bool((not generic_single_token_target) or generic_guard_checks >= 2)
        if generic_single_token_target and relaxed_gate_match and not generic_guard_passed:
            stats["generic_guard_block_count"] += 1
        card_like_hint = bool(
            _safe_regex_search(r"(?i)(card|container|layout|frame|content|item|root|servicecard)", click_node_resource)
            or _safe_regex_search(r"(?i)(card|layout|viewgroup|frame)", click_node_class_name)
        )
        probe_accept_reason = "none"
        probe_reject_reason = "none"
        evidence_pass = False
        if strong_evidence_count >= 1:
            evidence_pass = True
            probe_accept_reason = "strong_single"
        elif medium_evidence_count >= 2:
            evidence_pass = True
            probe_accept_reason = "medium_plus_medium"
        elif medium_evidence_count >= 1 and weak_evidence_count >= 1 and card_like_hint:
            evidence_pass = True
            probe_accept_reason = "medium_plus_weak_with_card"
        pre_candidate_match = bool(title_semantic_match or description_semantic_match or (evidence_pass and generic_guard_passed and card_like_hint))
        probe_allowed = False
        probe_promoted = False
        probe_text_source = "none"
        probe_match_reason = "none"
        probe_guard_reason = "none"
        hard_reject_reason = "none"
        if not pre_candidate_match:
            has_text_evidence = bool(pre_semantic_blob.strip() or click_descendant_blob.strip())
            if not has_text_evidence:
                hard_reject_reason = "probe_no_text_evidence"
                probe_reject_reason = hard_reject_reason
            elif _is_chrome_like_blob(pre_semantic_blob):
                hard_reject_reason = "probe_chrome_like"
                probe_reject_reason = hard_reject_reason
            elif _is_large_or_list_like_node(click_node, (left, top, right, bottom)):
                hard_reject_reason = "probe_large_or_list_like"
                probe_reject_reason = hard_reject_reason
            elif not _node_is_visible(click_node):
                hard_reject_reason = "probe_not_visible"
                probe_reject_reason = hard_reject_reason
            elif not (card_like_hint or bool(click_descendant_blob.strip())):
                hard_reject_reason = "probe_not_card_like"
                probe_reject_reason = hard_reject_reason
            else:
                probe_allowed = True
                stats["semantic_probe_pool_count"] += 1
                if len(stats["probe_samples"]) < 5:
                    stats["probe_samples"].append(
                        "source='pre_candidate' reason='semantic_probe_allowed' rid='{}'".format(
                            _clip(click_node_resource or click_node.get("resourceId", ""), sample_id_limit)
                        )
                    )
                probe_phrase_match = semantic_contains_phrase or bool(alias_hits)
                probe_token_match = bool(token_cover_match or alias_token_pair_hits > 0 or resource_hint_combo_hit)
                probe_match_reason = semantic_evidence_class
                if click_descendant_blob.strip():
                    probe_text_source = "descendant_text"
                elif click_label_blob.strip():
                    probe_text_source = "click_label"
                elif label_blob.strip():
                    probe_text_source = "node_label"
                else:
                    probe_text_source = "semantic_blob"
                probe_guard_passed = generic_guard_passed
                if generic_single_token_target and (probe_phrase_match or probe_token_match) and not probe_guard_passed:
                    stats["probe_guard_block_count"] += 1
                    probe_guard_reason = "generic_token_guard_failed"
                    probe_reject_reason = "generic_token_without_card_evidence"
                elif not evidence_pass:
                    probe_guard_reason = "probe_semantic_miss"
                    probe_reject_reason = "insufficient_evidence"
                else:
                    probe_guard_reason = "passed"
                if probe_guard_passed and evidence_pass and card_like_hint:
                    pre_candidate_match = True
                    probe_promoted = True
                    stats["semantic_probe_match_count"] += 1
                    stats["probe_accept_reason"] = probe_accept_reason
                else:
                    stats["semantic_probe_reject_count"] += 1
                    if not probe_reject_reason:
                        probe_reject_reason = "generic_token_without_card_evidence" if not card_like_hint else "insufficient_evidence"
                    stats["probe_reject_reason"] = probe_reject_reason
                    if len(stats["probe_reject_samples"]) < 5:
                        stats["probe_reject_samples"].append(
                            "reason='{}' rid='{}' alias_hit_top='{}' resource_token_hit_top='{}'".format(
                                probe_reject_reason or probe_guard_reason,
                                _clip(click_node_resource or click_node.get("resourceId", ""), sample_id_limit),
                                _clip(alias_hit_top, sample_text_limit),
                                _clip(resource_token_hit_top, sample_text_limit),
                            )
                        )
            if not probe_allowed:
                stats["hard_filter_reject_count"] += 1
        if not pre_candidate_match:
            _append_rejection(stats, "filtered_hard" if not probe_allowed else "semantic_probe_rejected")
            reject_reason = "filtered_hard" if not probe_allowed else "semantic_probe_rejected"
            _append_rejection(stats, "filtered_before_candidate")
            _record_inspect(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reject_reason=reject_reason,
                stage="label_filter",
                matched_text_node=matched_text_node,
                promotion_reason=promotion_reason,
                filter_stage="filtered_hard" if not probe_allowed else "semantic_probe_rejected",
                hard_reject_reason=hard_reject_reason,
                probe_allowed=probe_allowed,
                probe_text_source=probe_text_source,
                probe_match_reason=probe_match_reason,
                probe_guard_reason=probe_guard_reason,
                probe_promoted=probe_promoted,
                alias_hit_count=alias_hit_count,
                alias_hit_top=alias_hit_top,
                resource_token_hit_count=resource_token_hit_count,
                descendant_alias_hit_count=descendant_alias_hit_count,
                semantic_evidence_class=semantic_evidence_class,
                probe_accept_reason=probe_accept_reason,
                probe_reject_reason=probe_reject_reason,
            )
            continue
        click_bounds = parse_bounds_str(str(click_node.get("boundsInScreen", "") or "").strip())
        if not click_bounds:
            _append_rejection(stats, "no_click_node_bounds")
            _record_inspect(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reject_reason="no_click_node_bounds",
                matched_text_node=matched_text_node,
                promotion_reason=promotion_reason,
            )
            _record_pre_candidate(stats, node_ref=node, promoted_click_node=promoted_click_node, reason="promotion_fail:no_click_node_bounds")
            continue
        c_left, c_top, c_right, c_bottom = click_bounds
        if not (c_left < c_right and c_top < c_bottom):
            _append_rejection(stats, "invalid_click_node_bounds")
            _record_inspect(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reject_reason="invalid_click_node_bounds",
                matched_text_node=matched_text_node,
                promotion_reason=promotion_reason,
            )
            _record_pre_candidate(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reason="promotion_fail:invalid_click_node_bounds",
            )
            continue
        if c_bottom <= viewport_top or c_top >= viewport_bottom:
            _append_rejection(stats, "click_node_not_visible")
            _record_inspect(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reject_reason="click_node_not_visible",
                matched_text_node=matched_text_node,
                promotion_reason=promotion_reason,
            )
            _record_pre_candidate(stats, node_ref=node, promoted_click_node=promoted_click_node, reason="actionability_fail:click_node_not_visible")
            continue
        stats["visible_candidate_count"] += 1
        title_blob = " ".join(
            [
                str(click_node.get("text", "") or "").strip(),
                str(click_node.get("contentDescription", "") or "").strip(),
            ]
        ).strip()
        descendant_blob = click_descendant_blob
        semantic_blob = " ".join(part for part in [label_blob, title_blob, descendant_blob] if part).strip()
        if not semantic_blob:
            _append_rejection(stats, "promoted_label_empty")
            _record_inspect(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reject_reason="promoted_label_empty",
                matched_text_node=matched_text_node,
                promotion_reason=promotion_reason,
            )
            continue
        semantic_blob_lower = semantic_blob.lower()
        resource_blob = " ".join(
            [
                str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip(),
                str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or "").strip(),
            ]
        ).strip()
        title_semantic_match = any(_safe_regex_search(pattern, title_blob) or _safe_regex_search(pattern, semantic_blob) for pattern in title_patterns)
        description_semantic_match = allow_description_match and any(
            _safe_regex_search(pattern, semantic_blob) for pattern in description_patterns
        )
        resource_semantic_match = any(_safe_regex_search(pattern, resource_blob) for pattern in resource_patterns)
        if combined_target_tokens and any(token in semantic_blob_lower for token in combined_target_tokens):
            stats["partial_match_count"] += 1
        elif description_semantic_match or resource_semantic_match:
            stats["partial_match_count"] += 1
        click_node_class_name = str(click_node.get("className", "") or "").strip()
        container_class_match = bool(_safe_regex_search(r"(?i)(frame.?layout|relative.?layout|viewgroup)", click_node_class_name))
        container_has_text_descendant = bool(click_descendant_blob.strip())
        container_title_match = bool(
            container_class_match
            and container_has_text_descendant
            and _node_is_visible(click_node)
            and _is_actionable(click_node)
            and any(_safe_regex_search(pattern, click_descendant_blob) for pattern in title_patterns)
        )
        semantic_match = bool(title_semantic_match or description_semantic_match or resource_semantic_match or container_title_match)
        relaxed_semantic_match = False
        relaxed_source = "none"
        relaxed_reason = "none"
        generic_guard_passed_final = True
        if not semantic_match:
            click_node_resource = str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or "").strip()
            click_node_class_name = str(click_node.get("className", "") or "").strip()
            click_node_container_like = bool(
                _safe_regex_search(r"(?i)(card|container|layout|frame|content|item|root)", click_node_resource)
                or _safe_regex_search(r"(?i)(card|container|layout|frame|viewgroup)", click_node_class_name)
            )
            actionable_or_container_like = bool(_is_actionable(click_node) or click_node_container_like)
            semantic_evidence_present = bool(click_descendant_blob.strip() or title_blob.strip() or label_blob.strip())
            if actionable_or_container_like and semantic_evidence_present:
                normalized_semantic_blob = _normalize_phrase(semantic_blob)
                phrase_contains_match = bool(
                    normalized_semantic_blob
                    and any(
                        phrase in normalized_semantic_blob or normalized_semantic_blob in phrase
                        for phrase in normalized_target_phrases
                        if phrase
                    )
                )
                semantic_tokens = _tokenize_blob(" ".join([semantic_blob, title_blob, click_descendant_blob]))
                overlap_tokens = semantic_tokens.intersection(target_token_set)
                combined_overlap_tokens = semantic_tokens.intersection(combined_target_tokens)
                required_overlap = len(target_token_set) if len(target_token_set) <= 2 else len(target_token_set) - 1
                token_overlap_match = bool(target_token_set and len(overlap_tokens) >= max(1, required_overlap))
                alias_overlap_count = len(semantic_tokens.intersection(alias_token_set))
                descendant_alias_hit = bool(descendant_normalized and any(alias_phrase in descendant_normalized for alias_phrase, _ in alias_phrase_map))
                content_desc_normalized = _normalize_phrase(str(click_node.get("contentDescription", "") or ""))
                content_desc_alias_hit = bool(content_desc_normalized and any(alias_phrase in content_desc_normalized for alias_phrase, _ in alias_phrase_map))
                resource_tokens = set()
                resource_tokens.update(_tokenize_resource_id(node.get("viewIdResourceName", "") or node.get("resourceId", "")))
                resource_tokens.update(_tokenize_resource_id(click_node_resource))
                resource_alias_hit = bool(resource_tokens.intersection(alias_token_set.union(semantic_hint_tokens)))
                weak_generic_hit = bool(generic_weak_tokens.intersection(combined_overlap_tokens))
                generic_single_token_target = bool(
                    len(target_token_set) == 1 and next(iter(target_token_set), "") in {"find", "video"}
                )
                generic_guard_checks = 0
                if actionable_or_container_like:
                    generic_guard_checks += 1
                if bool(title_blob.strip() or click_descendant_blob.strip()):
                    generic_guard_checks += 1
                if bool(_safe_regex_search(r"(?i)(smart|service|plugin|care|find|video)", semantic_blob)):
                    generic_guard_checks += 1
                if not bool(_safe_regex_search(r"(?i)\b(add|more options|location|navigate up|home|button)\b", semantic_blob)):
                    generic_guard_checks += 1
                if not bool(_safe_regex_search(r"(?i)(recycler.?view|grid.?view|list.?view)", click_node_class_name + " " + click_node_resource)):
                    generic_guard_checks += 1
                generic_guard_passed_final = bool((not generic_single_token_target) or generic_guard_checks >= 2)
                if generic_single_token_target and not generic_guard_passed_final and (phrase_contains_match or token_overlap_match or weak_generic_hit):
                    stats["generic_guard_block_count"] += 1
                strong_evidence = bool(phrase_contains_match or token_overlap_match or alias_overlap_count >= 2)
                medium_evidence_count = 0
                if descendant_alias_hit:
                    medium_evidence_count += 1
                if resource_alias_hit:
                    medium_evidence_count += 1
                if content_desc_alias_hit:
                    medium_evidence_count += 1
                if strong_evidence and generic_guard_passed_final:
                    relaxed_semantic_match = True
                    relaxed_reason = "strong_single"
                    if descendant_blob.strip():
                        relaxed_source = "descendant_summary"
                    elif title_blob.strip():
                        relaxed_source = "descendant_title"
                    elif label_blob.strip():
                        relaxed_source = "node_label"
                    else:
                        relaxed_source = "semantic_blob"
                elif medium_evidence_count >= 2 and generic_guard_passed_final:
                    relaxed_semantic_match = True
                    relaxed_reason = "medium_plus_medium"
                    relaxed_source = "semantic_blob"
                elif medium_evidence_count >= 1 and weak_generic_hit and click_node_container_like and generic_guard_passed_final:
                    relaxed_semantic_match = True
                    relaxed_reason = "medium_plus_weak_with_card"
                    relaxed_source = "semantic_blob"
        semantic_match = bool(semantic_match or relaxed_semantic_match)
        if relaxed_semantic_match:
            stats["fallback_applied_count"] += 1
            stats["relaxed_semantic_match_count"] += 1
            if len(stats["relaxed_semantic_samples"]) < 5:
                stats["relaxed_semantic_samples"].append(
                    "source='{}' reason='{}' generic_token_guard_passed={} exact_or_partial_absent=true".format(
                        relaxed_source,
                        relaxed_reason,
                        str(bool(generic_guard_passed_final)).lower(),
                    )
                )
        if not semantic_match:
            if probe_allowed:
                stats["semantic_probe_reject_count"] += 1
                if len(stats["probe_reject_samples"]) < 5:
                    stats["probe_reject_samples"].append(
                        "reason='semantic_probe_post_filter_miss' rid='{}'".format(
                            _clip(str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or ""), sample_id_limit)
                        )
                    )
            _append_rejection(stats, "semantic_miss")
            _record_inspect(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reject_reason="semantic_miss",
                stage="semantic_filter",
                matched_text_node=matched_text_node,
                promotion_reason=promotion_reason,
                filter_stage="semantic_probe_rejected" if probe_allowed else "filtered_hard",
                hard_reject_reason=hard_reject_reason,
                probe_allowed=probe_allowed,
                probe_text_source=probe_text_source,
                probe_match_reason=probe_match_reason,
                probe_guard_reason=probe_guard_reason,
                probe_promoted=False,
                alias_hit_count=alias_hit_count,
                alias_hit_top=alias_hit_top,
                resource_token_hit_count=resource_token_hit_count,
                descendant_alias_hit_count=descendant_alias_hit_count,
                semantic_evidence_class=semantic_evidence_class,
                probe_accept_reason=probe_accept_reason,
                probe_reject_reason=probe_reject_reason or "semantic_probe_post_filter_miss",
            )
            _record_pre_candidate(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reason="semantic_pass_partial_but_exact_fail",
            )
            continue
        promotion_attempted = False
        promotion_source = "none"
        promotion_candidate_count = 0
        promotion_debug_summary = ""
        ancestor_distance = -1
        rank_summary_top3 = ""
        actionable_before_fallback = bool(_is_actionable(click_node))
        helper_result = "not_attempted"
        commit_to_candidate = bool(actionable_before_fallback)
        requires_promotion_fallback = bool((not actionable_before_fallback) and matched_text_node)
        if requires_promotion_fallback:
            promotion_attempted = True
            promoted_from_helper, helper_reason, helper_candidate_count, helper_debug, helper_ancestor_distance, helper_top3 = _select_promoted_container(
                matched_node=node,
                node_bounds=bounds,
                viewport_bounds=(viewport_top, viewport_bottom),
                source_nodes=actionable_nodes,
                source_name="helper",
                parent_map=parent_by_node_id,
            )
            promotion_candidate_count = helper_candidate_count
            promotion_debug_summary = helper_debug
            helper_result = helper_reason if isinstance(promoted_from_helper, dict) else "none"
            if isinstance(promoted_from_helper, dict):
                promoted_click_node = promoted_from_helper
                click_node = promoted_from_helper
                promotion_reason = helper_reason
                promotion_source = "helper"
                ancestor_distance = helper_ancestor_distance
                rank_summary_top3 = helper_top3
            commit_to_candidate = bool(_is_actionable(click_node))
            should_try_xml_live_fallback = bool(
                matched_text_node
                and int(stats.get("partial_match_count", 0) or 0) > 0
                and (helper_result == "none" or not commit_to_candidate)
                and not actionable_before_fallback
            )
            stats["will_try_xml_live_fallback"] = bool(should_try_xml_live_fallback)
            log(
                "[SCROLLTOUCH][promotion][fallback_decision] matched_text_found={} partial_match_count={} helper_result='{}' "
                "commit_to_candidate={} actionable_before_fallback={} will_try_xml_live_fallback={}".format(
                    str(bool(matched_text_node)).lower(),
                    int(stats.get("partial_match_count", 0) or 0),
                    str(helper_result)[:64],
                    str(bool(commit_to_candidate)).lower(),
                    str(bool(actionable_before_fallback)).lower(),
                    str(bool(should_try_xml_live_fallback)).lower(),
                )
            )
            if should_try_xml_live_fallback and xml_flat_nodes:
                promoted_from_xml, xml_reason, xml_candidate_count, xml_debug, xml_ancestor_distance, xml_top3 = _select_promoted_container(
                    matched_node=node,
                    node_bounds=bounds,
                    viewport_bounds=(viewport_top, viewport_bottom),
                    source_nodes=xml_actionable_nodes,
                    source_name="xml_live",
                    parent_map=xml_parent_by_node_id,
                    source_flat_nodes=xml_flat_nodes,
                )
                promotion_candidate_count = max(promotion_candidate_count, xml_candidate_count)
                promotion_debug_summary = f"{helper_debug};{xml_debug}"
                if isinstance(promoted_from_xml, dict):
                    promoted_click_node = promoted_from_xml
                    click_node = promoted_from_xml
                    promotion_reason = xml_reason
                    promotion_source = "xml_live"
                    ancestor_distance = xml_ancestor_distance
                    rank_summary_top3 = xml_top3
                commit_to_candidate = bool(_is_actionable(click_node))
            selected_container_bounds = str(click_node.get("boundsInScreen", "") or "").strip()
            selected_container_class = str(click_node.get("className", "") or "").strip()
            selected_container_view_id = str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or "").strip()
            log(
                "[SCROLLTOUCH][promotion][salvage] source='{}' reason='{}' selected_ancestor_distance={} selected_container_class='{}' selected_container_view_id='{}' "
                "rejected_large_container_count={} rejected_list_like_container_count={}".format(
                    promotion_source,
                    promotion_reason,
                    int(ancestor_distance),
                    selected_container_class[:48],
                    selected_container_view_id[:64],
                    int(stats.get("rejected_large_container_count", 0) or 0),
                    int(stats.get("rejected_list_like_container_count", 0) or 0),
                )
            )
            log(
                "[SCROLLTOUCH][promotion][commit] selected_container_class='{}' selected_container_view_id='{}' selected_container_bounds='{}' "
                "commit_to_candidate={} commit_stage='promotion_select' commit_failure_reason='{}'".format(
                    selected_container_class[:64],
                    selected_container_view_id[:64],
                    selected_container_bounds[:64],
                    str(bool(_is_actionable(click_node))).lower(),
                    "not_committed" if not _is_actionable(click_node) else "none",
                )
            )
        if not _is_actionable(click_node):
            stats["last_promotion_result_reason"] = "non_actionable_without_promotion"
            _append_rejection(stats, "non_actionable_without_promotion")
            _record_inspect(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reject_reason="non_actionable_without_promotion",
                stage="actionability_gate",
                matched_text_node=matched_text_node,
                promotion_reason=promotion_reason,
            )
            _record_pre_candidate(
                stats,
                node_ref=node,
                promoted_click_node=promoted_click_node,
                reason="actionability_fail:non_actionable_without_promotion",
            )
            log(
                "[SCROLLTOUCH][promotion][commit] selected_container_class='{}' selected_container_view_id='{}' selected_container_bounds='{}' "
                "commit_to_candidate=false commit_stage='actionability_gate' commit_failure_reason='not_committed'".format(
                    str(click_node.get("className", "") or "").strip()[:64],
                    str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or "").strip()[:64],
                    str(click_node.get("boundsInScreen", "") or "").strip()[:64],
                )
            )
            continue
        click_bounds = parse_bounds_str(str(click_node.get("boundsInScreen", "") or "").strip())
        if not click_bounds:
            _append_rejection(stats, "no_click_node_bounds_after_promotion")
            continue
        c_left, c_top, c_right, c_bottom = click_bounds
        if not (c_left < c_right and c_top < c_bottom):
            _append_rejection(stats, "invalid_click_node_bounds_after_promotion")
            continue
        card_resource = str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or "")
        class_name = str(click_node.get("className", "") or "").strip()
        bounds_repr = str(click_node.get("boundsInScreen", "") or "").strip()
        sample_repr = (
            f"label='{label_blob[:60]}' rid='{card_resource[:40]}' cls='{class_name[:32]}' bounds='{bounds_repr[:24]}'"
        )
        if len(stats["visible_samples"]) < 5:
            stats["visible_samples"].append(sample_repr)
        is_exact = bool(_safe_regex_search(target, title_blob))
        if is_exact:
            stats["exact_match_count"] += 1
        center_delta = abs(((c_top + c_bottom) // 2) - viewport_center)
        if target_tokens and any(token in semantic_blob.lower() for token in target_tokens) and len(stats["partial_samples"]) < 5:
            stats["partial_samples"].append(sample_repr)
        promoted_from = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or node.get("className", "") or "").strip()
        promoted_to = str(click_node.get("viewIdResourceName", "") or click_node.get("resourceId", "") or click_node.get("className", "") or "").strip()
        matched_text_bounds = bounds
        selected_area = max(1, (c_right - c_left) * (c_bottom - c_top))
        matched_text_area = max(1, (matched_text_bounds[2] - matched_text_bounds[0]) * (matched_text_bounds[3] - matched_text_bounds[1]))
        area_ratio = round(selected_area / float(matched_text_area), 3)
        text_inter_left = max(c_left, matched_text_bounds[0])
        text_inter_top = max(c_top, matched_text_bounds[1])
        text_inter_right = min(c_right, matched_text_bounds[2])
        text_inter_bottom = min(c_bottom, matched_text_bounds[3])
        text_intersection_area = 0
        if text_inter_left < text_inter_right and text_inter_top < text_inter_bottom:
            text_intersection_area = (text_inter_right - text_inter_left) * (text_inter_bottom - text_inter_top)
        containment_score = round(min(1.0, text_intersection_area / float(matched_text_area)), 3)
        title_exact_match = 1.0 if is_exact else 0.0
        title_partial_match = 1.0 if (target_tokens and any(token in semantic_blob.lower() for token in target_tokens)) else 0.0
        semantic_score = 1.0 if semantic_match else 0.0
        structure_score = round(max(0.0, 1.0 - (center_delta / float(max(1, viewport_bottom - viewport_top)))), 3)
        accumulated_score = round((title_exact_match * 1.0) + (title_partial_match * 0.6) + (semantic_score * 0.4), 3)
        final_score = (
            (semantic_score * 3.0)
            + (title_exact_match * 2.5)
            + (title_partial_match * 1.5)
            + (containment_score * 1.0)
            + (structure_score * 0.5)
            + (accumulated_score * 0.3)
        )
        xml_live_containment = bool(str(promotion_reason or "").startswith("xml_live_containment_container"))
        log(
            "[SCROLLTOUCH][RERANK_SCORE] candidate='{}' semantic={} title_exact={} title_partial={} containment={} structure={} final_score={:.3f}".format(
                _clip(card_resource or label_blob or class_name, 80),
                str(bool(semantic_match)).lower(),
                f"{title_exact_match:.1f}",
                f"{title_partial_match:.1f}",
                f"{containment_score:.3f}",
                f"{structure_score:.3f}",
                float(final_score),
            )
        )
        center_x = (c_left + c_right) // 2
        center_y = (c_top + c_bottom) // 2
        text_center_x = (matched_text_bounds[0] + matched_text_bounds[2]) // 2
        text_center_y = (matched_text_bounds[1] + matched_text_bounds[3]) // 2
        tap_strategy = "center"
        tap_x = center_x
        tap_y = center_y
        is_generic_wrapper = bool(
            promotion_source == "xml_live"
            and _safe_regex_search(r"(?i)relative.?layout|linear.?layout|frame.?layout", class_name)
            and not card_resource
            and not _node_label_blob(click_node)
            and area_ratio >= 2.0
        )
        if is_generic_wrapper:
            tap_x = min(max(text_center_x, c_left + 1), c_right - 1)
            tap_y = min(max(text_center_y, c_top + 1), c_bottom - 1)
            tap_strategy = "text_center"
            refined_y = text_center_y - max(6, (matched_text_bounds[3] - matched_text_bounds[1]) // 6)
            if c_top < refined_y < c_bottom:
                tap_y = refined_y
                tap_strategy = "refined_body_point"
        if probe_promoted:
            stats["candidate_from_probe_count"] += 1
        _record_inspect(
            stats,
            node_ref=node,
            promoted_click_node=promoted_click_node,
            reject_reason="survive_candidate",
            stage="candidate_ready",
            matched_text_node=matched_text_node,
            promotion_reason=promotion_reason,
            promoted_from=promoted_from,
            promoted_to=promoted_to,
            filter_stage="semantic_probe_allowed" if probe_allowed else "filtered_hard",
            hard_reject_reason=hard_reject_reason,
            probe_allowed=probe_allowed,
            probe_text_source=probe_text_source,
            probe_match_reason=probe_match_reason,
            probe_guard_reason=probe_guard_reason,
            probe_promoted=probe_promoted,
        )
        candidate_meta = {
            "promoted_container": bool(promoted_click_node is not None),
            "promotion_attempted": promotion_attempted,
            "promotion_source": promotion_source,
            "promotion_reason": promotion_reason if promoted_click_node is not None else "none",
            "promoted_from": promoted_from,
            "promoted_to": promoted_to,
            "promotion_candidate_count": promotion_candidate_count,
            "promotion_debug_summary": promotion_debug_summary,
            "matched_text_node": matched_text_node,
            "matched_text_bounds": f"{matched_text_bounds[0]},{matched_text_bounds[1]},{matched_text_bounds[2]},{matched_text_bounds[3]}",
            "selected_area": selected_area,
            "matched_text_area": matched_text_area,
            "selected_to_text_area_ratio": area_ratio,
            "ancestor_distance": ancestor_distance,
            "selected_ancestor_distance": ancestor_distance,
            "selected_container_class": class_name,
            "selected_container_view_id": card_resource,
            "tap_point": f"{tap_x},{tap_y}",
            "tap_strategy": tap_strategy,
            "rank_summary_top3": rank_summary_top3,
            "semantic_match": bool(semantic_match),
            "containment_score": float(containment_score),
            "xml_live_containment": bool(xml_live_containment),
            "title_exact_match": float(title_exact_match),
            "title_partial_match": float(title_partial_match),
            "structure_score": float(structure_score),
            "accumulated_score": float(accumulated_score),
            "final_score": float(final_score),
            "is_near_exact_text_match": bool(title_exact_match >= 1.0 or (title_partial_match >= 1.0 and semantic_score >= 1.0)),
        }
        stats["candidate_committed"] = True
        log(
            "[SCROLLTOUCH][promotion][commit] selected_container_class='{}' selected_container_view_id='{}' selected_container_bounds='{}' "
            "commit_to_candidate=true commit_stage='candidate_append' commit_failure_reason='none'".format(
                class_name[:64],
                card_resource[:64],
                bounds_repr[:64],
            )
        )
        candidates.append((float(final_score), click_node, candidate_meta))

    if not candidates:
        return None, "no_visible_candidate", stats, selected_meta
    semantic_candidates = [item for item in candidates if bool(item[2].get("semantic_match", False))]
    rerank_enabled = bool(len(candidates) >= 2 and len(semantic_candidates) >= 1)
    log(
        "[SCROLLTOUCH][RERANK_GATE] candidate_count={} semantic_candidates={} rerank_enabled={}".format(
            len(candidates),
            len(semantic_candidates),
            str(rerank_enabled).lower(),
        )
    )
    if len(candidates) == 1:
        only_meta = candidates[0][2]
        only_containment = float(only_meta.get("containment_score", 0.0) or 0.0)
        only_xml_live_containment = bool(only_meta.get("xml_live_containment", False))
        only_semantic = bool(only_meta.get("semantic_match", False))
        if only_semantic and (only_containment >= 0.8 or only_xml_live_containment):
            log(
                "[SCROLLTOUCH][IMMEDIATE_STRONG_SINGLE] reason=single_strong_candidate containment={} semantic={}".format(
                    f"{only_containment:.3f}",
                    str(only_semantic).lower(),
                )
            )
            return candidates[0][1], "immediate_strong_single", stats, only_meta
    if rerank_enabled:
        candidates.sort(
            reverse=True,
            key=lambda item: (
                1 if bool(item[2].get("is_near_exact_text_match", False)) else 0,
                float(item[0]),
                float(item[2].get("containment_score", 0.0) or 0.0),
                float(item[2].get("structure_score", 0.0) or 0.0),
            ),
        )
    else:
        candidates.sort(reverse=True, key=lambda item: float(item[0]))
    winner = candidates[0]
    if not bool(winner[2].get("semantic_match", False)) and semantic_candidates:
        semantic_candidates.sort(reverse=True, key=lambda item: float(item[0]))
        winner = semantic_candidates[0]
        log(
            "[SCROLLTOUCH][RERANK_FALLBACK] reason=winner_not_semantic selected='{}'".format(
                _clip(str(winner[2].get("selected_container_view_id", "") or winner[1].get("className", "") or ""), 80)
            )
        )
    if len(candidates) >= 2:
        second_meta = candidates[1][2]
        winner[2]["second_tap_point"] = str(second_meta.get("tap_point", "") or "")
        winner[2]["second_tap_strategy"] = str(second_meta.get("tap_strategy", "center") or "center")
        winner[2]["second_resource_id"] = str(second_meta.get("selected_container_view_id", "") or "")
        winner[2]["second_label"] = _node_label_blob(candidates[1][1])
        winner[2]["second_promotion_source"] = str(second_meta.get("promotion_source", "none") or "none")
    return winner[1], f"candidate_count={len(candidates)}", stats, winner[2]


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
        setattr(client, "last_pre_nav_failure_reason", "")
        return True
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    scrolltouch_debug_capture_enabled, scrolltouch_debug_verbose_log_enabled = _resolve_scrolltouch_debug_flags(tab_cfg)
    setattr(client, "last_pre_nav_failure_reason", "")
    setattr(client, "last_post_click_transition_same_screen", True)
    setattr(client, "last_post_click_transition_signal", "")
    capture_run_id = ""
    if scrolltouch_debug_capture_enabled and scenario_id.strip().lower() == _LIFE_AIR_CARE_SCENARIO_ID:
        capture_run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

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
        if action in {"xmlscrollsearchtap", "xml_scroll_search_tap", "dump_scroll_search_tap"}:
            action = "xml_scroll_search_tap"
        target = str(step.get("target", "") or "").strip()
        type_ = str(step.get("type", "a") or "a").strip()
        if not action or not target:
            log(f"[SCENARIO][pre_nav] failed reason='invalid_step_config' step={index}")
            return False
        if action not in {
            "select",
            "touch",
            "scrolltouch",
            "xml_scroll_search_tap",
            "touch_bounds_center",
            "select_and_click_focused",
            "tap_bounds_center_adb",
            "select_and_tap_bounds_center_adb",
            "select_and_click_focused_or_tap_bounds_center_adb",
        }:
            log(f"[SCENARIO][pre_nav] failed reason='unsupported_action' step={index} action='{action}'")
            return False

        step_retry_count = retry_count
        if action in {"scrolltouch", "xml_scroll_search_tap"}:
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
        local_match_failed = False
        for attempt in range(1, step_retry_count + 1):
            if action == "select":
                step_ok = bool(client.select(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
            elif action == "touch":
                step_ok = bool(client.touch(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
            elif action == "xml_scroll_search_tap":
                max_scroll_search_steps = max(
                    1,
                    int(step.get("max_scroll_search_steps", tab_cfg.get("max_scroll_search_steps", _PLUGIN_SCROLL_SEARCH_MAX_STEPS)) or _PLUGIN_SCROLL_SEARCH_MAX_STEPS),
                )
                if attempt == 1:
                    log("[XMLENTRY][search] pre_reset scroll_to_top=true")
                    scroll_to_top_fn = getattr(client, "scroll_to_top", None)
                    if callable(scroll_to_top_fn):
                        try:
                            scroll_to_top_fn(dev=dev, max_swipes=5, pause=0.6)
                        except Exception as exc:
                            log(f"[XMLENTRY][search] pre_reset_failed reason='{exc}'")
                step_ok, xml_reason = _run_xml_scroll_search_tap(
                    client,
                    dev,
                    tab_cfg=tab_cfg,
                    target=target,
                    type_=type_,
                    max_scroll_search_steps=max_scroll_search_steps,
                    step_wait_seconds=step_wait_seconds,
                    transition_fast_path=transition_fast_path,
                )
                if not step_ok:
                    fallback_reason = f"xml_entry_failed:{xml_reason}"
                    log(f"[SCENARIO][pre_nav][xmlentry] fallback='helper_scrollTouch' reason='{fallback_reason}'")
                    step_ok = bool(client.scrollTouch(dev=dev, name=target, type_=type_, wait_=action_wait_seconds))
                    if step_ok:
                        confirm_ok, confirm_signal = _confirm_click_focused_transition(
                            client=client,
                            dev=dev,
                            tab_cfg=tab_cfg,
                            transition_fast_path=transition_fast_path,
                        )
                        setattr(client, "last_post_click_transition_same_screen", not confirm_ok)
                        setattr(client, "last_post_click_transition_signal", str(confirm_signal or ""))
                        step_ok = bool(confirm_ok)
                local_match_failed = not step_ok
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
                post_scroll_settle_ms = 250
                xml_fallback_attempted = False
                xml_fallback_reason = "not_attempted"
                selected_candidate_observed = False
                entry_type = str(tab_cfg.get("entry_type", _ENTRY_TYPE_CARD) or _ENTRY_TYPE_CARD).strip().lower()
                card_entry_spec = _get_card_entry_spec(tab_cfg, target)
                for scroll_step in range(1, max_scroll_search_steps + 1):
                    selected_node, selected_reason, candidate_stats, selected_meta = _select_visible_plugin_candidate(
                        nodes=top_nodes,
                        target=target,
                        scenario_id=scenario_id,
                        entry_spec=card_entry_spec,
                    )
                    rejection_counts = candidate_stats.get("rejection_counts", {})
                    needs_xml_fallback = bool(
                        selected_node is None
                        and entry_type == _ENTRY_TYPE_CARD
                        and (
                            bool(candidate_stats.get("will_try_xml_live_fallback", False))
                            or
                            int(candidate_stats.get("visible_candidate_count", 0) or 0) == 0
                            or (
                                int(candidate_stats.get("partial_match_count", 0) or 0) > 0
                                and int((rejection_counts or {}).get("non_actionable_without_promotion", 0) or 0) > 0
                            )
                        )
                        and (
                            not xml_fallback_attempted
                            or bool(candidate_stats.get("will_try_xml_live_fallback", False))
                        )
                    )
                    if needs_xml_fallback and scrolltouch_debug_capture_enabled:
                        xml_fallback_attempted = True
                        xml_nodes, xml_fallback_reason = _load_scrolltouch_xml_nodes(client=client, dev=dev)
                        if xml_nodes:
                            selected_node, selected_reason, candidate_stats, selected_meta = _select_visible_plugin_candidate(
                                nodes=top_nodes,
                                target=target,
                                scenario_id=scenario_id,
                                xml_nodes=xml_nodes,
                                entry_spec=card_entry_spec,
                            )
                            rejection_counts = candidate_stats.get("rejection_counts", {})
                    visible_samples = candidate_stats.get("visible_samples", [])
                    partial_samples = candidate_stats.get("partial_samples", [])
                    inspect_samples = candidate_stats.get("inspect_samples", [])
                    pre_candidate_fail_samples = candidate_stats.get("pre_candidate_fail_samples", [])
                    visible_preview = " | ".join(visible_samples[:3]) if isinstance(visible_samples, list) and visible_samples else "-"
                    partial_preview = " | ".join(partial_samples[:3]) if isinstance(partial_samples, list) and partial_samples else "-"
                    relaxed_samples = candidate_stats.get("relaxed_semantic_samples", [])
                    relaxed_preview = " | ".join(relaxed_samples[:3]) if isinstance(relaxed_samples, list) and relaxed_samples else "-"
                    probe_samples = candidate_stats.get("probe_samples", [])
                    probe_preview = " | ".join(probe_samples[:3]) if isinstance(probe_samples, list) and probe_samples else "-"
                    probe_reject_samples = candidate_stats.get("probe_reject_samples", [])
                    probe_reject_preview = (
                        " | ".join(probe_reject_samples[:3]) if isinstance(probe_reject_samples, list) and probe_reject_samples else "-"
                    )
                    rejection_summary = "-"
                    if isinstance(rejection_counts, dict) and rejection_counts:
                        sorted_rejections = sorted(rejection_counts.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))
                        rejection_summary = ", ".join(f"{name}:{count}" for name, count in sorted_rejections[:6])
                    inspect_preview = (
                        " | ".join(inspect_samples[:5]) if isinstance(inspect_samples, list) and inspect_samples else "-"
                    )
                    pre_candidate_preview = (
                        " | ".join(pre_candidate_fail_samples[:3])
                        if isinstance(pre_candidate_fail_samples, list) and pre_candidate_fail_samples
                        else "-"
                    )
                    if scrolltouch_debug_verbose_log_enabled:
                        log(
                            f"[SCENARIO][pre_nav][scrolltouch][debug] scroll_step={scroll_step}/{max_scroll_search_steps} "
                            f"visible_candidate_count={candidate_stats.get('visible_candidate_count', 0)} "
                            f"partial_match_count={candidate_stats.get('partial_match_count', 0)} "
                            f"exact_match_count={candidate_stats.get('exact_match_count', 0)} "
                            f"relaxed_semantic_match_count={candidate_stats.get('relaxed_semantic_match_count', 0)} "
                            f"fallback_applied_count={candidate_stats.get('fallback_applied_count', 0)} "
                            f"generic_guard_block_count={candidate_stats.get('generic_guard_block_count', 0)} "
                            f"hard_filter_reject_count={candidate_stats.get('hard_filter_reject_count', 0)} "
                            f"semantic_probe_pool_count={candidate_stats.get('semantic_probe_pool_count', 0)} "
                            f"semantic_probe_match_count={candidate_stats.get('semantic_probe_match_count', 0)} "
                            f"semantic_probe_reject_count={candidate_stats.get('semantic_probe_reject_count', 0)} "
                            f"candidate_from_probe_count={candidate_stats.get('candidate_from_probe_count', 0)} "
                            f"probe_guard_block_count={candidate_stats.get('probe_guard_block_count', 0)} "
                            f"alias_hit_count={candidate_stats.get('alias_hit_count', 0)} "
                            f"alias_hit_top='{str(candidate_stats.get('alias_hit_top', '') or '')[:120]}' "
                            f"resource_token_hit_count={candidate_stats.get('resource_token_hit_count', 0)} "
                            f"resource_token_hit_top='{str(candidate_stats.get('resource_token_hit_top', '') or '')[:120]}' "
                            f"descendant_alias_hit_count={candidate_stats.get('descendant_alias_hit_count', 0)} "
                            f"semantic_evidence_class='{candidate_stats.get('semantic_evidence_class', 'miss')}' "
                            f"probe_accept_reason='{candidate_stats.get('probe_accept_reason', 'none')}' "
                            f"probe_reject_reason='{candidate_stats.get('probe_reject_reason', 'none')}' "
                            f"helper_text_hit_count={candidate_stats.get('helper_text_hit_count', 0)} "
                            f"xml_live_text_hit_count={candidate_stats.get('xml_live_text_hit_count', 0)} "
                            f"descendant_text_hit_count={candidate_stats.get('descendant_text_hit_count', 0)} "
                            f"xml_fallback_attempted={str(xml_fallback_attempted).lower()} "
                            f"xml_fallback_reason='{xml_fallback_reason}' "
                            f"rejections='{rejection_summary[:360]}' "
                            f"visible_top='{visible_preview[:360]}' partial_top='{partial_preview[:360]}' relaxed_top='{relaxed_preview[:360]}' "
                            f"probe_top='{probe_preview[:360]}' probe_reject_top='{probe_reject_preview[:360]}' "
                            f"pre_candidate_top='{pre_candidate_preview[:360]}' "
                            f"local_search_nodes={len(top_nodes) if isinstance(top_nodes, list) else 0} "
                            f"selected={str(selected_node is not None).lower()} selected_reason='{selected_reason}'"
                        )
                        log(
                            f"[SCENARIO][pre_nav][scrolltouch][inspect] scroll_step={scroll_step}/{max_scroll_search_steps} "
                            f"samples='{inspect_preview[:1200]}'"
                        )
                    if scrolltouch_debug_capture_enabled:
                        _capture_scrolltouch_step_bundle(
                            client,
                            dev,
                            scenario_id=scenario_id,
                            capture_run_id=capture_run_id,
                            step_index=index,
                            scroll_step=scroll_step,
                            target_regex=target,
                            selected=selected_node is not None,
                            selected_reason=selected_reason,
                            candidate_stats=candidate_stats,
                            selected_meta=selected_meta,
                            log_fn=log,
                        )
                    if selected_node is not None:
                        selected_candidate_observed = True
                        class_name = str(selected_node.get("className", "") or "").strip()
                        resource_id = str(selected_node.get("viewIdResourceName", "") or selected_node.get("resourceId", "") or "").strip()
                        bounds = str(selected_node.get("boundsInScreen", "") or "").strip()
                        visible = _node_is_visible(selected_node)
                        label_blob = _node_label_blob(selected_node)
                        log(
                            f"[SCENARIO][pre_nav][scrolltouch] candidate_select reason='{selected_reason}' class='{class_name}' "
                            f"resource='{resource_id}' bounds='{bounds}' visible={str(visible).lower()} label='{label_blob[:120]}' "
                            f"promoted_container={str(bool(selected_meta.get('promoted_container', False))).lower()} "
                            f"promotion_attempted={str(bool(selected_meta.get('promotion_attempted', False))).lower()} "
                            f"promotion_source='{str(selected_meta.get('promotion_source', 'none'))}' "
                            f"matched_text_node='{str(selected_meta.get('matched_text_node', ''))[:80]}' "
                            f"promotion_reason='{str(selected_meta.get('promotion_reason', 'none'))}' "
                            f"promotion_candidate_count={int(selected_meta.get('promotion_candidate_count', 0) or 0)} "
                            f"promotion_debug_summary='{str(selected_meta.get('promotion_debug_summary', ''))[:120]}' "
                            f"promoted_from='{str(selected_meta.get('promoted_from', ''))[:80]}' "
                            f"promoted_to='{str(selected_meta.get('promoted_to', ''))[:80]}' "
                            f"selected_area={int(selected_meta.get('selected_area', 0) or 0)} "
                            f"text_area={int(selected_meta.get('matched_text_area', 0) or 0)} "
                            f"area_ratio={float(selected_meta.get('selected_to_text_area_ratio', 0.0) or 0.0):.3f} "
                            f"ancestor_distance={int(selected_meta.get('ancestor_distance', -1) or -1)} "
                            f"tap_point='{str(selected_meta.get('tap_point', ''))[:24]}' "
                            f"tap_strategy='{str(selected_meta.get('tap_strategy', 'center'))[:24]}' "
                            f"rank_summary_top3='{str(selected_meta.get('rank_summary_top3', ''))[:220]}' "
                            f"scroll_step={scroll_step}/{max_scroll_search_steps} cumulative_mode={str(use_cumulative_search).lower()}"
                        )
                        tap_target = resource_id if resource_id else label_blob
                        tap_type = "r" if resource_id else "a"
                        tap_strategy = str(selected_meta.get("tap_strategy", "center") or "center").strip().lower()
                        tap_point_raw = str(selected_meta.get("tap_point", "") or "").strip()
                        tap_point: tuple[int, int] | None = None
                        if tap_point_raw:
                            parts = [part.strip() for part in tap_point_raw.split(",")]
                            if len(parts) == 2 and all(part.lstrip("-").isdigit() for part in parts):
                                tap_point = (int(parts[0]), int(parts[1]))
                        step_ok = False
                        click_dispatch_success = False
                        if (
                            str(selected_meta.get("promotion_source", "none")) == "xml_live"
                            and tap_strategy in {"text_center", "refined_body_point"}
                            and tap_point
                            and hasattr(client, "tap_xy_adb")
                        ):
                            click_dispatch_success = bool(client.tap_xy_adb(dev=dev, x=int(tap_point[0]), y=int(tap_point[1])))
                        else:
                            click_dispatch_success = bool(
                                client.tap_bounds_center_adb(dev=dev, name=tap_target, type_=tap_type, dump_nodes=top_nodes)
                            )
                        log(
                            f"[DEBUG] candidate_click_dispatch_result success={str(click_dispatch_success).lower()}"
                        )
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
                        setattr(client, "last_post_click_transition_same_screen", not confirm_ok)
                        setattr(client, "last_post_click_transition_signal", str(confirm_signal or ""))
                        step_ok = confirm_ok
                        if step_ok:
                            log("[INFO] candidate_click_result=success")
                        elif not click_dispatch_success:
                            fallback_reason = "dispatch_failed"
                            log("[WARN] candidate_click_failed:dispatch_failed")
                        else:
                            fallback_reason = f"post_click_transition_failed:{confirm_signal}"
                            second_resource_id = str(selected_meta.get("second_resource_id", "") or "").strip()
                            second_label = str(selected_meta.get("second_label", "") or "").strip()
                            second_tap_strategy = str(selected_meta.get("second_tap_strategy", "center") or "center").strip().lower()
                            second_tap_point_raw = str(selected_meta.get("second_tap_point", "") or "").strip()
                            second_tap_point: tuple[int, int] | None = None
                            if second_tap_point_raw:
                                second_parts = [part.strip() for part in second_tap_point_raw.split(",")]
                                if len(second_parts) == 2 and all(part.lstrip("-").isdigit() for part in second_parts):
                                    second_tap_point = (int(second_parts[0]), int(second_parts[1]))
                            if second_resource_id or second_label:
                                log(
                                    "[SCROLLTOUCH][CLICK_RETRY] attempt=2 candidate='{}'".format(
                                        _clip(second_resource_id or second_label, 80)
                                    )
                                )
                                second_click_dispatch_success = False
                                if (
                                    str(selected_meta.get("second_promotion_source", "none")) == "xml_live"
                                    and second_tap_strategy in {"text_center", "refined_body_point"}
                                    and second_tap_point
                                    and hasattr(client, "tap_xy_adb")
                                ):
                                    second_click_dispatch_success = bool(
                                        client.tap_xy_adb(dev=dev, x=int(second_tap_point[0]), y=int(second_tap_point[1]))
                                    )
                                else:
                                    second_tap_target = second_resource_id if second_resource_id else second_label
                                    second_tap_type = "r" if second_resource_id else "a"
                                    second_click_dispatch_success = bool(
                                        client.tap_bounds_center_adb(dev=dev, name=second_tap_target, type_=second_tap_type, dump_nodes=top_nodes)
                                    )
                                if second_click_dispatch_success:
                                    second_confirm_ok, second_confirm_signal = _confirm_click_focused_transition(
                                        client=client,
                                        dev=dev,
                                        tab_cfg=tab_cfg,
                                        transition_fast_path=transition_fast_path,
                                    )
                                    log(
                                        f"[SCENARIO][pre_nav][scrolltouch] post_click_transition same_screen={str(not second_confirm_ok).lower()} "
                                        f"signal='{second_confirm_signal}'"
                                    )
                                    setattr(client, "last_post_click_transition_same_screen", not second_confirm_ok)
                                    setattr(client, "last_post_click_transition_signal", str(second_confirm_signal or ""))
                                    step_ok = bool(second_confirm_ok)
                                    if step_ok:
                                        fallback_reason = "none"
                                    else:
                                        fallback_reason = f"post_click_transition_failed:{second_confirm_signal}"
                                else:
                                    fallback_reason = "dispatch_failed_retry2"
                        break

                    if scroll_step >= max_scroll_search_steps:
                        fallback_reason = "max_scroll_search_steps_reached"
                        if not isinstance(top_nodes, list) or not top_nodes:
                            fallback_reason = "local_search_empty_after_scroll"
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
                        f"scroll_performed={str(scrolled).lower()} settle_wait_ms={post_scroll_settle_ms} "
                        f"cumulative_mode={str(use_cumulative_search).lower()}"
                    )
                    if not scrolled:
                        fallback_reason = "scroll_forward_failed"
                        break
                    settle_wait_seconds = max(min(step_wait_seconds, 0.45), post_scroll_settle_ms / 1000.0)
                    time.sleep(settle_wait_seconds)
                    try:
                        top_nodes = dump_tree_fn(dev=dev) if callable(dump_tree_fn) else []
                    except Exception:
                        top_nodes = []
                    if not top_nodes:
                        fallback_reason = "local_search_empty_after_scroll"
                    current_signature = _make_visible_plugin_search_signature(top_nodes)
                    if current_signature and last_signature and current_signature == last_signature:
                        fallback_reason = "semantic_no_change_after_scroll"
                        break
                    last_signature = current_signature

                if not step_ok:
                    local_match_failed = True
                    candidate_committed = bool(candidate_stats.get("candidate_committed", False))
                    if selected_candidate_observed or candidate_committed:
                        log(
                            f"[SCROLLTOUCH][promotion][final_state] visible_candidate_count={int(candidate_stats.get('visible_candidate_count', 0) or 0)} "
                            f"partial_match_count={int(candidate_stats.get('partial_match_count', 0) or 0)} "
                            f"matched_text_found={str(bool(candidate_stats.get('matched_text_found', False))).lower()} "
                            f"promotion_attempted={str(bool(candidate_stats.get('promotion_attempted', False))).lower()} "
                            f"xml_node_found={str(bool(candidate_stats.get('xml_node_found', False))).lower()} "
                            f"xml_match_strategy='{str(candidate_stats.get('xml_match_strategy', 'none'))[:32]}' "
                            f"ancestor_chain_depth={int(candidate_stats.get('ancestor_chain_depth', 0) or 0)} "
                            f"actionable_ancestor_found={str(bool(candidate_stats.get('actionable_ancestor_found', False))).lower()} "
                            f"candidate_committed={str(candidate_committed).lower()} "
                            f"final_reason='candidate_click_failed:{fallback_reason}'"
                        )
                        log(
                            f"[SCENARIO][pre_nav][scrolltouch] candidate_select reason='candidate_click_failed' "
                            f"fallback='helper_scrollTouch' reason_detail='{fallback_reason}' "
                            f"cumulative_mode={str(use_cumulative_search).lower()}"
                        )
                    else:
                        log(
                            f"[SCROLLTOUCH][promotion][final_state] visible_candidate_count={int(candidate_stats.get('visible_candidate_count', 0) or 0)} "
                            f"partial_match_count={int(candidate_stats.get('partial_match_count', 0) or 0)} "
                            f"matched_text_found={str(bool(candidate_stats.get('matched_text_found', False))).lower()} "
                            f"promotion_attempted={str(bool(candidate_stats.get('promotion_attempted', False))).lower()} "
                            f"xml_node_found={str(bool(candidate_stats.get('xml_node_found', False))).lower()} "
                            f"xml_match_strategy='{str(candidate_stats.get('xml_match_strategy', 'none'))[:32]}' "
                            f"ancestor_chain_depth={int(candidate_stats.get('ancestor_chain_depth', 0) or 0)} "
                            f"actionable_ancestor_found={str(bool(candidate_stats.get('actionable_ancestor_found', False))).lower()} "
                            f"candidate_committed={str(candidate_committed).lower()} "
                            f"final_reason='no_local_match:{fallback_reason}'"
                        )
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
                        setattr(client, "last_post_click_transition_same_screen", not confirm_ok)
                        setattr(client, "last_post_click_transition_signal", str(confirm_signal or ""))
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
                        setattr(client, "last_post_click_transition_same_screen", not confirm_ok)
                        setattr(client, "last_post_click_transition_signal", str(confirm_signal or ""))
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
            failure_reason_for_capture = "action_failed"
            normalized_actual_reason = str(actual_reason or "").strip().lower()
            if local_match_failed:
                failure_reason_for_capture = "no_local_match"
            elif normalized_actual_reason == "target node not found":
                failure_reason_for_capture = "Target node not found"
            setattr(client, "last_pre_nav_failure_reason", str(failure_reason_for_capture or actual_reason or "action_failed"))
            if scrolltouch_debug_capture_enabled:
                _capture_pre_navigation_failure_bundle(
                    client,
                    dev,
                    scenario_id=scenario_id,
                    failure_phase="pre_navigation",
                    failure_reason=failure_reason_for_capture,
                    step_index=index,
                    target_regex=target,
                    capture_run_id=capture_run_id,
                    log_fn=log,
                )
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
    setattr(client, "last_pre_nav_failure_reason", "")
    return True


def open_scenario(client: A11yAdbClient, dev: str, tab_cfg: dict) -> bool:
    tab_retry_count = _get_retry_count(tab_cfg, "tab_select_retry_count", 2)
    anchor_retry_count = _get_retry_count(tab_cfg, "anchor_retry_count", 2)
    main_step_wait_seconds = _get_wait_seconds(tab_cfg, "main_step_wait_seconds", MAIN_STEP_WAIT_SECONDS)
    screen_context_mode = _resolve_screen_context_mode(tab_cfg)
    stabilization_mode = _resolve_stabilization_mode(tab_cfg, screen_context_mode)
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    entry_type = str(tab_cfg.get("entry_type", _ENTRY_TYPE_CARD) or _ENTRY_TYPE_CARD).strip().lower()
    if entry_type not in {_ENTRY_TYPE_CARD, _ENTRY_TYPE_DIRECT_SELECT}:
        entry_type = _ENTRY_TYPE_CARD
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
    scrolltouch_debug_capture_enabled, _ = _resolve_scrolltouch_debug_flags(tab_cfg)
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
            "entry_type": entry_type,
            "entry_contract_reason": _ENTRY_REASON_VERIFY_FAILED,
            "entry_contract_detail": "",
            "post_click_transition_same_screen": True,
            "post_click_transition_signal": "",
            "collection_flow_life_recovery_version": COLLECTION_FLOW_LIFE_RECOVERY_VERSION,
            "collection_flow_life_reset_version": COLLECTION_FLOW_LIFE_RESET_VERSION,
        },
    )

    is_life_plugin_scenario = _is_life_plugin_scenario(scenario_id)
    if is_life_plugin_scenario:
        life_list_ok, life_list_reason = _verify_fresh_life_list_state(client, dev, phase="plugin_start_initial")
        recover_triggered = not life_list_ok
        if recover_triggered:
            log("[PLUGIN_START][recover_before_entry] triggered=true mode='life_reset'")
            recover_success = False
            life_list_reason = "recover_failed"
            for recover_attempt in range(1, 3):
                previous_recover_invocation_reason = tab_cfg.get("_recover_invocation_reason", None)
                tab_cfg["_recover_invocation_reason"] = "plugin_start"
                try:
                    recover_success = recover_to_start_state(client, dev, tab_cfg)
                finally:
                    if previous_recover_invocation_reason is None:
                        tab_cfg.pop("_recover_invocation_reason", None)
                    else:
                        tab_cfg["_recover_invocation_reason"] = previous_recover_invocation_reason
                if recover_success:
                    life_list_reason = "life_reset_ready"
                    break
                if recover_attempt < 2:
                    log(
                        f"[PLUGIN_START][recover_before_entry] retry={recover_attempt}/2 "
                        "reason='recover_to_start_state_failed'"
                    )
        else:
            log("[PLUGIN_START][recover_before_entry] triggered=false")
            recover_success = True
        log(f"[PLUGIN_START][life_list_check] ok={str(recover_success).lower()} reason='{life_list_reason}'")
        log(f"[PLUGIN_START][recover_before_entry] success={str(bool(recover_success)).lower()}")
        if not recover_success:
            start_open_summary = getattr(client, "last_start_open_summary", {})
            if isinstance(start_open_summary, dict):
                start_open_summary["entry_contract_reason"] = _ENTRY_REASON_VERIFY_FAILED
                start_open_summary["entry_contract_detail"] = (
                    f"life_list_not_ready:{life_list_reason or 'recover_failed'}"
                )
                setattr(client, "last_start_open_summary", start_open_summary)
            return False

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
                if scrolltouch_debug_capture_enabled:
                    _capture_pre_navigation_failure_bundle(
                        client,
                        dev,
                        scenario_id=scenario_id,
                        failure_phase="focus_align_recheck",
                        failure_reason=plugin_root_reason,
                        step_index=1,
                        target_regex="",
                        log_fn=log,
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
            if scrolltouch_debug_capture_enabled:
                _capture_pre_navigation_failure_bundle(
                    client,
                    dev,
                    scenario_id=scenario_id,
                    failure_phase="before_pre_navigation",
                    failure_reason=plugin_root_reason,
                    step_index=0,
                    target_regex="",
                    log_fn=log,
                )
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
        start_open_summary = getattr(client, "last_start_open_summary", {})
        if isinstance(start_open_summary, dict):
            pre_nav_reason = _map_pre_nav_failure_reason_to_entry_reason(str(getattr(client, "last_pre_nav_failure_reason", "") or ""))
            start_open_summary["entry_contract_reason"] = pre_nav_reason
            start_open_summary["entry_contract_detail"] = str(getattr(client, "last_pre_nav_failure_reason", "") or "pre_navigation_failed")
            setattr(client, "last_start_open_summary", start_open_summary)
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
    anchor_fallback_source = _resolve_anchor_fallback_source(stabilize_result if isinstance(stabilize_result, dict) else {})
    air_anchor_fallback_accepted = bool(anchor_fallback_source in {"top_level_fallback", "focus_fallback"})
    if str(scenario_id or "").strip().lower() == _LIFE_AIR_CARE_SCENARIO_ID:
        fallback_candidate_view_id = str(stabilize_result.get("fallback_candidate_resource_id", "") or "").strip()
        fallback_candidate_label = str(stabilize_result.get("fallback_candidate_label", "") or "").strip()
        fallback_candidate_bounds = str(stabilize_result.get("fallback_candidate_bounds", "") or "").strip()
        accepted_reason = "trusted_fallback_source" if air_anchor_fallback_accepted else ""
        rejected_reason = "" if air_anchor_fallback_accepted else "fallback_source_not_allowed"
        log(
            "[ENTRY][air][fallback_acceptance] "
            f"fallback_source='{anchor_fallback_source or 'none'}' "
            f"fallback_candidate_view_id='{fallback_candidate_view_id or 'none'}' "
            f"fallback_candidate_label='{fallback_candidate_label or 'none'}' "
            f"fallback_candidate_bounds='{fallback_candidate_bounds or 'none'}' "
            f"accepted={str(air_anchor_fallback_accepted).lower()} "
            f"accepted_reason='{accepted_reason or 'none'}' "
            f"rejected_reason='{rejected_reason or 'none'}'"
        )
    setattr(client, "last_anchor_stabilize_result", stabilize_result if isinstance(stabilize_result, dict) else {})
    log(
        f"[TRACE][open_scenario] scenario='{scenario_id}' stabilization_mode='{stabilization_mode}' "
        f"focus_align_attempted={focus_align_attempted} focus_align_ok={focus_align_ok} "
        f"focus_align_reason='{focus_align_result.get('reason', '')}' context_ok={trace_context_ok} "
        f"anchor_matched={trace_anchor_matched} anchor_stable={trace_anchor_stable}",
    )
    start_open_summary = getattr(client, "last_start_open_summary", {})
    if isinstance(start_open_summary, dict):
        start_open_summary["anchor_fallback_source"] = anchor_fallback_source
        start_open_summary["air_anchor_fallback_accepted"] = air_anchor_fallback_accepted
        setattr(client, "last_start_open_summary", start_open_summary)
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
            start_open_summary = getattr(client, "last_start_open_summary", {})
            if isinstance(start_open_summary, dict):
                start_open_summary["entry_contract_reason"] = _ENTRY_REASON_VERIFY_FAILED
                start_open_summary["entry_contract_detail"] = str(low_conf_reason or "anchor_not_stable")
                setattr(client, "last_start_open_summary", start_open_summary)
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
            start_open_summary = getattr(client, "last_start_open_summary", {})
            if isinstance(start_open_summary, dict):
                start_open_summary["entry_contract_reason"] = _ENTRY_REASON_VERIFY_FAILED
                start_open_summary["entry_contract_detail"] = "life_energy_guard:entry_not_confirmed"
                setattr(client, "last_start_open_summary", start_open_summary)
            return False
    post_focus = client.get_focus(
        dev=dev,
        wait_seconds=min(main_step_wait_seconds, 0.8),
        allow_fallback_dump=False,
        mode="fast",
    )
    post_view_id, post_label, post_speech = _extract_post_open_focus_fields(post_focus)
    has_negative_signal = _is_negative_post_open_focus_signal(post_view_id, post_label, post_speech)
    has_negative_verify_token = _has_post_open_negative_verify_token(tab_cfg, post_view_id, post_label, post_speech)
    fallback_used = bool(stabilize_result.get("fallback_candidate_used"))
    post_click_transition_same_screen = bool(getattr(client, "last_post_click_transition_same_screen", True))
    post_click_transition_signal = str(getattr(client, "last_post_click_transition_signal", "") or "").strip()
    start_open_summary = getattr(client, "last_start_open_summary", {})
    pre_navigation_success = bool(start_open_summary.get("pre_navigation_success")) if isinstance(start_open_summary, dict) else False
    anchor_fallback_source = str(start_open_summary.get("anchor_fallback_source", "") or "").strip() if isinstance(start_open_summary, dict) else ""
    air_anchor_fallback_accepted = bool(start_open_summary.get("air_anchor_fallback_accepted")) if isinstance(start_open_summary, dict) else False
    dump_tree_fn = getattr(client, "dump_tree", None)
    identity_nodes: list[dict[str, Any]] = []
    if callable(dump_tree_fn):
        try:
            identity_nodes = dump_tree_fn(dev=dev)
        except Exception:
            identity_nodes = []
    identity_mismatch, identity_actual = _detect_life_plugin_identity_mismatch(
        scenario_id=scenario_id,
        post_view_id=post_view_id,
        post_label=post_label,
        post_speech=post_speech,
        nodes=identity_nodes,
    )
    air_post_nodes: list[dict[str, Any]] = []
    if str(scenario_id or "").strip().lower() == _LIFE_AIR_CARE_SCENARIO_ID and callable(dump_tree_fn):
        try:
            air_post_nodes = dump_tree_fn(dev=dev)
        except Exception:
            air_post_nodes = []
    air_list_screen_evidence = _collect_air_list_screen_evidence(
        air_post_nodes,
        extra_blobs=[post_view_id, post_label, post_speech],
    ) if str(scenario_id or "").strip().lower() == _LIFE_AIR_CARE_SCENARIO_ID else {}
    air_verified_entry_context, air_verified_entry_reason = _is_air_verified_entry_context(
        scenario_id=scenario_id,
        pre_navigation_success=pre_navigation_success,
        post_click_transition_signal=post_click_transition_signal,
        post_click_transition_same_screen=post_click_transition_same_screen,
        post_view_id=post_view_id,
        post_label=post_label,
        post_speech=post_speech,
        stabilize_result=stabilize_result if isinstance(stabilize_result, dict) else {},
        anchor_fallback_source=anchor_fallback_source,
        air_anchor_fallback_accepted=air_anchor_fallback_accepted,
        air_list_screen_evidence=air_list_screen_evidence if isinstance(air_list_screen_evidence, dict) else None,
    )
    transition_verify_hint = post_click_transition_signal.replace("_", " ").strip().lower()
    visible_verify_text = ""
    extra_verify_candidates: list[str] = []
    matches_verify = _matches_post_open_verify(tab_cfg, post_view_id, post_label, post_speech)
    negative_verify_hits = 1 if has_negative_verify_token else 0
    diagnostic_entry = (
        entry_type == _ENTRY_TYPE_DIRECT_SELECT
        and str(scenario_id or "").strip().lower() in _DIRECT_SELECT_DIAGNOSTIC_SCENARIOS
    )
    normalized_verify_tokens = [
        str(token or "").strip().lower() for token in tab_cfg.get("verify_tokens", []) if str(token or "").strip()
    ]
    normalized_negative_tokens = [
        str(token or "").strip().lower() for token in tab_cfg.get("negative_verify_tokens", []) if str(token or "").strip()
    ]
    if entry_type == _ENTRY_TYPE_DIRECT_SELECT and not matches_verify:
        visible_verify_text = _collect_post_open_visible_text(client, dev)
        extra_verify_candidates = _build_direct_select_verify_candidates(
            stabilize_result=stabilize_result,
            visible_verify_text=visible_verify_text,
            transition_verify_hint=transition_verify_hint,
            post_click_transition_same_screen=post_click_transition_same_screen,
        )
        matches_verify = _matches_post_open_verify(
            tab_cfg,
            post_view_id,
            post_label,
            post_speech,
            extra_candidates=extra_verify_candidates if extra_verify_candidates else None,
        )
        has_negative_verify_token = has_negative_verify_token or _has_post_open_negative_verify_token(
            tab_cfg,
            post_view_id,
            post_label,
            post_speech,
            extra_candidates=extra_verify_candidates if extra_verify_candidates else None,
        )
        if diagnostic_entry:
            initial_verify_hits = _collect_token_hits(
                normalized_verify_tokens,
                [post_view_id, post_label, post_speech, visible_verify_text, *extra_verify_candidates],
            )
            initial_negative_hits = _collect_token_hits(
                normalized_negative_tokens,
                [post_view_id, post_label, post_speech, visible_verify_text, *extra_verify_candidates],
            )
            log(
                "[SCENARIO][direct_select][snapshot] "
                f"scenario='{scenario_id}' focus_view_id='{post_view_id}' "
                f"focus_label='{post_label}' speech='{post_speech}' "
                f"visible='{visible_verify_text}' "
                f"fallback_label='{str(stabilize_result.get('fallback_candidate_label', '') or '').strip() or 'none'}' "
                f"post_open_anchor='{str(stabilize_result.get('fallback_candidate_resource_id', '') or '').strip() or 'none'}' "
                f"verify_hits='{','.join(initial_verify_hits) or 'none'}' "
                f"negative_hits='{','.join(initial_negative_hits) or 'none'}' "
                f"matches_verify={str(matches_verify).lower()} "
                f"has_negative_verify_token={str(has_negative_verify_token).lower()}"
            )
        if not matches_verify:
            for recheck_idx in range(_DIRECT_SELECT_VERIFY_RECHECK_COUNT):
                time.sleep(min(main_step_wait_seconds, _DIRECT_SELECT_VERIFY_RECHECK_SLEEP_SECONDS))
                recheck_focus = client.get_focus(
                    dev=dev,
                    wait_seconds=min(main_step_wait_seconds, 0.8),
                    allow_fallback_dump=False,
                    mode="fast",
                )
                recheck_view_id, recheck_label, recheck_speech = _extract_post_open_focus_fields(recheck_focus)
                visible_verify_text = _collect_post_open_visible_text(client, dev)
                extra_verify_candidates = _build_direct_select_verify_candidates(
                    stabilize_result=stabilize_result,
                    visible_verify_text=visible_verify_text,
                    transition_verify_hint=transition_verify_hint,
                    post_click_transition_same_screen=post_click_transition_same_screen,
                )
                has_negative_signal = has_negative_signal or _is_negative_post_open_focus_signal(
                    recheck_view_id,
                    recheck_label,
                    recheck_speech,
                )
                current_negative_verify = _has_post_open_negative_verify_token(
                    tab_cfg,
                    recheck_view_id,
                    recheck_label,
                    recheck_speech,
                    extra_candidates=extra_verify_candidates if extra_verify_candidates else None,
                )
                has_negative_verify_token = has_negative_verify_token or current_negative_verify
                if current_negative_verify:
                    negative_verify_hits += 1
                matches_verify = _matches_post_open_verify(
                    tab_cfg,
                    recheck_view_id,
                    recheck_label,
                    recheck_speech,
                    extra_candidates=extra_verify_candidates if extra_verify_candidates else None,
                )
                post_view_id, post_label, post_speech = recheck_view_id, recheck_label, recheck_speech
                if diagnostic_entry:
                    recheck_verify_hits = _collect_token_hits(
                        normalized_verify_tokens,
                        [recheck_view_id, recheck_label, recheck_speech, visible_verify_text, *extra_verify_candidates],
                    )
                    recheck_negative_hits = _collect_token_hits(
                        normalized_negative_tokens,
                        [recheck_view_id, recheck_label, recheck_speech, visible_verify_text, *extra_verify_candidates],
                    )
                    log(
                        "[SCENARIO][direct_select][recheck] "
                        f"scenario='{scenario_id}' attempt={recheck_idx + 1}/{_DIRECT_SELECT_VERIFY_RECHECK_COUNT} "
                        f"focus_view_id='{recheck_view_id}' focus_label='{recheck_label}' speech='{recheck_speech}' "
                        f"visible='{visible_verify_text}' "
                        f"verify_hits='{','.join(recheck_verify_hits) or 'none'}' "
                        f"negative_hits='{','.join(recheck_negative_hits) or 'none'}' "
                        f"matches_verify={str(matches_verify).lower()} "
                        f"current_negative_verify={str(current_negative_verify).lower()} "
                        f"negative_verify_hits={negative_verify_hits}"
                    )
                if matches_verify or has_negative_signal:
                    break
        has_negative_verify_token = (
            not matches_verify
            and negative_verify_hits >= _DIRECT_SELECT_NEGATIVE_VERIFY_PERSIST_THRESHOLD
        )
    if entry_type == _ENTRY_TYPE_CARD and not matches_verify:
        visible_verify_text = _collect_post_open_visible_text(client, dev)
        if visible_verify_text:
            matches_verify = _matches_post_open_verify(
                tab_cfg,
                post_view_id,
                post_label,
                post_speech,
                extra_candidates=[
                    visible_verify_text,
                    visible_verify_text.lower(),
                    transition_verify_hint if not post_click_transition_same_screen else "",
                ],
            )
        if not matches_verify:
            for recheck_idx in range(_CARD_ENTRY_VERIFY_RECHECK_COUNT):
                time.sleep(min(main_step_wait_seconds, _CARD_ENTRY_VERIFY_RECHECK_SLEEP_SECONDS))
                recheck_focus = client.get_focus(
                    dev=dev,
                    wait_seconds=min(main_step_wait_seconds, 0.8),
                    allow_fallback_dump=False,
                    mode="fast",
                )
                recheck_view_id = (
                    str(recheck_focus.get("viewIdResourceName", "") or recheck_focus.get("resourceId", "") or "").strip()
                    if isinstance(recheck_focus, dict)
                    else ""
                )
                recheck_label = _node_label_blob(recheck_focus if isinstance(recheck_focus, dict) else {})
                recheck_speech = str(
                    (recheck_focus.get("talkbackLabel", "") if isinstance(recheck_focus, dict) else "")
                    or (recheck_focus.get("mergedLabel", "") if isinstance(recheck_focus, dict) else "")
                    or (recheck_focus.get("contentDescription", "") if isinstance(recheck_focus, dict) else "")
                    or (recheck_focus.get("text", "") if isinstance(recheck_focus, dict) else "")
                    or ""
                ).strip()
                visible_verify_text = _collect_post_open_visible_text(client, dev)
                extra_candidates = [visible_verify_text, visible_verify_text.lower()] if visible_verify_text else []
                if not post_click_transition_same_screen and transition_verify_hint:
                    extra_candidates.append(transition_verify_hint)
                matches_verify = _matches_post_open_verify(
                    tab_cfg,
                    recheck_view_id,
                    recheck_label,
                    recheck_speech,
                    extra_candidates=extra_candidates if extra_candidates else None,
                )
                if matches_verify:
                    post_view_id = recheck_view_id
                    post_label = recheck_label
                    post_speech = recheck_speech
                    break
            if matches_verify:
                log(
                    f"[SCENARIO][entry_contract][card_verify_recheck] scenario='{scenario_id}' "
                    f"recovered=true post_click_transition_same_screen={str(post_click_transition_same_screen).lower()} "
                    f"signal='{post_click_transition_signal or 'none'}'"
                )
    is_air_scenario = str(scenario_id or "").strip().lower() == _LIFE_AIR_CARE_SCENARIO_ID
    air_requires_verify = (
        entry_type == _ENTRY_TYPE_CARD and isinstance(tab_cfg.get("verify_tokens"), list) and bool(tab_cfg.get("verify_tokens"))
    )
    post_click_success_seen = not post_click_transition_same_screen
    air_verify_success_seen = bool(air_verified_entry_context)
    air_verified_success_seen = bool(
        air_verify_success_seen
        or (
            post_click_success_seen
            and str(post_click_transition_signal or "").strip().lower() == "air_care_verify"
        )
        or matches_verify
    )
    air_verify_reject_seen = bool(
        str(air_verified_entry_reason or "").strip().lower() in {"list_screen_evidence", "list_screen_focus"}
    )
    if is_air_scenario:
        log(
            "[ENTRY][air][verdict_inputs] "
            f"scenario_id='{scenario_id}' "
            f"post_click_success_seen={str(post_click_success_seen).lower()} "
            f"air_verify_success_seen={str(air_verify_success_seen).lower()} "
            f"air_verify_reject_seen={str(air_verify_reject_seen).lower()} "
            f"anchor_fallback_accepted={str(air_anchor_fallback_accepted).lower()} "
            f"anchor_fallback_source='{anchor_fallback_source or 'none'}' "
            f"post_open_focus_view_id='{post_view_id or 'none'}' "
            f"post_open_focus_label='{post_label or 'none'}' "
            f"is_top_chrome_focus={str(has_negative_signal).lower()} "
            f"is_list_screen_focus={str(bool(air_list_screen_evidence.get('has_list_screen_evidence'))).lower()} "
            "final_allow_success=true final_fail_reason='none'"
        )
    if has_negative_signal and (entry_type == _ENTRY_TYPE_DIRECT_SELECT or fallback_used):
        if air_verified_entry_context and air_verified_entry_reason == "air_internal_content_signal":
            log("[ENTRY][air] false_success_guard bypassed")
        else:
            if (
                str(scenario_id or "").strip().lower() == _LIFE_AIR_CARE_SCENARIO_ID
                and air_verified_entry_reason == "list_screen_focus"
            ):
                log("[ENTRY][air] rejected plugin entry due to list_screen_focus")
            if is_air_scenario:
                log(
                    "[ENTRY][air][verdict_priority] "
                    "applied_rule='reject_list_screen_overrides_verify' "
                    "previous_state='candidate_success' new_state='verify_failed'"
                )
                log(
                    "[ENTRY][air][verdict_inputs] "
                    f"scenario_id='{scenario_id}' "
                    f"post_click_success_seen={str(not post_click_transition_same_screen).lower()} "
                    f"air_verify_success_seen={str(air_verify_success_seen).lower()} "
                    f"air_verify_reject_seen={str(air_verify_reject_seen).lower()} "
                    f"anchor_fallback_accepted={str(air_anchor_fallback_accepted).lower()} "
                    f"anchor_fallback_source='{anchor_fallback_source or 'none'}' "
                    f"post_open_focus_view_id='{post_view_id or 'none'}' "
                    f"post_open_focus_label='{post_label or 'none'}' "
                    f"is_top_chrome_focus={str(has_negative_signal).lower()} "
                    f"is_list_screen_focus={str(bool(air_list_screen_evidence.get('has_list_screen_evidence'))).lower()} "
                    f"final_allow_success=false final_fail_reason='{_ENTRY_REASON_FALSE_SUCCESS_GUARD}'"
                )
            log(
                f"[SCENARIO][entry_contract] failed scenario='{scenario_id}' entry_type='{entry_type}' "
                f"reason='{_ENTRY_REASON_FALSE_SUCCESS_GUARD}' view_id='{post_view_id}' label='{post_label}'"
            )
            start_open_summary = getattr(client, "last_start_open_summary", {})
            if isinstance(start_open_summary, dict):
                start_open_summary["entry_contract_reason"] = _ENTRY_REASON_FALSE_SUCCESS_GUARD
                start_open_summary["entry_contract_detail"] = "negative_post_open_focus"
                setattr(client, "last_start_open_summary", start_open_summary)
            return False
    if str(scenario_id or "").strip().lower() == _LIFE_AIR_CARE_SCENARIO_ID:
        if bool(air_list_screen_evidence.get("has_list_screen_evidence")):
            log(
                "[ENTRY][air][verdict_priority] "
                "applied_rule='reject_list_screen_overrides_verify' "
                "previous_state='candidate_success' new_state='verify_failed'"
            )
            log(
                "[ENTRY][air][verdict_inputs] "
                f"scenario_id='{scenario_id}' "
                f"post_click_success_seen={str(post_click_success_seen).lower()} "
                f"air_verify_success_seen={str(air_verify_success_seen).lower()} "
                f"air_verify_reject_seen={str(air_verify_reject_seen).lower()} "
                f"anchor_fallback_accepted={str(air_anchor_fallback_accepted).lower()} "
                f"anchor_fallback_source='{anchor_fallback_source or 'none'}' "
                f"post_open_focus_view_id='{post_view_id or 'none'}' "
                f"post_open_focus_label='{post_label or 'none'}' "
                f"is_top_chrome_focus={str(has_negative_signal).lower()} "
                f"is_list_screen_focus={str(bool(air_list_screen_evidence.get('has_list_screen_evidence'))).lower()} "
                "final_allow_success=false final_fail_reason='verify_failed:air_list_screen_evidence'"
            )
            log(
                f"[SCENARIO][entry_contract] failed scenario='{scenario_id}' entry_type='{entry_type}' "
                "reason='verify_failed' detail='air_list_screen_evidence'"
            )
            start_open_summary = getattr(client, "last_start_open_summary", {})
            if isinstance(start_open_summary, dict):
                start_open_summary["entry_contract_reason"] = _ENTRY_REASON_VERIFY_FAILED
                start_open_summary["entry_contract_detail"] = "air_list_screen_evidence"
                setattr(client, "last_start_open_summary", start_open_summary)
            return False
        preserve_success = bool(is_air_scenario and air_verified_success_seen and not air_verify_reject_seen)
        allow_missing_transition = bool(
            is_air_scenario
            and (air_verified_success_seen or not air_requires_verify)
            and str(air_verified_entry_reason or "").strip().lower() == "missing_transition_signal"
        )
        if str(air_verified_entry_reason or "").strip().lower() == "fallback_not_accepted" and preserve_success:
            log("[ENTRY][air][preserve] keep success despite fallback_not_accepted")
        if not air_verified_entry_context and allow_missing_transition:
            log("[ENTRY][air][preserve] ignore missing_transition_signal due to prior success")
        if (
            not air_verified_entry_context
            and not allow_missing_transition
            and not (str(air_verified_entry_reason or "").strip().lower() == "fallback_not_accepted" and preserve_success)
        ):
            applied_rule = (
                "reject_fallback_not_accepted"
                if str(air_verified_entry_reason or "").strip().lower() == "fallback_not_accepted"
                else "reject_air_verify_missing"
            )
            log(
                "[ENTRY][air][verdict_priority] "
                f"applied_rule='{applied_rule}' previous_state='candidate_success' new_state='verify_failed'"
            )
            log(
                "[ENTRY][air][verdict_inputs] "
                f"scenario_id='{scenario_id}' "
                f"post_click_success_seen={str(post_click_success_seen).lower()} "
                f"air_verify_success_seen={str(air_verify_success_seen).lower()} "
                f"air_verify_reject_seen={str(air_verify_reject_seen).lower()} "
                f"anchor_fallback_accepted={str(air_anchor_fallback_accepted).lower()} "
                f"anchor_fallback_source='{anchor_fallback_source or 'none'}' "
                f"post_open_focus_view_id='{post_view_id or 'none'}' "
                f"post_open_focus_label='{post_label or 'none'}' "
                f"is_top_chrome_focus={str(has_negative_signal).lower()} "
                f"is_list_screen_focus={str(bool(air_list_screen_evidence.get('has_list_screen_evidence'))).lower()} "
                f"final_allow_success=false final_fail_reason='{_ENTRY_REASON_VERIFY_FAILED}:{air_verified_entry_reason or 'air_verify_miss'}'"
            )
            log(
                f"[SCENARIO][entry_contract] failed scenario='{scenario_id}' entry_type='{entry_type}' "
                f"reason='{_ENTRY_REASON_VERIFY_FAILED}' detail='{air_verified_entry_reason or 'air_verify_miss'}'"
            )
            start_open_summary = getattr(client, "last_start_open_summary", {})
            if isinstance(start_open_summary, dict):
                start_open_summary["entry_contract_reason"] = _ENTRY_REASON_VERIFY_FAILED
                start_open_summary["entry_contract_detail"] = str(air_verified_entry_reason or "air_verify_miss")
                setattr(client, "last_start_open_summary", start_open_summary)
            return False
    entry_verify_candidate_success = bool(matches_verify and not has_negative_signal and not has_negative_verify_token)
    if (
        entry_type == _ENTRY_TYPE_CARD
        and not visible_verify_text
        and (tab_cfg.get("special_state_tokens") or tab_cfg.get("special_state_cta_tokens") or identity_nodes)
    ):
        visible_verify_text = _collect_post_open_visible_text(client, dev)
    special_state_detected, special_state_kind, special_state_meta = _classify_special_post_open_state(
        tab_cfg,
        post_view_id=post_view_id,
        post_label=post_label,
        post_speech=post_speech,
        visible_verify_text=visible_verify_text,
        matches_verify=matches_verify,
        post_nodes=identity_nodes,
    )
    special_signals = ",".join(special_state_meta.get("signals", [])) if isinstance(special_state_meta, dict) else ""
    log(
        "[ENTRY][special_state_check] "
        f"detected={str(bool(special_state_detected)).lower()} "
        f"signals='{special_signals or 'none'}' "
        f"kind='{special_state_kind or 'none'}'"
    )
    special_state_route_reason = "none"
    special_state_kind_is_setup_needed = str(special_state_kind or "").strip().lower() == "setup_needed_or_empty_state"
    special_state_long_intro_like = bool(special_state_meta.get("long_intro_like", False))
    special_state_cta_like = bool(
        special_state_meta.get("cta_hits")
        or special_state_meta.get("cta_pair", False)
    )
    special_state_low_content_diversity = bool(special_state_meta.get("low_content_diversity", False))
    special_state_intro_focus_like = bool(special_state_meta.get("intro_focus_like", False))
    special_state_top_chrome_intro_cta = bool(special_state_meta.get("top_chrome_intro_cta", False))
    strong_generic_special_state_evidence = bool(
        special_state_kind_is_setup_needed
        and special_state_long_intro_like
        and special_state_cta_like
        and special_state_low_content_diversity
        and special_state_intro_focus_like
    )
    consistent_intro_special_state_evidence = bool(
        special_state_kind_is_setup_needed
        and special_state_long_intro_like
        and (special_state_cta_like or special_state_intro_focus_like or special_state_top_chrome_intro_cta)
        and (special_state_low_content_diversity or special_state_intro_focus_like or special_state_top_chrome_intro_cta)
    )
    route_to_special_state = bool(
        special_state_detected
        and (
            not entry_verify_candidate_success
            or strong_generic_special_state_evidence
            or consistent_intro_special_state_evidence
        )
    )
    if route_to_special_state:
        special_state_route_reason = (
            "special_state_detected_verify_not_success"
            if not entry_verify_candidate_success
            else (
                "special_state_detected_strong_generic_evidence"
                if strong_generic_special_state_evidence
                else "special_state_detected_consistent_intro_evidence"
            )
        )
        log(
            "[ENTRY][special_state_check] "
            "decision='route_to_special_state' "
            f"reason='{special_state_route_reason}'"
        )
        handling = str(special_state_meta.get("handling", "") or "back_after_read")
        special_hits = ",".join(special_state_meta.get("special_hits", []))
        cta_hits = ",".join(special_state_meta.get("cta_hits", []))
        verify_hit = bool(special_state_meta.get("verify_hit", False))
        long_intro_like = special_state_long_intro_like
        log(f"[ENTRY][special_state_route] handling='{handling}'")
        log("[ENTRY][special_state_route] main_traversal_skipped=true")
        log(
            f"[SCENARIO][special_state] detected scenario='{scenario_id}' entry_type='{entry_type}' "
            f"kind='{special_state_kind}' handling='{handling}' verify_hit={str(verify_hit).lower()} "
            f"long_intro_like={str(long_intro_like).lower()} special_hits='{special_hits}' cta_hits='{cta_hits}'"
        )
        read_wait_seconds = min(main_step_wait_seconds, 0.5)
        if read_wait_seconds > 0:
            time.sleep(read_wait_seconds)
        back_status = "skipped"
        recover_reason = "not_required"
        recover_ok = handling != "back_after_read"
        if handling == "back_after_read":
            back_ok = _send_back(client, dev)
            if not back_ok:
                back_status = "back_failed"
                recover_reason = "back_failed"
            else:
                time.sleep(min(main_step_wait_seconds, 0.6))
                after_back_focus = client.get_focus(
                    dev=dev,
                    wait_seconds=min(main_step_wait_seconds, 0.8),
                    allow_fallback_dump=False,
                    mode="fast",
                )
                after_back_blob = _node_label_blob(after_back_focus if isinstance(after_back_focus, dict) else {}).lower()
                cta_tokens = [
                    str(token or "").strip().lower()
                    for token in tab_cfg.get("special_state_cta_tokens", [])
                    if str(token or "").strip()
                ]
                if not cta_tokens:
                    cta_tokens = ["start", "get started", "connect", "set up", "setup", "continue", "next", "try"]
                still_cta = bool(after_back_blob and any(token in after_back_blob for token in cta_tokens))
                back_status = "back_sent_still_cta" if still_cta else "back_sent_exit"
                recover_reason = "post_back_focus_still_cta" if still_cta else "post_back_focus_exit"
            log("[SPECIAL_STATE][recover] start")
            recover_ok = False
            for recover_attempt in range(1, 3):
                previous_recover_invocation_reason = tab_cfg.get("_recover_invocation_reason", None)
                tab_cfg["_recover_invocation_reason"] = "special_state_post_back"
                try:
                    recover_ok = recover_to_start_state(client, dev, tab_cfg)
                finally:
                    if previous_recover_invocation_reason is None:
                        tab_cfg.pop("_recover_invocation_reason", None)
                    else:
                        tab_cfg["_recover_invocation_reason"] = previous_recover_invocation_reason
                if recover_ok:
                    post_recover_state = _analyze_current_state(client, dev)
                    inside = _is_inside_smartthings(post_recover_state)
                    log(
                        "[SPECIAL_STATE][post_recover_check] "
                        f"inside_smartthings={str(inside).lower()} "
                        f"package={str(post_recover_state.get('package_signature_present', False)).lower()} "
                        f"app_bar_hits={int(post_recover_state.get('app_bar_hits', 0) or 0)}"
                    )
                    if not inside:
                        log("[SPECIAL_STATE][post_recover_check] detected_app_exit -> abort_recover")
                        recover_reason = "app_exited_after_back"
                        recover_ok = False
                        break
                    recover_reason = "life_plugin_list_recovered"
                    break
                recover_reason = "recover_to_start_state_failed"
                if recover_attempt < 2:
                    log(
                        f"[SPECIAL_STATE][recover] retry={recover_attempt}/2 "
                        "target='life_plugin_list' reason='recover_to_start_state_failed'"
                    )
            log(
                f"[SPECIAL_STATE][recover] success={str(recover_ok).lower()} "
                f"target='life_plugin_list' reason='{recover_reason}'"
            )
        if not recover_ok:
            start_open_summary = getattr(client, "last_start_open_summary", {})
            if isinstance(start_open_summary, dict):
                start_open_summary["entry_contract_reason"] = _ENTRY_REASON_VERIFY_FAILED
                start_open_summary["entry_contract_detail"] = f"special_state_recover_failed:{recover_reason}"
                start_open_summary["special_state_detected"] = True
                start_open_summary["special_state_kind"] = special_state_kind
                start_open_summary["special_state_handling"] = handling
                start_open_summary["special_state_back_status"] = back_status
                setattr(client, "last_start_open_summary", start_open_summary)
            log(
                f"[SCENARIO][entry_contract] failed scenario='{scenario_id}' entry_type='{entry_type}' "
                f"reason='{_ENTRY_REASON_VERIFY_FAILED}' detail='special_state_recover_failed:{recover_reason}'"
            )
            return False
        start_open_summary = getattr(client, "last_start_open_summary", {})
        if isinstance(start_open_summary, dict):
            start_open_summary["open_completed"] = True
            start_open_summary["entry_contract_reason"] = _ENTRY_REASON_SPECIAL_STATE_HANDLED
            start_open_summary["entry_contract_detail"] = "onboarding_back_exit_recovered"
            start_open_summary["special_state_detected"] = True
            start_open_summary["special_state_kind"] = special_state_kind
            start_open_summary["special_state_handling"] = handling
            start_open_summary["special_state_back_status"] = back_status
            setattr(client, "last_start_open_summary", start_open_summary)
        log(
            f"[SCENARIO][entry_contract] handled scenario='{scenario_id}' entry_type='{entry_type}' "
            f"reason='{_ENTRY_REASON_SPECIAL_STATE_HANDLED}' detail='onboarding_back_exit_recovered' "
            f"back_status='{back_status}'"
        )
        return True
    if special_state_detected:
        log("[ENTRY][special_state_check] decision='keep_success_path'")
    else:
        log("[ENTRY][special_state_check] decision='continue_verify'")

    if identity_mismatch:
        log(
            f"[ENTRY_GUARD][identity_mismatch] scenario='{scenario_id}' actual='{identity_actual}'"
        )
        previous_recover_invocation_reason = tab_cfg.get("_recover_invocation_reason", None)
        tab_cfg["_recover_invocation_reason"] = "entry_guard_identity_mismatch"
        try:
            recover_ok = recover_to_start_state(client, dev, tab_cfg)
        finally:
            if previous_recover_invocation_reason is None:
                tab_cfg.pop("_recover_invocation_reason", None)
            else:
                tab_cfg["_recover_invocation_reason"] = previous_recover_invocation_reason
        log(
            f"[ENTRY_GUARD][identity_mismatch] recover_triggered=true "
            f"recover_success={str(recover_ok).lower()}"
        )
        start_open_summary = getattr(client, "last_start_open_summary", {})
        if isinstance(start_open_summary, dict):
            start_open_summary["entry_contract_reason"] = _ENTRY_REASON_WRONG_OPEN
            start_open_summary["entry_contract_detail"] = f"identity_mismatch:{identity_actual or 'unknown'}"
            setattr(client, "last_start_open_summary", start_open_summary)
        return False

    if entry_type == _ENTRY_TYPE_DIRECT_SELECT and has_negative_verify_token:
        if diagnostic_entry:
            wrong_open_verify_hits = _collect_token_hits(
                normalized_verify_tokens,
                [post_view_id, post_label, post_speech, visible_verify_text, *extra_verify_candidates],
            )
            wrong_open_negative_hits = _collect_token_hits(
                normalized_negative_tokens,
                [post_view_id, post_label, post_speech, visible_verify_text, *extra_verify_candidates],
            )
            log(
                "[SCENARIO][direct_select][wrong_open_evidence] "
                f"scenario='{scenario_id}' focus_view_id='{post_view_id}' "
                f"focus_label='{post_label}' speech='{post_speech}' "
                f"verify_hits='{','.join(wrong_open_verify_hits) or 'none'}' "
                f"negative_hits='{','.join(wrong_open_negative_hits) or 'none'}' "
                f"negative_verify_hits={negative_verify_hits} "
                f"persist_threshold={_DIRECT_SELECT_NEGATIVE_VERIFY_PERSIST_THRESHOLD} "
                f"matches_verify={str(matches_verify).lower()} "
                f"has_negative_signal={str(has_negative_signal).lower()}"
            )
        log(
            f"[SCENARIO][entry_contract] failed scenario='{scenario_id}' entry_type='{entry_type}' "
            f"reason='{_ENTRY_REASON_WRONG_OPEN}' detail='post_open_negative_verify_token'"
        )
        start_open_summary = getattr(client, "last_start_open_summary", {})
        if isinstance(start_open_summary, dict):
            start_open_summary["entry_contract_reason"] = _ENTRY_REASON_WRONG_OPEN
            start_open_summary["entry_contract_detail"] = "post_open_negative_verify_token"
            setattr(client, "last_start_open_summary", start_open_summary)
        return False
    if entry_type == _ENTRY_TYPE_DIRECT_SELECT and not matches_verify:
        log(
            f"[SCENARIO][entry_contract] failed scenario='{scenario_id}' entry_type='{entry_type}' "
            f"reason='{_ENTRY_REASON_VERIFY_FAILED}' detail='post_open_verify_miss'"
        )
        start_open_summary = getattr(client, "last_start_open_summary", {})
        if isinstance(start_open_summary, dict):
            start_open_summary["entry_contract_reason"] = _ENTRY_REASON_VERIFY_FAILED
            start_open_summary["entry_contract_detail"] = "post_open_verify_miss"
            setattr(client, "last_start_open_summary", start_open_summary)
        return False
    requires_card_verify = entry_type == _ENTRY_TYPE_CARD and isinstance(tab_cfg.get("verify_tokens"), list) and bool(tab_cfg.get("verify_tokens"))
    if requires_card_verify and (has_negative_verify_token or not matches_verify):
        failure_reason = _ENTRY_REASON_WRONG_OPEN if (has_negative_signal or has_negative_verify_token) else _ENTRY_REASON_VERIFY_FAILED
        failure_detail = "post_open_negative_verify_token" if has_negative_verify_token else "post_open_verify_miss"
        log(
            f"[SCENARIO][entry_contract] failed scenario='{scenario_id}' entry_type='{entry_type}' "
            f"reason='{failure_reason}' detail='{failure_detail}'"
        )
        start_open_summary = getattr(client, "last_start_open_summary", {})
        if isinstance(start_open_summary, dict):
            start_open_summary["entry_contract_reason"] = failure_reason
            start_open_summary["entry_contract_detail"] = failure_detail
            setattr(client, "last_start_open_summary", start_open_summary)
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
        start_open_summary["post_click_transition_same_screen"] = post_click_transition_same_screen
        start_open_summary["post_click_transition_signal"] = post_click_transition_signal
        start_open_summary["entry_contract_reason"] = _ENTRY_REASON_SUCCESS_VERIFIED
        start_open_summary["entry_contract_detail"] = "plugin_open_verified"
        setattr(client, "last_start_open_summary", start_open_summary)
    if is_air_scenario:
        log(
            "[ENTRY][air][verdict_priority] "
            "applied_rule='accept_air_internal_content_signal' previous_state='candidate_success' new_state='success_verified'"
        )
        log(
            "[ENTRY][air][verdict_inputs] "
            f"scenario_id='{scenario_id}' "
            f"post_click_success_seen={str(post_click_success_seen).lower()} "
            f"air_verify_success_seen={str(air_verify_success_seen).lower()} "
            f"air_verify_reject_seen={str(air_verify_reject_seen).lower()} "
            f"anchor_fallback_accepted={str(air_anchor_fallback_accepted).lower()} "
            f"anchor_fallback_source='{anchor_fallback_source or 'none'}' "
            f"post_open_focus_view_id='{post_view_id or 'none'}' "
            f"post_open_focus_label='{post_label or 'none'}' "
            f"is_top_chrome_focus={str(has_negative_signal).lower()} "
            f"is_list_screen_focus={str(bool(air_list_screen_evidence.get('has_list_screen_evidence'))).lower()} "
            "final_allow_success=true final_fail_reason='none'"
        )
    log(
        f"[SCENARIO][entry_contract] success scenario='{scenario_id}' entry_type='{entry_type}' "
        f"reason='{_ENTRY_REASON_SUCCESS_VERIFIED}' detail='plugin_open_verified'"
    )
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
            else:
                log(
                    f"[ANCHOR][overlay_realign] success scenario='{tab_cfg.get('scenario_id', '')}' "
                    "reason='overlay_realign_verified'"
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


def _build_terminal_row(tab_cfg: dict[str, Any], *, stop_reason: str, status: str = "TAB_OPEN_FAILED") -> dict[str, Any]:
    row = {
        "tab_name": tab_cfg["tab_name"],
        "step_index": -1,
        "status": status,
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
        entry_type=str(tab_cfg.get("entry_type", _ENTRY_TYPE_CARD) or _ENTRY_TYPE_CARD),
        entry_contract_reason=_ENTRY_REASON_VERIFY_FAILED,
        entry_contract_detail="",
        special_state_detected=False,
        special_state_kind="",
        special_state_handling="",
        special_state_back_status="",
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
        result.entry_type = str(open_summary.get("entry_type", result.entry_type) or result.entry_type)
        result.entry_contract_reason = str(open_summary.get("entry_contract_reason", result.entry_contract_reason) or result.entry_contract_reason)
        result.entry_contract_detail = str(open_summary.get("entry_contract_detail", result.entry_contract_detail) or result.entry_contract_detail)
        result.special_state_detected = bool(open_summary.get("special_state_detected", False))
        result.special_state_kind = str(open_summary.get("special_state_kind", "") or "")
        result.special_state_handling = str(open_summary.get("special_state_handling", "") or "")
        result.special_state_back_status = str(open_summary.get("special_state_back_status", "") or "")
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

    if result.entry_contract_reason == _ENTRY_REASON_SPECIAL_STATE_HANDLED:
        result.success = True
        result.open_completed = True
        result.should_enter_main_loop = False
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
    setattr(
        client,
        "last_main_traversal_summary",
        {
            "scenario_id": str(tab_cfg.get("scenario_id", "") or ""),
            "scenario_type": str(tab_cfg.get("scenario_type", "") or ""),
            "main_steps_completed": 0,
            "stop_reason": "",
            "traversal_finished": False,
        },
    )
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
        failed_row = _build_terminal_row(
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
    if not start_result.should_enter_main_loop:
        if start_result.entry_contract_reason == _ENTRY_REASON_SPECIAL_STATE_HANDLED:
            handled_row = _build_terminal_row(
                tab_cfg,
                stop_reason=_ENTRY_REASON_SPECIAL_STATE_HANDLED,
                status="SPECIAL_STATE_HANDLED",
            )
            handled_row["entry_contract_detail"] = start_result.entry_contract_detail or "onboarding_back_exit"
            handled_row["special_state_detected"] = bool(start_result.special_state_detected)
            handled_row["special_state_kind"] = str(start_result.special_state_kind or "onboarding_or_empty_state")
            handled_row["special_state_handling"] = str(start_result.special_state_handling or "back_after_read")
            handled_row["special_state_back_status"] = str(start_result.special_state_back_status or "")
            rows.append(handled_row)
            all_rows.append(handled_row)
            if scenario_perf is not None:
                scenario_perf.record_row(handled_row)
                scenario_perf.finalize()
                log(format_perf_summary("scenario_summary", scenario_perf.summary_dict()))
            save_excel_with_perf(save_excel, all_rows, output_path, with_images=False, scenario_perf=scenario_perf)
        return rows
    if start_result.start_row is None:
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
    main_steps_completed = sum(1 for row in rows if int(row.get("step_index", -1) or -1) > 0)
    setattr(
        client,
        "last_main_traversal_summary",
        {
            "scenario_id": str(tab_cfg.get("scenario_id", "") or ""),
            "scenario_type": str(tab_cfg.get("scenario_type", "") or ""),
            "main_steps_completed": int(main_steps_completed),
            "stop_reason": str(state.stop_reason or ""),
            "traversal_finished": True,
        },
    )

    return rows
