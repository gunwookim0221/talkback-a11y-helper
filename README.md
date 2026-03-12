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
    - `com.example.a11yhelper.CHECK_TARGET`
    - `com.example.a11yhelper.NEXT`
    - `com.example.a11yhelper.PREV`
    - `com.example.a11yhelper.CLICK_FOCUSED`
    - `com.example.a11yhelper.SCROLL` (`forward` boolean)
    - `com.example.a11yhelper.SET_TEXT` (`text` string)
- `A11yNavigator`
  - 화면 트리 DFS 순회
  - Flat JSON 배열 덤프 생성
  - `targetName` + `targetType(t|b|r|a)` + `targetIndex(0-based)`로 노드 매칭
  - 매칭 노드를 DFS 순서로 카운트하여 `targetIndex`번째 노드에 액션 수행
  - `targetType`: `t`(text contains), `b`(contentDescription contains), `r`(viewIdResourceName ==), `a`(앞 3개 OR)
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
adb shell am broadcast -a com.example.a11yhelper.FOCUS_TARGET -p com.example.a11yhelper --es targetName "확인" --es targetType "t" --ei targetIndex 0
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {...}`

### 4) 특정 타겟 클릭/롱클릭

```bash
adb shell am broadcast -a com.example.a11yhelper.CLICK_TARGET -p com.example.a11yhelper --es targetName "확인" --es targetType "a" --ei targetIndex 0 --ez isLongClick false
adb shell am broadcast -a com.example.a11yhelper.CLICK_TARGET -p com.example.a11yhelper --es targetName "더보기" --es targetType "b" --ei targetIndex 1 --ez isLongClick true
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {...}`

### 5) 객체 존재 여부 확인(CHECK_TARGET)

```bash
adb shell am broadcast -a com.example.a11yhelper.CHECK_TARGET -p com.example.a11yhelper --es targetName "com.example.app:id/btn_ok" --es targetType "r" --ei targetIndex 0
```

- logcat: `A11Y_HELPER CHECK_TARGET_RESULT {"success":...}`

### 6) 접근성 포커스 다음/이전 이동

```bash
adb shell am broadcast -a com.example.a11yhelper.NEXT -p com.example.a11yhelper
adb shell am broadcast -a com.example.a11yhelper.PREV -p com.example.a11yhelper
```

- logcat: `A11Y_HELPER NAV_RESULT {"success":...,"direction":"NEXT|PREV"}`

### 7) 현재 접근성 포커스 클릭

```bash
adb shell am broadcast -a com.example.a11yhelper.CLICK_FOCUSED -p com.example.a11yhelper
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {"success":...,"action":"CLICK_FOCUSED"}`

### 8) 로그 확인

```bash
adb logcat -d | grep A11Y_HELPER
```

### 9) 스크롤

```bash
adb shell am broadcast -a com.example.a11yhelper.SCROLL -p com.example.a11yhelper --ez forward true
adb shell am broadcast -a com.example.a11yhelper.SCROLL -p com.example.a11yhelper --ez forward false
```

- logcat: `A11Y_HELPER SCROLL_RESULT {"success":...,"action":"SCROLL_FORWARD|SCROLL_BACKWARD",...}`

### 10) 텍스트 입력

```bash
adb shell am broadcast -a com.example.a11yhelper.SET_TEXT -p com.example.a11yhelper --es text "테스트 입력"
```

- logcat: `A11Y_HELPER SET_TEXT_RESULT {"success":...,"action":"SET_TEXT",...}`

## `test_a11y.py` 레거시 호환 API

- 다중 단말 지원: `A11yAdbClient(dev_serial="...")`로 기본 단말 시리얼을 설정할 수 있으며, 대부분 메서드는 `dev`(문자열 serial 또는 `dev.serial`) 인자를 우선 사용합니다. 내부적으로 `adb -s <serial>`로 실행됩니다.
- `clear_logcat(dev=None)`
  - 외부에서 직접 호출 가능한 공개 메서드이며, 지정 단말의 logcat 버퍼를 `adb logcat -c`로 초기화합니다.
- `touch(dev, name, wait_=5, type_='a', index_=0, long_=False)`
  - `wait_` 동안 폴링하며 `CLICK_TARGET`을 전송하고 성공 시 Smart Wait 후 `True` 반환
  - 실패가 계속되면 0.5초 간격 재시도 후 `False` 반환
- `isin(dev, name, wait_=5, type_='a', index_=0)`
  - `CHECK_TARGET`으로 존재 여부만 확인하며 성공 시 즉시 `True`, 타임아웃 시 `False`
- 공통적으로 각 루프에서 `_refresh_tree_if_needed()`를 호출해 화면 변동(팝업 등)에 대응합니다.
- `dump_tree(dev=None, wait_seconds=5.0)`
  - 긴 트리 로그(`DUMP_TREE_PART`)를 여러 줄로 수집한 뒤 모두 병합하여 JSON으로 파싱합니다.
