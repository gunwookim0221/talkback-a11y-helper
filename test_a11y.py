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

    def dump_tree(self, wait_seconds: float = 2.0) -> list[dict[str, Any]]:
        print("[DEBUG] 1. 로그 초기화(logcat -c) 수행...")
        self.clear_logcat()        
        
        print("[DEBUG] 2. 브로드캐스트 명령 전송 중...")
        cmd_out = self._run(["shell", "am", "broadcast", "-a", ACTION_DUMP_TREE, "-p", "com.example.a11yhelper"])
        print(f"[DEBUG] 브로드캐스트 응답: {cmd_out}")
        
        print(f"[DEBUG] 3. {wait_seconds}초 대기...")
        time.sleep(wait_seconds)

        print("[DEBUG] 4. 로그 가져오기 (-s 태그 필터 제외)...")
        # 윈도우 ADB 버그를 피하기 위해 전체 로그를 가져온 뒤 파이썬에서 문자열로 찾습니다.
        logs = self._run(["logcat", "-d"])
        
        a11y_lines = [line for line in logs.splitlines() if "A11Y_HELPER" in line]
        print(f"[DEBUG] 5. A11Y_HELPER 관련 로그 총 {len(a11y_lines)}줄 발견")
        if a11y_lines:
            print(f"[DEBUG] 가장 마지막 줄 미리보기: {a11y_lines[-1][:200]} ...")
            
        payload = self._extract_json_payload(logs, "DUMP_TREE_RESULT")
        if payload is None:
            raise RuntimeError("DUMP_TREE_RESULT 로그를 찾지 못했습니다. (위 디버그 로그를 확인해 주세요)")

        print(f"[DEBUG] 6. JSON 추출 성공! (길이: {len(payload)}자)")
        
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"JSON 파싱 에러 (로그가 길어서 안드로이드가 중간에 잘랐을 수 있습니다): {e}")
            
        if not isinstance(data, list):
            raise RuntimeError("DUMP_TREE_RESULT payload가 JSON 배열이 아닙니다.")
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

        # 여기에도 "-p", "com.example.a11yhelper" 를 필수로 추가합니다!
        cmd = ["shell", "am", "broadcast", "-a", action, "-p", "com.example.a11yhelper"]
        if text:
            cmd += ["--es", "targetText", text]
        if view_id:
            cmd += ["--es", "targetViewId", view_id]
        if class_name:
            cmd += ["--es", "targetClassName", class_name]

        return self._run(cmd)

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
        default="android.widget.Button",
        help="예제 액션에 사용할 targetClassName",
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
