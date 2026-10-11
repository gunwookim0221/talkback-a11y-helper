# Phase 4A shadow Smart Traversal planner

## Source and boundary

Starting integration: `c8f296a51a2a500858a4c9b1780baea71a038a37`.
Production main/origin/main: `6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`.
Original Phase 3: `fb4d01c489a0b3d56883e074771eb823c453d4f2`.

`tb_runner.phase4a_planner.plan_shadow` is a pure function. It takes an immutable
Phase 3 discovery snapshot, context status, and a projection of production
history. It returns canonical JSON; it has no device client, executor, clock,
random generator, or mutable attempt/visit ledger. Recommendations cannot
execute, reorder traversal, change entry, max_steps, termination, or visits.
Phase 4B and Phase 5 are not implemented.

The explicit smoke harness wraps existing production observation/persistence
points only inside its process. It forwards the original arguments and return
values, never passes a recommendation to production, and restores all wrappers
and argv in `finally`. Diagnostic captures use a separate client. They add
observation latency; this smoke is not a production performance benchmark.
Normal production imports and execution do not install these wrappers.

## Existing production contracts reused

| Responsibility | Existing functions / sources |
| --- | --- |
| Inventory | `collection_flow._register_focusable_inventory_node`, `_collect_step_candidate_priority_groups`, `local_tab_logic._current_valid_content_candidates`, `discovery_candidates.build_discovery_snapshot` |
| Eligibility | `completeness.candidate`, `completeness.eligibility`, current discovery candidate flags/presence, production planner candidate pool |
| Identity | `local_tab_logic._content_candidate_instance_id`, `traversal_reliability.instance_id`, `normalized_bounds` |
| Current focus | `traversal_reliability.focus_instance`, discovery `strict_current_focus` |
| Attempts | `TargetAttemptLedger.begin/finish/entries`, `ContentTerminal.target_attempted_ids/target_attempt_statuses`, `ContentTerminal.observe(target_attempt=...)` |
| Visits | `focus_reconciliation.reconcile_focus`, `TraversalMetrics.observe_focus/observe_reconciliation`, `ContentTerminal.observe`, existing `visited` membership |
| Focus actions | `collection_flow._apply_step_collection_phase`, `_confirm_focus_target`, `_maybe_realign_focus_to_representative`; `A11yAdbClient.move_focus_smart/target_focus_commit/focus_in_bounds` |
| Scroll | `scroll_reliability.capability/capture/verified_scroll/transition`, `ContentTerminal.scroll_opportunity`, `collection_flow._apply_content_terminal_phase` |
| Starvation | `local_tab_logic._prioritize_unattempted_active_unseen_candidates` |
| No progress / termination | `ContentTerminal.decision`, `traversal_reliability.termination_status`, `collection_flow._main_loop_phase` |

No existing production source or Helper source changes are needed.

## Input and identity

`PlannerInput` holds the discovery snapshot, trusted context status, production
history, last reconciled movement, focus plateau, scroll exhausted/blocked,
pending transition, explicit safety block, and optional verified transition
value identities. The runtime projection copies existing state and client
ledgers without I/O or mutation. The diagnostic snapshot supplies state/substate,
actual focus, positional candidates and axis-v1 scroll evidence.

Discovery action IDs remain observation IDs. Attempt and visit joins call the
existing production `instance-v1` oracle with the production scenario scope.
Different bounds distinguish the same resource ID; dynamic text does not alter
a positional identity. Scenario scope is an accounting boundary, not plugin
verification or a ranking privilege. No second identity algorithm is introduced.

Unknown history never establishes a never-attempted claim. Positive recorded
attempt/visit facts remain usable even when history is incomplete. Accepted
partial trees do not establish the initial visited population, so their history
is explicitly incomplete. Historical transitions generally lack attempt history.

## Eligibility and ranking

Only `FOCUS_TARGET` is ranked as a focus choice. Click, activate, navigation,
horizontal scroll, and untargeted FOCUS_NEXT observations are never executable
planner candidates. Exclusion reasons cover proven staleness/absence,
nonfocusability or explicit unavailable/disabled state, invalid geometry,
explicit unsafe hints, and an observed Global Nav or production pool exclusion.

A present, geometrically valid, proven focusable candidate with unknown enabled
state remains eligible structurally, with `ACTIONABILITY_PARTIAL_EVIDENCE` and
at least tier 1. This is a focus observation, not activation permission.
UNKNOWN is not treated as proof of NOT_ACTIONABLE. Any later Phase 4B executor
must revalidate current target properties and focus landing independently.

| Tier | Meaning |
| --- | --- |
| 0 | Known never-attempted, unvisited candidate with available focus evidence |
| 1 | Attempted-unvisited, incomplete-history structural candidate, or partial actionability |
| 2 | Visited candidate with an explicitly verified transition-value signal |
| 3 | Visited or current-focus candidate without verified transition value |

Ties use current-focus penalty, consecutive actual recent attempts, actual
attempt count, oldest last production attempt step, top/left/bottom/right
geometry, production instance identity, and discovery action ID. There are no
weights, wall-clock ties, or randomness. Each candidate records its rank, tier,
reason codes, attempts, visits, consecutive attempts, and last attempt step.

Fresh candidates precede repeated attempts. Attempted-unvisited candidates
remain eligible. Real production attempts update the projection; shadow
recommendations do not consume candidates. With unchanged production inputs,
the same recommendation is expected, even if production never attempts it.
This preserves determinism and prevents an invented shadow attempt ledger.

Current focus is taken only from confirmed accessibility focus. Input-focus or
fallback flags do not establish it. Other candidates precede an unproductive
current-focus revisit. A sole current-focus candidate receives no new focus
recommendation without verified transition value.

## Attempt versus visit

ACK status never grants visits. Failed target requests remain attempts.
ACK success with unchanged actual focus is not a new visit. ACK failure with
actual movement may appear in the existing production reconciled visited set;
the planner consumes that membership. Reconciliation rows can count repeated
recorded visits only for supplied production membership. Phase 3 observations
and representative fallback rows have zero visit authority.

## Scroll and no progress

Vertical forward scroll requires observed axis-v1 supporting evidence and valid
container geometry. Proven exhaustion, contradiction/already attempted viewport,
pending transition, overlay safety block, or wrong/contradictory context blocks
scroll. When no tier 0–2 focus remains, valid scroll precedes low-value revisits
or no-action. Horizontal direction never becomes a vertical recommendation.

The planner records `SHADOW_NO_PROGRESS_ASSESSMENT`; production keeps its own
scroll and termination policy. Partial/unresolved context uses structural
evidence and adds `STRUCTURAL_ONLY_CONTEXT`. Food verification is never forced.

## Replay and comparison

`python -m tools.phase4a_shadow_replay --root <workspace> --out <artifact-dir>`
replays the 16 historical transitions against their exact saved dictionaries.
Planner decisions are separate sidecars, never transition inputs. Source
evidence SHA-256 hashes are checked before/after. All decisions are computed
twice to verify deterministic canonical output and zero authority.

Accepted replay covers Home, Devices, Food, Family Care, Find, and Smoke Sensor.
Each has one recorded viewport. Candidate counts are respectively
36, 56, 19, 18, 17, 12. Eligible structural focus counts are
18, 28, 4, 9, 9, 5. Home/Devices/Food context remains PARTIAL_CONTEXT;
the other three have VERIFIED_PLUGIN_CONTEXT. All six state resolutions remain
UNRESOLVED because accepted captures omit display geometry. This does not force
state IDs or plugin assumptions. Never-attempted counts remain zero because
the accepted initial history is incomplete.

Comparison uses intended production action, not the eventual landing of an
untargeted move. Exact targeted matches and same-tier alternatives are
EQUIVALENT_CHOICE; a demonstrably higher-priority shadow choice is
EXPECTED_SMARTER_CHOICE; a worse priority is POTENTIAL_REGRESSION. Untargeted
SMART_NEXT, composite actions, absent targets, and incomplete evidence are
INSUFFICIENT_EVIDENCE. Scroll direction equivalence cannot claim exact container
match. Unknown comparisons are not counted as proven agreements.

## Food observation only

Accepted Food evidence has 100 production reconciliations, 30 targeted attempts
to 30 distinct positional targets, 88 confirmed moved and 12 confirmed unchanged
outcomes. Only one viewport was recorded. The separate fixed-inventory history
experiment labels every row `INITIAL_VIEWPORT_REUSED_NOT_CURRENT` and makes no
never-attempted claims. It repeatedly recommends the same structural target;
partial history and an unchanged old inventory cannot establish fresh coverage,
starvation, current saturation, or eventual scroll. This is a data limitation,
not permission to consume recommendations as attempts. No early termination or
semantic saturation code is added. Unit tests prove fresh candidate rotation
when actual attempts are supplied, and scroll after eligible focus exhaustion.

## Reproducible bounded smoke

`python -m tools.phase4a_shadow_monitor` validates supported clean-start state
for each of the six scenarios and creates an external runtime config with
exactly five production steps. It uses the corrected `AcceptanceMonitor` with
Helper ownership/request-ID correlation and PID-anchored lifecycle evidence.
It never treats JSON `restart:false` keys as restart events. Device locale is
read and preserved; no locale switch or Full32 is performed.

The smoke harness writes entry observations, each pre-production raw/snapshot/
history/flags/recommendation, and a per-step post-persistence comparison trace.
Each trace includes full ranking and exclusions, counts, reasons, state/context,
production target, shadow target, scroll opportunity, and zero authority flags.

A preliminary diagnostic smoke identified overly conservative handling of
unknown enabled state. Its evidence is retained separately in
`out/phase3_current_main_20261011/phase4a_shadow_smoke_20261011`.
Acceptance uses a separate six-scenario run with the finalized planner; no
preliminary trace is silently rewritten. `tools.phase4a_shadow_validate` checks
six entries, 30 exact steps, all monitor gates, and exact final planner replay
against every captured input.

## Acceptance results



Verdict: **PHASE4A_SHADOW_PLANNER_PASS_WITH_LIMITATIONS**.

**READY_FOR_PHASE4B=YES**. Ranking is deterministic, A–Q contracts pass, no unsafe recommendation or major planner contract gap was found, and production remains the sole execution/visit authority. Controlled execution must retain target revalidation and exact request/landing reconciliation.

Tests: PLANNER_TESTS: 37 passed, 0 skipped; PHASE3_FOCUSED_TESTS: 456 passed, 0 skipped; PRODUCTION_FOCUSED_TESTS: 320 passed, 0 skipped; ADDITIONAL_FOCUSED_TESTS: 193 passed, 0 skipped; FULL_PYTHON_SUITE: 3545 passed, 1 skipped. Helper tests: NOT_REQUIRED.

Final smoke: `D:\Python test\talkback-a11y-helper\out\phase3_current_main_20261011\phase4a_shadow_acceptance_20261011`. Device `R3CX40QFDBP`, locale `en-US` preserved. Start 2026-10-11T01:37:04.704034+00:00; end 2026-10-11T01:54:20.219626+00:00. Six validated entries, six completed scenarios, 30 traces, and 30/30 exact deterministic final-input replays.

| Scenario | Steps | Context statuses | Comparisons |
| --- | --- | --- | --- |
| home_main | 5 | {'VERIFIED_ROOT_CONTEXT': 5} | {'INSUFFICIENT_EVIDENCE': 5} |
| devices_main | 5 | {'VERIFIED_ROOT_CONTEXT': 5} | {'INSUFFICIENT_EVIDENCE': 3, 'EQUIVALENT_CHOICE': 2} |
| life_food_plugin | 5 | {'PARTIAL_CONTEXT': 5} | {'INSUFFICIENT_EVIDENCE': 5} |
| life_family_care_plugin | 5 | {'VERIFIED_PLUGIN_CONTEXT': 5} | {'INSUFFICIENT_EVIDENCE': 5} |
| life_find_plugin | 5 | {'VERIFIED_PLUGIN_CONTEXT': 5} | {'EQUIVALENT_CHOICE': 1, 'INSUFFICIENT_EVIDENCE': 4} |
| device_smoke_sensor_plugin | 5 | {'VERIFIED_PLUGIN_CONTEXT': 5} | {'INSUFFICIENT_EVIDENCE': 5} |

All lifecycle/transport gates: `{"TALKBACK_PID_CHANGE_COUNT": 0, "HELPER_UNEXPECTED_PID_CHANGE_COUNT": 0, "WINDOW_FATAL_COUNT": 0, "FATAL_BADTOKEN_COUNT": 0, "HELPER_ANR_COUNT": 0, "SMART_NEXT_TIMEOUT_COUNT": 0, "FOCUS_TIMEOUT_COUNT": 0, "CHUNK_ERROR_COUNT": 0, "INSPECTION_SUPPRESSION_COUNT": 0, "TALKBACK_RECONNECT_COUNT": 0}`. ENTRY failures: 0.

Primary trace: `D:\Python test\talkback-a11y-helper\out\phase3_current_main_20261011\phase4a_shadow_acceptance_20261011\phase4a_shadow_trace.jsonl`. Captured inputs: `phase4a_observations.jsonl`; final replay proof: `shadow_validation.json`; runtime monitor: `monitor_result.json`; test XMLs and accepted replay summary are under `D:\Python test\talkback-a11y-helper\out\phase3_current_main_20261011`.

A–Q matrix: A/B/C never-attempted/repeated-attempt eligibility; D current-focus penalty; E/F parameterized ACK/fallback no-credit; G production reconciled movement with ACK failure; H positional identity; I stale exclusion; J nonactionable; K/L scroll/no-action; M/N partial-context/scenario-independent structure; O deterministic ordering; P actual-attempt rotation; Q recent-repeat penalty. Additional tests cover pure projection, unknown positive history, current-only no-action, horizontal scroll exclusion, Global Nav domain exclusion, overlays/wrong context, and wrapper forwarding/restoration.
