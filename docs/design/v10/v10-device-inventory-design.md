# V10 Device Inventory Design

| Metadata | Value |
| --- | --- |
| Status | Completed |
| Phase | V10 Phase 1 |
| Owner | TalkBack Automation |
| Last Updated | 2026-06-30 |
| Depends On | [V10 Overview](v10-overview.md), [V10 Phase Plan](v10-phase-plan.md) |
| Related Documents | [V10 Overview](v10-overview.md), [V10 Phase Plan](v10-phase-plan.md), [V10 Quick Plugin Identify Design](v10-quick-plugin-identify-design.md) |
| Next | [V10 Quick Plugin Identify Design](v10-quick-plugin-identify-design.md) |

## 1. Background

현재 Device plugin 진입은 아래 흐름을 사용한다.

```text
scenario_config.target_stable_labels
-> find_device_card_by_stable_label()
-> stable display name exact match
-> selected scenario traversal
```

현재 Discover Plugins의 Device discovery는 helper dump에서 device card node를 찾고,
visible card를 정렬하여 discovery response로 반환한다. 주요 결과는 `label`,
`stable_label`, `bounds`, `resource_id`, `confidence`, `source`, `known`,
`existing_scenario_id`다.

이 구조는 현재 viewport의 card를 관찰하는 용도로는 유효하지만 runtime inventory로
사용하기에는 다음 한계가 있다.

- `current_view_only`이며 offscreen card를 수집하지 않는다.
- 동일한 `stable_label`은 하나의 card로 dedupe된다.
- `known`과 `existing_scenario_id`는 독립적인 plugin identification 결과가 아니라
  display name과 scenario config의 매칭 결과다.
- discovery `id`에 label과 enumeration index가 포함되어 있어 이름 변경이나 수집
  순서 변경에 영향을 받는다.
- room, section, scroll position, capture provenance가 inventory item에 포함되지 않는다.
- `confidence`는 card discovery 신뢰도이며 plugin type 식별 신뢰도가 아니다.

따라서 Phase 1은 display name을 제거하는 단계가 아니라, display name을 identity가
아닌 evidence 중 하나로 낮추는 runtime inventory 계층을 설계하는 단계다.

## 2. Inventory Goal

선택된 Devices 화면과 location 범위에서 bounded scrolling으로 접근 가능한 모든
Device Card를 하나의 runtime inventory로 수집한다.

Inventory의 책임은 다음과 같다.

- card의 존재와 runtime locator evidence를 보존한다.
- 같은 display name을 가진 card를 서로 다른 item으로 보존한다.
- Quick Identify가 특정 card를 다시 찾고 열 수 있는 충분한 문맥을 제공한다.
- card의 plugin family나 scenario를 Phase 1에서 확정하지 않는다.
- 현재 viewport만 수집된 경우 scope가 partial임을 명시한다.

여기서 "모든 Device Card"는 현재 선택된 account, location, Devices tab, filter와
수집 시점에 UI에서 접근 가능한 범위를 의미한다. 다른 location, account 또는
앱에 로드되지 않은 card까지 전역 inventory로 간주하지 않는다.

## 3. Inventory Model

### 3.1 Inventory Envelope

Inventory 전체에는 item 외에도 수집 범위와 신뢰성을 설명하는 envelope가 필요하다.

| Field | Required | Description |
| --- | --- | --- |
| `inventory_id` | Yes | 한 번의 inventory 실행을 식별하는 runtime ID |
| `schema_version` | Yes | inventory artifact schema version |
| `captured_at` | Yes | 수집 시작 시각 |
| `completed_at` | Yes | 수집 종료 시각 |
| `device_serial` | Yes | 실행 단말 식별자 |
| `account_context` | No | 노출 가능한 범위의 account context 또는 익명화된 key |
| `location` | No | 수집 시 선택된 SmartThings location |
| `filter` | No | All devices, room filter 등 현재 filter |
| `scope` | Yes | `viewport`, `bounded_scroll`, `partial` 중 하나 |
| `termination_reason` | Yes | end-of-list, repeated viewport, max scroll, error 등 |
| `screen_count` | Yes | 관찰한 distinct viewport 수 |
| `item_count` | Yes | 중복 병합 후 inventory item 수 |
| `warnings` | Yes | dump 실패, 불완전 수집, ambiguous dedupe 등 diagnostics |

`account_context`는 display name routing에 사용하지 않는다. 재현성과 artifact 구분을
위한 context이며, 개인정보 노출을 피할 수 있도록 raw account text보다 익명화된
식별자를 우선한다.

### 3.2 Inventory Item

| Field | Required | Description |
| --- | --- | --- |
| `runtime_card_id` | Yes | 해당 `inventory_id` 안에서만 유효한 unique ID |
| `stable_label` | Yes | 상태 suffix와 반복 text를 제거한 기존 normalized label |
| `display_label` | Yes | helper dump에서 관찰한 원본 사용자 표시 이름 |
| `resource_id` | No | card container resource-id |
| `class_name` | No | card container class |
| `bounds` | No | 최초 관찰 viewport의 card bounds |
| `entry_target` | Yes | bounds/resource-id/label을 포함한 재탐색용 locator evidence |
| `room` | No | card가 속한 room context, 확정할 수 없으면 empty |
| `section` | No | 화면 section 또는 group heading |
| `screen_index` | Yes | 최초 관찰한 viewport의 zero-based scan index |
| `observed_screen_indexes` | Yes | card가 관찰된 모든 viewport index |
| `visibility` | Yes | `fully_visible`, `partially_visible`, `offscreen_after_scan` |
| `source` | Yes | `helper`, `xml`, `combined` 등 evidence source |
| `discovery_confidence` | Yes | card candidate 판정 신뢰도 |
| `identity_confidence` | Yes | 동일 runtime card 병합 판단의 신뢰도 |
| `actionable` | Yes | clickable/focusable/effective-clickable 근거가 있는지 여부 |
| `node_state` | Yes | selected, focused, enabled 등 관찰된 최소 node state |
| `evidence_fingerprint` | Yes | dedupe와 진단을 위한 비영속 evidence fingerprint |
| `observations` | Yes | viewport별 bounds, label, source를 보존한 observation 목록 |
| `legacy_match` | No | 기존 display-name routing과의 shadow 비교 결과 |
| `identify_status` | Yes | Phase 1에서는 항상 `not_attempted` |

`stable_label`과 `display_label`은 locator 및 shadow comparison evidence다. 두 필드
어느 것도 `runtime_card_id` 또는 plugin identity의 source of truth가 아니다.

`runtime_card_id`는 한 inventory 실행 안에서 card를 참조하기 위한 값이다. account를
넘나드는 영속 device ID가 아니며 다음 실행에서 동일 값이 보장되지 않는다.

### 3.3 Identity And Dedupe Rule

스크롤 경계에서는 같은 card가 연속 viewport에 반복 노출될 수 있으므로 observation
병합은 필요하다. 그러나 label-only dedupe는 금지한다.

병합 판단은 다음 evidence를 함께 사용한다.

1. 인접 viewport에서의 상대 순서와 겹치는 scroll boundary
2. 동일한 container `resource_id`와 `class_name`
3. 동일하거나 정규화 가능한 label
4. 크기와 x-axis alignment가 유사한 bounds
5. room/section context 일치

모든 card가 공통 `resource_id`를 사용할 수 있으므로 resource-id 단독 병합도
금지한다. 병합 근거가 부족하면 별도 item으로 유지하고
`identity_confidence=low`와 warning을 기록한다. 동일 label의 여러 card는 기본적으로
서로 다른 item이며, 동일 모델 여러 대를 label로 합치지 않는다.

`evidence_fingerprint`는 관찰 비교용으로만 사용한다. bounds, 화면 순서, label이
변할 수 있으므로 persistent key로 승격하지 않는다.

## 4. Reuse From Current Discovery

Phase 1은 현재 Discovery의 다음 요소를 재사용할 수 있다.

- helper dump capture와 helper node extraction
- `collect_visible_device_cards()`의 card container 판정
- device card resource-id와 actionable node 조건
- `normalize_device_stable_label()`의 상태 suffix 제거
- label, stable label, bounds, resource-id, class 및 node state extraction
- top/left 기준의 deterministic viewport ordering
- source와 discovery confidence 개념
- discovery response의 schema version 및 diagnostics pattern
- 선택 location과 room section을 감지하는 기존 device tab helper

재사용 시에도 `known`과 `existing_scenario_id`는 inventory identity로 사용하지 않는다.
두 값은 legacy routing 비교용 shadow annotation으로만 유지할 수 있다.

## 5. New Information Required

현재 Discovery에 추가로 필요한 정보는 다음과 같다.

- inventory 실행 단위의 `inventory_id`와 capture timestamps
- selected account/location/filter context
- bounded scroll의 viewport fingerprint와 `screen_index`
- end-of-list 또는 repeated viewport를 판정하는 termination evidence
- viewport 간 observation 병합 기록과 `identity_confidence`
- 동일 label card를 보존하는 runtime ID allocation
- room/section heading과 card의 구조적 association
- full/partial collection 상태와 incomplete reason
- card 재탐색을 위한 observation history
- legacy match 결과를 identity와 분리한 shadow annotation
- 향후 Quick Identify가 결과를 연결할 explicit `identify_status`

room과 section은 dump 구조만으로 신뢰할 수 있을 때만 채운다. 근거가 약한 값을
display text에서 추측해 확정하지 않으며 empty와 low confidence를 허용한다.

## 6. Inventory Lifecycle

```text
Inventory Creation
-> Runtime Inventory
-> Quick Identify Input
-> Policy Selection
-> Existing Traversal Engine
```

### Inventory Creation

Devices tab과 현재 location/filter context를 고정하고 첫 helper dump를 수집한다.
visible card를 observation으로 기록한 뒤 bounded scroll을 수행하며 viewport fingerprint가
반복되거나 end-of-list가 확인될 때까지 수집한다. max scroll 또는 dump error로
종료하면 scope를 `partial`로 표시한다.

### Runtime Use

Inventory item은 capture 결과를 조회하고 특정 card를 다시 찾기 위한 runtime
descriptor로 사용한다. UI가 변하면 저장된 bounds를 바로 누르지 않고 현재 dump에서
resource, label, room/section, 상대 순서를 조합해 재검증한다.

### Quick Identify Handoff

Phase 2는 `runtime_card_id`와 locator evidence를 입력받아 card를 연다. identify 결과는
원본 item을 변경해 identity로 덮어쓰지 않고 별도 evidence/result로 연결한다.

### Policy Selection And Traversal

Policy Selection은 identify 결과를 기존 scenario policy에 매핑한다. Inventory 자체는
scenario를 선택하지 않는다. 선택된 policy 이후에는 기존 traversal engine을 사용한다.

Inventory는 한 routing session 동안만 유효하다. location/filter 변경, app restart,
구조적 화면 변경이 발생하면 stale로 처리하고 재수집한다.

## 7. Shadow Mode

Phase 1 Shadow Mode는 production navigation과 scenario selection을 변경하지 않는다.

- 기존 display-name routing을 계속 실행한다.
- 같은 시점에 runtime inventory artifact를 생성한다.
- legacy target label이 inventory에서 0개, 1개, 여러 개와 매칭되는지 기록한다.
- legacy가 선택한 card와 inventory item의 evidence를 연결한다.
- inventory는 card를 추가로 열거나 traversal을 시작하지 않는다.
- 수집 실패나 partial scope는 기존 실행을 차단하지 않고 diagnostics로 남긴다.

권장 관측 지표는 다음과 같다.

- viewport 및 bounded-scroll card coverage
- duplicate display label count
- low-confidence merge count
- legacy target 0/1/N match distribution
- partial inventory rate와 termination reason
- card rediscovery success rate

Phase 1 Shadow 결과는 Quick Identify 정확도를 의미하지 않는다. 이 단계의 성공은
"이름과 무관하게 card 후보를 개별 runtime item으로 열거하고 다시 참조할 수 있는가"로
판단한다.

## 8. Risks And Mitigations

| Risk | Impact | Design Response |
| --- | --- | --- |
| 동일 이름 | label-only dedupe 시 서로 다른 기기가 합쳐짐 | 동일 label을 허용하고 runtime ID를 별도 발급 |
| 스크롤 경계 중복 | 같은 card가 여러 item으로 기록됨 | observation 기반 multi-signal merge와 confidence 기록 |
| Bounds 변경 | 저장된 tap target이 stale해짐 | bounds는 hint로만 사용하고 action 직전 현재 dump로 재검증 |
| Card 위치 변경 | screen index와 순서가 달라짐 | screen index를 identity로 쓰지 않고 inventory를 session-scoped로 제한 |
| 동일 모델 여러 대 | resource와 구조가 동일해 구분이 어려움 | room/section/relative order를 보조 신호로 사용하고 불명확하면 분리 유지 |
| 동적 상태 text | label이 수집 중 변경됨 | raw display label과 normalized stable label을 observation별 보존 |
| lazy loading | 빠른 scroll에서 card 누락 | viewport stabilization 조건과 bounded retry 정의 |
| 무한/반복 scroll | inventory가 종료되지 않음 | repeated viewport, max scroll, timeout termination guard |
| room/section 오연결 | 잘못된 context가 locator를 오염 | 구조적 근거가 없으면 empty/low confidence 처리 |
| UI drift | resource-id 또는 hierarchy 변경 | source/evidence/diagnostics를 보존하고 단일 신호에 의존하지 않음 |
| inventory stale | 잘못된 card를 열 수 있음 | context change 시 invalidate하고 action 전 rediscovery |

가장 큰 위험은 안정적인 device identity가 없는 상태에서 runtime observation을 영속
identity로 오해하는 것이다. Phase 1은 persistent device registry가 아니라
capture-scoped inventory로 제한해야 한다.

## 9. Out Of Scope

Phase 1에서는 다음을 수행하지 않는다.

- plugin family 또는 capability 식별
- Quick Plugin Identify 실행
- capability/resource-id signature classifier
- scenario policy mapping 또는 policy selection
- production routing 변경
- display-name fallback 제거
- traversal engine 변경
- Frontend 노출
- account 간 persistent device identity 생성
- 모든 location을 자동 순회하는 global inventory
- inventory 결과로 device card를 자동 open

## 10. Acceptance Criteria

Phase 1은 다음 조건을 모두 만족하면 완료로 판단한다.

- 현재 선택된 Devices view의 bounded-scroll scope와 종료 이유를 artifact에 기록한다.
- 각 card가 inventory 내 unique `runtime_card_id`를 가진다.
- 동일 display name의 card가 자동으로 하나로 합쳐지지 않는다.
- label, bounds, resource-id, class, source, screen context와 observation history를
  보존한다.
- display name이 identity 또는 plugin type 판정으로 사용되지 않는다.
- viewport 경계의 반복 card에 대해 multi-signal dedupe 결과와 confidence를 기록한다.
- partial collection과 ambiguous merge가 명시적으로 관측된다.
- legacy display-name routing의 동작을 변경하지 않고 shadow comparison이 가능하다.
- Inventory item을 Phase 2 Quick Identify 입력으로 전달할 schema가 정의된다.
- location/filter/app context 변경 시 inventory invalidation 조건이 정의된다.

Phase 1 acceptance는 plugin type 판별 성공률로 평가하지 않는다. 그 평가는 Phase 2와
Phase 4의 책임이다.
