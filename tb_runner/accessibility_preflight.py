from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from talkback_lib.constants import DEFAULT_ADB_PATH, DEFAULT_PACKAGE_NAME


HELPER_SERVICE_CLASS = "com.iotpart.sqe.talkbackhelper.A11yHelperService"
HELPER_SERVICE_COMPONENT = f"{DEFAULT_PACKAGE_NAME}/{HELPER_SERVICE_CLASS}"


@dataclass(frozen=True)
class AccessibilitySettings:
    enabled_accessibility_services: str
    accessibility_enabled: str


@dataclass(frozen=True)
class AccessibilityPreflightResult:
    ok: bool
    reason: str
    before: AccessibilitySettings
    after: AccessibilitySettings
    enable_attempted: bool
    helper_ready: bool


def split_enabled_accessibility_services(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"null", "none"}:
        return []
    services: list[str] = []
    seen: set[str] = set()
    for item in raw.split(":"):
        service = item.strip()
        if not service or service.lower() in {"null", "none"}:
            continue
        key = service.lower()
        if key in seen:
            continue
        seen.add(key)
        services.append(service)
    return services


def build_enabled_accessibility_services_value(current_value: str | None, component: str = HELPER_SERVICE_COMPONENT) -> str:
    services = split_enabled_accessibility_services(current_value)
    if component.lower() not in {service.lower() for service in services}:
        services.append(component)
    return ":".join(services)


def is_accessibility_enabled(value: str | None) -> bool:
    return str(value or "").strip() == "1"


def has_helper_service(current_value: str | None, component: str = HELPER_SERVICE_COMPONENT) -> bool:
    return component.lower() in {service.lower() for service in split_enabled_accessibility_services(current_value)}


def _adb_command(adb_path: str, serial: str | None, *args: str) -> list[str]:
    command = [adb_path]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    return command


def run_adb_text(adb_path: str, serial: str | None, *args: str, timeout: float = 15.0) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            _adb_command(adb_path, serial, *args),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = completed.stdout.strip()
    if completed.returncode != 0:
        detail = completed.stderr.strip() or output
        return False, detail
    return True, output


def read_accessibility_settings(
    *,
    serial: str | None = None,
    adb_path: str = DEFAULT_ADB_PATH,
    adb_get: Callable[[str], str] | None = None,
) -> AccessibilitySettings:
    if adb_get is not None:
        return AccessibilitySettings(
            enabled_accessibility_services=adb_get("enabled_accessibility_services"),
            accessibility_enabled=adb_get("accessibility_enabled"),
        )
    ok_services, services = run_adb_text(
        adb_path,
        serial,
        "shell",
        "settings",
        "get",
        "secure",
        "enabled_accessibility_services",
    )
    ok_enabled, enabled = run_adb_text(
        adb_path,
        serial,
        "shell",
        "settings",
        "get",
        "secure",
        "accessibility_enabled",
    )
    return AccessibilitySettings(
        enabled_accessibility_services=services if ok_services else "",
        accessibility_enabled=enabled if ok_enabled else "",
    )


def ensure_accessibility_service_enabled(
    *,
    serial: str | None = None,
    adb_path: str = DEFAULT_ADB_PATH,
    component: str = HELPER_SERVICE_COMPONENT,
    adb_get: Callable[[str], str] | None = None,
    adb_put: Callable[[str, str], bool] | None = None,
    helper_ready_check: Callable[[], bool] | None = None,
    log_fn: Callable[[str], None] | None = None,
    settle_seconds: float = 0.8,
) -> AccessibilityPreflightResult:
    def log(message: str) -> None:
        if log_fn is not None:
            log_fn(message)

    before = read_accessibility_settings(serial=serial, adb_path=adb_path, adb_get=adb_get)
    service_present = has_helper_service(before.enabled_accessibility_services, component)
    accessibility_on = is_accessibility_enabled(before.accessibility_enabled)
    enable_attempted = False

    if not service_present or not accessibility_on:
        enable_attempted = True
        if not accessibility_on:
            log("[PREFLIGHT][accessibility] accessibility_disabled")
        if not service_present:
            log("[PREFLIGHT][accessibility] helper_service_missing")
        next_services = build_enabled_accessibility_services_value(before.enabled_accessibility_services, component)
        if adb_put is not None:
            services_ok = bool(adb_put("enabled_accessibility_services", next_services))
            enabled_ok = bool(adb_put("accessibility_enabled", "1"))
        else:
            services_ok, _ = run_adb_text(
                adb_path,
                serial,
                "shell",
                "settings",
                "put",
                "secure",
                "enabled_accessibility_services",
                next_services,
            )
            enabled_ok, _ = run_adb_text(
                adb_path,
                serial,
                "shell",
                "settings",
                "put",
                "secure",
                "accessibility_enabled",
                "1",
            )
        if not services_ok or not enabled_ok:
            after_failed = read_accessibility_settings(serial=serial, adb_path=adb_path, adb_get=adb_get)
            log("[PREFLIGHT][accessibility] enable_attempt_failed")
            return AccessibilityPreflightResult(
                ok=False,
                reason="enable_attempt_failed",
                before=before,
                after=after_failed,
                enable_attempted=enable_attempted,
                helper_ready=False,
            )
        time.sleep(max(0.0, settle_seconds))

    after = read_accessibility_settings(serial=serial, adb_path=adb_path, adb_get=adb_get)
    if not is_accessibility_enabled(after.accessibility_enabled):
        log("[PREFLIGHT][accessibility] accessibility_disabled")
        return AccessibilityPreflightResult(False, "accessibility_disabled", before, after, enable_attempted, False)
    if not has_helper_service(after.enabled_accessibility_services, component):
        log("[PREFLIGHT][accessibility] helper_service_missing")
        return AccessibilityPreflightResult(False, "helper_service_missing", before, after, enable_attempted, False)

    helper_ready = True
    if helper_ready_check is not None:
        try:
            helper_ready = bool(helper_ready_check())
        except Exception:
            helper_ready = False
    if not helper_ready:
        log("[PREFLIGHT][accessibility] helper_ready_timeout")
        return AccessibilityPreflightResult(False, "helper_ready_timeout", before, after, enable_attempted, False)

    return AccessibilityPreflightResult(True, "ok", before, after, enable_attempted, True)
