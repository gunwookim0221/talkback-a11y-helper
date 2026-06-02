from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

from talkback_lib import A11yAdbClient
from talkback_lib.constants import DEFAULT_ADB_PATH
from tb_runner.accessibility_preflight import (
    HELPER_SERVICE_COMPONENT,
    AccessibilityPreflightResult,
    ensure_accessibility_service_enabled,
    run_adb_text,
)


SMARTTHINGS_PACKAGE = "com.samsung.android.oneconnect"
EXTERNAL_POPUP_PACKAGES = {
    "com.android.vending",
    "com.google.android.finsky",
}
PREFLIGHT_UI_DUMP_PATH = "/sdcard/tb_runner_preflight_surface.xml"


@dataclass(frozen=True)
class CorePreflightResult:
    ok: bool
    reason: str
    accessibility: AccessibilityPreflightResult | None
    talkback_status: str
    talkback_reason: str
    device_connected: dict[str, object]
    screen_awake: dict[str, object]
    unlock_swipe: dict[str, object]
    app_foreground: dict[str, object]


def check_device_connected(
    *,
    serial: str | None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
) -> dict[str, object]:
    ok, output = adb_runner(adb_path, serial, "get-state", timeout=8.0)
    connected = ok and output.strip() == "device"
    return _step_result(
        "PASS" if connected else "FAIL",
        "ADB device connected" if connected else f"ADB device unavailable: {output or 'unknown error'}",
        adb_state=output.strip(),
    )


def wake_screen(
    *,
    serial: str | None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] = time.sleep,
    settle_seconds: float = 0.75,
) -> dict[str, object]:
    ok, output = adb_runner(adb_path, serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP", timeout=8.0)
    if ok:
        sleep_fn(max(0.0, settle_seconds))
    return _step_result(
        "PASS" if ok else "FAIL",
        "Wake keyevent sent; screen settle completed" if ok else f"Wake keyevent failed: {output or 'unknown error'}",
    )


def unlock_swipe(
    *,
    serial: str | None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_attempts: int = 3,
    settle_seconds: float = 0.6,
) -> dict[str, object]:
    coordinates = _resolve_unlock_swipe_coordinates(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    attempts: list[dict[str, object]] = []
    last_keyguard_active: bool | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        swipe_ok, swipe_output = adb_runner(
            adb_path,
            serial,
            "shell",
            "input",
            "swipe",
            *(str(value) for value in coordinates),
            timeout=8.0,
        )
        if swipe_ok:
            sleep_fn(max(0.0, settle_seconds))
        keyguard_active = _read_keyguard_active(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
        last_keyguard_active = keyguard_active
        attempts.append(
            {
                "attempt": attempt,
                "swipe_sent": swipe_ok,
                "keyguard_active": keyguard_active,
                "message": swipe_output,
            }
        )
        if swipe_ok and keyguard_active is False:
            return _step_result(
                "PASS",
                f"Swipe command sent; keyguard not active after {attempt} attempt(s)",
                attempts=attempts,
                coordinates=coordinates,
                keyguard_active=False,
            )

    if last_keyguard_active is True:
        message = "Swipe retry completed; secure lockscreen may still be active"
    elif last_keyguard_active is None:
        message = "Swipe retry completed; secure lock state not verified"
    else:
        message = "Unlock swipe retry completed with command errors"
    return _step_result(
        "WARN",
        message,
        attempts=attempts,
        coordinates=coordinates,
        keyguard_active=last_keyguard_active,
    )


def ensure_smartthings_foreground(
    *,
    serial: str | None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] = time.sleep,
    settle_seconds: float = 3.0,
) -> dict[str, object]:
    keyguard_active = _read_keyguard_active(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    package = _read_foreground_package(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    if package == SMARTTHINGS_PACKAGE:
        return _step_result(
            "PASS",
            "SmartThings foreground confirmed",
            package=package,
            launch_attempted=False,
            keyguard_active=keyguard_active,
        )

    launch_ok, launch_output = adb_runner(
        adb_path,
        serial,
        "shell",
        "monkey",
        "-p",
        SMARTTHINGS_PACKAGE,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
        timeout=12.0,
    )
    if not launch_ok:
        return _step_result(
            "FAIL",
            _foreground_failure_message(f"SmartThings launch failed: {launch_output or 'unknown error'}", keyguard_active),
            package=package,
            launch_attempted=True,
            keyguard_active=keyguard_active,
        )

    sleep_fn(max(0.0, settle_seconds))
    keyguard_active = _read_keyguard_active(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    package = _read_foreground_package(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    return _step_result(
        "PASS" if package == SMARTTHINGS_PACKAGE else "FAIL",
        "SmartThings foreground confirmed"
        if package == SMARTTHINGS_PACKAGE
        else _foreground_failure_message(
            f"SmartThings foreground not confirmed: {package or 'unknown package'}",
            keyguard_active,
        ),
        package=package,
        launch_attempted=True,
        keyguard_active=keyguard_active,
    )


def recover_external_popup_contamination(
    *,
    serial: str | None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] = time.sleep,
    settle_seconds: float = 0.7,
    relaunch_settle_seconds: float = 3.0,
    force_stop_settle_seconds: float = 1.5,
    dismiss_settle_seconds: float = 1.0,
    contamination_hint: str | None = None,
) -> dict[str, object]:
    before = _read_surface_packages(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    contamination_package = _find_external_popup_package(before) or (
        contamination_hint if contamination_hint in EXTERNAL_POPUP_PACKAGES else None
    )
    if not contamination_package:
        return _step_result(
            "PASS",
            "No external popup contamination detected",
            contamination_package=None,
            recovery_attempted=False,
            recovered=True,
            before=before,
            after=before,
        )

    adb_runner(adb_path, serial, "shell", "input", "keyevent", "KEYCODE_BACK", timeout=8.0)
    sleep_fn(max(0.0, settle_seconds))
    after = _read_surface_packages(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    if _surface_recovered(after):
        return _popup_recovery_result(contamination_package, before, after, recovery="back")

    adb_runner(
        adb_path,
        serial,
        "shell",
        "monkey",
        "-p",
        SMARTTHINGS_PACKAGE,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
        timeout=12.0,
    )
    sleep_fn(max(0.0, relaunch_settle_seconds))
    after = _read_surface_packages(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    if _surface_recovered(after):
        return _popup_recovery_result(contamination_package, before, after, recovery="back_or_relaunch")

    for package in sorted(EXTERNAL_POPUP_PACKAGES):
        adb_runner(adb_path, serial, "shell", "am", "force-stop", package, timeout=8.0)
    adb_runner(
        adb_path,
        serial,
        "shell",
        "monkey",
        "-p",
        SMARTTHINGS_PACKAGE,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
        timeout=12.0,
    )
    sleep_fn(max(0.0, force_stop_settle_seconds))
    after = _read_surface_packages(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    if _surface_recovered(after):
        return _popup_recovery_result(
            contamination_package,
            before,
            after,
            recovery="force_stop_external_and_relaunch",
        )

    dismiss_result = _dismiss_review_sheet_not_now(
        serial=serial,
        adb_path=adb_path,
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
        settle_seconds=dismiss_settle_seconds,
    )
    if dismiss_result.get("recovered"):
        return _popup_recovery_result(
            contamination_package,
            before,
            dismiss_result["after"],
            recovery="dismiss_review_sheet",
        )

    return _step_result(
        "FAIL",
        f"External popup contamination remains: {contamination_package}",
        contamination_package=contamination_package,
        recovery_attempted=True,
        recovery=str(dismiss_result.get("recovery") or "force_stop_external_and_relaunch"),
        recovered=False,
        before=before,
        after=dismiss_result.get("after") or after,
    )


def run_preflight(
    *,
    client: A11yAdbClient,
    serial: str | None,
    log_fn: Callable[[str], None],
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CorePreflightResult:
    device_connected = check_device_connected(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    log_fn(f"[PREFLIGHT] device_connected {device_connected['status']}")
    if device_connected["status"] == "FAIL":
        return _early_failure("device_connected_failed", device_connected, _not_run(), _not_run(), _not_run())

    log_fn("[PREFLIGHT] wake_screen start")
    screen_awake = wake_screen(serial=serial, adb_path=adb_path, adb_runner=adb_runner, sleep_fn=sleep_fn)
    log_fn(_format_step_log("wake_screen", screen_awake))
    if screen_awake["status"] == "FAIL":
        return _early_failure("wake_screen_failed", device_connected, screen_awake, _not_run(), _not_run())

    log_fn("[PREFLIGHT] unlock_swipe start")
    unlock_status = unlock_swipe(serial=serial, adb_path=adb_path, adb_runner=adb_runner, sleep_fn=sleep_fn)
    log_fn(_format_step_log("unlock_swipe", unlock_status))

    log_fn("[PREFLIGHT] app_foreground start")
    app_foreground = ensure_smartthings_foreground(
        serial=serial,
        adb_path=adb_path,
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
    )
    contamination_package = str(app_foreground.get("package") or "")
    if app_foreground["status"] == "FAIL" and _is_external_popup_package(contamination_package):
        popup_status = recover_external_popup_contamination(
            serial=serial,
            adb_path=adb_path,
            adb_runner=adb_runner,
            sleep_fn=sleep_fn,
            contamination_hint=contamination_package,
        )
        app_foreground["popup_check"] = popup_status
        _log_popup_recovery(log_fn, popup_status, package=contamination_package)
        if popup_status["status"] == "FAIL":
            app_foreground["message"] = popup_status["message"]
            return _early_failure("external_popup_contamination", device_connected, screen_awake, unlock_status, app_foreground)
        app_foreground = ensure_smartthings_foreground(
            serial=serial,
            adb_path=adb_path,
            adb_runner=adb_runner,
            sleep_fn=sleep_fn,
        )
        app_foreground["popup_check"] = popup_status
    log_fn(_format_step_log("app_foreground", app_foreground))
    if app_foreground["status"] == "FAIL":
        return _early_failure("app_foreground_failed", device_connected, screen_awake, unlock_status, app_foreground)

    popup_status = recover_external_popup_contamination(
        serial=serial,
        adb_path=adb_path,
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
    )
    app_foreground["popup_check"] = popup_status
    if popup_status.get("recovery_attempted"):
        _log_popup_recovery(log_fn, popup_status)
    if popup_status["status"] == "FAIL":
        app_foreground["status"] = "FAIL"
        app_foreground["message"] = popup_status["message"]
        return _early_failure("external_popup_contamination", device_connected, screen_awake, unlock_status, app_foreground)

    accessibility = ensure_accessibility_service_enabled(
        serial=serial,
        adb_path=adb_path,
        component=HELPER_SERVICE_COMPONENT,
        helper_ready_check=lambda: client.ping(dev=serial, wait_=3.0),
        log_fn=log_fn,
    )
    log_fn(
        "[PREFLIGHT][accessibility] "
        f"component='{HELPER_SERVICE_COMPONENT}' "
        f"before_enabled='{accessibility.before.enabled_accessibility_services}' "
        f"before_accessibility_enabled='{accessibility.before.accessibility_enabled}' "
        f"after_enabled='{accessibility.after.enabled_accessibility_services}' "
        f"after_accessibility_enabled='{accessibility.after.accessibility_enabled}' "
        f"enable_attempted={str(accessibility.enable_attempted).lower()} "
        f"helper_ready={str(accessibility.helper_ready).lower()} "
        f"result='{accessibility.reason}'"
    )
    if not accessibility.ok:
        return CorePreflightResult(
            False,
            accessibility.reason,
            accessibility,
            "unknown",
            "",
            device_connected,
            screen_awake,
            unlock_status,
            app_foreground,
        )

    talkback = client.check_talkback_ready(dev=serial)
    talkback_status = talkback.get("status", "disabled")
    talkback_reason = talkback.get("reason", "")
    if talkback_reason == "external_popup_contamination":
        contamination_package = str(talkback.get("packageName") or "com.android.vending")
        popup_status = recover_external_popup_contamination(
            serial=serial,
            adb_path=adb_path,
            adb_runner=adb_runner,
            sleep_fn=sleep_fn,
            contamination_hint=contamination_package,
        )
        app_foreground["popup_check"] = popup_status
        _log_popup_recovery(log_fn, popup_status, package=contamination_package)
        if popup_status["status"] == "FAIL":
            app_foreground["status"] = "FAIL"
            app_foreground["message"] = popup_status["message"]
            return _early_failure("external_popup_contamination", device_connected, screen_awake, unlock_status, app_foreground)
        talkback = client.check_talkback_ready(dev=serial)
        talkback_status = talkback.get("status", "disabled")
        talkback_reason = talkback.get("reason", "")
    log_fn(f"[PREFLIGHT] talkback status='{talkback_status}'")
    if talkback_status == "disabled":
        return CorePreflightResult(
            False, "talkback_off", accessibility, talkback_status, talkback_reason,
            device_connected, screen_awake, unlock_status, app_foreground,
        )
    if talkback_status == "enabled_but_not_ready":
        return CorePreflightResult(
            False, talkback_reason or "talkback_not_ready", accessibility, talkback_status, talkback_reason,
            device_connected, screen_awake, unlock_status, app_foreground,
        )
    return CorePreflightResult(
        True, "ok", accessibility, talkback_status, talkback_reason,
        device_connected, screen_awake, unlock_status, app_foreground,
    )


def _read_foreground_package(
    *,
    serial: str | None,
    adb_path: str,
    adb_runner: Callable[..., tuple[bool, str]],
) -> str | None:
    ok, output = adb_runner(adb_path, serial, "shell", "dumpsys", "window", timeout=8.0)
    package = _extract_foreground_package(output) if ok else None
    if package:
        return package
    ok, output = adb_runner(adb_path, serial, "shell", "dumpsys", "activity", "activities", timeout=8.0)
    return _extract_foreground_package(output) if ok else None


def _read_surface_packages(
    *,
    serial: str | None,
    adb_path: str,
    adb_runner: Callable[..., tuple[bool, str]],
) -> dict[str, object]:
    uiautomator_xml = _read_uiautomator_xml(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    return {
        "foreground_package": _read_foreground_package(serial=serial, adb_path=adb_path, adb_runner=adb_runner),
        "uiautomator_package": _extract_uiautomator_package(uiautomator_xml),
        "bottom_tab_present": _has_smartthings_bottom_tab(uiautomator_xml),
    }


def _read_uiautomator_xml(
    *,
    serial: str | None,
    adb_path: str,
    adb_runner: Callable[..., tuple[bool, str]],
) -> str:
    ok, _output = adb_runner(adb_path, serial, "shell", "uiautomator", "dump", PREFLIGHT_UI_DUMP_PATH, timeout=8.0)
    if not ok:
        return ""
    ok, output = adb_runner(adb_path, serial, "shell", "cat", PREFLIGHT_UI_DUMP_PATH, timeout=8.0)
    return output if ok else ""


def _extract_uiautomator_package(output: str) -> str | None:
    try:
        root = ET.fromstring(output)
    except ET.ParseError:
        return None
    for node in root.iter("node"):
        package = str(node.attrib.get("package", "") or "").strip()
        if package:
            return package
    return None


def _find_external_popup_package(packages: dict[str, object]) -> str | None:
    for key in ("foreground_package", "uiautomator_package"):
        package = packages.get(key)
        if _is_external_popup_package(package):
            return str(package)
    return None


def _is_external_popup_package(package: object) -> bool:
    return str(package or "").strip() in EXTERNAL_POPUP_PACKAGES


def _surface_recovered(packages: dict[str, object]) -> bool:
    return (
        packages.get("foreground_package") == SMARTTHINGS_PACKAGE
        and _find_external_popup_package(packages) is None
    )


def _dismiss_review_sheet_not_now(
    *,
    serial: str | None,
    adb_path: str,
    adb_runner: Callable[..., tuple[bool, str]],
    sleep_fn: Callable[[float], None],
    settle_seconds: float,
) -> dict[str, object]:
    xml_text = _read_uiautomator_xml(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    candidate = _find_review_sheet_not_now_candidate(xml_text)
    if not candidate:
        return {"recovered": False, "recovery": "force_stop_external_and_relaunch"}

    tap_ok, _output = adb_runner(
        adb_path,
        serial,
        "shell",
        "input",
        "tap",
        str(candidate["x"]),
        str(candidate["y"]),
        timeout=8.0,
    )
    if tap_ok:
        sleep_fn(max(0.0, settle_seconds))
    after = _read_surface_packages(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    return {
        "recovered": (
            tap_ok
            and _surface_recovered(after)
            and bool(after.get("bottom_tab_present"))
        ),
        "recovery": "dismiss_review_sheet",
        "after": after,
    }


def _find_review_sheet_not_now_candidate(xml_text: str) -> dict[str, int] | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    external_nodes = [
        node for node in root.iter("node")
        if _is_external_popup_package(node.attrib.get("package"))
    ]
    has_submit = any("submit" in _node_labels(node) for node in external_nodes)
    if not has_submit:
        return None
    for node in external_nodes:
        if "not now" not in _node_labels(node):
            continue
        center = _bounds_center(str(node.attrib.get("bounds", "") or ""))
        if center:
            return {"x": center[0], "y": center[1]}
    return None


def _node_labels(node: ET.Element) -> set[str]:
    return {
        str(node.attrib.get(key, "") or "").strip().lower()
        for key in ("text", "content-desc")
        if str(node.attrib.get(key, "") or "").strip()
    }


def _bounds_center(bounds: str) -> tuple[int, int] | None:
    match = re.match(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$", bounds.strip())
    if not match:
        return None
    left, top, right, bottom = (int(value) for value in match.groups())
    if right <= left or bottom <= top:
        return None
    return int((left + right) / 2), int((top + bottom) / 2)


def _has_smartthings_bottom_tab(xml_text: str) -> bool:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    for node in root.iter("node"):
        if str(node.attrib.get("package", "") or "").strip() != SMARTTHINGS_PACKAGE:
            continue
        resource_id = str(node.attrib.get("resource-id", "") or "").lower()
        if "bottom" in resource_id and ("tab" in resource_id or "nav" in resource_id):
            return True
    return False


def _popup_recovery_result(
    contamination_package: str,
    before: dict[str, object],
    after: dict[str, object],
    *,
    recovery: str,
) -> dict[str, object]:
    return _step_result(
        "PASS",
        "External popup contamination recovered",
        contamination_package=contamination_package,
        recovery_attempted=True,
        recovery=recovery,
        recovered=True,
        before=before,
        after=after,
    )


def _log_popup_recovery(
    log_fn: Callable[[str], None],
    popup_status: dict[str, object],
    *,
    package: str | None = None,
) -> None:
    contamination_package = package or str(popup_status.get("contamination_package") or "unknown")
    log_fn(f"[PREFLIGHT][popup] contamination package='{contamination_package}'")
    log_fn("[PREFLIGHT][popup] recovery='back_or_relaunch'")
    log_fn(
        f"[PREFLIGHT][popup] recovered={str(bool(popup_status.get('recovered'))).lower()} "
        f"method='{popup_status.get('recovery') or 'back_or_relaunch'}'"
    )


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


def _secure_lockscreen_active(output: str) -> bool | None:
    match = re.search(
        r"(?:isStatusBarKeyguard|mShowingLockscreen|mShowing)\s*=\s*(true|false|1|0)",
        output,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).lower() in {"true", "1"}


def _read_keyguard_active(
    *,
    serial: str | None,
    adb_path: str,
    adb_runner: Callable[..., tuple[bool, str]],
) -> bool | None:
    ok, output = adb_runner(adb_path, serial, "shell", "dumpsys", "window", "policy", timeout=8.0)
    return _secure_lockscreen_active(output) if ok else None


def _resolve_unlock_swipe_coordinates(
    *,
    serial: str | None,
    adb_path: str,
    adb_runner: Callable[..., tuple[bool, str]],
) -> tuple[int, int, int, int]:
    ok, output = adb_runner(adb_path, serial, "shell", "wm", "size", timeout=8.0)
    match = re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", output)
    if ok and match:
        width, height = int(match.group(1)), int(match.group(2))
        center_x = max(1, width // 2)
        return center_x, max(1, int(height * 0.85)), center_x, max(1, int(height * 0.25))
    return 500, 1800, 500, 500


def _foreground_failure_message(message: str, keyguard_active: bool | None) -> str:
    if keyguard_active is True:
        return f"{message}; keyguard/lockscreen may still be active"
    if keyguard_active is None:
        return f"{message}; keyguard/lockscreen state could not be verified"
    return f"{message}; keyguard/lockscreen not detected"


def _format_step_log(name: str, result: dict[str, object]) -> str:
    return f"[PREFLIGHT] {name} {result['status']} message='{result['message']}'"


def _step_result(status: str, message: str, **details: object) -> dict[str, object]:
    return {"status": status, "message": message, **details}


def _not_run() -> dict[str, object]:
    return _step_result("NOT_RUN", "Skipped because an earlier preflight step failed")


def _early_failure(
    reason: str,
    device_connected: dict[str, object],
    screen_awake: dict[str, object],
    unlock_status: dict[str, object],
    app_foreground: dict[str, object],
) -> CorePreflightResult:
    return CorePreflightResult(
        False,
        reason,
        None,
        "unknown",
        "",
        device_connected,
        screen_awake,
        unlock_status,
        app_foreground,
    )
