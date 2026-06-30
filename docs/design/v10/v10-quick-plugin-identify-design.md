# V10 Quick Plugin Identify Design

| Metadata | Value |
| --- | --- |
| Status | Completed |
| Phase | V10 Phase 2 |
| Owner | TalkBack Automation |
| Last Updated | 2026-06-30 |
| Depends On | [V10 Device Inventory Design](v10-device-inventory-design.md) |
| Related Documents | [V10 Overview](v10-overview.md), [V10 Phase Plan](v10-phase-plan.md), [V10 Policy Mapping Design](v10-policy-mapping-design.md) |
| Next | [V10 Policy Mapping Design](v10-policy-mapping-design.md) |

## 1. Purpose

Quick Plugin Identify는 Inventory가 발견한 runtime card를 짧게 열어, 화면 내부의
구조적 evidence로 plugin type 후보를 판정하는 Architecture Contract다.

Legacy routing은 아래처럼 display name을 scenario와 직접 연결한다.

```text
Display Name
-> Scenario
-> Traversal
```

이 방식은 같은 plugin이라도 사용자가 `거실 모션`, `Bedroom Motion`, `센서 1`처럼
이름을 변경하면 scenario를 찾기 어렵다. 반대로 이름에 `Motion`이 포함되어도 실제
plugin family가 Motion Sensor라는 보장은 없다.

Inventory는 화면의 card를 이름과 분리된 runtime item으로 열거하지만, card를 열기
전에는 plugin type을 확정하지 않는다. Quick Identify는 그 다음 단계에서
`runtime_card_id`가 가리키는 card를 제한된 범위로 열고, capability resource-id와
XML 구조 등 display name보다 직접적인 evidence를 수집한다.

목표 흐름은 다음과 같다.

```text
Runtime Card
-> Post-open Evidence
-> Plugin Type Candidate
-> Policy Mapping Input
```

Quick Identify의 결과는 policy 선택이나 traversal 시작 명령이 아니다. 충분한 근거가
있는 plugin candidate 또는 안전한 `unknown`/`ambiguous` 판정을 반환하는 것이
책임이다.

## 2. Input Contract

### 2.1 Required Input

Quick Identify는 하나의 Inventory envelope와 하나의 Inventory item을 입력으로 받는다.

| Field | Required | Purpose |
| --- | --- | --- |
| `inventory_id` | Yes | 결과가 어느 inventory 실행에 속하는지 연결 |
| `inventory_schema_version` | Yes | descriptor 호환성 확인 |
| `runtime_card_id` | Yes | inventory 안에서 대상 card를 식별 |
| `display_label` | Yes | 재탐색 보조 및 legacy shadow 비교 |
| `stable_label` | Yes | 상태 suffix를 제거한 locator 보조값 |
| `resource_id` | No | 현재 dump에서 card container 재탐색 |
| `class_name` | No | locator 교차 검증 |
| `bounds` | No | 최초 관찰 위치에 대한 비영속 hint |
| `entry_target` | Yes | bounds/resource/label을 묶은 재탐색 evidence |
| `room` | No | 동일 이름 card 구분을 위한 context |
| `section` | No | card group context |
| `screen_index` | Yes | card가 처음 발견된 scan viewport |
| `observed_screen_indexes` | Yes | card가 관찰된 viewport 목록 |
| `visibility` | Yes | full/partial/offscreen 상태 |
| `source` | Yes | helper/XML 등 Inventory evidence 출처 |
| `discovery_confidence` | Yes | card candidate 판정 신뢰도 |
| `identity_confidence` | Yes | observation 병합 신뢰도 |
| `observations` | Yes | 재탐색에 사용할 viewport별 evidence |
| `identify_status` | Yes | 입력 시 `not_attempted`여야 함 |

### 2.2 Input Preconditions

다음 조건을 만족하지 않으면 card를 열지 않고 `unknown`으로 종료한다.

- Inventory가 현재 account/location/filter/app session에 대해 유효하다.
- `runtime_card_id`가 Inventory 안에서 정확히 하나의 item을 가리킨다.
- 대상 card를 현재 helper dump에서 단일 candidate로 재탐색할 수 있다.
- candidate가 visible하고 actionable하다.
- 다른 실행, modal 또는 navigation transition이 진행 중이지 않다.

`bounds`, `screen_index`, `display_label` 중 어느 하나도 단독 entry key가 아니다.
action 직전 현재 dump에서 multi-signal로 card를 다시 확인해야 한다.

## 3. Output Contract

### 3.1 Quick Identify Result

| Field | Required | Description |
| --- | --- | --- |
| `schema_version` | Yes | Quick Identify result schema version |
| `identify_run_id` | Yes | 한 번의 identify attempt를 식별 |
| `inventory_id` | Yes | 입력 Inventory 연결 |
| `runtime_card_id` | Yes | 대상 runtime card 연결 |
| `started_at` | Yes | identify 시작 시각 |
| `completed_at` | Yes | identify 종료 시각 |
| `decision` | Yes | `identified`, `unknown`, `ambiguous`, `failed` |
| `plugin_type` | Yes | 판정된 canonical type, 아니면 `unknown` |
| `scenario_candidate` | No | Phase 3 검토용 advisory candidate |
| `confidence_score` | Yes | 0-100 bounded evidence score |
| `confidence_band` | Yes | `definite`, `high`, `medium`, `low`, `unknown` |
| `candidates` | Yes | 후보별 score, band, supporting/conflicting evidence |
| `evidence` | Yes | 정규화된 evidence record 목록 |
| `contradictions` | Yes | 후보 간 또는 source 간 충돌 목록 |
| `snapshot_refs` | Yes | helper/XML snapshot artifact reference |
| `stabilization` | Yes | stabilize 결과와 incomplete reason |
| `restoration` | Yes | Inventory 화면 복귀 및 대상 context 확인 결과 |
| `legacy_hint` | No | shadow 비교용 기존 display-name scenario |
| `shadow_comparison` | No | legacy와 identify 결과 비교 상태 |
| `duration_ms` | Yes | 전체 identify 소요 시간 |
| `errors` | Yes | capture, parse, open, back 실패 목록 |
| `recommended_action` | Yes | Phase 2 범위의 안전한 후속 조치 |

`scenario_candidate`는 routing decision이 아니다. plugin type과 기존 scenario 간
명백한 1:1 후보가 있을 때만 advisory 값으로 제공하며, Phase 3가 별도로 검증한다.

### 3.2 Candidate Record

각 `candidates` item은 다음 정보를 가진다.

| Field | Description |
| --- | --- |
| `plugin_type` | canonical plugin family |
| `score` | 해당 후보의 bounded score |
| `confidence_band` | score와 evidence quality gate를 적용한 band |
| `positive_evidence_ids` | 후보를 지지한 evidence |
| `negative_evidence_ids` | 후보와 충돌한 evidence |
| `unknown_evidence_ids` | 관찰할 수 없거나 불완전한 evidence |
| `quality_gate_passed` | structural evidence 최소 조건 충족 여부 |
| `rejection_reasons` | 후보 확정을 막은 이유 |

### 3.3 Evidence Record

각 evidence는 원본 snapshot과 판정 사이를 추적할 수 있어야 한다.

| Field | Description |
| --- | --- |
| `evidence_id` | result 내 unique ID |
| `source` | `helper`, `xml`, `talkback`, `inventory`, `legacy` |
| `kind` | resource-id, structure, header, label, speech, state 등 |
| `observed_value` | 실제 관찰값 또는 정규화된 요약 |
| `snapshot_ref` | evidence가 추출된 snapshot |
| `polarity` | `positive`, `negative`, `unknown` |
| `candidate_types` | evidence가 적용되는 plugin type |
| `weight` | scoring에 사용된 제안 weight |
| `reliability` | `very_high`, `high`, `medium`, `low`, `none` |
| `reason` | polarity와 reliability를 부여한 설명 |

### 3.4 Decision Semantics

- `identified`: 하나의 후보가 quality gate와 confidence 기준을 통과하고 강한 충돌이
  없다.
- `unknown`: 식별 evidence가 부족하거나 snapshot/open/stabilize가 불완전하다.
- `ambiguous`: 둘 이상의 후보가 유효하거나 강한 evidence가 서로 충돌한다.
- `failed`: card open 또는 Inventory 복귀 같은 lifecycle 자체가 안전하게 완료되지
  않았다.

`recommended_action`은 `record_candidate`, `record_unknown`, `manual_review`,
`retry_later`, `invalidate_inventory` 중 하나다. `start_traversal`은 Phase 2 출력으로
허용하지 않는다.

## 4. Lifecycle

```text
Inventory
-> Card Open
-> Screen Stabilize
-> Helper Snapshot
-> XML Snapshot
-> Evidence Extraction
-> Confidence Scoring
-> Plugin Candidate
-> Back
-> Inventory Restore Verification
```

### Inventory

입력 descriptor의 freshness와 runtime card uniqueness를 검증한다. stale 또는
ambiguous descriptor이면 open하지 않는다.

### Card Open

현재 dump에서 card를 재탐색하여 하나의 actionable target일 때만 연다. 이 단계의
display label은 보조 evidence이며 단독 선택 기준이 아니다.

### Screen Stabilize

새 plugin 화면 진입, loading 종료, helper tree의 구조적 안정성을 확인한다. timeout,
modal, error screen은 identify evidence가 아니라 lifecycle 상태로 기록한다.

### Helper And XML Snapshot

같은 안정화 window에서 helper snapshot과 XML snapshot을 각각 한 번 이상 수집한다.
두 source의 capture 시점 차이와 실패 여부를 기록한다. 한 source만 성공한 경우
confidence upper bound를 낮춘다.

### Evidence Extraction And Scoring

resource-id, capability header, XML hierarchy, representative label, TalkBack speech를
정규화된 evidence record로 변환한다. 원본 snapshot은 보존하고, legacy hint는
identify score와 분리한다.

### Plugin Candidate

후보별 positive, negative, unknown evidence를 계산하고 quality gate를 적용한다.
점수가 높아도 구조 evidence가 없거나 strong contradiction이 있으면 확정하지 않는다.

### Back And Inventory Restore

판정 후 back으로 이전 Devices context에 복귀하고 account/location/filter와 card
inventory context를 검증한다. 복귀 검증이 실패하면 result decision은 lifecycle
관점에서 `failed`로 기록하고 Inventory를 invalidate한다. 이미 수집한 evidence는
diagnostic artifact로 보존할 수 있지만 후속 routing에는 사용하지 않는다.

Quick Identify는 bounded operation이다. local tab 순회, control 조작, scroll coverage를
수행하지 않고 초기 안정 화면의 snapshot만 사용한다.

## 5. Evidence Model

Evidence 우선순위는 "화면이 어떤 plugin family로 구성되었는가"를 직접 설명하는
정도와 locale/display name 변화에 대한 안정성으로 결정한다.

### 5.1 Evidence Priority Matrix

아래 weight는 초기 calibration을 위한 제안값이며 확정된 production threshold가
아니다.

| Priority | Evidence | Suggested Weight | Reliability | Notes |
| --- | --- | ---: | --- | --- |
| Very High | family-specific capability root/header resource-id | 55 | Very High | 예: `MotionSensorCapabilityCardView`, `LockCapabilityCardView`; 단독 문자열이 실제 snapshot에 존재해야 함 |
| Very High | helper와 XML에서 같은 family-specific signature 교차 확인 | 65 | Very High | source 독립성이 확인될 때 가장 강한 evidence |
| High | capability header resource-id + 일치하는 header text | 35 | High | ID와 semantic label의 조합 |
| High | family-specific XML subtree/co-occurrence | 30 | High | parent/child/card structure가 signature와 일치 |
| High | 서로 다른 두 capability signature의 family-consistent 조합 | 30 | High | Washer, TV처럼 단일 root가 약한 경우 유용 |
| Medium | representative capability header/label | 18 | Medium | locale alias와 상태 text 변화에 민감 |
| Medium | TalkBack speech/merged label | 15 | Medium | 실제 사용자 노출 의미를 제공하지만 동적/locale 영향이 큼 |
| Medium | local tab 또는 control grouping | 10 | Medium | 공통 UI가 많아 단독 식별 금지 |
| Low | Inventory `stable_label`/`display_label` | 5 | Low | candidate tie-breaker와 shadow 분석에만 사용 |
| Low | room/section context | 2 | Low | locator 보조값이며 plugin type 근거로는 약함 |
| None | legacy scenario hint | 0 | None | score에 포함하지 않고 shadow comparison에만 사용 |
| None | generic chrome/navigation resource-id | 0 | None | Navigate up, More options, Devices tab 등 |
| None | loading/error/empty snapshot | 0 | Unknown | plugin evidence가 아니라 incomplete lifecycle evidence |

### 5.2 Priority Rules

- Very High/High structural evidence가 없는 후보는 `high` 이상이 될 수 없다.
- label, speech, display name만으로 `identified`를 만들지 않는다.
- helper와 XML이 같은 raw node를 표현할 뿐이라면 완전히 독립된 evidence로 중복
  가산하지 않는다.
- generic card/resource-id는 여러 plugin에 공통이므로 점수를 주지 않는다.
- legacy hint는 classifier score에 포함하지 않는다. 포함하면 shadow validation이
  circular해진다.
- evidence가 없다는 사실은 기본적으로 negative가 아니라 unknown이다.
- 강한 contradictory signature는 약한 positive 여러 개보다 우선한다.

## 6. Evidence Types

### Positive Evidence

특정 plugin 후보를 직접 지지하는 관찰이다.

예:

- `MotionSensorCapabilityCardView`가 helper/XML snapshot에 존재
- `LockCapabilityCardView` subtree와 `Locked/Unlocked` header가 함께 존재
- `WaterSensorCapabilityCardView_header_title`과 leak/dry/wet semantic label이
  일치

Positive evidence는 candidate type, source, raw value와 snapshot reference를 반드시
가진다.

### Negative Evidence

특정 후보와 명시적으로 충돌하는 관찰이다. 단순한 부재는 negative가 아니다.

예:

- `LockCapabilityCardView`는 단일-family calibration이 확립된 경우 Motion 후보에
  negative
- `SmokeSensorCapabilityCardView`와 smoke alarm structure는 Washer 후보에 negative
- open 결과가 target card가 아닌 다른 device title/context임이 구조적으로 확인됨

Multi-capability device가 가능하므로 다른 capability가 존재한다는 이유만으로 항상
negative를 부여하지 않는다. signature registry에서 상호 배타성이 검증된 조합만
strong negative로 사용한다.

### Unknown Evidence

관찰할 수 없거나 의미를 확정할 수 없는 상태다.

예:

- loading/skeleton 화면
- helper 또는 XML capture 실패
- generic `CapabilityCardView`만 존재
- resource-id 없이 `Motion` 같은 label만 존재
- snapshot 시점이 달라 helper/XML 구조가 비교 불가능
- locale alias registry에 없는 label

Unknown은 0점 evidence다. 점수를 감점해 다른 후보를 상대적으로 올리는 방식으로
사용하지 않는다.

## 7. Confidence Model

### 7.1 Suggested Bands

| Score | Band | Meaning |
| ---: | --- | --- |
| 95-100 | Definite | 교차 source 또는 복수의 독립 structural evidence가 일치 |
| 80-94 | High | 하나 이상의 강한 structural evidence와 supporting evidence가 일치 |
| 60-79 | Medium | plausible candidate이나 추가 validation 필요 |
| 40-59 | Low | 약한 후보, routing 입력으로 사용 불가 |
| 0-39 | Unknown | 식별 불가 |

### 7.2 Confidence Philosophy

점수는 통계적 확률이 아니라 evidence completeness와 consistency의 bounded summary다.
같은 계열의 중복 node를 많이 발견했다고 confidence가 계속 올라가면 안 된다.

Confidence는 다음 세 축을 함께 만족해야 한다.

1. **Strength**: family-specific structural evidence가 있는가
2. **Independence**: 서로 다른 종류/source의 evidence가 확인되는가
3. **Consistency**: strong contradiction 없이 하나의 후보로 수렴하는가

Quality gate는 raw score보다 우선한다.

- `Definite`는 helper/XML 교차 확인 또는 동등한 복수 독립 structural evidence가
  필요하다.
- `High`는 최소 하나의 Very High 또는 검증된 High structural evidence가 필요하다.
- Medium 이하 결과는 shadow candidate일 뿐 identified routing candidate가 아니다.
- helper/XML 중 하나가 실패하면 `Definite`를 허용하지 않는다.
- strong contradiction이 있으면 score와 관계없이 `ambiguous`다.
- lifecycle restoration 실패는 confidence와 별개로 result를 `failed` 처리한다.

Candidate 간 점수 차이도 필요하다. top candidate가 threshold를 넘더라도 second
candidate와의 margin이 calibration 기준보다 작으면 `ambiguous`다.

## 8. Fail-Closed Policy

Quick Identify는 다음 경우 `unknown`으로 종료한다.

- card를 현재 Inventory context에서 단일 target으로 재탐색할 수 없음
- plugin 화면 진입 또는 stabilization을 확인할 수 없음
- helper/XML snapshot이 모두 없거나 의미 있는 structure가 없음
- label/speech/display name evidence만 존재
- top candidate가 structural quality gate를 통과하지 못함
- score가 medium 이하이거나 evidence completeness가 부족함
- snapshot이 loading, error, permission 또는 modal 상태임

다음 경우 `ambiguous`로 종료한다.

- 둘 이상의 후보가 High 이상이며 충분한 score margin이 없음
- 서로 다른 plugin family의 Very High evidence가 충돌
- multi-capability 구조에서 primary plugin family를 contract상 결정할 수 없음
- helper와 XML이 서로 다른 family를 강하게 지지
- 같은 `runtime_card_id`가 실제로 둘 이상의 current card candidate와 연결됨

다음 경우 `failed`로 종료한다.

- 잘못된 card 또는 외부 화면이 열린 것이 확인됨
- back 동작 후 Inventory context 복귀를 확인하지 못함
- account/location/filter가 변경됨
- app crash, connection loss 또는 unrecoverable capture error 발생

`unknown`, `ambiguous`, `failed`에서는 traversal과 policy routing을 시작하지 않는다.
legacy fallback 사용 여부는 Phase 3 이후의 routing policy 책임이며 Quick Identify가
자동 결정하지 않는다.

## 9. Shadow Mode

Shadow Mode는 legacy 결과를 유지하면서 Quick Identify를 비교 기록한다.

| Legacy Result | Quick Identify | Shadow Status | Meaning |
| --- | --- | --- | --- |
| Motion | Motion / identified | `match` | family가 일치 |
| Motion | unknown | `identify_unknown` | legacy는 있으나 identify evidence 부족 |
| Motion | Door Lock / identified | `mismatch` | 양쪽 결과가 명시적으로 충돌 |
| Motion | Motion + Door Lock | `identify_ambiguous` | Quick Identify가 단일 후보를 확정하지 못함 |
| none | Motion / identified | `legacy_unmapped` | 이름 기반 routing이 놓친 확장 가능성 |
| none | unknown | `both_unresolved` | 어느 방식도 식별하지 못함 |
| unknown legacy label | TV / identified | `identify_only` | display name과 무관한 후보 발견 |
| any | failed | `identify_failed` | lifecycle 또는 restore 실패 |

Shadow record는 다음 값을 보존한다.

- `inventory_id`, `runtime_card_id`, display label
- legacy scenario/type과 lookup 근거
- identify decision, plugin type, score, band
- top candidates와 score margin
- positive/negative/unknown evidence IDs
- helper/XML snapshot refs
- match status와 mismatch reason
- stabilization 및 restoration 결과
- app version, locale, account/location 익명 context

Legacy hint는 Quick Identify 계산이 끝난 후 비교 단계에서만 결합한다. mismatch를
자동으로 classifier 오류 또는 legacy 오류로 단정하지 않고 manual triage 대상으로
남긴다.

## 10. Examples

아래 signature는 Architecture Contract를 설명하기 위한 초기 evidence 예시다. 실제
등록 전에는 여러 app version, locale, model의 snapshot corpus로 uniqueness와
상호 배타성을 검증해야 한다.

### 10.1 Motion Sensor

| Category | Example |
| --- | --- |
| Positive Evidence | `MotionSensorCapabilityCardView` root/header resource-id; `Motion sensor` 또는 motion state header; helper/XML 구조 일치 |
| Negative Evidence | 단일-family 검증이 완료된 `LockCapabilityCardView` 또는 `SmokeSensorCapabilityCardView`만 존재 |
| Expected Confidence | root ID가 helper/XML에서 교차 확인되면 Definite; 한 source + header면 High |
| Unknown Case | display name이 `거실 모션`이지만 generic card와 `Battery` label만 관찰됨 |

### 10.2 Door Lock

| Category | Example |
| --- | --- |
| Positive Evidence | `LockCapabilityCardView`; lock state (`Locked`, `Unlocked`)와 lock control subtree 조합 |
| Negative Evidence | smoke/water sensor 전용 root만 있고 lock structure가 없음 |
| Expected Confidence | unique lock root + state/control structure면 High 또는 Definite |
| Unknown Case | `Door Lock` display name과 generic power switch만 존재 |

### 10.3 Smoke Sensor

| Category | Example |
| --- | --- |
| Positive Evidence | `SmokeSensorCapabilityCardView`; smoke detector/alarm state header; helper/XML 일치 |
| Negative Evidence | water leak 전용 root와 wet/dry structure만 존재 |
| Expected Confidence | unique smoke root의 cross-source 확인이면 Definite |
| Unknown Case | 화면이 loading 중이거나 `Alarm`이라는 representative label만 존재 |

### 10.4 Water Leak Sensor

| Category | Example |
| --- | --- |
| Positive Evidence | `WaterSensorCapabilityCardView` 또는 `_header_title`; leak/wet/dry semantic header와 sensor subtree 조합 |
| Negative Evidence | lock 또는 washer 전용 root만 존재하고 water sensor structure가 없음 |
| Expected Confidence | WaterSensor root + leak semantic evidence면 High; cross-source면 Definite 후보 |
| Unknown Case | `Water` label만 있고 sensor인지 valve/appliance인지 구분할 구조가 없음 |

### 10.5 Washer

| Category | Example |
| --- | --- |
| Positive Evidence | `LaundryWasherRinseModeCapabilityCardView_header_title`; cycle, rinse, spin 등 washer-consistent capability 조합 |
| Negative Evidence | TV remote/channel/source structure 또는 sensor-only root만 존재 |
| Expected Confidence | washer-specific resource + 서로 다른 laundry capability 조합이면 High/Definite |
| Unknown Case | `Washer` display name과 generic power/status card만 존재하거나 washer/dryer 구분 신호가 없음 |

### 10.6 TV

| Category | Example |
| --- | --- |
| Positive Evidence | remote control, channel, source/input, volume 등 TV-consistent structure의 복수 조합 |
| Negative Evidence | washer cycle/rinse subtree 또는 sensor-only capability root만 존재 |
| Expected Confidence | 검증된 TV-specific root가 없으면 단일 label로 High 금지; 복수 독립 구조가 일치하면 High 후보 |
| Unknown Case | `TV` display name과 generic power control만 존재하여 monitor, display 또는 다른 media device와 구분 불가 |

### 10.7 Cross-Example Rules

- `Battery`, `History`, `Controls`, `Power`, `More options`는 여러 plugin에 공통이므로
  단독 positive evidence가 아니다.
- device display name이 family 이름과 같아도 structural quality gate를 대체하지
  못한다.
- 예상 capability가 없다는 사실은 snapshot completeness가 검증되지 않으면
  negative가 아니라 unknown이다.
- multi-capability device에서 Motion과 Temperature가 함께 나타나는 것은 자동
  contradiction이 아니다.

## 11. Decision Matrix

| Evidence Combination | Decision | Confidence | Action |
| --- | --- | --- | --- |
| 동일 family-specific signature가 helper/XML에서 일치하고 contradiction 없음 | `identified` | Definite | candidate 기록, Phase 3 입력 가능 |
| 하나의 Very High structural signal + 일치하는 header/structure | `identified` | High | candidate 기록, shadow 검증 |
| 두 개 이상의 독립 High structural signal + 충분한 score margin | `identified` | High | candidate 기록, shadow 검증 |
| structural signal 하나이나 snapshot source 하나가 실패 | `unknown` 또는 제한적 candidate | Medium 이하 | routing 금지, retry/manual review |
| representative label + TalkBack speech만 일치 | `unknown` | Low/Medium | 기록만 수행 |
| display name/legacy hint만 일치 | `unknown` | Low | legacy shadow 비교만 수행 |
| 서로 다른 family의 Very High evidence가 공존 | `ambiguous` | N/A | traversal 금지, manual review |
| top two candidate가 threshold를 넘고 margin 부족 | `ambiguous` | N/A | traversal 금지, registry calibration |
| loading/error/modal 또는 snapshot 없음 | `unknown` | Unknown | retry later |
| card open 실패 | `failed` | Unknown | Inventory 재탐색 또는 invalidate |
| Inventory 복귀 검증 실패 | `failed` | N/A | Inventory invalidate, 후속 routing 금지 |

## 12. Out Of Scope

이 문서는 다음을 정의하지 않는다.

- plugin type에서 scenario로 연결하는 Policy Mapping
- production routing 또는 legacy fallback 선택
- traversal engine 실행
- local tab/scroll coverage
- capability control 조작
- Frontend 표시 방식
- scenario config 변경
- signature registry의 production 값과 최종 weight calibration
- 새로운 Plugin Discovery 구현
- account 간 persistent device identity
- unknown/ambiguous의 운영 승인 workflow

## 13. Acceptance Criteria

Phase 2 Architecture Contract는 다음 조건을 모두 만족하면 완료로 판단한다.

- Inventory item에서 Quick Identify로 전달되는 필수 입력 schema가 정의된다.
- `identified`, `unknown`, `ambiguous`, `failed`의 의미가 상호 구분된다.
- result, candidate, evidence record schema가 정의된다.
- resource-id, XML structure, header, label, speech, display name의 우선순위가
  Evidence Priority Matrix로 정의된다.
- positive, negative, unknown evidence의 의미와 오용 방지 규칙이 정의된다.
- score보다 structural quality, source independence, consistency를 우선하는
  Confidence 철학이 정의된다.
- label/speech/display-name-only 판정을 fail-closed 처리한다.
- strong contradiction과 close candidates를 `ambiguous`로 처리한다.
- helper/XML capture와 Inventory restoration 실패의 결과가 정의된다.
- Shadow Mode의 match, mismatch, unknown, ambiguous, identify-only 기록 계약이
  정의된다.
- Motion, Door Lock, Smoke, Water Leak, Washer, TV 사례가 positive/negative/
  confidence/unknown 관점으로 설명된다.
- Quick Identify가 traversal 또는 policy routing을 직접 시작하지 않는다는 경계가
  명확하다.
- 실제 signature와 threshold는 snapshot corpus 기반 calibration 전까지 제안값임이
  명시된다.

Phase 2 완료는 classifier 구현 완료를 의미하지 않는다. 이 문서의 완료 조건은
구현과 검증이 따라야 할 evidence 및 decision contract가 모호하지 않게 정의되는
것이다.
