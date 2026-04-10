# PR3 Stop Policy 설계서 (동작 변경)

> [!IMPORTANT]
> 이 문서는 **historical design record(당시 설계 기록)** 입니다.
> 현재 운영 기준은 `docs/current-client-architecture.md` 및 운영 문서(`system-overview.md`, `architecture.md`, `testing-pipeline.md`)를 우선 참조하세요.


본 문서는 PR1(함수 분해), PR2(start pipeline 구조화) 이후 단계로, Python runner의 **stop policy / 반복 탐지 / no_progress 판단 / overlay 이후 흐름 제어**를 실제 코드 기준으로 보완하는 설계 문서다.

- 대상 범위: `script_test.py`, `tb_runner/*` 중 stop/loop/overlay 후속 제어
- 제외: Android helper(`app/*`), start pipeline 구조 자체(PR2), anchor heuristic 자체 변경
- 원칙: 기존 정책 폐기가 아니라 **확장/보완**

---

## 1) 현재 stop 정책 분석

### 1-1. `should_stop(...)` 현재 동작 요약

현재 stop 평가는 `tb_runner.diagnostics.StopEvaluator.evaluate()`가 수행하고, `collection_flow._main_loop_phase()`와 `overlay_logic.expand_overlay()`에서 호출된다.

- 입력 상태
  - 현재 row + 이전 row
  - 누적 카운터: `fail_count`, `same_count`
  - 이전 fingerprint: `prev_fingerprint`
  - 시나리오 문맥: `scenario_type`, `stop_policy`, `scenario_cfg`
- 출력
  - `(stop, fail_count, same_count, reason, current_fingerprint, details)`

핵심 판단 신호:

1. **terminal 계열**
   - `last_smart_nav_terminal=True` → `smart_nav_terminal` stop.
   - `move_result/last_smart_nav_result`가 terminal 집합일 때 `move_terminal` 가능.

2. **반복/정체 계열**
   - `same_like` 계산(엄격 서명 동일 또는 부분 공유 ≥3 또는 이전 fingerprint 동일 또는 semantic 서명 동일).
   - `same_count` 누적(`same_like`이면 +1).
   - `fail_count` 누적(`move_result='failed'`이면 +1).
   - `no_progress`: 
     - `(same_like && (move_failed || move_terminal || smart_nav_result in {failed, unchanged}))`
     - 또는 `bounded_two_card_loop`.

3. **recent duplicate 계열**
   - `_annotate_row_quality()`가 최근 창(window=5) 기준으로 아래 필드를 row에 기록:
     - `is_recent_duplicate_step`, `recent_duplicate_distance`
     - `is_recent_semantic_duplicate_step`, `recent_semantic_duplicate_distance`
     - `recent_semantic_unique_count`
   - stop evaluator는 해당 필드를 소비해 반복 성격을 강화.

4. **`bounded_two_card_loop`**
   - 조건: `recent_semantic_duplicate=True` && `distance in [2..4]` && `recent_semantic_unique_count <= 2`.
   - 의미: 완전 동일 1개가 아니라, 2~4 step 간격으로 좁은 의미 집합(대개 2개 카드) 왕복.

5. **`repeat_stop_hit`**
   - `reason`이 `repeat_no_progress | bounded_two_card_loop | repeat_semantic_stall` 중 하나일 때 True.
   - stop trigger의 “반복성 종료” 여부를 로그에서 식별하는 플래그.

6. **`safety_limit`**
   - main loop에서 stop 미발생 + `max_steps` 소진 시 `_persist_phase()`가 마지막 row 기준 `stop_reason='safety_limit'`로 요약.
   - 즉, 안전 종료는 evaluator가 아니라 시나리오 마무리 단계에서 기록됨.

### 1-2. 현재 로그 기준 stop 발생/미발생 패턴

현재 코드가 남기는 대표 로그 패턴:

- 평가 로그: `[STOP][eval] ... decision='stop|continue' reason='...'`
- 실제 종료 로그: `[STOP][triggered] ... reason='...'`
- 시나리오 요약 로그: `[STOP][summary] ... reason='...'`
- overlay 내부 강제 중단 로그: `[OVERLAY][break] reason='same_overlay_focus|...'`

정리:

- stop이 발생하는 경우
  - terminal 신호, 반복+정체 약신호 조합, bounded two-card loop, semantic stall.
- stop이 즉시 발생하지 않는 경우
  - 빈 텍스트만 있는 step(다른 약신호 부족 시), after_realign 마커 단독.
- overlay는 별도 강제 break + should_stop 병행으로 조기 종료 가능.

### 1-3. 현재 정책의 장점/문제점

장점:

- terminal/반복/semantic 반복을 모두 반영하는 다중 신호 구조.
- recent duplicate(거리/고유개수)로 단순 동일 row 반복 이상을 포착.
- after_realign 구간의 반복 정체를 별도 조건으로 다룸.

문제점:

- strict duplicate와 semantic duplicate의 정책 강도가 명시적으로 분리되어 있지 않음(동일 카운터 경로에 수렴).
- overlay 직후 1~2 step은 복구/정렬 과정인데도 repeat 신호가 강하게 누적될 수 있음.
- stop 최소 step 보장이 없어, 특정 시나리오에서 “초기 1~2 step 조기 stop” 위험이 남음.
- overlay 내부는 강제 break 규칙과 should_stop가 중첩되어 기준 일관성이 약함.

---

## 2) 현재 문제 정의

### 2-1. 너무 빨리 멈추는 경우

1. **overlay realign 직후 조기 stop**
   - main row에 `overlay_recovery_status='after_realign'`가 붙은 초반 step에서, same_like + move_failed가 결합되면 `repeat_no_progress`가 빠르게 발생 가능.

2. **semantic duplicate 과민 반응**
   - 문구가 유사한 카드형 UI에서 실제로는 정상 탐색 중인데, `recent_semantic_duplicate + unique_count 낮음`이 반복으로 해석될 수 있음.

### 2-2. 너무 늦게 멈추는 경우

1. **실제 루프인데 weak signal 분산**
   - move 실패가 간헐적이고 same_like가 불안정하면 weak_signals 조합이 늦게 충족.
2. **overlay 내부 우회 루프**
   - overlay 내에서 focus가 미세 변동(텍스트/bounds 소폭 변화)할 때 forced break/should_stop 모두 늦어질 수 있음.

### 2-3. overlay 이후 반복 오인

- overlay 확장 후 realign 성공 시에도 main loop는 바로 일반 stop 평가를 재개한다.
- 현재는 `post_realign_pending_steps=2`로 마커만 부여하고 stop 완화 정책은 없다.
- 따라서 “복구 직후 정상 재진입” 단계가 반복으로 오인될 수 있다.

### 2-4. semantic duplicate 오해석

- semantic fingerprint는 정규화 텍스트 중심이므로, 정보량이 낮은 고정 문자열(예: 공통 버튼/도구 모음)에서 동일로 수렴하기 쉽다.
- strict 동일(같은 view_id+bounds)과 semantic 동일(의미만 유사)을 분리해 stop 강도를 달리하지 않으면 오탐/미탐 모두 증가한다.

### 2-5. 실제 루프 미탐

- A↔B가 아니라 A→B→C→A처럼 3노드 루프는 `bounded_two_card_loop`로 직접 포착되지 않는다.
- 또한 이동 결과가 항상 `moved`로 나오면 fail_count 기반 신호는 약해진다.

---

## 3) 반복(Loop) 정의 재정의

PR3에서 반복을 아래 4종으로 명확히 분리한다.

### 3-1. strict duplicate (완전 동일)

정의:
- 동일 step 클래스에서 아래 triplet이 반복:
  - `normalized_visible_label`
  - `focus_view_id`
  - `focus_bounds`

판정 기준(제안):
- `current_fingerprint == prev_fingerprint` 또는 `same_focus_triplet=True`.
- 우선순위: 가장 강한 반복 신호.

### 3-2. semantic duplicate (의미상 동일)

정의:
- 텍스트/리소스 정규화 결과가 동일하나, bounds 또는 상세 필드가 달라 strict 동일은 아님.

판정 기준(제안):
- semantic signature 동일 + strict fingerprint 불일치.
- 최근 창에서 semantic unique 개수와 거리 함께 고려.

### 3-3. benign repeat (정상 흐름 반복)

정의:
- 반복처럼 보이나, 실제로는 탐색/복구/정렬 단계로 해석 가능한 반복.

판정 기준(제안):
- overlay realign 직후 grace window 내 반복.
- move 결과가 `moved/scrolled`이고, 최근 N step에서 새로운 strict fingerprint가 관찰됨.
- 전역 내비게이션/시작 게이트 정렬 단계와 같은 전이 상태.

### 3-4. harmful loop (탈출 불가능 루프)

정의:
- 탐색 진전 없이 같은 대상 집합을 순환하거나 같은 대상을 재진입.

판정 기준(제안):
- strict duplicate 고빈도 + no_progress.
- semantic duplicate 고빈도 + unique_count 매우 낮음 + distance 짧음.
- overlay 내부 forced break 조건 재현(동일 focus/동일 overlay fingerprint 반복).

---

## 4) 개선된 stop 정책 설계

> 핵심: 기존 evaluator를 유지하고, **판정 단계/완화 단계/에스컬레이션 단계**를 추가하는 확장형 설계.

### 4-1. 반복 판단 기준 개선

1. `repeat_class` 도입(계산 필드)
   - `strict_repeat`
   - `semantic_repeat`
   - `mixed_repeat`
   - `none`

2. stop 에스컬레이션을 클래스별로 분리
   - strict는 빠르게 stop 후보.
   - semantic은 추가 조건(no_progress + unique_count + window distance) 충족 시만 stop 후보.

### 4-2. semantic vs strict 분리 정책

- strict duplicate:
  - 임계값 낮게(예: same_like_count 2~3에서 후보).
- semantic duplicate:
  - 임계값 높게(예: same_like_count 4+), 동시에 `recent_semantic_unique_count <= K` 필요.
  - 이동 성공(`moved`)만 반복될 때는 즉시 stop 금지, 관찰 창을 1회 더 부여.

### 4-3. overlay 이후 reset/완화 조건

- realign 성공 직후 `grace_steps` 구간(기존 `post_realign_pending_steps` 재사용)에서:
  - semantic 기반 stop 금지(단, terminal은 예외).
  - strict+move_failed 조합만 제한적으로 stop 허용.
- overlay entry가 새 fingerprint로 확장된 경우, same_count 일부 감산(reset_partial) 적용.

### 4-4. no_progress 정의 명확화

`no_progress`를 아래 계층으로 명시:

- `hard_no_progress`:
  - move_failed && strict_repeat
  - move_terminal && same_like
- `soft_no_progress`:
  - semantic_repeat && recent_semantic_unique_count 낮음
  - bounded_two_card_loop

stop 트리거는 기본적으로 `hard_no_progress` 우선, `soft_no_progress`는 누적 관찰 후 승격.

### 4-5. 최소 step 보장

- 메인 루프 최소 보장 step(`min_steps_before_repeat_stop`) 도입 제안.
- 적용 규칙:
  - terminal/global_nav_exit는 즉시 stop 허용.
  - repeat 계열(reason in repeat_*)은 step_idx < N이면 stop 보류.
- 목표: start 직후/overlay 직후 조기 종료 감소.

### 4-6. escape 시도 로직

- 기존 `repeat_semantic_stall` 전용 escape(`attempt_stall_escape`) 유지.
- 확장:
  - `repeat_no_progress` 중 semantic 주도 케이스에서도 1회 escape 후보 검토.
  - 단, strict duplicate + failed 연속인 hard loop에는 escape 생략.

---

## 5) overlay 이후 정책

### 5-1. overlay → realign 이후 repeat 판단

- realign 성공 후 `grace_steps` 동안은 `semantic_repeat`를 benign으로 우선 분류.
- `overlay_recovery_status`가 `after_realign*`이면 아래 순서로 평가:
  1) terminal 여부
  2) strict/hard_no_progress 여부
  3) semantic/soft_no_progress는 지연 평가

### 5-2. overlay entry 기준 reset

- overlay entry fingerprint를 기준점으로 사용해,
  - realign 성공 시 `same_count` 부분 초기화(예: max(0, same_count-2)).
  - fail_count는 유지(실패 누적은 안전 신호이므로).

### 5-3. overlay 내부 반복 처리

- `expand_overlay`의 forced break(`same_overlay_fingerprint`, `same_overlay_focus`, `move_failed_without_focus_change`)는 유지.
- 단, overlay 내부 should_stop reason을 메인과 구분 가능하게 로그 태깅 강화:
  - 예: `overlay_repeat_no_progress`, `overlay_move_terminal` (reason prefix 또는 context 필드 추가).

---

## 6) 실행 순서 및 적용 위치

기존 순서는 유지하고, 적용 포인트만 확장한다.

1. main loop row 수집/품질 annotation
2. **stop pre-classification 추가** (strict/semantic/benign/harmful)
3. `should_stop` 호출(기존)
4. **post-stop adjust 단계 추가**
   - min-step gate
   - overlay-realign grace 완화
   - escape 확장 적용
5. overlay candidate 판정/실행(기존)
6. stop 확정 시 END 마킹/저장/break(기존)

overlay 경로:
- `expand_overlay` 내부 should_stop 위치는 유지.
- realign 이후 main loop 재진입 시 post-stop adjust만 추가 적용.

---

## 7) PR3 범위 정의

### IN SCOPE

- stop policy 개선(판정 계층화/완화 규칙)
- repeat detection 개선(strict vs semantic 분리)
- no_progress 판단 개선(hard/soft 구분)
- overlay 이후 흐름 개선(realign grace/reset)

### OUT OF SCOPE

- start pipeline 변경(PR2 영역)
- pre_navigation 변경
- anchor heuristic 변경
- overlay policy(allow/block candidate) 자체 변경
- save/export 로직 변경
- config 파서/해석 체계 대개편

---

## 8) 예상 영향 및 리스크

### 8-1. 예상 영향

- step 수: 일부 시나리오에서 증가(조기 stop 완화), 일부 루프 시나리오에서 감소(유해 루프 조기 차단).
- overlay count: realign 이후 진행 허용으로 소폭 증가 가능.
- stop reason 분포:
  - `repeat_no_progress` 감소 가능
  - `safety_limit` 또는 `repeat_semantic_stall_after_escape` 비중 변화 가능

### 8-2. 주요 리스크

1. **home_main step 변화(감소/증가)**
   - min-step gate/완화 규칙으로 baseline 대비 step 분포가 이동할 수 있음.

2. **energy plugin 조기 종료**
   - semantic duplicate 임계 재설정이 과도하면 plugin 카드 순회가 stop으로 오인될 수 있음.

3. **overlay 이후 루프 깨짐 실패**
   - grace가 과도하면 진짜 harmful loop를 늦게 잡아 step 낭비 증가 가능.

완화:
- 시나리오 그룹별 임계값(default + plugin/new_screen 보정)을 최소 폭으로 적용.

---

## 9) 로그 기반 검증 전략

PR3 전/후를 동일 시나리오 세트로 비교한다.

### 9-1. 비교 항목

1. step 수 변화
   - scenario별 평균/최대 step.
2. stop reason 변화
   - `repeat_no_progress`, `bounded_two_card_loop`, `repeat_semantic_stall`, `safety_limit` 분포.
3. overlay count 변화
   - overlay 진입 횟수, realign 성공률.
4. repeat 로그 변화
   - `[STOP][eval]`의 `same_like_count`, `no_progress`, `recent_repeat`, `repeat_stop_hit`.
5. duplicate 지표 변화
   - `recent_duplicate_distance`, `recent_semantic_duplicate_distance`, `recent_semantic_unique_count`.

### 9-2. 정상 변화 vs 회귀 기준

정상 변화:
- `repeat_no_progress` 감소 + 성공적 종료(reason 다양화) 증가.
- overlay 이후 1~2 step 추가 진행 후 정상 종료.
- 무한 루프성 scenario에서 총 step 감소.

회귀:
- `safety_limit` 급증.
- 동일 시나리오에서 stop_reason이 불안정하게 흔들림(실행마다 상이).
- overlay 이후 END 미도달/과도한 step 증가.

---

## 10) 동작 변경 체크리스트

- [ ] 불필요한 조기 종료(`repeat_*`)가 baseline 대비 감소했는가?
- [ ] 실제 무한/유해 루프에서 종료 step이 단축되었는가?
- [ ] overlay 이후 정상 진행(재정렬→본 루프 복귀)이 유지되는가?
- [ ] 동일 시나리오 반복 실행 시 stop reason 일관성이 유지되는가?
- [ ] strict vs semantic 반복 로그가 구분되어 분석 가능해졌는가?
- [ ] `home_main`, `energy plugin` 등 민감 시나리오에서 회귀가 없는가?

---

## 구현 메모(PR3 구현 프롬프트용)

1. `should_stop` 핵심 구조는 유지하고, pre/post 보정 레이어를 `collection_flow._main_loop_phase`에 추가한다.
2. `overlay_recovery_status`/`post_realign_pending_steps`를 stop 완화 신호로 공식 사용한다.
3. 테스트는 기존 `tests/test_diagnostics.py`, `tests/test_collection_flow.py` 패턴을 확장해 strict/semantic/grace/min-step 케이스를 분리 검증한다.
4. 로그 포맷은 기존 `[STOP][eval]`, `[STOP][triggered]`를 유지하되 분류 필드(`repeat_class`, `no_progress_class`)를 추가해 회귀 비교 가능성을 높인다.
