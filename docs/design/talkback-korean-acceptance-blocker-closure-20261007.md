# Korean acceptance blocker closure — 2026-10-07

**Verdict: PARTIAL_CLOSURE_BADTOKEN_TRIGGER_FIXED_LONG_STRESS_NOT_PROVEN.**

**Next Korean Full32 readiness: NO.** The targeted stress reproduced a TalkBack BadToken fatal and stopped early. A narrow, evidence-backed audit-capture trigger fix passed deterministic tests, full regression, and one short Clothing Care revalidation. This does not establish 60–120 minute stability or fix the historical window-count-over-max crash. No baseline was approved.

## Baseline and scope

Started from `df9e8b86df3df06c2d5dce1b107b2aec60b86094`, equal to fetched `origin/main`, on `fix/korean-acceptance-blocker-closure`. Historical `out/`, `tests/out/`, and `qa_frontend_runs/` were preserved. No Full32, English device scenarios, locale contract changes, Phase 4 changes, hard cap changes, starvation policy changes, Home Safe suppression, timestamp semantic changes, or candidate ranking changes were authorized or performed.

The rejected `batch_20261007_080753` remains rejected. Repairing its reporting does not make its three TalkBack crashes acceptable evidence.

## Phase A: restart continuity

Frontend surface preflight now reads the TalkBack PID before launching SmartThings. `RunSpec` passes that exact PID to the subprocess; core preflight keeps it instead of replacing it with a later PID. Direct CLI runs capture their seed before foreground/recovery actions. The first lifecycle recorder starts with this PID, compares the first runtime sample, and uses the existing entry/traversal invalidation path (`INCOMPLETE_ERROR / talkback_restarted`). State is carried across scenarios.

A temporary unavailable PID remains unavailable evidence. Returning with the same PID is not classified as a restart. A different PID after an unavailable interval is a restart. After the 256 full snapshot cap, existing action capture points still issue lightweight PID/service probes and now persist those bounded records, including unavailable/error evidence. No periodic full-window polling was added.

Batch crash capture already started before frontend launch preflight. It now detects TalkBack AndroidRuntime fatal blocks separately under `talkback_monitor/crashes/`, so they cannot become OneConnect crash positives. ApplicationExitInfo is captured at monitor start and end. Streaming raw logcat is flushed as it arrives; the long stress also watches process changes and relevant live fatal blocks.

Deterministic tests cover equal/different first PID, frontend-to-core seed preservation, immediate entry invalidation, traversal interruption without row credit, post-cap PID detection, transient unavailability, and separate TalkBack crash attribution.

## Phase B: non-target transport

The preserved raw logcat establishes a single-line truncation cause for both channels:

| Producer/channel | Valid historical records | Invalid records | Invalid line size |
| --- | ---: | ---: | --- |
| SMART_NAV_RESULT | 925 | 901 | 4,101–4,103 UTF-8 bytes |
| EVIDENCE_EVENTS_RESULT | 4 | 963 | 4,101–4,103 UTF-8 bytes |

SMART_NAV had two producer stages: a small service response followed by a receiver response enriched with evidence. EVIDENCE_EVENTS was a receiver snapshot-and-clear response. Their invalid payloads end inside JSON strings/objects at the logcat boundary (SMART payloads around 4,037 bytes; evidence snapshots around 4,031 bytes), before Python receives them.

The receiver now emits one final SMART response after evidence attachment, and emits evidence snapshots through the existing `A11yResultTransport`. The premature service result is removed to prevent the collector accepting incomplete semantic evidence or duplicate chunk sequences. Failure responses use the same transport.

All channels use the same request ID, indexed 1,500-byte UTF-8 chunks, Base64, total count, SHA256, bounded reader, complete reassembly, and legacy small-line format. The reader rejects missing/duplicate chunks, wrong digest, invalid encoding/bounds, and oversized payloads; chunk request IDs are matched exactly. No partial JSON is accepted. Tests cover small, ~4 KB, >4 KB, 8–16 KB, Korean Unicode, escaping, out-of-order, missing/duplicate, digest, and legacy cases.

## Phase C: diagnostics and target attempts

The historical 18→0 diagnostic loss occurred because summary classification includes WARN/SHADOW and classification-unavailable signals, while the review source reader selected only FAIL result rows. Review generation now projects the actual canonical `summary.json.automation_diagnostics` population, including its diagnostic content and classification reasons. It validates declared count against the population; it does not copy a count into an empty sheet.

Review source counts, generated workbook Summary, and diagnostic sheet rows now agree. A population SHA256 also detects a stale generated workbook when content changes but count does not. Unreviewed stale generated files can be regenerated; reviewed files are preserved and a consistency failure is reported. The SHA row is appended after the existing summary formula rows, keeping their references intact. Batch summary extraction excludes generated review/QA workbooks so they cannot be reingested as raw result evidence.

Each targeted focus attempt gets a run-local deterministic `target_000001` identity before its log marker and command. Its descriptor and initial `NO_RESULT` state are saved immediately in `<run>.target_attempt_ledger.json`, then resolved to MATCHED, NOT_FOUND, AMBIGUOUS_TARGET, UNAVAILABLE, INTERRUPTED_TALKBACK_RESTART, TRANSPORT_ERROR, NO_RESULT, or OTHER_EXPLICIT_STATE. Helper request ID/status and restart evidence are retained. Duplicate results are explicit errors. A later same-step restart overrides the attempt state while preserving the pre-interruption state.

The marker includes attempt ID; parsed outcome is correlated through request ID; a persisted raw workbook row carries `target_focus_attempt_id`. Final reconciliation lists each corresponding raw workbook row or an explicit `NO_NORMAL_WORKBOOK_ROW` omission. Normal result-sheet omissions therefore do not remove attempts from acceptance evidence. Counts of attempts, entries, outcomes, workbook rows, and omitted attempts are separate metrics.

## Phase D: clean source and preserved replay

The smallest workflow uses a detached clean worktree, existing Python dependencies, and absolute artifact/output paths outside that worktree. This run used:

- Runtime source: `C:\Users\smani\AppData\Local\Temp\talkback_korean_closure_0df39737\source` at `b38f767cd8cda0bce1d5bee198fd2bd20d846bb1`.
- Final reporting source: `C:\Users\smani\AppData\Local\Temp\talkback_korean_closure_0df39737\reporting` at `401ec0ad7d9b6f76258ddbfda08d6175f770d1cb`. The reporting commit was amended during stress to move the new digest metric after the fixed Summary formula rows and add its regression assertions. This changes generated review layout only; stress runtime code and traversal behavior are identical.
- Narrow trigger-fix source: `C:\Users\smani\AppData\Local\Temp\talkback_korean_closure_0df39737\window_fix` at `4989547`. Short device revalidation and stopped-run evidence replay used this clean checkout with external outputs.
- Outputs: `qa_frontend_runs/acceptance_blocker_closure_20261007/` in the original workspace, outside the detached source.
- Historical inputs: `qa_frontend_runs/batch_20261007_080753/device_SM-F741N_R3CX40QFDBP/`.

Workflow validation reads the original run with `build_baseline_candidate(original, write=False, integrate=False)`, then saves the returned candidate externally. Review generation operates on an external copy. The source checkout remains clean before and after generation, and SHA256 checks verify the original run inputs and parent batch summary are unchanged. The copied review reports 18 summary diagnostics, 18 review-generation diagnostics, and 18 workbook diagnostic rows.

The original run captured dirty source provenance. A clean generation checkout cannot retroactively change that fact: the replay candidate remains `NOT_ELIGIBLE`, with its original `working_tree_clean=FAIL`. No validator changes, provenance rewriting, baseline approval, or original evidence deletion were used. For future eligibility, the actual device run must start from the clean worktree and write outputs externally; clean generation alone cannot repair a historical dirty run.

Reproduction procedure (use a new task-specific temporary path and an output path outside it):

```powershell
git worktree add --detach "$env:TEMP\talkback-clean-source" <verified-commit>
$env:PYTHONPATH = "$env:TEMP\talkback-clean-source"
# Invoke the runtime from this clean source with an absolute external --output-dir.
# Set the frontend RUN_LOG_DIR to an absolute external directory for batch runs.
# Capture source git status and environment provenance before launch.
# For historical replay: build_baseline_candidate(input, write=False, integrate=False).
# Write its returned document outside source; generate review only on a copy.
```

Final workflow proof: `qa_frontend_runs/acceptance_blocker_closure_20261007/workflow_validation_final/workflow_validation.json`. The reproducible inspection script is retained alongside the run artifacts as `validate_clean_workflow.py`.

## Phase E: targeted workload

Target: 60–120 minutes, maximum 120 minutes. Selected scenario set: `life_main`, `life_family_care_plugin`, `life_plant_care_plugin`, `life_clothing_care_plugin`, `life_home_monitor_plugin`, `device_home_camera_plugin`. The runner retains its registry execution order. Each cycle selects only these six; it uses existing full traversal limits without overrides, Korean current locale, clean app launch, identity/evidence/profiler enabled, and `TALKBACK_WINDOW_LIFECYCLE=1`.

Stress started at 2026-10-07 21:52:03 KST, TalkBack PID `24156`, from the detached code checkout. A continuous observer retains lifecycle logcat, 60 seconds before a fatal when available, and the restart tail. Existing per-action lifecycle samples and 15-second watchdog PID probes provide complementary continuity evidence. ApplicationExitInfo is captured at the controls and checked during the workload. A fatal/PID transition stops automation; no later scenarios are authorized after sufficient failure evidence.

### Stress outcome and stop

The stress batch was `batch_20261007_215202`. Active batch time was **43:16** (21:52:03–22:35:19 KST); total observer duration including the passive restart tail was **43:32.5**. At 22:35:13.475, TalkBack PID `24156` died with `WindowManager$BadTokenException`; Android recorded a new `APP CRASH(EXCEPTION)` exit at 22:35:13.478 and restarted TalkBack as PID `21432` at 22:35:14.517. The batch was stopped and no second long-stress cycle ran. Home Monitor was not reached.

| Scenario actually executed | Attempted steps | Captured terminal evidence |
| --- | ---: | --- |
| device_home_camera_plugin | 100 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_main | 38 | INCOMPLETE_NO_PROGRESS / content_no_progress |
| life_family_care_plugin | 35 | COMPLETED / scroll_exhausted |
| life_plant_care_plugin | 8 | COMPLETED / plugin_boundary_global_nav |
| life_clothing_care_plugin | 3 completed steps; step 4 restart probe | Forced stop during interruption; no fabricated terminal traversal summary |
| life_home_monitor_plugin | 0 | Not run after sufficient failure evidence |

The runtime recorded the restart at step 4 before SMART_NEXT, but the initial implementation still sent that action before the existing post-action abort check. The external stop then terminated the process before normal `finally` reconciliation. These are safety/evidence gaps, not evidence of valid continuation or a successful scenario. The narrow follow-up fix blocks the action when its before probe sees a restart and reconciles durable ledgers from persisted raw workbook rows after subprocess termination.

The temporary first observer also treated a changed global ApplicationExitInfo persistence timestamp as a failure dictionary entry. Semantic comparison proved all 16 historical exit records unchanged at that point. This metadata entry delayed its fatal callback, although the independent window guard and runtime PID detector captured the actual failure. The guard's process search found no matching worker; it did not terminate a process. The final stop was the batch controller/runtime restart path. The short revalidation observer compares actual exit records and directly requests a batch stop for a live fatal/window exception. The original observer outputs and this limitation are preserved; they are not reclassified as a clean stress pass.

### BadToken sequence and ownership

| KST | Direct runtime evidence |
| --- | --- |
| 22:35:10.767 | Automation invokes `uiautomator dump /sdcard/phase0b_after_scroll.xml` solely to save supplementary XML. |
| 22:35:11.026–11.028 | UiAutomation registers with `flags=0x0`; Android removes the existing hidden Search window via accessibility service connection removal and `WindowManagerService.removeWindowToken`. |
| 22:35:12.100 | Automation connection restores the user/service context. |
| 22:35:13.177 | Automation starts the next supplementary `uiautomator dump /sdcard/window_dump_v4_1.xml`. |
| 22:35:13.421 | TalkBack reports `System bound to service`. |
| 22:35:13.443 | Second UiAutomation registration with `flags=0x0`. |
| 22:35:13.447 | TalkBack calls SearchScreenOverlay addView from `createUIElements` / `onServiceConnected`. |
| 22:35:13.455 | WindowManager rejects an accessibility overlay with an unknown token. |
| 22:35:13.470–13.478 | Failed-add cleanup, BadToken fatal, and new Android crash exit. |

UiAutomation suppresses accessibility services by default; Android's non-suppression flag is `FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES`. This explains why registration can remove service overlay tokens. The device's direct logs show the suppression/removal and simultaneous reconnect/addView, rather than relying on the API contract alone. See [Android UiAutomation API](https://developer.android.com/reference/android/app/UiAutomation) and [AOSP UiAutomationManager](https://android.googlesource.com/platform/frameworks/base/+/6c95f48d4b13/services/accessibility/java/com/android/server/accessibility/UiAutomationManager.java).

Classification: **AUTOMATION_TRIGGERED for the observed supplementary-dump token race**, with high confidence in this sequence. TalkBack's asynchronous infrastructure recreation also participates. No owning SmartThings Activity destruction appears in the preceding 60 seconds; foreground remains `WebPluginActivity`. This does not establish the cause of the historical window-count-over-max crash or the historical exception with no retained text.

The preceding 60 seconds contain three UIAutomator dump commands/registrations, two TalkBack service binds, two SearchOverlay addView calls, and two server Search-window removals. Before the fatal, the old PID has 62 bind events and 62 direct SearchOverlay addView attempts; the last attempt fails. Bind-to-addView delays are 15–35 ms. Across 553 lifecycle records, including 44 lightweight post-cap probes, available full snapshots reach at most 23 total and 2 TalkBack windows. Each ten-minute bin remains bounded; no persistent sampled owned-window growth is observed. Bounded samples do not disprove the fatal or establish absence of a leak.

### Narrow fix and short revalidation

`4989547` removes the two supplementary UIAutomation XML calls. Scroll XML is serialized from the already observed post-scroll Helper nodes. V4 audit XML is serialized from the existing row snapshot or saved post-scroll snapshot. No additional Helper/device read is introduced. XML explicitly carries `source=a11y_helper` and an observed-snapshot contract; it is not presented as independent UIAutomator evidence. Missing data remains an explicit capture error. Actual traversal decisions, caps, candidate identities, ranking, timestamp semantics, and starvation policy are unchanged.

Before-action restart guards now prevent SMART_NEXT/local-tab activation, scroll, and targeted-focus commands after their lifecycle probe has observed a PID transition. Frontend terminal summary generation reconciles saved target ledgers against persisted raw rows, preserving omitted attempts after forced termination. A stopped run cannot acquire workbook credit from log-only evidence.

The initial fresh-Helper-read implementation failed one Food handoff regression because it consumed the next snapshot. It was corrected to use existing observed data only; the focused test and final full suite then passed. No failing intermediate version is claimed as the final result.

Short revalidation: `batch_20261007_224944`, only `life_clothing_care_plugin`, **3:51.6**. It attempted 11 steps and ended with existing `INCOMPLETE_NO_PROGRESS / repeat_no_progress`, actual visited 8/12 confirmed candidates. PID `21432` remained unchanged, no new exit record, fatal, BadToken, anchor abort, or result parser error. Three audit XML files identify their Helper provenance. Neither offending command nor any UIAutomator dump after traversal started appears in raw logcat. Twelve entry-stage service binds/addView calls remain from other existing fallback paths; those paths and long-duration stability are residual risks.

### Transport and evidence reconciliation

| Population | SMART chunked valid | EVIDENCE chunked valid | TARGET chunked valid | Parser errors / duplicate / digest errors |
| --- | ---: | ---: | ---: | --- |
| Failed stress | 197/197 | 199/199 | 59/59 | 0 / 0 / 0 |
| Short revalidation | 11/11 | 14/14 | 4/4 | 0 / 0 / 0 |

Maximum stress payloads: SMART 39,343 bytes / 27 chunks; EVIDENCE 55,375 bytes / 37 chunks. Maximum chunk logcat line is 2,189 bytes. Both non-target channels successfully carry Korean payloads beyond the previous 4 KB limit.

Stopped-run replay preserves every original captured input hash. Its canonical ledger reconciles **56 attempts = 56 classified outcomes = 56 entries**, **49 persisted workbook target rows**, and **7 explicit omissions**. States are 39 MATCHED / 17 NOT_FOUND. Normal `finally` was interrupted in the original run, so its ledger stays as captured; the external replay proves the new terminal reconciliation function without rewriting original evidence. Short validation adds one attempt, one outcome, one ledger entry, one workbook row, and zero omissions. Aggregate new device evidence: **57 / 57 / 57 / 50 rows / 7 omissions**.

Diagnostics are separate populations: preserved rejected-run replay **18 summary = 18 review-generation = 18 workbook rows**; stopped-run manual evidence review **4 = 4** (automatic review remains explicitly skipped because the batch stopped); fresh completed short run **0 summary = 0 review-generation = 0 workbook rows**. The manual stopped review is not labeled automatic acceptance output. Both fresh candidate checks report `working_tree_clean=PASS`, and candidates remain `NOT_ELIGIBLE`. Historical dirty provenance remains FAIL/NOT_ELIGIBLE; the validator and baseline were unchanged.

Artifact receipts under `qa_frontend_runs/acceptance_blocker_closure_20261007/`:

- `long_stress/stress_result.json`, `long_stress/preceding_60_seconds_and_restart_raw_logcat.txt`, `long_stress/fatal_lifecycle_sequence.txt`, and the batch `talkback_monitor/crashes/CRASH-0001/`.
- `failure_window_analysis.json`, `chunk_transport_validation.json`.
- `workflow_validation_final/workflow_validation.json`, `stopped_run_workflow/stopped_run_audit.json`.
- `short_clothing_revalidation/short_revalidation_audit.json`, `short_clothing_revalidation/chunk_transport_validation.json`.
- `python_suite_final.log`, `python_suite_root_final.log`, `related_regression_final.log`.

## Final verification

- Focused restart/transport/reporting tests: 135 passed before the later formula-position audit.
- Related runner/reporting regression: 675 passed.
- Helper unit tests: 372 passed, zero failures/errors/skips.
- Helper `assembleDebug`: successful; the built APK was installed on `R3CX40QFDBP` before stress. Installation kept TalkBack PID `24156`; Korean locale remained `ko-KR,en-US`.
- Final full Python suite after all changes: **3,080 passed, 1 skipped** across the working-directory-correct invocations (3,078 passed, 1 skipped, 2 deselected from `tests/`; the two source-reading tests passed from repository root). CWD-dependent `.test_tmp` fixtures ran from `tests/` because the root `.test_tmp` is denied by this sandbox. An earlier literal root `python -m pytest -q tests` hit only this fixture permission problem (36 setup errors), all covered by the successful `tests/` invocation.
- Formula-position regression and ledger/restart spot checks: 23 passed.
- Narrow snapshot/restart/ledger tests: 57 passed; corrected Food handoff plus snapshot/ledger/scroll checks: 49 passed.
- Final related runner/transport/reporting regression: **677 passed**.

## Readiness and publication

`NEXT_KOREAN_FULL_RUN_READY=NO`. Required next validation is a separately scoped 60–120 minute Korean targeted stress from clean source with the audit fix and immediate fatal stop; assess remaining entry/fallback UiAutomation service churn. Do not start Full32 until that gate passes and the user explicitly authorizes it. Do not claim the historical window-count fatal fixed. Clothing Care's incomplete content coverage also remains visible under the unchanged traversal contract.

These instrumentation, transport, evidence, and narrow safety fixes meet the user-authorized merge policy even though long-stress acceptance remains unresolved. Source/test scope is 31 files, with this closure report and the unchanged prior rejection report making 33 files total. Historical run data and output folders are excluded from Git staging and preserved.

Commits:

1. `a0f347c` — Harden TalkBack restart and result transport
2. `401ec0a` — Reconcile acceptance evidence reporting
3. `4989547` — Avoid UiAutomation churn in TalkBack audit snapshots
4. Documentation commit — Document Korean long-stress closure

The final branch push/main fast-forward/main push and exact final HEAD equality are recorded after publication in `qa_frontend_runs/acceptance_blocker_closure_20261007/publication_receipt.json`. This file is the publication receipt, not an acceptance approval. Full32=NO, English=NO, Phase4 changes=NO.
