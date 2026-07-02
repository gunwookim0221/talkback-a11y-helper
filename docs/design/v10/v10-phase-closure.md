# V10 Phase Closure

| Metadata | Value |
| --- | --- |
| Status | Completed |
| Phase | V10 Closure |
| Owner | TalkBack Automation |
| Last Updated | 2026-07-03 |
| Depends On | [V10 Implementation Roadmap](v10-implementation-roadmap.md) |
| Related Documents | [V10 Overview](v10-overview.md), [V10 Phase Plan](v10-phase-plan.md), [V10 Shadow Validation Design](v10-shadow-validation-design.md) |
| Next | V11 Controlled Routing Pilot |

## 1. V10 Goal

V10의 목표는 Device plugin의 semantic identity를 display name에서 분리할 수 있는
runtime 경로를 만들고, 기존 traversal engine을 바꾸지 않은 채 capability 기반
scenario candidate를 Legacy 결과와 안전하게 비교하는 것이었다.

V10은 production routing 교체가 아니라 아래 shadow architecture를 완성했다.

```text
Device Card Inventory
-> Quick Plugin Identify
-> Versioned Policy Registry
-> Legacy/V10 Shadow Compare
-> Promotion Readiness
-> QA Frontend Reporting
```

## 2. Completed Sprints

| Sprint | 결과 |
| --- | --- |
| Sprint 0 | default-OFF feature flags, version schema, artifact/fixture/validation 기반 |
| Sprint 1 | bounded Runtime Inventory와 runtime-card identity contract |
| Sprint 2 | post-open capability/XML evidence 기반 Quick Plugin Identify |
| Sprint 3 | versioned Policy Registry와 fail-closed scenario candidate |
| Sprint 4 | Legacy-authoritative Shadow Compare, JSON/Markdown, Full Run hook |
| Sprint 4.6 | 기존 run artifact를 사용하는 Shadow-only Runner |
| Sprint 4.7 | conservative Inventory boundary duplicate merge |
| Sprint 5 | QA Frontend Shadow Validation summary와 artifact access |
| Sprint 6 | plugin family별 Promotion Readiness 평가와 reporting |

## 3. Implemented Features

- Runtime Inventory
- Quick Plugin Identify
- versioned Policy Registry
- Shadow Validation과 comparison metrics
- Shadow-only developer runner
- Inventory boundary duplicate diagnostics/merge
- QA Frontend Shadow reporting
- Promotion Readiness JSON/Markdown 및 UI
- Shadow exception 격리와 `legacy_result_preserved=true`

Display/stable name은 V10 classifier의 primary identity가 아니라 locator evidence다.
다만 production traversal은 Controlled Routing이 없으므로 기존
`target_stable_labels` locator를 계속 사용한다.

## 4. Known Issue Resolution

Viewport overlap에서 같은 physical Device Card가 중복 수집되던 boundary duplicate는
Sprint 4.7에서 해결했다.

- label-only, bounds-only, resource-id-only merge 금지
- 인접 viewport, clipping, structure, bounds proximity와 observation order의 복합
  evidence가 있을 때만 merge
- 동일 이름의 실제 다른 device는 별도 inventory item으로 유지
- merge reason과 identity diagnostics를 artifact에 기록

현재 이 이슈는 V10 closure blocker가 아니다.

## 5. Intentionally Not Implemented

Controlled Routing은 의도적으로 구현하지 않았다.

- V10 scenario candidate는 traversal을 시작하지 않는다.
- Legacy routing/traversal/report가 authoritative다.
- QA Frontend에 route 전환 버튼이 없다.
- source V10 feature flags는 기본 false다.
- `runtime_activation_supported=false`다.

## 6. Final Decision

| 항목 | 판단 | 근거 |
| --- | --- | --- |
| Shadow Validation | PASS | Full Run과 Shadow-only에서 artifact 생성, Legacy 보존, MISMATCH/FAILED 0 검증 |
| Promotion Readiness | HOLD | READY candidate는 있으나 family별 표본과 UNKNOWN coverage가 promotion gate에 부족 |
| Controlled Routing | NOT STARTED | V10 범위 밖이며 fail-closed 원칙에 따라 미활성 |

최종 readiness 검증에서는 overall `HOLD`, READY candidate 5개, BLOCKED 0개를
확인했다.

V10 구현 phase는 완료한다. 이 판단은 V10을 production routing으로 승격한다는 의미가
아니다.

## 7. Remaining Work

- locale/account/device cohort별 독립 표본 확대
- UNKNOWN-only family의 capability signature 보강
- mixed MATCH/UNKNOWN family의 evidence 원인 분석
- confidence drift와 registry/mapping revision cohort 추적
- Controlled Routing 진입 전 rollback/kill-switch 운영 검증

## 8. V11 Scope

V11 후보 범위:

- family allowlist 기반 Controlled Routing Pilot
- Legacy fallback과 즉시 rollback이 가능한 kill switch
- capability-first entry/traversal 실험
- multi-run Promotion Readiness aggregation
- READY family 확대와 UNKNOWN 감소
- Legacy display-name locator 의존성의 단계적 축소

V11에서도 초기 production default는 Legacy로 유지하고, 승인된 family/cohort만 제한된
pilot 대상으로 삼아야 한다.
