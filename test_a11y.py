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
ACTION_FOCUS_TARGET = "com.example.a11yhelper.FOCUS_TARGET"
ACTION_CLICK_TARGET = "com.example.a11yhelper.CLICK_TARGET"
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

    def dump_tree(self, wait_seconds: float = 3.0) -> list[dict[str, Any]]:
        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()        
        
        print("[DEBUG] 2. 브로드캐스트 명령 전송 중...")
        # 패키지명을 명시적으로 지정하여 전송
        cmd_out = self._run(["shell", "am", "broadcast", "-a", ACTION_DUMP_TREE, "-p", self.package_name])
        print(f"[DEBUG] 브로드캐스트 응답: {cmd_out}")
        
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
        

    def focus_target(
        self,
        text: str | None = None,
        view_id: str | None = None,
        class_name: str | None = None,
    ) -> str:
        return self._target_action(ACTION_FOCUS_TARGET, text, view_id, class_name)

    def click_target(
        self,
        text: str | None = None,
        view_id: str | None = None,
        class_name: str | None = None,
    ) -> str:
        return self._target_action(ACTION_CLICK_TARGET, text, view_id, class_name)

    def _target_action(
        self,
        action: str,
        text: str | None,
        view_id: str | None,
        class_name: str | None,
    ) -> str:
        if not any([text, view_id, class_name]):
            raise ValueError("text, view_id, class_name 중 최소 하나는 필요합니다.")

        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()

        # 여기에도 "-p", "com.example.a11yhelper" 를 필수로 추가합니다!
        cmd = ["shell", "am", "broadcast", "-a", action, "-p", "com.example.a11yhelper"]
        if text:
            cmd += ["--es", "targetText", text]
        if view_id:
            cmd += ["--es", "targetViewId", view_id]
        if class_name:
            cmd += ["--es", "targetClassName", class_name]

        print("[DEBUG] 2. 브로드캐스트 명령 전송 중...")
        cmd_out = self._run(cmd)
        print(f"[DEBUG] 브로드캐스트 응답: {cmd_out}")

        wait_seconds = 3.0
        print(f"[DEBUG] 3. 로그 대기 및 수집 (최대 {wait_seconds}초)...")
        start_time = time.time()
        logs = ""
        payload: str | None = None

        while time.time() - start_time < wait_seconds:
            logs = self._run(["logcat", "-d"])
            payload = self._extract_json_payload(logs, "TARGET_ACTION_RESULT")
            if payload:
                break
            time.sleep(0.5)

        if payload is None:
            raise RuntimeError("TARGET_ACTION_RESULT 로그를 찾지 못했습니다.")

        result = self._parse_target_action_result(payload)
        print(self._format_target_action_result(result, text, view_id, class_name))
        return cmd_out

    @staticmethod
    def _parse_target_action_result(payload: str) -> dict[str, Any]:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"TARGET_ACTION_RESULT JSON 파싱 실패: {exc}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError("TARGET_ACTION_RESULT JSON 형식이 올바르지 않습니다.")
        return parsed

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

    tree = client.dump_tree()
    print(f"DUMP_TREE 노드 개수: {len(tree)}")

    with open("ui_tree.json", "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
        print("[INFO] 전체 UI 트리를 ui_tree.json 파일로 저장했습니다.")

    print("AND 조건 예제 실행:")
    print(
        "  "
        + " ".join(
            [
                shlex.quote(args.adb),
                "shell am broadcast",
                "-a",
                ACTION_CLICK_TARGET if args.mode == "click" else ACTION_FOCUS_TARGET,
                "--es targetText",
                shlex.quote(args.text),
                "--es targetClassName",
                shlex.quote(args.class_name),
                *(
                    ["--es targetViewId", shlex.quote(args.view_id)]
                    if args.view_id
                    else []
                ),
            ]
        )
    )

    if args.mode == "click":
        output = client.click_target(text=args.text, view_id=args.view_id, class_name=args.class_name)
        print(f"CLICK_TARGET broadcast 결과: {output}")
    else:
        output = client.focus_target(text=args.text, view_id=args.view_id, class_name=args.class_name)
        print(f"FOCUS_TARGET broadcast 결과: {output}")


if __name__ == "__main__":
    main()
