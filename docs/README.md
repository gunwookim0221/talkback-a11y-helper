# Docs Guide

현재 운영 기준 문서와 historical 설계 문서를 분리해 둔 인덱스입니다.

## 운영 기준

- 시스템 개요: [system-overview.md](system-overview.md)
- 아키텍처: [architecture.md](architecture.md)
- 현재 client 구조: [current-client-architecture.md](current-client-architecture.md)
- 실행 흐름: [runner_flow.md](runner_flow.md)
- 테스트 파이프라인: [testing-pipeline.md](testing-pipeline.md)
- scenario 설정: [scenario-config.md](scenario-config.md)
- runtime 설정: [runtime-config.md](runtime-config.md)
- helper/client API: [api-reference.md](api-reference.md)
- V8 Coverage-Driven Traversal: [design/v8-coverage-driven-traversal.md](design/v8-coverage-driven-traversal.md)
- V7/V8 Focusable Coverage 설계: [design/audit-v7-focusable-coverage-design.md](design/audit-v7-focusable-coverage-design.md)
- Semantic Value / Shadow / Promotion 구분: [design/semantic-value-shadow-audit.md](design/semantic-value-shadow-audit.md)
- Devices plugin 운영: [device-plugin-guide.md](device-plugin-guide.md)
- Device Plugin Audit V3: [device-plugin-audit-guide.md](device-plugin-audit-guide.md)
- Device Plugin Audit V4 Design: [design/audit-v4-xml-coverage-design.md](design/audit-v4-xml-coverage-design.md)
- Audit V4 Closure: [design/audit-v4-phase-closure.md](design/audit-v4-phase-closure.md)
- Audit V5 Traversal Engine Audit: [design/audit-v5-traversal-engine-audit.md](design/audit-v5-traversal-engine-audit.md)
- Audit V5 Phase 5A Traversal Event Inventory: [design/audit-v5-phase5a-traversal-event-inventory.md](design/audit-v5-phase5a-traversal-event-inventory.md)
- Audit V5 Phase 5A Normalized Event Schema: [design/audit-v5-phase5a-normalized-event-schema.md](design/audit-v5-phase5a-normalized-event-schema.md)
- Traversal Evidence Architecture: [design/talkback-traversal-evidence-architecture.md](design/talkback-traversal-evidence-architecture.md)
- Evidence Instrumentation: [design/talkback-traversal-evidence-implementation.md](design/talkback-traversal-evidence-implementation.md)
- 신규 plugin onboarding: [plugin-onboarding-guide.md](plugin-onboarding-guide.md)
- report row schema: [report-schema.md](report-schema.md)
- i18n / locale matching: [i18n_locale_matching.md](i18n_locale_matching.md)
- QA Local Control Panel: [qa-frontend-guide.md](qa-frontend-guide.md) (Batch-First UX 통합 적용)
- QA Frontend 로컬 실행: [qa-frontend-local-run.md](qa-frontend-local-run.md)
- TalkBack 접근성 품질 판독: [talkback-quality-guide.md](talkback-quality-guide.md)
- Crash Capture Design: [crash-capture-design.md](crash-capture-design.md)

## V10 Design and Closure

- V10 Overview: [design/v10/v10-overview.md](design/v10/v10-overview.md)
- V10 Phase Plan: [design/v10/v10-phase-plan.md](design/v10/v10-phase-plan.md)
- V10 Device Inventory: [design/v10/v10-device-inventory-design.md](design/v10/v10-device-inventory-design.md)
- V10 Quick Plugin Identify: [design/v10/v10-quick-plugin-identify-design.md](design/v10/v10-quick-plugin-identify-design.md)
- V10 Policy Mapping: [design/v10/v10-policy-mapping-design.md](design/v10/v10-policy-mapping-design.md)
- V10 Shadow Validation: [design/v10/v10-shadow-validation-design.md](design/v10/v10-shadow-validation-design.md)
- V10 Shadow Corpus / History: [design/v10/v10-shadow-corpus-design.md](design/v10/v10-shadow-corpus-design.md)
- V10 Implementation Roadmap: [design/v10/v10-implementation-roadmap.md](design/v10/v10-implementation-roadmap.md)
- V10 Phase Closure: [design/v10/v10-phase-closure.md](design/v10/v10-phase-closure.md)

V10 Sprint 0~6 구현은 완료됐다. Runtime Inventory, Quick Plugin Identify, Policy
Registry, Shadow Validation, Shadow-only Runner, QA Frontend reporting과 Promotion
Readiness는 현재 제공된다. Legacy routing/traversal은 계속 authoritative이며
Controlled Routing은 V11 이후 계획이다.

V10 후속 Shadow Corpus는 run-local shadow 결과의 compact history와 family/readiness
요약을 `artifacts/v10/corpus/`에 누적한다. raw XLSX, screenshot, full log는 복사하지
않으며 `python tools/update_v10_shadow_corpus.py --run-dir "<device-run-dir>"`로
갱신한다.

QA Frontend의 별도 `V10 Corpus Readiness` 카드에서 누적 entry, overall readiness,
family별 MATCH/UNKNOWN/MISMATCH/FAILED, 단말·locale 다양성과 V11 pilot 후보를
확인할 수 있다. 이 dashboard는 `/api/v10/corpus/summary`를 읽기만 하며 Controlled
Routing을 활성화하거나 Promotion Readiness를 재판정하지 않는다.

## Plugin Onboarding Wizard MVP

신규 Life / Device plugin 추가 흐름은 [plugin-onboarding-guide.md](plugin-onboarding-guide.md)
와 [qa-frontend-guide.md](qa-frontend-guide.md)를 우선 참조합니다.

현재 MVP 범위:

- visible plugin discovery
- bounded probe
- draft generate/review/apply
- smoke start/status refresh
- onboarding session persistence/restore
- next action recommendation
- rollback preview

현재 rollback은 preview only이며 실제 복원 실행은 제공하지 않습니다.

## Historical design record

설계 당시 기록은 [archive/](archive/) 아래에 보존합니다.

- PR1 함수 분해
- PR2 start pipeline 구조화
- PR3 stop policy
- PR4 overlay flow
- PR14 client split

운영 판단은 archive 문서보다 운영 기준 문서를 우선합니다.
*(최근의 Batch-First UX 통합 및 Known Issues 등에 대해서는 `qa-frontend-guide.md`를 참고하세요.)*

## Related design documents

- [v8-coverage-driven-traversal.md](design/v8-coverage-driven-traversal.md)
- [audit-v7-focusable-coverage-design.md](design/audit-v7-focusable-coverage-design.md)
- [semantic-value-shadow-audit.md](design/semantic-value-shadow-audit.md)
