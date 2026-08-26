# TalkBack A11y Helper

`talkback-a11y-helper`는 SmartThings TalkBack 환경에서 시나리오 기반 접근성
검증을 실행하고, 실제 TalkBack focus와 화면/발화 evidence를 수집해 사람이 검토할
수 있도록 하는 시스템입니다. Android Helper, Python Runner, QA Frontend가 하나의
controlled/manual validation workflow를 이룹니다.

> 이 문서는 현재 `main` 구현의 요약입니다. 과거 acceptance 결과는 당시 실행의
> 범위와 날짜를 보존한 historical evidence이며, 현재 구현 capability나 최신
> physical-device validation result와 같은 의미가 아닙니다.

---

## 프로젝트 구성 (현재 기준)

### 1) Android Helper (`app/`)

- `AccessibilityService` 기반 helper APK
- ADB broadcast 액션 수신
- 트리 덤프 / 포커스 이동 / 클릭 / 스크롤 / 텍스트 입력 수행

### 2) Python Runner (`script_test.py`, `tb_runner/`, `talkback_lib/`)

- 시나리오 기반 수집 실행
- step row 생성/정제/저장(`raw/filtered/summary/result`)
- overlay 처리, traversal/recovery, stop 정책, diagnostics 로깅
- actual TalkBack focus, visible text, speech observation, focus/evidence,
  screenshot/crop, XLSX/JSON/log artifact 수집
- V10 opt-in Shadow Validation과 Promotion Readiness reporting

### 3) QA Frontend (`qa_frontend/backend/`, `qa_frontend/frontend/`)

- device/ADB/Helper/TalkBack preflight
- Full Validation, Quick Smoke, Custom/Debug run profile과 scenario selection
- Batch 실행, 현재 상태/진행률, Run History, crash/coverage/identity 확인
- QA accessibility review와 automation diagnostics를 분리한 Review Required projection
- Candidate, Offline Validation, Comparator 결과와 Baseline metadata 확인

### 4) V10 현재 상태

V10은 Device Card를 runtime inventory로 수집하고, card를 짧게 열어 capability
resource-id/XML 구조로 plugin family를 식별한 뒤 versioned policy registry의 scenario
candidate와 Legacy 결과를 비교한다.

- 구현 완료: Runtime Inventory, Quick Plugin Identify, Policy Registry, Shadow
  Validation, Shadow-only Runner, QA Frontend reporting, Promotion Readiness
- V10 비교의 기준은 기존 Legacy scenario result이며, V10 자체는 production
  routing/traversal을 수행하지 않음
- 기본값: V10 feature flags와 QA Frontend Shadow Validation은 모두 OFF이며 V10은
  production traversal authority가 아님
- 미구현: Controlled Routing과 V10 traversal 활성화

개발 중 기존 Full Run을 반복하지 않고 Shadow만 재실행하려면:

```powershell
python tools/run_v10_shadow_only.py --run-dir "<device-run-dir>" --output-suffix debug
```

현재 운영 설명은 `docs/system-overview.md`, 상세 종료 판단은
`docs/design/v10/v10-phase-closure.md`를 참조한다.

### 5) Canonical Identity Shadow Phase 8 / Production Migration Phase 8.5

Traversal Evidence의 physical focus observation을 Canonical Identity로 정규화해
`MOVE_CONFIRMED`, `STATIC_FOCUS`, `MOVE_TO_OTHER_NODE`, `SNAP_BACK`,
`INDETERMINATE`를 판정하는 별도 shadow-only 경로가 제공됩니다.

- 기본값: Traversal Identity V2가 Production Traversal Engine으로 ON이며, 필요한
  Evidence Ledger와 Identity Shadow V2도 run-scoped로 함께 활성화
- Legacy Compatibility: QA Frontend에서 Traversal Engine을 OFF하면 해당 run에만
  `TB_TRAVERSAL_IDENTITY_V2_ENABLED=0`을 전달해 기존 Legacy traversal을 사용
- 출력: append-only V2 ledger event, reconciliation metrics, read-only distribution card
- Phase 8 보존: Legacy reducer와 production traversal semantics unchanged
- Phase 8.5 production default: strong closed transaction만 progress/visit/stop/recovery gate에 사용;
  incomplete/indeterminate/other-node/snap-back은 legacy fallback
- OFF 보존: Phase 8.5 flag OFF에서는 기존 traversal/anchor/representative/visit/coverage/
  audit/summary/XLSX 경로 유지
- 현재 production default: Traversal Identity V2가 run-scoped Production Traversal Engine으로
  ON이며, 필요한 Evidence Ledger와 Identity Shadow V2도 함께 활성화
- strong closed transaction만 progress/visit/stop/recovery gate에 제한적으로 사용하고,
  incomplete/indeterminate/other-node/snap-back은 Legacy fallback
- `TB_TRAVERSAL_IDENTITY_V2_ENABLED=0`을 명시한 run은 Legacy Compatibility path를 사용

이 문서에 연결된 Phase 8/8.5 수치는 해당 문서에 기록된 당시 acceptance evidence입니다.
현재 `main`의 최신 32-scenario physical-device Full Validation 결과로 재해석하지 않습니다.

상세: `docs/design/talkback-identity-shadow-phase8-completion.md`,
`docs/design/talkback-production-traversal-migration.md`

---

## Python client 구조 요약 (PR14 완료)

PR14-A/B/C까지 반영되어 Python client 책임 분해가 완료되었습니다.

- `A11yAdbClient` (`talkback_lib/__init__.py`): 공개 API façade
- low-level 분리
  - `adb_executor.py`, `logcat_reader.py`, `action_result_parser.py`, `helper_bridge.py`
- trace/row assembly 분리
  - `focus_trace_builder.py`, `focus_service.py`, `step_row_builder.py`, `step_collection_service.py`
- 결과: 공개 계약은 유지하면서 내부 책임을 모듈별로 분리

상세: `docs/current-client-architecture.md`

---

## Canonical Full Validation

구현의 authoritative source는
[`canonical_full_scenario_ids()`](tb_runner/scenario_config.py)이며,
`TAB_CONFIGS`의 scenario ID를 그대로 canonical Full membership으로 사용합니다.
현재 source에서 확인되는 Full set은 **32개**입니다.

- **6개 main/navigation**: `global_nav_main`, `home_main`, `devices_main`,
  `life_main`, `routines_main`, `menu_main`
- **12개 Device plugin**: `device_smoke_sensor_plugin`,
  `device_water_leak_sensor_plugin`, `device_motion_sensor_plugin`,
  `device_door_lock_plugin`, `device_air_purifier_plugin`, `device_tv_plugin`,
  `device_washer_plugin`, `device_humidity_sensor_plugin`,
  `device_temperature_humidity_sensor_plugin`, `device_camera_plugin`,
  `device_home_camera_plugin`, `device_audio_plugin`
- **12개 Life plugin**: `life_food_plugin`, `life_air_care_plugin`,
  `life_home_care_plugin`, `life_energy_plugin`, `life_pet_care_plugin`,
  `life_family_care_plugin`, `life_plant_care_plugin`,
  `life_clothing_care_plugin`, `life_find_plugin`, `life_video_plugin`,
  `life_home_monitor_plugin`, `life_music_sync_plugin`
- **2개 auxiliary/support**: `home_safe_plugin`, `settings_entry_example`

`config/runtime_config.json`은 같은 32개 scenario entry를 담고 있지만, checked-in
기본값에서 `enabled`인 항목은 targeted execution을 위한 1개뿐입니다. 이 `enabled`
값은 canonical Full membership을 정의하지 않습니다. QA Frontend의 Full Validation은
위 32개를 모두 선택하고, 일부만 선택하면 Custom Run으로 분류합니다.

## Candidate / Comparator / Baseline workflow

```text
Full Validation → Candidate → Offline Validation → Compare UI/Comparator
  → Markdown/JSON Report → Human Approval → Approved Baseline + Observation Bundle
```

Full Validation profile은 Clean launch, Full mode, canonical 32개 scenario, Coverage
Probe, Evidence Ledger, Identity V2, Production Traversal V2, Profiler를 사용합니다.
Shadow Validation은 별도 opt-in입니다. 완전한 terminal Full run과 필요한 artifact가
있을 때 Batch Runner가 Candidate를 additive하게 만들 수 있으며, Candidate는 자동 승인되지
않습니다.

Comparator는 선택한 Candidate와 Approved Baseline을 읽고 deterministic JSON/Markdown
report와 verdict를 만듭니다. QA Frontend와 Comparator는 Baseline을 자동 변경하거나
approval을 수행하지 않습니다. `qa_frontend_runs/`와 raw logs/XLSX는 Git에 포함되지
않으므로 clean clone에서는 local Candidate 목록이 비어 있을 수 있습니다.

현재 readiness는 **Production Ready with Limitations (controlled/manual)**입니다.
사람의 review/approval이 필요하며, unattended approval, remote CAS/durable history,
일반적인 multi-device Baseline family 운영, 모든 미래 Candidate의 portable bundle 자동
첨부는 제공되지 않습니다. 모델 policy도 exact reviewed model 기준이며 unknown model을
자동 승인하지 않습니다.

## Historical evidence의 해석

다음 문서의 결과는 각 문서에 기록된 당시 scope/date의 evidence로만 해석합니다.

- Phase 8/8.5 identity/traversal acceptance와 recovery 수치
- 2026-07-03에 기록된 Global `7/7`, Life `12/12`, Device `12/12` group 결과
- Phase 9.5 및 9.5.1의 Full Run/regression 결과와 RCA
- Phase 10 offline/comparator acceptance

이 결과들은 현재 `main`의 capability와 설계 계약을 이해하는 데 유용하지만, 최신
HEAD가 32-scenario physical-device Full Validation을 통과했다는 증거로 재사용하지
않습니다. 현재 tracked evidence에는 최신 HEAD에 대한 새로운 32-scenario physical
acceptance result를 주장할 수 있는 기록이 없으므로, 이 저장소는 capability와
controlled/manual 운영 준비 상태를 문서화할 뿐 새 validation 결과를 발명하지 않습니다.

## 문서 시작점

- [문서 인덱스](docs/README.md)
- [시스템 개요](docs/system-overview.md)
- [아키텍처](docs/architecture.md)
- [운영 Runbook](docs/operations/talkback-operational-runbook.md)
- [QA Frontend README](qa_frontend/README.md) / [검증 계약](qa_frontend/VALIDATION.md)
- [현재 Python client 구조](docs/current-client-architecture.md)
- [Runner 흐름](docs/runner_flow.md) / [scenario 설정](docs/scenario-config.md) /
  [runtime 설정](docs/runtime-config.md)
- [Phase 10.2.5 Run Profiles](docs/design/talkback-phase10.2.5-run-profiles.md)
- [Phase 10.4 Compare UI](docs/design/talkback-phase10.4-compare-ui.md)
- [Comparator finalization](docs/design/talkback-phase10.3d-comparator-finalization.md)
- [V10 closure](docs/design/v10/v10-phase-closure.md)

새 PC에서는 다음 의존성을 설치한 뒤 [운영 Runbook](docs/operations/talkback-operational-runbook.md)의
preflight 순서를 따릅니다.

```powershell
python -m pip install -r requirements-script_test.txt
python -m pip install -r requirements-qa_frontend.txt
Set-Location qa_frontend/frontend
npm install
```

Runner 실행:

```powershell
python script_test.py
```

QA Backend/Frontend 실행:

```powershell
uvicorn qa_frontend.backend.main:app --reload
Set-Location qa_frontend/frontend
npm run dev
```

물리 단말 실행은 연결된 Android device, USB debugging, Helper APK, TalkBack,
지원 모델 policy와 locale preflight가 필요합니다. 이 문서는 physical Full Validation을
자동으로 실행하지 않습니다.

## `script_test.py` 실행 환경 준비

새 PC 또는 다른 Python 버전(권장: 3.10~3.12)에서 `script_test.py`를 실행할 때는 아래처럼 의존성을 먼저 설치하세요.

```bash
python -m pip install -r requirements-script_test.txt
```

실행:

```bash
python script_test.py
```

---

## Debug Bundle 자동 캡처 (Python Runner)

`capture_debug_bundle.py`는 기본적으로 **Life plugin list scroll_capture**를 자동 수행합니다.

- 기본 실행: `python capture_debug_bundle.py`
- 선택 옵션:
  - `--mode scroll_capture` (기본: `scroll_capture`)
  - `--max_steps 10`
  - `--save_xml true|false` (기본: `true`)

저장 경로는 timestamp 기반으로 생성됩니다.

- `output/capture_bundles/life_plugin_scroll_capture/<run_id>/step_XX/`
- 각 step에는 `helper_dump.json`, `meta.json`, `screenshot.jpg`가 저장됩니다.
- `--save_xml=true`일 때 `window_dump.xml`도 함께 저장됩니다.
- run 루트에는 스텝 메타를 통합한 `summary.json`이 저장됩니다.
- `meta.json`에는 resource id 분석 필드(`resource_ids_top_n`, `resource_id_counts`, `resource_id_sources`, `resource_ids_card_like_top_n`)와 chrome 분리 필드(`top_bar_present`, `bottom_tab_present`, `chrome_filtered_labels`, `content_candidate_labels`)가 포함됩니다.
- `summary.json`에는 step 통합 resource id 필드(`resource_ids_union_top_n`, `resource_ids_card_like_union_top_n`, `steps_with_no_resource_ids` 등)가 포함됩니다.

---

## Overlay first-row 경로 디버그 게이트

overlay first-row 생명주기 추적 로그는 기본 OFF이며, 아래 환경변수 하나로만 활성화됩니다.

- `TB_OVERLAY_FIRST_ROW_DEBUG=true`

활성화 시 `[OVERLAY][FIRSTROW][...]` prefix 로그가 추가되어 synthetic 생성/append/반환/caller 수신/export 직전 경로를 추적할 수 있습니다.

## Overlay repeat 원인 추적 디버그 게이트

overlay 내부 second-item 반복(`Delete`, `Manage devices`, `Add device`) 원인 추적 로그는 기본 OFF이며, 아래 환경변수 하나로만 활성화됩니다.

- `TB_OVERLAY_REPEAT_DEBUG=true`

활성화 시 `[OVERLAY][REPEAT][...]` prefix 로그가 duplicate 후보 구간에서만 추가되어 node identity/diff/children/fingerprint_parts/duplicate_decision/break_context를 한 번에 추적할 수 있습니다.
