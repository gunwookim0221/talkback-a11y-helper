from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from tb_runner import device_tab_logic

SCHEMA_VERSION = "plugin-discovery-v1"
DISCOVERY_CARD_VERSION = "phase5a-visible-discovery-v1"

CHROME_LABEL_PATTERNS = (
    r"(?i)^navigate\s+up$",
    r"(?i)^back$",
    r"(?i)^more\s+options$",
    r"(?i)^add$",
    r"(?i).*location.*",
    r"(?i).*qr\s*code.*",
    r"(?i)^home$",
    r"(?i)^devices$",
    r"(?i)^life$",
    r"(?i)^routines$",
    r"(?i)^menu$",
)

CHROME_RESOURCE_PATTERNS = (
    r"(?i)(toolbar|appbar|actionbar|bottom|tab|navigation)",
    r"(?i)menu_(favorites|devices|services|automations|more)",
    r"(?i)(home_button|add_menu_button|more_menu_button|tab_title|small_title_bar)",
)

LIFE_CARD_RESOURCE_PATTERNS = (
    r"(?i)(servicecard|preinstalledservicecard|card|container|item|layout|frame)",
)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_key(value: Any) -> str:
    lowered = _text(value).lower()
    lowered = re.sub(r"[^0-9a-z가-힣]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _slug(value: str) -> str:
    normalized = _normalize_key(value).replace(" ", "_")
    return normalized or "unknown"


def _safe_regex_search(pattern: str, value: str) -> bool:
    try:
        return bool(re.search(pattern, value or ""))
    except re.error:
        return False


def _is_chrome_label(label: str) -> bool:
    normalized = _text(label)
    if not normalized:
        return False
    return any(_safe_regex_search(pattern, normalized) for pattern in CHROME_LABEL_PATTERNS)


def _is_chrome_resource(resource_id: str, class_name: str) -> bool:
    blob = f"{resource_id} {class_name}"
    return any(_safe_regex_search(pattern, blob) for pattern in CHROME_RESOURCE_PATTERNS)


def _parse_bounds(value: Any) -> tuple[int, int, int, int] | None:
    text = _text(value)
    if not text:
        return None
    bracket_match = re.fullmatch(r"\[(\-?\d+),(\-?\d+)\]\[(\-?\d+),(\-?\d+)\]", text)
    if bracket_match:
        left, top, right, bottom = (int(part) for part in bracket_match.groups())
    else:
        parts = [part.strip() for part in text.split(",")]
        if len(parts) != 4 or not all(re.fullmatch(r"\-?\d+", part) for part in parts):
            return None
        left, top, right, bottom = (int(part) for part in parts)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _format_bounds(bounds: tuple[int, int, int, int] | None) -> str:
    if not bounds:
        return ""
    return f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"


def _node_label(node: dict[str, Any]) -> str:
    for key in ("text", "contentDescription", "content-desc", "content_desc", "talkbackLabel", "mergedLabel"):
        value = _text(node.get(key))
        if value:
            return value
    return ""


def _node_resource_id(node: dict[str, Any]) -> str:
    for key in ("viewIdResourceName", "resourceId", "resource-id", "resource_id", "id"):
        value = _text(node.get(key))
        if value:
            return value
    return ""


def _node_class_name(node: dict[str, Any]) -> str:
    for key in ("className", "class", "class_name"):
        value = _text(node.get(key))
        if value:
            return value
    return ""


def _node_bounds(node: dict[str, Any]) -> tuple[int, int, int, int] | None:
    return _parse_bounds(node.get("boundsInScreen") or node.get("bounds"))


def _is_visible(node: dict[str, Any]) -> bool:
    for key in ("visibleToUser", "visible-to-user", "isVisibleToUser"):
        if key not in node:
            continue
        value = node.get(key)
        if isinstance(value, str):
            return value.strip().lower() != "false"
        return bool(value)
    return True


def _walk_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = list(nodes)
    while stack:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        flattened.append(node)
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(child for child in children if isinstance(child, dict))
    return flattened


def parse_uiautomator_xml(xml_text: str) -> list[dict[str, Any]]:
    if not _text(xml_text):
        return []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    def parse_element(element: ET.Element) -> dict[str, Any]:
        attrs = element.attrib
        children = [parse_element(child) for child in list(element)]
        return {
            "text": _text(attrs.get("text")),
            "contentDescription": _text(attrs.get("content-desc") or attrs.get("contentDescription")),
            "viewIdResourceName": _text(attrs.get("resource-id") or attrs.get("resourceId")),
            "className": _text(attrs.get("class")),
            "boundsInScreen": _format_bounds(_parse_bounds(attrs.get("bounds"))),
            "clickable": str(attrs.get("clickable", "")).strip().lower() == "true",
            "focusable": str(attrs.get("focusable", "")).strip().lower() == "true",
            "visibleToUser": str(attrs.get("visible-to-user", "")).strip().lower() != "false",
            "children": children,
        }

    return [parse_element(child) for child in list(root)]


def build_known_plugin_index(tab_configs: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    known: dict[str, dict[str, str]] = {}
    for cfg in tab_configs:
        if not isinstance(cfg, dict):
            continue
        scenario_id = _text(cfg.get("scenario_id"))
        if not scenario_id:
            continue
        plugin_type = "life" if scenario_id.startswith("life_") else ("device" if scenario_id.startswith("device_") else "")
        if not plugin_type:
            continue
        entry = {"scenario_id": scenario_id, "type": plugin_type}
        if plugin_type == "device":
            for step in cfg.get("pre_navigation", []) if isinstance(cfg.get("pre_navigation"), list) else []:
                if not isinstance(step, dict):
                    continue
                labels = step.get("target_stable_labels", [])
                if isinstance(labels, str):
                    labels = [labels]
                for label in labels if isinstance(labels, list) else []:
                    key = _normalize_key(device_tab_logic.normalize_device_stable_label(str(label)))
                    if key:
                        known[f"device:{key}"] = entry
        else:
            scenario_label = scenario_id.removeprefix("life_").removesuffix("_plugin").replace("_", " ")
            if scenario_label:
                known[f"life:{_normalize_key(scenario_label)}"] = entry
            entry_match = cfg.get("entry_match", {})
            if isinstance(entry_match, dict):
                for pattern in entry_match.get("title_patterns", []) if isinstance(entry_match.get("title_patterns"), list) else []:
                    for label in _labels_from_regex_pattern(str(pattern)):
                        known[f"life:{_normalize_key(label)}"] = entry
    return known


def _labels_from_regex_pattern(pattern: str) -> list[str]:
    cleaned = pattern
    cleaned = re.sub(r"\(\?i\)", " ", cleaned)
    cleaned = re.sub(r"\\s\*|\\s\+", " ", cleaned)
    cleaned = re.sub(r"\\b", " ", cleaned)
    cleaned = re.sub(r"[\^\$\(\)\[\]\{\}\?\*\+\\]", " ", cleaned)
    parts = re.split(r"\|", cleaned)
    labels = []
    for part in parts:
        label = re.sub(r"[^0-9a-zA-Z가-힣& ]+", " ", part)
        label = _text(label)
        if 2 <= len(label) <= 40:
            labels.append(label)
    return labels


def _known_meta(plugin_type: str, stable_label: str, known_index: dict[str, dict[str, str]]) -> tuple[bool, str]:
    meta = known_index.get(f"{plugin_type}:{_normalize_key(stable_label)}", {})
    return bool(meta), str(meta.get("scenario_id", "") or "")


def discover_device_cards(
    nodes: list[dict[str, Any]],
    *,
    known_index: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    known_index = known_index or {}
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, card in enumerate(device_tab_logic.collect_visible_device_cards(nodes if isinstance(nodes, list) else [])):
        stable_label = device_tab_logic.normalize_device_stable_label(str(card.get("stable_label") or card.get("label") or ""))
        label = _text(card.get("label") or stable_label)
        key = _normalize_key(stable_label or label)
        if not key or key in seen:
            continue
        seen.add(key)
        known, scenario_id = _known_meta("device", stable_label or label, known_index)
        cards.append(
            {
                "id": f"device:{_slug(stable_label or label)}:{index}",
                "label": label,
                "stable_label": stable_label or label,
                "type": "device",
                "confidence": "high",
                "source": "helper",
                "bounds": _text(card.get("bounds")),
                "resource_id": _text(card.get("resource_id") or card.get("rid")),
                "known": known,
                "existing_scenario_id": scenario_id,
            }
        )
    return cards


def _is_title_like(label: str) -> bool:
    if not label or _is_chrome_label(label):
        return False
    normalized = _normalize_key(label)
    if not normalized:
        return False
    tokens = normalized.split()
    if len(tokens) > 4 or len(label) > 48:
        return False
    if re.search(r"[,.;:!?]", label):
        return False
    return True


def _descendant_labels(node: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    children = node.get("children")
    if not isinstance(children, list):
        return labels
    for child in _walk_nodes([child for child in children if isinstance(child, dict)]):
        label = _node_label(child)
        if label:
            labels.append(label)
    return labels


def _is_life_card_like(node: dict[str, Any], viewport_area: int) -> bool:
    if not _is_visible(node):
        return False
    bounds = _node_bounds(node)
    if not bounds:
        return False
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    area = max(1, width * height)
    if area < max(5000, int(viewport_area * 0.003)) or area > int(viewport_area * 0.85):
        return False
    resource_id = _node_resource_id(node)
    class_name = _node_class_name(node)
    label = _node_label(node)
    if _is_chrome_label(label) or _is_chrome_resource(resource_id, class_name):
        return False
    blob = f"{resource_id} {class_name}"
    has_card_hint = any(_safe_regex_search(pattern, blob) for pattern in LIFE_CARD_RESOURCE_PATTERNS)
    has_title = any(_is_title_like(descendant) for descendant in [label, *_descendant_labels(node)])
    return bool(has_card_hint and has_title)


def discover_life_cards_from_nodes(
    nodes: list[dict[str, Any]],
    *,
    known_index: dict[str, dict[str, str]] | None = None,
    source: str = "xml",
) -> list[dict[str, Any]]:
    known_index = known_index or {}
    flat = _walk_nodes(nodes if isinstance(nodes, list) else [])
    bounds_list = [_node_bounds(node) for node in flat]
    bounds_list = [bounds for bounds in bounds_list if bounds]
    viewport_area = 1080 * 1920
    if bounds_list:
        left = min(bounds[0] for bounds in bounds_list)
        top = min(bounds[1] for bounds in bounds_list)
        right = max(bounds[2] for bounds in bounds_list)
        bottom = max(bounds[3] for bounds in bounds_list)
        viewport_area = max(1, (right - left) * (bottom - top))

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, node in enumerate(flat):
        if not _is_life_card_like(node, viewport_area):
            continue
        own_label = _node_label(node)
        descendants = _descendant_labels(node)
        title = next((label for label in [own_label, *descendants] if _is_title_like(label)), "")
        if not title:
            continue
        stable_label = title
        key = _normalize_key(stable_label)
        if not key or key in seen:
            continue
        seen.add(key)
        resource_id = _node_resource_id(node)
        class_name = _node_class_name(node)
        known, scenario_id = _known_meta("life", stable_label, known_index)
        confidence = "high" if title in descendants else "medium"
        if own_label and not descendants:
            confidence = "low"
        cards.append(
            {
                "id": f"life:{_slug(stable_label)}:{index}",
                "label": title,
                "stable_label": stable_label,
                "type": "life",
                "confidence": confidence,
                "source": source,
                "bounds": _format_bounds(_node_bounds(node)),
                "resource_id": resource_id,
                "known": known,
                "existing_scenario_id": scenario_id,
                "class_name": class_name,
            }
        )
    return cards


def discover_life_cards_from_xml(
    xml_text: str,
    *,
    known_index: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    return discover_life_cards_from_nodes(parse_uiautomator_xml(xml_text), known_index=known_index, source="xml")


def build_discovery_response(
    *,
    cards: list[dict[str, Any]],
    warnings: list[str] | None = None,
    ok: bool = True,
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "schema_version": SCHEMA_VERSION,
        "cards": cards,
        "diagnostics": {
            "warnings": list(warnings or []),
        },
    }
