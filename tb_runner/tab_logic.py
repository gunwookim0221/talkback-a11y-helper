import re
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

def stabilize_tab_selection(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    max_retries: int = 2,
) -> dict[str, Any]:
    normalized_tab_cfg = normalize_tab_config(tab_cfg)
    tie_breaker = str(normalized_tab_cfg.get("tie_breaker", "bottom_nav_left_to_right") or "bottom_nav_left_to_right")
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    fallback_to_legacy = bool(normalized_tab_cfg.get("_fallback_to_legacy", False))
    if fallback_to_legacy:
        log(f"[TAB][select] fallback_to_legacy=True scenario='{scenario_id}'")

    last_context: dict[str, Any] = {"ok": True, "type": "none", "expected": ""}
    last_best: dict[str, Any] = {}
    last_selected = False
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
                    f"resource='{best_resource}' bounds='{best_bounds}' center='{center_x},{center_y}'"
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
                        f"reason='{tab_action_reason}' resource='{best_resource}'"
                    )
            else:
                tab_action_mode = "select_fallback"
                tab_action_reason = "missing_bounds"
                debug_reason = "bounds_parse_failed"
                resource_pattern = f"^{re.escape(best_resource)}$"
                selected = client.select(dev=dev, name=resource_pattern, type_="r", wait_=5)
                log(
                    f"[TAB][action] scenario='{scenario_id}' mode='select_fallback' "
                    f"reason='{tab_action_reason}' resource='{best_resource}' bounds='{best_bounds}'"
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
                    f"reason='no_best_candidate_or_resource'"
                )
            else:
                log(
                    f"[TAB][action] scenario='{scenario_id}' mode='legacy_touch' "
                    f"reason='fallback_after_{tab_action_mode}'"
                )

        verify_row = client.collect_focus_step(
            dev=dev,
            step_index=-(500 + attempt),
            move=False,
            wait_seconds=MAIN_STEP_WAIT_SECONDS,
            announcement_wait_seconds=MAIN_ANNOUNCEMENT_WAIT_SECONDS,
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
                "verify_context": last_context,
                "best": best,
                "candidate_count": len(matches),
            }
        last_selected = bool(selected)
        if attempt < max_retries:
            log(f"[TAB][select] retry {attempt}/{max_retries} scenario='{scenario_id}'")

    return {
        "ok": False,
        "attempt": max_retries,
        "selected": last_selected,
        "verify_context": last_context,
        "best": last_best,
    }
