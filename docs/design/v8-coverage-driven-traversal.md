# V8 Coverage-Driven Traversal

## 1. Purpose

이 문서는 현재 구현 기준의 V8 primary design document다.

V8의 목적은 "TalkBack traversal 결과만으로 설명되지 않는 focusable coverage gap"을
runtime probe와 reporting pipeline으로 보강하는 것이다.

V8은 다음을 완성했다.

- focusable discovery
- coverage
- runtime probe
- late focus verification
- validation
- shadow reporting
- promotion policy
- production promotion
- deduplication
- aggregate artifacts
- QA Frontend reporting

## 2. Pipeline

```text
Traversal
↓
Focusable Discovery
↓
Coverage
↓
Probe Plan
↓
Runtime Probe
↓
Late Verification
↓
Validation
↓
Shadow
↓
Promotion Policy
↓
Production Promotion
↓
Dedup
↓
Excel
↓
QA Frontend
```

## 3. Design Rules

- runtime traversal behavior는 V8 때문에 재정의하지 않는다.
- `PASS` / `WARN` / `FAIL`은 기존 traversal quality semantics를 유지한다.
- probe는 별도 evidence layer다.
- promotion은 conservative append-only policy다.
- helper APK 수정 없이 runner/reporting layer에서 해결 가능한 문제를 우선한다.

## 4. Runtime Flow

### 4.1 Enablement

Runtime Probe는 기본 always-on이 아니다.

현재 활성화 경로:

- `TB_V8_COVERAGE_PROBE=1`
- 또는 `tb_runner/run_spec.py`에서 `enable_coverage_probe=True`
- QA Frontend batch run에서 V8 Runtime Probe toggle ON

### 4.2 Scenario lifecycle

시나리오별로 현재 순서는 다음과 같다.

1. traversal row 수집
2. focusable inventory 생성
3. focusable coverage 계산
4. coverage probe plan 저장
5. probe enabled면 scenario-isolated probe 실행
6. results 저장 및 aggregate append
7. validation 저장 및 aggregate append
8. 최종 Excel 생성 시 shadow / promoted row 반영

### 4.3 Probe mechanics

Probe는 `focus_in_bounds(bounds)`를 중심 primitive로 쓴다.

추가 정책:

- related-bounds leaf는 enclosing actionable container로 target promotion 가능
- helper failure 뒤 late verification polling 수행
- retryable failure면 scroll 후 재시도
- foreground/screen/keyguard guard로 environment skip

### 4.4 Keep-awake and interruption handling

full run 안정성을 위해 QA Frontend backend는 run 시작 시 keep-awake를 적용한다.

- 적용: `adb shell svc power stayon true`
- 종료 후 기존 값 복원

SystemUI / screen interruption policy:

- `com.android.systemui` foreground
- `SCREEN_OFF`
- keyguard / notification shade 성격의 interruption

이 경우 probe skip 또는 environment interruption으로 처리하며 app crash로 집계하지 않는다.

## 5. Artifacts

### 5.1 Focusable coverage artifacts

`*.focusable_inventory.json`

- purpose: raw focusable evidence inventory
- producer: `tb_runner/collection_flow.py`
- consumer: coverage build, probe target promotion
- lifecycle: per run / per output stem

`*.focusable_coverage.json`

- purpose: canonical focusable coverage status
- producer: `tb_runner/collection_flow.py`
- consumer: probe plan builder, review
- lifecycle: per run / per output stem

### 5.2 Probe artifacts

`*.coverage_probe_plan.json`

- purpose: candidate list for runtime probe
- producer: `tb_runner/collection_flow.py`
- consumer: `tb_runner/coverage_probe_engine.py`
- lifecycle: per scenario output

`*.coverage_probe_results.json`

- purpose: scenario probe execution result
- producer: `tb_runner/coverage_probe_engine.py`
- consumer: validation
- lifecycle: latest scenario result file

`*.coverage_probe_results.aggregate.json`

- purpose: multi-scenario probe execution aggregate
- producer: `tb_runner/coverage_probe_engine.py`
- consumer: QA Frontend summary, analysis
- lifecycle: append across scenario run

`*.coverage_probe_validation.json`

- purpose: scenario probe validation and promotion metadata
- producer: `tb_runner/coverage_probe_validation.py`
- consumer: Excel fallback
- lifecycle: latest scenario validation file

`*.coverage_probe_validation.aggregate.json`

- purpose: multi-scenario validation aggregate
- producer: `tb_runner/coverage_probe_validation.py`
- consumer: Excel shadow source, QA Frontend summary
- lifecycle: append across scenario run

### 5.3 Reporting artifact

`*.xlsx`

- purpose: traversal rows, shadow rows, promoted rows를 포함한 최종 보고서
- producer: `tb_runner/excel_report.py`
- consumer: QA review, QA Frontend, downstream reporting
- lifecycle: final run artifact

## 6. Policies

### 6.1 Coverage policy

- taxonomy 기반으로 expected node를 분류한다.
- `REQUIRED`, `REVIEW`, `OPTIONAL`, `IGNORE`를 사용한다.
- coverage status는 `COVERED`, `MISSED`, `UNKNOWN`이다.

### 6.2 Probe plan policy

현재 probe는 보수적으로 coverage gap만 겨냥한다.

- required node 중심
- missed 또는 weak-related unknown node 중심

### 6.3 Validation policy

validation status:

- `MATCH`
- `PARTIAL_MATCH`
- `MISMATCH`
- `NO_SPEECH_OR_TEXT`
- `NOT_VALIDATED`

false-positive 억제:

- short token boundary rule
- numeric value normalization

### 6.4 Promotion policy

`PROMOTABLE` 조건:

- `probe_success == true`
- `validation_status == MATCH`
- `probe_success_source in {HELPER_SUCCESS, LATE_FOCUS_VERIFIED}`
- `probe_skipped == false`

그 외는 `NOT_PROMOTABLE`.

### 6.5 Production promotion policy

shadow row가 `PROMOTABLE`이어도 기존 production row와 중복되면 append하지 않는다.

dedup 결과:

- promoted
- skipped as duplicate

현재 promoted row는 기존 row를 replace하지 않고 append된다.

## 7. Excel Reporting

result sheet에는 세 종류의 row가 공존할 수 있다.

- traversal production row
- `COVERAGE_PROBE_SHADOW`
- `COVERAGE_PROBE_PROMOTED`

shadow row:

- validation evidence를 보여 주는 reporting row
- `final_result=SHADOW`

promoted row:

- production report에 append된 승격 row
- `final_result=PASS`

추가 메타데이터:

- `probe_validation_status`
- `probe_success_source`
- `promotion_status`
- `promotion_reason`
- `promotion_applied`
- `promotion_dedup_status`
- `promotion_dedup_reason`
- `probe_target_strategy`
- `probe_intent`

## 8. QA Frontend Reporting

Coverage Probe summary card는 aggregate artifact를 우선 사용한다.

표시 지표:

- Candidates
- Attempted
- Succeeded
- Failed
- Promotable
- Promoted
- Dedup Skipped
- Screen Skipped
- Scenario Filtered

source policy:

- aggregate preferred
- scenario fallback
- artifact 없음이면 `Not Available`

UI는 backend가 재계산하지 않고 artifact 값을 그대로 사용한다.

## 9. V8 Feature Completion

실구현 완료 항목:

- coverage probe plan
- runtime probe engine
- late focus verification
- probe validation
- shadow reporting
- promotion policy
- production promotion
- dedup
- aggregate reporting
- QA Frontend summary card
- keep-awake lifecycle
- environment interruption handling
- scenario isolation

검증 상태:

- 31-scenario full run 완료
- aggregate validation 동작 확인
- promoted row / dedup skip 동작 확인
- QA Frontend coverage probe summary 표시 확인

## 10. Known Limitations

- promotion은 conservative하다.
- `PARTIAL_MATCH`는 production 승격하지 않는다.
- late speech/text success는 validation evidence로는 남지만 promotion allowed source가 아니다.
- cross-run cache, learning, auto-retargeting은 지원하지 않는다.
- aggregate artifact는 run 내부 scenario append 기준이며 cross-run merge는 하지 않는다.

## 11. Future Work

- promotion precision을 유지한 상태에서 richer allowed success source 검토
- probe candidate selection 고도화
- scenario-aware retry policy 세분화
- QA Frontend 상세 drill-down 강화

이 항목들은 V8 이후 주제이며, 현재 완료 구현의 의미를 바꾸지 않는다.
