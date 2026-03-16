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
- 덤프 직전 결과를 `boundsInScreen` 기준으로 상단→하단, 좌→우 순서로 정렬해 TalkBack 스와이프 순서와 유사한 탐색 순서를 만듭니다.
- `targetName`/`targetType`/`targetIndex` 기반 DFS 매칭 후, 추가 AND 필터(`className`/`clickable`/`focusable`/`targetText`/`targetId`)를 검증해 대상 노드를 찾고 액션(클릭/롱클릭/포커스)을 실행합니다.
- 매칭 노드가 클릭 불가능하면 클릭 가능한 첫 조상으로 보정하고, `clickable` 필터도 보정된 노드 기준으로 검사합니다.
- `targetName`은 공통 regex 패턴으로 정규화되어 `targetType=t|b|r` 모두 동일한 매칭 규칙을 사용합니다(명시적 regex 패턴이 없으면 exact regex로 처리). 매칭은 IGNORE_CASE 옵션으로 대소문자를 구분하지 않습니다.

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
