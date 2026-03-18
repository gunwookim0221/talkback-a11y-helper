# Architecture

[System Overview 보기](system-overview.md) | [Testing Pipeline 보기](testing-pipeline.md)

## Overview

`talkback-a11y-helper`는 **Android `AccessibilityService` 기반의 헬퍼 앱**으로, Python/ADB 자동화에서 화면 전체 노드를 구조화해 읽고 특정 UI를 직접 제어하기 위한 중간 계층입니다.

## Architecture Diagram

```text
AccessibilityService
    -> Tree Dumper / Target Action Engine
    -> State Store
    -> Broadcast Interface
```

### Component Responsibilities

#### A11yHelperService

- Android 접근성 이벤트를 구독합니다.
- 현재 접근성 포커스 노드를 추적합니다.
- `TYPE_ANNOUNCEMENT` 이벤트를 감지해 `A11Y_ANNOUNCEMENT` 로그를 남깁니다.
- `TYPE_WINDOW_STATE_CHANGED` 이벤트를 감지해 `SCREEN_CHANGED` 로그를 남깁니다.
- 루트 노드를 순회해 Flat JSON 배열로 트리를 덤프합니다.
- `targetName`/`targetType`/`targetIndex` 기준 DFS 매칭과, 선택적 `className`/`clickable`/`focusable`/`targetText`/`targetId` AND 필터를 함께 적용해 `ACTION_ACCESSIBILITY_FOCUS`/`ACTION_CLICK`/`ACTION_LONG_CLICK`을 수행합니다.
- 매칭 노드가 클릭 불가능하면 첫 번째 클릭 가능한 조상으로 타겟을 보정하는 Parent Resolution을 적용합니다.
- 현재 접근성 포커스 노드에서 부모 방향으로 올라가며 `isScrollable=true` 노드를 찾고, 없으면 루트 트리를 BFS로 순회해 첫 번째 스크롤 가능 노드로 폴백합니다. BFS 결과도 없으면 화면 영역이 가장 큰 스크롤 가능 노드를 찾아 방향(`down/up/right/left`)에 맞는 스크롤 액션(`ACTION_SCROLL_FORWARD/BACKWARD`)을 수행합니다.
- 현재 포커스 노드에 `ACTION_SET_TEXT`를 수행해 텍스트를 주입합니다.

#### A11yCommandReceiver

- ADB에서 전달된 `am broadcast` 명령을 수신합니다.
- 수신 보안을 위해 receiver 권한을 `android.permission.DUMP`로 제한하여 ADB shell/시스템 권한 송신자만 접근할 수 있습니다.
- 수신 액션(`GET_FOCUS`, `DUMP_TREE`, `FOCUS_TARGET`, `CLICK_TARGET`, `CHECK_TARGET`, `NEXT`, `PREV`, `CLICK_FOCUSED`, `SCROLL`, `SET_TEXT`, `PING`)을 서비스 로직으로 전달합니다.
- `PING` 수신 시 `PING_RESULT {"reqId":...,"success":true,"status":"READY"}` 로그를 반환해 준비 상태를 확인합니다.
- 서비스 인스턴스가 null이면 요청의 `reqId`를 포함한 실패 JSON(`{"reqId":...,"success":false,"reason":"Accessibility Service is null or not running"}`)을 각 결과 태그(`TARGET_ACTION_RESULT`, `SCROLL_RESULT` 등)로 출력합니다.

#### A11yNavigator

- 접근성 노드 트리에서 TalkBack 유사 규칙으로 포커스 가능한 컨테이너를 식별합니다(`clickable` 또는 `screenReaderFocusable`).
- 컨테이너 노드는 하위 가시 노드의 텍스트/콘텐츠 설명을 병합해 단일 JSON 노드로 직렬화합니다(단, 독립 `clickable` 하위 노드는 별도 포커스로 유지).
- 최종 포커스 리스트에서 병합 결과 `text`와 `contentDescription`이 모두 blank인 `clickable=true` 노드는 의미 없는 껍데기 버튼으로 간주해 제거합니다.
- 덤프 직전 결과를 `boundsInScreen` 기준으로 상단→하단, 좌→우 순서로 정렬하되, 포함 관계(부모-자식)가 성립하면 좌표값과 무관하게 부모 노드를 자식보다 먼저 배치합니다.
- `targetName`/`targetType`/`targetIndex` 기반 DFS 매칭 후, 추가 AND 필터(`className`/`clickable`/`focusable`/`targetText`/`targetId`)를 검증해 대상 노드를 찾고 액션(클릭/롱클릭/포커스)을 실행합니다.
- 매칭 노드가 클릭 불가능하면 클릭 가능한 첫 조상으로 보정하고, `clickable` 필터도 보정된 노드 기준으로 검사합니다.
- `targetName`은 공통 regex 패턴으로 정규화되어 `targetType=t|b|r` 모두 동일한 매칭 규칙을 사용합니다(명시적 regex 패턴이 없으면 exact regex로 처리). 매칭은 IGNORE_CASE 옵션으로 대소문자를 구분하지 않습니다.
- 내비게이터 알고리즘 버전은 `A11yNavigator.NAVIGATOR_ALGORITHM_VERSION`(현재 `2.9.6`)으로 관리하며, `moved/scrolled/looped` 포커스는 공통 가시성-포커스 루틴을 통해 하단 가림(`effectiveBottom-300`) 및 스크롤 직후 상단 정렬(`screenTop+300`) 보정을 수행합니다.
- `SMART_NEXT` 스크롤 폴링은 기존 스냅샷 비교 구조를 유지하되, 트리 변경 감지 시 300ms 안착 대기 후 최신 루트를 다시 읽는 3단계(변화 감지 → 추가 대기 → 최종 확인)로 보강되어 리스트 재구성 도중 중간 아이템 누락을 줄입니다.
- 스냅샷 비교는 상단 앱바/하단 내비게이션 바로 판정되는 노드를 제외한 컨텐츠 토큰을 우선 사용하여 상태바/고정 바의 미세 갱신으로 스크롤 완료 판정이 앞당겨지는 현상을 완화합니다.
- 이 공통 보정 루틴은 일반 콘텐츠에만 `ACTION_SHOW_ON_SCREEN`을 허용하며, `isTopAppBarNode`/`isBottomNavigationBarNode`로 분류된 고정 상단바·하단바에서는 보정 액션과 관련 로그를 모두 차단해 시스템 Bounce를 방지합니다.
- `findMainScrollContainer`는 화면에서 면적이 가장 큰 `isScrollable=true` 노드를 메인 스크롤 컨테이너로 선택하고, `SMART_NEXT`는 이를 기준으로 스크롤 대상과 컨텐츠/고정 UI 경계를 해석합니다.
- `isFixedSystemUI`는 노드 또는 조상에 `Toolbar`/`ActionBar`/`BottomNavigationView` 계열 키워드가 있으면 우선 `Fixed UI`로 분류합니다. 그 외에는 `Button`/`ImageButton` 클래스만 엄격한 고정 UI 후보로 보며, `ViewGroup`/`FrameLayout` 등 일반 콘텐츠 컨테이너는 메인 스크롤 영역 근처 콘텐츠로 취급합니다.
- 스크롤 후 히스토리 필터는 이미 본 `Fixed UI`를 상단 위치와 무관하게 우선 스킵하고, 고정되지 않은 컨텐츠에만 화면 상단 25% 예외를 적용합니다. 메인 스크롤 컨테이너 구분은 유지하되, 상단 물리 위치 증거는 `!isFixedUi` 후보에만 재포커스 허용 근거로 사용합니다. 이때 대상 노드가 이미 시스템 접근성 포커스를 보유하면 추가 `ACTION_ACCESSIBILITY_FOCUS`를 생략해 중복 공지를 줄입니다.
- 스크롤 대기 구간은 스크롤 직후 반드시 200ms를 먼저 대기한 뒤, 최대 10회(150ms 간격) 동안 새 `rootInActiveWindow`의 전체 노드 텍스트/설명/리소스 ID 스냅샷 문자열을 이전 화면 스냅샷과 비교해 트리 갱신을 감지합니다. 10회 모두 실패하면 마지막으로 500ms를 한 번 더 대기한 최신 루트로 재탐색하며, 추가 포커스 강제 해제는 사용하지 않습니다.
- 리스트 끝에서 다음 후보가 하단 탭이면 `findAndFocusFirstContent(..., allowLooping = false)`로 새 콘텐츠 유무를 확인한 뒤, 없을 때는 `moved_to_bottom_bar`로 하단 탭 포커스를 반환합니다.
- 같은 하단 탭 진입 시나리오에서 `ACTION_SCROLL_FORWARD` 자체가 `false`이면 더 이상 스크롤하지 않고 즉시 `moved_to_bottom_bar_direct` 경로로 하단 탭 포커스를 시도합니다.
- 공통 포커스 루틴은 이미 시스템 접근성 포커스가 있는 노드에 대한 중복 포커스 가드를 유지하며, 실제 `ACTION_ACCESSIBILITY_FOCUS` 성공 직후 100ms를 대기해 시스템의 `accessibilityFocused` 상태 반영 시간을 보장합니다.
- 하단 네비게이션 경계 계산 시 화면 하단 5% 이내 값이 감지되면 사용자 체감 하단바를 반영해 `screenBottom * 0.85` 가이드를 적용합니다.

#### A11yStateStore

- 현재 포커스 노드 정보를 JSON 형태로 저장합니다.
- 자동화 스크립트가 읽기 쉬운 구조로 상태를 직렬화합니다.

## Accessibility Events Used

- `TYPE_VIEW_ACCESSIBILITY_FOCUSED`
- `TYPE_VIEW_FOCUSED`
- `TYPE_WINDOW_STATE_CHANGED`
- `TYPE_ANNOUNCEMENT`

## Output Channels

- `logcat` 출력
- JSON 파일 저장
- broadcast 응답
