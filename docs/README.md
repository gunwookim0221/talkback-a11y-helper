# Docs Guide

이 문서는 `talkback-a11y-helper` 문서를 어디에서 읽어야 하는지 안내하는 primary
index입니다. 현재 구현, 운영 계약, dated acceptance evidence, historical design을
서로 다른 권위로 취급합니다.

## 문서 권위 순서

현재 상태를 확인할 때는 다음 순서를 따릅니다.

1. **Current operational authority** — [Phase 10 운영 Runbook](operations/talkback-operational-runbook.md),
   [QA Frontend README](../qa_frontend/README.md), [QA Frontend validation contract](../qa_frontend/VALIDATION.md)
2. **Current architecture / system overview** — [시스템 개요](system-overview.md),
   [아키텍처](architecture.md)
3. **Implemented subsystem contracts** — Runner/client/config/report, traversal,
   Compare UI와 Candidate/Comparator 계약
4. **Dated phase closure and acceptance evidence** — 해당 phase의 scope/date에서만
   유효한 결과와 handoff
5. **Historical design / archive** — 당시 설계 의사결정과 RCA

오래된 문서의 acceptance 수치나 flag 설명이 현재 코드와 다르면, 위 순서에 따라
현재 구현과 Runbook을 우선합니다. historical 문서는 과거 기록 보존을 위해 수정하지
않습니다.

## 현재 시스템과 운영 계약

- [시스템 개요](system-overview.md): 현재 실행 lifecycle, evidence, review, Candidate/
  Comparator/Baseline 흐름
- [아키텍처](architecture.md): Production authority와 diagnostic/shadow 계층 구분
- [Runner 흐름](runner_flow.md): scenario open, traversal, recovery, persistence
- [현재 Python client 구조](current-client-architecture.md): `A11yAdbClient`와 내부 책임 분해
- [테스트 파이프라인](testing-pipeline.md): 수집/검증 파이프라인 요약
- [scenario 설정](scenario-config.md) / [runtime 설정](runtime-config.md): scenario registry와
  targeted runtime defaults
- [report row schema](report-schema.md): raw/result/representative row semantics
- [Devices plugin 운영](device-plugin-guide.md): Devices entry와 bounded search 계약
- [QA Local Control Panel](qa-frontend-guide.md) / [QA Frontend local run](qa-frontend-local-run.md):
  로컬 실행과 operator UI
- [TalkBack 품질 판독](talkback-quality-guide.md): evidence와 품질 해석 규칙

## Traversal, coverage, evidence

- [Production Traversal Migration Phase 8.5](design/talkback-production-traversal-migration.md):
  현재 V2 default-on/Legacy compatibility 계약과 dated migration evidence
- [V8 Coverage-Driven Traversal](design/v8-coverage-driven-traversal.md): focusable discovery,
  coverage와 probe의 역할
- [V7/V8 Focusable Coverage 설계](design/audit-v7-focusable-coverage-design.md)
- [Semantic Value / Shadow / Promotion](design/semantic-value-shadow-audit.md)
- [Device Plugin Audit V3](device-plugin-audit-guide.md): traversal audit의 진단 목적
- [Evidence implementation](design/talkback-traversal-evidence-implementation.md)
- [Canonical Identity & Target Relation](design/talkback-canonical-identity-and-target-relation.md)

Coverage, audit, Identity Shadow, V10 Shadow는 각각 evidence/diagnostic/readiness를
제공할 수 있지만, 문서가 명시한 Production authority를 자동으로 대체하지 않습니다.
현재 Full Validation은 canonical registry 전체를 선택하며 runtime `enabled` flag는
targeted execution default입니다.

## Future design / roadmap

- [State-Graph 기반 자동 Accessibility Crawl 로드맵](design/talkback-state-graph-accessibility-crawl-roadmap.md):
  현재 Scenario-driven traversal에서 미래 State-Graph-driven crawl로의 설계 방향

이 로드맵은 현재 production traversal의 설명이 아니라 future architectural direction입니다.
현재 기반과 향후 설계/구현 gap을 구분해서 읽습니다.

## QA Frontend, profiles, and comparison

- [Phase 10.2.5 Run Profiles](design/talkback-phase10.2.5-run-profiles.md): Full Validation,
  Quick Smoke, Custom/Debug profile 계약
- [Comparator finalization](design/talkback-phase10.3d-comparator-finalization.md):
  deterministic report, replay와 verdict 계약
- [Phase 10.4 Compare UI](design/talkback-phase10.4-compare-ui.md): local Candidate와
  Approved Baseline을 선택하는 read-only UI
- [QA validation contract](../qa_frontend/VALIDATION.md): scenario selection, preflight,
  batch/live/history/review 검증
- [Crash Capture Design](crash-capture-design.md)
- [Plugin onboarding wizard](plugin-onboarding-guide.md): discovery, bounded probe, draft review

Full Validation의 Candidate 자동 생성은 terminal/full registry/required artifacts 조건을
통과한 경우에만 additive하게 시도됩니다. Comparator와 Frontend는 자동 approval을 하지
않으며, Approved Baseline은 사람의 결정을 거친 reference입니다.

## V10 Shadow and readiness

- [V10 shadow corpus](design/v10/v10-shadow-corpus-design.md)
- [V10 phase closure](design/v10/v10-phase-closure.md)

V10은 Runtime Inventory, Quick Plugin Identify, Policy Registry, Shadow Compare,
Promotion Readiness와 corpus/readiness reporting을 제공합니다. V10 shadow 비교에서는
기존 Legacy scenario result가 comparison reference이며, 전체 production traversal은
current Runner/Traversal Identity V2 경로가 담당합니다. **Controlled Routing은 아직
시작되지 않았습니다**. V10 계획/roadmap은 구현된 current contract보다 우선하지 않습니다.

## Dated closure and historical evidence

다음 문서들은 당시 checkpoint를 기록한 evidence 또는 handoff입니다. 현재 운영을
설명하는 문서로 읽지 말고, 날짜와 scope를 함께 확인하십시오.

- [Phase 8 Identity Shadow completion](design/talkback-identity-shadow-phase8-completion.md)
- [Phase 9.5 Full Acceptance](design/talkback-phase9.5-full-acceptance.md)
- [Phase 9.5.1 Regression Recovery](design/talkback-phase9.5.1-regression-recovery.md)
- [Phase 9.5.2 Aggregate RCA](design/talkback-phase9.5.2-aggregate-rca.md)
- [Phase 9.5.3 Navigation Boundary Fix](design/talkback-phase9.5.3-global-navigation-boundary-fix.md)
- [Phase 10 phase closure](design/talkback-phase10-phase-closure.md)
- [Korean locale / Baseline phase closure](design/talkback-phase10-korean-locale-baseline-closure.md)
- [Audit V4 closure](design/audit-v4-phase-closure.md) / [Audit V5 traversal audit](design/audit-v5-traversal-engine-audit.md)
- [V10 overview](design/v10/v10-overview.md), [phase plan](design/v10/v10-phase-plan.md),
  [implementation roadmap](design/v10/v10-implementation-roadmap.md)

Phase 9.x의 Full Run 수치, Phase 8.5 recovery 결과, 그리고 2026-07-03 group result
(`7/7`, `12/12` 등)은 해당 문서의 historical/group scope에서만 유효합니다. 최신
`main`의 canonical 32-scenario physical-device acceptance를 증명하는 current result로
표시하지 않습니다.

## Historical design record

설계 당시 기록은 [archive/](archive/) 아래에 보존합니다.

- PR1 함수 분해
- PR2 start pipeline 구조화
- PR3 stop policy
- PR4 overlay flow
- PR14 client split

Archive와 phase 문서는 당시 결정을 설명하며, 현재 운영 판단은 위의 current operational
authority와 구현 source를 우선합니다.
