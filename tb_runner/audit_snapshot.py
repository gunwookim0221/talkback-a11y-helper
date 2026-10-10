"""Serialize observed Helper hierarchy without connecting UiAutomation."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from tb_runner.traversal_reliability import normalized_bounds


def write_helper_snapshot_xml(nodes: list[dict[str, Any]], path: Path) -> None:
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("Helper audit snapshot unavailable")
    root = ET.Element("hierarchy", {"source": "a11y_helper", "snapshot_contract": "observed-helper-tree-v1"})

    def append(parent: ET.Element, value: dict[str, Any], index: int) -> None:
        if not isinstance(value, dict):
            raise ValueError("Invalid Helper snapshot node")
        attributes = {"index": str(index)}
        for xml_key, keys in {
            "text": ("text",), "content-desc": ("contentDescription",),
            "resource-id": ("viewIdResourceName", "resourceId"),
            "class": ("className", "class"), "package": ("packageName",),
            "clickable": ("clickable",), "focusable": ("focusable",),
            "focused": ("focused",), "accessibility-focused": ("accessibilityFocused",),
            "scrollable": ("isScrollable", "scrollable"), "enabled": ("enabled", "isEnabled"),
            "visible-to-user": ("visibleToUser", "isVisibleToUser"),
            "selected": ("selected",), "checkable": ("checkable",), "checked": ("checked",),
        }.items():
            for key in keys:
                if key in value and value[key] is not None:
                    item = value[key]
                    attributes[xml_key] = str(item).lower() if isinstance(item, bool) else str(item)
                    break
        bounds = normalized_bounds(value.get("boundsInScreen", value.get("bounds", "")))
        if bounds:
            parts = bounds.split(",")
            if len(parts) == 4:
                attributes["bounds"] = f"[{parts[0]},{parts[1]}][{parts[2]},{parts[3]}]"
        element = ET.SubElement(parent, "node", attributes)
        for child_index, child in enumerate(value.get("children") or []):
            append(element, child, child_index)

    for index, node in enumerate(nodes):
        append(root, node, index)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
