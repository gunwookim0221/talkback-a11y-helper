# TalkBack A11y Helper (`com.iotpart.sqe.talkbackhelper`)

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
  - 현재 접근성 포커스에서 부모로 올라가며 스크롤 가능한 노드를 찾고, 없으면 루트 트리를 BFS로 순회해 첫 번째 스크롤 가능한 노드로 폴백한 뒤, 그래도 없으면 화면 전체에서 가장 큰 스크롤 가능한 노드를 찾아 방향별 스크롤 수행
  - 현재 포커스 노드에 텍스트 입력(`ACTION_SET_TEXT`) 수행
- `A11yCommandReceiver`
  - 브로드캐스트 액션 처리
    - `com.iotpart.sqe.talkbackhelper.GET_FOCUS`
    - `com.iotpart.sqe.talkbackhelper.DUMP_TREE`
    - `com.iotpart.sqe.talkbackhelper.FOCUS_TARGET`
    - `com.iotpart.sqe.talkbackhelper.CLICK_TARGET`
    - `com.iotpart.sqe.talkbackhelper.CHECK_TARGET`
    - `com.iotpart.sqe.talkbackhelper.NEXT`
    - `com.iotpart.sqe.talkbackhelper.PREV`
    - `com.iotpart.sqe.talkbackhelper.CLICK_FOCUSED`
    - `com.iotpart.sqe.talkbackhelper.SCROLL` (`forward` boolean, `direction` string)
    - `com.iotpart.sqe.talkbackhelper.SET_TEXT` (`text` string)
- `A11yNavigator`
  - 화면 트리 DFS 순회
  - Flat JSON 배열 덤프 생성
  - `targetName` + `targetType(t|b|r|a)` + `targetIndex(0-based)` 기본 매칭 지원
  - 매칭 노드를 DFS 순서로 카운트하여 `targetIndex`번째 노드에 액션 수행
  - `targetType`: `t`/`b`/`r`는 공통 regex 패턴(`Regex(regexPattern)`)으로 매칭됩니다. `.*`, `.+`, `^`, `$` 패턴이 없으면 내부적으로 exact regex(`^...$`)로 처리됩니다. `a`는 앞 3개 OR 매칭입니다.
  - 추가 AND 필터: `className`, `clickable`, `focusable`, `targetText`(text/contentDescription contains), `targetId`(viewId regex)
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
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.GET_FOCUS -p com.iotpart.sqe.talkbackhelper --ez saveFile true --es reqId "focus-001"
```

### 2) 전체 화면 트리 덤프

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.DUMP_TREE -p com.iotpart.sqe.talkbackhelper --es reqId "dump-001"
```

- logcat: `DUMP_TREE_RESULT <reqId> [...]` 또는 `DUMP_TREE_PART <reqId> ...` 여러 줄 + `DUMP_TREE_END <reqId>` 형식으로 출력됩니다.
- 각 노드 필드: `text`, `contentDescription`, `className`, `viewIdResourceName`, `boundsInScreen`, `clickable`, `focusable`, `isVisibleToUser`

### 3) 특정 타겟 접근성 포커스

(선택) `--es className`, `--es clickable`, `--es focusable`, `--es targetText`, `--es targetId`를 함께 전달해 추가 조건을 AND로 결합할 수 있습니다.


```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.FOCUS_TARGET -p com.iotpart.sqe.talkbackhelper --es targetName "확인" --es targetType "t" --ei targetIndex 0
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {...}`
- 병렬 실행 시 `--es reqId "<id>"`를 전달하면 결과 JSON/로그에 동일한 `reqId`가 포함되어 상관관계 추적이 가능합니다.

### 4) 특정 타겟 클릭/롱클릭

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.CLICK_TARGET -p com.iotpart.sqe.talkbackhelper --es targetName "확인" --es targetType "a" --ei targetIndex 0 --ez isLongClick false
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.CLICK_TARGET -p com.iotpart.sqe.talkbackhelper --es targetName "더보기" --es targetType "b" --ei targetIndex 1 --ez isLongClick true
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {...}`

### 5) 객체 존재 여부 확인(CHECK_TARGET)

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.CHECK_TARGET -p com.iotpart.sqe.talkbackhelper --es targetName "com.example.app:id/btn_ok" --es targetType "r" --ei targetIndex 0
```

- logcat: `A11Y_HELPER CHECK_TARGET_RESULT {"success":...}`

### 6) 접근성 포커스 다음/이전 이동

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.NEXT -p com.iotpart.sqe.talkbackhelper --es reqId "run-001"
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.PREV -p com.iotpart.sqe.talkbackhelper --es reqId "run-002"
```

- logcat: `A11Y_HELPER NAV_RESULT {"success":...,"direction":"NEXT|PREV"}`

### 7) 현재 접근성 포커스 클릭

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.CLICK_FOCUSED -p com.iotpart.sqe.talkbackhelper
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {"success":...,"action":"CLICK_FOCUSED"}`

### 8) 로그 확인

```bash
adb logcat -d | grep A11Y_HELPER
```

### 9) 스크롤

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.SCROLL -p com.iotpart.sqe.talkbackhelper --ez forward true --es direction down
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.SCROLL -p com.iotpart.sqe.talkbackhelper --ez forward false --es direction up
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.SCROLL -p com.iotpart.sqe.talkbackhelper --ez forward true --es direction right
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.SCROLL -p com.iotpart.sqe.talkbackhelper --ez forward false --es direction left
```

- logcat: `A11Y_HELPER SCROLL_RESULT {"success":...,"action":"SCROLL_FORWARD|SCROLL_BACKWARD",...}`

### 10) 텍스트 입력

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.SET_TEXT -p com.iotpart.sqe.talkbackhelper --es text "테스트 입력"
```

- logcat: `A11Y_HELPER SET_TEXT_RESULT {"success":...,"action":"SET_TEXT",...}`

## `talkback_lib.py` 레거시 호환 API

- 다중 단말 지원: `A11yAdbClient(dev_serial="...")`로 기본 단말 시리얼을 설정할 수 있으며, 대부분 메서드는 `dev`(문자열 serial 또는 `dev.serial`) 인자를 우선 사용합니다. 내부적으로 `adb -s <serial>`로 실행됩니다.
- `clear_logcat(dev=None)`
  - 외부에서 직접 호출 가능한 공개 메서드이며, 지정 단말의 logcat 버퍼를 `adb logcat -c`로 초기화합니다.
- `touch(dev, name, wait_=5, type_='a', index_=0, long_=False, class_name=None, clickable=None, focusable=None)`
  - 호출마다 내부적으로 고유 `reqId`를 생성해 브로드캐스트에 포함하고, 동일 `reqId`를 가진 결과 로그만 소비합니다.
  - 액션 시작 시 `last_announcements`를 초기화하고, `wait_` 동안 폴링하며 `CLICK_TARGET`을 전송합니다.
  - 성공 시 Smart Wait 단계에서 TalkBack 안내를 자동 수집하고 `client.last_announcements`에 저장한 뒤 `True`를 반환합니다.
  - `name`에 리스트를 주고 `type_='and'`를 사용하면 다중 조건 모드로 동작합니다. 리스트 항목에서 리소스 ID 형태(`.../id/...`, `.*` 시작)는 `targetId`, 일반 문자열은 `targetText`로 분류해 전송합니다.
  - 실패가 계속되면 0.5초 간격 재시도 후 `False`를 반환합니다.
- `isin(dev, name, wait_=5, type_='a', index_=0, class_name=None, clickable=None, focusable=None)`
  - 액션 시작 시 `last_announcements`를 초기화합니다.
  - `CHECK_TARGET`으로 존재 여부만 확인하며 성공 시 즉시 `True`, 타임아웃 시 `False`입니다.
- `select(dev, name, wait_=5, type_='a', index_=0, class_name=None, clickable=None, focusable=None)`
  - `touch()`와 동일한 폴링 루틴을 사용하지만 클릭 대신 `FOCUS_TARGET` 액션으로 접근성 포커스만 이동합니다.
  - 성공 시 `True`, 타임아웃 시 `False`를 반환합니다.
- `scroll(dev, direction, step_=50, time_=1000, bounds_=None)`
  - 레거시 시그니처 호환을 위해 `step_`, `time_`, `bounds_` 인자는 유지하지만 내부에서는 사용하지 않습니다.
  - `direction`을 `d/down→down`, `u/up→up`, `r/right→right`, `l/left→left`로 정규화해 브로드캐스트의 `direction` extra로 전달합니다.
  - 정규화된 방향 기준으로 `down/right`는 forward, `up/left`는 backward를 사용합니다.
  - `SCROLL_RESULT` 로그의 `success` 값을 기준으로 `True/False`를 반환합니다.
- `scrollFind(dev, name, wait_=30, direction_='updown', type_='all')`
  - `wait_` 시간 동안 `isin(..., wait_=0)`으로 대상 존재를 먼저 확인하고, 없으면 `scroll()`을 호출해 탐색합니다.
  - `type_` 별칭을 내부 코드로 변환합니다 (`all→a`, `text→t`, `talkback→b`, `resourceid→r`).
  - 찾으면 `True`, 타임아웃이면 `None`을 반환합니다.
- `typing(dev, name, adbTyping=False)`
  - `adbTyping=True`면 `adb shell input text`를 사용합니다.
  - 기본값(`False`)에서는 `SET_TEXT` 브로드캐스트로 현재 포커스된 입력창에 텍스트를 설정합니다.
  - 성공 시 `None`, 실패 시 `False`를 반환합니다.
- `waitForActivity(dev, ActivityName, waitTime)`
  - `waitTime`(ms) 동안 `adb shell dumpsys window windows`를 폴링합니다.
  - 출력에 `mCurrentFocus` 또는 `ActivityName`이 포함되면 즉시 `True`, 타임아웃이면 `False`를 반환합니다.
- `dump_tree(dev=None, wait_seconds=5.0)`
  - 액션 시작 시 `last_announcements`를 초기화합니다.
  - 긴 트리 로그(`DUMP_TREE_PART`)를 여러 줄로 수집한 뒤 모두 병합하여 JSON으로 파싱합니다.
- `get_announcements(dev=None, wait_seconds=2.0, only_new=True)`
  - 수집 전에 `check_talkback_status(dev)`로 TalkBack 활성 여부를 확인합니다.
  - 비활성으로 판단되면 `"TalkBack이 꺼져 있어 음성을 수집할 수 없습니다"`를 출력하고 빈 리스트를 반환합니다.
  - `only_new=True`(기본): 내부 마커 이후의 새 `A11Y_ANNOUNCEMENT`만 수집합니다.
  - `only_new=False`: 마커를 무시하고 현재 logcat 버퍼의 전체 안내를 수집합니다.
  - 수집 결과는 반환값과 함께 `client.last_announcements`에도 항상 저장됩니다.
- `check_talkback_status(dev=None) -> bool`
  - 1단계: `adb shell pm list packages`로 헬퍼 앱(`com.iotpart.sqe.talkbackhelper`) 설치 여부를 먼저 확인합니다.
  - 2단계-헬퍼 앱 있음: 최근 `logcat`에 `A11Y_ANNOUNCEMENT` 로그가 있는지 확인해 상태를 판단합니다.
  - 2단계-헬퍼 앱 없음(Fallback): `adb shell settings get secure enabled_accessibility_services` 출력에 `com.google.android.marvin.talkback` 포함 여부로 판단합니다.
  - ADB 실패/단말 미연결 포함 예외 상황은 모두 `False`를 반환합니다.
- 공통적으로 각 루프에서 `_refresh_tree_if_needed()`를 호출해 화면 변동(팝업 등)에 대응합니다.
