# Phase 4B controlled smart traversal execution

## Scope and source gate

Work is confined to `integration/phase3-current-main`, starting at
`ef3d1c92bdbb4716a1b0525ba715622c75f52756`. The accepted main and origin/main
remain `6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`; the original Phase 3 branch
remains `fb4d01c489a0b3d56883e074771eb823c453d4f2`. The starting tracked worktree
was clean. No Helper, Camera termination, Family Care production logic, Phase
4C or Phase 5 changes are part of this implementation.

Normal production never imports the Phase 4B adapter. Controlled authority is
available only through `tools.phase4b_controlled_smoke` with explicit
`TB_PHASE4B_CONTROLLED=1`, a supported scenario and a temporary configuration
with exactly five total traversal steps. Production configuration is unchanged.

## Authority contract

`tb_runner.phase4b_authority.execution_gate` is deterministic and performs no
device I/O or ledger writes. Modes are SHADOW_ONLY, CONTROLLED_TARGET_FOCUS,
CONTROLLED_SCROLL and FALLBACK_PRODUCTION. Unknown evidence denies authority.

The gate recomputes the original shadow recommendation, rejects forged
recommendations, then revalidates the selected action against a separate fresh
observation and a new planner ranking. It checks recovery, lifecycle, transport,
actual accessibility focus coherence, observed context, current geometry,
positive enabled/focusable flags, inventory presence, production positional
identity, stale aliases, current focus and verified transition value. The
candidate must remain the highest-ranked eligible recommendation.

Partial context permits read-only structural focus when independently proven.
Plugin assumptions require verified plugin context. No scenario-name inference
supplies safety. An unresolved diagnostic state can authorize structural focus
only with unchanged fingerprint/viewport, the same independently observed
package/activity scope, exact current target metadata and coherent focus.
Changing observation-scoped diagnostic IDs never replace the production
instance identity. Unknown enabled state is denied even though Phase 4A can
rank such an observation.

## Production focus and reconciliation

The adapter calls the existing production
`_maybe_realign_focus_to_representative` / `target_focus_commit` path. Its
durable production target-attempt ledger records the attempt independently of
ACK success. The Helper result must match the exact active request ID. There
is no alternate low-level focus implementation and no activation/click.

The production collector observes post-action accessibility focus with
`move=False`, closes the target evidence transaction, and returns a normal
production row. Previous SMART_NEXT caches are cleared for this target-only
collection. Target metadata cannot overwrite the collected actual focus.
The opt-in reconciliation wrapper supplies the fresh strict before-focus row
to the unchanged production reconciliation function. The original main loop
then retains representative processing, visit gates, metrics and persistence.

A pure production reconciliation preview selects fallback; its credit is never
applied. Final audit visit credit copies the production RECORDED outcome.
Phase 4B itself grants zero visits. ACK success with unchanged focus, false
input-focus fallback, and stale request results do not grant controlled visits.
ACK failure with confirmed matching actual movement remains valid production
movement. A stale result is never attributed to the target; the normal fallback
transaction is recorded separately.

## Fallback and budgets

Each production step has at most one controlled action and one immediate
production SMART_NEXT fallback. Failed, unchanged, indeterminate or mismatched
target actions record PLANNER_ACTION_FAILED and use that bounded fallback.
Denied authority forwards the original collection arguments and returned row
unchanged. Lifecycle restart evidence leaves immediate stopping to the existing
main loop and supervisor; no fallback is issued after a confirmed restart.

There are at most five controlled actions per scenario and five total traversal
steps. The budget records target attempts, consecutive selections, repeated
results, inventory/state stability, scroll attempts and fallback count. Two
consecutive controlled results without progress disable execution for the
remaining scenario. Repeated targeting without a new production visit also
degrades to production. This temporary disablement is reset only at the next
independently validated scenario.

## Vertical scroll

Only a planner-recommended vertical opportunity after higher-value focus
candidates are exhausted can pass the scroll gate. It requires axis-v1,
positive forward capability, a known production container path and matching
geometry, no exhaustion and no contradiction. The actual production capture
revalidates the container immediately before the existing `verified_scroll`
call. No arbitrary swipe coordinates are introduced.

Before/after viewports and production scroll results classify SCROLL_MOVED,
SCROLL_NO_MOVEMENT or SCROLL_INDETERMINATE. Every result refreshes hierarchy,
Phase 3 state/substate, inventory, identities, current focus and recommendation.
After movement the old ranking is discarded. Uncertain/no movement uses one
production fallback; it never authorizes a second scroll retry within the step.

## Audit and staged acceptance

`phase4b_observations.jsonl` saves original and fresh observations, immutable
snapshots, real production history, planner flags, recommendation and gate.
`phase4b_execution_trace.jsonl` records scenario/step/state/context, action,
target/rank/reasons, gate evidence/result/reason, execution mode, actual
production action/target, target request/ACK and separate fallback request/ACK,
before/after actual focus, production reconciliation, copied attempt/visit
credit, fallback, scroll refresh and loop budget. Final production terminal
status/reason is attached after scenario completion.

The local fix also emits `phase4b_action_audit.jsonl` before and after controlled
actions and fallback, before final row persistence. This preserves action
evidence even if a later collection is interrupted. The interrupted original
Devices action is reconstructed separately from its saved pre-step and durable
production target ledger; missing final movement/visit outcomes remain unknown.

Classifications are PLANNER_EXECUTED, PLANNER_BLOCKED_BY_GATE,
PLANNER_FAILED_FALLBACK_USED, PLANNER_NO_SAFE_ACTION and PRODUCTION_ONLY.

The supervisor reuses the accepted clean-start and exact request-correlated
lifecycle monitor. It validates foreground SmartThings, bottom navigation,
absence of modal state, valid start state, stable locale and PIDs before every
normal production entry. The staged order is strictly sequential:

1. Home, Devices.
2. Find, Smoke Sensor, only after both Stage 1 scenarios pass.
3. Food, Family Care, only after both Stage 2 scenarios pass.

No scenario retry is automatic. A fresh output root is required. Scenario
validation requires normal entry, five observed steps, a real controlled
action, production terminal evidence, confirmed movement and zero authority
violations. The supervisor stops before the next scenario on failure and
immediately terminates a child on confirmed lifecycle/transport hard evidence.
Unanchored strings and false-valued JSON keys do not trigger a stop.

## Validation results

**OVERALL_VERDICT=PHASE4B_CONTROLLED_EXECUTION_REJECT**

**READY_FOR_PHASE4C=NO.** The local implementation is complete and its adapter
fix passes offline tests, but the staged live acceptance failed. No integration
commit or push was made. Integration HEAD and origin integration remain at the
starting commit. Main's tracked worktree is clean, its refs are unchanged, and
the original Phase 3 branch ref is unchanged.

### Source and offline evidence

The initial source gate passed with a clean tracked integration worktree. Final
source changes are local to that worktree. The production runner, runtime
configuration, Helper and production Camera/Family Care files are unchanged.

- Final authority/harness: **41 passed**.
- Existing Phase 4A planner/harness: **37 passed**.
- Phase 3/adapters: **456 passed**.
- Production regression: **320 passed**.
- Additional focus/visit/starvation/scroll/completeness evidence: **193 passed**.
- Final full Python: **3,586 passed, 1 skipped**, versus 3,545 passed, 1 skipped
  before Phase 4B. An earlier full run before the local fix also passed (3,577
  passed, 1 skipped). Helper tests are NOT_REQUIRED because Helper is unchanged.
- Historical transitions: **16/16 exact**, with and without authority sidecars.
- Accepted baseline: **6/6 replayed**; all six authority decisions denied
  because the saved partial captures lack an independent strict current focus.
- Phase 4A inputs: **30/30 exact recommendation replay**, 29 hypothetical
  authorizations and one denial for indeterminate focus. This never executed a
  live action or awarded a visit. Source evidence hashes remain unchanged.

### Staged device result

Device `R3CX40QFDBP` remained at **en-US**. TalkBack PID **19549** and Helper
PID **12034** stayed unchanged. All ten lifecycle/transport hard gate counts
are **0**. The accepted supported clean-start passed before Home and Devices;
both used normal production entry. The monitored session ran from
2026-10-11 02:13:14.598902 UTC to 02:17:12.788823 UTC (238.19 seconds).

| Scenario | Entry | Completed steps | Authorized/executed targets | Failed target outcomes | Fallbacks | Confirmed final moves/new visits | Terminal/result |
|---|---|---:|---:|---:|---:|---|---|
| Home | PASS | 5 | 5/5 | 2 | 2 | 5/5 | INCOMPLETE_SAFETY_LIMIT; acceptance REJECT |
| Devices | PASS | 0 (step 1 interrupted) | 1/1 | Unknown final outcome | Unknown | Unknown; not counted | INTERRUPTED_FIRST_STEP |
| Find | NOT_STARTED | 0 | 0/0 | 0 | 0 | 0/0 | NOT_RUN_STAGE1_REJECTED |
| Smoke Sensor | NOT_STARTED | 0 | 0/0 | 0 | 0 | 0/0 | NOT_RUN_STAGE1_REJECTED |
| Food | NOT_STARTED | 0 | 0/0 | 0 | 0 | 0/0 | NOT_RUN_STAGE1_REJECTED |
| Family Care | NOT_STARTED | 0 | 0/0 | 0 | 0 | 0/0 | NOT_RUN_STAGE1_REJECTED |

Totals: six recommendations, six authorizations, six actual target attempts,
five completed traversal steps, two known failed target outcomes, two observed
fallbacks and five production-confirmed new visits. No controlled scroll was
recommended or executed. The interrupted Devices step has a MATCHED production
target ledger with exact Helper request ID, but no final persisted row or
production reconciliation. Its movement/visit is unknown and excluded from
the confirmed totals. The scroll path is implemented and unit verified; live
controlled scroll remains unproven.

The original per-scenario validator accepted Home based on entry, five steps,
actual actions, normal terminal and five final production moves. Artifact
review identified a more specific before-focus contract failure while Devices
was starting its first step. The agent stopped that exact child; the supervisor
saved its interrupted result and did not start Stage 2 or Stage 3. The original
Home stage decision is archived as `home_main_original_stage_gate.json`; the
stricter final acceptance is REJECT. There was no automatic scenario retry.

Windows Stop-Process and taskkill attempts failed with OS execution errors.
After verifying the exact child PID, Python termination stopped that child and
allowed the supervisor to finalize its monitor evidence. No other process,
TalkBack or Helper was terminated.

### Proven regression and local fix

Home steps **1 and 3** began with a real strict Helper focus whose resource ID,
`text` and `contentDescription` were null, while `talkbackLabel` contained the
observed device label. The initial Phase 4B `focus_row` adapter copied only
`text`/`contentDescription`. It lost the before-focus identity even though the
fresh tree and get-focus observations agreed. Both exact target ACKs were
TARGET_MATCHED, but the production reconciliation preview became UNAVAILABLE,
causing unnecessary fallback.

Production fallback remained bounded and produced real movement. No invented
visit, stale result attribution or lifecycle failure was found. Nonetheless,
the adapter violated the promised coherent before/after reconciliation and
caused a 2/5 unexpected fallback rate. Therefore
**CONTROLLED_EXECUTION_REGRESSION=YES**. The five final Home visits equal the
recent five-step production reference; the failure is reconciliation fidelity
and fallback rate, not a catastrophic final visit drop. Five-step evidence
cannot establish complete content reachability. Family Care state/performance
comparison is NOT_RUN.

The local fix now uses the existing production bounds normalizer and preserves
`talkbackLabel`/`mergedLabel` as observed labels. Focus coherence also requires
an extractable production identity. Tests cover both real Helper label shapes,
dictionary bounds, unknown identity denial, repeated movement without a new
visit, durable action events, and production recovery bypassing the controlled
collector. That existing recovery path retains its original arguments and row
while receiving a PRODUCTION_ONLY audit. The stage validator now rejects a lost
before-focus identity despite a positive initial coherence gate.

Offline replay of the two saved immediate actual focus captures now produces
CONFIRMED_MOVED and the exact positional before identities. This applies zero
visit credit, preserves all original raw evidence hashes, and **does not turn
the failed live run into a pass**. The fix was not rerun on the device.

### Artifacts and next step

Artifacts are under the integration worktree's parent:
`phase4b_controlled_acceptance_20261011/`.

- `final_report.txt` / `final_report.json`: all requested final report keys.
- `stage1_stop_review.json`: original decision, stricter acceptance, test
  counts, comparison, stop scope and unchanged source hashes.
- `phase4b_execution_trace.jsonl`: five original completed step audits.
- `phase4b_execution_trace_reviewed.jsonl`: original five audits plus the
  evidence-backed interrupted Devices action, with unknown outcomes preserved.
- `adapter_fix_offline_replay.json`: two exact captured before-focus cases.
- `production_comparison.json`: five-step Home production comparison.
- `per_scenario_metrics.json`: every requested per-scenario metric, preserving
  null values for interrupted outcomes that were not reconciled.
- `monitor_result.json`, `monitor.jsonl`, `runner.log`, `logcat.txt`,
  preconditions, raw observations and production attempt/evidence ledgers.

Sibling `phase4b_final_gate_replay_20261011/` contains the final historical,
accepted baseline and Phase 4A input replays. Sibling `phase4b_final_*.xml`
contains the final test results.

The next step is a separately authorized acceptance run of the fixed local
adapter, starting again at Stage 1. Later stages remain blocked until Stage 1
passes. Phase 4C and Phase 5 remain unimplemented, and normal production
planner execution remains OFF.

## Controlled acceptance retry after before-focus fix — 2026-10-11

Verdict: **PHASE4B_CONTROLLED_EXECUTION_REJECT**.
**READY_FOR_PHASE4C=NO**. The Home label-preservation regression is resolved;
the retry exposed a separate controlled target resolution blocker at Smoke
sensor. No planner policy, production action path, Helper, Camera, Family
Care, Phase 4C or Phase 5 change was made during this retry. No commit or push
was performed because acceptance did not pass.

### Source and regression gates

The existing integration worktree was retained on
`integration/phase3-current-main`. Fetch and checkout completed without a
pull. Initial/final local and origin integration HEAD remained
`ef3d1c92bdbb4716a1b0525ba715622c75f52756`; the uncommitted Phase 4B fix was
preserved. The tracked modification remained the opt-in supervisor extension
in `tools/phase4a_shadow_monitor.py`; the Phase 4B implementation and tests
were still untracked local files.

Main and origin/main remained
`6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`, and the original Phase 3 branch
remained `fb4d01c489a0b3d56883e074771eb823c453d4f2`. Main's tracked worktree
was clean. The tested implementation source hashes did not change during
acceptance.

The fixed before-focus adapter preserves observed `talkbackLabel` and
`mergedLabel`, uses production bounds normalization, and still requires real
accessibility focus. It does not promote input focus, create visits, or change
exact request correlation. Focused regressions passed **41/41**; the full
Python suite passed **3586**, with **1 skipped and 0 failed**, before any live
scenario started. Fresh offline replay passed historical16, accepted6 and
Phase 4A input30, with no actions or applied visit credit.

### Staged live result

The single retry ran from **03:08:29.576005 to 03:18:36.827719 UTC**
(607.251714 seconds). Device serial `R3CX40QFDBP`, locale `en-US`, TalkBack
PID `19549`, and Helper PID `12034` remained unchanged. Every started scenario
had a validated SmartThings foreground, bottom navigation, no modal and valid
clean start, followed by normal production entry. There was no manual scenario
correction, Full32, individual rerun or automatic acceptance retry.

| Stage | Scenario | Traversal steps | Controlled executions | Production fallbacks | Confirmed moves / new visits | Acceptance |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | Home | 5 | 5 | 0 | 5 / 5 | PASS |
| 1 | Devices | 5 | 5 | 0 | 5 / 5 | PASS |
| 2 | Find | 5 | 4 | 1 | 5 / 5 | PASS |
| 2 | Smoke sensor | 5 | 0 | 5 | 5 / 5 | FAIL |
| 3 | Food | Not run | Not run | Not run | Not run | NOT_RUN |
| 3 | Family Care | Not run | Not run | Not run | Not run | NOT_RUN |

Stage 1 passed before Stage 2 started. Home observed **one real label-only
before-focus case**, with preserved before identity, exact correlated target
result and `CONFIRMED_MOVED`. Devices observed zero label-only cases. Both
false UNAVAILABLE counts were **zero**. All completed steps across the retry
had production-confirmed movement and production-owned visit accounting;
Phase 4B applied zero visits.

Find's single fallback was a legitimate `RECOVERY_CONFLICT`: controlled
authority yielded to existing production recovery. Find and Smoke sensor had
verified plugin context. After Smoke sensor completed, its acceptance
validator rejected `NO_REAL_CONTROLLED_ACTION` and the supervisor stopped
before Stage 3. The five-step `INCOMPLETE_SAFETY_LIMIT` terminals were the
intended smoke bounds, not entry failures or anchor aborts.

### New blocker: positional identity aliases multiple raw nodes

Smoke sensor steps 1 and 2 recommended a read-only focus target: a focusable
`android.webkit.WebView`, empty resource ID and bounds `0,0,1080,2640`.
The fresh gate allowed the candidate. The execution adapter then searched raw
nodes using production positional identity, which is scoped by scenario,
resource ID and bounds. It found **four** nodes with that same identity:

- one non-focusable FrameLayout;
- one non-focusable WebView;
- one focusable WebView;
- one non-focusable View.

It conservatively rejected each resolution as
`TARGET_DISAPPEARED_OR_AMBIGUOUS` before issuing a controlled Helper request.
After the two consecutive failures it degraded to production for the remaining
three steps. Every fallback still produced a confirmed move and new visit.
The five-step production comparison shows no visit drop; the acceptance
blocker is failure to exercise controlled targeting for this scenario.

This is a candidate-to-node binding gap between the gate and adapter. Class
filtering alone would still leave **two WebViews** and is insufficient.
Selecting the first match or weakening identity/focus checks is not an
acceptable fix. A subsequent focused task must prove a fresh, unambiguous
binding and Helper target resolution while preserving production visit
identity, accessibility-focus evidence and exact request correlation. No new
implementation or live retry was attempted after this hard acceptance failure.

### Totals, hard gates and limitations

The retry recorded **20 recommendations, 16 authorizations, 14 real controlled
executions, 4 blocked recommendations, 2 pre-execution resolution failures,
6 production fallbacks, 20 confirmed moves and 20 new production visits**.
All ten lifecycle/transport gates were **zero**: TalkBack PID changes,
unexpected Helper PID changes, window fatal, fatal BadToken, Helper ANR,
SMART_NEXT timeout/error, FOCUS timeout/error, chunk error, inspection
suppression and TalkBack reconnect. No unsafe controlled targeting or fabricated
visit was observed.

There were no live scroll recommendations or controlled scroll executions.
Scroll, stale/failing ACK handling, bounded fallback and degradation paths
remain regression-tested. Five-step smoke cannot prove full content coverage.
Food's partial context and Family Care performance/state were not observed in
this retry and are not inferred from other scenarios or earlier runs.

Artifacts are under the sibling directory
`phase4b_controlled_retry_20261011/`: source gate, validated preconditions,
raw observations, durable action audit, execution trace, per-scenario acceptance,
production ledgers, correlated monitor logs, comparison, RCA and final report.
`smoke_sensor_resolution_rca.json` replays both exact saved fresh observations
without device actions or visit writes and verifies original artifact hashes
are unchanged. Sibling `phase4b_retry_focused.xml`,
`phase4b_retry_full_python.xml` and `phase4b_retry_gate_replay_20261011/`
contain the current test and offline replay results. The next step is a focused
Smoke sensor controlled target binding investigation and fix, followed by a
separately authorized staged acceptance retry. Phase 4C remains blocked.

## Candidate identity collision recovery — 2026-10-11

### Existing identity contract and implementation trace

| Boundary | Functions / files | Identity and authority |
| --- | --- | --- |
| Hierarchy acquisition and flattening | `talkback_lib/hierarchy_snapshot.py`: `service_hierarchy_to_xml`, `flatten_service_hierarchy`; `tools/state_fingerprint_diagnostic.py`: `capture_observation`; `tb_runner/global_navigation.py`: `xml_nodes` | Current service hierarchy supplies bounds, flags, class, observed paths and ancestor metadata. Capture is sequential; it is not an atomic UI transaction. |
| Candidate extraction | `tb_runner/completeness.py`: `candidate`, `eligibility`; `tb_runner/discovery_candidates.py`: `_node`, `_target`, `_semantics`, `_collect`, `build_discovery_snapshot` | Normalizes current nodes, retains observed semantics, and emits focus candidates only for observed focusable nodes. Non-actionable blank wrappers are excluded. Multiple semantic variants of the same discovery target remain excluded. |
| Instance identity | `tb_runner/traversal_reliability.py`: `instance_id`, `normalized`, `normalized_bounds`; `tb_runner/phase4a_planner.py`: `production_instance` | Production `instance-v1` is scoped by normalized scenario and resource ID, then exact bounds. Without bounds it uses container/path, then unresolved label/class. Paths and mutable labels do not replace valid bounds. Geometry-free identity cannot prove a physical visit. |
| Discovery / planner identity | `tb_runner/discovery_candidates.py`: `_target`, `_collect.add`; `tb_runner/phase4a_planner.py`: `production_instance`, `plan_shadow` | Discovery candidate ID hashes schema, state scope, action kind and target metadata including class. Labels, current focus and timestamps are evidence. The planner re-scopes the existing instance oracle to the production scenario when consulting history. |
| Attempt ledger and history | `tb_runner/target_attempt_ledger.py`: `TargetAttemptLedger.begin`, `finish`, `reconcile`; `tb_runner/focus_realign_logic.py`: `_maybe_realign_focus_to_representative_impl`; `tb_runner/phase4a_inputs.py`: `project_history`, `runtime_input` | Each request creates a durable attempt with a target descriptor and exact Helper request ID. Attempts remain distinct from visits. Production history uses the same resource/bounds instance oracle; no new canonical ID replaces its counters. |
| Reconciled visits | `tb_runner/focus_reconciliation.py`: `_strict_focus_proof`, `_actual_item`, `_candidate_matches`, `reconcile_focus`, `apply_reconciliation_to_row`; `tb_runner/traversal_reliability.py`: `focus_instance`, `TraversalMetrics.observe_focus`, `observe_reconciliation`; `tb_runner/content_terminal.py`: `ContentTerminal.observe` | Actual accessibility focus and before/after reconciliation own physical visit evidence. ACK does not establish movement. Phase 3/4 observations and previews do not apply visits. |
| Controlled execution binding | `tb_runner/phase4b_target_binding.py`: `resolve_focus_target`, `actual_target_matches`; `tb_runner/phase4b_execution.py`: `controlled_collect` | Fresh raw binding uses existing positional identity, exact selected class, focusability, enabled/visible evidence and observed wrapper relationship. Landing must also match the target's actual class, resource ID and bounds. |
| Transport target resolution | `talkback_lib/__init__.py`: `_target_focus_commit_impl`; Helper `A11yCommandReceiver`, `A11yHelperService.performTargetFocusCommit`, `TargetFocusMatcher.resolve`, `sameIdentity` | Exact bounds and supplied resource/label/class metadata are matched. An explicit controlled `requireFocusable` predicate filters non-focusable/disabled nodes; remaining ambiguity is rejected. Normal requests retain the existing default predicate OFF. |

Current identity field behavior:

- **Resource ID and bounds:** production identity fields; repeated resource IDs
  with different bounds remain distinct.
- **Class:** discovery target metadata and execution/landing discriminator;
  excluded from the production bounds-based identity.
- **Text/contentDescription/talkbackLabel:** observed semantic/focus evidence;
  dynamic text does not create a new bounds-based production instance.
- **Center point:** diagnostic geometry only; not an identity field.
- **Hierarchy path, child index, parent metadata:** observed structural evidence;
  paths are only a legacy fallback when bounds are absent. The new resolver
  uses current ancestor/descendant paths to prove wrapper equivalence, never
  appends a volatile XML index to a durable ID.
- **Accessibility properties, clickable/focusable/enabled/visible state:**
  eligibility and execution safety evidence, not new production identity fields.
- **Accessibility-focused and input-focused:** separate evidence. Input focus
  alone never becomes accessibility focus or a physical visit.

### Proven four-node classification

The exact saved Smoke sensor fresh observations from steps 1 and 2 both show
the following chain with empty resource IDs, text and content descriptions,
bounds `0,0,1080,2640`, and center `(540,1320)`:

| Raw index | Class | Hierarchy path | Focusable | Clickable | Accessibility focused | Input focused |
| ---: | --- | --- | --- | --- | --- | --- |
| 0 | FrameLayout | `0.0` | false | false | false | false |
| 1 | WebView | `0.0.0` | false | false | false | false |
| 2 | WebView | `0.0.0.0` | true | false | false | true |
| 3 | View | `0.0.0.0.0` | false | false | false | false |

All are enabled and visible. Parent resource/class/bounds and child index are
reconstructed from the saved current hierarchy paths, not from assumed traversal
order. Full names, fields and both cases are in `collision_rca.json`.
`talkbackLabel` was not retained by the historical XML projection and is reported
as **unknown**, rather than invented from blank text. The saved ancestry proves
parent/child relationships, and one observed WebView is focusable. No evidence
supports four distinct actionable controls or a stale duplicate capture.

**COLLISION_CLASSIFICATION=B: parent/child presentation wrappers around one
logical accessibility focus target. ROOT_CAUSE_PROVEN=YES.** The discovery
snapshot already has one eligible WebView focus candidate and zero discovery-ID
collisions. The initial execution adapter discarded that stronger candidate
metadata by matching every raw node solely against production positional
identity. Its lookup found four aliases. Helper class-only lookup would still
find two WebViews.

### Minimum generic fix and versioning

Resolution is **FILTER_NON_ACTIONABLE_WRAPPERS +
PROMOTE_CANONICAL_ACTIONABLE_NODE**, with current hierarchy proof. No scenario
name, plugin resource, WebView-specific branch or English/Korean label is used.

`resolve_focus_target` retains the production identity and requires exactly one
fresh class-compatible, visible, enabled, focusable node. When multiple raw
nodes share that positional identity, every other node must have a distinct,
observed ancestor/descendant path and be non-clickable, non-focusable,
non-accessibility-focused and without an independent semantic label. Missing
flags/paths, separate siblings, semantic controls, multiple focusable controls,
and repeated paths are denied. It does not pick the first raw match.

Controlled execution temporarily adds `require_focusable=True` to the existing
production target commit call and restores the client method in `finally`.
Python transmits typed `requireFocusable=true` only for literal opt-in True.
Helper matches the current visible root again and additionally requires
`isFocusable && isEnabled`. More than one remaining target still returns
AMBIGUOUS. The receiver, dispatcher, request ID, ACK emission and durable
attempt ledger are retained. Actual target landing must match exact class,
resource ID and bounds as well as true accessibility focus; a positional alias
alone cannot verify the controlled target.

**IDENTITY_SCHEMA_CHANGED=NO. IDENTITY_VERSION=instance-v1.** No migration,
new visit ID, new starvation-history key or added planner candidate is required.
`phase4b-target-binding-v1` is a diagnostic proof schema, not a replacement
candidate/visit identity. The additive Helper predicate defaults OFF; normal
production calls and accepted Phase 3/4A behavior retain their prior contracts.
Planner ranking policy, Camera termination and Family Care logic are unchanged.

### Contract verification and tests before live acceptance

| Contract | Verification |
| --- | --- |
| CONTRACT_01 | PASS: same resource ID with different bounds remains distinct. |
| CONTRACT_02 | PASS: canonical binding returns the existing production key used by both attempt and visit reconciliation. |
| CONTRACT_03 | PASS: dynamic label changes retain the bounds-based key. |
| CONTRACT_04 | PASS: durable target attempt and physical visit remain separate. |
| CONTRACT_05 | PASS: false accessibility focus/input-only fallback applies no visit. |
| CONTRACT_06 | PASS: successful ACK without movement applies no new visit. |
| CONTRACT_07 | PASS: failed ACK with actual target accessibility movement still reconciles as movement. |
| CONTRACT_08 | PASS: diagnostic snapshots, planner decisions and reconciliation previews never apply production visits. |
| CONTRACT_09 | PASS: stale/mismatched request evidence is not attributed; only fresh production fallback can record its actual move. |
| CONTRACT_10 | PASS: changed labels/hierarchy prefixes preserve prior attempt/visit counts and starvation history. |

Focused regressions passed **295**. Full Python passed **3613**, with **1
skipped, 0 failed**, including 27 new Python cases. Full Helper passed **408**
tests, with 0 failures/errors/skips. APK build succeeded. Fresh replay passed
historical16, accepted6 and Phase4A-input30. Exact saved collision replay selects
the same canonical node in both observations, preserves all original source
hashes and applies zero visits or device actions. These offline results do not
by themselves establish live acceptance.

The built and installed APK SHA-256 is
`25e4f3c491ebb2e2c6b67f7ba4359e4f91983d892619e3fbb7518d00c1afee03`.
Helper reconnected as PID `18024` after the update; TalkBack remained `19549`
and locale remained `en-US`. The first immediate post-install PID read occurred
during reconnection and failed; verification then succeeded without reinstalling.
`helper_install.json` distinguishes the last accepted baseline from the later
verification reads. Live acceptance uses the stable new Helper PID as baseline.

Recovery artifacts are in the sibling `phase4b_collision_recovery_20261011/`
directory. Stage 1, then Stage 2, then Stage 3 must pass in order. A failed
stage stops the supervisor; there is no automatic scenario correction or retry.

### Acceptance validator correction and continuation

The first segment (`acceptance/`) completed Home, Devices and Find once each.
An additional acceptance check then falsely rejected Find: it compared final
production focus with the earlier controlled target. Find step 1 had a fresh,
correlated Helper request and immediate accessibility focus on `menu_button`;
the controlled preview confirmed that move. Later production realignment moved
to `current_location_btn`, and production correctly reconciled and credited
that final actual target. Requiring the later focus to remain on the earlier
planner target was a validator error, not an unsafe controlled action.

`controlled_target_evidence_failures` now checks immediate target metadata,
correlated request, explicit Helper predicate and preview movement at the
controlled boundary, then independently checks final actual focus against final
production reconciliation. It never applies visits. Nine regression cases
cover this boundary, including wrong/stale/falsely focused evidence. After the
correction, focused Python passed **304**, full Python **3622 passed, 1 skipped,
0 failed**. Helper remains **408 passed**; execution/identity/Helper code and the
installed APK were unchanged between the two live segments.

Original Find rejection, logs and monitor result are preserved. A separately
named reviewed acceptance records the proven false positive. After offline
verification and a stable PID/locale checkpoint, only the unstarted Smoke
scenario was continued in `acceptance_continuation/`; Home, Devices and Find
were not rerun. The combined report explicitly retains the validator pause,
both original monitor paths and artifact hashes. Monitoring covers each live
execution segment; continuous monitoring during the test/review pause is not
claimed.

### Final recovery verdict: REJECT

| Stage | Scenario | Steps | Controlled attempts | Confirmed controlled moves | Fallbacks | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | Home | 5 | 5 | 5 | 0 | PASS |
| 1 | Devices | 5 | 5 | 5 | 0 | PASS |
| 2 | Find | 5 | 4 | 4 | 1 | PASS after validator evidence review |
| 2 | Smoke Sensor | 4 | 2 | 0 | 4 | REJECT |
| 3 | Food | 0 | 0 | 0 | 0 | NOT RUN |
| 3 | Family Care | 0 | 0 | 0 | 0 | NOT RUN |

Smoke's first target reproduced the four-node wrapper chain. Binding resolved
exactly one eligible node at `0.0.0.0`; Helper returned correlated
`TARGET_MATCHED` and strict immediate accessibility focus on that WebView.
The positional ambiguity is therefore resolved in the live observation.
The second target was a unique anonymous TextView. Both immediate targets had
empty resource ID and all label fields. Existing
`traversal_reliability.observed_focus_instance` requires `(resource ID OR label)`
plus bounds, and returns no identity for both immediate observations.
Controlled previews were `UNAVAILABLE`; later collected focus also cannot be
credited using an earlier target ACK. The full cause of those later collection
transitions is not proven here; their captured focus sequence is retained in
`new_live_blocker.json`.

Each uncertain action used production fallback. Two consecutive uncertain
results triggered `TWO_CONSECUTIVE_CONTROLLED_NO_PROGRESS_RESULTS` degrade.
Production subsequently stopped at step 4 with `COMPLETED` /
`plugin_boundary_global_nav`. This preserves production termination but fails
the requested five-step acceptance and provides no confirmed controlled Smoke
move. Stage 2 therefore rejected; Stage 3 was not started. No automatic retry,
manual in-run correction or weakening of production identity/visit proof was
performed. The anonymous-focus blocker needs further separately authorized
recovery before readiness can change.

Across the 19 recorded steps: 16 controlled attempts, 2 failed controlled
previews, 5 production fallbacks, 17 new production visits, and zero planner
visit credit. The earlier before-focus talkbackLabel regression count remains
zero; that metric does not assert that anonymous focus is reconciled. All ten
lifecycle/transport gates are zero; TalkBack PID `19549`, Helper PID `18024`
and locale `en-US` stayed stable across both execution segments. No live scroll
execution occurred.

**OVERALL_VERDICT=PHASE4B_CONTROLLED_EXECUTION_REJECT**

**READY_FOR_PHASE4C=NO.** Phase 4C/5 are not implemented. Integration HEAD and
origin remain `ef3d1c92bdbb4716a1b0525ba715622c75f52756`. No commit or push was
performed because staged acceptance rejected. Main and the original Phase 3
branch are unchanged. All local Phase 4B work and evidence are retained.

## Anonymous focus identity recovery (2026-10-11)

### Source gate and RCA

Integration HEAD and origin were both
`ef3d1c92bdbb4716a1b0525ba715622c75f52756` at the start. Main/origin were both
`6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`; original Phase 3 remained
`fb4d01c489a0b3d56883e074771eb823c453d4f2`. Fetch/checkout preserved all local
Phase 4B changes; there was no pull/discard. Initial tracked status and source
hashes are in `phase4b_anonymous_recovery_20261011/source_gate_before_changes.json`.

Latest rejected Smoke observations contain two real strict anonymous targets:
an exact full-screen WebView and a TextView at `180,108,876,288`. Both returned
correlated `TARGET_MATCHED`, and independent immediate FOCUS_RESULT reads had
`accessibilityFocused=True`. They are structurally distinguishable; empty
labels do not make this actual focus invalid. The WebView is a focusable
container/wrapper stop, and the TextView is an anonymous element stop. Virtual
accessibility implementation details are not inferred. Before/after metadata,
parent context and observed hierarchy paths are in `anonymous_focus_rca.json`.
Parent/path fields are reconstructed from the fresh pre-action hierarchy, with
explicit provenance; they were not present in the immediate focused payload.

Two defects blocked reconciliation:

1. `observed_focus_instance` required resource ID or label even for strict
   focused nodes with valid bounds and class. Both saved immediate reads
   therefore yielded no production identity.
2. Normal `FocusService.get_focus` classified success-false top-level anonymous
   payloads as weak because they had no text-like label. At saved Smoke step 2,
   the strict TextView was replaced by an input-focused dump node. Fast
   immediate reads retained the actual accessibility-focused TextView.

### Production focus identity chain and fallback precedence

| Responsibility | Functions/evidence |
| --- | --- |
| Capture | Helper `findFocus(FOCUS_ACCESSIBILITY)`, `HelperBridge._request_get_focus`, `FocusService.get_focus`; existing exact request matching remains in transport. |
| Normalize | `normalize_bounds`, step row builder, `StepCollectionService._snapshot_actual_focus_fields`, controlled before-focus `focus_row`. |
| Build identity | `observed_focus_instance`, strict `focus_instance`, scoped deterministic `instance_id`. |
| Compare | `_strict_focus_proof`, `_previous_actual_id`, `reconcile_focus`; compare actual before/after, not ACK success alone. |
| Reconcile visits | Production `_apply_focus_reconciliation`, visit gate, `TraversalMetrics.observe_focus/observe_reconciliation`; diagnostic preview does not persist credit. |
| Persist proof | `TraversalMetrics` retains actual class in the coherent focus proof so an anonymous observation survives serialization. |

Existing labeled/resource-ID behavior remains first. Instance identity uses
scenario scope + resource ID + exact bounds when bounds exist; hierarchy path
is a fallback without geometry, and unresolved label/class evidence cannot
prove a physical visit. Text/contentDescription/talkbackLabel/speech are
observations, not extra geometry-based identity keys. Center is derived from
bounds, not a new discriminator. Parent/path/sibling metadata are corroborating
hierarchy evidence; actionability and focusable state do not manufacture focus.

For resource-ID/label-empty focus, the minimum new eligibility fallback is:
coherent **actual accessibility focus**, positive exact bounds and observed
class. Conflicting flags, class/bounds mismatch, missing class/invalid geometry,
ambiguous reconciliation and explicit false visit proof are refused. Input
focus alone is insufficient. The deterministic **instance-v1** key is retained;
class remains comparison evidence. This preserves attempt/visit/starvation
history and later dynamic labels. Same bounds with conflicting observed class
remains `AMBIGUOUS`, with zero new visit; no arbitrary uniqueness field is added.
There is no identity migration, random ID, timestamp or attempt-based identity.

Normal focus capture now preserves complete strict accessibility-focused
payloads with positive geometry/class. The new rule does not authorize salvaged
partial JSON or input-focused fallback. Request correlation, lifecycle handling,
planner policy, candidate canonical binding and default authority are unchanged.
No Smoke-specific production condition was added.

### Contract and regression gates

| Contract | Result |
| --- | --- |
| FOCUS_CONTRACT_01 | PASS: input focus is not accessibility focus. |
| FOCUS_CONTRACT_02 | PASS: coherent actual accessibility-focused payload is authoritative. |
| FOCUS_CONTRACT_03 | PASS: ACK success without movement creates no new visit. |
| FOCUS_CONTRACT_04 | PASS: ACK failure with confirmed actual movement can reconcile. |
| FOCUS_CONTRACT_05 | PASS: false-focus fallback gets zero visit credit. |
| FOCUS_CONTRACT_06 | PASS: stale request/result attribution remains blocked. |
| FOCUS_CONTRACT_07 | PASS: same resource ID with different bounds remains distinct. |
| FOCUS_CONTRACT_08 | PASS: attempts remain separate from visits. |
| FOCUS_CONTRACT_09 | PASS: Phase 3/4 diagnostics/preview do not apply production visits. |
| FOCUS_CONTRACT_10 | PASS: anonymous identity is deterministic and uses the existing scoped key. |

Focused regressions: **221 passed**. Full Python: **3647 passed, 1 skipped,
0 failed**. Full Helper: **408 passed, 0 failed/errors/skipped**. Exact saved
anonymous replay now returns the existing candidate ID and `CONFIRMED_MOVED`
for both immediate observations, applying zero visits/device actions. Historical
transition16, accepted6 and Phase4A-input30 replay remain exact. Helper source
and APK did not change for this recovery; installed and built APK SHA-256 match
`25e4f3c491ebb2e2c6b67f7ba4359e4f91983d892619e3fbb7518d00c1afee03`.
No reinstall or locale change was performed. Stable precheck PIDs are TalkBack
`19549`, Helper `18024`, locale `en-US`.

Live plan: separate normal-entry Smoke Sensor verification, then a fresh full
staged Home/Devices → Find/Smoke → Food/Family five-step acceptance. Verification
and staged artifacts have distinct roots. A true failed acceptance stops the
next stage, with no automatic scenario retry or in-run manual correction.

### Final anonymous recovery acceptance

**PHASE4B_CONTROLLED_EXECUTION_PASS_WITH_LIMITATIONS**

**READY_FOR_PHASE4C=YES**

Separate Smoke verification passed five controlled moves, two anonymous focus
cases, zero fallback and all hard gates zero. One fresh full staged acceptance
then passed every stage and every scenario, five steps each:

| Stage | Scenario | Controlled moves | Production fallback | New production visits | Scenario runtime seconds |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Home | 5 | 0 | 5 | 115.07 |
| 1 | Devices | 5 | 0 | 5 | 186.70 |
| 2 | Find | 4 | 1 | 5 | 199.98 |
| 2 | Smoke Sensor | 5 | 0 | 5 | 117.19 |
| 3 | Food | 5 | 0 | 5 | 148.61 |
| 3 | Family Care | 4 | 1 | 5 | 380.36 |

Full staged run: **30 recommendations/steps, 28 controlled moves, 0 controlled
failures, 2 legitimate RECOVERY_CONFLICT fallbacks, 30 production visits,
0 planner visit credit**. Four anonymous controlled cases were confirmed in
the staged run; Smoke includes both previously rejected shapes. Before-focus
label-loss false UNAVAILABLE count is zero. Complete strict anonymous identity
and immediate target evidence were valid for every observed anonymous case.
Food remained `PARTIAL_CONTEXT`; target safety was independently proven.
Family Care used verified plugin context; its runtime variation and one
production recovery fallback do not imply a Full32 performance verdict.

Staged monitoring ran from `2026-10-11T04:15:35.701217+00:00` to
`2026-10-11T04:36:07.569210+00:00` (**1231.87 seconds**). All ten
lifecycle/transport gates are zero across targeted verification and staged
acceptance. TalkBack `19549`, Helper `18024` and `en-US` remained unchanged.
Production, Helper, adapter and monitor source hashes matched their pre-run
snapshots. No automatic retry, manual correction or Full32 was performed.

Limitations: five steps do not establish complete plugin coverage; live scroll
execution was not exercised; same-geometry conflicting class evidence remains
ambiguous. Scroll and degrade contracts have regression coverage; no production
policy was weakened to obtain acceptance. All ten focus contracts passed.
No Phase 4C/5 implementation or merge into main was performed. Accepted work
is published only on the integration branch under the existing git policy;
the final commit/ref and publication status are recorded in
`phase4b_anonymous_recovery_20261011/final_report.json`.
