# TalkBack Canonical Identity & Target Relation Analysis

상태: Phase 5 analysis/design only  
기준일: 2026-07-11  
범위: latest Motion Sensor / Safe evidence-on acceptance runs  
Production behavior 변경: 없음

## Executive Summary

최신 Motion 16개 action transaction과 Safe 20개 action transaction의 ledger를 `transaction_id`로 재구성했다. 현재 `MOVE_TO_OTHER_NODE = 36/36`은 실제로 36번 모두 엉뚱한 node에 focus했다는 증거가 아니다. 현 reducer의 raw tuple comparator와 source schema 비대칭이 이 결과를 결정한다.

확정된 경로는 다음과 같다.

1. Runner `PRE_FOCUS_OBSERVED`는 canonical snake_case observation이며 `window_id`가 비어 있다.
2. Helper `TARGET_RESOLVED.resolvedTarget`는 raw camelCase `FocusSnapshot`이며 `windowId`가 없다.
3. Helper `POST_ACTION_OBSERVATION`과 `DELAYED_OBSERVATION`은 같은 `FocusSnapshot`에만 `windowId`를 추가한다.
4. reducer `signature()`는 missing과 present를 compatibility가 아니라 tuple inequality로 비교한다.
5. 따라서 resolved/post는 36/36 exact mismatch, pre/post는 36/36 `CHANGED`가 된다.
6. `target_relation=OTHER_NODE`와 `delta=CHANGED`이면 action result와 무관하게 `MOVE_TO_OTHER_NODE`가 된다.

정량 결과:

| Fact | Motion | Safe | Total |
|---|---:|---:|---:|
| transaction | 16 | 20 | 36 |
| current verdict `MOVE_TO_OTHER_NODE` | 16 | 20 | 36 |
| resolved/post exact tuple mismatch | 16 | 20 | 36 |
| mismatch에 `windowId`가 포함 | 16 | 20 | 36 |
| Motion fallback에서 `class_name` alias도 손실 | 1 | 0 | 1 |
| resolved와 100/300/1000 ms canonical structural tuple 동일 | 16 | 20 | 36 |
| current reducer stability `STABLE` | 15 | 20 | 35 |
| current reducer stability `UNSTABLE` | 1 | 0 | 1 |
| canonicalized delayed series stable | 16 | 20 | 36 |
| successful `moved` | 14 | 17 | 31 |
| successful `moved` 중 pre/post structural-static | 3 | 6 | 9 |
| `reached_end` 중 expected static | 2 | 3 | 5 |

`MOVE_TO_OTHER_NODE` 100%의 primary root cause는 **SCHEMA_NORMALIZATION_DEFECT + IDENTITY_COMPARATOR_TOO_STRICT + TARGET_RELATION_INCOMPLETE**이며 confidence는 `CONFIRMED`다. 이 verdict 분포 자체는 traversal defect의 크기를 측정하지 못한다.

별도로, 성공 `moved` 31건 중 9건은 package/class/resource/bounds/label이 pre/post에서 같고 100/300/1000 ms까지 같은 node description에 머문다. 이는 `MOVE_SUCCESS_WITH_STATIC_FOCUS`에 대한 `HIGH_CONFIDENCE` evidence다. 다만 pre observation에는 window/node unique ID/path가 없으므로 “동일 physical node”를 100% 확정할 수는 없다. 따라서 답은 **둘 다이지만 확정 수준이 다르다**: reducer defect는 confirmed, traversal/static-focus behavior는 high confidence다.

Representative는 focus와 동일 transaction 안에 기록되더라도 focus landing 이후의 planning observation이다. Motion과 Safe 각각 5건만 존재하며, reducer 실행 이후 생성된 경우가 있다. Representative와 actual focus의 차이는 이 분석에서 movement defect 판정에 사용하지 않았다.

## Artifact Inventory

### Primary runs

| Scenario | Run ID | Ledger | Events | Transactions | Reconciliation |
|---|---|---|---:|---:|---|
| Motion Sensor | `run_76d4cc40914c433b80b07da49b0ca475` | `qa_frontend_runs/batch_20260711_212123/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260711_212134.evidence.jsonl` | 475 | 16 | PASS, orphan 0, duplicate 0 |
| Safe | `run_5251b54c1f54491bb30649e70ef26660` | `qa_frontend_runs/batch_20260711_212734/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260711_212745.evidence.jsonl` | 583 | 20 | PASS, orphan 0, duplicate 0 |

두 run 모두 manifest, reconciliation, `runner.log`, `normal.log`, `logcat.txt`, XLSX, XML dumps, screenshots/crops, focusable inventory, focusable coverage, coverage probe plan/results/validation을 가진다. Motion은 일부 `debug_logs`도 가진다. 최신 Safe에는 별도 standalone Helper full-tree dump artifact가 없고, 두 ledger의 transported target/focus node는 `childrenOmitted=true`다. 이 때문에 container ancestry를 이 corpus만으로 확정할 수 없다.

XLSX는 존재하지만 Source of Truth가 아니다. 이 세션에는 승인된 spreadsheet runtime dependency loader가 없어 workbook cell-level read-only inspection을 수행하지 못했다. XLSX 관련 결론은 새로 만들지 않았고, physical movement 판정은 ledger와 Helper logcat에만 근거한다.

### Evidence used

- Ledger: correlation, event order, reducer payload, resolved/post/delayed observation.
- Manifest: Runner repository/source, Helper APK, device/app/TalkBack/WebView provenance와 dirty-worktree 사실.
- Reconciliation: ledger completeness, orphan/duplicate/write failure 0.
- `logcat.txt`: Helper 원본 event timestamp와 `TARGET_RESOLVED`/post/delayed serialization 차이.
- `normal.log`: production `moved`, `reached_end`, `[STEP] END`, representative projection, stop behavior.
- XML: package/class/resource-id/bounds/hierarchy 화면 맥락.
- Crop: Motion step 4에서 `동작 감지 센서`, Safe step 7에서 `기록` focus outline이 유지되는 시각적 보조 증거.
- Inventory/coverage/probe: source schema와 candidate projection 확인. Physical focus의 Source of Truth로 사용하지 않음.

### Required design references

이 문서는 다음 불변식을 유지한다.

- Step ≠ Transaction
- Ack ≠ Focus
- Representative ≠ Visit
- Consumed ≠ Visited
- XLSX ≠ Source of Truth
- Unknown is first-class

근거 문서:

- `docs/design/talkback-traversal-engine-root-cause-analysis-v2.md`
- `docs/design/talkback-traversal-engine-rca-independent-technical-review.md`
- `docs/design/talkback-traversal-evidence-architecture.md`
- `docs/design/talkback-traversal-evidence-implementation.md`

## Motion Transaction Analysis

표의 `pre`, `resolved`, `post`, delayed 값은 같은 `transaction_id`로 join했다. `relation`은 production 판정이 아니라 Phase 5 제안이다. `STRONG_ENTITY_LINK`는 physical exactness가 아니라, 동일 package/class/resource/bounds/label과 3~16 ms resolved→post 간격에 근거한 cross-observation link다.

| Step | Transaction / Logical action | Pre → Resolved → Post/Delayed | API / Event | Representative | Current | Proposed |
|---:|---|---|---|---|---|---|
| 1 | `tx_3518c77ea6064da39056d7bbbf9ae875` / `act_b5dd8f670f374ef5b08e633f84efccd6` | 상위 메뉴로 이동 → 모션센서… → same at 0/100/300/1000 | moved, claim, event 8, announcement | 100% | MOVE_TO_OTHER_NODE | resolved↔landing STRONG_ENTITY_LINK; pre changed-like |
| 2 | `tx_92cf94cd77854cfba0798e3ad81c52eb` / `act_bd278f3391ea4b10b45fb0877e21aadf` | 모션센서… → 옵션 더보기 → same at all samples | moved, claim, announcement | 동작 감지 센서 기록 | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 3 | `tx_86f30639f1f9431385a1a959042e70c1` / `act_d5e63cbd2b324b7f8a3eae51971d3f12` | 옵션 더보기 → 동작 감지 센서 → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 4 | `tx_ef88743be55a4f64904ac212ee622b30` / `act_1d8368495ab547a3b15d792e9f95e922` | 동작 감지 센서 → same → same | moved, claim, announcement | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like** |
| 6 | `tx_95e9095100e44a5ab8495e0117dc9e2d` / `act_91586eae11434135bdf56fc3ea34e967` | SmartThings Plugin → 동작 감지 센서 → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 7 | `tx_31939b02fdb64f8a8803e20c11014350` / `act_f5fb876ade2e4e4885a9c1b64cffcac7` | 동작 감지 센서 → same → same | moved, claim, announcement | compound motion card | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like**; representative separate |
| 8 | `tx_c75bd39358474755b98058c1dd8eb584` / `act_dd2ffc817780433aba7b17178aab13c8` | 동작 감지 센서 → same → same | moved, claim, announcement | 100% | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like**; representative separate |
| 9 | `tx_1349eaad26ab49e89f882fda444e7aec` / `act_671c682926bc41edb14e74880031185e` | 동작 감지 센서 → 제어 → same | moved, claim, announcement | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 11 | `tx_09c3e0bb3a844664aa0c80b784effbf3` / `act_31f62779902747f9a440fbdef98efa11` | 루틴 → 제어 → same | moved, claim, announcement | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 12 | `tx_7b8c91faf5104acd9f205b9a91377fba` / `act_a8263703afb54be483bcce8367d1841f` | 제어 → 루틴 → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 13 | `tx_3aea90bb9c624f5a8f4c80115acc5f48` / `act_5afe6cfa04154363b1d3cfd913e829c0` | 루틴 → 기록 → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 14 | `tx_f412f94cdb8c4cc1993f6cb36ecf7561` / `act_9f08c53c55da4083b94cc46bc46be4e7` | 기록 → same → same | reached_end, no claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; expected static |
| 16 | `tx_2649c662e1154f1f95ba594f7a998bd2` / `act_26caa86045ba47f2a7e407743c716799` | 기록 → 제어 → same | moved, claim, announcement | 기록이 없습니다 | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like; representative separate |
| 17 | `tx_d814ad37e333415fa281f23ca488b0f9` / `act_480e1d0d775a4e68a42dbb37ff4e4cf1` | 제어 → 루틴 → immediate missing; 100/300/1000 same 루틴 | moved, claim, announcement | - | MOVE_TO_OTHER_NODE, UNSTABLE | delayed stable; immediate missing; Runner fallback schema mismatch |
| 18 | `tx_202e15b8a36343498e457a9d13c84bb0` / `act_a9d3f8e7f0d048bd981b58e315c58413` | 루틴 → 기록 → same | moved, claim, announcement | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 19 | `tx_4438ea0edff44e7cb7d61313a8079621` / `act_36c95d7f2fb741ec9d952afd3b39572e` | 기록 → same → same | reached_end, no claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; expected static |

Motion summary:

- `moved`: 14; `reached_end`: 2.
- Successful moved 중 structural-static: steps 4, 7, 8 = 3/14.
- Current stability: 15 stable, 1 unstable. Canonicalized delayed series는 16/16 stable.
- Helper focus event가 transaction에 직접 귀속된 건 5/16; Helper announcement도 5/16. 나머지는 observation series가 movement evidence이고 event absence는 movement failure를 뜻하지 않는다.
- Representative 5개는 physical landing과 다른 planning candidate이며, physical delta 계산에서 제외해야 한다.

## Safe Transaction Analysis

Safe run에는 메뉴 overlay 순회 8 transaction과 본문 순회 12 transaction이 같은 scenario ledger에 있다. Step index는 transaction identity가 아니므로 중복 step 번호를 transaction ID로 구분한다.

| Step | Transaction / Logical action | Pre → Resolved → Post/Delayed | API / Event | Representative | Current | Proposed |
|---:|---|---|---|---|---|---|
| 1 | `tx_cf24764609c0469d89221a8da3d4c0d3` / `act_1744faed21fd4a90a0ed3d5123f42108` | Safe WebView → 세이프 버튼 → same all samples | moved, claim, event 32768 | 도움 요청 연습하기 compound | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like; representative separate |
| 2 | `tx_77d4253d0613412492eb1acfcba96e10` / `act_d8bb1d87042f4daa8ac301a20dda1e50` | 기기 편집 → 기기 삭제 → same | moved, claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 3 | `tx_7c0d30daa20b492591a73aaf3cc3dcff` / `act_4756c834fd534694850fe7bd9fcf9583` | 기기 삭제 → 홈 화면에 추가 → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 4 | `tx_df77f48ec47545f48daa1dd2e8491c38` / `act_96cc4f189dba44f5bac219d271cddd3f` | 홈 화면에 추가 → 설정 → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 5 | `tx_7c86fba40e27446fa904de168e32dd25` / `act_e0b4dde48d034d008d366c587606ea79` | 설정 → 정보 → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 6 | `tx_fd45fa548ca64588a10440b6e1a2d9e4` / `act_576a43d31357494d8fec4d3ec5433fda` | 정보 → same → same | reached_end | - | MOVE_TO_OTHER_NODE | expected static |
| 7 | `tx_bd35a5bfc6784d879a11cf2c97ec85c7` / `act_10fb3f65c84c4d40b235022e655534e0` | 정보 → same → same | reached_end | - | MOVE_TO_OTHER_NODE | expected static |
| 8 | `tx_dc4e0588b3584053bc9d7e80b0689b2d` / `act_d57c3ed3a343420ab7e890a183a53606` | 정보 → same → same | reached_end | - | MOVE_TO_OTHER_NODE | expected static |
| 2 | `tx_5be1251defaf4363be98eaf26f26a097` / `act_7a049b11fccd43528e5d21910aa42067` | Safe WebView → 세이프 버튼 → same | moved, claim, event 32768 | greeting | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 3 | `tx_3f1c0c253b57459d97d5700dd454f410` / `act_850ca9f78a1a4bacbcbeeeb63aacbd57` | 세이프 버튼 → 옵션 더보기 → same | moved, claim, event 32768 | record compound | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 4 | `tx_a63931c599434ccc84cf47be1ae057b1` / `act_83b0be2b2a4742b2bf7b6782d8d02f0f` | 옵션 더보기 → greeting → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 5 | `tx_d676ee6bb1454b82b1878321256ca5fa` / `act_fa72914ee3884bbf908d1f900fa5a5fd` | greeting → record compound → same | moved, claim, event 32768 | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 6 | `tx_467e57ddce0e45db94fab11326e93344` / `act_d24aeb7f956745f993c59bc10ba97472` | record compound → 기록 title → same | moved, claim, event 32768 | description child | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like; representative separate |
| 7 | `tx_c5e76172b1374169a6d8574d50f77cbf` / `act_748e14c01e314eefb0b5beb8c4492704` | 기록 → same → same | moved, claim | icon candidate | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like**; representative separate |
| 8 | `tx_2b7bdeb13162484d919d1ab8b0b7bc61` / `act_22a556b85b0e4d7ba75ec8b3c8128734` | 기록 → same → same | moved, claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like** |
| 9 | `tx_af23112b25234b76966ccf4be3013c2f` / `act_6da84bee0e0e45ada7296471fb625524` | 기록 → record compound → same | moved, claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; changed-like |
| 10 | `tx_9432bcab83a04387a3fd45a908cc3374` / `act_fc0c0425a7694759899b12a2028cbca9` | record compound → same → same | moved, claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like** |
| 11 | `tx_1cd5c2a4f06542b3879614a0ece69109` / `act_960057ca05fb477eac60b128ea619c53` | record compound → same → same | moved, claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like** |
| 12 | `tx_c380e39b017a41e9981fc40cc0fec0bd` / `act_a38a75f54de6469db9a2e41dd675178d` | record compound → same → same | moved, claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like** |
| 13 | `tx_36cac43296bf4d4b820596e0a97e0298` / `act_94346b89689246aa9ae9f0bccf1b48fd` | record compound → same → same | moved, claim | - | MOVE_TO_OTHER_NODE | STRONG_ENTITY_LINK; **static-like** |

Safe summary:

- `moved`: 17; `reached_end`: 3.
- Successful moved 중 structural-static: body steps 7, 8, 10, 11, 12, 13 = 6/17.
- resolved와 immediate/delayed structural observation은 20/20 동일하고 20/20 stable하다.
- Helper focus event 직접 귀속 9/20, Helper announcement 8/20.
- Safe는 target resolution failure를 보이지 않는다. 이번 run의 resolved target과 landing은 모두 강하게 compatible하다.
- Representative가 practice/description/icon/body candidate를 가리키는 것은 actual focus와 다른 abstraction이다. 이 사실만으로 container merge 또는 traversal success를 주장할 수 없다.

## MOVE_TO_OTHER_NODE Root Cause

### Exact code path

`tb_runner/evidence.py:489-580`의 current reducer는 다음을 수행한다.

```text
signature = package + window + class + resource-id + exact 8-value bounds tuple
pre = PRE_FOCUS_OBSERVED
post = last POST_ACTION_OBSERVATION, else POST_FOCUS_OBSERVED
resolved = first payload containing resolvedTarget

post == resolved       -> TARGET
post in resolved.children -> CONTAINER_CHILD
else                   -> OTHER_NODE

pre == post            -> UNCHANGED
else                   -> CHANGED

CHANGED + OTHER_NODE   -> MOVE_TO_OTHER_NODE
```

### Failure decomposition

| Condition | Motion | Safe | Cause |
|---|---:|---:|---|
| exact resolved/post mismatch | 16/16 | 20/20 | optional `windowId` present only in post |
| window mismatch | 16/16 | 20/20 | `FocusSnapshot.toJson()` lacks window; post capture appends it |
| class mismatch | 1/16 | 0/20 | Motion immediate missing; Runner canonical fallback uses `class_name`, comparator only reads `className`/`class` |
| package mismatch | 0 | 0 | compatible |
| resource-id mismatch | 0 | 0 | compatible, including both missing |
| bounds mismatch | 0 | 0 | exact equal |
| resolved children available | 0/16 | 0/20 | transport emits `childrenOmitted=true` |
| container-child evaluator usable | 0/16 | 0/20 | `has_descendant()` has no children to traverse |
| pre/post current delta CHANGED | 16/16 | 20/20 | primarily the same window schema asymmetry |
| delayed used for target relation | 0 | 0 | delayed observations are stability-only |

### Missing field semantics defect

현재 tuple equality는 다음 세 상태를 구분하지 않는다.

- known equal
- known different
- unavailable on one or both sides

`resolved.windowId = unavailable`과 `post.windowId = 1637/1685`는 contradiction이 아니라 incomplete evidence다. 이를 different로 처리한 것이 36/36 false `OTHER_NODE`의 직접 원인이다. 반대로 둘 다 missing인 것도 equal physical evidence가 아니다. Canonical comparator는 field별 `EQUAL`, `DIFFERENT`, `LEFT_MISSING`, `RIGHT_MISSING`, `BOTH_MISSING`, `INCOMPARABLE_SCOPE`를 먼저 산출해야 한다.

### Bounds and text

- Bounds는 exact integer tuple만 지원한다. coordinate space/display/surface revision 검증이나 tolerance가 없다.
- Text/content-description/talkback label은 current target relation에 전혀 사용되지 않는다.
- Node path/parent path/accessibility node ID도 사용하지 않는다.
- 따라서 current comparator는 한편으로 missing window에 과도하게 엄격하고, 다른 한편으로 semantic/hierarchy evidence에는 지나치게 빈약하다.

### Container relation is unreachable in this corpus

`has_descendant(resolved, post_signature)`는 serialized `resolvedTarget.children`가 있어야 한다. 두 run의 36개 resolved target은 모두 `childrenOmitted=true`이고 children array가 없다. 그러므로 container-child branch는 data transport상 실행 불가능하다. Bounds containment를 대신 쓰지 않는 것은 옳지만, hierarchy assertion을 별도 event/field로 운반해야 한다.

## Observation Schema Compatibility

| Semantic field | Runner focus / representative | Helper target/focus | XML candidate | Focusable inventory/probe |
|---|---|---|---|---|
| package | `package` | `packageName` | `package` attr → often `packageName` adapter | generally absent |
| resource-id | `resource_id` | `viewIdResourceName` | `resource-id` attr → `viewIdResourceName` | `view_id` / `probe_target_view_id` |
| class | `class_name` | `className` | `class` attr → `className` | `class_name` / `probe_target_class_name` |
| bounds | `bounds` dict; representative may contain `raw` string | `boundsInScreen` dict | `[l,t][r,b]` string → adapter string/dict | `bounds` string/dict repr |
| text | `text`, `normalized_text` | `text` | `text` attr | `label` |
| content description | `content_description` | `contentDescription` | `content-desc` attr | folded into `label` or unavailable |
| TalkBack label | `talkback_label`, normalized | `talkbackLabel`, `mergedLabel` | not native; derived | `label`, `normalized_label` |
| node path | `node_path` | `nodePath=null` | derivable from XML indices but not persisted canonically | unavailable |
| parent path | `parent_path` | `parentPath=null` | derivable | unavailable |
| window | `window_id`, usually empty | absent in resolved; present in post/delayed | unavailable | unavailable |
| source node ID | unavailable | unavailable | unavailable | unavailable |
| timestamp | `captured_at` + snapshot ID | epoch `timestamp` | dump file/step time | production step time |
| snapshot/surface | Runner-generated | not Helper-native; envelope surface only | dump/step implicit | output/step implicit |

`build_node_observation()`은 raw camelCase를 canonical snake_case로 만들지만 이미 canonical인 `class_name`을 다시 입력받으면 읽지 못한다. Current reducer도 `class_name`을 읽지 않는다. Canonical model은 ingestion boundary에서 한 번만 normalize하고, 이후 raw source key를 직접 읽지 않아야 한다.

## Canonical Observation Model

### Model

```text
CanonicalObservation
  canonical_observation_id
  source_observation_id
  source_type / producer
  run_id / scenario_tx_id / transaction_id
  capture_time / runner_receive_time / producer_sequence
  snapshot_id / surface_id / surface_revision
  package_name / window_id / display_id
  class_name / resource_id / resource_id_short
  bounds_screen / bounds_normalized / coordinate_space
  text_normalized / content_description_normalized
  talkback_label_normalized / announcement_tokens
  node_path / parent_path / child_index / accessibility_node_id
  semantic_role
  clickable / focusable / accessibility_focused / selected / enabled
  capture_source / capture_status
  field_availability / normalization_version / raw_reference
```

### Field classification

| Field | Classification | Scope / rule |
|---|---|---|
| run/scenario/transaction IDs | Stable identity context | correlation only, not node equality |
| canonical observation ID | Stable observation key | one immutable observation; never cross-time equality |
| package name | Stable physical scope | known different forbids same physical node |
| window ID | Stable within window lifecycle | required-or-unavailable; missing is not difference |
| display ID | Stable coordinate scope | required for cross-display geometry |
| accessibility node ID | Strong but unstable | exact within active window lifecycle; never global |
| resource ID/full and short | Supporting high weight | may be missing, duplicated, recycled, or WebView-generated |
| class | Supporting | framework/virtual replacement may change class |
| node/parent path | Supporting, unstable | DOM/list mutation can invalidate |
| child index | Supporting, unstable | only with parent/snapshot |
| bounds screen | Volatile observation fact | exact within snapshot; scroll/layout sensitive |
| normalized bounds | Supporting geometry | only after coordinate/surface compatibility |
| semantic role | Supporting semantic | native or inferred with provenance |
| normalized text/description/label | Supporting semantic | never physical equality alone |
| clickable/focusable/selected/enabled | Volatile state | relation support, not identity core |
| accessibility focused | Volatile state | focus fact at capture time |
| capture time/source/status | Display/audit metadata | temporal validity, not node equality |
| raw text/description/label | Display-only/raw evidence | normalized derivative used for comparison |
| alias | Optional asserted relation | adapter/config or evidence assertion, never implicit equality |

Every field carries availability: `KNOWN`, `UNAVAILABLE_AT_SOURCE`, `OMITTED_BY_TRANSPORT`, `PARSE_FAILED`, `NOT_APPLICABLE`. Empty string must not collapse all five.

### Normalization requirements

- Accept source aliases (`resource_id`, `viewIdResourceName`, `view_id`, XML `resource-id`) only at adapters.
- Canonical internal keys are snake_case and comparator never reads raw aliases.
- Resource ID normalization retains full value and short suffix; short equality cannot override different full IDs.
- Bounds parse dict, Android string, XML brackets, Python dict repr; retain raw, coordinate space and parse status.
- Text normalization uses Unicode normalization, whitespace/punctuation policy and locale; raw value retained.
- Missing field is not a wildcard and not a mismatch. It reduces achievable confidence.
- Source timestamps are not directly ordered across processes; correlation and producer sequence dominate. Helper epoch deltas may be used within Helper only.

## Physical Node Identity

Physical identity asks whether two observations refer to the same accessibility node instance/lifecycle, not whether they mean the same thing.

### Match levels

| Level | Minimum evidence | Permitted conclusion |
|---|---|---|
| `EXACT_OBSERVATION` | same canonical observation ID | same captured fact |
| `EXACT_PHYSICAL_NODE` | compatible run/surface/window lifecycle + same accessibility node ID, no strong contradiction | physical same |
| `STRONG_PHYSICAL_LINK` | same package/window when known + class/resource/path compatible + exact/compatible geometry in adjacent capture | likely same physical entity |
| `WEAK_PHYSICAL_LINK` | partial structural/geometry agreement, no contradiction | hypothesis only |
| `DIFFERENT_PHYSICAL_NODE` | known incompatible package/window, different node IDs in same lifecycle, or multiple strong contradictions | physical different |
| `INDETERMINATE_PHYSICAL` | missing/ambiguous/conflicting evidence | no physical verdict |

For the current 36 transactions, resolved↔post/delayed is `STRONG_PHYSICAL_LINK`, not `EXACT_PHYSICAL_NODE`, because resolved lacks window and all sources lack accessibility node ID/path. Pre↔post static-like 14건도 exact physical same이 아니라 `HIGH_CONFIDENCE structural static`이다.

### Dynamic cases

- Node recreation: new physical identity; semantic entity link may remain.
- Scroll: bounds changes; same resource/path/relative list key may preserve entity link.
- WebView/Compose: node ID/path can churn; surface revision and semantic/hierarchy evidence required.
- RecyclerView: resource ID reuse is expected; row key, relative path, label and geometry instance must disambiguate.
- Full-screen ancestor/bottom navigation/local tab: bounds or text alone cannot establish physical equality.

## Semantic Object Identity

Semantic identity asks whether observations represent the same user-perceivable object even if physical nodes differ.

### Inputs

- stable resource ID with instance/list context
- normalized TalkBack label and semantic role
- text/content-description composition
- explicit ancestor/descendant or container-merge assertion
- relative geometry within a known container
- announcement equivalence
- adapter alias with validity scope

### Guardrails

- Same text alone is `SAME_LABEL`, not same semantic object.
- Same resource ID with different list instance is `SAME_RESOURCE_DIFFERENT_INSTANCE`.
- Same bounds after surface mutation is not equality.
- Different bounds after scroll is not difference by itself.
- Compound announcement may grant semantic-announcement credit to children but not direct physical visit credit.
- SmartThings-specific labels/selectors belong in adapter/config, never the core comparator.

`SemanticIdentityResult` must include relation, confidence, supporting and contradicting signals, scope, rule version, and `allows_direct_visit_credit=false` by default.

## Target Relation Taxonomy

### Orthogonal result axes

A single enum cannot safely encode all facts. The evaluator returns:

```text
TargetRelationResult
  physical_relation
  hierarchy_relation
  semantic_relation
  temporal_relation
  aggregate_relation
  confidence
  supporting_fields
  contradictions
  missing_fields
  evidence_ids
  rule_version
  allows_move_confirmation
  allows_direct_visit_credit
```

### Aggregate taxonomy and conditions

| Relation | Required evidence | Priority / credit |
|---|---|---|
| `EXACT_PHYSICAL_NODE` | exact physical criteria | highest; may confirm target landing |
| `SAME_SEMANTIC_OBJECT` | strong entity link or explicit semantic continuity without physical contradiction | movement target compatible; direct visit depends on policy |
| `TARGET_ANCESTOR` | landed node is proven ancestor of requested/resolved target | directional hierarchy; no automatic leaf visit |
| `TARGET_DESCENDANT` | landed node is proven descendant | directional hierarchy |
| `CONTAINER_PARENT` | target child, landing focusable container with tree evidence | container direct visit only |
| `CONTAINER_CHILD` | target container, landing focusable child with tree evidence | child direct visit only |
| `ALIAS_EQUIVALENT` | explicit scoped alias assertion | policy-specific compatibility; default no visit credit |
| `ANNOUNCEMENT_EQUIVALENT` | announcement composition matches target semantics, physical link absent | semantic speech credit only |
| `SAME_RESOURCE_DIFFERENT_INSTANCE` | same resource, incompatible instance/path/list key/window lifecycle | not same target |
| `SAME_LABEL_DIFFERENT_LOCATION` | label same, geometry/instance differs | ambiguity diagnostic |
| `RELATED_BOUNDS` | geometry relation only | weak diagnostic, never movement confirmation |
| `UNRELATED_NODE` | strong incompatible evidence after hierarchy/alias evaluation | target mismatch |
| `INSUFFICIENT_EVIDENCE` | neither compatible nor contradictory evidence sufficient | first-class unknown |

### Conflict precedence

1. Validate correlation, snapshot/surface/window scope. Incomparable scope yields insufficient unless an explicit cross-surface link exists.
2. Known package/window/node-ID contradiction blocks exact physical equality.
3. Exact observation/physical relation wins only with no strong contradiction.
4. Proven hierarchy relation is preserved even when physical nodes differ.
5. Explicit scoped alias is evaluated after physical/hierarchy facts and never erases them.
6. Strong semantic object link may establish compatibility but not physical sameness.
7. Resource/label/bounds-only relations remain diagnostic.
8. `UNRELATED_NODE` requires positive contradiction; missing evidence yields `INSUFFICIENT_EVIDENCE`.

For directional `SMART_NEXT`, requested target is only `direction=next`; it is not a node identity. Relation must therefore be resolved-target↔landing, while pre↔landing answers movement delta. Requested node relation is applicable only to target-specific SELECT/FOCUS/REALIGN actions.

## Time/Stability Model

### Temporal classifications

| Pattern | Evidence rule |
|---|---|
| `STABLE_LANDING` | compatible landing at immediate/100/300/1000, or resolved plus all available delayed samples when immediate unavailable |
| `TRANSIENT_LANDING` | immediate target-compatible, later stable on a different node |
| `SNAP_BACK` | pre A → post B → delayed A with strong links |
| `DELAYED_COMMIT` | immediate pre/static/unknown → later target-compatible B, supported by focus event |
| `INTERMEDIATE_CONTAINER` | intermediate ancestor/container then stable descendant/target with hierarchy evidence |
| `NODE_REPLACEMENT` | semantic continuity with new physical node/surface revision |
| `ANNOUNCEMENT_ONLY_MOVEMENT` | announcement changes but physical focus remains/unknown |
| `UNSTABLE` | multiple incompatible landings without a terminal stable sample |
| `INDETERMINATE_STABILITY` | insufficient samples/scope |

### Current runs

| Pattern | Motion | Safe | Confidence |
|---|---:|---:|---|
| structurally stable resolved→100/300/1000 | 16 | 20 | HIGH_CONFIDENCE |
| current reducer stable | 15 | 20 | observed |
| current reducer unstable | 1 | 0 | schema/source artifact, not physical drift |
| snap-back | 0 observed | 0 observed | not proven absent outside sample windows |
| delayed commit | 0 confirmed | 0 confirmed | event stream incomplete |
| transient/intermediate/replacement | 0 confirmed | 0 confirmed | hierarchy/node ID missing |
| announcement-only | 0 confirmed | 0 confirmed | physical identity incomplete |

Helper resolved→immediate gap은 Motion 15건에서 3–16 ms, Safe 20건에서 2–15 ms다. Motion 한 건은 immediate observation이 missing이다. 100/300/1000 callbacks은 best effort이며 Motion에서 handler 지연 outlier가 있었지만 세 sample의 canonical structural node는 동일했다. Offset label 대신 actual capture timestamp를 사용해야 한다.

## Container Merge Model

### Required chain

```text
requested candidate observation
  -> resolved action node
  -> accessibility event source node
  -> immediate/delayed landing node
  -> representative candidate
  -> announcement composition
```

Container merge assertion에는 최소한 다음이 필요하다.

- target and landing observation IDs
- common snapshot or explicit cross-snapshot link
- node path/parent path/child index or a bounded ancestor chain
- package/window/surface compatibility
- focusable/clickable/role facts
- child label set and announcement token mapping
- bounds as supporting evidence only
- assertion direction and confidence
- direct visit credit policy

현재 Safe/Motion corpus에서는 resolved target의 children이 모두 transport에서 생략되고 node/parent path가 null이다. Representative도 다른 snapshot의 planning candidate이고 일부 bounds는 raw string이다. 따라서 requested child→container→representative child chain은 **UNVERIFIED**다. Container merge를 정상 success로 인정할 수 있는 일반 설계는 가능하지만, 이번 36건을 container merge로 재분류할 evidence는 없다.

정상 container landing인 경우:

- container는 direct physical visit credit 가능
- announcement에 포함된 child는 semantic-announcement credit 가능
- child direct physical visit은 생성 금지
- representative 선택/consumption은 별도 planning fact

## Anchor/Target/Focus/Visit Identity Separation

| Identity | Question | Comparator policy |
|---|---|---|
| Anchor identity | 화면 readiness를 증명하는 focus/screen marker인가? | screen identity와 focus anchor를 별도 축으로 평가; configured allowed alias만 허용 |
| Action target identity | Runner가 요청했고 Helper가 실제 action한 node는 무엇인가? | requested↔resolved; ancestor promotion은 directional relation과 reason 필수 |
| Focus landing identity | action 후 physical focus는 어디에 안정화됐는가? | resolved↔post/delayed; physical/hierarchy/time relation |
| Visit identity | 어떤 object에 어떤 종류의 visit credit을 줄 수 있는가? | direct physical, container, semantic announcement를 분리 |
| Representative identity | planning/export candidate는 무엇인가? | basis snapshot과 focus relation을 기록; movement/visit의 대체물 금지 |

다섯 identity가 하나의 comparator를 공유하면 안 된다. Canonical observation normalization은 공유할 수 있지만 comparator policy와 허용 relation은 목적별로 다르다. 특히 anchor는 target substitution을 검출해야 하고, traversal delta는 pre/post physical relation을 보며, visit은 stable landing과 credit policy가 필요하다.

## Cross-Plugin Applicability

| Screen type | Required identity behavior |
|---|---|
| Native Android View | resource/window/node ID 강한 신호, state 변화 별도 |
| WebView | missing resource/path, virtual node recreation, compound label, surface revision |
| Compose | semantics merge와 regenerated virtual node, role/label/state provenance |
| RecyclerView/List | repeated resource ID, row instance key, scroll relocation |
| Card container | parent/child directional relation과 announcement composition |
| Local tab/bottom navigation | stable resource/role + selected state; content visit과 분리 |
| Full-screen primary ancestor | bounds containment만으로 alias 금지; requested/resolved promotion reason 필요 |
| Dynamic content | surface revision과 cross-snapshot entity assertion |
| Same-label repeated nodes | instance/path/geometry required; label-only equality 금지 |
| Resource-id-less node | node/path/role/geometry/label 조합, confidence 제한 |

Core에는 SmartThings label, Safe/Motion selector 또는 plugin exception을 넣지 않는다. 앱 alias는 versioned adapter/config에서 `AliasAssertion`으로 제공한다.

## Current Reducer Gap

| Classification | Confidence | Finding |
|---|---|---|
| `SCHEMA_NORMALIZATION_DEFECT` | CONFIRMED | snake/camel aliases와 already-canonical `class_name` 처리 불완전 |
| `IDENTITY_COMPARATOR_TOO_STRICT` | CONFIRMED | missing vs known을 different로 처리; exact tuple only |
| `TARGET_RELATION_INCOMPLETE` | CONFIRMED | hierarchy/semantic/alias axes 없음; container branch data unavailable |
| `TIMESTAMP_ALIGNMENT_DEFECT` | UNVERIFIED as primary | action events은 잘 correlated; representative는 의도적으로 later planning fact |
| `HELPER_TARGET_RESOLUTION_DEFECT` | NOT SUPPORTED for these runs | resolved와 landing/delayed 36/36 structurally compatible |
| `ACTUAL_DIFFERENT_NODE_MOVEMENT` | MIXED | 22/36 changed-like, 14/36 static-like; exact physical identity unavailable |
| `CONTAINER_MERGE_UNMODELED` | CONFIRMED design gap, UNVERIFIED occurrence | code/data cannot prove hierarchy in this corpus |
| `MULTIPLE_INTERACTING_CAUSES` | CONFIRMED | schema asymmetry + strict equality + missing-field semantics + incomplete taxonomy |

### Why every transaction was MOVE_TO_OTHER_NODE

모든 transaction에 대해 post observation에는 window ID가 있고 resolved target에는 없다. Comparator는 이를 different로 만든다. 같은 이유로 pre/post도 changed가 된다. Then `CHANGED + OTHER_NODE` branch가 action success 여부나 announcement와 관계없이 `MOVE_TO_OTHER_NODE`를 반환한다. Motion immediate-missing 한 건은 Runner fallback의 `class_name` alias까지 놓쳐 같은 결과가 된다.

### Reducer bug or traversal bug?

- 100% verdict distribution: **reducer/schema bug, CONFIRMED**.
- Successful moved 중 9/31 static-like: **traversal/Helper success behavior issue, HIGH_CONFIDENCE**, exact physical same은 아직 미확정.
- 나머지 22 successful moved는 canonical structural focus change가 관찰됐다. 이들이 requested semantic target을 올바르게 방문했는지는 node-specific request가 없는 directional action이므로 별도 relation/visit evidence가 필요하다.

## Implementation Design

이 절은 Phase 6의 shadow-only identity 구현 계약이며 실제 코드는 이번 Phase 5에서 변경하지 않는다.

### Expected files

- New `tb_runner/evidence_identity.py`: canonical model, adapters, comparison result types, relation evaluator.
- `tb_runner/evidence.py`: legacy reducer 옆에 v2 shadow reducer integration; ledger/event schema 유지.
- `tb_runner/collection_flow.py`: production row를 읽지 않는 shadow assertion emission hook only, 필요한 경우.
- `app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yHelperService.kt`: 후속 evidence completeness 단계에서 resolved target에도 window/path provenance를 동일 방식으로 싣는 범용 instrumentation 후보. Phase 6 core normalization의 선행조건은 아님.
- `app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yModels.kt`: observation serialization contract가 확장될 때만.
- `tests/test_evidence_identity.py`: new table-driven identity/relation tests.
- `tests/test_evidence.py`: legacy/new dual reducer and flag isolation.
- Frozen sanitized Motion/Safe fixtures plus Native/List/WebView/Compose synthetic fixtures.

### New models/interfaces

- `CanonicalObservation`
- `FieldComparison`
- `PhysicalIdentityResult`
- `SemanticIdentityResult`
- `HierarchyRelationResult`
- `TemporalStabilityResult`
- `TargetRelationResult`
- `IdentityAssertion`
- `ObservationAdapter` protocol per source
- `ComparatorPolicy` per anchor/action/focus/visit/representative purpose

### Functions

```text
normalize_observation(raw, source_type, envelope) -> CanonicalObservation
compare_physical(left, right, scope) -> PhysicalIdentityResult
compare_semantic(left, right, context) -> SemanticIdentityResult
evaluate_hierarchy(target, landing, assertions) -> HierarchyRelationResult
evaluate_stability(pre, immediate, delayed, events) -> TemporalStabilityResult
evaluate_target_relation(requested, resolved, landing, context) -> TargetRelationResult
reduce_shadow_v2(transaction_events) -> ShadowVerdictV2
```

Normalization must be pure and deterministic. Comparator output must cite observation/event IDs and rule version. No comparator reads production visited/consumed/summary fields.

### Reducer integration

1. Group immutable events by transaction ID.
2. Normalize each source observation once.
3. Evaluate pre↔landing physical delta.
4. Evaluate resolved↔landing target relation.
5. Evaluate time stability using actual timestamps.
6. Emit a new append-only shadow identity assertion/reduction event or v2 reconciliation projection.
7. Keep existing `SHADOW_ACTION_REDUCED` and production artifacts untouched during migration.

### Feature flag

Use a separate opt-in flag such as `TB_EVIDENCE_IDENTITY_SHADOW_ENABLED=1`, effective only when the evidence ledger is enabled. Default off. The flag controls v2 shadow calculation/emission only; it must not be read by traversal, Helper navigation, visit, audit, summary, coverage or frontend code.

### Telemetry

- relation count by source pair and confidence
- field availability/mismatch matrix
- legacy vs v2 verdict disagreement
- static-like moved count
- hierarchy/alias assertions and direct-credit=false count
- incomplete transaction/reducer exception count
- normalization version and rule version
- timing/cost and ledger size delta

No labels/selectors should be emitted as unredacted metric dimensions.

## Migration Strategy

1. Freeze current two ledgers as regression corpus; do not rewrite them.
2. Implement adapters and comparator unit tests with no reducer integration.
3. Replay frozen ledger deterministically and compare byte-stable v2 output.
4. Enable dual shadow reduction behind the new flag.
5. Validate expected outcome: current 36 `OTHER_NODE` are no longer produced solely from missing window; unresolved cases become `INSUFFICIENT_EVIDENCE`, not success.
6. Add Native, WebView, Compose, List, container and repeated-label corpus.
7. Collect new Helper evidence with resolved/post equivalent field availability and hierarchy assertions.
8. Only after independent acceptance may later work discuss production semantics. Phase 6 must not do so.

Backward compatibility:

- `evidence-event-v1` envelope remains valid.
- Existing ledger fields remain append-only.
- Old Helper/Runner observations normalize with explicit unavailable states.
- Existing reducer/output retained for comparison.
- No XLSX/API/summary/coverage schema change.

Rollback: turn off the v2 shadow flag. No production rollback or data migration is required.

## Regression Risk

| Risk | Consequence | Design control |
|---|---|---|
| missing treated as wildcard | false same-node | confidence cap; no exact match without required fields |
| window ID over-strict | fragmentation across source asymmetry | unavailable semantics; lifecycle scope |
| resource ID over-trust | repeated-list false match | instance/path/geometry context |
| label over-trust | same-text false match | semantic-only relation |
| bounds tolerance overreach | nearby nodes merged | coordinate/surface check; bounds supporting only |
| alias grants visit | false coverage | direct credit default false |
| container merge overreach | leaf falsely visited | separate container vs semantic announcement credit |
| late representative joined as focus | false movement | purpose and timestamp separation |
| shadow result leaks into production | behavior regression | separate flag/module; no production consumer |
| app-specific rules enter core | cross-plugin regressions | adapter/config boundary |

## Required Tests

### Unit matrix

- every source alias for package/resource/class/bounds/text/description/path/window
- already-canonical input remains lossless
- missing vs present is unavailable, not different
- known different package/window/node ID blocks physical same
- same resource repeated list instance stays different/indeterminate
- same label different bounds/location
- scroll bounds change with stable entity link
- WebView/Compose node recreation
- resource-id-less node
- exact and tolerant bounds with coordinate scope
- requested ancestor/descendant/container directions
- explicit alias validity and expiration
- announcement composition without direct visit credit
- immediate missing with stable delayed samples
- A→B→A snap-back
- delayed commit and node replacement
- event absent but observation complete
- late representative never changes movement result

### Frozen replay expectations

- Motion/Safe replay preserves 36 transactions and correlation IDs.
- resolved↔delayed produces at least `STRONG_PHYSICAL_LINK` 36/36, not `UNRELATED_NODE` from missing window.
- pre/post structural-static diagnostic: Motion 5/16 total, Safe 9/20 total.
- successful moved static-like diagnostic: Motion 3/14, Safe 6/17.
- Motion immediate-missing transaction uses delayed stability and stays non-snap-back.
- container relation remains `INSUFFICIENT_EVIDENCE` until hierarchy evidence exists.
- legacy reducer output is unchanged and recorded only for comparison.
- production rows, ordering, stop, summary, coverage, audit and XLSX are byte/semantic unchanged.

### Additional real-device evidence required

Before any production movement/visit policy change:

1. Same node snapshot must expose window ID and an accessibility node identifier on resolved, pre, post and delayed sources.
2. At least one known container-merge case must record bounded ancestor chain and announcement child mapping.
3. Manual TalkBack reference runs for one Native node, one WebView/Compose merge and one repeated-list label.
4. Safe/Motion repeat runs with clean repository SHA and matched Helper APK provenance.
5. A directional move with known static physical node and a known real move, each with focus event stream.
6. A scroll/recreation case proving semantic continuity across changed physical node.

## Final Gate

### Can Phase 6 Identity Implementation Start? — YES WITH LIMITATIONS

Phase 6 may implement only canonical normalization, identity/relation evaluation, frozen-ledger replay and dual **shadow-only** reduction. The current corpus is sufficient to prove the existing reducer defect and to specify missing-field semantics.

Limitations:

- Exact physical identity cannot be guaranteed because pre/resolved observations lack window/node unique ID/path.
- Container merge occurrence cannot be classified because ancestry is omitted.
- XLSX cell-level inspection was unavailable in this session; it is not required for the reducer root cause but remains an artifact-validation gap.
- Only Safe/Motion real-device corpus exists; Native/List/Compose and repeated-label corpus is required before production adoption.

Clear answers:

- **왜 모든 transaction이 MOVE_TO_OTHER_NODE였는가?** Source-specific window/class schema asymmetry was treated as exact identity difference; this forced both `CHANGED` and `OTHER_NODE`, and the reducer branch returned the verdict for all 36.
- **실제 traversal bug인가, reducer bug인가, 둘 다인가?** The 100% verdict is a confirmed reducer/schema bug. Separately, 9/31 successful moves are high-confidence static-focus behavior, so both issues exist, but only the reducer part is physically confirmed with current identity evidence.
- **어떤 relation부터 shadow-only로 구현해야 하는가?** `EXACT/STRONG_PHYSICAL_LINK`, `DIFFERENT_PHYSICAL_NODE`, `INSUFFICIENT_EVIDENCE`, and pre/post temporal stability first. Then hierarchy/container relations once ancestry evidence exists. Semantic/announcement/alias relations must remain non-crediting initially.
- **Production semantics 변경 없이 검증 가능한가?** Yes. Frozen ledger replay and dual shadow events can validate normalization, relations and verdict disagreements without any production consumer.
- **Phase 6에서 절대 건드리면 안 되는 영역은 무엇인가?** Traversal order/selection, Helper success meaning, anchor behavior, representative selection, duplicate/stop, visited/consumed, Summary/Coverage/Probe/Audit/PASS, XLSX/API/frontend, retry/sleep, and plugin-specific policy.

