from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Mapping


LATER_RESOURCE_ID = "android:id/button3"
SETUP_RESOURCE_ID = "android:id/button1"
DISMISS_LABELS = {"later", "나중에"}
POSITIVE_LABELS = {"set up now", "지금 설정하기", "설정", "확인"}

_EN_EVIDENCE = (
    "protect your samsung account",
    "samsung account",
    "two-step verification",
    "set up two-step verification",
)
_KO_EVIDENCE = (
    "삼성 계정을 더 안전하게",
    "삼성 계정",
    "2단계 인증",
    "계정을 안전하게 보호",
)


@dataclass(frozen=True)
class SamsungAccountPopupCandidate:
    label: str
    bounds: str
    x: int
    y: int
    resource_id: str
    method: str
    locale: str
    title: str = ""
    popup_kind: str = "samsung_account_two_step"


def find_samsung_account_popup_candidate_in_xml(xml_text: str) -> SamsungAccountPopupCandidate | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    return find_samsung_account_popup_candidate(root.iter("node"))


def find_samsung_account_popup_candidate(
    nodes: object,
) -> SamsungAccountPopupCandidate | None:
    node_attrs = [_attributes(node) for node in nodes]
    evidence = _detect_evidence(node_attrs)
    if not evidence["detected"]:
        return None

    by_resource: SamsungAccountPopupCandidate | None = None
    by_label: SamsungAccountPopupCandidate | None = None
    for attrs in node_attrs:
        label = _node_label(attrs)
        normalized_label = normalize(label)
        resource_id = str(attrs.get("resource-id", "") or attrs.get("resourceId", "") or attrs.get("viewIdResourceName", "") or "").strip()
        normalized_resource = normalize(resource_id)

        if normalized_resource == SETUP_RESOURCE_ID or normalized_label in POSITIVE_LABELS:
            continue
        if normalized_label not in DISMISS_LABELS:
            continue

        center = bounds_center(str(attrs.get("bounds", "") or attrs.get("boundsInScreen", "") or ""))
        if center is None:
            continue
        candidate = SamsungAccountPopupCandidate(
            label=label,
            bounds=str(attrs.get("bounds", "") or attrs.get("boundsInScreen", "") or ""),
            x=center[0],
            y=center[1],
            resource_id=resource_id,
            method="resource_id" if normalized_resource == LATER_RESOURCE_ID else "label",
            locale=str(evidence["locale"]),
            title=str(evidence["title"]),
        )
        if normalized_resource == LATER_RESOURCE_ID:
            by_resource = candidate
            break
        if _is_actionable(attrs) and by_label is None:
            by_label = candidate

    return by_resource or by_label


def normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def bounds_center(bounds: str) -> tuple[int, int] | None:
    text = str(bounds or "").strip()
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", text)
    if not match:
        match = re.fullmatch(r"(\d+),(\d+),(\d+),(\d+)", text)
    if not match:
        return None
    left, top, right, bottom = (int(part) for part in match.groups())
    if right <= left or bottom <= top:
        return None
    return (left + right) // 2, (top + bottom) // 2


def _attributes(node: object) -> Mapping[str, object]:
    attrib = getattr(node, "attrib", None)
    if isinstance(attrib, dict):
        return attrib
    if isinstance(node, dict):
        return node
    return {}


def _node_label(attrs: Mapping[str, object]) -> str:
    for key in ("text", "content-desc", "contentDescription", "label", "talkbackLabel", "mergedLabel"):
        value = str(attrs.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _is_actionable(attrs: Mapping[str, object]) -> bool:
    return any(_truthy(attrs.get(key)) for key in ("clickable", "focusable", "effectiveClickable"))


def _truthy(value: object) -> bool:
    return bool(value) if not isinstance(value, str) else value.strip().lower() == "true"


def _detect_evidence(node_attrs: list[Mapping[str, object]]) -> dict[str, object]:
    title = ""
    all_text: list[str] = []
    for attrs in node_attrs:
        label = _node_label(attrs)
        if not label:
            continue
        all_text.append(label)
        resource_id = str(attrs.get("resource-id", "") or attrs.get("resourceId", "") or attrs.get("viewIdResourceName", "") or "")
        if normalize(resource_id) == "android:id/alerttitle":
            title = label

    haystack = normalize(" ".join(all_text))
    has_en = any(token in haystack for token in _EN_EVIDENCE)
    has_ko = any(token in haystack for token in _KO_EVIDENCE)
    if not (has_en or has_ko):
        return {"detected": False, "locale": "", "title": title}
    return {"detected": True, "locale": "ko" if has_ko else "en", "title": title}
