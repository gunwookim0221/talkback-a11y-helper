# TalkBack Phase 5C Full32 Acceptance — 2026-10-12

## Latest continuation result — 2026-10-13

**PHASE5C_HARNESS_RECOVERY_REJECT**<br>
PHASE5_COMPLETE=NO · READY_FOR_PHASE6=NO · PHASE6_IMPLEMENTED=NO

This is the authoritative result for the budget-mapping recovery and Full32
continuation. It supersedes the earlier precheck-only checkpoint documented
below. The corrected continuation reused scenario 1, accepted scenario 2 from
preserved live evidence, and passed scenarios 3 and 4. It hard-stopped on
scenario 5, life_air_care_plugin, before traversal because the Phase 4C
observer could not establish a trusted normal plugin entry. No later scenario
started and no retry was made.

### Budget root cause and correction

The continuation plan correctly retained production max_steps=100, but the
safe-navigation worker copied that value into the shared Phase 4C/5B BUDGETS
map. The controlled smoke layer then used the same value for
ExecutionBudget(max_actions=...), whose contract is 1..20. This produced the
original “controlled action budget must be 1..20” error before scenario 2
traversal.

The generic mapping now keeps two independent values: production max steps
remain coverage-first, while the Phase 5 controlled-action budget is bounded
using the existing policy (default 10, existing Food and Camera exceptions
20). Initial and continuation Full32 paths consume the same plan. The Phase
4C loop monitor was also corrected after scenario 2: it had compared all 14
production rows with the controlled budget of 10 and falsely raised
PLANNER_LOOP_UNBOUNDED, despite only 9 controlled actions. It now checks
production rows against the production limit and executed controlled actions
against their separate limit. Scenario 2 evidence was revalidated offline;
the live scenario was not rerun.

No safe-action, authorization, focus-reconciliation, planner, or visit policy
changed. The local source changes are limited to the budget policy, the
controlled-smoke adapter, the Phase 4C acceptance monitor, and tests.

### Canonical continuation results

| Order | Scenario | Result | Production steps | Controlled budget / used | Notes |
|---:|---|---|---:|---:|---|
| 1 | global_nav_main | PASS, preserved | 5 destinations | Not applicable | Revalidated from preserved evidence; not rerun |
| 2 | home_main | PASS, offline revalidation | 14 | 10 / 9 | Live evidence terminal INCOMPLETE_NO_PROGRESS; no new visits after no movement |
| 3 | home_safe_plugin | PASS | 100 | 10 / 10 | INCOMPLETE_SAFETY_LIMIT; 8 confirmed focus executions; 92 production fallbacks |
| 4 | life_food_plugin | PASS | 100 | 20 / 20 | INCOMPLETE_SAFETY_LIMIT; 17 confirmed focus executions and 3 safe scrolls |
| 5 | life_air_care_plugin | REJECT before traversal | 0 | 10 / 0 | Runtime error: ValueError: Trusted normal plugin entry required |

For scenario 5, clean-start/device precheck completed and the runner started,
but the traversal summary records attempted_steps=0,
termination_status=INCOMPLETE_ERROR, and termination_reason=runtime_error.
The exception occurred while phase4b_controlled_smoke.py initialized
DestinationOwnership from the observed entry state. The registry has no
trusted entry state and no destination event file was emitted. The monitor
reported no lifecycle or transport hard hits. This is a new unresolved
pre-traversal integration blocker; its root cause has not been proven beyond
the exception and missing trusted-entry evidence.

Read-only RCA of the Air Care logs narrows the failure: the XML entry path
selected an Air Care card, then logged a target-not-found result; the existing
production entry verifier nevertheless accepted internal Air Care content
signals, including Outdoor air is Unhealthy and Add an air conditioner, and
emitted success_verified/plugin_open_verified. The Phase 4C ownership adapter
then rejected the context because DestinationOwnership only accepts a
VERIFIED_PLUGIN_CONTEXT or PARTIAL_CONTEXT with a destination identity.
Therefore the proven failure is a contract disagreement between the
production Air Care entry verdict and the generic destination-ownership
context. The exact generic context status/reason was not persisted: the
observer saves its raw entry observation after DestinationOwnership
construction, which throws first. This does not prove whether the mismatch
came from component identity, selected-tab evidence, or body ownership. No
source change or retry was made for this separate blocker.

Canonical accounting is 32 expected, 5 scenario IDs observed, 4 terminal
scenario results, 1 failed scenario run, and 27 later scenarios not started.
The original scenario 2 budget-failure folder is preserved as a failed
harness attempt and is not a terminal result. The continuation returned code
1 with overall state REJECT.

### Gates, safety, and runtime

- Focused regression gates passed: 344 tests; the full Python suite passed
  4,100, with 1 skipped and 0 failures.
- Offline replay gates passed, including the Phase 5A/5B authorization and
  Phase 4C representative replays. The final representative Phase 4C replay
  accepted six scenarios with no actions or visit credit.
- Across the accepted scenario 2–4 reports, risky, forbidden, unknown,
  destructive, payment, account-mutation, physical-device-control, and
  external-send executions were all zero. Emitted planner-safety and audit
  hard gates were zero. Scenario 5 had no traversal actions.
- The full32-wide safety/authorization totals and coverage comparison remain
  incomplete because scenarios 5–32 did not pass. Phase 5 is not closed.
- Before this continuation, device precheck had paused at SmartThings two-step
  verification. The user completed it and returned SmartThings to Home; that
  manual wait is excluded from active runtime.
- Active scenario runtime sum: 6,869.748 seconds. End-to-end wall span:
  37,494.695 seconds. The recorded accounting excludes manual wait from
  active runtime.
- Device serial was R3CX40QFDBP, locale remained en-US, TalkBack PID
  remained 19549, and Helper PID remained 18024. All emitted lifecycle
  and transport counters were zero.

### Source and artifacts

| Gate | Result |
|---|---|
| Branch | integration/phase3-current-main |
| Start / final / origin integration HEAD | 07fc6e4f7a882e6a98588006d781a5904f67ab83 |
| Main / origin main | 6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee |
| Original Phase 3 branch | fb4d01c489a0b3d56883e074771eb823c453d4f2 (unchanged) |
| Main changed | No |
| Commit / push | None; final acceptance rejected |
| Defaults | Production smart traversal OFF; safe-action enforcement OFF |

Key evidence:

- [Canonical Full32 state](../../out/phase3_current_main_20261011/source/out/phase5c_full32_resume_20261012/full32/canonical_full32.json)
- [Canonical scenario ledger](../../out/phase3_current_main_20261011/source/out/phase5c_full32_resume_20261012/full32/canonical_scenario_results.jsonl)
- [Scenario attempt history](../../out/phase3_current_main_20261011/source/out/phase5c_full32_resume_20261012/full32/scenario_attempts.jsonl)
- [Scenario 5 stage summary](../../out/phase3_current_main_20261011/source/out/phase5c_full32_resume_20261012/full32/05_life_air_care_plugin/stage_summary.json)
- [Scenario 5 traversal summary](../../out/phase3_current_main_20261011/source/out/phase5c_full32_resume_20261012/full32/05_life_air_care_plugin/run/life_air_care_plugin/talkback_compare_20261013_005614.traversal_summary.json)
- [Scenario 5 runner log](../../out/phase3_current_main_20261011/source/out/phase5c_full32_resume_20261012/full32/05_life_air_care_plugin/runner.log)
- [Budget policy](../../out/phase3_current_main_20261011/source/tb_runner/phase5c_budget_policy.py)
- [Budget policy tests](../../out/phase3_current_main_20261011/source/tests/test_phase5c_budget_policy.py)

The next acceptance task must RCA the generic trusted plugin-entry failure and
resume at scenario 5 using the preserved canonical state. Do not rerun
scenarios 1–4.

## Previous checkpoint verdict (superseded by the continuation result above)

**`PHASE5C_FULL32_ACCEPTANCE_REJECT`**<br>
`PHASE5_COMPLETE=NO` · `READY_FOR_PHASE6=NO` · `PHASE6_IMPLEMENTED=NO`

All five high-risk sanity scenarios passed. The initial Full32 attempt stopped
on scenario 1 (`global_nav_main`): the app's specialized global-navigation
runner verified all five destinations, but the shared Phase 5B acceptance
validator rejected it because it requires ordinary traversal rows and planner
execution. The acceptance-only validator was corrected and passed against the
preserved live scenario 1 evidence; scenario 1 was not rerun. A continuation
then stopped at its device precheck because a SmartThings two-step-verification
prompt left bottom navigation unavailable. Scenario 2 never started. This is
not evidence of a production navigation regression, but Full32 safety coverage
remains incomplete and Phase 5 is not closed.

## Source and defaults

| Gate | Result |
|---|---|
| Branch | `integration/phase3-current-main` |
| Start / final HEAD | `07fc6e4f7a882e6a98588006d781a5904f67ab83` |
| `origin/integration/phase3-current-main` | `07fc6e4f7a882e6a98588006d781a5904f67ab83` |
| `main` / `origin/main` | `6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee` |
| Original Phase 3 branch | `fb4d01c489a0b3d56883e074771eb823c453d4f2` (unchanged) |
| Tracked source changes during acceptance | None |
| `config/safe_action_policy.json` default | `off` |
| `config/safe_navigation_contracts.json` default | `false` |
| Main changed / merged | No |

The required branch/source gate passed with a clean tracked worktree before
acceptance. The only local documentation changes are this report and its index
entry. No functional source or Helper change was made. No commit or push was
made.

## Pre-acceptance gates

Focused gates passed: Phase 5A 150, Phase 5B 117, Phase 3 58, production 465,
and Phase 4 306 tests; zero failures or skips. Full Python passed **4,086**,
with **1 skipped** and **0 failures** in 180.56 seconds.

Offline replays passed for historical Phase 3, Phase 4A/B, Phase 4C, the accepted
baseline, Food/pre-Food and audit linkage, Family Care recovery, Camera modal,
Phase 5A dynamic context, UNKNOWN focus authorization, and secondary
authorization preflight. The Phase 5B safe-child return and settling replays
also passed: 1/1 return success in each, 0 visit credit, and complete audit
preservation. Evidence is in [`replay/`](../../out/phase5c_full32_acceptance_20261012/replay/).

After live validation, the Phase 5A safety tests passed again (150/150) and the
Phase 5B authorization tests passed again (117/117). Since functional source
was unchanged, the full Python suite was not rerun after the device session.

## Device precheck

| Item | Captured value |
|---|---|
| Device | `R3CX40QFDBP` |
| Locale | `en-US` before and after; unchanged |
| SmartThings | `1.8.51.30` |
| Helper | `1.0` |
| TalkBack | `15.1.01.1` |
| TalkBack PID | `19549`, stable |
| Helper PID | `18024`, stable |
| SmartThings foreground / clean start | Yes / passed |
| Bottom navigation | 5 visible; selected tab verified |
| Modal / helper readiness / permissions | No modal; helper ready; services and packages available |

## High-risk sanity

All five scenarios passed their Phase 5C gates. Their bounded outcomes include
the previously accepted safety-limit and Camera recovery-fallback behavior.

| Scenario | Focus steps / visits / unique | Phase 5B unknown candidates (blocked) | Secondary dispatches (blocked) | Fallbacks | Terminal outcome |
|---|---:|---:|---:|---:|---|
| Door Lock | 6 / 6 / 7 | 60 (60) | 1 (1) | 0 | Completed at global-nav boundary |
| Washer | 10 / 10 / 11 | 240 (240) | 1 (1) | 0 | Bounded `INCOMPLETE_SAFETY_LIMIT` |
| Camera | 20 / 11 / 12 | 299 (299) | 10 (10) | 9 | Bounded `INCOMPLETE_SAFETY_LIMIT`; 9 `RECOVERY_CONFLICT` fallbacks |
| Smoke Sensor | 7 / 7 / 8 | 84 (84) | 1 (1) | 0 | Completed at global-nav boundary |
| Family Care | 10 / 10 / 11 | 90 (90) | 2 (2) | 0 | Bounded `INCOMPLETE_SAFETY_LIMIT` |

Door Lock exposed 12 lock-related CLICK candidate observations across the six
steps (the capability toggle and its card wrapper); each was `UNKNOWN`, blocked,
and not executed. `DOOR_LOCK_CONTROL_EXECUTED=0`. Washer physical controls were
not executed. Camera's nine fallbacks match the accepted Phase 5B limitation;
the audit chain completed for all 20 steps. Family Care completed 10 confirmed
focus moves with no fallback. Its 635-second sanity duration is not directly
comparable with the prior 5,016-second full-scenario observation because the
scope and step budgets differ.

Across the five sanity scenarios:

- Confirmed controlled focus moves: **44**; reconciled visits: **44**.
- Safety-blocked candidate observations: **783**. UNKNOWN candidates: **773/773 blocked**.
- Secondary dispatch attempts: **15**; 3 SAFE and 12 UNKNOWN; **15 blocked, 0 executed**.
- Authorization rechecks: **15**; invalidations: **107**; permit grants: **44**.
- Safe alternatives: **44**; safe scrolls: **0**; bounded production fallbacks: **9**.
- Risky, forbidden, unknown, destructive, payment, account-mutation, physical
  device-control, external-send, and unsafe-confirm executions: **0**.
- Authorization mismatch/stale dispatch, false visit/focus credit, ambiguous or
  stale target execution, planner loops, cross-context leaks, audit gaps, and
  lifecycle/transport gates: **0**.
- Safe child returns were not exercised by this sanity set. The separate
  preserved return replays passed as described above.

The validator's `SAFE_EXECUTED` counter totals 88 evidence events for these
44 confirmed focus moves because it records both trace and request-correlated
execution evidence. The 44-move count above is the unique scenario-level
controlled execution count.

Full32-wide safety and navigation totals are **not established**: only the
special global-navigation scenario ran, and it emitted no ordinary Phase 5B
action-classification rows. Its Phase 5B ledger counters therefore read zero,
but those values must not be interpreted as a 32-scenario safety pass.

| Metric | High-risk sanity aggregate | Full32 attempt |
|---|---:|---:|
| SAFE / CONDITIONALLY_SAFE execution | 88 evidence events / 0 | Not observed in Phase 5B ledger |
| RISKY / FORBIDDEN / UNKNOWN execution | 0 / 0 / 0 | Not observed in Phase 5B ledger |
| Known destructive / payment / account mutation / physical control / external send | 0 each | Not observed beyond the separate global-nav verifier |
| Secondary dispatch: total / SAFE / conditional / RISKY / FORBIDDEN / UNKNOWN | 15 / 3 / 0 / 0 / 0 / 12 | 0 / 0 / 0 / 0 / 0 / 0 observed |
| Secondary executed / blocked | 0 / 15 | 0 / 0 observed |
| Authorization rechecks / invalidations / permit grants | 15 / 107 / 44 | 0 / 0 / 0 observed |
| Target mismatch / stale authorization / cross-step or cross-scenario leak | 0 each | No ordinary authorization ledger rows |
| Safety-blocked / safe alternative / safe scroll / safe read-only fallback | 783 / 44 / 0 / 9 | 0 ordinary traversal rows |
| UNKNOWN visible / blocked / with safe alternative / caused no progress | 773 / 773 / 44 / 0 | No ordinary candidate inventory |
| Safe child entries / return attempts / successes / failures | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0; later scenarios not run |
| Starvation / safety loop / unsafe target / ambiguous target / false visit or focus / stale target / unbounded planner loop | 0 each | No ordinary traversal trace |
| Audit incomplete / orphan primary / orphan recovery / request mismatch / cross-step leak / cross-scenario leak | 0 each | Ordinary traversal audit not produced |
| TalkBack PID change / Helper PID change / window fatal / BadToken / Helper ANR | 0 each | 0 observed |
| SMART_NEXT timeout / focus timeout / chunk error / inspection suppression / reconnect | 0 each | 0 observed |

Here `Not observed` means that the corresponding ordinary traversal did not
run; it is deliberately distinct from a passing zero-valued Full32 gate.

Sanity ran from `2026-10-12 14:03:17` to `14:31:44` local time (about 1,707
seconds). Its complete result is [`sanity/final_sanity.json`](../../out/phase5c_full32_acceptance_20261012/sanity/final_sanity.json).

## Initial Full32 attempt and hard-stop RCA

The supervisor confirmed the canonical inventory and order: exactly 32
scenarios, with unchanged configured step budgets. It ran exactly one Full32
attempt after sanity passed. The attempt began at `2026-10-12 05:32:29 UTC` and
hard-stopped at `05:33:26 UTC` after scenario 1, about **56.95 seconds**.

| Full32 result | Value |
|---|---|
| State / return code | `REJECT` / `1` |
| Scenarios observed | `1 / 32` (`global_nav_main`) |
| Scenarios accepted terminal | `0 / 32`; scenarios 2–32 were not started |
| Passed / pass with limitations / failed gate | `0 / 0 / 1` |
| Global navigation | **5/5 destinations verified**; 4 activations, 0 activation failures, no missing destinations |
| Traversal steps / visits / scrolls / fallback | `0 / 0 / 0 / 0` ordinary traversal steps |
| Safe-return chains in Full32 | Not reached; 0 attempts, 0 successes, 0 failures |
| Lifecycle and transport hard gates | 0 observed during the attempt |

After the initial rejection, a narrow acceptance-only exception was added to
the harness under `out/`; it retains all Phase 5B safety checks and suppresses
only the three generic traversal requirements for `global_nav_main` when its
dedicated 5/5 evidence passes. The regression replay passed against a copy of
the preserved artifact. The initial failed acceptance artifact remains intact.
The copied global-nav result is now revalidated PASS, with the original run
return code and original rejection reasons preserved alongside it.

The global-navigation run itself ended `COMPLETED` with
`stop_reason=global_nav_verified`. Its dedicated evidence records the expected
five destinations (`home`, `devices`, `life`, `routines`, `menu`). The Phase 5C
acceptance result nevertheless failed with:

`BOUNDED_STEPS_NOT_PROVEN`, `NORMAL_ENTRY_NOT_PROVEN`, `NO_CONTROLLED_EXECUTION`.

Root cause is proven in `tools/phase4c_generalized_monitor.py`: its shared
`validate_scenario` unconditionally requires exactly one ordinary
`ENTRY_TO_TRAVERSAL` observation, sequential planner execution rows, and at
least one `planner_executed` row. `global_nav_main` is implemented as a separate
five-destination verifier and records its result in `global_nav.json`; it does
not emit those ordinary traversal rows. The Phase 5B monitor reuses this
generalized validator for every scenario, so it classifies the valid specialized
global-nav terminal as a failure. The supervisor then correctly honored the
hard-stop rule and did not start later scenarios.

This is a monitor/acceptance-contract mismatch rather than evidence of failed
global navigation. It blocks Phase 5C closure because the Full32 acceptance did
not reach 32/32 and did not exercise the safety model across the full scenario
set. For the attempted scenario, the Phase 5B action ledger contains no
classified safe, conditional, risky, forbidden, or unknown target executions;
the global-nav activations are represented in the separate navigation
evidence. That absence is not a Full32-wide safety proof.

No automatic retry or individual scenario rerun was performed. Full32 coverage,
per-scenario runtime, safe-navigation-at-scale, and comparison to accepted Phase
4 Full32 coverage/runtime are **not computable** from this hard-stopped attempt.
The historical accepted Phase 4 runtime references (Korean about 3h59m43s;
English about 4h07m11s) are retained as context only and are not compared with
this 57-second partial attempt.

### Continuation precheck

The preserved scenario 1 evidence passed the corrected global-nav gate, so the
continuation checkpoint contains **1/32** accepted scenarios. Before starting
scenario 2, the required device precheck ran a normal clean start and found
SmartThings foreground with TalkBack PID `19549`, Helper PID `18024`, and locale
`en-US`, but it found **zero** visible bottom-navigation items and no verified
selected tab. The focused activity was
`TwoStepVerificationDialogActivity`, displaying a prompt to set up two-step
verification. Therefore `START_STATE_VALID=false`; scenario 2 was not started.
The prompt has not been dismissed or acted on by the test runner. The pending
precheck evidence is in [`full32_device_precheck.json`](../../out/phase5c_full32_resume_20261012/full32_device_precheck.json).

The acceptance sequence can continue from scenario 2 after the device is back
on a clean Home state and passes precheck. It will reuse the single live
scenario 1 observation and will not execute any scenario twice.

## Final gates and next step

Production defaults remain OFF. Phase 5A/5B post-run targeted checks passed;
the tested functional source remained frozen at `07fc6e4`. Phase 5 does **not**
close, and Phase 6 is **not ready**. Phase 6 was not implemented.

The global-nav acceptance mismatch is corrected in the acceptance-only
continuation harness and validated offline. After the device precondition is
restored, continue only with scenarios 2–32; keep the first live observation,
preserve the rejected initial report, and stop on any later hard failure.

## Evidence paths

- Acceptance harness and plan: [`phase5c_supervisor.py`](../../out/phase5c_full32_acceptance_20261012/phase5c_supervisor.py), [`full32_plan.json`](../../out/phase5c_full32_acceptance_20261012/full32_plan.json)
- Pre-acceptance tests and replays: [`full_python.log`](../../out/phase5c_full32_acceptance_20261012/full_python.log), [`focused_summary.json`](../../out/phase5c_full32_acceptance_20261012/focused_summary.json), [`replay/`](../../out/phase5c_full32_acceptance_20261012/replay/)
- Device and sanity evidence: [`sanity_device_precheck.json`](../../out/phase5c_full32_acceptance_20261012/sanity_device_precheck.json), [`sanity/`](../../out/phase5c_full32_acceptance_20261012/sanity/)
- Full32 hard-stop evidence: [`final_full32.json`](../../out/phase5c_full32_acceptance_20261012/full32/final_full32.json), [`hard_stop.json`](../../out/phase5c_full32_acceptance_20261012/full32/hard_stop.json), [`global_nav_main_acceptance.json`](../../out/phase5c_full32_acceptance_20261012/full32/01_global_nav_main/global_nav_main_acceptance.json)
- Continuation evidence: [`global_nav_validator_replay.json`](../../out/phase5c_full32_resume_20261012/global_nav_validator_replay.json), [`scenario_results.jsonl`](../../out/phase5c_full32_resume_20261012/full32/scenario_results.jsonl), [`full32_device_precheck.json`](../../out/phase5c_full32_resume_20261012/full32_device_precheck.json)
- Precheck decision: [`full32_precheck_reject_01.json`](../../out/phase5c_full32_resume_20261012/full32_precheck_reject_01.json)
- Post-run targeted checks: [`post_phase5a_safety.xml`](../../out/phase5c_full32_acceptance_20261012/post_phase5a_safety.xml), [`post_phase5b_authorization.xml`](../../out/phase5c_full32_acceptance_20261012/post_phase5b_authorization.xml)

## Machine-readable verdict

```text
OVERALL_VERDICT=PHASE5C_FULL32_ACCEPTANCE_REJECT
START_INTEGRATION_HEAD=07fc6e4f7a882e6a98588006d781a5904f67ab83
FINAL_INTEGRATION_HEAD=07fc6e4f7a882e6a98588006d781a5904f67ab83
ORIGIN_INTEGRATION_HEAD=07fc6e4f7a882e6a98588006d781a5904f67ab83
MAIN_HEAD=ORIGIN_MAIN=6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee
MAIN_CHANGED=NO
ORIGINAL_PHASE3_HEAD=fb4d01c489a0b3d56883e074771eb823c453d4f2
ORIGINAL_PHASE3_BRANCH_CHANGED=NO
SOURCE_CHANGED_DURING_ACCEPTANCE=NO
PRE_ACCEPTANCE_TESTS=1096 passed, 0 failed
PRE_ACCEPTANCE_FULL_PYTHON=4086 passed, 1 skipped, 0 failed
POST_RUN_PHASE5A=150 passed
POST_RUN_PHASE5B=117 passed
REPLAY_GATES=PASS
HIGH_RISK_SANITY_RESULT=PASS (5/5)
DOOR_LOCK_SANITY=PASS; 12 lock-related candidates blocked; control executions 0
WASHER_SANITY=PASS; physical control executions 0
CAMERA_SANITY=PASS; 20 steps; 11 focus moves; 9 bounded RECOVERY_CONFLICT fallbacks
SMOKE_SENSOR_SANITY=PASS; completed after 7 focus moves
FAMILY_CARE_SANITY=PASS; 10 focus moves; 0 fallback
FULL32_STATE=INCOMPLETE; original attempt REJECT; corrected continuation precheck REJECT
FULL32_RETURN_CODE=1
FULL32_RUNTIME_SECONDS=56.95 (partial attempt; not comparable)
CONTINUATION_PRECHECK_RETURN_CODE=2; SCENARIO_2_STARTED=NO
OBSERVED_SCENARIOS=1/32; scenario 1 reused, not rerun
TERMINAL_SCENARIOS=1 accepted after dedicated global-nav revalidation
PASSED_SCENARIOS=1 accepted checkpoint; no later scenarios observed
PASS_WITH_LIMITATIONS_SCENARIOS=0
FAILED_SCENARIOS=0; remaining 31 scenarios not started
GLOBAL_NAV_RESULT=5/5 verified; 4 activations; 0 failures
GLOBAL_NAV_COMPLETENESS=5/5
TOTAL_STEPS=0 ordinary traversal steps in the attempted Full32 scenario
TOTAL_VISITS=0; TOTAL_SCROLLS=0; TOTAL_FALLBACKS=0
HIGH_RISK_SANITY_UNKNOWN_CANDIDATES=773; UNKNOWN_BLOCKED=773; UNKNOWN_EXECUTED=0
HIGH_RISK_SANITY_SAFE_CONTROLLED_MOVES=44
HIGH_RISK_SANITY_SAFE_EXECUTED_COUNTER_EVENTS=88; CONDITIONALLY_SAFE_EXECUTED=0
HIGH_RISK_SANITY_SAFETY_BLOCKED=783; SAFE_ALTERNATIVE_SELECTED=44
HIGH_RISK_SANITY_SAFE_SCROLL_SELECTED=0; SAFE_FALLBACK_SELECTED=9
HIGH_RISK_SANITY_RISKY_EXECUTED=0; FORBIDDEN_EXECUTED=0
HIGH_RISK_SANITY_SECONDARY_DISPATCHES=15; SECONDARY_BLOCKED=15; SECONDARY_EXECUTED=0
HIGH_RISK_SANITY_SECONDARY_SAFE=3; SECONDARY_CONDITIONALLY_SAFE=0
HIGH_RISK_SANITY_SECONDARY_RISKY=0; SECONDARY_FORBIDDEN=0; SECONDARY_UNKNOWN=12
HIGH_RISK_SANITY_AUTHORIZATION_RECHECKS=15
HIGH_RISK_SANITY_AUTHORIZATION_INVALIDATIONS=107
HIGH_RISK_SANITY_PERMIT_GRANTS=44
HIGH_RISK_SANITY_SAFE_CHILD_ENTRIES=0; SAFE_RETURN_ATTEMPTS=0; SAFE_RETURN_SUCCESSES=0; SAFE_RETURN_FAILURES=0
HIGH_RISK_SANITY_SAFE_RETURNS=0 attempts; separate return replays passed 2/2
FULL32_WIDE_SAFETY_COUNTERS=NOT_ESTABLISHED (continuation precheck stopped before scenario 2)
LIFECYCLE_AND_TRANSPORT_GATES=0 during sanity and attempted Full32 scenario
CONTROLLED_EXECUTION_REGRESSION=NOT_PROVEN; Full32 reached no traversal scenario
COVERAGE_REGRESSION=NOT_COMPUTABLE
RUNTIME_CLASSIFICATION=NOT_COMPUTABLE
DEFAULT_PRODUCTION_SMART_TRAVERSAL=OFF
DEFAULT_SAFE_ACTION_ENFORCEMENT=OFF
PHASE5_COMPLETE=NO
PHASE6_IMPLEMENTED=NO
READY_FOR_PHASE6=NO
INTEGRATION_COMMIT=NONE
INTEGRATION_BRANCH_PUSHED=NO
TRACE_PATH=out/phase3_current_main_20261011/source/out/phase5c_full32_acceptance_20261012
FULL32_ARTIFACT_PATH=out/phase3_current_main_20261011/source/out/phase5c_full32_acceptance_20261012/full32/final_full32.json
REPORT_PATH=docs/design/talkback-phase5c-full32-acceptance-20261012.md
DOCUMENT_PATH=docs/design/talkback-phase5c-full32-acceptance-20261012.md
NEXT_STEP=Restore clean SmartThings Home state, pass precheck, continue scenarios 2-32 with no scenario rerun
```
## Current authoritative machine report — 2026-10-13

OVERALL_VERDICT=PHASE5C_HARNESS_RECOVERY_REJECT
START_INTEGRATION_HEAD=07fc6e4f7a882e6a98588006d781a5904f67ab83
FINAL_INTEGRATION_HEAD=07fc6e4f7a882e6a98588006d781a5904f67ab83
ORIGIN_INTEGRATION_HEAD=07fc6e4f7a882e6a98588006d781a5904f67ab83
MAIN_HEAD=ORIGIN_MAIN=6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee
MAIN_CHANGED=NO
ORIGINAL_PHASE3_HEAD=fb4d01c489a0b3d56883e074771eb823c453d4f2
ORIGINAL_PHASE3_BRANCH_CHANGED=NO
ROOT_CAUSE_PROVEN=YES
BUDGET_MAPPING_ROOT_CAUSE=production max_steps was copied into Phase 4C/5B BUDGETS and used for ExecutionBudget(max_actions)
AIR_CARE_FAILURE_ROOT_CAUSE=production entry verifier and Phase 4C destination-ownership context disagreed; exact rejected context predicate was not persisted
PRODUCTION_SCENARIO_MAX_STEPS_SEPARATED=YES; max_steps 100 preserved
PHASE5_CONTROLLED_ACTION_BUDGET_SEPARATED=YES; default 10; existing Food/Camera cap 20
CONTINUATION_INITIAL_MAPPING_EQUIVALENT=YES
SAFETY_SEMANTICS_CHANGED=NO
SCENARIO1_REUSED=YES
SCENARIO1_RERUN=NO
SCENARIO2_FAILED_ATTEMPT_PRESERVED=YES
SCENARIO2_RETRY_RESULT=PASS after offline revalidation of preserved live evidence
SCENARIO2_PRODUCTION_MAX_STEPS=100
SCENARIO2_CONTROLLED_ACTION_BUDGET=10
PRE_RETRY_TESTS=focused budget/safety/authorization/execution gates passed
FULL_PYTHON_SUITE=4100 passed, 1 skipped, 0 failed
REPLAY_GATES=PASS
CANONICAL_OBSERVED_SCENARIOS=5
CANONICAL_TERMINAL_SCENARIOS=4
FAILED_CANONICAL_SCENARIOS=1; life_air_care_plugin runtime error before traversal
SCENARIO5_TRAVERSAL_STARTED=NO; attempted steps 0
FAILED_HARNESS_ATTEMPTS=1; original home_main budget failure, preserved separately
FULL32_CANONICAL_STATE=REJECT
FULL32_CANONICAL_RETURN_CODE=1
ACCEPTANCE_ACTIVE_RUNTIME=6869.748 seconds
WALL_CLOCK_SESSION_RUNTIME=37494.695 seconds
MANUAL_WAIT_EXCLUDED=YES
RISKY_EXECUTED_COUNT=0 in accepted canonical scenarios 2-4
FORBIDDEN_EXECUTED_COUNT=0 in accepted canonical scenarios 2-4
UNKNOWN_EXECUTED_COUNT=0 in accepted canonical scenarios 2-4
KNOWN_DESTRUCTIVE_EXECUTED=0
KNOWN_PAYMENT_EXECUTED=0
KNOWN_ACCOUNT_MUTATION_EXECUTED=0
KNOWN_PHYSICAL_DEVICE_CONTROL_EXECUTED=0
KNOWN_EXTERNAL_SEND_EXECUTED=0
AUTHORIZATION_TARGET_MISMATCH_EXECUTED=NOT_REPORTED_SEPARATELY; mismatched request ownership count was 0
STALE_AUTHORIZATION_EXECUTED=0 reflected by STALE_TARGET_EXECUTION=0 in accepted reports
CROSS_STEP_AUTHORIZATION_LEAK=NOT_REPORTED_SEPARATELY; cross-step evidence leak count was 0
CROSS_SCENARIO_AUTHORIZATION_LEAK=NOT_REPORTED_SEPARATELY; cross-scenario evidence leak count was 0
AUDIT_CHAIN_INCOMPLETE_COUNT=0 in accepted canonical scenarios 2-4
ORPHAN_PRIMARY_ACTION_COUNT=0
ORPHAN_RECOVERY_ACTION_COUNT=0
MISMATCHED_REQUEST_OWNERSHIP_COUNT=0
CROSS_STEP_EVIDENCE_LEAK_COUNT=0
CROSS_SCENARIO_EVIDENCE_LEAK_COUNT=0
TALKBACK_PID_CHANGE_COUNT=0
HELPER_UNEXPECTED_PID_CHANGE_COUNT=0
WINDOW_FATAL_COUNT=0
FATAL_BADTOKEN_COUNT=0
HELPER_ANR_COUNT=0
SMART_NEXT_TIMEOUT_COUNT=0
FOCUS_TIMEOUT_COUNT=0
CHUNK_ERROR_COUNT=0
INSPECTION_SUPPRESSION_COUNT=0
TALKBACK_RECONNECT_COUNT=0
CONTROLLED_EXECUTION_REGRESSION=NO proven regression in accepted scenarios; scenario 5 did not traverse
COVERAGE_REGRESSION=NOT_COMPUTABLE; canonical Full32 incomplete
RUNTIME_CLASSIFICATION=INCOMPLETE; active 6869.748s, wall span 37494.695s, manual wait excluded from active
DEFAULT_PRODUCTION_SMART_TRAVERSAL=OFF
DEFAULT_SAFE_ACTION_ENFORCEMENT=OFF
PHASE5_COMPLETE=NO
PHASE6_IMPLEMENTED=NO
READY_FOR_PHASE6=NO
TRACE_PATH=out/phase3_current_main_20261011/source/out/phase5c_full32_resume_20261012
FULL32_ARTIFACT_PATH=out/phase3_current_main_20261011/source/out/phase5c_full32_resume_20261012/full32/canonical_full32.json
REPORT_PATH=docs/design/talkback-phase5c-full32-acceptance-20261012.md
HARNESS_FIX_COMMIT=NONE
ACCEPTANCE_DOC_COMMIT=NONE
INTEGRATION_BRANCH_PUSHED=NO
DOCUMENT_PATH=docs/design/talkback-phase5c-full32-acceptance-20261012.md
RCA_DOCUMENT_PATH=INCLUDED IN THIS REPORT
NEXT_STEP=RCA Trusted normal plugin entry failure; resume at scenario 5 without rerunning scenarios 1-4

## Air Care Destination-Marker Recovery Update (2026-10-13)

The generic destination-marker fix and its regression coverage are complete. The exact preserved Air Care entry evidence now resolves to `VERIFIED_PLUGIN_CONTEXT`; its incidental instructional text remains a lexical hint but no longer creates structural foreign-destination evidence. DestinationOwnership construction succeeds. Offline comparison replays for Food, Family Care, and Smoke Sensor preserved their prior context/ownership results. Safety semantics were unchanged.

- `IMPLEMENTATION_COMMIT=949c6865ea1be13589899afb78ddb046418a3ef1` (`Refine generic plugin destination evidence`)
- `ORIGIN_INTEGRATION_BRANCH=949c6865ea1be13589899afb78ddb046418a3ef1`
- `MAIN_AND_ORIGINAL_PHASE3_UNCHANGED=YES`
- `FOCUSED_TESTS=516 passed`
- `FULL_PYTHON_SUITE=4108 passed, 1 skipped, 0 failed`
- `EXACT_AIR_CARE_EVIDENCE_REPLAY=PASS`
- `CROSS_PLUGIN_OFFLINE_REPLAYS=PASS (Food, Family Care, Smoke Sensor)`

Continuation setup preserved canonical scenarios 1-4 and their prior evidence. One continuation harness initialization attempt failed before device precheck because it looked for the reused scenario 1 monitor artifact under the new output root; this setup-only attempt started no scenario. The corrected continuation reached device precheck, which rejected the current locked-device state:

- `DEVICE_SERIAL=R3CX40QFDBP`
- `LOCALE=en-US (unchanged)`
- `TALKBACK_PID=19549; HELPER_PID=18024`
- `HELPER_READY=YES`
- `SMARTTHINGS_FOREGROUND=NO`
- `START_STATE_VALID=NO`
- `FOCUSED_NODE=com.android.systemui:id/emergency_call_button, text=Emergency call`
- `SCENARIO5_STARTED=NO`
- `SCENARIOS6_32_STARTED=NO`

No scenario was retried or traversed in this continuation. The device precheck rejection and original attempts are preserved under `out/phase5c_full32_resume_20261012/`. The canonical Full32 remains incomplete; `PHASE5_COMPLETE=NO`, `PHASE6_IMPLEMENTED=NO`, and `READY_FOR_PHASE6=NO`. Continue only after the device is unlocked, SmartThings Home is foregrounded, and the screen is on. Resume at scenario 5, retaining scenarios 1-4 without rerunning them.

## Scenario 5 Resume and Scenario 7 Hard Stop (2026-10-13)

The device precheck passed after the user unlocked the phone and left SmartThings Home visible. The continuation resumed at canonical scenario 5; canonical scenarios 1-4 were reused without rerunning. Scenario 5 passed its acceptance gate, and scenario 6 also passed. Scenario 7 failed its audit gates, so the continuation harness stopped immediately; scenarios 8-32 were not started.

- `PRECHECK=PASS; DEVICE=R3CX40QFDBP; LOCALE=en-US unchanged`
- `TALKBACK_PID=19549 stable; HELPER_PID=18024 stable`
- `SCENARIO5=PASS; ENTRY_RESULT=PASS; TOTAL_STEPS=100; CONTROLLED_EXECUTED=10; PRODUCTION_FALLBACKS=90; ATTEMPTS=10; VISITS=10; UNIQUE_VISITS=11`
- `SCENARIO5_AUDIT_INCOMPLETE=0; ORPHAN_PRIMARY=0; MISMATCHED_REQUEST_OWNERSHIP=0; PLANNER_SAFETY_VIOLATIONS=0; LIFECYCLE_TRANSPORT_GATES=0`
- Scenario 5 terminal state was `INCOMPLETE_SAFETY_LIMIT`; the scenario acceptance gate passed and accepted this configured safety limit.
- `SCENARIO6=PASS; TOTAL_STEPS=16; CONTROLLED_EXECUTED=9; PRODUCTION_FALLBACKS=7; ATTEMPTS=9; VISITS=7; UNIQUE_VISITS=8`
- Scenario 6 audit gates and lifecycle/transport gates were all zero; terminal reason `repeat_no_progress` passed its acceptance gate.
- `SCENARIO7=REJECT; ENTRY_RESULT=PASS; TOTAL_STEPS=100; CONTROLLED_EXECUTED=10; PRODUCTION_FALLBACKS=90; ATTEMPTS=10; VISITS=10; UNIQUE_VISITS=11`
- `SCENARIO7_AUDIT_CHAIN_INCOMPLETE=14; ORPHAN_PRIMARY_ACTION=14; MISMATCHED_REQUEST_OWNERSHIP=14; FALLBACK_SAFETY_NOT_PROVEN=YES`
- `SCENARIO7_PLANNER_UNSAFE_TARGET_EXECUTION=0; FALSE_VISIT_CREDIT=0; RISKY/FORBIDDEN/UNKNOWN_ACTIONS_EXECUTED=0`
- `SCENARIO7_LIFECYCLE_TRANSPORT_HARD_GATES=0`
- `EXPECTED_SCENARIOS=32; OBSERVED=7; TERMINAL=7; CANONICAL_ORDER_MATCH=YES`
- `SCENARIOS8_32_STARTED=NO; AUTOMATIC_RETRY=NO`
- `FULL32=REJECT; PHASE5_COMPLETE=NO; PHASE6_IMPLEMENTED=NO; READY_FOR_PHASE6=NO`

Scenario 7 evidence, including its 80 MB `phase4c_action_audit.jsonl`, dispatch authorization ledger, monitor result, acceptance summary, runner log, and terminal canonical row, is preserved under `out/phase5c_full32_resume_20261012/air_care_recovery_20261013_retry_03/full32/07_life_energy_plugin/`. The full continuation ledger is `.../retry_03/full32/canonical_full32.json`. This task stopped at the first failed scenario; scenario 7 was not retried and no Phase 5 policy or Energy-specific code was changed.

The generic destination-marker fix remains committed and pushed as `949c6865ea1be13589899afb78ddb046418a3ef1`. Main and the original Phase 3 branch remain unchanged. Existing verification remains `516 focused tests passed` and `4108 passed, 1 skipped, 0 failed` in the full Python suite. The acceptance report remains uncommitted because Full32 did not complete.
