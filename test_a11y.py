#!/usr/bin/env python3
"""ADB 기반 TalkBack A11y Helper 테스트 스크립트."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any


ACTION_DUMP_TREE = "com.example.a11yhelper.DUMP_TREE"
ACTION_GET_FOCUS = "com.example.a11yhelper.GET_FOCUS"
ACTION_FOCUS_TARGET = "com.example.a11yhelper.FOCUS_TARGET"
ACTION_NEXT = "com.example.a11yhelper.NEXT"
ACTION_PREV = "com.example.a11yhelper.PREV"
ACTION_CLICK_FOCUSED = "com.example.a11yhelper.CLICK_FOCUSED"
ACTION_SCROLL = "com.example.a11yhelper.SCROLL"
ACTION_SET_TEXT = "com.example.a11yhelper.SET_TEXT"
LOG_TAG = "A11Y_HELPER"


@dataclass
class A11yAdbClient:
    adb_path: str = "adb"
    package_name: str = "com.example.a11yhelper"
    start_monitor: bool = True

    def __post_init__(self) -> None:
        self.needs_update = True
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_proc: subprocess.Popen[str] | None = None
        self._monitor_thread: threading.Thread | None = None
        self._is_dumping_tree = False

        if self.start_monitor:
            self._monitor_thread = threading.Thread(
                target=self._monitor_logcat,
                name="a11y-logcat-monitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        with self._state_lock:
            proc = self._monitor_proc

        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()

        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)

    def __del__(self) -> None:
        self.close()

    def _monitor_logcat(self) -> None:
        while not self._stop_event.is_set():
            proc: subprocess.Popen[str] | None = None
            try:
                proc = subprocess.Popen(
                    [self.adb_path, "logcat", "-v", "raw", "-s", LOG_TAG],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    bufsize=1,
                )
                with self._state_lock:
                    self._monitor_proc = proc

                if proc.stdout is None:
                    break

                for raw_line in proc.stdout:
                    if self._stop_event.is_set():
                        break
                    if "SCREEN_CHANGED" in raw_line:
                        with self._state_lock:
                            self.needs_update = True
                        print("[MONITOR] SCREEN_CHANGED 감지: 다음 액션 전 트리를 갱신합니다.")
            except Exception as exc:  # pragma: no cover - 운영 환경 복구 루프
                print(f"[MONITOR] logcat 감시 중 오류 발생: {exc}")
            finally:
                with self._state_lock:
                    self._monitor_proc = None

                if proc and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()

            if not self._stop_event.is_set():
                time.sleep(0.2)

    def _maybe_refresh_tree(self) -> None:
        with self._state_lock:
            should_refresh = self.needs_update and not self._is_dumping_tree

        if should_refresh:
            print("[DEBUG] 화면 변경 감지됨: 액션 전 dump_tree() 자동 실행")
            self.dump_tree()

    def _run(self, args: list[str], timeout: float = 10.0) -> str:
        proc = subprocess.run(
            [self.adb_path, *args],
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout,
            encoding='utf-8',    # 안드로이드 로그 인코딩 지정
            errors='ignore'      # 깨진 글자가 있어도 무시하고 진행
        )
        return proc.stdout.strip()

    def clear_logcat(self) -> None:
        self._run(["logcat", "-c"])

    def _broadcast(self, action: str, extras: list[str] | None = None) -> str:
        cmd = ["shell", "am", "broadcast", "-a", action, "-p", self.package_name]
        if extras:
            cmd.extend(extras)
        print("[DEBUG] 브로드캐스트 명령 전송 중...")
        cmd_out = self._run(cmd)
        print(f"[DEBUG] 브로드캐스트 응답: {cmd_out}")
        return cmd_out

    def _read_log_result(self, prefixes: tuple[str, ...], wait_seconds: float = 3.0) -> tuple[str, str]:
        print(f"[DEBUG] 로그 대기 및 수집 (최대 {wait_seconds}초)...")
        start_time = time.time()
        logs = ""
        while time.time() - start_time < wait_seconds:
            logs = self._run(["logcat", "-d"])
            for prefix in prefixes:
                payload = self._extract_json_payload(logs, prefix)
                if payload:
                    return prefix, payload
            time.sleep(0.5)
        raise RuntimeError(f"결과 로그를 찾지 못했습니다. expected={prefixes}")

    @staticmethod
    def _parse_json_payload(payload: str, label: str) -> dict[str, Any]:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{label} JSON 파싱 실패: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{label} JSON 형식이 올바르지 않습니다.")
        return parsed

    @staticmethod
    def _build_target_extras(
        text: str | None,
        view_id: str | None,
        class_name: str | None,
    ) -> list[str]:
        extras: list[str] = []
        if text:
            extras += ["--es", "targetText", text]
        if view_id:
            extras += ["--es", "targetViewId", view_id]
        if class_name:
            extras += ["--es", "targetClassName", class_name]
        return extras

    def dump_tree(self, wait_seconds: float = 3.0) -> list[dict[str, Any]]:
        with self._state_lock:
            self._is_dumping_tree = True

        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()        
        
        cmd_out = self._broadcast(ACTION_DUMP_TREE)
        
        print(f"[DEBUG] 3. 로그 대기 및 수집 (최대 {wait_seconds}초)...")
        start_time = time.time()
        logs = ""
        
        # 로그가 바로 안 찍힐 수 있으므로 반복해서 확인합니다.
        while time.time() - start_time < wait_seconds:
            logs = self._run(["logcat", "-d"])
            if ("DUMP_TREE_PART" in logs and "DUMP_TREE_END" in logs) or "DUMP_TREE_RESULT" in logs:
                break
            time.sleep(0.5)

        # 수집된 로그 라인 수 확인 (디버깅용)
        a11y_lines = [line for line in logs.splitlines() if "A11Y_HELPER" in line]
        print(f"[DEBUG] 4. A11Y_HELPER 관련 로그 총 {len(a11y_lines)}줄 발견")
        
        payload_parts = self._extract_all_payloads(logs, "DUMP_TREE_PART")
        if payload_parts:
            payload = "".join(payload_parts)
            print(f"[DEBUG] chunk 로그 {len(payload_parts)}개를 병합했습니다.")
        else:
            payload = self._extract_json_payload(logs, "DUMP_TREE_RESULT")

        if payload is None:
            # 만약 DUMP_TREE 로그를 찾지 못하면 전체 로그 중 태그가 있는 라인이라도 출력해봅니다.
            if a11y_lines:
                print(f"[DEBUG] 발견된 마지막 로그 내용: {a11y_lines[-1]}")
            raise RuntimeError("DUMP_TREE 로그를 찾지 못했습니다. 기기의 '접근성 서비스'가 켜져 있는지 다시 확인해 주세요.")

        print(f"[DEBUG] 5. JSON 추출 성공! (길이: {len(payload)}자)")
        
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            # 로그가 너무 길면 adb가 자를 수 있습니다. 이 경우 에러 메시지를 상세히 띄웁니다.
            raise RuntimeError(f"JSON 파싱 실패 (로그 잘림 의심): {e}")
        finally:
            with self._state_lock:
                self._is_dumping_tree = False

        with self._state_lock:
            self.needs_update = False

        return data
        

    def select_object(
        self,
        text: str | None = None,
        view_id: str | None = None,
        class_name: str | None = None,
        t: str | None = None,
        r: str | None = None,
        c: str | None = None,
    ) -> dict[str, Any]:
        self._maybe_refresh_tree()
        return self._target_action(
            ACTION_FOCUS_TARGET,
            t if t is not None else text,
            r if r is not None else view_id,
            c if c is not None else class_name,
        )

    def touch_object(
        self,
        text: str | None = None,
        view_id: str | None = None,
        class_name: str | None = None,
        t: str | None = None,
        r: str | None = None,
        c: str | None = None,
        wait_for_speech: bool = True  # 발화 대기 옵션 추가
    ) -> dict[str, Any]:
        """객체를 찾아 포커스를 이동시킨 후, 음성 안내를 듣고 클릭합니다."""
        self._maybe_refresh_tree()
        
        # 1. 타겟에 접근성 포커스 이동
        self.select_object(
            text=text,
            view_id=view_id,
            class_name=class_name,
            t=t,
            r=r,
            c=c,
        )

        # 2. 포커스 이동에 따른 음성 안내 캡처 및 동적 대기 (Smart Wait)
        if wait_for_speech:
            print("[DEBUG] TalkBack 발화 내용 수집 및 대기 중...")
            # 포커스 후 시스템이 읽어주는 내용을 최대 1.5초간 수집
            announcements = self.get_announcements(wait_seconds=1.5)
            
            if announcements:
                # 마지막으로 캡처된 전체 안내 텍스트
                speech_text = announcements[-1] 
                print(f"  🔊 인식된 발화: '{speech_text}'")
                
                # 텍스트 길이에 비례한 대기 시간 계산 (한국어 평균 TTS 속도: 글자당 약 0.1~0.15초)
                # 너무 길게 대기하는 것을 방지하기 위해 최소 0.5초, 최대 4.0초로 제한
                dynamic_delay = len(speech_text) * 0.12 
                wait_time = max(0.5, min(dynamic_delay, 4.0))
                
                print(f"  ⏱️ 글자 수({len(speech_text)}자)에 따라 {wait_time:.1f}초 대기...")
                time.sleep(wait_time)
            else:
                # 캡처된 안내가 없더라도 화면 전환 여유 시간으로 0.5초 대기
                time.sleep(0.5)

        # 3. 캡처 및 대기가 끝나면 더블 탭(클릭) 액션 수행
        return self.click_focused()

    def focus_target(self, text: str | None = None, view_id: str | None = None, class_name: str | None = None) -> dict[str, Any]:
        return self.select_object(text=text, view_id=view_id, class_name=class_name)

    def click_target(self, text: str | None = None, view_id: str | None = None, class_name: str | None = None) -> dict[str, Any]:
        return self.touch_object(text=text, view_id=view_id, class_name=class_name)

    def _target_action(
        self,
        action: str,
        text: str | None,
        view_id: str | None,
        class_name: str | None,
    ) -> dict[str, Any]:
        if not any([text, view_id, class_name]):
            raise ValueError("text, view_id, class_name 중 최소 하나는 필요합니다.")

        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()

        self._broadcast(action, self._build_target_extras(text, view_id, class_name))
        _, payload = self._read_log_result(("TARGET_ACTION_RESULT",))
        result = self._parse_target_action_result(payload)
        print(self._format_target_action_result(result, text, view_id, class_name))
        return result

    def move_next(self) -> dict[str, Any]:
        return self._navigation_action(ACTION_NEXT)

    def move_prev(self) -> dict[str, Any]:
        return self._navigation_action(ACTION_PREV)

    def click_focused(self) -> dict[str, Any]:
        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()
        self._broadcast(ACTION_CLICK_FOCUSED)
        _, payload = self._read_log_result(("TARGET_ACTION_RESULT",))
        result = self._parse_json_payload(payload, "TARGET_ACTION_RESULT")
        print(f"[CLICK_FOCUSED] success={bool(result.get('success'))} payload={result}")
        return result

    def scroll_next(self) -> dict[str, Any]:
        return self._scroll_action(forward=True)

    def scroll_prev(self) -> dict[str, Any]:
        return self._scroll_action(forward=False)

    def input_text(self, text: str) -> dict[str, Any]:
        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()
        self._broadcast(ACTION_SET_TEXT, ["--es", "text", text])
        _, payload = self._read_log_result(("SET_TEXT_RESULT",))
        result = self._parse_json_payload(payload, "SET_TEXT_RESULT")
        print(f"[SET_TEXT] success={bool(result.get('success'))} payload={result}")
        return result

    def get_announcements(self, wait_seconds: float = 2.0) -> list[str]:
        start_time = time.monotonic()
        announcements: list[str] = []
        seen: set[str] = set()

        while True:
            logs = self._run(["logcat", "-d"])
            for line in logs.splitlines():
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

        return announcements

    def get_current_focus(self) -> dict[str, Any]:
        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()
        self._broadcast(ACTION_GET_FOCUS)
        _, payload = self._read_log_result(("FOCUS_RESULT",))
        result = self._parse_json_payload(payload, "FOCUS_RESULT")
        print(f"[GET_FOCUS] 포커스 객체 확인 완료: {result}")
        return result

    def _navigation_action(self, action: str) -> dict[str, Any]:
        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()
        self._broadcast(action)
        _, payload = self._read_log_result(("NAV_RESULT",))
        result = self._parse_json_payload(payload, "NAV_RESULT")
        direction = result.get("direction", "UNKNOWN")
        print(f"[{direction}] NAV_RESULT success={bool(result.get('success'))} payload={result}")
        return result

    def _scroll_action(self, forward: bool) -> dict[str, Any]:
        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()
        self._broadcast(ACTION_SCROLL, ["--ez", "forward", "true" if forward else "false"])
        _, payload = self._read_log_result(("SCROLL_RESULT",))
        result = self._parse_json_payload(payload, "SCROLL_RESULT")
        direction = "NEXT" if forward else "PREV"
        print(f"[SCROLL_{direction}] SCROLL_RESULT success={bool(result.get('success'))} payload={result}")
        return result

    @staticmethod
    def _parse_target_action_result(payload: str) -> dict[str, Any]:
        return A11yAdbClient._parse_json_payload(payload, "TARGET_ACTION_RESULT")

    @staticmethod
    def _format_target_action_result(
        result: dict[str, Any],
        text: str | None,
        view_id: str | None,
        class_name: str | None,
    ) -> str:
        success = bool(result.get("success"))
        reason = result.get("reason", "(reason 없음)")
        action = result.get("action", "UNKNOWN")
        lines = [
            f"[{action}] TARGET_ACTION_RESULT",
            f"  - success: {success}",
            f"  - reason : {reason}",
        ]

        if not success:
            lines.append("  - 요청 조건:")
            if text:
                lines.append(f"    * targetText: {text}")
            if view_id:
                lines.append(f"    * targetViewId: {view_id}")
            if class_name:
                lines.append(f"    * targetClassName: {class_name}")

        return "\n".join(lines)

    @staticmethod
    def _extract_all_payloads(log_text: str, prefix: str) -> list[str]:
        pattern = re.compile(rf"{re.escape(prefix)}\s+(.*)$")
        payloads: list[str] = []
        for line in log_text.splitlines():
            m = pattern.search(line)
            if m:
                payloads.append(m.group(1).strip())
        return payloads

    @staticmethod
    def _extract_json_payload(log_text: str, prefix: str) -> str | None:
        pattern = re.compile(rf"{re.escape(prefix)}\s+(.*)$")
        for line in reversed(log_text.splitlines()):
            m = pattern.search(line)
            if m:
                return m.group(1).strip()
        return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TalkBack A11y Helper ADB 테스트")
    parser.add_argument("--adb", default="adb", help="adb 실행 파일 경로")
    parser.add_argument("--text", default="확인", help="예제 액션에 사용할 targetText")
    parser.add_argument(
        "--class-name",
        default=None,  # 기본값을 None으로 설정하여 필수 조건에서 제외합니다.
        help="필요한 경우에만 클래스명을 지정하여 필터링합니다.",
    )
    parser.add_argument("--view-id", default=None, help="예제 액션에 사용할 targetViewId")
    parser.add_argument(
        "--mode",
        choices=["focus", "click"],
        default="click",
        help="예제에서 실행할 타겟 액션",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = A11yAdbClient(adb_path=args.adb)
    try:
        # 1. 현재 화면 트리 덤프 (동작 확인용)
        tree = client.dump_tree()
        print(f"DUMP_TREE 노드 개수: {len(tree)}")

        # 2. '라이프' 텍스트를 가진 객체 선택(포커스) 테스트
        print("\n['라이프' 선택 테스트 시작]")
        # select_object 함수는 t(text), r(resource_id), c(class_name) 인자를 지원합니다.
        result = client.select_object(t="라이프")
        
        if result.get("success"):
            print("성공: '라이프' 객체에 접근성 포커스가 이동되었습니다.")
        else:
            print(f"실패: {result.get('reason')}")

        result1 = client.click_focused()
        
        if result1.get("success"):
            print("성공: 객체에 접근성 포커스가 선택되었습니다.")
        else:
            print(f"실패: {result1.get('reason')}")
    finally:
        client.close()

def test_feedback():
    client = A11yAdbClient()
    try:
        # 1. '라이프' 탭 클릭 시도
        print("['라이프' 탭 클릭]")
        client.touch_object(t="라이프")
        
        # 2. 클릭 직후 약 2초간 발생하는 음성 안내 수집
        # TalkBack이 "라이프 탭이 선택되었습니다" 또는 "라이프 화면입니다" 등을 읽어줍니다.
        announcements = client.get_announcements(wait_seconds=2.0)
        
        print(f"\n[실시간 음성 피드백 결과]")
        if announcements:
            for msg in announcements:
                print(f"- TalkBack 안내 내용: {msg}")
        else:
            print("- 캡처된 음성 안내가 없습니다. (TalkBack 활성화 여부 확인 필요)")
    finally:
        client.close()

if __name__ == "__main__":
    test_feedback()


# if __name__ == "__main__":
#     main()
