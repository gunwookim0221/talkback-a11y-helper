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

LIFE_POSITIVE_RESOURCE_PATTERNS = (
    r"(?i)(preinstalledservicecard|servicecard(?:body|container)?|llcard)",
    r"(?i)(containername(?:layout)?|containerheaderlayout|containerbodylayout)",
    r"(?i)(tvheadertitle)",
    r"(?i)(fme_title_layout|fme_map_touch_layer|fme_map_bubble_layout|map_area)",
    r"(?i)(title_view|title_service_name|camera_description|container_name)",
)

LIFE_EXCLUDED_LABEL_PATTERNS = (
    r"(?i)^search$",
    r"(?i)^add$",
    r"(?i)^more$",
    r"(?i)^more options$",
    r"(?i)^edit$",
    r"(?i)^settings$",
    r"(?i)^switch$",
    r"(?i)^turn off$",
    r"(?i)^picture$",
    r"(?i)^profile$",
    r"(?i)^active(?: now)?$",
    r"(?i)^no room assigned$",
    r"(?i)^qr(?:\s*code)?$",
    r"(?i)^barcode scan$",
    r"(?i)^바코드 스캔$",
    r"(?i)^우리 집$",
    r"(?i).*\(me\).*",
    r"(?i)^\d+$",
)

LIFE_DETAIL_LABEL_PATTERNS = (
    r"(?i)^mapview$",
    r"(?i)^naver$",
    r"(?i).*s24 ultra.*",
    r"(?i).*last updated.*",
)

LIFE_EXCLUDED_RESOURCE_PATTERNS = (
    r"(?i)(toolbar|app_bar|action_bar|home_button|add_menu_button|more_menu_button|small_title_bar|tab_title)",
    r"(?i)(search|profile|avatar|picture|barcode|qr|location|room|setting_button|settings_button)",
)

LIFE_TITLE_RESOURCE_PATTERNS = (
    r"(?i)(container_name|containername|title_service_name|tvheadertitle|fme_title_layout)",
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


def _bounds_contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


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


def _walk_nodes_with_ancestors(
    nodes: list[dict[str, Any]],
    ancestors: list[dict[str, Any]] | None = None,
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    results: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        current_ancestors = list(ancestors or [])
        results.append((node, current_ancestors))
        children = node.get("children")
        if isinstance(children, list):
            results.extend(
                _walk_nodes_with_ancestors(
                    [child for child in children if isinstance(child, dict)],
                    [*current_ancestors, node],
                )
            )
    return results


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
    if not label or _is_chrome_label(label) or _is_life_excluded_label(label):
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


def _descendant_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    return _walk_nodes([child for child in children if isinstance(child, dict)])


def _is_life_excluded_label(label: str) -> bool:
    normalized = _text(label)
    if not normalized:
        return False
    return any(_safe_regex_search(pattern, normalized) for pattern in LIFE_EXCLUDED_LABEL_PATTERNS)


def _is_life_detail_label(label: str) -> bool:
    normalized = _text(label)
    if not normalized:
        return False
    return any(_safe_regex_search(pattern, normalized) for pattern in LIFE_DETAIL_LABEL_PATTERNS)


def _is_life_excluded_resource(resource_id: str, class_name: str) -> bool:
    blob = f"{resource_id} {class_name}"
    return any(_safe_regex_search(pattern, blob) for pattern in LIFE_EXCLUDED_RESOURCE_PATTERNS)


def _has_life_positive_structure(node: dict[str, Any]) -> bool:
    resources = []
    for candidate in [node, *_descendant_nodes(node)]:
        resources.append(f"{_node_resource_id(candidate)} {_node_class_name(candidate)}")
    return any(
        _safe_regex_search(pattern, resource_blob)
        for resource_blob in resources
        for pattern in LIFE_POSITIVE_RESOURCE_PATTERNS
    )


def _has_life_excluded_content(node: dict[str, Any]) -> bool:
    for candidate in [node, *_descendant_nodes(node)]:
        if _is_life_excluded_label(_node_label(candidate)):
            return True
        if _is_life_excluded_resource(_node_resource_id(candidate), _node_class_name(candidate)):
            return True
    return False


def _title_from_preferred_resources(node: dict[str, Any]) -> str:
    candidates = [node, *_descendant_nodes(node)]
    for candidate in candidates:
        resource_id = _node_resource_id(candidate)
        label = _node_label(candidate)
        if not label or _is_life_excluded_label(label) or _is_life_detail_label(label):
            continue
        if any(_safe_regex_search(pattern, resource_id) for pattern in LIFE_TITLE_RESOURCE_PATTERNS):
            if _is_title_like(label):
                return label
    return ""


def _title_from_node(node: dict[str, Any]) -> str:
    label = _node_label(node)
    if not label or _is_life_excluded_label(label) or _is_life_detail_label(label):
        return ""
    resource_id = _node_resource_id(node)
    if any(_safe_regex_search(pattern, resource_id) for pattern in LIFE_TITLE_RESOURCE_PATTERNS):
        return label if _is_title_like(label) else ""
    return ""


def _is_life_container_candidate(node: dict[str, Any], viewport_area: int) -> bool:
    if not _is_visible(node):
        return False
    bounds = _node_bounds(node)
    if not bounds:
        return False
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    area = max(1, width * height)
    if area < max(5000, int(viewport_area * 0.003)):
        return False
    resource_id = _node_resource_id(node)
    class_name = _node_class_name(node)
    label = _node_label(node)
    if _is_chrome_label(label) or _is_chrome_resource(resource_id, class_name):
        return False
    if _is_life_excluded_label(label) or _is_life_excluded_resource(resource_id, class_name):
        return False
    if not bool(node.get("clickable") or node.get("focusable")):
        return False
    if _has_life_excluded_content(node):
        return False
    has_card_hint = _has_life_positive_structure(node)
    if area > int(viewport_area * 0.95) and not has_card_hint:
        return False
    return bool(has_card_hint)


def _promote_life_candidate_container(
    node: dict[str, Any],
    ancestors: list[dict[str, Any]],
    viewport_area: int,
) -> dict[str, Any] | None:
    lineage = [node, *reversed(ancestors)]
    for candidate in lineage:
        if _is_life_container_candidate(candidate, viewport_area):
            return candidate
    return None


def _candidate_resource_blob(node: dict[str, Any]) -> str:
    return " ".join(
        f"{_node_resource_id(candidate)} {_node_class_name(candidate)}"
        for candidate in [node, *_descendant_nodes(node)]
    ).lower()


def _is_find_internal_item_candidate(
    *,
    label: str,
    node: dict[str, Any],
    container: dict[str, Any],
    accepted_cards: list[dict[str, Any]],
) -> bool:
    node_bounds = _node_bounds(node)
    if not node_bounds:
        return False
    lowered = _normalize_key(label)
    if not lowered or lowered == "find":
        return False
    container_blob = _candidate_resource_blob(container)
    if not any(token in container_blob for token in ("fme_", "map_area")):
        return False
    node_blob = f"{_node_resource_id(node)} {_node_class_name(node)}".lower()
    if not any(token in node_blob for token in ("bubble", "marker", "map_area", "container_name")):
        return False
    if "last updated" in _text(label).lower():
        return True
    for accepted in accepted_cards:
        accepted_bounds = accepted.get("bounds_tuple")
        accepted_title = _normalize_key(accepted.get("title"))
        accepted_blob = str(accepted.get("resource_blob") or "")
        if (
            accepted_bounds
            and isinstance(accepted_bounds, tuple)
            and _bounds_contains(accepted_bounds, node_bounds)
            and accepted_title == "find"
            and any(token in accepted_blob for token in ("fme_", "map_area"))
        ):
            return True
    return False


def _is_life_card_like(node: dict[str, Any], viewport_area: int) -> bool:
    if not _is_life_container_candidate(node, viewport_area):
        return False
    return any(_is_title_like(descendant) for descendant in [_node_label(node), *_descendant_labels(node)])


def discover_life_cards_from_nodes(
    nodes: list[dict[str, Any]],
    *,
    known_index: dict[str, dict[str, str]] | None = None,
    source: str = "xml",
) -> list[dict[str, Any]]:
    known_index = known_index or {}
    tree_nodes = [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []
    flat = _walk_nodes(tree_nodes)
    flat_with_ancestors = _walk_nodes_with_ancestors(tree_nodes)
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
    accepted_cards: list[dict[str, Any]] = []
    for index, (node, ancestors) in enumerate(flat_with_ancestors):
        node_title = _title_from_node(node)
        if not node_title:
            continue
        container = _promote_life_candidate_container(node, ancestors, viewport_area)
        if not container:
            continue
        title = _title_from_preferred_resources(container)
        if not title:
            title = node_title
        if not title:
            continue
        if _is_find_internal_item_candidate(
            label=title,
            node=node,
            container=container,
            accepted_cards=accepted_cards,
        ):
            continue
        stable_label = title
        key = _normalize_key(stable_label)
        if not key or key in seen:
            continue
        seen.add(key)
        container_bounds = _node_bounds(container)
        resource_id = _node_resource_id(container)
        class_name = _node_class_name(container)
        known, scenario_id = _known_meta("life", stable_label, known_index)
        confidence = "high" if title in _descendant_labels(container) else "medium"
        if _node_label(container) and not _descendant_labels(container):
            confidence = "low"
        if container_bounds:
            accepted_cards.append(
                {
                    "title": title,
                    "bounds_tuple": container_bounds,
                    "resource_blob": _candidate_resource_blob(container),
                }
            )
        cards.append(
            {
                "id": f"life:{_slug(stable_label)}:{index}",
                "label": title,
                "stable_label": stable_label,
                "type": "life",
                "confidence": confidence,
                "source": source,
                "bounds": _format_bounds(container_bounds),
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
