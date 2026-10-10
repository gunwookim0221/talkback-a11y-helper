# Korean Full32 Acceptance Rejection — 2026-10-07

## Decision

**REJECT_NEW_BASELINE.** The one monitored Korean Full32 reached terminal state for all 32 selected scenarios, but TalkBack crashed three times during the run. Two scenarios were explicitly invalidated as `INCOMPLETE_ERROR/talkback_restarted`; the first crash occurred before the runner's first lifecycle sample and was not caught by its internal PID comparison. The source summary and generated review workbook also disagree on automation diagnostic count, target-focus outcomes are not fully represented in workbook rows, and the generated baseline candidate is not eligible under its worktree check.

No production code was changed. This report is on review branch `docs/korean-full-run-acceptance-20261007`; no commit, branch push, merge, or main push was performed. No second Full32 was started.

## Run identity and preflight

| Field | Value |
|---|---|
| Batch | `batch_20261007_080753` |
| Device | `SM-F741N` / `R3CX40QFDBP` |
| Locale | `ko-KR` |
| Start | 2026-10-07 08:07:54 KST |
| End | 2026-10-07 11:56:44 KST |
| Runtime | 3:48:50 |
| Runner state / device state / return code | `finished` / `passed` / `0` |
| Source branch | `docs/korean-full-run-acceptance-20261007` |
| Source HEAD / `origin/main` | `df9e8b86df3df06c2d5dce1b107b2aec60b86094` / same |
| Lifecycle monitoring | `TALKBACK_WINDOW_LIFECYCLE=1`; lifecycle records present throughout the run |
| Pre-run TalkBack PID | `18593` |
| Android / One UI / TalkBack | 15 / 7.0 / 15.1.01.1 |
| SmartThings version | 1.8.51.30 |

Pre-run locale, TalkBack, Helper service, and device checks passed. The pre-run lifecycle sample recorded 22 total windows and one TalkBack-owned window. Tracked source was clean at launch. Provenance records no staged or modified tracked paths; it also records preserved untracked/ignored output paths. The run metadata is in `qa_frontend_runs/batch_20261007_080753/batch_summary.json`, `repository_provenance.json`, and the device `runtime_config.json`.

## Execution integrity

- Expected, observed, and terminal scenarios: **32 / 32 / 32**.
- Missing, extra, duplicate scenario IDs: **0 / 0 / 0**. The observed and terminal ID lists match the selected canonical set.
- Global Navigation: **5/5 destinations verified**.
- Scenario termination counts: **14 `COMPLETED`, 15 `INCOMPLETE_NO_PROGRESS`, 1 `INCOMPLETE_SAFETY_LIMIT`, 2 `INCOMPLETE_ERROR`**.
- Device execution completed with return code 0, while `summary.json` reports `scenario_result_status=failed`, 14 passed, 16 warning, and 2 failed scenarios. `process_status` is `unknown` in that summary.

### Per-scenario traversal and completeness

`Coverage` is actual visited / expected, followed by missed / unknown. Global Navigation is reported separately because it verifies destinations rather than content traversal.

| Scenario | Attempted | Unique / candidates | Coverage; missed / unknown | Termination |
|---|---:|---:|---|---|
| `global_nav_main` | — | — | 5/5 destinations | `COMPLETED / global_nav_verified` |
| `home_main` | 23 | 16 / 44 | 16/48; 17 / 15 | `INCOMPLETE_NO_PROGRESS / content_no_progress` |
| `home_safe_plugin` | 16 | 14 / 31 | 18/38; 9 / 11 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `life_food_plugin` | 28 | 20 / 28 | 20/32; 11 / 1 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `life_air_care_plugin` | 11 | 10 / 12 | 14/17; 1 / 2 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `life_home_care_plugin` | 14 | 11 / 13 | 14/17; 1 / 2 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `life_energy_plugin` | 41 | 29 / 31 | 34/44; 6 / 4 | `COMPLETED / scroll_exhausted` |
| `devices_main` | 64 | 43 / 85 | 43/106; 30 / 33 | `INCOMPLETE_NO_PROGRESS / content_no_progress` |
| `device_smoke_sensor_plugin` | 17 | 9 / 12 | 9/12; 3 / 0 | `COMPLETED / plugin_boundary_global_nav` |
| `device_water_leak_sensor_plugin` | 11 | 8 / 12 | 8/12; 3 / 1 | `COMPLETED / plugin_boundary_global_nav` |
| `device_motion_sensor_plugin` | 11 | 7 / 9 | 7/9; 2 / 0 | `COMPLETED / plugin_boundary_global_nav` |
| `device_door_lock_plugin` | 11 | 8 / 10 | 8/10; 2 / 0 | `COMPLETED / plugin_boundary_global_nav` |
| `device_air_purifier_plugin` | 19 | 9 / 35 | 9/35; 7 / 19 | `COMPLETED / plugin_boundary_global_nav` |
| `device_tv_plugin` | 55 | 17 / 24 | 17/24; 7 / 0 | `COMPLETED / plugin_boundary_global_nav` |
| `device_washer_plugin` | 31 | 30 / 52 | 30/52; 15 / 7 | `COMPLETED / plugin_boundary_global_nav` |
| `device_humidity_sensor_plugin` | 11 | 7 / 9 | 7/9; 2 / 0 | `COMPLETED / plugin_boundary_global_nav` |
| `device_temperature_humidity_sensor_plugin` | 11 | 7 / 9 | 7/9; 2 / 0 | `COMPLETED / plugin_boundary_global_nav` |
| `device_camera_plugin` | 72 | 27 / 29 | 27/47; 16 / 4 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `device_home_camera_plugin` | 100 | 51 / 50 | 51/87; 21 / 15 | `INCOMPLETE_SAFETY_LIMIT / safety_limit` |
| `device_audio_plugin` | 16 | 16 / 18 | 16/19; 2 / 1 | `COMPLETED / plugin_boundary_global_nav` |
| `life_main` | 31 | 17 / 35 | 17/56; 15 / 24 | `INCOMPLETE_NO_PROGRESS / content_no_progress` |
| `routines_main` | 23 | 18 / 40 | 18/40; 7 / 15 | `INCOMPLETE_NO_PROGRESS / content_no_progress` |
| `menu_main` | 66 | 33 / 57 | 33/67; 11 / 23 | `INCOMPLETE_NO_PROGRESS / content_no_progress` |
| `settings_entry_example` | 87 | 26 / 47 | 26/65; 10 / 29 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `life_pet_care_plugin` | 3 | 2 / 5 | 6/9; 3 / 0 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `life_family_care_plugin` | 35 | 29 / 60 | 38/101; 13 / 50 | `COMPLETED / scroll_exhausted` |
| `life_plant_care_plugin` | 0 | 0 / 0 | 0/0; 0 / 0 | `INCOMPLETE_ERROR / talkback_restarted` |
| `life_clothing_care_plugin` | 4 | 2 / 8 | 2/8; 4 / 2 | `INCOMPLETE_ERROR / talkback_restarted` |
| `life_find_plugin` | 10 | 9 / 13 | 12/16; 0 / 4 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `life_video_plugin` | 16 | 7 / 10 | 11/15; 2 / 2 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| `life_home_monitor_plugin` | 16 | 17 / 55 | 17/55; 18 / 20 | `COMPLETED / plugin_boundary_global_nav` |
| `life_music_sync_plugin` | 6 | 5 / 5 | 5/5; 0 / 0 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |

## Blocking lifecycle RCA

The run has **three TalkBack app-crash exits and three PID changes**. The initial process change was missed by the runner's restart detector because its first in-run sample arrived after the crash and reported `previous_talkback_pid=null`.

| Time (KST) | Process evidence | Consequence |
|---|---|---|
| 08:09:09 | PID `18593` crashed with `IllegalStateException: window count is over max!!` at `WindowManagerGlobal.java:461`; it died and restarted as PID `29833` one second later. | Occurred during the transition into `home_main`. The runner did not invalidate this scenario because its first lifecycle sample was at 08:09:23 with PID `29833` and no previous PID. This is the reproduced window fatal and a missed lifecycle transition. |
| 11:32:19 | PID `29833` exited with Android `ApplicationExitInfo` reason `APP CRASH(EXCEPTION)`. Android did not retain the exception text in the available crash buffer or DropBox. PID `20060` was observed at 11:32:29.887. | `life_plant_care_plugin` was invalidated during entry with `INCOMPLETE_ERROR/talkback_restarted`; attempted steps 0. |
| 11:35:01 | PID `20060` crashed with `WindowManager$BadTokenException: Unable to add window -- token … is not valid; is your activity running?` at `ViewRootImpl.java:2025`; it died and restarted as PID `24156`. | `life_clothing_care_plugin` was invalidated at step 4 with `INCOMPLETE_ERROR/talkback_restarted`. |

Initial/final PID: **18593 / 24156**. Runner-detected restart aborts: **2**. `WINDOW_FATAL_REPRODUCED=YES`; acceptance-required `TALKBACK_PID_CHANGE_COUNT=0` was not met. The first failure is a recurrence of the prior TalkBack window-count fatal; the later stale-token crash is an additional fatal. The 11:32 crash is confirmed as an app crash, but its exception cause remains unknown.

Lifecycle sampling produced 2,413 records, 2,411 with an available snapshot and PID. Available snapshots ranged from 20 to 23 total windows and 0 to 2 TalkBack-owned windows. No monotonic growth was observed in sampled counts. `SearchScreenOverlay` was detected as one hidden/non-visible window in 2,328 samples; it was absent in 85 and was never reported visible. The maximum sampled TalkBack-owned count was 2. These samples do not establish the cause of `window count is over max!!`; that fatal is independent direct evidence. The two snapshots without PID or window data were at 11:32:18.795 and 11:32:19.173, surrounding the second crash.

Evidence: `talkback_window_fatal_rca.txt`, the `TALKBACK_WINDOW` records and restart aborts in `runner.log`, and device `dumpsys activity exit-info` captured three in-run TalkBack app-crash exits (PIDs `18593`, `29833`, `20060`).

## Entry, starvation, and known product behavior

- `tab_or_anchor_failed` and anchor-abort log events: **0**. The prior anchor-abort regression was not reproduced.
- False `possible_crash` / crash-like classifications: **0**. The three TalkBack process crashes are real TalkBack crashes, not SmartThings app crashes.
- Previous P0 entries Food, Air Care, Family Care, Find, and Music Sync all entered and attempted traversal. No `INCOMPLETE_ERROR` occurred in those five scenarios.
- Air Care special-state check: `detected=false`; traversal started with **11 attempted steps**. The `설정하기` descriptive-text false positive was not reproduced.
- The five roots all entered: `home_main` 23 attempts, `devices_main` 64, `life_main` 31, `routines_main` 23, and `menu_main` 66. Their terminal planner summaries each reported `unattempted_active_unseen=0`; no valid planner-visible unattempted-candidate starvation was found. Active unseen items remained at termination, but were not left unattempted while the runner looped on attempted items.
- Home Safe `EMPTY_VISIBLE` occurred twice (steps 3 and 4). Both remain `FAIL` / `SHADOW_FAIL`, classified as the known product accessibility defect. Neither was suppressed or downgraded.

## Target focus and transport evidence

- Runner log: **191** `[TARGET_FOCUS][attempt]` markers.
- Parsed target-decision outcomes in `TARGET_ACTION_RESULT`: **129 `TARGET_MATCHED`, 56 `TARGET_NOT_FOUND`, 5 `AMBIGUOUS_TARGET`** (190 classified outcomes).
- Source workbook `raw` sheet: **166** target-status rows (**125 matched, 36 not found, 5 ambiguous**). The workbook therefore does not represent 24 classified outcomes present in the runner result log; the 191 attempt markers and 190 classified outcomes also do not fully reconcile. Treat the log as the complete observed attempt evidence until this reporting gap is explained.
- Target-result parser errors: **0** for `FOCUS_RESULT` and **0** for `TARGET_ACTION_RESULT`. Explicit `TARGET_MISMATCH` events and recorded target mismatch counts: **0**. Fallback flags in recorded target rows: **0**.
- In workbook `TARGET_NOT_FOUND` rows, 25 recorded visits and 3 already-visited outcomes have `actual_focus_accessibility_focused=true`; 3 existing-gate records also have actual accessibility focus. Five `UNAVAILABLE` outcomes have no accessibility focus and were not credited. No false visit credit was identified in those recorded rows.
- Separate non-target parser errors remain frequent: **901 `SMART_NAV_RESULT`** and **963 `EVIDENCE_EVENTS_RESULT`** parse errors, often at the approximately 4 KB log line boundary. These are distinct from the target-focus result parsers above and need review; optional evidence-event snapshots can be absent.

### Dynamic timestamps

`device_home_camera_plugin` recorded eight timestamp `TARGET_NOT_FOUND` outcomes. At step 98 the selected time was `21:00`, while actual A11y focus was `20:30`; the row records the actual focused `time_text` node and does not credit the requested `21:00` instance. Other timestamp misses either landed on an actual focused time node, an already visited instance, or an unavailable non-time node. The scenario continued to step 100 and terminated on `safety_limit`, not a target-miss termination.

`device_camera_plugin` had two timestamp misses (`07:00` and `03:30`) and continued through step 72, ending `repeat_no_progress`. The 03:30 attempt's actual focus was a location label and was marked unavailable. The run does not show that timestamp disappearance alone caused either terminal condition; these remain dynamic-target limitations to document.

## Workbook and review consistency

Source workbook result rows: **547**.

| Result | Count |
|---|---:|
| PASS | 481 |
| WARN | 63 |
| FAIL | 2 |
| SHADOW | 1 |

Both workbook FAILs are the two known Home Safe `EMPTY_VISIBLE` defects. Shadow verdict totals are 507 pass, 3 review, 34 warn, and 2 fail.

The generated artifacts disagree on automation diagnostics:

- `summary.json` has 18 `automation_diagnostics`; `quality_issues_contract.automation_diagnostic_count=18` and `classification_unavailable_count=10`.
- `review_generation.json` reports `automation_diagnostic_count=0`.
- The generated review workbook `Summary` reports QA Review Count 2 and Automation Diagnostic Count 0; its `Automation Diagnostic` sheet has 0 rows.

The source summary therefore disagrees with the review output on the canonical diagnostic count. This fails the required summary/review consistency gate. The source summary's separate quality buckets are `clean=527`, `review=16`, `fail=4`, `issue=0`; these are not the raw result-sheet PASS/WARN/FAIL/SHADOW totals above.

The baseline candidate `candidate_01bbad4c531d99ccc2f7913f.baseline_candidate.json` is `NOT_ELIGIBLE`. Its validator reports 23 PASS, 1 WARNING, and 1 FAIL: `working_tree_clean`. Provenance confirms 0 staged and 0 modified tracked files, but the candidate validator treats preserved untracked outputs as a dirty tree. The provenance records 2,185 status paths, including 1,697 untracked paths under output directories. The candidate's failure is a validator/worktree gate; it is not evidence of a tracked source change.

## Comparison with prior runs

| Metric | Accepted Phase 0 run `20261004_203348` | This run |
|---|---:|---:|
| Terminal scenarios | 32/32 | 32/32 |
| Runtime | 2:28:03 | 3:48:50 |
| Global Nav | 5/5 | 5/5 |
| Workbook rows | 429 | 547 |
| PASS / WARN / FAIL / SHADOW | 366 / 61 / 1 / 1 | 481 / 63 / 2 / 1 |

Compared with rejected run `batch_20261006_011302`, anchor aborts and false `possible_crash` classification were not reproduced, and target-focus result parsing had no errors. The TalkBack fatal/restart blocker recurred, with three crash exits and two explicit scenario invalidations. The diagnostic-count mismatch remains, and candidate eligibility still fails its worktree check. The two Home Safe product failures remain visible as required. Clothing Care could not be assessed against its prior representative-context limitation because the scenario was invalidated by a TalkBack restart.

## Regression classification and next fix scope

**Severity: P0 acceptance blocker.** This run cannot serve as a new Korean baseline.

Likely ownership and the smallest next investigation:

1. **TalkBack window lifecycle:** Samsung TalkBack/window-overlay behavior owns the crashes evidenced inside `com.samsung.android.accessibility.talkback`; QA runner lifecycle ownership includes the missed first PID transition. Seed the run monitor from the preflight PID, capture Android crash events from batch start, and retain the 11:32 exception trace on the next authorized diagnostic run. Keep restart invalidation enabled.
2. **Summary/review aggregation:** reconcile the 18 source diagnostics with the review workbook's 0 diagnostics under one documented `quality_issues` contract; verify the output review workbook and candidate metadata report the same count.
3. **Candidate eligibility:** run review generation in a clean isolated checkout with output paths outside the worktree, preserving existing artifacts. Do not weaken the validator's clean-tree rule.
4. **Target attempt ledger:** reconcile all 191 attempt markers, 190 classified target outcomes, and 166 workbook status rows. Persist or explicitly classify every attempted target outcome so counts can be compared without treating omitted result rows as successful visits.
5. **Non-target result transport:** investigate the repeated approximately 4 KB `SMART_NAV_RESULT` and optional `EVIDENCE_EVENTS_RESULT` parse errors and verify legacy fallback behavior.

## Final acceptance fields

```text
FINAL_ACCEPTANCE_VERDICT=REJECT_NEW_BASELINE
RUN_ID=batch_20261007_080753
DEVICE=SM-F741N / R3CX40QFDBP
LOCALE=ko-KR
START_TIME=2026-10-07 08:07:54 KST
END_TIME=2026-10-07 11:56:44 KST
RUNTIME=03:48:50
SOURCE_BRANCH=docs/korean-full-run-acceptance-20261007
SOURCE_HEAD=df9e8b86df3df06c2d5dce1b107b2aec60b86094
ORIGIN_MAIN=df9e8b86df3df06c2d5dce1b107b2aec60b86094
HEAD_ORIGIN_MAIN_MATCH=YES
TRACKED_WORKTREE_CLEAN=YES at launch; no tracked source changes during run
WINDOW_MONITORING_ENABLED=YES
EXPECTED_SCENARIOS=32
OBSERVED_SCENARIOS=32
TERMINAL_SCENARIOS=32
MISSING_SCENARIOS=0
EXTRA_SCENARIOS=0
DUPLICATE_SCENARIOS=0
GLOBAL_NAV_RESULT=5/5
SCENARIO_COMPLETED=14
SCENARIO_NO_PROGRESS=15
SCENARIO_SAFETY_LIMIT=1
SCENARIO_ERROR=2
ROOT_HOME_RESULT=23 attempted; 16 unique / 44 candidates; INCOMPLETE_NO_PROGRESS
ROOT_DEVICES_RESULT=64 attempted; 43 unique / 85 candidates; INCOMPLETE_NO_PROGRESS
ROOT_LIFE_RESULT=31 attempted; 17 unique / 35 candidates; INCOMPLETE_NO_PROGRESS
ROOT_ROUTINES_RESULT=23 attempted; 18 unique / 40 candidates; INCOMPLETE_NO_PROGRESS
ROOT_MENU_RESULT=66 attempted; 33 unique / 57 candidates; INCOMPLETE_NO_PROGRESS
P0_ENTRY_REGRESSION=NO
FALSE_POSSIBLE_CRASH_REPRODUCED=NO
AIR_CARE_FALSE_SPECIAL_STATE_REPRODUCED=NO
TARGET_ATTEMPTS=191 runner markers; 166 workbook status rows
TARGET_MATCHED=129 result log / 125 workbook
TARGET_NOT_FOUND=56 result log / 36 workbook
TARGET_PARSE_ERROR=0 FOCUS_RESULT; 0 TARGET_ACTION_RESULT
TARGET_MISMATCH=0
TARGET_FALLBACK=0 recorded workbook rows
STARVATION_REGRESSION=NO; roots report unattempted_active_unseen=0
WINDOW_FATAL_REPRODUCED=YES; 3 TalkBack app-crash exits
TALKBACK_PID_START=18593
TALKBACK_PID_END=24156
TALKBACK_PID_CHANGE_COUNT=3
MAX_TOTAL_WINDOW_COUNT=23
MAX_TALKBACK_WINDOW_COUNT=2
PERSISTENT_TALKBACK_WINDOW_GROWTH=NOT OBSERVED IN SAMPLED COUNTS
SEARCH_SCREEN_OVERLAY_BEHAVIOR=1 hidden/non-visible window in 2,328 samples; never visible
SUMMARY_DIAGNOSTIC_COUNT=18
REVIEW_DIAGNOSTIC_COUNT=0
DIAGNOSTIC_COUNTS_MATCH=NO
WORKBOOK_PASS=481
WORKBOOK_WARN=63
WORKBOOK_FAIL=2
WORKBOOK_SHADOW=1
HOME_SAFE_PRODUCT_DEFECT_COUNT=2
NEW_AUTOMATION_WORKBOOK_FAIL_COUNT=0; lifecycle/evidence blockers remain outside result-row FAILs
UNRESOLVED_FAIL_COUNT=2 scenario INCOMPLETE_ERROR results
CLOTHING_CARE_CLASSIFICATION=INCOMPLETE_ERROR due TalkBack restart; prior limitation not assessable
HOME_CAMERA_DYNAMIC_TARGET_CLASSIFICATION=timestamp misses; actual focus retained; no target-miss termination
PRIOR_ACCEPTED_BASELINE_COMPARISON=32/32, 2:28:03, Global Nav 5/5, 366/61/1/1; current 32/32, 3:48:50, 5/5, 481/63/2/1
REJECTED_20261006_BLOCKERS_RESOLVED=PARTIAL; anchor/false-crash/target-parser gates pass; lifecycle and diagnostic mismatch remain
REJECTION_DOCUMENT=docs/design/talkback-korean-full-run-rejection-20261007.md
DOC_INDEX_UPDATED=NO
COMMIT=NOT CREATED
BRANCH_PUSH=NOT PERFORMED
MAIN_MERGE=NOT PERFORMED
MAIN_PUSH=NOT PERFORMED
FINAL_HEAD=df9e8b86df3df06c2d5dce1b107b2aec60b86094
HEAD_ORIGIN_MAIN_MATCH_FINAL=YES
NEXT_STEP=RCA the TalkBack crashes and reconcile lifecycle, target-result, review-count, and candidate worktree gates before another acceptance run is authorized
```

