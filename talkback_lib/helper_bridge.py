#!/usr/bin/env python3
"""Helper APK broadcast 프로토콜 레이어."""

from __future__ import annotations

import time
import uuid
from typing import Any

from talkback_lib.constants import (
    ACTION_GET_FOCUS,
    ACTION_PING,
    ACTION_SMART_NEXT,
    RED_TEXT,
    RESET_TEXT,
    STATUS_FAILED,
    STATUS_LOOPED,
    STATUS_MOVED,
    STATUS_SCROLLED,
)


class HelperBridge:
    def __init__(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def _parse_broadcast_result(result: dict[str, Any], *, success_key: str = "success") -> bool:
        return bool(result.get(success_key))

    def _ping_helper(self, dev: Any = None, wait_: float = 3.0) -> bool:
        self._client.clear_logcat(dev=dev)
        req_id = str(uuid.uuid4())[:8]
        self._client._broadcast(dev, ACTION_PING, ["--es", "reqId", req_id])
        result = self._client._read_log_result(dev, "PING_RESULT", req_id, wait_seconds=wait_)
        return self._parse_broadcast_result(result) and result.get("status") == "READY"

    def _helper_ready_check(self, dev: Any = None) -> bool:
        started = time.monotonic()
        serial = self._client._resolve_serial(dev)
        cache_hit, cached_result = self._client._get_cached_helper_status(serial=serial)
        if cache_hit:
            elapsed = time.monotonic() - started
            self._client._debug_print(
                f"[DEBUG][helper_status] serial={serial or 'default'} cached=True "
                f"result={cached_result} elapsed={elapsed:.3f}s"
            )
            return cached_result

        enabled_services = self._client._run(
            ["shell", "settings", "get", "secure", "enabled_accessibility_services"],
            dev=dev,
        )
        helper_enabled = self._client.package_name in enabled_services
        if not helper_enabled:
            print(
                f"{RED_TEXT}⚠️ [ERROR] 헬퍼 앱의 접근성 서비스가 꺼져 있습니다. "
                "'설정 > 접근성 > 설치된 앱'에서 활성화해 주세요."
                f"{RESET_TEXT}"
            )
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print(f"[WARN][helper_status] serial={serial or 'default'} result=False reason=service_disabled elapsed={elapsed:.3f}s")
            return False

        if not self._client.ping(dev=dev, wait_=3.0):
            print(
                f"{RED_TEXT}⚠️ [ERROR] 헬퍼 앱 접근성 서비스가 명령 수신 준비 상태가 아닙니다. "
                "서비스를 다시 시작하거나 접근성 설정을 재확인해 주세요."
                f"{RESET_TEXT}"
            )
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print(f"[WARN][helper_status] serial={serial or 'default'} result=False reason=ping_failed elapsed={elapsed:.3f}s")
            return False

        self._client._update_helper_status_cache(serial=serial, result=True)
        elapsed = time.monotonic() - started
        self._client._debug_print(
            f"[DEBUG][helper_status] serial={serial or 'default'} cached=False "
            f"result=True elapsed={elapsed:.3f}s"
        )
        return True

    def _request_get_focus(
        self,
        dev: Any,
        req_id: str,
        wait_seconds: float,
        poll_interval_sec: float = 0.2,
    ) -> dict[str, Any]:
        self._client.clear_logcat(dev=dev)
        self._client._broadcast(dev, ACTION_GET_FOCUS, ["--es", "reqId", req_id])
        return self._client._read_log_result(
            dev,
            "FOCUS_RESULT",
            req_id,
            wait_seconds=wait_seconds,
            poll_interval_sec=poll_interval_sec,
        )

    def _request_smart_next(self, dev: Any, req_id: str) -> dict[str, Any]:
        serial = self._client._resolve_serial(dev)
        cmd_parts = [self._client.adb_path]
        if serial:
            cmd_parts.extend(["-s", serial])
        cmd_parts.extend(
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                ACTION_SMART_NEXT,
                "-p",
                self._client.package_name,
                "--es",
                "reqId",
                req_id,
            ]
        )
        full_cmd = " ".join(cmd_parts)
        print(
            f"[SMART_NEXT_TRACE] before_broadcast action={ACTION_SMART_NEXT} "
            f"req_id={req_id} fallback=false full_adb_command=\"{full_cmd}\""
        )
        self._client._broadcast(dev, ACTION_SMART_NEXT, ["--es", "reqId", req_id])
        return self._client._read_log_result(
            dev,
            "SMART_NAV_RESULT",
            req_id,
            wait_seconds=3.0,
            poll_interval_sec=0.2,
        )

    @staticmethod
    def normalize_smart_next_status(result: dict[str, Any]) -> tuple[str, bool, str, set[str]]:
        detail = str(result.get("detail", "")).strip().lower()
        flags = {
            str(flag).strip().lower()
            for flag in (result.get("flags") or [])
            if str(flag).strip()
        }
        terminal = detail == "end_of_sequence" or "terminal" in flags
        if not result.get("success"):
            return STATUS_FAILED, terminal, detail, flags

        status = str(result.get("status", "failed")).strip().lower()
        normalized = {
            "moved": STATUS_MOVED,
            "scrolled": STATUS_SCROLLED,
            "looped": STATUS_LOOPED,
            "failed": STATUS_FAILED,
            # Backward compatibility for older Android helper builds.
            "moved_to_bottom_bar": STATUS_MOVED,
            "moved_to_bottom_bar_direct": STATUS_MOVED,
            "moved_aligned": STATUS_MOVED,
        }.get(status)
        if normalized is not None:
            return normalized, terminal, detail, flags

        if detail in {"moved_to_bottom_bar", "moved_to_bottom_bar_direct", "moved_aligned"}:
            return STATUS_MOVED, terminal, detail, flags
        return STATUS_FAILED, terminal, detail, flags
