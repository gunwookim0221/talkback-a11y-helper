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
- **Run History (Batch Runs)**: 기존 Single Run 방식을 대체하여, 이제 모든 실행은 다중/단일 단말 관계없이 Batch 모드로 실행 및 관리됩니다. 최근에 수행된 배치 실행 건들을 목록으로 모아 보여줍니다.
- **Batch Details (Device Details)**: 선택한 배치 런과 단말에 대한 시나리오 단위 통과/경고/실패 상세 정보와, 추출된 접근성 품질(TalkBack Quality), Crash Issues, 로그 및 XLSX 원본 파일에 접근할 수 있습니다.

*(참고: 레거시 Outputs 패널과 Single Run 패널은 Batch First UX 전환으로 제거되었습니다.)*

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
- `Selected Smoke`: 현재 선택된 시나리오를 축소된 `max_steps`로 빠르게 검증합니다.
- `Selected Full`: 현재 선택된 시나리오를 source runtime config의 `max_steps`로 실행합니다. 이 모드는 모든 plugin을 자동 선택하지 않습니다.

**Scenario Presets**
- `All Plugins`: `device_*_plugin`과 `life_*_plugin`만 선택합니다. `life_main`, navigation, settings 등 plugin이 아닌 시나리오는 제외합니다.
- `All Scenarios`: navigation/main 시나리오와 모든 plugin 시나리오를 포함한 전체 available scenario를 선택합니다.
- Preset은 checkbox 선택만 바꾸며, Smoke/Full 실행 모드나 source `config/runtime_config.json`은 변경하지 않습니다.

**Run / Stop**
- 선택한 단말(들)과 시나리오에 대해 Batch Run을 실행하거나 중지합니다.

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
*참고: 현재 Batch First 환경에서 Live Monitor의 실시간 Step 렌더링은 제한적으로 동작하며, 주로 현재 실행 중인 단말 표시 및 상태 안내, Log Tail 뷰어의 역할을 수행합니다.*

- **Idle 시 접힘**: 테스트가 실행 중이 아닐 때는 공간을 차지하지 않도록 기본적으로 접혀 있습니다.
- **Running 시 자동 펼침**: 테스트가 시작되면 실시간 확인을 위해 자동으로 펼쳐집니다.

---

## Batch-First 워크플로우 가이드

새로운 운영 UX는 기존 Single Run 중심에서 벗어나 아래의 흐름으로 통일되었습니다.

1. **Run (실행)**: 상단 패널에서 단말과 시나리오를 선택 후 `Run`을 클릭하면 `/api/batch/start`를 통해 배치 런이 생성됩니다.
2. **Run History**: 실행 즉시 좌측 사이드바의 Batch Runs 목록에 새 배치가 등록됩니다.
3. **Device Details**: 완료(또는 실행 중)인 배치를 클릭하고 디바이스 카드를 열면, 기존 Single Run과 동일한 수준의 `TalkBack Quality`, `Scenario Quality`, `Quality Signals` 요약 데이터를 확인할 수 있습니다.
4. **Log/XLSX 확인**: Device 카드 하단의 링크를 통해 런타임 로그와 엑셀 리포트 전문을 조회할 수 있습니다.
5. **Crash Issues 확인**: Crash Capture가 생성한 event가 있으면 Device Details의 Crash Issues section에서 event card, repro guide, screenshot, artifact zip을 확인합니다.

### Batch Summary 구조
모든 결과는 `batch_runner.py`가 기존 단일 파서를 재사용하여 생성하며, `summary.json`에는 다음 정보가 포함됩니다.
* `scenarios` (개별 시나리오 진행 상태 및 스텝 수)
* `passed_scenarios`, `failed_scenarios` (시나리오 단위 성공 여부 집계)
* `quality` (TalkBack 품질 메타데이터)

### Batch TalkBack Quality
Batch 결과의 TalkBack Quality는 `fail`, `issue`, `review`, `clean` 항목으로 구성됩니다.
이 값은 시나리오 통과 개수와 무관하며, 테스트 완료 후 생성된 원본 **XLSX 파일의 mismatch summary 결과**를 기반으로 실질적인 접근성 품질 수준을 계산하여 표시합니다.

### Crash Issues

Crash Issues는 TalkBack Quality와 별도로 runtime 안정성 문제를 표시합니다.

위치:

```text
Run History
↓
Batch Details
↓
Device Details
↓
TalkBack Quality
↓
Quality Issues
↓
Crash Issues
```

Crash Card 표시 항목:

- Crash Event ID (`CRASH-0001`)
- Crash Type (`CONFIRMED_CRASH`, `APP_TERMINATED`, `POSSIBLE_CRASH`, `ANR` reserved)
- Scenario
- Recovery Result (`CRASH_CAPTURED`, `CRASH_RECOVERED`, `CRASH_REPEATED`)
- Timestamp
- Artifact badges: Repro Guide, Screenshot, Helper Dump, Window Dump

사용 가능한 동작:

- `View Repro Guide`: `crash_repro.md`를 modal에서 확인
- `View Screenshot`: `crash_screenshot.png`를 modal에서 확인
- `Download Artifacts`: crash artifact directory를 zip으로 다운로드

상태 표시:

- Loading: crash summary API 응답 대기
- Empty: `No crash issues detected.`
- Error: `Crash summary unavailable`

Artifact viewer 실패는 Crash Issues modal 안에서만 표시되며 Device Details 전체 렌더링을 중단하지 않습니다.

---

## Known Issues

- **Log Tail 누락 가능성 (P3)**: 간헐적으로 Log Tail의 최종 라인에 `[MAIN] script end` 또는 `scenario_summary` 계열 마지막 로그가 보이지 않는 현상이 있으나 실제 결과 집계에는 영향을 주지 않습니다.
- **Live Monitor 미연동 (Phase M-4-H 이후 개선 예정)**: 현재 실시간 시나리오 진행률 및 Step 카운트 등이 Batch 모드 API(`/api/batch/status`)에서 제대로 렌더링되지 않는 한계가 존재합니다. 우선적으로 Log Tail 표시 중심으로 운영됩니다.
