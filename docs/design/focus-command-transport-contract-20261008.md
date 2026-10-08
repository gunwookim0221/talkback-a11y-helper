# Accessibility Command Transport Contract — 2026-10-08

## Baseline and scope

Start HEAD / `origin/main`: `a9ddec864415bc9ebce76b9aa77fde6f5784c09e`, branch `fix/smart-next-transport-timeout`. The existing SMART_NEXT local fix and all historical outputs are preserved. This continuation changes transport for FOCUS_IN_BOUNDS and TARGET_FOCUS_COMMIT, which shared the same static executor and held pending broadcasts. Other command implementations are audited below. Full32, English, Phase 4, traversal limits, starvation, target identity/visit-credit rules, product defects, and window lifecycle policy remain out of scope.

## Reconstructed request `ea51b41a`

Source run: `batch_20261008_062014`, `life_family_care_plugin`, device `R3CX40QFDBP`. All times are 2026-10-08 KST.

| Stage | Timestamp / evidence |
|---|---|
| Python send / host subprocess start | Exact timestamp unavailable; unprefixed command error in runner log |
| Device shell command start observation | 06:27:29.042, independent raw log line 195404 |
| Helper receiver receipt | 06:27:29.103, PID 8500, raw line 195417 |
| Service dispatch / actual focus-work start | Not separately logged; occurs after receipt and before final result |
| ADB timeout | 30.0-second subprocess timeout; runner line 1719. Approximately 06:27:59.042 relative to the device-shell observation; host deadline is not independently timestamped |
| Focus work outcome | 06:27:59.556, PID 8500 / thread 14956, raw line 201473 |
| Result emission | 06:27:59.557, raw line 201474 |
| Python correlation | Matched same request ID at runner line 1721, after command timeout; exact host timestamp unavailable |

Receiver-to-result latency is **30.454s**. Device-shell-observation-to-result is **30.515s**. Lateness relative to a 30-second receiver boundary is 0.454s; relative to the observed shell-command boundary it is approximately 0.515s. The exact host deadline offset cannot be recovered from these logs.

The result was `TARGET_ACTION_RESULT`, `success=false`, `reason=no_content_candidate_in_bounds`, `candidateCount=0`; it was not lost or mis-correlated. The captured stdout/stderr from the original TimeoutExpired were not preserved by the generic ADB path. The actual request includes bounds `{l:0,t:106,r:180,b:286}`, `preferEmptyState=false`, `excludeTopChrome=true`, `excludeBottomNav=true`.

Classification: **BROADCAST_PENDING_TOO_LONG + RESULT_EMITTED_AFTER_ADB_TIMEOUT**. Delivery loss and result-correlation timeout are disproved by receipt and matching emission/correlation. The combined queue/service interval was slow; its exact split and individual slow node IPC were not instrumented, so SERVICE_WORK_SLOW is not assigned as an independently measured stage.

## End-to-end path and cause

Before this change: `A11yAdbClient.focus_in_bounds` → `_broadcast` → `AdbDevice.subprocess.run(timeout=30)` → receiver `handleFocusInBounds` → `goAsync()` → static `focusInBoundsExecutor` → `performFocusInBounds` → result emission → `PendingResult.finish()` → Python's two-second TARGET_ACTION_RESULT wait. The receiver's broadcast lifetime therefore included the complete service operation.

The operation synchronously reads the active root, builds TalkBack-like focus nodes, filters candidates, may collect raw content-entry candidates, executes/verifies accessibility focus (up to two attempts and a 650ms verification window), reads actual focus, captures evidence/snapshots, attaches evidence, and emits its result. Delayed evidence observations are separately posted, but the immediate evidence and candidate scans execute within the service call. Expensive tree work therefore happened before receiver completion. TARGET_FOCUS_COMMIT used the same pending executor pattern and synchronously scanned the visible tree, resolved exact identity, performed focus, waited 80ms when accepted, and verified actual accessibility focus.

The old Python focus retry loop could resend when no correlated result arrived inside its operation attempt. After uncertain delivery this is not a safe contract. It now issues one command and returns explicit delivery/result failures; a semantic negative result remains negative.

## Command family audit

This table describes the pre-fix local state (SMART_NEXT already locally fixed) and the resulting scope. All 18 receiver actions support request IDs. “Result async” means service work/result can finish after receiver completion, not merely that a log line is consumed later. Direct synchronous service delegation is still service delegation.

| COMMAND | USES_GOASYNC | PENDING_RESULT_HELD_UNTIL_WORK_COMPLETE | SERVICE_DELEGATED | RESULT_ASYNC | REQUEST_ID_SUPPORTED | ADB_TIMEOUT_RISK / disposition |
|---|---|---|---|---|---|---|
| SMART_NEXT | NO after prior local fix | NO | YES, service-owned serial worker | YES | YES | Prior 17 failures classified; retain existing fix |
| FOCUS_IN_BOUNDS | YES → NO | YES → NO | YES, shared service-owned focus worker | NO → YES | YES | Proven 30s timeout; fixed here |
| TARGET_FOCUS_COMMIT | YES → NO | YES → NO | YES, same shared focus worker | NO → YES | YES | Identical pending pattern plus unbounded tree scan; fixed transport only |
| FOCUS_TARGET | NO | No PendingResult; inline receiver still waits for work | YES, synchronous | NO | YES | Potential tree/IPC latency; no 30s failure established for this action; audit only |
| CLICK_TARGET / LONG_CLICK | NO | Inline receiver waits | YES, synchronous | NO | YES | Potential target-search/action latency; audit only |
| TOUCH_BOUNDS_CENTER_TARGET | NO | Inline receiver waits | YES, synchronous | NO | YES | Search and bounded gesture callback wait (2800ms), plus node IPC; audit only |
| CHECK_TARGET | NO | Inline receiver waits | YES, synchronous | NO | YES | Potential target tree scan; audit only |
| GET_FOCUS | NO | Inline receiver waits | YES, refresh snapshot plus state store | NO | YES | Focus-node/snapshot IPC potential; audit only |
| DUMP_TREE | NO | Inline receiver waits | YES, synchronous | NO | YES | Full tree and optional scroll/device metadata scans; potential latency, no failure proved here; audit only |
| NEXT | NO | Inline receiver waits | YES, synchronous | NO | YES | Native navigation/node IPC potential; audit only |
| PREV | NO | Inline receiver waits | YES, synchronous | NO | YES | Native navigation/node IPC potential; audit only |
| CLICK_FOCUSED | NO | Inline receiver waits | YES, synchronous | NO | YES | Mirror/descendant/ancestor search and gesture paths; potential latency; audit only |
| SCROLL | NO | Inline receiver waits | YES, synchronous | NO | YES | Ancestor/tree/validated-device-container search plus evidence; potential latency; audit only |
| SET_TEXT | NO | Inline receiver waits | YES, synchronous | NO | YES | Focused node/action IPC; no long pending path established; audit only |
| SET_SYSTEM_LANGUAGE | NO | Inline receiver waits | YES, bounded locale adapter | NO | YES | 1500ms root stabilization budget plus snapshot IPC; not exercised (English out of scope) |
| PING | NO | NO long work | YES, readiness reference | NO | YES | Cheap READY result; low observed risk |
| ACTION_COMMAND / reset | NO | NO long work | NO, navigator history reset | NO | YES | In-memory reset; low observed risk |
| EVIDENCE_EVENTS | NO | NO node work | NO, evidence snapshot/clear | NO | YES | Buffer serialization/chunks; no tree scan; audit only |

The two remaining `goAsync` sites are removed. Other synchronous receiver operations remain recorded risks; their individual tree/action behavior is not rewritten without evidence that their command lifetime needs this change. This audit does not certify unexercised commands as latency-safe. Anchor/realignment is a Python flow using these existing commands, not another receiver action.

## Implemented contract

1. FOCUS_IN_BOUNDS and TARGET_FOCUS_COMMIT enqueue work on one `AccessibilityCommandDispatcher` owned by the bound service, then return promptly. Ordering, active/completed request deduplication, explicit worker failure, and close/drain behavior are centralized once for these two commands.
2. Service focus algorithms and target matcher/verification remain unchanged. An optional emission parameter lets direct existing service callers retain their result behavior; receiver-dispatched work returns its payload without emitting, and the receiver callback emits exactly one terminal TARGET_ACTION_RESULT after service completion. Callback emission exceptions never trigger a second result.
3. ADB delivery timeout remains **30s**. These commands now surface TimeoutExpired/nonzero/OS failures explicitly, retaining partial stdout/stderr, and never claim success or issue a blind retry after delivery failure.
4. Focus result waiting is independent and bounded at **75s**, matching SMART_NEXT. The observed focus response already crossed 30s, and these focus commands scan the same accessibility trees where SMART_NEXT's measured collection/result spans approached 60s. The shared 75s operation bound preserves a margin for focus verification and IPC while keeping missing results failures. Existing `wait_` parameters remain call-compatible; their old retry/short-result budgets do not hold a broadcast or trigger repeated navigation.
5. Full UUID IDs, request/prefix-specific correlation, deadline checks, retired-result observation, duplicate terminal-result rejection, and protection against logcat clearing while either async family has an outstanding request prevent stale credit or cross-family result loss. Generic target-action cache behavior is retained outside these async focus requests. Existing chunk/digest parsing remains in use.

## Verification and disposition

### Offline gates

- Focus transport tests: **15 passed**. Related SMART_NEXT/result/recovery/target-focus regression: **54 passed** (combined: 69 passed).
- Final full Python: **3105 passed, 1 skipped**, 89.19s; one pytest cache permission warning, no failed test.
- Full Helper: **383 passed**, zero failures/errors/skips. `testDebugUnitTest assembleDebug --offline`: BUILD SUCCESSFUL.
- Debug APK installed before validation, SHA-256 `eea1c64d780f5b76643c2672d52ee9e190c7622e846898ee8978d436e3d95786`. Production hashes remained identical to the final offline gates.
- Evidence: `qa_frontend_runs/focus_transport_20261008/python_focused.log`, `python_full_suite_final.log`, `helper_tests_build.log`, and `flow_state.json`.

### Korean device gates

Primary locale `ko-KR`; device `R3CX40QFDBP`. TalkBack PID **21432** and Helper PID **21979** remained unchanged across all three runs. Delivery/result timeouts, missing results, correlation/parser/chunk errors, duplicate work, Helper ANR, TalkBack restarts, window fatal and fatal BadToken: **zero**.

| Validation | Batch | SMART_NEXT sent/matched | FOCUS_IN_BOUNDS | TARGET_FOCUS_COMMIT | Transport verdict |
|---|---|---|---|---|---|
| Family single | `batch_20261008_182422` | 96/96 | 7/7 | 9/9 | PASS |
| Family repeated stress | `batch_20261008_200140` | 29/29 | 2/2 | 5/5 | PASS |
| Home Monitor control | `batch_20261008_202704` | 16/16 | Not exercised | 1/1 | PASS |

Family single naturally terminated after **84 attempted steps**, `INCOMPLETE_NO_PROGRESS / repeat_no_progress`; coverage was incomplete (41 visited of 46 confirmed expected, 5 missed, 24 unknown). This is a transport PASS. Complete focus coverage and final Korean acceptance are not established here. Traversal settings, dynamic timestamps, candidate/review rules and target-focus semantics remain unchanged.

Repeats used the permitted **20-30 minute** option: one additional run, **1263.830s active stress (21m03.830s)**, **1403.205s wall time (23m23.205s)**, 18 observed content-step starts. An unstaged QA-only bootstrap stops before the next SMART_NEXT dispatch after the time window, with `async_in_flight=0 next_request_dispatched=false`. Every dispatched request completed and matched. This timed stress is not represented as natural complete-scenario coverage. A fake-clock probe checked the no-dispatch stop and outstanding-request guard. Its environment was removed before the control run.

Home Monitor naturally terminated after **16 attempts**, `COMPLETED / plugin_boundary_global_nav`, `traversal_complete=True`. Its coverage remains partial (17 visited of 35 confirmed expected). No camera fallback was used.

One **caught nonfatal** TalkBack `SimpleOverlay` BadToken incident occurred at **20:01:49.338** during repeat startup (two diagnostic lines: `Overlay not shown. Ignoring thrown BadTokenException.` and its exception message). The exception was explicitly caught, no fatal/ANR followed, and the same PID continued through repeat and control. This is documented under the user's allowed nonfatal-warning rule; it does not establish window-leak closure.

The original QA observer's unrequested 45-minute whole-run bound was removed by replacing the observer while the same batch continued. No scenario was stopped/rerun and command/result deadlines were unchanged. Original logs are retained; final audits use uninterrupted backend logcat, corroborated by runner and independent observer evidence. QA DUMP_TREE_END ID extraction and UTF-8 launcher reading were corrected without production changes.

### Command family post-validation audit

These counts cover the three new runs, excluding historical rejected runs. Checks include request-specific terminal payloads/dump parts, JSON/chunk integrity, duplicate work, and runner timeout/parse/late-result signals. Per-batch details: `qa_frontend_runs/focus_transport_20261008/command_family_post_validation.json`.

| COMMAND | REQUEST_COUNT | ADB_TIMEOUTS | RESULT_TIMEOUTS | MISSING_RESULTS | LATE_RESULTS | DUPLICATES | PARSE_ERRORS |
|---|---:|---:|---:|---:|---:|---:|---:|
| CLICK_TARGET | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| DUMP_TREE | 355 | 0 | 0 | 0 | 0 | 0 | 0 |
| EVIDENCE_EVENTS | 142 | 0 | 0 | 0 | 0 | 0 | 0 |
| FOCUS_IN_BOUNDS | 9 | 0 | 0 | 0 | 0 | 0 | 0 |
| FOCUS_TARGET | 23 | 0 | 0 | 0 | 0 | 0 | 0 |
| GET_FOCUS | 195 | 0 | 0 | 0 | 0 | 0 | 0 |
| PING | 368 | 0 | 0 | 0 | 0 | 0 | 0 |
| SCROLL | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| SMART_NEXT | 141 | 0 | 0 | 0 | 0 | 0 | 0 |
| TARGET_FOCUS_COMMIT | 15 | 0 | 0 | 0 | 0 | 0 | 0 |

**Ten exercised command types, 1258 requests, zero findings.** All 18 receiver paths were audited in code. Unexercised commands retain the documented potential inline-latency risks; their individual maximum runtime latency is not certified.

### Measured delivery/work independence

Real FOCUS_IN_BOUNDS request `322234b696474033addc3a8a61c5010e` in the Family single: receiver ACK/work start **19:42:47.730**, result **19:43:18.072**, **30.342s** after ACK. ADB delivery completed in **0.163s**; Python independently matched the successful verified-focus result. No retry or timeout increase was used.

SMART_NEXT ACK-to-result latency reached **65.711s** (88 requests exceeded 30s). FOCUS_IN_BOUNDS reached **30.342s** (one exceeded 30s). TARGET_FOCUS_COMMIT reached **7.305s**. All correlated inside the unchanged **75s** result deadline; ADB delivery remains **30s**. Per-request timestamps: `latency_summary.json`.

### Publication and next step

All specified transport gates passed. Publication scope: **13 files** (seven production files, four tests, two RCA documents). Historical rejection documents and output/QA artifacts remain unstaged and preserved. Actual commit/push/main fast-forward verification is retained separately in `qa_frontend_runs/focus_transport_20261008/publish_receipt.json`.

After verified publication, **NEXT_KOREAN_FULL_RUN_READY=YES** for one monitored Korean Full32 and separate acceptance review. Family/Home Monitor coverage limitations remain for that review; this task does not grant final Korean acceptance. **FULL32_RUN=NO, ENGLISH_RUN=NO, PHASE4_CHANGED=NO** here.
