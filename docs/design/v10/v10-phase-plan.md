# V10 Phase Plan

| Metadata | Value |
| --- | --- |
| Status | Completed |
| Phase | V10 Phase 0 |
| Owner | TalkBack Automation |
| Last Updated | 2026-07-03 |
| Depends On | [V10 Overview](v10-overview.md) |
| Related Documents | [V10 Device Inventory Design](v10-device-inventory-design.md), [V10 Phase Closure](v10-phase-closure.md) |
| Next | [V10 Phase Closure](v10-phase-closure.md) |

## 1. Delivery Principle

V10의 첫 구현은 production replacement가 아니라 shadow MVP다.

운영 원칙:

- 기존 Display Name 방식은 fallback으로 유지한다.
- unknown/ambiguous는 fail-closed 처리한다.
- traversal engine은 최대한 재사용한다.
- 변경 핵심은 policy selection 방식이다.

## 2. Target Architecture

```text
Device Inventory
-> Quick Plugin Identify
-> Policy Mapping
-> Existing Traversal Engine
```

## 3. Phase 1: Device Inventory

### Goal

Devices 화면에서 현재 보이는 card를 runtime inventory로 안정적으로 수집한다.

### Deliverables

- visible device card inventory schema
- runtime card descriptor
- discovery evidence set
- current-view inventory artifact

### Validation Criteria

- 현재 viewport에서 visible card를 누락 없이 수집한다.
- label, stable label, bounds, resource-id, source 같은 locator evidence를 기록한다.
- display name은 semantic identity가 아니라 runtime locator로 저장된다.

### Risks

- current-view-only inventory는 offscreen card를 포함하지 못한다.
- card index나 bounds는 영속 identity가 아니다.

## 4. Phase 2: Quick Plugin Identify

### Goal

선택한 device card를 짧게 열고 capability/resource-id/XML structure를 수집하여
plugin family를 분류한다.

### Deliverables

- quick identify flow
- identify evidence schema
- signature extraction rules
- classifier result: matched / unknown / ambiguous

### Validation Criteria

- open 후 짧은 step 내에서 capability evidence를 확보할 수 있다.
- Motion, Door, Leak, Smoke 같은 family에 대해 최소한 shadow 분류가 가능하다.
- identify 실패 시 잘못된 scenario를 강제 선택하지 않는다.

### Risks

- entry/back restoration이 불안정할 수 있다.
- dynamic loading이나 modal overlay가 identify를 오염시킬 수 있다.
- multi-capability device는 단일 signature로 설명되지 않을 수 있다.

## 5. Phase 3: Policy Mapping

### Goal

identify 결과를 기존 scenario policy에 연결한다.

### Deliverables

- capability signature -> scenario mapping registry
- policy selection rules
- ambiguous handling policy
- fallback decision matrix

### Validation Criteria

- 기존 scenario config를 최대한 재사용한다.
- 선택 결과가 deterministic하게 기록된다.
- unknown/ambiguous는 fail-closed 또는 legacy fallback으로만 처리된다.

### Risks

- capability family와 scenario granularity가 정확히 일치하지 않을 수 있다.
- 잘못된 mapping은 기존 traversal 재사용이라는 장점을 오히려 회귀로 바꿀 수 있다.

## 6. Phase 4: Shadow Validation

### Goal

production routing을 바꾸지 않고 classifier와 legacy display-name routing을 병렬 비교한다.

### Deliverables

- shadow comparison report
- match rate / unknown rate / ambiguous rate
- classifier confidence summary
- mismatch triage list

### Validation Criteria

- 기존 routing 결과와 classifier 결과를 scenario 단위로 비교할 수 있다.
- unknown/ambiguous 비율이 관측 가능하다.
- 오탐과 미탐을 분리해 분석할 수 있다.

### Risks

- 실제 운영 환경에서 shadow artifact가 충분히 축적되지 않으면 판단이 흔들린다.
- 계정/언어/앱 버전 다양성을 충분히 커버하지 못할 수 있다.

## 7. Phase 5: Controlled Routing

### Goal

shadow 결과가 충분히 안정적일 때 high-confidence case에 한해 제한적으로 classifier
기반 routing을 허용한다.

### Deliverables

- gated routing policy
- confidence threshold
- fallback routing behavior
- operational guardrails

### Validation Criteria

- classifier high-confidence case만 production routing 대상으로 사용한다.
- legacy fallback이 유지된다.
- unknown/ambiguous는 기존 방식 또는 skip으로 안전 종료된다.

### Risks

- 부분 전환 상태에서 debugging 복잡도가 증가할 수 있다.
- fallback과 classifier 결과가 충돌할 때 운영 판단 규칙이 필요하다.

## 8. Phase 6: Frontend Exposure

### Goal

Discovery/Identify/Policy Selection 결과를 관찰 가능하게 노출한다.

### Deliverables

- discovery inventory view extension
- identify result surface
- confidence / unknown / ambiguous status exposure
- shadow comparison visibility

### Validation Criteria

- 사용자가 "왜 이 policy가 선택됐는가"를 추적할 수 있다.
- identify evidence와 routing decision을 함께 볼 수 있다.
- production action과 shadow information이 구분된다.

### Risks

- UI가 classifier confidence를 과신하게 만들 수 있다.
- raw evidence가 부족하면 설명 가능성이 떨어진다.

## 9. Phase 7: Migration / Closure

### Goal

legacy display-name-only routing 의존성을 단계적으로 축소하고 운영 기준을 정리한다.

### Deliverables

- migration rule
- plugin family별 readiness table
- legacy dependency inventory
- closure criteria

### Validation Criteria

- family별로 classifier readiness를 선언할 수 있다.
- display-name-only 의존 scenario를 명시적으로 구분할 수 있다.
- 운영 문서가 legacy와 V10 routing 경계를 설명한다.

### Risks

- 모든 plugin family가 같은 속도로 readiness에 도달하지 않는다.
- 일부 plugin은 장기적으로도 display name fallback을 유지해야 할 수 있다.

## 10. Recommended First Cut

첫 구현 우선순위는 아래가 적절하다.

1. Device Inventory
2. Quick Plugin Identify
3. Policy Mapping
4. Shadow Validation

이 4단계만으로도 Display Name dependency 완화 가능성을 실측할 수 있다.

## 11. MVP Success Condition

Shadow MVP의 성공 조건은 아래와 같다.

- 기존 traversal engine 변경 없이 classifier 결과를 생성할 수 있다.
- Motion Sensor 같은 대표 device family에 대해 post-open identify가 가능하다.
- unknown/ambiguous를 안전하게 처리한다.
- display-name-only routing 대비 개선 여지를 계량적으로 보여 줄 수 있다.

## 12. Failure Condition

아래 조건이면 V10은 즉시 production 전환이 아니라 추가 shadow 단계가 필요하다.

- unknown rate가 높다.
- ambiguous rate가 높다.
- capability signature가 plugin family를 안정적으로 분리하지 못한다.
- identify/back restoration이 운영 안정성을 해친다.

## 13. Final Direction

V10의 본질은 traversal 재작성 프로젝트가 아니다. 이미 존재하는 traversal/policy
자산을 보존하면서, 그 앞단에 discovery-based identification과 policy selection
계층을 추가하는 프로젝트다.
