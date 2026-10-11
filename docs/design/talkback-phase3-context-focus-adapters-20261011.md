# Phase 3 context and focus adapters

Date: 2026-10-11
Integration branch: `integration/phase3-current-main`
Accepted main baseline: `6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`

## Purpose and boundaries

The adapters supply evidence-backed context and focus observations to the existing Phase 3 state and transition observers. They do not choose traversal targets, award visits, change production navigation, or alter Helper behavior. Existing traversal policy remains authoritative.

## Gaps addressed

Before this change, entry context was assembled across `tools.state_fingerprint_diagnostic.capture_observation`, `tb_runner.state_observation.build_state_observation` and `observation_problems`, `tb_runner.discovery_candidates.build_discovery_snapshot`, and `tb_runner.state_registry.StateRegistry.observe`. Those paths did not share one provenance check tying a plugin observation to the checked-in entry contract and the current scenario execution. A scenario ID by itself could therefore look more authoritative than its evidence.

Focus was separately projected by `tb_runner.transition_observation._focus` and `_focus_row`, while `tb_runner.focus_reconciliation.reconcile_focus` consumed production reconciliation evidence. The smoke hook previously compared independent focus snapshots without proving that the before and after observations belonged to the exact Helper request. A `focused` flag or a `TARGET_RESOLVED` record could be mistaken for actual accessibility focus.

## Context contract

`tb_runner.phase3_context.resolve_phase3_context` validates context using the following precedence:

1. A Home or Devices root context requires an observed selected tab and a unique observed root resource marker. If runtime package and activity are available, they are included as additional identity evidence.
2. A plugin context requires the checked-in scenario entry contract hash, matching scenario and run IDs, valid entry evidence from the current production main loop or the exact accepted Full32 terminal event, the expected selected tab, a passing checked-in `context_verify` body expression, and activity or unique resource identity.
3. Scenario identity alone never verifies context. Conflicting body or selected-tab evidence is reported rather than reconciled optimistically.

Context sources are restricted to `service_hierarchy_selected`, `helper_selected`, and `observed_selected_node`. Results distinguish `VERIFIED_ROOT_CONTEXT`, `VERIFIED_PLUGIN_CONTEXT`, `PARTIAL_CONTEXT`, `UNRESOLVED_CONTEXT`, `WRONG_CONTEXT`, and `CONTRADICTORY_CONTEXT`.

`build_state_observation` accepts plugin navigation context only when plugin context is verified. It waives missing package/activity only for a verified root selected tab plus its unique root marker. Missing display geometry stays unbound; the adapter does not invent bounds or state IDs. Focus remains optional to state identity.

## Focus contract

`tb_runner.phase3_focus.normalize_phase3_focus_transition` accepts a strict transition only when the Helper `evidence-helper-v1` ledger proves the exact `reqId`, `SMART_NEXT` ownership, request start and ACK order, scenario/run/capture identity, pre/post snapshot order, and ACK correspondence.

Actual accessibility focus is the strict focus signal. A `focused` flag by itself is marked `FALSE_FOCUS_FALLBACK`; a correlated `POST_ACTION_OBSERVATION` is preferred, while `TARGET_RESOLVED` is not actual focus. The adapter uses the existing positional identity (resource ID and bounds), so the same resource ID at different bounds remains a different instance.

Results record movement, no movement, ACK outcome, stale evidence, fallback, or indeterminate evidence. Every result gives zero visit credit and carries no production visit authority. Invalid correlation clears projected actual focus before `TransitionObserver.complete` receives it.

## Negative and positive evidence

Context tests cover root Home and Devices, all plugin entry contexts, scenario-only evidence, wrong body verification, stale evidence and run leakage, global navigation only, selected-tab mismatch, conflicting body evidence, accepted terminal-event provenance without activity for Family Care and Find, and partial accepted root evidence.

Focus tests cover the A-I behavior matrix plus scenario, run, and capture mismatches. They assert exact request correlation, actual-focus precedence, fallback classification, safe indeterminate outcomes, and zero visit authority.

## Verification results

- New context and focus adapter tests: 34 passed.
- Broad targeted groups: 636 passed.
- Phase 3 focused inventory plus adapters: 456 passed (422 existing focused cases and 34 adapter cases).
- Production focused inventory: 320 passed.
- Historical Phase 3 replay: 16/16 exact. All 16 controlled actions mapped; state-binding mismatch, transition collision, unsafe bind, and unexpected churn counts were zero.
- Accepted baseline replay: all six scenarios passed candidate discovery with no false visits or material regression. Home, Devices, and Food remained `PARTIAL_CONTEXT`; Family Care, Find, and Smoke Sensor were `VERIFIED_PLUGIN_CONTEXT`. Captures without display bounds remained unresolved by design. Find had coherent focus evidence; other accepted captures retained partial or unknown focus where data was absent.
- Full `pytest -q` run: 3,508 tests, 17 failures, no errors, one skip. All 17 are in the existing root `test_talkback_lib.py` compatibility/focus tests. `talkback_lib/__init__.py` and `test_talkback_lib.py` are unchanged from accepted main; the failures do not touch adapter files. The focused requested suites passed.

## Live smoke and readiness

Device preflight succeeded on serial `R3CX40QFDBP`; TalkBack PID was `19549`, Helper PID was `12034`, both services were enabled, both package paths were present, and the device locale was recorded as `en-US` without changing it. There were no PID changes or monitor lifecycle hits.

The bounded smoke stopped at its first scenario, `home_main`, which terminated `INCOMPLETE_ERROR` with `tab_or_anchor_failed` because the existing selected-tab verifier observed no bottom-navigation candidates. The process had not entered the Phase 3 main-loop hook, so this run produced no live adapter transition evidence. The process was stopped by the anchored terminal scenario result; the remaining five smoke scenarios were not run.

**Phase 4 readiness: NO.** Offline replay and focused tests support the adapter contracts, but the live run did not reach the adapter hook and the full Python suite has 17 existing compatibility/focus failures. No production traversal or Helper changes were made in response to these findings.
