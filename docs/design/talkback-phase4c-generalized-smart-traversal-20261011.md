# Phase 4C generalized smart traversal — 2026-10-11

## Foundation and scope

Integration foundation: a4795a14501f7c6956e1bfe45ee1dd87f687b2b6.
Production main: 6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee.
Original Phase 3: fb4d01c489a0b3d56883e074771eb823c453d4f2.

Phase 4A supplies deterministic side-effect-free ranking from observed discovery
candidates and real production attempt/visit history. Never-attempted useful
candidates precede attempted-unvisited targets; visited/current targets are
lower priority. A verified vertical scroll precedes an ordinary visited revisit.
Phase 4B supplies explicit opt-in, independent fresh revalidation, canonical
unique target resolution, exact request correlation, production focus/scroll
execution, and production reconciliation. The accepted six-scenario validation
had 28 controlled actions, two legitimate recovery fallbacks and zero hard gates.
Anonymous focus support uses strict accessibility focus plus positive bounds and
class, retaining production instance-v1. Label-only identity is preserved.

Phase 4C retains those decisions and adds an explicit generalized session.
Phase 5 is not implemented. Main and original Phase 3 remain unchanged.
Normal production and Full32 do not import or enable this harness.

## Execution model

Normal selectable scenario entry → Phase 3 context → current discovery inventory
→ original Phase 4A ranking → independent immediate capture → Phase 4B execution
 gate → production target focus or verified scroll → production reconciliation
and persistence → fresh context/inventory → session evidence → repeat.

`tools.phase4c_generalized_smoke` calls the shared controlled harness with an
explicit generalized option and requires `TB_PHASE4C_CONTROLLED=1` before any
client is created. Hooks are process-local and restored in finally blocks.
Production scenario selection, anchor acquisition and entry remain intact.
The shared Phase 4B entry point retains its original five-step default.

`phase4c_traversal.TraversalSession` never writes an attempt or visit ledger.
Audit attempt/visit credits are copies of production outcomes. Production ACK
success without actual movement gets no new visit; ACK failure plus proven
accessibility focus movement may reconcile normally. Input focus, stale results,
partial salvaged focus and diagnostics never independently award visits.

## Focus and scroll policy

Focus requires the original deterministic recommendation, fresh same context,
strict coherent accessibility focus, current viewport geometry, actual candidate
presence/actionability and unique generic canonical resolution. No new identity
schema, scenario-specific targeting or arbitrary label inference is introduced.

Scroll requires absence of higher-value eligible focus candidates, trustworthy
vertical capability and container, no pending recovery, and no exhaustion.
Execution recaptures the production container and uses `verified_scroll` and the
Helper container path/bounds mechanism. No raw swipe is added. The scroll request
ID and ACK are copied at the transport boundary before subsequent captures can
replace active request metadata.

Scroll outcomes: SCROLL_MOVED, SCROLL_NO_MOVEMENT, SCROLL_INDETERMINATE.
Every outcome refreshes context, hierarchy fingerprint, viewport, inventory,
capability and focus. No pre-scroll ranking is reused. Session state reports
SCROLL_AVAILABLE, SCROLL_MOVED, SCROLL_EXHAUSTED or SCROLL_UNKNOWN.
An unknown or contradictory capability cannot prove no-progress exhaustion.

A proven production viewport end or two successful, valid, unchanged scroll
results at the same state/container/viewport records exhaustion. Two observations
follow existing Phase 4B consecutive-failure bounds; scope keys include actual
state/substate, foreground package/activity, container path/bounds and stable
viewport signature. A different viewport does not inherit exhaustion.

## Loop and starvation protection

The session tracks repeated target/current focus, unchanged inventory/state,
canonical binding, resolution failures, focus failures, consecutive fallbacks,
and unchanged scroll results. Phase 4B's two consecutive controlled failures or
repeated target without new production visit degrade to production. Fresh new
production visits, candidate discovery or state change may restore controlled
eligibility, while the absolute scenario budget remains intact.

A four-step window follows production runtime_input's existing plateau threshold.
Repeated targets/failures at two, or current focus/fallback at four, signal a loop
only without actual progress. One repeat cannot prove a terminal condition.
Never-attempted eligible higher-priority targets continue to outrank revisits;
current-focus targets without transition value are not an available movement.
Attempted-unvisited targets remain ranked; diagnostic recommendations do not
consume attempts. No independent planner history replaces production history.

## No-progress, saturation and incomplete outcomes

Production errors and proven completion classes are preserved. Existing repeat
or content-no-progress stops are accepted only after the recent four-step window
shows no state/focus/candidate/visit/scroll progress, no useful candidate remains,
scroll is proven exhausted/unavailable, and focus identity is unambiguous.
Otherwise controlled traversal continues within its configured validation budget.
Production compatibility uses repeat_no_progress / INCOMPLETE_NO_PROGRESS.
Safety budgets remain INCOMPLETE_SAFETY_LIMIT, never complete.

Generic saturation is SHADOW ONLY: four recent observations without new
candidate, new visit, state change or moved scroll, no useful never-attempted
candidate, proven exhausted scroll, no identity ambiguity. It is not a hard
termination authority. No Food cutoff or semantic special case is added.

## Validation plan and artifact provenance

Stage A: Home, Devices, Life root (10 each).
Stage B: Find, Smoke Sensor, TV, Washer (10 each).
Stage C: Energy 10, Food 20, Family Care 10.
Stage D: Camera 20. Total ceiling: 130 production traversal steps.
These are validation-only budgets; production max_steps is unchanged.
Food PARTIAL_CONTEXT is allowed with independent structural safety.
Family state variance is reported rather than compared blindly.
Camera remains coverage-first; its production policy is unchanged.

The supervisor reuses corrected Helper-owner/exact-request hard-stop monitoring.
All lifecycle/transport and planner safety gates must remain zero. A true hard
failure stops later scenarios; output roots cannot be automatically retried.

Artifact root: `out/phase3_current_main_20261011/phase4c_generalized_20261011`.
Replay uses unchanged historical Phase 3 16, Phase 4A 30, Phase 4B 30, and accepted
baseline six captures. Saved source hashes prove no evidence mutation.
Accepted production Full32 batch_20261010_214943 provides broader comparison
for all eleven scenarios. Equal-budget prefixes and observed context are used;
full-run coverage is not directly equated with bounded smoke counts.

## Results and closure

**PHASE4_GENERALIZED_SMART_TRAVERSAL_REJECT**

PHASE4_COMPLETE=NO; READY_FOR_PHASE5=NO; PHASE5_IMPLEMENTED=NO.
The implementation remains local on integration/phase3-current-main. No commit,
push or merge was performed. Main, origin/main and the original Phase 3 branch
retain their initial refs. Default production Smart Traversal remains OFF.

This rejection concerns required controlled capability. TV's production entry,
bounded fallback and ten real visits succeeded; its high fallback rate by itself
is not a safety or production coverage failure. The current Phase 3 adapter has
no TV plugin context contract. All ten current captures remained unresolved, so
the Phase 4B authority gate correctly blocked execution. Broad controlled device
traversal is not established. Closing Phase 4 while that dependency is missing
would overstate the representative acceptance evidence.

The supervisor stopped at that acceptance failure. Washer, Energy, Food, Family
Care and Camera were not run. No automatic retry or manual scenario correction
was made. Six scenarios ran once; five passed and TV rejected. All ten
lifecycle/transport gates and all six planner safety gates are zero.

### Staged outcomes

| Scenario | Steps | Controlled focus | Controlled scroll | Fallback | New visits | Outcome |
|---|---:|---:|---:|---:|---:|---|
| home_main | 10 | 9 | 0 | 1 | 9 | PASS; INCOMPLETE_SAFETY_LIMIT |
| devices_main | 10 | 8 | 0 | 2 | 8 | PASS; INCOMPLETE_SAFETY_LIMIT |
| life_main | 10 | 8 | 2 | 0 | 10 | PASS; INCOMPLETE_SAFETY_LIMIT |
| life_find_plugin | 10 | 9 | 0 | 1 | 8 | PASS; INCOMPLETE_SAFETY_LIMIT |
| device_smoke_sensor_plugin | 7 | 7 | 0 | 0 | 7 | PASS; COMPLETED |
| device_tv_plugin | 10 | 0 | 0 | 10 | 10 | REJECT_CONTROLLED_CAPABILITY_UNPROVEN; INCOMPLETE_SAFETY_LIMIT |
| device_washer_plugin | — | — | — | — | — | NOT RUN after Stage B stop |
| life_energy_plugin | — | — | — | — | — | NOT RUN after Stage B stop |
| life_food_plugin | — | — | — | — | — | NOT RUN after Stage B stop |
| life_family_care_plugin | — | — | — | — | — | NOT RUN after Stage B stop |
| device_camera_plugin | — | — | — | — | — | NOT RUN after Stage B stop |

Totals: 57 steps, 41 targeted focus executions, two planner scroll executions,
14 production fallbacks, 55 confirmed focus moves, 52 new production visits,
192 discovered positional candidate instances. No planner-created visit credit.
No loop, starvation or saturation signal fired. Bounds-based discovery counts
are positional observations, not a claim of 192 distinct logical controls.
Target focus attempts are distinguished from production traversal step attempts
in per_scenario_metrics.json; attempt credit in the inherited trace refers to
the real target-attempt ledger.

Home's repeated target without a new production visit degraded to bounded
fallback and then recovered on a real new visit. Devices had one input-only
focus result and then a valid after-focus with unavailable before evidence;
both were uncredited. These are legitimate uncertainty blocks, not label-loss
false UNAVAILABLE. Smoke Sensor's two anonymous focused targets reconciled
normally. Its seven-step completion came from the existing production plugin
boundary, not a new cutoff.

### TV context root cause

Source: `tb_runner/phase3_context.py` `_PLUGIN_IDS` and
`resolve_phase3_context`; `tb_runner/phase4b_authority.py` `execution_gate`.
Known plugin profiles: Food, Family Care, Find, Smoke Sensor. The unknown-profile
branch admits an observed root tab or returns UNRESOLVED_CONTEXT before checking
the configured production entry contract.

For all ten saved TV steps:

- foreground package was com.samsung.android.oneconnect;
- foreground activity was com.samsung.android.oneconnect.webplugin.WebPluginActivity;
- the actual entry proof was current and matched the configured contract digest;
- the anchor was accessibility-focused at verified pre-loop entry;
- the recommended structural target resolved uniquely;
- context remained UNRESOLVED_CONTEXT / NO_VERIFIED_CONTEXT_CONTRACT;
- execution was denied as CONTEXT_INSUFFICIENT;
- production fallback moved actual accessibility focus and recorded a real visit.

Evidence: tv_context_rca.json and the unmodified observations/action/step ledgers.
No TV special case or automatic unresolved-to-partial promotion was implemented.
A recovery task needs a generic observed-entry and current structural-context
contract that preserves wrong/contradictory/stale rejection. New device
acceptance is needed after such a contract is proven.

### Live scroll and diagnostic correction

Life root steps 5 and 6 executed the existing production verified scroll path.
Both had explicit native container targets, successful supported actions, real
viewport changes and freshly rebuilt candidate inventories. The Helper owned
both responses with PID 18024. Request IDs were 5e49e51e and a6a96ca6; exact
transport request reads and Helper response IDs matched. ACK timestamps fell
between fresh pre-action and post-scroll captures. Container paths were 0.0.6
and 0.0.1 respectively.

The first instrumentation copied the focus transaction's active ID for SCROLL.
Native SCROLL does not create that focus transaction, leaving the diagnostic ID
empty and the diagnostic correlation flag false. The underlying native transport
already read SCROLL_RESULT using its own exact freshly generated request ID.
This was an audit display gap, not a stale response accepted by production.

After the run stopped, only this diagnostic observer was corrected to record the
explicit native SCROLL_RESULT request argument. Four regression cases cover
success, ACK failure, stale result and hook restoration on exception. Actions,
request allocation/matching, ranking, gate policy and visit authority were not
changed by this post-live correction. No further device run was made.

The raw trace remains unchanged. audit_scroll.py reconstructs a separate checked
trace from exact runner request-start/match records, Helper-owned logcat results,
fresh timestamps and container paths. It also links the final step to actual
production SCENARIO_TERMINAL evidence. Source hashes prove no original evidence
mutation; no replay action or production ledger write occurs. The frozen execution/monitor
files differ only for the diagnostic observer in phase4b_execution.py; four
request-audit test cases were added after the live run. The final full Python suite and all historical replays were
rerun after that correction.

No live no-movement/exhaustion scroll case occurred. Two-result exhaustion and
scope invalidation passed offline tests. The raw metric named SCROLL_EXHAUSTED
counts unavailable/exhausted state observations; final_report's total exhaustion
field counts proven no-move exhaustion events (zero). These measures are kept
separate in the per-scenario metrics.

### Tests and replay

- Final Python: **3667 passed, 1 skipped, 0 failed**.
- Phase 4 focused: **133 passed**.
- Phase 3 focused: **58 passed**.
- Production focused: **411 passed**.
- Post-live request-audit focused: **54 passed**.
- Helper source and installed APK unchanged; accepted **408-pass** Helper result
  retained, no new Helper suite or reinstall required.
- Historical Phase 3: **16 exact**.
- Phase 4A: **30 exact**.
- Phase 4B controlled: **30 exact**, including gate/recommendation and visit rules.
- Accepted baseline replay: **six scenarios**.
- Native live scroll transport replay: **two exact owner/request matches**.

### Coverage comparison and limitations

Accepted production batch_20261010_214943 supplies all eleven baseline terminals
and equal-budget reconciliation prefixes. The new run is shorter and may observe
a different state. No claim of identical paths or full coverage equivalence is
made. Context uncertainty is analyzed explicitly.

| Scenario | New visits | Accepted equal-budget new visits | Classification |
|---|---:|---:|---|
| home_main | 9 | 10 | ACCEPTABLE_VARIANCE |
| devices_main | 8 | 10 | ACCEPTABLE_VARIANCE |
| life_main | 10 | 10 | EQUIVALENT |
| life_find_plugin | 8 | 8 | EQUIVALENT |
| device_smoke_sensor_plugin | 7 | 6 | ACCEPTABLE_VARIANCE |
| device_tv_plugin | 10 | 10 | EQUIVALENT |
| device_washer_plugin | — | — | INSUFFICIENT_EVIDENCE; not run |
| life_energy_plugin | — | — | INSUFFICIENT_EVIDENCE; not run |
| life_food_plugin | — | — | INSUFFICIENT_EVIDENCE; not run |
| life_family_care_plugin | — | — | INSUFFICIENT_EVIDENCE; not run |
| device_camera_plugin | — | — | INSUFFICIENT_EVIDENCE; not run |

The classifications above describe bounded observed behavior. Full-run coverage
is insufficiently established for every bounded case. Home lost one new visit
to an existing visit; Devices lost two steps to actual focus/state uncertainty.
Find and Life matched the bounded production visit counts. Smoke Sensor's
terminal unique count was eight versus nine in the longer accepted run, with
unchanged production boundary termination. TV matched ten fallback visits while
failing to establish controlled execution. No material production coverage
regression is proven, and all-eleven controlled coverage is unproven.

### Food, Family Care, Camera and saturation findings

These scenarios were not reached after the Stage B stop. Food's candidate growth,
repeated templates, last new candidate/visit and saturation step are NOT RUN;
no live saturation conclusion is drawn. Generic saturation remains shadow-only.
Family Care runtime/state comparison is NOT RUN; its logic was not modified.
Camera efficiency/coverage comparison is NOT RUN. Its production max-step and
coverage-first termination policy are unchanged; the proposed 20-step budget is
only a validation configuration and was not executed.

### Closure and next step

Controlled focus, anonymous identity and two real planner scrolls were observed
safely. Required broader context support is incomplete, and five required live
scenarios are untested. Phase 4 cannot close and Phase 5 is not ready.

Next: prove a generic current observed-entry/structural context contract for
unsupported plugins, retain fail-closed context and exact correlation semantics,
then perform a new A→B→C→D acceptance. Do not weaken the execution gate merely
to allow an unresolved TV context.

### Artifacts

All files below are under
`out/phase3_current_main_20261011/phase4c_generalized_20261011`:

- final_report.json / final_report.txt: complete requested report fields;
- per_scenario_metrics.json and coverage_comparison.json;
- tv_context_rca.json: ten independent current entry/target/context proofs;
- acceptance/monitor_result.json and individual scenario acceptance files;
- acceptance/phase4c_execution_trace.jsonl: original immutable step trace;
- transport_checked_trace.jsonl: exact scroll correlation and terminal evidence;
- scroll_transport_audit.json / audit_scroll.py: replayable proof and hashes;
- final_full_python.xml/log and focused-suite XML/logs;
- replay_post_live/summary.json and replay outputs;
- source_gate.json, pre_acceptance_source_hashes.json, helper_source_hashes.json.

# Generic plugin-context recovery retry — final rejection

OVERALL_VERDICT=PHASE4_PLUGIN_CONTEXT_RECOVERY_REJECT
PHASE4_COMPLETE=NO
READY_FOR_PHASE5=NO
PHASE5_IMPLEMENTED=NO

The original rejection above remains an immutable historical result. This retry
resolved the TV context blocker through the generic evidence contract documented
in `talkback-phase4c-plugin-context-rca-20261011.md`. It adds no TV-specific bypass.
The current native post-open proof is owned by scenario/run/destination/epoch;
current activity/window/body must agree. TV remains correctly PARTIAL_CONTEXT
when its configured text marker is absent. Independently safe structural targets
may execute under the existing authority gate. Navigation attempts expire proof;
focus and scroll preserve it. Candidate/focus identity, ledger/visit authority,
planner ordering, scroll, starvation and loop policies were not changed by this
context recovery. Default normal production smart traversal remains OFF.

## Source and offline gates

- Integration start/final/origin: `a4795a14501f7c6956e1bfe45ee1dd87f687b2b6`.
- Main/origin unchanged: `6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`.
- Original Phase 3 unchanged: `fb4d01c489a0b3d56883e074771eb823c453d4f2`.
- Existing local Phase 4C fixes preserved; no pull, new commit, push or main merge.
- Context tests 39; missing-tab precondition tests 2; Phase 3 focused 58;
  production focused 411; Phase 4/planner/generalized focused 174: all passed.
- Final full Python: **3708 passed, 1 skipped, 0 failures**.
- Helper unchanged (47 source hashes); prior accepted 408-pass result retained,
  not represented as a new Helper test run.
- Historical Phase 3 16 exact, Phase 4A 30 exact, Phase 4B 30 exact; accepted
  six-scenario baseline gates PASS; eight-plugin context replay records missing
  historical evidence explicitly and does not force verified context.
- Phase 4C pre-stop 57 original decisions exact. A separate rebuilt-candidate
  semantic replay passes all 57: production identities, targets, history and
  ordering semantics unchanged. Opaque generic context diagnostic IDs may differ.
- TV offline: UNRESOLVED_CONTEXT becomes PARTIAL_CONTEXT; 10/10 hypothetical
  structural gates pass without actions or ledger mutation.

## Live TV and staged acceptance

The initial locked setup started no scenario; its immutable `tv_only` artifacts
are retained. The missing-tab reporting exception was fixed without weakening
startup checks. After the user unlocked the phone, clean-start validation passed.
Serial R3CX40QFDBP; locale en-US unchanged; TalkBack PID 19549 and Helper PID 18024
remained stable. All scenarios used normal production entry and fresh artifacts.

TV-only **PASS**: 10 recommendations, 10 authorized and executed controlled focus
actions, 10 confirmed movements and 10 audit new visits, 0 fallbacks/scrolls.
Context is PARTIAL_CONTEXT at all 10 steps, source
`generic_production_entry+post_open+current_runtime`. Termination is the requested
10-step INCOMPLETE_SAFETY_LIMIT; it is not a claim of complete device coverage.

Stage B **PASS 4/4**. Stage C: Energy PASS; Food REJECT on the final acceptance
audit. The supervisor stopped the staged sequence after Food completed its
20-step bounded run. Family Care was not started; Stage D Camera was not started.
No automatic retry, individual correction or Full32 was run.

| Scenario | Context (step counts) | Steps | Controlled focus / scroll | Fallback | Audit new visits / native | Result |
|---|---|---:|---:|---:|---:|---|
| life_find_plugin | VERIFIED_PLUGIN_CONTEXT: 1, UNRESOLVED_CONTEXT: 9 | 10 | 1 / 0 | 9 | 8 / 8 | PASS |
| device_smoke_sensor_plugin | VERIFIED_PLUGIN_CONTEXT: 7 | 7 | 7 / 0 | 0 | 7 / 7 | PASS |
| device_tv_plugin | PARTIAL_CONTEXT: 10 | 10 | 10 / 0 | 0 | 10 / 10 | PASS |
| device_washer_plugin | PARTIAL_CONTEXT: 10 | 10 | 10 / 0 | 0 | 10 / 10 | PASS |
| life_energy_plugin | VERIFIED_PLUGIN_CONTEXT: 1, UNRESOLVED_CONTEXT: 9 | 10 | 1 / 0 | 9 | 10 / 10 | PASS |
| life_food_plugin | PARTIAL_CONTEXT: 20 | 20 | 17 / 3 | 0 | 17 / 18 | REJECT |

Current B/C totals only: 67 steps, 46 controlled focus executions, 3 controlled
scrolls, 18 controlled-path production fallbacks, 65 copied-row confirmed moves,
62 audit new visits versus 63 native reconciled new visits, 80 discovered
candidates. Standalone TV and prior Stage A are excluded from these totals.
Smoke ended normally at `plugin_boundary_global_nav` after 7 steps. Find/Energy
each executed one controlled focus before existing production navigation expired
their entry epoch; the remaining nine steps used legitimate unresolved-context
fallback. Refresh after internal navigation remains a conservative limitation.

## New closure blocker: Food recovery actor evidence

Food step 11 request `2e989e3a29364a4b842db8b27491a6b2` targeted the Button at
864,1567,954,1660. Correlated immediate actual accessibility focus matched it.
Native event `evt_69c7368b26cb40beb0387eb5e50e459e` at 08:58:01.264 UTC records
CONFIRMED_MOVED, EXACT mapping, physical_visit_confirmed=true and RECORDED.

Subsequent normal production V2 recovery made three attempts in that same step.
The successful recovery produced an accessibility-focused View at
90,883,501,1033 (GET_FOCUS request `34ec6d03`). Its replacement final row lacks
`focus_reconciliation_evidence`, `focus_transition_status` and
`visit_record_status`. The acceptance observer copies that final row and compares
its valid actual identity against an empty reconciliation identity. It reports
FINAL_ACTUAL_FOCUS_DISAGREES_WITH_PRODUCTION_RECONCILIATION.

The original FALSE_FOCUS_MOVEMENT=1 flag is preserved; actual false physical
movement is **not proven**. This is a final recovery actor/evidence linkage gap,
not a new generic context failure. No override or fabricated visit was added.
Food audit has 17 new visits, native reconciliation 18 and native unique visited
instances 20. Zero controlled-path fallback does not mean zero later production
recovery: the three V2 attempts are recorded separately. Closure requires an
actor-aware audit that binds each actual outcome to the correct production
reconciliation while preserving visit/focus/request authority, followed by a new
explicit staged acceptance request. No fix for this newly discovered blocker was
implemented in this retry.

## Scroll, saturation and hard gates

| Food step | Request ID | Result | New candidates |
|---:|---|---|---:|
| 10 | 3cfc20d0 | SCROLL_MOVED | 3 |
| 12 | c67ac47e | SCROLL_MOVED | 0 |
| 15 | 220ade63 | SCROLL_MOVED | 5 |

All three scrolls have exact request IDs, Helper-owned PID 18024 SCROLL_RESULT,
explicit target, matching ACK, fresh after-scroll capture and retained before/
after viewport files. Resolved state IDs remain null in PARTIAL_CONTEXT; the
evidence does not invent resolved plugin states. Request ledger lines and capture
hashes are in `scroll_validation.json`. No opportunity was manufactured.

Food: 20 steps, 20 native unique visits, 18 new candidates; last new candidate
step 15, last copied-row new visit step 20; 3 scrolls, 0 repeated controlled
targets, no saturation signal; termination safety_limit. No Food cutoff added.
All ten lifecycle/transport hard gates are 0. Unsafe/ambiguous/stale execution,
false visit credit, unbounded loop, starvation regression and false no-progress
are 0. There is one bounded loop observation across B/C, not an unbounded loop.
The one acceptance focus mismatch described above prevents closure.

## Coverage and closure

| Scenario | Bounded comparison | Evidence scope |
|---|---|---|
| home_main | ACCEPTABLE_VARIANCE | CARRIED_PREVIOUS_STAGE_A |
| devices_main | ACCEPTABLE_VARIANCE | CARRIED_PREVIOUS_STAGE_A |
| life_main | EQUIVALENT | CARRIED_PREVIOUS_STAGE_A |
| life_find_plugin | EQUIVALENT | CURRENT_RECOVERY_STAGE_BCD |
| device_smoke_sensor_plugin | IMPROVED | CURRENT_RECOVERY_STAGE_BCD |
| device_tv_plugin | EQUIVALENT | CURRENT_RECOVERY_STAGE_BCD |
| device_washer_plugin | EQUIVALENT | CURRENT_RECOVERY_STAGE_BCD |
| life_energy_plugin | EQUIVALENT | CURRENT_RECOVERY_STAGE_BCD |
| life_food_plugin | ACCEPTABLE_VARIANCE | CURRENT_RECOVERY_STAGE_BCD |
| life_family_care_plugin | INSUFFICIENT_EVIDENCE | NOT RUN |
| device_camera_plugin | INSUFFICIENT_EVIDENCE | NOT RUN |

Home/Devices/Life are carried historical Stage A results, not new live runs;
their root decisions were replayed unchanged. Bounded visit counts do not prove
full-run coverage equivalence. Food differs in live content/viewport and scroll
mix; it cannot be compared blindly to raw production coverage. No observed
catastrophic coverage regression is established, but Family/Camera lack current
evidence and representative coverage is incomplete. Thus COVERAGE_REGRESSION=NO
means no proven observed regression, not a full coverage pass.

CONTROLLED_EXECUTION_REGRESSION=YES denotes the acceptance evidence blocker;
it does not assert unsafe targeting. Phase 4 is not closed and Phase 5 remains
unimplemented. Rejection preserves all justified local fixes; no commit/push.

Evidence root: `../phase4c_context_recovery_20261011/`. See `final_report.json`
and `.txt`, `per_scenario_metrics.json`, `coverage_comparison.json`,
`food_actor_audit_rca.json`, `scroll_validation.json`, `food_saturation.json`,
TV RCA/recovery files, frozen source hashes, final test XML/logs and replay
summaries. Original live traces, native evidence, monitor results and acceptance
files remain unchanged under `tv_validation/` and `staged/`.

# Food audit linkage recovery — closure retry

The previous rejection sections above remain historical. Original Food step 11
and its mismatch are preserved byte for byte. This retry changes only generic
audit/provenance/recovery correlation relative to that rejected source; the
accumulated justified Phase 4C context/traversal work is also included for
integration publication. No Phase 5 implementation or main merge is performed.

## Proven RCA and ownership contract

Food step 11's primary target/request and native production reconciliation were
valid. Later normal production V2 recovery replaced the final row. Its omitted
legacy reconciliation fields disconnected primary evidence from the final
recovery actor. The classification is AUDIT_ROW_REPLACEMENT_ONLY plus
PROVENANCE_LINKAGE_MISSING; actual incorrect physical focus movement was not
proven. See `talkback-phase4c-audit-linkage-rca-20261011.md` for the exact IDs,
events, pipeline and strict acceptance conditions.

The deterministic STEP_ACTION_ID composes schema, existing run/scenario
transaction, scenario ID and traversal step. Primary requests, native focus
reconciliation, recovery requests/results and verification observations remain
separate actors under that owner. Append-only step evidence snapshots the native
journal. The final row retains the actual recovered outcome and adds only an ID
and hash/reference to the immutable chain. It does not restore the first row or
overwrite final outcome/visit fields. Audit linkage has no visit authority.

The checker keeps all primary target, predicate, actual movement and exact
request checks. A later actor requires its own native request/ACK, actual
accessibility focus observation, production physical-move/visit gate and strong
recovery result in the same transaction. Missing, stale, mismatched or cross-step/
scenario evidence rejects. The sidecar must agree exactly with its hash/reference.
No Food special case or acceptance flag override is used.

Planner ranking/authority, focus commands, candidate/focus identity, fallback and
recovery selection, scroll, visit accounting, starvation and termination are
unchanged by this audit repair. Critical pre-retry source hashes and the original
EvidenceRuntime AST (excluding the new read-only step reader) are unchanged.
Default production Smart Traversal stays OFF.

## Offline gates

- Generic audit/recovery/evidence focused: 87 passed (43 new provenance cases).
- Phase 3 focused: 58 passed; production focused: 442 passed;
  Phase 4 focused: 217 passed.
- Full Python: **3751 passed, 1 skipped, 0 failed**.
- Helper source unchanged (47 hashes); prior accepted 408-pass result retained;
  no new Helper test run is claimed.
- Historical Phase 3: 16 exact; accepted Phase 4A: 30 exact;
  Phase 4B: 30 exact; accepted six-scenario baseline gates pass.
- All 47 pre-Food decisions and all 67 prior B/C decisions replay exactly.
  Existing planner/context/gate and production identity semantics are preserved.
- Exact Food step 11 fixture reproduces the old mismatch and proves a new
  complete chain including all three original recovery attempts and final actor.
- All 67 reconstructed native chains validate; originals remain unchanged.

## Live retry

Serial R3CX40QFDBP; locale en-US unchanged. TalkBack PID 19549 and Helper PID
18024 remain stable. All scenarios use normal production entry, validated clean
start, frozen tested source and the corrected hard-stop monitor. No Full32,
manual correction, automatic scenario retry or locale change occurred.
Shared audit impact justified a full Stage B rerun. Stage C followed Food-only.
Family Care rejected at the completed 10-step acceptance boundary because no
controlled action executed. Camera was not run, as required by the Stage C gate.

| Run / scenario | Context counts | Steps | Controlled focus / scroll | Fallback | Native primary visits / recovery visits | Complete chains | Result |
|---|---|---:|---:|---:|---:|---:|---|
| food_validation / life_food_plugin | PARTIAL_CONTEXT: 20 | 20 | 17 / 3 | 0 | 18 / 1 | 20 | PASS |
| stage_b / life_find_plugin | VERIFIED_PLUGIN_CONTEXT: 1, UNRESOLVED_CONTEXT: 9 | 10 | 1 / 0 | 9 | 8 / 0 | 10 | PASS |
| stage_b / device_smoke_sensor_plugin | VERIFIED_PLUGIN_CONTEXT: 7 | 7 | 7 / 0 | 0 | 7 / 0 | 7 | PASS |
| stage_b / device_tv_plugin | PARTIAL_CONTEXT: 10 | 10 | 10 / 0 | 0 | 10 / 0 | 10 | PASS |
| stage_b / device_washer_plugin | PARTIAL_CONTEXT: 10 | 10 | 10 / 0 | 0 | 10 / 0 | 10 | PASS |
| stage_c / life_energy_plugin | VERIFIED_PLUGIN_CONTEXT: 1, UNRESOLVED_CONTEXT: 9 | 10 | 1 / 0 | 9 | 10 / 0 | 10 | PASS |
| stage_c / life_food_plugin | PARTIAL_CONTEXT: 20 | 20 | 17 / 3 | 0 | 17 / 2 | 20 | PASS |
| stage_c / life_family_care_plugin | VERIFIED_PLUGIN_CONTEXT: 1, UNRESOLVED_CONTEXT: 9 | 10 | 0 / 0 | 10 | 10 / 0 | 10 | REJECT |

Food-only experienced real later production recovery; its primary and recovery
requests/results remain linked. Stage C Food also retains its later recovery
attempts. Per-step actor IDs/results are in each *_audit_metrics.json and the
immutable phase4c_step_action_evidence.jsonl. Native primary RECORDED events,
native strong recovery visit events and copied final-row credits are reported
separately. Their counts are not silently normalized or used to award visits.

The standalone Food monitor/scenario passed before a wrapper summary reader
raised a CP949/UTF8 decoding exception. The artifact driver was corrected to
UTF8; Food was not rerun. The first offline replay used an unaccepted Phase 4A
input and failed its input comparison; the corrected accepted input passes.
Both original diagnostic outputs remain available.

## Scroll proof and coverage

| Run | Step | Exact Helper request | New candidates |
|---|---:|---|---:|
| food_validation | 8 | c4cb3266 | 4 |
| food_validation | 13 | b7fcca12 | 3 |
| food_validation | 17 | 2b4c51cf | 5 |
| stage_c | 6 | 2277b515 | 6 |
| stage_c | 13 | 99f73c89 | 5 |
| stage_c | 19 | 85fa684d | 4 |

Every listed scroll has the exact Helper-owned PID18024 SCROLL_RESULT,
matching request/ACK, explicit target, fresh after-scroll refresh and hashed
before/after viewport captures in scroll_validation.json. Resolved state IDs
remain null in PARTIAL_CONTEXT; the evidence does not invent plugin state IDs.

| Scenario | Bounded comparison | Native primary visits | Accepted baseline prefix | Terminal status / reason |
|---|---|---:|---:|---|
| life_find_plugin | EQUIVALENT | 8 | 8 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_smoke_sensor_plugin | IMPROVED | 7 | 6 | COMPLETED / plugin_boundary_global_nav |
| device_tv_plugin | EQUIVALENT | 10 | 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_washer_plugin | EQUIVALENT | 10 | 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_energy_plugin | EQUIVALENT | 10 | 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_food_plugin | ACCEPTABLE_VARIANCE | 17 | 19 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_family_care_plugin | ACCEPTABLE_VARIANCE | 10 | 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_camera_plugin | INSUFFICIENT_EVIDENCE | — | — | — / — |

These are bounded live comparisons, not Full32 or complete coverage equivalence.
Food/Family content and state can vary; raw counts across different complex
states are not direct coverage claims. Family is observed ACTIVE (Active now).
Smoke's normal global-navigation boundary
can end before its cap. Find/Energy/Family context can become unresolved after
existing navigation invalidates the entry epoch, leading to bounded production
fallback. Partial context remains explicit for safe structural plugin targets.
Camera has no new evidence in this retry; coverage-first production termination
is unchanged. Historical Stage A roots are
carried through semantic replay, not represented as new live runs.

## Final closure

OVERALL_VERDICT=PHASE4_AUDIT_LINKAGE_RECOVERY_REJECT
PHASE4_COMPLETE=NO
READY_FOR_PHASE5=NO
PHASE5_IMPLEMENTED=NO
DEFAULT_PRODUCTION_SMART_TRAVERSAL=OFF

All six audit, six execution-safety and ten lifecycle/transport hard gates are
zero across the 97 executed steps. The Food linkage repair passes replay and both
live Food runs, including actual later recovery. Overall closure nevertheless
rejects: Family Care executed zero controlled actions. Its first recommendation
snapshot has state_id=null; immediate fresh snapshot has
phase4b-controlled-smoke:state:00000002 and different fingerprint/viewport.
The unchanged authority gate denies STATE_OR_SUBSTATE_CHANGED. Step2 denies
RECOVERY_CONFLICT; steps3-10 deny CONTEXT_INSUFFICIENT after the existing
navigation epoch is invalidated. Ten safe production fallbacks confirm actual
focus and native visits. They do not demonstrate generalized controlled execution.
family_controlled_execution_blocker.json retains this separate new blocker.

CONTROLLED_EXECUTION_REGRESSION=YES is scoped to missing acceptance evidence,
not unsafe targeting or a proven audit-induced production behavior change.
COVERAGE_REGRESSION=NO means no proven material observed loss; Camera has
INSUFFICIENT_EVIDENCE and representative closure remains incomplete.
No authority/context policy is relaxed and no new retry is attempted.
Generalized traversal remains bounded and opt-in. Valid local Phase 4C changes
are preserved; no commit, push or main merge occurs under the rejection policy.
Phase 4 remains incomplete and Phase 5 readiness is NO. Phase 5 is not implemented.

Source start/origin integration: a4795a14501f7c6956e1bfe45ee1dd87f687b2b6.
Main/origin remain 6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee; original Phase 3
remains fb4d01c489a0b3d56883e074771eb823c453d4f2. Integration HEAD and origin
remain the starting commit; no publication occurs for this rejection.

Evidence root: ../phase4c_audit_recovery_20261011/. See final_report.json/.txt,
coverage_comparison.json, source/test/frozen hashes, production_behavior_proof.json,
corrected replay summaries, food_step11_old_new.json, scroll_validation.json,
per-run audit metrics, original traces, native journals, acceptance files and
hard-stop monitor results. Prior rejection artifacts remain unchanged.

# Dynamic context and recovery re-entry — final acceptance

Prior rejection sections remain immutable historical outcomes. This recovery
introduces a generic scenario-local destination lease, freshness and recovery
re-entry contract. It contains no Family Care special case. See
`talkback-phase4c-dynamic-context-recovery-20261011.md` for exact RCA, ownership
boundaries, two-capture revalidation and conservative target proof.

The old Family ten-step trace is reproduced exactly: state mismatch, recovery
conflict and eight stale-epoch context blocks. Current plugin activity/body
remained available, but the original adapter had no ownership reacquisition.
Destination identity now remains separate from discovery state and substate.
Navigation suspends or invalidates the lease according to observed evidence.
Recovery blocks authority until two fresh body observations restore ownership.
Fresh current-state replanning requires a safe current focus target in both
independent snapshots and then reruns the unchanged base authority gate.
No forced target, failure-budget reset or context-derived visit is introduced.

## Frozen source and offline gates

- Integration start/origin: a4795a14501f7c6956e1bfe45ee1dd87f687b2b6.
- Main/origin: 6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee unchanged.
- Original Phase3: fb4d01c489a0b3d56883e074771eb823c453d4f2 unchanged.
- Dynamic context 50, audit87, Phase3 focused58, production focused442,
  Phase4 focused267: all passed.
- Final Python: **3801 passed, 1 skipped, 0 failed**. A final explicit ownership
  check was added after the first full pass; all focused/full tests were rerun
  on the final frozen code before live. No source code changed during live.
- Helper47 source hashes unchanged; prior accepted408-pass result retained,
  not represented as a new Helper test run.
- Historical Phase3=16 exact; accepted Phase4A=30 exact; Phase4B=30 exact;
  accepted six-scenario baseline gates pass.
- Prior Phase4C67 planner/context/gate decisions reproduce exactly under their
  legacy adapter. All97 previous action chains remain complete; originals and
  old verdicts are unchanged. Food step11 old mismatch is reproduced and its
  new primary/recovery/final chain passes.
- Exact Family new replay authorizes six later safe steps; four remain blocked.
  Replay issues no commands or visits and does not rewrite recorded verdicts.

Existing production collection flow, planner ranking, base authority gate,
identity/focus/visit, traversal session/scroll/loop policies and Camera termination
remain unchanged. Changed shared surfaces are the opt-in context adapter,
navigation observation and audit linkage/checking. Smart Traversal stays OFF
by default; generalized runs require explicit process opt-in.

## Live staged evidence

Serial R3CX40QFDBP; locale en-US unchanged. TalkBack19549 and Helper18024 are
stable. All runs use normal production entry, validated clean start, frozen
source and corrected request-correlated hard-stop monitoring. No Full32, manual
scenario correction, automatic failed-scenario retry or Phase5 implementation.
Family-only preceded full shared StageB; StageC and Camera were gated by all
prior acceptance results. Historical StageA roots are replayed/carry-forward
evidence, not new live runs.

Current Food executed three controlled scrolls with movement. Each exact request
is linked to a Helper18024-owned SCROLL_RESULT, the runner correlation ledger,
the matching ACK, fresh before/after hierarchy hashes and post-scroll refresh.
See scroll_validation.json. PARTIAL_CONTEXT state IDs remain unresolved where
recorded; no state identity or visit is invented by this supplemental proof.

| Run / scenario | Steps | Context counts | Controlled focus / scroll | Fallback | Native primary visits / recovery visit events | Audit complete | Result |
|---|---:|---|---:|---:|---:|---:|---|
| family_only / life_family_care_plugin | 10 | VERIFIED_PLUGIN_CONTEXT:9, UNRESOLVED_CONTEXT:1 | 8 / 0 | 2 | 10 / 0 | 10 | PASS |
| stage_b / life_find_plugin | 10 | VERIFIED_PLUGIN_CONTEXT:9, UNRESOLVED_CONTEXT:1 | 8 / 0 | 2 | 8 / 0 | 10 | PASS |
| stage_b / device_smoke_sensor_plugin | 7 | VERIFIED_PLUGIN_CONTEXT:7 | 7 / 0 | 0 | 7 / 0 | 7 | PASS |
| stage_b / device_tv_plugin | 10 | PARTIAL_CONTEXT:10 | 10 / 0 | 0 | 10 / 0 | 10 | PASS |
| stage_b / device_washer_plugin | 10 | PARTIAL_CONTEXT:10 | 10 / 0 | 0 | 10 / 0 | 10 | PASS |
| stage_c / life_energy_plugin | 10 | VERIFIED_PLUGIN_CONTEXT:8, UNRESOLVED_CONTEXT:2 | 7 / 0 | 3 | 10 / 0 | 10 | PASS |
| stage_c / life_food_plugin | 20 | PARTIAL_CONTEXT:20 | 17 / 3 | 0 | 18 / 1 | 20 | PASS |
| stage_c / life_family_care_plugin | 10 | VERIFIED_PLUGIN_CONTEXT:9, UNRESOLVED_CONTEXT:1 | 8 / 0 | 2 | 10 / 0 | 10 | PASS |
| stage_d / device_camera_plugin | 20 | UNRESOLVED_CONTEXT:20 | 0 / 0 | 20 | 16 / 0 | 20 | REJECT |

## Context and recovery metrics

| Run / scenario | Invalidations / revalidations | Recovery starts / completions / rebounds | Authority blocks / regains | Executed after revalidation |
|---|---:|---:|---:|---:|
| family_only / life_family_care_plugin | 2 / 1 | 1 / 1 / 1 | 2 / 1 | 7 |
| stage_b / life_find_plugin | 2 / 1 | 1 / 1 / 1 | 2 / 1 | 7 |
| stage_b / device_smoke_sensor_plugin | 0 / 0 | 0 / 0 / 0 | 0 / 0 | 0 |
| stage_b / device_tv_plugin | 0 / 0 | 0 / 0 / 0 | 0 / 0 | 0 |
| stage_b / device_washer_plugin | 0 / 0 | 0 / 0 / 0 | 0 / 0 | 0 |
| stage_c / life_energy_plugin | 4 / 1 | 1 / 1 / 1 | 3 / 1 | 6 |
| stage_c / life_food_plugin | 0 / 0 | 0 / 0 / 0 | 0 / 0 | 0 |
| stage_c / life_family_care_plugin | 2 / 1 | 1 / 1 / 1 | 2 / 1 | 7 |
| stage_d / device_camera_plugin | 1 / 0 | 1 / 0 / 0 | 20 / 0 | 0 |

Metrics include all current executed Family-only+B+C+D runs. Family-prefixed
fields in final_report.json describe standalone Family; staged Family is separate.
Context invalidations count navigation-observer events plus distinct capture
freshness downgrades. Recovery lifecycle counts are observed context recovery
flag/overlay boundaries; native production recovery requests/results are retained
and reported separately. Authority regain is a blocked prior step or denied state
gate becoming authorized; each step is counted once. Execution after revalidation
includes owned context revalidation or bounded current-state target rebind.
These counters never award visits. Native primary RECORDED events, native strong
recovery visit events and copied final-row credits remain separate production
facts. Full per-step ownership/epoch/freshness/gate/request/focus/final actor
evidence is in each *_dynamic_metrics.json and *_audit_metrics.json.

## Coverage and remaining limits

| Scenario | Bounded comparison | New native primary visits / baseline prefix | Termination |
|---|---|---:|---|
| life_find_plugin | EQUIVALENT | 8 / 8 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_smoke_sensor_plugin | IMPROVED | 7 / 6 | COMPLETED / plugin_boundary_global_nav |
| device_tv_plugin | EQUIVALENT | 10 / 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_washer_plugin | EQUIVALENT | 10 / 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_energy_plugin | EQUIVALENT | 10 / 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_food_plugin | ACCEPTABLE_VARIANCE | 18 / 19 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_family_care_plugin | ACCEPTABLE_VARIANCE | 10 / 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_camera_plugin | IMPROVED | 16 / 15 | INCOMPLETE_SAFETY_LIMIT / safety_limit |

These are bounded state-sensitive comparisons, not complete coverage or Full32
equivalence. Family ACTIVE/WAITING and Food content/viewport variance are not
compared blindly. Partial context allows only independently safe structure;
missing/contradictory body or unknown epochs continue to block. Cross-component
activity changes remain conservative and may require new normal-entry evidence.
Two-capture body/target requirements may defer a legitimate control while the
UI is transient. Scroll retains its original gate; no focus-rebind exemption
is applied to scrolling. Camera remains coverage-first; a20-step safety cap
does not establish complete coverage or a termination regression. No shorter
production Camera or Family cutoff is added.

## Closure

OVERALL_VERDICT=PHASE4_DYNAMIC_CONTEXT_RECOVERY_REJECT
PHASE4_COMPLETE=NO
READY_FOR_PHASE5=NO
PHASE5_IMPLEMENTED=NO
DEFAULT_PRODUCTION_SMART_TRAVERSAL=OFF

A staged acceptance gate or required closure evidence did not pass. Dependent
stages stopped; no automatic retry, authority override or main merge was made.
The unresolved blocker is preserved in final_report.json and original acceptance
artifacts. Valid local changes are retained; no commit/push occurs. Phase4 remains
incomplete and Phase5 readiness is NO.

Current rejection is specifically Camera NO_CONTROLLED_EXECUTION: normal entry
passed, but all20 actions used production fallback under RECOVERY_CONFLICT.
Saved overlay/recovery observations kept ownership STALE_REVALIDATABLE and
RECOVERY_ACTIVE; no completion/rebound or controlled focus/scroll was observed.
Camera still records20 actual focus moves,16 native visits and20 complete audit
chains, with all safety/audit/lifecycle gates zero. The20-step safety cap itself
is not the rejection reason. Family-only and StageB/C all pass.
camera_new_blocker.json preserves every before/current capture, reconstructed
popup detector result, gate evidence and original-file hashes. The next task
is to distinguish a real modal from a broad popup-detector signal using this
saved evidence. No classifier/authority change, retry or Camera cutoff change
was made to conceal the blocker.

The saved Camera resource trigger is the PIP control: `btn_popup_play`,
`btn_popup_play_parent` and `btn_popup_play_frame` under `live_overlay_layout`.
The existing detector treats the substring `popup` as modal evidence. This proves
the source of `popup_resource`; it does not by itself establish a true modal or
justify bypassing recovery. Generic popup-vs-presentation classification is the
specific next RCA boundary.

Evidence root: ../phase4c_dynamic_context_recovery_20261011/. See final_report.json/
.txt, source/test/frozen manifests, behavior_scope_proof.json, family_authority_loss_rca.json,
family_new_replay.json, audit_replay.json, corrected historical replay summaries,
coverage_comparison.json, per-run metrics, native journals, immutable destination/
action sidecars, acceptance files and monitor results. Prior originals remain
unchanged under ../phase4c_audit_recovery_20261011/.

## Camera popup false-positive recovery retry — 2026-10-11

The earlier Camera rejection above remains as historical evidence. This retry
closed that blocker without changing planner ranking, focus/visit authority,
scroll policy, starvation policy, Camera step limits, or termination behavior.

### RCA and modal contract

The old popup detector treated a `popup` substring in resource IDs as modal
evidence. In particular, `btn_popup_play*` contributed `popup_resource`; that
token also made the old `modal_container_seen` predicate true, allowing
`title_body_with_actions` to be synthesized from unrelated labels and actions.
The diagnostic then marked an overlay observed, recovery became active, and the
execution gate returned `RECOVERY_CONFLICT`. No dialog window, blocking region,
focus trap, inaccessible background, or required dismissal was needed by that
old path. The resource name proved only that a candidate had been found.

Popup-like resource IDs, text, and descriptions now nominate candidates only.
The shared classifier returns `VERIFIED_MODAL`, `LIKELY_MODAL`,
`NON_MODAL_CONTROL`, or `AMBIGUOUS_OVERLAY`. Dialog-window evidence, dialog
hierarchy, substantial blocking bounds, background accessibility, and actual
`accessibilityFocused` placement inform the result. A localized control is
cleared as non-modal only with same-activity ordinary-window evidence, a small
candidate region, accessible background, and accessibility focus outside it.
Input focus is not a substitute for accessibility focus. Ambiguous evidence
remains conservative. Popup dismissal is eligible only for verified or likely
modal states; the recovery gate remains unchanged and still blocks ambiguous
overlay evidence.

### Camera evidence and live retry

Camera's `btn_popup_play_parent` (`LinearLayout`),
`btn_popup_play_frame` (`FrameLayout`), and `btn_popup_play` (`ImageButton`,
description `PIP`) are localized descendants of `live_overlay_layout` in the
same Camera `MainActivity` base application window. Their union occupied about
0.8657% of the display. The live capture summarized 22 windows; the active
focused window remained Camera `MainActivity` / `BASE_APPLICATION`. The
background remained accessible and accessibility focus stayed outside the PIP
on 19 of 20 steps. This supports `INLINE_PIP_CONTROL` with high confidence for
those steps. At step 19, TalkBack accessibility focus was inside the PIP, so
the classifier returned `AMBIGUOUS_OVERLAY` and the existing recovery conflict
gate safely fell back.

The Camera-only run entered normally and completed its 20-step bound:

| Measure | Result |
|---|---:|
| Popup candidates | 20 |
| Verified / likely modal | 0 / 0 |
| Non-modal / ambiguous | 19 / 1 |
| Planner recommendation / authorization / execution | 19 / 19 / 19 |
| Production fallback / recovery conflict | 1 / 1 |
| Confirmed focus moves / native visits | 20 / 19 |
| Audit chains incomplete | 0 |
| Termination | `INCOMPLETE_SAFETY_LIMIT` / `safety_limit` |

The old rejected 20-step trace is preserved. Replaying it changes the prior
20/20 recovery-conflict decisions to 16 authorized and 4 still blocked; the
replay performs no actions and awards no visits. A live modal did not occur in
this retry. Constructed regression cases establish true-modal blocking,
including dialog-root plus inaccessible background, substantial blocking
overlay with dismissal, and contradictory dialog-window evidence. A small PIP
with accessible background is non-modal; popup-like names without modal
evidence cannot trigger dismissal.

### Regression and closure gates

Focused dynamic-context, audit, Phase 3, production, Phase 4, popup/modal, and
window-evidence suites passed. Full Python result: **3814 passed, 1 skipped,
0 failed**. Helper source was unchanged; the previously accepted 408 Helper
tests remain the applicable result. Historical Phase 3 replay matched 16
records; Phase 4A and Phase 4B replay inputs matched 30 and 30; accepted
baseline replay passed six scenarios; Phase 4C pre-stop replay matched 57;
Food audit replay retained 97 complete prior chains and repaired the step-11
linkage; Family recovery reference remained safe; the rejected Camera replay
produced no actions or visit mutations.

Stage B passed live 4/4 (Find, Smoke Sensor, TV, Washer). Stage C passed live
3/3 (Energy, Food, Family Care). Family Care completed 10 steps with 10 native
visits in about 802 seconds. Food's bounded run credited 16 visits versus a
19-visit reference prefix, while discovering 22 candidates, visiting 21 unique
instances, executing all three recommended scrolls, completing 20 observations,
and recording no failed/indeterminate focus movement or safety/audit violation.
This is recorded as state-sensitive `ACCEPTABLE_VARIANCE`, not equivalence.
Camera improved from 15 reference-prefix visits to 19. Find, Energy, Family
Care, TV, and Washer were equivalent; Smoke Sensor improved. No coverage
comparison was classified as a regression.

All audit, planner-safety, lifecycle, and transport hard gates were zero across
the eight live scenarios. The default production Smart Traversal feature flags
remain off. No true modal was encountered live, so true-modal blocking is
supported by focused constructed tests rather than a device observation. One
Camera focus-inside-PIP observation remains explicitly ambiguous and safely
blocked, and bounded Camera termination does not establish full coverage.

OVERALL_VERDICT=PHASE4_CAMERA_MODAL_RECOVERY_PASS_WITH_LIMITATIONS
PHASE4_COMPLETE=YES
READY_FOR_PHASE5=YES
PHASE5_IMPLEMENTED=NO
DEFAULT_PRODUCTION_SMART_TRAVERSAL=OFF

The machine-readable run report and per-step evidence are in
`../phase4c_camera_modal_closure_retry_20261011/final_report.json` and
`camera_modal_step_summary.json`. The standalone RCA is
`talkback-phase4c-camera-modal-rca-20261011.md`.
