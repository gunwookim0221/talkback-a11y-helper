import re
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.context_verifier import verify_context
from tb_runner.constants import MAIN_ANNOUNCEMENT_WAIT_SECONDS, MAIN_STEP_WAIT_SECONDS
from tb_runner.logging_utils import log
from tb_runner.utils import _safe_regex_search, parse_bounds_str

_VALID_STABILIZATION_MODES = {"tab_context", "anchor_only", "anchor_then_context"}


def _extract_candidate_from_node(node: dict[str, Any], index: int = -1) -> dict[str, Any]:
    text = str(node.get("text", "") or "").strip()
    description = str(node.get("contentDescription", "") or "").strip()
    announcement = str(node.get("talkbackLabel", "") or "").strip()
    if not announcement:
        announcement = f"{text} {description}".strip()
    resource_id = str(node.get("viewIdResourceName", "") or "").strip()
    class_name = str(node.get("className", "") or "").strip()
    bounds = str(node.get("boundsInScreen", "") or "").strip()
    parsed = parse_bounds_str(bounds)
    top, left, right, bottom = (parsed[1], parsed[0], parsed[2], parsed[3]) if parsed else (10**9, 10**9, -1, -1)
    return {
        "source": "dump_tree",
        "index": index,
        "text": text,
        "class_name": class_name,
        "announcement": announcement,
        "resource_id": resource_id,
        "bounds": bounds,
        "top": top,
        "left": left,
        "right": right,
        "bottom": bottom,
    }

def _extract_candidate_from_step(step: dict[str, Any]) -> dict[str, Any]:
    bounds = str(step.get("focus_bounds", "") or "").strip()
    parsed = parse_bounds_str(bounds)
    top, left, right, bottom = (parsed[1], parsed[0], parsed[2], parsed[3]) if parsed else (10**9, 10**9, -1, -1)
    return {
        "source": "focus_step",
        "index": -1,
        "text": str(step.get("visible_label", "") or "").strip(),
        "class_name": str(step.get("focus_node", {}).get("className", "") or "").strip(),
        "announcement": str(step.get("merged_announcement", "") or "").strip(),
        "resource_id": str(step.get("focus_view_id", "") or "").strip(),
        "bounds": bounds,
        "top": top,
        "left": left,
        "right": right,
        "bottom": bottom,
    }

def _resolve_anchor_cfg(tab_cfg: dict[str, Any]) -> dict[str, Any]:
    anchor_cfg = dict(tab_cfg.get("anchor", {}) or {})
    if "tie_breaker" not in anchor_cfg:
        anchor_cfg["tie_breaker"] = "top_left"
    anchor_cfg["allow_resource_id_only"] = bool(anchor_cfg.get("allow_resource_id_only", False))
    if not anchor_cfg.get("text_regex") and tab_cfg.get("anchor_name"):
        anchor_type = str(tab_cfg.get("anchor_type", "") or "").lower()
        if anchor_type in {"t", "b", "a"}:
            anchor_cfg["text_regex"] = str(tab_cfg.get("anchor_name") or "")
        if anchor_type in {"r", "a"}:
            anchor_cfg["resource_id_regex"] = str(tab_cfg.get("anchor_name") or "")
    return anchor_cfg

def _match_composite_candidate(candidate: dict[str, Any], match_cfg: dict[str, Any]) -> dict[str, Any]:
    matched_fields: list[str] = []
    score = 0

    resource_id_regex = str(match_cfg.get("resource_id_regex", "") or "").strip()
    text_regex = str(match_cfg.get("text_regex", "") or "").strip()
    announcement_regex = str(match_cfg.get("announcement_regex", "") or "").strip()
    class_name_regex = str(match_cfg.get("class_name_regex", "") or "").strip()
    bounds_regex = str(match_cfg.get("bounds_regex", "") or "").strip()
    allow_resource_id_only = bool(match_cfg.get("allow_resource_id_only", False))

    if resource_id_regex and _safe_regex_search(resource_id_regex, candidate.get("resource_id", "")):
        matched_fields.append("resource_id")
        score += 100
    if text_regex and _safe_regex_search(text_regex, candidate.get("text", "")):
        matched_fields.append("text")
        score += 40
    if announcement_regex and _safe_regex_search(announcement_regex, candidate.get("announcement", "")):
        matched_fields.append("announcement")
        score += 30
    if class_name_regex and _safe_regex_search(class_name_regex, candidate.get("class_name", "")):
        matched_fields.append("class_name")
        score += 20
    if bounds_regex and _safe_regex_search(bounds_regex, candidate.get("bounds", "")):
        matched_fields.append("bounds")
        score += 10

    has_resource_match = "resource_id" in matched_fields
    has_other_match = any(field in matched_fields for field in ("text", "announcement", "class_name"))
    matched = has_resource_match and (has_other_match or allow_resource_id_only)
    if not resource_id_regex:
        matched = bool(matched_fields)

    return {
        "matched": matched,
        "score": score,
        "matched_fields": matched_fields,
        "candidate": candidate,
        "allow_resource_id_only": allow_resource_id_only,
    }

def match_anchor(candidate: dict[str, Any], anchor_cfg: dict[str, Any]) -> dict[str, Any]:
    return _match_composite_candidate(candidate, anchor_cfg)

def choose_best_anchor_candidate(matches: list[dict[str, Any]], tie_breaker: str = "top_left") -> dict[str, Any] | None:
    if not matches:
        return None
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

def stabilize_anchor(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    phase: str,
    max_retries: int = 2,
    verify_reads: int = 2,
) -> dict[str, Any]:
    anchor_cfg = _resolve_anchor_cfg(tab_cfg)
    tie_breaker = str(anchor_cfg.get("tie_breaker", "top_left") or "top_left")
    stabilization_mode = str(tab_cfg.get("stabilization_mode", "anchor_then_context") or "anchor_then_context").strip().lower()
    if stabilization_mode not in _VALID_STABILIZATION_MODES:
        stabilization_mode = "anchor_then_context"
    last_verify: dict[str, Any] = {}
    last_context: dict[str, Any] = {"ok": True, "type": "none", "expected": ""}
    scenario_id = str(tab_cfg.get("scenario_id", "") or "")
    pre_navigation = tab_cfg.get("pre_navigation", [])
    has_pre_navigation = isinstance(pre_navigation, list) and bool(pre_navigation)
    screen_context_mode = str(tab_cfg.get("screen_context_mode", "") or "").strip().lower()
    transition_fast_path = (
        phase == "scenario_start"
        and has_pre_navigation
        and screen_context_mode == "new_screen"
        and stabilization_mode == "anchor_only"
    )

    for attempt in range(1, max_retries + 1):
        dump_nodes = client.dump_tree(dev=dev)
        candidates = [
            _extract_candidate_from_node(node, index=i)
            for i, node in enumerate(dump_nodes if isinstance(dump_nodes, list) else [])
        ]
        matches = [m for m in (match_anchor(c, anchor_cfg) for c in candidates) if m["matched"]]
        best = choose_best_anchor_candidate(matches, tie_breaker=tie_breaker)

        selected = False
        if best and best["candidate"].get("resource_id"):
            resource_pattern = f"^{re.escape(str(best['candidate']['resource_id']))}$"
            selected = client.select(
                dev=dev,
                name=resource_pattern,
                type_="r",
                wait_=8,
            )

        if not selected:
            selected = client.select(
                dev=dev,
                name=str(tab_cfg.get("anchor_name", "") or ""),
                type_=str(tab_cfg.get("anchor_type", "a") or "a"),
                wait_=8,
            )

        verify_match: dict[str, Any] | None = None
        context_result: dict[str, Any] = {"ok": True, "type": "none", "expected": ""}
        verify_rows: list[dict[str, Any]] = []
        for verify_idx in range(max(1, verify_reads)):
            verify_row = client.collect_focus_step(
                dev=dev,
                step_index=-(attempt * 10 + verify_idx),
                move=False,
                wait_seconds=min(MAIN_STEP_WAIT_SECONDS, 0.25) if transition_fast_path else MAIN_STEP_WAIT_SECONDS,
                announcement_wait_seconds=min(MAIN_ANNOUNCEMENT_WAIT_SECONDS, 0.2)
                if transition_fast_path
                else MAIN_ANNOUNCEMENT_WAIT_SECONDS,
                focus_wait_seconds=0.8 if transition_fast_path else None,
                allow_get_focus_fallback_dump=not transition_fast_path,
                allow_step_dump=not transition_fast_path,
                get_focus_mode="fast" if transition_fast_path else "normal",
            )
            verify_rows.append(verify_row)
            verify_candidate = _extract_candidate_from_step(verify_row)
            verify_match = match_anchor(verify_candidate, anchor_cfg)
            if stabilization_mode == "anchor_only":
                context_result = {
                    "ok": True,
                    "type": "skipped",
                    "expected": "",
                    "actual_text": "",
                    "actual_announcement": "",
                    "reason": "anchor_only_mode",
                }
                log("[CONTEXT] skipped reason='anchor_only_mode'")
            else:
                context_result = verify_context(verify_row, tab_cfg, client=client, dev=dev)
            if verify_match["matched"]:
                break

        last_verify = verify_match or {}
        last_context = context_result
        log(
            f"[ANCHOR][{phase}] attempt={attempt}/{max_retries} selected={selected} "
            f"mode='{stabilization_mode}' "
            f"matched={bool(last_verify.get('matched'))} "
            f"context_ok={bool(last_context.get('ok'))} "
            f"scenario='{scenario_id}' "
            f"fields={last_verify.get('matched_fields', [])} "
            f"score={last_verify.get('score', 0)} "
            f"resource='{(last_verify.get('candidate') or {}).get('resource_id', '')}' "
            f"bounds='{(last_verify.get('candidate') or {}).get('bounds', '')}'"
        )
        if str(last_context.get("type", "")) == "selected_bottom_tab":
            expected_value = (
                str(dict(tab_cfg.get("context_verify", {}) or {}).get("announcement_regex", "") or "").strip()
                or str(dict(tab_cfg.get("context_verify", {}) or {}).get("text_regex", "") or "").strip()
            )
            log(
                f"[CONTEXT][dump] scenario='{scenario_id}' type='selected_bottom_tab' "
                f"expected='{expected_value}'"
            )
            selected_candidates = last_context.get("selected_candidates", [])
            log(f"[CONTEXT][dump] selected_candidates_count={len(selected_candidates) if isinstance(selected_candidates, list) else 0}")
            log(f"[CONTEXT][dump] selected_candidates={selected_candidates}", level="DEBUG")
            log(f"[CONTEXT][dump] actual_selected_text='{last_context.get('actual_selected_text', '')}'")
            log(f"[CONTEXT][dump] source='{last_context.get('dump_source', 'step_cache')}'")
            log(f"[CONTEXT][dump] lazy_dump_node_count={int(last_context.get('lazy_dump_node_count', 0) or 0)}")
            log(f"[CONTEXT][dump] ok={bool(last_context.get('ok'))}")
        log(
            f"[CONTEXT] scenario='{scenario_id}' type='{last_context.get('type', 'none')}' "
            f"expected='{last_context.get('expected', '')}' "
            f"actual='{last_context.get('actual_selected_text', last_context.get('actual_announcement', last_context.get('actual_text', '')))}' "
            f"ok={bool(last_context.get('ok'))}"
        )
        verify_matched = bool(last_verify.get("matched"))
        context_ok = bool(last_context.get("ok"))
        if stabilization_mode == "anchor_only":
            success = verify_matched
        elif stabilization_mode == "tab_context":
            success = context_ok
        else:
            success = verify_matched and context_ok

        if not verify_matched:
            log(f"[ANCHOR][{phase}] anchor mismatch scenario='{scenario_id}'")
        elif not context_ok:
            log(f"[ANCHOR][{phase}] context mismatch scenario='{scenario_id}'")
            log(f"[CONTEXT] verification failed scenario='{scenario_id}'")
        else:
            log(f"[CONTEXT] verification passed scenario='{scenario_id}'")

        if success:
            success_reason = "selected_and_verified" if selected else "verified_without_select"
            log(
                f"[ANCHOR][{phase}] success scenario='{scenario_id}' selected={selected} "
                f"matched={verify_matched} context_ok={context_ok} reason='{success_reason}'"
            )
            return {
                "ok": True,
                "attempt": attempt,
                "selected": selected,
                "reason": success_reason,
                "verify": last_verify,
                "context": last_context,
                "verify_rows": verify_rows,
                "candidate_count": len(matches),
                "phase": phase,
            }

    return {
        "ok": False,
        "attempt": max_retries,
        "selected": False,
        "verify": last_verify,
        "context": last_context,
        "candidate_count": 0,
        "phase": phase,
    }
