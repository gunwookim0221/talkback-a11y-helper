# TalkBack Traversal Engine Evidence Architecture

작성일: 2026-07-11
상태: Architecture specification — no implementation
적용 범위: Runner, Android Helper, Audit V4/V5+, Summary, Coverage Probe, XLSX/QA Frontend export
근거: [Independent Technical Review](talkback-traversal-engine-rca-independent-technical-review.md)

## 1. Evidence Architecture

### 1.1 목적

이 설계의 목적은 traversal 결과를 개선하는 것이 아니라, 다음 질문에 plugin 종류와 무관하게 답할 수 있는 증거 기반을 정의하는 것이다.

- 어떤 action이 언제 시작되고 종료됐는가?
- action 직전과 직후의 physical accessibility focus는 무엇이었는가?
- requested target과 Helper가 실제 action한 resolved target은 같은 node인가?
- Helper가 `moved`를 반환한 시점에 focus event와 focus observation이 이를 지지하는가?
- 이후 overlay, realign, scroll, WebView reset 또는 snap-back이 있었는가?
- representative는 어느 snapshot을 근거로 선택됐으며 actual focus와 어떤 관계인가?
- visit/consumed/audit/export 결정은 어떤 원자적 evidence를 근거로 했는가?
- Summary가 scenario lifecycle의 어느 terminal fact에서 파생됐는가?

이 문서는 Safe의 동작을 정답으로 사용하지 않는다. Safe는 target substitution 예시, Motion은 post-snapshot realign 예시, Family/Energy는 intervening overlay 예시, TV는 반복 focus/stability 예시, Pet Care는 동일 reason·상이 root cause 가능성의 예시일 뿐이다.

### 1.2 핵심 원칙

1. **Step is not a transaction.** 한 step 안에는 SMART_NEXT, focus read, realign, overlay 같은 여러 action transaction이 존재할 수 있다.
2. **Event is immutable fact.** producer가 관측한 사실은 append-only event로 남고 나중 판단이 이전 event를 덮어쓰지 않는다.
3. **Correlation precedes time comparison.** process 간 wall clock보다 `transaction_id`, `attempt_id`, `causation_event_id`를 우선한다.
4. **Observation time is explicit.** 모든 값은 `observed_at`과 `snapshot_id`를 가지며 서로 다른 시점의 값을 같은 state로 취급하지 않는다.
5. **Ack is not focus.** action API 성공, Helper ack, focus commit claim, accessibility event, Runner observation을 별도 fact로 저장한다.
6. **Representative is not focus.** representative는 planning fact이며 physical visit을 증명하지 않는다.
7. **Consumed is not visited.** planning consumption, semantic coverage, direct-focus visit을 분리한다.
8. **Alias is an asserted relation.** container merge나 clickable ancestor 관계는 명시적 evidence와 validity scope가 있어야 한다.
9. **Projection is not source of truth.** XLSX, normal.log, Summary, QA Frontend는 canonical ledger의 파생 projection이다.
10. **Unknown is first-class.** evidence가 불완전하면 PASS/FAIL로 추정하지 않고 `INDETERMINATE`를 유지한다.
11. **No behavior coupling in evidence phase.** evidence 수집 실패가 traversal policy를 바꾸거나 visit을 생성하지 않는다.
12. **Every verdict is traceable.** audit·summary·coverage의 모든 결론은 사용한 `evidence_event_ids`를 가진다.

### 1.3 논리 구조

```text
Run
└─ Scenario Transaction
   ├─ Surface/Entry Transaction
   ├─ Action Transaction: SMART_NEXT
   │  ├─ Pre-focus observation
   │  ├─ Requested/resolved target
   │  ├─ Helper execution and commit claim
   │  ├─ Accessibility events
   │  └─ Post-focus stability window
   ├─ Child Action Transaction: REALIGN
   ├─ Child Action Transaction: OVERLAY_OPEN / OVERLAY_CLOSE
   ├─ Representative Decision Transaction
   ├─ Visit Decision Transaction
   └─ Projection/Audit Transactions
```

Canonical data flow:

```text
Runner facts ─┐
Helper facts ─┼─> Immutable Evidence Ledger ─> Deterministic Reducers
Probe facts ──┘                                  ├─> Audit ledger
Manual facts ────────────────────────────────────┤
                                                  ├─> Summary
                                                  ├─> Coverage
                                                  └─> XLSX / UI
```

## 2. Action Transaction Model

### 2.1 Transaction hierarchy

| Level | Identity | Purpose | Terminal condition |
|---|---|---|---|
| Run | `run_id` | 한 device/build/config 실행 | run completed/aborted |
| Scenario | `scenario_tx_id` | plugin 진입부터 scenario 종료까지 | scenario terminal fact |
| Surface | `surface_id` + `surface_revision` | 동일 window/DOM/viewport 관측 범위 | transition, mutation, scroll revision |
| Action | `transaction_id` | 하나의 외부 효과 또는 판단 단위 | committed/failed/aborted/indeterminate |
| Attempt | `attempt_id` | 동일 logical action의 개별 실행 | attempt ack/timeout/cancel |
| Observation | `observation_id` | 특정 시점의 node/focus snapshot | immutable |

`step_index`는 presentation coordinate로만 유지한다. transaction join key로 사용하지 않는다.

### 2.2 Action type catalog

최소 action vocabulary:

- `SCENARIO_CARD_DISCOVER`
- `SCENARIO_CARD_ACTIVATE`
- `SCREEN_TRANSITION_VERIFY`
- `ANCHOR_SELECT`
- `ANCHOR_VERIFY`
- `SMART_NEXT`, `SMART_PREVIOUS`
- `TARGET_FOCUS`, `TARGET_CLICK`
- `SCROLL_FORWARD`, `SCROLL_BACKWARD`
- `REALIGN_FOCUS`
- `OVERLAY_OPEN`, `OVERLAY_TRAVERSE`, `OVERLAY_CLOSE`
- `LOCAL_TAB_ACTIVATE`
- `REPRESENTATIVE_SELECT`
- `CANDIDATE_CONSUME`
- `VISIT_DECIDE`
- `COVERAGE_PROBE`
- `MANUAL_TALKBACK_MOVE`
- `PERSIST_PROJECT`, `AUDIT_REDUCE`, `SUMMARY_REDUCE`, `EXPORT_PROJECT`

Retry는 action type이 아니다. 동일 `logical_action_id` 아래 새 `attempt_id` 또는 새 child transaction으로 표현한다.

### 2.3 공통 event envelope

모든 producer event는 다음 envelope를 가진다.

```json
{
  "schema_version": "evidence-event-v1",
  "event_id": "evt_...",
  "event_type": "POST_FOCUS_OBSERVED",
  "run_id": "run_...",
  "scenario_tx_id": "stx_...",
  "transaction_id": "tx_...",
  "logical_action_id": "act_...",
  "attempt_id": "att_...",
  "parent_transaction_id": null,
  "causation_event_id": "evt_...",
  "producer": "helper",
  "producer_instance_id": "helper_process_...",
  "producer_sequence": 1842,
  "wall_time_utc": "2026-07-11T01:32:27.890Z",
  "monotonic_time_ns": 1234567890,
  "runner_received_wall_time_utc": null,
  "scenario_id": "home_safe_plugin",
  "plugin_family": "home",
  "step_index": 0,
  "phase": "anchor_verify",
  "surface_id": "surface_...",
  "surface_revision": 3,
  "payload": {},
  "provenance": {}
}
```

Required envelope fields:

- globally unique `event_id`
- `run_id`, `scenario_tx_id`, `transaction_id`
- `producer`, `producer_instance_id`, monotonic `producer_sequence`
- UTC wall time와 producer-local monotonic time
- `event_type`, `schema_version`, `phase`
- `provenance` 또는 provenance manifest reference

Cross-process order는 `transaction_id + producer_sequence + send/receive pair`로 재구성한다. 서로 다른 monotonic clock 숫자를 직접 비교하지 않는다.

### 2.4 필수 action timeline

일반 action transaction은 다음 순서를 사용한다.

| Seq | Event | Producer | 의미 |
|---:|---|---|---|
| 1 | `TRANSACTION_OPENED` | Runner | logical action과 scope 생성 |
| 2 | `PRE_FOCUS_OBSERVED` | Helper/Runner | action 직전 physical focus observation |
| 3 | `TARGET_REQUESTED` | Runner | directional intent 또는 candidate identity |
| 4 | `ACTION_SENT` | Runner | Helper command 전송 |
| 5 | `ACTION_EXECUTION_STARTED` | Helper | Helper가 attempt 실행 시작 |
| 6 | `TARGET_RESOLVED` | Helper | 실제 action node와 requested target 관계 |
| 7 | `ACTION_API_RESULT` | Helper | Android action API true/false; focus 성공과 구분 |
| 8 | `FOCUS_COMMIT_CLAIMED` | Helper | Helper 내부 검증이 commit을 주장 |
| 9 | `ACCESSIBILITY_FOCUS_EVENT` | Helper | 0..N개의 raw focus event |
| 10 | `ANNOUNCEMENT_OBSERVED` | Helper | 0..N개의 announcement |
| 11 | `HELPER_ACK_SENT` / `HELPER_ACK_RECEIVED` | Helper/Runner | transport acknowledgement |
| 12 | `POST_FOCUS_OBSERVED` | Helper/Runner | ack 이후 focus observation series |
| 13 | `FOCUS_STABILITY_WINDOW_CLOSED` | Runner | stable/snap-back/indeterminate 판정용 fact set 종료 |
| 14 | `TRANSACTION_CLOSED` | Runner | action terminal state |

8~12번의 raw 발생 순서는 Android event delivery와 transport scheduling에 따라 교차할 수 있다. 위 표는 필수 causal phase이지 total ordering이 아니다. 실제 순서는 producer sequence와 send/receive event pair를 보존해 재구성한다.

`REPRESENTATIVE_SELECTED`, `REALIGN_*`, `VISIT_DECIDED`, `PERSISTED`, `AUDIT_COMMITTED`, `EXPORTED`는 위 transaction의 필드가 아니라 별도 transaction/event다. 관련성은 parent/causation ID로 연결한다.

### 2.5 필수 event payload

| Event | Required payload |
|---|---|
| `TRANSACTION_OPENED` | action type, logical action ID, scenario/plugin, parent transaction, sequence intent |
| `PRE_FOCUS_OBSERVED` | observation ID, capture start/end time, focus source, snapshot/surface revision, capture status |
| `TARGET_REQUESTED` | request kind, candidate/observation ID 또는 direction, requested action, selection decision ID |
| `TARGET_RESOLVED` | resolved observation ID, requested↔resolved relation, ancestor/path distance, resolution reason/rule version |
| `ACTION_SENT` | command type, attempt ID, destination, payload hash, sender time |
| `ACTION_EXECUTION_STARTED` | received command hash, Helper process sequence, start time |
| `ACTION_API_RESULT` | Android action constant, boolean result, attempted observation ID, error/reason |
| `FOCUS_COMMIT_CLAIMED` | claimed observation ID, verification method, basis event IDs, claim confidence |
| `ACCESSIBILITY_FOCUS_EVENT` | raw event type/action/time, source observation ID, window/package, transaction assignment confidence |
| `ANNOUNCEMENT_OBSERVED` | raw/protected text reference, normalized text, event time, source observation if known, association confidence |
| `HELPER_ACK_*` | tx/attempt ID, transport status, Helper result vocabulary, send/receive time, payload hash |
| `POST_FOCUS_OBSERVED` | observation ID, sample offset, focus source, capture status, intervening transaction IDs |
| `FOCUS_STABILITY_WINDOW_CLOSED` | observation series IDs, duration, intervening actions, stable/snap-back/drift fact, incomplete reason |
| `REPRESENTATIVE_SELECTED` | representative observation/candidate ID, basis snapshot, selection time/reason, relation to final focus |
| `REALIGN_*` | child transaction ID, target, pre/post focus observations, action/landing/stability result |
| `VISIT_DECIDED` | candidate ID, visit kind, focus/alias/announcement evidence IDs, gate results, rule version |
| `PERSIST_PROJECTED` | projection/row ID, field lineage, output destination/hash, write status |
| `AUDIT_COMMITTED` | audit dimension/verdict, input closure/hash, evidence IDs, missing evidence, reducer version |
| `SUMMARY_REDUCED` | lifecycle axes, terminal event, reconciliation results, reducer version |
| `EXPORTED` | projection manifest, schema version, artifact path/hash, row/object counts |

### 2.6 Action 결과 축

단일 `success` boolean을 사용하지 않는다.

| Axis | 값 예시 |
|---|---|
| transport | `ACKED`, `TIMEOUT`, `MALFORMED` |
| action_api | `ACCEPTED`, `REJECTED`, `NOT_ATTEMPTED` |
| target_relation | `EXACT`, `ANCESTOR_ALIAS`, `DESCENDANT_ALIAS`, `UNRELATED`, `INDETERMINATE` |
| focus_commit_claim | `CLAIMED`, `NOT_CLAIMED`, `INDETERMINATE` |
| physical_focus_delta | `CHANGED`, `UNCHANGED`, `LOST`, `INDETERMINATE` |
| target_landing | `EXACT`, `ALIAS_CONFIRMED`, `OTHER_NODE`, `NO_FOCUS`, `INDETERMINATE` |
| stability | `STABLE`, `SNAP_BACK`, `DRIFTED`, `WINDOW_INCOMPLETE` |
| announcement | `MATCHED`, `DIFFERENT`, `ABSENT`, `INDETERMINATE` |

이 축을 조합해야만 `MOVE_CONFIRMED`, `MOVE_CLAIMED_BUT_UNVERIFIED`, `MOVE_TO_OTHER_NODE`, `STATIC_FOCUS`, `SNAP_BACK` 같은 파생 verdict를 만든다.

### 2.7 Safe와 Motion의 재구성 예

Safe anchor transaction:

```text
TARGET_REQUESTED: title "세이프 버튼"
TARGET_RESOLVED: full-screen primary, relation=ANCESTOR_UNVERIFIED
ACTION_API_RESULT: ACCEPTED
POST_FOCUS_OBSERVED: primary
TARGET_LANDING: OTHER_NODE or UNCONFIRMED_ALIAS
ANCHOR_VERIFY: mismatch
SCENARIO_TERMINAL: ANCHOR_ABORT
```

이 timeline은 Safe target substitution을 증명하지만 다른 plugin의 common engine defect를 자동 결론 내리지 않는다.

Motion step 8:

```text
Parent SMART_NEXT transaction
  POST_FOCUS_OBSERVED: header
Child REALIGN_FOCUS transaction
  TARGET_REQUESTED: 100%
  POST_FOCUS_OBSERVED: 100%
Representative decision
  REPRESENTATIVE_SELECTED: 100%, based_on=post-realign observation
```

따라서 earlier header와 later `100%`를 같은 시점의 mismatch로 세지 않는다.

## 3. Evidence Ledger Specification

### 3.1 Canonical ledger entities

| Entity | Purpose | Canonical key |
|---|---|---|
| `run_manifest` | build/config/device provenance | `run_id` |
| `scenario_ledger` | scenario lifecycle facts | `scenario_tx_id` |
| `surface_ledger` | window/DOM/viewport revision | `surface_id`, `surface_revision` |
| `action_event` | immutable action timeline | `event_id` |
| `node_observation` | 특정 snapshot의 node fact | `observation_id` |
| `identity_assertion` | cross-snapshot same/alias/different 주장 | `assertion_id` |
| `candidate_ledger` | discovery부터 terminal coverage까지 | `candidate_id` |
| `decision_ledger` | representative/consume/visit/audit 결정 | `decision_id` |
| `projection_manifest` | XLSX/summary/UI 생성 근거 | `projection_id` |

### 3.2 Node observation payload

모든 focus/target/representative node는 문자열 label 대신 `observation_id`를 참조한다. observation에는 다음을 저장한다.

- physical identity components
- semantic components
- complete bounds와 coordinate space
- node path와 path source
- accessibility state flags
- window/display/package
- source snapshot ID, surface revision, capture timestamp
- raw value와 normalized value를 분리한 text/content description
- parent/children observation references when available
- redaction classification

### 3.3 Decision event payload

`REPRESENTATIVE_SELECTED`:

- `representative_observation_id`
- `candidate_id`
- `based_on_snapshot_id`
- `selection_timestamp`
- `selection_reason`, rank, candidate set revision
- current focus observation reference
- identity relation to current focus
- whether realign is required, attempted, completed

`CANDIDATE_CONSUMED`:

- `candidate_id`
- `consumption_basis`: `PLANNING_ONLY`, `DIRECT_FOCUS`, `ALIAS_FOCUS`, `SEMANTIC_EXPOSURE`, `POLICY_SKIP`
- supporting event IDs
- reversible/terminal scope
- must not imply visit

`VISIT_DECIDED`:

- `candidate_id`
- `visit_kind`: `DIRECT_PHYSICAL_FOCUS`, `CONFIRMED_ALIAS_FOCUS`, `SEMANTIC_ANNOUNCEMENT_ONLY`, `VISIBLE_ONLY`, `NOT_VISITED`, `INDETERMINATE`
- `focus_observation_id`
- identity/alias assertion ID
- announcement event IDs
- stability evidence IDs
- rule version and decision confidence

### 3.4 Persistence and audit evidence

`PERSIST_PROJECTED`는 row 값 전체를 canonical fact로 복제하지 않는다. 다음을 저장한다.

- projection ID, row ID, sheet/log destination
- included event/decision IDs
- projected field → source event mapping
- projection schema/rule version
- output hash and write status

`AUDIT_COMMITTED`:

- candidate/scenario/run scope
- audit dimension
- verdict and confidence
- exact input event IDs
- reducer/rule version
- missing evidence list
- superseded audit decision reference when re-evaluated

### 3.5 Ledger invariants

- event IDs are immutable and idempotent.
- every action terminal event references its opening event.
- every focus verdict references at least one pre- and one post-observation or is `INDETERMINATE`.
- every cross-snapshot identity match is an `identity_assertion`; it is never silently inferred in a row.
- every representative references the snapshot from which it was selected.
- every direct visit references a focus observation and completed stability window.
- every alias visit references an explicit alias assertion.
- consumed cannot satisfy direct-focus coverage.
- export cannot create visit evidence.
- audit cannot upgrade missing evidence to PASS.

## 4. Canonical Identity Specification

### 4.1 하나의 identity 문자열을 사용하지 않는다

Canonical Identity는 네 층으로 분리한다.

1. `Observation Identity`: 한 snapshot 안에서 node를 유일하게 식별
2. `Physical Node Identity`: focus가 놓인 물리/virtual accessibility node 비교
3. `Cross-snapshot Entity Link`: surface revision 간 동일 entity 주장
4. `Semantic/Alias Identity`: 의미 또는 container 관계; physical equality와 별개

### 4.2 구성 요소 분류

| 요소 | 분류 | 용도 | 제한 |
|---|---|---|---|
| package | **필수** | app/process scope | package 변화 시 physical same 금지 |
| window id | **필수 또는 명시적 unavailable** | focus window scope | window 재생성 시 cross-link 필요 |
| class | **필수** | node type discriminator | WebView virtual node에서 변할 수 있음 |
| full bounds | **필수 observation fact** | snapshot 내 위치/크기 | scroll/layout 변화에 불안정, 단독 same 금지 |
| coordinate space/display id | **필수** | bounds 해석 | 누락 시 bounds match는 indeterminate |
| snapshot id/surface revision | **필수** | 시간·화면 scope | 없으면 cross-time 비교 금지 |
| resource-id | **선택, high-weight** | stable discriminator | WebView에서 없거나 중복 가능 |
| node path | **선택, high-weight** | no-id virtual node discriminator | DOM mutation/merge에 불안정 |
| accessibility node unique id | **선택, ephemeral** | 같은 window lifecycle 내 강한 signal | cross-window/run stable key 금지 |
| parent/child index | **선택, unstable** | path 보조 | 단독 identity 금지 |
| content description | **선택 semantic** | announcement/role | 동일 text node 다수 가능 |
| text | **선택 semantic** | label comparison | physical identity 구성의 단독 근거 금지 |
| semantic role/state | **선택 semantic** | button/value/tab 의미 | framework inference일 수 있음 |
| alias group | **선택 asserted relation** | merge/ancestor 관계 | 자동 equality가 아님 |

### 4.3 Observation ID

`observation_id`는 다음 scope에서만 유일하면 된다.

```text
oid:v1:<run_id>:<surface_revision>:<snapshot_id>:<node_ordinal_or_hash>
```

hash 입력에는 raw PII text를 넣지 않는다. ID는 evidence lookup key이지 cross-time same-node claim이 아니다.

Identity comparison priority:

1. 동일 `observation_id`
2. 동일 active window lifecycle의 accessibility unique node ID
3. package + window + class + resource-id + compatible node path
4. resource-id가 없을 때 package + window + class + node path + compatible full bounds/parent signature
5. explicit alias assertion
6. semantic role/text/content description relation

1~4는 physical/entity comparison, 5는 alias comparison, 6은 semantic comparison이다. 낮은 단계가 높은 단계의 충돌을 덮을 수 없다. node path, bounds, accessibility unique ID는 각각 불안정하므로 snapshot/surface/window scope 없이 global key로 사용하지 않는다.

### 4.4 Physical match levels

| Match level | 요구 evidence | 허용 용도 |
|---|---|---|
| `EXACT_OBSERVATION` | 동일 observation ID | 동일 snapshot fact |
| `EXACT_PHYSICAL` | 동일 active window lifecycle + node unique id 또는 완전한 stable tuple | pre/post focus delta |
| `STRONG_ENTITY_LINK` | package/window/class + resource-id/path + compatible geometry | cross-snapshot same candidate |
| `ALIAS_CONFIRMED` | explicit alias assertion + validity scope | container/ancestor visit relation |
| `SEMANTIC_ONLY` | text/description/role only | semantic coverage, physical visit 금지 |
| `DIFFERENT` | contradictory strong fields | mismatch |
| `INDETERMINATE` | evidence 부족/충돌 | 결론 유보 |

Bounds tolerance는 coordinate transform과 surface revision을 먼저 확인한 후 geometry compatibility에만 사용한다. text equality는 `STRONG_ENTITY_LINK`를 만들 수 없다.

### 4.5 Alias model

Alias type:

- `CLICKABLE_ANCESTOR`
- `FOCUSABLE_DESCENDANT`
- `TALKBACK_CONTAINER_MERGE`
- `WEBVIEW_VIRTUAL_REPLACEMENT`
- `SCROLL_RELOCATION`
- `STICKY_HEADER_DUPLICATE`
- `SEMANTIC_EQUIVALENT_ONLY`

Alias assertion required fields:

- source and target observation/candidate IDs
- alias type and direction
- supporting tree/event evidence
- validity surface/window/time range
- confidence
- producer and rule version
- `allows_direct_visit_credit` boolean, default false

`TALKBACK_CONTAINER_MERGE`는 container에 direct-focus credit을 주고 leaf에는 `SEMANTIC_ANNOUNCEMENT_ONLY` credit을 줄 수 있지만, leaf direct-focus visit을 자동 생성하지 않는다.

## 5. Traversal State Machine

### 5.1 공식 transaction state

```text
DISCOVERED
  -> TARGET_SELECTED
  -> ACTION_SENT
  -> HELPER_ACKED
  -> FOCUS_COMMIT_CLAIMED
  -> FOCUS_CONFIRMED
  -> FOCUS_STABLE
  -> ANNOUNCEMENT_EVALUATED
  -> REPRESENTATIVE_SELECTED
  -> VISIT_DECIDED
  -> PERSISTED
  -> AUDIT_COMMITTED
  -> EXPORTED
```

모든 상태에서 `FAILED`, `ABORTED`, `INDETERMINATE` terminal branch가 가능하다. `FOCUS_COMMIT_CLAIMED`는 Helper 주장 상태이며 `FOCUS_CONFIRMED`와 동일하지 않다.

### 5.2 상태 계약

| State | Entry | Exit invariant | Failure/Abort | Retry/Rollback |
|---|---|---|---|---|
| `DISCOVERED` | candidate observation 생성 | candidate ID와 discovery snapshot 존재 | missing/invalid snapshot | 새 surface revision에서 재발견; 기존 event 유지 |
| `TARGET_SELECTED` | selection decision + candidate set revision | requested target observation/candidate 명시 | no candidate, policy exclusion | 새 decision transaction; 이전 선택 superseded |
| `ACTION_SENT` | pre-focus와 target request 완료 | attempt ID와 send event 존재 | transport send failure | 새 attempt ID; in-place overwrite 금지 |
| `HELPER_ACKED` | matching ack 수신 | ack가 동일 tx/attempt와 join | timeout, malformed, wrong tx | late ack는 별도 event; terminal 재작성 금지 |
| `FOCUS_COMMIT_CLAIMED` | Helper 내부 commit claim | claim basis observation/event 존재 | no claim or conflicting claim | 새 observation/attempt 가능 |
| `FOCUS_CONFIRMED` | post-focus observation + identity relation | target landing과 physical delta 판정 가능 | other/no focus/indeterminate | realign은 child transaction; parent history 보존 |
| `FOCUS_STABLE` | stability window complete | stable/snap-back/drift/window-incomplete 중 하나 | interruption/window incomplete | 새 stability observation series; prior series 유지 |
| `ANNOUNCEMENT_EVALUATED` | announcement window closed | match/different/absent/indeterminate | capture unavailable | later event는 새 evaluation revision |
| `REPRESENTATIVE_SELECTED` | candidate set + basis snapshot | representative와 current/final focus 관계 명시 | stale snapshot, no representative | 새 decision; physical state 변경 금지 |
| `VISIT_DECIDED` | required focus/alias/stability evidence | visit kind와 supporting event IDs 존재 | evidence gate fail | `INDETERMINATE`; audit가 임의 승격 금지 |
| `PERSISTED` | canonical decision complete | projection field lineage와 hash 존재 | partial write | compensating projection event; canonical ledger 불변 |
| `AUDIT_COMMITTED` | audit reducer input closure | verdict, rule version, evidence IDs, missing list | incomplete ledger | `INDETERMINATE` 또는 `DATA_INCOMPLETE` |
| `EXPORTED` | projection success | export manifest/hash/revision 존재 | export failure | 새 projection revision; visit fact 불변 |

### 5.3 Retry, rollback, abort semantics

- Retry는 동일 event를 수정하지 않고 새 attempt 또는 child transaction을 만든다.
- Rollback은 `COMPENSATION_STARTED/COMPLETED/FAILED` event로 표현한다.
- Overlay close와 focus recovery는 rollback이 아니라 별도 action transaction이다.
- Abort는 `abort_stage`, `abort_reason_code`, `last_completed_state`, `trigger_event_id`를 필수로 가진다.
- `CARD_NOT_FOUND`, `CARD_ACTIVATION_FAILED`, `SCREEN_TRANSITION_FAILED`, `ANCHOR_ABORT`, `TRAVERSAL_ABORT`, `ENVIRONMENT_ABORT`, `EVIDENCE_INCOMPLETE`는 서로 다른 terminal reason이다.
- state는 단조 증가한다. card activated와 screen transition evidence가 있으면 later aggregation이 `CARD_NOT_FOUND`로 회귀할 수 없다.

## 6. Evidence Gate

각 gate는 `PASS`, `FAIL`, `INDETERMINATE`, `NOT_APPLICABLE` 중 하나를 출력하고 evidence IDs를 보존한다.

| Gate | 질문 | 필수 evidence | FAIL 의미 |
|---|---|---|---|
| G0 Provenance | 실행 코드와 artifact를 연결할 수 있는가 | Runner SHA, Helper APK hash/build SHA, config hash, app/WebView/device versions | code attribution 금지 |
| G1 Temporal Completeness | action 경계를 재구성할 수 있는가 | tx/attempt IDs, send/receive pair, producer sequence, pre/post observations | movement 판정 금지 |
| G2 Physical Movement | focus가 실제 변했는가 | pre/post physical identity + focus event stream | static/lost/other focus |
| G3 Target Resolution | requested와 resolved target 관계는 무엇인가 | both observations + path/alias assertion | target substitution/unrelated |
| G4 Stability/Snap-back | commit 이후 focus가 유지됐는가 | bounded observation series와 intervening action list | snap-back/drift |
| G5 Realign | realign이 final focus를 바꿨는가 | child tx pre/target/post/stability | realign fail/indeterminate |
| G6 Representative Coherence | representative가 어떤 snapshot과 focus를 기준으로 했는가 | basis snapshot, selection time, final focus relation | stale/mixed-phase decision |
| G7 Container Merge | leaf miss가 정상 merge인가 | tree relation, announcement tokens, manual/runtime focus evidence, alias assertion | unproven merge |
| G8 Intervening Action | endpoint 사이 action이 있었는가 | child/peer transaction list | endpoint comparison invalid |
| G9 Manual TalkBack | native TalkBack도 동일 surface에서 도달 가능한가 | manual tx, screen recording reference, focus event stream | obligation 재평가 필요 |
| G10 Visit Commit | visit credit이 물리/alias/semantic 중 무엇인가 | visit decision and supporting gates | false visit/unknown |
| G11 Audit Reproducibility | audit verdict를 다시 계산할 수 있는가 | input closure, reducer version, hashes | audit non-reproducible |
| G12 Aggregation Consistency | summary가 lifecycle facts와 일치하는가 | scenario state reduction + reconciliation checks | summary blocked |

### 6.1 Root-cause 확정 규칙

- `FOCUS_MOVE_MISMATCH`는 G1/G2/G4/G8이 모두 PASS일 때만 확정한다.
- `ANCHOR_TARGET_SUBSTITUTION`은 G1/G3이 PASS이고 relation이 unrelated 또는 unapproved ancestor일 때 확정한다.
- `REPRESENTATIVE_ACTUAL_DIVERGENCE`는 같은 `basis_snapshot_id` 또는 explicit final observation 기준일 때만 계산한다.
- `DISCOVERED_NOT_VISITED`는 G7/G9를 통해 direct-focus obligation이 확인된 candidate에만 strong verdict를 준다.
- `COMMON_*` verdict는 최소 두 plugin family에서 동일 gate failure와 동일 causal event pattern이 확인돼야 한다. reason string 일치만으로는 부족하다.

## 7. Observability Architecture

### 7.1 Source of Truth 책임

Global Source of Truth는 **Immutable Evidence Ledger**다. 각 component는 자기 관측 영역의 authoritative producer이지 전체 verdict의 owner가 아니다.

| Component | Authoritative facts | 사용 금지 |
|---|---|---|
| Runner | orchestration intent, transaction lifecycle, send/receive, candidate/representative decisions, child action graph | Helper focus success 추정 |
| Helper | Android action API result, resolved node, accessibility events, local focus observations, commit claim | scenario PASS/visit 판정 |
| Audit | immutable facts에 대한 versioned derived verdict | log label만으로 physical visit 생성 |
| Summary | scenario/run reducer의 projection | earlier stage reason으로 later stage failure 덮어쓰기 |
| Coverage Probe | 독립 probe transaction facts | legacy traversal row를 무근거 대체 |
| XLSX/QA Frontend | human-readable projection | canonical identity 또는 ledger 수정 |
| Manual Test | independently sourced focus/event evidence | 자동 event처럼 출처 숨기기 |

### 7.2 Canonical, duplicated, derived data

| Data class | 예 | 정책 |
|---|---|---|
| Canonical event | action sent, focus event, post observation | ledger에 한 번 저장, immutable |
| Canonical assertion | identity link, alias relation | 별도 versioned assertion |
| Derived decision | movement verdict, visit kind, audit root cause | rule version과 input event IDs 필수 |
| Projection duplicate | normal.log line, XLSX row, UI card | projection manifest로 canonical source 추적 |
| Diagnostic cache | candidate index, normalized label | 재생성 가능; Source of Truth 아님 |

Raw log와 JSON event를 이중 저장할 수 있지만 raw log는 forensic copy, structured ledger가 machine aggregation source다. 두 값이 다르면 reconciliation error를 발생시키며 한쪽을 조용히 우선하지 않는다.

### 7.3 Focus event stream

Focus event는 transaction마다 다음 window로 capture한다.

- pre-action observation
- action execution start부터 Helper ack까지의 raw events
- ack 이후 stability window events
- child realign/overlay가 시작되면 parent window 종료 후 child window 시작

각 focus event는 source node observation, Android event time, Helper receive time, transaction assignment confidence를 가진다. transaction 경계에 걸쳐 귀속이 불명확하면 `UNASSIGNED_FOCUS_EVENT`로 남기고 임의 연결하지 않는다.

### 7.4 Build provenance

Run manifest required fields:

- repository commit SHA와 dirty flag
- Runner source/build hash
- Helper APK SHA-256, versionName/versionCode, source commit when available
- schema/reducer versions
- runtime config hash와 scenario registry hash
- target app version, Android build, TalkBack version, WebView version
- device/display/locale/accessibility settings
- artifact manifest with path, size, hash, generation status

G0가 실패하면 behavioral evidence는 사용할 수 있지만 특정 code line/commit 귀속은 금지한다.

## 8. Aggregation Architecture

### 8.1 Scenario 결과는 단일 status가 아니라 직교 축이다

| Axis | 값 예시 |
|---|---|
| discovery | `CARD_FOUND`, `CARD_NOT_FOUND`, `NOT_RUN`, `INDETERMINATE` |
| activation | `ACTIVATED`, `FAILED`, `NOT_APPLICABLE` |
| transition | `NEW_SURFACE_CONFIRMED`, `SAME_SURFACE`, `FAILED` |
| anchor | `CONFIRMED`, `FAILED`, `ABORTED`, `NOT_REQUIRED` |
| traversal | `COMPLETED`, `STOPPED`, `ABORTED_BEFORE_START`, `NOT_RUN` |
| evidence | `COMPLETE`, `PARTIAL`, `CORRUPT` |
| audit | `PASS`, `REVIEW`, `FAIL`, `INDETERMINATE`, `NOT_RUN` |
| coverage | `COMPLETE`, `PARTIAL`, `ZERO_ELIGIBLE`, `NOT_COLLECTED`, `INDETERMINATE` |
| environment | `OK`, `INTERRUPTED`, `UNAVAILABLE` |

UI가 단일 headline을 요구하면 이 tuple에서 deterministic rule로 파생하되 전체 축과 source event를 함께 보존한다.

### 8.2 Monotonic lifecycle reduction

Scenario stage:

```text
DISCOVERY_STARTED
< CARD_FOUND
< CARD_ACTIVATED
< SCREEN_TRANSITION_CONFIRMED
< ANCHOR_EVALUATED
< TRAVERSAL_STARTED
< TRAVERSAL_TERMINATED
< AUDIT_TERMINATED
< EXPORTED
```

Reducer는 later-stage evidence가 존재할 때 earlier-stage negative reason을 최종 원인으로 선택할 수 없다.

Safe 예시 invariant:

- `CARD_FOUND`, `CARD_ACTIVATED`, `SCREEN_TRANSITION_CONFIRMED`가 존재한다.
- 따라서 final discovery는 `CARD_FOUND`다.
- terminal failure는 `ANCHOR_ABORT`다.
- `optional Safe card not found`는 reconciliation violation이며 summary publish를 차단한다.

### 8.3 Zero와 missing 분리

모든 count aggregate는 다음 상태를 별도 저장한다.

- `ZERO_VALID`: 실행했고 결과가 0
- `NOT_RUN`: 실행하지 않음
- `ABORTED_BEFORE_COLLECTION`
- `NO_ELIGIBLE_CANDIDATE`
- `SOURCE_MISSING`
- `SOURCE_CORRUPT`
- `FILTERED_BY_POLICY`

따라서 Probe candidate 0과 pre-start abort inventory 0은 같은 숫자여도 같은 의미가 아니다.

### 8.4 Aggregation lineage

모든 aggregate field는 다음 metadata를 가진다.

- numerator event IDs/query
- denominator event IDs/query
- reducer version
- input manifest hash
- excluded count와 reason buckets
- incomplete transaction count
- generated timestamp and projection ID

Cross-plugin visit rate는 동일 candidate obligation과 동일 visit kind를 분모/분자로 사용할 때만 생성한다. XML readable count와 canonical candidate count, direct physical visit count를 단순 나눗셈으로 혼합하지 않는다.

### 8.5 Reconciliation checks

- transaction opened = terminal + explicitly open/incomplete
- action sent attempt에는 ack/timeout/cancel 중 하나 존재
- direct visit에는 focus-confirmed evidence 존재
- alias visit에는 alias assertion 존재
- persisted row의 모든 semantic field에 source mapping 존재
- scenario terminal stage가 summary reason stage와 일치
- aggregate candidate total = eligible + ineligible + indeterminate
- audit input hash가 artifact manifest와 일치
- export row count가 projection manifest와 일치

Violation은 `AGGREGATION_INCONSISTENT` 또는 `DATA_INCOMPLETE`이며 PASS로 축약하지 않는다.

## 9. Cross-plugin Applicability

| Surface pattern | 대표 plugin | Evidence Architecture 적용점 |
|---|---|---|
| WebView title/body/CTA | Safe, Food, Pet Care | virtual node path, ancestor alias, container merge, DOM revision |
| Capability cards | Motion, Smoke, Water Leak, Air Care | header/value/container alias와 realign child tx |
| Repeated values/modes | TV | same text/different node, snap-back/stability window |
| Overlay/menu | Energy, Family, Safe | intervening child tx와 endpoint comparison gate |
| Local tabs/bottom strip | Food, device plugins | tab activation transaction과 content traversal 분리 |
| Optional/empty state | Home Care, Safe | discovery obligation과 taxonomy/probe-zero reason 분리 |

Plugin-specific regex나 special-case field는 canonical event schema에 들어가지 않는다. Plugin 차이는 action/candidate metadata와 policy version으로만 표현한다.

## 10. Architecture Risk Analysis

| Risk | 영향 | Architecture control |
|---|---|---|
| instrumentation이 focus timing에 영향 | 관측이 현상을 바꿈 | producer-local lightweight event, timing overhead metric, capture mode 비교 |
| event volume 증가 | storage/performance | bounded raw payload, manifest retention tier, structured event 우선 |
| process clock skew | 잘못된 순서 | tx correlation, send/receive pair, producer sequence; wall clock 단독 정렬 금지 |
| WebView node path 불안정 | false same/different | surface revision과 explicit cross-snapshot assertion |
| bounds 변화/scroll | identity fragmentation | coordinate space와 geometry compatibility, bounds 단독 equality 금지 |
| alias over-credit | leaf false visited | alias type별 visit-credit policy, default false |
| semantic text PII | 개인정보 노출 | raw protected field와 redacted/normalized field 분리, ID hash에서 raw text 제외 |
| partial ledger write | false summary | append status, transaction completeness, publish reconciliation gate |
| duplicate events | double count | idempotent event ID와 producer sequence |
| schema evolution | old/new run 비교 오류 | versioned envelope, reducer compatibility matrix, no silent coercion |
| legacy artifact mismatch | historical trend 단절 | legacy projection은 `evidence_quality=legacy_non_atomic`로 명시 |
| manual TalkBack 주관성 | 잘못된 obligation | manual source label, recording/event correlation, independent confidence |
| Audit circularity | output이 input을 증명 | export/summary를 physical fact source로 사용 금지 |
| single headline pressure | stage 오분류 | orthogonal result axes와 reconciliation failure 노출 |

## 11. Implementation Prerequisites

Phase 3 시작 전에 architecture artifact로 확정되어야 하는 항목:

1. `evidence-event-v1` envelope와 event vocabulary freeze
2. transaction/action type catalog와 parent/child rules
3. physical, semantic, alias identity glossary와 match-level truth table
4. producer responsibility matrix와 clock/correlation contract
5. scenario lifecycle와 terminal reason taxonomy
6. visit-kind 및 coverage-dimension 정의
7. reducer/aggregation lineage schema
8. run/build provenance manifest schema
9. PII/redaction/retention policy
10. partial-write, late-event, duplicate-event 처리 규칙
11. legacy artifact compatibility label과 migration boundary
12. plugin-independent evidence corpus 선정

Required validation corpus는 최소 다음 패턴을 포함해야 한다.

- Safe target substitution
- Motion post-snapshot realign
- Energy/Family intervening overlay
- TV same-label repeated nodes와 stability
- Pet Care anchor abort
- Food local-tab/WebView container
- Home Care no-candidate/optional state
- native device plugin의 resource-id stable node

Architecture acceptance criteria:

- 한 transaction을 raw events만으로 deterministic하게 재구성 가능
- 같은 ledger를 두 번 reduce했을 때 byte-equivalent verdict 생성
- actual/representative comparison이 동일 snapshot 또는 explicit temporal relation 없이 생성되지 않음
- overlay/realign이 parent action의 숨은 field로 소실되지 않음
- direct visit과 semantic/alias coverage가 별도 집계됨
- scenario summary가 Safe anchor abort를 card-not-found로 표현할 수 없음
- evidence incomplete run이 PASS로 승격되지 않음

## 12. Can Phase 3 (Implementation) Start?

### Verdict: YES WITH LIMITATIONS

Evidence Architecture 자체의 구현은 시작할 수 있다. Missing evidence는 이 instrumentation을 통해서만 수집 가능하므로, evidence layer 구현까지 추가 runtime 증거를 선행조건으로 요구하면 순환 의존이 생긴다.

허용 범위:

- append-only event envelope와 transaction correlation
- Runner/Helper fact emission
- canonical node observation과 explicit identity assertion
- immutable ledger와 read-only deterministic reducer
- shadow audit/summary projection
- build provenance와 reconciliation report

금지 범위:

- traversal selection/stop/realign 동작 변경
- Helper movement success 의미 변경
- identity 결과를 visited/consumed policy에 즉시 적용
- 기존 Audit/coverage verdict 교체
- 기존 Summary를 검증 전 새 reducer 결과로 대체
- Safe 또는 특정 plugin workaround

Behavioral implementation을 시작하기 전에 추가되어야 할 evidence:

1. Motion/TV static-focus 의심 transaction의 atomic pre/post/event/stability ledger
2. representative 선택 전 observation과 realign 후 final observation의 분리 증거
3. Safe와 Pet Care 각각의 requested/resolved/post-focus target chain
4. manual TalkBack 기준 container/leaf direct-focus obligation evidence
5. Runner SHA와 Helper APK/source provenance가 결합된 반복 run
6. V5를 frozen ledger에 실행한 reproducible visit/audit result
7. Safe anchor abort, true card absence, activation failure를 구분하는 aggregation reconciliation 결과
8. 최소 두 plugin family에서 동일 gate failure가 재현된 경우에만 common defect evidence

따라서 Phase 3는 **evidence-only, shadow, non-behavioral implementation**으로 제한해 시작할 수 있다. Traversal/Helper/Audit/Summary의 production semantics 변경은 위 evidence가 확보되고 Independent Review의 미확정 항목이 gate를 통과할 때까지 시작할 수 없다.

## 13. Deliverable Mapping

| Requested deliverable | Section |
|---|---|
| Evidence Architecture | 1 |
| Transaction Model | 2 |
| Evidence Ledger Specification | 3 |
| Canonical Identity Specification | 4 |
| Traversal State Machine | 5 |
| Evidence Gate | 6 |
| Observability Architecture | 7 |
| Aggregation Architecture | 8 |
| Architecture Risk Analysis | 10 |
| Implementation Prerequisites | 11–12 |
