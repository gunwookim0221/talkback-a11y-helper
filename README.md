# TalkBack A11y Helper (`com.example.a11yhelper`)

ADB 기반 자동화에서 접근성 서비스로 **현재 화면 트리를 덤프하고**,
원하는 노드에 대해 **직접 포커스/클릭 액션**을 수행하기 위한 debug용 헬퍼 APK입니다.

## 프로젝트 구성

- `A11yHelperService`
  - 이벤트 수신: `TYPE_VIEW_ACCESSIBILITY_FOCUSED`, `TYPE_VIEW_FOCUSED`, `TYPE_WINDOW_STATE_CHANGED`, `TYPE_ANNOUNCEMENT`
  - `TYPE_ANNOUNCEMENT`, `TYPE_VIEW_ACCESSIBILITY_FOCUSED`, `TYPE_WINDOW_STATE_CHANGED` 발생 시 음성 텍스트를 추출해 `A11Y_ANNOUNCEMENT: ...` 로그 출력
  - `event.text`를 공백으로 합쳐 우선 사용하고, 비어 있으면 `event.source`의 `text + contentDescription`을 fallback으로 사용
  - `TYPE_WINDOW_STATE_CHANGED` 발생 시 `SCREEN_CHANGED` 로그 출력
  - 현재 포커스 노드 스냅샷 JSON 생성/갱신
  - 루트 트리 전체 덤프 및 타겟 액션(포커스/클릭) 수행
  - 현재 포커스 기준 스크롤 가능한 부모 노드를 찾아 스크롤 수행
  - 현재 포커스 노드에 텍스트 입력(`ACTION_SET_TEXT`) 수행
- `A11yCommandReceiver`
  - 브로드캐스트 액션 처리
    - `com.example.a11yhelper.GET_FOCUS`
    - `com.example.a11yhelper.DUMP_TREE`
    - `com.example.a11yhelper.FOCUS_TARGET`
    - `com.example.a11yhelper.CLICK_TARGET`
    - `com.example.a11yhelper.NEXT`
    - `com.example.a11yhelper.PREV`
    - `com.example.a11yhelper.CLICK_FOCUSED`
    - `com.example.a11yhelper.SCROLL` (`forward` boolean)
    - `com.example.a11yhelper.SET_TEXT` (`text` string)
- `A11yNavigator`
  - 화면 트리 DFS 순회
  - Flat JSON 배열 덤프 생성
  - `targetText`/`targetViewId`/`targetClassName` 조건 매칭(입력된 조건은 모두 AND) 후 액션 수행
    - `targetText`는 노드 `text` 또는 `contentDescription`을 `trim()`한 값 기준으로 `contains()` 매칭
    - `targetViewId`/`targetClassName`은 기존과 동일하게 완전 일치(`==`)
- `A11yStateStore`
  - 메모리 `lastFocusJson` 유지
  - 필요 시 `/sdcard/a11y_focus.json` 저장 시도

## 빌드 / 설치

```bash
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## ADB 사용 예시

### 1) 현재 포커스 JSON 요청

```bash
adb shell am broadcast -a com.example.a11yhelper.GET_FOCUS -p com.example.a11yhelper --ez saveFile true
```

### 2) 전체 화면 트리 덤프

```bash
adb shell am broadcast -a com.example.a11yhelper.DUMP_TREE -p com.example.a11yhelper
```

- logcat: 짧은 결과는 `A11Y_HELPER DUMP_TREE_RESULT [...]` 1회 출력, 긴 결과는 `A11Y_HELPER DUMP_TREE_PART ...` 여러 줄 + `A11Y_HELPER DUMP_TREE_END` 출력
- 각 노드 필드: `text`, `contentDescription`, `className`, `viewIdResourceName`, `boundsInScreen`, `clickable`, `focusable`, `isVisibleToUser`

### 3) 특정 타겟 접근성 포커스

```bash
adb shell am broadcast -a com.example.a11yhelper.FOCUS_TARGET -p com.example.a11yhelper --es targetText "확인"
adb shell am broadcast -a com.example.a11yhelper.FOCUS_TARGET -p com.example.a11yhelper --es targetViewId "com.example.app:id/btn_ok"
adb shell am broadcast -a com.example.a11yhelper.FOCUS_TARGET -p com.example.a11yhelper --es targetText "확인" --es targetClassName "android.widget.Button"
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {...}`

### 4) 특정 타겟 클릭

```bash
adb shell am broadcast -a com.example.a11yhelper.CLICK_TARGET -p com.example.a11yhelper --es targetText "확인"
adb shell am broadcast -a com.example.a11yhelper.CLICK_TARGET -p com.example.a11yhelper --es targetViewId "com.example.app:id/btn_ok"
adb shell am broadcast -a com.example.a11yhelper.CLICK_TARGET -p com.example.a11yhelper --es targetText "확인" --es targetClassName "android.widget.Button"
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {...}`

### 5) 접근성 포커스 다음/이전 이동

```bash
adb shell am broadcast -a com.example.a11yhelper.NEXT -p com.example.a11yhelper
adb shell am broadcast -a com.example.a11yhelper.PREV -p com.example.a11yhelper
```

- logcat: `A11Y_HELPER NAV_RESULT {"success":...,"direction":"NEXT|PREV"}`

### 6) 현재 접근성 포커스 클릭

```bash
adb shell am broadcast -a com.example.a11yhelper.CLICK_FOCUSED -p com.example.a11yhelper
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {"success":...,"action":"CLICK_FOCUSED"}`

### 7) 로그 확인

```bash
adb logcat -d | grep A11Y_HELPER
```

### 8) 스크롤

```bash
adb shell am broadcast -a com.example.a11yhelper.SCROLL -p com.example.a11yhelper --ez forward true
adb shell am broadcast -a com.example.a11yhelper.SCROLL -p com.example.a11yhelper --ez forward false
```

- logcat: `A11Y_HELPER SCROLL_RESULT {"success":...,"action":"SCROLL_FORWARD|SCROLL_BACKWARD",...}`

### 9) 텍스트 입력

```bash
adb shell am broadcast -a com.example.a11yhelper.SET_TEXT -p com.example.a11yhelper --es text "테스트 입력"
```

- logcat: `A11Y_HELPER SET_TEXT_RESULT {"success":...,"action":"SET_TEXT",...}`

## `test_a11y.py` 타겟/내비게이션 확인 동작

- `A11yAdbClient`는 기본 패키지명(`com.example.a11yhelper`)을 멤버로 관리하고, 모든 브로드캐스트에 `-p {package_name}`을 자동으로 붙입니다.
- `A11yAdbClient`는 백그라운드 daemon 스레드에서 `adb logcat -v raw -s A11Y_HELPER`를 실시간 감시하고, `SCREEN_CHANGED` 로그를 감지하면 `needs_update=True`로 표시합니다.
- 클라이언트 초기 실행 시 `needs_update=True`로 시작하며, `select_object()`/`touch_object()` 실행 전 `needs_update=True`이면 `dump_tree()`를 자동 수행해 최신 UI 트리를 반영합니다.
- `dump_tree()`가 성공하면 `needs_update=False`로 초기화되며, 클라이언트 종료 시 `close()`로 logcat 프로세스와 감시 스레드를 안전하게 정리합니다.
- 타겟 기반 제어는 `select_object(t/r/c)`로 먼저 포커스를 이동한 뒤 `touch_object(t/r/c)`가 발화 로그를 짧게 수집해 동적 대기(Smart Wait) 후 `click_focused()`를 호출해 클릭을 수행하며, 입력된 조건은 AND 조합으로 전달됩니다.
- 내비게이션 제어는 `move_next()`, `move_prev()`, `click_focused()`를 제공합니다.
- 스크롤/입력 제어는 `scroll_next()`, `scroll_prev()`, `input_text(text)`를 제공합니다.
- 음성 안내 로그 수집은 `get_announcements(wait_seconds=2.0)`를 제공하며, `adb logcat -v time -d` 기준으로 마지막으로 처리한 로그 마커 이후의 라인만 증분 파싱합니다.
- `get_announcements()`는 접두사 뒤 메시지를 `strip()` 처리하고 중복 제거(`seen` 집합) 후 반환하며, `wait_seconds` 동안 짧은 간격으로 반복 조회합니다.
- 상태 조회는 `get_current_focus()`로 `FOCUS_RESULT` 로그 JSON을 딕셔너리로 반환합니다.
- 각 함수는 실행 뒤 `adb logcat -d`를 반복 조회해 `TARGET_ACTION_RESULT` 또는 `NAV_RESULT`(포커스 조회는 `FOCUS_RESULT`)를 파싱하고 성공 여부를 출력합니다.
