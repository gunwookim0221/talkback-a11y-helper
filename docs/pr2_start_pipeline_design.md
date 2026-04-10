# PR2 Start Pipeline 구조화 설계서 (동작 변경 없음)

> [!IMPORTANT]
> 이 문서는 **historical design record(당시 설계 기록)** 입니다.
> 현재 운영 기준은 `docs/current-client-architecture.md` 및 운영 문서(`system-overview.md`, `architecture.md`, `testing-pipeline.md`)를 우선 참조하세요.


본 문서는 `docs/pr1_function_split.md` 이후 단계(PR2)로, Python runner의 **scenario start pipeline**을 명시적으로 구조화하기 위한 설계를 정의한다. 

- 대상 범위: `script_test.py`, `tb_runner/*` 중 **start 진입 파이프라인 관련 로직**
- 핵심 파일: `tb_runner/collection_flow.py` (보조: `tb_runner/tab_logic.py`, `tb_runner/anchor_logic.py`)
- 제외: Android helper(`app/*`) 및 Android 빌드/동작
- 원칙: **동작 변경 금지, 실행 순서 유지, heuristic/정책 변경 금지**

---

## 1. 현재 구조 문제 요약

### 1-1. `open_scenario` 주변 책임 분산
현재 start 구간 책임은 한 함수/한 단계에 모여 있지 않고, 아래처럼 흩어져 있다.

- `open_scenario(...)` 내부
  - stabilization mode 계산
  - tab select + context verify 결과 소비
  - pre-navigation 실행
  - anchor stabilize + low-confidence fallback 판단
  - `tab_cfg`에 start 메타 mutation
- `collect_tab_rows(...)` 내부
  - `open_scenario` 성공/실패 분기
  - post_open_focus trace
  - global_nav start gate
  - anchor row(step 0) 수집/annotate/save
  - main loop 진입 상태 초기화

결과적으로 “scenario start”라는 하나의 논리 단위를 파악하려면 `open_scenario`와 `collect_tab_rows`를 동시에 추적해야 한다.

### 1-2. pre_navigation / context verify / anchor stabilize / fallback 결과의 암묵 전달
start 결과가 구조체로 정리되지 않아, 결과가 암묵적으로 전달된다.

- `open_scenario` 반환값은 `bool` 하나라서 세부 실패 이유/중간 상태가 소실된다.
- 일부 상태는 `tab_cfg` 내부 임시 키(`_scenario_*`)에 기록되어 후속(anchor row 기록)에서 읽힌다.
- context verify 결과는 `stabilize_tab_selection` 내부/`stabilize_anchor` 내부에서 각각 소비되고, start orchestration 레벨에서 단일 상태로 정리되지 않는다.

### 1-3. 회귀가 쉬운 이유
- start 실패 row 생성/저장 타이밍이 `collect_tab_rows`에 분산되어 있어, 분해 시 순서가 미세하게 어긋나기 쉽다.
- global_nav start gate가 `open_scenario` 이후 별도 지점에 있어, start 성공 정의가 함수별로 불일치하기 쉽다.
- post_open_focus trace와 anchor row 수집 사이 타이밍이 고정되어 있는데, 구조화 없이 이동하면 로그/행동 불일치가 발생할 수 있다.

### 1-4. PR1 이후 PR2가 필요한 이유
PR1은 `collect_tab_rows`의 메인 루프/overlay/persist 분리를 중심으로 가독성을 개선했다. 하지만 start 파이프라인은 여전히 `open_scenario(bool)` + `collect_tab_rows` 전반부에 분산되어 있어, start 관련 리뷰/회귀 방어가 어렵다. 따라서 PR2는 **시작 단계만 별도 파이프라인으로 계약화**하는 것이 필요하다.

---

## 2. 현재 start pipeline 실제 흐름 정리

아래는 현재 코드 기준 start 흐름(메인 루프 진입 직전까지)이다.

1. `collect_tab_rows` 진입 후 wait/checkpoint 파라미터 결정
2. `open_scenario(client, dev, tab_cfg)` 호출
3. `open_scenario` 내부:
   - scenario stabilization mode 결정 (`_resolve_screen_context_mode`, `_resolve_stabilization_mode`)
   - tab select + context verify (`stabilize_tab_selection`)
   - 필요 시 plugin root state verify (`_verify_plugin_entry_root_state`)
   - `pre_navigation` 실행 (`_run_pre_navigation_steps`)
   - anchor stabilize (`stabilize_anchor`)
   - anchor 실패 시 low-confidence fallback 허용 여부 판단 (`_is_new_screen_low_confidence_allowed`)
4. open 실패면 `TAB_OPEN_FAILED` row 생성/append/save 후 즉시 반환
5. open 성공이면 `post_open_focus` trace 수집/로그
6. (global_nav + bottom_tab) start gate 검증 (`_ensure_global_nav_start_focus`)
   - gate 실패 시 `TAB_OPEN_FAILED` row 생성/append/save 후 반환
7. anchor row(step 0) 수집 (`collect_focus_step(move=False)`)
8. anchor row 메타 주입
   - `scenario_start_mode/source`, `anchor_stable`, `review_note` (`tab_cfg` 기반)
9. anchor row 품질 annotation + crop + append/save
10. main loop 상태 초기화 후 `_main_loop_phase` 진입

### 텍스트 다이어그램

```text
scenario start
→ stabilization mode resolve
→ tab select / context verify
→ (optional) plugin root verify
→ pre_navigation
→ anchor stabilize
→ open 실패 처리 (TAB_OPEN_FAILED row/save)
→ post_open_focus trace
→ global_nav start gate
→ anchor row(step 0) collect/annotate/save
→ main loop enter
```

---

## 3. PR2 목표 구조 제안

PR2는 start 구간을 “동작은 동일, 경계만 명시화”하는 구조화 PR이다.

### 제안 함수 경계(안)

- `_run_start_pipeline(...) -> StartPipelineResult`
  - start 전체 orchestration 담당
  - 기존 `open_scenario` + `collect_tab_rows` 전반부의 start 관련 단계를 묶어서 명시화
- `_resolve_start_context(...) -> StartContext`
  - scenario_id, screen_context_mode, stabilization_mode, scenario_type, strict/transition 플래그 계산
- `_run_open_phase(...) -> OpenPhaseResult`
  - 기존 `open_scenario` 실질 단계(탭 안정화~pre_navigation~anchor stabilize) 실행
- `_trace_post_open_focus(...) -> PostOpenFocusTrace`
  - 기존 post_open_focus trace 수집/로그 담당
- `_run_global_nav_start_gate_if_needed(...) -> GateResult`
  - global_nav start gate 분기 담당
- `_collect_start_anchor_row(...) -> dict`
  - step 0 anchor row 수집/주석/품질 annotation/crop
- `_finalize_start_result(...) -> StartPipelineResult`
  - main loop 진입 여부, 실패 reason, 저장 필요 상태를 결과 객체로 정리

> 함수명은 구현 시 조정 가능하나, 책임 경계(계산/실행/게이트/anchor row/finalize)는 유지한다.

---

## 4. Start Result 구조체 설계

PR2에서 도입할 시작 단계 결과 객체(예: `StartPipelineResult`) 제안.

### 필드(현재 코드 기반)

- `success: bool`
  - start pipeline 전체 성공 여부
  - 채움: `_finalize_start_result`
  - 소비: `collect_tab_rows` (즉시 반환 vs main loop 진입)
- `failure_reason: str`
  - 예: `tab_or_anchor_failed`, `global_nav_start_gate_failed`
  - 채움: open 실패/게이트 실패 처리 지점
  - 소비: 실패 row 생성/로그
- `stabilization_mode: str`
  - `tab_context` / `anchor_only` / `anchor_then_context`
  - 채움: `_resolve_start_context`
  - 소비: trace/log, 리뷰 분석
- `context_ok: bool`
  - tab stabilize 내부 context 결과의 요약 상태
  - 채움: open phase
  - 소비: trace/log
- `anchor_matched: bool`
  - `stabilize_anchor` 결과 매칭 여부
  - 채움: open phase
  - 소비: trace/log
- `anchor_stable: bool`
  - start anchor 안정화 여부(저신뢰 fallback 포함 시 false 가능)
  - 채움: open phase + finalize
  - 소비: step0 row(`anchor_stable`)
- `focus_align_attempted: bool`
- `focus_align_ok: bool`
- `focus_align_reason: str`
  - 채움: tab stabilize 결과 소비 지점
  - 소비: trace/log 및 실패 원인 분석
- `pre_navigation_attempted: bool`
- `pre_navigation_success: bool`
  - 채움: pre_navigation 실행 지점
  - 소비: 실패 판단/분석
- `open_completed: bool`
  - `open_scenario` 영역 완료 여부
  - 채움: open phase 완료 시
  - 소비: post_open_focus 진입 조건
- `post_open_focus_collected: bool`
  - 채움: `_trace_post_open_focus`
  - 소비: 디버깅/로그 일관성 검증
- `should_enter_main_loop: bool`
  - 채움: `_finalize_start_result`
  - 소비: `_main_loop_phase` 호출 여부
- `start_row: dict | None`
  - 성공 시 anchor row(step 0)
  - 채움: `_collect_start_anchor_row`
  - 소비: `rows/all_rows` append, state 초기화
- `needs_open_failed_row: bool`
  - 실패 시 `TAB_OPEN_FAILED` row 생성 필요 여부
  - 채움: 실패 분기
  - 소비: 실패 row 생성/저장 지점

핵심: `tab_cfg` 임시 mutation을 바로 제거하지 않더라도, **start 의사결정 상태를 결과 객체에 먼저 승격**해 암묵 전달을 줄인다.

---

## 5. 함수별 책임/입출력 계약

### 5-1. `_resolve_start_context(...)`
- 역할: start 관련 모드/시나리오 플래그 계산
- 입력: `tab_cfg`
- 출력: `StartContext`(scenario_id, screen_context_mode, stabilization_mode, scenario_type, strict/transition 여부)
- 내부 상태 변경: 없음(pure)
- side effect: 없음
- 호출 범위: start pipeline 내부 전용
- 금지 책임: adb 호출, 저장, row 생성

### 5-2. `_run_open_phase(...)`
- 역할: tab stabilize → pre_navigation → anchor stabilize 실행
- 입력: `client, dev, tab_cfg, StartContext`
- 출력: `OpenPhaseResult`(성공/실패, focus_align/context/anchor/pre_nav 요약)
- 내부 상태 변경: `tab_cfg`의 기존 `_scenario_*` mutation(현행 유지)
- side effect: select/touch/focus 수집/log
- 호출 범위: start pipeline 내부 전용
- 금지 책임: 실패 row 생성/저장, post_open_focus trace, global_nav gate

### 5-3. `_trace_post_open_focus(...)`
- 역할: open 직후 focus snapshot trace 수집
- 입력: `client, dev, scenario_id, wait_seconds`
- 출력: trace dict(view_id/label/speech/bounds/source/top_level)
- 내부 상태 변경: 없음
- side effect: get_focus + log
- 호출 범위: open 성공 이후
- 금지 책임: gate 판정, anchor row 생성

### 5-4. `_run_global_nav_start_gate_if_needed(...)`
- 역할: global_nav bottom_tab 조건에서만 gate 수행
- 입력: `client, dev, tab_cfg, scenario_id, post_open_focus`
- 출력: `GateResult(ok, reason)`
- 내부 상태 변경: 없음
- side effect: 필요 시 추가 focus 이동/로그
- 호출 범위: post_open_focus 직후
- 금지 책임: 실패 row 저장, anchor 수집

### 5-5. `_collect_start_anchor_row(...)`
- 역할: step 0 수집 + 메타 주입 + 품질 annotation + crop
- 입력: `client, dev, tab_cfg, output_base_dir, wait/announcement 설정, quality history`
- 출력: anchor row(dict), annotation 결과(fingerprint/repeat)
- 내부 상태 변경: history deque 갱신
- side effect: collect_focus_step, crop 캡처, log
- 호출 범위: start 성공 경로
- 금지 책임: main loop 실행, stop 평가

### 5-6. `_finalize_start_result(...)`
- 역할: start pipeline 종료 상태를 단일 객체로 결정
- 입력: open/gate/anchor 결과
- 출력: `StartPipelineResult`
- 내부 상태 변경: 없음
- side effect: 없음(최소화)
- 호출 범위: start pipeline 마지막
- 금지 책임: adb 동작, 저장 호출

### 5-7. `collect_tab_rows(...)`의 orchestration 경계
- 유지 역할:
  - start pipeline 호출
  - 실패 row append/save
  - 성공 시 start_row append/save + state 초기화 + `_main_loop_phase` 호출
- 제거/축소 대상:
  - start 세부 단계의 인라인 구현
- 금지 책임:
  - start 내부 정책/heuristic 자체 변경

---

## 6. 실행 순서 계약 (가장 중요)

**PR2에서는 start pipeline을 구조화하되, 아래 실행 순서는 절대 변경하면 안 된다.**

1. `open_scenario` 성격의 open phase 먼저 실행
2. open 실패 시 즉시 실패 처리(row 생성/저장/반환)
3. open 성공 후 `post_open_focus` trace 실행
4. global_nav start gate 실행(해당 시나리오 조건에서만)
5. gate 실패 시 실패 처리(row 생성/저장/반환)
6. anchor row(step 0) 수집/annotate/save
7. main loop 진입 조건 판단 후 `_main_loop_phase` 호출

### 고정 포인트 분석
- **open 실패 처리 시점**: post_open_focus 이전이어야 함
- **post_open_focus trace 시점**: open 성공 직후, gate/anchor row 이전
- **global_nav start gate 시점**: post_open_focus 이후, anchor row 이전
- **anchor row 저장 시점**: main loop 진입 이전, step 0 직후
- **main loop 진입 판단 시점**: anchor row 준비 완료 후

---

## 7. Side Effect / 상태 전달 관리

### 7-1. `tab_cfg` mutation
- 현재: `open_scenario`가 `_scenario_start_mode/_scenario_anchor_stable/_scenario_start_note/_scenario_start_source` 기록
- PR2: 우선 현행 유지(동작 동일), 동시에 StartResult에도 동일 의미 필드를 기록
- 이유: row 생성 로직의 기존 의존성을 깨지 않으면서 명시적 전달로 전환

### 7-2. runtime state
- 현재: `collect_tab_rows`에서 `state` dict 초기화 후 main loop 전달
- PR2: start pipeline 결과(`start_row`, 초기 fingerprint 등)를 받아 기존 state 초기화 로직 위치는 유지

### 7-3. anchor 관련 상태
- 현재: anchor 안정화 결과는 로그/`tab_cfg`/step0 row로 흩어짐
- PR2: `anchor_matched`, `anchor_stable`, `start_candidate_source`를 StartResult에 집약

### 7-4. context verify 결과
- 현재: tab stabilize 내부 context와 anchor stabilize 내부 context가 분리
- PR2: start 레벨에서는 `context_ok`(요약)만 승격하고, 상세 payload는 기존 로그/하위 결과에 유지

### 7-5. pre_navigation 결과
- 현재: bool 반환 후 즉시 실패/진행
- PR2: `pre_navigation_attempted/success`를 StartResult로 승격

### 7-6. open 실패 row 생성/저장
- 현재: `collect_tab_rows`에서 생성/append/save
- PR2: **위치 유지(절대 이동 금지)**. 단, reason 결정은 StartResult를 통해 명시화

### 7-7. anchor row annotate/save
- 현재: open 성공 후 `collect_tab_rows`에서 처리
- PR2: start pipeline 내부 helper로 분리 가능하나, **실행 타이밍은 동일하게 유지**

---

## 8. PR2 범위 정의

### IN SCOPE
- start pipeline 구조화
- Start Result(결과 객체) 도입
- start 상태 전달 명시화
- `open_scenario` 주변 책임 경계 정리
- `collect_tab_rows`와 start pipeline 연결 지점 정리

### OUT OF SCOPE
- pre_navigation heuristic 변경
- anchor heuristic 변경
- stop policy 변경
- overlay 정책 변경
- save 정책 변경
- config 해석 변경
- retry / timing 변경
- 성공률 개선 목적의 로직 수정

---

## 9. 예상 Diff 영향

### 수정 후보 파일
- 1순위: `tb_runner/collection_flow.py`
- 필요 시 최소 보조: 타입 정의(동일 파일 내부 또는 `tb_runner` 내 보조 모듈)
- 문서 동기화: `docs/*` (필요 시)

### 가장 크게 바뀔 함수
- `collect_tab_rows` start 전반부
- `open_scenario`(혹은 open phase wrapper) 호출/결과 소비 구간

### 리뷰 집중 지점
- open 실패 row/save 분기
- post_open_focus 로그 위치
- global_nav start gate 위치
- anchor row(step 0) 생성/저장 타이밍
- main loop 진입 조건

### 주요 회귀 위험(반드시 체크)
- `home_main`에서 tab select/verify 실패 회귀
- "Navigate up, Navigate up" 형태의 잘못된 start context 재발
- open 성공 후 main loop 미진입 회귀
- open 실패 row/save 타이밍 변경으로 인한 리포트 불일치

---

## 10. 동작 동일 체크리스트

PR2 완료 후 로그/결과 비교 체크리스트:

- [ ] `home_main` 정상 진입
- [ ] anchor stabilize 성공 여부 동일
- [ ] step 수 동일
- [ ] overlay 횟수 동일
- [ ] realign 성공 여부 동일
- [ ] stop reason 동일
- [ ] save/checkpoint/final save 흐름 동일
- [ ] open 실패 시 `TAB_OPEN_FAILED` row 생성/저장 시점 동일
- [ ] post_open_focus trace 로그 위치 동일
- [ ] global_nav start gate 판정/실패 처리 시점 동일

---

## 부록: PR2 구현 시 가드레일

- 함수 분해는 허용되지만, start 단계의 adb 호출 순서/대기/retry 의미는 변경하지 않는다.
- StartResult는 “상태 전달 명시화” 목적이며, 성공/실패 판정 규칙을 바꾸는 수단이 아니다.
- PR2 리뷰 기준은 “더 읽기 쉬운가”보다 먼저 “로그/row/save 타이밍이 기존과 동일한가”다.
