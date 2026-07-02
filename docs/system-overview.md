# System Overview (현재 운영 기준)

[README](README.md) | [Architecture](architecture.md) | [Runner Flow](runner_flow.md) | [Testing Pipeline](testing-pipeline.md)

Updated for V10: 2026-07-03

## 1) 시스템 목적

`talkback-a11y-helper`는 SmartThings TalkBack 환경에서 일반 자동화만으로
안정적으로 다루기 어려운 포커스 이동, 화면 진입, step 수집, 리포트 생성을
보완하는 runner다.

핵심 원칙:

- Android helper / SMART_NEXT / move_smart는 안정 영역
- Python runner가 scenario open, traversal, 저장 semantics를 관리
- 운영 기준은 representative smoke와 long-run regression으로 검증

## 2) 현재 운영 범위

- Global nav / main tab scenarios
- Life plugin scenarios
- Device plugin scenarios
- Excel raw/result report export
- ko-KR 및 English SmartThings UI 지원
- Full Run 이후 opt-in V10 Shadow Validation
- plugin family별 Promotion Readiness reporting

최근 운영 상태:

- Global long-run: `7/7` pass
- Life long-run: `12/12` pass
- Device long-run: `12/12` 실질 pass
- ko/en representative smoke: pass
- fatal / traceback 없음

## 3) 핵심 구성

### Android Helper (`app/`)
- accessibility bridge
- focus / tree dump / target action / SMART_NEXT 지원

### Python Runner (`script_test.py`, `tb_runner/`, `talkback_lib/`)
- scenario start pipeline
- traversal / stop / overlay / local tab handling
- checkpoint / final Excel 저장
- raw/result row semantics 관리

### V10 Shadow 계층 (`tb_runner/`, `qa_frontend/backend/`)

- Devices 화면의 Runtime Inventory 수집
- capability resource-id, XML 구조, header/label evidence 기반 Quick Identify
- versioned Policy Registry를 통한 scenario candidate 생성
- Legacy scenario와 V10 candidate 비교
- Promotion Readiness JSON/Markdown 및 QA Frontend summary 제공
- 기존 run artifact를 입력으로 Shadow만 재실행하는 developer tool 제공

## 4) 현재 중요 운영 정책

- Devices plugin card search는 helper scroll이 아니라 **ADB swipe 기반 bounded
  search**를 사용
- Devices 진입은 `enter_device_card_plugin` pre-navigation으로 통일
- result/raw 기본 visible 계열은 **actual TalkBack focus 기준**
- representative traversal 정보는 `representative_*` 컬럼에 분리 저장
- V10 Shadow는 Full Run에서 runtime flag와 request가 모두 ON일 때만 실행
- Shadow 실패는 Legacy 결과를 실패로 바꾸지 않으며 `legacy_result_preserved=true`
- Controlled Routing은 구현되지 않았고 V10 candidate는 traversal을 시작하지 않음

## 5) 문서 우선순위

1. [current-client-architecture.md](current-client-architecture.md)
2. [runner_flow.md](runner_flow.md)
3. [testing-pipeline.md](testing-pipeline.md)
4. [device-plugin-guide.md](device-plugin-guide.md)
5. [report-schema.md](report-schema.md)
6. [i18n_locale_matching.md](i18n_locale_matching.md)
7. [api-reference.md](api-reference.md)

Historical 설계 문서는 [archive/](archive/) 아래에 보존한다.
