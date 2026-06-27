# Semantic Value Shadow Audit

## 1. Purpose

이 문서는 semantic value audit와 V8 probe reporting의 경계를 설명한다.

현재 시스템에는 서로 다른 reporting layer가 공존한다.

- semantic value shadow
- coverage probe shadow
- promotion policy
- production promotion

이 문서의 목적은 특히 아래 구분을 명확히 하는 것이다.

```text
Shadow
↓
Promotion
↓
Production
```

## 2. Semantic Value Audit Scope

semantic value audit는 row-centric reporting layer다.

다루는 것:

- `semantic_card_values`
- semantic value coverage
- semantic value confidence
- semantic value quality
- semantic value review/gate candidate

다루지 않는 것:

- traversal movement 변경
- probe targetting
- helper focus primitive
- production row 승격

semantic value audit는 여전히 `PASS` / `WARN` / `FAIL`을 직접 바꾸지 않는다.

## 3. Shadow Layers In The Current System

현재 shadow에는 최소 두 종류가 있다.

### 3.1 Semantic shadow

semantic card metadata와 speech evidence를 비교해 row-level 값 커버리지를 설명한다.

예:

- `VALUE_FULLY_COVERED`
- `VALUE_PARTIALLY_COVERED`
- `VALUE_MISSING`

### 3.2 Coverage probe shadow

runtime probe가 별도 focus candidate를 검증한 뒤 result sheet에 shadow row를 append한다.

row source:

- `COVERAGE_PROBE_SHADOW`

이 row는 traversal row를 대체하지 않는다.

## 4. Shadow Means Reporting, Not Production

Shadow의 공통 의미:

- 추가 evidence를 보여 준다.
- 기존 traversal result를 덮어쓰지 않는다.
- production verdict semantics를 즉시 바꾸지 않는다.

현재 shadow row 특징:

- `final_result=SHADOW`
- review/audit visibility 제공
- downstream promotion policy의 입력이 될 수 있음

## 5. Promotion Layer

Promotion은 shadow row를 production row로 올릴 수 있는지 판정하는 독립 계층이다.

중요한 점:

- shadow 생성과 promotion은 다른 단계다.
- `MATCH`라고 해서 자동 승격되지 않는다.
- semantic shadow와 probe shadow는 promotion 대상 성격이 다르다.

현재 V8 promotion policy는 coverage probe validation에만 적용된다.

핵심 fields:

- `promotion_status`
- `promotion_reason`

대표 값:

- `PROMOTABLE`
- `NOT_PROMOTABLE`

대표 reason:

- `exact_probe_match`
- `partial_validation`
- `probe_failed`
- `screen_skip`
- `environment_skip`

## 6. Production Layer

Production은 최종 result sheet의 운영 row semantics를 뜻한다.

현재 production row는 두 source에서 올 수 있다.

- 원래 traversal row
- `COVERAGE_PROBE_PROMOTED`

promoted row 특징:

- `final_result=PASS`
- 기존 traversal row는 그대로 유지
- duplicate production row가 이미 있으면 append하지 않음

즉, current production promotion은 replace가 아니라 append + dedup 정책이다.

## 7. Semantic Value vs Probe Shadow

두 계층은 목적이 다르다.

semantic value audit:

- 한 row가 user-meaningful value를 충분히 말했는지 본다.
- representative / nearby evidence를 활용할 수 있다.

coverage probe audit:

- coverage gap node를 runtime에서 다시 focus/verify한다.
- helper focus success, late verification, validation status, promotion policy를 따진다.

따라서 semantic value coverage가 충분해도 probe promotion이 불가능할 수 있고,
반대로 probe shadow는 semantic value 판단과 무관하게 production append 후보가 될 수 있다.

## 8. Result Sheet Semantics

현재 result sheet에서 구분해야 할 source:

- traversal row: 기존 수집 결과
- `COVERAGE_PROBE_SHADOW`: validation evidence row
- `COVERAGE_PROBE_PROMOTED`: production 승격 row

현재 추가 메타데이터:

- `probe_validation_status`
- `probe_success_source`
- `promotion_status`
- `promotion_reason`
- `promotion_applied`
- `promotion_dedup_status`
- `promotion_dedup_reason`

## 9. Operational Interpretation

리뷰 시 해석 우선순위:

1. traversal row는 원래 pipeline 결과다.
2. semantic value fields는 row 의미 품질을 설명한다.
3. probe shadow row는 coverage gap recheck evidence다.
4. promotion status는 production 승격 가능성만 설명한다.
5. promoted row는 dedup을 통과한 보수적 append 결과다.

## 10. Known Limitations

- semantic value gate candidate는 여전히 reporting-only다.
- coverage probe promotion은 conservative하다.
- `PARTIAL_MATCH`는 production 승격하지 않는다.
- semantic value confidence와 probe promotion confidence는 같은 개념이 아니다.

## 11. Related Reading

- [Audit V7 Focusable Coverage Design](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v7-focusable-coverage-design.md)
- [V8 Coverage-Driven Traversal](/d:/Python%20test/talkback-a11y-helper/docs/design/v8-coverage-driven-traversal.md)
