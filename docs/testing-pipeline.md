# Testing Pipeline (현재 운영 기준)

[System Overview](system-overview.md) | [Architecture](architecture.md) | [Runner Flow](runner_flow.md)

---

## 1) 실행 진입

- 엔트리: `script_test.py`
- 주요 절차
  1. `load_runtime_bundle(...)`로 runtime 병합
  2. `enabled=true` 시나리오만 순차 실행
  3. 시나리오마다 `collect_tab_rows(...)` 실행
  4. checkpoint/final 저장

---

## 2) Scenario start pipeline

`collect_tab_rows(...)` 시작 시 아래 순서로 진행합니다.

1. tab stabilize
2. pre_navigation(옵션)
3. anchor stabilize
4. post-open trace
5. (필요 시) global_nav start gate
6. anchor row(step 0) 수집

anchor stabilization은 단일 성공 신호가 아니라 안정화 검증(재확인 포함)을 기준으로 판단합니다.

---

## 3) Main step loop

step 1..N에서 아래를 반복합니다.

1. `collect_focus_step(move=True, direction="next")`
2. row 품질 annotation / mismatch 진단
3. `StopEvaluator` 종료 판단
4. overlay 후보면 overlay 분기 실행
5. checkpoint 저장 조건 확인

`collect_focus_step` row에는 다음 계열 정보가 포함됩니다.
- move 결과
- announcement 수집/안정화 정보
- get_focus 결과 + fallback trace
- SMART_NEXT payload 관련 필드

---

## 4) get_focus fallback 처리

운영 기준:
- `success=true`만 절대 기준으로 보지 않음
- top-level payload가 충분하면 유지 가능
- 부족하면 dump fallback 시도
- fast path는 정책적으로 dump 생략 가능

즉, get_focus는 단일 플래그가 아니라 payload 품질 기반으로 최종 채택합니다.

---

## 5) Overlay 흐름

main row가 overlay entry 후보일 때:

1. entry click
2. post-click probe(`overlay` / `navigation` / `unchanged`)
3. `overlay`일 때만 `expand_overlay(...)` 수행
4. overlay 종료 후 back recovery
5. 필요 시 realign + anchor 재안정화

---

## 6) Stop policy

`StopEvaluator.should_stop(...)`는 strong/weak 신호를 조합해 판단합니다.

- strong: terminal, global nav 경계
- weak: repeat, no_progress, move_failed, empty 계열

대표 reason 예시:
- `global_nav_entry`, `global_nav_exit`, `global_nav_end`
- `smart_nav_terminal`, `move_terminal`
- `repeat_no_progress`, `repeat_semantic_stall`

---

## 7) 저장

- partial save: checkpoint 주기 또는 stop 시점
- final save: run 종료 finally 블록
- 예외 발생 시에도 가능한 중간 결과를 먼저 저장
