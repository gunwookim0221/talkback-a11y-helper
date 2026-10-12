# Phase 5B Safe Navigation Execution and Recovery

Requested checkpoint date: 2026-10-11. Implementation/validation continued on
2026-10-12 (Asia/Seoul).

Branch: `integration/phase3-current-main`. Baseline:
`6929ba1aa8a9ccb7cd1213a2c243dab76d17cee4`.

## Scope and defaults

This is a bounded first execution layer over accepted Phase 5A. Normal
production traversal and safe-action enforcement remain OFF. Explicit
`TB_PHASE5B_CONTROLLED=1` and Phase 5A `enforce` mode are required by the new
smoke entry point. Phase 5C and a Full32 are outside this implementation.

The existing Phase 5A classifier, eligibility policy, lexicon and safety classes
are unchanged. Phase 4 candidate/focus identities, reconciliation, attempts,
visits, ranking, scroll, context, ownership, modal and termination algorithms
are unchanged. Existing harness behavior is preserved when the new keyword is
false. The new runner selects its own representative scenarios/bounds.

## Execution boundaries

The traversal path uses existing safety filtering and fresh Phase 4 gates.
Only SAFE and sufficiently proven CONDITIONALLY_SAFE actions may dispatch.
Risky/forbidden/unknown activating actions remain observable and blocked.
Focusing an Unlock or Power button does not activate it: focus and activation
retain different action identities and classifications.

`SafeNavigationSession.firewall` covers the existing client command path,
direct AdbDevice command path, and direct touch helper throughout the production
main loop. Unapproved clicks, taps, editable input, Home, application launch,
force-stop, generic Back, and unknown Helper commands are denied before native
dispatch. Passive observation, strict focus and known read-only focus APIs stay
available. Unbound NEXT/PREV/SMART_NEXT are blocked consistently with Phase 5A's
UNKNOWN movement classification. A click permit requires the exact expected request and is consumed
once. A Back permit authorizes one Android Back only. Hooks are restored on
success, exception or stop; normal entry/setup occurs before this scope.
The client command path forwards to AdbDevice through AdbExecutor. One exact
command/device forwarding receipt admits that nested boundary once, so a single
dispatch consumes one permit. Changed or repeated nested commands remain denied.

The collector proxy sets `move=False`, records exact GET_FOCUS request/ACKs,
and takes a fresh strict before-read focus. It does not reinterpret the UNKNOWN
unbound FOCUS_NEXT inventory action or claim movement from the read receipt.
However, live validation proved that the enclosing production collection phase
can subsequently run representative focus alignment during capture/local-tab
processing. The Phase 5B command-name firewall did not authorize that secondary
target through Phase 4 and Phase 5A gates. End-to-end fallback safety is therefore
NOT accepted. This is the blocking defect described in the final result below.

Verified scroll requires the exact current axis-v1 container/path/bounds and
forward capability. Adjustment controls are denied. Existing verified-scroll
refresh rebuilds hierarchy/candidates after every scroll, including failures.
Safety reclassification happens again before the next planner action.

## Blocked targets, alternatives and accounting

Traversal retains the original immutable Phase 4 history projection. Safety
filtering removes ineligible targets from the allowed domain without changing
relative ranking. The planner may use the next safe focus target, verified
scroll, or safe production fallback. A blocked target does not create a visit
or attempted action and does not introduce a new stop reason.

The new blocked observation record is scoped by the existing production target
identity, action type, destination/run ownership, structural state and semantic
substate. It survives diagnostic observation-ID churn and mutable text values.
Meaningful structural/context changes create another scope. Repeated blocked
observations are counted; they never become execution attempts.

The classifier, safety session and navigation lease grant zero visits. Native
targeted focus preparation uses the existing attempt ledger and actual-focus
preview; production reconciliation continues to own production visits. The
navigation proof copies outcomes and never commits a synthetic visit.

## Bounded child entry and return

`config/safe_navigation_contracts.json` contains an explicit reviewed application
overflow-menu effect. It is selected by observed package/resource identity and
EN/KO control semantics, not a scenario name. The default rollout flag is false.
The first layer supports at most one reviewed menu roundtrip per scenario.
Unknown details, settings, device controls and generic clickable cards are not
certified as read-only by a missing risk word.

A separate navigation task projects only the reviewed toolbar target into a
Phase 4 planner domain. Content-only production allowlists intentionally omit
toolbar chrome and remain intact for traversal. The navigation task uses the
same ranking and real attempt/visit history. Fresh Phase 4 target/focus, scope,
geometry, lifecycle, transport, recovery and current-state gates must pass;
then the existing controlled-focus adapter prepares the exact target.

Before the single click, actual accessibility focus, unchanged target geometry
and ownership/structure are checked again. Entry is a Phase 5A NAVIGATE action
with a configured read-only effect and an independently bounded return path.
The click has one exact Helper request/ACK; a missing/stale ACK is not entry
confirmation. No retrying click API is used.

The lease captures parent destination/state, entry action ID, navigation epoch,
expected return scope, actual child destination and child structural state.
The observed child must remain within the app/component, change the hierarchy,
and expose no editing/checking/adjustment control for this reviewed menu effect.
Android short component names expand only with the observed package. At most
three passive observations allow the menu's accessibility-focus event to settle;
wrong ownership or mutation evidence stops immediately. No entry is retried.

Android Back is represented as NAVIGATE in the RETURN direction under this
specific read-only child lease, with BACK as the transport. Phase 5A's generic
unproven BACK classification remains unchanged. A current child target supplies
the return action identity; the disappeared parent node does not supply fresh
target evidence. A second immediate child observation checks for stale scope
before the single Back. Two consecutive parent observations must prove matching
destination, structure, no overlay, and revalidated context before return is
successful. Up to four bounded read-only captures may be used to obtain that
pair when a transient Helper-flat observation lacks selected-tab or complete
hierarchy evidence. A missing field is inconclusive; a known package, activity,
run, entry, tab, modal, or Phase 3 context contradiction stops confirmation.
No entry or Back action is retried.

An empty resource ID is encoded as a paired `""` token by the ADB shell
argument builder. The Phase 5B native firewall decodes that token back to the
empty string before comparing it with the one-use permit, preserving exact
target identity for legitimate anonymous nodes without granting broader
authority.
The current return identity can come from an existing CLICK candidate when the
actual accessibility-focused menu row has `focusable=false`. That row is never
clicked by return; it identifies the lease's current observed child. No focus
flags or production discovery/reconciliation semantics are promoted or changed.

Generic OK/Confirm is never a return mechanism. Known cancel/close semantics
retain Phase 5A's conditional non-committing policy; no arbitrary dialog button
is activated by production recovery. This first reviewed lease does not certify
all cancel, close, tab or detail paths. Additional effect/return contracts must
meet the same prerequisites rather than expanding a lexical allowlist.

## Evidence and failure policy

Existing Phase 4 step-action chains include the accepted Phase 5A safety
sidecar with selected target/class/confidence/signals/conditions/policy/gate and
copied final outcome. Separate immutable JSONL records capture:

- `phase5b_blocked_actions`: observed target, activating/focus action, safety
  class/block reason, and `executed=false`.
- `phase5b_transport_blocks`: rejected native command before dispatch.
- `phase5b_fallback_safety`: fallback classification and policy.
- `phase5b_navigation_chains`: parent/child/return ownership, exact entry
  request/ACK, focus preparation, return conditions, current observations,
  native entry/return journal events and integrity hash.
- `phase5b_session_summary`: blocked scopes/repeats and transport blocks.
- `phase5b_failure`: first navigation mismatch and its current evidence.

The validator reuses Phase 4 target, focus, visit, ownership and audit gates.
It additionally checks selected safety eligibility, declared fallback safety,
navigation policy/gate/hash/native linkage, and native ACTION_SENT command names.
Its whitelist rejected unapproved clicks but missed an extra TARGET_FOCUS_COMMIT
whose target was not in the safety-filtered planner population. Independent
exact-request target classification found and overrides that false pass.
The existing correlated monitor checks lifecycle/transport with Helper ownership
and exact request IDs; JSON `false` fields are not restart events.

On a meaningful navigation mismatch the runner exits outside ordinary scenario
crash/retry handling. The stage stops; no subsequent stage starts on failure.
Artifacts are preserved for RCA before any explicitly justified recovery.

## Validation status

### Preserved Stage A failures and recovery

The first Stage A stopped before controlled traversal: a root-tab entry proof
was routed to the plugin-only destination owner. Root and plugin ownership are
now selected separately in the explicit Phase 5B adapter. The existing owner
and Phase 3 resolver remain unchanged.

The first recovery stopped after five successful Home focus steps. The reviewed
menu click was denied before native dispatch because both client and AdbDevice
guards consumed the same single-use permit. The forwarding receipt above fixes
that routing defect, with real AdbExecutor regression tests for click and Back,
duplicate forwarding, changed request and wrong device. No Helper ACK or click
dispatch occurred for that blocked request. All lifecycle/transport gates were
zero. Stage B/C were not started in either failed attempt; their artifacts and
RCA manifests are retained. Any subsequent recovery uses a fresh directory after
focused/full tests and replay checks.

The second recovery executed the reviewed menu opening once with an exact
successful ACK, then stopped at child verification. The popup reported the same
Android activity using its short class name. Its initial strict focus read also
preceded the menu focus event. Two later read-only RCA captures proved coherent
focus on a clickable, `focusable=false` menu row represented by the existing
CLICK inventory. Component normalization, bounded passive settling and lookup
of that current child candidate now belong to the new lease only. No Back or
menu-item activation occurred in the rejected recovery. Its artifacts remain
intact, with lifecycle/transport gates zero and Stage B/C unexecuted.

### Final result: REJECT

`OVERALL_VERDICT=PHASE5B_SAFE_NAVIGATION_REJECT`.
`PHASE5B_COMPLETE=NO`. `READY_FOR_PHASE5C=NO`.

- Python: **4049 passed, 1 skipped, 0 failed**; Phase 5B focused: **85 passed**.
- Phase 5A 150, Phase 3 58, production 442 and Phase 4 306 focused tests passed.
  Helper source is unchanged; its previously accepted 408 passes are retained.
- Historical/accepted/Phase 4A/4B/4C, Food audit, Family recovery, Camera modal
  and Phase 5A shadow replays passed. Shadow preserved 116/116 prior controlled
  actions across 4,836 candidate observations; 97 audit chains remained complete.
- Final Stage A recovery: Home 10 completed traces, Devices 4 completed traces;
  Devices step 5 was in flight when the runner was terminated. Life was not run.
  Stage B and Stage C were not run. No retry followed the hard failure.
- One actual reviewed menu child entry and one successful Back return were
  proved with exact request/ACK, native journal, ownership/context and chain hash.
- Completed trace scope: 14 steps, 13 main SAFE controlled actions, 2 conditional
  entry/return activations, and **1 extra UNKNOWN focus action**. Live safe scroll
  was not reached. No physical/destructive/account/payment/external-send action
  was observed; the physical-device stage was not validated.
- TalkBack and Helper PIDs stayed 19549 and 18024; all monitored lifecycle and
  transport gates were zero. This does not satisfy the separate safety gate.

At Home step 10, after the read-only collector proxy returned, the original
collection phase invoked `maybe_capture_focus_crop`/local-tab representative
alignment. `focus_realign_logic` dispatched TARGET_FOCUS_COMMIT request
`895773aeb784427eade19957520d14f9` for `device_name` TextView bounds
`78,635,309,683`. The raw node had `focusable=false`, `clickable=false` and was
absent from the planner candidate population. The unchanged Phase 5A classifier
returns `UNKNOWN / FOCUS_CAPABILITY_UNPROVEN` for that native FOCUS target. Its
exact successful Helper ACK and actual accessibility focus prove execution.

Production reconciliation recorded a real focus movement, so its visit is not
fabricated and its contracts remain unchanged. The defect is in Phase 5B's
secondary-action authorization and fallback boundary. The old Home per-scenario
validator passed because it whitelisted the strict focus command name; the
independent native target audit correctly rejects that result. Completed-row
audit assertions passed, while the safety-policy linkage missed this action.
The interrupted Devices step has only partial audit evidence.

Required recovery: every native focus dispatch needs current target/policy and
Phase 4 authorization, including post-collector representative alignment. A
passive fallback must suppress or gate that downstream behavior. Additional
native requests must be accounted for and rejected when not authorized. Do not
promote `focusable=false` or weaken UNKNOWN solely to pass acceptance.

All valid local implementation and rejected evidence are preserved. No commit,
push, main merge, Phase 5C implementation or global enablement was performed.
Both production defaults remain OFF. The trace directory contains the complete
uppercase report, stage records, tests, replay results and four RCA manifests:
`out/phase3_current_main_20261011/phase5b_safe_navigation_20261012`.

## Secondary dispatch authorization recovery (2026-10-12)

The retained Home step 10 Helper journal proves the blocked-path defect: after
the production fallback collector was made passive, the enclosing crop and
representative-focus recovery still called `target_focus_commit`. The request
for `com.samsung.android.oneconnect:id/device_name`, a `TextView` at
`78,635,309,683`, succeeded and moved accessibility focus. That node was not a
planner candidate and had `focusable=false`, so Phase 5A classifies this FOCUS
action as `UNKNOWN / FOCUS_CAPABILITY_UNPROVEN`. The earlier firewall admitted
it by command name alone, and the earlier monitor treated the command as
implicitly safe. This is a Phase 5B fallback-boundary authorization defect;
production focus reconciliation and visit authority remain unchanged.

The recovery scopes an authorization to one target-specific native focus
dispatch. A permit records the exact resource ID, class and normalized bounds,
FOCUS action, Phase 5A classification and policy result, Phase 4 gate result,
destination ownership, state ID, structural observation epoch and one native
request. The native ADB dispatch rechecks the target payload, active epoch,
Phase 5A policy and gate before permitting the command. The permit is consumed
once and expires when its dispatch scope ends. New observations and fallback,
recovery, retargeting or rebuilt-state boundaries advance the authorization
epoch and invalidate a live permit.

Post-collector alignment has no exact permit of its own. Its target is resolved
against the current observation and classified for the audit; if no current
Phase 4-gated target-specific permit exists, the Helper request is blocked
before transport. `focusable=false` remains UNKNOWN. Planner-selected safe
alternatives and verified safe scroll continue through their existing gates.
No alignment exception, candidate identity change, visit authority or global
default enablement is introduced.

The Phase 5B monitor independently links every Helper focus request to the
authorization record using the exact request ID and checks its target against
the request journal. A local ACTION_SENT intent with a matching explicit block
and no Helper execution-start event is recorded as blocked, not executed. A
Helper execution-start event without an exact authorized record is a hard
safety failure. The preserved UNKNOWN request is the required old-behavior
replay fixture; its recovery test must prove that no command reaches the
Helper. Full test, saved replay and staged live retry results are recorded in
the 2026-10-12 RCA and final acceptance report after those gates complete.

## Bounds-only recovery audit correction (2026-10-12)

The next live retry passed Stage A and stopped at Food step 9. The primary
focus request was correlated; 14 later bounds-only recovery attempts were all
blocked before Helper by the Phase 5B UNKNOWN policy. The audit had reported
one orphan recovery action because `focus_in_bounds()` wrote `ACTION_SENT`
before the native firewall blocked each request. There were no Helper ACKs or
recovery results for those blocked requests, and no UNKNOWN/RISKY/FORBIDDEN
execution occurred.

The generic correction adds a bounds-focus preflight at the existing Phase 5B
firewall. Bounds-only requests cannot prove exact target identity and remain
blocked. The preflight rejects them before `ACTION_SENT`; the recovery executor
closes the rejected transaction without a post-action focus observation or
recovery visit attribution. Exact target focus retains its one-use target
permit and native boundary recheck. The replay manifest and regression tests
are in `talkback-phase5b-secondary-authorization-rca-20261012.md`.

Secondary `CLICK_TARGET` activation outside a planner step now uses the same
fail-closed boundary. The Phase 5B opt-in preflight resolves a unique current
hierarchy target and records its action classification, but denies dispatch
when the action has no exact Phase 4 gate and current Phase 5 permit. A blocked
overlay expansion is recorded once and skipped so the main production
traversal can continue to a separately authorized safe target or scroll.
Unmediated commands still stop at the native ADB firewall. UNKNOWN remains
blocked; this path does not inherit the primary focus authorization.

## Final secondary-authorization staged retry (2026-10-12)

The final retry completed both live preflight probes and all three stages. Home
and Devices probes completed 10 steps each. Stage A passed Home, Devices, and
Life at 10 steps each; Stage B passed Food at 20 and Family Care at 10; Stage C
passed Smoke Sensor (7), Door Lock (6), TV (10), Washer (10), and Camera (20).
There was no hard stop. The independent saved-artifact revalidation passed all
12 scenario rows (two probes plus ten Stage A/B/C rows).

For Stage A/B/C, the authorization ledger records 36 secondary dispatch
attempts: 3 SAFE and 33 UNKNOWN, with no conditionally safe, risky, or forbidden
targets. All 36 were denied before Helper execution; zero secondary focus
actions executed. All 36 attempts were rechecked and denied. The 35 secondary
focus retargets were separately counted from the one secondary overlay-click
preflight. Across the staged rows there were 230 authorization invalidations,
100 permit grants, and 10 production fallbacks. Three safe child entries had
three successful returns. Including both preflight probes, secondary attempts
were 39 (4 SAFE, 35 UNKNOWN), and five child entries returned successfully.
The staged rows also selected 103 safe alternatives, six verified safe scrolls,
and ten read-only production fallbacks; UNKNOWN candidates caused zero
no-progress stops.

Unknown, risky, forbidden, destructive, payment, account-mutation,
physical-device-control, and external-send execution counts were zero. Phase 4
unsafe-target, ambiguous-target, false-visit, false-focus, stale-target,
unbounded-loop, and cross-context gates were zero. Every live monitor completed
its scenario with stable TalkBack and Helper PIDs, unchanged `en-US` locale, and
zero lifecycle/transport hits. The staged retry therefore proves safe denial
and continued progress; fresh-authorized SAFE secondary dispatch is exercised
by the Phase 5B test matrix because no live secondary had an independent Phase
4 action gate.

Camera is the remaining coverage limitation: its 20-step bound completed with
11 controlled focus executions and nine production fallbacks caused by
`RECOVERY_CONFLICT`. The fallback path remained bounded and audit-complete, and
did not execute an unsafe action. This is a safe traversal-coverage limitation,
not an authorization or lifecycle failure.

Final verdict: `PHASE5B_SECONDARY_AUTH_RECOVERY_PASS_WITH_LIMITATIONS`;
`PHASE5B_COMPLETE=YES`; `READY_FOR_PHASE5C=YES`. Phase 5C is not implemented.
Both safe-action policy mode and safe-navigation defaults remain OFF. The full
Python suite passed with 4,086 passed and one skipped. Replay evidence,
revalidated monitor metrics, and per-scenario live evidence are under
`../phase5b_secondary_auth_recovery_20261012/quality_after_secondary_activation_fix`.
