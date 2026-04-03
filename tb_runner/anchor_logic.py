import re
import time
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.context_verifier import verify_context
from tb_runner.constants import MAIN_ANNOUNCEMENT_WAIT_SECONDS, MAIN_STEP_WAIT_SECONDS
from tb_runner.logging_utils import log
from tb_runner.utils import _safe_regex_search, parse_bounds_str

_VALID_STABILIZATION_MODES = {"tab_context", "anchor_only", "anchor_then_context"}
_ANCHOR_VERIFY_SETTLE_SECONDS = 0.12
_ANCHOR_VERIFY_SCORE_THRESHOLD = 100


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
    if not parsed:
        nums = [int(v) for v in re.findall(r"-?\d+", bounds)]
        if len(nums) >= 4:
            parsed = (nums[0], nums[1], nums[2], nums[3])
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
        "focusable": bool(node.get("focusable", False)),
        "clickable": bool(node.get("clickable", False)),
        "visible_to_user": bool(node.get("visibleToUser", True)),
    }

def _extract_candidate_from_step(step: dict[str, Any]) -> dict[str, Any]:
    bounds = str(step.get("focus_bounds", "") or "").strip()
    parsed = parse_bounds_str(bounds)
    if not parsed:
        nums = [int(v) for v in re.findall(r"-?\d+", bounds)]
        if len(nums) >= 4:
            parsed = (nums[0], nums[1], nums[2], nums[3])
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


def _has_explicit_anchor(tab_cfg: dict[str, Any], anchor_cfg: dict[str, Any]) -> bool:
    if str(tab_cfg.get("anchor_name", "") or "").strip():
        return True
    for key in ("resource_id_regex", "text_regex", "announcement_regex", "class_name_regex", "bounds_regex"):
        if str(anchor_cfg.get(key, "") or "").strip():
            return True
    return False


def _is_fallback_chrome_candidate(candidate: dict[str, Any], screen_width: int, screen_height: int) -> bool:
    top = int(candidate.get("top", 10**9))
    bottom = int(candidate.get("bottom", -1))
    left = int(candidate.get("left", 10**9))
    right = int(candidate.get("right", -1))
    class_name = str(candidate.get("class_name", "") or "").lower()
    resource_id = str(candidate.get("resource_id", "") or "").lower()
    label_blob = " ".join(
        [
            str(candidate.get("text", "") or "").lower(),
            str(candidate.get("announcement", "") or "").lower(),
        ]
    ).strip()

    if screen_height > 0 and top <= int(screen_height * 0.1):
        if any(token in f"{resource_id} {class_name} {label_blob}" for token in ("toolbar", "actionbar", "search", "뒤로", "back")):
            return True
    if screen_height > 0 and top >= int(screen_height * 0.78):
        if any(token in f"{resource_id} {class_name} {label_blob}" for token in ("bottom", "navigation", "tab", "menu_")):
            return True
    if any(token in f"{resource_id} {class_name} {label_blob}" for token in ("statusbar", "systemui", "more", "location")):
        return True
    if screen_width > 0 and (right <= 0 or left >= screen_width):
        return True
    if screen_height > 0 and (bottom <= 0 or top >= screen_height):
        return True
    return False


def _pick_top_content_fallback_candidate(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    if not candidates:
        return None, ""
    screen_width = max((int(c.get("right", 0) or 0) for c in candidates), default=0)
    screen_height = max((int(c.get("bottom", 0) or 0) for c in candidates), default=0)
    content_candidates = [
        c
        for c in candidates
        if bool(c.get("visible_to_user", True))
        and (bool(c.get("focusable", False)) or bool(c.get("clickable", False)))
        and int(c.get("top", 10**9)) >= 0
        and int(c.get("left", 10**9)) >= 0
        and not _is_fallback_chrome_candidate(c, screen_width, screen_height)
    ]
    if not content_candidates:
        return None, ""
    top_y = min(int(c.get("top", 10**9)) for c in content_candidates)
    top_row_tolerance = max(24, int(screen_height * 0.02)) if screen_height > 0 else 24
    top_row_candidates = [c for c in content_candidates if int(c.get("top", 10**9)) <= top_y + top_row_tolerance]
    if not top_row_candidates:
        return None, ""

    identity_candidates = [
        c
        for c in top_row_candidates
        if str(c.get("announcement", "") or "").strip()
        or str(c.get("text", "") or "").strip()
        or str(c.get("resource_id", "") or "").strip()
    ]
    if not identity_candidates:
        return None, ""
    if screen_width > 0:
        def _center_x(item: dict[str, Any]) -> int:
            return (int(item.get("left", 0)) + int(item.get("right", 0))) // 2

        left_bucket = [c for c in identity_candidates if _center_x(c) <= int(screen_width * 0.34)]
        if left_bucket:
            return sorted(left_bucket, key=lambda c: (int(c.get("left", 10**9)), int(c.get("top", 10**9))))[0], "top_left"

        center_bucket = [
            c for c in identity_candidates if int(screen_width * 0.34) < _center_x(c) < int(screen_width * 0.66)
        ]
        if center_bucket:
            center_x = screen_width // 2
            return sorted(
                center_bucket,
                key=lambda c: (
                    abs(_center_x(c) - center_x),
                    int(c.get("left", 10**9)),
                ),
            )[0], "top_center"

        right_bucket = [c for c in identity_candidates if _center_x(c) >= int(screen_width * 0.66)]
        if right_bucket:
            return sorted(right_bucket, key=lambda c: (-int(c.get("right", -1)), int(c.get("top", 10**9))))[0], "top_right"

    return sorted(identity_candidates, key=lambda c: (int(c.get("left", 10**9)), int(c.get("top", 10**9))))[0], "top_left"


def _build_verify_cfg_for_fallback(candidate: dict[str, Any]) -> dict[str, Any]:
    resource_id = str(candidate.get("resource_id", "") or "").strip()
    text = str(candidate.get("text", "") or "").strip()
    announcement = str(candidate.get("announcement", "") or "").strip()
    verify_cfg: dict[str, Any] = {"allow_resource_id_only": True, "tie_breaker": "top_left"}
    if resource_id:
        verify_cfg["resource_id_regex"] = f"^{re.escape(resource_id)}$"
    if text:
        verify_cfg["text_regex"] = f"^{re.escape(text)}$"
    elif announcement:
        verify_cfg["announcement_regex"] = f"^{re.escape(announcement)}$"
    return verify_cfg


def _select_anchor_candidate(client: A11yAdbClient, dev: str, candidate: dict[str, Any]) -> tuple[bool, bool]:
    select_attempted = False
    selected = False
    resource_id = str(candidate.get("resource_id", "") or "").strip()
    if resource_id:
        select_attempted = True
        selected = client.select(
            dev=dev,
            name=f"^{re.escape(resource_id)}$",
            type_="r",
            wait_=8,
        )
    if selected:
        return True, True
    announcement = str(candidate.get("announcement", "") or "").strip()
    if announcement:
        select_attempted = True
        selected = client.select(
            dev=dev,
            name=f"^{re.escape(announcement)}$",
            type_="a",
            wait_=8,
        )
    return selected, select_attempted


def _is_anchor_verify_match(verify_match: dict[str, Any], anchor_cfg: dict[str, Any]) -> bool:
    score_threshold = int(anchor_cfg.get("score_threshold", _ANCHOR_VERIFY_SCORE_THRESHOLD) or _ANCHOR_VERIFY_SCORE_THRESHOLD)
    return bool(verify_match.get("matched")) or int(verify_match.get("score", 0) or 0) >= score_threshold


def stabilize_anchor_focus(
    client: A11yAdbClient,
    dev: str,
    anchor_cfg: dict[str, Any],
    *,
    attempt: int,
    max_retries: int,
    transition_fast_path: bool,
) -> dict[str, Any]:
    verify_rows: list[dict[str, Any]] = []
    verify_matches: list[dict[str, Any]] = []
    verify_flags: list[bool] = []
    for verify_idx in range(2):
        if verify_idx > 0:
            time.sleep(_ANCHOR_VERIFY_SETTLE_SECONDS)
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
        verify_match = match_anchor(_extract_candidate_from_step(verify_row), anchor_cfg)
        verify_matches.append(verify_match)
        verify_flags.append(_is_anchor_verify_match(verify_match, anchor_cfg))

    verify1_matched = bool(verify_flags[0]) if verify_flags else False
    verify2_matched = bool(verify_flags[1]) if len(verify_flags) > 1 else False
    stable = verify1_matched and verify2_matched
    reason = "double_verified" if stable and attempt == 1 else "retry_success" if stable else "not_stable"
    return {
        "stable": stable,
        "reason": reason,
        "verify_rows": verify_rows,
        "verify_matches": verify_matches,
        "verify1_matched": verify1_matched,
        "verify2_matched": verify2_matched,
    }

def stabilize_anchor(
    client: A11yAdbClient,
    dev: str,
    tab_cfg: dict[str, Any],
    phase: str,
    max_retries: int = 2,
    verify_reads: int = 2,
) -> dict[str, Any]:
    _ = verify_reads  # backward-compatible signature; anchor stabilization uses fixed double verification.
    anchor_cfg = _resolve_anchor_cfg(tab_cfg)
    explicit_anchor_configured = _has_explicit_anchor(tab_cfg, anchor_cfg)
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
        log(f"[ANCHOR][stabilize] attempt={attempt}/{max_retries} scenario='{scenario_id}'")
        dump_nodes = client.dump_tree(dev=dev)
        candidates = [
            _extract_candidate_from_node(node, index=i)
            for i, node in enumerate(dump_nodes if isinstance(dump_nodes, list) else [])
        ]
        matches: list[dict[str, Any]] = []
        best: dict[str, Any] | None = None
        fallback_position = ""
        active_anchor_cfg = dict(anchor_cfg)
        if explicit_anchor_configured:
            matches = [m for m in (match_anchor(c, anchor_cfg) for c in candidates) if m["matched"]]
            best = choose_best_anchor_candidate(matches, tie_breaker=tie_breaker)
        elif attempt == 1:
            log("[ANCHOR][fallback] no explicit anchor configured")

        fallback_candidate: dict[str, Any] | None = None
        if best is None:
            if explicit_anchor_configured:
                log("[ANCHOR][fallback] explicit anchor not matched, trying top content fallback")
            fallback_candidate, fallback_position = _pick_top_content_fallback_candidate(candidates)
            if fallback_candidate:
                active_anchor_cfg = _build_verify_cfg_for_fallback(fallback_candidate)
                best = {"candidate": fallback_candidate, "score": 0, "matched": True, "matched_fields": ["fallback"]}
                log(
                    f"[ANCHOR][fallback] selected candidate label='{fallback_candidate.get('announcement', '')}' "
                    f"position='{fallback_position}'"
                )
            else:
                log("[ANCHOR][fallback] no usable fallback candidate")

        selected = False
        select_attempted = False
        if best:
            selected, select_attempted = _select_anchor_candidate(client, dev, best["candidate"])

        if not selected and fallback_candidate is None:
            select_attempted = True
            selected = client.select(
                dev=dev,
                name=str(tab_cfg.get("anchor_name", "") or ""),
                type_=str(tab_cfg.get("anchor_type", "a") or "a"),
                wait_=8,
            )

        verify_match: dict[str, Any] | None = None
        context_result: dict[str, Any] = {"ok": True, "type": "none", "expected": ""}
        verify_rows: list[dict[str, Any]] = []
        verify_results = stabilize_anchor_focus(
            client=client,
            dev=dev,
            anchor_cfg=active_anchor_cfg,
            attempt=attempt,
            max_retries=max_retries,
            transition_fast_path=transition_fast_path,
        )
        verify_rows = list(verify_results.get("verify_rows", []))
        verify_matches = list(verify_results.get("verify_matches", []))
        if verify_matches:
            verify_match = verify_matches[-1]
        for verify_row in verify_rows:
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
            if not context_result.get("ok"):
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
        verify_stable = bool(verify_results.get("stable"))
        verify1_matched = bool(verify_results.get("verify1_matched"))
        verify2_matched = bool(verify_results.get("verify2_matched"))
        context_ok = bool(last_context.get("ok"))
        if stabilization_mode == "anchor_only":
            success = verify_stable
        elif stabilization_mode == "tab_context":
            success = context_ok
        else:
            success = verify_stable and context_ok

        if select_attempted and not selected and not verify_stable:
            stabilize_reason = "select_failed"
        else:
            stabilize_reason = str(verify_results.get("reason", "not_stable") or "not_stable")
        log(
            f"[ANCHOR][stabilize] attempt={attempt}/{max_retries} "
            f"scenario='{scenario_id}' "
            f"select_attempted={str(select_attempted).lower()} "
            f"verify1_matched={str(verify1_matched).lower()} "
            f"verify2_matched={str(verify2_matched).lower()} "
            f"stable={str(verify_stable).lower()} "
            f"reason='{stabilize_reason}'"
        )

        if not verify_matched:
            log(f"[ANCHOR][{phase}] anchor mismatch scenario='{scenario_id}'")
        if not verify_stable and stabilization_mode != "tab_context":
            log(f"[ANCHOR][{phase}] anchor not stable scenario='{scenario_id}'")
        elif not context_ok:
            log(f"[ANCHOR][{phase}] context mismatch scenario='{scenario_id}'")
            log(f"[CONTEXT] verification failed scenario='{scenario_id}'")
        else:
            log(f"[CONTEXT] verification passed scenario='{scenario_id}'")

        if success:
            if stabilization_mode == "tab_context":
                success_reason = "context_verified"
            elif selected:
                success_reason = "selected_and_verified"
            else:
                success_reason = "verified_without_select"
            log(
                f"[ANCHOR][{phase}] success scenario='{scenario_id}' selected={selected} "
                f"matched={verify_matched} stable={verify_stable} context_ok={context_ok} reason='{success_reason}'"
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
        "reason": "low_confidence_anchor_start",
        "verify": last_verify,
        "context": last_context,
        "candidate_count": 0,
        "phase": phase,
    }
