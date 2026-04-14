# Python Runner 실행 흐름 (현재 코드 기준)

이 문서는 **현재 운영 기준 문서**입니다.

본 문서는 `script_test.py`와 `tb_runner/*`의 **현재 구현**을 기준으로, scenario 단위 수집이 실제로 어떤 순서로 실행되는지 정리한다.

범위 제한:
- 포함: Python runner (`script_test.py`, `tb_runner/collection_flow.py`, `tb_runner/overlay_logic.py`, `tb_runner/anchor_logic.py`, `tb_runner/diagnostics.py`)
- 제외: Android helper(`app/`) 로직

---

## 1) 시나리오 시작 (scenario start)

`script_test.py`의 `main()`에서 runtime 설정을 로드한 뒤 시나리오 반복을 시작한다.

- `run_perf.start_scenario(...)`로 시나리오 성능 컨텍스트를 시작한다.
- `collect_tab_rows(...)`를 시나리오별로 1회 호출한다.
- 첫 시나리오 이후에는 `recover_to_start_state(...)`를 시도해 다음 시나리오 시작 상태를 맞춘다.

### Side effect
- 로그 파일 초기화/기록 (`configure_log_files`, `log`).
- 런 전체 row 누적 리스트(`all_rows`)에 시나리오별 row를 append.

---

## 2) start pipeline 단계

`collect_tab_rows` 시작 직후 `_run_start_pipeline(...)`를 호출한다.

start pipeline 내부에서 `open_scenario(...)`를 먼저 실행한 뒤, post-open trace / global nav gate / anchor row(step 0) 수집까지 동일 순서로 처리한다.

핵심 순서:
1. screen/stabilization 모드 계산 (`_resolve_screen_context_mode`, `_resolve_stabilization_mode`)
2. tab 선택 안정화 (`stabilize_tab_selection`)
3. 필요 시 plugin root state 검증 (`_verify_plugin_entry_root_state`)
4. pre-navigation 실행 (`_run_pre_navigation_steps`)
5. anchor 안정화 (`stabilize_anchor`)
6. 실패 시 low-confidence fallback 허용 조건 평가 (`_is_new_screen_low_confidence_allowed`)
7. post-open focus trace
   - Life plugin의 경우 entry contract 판정 로그(`[SCENARIO][entry_contract]`)를 남기며, `success_verified | verify_failed | false_success_guard | no_match | text_only_no_promotion | wrong_open` taxonomy로 최종 진입 판정을 분리한다.
8. global_nav start gate(해당 시)
9. anchor row(step 0) 수집/annotation/crop

### 상태 변경 지점 (mutation)
- `tab_cfg`에 scenario 시작 상태 메타를 직접 기록:
  - `_scenario_start_mode`
  - `_scenario_anchor_stable`
  - `_scenario_start_note`
  - `_scenario_start_source`

### 주요 의사결정
- tab stabilize 실패를 즉시 실패로 볼지, transition/plugin 시나리오에서 허용할지 결정.
- anchor stabilize 실패를 즉시 abort할지, low-confidence fallback start로 진행할지 결정.

### Side effect
- 다수의 trace/log 출력.
- ADB 기반 focus/select/click/collect 호출.

---

## 3) pre_navigation 단계

`open_scenario` 내부에서 `_run_pre_navigation_steps(...)`가 실행된다.

- `tab_cfg["pre_navigation"]` 리스트를 순회하며 `select + click_focused` 또는 direct 액션 수행.
- Life plugin에서는 `xml_scroll_search_tap` 액션으로 XML dump 기반 후보 탐색/스크롤/ADB tap 진입을 먼저 시도할 수 있으며, 실패 시 기존 `scrollTouch` fallback 경로를 유지한다.
- step별 retry/reason을 추적하고 실패 시 즉시 `False` 반환.
- 각 pre-navigation step 후 `collect_focus_step(...)`를 음수 step index로 호출해 상태를 확인.

### 주요 의사결정
- select 실패 시 `last_target_action_result`를 확인해 accessibilityFocused 기반으로 계속 진행할지 판단.
- step retry 한계 도달 시 시나리오 오픈 실패 처리.

### Side effect
- pre-navigation 자체가 실제 화면 전환/포커스 이동을 유발.
- 상세 로그를 남김.

---

## 4) anchor stabilize 단계

`open_scenario` 마지막에서 `stabilize_anchor(...)` 수행.

- explicit anchor 매칭 우선.
- 필요 시 top-content fallback anchor 후보 사용.
- 선택 후 `stabilize_anchor_focus`로 verify read를 수행.

`open_scenario` 성공 시 `collect_tab_rows`로 복귀하고, step 0(anchor_row)를 수집한다.

### 상태/품질 메타 반영
- step 0 row에 `scenario_start_mode/source`, `anchor_stable`, `review_note` 기록.
- `_annotate_row_quality(...)`로 fingerprint/중복/semantic duplicate/noise 필드 계산.

### Side effect
- step 0 즉시 `save_excel_with_perf(...)` 호출(초기 checkpoint 성격).
- crop 캡처(`maybe_capture_focus_crop`)로 이미지 파일 생성 가능.

---

## 5) main step loop

`for step_idx in range(1, tab_cfg["max_steps"] + 1)` 루프에서 본 수집을 수행한다.

참고(PR6):
- `collect_tab_rows`는 main/persist 단계의 공유 상태를 `MainLoopState`, `CollectionPhaseContext`로 묶어 전달한다.
- 이 변경은 **상태 전달 정리 목적**이며, 실행 순서(`open -> main -> overlay -> realign -> stop -> persist`)와 정책 의미는 유지한다.

## 5-1) step 수집 (focus / announcement / crop / fallback)

각 step에서:
- `collect_focus_step(move=True, direction="next", ...)` 호출.
- row 공통 필드 주입 (`context_type=main`, elapsed, scenario_type 등).
- `maybe_capture_focus_crop` 실행.
- `_annotate_row_quality`로 fingerprint/duplicate/noise 계산.
- `detect_step_mismatch`로 mismatch/low_confidence 로깅.

여기서 fallback 관련 관찰 지표(`get_focus_fallback_used`, `get_focus_fallback_found`, `step_dump_tree_used`)도 row에 포함되어 후속 진단/리포팅에 사용된다.

## 5-2) stop 정책 평가

각 main step마다 `should_stop(...)`를 호출한다.

평가 입력:
- 현재 row + 이전 row
- `prev_fingerprint`, `fail_count`, `same_count`
- scenario_type/stop_policy/scenario_cfg

평가 결과:
- `stop`, `reason`, `stop_details` (terminal/repeat/global_nav 등)

추가 분기:
- `repeat_semantic_stall`이면 `should_attempt_stall_escape` → `attempt_stall_escape` 수행 가능.
- global_nav 시나리오면 `is_global_nav_row` 재평가 후 skip/continue 처리 가능.

## 5-3) overlay 후보 판단

stop 평가 직후(동일 loop 내) overlay 후보를 판정한다.

- `is_overlay_candidate(row, tab_cfg)` 호출.
- global_nav 전용 시나리오는 기본적으로 overlay 차단.
- 이미 확장한 entry는 fingerprint(`make_overlay_entry_fingerprint`)로 중복 방지.

## 5-4) overlay 실행

overlay 후보면 entry click 시도 후 `classify_post_click_result`로 분기:
- `overlay`: `expand_overlay(...)` 실행
- `navigation`: overlay 루틴 skip
- `unchanged`: overlay 루틴 skip

overlay 확장 후:
- `realign_focus_after_overlay(...)` 실행
- realign 성공 시 `stabilize_anchor(phase="overlay_realign")` 재호출
  - 이때 overlay 복귀 성공 로그는 `overlay_realign_verified`, plugin 진입 성공 로그는 `plugin_open_verified`로 분리한다.

### Side effect (overlay 구간)
- overlay row들이 `rows/all_rows`에 추가됨.
- overlay 내부에서도 반복적으로 `save_excel_with_perf(...)` 호출:
  - 반복/종료 시점
  - `checkpoint_every` step마다
  - overlay 종료 후 recovery 상태 반영 시점

### 주요 의사결정 (overlay)
- allow/block policy 매칭
- post-click 결과 분류(overlay/navigation/unchanged)
- overlay 내부 stop 정책(`should_stop`)으로 overlay 종료 판단
- realign 성공/실패에 따른 후속 anchor stabilize 여부

## 5-5) loop 종료

- `stop=True`이면 row를 `END`로 마킹하고 loop break.
- stop 없이 max_steps 소진 시 마지막 row를 safety_limit 종료로 요약.

---

## 6) save / checkpoint / final export

저장 흐름은 단일 지점이 아니라 여러 레벨에서 발생한다.

### 시나리오 내부 저장 (`collect_tab_rows`)
- open 실패 시 즉시 저장
- anchor row(step 0) 직후 저장
- main loop 중:
  - stop 발생 시 저장
  - `step_idx % checkpoint_every == 0`일 때 checkpoint 저장

### overlay 내부 저장 (`expand_overlay`)
- overlay break/stop/checkpoint/recovery 시 저장

### 런 최종 저장 (`script_test.py`)
- 예외 발생 시: `with_images=False` 저장 후 재예외.
- `finally`에서 항상 `with_images=True` 최종 저장.
- 최종 run perf summary 로그 출력 후 로그 파일 종료.
- 스크립트 시작 시 Python 프로세스의 `TMP/TEMP`를 `output/.tmp`로 오버라이드하여 xlsxwriter 임시 파일 경로를 프로젝트 내부로 고정한다.

### 저장 안정화 (`tb_runner/perf_stats.py`)
- 공통 저장 진입점 `save_excel_with_perf(...)`에서 `FileCreateError`/`PermissionError`만 최대 5회 재시도한다.
- 재시도 간 1.0초 대기하며 `[SAVE][retry]` 로그로 시도 횟수, 오류 타입, output 경로를 남긴다.
- 마지막 시도까지 실패하면 예외를 그대로 상위로 전달한다(예외 삼키기 없음).

### Side effect
- 엑셀 파일 반복 overwrite/갱신
- 이미지 crop 파일 생성
- 성능 집계(`ScenarioPerfStats`, `RunPerfStats`) 누적 및 finalize

---

## 실행 순서 다이어그램 (텍스트)

```text
scenario start
→ collect_tab_rows
  → open_scenario
    → tab stabilize
    → pre_navigation
    → anchor stabilize
  → collect anchor row(step 0)
  → main loop (step 1..N)
    → collect step (focus/announcement/crop/fallback 관찰)
    → stop policy evaluate
    → overlay candidate check
    → overlay execute (optional)
      → expand_overlay
      → realign_focus_after_overlay
      → anchor stabilize (overlay_realign, optional)
    → stop check / break
  → scenario finalize (summary)
→ (next scenario이면) recover_to_start_state
→ final save/export (main finally)
```

---

## 요약 포인트

- `collect_tab_rows`는 scenario open + anchor 수집 + main loop + overlay + 저장까지 모두 포함한 오케스트레이터다.
- 실행 순서의 핵심 불변은 **open_scenario → anchor row → main step loop**이며, overlay는 main loop 내부의 조건부 분기다.
- `tab_cfg` mutation은 `open_scenario`에서 발생하고, 저장 side effect는 main/overlay 양쪽에서 반복적으로 발생한다.
