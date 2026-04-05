import re
import time
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.anchor_logic import _extract_candidate_from_node, _match_composite_candidate
from tb_runner.constants import MAIN_ANNOUNCEMENT_WAIT_SECONDS, MAIN_STEP_WAIT_SECONDS
from tb_runner.context_verifier import verify_context
from tb_runner.logging_utils import _should_log, log
from tb_runner.utils import parse_bounds_str


def normalize_tab_config(tab_cfg: dict[str, Any]) -> dict[str, Any]:
    normalized_tab_cfg = dict(tab_cfg.get("tab", {}) or {})
    fallback_to_legacy = not bool(normalized_tab_cfg)
    if fallback_to_legacy:
        tab_name = str(tab_cfg.get("tab_name", "") or "").strip()
        tab_type = str(tab_cfg.get("tab_type", "") or "").strip().lower()
        if tab_type in {"t", "b", "a"} and tab_name:
            normalized_tab_cfg["text_regex"] = tab_name
        if tab_type in {"r", "a"} and tab_name:
            normalized_tab_cfg["resource_id_regex"] = tab_name
    if "tie_breaker" not in normalized_tab_cfg:
        normalized_tab_cfg["tie_breaker"] = "bottom_nav_left_to_right"
    normalized_tab_cfg["allow_resource_id_only"] = bool(normalized_tab_cfg.get("allow_resource_id_only", False))
    normalized_tab_cfg["_fallback_to_legacy"] = fallback_to_legacy
    return normalized_tab_cfg

def match_tab_candidate(node: dict[str, Any], tab_cfg: dict[str, Any]) -> dict[str, Any]:
    candidate = _extract_candidate_from_node(node)
    return _match_composite_candidate(candidate, tab_cfg)

def choose_best_tab_candidate(matches: list[dict[str, Any]], tie_breaker: str = "first_match") -> dict[str, Any] | None:
    if not matches:
        return None
    if tie_breaker == "bottom_nav_left_to_right":
        return sorted(
            matches,
            key=lambda item: (
                -int(item.get("score", 0)),
                -int(item["candidate"].get("top", -1)),
                int(item["candidate"].get("left", 10**9)),
                int("resource_id" in item.get("matched_fields", [])) * -1,
            ),
        )[0]
    if tie_breaker == "top_left":
        return sorted(
            matches,
            key=lambda item: (
                -int(item.get("score", 0)),
                int(item["candidate"].get("top", 10**9)),
                int(item["candidate"].get("left", 10**9)),
            ),
        )[0]
    return sorted(matches, key=lambda item: -int(item.get("score", 0)))[0]


def _resolve_focus_align_retry_count(tab_cfg: dict[str, Any], fallback: int = 2) -> int:
    value = tab_cfg.get("tab_focus_align_retry_count", fallback)
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int) and value > 0:
        return value
    return fallback


def _resolve_positive_float(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return fallback


def _is_transition_fast_align(tab_cfg: dict[str, Any]) -> bool:
    screen_context_mode = str(tab_cfg.get("screen_context_mode", "") or "").strip().lower()
    pre_navigation = tab_cfg.get("pre_navigation", [])
    has_pre_navigation = isinstance(pre_navigation, list) and bool(pre_navigation)
    return screen_context_mode == "new_screen" and has_pre_navigation


def _is_transition_fast_verify_path(tab_cfg: dict[str, Any], fast_focus_align: bool) -> bool:
    if not fast_focus_align:
        return False
    context_cfg = tab_cfg.get("context_verify", {})
    if not isinstance(context_cfg, dict):
        return True
    context_type = str(context_cfg.get("type", "none") or "none").strip().lower()
    return context_type in {"", "none"}


def _attempt_tab_focus_alignment(
    client: A11yAdbClient,
    dev: str,
    scenario_id: str,
    normalized_tab_cfg: dict[str, Any],
    best: dict[str, Any] | None,
    max_retries: int,
    *,
    fast_mode: bool = False,
    select_wait_seconds: int = 5,
) -> dict[str, Any]:
    log_tag = "[TAB][focus_align_fast]" if fast_mode else "[TAB][focus_align]"
    selectors: list[tuple[str, str, str]] = []
    best_candidate = (best or {}).get("candidate", {}) if isinstance(best, dict) else {}
    best_resource = str(best_candidate.get("resource_id", "") or "").strip()
    if best_resource:
        selectors.append(("r", f"^{re.escape(best_resource)}$", "best_resource_exact"))

    tab_resource_regex = str(normalized_tab_cfg.get("resource_id_regex", "") or "").strip()
    if tab_resource_regex:
        selectors.append(("r", tab_resource_regex, "tab_resource_regex"))
    tab_text_regex = str(normalized_tab_cfg.get("text_regex", "") or "").strip()
    if tab_text_regex:
        selectors.append(("t", tab_text_regex, "tab_text_regex"))
    tab_announcement_regex = str(normalized_tab_cfg.get("announcement_regex", "") or "").strip()
    if tab_announcement_regex:
        selectors.append(("a", tab_announcement_regex, "tab_announcement_regex"))

    deduped_selectors: list[tuple[str, str, str]] = []
    visited: set[tuple[str, str]] = set()
    for type_, pattern, source in selectors:
        key = (type_, pattern)
        if key in visited:
            continue
        visited.add(key)
        deduped_selectors.append((type_, pattern, source))

    if not deduped_selectors:
        log(f"{log_tag} skipped scenario='{scenario_id}' reason='no_selector'", level="DEBUG")
        return {"attempted": False, "ok": False, "reason": "no_selector"}

    for attempt in range(1, max_retries + 1):
        type_, pattern, source = deduped_selectors[(attempt - 1) % len(deduped_selectors)]
        log(
            f"{log_tag} attempt={attempt}/{max_retries} scenario='{scenario_id}' "
            f"type='{type_}' source='{source}'",
            level="DEBUG",
        )
        aligned = bool(client.select(dev=dev, name=pattern, type_=type_, wait_=select_wait_seconds))
        if aligned:
            log(
                f"{log_tag} success scenario='{scenario_id}' attempt={attempt}/{max_retries} "
                f"type='{type_}' source='{source}'",
                level="DEBUG",
            )
            return {"attempted": True, "ok": True, "attempt": attempt, "type": type_, "source": source}

    last_result = getattr(client, "last_target_action_result", {})
    target = last_result.get("target", {}) if isinstance(last_result, dict) else {}
    focus_label = str(target.get("text", "") or target.get("contentDescription", "") or "").strip()
    focus_resource = str(target.get("viewIdResourceName", "") or target.get("resourceId", "") or "").strip()
    log(
        f"{log_tag} failed scenario='{scenario_id}' attempt={max_retries}/{max_retries} "
        f"focus_label='{focus_label}' focus_resource='{focus_resource}'"
    )
    return {
        "attempted": True,
        "ok": False,
        "attempt": max_retries,
        "reason": "selector_not_focused",
        "focus_label": focus_label,
        "focus_resource": focus_resource,
    }


def stabilize_tab_selection(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    max_retries: int = 2,
) -> dict[str, Any]:
    normalized_tab_cfg = normalize_tab_config(tab_cfg)
    tie_breaker = str(normalized_tab_cfg.get("tie_breaker", "bottom_nav_left_to_right") or "bottom_nav_left_to_right")
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    focus_align_retries = _resolve_focus_align_retry_count(tab_cfg, fallback=2)
    fast_focus_align = _is_transition_fast_align(tab_cfg)
    fast_verify_path = _is_transition_fast_verify_path(tab_cfg, fast_focus_align)
    if fast_focus_align:
        focus_align_retries = min(focus_align_retries, 2)
        if focus_align_retries < 1:
            focus_align_retries = 1
    fallback_to_legacy = bool(normalized_tab_cfg.get("_fallback_to_legacy", False))
    if fallback_to_legacy:
        log(f"[TAB][select] fallback_to_legacy=True scenario='{scenario_id}'")

    last_context: dict[str, Any] = {"ok": True, "type": "none", "expected": ""}
    last_best: dict[str, Any] = {}
    last_selected = False
    focus_align_result: dict[str, Any] = {"attempted": False, "ok": False, "reason": "not_attempted"}
    for attempt in range(1, max_retries + 1):
        dump_nodes = client.dump_tree(dev=dev)
        node_list = dump_nodes if isinstance(dump_nodes, list) else []
        matches = [m for m in (match_tab_candidate(node, normalized_tab_cfg) for node in node_list) if m.get("matched")]
        best = choose_best_tab_candidate(matches, tie_breaker=tie_breaker)
        last_best = best or {}
        log(
            f"[TAB][select][debug] scenario='{scenario_id}' candidates={len(matches)} tie_breaker='{tie_breaker}'",
            level="DEBUG",
        )

        selected = False
        tab_action_mode = "legacy_touch"
        tab_action_reason = ""
        if best and best.get("candidate", {}).get("resource_id"):
            candidate = best.get("candidate", {}) or {}
            best_resource = str(candidate.get("resource_id", "") or "")
            raw_bounds = candidate.get("bounds", "")
            best_bounds = str(raw_bounds or "")
            parsed_bounds = parse_bounds_str(raw_bounds)
            center_x: int | None = None
            center_y: int | None = None
            touch_eligible = bool(parsed_bounds)
            debug_reason = ""
            if parsed_bounds:
                l, t, r, b = parsed_bounds
                center_x = int((l + r) / 2)
                center_y = int((t + b) / 2)
                tab_action_mode = "touch"
                log(
                    f"[TAB][action] scenario='{scenario_id}' mode='touch' "
                    f"resource='{best_resource}' bounds='{best_bounds}' center='{center_x},{center_y}'",
                    level="DEBUG",
                )
                selected = client.touch_point(dev=dev, x=center_x, y=center_y)
                if not selected:
                    tab_action_mode = "select_fallback"
                    tab_action_reason = "touch_failed"
                    debug_reason = tab_action_reason
                    resource_pattern = f"^{re.escape(best_resource)}$"
                    selected = client.select(dev=dev, name=resource_pattern, type_="r", wait_=5)
                    log(
                        f"[TAB][action] scenario='{scenario_id}' mode='select_fallback' "
                        f"reason='{tab_action_reason}' resource='{best_resource}'",
                        level="DEBUG",
                    )
            else:
                tab_action_mode = "select_fallback"
                tab_action_reason = "missing_bounds"
                debug_reason = "bounds_parse_failed"
                resource_pattern = f"^{re.escape(best_resource)}$"
                selected = client.select(dev=dev, name=resource_pattern, type_="r", wait_=5)
                log(
                    f"[TAB][action] scenario='{scenario_id}' mode='select_fallback' "
                    f"reason='{tab_action_reason}' resource='{best_resource}' bounds='{best_bounds}'",
                    level="DEBUG",
                )
            parsed_bounds_text = (
                f"{parsed_bounds[0]},{parsed_bounds[1]},{parsed_bounds[2]},{parsed_bounds[3]}" if parsed_bounds else ""
            )
            center_text = f"{center_x},{center_y}" if center_x is not None and center_y is not None else ""
            debug_reason_text = f" reason='{debug_reason}'" if debug_reason else ""
            log(
                f"[TAB][action][debug] raw_bounds='{raw_bounds}' parsed_bounds='{parsed_bounds_text}' "
                f"center='{center_text}' touch_eligible={touch_eligible}{debug_reason_text}",
                level="DEBUG",
            )

        if not selected:
            selected = client.touch(
                dev=dev,
                name=str(tab_cfg.get("tab_name", "") or ""),
                type_=str(tab_cfg.get("tab_type", "") or ""),
                wait_=5,
            )
            if tab_action_mode == "legacy_touch":
                log(
                    f"[TAB][action] scenario='{scenario_id}' mode='legacy_touch' "
                    f"reason='no_best_candidate_or_resource'",
                    level="DEBUG",
                )
            else:
                log(
                    f"[TAB][action] scenario='{scenario_id}' mode='legacy_touch' "
                    f"reason='fallback_after_{tab_action_mode}'",
                    level="DEBUG",
                )

        focus_align_result = {"attempted": False, "ok": False, "reason": "not_selected"}
        if selected:
            if fast_focus_align:
                settle_wait_seconds = min(
                    _resolve_positive_float(tab_cfg.get("tab_focus_align_settle_wait_seconds"), 0.12),
                    0.2,
                )
                log(
                    f"[TAB][focus_align_fast] path='touch_immediate' scenario='{scenario_id}' "
                    f"transition=true settle_wait_seconds={settle_wait_seconds:.2f} max_attempts={focus_align_retries}",
                    level="DEBUG",
                )
                time.sleep(settle_wait_seconds)
            focus_align_result = _attempt_tab_focus_alignment(
                client=client,
                dev=dev,
                scenario_id=scenario_id,
                normalized_tab_cfg=normalized_tab_cfg,
                best=best,
                max_retries=focus_align_retries,
                fast_mode=fast_focus_align,
                select_wait_seconds=1 if fast_focus_align else 5,
            )
            focus_align_result["fast_mode"] = fast_focus_align
        else:
            log(f"[TAB][focus_align] skipped scenario='{scenario_id}' reason='tab_select_failed'", level="DEBUG")

        if selected and focus_align_result.get("ok") and fast_verify_path:
            log(f"[TAB][focus_align_fast] verify_shortcut scenario='{scenario_id}' reason='context_none'", level="DEBUG")
            return {
                "ok": True,
                "attempt": attempt,
                "selected": selected,
                "focus_align": focus_align_result,
                "verify_context": {"ok": True, "type": "none", "expected": "", "reason": "fast_verify_shortcut"},
                "best": best,
                "candidate_count": len(matches),
            }

        verify_row = client.collect_focus_step(
            dev=dev,
            step_index=-(500 + attempt),
            move=False,
            wait_seconds=min(MAIN_STEP_WAIT_SECONDS, 0.25) if fast_focus_align else MAIN_STEP_WAIT_SECONDS,
            announcement_wait_seconds=min(MAIN_ANNOUNCEMENT_WAIT_SECONDS, 0.2)
            if fast_focus_align
            else MAIN_ANNOUNCEMENT_WAIT_SECONDS,
            focus_wait_seconds=0.8 if fast_focus_align else None,
            allow_get_focus_fallback_dump=not fast_focus_align,
            allow_step_dump=not fast_focus_align,
            get_focus_mode="fast" if fast_focus_align else "normal",
        )
        last_context = verify_context(verify_row, tab_cfg, client=client, dev=dev)
        log(
            f"[TAB][select] scenario='{scenario_id}' selected={selected} "
            f"matched_fields={(best or {}).get('matched_fields', [])} score={(best or {}).get('score', 0)}"
        )
        log(
            f"[TAB][verify] selected_bottom_tab ok={bool(last_context.get('ok'))} "
            f"actual='{last_context.get('actual_selected_text', '')}'"
        )
        if _should_log("DEBUG") and best:
            log(
                f"[TAB][select][debug] best_resource='{best['candidate'].get('resource_id', '')}' "
                f"best_bounds='{best['candidate'].get('bounds', '')}'"
            )
        if selected and bool(last_context.get("ok")):
            return {
                "ok": True,
                "attempt": attempt,
                "selected": selected,
                "focus_align": focus_align_result,
                "verify_context": last_context,
                "best": best,
                "candidate_count": len(matches),
            }
        last_selected = bool(selected)
        if attempt < max_retries:
            log(f"[TAB][select] retry {attempt}/{max_retries} scenario='{scenario_id}'", level="DEBUG")

    return {
        "ok": False,
        "attempt": max_retries,
        "selected": last_selected,
        "focus_align": focus_align_result,
        "verify_context": last_context,
        "best": last_best,
    }
