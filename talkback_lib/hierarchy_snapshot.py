"""Normalization helpers for service-owned AccessibilityService hierarchy payloads."""
from __future__ import annotations

from typing import Any
import xml.etree.ElementTree as ET


def _service_window_roots(
    snapshot: dict[str, Any], *, include_all_windows: bool
) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    if not isinstance(snapshot, dict) or snapshot.get("success") is not True:
        raise ValueError("HIERARCHY_SNAPSHOT:SERIALIZATION_ERROR:invalid_snapshot")
    windows = snapshot.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("HIERARCHY_SNAPSHOT:NO_ROOT:window_list_empty")
    entries: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, window in enumerate(windows):
        if not isinstance(window, dict):
            raise ValueError(f"HIERARCHY_SNAPSHOT:SERIALIZATION_ERROR:invalid_window:{index}")
        root = window.get("root")
        if not isinstance(root, dict):
            raise ValueError(f"HIERARCHY_SNAPSHOT:NO_ROOT:window_root_missing:{index}")
        entries.append((index, window, root))

    if include_all_windows:
        return entries

    focused = [entry for entry in entries if bool(entry[1].get("focused"))]
    active = [entry for entry in entries if bool(entry[1].get("active"))]
    preferred = [entry for entry in focused if entry in active] or focused or active
    if preferred:
        return [preferred[0]]
    if len(entries) == 1:
        return [entries[0]]
    raise ValueError("HIERARCHY_SNAPSHOT:NO_ACTIVE_WINDOW:no focused or active service window")


def flatten_service_hierarchy(
    snapshot: dict[str, Any], *, include_all_windows: bool = False
) -> list[dict[str, Any]]:
    """Flatten the active service window, matching the former active-window XML view.

    Set ``include_all_windows`` for diagnostics that need every service-visible
    root. The raw snapshot always retains all window metadata and roots.
    """
    window_roots = _service_window_roots(snapshot, include_all_windows=include_all_windows)

    flattened: list[dict[str, Any]] = []

    def visit(
        node: dict[str, Any],
        path: str,
        ancestors: list[dict[str, Any]],
        window_index: int,
        service_window_index: int,
    ) -> None:
        normalized = dict(node)
        bounds = node.get("boundsInScreen", node.get("bounds", ""))
        if isinstance(bounds, dict):
            try:
                bounds = "[{l},{t}][{r},{b}]".format(
                    l=int(bounds.get("left", bounds.get("l", 0)) or 0),
                    t=int(bounds.get("top", bounds.get("t", 0)) or 0),
                    r=int(bounds.get("right", bounds.get("r", 0)) or 0),
                    b=int(bounds.get("bottom", bounds.get("b", 0)) or 0),
                )
            except (TypeError, ValueError):
                bounds = ""
        normalized["text"] = str(node.get("text") or "")
        normalized["contentDescription"] = str(node.get("contentDescription") or "")
        normalized["viewIdResourceName"] = str(node.get("viewIdResourceName") or "")
        normalized["resource-id"] = normalized["viewIdResourceName"]
        normalized["className"] = str(node.get("className") or "")
        normalized["class"] = normalized["className"]
        normalized["packageName"] = str(node.get("packageName") or "")
        normalized["package"] = normalized["packageName"]
        normalized["boundsInScreen"] = str(bounds or "")
        normalized["bounds"] = normalized["boundsInScreen"]
        normalized["visibleToUser"] = bool(node.get("visibleToUser", node.get("isVisibleToUser", True)))
        normalized["visible-to-user"] = "true" if normalized["visibleToUser"] else "false"
        for attribute in ("clickable", "focusable", "focused", "accessibilityFocused", "selected", "scrollable", "checked"):
            normalized[attribute] = bool(node.get(attribute, False))
        normalized["enabled"] = bool(node.get("enabled", True))
        normalized["content-desc"] = normalized["contentDescription"]
        normalized["stable_node_path"] = path
        normalized["ancestors"] = ancestors
        normalized["windowIndex"] = window_index
        normalized["serviceWindowIndex"] = service_window_index
        normalized.setdefault("role", "")
        # This adapter represents the legacy flat node list. Keep descendants
        # only in the raw service snapshot and the dedicated scroll-tree view.
        normalized.pop("children", None)
        flattened.append(normalized)
        children = node.get("children")
        if children is None:
            return
        if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
            raise ValueError("HIERARCHY_SNAPSHOT:SERIALIZATION_ERROR:invalid_children")

        for order, child in enumerate(sorted(children, key=lambda item: int(item.get("childIndex", 0)))):
            child_path = f"{path}.{child.get('childIndex', order)}"
            child_ancestors = ancestors + [{
                "path": path,
                "resource_id": str(node.get("viewIdResourceName") or ""),
                "class_name": str(node.get("className") or ""),
                "role": str(node.get("role") or ""),
            }]
            visit(child, child_path, child_ancestors, window_index, service_window_index)

    for projected_index, (service_window_index, _window, root) in enumerate(window_roots):
        # The legacy XML parser began at the <hierarchy> document node and
        # assigned the active window root child index zero. Preserve that path
        # prefix so path based candidate identity remains comparable, while
        # retaining the original AccessibilityWindowInfo index separately.
        visit(root, f"{projected_index}.0", [], projected_index, service_window_index)
    return flattened


def legacy_scroll_nodes(
    snapshot: dict[str, Any], *, include_all_windows: bool = False
) -> list[dict[str, Any]]:
    """Adapt service nodes to the former scrolltouch XML parser's semantic shape."""
    from talkback_lib.utils import normalize_bounds

    def convert(value: dict[str, Any]) -> dict[str, Any] | None:
        bounds = normalize_bounds(value)
        children = [node for child in value.get("children") or [] if isinstance(child, dict)
                    if (node := convert(child)) is not None]
        if not bounds and not children:
            return None
        return {
            "text": str(value.get("text") or "").strip(),
            "contentDescription": str(value.get("contentDescription") or "").strip(),
            "viewIdResourceName": str(value.get("viewIdResourceName") or "").strip(),
            "className": str(value.get("className") or "").strip(),
            "packageName": str(value.get("packageName") or "").strip(),
            "clickable": bool(value.get("clickable")),
            "focusable": bool(value.get("focusable")),
            "effectiveClickable": bool(value.get("effectiveClickable", value.get("clickable"))),
            "visibleToUser": bool(value.get("visibleToUser", value.get("isVisibleToUser", True))),
            "selected": bool(value.get("selected")),
            "scrollable": bool(value.get("scrollable", value.get("isScrollable", False))),
            "enabled": bool(value.get("enabled", True)),
            "boundsInScreen": bounds,
            "children": children,
        }
    nodes = [node for _, _, root in _service_window_roots(snapshot, include_all_windows=include_all_windows)
             if (node := convert(root)) is not None]
    return nodes


def hierarchy_package(snapshot: dict[str, Any], *, include_all_windows: bool = False) -> str | None:
    for node in flatten_service_hierarchy(snapshot, include_all_windows=include_all_windows):
        package = str(node.get("packageName") or "").strip()
        if package:
            return package
    return None


def hierarchy_windows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    windows = snapshot.get("windows") if isinstance(snapshot, dict) else None
    if not isinstance(windows, list) or any(not isinstance(window, dict) for window in windows):
        raise ValueError("HIERARCHY_SNAPSHOT:SERIALIZATION_ERROR:invalid_windows")
    return windows


def service_hierarchy_to_xml(snapshot: dict[str, Any], *, include_all_windows: bool = False) -> str:
    """Serialize service nodes into the former active-window XML consumer shape.

    ``include_all_windows`` is available for diagnostic XML exports; normal
    compatibility reads remain scoped to the active/focused service window.
    """
    if not isinstance(snapshot, dict) or snapshot.get("success") is not True:
        raise ValueError("HIERARCHY_SNAPSHOT:SERIALIZATION_ERROR:invalid_snapshot")
    window_roots = _service_window_roots(snapshot, include_all_windows=include_all_windows)
    document = ET.Element("hierarchy")

    def bounds_string(value: Any) -> str:
        if isinstance(value, dict):
            try:
                left = int(value.get("left", value.get("l", 0)) or 0)
                top = int(value.get("top", value.get("t", 0)) or 0)
                right = int(value.get("right", value.get("r", 0)) or 0)
                bottom = int(value.get("bottom", value.get("b", 0)) or 0)
                return f"[{left},{top}][{right},{bottom}]"
            except (TypeError, ValueError):
                return ""
        return str(value or "")

    def add_node(parent: ET.Element, node: dict[str, Any]) -> None:
        values = {
            "text": node.get("text"),
            "content-desc": node.get("contentDescription"),
            "resource-id": node.get("viewIdResourceName"),
            "class": node.get("className"),
            "package": node.get("packageName"),
            "bounds": bounds_string(node.get("boundsInScreen")),
            "clickable": node.get("clickable"),
            "focusable": node.get("focusable"),
            "enabled": node.get("enabled"),
            "focused": node.get("focused"),
            "accessibility-focused": node.get("accessibilityFocused"),
            "selected": node.get("selected"),
            "scrollable": node.get("scrollable"),
            "checkable": node.get("checkable"),
            "checked": node.get("checked"),
            "visible-to-user": node.get("visibleToUser", node.get("isVisibleToUser", True)),
        }
        element = ET.SubElement(parent, "node")
        for key, value in values.items():
            if value is None:
                continue
            element.set(key, str(value).lower() if isinstance(value, bool) else str(value))
        for index, child in enumerate(node.get("children") or []):
            if isinstance(child, dict):
                add_node(element, child)

    for _service_index, _metadata, root in window_roots:
        add_node(document, root)
    return ET.tostring(document, encoding="unicode")
