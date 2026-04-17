import re
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.logging_utils import _should_log, log
from tb_runner.utils import _safe_regex_search


_TAB_ALIAS_TO_CANONICAL = {
    "홈": "home",
    "기기": "devices",
    "라이프": "life",
    "자동화": "routines",
    "메뉴": "menu",
    "선택됨": "selected",
    "새 콘텐츠 사용 가능": "new content available",
}

_BOTTOM_GLOBAL_NAV_RESOURCE_REGEX = re.compile(
    r"com\.samsung\.android\.oneconnect:id/(menu_(favorites|devices|services|automations|more)|bottom_(favorites|devices|services|automations|more))",
    flags=re.IGNORECASE,
)


def _expand_bottom_tab_aliases(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    lowered = text.lower()
    normalized_additions: list[str] = []
    for alias, canonical in _TAB_ALIAS_TO_CANONICAL.items():
        if alias in text and canonical not in lowered:
            normalized_additions.append(canonical)
    if not normalized_additions:
        return text
    return f"{text}, {', '.join(normalized_additions)}"


def _is_bottom_nav_resource_id(view_id: str, scenario_cfg: dict[str, Any]) -> bool:
    normalized_view_id = str(view_id or "").strip().lower()
    if not normalized_view_id:
        return False
    global_nav_cfg = scenario_cfg.get("global_nav", {})
    if isinstance(global_nav_cfg, dict):
        known_ids = [str(item or "").strip().lower() for item in global_nav_cfg.get("resource_ids", []) if isinstance(item, str)]
        if known_ids and normalized_view_id in known_ids:
            return True
    return bool(_BOTTOM_GLOBAL_NAV_RESOURCE_REGEX.search(normalized_view_id))


def _build_focus_selected_text(step: dict[str, Any]) -> str:
    focus_node = step.get("focus_node", {})
    source_map = focus_node if isinstance(focus_node, dict) else {}
    values: list[str] = []
    for value in (
        source_map.get("talkbackLabel", ""),
        source_map.get("mergedLabel", ""),
        source_map.get("contentDescription", ""),
        source_map.get("text", ""),
        step.get("visible_label", ""),
        step.get("merged_announcement", ""),
        step.get("focus_content_description", ""),
    ):
        normalized = str(value or "").strip()
        if normalized and normalized not in values:
            values.append(normalized)
    return " | ".join(values)


def verify_context(
    step: dict[str, Any],
    scenario_cfg: dict[str, Any],
    client: A11yAdbClient | None = None,
    dev: str = "",
) -> dict[str, Any]:
    context_cfg = dict(scenario_cfg.get("context_verify", {}) or {})
    if not context_cfg and str(scenario_cfg.get("screen_context_mode", "") or "").strip().lower() == "new_screen":
        return {
            "ok": True,
            "type": "none",
            "expected": "",
            "actual_text": "",
            "actual_announcement": "",
            "skipped": True,
            "reason": "new_screen_without_context_verify",
        }
    context_type = str(context_cfg.get("type", "none") or "none").strip().lower()
    if context_type in {"", "none"}:
        return {
            "ok": True,
            "type": "none",
            "expected": "",
            "actual_text": "",
            "actual_announcement": "",
        }

    text_regex = str(context_cfg.get("text_regex", "") or "").strip()
    announcement_regex = str(context_cfg.get("announcement_regex", "") or "").strip()

    if context_type == "selected_bottom_tab":
        smart_requested_view_id = str(step.get("smart_nav_requested_view_id", "") or "").strip()
        smart_resolved_view_id = str(step.get("smart_nav_resolved_view_id", "") or "").strip()
        smart_actual_view_id = str(step.get("smart_nav_actual_view_id", "") or "").strip()
        smart_resolved_label = str(step.get("smart_nav_resolved_label", "") or "").strip()
        smart_actual_label = str(step.get("smart_nav_actual_label", "") or "").strip()
        smart_success = bool(step.get("smart_nav_success", False))
        smart_expected_norm = smart_requested_view_id.lower()
        smart_resolved_norm = smart_resolved_view_id.lower()
        smart_actual_norm = smart_actual_view_id.lower()
        smart_view_id_matched = bool(
            smart_success
            and smart_expected_norm
            and (smart_resolved_norm == smart_expected_norm or smart_actual_norm == smart_expected_norm)
        )
        if smart_view_id_matched:
            smart_actual_selected_text = smart_resolved_label or smart_actual_label
            smart_text_for_match = _expand_bottom_tab_aliases(smart_actual_selected_text)
            text_ok = True if not text_regex else _safe_regex_search(text_regex, smart_text_for_match)
            announcement_ok = (
                True if not announcement_regex else _safe_regex_search(announcement_regex, smart_text_for_match)
            )
            return {
                "ok": text_ok and announcement_ok,
                "type": context_type,
                "expected": " | ".join(part for part in [f"text={text_regex}" if text_regex else "", f"announcement={announcement_regex}" if announcement_regex else ""] if part),
                "actual_text": smart_actual_selected_text,
                "actual_announcement": smart_actual_selected_text,
                "actual_selected_text": smart_actual_selected_text,
                "actual_source": "smart_nav_result",
                "selected_candidates": [],
                "dump_source": "smart_nav_result",
                "lazy_dump_node_count": 0,
            }

        focus_node = step.get("focus_node", {})
        focus_node_map = focus_node if isinstance(focus_node, dict) else {}
        focus_view_id = str(
            focus_node_map.get("viewIdResourceName", "")
            or focus_node_map.get("resourceId", "")
            or step.get("focus_view_id", "")
            or ""
        ).strip()
        focus_selected_text = _build_focus_selected_text(step)
        focus_selected_text_for_match = _expand_bottom_tab_aliases(focus_selected_text)
        focus_has_selected_signal = bool(re.search(r"(selected|선택됨)", focus_selected_text_for_match, flags=re.IGNORECASE))
        focus_payload_strong = bool(step.get("get_focus_top_level_payload_sufficient", False)) or str(
            step.get("get_focus_final_payload_source", "") or ""
        ).strip().lower() in {"top_level", "fallback_dump"}
        focus_bottom_nav_hit = _is_bottom_nav_resource_id(focus_view_id, scenario_cfg)
        focus_text_ok = True if not text_regex else _safe_regex_search(text_regex, focus_selected_text_for_match)
        focus_announcement_ok = (
            True if not announcement_regex else _safe_regex_search(announcement_regex, focus_selected_text_for_match)
        )
        if (
            focus_payload_strong
            and focus_bottom_nav_hit
            and focus_has_selected_signal
            and focus_text_ok
            and focus_announcement_ok
        ):
            expected_parts = []
            if text_regex:
                expected_parts.append(f"text={text_regex}")
            if announcement_regex:
                expected_parts.append(f"announcement={announcement_regex}")
            expected_pattern = " | ".join(expected_parts)
            log(
                f"[CONTEXT][selected_tab_fast_path] ok=True view_id='{focus_view_id}' source='focus_payload'",
                level="DEBUG",
            )
            return {
                "ok": True,
                "type": context_type,
                "expected": expected_pattern,
                "actual_text": focus_selected_text,
                "actual_announcement": focus_selected_text,
                "actual_selected_text": focus_selected_text,
                "actual_source": "focus_payload_fast_path",
                "selected_candidates": [],
                "dump_source": "focus_payload",
                "lazy_dump_node_count": 0,
            }

        nodes = step.get("dump_tree_nodes", [])
        dump_source = "step_cache"
        lazy_dump_node_count = 0
        if not isinstance(nodes, list) or not nodes:
            if client and dev:
                lazy_nodes = client.dump_tree(dev=dev)
                if isinstance(lazy_nodes, list):
                    nodes = lazy_nodes
                    step["dump_tree_nodes"] = lazy_nodes
                    lazy_dump_node_count = len(lazy_nodes)
                    dump_source = "lazy_dump"
                else:
                    nodes = []
        selected_candidates: list[str] = []
        selected_values: list[str] = []
        fallback_values: list[str] = []
        selected_candidate_debug_rows: list[dict[str, str]] = []
        tab_like_candidate_debug_rows: list[dict[str, str]] = []
        tab_like_candidate_eval_rows: list[dict[str, Any]] = []
        tab_like_fallback_values: list[str] = []
        actual_source = "none"

        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            text = str(node.get("text", "") or "").strip()
            description = str(node.get("contentDescription", "") or "").strip()
            announcement = str(node.get("talkbackLabel", "") or "").strip()
            view_id = str(node.get("viewIdResourceName", "") or "").strip()
            bounds = str(node.get("boundsInScreen", "") or "").strip()
            selected_raw = node.get("selected")
            selected_state = bool(selected_raw) if not isinstance(selected_raw, str) else selected_raw.strip().lower() == "true"
            combined = ", ".join(part for part in [description, text] if part).strip()
            if not combined:
                combined = announcement
            marker = f"text='{text}' desc='{description}' selected={selected_state} viewId='{view_id}' bounds='{bounds}'"
            selected_candidates.append(marker)
            is_main_bottom_nav_candidate = bool(
                _is_bottom_nav_resource_id(view_id, scenario_cfg)
            )
            if is_main_bottom_nav_candidate and combined:
                fallback_values.append(combined)
            if is_main_bottom_nav_candidate:
                eval_text = _expand_bottom_tab_aliases(combined or marker)
                text_matched = True if not text_regex else _safe_regex_search(text_regex, eval_text)
                announcement_matched = True if not announcement_regex else _safe_regex_search(announcement_regex, eval_text)
                tab_like_candidate_debug_rows.append(
                    {
                        "text": text,
                        "announcement": announcement,
                        "resource_id": view_id,
                    }
                )
                tab_like_candidate_eval_rows.append(
                    {
                        "text": text,
                        "resource_id": view_id,
                        "selected": selected_state,
                        "matched": bool(text_matched and announcement_matched),
                    }
                )
                if combined:
                    tab_like_fallback_values.append(combined)
            if is_main_bottom_nav_candidate and (
                selected_state or re.search(r"(selected|선택됨)", combined or "", flags=re.IGNORECASE)
            ):
                selected_values.append(combined or marker)
                selected_candidate_debug_rows.append(
                    {
                        "text": text,
                        "announcement": announcement,
                        "resource_id": view_id,
                        "bounds": bounds,
                    }
                )

        actual_selected_text = selected_values[0] if selected_values else ""
        if actual_selected_text:
            actual_source = "selected_candidate"
        actual_selected_text_for_match = _expand_bottom_tab_aliases(actual_selected_text)
        actual_text = actual_selected_text
        actual_announcement = actual_selected_text

        # selected_bottom_tab은 dump 기반 selected 후보에서만 판정한다.
        text_ok = True if not text_regex else _safe_regex_search(text_regex, actual_selected_text_for_match)
        announcement_ok = (
            True if not announcement_regex else _safe_regex_search(announcement_regex, actual_selected_text_for_match)
        )
        ok = text_ok and announcement_ok

        if not actual_selected_text and fallback_values:
            actual_selected_text = fallback_values[0]
            actual_text = actual_selected_text
            actual_announcement = actual_selected_text
            actual_selected_text_for_match = _expand_bottom_tab_aliases(actual_selected_text)
            actual_source = "global_fallback"
            if tab_like_fallback_values and fallback_values[0] == tab_like_fallback_values[0]:
                actual_source = "tab_like_candidate"
            text_ok = True if not text_regex else _safe_regex_search(text_regex, actual_selected_text_for_match)
            announcement_ok = (
                True
                if not announcement_regex
                else _safe_regex_search(announcement_regex, actual_selected_text_for_match)
            )
            ok = text_ok and announcement_ok

        dump_node_count = len(nodes) if isinstance(nodes, list) else 0
        tab_like_count = len(tab_like_candidate_debug_rows)
        selected_count = len(selected_candidate_debug_rows)
        log(
            f"[CONTEXT][debug] dump_nodes={dump_node_count} tab_like_candidates={tab_like_count} "
            f"selected_candidates={selected_count} source='{dump_source}' lazy_dump_nodes={lazy_dump_node_count}",
            level="DEBUG",
        )
        log(
            f"[CONTEXT][debug] actual_source='{actual_source}' actual='{actual_selected_text}'",
            level="DEBUG",
        )
        log(
            f"[FOCUS][debug] source='{step.get('get_focus_final_payload_source', 'none')}' "
            f"fallback_nodes_reused={str(step.get('step_dump_tree_reason', '') == 'fallback_nodes_reused')} "
            f"get_focus_success_false_top_level_dump_attempted={bool(step.get('get_focus_success_false_top_level_dump_attempted', False))} "
            f"get_focus_success_false_top_level_dump_found={bool(step.get('get_focus_success_false_top_level_dump_found', False))} "
            f"final_payload_source='{step.get('get_focus_final_payload_source', 'none')}'",
            level="DEBUG",
        )
        if _should_log("DEBUG"):
            for idx, candidate in enumerate(selected_candidate_debug_rows):
                log(
                    f"[CONTEXT][debug] selected_candidate[{idx}] text='{candidate.get('text', '')}' "
                    f"announcement='{candidate.get('announcement', '')}' "
                    f"resource_id='{candidate.get('resource_id', '')}' "
                    f"bounds='{candidate.get('bounds', '')}'",
                    level="DEBUG",
                )
            if selected_count == 0:
                log(f"[CONTEXT][debug] tab_like_candidates={tab_like_count}", level="DEBUG")
                for idx, candidate in enumerate(tab_like_candidate_debug_rows):
                    log(
                        f"[CONTEXT][debug] tab_like_candidate[{idx}] text='{candidate.get('text', '')}' "
                        f"announcement='{candidate.get('announcement', '')}' "
                        f"resource_id='{candidate.get('resource_id', '')}'",
                        level="DEBUG",
                    )

        expected_parts = []
        if text_regex:
            expected_parts.append(f"text={text_regex}")
        if announcement_regex:
            expected_parts.append(f"announcement={announcement_regex}")
        expected_pattern = " | ".join(expected_parts)
        matched_by = "none"
        if ok:
            if actual_source == "selected_candidate":
                matched_by = "selected_values[0]"
            elif actual_source in {"global_fallback", "tab_like_candidate"}:
                matched_by = "fallback_values[0]"
            else:
                matched_by = "actual_selected_text"
        log(
            f"[TRACE][context_selected_tab] ok={ok} actual_source='{actual_source}' "
            f"actual='{actual_selected_text}' expected='{expected_pattern}' matched_by='{matched_by}' "
            f"selected_values={selected_values} fallback_values={fallback_values}",
            level="DEBUG",
        )
        if not ok:
            verify_reason = "regex_mismatch"
            if not tab_like_candidate_eval_rows:
                verify_reason = "no_bottom_nav_candidates"
            elif not selected_values:
                verify_reason = "selected_candidate_missing"
            elif not text_ok:
                verify_reason = "text_regex_mismatch"
            elif not announcement_ok:
                verify_reason = "announcement_regex_mismatch"
            expected_id_hint = smart_requested_view_id or smart_resolved_view_id or smart_actual_view_id
            candidate_summary = "; ".join(
                [
                    (
                        f"text='{str(candidate.get('text', '') or '').strip()}' "
                        f"res_id='{str(candidate.get('resource_id', '') or '').strip()}' "
                        f"selected={str(bool(candidate.get('selected', False))).lower()} "
                        f"matched={str(bool(candidate.get('matched', False))).lower()}"
                    )
                    for candidate in tab_like_candidate_eval_rows[:5]
                ]
            )
            log(
                "[TAB][verify_debug] "
                f"expected_view_id='{expected_id_hint}' text_regex='{text_regex}' announcement_regex='{announcement_regex}' "
                f"actual='{actual_selected_text}' reason='{verify_reason}' "
                f"candidates='{candidate_summary or 'none'}'"
            )

        return {
            "ok": ok,
            "type": context_type,
            "expected": expected_pattern,
            "actual_text": actual_text,
            "actual_announcement": actual_announcement,
            "actual_selected_text": actual_selected_text,
            "actual_source": actual_source,
            "selected_candidates": selected_candidates,
            "dump_source": dump_source,
            "lazy_dump_node_count": lazy_dump_node_count,
        }

    actual_text = str(step.get("visible_label", "") or "").strip()
    actual_announcement = str(step.get("merged_announcement", "") or "").strip()
    if context_type == "screen_text":
        text_ok = True if not text_regex else _safe_regex_search(text_regex, actual_text)
        announcement_ok = True
    elif context_type == "screen_announcement":
        text_ok = True
        announcement_ok = True if not announcement_regex else _safe_regex_search(announcement_regex, actual_announcement)
    elif context_type == "focused_anchor":
        focus_view_id = str(step.get("focus_view_id", "") or "").strip()
        view_id_regex = str(context_cfg.get("view_id_regex", "") or "").strip()
        text_ok = True if not text_regex else _safe_regex_search(text_regex, actual_text)
        announcement_ok = True if not announcement_regex else _safe_regex_search(announcement_regex, actual_announcement)
        view_id_ok = True if not view_id_regex else _safe_regex_search(view_id_regex, focus_view_id)
        ok = text_ok and announcement_ok and view_id_ok
        expected_parts = []
        if text_regex:
            expected_parts.append(f"text={text_regex}")
        if announcement_regex:
            expected_parts.append(f"announcement={announcement_regex}")
        if view_id_regex:
            expected_parts.append(f"view_id={view_id_regex}")
        return {
            "ok": ok,
            "type": context_type,
            "expected": " | ".join(expected_parts),
            "actual_text": actual_text,
            "actual_announcement": actual_announcement,
            "actual_view_id": focus_view_id,
        }
    else:
        text_ok = True if not text_regex else _safe_regex_search(text_regex, actual_text)
        announcement_ok = True if not announcement_regex else _safe_regex_search(announcement_regex, actual_announcement)
    ok = text_ok and announcement_ok

    expected_parts = []
    if text_regex:
        expected_parts.append(f"text={text_regex}")
    if announcement_regex:
        expected_parts.append(f"announcement={announcement_regex}")

    return {
        "ok": ok,
        "type": context_type,
        "expected": " | ".join(expected_parts),
        "actual_text": actual_text,
        "actual_announcement": actual_announcement,
    }
