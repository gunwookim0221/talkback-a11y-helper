from __future__ import annotations

import re
from typing import Any

from tb_runner.utils import parse_bounds_str

DEVICE_CARD_RESOURCE_IDS = {
    "com.samsung.android.oneconnect:id/device_card",
    "com.samsung.android.oneconnect:id/device_card_camera",
}

ALL_DEVICES_LABELS = {
    "모든 기기",
    "all devices",
}

DEVICE_STATE_SUFFIXES = (
    "움직임 감지됨",
    "물기 없음",
    "감지 안 됨",
    "진동 감지됨",
    "최근 감지",
    "연결됨",
    "일시중지",
    "오프라인",
    "켜짐",
    "꺼짐",
    "잠김",
    "열림",
    "감지됨",
    "온도",
    "습도",
    "배터리",
    "전력량",
    "connected",
    "paused",
    "offline",
    "locked",
    "unlocked",
    "open",
    "closed",
    "detected",
    "temperature",
    "humidity",
    "battery",
    "power",
    "on",
    "off",
)

COLLAPSED_TOKENS = (
    "접힘",
    "접혀짐",
    "접힌",
    "펼치기",
    "collapsed",
    "expand",
)

EXPANDED_TOKENS = (
    "펼쳐짐",
    "접기",
    "expanded",
    "collapse",
)

ROOM_SECTION_RESOURCE_HINTS = (
    "subheader",
    "room",
    "section",
    "header",
)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _resource_id(node: dict[str, Any]) -> str:
    for key in ("viewIdResourceName", "resourceId", "resource_id", "resource-id", "id"):
        value = node.get(key)
        if value:
            return str(value).strip()
    return ""


def _node_label(node: dict[str, Any]) -> str:
    for key in ("mergedLabel", "talkbackLabel", "contentDescription", "text", "content-desc"):
        value = _text(node.get(key))
        if value:
            return value
    return ""


def _bounds_text(node: dict[str, Any]) -> str:
    bounds = node.get("boundsInScreen", node.get("bounds", ""))
    parsed = parse_bounds_str(bounds)
    if not parsed:
        return _text(bounds)
    left, top, right, bottom = parsed
    return f"{left},{top},{right},{bottom}"


def _bounds_tuple(node: dict[str, Any]) -> tuple[int, int, int, int] | None:
    return parse_bounds_str(node.get("boundsInScreen", node.get("bounds", "")))


def _bool_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _visible(node: dict[str, Any]) -> bool:
    if "isVisibleToUser" in node:
        return _bool_value(node.get("isVisibleToUser"))
    if "visibleToUser" in node:
        return _bool_value(node.get("visibleToUser"))
    return True


def _normalized_label(value: Any) -> str:
    normalized = _text(value).lower()
    normalized = re.sub(r"[^0-9a-z가-힣]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_device_match_label(value: Any) -> str:
    return _normalized_label(normalize_device_stable_label(str(value or "")))


def _dedupe_repeated_words(value: str) -> str:
    parts = value.split()
    if len(parts) % 2 == 0 and parts[: len(parts) // 2] == parts[len(parts) // 2 :]:
        return " ".join(parts[: len(parts) // 2])
    return value


def normalize_device_stable_label(label: str) -> str:
    stable = _dedupe_repeated_words(_text(label))
    for suffix in sorted(DEVICE_STATE_SUFFIXES, key=len, reverse=True):
        stable = re.sub(rf"\s+{re.escape(suffix)}$", "", stable, flags=re.IGNORECASE).strip()
    return stable


def label_contains_state_text(label: str) -> bool:
    normalized = _normalized_label(label)
    words = set(normalized.split())
    for token in DEVICE_STATE_SUFFIXES:
        normalized_token = _normalized_label(token)
        if not normalized_token:
            continue
        if re.fullmatch(r"[a-z]+", normalized_token):
            if normalized_token in words:
                return True
            continue
        if normalized_token in normalized:
            return True
    return False


def _is_all_devices_label(label: str) -> bool:
    normalized = _normalized_label(_dedupe_repeated_words(label))
    return normalized in {_normalized_label(value) for value in ALL_DEVICES_LABELS}


def _make_candidate(node: dict[str, Any], *, role: str) -> dict[str, Any]:
    bounds = _bounds_tuple(node)
    left, top, right, bottom = bounds if bounds else (0, 0, 0, 0)
    label = _node_label(node)
    stable_label = normalize_device_stable_label(label)
    return {
        "role": role,
        "node": node,
        "label": label,
        "stable_label": stable_label,
        "rid": _resource_id(node),
        "resource_id": _resource_id(node),
        "class_name": _text(node.get("className")),
        "bounds": _bounds_text(node),
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "clickable": _bool_value(node.get("clickable")),
        "focusable": _bool_value(node.get("focusable")),
        "selected": _bool_value(node.get("selected")),
        "effective_clickable": _bool_value(node.get("effectiveClickable")) or _bool_value(node.get("clickable")),
        "has_clickable_descendant": _bool_value(node.get("hasClickableDescendant")),
        "actionable_descendant_resource_id": _text(node.get("actionableDescendantResourceId")),
        "target_label_allowed": bool(stable_label) and not label_contains_state_text(stable_label),
    }


def detect_selected_device_location(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    candidate = find_all_devices_location_candidate(nodes)
    if not candidate:
        return {"selected": False, "candidate": None, "reason": "all_devices_not_found"}
    node = candidate["node"]
    selected = bool(candidate.get("selected"))
    label = candidate.get("label", "")
    if _is_all_devices_label(label) and (
        selected
        or _bool_value(node.get("focusable"))
        or _bool_value(node.get("accessibilityFocused"))
        or _bool_value(node.get("focused"))
    ):
        return {"selected": True, "candidate": candidate, "reason": "all_devices_visible"}
    return {"selected": False, "candidate": candidate, "reason": "all_devices_candidate_not_selected"}


def find_all_devices_location_candidate(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict) or not _visible(node):
            continue
        label = _node_label(node)
        if not label or not _is_all_devices_label(label):
            continue
        candidate = _make_candidate(node, role="all_devices_location")
        score = 0
        score += 40 if candidate["focusable"] else 0
        score += 30 if candidate["clickable"] or candidate["effective_clickable"] else 0
        score += 20 if candidate["selected"] else 0
        score += 10 if "title" not in candidate["rid"].lower() else 0
        candidate["score"] = score
        candidates.append(candidate)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-int(item["score"]), item["top"], item["left"]))[0]


def find_collapsed_room_sections(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict) or not _visible(node):
            continue
        label = _node_label(node)
        if not label:
            continue
        rid = _resource_id(node).lower()
        class_name = _text(node.get("className")).lower()
        haystack = _normalized_label(f"{label} {rid} {class_name}")
        has_section_hint = any(token in rid for token in ROOM_SECTION_RESOURCE_HINTS)
        has_collapsed = any(_normalized_label(token) in haystack for token in COLLAPSED_TOKENS)
        has_expanded = any(_normalized_label(token) in haystack for token in EXPANDED_TOKENS)
        if has_expanded and not has_collapsed:
            continue
        if has_collapsed or has_section_hint:
            candidate = _make_candidate(node, role="room_section")
            candidate["collapsed"] = bool(has_collapsed)
            candidate["confidence"] = "high" if has_collapsed else "low"
            candidate["actionable"] = bool(has_collapsed and (candidate["clickable"] or candidate["effective_clickable"]))
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: (item["top"], item["left"], item["label"]))


def _is_device_card_node(node: dict[str, Any]) -> bool:
    rid = _resource_id(node)
    if rid not in DEVICE_CARD_RESOURCE_IDS:
        return False
    if not _visible(node):
        return False
    class_name = _text(node.get("className"))
    if "ViewGroup" not in class_name:
        return False
    return bool(
        _bool_value(node.get("clickable"))
        or _bool_value(node.get("focusable"))
        or _bool_value(node.get("effectiveClickable"))
    )


def collect_visible_device_cards(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not _is_device_card_node(node):
            continue
        card = _make_candidate(node, role="device_card")
        card["source_index"] = index
        card["entry_target"] = {
            "type": "bounds" if card["bounds"] else "resource",
            "resource_id": card["rid"],
            "bounds": card["bounds"],
            "label": card["stable_label"],
        }
        cards.append(card)
    return sorted(cards, key=lambda item: (item["top"], item["left"], item["stable_label"]))


def find_device_card_by_stable_label(
    nodes: list[dict[str, Any]],
    target_stable_labels: list[str] | tuple[str, ...],
) -> dict[str, Any] | None:
    target_labels = {
        normalize_device_match_label(label)
        for label in target_stable_labels
        if normalize_device_match_label(label)
    }
    if not target_labels:
        return None
    for card in collect_visible_device_cards(nodes):
        if normalize_device_match_label(card.get("stable_label", "")) in target_labels:
            return card
    return None


def select_all_devices_candidate_for_action(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    state = detect_selected_device_location(nodes)
    if bool(state.get("selected")):
        return None
    return state.get("candidate") if isinstance(state.get("candidate"), dict) else None


def collect_high_confidence_collapsed_room_sections(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        candidate
        for candidate in find_collapsed_room_sections(nodes)
        if candidate.get("confidence") == "high" and bool(candidate.get("actionable"))
    ]


def _bounds_contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def promote_device_card_target(node: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    if _is_device_card_node(node):
        return _make_candidate(node, role="device_card")
    child_bounds = _bounds_tuple(node)
    cards = collect_visible_device_cards(nodes)
    if not child_bounds:
        child_label = _normalized_label(_node_label(node))
        for card in cards:
            card_label = _normalized_label(card.get("label", ""))
            if child_label and card_label and child_label in card_label:
                promoted = dict(card)
                promoted["promoted_from"] = _make_candidate(node, role="matched_child")
                return promoted
        return None
    containing_cards = []
    for card in cards:
        card_bounds = parse_bounds_str(card["bounds"])
        if card_bounds and _bounds_contains(card_bounds, child_bounds):
            containing_cards.append(card)
    if not containing_cards:
        return None
    promoted = sorted(
        containing_cards,
        key=lambda item: ((item["right"] - item["left"]) * (item["bottom"] - item["top"]), item["top"], item["left"]),
    )[0]
    result = dict(promoted)
    result["promoted_from"] = _make_candidate(node, role="matched_child")
    return result
