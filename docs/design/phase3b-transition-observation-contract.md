# Phase 3B — Transition Observation Contract

검증일: 2026-10-05 / branch: `feature/phase3b-transition-observation`

## 1. Verdict

**PASS_WITH_LIMITATIONS**. 기존 controlled action의 전후 관찰을 진단 artifact로 연결한다.
Full Python: **2,979 passed / 0 failed / 0 errors / 1 skipped**.
Phase 2/3A/3B regression: **306 passed / 0 failed / 0 errors**.
실단말 13 transition에서 binding mismatch, ID collision, unsafe binding, unexpected churn은 모두 0이다.
Plugin 및 동적 Home 재결합의 unresolved 증거는 아래에 별도로 기록한다.
`READY_FOR_PHASE3C=YES`. Phase 3C 구현은 하지 않았다.

## 2. Phase 3A Inputs

Source of truth:

- [Phase 1 architecture](phase1-state-auto-discovery-gap-analysis.md)
- [Phase 2 closure](phase2-state-model-closure.md)
- [Phase 3A report / churn closure](phase3a-auto-discovery-integration.md)

Phase 3A closure는 `PASS_WITH_LIMITATIONS`, original churn은
`NON_REPRODUCED_TRANSIENT / UNKNOWN_ORIGINAL_SECOND_OBSERVATION_MISSING`였다.
이를 수정 완료나 원인 확정으로 변경하지 않았다. 기존 2,927 Python passed와
254 Phase 2/3A passed를 baseline으로 사용했다.

Publication을 먼저 완료했다:

```ini
PHASE3A_COMMIT=f2427770c654c2f6acf634cdc3a90e747de56ec2
PHASE3A_BRANCH_PUSH=SUCCESS
PHASE3A_MAIN_MERGE=SUCCESS_FAST_FORWARD
MAIN_PUSH=SUCCESS
HEAD_ORIGIN_MAIN_MATCH=YES
```

Audited 5 files만 단일 commit에 포함했다. Feature branch push 후 main pull
`--ff-only`, merge `--ff-only`, main push를 수행했다. 새 Phase 3B branch의 시작점은
main/origin/main과 동일하다. 이 보고서의 원래 검증 종료 시점에는 Phase 3B 파일이
untracked였고, 아래 별도 publication 절차는 아직 실행되지 않은 상태였다.
[Publication gate](../../output/phase3b_transition_20261005/publication_gate.json).

## 3. Goals / Non-goals

외부 caller가 이미 결정하고 실행한 action을 `prepare → caller executes → complete`
bracket으로 기록한다. Source fingerprint/Registry/candidate와 결과 관찰을 연결한다.

Action 선택·실행, autonomous activation, graph, DFS/BFS, scheduling, safe navigation,
destructive action, scenario replacement, traversal ordering/termination/QA verdict 변경은 없다.
Production runtime/config, Helper/APK, frontend를 변경하지 않았다.

## 4. Existing Reused Evidence

| Authority | Reuse |
|---|---|
| State observation / fingerprint | `build_state_observation` |
| State equality | `evaluate_state_equality`, `VerifiedScrollEvidence` |
| Registry | `StateRegistry.observe/load/save` |
| Candidate inventory | `build_discovery_snapshot`, 기존 node normalization |
| Command ACK | `diagnostics.classify_command_ack` |
| Strict physical focus | `focus_instance` + `focus_reconciliation.reconcile_focus` |
| Scroll producer | `verified_scroll`, `scroll_reliability.transition`, axis-v1 |
| Root navigation | `global_navigation.discover/current/verify_transition`, 기존 center tap |
| Plugin entry | 기존 structural collection, visible card selector, `_tap_device_card_safe`, `verify_context` |
| Back | 기존 `press_back_and_recover_focus` |

관찰기는 pure evidence projection만 수행한다. Reconciliation의 visit/progress advisory를
적용하는 함수나 visit ledger는 호출하지 않는다.

## 5. Transition Model

새 파일:

- `tb_runner/transition_observation.py`: immutable `ControlledAction`, `PreparedTransition`,
  `TransitionObservation`, diagnostic `TransitionObserver`, JSONL writer.
- `tools/state_transition_diagnostic.py`: 저장된 raw/action/ACK/evidence replay CLI. ADB/executor 없음.
- `tests/test_transition_observation.py`: contract/negative/replay 테스트.
- `tests/test_state_transition_diagnostic.py`: offline CLI, namespace, overwrite 방지 테스트.
- 본 보고서.

모델은 source/result state ID, candidate ID, action kind/target, occurrence ID,
action 시작/종료 시간, raw/normalized ACK, strict focus status/actual target,
viewport change, fingerprint references, 전체 Phase 2 equality, outcome,
evidence refs/provenance, `visit_credit=0`을 보존한다.
JSON-backed frozen dataclass와 독립적인 `to_dict()` 사본으로 caller mutation을 차단한다.

## 6. Transition Identity

Caller의 필수 `occurrence_id`는 실제 controlled action occurrence를 구분한다.
Random UUID나 wall-clock timestamp를 identity의 유일한 근거로 사용하지 않는다.

`semantic_hash`는 state IDs, 실제 kind, bound candidate/target, normalized ACK,
strict focus before/after identity와 status, equality/viewport/outcome을 포함한다.
`transition_id`는 occurrence ID와 이 canonical semantic document의 SHA-256이다.
Timestamp, ACK request ID, raw ACK repr, capture observation ID, evidence path는 제외한다.
Unresolved endpoint에는 timestamp를 제외한 structured fingerprint discriminator를 사용한다.

`transition_type_hash`는 occurrence와 구체적인 focus before/after instance를 제외한다.
동일 occurrence의 동일 replay는 count를 증가시키지 않는다. 동일 occurrence의 다른
semantic 결과는 churn conflict로 거부한다. 동일 ID의 다른 semantic document는 collision으로 거부한다.
서로 다른 실제 occurrence는 같은 type이라도 서로 다른 transition ID를 가진다.

Registry ID는 persisted namespace의 allocation 결과다. Replay order invariance는 같은
저장된 Registry를 사용한 조건이며, 새로운 Registry의 다른 최초 발견 순서까지 global ID가
같다고 주장하지 않는다.

## 7. Outcome Contract

| Outcome | Contract |
|---|---|
| `STATE_CHANGED` | Phase 2 DIFFERENT + 양 endpoint resolved + IDs 다름 |
| `VIEWPORT_CHANGED` | Phase 2 SAME + 동일 ID + viewport unequal |
| `FOCUS_ONLY` | SAME/동일 viewport + 양쪽 strict A11y proof + 실제 instance 이동 |
| `ACTION_FAILED` | 관찰된 state/viewport/confirmed focus 변화 없음 + ACK FAIL |
| `SAME_STATE` | 같은 state/viewport; 확정 focus 이동 없음. Focus UNKNOWN을 False로 바꾸지 않음 |
| `AMBIGUOUS_RESULT` | source/result unresolved, equality ambiguous 또는 binding 불일치 |
| `ERROR` | post-action observation 없음; 성공 ACK가 있어도 결과 없음 |

Actual state/viewport/focus change를 ACK FAIL보다 우선한다. ACK success는 이동 증명이 아니다.
`actual_focus_moved`는 True/False/None을 구분한다. Unknown focus에서 ACTION_FAILED는
관찰된 변화가 없다는 bounded 분류이며, 화면 전체가 전혀 변하지 않았다는 증명이 아니다.

## 8. Source State Binding

`prepare`에서 실제 raw observation으로 fingerprint와 Registry resolution 및 DiscoverySnapshot을 만든다.
Caller의 임의 state ID는 받지 않는다. Source unresolved면 definitive binding 및 candidate binding을 만들지 않는다.
Prepared source는 생성한 observer만 complete할 수 있다. Foreign/replaced source는 거부한다.

## 9. Action Binding

현재 source snapshot의 action kind, 선언한 target 또는 requested candidate ID로만 연결한다.
FOCUS_NEXT는 기존 untargeted singleton이며 원하는 특정 object에 도착한다고 약속하지 않는다.
Bottom Nav는 선언한 destination, scroll/click/focus target은 현재 관찰된 positional identity를 사용한다.
Kind만으로 여러 target 중 하나를 선택하지 않는다. 동일 resource ID의 다른 bounds를 합치지 않는다.

Unavailable/foreign/missing/ambiguous candidate는 `UNMAPPED_CONTROLLED_ACTION`, candidate ID null이다.
실제 executed target evidence가 요청과 모순되면 mapping을 해제하고 양쪽을 보존한다.
선택한 focus target과 실제 focus target이 다르면 requested target과 actual observed target을 모두 기록한다.
CLICK mapping은 activation의 안전성 승인이나 원하는 plugin 도착의 증명이 아니다.

## 10. Result State Binding

Post raw로 새 observation/snapshot을 만들고 같은 Registry 및 Phase 2 equality를 사용한다.
새 equality를 구현하지 않았다. Scroll continuity는 기존 producer transition을 Phase 2 validator로 검증한다.
Invalid continuity는 rejection reason을 기록하고 merge 근거에서 제외한다.
Known IDs와 equality가 서로 모순되면 result ID를 null로 quarantine하고 mismatch count를 증가시킨다.

## 11. Focus-only Transition

실단말 첫 Home SMART_NEXT: tab title → mapview layout, 양쪽 A11y flag True.
Home state ID 유지, viewport unchanged, `FOCUS_ONLY`, moved=True, visit credit=0.

두 번째 SMART_NEXT: before mapview의 A11y flag False/input focus True,
after more-menu의 A11y flag True. ACK moved이지만 before physical proof가 없어
`SAME_STATE`, moved=None, focus status UNAVAILABLE로 기록했다.
처음 smoke harness의 모든 focus를 FOCUS_ONLY로 기대한 assertion은 여기서 중단됐다.
이 capture를 보존하고 현재 단말 상태에서 나머지 case만 재개했다. Contract/assertion을
완화해 이동으로 인정하지 않았다. 서로 다른 actual proof가 type 차이를 설명한다.

## 12. Scroll Transition

Home down은 기존 `verified_scroll`, restore는 기존 container-targeted `client.scroll('up')`을 사용했다.
양방향 모두 legacy viewport movement와 axis-v1 capability를 보존하고
Phase 2 `VerifiedScrollEvidence`로 연결했다.
Source/result 모두 Home `state:00000001`, viewport_changed=True, `VIEWPORT_CHANGED`였다.
Attempt/ACK만으로 continuity를 생성하는 negative fixture는 unresolved로 남는다.

## 13. Global Nav Transition

Home→Devices, Devices→Life, Life→Home, Home→Devices 반복, Devices→Home,
plugin 준비용 Home→Devices는 모두 mapped `STATE_CHANGED`였다.
Selected-tab before/after, destination verification, viewport evidence를 기존 producer로 기록했다.
Home/Devices/Life IDs는 각각 `phase3b-device:state:00000001/2/3`이다.
Home→Devices 세 occurrence는 동일 transition type hash였다.

## 14. Plugin Transition

현재 Devices collection에서 기존 visible selector가 습도센서 card를 선택했고,
기존 safe tap을 사용했다. Source CLICK candidate는 정확한 card bounds로 mapped됐다.
실제 activity는 `.webplugin.WebPluginActivity`, 화면 제목은 **진동 센서**였다.
기존 습도센서 context verifier는 **False**를 반환했다. 이를 성공적인 습도 plugin verification으로 바꾸지 않았다.

Plugin capture에는 selected root/navigation context가 없어 Phase 2 Registry가 result를 unresolved로 유지했다.
Transition은 mapped CLICK + `AMBIGUOUS_RESULT`, result ID null, definitive binding False다.
뒤로 이동은 기존 back transport로 Devices에 복귀했지만 unresolved source에서 시작하므로
unmapped BACK + `AMBIGUOUS_RESULT`였다. Synthetic selected tab이나 plugin state ID를 만들지 않았다.
Optional plugin의 desired-context verification은 미완료 limitation이다.

## 15. Failure / Reconciliation

Failed ACK + confirmed actual focus move는 FOCUS_ONLY로 보존한다.
Failed ACK + observed unchanged strict focus/state는 ACTION_FAILED다.
Input-only/false-screen fallback/conflicting flags는 physical focus proof가 아니다.
초기 compile/test 실패 1건은 invalid-proof fixture가 raw viewport dictionary와 alias를 공유한 문제였다.
Fixture evidence를 deepcopy해 독립적으로 손상시켰고 negative assertion을 유지했다.

마지막 plugin cleanup의 Home selected/destination verification은 True였다.
하지만 카메라 `device_status`의 `마지막 업데이트: 10/05 4:46 AM → 9:16 AM` 때문에
기존 Home representative와 secondary semantics가 달랐다. Fingerprint hash/viewport는 같아도
Phase 2 equality는 `COARSE_CORE_MATCH_WITHOUT_SECONDARY_CONTINUITY / AMBIGUOUS`였고
Registry가 기존 Home에 merge하지 않았다. Devices→관찰된 Home의 직접 equality는 DIFFERENT지만
result Registry unresolved이므로 transition은 AMBIGUOUS_RESULT다.
[Exact secondary diff](../../output/phase3b_transition_20261005/device1/home_return_variability.json).

## 16. Artifact Format

Authoritative final artifact:
[state_transitions_final.jsonl](../../output/phase3b_transition_20261005/device1/state_transitions_final.jsonl).
Final code로 saved actual before/action/ACK/after를 replay했다. 원본 device artifacts와
중간 projection은 `device1/state_transitions.jsonl`, `brackets.json`, 각 case JSON에 보존했다.
13 original transition ID를 모두 유지했다. 최종 artifact에 full raw XML/전체 candidate tree를 복제하지 않는다.
Fingerprint/snapshot hash와 evidence reference, 최소 actual focus target만 기록한다.

Offline invocation:

```powershell
python -m tools.state_transition_diagnostic --input saved_brackets.json --registry-in saved_registry.json --registry-out replayed_registry.json --output state_transitions.jsonl
```

CLI는 기존 output overwrite를 거부하며 동일 occurrence의 동일 replay를 중복 append하지 않는다.
Evidence refs는 device1 run directory를 기준으로 해석한다.
[Artifact audit](../../output/phase3b_transition_20261005/artifact_audit.json): PASS, 48 reference files checksum 검증.

## 17. Tests

| Task | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|
| Full Python, 최종 code | 2,979 | 0 | 0 | 1 |
| Phase 2/3A/3B related | 306 | 0 | 0 | 0 |
| 새 Phase 3B tests (위 suite에 포함) | 52 | 0 | 0 | 0 |

Full suite는 기존 `out/`에 상대 경로 artifact를 쓰는 테스트 때문에 byte-identical source copy에서 실행했다.
679 source files와 기존 local baseline inputs를 사용했고 failing test/source를 제외하지 않았다.
원본 unrelated `out/` 615개는 검증 전후 path/hash 동일이다.
기존 1 skipped는 xlsxwriter dependency 부재에 따른 thumbnail test이며 새 skip이 아니다.
Full 76.95초, related 10.43초.

요구된 15 contract case를 모두 포함한다: deterministic input, timestamp exclusion, focus-only,
verified scroll, root nav, failed ACK unchanged/moved, requested/actual mismatch,
ambiguous source/result, stable candidate ID, input focus exclusion, byte-stable serialization,
persisted Registry replay order, meaningful semantic state change.
추가로 source forgery, unavailable/unmapped actions, same-RID instances, executed-target contradiction,
hash collision, duplicate occurrence/churn rejection, inconsistent Registry quarantine, ERROR를 확인했다.

Evidence: [full XML](../../output/phase3b_transition_20261005/full_python_final.xml),
[full log](../../output/phase3b_transition_20261005/full_python_final.log),
[related XML](../../output/phase3b_transition_20261005/related_regression.xml),
[source manifest](../../output/phase3b_transition_20261005/regression_source_manifest.json).

## 18. Device Smoke

SM-F741N / R3CX40QFDBP, USB 연결, 배터리 63% 확인. 기존 Helper service 사용, APK 설치/빌드 변경 없음.
Full 32를 실행하지 않았다. Fixed smoke caller가 기존 action을 실행하고 sidecar는 관찰만 했다.

| Case | Source → result | Outcome | Mapping |
|---|---|---|---|
| Home focus 1 | Home → Home | FOCUS_ONLY | Mapped |
| Home focus 2 | Home → Home | SAME_STATE, focus unavailable | Mapped |
| Home down | Home → Home | VIEWPORT_CHANGED | Mapped |
| Home restore | Home → Home | VIEWPORT_CHANGED | Mapped |
| Home→Devices #1 | Home → Devices | STATE_CHANGED | Mapped |
| Devices→Life | Devices → Life | STATE_CHANGED | Mapped |
| Life→Home | Life → Home | STATE_CHANGED | Mapped |
| Home→Devices #2 | Home → Devices | STATE_CHANGED | Mapped |
| Devices→Home | Devices → Home | STATE_CHANGED | Mapped |
| Plugin setup | Home → Devices | STATE_CHANGED | Mapped |
| Humidity requested / vibration observed | Devices → unresolved | AMBIGUOUS_RESULT | Mapped CLICK |
| Plugin back | unresolved → Devices | AMBIGUOUS_RESULT | Unmapped BACK |
| Final Home cleanup | Devices → unresolved observed Home | AMBIGUOUS_RESULT | Mapped |

Home selected 상태로 복귀했다. Optional plugin/cleanup은 성공 기대 assertion에서 중단된 원본 log를
보존하고 raw 증거에 따라 limitation으로 판정했다. Mandatory focus/scroll/root cases는 완료했다.
[Device summary](../../output/phase3b_transition_20261005/device1/final_device_summary.json).

## 19. Stability Metrics

```ini
TOTAL_TRANSITIONS_OBSERVED=13
MAPPED_ACTION_TRANSITIONS=12
UNMAPPED_CONTROLLED_ACTIONS=1
AMBIGUOUS_SOURCE_COUNT=1
AMBIGUOUS_RESULT_COUNT=3
STATE_BINDING_MISMATCH_COUNT=0
TRANSITION_ID_COLLISION_COUNT=0
UNSAFE_TRANSITION_BIND_COUNT=0
UNEXPECTED_TRANSITION_CHURN_COUNT=0
```

Unique action occurrences가 denominator다. Mapped + unmapped = total.
Ambiguous source는 source state ID null, ambiguous result counter는
`outcome=AMBIGUOUS_RESULT`인 transition 수다. Source ambiguity만 있는 BACK도 여기에 포함되며,
이 두 counter는 서로 배타적인 partition이 아니다. 실제 null result state ID는 2건이다.
Unexplained conflicting replay는 0이다. Dynamic real occurrences의 다른 actual proof는 expected variability다.

Exact byte replay 13/13, duplicate serialization 13/13, reversed/interleaved replay IDs 13/13,
reordered node input IDs 13/13, timestamp/request-ID 변화 IDs 13/13.
Home→Devices repeated type 3/3 stable. Persistence reload도 byte-identical이다.

## 20. Performance

Actual saved device observations에서 기존 authority wrapper로 측정했다. 아래는 per-call 평균이다.
Prepare/complete 합계 약 876ms는 ADB capture/action/Registry file loading을 제외한 diagnostic 비용이다.
Live mandatory run에서는 prepare 479ms, complete 404ms, capture 4,339ms 평균이었다.

| Stage | Calls | Mean ms | Max ms |
|---|---:|---:|---:|
| Pre/post StateObservation builder | 26 | 105.50 | 141.32 |
| Snapshot 내부 fingerprint builder | 26 | 109.26 | 161.16 |
| Candidate snapshot | 26 | 90.80 | 142.01 |
| 기존 Audit inventory | 26 | 7.77 | 11.07 |
| Registry resolution | 26 | 106.37 | 149.00 |
| Action strict focus evidence | 13 | 0.26 | 0.38 |
| Post State Equality | 13 | 12.76 | 18.59 |
| Transition serialization | 65 | 0.86 | 4.44 |
| Prepare total | 13 | 442.24 | 570.44 |
| Complete total | 13 | 433.37 | 558.42 |

기존 snapshot API도 fingerprint를 생성하므로 source/post observation builder와 snapshot 내부 builder
비용이 각각 포함된다. Stage 비용은 nested total과 중복되므로 행을 전부 합산하면 안 된다.
단일 device의 작은 diagnostic run 수치이며 production hot-path latency로 일반화하지 않는다.
Registry persistence/loading과 retained evidence의 장기 성장 비용은 별도 stress 범위다. 성능 최적화는 하지 않았다.

## 21. Known Limitations

- XML/Helper/focus/window capture는 순차적이며 atomic snapshot이 아니다. 실제로 한 pre-focus flag가 False였다.
- Phase 2는 selected root/context가 없는 plugin을 unresolved로 남긴다. 이번 optional desired plugin은 실제 title도 불일치했다.
- Camera last-update label은 fingerprint normalization과 secondary equality의 관찰 범위가 달라 Home 재결합을 unresolved로 만들었다.
  이 producer/equality 문제를 Phase 3B에서 의미 없는 merge나 normalization 확대로 숨기지 않았다.
- Positional candidate identity는 해당 state/viewport에서만 유효하다. 이동한 card의 전역 entity identity를 보장하지 않는다.
- Overlay absence와 partial-tree equality 한계는 Phase 2 계약 그대로다.
- Replay order invariance는 persisted Registry namespace를 전제로 한다.
- 대규모/장시간 diagnostic retention, multi-device, dynamic overlay/plugin stress는 수행하지 않았다.
- 기존 Python skip 1개가 남았다. Helper는 변경되지 않아 추가 APK build가 이번 단계에 필요하지 않았다.

## 22. Phase 3C Preconditions

| Gate | Result |
|---|---|
| Deterministic transition representation | PASS |
| Unsafe source/target binding 없음 | PASS, 0 |
| Focus-only / strict flag protection | PASS |
| Same-state verified scroll | PASS |
| Controlled root navigation | PASS |
| ACK vs actual separation | PASS |
| Phase 2/3A regressions | PASS |
| Full Python 0 failed / 0 errors | PASS |
| Production/runtime/config/Helper isolation | PASS |

`READY_FOR_PHASE3C=YES`: transition stability/ambiguity stress/snapshot cross-check를 진행할 수 있다.
이는 autonomous exploration 또는 Phase 4 traversal activation의 승인이 아니다.
Optional plugin identity와 dynamic secondary-label ambiguity를 이후 closure/stress에서 다뤄야 한다.
Phase 3C 구현은 하지 않았다.

## 23. Final Verdict / Git

```ini
PHASE3_BRANCH=feature/phase3b-transition-observation
PHASE3B_VERDICT=PASS_WITH_LIMITATIONS
PYTHON_TEST_RESULT=2979_PASSED_0_FAILED_0_ERRORS_1_SKIPPED
PRODUCTION_RUNTIME_CHANGED=NO
PRODUCTION_CONFIG_CHANGED=NO
HELPER_CHANGED=NO
READY_FOR_PHASE3C=YES
```

Production config SHA-256:
`6dd5d8a191d21e4366ed2513627d97b37515a1e2ae9c2ed342b8d2317fecb964`.
Phase 3A published 7 files의 post-checkout bytes도 그대로 유지했다.

`git branch --show-current`:

```text
feature/phase3b-transition-observation
```

`git status --short`:

```text
?? docs/design/phase3b-transition-observation-contract.md
?? out/
?? tb_runner/transition_observation.py
?? tests/test_state_transition_diagnostic.py
?? tests/test_transition_observation.py
?? tools/state_transition_diagnostic.py
```

이후 사용자가 Part A publication을 명시적으로 허용하여 위 5개 파일만 commit했다:

```ini
PHASE3B_COMMIT=f89836a36ed12b2749f7f8203ead0d8dcebd4a5d
PHASE3B_BRANCH_PUSH=SUCCESS
PHASE3B_MAIN_MERGE=SUCCESS_FAST_FORWARD
MAIN_PUSH=SUCCESS
HEAD_ORIGIN_MAIN_MATCH=YES
```

`out/`은 commit 대상에서 제외했다. 최신 `main`을 fast-forward한 뒤
`feature/phase3c-transition-stability-closure`를 만들었다.
위 final assessment 당시의 untracked git snapshot은
[final_git_state.txt](../../output/phase3b_transition_20261005/final_git_state.txt)에 남겨 둔다.
[Scope audit](../../output/phase3b_transition_20261005/scope_audit.json)는 Phase 3B publication 전
runtime/config/Helper, out/ hashes 및 당시 allowed file scope를 기록한다.
