# Phase 5B Secondary Dispatch Authorization RCA and Recovery

## Proven failure

Preserved evidence: `out/phase3_current_main_20261011/phase5b_safe_navigation_20261012/fallback_hard_stop_rca.json` and the matching `stage_a_recovery_03` native evidence. Home step 10 sent Helper request `895773aeb784427eade19957520d14f9` as `TARGET_FOCUS_COMMIT` for resource ID `com.samsung.android.oneconnect:id/device_name`, class `android.widget.TextView`, bounds `78,635,309,683`. The correlated Helper ACK reported success and actual accessibility focus on that target.

The node was not in the current planner candidate population. Its raw node evidence showed `focusable=false`, `clickable=false`, and a label of `세이프 버튼`. Reclassifying the dispatched operation as FOCUS with the unchanged Phase 5A classifier yields `UNKNOWN / FOCUS_CAPABILITY_UNPROVEN`. Therefore `UNKNOWN_TARGET_EXECUTED=YES` is proven.

The exact source path was:

`SafeNavigationSession.collect/fallback` → passive `collect_focus_step(move=False)` → production `_apply_step_collection_phase_impl` → `maybe_capture_focus_crop` → local-tab representative selection/alignment → `focus_realign_logic` → `target_focus_fn` → `A11yAdbClient.target_focus_commit` → Helper `TARGET_FOCUS_COMMIT`.

The primary planner authorization was not reused as an exact target credential in code; rather, the firewall admitted any strict focus command by suffix, so the secondary action had no target-specific authorization check at all. The previous monitor made the same invalid assumption by whitelisting `TARGET_FOCUS_COMMIT` without linking request ID to target classification. The production reconciliation correctly recorded actual accessibility focus movement and remains authoritative for visits. No incorrect visit credit or lifecycle/transport blocker was found.

## Recovery contract

Phase 5B owns a one-use permit for the exact focus action and target identity. It records resource ID, class, normalized bounds, Phase 5A safety class and policy, Phase 4 gate, destination ownership, state ID and structural observation epoch. At the native ADB boundary, dispatch requires the exact target payload, a current epoch, a valid Phase 4 gate and a fresh Phase 5A policy recheck. A single exact Helper request consumes the permit.

Fallback, a new observation, retargeting, state rebuild, or dispatch-scope exit invalidates the permit. Passive reads remain available. A downstream production alignment without its own fresh target authorization is blocked before the Helper receives it. UNKNOWN stays blocked, including non-focusable observed nodes. This does not change the Phase 5A classifier, planner ranking, focus reconciliation, attempt ledger or production visit authority.

The safe-navigation monitor treats Helper `ACTION_EXECUTION_STARTED` as evidence of execution. It requires every focus request to link by exact request ID to one valid authorization event and checks the Helper's `TARGET_REQUESTED` resource ID and bounds against that event. A locally emitted `ACTION_SENT` with an explicit transport block and no Helper execution-start is a blocked attempt. An execution-start without an authorization is a hard failure.

## Regression matrix

Tests A–M cover one-use exact-target authorization, target and action changes, fallback invalidation, fresh safe-secondary authorization, UNKNOWN blocking, risky/forbidden activation non-inheritance, post-scroll and state rebuilds, visual-label collisions, stale steps and stale scenarios. An exact regression fixture replays the preserved Home `device_name` request and verifies that the Helper transport is never called.

## Acceptance status

Implementation, focused/full tests, saved replay matrix, staged live results, git status and final Phase 5B/Phase 5C verdict are filled in after the current recovery run. Prior rejected artifacts remain preserved and are not overwritten.

## Return-confirmation observation RCA (2026-10-12)

The later staged retry stopped at Stage A `devices_main`, step 5, with
`SAFE_RETURN_OWNERSHIP_NOT_PROVEN`. The single Back action had succeeded and
returned to the same app, activity, scenario run, and Phase 3 entry. The first
parent capture used `helper_capability+service_hierarchy_semantics`, exposed a
verified `devices` tab, and matched the original 104-node / 68-identity
structure. The second capture fell back to `helper_flat` after hierarchy
capture failed, had 57 nodes, omitted selected-tab evidence, and resolved to
`PARTIAL_CONTEXT`. No contradictory app, run, entry, tab, or modal evidence was
observed. The return was safely rejected because the two required complete
observations did not match.

The generic correction treats missing hierarchy/tab evidence as inconclusive,
not as proof of a wrong destination. It permits at most four passive return
captures and requires two consecutive complete observations to match the
original destination, structure, overlay state, and verified context. A
positive mismatch in app/activity/run/entry/tab, modal state, or Phase 3
context stops confirmation immediately. No entry or Back action is repeated;
the attempt and visit ledgers are unchanged. Regression cases cover a single
transient Helper-flat sample, persistently unstable evidence, and a positively
wrong tab.

## Empty resource-ID authorization RCA (2026-10-12)

The fresh Stage B Food run stopped with four incomplete action chains and four
request-ownership mismatches. In steps 1, 2, 13, and 14, Phase 5B issued a
one-use permit for a candidate whose resource ID was the empty string. The
ADB shell encoder represented that empty extra as `""`. The preflight path
compared the empty value, while `_extras` at the actual ADB firewall left the
two quote characters intact, so it rejected the same request as
`TARGET_IDENTITY_MISMATCH` after `ACTION_SENT` had been recorded. The Helper
never executed those blocked requests; audit then paired the blocked request
with a stale prior `TARGET_ACTION_RESULT`, correctly reporting mismatched
request ownership. This is a transport-boundary normalization defect, not a
Phase 5A classification or production visit defect.

The generic correction decodes only the exact paired-double-quote empty
sentinel to an empty value before the native target comparison. Class, bounds,
request ID, permit, policy, gate, and epoch checks remain exact. Regression
coverage exercises preflight and ADB boundary agreement for an anonymous
resource ID and replays the four preserved mismatches without sending a device
command.

## Bounds-only recovery audit RCA (2026-10-12)

The next staged retry passed all Stage A scenarios and stopped at Stage B Food.
Food step 9 had one correlated primary target action, followed by 14
bounds-only `FOCUS_IN_BOUNDS` recovery attempts. The Phase 5B ADB firewall
blocked every recovery attempt before Helper dispatch (`executed=false`), and
the authorization records classified them as blocked. No UNKNOWN, RISKY, or
FORBIDDEN target executed. The primary action retained its exact request/ACK
correlation and focus reconciliation.

The audit mismatch came from ordering: `focus_in_bounds()` emitted
`ACTION_SENT` before calling the ADB firewall. A denied command therefore
looked dispatched in the immutable request journal, despite having no Helper
ACK or recovery result. Since the step index carried `:recovery:N`, the audit
correctly treated it as an incomplete recovery action. Recovery then skipped
the post-action capture because the firewall exception escaped, avoiding false
visit credit but leaving the misleading `ACTION_SENT` record orphaned.

The generic correction adds an opt-in bounds-focus preflight to the Phase 5B
firewall. Bounds-only requests cannot satisfy exact target authorization, so
they are rejected before `ACTION_SENT` and before Helper. The recovery executor
closes that blocked transaction without a post-action observation or recovery
result, preventing focus movement from a prior action from being attributed to
a command that was never dispatched. Exact-target focus keeps its existing
one-use permit, native boundary recheck, and request correlation. Regression
tests verify preflight denial, absence of `ACTION_SENT`/Helper dispatch, and no
post-block recovery visit attribution.

## Secondary activation preflight RCA (2026-10-12)

The next fresh staged retry passed both probes, all Stage A scenarios, and
Stage B Food. Family Care then stopped at step 1. The production overlay path
called `A11yAdbClient.touch()` for a “More options” `ImageView` with no resource
ID, at `924,106,1032,286`. This was a `CLICK_TARGET` activation outside the
controlled planner step: it had no exact Phase 4 action gate and no Phase 5
target/action permit. The Phase 5A classifier resolved the uniquely observed
target to `UNKNOWN / ACTIVATION_EFFECT_UNPROVEN`. The lowest ADB firewall
correctly prevented Helper execution, but raised `SafetyBlocked`; the smoke
harness then exited with code 3, leaving the scenario incomplete. No Helper
execution, visit credit, or lifecycle/transport hard hit was observed.

The correction adds a generic opt-in activation preflight to `touch()`. While
the Phase 5B firewall is active, it resolves the requested selector against
the current visible hierarchy and records its exact action/target
classification. Without a matching Phase 4 gate and target-scoped Phase 5
authorization, it returns `BLOCKED_BEFORE_DISPATCH` before broadcast and
without entering the retry loop. The overlay handler marks that blocked
entry as handled and continues ordinary production traversal; it does not
reclassify the activation as safe or award attempt/visit credit. Direct
unmediated activation commands remain denied by the lower ADB firewall.
Monitor metrics count these preflight denials as blocked secondary attempts,
not executions.

The preserved Family Care step replays from its actual captured hierarchy and
blocked `CLICK_TARGET` evidence. The replay reports a unique target match,
UNKNOWN classification, missing Phase 4 action gate, zero broadcast/ADB
dispatch, and zero visit credit. The previous Home UNKNOWN focus replay also
remains blocked before Helper. The focused, broad, full-suite, deterministic
replay, and new staged results are recorded under
`../phase5b_secondary_auth_recovery_20261012/quality_after_secondary_activation_fix`.

## Final staged acceptance

The final device run used serial `R3CX40QFDBP`, kept locale `en-US`, TalkBack
PID `19549`, and Helper PID `18024` stable, and completed on 2026-10-12. It
ran for 67.67 minutes and included two 10-step Home/Devices preflight probes, then Stage A (Home,
Devices, Life: 10 steps each), Stage B (Food: 20; Family Care: 10), and Stage C
(Smoke Sensor: 7; Door Lock: 6; TV: 10; Washer: 10; Camera: 20). All 12
scenario rows passed, including all ten required Stage A/B/C scenarios. The
saved monitor artifacts report one expected, started, and completed scenario
per run, no smoke stops, no hard hits, and zero lifecycle/transport gates.

Fresh monitor revalidation was run against the preserved native artifacts after
the counter correction; it did not repeat any device scenario. The counts below
separate Stage A/B/C from the two preflight probes:

| Metric | Stage A/B/C | Including probes |
| --- | ---: | ---: |
| Secondary attempts / blocked / executed | 36 / 36 / 0 | 39 / 39 / 0 |
| Secondary SAFE / UNKNOWN | 3 / 33 | 4 / 35 |
| Secondary authorization rechecks / failures | 36 / 36 | 39 / 39 |
| Authorization invalidations / permit grants | 230 / 100 | 276 / 120 |
| Production fallbacks | 10 | 12 |
| Secondary focus retargets / fallback rechecks | 35 / 35 | 38 / 38 |
| Safe child entries / successful returns | 3 / 3 | 5 / 5 |
| Safe alternatives / verified safe scrolls / read-only fallbacks | 103 / 6 / 10 | 121 / 6 / 12 |

The secondary class totals for conditionally safe, risky, and forbidden targets
were zero in both scopes. Unknown/risky/forbidden and known destructive,
payment, account-mutation, physical-device-control, or external-send executions
were all zero. Authorization mismatch, stale authorization, cross-step and
cross-scenario authorization leaks, Phase 4 unsafe/ambiguous execution, false
visit/focus, stale target, unbounded loop, and cross-context gates were zero.
The click preflight for Family Care is included in secondary attempt totals but
excluded from fallback focus-retarget counts.

Camera completed the requested 20-step bound with 11 controlled focus actions
and nine production fallbacks (`RECOVERY_CONFLICT`). Its audit chain remained
complete and no unsafe action executed, but traversal coverage is still limited.
This does not block safe closure; it is the reason for the
`PASS_WITH_LIMITATIONS` verdict. Live secondary focus attempts were all blocked,
including four SAFE-class targets that lacked their own Phase 4 execution gate.
The separate test matrix proves a SAFE secondary can execute after a fresh
target-scoped authorization and gate. UNKNOWN remains blocked.

The final Python suite passed: **4,086 passed, 1 skipped**. The focused
Phase 5A/5B/Phase 3/production/Phase 4 groups passed (150/117/58/465/306), and
the exact UNKNOWN replay plus safe child-entry/return replays passed. The
historical Phase 3, Phase 4A, Phase 4B, accepted baseline, Phase 4C, Food audit,
Family recovery, Camera modal, Phase 5A shadow, Home UNKNOWN focus, and Family
Care secondary-activation replay gates passed. Policy mode remains `off` and
safe navigation `default_enabled` remains `false`.

Final result: `PHASE5B_SECONDARY_AUTH_RECOVERY_PASS_WITH_LIMITATIONS`,
`PHASE5B_COMPLETE=YES`, `PHASE5C_IMPLEMENTED=NO`,
`READY_FOR_PHASE5C=YES`. The revalidated monitor totals are preserved in
`../phase5b_secondary_auth_recovery_20261012/quality_after_secondary_activation_fix/phase5b_live_metric_revalidation.json`;
the full final report and device artifacts remain in the adjacent live output
folder.
