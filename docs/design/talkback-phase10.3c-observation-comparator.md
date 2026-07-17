# TalkBack Phase 10.3C — Observation Comparator

상태: **Implemented**

기준일: 2026-07-17

범위: observation artifact adapter, canonical normalization, deterministic Tier 1–3
node matching, text/speech delta, common-cohort coverage, reviewed limitation binding,
node-level accessibility failure classification

## 1. Scope

Phase 10.3C는 Phase 10.3B의 read-only aggregate comparison 결과에 node-level 결과를
additive하게 연결한다. Baseline/Candidate를 수정하지 않고 Evidence, XLSX, Coverage,
Inventory와 reviewed limitation snapshot에서 관찰을 복원한다.

포함 모듈:

- `observation_schema.py`
- `observation_adapter.py`
- `observation_normalizer.py`
- `node_matcher.py`
- `text_speech_comparator.py`
- `coverage_transition_comparator.py`
- `limitation_matcher.py`
- `observation_comparator.py`

final overall verdict, 자동 승인, limitation 등록, repository/CAS mutation, CLI, Frontend,
report writer, LLM/ML matching과 실기기 실행은 범위 밖이다.

## 2. Observation Availability

읽기 우선순위와 신뢰도는 다음과 같다.

1. digest가 검증된 pinned Evidence Manifest/CAS payload
2. digest가 검증된 logical `qa-run://` Evidence JSONL
3. digest가 검증된 XLSX `raw`/`result`
4. Focusable Coverage
5. Focusable Inventory
6. Run Summary
7. reviewed limitation snapshot

Profiler는 observation source가 아니다. Evidence는 transaction, request, node snapshot,
announcement와 identity/progress/visit/recovery verdict를 제공한다. XLSX는 row와 최종
quality mismatch/raw result를 제공한다. 두 자료가 모두 검증되고 실제 row가 있으면
`COMPLETE`, 일부만 복원되면 `PARTIAL`이다.

지원 상태는 `COMPLETE`, `PARTIAL`, `UNAVAILABLE`, `CORRUPT`,
`UNSUPPORTED_SCHEMA`이다. 양쪽 상태가 다르거나 양쪽 모두 `COMPLETE`가 아니면 full
node comparison을 수행하지 않고 `DATA_UNAVAILABLE`을 반환한다. 한쪽 자료로 다른 쪽
관찰을 합성하지 않는다.

canonical output에는 절대 경로를 넣지 않는다. 공개 provenance는 logical URI, SHA-256
digest, schema version, row/transaction locator와 resolution 종류만 보존한다.

## 3. Canonical Observation Model

`talkback-canonical-observation-v1`은 다음 축을 갖는다.

- Identity: scenario, step, transaction, request, deterministic observation ID,
  action, terminal
- Node: package, resource ID, class/role, bounds/relative region, accessibility focus,
  focusable/clickable/enabled/selected/checked/scrollable, parent/ancestor/sibling
- Text/Speech: visible text, contentDescription, hint, stateDescription, TalkBack
  speech, announcement, locale, normalized tokens, dynamic markers
- Verdict: mismatch/raw result, identity/progress/visit verdict, stop/recovery result,
  duplicate source step
- Provenance: artifact type, digest, logical reference, schema, row/record locator

observation ID에는 source ID나 로컬 경로를 넣지 않는다. scenario, step, transaction,
resource/class/bounds, normalized text/speech와 stable row locator를 canonical hash한다.
같은 source artifact에서 반복된 동일-looking row도 row locator로 구분된다.

## 4. Normalization

정규화는 deterministic하며 locale 안에서만 사용한다.

- Unicode NFC
- CRLF/CR/LF 및 whitespace 축약
- casefold
- Unicode punctuation을 공백으로 정규화
- 연속 중복 speech segment 축약과 duplicate marker
- 영어/한국어 role suffix(`button`, `버튼` 등) 분리
- percent, time, date, masked identifier, number, configured device name placeholder
- percentage/battery value, count badge 등 숫자성 값의 marker

동적 값은 삭제하지 않는다. `<PERCENT>`, `<TIME>`, `<DATE>`, `<NUMBER>`,
`<DEVICE_NAME>`, `<MASKED_ID>` placeholder와 raw value SHA-256 digest를 남긴다.
따라서 값만 바뀐 경우를 구조적으로 설명할 수 있지만 원문 동적 식별자를 output에
재노출하지 않는다. `en-US`와 `ko-KR` normalization 결과를 직접 동치로 간주하지 않는다.

## 5. Node Matching Tiers

Matcher는 scenario 경계를 넘지 않는다.

### Tier 1 — Stable Exact Identity

resource ID exact, class/role compatible, stable semantic identity를 요구한다. duplicate
resource ID는 observation ID, transaction, request, step, bounds, parent/sibling 증거로
해소한다. bounds 단독으로는 Tier 1이 될 수 없다.

### Tier 2 — Semantic Structure

normalized semantic text/contentDescription, compatible class/role, ancestor signature,
relative region과 focusability의 독립 증거를 점수화한다. label 하나만으로 확정하지 않는다.

### Tier 3 — Traversal Neighborhood

scenario-local step 거리, speech/text pair, sibling neighborhood와 action context를 사용한다.
낮은 confidence이며 review 대상이다. traversal reorder와 step shift를 허용하되 동일
scenario와 복수 독립 증거가 필요하다.

Tier 1–3에 들지 않으면 Tier 4 의미의 added/removed unmatched로 남긴다.

## 6. Matching Safety

각 match는 `match_type`, confidence, supporting/conflicting evidence, ambiguity,
rejected alternatives를 반환한다.

- duplicate resource ID/repeated row: transaction/request/row locator로 먼저 분리
- same label/different control: 동률이면 강제 선택하지 않음
- container/child, split/merge: one-to-many/many-to-one semantic cohort로 별도 표시
- transient/zero bounds/off-screen: bounds를 identity 단독 증거로 쓰지 않음
- reorder/step shift: Tier 3 또는 changed order
- WebView root/child: class/ancestor/neighborhood의 충돌을 보존
- dynamic list item: placeholder semantic과 구조 증거를 함께 요구

동률, many-to-one 충돌 또는 동등 후보가 남으면 `AMBIGUOUS_MATCH`이다. fuzzy similarity,
plugin-name hardcoding, LLM/ML 선택은 없다.

## 7. Node Delta Taxonomy

구현된 값:

- `SAME_NODE_UNCHANGED`
- `SAME_NODE_CHANGED_LABEL`
- `SAME_NODE_CHANGED_SPEECH`
- `SAME_NODE_CHANGED_STATE`
- `SAME_NODE_CHANGED_ROLE`
- `SAME_NODE_CHANGED_BOUNDS`
- `SAME_NODE_CHANGED_ORDER`
- `ADDED_NODE`
- `REMOVED_NODE`
- `SPLIT_NODE`
- `MERGED_NODE`
- `AMBIGUOUS_MATCH`
- `DATA_UNAVAILABLE`

각 row에는 baseline/candidate observation reference와 confidence가 있다.

## 8. Text/Speech Delta

구현 taxonomy:

- `TEXT_CHANGED_SPEECH_MATCHED`
- `TEXT_MATCHED_SPEECH_CHANGED`
- `BOTH_CHANGED_EQUIVALENT`
- `BOTH_CHANGED_DIFFERENT`
- `SPEECH_MISSING`
- `VISIBLE_LABEL_MISSING`
- `NEW_EMPTY_VISIBLE`
- `RESOLVED_EMPTY_VISIBLE`
- `KNOWN_EMPTY_VISIBLE`
- `DUPLICATE_SPEECH`
- `UNEXPECTED_SPEECH`
- `DYNAMIC_VALUE_ONLY`
- `ROLE_SUFFIX_ONLY`
- `PUNCTUATION_ONLY`
- `WHITESPACE_ONLY`
- `AMBIGUOUS`
- `DATA_UNAVAILABLE`

semantic equivalence는 동일 normalized form 또는 marker/role/punctuation/whitespace라는
명시적 deterministic 변환으로 설명될 때만 인정한다. 서로 다른 locale의 번역을 자동
동치로 보지 않는다.

## 9. Coverage Cohort Transition

Node match가 common cohort를 정의한다. scenario별로 다음 전이를 집계한다.

- `COVERED → COVERED`
- `COVERED → MISSED`
- `COVERED → UNKNOWN`
- `MISSED → COVERED`
- `MISSED → MISSED`
- `UNKNOWN → COVERED`
- `UNKNOWN → MISSED`
- `ADDED_CANDIDATE`
- `REMOVED_CANDIDATE`
- `AMBIGUOUS_COHORT`

각 row는 양쪽 coverage signature를 보존한다. coverage percentage만으로 regression을
판정하지 않으며, denominator 추가/제거를 common cohort 전이와 분리한다.

## 10. Known Limitation Binding

Reviewed snapshot의 issue ID, scenario/locale scope, resource ID, class, bounds,
mismatch/stop signature, derivative, evidence transaction, review status와 expiration을
검사한다. 가능한 경우 evidence reference의 transaction ID가 exact repeated row를
구분한다.

결과:

- `KNOWN_LIMITATION_UNCHANGED`
- `KNOWN_LIMITATION_CHANGED`
- `KNOWN_LIMITATION_RESOLVED`
- `NEW_UNREVIEWED_FAILURE`
- `LIMITATION_SCOPE_EXPANDED`
- `LIMITATION_EXPIRED`
- `DERIVATIVE_DUPLICATE`
- `LIMITATION_BINDING_AMBIGUOUS`

binding은 raw `FAIL`을 유지한다. PASS로 변환하지 않고 신규 limitation도 등록하지 않는다.
app version 변경만으로 자동 승계하지 않는다. resource/class/bounds/signature drift,
expiration 또는 scope 확장은 review item이다. 같은 issue ID도 scenario/locale scope가
다르면 자동 binding하지 않는다.

## 11. Accessibility Failure Classification

node delta, text/speech delta, raw result와 limitation binding을 조합해 다음 count를 만든다.

- `NO_ACCESSIBILITY_FAILURE`
- `REVIEWED_KNOWN_FAILURE`
- `NEW_ACCESSIBILITY_FAILURE`
- `RESOLVED_FAILURE`
- `STRUCTURAL_CHANGE`
- `AMBIGUOUS_FAILURE`
- `DATA_UNAVAILABLE`

new EMPTY_VISIBLE, 기존 label 대비 speech missing, incompatible speech, 동일 node의
covered-to-missed, role/action semantic loss, 신규 unmatched focusable unlabeled node는
new failure 후보다. 이 분류는 node-level 사실 분류이며 final overall PASS/FAIL이 아니다.

## 12. Comparator Core Integration

Phase 10.3B result에 다음 필드를 additive하게 연결한다.

- `observation_availability`
- `node_match_summary`
- `node_deltas`
- `text_speech_deltas`
- `coverage_cohort_transitions`
- `limitation_binding_deltas`
- `accessibility_failure_summary`
- `observation_artifact_references`
- observation `review_items`

기존 Phase 10.3B ID는 `aggregate_comparison_id`로 그대로 보존한다. Enriched
`comparison_id`는 그 ID, observation comparator version, baseline/candidate canonical
observation digest를 hash한다. generated time과 절대 경로는 ID source가 아니다.
따라서 optional source semantic 내용이 달라지면 enriched ID도 달라지고, aggregate-only
contract는 별도 ID로 안정적으로 남는다.

## 13. Data Availability Limitation

현재 English/Korean Approved core package에는 일반 node 전체 Evidence/XLSX가 embedded
또는 required pinned되어 있지 않다. 그러나 현재 workspace에는 manifest logical URI가
가리키는 보존 source run이 있어 digest 검증 후 복원이 가능하다.

- English `baseline_8f00aed49e61a07b_r0001`: Evidence + XLSX + Coverage +
  Inventory local source 이용 가능
- Korean `baseline_1f697e9b60c655df_r0001`: 같은 범위 이용 가능

현재 환경에서는 양쪽 모두 `COMPLETE`를 만들 수 있다. 다른 checkout에서 source run이
없으면 해당 optional artifact는 `UNAVAILABLE`이며 limitation/coverage-only 관찰을
일반 node 관찰로 가장하지 않는다. source를 찾았다는 이유로 기존 baseline package를
수정하거나 artifact를 pin하지 않는다.

이식 가능한 Phase 10.3D 비교를 위해서는 canonical observation bundle 또는 Evidence+
XLSX+Coverage 최소 묶음을 digest-pinned required/optional comparison artifact로 보존하는
migration이 필요하다.

## 14. Read-only Safety

Adapter는 `Path.open`, openpyxl read-only workbook과 JSON read만 사용한다. baseline,
candidate, catalog/index, lifecycle, CAS와 source run에 write API를 호출하지 않는다.
resolver는 `artifact://sha256/...`와 `qa-run://...`만 허용하고 digest를 검증한다.
ambiguous local device resolution, missing payload, digest mismatch와 unsupported schema는
구조화된 availability/diagnostic으로 반환한다.

이번 Phase에서 commit, push, 실기기 명령, repository mutation은 수행하지 않는다.

## 15. Tests

`tests/test_observation_comparator.py`는 33 tests로 요구된 31 scenarios를 포함한다.
resource exact/duplicate/changed, label/speech/dynamic/punctuation/whitespace, EMPTY_VISIBLE,
limitation unchanged/drift/resolved/scope/derivative, added/removed/order/ambiguous/split/merge,
coverage 양방향/denominator, unavailable/corrupt/asymmetric, deterministic/read-only와 실제
English/Korean source fixture를 검증한다.

Phase 10.3B comparator test는 additive integration 뒤에도 그대로 통과해야 한다.
Environment/Candidate/Repository regression, repository verify, py_compile과
`git diff --check`도 acceptance validation에 포함한다.

## 16. Phase 10.3D Handoff

10.3D는 이 Phase의 node-level 사실과 10.3B aggregate delta를 입력으로 final verdict
reducer를 설계해야 한다. 최소 handoff 항목은 다음과 같다.

1. availability/asymmetry를 verdict confidence에 반영
2. ambiguous/low-confidence match를 자동 regression으로 확정하지 않음
3. raw FAIL과 reviewed limitation을 별도 축으로 유지
4. common-cohort coverage와 denominator drift를 분리
5. observation bundle pinning/migration 후 portable replay 보장
6. final verdict 규칙의 versioning과 deterministic identity

10.3C는 final verdict를 생성하지 않으며 `FINAL_VERDICT_DEFERRED_TO_PHASE_10_3D`
warning을 유지한다.
