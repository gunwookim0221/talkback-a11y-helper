import ast
import json
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def generate_output_path() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"output/talkback_compare_{timestamp}.xlsx"


def to_json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def parse_bounds_str(bounds_value: Any) -> tuple[int, int, int, int] | None:
    if bounds_value is None:
        return None
    try:
        parts: list[int]
        if isinstance(bounds_value, dict):
            l = int(bounds_value.get("l"))
            t = int(bounds_value.get("t"))
            r = int(bounds_value.get("r"))
            b = int(bounds_value.get("b"))
            parts = [l, t, r, b]
        else:
            bounds_str = str(bounds_value).strip()
            if not bounds_str:
                return None
            if bounds_str.startswith("{") and bounds_str.endswith("}"):
                parsed_dict = ast.literal_eval(bounds_str)
                if isinstance(parsed_dict, dict):
                    l = int(parsed_dict.get("l"))
                    t = int(parsed_dict.get("t"))
                    r = int(parsed_dict.get("r"))
                    b = int(parsed_dict.get("b"))
                    parts = [l, t, r, b]
                else:
                    return None
            else:
                parts = [int(x.strip()) for x in bounds_str.split(",")]
                if len(parts) != 4:
                    return None
        l, t, r, b = parts
        if r <= l or b <= t:
            return None
        return l, t, r, b
    except Exception:
        return None


def _safe_regex_search(pattern: str, value: str) -> bool:
    if not pattern:
        return False
    try:
        return bool(re.search(pattern, value or "", flags=re.IGNORECASE))
    except re.error as exc:
        logger.warning("Invalid regex pattern ignored: %r (%s)", pattern, exc)
        return False


def sanitize_filename(value: str) -> str:
    keep = []
    for ch in value:
        if ch.isalnum() or ch in ("_", "-", "."):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep).strip("_") or "item"


def make_main_fingerprint(step: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(step.get("normalized_visible_label", "") or "").strip(),
        str(step.get("focus_view_id", "") or "").strip(),
        str(step.get("focus_bounds", "") or "").strip(),
    )


def make_overlay_entry_fingerprint(tab_name: str, step: dict[str, Any]) -> str:
    focus_view_id = str(step.get("focus_view_id", "") or "").strip()
    normalized_visible_label = str(step.get("normalized_visible_label", "") or "").strip()
    return f"{tab_name}|{focus_view_id}|{normalized_visible_label}"


def _normalize_fingerprint_text(value: Any, max_len: int = 80) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) > max_len:
        return normalized[:max_len]
    return normalized


def normalize_semantic_text(value: Any, max_len: int = 120) -> str:
    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"smartthings[-_\s]*air[-_\s]*plugin", " ", normalized)
    normalized = re.sub(r"[^0-9a-z가-힣]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) > max_len:
        return normalized[:max_len]
    return normalized


def _extract_bounds_center(bounds_value: Any) -> tuple[int, int]:
    parsed_bounds = parse_bounds_str(bounds_value)
    if parsed_bounds is None:
        return 0, 0
    left, top, right, bottom = parsed_bounds
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    return center_x, center_y


def build_row_fingerprint(row: dict[str, Any]) -> str:
    resource_id = _normalize_fingerprint_text(
        row.get("focus_view_id", "") or row.get("resource_id", "") or row.get("resourceId", "")
    )
    normalized_visible = _normalize_fingerprint_text(
        row.get("normalized_visible_label", "") or row.get("visible_label", "")
    )
    normalized_speech = _normalize_fingerprint_text(
        row.get("normalized_announcement", "") or row.get("merged_announcement", "")
    )
    center_x, center_y = _extract_bounds_center(row.get("focus_bounds", "") or row.get("bounds", ""))
    return f"{resource_id}|{normalized_visible}|{normalized_speech}|{center_x},{center_y}"


def build_row_semantic_fingerprint(row: dict[str, Any]) -> str:
    resource_id = normalize_semantic_text(
        row.get("focus_view_id", "") or row.get("resource_id", "") or row.get("resourceId", "")
    )
    normalized_visible = normalize_semantic_text(
        row.get("normalized_visible_label", "") or row.get("visible_label", "")
    )
    normalized_speech = normalize_semantic_text(
        row.get("normalized_announcement", "") or row.get("merged_announcement", "")
    )
    return f"{resource_id}|{normalized_visible}|{normalized_speech}"


def is_noise_row(row: dict[str, Any]) -> tuple[bool, str]:
    visible = _normalize_fingerprint_text(row.get("visible_label", "") or row.get("normalized_visible_label", ""))
    speech = _normalize_fingerprint_text(
        row.get("merged_announcement", "") or row.get("normalized_announcement", "")
    )

    if visible and not speech:
        return True, "speech_empty"
    if "battery" in speech or "percent" in speech:
        return True, "system_announcement"
    if speech and not visible:
        return True, "label_mismatch"
    return False, ""
