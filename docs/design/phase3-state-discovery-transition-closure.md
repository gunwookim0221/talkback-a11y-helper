# Phase 3 — State Discovery and Transition Closure

Run date: 2026-10-05
Device: SM-F741N (`R3CX40QFDBP`)
Phase 3B publication: `f89836a36ed12b2749f7f8203ead0d8dcebd4a5d`

## 1. Final Verdict

**PHASE3_PASS_WITH_LIMITATIONS**, with **Home blocker closure FAIL** and `READY_FOR_PHASE4=NO`. The camera overlay is now classified **SEMANTIC_CAMERA_STATE** from installed APK domain-event and actual render paths. Its semantics are preserved; no identity filter is applied. Reliable ABSENT parent TalkBack speech is captured, but PRESENT comparison and safe Home substate observation remain missing. Current 25 targeted Home captures resolve 0/25; retained acceptance still maps 0/10 Home actions with 4/4 ambiguous core returns. Standard Python regression passes 3,074 tests and related Phase 2/3 regression passes 401, with zero failures/errors. See §25 for the current decision; §24 retains the previous UNKNOWN evidence gate and §§3–23 the earlier findings.

## 2. Phase 3 Scope

Phase 3C audited State → Candidate → controlled Action → Transition → Result State, repeated observations, saved evidence, process restart and device behavior. It added only a diagnostic auditor and focused tests. No Phase 4 action selection or autonomous traversal was implemented.

Phase 3B was published first: its five audited files were committed on `feature/phase3b-transition-observation`, pushed, fast-forward merged to `main`, and pushed. The 3B commit is the base of `feature/phase3c-transition-stability-closure`. Phase 3C remains uncommitted, unpushed and unmerged for review.

## 3. Phase 3A Summary

Phase 3A recorded 44 observations, 80 comparisons and 36 passive observations across Home, Devices and Life. Its prior closure gate was `PASS_WITH_LIMITATIONS`: 2 expected candidate changes, 0 unexpected changes, state binding mismatches, candidate ID collisions or unsafe state binds. The recorded scroll transition remained evidence-backed, and persisted Registry reload was byte-identical.

## 4. Phase 3A Churn Closure

The original historical churn incident remains `NON_REPRODUCED_TRANSIENT`; its actual cause is `UNKNOWN_ORIGINAL_SECOND_OBSERVATION_MISSING`. No engine fix was applied. Phase 3C replay rebuilt all 44 saved snapshots byte-identically in each of two fresh processes, and each persisted replay Registry reloaded byte-identically. The original incident is not claimed as fixed.

## 5. Phase 3B Summary

Phase 3B published at commit `f89836a36ed12b2749f7f8203ead0d8dcebd4a5d`; branch push, fast-forward merge to main, main push and `HEAD == origin/main` all succeeded. Original device run: 13 transitions, 12 mapped, 1 unmapped, 1 ambiguous source and 3 ambiguous results. State binding mismatch, transition ID collision, unsafe transition bind and unexpected transition churn were all zero.

The Phase 3B report was amended in this worktree only to correct its historical publication status and the audited file count. Its frozen runtime contract was not changed.

## 6. Phase 3C Goals

The fixed SM-F741N matrix used the persisted Phase 3B Registry seed. It captured 3 passive Home observations and 16 controlled transitions: 2 focus requests, 2 scroll-down/restore pairs and 2 repeated bottom-navigation cycles. Full 32-scenario execution was not part of this stability matrix.

## 7. Cross-Layer Consistency

All 29 Phase 3B and 3C transitions were rebuilt from saved before/action/ACK/after brackets and matched their frozen transition documents and IDs exactly. The auditor checked transition source against its source snapshot, mapped candidate membership and action kind, result fingerprint against the result observation and snapshot, outcome against equality/viewport/focus evidence, ACK reconciliation, and semantic hash/ID replay.

There were **0 cross-layer contradictions**. Each of the eight explicit contradiction counters in the final metrics is zero.

Regression: all 24 Phase 3C focused tests passed; they are included in the 330 passing Phase 2/3 related regression tests. The full Python suite passed with 3,003 passed, 0 failed, 0 errors and 1 existing skipped test. The skip is the pre-existing thumbnail test requiring the unavailable `xlsxwriter` dependency.

## 8. Replay Stability

Two fresh Python processes independently replayed the Phase 2 curated set (42 cases), Phase 2 actual artifact set (98 cases), Phase 3A observations (44), Phase 3B transitions (13) and Phase 3C transitions (16). Phase 2 reports and Phase 3A Registry artifacts were byte-identical between processes. Phase 3B and 3C transition documents reproduced exactly 13/13 and 16/16 times in both runs. The combined closure report was byte-identical between runs.

`TOTAL_REPLAY_CASES=213` counts those unique saved cases once: 42 + 98 + 44 + 29. It does not multiply the denominator by the second process replay.

## 9. Process Restart Stability

The Phase 2 curated and actual reports match their previously persisted restart metrics. The Phase 3A Registry reloaded byte-identically in both closure processes. A focused test also saves a Registry, reloads it, and verifies the repeated transition ID and transition type hash.

## 10. Focus-Only Stability

Of 2 real-device focus requests, the first had strict focus-movement proof and the second had no reliable before-focus identity. Both remain `AMBIGUOUS_RESULT` because Home has no state ID; the second is not credited as movement. The two observed proof variants are classified as expected variability, with no transition churn.

## 11. Scroll Stability

Both real-device scroll-down actions changed the viewport signature; each matching restore returned to the exact initial viewport signature. ACKs reported `scrolled` for all four actions. The transitions remain safely ambiguous because their Home source state is unresolved. Candidate set hashes vary across Home observations while there is no resolved Home state, so they are not compared as if they belonged to one stable state.

## 12. Root Navigation Stability

Both 5-action cycles followed the observed selected roots `Home → Devices → Home → Devices → Life → Home`; every navigation ACK reported `activated`, and the final selected root was Home. Home-source actions were left unmapped. Devices/Life-source candidates were mapped where present, while transitions returning to Home remained ambiguous. This establishes physical navigation evidence without claiming a stable Home identity.

## 13. Plugin Transition Findings

The existing Phase 3B evidence requested the humidity sensor but observed the vibration sensor screen (`진동 센서`); the plugin context verifier returned false and the result remained unresolved. Phase 3C preserved this mismatch and did not rerun the unreliable optional plugin context. A focused test verifies that a plugin-context mismatch stays unbound and does not create an unsafe transition bind.

## 14. Ambiguity Handling

Ambiguity remained explicit throughout replay. In the Phase 3C matrix, all 3 passive Home observations had `state_id=null`; their candidate set hashes were distinct. Ten of 16 actions therefore had an unresolved source, and 14 transitions had an ambiguous result. No state or transition was force-merged to improve mapping metrics.

## 15. Candidate and Transition Mapping

Phase 3B mapped 12/13 controlled actions. Phase 3C mapped 6/16; its 10 unmapped actions all began from unresolved Home. Every mapped candidate was found in the source snapshot with matching state ID and action kind. No candidate or transition semantic split was observed.

## 16. Identity Collision Audit

Across the 29 replayed device transitions: state collisions 0, candidate ID collisions 0, transition ID collisions 0, unsafe state binds 0, unsafe transition binds 0, unexpected candidate churn 0, unexpected transition churn 0, and unexpected transition splits 0. Phase 3A’s two observed candidate changes remain classified as expected; the historical incident remains unreproduced.

## 17. Artifact Integrity

All 48 Phase 3B and 48 Phase 3C evidence references resolved within their run directories. Replayed before/after captures and ACK documents matched their bracket inputs. Phase 3C’s 16 transition snapshot/observation pairs and 3 passive observation/snapshot pairs reproduced byte-identically. Phase 3A’s 44 bundles and 80 comparisons remain complete and were replayed again.

The original repository `out/` remained unchanged: all 615 paths have the same SHA-256 hashes as the Phase 3B baseline. Regression ran from an isolated source copy.

## 18. Performance

Approximate Phase 3C median timings from saved device diagnostics: source prepare 400 ms, post-transition completion 475 ms, and device capture 4,569 ms. These do not include an autonomous policy. Phase 3B’s recorded medians were 100 ms for StateObservation, 91 ms for candidate snapshot, 104 ms for Registry resolution, 426 ms for prepare, 421 ms for completion and 0.26 ms for serialization. These are small-run diagnostic measurements, not production latency guarantees.

## 19. Remaining Limitations

- Home state remains unresolved after the camera “last updated” label changed; Home candidate hashes vary across three passive observations while unbound.
- Ten Phase 3C source actions were consequently unmapped, and Home-return results remain ambiguous.
- The optional humidity/vibration plugin context mismatch is retained from Phase 3B.
- The historical Phase 3A churn incident is still a non-reproduced transient with unknown original cause.

## 20. Phase 4 Preconditions

All numerical identity, binding, churn, split, contradiction and full-regression gates are clear. Phase 4 is **not ready** because Home is a required core path and is still safely unresolved. Resolve or provide stable, evidence-backed Home identity in a separate approved phase before Phase 4 consumes Home candidates. Do not loosen Phase 2 equality or identity rules to force a match.

## 21. Baseline Metrics Before Home Closure

```ini
PHASE3_FINAL_VERDICT=PHASE3_PASS_WITH_LIMITATIONS
READY_FOR_PHASE4=NO
TOTAL_REPLAY_CASES=213
TOTAL_DEVICE_TRANSITIONS=29
STABLE_TRANSITIONS=10
EXPECTED_VARIABILITY_COUNT=2
AMBIGUOUS_BUT_SAFE_COUNT=17
UNEXPECTED_NONDETERMINISM_COUNT=0
STATE_COLLISION_COUNT=0
CANDIDATE_ID_COLLISION_COUNT=0
TRANSITION_ID_COLLISION_COUNT=0
UNSAFE_STATE_BIND_COUNT=0
UNSAFE_TRANSITION_BIND_COUNT=0
UNEXPECTED_CANDIDATE_CHURN_COUNT=0
UNEXPECTED_TRANSITION_CHURN_COUNT=0
UNEXPECTED_TRANSITION_SPLIT_COUNT=0
CROSS_LAYER_CONTRADICTION_COUNT=0
SOURCE_STATE_SNAPSHOT_MISMATCH_COUNT=0
ACTION_NOT_IN_SOURCE_SNAPSHOT_COUNT=0
RESULT_STATE_FINGERPRINT_MISMATCH_COUNT=0
OUTCOME_STATE_EQUALITY_MISMATCH_COUNT=0
VIEWPORT_OUTCOME_MISMATCH_COUNT=0
FOCUS_OUTCOME_MISMATCH_COUNT=0
ACK_RECONCILIATION_MISMATCH_COUNT=0
TRANSITION_HASH_REPLAY_MISMATCH_COUNT=0
```

## 22. Baseline Verdict Before Home Closure

**PHASE3_PASS_WITH_LIMITATIONS**. Phase 3 contracts remain mutually consistent and replay-stable on saved Phase 2/3A/3B evidence and the 29 device transitions. The Phase 3C diagnostic/tool tests pass; production runtime, production config and Helper are unchanged. Phase 4 is not approved until the required Home identity can be resolved safely.

```ini
PRODUCTION_RUNTIME_CHANGED=NO
PRODUCTION_CONFIG_CHANGED=NO
HELPER_CHANGED=NO
```

### Evidence

- [Phase 3A churn closure gate](../../output/phase3a_churn_closure_20261005/closure_gate.json) and [artifact audit](../../output/phase3a_churn_closure_20261005/evidence_audit.json)
- [Phase 3B artifact audit](../../output/phase3b_transition_20261005/artifact_audit.json)
- [Phase 3C device summary](../../output/phase3c_transition_20261005/device/summary.json), [transition audit](../../output/phase3c_transition_20261005/closure-process4/closure_replay.json), [fresh-process replay](../../output/phase3c_transition_20261005/closure-process5/closure_replay.json)
- [Focused and Phase 2/3 regression](../../output/phase3c_transition_20261005/related_regression.xml), [full Python regression](../../output/phase3c_transition_20261005/full_python.xml)

## 23. Home Identity Blocker Closure

Date: 2026-10-05. Branch remains `feature/phase3c-transition-stability-closure` at `f89836a36ed12b2749f7f8203ead0d8dcebd4a5d`. No Phase 3C commit, push, merge or Phase 4 implementation was performed. All evidence is isolated under `output/phase3c_home_identity_20261005/`.

### 23.1 Original Blocker

The original three passive Home observations were mutually `SAME`: 128 nodes, one core signature, one viewport signature, identical secondary semantics and identical physical candidate behavior. They were unresolved against the persisted Registry, rather than unstable relative to each other. The matching Home representative differed in exactly one resource-anchored passive TextView label:

```text
com.samsung.android.oneconnect:id/device_status
마지막 업데이트: 10/05 4:46 AM
마지막 업데이트: 10/05 9:16 AM
```

Class, bounds bucket `[2,22,26,23]`, flags, state description, overlay, context and all other nodes were unchanged. Core and viewport fingerprints omit general resource-bearing text; the timestamp was retained in the secondary label. Consequently the equality reason was `COARSE_CORE_MATCH_WITHOUT_SECONDARY_CONTINUITY`. Another representative was a genuine scrolled viewport, with 69 removed/68 added secondary rows, and could not establish equality without continuity. The Registry correctly retained ambiguity under its old comparison rule. [Original RCA with both saved observation documents](../../output/phase3c_home_identity_20261005/original_rca.json).

### 23.2 RCA Methodology

The existing seed and contract were used unchanged for a 21-observation baseline. Seven captures each used immediate collection, the existing matrix's 0.45-second short stabilization interval, or the existing Helper readiness check. No focus move, scroll, tab switch, click or plugin entry occurred in any passive batch. Readiness checks are diagnostic service/context evidence, not assertions of whole-tree completeness. After the minimal fix, a fresh 21-observation acceptance batch and a final 21-observation batch after controlled navigation were collected. Canonical Full 32 was not executed.

All observations remain `OBSERVED_PARTIAL`; none was promoted to `OBSERVED_FULL`. Pairwise equality retains missing-context, partial-subset, overlay, semantic-control, unknown-flag and instance-geometry guards. Candidate equality is a downstream diagnostic and never a logical-state authority.

### 23.3 Evidence Collected

Each bundle preserves index, capture interval/mode, timestamp, raw normalized flat nodes with paths/ancestors and accessibility flags, fingerprint core/viewport/overlay/transient sections, full secondary sidecar, resolution and equality evaluations, Registry candidate IDs, candidate IDs/hash/count, source breakdown, root-node/context evidence, resource/anchor counts and capability container. No raw XML is duplicated. The diagnostic collector executes zero UI actions and grants zero visit credit.

The additional [window/Helper probe](../../output/phase3c_home_identity_20261005/window_and_helper_probe.json) observed SmartThings `SCMainActivity` as the focused/resumed app; a separate SystemUI subdisplay had null current focus. Earlier `dumpsys window windows` summaries were unavailable, and are not claimed as verified window IDs. Helper node payloads expose no `importantForAccessibility` or semantic description of the camera alert images. Overlay absence remains unproven under the existing bounded detector.

Evidence directories: [baseline](../../output/phase3c_home_identity_20261005/baseline/summary.json), [initial acceptance](../../output/phase3c_home_identity_20261005/acceptance/summary.json), [post-navigation acceptance](../../output/phase3c_home_identity_20261005/post_navigation/summary.json).

### 23.4 Pairwise Differences

| Evidence | Observation | Classification / implication |
|---|---|---|
| Original stored Home vs first passive Home | Only the passive update-time label differs | `VOLATILE_FIELD`; label subtype `TIMESTAMP`; secondary evidence defect |
| Baseline's 21 observations | All 210 pairs `SAME`; core/secondary/viewport/overlay/context stable; 128 nodes throughout | No evidence for a Home-specific sleep or an equality threshold change |
| Original candidate hash differences | Physical position, semantics and sources identical | `VOLATILE_FIELD`: unresolved scope includes observation ID, which includes capture diagnostics; a symptom of unresolved binding |
| Initial repaired acceptance | All 210 pairs `SAME`, same persisted state ID and candidate hash | Initial timestamp repair succeeds |
| Later Home/Devices vs earlier captures | Empty `camera_card_alert_animation_previous` ImageView disappears | Observed tree composition change; its alert meaning is `UNKNOWN`, so it remains an identity discriminator |
| Final passive batch | First 3 captures have 129 nodes and `camera_card_alert_background`/`camera_card_alert_animation_current`; remaining 18 have 127 nodes without them | Natural visual/tree timing variation; no observed control flag/value change; semantic significance remains `UNKNOWN` |
| Combined post-fix acceptance | 42 observations, 861 pairs: 366 `SAME`, 495 `AMBIGUOUS` | No unsafe merge or guessed state split |

The final pair artifact explicitly records CORE, SECONDARY, VIEWPORT, OVERLAY, TRANSIENT, ACTIVITY_CONTEXT, OBSERVATION_COMPLETENESS, NODE_SET, CANDIDATE_SET, CANDIDATE_SOURCE and SEMANTIC_CONTROL_STATE, with source-level ADDED/REMOVED/CHANGED records. Observable control-state changes are zero; neutral image membership changes are retained under NODE_SET/VIEWPORT. [Final pair differences](../../output/phase3c_home_identity_20261005/final_pair_diffs.jsonl). The same `animation_previous` removal was independently observed in Devices; [Devices pair evidence](../../output/phase3c_home_identity_20261005/devices_visual_difference.json) links that new limitation to the camera component rather than the old Phase 3A churn incident.

### 23.5 Root Cause

`ROOT_CAUSE=VOLATILE_LABEL_LEAK`: the original Home timestamp was non-actionable update metadata leaking into exact secondary equality. This was not a core fingerprint instability, a candidate-producer defect, bounds jitter, missing selected tab, overlay change, or demonstrated observation-readiness race.

The remaining blocker is different: camera alert-image membership changes in partial observations. The captures prove the structural difference and unchanged observed controls/candidates, but cannot prove that the images are merely decoration rather than meaningful alert state. Their semantic classification remains `UNKNOWN`. Resource names alone are insufficient evidence to drop them.

### 23.6 Minimal Fix and Rationale

`FIX_APPLIED=YES`. A generic comparison projection recognizes a complete valid update timestamp on a resource-anchored, passive `android.widget.TextView`. It requires known non-clickable, non-focusable, non-scrollable, unchecked, unselected flags, and no semantic value/state/state description. It retains the metadata kind, resource/class/role, geometry and every flag; it changes only the comparison-time timestamp value. Reviewed English and Korean metadata prefixes are supported without a Home, camera-name or resource-name override. Expiry dates, model numbers, unknown/mixed state labels, actionable/unknown nodes and unanchored text stay unchanged. Original raw sidecars, fingerprints, checksums and schema layouts are preserved.

Persistence needed explicit policy provenance. Untagged historical Registry events replay with `observed-secondary-v1`; new events carry `passive-update-timestamp-v1`. Unknown policies and policy-tagged forged outcomes are rejected. Historical documents load/export byte-identically; new mixed-history documents also restart byte-identically. Transition and replay callers use their Registry's explicit policy. This preserves historical verification without rewriting saved unresolved events or weakening equality/Registry validation.

| File | Purpose |
|---|---|
| `tb_runner/state_equality.py` | Guarded typed timestamp projection and versioned comparison policy |
| `tb_runner/state_registry.py` | Replay each event under its recorded policy; preserve historical payloads and validate new mixed history |
| `tb_runner/state_replay.py` | Apply the same Registry policy to pair/restart replay |
| `tb_runner/transition_observation.py` | Record transition equality using the Registry policy |
| `tools/home_identity_closure.py` | Opt-in passive bundles, pair/source diffs and metrics; no action executor |
| `tests/test_home_identity_closure.py` | 40 regression cases covering normalization boundaries, distinct controls/instances, partial/overlay ambiguity, persistence, candidates and Home return |
| This report | Current closure findings and readiness gate |

The earlier Phase 3C tool/tests and Phase 3B report correction are retained. Production traversal/config/Helper paths were not changed. No new readiness wait is added to production. Thirty-pair microbenchmarks measured median equality 18.10 ms under the old policy and 15.76 ms under the new policy; concurrent-load noise makes this unsuitable as a speedup claim. Baseline and initial acceptance capture medians were 4,790 and 4,970 ms. [Timing evidence](../../output/phase3c_home_identity_20261005/performance_and_readiness.json).

### 23.7 Home Passive Stability

| Batch | Total | Resolved | Unresolved | Resolved logical states | Core variants beyond first | Secondary variants beyond first |
|---|---:|---:|---:|---:|---:|---:|
| Before fix, original seed | 21 | 0 | 21 | 0 | 0 | 0 |
| Same baseline raw evidence replayed after fix | 21 | 21 | 0 | 1 | 0 | 0 |
| Fresh acceptance before actions | 21 | 21 | 0 | 1 | 0 | 0 |
| Final passive acceptance after navigation | 21 | 0 | 21 | 0 | 0 | 1 |
| Combined post-fix acceptance denominator | 42 | 21 | 21 | 1 | 0 | 2 |

Combined acceptance has zero unsafe merges, unexpected splits, unexpected candidate churn and candidate collisions. The one resolved state is the original `phase3b-device:state:00000001`; unresolved observations are not counted as invented states. All 42 observations share one physical candidate-behavior variant. Zero churn is not a claim that their unresolved candidate IDs match or that the unclassified visual states are equal.

### 23.8 Home Action Mapping

The fixed matrix reran 16 controlled actions with saved before/ACK/after brackets and the acceptance Registry seed. Ten actions originate from Home: 2 untargeted SmartNext requests, 4 vertical scroll requests and 4 Home-to-Devices actions. Nine map to source candidates; `nav_14_devices` remains unmapped because its source Home has the new unresolved visual composition. There are no unexplained out-of-band mappings. Two additional unmapped actions originate in Devices after the same image disappearance. [Action matrix](../../output/phase3c_home_identity_20261005/actions/summary.json), [mapping details](../../output/phase3c_home_identity_20261005/current-process1/closure.json).

One scroll restore changed the viewport but lost its Helper result log. Its ACK is failure, its continuity proof is rejected, and the outcome remains safely ambiguous. The other restore has verified movement. Neither SmartNext request has strict before/after movement proof; both operation candidates map, but movement/visit credit is not manufactured. The observer grants zero visit credit throughout.

### 23.9 Return-to-Home Transitions

Four controlled returns were observed: two Devices → Home and two Life → Home. The first of each resolves the original Home state; the second of each has an unresolved Home result after image-node variation. Thus `RETURN_TO_HOME_TRANSITIONS=4` and `RETURN_TO_HOME_AMBIGUOUS_COUNT=2`. Final selected root remains Home. Root selection/activation ACKs do not replace logical identity evidence.

### 23.10 Regression and Replay

- Phase 2/3 related regression: **370 passed, 0 failed, 0 errors**; includes all 40 new focused cases. [XML](../../output/phase3c_home_identity_20261005/related_complete.xml).
- Final focused diagnostic/Phase 3C check after clarification of the control-state diff field: **64 passed**. [XML](../../output/phase3c_home_identity_20261005/diagnostic_final.xml).
- Canonical full Python command, matching the earlier 3,003-test baseline: `python -m pytest tests -q`, executed in an isolated source copy with required frozen fixture directories. **3,043 passed, 0 failed, 0 errors, 1 skipped in 93.59s**. The skip is the same unavailable-`xlsxwriter` thumbnail case. No dependency installation, assertion weakening or test exclusion was applied. [XML](../../output/phase3c_home_identity_20261005/full_python_final.xml), [log](../../output/phase3c_home_identity_20261005/full_python_final.log).
- A preparatory whole-root `pytest -q` collected an additional 153 legacy top-level harness cases and initially lacked local frozen fixture data: 17 failures and 5 skips. Nine fixture failures/four local-ledger skips disappear with the prior verified fixture directories; the eight legacy failures reference unchanged APIs/algorithm `1.7.42` against the existing `1.7.71` client. That supplemental invocation is not reported as a passing suite. The standard `tests/` regression above is complete. [Initial broader log](../../output/phase3c_home_identity_20261005/full_python.log).
- Current-policy Phase 2 curated 42/actual 98 replay and separate-process persisted restarts have identical metrics and zero collisions/unsafe merges/unexpected splits/unexpected unresolved cases. [Curated restart](../../output/phase3c_home_identity_20261005/p2-restart/curated.json), [actual restart](../../output/phase3c_home_identity_20261005/p2-restart/actual.json).
- Two fresh legacy-policy processes reproduce the prior 213-case closure, 44 Phase 3A snapshots/Registry restart and all 13/16 Phase 3B/3C transition documents exactly. Reports are byte-identical, with zero contradiction counters. [Legacy replay 1](../../output/phase3c_home_identity_20261005/legacy-process1/closure_replay.json), [legacy replay 2](../../output/phase3c_home_identity_20261005/legacy-process2/closure_replay.json).
- Two fresh current-policy processes reproduce 63 passive snapshots (21 baseline-fixed replay, 21 initial acceptance, 21 final acceptance), 3 auxiliary matrix observations, all 16 new transition documents/IDs, 48 evidence references and mixed-history Registry restart exactly. All 16 equality relations are independently recomputed with their recorded policies/proofs. Closure reports are byte-identical and the new transition audit has zero mismatch, collision, unsafe-binding, churn, split or contradiction counters. [Current replay 1](../../output/phase3c_home_identity_20261005/current-process1/closure.json), [current replay 2](../../output/phase3c_home_identity_20261005/current-process2/closure.json).
- The [combined 45-transition audit](../../output/phase3c_home_identity_20261005/combined_transition_audit.json) also checks cross-run state/candidate/transition identities together: PASS, 20 stable, 2 expected variability, 23 safely ambiguous, with every mismatch/collision/unsafe-binding/churn/split/contradiction counter zero.

### 23.11 Remaining Limitations

The Home blocker remains. The smallest next investigation is to establish the accessibility importance and actual alert meaning of the camera card's unlabeled image/background nodes during their appearance/disappearance, retaining parent structure and visual/semantic evidence on both sides. Only then can a generic decoration/readiness rule or a legitimate distinct-state rule be evaluated. These captures do not justify ignoring all ImageViews, all resource IDs, all labels or geometry.

The old Phase 3A non-reproduced churn incident and humidity/vibration plugin mismatch remain separate limitations. The single lost scroll ACK and unavailable strict focus proof are retained as bounded action evidence limitations. The supplemental legacy top-level test harness is pre-existing maintenance debt, outside this identity repair. No limitation was removed by force-binding an observation.

### 23.12 Revised Phase 4 Readiness and Final Metrics

**Home closure FAIL / partially repaired; overall Phase 3 remains `PHASE3_PASS_WITH_LIMITATIONS`. `READY_FOR_PHASE4=NO`.** The numerical safety gates are clear, but Home unresolved and return-ambiguity gates fail. Phase 4 must not consume optimistic Home state identity.

The Home metrics below count the two post-fix acceptance batches (42), not the 21 pre-fix RCA captures, their offline replay, the three auxiliary matrix observations, or controlled transition brackets. Safety counters cover the combined audit of the preserved 29 and new 16 transitions; all are zero.

```ini
PHASE3_HOME_IDENTITY_CLOSURE_VERDICT=FAIL
ROOT_CAUSE=VOLATILE_LABEL_LEAK
FIX_APPLIED=YES
HOME_IDENTITY_BLOCKER_REMAINS=YES
REMAINING_BLOCKER=UNCLASSIFIED_CAMERA_ALERT_IMAGE_NODE_VARIATION
HOME_OBSERVATIONS_TOTAL=42
HOME_RESOLVED_COUNT=21
HOME_UNRESOLVED_COUNT=21
HOME_UNIQUE_LOGICAL_STATE_COUNT=1
HOME_UNSAFE_MERGE_COUNT=0
HOME_UNEXPECTED_SPLIT_COUNT=0
HOME_CORE_VARIATION_COUNT=0
HOME_SECONDARY_VARIATION_COUNT=2
HOME_CANDIDATE_UNEXPECTED_CHURN_COUNT=0
HOME_ACTIONS_TOTAL=10
HOME_ACTIONS_MAPPED=9
HOME_ACTIONS_UNMAPPED=1
HOME_ACTION_MAPPING_BLOCKERS=1
RETURN_TO_HOME_TRANSITIONS=4
RETURN_TO_HOME_AMBIGUOUS_COUNT=2
STATE_COLLISION_COUNT=0
CANDIDATE_ID_COLLISION_COUNT=0
TRANSITION_ID_COLLISION_COUNT=0
UNSAFE_STATE_BIND_COUNT=0
UNSAFE_TRANSITION_BIND_COUNT=0
UNEXPECTED_CANDIDATE_CHURN_COUNT=0
UNEXPECTED_TRANSITION_CHURN_COUNT=0
UNEXPECTED_TRANSITION_SPLIT_COUNT=0
CROSS_LAYER_CONTRADICTION_COUNT=0
PYTHON_TEST_RESULT=3043 passed, 0 failed, 0 errors, 1 known skipped
PHASE2_PHASE3_REGRESSION_RESULT=370 passed, 0 failed, 0 errors
PRODUCTION_RUNTIME_CHANGED=NO
PRODUCTION_CONFIG_CHANGED=NO
HELPER_CHANGED=NO
PHASE3_FINAL_VERDICT=PHASE3_PASS_WITH_LIMITATIONS
READY_FOR_PHASE4=NO
```

Original `out/`: 615/615 paths and SHA-256 hashes preserved; no additions/deletions/changes. Production config SHA-256 remains `6dd5d8a191d21e4366ed2513627d97b37515a1e2ae9c2ed342b8d2317fecb964`. [Integrity evidence](../../output/phase3c_home_identity_20261005/integrity.json). [Final Git command output and full untracked-file list](../../output/phase3c_home_identity_20261005/final_git_state.txt). New documents/tools/tests are untracked and therefore absent from normal `git diff --stat`; `out/` remains unrelated untracked user data.

## 24. Camera Alert Image Node Semantic Classification

### 24.1 Remaining blocker

The primary classification of `camera_card_alert_animation_previous` remains **UNKNOWN**. Confidence is **INSUFFICIENT_FOR_EQUIVALENCE**. This investigation did not establish that the image is decorative, a placeholder, stale, loading, or an alert state. The existing passive update-timestamp repair and policy-version compatibility remain intact. No new identity fix was applied. Home closure remains FAIL; Phase 3 remains `PHASE3_PASS_WITH_LIMITATIONS`, and Phase 4 readiness remains NO.

New evidence is isolated under `output/phase3c_camera_semantics_20261005/`. No commit, push, merge, branch switch, Phase 4 implementation, Helper change or production configuration change was performed.

### 24.2 Node metadata

The three original saved Home observations expose `com.samsung.android.oneconnect:id/camera_card_alert_animation_previous`, class `android.widget.ImageView`, package `com.samsung.android.oneconnect`, bounds `[468,1977][612,2121]`. Text and contentDescription are empty; clickable, focusable, checked, selected, focused and scrollable are false; enabled is true. The saved XML-derived `visibleToUser` is **unknown**, not false. The saved node has an empty role field, which does not prove that TalkBack has no inferred role.

Live XML records for `camera_card_alert_animation_current` and `camera_card_alert_background` include package, class, text, content-desc, enabled, clickable, focusable, checkable, checked, selected, focused, scrollable, long-clickable, password, bounds, child count and exact tree paths. Current has the same `[468,1977][612,2121]` bounds; background covers `[30,1713][1050,2217]`. Both are blank neutral ImageViews in the exposed XML fields.

StateDescription, hint, paneTitle, importance, action lists, traversalBefore/After and source/window IDs are not exposed by these XML/Helper sources. They are explicitly null/unobserved in the diagnostic, never treated as observed absence. See `saved_previous_nodes.json`, `passive30/*.xml` and `present_absent_comparison.json` for full fields.

### 24.3 Parent/sibling structure

The exact immediate parent of the saved previous image is an unnamed `android.view.ViewGroup` at `[30,1713][1050,2217]`, below the clickable/focusable `favorite_device_card_camera` FrameLayout. Its siblings are `clip_thumbnail` and `base_part`; it has three direct children including previous. The previous ImageView is a leaf. In the absent live variant, the same inner card group has only thumbnail and base_part. In the live current/background variant, two ImageView children are added alongside them.

```text
favorite_device_card_camera (FrameLayout; clickable/focusable)
└ unnamed ViewGroup
  ├ clip_thumbnail
  ├ base_part (room/name/update-time/power button)
  └ animation_previous                 [saved original only]

Live related PRESENT: thumbnail + alert_background + base_part + animation_current
Live ABSENT:          thumbnail + base_part
```

The exposed meaningful descendants retain the same labels, power control, enabled/clickable/focusable/selected/checkable/checked flags and bounds in the selected live comparison. No candidate is attributed to the alert images. Structural presence alone is not classified as a semantic alert.

### 24.4 Accessibility importance

Normal and compressed XML were saved at observations 1, 15 and 30. All three compressed checks happened during ABSENT frames, so they do not establish importance of the transient images. Compression is not equated with an observed `importantForAccessibility` value.

Two focus-only probes positively observed `accessibilityFocused=true` on the exact camera parent. Requests targeting current/background returned **Target node not found**; subsequent actual-focus reads did not confirm image focus. Because XML/Helper reads are sequential and target discovery may differ from TalkBack traversal, this is **not proof that the images cannot receive TalkBack focus**. Previous was not available live. A complete TalkBack traversal proving no additional spoken item was not obtained. Root fallback with both focus flags false received no focus/visit credit.

### 24.5 TalkBack speech evidence

`speech1/` brackets a related PRESENT camera probe; `speech2/` brackets an ABSENT probe. Native TalkBack focus/speaking-fragment logs produced no correlatable application utterance for either. A supplementary injected 5px, 350ms input swipe produced no correlatable camera speech. A later read found the camera detail page, so the input was not established as TalkBack exploration and is rejected as speech/importance evidence. One existing Android Back command restored verified Home (`probe_back_restore.json`). No double tap, power command or remote device-control command was issued. This unexpected UI navigation is retained explicitly rather than reported as successful focus-only evidence.

The wider native log contains TalkBack service enable/disable/time utterances around existing navigation behavior, but these are reader/system announcements and are not camera speech. No verbosity or accessibility setting was edited to manufacture evidence. Exact spoken label/state/role/hint/action differences therefore remain **UNOBSERVED**. Helper `mergedLabel`/`talkbackLabel` aggregates such as room, camera name, update time and power action are predictions/metadata and are **not substituted for actual TalkBack speech**. Speech equality is not claimed.

### 24.6 Visual evidence

The existing screenshot approach (remote screencap file followed by adb pull) captured all 30 observations. Reviewed screenshots:

- `passive30/001.png`: camera thumbnail, room/name/update time and power action; no central camera icon.
- `passive30/011.png`: a white camera-shaped icon with rays and a darker thumbnail overlay is visibly present.
- `passive30/013.png`: the icon is gone by screenshot time, although its preceding XML still contained current/background.

The top smoke-warning carousel card remains visible across these images and is a separate accessibility subtree; it is not attributed to the camera image merely because both names contain alert-related language. The camera crop differs in 490,077 of 514,080 pixels between 001 and 011, including the overlay/icon. This proves a visible difference in those screenshots, **not its meaning**. Sequential XML and screenshot timestamps are retained; they are not an atomic rendering capture. There is insufficient evidence to call the icon harmless decoration, a loading signal or a semantic alert.

### 24.7 Temporal behavior and controlled events

Thirty passive Home observations were collected on 2026-10-05 from 12:52:23 to 12:56:11 KST without a gesture, click, refresh or device-state change. All use `helper_capability+xml_semantics`; no Helper-only fallback was silently accepted.

Previous was absent in all 30. Current and background appeared together in observations 11–14, then disappeared without a user action. Those four capture starts span 12:53:36–12:53:58 KST; they bound observed presence, not an exact animation duration. There are 26 frames with 127 nodes and four with 129 nodes. Physical candidate behavior has one variant. `timeline.json` records timestamps, exact node presence/count, parent metadata, explicit missing speech, candidate hash, physical candidate hash and Registry resolution for every observation. `pairs.jsonl` records all 435 pair equality outcomes.

The fixed action matrix repeats Home→Devices/Home and Devices→Life→Home twice, with the existing stabilization interval and scroll/focus commands. No explicit camera refresh, power, alert acknowledgement, remote device-control or destructive command was issued. The rejected supplementary input probe navigated to camera detail and was restored with Back; it is outside this passive batch and the fixed 16-transition matrix. Correlation with INITIAL_RENDER/LOADING/REFRESH/ALERT_STATE remains UNKNOWN.

### 24.8 PRESENT/ABSENT semantic comparison

The live comparison is **current/background PRESENT versus absent**, not a validated reproduction of previous. The original previous-side evidence is retained separately in `saved_previous_nodes.json` (three observations; no original screenshots or speech). It cannot complete a both-variant equivalence claim.

| Required comparison | Result | Evidence scope |
|---|---|---|
| PARENT_TEXT_CHANGED | false | Exact camera parent XML |
| PARENT_CONTENT_DESC_CHANGED | false | Exact camera parent XML |
| PARENT_STATE_DESC_CHANGED | UNKNOWN | Field not exposed |
| PARENT_ACTIONS_CHANGED | UNKNOWN | Full action lists not exposed; clickable/long-clickable flags remain same |
| PARENT_ENABLED_CHANGED | false | XML |
| PARENT_CLICKABLE_CHANGED | false | XML |
| PARENT_SELECTED_CHANGED | false | XML |
| PARENT_SPEECH_CHANGED | UNKNOWN | Actual camera speech unavailable |
| CANDIDATE_SET_CHANGED | false | Physical/semantic candidate projection; raw observation-bound IDs remain distinct |
| VISIBLE_UI_CHANGED | true | Camera crop in screenshots 001 versus 011; semantic meaning unknown |

Exposed descendant semantics are unchanged. Unknowns are null in `present_absent_comparison.json`, not coerced to false.

### 24.9 Semantic classification

**UNKNOWN** is the sole primary classification. Natural appearance/disappearance and stable candidates suggest a transient rendering component, but they do not prove non-semantic equivalence. The visible icon/overlay makes blind ImageView exclusion especially unsafe. No claim of SEMANTIC_ALERT_STATE or SEMANTIC_LOADING_STATE is made without identifying what the icon means to the user and to TalkBack. The word `alert`, blank labels and node count are not used as classification oracles.

### 24.10 Fix/no-fix rationale

**FIX_APPLIED=NO**, **FIX_TYPE=NONE_CAMERA_IDENTITY** for this investigation. The prior timestamp fix remains applied. No matching policy, Registry identity, fingerprint, transition binding or replay contract was altered. No resource-specific camera exclusion or blanket passive-image rule was introduced.

Missing closure evidence is specific: live previous-node reproduction; paired actual TalkBack speech (label/state/role/hint/actions); observed importance/actions and parent aggregation; complete image traversal evidence; and attribution of the visible icon/overlay to loading, alert, camera activity, or harmless rendering. If the image proves semantic, preserve the distinction and review how the existing Phase 2 model can resolve it. A model redesign must be a separately scoped architecture decision.

### 24.11 Safety analysis and changed files

New `tests/test_camera_alert_semantics.py` adds 21 checks: unknown blank-image removal remains AMBIGUOUS; desc/state/focus/action/role/warning/error/disabled/selected/lock/offline images are preserved; real semantic changes remain DIFFERENT; input order is stable; parent change is detected; partial trees stay AMBIGUOUS; unresolved variants remain unresolved after Registry restart; missing speech/action metadata remains unknown; and parent/sibling XML is recorded exactly. Existing 40 Home tests continue to protect timestamp typing, real control state, overlays, positional instances and legacy/mixed policy replay. Decorative equivalence tests are deliberately conditional on proof, which was not obtained.

New `tools/camera_alert_diagnostic.py` is an explicit opt-in, passive diagnostic only. It records XML structure, screenshots, timestamps, candidates, resolution and tri-valued metadata comparison; it does not select or activate UI and is not integrated into production. Its ID constants locate evidence, not exclude identity. This closure document is updated. Earlier Phase 3 Python changes remain byte-identical to the initial worktree.

### 24.12 Home passive acceptance

The new 30-observation batch resolves **0/30**, leaves **30 unresolved**, and binds **0 unique logical states**. The previously persisted Home state is retained in the seed, but these observations do not safely bind to it. This does not redefine the historical 42-observation metrics in §23.

Previous PRESENT=0 / ABSENT=30 live; related current/background PRESENT=4 / ABSENT=26. Pair outcomes: SAME=331, AMBIGUOUS=104. Core variation=0; secondary variation=1; physical candidate variants=1; unsafe merges=0; unexpected splits=0; unexpected candidate churn=0. Observation-scoped candidate IDs in unresolved frames are expected diagnostics and do not confer a logical state binding. The both-variant and resolved-Home acceptance gates fail.

### 24.13 Home action mapping

The fixed matrix completed 16 transitions. Ten actions originated on Home (two focus requests, two down/restore pairs and four Home departures). Home mappings are **0/10**, unmapped=10, blocking mappings=10. All have `UNRESOLVED_SOURCE_IDENTITY`; they are not mislabeled as new candidate collisions. Overall matrix mappings=2/16, unmapped=14/16. All ACKs remain separate from actual movement, state resolution and visit credit. Matrix script `status=PASS` means execution completed, not Home acceptance.

### 24.14 Return-to-Home results

Devices→Home and Life→Home each ran twice. All four returned to the selected Home tab but yielded no safe Home logical binding: **4/4 AMBIGUOUS_RESULT**. Root navigation success does not imply logical-state closure. The matrix ended on Home. The two Helper focus-only speech probes grant no traversal/visit credit. The later supplementary injected-input probe unexpectedly reached camera detail; it is excluded from the fixed matrix and its speech evidence is rejected. A saved post-probe Back bracket verifies the final device root is Home, with no identity binding or visit credit manufactured for that probe.

### 24.15 Regression, replay and cross-layer audit

The focused camera + prior Home suite passed **61/61**. Phase 2/3 regression passed **391/391**. Standard `python -m pytest tests -q` passed **3,064**, failed **0**, errors **0**, skipped **1**. The skip is unchanged: `test_save_excel_xlsxwriter_thumbnail_insert_does_not_raise_file_not_found`, missing xlsxwriter. The isolated fresh source copy emitted one existing SyntaxWarning from an imported legacy module; the unrelated whole-root harness was not collected. Tests ran against an isolated source copy so root `out/` was protected; hashes confirm tested Python sources match the worktree.

Fresh Phase 2 replay covers curated 42 and actual 98 observations with no collisions, unsafe merges, unexpected splits or unexpected unresolved outcomes. Legacy replay rebuilds the original 44 candidate snapshots and 29 transition documents; prior current-policy replay rebuilds the earlier 63 Home snapshots, 16 Home-matrix documents and mixed Registry restarts exactly. Historical initial Phase 3B `*_result.json` files predate canonical `state_transitions_final.jsonl`; the audit uses finalized documents independently regenerated from raw brackets, not those stale embedded documents.

New 30-observation and 16-transition replay, prior 45-transition audit and combined 61-transition audit results are recorded in the final metrics below. No contract was weakened after preparatory diagnostics hit a multi-display screenshot stdout prefix and an incorrect attempt to compare pre-final Phase 3B documents. Those logs remain retained; the screenshot collector uses the existing remote-file/pull approach, and canonical legacy cases are exported by exact raw-bracket replay.

### 24.16 Revised Phase 4 readiness and final Git state

**READY_FOR_PHASE4=NO**. UNKNOWN classification, 30 unresolved observations, ten Home mapping blockers and four ambiguous core returns independently prevent approval. Remaining work is evidence closure of the image meaning and accessibility effect, followed by the existing safe identity/model decision and both-variant acceptance. Phase 4 is not implemented.

Production runtime/config/Helper stay unchanged. The runtime JSON SHA256 remains `6dd5d8a191d21e4366ed2513627d97b37515a1e2ae9c2ed342b8d2317fecb964`. The unrelated `out/` path/hash set remains exactly 615 files. The branch and original HEAD remain unchanged; nothing is staged, committed, pushed or merged. Complete initial/final Git command outputs, including every untracked path, are retained as `initial_git_state.txt` and `final_git_state.txt` in the isolated output directory.


Current audit: prior **45/45**, combined **61/61**, both **PASS**; every mismatch/collision/unsafe/churn/split/contradiction counter is zero. Stable=20, expected focus variability=2, safe ambiguous=39. New replay reproduces **30/30** passive snapshots and **16/16** transition documents, verifies **48** evidence files and preserves Registry restart bytes. Two fresh processes produce identical closure, passive/transition Registry and audit files.

```ini
CAMERA_ALERT_NODE_CLASSIFICATION=UNKNOWN
CLASSIFICATION_CONFIDENCE=INSUFFICIENT_FOR_EQUIVALENCE
CLASSIFICATION_EVIDENCE_SUMMARY=Live related image flicker and visible icon/overlay; previous not reproduced; paired actual speech and full importance/actions absent
FIX_APPLIED=NO
FIX_TYPE=NONE_CAMERA_IDENTITY_EXISTING_TIMESTAMP_FIX_PRESERVED
CAMERA_ALERT_NODE_PRESENT_COUNT=0
CAMERA_ALERT_NODE_ABSENT_COUNT=30
HOME_OBSERVATIONS_TOTAL=30
HOME_RESOLVED_COUNT=0
HOME_UNRESOLVED_COUNT=30
HOME_UNIQUE_LOGICAL_STATE_COUNT=0
HOME_UNSAFE_MERGE_COUNT=0
HOME_UNEXPECTED_SPLIT_COUNT=0
HOME_CANDIDATE_UNEXPECTED_CHURN_COUNT=0
HOME_ACTIONS_MAPPED=0
HOME_ACTIONS_TOTAL=10
HOME_ACTIONS_UNMAPPED=10
HOME_ACTION_MAPPING_BLOCKERS=10
RETURN_TO_HOME_AMBIGUOUS_COUNT=4
RETURN_TO_HOME_TRANSITIONS=4
STATE_COLLISION_COUNT=0
CANDIDATE_ID_COLLISION_COUNT=0
TRANSITION_ID_COLLISION_COUNT=0
UNSAFE_STATE_BIND_COUNT=0
UNSAFE_TRANSITION_BIND_COUNT=0
UNEXPECTED_CANDIDATE_CHURN_COUNT=0
UNEXPECTED_TRANSITION_CHURN_COUNT=0
UNEXPECTED_TRANSITION_SPLIT_COUNT=0
CROSS_LAYER_CONTRADICTION_COUNT=0
PYTHON_TEST_RESULT=3064 passed, 0 failed, 0 errors, 1 known skipped
PHASE2_PHASE3_REGRESSION_RESULT=391 passed, 0 failed, 0 errors
PRODUCTION_RUNTIME_CHANGED=NO
PRODUCTION_CONFIG_CHANGED=NO
HELPER_CHANGED=NO
HOME_IDENTITY_BLOCKER_REMAINS=YES
PHASE3_FINAL_VERDICT=PHASE3_PASS_WITH_LIMITATIONS
READY_FOR_PHASE4=NO
```

Final Git commands (full untracked listing: isolated `final_git_state.txt`, 622 paths = preserved out/615 + Phase 3 source/docs/tests 7):

```text
git branch --show-current
feature/phase3c-transition-stability-closure


git status --short
 M docs/design/phase3b-transition-observation-contract.md
 M tb_runner/state_equality.py
 M tb_runner/state_registry.py
 M tb_runner/state_replay.py
 M tb_runner/transition_observation.py
?? docs/design/phase3-state-discovery-transition-closure.md
?? out/
?? tests/test_camera_alert_semantics.py
?? tests/test_home_identity_closure.py
?? tests/test_phase3c_transition_closure.py
?? tools/camera_alert_diagnostic.py
?? tools/home_identity_closure.py
?? tools/phase3c_transition_closure.py


git diff --stat
 .../phase3b-transition-observation-contract.md     | 27 +++++++----
 tb_runner/state_equality.py                        | 56 +++++++++++++++++++---
 tb_runner/state_registry.py                        | 47 +++++++++++-------
 tb_runner/state_replay.py                          | 15 +++---
 tb_runner/transition_observation.py                |  3 +-
 5 files changed, 109 insertions(+), 39 deletions(-)


git diff --name-only
docs/design/phase3b-transition-observation-contract.md
tb_runner/state_equality.py
tb_runner/state_registry.py
tb_runner/state_replay.py
tb_runner/transition_observation.py

```

## 25. Camera Overlay Semantic Probe

### 25.1 Objective

Determine the event and user meaning of the Home camera overlay before changing identity. This is a targeted diagnostic investigation, with no Phase 4 implementation, production changes, commit, push or merge. Dedicated evidence: `output/phase3c_overlay_probe_20261005/`. Prior §24 evidence is retained and explicitly distinguished from this run.

### 25.2 Baseline and evidence sources

Branch remains `feature/phase3c-transition-stability-closure`, HEAD `f89836a36ed12b2749f7f8203ead0d8dcebd4a5d`. The timestamp repair, existing Phase 3 worktree, and unrelated `out/` 615-file manifest are preserved. Prior acceptance: 30 Home observations, 0 resolved, 30 unresolved; related current/background present 4 times, previous present 0 times; actions mapped 0/10 and core returns ambiguous 4/4.

Three distinct sources support this probe: event-bracketed live observations, retained prior positive XML/screenshots, and resources plus DEX instructions from a read-only copy of the **installed target APK**. No app/Helper APK was replaced. Installed application code is local primary evidence; semantic meaning is not inferred from the resource names alone.

### 25.3 Event correlation

`events_final/events.json` records 11 safe before/event/after brackets, with command ACK, timestamps and capture references. It captures 29 total observations: 25 Home, 2 Devices, 2 Life. This is not another 30-observation passive acceptance run. All 25 Home observations are overlay ABSENT. There are **0 newly captured overlay onset/removal events**; this does not erase the four retained earlier positive observations.

| Condition | Actual investigation | Result |
|---|---|---|
| Fresh Home entry / background return | Existing exported main activity, Android HOME and return | No overlay in after frames |
| Home stabilization | Diagnostic 450 ms reference wait and next capture | No overlay |
| Devices → Home | Existing bottom navigation, 3 after frames | No overlay; Home remains unresolved |
| Life → Home | Existing bottom navigation, 3 after frames | No overlay; Home remains unresolved |
| Existing safe refresh control | No supported safe path found | Not invoked |
| Initial render | First and subsequent Home frames | Initial positional settling, no overlay |
| Natural last-update change | Baseline timestamp advances from 12:36 PM to 1:32 PM | Timestamp update alone did not coincide with overlay |
| Network/content loading | No natural offline/loading transition captured | Not reproduced |
| Immediately before/after overlay | No new positive frame | Not reproduced; retained earlier sequence analyzed |
| User focus | Parent focus and existing Helper PREV/NEXT | No overlay; ACK is not visit credit |

The first setup attempt used a non-exported internal activity and failed with SecurityException, leaving the launcher visible. That failed run is retained in `events/` and `events.log` and **excluded** from Home/overlay counts. The corrected run uses the existing repository entry `com.samsung.android.oneconnect/.ui.SCMainActivity`. No app data reset, force-stop or camera setting change occurred.

### 25.4 Temporal sequence

No new overlay onset was available for a fresh T−2/T−1/T0/T+1 sequence. Existing raw observations provide absent frames 9–10, first related positive 11, positive 12–14, and removed frames 15–16. These are sampled observations, not continuous video. Frame 11's screenshot shows the icon; frame 13's later screenshot lacks it while preceding XML contains the nodes, demonstrating the earlier timing limitation. The exact old event trigger remains unrecorded.

### 25.5 XML/screenshot synchronization and diagnostic overhead

The new diagnostic intercepts the XML dump command and starts screencap immediately after it completes, before remaining Helper/semantic processing. Each observation stores full XML start/end and screenshot start/end timestamps. `DELTA_MS` is the host invocation gap only: approximately **0.0103–0.0144 ms**. The complete XML-start-to-screenshot-end uncertainty bound is **3,053.8–3,940.3 ms**. Captures are **BOUNDED_SEQUENTIAL_NOT_ATOMIC**, not simultaneous snapshots. No new positive frame exists to claim tighter positive node/pixel attribution.

Total diagnostic capture cost is **5,863.1–7,574.7 ms per observation**, including existing observation collection and screenshot/pull. Additional screenshot/pull work is diagnostic; the isolated incremental overhead was not benchmarked. The only explicit stabilization wait is 450 ms; supplementary focus speech uses 1.2 seconds per command. No production wait was added. XML captures correlate with reader-disabled/reader-enabled log pairs; this is a diagnostic confound, not proof that the app changed its semantic state.

### 25.6 Camera subtree diff

Retained normal/present/removed card evidence compares full resource ID, class, text, contentDescription, enabled, clickable, focusable, selected, checked/checkable, bounds, path, parent and siblings. Normal has 127 whole-screen nodes; related-positive frames have 129, adding current/background under the same camera subtree. Parent remains the clickable/focusable camera FrameLayout, bounds `[30,1713][1050,2217]`. Its exposed text/contentDescription and enabled/clickable/selected attributes do not change. Non-overlay descendants match in the retained same-time-label pair; original previous-only evidence adds a separate blank ImageView under the unnamed camera ViewGroup.

XML does **not** expose stateDescription, hint, visibleToUser, full action sets, source/window IDs or runtime importance here. Those fields remain unknown, not false. `present_absent_comparison.json` in the prior evidence directory contains the full attribute/structure comparison; new `events_final/observation_*.json` preserves every current camera subtree and candidate snapshot.

### 25.7 Visual and installed-code evidence

The retained positive screenshot `phase3c_camera_semantics_20261005/passive30/011.png` shows a white camera-shaped event icon with rays and a darkened thumbnail. Normal frame 001 and the new final screenshot lack this icon. The separate smoke-alert carousel is visible in both and is not attributed to the camera overlay.

The installed APK establishes a concrete semantic producer/consumer chain:

1. `clouddevice.viewmodel.t.m(DeviceItem)` reads `BasicPlusData.Camera.getOverlayIcons()`, then the first `OverlayIcon.getIconUri()`, stripping `res://`.
2. Exact URI values map to **CameraEventType.HUMAN, MOTION, PET**, with missing/unrecognized values mapped to NONE. The enum is stored in camera viewmodel `z0.c`.
3. Actual `camera.view.g` (constructor debug tag CameraCardView) binds background/current/previous resource IDs to its views. `I(CameraEventType)` selects the motion/person/animal Lottie resource. `z(...)` compares the old/new event, logs `updateAlertEvent`, and chooses alert appearance/change/dismissal paths. NONE→NONE invokes `F()` to hide background/current; non-NONE paths set compositions/visibility and animate them.
4. Thumbnail loading has a **separate 24 dp ProgressBar/ViewStub** and loading path. The semantic alert path hides that progress indicator before displaying the event composition. The overlay cannot be discounted as a generic thumbnail spinner.

Evidence files: `apk_code_00.txt` (URI→enum, lines 1396–1443), `apk_camera_code_00.txt` (raw resources), `apk_camera_code_01.txt` (view bindings, hide/update/show paths), `apk_xml_00.txt` (layout), `apk_xml_02.txt` (separate progress), and `apk_xml_03.txt`–`08.txt` (animation/background resources). The extracted APK/resources/DEX remain ignored output artifacts.

The layout marks thumbnail/background `importantForAccessibility=NO`; current/previous are LottieAnimationView subclasses without that explicit override in this layout. Runtime aggregation can differ. `F()` hides current/background but does not explicitly hide previous. That supports a **possible** uninitialized/stale previous-view explanation for the historical blank node; it does not prove that every previous view is decorative, since the same view participates in meaningful event transitions.

### 25.8 Actual focus evidence

In ABSENT state, existing parent selection is followed by actual Helper `accessibilityFocused=true`. Independently, native TalkBack logs identify the camera FrameLayout, matching bounds/resource ID, `importantForAccessibility=true`, `visible=true`, and actions including click and long-click. This proves actual parent accessibility focus for that observation.

Initial event probes interleave XML capture and focus, correlating with reader reconnects. Supplementary probes omit XML between commands. A further diagnostic repair collects speech **before GET_FOCUS**, because the existing bridge clears logcat in that call (`talkback_lib/helper_bridge.py:135`). Earlier empty captures are retained and rejected as speech equivalence evidence.

No PRESENT image node was available for direct focus. XML `focusable=false`, filtered Helper absence and parent aggregation are insufficient to prove no extra native focus stop. Supplementary PREV focuses a shortcut; NEXT fails in that particular bracket and leaves shortcut focus. These commands are not a successful native camera traversal acceptance run. No action activation, injected touch-exploration gesture or visit credit is used. Full PRESENT/ABSENT order/extra-stop comparison remains unproven.

### 25.9 Actual speech evidence

`focus_speech_before_get_focus/camera_parent.log` records native TalkBack focus event time `154511275`, PID `26858`, package `com.samsung.android.oneconnect`, camera FrameLayout, then the matching `SpeechControllerImpl` utterance:

> 거실, 홈카메라 360, 마지막 업데이트: 10/05 1:32 PM

This is **actual ABSENT parent speech**, not Helper's mergedLabel prediction. The parent native metadata has null stateDescription/contentDescription. No reliable PRESENT utterance exists. Therefore the required paired result is **NO_RELIABLE_SPEECH_EVIDENCE**, even though one side is now reliable. Empty earlier recordings do not imply identical speech. Windows newline translation changes physical log line offsets; replay verifies all utterance text/PID-event association fields and retains both line-index forms.

### 25.10 Trigger classification

**CAMERA_UPDATE** is proven as the implemented semantic trigger path: cloud camera overlayIcon→CameraEventType→event composition. Current live application logs on Home returns explicitly show **NONE→NONE**, consistent with no overlay. Fresh entry, returns, focus and timestamp change alone do not establish an event overlay trigger.

The actual runtime trigger of the earlier four positive samples is **UNKNOWN / TRIGGER_NOT_REPRODUCED**. No positive event payload/log was saved then; static code does not prove which of MOTION/HUMAN/PET caused that specific screenshot. A request for an observable natural camera event did not produce additional captured positive evidence in this run. Camera power/settings were not changed to force a result.

### 25.11 Duration

New duration: **UNKNOWN_NOT_REPRODUCED**. The earlier positive sample timestamps span **22,372.835 ms** (03:53:36.476383–03:53:58.849218 UTC), bracketed by absent samples. This is a sampled window, not a continuous measured lifetime; visual removal occurs within that sequence. XML collection may disturb the reader and render timing. Resource fade duration is an animation parameter and is not an overlay lifetime measurement. No fixed event TTL or transient-equivalence claim is made.

### 25.12 Semantic impact matrix

| Dimension, PRESENT vs ABSENT | Evidence and conclusion |
|---|---|
| Visual difference | YES: retained white event icon/darkened thumbnail; prior captures sequential |
| Actual TalkBack speech difference | UNKNOWN: reliable ABSENT only |
| Focus traversal / extra stop | UNKNOWN: no live positive native traversal |
| Parent exposed metadata | No difference in retained XML subset; complete runtime pair missing |
| Action availability | Exposed clickable/long-clickable unchanged; complete positive action set unavailable |
| Physical candidate set | Retained positive/absent pair identical; no proof that domain event meaning is identical |
| stateDescription | Not exposed by XML; ABSENT native parent null; PRESENT unknown |
| contentDescription | Same empty XML parent; ABSENT native parent null; full positive aggregation unknown |
| Logical app meaning | **Changes camera detection event type** in installed app's producer/viewmodel/render path |

New Home candidate projections have two variants: first entry frame has horizontally displaced scroll target bounds, later settled frames have normal bounds. This positional variation occurs with **overlay absent on both sides**. It is retained as expected initial-render evidence, not attributed to camera semantics or normalized away. The retained positive/absent semantic-candidate comparison remains unchanged.

### 25.13 Final primary classification

**CAMERA_OVERLAY_CLASSIFICATION=SEMANTIC_CAMERA_STATE**. Confidence is **HIGH_FOR_IMPLEMENTED_DOMAIN_SEMANTICS; INSUFFICIENT_FOR_VARIANT_EQUIVALENCE**. The cloud event enum driving actual overlay view composition proves meaningful camera detection state independently of resource naming and independently of missing spoken accessibility exposure. It is user-relevant information that TalkBack should communicate; this probe does not claim the app currently communicates it correctly.

This primary result applies to the overlay/event mechanism. The earlier blank previous-only node's exact instance role and the exact earlier event subtype remain unproven. They do not justify deleting the whole event family from identity. UNKNOWN accessibility impact remains a limitation, not a nonsemantic verdict.

### 25.14 Fix/no-fix and Phase 2 model decision

**No identity fix or filter is applied.** Existing timestamp normalization remains intact. Generic removal of blank nonfocusable images could erase meaningful camera event composition; no positive equivalence evidence exists to justify it.

Phase 2 already preserves observed semantic values/state descriptions/flags, but current Helper/XML observations do not expose CameraEventType or a trustworthy event substate. StateRegistry deliberately keeps the historical partial image variants ambiguous under the existing Home core. Adding a synthetic event marker, resource-ID exception, optimistic fresh state or fabricated observed substate would bypass that contract.

Required next design/evidence work: a trusted runtime observation of camera event type/absence and provenance; agreed same-root camera semantic substate identity; safe reconciliation of old partial observations; then both-variant speech/focus and Home action/return acceptance. A larger semantic producer/model integration is outside this diagnostic scope. Implementation stops here; Phase 4 stays deferred.

### 25.15 Regression and replay

Standard `python -m pytest tests -q`: **3,074 passed, 0 failed, 0 errors, 1 known skipped** in 90.28 seconds. The existing xlsxwriter-dependent thumbnail test is the unchanged skip. One existing invalid-escape SyntaxWarning from the imported legacy module remains; it is not a test failure. Phase 2 identity and Phase 3A/3B/3C related suite including new probe tests: **401 passed, 0 failed, 0 errors**, 12.81 seconds. New 10 pure diagnostic tests reject reversed timing, refuse empty-speech equivalence and require semantic review for changed speech.

Tests run against an isolated source copy with current tracked/untracked Python sources, preserving root `out/`. No production/Helper changes require APK rebuild. Prior 61 transition cases are regenerated/re-audited under the current worktree: **PASS**, all collisions/unsafe binds/churn/splits/contradictions zero; 20 stable, 2 expected variability, 39 safe ambiguous. The new 29 event snapshots replay exactly and Registry serialization/restart is exact. Event probes are not promoted to 11 finalized transition-contract acceptance cases.

### 25.16 Home identity result and metrics scope

Current targeted Home captures: **25 total, 0 resolved, 25 unresolved**, no unsafe logical binding manufactured. Four off-Home references are excluded. Earlier 30-observation acceptance, 10 unmapped actions and four ambiguous core returns remain the authoritative acceptance baseline and were not repeated. Current diagnostic returns confirm unresolved Home but do not replace that matrix. Positive observations **0/25 current**, **4/30 retained prior**; original previous-only saved evidence is a third historical scope. Safety counters below come from the regenerated **61-case** cross-layer audit, not invented success on the new diagnostic events.

### 25.17 Phase 4 readiness and final Git state

**PHASE3_FINAL_VERDICT=PHASE3_PASS_WITH_LIMITATIONS; HOME_IDENTITY_BLOCKER_REMAINS=YES; READY_FOR_PHASE4=NO.** The overlay's implemented camera semantics are now established; trustworthy runtime substate capture, both-variant accessibility comparison, Home resolution and core-return closure remain missing. No full Home acceptance or action matrix rerun is warranted without an identity change.

Changed in this task: report document; new diagnostic `tools/camera_overlay_probe.py`; new `tests/test_camera_overlay_probe.py`. Existing production/Phase 3 sources remain byte-identical to task entry. Dedicated output contains event/timing/native-focus/speech/APK evidence, replay, regression logs and complete initial/final Git commands. Config, Helper and the 615-file `out/` manifest remain exact. No staging, commit, push or merge occurred.

Final metrics: current event Home scope = 25; retained acceptance action/return scope = 10/4; cross-layer safety scope = 61 re-audited cases. Current event probes = 11, all observations = 29. Retained earlier overlay PRESENT/ABSENT = 4/26.

```ini
OVERLAY_PRESENT_OBSERVATIONS=0
OVERLAY_ABSENT_OBSERVATIONS=25
OVERLAY_EVENTS_CAPTURED=0
OVERLAY_TRIGGER_CLASSIFICATION=CAMERA_UPDATE_IMPLEMENTED_PATH; HISTORICAL_POSITIVE_TRIGGER_UNKNOWN
OVERLAY_DURATION_RANGE=UNKNOWN_NOT_REPRODUCED; PRIOR_SAMPLED_WINDOW_22372.835_MS_NOT_CONTINUOUS_LIFETIME
IMAGE_NODE_FOCUSABLE_EVIDENCE=NO_PRESENT_IMAGE_PROBE; ABSENT_PARENT_NATIVE_FOCUS_CONFIRMED
FOCUS_TRAVERSAL_CHANGED=UNKNOWN_NO_PAIRED_PRESENT_TRAVERSAL
TALKBACK_SPEECH_COMPARISON=NO_RELIABLE_SPEECH_EVIDENCE; ABSENT_NATIVE_UTTERANCE_AVAILABLE_ONLY
PARENT_SEMANTICS_CHANGED=NO_IN_EXPOSED_PRIOR_XML_PAIR; COMPLETE_RUNTIME_PAIR_UNKNOWN
CANDIDATE_SET_SEMANTICS_CHANGED=NO_IN_RETAINED_PRESENT_ABSENT_PAIR; FIRST_NEW_ABSENT_FRAME_HAS_POSITIONAL_SETTLING
VISIBLE_UI_CHANGED=YES_RETAINED_POSITIVE_SCREENSHOT
CAMERA_OVERLAY_CLASSIFICATION=SEMANTIC_CAMERA_STATE
CLASSIFICATION_CONFIDENCE=HIGH_FOR_IMPLEMENTED_DOMAIN_SEMANTICS; INSUFFICIENT_FOR_VARIANT_EQUIVALENCE
CLASSIFICATION_EVIDENCE_SUMMARY=Installed camera overlayIcon maps to HUMAN/MOTION/PET enum and actual overlay composition; separate loading progress; retained positive visual; ABSENT native speech only
FIX_APPLIED=NO
FIX_TYPE=NONE_IDENTITY; DIAGNOSTIC_PROBE_ONLY; EXISTING_TIMESTAMP_FIX_PRESERVED
HOME_OBSERVATIONS_TOTAL=25
HOME_RESOLVED_COUNT=0
HOME_UNRESOLVED_COUNT=25
HOME_UNSAFE_MERGE_COUNT=0
HOME_UNEXPECTED_SPLIT_COUNT=0
HOME_ACTIONS_TOTAL=10
HOME_ACTIONS_MAPPED=0
HOME_ACTIONS_UNMAPPED=10
RETURN_TO_HOME_TRANSITIONS=4
RETURN_TO_HOME_AMBIGUOUS_COUNT=4
STATE_COLLISION_COUNT=0
CANDIDATE_ID_COLLISION_COUNT=0
TRANSITION_ID_COLLISION_COUNT=0
UNSAFE_STATE_BIND_COUNT=0
UNSAFE_TRANSITION_BIND_COUNT=0
UNEXPECTED_CANDIDATE_CHURN_COUNT=0
UNEXPECTED_TRANSITION_CHURN_COUNT=0
UNEXPECTED_TRANSITION_SPLIT_COUNT=0
CROSS_LAYER_CONTRADICTION_COUNT=0
PYTHON_TEST_RESULT=3074 passed, 0 failed, 0 errors, 1 known skipped
PHASE2_PHASE3_REGRESSION_RESULT=401 passed, 0 failed, 0 errors
PRODUCTION_RUNTIME_CHANGED=NO
PRODUCTION_CONFIG_CHANGED=NO
HELPER_CHANGED=NO
HOME_IDENTITY_BLOCKER_REMAINS=YES
PHASE3_FINAL_VERDICT=PHASE3_PASS_WITH_LIMITATIONS
READY_FOR_PHASE4=NO
```

Final Git state (every untracked path is recorded in `output/phase3c_overlay_probe_20261005/final_git_state.txt`; 624 paths = preserved out/615 + Phase 3 files/9):

```text
git branch --show-current
feature/phase3c-transition-stability-closure


git status --short
 M docs/design/phase3b-transition-observation-contract.md
 M tb_runner/state_equality.py
 M tb_runner/state_registry.py
 M tb_runner/state_replay.py
 M tb_runner/transition_observation.py
?? docs/design/phase3-state-discovery-transition-closure.md
?? out/
?? tests/test_camera_alert_semantics.py
?? tests/test_camera_overlay_probe.py
?? tests/test_home_identity_closure.py
?? tests/test_phase3c_transition_closure.py
?? tools/camera_alert_diagnostic.py
?? tools/camera_overlay_probe.py
?? tools/home_identity_closure.py
?? tools/phase3c_transition_closure.py


git diff --stat
 .../phase3b-transition-observation-contract.md     | 27 +++++++----
 tb_runner/state_equality.py                        | 56 +++++++++++++++++++---
 tb_runner/state_registry.py                        | 47 +++++++++++-------
 tb_runner/state_replay.py                          | 15 +++---
 tb_runner/transition_observation.py                |  3 +-
 5 files changed, 109 insertions(+), 39 deletions(-)


git diff --name-only
docs/design/phase3b-transition-observation-contract.md
tb_runner/state_equality.py
tb_runner/state_registry.py
tb_runner/state_replay.py
tb_runner/transition_observation.py

```


---

## 26. Semantic Substate Modeling Closure (Phase 3D)

This Phase 3D section is the current result and supersedes the Phase 3C readiness value in §25.17. Earlier Phase 3C captures and verdicts remain historical evidence; they were not rewritten.

### 26.1 Problem and design decision

The earlier Home comparison treated card-local camera alert nodes as root identity evidence. Their appearance could make an otherwise complete Home observation ambiguous and prevent candidate and transition binding. Phase 3D keeps one logical Home state and records the camera card's observed condition as child semantic substates.

The new `semantic-substate-v1` records carry category, key, value, confidence, evidence, and provenance. The versioned `observed-discriminators-v2` sidecar is emitted when records exist. The camera adapter recognizes the camera-card and alert-node families under that card; it does not infer HUMAN/MOTION/PET from a resource ID. An explicit typed producer can supply those values later.

### 26.2 Root identity and substate contract

- Same complete root with a different allowed substate evaluates as logical `SAME`, with `semantic_substate_relation=DIFFERENT`.
- Different roots remain `DIFFERENT`. Incomplete root evidence and unverified Home context remain `AMBIGUOUS`.
- Only alert-node tokens explicitly named in their substate evidence are projected out of root comparison. The source nodes and semantic fields remain in the observation, serialized substate evidence, and replay inputs.
- Full-screen dialogs, system popups, permission sheets, plugin roots, and other context-significant state remain part of root identity.
- The Phase 2 timestamp normalization remains unchanged; a last-update timestamp alone does not split the root.
- Legacy v1 observations retain their original documents and checksums. A versioned in-memory adapter exposes their old camera-family evidence without rewriting those saved bytes. Untagged registry history is replayed with the legacy matching policy; new events record the semantic root policy explicitly.

### 26.3 Camera mapping and observations

The current live Home screen exposed the camera card and no alert-family nodes, so it mapped to `detection_event=NONE` and `overlay_state=ABSENT`. A preserved Phase 3C positive frame contains `camera_card_alert_background` and `camera_card_alert_animation_current`; replay maps it to `UNKNOWN/ACTIVE_UNKNOWN`, preserving the event and overlay evidence without claiming a live reproduction or guessing the event type. Older Home frames with no camera card map to `UNKNOWN/UNKNOWN` when the Samsung Home context is otherwise verified.

Across the Phase 3D model corpus (87 substate-bearing Home observations: 20 live passive, 42 historical Home replay, 1 separately replayed positive overlay frame, and 24 Home-rooted action-matrix captures), three value pairs were observed:

| `detection_event` | `overlay_state` | Evidence scope |
|---|---|---|
| `NONE` | `ABSENT` | 20 live passive, 18 historical, 24 action-matrix observations |
| `UNKNOWN` | `ACTIVE_UNKNOWN` | 3 historical observations and 1 separate preserved-frame replay |
| `UNKNOWN` | `UNKNOWN` | 21 historical observations |

`SUBSTATE_UNKNOWN_COUNT=25` counts observations containing at least one literal `UNKNOWN` value. No current live camera alert overlay was reproduced during the 20-observation passive run. The exact HUMAN/MOTION/PET value and a paired live-present TalkBack speech/focus comparison remain unobserved.

### 26.4 Equality, registry, and persistence

`StateRegistry` deduplicates Home at the logical root and stores semantic substate observations separately. The 20 live captures share `phase3d-device:state:00000001`; the 42 preserved Home observations replayed in an independent `phase3d-historical-home-replay` registry into one ID (1 `CREATED`, 41 `REUSED`). That replay included 18 `NONE/ABSENT`, 3 `UNKNOWN/ACTIVE_UNKNOWN`, and 21 `UNKNOWN/UNKNOWN` values. Registry save/load and a fresh-process replay produced identical IDs and bytes.

The focused model suite covers root/substate equality, Home versus Devices/Life, timestamp-only changes, incomplete Home, full-screen context changes, plugin and lock-state distinctions, state reuse/restart, candidate binding, transition evidence, passive-change attribution, and retained semantic-node evidence.

### 26.5 Candidate and transition integration

Discovery snapshots carry substate values and a deterministic substate hash while candidate identity remains attached to the logical root. Physical candidate differences remain observable. The live passive Home set had one physical candidate-set variant and zero unexpected churn or candidate ID collisions.

Transitions retain source and result substate evidence. A substate change between capture boundaries is recorded as unattributed to the last controlled action; the model does not infer action causality from temporal order alone. The fresh replay verified all 16 saved real-device transitions and 16 equality evaluations exactly, including evidence references and registry restart.

### 26.6 Targeted real-device validation

Device: Samsung SM-F741N, serial `R3CX40QFDBP`; Helper readiness passed before capture. No Full 32 run was performed.

| Metric | Result |
|---|---:|
| `HOME_OBSERVATIONS_TOTAL` (live passive) | 20 |
| `HOME_LOGICAL_STATE_RESOLVED` | 20 |
| `HOME_LOGICAL_STATE_UNRESOLVED` | 0 |
| `HOME_UNIQUE_LOGICAL_STATE_COUNT` | 1 |
| Live Home substate variants | `NONE/ABSENT` only |
| Home-origin controlled actions | 10 total, 10 mapped, 0 unmapped |
| `RETURN_TO_HOME_TRANSITIONS` | 4 |
| `RETURN_TO_HOME_AMBIGUOUS_COUNT` | 0 |

The ten Home-origin actions were two SMART_NEXT requests, two scroll-down/restore pairs, and four Home-to-Devices tab actions. All ten mapped to Home-root candidates. All four Devices→Home (2) and Life→Home (2) returns ended with the same resolved Home ID. The complete matrix recorded 16/16 mapped transitions, zero ambiguous sources/results, zero binding mismatches, and zero transition ID collisions. The two SMART_NEXT acknowledgements did not produce a confirmed focus-move signal in this matrix (`focus_confirmed=0/2`); that traversal-effect limitation is retained explicitly.

### 26.7 Safety and regression results

- Phase 2/3 focused Python regression: **391 passed**.
- Full Python suite from an isolated copy of the exact current tracked and untracked source plus the repository's required ignored acceptance fixtures: **3,089 passed, 5 skipped, 0 failed, 0 errors** (`pytest tests -q`, 83.89 s).
- The five skips are unchanged optional or unavailable fixtures: one missing `xlsxwriter` package and four missing frozen evidence ledgers.
- The first full run from the live workspace root had 3,057 passed, 1 skipped, and 36 setup errors. Each error was `PermissionError` while the test fixture tried to create a random child under the pre-existing `.test_tmp` directory. No ACL or test code was changed. The isolated full run exercised all 157 test files after preserving the candidate documents, referenced acceptance artifacts, content-addressed store, and V10 fixtures.
- Semantic serialization: 99 round-trip checks and 55 current-document checks had zero mismatch; 42 legacy documents retained their exact serialized bytes.
- Fresh-process historical Home replay mismatch: 0. Action transition replay mismatch: 0/16.
- Phase 3A/3B/3C replay audit (16 device transitions): `STATE_COLLISION_COUNT=0`, `CANDIDATE_ID_COLLISION_COUNT=0`, `TRANSITION_ID_COLLISION_COUNT=0`, `UNSAFE_STATE_BIND_COUNT=0`, `UNSAFE_TRANSITION_BIND_COUNT=0`, `UNEXPECTED_CANDIDATE_CHURN_COUNT=0`, `UNEXPECTED_TRANSITION_CHURN_COUNT=0`, `UNEXPECTED_TRANSITION_SPLIT_COUNT=0`, `CROSS_LAYER_CONTRADICTION_COUNT=0`, `VALIDATION_FAILURE_COUNT=0`.
- Negative safety tests continue to reject root collapse for different tabs, partial observations, full-screen overlays, plugin roots, and state-significant lock/error/context changes.

### 26.8 Approximate local performance

Synchronous local measurements used saved Home observations, 120 samples per operation (60 for first registry observation), and no ADB wait:

| Operation | Median | p95 |
|---|---:|---:|
| Camera substate extraction | 3.90 µs | 5.10 µs |
| Home normal vs preserved overlay equality | 28.25 ms | 46.63 ms |
| First registry observation | 45.18 ms | 52.05 ms |
| State-observation JSON serialization | 6.48 ms | 8.35 ms |
| Full observation build with camera adapter | 108.12 ms | 121.22 ms |
| Full observation build comparison without Home adapter | 88.13 ms | 104.32 ms |
| Approximate median build delta | +19.99 ms | — |

These are machine-local diagnostic timings, not a device latency guarantee.

### 26.9 Production isolation and limitations

`PRODUCTION_RUNTIME_CHANGED=NO`; `PRODUCTION_CONFIG_CHANGED=NO`; `HELPER_CHANGED=NO`. The Phase 3C baseline audit still matches all 615 `out/` files, all 3 config files, and all 41 Helper files byte-for-byte. `config/runtime_config.json` remains SHA-256 `6dd5d8a191d21e4366ed2513627d97b37515a1e2ae9c2ed342b8d2317fecb964`.

Remaining non-blocking limitations: no live camera overlay event occurred during this run; the accessible tree supports only `UNKNOWN` for an observed alert-family event, not HUMAN/MOTION/PET; no paired live-present speech/focus comparison exists; and this matrix did not confirm SMART_NEXT focus movement. The root model does not hide those limits.

### 26.10 Phase 3D gate

```ini
SEMANTIC_SUBSTATE_MODEL_IMPLEMENTED=YES
ROOT_STATE_SUBSTATE_SEPARATION_VERDICT=PASS
HOME_OBSERVATIONS_TOTAL=20
HOME_LOGICAL_STATE_RESOLVED=20
HOME_LOGICAL_STATE_UNRESOLVED=0
HOME_UNIQUE_LOGICAL_STATE_COUNT=1
HOME_SUBSTATE_VARIANTS=NONE/ABSENT; UNKNOWN/ACTIVE_UNKNOWN; UNKNOWN/UNKNOWN
SUBSTATE_OBSERVATIONS_TOTAL=87
SUBSTATE_VARIANT_COUNT=3
SUBSTATE_UNKNOWN_COUNT=25
SUBSTATE_REPLAY_MISMATCH_COUNT=0
SUBSTATE_SERIALIZATION_MISMATCH_COUNT=0
HOME_ACTIONS_TOTAL=10
HOME_ACTIONS_MAPPED=10
HOME_ACTIONS_UNMAPPED=0
HOME_ACTION_MAPPING_BLOCKERS=0
RETURN_TO_HOME_TRANSITIONS=4
RETURN_TO_HOME_AMBIGUOUS_COUNT=0
STATE_COLLISION_COUNT=0
STATE_BINDING_MISMATCH_COUNT=0
CANDIDATE_ID_COLLISION_COUNT=0
TRANSITION_ID_COLLISION_COUNT=0
HISTORICAL_HOME_REPLAY_OBSERVATIONS=42
HISTORICAL_HOME_REPLAY_UNIQUE_STATE_COUNT=1
UNSAFE_STATE_BIND_COUNT=0
UNSAFE_TRANSITION_BIND_COUNT=0
UNEXPECTED_CANDIDATE_CHURN_COUNT=0
UNEXPECTED_TRANSITION_CHURN_COUNT=0
UNEXPECTED_TRANSITION_SPLIT_COUNT=0
CROSS_LAYER_CONTRADICTION_COUNT=0
PYTHON_TEST_RESULT=3089 passed, 5 skipped, 0 failed, 0 errors
PHASE2_PHASE3_REGRESSION_RESULT=391 passed; 16/16 saved device transitions replayed exactly
PRODUCTION_RUNTIME_CHANGED=NO
PRODUCTION_CONFIG_CHANGED=NO
HELPER_CHANGED=NO
HOME_IDENTITY_BLOCKER_REMAINS=NO
PHASE3_FINAL_VERDICT=PHASE3_PASS_WITH_LIMITATIONS
READY_FOR_PHASE4=YES
PHASE4_IMPLEMENTED=NO
```

Phase 4 may begin with the root identity contract closed. Camera event typing and traversal-effect validation remain explicit follow-up limitations; Phase 4 was not implemented here.
