from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable


PROBE_ENV_VAR = "TB_V8_COVERAGE_PROBE"
EXPECTED_FOREGROUND_PACKAGE = "com.samsung.android.oneconnect"
SYSTEM_UI_PACKAGE = "com.android.systemui"
LAUNCHER_PACKAGES = {
    "com.sec.android.app.launcher",
    "com.android.launcher",
    "com.android.launcher3",
}
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_SCROLLS = 2
DEFAULT_LATE_VERIFICATION_TIMEOUT_MS = 500
DEFAULT_LATE_VERIFICATION_POLL_MS = 75
RETRYABLE_FOCUS_FAILURES = {"no_content_candidate_in_bounds", "focus_action_failed"}
PROMOTED_TARGET_STRATEGY = "promote_to_enclosing_actionable_container"
ORIGINAL_TARGET_STRATEGY = "original_bounds"
SUCCESS_SOURCE_HELPER = "HELPER_SUCCESS"
SUCCESS_SOURCE_LATE_FOCUS = "LATE_FOCUS_VERIFIED"
SUCCESS_SOURCE_LATE_SPEECH = "LATE_SPEECH_VERIFIED"
SUCCESS_SOURCE_LATE_VISIBLE_TEXT = "LATE_VISIBLE_TEXT_VERIFIED"
SUCCESS_SOURCE_FAILED = "FAILED"


def coverage_probe_results_path(output_path: str) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.stem}.coverage_probe_results.json")


def coverage_probe_results_aggregate_path(output_path: str) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.stem}.coverage_probe_results.aggregate.json")


def coverage_probe_plan_path(output_path: str) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.stem}.coverage_probe_plan.json")


def focusable_inventory_path(output_path: str) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.stem}.focusable_inventory.json")


def is_probe_enabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(PROBE_ENV_VAR, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _parse_bounds(value: Any) -> tuple[int, int, int, int] | None:
    numbers = [int(match.group(0)) for match in re.finditer(r"-?\d+", str(value or ""))]
    if len(numbers) < 4:
        return None
    left, top, right, bottom = numbers[:4]
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _format_bounds(bounds: tuple[int, int, int, int]) -> str:
    left, top, right, bottom = bounds
    return f"{left},{top},{right},{bottom}"


def _bounds_area(bounds: tuple[int, int, int, int]) -> int:
    return max(0, bounds[2] - bounds[0]) * max(0, bounds[3] - bounds[1])


def _bounds_center(bounds: tuple[int, int, int, int]) -> tuple[float, float]:
    return ((bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0)


def _contains_bounds(container: tuple[int, int, int, int], child: tuple[int, int, int, int]) -> bool:
    return container[0] <= child[0] and container[1] <= child[1] and container[2] >= child[2] and container[3] >= child[3]


def _overlap_ratio(container: tuple[int, int, int, int], child: tuple[int, int, int, int]) -> float:
    left = max(container[0], child[0])
    top = max(container[1], child[1])
    right = min(container[2], child[2])
    bottom = min(container[3], child[3])
    overlap = _bounds_area((left, top, right, bottom)) if right > left and bottom > top else 0
    child_area = _bounds_area(child)
    return float(overlap) / float(child_area or 1)


def _center_distance(left_bounds: tuple[int, int, int, int], right_bounds: tuple[int, int, int, int]) -> float:
    left_x, left_y = _bounds_center(left_bounds)
    right_x, right_y = _bounds_center(right_bounds)
    return ((left_x - right_x) ** 2 + (left_y - right_y) ** 2) ** 0.5


def _bounds_from_snapshot(snapshot: dict[str, Any]) -> tuple[int, int, int, int] | None:
    return _parse_bounds(snapshot.get("boundsInScreen") or snapshot.get("bounds") or "")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def _load_inventory_items(output_path: str) -> list[dict[str, Any]]:
    path = focusable_inventory_path(output_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _extract_package_from_window_text(text: str) -> str | None:
    for pattern in (
        r"mCurrentFocus=.*?\s([A-Za-z0-9_.]+)/",
        r"mFocusedApp=.*?\s([A-Za-z0-9_.]+)/",
        r"topResumedActivity=.*?\s([A-Za-z0-9_.]+)/",
        r"ResumedActivity:.*?\s([A-Za-z0-9_.]+)/",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _current_package(*, client: Any, dev: str | None) -> str:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return ""
    try:
        output = run_fn(["shell", "dumpsys", "window"], dev=dev, timeout=5.0)
    except TypeError:
        try:
            output = run_fn(["shell", "dumpsys", "window"], dev=dev)
        except Exception:
            return ""
    except Exception:
        return ""
    return str(_extract_package_from_window_text(str(output or "")) or "")


def _read_screen_state(*, client: Any, dev: str | None) -> str:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return "UNKNOWN"
    try:
        output = run_fn(["shell", "dumpsys", "power"], dev=dev, timeout=5.0)
    except TypeError:
        try:
            output = run_fn(["shell", "dumpsys", "power"], dev=dev)
        except Exception:
            return "UNKNOWN"
    except Exception:
        return "UNKNOWN"
    text = str(output or "")
    if re.search(r"mWakefulness=\s*Awake", text, re.IGNORECASE) or re.search(r"Display Power:\s*state=\s*ON", text, re.IGNORECASE):
        return "SCREEN_ON"
    if re.search(r"mWakefulness=\s*(Asleep|Dozing)", text, re.IGNORECASE) or re.search(r"Display Power:\s*state=\s*OFF", text, re.IGNORECASE):
        return "SCREEN_OFF"
    return "UNKNOWN"


def _read_keyguard_active(*, client: Any, dev: str | None) -> bool | None:
    run_fn = getattr(client, "_run", None)
    if not callable(run_fn):
        return None
    try:
        output = run_fn(["shell", "dumpsys", "window", "policy"], dev=dev, timeout=5.0)
    except TypeError:
        try:
            output = run_fn(["shell", "dumpsys", "window", "policy"], dev=dev)
        except Exception:
            return None
    except Exception:
        return None
    match = re.search(
        r"(?:isStatusBarKeyguard|mShowingLockscreen|mShowing)\s*=\s*(true|false|1|0)",
        str(output or ""),
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).lower() in {"true", "1"}


def _bool_field(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _is_related_bounds_leaf_candidate(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("probe_intent", "") or "") != "VERIFY_RELATED_BOUNDS":
        return False
    if str(candidate.get("coverage_status", "") or "").upper() != "UNKNOWN":
        return False
    if str(candidate.get("coverage_reason", "") or "") != "related_bounds_only":
        return False
    class_name = str(candidate.get("class_name", "") or "").strip()
    view_id = str(candidate.get("view_id", "") or "").strip()
    clickable = _bool_field(candidate.get("clickable"))
    focusable = _bool_field(candidate.get("focusable"))
    return bool(
        class_name == "android.widget.TextView"
        or clickable is False
        or focusable is False
        or not view_id
    )


def _is_actionable_container_like(item: dict[str, Any]) -> bool:
    clickable = _bool_field(item.get("clickable"))
    focusable = _bool_field(item.get("focusable"))
    has_focusable_descendant = _bool_field(item.get("has_focusable_descendant"))
    descriptor = " ".join(
        str(item.get(key, "") or "")
        for key in ("class_name", "view_id", "label", "contentDescription", "content_description")
    ).lower()
    return bool(
        clickable is True
        or focusable is True
        or has_focusable_descendant is True
        or any(hint.lower() in descriptor for hint in ("Card", "Capability", "Row", "Item"))
    )


def _is_generic_root_like(item: dict[str, Any], bounds: tuple[int, int, int, int], max_area: int) -> bool:
    label = _normalize_text(item.get("label", ""))
    class_name = _normalize_text(item.get("class_name", ""))
    view_id = _normalize_text(item.get("view_id", ""))
    area = _bounds_area(bounds)
    nearly_full_screen = bool(max_area and area >= max_area * 0.85)
    generic_label = label in {"smartthings plugin", "smartthings", "plugin", "main", "primary", "screen"}
    generic_class = any(token in class_name for token in ("decor", "screen", "root"))
    generic_view_id = view_id in {"root", "main", "primary"}
    return nearly_full_screen and (generic_label or generic_class or generic_view_id)


def _candidate_equivalent_to_item(candidate: dict[str, Any], item: dict[str, Any]) -> bool:
    return (
        _normalize_text(candidate.get("label", "")) == _normalize_text(item.get("label", ""))
        and str(candidate.get("view_id", "") or "").strip() == str(item.get("view_id", "") or "").strip()
        and _parse_bounds(candidate.get("bounds")) == _parse_bounds(item.get("bounds"))
    )


def _promotion_target_metadata(item: dict[str, Any], bounds: tuple[int, int, int, int]) -> dict[str, Any]:
    return {
        "probe_bounds": _format_bounds(bounds),
        "probe_target_strategy": PROMOTED_TARGET_STRATEGY,
        "probe_target_source": "focusable_inventory",
        "probe_target_label": str(item.get("label", "") or ""),
        "probe_target_view_id": str(item.get("view_id", "") or ""),
        "probe_target_class_name": str(item.get("class_name", "") or ""),
        "probe_target_clickable": _bool_field(item.get("clickable")),
        "probe_target_focusable": _bool_field(item.get("focusable")),
    }


def _original_target_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "probe_bounds": str(candidate.get("bounds", "") or "").strip(),
        "probe_target_strategy": ORIGINAL_TARGET_STRATEGY,
        "probe_target_source": "candidate",
        "probe_target_label": str(candidate.get("label", "") or ""),
        "probe_target_view_id": str(candidate.get("view_id", "") or ""),
        "probe_target_class_name": str(candidate.get("class_name", "") or ""),
        "probe_target_clickable": _bool_field(candidate.get("clickable")),
        "probe_target_focusable": _bool_field(candidate.get("focusable")),
    }


def _resolve_probe_target(candidate: dict[str, Any], inventory_items: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = {**candidate, **_original_target_metadata(candidate)}
    candidate_bounds = _parse_bounds(candidate.get("bounds"))
    if candidate_bounds is None or not _is_related_bounds_leaf_candidate(candidate):
        return resolved

    inventory_bounds = [
        parsed
        for item in inventory_items
        if (parsed := _parse_bounds(item.get("bounds"))) is not None
    ]
    max_area = max((_bounds_area(bounds) for bounds in inventory_bounds), default=0)
    matches: list[tuple[tuple[int, int, int, int], dict[str, Any], tuple[Any, ...]]] = []
    for item in inventory_items:
        item_bounds = _parse_bounds(item.get("bounds"))
        if item_bounds is None:
            continue
        if _candidate_equivalent_to_item(candidate, item):
            continue
        contains = _contains_bounds(item_bounds, candidate_bounds)
        overlap = _overlap_ratio(item_bounds, candidate_bounds)
        if not contains and overlap < 0.80:
            continue
        if not _is_actionable_container_like(item):
            continue
        if _is_generic_root_like(item, item_bounds, max_area):
            continue
        item_area = _bounds_area(item_bounds)
        candidate_area = _bounds_area(candidate_bounds)
        if item_area <= candidate_area:
            continue
        useful_label = bool(_normalize_text(item.get("label", "")) and _normalize_text(item.get("label", "")) not in {"smartthings plugin"})
        score = (
            0 if contains else 1,
            0 if _is_actionable_container_like(item) else 1,
            item_area,
            _center_distance(item_bounds, candidate_bounds),
            0 if useful_label else 1,
        )
        matches.append((item_bounds, item, score))

    if not matches:
        return resolved
    target_bounds, target_item, _score = min(matches, key=lambda entry: entry[2])
    return {**resolved, **_promotion_target_metadata(target_item, target_bounds)}


def _raw_action_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    raw = result.get("raw")
    return raw if isinstance(raw, dict) else result


def _action_success(result: Any) -> bool:
    if not isinstance(result, dict):
        return bool(result)
    raw = _raw_action_result(result)
    return bool(result.get("success")) or bool(raw.get("success"))


def _action_reason(result: Any) -> str:
    if isinstance(result, dict):
        raw = _raw_action_result(result)
        return str(raw.get("reason") or raw.get("detail") or result.get("detail") or result.get("reason") or "").strip()
    return ""


def _focus_label(snapshot: Any) -> str:
    if not isinstance(snapshot, dict):
        return ""
    for key in (
        "mergedLabel",
        "talkbackLabel",
        "visible_label",
        "actual_focus_visible",
        "text",
        "contentDescription",
        "content_description",
        "label",
    ):
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _capture_focus_snapshot(client: Any, dev: Any, *, wait_seconds: float = 1.0) -> dict[str, Any]:
    get_focus = getattr(client, "get_focus", None)
    if not callable(get_focus):
        return {}
    try:
        focus = get_focus(dev=dev, wait_seconds=wait_seconds, allow_fallback_dump=False, mode="fast")
    except TypeError:
        try:
            focus = get_focus(dev=dev)
        except Exception:
            return {}
    except Exception:
        return {}
    return focus if isinstance(focus, dict) else {}


def _extract_focus_from_result(result: Any) -> dict[str, Any]:
    raw = _raw_action_result(result)
    focused = raw.get("focused") if isinstance(raw.get("focused"), dict) else None
    target = raw.get("target") if isinstance(raw.get("target"), dict) else None
    return focused or target or {}


def _captured_speech(client: Any, focus_snapshot: dict[str, Any], result: Any) -> str:
    merged = str(getattr(client, "last_merged_announcement", "") or "").strip()
    if merged:
        return merged
    raw = _raw_action_result(result)
    for key in ("actual_focus_speech", "merged_announcement", "speech", "talkbackLabel", "mergedLabel"):
        value = raw.get(key) if isinstance(raw, dict) else ""
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _focus_label(focus_snapshot)


def _captured_visible_text(focus_snapshot: dict[str, Any], result: Any) -> str:
    label = _focus_label(focus_snapshot)
    if label:
        return label
    result_focus = _extract_focus_from_result(result)
    return _focus_label(result_focus)


def _matched_expected_label(candidate: dict[str, Any], speech: str, visible: str, focus_snapshot: dict[str, Any]) -> bool:
    expected = _normalize_text(candidate.get("label", ""))
    if not expected:
        return False
    focus_label = _normalize_text(_focus_label(focus_snapshot))
    speech_norm = _normalize_text(speech)
    visible_norm = _normalize_text(visible)
    target_label = _normalize_text(candidate.get("probe_target_label", ""))
    return bool(
        (speech_norm and expected in speech_norm)
        or (visible_norm and expected in visible_norm)
        or (focus_label and focus_label == expected)
        or (
            target_label
            and expected in target_label
            and (
                (focus_label and (focus_label in target_label or target_label in focus_label))
                or (speech_norm and (speech_norm in target_label or target_label in speech_norm))
                or (visible_norm and (visible_norm in target_label or target_label in visible_norm))
            )
        )
    )


def _observed_text_matches_candidate(candidate: dict[str, Any], value: str) -> bool:
    observed = _normalize_text(value)
    if not observed:
        return False
    expected = _normalize_text(candidate.get("label", ""))
    target_label = _normalize_text(candidate.get("probe_target_label", ""))
    if expected and expected in observed:
        return True
    if target_label and (observed in target_label or target_label in observed):
        return True
    return bool(expected and target_label and expected in target_label and observed in target_label)


def _late_focus_signal(candidate: dict[str, Any], focus_snapshot: dict[str, Any]) -> bool:
    if not focus_snapshot:
        return False
    expected_view_id = str(candidate.get("probe_target_view_id", "") or "").strip()
    actual_view_id = str(focus_snapshot.get("viewIdResourceName", "") or "").strip()
    if expected_view_id and actual_view_id == expected_view_id:
        return True
    expected_class = str(candidate.get("probe_target_class_name", "") or "").strip()
    actual_class = str(focus_snapshot.get("className", "") or "").strip()
    probe_bounds = _parse_bounds(candidate.get("probe_bounds"))
    actual_bounds = _bounds_from_snapshot(focus_snapshot)
    if probe_bounds is None or actual_bounds is None:
        return False
    if expected_class and actual_class and expected_class != actual_class:
        return False
    return _overlap_ratio(probe_bounds, actual_bounds) >= 0.60 or _overlap_ratio(actual_bounds, probe_bounds) >= 0.60


def _late_success_source(candidate: dict[str, Any], focus_snapshot: dict[str, Any], speech: str, visible: str) -> str:
    if not _late_focus_signal(candidate, focus_snapshot):
        return ""
    focus_label_matches = _observed_text_matches_candidate(candidate, _focus_label(focus_snapshot))
    speech_matches = _observed_text_matches_candidate(candidate, speech)
    visible_matches = _observed_text_matches_candidate(candidate, visible)
    if focus_label_matches:
        return SUCCESS_SOURCE_LATE_FOCUS
    if speech_matches:
        return SUCCESS_SOURCE_LATE_SPEECH
    if visible_matches:
        return SUCCESS_SOURCE_LATE_VISIBLE_TEXT
    return ""


def _late_verification_result(
    client: Any,
    dev: Any,
    candidate: dict[str, Any],
    helper_result: Any,
    *,
    timeout_ms: int,
    poll_interval_ms: int,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + max(0, timeout_ms) / 1000.0
    poll_interval = max(0.0, poll_interval_ms / 1000.0)
    last_focus: dict[str, Any] = {}
    last_speech = ""
    last_visible = ""
    source = ""

    while True:
        last_focus = _capture_focus_snapshot(client, dev, wait_seconds=0.10)
        last_speech = _captured_speech(client, last_focus, helper_result)
        last_visible = _captured_visible_text(last_focus, helper_result)
        source = _late_success_source(candidate, last_focus, last_speech, last_visible)
        if source:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "late_verification_started": True,
        "late_verification_elapsed_ms": elapsed_ms,
        "late_focus_detected": _late_focus_signal(candidate, last_focus),
        "late_speech_detected": _observed_text_matches_candidate(candidate, last_speech),
        "late_visible_text_detected": _observed_text_matches_candidate(candidate, last_visible),
        "probe_success_source": source or SUCCESS_SOURCE_FAILED,
        "after_focus": last_focus,
        "captured_speech": last_speech,
        "captured_visible_text": last_visible,
        "matched_expected_label": _matched_expected_label(candidate, last_speech, last_visible, last_focus),
    }


def _node_signature(node: Any) -> list[tuple[str, str]]:
    if not isinstance(node, dict):
        return []
    labels: list[tuple[str, str]] = []
    text = _focus_label(node)
    bounds = node.get("boundsInScreen") or node.get("bounds") or ""
    if text:
        labels.append((text, json.dumps(_json_safe(bounds), ensure_ascii=False, sort_keys=True)))
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            labels.extend(_node_signature(child))
    return labels


def _viewport_signature(client: Any, dev: Any) -> str:
    dump_tree = getattr(client, "dump_tree", None)
    if not callable(dump_tree):
        return ""
    try:
        nodes = dump_tree(dev=dev)
    except Exception:
        return ""
    if not isinstance(nodes, list):
        return ""
    signature: list[tuple[str, str]] = []
    for node in nodes:
        signature.extend(_node_signature(node))
    return json.dumps(signature[:80], ensure_ascii=False, sort_keys=True)


def _scroll_forward(client: Any, dev: Any) -> bool:
    scroll = getattr(client, "scroll", None)
    if not callable(scroll):
        return False
    try:
        return bool(scroll(dev=dev, direction="down"))
    except TypeError:
        try:
            return bool(scroll(dev, "down"))
        except Exception:
            return False
    except Exception:
        return False


def _empty_result_payload(enabled: bool, probe_plan_path: str, output_path: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "v8_coverage_probe_results",
        "enabled": bool(enabled),
        "probe_plan_path": str(probe_plan_path),
        "output_path": str(output_path),
        "summary": {
            "candidate_count": 0,
            "attempted_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "scroll_attempt_count": 0,
            "promoted_target_count": 0,
            "original_target_count": 0,
        },
        "results": [],
    }


def _skip_result(candidate: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **_candidate_result_base(candidate),
        "probe_method": "helper_focus_in_bounds_scroll_retry",
        "attempted": False,
        "probe_skipped": True,
        "skip_reason": reason,
        "probe_success": False,
        "probe_success_source": SUCCESS_SOURCE_FAILED,
        "helper_success": False,
        "helper_result": {},
        "late_verification_started": False,
        "late_verification_elapsed_ms": 0,
        "late_focus_detected": False,
        "late_speech_detected": False,
        "late_visible_text_detected": False,
        "attempt_count": 0,
        "scroll_attempt_count": 0,
        "failure_reason": reason,
        "before_focus": {},
        "after_focus": {},
        "captured_speech": "",
        "captured_visible_text": "",
        "matched_expected_label": False,
        "foreground_package": "",
        "screen_state": "",
        "keyguard_active": None,
        "candidate_scenario_id": str(candidate.get("scenario_id", "") or ""),
        "notes": [reason],
    }


def _candidate_result_base(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "label",
        "normalized_label",
        "scenario_id",
        "tab_name",
        "view_id",
        "bounds",
        "taxonomy",
        "coverage_status",
        "coverage_reason",
        "probe_intent",
        "probe_priority",
        "probe_bounds",
        "probe_target_strategy",
        "probe_target_source",
        "probe_target_label",
        "probe_target_view_id",
        "probe_target_class_name",
        "probe_target_clickable",
        "probe_target_focusable",
    )
    return {key: candidate.get(key, "") for key in keys}


def _scenario_filtered_result(candidate: dict[str, Any], current_scenario_id: str) -> dict[str, Any]:
    result = _skip_result(candidate, "scenario_mismatch")
    result["current_scenario_id"] = current_scenario_id
    return result


def _screen_guard_result(candidate: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    result = _skip_result(candidate, str(context.get("skip_reason", "") or "screen_not_active"))
    result["foreground_package"] = str(context.get("foreground_package", "") or "")
    result["screen_state"] = str(context.get("screen_state", "") or "")
    result["keyguard_active"] = context.get("keyguard_active")
    result["current_scenario_id"] = str(context.get("current_scenario_id", "") or "")
    return result


def _probe_runtime_context(client: Any, dev: Any, candidate: dict[str, Any], current_scenario_id: str) -> dict[str, Any]:
    foreground_package = _current_package(client=client, dev=dev)
    screen_state = _read_screen_state(client=client, dev=dev)
    keyguard_active = _read_keyguard_active(client=client, dev=dev)
    skip_reason = ""
    if screen_state == "SCREEN_OFF" or keyguard_active is True:
        skip_reason = "screen_not_active"
    elif foreground_package == SYSTEM_UI_PACKAGE:
        skip_reason = "foreground_not_target_app"
    elif foreground_package in LAUNCHER_PACKAGES:
        skip_reason = "foreground_not_target_app"
    elif foreground_package and foreground_package != EXPECTED_FOREGROUND_PACKAGE:
        skip_reason = "foreground_not_target_app"
    return {
        "foreground_package": foreground_package,
        "screen_state": screen_state,
        "keyguard_active": keyguard_active,
        "skip_reason": skip_reason,
        "current_scenario_id": current_scenario_id,
        "candidate_scenario_id": str(candidate.get("scenario_id", "") or ""),
    }


def _probe_candidate(
    client: Any,
    dev: Any,
    candidate: dict[str, Any],
    *,
    max_attempts: int,
    max_scrolls: int,
    late_verification_timeout_ms: int,
    late_verification_poll_ms: int,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before_focus = _capture_focus_snapshot(client, dev)
    focus_package = str(before_focus.get("packageName", "") or before_focus.get("package_name", "") or "")
    if focus_package and focus_package != EXPECTED_FOREGROUND_PACKAGE:
        return _screen_guard_result(
            candidate,
            {
                **(runtime_context or {}),
                "skip_reason": "focus_outside_target_app",
            },
        )
    attempt_count = 0
    scroll_attempt_count = 0
    last_failure = ""
    notes: list[str] = []
    after_focus: dict[str, Any] = {}
    captured_speech = ""
    captured_visible = ""
    matched = False
    last_helper_result: Any = {}
    last_late_result: dict[str, Any] = {}
    focus_in_bounds = getattr(client, "focus_in_bounds", None)
    bounds = str(candidate.get("probe_bounds") or candidate.get("bounds", "") or "").strip()

    while attempt_count < max_attempts:
        attempt_count += 1
        result = focus_in_bounds(dev=dev, bounds=bounds)
        last_helper_result = result
        helper_success = _action_success(result)
        if helper_success:
            result_focus = _extract_focus_from_result(result)
            after_focus = _capture_focus_snapshot(client, dev) or result_focus
            captured_speech = _captured_speech(client, after_focus or result_focus, result)
            captured_visible = _captured_visible_text(after_focus or result_focus, result)
            matched = _matched_expected_label(candidate, captured_speech, captured_visible, after_focus or result_focus)
            if not matched:
                notes.append("focused_node_label_mismatch")
            return {
                **_candidate_result_base(candidate),
                "probe_method": "helper_focus_in_bounds_scroll_retry",
                "attempted": True,
                "probe_success": True,
                "probe_success_source": SUCCESS_SOURCE_HELPER,
                "helper_success": True,
                "helper_result": _json_safe(_raw_action_result(result)),
                "late_verification_started": False,
                "late_verification_elapsed_ms": 0,
                "late_focus_detected": False,
                "late_speech_detected": False,
                "late_visible_text_detected": False,
                "attempt_count": attempt_count,
                "scroll_attempt_count": scroll_attempt_count,
                "failure_reason": None,
                "before_focus": before_focus,
                "after_focus": after_focus or result_focus,
                "captured_speech": captured_speech,
                "captured_visible_text": captured_visible,
                "matched_expected_label": matched,
                "notes": notes,
            }

        last_failure = _action_reason(result) or "focus_in_bounds_failed"
        late_result = _late_verification_result(
            client,
            dev,
            candidate,
            result,
            timeout_ms=late_verification_timeout_ms,
            poll_interval_ms=late_verification_poll_ms,
        )
        last_late_result = late_result
        if late_result["probe_success_source"] != SUCCESS_SOURCE_FAILED:
            return {
                **_candidate_result_base(candidate),
                "probe_method": "helper_focus_in_bounds_scroll_retry",
                "attempted": True,
                "probe_success": True,
                "probe_success_source": late_result["probe_success_source"],
                "helper_success": False,
                "helper_result": _json_safe(_raw_action_result(result)),
                "late_verification_started": True,
                "late_verification_elapsed_ms": late_result["late_verification_elapsed_ms"],
                "late_focus_detected": late_result["late_focus_detected"],
                "late_speech_detected": late_result["late_speech_detected"],
                "late_visible_text_detected": late_result["late_visible_text_detected"],
                "attempt_count": attempt_count,
                "scroll_attempt_count": scroll_attempt_count,
                "failure_reason": None,
                "before_focus": before_focus,
                "after_focus": late_result["after_focus"],
                "captured_speech": late_result["captured_speech"],
                "captured_visible_text": late_result["captured_visible_text"],
                "matched_expected_label": late_result["matched_expected_label"],
                "notes": notes,
            }
        if last_failure not in RETRYABLE_FOCUS_FAILURES:
            break
        if attempt_count >= max_attempts or scroll_attempt_count >= max_scrolls:
            break

        before_signature = _viewport_signature(client, dev)
        scroll_attempt_count += 1
        if not _scroll_forward(client, dev):
            last_failure = f"{last_failure}_scroll_failed"
            break
        after_signature = _viewport_signature(client, dev)
        if before_signature and after_signature and before_signature == after_signature:
            last_failure = f"{last_failure}_viewport_unchanged_after_scroll"
            break

    after_focus = _capture_focus_snapshot(client, dev)
    failure_reason = last_failure or "max_attempts_reached"
    if attempt_count >= max_attempts and last_failure in RETRYABLE_FOCUS_FAILURES:
        failure_reason = f"{last_failure}_after_scroll_retry"
    return {
        **_candidate_result_base(candidate),
        "probe_method": "helper_focus_in_bounds_scroll_retry",
        "attempted": True,
        "probe_success": False,
        "probe_success_source": SUCCESS_SOURCE_FAILED,
        "helper_success": False,
        "helper_result": _json_safe(_raw_action_result(last_helper_result)),
        "late_verification_started": bool(last_late_result),
        "late_verification_elapsed_ms": int(last_late_result.get("late_verification_elapsed_ms", 0) or 0),
        "late_focus_detected": bool(last_late_result.get("late_focus_detected")),
        "late_speech_detected": bool(last_late_result.get("late_speech_detected")),
        "late_visible_text_detected": bool(last_late_result.get("late_visible_text_detected")),
        "attempt_count": attempt_count,
        "scroll_attempt_count": scroll_attempt_count,
        "failure_reason": failure_reason,
        "before_focus": before_focus,
        "after_focus": after_focus,
        "captured_speech": _captured_speech(client, after_focus, {}),
        "captured_visible_text": _focus_label(after_focus),
        "matched_expected_label": False,
        "notes": notes,
    }


def build_probe_results_payload(
    client: Any,
    dev: Any,
    probe_plan: dict[str, Any],
    *,
    probe_plan_path: str,
    output_path: str,
    enabled: bool,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    late_verification_timeout_ms: int = DEFAULT_LATE_VERIFICATION_TIMEOUT_MS,
    late_verification_poll_ms: int = DEFAULT_LATE_VERIFICATION_POLL_MS,
    current_scenario_id: str = "",
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if not enabled:
        return _empty_result_payload(False, probe_plan_path, output_path)

    candidates = probe_plan.get("candidates", []) if isinstance(probe_plan, dict) else []
    inventory_items = _load_inventory_items(output_path)
    sorted_candidates = sorted(
        [(idx, candidate) for idx, candidate in enumerate(candidates) if isinstance(candidate, dict)],
        key=lambda item: (int(item[1].get("probe_priority", 999) or 999), item[0]),
    )
    results: list[dict[str, Any]] = []
    focus_in_bounds = getattr(client, "focus_in_bounds", None)
    scenario_filtered_count = 0
    screen_skipped_count = 0
    for _idx, candidate in sorted_candidates:
        candidate = _resolve_probe_target(candidate, inventory_items)
        bounds = str(candidate.get("bounds", "") or "").strip()
        candidate_scenario_id = str(candidate.get("scenario_id", "") or "")
        if current_scenario_id and candidate_scenario_id and candidate_scenario_id != current_scenario_id:
            scenario_filtered_count += 1
            if log_fn:
                log_fn(
                    "[FOCUSABLE][coverage_probe_skip] "
                    f"scenario_id='{current_scenario_id}' candidate_scenario_id='{candidate_scenario_id}' "
                    "probe_skipped=true skip_reason='scenario_mismatch'"
                )
            results.append(_scenario_filtered_result(candidate, current_scenario_id))
            continue
        if not bool(candidate.get("probe_eligible")):
            results.append(_skip_result(candidate, "probe_ineligible"))
            continue
        if str(candidate.get("probe_method_candidate", "") or "") != "helper_focus_in_bounds" or not bounds:
            results.append(_skip_result(candidate, "unsupported_probe_method"))
            continue
        if not callable(focus_in_bounds):
            results.append(_skip_result(candidate, "focus_in_bounds_unavailable"))
            continue
        runtime_context = _probe_runtime_context(client, dev, candidate, current_scenario_id)
        if runtime_context["skip_reason"]:
            screen_skipped_count += 1
            if log_fn:
                log_fn(
                    "[FOCUSABLE][coverage_probe_skip] "
                    f"scenario_id='{current_scenario_id}' candidate_scenario_id='{candidate_scenario_id}' "
                    f"foreground_package='{runtime_context['foreground_package']}' "
                    f"screen_state='{runtime_context['screen_state']}' "
                    "probe_skipped=true "
                    f"skip_reason='{runtime_context['skip_reason']}'"
                )
            results.append(_screen_guard_result(candidate, runtime_context))
            continue
        results.append(
            _probe_candidate(
                client,
                dev,
                candidate,
                max_attempts=max(1, int(max_attempts or DEFAULT_MAX_ATTEMPTS)),
                max_scrolls=max(0, int(max_scrolls or DEFAULT_MAX_SCROLLS)),
                late_verification_timeout_ms=max(0, int(late_verification_timeout_ms)),
                late_verification_poll_ms=max(1, int(late_verification_poll_ms)),
                runtime_context=runtime_context,
            )
        )

    attempted_count = sum(1 for result in results if bool(result.get("attempted")))
    success_count = sum(1 for result in results if bool(result.get("probe_success")))
    skipped_count = sum(1 for result in results if not bool(result.get("attempted")))
    failed_count = attempted_count - success_count
    scroll_attempt_count = sum(int(result.get("scroll_attempt_count", 0) or 0) for result in results)
    promoted_target_count = sum(1 for result in results if result.get("probe_target_strategy") == PROMOTED_TARGET_STRATEGY)
    original_target_count = sum(1 for result in results if result.get("probe_target_strategy") == ORIGINAL_TARGET_STRATEGY)
    return {
        "schema_version": 1,
        "source": "v8_coverage_probe_results",
        "enabled": True,
        "probe_plan_path": str(probe_plan_path),
        "output_path": str(output_path),
        "summary": {
            "candidate_count": len(sorted_candidates) - scenario_filtered_count,
            "attempted_count": attempted_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "scroll_attempt_count": scroll_attempt_count,
            "promoted_target_count": promoted_target_count,
            "original_target_count": original_target_count,
            "scenario_filtered_count": scenario_filtered_count,
            "screen_skipped_count": screen_skipped_count,
        },
        "results": results,
    }


def _int_summary(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _aggregate_plugin_name(results: list[Any]) -> str:
    for result in results:
        if not isinstance(result, dict):
            continue
        for key in ("plugin_name", "plugin", "tab_name"):
            value = str(result.get(key, "") or "").strip()
            if value:
                return value
    return ""


def _results_aggregate_entry(payload: dict[str, Any], current_scenario_id: str) -> dict[str, Any]:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
    scenario_id = str(current_scenario_id or "").strip()
    if not scenario_id:
        for result in results:
            if isinstance(result, dict) and str(result.get("scenario_id", "") or "").strip():
                scenario_id = str(result.get("scenario_id", "") or "").strip()
                break
    return {
        "scenario_id": scenario_id,
        "plugin_name": _aggregate_plugin_name(results),
        "candidate_count": _int_summary(summary, "candidate_count"),
        "attempted_count": _int_summary(summary, "attempted_count"),
        "success_count": _int_summary(summary, "success_count"),
        "failed_count": _int_summary(summary, "failed_count"),
        "skipped_count": _int_summary(summary, "skipped_count"),
        "screen_skipped_count": _int_summary(summary, "screen_skipped_count"),
        "scenario_filtered_count": _int_summary(summary, "scenario_filtered_count"),
        "summary": dict(summary),
        "results": results,
    }


def _build_results_aggregate(output_path: str, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "v8_probe_results_aggregate",
        "run_id": Path(output_path).stem,
        "output_path": str(output_path),
        "scenario_count": len(scenarios),
        "total_candidate_count": sum(_int_summary(item, "candidate_count") for item in scenarios),
        "total_attempted_count": sum(_int_summary(item, "attempted_count") for item in scenarios),
        "total_success_count": sum(_int_summary(item, "success_count") for item in scenarios),
        "total_failed_count": sum(_int_summary(item, "failed_count") for item in scenarios),
        "total_skipped_count": sum(_int_summary(item, "skipped_count") for item in scenarios),
        "total_screen_skipped_count": sum(_int_summary(item, "screen_skipped_count") for item in scenarios),
        "total_scenario_filtered_count": sum(_int_summary(item, "scenario_filtered_count") for item in scenarios),
        "scenarios": scenarios,
    }


def append_results_aggregate_file(
    payload: dict[str, Any],
    *,
    output_path: str,
    current_scenario_id: str = "",
) -> dict[str, Any]:
    target = coverage_probe_results_aggregate_path(output_path)
    scenarios: list[dict[str, Any]] = []
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            existing_scenarios = existing.get("scenarios", []) if isinstance(existing, dict) else []
            if isinstance(existing_scenarios, list):
                scenarios = [item for item in existing_scenarios if isinstance(item, dict)]
        except Exception:
            scenarios = []
    scenarios.append(_results_aggregate_entry(payload, current_scenario_id))
    aggregate = _build_results_aggregate(output_path, scenarios)
    target.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    return aggregate


def execute_probe_plan_file(
    client: Any,
    dev: Any,
    *,
    output_path: str,
    probe_plan_path: str | Path | None = None,
    enabled: bool = True,
    log_fn: Callable[[str], None] | None = None,
    current_scenario_id: str = "",
) -> dict[str, Any]:
    plan_path = Path(probe_plan_path) if probe_plan_path is not None else coverage_probe_plan_path(output_path)
    result_path = coverage_probe_results_path(output_path)
    if not plan_path.exists():
        payload = _empty_result_payload(enabled, str(plan_path), output_path)
        payload["summary"]["skipped_count"] = 0
        if enabled:
            payload["notes"] = ["probe_plan_missing"]
    else:
        try:
            plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception as exc:
            plan_payload = {"candidates": []}
            if log_fn:
                log_fn(f"[FOCUSABLE][coverage_probe_results_load_failed] path='{plan_path}' error='{exc}'")
        payload = build_probe_results_payload(
            client,
            dev,
            plan_payload,
            probe_plan_path=str(plan_path),
            output_path=output_path,
            enabled=enabled,
            current_scenario_id=current_scenario_id,
            log_fn=log_fn,
        )
    try:
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        if log_fn:
            log_fn(f"[FOCUSABLE][coverage_probe_results_save_failed] path='{result_path}' error='{exc}'")
    else:
        try:
            append_results_aggregate_file(
                payload,
                output_path=output_path,
                current_scenario_id=current_scenario_id,
            )
        except Exception as exc:
            if log_fn:
                aggregate_path = coverage_probe_results_aggregate_path(output_path)
                log_fn(f"[FOCUSABLE][coverage_probe_results_aggregate_save_failed] path='{aggregate_path}' error='{exc}'")
        try:
            from tb_runner import coverage_probe_validation

            coverage_probe_validation.write_validation_file(
                payload,
                probe_results_path=result_path,
                output_path=output_path,
                current_scenario_id=current_scenario_id,
            )
        except Exception as exc:
            if log_fn:
                validation_path = result_path.with_name(f"{Path(output_path).stem}.coverage_probe_validation.json")
                log_fn(f"[FOCUSABLE][coverage_probe_validation_save_failed] path='{validation_path}' error='{exc}'")
    return payload


def maybe_execute_probe_plan_file(
    client: Any,
    dev: Any,
    *,
    output_path: str,
    env: dict[str, str] | None = None,
    log_fn: Callable[[str], None] | None = None,
    current_scenario_id: str = "",
) -> dict[str, Any] | None:
    if not is_probe_enabled(env):
        return None
    return execute_probe_plan_file(
        client,
        dev,
        output_path=output_path,
        enabled=True,
        log_fn=log_fn,
        current_scenario_id=current_scenario_id,
    )
