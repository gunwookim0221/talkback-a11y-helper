# Phase 9.5.3 — Global Navigation Boundary Fix

## 1. Root Cause

Phase 9.5.2 artifact와 현재 코드를 다시 대조한 결과, 공통
`is_global_nav_row()` classifier의 strong-evidence 정의가 결함이었다.

기존 구현은 configured navigation label의 **substring** 일치 또는
`selected_pattern` 일치만으로 `strong_signal=True`를 만들었다. 따라서 본문 card가
generic resource token 1점과 label substring 2점을 얻으면, 실제 bottom navigation
영역이나 전용 navigation resource가 없어도 score 3으로 global navigation이 됐다.

확정된 두 counterexample은 다음과 같다.

| Object | Resource | Bounds | 기존 결과 |
|---|---|---|---|
| `Home profile Design your smart home to match your daily life` | `...:id/my_profile_card_view` | `30,310,1050,671` | `resource_hint,label`로 false global-nav |
| `Supported devices Find out which devices work with SmartThings.` | `...:id/supported_devices_card_view_layout` | `30,1158,1050,1525` | `resource_hint,label`로 false global-nav |

두 bounds 모두 1080×2640 화면의 bottom-tab 영역이 아니다. Phase 9.5.1 Menu는 이
오분류 때문에 step 2~3에서 `global_nav_entry`로 종료했다.

## 2. Classifier Contract Before / After

### Before

- configured resource-id는 substring 포함만으로 strong evidence였다.
- configured label substring은 strong evidence였다.
- `selected_pattern`도 strong evidence였다.
- bottom/left region은 1점짜리 보조 evidence였고 필수가 아니었다.
- 결과적으로 `generic resource substring + label substring`만으로 확정할 수 있었다.

### After

Strong evidence는 다음 중 하나를 요구한다.

1. configured navigation resource-id와 canonical resource-id가 정확히 일치한다.
2. configured `bottom_tabs`/`left_rail` region과 실제 bounds가 일치한다.

Label, generic resource token, selected pattern/state는 점수와 diagnostic reason을
유지하지만 **corroborating evidence**로만 사용한다. 따라서 weak evidence만으로 score가
3 이상이어도 global navigation으로 승격되지 않는다.

이 contract는 bounds-only classifier가 아니다. 실제 bottom tab의 전용 resource-id는
geometry가 없더라도 기존처럼 positive다. 반대로 전용 resource가 없는 label-based
navigation은 trusted region evidence가 함께 있어야 한다.

## 3. Positive Evidence and Weak Evidence

| Evidence | 역할 | 비고 |
|---|---|---|
| Exact configured nav resource | Strong | `menu_favorites`, `menu_devices`, `menu_services`, `menu_automations`, `menu_more` |
| Trusted bottom/left region | Strong | 유효 bounds와 numeric screen geometry 필요 |
| Configured label substring | Weak | 영어/한국어 label 지원 유지 |
| Selected announcement pattern | Weak | 단독으로 boundary를 확정하지 않음 |
| Selected state | Weak | 단독으로 boundary를 확정하지 않음 |
| Generic resource/text token | Weak | diagnostic reason과 보조 점수 유지 |

## 4. Negative / Positive Corpus

추가 unit corpus는 다음을 포함한다.

### Negative

- RCA의 `Home profile...` 및 `Supported devices...` card
- 본문 Home, Devices, Life, Routines, Menu card
- 중앙 영역 label 일치
- bottom 영역이지만 label/resource evidence가 없는 object
- generic resource substring 단독
- label substring 단독
- configured resource의 prefix만 공유하는 content resource
- label/selected는 있으나 bounds가 없는 object

### Positive

- Home / Life / Routines / Menu production resource corpus
- 동일 production resource의 한국어 label corpus
- geometry 없는 exact dedicated nav resource
- exact configured label + trusted bottom region
- 2400 및 2640 screen height의 bottom-region case

## 5. Changed Files

- `tb_runner/diagnostics.py`
  - configured resource matching을 exact match로 제한
  - label/selected pattern을 weak evidence로 변경
  - trusted region을 strong evidence로 변경
- `tests/test_diagnostics.py`
  - classifier positive/negative/boundary corpus
  - false content card가 `StopEvaluator`의 `global_nav_entry`를 유발하지 않는 회귀 테스트
- `docs/design/talkback-phase9.5.3-global-navigation-boundary-fix.md`
  - RCA, contract, tests, device validation 및 limitation 기록

Scenario/plugin/string hardcoding, token 삭제, threshold 변경, traversal/coverage/identity/
verification/recovery/anchor/parser 변경은 없다.

## 6. Test Results

| Scope | Result |
|---|---:|
| `tests/test_diagnostics.py` | 35 passed |
| Scenario/runtime config | 14 passed |
| Device pre-navigation | 12 passed |
| Collection global-nav/stop selection | 12 passed, 452 deselected |
| Diagnostics + config + anchor + focus parser + full collection flow | 544 passed |
| `git diff --check` | PASS |

확대 실행에 `test_runtime_report_parser.py`를 함께 넣었을 때 549 tests는 통과했고 36
setup errors가 발생했다. 모두 fixture가 저장소의 기존 `.test_tmp` 아래에 directory를
생성할 때 발생한 Windows `PermissionError`였으며 classifier failure가 아니다. 해당
unrelated file을 제외한 동일 안정 regression 범위는 544/544로 통과했다.

## 7. Menu Standalone Replay

환경:

- device `R3CX40QFDBP`
- current language (English surface)
- Traversal Identity V2 ON
- Evidence Ledger ON
- Identity Shadow V2 ON

첫 시도는 resumed activity가 SmartThings main이 아니라
`com.samsung.android.plugin.lightsync.MainActivity`였기 때문에 pre-navigation에서
`no_bottom_nav_candidates`로 abort됐다. classifier transaction 이전 실패이므로 acceptance
결과에서 제외했다. SmartThings launcher activity로 복귀한 뒤 재실행했다.

재실행 결과:

| Metric | Result |
|---|---:|
| Raw / filtered rows | 23 / 23 |
| Coverage | 15/26 (57.7%) |
| `Home profile...` | `is_global_nav=false`, step 2 PASS |
| `Supported devices...` | `is_global_nav=false`, step 3 PASS |
| Terminal | step 22 `global_nav_entry` |
| Terminal node | `menu_favorites`, `Home, Tab 1 of 5.` |
| Terminal evidence | `resource_id,label`, bounds `23,2316,217,2496` |
| Reconciliation | PASS |
| Evidence | 708 events; duplicate 0, orphan 0, write failure 0 |

Phase 9.5.1의 3 raw / 2 result rows 및 2/15 coverage와 비교하면 false boundary 제거 후
Menu가 23 rows를 수집했고 coverage는 nominal과 같은 15/26으로 복원됐다. 실제 bottom
navigation은 계속 탐지됐다.

## 8. Home / Life / Routines Boundary Replay

세 scenario를 같은 장비에서 제한 실행했다.

| Scenario | Raw rows | Terminal | Global-nav evidence | Coverage |
|---|---:|---|---|---:|
| Home | 7 | `global_nav_entry` at `menu_favorites` | `resource_id,label,selected_pattern` | 5/17 (29.4%) |
| Life | 10 | `repeat_no_progress` on content | no false global-nav row | 5/17 (29.4%) |
| Routines | 7 | `global_nav_entry` at `menu_favorites` | `resource_id,label` | 4/19 (21.1%) |

Reconciliation은 PASS였고 1,442 evidence events에서 duplicate/orphan/write failure는 모두
0이었다. Life의 `repeat_no_progress` 및 낮은 scenario coverage는 이번 classifier scope의
새 회귀로 판단할 근거가 없으며 정책 변경 대상이 아니다.

## 9. Full Run Result

32-scenario Full Run은 수행하지 않았다. 최근 동일 acceptance run은 약 9,358초(약 2.6시간)
였고, 이번 Phase는 먼저 Menu 및 boundary scenario의 classifier defect를 검증하는 제한
범위다. Menu와 Home/Life/Routines 단독 검증 및 544-test regression은 통과했지만,
cross-plugin aggregate parity는 다음 Full Acceptance에서 확인해야 한다.

## 10. Performance Impact

### Classifier calculation

Exact resource comparison 및 strong-signal boolean 변경뿐이며 새 I/O, retry, sleep, dump,
polling은 없다. 별도 profiler를 활성화하지 않았으므로 sub-millisecond 수치를 주장하지
않지만 계산 복잡도는 기존과 동일한 configured-resource/label 선형 scan이다.

### Restored workload

Menu 재실행 runtime은 scenario summary 기준 193.1초였다. 이는 classifier 비용 증가가
아니라 2~3 step 조기 종료 대신 22 traversal steps와 실제 bottom boundary까지 수행한
정상 workload다.

### Full Run wall time

Full Run을 수행하지 않아 aggregate wall-time before/after는 비교할 수 없다.

## 11. Remaining Limitations and Risks

- 32-scenario Full Run과 cross-plugin aggregate parity는 미검증이다.
- 한국어 navigation은 unit corpus로 검증했지만 이번 실기기 replay surface는 영어였다.
- trusted bottom-region은 기존 72% geometry contract를 유지한다. screen geometry가 없으면
  label-only object는 보수적으로 negative이며 exact configured resource가 필요하다.
- navigation container/parent hierarchy evidence는 현재 row schema에서 classifier input으로
  사용하지 않는다. 이번 defect를 고치는 데 필요하지 않아 scope를 확장하지 않았다.
- Exact resource matching은 configured resource의 prefix를 공유하는 content view가 strong
  signal이 되는 것을 막는다. 실제 runtime corpus의 bottom tabs는 exact resource로 확인됐다.

## 12. Acceptance Verdict

**PASS WITH VALIDATION LIMITATION**

두 RCA counterexample은 실기기에서 negative가 됐고, 실제 bottom navigation은 positive로
유지됐다. Menu 조기 종료가 제거되고 nominal row/coverage가 복원됐으며 관련 regression과
reconciliation도 통과했다. 다만 명시된 32-scenario Full Run을 수행하지 않았으므로 완전한
PASS로 승격하지 않는다.
