# V10 Implementation Roadmap

| Metadata | Value |
| --- | --- |
| Status | Completed |
| Phase | V10 Execution Planning |
| Owner | TalkBack Automation |
| Last Updated | 2026-07-03 |
| Depends On | [V10 Shadow Validation Design](v10-shadow-validation-design.md) |
| Related Documents | [V10 Overview](v10-overview.md), [V10 Device Inventory Design](v10-device-inventory-design.md), [V10 Quick Plugin Identify Design](v10-quick-plugin-identify-design.md), [V10 Policy Mapping Design](v10-policy-mapping-design.md), [V10 Phase Closure](v10-phase-closure.md) |
| Next | [V10 Phase Closure](v10-phase-closure.md) |

## 1. Purpose

이 문서는 V10 Architecture Contract를 작은 구현 Sprint로 전환하기 위한 Project
Execution Plan이다. 새로운 contract를 정의하지 않고 구현 순서, 산출물, 검증,
완료 조건과 rollback point를 정한다.

Sprint 단위로 구현하는 이유는 다음과 같다.

- Inventory, Identify, Mapping, Shadow의 failure domain을 분리할 수 있다.
- 각 단계가 reporting-only로 동작하는지 확인한 뒤 다음 단계로 이동할 수 있다.
- 기존 Legacy routing과 Traversal Engine의 회귀를 Sprint마다 차단할 수 있다.
- device-dependent 문제를 fixture/offline 문제와 분리해 진단할 수 있다.
- 문제가 발생하면 마지막 검증된 boundary까지 기능 단위로 비활성화할 수 있다.

Routing을 한 번에 교체하면 card inventory 오류, identify 오탐, mapping 오류와
traversal 회귀가 하나의 실행에서 섞인다. V10은 Legacy를 계속 authoritative path로
유지하고, 관찰 가능한 shadow layer를 아래에서 위로 쌓아야 한다.

## 2. Implementation Strategy

장기적인 전환 방향은 다음과 같다.

```text
Legacy Maintained
-> Shadow Capabilities Added
-> Capability Routing Runs Alongside Legacy
-> Family-level Promotion
-> Controlled Routing
-> Legacy Dependency Reduction
-> Legacy Removal Decision
```

이 Roadmap의 실제 범위는 `Promotion Readiness`까지다. Controlled Routing 운영,
production default 전환과 Legacy 제거는 후속 계획으로 분리한다.

실행 원칙:

- 모든 신규 기능은 기본적으로 off 또는 reporting-only로 시작한다.
- Sprint 1-4에서는 V10 결과가 production scenario selection을 바꾸지 않는다.
- 기존 display-name routing과 Traversal Engine 결과를 baseline으로 보존한다.
- unknown, ambiguous, failed는 fail-closed로 유지한다.
- schema와 artifact version을 첫 Sprint부터 기록한다.
- 각 Sprint는 이전 Sprint artifact를 입력으로 사용하고 내부 구현에 직접 결합하지
  않는다.
- device test 이전에 fixture 기반 offline/unit gate를 통과한다.

## 3. Sprint Plan

### 3.1 Sprint Summary

| Sprint | Goal | Deliverables | Validation |
| --- | --- | --- | --- |
| Sprint 0 | 계약과 baseline 고정 | scope checklist, fixture corpus, version plan, feature-flag/rollback plan, baseline report | Offline review, baseline unit/full regression |
| Sprint 1 | Runtime Device Inventory 구현 | inventory schema/model, bounded scanner, observation merge, artifact, diagnostics | Offline fixture, unit, targeted device |
| Sprint 2 | Quick Plugin Identify 구현 | open/stabilize/snapshot/restore flow, evidence extractor, candidate result, fail-closed handling | Offline corpus, unit, targeted device |
| Sprint 3 | Versioned Policy Registry 구현 | registry, mapping selector, conflict rules, selection artifact | Offline replay, unit, targeted smoke |
| Sprint 4 | Legacy/V10 Shadow Compare 구현 | dual decision orchestration, comparison result, metrics, shadow artifacts | Integration, targeted device, shadow full run |
| Sprint 5 | QA Frontend reporting 통합 | backend read API, summary/drill-down UI, version/gate visibility | API unit, frontend test/build, artifact replay |
| Sprint 6 | Promotion Readiness 평가 | promotion evaluator, drift/rollback checks, readiness report | Multi-cohort shadow validation, full run, manual adjudication |

### 3.2 Sprint 0: Preparation

**Goal**

V10 구현 전에 contract, baseline, fixture와 rollback boundary를 고정한다.

**Deliverables**

- Phase 1-4 schema/version checklist
- representative helper/XML fixture corpus와 anonymization rule
- 최소 pilot family: Motion, Lock, Smoke, Leak, Washer, TV
- current Legacy routing regression baseline
- feature flag 및 default-off 원칙
- Sprint별 artifact naming/output isolation plan
- device/account/locale/app-version validation matrix
- owner와 review/approval boundary

**Verification**

- 모든 V10 문서 link와 schema field consistency review
- 기존 unit test suite baseline 기록
- 대표 Device Scenario targeted baseline 기록
- current full run의 scenario availability/result baseline 기록
- fixture에 raw helper/XML과 expected interpretation이 함께 있는지 검토

**Exit Criteria**

- 구현 대상 contract가 승인되고 unresolved schema conflict가 없다.
- pilot fixture가 최소 positive, negative, unknown, ambiguous case를 포함한다.
- 기존 테스트와 대표 full run baseline이 재현 가능하다.
- 각 Sprint feature가 독립적으로 disable 가능한 계획이 있다.
- artifact가 기존 production output을 덮어쓰지 않는 경로가 정의된다.

**Risk**

불완전한 fixture로 구현을 시작하면 실제 device variation을 classifier bug로
오해하거나 반대로 과적합할 수 있다.

**Rollback Point**

코드 변경 전 baseline이다. Preparation gate가 실패하면 Sprint 1을 시작하지 않는다.

### 3.3 Sprint 1: Inventory Runtime

**Goal**

현재 Devices view의 card를 display name identity 없이 runtime inventory로 수집한다.

**Deliverables**

- versioned Inventory envelope/item model
- visible-card collection과 bounded scroll scanner
- viewport observation, termination reason과 partial scope
- label-only dedupe를 사용하지 않는 merge logic
- capture-scoped `runtime_card_id`
- inventory JSON artifact와 diagnostics
- current Discovery와의 adapter 또는 compatibility boundary

**Verification**

- offline helper dump fixture로 card extraction/ordering 검증
- duplicate display name, changing bounds, repeated viewport unit tests
- scroll end, timeout, helper failure와 stale context tests
- targeted device에서 visible/scrollable card 수동 대조
- Inventory 실행 전후 selected location/filter가 유지되는지 확인

**Exit Criteria**

- eligible scope의 모든 관찰 card가 artifact에 포함된다.
- 동일 이름의 서로 다른 card가 자동 병합되지 않는다.
- repeated viewport card는 evidence와 confidence를 갖고 병합된다.
- partial/failed collection을 complete로 보고하지 않는다.
- Inventory 실행이 Legacy routing 결과를 변경하지 않는다.
- feature off 시 기존 Discovery 동작과 artifact가 변하지 않는다.

**Risk**

scroll side effect, lazy loading, unstable bounds와 잘못된 observation merge가 주요
위험이다.

**Rollback Point**

Inventory collector/flag를 disable하고 기존 current-view discovery만 사용한다.
생성된 V10 artifact는 삭제하지 않고 diagnostic으로 보존한다.

### 3.4 Sprint 2: Quick Plugin Identify

**Goal**

Inventory item을 짧게 열어 structural evidence 기반 plugin candidate를 reporting-only로
반환한다.

**Deliverables**

- runtime card rediscovery와 single-target gate
- open, stabilize, helper/XML snapshot, back/restore lifecycle
- normalized evidence/result schema
- capability signature extraction과 confidence quality gate
- `identified`, `unknown`, `ambiguous`, `failed` 처리
- pilot family evidence registry
- snapshot/result artifact

**Verification**

- fixture corpus 기반 positive/negative/unknown extraction tests
- duplicate evidence, source failure, contradiction과 candidate margin tests
- open 실패/loading/modal/restoration failure unit tests
- pilot family targeted device tests
- display name을 바꾼 card에서 동일 structural result가 나오는지 확인
- identify 전후 Inventory context와 card list 복귀 검증

**Exit Criteria**

- pilot family의 verified signature를 expected candidate로 반환한다.
- label/display-name-only case는 identified가 되지 않는다.
- unknown/ambiguous/failed에서 traversal을 시작하지 않는다.
- restoration success가 pilot scope에서 요구 수준을 충족한다.
- confidence result가 raw evidence와 snapshot reference로 추적 가능하다.
- Legacy scenario selection은 변경되지 않는다.

**Risk**

잘못된 card open, incomplete stabilization, helper/XML 시점 차이와 복귀 실패가 가장
큰 위험이다.

**Rollback Point**

Quick Identify flag를 disable하고 Sprint 1 Inventory artifact까지만 생성한다.
Identify failure가 Legacy fallback을 자동 실행하도록 연결하지 않는다.

### 3.5 Sprint 3: Policy Registry

**Goal**

Quick Identify candidate를 기존 Scenario Policy에 deterministic하게 연결하되 routing은
변경하지 않는다.

**Deliverables**

- versioned canonical capability registry
- 12개 현재 Device Scenario mapping entry
- confidence requirement와 entry status
- discriminator, forbidden conflict와 precedence rule
- Traversal Policy Selection result
- registry/mapping/routing version 기록

**Verification**

- recorded Quick Identify Result replay tests
- exact mapping, registry miss, disabled/deprecated entry tests
- Motion+Temperature, Motion+Vibration, Camera/Home Camera conflict tests
- one-to-many mapping과 missing discriminator tests
- version mismatch/backward compatibility tests
- existing scenario ID availability sanity check

**Exit Criteria**

- 같은 version/input이 항상 같은 selection을 반환한다.
- Medium 이하, unresolved ambiguous와 failed는 V10 route가 되지 않는다.
- mapping이 없는 candidate에 scenario를 추측 생성하지 않는다.
- 12개 entry가 모두 explicit status와 minimum confidence를 가진다.
- selected scenario가 기존 Scenario Policy를 그대로 참조한다.
- production routing은 Legacy 상태를 유지한다.

**Risk**

classifier candidate와 scenario granularity 불일치, 잘못된 precedence와 stale scenario
reference가 주요 위험이다.

**Rollback Point**

Registry 전체 또는 family entry를 `disabled` 처리하고 Quick Identify 결과까지만
shadow artifact에 남긴다.

### 3.6 Sprint 4: Shadow Compare

**Goal**

Legacy와 V10 scenario decision을 같은 runtime card 기준으로 비교하고 promotion
metric을 생성한다.

**Deliverables**

- Legacy/V10 dual-decision orchestration
- MATCH/MISMATCH/UNKNOWN/AMBIGUOUS/FAILED comparison
- denominator-safe metric aggregation
- `shadow_validation.json`, `routing_compare.csv`, summary/report artifact
- version cohort와 confidence drift baseline
- critical mismatch/restoration incident record

**Verification**

- synthetic comparison matrix unit tests
- denominator zero, partial artifact와 repeated sample tests
- end-to-end artifact integration tests
- targeted device shadow runs
- plugin family/locale/app-version cohort 확인
- 기존 Legacy-selected scenario와 traversal result가 shadow off/on에서 같은지 full run
  비교

**Exit Criteria**

- 동일 `runtime_card_id`가 아니면 비교하지 않는다.
- failure/unknown을 제외해 Match Rate가 부풀려지지 않는다.
- shadow on/off에서 production routing과 Traversal 결과가 동일하다.
- 필수 artifact와 version field가 완전하다.
- mismatch와 restoration failure가 blocking incident로 노출된다.
- M3 Shadow MVP 결과를 반복 생성할 수 있다.

**Risk**

잘못된 comparison identity, metric denominator 오류, runtime overhead와 shadow가
Legacy timing/state에 영향을 주는 문제가 핵심 위험이다.

**Rollback Point**

Shadow orchestration을 disable하고 Sprint 1-3 기능을 수동/reporting-only 도구로
제한한다. Legacy run path와 기존 report를 authoritative 상태로 유지한다.

### 3.7 Sprint 5: Frontend Integration

**Goal**

Shadow 결과를 QA가 판독할 수 있도록 reporting-only로 노출한다.

**Deliverables**

- shadow artifact read/summary backend API
- family별 comparison/metric/promotion status
- mismatch/unknown/ambiguous/failed drill-down
- confidence/version/cohort/rollback reason 표시
- artifact missing/stale/error state
- V10 routing을 변경하지 않는 read-only UI

**Verification**

- backend parser/API unit tests
- malformed/missing/old-version artifact tests
- frontend component/API contract tests
- production build
- stored artifact replay로 UI 값과 source artifact 대조
- accessibility와 locale label 확인

**Exit Criteria**

- Agreement와 adjudicated Routing Accuracy를 구분해 표시한다.
- family/blocking reason/version cohort를 추적할 수 있다.
- UI가 unknown/failed를 success denominator에서 숨기지 않는다.
- UI action이 routing, registry 또는 scenario config를 변경하지 않는다.
- artifact가 없어도 기존 QA 기능이 정상 동작한다.

**Risk**

MATCH를 accuracy로 오해하게 만드는 표현, stale report, 민감 context 노출과 UI/API
schema drift가 주요 위험이다.

**Rollback Point**

V10 panel/route를 숨기고 backend artifact generation은 유지한다. 기존 QA Frontend
기능에는 영향을 주지 않는다.

### 3.8 Sprint 6: Promotion Readiness

**Goal**

family/version cohort별로 Controlled Routing 후보 여부를 판정한다.

**Deliverables**

- promotion/hold/blocked/insufficient-data evaluator
- Promotion Matrix와 Rollback Matrix evaluation
- confidence drift와 sample diversity report
- manual adjudication record 연결
- family별 readiness table
- M4 promotion readiness report와 unresolved risk list

**Verification**

- gate boundary와 critical override unit tests
- version change/new cohort tests
- multiple account/locale/model/app-version shadow runs
- confirmed mismatch와 restoration failure injection/replay
- adjudicated sample review
- representative full runs와 repeated clean window 비교

**Exit Criteria**

- required gate를 family별로 독립 평가한다.
- confirmed mismatch/critical failure는 aggregate metric과 무관하게 block한다.
- insufficient sample은 promotable로 표시되지 않는다.
- version 변경 시 기존 approval을 자동 상속하지 않는다.
- promotable family와 Legacy 유지 family가 명확히 분리된다.
- Controlled Routing을 시작하지 않고 readiness report만 생성한다.

**Risk**

작은 표본, 반복 device의 과대 계산, metric gaming, confidence drift와 수동
adjudication 부족이 주요 위험이다.

**Rollback Point**

모든 promotion 상태를 `HOLD` 또는 `BLOCKED`로 되돌리고 Legacy를 유지한다. Shadow
artifact는 보존하며 production routing은 변경하지 않는다.

## 4. Sprint Dependency

### 4.1 Dependency Diagram

```text
Sprint 0: Preparation
          |
          v
Sprint 1: Inventory Runtime
          |
          v
Sprint 2: Quick Plugin Identify
          |
          v
Sprint 3: Policy Registry
          |
          v
Sprint 4: Shadow Compare
          |
          v
Sprint 5: Frontend Integration
          |
          v
Sprint 6: Promotion Readiness
```

Sprint 5는 artifact contract가 안정된 뒤 시작한다. Sprint 6의 evaluator 자체는
Sprint 4 artifact로 개발할 수 있지만, 운영 review readiness는 Sprint 5 reporting
검증 이후 완료한다.

### 4.2 Dependency Matrix

| Sprint | Depends On | Blocks |
| --- | --- | --- |
| Sprint 0 | Approved V10 design documents | Sprint 1 |
| Sprint 1 | Sprint 0 fixtures/baseline/version plan | Sprint 2 |
| Sprint 2 | Sprint 1 runtime card contract | Sprint 3 |
| Sprint 3 | Sprint 2 candidate/result contract | Sprint 4 |
| Sprint 4 | Sprint 1-3 artifacts and versions | Sprint 5, Sprint 6 |
| Sprint 5 | Sprint 4 stable artifact schema | Sprint 6 operational review |
| Sprint 6 | Sprint 4 metrics, Sprint 5 visibility, adjudication | Future Controlled Routing |

## 5. Expected Code Ownership

아래는 구현 시 예상되는 ownership이며 확정된 file change list가 아니다. 기존
Traversal Engine 내부 변경은 계획하지 않는다.

| Sprint | Expected Modules | Ownership Boundary |
| --- | --- | --- |
| Sprint 0 | test fixtures, V10 schema/version definitions, validation scripts | baseline과 contract 준비 |
| Sprint 1 | `tb_runner/plugin_card_discovery.py`, `tb_runner/device_tab_logic.py`, 신규 inventory module, 관련 tests | card 수집과 runtime inventory |
| Sprint 2 | `tb_runner/plugin_probe.py`, 신규 identify/evidence module, helper/XML capture adapter, 관련 tests | bounded identify lifecycle |
| Sprint 3 | 신규 policy registry/selector module, scenario lookup adapter, 관련 tests | mapping only; scenario config 내용은 유지 |
| Sprint 4 | 신규 shadow comparison/report module, 최소 orchestration integration, 필요 시 `tb_runner/collection_flow.py`의 boundary hook, 관련 tests | production decision을 바꾸지 않는 shadow hook |
| Sprint 5 | `qa_frontend/backend`의 artifact API/parser, `qa_frontend/frontend/src`의 reporting component/API, 관련 tests | read-only reporting |
| Sprint 6 | promotion evaluator/report tooling, shadow artifact parser, validation tests | readiness calculation only |

`collection_flow.py`를 수정해야 하더라도 기존 step collection, stop policy, local tab,
coverage와 traversal decision을 변경하지 않는 얇은 observation hook으로 제한한다.
`scenario_config.py`는 이 Roadmap의 예상 수정 대상이 아니다.

## 6. Validation Strategy

| Sprint | Offline Test | Unit Test | Targeted Device Test | Shadow Validation | Full Run |
| --- | --- | --- | --- | --- | --- |
| Sprint 0 | Required | Baseline | Baseline sample | Not applicable | Baseline required |
| Sprint 1 | Required | Required | Required | Reporting check | Regression as needed |
| Sprint 2 | Required | Required | Required | Candidate recording | Pilot regression |
| Sprint 3 | Required replay | Required | Targeted smoke | Selection recording | Not primary |
| Sprint 4 | Required synthetic | Required | Required | Required | Required |
| Sprint 5 | Artifact replay | Required | UI data smoke | Report review | Existing QA regression |
| Sprint 6 | Cohort replay | Required | Multi-device/account | Required over clean windows | Required |

Validation ordering은 항상 다음을 따른다.

```text
Offline Fixture
-> Unit/Contract Test
-> Integration Test
-> Targeted Device Test
-> Shadow Full Run
-> Promotion Review
```

앞 단계 실패를 device 반복 실행으로 우회하지 않는다. Device test 결과는 app/helper
version, locale, account/location context와 함께 기록한다.

## 7. Risk Register

### 7.1 Risk Matrix

| Sprint | Risk | Mitigation |
| --- | --- | --- |
| Sprint 0 | `P0` fixture/baseline 부족으로 잘못된 설계 가정 고정 | pilot family별 positive/negative/unknown/ambiguous corpus와 baseline 승인 |
| Sprint 1 | `P0` scroll이 UI context를 바꾸거나 card를 누락 | bounded scanner, termination reason, state restoration, partial fail-closed |
| Sprint 1 | `P1` 동일 이름/변경 bounds로 잘못된 dedupe | multi-signal observation merge, low-confidence 분리 유지 |
| Sprint 2 | `P0` 잘못된 card open 또는 Inventory 복귀 실패 | action 전 rediscovery, single-target gate, restoration verification |
| Sprint 2 | `P0` label 기반 classifier 과적합 | structural quality gate, cross-source evidence, display name weight 제한 |
| Sprint 2 | `P1` helper/XML snapshot 시점 불일치 | stabilization window와 source timestamp 기록 |
| Sprint 3 | `P0` 잘못된 scenario mapping | versioned allowlist, explicit entry status, conflict/discriminator tests |
| Sprint 3 | `P1` multi-capability precedence 오판 | primary signature 우선, unresolved case ambiguous |
| Sprint 4 | `P0` shadow가 production routing/timing에 영향 | reporting-only hook, on/off equivalence full run |
| Sprint 4 | `P0` denominator 오류로 metric 과대평가 | explicit denominator tests, unknown/failed 별도 gate |
| Sprint 4 | `P1` 서로 다른 card 결과 비교 | inventory/runtime card identity contract 강제 |
| Sprint 5 | `P1` MATCH를 accuracy로 오해 | Agreement와 adjudicated Accuracy 분리 표시 |
| Sprint 5 | `P1` stale/민감 artifact 노출 | version/freshness 표시, context 익명화 |
| Sprint 6 | `P0` 작은 표본 또는 반복 run으로 조기 promotion | distinct cohort/sample diversity와 clean window gate |
| Sprint 6 | `P0` confirmed mismatch가 평균에 가려짐 | critical override와 family-level block |
| Sprint 6 | `P1` version drift 상태에서 과거 approval 재사용 | immutable cohort와 version change 재검증 |

P0는 Sprint exit를 차단한다. P1은 명시적 mitigation과 owner가 없으면 다음
milestone으로 이동하지 않는다.

## 8. Rollback Plan

| Failed Sprint | Rollback Boundary | Preserved Capability | Prohibited After Rollback |
| --- | --- | --- | --- |
| Sprint 0 | current Legacy baseline | 기존 Discovery/Runner/Traversal | V10 implementation start |
| Sprint 1 | Inventory feature off | 기존 visible discovery | V10 inventory를 routing에 사용 |
| Sprint 2 | Identify feature off | Inventory artifact | candidate 기반 mapping/routing |
| Sprint 3 | Registry/family entry disabled | Inventory + Identify artifact | mapped scenario로 traversal 시작 |
| Sprint 4 | Shadow orchestration off | Sprint 1-3 standalone diagnostics | shadow result가 production decision 변경 |
| Sprint 5 | V10 UI/API surface hidden | backend artifacts와 기존 QA UI | stale/partial report 노출 |
| Sprint 6 | all promotion verdicts HOLD/BLOCKED | Shadow operation과 Legacy baseline | Controlled Routing 진입 |

Rollback 원칙:

- rollback은 기존 Legacy behavior를 복원하는 것이 아니라 처음부터 유지된 Legacy
  authority를 계속 사용하는 것이다.
- diagnostic artifact와 incident record를 삭제하지 않는다.
- 실패 Sprint 이후의 dependent feature를 함께 disable한다.
- schema/version 변경을 되돌릴 때 기존 artifact를 새 schema로 덮어쓰지 않는다.
- production output과 traversal result가 바뀌었다면 해당 Sprint exit는 실패다.

## 9. Success Metrics

| Sprint | Primary Metric | Success Interpretation |
| --- | --- | --- |
| Sprint 0 | Baseline reproducibility, fixture completeness | 구현 전 expected behavior가 재현 가능 |
| Sprint 1 | Inventory Coverage, duplicate preservation, partial detection | runtime card를 누락/오병합 없이 열거 |
| Sprint 2 | Adjudicated Identify Accuracy, unknown/ambiguous rate, restoration success | 구조 evidence로 안전한 candidate 생성 |
| Sprint 3 | Policy Agreement, deterministic selection, registry miss safety | candidate가 올바른 기존 scenario에만 연결 |
| Sprint 4 | Shadow Match/Mismatch, coverage, failure/fallback rate | Legacy와 비교 가능한 안전한 Shadow MVP |
| Sprint 5 | Report correctness, artifact/UI agreement, blocking visibility | QA가 결과와 위험을 오해 없이 판독 |
| Sprint 6 | Promotion gate pass rate, routing accuracy, clean windows | family별 Controlled Routing 준비 여부 판정 |

Success metric은 Sprint exit criteria를 대체하지 않는다. 예를 들어 Match Rate가 높아도
confirmed mismatch 1건이나 restoration failure가 있으면 M4로 승격하지 않는다.

## 10. Milestones

### 10.1 Milestone Table

| Milestone | Completion Condition |
| --- | --- |
| M1 Inventory Complete | Sprint 1 exit 통과; complete/partial scope, duplicate card와 runtime ID가 검증됨 |
| M2 Quick Identify Ready | Sprint 2 exit 통과; pilot family evidence와 fail-closed restoration이 검증됨 |
| M3 Shadow MVP | Sprint 3-4 exit 통과; Legacy authority를 유지한 comparison artifact/metrics 생성 |
| M4 Promotion Ready | Sprint 5-6 exit 통과; family별 promotable/hold/blocked 판단과 rollback evidence 완성 |

Milestone은 코드 병합 시점이 아니라 검증과 exit criteria 통과 시점이다.

## 11. Non-Goals

이 Roadmap은 다음을 포함하지 않는다.

- Legacy routing 제거
- Controlled Routing의 실제 운영
- V10 production default 전환
- 전체 account/device에 대한 production rollout
- Traversal Engine 재작성
- Scenario Policy 재설계
- coverage semantics 변경
- 모든 plugin family를 동일 시점에 promotion
- persistent cross-account device identity
- final kill switch 운영 구현

## 12. Acceptance Criteria

이 Roadmap은 다음 조건을 모두 만족하면 완료된 실행 계획으로 판단한다.

- Sprint 0-6 각각 Goal, Deliverables, Verification, Exit Criteria, Risk와 Rollback
  Point를 가진다.
- Sprint Summary와 Dependency Matrix가 구현 순서와 blocking 관계를 설명한다.
- 각 Sprint의 예상 code ownership이 현재 Repository module 기준으로 제안된다.
- Offline, Unit, Targeted Device, Shadow와 Full Run 검증 수준이 Sprint별로 정의된다.
- P0/P1 Risk Matrix와 mitigation이 정의된다.
- 실패 Sprint별 rollback boundary와 보존/금지 기능이 명확하다.
- Sprint success metric이 architecture gate와 연결된다.
- M1-M4 completion condition이 검증 가능한 형태로 정의된다.
- Sprint 1-4에서 Legacy authority와 reporting-only 원칙을 유지한다.
- M4가 Controlled Routing 실행이 아니라 readiness 판단임이 명확하다.
- Legacy Removal과 production rollout이 Non-Goal로 분리된다.
- 다음 Sprint는 이전 Sprint exit criteria 통과 전 시작하지 않는다.

## 13. Sprint 1 Readiness Assessment

현재 판단은 `Conditional Go`다.

설계 측면에서는 Inventory schema, lifecycle, risk와 acceptance criteria가 이미
[V10 Device Inventory Design](v10-device-inventory-design.md)에 정의되어 있어 Sprint 1
구현 범위가 충분히 명확하다.

다만 Sprint 1 시작 전 Sprint 0에서 다음 항목을 완료해야 한다.

- representative helper dump fixture와 duplicate/scroll edge case 확보
- current Legacy baseline unit/full run 기록
- inventory schema/version과 artifact output 위치 고정
- default-off/reporting-only flag와 rollback owner 확정
- targeted device/account/location validation matrix 확정

이 준비가 완료되면 Sprint 1은 구현 가능한 상태다. 하나라도 누락되면 Inventory
coverage와 regression을 객관적으로 판정할 기준이 없으므로 시작하지 않는다.
