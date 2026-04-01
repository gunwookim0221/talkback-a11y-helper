import ast
import json
import re
from datetime import datetime
from typing import Any


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
    return bool(re.search(pattern, value or "", flags=re.IGNORECASE))


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
