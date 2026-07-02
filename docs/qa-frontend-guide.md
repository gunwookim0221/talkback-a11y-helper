# QA Frontend Overview

Updated for V10: 2026-07-03

## 목적
QA Frontend는 TalkBack 기반 접근성 자동화 테스트의 설정, 실행 제어, 실시간 모니터링 및 결과 분석을 통합 제공하는 대시보드입니다.

## 시스템 구성

- **ADB**: 디바이스 연결 상태와 기본 제어 환경을 확인하는 섹션입니다.
- **TalkBack A11y Helper**: 디바이스 내 헬퍼 앱의 설치 여부와 서비스 활성화 상태를 관리합니다.
- **Run**: 테스트 모드와 환경을 설정하고 실제 실행 및 중지를 제어하는 패널입니다.
- **Runtime Preflight**: 테스트 시작 전 기기의 상태가 자동화 실행에 적합한지 사전 점검합니다.
- **Live Monitor**: (이전 Runtime Dashboard) 테스트가 진행되는 동안의 실시간 상황을 모니터링합니다.
- **Scenarios**: 실행할 대상 시나리오들을 선택하고, 플러그인 모듈별 상태를 확인합니다.
- **Plugin Discovery**: 현재 SmartThings 화면에서 visible Life/Device plugin 후보를 찾고, Probe/Draft/Review/Apply/Smoke/Session Restore/Rollback Preview를 순차적으로 수행합니다.
- **Run History (Batch Runs)**: 기존 Single Run 방식을 대체하여, 이제 모든 실행은 다중/단일 단말 관계없이 Batch 모드로 실행 및 관리됩니다. 최근에 수행된 배치 실행 건들을 목록으로 모아 보여줍니다.
- **Batch Details (Device Details)**: 선택한 배치 런과 단말에 대한 시나리오 단위 통과/경고/실패 상세 정보와, 추출된 접근성 품질(TalkBack Quality), Crash Issues, V10 Shadow Validation, 로그 및 XLSX 원본 파일에 접근할 수 있습니다.

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

**Runtime Coverage Probe**
- Runtime Coverage Probe toggle이 ON이면 backend가 subprocess env에 `TB_V8_COVERAGE_PROBE=1`을 전달합니다.
- 이 toggle은 runtime probe artifact와 Coverage Probe summary card 표시를 위한 prerequisite입니다.
- probe는 aggregate reporting까지 포함하지만 기존 traversal verdict를 바꾸지는 않습니다.
- Full Run에서는 기본 ON, Smoke Run에서는 기본 OFF이며 사용자가 해제할 수 있습니다.

**Shadow Validation (Experimental)**

- Full Run에서만 활성화할 수 있고 기본 OFF다.
- 체크하면 request에 `shadow_validation=true`가 포함된다.
- backend는 해당 run의 local runtime config에만 Inventory, Quick Identify, Policy
  Mapping, Shadow Validation flag를 true로 설정한다.
- 저장소의 `config/runtime_config.json` 기본값은 변경하지 않는다.
- Shadow는 Legacy Full Run과 artifact 저장이 끝난 뒤 별도 pass로 실행된다.
- Shadow 실패는 Legacy 결과, XLSX, report를 실패로 바꾸지 않는다.

---

## Runtime Preflight

테스트 실행 전 자동화 환경 점검 항목입니다.

- **Preflight**: 종합적인 사전 점검 통과 여부 (Passed / Blocked)
- **Helper**: 헬퍼 앱의 설치 및 접근성 서비스 권한 상태
- **TalkBack**: 시스템 TalkBack(삼성/구글)의 활성화 여부
- **Foreground**: 현재 기기에서 실행 중인 포그라운드 앱 패키지
- **Popup**: 시스템 또는 외부 앱 팝업 발생 여부 및 방해 요소 감지
- **Settings**: 디바이스 설정 화면 노출 및 제어 가능 여부

장시간 full run에서는 backend가 keep-awake lifecycle을 적용합니다.

- run 시작 시 `adb shell svc power stayon true`
- run 종료 시 기존 stay-awake 값 복원

이는 V8 probe full run에서 `SCREEN_OFF`에 의한 중단을 줄이기 위한 운영 보강입니다.

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

---

## Plugin Onboarding Wizard

Plugin Discovery panel은 신규 Life / Device plugin scenario를 추가하기 위한 MVP
workflow를 제공한다.

### 기본 흐름

```text
Discover Plugins
↓
Probe
↓
Generate Draft
↓
Review Draft
↓
Apply Draft
↓
Smoke Draft
↓
Refresh Smoke Result
```

### Discovery

`Discover Plugins`는 현재 SmartThings 화면에 visible 상태로 보이는 후보 card를
수집한다.

표시 항목:

- Type
- Label
- Stable Label
- Confidence
- Source
- Known
- Existing Scenario

run 실행 중에는 discovery/probe/draft review/apply/smoke가 충돌 방지를 위해
차단될 수 있다.

### Draft Review / Apply

Draft Review는 실제 파일 수정 전 적용 가능성을 확인한다.

- scenario id 중복
- runtime config key 중복
- manual review required
- diff preview

Apply Draft는 review가 허용한 draft만 적용하며 backup을 생성한다.

### Smoke

Smoke Draft는 apply된 scenario 하나만 `max_steps=5` 기본값으로 실행한다. 시작 후
`Refresh Smoke Result`를 눌러 완료 상태와 summary를 갱신한다.

표시 항목:

- Smoke Status
- Run Status
- Result Status
- Pre-navigation Success
- Plugin Open Verified
- Steps Collected
- Failure Reason
- Log/XLSX link

### Onboarding Session

`Start Onboarding Session`은 현재 card 기준으로 wizard session을 생성한다. session은
`output/plugin_onboarding_sessions/`에 저장되며 각 단계 결과 payload를 누적한다.

Recent Onboarding Sessions에서 session을 선택하면 restore API를 호출해 가능한 panel
state를 복원한다.

### Recommendation

Session restore 후 다음 action recommendation을 표시한다.

- `ready_for_manual_validation`
- `ready_with_warning`
- `needs_probe_revision`
- `apply_rollback_candidate`
- `review_blocked`
- `incomplete`

Recommendation은 안내 전용이며 실제 commit/retry/rollback 실행은 하지 않는다.

### Rollback Preview

recommendation이 `apply_rollback_candidate`이면 `Rollback Preview` 버튼을 표시한다.
Preview는 apply backup과 현재 파일을 비교하고, 실제 rollback 전에 제거될 scenario
entry/runtime config entry와 diff preview를 보여준다.

Rollback 실행은 아직 제공하지 않는다.

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

## Coverage Probe Summary Card

Batch Details의 Device Details에는 V8 Coverage Probe summary card가 표시될 수 있습니다.

표시 지표:

- Candidates
- Attempted
- Succeeded
- Failed
- Promotable
- Promoted
- Dedup Skipped
- Screen Skipped
- Scenario Filtered

데이터 source 정책:

- `*.coverage_probe_validation.aggregate.json` 우선
- aggregate가 없으면 `*.coverage_probe_validation.json` fallback
- execution count는 `*.coverage_probe_results.aggregate.json` 또는 scenario results에서 읽음
- promotion/validation count는 validation artifact에서 읽음

상태 해석:

- aggregate source 사용 시 `Source: aggregate`
- scenario fallback 사용 시 `Source: scenario`
- probe artifact가 없으면 `Not Available`
- artifact는 있으나 candidate가 0이면 zero run으로 표시하고 "Probe artifacts found, but no candidates were recorded." 안내를 보여줍니다.

이 카드는 artifact 값을 그대로 보여 주며 backend에서 probe 결과를 재계산하지 않습니다.

## V10 Shadow Validation과 Promotion Readiness

Shadow artifact가 존재하는 Device Details에만 `V10 Shadow Validation` card가
표시된다. Shadow를 실행하지 않은 run에서는 이 card를 숨긴다.

표시 항목:

- Inventory / Identified / Identify Unknown
- MATCH / UNKNOWN / AMBIGUOUS / MISMATCH / FAILED
- Promotion Eligible
- Legacy Preserved
- Shadow Runtime
- plugin family별 comparison result

같은 card의 `Promotion Readiness` 영역은 family별
`READY`, `HOLD`, `BLOCKED`, `INSUFFICIENT_DATA`, `UNKNOWN_ONLY`를 표시한다.
단일 고신뢰 MATCH는 READY candidate일 수 있지만 최소 표본 gate를 통과하지 못하면
최종 상태는 HOLD다. 이 평가는 실제 routing을 활성화하지 않는다.

Artifact 동작:

- `Open Shadow Report`: `shadow_report.md`
- `Open Compare JSON`: `shadow_compare.json`
- `Open Readiness Report`: `promotion_readiness.md`
- `Open Readiness JSON`: `promotion_readiness.json`
- `Open Shadow Folder`: device run의 `shadow/`

Legacy는 항상 authoritative이며 UI에는 routing 전환 버튼이 없다.

---

## Known Issues

- **Log Tail 누락 가능성 (P3)**: 간헐적으로 Log Tail의 최종 라인에 `[MAIN] script end` 또는 `scenario_summary` 계열 마지막 로그가 보이지 않는 현상이 있으나 실제 결과 집계에는 영향을 주지 않습니다.
- **Live Monitor 미연동 (Phase M-4-H 이후 개선 예정)**: 현재 실시간 시나리오 진행률 및 Step 카운트 등이 Batch 모드 API(`/api/batch/status`)에서 제대로 렌더링되지 않는 한계가 존재합니다. 우선적으로 Log Tail 표시 중심으로 운영됩니다.
- **Plugin Onboarding visible-only discovery**: 현재 discovery/probe는 visible card 중심이며 bounded scroll과 자동 tab 이동은 아직 제공하지 않습니다.
- **Smoke result manual refresh**: smoke 결과는 자동 polling이 아니라 `Refresh Smoke Result` 수동 갱신 방식입니다.
- **Rollback preview only**: Apply는 backup을 만들지만 rollback 실행 API/UI는 아직 없고 preview만 제공합니다.
- **Smoke serial 미연결**: smoke request schema의 `serial`은 현재 runner 실행 경로에 직접 연결되지 않습니다.
- **V10 Controlled Routing 미구현**: Shadow/Readiness는 진단과 평가 전용이며
  production scenario selection을 변경하지 않습니다.

## Related design documents

- [semantic-value-shadow-audit.md](design/semantic-value-shadow-audit.md)
- [audit-v7-focusable-coverage-design.md](design/audit-v7-focusable-coverage-design.md)
- [V10 Phase Closure](design/v10/v10-phase-closure.md)
