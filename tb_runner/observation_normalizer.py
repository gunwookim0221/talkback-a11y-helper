"""Locale-aware deterministic normalization for Phase 10.3C observations."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping

from tb_runner.canonical_json import canonical_sha256
from tb_runner.observation_schema import (
    OBSERVATION_SCHEMA_VERSION,
    CanonicalObservation,
)


_WHITESPACE = re.compile(r"\s+")
_PERCENT = re.compile(
    r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(%|percent|퍼센트)(?!\w)",
    re.IGNORECASE,
)
_TIME = re.compile(
    r"(?<!\w)(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?)(?!\w)",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"(?<!\w)(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})(?!\w)"
)
_MASKED = re.compile(r"(?<!\w)(?:[•●*#·]\s*){3,}(?!\w)")
_NUMBER = re.compile(r"(?<![\w<>])\d+(?:[.,]\d+)?(?![\w<>])")
_BOUNDS_NUMBER = re.compile(r"-?\d+")
_ROLE_SUFFIXES = {
    "en": (
        "button",
        "tab",
        "checkbox",
        "switch",
        "image",
        "link",
        "heading",
    ),
    "ko": ("버튼", "탭", "체크박스", "스위치", "이미지", "링크", "제목"),
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value if _text(item))
    return str(value)


def _normalize_space(value: str) -> str:
    return _WHITESPACE.sub(" ", value.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _punctuation_to_space(value: str) -> str:
    return _normalize_space(
        "".join(
            " " if unicodedata.category(char).startswith("P") else char
            for char in value
        )
    )


def _collapse_duplicate_segments(value: str) -> tuple[str, bool]:
    parts = [
        _normalize_space(part)
        for part in re.split(r"[,;\n]+", value)
        if _normalize_space(part)
    ]
    collapsed: list[str] = []
    duplicate = False
    for part in parts:
        if collapsed and collapsed[-1].casefold() == part.casefold():
            duplicate = True
            continue
        collapsed.append(part)
    return ", ".join(collapsed), duplicate


def _marker(
    marker_type: str,
    raw: str,
    placeholder: str,
    *,
    start: int,
) -> dict[str, Any]:
    return {
        "type": marker_type,
        "placeholder": placeholder,
        "value_digest": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "start": start,
        "length": len(raw),
    }


def _replace_pattern(
    value: str,
    pattern: re.Pattern[str],
    marker_type: str,
    placeholder: str,
    markers: list[dict[str, Any]],
) -> str:
    def replace(match: re.Match[str]) -> str:
        markers.append(
            _marker(
                marker_type,
                match.group(0),
                placeholder,
                start=match.start(),
            )
        )
        return placeholder

    return pattern.sub(replace, value)


def normalize_text(
    value: Any,
    *,
    locale: str,
    dynamic_device_names: Iterable[str] = (),
    speech: bool = False,
) -> dict[str, Any]:
    raw = unicodedata.normalize("NFC", _text(value))
    whitespace = _normalize_space(raw)
    collapsed, duplicate = _collapse_duplicate_segments(whitespace)
    dynamic = collapsed
    markers: list[dict[str, Any]] = []
    dynamic = _replace_pattern(dynamic, _PERCENT, "PERCENT", "<PERCENT>", markers)
    dynamic = _replace_pattern(dynamic, _TIME, "TIME", "<TIME>", markers)
    dynamic = _replace_pattern(dynamic, _DATE, "DATE", "<DATE>", markers)
    dynamic = _replace_pattern(dynamic, _MASKED, "MASKED_IDENTIFIER", "<MASKED_ID>", markers)
    for device_name in sorted(
        {str(item).strip() for item in dynamic_device_names if str(item).strip()},
        key=len,
        reverse=True,
    ):
        match = re.search(re.escape(device_name), dynamic, flags=re.IGNORECASE)
        if match:
            markers.append(
                _marker(
                    "DYNAMIC_DEVICE_NAME",
                    match.group(0),
                    "<DEVICE_NAME>",
                    start=match.start(),
                )
            )
            dynamic = re.sub(
                re.escape(device_name),
                "<DEVICE_NAME>",
                dynamic,
                flags=re.IGNORECASE,
            )
    dynamic = _replace_pattern(dynamic, _NUMBER, "NUMBER", "<NUMBER>", markers)
    casefolded = dynamic.casefold()
    punctuation = _punctuation_to_space(casefolded)
    language = str(locale or "").split("-", 1)[0].lower()
    role_suffixes = _ROLE_SUFFIXES.get(language, ())
    role_stripped = punctuation
    removed_roles: list[str] = []
    changed = True
    while changed:
        changed = False
        for suffix in role_suffixes:
            suffix_folded = suffix.casefold()
            if role_stripped == suffix_folded:
                role_stripped = ""
                removed_roles.append(suffix)
                changed = True
                break
            if role_stripped.endswith(" " + suffix_folded):
                role_stripped = role_stripped[: -(len(suffix_folded) + 1)].strip()
                removed_roles.append(suffix)
                changed = True
                break
    return {
        "raw_nfc": raw,
        "whitespace_normalized": whitespace,
        "duplicate_segments_collapsed": collapsed,
        "duplicate_segment_detected": duplicate if speech else False,
        "casefolded": casefolded,
        "punctuation_normalized": punctuation,
        "semantic": punctuation,
        "role_stripped": role_stripped,
        "role_tokens_removed": removed_roles,
        "tokens": punctuation.split() if punctuation else [],
        "dynamic_markers": markers,
    }


def parse_bounds(value: Any) -> tuple[int, int, int, int] | None:
    if isinstance(value, Mapping):
        values = (
            value.get("left", value.get("l")),
            value.get("top", value.get("t")),
            value.get("right", value.get("r")),
            value.get("bottom", value.get("b")),
        )
        if all(item is not None for item in values):
            try:
                parsed = tuple(int(item) for item in values)
                return parsed if parsed[2] > parsed[0] and parsed[3] > parsed[1] else None
            except (TypeError, ValueError):
                return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            parsed = tuple(int(item) for item in value)
            return parsed if parsed[2] > parsed[0] and parsed[3] > parsed[1] else None
        except (TypeError, ValueError):
            return None
    numbers = [int(item) for item in _BOUNDS_NUMBER.findall(str(value or ""))]
    if len(numbers) >= 4:
        parsed = tuple(numbers[:4])
        return parsed if parsed[2] > parsed[0] and parsed[3] > parsed[1] else None
    return None


def bounds_region(
    bounds: tuple[int, int, int, int] | None,
    *,
    viewport: tuple[int, int] = (1080, 2640),
) -> str:
    if bounds is None:
        return "UNKNOWN"
    width, height = viewport
    if (
        bounds[2] <= 0
        or bounds[3] <= 0
        or bounds[0] >= width
        or bounds[1] >= height
    ):
        return "OFF_SCREEN"
    center_x = (bounds[0] + bounds[2]) / 2
    center_y = (bounds[1] + bounds[3]) / 2
    horizontal = "LEFT" if center_x < width / 3 else "RIGHT" if center_x > width * 2 / 3 else "CENTER"
    vertical = "TOP" if center_y < height / 3 else "BOTTOM" if center_y > height * 2 / 3 else "MIDDLE"
    return f"{vertical}_{horizontal}"


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _node_value(node: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in node and node.get(name) is not None:
            return node.get(name)
    return None


def _role(class_name: str, explicit: Any = None) -> str:
    if explicit:
        return str(explicit)
    value = str(class_name or "").rsplit(".", 1)[-1]
    return value.upper() if value else ""


def build_observation(
    raw: Mapping[str, Any],
    *,
    locale: str,
    provenance: Iterable[Mapping[str, Any]],
    viewport: tuple[int, int] = (1080, 2640),
    dynamic_device_names: Iterable[str] = (),
) -> CanonicalObservation:
    node = raw.get("node")
    node = node if isinstance(node, Mapping) else {}
    visible = _text(
        raw.get("visible_text")
        or _node_value(node, "text")
        or raw.get("content_description")
        or _node_value(node, "contentDescription", "content_description")
    )
    content_description = _text(
        raw.get("content_description")
        or _node_value(node, "contentDescription", "content_description")
    )
    hint = _text(raw.get("hint") or _node_value(node, "hint", "hintText"))
    state_description = _text(
        raw.get("state_description")
        or _node_value(node, "stateDescription", "state_description")
    )
    speech_value = _text(raw.get("talkback_speech"))
    announcement = _text(raw.get("announcement") or speech_value)
    normalized_text = normalize_text(
        visible,
        locale=locale,
        dynamic_device_names=dynamic_device_names,
    )
    normalized_speech = normalize_text(
        speech_value or announcement,
        locale=locale,
        dynamic_device_names=dynamic_device_names,
        speech=True,
    )
    bounds = parse_bounds(
        raw.get("bounds")
        or _node_value(node, "boundsInScreen", "bounds", "bounds_in_screen")
    )
    class_name = _text(
        raw.get("class_name") or _node_value(node, "className", "class_name")
    )
    resource_id = _text(
        raw.get("resource_id")
        or _node_value(
            node,
            "viewIdResourceName",
            "resourceId",
            "resource_id",
        )
    )
    package = _text(
        raw.get("package")
        or _node_value(node, "packageName", "package", "package_name")
    )
    parent = _text(
        raw.get("parent_signature")
        or _node_value(node, "parentPath", "parent_path")
    )
    ancestor = _text(
        raw.get("ancestor_signature")
        or _node_value(node, "nodePath", "node_path")
        or parent
    )
    identity_source = {
        "schema": OBSERVATION_SCHEMA_VERSION,
        "scenario_id": _text(raw.get("scenario_id")),
        "step_index": _integer(raw.get("step_index")),
        "transaction_id": _text(raw.get("transaction_id")),
        "record_locator": (
            f"xlsx-row:{raw.get('xlsx_row_number')}"
            if raw.get("xlsx_row_number") is not None
            else f"record:{raw.get('record_index')}"
            if raw.get("record_index") is not None
            else ""
        ),
        "resource_id": resource_id,
        "class_name": class_name,
        "bounds": bounds,
        "visible_semantic": normalized_text["semantic"],
        "speech_semantic": normalized_speech["semantic"],
    }
    observation_id = "observation_" + canonical_sha256(identity_source)[:24]
    markers = tuple(
        {
            **item,
            "channel": "VISIBLE_TEXT",
        }
        for item in normalized_text["dynamic_markers"]
    ) + tuple(
        {
            **item,
            "channel": "TALKBACK_SPEECH",
        }
        for item in normalized_speech["dynamic_markers"]
    )
    return CanonicalObservation(
        observation_schema=OBSERVATION_SCHEMA_VERSION,
        observation_id=observation_id,
        scenario_id=_text(raw.get("scenario_id")),
        step_index=_integer(raw.get("step_index")),
        transaction_id=_text(raw.get("transaction_id")),
        request_id=_text(raw.get("request_id")),
        action_type=_text(raw.get("action_type")),
        terminal=bool(raw.get("terminal")),
        package=package,
        resource_id=resource_id,
        class_name=class_name,
        role=_role(class_name, raw.get("role")),
        bounds=bounds,
        bounds_region=bounds_region(bounds, viewport=viewport),
        accessibility_focused=_bool(
            raw.get("accessibility_focused")
            if "accessibility_focused" in raw
            else _node_value(
                node,
                "accessibilityFocused",
                "accessibility_focused",
            )
        ),
        focusable=_bool(
            raw.get("focusable")
            if "focusable" in raw
            else _node_value(node, "focusable")
        ),
        clickable=_bool(
            raw.get("clickable")
            if "clickable" in raw
            else _node_value(node, "clickable")
        ),
        enabled=_bool(
            raw.get("enabled")
            if "enabled" in raw
            else _node_value(node, "enabled")
        ),
        selected=_bool(
            raw.get("selected")
            if "selected" in raw
            else _node_value(node, "selected")
        ),
        checked=_bool(
            raw.get("checked")
            if "checked" in raw
            else _node_value(node, "checked")
        ),
        scrollable=_bool(
            raw.get("scrollable")
            if "scrollable" in raw
            else _node_value(node, "scrollable")
        ),
        parent_signature=parent,
        ancestor_signature=ancestor,
        sibling_signature=_text(raw.get("sibling_signature")),
        visible_text=visible,
        content_description=content_description,
        hint=hint,
        state_description=state_description,
        talkback_speech=speech_value,
        announcement=announcement,
        locale=locale,
        normalized_text=normalized_text,
        normalized_speech=normalized_speech,
        dynamic_value_markers=markers,
        mismatch_type=_text(raw.get("mismatch_type")).upper(),
        raw_result=_text(raw.get("raw_result")).upper(),
        identity_verdict=_text(raw.get("identity_verdict")).upper(),
        progress_verdict=_text(raw.get("progress_verdict")).upper(),
        visit_verdict=_text(raw.get("visit_verdict")).upper(),
        stop_reason=_text(raw.get("stop_reason")),
        recovery_result=_text(raw.get("recovery_result")).upper(),
        duplicate_of_step=_integer(raw.get("duplicate_of_step")),
        coverage_signature=_text(raw.get("coverage_signature")),
        coverage_status=_text(raw.get("coverage_status")).upper(),
        provenance=tuple(dict(item) for item in provenance),
    )


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


__all__ = [
    "bounds_region",
    "build_observation",
    "normalize_text",
    "parse_bounds",
    "parse_json_object",
]
