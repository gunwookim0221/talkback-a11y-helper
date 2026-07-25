# Run-local Review Checklist reporting

## Contract

Each completed device Run has its own optional `<source-stem>.review.generated.xlsx`.
The original `talkback_compare_*.xlsx` stays unchanged and remains the source of truth for
raw evidence, developer debugging, and audit. Review Checklist is a **QA Manual Verification**
surface: it lets a QA reviewer find the intended Focus target on a real device in minutes and
record what TalkBack actually says. It is not a developer-debug report and does not change
Comparator, Candidate, Baseline, or approval behavior.

Each `final_result=FAIL` is classified by its final meaning, not only by the mismatch label.
Human-verifiable speech/text cases such as `EMPTY_VISIBLE`, `EMPTY_SPEECH`, `TEXT_MISMATCH`,
`SPEECH_MISMATCH`, `NEW_FOCUSABLE_SPEECH_ONLY`, and `speech_visible_diverged` belong in QA
Manual Review. Automation-only outcomes such as `terminal_not_handled`,
`repeat_no_progress`, `move_failed`, `target_not_found`, recovery, identity, coverage,
traversal, platform, and environment states belong in Automation Diagnostic. When an
automation-only terminal reason accompanies a human mismatch label, the terminal reason wins:
the reviewer cannot resolve that run-state failure by listening to TalkBack. PASS rows are
excluded. WARN rows are reduced to one deterministic representative per scenario and warning
type in `Additional Review`.

## Workbook layout

## Full-screen evidence contract

At the same observation point that creates a focus crop, the collector stores an additive full-screen
PNG under `screens/`. Its deterministic name includes scenario, context, observation step, and a stable
correlation suffix. The row records the full-screen path, pixel dimensions, capture timestamp, and
correlation ID alongside the existing crop path, focus bounds, and logical display metadata. Full-screen
capture is enabled by default (`TB_ENABLE_FULL_SCREEN_EVIDENCE=1`) because FAIL/WARN classification is
post-observation; it can be disabled for constrained diagnostic runs. A typical 1080x2340 PNG is roughly
0.5–2 MB per unique observation, so a 50-step Run commonly adds 25–100 MB. Capture failure is isolated:
the traversal continues with structured empty artifact fields and any incomplete PNG is removed.

Review annotation scales Android logical bounds to the actual PNG pixel dimensions, clamps out-of-range
coordinates, and draws a thick rectangle, small center cross, and text label on a copy only. The original
full screenshot is unchanged. Review evidence priority is annotated full screen, raw full screen, legacy
crop, then `Full screenshot not captured for this run`. A legacy Run is never reconstructed from crops.
The current observation schema does not yet emit a stable rotation value, so this release assumes the
logical display orientation matches the captured PNG orientation; rotation-aware transform is deferred
until that metadata is available rather than guessing an unsafe coordinate system.

Generation is non-destructive by default: an existing output is preserved. `--force-regenerate` may
replace only the default unreviewed `.review.generated.xlsx`; any workbook with reviewer input and every
reviewed/custom output stays protected. Writes use a temporary workbook followed by replace, and failed
writes remove the temporary file.

## Automatic generation

`BatchRunManager` invokes the same Review Checklist service after a Full batch reaches `finished` and
after Candidate post-processing. The services are independent: Candidate eligibility does not decide
whether a readable Full Run receives a Review workbook, and a Review failure never changes device/batch
status or Candidate output. Each Run root receives `review_generation.json` with bounded lifecycle events,
source/output digests, counts, and a bounded failure reason. Smoke and non-finished batches are skipped.

- `Review Checklist`: the **only QA Manual Review surface**. It contains Review ID, Scenario,
  Focus Target, approximate screen position, a concrete TalkBack verification instruction,
  annotated crop thumbnail, Speech Status, Visible Text, and validator decision/comment.
  The original observation Step is retained only as a hidden final column and is never a
  reproduction instruction. Developer evidence and engine metadata do not appear on this sheet.
- `Automation Diagnostic`: developer-facing sheet for FAIL rows whose final meaning is an
  automation-engine diagnostic. It records Scenario, Issue, Reason, Step, traversal/recovery/
  terminal state, resource, bounds, evidence, and notes. These rows never receive QA validator
  decisions because a listener on the device cannot determine the engine failure.
- `Focus Target`: uses `contentDescription`, visible text, normalized resource-ID meaning, crop OCR,
  parent node, nearest representative, then `Unknown`. Resource IDs are not shown raw: prefixes such
  as `btn_`, `iv_`, `tv_`, `ll_`, `rv_`, `cl_`, `shm_`, and `device_` are removed and snake_case/
  camelCase words are title-normalized. For example, `shm_setting_button` becomes `Settings Button`,
  `home_monitor_setting` becomes `Home Monitor Settings`, and `btn_menu` becomes `Menu`.
- `Speech Status` separates the QA meaning of an empty automation speech field. `Speech Observed`
  means the helper captured meaningful speech. `Role-only Speech` means the captured value is only a
  role such as `Button`, `Checkbox`, or `Switch`. `Speech Missing` means a platform focus or
  announcement event was observable but both meaningful node metadata and speech were absent; QA must
  verify whether the app is genuinely silent. `Speech Unobserved` means the evidence contains a focused
  snapshot with no metadata but no focus/announcement event, so the helper could not observe the actual
  TalkBack utterance. `Unknown` is the safe legacy fallback when evidence provenance is absent or cannot
  be matched. The status is Review Generator interpretation only; it never changes an observation,
  Comparator result, Verdict, Baseline, or approval decision.
- Review instructions are status-specific: `Speech Unobserved` asks QA to listen at the shown focus
  location, `Speech Missing` asks QA to determine whether the app is genuinely silent, and `Role-only
  Speech` asks QA to verify that only the role is spoken. This prevents an unobserved semantic utterance
  from appearing equivalent to an app accessibility defect.
- `Approximate Position`: derives a 3x3 human-readable position with relative coordinates, such
  as `Top Right (83%, 17%)`, from focus bounds and Run display dimensions. Exact bounds and center
  coordinates remain developer metadata in `Automation Diagnostic`.
- `Screenshot`: shows an approximately 200px annotated crop thumbnail. The red focus marker is a
  generated copy under `review_annotations/`; the original crop is unchanged and linked from the
  cell as `Open original screenshot`. When unavailable the cell says `No screenshot captured`.
  Evidence JSONL is never presented as a screenshot.
- `Validator Checklist`: Excel dropdown values are `미검토`, `정상 발화`, `실제 접근성 문제`,
  `False Positive`, `재현 불가`, and `추가 조사 필요`.
- `Summary`: Run identity, environment, raw PASS/WARN/FAIL counts, `QA Review Count`,
  `Automation Diagnostic Count`, `Scenario Count`, estimated QA review time, scenario FAIL distribution,
  focus-position distribution, Unknown target count, screenshot-unavailable count,
  Resource-derived Target count, per-status Speech Status counts,
  formula-based completion, and overall status.
- `Additional Review`: representative WARN data, counts, terminal/result, and whether the
  scenario also contains a real FAIL.
- `Audit Sample`: created only when `--pass-sample-rate` is greater than zero. Selection is
  deterministic from the Run ID and row identity; default sampling is disabled.

## Status rules

`NOT_STARTED` is represented by all items remaining `미검토`; an edited workbook is
`IN_PROGRESS` until every item has a decision. `실제 접근성 문제` produces
`COMPLETED_WITH_ISSUES`, while `추가 조사 필요` produces `RETEST_REQUIRED`. These are review
tracking statuses, not Comparator verdicts or approval states.

## Historical Runs and multi-Run summary

Use the CLI `generate` command for a completed Run containing the source Excel. Use the CLI
`summary` command when an operator needs one progress view across OS/environment Runs. The
combined workbook reads each detail workbook's Summary and links to each detail file; it never
merges detailed rows across Runs.
