from __future__ import annotations

import re
from typing import Any

from talkback_lib import A11yAdbClient
from tb_runner import device_tab_logic
from tb_runner.plugin_card_discovery import (
    _is_chrome_label,
    _node_bounds,
    _node_class_name,
    _node_label,
    _node_resource_id,
    _normalize_key,
    _parse_bounds,
    _text,
    build_known_plugin_index,
    discover_device_cards,
    discover_life_cards_from_nodes,
    parse_uiautomator_xml,
)
from tb_runner.scenario_config import TAB_CONFIGS

PROBE_SCHEMA_VERSION = "plugin-probe-v1"
FAILURE_REASONS = {
    "invalid_request",
    "run_in_progress",
    "helper_unavailable",
    "xml_unavailable",
    "card_not_visible_anymore",
    "entry_target_missing",
    "tap_failed",
    "transition_not_confirmed",
    "still_on_shell_screen",
    "wrong_plugin_open_suspected",
    "focus_collection_failed",
    "probe_step_timeout",
    "probe_step_no_progress",
    "overlay_blocked_observation",
    "collector_partial_only",
}


def _failure_response(reason: str, warnings: list[str] | None = None) -> dict[str, Any]:
    normalized = reason if reason in FAILURE_REASONS else "collector_partial_only"
    return {
        "ok": False,
        "schema_version": PROBE_SCHEMA_VERSION,
        "probe_status": "failed",
        "entry": {
            "attempted": False,
            "method": "",
            "open_confirmed": False,
            "reason": normalized,
        },
        "summary": {
            "plugin_open_verified_candidate": False,
            "suggested_entry_method": "",
            "suggested_scenario_type": "content",
        },
        "seed": {
            "verify_tokens": [],
            "negative_verify_tokens": [],
            "headers": [],
            "local_tabs": [],
            "representative_cards": [],
            "overlay_hints": [],
            "context_verify_text_candidates": [],
            "entry_candidate": {"action": "", "target_seed": ""},
        },
        "artifacts": {
            "helper_nodes_captured": False,
            "xml_captured": False,
            "focus_steps": 0,
        },
        "diagnostics": {
            "warnings": list(warnings or []),
            "failure_reason": normalized,
        },
    }


def _capture_helper_nodes(client: A11yAdbClient, serial: str | None) -> tuple[list[dict[str, Any]], str]:
    dump_tree_fn = getattr(client, "dump_tree", None)
    if not callable(dump_tree_fn):
        return [], "helper_unavailable"
    try:
        payload = dump_tree_fn(dev=serial)
    except Exception:
        return [], "helper_unavailable"
    if isinstance(payload, list):
        return [node for node in payload if isinstance(node, dict)], ""
    if isinstance(payload, dict) and isinstance(payload.get("nodes"), list):
        return [node for node in payload["nodes"] if isinstance(node, dict)], ""
    return [], ""


def _capture_window_xml(client: A11yAdbClient, serial: str | None) -> tuple[str, str]:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return "", "xml_unavailable"
    remote_xml = "/sdcard/window_dump_plugin_probe.xml"
    try:
        run_fn(["shell", "uiautomator", "dump", remote_xml], dev=serial)
        xml_text = str(run_fn(["shell", "cat", remote_xml], dev=serial) or "")
        return xml_text, "" if xml_text.strip() else "xml_unavailable"
    except Exception:
        return "", "xml_unavailable"
    finally:
        try:
            run_fn(["shell", "rm", "-f", remote_xml], dev=serial)
        except Exception:
            pass


def _flatten_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = [node for node in nodes if isinstance(node, dict)]
    while queue:
        node = queue.pop(0)
        flattened.append(node)
        children = node.get("children")
        if isinstance(children, list):
            queue.extend(child for child in children if isinstance(child, dict))
    return flattened


def _record_from_node(node: dict[str, Any], *, source: str) -> dict[str, Any]:
    bounds = _node_bounds(node)
    return {
        "label": _node_label(node),
        "resource_id": _node_resource_id(node),
        "class_name": _node_class_name(node),
        "bounds": bounds,
        "source": source,
        "clickable": bool(node.get("clickable") or node.get("effectiveClickable")),
        "focusable": bool(node.get("focusable")),
    }


def _collect_records(helper_nodes: list[dict[str, Any]], xml_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = [_record_from_node(node, source="helper") for node in _flatten_nodes(helper_nodes)]
    records.extend(_record_from_node(node, source="xml") for node in _flatten_nodes(xml_nodes))
    return records


def _meaningful_label(label: str) -> bool:
    normalized = _text(label)
    if not normalized or _is_chrome_label(normalized):
        return False
    return len(normalized) >= 2


def _context_regex_from_label(label: str) -> str:
    tokens = [re.escape(token) for token in re.split(r"\s+", _text(label)) if token]
    if not tokens:
        return ""
    return rf"(?i).*{r'\s*'.join(tokens)}.*"


def _extract_headers(records: list[dict[str, Any]], stable_label: str) -> list[str]:
    bounds_values = [record["bounds"] for record in records if record.get("bounds")]
    viewport_bottom = max((bounds[3] for bounds in bounds_values), default=1920)
    cutoff = int(viewport_bottom * 0.28)
    headers: list[str] = []
    seen: set[str] = set()
    candidates = [stable_label] + [record.get("label", "") for record in records if record.get("bounds") and record["bounds"][1] <= cutoff]
    for candidate in candidates:
        label = _text(candidate)
        key = _normalize_key(label)
        if not _meaningful_label(label) or not key or key in seen:
            continue
        if len(label.split()) > 5 or len(label) > 48:
            continue
        seen.add(key)
        headers.append(label)
    return headers[:5]


def _extract_local_tabs(records: list[dict[str, Any]]) -> list[str]:
    candidates = []
    for record in records:
        label = _text(record.get("label"))
        bounds = record.get("bounds")
        if not _meaningful_label(label) or not bounds:
            continue
        if len(label.split()) > 3 or len(label) > 24:
            continue
        if not (record.get("clickable") or record.get("focusable")):
            continue
        candidates.append((bounds[1], label))
    if not candidates:
        return []
    y_clusters: dict[int, list[str]] = {}
    for top, label in candidates:
        bucket = int(round(top / 80.0) * 80)
        y_clusters.setdefault(bucket, []).append(label)
    best_cluster = max(y_clusters.values(), key=len, default=[])
    unique: list[str] = []
    seen: set[str] = set()
    for label in best_cluster:
        key = _normalize_key(label)
        if key and key not in seen:
            seen.add(key)
            unique.append(label)
    if 2 <= len(unique) <= 5:
        return unique
    return []


def _extract_overlay_hints(records: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()
    for record in records:
        label = _text(record.get("label"))
        resource_id = _text(record.get("resource_id"))
        class_name = _text(record.get("class_name"))
        blob = f"{label} {resource_id} {class_name}".lower()
        if not blob:
            continue
        if any(token in blob for token in ("more options", "dialog", "modal", "sheet", "popup")):
            key = _normalize_key(label or resource_id or class_name)
            if key and key not in seen:
                seen.add(key)
                hints.append(label or resource_id or class_name)
    return hints[:5]


def _extract_representative_cards(
    card_type: str,
    helper_nodes: list[dict[str, Any]],
    xml_nodes: list[dict[str, Any]],
    stable_label: str,
) -> list[str]:
    if card_type == "device":
        cards = discover_device_cards(helper_nodes)
    else:
        cards = discover_life_cards_from_nodes(xml_nodes, source="xml")
    results: list[str] = []
    seen: set[str] = set()
    stable_key = _normalize_key(stable_label)
    for card in cards:
        label = _text(card.get("stable_label") or card.get("label"))
        key = _normalize_key(label)
        if not key or key == stable_key or key in seen:
            continue
        seen.add(key)
        results.append(label)
    return results[:5]


def _extract_verify_tokens(
    stable_label: str,
    headers: list[str],
    rows: list[dict[str, Any]],
) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for candidate in [stable_label, *headers]:
        label = _text(candidate)
        key = _normalize_key(label)
        if label and key and key not in seen:
            seen.add(key)
            tokens.append(label)
    for row in rows:
        for candidate in (row.get("visible_label"), row.get("merged_announcement")):
            label = _text(candidate)
            key = _normalize_key(label)
            if not _meaningful_label(label) or not key or key in seen:
                continue
            if len(label.split()) > 5 or len(label) > 48:
                continue
            seen.add(key)
            tokens.append(label)
    return tokens[:6]


def _wrong_plugin_open_suspected(
    stable_label: str,
    headers: list[str],
    known_index: dict[str, dict[str, str]],
    card_type: str,
) -> bool:
    current_key = _normalize_key(stable_label)
    for header in headers:
        key = _normalize_key(header)
        if not key or key == current_key:
            continue
        if f"{card_type}:{key}" in known_index:
            return True
    return False


def _has_stable_label_anchor(stable_label: str, headers: list[str], rows: list[dict[str, Any]]) -> bool:
    stable_key = _normalize_key(stable_label)
    if not stable_key:
        return False
    for candidate in headers:
        if _normalize_key(candidate) == stable_key:
            return True
    for row in rows:
        for candidate in (row.get("visible_label"), row.get("merged_announcement")):
            if _normalize_key(candidate) == stable_key:
                return True
    return False


def _still_on_shell_screen(stable_label: str, headers: list[str], rows: list[dict[str, Any]]) -> bool:
    if _has_stable_label_anchor(stable_label, headers, rows):
        return False
    header_blob = " ".join(_text(header) for header in headers).lower()
    if header_blob and any(token in header_blob for token in ("home", "devices", "life", "routines", "menu", "location", "qr code")):
        return True
    if not any(_text(row.get("visible_label") or row.get("merged_announcement")) for row in rows):
        return True
    return not bool(headers)


def _observe_probe_steps(
    client: A11yAdbClient,
    serial: str | None,
    *,
    max_probe_steps: int,
    include_helper_dump: bool,
    include_xml: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    collect_focus_step = getattr(client, "collect_focus_step", None)
    if callable(collect_focus_step):
        for step_index in range(max(1, max_probe_steps)):
            move = step_index > 0
            try:
                row = collect_focus_step(
                    dev=serial,
                    step_index=step_index,
                    move=move,
                    direction="next",
                    wait_seconds=0.8,
                    announcement_wait_seconds=0.8,
                    focus_wait_seconds=0.8,
                    allow_get_focus_fallback_dump=True,
                    allow_step_dump=include_helper_dump,
                    get_focus_mode="fast",
                )
            except Exception:
                if step_index == 0:
                    return [], [], [], ["focus_collection_failed"]
                warnings.append("probe_step_timeout")
                break
            rows.append(row if isinstance(row, dict) else {})
    else:
        return [], [], [], ["focus_collection_failed"]

    helper_nodes: list[dict[str, Any]] = []
    xml_nodes: list[dict[str, Any]] = []
    helper_reason = ""
    xml_reason = ""
    if include_helper_dump:
        helper_nodes, helper_reason = _capture_helper_nodes(client, serial)
    if include_xml:
        xml_text, xml_reason = _capture_window_xml(client, serial)
        xml_nodes = parse_uiautomator_xml(xml_text) if xml_text else []
    if helper_reason:
        warnings.append(helper_reason)
    if xml_reason:
        warnings.append(xml_reason)
    return rows, helper_nodes, xml_nodes, warnings


def _attempt_life_entry(client: A11yAdbClient, serial: str | None, card: dict[str, Any]) -> tuple[bool, str]:
    bounds = _parse_bounds(card.get("bounds"))
    if bounds:
        center_x = int((bounds[0] + bounds[2]) / 2)
        center_y = int((bounds[1] + bounds[3]) / 2)
        tap_ok = bool(getattr(client, "tap_xy_adb")(dev=serial, x=center_x, y=center_y)) if callable(getattr(client, "tap_xy_adb", None)) else False
        return tap_ok, "life_bounds_tap"
    resource_id = _text(card.get("resource_id"))
    if resource_id and callable(getattr(client, "tap_bounds_center_adb", None)):
        return bool(client.tap_bounds_center_adb(dev=serial, name=resource_id, type_="r")), "life_resource_tap"
    return False, "life_bounds_tap"


def _attempt_device_entry(
    client: A11yAdbClient,
    serial: str | None,
    card: dict[str, Any],
    helper_nodes: list[dict[str, Any]],
) -> tuple[bool, str, str]:
    if not helper_nodes:
        return False, "device_visible_card_tap", "helper_unavailable"
    labels = [card.get("stable_label"), card.get("label")]
    labels = [str(label) for label in labels if _text(label)]
    matched = device_tab_logic.find_device_card_by_stable_label(helper_nodes, labels)
    if not isinstance(matched, dict):
        return False, "device_visible_card_tap", "card_not_visible_anymore"
    bounds = _parse_bounds(matched.get("bounds"))
    if not bounds:
        return False, "device_visible_card_tap", "entry_target_missing"
    avoid_bounds = [item.get("bounds") for item in device_tab_logic.collect_device_card_tap_avoid_bounds(helper_nodes)]
    safe_point = device_tab_logic.compute_safe_device_card_tap_point(bounds, avoid_bounds)
    if not safe_point:
        center_x = int((bounds[0] + bounds[2]) / 2)
        center_y = int((bounds[1] + bounds[3]) / 2)
    else:
        center_x = int(safe_point.get("x", 0) or 0)
        center_y = int(safe_point.get("y", 0) or 0)
    tap_fn = getattr(client, "tap_xy_adb", None)
    if not callable(tap_fn):
        return False, "device_visible_card_tap", "tap_failed"
    if not bool(tap_fn(dev=serial, x=center_x, y=center_y)):
        return False, "device_visible_card_tap", "tap_failed"
    return True, "device_visible_card_tap", ""


def start_plugin_probe(
    request: dict[str, Any],
    *,
    client: A11yAdbClient | None = None,
    known_index: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    card = request.get("card") if isinstance(request, dict) else None
    if not isinstance(card, dict):
        return _failure_response("invalid_request")
    card_type = _text(card.get("type")).lower()
    if card_type not in {"life", "device"}:
        return _failure_response("invalid_request")
    stable_label = _text(card.get("stable_label"))
    label = _text(card.get("label"))
    if not stable_label or not label:
        return _failure_response("invalid_request")
    if not _text(card.get("bounds")) and not _text(card.get("resource_id")):
        return _failure_response("invalid_request")

    max_probe_steps = int(request.get("max_probe_steps", 3) or 3)
    max_probe_steps = min(5, max(3, max_probe_steps))
    include_xml = bool(request.get("include_xml", True))
    include_helper_dump = bool(request.get("include_helper_dump", True))
    serial = request.get("serial")
    client = client or A11yAdbClient()
    known_index = known_index or build_known_plugin_index(TAB_CONFIGS)
    warnings: list[str] = []

    helper_nodes: list[dict[str, Any]] = []
    if card_type == "device":
        helper_nodes, helper_reason = _capture_helper_nodes(client, serial)
        if helper_reason:
            return _failure_response(helper_reason)
        attempted, method, failure_reason = _attempt_device_entry(client, serial, card, helper_nodes)
        if not attempted:
            return _failure_response(failure_reason or "tap_failed")
    else:
        attempted, method = _attempt_life_entry(client, serial, card)
        if not attempted:
            return _failure_response("tap_failed")

    rows, observed_helper_nodes, xml_nodes, observation_warnings = _observe_probe_steps(
        client,
        serial,
        max_probe_steps=max_probe_steps,
        include_helper_dump=include_helper_dump,
        include_xml=include_xml,
    )
    warnings.extend(observation_warnings)
    if not rows:
        return _failure_response("focus_collection_failed", warnings=warnings)
    if card_type == "device" and observed_helper_nodes:
        helper_nodes = observed_helper_nodes

    records = _collect_records(helper_nodes or observed_helper_nodes, xml_nodes)
    headers = _extract_headers(records, stable_label)
    local_tabs = _extract_local_tabs(records)
    overlay_hints = _extract_overlay_hints(records)
    representative_cards = _extract_representative_cards(card_type, helper_nodes or observed_helper_nodes, xml_nodes, stable_label)
    verify_tokens = _extract_verify_tokens(stable_label, headers, rows)
    context_regex = _context_regex_from_label(stable_label)

    wrong_plugin = _wrong_plugin_open_suspected(stable_label, headers, known_index, card_type)
    shell_screen = _still_on_shell_screen(stable_label, headers, rows)
    open_confirmed = not shell_screen and not wrong_plugin
    failure_reason = ""
    probe_status = "opened_partial_observed"
    if wrong_plugin:
        failure_reason = "wrong_plugin_open_suspected"
        probe_status = "failed"
    elif shell_screen:
        if any(_text(row.get("visible_label") or row.get("merged_announcement")) for row in rows):
            failure_reason = "collector_partial_only"
            probe_status = "collector_partial_only"
        else:
            failure_reason = "transition_not_confirmed"
            probe_status = "failed"
    elif any(warning == "probe_step_timeout" for warning in warnings):
        probe_status = "collector_partial_only"
        failure_reason = "collector_partial_only"

    suggested_entry_method = "xml_scroll_search_tap" if card_type == "life" else "enter_device_card_plugin"
    entry_reason = "transition_or_anchor_seen" if open_confirmed else failure_reason or "transition_not_confirmed"
    if probe_status == "failed":
        ok = False
    else:
        ok = True

    return {
        "ok": ok,
        "schema_version": PROBE_SCHEMA_VERSION,
        "probe_status": probe_status,
        "entry": {
            "attempted": True,
            "method": method,
            "open_confirmed": open_confirmed,
            "reason": entry_reason,
        },
        "summary": {
            "plugin_open_verified_candidate": open_confirmed,
            "suggested_entry_method": suggested_entry_method,
            "suggested_scenario_type": "content",
        },
        "seed": {
            "verify_tokens": verify_tokens,
            "negative_verify_tokens": [],
            "headers": headers,
            "local_tabs": local_tabs,
            "representative_cards": representative_cards,
            "overlay_hints": overlay_hints,
            "context_verify_text_candidates": [context_regex] if context_regex else [],
            "entry_candidate": {
                "action": suggested_entry_method,
                "target_seed": stable_label,
            },
        },
        "artifacts": {
            "helper_nodes_captured": bool(helper_nodes or observed_helper_nodes),
            "xml_captured": bool(xml_nodes),
            "focus_steps": len(rows),
        },
        "diagnostics": {
            "warnings": warnings,
            "failure_reason": failure_reason,
        },
    }
