# QA Frontend Overview

이 문서는 QA Frontend의 목적과 각 패널의 구성 요소, 운영 시나리오를 설명합니다.

## 목적
QA Frontend는 TalkBack 자동화 테스트 실행을 제어하고, 진행 상황을 모니터링하며, 완료된 테스트의 접근성 품질을 평가할 수 있는 대시보드입니다.

## 구성

- **Runtime Dashboard**: 현재 실행 중인 테스트의 실시간 진행 상황(현재 시나리오, 성공/실패 시나리오 수 등)을 보여줍니다.
- **Runtime Preflight**: 테스트 시작 전 기기 상태, 접근성 서비스 활성화 상태 등을 점검하는 패널입니다.
- **Recent Runs**: 이전에 실행 완료된 최근 테스트 기록들을 모아 보여주는 패널입니다.
- **Run Details**: 선택한 실행 건에 대해 세부 로그, 통과/경고/실패 시나리오 목록을 확인할 수 있습니다.
- **TalkBack Quality**: 실행 완료된 시나리오에서 추출된 접근성 품질(FAIL, ISSUE, REVIEW, CLEAN) 요약을 보여줍니다.
- **Scenario Quality**: 특정 시나리오가 속한 모듈(Navigation, Life Plugins, Device Plugins)별 접근성 품질 상태를 나열합니다.
- **Quality Signals**: 시나리오 내부 스텝에서 발생한 구체적인 품질 신호(True Mismatch, Empty Visible 등)를 보여주는 리스트입니다.
- **Outputs**: 로그 파일, 스크린샷, 엑셀 리포트 등 생성된 결과물 파일들을 조회할 수 있습니다.

## Run Panel 설명

**Launch**
- `Clean`: 앱 데이터를 초기화한 후 깨끗한 상태에서 테스트를 실행합니다.
- `Warm`: 기존 데이터를 유지한 상태에서 테스트를 이어서 실행합니다.

**Language**
- `Current`: 기기에 설정된 현재 언어로 테스트를 실행합니다.
- `Korean`: 테스트 실행 전 기기 언어를 한국어(ko-KR)로 변경합니다.
- `English`: 테스트 실행 전 기기 언어를 영어(en-US)로 변경합니다.

**Mode**
- `Smoke`: 빠른 검증을 위한 주요 시나리오(Quick check)만 실행합니다.
- `Full`: 전체 회귀 테스트(Full regression)를 실행합니다.

## Recent Runs 설명
완료된 테스트를 시간순으로 나열하여 선택할 수 있는 대시보드입니다. 런타임이 종료되면 이곳에 새로운 Run 카드가 나타나며, 카드를 클릭하면 `Run Details`와 `TalkBack Quality`가 해당 실행 결과로 갱신됩니다.

## Run Details 설명
- **Failed**: 실행 중 치명적인 에러(앱 크래시 등)로 인해 실패한 시나리오 목록을 보여줍니다. (기본 펼침)
- **Warning**: 부분적인 실패나 진행 중 문제가 발생했으나 완전히 실패하지 않은 시나리오 목록입니다.
- **Passed**: 정상적으로 끝까지 수행된 시나리오 목록입니다.

## 운영 시 추천 사용 순서
1. **Preflight 점검**: Helper App과 ADB 상태가 정상인지 확인합니다.
2. **Run Panel 설정**: Launch(Clean/Warm), Language, Mode를 선택합니다.
3. **실행 및 모니터링**: Run 버튼을 누르고 Runtime Dashboard에서 실시간 경과를 확인합니다.
4. **결과 확인**: Recent Runs 패널에서 완료된 Run을 선택합니다.
5. **품질 검수**: TalkBack Quality의 FAIL, ISSUE 카운트를 확인하고, Quality Signals에서 실제 문제 항목을 식별합니다.
