# Phase 1 — State-based Auto Discovery Gap Analysis

분석 시작: 2026-10-04 · 보고서 완료: 2026-10-05 · 기준: `d42970272ea5002b8659a625c5799471f4127311`

이 문서는 현재 코드에서 확인한 사실과 후속 설계 제안을 구분한다. 신규 state/explorer 구현, 테스트 실행, 단말 조작, Full Run, APK build/install은 수행하지 않았다. 저장된 Phase 0 Acceptance 결과는 이 단계의 신규 검증 결과가 아니다.

## 1. Executive Summary

**Verdict: `READY_FOR_PHASE2_WITH_PRECONDITIONS`.** 기존 executor, 실제 focus reconciliation, positional visit ledger, axis-aware scroll, Global Navigation, evidence writer를 보존하고 **State observation / equality / registry 계층**을 추가하는 것이 적합하다. 기존 engine을 교체할 근거는 없다.

현재 구현은 `scenario entry → bounded focus traversal → evidence / completeness`까지 갖췄다. `현재 state → 안전한 action 목록 → resulting state → graph frontier`를 관리하는 공통 계약은 없다. Audit 후보, Helper focus 후보, navigation 후보는 목적과 denominator가 다르다. 이들을 단일 action 목록으로 무조건 합칠 수 없다.

Phase 2 착수 전 확정할 조건은 ① screen/viewport/object identity 분리, ② missing/unstable observation의 UNKNOWN 처리, ③ 기존 production 결과를 바꾸지 않는 관찰 adapter 경계, ④ equality replay corpus와 합격 기준이다. 활성화 safety policy는 Phase 2 관찰 작업을 막지 않지만 **자동 navigation 활성화 전에 반드시 완료**해야 한다.

기준 확인 결과:

```ini
BASELINE_HEAD=d42970272ea5002b8659a625c5799471f4127311
BASELINE_ORIGIN_MAIN=d42970272ea5002b8659a625c5799471f4127311
BASELINE_MATCH=YES
INITIAL_BRANCH=main
INITIAL_GIT_STATUS=?? out/
ANALYSIS_BRANCH=feature/phase1-state-auto-discovery-gap
```

최종32 Acceptance는 canonical 32/32 terminal, return code 0, root entry 5/5, Global Nav 5/5, input-only credit 0, QA/primary mismatch 0, artifact mismatch 0으로 published됐다. 그러나 QA 결과는 passed 2 / warning 28 / failed 2였고 cap/partial coverage/Food entry/Clothing 품질 FAIL은 남았다. **실행 종료 32/32가 전체 state나 객체 coverage 완료를 의미하지 않는다.** [최종 Acceptance 보고서](../../output/final32_acceptance_run_20261004/FINAL32_ACCEPTANCE_REPORT.md), §5–17.

## 2. Current Architecture

```text
QA run profile / canonical selection / RunSpec
  → scenario_config + runtime_config merge
  → collection_flow: entry / anchor / context / precondition
  → main loop / TraversalCoordinator
  → collect_focus_step / A11yAdbClient
  → Helper SMART_NEXT or explicit target / scroll / click
  → actual focus + speech + tree observation
  → evidence gate / reconciliation / VisitTracker / TraversalMetrics
  → stop policy + root ContentTerminal / scroll opportunity
  → XLSX / evidence JSONL / completeness / QA projection
```

아래 source 표의 경로, 심볼, 시작 line은 기준 worktree에서 확인했다. `CF`는 `collection_flow.py`, `SC`는 `scenario_config.py`를 뜻한다. 후속 표의 source 표기는 이 표와 해당 심볼을 참조한다.

| ID | 실제 구현 / 읽은 source | 책임과 경계 |
|---|---|---|
| S01 | [scenario_config.py](../../tb_runner/scenario_config.py):26 `TAB_CONFIGS`; :1496 `canonical_full_scenario_ids` | canonical membership/order, tab/anchor/context, pre-navigation, special policy, 기본 cap |
| S02 | [runtime_config.py](../../tb_runner/runtime_config.py):336 `load_runtime_bundle`, :386 merge; [runtime_config.json](../../config/runtime_config.json); [run_selection.py](../../tb_runner/run_selection.py):38 | defaults/group/shared navigation/shared anchor/shared pre-navigation/scenario override; 실행 selection |
| S03 | [collection_flow.py](../../tb_runner/collection_flow.py):9642 `_run_pre_navigation_steps`, :19159 `_run_start_pipeline`, :17851 `_main_loop_phase` | 실제 entry와 traversal lifecycle; state라는 변수명은 engine control state |
| S04 | CF:1092 `_is_focusable_inventory_node`, :1119 register, :1334 snapshot, :1915 coverage, :2097 probe plan; [coverage_probe_engine.py](../../tb_runner/coverage_probe_engine.py):906 | Audit V7 inventory/coverage/bounded focus probe |
| S05 | [A11yNavigator.kt](../../app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yNavigator.kt):48 `dumpTreeFlat`, :732 runtime collection, :920 pipeline; [A11yTraversalAnalyzer.kt](../../app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yTraversalAnalyzer.kt):77 | TalkBack-like focus candidates, merged/container normalization, Helper selection/execution |
| S06 | [A11yModels.kt](../../app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yModels.kt):396 `A11yNodeInfo`, :507 scroll capability, :604 focus snapshot; [A11yHelperService.kt](../../app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yHelperService.kt):196 dump | flat focus-oriented nodes와 opt-in raw scroll diagnostics; focus payload는 별도 schema |
| S07 | [talkback_lib/__init__.py](../../talkback_lib/__init__.py):1068 dump parser, :2066 click, :2092 scroll, :2685 smart move; [helper_bridge.py](../../talkback_lib/helper_bridge.py):145 | request/ACK/result transport, correlated evidence; dump metadata를 별도 저장 |
| S08 | [step_collection_service.py](../../talkback_lib/step_collection_service.py):36 correlated focus, :137 actual-field snapshot, :270 smart move | command 뒤 실제 focus와 speech 관찰; representative와 actual 분리 |
| S09 | [focus_reconciliation.py](../../tb_runner/focus_reconciliation.py):149; [traversal_reliability.py](../../tb_runner/traversal_reliability.py):30 identity, :79 strict focus, :159 metrics | selection/ACK/actual movement/new visit 분리 |
| S10 | [completeness.py](../../tb_runner/completeness.py):11 candidate, :27 eligibility, :45 reconcile; [candidate_lifecycle.py](../../tb_runner/candidate_lifecycle.py):27 relocation, :53 lifecycle | observed positional population, stale successor, strict visit denominator |
| S11 | [scroll_reliability.py](../../tb_runner/scroll_reliability.py):50 capability, :131 viewport, :154 transition, :208 verified scroll; [content_terminal.py](../../tb_runner/content_terminal.py):43 | scroll source/axis/movement, root observed-instance closure |
| S12 | [global_navigation.py](../../tb_runner/global_navigation.py):44 discover, :97 verify transition, :144 collect; [context_verifier.py](../../tb_runner/context_verifier.py):28 resource canonical map | selected destination 검증; body visit와 분리 |
| S13 | [local_tab_logic.py](../../tb_runner/local_tab_logic.py):26 lifecycle maps, :2232/:2291 Motion exceptions; CF:14591 candidate priority | tab activation/content/exhaustion state, spatial/container/CTA 우선순위 |
| S14 | [overlay_logic.py](../../tb_runner/overlay_logic.py):146 policy, :191 post-click classification; [popup_handler.py](../../tb_runner/popup_handler.py):14/:34 safe/danger labels; [device_tab_logic.py](../../tb_runner/device_tab_logic.py):486/:509 avoid tap | bounded navigation/recovery safety의 부분 구현 |
| S15 | [evidence.py](../../tb_runner/evidence.py):105 NodeObservation, :219 append-only writer, :303 scenario surface, :520 finalize; [evidence_identity.py](../../tb_runner/evidence_identity.py):331 normalize/:1055 reducer | observation/transaction/correlation IDs와 temporal evidence; screen registry는 아님 |
| S16 | [environment_fingerprint.py](../../tb_runner/environment_fingerprint.py):103; [observation_bundle.py](../../tb_runner/observation_bundle.py):70/:169; [baseline_artifact_store.py](../../tb_runner/baseline_artifact_store.py):34 | environment compatibility, portable observations, content-addressed artifact store |
| S17 | [plugin_card_discovery.py](../../tb_runner/plugin_card_discovery.py):300/:517/:605; [QA plugin_discovery.py](../../qa_frontend/backend/plugin_discovery.py):82 | current-view card discovery / onboarding 후보; 범용 graph crawl은 아님 |
| S18 | [audit_xml_candidates.py](../../tools/audit_xml_candidates.py):91; [audit_xml_coverage.py](../../tools/audit_xml_coverage.py):67; [audit_v5_traversal_core.py](../../tools/audit_v5_traversal_core.py):494/:905 | offline XML taxonomy / label coverage / normalized event ledger |
| S19 | [traversal_orchestration.py](../../tb_runner/traversal_orchestration.py):38 VisitTracker, :93 StopPolicy, :129 RecoveryExecutor, :302 Coordinator | production evidence decisions / existing recovery lifecycle |
| S20 | [audit_device_plugins.py](../../tools/audit_device_plugins.py):39 expected-content map, :476 evaluate; [audit_xml_policy.py](../../tools/audit_xml_policy.py):117 classify/:150 recommend | plugin-specific expected content, XML taxonomy/coverage/shadow aggregation; offline review 중심 |

Scenario는 entry point뿐 아니라 label/resource regex, anchor tie-breaker, context verification, recovery, overlay allow/block, stop boundary와 cap도 고정한다. 실행 cap은 base 정의만 읽어서는 안 된다. `load_runtime_bundle`은 group → shared references → per-scenario override를 적용한다. canonical Full membership은 enabled default와 별개다.

관련 [기존 state graph roadmap](talkback-state-graph-accessibility-crawl-roadmap.md)은 future direction으로 명시돼 있다. 현재 production 구현 여부는 위 source를 기준으로 판단했다. V10 identify/policy/shadow readiness 역시 [현재 architecture](../architecture.md) §6에서 Controlled Routing NOT STARTED로 구분된다.

## 3. Phase 0 Reusable Assets

분류는 후속 state explorer에서 사용할 때의 평가다. `REUSE_AS_IS`라도 상위 state/scope adapter가 필요할 수 있으며 기존 계약의 의미를 바꾸지 않는다는 뜻이다.

| 자산 | 분류 | 이유 / 필요한 연결 |
|---|---|---|
| Helper tree/focus collection + chunked transport | REUSE_WITH_ADAPTER | transport 재사용; flat traversal list와 raw hierarchy/XML, focus payload의 schema/source 분리 필요 (S05–08) |
| bounds/resource/class/text observation | REUSE_AS_IS | 원본 evidence로 보존; text를 durable screen ID로 쓰지 않음 |
| positional instance-v1 | REUSE_AS_IS | 동일 resource ID의 다른 bounds 분리; stable logical state ID와 별도 (S09) |
| expected population / eligibility | REUSE_WITH_ADAPTER | observed-only denominator와 UNKNOWN 유지; screen/viewport별 scope 추가 (S10) |
| actual observed population / strict visit proof | REUSE_AS_IS | A11y focus가 아닌 fallback/input-only는 credit 없음 |
| missed / unseen / active unseen | REUSE_WITH_ADAPTER | actionable navigation 후보와 구분; freshness/presence 붙여 scheduling input으로 소비 |
| stale relocation reconciliation | REUSE_WITH_ADAPTER | 같은 screen/container/관찰 세대 내에 한정; cross-screen alias 금지 |
| coverage / semantic coverage | REUSE_WITH_ADAPTER | semantic reading은 physical visit 또는 activated action 증명이 아님 |
| Audit V4 XML taxonomy/filter | REUSE_WITH_ADAPTER | readable/status/CTA/chrome 분류 힌트; locale/label merge 영향 큼 (S18) |
| V4 label-based coverage를 explorer completion oracle로 사용 | REQUIRES_REDESIGN | 같은 label 여러 instance collapse 가능; 현재 자체 진단값은 보존 |
| Audit V5 normalized events / candidate ledger | REUSE_WITH_ADAPTER | 사후 causal debugging에 적합; graph transition/state scope 부가 |
| V7 inventory / coverage probe plan | REUSE_WITH_ADAPTER | Focus action 후보의 기반; live freshness 및 unlabeled actionable gap 필요 |
| V8 bounded probe / promotion / coverage delta | REUSE_WITH_ADAPTER | probing은 실제 focus action을 수행하는 diagnostic 경로; production visit 권위와 합치지 않음 |
| actual move reconciliation / evidence gate | REUSE_AS_IS | ACK와 actual focus 분리; ambiguous/incomplete는 fail closed |
| axis-v1 verified scroll | REUSE_WITH_ADAPTER | forward vertical과 horizontal/pager 구분 재사용; 다중 container/역방향 registry 연결 필요 |
| Global Nav destination verification | REUSE_WITH_ADAPTER | target selected + transition evidence 계약 유지; common navigation action 형태로 감싸기 |
| root ContentTerminal | REUSE_WITH_ADAPTER | root에서만 현재 활성; plugin/state closure 및 action exhaustion은 별도 설계 |
| speech/native focus capture, Excel/JSONL/QA projection | REUSE_AS_IS | 기존 품질 판정 유지; graph sidecar schema 추가 |
| shadow verdict / V10 readiness를 explorer 실행 허가로 사용 | NOT_APPLICABLE | diagnostic/review provenance이며 production routing/safety authorization 아님 |

Audit 전체를 사후 tool로만 보는 것도 정확하지 않다. V7 inventory/plan은 runtime에 생성되고 probe가 focus action까지 수행한다. 반면 V4/V5 offline report와 shadow verdict는 이미 실행된 결과의 분석이다. **runtime 후보 추출을 발전시키되 진단 verdict를 자동 navigation 권한으로 승격하지 않는다.**

Device Audit driver(S20)는 별도 scenario 실행/retry/preflight도 제공하고, 결과 평가에서 XML candidate → label coverage → shadow verdict를 합친다. `PLUGIN_EXPECTED_CONTENT`의 Motion/Battery/Lock/TV/Washer 등 predefined token 그룹은 현재 explicit plugin quality expectation이다. READ/expected-content 대상이라는 사실이 해당 Lock/Start/Power action 활성화를 허용하지 않는다. 이 expectation은 locale/version 유지보수 지점이며 auto discovery로 자동 제거할 수 없다.

## 4. Candidate Discovery Analysis

### Producer → consumer chains

```text
(A) Helper focus model
AccessibilityNodeInfo
 → A11yTraversalAnalyzer.buildTalkBackLikeFocusNodes
 → A11yNavigator collect/normalize/grouped traversal list
 → A11yNavigationPolicy decision → SMART_NEXT execution
 → actual focus payload → Python step collection

(B) Audit inventory / expected model
dumpTreeFlat → A11yAdbClient.dump_tree
 → CF post-anchor snapshot + row inventory registration
 → inventory canonicalization (instance-v1)
 → focusable coverage matcher → uncovered/semantic/actual records
 → probe plan → bounded CoverageProbeEngine / offline review

(C) root terminal model
scroll_reliability.capture + actual focus proofs + semantic IDs
 → completeness.candidate/eligibility → ContentTerminal.records
 → CandidateLifecycle fresh-frame relocation aliases
 → historical unseen / active unseen / stale / logical covered
 → ContentTerminal.decision / scroll_opportunity
 → CF _apply_content_terminal_phase → verified_scroll → rediscovery

(D) navigation card candidates
Helper visible device nodes / raw Life XML
 → plugin_card_discovery → QA discovery response / onboarding draft
 → selected explicit entry route (separate workflow)
```

A와 B의 후보는 같지 않다. Helper는 merged/container/alias normalization을 적용한다. V7 inventory는 label 필수이고 readable short text도 수용한다(CF:1092). `completeness.eligibility`는 label/role 없는 노드를 제외하지만 root `ContentTerminal.observe`는 unlabeled focusable/clickable을 EXPECTED로 보강한다. 이렇게 denominator와 취급이 다르므로 하나를 그대로 범용 action generator로 사용할 수 없다.

**재사용 판단: REUSE_WITH_ADAPTER.** 후보 observation envelope에 `source, screen_id, viewport_id, capture_epoch, positional_instance_id, eligibility, current_presence, logical_successor, supported_action, confidence`를 추가하는 설계가 필요하다. 생성 결과는 적어도 `READ/FOCUS`, `SCROLL`, `NAVIGATION_ACTIVATION`, `MUTATING_CONTROL`, `UNKNOWN`으로 구분해야 한다. clickable/focusable은 safety 허가가 아니다.

현재 active unseen은 historical record 중 stale alias와 logical covered를 뺀 obligation이다. **active unseen이 지금 viewport에서 보이고 실행 가능한 객체라는 뜻은 아니다.** `current_presence`와 최신 bounds/action 지원을 다시 확인해야 한다. 미방문 후보가 있다는 사실만으로 reachability를 주장하지 않는다.

Helper의 `dumpTreeFlat`은 이름과 달리 모든 raw node의 완전한 hierarchy dump가 아니다. TalkBack-like focus node의 flat model이고 A11yNodeInfo에는 selected/enabled/role/package/window/path/actionList가 공통 필드로 없으며 actionable descendant 일부만 제공한다(S05/S06). selected tab/ancestry는 XML 또는 다른 payload에서 얻는다. Phase 2 collector는 누락을 UNKNOWN으로 표시해야 한다.

QA plugin discovery는 `current_view_only`를 벗어나는 요청에 `bounded_discovery_not_implemented_current_view_only_used` warning을 내고 Life는 XML이 필요하다(S17). 이 기능을 이미 존재하는 multi-state auto discovery로 셀 수 없다.

## 5. Smart Move Analysis

실제 main chain: CF:17370 `collect_focus_step(move=True)` → StepCollectionService:270 `move_focus_smart` → client:2685 → HelperBridge:145 correlated reqId broadcast → Helper collect/normalize/select → pipeline:920 focus 또는 pre-scroll → `SMART_NAV_RESULT` → actual focus/speech/delayed observation → actual fields snapshot → evidence gate / CF:269 reconciliation → VisitTracker / TraversalMetrics → repeat/stop/root scroll opportunity.

CF의 spatial/CTA representative 선택과 Helper의 next selection도 별도다. representative가 row를 보강/대체해도 actual fields는 분리돼 있고 실제 A11y focus로 확인된 객체만 방문 기록에 들어간다. CF:13662는 row persistence 전 focus proof를 수집하므로 Excel row와 unique visit 수는 동일하지 않다.

| 단계 | 현재 존재 | state explorer에서 추가할 것 |
|---|---|---|
| candidate selection | Helper list + Python spatial/CTA/local-tab priorities | live state/scope 후보와 executor 실제 선택의 correlation |
| command / request / ACK | reqId / tx / Helper result / flags | executor result adapter; 기존 ACK 의미 유지 |
| actual focus observation | immediate + delayed + fallback 구분 | resulting screen observation을 별도 수집 |
| focus reconciliation | selected≠actual, ambiguous, unchanged, ACK fail인데 moved도 분리 | transition 안에 focus result link |
| visit ledger | strict positional actual visit / duplicate / planning consumed | screen/viewport 별 projection; state/action ledger는 신규 |
| repeat / no progress | object/semantic/local-tab guards + capped loop | screen/action frontier exhaustion과 별도 관리 |
| scroll opportunity | root verified vertical continuation + viewport evidence | plugin/multiple container/backward에 적용하는 adapter contract |
| resulting state / graph update | 일반 state registry 없음 | Phase 2 observation/equality; Phase 6 graph frontier |

**기본 focus executor로 재사용 가능하다. 그러나 임의 후보 target을 실행하는 executor와 동일하지 않다.** `move_focus_smart(dev, direction)`에 desired candidate 인자가 없고 Helper가 next를 선택한다. `candidate generator → SMART_NEXT → actual focus`의 candidate는 기대/priority 힌트이며 target 보장 계약이 아니다. 특정 target은 기존 select/FOCUS_IN_BOUNDS/recovery 경로로 요청하고 landing을 검증해야 한다.

SMART_NEXT 한 번에 implicit pre-scroll/retarget가 발생할 수 있다. explorer transition은 요청 action, 실제 내부 effect, focus landing, viewport change, screen change를 구분해야 한다. focus가 움직였다는 사실만으로 screen state가 바뀌었다고 등록하면 안 된다. Smart previous는 같은 pipeline이 아니라 legacy previous fallback을 사용한다(client:2685).

## 6. Identity Model

현재 `instance-v1 = [schema, normalized scenario scope, resource_id, bounds discriminator]`; bounds 없으면 container+path, 그것도 없으면 unresolved label/class fallback이다(S09:30). **label/state text는 bounds identity의 key가 아니다.** strict physical credit에는 유효 bounds와 일관된 actual accessibility focus가 필요하다(:79). unresolved ID를 만들 수 있어도 방문 증명을 할 수는 없다.

| 상황 | 현재 계약 | state layer 설계 |
|---|---|---|
| 동일 resource ID / 다른 bounds | 서로 다른 positional instance | 그대로 유지 |
| 같은 resource/bounds / 온도만 변함 | 같은 positional ID; 변화는 evidence | 값 observation revision만 증가 |
| scroll로 위치 이동 | 새 positional ID; 보수적 stale successor relation 가능 | screen+container+capture epoch 내 logical link만 |
| 같은 bounds/path 재활용 | instance-v1만으로 durable object 동일성 불충분 | viewport/time/evidence provenance와 contradiction 기록 |
| 다른 screen에서 동일 resource/bounds | scenario scope만으로 screen 구분 불충분 | 기존 key를 변경하지 않고 `(screen_id, viewport_observation, instance_id)` association 추가 |

객체 identity와 화면 state identity는 다른 문제다. 화면에는 여러 객체가 있고 객체 geometry는 scroll/rotation에 따라 바뀐다. resource ID 하나로 state를 정의하거나 visible instance ID 전체를 screen ID로 정의하면 UI reuse/cap/scroll마다 false collision 또는 explosion이 발생한다.

CandidateLifecycle은 fresh verified frame 두 개에서 구조가 one-to-one으로 맞고, ≥3개 객체/≥60% coherent vertical translation 조건이 맞을 때 alias를 만든다(S10:27). absence alone은 retirement 증명이 아니다. successor는 기존 obligation의 논리적 reconciliation이며 **successor가 실제 focus 방문했다는 credit이 아니다**. 이를 state merge의 직접 근거로 쓰지 않는다.

## 7. Existing State Concepts

| 현재 개념 | 실제 의미 | 재사용 / 한계 |
|---|---|---|
| `MainLoopState`, ScrollState, CTA/local-tab state | runtime progress/guard/control memory (CF:777) | engine state; screen registry 아님 |
| screen_context_mode + context verifier | bottom-tab/new-screen 및 expected route 확인 | state observation hint; arbitrary screen equality 아님 |
| selected bottom tab / Global Nav `current` | selected destination semantic verification | navigation context 핵심 입력; XML 의존 경로 존재 |
| local tab lifecycle/signature maps | focus/activation/content confirmed/exhausted 분리 | scoped tab action ledger prototype (S13); durable graph 아님 |
| `scroll_reliability.viewport` | instance set strict SHA256 + 16px quantized stable signature | viewport change input; screen ID 아님 |
| ContentTerminal strict/semantic signature | labels 포함/제외 + structural/cap/scope stability | dynamic value 분리 힌트; root closure 전용 |
| `_make_dump_signature` CF:3959 | 첫 10 nodes의 resource/text/description | entry 변화 휴리스틱; partial/order/text dependent |
| client `_tree_signature/_tree_node_hashes`:1311 | 전체 JSON 직렬화 / per-node SHA1 | raw exact change; focus/값/order로 쉽게 바뀜 |
| Helper A11ySnapshotTracker text snapshot | top/bottom chrome 제외 text/ID change detection | post-scroll/no-progress용; locale/dynamic text 의존 |
| Helper A11yStateStore | last focus JSON/last requested index | screen engine 아님; latest focus cache |
| evidence `surface_id/surface_revision/snapshot_id` | scenario transaction scope / observation capture IDs | surface는 `surface:<scenario_tx_id>`; stable screen ID 아님(S15:303) |
| environment fingerprint | app/runtime/schema/locale/device compatibility | run partition에 재사용; UI screen identity 아님 |
| onboarding restored state / QA run history | workflow steps/artifact review 복원 | device navigation/explorer frontier resume 아님 |

일부 semantic equivalent는 이미 존재하지만 통일된 stable screen fingerprint, StateRegistry, visited-state set, replayable source→target navigation graph는 확인되지 않았다. 명칭에 `state`, `fingerprint`, `transition`, `logical_action_id`가 있다고 구현 완료로 계산하지 않는다.

## 8. State Fingerprint Gap

제안: raw observation digest와 dedup screen fingerprint를 분리하고 versioned normalized components와 equality 이유를 함께 보관한다. hash는 설명 가능한 components의 색인이다. hash만 같다고 screen 동일성을 증명하지 않는다.

| 요소 | CURRENT_SOURCE | STABILITY | LANGUAGE_DEPENDENCY | UI_VERSION_DEPENDENCY | COST | RECOMMENDATION |
|---|---|---|---|---|---|---|
| package / activity | FocusSnapshot package, existing dumpsys window collector | package 높음 / activity plugin 공용 가능 | 낮음 | 중간 | cached 낮음 / dumpsys 중간 | scope hard guard; activity optional, missing 명시 |
| selected bottom tab | Global Nav XML selected + resource canonical map | 높음, ambiguous selected 고려 | ID 낮음 / label 중간 | ID map 중간 | XML 추가 수집 높음 | available일 때 mandatory context; focus tab과 구분 |
| selected local tab / pane | local-tab state + XML / selection evidence | 중간 | 중간 | 중간–높음 | 중간 | subpage/pane discriminator; 추측 selected 금지 |
| visible node structure | flat Helper candidates / raw XML | 중간; lazy/merged dynamic 영향 | 낮음–중간 | 높음 | existing tree 낮음 / XML 높음 | structure signature는 viewport/context corroboration |
| stable semantic IDs | resource/class/role/ancestry, card model | 중간; logical ID 공급 제한 | ID 낮음 / semantic label 높음 | 중간–높음 | 낮음–중간 | structural family+role 조합; 개별 ID 필수 규칙 최소화 |
| focused element | actual focus fields / canonical observation | 순간적 | ID 낮음 / speech 높음 | 중간 | 기존 step 낮음 | screen key 제외; object visit/transition evidence |
| scroll / viewport | axis-v1 capability + viewport signatures | viewport 안 중간–높음 | bounds ID 낮음 | layout/device 높음 | dump 중간 | child viewport key; screen key와 분리 |
| overlay / dialog | popup modal evidence / post-click classification | 중간; heuristic일 수 있음 | label 중간–높음 | 중간 | 중간 | overlay layer structural/modal evidence; unknown 유지 |
| navigation context/depth | declared entry/recovery + parent transactions | 실제 depth 아직 미정의 | 낮음–중간 | route 높음 | 기록 낮음 / 복귀 검증 높음 | observed route hint; depth/path 자체를 screen ID에 모두 넣지 않음 |
| live values / announcements | raw/actual native speech, text | 낮음 | 높음 | 중간 | 기존 수집 낮음 | full evidence 보존, semantic identity에는 masked value revision |
| window ID / capture timestamp | focus/evidence 일부 지원 | ephemeral | 낮음 | lifecycle 높음 | 낮음 | observation provenance; durable screen fingerprint 제외 |

**Equality 제안(Phase 2에서 contract 검증 필요):**

| 비교 | 결과 | 판정 근거 |
|---|---|---|
| 동일 화면 반복 수집 | SAME_SCREEN / SAME_VIEWPORT | verified navigation context + stable structural signature |
| focus만 이동 | SAME_SCREEN | focus는 interaction observation; 새 screen 생성 금지 |
| 같은 screen의 scroll 이동 | SAME_SCREEN / DIFFERENT_VIEWPORT | same content scope/container + observed movement / lifecycle evidence |
| dialog/overlay 등장 | DIFFERENT_INTERACTION_STATE | base screen 유지, overlay child state/layer; dismiss 뒤 base 복귀 확인 |
| 같은 plugin의 다른 subpage | DIFFERENT_SCREEN | selected pane/title/structural context + navigation transition |
| 온도 23°C→24°C | SAME_SCREEN / VALUE_REVISION | 같은 role/structure/context; 원본 value는 evidence에 보존 |
| 온도 값 변동으로 버튼 가능 여부가 바뀜 | SAME_SCREEN + ACTION_SET_REVISION | action eligibility 재평가; state key 변경 없이 retry version 관리 가능 |
| loading/empty/error/setup로 interaction 구조 변경 | DIFFERENT_INTERACTION_STATE 또는 UNKNOWN | operational mode가 바뀌므로 모든 text change를 mask하면 안 됨 |
| empty dump / missing context / 다중 selected | UNKNOWN | NEW 또는 SAME로 강제하지 않고 incomplete observation 기록 |

`State → Viewport → Focusable instances`를 권장한다. screen은 navigation/interaction 구조 단위, viewport는 container 위치/visible instance observation 단위다. 여러 scroll container와 overlay를 표현하기 쉽고 Phase 0 stale reconciliation과 연결된다. 단순 `Screen + Scroll Position`의 절대 offset은 모든 Android node에서 제공되지 않으므로 observed viewport signature를 사용하되 offset은 optional이다.

lazy-loaded item 출현을 새 screen으로 자동 등록하지 않는다. 기존 screen의 viewport/candidate-set revision으로 수용하고, pane/subpage 변경과 구분할 신호가 부족하면 UNKNOWN으로 둔다. screen 및 viewport matching confidence는 별도 필드로 유지한다.

## 9. Action Model Gap

분류는 범용 auto discovery 실행 관점이다. 기존 명시적 scenario가 수행하는 허용된 action까지 제거하자는 뜻은 아니다.

| Action | 실제 지원 / source | 분류 | 필요한 계약 |
|---|---|---|---|
| SMART_NEXT / reading focus | client:2685 / Helper pipeline | SAFE_FOR_AUTO_DISCOVERY | target-app/current scope guard; implicit scroll effect 기록; A11y actual proof |
| explicit target focus / FOCUS_IN_BOUNDS | client / RecoveryExecutor / CoverageProbe | SAFE_FOR_AUTO_DISCOVERY | fresh bounds/landing verification; activation으로 오인 금지 |
| click_focused / target touch | client:2066 / Helper click / touch_point | REQUIRES_GUARD | 무엇을 누르는지 semantic classification + fresh target validation |
| activate라는 공통 typed action executor | navigation/click을 각 helper가 조합 | NOT_IMPLEMENTED | transport primitive는 있음; generic action identity/result/safety envelope 없음 |
| vertical scroll forward | client:2092 + verified_scroll:208 | REQUIRES_GUARD | current container/path/axis 지원 + before/after movement proof |
| scroll backward/up | client scroll direction / Helper 지원 | REQUIRES_GUARD | primitive 있음; runner verified forward closure와 동등한 범용 reverse graph adapter 없음 |
| horizontal / pager scroll | Helper directional capability 존재 | REQUIRES_GUARD | pane/state 변화와 content viewport 변화 구분; vertical fallback에 섞지 않음 |
| bottom tab navigation | GlobalNav collect + selected verification | REQUIRES_GUARD | configured destination scope / verified selection / post-state observation |
| More / Menu | scenario overlay allowlist + post-click classifier | REQUIRES_GUARD | More 자체와 메뉴 내부 destructive items 분리 |
| Expand / room / accordion | collapsed room detection / local-tab/CTA navigation | REQUIRES_GUARD | 실제 disclosure로 확인; arbitrary 버튼 activation 금지 |
| Back / navigate up | CF:3469 keyevent 4, bounded recovery | REQUIRES_GUARD | parent-state restore 확인; app exit/unsaved change/context loss 처리 |
| ON/OFF / lock / purchase / delete / reset / account mutation | click primitive로 실행 가능 | UNSAFE | generic exploration deny; 명시적 별도 승인 scenario 범위가 없으면 focus/read만 |

Action key는 `(screen_id, logical_target, operation, direction/container, relevant_action_set_revision)` 형태를 검토한다. retry마다 action_id를 새로 만들면 action dedup이 안 된다. positional instance는 target observation ref로 붙이고 logical binding이 불확실하면 UNKNOWN target으로 activation을 막는다.

## 10. Navigation / Safety Gap

| 현재 navigation 자산 | generic 승격 가능성 | scenario 종속성 / gap |
|---|---|---|
| bottom nav / Global Nav | 높음: discover → select → verify destination | 5개 configured canonical destinations / aliases / resource map; unknown 앱/tab 일반화 검증 없음 |
| root tab selection / context | 높음: existing ID-first + semantic fallback | expected tab/anchor config와 route-specific retry |
| device plugin entry | shared device card route 재사용 | All devices/room handling, stable labels, safe tap avoidance, 4-step search bound |
| Life plugin entry | XML/card matcher adapter | title/description/verify tokens/negative tokens 및 plugin state에 크게 의존 |
| More / overlay | transport + post-click evidence 재사용 | per-scenario allow/block; classifier heuristic; modal registry 필요 |
| local tabs | existing focus/activation/content/exhaustion lifecycle 재사용 | tab signature/label/food-specific Scan/Home logic |
| Back / recovery | bounded primitive + existing recovery checkpoints | expected start target로 돌아감; arbitrary parent state 재구성/verified stack 없음 |

GlobalNav 5/5는 navigation activation과 body traversal을 분리한 좋은 계약이다. 현재 selected destination은 action 없이 검증할 수 있고 tap은 destination selected/transition으로 확인한다. nav row는 `physical_visited=False`다. explorer에서도 `verified navigation destination != physical body focus visit`를 유지한다. 5/5는 이 앱/환경에서의 결과이며 임의 화면 경로를 이미 재구성할 수 있다는 증거가 아니다.

**현재 안전 로직은 부분적으로 존재한다.**

- Overlay: block list 우선, allow list 미설정/빈 경우 차단(S14). Safe의 Ask for help/Remove device 등 scenario-level block도 있다(SC:95).
- Popup: Korean/English safe label 목록과 delete/reset/signout/purchase/pay/agree/allow 등 dangerous 목록을 실제 분류한다. modal evidence, actionable count, Samsung Account Later/setup 구분으로 dismissal을 제한한다(`popup_handler.py`:14, :34, :235).
- Device entry: move-devices/assign-room 영역을 피한 tap point 계산과 verified viewport/complete containment 확인(`device_tab_logic.py`:486, :509, :680).
- Coverage Probe: foreground package/screen on/keyguard/scenario guard가 있지만 **focus probe용 guard**다(S04:883). navigation mutation 허가 정책이 아니다.

범용 safety gap은 모든 activation 경로에서 공통으로 호출되는 classifier/decision ledger, UNKNOWN default deny, external-intent boundary, device controls/doorlock/계정 mutation semantic model, contextual confirmation, policy version과 이유 기록이다. `OK/Done`이라는 label은 안전한 popup dismissal context에서만 기존 힌트로 사용한다. 구매 confirmation의 OK를 label만 보고 허용하면 안 된다.

후속 action safety는 `allowlisted informational navigation / disclosure`, `focus-only control`, `blocked mutation`, `unknown`, `out-of-app`을 구분한다. back은 reversible이라고 무조건 안전 처리하지 않는다. 기존 문서의 Safe Navigation Object 방향과 일치하지만 이번 단계에서 새 policy를 구현하지 않았다.

## 11. Terminal Contract Gap

| Phase 0 contract | explorer 해석 | 그대로 보존할 것 / 새로운 판단 |
|---|---|---|
| COMPLETED | 정해진 traversal/nav scope 완료 | STATE_EXHAUSTED나 GRAPH_COMPLETE로 자동 승격 금지; plugin boundary/special-state completion도 있음 |
| INCOMPLETE_NO_PROGRESS | 현재 executor/observation의 progress 없음 | BLOCKED_NO_PROGRESS / UNKNOWN_REACHABILITY; ACTION_EXHAUSTED 증명 아님 |
| INCOMPLETE_SAFETY_LIMIT | step cap 소진 | GRAPH_BUDGET_EXHAUSTED 또는 LOCAL_BUDGET_EXHAUSTED; pending frontier 보존 |
| INCOMPLETE_SCROLL_UNVERIFIED / SCROLL_ERROR | movement/exhaustion 증명 실패 | observation/action error; exhaustion으로 바꾸지 않음 |
| INCOMPLETE_ERROR | entry/runtime/observation error | ERROR; unknown target state 및 diagnostic 유지 |
| Global Nav COMPLETED 5/5 | configured destination set verified | scoped NAV_DESTINATIONS_VERIFIED; 모든 내부 state explored 의미 없음 |

추가 explorer terminal vocabulary가 필요하다: `STATE_EXHAUSTED`, `ACTION_EXHAUSTED`, `GRAPH_BUDGET_EXHAUSTED`, `UNSAFE_ONLY`, `BLOCKED_NO_PROGRESS`, `ERROR`, `UNKNOWN`. 기존 termination_status는 그대로 저장하고 별도 `exploration_status/reason/scope/pending_safe_actions/unknown_actions/blocked_actions`를 추가한다.

STATE_EXHAUSTED는 valid/stable scoped observations, 현재 actionable/read obligations의 reconciliation, verified viewport exhaustion, 아직 실행할 safe navigation action이 없음이 필요하다. unsafe만 남으면 UNSAFE_ONLY로 기록한다. UNKNOWN action이 남으면 UNSAFE_ONLY도 증명할 수 없다. Graph 완료는 모든 in-scope known safe frontier closure가 필요하며 observed universe와 whole-app completeness를 구분한다.

Root ContentTerminal은 `bottom_tab` content에서만 활성화된다(`content_terminal.enabled`:19, CF:17739). strict visit/semantic readable/stale obligation/verified scroll을 재사용할 수 있지만 plugin completion policy를 그대로 그 구현으로 처리한다고 가정하지 않는다. Step cap 변경으로 terminal을 통과시키는 계획은 없다.

## 12. State / Action / Transition Model

**`object visited != state visited`.** 객체 focus 방문, navigation action 실행, screen 관찰, 검증된 state transition은 서로 다른 ledger다.

| ledger | 현재 구현 수준 | 제안된 최소 의미 |
|---|---|---|
| visited object | 충분한 기반: strict instance ledger, physical/planning/semantic 분리 | `(screen association, viewport observation, instance-v1)`에서 실제 A11y focus proof |
| visited action | 부분: tx/attempt IDs, local-tab activation attempted/content confirmed, GlobalNav attempts | stable action key 별 attempted/succeeded/failed/blocked/no-change/retry count |
| visited state | GlobalNav verified destinations / context hints만 부분 존재 | StateRegistry observation count, equality confidence, explored flags는 별도 |
| visited transition | scroll/global nav/identity temporal evidence가 부분 존재 | actual source/target state + action/attempt + result/evidence causal edge |

현재 EvidenceRuntime `logical_action_id`는 transaction 시작마다 발급되는 capture/action correlation ID다(S15:320). explorer의 durable action dedup key가 이미 구현된 것으로 세지 않는다. `coverage_transition_comparator`는 coverage status before/after 비교이며 navigation graph edge가 아니다.

| entity | 최소 데이터(설계 제안) | 현재 source / missing |
|---|---|---|
| State | state_id, schema/equality version, components, kind, scope, confidence, first/last seen, visit_count | raw context/evidence 있음; stable ID/registry/equality 신규 |
| Viewport | viewport_id, state_id, container identity, axis, signature, revision, observation refs | S11 viewport 재사용; graph association 신규 |
| Object observation | instance_id, logical successor, presence, eligibility, focus proof, captured_at | S09–10; state association 신규 |
| Action | action_id, source_state, target binding, operation, safety classification/reason/version, status, attempt budget | existing commands/tx 일부; stable identity/policy 신규 |
| Transition | transition_id, source_state, target_state nullable, action_id, attempt_id, action_result, effect kind, equality result, evidence, visit_count | tx/action/focus/scroll/nav evidence 있음; state linkage 신규 |
| Frontier/checkpoint | pending safe actions, blocked/unknown, budgets, restore route, last committed sequence | graph scheduling/durable resume 신규 |

Target UNKNOWN/ambiguous인 transition도 저장한다. action_success와 state_changed는 독립이다. focus action은 A→A self-edge + object visit일 수 있고, scroll은 same screen의 viewport edge, overlay open은 base→overlay interaction state, nav는 A→B다. 반복 edge는 attempt evidence를 누적하고 edge count를 갱신한다. 동적 value revision은 edge/observation에 남기되 screen node를 매번 만들지 않는다.

## 13. Scenario Dependency Matrix

canonical source order 32개다. primary class는 **현재 유지보수의 주된 종속성** 기준이며 auto exploration safety 승인이 아니다. `ENTRY_ONLY`도 실제로 공통 traversal engine/Helper policies를 사용한다. `GENERIC_TRAVERSAL_COMPATIBLE`은 shared engine 적용 가능성을 뜻하며 이미 완전한 generic crawl이라는 뜻은 아니다. 아래 SC line은 base definition, cap은 현재 runtime override 반영값이다(S02의 groups에는 추가 cap override 없음).

| # | Scenario | Primary class | cap | 실제 종속성 / source | 내부 discovery MVP 적합도 |
|---|---|---|---:|---|---|
| 1 | global_nav_main | SPECIAL_CASE | 10 | SC:26, S12 destination state ledger; body traversal과 별도 | navigation contract replay 우선 |
| 2 | home_main | GENERIC_TRAVERSAL_COMPATIBLE | 10 | SC:50, QR anchor/overlay policy, root ContentTerminal | root fingerprint/viewport 관찰 우선 |
| 3 | home_safe_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 30 | SC:95, CF:7024 favorite route/optional availability, More allow/block | focus-only; 도움 요청 activation 차단 필요 |
| 4 | life_food_plugin | HEAVILY_HARDCODED | 50 | SC:166, CF:19013 recipe→Home handoff/Scan recovery, local_tab:4134 | 초기 MVP 제외; destination verification limitation |
| 5 | life_air_care_plugin | SPECIAL_CASE | 50 | SC:255, recoverable_precondition, CF air/special-state verification | special/error/setup state corpus 우선 |
| 6 | life_home_care_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 50 | SC:324, negative/special CTA tokens / special_state_handling | focus-only + setup mode 분리 |
| 7 | life_energy_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 50 | SC:400, CF Energy-specific semantic/header handling, activity pane | reverse-only scroll corpus; 후순위 integration |
| 8 | devices_main | GENERIC_TRAVERSAL_COMPATIBLE | 10 | SC:461, runtime shared anchor, All devices/ordering, root closure | root 관찰 우선; sensor order 보존 |
| 9 | device_smoke_sensor_plugin | ENTRY_ONLY | 40 | SC:507, shared device-card route + smoke labels/context | 가장 먼저 focus-only state MVP |
| 10 | device_water_leak_sensor_plugin | ENTRY_ONLY | 40 | SC:544, shared route + water leak labels/context | 가장 먼저; ordering 기준 유지 |
| 11 | device_motion_sensor_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 40 | SC:581, local_tab:2232/:2291 status/chrome whitelist | custom status candidates 보존 후 |
| 12 | device_door_lock_plugin | ENTRY_ONLY | 40 | SC:618, shared card route, lock-specific context | focus-only; lock control UNSAFE |
| 13 | device_air_purifier_plugin | ENTRY_ONLY | 40 | SC:655, shared card route/anchor, common engine | focus-only; power/mode activation 제외 |
| 14 | device_tv_plugin | ENTRY_ONLY | 40 | SC:692, shared route/TV context, slider native speech | 현실적 hybrid 예시; initial activation 제외 |
| 15 | device_washer_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 40 | SC:729, CF:494 CTA token handling, common Helper policy | focus-only; Start control deny |
| 16 | device_humidity_sensor_plugin | ENTRY_ONLY | 40 | SC:766, shared route/context | 값 변화 vs same screen corpus 우선 |
| 17 | device_temperature_humidity_sensor_plugin | ENTRY_ONLY | 40 | SC:803, shared route/context | 온도 value revision 검증 우선 |
| 18 | device_camera_plugin | ENTRY_ONLY | 40 | SC:840, shared route, known cap/partial coverage | scroll/equality 기반 후; coverage 완료 주장 금지 |
| 19 | device_home_camera_plugin | ENTRY_ONLY | 40 | SC:877, shared route, cap/re-entry/partial candidates | 첫 explorer pilot 제외; limitation corpus |
| 20 | device_audio_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 40 | SC:914, CF:493 CTA token, slider/native focus | focus-only; playback/device mutation 제외 |
| 21 | life_main | GENERIC_TRAVERSAL_COMPATIBLE | 50 | SC:951, new-content/QR anchor, Life root/card taxonomy | dynamic cards + viewport corpus |
| 22 | routines_main | GENERIC_TRAVERSAL_COMPATIBLE | 10 | SC:997, root anchor/overlay, shared closure | fingerprint 가능; routine 실행 activation deny |
| 23 | menu_main | GENERIC_TRAVERSAL_COMPATIBLE | 50 | SC:1043, account/header/navigation tiles/overlay | fingerprint 가능; 계정/외부 메뉴 safety 전제 |
| 24 | settings_entry_example | HEAVILY_HARDCODED | 50 | SC:1080, shared Settings route/anchor, CF:495, OneConnect Settings alias policy | 계정/설정 mutation 피하며 replay부터 |
| 25 | life_pet_care_plugin | SPECIAL_CASE | 50 | SC:1116, special CTA/intro/negative tokens, direct-select diagnostic | onboarding/ready equality 검증 후 |
| 26 | life_family_care_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 50 | SC:1191, CF:15159/:15226 Later onboarding recovery | custom recovery+cap; 후순위 |
| 27 | life_plant_care_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 50 | SC:1233, CF:3144 identity mismatch/pre-reset diagnostic | identity guard 보존; focus-only |
| 28 | life_clothing_care_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 50 | SC:1275, CF:3146 identity guard, scroll/native speech, quality FAIL | scroll evidence corpus; product FAIL 유지 |
| 29 | life_find_plugin | ENTRY_PLUS_CUSTOM_TRAVERSAL | 50 | SC:1313, verify/negative tokens, S17 internal-item exclusion | entry vs internal items distinction 우선 |
| 30 | life_video_plugin | ENTRY_ONLY | 50 | SC:1364, XML entry, verify/negative destination tokens | entry adapter 후 focus-only; external/control deny |
| 31 | life_home_monitor_plugin | ENTRY_ONLY | 50 | SC:1408, XML entry/card/context tokens | focus-only; monitoring/control safety 확인 |
| 32 | life_music_sync_plugin | ENTRY_ONLY | 10 | SC:1446, XML entry/token aliases, production cap | 작은 관찰 fixture 적합; activation은 별도 |

Primary 집계: ENTRY_ONLY 12, ENTRY_PLUS_CUSTOM_TRAVERSAL 10, HEAVILY_HARDCODED 2, GENERIC_TRAVERSAL_COMPATIBLE 5, SPECIAL_CASE 3 = 32. Helper에는 OneConnect-specific aliases/header/settings normalization이 공통으로 적용되므로 ENTRY_ONLY 항목도 UI-version 독립을 보장하지 않는다.

**Hybrid 권장:** 32 scenario는 entry/scope/known exceptional policy로 보존한다. `device_tv_plugin entry → StateCollector → focus/viewport audit → reviewed safe informational pane만 내부 exploration`이 현실적인 첫 activation MVP다. 실제 첫 Phase 2 observation corpus는 Smoke/Water/Temperature-Humidity/GlobalNav에서 시작하면 더 단순하다. TV의 전원/volume/slider를 safe navigation으로 활성화하지 않는다.

## 14. Locale Dependency

| 의존 방식 | 현재 예 / source | 한국어↔영어 위험 | 설계 권장 |
|---|---|---|---|
| resource-ID | bottom tab, setting layout, device card IDs | locale 낮음; 앱 release ID 변경 중간–높음 | structural/role fallback과 source confidence |
| class | RecyclerView/ScrollView/pager, button/container | locale 낮음; Compose/custom rendering 전환 위험 | class 단독 key 금지; directional action/semantic structure 병행 |
| structure / bounds | bottom band, container/ancestry, one-to-one alias | locale로 wrap/geometry 달라질 수 있음; fold/rotation 위험 | display/viewport scoped, screen identity는 절대 bounds 의존 최소화 |
| text regex | QR/Home/selected, Life titles, recipe verification | 높음; 예상 언어 밖 token 누락 | label aliases를 hints로; exact dynamic text key 제외 |
| semantic labels | entry_match / stable device labels / local tabs / popup safe labels | 중간–높음; 명칭/번역도 contract 일부 | canonical semantic family + context; unknown safe 판단 차단 |

`label_matcher`와 context resource canonical map은 Korean/English resilience 기반이다. 그러나 Food verify_tokens/recipe detail, HomeCare/Pet special tokens, Motion English status whitelist, popup safe/danger exact labels, local tab label/Scan 예외는 완전한 locale-independent 계약이 아니다. runtime shared Home anchor에는 English regex가 존재하며 downstream alias/ID/context recovery가 이를 보완한다. 개별 regex가 bilingual이라는 이유로 전체 route language independence를 주장할 수 없다.

State core는 focus speech/selected announcement의 번역문을 key에서 제외하고 selected structural evidence/role/route family를 우선한다. screen equivalence의 cross-locale mapping은 명시적 confidence/compatibility contract가 있어야 한다. 기존 environment fingerprint의 locale partition을 제거하거나 ko 결과를 en PASS로 재해석하지 않는다. R1/R2 ID 변화와 locale 변화는 별도 axis로 검증한다.

## 15. Performance / Persistence

Final32 elapsed는 약 8,883초(2시간 28분), evidence 23,024 events, primary attempted 586, confirmed A11y focus moves 477, per-scenario unique visits 합 391, raw rows 487였다(기존 Acceptance §5/14). graph frontier가 추가되면 run 비용이 더 커질 수 있다. 절감률이나 탐색 종료 시간을 이번 분석으로 측정하지 않았다.

| Guard | 현재 기반 | 추가 contract |
|---|---|---|
| state dedup | 여러 raw/viewport signature | normalized screen registry + equality confidence; UNKNOWN retry bound |
| action dedup | local-tab/nav attempts, tx IDs | stable operation+logical target key; action-set revision과 retry budget |
| viewport dedup | stable viewport signature, root attempted_viewports | state+container+axis scope; repeated scroll no-change guard |
| early terminal | existing no-progress / exhaustion / cap | known safe frontier와 unknown/unsafe/unreachable 구분 |
| budget | max_steps, retry/search/probe bounds | run/state/action/depth/viewport/time budget; cap 후 frontier 저장 |
| observation cost | profiler, cached focus / existing tree | 기존 수집 snapshot 재사용; XML/dumpsys는 필요할 때; logcat clearing/correlation 순서 보존 |
| persistence | append-only ledger, Excel checkpoint, portable bundles/CAS | durable StateRegistry/checkpoint sequence/version/atomic write |
| resume | recent runs, onboarding workflow restore | device state restore→verified equality→frontier resume; blind click replay 금지 |

CF:16690의 checkpoint는 주기적 Excel 저장이다. `start_step_index`도 Food handoff 등 같은 process 내 continuation에 사용되며 crash 후 arbitrary device screen/frontier resume를 제공하지 않는다. QA recent runs는 log/summary review이고 baseline store는 approved comparison artifact 관리다. 이것들을 graph checkpoint가 이미 있다고 셀 수 없다.

Artifact CAS와 `observation_bundle`의 atomic write/load/validation 패턴은 registry persistence에 재사용할 수 있다. 탐색용 checkpoint와 approved baseline을 다른 schema/path/lifecycle로 분리해야 한다. registry load는 “관찰 기록 복원”이며 device control history 복원은 후속 Phase 6 작업이다.

### Exploration policy 비교

| Policy | 장점 | TalkBack 비용 / 위험 | 권장 |
|---|---|---|---|
| DFS | plugin 내부에서 깊게 탐색, 짧은 local moves | 깊은 route/cycle/back recovery 비용, 한 branch에 budget 몰림 | shallow scoped subgraph에 제한 |
| BFS | 얕은 screen breadth를 먼저 확보 | roots/plugin 재진입 잦음, pending queue/persistence 필요 | broad route 비교/coverage review 보조 |
| priority-based | verified safe/info/unseen 가치와 비용 반영 | heuristic 편향/starvation | aging + explicit budgets 필요 |
| coverage-driven | 후보 gap을 우선 수집 | model false expected/unknown을 무한 추격 가능 | confidence/current-presence 제한 |
| unseen-first | 동일 viewport의 fresh obligations부터 | unseen=reachable/actionable 오판 가능 | current viewport + strict eligibility 한정 |
| hybrid | local focus/viewport exhaustion 후 safe nav | recovery/order/policy 구현 필요 | 기본 권장 |

권장 hybrid는 `현재 viewport focus obligations → verified content scroll → reviewed safe pane/subpage → bounded local DFS → verified parent recovery` 순서다. state frontier는 coverage value/confidence/recovery cost 기반 priority queue에 두고 depth/time/state limits와 aging을 둔다. destructive controls는 frontier 실행 대상에서 제외하며 blocked evidence로 남긴다. 모든 후보를 FOCUS_IN_BOUNDS로 반복 probing하는 방식은 비용과 실제 TalkBack sequence semantics 때문에 기본값으로 삼지 않는다.

## 16. Observability

| 신규 artifact 제안 | 재사용 가능한 기반 | 필수 차이 |
|---|---|---|
| state_graph.json / registry.json | JSON sidecars / deterministic serialization / CAS | schema/equality version, state/action/viewport refs, pending frontier |
| transition.jsonl | append-only evidence runtime, tx/attempt correlation | source/target state, effect, ACK/actual focus/state change 분리 |
| state/viewport observations | Helper/XML dump/profiler archives | capture epoch, partial/missing fields, source, validity, normalized components |
| state screenshots | existing snapshot/crop files | state observation refs와 image path; screenshot는 identity oracle 아님 |
| candidate/action evidence | inventory, coverage, probe, reconciliation events | freshness/presence, supported operation, safety decision/version/reason |
| terminal/frontier summary | traversal/completeness/QA JSON/Excel | local traversal vs exploration terminal 두 필드; blocked/unknown/budget 잔여 |
| coverage delta | coverage/completeness + coverage_transition_comparator | object/viewport/state/action denominator 분리 |
| equality trace | canonical identity diagnostics 패턴 | SAME/DIFFERENT/UNKNOWN, components, volatile exclusions, collision reason |
| checkpoint manifest | evidence manifest/reconciliation + atomic bundles | last durable sequence, config/equality/policy hash, re-entry verification |

기존 JSONL/summary/Excel/QA metric 의미를 덮어쓰지 않고 sidecar projection으로 시작한다. attempted move / command ACK / confirmed focus moves / recorded rows / unique object visits / observed states / action attempts / verified edges를 분리한다. 기존 artifact audit duplicate/orphan/write failure/transaction closure check를 확장하되 baseline 품질 PASS/FAIL은 유지한다.

## 17. Gap Matrix

Reuse level은 `AS_IS=REUSE_AS_IS`, `ADAPTER=REUSE_WITH_ADAPTER`, `REDESIGN=REQUIRES_REDESIGN`, `N/A=NOT_APPLICABLE` 약어다. 현재 없음은 신규 설계 의미로 REDESIGN에 표시한다.

| CAPABILITY | CURRENT_IMPLEMENTATION | REUSE_LEVEL | MISSING_PIECE | PHASE_TO_IMPLEMENT | RISK |
|---|---|---|---|---|---|
| Object identity | instance-v1 / strict A11y ledger S09 | AS_IS | screen association / epoch projection | 2–4 | 중간: recycled geometry |
| Candidate discovery | Helper focus list, V7, root lifecycle S04–10 | ADAPTER | unified sourced/fresh/action-class envelope | 3 | 높음: merged/unlabeled/unknown |
| Focus executor | SMART_NEXT, explicit focus, client S05–08 | ADAPTER | state-scoped result wrapper; next≠desired target | 4 | 중간 |
| Move reconciliation | selected/actual/ACK/moved/new visit S09 | AS_IS | state transition linkage | 2/4 | 중간: asynchronous landing |
| Scroll | axis-v1, verified movement S11 | ADAPTER | multiple containers/reverse/pager adapters | 4 | 높음 |
| Global navigation | configured destinations / selected verification S12 | ADAPTER | common typed nav action/result | 5 | 중간: ID/locale/context |
| Context verification | ID/alias/token/selected checks S12 | ADAPTER | arbitrary subpage/overlay context contract | 2/5 | 높음 |
| State fingerprint | raw/viewport/env hashes S07/11/16 | REDESIGN | normalized screen components/version/confidence | 2A | 높음: false merge/split |
| State identity/equality | no common screen contract | REDESIGN | screen/viewport/interaction equality | 2B | 높음 |
| Action identity | tx IDs + local tab/nav lifecycle | REDESIGN | stable dedup key + action-set revisions | 3/5 | 높음: unsafe duplicate |
| Transition model | focus/scroll/nav evidence S09/11/12/15 | ADAPTER | source/target state causal model / unknown target | 2/4/5 | 중간–높음 |
| Visited state | destination verified partial S12 | REDESIGN | StateRegistry visit/explored distinction | 2C/6 | 높음 |
| Graph persistence | JSONL/CAS/portable bundles S15/16 | ADAPTER | state/action refs + durable graph transactions | 2C/6 | 중간 |
| Exploration policy | local next/spatial/unseen/guards | REDESIGN | safe frontier / hybrid scheduling / aging | 6 | 높음: explosion/starvation |
| Safe action policy | overlay/popup/device/probe guards S14 | ADAPTER | common deny-by-default semantic/contextual policy | 3 contract / 5 execution | 매우 높음 |
| Terminal policy | strict root closure / scoped traversal S11 | ADAPTER | state/action/graph exhaustion vocab + proof | 4–6 | 높음: false complete |
| Coverage | actual/semantic/missed/unknown/stale S10 | ADAPTER | separate state/action/viewport scopes/denominators | 3/6/7 | 높음 |
| Checkpoint/resume | Excel saves/history/onboarding restore | REDESIGN | durable frontier + verified device re-entry | 6 | 높음 |
| Observability | evidence/profiler/sidecars/QA S15 | ADAPTER | equality/graph/safety/frontier artifacts | 2 onward | 중간 |
| Locale resilience | ID/aliases/structure mixed S01/12/14 | ADAPTER | identity core independence + ko/en corpus | 2/5/8 | 높음 |
| Entry/scope binding | canonical32 / shared routes S01–03 | ADAPTER | scenario as entry/scope envelope; exceptions retained | 7 | 중간–높음 |
| Snapshot completeness | flat focus schema / XML / optional caps S06 | ADAPTER | field availability / capture source / sampling consistency | 2A/3 | 높음 |
| Recovery/parent restore | bounded start recovery S03/19 | ADAPTER | verified parent registry and route stack | 5/6 | 높음 |
| Offline audit label verdict as execution authority | V4/shadow diagnostics S18 | N/A | keep diagnostic-only; strict runtime proof mandatory | 모든 phase | 높음 if promoted |

## 18. Reuse Estimate

engineering 범위 추정이며 코드 줄 수, 이미 검증된 기능 비율, 성능 절감률이 아니다. adapter/integration/새 validation 비용은 new work에 포함한다. UI 표현과 safety 범위 확정에 따라 변한다.

| Layer | current reusable % | new work % | 근거 |
|---|---:|---|
| traversal / focus executor | 약 80% | 약 20% | command/focus/strict reconciliation/visit/evidence 이미 있음; scoped result adapter 필요 |
| candidate / Audit / completeness | 약 60% | 약 40% | discovery/positional lifecycle 재사용; 후보 schema/freshness/action distinction/partial denominator 연결 |
| scroll / viewport | 약 70% | 약 30% | axis/movement/new/persisted evidence; 역방향/multiple containers/state scope 추가 |
| navigation / safety / recovery | 약 40–50% | 약 50–60% | shared entry/nav/allow-block 있음; common safety/arbitrary parent restore/new route classification 부족 |
| observability / artifact plumbing | 약 80% | 약 20% | append-only ledger/sidecar/manifest/profiler/portable bundle; graph/equality projection 신규 |
| screen/state/graph layer | 약 10–20% | 약 80–90% | signature/transaction hints는 있음; equality/registry/frontier/checkpoint/explorer 신규 |
| 전체 bounded hybrid MVP | 약 50–60% | 약 40–50% | executor/candidate 자산이 상당하나 graph/safety 통합 effort가 큼 |

전체값은 각 행의 단순 평균이 아니다. 예시 effort weighting을 executor 35%, candidate 20%, navigation/safety 15%, evidence 10%, state/graph 20%로 놓으면 중간 가정 재사용 약 55–60%다. 확대된 whole-app/locale/version explorer는 신규 safety/restore/equality 검증 부담이 더 크므로 같은 비율을 적용할 수 없다.

## 19. Recommended Target Architecture

아래는 **제안**이며 현재 구현 diagram이 아니다.

```text
Existing Scenario Entry + Scope + Exceptional Policies
                    ↓
State Collector Adapter (existing Helper / focus / XML / context)
                    ↓
State Fingerprint + Equality + Registry [Phase 2]
    ├─ Screen / Interaction State
    ├─ Viewport(s) / container / axis
    └─ Existing instance-v1 observations / strict object ledger
                    ↓
Candidate Adapter [Phase 3]
    ├─ Read / focus candidates
    ├─ Scroll candidates
    ├─ Possible navigation candidates
    └─ Mutation / unknown / out-of-scope candidates
                    ↓
Safe Action Policy + Selector [Phase 5 before activation]
                    ↓
Existing Smart Move / Explicit Focus / Scroll / Navigation Executor
                    ↓
Actual UI Observation + Existing Reconciliation / Evidence Gate
                    ↓
Transition Recorder (ACK / focus / viewport / screen effects separate)
                    ↓
Registry Update + Terminal Evidence + Durable Frontier [Phase 6]
                    ↓
Hybrid scoped explorer → verified parent recovery / next safe action
```

초기 Phase 2 path는 기존 저장된 observation → collector adapter → fingerprint/equality/registry sidecar까지다. 실행 selector/frontier feedback을 production loop에 연결하지 않는다. 이후 통합도 public client/Helper protocol/actual-visit/evidence/terminal authority를 보존하며 `collection_flow`의 side-effect ordering에 adapter를 연결한다. 19k-line orchestrator를 대규모 재작성하는 작업을 전제하지 않는다.

## 20. Phase 2 MVP

**목표: State Model foundation의 의미를 replay로 증명.** production routing/stop/visit 결과는 바꾸지 않는다.

최소 산출물 제안:

1. `StateObservation`: existing payload를 source/availability/provenance와 함께 정규화하는 offline/read-only adapter 계약.
2. `StateFingerprint`: screen/interaction/viewport component sets, schema version, raw digest, excluded volatile fields, confidence.
3. `StateIdentity/Equality`: SAME/DIFFERENT/UNKNOWN과 이유; focus-only/scroll/value/overlay/subpage를 구분.
4. `StateRegistry`: observed states/viewports/observations 등록과 deterministic export/load. explored와 observed를 다른 필드로 둠.
5. `StateTransitionEvidence`: existing request/tx/actual focus/nav/scroll을 state observation refs에 연결; target UNKNOWN 허용.

첫 corpus: GlobalNav five selected destinations, Home/Devices roots, Smoke/Water/Temperature-Humidity focus sequence, Clothing scroll, TV/Audio slider value, Food/Air/Pet special/error states, HomeCamera partial observations. existing outputs의 필요한 fields가 없는 사례는 UNKNOWN으로 평가하고 예측으로 채우지 않는다. 실제 before/after overlay/subpage나 locale pair가 부족하면 **reviewed fixture를 명시적으로 보강**한다. Phase 0 artifact를 읽는 것만으로 모든 equality case가 검증됐다고 하지 않는다.

완료 기준: replay corpus의 기대 equality 판정 전부 일치; focus-only/dynamic-value false split 0; reviewed subpage/overlay false merge 0; invalid/missing/ambiguous UNKNOWN을 NEW/SAME로 승격 0; same-ID/different-bounds object collapse 0; serialize/load replay deterministic; state source→target evidence refs 무결성; 기존 strict visit/terminal/QA regression 의미 보존. 숫자는 future acceptance criteria이며 이번 실행 결과가 아니다.

MVP 제외: graph exploration, automatic arbitrary click, new Helper/APK schema, scenario replacement, full run, runtime config/cap 변경, cross-locale/R1-R2 자동 동등성 승인. 기존 snapshot만으로 activity/selected/overlay 구조가 충분하지 않으면 missing 상태를 보존하고 collector 확장은 별도 후속 scope로 지정한다.

## 21. Phase 2 Subphases

| 단계 | 목적 | 변경 범위 제안 | 검증 | 완료 조건 |
|---|---|---|---|---|
| 2A State fingerprint contract | 데이터 source / stability / scope 정의 | schema, offline observation adapter, volatile field rule, raw/semantic components | Helper flat vs focus vs XML availability, order/permutation, missing/empty, dynamic text fixtures | field provenance/partial status 명확; no guessed selected/activity; 원본 evidence 보존 |
| 2B State identity / equality | screen/interaction/viewport/object 관계 확립 | pure equality module / identity schema / reason codes | focus-only, scroll/cohort, overlay, subpage, temperature, duplicate IDs, recycled bounds, loading/empty, locale pairs | reviewed expected relation 일치; ambiguity UNKNOWN; false merge/split 기준 충족 |
| 2C State registry / persistence | 관찰 registry 등록/export/load | additive state/viewport registry, JSON/JSONL sidecar, version/checksum/atomic write | duplicate insertion, restart/load, truncated file, schema mismatch, unknown target, orphan refs | deterministic round-trip; missing/corrupt fail closed; graph frontier 실행 없음 |
| 2D replay verification | stable Phase0와 foundation 차이를 확인 | replay CLI/report / curated manifest / validation fixtures | existing artifact replay + reviewed missing-case fixtures; 관련 Phase 0 contract regression | zero source contract drift; strict visits/terminal 결과 보존; §20 acceptance case 충족 및 reviewer 확인 |

2C의 reload는 registry 파일 복원까지만 의미한다. device navigation을 다시 실행하는 operational resume는 Phase 6이다. 2D에서 부족한 real before/after evidence 확보가 필요하면 별도로 bounded read-only capture를 계획하고 Full Run/자동 activation을 foundation 검증에 끼워 넣지 않는다.

## 22. Updated Phase 1–8 Roadmap

Phase 번호와 전체 구조는 유지할 수 있다. 단, Phase 3를 **후보 생성만**, Phase 4를 **focus/verified scroll 통합만**으로 제한하고 activation execution은 Phase 5 safety 완료 뒤에 연다. 이렇게 하면 Safety를 Phase 5에 둔 기존 순서가 Phase 3 auto discovery의 무분별한 click으로 이어지는 것을 방지한다.

| Phase | 재검토한 범위 / 산출물 | 진입 또는 완료 gate |
|---|---|---|
| 1 Gap Analysis | 이 문서 / inventory / dependency / MVP definition | baseline/source facts 확인, production 무변경 |
| 2 State Model | observation/fingerprint/equality/registry/transition evidence | reviewed replay corpus / UNKNOWN contract / additive boundary |
| 3 Auto Discovery Integration | unified current-state candidate adapter; action proposal/safety classification 계약 | Audit/Helper candidate distinction, freshness, unlabeled/merged coverage; **activation 없음** |
| 4 Smart Traversal Integration | existing focus/scroll/reconciliation을 state scope로 연결 | object credit 유지, viewport proof, cap/incomplete regression 없음 |
| 5 Safe Navigation | common contextual allow/deny/UNKNOWN policy, nav executor/result, parent restore | destructive/external/device control deny cases, verified landing/recovery; 이 gate 전 automated activation 금지 |
| 6 State Graph Exploration | bounded hybrid frontier, state/action dedup, graph persistence/checkpoint/verified resume | budget terminal / cycles / failed nav / parent mismatch / restart 안전성 |
| 7 Hybrid32 + Auto Exploration | 32 entry/scope 유지하며 내부 explorer opt-in rollout | pilot sensors/TV informational pane → more plugins; custom exemptions/rollback preserved |
| 8 Full Run / R1–R2 Resilience | 기존32 + added state coverage, ko/en/R1/R2/device profiles | artifact/QA consistency, quality FAIL 유지, runtime cost/budget, route/identity resilience |

Phase 3에서 activation까지 하고 싶다면 Phase 5 safe action/navigation contract를 Phase 3보다 먼저 옮겨야 한다. 권장안은 위처럼 후보 생성과 activation을 분리해 numbering과 위험 gate를 명확히 유지하는 것이다.

## 23. Risks

### Phase 0 limitation과 연결

| 기존 limitation | discovery가 개선할 가능성 | 자동 해결되지 않는 부분 / 후속 검증 |
|---|---|---|
| production safety cap | budgets/checkpoint/continued frontier로 partial progress 표현 및 재개 가능 | cap 소진은 completeness 아님; cap을 올리는 것만으로 resolution 불가 |
| Home Camera partial coverage / re-entry | screen/viewport dedup와 state-scoped obligations가 원인 분리에 도움 | cap40/38confirmed moves/23unique/30expected-confirmed/7missed/1unknown/scroll0; terminal reachability 미증명; real replay/scroll contract 필요 |
| Camera / Family partial coverage | action/viewport ledger가 revisit와 new progress 구분 | Camera cap40/20unique/6missed; Family cap50/44unique/4missed/37unknown; candidate 모델과 cap 여전 |
| plugin-specific entry (Food) | resulting state fingerprint가 unexpected destination을 설명하고 route 비교 보강 | 최종 run attempted0/INCOMPLETE_ERROR; entry verification이 실패하면 internal exploration 시작 못 함 |
| Clothing product quality FAIL | 더 많은 states의 accessible label/speech evidence 수집 | 제품의 EMPTY_VISIBLE를 crawler가 고치지 못함; FAIL 및 native speech-positive evidence 둘 다 유지 |
| expected candidate population limitation | fresh scope/viewport association + UNKNOWN/provenance 개선 | Helper filtered tree/merged/custom/Compose/WebView/lazy universe 불완전; whole-screen oracle 없음 |
| Life/Menu/no-progress | separate state/action exhaustion이 왜 막혔는지 설명 | forward 없음이 navigation frontier exhaustion 증명 아님; model unseen=reachable 금지 |
| locale/R1-R2 route fragility | 구조/semantic family 중심 내부 후보 discovery로 개별 ID 유지보수 감소 가능 | entry/identity/safety rule 유지보수 사라지지 않음; 한국어 Acceptance만으로 영어/release 검증 불가 |

추가 주요 위험: shared plugin activity의 false merge, dynamic lists/values의 graph explosion, recycled bounds의 target collision, unsupported role/selected/path의 추정, simultaneous node/focus/XML snapshot의 temporal mismatch, implicit SMART_NEXT scroll의 double counting, unknown activation/doorlock/device mutation, Back의 app exit/unsaved effects, root-only terminal의 잘못된 plugin 확대, multi-container horizontal/vertical 혼동, stale alias의 screen 간 전파, checkpoint 이후 UI/environment mismatch, long-run disk/logcat/observation overhead.

완화 방향은 versioned equality/scope/availability, 기존 strict actual proof 보존, default-deny activation, bounded retry/frontier/time, causal evidence, source-aware snapshot reuse, verified parent restore다. 이번 Phase 1에서는 위험을 해결했다고 주장하지 않고 후속 gate로 지정한다.

## 24. Final Verdict

```ini
VERDICT=READY_FOR_PHASE2_WITH_PRECONDITIONS
READY_FOR_PHASE2=WITH_PRECONDITIONS
PRODUCTION_RUNTIME_CHANGED=NO
STATE_ENGINE_IMPLEMENTED=NO
GRAPH_EXPLORER_IMPLEMENTED=NO
FULL_RUN_EXECUTED=NO
APK_CHANGED=NO
TESTS_EXECUTED_IN_PHASE1=NO
COMMIT_PERFORMED=NO
PUSH_PERFORMED=NO
```

Phase 2를 구현 가능한 foundation 크기로 정의했다. 사전 조건은 §8 equality 범위/UNKNOWN 계약, §20 observation-only boundary, §21 replay manifest 및 판정 기대값을 Phase 2A design에서 승인 가능한 형태로 확정하는 것이다. 아직 arbitrary state graph explorer를 실행할 readiness는 아니다. 이를 이유로 foundation 작업까지 불가능하다고 판단할 필요는 없다.

기존32 entry와 traversal 자산을 유지한다. 객체 유지보수의 일부를 dynamic candidate adapter로 옮길 수 있지만 entry/safety/exceptional UI와 product 품질 판정의 유지보수는 계속 필요하다. Phase 0 stable acceptance와 incomplete/FAIL evidence는 변경하지 않았다.

## 25. Git State

분석 branch를 생성했다. tracked production/config/test 파일 변경과 staging은 없다. 신규 파일은 이 보고서 하나다. 기존 unrelated `out/`는 읽기/쓰기 대상으로 삼지 않고 보존했다.

```text
$ git branch --show-current
feature/phase1-state-auto-discovery-gap

$ git rev-parse HEAD
d42970272ea5002b8659a625c5799471f4127311

$ git rev-parse origin/main
d42970272ea5002b8659a625c5799471f4127311

$ git status --short
?? docs/design/phase1-state-auto-discovery-gap-analysis.md
?? out/

$ git diff --stat
(empty)

$ git diff --name-only
(empty)
```

`git diff --stat`는 untracked 보고서를 포함하지 않으므로 빈 출력이다. 보고서는 worktree에만 두었고 add/commit/push하지 않았다. production config SHA256(분석 전/후):

```text
6dd5d8a191d21e4366ed2513627d97b37515a1e2ae9c2ed342b8d2317fecb964
```
