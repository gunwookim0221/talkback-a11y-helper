# TalkBack Runtime Optimization (Phase 9.4)

상태: implemented with limited performance acceptance
기준일: 2026-07-13
범위: post-action verification wait와 profiler counter
비범위: traversal, coverage, visit/consumed, recovery/stop 정책, snapshot cache

## 1. Baseline과 root cause

동일 단말 `R3CX40QFDBP`, clean launch, current language, Runtime Coverage Probe OFF,
Evidence/Identity V2/Profiler ON 기준 baseline은 다음과 같다.

| Scenario | Runtime | Traversal loop | Verification poll | Recovery executor |
|---|---:|---:|---:|---:|
| Safe | 363.433 s | 184.525 s / 30 | 50.946 s / 33 | 18.916 s / 30 |
| Motion | 229.461 s | 121.717 s / 18 | 19.954 s / 18 | 0.000 s / 18 |

Profiler metric은 중첩된 inclusive duration이다. 예를 들어 `verification_poll`은
`traversal_loop` 안에서 실행된다. 따라서 위 duration을 더해 total runtime으로
해석하면 안 된다.

한 traversal step의 주요 호출 순서는 SMART_NEXT/NEXT Helper action, TalkBack
announcement logcat polling, GET_FOCUS, 필요 시 DUMP_TREE, evidence close/reduce,
visit/stop/persistence다. 기존 announcement 안정화는 새 announcement가 있으면 idle로
끝날 수 있었지만, announcement가 없으면 configured maximum까지 기다렸다. 이 고정
대기가 Motion과 Safe 공통의 반복 비용이었다.

GET_FOCUS는 자체적으로 logcat을 clear한다. 따라서 announcement window 도중
GET_FOCUS를 앞당기는 방식은 늦은 발화를 유실할 수 있어 적용하지 않았다.

## 2. Adaptive Verification Fast Path

`VerificationWaitPolicy`는 수집/판정 코드와 종료 정책을 분리한다. Fast path는 다음
조건을 모두 만족할 때만 허용한다.

1. action-scoped Evidence transaction과 Helper request ID가 일치한다.
2. Helper `ACTION_API_RESULT.success=true`가 존재한다.
3. Helper `FOCUS_COMMIT_CLAIMED`와 `POST_ACTION_OBSERVATION`이 존재한다.
4. immediate observation이 accessibility-focused이고 package/class/bounds identity를 가진다.
5. 100/300/1000 ms `DELAYED_OBSERVATION`이 모두 존재한다.
6. 세 delayed observation의 physical signature가 immediate observation과 같다.
7. 최소 1.05 s verification window가 지났다.
8. configured announcement idle window 동안 새 announcement가 없다.

Action evidence는 initial announcement poll과 동일 시간대의 non-consuming Helper logcat
side channel을 transaction에 병합한 뒤 읽는다. Helper success만으로 movement, visited,
consumed를 만들지 않는다. 최종 authoritative source는 기존 `ProgressDecision`과
`VisitDecision`이다.

다음 경우 기존 configured deadline과 polling을 그대로 사용한다.

- transaction/request mismatch
- missing, malformed 또는 incomplete Helper evidence
- accessibility focus identity 부족
- delayed observation 누락
- delayed identity 변화, transient landing 또는 snap-back 가능성
- announcement가 계속 들어오는 경우
- action result failure

Fast path와 fallback은 동일 GET_FOCUS/row builder/evidence reducer/visit/stop 경로로
합류한다. 차이는 안전하게 끝낼 수 있는 announcement polling duration뿐이다.

## 3. Snapshot freshness 분석

새 snapshot cache는 구현하지 않았다. GET_FOCUS fallback에서 만들어진 DUMP_TREE를
동일 step의 row에 재사용하는 기존 경로는 이미 존재하며 `fallback_nodes_reused`로
source가 명시된다. 반면 NEXT, CLICK, scroll, FOCUS_IN_BOUNDS, overlay, local-tab 및
screen transition 전체를 포괄하는 mutation generation 계약은 현재 없다.

따라서 action-scoped freshness를 증명하지 못한 XML/focus snapshot을 재사용하면 stale
snapshot이 gate에 들어갈 수 있다. Phase 9.4에서는 기존 fallback reuse만 계측하고,
새 cache와 invalidation counter는 추가하지 않았다.

## 4. Recovery와 stop 불변식

Recovery candidate eligibility/order, hard-failed/canonical duplicate 방지, attempt 수 의미,
FOCUS_IN_BOUNDS success 조건, strong recovery gate, stop policy는 수정하지 않았다.
Recovery verification은 동일 adaptive policy를 사용하되 100/300/1000 ms stable evidence가
없으면 기존 deadline으로 fallback한다.

## 5. Profiler counter

기존 profiler JSON의 `metrics`와 `recovery`는 유지하고 additive `counters`를 추가했다.

- `verification_poll_attempts`
- `verification_fast_path_hits`
- `verification_fallback_count`
- `verification_timeout_count`
- `verification_focus_stable_count`
- `verification_announcement_idle_count`
- `focus_snapshot_read_count`
- `xml_snapshot_read_count`
- `reused_snapshot_count` (기존 GET_FOCUS fallback tree가 재사용될 때만)
- `recovery_verification_fast_path_hits`

새 cache가 없으므로 `invalidated_snapshot_count`는 기록하지 않는다. Profiler OFF이면
counter lookup은 no-op이며 artifact도 만들지 않는다.

## 6. Test 결과

- Phase 9.4 정책/수집/profiler/evidence/orchestration/collection/recovery/identity: 595 passed
- `test_talkback_lib.py` 전체: 139 passed, 8 pre-existing failures
  - 3건: 현재 HEAD의 logcat/version 동작과 오래된 기대값 불일치
  - 5건: 기존 focus-affinity announcement fallback 기대값 불일치
  - Phase 9.4 대상 max-wait/idle tests는 별도 실행에서 통과

기존 assertion은 삭제하거나 완화하지 않았다.

## 7. 실기기 결과

비교 가능한 단독/동일-flow 결과는 다음과 같다.

| Scenario | Baseline | After | 변화 | Fast/Fallback | 의미 결과 |
|---|---:|---:|---:|---:|---|
| Safe | 363.433 s | 336.236 s | -7.5% | 36 / 5 | rows 18, recovery 3/3, reconciliation PASS |
| Motion | 229.461 s | 232.488 s | +1.3% | 11 / 8 | steps 17, stop `confirmed_local_tab_exhaustion`, reconciliation PASS |

Safe after의 주요 inclusive metric은 traversal loop 126.170 s, verification poll
36.581 s, recovery executor 13.668 s였다. 각각 baseline 대비 약 31.6%, 28.2%, 27.7%
감소했다. Motion verification poll은 19.870 s로 baseline과 사실상 같았다.

Safe+Motion 최종 batch는 UI 상태 차이로 Safe overlay가 baseline 1회에서 2회로 늘어
Safe runtime이 429.986 s가 됐다. 이는 동일 work count 비교가 아니므로 성능 개선치로
사용하지 않는다. 해당 batch에서도 Motion steps/stop은 유지되고 reconciliation은 PASS,
orphan 0, duplicate 0, ledger failure 0이었다. 다만 baseline과 달리 추가 Safe overlay
경로의 transaction 1건이 PARTIAL이었다. 비교 가능한 Safe 단독 run(40/40 COMPLETE)과
Motion run(15/15 COMPLETE)에서는 incomplete transaction 증가가 없었다.

목표였던 두 scenario 모두 15% 단축은 달성하지 못했다. Motion은 fast path 절감과
evidence/focus/row 고정 비용이 상쇄됐고, Safe total에는 navigation, overlay, dump/crop,
persistence 등 verification 밖의 비용이 크다.

## 8. 위험과 rollback

주요 위험은 단말/화면 상태에 따른 runtime 분산, delayed event transport 지연, 긴
TalkBack 발화다. 세 delayed snapshot 또는 idle 조건이 만족되지 않으면 fast path가
아니라 기존 deadline으로 돌아간다.

Rollback은 `StepCollectionService`의 adaptive policy 호출을 제거하고 기존 full
announcement wait loop로 복귀하는 것이다. Profiler `counters`는 additive이므로 별도로
rollback하지 않아도 기존 consumer와 호환된다.

## 9. Phase 9.5 후보

- announcement parser가 이미 읽은 logcat buffer와 evidence collector의 read 공유
- action mutation generation의 명시적 계약 수립 후 action-scoped snapshot cache 재평가
- crop/save/navigation 고정 비용의 독립 최적화
- 동일 UI state를 보장하는 반복 benchmark harness와 분산 통계
