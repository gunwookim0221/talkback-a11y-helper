# TalkBack A11y Helper (`com.example.a11yhelper`)

ADB 기반 자동화에서 **TalkBack 오른쪽/왼쪽 스와이프(다음/이전 접근성 포커스 이동)**를 최대한 재현하고,
현재 접근성 포커스 노드 정보를 JSON으로 수집/검증하기 위한 **debug용 헬퍼 APK**입니다.

## 왜 필요한가?

- `adb shell input swipe`/`drag`는 터치 제스처일 뿐이라 TalkBack의 논리적 탐색 제스처와 다를 수 있습니다.
- `keyevent TAB(61)`, `DPAD_RIGHT(22)` 등은 보통 **읽기 순서(traversal)** 가 아니라 포커스 가능한 위젯 중심으로 이동해,
  복잡한 화면(상단바/하단탭/카드/그리드)에서 포커스가 튀는 문제가 자주 발생합니다.
- 일부 삼성 디바이스는 TTS 로그가 평문으로 남지 않아(logcat 인코딩/축약) 읽은 문구를 직접 얻기 어렵습니다.
- 따라서 접근성 서비스에서 포커스 노드의 텍스트/설명/상태/바운드를 별도 기록해 디버깅 가능한 기준을 제공합니다.

---

## 프로젝트 구성

- `A11yHelperService`
  - 이벤트 수신: `TYPE_VIEW_ACCESSIBILITY_FOCUSED`, `TYPE_VIEW_FOCUSED`, `TYPE_WINDOW_STATE_CHANGED`, `TYPE_ANNOUNCEMENT`
  - 현재 포커스 노드 식별(`event.source` 우선 + `findFocus` fallback)
  - 포커스 JSON 생성/갱신/로그 출력
  - NAV 명령(NEXT/PREV) 수행
- `A11yCommandReceiver`
  - 브로드캐스트 액션 처리
    - `com.example.a11yhelper.GET_FOCUS`
    - `com.example.a11yhelper.NEXT`
    - `com.example.a11yhelper.PREV`
- `A11yNavigator`
  - 루트 트리 DFS 순회로 후보 노드 목록 생성(visible + focusable/clickable/text/desc)
  - 현재 인덱스 기반 다음/이전 노드 계산 후 `ACTION_ACCESSIBILITY_FOCUS` 시도
- `A11yStateStore`
  - 메모리 `lastFocusJson` 유지
  - 필요 시 `/sdcard/a11y_focus.json` 저장 시도

---

## 빌드 / 설치

```bash
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

> 본 저장소는 debug 기준입니다(릴리즈 난독화/최적화 대상 아님).

---

## 접근성 서비스 활성화

1. 기기에서 **설정 > 접근성 > 설치된 앱(또는 다운로드한 서비스)** 이동
2. `TalkBack A11y Helper` 서비스 수동 ON

> 주의: ADB로 접근성 서비스를 강제 ON하는 것은 Android 정책/권한/보안 설정에 따라 막히거나 기기별로 동작이 다를 수 있습니다.

---

## ADB 사용 예시

### 1) (참고) DPAD/TAB 이동

```bash
adb shell input keyevent 20   # DPAD_DOWN
adb shell input keyevent 21   # DPAD_LEFT
adb shell input keyevent 22   # DPAD_RIGHT
adb shell input keyevent 23   # DPAD_CENTER
adb shell input keyevent 61   # TAB
```

### 2) 현재 포커스 JSON 요청

```bash
adb shell am broadcast -a com.example.a11yhelper.GET_FOCUS --ez saveFile true
```

- logcat: `A11Y_HELPER FOCUS_RESULT {...}`
- 파일 저장 시도: `/sdcard/a11y_focus.json`
- 추가 응답 broadcast: `com.example.a11yhelper.FOCUS_RESULT` (`json` extra 포함)

### 3) TalkBack 유사 다음/이전 이동 시도

```bash
adb shell am broadcast -a com.example.a11yhelper.NEXT
adb shell am broadcast -a com.example.a11yhelper.PREV
```

- logcat: `A11Y_HELPER NAV_RESULT {...}`

### 4) 로그 확인

```bash
adb logcat -d | grep A11Y_HELPER
```

---

## 출력 JSON 스키마

`FOCUS_UPDATE` / `FOCUS_RESULT`의 기본 구조:

```json
{
  "timestamp": 1710000000000,
  "packageName": "com.example.app",
  "className": "android.widget.Button",
  "viewIdResourceName": "com.example.app:id/btn_ok",
  "text": "확인",
  "contentDescription": "확인 버튼",
  "clickable": true,
  "focusable": true,
  "focused": false,
  "accessibilityFocused": true,
  "selected": false,
  "checkable": false,
  "checked": false,
  "enabled": true,
  "boundsInScreen": {
    "l": 120,
    "t": 840,
    "r": 980,
    "b": 980
  }
}
```

`NAV_RESULT` 예시:

```json
{
  "timestamp": 1710000001000,
  "direction": "NEXT",
  "success": true,
  "reason": "ACTION_ACCESSIBILITY_FOCUS success",
  "fromIndex": 3,
  "targetIndex": 4,
  "target": { "...focus snapshot...": true }
}
```

---

## 제한사항

- OS/보안 제약 및 앱 구현 상태(WebView/Compose/커스텀뷰 등)에 따라
  TalkBack 실제 제스처와 100% 동일한 순서를 재현하지 못할 수 있습니다.
- 삼성 등 일부 기기에서 TTS 로그가 평문이 아닐 수 있어, logcat만으로 읽은 문구 검증이 어렵습니다.
- 개발자 옵션의 **Display speech output** 오버레이는 UIAutomator dump XML에 잡히지 않을 수 있어,
  최종 사용자 체감 문구 검증에는 OCR(스크린샷 기반) 확장이 필요할 수 있습니다.

---

## (선택) Python 자동화 샘플

아래 예시는 step마다 logcat 초기화 → NEXT 호출 → 짧게 대기 → 최신 JSON 파싱 흐름입니다.

```python
#!/usr/bin/env python3
import json
import re
import subprocess
import time

A11Y_TAG = "A11Y_HELPER"


def run(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)


def parse_latest_focus_json(log: str):
    # 예: I/A11Y_HELPER: FOCUS_UPDATE {...}
    pattern = re.compile(r"A11Y_HELPER.*(?:FOCUS_UPDATE|FOCUS_RESULT)\s+(\{.*\})")
    matches = pattern.findall(log)
    if not matches:
        return None
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return None


def expected_utterance_placeholder(focus: dict) -> str:
    # 실제 프로젝트에서는 text/desc/role/state 조합으로 예측 발화를 구성
    # contains/regex 기반 완화 매칭 권장
    text = focus.get("text") or ""
    desc = focus.get("contentDescription") or ""
    cls = focus.get("className") or ""
    checked = focus.get("checked")
    state = "선택됨" if checked else ""
    return " ".join(x for x in [text, desc, cls, state] if x)


def step_next_and_read(wait_s=0.5):
    run("adb logcat -c")
    run("adb shell am broadcast -a com.example.a11yhelper.NEXT")
    time.sleep(wait_s)
    logs = run(f"adb logcat -d | grep {A11Y_TAG}")
    focus = parse_latest_focus_json(logs)
    return focus


if __name__ == "__main__":
    for i in range(5):
        focus = step_next_and_read(wait_s=0.5)
        print(f"step={i} focus={focus}")
        if focus:
            expected = expected_utterance_placeholder(focus)
            print("expected_utterance~", expected)

    print("\nTIP: Display speech output과 최종 비교는 OCR/스크린샷 파이프라인으로 확장하세요.")
```

