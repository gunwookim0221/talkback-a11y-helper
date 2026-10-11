# Phase 4C dynamic destination context and recovery re-entry

## Source and proven blocker

Work only on integration/phase3-current-main. Integration start/origin:
`a4795a14501f7c6956e1bfe45ee1dd87f687b2b6`. Main/origin remain
`6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`; original Phase 3 remains
`fb4d01c489a0b3d56883e074771eb823c453d4f2`. Prior justified local Phase 4C
changes are retained. No pull, main merge, Phase 5 implementation or global
Smart Traversal enablement is included.

Previous immutable artifacts: ../phase4c_audit_recovery_20261011/stage_c.
Family's ten old recommendations and gate decisions replay exactly. Step1:
original state_id=null, fresh state_id=phase4b-controlled-smoke:state:00000002;
the gate safely denies STATE_OR_SUBSTATE_CHANGED. Normal production subsequently
opens/recovers an overlay and returns to the plugin. Step2 denies RECOVERY_CONFLICT.
Steps3-10 deny CONTEXT_INSUFFICIENT: the navigation guard changed the epoch,
while the only normal-entry proof retained the original epoch. No adapter path
reacquired same-destination ownership after the body returned. All ten current
observations retain the entry activity and shared plugin body resource IDs.
Budget degradation was not necessary to explain the zero controlled actions.

The cause is a transient state mismatch followed by missing generic destination
reacquisition/recovery rebinding. This is not a proven unsafe action or visit
failure. family_authority_loss_rca.json records all ten requested fields and
source hashes. The exact fixture retains original before/fresh snapshots,
contexts, history, safety flags and outcomes; complete native originals are not
rewritten. No Family-specific selector or state exemption is introduced.

## Destination, state and substate

- Destination identity: trusted normal-entry contract digest, owned scenario run,
  entry navigation epoch, runtime component and original capture provenance.
- State identity: discovery registry state_id/fingerprint/viewport, possibly
  unresolved. It changes with observed UI structure and content.
- Substate identity: discovery semantic_substates, when available.

The destination token deterministically composes existing entry/run/destination/
component/capture evidence. State and substate are excluded from the token.
State changes do not manufacture a new plugin destination, nor imply a visit.

## Freshness and contradiction

DestinationOwnership is a scenario-local Phase 4C adapter. Normal entry and its
existing post-open proof are required; scenario name alone cannot establish it.
Fresh observations use the existing Phase 3 generic resolver, actual component,
selected-tab compatibility and body evidence. Capture IDs must be distinct and
timestamps ordered. Ownership cannot migrate to a different scenario/run or an
unknown externally supplied navigation epoch.

| Freshness | Authority |
|---|---|
| FRESH_VERIFIED | Existing target gate may consider execution |
| FRESH_PARTIAL | Only independently proven structural safety |
| STALE_REVALIDATABLE | Suspend and reacquire body evidence first |
| STALE_INVALID | Reject; normal entry is required again |
| CONTRADICTORY | Drop/block ownership |

The navigation observer preserves every original command and result. Click,
tap or Back provisionally suspend the token; they do not attest internal
navigation by themselves. Two different fresh observations must restore the
owned component and destination-specific body evidence. Shared generic WebView
IDs or common words alone are insufficient. Strong evidence is either an
entry-owned body namespace matching the runtime component, or a configured
destination title plus verified current body and shared entry resources.

Home, activity launch, force-stop and explicit scenario exit invalidate the
old token. Another plugin/root activity, incompatible selected global tab,
different configured destination body, package mismatch or unknown owner epoch
also blocks. A temporary body absence during recovery stays revalidatable;
it never authorizes an action. Original normal-entry facts remain immutable;
derived proof records the original entry capture and the explicit lease ID.

## Recovery lifecycle and authority re-entry

Observed production recovery flags/overlay produce RECOVERY_STARTED and
RECOVERY_ACTIVE. Controlled execution stays blocked. Once flags clear:
RECOVERY_COMPLETED → RECOVERY_REVALIDATING → RECOVERY_REBOUND requires two
fresh body proofs. A contradiction produces RECOVERY_FAILED; no unsafe retry is
issued. Repeated successful recovery does not permanently poison the lease.
These context-boundary observations are reported separately from native
production recovery request/result events.

After state or inventory changes, rebind_execution may reconsider a denied
state/structural-scope/ranking gate. It does not ignore the old denial or use an
old target. It validates the old planner recommendation, regenerates a current
recommendation with the unchanged planner, and requires exactly one matching
safe focus target in both independently captured inventories. Resource/class/
bounds and enabled/focusable/presence/safety evidence must agree.

Only then does the unchanged Phase 4B gate validate the current plan/current
state again. Every focus, geometry, ranking, history/stale-target, lifecycle,
transport, recovery and bounded-budget condition remains effective. Scroll
does not use this focus rebind path. No new capture loop, scenario retry, forced
authorization, visit award or failure-budget reset is added. Missing two-capture
target evidence continues to fall back. Actual execution still uses existing
Helper commands, target binding and production focus/visit reconciliation.

## Immutable audit

Each step records before/current destination lease, navigation/recovery epoch,
freshness, revalidation result, initial/final authority reason and current-state
replan proof. Append-only phase4c_destination_events.jsonl records deterministic
event IDs. The existing step-action chain includes these ownership transitions;
its final-row reference/hash preserves primary, recovery and final actor facts.
The checker verifies the ownership against the saved before/fresh observations,
the event sidecar and the immutable action chain. Cross-destination/scenario
context use, stale execution or altered provenance rejects.

Production accessibility focus and reconciliation remain the only visit
authority. No context status independently creates/revokes visits. The original
Food mismatch/rejection and all 97 earlier audit chains remain preserved.

## Offline validation and live plan

The dynamic test matrix covers state/substate separation, recovery start/clear,
two-capture body restoration, contradictory destinations, root disappearance,
global navigation, epoch/run isolation, partial safety, weak generic body,
repeated recovery, immutable events and target/history/budget/focus safety.
Exact rejected Family replay: old 10/10 blocked; new six later safe steps regain
authority, while four remain blocked. No replay action or visit is issued.

Focused/full Python and historical Phase 3/4A/4B/baseline, prior Phase 4C, Food
audit and Family replay gates must all pass on frozen source before live.
Helper source is unchanged. Live plan: Family-only10, full shared StageB sanity,
then Energy10/Food20/Family10, then Camera20 only after StageC passes.
Normal production entry, validated clean start and correlated hard-stop monitor
remain mandatory. No automatic retry follows a true hard failure. Final results,
metric definitions, coverage limits and closure are appended after live gates.

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
