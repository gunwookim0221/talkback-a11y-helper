#!/usr/bin/env python3
"""Helper APK broadcast 프로토콜 레이어."""

from __future__ import annotations

import time
import uuid
import threading
from collections import OrderedDict
from typing import Any

from talkback_lib.adb_device import AdbCommandFailure

from talkback_lib.constants import (
    ACTION_GET_FOCUS,
    ACTION_EVIDENCE_EVENTS,
    ACTION_PING,
    ACTION_SMART_NEXT,
    ACTION_FOCUS_IN_BOUNDS,
    ACTION_TARGET_FOCUS_COMMIT,
    RED_TEXT,
    RESET_TEXT,
    STATUS_FAILED,
    STATUS_LOOPED,
    STATUS_MOVED,
    STATUS_SCROLLED,
)


class HelperBridge:
    BRIDGE_VERSION = "1.0.1"
    _PREFLIGHT_LIGHT_CMD_TIMEOUT_SEC = 5.0
    # Failed-run results arrived in 41.946–55.903s; ten broadcasts then ANRed
    # around 60s. Navigation completion is independent of the unchanged 30s
    # command-delivery limit. Never retry an action whose delivery is uncertain.
    SMART_NAV_RESULT_WAIT_SECONDS = 75.0
    # FOCUS_IN_BOUNDS already took 30.454s. These commands scan the same
    # accessibility trees as SMART_NEXT (observed up to ~60s); share its
    # bounded operation budget, independently of 30s broadcast delivery.
    FOCUS_RESULT_WAIT_SECONDS = 75.0

    def __init__(self, client: Any) -> None:
        self._client = client
        self._smart_request_lock = threading.Lock()
        self._smart_request_ids: OrderedDict[str, None] = OrderedDict()
        self._expired_smart_requests: OrderedDict[str, bool] = OrderedDict()
        self._async_lock = threading.RLock()
        self._async_in_flight: set[str] = set()
        self._focus_request_ids: OrderedDict[str, str] = OrderedDict()
        self._expired_focus_requests: OrderedDict[str, bool] = OrderedDict()

    def is_focus_request(self, req_id: str) -> bool:
        with self._async_lock:
            return req_id in self._focus_request_ids

    def observe_late_focus_results(self, logs: str) -> None:
        with self._async_lock:
            retired = list(self._expired_focus_requests.items())
        for req_id, observed in retired:
            if observed:
                continue
            transport = self._client._logcat_reader.reassemble_chunked_payload(logs, "TARGET_ACTION_RESULT", req_id)
            payloads = [transport["payload"]] if transport.get("state") == "complete" else []
            if transport.get("state") == "absent":
                payloads = self._client._extract_all_payloads(logs, "TARGET_ACTION_RESULT")
            for payload in payloads:
                try:
                    result = self._client._parse_json_payload(payload, "TARGET_ACTION_RESULT")
                except Exception:
                    continue
                if result.get("reqId") == req_id:
                    with self._async_lock:
                        self._expired_focus_requests[req_id] = True
                    self._client._safe_trace_print(f"[FOCUS_TRANSPORT] late_result req_id={req_id} ignored=true reason=retired_request")
                    break

    def request_focus_command(self, dev: Any, action: str, req_id: str, extras: list[str]) -> dict[str, Any]:
        if action not in {ACTION_FOCUS_IN_BOUNDS, ACTION_TARGET_FOCUS_COMMIT}:
            raise ValueError("Unsupported asynchronous focus command")
        with self._async_lock:
            if req_id in self._focus_request_ids:
                return {"success": False, "status": "transport_error", "reason": "duplicate_focus_request_id", "reqId": req_id}
            self._focus_request_ids[req_id] = action
            self._async_in_flight.add(req_id)
            while len(self._focus_request_ids) > 1024:
                expired = next((key for key in self._focus_request_ids if key not in self._async_in_flight), None)
                if expired is None:
                    break
                del self._focus_request_ids[expired]
        self._client._safe_trace_print(f"[FOCUS_TRANSPORT] before_broadcast action={action} req_id={req_id}")
        started = time.monotonic()
        try:
            try:
                stdout = self._client._broadcast(dev, action, extras)
            except AdbCommandFailure as exc:
                result = {"success": False, "status": "transport_error", "reason": exc.reason, "reqId": req_id,
                          "deliveryElapsedSeconds": time.monotonic() - started,
                          "command": exc.command, "commandTimeoutSeconds": exc.timeout,
                          "commandStdout": exc.stdout, "commandStderr": exc.stderr, "resultWaitStarted": False}
                self._client._safe_trace_print(f"[FOCUS_TRANSPORT] delivery_failed action={action} req_id={req_id} reason={exc.reason} retry=false")
            else:
                delivery = time.monotonic() - started
                self._client._safe_trace_print(f"[FOCUS_TRANSPORT] delivered action={action} req_id={req_id} delivery_seconds={delivery:.3f} result_pending=true")
                result = self._client._read_log_result(dev, "TARGET_ACTION_RESULT", req_id,
                    wait_seconds=self.FOCUS_RESULT_WAIT_SECONDS, poll_interval_sec=0.2)
                result.update(commandStdout=stdout, deliveryElapsedSeconds=delivery,
                              resultWaitSeconds=self.FOCUS_RESULT_WAIT_SECONDS, resultWaitStarted=True)
            if result.get("status") == "transport_error" or result.get("reason") == "json_parse_failed":
                with self._async_lock:
                    self._expired_focus_requests[req_id] = bool(result.get("lateResult"))
                    while len(self._expired_focus_requests) > 64:
                        self._expired_focus_requests.popitem(last=False)
            self._client._safe_trace_print(f"[FOCUS_TRANSPORT] completed action={action} req_id={req_id} status={result.get('status', '')} reason={result.get('reason', '')} retry=false")
            return result
        finally:
            with self._async_lock:
                self._async_in_flight.discard(req_id)

    def observe_late_smart_results(self, logs: str) -> None:
        """Classify retired responses from existing polls without issuing actions."""
        for req_id, observed in list(self._expired_smart_requests.items()):
            if observed:
                continue
            transport = self._client._logcat_reader.reassemble_chunked_payload(logs, "SMART_NAV_RESULT", req_id)
            payloads = [transport["payload"]] if transport.get("state") == "complete" else []
            if transport.get("state") == "absent":
                payloads = self._client._extract_all_payloads(logs, "SMART_NAV_RESULT")
            for payload in payloads:
                try:
                    result = self._client._parse_json_payload(payload, "SMART_NAV_RESULT")
                except Exception:
                    continue
                if result.get("reqId") == req_id:
                    self._expired_smart_requests[req_id] = True
                    self._client._safe_trace_print(f"[SMART_NEXT_TRANSPORT] late_result req_id={req_id} ignored=true reason=retired_request")
                    break

    def _retire_smart_request(self, req_id: str, *, late_observed: bool = False) -> None:
        self._expired_smart_requests[req_id] = late_observed
        while len(self._expired_smart_requests) > 64:
            self._expired_smart_requests.popitem(last=False)

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
        serial_label = serial or "default"
        cache_hit, cached_result = self._client._get_cached_helper_status(serial=serial)
        if cache_hit:
            elapsed = time.monotonic() - started
            self._client._debug_print(
                f"[DEBUG][helper_status] serial={serial_label} cached=True "
                f"result={cached_result} elapsed={elapsed:.3f}s"
            )
            return cached_result

        self._client._debug_print("[PREFLIGHT][helper] checking enabled_accessibility_services")
        try:
            enabled_services = self._client._run(
                ["shell", "settings", "get", "secure", "enabled_accessibility_services"],
                dev=dev,
                timeout=self._PREFLIGHT_LIGHT_CMD_TIMEOUT_SEC,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print(
                f"[PREFLIGHT][helper] adb failure during enabled_accessibility_services error='{exc}'"
            )
            print(
                f"[PREFLIGHT][helper] helper_ready=False reason='adb_failure' "
                f"serial={serial_label} elapsed={elapsed:.3f}s"
            )
            return False
        if not enabled_services:
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print("[PREFLIGHT][helper] adb timeout or failure during enabled_accessibility_services")
            print(
                f"[PREFLIGHT][helper] helper_ready=False reason='adb_timeout_or_failure' "
                f"serial={serial_label} elapsed={elapsed:.3f}s"
            )
            return False
        helper_enabled = self._client.package_name in enabled_services
        if not helper_enabled:
            print(
                f"{RED_TEXT}⚠️ [ERROR] 헬퍼 앱의 접근성 서비스가 꺼져 있습니다. "
                "'설정 > 접근성 > 설치된 앱'에서 활성화해 주세요."
                f"{RESET_TEXT}"
            )
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print(f"[WARN][helper_status] serial={serial_label} result=False reason=service_disabled elapsed={elapsed:.3f}s")
            print(
                f"[PREFLIGHT][helper] helper_ready=False reason='service_disabled' "
                f"serial={serial_label} elapsed={elapsed:.3f}s"
            )
            return False

        self._client._debug_print("[PREFLIGHT][helper] checking helper ping readiness")
        if not self._client.ping(dev=dev, wait_=3.0):
            print(
                f"{RED_TEXT}⚠️ [ERROR] 헬퍼 앱 접근성 서비스가 명령 수신 준비 상태가 아닙니다. "
                "서비스를 다시 시작하거나 접근성 설정을 재확인해 주세요."
                f"{RESET_TEXT}"
            )
            self._client._update_helper_status_cache(serial=serial, result=False)
            elapsed = time.monotonic() - started
            print(f"[WARN][helper_status] serial={serial_label} result=False reason=ping_failed elapsed={elapsed:.3f}s")
            print(
                f"[PREFLIGHT][helper] helper_ready=False reason='ping_failed' "
                f"serial={serial_label} elapsed={elapsed:.3f}s"
            )
            return False

        self._client._update_helper_status_cache(serial=serial, result=True)
        elapsed = time.monotonic() - started
        print(
            f"[PREFLIGHT][helper] helper_ready=True reason='ok' "
            f"serial={serial_label} elapsed={elapsed:.3f}s"
        )
        self._client._debug_print(
            f"[DEBUG][helper_status] serial={serial_label} cached=False "
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
        with self._async_lock:
            self._async_in_flight.add(req_id)
        try:
            return self._request_smart_next_impl(dev, req_id)
        finally:
            with self._async_lock:
                self._async_in_flight.discard(req_id)

    def _request_smart_next_impl(self, dev: Any, req_id: str) -> dict[str, Any]:
        with self._smart_request_lock:
            if req_id in self._smart_request_ids:
                return {"success": False, "status": "transport_error", "reason": "duplicate_smart_next_request_id", "reqId": req_id}
            self._smart_request_ids[req_id] = None
            while len(self._smart_request_ids) > 1024:
                self._smart_request_ids.popitem(last=False)
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
        self._client._safe_trace_print(
            f"[SMART_NEXT_TRACE] before_broadcast action={ACTION_SMART_NEXT} "
            f"req_id={req_id} fallback=false full_adb_command=\"{full_cmd}\""
        )
        correlation_extras = []
        get_correlation_extras = getattr(self._client, "_evidence_correlation_extras", None)
        if callable(get_correlation_extras):
            try:
                correlation_extras = list(get_correlation_extras() or [])
            except Exception:
                correlation_extras = []
        delivery_start = time.monotonic()
        try:
            raw_stdout = self._client._broadcast(
                dev,
                ACTION_SMART_NEXT,
                ["--es", "reqId", req_id, *correlation_extras],
            )
        except AdbCommandFailure as exc:
            self._retire_smart_request(req_id)
            result = {"success": False, "status": "transport_error", "reason": exc.reason, "reqId": req_id,
                      "deliveryElapsedSeconds": time.monotonic() - delivery_start,
                      "commandTimeoutSeconds": exc.timeout, "command": exc.command,
                      "commandStdout": exc.stdout, "commandStderr": exc.stderr, "resultWaitStarted": False}
            self._client._safe_trace_print(f"[SMART_NEXT_TRANSPORT] delivery_failed req_id={req_id} reason={exc.reason} retry=false")
            return result
        delivery_elapsed = time.monotonic() - delivery_start
        self._client._safe_trace_print(
            f"[SMART_NEXT_TRACE] adb_raw_response req_id={req_id} raw_stdout=\"{raw_stdout}\""
        )
        result = self._client._read_log_result(
            dev,
            "SMART_NAV_RESULT",
            req_id,
            wait_seconds=self.SMART_NAV_RESULT_WAIT_SECONDS,
            poll_interval_sec=0.2,
        )
        self._client._safe_trace_print(
            f"[SMART_NEXT_TRACE] parsed_broadcast_result req_id={req_id} raw_json={result}"
        )
        result.update(deliveryElapsedSeconds=delivery_elapsed, resultWaitSeconds=self.SMART_NAV_RESULT_WAIT_SECONDS)
        if not result.get("success") and result.get("status") == "transport_error":
            self._retire_smart_request(req_id, late_observed=bool(result.get("lateResult")))
        self._client._safe_trace_print(f"[SMART_NEXT_TRANSPORT] completed req_id={req_id} delivery_seconds={delivery_elapsed:.3f} result_wait_limit={self.SMART_NAV_RESULT_WAIT_SECONDS} status={result.get('status', '')} reason={result.get('reason', '')} retry=false")
        return result

    def request_evidence_events(self, dev: Any, req_id: str) -> dict[str, Any]:
        """Read an optional Helper evidence snapshot; never affects navigation results."""
        # Do not clear logcat here: delayed per-event evidence is collected by
        # the Runner immediately before this legacy snapshot request.
        self._client._broadcast(dev, ACTION_EVIDENCE_EVENTS, ["--es", "reqId", req_id])
        return self._client._read_log_result(
            dev,
            "EVIDENCE_EVENTS_RESULT",
            req_id,
            wait_seconds=0.1,
            poll_interval_sec=0.05,
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
