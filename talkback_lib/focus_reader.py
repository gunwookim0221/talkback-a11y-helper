"""Focus reader staging helpers (not wired into runtime yet)."""

from __future__ import annotations

from typing import Any

from .utils import normalize_bounds, parse_bounds_tuple


def normalize_focus_bounds(node: dict[str, Any]) -> str:
    return normalize_bounds(node)


def parse_focus_bounds_tuple(bounds: str) -> tuple[int, int, int, int] | None:
    return parse_bounds_tuple(bounds)
