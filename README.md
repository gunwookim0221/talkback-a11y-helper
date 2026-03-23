# TalkBack A11y Helper (`com.iotpart.sqe.talkbackhelper`)

ADB 기반 자동화에서 접근성 서비스로 **현재 화면 트리를 덤프하고**,
원하는 노드에 대해 **직접 포커스/클릭 액션**을 수행하기 위한 debug용 헬퍼 APK입니다.

## 배경 및 목적

기존 사내 UI 자동화 라이브러리는 객체 탐색 및 클릭 기능을 포함해, **일반 테스트 환경에서 안정적으로 동작**합니다.

다만 **TalkBack이 활성화된 접근성 테스트 환경**에서는 일부 화면/컴포넌트에서 기존 라이브러리가 UI 객체를 정확히 인식하거나 제어하지 못하는 사례가 확인되었습니다.

`talkback-a11y-helper`는 이 문제를 보완하기 위한 **특수 목적 헬퍼 앱**으로,

- 기존 라이브러리를 대체하지 않고,
- 일반 환경에서는 기존(레거시) 자동화 함수를 그대로 사용하며,
- 접근성(TalkBack) 환경에서 기존 함수가 실패하는 구간에 한해 **Override/Fallback 경로**로 동작합니다.

즉, 본 프로젝트의 목적은 “전면 교체”가 아니라, **접근성 환경 전용 보완 수단**을 제공해 자동화 안정성을 높이는 것입니다.

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
    - `com.iotpart.sqe.talkbackhelper.SMART_NEXT`
    - `com.iotpart.sqe.talkbackhelper.CLICK_FOCUSED`
    - `com.iotpart.sqe.talkbackhelper.SCROLL` (`forward` boolean, `direction` string)
    - `com.iotpart.sqe.talkbackhelper.SET_TEXT` (`text` string)
    - `com.iotpart.sqe.talkbackhelper.PING` (상태 확인)
- `A11yNavigator`
  - 알고리즘 버전: `NAVIGATOR_ALGORITHM_VERSION = 2.11.4`
  - `SMART_NEXT` 스크롤 후 폴링 중 트리 변경을 감지하면 즉시 탐색하지 않고 `[SMART_NEXT] Tree change detected, waiting for settling...` 로그 후 300ms 안착 대기를 추가로 수행한 뒤 최신 `rootInActiveWindow`로 재확인하여 중간 항목 누락을 줄임
  - `SMART_NEXT` 스냅샷 비교는 상단 앱바/하단 내비게이션 바를 제외한 컨텐츠 중심 텍스트·설명·뷰 ID 토큰을 사용해 시간/상태바 같은 미세 변화로 폴링이 조기 종료되는 문제를 완화
  - `SMART_NEXT` 스크롤 후 후보 탐색 시 `isVisibleToUser=true`여도 `bounds.bottom <= screenTop || bounds.top >= screenBottom`인 물리적 오프스크린 노드는 제외하고 `[SMART_NEXT] Skipping off-screen node: $label` 로그를 기록
  - 스크롤 후(`isScrollAction=true`) 직전 항목 제외 조건(`excludeDesc`)으로 탐색했는데 유효 포커스를 찾지 못하면, `[SMART_NEXT] Fallback loop triggered - resetting filters` 로그와 함께 `isScrollAction=false`, `excludeDesc=null`, `startIndex=0`, `status=looped`로 1회 루핑 재탐색해 무한 재귀를 차단
  - `SMART_NEXT` 시작 시 하단 탭 후보(`isBottomNavigationBarNode=true`)의 최상단 Top 좌표를 `effectiveBottom`으로 계산해 실제 콘텐츠 가시 영역 하한으로 사용(없으면 물리 `screenBottom` 사용)
  - `effectiveBottom` 계산 시 하단바 후보는 반드시 화면 하단 절반(`Top > screenHeight / 2`)에 위치해야 하며, 조건을 만족한 노드에 대해 `[SMART_NEXT] Effective bottom set to ...` 진단 로그를 남김
  - 노드 포커스/가시성 통합 루틴에서는 일반 콘텐츠에만 `ACTION_SHOW_ON_SCREEN`을 허용하고, `isTopAppBarNode` 또는 `isBottomNavigationBarNode`로 판별된 고정 UI는 어떤 경우에도 호출하지 않아 시스템 Bounce를 차단
  - `findMainScrollContainer`가 화면에서 가장 큰 스크롤 가능 노드(예: `RecyclerView`)를 메인 스크롤 컨테이너로 선택해 이후 고정 UI 판별과 실제 스크롤 대상 선택의 기준점으로 사용
  - `isFixedSystemUI`는 노드/조상에 `Toolbar`·`ActionBar`·`BottomNavigationView` 계열 식별자가 있으면 우선 고정 UI로 분류하되, 일반 콘텐츠 컨테이너(`ViewGroup`·`FrameLayout` 등)는 메인 스크롤 영역 근처 콘텐츠로 취급합니다. 메인 스크롤 기준 바깥 노드 중에서는 `Button`·`ImageButton` 클래스만 엄격한 고정 UI 후보로 보고, `Add`/`More options` 계열 시스템 버튼일 때만 최종 고정 UI로 확정
  - 스크롤 직전 화면에 보인 라벨을 `visibleHistory`로 저장하되, 스크롤 후 히스토리 필터는 `inHistory=true`인 후보를 기본적으로 모두 스킵하며, 스크롤 직후 1차 탐색에서는 메인 스크롤 내부의 상단 후보도 예외 없이 건너뛰고 새 컨텐츠를 끝까지 우선 탐색합니다
  - 스크롤 후 새 컨텐츠를 찾지 못했을 때만 Fallback Loop로 상단부터 재탐색하여, 기존 히스토리(예: Music Sync)로 즉시 역주행하지 않고 새 카드(예: Food)를 먼저 찾도록 강화
  - `[SMART_DEBUG] Index, Label, Y_Bottom, Eff_Bottom, InHistory` 좌표 기반 로그를 모든 후보 노드에 출력
  - 스크롤 후 첫 콘텐츠 재포커스는 항상 `startIndex=0`에서 시작하되, `visibleHistory` 필터로 상단바/이전 페이지 잔류 항목을 스킵해 신규 콘텐츠를 우선 탐색
  - 스크롤 대기 구간은 스크롤 직후 반드시 200ms를 먼저 대기한 뒤, 최대 10회(150ms 간격) 동안 새 `rootInActiveWindow`의 전체 노드 텍스트/설명/리소스 ID 스냅샷 문자열을 이전 화면 스냅샷과 비교해 트리 갱신을 감지하고, 10회 모두 실패하면 마지막으로 500ms를 한 번 더 대기한 최신 루트로 재탐색해 안전하게 후속 포커스를 이어감
  - `findAndFocusFirstContent(..., allowLooping = false)`를 통해 새 콘텐츠가 없을 때 루핑을 막고 즉시 `failed_no_new_content`를 반환할 수 있음
  - `SMART_NEXT`에서 다음 후보가 하단 탭이고 스크롤 가능한 컨테이너가 있으면 먼저 스크롤한 뒤, 새 콘텐츠가 없을 경우 원래의 하단 탭(Home 등)에 바로 포커스를 이동해 리스트 끝에서 위로 루프하지 않음
  - 위 하단 탭 진입 흐름에서 `ACTION_SCROLL_FORWARD`가 `false`를 반환해도 리스트 끝으로 간주하고 즉시 하단바 대상에 포커스를 시도해 탐색이 중단되지 않음
  - `ACTION_ACCESSIBILITY_FOCUS` 성공 직후 `Thread.sleep(100)`으로 시스템 포커스 안착 시간을 확보해 외부 검증 도구의 타이밍 오판을 줄임
  - 포커스 전 `ACTION_SHOW_ON_SCREEN`이 실행되면 100ms를 추가 대기해 큰 카드가 완전히 안착한 뒤 포커스를 시도
  - `ACTION_ACCESSIBILITY_FOCUS`가 `false`를 반환하면 50ms 간격으로 최대 3회 재시도하고, 반환값은 계속 `false`여도 최종적으로 `isAccessibilityFocused=true`이면 TalkBack이 선점한 것으로 간주해 성공 처리
  - `SMART_NEXT`에서 현재 포커스 노드 기준 부모 방향으로 올라가며 `isScrollable && ACTION_SCROLL_FORWARD`를 동시에 만족하는 가장 가까운 스크롤 가능한 조상을 우선 스크롤 대상으로 사용(잘못된 컨테이너 스크롤 방지)
  - 리스트 마지막/다음 인덱스 미존재 상황에서도 즉시 Loop하지 않고, 스크롤 가능한 컨테이너가 있으면 항상 `ACTION_SCROLL_FORWARD`를 먼저 시도한 뒤 실패 시에만 Loop 수행
  - 노드 동일성/인덱스 매칭 Fallback은 `id + text + contentDescription` 3중 키를 사용해 동일 ID/텍스트 카드 간 오인식을 방지
  - 스크롤 후 첫 컨텐츠 재포커스 시 직전 포커스 노드의 `contentDescription`과 동일하고 화면 상단 30% 이내에 있는 노드만 1회 건너뜀(중복 ID 환경에서 신규 콘텐츠 오인식 방지)
  - 상단 고정 영역 판별: 클래스(`toolbar/actionbar/appbarlayout`) + 리소스 ID 키워드(`title_bar/header/toolbar/more_menu/action_bar/home_button/tab_title/header_bar/add_menu/add_button/menu_button`)만 사용(좌표 기반 15% 임계값 제거)
  - 하단 고정 영역 판별: 클래스(`bottomnavigation/tablayout/navigationbar`) + 리소스 ID 키워드(`bottom/footer/tab_bar/navigation/menu_bar/menu_favorites/menu_devices/menu_life/menu_routines/menu_menu/bottom_menu/bottom_tab/bottom_nav`)만 사용(좌표 기반 15% 임계값 제거)
  - 하단 경계의 리스트 카드(예: `Pet Care`)가 잘못 스킵되지 않도록 하단바 판별은 클래스/ID 키워드만 사용하고 좌표 기반(bottom 20%) 오인식 로직을 배제
  - 포커스 시도 직전에 `[SMART_DEBUG] Attempting focus on Index:$index, AlreadyFocused:${node.isAccessibilityFocused}` 로그를 남겨 시스템 선점 여부를 추적
  - `performSmartNext` 시작 시 현재 `findFocus(FOCUS_ACCESSIBILITY)` 노드가 있으면 새 타겟으로 이동하기 직전에 `ACTION_CLEAR_ACCESSIBILITY_FOCUS`를 먼저 보내 끈적한 포커스 락을 해제
  - 중복 포커스 스킵은 더 이상 `node.isAccessibilityFocused`나 라벨 문자열만으로 판단하지 않고, 실제 시스템 포커스(`findFocus(FOCUS_ACCESSIBILITY)`)와 타겟의 `BoundsInScreen`이 완전히 일치할 때만 재사용
  - `performSmartNext`는 현재 포커스 매칭 인덱스가 직전 성공 인덱스(`lastRequestedFocusIndex`)보다 뒤처지지 않으면 stale 매칭으로 간주하고 `lastRequestedFocusIndex + 1`로 강제 전진해 중복 카드 구간 무한 루프를 차단
  - `findAndFocusFirstContent(...)`는 현재 시스템 포커스와 좌표가 완전히 같은 후보를 라벨과 무관하게 즉시 skip하며, 일반 이동(`isScrollAction=false`)에서는 이 중복 좌표 스킵을 더 엄격히 적용
  - 같은 행(Y 좌표 동일)의 노드로 이동할 때는 포커스 명령 직전 50ms 지연을 추가
  - `performFocusWithVisibilityCheck(...)`는 포커스 요청 직전에 `ACTION_CLEAR_ACCESSIBILITY_FOCUS`와 `TYPE_VIEW_ACCESSIBILITY_FOCUS_CLEARED` 이벤트를 함께 보내 캐시를 비우고, 직전 명령과 동일한 인덱스라면 `isAccessibilityFocused=true`도 stale 상태로 간주해 재요청
  - 라벨이 `<no-label>`인 타겟은 스크롤 직후 TalkBack 선점 포커스 재사용 로직(`scrolled_auto_focused`)을 우회하고 항상 `ACTION_ACCESSIBILITY_FOCUS`를 강제 실행해 연속 무라벨 구간을 돌파
  - 포커스 성공 직후 상단 정렬/하단 끌어올리기 보정이 필요해도, 상단바/하단바는 `ACTION_SHOW_ON_SCREEN`과 관련 로그를 모두 생략하고 일반 콘텐츠에만 보정을 적용
  - 스크롤 직후 이미 포커스된 노드가 화면 하단 20% 영역에 있으면 이전 페이지 잔류 포커스로 간주해 무시하고 다음 후보를 탐색
  - TalkBack 유사 규칙으로 포커스 컨테이너(`clickable` 또는 `screenReaderFocusable`) 식별
  - 컨테이너 노드에 하위 가시 노드 텍스트/콘텐츠 설명을 병합(독립 `clickable` 자식은 별도 노드 유지)
  - 최종 리스트 반환 직전에, 병합된 `text`와 `contentDescription`이 모두 공백/비어 있는 `clickable=true` 노드는 의미 없는 껍데기 버튼으로 간주해 완전히 제외
  - 최종 덤프 노드를 `boundsInScreen` 기준 상→하, 좌→우(행 버킷) 정렬하되, 부모-자식 포함 관계가 있으면 좌표와 무관하게 부모를 자식보다 먼저 배치
  - `targetName` + `targetType(t|b|r|a)` + `targetIndex(0-based)` 기본 매칭 지원
  - 매칭 노드를 DFS 순서로 카운트하여 `targetIndex`번째 노드에 액션 수행
  - 매칭 노드가 `clickable=false`면 최초의 `clickable=true` 조상을 찾아 타겟을 보정(Parent Resolution)하며, 조상이 없으면 원래 노드를 사용
  - `targetType`: `t`/`b`/`r`는 공통 regex 패턴(`Regex(regexPattern, IGNORE_CASE)`)으로 **대소문자 구분 없이** 매칭됩니다. `.*`, `.+`, `^`, `$` 패턴이 없으면 내부적으로 exact regex(`^...$`)로 처리됩니다. `a`는 앞 3개 OR 매칭입니다.
  - 추가 AND 필터: `className`(ignoreCase contains), `clickable`, `focusable`, `targetText`(text/contentDescription ignoreCase contains), `targetId`(viewId regex, ignoreCase)
  - `clickable` 필터는 Parent Resolution으로 보정된 최종 타겟 노드를 기준으로 검증
- `A11yStateStore`
  - 메모리 `lastFocusJson` 유지
  - 필요 시 `/sdcard/a11y_focus.json` 저장 시도

## 빌드 / 설치

```bash
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## ADB 사용 예시


> 보안 제한: `A11yCommandReceiver`는 `android.permission.DUMP` 권한 송신자만 브로드캐스트를 보낼 수 있도록 제한됩니다(ADB shell/시스템 권한 앱).

### 1) 현재 포커스 JSON 요청

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.GET_FOCUS -p com.iotpart.sqe.talkbackhelper --ez saveFile true --es reqId "focus-001"
```

### 2) 헬퍼 준비 상태 확인(PING)

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.PING -p com.iotpart.sqe.talkbackhelper --es reqId "ping-001"
```

- logcat: `A11Y_HELPER PING_RESULT {"reqId":"ping-001","success":true,"status":"READY"}`

### 3) 전체 화면 트리 덤프

```bash
adb shell am broadcast -a com.iotpart.sqe.talkbackhelper.DUMP_TREE -p com.iotpart.sqe.talkbackhelper --es reqId "dump-001"
```

- logcat: `DUMP_TREE_RESULT <reqId> [...]` 또는 `DUMP_TREE_PART <reqId> ...` 여러 줄 + `DUMP_TREE_END <reqId>` 형식으로 출력됩니다.
- 서비스 미연결 시에도 `reqId`가 포함된 실패 JSON(예: `{"reqId":"dump-001","success":false,"reason":"Accessibility Service is null or not running"}`)이 결과 태그로 출력됩니다.
- 각 노드 필드: `text`, `contentDescription`, `className`, `viewIdResourceName`, `boundsInScreen`, `clickable`, `focusable`, `isVisibleToUser`, `isTopAppBar`, `isBottomNavigationBar`

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
- `NEXT/PREV`는 트리 순회 시 클릭 가능한 부모를 가진 자식 노드(예: 카드 내부 Text/Image)를 이동 경로에서 제외하여 TalkBack 그룹 포커스와 동일하게 동작합니다.

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
  - `timeout=5.0`으로 실행되며, `subprocess.TimeoutExpired` 발생 시 `"[WARN] logcat -c timed out, skipping..."`를 출력하고 빈 문자열(`""`)을 반환합니다.
- `touch(dev, name, wait_=5, type_='a', index_=0, long_=False, class_name=None, clickable=None, focusable=None)`
  - 호출마다 내부적으로 고유 `reqId`를 생성해 브로드캐스트에 포함하고, 동일 `reqId`를 가진 결과 로그만 소비합니다.
  - 액션 시작 시 `last_announcements`를 초기화하고, `wait_` 동안 폴링하며 `CLICK_TARGET`을 전송합니다.
  - 성공 시 Smart Wait 단계에서 TalkBack 안내를 자동 수집하고 `client.last_announcements`에 저장한 뒤 `True`를 반환합니다.
  - `name`에 리스트를 주고 `type_='and'`를 사용하면 다중 조건 모드로 동작합니다. 리스트 항목에서 리소스 ID 형태(`.../id/...`, `.*` 시작)는 `targetId`, 일반 문자열은 `targetText`로 분류해 전송합니다.
  - 실패가 계속되면 0.5초 간격 재시도 후 `False`를 반환합니다.
- `isin(dev, name, wait_=5, type_='a', index_=0, class_name=None, clickable=None, focusable=None)`
  - 액션 시작 시 `last_announcements`를 초기화합니다.
  - 브로드캐스트 전 `dump_tree()` 결과의 **전체 노드**를 전수 조사해 사전 매칭을 수행합니다.
  - `type_='text'`/`'t'` 매칭은 `text`뿐 아니라 `contentDescription`도 함께 검색하며, 대소문자를 구분하지 않습니다.
  - `CHECK_TARGET`으로 존재 여부만 확인하며 성공 시 즉시 `True`, 타임아웃 시 `False`입니다.
  - `targetName` 문자열은 대소문자 구분 없는 정규식 매칭으로 처리됩니다. `select()/isin()/트리 사전 매칭` 모두 `(?i)` + `re.IGNORECASE` 기준으로 동작하며, `Pet.*`는 `pet`, `Pets`, `PET` 모두 매칭됩니다.
  - 매칭 실패 시 현재 화면에서 수집한 텍스트 노드 전체를 `"현재 화면 텍스트: [...]"` 형태로 디버그 출력합니다.
- `select(dev, name, wait_=5, type_='a', index_=0, class_name=None, clickable=None, focusable=None)`
  - `touch()`와 동일한 폴링 루틴을 사용하지만 클릭 대신 `FOCUS_TARGET` 액션으로 접근성 포커스만 이동합니다.
  - `targetName`은 `isin()`과 동일하게 대소문자 구분 없는 정규식 매칭(`(?i)`)으로 처리합니다.
  - 성공 시 `True`, 타임아웃 시 `False`를 반환합니다.
- `move_focus(dev=None, direction='next')`
  - TalkBack 탐색 포커스를 `direction` 기준으로 한 칸 이동합니다. (`'next'` 또는 `'prev'`)
  - 실행 전 `check_helper_status(dev)` 안전 검증 후 `clear_logcat()`을 호출하고, 요청별 `reqId`를 생성해 `NEXT/PREV` 브로드캐스트를 전송합니다.
  - 결과는 `NAV_RESULT` 로그에서 동일 `reqId`로 매칭해 판독하며, `success=True`인 경우 `_wait_for_speech_if_needed()`를 호출해 음성 안내가 시작될 시간을 대기합니다.
  - 실패 시 `reason`을 에러 로그로 남기고 `False`를 반환합니다.
- `scroll(dev, direction, step_=50, time_=1000, bounds_=None)`
  - 레거시 시그니처 호환을 위해 `step_`, `time_`, `bounds_` 인자는 유지하지만 내부에서는 사용하지 않습니다.
  - `direction`을 `d/down→down`, `u/up→up`, `r/right→right`, `l/left→left`로 정규화해 브로드캐스트의 `direction` extra로 전달합니다.
  - 정규화된 방향 기준으로 `down/right`는 forward, `up/left`는 backward를 사용합니다.
  - `ACTION_SCROLL` 전송 직후, 결과 판독 전 **항상 `1.5초` 대기**하여 시스템 노드 데이터 동기화 시간을 확보합니다.
  - `SCROLL_RESULT` 로그의 `success` 값을 기준으로 `True/False`를 반환합니다.
- `scrollFind(dev, name, wait_=30, direction_='updown', type_='all')`
  - `wait_` 시간 동안 `isin(..., wait_=0)`으로 대상 존재를 먼저 확인하고, 없으면 `scroll()`을 호출해 탐색합니다.
  - `type_` 별칭을 내부 코드로 변환합니다 (`all→a`, `text→t`, `talkback→b`, `resourceid→r`).
  - `direction_='updown'`이면 아래(`down`)부터 시작하고, 화면 끝에서 스크롤 실패(`scroll()==False`)가 발생했을 때만 위(`up`)로 **한 번만** 방향 전환합니다.
  - `direction_='downup'`이면 위(`up`)부터 시작하고, 마찬가지로 스크롤 실패 시에만 아래(`down`)로 한 번 전환합니다.
  - 단일 방향(`up/down/left/right` 등) 지정 시에는 방향 전환 없이 해당 방향만 유지합니다.
  - 스크롤이 실제로 성공(`scroll()==True`)하면 `needs_update=True`로 표시해 다음 `isin()`에서 UI 트리를 강제로 최신화합니다. 스크롤 실패 시에는 불필요한 트리 갱신을 유발하지 않습니다.
  - 매 스크롤 시도 전/후로 `dump_tree()`를 수행하고, 노드의 `텍스트 + boundsInScreen(위치)` 조합 변화 여부를 기준으로 화면 변화를 판단합니다. 이때 화면 전체가 아니라 **상단 15%/하단 15%를 제외한 중앙 70% 영역**만 비교해, 고정 탭 바가 있어도 실제 리스트 이동을 안정적으로 감지합니다.
  - 변화가 없으면 `"화면 끝 도달 감지: 스크롤 전/후 텍스트/위치 변화가 없습니다."` 로그를 출력하고 즉시 중단합니다.
  - 스크롤 시도 시 중앙 영역 기준으로 **텍스트 노드 개수**와 **중앙 70% 영역 텍스트 목록**을 로그 출력합니다.
  - `scrollFind()` 루프는 각 시도 사이에 `0.8초` 대기합니다.
  - 찾으면 `True`, 타임아웃이면 `None`을 반환합니다.
- `scrollSelect(dev, name, wait_=60, direction_='updown', type_='a', index_=0, class_name=None, clickable=None, focusable=None)`
  - 시작 시 `[DEBUG][scrollSelect] 탐색 시작 (최대 {wait_}초 대기)` 로그를 출력하고 `scrollFind()`로 대상을 찾습니다.
  - `type_='all'`이 전달되면 내부에서 `safe_type='a'`로 정규화한 뒤 `scrollFind()`/`select(..., wait_=10)`에 전달합니다.
  - 탐색 성공 시 `time.sleep(1.5)`으로 화면 안정화를 기다린 뒤 `select(..., wait_=10)`를 호출합니다.
  - `scrollFind()` 실패 또는 `select()` 실패 원인을 각각 디버그 로그로 남기며, 실패 시 `False`를 반환합니다.
- `scrollTouch(dev, name, wait_=60, direction_='updown', type_='a', index_=0, long_=False, class_name=None, clickable=None, focusable=None)`
  - 시작 시 `[DEBUG][scrollTouch] 탐색 시작 (최대 {wait_}초 대기)` 로그를 출력하고 `scrollFind()`로 대상을 찾습니다.
  - `type_='all'`이 전달되면 내부에서 `safe_type='a'`로 정규화한 뒤 `scrollFind()`/`touch(..., wait_=10)`에 전달합니다.
  - 탐색 성공 시 `time.sleep(1.5)`으로 화면 안정화를 기다린 뒤 `touch(..., wait_=10)`를 호출합니다.
  - `scrollFind()` 실패 또는 `touch()` 실패 원인을 각각 디버그 로그로 남기며, 실패 시 `False`를 반환합니다.
- `typing(dev, name, adbTyping=False)`
  - 실행 시작 전 `check_helper_status(dev)`를 호출해 헬퍼 앱 접근성 서비스 활성 여부를 확인합니다.
  - 비활성 상태면 즉시 `False`를 반환하고 실제 입력/브로드캐스트는 수행하지 않습니다.
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
  - 로그 조회 시 `A11Y_HELPER:V A11Y_ANNOUNCEMENT:V *:S` 필터를 사용해 필요한 태그만 읽습니다.
  - 수집 결과는 반환값과 함께 `client.last_announcements`에도 항상 저장됩니다.
- `ping(dev=None, wait_=3.0) -> bool`
  - `PING` 브로드캐스트를 전송하고 `PING_RESULT` 로그의 `reqId/success/status`를 확인해 준비 상태(`READY`)를 반환합니다.
- `check_helper_status(dev=None) -> bool`
  - `adb shell settings get secure enabled_accessibility_services`에서 헬퍼 앱 패키지(`com.iotpart.sqe.talkbackhelper`) 포함 여부를 확인합니다.
  - 활성화되어 있어도 `ping()`으로 실제 명령 수신 가능 상태를 추가 검증합니다.
  - 비정상 상태면 빨간색 ANSI 강조로 안내 문구를 출력하고 `False`를 반환합니다.
- `check_talkback_status(dev=None) -> bool`
  - `adb shell settings get secure enabled_accessibility_services` 출력에 `com.google.android.marvin.talkback` 포함 여부만 확인합니다.
  - 포함되어 있으면 `True`, 아니거나 ADB 실패/단말 미연결 포함 예외 상황이면 `False`를 반환합니다.
- `touch/select/scroll/scrollFind/typing/isin/dump_tree`는 공통적으로 시작 시 `check_helper_status()`를 먼저 확인하며, 비활성 상태면 즉시 실패(`False` 또는 빈 리스트)를 반환합니다.
- `verify_speech(dev, expected_regex, wait_seconds=3.0, take_error_snapshot=True)`
  - `expected_regex`를 파일명에 안전한 문자열로 정규화한 뒤 임시 스냅샷(`temp_<safe_name>.png`)을 생성합니다.
  - `get_announcements()`로 발화를 수집한 뒤 마지막 문장에 대해 `re.search(expected_regex, actual_speech, re.IGNORECASE)`로 검증합니다.
  - 성공 시 임시 스냅샷을 삭제하고 `True`를 반환합니다.
  - 실패 시 `take_error_snapshot=True`인 경우 `error_log/fail_<sanitized_target>.png`에 EXPECTED/ACTUAL 오버레이 이미지를 저장하고 `False`를 반환합니다.
- 공통적으로 각 루프에서 `_refresh_tree_if_needed()`를 호출해 화면 변동(팝업 등)에 대응합니다.
- 내부 `_run(args, dev=None, timeout=30.0)`의 기본 타임아웃은 30초이며, `returncode != 0`일 때 예외 대신 에러 로그를 출력하고 빈 문자열을 반환합니다.

## 선(先) 스냅샷, 후(後) 검증 예제 (`main.py`)

- `main()`
  - 시작 시 `check_helper_status()`를 먼저 확인하고, 비활성 상태면 안내 문구 출력 후 `sys.exit(1)`로 안전 종료합니다.
  - 활성 상태에서 `scrollFind(..., direction_="down")`으로 대상을 찾습니다.
  - 발화 검증 전에 `client.select(dev_serial, target_name)`를 먼저 호출해 타겟 포커스를 맞춘 뒤, `client.verify_speech(dev_serial, expected_regex=target_name)` 결과로 PASS/FAIL을 판별합니다.
