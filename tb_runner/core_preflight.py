from __future__ import annotations

import re
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

from talkback_lib import A11yAdbClient
from talkback_lib.constants import DEFAULT_ADB_PATH
from talkback_lib.window_lifecycle import TALKBACK_PACKAGE
from tb_runner.accessibility_preflight import (
    HELPER_SERVICE_COMPONENT,
    AccessibilityPreflightResult,
    ensure_accessibility_service_enabled,
    run_adb_text,
)
from tb_runner.samsung_account_popup import (
    find_samsung_account_popup_candidate,
    find_samsung_account_popup_candidate_in_xml,
)


SMARTTHINGS_PACKAGE = "com.samsung.android.oneconnect"
EXTERNAL_POPUP_PACKAGES = {
    "com.android.vending",
    "com.google.android.finsky",
}
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
    client: A11yAdbClient | None = None,
    serial: str | None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] = time.sleep,
    settle_seconds: float = 0.7,
    relaunch_settle_seconds: float = 3.0,
    force_stop_settle_seconds: float = 1.5,
    dismiss_settle_seconds: float = 1.0,
    contamination_hint: str | None = None,
    contamination_hint_current: bool = False,
    contamination_hint_source: str | None = None,
) -> dict[str, object]:
    hint_package = contamination_hint if _is_external_popup_package(contamination_hint) else None
    hint_source = contamination_hint_source or "current_preflight_hint"

    def result(status: str, message: str, **details: object) -> dict[str, object]:
        before = details.get("before") if isinstance(details.get("before"), dict) else {}
        after = details.get("after") if isinstance(details.get("after"), dict) else None
        final_observation = (
            details.get("final_observation")
            if isinstance(details.get("final_observation"), dict)
            else after or before
        )
        details.setdefault("before_contamination_package", _find_external_popup_package(before))
        details.setdefault("after_contamination_package", _find_external_popup_package(after or {}))
        details.setdefault("final_observation", final_observation)
        details.setdefault("final_contamination_package", _find_external_popup_package(final_observation))
        details.setdefault(
            "final_contamination_evidence_source",
            _external_popup_evidence_source(final_observation),
        )
        details.setdefault("surface_recovered", _surface_recovered(final_observation))
        details.setdefault("recovery_action_attempted", bool(details.get("recovery_attempted")))
        details.setdefault("contamination_hint", hint_package)
        details.setdefault("contamination_hint_current", bool(hint_package and contamination_hint_current))
        details.setdefault("contamination_hint_source", hint_source if hint_package else None)
        return _step_result(status, message, **details)

    if client is None:
        before = {
            "foreground_package": _read_foreground_package(
                serial=serial, adb_path=adb_path, adb_runner=adb_runner,
            ),
            "hierarchy_package": None,
            "hierarchy_focused_package": None,
            "hierarchy_ok": False,
            "hierarchy_error": "helper client unavailable",
            "hierarchy_error_type": "MissingDependency",
            "hierarchy_error_message": "helper client unavailable",
            "hierarchy_failure_stage": "validate_recovery_dependencies",
            "hierarchy_transport_status": "NOT_STARTED",
            "hierarchy_schema_result": "UNKNOWN",
            "hierarchy_root_result": "UNKNOWN",
            "hierarchy_request_id": None,
            "hierarchy_operation_id": None,
        }
        return result(
            "FAIL", "Popup recovery helper client unavailable",
            reason="readiness_recovery_dependency_unavailable",
            contamination_package=None,
            contamination_hint=hint_package,
            contamination_evidence_source="hint_only_suspicion" if hint_package else None,
            recovery_attempted=False, recovered=False, before=before, after=before,
        )

    before = _read_surface_packages(client=client, serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    observed_package = _find_external_popup_package(before)
    observed_source = _external_popup_evidence_source(before)
    has_package_evidence = _has_surface_package_evidence(before)
    selected_package = observed_package
    selected_source = observed_source

    if not before.get("hierarchy_ok") and not selected_package:
        return result(
            "FAIL", "Service hierarchy acquisition failed during popup preflight",
            reason="service_hierarchy_acquisition_failed",
            contamination_package=None,
            contamination_hint=hint_package,
            contamination_evidence_source="hint_only_suspicion" if hint_package else None,
            recovery_attempted=False, recovered=False, before=before, after=before,
            final_observation=before,
        )
    if before.get("hierarchy_ok") and not has_package_evidence and not selected_package:
        return result(
            "FAIL", "Surface package evidence unavailable during popup preflight",
            reason="readiness_surface_evidence_unavailable",
            contamination_package=None,
            contamination_hint=hint_package,
            contamination_evidence_source="hint_only_suspicion" if hint_package else None,
            recovery_attempted=False, recovered=False, before=before, after=before,
            final_observation=before,
        )
    if not selected_package:
        return result(
            "PASS", "No external popup contamination detected",
            reason="ok",
            contamination_package=None,
            contamination_hint=hint_package,
            contamination_evidence_source="current_clean_observation",
            recovery_attempted=False, recovered=True, before=before, after=before,
            final_observation=before,
        )
    contamination_package = selected_package
    if not before.get("hierarchy_ok"):
        return result(
            "FAIL", f"External popup package observed but hierarchy unavailable: {contamination_package}",
            reason="external_popup_contamination",
            contamination_package=contamination_package,
            contamination_hint=hint_package,
            contamination_evidence_source=selected_source or "current_observation",
            recovery_attempted=False, recovered=False, before=before, after=before,
            final_observation=before,
        )

    adb_runner(adb_path, serial, "shell", "input", "keyevent", "KEYCODE_BACK", timeout=8.0)
    sleep_fn(max(0.0, settle_seconds))
    after = _read_surface_packages(client=client, serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    if _surface_recovered(after):
        return _popup_recovery_result(
            contamination_package, before, after, recovery="back",
            evidence_source=selected_source, contamination_hint=hint_package,
            contamination_hint_current=contamination_hint_current,
            contamination_hint_source=hint_source,
        )

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
    after = _read_surface_packages(client=client, serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    if _surface_recovered(after):
        return _popup_recovery_result(
            contamination_package, before, after, recovery="back_or_relaunch",
            evidence_source=selected_source, contamination_hint=hint_package,
            contamination_hint_current=contamination_hint_current,
            contamination_hint_source=hint_source,
        )

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
    after = _read_surface_packages(client=client, serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    if _surface_recovered(after):
        return _popup_recovery_result(
            contamination_package,
            before,
            after,
            recovery="force_stop_external_and_relaunch",
            evidence_source=selected_source,
            contamination_hint=hint_package,
            contamination_hint_current=contamination_hint_current,
            contamination_hint_source=hint_source,
        )

    dismiss_result = _dismiss_review_sheet_not_now(
        client=client,
        serial=serial,
        adb_path=adb_path,
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
        settle_seconds=dismiss_settle_seconds,
    )
    final_observation = (
        dismiss_result.get("after")
        if isinstance(dismiss_result.get("after"), dict)
        else after
    )
    if _surface_recovered(final_observation):
        return _popup_recovery_result(
            contamination_package,
            before,
            final_observation,
            recovery=(
                "dismiss_review_sheet"
                if dismiss_result.get("recovery_action_succeeded")
                else "surface_observed_clean"
            ),
            evidence_source=selected_source,
            contamination_hint=hint_package,
            contamination_hint_current=contamination_hint_current,
            contamination_hint_source=hint_source,
        )

    latest_external_package = _find_external_popup_package(final_observation)
    latest_source = _external_popup_evidence_source(final_observation)
    latest_hierarchy_ok = final_observation.get("hierarchy_ok") is True
    if latest_external_package:
        failure_reason = "external_popup_contamination"
        failure_message = f"External popup contamination remains: {latest_external_package}"
    elif not latest_hierarchy_ok:
        failure_reason = "service_hierarchy_acquisition_failed"
        failure_message = "Service hierarchy acquisition failed during popup recovery"
    else:
        failure_reason = "readiness_surface_evidence_unavailable"
        failure_message = "SmartThings recovery surface was not confirmed by the latest observation"

    return result(
        "FAIL",
        failure_message,
        reason=failure_reason,
        contamination_package=latest_external_package,
        final_contamination_package=latest_external_package,
        final_contamination_evidence_source=latest_source,
        contamination_hint=hint_package,
        contamination_evidence_source=latest_source,
        recovery_attempted=True,
        recovery=str(dismiss_result.get("recovery") or "force_stop_external_and_relaunch"),
        recovered=False,
        surface_recovered=False,
        recovery_action_attempted=True,
        before=before,
        after=final_observation,
        final_observation=final_observation,
        recovery_hierarchy_error=dismiss_result.get("hierarchy_error"),
    )


def run_preflight(
    *,
    client: A11yAdbClient,
    serial: str | None,
    log_fn: Callable[[str], None],
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] = time.sleep,
    entry_mode: str = "AUTOMATED",
) -> CorePreflightResult:
    from tb_runner.entry_mode import PREPOSITIONED, normalize_entry_mode, readonly_preflight
    if normalize_entry_mode(entry_mode) == PREPOSITIONED:
        return readonly_preflight(client, serial, log_fn)
    device_connected = check_device_connected(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    log_fn(f"[PREFLIGHT] device_connected {device_connected['status']}")
    if device_connected["status"] == "FAIL":
        _log_readiness_diagnostic(
            log_fn, stage="device_connected", result=device_connected,
            readiness_result="device_connected_failed",
        )
        return _early_failure("device_connected_failed", device_connected, _not_run(), _not_run(), _not_run())

    # Seed before any app transition. Frontend preflight may have captured an
    # even earlier PID; never overwrite it with a process that already restarted.
    preflight_pid = os.environ.get("TB_TALKBACK_PREFLIGHT_PID", "").strip()
    if not preflight_pid.isdigit():
        pid_ok, pid_output = adb_runner(adb_path, serial, "shell", "pidof", TALKBACK_PACKAGE, timeout=5.0)
        preflight_pid = pid_output.strip() if pid_ok and pid_output.strip().isdigit() else ""
    client._preflight_talkback_pid = preflight_pid or None
    log_fn(f"[PREFLIGHT][talkback_pid] pid='{preflight_pid}' available={str(bool(preflight_pid)).lower()}")

    log_fn("[PREFLIGHT] wake_screen start")
    screen_awake = wake_screen(serial=serial, adb_path=adb_path, adb_runner=adb_runner, sleep_fn=sleep_fn)
    log_fn(_format_step_log("wake_screen", screen_awake))
    if screen_awake["status"] == "FAIL":
        _log_readiness_diagnostic(
            log_fn, stage="wake_screen", result=screen_awake,
            readiness_result="wake_screen_failed",
        )
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
    if app_foreground["status"] == "FAIL" and not _is_external_popup_package(contamination_package):
        log_fn(_format_step_log("app_foreground", app_foreground))
        _log_readiness_diagnostic(
            log_fn, stage="app_foreground", result=app_foreground,
            readiness_result="app_foreground_failed",
        )
        return _early_failure("app_foreground_failed", device_connected, screen_awake, unlock_status, app_foreground)

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
        _log_readiness_diagnostic(
            log_fn, stage="accessibility_service", result={},
            readiness_result=accessibility.reason,
        )
        return CorePreflightResult(
            False, accessibility.reason, accessibility, "unknown", "",
            device_connected, screen_awake, unlock_status, app_foreground,
        )

    if app_foreground["status"] == "FAIL" and _is_external_popup_package(contamination_package):
        popup_status = recover_external_popup_contamination(
            client=client,
            serial=serial,
            adb_path=adb_path,
            adb_runner=adb_runner,
            sleep_fn=sleep_fn,
            contamination_hint=contamination_package,
            contamination_hint_current=True,
            contamination_hint_source="app_foreground",
        )
        app_foreground["popup_check"] = popup_status
        if popup_status.get("recovery_attempted"):
            _log_popup_recovery(log_fn, popup_status, package=contamination_package)
        _log_readiness_diagnostic(
            log_fn, stage="popup_recovery_after_foreground", result=popup_status,
            readiness_result=_popup_failure_reason(popup_status) if popup_status["status"] == "FAIL" else "PASS",
            contamination_hint=contamination_package,
            contamination_package=str(popup_status.get("contamination_package") or "") or None,
            evidence_source=str(popup_status.get("contamination_evidence_source") or "") or None,
        )
        if popup_status["status"] == "FAIL":
            app_foreground["message"] = popup_status["message"]
            return _early_failure(_popup_failure_reason(popup_status), device_connected, screen_awake, unlock_status, app_foreground)
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
        client=client,
        serial=serial,
        adb_path=adb_path,
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
    )
    app_foreground["popup_check"] = popup_status
    if popup_status.get("recovery_attempted"):
        _log_popup_recovery(log_fn, popup_status)
    popup_failure_reason = (
        _popup_failure_reason(popup_status)
        if popup_status["status"] == "FAIL"
        else "PASS"
    )
    if popup_status.get("recovery_attempted") or popup_status["status"] == "FAIL":
        _log_readiness_diagnostic(
            log_fn, stage="external_popup_preflight", result=popup_status,
            readiness_result=popup_failure_reason,
            contamination_hint=str(popup_status.get("contamination_hint") or "") or None,
            contamination_package=str(popup_status.get("contamination_package") or "") or None,
            evidence_source=str(popup_status.get("contamination_evidence_source") or "") or None,
        )
    if popup_status["status"] == "FAIL":
        app_foreground["status"] = "FAIL"
        app_foreground["message"] = popup_status["message"]
        return _early_failure(popup_failure_reason, device_connected, screen_awake, unlock_status, app_foreground)

    internal_popup_status = dismiss_samsung_account_security_popup(
        client=client,
        serial=serial,
        adb_path=adb_path,
        adb_runner=adb_runner,
        sleep_fn=sleep_fn,
    )
    app_foreground["internal_popup_check"] = internal_popup_status
    _log_samsung_account_popup(log_fn, internal_popup_status)
    if internal_popup_status.get("acquisition_error"):
        failed_popup_check = _step_result(
            "FAIL",
            f"Service hierarchy acquisition failed: {internal_popup_status['acquisition_error']}",
            recovered=False,
            internal_popup_check=internal_popup_status,
        )
        app_foreground["status"] = "FAIL"
        app_foreground["message"] = str(failed_popup_check.get("message") or "Service hierarchy acquisition failed")
        _log_readiness_diagnostic(
            log_fn, stage="internal_popup_hierarchy", result={
                "before": {
                    "hierarchy_ok": False,
                    "hierarchy_error_type": internal_popup_status.get("acquisition_error_type") or "",
                    "hierarchy_error_message": internal_popup_status.get("acquisition_error_message") or internal_popup_status["acquisition_error"],
                    "hierarchy_failure_stage": internal_popup_status.get("acquisition_failure_stage") or "dismiss_samsung_account_security_popup",
                    "hierarchy_transport_status": "ERROR",
                    "hierarchy_schema_result": "UNKNOWN",
                    "hierarchy_root_result": "UNKNOWN",
                },
                "status": "FAIL",
            }, readiness_result="service_hierarchy_acquisition_failed",
        )
        return _early_failure("service_hierarchy_acquisition_failed", device_connected, screen_awake, unlock_status, app_foreground)

    talkback = client.check_talkback_ready(dev=serial)
    talkback_status = talkback.get("status", "disabled")
    talkback_reason = talkback.get("reason", "")
    if talkback_reason == "external_popup_contamination":
        contamination_package = str(talkback.get("packageName") or "com.android.vending")
        popup_status = recover_external_popup_contamination(
            client=client,
            serial=serial,
            adb_path=adb_path,
            adb_runner=adb_runner,
            sleep_fn=sleep_fn,
            contamination_hint=contamination_package,
            contamination_hint_current=True,
            contamination_hint_source="talkback_focus",
        )
        app_foreground["popup_check"] = popup_status
        if popup_status.get("recovery_attempted"):
            _log_popup_recovery(log_fn, popup_status, package=contamination_package)
        _log_readiness_diagnostic(
            log_fn, stage="popup_recovery_after_talkback_focus", result=popup_status,
            readiness_result=_popup_failure_reason(popup_status) if popup_status["status"] == "FAIL" else "PASS",
            contamination_hint=contamination_package,
            contamination_package=str(popup_status.get("contamination_package") or "") or None,
            evidence_source=str(popup_status.get("contamination_evidence_source") or "") or None,
        )
        if popup_status["status"] == "FAIL":
            app_foreground["status"] = "FAIL"
            app_foreground["message"] = popup_status["message"]
            return _early_failure(_popup_failure_reason(popup_status), device_connected, screen_awake, unlock_status, app_foreground)
        talkback = client.check_talkback_ready(dev=serial)
        talkback_status = talkback.get("status", "disabled")
        talkback_reason = talkback.get("reason", "")
    log_fn(f"[PREFLIGHT] talkback status='{talkback_status}'")
    if talkback_status == "disabled":
        _log_readiness_diagnostic(
            log_fn, stage="talkback_readiness", result={}, readiness_result=talkback_reason or "talkback_off",
            contamination_package=None,
        )
        return CorePreflightResult(
            False, "talkback_off", accessibility, talkback_status, talkback_reason,
            device_connected, screen_awake, unlock_status, app_foreground,
        )
    if talkback_status == "enabled_but_not_ready":
        _log_readiness_diagnostic(
            log_fn, stage="talkback_readiness", result={}, readiness_result=talkback_reason or "talkback_not_ready",
            contamination_package=str(talkback.get("packageName") or "") or None,
            evidence_source="talkback_focus" if talkback.get("packageName") else None,
        )
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
    client: A11yAdbClient | None,
    serial: str | None,
    adb_path: str,
    adb_runner: Callable[..., tuple[bool, str]],
    nodes_out: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    foreground_package = _read_foreground_package(serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    stage = "dump_hierarchy"
    snapshot: dict[str, object] | None = None
    try:
        if client is None:
            raise RuntimeError("HIERARCHY_SNAPSHOT:SERVICE_UNAVAILABLE:helper client unavailable")
        from talkback_lib.hierarchy_snapshot import flatten_service_hierarchy

        snapshot = client.dump_hierarchy(dev=serial)
        stage = "flatten_service_hierarchy"
        nodes = flatten_service_hierarchy(snapshot)
        if nodes_out is not None:
            nodes_out.extend(nodes)
        windows = snapshot.get("windows", [])
        focused = next((node for node in nodes if bool(node.get("focused"))), None)
        packages = [str(node.get("packageName") or "").strip() for node in nodes]
        packages = [package for package in packages if package]
        hierarchy_package = (focused or {}).get("packageName") or (packages[0] if packages else None)
        bottom_tab_present = _has_smartthings_bottom_tab_nodes(nodes)
        hierarchy_ok = bool(nodes and windows)
        if not hierarchy_ok:
            stage = "validate_hierarchy_root"
        transport_metadata = _client_hierarchy_transport_metadata(client)
        hierarchy_metadata = _client_hierarchy_metadata(client)
        empty_error = "HIERARCHY_SNAPSHOT:NO_ROOT:empty_snapshot" if not hierarchy_ok else None
        return {
            "foreground_package": foreground_package,
            "hierarchy_package": str(hierarchy_package) if hierarchy_package else None,
            "hierarchy_focused_package": str((focused or {}).get("packageName") or "") or None,
            "bottom_tab_present": bottom_tab_present,
            "hierarchy_ok": hierarchy_ok,
            "hierarchy_window_count": len(windows),
            "hierarchy_node_count": len(nodes),
            "hierarchy_error": empty_error,
            "hierarchy_error_type": "HierarchyValidationError" if empty_error else None,
            "hierarchy_error_message": empty_error,
            "hierarchy_failure_stage": stage if empty_error else None,
            "hierarchy_transport_status": str(transport_metadata.get("status") or "COMPLETE"),
            "hierarchy_schema_result": "PASS" if isinstance(snapshot, dict) and snapshot.get("success") is True else "FAIL",
            "hierarchy_root_result": "PASS" if hierarchy_ok else "FAIL",
            "hierarchy_request_id": (
                hierarchy_metadata.get("reqId") or transport_metadata.get("request_id")
                or transport_metadata.get("requestId")
            ),
            "hierarchy_operation_id": (
                hierarchy_metadata.get("operation_id") or transport_metadata.get("operation_id")
            ),
        }
    except Exception as exc:
        transport_metadata = _client_hierarchy_transport_metadata(client)
        hierarchy_metadata = _client_hierarchy_metadata(client)
        reason = getattr(exc, "reason", None)
        request_id = getattr(exc, "request_id", None)
        message = str(exc)
        if not request_id:
            request_match = re.search(r"\breq(?:uest)?_?id=([^\s]+)", message, re.IGNORECASE)
            request_id = request_match.group(1) if request_match else None
        operation_match = re.search(r"\boperation_?id=([^\s]+)", message, re.IGNORECASE)
        transport_status = str(
            transport_metadata.get("status") or reason or _transport_status_from_error(message)
        )
        validation_result = "FAIL" if any(token in message.upper() for token in ("SCHEMA", "VALIDATION", "INVALID")) else "UNKNOWN"
        root_result = "FAIL" if any(token in message.upper() for token in ("NO_ROOT", "EMPTY_HIERARCHY", "EMPTY_SNAPSHOT")) else "UNKNOWN"
        return {
            "foreground_package": foreground_package,
            "hierarchy_package": None,
            "hierarchy_focused_package": None,
            "bottom_tab_present": False,
            "hierarchy_ok": False,
            "hierarchy_error": f"{type(exc).__name__}:{message}",
            "hierarchy_error_type": type(exc).__name__,
            "hierarchy_error_message": message,
            "hierarchy_failure_stage": stage,
            "hierarchy_transport_status": transport_status,
            "hierarchy_schema_result": validation_result,
            "hierarchy_root_result": root_result,
            "hierarchy_request_id": request_id or hierarchy_metadata.get("reqId")
            or transport_metadata.get("request_id") or transport_metadata.get("requestId"),
            "hierarchy_operation_id": getattr(exc, "operation_id", None)
            or (operation_match.group(1) if operation_match else None)
            or hierarchy_metadata.get("operation_id") or transport_metadata.get("operation_id"),
        }


def dismiss_samsung_account_security_popup(
    *,
    client: A11yAdbClient | None = None,
    serial: str | None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_runner: Callable[..., tuple[bool, str]] = run_adb_text,
    sleep_fn: Callable[[float], None] = time.sleep,
    settle_seconds: float = 0.7,
) -> dict[str, object]:
    if client is None:
        return {"detected": False, "dismissed": False, "verified_gone": None,
                "acquisition_error": "HIERARCHY_SNAPSHOT:SERVICE_UNAVAILABLE:helper client unavailable",
                "acquisition_error_type": "MissingDependency",
                "acquisition_error_message": "helper client unavailable",
                "acquisition_failure_stage": "validate_helper_client"}
    try:
        from talkback_lib.hierarchy_snapshot import flatten_service_hierarchy

        nodes = flatten_service_hierarchy(client.dump_hierarchy(dev=serial))
    except Exception as exc:
        return {"detected": False, "dismissed": False, "verified_gone": None,
                "acquisition_error": f"{type(exc).__name__}:{exc}",
                "acquisition_error_type": type(exc).__name__,
                "acquisition_error_message": str(exc),
                "acquisition_failure_stage": "dump_hierarchy"}
    candidate = find_samsung_account_popup_candidate(nodes)
    if candidate is None:
        return {"detected": False, "dismissed": False, "verified_gone": None}

    tap_ok, tap_output = adb_runner(
        adb_path,
        serial,
        "shell",
        "input",
        "tap",
        str(candidate.x),
        str(candidate.y),
        timeout=8.0,
    )
    if tap_ok:
        sleep_fn(max(0.0, settle_seconds))
    try:
        verify_nodes = flatten_service_hierarchy(client.dump_hierarchy(dev=serial))
        verified_gone = find_samsung_account_popup_candidate(verify_nodes) is None
    except (OSError, RuntimeError, TypeError, ValueError):
        verified_gone = None
    return {
        "detected": True,
        "dismissed": bool(tap_ok),
        "verified_gone": verified_gone,
        "method": candidate.method,
        "label": candidate.label,
        "resource_id": candidate.resource_id,
        "locale": candidate.locale,
        "title": candidate.title,
        "tap_output": tap_output,
    }


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


def _has_smartthings_bottom_tab_nodes(nodes: list[dict[str, object]]) -> bool:
    for node in nodes:
        if str(node.get("packageName") or "").strip() != SMARTTHINGS_PACKAGE:
            continue
        resource_id = str(node.get("viewIdResourceName") or "").lower()
        if "bottom" in resource_id and ("tab" in resource_id or "nav" in resource_id):
            return True
    return False


def _find_external_popup_package(packages: dict[str, object]) -> str | None:
    for key in ("foreground_package", "hierarchy_focused_package", "hierarchy_package"):
        package = packages.get(key)
        if _is_external_popup_package(package):
            return str(package)
    return None


def _external_popup_evidence_source(packages: dict[str, object]) -> str | None:
    for key in ("foreground_package", "hierarchy_focused_package", "hierarchy_package"):
        if _is_external_popup_package(packages.get(key)):
            return key
    return None


def _has_surface_package_evidence(packages: dict[str, object]) -> bool:
    return any(
        str(packages.get(key) or "").strip()
        for key in ("foreground_package", "hierarchy_focused_package", "hierarchy_package")
    )


def _client_hierarchy_metadata(client: object | None) -> dict[str, object]:
    value = getattr(client, "last_hierarchy_metadata", None)
    return value if isinstance(value, dict) else {}


def _client_hierarchy_transport_metadata(client: object | None) -> dict[str, object]:
    value = getattr(client, "_last_hierarchy_transport_metadata", None)
    return value if isinstance(value, dict) else {}


def _transport_status_from_error(message: str) -> str:
    match = re.search(r"HIERARCHY_SNAPSHOT:([A-Z_]+)", message)
    return match.group(1) if match else "ERROR"


def _is_external_popup_package(package: object) -> bool:
    return str(package or "").strip() in EXTERNAL_POPUP_PACKAGES


def _surface_recovered(packages: dict[str, object]) -> bool:
    return (
        packages.get("hierarchy_ok") is True
        and
        packages.get("foreground_package") == SMARTTHINGS_PACKAGE
        and _find_external_popup_package(packages) is None
    )


def _dismiss_review_sheet_not_now(
    *,
    client: A11yAdbClient | None,
    serial: str | None,
    adb_path: str,
    adb_runner: Callable[..., tuple[bool, str]],
    sleep_fn: Callable[[float], None],
    settle_seconds: float,
) -> dict[str, object]:
    hierarchy_nodes: list[dict[str, object]] = []
    observation = _read_surface_packages(
        client=client, serial=serial, adb_path=adb_path,
        adb_runner=adb_runner, nodes_out=hierarchy_nodes,
    )
    if _surface_recovered(observation):
        return {
            "recovered": True,
            "surface_recovered": True,
            "recovery_action_attempted": False,
            "recovery_action_succeeded": False,
            "recovery": "surface_already_clean",
            "after": observation,
        }
    if observation.get("hierarchy_ok") is not True:
        return {
            "recovered": False,
            "surface_recovered": False,
            "recovery_action_attempted": False,
            "recovery": "service_hierarchy_failed",
            "hierarchy_error": observation.get("hierarchy_error"),
            "after": observation,
        }
    candidate = _find_review_sheet_not_now_candidate_nodes(hierarchy_nodes)
    if not candidate:
        return {
            "recovered": False,
            "surface_recovered": False,
            "recovery_action_attempted": False,
            "recovery": "force_stop_external_and_relaunch",
            "after": observation,
        }

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
    after = _read_surface_packages(client=client, serial=serial, adb_path=adb_path, adb_runner=adb_runner)
    return {
        "recovered": _surface_recovered(after),
        "surface_recovered": _surface_recovered(after),
        "recovery_action_attempted": True,
        "recovery_action_succeeded": tap_ok,
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


def _find_review_sheet_not_now_candidate_nodes(nodes: list[dict[str, object]]) -> dict[str, int] | None:
    external_nodes = [node for node in nodes if _is_external_popup_package(node.get("packageName"))]
    has_submit = any(
        "submit" in {
            str(node.get("text") or "").strip().lower(),
            str(node.get("contentDescription") or "").strip().lower(),
        }
        for node in external_nodes
    )
    if not has_submit:
        return None
    for node in external_nodes:
        labels = {
            str(node.get("text") or "").strip().lower(),
            str(node.get("contentDescription") or "").strip().lower(),
        }
        if "not now" not in labels:
            continue
        bounds = node.get("boundsInScreen")
        if isinstance(bounds, dict):
            bounds = "[{l},{t}][{r},{b}]".format(
                l=int(bounds.get("left", bounds.get("l", 0)) or 0),
                t=int(bounds.get("top", bounds.get("t", 0)) or 0),
                r=int(bounds.get("right", bounds.get("r", 0)) or 0),
                b=int(bounds.get("bottom", bounds.get("b", 0)) or 0),
            )
        center = _bounds_center(str(bounds or ""))
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
    evidence_source: str | None = None,
    contamination_hint: str | None = None,
    contamination_hint_current: bool = False,
    contamination_hint_source: str | None = None,
) -> dict[str, object]:
    return _step_result(
        "PASS",
        "External popup contamination recovered",
        reason="ok",
        contamination_package=None,
        before_contamination_package=_find_external_popup_package(before) or contamination_package,
        after_contamination_package=_find_external_popup_package(after),
        final_contamination_package=None,
        contamination_hint=contamination_hint,
        contamination_hint_current=bool(contamination_hint and contamination_hint_current),
        contamination_hint_source=contamination_hint_source if contamination_hint else None,
        contamination_evidence_source=evidence_source or _external_popup_evidence_source(before),
        final_contamination_evidence_source=None,
        recovery_attempted=True,
        recovery_action_attempted=True,
        recovery=recovery,
        recovered=True,
        surface_recovered=True,
        before=before,
        after=after,
        final_observation=after,
    )


def _log_popup_recovery(
    log_fn: Callable[[str], None],
    popup_status: dict[str, object],
    *,
    package: str | None = None,
) -> None:
    contamination_package = (
        str(popup_status.get("before_contamination_package") or "")
        or package
        or "unknown"
    )
    log_fn(f"[PREFLIGHT][popup] contamination package='{contamination_package}'")
    log_fn("[PREFLIGHT][popup] recovery='back_or_relaunch'")
    log_fn(f"[PREFLIGHT][popup] method='{popup_status.get('recovery') or 'back_or_relaunch'}'")
    log_fn(
        f"[PREFLIGHT][popup] recovered={str(bool(popup_status.get('recovered'))).lower()} "
        f"method='{popup_status.get('recovery') or 'back_or_relaunch'}'"
    )


def _log_readiness_diagnostic(
    log_fn: Callable[[str], None],
    *,
    stage: str,
    result: dict[str, object] | None = None,
    readiness_result: str | None = None,
    contamination_hint: str | None = None,
    contamination_package: str | None = None,
    evidence_source: str | None = None,
) -> None:
    details = result if isinstance(result, dict) else {}
    before = details.get("before") if isinstance(details.get("before"), dict) else {}
    if not before and isinstance(details.get("popup_check"), dict):
        popup_check = details["popup_check"]
        before = popup_check.get("before") if isinstance(popup_check.get("before"), dict) else {}
        details = popup_check
    after = details.get("after") if isinstance(details.get("after"), dict) else None
    final_observation = (
        details.get("final_observation")
        if isinstance(details.get("final_observation"), dict)
        else after or before
    )
    hierarchy_ok = final_observation.get("hierarchy_ok")
    hierarchy_error_type = final_observation.get("hierarchy_error_type") or ""
    hierarchy_error_message = final_observation.get("hierarchy_error_message") or final_observation.get("hierarchy_error") or ""
    before_contamination = details.get(
        "before_contamination_package", _find_external_popup_package(before),
    )
    after_contamination = details.get(
        "after_contamination_package", _find_external_popup_package(after or {}),
    )
    final_contamination = details.get(
        "final_contamination_package",
        details.get("contamination_package", contamination_package),
    )
    final_evidence_source = details.get(
        "final_contamination_evidence_source",
        details.get("contamination_evidence_source", evidence_source),
    )
    recovery_action_attempted = details.get(
        "recovery_action_attempted", details.get("recovery_attempted"),
    )
    surface_recovered = details.get("surface_recovered", details.get("recovered"))
    fields = {
        "READINESS_STAGE": stage,
        "READINESS_RESULT": readiness_result or details.get("reason") or details.get("message") or details.get("status") or "FAIL",
        "HIERARCHY_OK": "unknown" if hierarchy_ok is None else str(bool(hierarchy_ok)).lower(),
        "HIERARCHY_ERROR_TYPE": hierarchy_error_type,
        "HIERARCHY_ERROR_MESSAGE": hierarchy_error_message,
        "FINAL_OBSERVATION": "after" if after is not None else "before",
        "BEFORE_HIERARCHY_OK": "unknown" if before.get("hierarchy_ok") is None else str(bool(before.get("hierarchy_ok"))).lower(),
        "AFTER_HIERARCHY_OK": "unknown" if after is None or after.get("hierarchy_ok") is None else str(bool(after.get("hierarchy_ok"))).lower(),
        "FOREGROUND_PACKAGE": final_observation.get("foreground_package") or details.get("foreground_package") or "",
        "HIERARCHY_PACKAGE": final_observation.get("hierarchy_package") or "",
        "FOCUSED_PACKAGE": final_observation.get("hierarchy_focused_package") or "",
        "CONTAMINATION_HINT": contamination_hint or details.get("contamination_hint") or "",
        "CONTAMINATION_HINT_CURRENT": str(bool(details.get("contamination_hint_current"))).lower(),
        "CONTAMINATION_HINT_SOURCE": details.get("contamination_hint_source") or "",
        "BEFORE_CONTAMINATION_PACKAGE": before_contamination or "",
        "AFTER_CONTAMINATION_PACKAGE": after_contamination or "",
        "FINAL_CONTAMINATION_PACKAGE": final_contamination or "",
        "CONTAMINATION_PACKAGE": final_contamination or "",
        "BEFORE_CONTAMINATION_EVIDENCE_SOURCE": _external_popup_evidence_source(before) or "",
        "CONTAMINATION_EVIDENCE_SOURCE": final_evidence_source or "",
        "HIERARCHY_FAILURE_STAGE": final_observation.get("hierarchy_failure_stage") or "",
        "HIERARCHY_TRANSPORT_STATUS": final_observation.get("hierarchy_transport_status") or "unknown",
        "HIERARCHY_SCHEMA_RESULT": final_observation.get("hierarchy_schema_result") or "unknown",
        "HIERARCHY_ROOT_RESULT": final_observation.get("hierarchy_root_result") or "unknown",
        "HIERARCHY_REQUEST_ID": final_observation.get("hierarchy_request_id") or "",
        "HIERARCHY_OPERATION_ID": final_observation.get("hierarchy_operation_id") or "",
        "RECOVERY_HIERARCHY_ERROR": details.get("recovery_hierarchy_error") or "",
        "RECOVERY_ATTEMPTED": str(bool(details.get("recovery_attempted"))).lower(),
        "RECOVERY_ACTION_ATTEMPTED": str(bool(recovery_action_attempted)).lower(),
        "SURFACE_RECOVERED": str(bool(surface_recovered)).lower(),
        "RECOVERY_RESULT": (
            details.get("recovery")
            or ("RECOVERED" if surface_recovered else "FAILED")
            if recovery_action_attempted else ("RECOVERED" if surface_recovered else "NOT_ATTEMPTED")
        ),
    }
    formatted = " ".join(
        f"{key}='{_readiness_log_value(value)}'" for key, value in fields.items()
    )
    log_fn(f"[PREFLIGHT][readiness] {formatted}")


def _readiness_log_value(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("'", "_")
    return text[:240]


def _popup_failure_reason(popup_status: dict[str, object]) -> str:
    reason = str(popup_status.get("reason") or "")
    if reason in {
        "external_popup_contamination",
        "service_hierarchy_acquisition_failed",
        "readiness_surface_evidence_unavailable",
        "readiness_recovery_dependency_unavailable",
    }:
        return reason
    if popup_status.get("contamination_package") and popup_status.get("contamination_evidence_source") != "hint_only_suspicion":
        return "external_popup_contamination"
    before = popup_status.get("before")
    if isinstance(before, dict) and before.get("hierarchy_ok") is False:
        return "service_hierarchy_acquisition_failed"
    return "readiness_surface_evidence_unavailable"


def _log_samsung_account_popup(log_fn: Callable[[str], None], popup_status: dict[str, object]) -> None:
    detected = bool(popup_status.get("detected"))
    log_fn(
        "[PREFLIGHT][popup] samsung_account_security "
        f"detected={str(detected).lower()} "
        f"locale='{popup_status.get('locale') or ''}' "
        f"title='{popup_status.get('title') or ''}'"
    )
    if not detected:
        return
    log_fn(
        "[PREFLIGHT][popup] samsung_account_security dismiss "
        f"method={popup_status.get('method') or ''} "
        f"target='{popup_status.get('resource_id') or ''}' "
        f"label='{popup_status.get('label') or ''}' "
        f"ok={str(bool(popup_status.get('dismissed'))).lower()} "
        f"verified_gone='{popup_status.get('verified_gone')}'"
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
