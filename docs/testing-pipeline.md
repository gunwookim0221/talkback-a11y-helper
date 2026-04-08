# Testing Pipeline

[System Overview 보기](system-overview.md) | [Architecture 보기](architecture.md)

## 문서 목적

이 문서는 현재 저장소의 **실제 collector 실행 흐름**을 기준으로 작성되었습니다.

중요: 현재 단계는 DFS/full-depth 탐색이 아니라, 시나리오 기반 **linear collector 안정화 + 데이터 정제** 단계입니다.

---

## 1) Runner 진입

- 진입점: `script_test.py`
- 주요 흐름
  1. `load_runtime_bundle(TAB_CONFIGS)`로 runtime defaults/override 병합
  2. `enabled=true` 시나리오만 순차 실행
  3. 시나리오마다 `collect_tab_rows(...)` 수행
  4. 중간 checkpoint 저장 + 종료 시 final 저장

---

## 2) Scenario 시작 안정화

`collect_tab_rows(...)`는 먼저 `open_scenario(...)`를 호출해 아래 순서로 진입 안정화를 수행합니다.

1. tab stabilize (`stabilize_tab_selection`)
2. optional pre_navigation
3. anchor stabilize (`stabilize_anchor`)

### Anchor stabilization 핵심

- select 후 즉시 성공으로 끝내지 않고, **settle 포함 2회 검증**(`stabilize_anchor_focus`)을 통과해야 stable로 판정
- 기본 재시도 경로 존재(`anchor_retry_count`)
- 목표: 시작 포커스 흔들림/일시적 mismatch를 줄여 step loop 시작 품질을 높임

`stabilization_mode`별 성공 판정:
- `anchor_only`: anchor double-verify 기준
- `tab_context`: context verify 기준
- `anchor_then_context`: anchor double-verify + context verify

---

## 3) Main step loop (collect_focus_step + SMART_NEXT)

시나리오가 열리면 anchor row(step 0)를 먼저 저장하고, 이후 step 1..N 반복:

- `collect_focus_step(move=True, direction="next")`
- move 결과 + announcement + get_focus + dump/crop + 품질 메타데이터를 row로 누적
- SMART_NEXT payload(`smart_nav_requested_view_id`, `smart_nav_resolved_view_id`, `smart_nav_actual_view_id`, `post_move_verdict_source`)를 함께 기록
- `global_nav`에서는 SMART_NEXT의 resolved/actual view id가 requested target view id와 일치하면 이를 post-move 1차 truth로 우선 반영
- `StopEvaluator`로 종료 여부 판정

### Announcement 안정화 대기

main loop에서 다음 키를 사용합니다.
- `main_announcement_wait_seconds`
- `main_announcement_idle_wait_seconds`
- `main_announcement_max_extra_wait_seconds`

동작:
- step 시작 시 직전 merged announcement를 baseline으로 기록
- 고정 대기 후 partial announcements 수집, baseline 대비 변경(candidate change) 여부를 우선 판단
- idle polling(짧은 주기)으로 "새 candidate" 변화가 멈출 때까지 추가 대기
- 최대 extra wait을 넘기면 강제 종료
- baseline prefix가 현재 발화 앞에 붙는 오염 패턴은 일반 규칙으로 trim해 최종 speech를 선택
- 결과 row에 `announcement_extra_wait_sec`, `announcement_window_sec` 기록

---

## 4) get_focus 해석 및 fallback 최적화

`get_focus`는 `success=true`만 절대 기준으로 쓰지 않습니다.

핵심 동작:
- nested `node/focusNode/...` 우선 사용
- 필요 시 top-level payload(`text/viewIdResourceName/boundsInScreen/...`)도 후보로 수용
- `success=false + top-level`이어도 payload가 충분하면(강한 bounds/label/identity 신호) dump fallback을 생략하고 사용
- 불충분하면 dump fallback 시도 후 focused node가 더 신뢰 가능할 때 교체
- fast path에서는 정책상 dump를 건너뛸 수 있음

row 진단 필드 예:
- `focus_payload_source`
- `get_focus_response_success`
- `get_focus_top_level_success_false`
- `get_focus_top_level_payload_sufficient`
- `get_focus_success_false_top_level_dump_attempted`
- `get_focus_success_false_top_level_dump_found`
- `get_focus_success_false_top_level_dump_skipped`
- `get_focus_dump_skip_reason`
- `get_focus_final_payload_source`

---

## 5) Overlay 진입/복귀

main row가 overlay entry candidate면:

1. entry click 시도
2. post-click probe(`collect_focus_step(move=False)`)로 분류
   - `overlay`
   - `navigation`
   - `unchanged`
3. `overlay`인 경우에만 `expand_overlay(...)` 실행
4. overlay 종료 후 back recovery
5. 필요 시 entry 기준 realign + anchor/context 재안정화

overlay 수집에서도 별도 announcement 안정화 키 사용:
- `overlay_announcement_wait_seconds`
- `overlay_announcement_idle_wait_seconds`
- `overlay_announcement_max_extra_wait_seconds`

---

## 6) StopEvaluator / stop policy

`should_stop(...)`는 strong + weak 신호를 함께 봅니다.

- strong 계열: terminal signal, global nav 경계 진입/이탈
- weak 계열: repeat(same_like), no progress, move failure, empty row
- 최근 반복/overlay realign 직후 반복(no progress) 조건을 보수적으로 조합

`stop_policy` 지원 키:
- `stop_on_global_nav_entry`
- `stop_on_global_nav_exit`
- `stop_on_terminal`
- `stop_on_repeat_no_progress`

주요 reason:
- `global_nav_entry`
- `global_nav_exit`
- `global_nav_end`
- `smart_nav_terminal`
- `move_terminal`
- `repeat_no_progress`
- `repeat_semantic_stall`
- `repeat_semantic_stall_after_escape` (plugin/new_screen 계열 content 시나리오에서 stall escape 1회 실패 시)

---

## 7) content vs global_nav

`scenario_type`은 `content` / `global_nav`를 지원합니다.

- `content`: 본문 수집 중심
- `global_nav`: 하단 탭/좌측 rail 같은 전역 내비게이션 수집 중심

global nav 판별은 `is_global_nav_row(...)`에서 아래 신호를 점수화합니다.
- resource id
- label/announcement
- selected pattern + selected state
- region hint(`bottom_tabs`/`left_rail`)

운영 가이드:
- content/global_nav를 같은 시나리오에서 과도하게 섞기보다 분리 실행이 더 안전함

---

## 8) Row 품질 메타데이터와 리포트

main row에는 후처리 품질 메타데이터가 기록됩니다.

- `fingerprint`
- `fingerprint_repeat_count`
- `is_duplicate_step`
- `is_recent_duplicate_step`
- `recent_duplicate_distance`
- `recent_duplicate_of_step`
- `is_noise_step`
- `noise_reason`

엑셀 저장(`save_excel`)은 4개 시트로 구성됩니다.
- `raw`: 전체 row + 파생 컬럼
- `filtered`: duplicate/recent_duplicate는 기본 제외하며, noise는 보조 신호로 사용합니다. `WARN/FAIL`, `review_note`/`failure_reason` 존재, visible/speech mismatch(오염 포함) 등 리뷰 가치가 있으면 noise여도 유지합니다.
- `summary`: overall/scenario 집계
- `result`: 최종 판정(PASS/WARN/FAIL), `failure_reason`, `debug_log_path/debug_log_name`(WARN/FAIL 중심 디버그 로그 링크)

상태 토큰 분리 컬럼:
- `speech_main`, `speech_status_tokens`
- `visible_main`, `visible_status_tokens`

의도: badge/상태성 토큰(예: selected, tab x of y, new content available)을 main label과 분리해 검증 정확도를 높임.

---

## 9) 저장 타이밍

- partial save: checkpoint 주기(`checkpoint_save_every`) 또는 stop 시점
- final save: run 종료 `finally` 블록에서 이미지 포함 저장
- 예외 발생 시에도 중간 결과를 우선 저장
