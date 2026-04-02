import re
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner.logging_utils import _should_log, log
from tb_runner.utils import _safe_regex_search


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
        tab_like_fallback_values: list[str] = []
        actual_source = "none"

        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            text = str(node.get("text", "") or "").strip()
            description = str(node.get("contentDescription", "") or "").strip()
            announcement = str(node.get("talkbackLabel", "") or "").strip()
            view_id = str(node.get("viewIdResourceName", "") or "").strip()
            class_name = str(node.get("className", "") or "").strip()
            bounds = str(node.get("boundsInScreen", "") or "").strip()
            selected_raw = node.get("selected")
            selected_state = bool(selected_raw) if not isinstance(selected_raw, str) else selected_raw.strip().lower() == "true"
            combined = ", ".join(part for part in [description, text] if part).strip()
            if not combined:
                combined = announcement
            marker = f"text='{text}' desc='{description}' selected={selected_state} viewId='{view_id}' bounds='{bounds}'"
            selected_candidates.append(marker)
            if combined:
                fallback_values.append(combined)
            tab_like = bool(
                re.search(r"(menu_|bottom|tab|navigation)", f"{view_id} {class_name}", flags=re.IGNORECASE)
                or re.search(r"(home|devices|life|routines|menu|selected|선택됨)", f"{text} {description} {announcement}", flags=re.IGNORECASE)
            )
            if tab_like:
                tab_like_candidate_debug_rows.append(
                    {
                        "text": text,
                        "announcement": announcement,
                        "resource_id": view_id,
                    }
                )
                if combined:
                    tab_like_fallback_values.append(combined)
            if selected_state or re.search(r"(selected|선택됨)", combined or "", flags=re.IGNORECASE):
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
        actual_text = actual_selected_text
        actual_announcement = actual_selected_text

        # selected_bottom_tab은 dump 기반 selected 후보에서만 판정한다.
        text_ok = True if not text_regex else _safe_regex_search(text_regex, actual_selected_text)
        announcement_ok = True if not announcement_regex else _safe_regex_search(announcement_regex, actual_selected_text)
        ok = text_ok and announcement_ok

        if not actual_selected_text and fallback_values:
            actual_selected_text = fallback_values[0]
            actual_text = actual_selected_text
            actual_announcement = actual_selected_text
            actual_source = "global_fallback"
            if tab_like_fallback_values and fallback_values[0] == tab_like_fallback_values[0]:
                actual_source = "tab_like_candidate"

        dump_node_count = len(nodes) if isinstance(nodes, list) else 0
        tab_like_count = len(tab_like_candidate_debug_rows)
        selected_count = len(selected_candidate_debug_rows)
        log(
            f"[CONTEXT][debug] dump_nodes={dump_node_count} tab_like_candidates={tab_like_count} "
            f"selected_candidates={selected_count} source='{dump_source}' lazy_dump_nodes={lazy_dump_node_count}"
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
            f"final_payload_source='{step.get('get_focus_final_payload_source', 'none')}'"
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

        return {
            "ok": ok,
            "type": context_type,
            "expected": " | ".join(expected_parts),
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
