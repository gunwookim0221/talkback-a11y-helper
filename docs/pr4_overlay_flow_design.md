# PR4 Overlay Flow 설계서 (구조/계약 정리 중심)

> [!IMPORTANT]
> 이 문서는 **historical design record(당시 설계 기록)** 입니다.
> 현재 운영 기준은 `docs/current-client-architecture.md` 및 운영 문서(`system-overview.md`, `architecture.md`, `testing-pipeline.md`)를 우선 참조하세요.


본 문서는 PR1/PR2/PR3 다음 단계로, Python runner의 overlay 구간을 **정책(policy) / 실행(execution) / 복귀(realign/recovery) / 저장(persist)** 책임으로 분리하기 위한 기준서다.

- 대상 범위: `script_test.py`, `tb_runner/collection_flow.py`, `tb_runner/overlay_logic.py` 중심의 Python runner overlay 흐름
- 제외: Android helper (`app/*`) 전부
- 원칙:
  - 현재 동작과 로그 흐름을 기준으로 정리
  - 추상적 일반론 금지
  - PR4는 우선 구조/계약 명확화가 1차 목표

---

## 1) 현재 overlay 흐름 분석

아래는 현재 코드 기준 실제 실행 순서다.

### 1-1. main step 직후 overlay candidate 판단
- main loop 한 step의 row를 수집/annotate/stop 평가한 뒤 row를 `rows/all_rows`에 append/save 한다.
- 그 다음 `_overlay_phase(...)`에서 `is_overlay_candidate(row, tab_cfg)`를 호출한다.
- `scenario_type='global_nav'`이면 overlay 후보 판단 자체를 막고 `blocked_by_global_nav_only`로 취급한다.

### 1-2. overlay entry click
- 후보가 맞고, 해당 entry fingerprint가 `expanded_overlay_entries`에 없으면 진입 시도.
- click 우선순위:
  1. `focus_view_id` 기반 `touch(type_='r')`
  2. 실패 시 `visible_label` 기반 `touch(type_='a')`
- click 실패 시 현재 구현은 post-click 결과를 사실상 `unchanged(entry_click_failed)`로 로깅하고 overlay 실행은 생략된다.

### 1-3. post-click classification
- click 성공 후 `classify_post_click_result(...)` 호출.
- 분류값:
  - `overlay`
  - `navigation`
  - `unchanged`
- `overlay_logic.classify_post_click_result`는 아래 신호를 결합한다.
  - pre/post main fingerprint 동일 여부 (`unchanged`)
  - dump tree signature overlap ratio
  - 명시적 navigation cue (`navigate up`, `back`, toolbar/view_id 신호)
  - overlay candidate guard (allow 후보였던 entry는 저 overlap을 navigation으로 쉽게 보내지 않음)

### 1-4. overlay 내부 step 수집
- classification=`overlay`일 때만 `expand_overlay(..., skip_entry_click=True)` 실행.
- 내부 루프(`1..OVERLAY_MAX_STEPS`)에서 step을 `move=True,next`로 수집하고 `context_type='overlay'`로 저장.
- overlay row는 즉시 `rows/all_rows`에 append된다.

### 1-5. overlay break 조건
- `expand_overlay` 내부 강제 break(should_stop 이전) 조건:
  - `move_failed_without_focus_change` (overlay warmup 이후)
  - `same_overlay_fingerprint` (overlay warmup 이후 + 연속 반복 + `no_progress/failed` 결합)
  - `same_overlay_focus` (overlay warmup 이후 + 연속 반복 + `no_progress/failed` 결합)
- 반복 징후 시 `[OVERLAY][repeat]`, 실제 break 시 `[OVERLAY][break]` 로그를 남긴다.
- 강제 break가 없으면 overlay row를 append 후 `should_stop(...)`를 overlay 컨텍스트에서 다시 호출하여 종료를 판단한다.

### 1-6. overlay row 저장
- overlay 내부에서도 break/stop/checkpoint 시점마다 `save_excel_with_perf(..., with_images=False)`를 호출한다.
- 루프 종료 후 `press_back_and_recover_focus(...)`를 실행하고 마지막 overlay row에 `overlay_recovery_status`를 기록한 뒤 다시 저장한다.

### 1-7. overlay 종료 후 realign
- `_overlay_phase`로 복귀 후 `realign_focus_after_overlay(...)` 실행.
- 결과 로그: `[OVERLAY] realign status='...' entry_reached=... steps_taken=... match_by='...'`
- `entry_reached=True`면 `post_realign_pending_steps_delta=2`를 반환하고 `stabilize_anchor(... phase='overlay_realign')`를 1회 수행한다.

### 1-8. overlay_realign anchor/context 확인
- `stabilize_anchor(phase='overlay_realign')` 실패 시 `[ANCHOR][overlay_realign] stabilization failed` 로그를 남긴다.
- 성공/실패와 무관하게 main loop는 계속 진행되며, 이후 main row에 `overlay_recovery_status='after_realign'`가 최대 2step 반영된다.

### 1-9. main loop 복귀
- `_overlay_phase`가 종료되면 `_main_loop_phase`로 즉시 복귀한다.
- 복귀 후에는 동일 루프 계약 유지:
  - 다음 step 수집
  - stop 평가
  - row append/save
  - 필요 시 overlay 후보 판단

### 1-10. 텍스트 다이어그램

```text
main step collect/annotate/stop eval
→ main row append/save
→ overlay candidate check
→ click entry
→ classify post-click result
→ (if overlay) collect overlay steps
→ overlay break/stop
→ persist overlay rows/checkpoints
→ press_back recovery
→ realign to entry
→ overlay_realign stabilize_anchor verify
→ resume main loop
```

---

## 2) 현재 구조 문제 요약

### 2-1. policy와 execution 혼재
- 후보 정책(`is_overlay_candidate`)과 실행 오케스트레이션(`_overlay_phase`)은 `collection_flow.py`에 있고,
- 분류/확장/realign 실행은 `overlay_logic.py`에 있다.
- 즉, 판단-실행-복귀가 파일 단위로 교차되어 변경 영향 범위 추적이 어렵다.

### 2-2. candidate/execution/recovery/save 결합
- `_overlay_phase`에서 후보 판정, click, classification, expand, realign, stabilize_anchor까지 직렬 수행한다.
- `expand_overlay` 내부는 row append + break + should_stop + back recovery + save를 한 함수에서 모두 처리한다.
- 결과적으로 overlay 정책만 수정하려 해도 저장 타이밍/복귀 타이밍 회귀 위험이 함께 발생한다.

### 2-3. overlay 변경이 main loop 회귀로 이어지는 이유
- main row append/save 이후 overlay가 실행되는 현재 순서가 코드상 암묵적으로 박혀 있다.
- overlay_realign 결과(`post_realign_pending_steps`)가 stop evaluator(PR3)와 연결되어 있어, overlay 내부의 작은 변경도 main stop 민감도에 영향이 간다.

### 2-4. Home/Energy/Food 시나리오 부담
- 시나리오마다 `overlay_policy.allow/block` 구성이 다르고, 라벨/리소스/클래스 조합 신뢰도가 다르다.
- 특히 `Add`, `More options`는 홈/플러그인 화면 모두에 등장 가능하여 false positive/negative 위험이 높다.
- 구조적으로 정책과 실행이 분리되지 않으면 시나리오별 예외 분기 누적이 쉽게 발생한다.

---

## 3) overlay candidate 정책 정리

### 3-1. overlay 후보 row 정의
- 기본: 현재 main row가 `overlay_policy.allow_candidates` 중 하나와 매칭되면 후보.
- 매칭 키:
  - `resource_id` (`focus_view_id`와 exact)
  - `label` (`normalized_visible_label`과 exact)
  - `class_name` (focus node class)
- 세 키 중 정의된 항목만 AND로 충족해야 매칭된다.

### 3-2. 우선순위
1. `block_candidates` 선차단
2. `allow_candidates` 매칭
3. 미매칭 시 비후보

즉, 동일 대상이 allow/block에 모두 있으면 block 우선이다.

### 3-3. no_overlay_policy / explicit allow / deny 의미
- `no_overlay_policy`: `overlay_policy` 자체 부재 → 전면 차단(`blocked_no_overlay_policy`)
- `empty_allow_list`: 정책은 있으나 allow 없음 → 전면 차단(`blocked_empty_allow_list`)
- explicit allow: allow 항목 매칭 시만 후보
- explicit deny: block 항목 매칭 즉시 차단

### 3-4. 재확장 방지 규칙
- `make_overlay_entry_fingerprint(tab_name, row)`를 key로 `expanded_overlay_entries` set에 저장.
- 이미 확장한 fingerprint는 `[OVERLAY] skip already expanded entry`로 스킵.

### 3-5. false positive 완화 안전장치
- global_nav 시나리오는 overlay 판단 자체를 차단.
- post-click classification에서 `entry_is_overlay_candidate` guard로 저 overlap을 무조건 navigation으로 보내지 않음.
- click 실패 시 overlay 실행으로 진입하지 않음.

---

## 4) post-click classification 체계 정리

> 현재 구현은 `overlay/navigation/unchanged` 3분류이며, PR4 구조 문서에서는 `unknown`을 계약상 예약값으로 포함한다.

### 4-1. overlay
- 판정 기준(현재):
  - pre/post fingerprint 동일이 아님
  - explicit navigation cue가 없음
  - low-overlap navigation 조건이 guard되지 않음
- 이후 흐름: `expand_overlay` 실행 → realign → (entry_reached 시) overlay_realign stabilize
- main loop 영향: `post_realign_pending_steps` 설정 가능, overlay row가 추가됨

### 4-2. navigation
- 판정 기준(현재):
  - `navigate up/back/up button` 등 cue 탐지
  - 또는 signature overlap < 0.30 (guard 제외)
- 이후 흐름: overlay 루틴 스킵
- main loop 영향: main step만 유지, overlay_count 증가 없음

### 4-3. unchanged
- 판정 기준(현재):
  - pre/post main fingerprint 동일
  - 또는 entry click 실패를 `_overlay_phase`에서 사실상 unchanged 성격으로 처리
- 이후 흐름: overlay 루틴 스킵
- main loop 영향: 다음 step으로 진행

### 4-4. unknown (목표 계약)
- 판정 기준(목표):
  - 분류 근거 부족/수집 실패/예외 방어 시
- 이후 흐름(목표):
  - 기본은 `overlay 루틴 스킵 + 진단 로그 강화`
- main loop 영향(목표):
  - stop 정책을 건드리지 않고 안전 복귀

---

## 5) overlay 내부 수집 및 break 정책

### 5-1. overlay 내부 수집 방식
- `collect_focus_step(move=True,direction='next')`를 overlay 전용 wait/announcement 파라미터로 수행.
- row 공통 필드:
  - `context_type='overlay'`
  - `parent_step_index`(entry main step)
  - `overlay_entry_label`

### 5-2. overlay 내부 반복 판단 기준
- 강제 break 신호(우선):
  - `same_overlay_fingerprint`
  - `same_overlay_focus` (triplet 또는 visible/announcement 반복)
  - `move_failed_without_focus_change`
- 강제 break가 없을 때만 `should_stop`로 추가 종료 판단.

### 5-3. same_overlay_fingerprint
- `build_row_fingerprint` 기준으로 이전 overlay row와 완전 동일이면 break.
- 목적: overlay 내부 무한 순환 단축.

### 5-4. move_failed_without_focus_change
- `move_result in {'failed','no_progress'}` 이면서 focus/fingerprint 변화가 없으면 즉시 break.
- 목적: 실제 이동 실패 루프의 조기 종료.

### 5-5. overlay 내부 stop 적용 범위
- overlay에서도 `should_stop`를 호출하지만,
- main stop(PR3)와 동일 의미로 취급하지 않고 overlay local 종료로 사용한다.

### 5-6. overlay 내부 max step 정책
- 상한: `OVERLAY_MAX_STEPS`.
- break/stop이 없더라도 상한 도달 시 루프 종료 후 recovery/저장으로 진행.

### 5-7. main stop(PR3)와 overlay break 구분 계약
- main stop(PR3): 시나리오 메인 수집 종료 결정 (`status=END`, loop break).
- overlay break: overlay 서브플로우 내부 종료 결정(메인 종료 아님).
- PR4 계약: 두 정책의 카운터/이유(reason)/로그 태그를 명시적으로 분리한다.

---

## 6) realign 및 복귀 계약

### 6-1. `realign_entry_reached` 의미
- overlay 종료 후 next 이동 탐색 중 entry 기준점(`view_id/label/bounds`)에 다시 도달했다는 뜻.
- 이 상태에서만 `post_realign_pending_steps`와 overlay_realign 안정화가 활성화된다.

### 6-2. entry_reached 실패 처리
- 상태값 예:
  - `skip_realign_not_before_entry`
  - `realign_entry_not_found`
- 실패 시에도 main loop는 계속 진행하되, `post_realign_pending_steps`는 증가시키지 않는다.

### 6-3. `match_by(view_id 등)` 의미
- `view_id` > `label` > `bounds` 순으로 해석 신뢰도가 높다.
- `bounds` only 매칭은 경고 로그 대상(`overlay realign matched by bounds only`).

### 6-4. overlay_realign 이후 context verify / anchor stabilize 역할
- 현재는 `stabilize_anchor(phase='overlay_realign', verify_reads=1)` 호출로 최소 재정렬을 수행.
- 목적:
  - overlay 종료 후 잘못된 context 잔류 방지
  - 다음 main step의 baseline 안정화

### 6-5. main loop 재개 시 step numbering/duplicate 영향
- step numbering은 main loop 연속 번호를 유지(overlay step은 별도 context).
- overlay 후 2step(`post_realign_pending_steps`)은 `overlay_recovery_status='after_realign'`로 표기되어 stop evaluator가 완화 판단에 활용한다.
- PR4에서 이 계약을 깨면 duplicate/loop 판정 분포가 즉시 변한다.

---

## 7) PR4 목표 구조 제안

아래는 함수명 예시이며, 실제 구현에서는 기존 함수 재배치/통합 중심으로 조정한다.

### 7-1. 정책 계층
- `_is_overlay_candidate(row, tab_cfg) -> CandidateDecision`
  - allow/block/no_policy 판단 전담
  - 이유(reason)와 매칭근거(match_fields) 반환

### 7-2. post-click 분류 계층
- `_classify_overlay_post_click(client, dev, tab_cfg, pre_row) -> PostClickClassificationResult`
  - 분류 + 근거( fingerprint_equal, overlap_ratio, cue_flags )를 구조화

### 7-3. overlay 실행 계층
- `_run_overlay_collection(...) -> OverlayCollectionResult`
  - 현재 `expand_overlay` 책임을 실행/중단/저장 메타 중심으로 구조화
  - overlay 내부 break reason과 should_stop reason 분리

### 7-4. 정리/저장 계층
- `_finalize_overlay_result(...)`
  - overlay row append/save, overlay_count/overlay_step_count 반영 지점을 명시

### 7-5. 복귀 계층
- `_realign_after_overlay(...) -> OverlayRealignResult`
  - realign + overlay_realign stabilize + resume_allowed 판단

### 7-6. 핵심 분리 원칙
- 정책(후보/분류)과 실행(수집/중단), 복귀(realign), 저장(persist)을 한 함수에 혼합하지 않는다.
- 단, PR4는 동작 변경보다 **계약 가시화**가 우선이므로 호출 순서는 유지한다.

---

## 8) overlay result 구조체 설계

PR4에서 `_overlay_phase`의 암묵 상태 전달을 줄이기 위해 아래 결과 객체 도입을 제안한다.

### 8-1. 필드 정의
- `triggered: bool`
  - 의미: 후보 판정 + entry click/classification까지 진행했는지
  - 생산: overlay orchestration
  - 소비: main loop 로그/요약

- `classification: str`
  - 의미: `overlay|navigation|unchanged|unknown`
  - 생산: post-click classifier
  - 소비: 분기 실행/회귀 분석

- `entry_label: str`
  - 의미: entry row label snapshot
  - 생산: orchestration
  - 소비: 로그, diagnostics

- `entry_view_id: str`
  - 의미: entry row view_id snapshot
  - 생산: orchestration
  - 소비: click/realign 진단

- `overlay_rows: list[dict]`
  - 의미: overlay 수집 결과 row 집합
  - 생산: overlay collection runner
  - 소비: rows/all_rows append, summary

- `break_reason: str`
  - 의미: overlay 강제 break/stop의 대표 이유
  - 생산: overlay collection runner
  - 소비: 회귀 판정(중복/누락)

- `realign_attempted: bool`
  - 의미: realign 함수 호출 여부
  - 생산: realign runner
  - 소비: perf summary

- `realign_success: bool`
  - 의미: `entry_reached` 성공 여부
  - 생산: realign runner
  - 소비: post_realign_pending_steps 결정

- `entry_reached: bool`
  - 의미: realign entry 도달 여부
  - 생산: realign runner
  - 소비: overlay_realign stabilize gate

- `resume_allowed: bool`
  - 의미: main loop 정상 복귀 허용 여부(현재는 항상 true에 가까움)
  - 생산: finalize 단계
  - 소비: 향후 안정성 게이트(로그/경고)

- `diagnostics: dict[str, Any]`
  - 의미: overlap_ratio, navigation cue, match_by, save_count 등 부가 근거
  - 생산: 각 하위 단계
  - 소비: 로그 기반 검증/테스트

---

## 9) 실행 순서 계약 (가장 중요)

**PR4에서는 overlay 구조를 정리하되, 아래 실행 순서는 절대 변경하면 안 된다.**

1. main step row 수집/annotation/stop 평가
2. main row를 먼저 `rows/all_rows`에 저장(필요 시 checkpoint 저장)
3. 그 다음 overlay candidate 판단
4. overlay entry click 후 post-click classification
5. classification=`overlay`일 때만 overlay row 수집
6. overlay row persist(overlay 내부 break/stop/checkpoint/recovery 시점 포함)
7. overlay 종료 후 realign 수행
8. realign 성공 시 overlay_realign(anchor stabilize) 수행
9. main loop 복귀

### 9-1. 저장 순서 명시
- 현재 계약은 **저장 후 overlay 진입**(main row 기준)이다.
- 즉, `overlay 후 main row 저장`으로 바꾸면 안 된다.

### 9-2. 시점 고정 항목
- post-click classification: entry click 직후
- overlay row persist: overlay 내부 루프 중/종료 시
- realign: overlay collection 종료 직후
- main loop 복귀: realign(및 조건부 overlay_realign) 이후

---

## 10) PR4 범위 정의

### IN SCOPE
- overlay 정책/실행/복귀 구조 정리
- overlay candidate 계약 명확화
- classification 구조 정리
- overlay result 구조체 설계
- overlay와 main loop 경계 명확화

### OUT OF SCOPE
- start pipeline 변경
- stop policy 재설계(PR3 영역)
- pre_navigation 변경
- anchor heuristic 변경
- config 해석 변경
- save/export 전체 정책 변경

---

## 11) 예상 영향 및 리스크

### 11-1. 예상 영향
- `overlay_count` 변화 가능성
  - classification 근거를 명시화하면 기존 애매 케이스의 분류가 달라질 수 있음
- overlay row 수 변화 가능성
  - break reason 분리/정규화 시 종료 지점이 달라질 수 있음
- realign 성공률 변화 가능성
  - realign 계약 명시 후 `entry_reached` 판정 로깅 정교화로 통계가 변동 가능
- duplicate 판단 변화 가능성
  - overlay 후 main 복귀 마커 처리 계약이 명확해지면 PR3 stop 분포가 이동할 수 있음
- main loop 복귀 실패 가능성
  - 구조 분리 과정에서 resume 경계를 잘못 옮기면 회귀 위험

### 11-2. 필수 명시 리스크
- Add / More options overlay 누락
- overlay 후 wrong context 복귀
- overlay row 중복/누락
- realign 이후 조기 stop

---

## 12) 로그 기반 검증 전략

PR4 구현 후에는 아래 로그를 **변경 전/후 동일 시나리오**로 비교한다.

### 12-1. 필수 비교 로그
- `[OVERLAY] candidate matched`
- `[OVERLAY] post_click classification`
- `[OVERLAY][repeat]`
- `[OVERLAY][break]`
- `[OVERLAY] realign status`
- `[ANCHOR][overlay_realign]`
- overlay 이후 main `[STEP]` 흐름 연속성
- `scenario_summary`의 `overlay_count / overlay_step_count`

### 12-2. 정상 변화 vs 회귀 판정 기준

#### 정상 변화
- 로그 키/순서는 유지되며, reason 상세도가 증가
- overlay_count가 소폭 변해도, 분류 근거(`classification`, `break_reason`, `match_by`)가 설명 가능
- main step 연속성(누락/역전 없음) 유지

#### 회귀
- `candidate matched` 후 `post_click classification` 로그가 누락
- overlay row가 append됐는데 `overlay_count`/`overlay_step_count` 반영이 불일치
- `realign status`가 있는데 이후 main step가 비정상 중단
- `overlay_realign` 후 `wrong context`로 보이는 mismatch 급증
- 기존 대비 `same_overlay_fingerprint`/`move_failed_without_focus_change` break가 과도하게 감소 또는 증가

---

## 부록 A) PR4 구현 체크리스트(요약)

- [ ] `_overlay_phase`에 집중된 후보/분류/실행/복귀/저장 책임 분리
- [ ] 실행 순서 계약(Section 9) 고정
- [ ] overlay result 객체 도입 및 호출부 소비 경로 명시
- [ ] 로그 키 호환성 유지 + 진단 필드 확장
- [ ] 시나리오별(Home/Energy/Food) overlay 정책 오탐/미탐 회귀 확인
