from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from talkback_lib import A11yAdbClient
from tb_runner.accessibility_preflight import (
    HELPER_SERVICE_COMPONENT,
    AccessibilityPreflightResult,
    ensure_accessibility_service_enabled,
)


@dataclass(frozen=True)
class CorePreflightResult:
    ok: bool
    reason: str
    accessibility: AccessibilityPreflightResult
    talkback_status: str
    talkback_reason: str


def run_preflight(
    *,
    client: A11yAdbClient,
    serial: str | None,
    log_fn: Callable[[str], None],
) -> CorePreflightResult:
    accessibility = ensure_accessibility_service_enabled(
        serial=serial,
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
        return CorePreflightResult(False, accessibility.reason, accessibility, "unknown", "")

    talkback = client.check_talkback_ready(dev=serial)
    talkback_status = talkback.get("status", "disabled")
    talkback_reason = talkback.get("reason", "")
    log_fn(f"[PREFLIGHT] talkback status='{talkback_status}'")
    if talkback_status == "disabled":
        return CorePreflightResult(False, "talkback_off", accessibility, talkback_status, talkback_reason)
    if talkback_status == "enabled_but_not_ready":
        return CorePreflightResult(False, talkback_reason or "talkback_not_ready", accessibility, talkback_status, talkback_reason)
    return CorePreflightResult(True, "ok", accessibility, talkback_status, talkback_reason)

