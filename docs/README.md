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
- Devices plugin 운영: [device-plugin-guide.md](device-plugin-guide.md)
- Device Plugin Audit V3: [device-plugin-audit-guide.md](device-plugin-audit-guide.md)
- Device Plugin Audit V4 Design: [design/audit-v4-xml-coverage-design.md](design/audit-v4-xml-coverage-design.md)
- Audit V4 Closure: [design/audit-v4-phase-closure.md](design/audit-v4-phase-closure.md)
- Audit V5 Traversal Engine Audit: [design/audit-v5-traversal-engine-audit.md](design/audit-v5-traversal-engine-audit.md)
- Audit V5 Phase 5A Traversal Event Inventory: [design/audit-v5-phase5a-traversal-event-inventory.md](design/audit-v5-phase5a-traversal-event-inventory.md)
- Audit V5 Phase 5A Normalized Event Schema: [design/audit-v5-phase5a-normalized-event-schema.md](design/audit-v5-phase5a-normalized-event-schema.md)
- 신규 plugin onboarding: [plugin-onboarding-guide.md](plugin-onboarding-guide.md)
- report row schema: [report-schema.md](report-schema.md)
- i18n / locale matching: [i18n_locale_matching.md](i18n_locale_matching.md)
- QA Local Control Panel: [qa-frontend-guide.md](qa-frontend-guide.md) (Batch-First UX 통합 적용)
- QA Frontend 로컬 실행: [qa-frontend-local-run.md](qa-frontend-local-run.md)
- TalkBack 접근성 품질 판독: [talkback-quality-guide.md](talkback-quality-guide.md)
- Crash Capture Design: [crash-capture-design.md](crash-capture-design.md)

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

- [semantic-value-shadow-audit.md](design/semantic-value-shadow-audit.md)
- [audit-v7-focusable-coverage-design.md](design/audit-v7-focusable-coverage-design.md)
