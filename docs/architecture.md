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
- 현재 접근성 포커스 노드에서 부모 방향으로 올라가며 `isScrollable=true` 노드를 찾고, 없으면 루트 트리를 BFS로 순회해 첫 번째 스크롤 가능 노드로 폴백합니다. BFS 결과도 없으면 `A11yNodeUtils.findBestScrollableContainer(...)`로 화면 영역이 가장 큰 스크롤 가능 노드를 선택해 방향(`down/up/right/left`)에 맞는 스크롤 액션(`ACTION_SCROLL_FORWARD/BACKWARD`)을 수행합니다.
- 현재 포커스 노드에 `ACTION_SET_TEXT`를 수행해 텍스트를 주입합니다.

#### A11yCommandReceiver

- ADB에서 전달된 `am broadcast` 명령을 수신합니다.
- 수신 보안을 위해 receiver 권한을 `android.permission.DUMP`로 제한하여 ADB shell/시스템 권한 송신자만 접근할 수 있습니다.
- 수신 액션(`GET_FOCUS`, `DUMP_TREE`, `FOCUS_TARGET`, `CLICK_TARGET`, `CHECK_TARGET`, `NEXT`, `PREV`, `SMART_NEXT`, `CLICK_FOCUSED`, `SCROLL`, `SET_TEXT`, `PING`)을 서비스 로직으로 전달합니다.
- `SMART_NEXT`는 `goAsync()` + 단일 스레드 executor에서 비동기 실행되어 BroadcastReceiver 메인 스레드를 점유하지 않고, 접근성 이벤트 루프가 focus verification polling window 동안 계속 이벤트를 처리할 수 있게 유지합니다.
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
- 내비게이터 알고리즘 버전은 `A11yNavigator.NAVIGATOR_ALGORITHM_VERSION`(현재 `2.67.0`)으로 관리합니다. 또한 노드 판별/검색 유틸리티는 `A11yNodeUtils`로 분리되고, 히스토리/억제 윈도우(Authoritative Commit 상태, suppression window 판정/시작/해제, post-commit stray focus 이벤트 무시 정책 포함)는 `A11yHistoryManager`로 통합 관리합니다. 포커스 실행/재시도/검증 파이프라인(`requestFocusFlow`, `resolveFocusRetargetDecision`, pre-focus 정렬/검증 유틸 포함)은 `A11yFocusExecutor`, Snapshot/Polling/Visible History 로직은 `A11ySnapshotTracker`, post-scroll 후보 선택 진입점은 `A11yTraversalAnalyzer`로 분리합니다. Smart Next의 정책/결정 로직(continuation 판정, bottom bar 진입/스크롤 결정, post-scroll continuation plan 계산)은 `A11yNavigationPolicy`로 분리되어 `A11yNavigator`는 coordinator 역할에 집중합니다.
- post-scroll 후보 분류는 상단 Y 좌표 단일 신호를 `persistent header` 근거로 사용하지 않고, non-scrolling chrome(TopAppBar 또는 non-content/non-interactive + visible-history + pre-scroll anchor 이전)일 때만 header로 고정 분류합니다.
- focus verification 단계에서는 attempt/post_action_settle 모두 동일한 판정 기준(실제 focused node + bounds + target bounds + target package)으로 match를 계산합니다. `com.android.systemui` 및 target app 외부 package focus 이벤트는 polling 중 transient 노이즈로 skip하며, attempt window에서 이미 성립한 성공은 settle mismatch만으로 실패로 뒤집지 않습니다(명백한 외부 package 이탈은 별도 실패 신호로 처리).
- 첫 상단(top-chrome→top-chrome) 이동에서는 pre-commit 짧은 구간(300ms)에 한해 `com.android.systemui` 이벤트를 추가로 transient 노이즈로 억제하며, active app focus가 target package에 남아 있을 때만 적용됩니다(실제 외부 이탈은 억제하지 않음).
- post-scroll continuation 후보 평가는 `rewound_before_anchor`를 기본 차단으로 유지하지만, top chrome/persistent header가 아닌 content 후보가 descendant label 복구 및 successor 가능성(`logical_successor`/continuation fallback)을 만족하면 `accepted:continuation_candidate_despite_rewound_before_anchor`로 예외 수용합니다.
- `final_focus_commit` 직후 suppression window에서는 committed 후보와 다른 identity/bounds로 들어오는 stray 포커스/announcement 이벤트를 `final_focus_ignored_event reason=already_committed`로 무시하며, visited/snapshot/status를 덮어쓰지 않습니다.
- 같은 Smart Next 턴에서 `final_focus_commit`가 발생하면 finalize 단계에서 `status_locked_by_final_commit` 로그를 남기고 성공 상태를 잠가 stale 후속 이벤트가 success를 failure로 뒤집지 못하게 유지합니다.
- `SMART_NEXT` 스크롤 폴링은 기존 스냅샷 비교 구조를 유지하되, 트리 변경 감지 시 300ms 안착 대기 후 최신 루트를 다시 읽는 3단계(변화 감지 → 추가 대기 → 최종 확인)로 보강되어 리스트 재구성 도중 중간 아이템 누락을 줄입니다.
- 스냅샷 비교는 상단 앱바/하단 내비게이션 바로 판정되는 노드를 제외한 컨텐츠 토큰을 우선 사용하여 상태바/고정 바의 미세 갱신으로 스크롤 완료 판정이 앞당겨지는 현상을 완화합니다.
- Bottom Bar 직전 pre-scroll은 `shouldScrollBeforeBottomBar(...)`가 현재 포커스 위치/남은 본문 후보/top chip·filter loop 위험을 함께 평가해 “숨은 본문이 더 있을 가능성”이 높을 때만 수행합니다.
- Bottom Bar가 다음 후보일 때는 hidden-content likelihood 단일 신호에 의존하지 않고, 현재 노드의 near-bottom 여부 + row/grid 반복 패턴 + bottom bar 직전 trailing content(0~80px band)를 함께 재검증합니다. continuation 신호가 하나라도 감지되면 bottom bar 진입을 defer하고 pre-scroll을 강제합니다.
- scroll 이후 후보 탐색은 pre-scroll anchor exact match를 먼저 시도하고, 실패하면 `A11yTraversalAnalyzer.selectPostScrollCandidate(...)` 기반 continuation fallback을 사용합니다. 이때 우선순위는 `(1) pre-scroll focused anchor의 logical successor > (2) scroll 후 신규 미방문 interactive(clickable/focusable, non-bottom-nav) 후보 > (3) scroll 후 상단 신규(미방문) content continuation 후보 > (4) pre-scroll anchor 하단의 trailing continuation 후보 > (5) raw tree에는 있으나 traversal에서 누락됐던 설정 row(viewId 승격 대상) > (6) scroll 후 하단 신규 노출 본문 > (7) 기타 unvisited visible 후보` 순이며, 상단 resurfaced 브랜딩/anchor 계열은 제외(또는 최하위)합니다. `rewound before pre-scroll anchor` 또는 `header resurfaced before anchor` 신호가 true면 `newly revealed` 우선순위보다 먼저 탈락 처리합니다. continuation fallback이 실패하더라도 유효 후보가 관찰된 케이스는 일반 스캔을 차단하지 않고, 유효 후보가 전혀 없을 때만 `skipGeneral decision reason=continuation_fallback_failed_no_valid_candidate`와 함께 일반 탐색 재진입을 생략합니다. 또한 continuation context의 top `<no-label>` 후보는 즉시 노이즈 스킵하지 않고 descendant 라벨 복구/히스토리 재검사를 먼저 수행합니다.
- traversal builder는 설정 row ID(`item_history`, `item_notification`, `item_customer_service`, `item_repair_history`, `item_how_to_use`, `item_notices`, `item_contact_us`, `item_offline_diag`, `item_knox_matrix`, `item_privacy_notice`)를 클릭 가능 여부와 무관하게 focus container로 간주해 후보에서 누락되지 않게 유지합니다. row label이 비어 있으면 descendant readable text를 머지해 post-scroll 후보 로그 및 continuation 필터 입력 라벨로 사용합니다.
- traversal builder는 `clickable && focusable` 이면서 순수 action control이 아닌 대형 composite container(복수 interactive/labeled descendant 보유)를 empty shell/컨테이너 제거 규칙에서 예외 처리해 parent card와 child control을 동시에 후보로 유지합니다.
- Bottom Bar pre-scroll 직후 새 traversal 스냅샷이 이전과 같을 때는 추가 Bottom Bar fallback/인덱스 동기화 연쇄를 수행하지 않고 즉시 실패 종료(`reached_end_no_scroll_progress`)해 단일 호출 내 sweep loop를 차단합니다.
- stale index 보정은 `currentIndex < lastRequestedFocusIndex`라도 `currentIndex + 1` 중간 후보가 실제 리스트에 있으면 먼저 소진하도록 완화되어, `lastRequestedFocusIndex + 1` 점프가 본문 마지막 후보를 건너뛰지 않게 했습니다.
- 다음 후보가 Bottom Bar로 판정되더라도 `findIntermediateContentCandidateBeforeBottomBar(...)`가 중간 본문(특히 Bottom Bar top 경계 0~80px 위에서 끝나는 얇은 trailing content)을 먼저 반환하면 해당 후보를 우선 포커스합니다.
- 스크롤 후 후보가 모두 히스토리 또는 skip 규칙으로 제거되어 실제 포커스 시도 대상이 0개면 `looped` 재탐색 대신 즉시 `reached_end`를 반환합니다.
- 포커스 성공 후 `lastRequestedFocusIndex`를 보정할 때는 좌표 일치만으로 히스토리를 전진시키지 않고, 현재 접근성 포커스 노드의 객체 ID가 traversal 후보와 직접 일치할 때만 엄격하게 반영합니다.
- 이 공통 보정 루틴은 일반 콘텐츠에만 `ACTION_SHOW_ON_SCREEN`을 허용하며, `isTopAppBarNode`/`isBottomNavigationBarNode`로 분류된 고정 상단바·하단바에서는 보정 액션과 관련 로그를 모두 차단해 시스템 Bounce를 방지합니다.
- SmartThings 하단 탭 리소스(`menu_services`, `menu_automations`, `menu_more` 포함)는 `isBottomNavigationBarNode`에서 bottom navigation으로 강제 분류되며, 해당 타겟은 `Detected bottom navigation target -> skipping pre-focus alignment` 로그와 함께 pre-focus alignment/readable scroll을 건너뛰고 직접 포커스만 수행합니다.
- `findMainScrollContainer`는 화면에서 면적이 가장 큰 `isScrollable=true` 노드를 메인 스크롤 컨테이너로 선택하고, `SMART_NEXT`는 이를 기준으로 스크롤 대상과 컨텐츠/고정 UI 경계를 해석합니다.
- `isFixedSystemUI`는 노드 또는 조상에 `Toolbar`/`ActionBar`/`BottomNavigationView` 계열 키워드가 있으면 우선 `Fixed UI`로 분류합니다. 그 외에는 `Button`/`ImageButton` 클래스만 엄격한 고정 UI 후보로 보며, `ViewGroup`/`FrameLayout` 등 일반 콘텐츠 컨테이너는 메인 스크롤 영역 근처 콘텐츠로 취급합니다.
- 스크롤 후 히스토리 필터는 `inHistory=true`인 후보를 기본적으로 모두 스킵하며, 스크롤 직후 1차 탐색에서는 메인 스크롤 내부의 상단 후보도 예외 없이 건너뛰고 새 컨텐츠를 끝까지 우선 탐색합니다. 메인 스크롤 컨테이너 구분은 유지하되, 상단 물리 위치 증거는 `!isFixedUi` 후보에만 재포커스 허용 근거로 사용합니다. 이때 대상 노드가 이미 시스템 접근성 포커스를 보유하면 추가 `ACTION_ACCESSIBILITY_FOCUS`를 생략해 중복 공지를 줄입니다.
- 스크롤 대기 구간은 스크롤 직후 반드시 200ms를 먼저 대기한 뒤, 최대 10회(150ms 간격) 동안 새 `rootInActiveWindow`의 전체 노드 텍스트/설명/리소스 ID 스냅샷 문자열을 이전 화면 스냅샷과 비교해 트리 갱신을 감지합니다. 10회 모두 실패하면 마지막으로 500ms를 한 번 더 대기한 최신 루트로 재탐색하며, 추가 포커스 강제 해제는 사용하지 않습니다.
- 리스트 끝에서 다음 후보가 하단 탭이면 `findAndFocusFirstContent(..., allowLooping = false)`로 새 콘텐츠 유무를 확인합니다. 단, continuation fallback 후보를 찾고도 확정하지 못한 케이스는 하단탭 fallback을 차단하고 `failed`로 종료해 오탐색 성공(`status=moved`, `detail=moved_to_bottom_bar`)을 방지합니다.
- 같은 하단 탭 진입 시나리오에서 `ACTION_SCROLL_FORWARD` 자체가 `false`이면 더 이상 스크롤하지 않고 즉시 하단 탭 direct 경로를 시도하며, 최종 응답은 `status=moved`와 `detail=moved_to_bottom_bar_direct`로 기록합니다.
- 공통 포커스 루틴은 이미 시스템 접근성 포커스가 있는 노드에 대한 중복 포커스 가드를 유지하며, `ACTION_SHOW_ON_SCREEN`이 실제 성공한 경우에만 조정 상태를 true로 인정합니다. 이때 추가 컨테이너 스크롤은 생략해 이중 스크롤 충돌을 막고, 보정 후 400ms 대기 + `target.refresh()`로 최신 bounds를 읽은 뒤 포커스를 시도합니다. 실제 `ACTION_ACCESSIBILITY_FOCUS`는 동일 `performSmartNext` 호출 안에서 타겟당 최대 3회(시도 간 100ms)까지 재시도하고, 직전 `target.refresh()`로 최신 상태를 읽은 뒤 성공 직후 추가 150ms를 대기해 포커스 표시 안착을 보조합니다. 반환값이 `false`여도 직후 `accessibilityFocused=true`면 성공으로 판정합니다.
- `performSmartNext`는 새 타겟으로 이동하기 직전에 현재 `findFocus(FOCUS_ACCESSIBILITY)` 노드가 있으면 `ACTION_CLEAR_ACCESSIBILITY_FOCUS`를 먼저 보내 포커스 락을 끊고, 이후 `val service: android.accessibilityservice.AccessibilityService? = A11yHelperService.instance`로 타입을 확정한 뒤 `(service as A11yHelperService).sendAccessibilityEvent(TYPE_VIEW_ACCESSIBILITY_FOCUS_CLEARED)`를 호출해 접근성 포커스 캐시를 안전하게 갱신합니다.
- `performSmartNext` 시작 시 순회 노드 로그는 기존 Top 단일 좌표 대신 `(L, T, R, B)` 전체 bounds와 `buildTalkBackLikeFocusNodes`가 만든 `Merged Label`을 함께 기록해, 무라벨 컨테이너가 TalkBack에서 읽는 병합 텍스트를 추적합니다.
- `performSmartNext`는 현재 포커스 인덱스를 찾을 때 마지막 노드와의 동일성 검사를 먼저 수행해, 중간 후보가 먼저 매칭되더라도 현재 포커스가 실제 마지막 항목이면 마지막 인덱스를 우선 반환합니다. 이후에도 매칭에 실패하면 `A11yTraversalAnalyzer.findNodeIndexByIdentity(...)`로 좌표 우선 재탐색을 수행하며, `BoundsInScreen`이 완전히 같은 후보를 찾으면 ID/텍스트/설명이 달라도 `[SMART_NEXT] Matched node by coordinates at index X` 로그와 함께 성공 처리합니다.
- 리스트 마지막/다음 인덱스 미존재 상황에서는 기본적으로 `reached_end`를 반환하며, 스크롤 가능한 컨테이너 존재만으로 end-of-traversal scroll-first를 수행하지 않습니다.
- 마지막 노드 그레이스 처리로, 보정 후 `nextIndex`가 범위를 벗어나더라도 `currentIndex < lastIndex`이면 마지막 후보에 대한 포커스를 한 번 더 시도합니다. 반대로 `currentIndex == lastIndex`인 진짜 종료 시점에는 `[SMART_NEXT] Ensuring last node focus visibility before termination` 로그를 남기고 마지막 노드에 `ACTION_ACCESSIBILITY_FOCUS`를 한 번 더 보낸 뒤 `reached_end`를 반환합니다.
- `requestFocusFlow(...)`는 실제 포커스가 타겟으로 이동한 경우에만 성공 status를 반환하며, snap-back은 강제 성공으로 승격하지 않고 실패(`snap_back`)로 반환합니다.
- `SMART_NAV_RESULT.status`는 top-level 4종(`moved/scrolled/looped/failed`)으로 고정하고, 세부 분기(`moved_to_bottom_bar_direct`, `moved_aligned` 등)는 `detail`/`flags`로 전달합니다.
- `requestFocusFlow(...)`는 현재 포커스 바로 아래의 **첫 번째** partially visible 다음 후보를 intended candidate로 고정해(`[SMART_NEXT] Detected partially visible next candidate`) 후보 점프를 막고, pre-focus 보정은 `best effort minimal adjustment` 원칙으로 제한합니다. 즉 partially visible intended/후행 후보가 감지되면 컨테이너 강제 스크롤을 생략하고 `ACTION_SHOW_ON_SCREEN` 중심의 최소 보정만 수행하며, intended candidate가 fully visible이 되는 즉시 추가 보정을 중단합니다. 보정 결과 intended가 화면 상단 밖으로 밀리거나, 후행 카드의 가시 영역이 intended를 넘어 주 객체가 되면 overshoot로 기록(`[SMART_NEXT] Overshoot detected...`)하고 즉시 best-effort focus로 전환합니다.
- 포커스 성공 직후에는 `stabilizeVisualFocusAfterMove(...)` 단계가 추가되어 100~250ms 구간에서 intended target의 `accessibilityFocused` 유지와 bounds 일치를 재검증합니다. 이때 `com.android.systemui` 포커스 업데이트는 transient 노이즈로 무시하며(`[SMART_NEXT] Ignoring transient system UI focus during stabilization`), 필요 시 `ACTION_SHOW_ON_SCREEN + ACTION_FOCUS + ACTION_ACCESSIBILITY_FOCUS`를 최대 1회만 보수적으로 재시도합니다.
- 중복 포커스 재사용은 `isAccessibilityFocused` 플래그만 보지 않고 실제 시스템 포커스 노드와 타겟 노드의 `BoundsInScreen`이 완전히 일치할 때만 허용합니다. 1px이라도 다르면 별도 노드로 보고 `ACTION_ACCESSIBILITY_FOCUS`를 강제합니다.
- `performSmartNext`는 현재 인덱스를 찾은 직후 `A11yStateStore.lastRequestedFocusIndex`와 동기화하고, 바로 다음 노드의 `BoundsInScreen`이 현재와 완전히 같을 때만 유령 노드로 간주해 `currentIndex + 1`로 보정합니다. 이때 `[SMART_NEXT] Skipping invisible duplicate at index X` 로그를 남기며, 1px이라도 좌표가 다르면 동일 행/인접 카드라도 별도 후보로 유지합니다.
- `findAndFocusFirstContent(...)`는 루프 최상단에서 현재 시스템 포커스와 좌표가 완전히 같은 후보를 어떤 조건보다 먼저 skip하며, 특히 일반 이동(`isScrollAction=false`)에서는 동일 좌표 후보를 검증 없이 더 엄격하게 건너뜁니다.
- 같은 행(Y 좌표 동일)의 후보를 포커스할 때는 명령 직전 100ms 지연을 넣어 TalkBack의 물리적 이동 시간을 확보합니다.
- `requestFocusFlow(...)`는 포커스 요청 직전 `ACTION_CLEAR_ACCESSIBILITY_FOCUS`와 `TYPE_VIEW_ACCESSIBILITY_FOCUS_CLEARED`를 함께 보내 캐시를 비우고, `ACTION_FOCUS`를 먼저 시도한 뒤 접근성 포커스를 요청합니다. visual stabilization 또는 재시도 단계에서 mismatch가 발생해도 grace window가 끝날 때까지 롤백을 지연하며(`[SMART_NEXT] Delaying rollback due to pending stabilization`), grace window 내 포커스 복구 시 성공으로 유지합니다. grace window 이후에도 미복구인 경우에만 실제 시스템 `findFocus(FOCUS_ACCESSIBILITY)` 기준으로 `lastRequestedFocusIndex`를 재동기화합니다.
- 같은 루틴 안에서 `ACTION_ACCESSIBILITY_FOCUS` 직전/직후 시스템 `findFocus`의 전체 좌표와 타겟 좌표를 `Before Focus`/`After Focus` 로그로 함께 남겨, 시스템 포커스가 실제로 어느 bounds에 머무는지 비교할 수 있습니다. 액션 반환값이 `false`여도 실제 시스템 포커스 bounds가 타겟과 오차 허용 범위 내에서 일치하고 타겟이 `isAccessibilityFocused=true`이면 성공으로 승격합니다. 반대로 snap-back(허용 오차 밖)인 경우는 성공 강제 없이 실패로 반환합니다.
- snap-back 처리 직전에는 100ms 대기를 넣어 TalkBack이 해당 노드 텍스트를 읽을 최소 시간을 확보하며, 같은 `performSmartNext` 호출 안에서 동일 타겟에 대한 `ACTION_ACCESSIBILITY_FOCUS`는 최대 3회까지 재시도합니다.
- 라벨이 `<no-label>`인 타겟은 스크롤 직후 TalkBack 자동 선점 포커스라도 재사용하지 않고 항상 강제 포커스하여 연속 무라벨 구간의 제자리걸음을 줄입니다.
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



## Current Stable Baseline and Deferred Trailing-Control Work

### 1. 현재 안정 기준 (Stable Baseline)

PR #265 (commit `b603552`) 기준으로 현재 traversal 엔진은 **안정 상태**로 판단한다.

- 변경 내용: Settings 화면에서 composite card(예: "Update app")가 누락되던 문제 수정
- 결과: "Update app"과 같은 큰 parent card가 정상적으로 수집 및 읽힘
- 이 버전을 **자동화 및 검증의 기준 baseline**으로 사용한다

현재 시점의 `move_smart`는 다음을 안정적으로 제공한다:
- 순차 포커스 이동 안정성
- row / card / title 단위 읽기 정확성
- loop 및 순서 붕괴 없이 예측 가능한 traversal

---

### 2. move_smart의 현재 사용 목적

현재 baseline에서 `move_smart`의 역할은 다음과 같다:

- Settings row, 카드, 제목 등의 **row-level 읽기**
- 화면 내 요소의 **순차 이동**
- TalkBack 결과를 **row/content 단위로 수집 및 검증**

보장하지 않는 것:

- row 내부 trailing control (on/off switch 등)의 별도 포커스 분리
- composite UI 내부의 세부 control까지 포함한 정밀 traversal

---

### 3. 알려진 제한 사항 (Multiline Row Trailing Control)

현재 multiline row에서 다음 문제가 존재한다:

예시:
- "Shared location information notifications"
- 해당 row의 trailing switch(on/off)가 별도 포커스로 분리되지 않음

원래 목표:
- row → trailing switch → 다음 row 순서로 traversal

현재 상태:
- trailing switch는 항상 별도 stop으로 보장되지 않음

---

### 4. 시도했던 접근과 실패 원인 (설계 수준)

다음과 같은 접근을 시도했으나 실제 디바이스 기준으로 모두 문제 발생:

- collect 단계에서 trailing control 강제 포함
- alias / wrapper 병합 로직 수정
- normalize 이후 logical stop 삽입
- decision 단계 row-local follow-up 추가

발생한 문제:
- row-first 순서 붕괴
- 무한 루프 또는 반복 포커스
- alias representative 충돌 (row vs switch)
- 전체 traversal 안정성 저하 (상단 포커스 포함)

결론:
이 접근들은 현재 엔진의 핵심 불변식과 충돌한다:

- single-step 실행 (한 번에 하나의 target)
- no-later-sweep 정책
- alias representative 모델
- visited / final commit 상태 관리

---

### 5. 현재 설계 판단 (중요)

위 문제를 기반으로 다음과 같이 결정한다:

- `move_smart` 본체는 **수정하지 않는다**
- trailing control 문제는 **의도적으로 보류한다**
- 다음 영역은 더 이상 patch하지 않는다:
  - collect
  - alias
  - normalize
  - decision 로직

향후 방향 (미구현):
- 별도 명령 기반 접근
- 또는 traversal 엔진 구조 재설계

---

### 6. Codex 작업 시 주의사항 (IMPORTANT)

Traversal 로직 수정 시 반드시 지켜야 한다:

하지 말 것:
- `move_smart` 내부에서 trailing control 해결 시도
- collect 단계에서 후보 강제 추가
- alias representative 로직 수정
- normalize 단계에서 stop 삽입
- decision 단계 follow-up 로직 추가

해야 할 것:
- 현재 baseline 안정성을 최우선으로 유지
- 코드 수정 전에 반드시 설계 검토
- row 내부 control은 별도 경로로 접근

---

### 7. 현재 사용 가이드 (Practical Usage)

현재 자동화/검증에서 사용 범위:

사용 가능:
- row / title / card 읽기
- 순차 traversal 검증

사용하지 않는 것:
- trailing switch 자동 접근
- row 내부 control 포함 전체 traversal

이 제한은 현재 **안정성 유지 목적상 의도적으로 허용된 상태**이다.
