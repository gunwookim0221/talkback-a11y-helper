#!/usr/bin/env python3
"""ADB 기반 TalkBack A11y Helper 테스트/클라이언트."""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

ACTION_DUMP_TREE = "com.iotpart.sqe.talkbackhelper.DUMP_TREE"
ACTION_GET_FOCUS = "com.iotpart.sqe.talkbackhelper.GET_FOCUS"
ACTION_FOCUS_TARGET = "com.iotpart.sqe.talkbackhelper.FOCUS_TARGET"
ACTION_CLICK_TARGET = "com.iotpart.sqe.talkbackhelper.CLICK_TARGET"
ACTION_CHECK_TARGET = "com.iotpart.sqe.talkbackhelper.CHECK_TARGET"
ACTION_NEXT = "com.iotpart.sqe.talkbackhelper.NEXT"
ACTION_PREV = "com.iotpart.sqe.talkbackhelper.PREV"
ACTION_CLICK_FOCUSED = "com.iotpart.sqe.talkbackhelper.CLICK_FOCUSED"
ACTION_SCROLL = "com.iotpart.sqe.talkbackhelper.SCROLL"
ACTION_SET_TEXT = "com.iotpart.sqe.talkbackhelper.SET_TEXT"
LOG_TAG = "A11Y_HELPER"
LOGCAT_TIME_PATTERN = re.compile(r"^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})")


@dataclass
class A11yAdbClient:
    adb_path: str = "adb"
    package_name: str = "com.iotpart.sqe.talkbackhelper"
    dev_serial: str | None = None
    start_monitor: bool = True

    def __post_init__(self) -> None:
        self.needs_update = True
        self.last_announcements: list[str] = []
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_proc: subprocess.Popen[str] | None = None
        self._monitor_thread: threading.Thread | None = None
        self._last_log_marker: tuple[tuple[int, int, int, int, int, int], int] | None = None

    def _resolve_serial(self, dev: Any) -> str | None:
        if dev is None:
            return self.dev_serial
        if isinstance(dev, str):
            return dev
        return getattr(dev, "serial", self.dev_serial)

    def _run(self, args: list[str], dev: Any = None, timeout: float = 10.0) -> str:
        serial = self._resolve_serial(dev)
        cmd = [self.adb_path]
        if serial:
            cmd += ["-s", serial]
        cmd += args
        proc = subprocess.run(
            cmd,
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
        )
        return proc.stdout.strip()

    def _broadcast(self, dev: Any, action: str, extras: list[str] | None = None) -> str:
        cmd = ["shell", "am", "broadcast", "-a", action, "-p", self.package_name]
        if extras:
            cmd.extend(extras)
        return self._run(cmd, dev=dev)

    @staticmethod
    def _escape_adb_string(value: str) -> str:
        if value == "":
            return '""'
        return "'" + value.replace("'", "'\\''") + "'"

    @staticmethod
    def _build_target_extras(
        name: str,
        type_: str,
        index_: int,
        long_: bool = False,
        class_name: str | None = None,
        clickable: bool | None = None,
        focusable: bool | None = None,
        target_text: str | None = None,
        target_id: str | None = None,
    ) -> list[str]:
        extras = [
            "--es", "targetName", A11yAdbClient._escape_adb_string(name),
            "--es", "targetType", type_,
            "--ei", "targetIndex", str(index_),
            "--ez", "isLongClick", "true" if long_ else "false",
        ]
        if class_name is not None:
            extras += ["--es", "className", A11yAdbClient._escape_adb_string(class_name)]
        if clickable is not None:
            extras += ["--es", "clickable", "true" if clickable else "false"]
        if focusable is not None:
            extras += ["--es", "focusable", "true" if focusable else "false"]
        if target_text is not None:
            extras += ["--es", "targetText", A11yAdbClient._escape_adb_string(target_text)]
        if target_id is not None:
            extras += ["--es", "targetId", A11yAdbClient._escape_adb_string(target_id)]
        return extras

    def _refresh_tree_if_needed(self, dev: Any = None) -> None:
        if self.needs_update:
            self.dump_tree(dev)

    def _wait_for_speech_if_needed(self, dev: Any = None, enabled: bool = True) -> None:
        if not enabled:
            return
        announcements = self.get_announcements(dev=dev, wait_seconds=1.5, only_new=True)
        if announcements:
            speech_text = announcements[-1]
            wait_time = max(0.5, min(len(speech_text) * 0.12, 4.0))
            time.sleep(wait_time)
        else:
            time.sleep(0.5)

    @staticmethod
    def _extract_json_payload(log_text: str, prefix: str) -> str | None:
        pattern = re.compile(rf"{re.escape(prefix)}\s+(.*)$")
        for line in reversed(log_text.splitlines()):
            m = pattern.search(line)
            if m:
                return m.group(1).strip()
        return None

    @staticmethod
    def _parse_json_payload(payload: str, label: str) -> dict[str, Any]:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{label} JSON 파싱 실패: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{label} JSON 형식이 올바르지 않습니다.")
        return parsed

    def _read_log_result(self, dev: Any, prefix: str, req_id: str, wait_seconds: float = 2.0) -> dict[str, Any]:
        start = time.monotonic()
        while time.monotonic() - start < wait_seconds:
            logs = self._run(["logcat", "-d"], dev=dev)
            payloads = self._extract_all_payloads(logs, prefix)
            for payload in reversed(payloads):
                parsed = self._parse_json_payload(payload, prefix)
                if parsed.get("reqId") == req_id:
                    return parsed
            time.sleep(0.2)
        return {"success": False, "reason": f"{prefix} 로그를 찾지 못했습니다."}

    @staticmethod
    def _extract_all_payloads(log_text: str, prefix: str) -> list[str]:
        pattern = re.compile(rf"{re.escape(prefix)}\s+(.*)$")
        payloads: list[str] = []
        for line in log_text.splitlines():
            m = pattern.search(line)
            if m:
                payloads.append(m.group(1).strip())
        return payloads

    def clear_logcat(self, dev: Any = None) -> str:
        return self._run(["logcat", "-c"], dev=dev)

    def check_talkback_status(self, dev: Any = None) -> bool:
        """TalkBack 활성화 상태를 확인합니다.

        1) 헬퍼 앱 설치 여부 확인
        2) 헬퍼 앱이 있으면 최근 A11Y_ANNOUNCEMENT 로그 존재 여부로 판단
        3) 헬퍼 앱이 없으면 enabled_accessibility_services에서 TalkBack 패키지 포함 여부로 판단

        ADB 실패/단말 미연결 등 예외 상황은 모두 False를 반환합니다.
        """
        try:
            package_list = self._run(["shell", "pm", "list", "packages"], dev=dev)
        except Exception:
            return False

        helper_installed = f"package:{self.package_name}" in package_list

        if helper_installed:
            try:
                logs = self._run(["logcat", "-v", "time", "-d"], dev=dev)
            except Exception:
                return False
            return "A11Y_ANNOUNCEMENT:" in logs

        try:
            enabled_services = self._run(
                ["shell", "settings", "get", "secure", "enabled_accessibility_services"],
                dev=dev,
            )
        except Exception:
            return False

        return "com.google.android.marvin.talkback" in enabled_services

    def dump_tree(self, dev: Any = None, wait_seconds: float = 5.0) -> list[dict[str, Any]]:
        self.last_announcements = []
        self.clear_logcat(dev=dev)
        self._broadcast(dev, ACTION_DUMP_TREE)
        
        start_time = time.time()
        logs = ""
        while time.time() - start_time < wait_seconds:
            # -v raw 옵션을 주어 타임스탬프를 제외한 순수 메시지만 가져오면 파싱이 더 정확해집니다.
            logs = self._run(["logcat", "-v", "raw", "-d"], dev=dev)
            if "DUMP_TREE_END" in logs:
                break
            time.sleep(1.0) # 기기 부하를 고려해 대기 시간을 조금 늘립니다.
    
        # 수집된 모든 PART 로그를 병합
        payload_parts = self._extract_all_payloads(logs, "DUMP_TREE_PART")
        if not payload_parts:
            # 디버깅을 위해 로그 태그가 포함된 라인 출력
            a11y_lines = [l for l in logs.splitlines() if "A11Y_HELPER" in l]
            print(f"[DEBUG] 발견된 로그 요약: {a11y_lines}")
            raise RuntimeError("DUMP_TREE 로그를 찾지 못했습니다.")
    
        payload = "".join(payload_parts)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DUMP_TREE JSON 파싱 실패: {exc}") from exc
        if not isinstance(parsed, list):
            raise RuntimeError("DUMP_TREE JSON 형식이 올바르지 않습니다.")
        return parsed
        

    @staticmethod
    def _split_and_conditions(name: Any, type_: str) -> tuple[str, str, str | None, str | None]:
        if not (isinstance(name, list) and str(type_).strip().lower() == "and"):
            return str(name), str(type_), None, None

        target_text: str | None = None
        target_id: str | None = None
        for item in name:
            token = str(item).strip()
            if not token:
                continue
            looks_like_id = "id/" in token or token.startswith(".*")
            if looks_like_id:
                target_id = token
            else:
                target_text = token

        return "", "", target_text, target_id


    def touch(
        self,
        dev,
        name: str | list[str],
        wait_: int = 5,
        type_: str = "a",
        index_: int = 0,
        long_: bool = False,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> bool:
        self.last_announcements = []
        deadline = time.monotonic() + wait_
        while time.monotonic() <= deadline:
            self._refresh_tree_if_needed(dev)
            self._run(["logcat", "-c"], dev=dev)
            req_id = str(uuid.uuid4())[:8]
            parsed_name, parsed_type, target_text, target_id = self._split_and_conditions(name, type_)
            extras = self._build_target_extras(
                name=parsed_name,
                type_=parsed_type,
                index_=index_,
                long_=long_,
                class_name=class_name,
                clickable=clickable,
                focusable=focusable,
                target_text=target_text,
                target_id=target_id,
            )
            extras += ["--es", "reqId", req_id]
            self._broadcast(
                dev,
                ACTION_CLICK_TARGET,
                extras,
            )
            result = self._read_log_result(dev, "TARGET_ACTION_RESULT", req_id)
            if bool(result.get("success")):
                self._wait_for_speech_if_needed(dev)
                return True
            time.sleep(0.5)
        return False

    def select(
        self,
        dev,
        name: str | list[str],
        wait_: int = 5,
        type_: str = "a",
        index_: int = 0,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> bool:
        self.last_announcements = []
        deadline = time.monotonic() + wait_
        while time.monotonic() <= deadline:
            self._refresh_tree_if_needed(dev)
            self._run(["logcat", "-c"], dev=dev)
            req_id = str(uuid.uuid4())[:8]
            parsed_name, parsed_type, target_text, target_id = self._split_and_conditions(name, type_)
            extras = self._build_target_extras(
                name=parsed_name,
                type_=parsed_type,
                index_=index_,
                class_name=class_name,
                clickable=clickable,
                focusable=focusable,
                target_text=target_text,
                target_id=target_id,
            )
            extras += ["--es", "reqId", req_id]
            self._broadcast(
                dev,
                ACTION_FOCUS_TARGET,
                extras,
            )
            result = self._read_log_result(dev, "TARGET_ACTION_RESULT", req_id)
            if bool(result.get("success")):
                return True
            time.sleep(0.5)
        return False

    def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None) -> bool:
        _ = (step_, time_, bounds_)
        direction_token = str(direction).strip().lower()
        forward_tokens = {"d", "down", "r", "right"}
        backward_tokens = {"u", "up", "l", "left"}
        forward = True if direction_token in forward_tokens else False
        if direction_token not in forward_tokens | backward_tokens:
            forward = True

        self._run(["logcat", "-c"], dev=dev)
        req_id = str(uuid.uuid4())[:8]
        self._broadcast(
            dev,
            ACTION_SCROLL,
            ["--ez", "forward", "true" if forward else "false", "--es", "reqId", req_id],
        )
        result = self._read_log_result(dev, "SCROLL_RESULT", req_id)
        return bool(result.get("success"))

    def scrollFind(self, dev, name, wait_=30, direction_='updown', type_='all'):
        type_map = {
            "all": "a",
            "text": "t",
            "talkback": "b",
            "resourceid": "r",
        }
        parsed_type = type_map.get(str(type_).strip().lower(), str(type_).strip().lower()[:1] or "a")
        deadline = time.monotonic() + wait_
        toggle = True

        while time.monotonic() <= deadline:
            if self.isin(dev, name, wait_=0, type_=parsed_type):
                return True

            direction_token = str(direction_).strip().lower()
            if direction_token in {"updown", "downup"}:
                step_direction = "down" if toggle else "up"
                toggle = not toggle
            else:
                step_direction = direction_

            self.scroll(dev, step_direction)
            time.sleep(0.5)

        return None

    def typing(self, dev, name: str, adbTyping=False):
        try:
            if adbTyping:
                self._run(["shell", "input", "text", self._escape_adb_string(name)], dev=dev)
                return None

            self._run(["logcat", "-c"], dev=dev)
            req_id = str(uuid.uuid4())[:8]
            self._broadcast(dev, ACTION_SET_TEXT, ["--es", "text", self._escape_adb_string(name), "--es", "reqId", req_id])
            result = self._read_log_result(dev, "SET_TEXT_RESULT", req_id)
            if bool(result.get("success")):
                return None
            return False
        except Exception:
            return False

    def waitForActivity(self, dev, ActivityName: str, waitTime: int) -> bool:
        deadline = time.monotonic() + (waitTime / 1000.0)
        while time.monotonic() <= deadline:
            try:
                output = self._run(["shell", "dumpsys", "window", "windows"], dev=dev)
            except Exception:
                output = ""

            if "mCurrentFocus" in output or ActivityName in output:
                return True
            time.sleep(0.2)
        return False

    def isin(
        self,
        dev,
        name: str | list[str],
        wait_: int = 5,
        type_: str = "a",
        index_: int = 0,
        class_name: str = None,
        clickable: bool = None,
        focusable: bool = None,
    ) -> bool:
        self.last_announcements = []
        deadline = time.monotonic() + wait_
        while time.monotonic() <= deadline:
            self._refresh_tree_if_needed(dev)
            self._run(["logcat", "-c"], dev=dev)
            req_id = str(uuid.uuid4())[:8]
            parsed_name, parsed_type, target_text, target_id = self._split_and_conditions(name, type_)
            extras = self._build_target_extras(
                name=parsed_name,
                type_=parsed_type,
                index_=index_,
                class_name=class_name,
                clickable=clickable,
                focusable=focusable,
                target_text=target_text,
                target_id=target_id,
            )
            extras += ["--es", "reqId", req_id]
            self._broadcast(
                dev,
                ACTION_CHECK_TARGET,
                extras,
            )
            result = self._read_log_result(dev, "CHECK_TARGET_RESULT", req_id)
            if bool(result.get("success")):
                return True
            time.sleep(0.5)
        return False

    def get_announcements(self, dev: Any = None, wait_seconds: float = 2.0, only_new: bool = True) -> list[str]:
        if not self.check_talkback_status(dev=dev):
            print("TalkBack이 꺼져 있어 음성을 수집할 수 없습니다")
            self.last_announcements = []
            return []

        start_time = time.monotonic()
        announcements: list[str] = []
        seen: set[str] = set()

        with self._state_lock:
            last_log_marker = self._last_log_marker

        newest_log_marker = last_log_marker

        while True:
            logs = self._run(["logcat", "-v", "time", "-d"], dev=dev)
            for line_index, line in enumerate(logs.splitlines(), start=1):
                parsed_time = self._parse_logcat_time(line)
                if parsed_time is None:
                    continue

                marker = (parsed_time, line_index)
                if newest_log_marker is None or marker > newest_log_marker:
                    newest_log_marker = marker

                if only_new and last_log_marker is not None and marker <= last_log_marker:
                    continue

                if "A11Y_ANNOUNCEMENT:" not in line:
                    continue
                _, payload = line.split("A11Y_ANNOUNCEMENT:", 1)
                message = payload.strip()
                if message and message not in seen:
                    seen.add(message)
                    announcements.append(message)

            elapsed = time.monotonic() - start_time
            if elapsed >= wait_seconds:
                break

            time.sleep(min(0.3, wait_seconds - elapsed))

        with self._state_lock:
            self._last_log_marker = newest_log_marker

        self.last_announcements = announcements

        return announcements

    @staticmethod
    def _parse_logcat_time(line: str) -> tuple[int, int, int, int, int, int] | None:
        match = LOGCAT_TIME_PATTERN.match(line)
        if not match:
            return None

        timestamp = match.group(1)
        month_day, clock = timestamp.split(" ")
        month, day = (int(value) for value in month_day.split("-"))
        hour, minute, sec_millis = clock.split(":")
        second, millis = sec_millis.split(".")
        return (month, day, int(hour), int(minute), int(second), int(millis))
