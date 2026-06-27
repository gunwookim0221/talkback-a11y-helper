# Audit V7 Focusable Coverage Design

## 1. Status

이 문서는 V8 완료 기준으로 갱신된 V7/V8 coverage-driven audit 설계 문서다.

초기 V7 문서가 다루던 범위는:

- focusable discovery
- focusable coverage
- taxonomy
- reporting-only shadow visibility

현재 구현은 그 위에 다음 단계를 추가로 완성했다.

- coverage probe plan
- runtime probe execution
- late focus verification
- probe validation
- shadow reporting
- promotion policy
- production promotion
- conservative deduplication
- aggregate artifacts
- QA Frontend coverage probe reporting

즉, V7의 "focusable coverage 설명 계층"은 현재 V8의 end-to-end pipeline으로 확장되었다.

## 2. Final Architecture

현재 파이프라인은 아래 순서로 동작한다.

```text
Traversal
↓
Focusable Discovery
↓
Focusable Coverage
↓
Coverage Probe Plan
↓
Runtime Probe
↓
Late Focus Verification
↓
Probe Validation
↓
Shadow Reporting
↓
Promotion Policy
↓
Production Promotion
↓
Deduplication
↓
Excel
↓
QA Frontend
```

핵심 원칙:

- traversal row 생성 규칙은 유지한다.
- `PASS` / `WARN` / `FAIL` 의미는 바꾸지 않는다.
- probe 결과는 별도 artifact와 shadow row로 먼저 표현한다.
- production row 승격은 conservative policy로만 수행한다.

## 3. Focusable Discovery And Coverage

### 3.1 Discovery 목적

V7/V8의 첫 질문은 여전히 동일하다.

- 현재 화면에서 TalkBack이 방문 가능하거나 의미 있게 읽을 수 있는 focusable node는 무엇인가?
- 그 node가 persisted row로 설명되었는가?

### 3.2 Discovery 입력

현재 inventory는 아래 evidence를 정규화해 구성한다.

- focus payload
- helper snapshot
- dump tree nodes
- actionable descendant metadata

### 3.3 Coverage 출력

`*.focusable_coverage.json`의 canonical item은 최소한 아래 축을 가진다.

- label
- bounds
- class / view id
- taxonomy
- coverage status
- coverage reason
- scenario / tab scope

Coverage status:

- `COVERED`
- `MISSED`
- `UNKNOWN`

현재 `UNKNOWN`은 "관련 row evidence는 있지만 coverage를 강하게 증명하지 못함"을 뜻한다.
대표적인 예는 `related_bounds_only` 같은 weak relation이다.

### 3.4 Taxonomy

현재 taxonomy는 reporting and probe planning에 사용된다.

- `REQUIRED`
- `REVIEW`
- `OPTIONAL`
- `IGNORE`

기본 운영 의미:

- `REQUIRED`: 상태값, 센서값, 현재 값처럼 사용자 의미가 직접적인 항목
- `REVIEW`: 버튼, chevron, graph/history 같은 검토 대상 affordance
- `OPTIONAL`: 중복 설명 또는 보조 텍스트
- `IGNORE`: chrome, container root, 노이즈

## 4. Coverage Probe Planning

Coverage만으로는 "row 미존재"와 "실제 TalkBack focus 미검증"을 분리하기 어렵다.
그래서 현재 구현은 coverage artifact에서 별도 probe plan을 만든다.

현재 후보 생성은 보수적으로 유지된다.

```text
taxonomy == REQUIRED
AND
coverage_status == MISSED or UNKNOWN
```

실제 실행 의도는 coverage reason에 따라 분기된다.

- 명확한 miss 재검증
- related-bounds 기반 representative/container probe

Plan artifact는 row-like candidate record와 summary를 포함한다.

## 5. Runtime Probe Flow

Runtime Probe는 Helper APK의 `FOCUS_IN_BOUNDS` primitive를 사용한다.

현재 probe method:

- `helper_focus_in_bounds_scroll_retry`

현재 probe engine 정책:

1. candidate bounds 또는 promoted target bounds를 결정한다.
2. foreground / screen / keyguard 상태를 점검한다.
3. `focus_in_bounds(bounds)`를 시도한다.
4. helper success면 capture된 focus/speech/text를 저장한다.
5. helper success가 아니어도 late verification polling을 잠시 수행한다.
6. retryable failure면 scroll 후 재시도한다.

현재 late verification success source:

- `LATE_FOCUS_VERIFIED`
- `LATE_SPEECH_VERIFIED`
- `LATE_VISIBLE_TEXT_VERIFIED`

현재 primary helper success source:

- `HELPER_SUCCESS`

## 6. Target Promotion During Probe

probe는 leaf text node 자체보다 enclosing actionable container가 더 실제 TalkBack target에
가깝다고 판단되는 경우 bounds target을 승격할 수 있다.

현재 target strategy:

- `original_bounds`
- `promote_to_enclosing_actionable_container`

이 승격은 traversal row semantics를 바꾸지 않는다.
probe 실행 타겟을 현실적인 focus target으로 조정하는 runtime policy다.

## 7. Environment Guards

Runtime Probe는 실행 안정성을 위해 screen/app guards를 갖는다.

현재 주요 guard:

- foreground가 target app이 아니면 skip
- `SCREEN_OFF`면 skip
- keyguard active면 skip
- `com.android.systemui` foreground + screen interruption은 crash가 아니라 environment interruption으로 분류

실행 안정성 보완:

- scenario isolation
- aggregate append 방식
- keep-awake lifecycle

keep-awake는 QA Frontend batch run 시작 시 `adb shell svc power stayon true`를 적용하고,
종료 후 기존 값을 복원하는 운영 경로를 사용한다.

## 8. Probe Validation

Probe validation은 traversal mismatch와 별개의 V8 validation layer다.

입력:

- captured speech
- captured visible text
- probe success metadata

출력 status:

- `MATCH`
- `PARTIAL_MATCH`
- `MISMATCH`
- `NO_SPEECH_OR_TEXT`
- `NOT_VALIDATED`

현재 특징:

- numeric value match 허용
- exact normalized match 허용
- token overlap 기반 partial match 분리
- short-token false positive 억제

## 9. Shadow Reporting

Validation 결과는 먼저 result sheet에 shadow row로 append된다.

row source:

- `COVERAGE_PROBE_SHADOW`

shadow row 조건:

- validation status가 `MATCH` 또는 `PARTIAL_MATCH`
- probe success가 true

중요한 점:

- shadow row는 기존 traversal row를 대체하지 않는다.
- shadow row는 production verdict를 바꾸지 않는다.

## 10. Promotion Policy

Promotion policy는 shadow row가 production 승격 후보인지 판정하는 별도 계층이다.

현재 `PROMOTABLE` 조건:

- `probe_success == true`
- `validation_status == MATCH`
- `probe_success_source in {HELPER_SUCCESS, LATE_FOCUS_VERIFIED}`
- `probe_skipped == false`

그 외는 모두 `NOT_PROMOTABLE`.

현재 대표 reason:

- `exact_probe_match`
- `partial_validation`
- `probe_failed`
- `screen_skip`
- `environment_skip`
- `unsupported_success_source`

## 11. Production Promotion And Dedup

Promotion policy가 `PROMOTABLE`이어도 즉시 traversal row를 수정하지는 않는다.

현재 단계:

1. shadow row 생성
2. promotion eligibility 판정
3. 기존 production row와 identity 비교
4. 중복이 아니면 promoted row append
5. 중복이면 shadow row에 dedup skip metadata만 기록

promoted row source:

- `COVERAGE_PROBE_PROMOTED`

promotion dedup 상태:

- `PROMOTED`
- `SKIPPED`
- `NOT_APPLICABLE`

현재 production promotion은 conservative append-only 정책이다.

## 12. Aggregate Artifacts

V8 완료 구현은 per-scenario file과 aggregate file을 함께 만든다.

### 12.1 Artifact list

`*.focusable_inventory.json`

- 목적: raw inventory evidence
- producer: `tb_runner/collection_flow.py`
- consumer: coverage calculation, probe target promotion
- lifecycle: scenario execution 중 생성, per-run 기준 파일

`*.focusable_coverage.json`

- 목적: canonical focusable item, taxonomy, coverage status
- producer: `tb_runner/collection_flow.py`
- consumer: probe plan builder, shadow/analysis
- lifecycle: scenario execution 중 생성

`*.coverage_probe_plan.json`

- 목적: coverage 기반 runtime probe candidate plan
- producer: `tb_runner/collection_flow.py`
- consumer: `tb_runner/coverage_probe_engine.py`
- lifecycle: per-scenario 실행 직전 또는 coverage 생성 직후 저장

`*.coverage_probe_results.json`

- 목적: scenario 단위 probe execution 결과
- producer: `tb_runner/coverage_probe_engine.py`
- consumer: probe validation, manual debug
- lifecycle: scenario별 overwrite

`*.coverage_probe_results.aggregate.json`

- 목적: run 전체 scenario probe execution aggregate
- producer: `tb_runner/coverage_probe_engine.py`
- consumer: QA Frontend summary, docs/debug
- lifecycle: scenario별 append aggregate

`*.coverage_probe_validation.json`

- 목적: scenario 단위 probe validation + promotion metadata
- producer: `tb_runner/coverage_probe_validation.py`
- consumer: Excel shadow row fallback, manual debug
- lifecycle: scenario별 overwrite

`*.coverage_probe_validation.aggregate.json`

- 목적: run 전체 validation aggregate
- producer: `tb_runner/coverage_probe_validation.py`
- consumer: Excel shadow row source, QA Frontend summary
- lifecycle: scenario별 append aggregate

`*.xlsx`

- 목적: traversal rows + shadow rows + promoted rows를 포함한 운영 보고서
- producer: `tb_runner/excel_report.py`
- consumer: QA review, QA Frontend, downstream analysis
- lifecycle: final run artifact

### 12.2 Aggregate summary fields

results aggregate 주요 필드:

- `total_candidate_count`
- `total_attempted_count`
- `total_success_count`
- `total_failed_count`
- `total_screen_skipped_count`
- `total_scenario_filtered_count`

validation aggregate 주요 필드:

- `total_match_count`
- `total_partial_match_count`
- `promotable_count`
- `not_promotable_count`
- `total_screen_skipped_count`
- `total_scenario_filtered_count`

Excel promotion summary:

- `promoted_row_count`
- `promotion_dedup_skipped_count`

## 13. QA Frontend Reporting

QA Frontend는 aggregate artifact를 우선 사용한다.

fallback 순서:

1. `*.coverage_probe_validation.aggregate.json`
2. `*.coverage_probe_validation.json`

execution metrics는 results artifact에서 읽고,
validation/promotion metrics는 validation artifact에서 읽는다.

Coverage Probe summary card 주요 지표:

- Candidates
- Attempted
- Succeeded
- Failed
- Promotable
- Promoted
- Dedup Skipped
- Screen Skipped
- Scenario Filtered

상태 구분:

- artifact 없음: `available=false`, `source=none`, UI는 `Not Available`
- aggregate 있음: `available=true`, `source=aggregate`
- scenario fallback: `available=true`, `source=scenario`
- artifact는 있으나 candidate가 0: zero run으로 해석하고 별도 안내 문구 표시

## 14. Final Operational Semantics

현재 V8은 다음을 보장한다.

- traversal / mismatch / V6 shadow semantics 유지
- probe는 opt-in
- helper APK 변경 없이 runner + reporting pipeline으로 동작
- aggregate artifact 기반 batch reporting 가능
- environment interruption이 crash threshold를 불필요하게 소모하지 않음

## 15. Known Limitations

- promotion은 conservative하다.
- `PARTIAL_MATCH`는 승격하지 않는다.
- `LATE_SPEECH_VERIFIED`와 `LATE_VISIBLE_TEXT_VERIFIED`는 success로 기록되더라도 production promotion 대상이 아니다.
- cross-run learning 또는 cache 기반 probe 최적화는 지원하지 않는다.
- probe는 aggregate reporting을 제공하지만 traversal policy 자체를 self-healing 하지는 않는다.

## 16. Recommended Reading

- [V8 Coverage-Driven Traversal](/d:/Python%20test/talkback-a11y-helper/docs/design/v8-coverage-driven-traversal.md)
- [Semantic Value Shadow Audit](/d:/Python%20test/talkback-a11y-helper/docs/design/semantic-value-shadow-audit.md)
- [QA Frontend Guide](/d:/Python%20test/talkback-a11y-helper/docs/qa-frontend-guide.md)
