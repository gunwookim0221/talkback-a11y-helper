#!/usr/bin/env python3
"""ADB 기반 TalkBack A11y Helper 테스트 스크립트."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Any


ACTION_DUMP_TREE = "com.example.a11yhelper.DUMP_TREE"
ACTION_GET_FOCUS = "com.example.a11yhelper.GET_FOCUS"
ACTION_FOCUS_TARGET = "com.example.a11yhelper.FOCUS_TARGET"
ACTION_CLICK_TARGET = "com.example.a11yhelper.CLICK_TARGET"
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
    ) -> dict[str, Any]:
        return self._target_action(
            ACTION_CLICK_TARGET,
            t if t is not None else text,
            r if r is not None else view_id,
            c if c is not None else class_name,
        )

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
        start_time = time.time()
        announcements: list[str] = []

        while time.time() - start_time < wait_seconds:
            logs = self._run(["logcat", "-d"])
            for line in logs.splitlines():
                if "A11Y_ANNOUNCEMENT:" not in line:
                    continue
                _, payload = line.split("A11Y_ANNOUNCEMENT:", 1)
                text = payload.strip()
                if text:
                    announcements.append(text)
            if announcements:
                break
            time.sleep(0.3)
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

def test_feedback():
    client = A11yAdbClient()
    
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

if __name__ == "__main__":
    test_feedback()


# if __name__ == "__main__":
#     main()
