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
- 신규 plugin onboarding: [plugin-onboarding-guide.md](plugin-onboarding-guide.md)
- report row schema: [report-schema.md](report-schema.md)
- i18n / locale matching: [i18n_locale_matching.md](i18n_locale_matching.md)

## Historical design record

설계 당시 기록은 [archive/](archive/) 아래에 보존합니다.

- PR1 함수 분해
- PR2 start pipeline 구조화
- PR3 stop policy
- PR4 overlay flow
- PR14 client split

운영 판단은 archive 문서보다 운영 기준 문서를 우선합니다.
