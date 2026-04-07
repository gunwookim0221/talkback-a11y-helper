#!/usr/bin/env python3
"""Focus parsing helpers."""

from __future__ import annotations

from typing import Any

from talkback_lib.utils import normalize_bounds, parse_bounds_tuple, safe_parse_json_payload


def parse_json_payload(payload: str, label: str) -> dict[str, Any]:
    return safe_parse_json_payload(payload=payload, label=label)


def normalize_focus_bounds(node: dict[str, Any]) -> str:
    return normalize_bounds(node)


def parse_focus_bounds_tuple(bounds: str) -> tuple[int, int, int, int] | None:
    return parse_bounds_tuple(bounds)


def is_meaningful_focus_node(node: Any) -> bool:
    if not isinstance(node, dict) or not node:
        return False

    text_value = node.get("text")
    if isinstance(text_value, str) and text_value.strip():
        return True

    content_desc = node.get("contentDescription")
    if isinstance(content_desc, str) and content_desc.strip():
        return True

    view_id = node.get("viewIdResourceName")
    if isinstance(view_id, str) and view_id.strip():
        return True

    bounds = node.get("boundsInScreen")
    if isinstance(bounds, dict) and any(key in bounds for key in ("l", "t", "r", "b", "left", "top", "right", "bottom")):
        return True

    if bool(node.get("accessibilityFocused")):
        return True

    if bool(node.get("focused")):
        return True

    return False


def find_focused_node_in_tree(nodes: Any) -> dict[str, Any]:
    def _walk(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}

        if bool(node.get("accessibilityFocused")):
            return node

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                found = _walk(child)
                if found:
                    return found
        return {}

    def _walk_focused(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}

        if bool(node.get("focused")):
            return node

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                found = _walk_focused(child)
                if found:
                    return found
        return {}

    if not isinstance(nodes, list):
        return {}

    for node in nodes:
        found = _walk(node)
        if found:
            return found

    for node in nodes:
        found = _walk_focused(node)
        if found:
            return found

    return {}
