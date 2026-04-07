"""talkback_lib 공통 유틸 (비즈니스 로직 제외)."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable


def safe_parse_json_payload(payload: str, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{label} JSON 형식이 올바르지 않습니다.")
    return parsed


def normalize_for_comparison(text: str | None) -> str:
    if text is None:
        return ""

    normalized = str(text).replace("\n", " ").replace("\t", " ").strip().lower()
    normalized = re.sub(r"[,:;|]", " ", normalized)

    removable_phrases = (
        "double tap to activate",
        "double tap to open",
        "button",
        "selected",
        "disabled",
        "버튼",
        "선택됨",
        "사용 안 함",
    )
    for phrase in removable_phrases:
        normalized = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", normalized)

    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_value(item) for item in value]
    return str(value)


def normalize_bounds(node: dict[str, Any]) -> str:
    bounds = node.get("boundsInScreen")
    if isinstance(bounds, dict):
        left = bounds.get("left", bounds.get("l"))
        top = bounds.get("top", bounds.get("t"))
        right = bounds.get("right", bounds.get("r"))
        bottom = bounds.get("bottom", bounds.get("b"))
        return f"{left},{top},{right},{bottom}"
    if isinstance(bounds, str):
        return bounds
    return ""


def parse_bounds_tuple(bounds: str) -> tuple[int, int, int, int] | None:
    nums = [int(x) for x in re.findall(r"-?\d+", bounds)]
    if len(nums) >= 4:
        return nums[0], nums[1], nums[2], nums[3]
    return None


def parse_bottom_from_bounds(bounds: str) -> int:
    nums = [int(x) for x in re.findall(r"-?\d+", bounds)]
    if len(nums) >= 4:
        return nums[3]
    return -1


def null_safe_get(data: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(data, dict):
        return default
    return data.get(key, default)


def retry_call(func: Callable[[], Any], retries: int, delay_sec: float) -> Any:
    attempts = max(1, int(retries) + 1)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return func()
        except Exception as exc:  # pragma: no cover - helper only
            last_exc = exc
            if attempt >= attempts - 1:
                raise
            time.sleep(max(0.0, delay_sec))
    if last_exc is not None:
        raise last_exc
    return None


def measure_elapsed(started_at: float) -> float:
    return time.monotonic() - started_at
