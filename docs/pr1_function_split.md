# PR1 함수 분해 설계서 (동작 변경 없음)

> [!IMPORTANT]
> 이 문서는 **historical design record(당시 설계 기록)** 입니다.
> 현재 운영 기준은 `docs/current-client-architecture.md` 및 운영 문서(`system-overview.md`, `architecture.md`, `testing-pipeline.md`)를 우선 참조하세요.


본 문서는 `tb_runner/collection_flow.py`의 `collect_tab_rows`를 PR1에서 분해할 때의 설계 계약을 정의한다.

핵심 원칙:
- **동작 변경 금지**
- **실행 순서 변경 금지**
- **stop/overlay/save 정책 변경 금지**
- 목적은 가독성/리뷰성 향상을 위한 함수 분해

---

## 1. 현재 문제 요약

`collect_tab_rows`가 과도하게 큰 이유:

1. 시나리오 오픈 실패 처리부터 메인 루프 종료 요약까지 전 구간이 한 함수에 집중되어 있다.
2. 서로 다른 책임이 섞여 있다.
   - 시나리오 진입(open/pre-navigation/anchor)
   - step 데이터 수집 및 품질 annotation
   - stop evaluator 호출/분기
   - overlay 후보 판정/실행/realign
   - 저장(checkpoint/종료 시 save)
   - perf 집계 및 로그
3. 상태 변수(`prev_fingerprint`, `fail_count`, `same_count`, `post_realign_pending_steps`, `expanded_overlay_entries`)의 생명주기가 길어 추적이 어렵다.

결과적으로, 리뷰 시 “어디서 상태가 바뀌는지”와 “어디서 I/O가 발생하는지”를 빠르게 확인하기 어렵다.

---

## 2. 함수 분해 설계

아래는 PR1에서 목표로 하는 분해 단위다. (함수명은 제안이며, 실제 구현 시 동일 의미로 조정 가능)

## 2-1) `_scenario_open_phase(...)`

### 역할
- `open_scenario` 호출
- 실패 시 `TAB_OPEN_FAILED` row 생성/append/save
- 성공 시 post-open focus trace + global nav start gate 처리 + anchor row(step 0) 수집/annotate/save
- main loop 시작에 필요한 초기 상태 컨텍스트 구성

### 입력값
- `client, dev, tab_cfg, all_rows, output_path, output_base_dir`
- `scenario_perf`, `checkpoint_every`, main wait/announcement 설정

### 출력값
- 성공: `ok=True` + `rows`(anchor 포함) + main loop 초기 상태 컨텍스트
- 실패: `ok=False` + 실패 row 포함 `rows` 반환(호출자는 즉시 반환)

### 내부 상태 변경 (mutation)
- `rows`, `all_rows` append
- `tab_cfg`는 `open_scenario` 내부 mutation 결과를 그대로 소비

### Side effect
- `save_excel_with_perf` 호출
- `maybe_capture_focus_crop`로 이미지 생성
- 다수 로그 출력

### 호출 가능 여부
- overlay 로직: **호출하지 않음**
- stop evaluator: **호출하지 않음**
- save/export: **호출함 (초기 실패/anchor checkpoint)**

---

## 2-2) `_pre_navigation_phase(...)`

> 참고: 실제 pre-navigation 실행은 현재 `open_scenario` 내부 `_run_pre_navigation_steps`가 담당한다.
> PR1에서는 중복 실행을 만들지 않고, “시나리오 오픈 단계 내부 서브 페이즈”로만 추출/정리한다.

### 역할
- pre-navigation 단계 책임을 코드 구조상 분리해 가독성 확보
- pre-navigation 실패 시 즉시 시나리오 실패로 연결

### 입력값
- `client, dev, tab_cfg`
- transition-fast 관련 옵션

### 출력값
- `bool` 성공/실패 + (선택) 실패 reason

### 내부 상태 변경 (mutation)
- 직접 row mutation은 없음
- 화면 상태(포커스/화면 전이)는 adb 액션으로 변경됨

### Side effect
- `select`, `click_focused`, `collect_focus_step` 호출
- 로그 출력

### 호출 가능 여부
- overlay 로직: **호출하지 않음**
- stop evaluator: **호출하지 않음**
- save/export: **직접 호출하지 않음**

---

## 2-3) `_main_loop_phase(...)`

### 역할
- step 1..max_steps 반복 수행
- step 수집/품질 annotation/mismatch 진단
- stop evaluator 호출
- global_nav 전용 skip 처리
- checkpoint 저장
- overlay phase 호출 orchestration

### 입력값
- `client, dev, tab_cfg, rows, all_rows, output_path, output_base_dir`
- 상태 컨텍스트:
  - `prev_fingerprint`, `last_fingerprint`, `fingerprint_repeat_count`
  - `previous_step_row`, `fail_count`, `same_count`
  - `expanded_overlay_entries`, `post_realign_pending_steps`
  - `main_step_index_by_fingerprint`
  - recent history deque
- wait/announcement/checkpoint/perf 옵션

### 출력값
- 갱신된 `rows`
- stop 요약(`stop_triggered`, `stop_reason`, `stop_step`)
- 다음 phase/summary에 필요한 갱신 상태 컨텍스트

### 내부 상태 변경 (mutation)
- `rows/all_rows` append
- main loop 상태 변수 다수 mutation
- 일부 row 필드(`status`, `stop_reason`, `stop_triggered` 등) mutation

### Side effect
- `collect_focus_step`, crop 캡처, 로그
- `save_excel_with_perf` (stop/checkpoint)

### 호출 가능 여부
- overlay 로직: **호출함** (`_overlay_phase`)
- stop evaluator: **호출함** (`should_stop`)
- save/export: **호출함** (checkpoint/stop 저장)

---

## 2-4) `_overlay_phase(...)`

### 역할
- overlay 후보 판정
- entry click + post-click classification
- overlay 확장(`expand_overlay`) 및 realign(`realign_focus_after_overlay`)
- 필요 시 `stabilize_anchor(overlay_realign)` 호출

### 입력값
- `client, dev, tab_cfg, current_row`
- `rows, all_rows, output_path, output_base_dir`
- `expanded_overlay_entries`, `main_step_index_by_fingerprint`
- `scenario_perf`

### 출력값
- overlay 처리 결과 구조체(예: handled 여부, `post_realign_pending_steps` 변경량)
- `expanded_overlay_entries` 갱신 결과

### 내부 상태 변경 (mutation)
- `rows/all_rows`에 overlay row append (via `expand_overlay`)
- `expanded_overlay_entries` set mutation
- `post_realign_pending_steps` 증가 가능

### Side effect
- ADB touch/click/focus 이동
- overlay 내부 저장(checkpoint/종료)
- overlay recovery/realign 로그 다수

### 호출 가능 여부
- overlay 로직: **핵심 담당**
- stop evaluator: **간접 호출됨** (`expand_overlay` 내부 `should_stop`)
- save/export: **호출됨** (`expand_overlay` 내부)

---

## 2-5) `_persist_phase(...)`

### 역할
- 시나리오 종료 시점 summary/perf finalize 정리
- “시나리오 내부 마지막 처리”와 “런 레벨 최종 저장(script_test finally)”의 경계를 명확히 문서화

### 입력값
- `rows`, stop 요약, `scenario_perf`

### 출력값
- 없음(혹은 최종 summary dict)

### 내부 상태 변경 (mutation)
- `scenario_perf.finalize()`
- 마지막 row의 safety_limit 메타 보정(미종료 케이스)

### Side effect
- summary 로그 출력
- (주의) 런 최종 export는 `script_test.py` finally에서 수행

### 호출 가능 여부
- overlay 로직: **호출하지 않음**
- stop evaluator: **호출하지 않음**
- save/export: **시나리오 요약 수준만**, 최종 export는 상위(main) 책임

---

## 3. 실행 순서 계약 (가장 중요)

PR1 분해 후에도 호출 순서는 아래와 같아야 한다.

```text
scenario_open
→ pre_navigation
→ anchor_stabilize
→ main_loop
  → collect_step
  → overlay_check
  → overlay_execute
  → stop_check
→ persist
```

**명시적 계약:**
> 이 순서는 PR1에서 절대 변경하면 안 됨.

보조 설명:
- 코드 상 `stop_check` 계산은 현재 collect 직후 수행되고, overlay는 그 다음 분기에서 실행된다.
- 위 순서 표기는 리뷰 가독성을 위한 논리 계약이며, 실제 구현의 기존 평가/저장 타이밍은 그대로 유지한다.
- 즉, “순서 표기의 의미”를 근거로 기존 stop/overlay 호출 타이밍을 바꾸면 안 된다.

---

## 4. Side Effect 관리

## 4-1) `tab_cfg` 변경

현재 `open_scenario`에서만 시나리오 시작 메타를 `tab_cfg`에 기록한다.

- 변경 가능 함수:
  - `_scenario_open_phase`(실제 mutation은 `open_scenario` 내부)
- pure 유지 권장 함수:
  - `_overlay_phase`는 `tab_cfg`를 read-only로 사용
  - `_main_loop_phase`는 `tab_cfg` 정책값 읽기만 수행

## 4-2) save/checkpoint 호출 위치

유지해야 할 저장 위치:
- open 실패 즉시 저장
- anchor row 직후 저장
- main loop stop 발생 시 저장
- main loop checkpoint 주기 저장
- overlay 내부 break/stop/checkpoint/recovery 저장
- run 최종 저장은 `script_test.py` finally 유지

분해 후에도 저장 호출 위치/횟수 조건은 변경 금지.

## 4-3) fallback dump 사용 위치

fallback dump 관련 신호는 row 필드(`get_focus_fallback_used`, `get_focus_fallback_found`, `step_dump_tree_*`)로 수집/로그된다.

- 변경 가능 함수:
  - 없음 (PR1에서 로직 변경 금지)
- pure 유지 권장:
  - side effect 없는 후처리 함수(예: quality annotation helper)는 pure 성격 유지

---

## 5. PR1 범위 정의

## IN SCOPE
- 함수 분해
- 코드 이동
- 구조 정리
- 이름 개선

## OUT OF SCOPE
- 로직 변경
- heuristic 수정
- stop 정책 변경
- overlay 동작 변경
- config 해석 변경

추가 제한:
- `should_stop`, `is_overlay_candidate`, `expand_overlay`, `realign_focus_after_overlay`의 호출 조건/입력 구조 변경 금지
- row 스키마/필드명 변경 금지

---

## 6. 예상 Diff 영향

## 6-1) 변경 예상 영역
- `tb_runner/collection_flow.py` 내부에서 `collect_tab_rows` 본문 분해
- 동일 파일 내 private helper 추가/이동
- 외부 모듈(`overlay_logic.py`, `diagnostics.py`, `script_test.py`)의 동작 변경 없음

## 6-2) 리뷰 포인트
1. 실행 순서가 기존과 동일한가
2. 저장 타이밍(초기/체크포인트/종료)이 동일한가
3. stop reason/status 표기 값이 동일한가
4. overlay 진입/스킵 조건이 동일한가
5. `tab_cfg` mutation 키/값이 동일한가

## 6-3) 동일 동작 체크리스트
- [ ] open 실패 시 `TAB_OPEN_FAILED` row 생성 및 즉시 저장
- [ ] anchor row(step 0) 생성/annotate/crop/save 유지
- [ ] main step별 fingerprint/semantic/noise 필드 동일
- [ ] stop evaluator 입력/출력 처리 동일
- [ ] global_nav skip 처리 동일
- [ ] overlay candidate 판정 및 expanded dedupe 동일
- [ ] overlay realign + post-realign anchor stabilize 조건 동일
- [ ] scenario summary(perf finalize/log) 동일
- [ ] run 최종 export(`script_test.py` finally) 동일

---

## 결론

PR1은 `collect_tab_rows`를 “읽기 가능한 단계 함수”로 분해하는 구조 개선 작업이다.
핵심은 코드 길이 축소가 아니라, **기존 실행 계약과 side effect 위치를 1:1로 보존**하는 것이다.
