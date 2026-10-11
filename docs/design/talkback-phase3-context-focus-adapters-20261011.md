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

## Acceptance recovery

This section records the recovery run and supersedes the earlier live-smoke and readiness result above. The earlier Home run remains part of the history: it started on a plugin refresh/content view, lacked bottom-navigation candidates, and stopped before the Phase 3 hook. No adapter conclusion was drawn from it.

### Full-suite failure RCA and isolation

All 17 failing `test_talkback_lib.py` cases were reproduced individually and in the original full-suite order. They also failed after the Phase 3 adapter tests before the fixes. No order dependency or shared-state leak was found: the adapter tests do not mutate environment/global runner state, HelperBridge caching is instance-scoped, and each failing case failed alone.

| Cases | Classification and evidence | Fix |
| --- | --- | --- |
| `TouchIsinTest.test_focus_in_bounds_sends_helper_command`; `SmartMoveFocusTest.test_move_focus_smart_maps_legacy_bottom_bar_status_to_moved`, `test_move_focus_smart_marks_terminal_when_end_of_sequence_detail_returned`, `test_move_focus_smart_next_does_not_call_dump_or_get_focus`, `test_move_focus_smart_next_does_not_clear_logcat`, `test_move_focus_smart_returns_failed_when_status_invalid`, `test_move_focus_smart_uses_android_side_smart_next_status`, `test_move_focus_smart_uses_detail_when_status_unknown`, `test_move_focus_smart_uses_recent_helper_cache` | 9 fixture-assumption failures. `uuid.uuid4()` mocks returned strings, while the current production request contract reads `.hex`, producing `AttributeError: 'str' object has no attribute 'hex'`. These tests predate the adapters and were not touched by adapter code. | Return UUID-shaped `SimpleNamespace(hex=...)` fixtures. The `focus_in_bounds` case also had an obsolete fake transport: `FakeA11yClient` recorded `_run`, while the client now uses `_broadcast`. The fake now records the current transport. Production transport is unchanged. |
| `ClientInterfaceCompatTest.test_clear_logcat_is_public_and_uses_default_dev_serial`; `test_clear_logcat_returns_empty_string_on_timeout` | 2 outdated API expectations. The tests expected the older `_run` call and timeout message; the current implementation invokes `adb` through `subprocess.Popen` and treats logcat clearing as best-effort, including process cleanup on timeout. | Patch the current `Popen` boundary and assert the default-serial command, timeout cleanup and current warning. |
| `FocusHelpersTest.test_client_algorithm_version_is_updated` | 1 outdated test expectation: expected `1.7.42`, while the checked-in client reports `1.7.71`. | Update the expectation to `1.7.71`. |
| `FocusHelpersTest.test_collect_focus_step_does_not_force_fallback_when_top_level_payload_not_sufficient`, `test_collect_focus_step_does_not_override_existing_announcement_with_top_level_fallback`, `test_collect_focus_step_does_not_trim_battery_only_announcement`, `test_collect_focus_step_does_not_trim_when_visible_anchor_not_found`, `test_collect_focus_step_trims_battery_suffix_when_prefix_matches_focus` | 5 focus-semantic cases. Their fixtures conflated input `focused` with actual `accessibilityFocused` evidence, or expected fallback/trim behavior without proving accessibility focus. A real narrow production gap was found: focus-label fallback did not require confirmed accessibility focus. | Gate the snapshot label fallback on `safe_focus_node.accessibilityFocused is True`; update negative fixtures to state `focused=True, accessibilityFocused=False`, and add a positive confirmed-accessibility-focus test. Existing spoken announcements remain authoritative without actual accessibility focus. |

The production focus change preserves the accepted distinction between input focus and accessibility focus. Phase 3 remains observational; the production visit ledger remains authoritative. No traversal, entry, termination, Helper, Camera or Family Care logic changed. The former 17 cases plus the new positive focus case passed after the adapter tests (52 tests in that combined check). The complete top-level `test_talkback_lib.py` module then passed 154/154. The full Python suite passed 3,508, failed 0, skipped 1 (3,509 collected).

### Smoke-only precondition and bounded run

The Home failure was a smoke start-state problem before adapter entry: a plugin refresh/content view had replaced the stable shell, leaving no bottom-navigation candidates. Recovery added a smoke-only precondition around the existing `tools.clean_start_smartthings.clean_start_smartthings` helper. For every scenario, it returns to the SmartThings shell, checks the foreground package/activity, verifies bottom navigation and the selected tab, confirms no transient modal, and records locale and service PIDs. Only after `SMOKE_PRECONDITION_READY` does the harness invoke the normal production scenario entry. It does not navigate directly to a target plugin or change production traversal behavior.

An initial harness diagnostic was discarded before scenario entry because its wrapper passed an unsupported `dev=` keyword. The wrapper signature was corrected; the valid monitored run below is the sole six-scenario smoke evidence. Each of the six independently validated preconditions with SmartThings foreground, bottom navigation available, no transient overlay and Home selected at start. The run used serial `R3CX40QFDBP`, left locale `en-US` unchanged, and ran from `2026-10-11T00:33:08.284837Z` to `2026-10-11T00:55:06.017473Z` (21m57.733s). The five-step cap intentionally produces `INCOMPLETE_SAFETY_LIMIT`; that is the expected bounded-smoke terminal condition after successful entry.

| Scenario | Precondition / entry | Context status and source | Phase 3 state / resolution | Candidates |
| --- | --- | --- | --- | ---: |
| `home_main` | ready; `VERIFIED_MAIN_LOOP` | `VERIFIED_ROOT_CONTEXT`; `observed_selected_tab+observed_root_body+window_activity` | created / `CREATED` | 54 |
| `devices_main` | ready; `VERIFIED_MAIN_LOOP` | `VERIFIED_ROOT_CONTEXT`; `observed_selected_tab+observed_root_body+window_activity` | created / `CREATED` | 65 |
| `life_food_plugin` | ready; `VERIFIED_MAIN_LOOP` | `PARTIAL_CONTEXT`; `insufficient_or_contradictory_runtime_evidence` (`PLUGIN_BODY_EVIDENCE_MISSING`) | not created / `UNRESOLVED` | 31 |
| `life_family_care_plugin` | ready; `VERIFIED_MAIN_LOOP` | `VERIFIED_PLUGIN_CONTEXT`; `production_entry_boundary+context_verify_body+observed_activity+plugin_resource_identity` | created / `CREATED` | 23 |
| `life_find_plugin` | ready; `VERIFIED_MAIN_LOOP` | `VERIFIED_PLUGIN_CONTEXT`; `production_entry_boundary+context_verify_body+observed_activity+plugin_resource_identity` | created / `CREATED` | 18 |
| `device_smoke_sensor_plugin` | ready; `VERIFIED_MAIN_LOOP` | `VERIFIED_PLUGIN_CONTEXT`; `production_entry_boundary+context_verify_body+observed_activity+plugin_resource_identity` | created / `CREATED` | 21 |

| Scenario | Focus observations / moved / unchanged / indeterminate | ACK success no move / ACK failure but move | False fallback / stale evidence | Attempted / unique visits / transitions | Terminal status / reason / anchor abort |
| --- | --- | --- | --- | --- | --- |
| `home_main` | 5 / 4 / 0 / 1 | 0 / 0 | 0 / 1 | 5 / 6 / 5 | `INCOMPLETE_SAFETY_LIMIT` / `safety_limit` / no |
| `devices_main` | 5 / 4 / 0 / 0 | 0 / 0 | 1 / 0 | 5 / 5 / 5 | `INCOMPLETE_SAFETY_LIMIT` / `safety_limit` / no |
| `life_food_plugin` | 5 / 4 / 0 / 1 | 0 / 0 | 0 / 1 | 5 / 5 / 5 | `INCOMPLETE_SAFETY_LIMIT` / `safety_limit` / no |
| `life_family_care_plugin` | 17 / 12 / 1 / 3 | 0 / 0 | 1 / 3 | 5 / 6 / 17 | `INCOMPLETE_SAFETY_LIMIT` / `safety_limit` / no |
| `life_find_plugin` | 10 / 5 / 3 / 2 | 0 / 0 | 0 / 2 | 5 / 5 / 10 | `INCOMPLETE_SAFETY_LIMIT` / `safety_limit` / no |
| `device_smoke_sensor_plugin` | 5 / 5 / 0 / 0 | 0 / 0 | 0 / 0 | 5 / 6 / 5 | `INCOMPLETE_SAFETY_LIMIT` / `safety_limit` / no |

Food entry and traversal succeeded, and the runtime showed the recipe plugin activity/body and recipe-card resources. The checked-in Food `context_verify` expression did not match that observed body, so the adapter correctly withheld verified plugin context and created no state. This remains a diagnostic evidence limitation; scenario identity was not used as a substitute. Family Care, Find and Smoke Sensor resolved verified plugin context from current runtime evidence.

The 47 live focus observations were classified as 34 `FOCUS_MOVE_CONFIRMED`, 4 `ACK_FAILURE_NO_FOCUS_MOVE`, 2 `FALSE_FOCUS_FALLBACK`, and 7 `STALE_OR_CONTRADICTORY_EVIDENCE`. The counters `ACK_SUCCESS_NO_MOVE` and `ACK_FAILURE_BUT_MOVE` were both zero. Every focus sidecar record had `visit_credit=0` and `production_visit_authority=false`; the observer did not drive the next action or traversal order.

Separately, the normal Family Care runner reconciled one ACK-failed action with actual focus movement as a movement on the production path. That action was not among the 47 intercepted adapter-hook observations, so it is not included in the hook-level `ACK_FAILURE_BUT_MOVE` count.

### Recovery verification and final readiness

- Phase 3 focused suite: 456 passed. Production focused suite: 320 passed.
- Historical Phase 3 replay: 16/16 exact; mapping, binding, collision, unsafe-bind and unexpected-churn error counts were zero.
- Accepted baseline replay: all six scenarios passed candidate discovery, with no false visits and no material regression.
- Full Python suite: 3,508 passed, 0 failed, 1 skipped.
- The valid six-scenario smoke completed all six scenario entries and all six bounded traversals without an anchor abort or hard-stop monitor hit.
- Lifecycle gates across the smoke were all zero: TalkBack PID changes, unexpected Helper PID changes, window fatal, fatal BadToken, Helper ANR, SMART_NEXT timeout, focus timeout, chunk error, inspection suppression and TalkBack reconnect. TalkBack PID stayed `19549`; Helper PID stayed `12034`.
- Context resolution was verified for both roots and for Family Care, Find and Smoke Sensor. Food remains partial only because its configured body expression did not match the runtime evidence.
- Focus remained evidence-correlated and observational, with zero visit credit and no production visit authority.

**Verdict: `PHASE3_ADAPTER_ACCEPTANCE_PASS_WITH_LIMITATIONS`. Phase 4 readiness: YES.** The hard suite, replay, bounded entry/traversal, focus semantics and lifecycle gates passed. The Food body-verification mismatch is retained as a visible non-blocking context limitation. Phase 4 is not implemented in this recovery.

Evidence is under `out/phase3_current_main_20261011/`: `phase3_recovery_individual/summary.json`, `phase3_recovery_order_isolation.xml`, `phase3_recovery_full_suite.xml`, `phase3_recovery_phase3_focused.xml`, `phase3_recovery_production_focused.xml`, `phase3_recovery_replay_20261011/summary.json`, and `phase3_adapter_recovery_smoke_fixed_20261011/`.
