from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def annotate_bottom_nav_candidates(
    nodes: list[dict[str, Any]],
    *,
    expected_count: int = 0,
) -> list[dict[str, Any]]:
    annotated = [dict(node) for node in nodes if isinstance(node, dict)]
    for node in annotated:
        node["_bottom_nav_candidate"] = False

    row_groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, node in enumerate(annotated):
        bounds = _parse_bounds(node.get("boundsInScreen"))
        if not bounds or not _is_semantic_tab_node(node):
            continue
        left, top, right, bottom = bounds
        if right <= left or bottom <= top:
            continue
        row_groups[(top, bottom)].append(index)

    minimum_count = max(3, int(expected_count or 0))
    eligible_rows = [indices for indices in row_groups.values() if len(indices) >= minimum_count]
    if not eligible_rows:
        return annotated

    selected_row = max(
        eligible_rows,
        key=lambda indices: (
            len(indices),
            max(_parse_bounds(annotated[index].get("boundsInScreen"))[3] for index in indices),
        ),
    )
    for index in selected_row:
        annotated[index]["_bottom_nav_candidate"] = True
    return annotated


def is_annotated_bottom_nav_candidate(node: dict[str, Any]) -> bool:
    return bool(node.get("_bottom_nav_candidate", False))


def _is_semantic_tab_node(node: dict[str, Any]) -> bool:
    class_name = str(node.get("className", "") or "").strip()
    resource_id = str(node.get("viewIdResourceName", "") or node.get("resourceId", "") or "").strip()
    if class_name != "android.widget.LinearLayout" or resource_id:
        return False
    if not _as_bool(node.get("focusable")) or node.get("visibleToUser") is False:
        return False
    label = str(node.get("contentDescription", "") or node.get("text", "") or "").strip()
    return bool(label)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _parse_bounds(value: Any) -> tuple[int, int, int, int] | None:
    if isinstance(value, dict):
        try:
            return (
                int(value["l"]),
                int(value["t"]),
                int(value["r"]),
                int(value["b"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
    numbers = [int(item) for item in re.findall(r"-?\d+", str(value or ""))]
    if len(numbers) < 4:
        return None
    return numbers[0], numbers[1], numbers[2], numbers[3]
