from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Literal

from .adb import get_adb_status, get_helper_status, run_adb
from tb_runner.samsung_account_popup import (
    LATER_RESOURCE_ID as SAMSUNG_ACCOUNT_POPUP_LATER_RESOURCE_ID,
    find_samsung_account_popup_candidate,
)


SMARTTHINGS_PACKAGE = "com.samsung.android.oneconnect"
TALKBACK_PACKAGES = {
    "com.samsung.android.accessibility.talkback",
    "com.google.android.marvin.talkback",
}
KNOWN_EXTERNAL_POPUP_PACKAGES = {
    "com.android.vending": "google_play_review_or_rating_popup",
}
DISMISS_LABELS = (
    "not now",
    "no thanks",
    "cancel",
    "close",
    "dismiss",
    "아니요",
    "괜찮아요",
    "취소",
    "닫기",
)
DANGEROUS_POPUP_LABEL_TOKENS = (
    "submit",
    "send",
    "rate",
    "review",
    "rating",
    "리뷰",
    "평가",
    "제출",
    "보내기",
)
LaunchMode = Literal["warm", "clean"]


def normalize_launch_mode(value: str | None) -> LaunchMode:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "clean"}:
        return "clean"
    return "warm"


def is_talkback_enabled(enabled_services: str | None) -> bool:
    services = _split_enabled_accessibility_services(enabled_services)
    return any(service.split("/", 1)[0] in TALKBACK_PACKAGES for service in services)


def get_talkback_status(adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb) -> dict[str, object]:
    result = adb_runner(["shell", "settings", "get", "secure", "enabled_accessibility_services"], 8.0)
    enabled_services = str(result.get("stdout", "")).strip() if result.get("ok") else ""
    enabled = is_talkback_enabled(enabled_services)
    status = "enabled" if enabled else "disabled"
    if not result.get("ok"):
        status = "adb_error"
    return {
        **result,
        "status": status,
        "enabled": enabled,
        "enabled_accessibility_services": enabled_services,
        "accepted_packages": sorted(TALKBACK_PACKAGES),
    }


def open_accessibility_settings(adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb) -> dict[str, object]:
    return adb_runner(["shell", "am", "start", "-a", "android.settings.ACCESSIBILITY_SETTINGS"], 8.0)


def launch_smartthings(
    launch_mode: LaunchMode,
    *,
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
    sleep_fn: Callable[[float], None] = time.sleep,
    settle_seconds: float = 3.0,
) -> dict[str, object]:
    force_stop_attempted = launch_mode == "clean"
    force_stop_result: dict[str, object] | None = None
    if force_stop_attempted:
        force_stop_result = adb_runner(["shell", "am", "force-stop", SMARTTHINGS_PACKAGE], 8.0)

    monkey_result = adb_runner(
        ["shell", "monkey", "-p", SMARTTHINGS_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"],
        12.0,
    )
    monkey_success = bool(monkey_result.get("ok"))
    if monkey_success:
        sleep_fn(max(0.0, settle_seconds))

    return {
        "status": "ok" if monkey_success else "adb_error",
        "launch_mode": launch_mode,
        "force_stop_attempted": force_stop_attempted,
        "force_stop_ok": bool(force_stop_result.get("ok")) if force_stop_result is not None else None,
        "monkey_success": monkey_success,
        "force_stop_result": force_stop_result,
        "monkey_result": monkey_result,
    }


def get_foreground_package(adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb) -> dict[str, object]:
    window_result = adb_runner(["shell", "dumpsys", "window"], 8.0)
    package = _extract_foreground_package(str(window_result.get("stdout", "")))
    source = "dumpsys window"
    raw_result = window_result

    if not package:
        activity_result = adb_runner(["shell", "dumpsys", "activity", "activities"], 8.0)
        package = _extract_foreground_package(str(activity_result.get("stdout", "")))
        source = "dumpsys activity"
        raw_result = activity_result

    return {
        "status": "ok" if package else "unknown",
        "package": package,
        "expected_package": SMARTTHINGS_PACKAGE,
        "matches_expected": package == SMARTTHINGS_PACKAGE,
        "source": source,
        "ok": bool(raw_result.get("ok")),
        "error": raw_result.get("error"),
    }


def get_uiautomator_package_status(
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
) -> dict[str, object]:
    dump_result = adb_runner(["shell", "uiautomator", "dump", "/sdcard/qa_frontend_surface.xml"], 8.0)
    if not dump_result.get("ok"):
        return {"status": "unknown", "ok": False, "package": None, "focused_package": None, "error": dump_result.get("error")}
    cat_result = adb_runner(["shell", "cat", "/sdcard/qa_frontend_surface.xml"], 8.0)
    if not cat_result.get("ok"):
        return {"status": "unknown", "ok": False, "package": None, "focused_package": None, "error": cat_result.get("error")}
    return parse_uiautomator_package_status(str(cat_result.get("stdout", "")))


def parse_uiautomator_package_status(xml_text: str) -> dict[str, object]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {"status": "unknown", "ok": False, "package": None, "focused_package": None, "error": str(exc)}

    first_package = None
    focused_package = None
    for node in root.iter("node"):
        package = str(node.attrib.get("package", "") or "").strip()
        if package and first_package is None:
            first_package = package
        if package and str(node.attrib.get("focused", "")).lower() == "true":
            focused_package = package
            break

    package = focused_package or first_package
    return {
        "status": "ok" if package else "unknown",
        "ok": bool(package),
        "package": package,
        "root_package": first_package,
        "focused_package": focused_package,
    }


def get_launch_surface_status(adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb) -> dict[str, object]:
    foreground_status = get_foreground_package(adb_runner)
    uia_status = get_uiautomator_package_status(adb_runner)
    detected_external = _detect_external_popup_package(foreground_status, uia_status)
    return {
        "foreground_status": foreground_status,
        "uiautomator_status": uia_status,
        "foreground_package": foreground_status.get("package"),
        "uiautomator_package": uia_status.get("package"),
        "uiautomator_focused_package": uia_status.get("focused_package"),
        "external_popup_package": detected_external,
        "external_popup_reason": _external_popup_reason(foreground_status, uia_status, detected_external),
        "smartthings_ready": (
            foreground_status.get("package") == SMARTTHINGS_PACKAGE
            and uia_status.get("package") == SMARTTHINGS_PACKAGE
            and detected_external is None
        ),
    }


def poll_launch_surface_status(
    *,
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
    sleep_fn: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 4.0,
    interval_seconds: float = 0.7,
) -> dict[str, object]:
    last_status: dict[str, object] = {}
    max_polls = max(1, int(max(0.1, timeout_seconds) / max(0.1, interval_seconds)) + 1)
    for index in range(max_polls):
        last_status = get_launch_surface_status(adb_runner)
        if last_status.get("smartthings_ready") or last_status.get("external_popup_package"):
            return last_status
        if index < max_polls - 1:
            sleep_fn(max(0.1, interval_seconds))
    return last_status


def stabilize_external_popup(
    *,
    initial_foreground_status: dict[str, object] | None = None,
    initial_surface_status: dict[str, object] | None = None,
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_attempts: int = 2,
) -> dict[str, object]:
    surface_status = initial_surface_status or get_launch_surface_status(adb_runner)
    foreground_status = _dict(surface_status.get("foreground_status")) or initial_foreground_status or get_foreground_package(adb_runner)
    detected_package = str(surface_status.get("external_popup_package") or foreground_status.get("package") or "")
    detected_reason = str(surface_status.get("external_popup_reason") or KNOWN_EXTERNAL_POPUP_PACKAGES.get(detected_package) or "")
    attempts: list[dict[str, object]] = []

    if not detected_reason:
        return {
            "state": "not_detected",
            "popup_detected": False,
            "popup_package": None,
            "popup_dismissed": False,
            "popup_result": "not_detected",
            "detected_reason": None,
            "attempts": attempts,
            "foreground_after": foreground_status.get("package"),
            "foreground_status": foreground_status,
            "surface_status": surface_status,
        }

    popup_dismissed = False
    for attempt_index in range(1, max(1, max_attempts) + 1):
        try:
            candidate = find_popup_dismiss_candidate(adb_runner)
            if candidate:
                tap_result = tap_candidate_center(candidate, adb_runner)
                method = "label"
                result = "clicked" if tap_result.get("ok") else "click_failed"
                popup_dismissed = popup_dismissed or bool(tap_result.get("ok"))
                attempts.append(
                    {
                        "attempt": attempt_index,
                        "dismiss_method": method,
                        "dismiss_label": candidate.get("label"),
                        "back_attempted": False,
                        "result": result,
                    }
                )
            else:
                back_result = adb_runner(["shell", "input", "keyevent", "KEYCODE_BACK"], 5.0)
                attempts.append(
                    {
                        "attempt": attempt_index,
                        "dismiss_method": "back",
                        "dismiss_label": None,
                        "back_attempted": True,
                        "result": "back_sent" if back_result.get("ok") else "back_failed",
                    }
                )
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt_index,
                    "dismiss_method": "exception",
                    "dismiss_label": None,
                    "back_attempted": False,
                    "result": f"error:{exc}",
                }
            )

        sleep_fn(0.7)
        surface_status = poll_launch_surface_status(adb_runner=adb_runner, sleep_fn=sleep_fn, timeout_seconds=2.0)
        foreground_status = _dict(surface_status.get("foreground_status"))
        foreground_after = str(surface_status.get("foreground_package") or foreground_status.get("package") or "")
        external_after = str(surface_status.get("external_popup_package") or "")
        if foreground_after == SMARTTHINGS_PACKAGE and not external_after:
            return {
                "state": "cleared",
                "popup_detected": True,
                "popup_package": detected_package,
                "popup_dismissed": True,
                "popup_result": "cleared",
                "detected_reason": detected_reason,
                "attempts": attempts,
                "foreground_after": foreground_after,
                "foreground_status": foreground_status,
                "surface_status": surface_status,
            }
        if external_after not in KNOWN_EXTERNAL_POPUP_PACKAGES:
            break

    foreground_after = str(surface_status.get("foreground_package") or foreground_status.get("package") or "")
    external_after = str(surface_status.get("external_popup_package") or "")
    still_external = external_after in KNOWN_EXTERNAL_POPUP_PACKAGES
    return {
        "state": "uncleared" if still_external else "dismissed_unverified",
        "popup_detected": True,
        "popup_package": detected_package,
        "popup_dismissed": popup_dismissed,
        "popup_result": "uncleared" if still_external else "dismissed_unverified",
        "detected_reason": detected_reason,
        "attempts": attempts,
        "foreground_after": foreground_after or None,
        "foreground_status": foreground_status,
        "surface_status": surface_status,
    }


def find_popup_dismiss_candidate(
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
) -> dict[str, object] | None:
    dump_result = adb_runner(["shell", "uiautomator", "dump", "/sdcard/qa_frontend_popup.xml"], 8.0)
    if not dump_result.get("ok"):
        return None
    cat_result = adb_runner(["shell", "cat", "/sdcard/qa_frontend_popup.xml"], 8.0)
    if not cat_result.get("ok"):
        return None
    return find_dismiss_candidate_in_uiautomator_xml(str(cat_result.get("stdout", "")))


def find_dismiss_candidate_in_uiautomator_xml(xml_text: str) -> dict[str, object] | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    samsung_popup_candidate = _find_samsung_account_popup_candidate(root)
    if samsung_popup_candidate is not None:
        return samsung_popup_candidate

    candidates: dict[str, dict[str, object]] = {}
    for node in root.iter("node"):
        label = _node_label(node.attrib)
        if not label or _is_dangerous_popup_label(label):
            continue
        normalized = _normalize_label(label)
        if normalized not in DISMISS_LABELS:
            continue
        bounds = str(node.attrib.get("bounds", "") or "")
        center = _bounds_center(bounds)
        if not center:
            continue
        candidates.setdefault(normalized, {"label": label, "bounds": bounds, "x": center[0], "y": center[1]})

    for label in DISMISS_LABELS:
        if label in candidates:
            return candidates[label]
    return None


def _find_samsung_account_popup_candidate(root: ET.Element) -> dict[str, object] | None:
    candidate = find_samsung_account_popup_candidate(root.iter("node"))
    if candidate is None:
        return None
    return {
        "label": candidate.label,
        "bounds": candidate.bounds,
        "x": candidate.x,
        "y": candidate.y,
        "resource_id": candidate.resource_id,
        "popup_kind": candidate.popup_kind,
        "dismiss_method": candidate.method,
        "locale": candidate.locale,
        "title": candidate.title,
    }


def dismiss_samsung_account_popup(
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
) -> dict[str, object]:
    candidate = find_popup_dismiss_candidate(adb_runner)
    if not candidate or candidate.get("popup_kind") != "samsung_account_two_step":
        return {"popup_detected": False, "popup_dismissed": False, "dismiss_method": None, "candidate": None}
    tap_result = tap_candidate_center(candidate, adb_runner)
    return {
        "popup_detected": True,
        "popup_dismissed": bool(tap_result.get("ok")),
        "dismiss_method": "button3" if candidate.get("resource_id") == SAMSUNG_ACCOUNT_POPUP_LATER_RESOURCE_ID else "label_or_bounds",
        "candidate": candidate,
        "tap_result": tap_result,
    }


def tap_candidate_center(
    candidate: dict[str, object],
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
) -> dict[str, object]:
    x = int(candidate.get("x", 0) or 0)
    y = int(candidate.get("y", 0) or 0)
    if x <= 0 or y <= 0:
        return {"ok": False, "status": "error", "error": "invalid tap coordinates"}
    return adb_runner(["shell", "input", "tap", str(x), str(y)], 5.0)


def run_runtime_preflight(
    launch_mode: str | None,
    *,
    adb_status_fn: Callable[[], dict[str, object]] = get_adb_status,
    helper_status_fn: Callable[[], dict[str, object]] = get_helper_status,
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    normalized_launch_mode = normalize_launch_mode(launch_mode)
    adb_status = adb_status_fn()
    device_ready = bool(adb_status.get("ok")) and any(
        device.get("state") == "device" for device in _devices(adb_status)
    )
    if not device_ready:
        return _blocked_result(
            reason="adb_device_unavailable",
            launch_mode=normalized_launch_mode,
            adb_status=adb_status,
            helper_status=None,
            talkback_status=None,
            launch_status=None,
            foreground_status=None,
            accessibility_settings_opened=False,
        )

    helper_status = helper_status_fn()
    helper_state = _helper_state(helper_status)
    if helper_state != "ok":
        return _blocked_result(
            reason="helper_not_ready",
            launch_mode=normalized_launch_mode,
            adb_status=adb_status,
            helper_status=helper_status,
            talkback_status=None,
            launch_status=None,
            foreground_status=None,
            accessibility_settings_opened=False,
        )

    talkback_status = get_talkback_status(adb_runner)
    accessibility_settings_opened = False
    accessibility_settings_result = None
    if talkback_status.get("status") != "enabled":
        accessibility_settings_result = open_accessibility_settings(adb_runner)
        accessibility_settings_opened = bool(accessibility_settings_result.get("ok"))
        result = _blocked_result(
            reason="talkback_disabled",
            launch_mode=normalized_launch_mode,
            adb_status=adb_status,
            helper_status=helper_status,
            talkback_status=talkback_status,
            launch_status=None,
            foreground_status=None,
            accessibility_settings_opened=accessibility_settings_opened,
        )
        result["accessibility_settings_result"] = accessibility_settings_result
        result["user_message"] = (
            "TalkBack is disabled. Please enable TalkBack and retry."
            if not accessibility_settings_opened
            else "TalkBack is disabled. Accessibility settings opened on device. Please enable TalkBack and retry."
        )
        return result

    return _run_launch_surface_preflight(
        normalized_launch_mode=normalized_launch_mode,
        adb_status=adb_status,
        helper_status=helper_status,
        helper_state=helper_state,
        talkback_status=talkback_status,
        talkback_state="enabled",
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
    )


def run_surface_preflight(
    launch_mode: str | None,
    *,
    adb_status_fn: Callable[[], dict[str, object]] = get_adb_status,
    adb_runner: Callable[[list[str], float], dict[str, object]] = run_adb,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Prepare the app surface; the core runtime owns readiness checks."""
    normalized_launch_mode = normalize_launch_mode(launch_mode)
    adb_status = adb_status_fn()
    device_ready = bool(adb_status.get("ok")) and any(
        device.get("state") == "device" for device in _devices(adb_status)
    )
    if not device_ready:
        return _blocked_result(
            reason="adb_device_unavailable",
            launch_mode=normalized_launch_mode,
            adb_status=adb_status,
            helper_status=None,
            talkback_status=None,
            launch_status=None,
            foreground_status=None,
            accessibility_settings_opened=False,
        )

    return _run_launch_surface_preflight(
        normalized_launch_mode=normalized_launch_mode,
        adb_status=adb_status,
        helper_status=None,
        helper_state="deferred_to_core",
        talkback_status=None,
        talkback_state="deferred_to_core",
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
    )


def _run_launch_surface_preflight(
    *,
    normalized_launch_mode: str,
    adb_status: dict[str, object],
    helper_status: dict[str, object] | None,
    helper_state: str,
    talkback_status: dict[str, object] | None,
    talkback_state: str,
    adb_runner: Callable[[list[str], float], dict[str, object]],
    sleep_fn: Callable[[float], None],
) -> dict[str, object]:
    launch_status = launch_smartthings(
        normalized_launch_mode,
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
    )
    if not launch_status.get("monkey_success"):
        return _blocked_result(
            reason="smartthings_launch_failed",
            launch_mode=normalized_launch_mode,
            adb_status=adb_status,
            helper_status=helper_status,
            talkback_status=talkback_status,
            launch_status=launch_status,
            foreground_status=None,
            accessibility_settings_opened=False,
        )

    surface_status = poll_launch_surface_status(adb_runner=adb_runner, sleep_fn=sleep_fn)
    foreground_status = _dict(surface_status.get("foreground_status"))
    popup_status = stabilize_external_popup(
        initial_foreground_status=foreground_status,
        initial_surface_status=surface_status,
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
    )
    surface_status = _dict(popup_status.get("surface_status")) or surface_status
    foreground_status = _dict(popup_status.get("foreground_status")) or foreground_status
    if popup_status.get("popup_result") == "uncleared":
        return _blocked_result(
            reason="external_popup_uncleared",
            launch_mode=normalized_launch_mode,
            adb_status=adb_status,
            helper_status=helper_status,
            talkback_status=talkback_status,
            launch_status=launch_status,
            foreground_status=foreground_status,
            popup_status=popup_status,
            accessibility_settings_opened=False,
        )

    internal_popup_status = dismiss_samsung_account_popup(adb_runner)
    if internal_popup_status.get("popup_detected"):
        sleep_fn(0.7)

    return {
        "state": "passed",
        "ok": True,
        "reason": "ok",
        "launch_mode": normalized_launch_mode,
        "adb_state": "ok",
        "helper_state": helper_state,
        "talkback_state": talkback_state,
        "foreground_package": foreground_status.get("package"),
        "foreground_matches_expected": foreground_status.get("matches_expected"),
        "uiautomator_package": surface_status.get("uiautomator_package"),
        "uiautomator_focused_package": surface_status.get("uiautomator_focused_package"),
        "accessibility_settings_opened": False,
        "adb_status": adb_status,
        "helper_status": helper_status,
        "talkback_status": talkback_status,
        "launch_status": launch_status,
        "foreground_status": foreground_status,
        "popup_status": popup_status,
        "internal_popup_status": internal_popup_status,
        "popup_detected": popup_status.get("popup_detected"),
        "popup_package": popup_status.get("popup_package"),
        "popup_dismissed": popup_status.get("popup_dismissed"),
        "popup_result": popup_status.get("popup_result"),
        "user_message": None,
    }


def format_preflight_log_lines(preflight: dict[str, object]) -> list[str]:
    launch_status = _dict(preflight.get("launch_status"))
    foreground_status = _dict(preflight.get("foreground_status"))
    popup_status = _dict(preflight.get("popup_status"))
    internal_popup_status = _dict(preflight.get("internal_popup_status"))
    surface_status = _dict(preflight.get("popup_status")).get("surface_status") or {}
    lines = [
        f"[QA_FRONTEND][preflight][adb] status='{preflight.get('adb_state', 'unknown')}'",
        f"[QA_FRONTEND][preflight][helper] status='{preflight.get('helper_state', 'unknown')}'",
        f"[QA_FRONTEND][preflight][talkback] status='{preflight.get('talkback_state', 'unknown')}'",
        f"[QA_FRONTEND][preflight][launch_app] launch_mode='{preflight.get('launch_mode', 'clean')}'",
        f"[QA_FRONTEND][preflight][launch_app] force_stop_attempted='{str(launch_status.get('force_stop_attempted', False)).lower()}'",
        f"[QA_FRONTEND][preflight][launch_app] monkey_success='{str(launch_status.get('monkey_success', False)).lower()}'",
        f"[QA_FRONTEND][preflight][launch_app] foreground_package='{foreground_status.get('package') or ''}'",
        f"[QA_FRONTEND][preflight][launch_app] uiautomator_package='{_dict(surface_status).get('uiautomator_package') or preflight.get('uiautomator_package') or ''}'",
        f"[QA_FRONTEND][preflight][launch_app] uiautomator_focused_package='{_dict(surface_status).get('uiautomator_focused_package') or preflight.get('uiautomator_focused_package') or ''}'",
        f"[QA_FRONTEND][preflight][talkback] accessibility_settings_opened='{str(preflight.get('accessibility_settings_opened', False)).lower()}'",
    ]
    if popup_status:
        lines.append(
            "[QA_FRONTEND][preflight][popup] "
            f"detected_package='{popup_status.get('popup_package') or ''}' "
            f"reason='{popup_status.get('detected_reason') or ''}'"
        )
        for attempt in _list_of_dicts(popup_status.get("attempts")):
            lines.append(
                "[QA_FRONTEND][preflight][popup] "
                f"dismiss_attempt='{attempt.get('attempt')}' "
                f"dismiss_method='{attempt.get('dismiss_method') or ''}' "
                f"dismiss_label='{attempt.get('dismiss_label') or ''}' "
                f"back_attempted='{str(attempt.get('back_attempted', False)).lower()}' "
                f"result='{attempt.get('result') or ''}'"
            )
        lines.append(
            "[QA_FRONTEND][preflight][popup] "
            f"foreground_after='{popup_status.get('foreground_after') or ''}' "
            f"result='{popup_status.get('popup_result') or ''}'"
        )
    if internal_popup_status:
        candidate = _dict(internal_popup_status.get("candidate"))
        lines.append(
            "[QA_FRONTEND][preflight][popup] "
            f"internal_detected='{str(internal_popup_status.get('popup_detected', False)).lower()}' "
            f"internal_dismissed='{str(internal_popup_status.get('popup_dismissed', False)).lower()}' "
            f"dismiss_method='{internal_popup_status.get('dismiss_method') or ''}' "
            f"dismiss_label='{candidate.get('label') or ''}'"
        )
    lines.append(f"[QA_FRONTEND][preflight] final_result='{preflight.get('state')}' reason='{preflight.get('reason')}'")
    return lines


def _split_enabled_accessibility_services(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"null", "none"}:
        return []
    return [item.strip().lower() for item in raw.split(":") if item.strip()]


def _extract_foreground_package(output: str) -> str | None:
    patterns = [
        r"mCurrentFocus=.*?\s([a-zA-Z0-9_.]+)/",
        r"mFocusedApp=.*?\s([a-zA-Z0-9_.]+)/",
        r"topResumedActivity=.*?\s([a-zA-Z0-9_.]+)/",
        r"ResumedActivity:.*?\s([a-zA-Z0-9_.]+)/",
    ]
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            return match.group(1)
    return None


def _detect_external_popup_package(
    foreground_status: dict[str, object],
    uia_status: dict[str, object],
) -> str | None:
    for package in (
        str(uia_status.get("focused_package") or ""),
        str(uia_status.get("package") or ""),
        str(foreground_status.get("package") or ""),
    ):
        if package in KNOWN_EXTERNAL_POPUP_PACKAGES:
            return package
    return None


def _external_popup_reason(
    foreground_status: dict[str, object],
    uia_status: dict[str, object],
    package: str | None,
) -> str | None:
    if not package:
        return None
    if uia_status.get("focused_package") == package:
        return "post_launch_uiautomator_focus"
    if uia_status.get("package") == package:
        return "post_launch_uiautomator_root"
    if foreground_status.get("package") == package:
        return "post_launch_foreground"
    return KNOWN_EXTERNAL_POPUP_PACKAGES.get(package)


def _node_label(attributes: dict[str, str]) -> str:
    for key in ("text", "content-desc"):
        value = str(attributes.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip()).lower()


def _is_dangerous_popup_label(label: str) -> bool:
    normalized = _normalize_label(label)
    return any(token in normalized for token in DANGEROUS_POPUP_LABEL_TOKENS)


def _bounds_center(bounds: str) -> tuple[int, int] | None:
    match = re.match(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$", str(bounds or "").strip())
    if not match:
        return None
    left, top, right, bottom = [int(value) for value in match.groups()]
    if right <= left or bottom <= top:
        return None
    return int((left + right) / 2), int((top + bottom) / 2)


def _devices(adb_status: dict[str, object]) -> list[dict[str, object]]:
    devices = adb_status.get("devices")
    return devices if isinstance(devices, list) else []


def _helper_state(helper_status: dict[str, object] | None) -> str:
    if not helper_status:
        return "unknown"
    if not helper_status.get("ok") and helper_status.get("status") == "error":
        return "adb_error"
    return str(helper_status.get("status", "unknown"))


def _blocked_result(
    *,
    reason: str,
    launch_mode: LaunchMode,
    adb_status: dict[str, object] | None,
    helper_status: dict[str, object] | None,
    talkback_status: dict[str, object] | None,
    launch_status: dict[str, object] | None,
    foreground_status: dict[str, object] | None,
    accessibility_settings_opened: bool,
    popup_status: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "state": "blocked",
        "ok": False,
        "reason": reason,
        "launch_mode": launch_mode,
        "adb_state": "ok" if adb_status and adb_status.get("ok") else "adb_error",
        "helper_state": _helper_state(helper_status),
        "talkback_state": str(talkback_status.get("status")) if talkback_status else "unknown",
        "foreground_package": foreground_status.get("package") if foreground_status else None,
        "foreground_matches_expected": foreground_status.get("matches_expected") if foreground_status else None,
        "popup_status": popup_status,
        "popup_detected": popup_status.get("popup_detected") if popup_status else False,
        "popup_package": popup_status.get("popup_package") if popup_status else None,
        "popup_dismissed": popup_status.get("popup_dismissed") if popup_status else False,
        "popup_result": popup_status.get("popup_result") if popup_status else None,
        "accessibility_settings_opened": accessibility_settings_opened,
        "adb_status": adb_status,
        "helper_status": helper_status,
        "talkback_status": talkback_status,
        "launch_status": launch_status,
        "foreground_status": foreground_status,
        "user_message": None,
    }


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
