from __future__ import annotations

import re
from typing import Any

from tb_runner.utils import parse_bounds_str


def _build_candidate_object_signature(*, rid: str, bounds: str, label: str) -> str:
    normalized_label = re.sub(r"\s+", " ", str(label or "").strip()).lower()
    return "||".join([str(rid or "").strip().lower(), str(bounds or "").strip(), normalized_label])


def _candidate_object_signature(candidate: dict[str, Any]) -> str:
    return _build_candidate_object_signature(
        rid=str(candidate.get("rid", "") or "").strip(),
        bounds=str(candidate.get("bounds", "") or "").strip(),
        label=str(candidate.get("label", "") or "").strip(),
    )


def _candidate_cluster_signature(candidate: dict[str, Any]) -> str:
    return str(candidate.get("cluster_signature", "") or "").strip()


def _normalize_logical_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    normalized = re.sub(r"[^\w\s:/%-]+", "", normalized)
    return normalized.strip()


def _candidate_cluster_logical_signature(candidate: dict[str, Any]) -> str:
    cluster_rid = str(candidate.get("cluster_rid", "") or candidate.get("rid", "") or "").strip().lower()
    label = str(candidate.get("cluster_label", "") or candidate.get("label", "") or "").strip()
    logical_label = _normalize_logical_text(label)
    return "||".join([cluster_rid or "none", logical_label or "none"])


def _candidate_container_group_visual_order_key(candidate: dict[str, Any]) -> tuple[int, int]:
    bounds = parse_bounds_str(str(candidate.get("bounds", "") or "").strip())
    if bounds:
        return (bounds[1] + bounds[3]) // 2, (bounds[0] + bounds[2]) // 2
    return int(candidate.get("top", 0) or 0), int(candidate.get("left", 0) or 0)


def _should_apply_container_priority_narrowing(
    container_candidates: list[dict[str, Any]],
    all_candidates: list[dict[str, Any]],
) -> tuple[bool, str]:
    if not container_candidates:
        return False, "no_container_candidates"
    if len(container_candidates) < 2:
        return False, "single_container_keep_mixed_candidates"
    bounds_list = [
        parse_bounds_str(str(candidate.get("bounds", "") or "").strip())
        for candidate in container_candidates
    ]
    bounds_list = [bounds for bounds in bounds_list if bounds]
    if len(bounds_list) < 2:
        return True, "repeated_container_group"
    widths = [bounds[2] - bounds[0] for bounds in bounds_list]
    heights = [bounds[3] - bounds[1] for bounds in bounds_list]
    tops = sorted(bounds[1] for bounds in bounds_list)
    width_similar = max(widths) - min(widths) <= max(180, int(max(widths) * 0.35))
    height_similar = max(heights) - min(heights) <= max(120, int(max(heights) * 0.45))
    vertical_repeated = len(set(tops)) >= 2
    if width_similar and height_similar and vertical_repeated:
        return True, "repeated_container_group"
    if len(container_candidates) >= 3 and vertical_repeated:
        return True, "repeated_container_group"
    return False, "container_group_not_repeated"


def _container_group_signature(container_candidates: list[dict[str, Any]]) -> str:
    signatures = sorted(
        signature
        for signature in (_candidate_object_signature(candidate) for candidate in container_candidates)
        if signature
    )
    return "container_group:" + "##".join(signatures) if signatures else ""
