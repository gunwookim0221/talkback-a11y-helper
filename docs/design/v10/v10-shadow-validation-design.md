# V10 Shadow Validation Design

| Metadata | Value |
| --- | --- |
| Status | Completed |
| Phase | V10 Phase 4 |
| Owner | TalkBack Automation |
| Last Updated | 2026-06-30 |
| Depends On | [V10 Policy Mapping Design](v10-policy-mapping-design.md) |
| Related Documents | [V10 Overview](v10-overview.md), [V10 Phase Plan](v10-phase-plan.md), [V10 Quick Plugin Identify Design](v10-quick-plugin-identify-design.md), [V10 Implementation Roadmap](v10-implementation-roadmap.md) |
| Next | [V10 Implementation Roadmap](v10-implementation-roadmap.md) |

## 1. Purpose

Shadow Validation은 Legacy Display Name Routing과 V10 Capability Routing의 결정을
같은 runtime card에 대해 비교하고, V10 mapping이 Controlled Routing으로 진입할
준비가 되었는지 판정하는 Operation Contract다.

V10을 바로 production routing에 사용하지 않는 이유는 다음과 같다.

- capability signature와 confidence threshold는 실제 account, locale, app version,
  device model에서 검증되어야 한다.
- Legacy와 V10의 결과가 같다는 사실만으로 둘 중 어느 쪽이 실제로 맞는지 증명되지
  않는다.
- unknown, ambiguous, restoration failure와 같은 operational failure를 충분히
  관찰하기 전에 routing을 바꾸면 잘못된 Scenario Policy가 실행될 수 있다.
- 전체 평균이 좋아도 특정 plugin family나 locale에서 치명적인 mismatch가 숨을 수
  있다.

Shadow의 역할은 새로운 routing 결정을 production에 적용하는 것이 아니라, 기존
Legacy 결과를 authoritative baseline으로 유지하면서 V10 decision과 evidence를
reporting-only로 축적하는 것이다.

Phase 4에서의 Promotion은 Legacy 제거를 뜻하지 않는다. 특정 plugin family와
version cohort가 Phase 5 Controlled Routing 후보가 될 수 있다는 승인만 의미한다.

## 2. Architecture

Shadow에서는 두 decision path를 논리적으로 병렬 평가한다. 동일 card에 대해 두
Traversal을 실행하는 구조가 아니다. Legacy가 운영 baseline이고 V10은 scenario
selection 결과만 계산한다.

```text
                           +--------------------------+
                           | Runtime Device Inventory |
                           +-------------+------------+
                                         |
                    +--------------------+--------------------+
                    |                                         |
                    v                                         v
        +--------------------------+              +------------------------+
        | Legacy Display Name      |              | Quick Plugin Identify  |
        | Routing                  |              +-----------+------------+
        +------------+-------------+                          |
                     |                                        v
                     v                            +------------------------+
        +--------------------------+              | V10 Policy Mapping     |
        | Legacy Scenario          |              +-----------+------------+
        +------------+-------------+                          |
                     |                                        v
                     |                            +------------------------+
                     |                            | V10 Scenario Decision  |
                     |                            +-----------+------------+
                     |                                        |
                     +--------------------+-------------------+
                                          v
                              +--------------------------+
                              | Scenario Comparison      |
                              +------------+-------------+
                                           |
                              +------------+-------------+
                              | Metrics + Artifacts      |
                              +------------+-------------+
                                           |
                              +------------+-------------+
                              | Promotion / Hold / Block |
                              +--------------------------+
```

Legacy와 V10은 같은 `inventory_id`와 `runtime_card_id`를 사용해야 한다. 서로 다른
card 또는 context의 결과를 비교하면 해당 record는 `FAILED`다.

## 3. Shadow Lifecycle

```text
Inventory
-> Quick Identify
-> Policy Mapping
-> Legacy Routing Evaluation
-> Scenario Compare
-> Metrics Aggregation
-> Artifact Storage
-> Promotion Evaluation
```

### Inventory

비교 단위가 될 runtime card와 account/location/filter context를 고정한다. partial,
stale 또는 ambiguous Inventory 상태를 기록한다.

### Quick Identify

plugin 화면의 structural evidence와 candidate confidence를 생성하고 Inventory
context로 복귀한다. restoration 실패는 이후 Legacy 비교를 강행하지 않고
`FAILED`로 종료한다.

### Policy Mapping

Quick Identify Result를 versioned registry에 적용하여 V10 scenario decision을
생성한다. Shadow Mode에서는 `v10_route` 후보여도 traversal을 시작하지 않는다.

### Legacy Routing Evaluation

현재 `target_stable_labels`와 exact normalized display-name match를 사용해 Legacy
scenario와 locator 결과를 산출한다. 비교를 위해 결과를 계산하지만 현재 운영
동작을 V10 결과로 덮어쓰지 않는다.

### Compare And Aggregate

동일 runtime card에 대한 scenario, plugin type, decision, confidence, fallback 및
failure context를 비교한다. row-level result를 먼저 결정하고, plugin family와
version cohort별 metric을 집계한다.

### Store And Evaluate

raw evidence reference, comparison row, summary와 promotion decision을 분리 저장한다.
Promotion gate는 artifact completeness와 sample diversity를 확인한 후 평가한다.

## 4. Comparison Model

### 4.1 Comparison Unit

기본 comparison unit은 다음 key로 식별되는 하나의 shadow attempt다.

```text
shadow_run_id
+ inventory_id
+ runtime_card_id
+ identify_run_id
+ selection_id
```

같은 card를 반복 실행한 결과는 안정성 관찰에는 사용할 수 있지만 독립적인 device
표본으로 중복 계산하지 않는다. promotion sample은 account/location/device
fingerprint를 익명화하여 distinct sample과 repeated run을 구분해야 한다.

### 4.2 Compared Dimensions

| Dimension | Legacy Value | V10 Value | Comparison Purpose |
| --- | --- | --- | --- |
| Runtime Card | display-name locator가 선택한 card | Inventory `runtime_card_id` | 같은 대상 비교 여부 |
| Scenario | legacy scenario ID | mapped scenario ID | 핵심 agreement |
| Plugin Type | scenario에서 역산한 family hint | identified canonical type | family consistency |
| Decision | route/not available | route/shadow/fallback/skip | 실행 가능성 차이 |
| Confidence | 별도 classifier confidence 없음 | identify score/band | V10 evidence strength |
| Locator | stable display-name exact match | Inventory multi-signal descriptor | entry dependency 차이 |
| Fallback | legacy 자체가 baseline | legacy fallback reason | V10 독립성 측정 |
| Inventory | 암묵적 visible card search | explicit scope/completeness | 후보 coverage 확인 |
| Unknown | card/scenario 미발견 | identify/mapping unknown | unresolved 원인 분리 |
| Ambiguous | duplicate display-name target | multiple candidate/mapping conflict | unsafe selection 탐지 |
| Failure | entry/runtime failure | open/capture/restore/mapping failure | operational safety |
| Runtime | legacy decision/entry duration | identify+mapping+restore duration | 비용과 timeout 위험 |
| Version | scenario/config 기준 | identify/registry/mapping versions | 재현 가능한 cohort 구성 |

### 4.3 Comparison Principles

- scenario ID exact agreement를 기본 MATCH 기준으로 사용한다.
- plugin family agreement만 있고 scenario가 다르면 MATCH로 올리지 않는다.
- Legacy가 scenario를 찾지 못하고 V10만 찾은 경우는 promotion opportunity이지만
  자동 정답으로 간주하지 않는다.
- Legacy와 V10이 같은 scenario를 선택해도 manual/adjudicated ground truth 표본 없이는
  Routing Accuracy를 확정하지 않는다.
- failure와 unresolved result를 denominator에서 제거해 Match Rate를 높이지 않는다.
- overall metric 외에 plugin family, locale, app version, device model cohort를 각각
  평가한다.

## 5. Comparison Results

### 5.1 Result Semantics

- `MATCH`: Legacy와 V10이 같은 runtime card에 대해 같은 scenario를 선택했다.
- `MISMATCH`: 양쪽이 concrete scenario를 선택했지만 scenario가 다르다.
- `UNKNOWN`: 한쪽 이상이 scenario를 결정하지 못했으며 복수 후보 충돌은 아니다.
- `AMBIGUOUS`: card, identify candidate 또는 policy mapping이 둘 이상으로 남았다.
- `FAILED`: lifecycle, artifact, context 또는 restoration 문제로 비교 자체가 유효하지
  않다.

각 result는 `reason_code`를 가져야 한다. 예를 들어 UNKNOWN은
`legacy_unmapped_v10_candidate`, `identify_unknown`, `registry_miss`를 구분한다.

### 5.2 Comparison Matrix

| Legacy | V10 | Result | Action |
| --- | --- | --- | --- |
| Scenario A | Scenario A / identified | `MATCH` | metric 반영, 표본 adjudication 후보 |
| Scenario A | Scenario B / identified | `MISMATCH` | 해당 family promotion 즉시 block, manual triage |
| Scenario A | unknown | `UNKNOWN` | legacy 유지, identify evidence 보강 |
| Scenario A | registry miss/disabled | `UNKNOWN` | legacy 유지, registry readiness 검토 |
| Scenario A | multiple candidates | `AMBIGUOUS` | legacy 유지 조건 검증, V10 promotion block |
| no scenario | Scenario A / identified | `UNKNOWN` | `legacy_unmapped_v10_candidate`로 분리, ground truth 검토 |
| no scenario | unknown | `UNKNOWN` | `both_unresolved`, inventory/evidence 검토 |
| duplicate legacy targets | Scenario A | `AMBIGUOUS` | locator ambiguity 해결 전 promotion 제외 |
| Scenario A | failed | `FAILED` | run 제외가 아니라 failure metric 반영, restoration 점검 |
| wrong runtime card | any | `FAILED` | 비교 폐기, Inventory/locator incident 처리 |
| any | restoration failed | `FAILED` | Inventory invalidate, 후속 traversal 금지 |

### 5.3 Follow-up Policy

- MATCH는 자동 promotion이 아니라 clean evidence 한 건이다.
- MISMATCH는 원인이 Legacy 오류로 확인되더라도 먼저 block하고 adjudication 결과를
  기록한 뒤 별도 revision에서 재평가한다.
- UNKNOWN과 AMBIGUOUS는 fail-closed이며 V10 traversal에 사용하지 않는다.
- FAILED는 성공률 denominator에서 제외하지 않고 별도 failure rate에 반드시 포함한다.

## 6. Metrics

### 6.1 Metric Table

모든 metric은 overall과 plugin family별로 계산하며, 필요하면 locale/app
version/device model cohort로 분리한다.

| Metric | Definition | Denominator | Interpretation |
| --- | --- | --- | --- |
| `Match Rate` | MATCH count / comparable count | MATCH + MISMATCH | 두 routing의 scenario agreement |
| `Mismatch Rate` | MISMATCH count / comparable count | MATCH + MISMATCH | concrete wrong-route risk signal |
| `Unknown Rate` | UNKNOWN count / eligible attempts | all eligible shadow attempts | unresolved identification/mapping 비율 |
| `Ambiguous Rate` | AMBIGUOUS count / eligible attempts | all eligible shadow attempts | unsafe multi-candidate 비율 |
| `Failure Rate` | FAILED count / attempted comparisons | all attempted shadow comparisons | lifecycle/artifact/context 안정성 |
| `Fallback Rate` | legacy fallback selections / mapping attempts | valid mapping attempts | V10 독립성 부족 정도 |
| `Shadow Coverage` | complete valid comparison records / eligible inventory cards | eligible inventory cards | 실제 검증 범위 |
| `Routing Accuracy` | adjudicated correct V10 routes / adjudicated V10 routes | manually verified sample | agreement가 아닌 실제 correctness |
| `Legacy Accuracy` | adjudicated correct legacy routes / adjudicated legacy routes | manually verified sample | baseline 오류 분리 |
| `Confidence Distribution` | confidence band/score histogram | valid identify results | score drift와 low-confidence concentration |
| `Promotion Eligible Rate` | gate를 통과한 V10 candidates / valid mapping attempts | valid mapping attempts | controlled routing 가능 범위 |
| `Restoration Success Rate` | verified Inventory restores / card opens | successful card opens | identify lifecycle safety |
| `Inventory Resolution Rate` | unique actionable runtime cards / inventory items | eligible inventory items | card selection 안정성 |
| `Mapping-only Discovery Rate` | legacy missing + adjudicated V10 correct / eligible attempts | eligible attempts | display-name dependency 제거 효과 |
| `Latency Overhead` | identify+mapping+restore elapsed time distribution | completed identify attempts | Shadow/향후 routing 비용 |
| `Artifact Completeness` | required artifact fields가 완전한 records / attempts | all attempts | audit 가능성 |

### 6.2 Denominator Rules

- MATCH/MISMATCH만으로 Match Rate를 계산하되 Unknown/Ambiguous/Failed는 각각 별도
  gate로 반드시 평가한다.
- `no comparable records`를 100% match로 표현하지 않는다.
- partial Inventory와 unsupported version은 별도 cohort로 표시하고 promotion
  denominator에 조용히 포함하거나 제외하지 않는다.
- 반복 실행은 reliability metric에는 포함할 수 있지만 distinct device coverage로
  중복 계산하지 않는다.
- family별 sample이 부족하면 overall 수치가 높아도 해당 family는 `INSUFFICIENT_DATA`다.
- Routing Accuracy는 ground truth adjudication이 있는 표본에만 사용한다.

## 7. Shadow Artifacts

Artifact 이름과 필드는 제안 수준이며 구현 contract는 별도로 확정한다.

### 7.1 Shadow Artifact Matrix

| Artifact | Purpose | Consumer |
| --- | --- | --- |
| `shadow_validation.json` | run metadata, row-level comparison, evidence/version reference 보존 | automation, audit, debugging |
| `routing_compare.csv` | card별 Legacy/V10 scenario와 result를 표 형태로 분석 | QA, data review |
| `shadow_summary.md` | metric, cohort, 주요 mismatch/unknown을 사람이 읽는 형태로 요약 | QA, engineering |
| `promotion_report.md` | gate별 pass/fail, blocking reason, 승인 범위를 기록 | release owner, operations |
| `confidence_drift.json` | baseline 대비 confidence/evidence-source drift 기록 | classifier owner, monitoring |
| `shadow_incidents.json` | mismatch, restoration failure, invalid context incident 목록 | triage owner |

### 7.2 Proposed Record Fields

`shadow_validation.json`은 다음 범주의 필드를 포함하는 것이 적절하다.

- run: `shadow_run_id`, timestamps, mode, status
- context: anonymized account/location, locale, app/helper/device versions
- identity: inventory/runtime card/identify/selection IDs
- legacy: scenario, locator, duplicate count, availability
- V10: plugin type, decision, scenario, confidence, fallback
- comparison: result, reason code, adjudication status
- lifecycle: open, stabilize, snapshot, restore status와 durations
- versions: inventory, identify, policy, registry, mapping, routing, shadow contract
- evidence: snapshot references와 evidence IDs
- promotion: eligibility, gate failures, scope

Raw helper/XML snapshot을 summary artifact에 중복 저장하지 않고 reference로 연결한다.
민감한 account/device 정보는 익명화한다.

## 8. Promotion Gate

### 8.1 Promotion Philosophy

Promotion은 단일 전체 수치가 아니라 다음 조건의 교집합이다.

1. **Correctness**: confirmed wrong scenario가 없어야 한다.
2. **Completeness**: unknown/ambiguous/failure가 낮고 원인이 설명 가능해야 한다.
3. **Coverage**: 충분히 다양한 실제 환경과 card를 검증해야 한다.
4. **Stability**: 여러 연속 validation window에서 결과가 유지되어야 한다.
5. **Traceability**: 동일한 version cohort와 완전한 artifact로 재현 가능해야 한다.
6. **Reversibility**: Phase 5에서 즉시 Legacy로 되돌릴 수 있어야 한다.

Promotion은 plugin family 단위로 판단한다. 전체 Match Rate가 높아도 특정 family가
gate를 통과하지 못하면 해당 family는 Legacy에 남는다.

### 8.2 Promotion Matrix

아래 target은 초기 제안값이며 corpus 규모와 위험도에 따라 family별로 더 엄격하게
조정할 수 있다.

| Metric | Target | Required | Notes |
| --- | --- | --- | --- |
| Match Rate | `>= 99%` | Yes | 충분한 comparable sample 전제 |
| Mismatch Rate | `0% confirmed` | Yes | confirmed wrong scenario는 허용하지 않음 |
| Routing Accuracy | `100% in adjudicated promotion sample` | Yes | Legacy agreement만으로 대체 불가 |
| Unknown Rate | `<= 1%` | Yes | 원인이 known/contained여도 추세 악화 금지 |
| Ambiguous Rate | `0% in promotable scope` | Yes | ambiguous family/card는 scope에서 제외하거나 해결 |
| Failure Rate | `0% critical`, near-zero recoverable | Yes | restoration/context failure는 별도 critical gate |
| Shadow Coverage | `>= 95%` | Yes | eligible inventory 기준; excluded reason 공개 |
| Restoration Success Rate | `100% in promotable scope` | Yes | traversal 시작 context 안전성 |
| Artifact Completeness | `100% required fields` | Yes | audit 불가능한 run은 promotion evidence가 아님 |
| Confidence Distribution | High/Definite가 promotable scope를 설명 | Yes | 평균 score보다 band/source quality를 검토 |
| Fallback Rate | 지속 감소하고 residual 원인 설명 가능 | Conditional | fallback 존재 자체보다 범위와 추세가 중요 |
| Sample Diversity | agreed account/locale/model/app-version strata 충족 | Yes | 단일 계정 반복으로 충족 금지 |
| Clean Windows | 연속된 복수 validation window 통과 | Yes | 하루 또는 한 번의 clean run으로 승격 금지 |
| Version Stability | 평가 window 내 contract/mapping version 고정 | Yes | version 변경 시 새 cohort로 재검증 |

### 8.3 Promotion Decision

Promotion verdict는 다음 중 하나다.

- `PROMOTABLE`: 특정 family/version scope가 모든 required gate를 통과
- `HOLD`: 오류는 없지만 sample, coverage 또는 clean window가 부족
- `BLOCKED`: mismatch, critical failure 또는 unresolved ambiguity 존재
- `INSUFFICIENT_DATA`: denominator나 cohort diversity가 부족

승격 승인에는 자동 metric 결과와 owner review가 모두 필요하다. threshold 통과만으로
default routing을 자동 전환하지 않는다.

## 9. Rollback Gate

Phase 4에서는 Legacy가 이미 authoritative이므로 rollback은 V10 promotion eligibility를
취소하고 Legacy 유지 상태로 돌아가는 것을 뜻한다. Phase 5 이후에는 해당 family의
V10 routing을 disable하고 Legacy fallback으로 복귀하는 같은 gate를 사용한다.

### 9.1 Rollback Matrix

| Condition | Action | Severity |
| --- | --- | --- |
| confirmed scenario MISMATCH 1건 이상 | 해당 family promotion block, Legacy 유지, incident triage | Critical |
| wrong runtime card 또는 cross-device comparison | run 무효화, Inventory/locator scope block | Critical |
| Inventory restoration 실패 | V10 attempt 중단, Inventory invalidate, affected scope block | Critical |
| app crash/unsafe navigation | 전체 affected version cohort block | Critical |
| required Scenario Policy 누락/disabled/version mismatch | mapping disable, Legacy 유지 | High |
| Unknown Rate가 baseline/control limit를 초과 | promotion hold, evidence/source 조사 | High |
| Ambiguous result 신규 발생 또는 증가 | affected family block 또는 scope 축소 | High |
| High/Definite 비율 급락 | confidence drift incident, version cohort 재검증 | High |
| helper/XML source availability 급락 | promotion hold, capture pipeline 조사 | High |
| Shadow Coverage가 target 아래로 하락 | promotion hold, missing scope 공개 | Medium |
| Fallback Rate 급증 | routing independence 조사, promotion hold | Medium |
| artifact/version field 누락 | 해당 run을 promotion evidence에서 제외하고 재수집 | High |
| 새로운 app/helper version 감지 | 기존 approval 상속 금지, 새 shadow cohort 시작 | High |
| sample diversity 또는 clean window 부족 | `HOLD`/`INSUFFICIENT_DATA` 유지 | Medium |

Critical condition은 aggregate threshold와 무관하게 즉시 gate를 닫는다. 문제 run을
단순히 denominator에서 제거해 promotion 상태를 유지하면 안 된다.

## 10. Confidence Drift

Confidence drift는 score 평균만 비교하지 않는다. plugin family, app version, locale,
device model과 evidence source availability를 함께 본다.

### 10.1 Baseline

Promotion 검토 시 다음 baseline을 immutable cohort로 저장한다.

- confidence score distribution과 band 비율
- top/second candidate margin distribution
- helper/XML cross-source confirmation rate
- required structural evidence occurrence rate
- unknown/ambiguous reason 분포
- identify latency와 restoration success
- 사용된 identify contract와 evidence registry version

### 10.2 Drift Rules

- contract, mapping, app/helper version이 바뀌면 기존 baseline과 합치지 않고 새 cohort로
  시작한다.
- High에서 Medium/Unknown으로 이동하는 band transition을 직접 추적한다.
- 평균이 같아도 특정 locale/model에서 tail confidence가 하락하면 drift로 본다.
- confidence 상승도 새로운 중복 evidence 가산이나 threshold 오류일 수 있으므로
  무조건 개선으로 간주하지 않는다.
- source 하나가 사라졌는데 score가 유지되면 scoring quality gate를 재검토한다.
- sample이 작은 cohort는 drift 결론 대신 `INSUFFICIENT_DATA`로 둔다.

Drift threshold는 baseline 분산과 family risk에 맞춰 calibration한다. 고정된 전역
숫자 하나로 모든 family를 판정하지 않는다.

## 11. Shadow Reporting

QA Frontend에는 raw score보다 운영 판단에 필요한 정보를 우선 노출하는 것이
적절하다. 이 문서는 UI 구현을 포함하지 않는다.

권장 정보:

- overall status: `PROMOTABLE`, `HOLD`, `BLOCKED`, `INSUFFICIENT_DATA`
- family별 MATCH/MISMATCH/UNKNOWN/AMBIGUOUS/FAILED count와 rate
- Shadow Coverage, fallback, restoration success
- confidence band distribution과 baseline drift
- mapping-only candidates와 unresolved duplicate cards
- gate별 pass/fail 및 blocking reason
- policy/registry/mapping/identify/shadow versions
- locale, app version, model cohort coverage
- latest critical incident와 adjudication status
- row drill-down용 Legacy/V10 scenario, evidence refs, reason code

UI는 MATCH를 correctness로 표현하지 않아야 한다. `Agreement`와 adjudicated
`Routing Accuracy`를 별도 지표로 표시해야 한다.

## 12. Operational Strategy

### Shadow Duration

Shadow 기간을 고정 일수만으로 종료하지 않는다. 각 promotable family가 합의된 distinct
sample diversity, 복수 clean window, version stability와 required gate를 충족할
때까지 유지한다.

### Default Promotion

Phase 4 승격은 바로 V10 default가 아니라 Phase 5 Controlled Routing 진입 승인이다.
초기에는 family별 High/Definite case와 제한된 cohort만 V10 routing 대상으로 삼고,
Legacy fallback과 kill switch를 유지한다.

### Legacy Removal

Legacy는 다음 조건을 모두 만족한 family부터 단계적으로 축소한다.

- Shadow gate 통과
- Controlled Routing 기간 동안 confirmed mismatch와 critical failure 없음
- fallback/rollback이 실제로 검증됨
- 새 app/helper version에 대한 재검증 절차 운영
- unknown/ambiguous device가 안전하게 skip됨
- 운영 owner가 family별 closure를 승인

모든 family를 동시에 제거하지 않는다. 장기적으로도 unsupported/unknown family를
위해 Legacy 또는 manual routing이 필요할 수 있다. Display name fallback 제거는
V10 default 승격과 별도의 closure decision이다.

## 13. Version Tracking

모든 shadow record와 summary는 최소 다음 version을 함께 기록한다.

| Version | Purpose |
| --- | --- |
| `policy_version` | 선택 대상 Scenario Policy behavior |
| `registry_version` | capability-to-policy registry contract |
| `mapping_revision` | 실제 mapping/discriminator content |
| `identify_contract_version` | Quick Identify input/output semantics |
| `shadow_validation_version` | comparison, metric, promotion contract |

추가로 `routing_rule_version`, `inventory_schema_version`, app/helper version을 기록하면
cohort 재현성이 높아진다.

Version 원칙:

- 서로 다른 version cohort의 metric을 하나의 promotion 결과로 단순 합산하지 않는다.
- mapping 또는 identify contract가 변경되면 영향받는 family의 clean window를 다시
  시작한다.
- `shadow_validation_version`이 denominator/result semantics를 바꾸면 이전 report와
  직접 비교하지 않는다.
- promotion report는 사용한 모든 version과 evaluation window를 고정해 기록한다.
- 과거 artifact를 새 version 결과로 재해석할 경우 원본 verdict를 덮어쓰지 않고
  별도 re-evaluation record를 만든다.

## 14. Out Of Scope

이 문서는 다음을 구현하거나 변경하지 않는다.

- Traversal Engine 또는 traversal policy
- Quick Identify classifier와 evidence extraction
- Policy Mapping registry 구현
- Device Inventory 또는 Plugin Discovery 구현
- Scenario Config
- QA Frontend 구현
- coverage 수집/판정 변경
- production routing 전환
- kill switch/rollback mechanism 구현
- artifact file format의 최종 고정
- 수동 ground truth adjudication 도구

## 15. Acceptance Criteria

Phase 4 Operation Contract는 다음 조건을 모두 만족하면 완료로 판단한다.

- Legacy와 V10이 같은 runtime card를 비교한다는 identity contract가 정의된다.
- 두 traversal을 실행하는 것이 아니라 scenario decision을 병렬 비교한다는 경계가
  명확하다.
- Inventory부터 promotion evaluation까지 Shadow Lifecycle이 정의된다.
- Scenario, plugin type, confidence, decision, fallback, runtime, inventory와 failure
  비교 항목이 정의된다.
- MATCH, MISMATCH, UNKNOWN, AMBIGUOUS, FAILED의 의미와 후속 action이 Comparison
  Matrix로 정의된다.
- Match/Mismatch/Unknown/Ambiguous/Failure/Fallback/Coverage/Accuracy/Confidence/
  Promotion metric과 denominator가 정의된다.
- agreement와 adjudicated Routing Accuracy가 구분된다.
- plugin family와 version cohort별 gate가 전체 평균보다 우선한다.
- Shadow Artifact Matrix와 최소 field 범주가 정의된다.
- Promotion Matrix가 correctness, completeness, coverage, stability, traceability,
  reversibility 원칙을 반영한다.
- confirmed mismatch와 critical lifecycle failure가 threshold와 무관한 block 조건이다.
- Rollback Matrix에 즉시 block, hold와 revalidation 조건이 정의된다.
- confidence drift baseline, version split과 band transition 원칙이 정의된다.
- QA reporting에서 agreement와 accuracy를 분리하도록 제안한다.
- Shadow 기간, Controlled Routing 진입, Legacy closure가 서로 다른 단계로 정의된다.
- 필수 5개 version과 cohort 분리 원칙이 정의된다.
- unknown, ambiguous, failed가 V10 traversal을 시작하지 않는 fail-closed 원칙을
  유지한다.

Phase 4 완료는 V10 production promotion을 의미하지 않는다. 완료 조건은 Shadow
실행 결과를 안전하게 비교하고, 증거가 충분한 family만 Phase 5 Controlled Routing
후보로 판정할 수 있는 운영 계약이 명확한 것이다.
