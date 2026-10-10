# TalkBack English device-card entry RCA — 2026-10-10

## Scope and source

This change is based on published `main` at
`db6bc53fe68603ab4bd7771ddf0831deddeb4b90` and the branch
`fix/english-device-card-entry-hardstop`. It addresses the shared entry path
used by the 12 Devices card plugins and the acceptance monitor's missing
terminal-scenario hard stop. No English Full32 was run.

## Rejected Full32 evidence

English batch `batch_20261010_192214` was rejected after the first device-card
scenario, `device_smoke_sensor_plugin`, ended with
`INCOMPLETE_ERROR / tab_or_anchor_failed`. Its first terminal record was at
20:23:56 KST:

```text
[TRAVERSAL_SUMMARY] scenario='device_smoke_sensor_plugin' attempted=0 moved=0 failed=0 rows=1 unique_visited=0 candidates=0 semantic_covered=0 termination=INCOMPLETE_ERROR reason='tab_or_anchor_failed' terminal_step=-1
```

The Devices main scenario had entered successfully. It then traversed 62
accessibility moves and ended with `INCOMPLETE_NO_PROGRESS / content_no_progress`.
The first device-plugin attempt reported:

```text
[DEVICE_ENTRY][visible_target] direct_entry=false reason='devices_context_unverified:all_devices_not_found'
[SCROLL_TOP] reached_top=true reason='verified_top' evidence='stable_first_device_card'
[DEVICE][location] selection_verify_failed expected='All devices' actual='거실' reason='all_devices_candidate_not_found'
```

The same `tab_or_anchor_failed` result then appeared for all 12 device-card
scenarios. The Devices tab itself had been entered and verified; the failure
was downstream in device-card entry. The historical run's runner log is at
`qa_frontend_runs/batch_20261010_192214/device_SM-F741N_R3CX40QFDBP/runner.log`.

## Shared entry path and root cause

The common path is:

`recover_to_start_state` → `recover_to_device_start_state` →
`_ensure_all_devices_location_selected` →
`find_all_devices_location_candidate` →
`_run_enter_device_card_plugin` →
`find_device_card_by_stable_label` → `_tap_device_card_safe` →
`_confirm_click_focused_transition`.

The failure was a **horizontal viewport start-position** problem. The All
devices location chip had moved outside the visible part of the horizontal
location strip during Devices main traversal. The vertical device-list
normalizer still reported the first device card at the top, so it did not
restore the separate horizontal strip. The visible-only All devices candidate
finder therefore had no candidate to select. The selected location was the
room `거실`.

Evidence separates this from a locale or card-filter problem:

- The saved Devices hierarchy contains the app's `id/search_icon` and
  actionable `id/device_card` frames. A Smoke card has a child
  `id/device_name` and a `Smoke detected` status node.
- The All devices chip is a focusable `LinearLayout` with text and
  content-description `All devices`; its child is `id/title`. The chip has no
  dedicated resource ID. Its saved initial bounds were `171,286,459,436` and
  it was selected in that initial snapshot.
- In the failed entry attempt, the All devices candidate was absent from the
  visible tree after the strip moved horizontally. It was not rejected for a
  wrong device-card resource ID, inaccessible card container, or unmatched
  locale string.
- `[SCROLL_TOP] reached_top=true` proves vertical normalization succeeded; it
  does not reset the independent location-chip strip.
- Korean batch `batch_20261010_110819` entered Smoke, TV, and Washer cards and
  completed their plugin-boundary traversals. Its card hierarchy uses the
  same `id/device_card` container and `id/device_name` child. English Devices
  main batches `batch_20261010_162536` and `batch_20261010_174706` also passed
  their Devices-tab entry contract.

Replay field assessment:

```text
ALL_DEVICES_NODE_PRESENT=NO in the failed attempt's visible tree; YES in the saved initial Devices hierarchy
TARGET_DEVICE_NODE_PRESENT=YES in the saved initial Devices hierarchy; absence at the exact failed instant is not established
CANDIDATE_FILTERED=NO; no visible All devices candidate was available to filter
CANDIDATE_FILTER_REASON=all_devices_candidate_not_found because the chip was outside the visible strip viewport
RESOURCE_ID_MATCH=chip has no dedicated ID; device card uses the recognized id/device_card
TEXT_MATCH=English All devices text is present in the saved node, absent from the failed visible tree
CONTENT_DESCRIPTION_MATCH=All devices is present on the saved chip
VIEWPORT_RELEVANT=YES, horizontal location strip was shifted
SCROLL_STATE_RELEVANT=YES, horizontal strip position mattered; vertical scroll-to-top had succeeded
```

The Korean comparison does not show a different card structure that would
explain the failure: accepted Korean Smoke/TV/Washer entry uses the same card
container and device-name child. The acceptance evidence proves those Korean
entries worked; it does not prove that the strip viewport had the same start
position. No language-specific hierarchy difference is needed to explain the
English failure.

**RCA classification:** `VIEWPORT_START_POSITION` (horizontal location strip).
`ROOT_CAUSE_PROVEN=YES`. Locale text matching, resource-ID matching,
actionable-container promotion, and vertical scroll-to-top were not the cause.

## Minimal shared fix

When the expected All devices candidate is missing, the runner now performs a
recovery only if it has already verified Devices-tab context and the fresh
tree has both the Devices search anchor and a visible device card. It finds
the visible top-row location-chip strip structurally, sends at most three
left-revealing horizontal swipes inside that row, and dumps a fresh hierarchy
after each swipe. It stops on a visible All devices candidate, no visible
change, or the swipe bound. The existing selected-state check, candidate tap,
card matching, and post-open verification remain required. Candidate
acceptance was not weakened, and no text, plugin, wait, or traversal limit was
hardcoded.

The monitor now treats fresh `[PERF][scenario_contract_summary]`,
`[TRAVERSAL_SUMMARY]`, explicit scenario-result, and structured terminal-result
records as acceptance inputs. It hard-stops on the specified terminal
automation errors and explicit failed statuses. Accepted incomplete/no-progress
and safety-limit states continue. The API fallback now requires a failed
scenario record with an explicit terminal execution contract; the API's
transient `failed_scenarios` counter alone is not terminal evidence. This
matters because the live dashboard can briefly label an entered active
scenario failed before its scenario summary exists. Per-scenario terminal
contract data is now included in live batch progress.

## Validation

Targeted batches were run with device locale `en-US`, effective SmartThings
locale `en-US`, TalkBack PID `17467`, and Helper PID `12034`:

`cmd package get-app-locales` is unsupported by this device build. The
preflight showed no SmartThings app-locale override (`[]`), so the effective
app locale remained the unchanged system locale `en-US`. Each batch generated
its workbook artifact. The three batches ran from 21:00:17 to 21:29:13 KST
(28m56s total).

| Scenario | Batch | Entry and traversal evidence | Terminal result |
|---|---|---|---|
| Smoke sensor | `batch_20261010_210014` | Direct visible-card match and safe tap; post-open contract verified; 11 attempted / 11 moved | `COMPLETED`, 9 unique visits, no anchor abort |
| Door lock | `batch_20261010_210251` | All devices context confirmed; target revealed and safely tapped; post-open contract verified; 10 / 10 | `COMPLETED`, 8 unique visits, no anchor abort |
| TV | `batch_20261010_210251` | Target revealed and safely tapped; post-open contract verified; 15 / 15 | `COMPLETED`, 16 unique visits, no anchor abort |
| Washer | `batch_20261010_210251` | Target revealed and safely tapped; post-open contract verified; 20 / 20 | `COMPLETED`, 21 unique visits, no anchor abort |
| Humidity sensor | `batch_20261010_211200` | Target revealed and safely tapped; post-open contract verified; 9 / 9 | `COMPLETED`, 7 unique visits, no anchor abort |
| Camera | `batch_20261010_211200` | Target revealed and safely tapped; post-open contract verified; 100 attempted / 98 moved | `INCOMPLETE_SAFETY_LIMIT`, 18 unique visits, no anchor abort |

All six selected scenarios entered and started traversal. There were no
SMART_NEXT or focus timeouts in the runner records. Camera reached the
existing 100-step safety limit after traversal; this is an accepted coverage
limitation for this entry validation. No Camera termination or traversal code
was changed.

The first smoke attempt (`batch_20261010_205530`) was stopped by the monitor
when the live API's transient failed counter rose while the scenario was still
running. Its log shows that plugin-open verification succeeded and traversal
had begun and a SMART_NEXT move had completed. The API had reported one failed
scenario while terminal count was zero. That was a monitor false stop, not a
plugin failure. A monitor regression test now proves that the counter alone
does not stop an active scenario and that an explicit terminal contract does.

Focused entry and monitor tests passed: 114 tests before the terminal-contract
API refinement; the updated live-status and monitor API tests passed 58 tests,
with the latest focused pair passing 2 tests. The final full suite passed:
`python -m pytest tests -q` → **3210 passed, 1 skipped** in 118.63 seconds.

The monitor replay test feeds the first hard-failure record from the rejected
English run and verifies stop at `device_smoke_sensor_plugin`, reason
`tab_or_anchor_failed`. Tests also cover `anchor_abort`, explicit failed
status, accepted no-progress/safety-limit/warning states, stale timestamps,
and false-valued lifecycle keys. The targeted live monitors wrote 1,248 status
samples; all reported empty `hard_blockers`, and every sampled TalkBack PID was
`17467`. Helper PID was `12034` in preflight and after the runs. No Helper ANR,
fatal, or restart marker was recorded. The live wrapper continuously polls
TalkBack PID; Helper PID transition count here is based on its unchanged
preflight/final PID and absence of Helper crash/restart markers.

Across targeted runner and logcat evidence, the recorded counts were:

```text
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
```

## Scope boundaries and readiness

No Helper source, Phase 3/4, Camera/Home Camera traversal or termination, or
Family Care logic/cache was changed. Korean device-card replay/regression tests
passed; the accepted Korean Full32 evidence remains preserved and was not
rerun. No English Full32 was run. The monitor replay detected the first
historical failure at `device_smoke_sensor_plugin` and stopped on
`INCOMPLETE_ERROR / tab_or_anchor_failed`.

**Verdict: `DEVICE_CARD_ENTRY_FIX_PASS_WITH_LIMITATIONS`.** The shared entry
fix is proven and all required target plugins entered and traversed. Camera
reached its unchanged safety limit, so this validation does not claim full
Camera content coverage. The fix is ready for one English Full32 retry with
the terminal-scenario hard stop enabled.

Publication record: pending scoped commit, branch push, and fast-forward main
push.
