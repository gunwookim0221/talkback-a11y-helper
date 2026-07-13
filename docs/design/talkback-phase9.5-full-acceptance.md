# TalkBack Phase 9.5 Full Acceptance

상태: **FAIL**  
기준일: 2026-07-14  
기준 commit: `e15ec2d2123cd14b8bd0624ffc11ad37ba1bf386`  
단말: `SM-F741N` / `R3CX40QFDBP` / locale `en-US`

## 1. Executive Summary

Phase 9.5는 traversal을 수정하지 않고 Production Traversal Engine의 32-scenario
full acceptance와 runtime profile을 수행했다. 실행 프로세스는 exit code `0`으로
종료했고 32개 scenario profiler를 모두 생성했다. Evidence ledger도 reconciliation
`PASS`, orphan `0`, duplicate `0`, write failure `0`을 유지했다.

그러나 Production Traversal Engine의 32-scenario 안정성 acceptance는 통과하지 못했다.

- 32개 scenario를 모두 시도했지만 정상 traversal을 시작한 scenario는 30개다.
- `life_home_care_plugin`과 `life_clothing_care_plugin`은 traversal 전
  `ANCHOR_ABORT`로 종료됐다. 이전 full run에서는 Clothing Care만 abort했다.
- Focusable Coverage는 `57.7%`에서 `52.5%`로 하락했다. denominator가 동적 UI에
  따라 `673`에서 `560`으로 바뀌었음에도 다수 scenario에서 큰 하락이 동시에 보였다.
- Ledger recovery candidate 결과는 `19 attempts / 11 recovered`에서
  `23 attempts / 9 recovered`로 악화됐다.
- XLSX row quality의 FAIL은 `1`에서 `2`로 증가했다. 기존 Home Monitor FAIL과 함께
  Menu의 `EMPTY_VISIBLE` FAIL이 새로 발생했다.
- V2 transaction integrity는 유지됐지만 `INDETERMINATE` 비율은
  `30/869 (3.5%)`에서 `53/793 (6.7%)`로 증가했다.
- scenario transaction 합계 runtime은 `10,803.5 s`에서 `9,358.4 s`로
  `13.4%` 감소했다. 하지만 steps가 `704`에서 `613`으로 줄고 row가 `567`에서
  `482`로 줄었으며 Home Care가 traversal 전 abort했으므로 이 감소를 순수 최적화
  효과로 인정할 수 없다.

따라서 Phase 10으로 바로 진행하지 않는다. 먼저 Phase 9.5 acceptance blocker를
재현·분류하고 동일 screen/work 조건의 full rerun에서 coverage, recovery, stop,
identity를 다시 통과시켜야 한다.

## 2. 실행 조건과 Evidence

### 2.1 Phase 9.5 run

- Clean launch
- Current language (`en-US`)
- Runtime Coverage Probe OFF
- Traversal Identity V2 default ON
- Evidence Ledger ON
- Identity Shadow V2 ON
- Runtime Profiler ON
- wall time: 약 `9,639 s` (`2 h 40 m 39 s`)
- scenario profiler: `32/32`
- Coverage Probe result artifact: `0`개

Current artifacts:

- `tmp_phase95_full_acceptance/talkback_compare_20260714_001506.normal.log`
- `tmp_phase95_full_acceptance/talkback_compare_20260714_001506.xlsx`
- `tmp_phase95_full_acceptance/talkback_compare_20260714_001506.evidence.jsonl`
- `tmp_phase95_full_acceptance/talkback_compare_20260714_001506.evidence_manifest.json`
- `tmp_phase95_full_acceptance/talkback_compare_20260714_001506.evidence_reconciliation.json`
- `tmp_phase95_full_acceptance/talkback_compare_20260714_001506.focusable_coverage.json`
- `tmp_phase95_full_acceptance/talkback_compare_20260714_001506.profiler/*.profiler.json`

### 2.2 비교 기준

32-scenario before 기준은
`qa_frontend_runs/batch_20260712_214922/device_SM-F741N_R3CX40QFDBP`다. 이 run은
Phase 9.4 이전 traversal이고 32개 scenario를 요청했다. Coverage Probe가 ON이었지만
promoted row는 `0`이므로 Coverage row 자체를 증대시키지는 않았다. 다만 batch wall
time은 Probe 비용 때문에 Phase 9.5와 직접 비교하지 않는다. Scenario runtime은 두
ledger의 `SCENARIO_TRANSACTION_OPENED`부터 `SCENARIO_TERMINAL`까지 동일한 범위로
계산했다.

Phase 9.4 문서의 standalone baseline은 Safe `363.433 s`, Motion `229.461 s`다.
Phase 9.5 full run은 각각 `357.783 s`와 `231.458 s`로, standalone 기준에서는
Safe `-1.6%`, Motion `+0.9%`다. 이는 둘 다 실질적으로 동일 범위이며 Phase 9.4의
단일-scenario 성능 결론을 뒤집지 않는다.

## 3. Full Run 결과

### 3.1 Aggregate

| 항목 | Before full | Phase 9.5 | 판정 |
|---|---:|---:|---|
| Requested scenarios | 32 | 32 | 동일 |
| Traversal completed | 31 | 30 | Regression |
| Anchor abort | 1 | 2 | Regression |
| Scenario passed / warning / no-target / failed | 8 / 23 / 1 / 0 | 9 / 21 / 2 / 0 | no process FAIL, no-target 증가 |
| Parsed steps | 704 | 613 | `-91` (`-12.9%`) |
| XLSX clean / review / fail rows | 391 / 175 / 1 | 342 / 138 / 2 | FAIL 증가 |
| Shadow pass / review / warn / fail | 369 / 137 / 60 / 1 | 294 / 100 / 86 / 2 | Regression |
| Focusable Coverage | 57.7% | 52.5% | Regression |
| Recovery candidate attempts / recovered | 19 / 11 | 23 / 9 | Regression |
| Evidence transactions | 869 | 793 | work 감소와 동반 |
| Evidence reconciliation | PASS | PASS | 유지 |
| Orphan / duplicate / write failure | 0 / 0 / 0 | 0 / 0 / 0 | 유지 |

`failed_scenarios=0`은 process/scenario aggregation 결과다. 이는 XLSX row-level
`final_result=FAIL` 2건과 같은 의미가 아니다. Phase 9.5의 두 row FAIL은 다음과 같다.

| Scenario | Step | Failure | 상태 |
|---|---:|---|---|
| `menu_main` | 1 | `EMPTY_VISIBLE`, high-confidence, `SHADOW_FAIL` | 신규 |
| `life_home_monitor_plugin` | 1 | `EMPTY_VISIBLE`, high-confidence, `SHADOW_FAIL` | 기존 known issue 재현 |

### 3.2 Evidence와 Identity

| 항목 | Before | Phase 9.5 |
|---|---:|---:|
| Ledger events | 27,822 | 25,016 |
| V2 COMPLETE / PARTIAL | 866 / 3 | 791 / 2 |
| V2 high-confidence / indeterminate confidence | 839 / 30 | 740 / 53 |
| MOVE_CONFIRMED | 624 (71.8%) | 509 (64.2%) |
| STATIC_FOCUS | 214 (24.6%) | 230 (29.0%) |
| INDETERMINATE | 30 (3.5%) | 53 (6.7%) |
| MOVE_TO_OTHER_NODE | 1 | 0 |
| SNAP_BACK | 0 | 1 |

Ledger integrity는 PASS지만 identity 결과 분포는 안정적이라고 볼 수 없다.
`INDETERMINATE`의 절대 건수와 비율이 모두 증가했고 Family Care에서 실제
`SNAP_BACK` 1건이 기록됐다. 이는 reducer failure로 단정할 증거는 아니지만
“Traversal Identity Regression 없음” acceptance를 입증하지 못한다.

## 4. Scenario별 Runtime Profiler

모든 profiler duration은 inclusive다. `verification_poll`, `focus_in_bounds`,
`recovery_executor`, `row_write`는 `traversal_loop`와 중첩될 수 있으므로 합산하지 않는다.
Before runtime도 profiler가 아니라 동일 ledger scenario transaction 범위에서 계산했다.

| Scenario | Before s | 9.5 s | Delta | Loop | Verify | Recovery | Focus | Discovery | Persist |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `global_nav_main` | 85.4 | 89.8 | +5.2% | 37.3 | 7.4 | 0.0 | 4.2 | 0.7 | 0.000 |
| `home_main` | 131.9 | 108.0 | -18.1% | 53.6 | 9.0 | 0.0 | 6.2 | 0.7 | 0.000 |
| `home_safe_plugin` | 423.3 | 357.8 | -15.5% | 151.4 | 46.8 | 15.9 | 26.2 | 0.7 | 0.000 |
| `life_food_plugin` | 506.2 | 595.0 | +17.5% | 323.7 | 66.5 | 5.5 | 46.3 | 0.7 | 0.000 |
| `life_air_care_plugin` | 345.0 | 389.2 | +12.8% | 196.2 | 64.2 | 27.8 | 28.4 | 0.7 | 0.000 |
| `life_home_care_plugin` | 323.5 | 28.2 | -91.3% | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.000 |
| `life_energy_plugin` | 575.7 | 342.4 | -40.5% | 149.8 | 31.8 | 0.1 | 23.7 | 0.7 | 0.000 |
| `devices_main` | 134.7 | 140.6 | +4.4% | 71.7 | 11.9 | 0.0 | 12.4 | 0.7 | 0.000 |
| `device_smoke_sensor_plugin` | 229.7 | 234.4 | +2.0% | 115.8 | 20.1 | 0.0 | 13.4 | 0.7 | 0.000 |
| `device_water_leak_sensor_plugin` | 233.7 | 233.0 | -0.3% | 114.7 | 19.3 | 0.0 | 13.4 | 0.7 | 0.000 |
| `device_motion_sensor_plugin` | 254.5 | 231.5 | -9.0% | 114.7 | 19.3 | 0.0 | 12.9 | 0.7 | 0.000 |
| `device_door_lock_plugin` | 277.2 | 255.4 | -7.9% | 127.4 | 21.0 | 0.0 | 14.1 | 0.7 | 0.000 |
| `device_air_purifier_plugin` | 507.9 | 405.2 | -20.2% | 214.3 | 44.5 | 0.0 | 38.7 | 0.8 | 0.000 |
| `device_tv_plugin` | 435.0 | 434.6 | -0.1% | 232.4 | 41.3 | 0.0 | 38.5 | 0.8 | 0.000 |
| `device_washer_plugin` | 467.5 | 404.7 | -13.4% | 225.6 | 52.5 | 0.0 | 41.9 | 0.8 | 0.000 |
| `device_humidity_sensor_plugin` | 280.0 | 266.7 | -4.8% | 127.0 | 19.7 | 0.0 | 14.7 | 0.7 | 0.000 |
| `device_temperature_humidity_sensor_plugin` | 283.4 | 270.2 | -4.7% | 131.4 | 21.2 | 0.0 | 15.8 | 0.7 | 0.000 |
| `device_camera_plugin` | 440.8 | 329.0 | -25.4% | 165.2 | 34.3 | 6.7 | 30.6 | 0.8 | 0.000 |
| `device_home_camera_plugin` | 271.2 | 243.8 | -10.1% | 115.8 | 21.2 | 0.3 | 14.1 | 0.7 | 0.000 |
| `device_audio_plugin` | 369.3 | 346.8 | -6.1% | 165.2 | 29.8 | 0.0 | 22.6 | 1.6 | 0.000 |
| `life_main` | 472.0 | 427.0 | -9.5% | 108.2 | 42.9 | 35.9 | 24.6 | 1.5 | 0.000 |
| `routines_main` | 165.1 | 111.3 | -32.6% | 41.6 | 5.8 | 0.0 | 5.6 | 1.6 | 0.000 |
| `menu_main` | 266.3 | 73.1 | -72.5% | 20.3 | 4.4 | 0.0 | 2.5 | 1.6 | 0.000 |
| `settings_entry_example` | 496.9 | 409.5 | -17.6% | 235.5 | 65.4 | 26.2 | 36.5 | 1.6 | 0.000 |
| `life_pet_care_plugin` | 540.6 | 458.1 | -15.3% | 203.0 | 36.8 | 0.0 | 30.4 | 1.4 | 0.000 |
| `life_family_care_plugin` | 628.9 | 553.2 | -12.0% | 225.4 | 34.2 | 0.0 | 34.3 | 1.4 | 0.000 |
| `life_plant_care_plugin` | 382.1 | 411.5 | +7.7% | 162.1 | 25.7 | 0.0 | 27.1 | 1.6 | 0.000 |
| `life_clothing_care_plugin` | 43.5 | 40.7 | -6.3% | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.000 |
| `life_find_plugin` | 224.7 | 205.6 | -8.5% | 50.4 | 9.6 | 0.5 | 6.1 | 1.4 | 0.000 |
| `life_video_plugin` | 422.7 | 319.5 | -24.4% | 85.8 | 34.7 | 26.1 | 16.4 | 1.4 | 0.000 |
| `life_home_monitor_plugin` | 413.3 | 476.3 | +15.2% | 273.5 | 57.7 | 0.0 | 33.7 | 1.4 | 0.000 |
| `life_music_sync_plugin` | 171.4 | 165.9 | -3.2% | 52.1 | 10.4 | 0.5 | 4.6 | 1.3 | 0.000 |

합계 runtime은 감소했지만 Food `+17.5%`, Home Monitor `+15.2%`, Air Care
`+12.8%`는 느려졌다. 반대로 Home Care `-91.3%`와 Menu `-72.5%`는 성능 개선이
아니라 work 손실/조기 종료와 함께 발생했다. 따라서 full-set runtime acceptance는
“전체가 빨라졌다”가 아니라 **workload parity 불충분**으로 판정한다.

## 5. Scenario 유형별 Runtime

유형은 서로 배타적이지 않다. 실제 normal log marker와 scenario contract를 기준으로
중첩 태그를 부여했다. 예를 들어 Safe는 Local Tab, Recovery, Overlay, WebView,
Cross Plugin에 모두 포함된다.

| 유형 | N | 평균 runtime | Scenario |
|---|---:|---:|---|
| Main Tab | 6 | 158.3 s | Global Nav, Home, Devices, Life, Routines, Menu |
| Local Tab | 24 | 345.4 s | Safe, Settings, sensor/device plugins, 대부분 Life plugins |
| Scroll | 8 | 339.1 s | Air Purifier, Audio, Camera, Door Lock, Humidity, Temp/Humidity, TV, Washer |
| Recovery | 11 | 344.1 s | Safe, Camera, Home Camera, Air Care, Energy, Find, Food, Life main, Music Sync, Video, Settings |
| Overlay | 9 | 395.1 s | Safe, Air Care, Energy, Find, Food, Home Monitor, Pet, Plant, Video |
| WebView | 2 | 408.0 s | Safe, Pet Care |
| Empty State | 13 | 300.2 s | Home, sensor/device empty states, Family Care, Video |
| Onboarding | 1 | 409.5 s | Settings entry example |
| Cross Plugin | 25 | 320.0 s | 모든 `*_plugin` scenario |

Detection contract:

- Local Tab: `[STEP][local_tab_*]` 또는 `[LOCAL_TAB]`
- Scroll: `[DEVICE][scroll]`, `[SCROLL_TOP]`, `[SCROLL_BOTTOM]`
- Recovery: scenario profiler `recovery[]`
- Overlay: `[OVERLAY][break]`
- WebView: 실제 focus/dump class `android.webkit.WebView`
- Empty State: `status_exhausted_excluded` 또는 명시적 empty-state detection
- Onboarding: onboarding scenario contract 또는 detected onboarding route

## 6. Profiler Top Ranking

32개 scenario runtime 합계 `9,358.4 s`를 분모로 한 inclusive ranking이다.

| Rank | Metric | Duration | Runtime 대비 | Count |
|---:|---|---:|---:|---:|
| 1 | `traversal_loop` | 4,290.8 s | 45.85% | 723 |
| 2 | `verification_poll` | 909.3 s | 9.72% | 746 |
| 3 | `focus_in_bounds` | 640.1 s | 6.84% | 746 |
| 4 | `row_write` | 381.9 s | 4.08% | 723 |
| 5 | `recovery_executor` | 145.4 s | 1.55% | 723 |
| 6 | `candidate_discovery` | 30.8 s | 0.33% | 30 |
| 7 | `recovery_planning` | 12.3 s | 0.13% | 43 |
| 8 | `candidate_ranking` | 6.2 s | 0.07% | 889 |

`persistence`는 총 약 `0.003 s`로 기록됐다. 그러나 normal log의 periodic XLSX save와
scenario 간 wall gap은 이 metric에 포함되지 않는다. Scenario profiler 합계와 shell
wall time 차이는 약 `280.5 s`다. 또한 total에서 `traversal_loop`를 제외한 약
`5,067.6 s`는 entry/anchor/navigation/capture/finalization 등이 혼합된 구간이다.
따라서 현재 profiler는 loop 내부 병목은 잘 보여주지만 loop 외 비용의 attribution은
충분하지 않다.

## 7. Scenario별 Regression 비교

표기:

- Coverage: before → Phase 9.5
- Recovery: profiler attempt / recovered
- V2: MOVE_CONFIRMED / STATIC_FOCUS / INDETERMINATE / exceptional
- Stop은 QA parser의 축약값이 아니라 ledger `SCENARIO_TERMINAL`을 사용한다.

| Scenario | Before status / steps / stop | Phase 9.5 status / steps / stop | Coverage | Recovery | Tx | V2 M/S/I/X |
|---|---|---|---:|---:|---:|---:|
| `global_nav_main` | passed/6/smart_nav_terminal | passed/6/smart_nav_terminal | 22.7→21.7 | 0/0 | 5 | 4/0/1/0 |
| `home_main` | passed/11/safety_limit | passed/11/safety_limit | 27.3→26.1 | 0/0 | 10 | 10/0/0/0 |
| `home_safe_plugin` | warning/17/repeat_no_progress | passed/18/safety_limit | 76.9→63.6 | 3/3 | 40 | 21/19/0/0 |
| `devices_main` | passed/11/safety_limit | passed/10/safety_limit | 36.8→23.5 | 0/0 | 10 | 9/0/1/0 |
| `life_main` | passed/25/global_nav_entry | passed/12/repeat_no_progress | 50.0→40.0 | 1/0 | 40 | 10/24/6/0 |
| `routines_main` | passed/8/global_nav_entry | passed/7/global_nav_entry | 21.1→21.1 | 0/0 | 6 | 5/0/1/0 |
| `menu_main` | passed/25/global_nav_entry | passed/4/global_nav_entry | 57.7→13.3 | 0/0 | 3 | 2/0/1/0 |
| `settings_entry_example` | warning/30/safety_limit | warning/31/repeat_no_progress | 87.5→84.8 | 3/2 | 43 | 30/11/2/0 |
| `device_smoke_sensor_plugin` | warning/16/confirmed_local_tab_exhaustion | warning/16/confirmed_local_tab_exhaustion | 73.3→71.4 | 0/0 | 15 | 8/5/2/0 |
| `device_water_leak_sensor_plugin` | warning/16/confirmed_local_tab_exhaustion | warning/16/confirmed_local_tab_exhaustion | 68.8→68.8 | 0/0 | 15 | 8/5/2/0 |
| `device_motion_sensor_plugin` | warning/18/confirmed_local_tab_exhaustion | warning/17/confirmed_local_tab_exhaustion | 72.7→75.0 | 0/0 | 15 | 8/5/2/0 |
| `device_door_lock_plugin` | warning/16/confirmed_local_tab_exhaustion | warning/15/confirmed_local_tab_exhaustion | 81.8→81.8 | 0/0 | 19 | 8/10/1/0 |
| `device_air_purifier_plugin` | warning/28/confirmed_local_tab_exhaustion | warning/27/confirmed_local_tab_exhaustion | 22.9→23.4 | 0/0 | 31 | 18/10/3/0 |
| `device_tv_plugin` | warning/34/confirmed_local_tab_exhaustion | warning/36/confirmed_local_tab_exhaustion | 50.0→50.0 | 0/0 | 36 | 20/14/2/0 |
| `device_washer_plugin` | warning/27/safety_limit | warning/23/safety_limit | 44.0→26.1 | 0/0 | 39 | 21/17/1/0 |
| `device_humidity_sensor_plugin` | warning/16/confirmed_local_tab_exhaustion | warning/15/confirmed_local_tab_exhaustion | 81.8→81.8 | 0/0 | 19 | 8/9/2/0 |
| `device_temperature_humidity_sensor_plugin` | warning/16/confirmed_local_tab_exhaustion | warning/15/confirmed_local_tab_exhaustion | 81.8→81.8 | 0/0 | 19 | 8/9/2/0 |
| `device_camera_plugin` | warning/28/safety_limit | passed/17/repeat_no_progress | 76.5→76.9 | 2/1 | 31 | 21/10/0/0 |
| `device_home_camera_plugin` | warning/19/local_tab_revisit_no_new_semantic_content | warning/19/repeat_no_progress | 63.2→61.1 | 1/0 | 18 | 17/1/0/0 |
| `device_audio_plugin` | warning/27/confirmed_local_tab_exhaustion | warning/21/confirmed_local_tab_exhaustion | 63.2→47.4 | 0/0 | 25 | 20/3/2/0 |
| `life_food_plugin` | warning/38/safety_limit | warning/48/repeat_no_progress | 82.9→91.4 | 1/0 | 58 | 37/14/7/0 |
| `life_air_care_plugin` | warning/20/repeat_no_progress | warning/25/repeat_no_progress | 78.6→58.3 | 3/2 | 46 | 34/11/1/0 |
| `life_home_care_plugin` | passed/25/plugin_boundary_global_nav | no_target_candidate/1/ANCHOR_ABORT | 44.1→NA | 0/0 | 0 | 0/0/0/0 |
| `life_energy_plugin` | warning/57/safety_limit | warning/31/repeat_no_progress | 71.4→72.2 | 1/0 | 31 | 23/8/0/0 |
| `life_pet_care_plugin` | warning/43/local_tab_revisit_no_new_semantic_content | warning/41/local_tab_revisit_no_new_semantic_content | 64.0→73.9 | 0/0 | 40 | 29/9/2/0 |
| `life_family_care_plugin` | warning/41/exhausted_strip_only_terminal_state | warning/37/exhausted_strip_only_terminal_state | 57.4→44.7 | 0/0 | 41 | 33/2/4/1 |
| `life_plant_care_plugin` | warning/27/confirmed_local_tab_exhaustion | warning/35/confirmed_local_tab_exhaustion | 68.4→43.8 | 0/0 | 34 | 26/8/0/0 |
| `life_clothing_care_plugin` | no_target_candidate/1/ANCHOR_ABORT | no_target_candidate/1/ANCHOR_ABORT | NA | 0/0 | 0 | 0/0/0/0 |
| `life_find_plugin` | warning/13/repeat_no_progress | warning/13/repeat_no_progress | 70.0→62.5 | 1/0 | 14 | 8/4/2/0 |
| `life_video_plugin` | passed/14/repeat_no_progress | passed/13/repeat_no_progress | 63.6→44.4 | 2/1 | 27 | 14/12/1/0 |
| `life_home_monitor_plugin` | warning/24/repeat_no_progress | warning/22/safety_limit | 48.3→41.7 | 0/0 | 54 | 43/7/4/0 |
| `life_music_sync_plugin` | warning/7/repeat_no_progress | warning/10/repeat_no_progress | 100.0→100.0 | 1/0 | 10 | 6/3/1/0 |

주요 regression signal:

1. Home Care가 `plugin_boundary_global_nav` 24-step traversal에서 pre-start anchor abort로 바뀌었다.
2. Menu는 steps `25→4`, Coverage `57.7→13.3`, 신규 row FAIL이 동시에 발생했다.
3. Life main은 `global_nav_entry` 24 main steps에서 `repeat_no_progress` 11 steps로 바뀌었다.
4. Washer, Audio, Air Care, Family Care, Plant Care, Video의 Coverage가 크게 하락했다.
5. Food/Air Care/Home Monitor는 scenario runtime이 10% 이상 증가했다.

이 차이가 Phase 9.4 코드만의 인과라고 확정할 수는 없다. SmartThings의 동적 UI,
screen data, card routing과 scenario work count가 달랐다. 그러나 Full Acceptance의
목표는 한 번의 성공 사례가 아니라 실제 32-scenario 안정성 검증이므로, 원인 귀속이
미확정이어도 acceptance는 실패다.

## 8. Acceptance 결과

| Gate | 결과 | Evidence |
|---|---|---|
| Coverage Regression 없음 | **FAIL** | 57.7%→52.5%; Home Care coverage 미생성; 다수 두 자릿수 하락 |
| Evidence Regression 없음 | **PASS WITH LIMITATION** | reconciliation PASS, orphan/duplicate/write failure 0; transaction은 869→793 |
| Recovery Regression 없음 | **FAIL** | ledger candidate 19/11→23/9; profiler summary는 19/9로 ledger와 count 불일치 |
| Stop Policy Regression 없음 | **FAIL** | Home Care 신규 anchor abort; Life main/Energy/Food/Home Monitor 등 terminal 변화 |
| Traversal Identity Regression 없음 | **FAIL** | INDETERMINATE 3.5%→6.7%; SNAP_BACK 1; distribution 안정성 미입증 |
| Runtime Regression 없음 | **FAIL** | total은 감소했으나 work parity 없음; Food/Home Monitor/Air Care는 >10% 증가 |
| Scenario process FAIL 없음 | **PASS** | exit code 0, `failed_scenarios=0` |
| Row/Shadow FAIL 안정 | **FAIL** | 1→2; Menu 신규 + Home Monitor 기존 |

## 9. Phase 9.4 이후 병목 Top 5

예상 절감은 현재 duration에 보수적 개선율을 적용한 범위이며 서로 중첩되므로 합산할
수 없다. Phase 9.5에서는 구현하지 않는다.

| Priority | 병목 | 근거 | 예상 절감 | 위험도 | 난이도 |
|---:|---|---|---:|---|---|
| 1 | Loop 외 entry/anchor/navigation/capture attribution 부족 | total의 54.2%가 traversal loop 밖; 단일 원인으로 분해 불가 | 계측 전 확정 불가, batch gap만 약 280 s | Medium | Medium |
| 2 | `traversal_loop` | 4,290.8 s, 45.85% | 215–429 s (5–10%) | High | High |
| 3 | `verification_poll` | 909.3 s, 9.72% | 91–182 s (10–20%) | High | High |
| 4 | `focus_in_bounds` | 640.1 s, 6.84% | 64–128 s (10–20%) | High | High |
| 5 | `row_write` | 381.9 s, 4.08% | 76–115 s (20–30%) | Medium | Medium |

`candidate_discovery`(30.8 s)와 profiler `persistence`(0.003 s)는 다음 최적화의
우선 병목이 아니다. Recovery executor는 145.4 s지만 recovery 성공 조건을 건드릴
위험이 높고 현재 recovery acceptance 자체가 실패했으므로 성능 최적화보다 정확성
재검증이 선행돼야 한다.

## 10. Known Limitations

- 단일 단말, 단일 full run이며 runtime 분산 통계가 없다.
- Before full run은 Coverage Probe ON, Phase 9.5는 OFF다. Scenario transaction
  runtime 비교에는 Probe 후처리를 제외했지만 batch wall time은 직접 비교하지 않았다.
- SmartThings 화면과 사용자 데이터가 동적이므로 inventory denominator와 work count가
  동일하지 않다.
- Profiler metric은 inclusive이며 entry/anchor/navigation/crop/periodic XLSX save를
  충분히 세분화하지 않는다.
- Profiler recovery summary는 `19/9`, ledger `RECOVERY_CANDIDATE_RESULT`는 `23/9`다.
  attempt 정의 차이를 해소하기 전에는 profiler count를 canonical recovery count로
  사용할 수 없다.
- Home Care와 Clothing Care는 profiler artifact는 생성됐지만 traversal metric이 0이다.
  이는 profiler 성공이 아니라 pre-start abort의 관측 결과다.
- `INDETERMINATE` 53건, PARTIAL transaction 2건, hierarchy/container evidence 부족은
  여전히 남아 있다.

## 11. Recommended Next Phase

권장 next phase는 최적화 구현이 아니라 **Phase 9.5A Acceptance Blocker
Reproduction**이다.

필수 선행 evidence:

1. Home Care의 previous success와 current anchor abort를 같은 card/screen snapshot으로 재현.
2. Menu step 1 `EMPTY_VISIBLE`의 pre/post focus, announcement, persisted row 확인.
3. Recovery canonical count를 ledger/profiler에서 동일 정의로 reconciliation.
4. INDETERMINATE 증가 23건의 scenario/timing/container 분류.
5. Coverage 하락 상위 scenario를 동일 UI state와 동일 denominator로 반복 실행.
6. 위 조건을 고정한 32-scenario rerun에서 Coverage, recovery, stop, identity, row FAIL parity 확인.

## 12. Final Verdict

**Phase 9.5: FAIL**

Evidence transport 자체는 production acceptance 수준으로 동작했지만, 32-scenario
traversal 안정성은 입증되지 않았다. 신규 Home Care anchor abort, Menu Shadow FAIL,
Coverage/Recovery/Identity/Stop 변화가 동시에 존재한다.

**Can Phase 10 start? NO.**

Phase 10은 위 blocker를 evidence로 분류하고 동일-work full rerun이 최소한
`PASS WITH LIMITATIONS`를 얻은 뒤 진행해야 한다.
