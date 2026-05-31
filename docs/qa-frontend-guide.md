# QA Frontend Overview

## 목적
QA Frontend는 TalkBack 기반 접근성 자동화 테스트의 설정, 실행 제어, 실시간 모니터링 및 결과 분석을 통합 제공하는 대시보드입니다.

## 시스템 구성

- **ADB**: 디바이스 연결 상태와 기본 제어 환경을 확인하는 섹션입니다.
- **TalkBack A11y Helper**: 디바이스 내 헬퍼 앱의 설치 여부와 서비스 활성화 상태를 관리합니다.
- **Run**: 테스트 모드와 환경을 설정하고 실제 실행 및 중지를 제어하는 패널입니다.
- **Runtime Preflight**: 테스트 시작 전 기기의 상태가 자동화 실행에 적합한지 사전 점검합니다.
- **Live Monitor**: (이전 Runtime Dashboard) 테스트가 진행되는 동안의 실시간 상황을 모니터링합니다.
- **Scenarios**: 실행할 대상 시나리오들을 선택하고, 플러그인 모듈별 상태를 확인합니다.
- **Outputs**: 로그 파일, 캡처된 스크린샷, 엑셀 리포트 등 테스트 산출물을 확인하고 다운로드할 수 있습니다.
- **Recent Runs**: 최근에 수행된 실행 건들을 목록으로 모아 상태를 한눈에 보여줍니다.
- **Run Details**: 선택한 실행 건에 대한 시나리오별 통과/경고/실패 상세 정보를 제공합니다.
- **TalkBack Quality**: 실행 완료 후 추출된 시나리오별 접근성 품질 상태(FAIL, ISSUE, REVIEW, CLEAN)를 요약합니다.

---

## Run Panel

**Launch**
- `Clean`: 앱 데이터를 완전히 초기화한 후 깨끗한 상태에서 시작합니다.
- `Warm`: 기존 데이터를 유지한 채 이어서 테스트를 진행합니다.

**Language**
- `Current`: 기기에 현재 설정된 언어를 유지합니다.
- `Korean`: 테스트 실행 전 기기 언어를 한국어(ko-KR)로 자동 변경합니다.
- `English`: 테스트 실행 전 기기 언어를 영어(en-US)로 자동 변경합니다.

**Mode**
- `Smoke`: 일부 주요 시나리오에 대해서만 빠른 검증(Quick check)을 수행합니다.
- `Full`: 전체 시나리오를 대상으로 회귀 테스트(Full regression)를 수행합니다.

**Run / Stop**
- 선택한 설정대로 테스트를 실행하거나, 현재 진행 중인 테스트를 강제 중지합니다.

---

## Runtime Preflight

테스트 실행 전 자동화 환경 점검 항목입니다.

- **Preflight**: 종합적인 사전 점검 통과 여부 (Passed / Blocked)
- **Helper**: 헬퍼 앱의 설치 및 접근성 서비스 권한 상태
- **TalkBack**: 시스템 TalkBack(삼성/구글)의 활성화 여부
- **Foreground**: 현재 기기에서 실행 중인 포그라운드 앱 패키지
- **Popup**: 시스템 또는 외부 앱 팝업 발생 여부 및 방해 요소 감지
- **Settings**: 디바이스 설정 화면 노출 및 제어 가능 여부

---

## Live Monitor

**역할**
테스트가 진행되는 동안 시나리오 전환, 스텝 진행률, 이벤트 피드 등 실시간 디버깅 데이터를 제공하는 모니터링 영역입니다.

- **Idle 시 접힘**: 테스트가 실행 중이 아닐 때는 공간을 차지하지 않도록 기본적으로 접혀 있습니다.
- **Running 시 자동 펼침**: 테스트가 시작(Running/Starting)되면 실시간 확인을 위해 자동으로 펼쳐집니다.

---

## Recent Runs, Run Details, Outputs 사용법

- **Recent Runs**: 목록에서 최근 10개의 테스트 결과를 확인합니다. 각 카드는 `TALKBACK FAIL (n)`, `TALKBACK ISSUE` 등의 접근성 퀄리티 요약 배지를 제공하여 런 단위의 상태를 즉시 비교할 수 있습니다.
- **Run Details**: Recent Runs에서 카드를 선택하면 해당 Run의 시나리오 단위 디테일(Failed, Warning, Passed)이 우측에 열리며 세부 오류 사유를 확인할 수 있습니다.
- **Outputs**: 테스트가 끝난 후, 원본 로그 파일 및 XLSX 보고서를 다운로드할 수 있는 영역입니다.
