# Family Care SMART_NEXT timeout RCA and local transport fix

The 17 failures in `batch_20261007_231704` are classified. Seven requests emitted complete, correctly correlated results after Python's deadline. Ten requests reached the Helper service worker but were interrupted by Android broadcast ANR kills before emitting their navigation results. The local fix removes navigation work from the pending broadcast lifetime and separates delivery failure from bounded result waiting. Unit tests and the APK build pass. **Device validation is blocked; this hotfix is not approved or published.**

Starting HEAD and `origin/main` were both `a9ddec864415bc9ebce76b9aa77fde6f5784c09e`. The local branch is `fix/smart-next-transport-timeout`. Existing rejected-run evidence and output trees were preserved.

## Evidence and classification

Primary evidence is the rejected run's device `runner.log` and `logcat.txt`, under `qa_frontend_runs/batch_20261007_231704/device_SM-F741N_R3CX40QFDBP/`. The extraction is preserved under `qa_frontend_runs/smart_next_timeout_rca_20261008/`:

- `failure_analysis.json`: all 17 exact commands, Python timeout/miss line references, receiver/service/navigator timestamps, Helper PIDs, foreground activity, focus evidence, ANR/kill context, and reassembled late-result verdicts.
- `failed_request_logcat.txt`: full correlated logcat records for all 17 IDs, including records after Python stopped waiting.
- `analyze_failed_run.py`: reproducible extraction from the preserved primary artifacts.

All 17 commands timed out at 30 seconds, with empty Python stdout and a subsequent missing `SMART_NAV_RESULT`. Every request had receiver and service/navigator entry evidence, so none is classified as delivery failure before the receiver. Searching the entire capture includes at least 30 seconds after each timeout; the external capture ends at 02:45:19.653 KST, after the last Helper kill at 02:44:48.072.

Times below are 2026-10-08 KST. Collection duration is the logged interval from `performSmartNext_start` to `current_focused_node_snapshot`; it localizes the slow stage but does not identify each individual node IPC. A late delay is estimated relative to receipt plus the 30-second command timeout because Python did not record an absolute subprocess-start timestamp. It is not an exact measurement of the Python deadline.

| Step | Request ID | Helper PID | Receiver receipt | Collection seconds | Late result found | Receipt-to-result seconds | Approx. after command timeout | Helper ANR kill | Classification |
|---:|---|---:|---|---:|---|---:|---:|---|---|
| 1 | `310d55ed` | 14159 | 02:18:56.816 | 44.108 | YES | 45.092 | 15.092s | — | RESULT_CORRELATION_TIMEOUT |
| 5 | `7a02bec5` | 14159 | 02:24:06.995 | 43.472 | YES | 48.882 | 18.882s | — | RESULT_CORRELATION_TIMEOUT |
| 6 | `c02c3f6d` | 14159 | 02:25:05.829 | 47.265 | YES | 55.903 | 25.903s | — | RESULT_CORRELATION_TIMEOUT |
| 7 | `b27e9d6b` | 14159 | 02:26:22.641 | 37.723 | YES | 47.500 | 17.500s | — | RESULT_CORRELATION_TIMEOUT |
| 10 | `6a7f4227` | 14159 | 02:27:56.029 | 42.060 | YES | 49.836 | 19.836s | — | RESULT_CORRELATION_TIMEOUT |
| 11 | `a7c10b48` | 14159 | 02:28:52.472 | 41.350 | YES | 48.848 | 18.848s | — | RESULT_CORRELATION_TIMEOUT |
| 12 | `86cafc2e` | 14159 | 02:29:51.135 | 35.751 | YES | 41.946 | 11.946s | — | RESULT_CORRELATION_TIMEOUT |
| 15 | `501de6f8` | 14159 | 02:31:53.617 | 59.881 | NO | — | — | 02:32:54.673 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 16 | `3e49d6aa` | 18851 | 02:33:13.066 | Not reached | NO | — | — | 02:34:13.765 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 18 | `0776ac9b` | 19345 | 02:34:41.354 | 60.171 | NO | — | — | 02:35:42.087 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 19 | `305b9ebf` | 20132 | 02:36:13.856 | 49.097 | NO | — | — | 02:37:14.566 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 20 | `859948b5` | 20780 | 02:37:36.530 | 53.919 | NO | — | — | 02:38:37.204 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 21 | `7d56dde2` | 21420 | 02:38:50.438 | 49.836 | NO | — | — | 02:39:51.049 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 22 | `3bf82c74` | 21923 | 02:40:12.030 | 54.839 | NO | — | — | 02:41:12.679 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 23 | `43063146` | 22405 | 02:41:20.056 | 57.992 | NO | — | — | 02:42:20.714 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 24 | `e9b541a3` | 22904 | 02:42:28.003 | 52.337 | NO | — | — | 02:43:28.684 | HELPER_RECEIVED_SERVICE_BLOCKED |
| 25 | `d8136773` | 23395 | 02:43:47.412 | 54.083 | NO | — | — | 02:44:48.072 | HELPER_RECEIVED_SERVICE_BLOCKED |

All seven late results reassemble completely through the existing Base64/SHA256 transport, contain the original `reqId`, and report normal navigation results. There is no evidence that Python discarded a timely result, correlated to the wrong ID, or that these seven payloads were truncated. The other ten have explicit `ANR in com.iotpart.sqe.talkbackhelper`, `Reason: Broadcast ... SMART_NEXT`, and `Killing ... bg anr` records tied to their receiver PID. `HELPER_RECEIVED_SERVICE_BLOCKED` describes unfinished service-worker work; it does not claim the main thread executed navigation.

## Pipeline and primary cause

The old path was `A11yAdbClient.move_focus_smart` → `HelperBridge._request_smart_next` → `_broadcast` → `AdbExecutor.run` → `AdbDevice._run_adb_command`. It used `subprocess.run` with a list of arguments, no shell interpretation, captured stdout/stderr, and `DEFAULT_TIMEOUT_SECONDS=30.0`. `TimeoutExpired` was converted into an empty string, obscuring the difference between delivery failure and result absence. After the command, Python waited three seconds for a correlated `SMART_NAV_RESULT`.

`A11yCommandReceiver.handleSmartNext` already dispatched navigation to a worker, but it called `goAsync()` and finished its pending broadcast only after `service.moveFocusSmart`, evidence attachment, and result emission. Thus moving work off the main thread did not end the broadcast. The shell command waited for that pending lifetime, and Android eventually killed the Helper when the broadcast outlived its deadline. Android documents that the broadcast deadline still includes the interval between `goAsync()` and `PendingResult.finish()`; AOSP's shell implementation waits for broadcast completion. [Android receiver contract](https://developer.android.com/reference/android/content/BroadcastReceiver#goAsync()), [AOSP shell broadcast implementation](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android10-release/services/core/java/com/android/server/am/ActivityManagerShellCommand.java).

The slow stage is inside navigator runtime-state collection before candidate selection. In the first seven failures it consumed 35.751–47.265 seconds of the 41.946–55.903-second receiver-to-result interval. The later collection spans reached roughly 60 seconds, followed by Helper ANR kills. The first failure shows 24 candidates in the native Family Care activity; total windows remained 22–23. ANR context contains system load/pressure observations; no evidence establishes memory pressure as the cause. Helper process rebinds follow the ANR kills, so they do not explain the first seven delays.

Across 859 responding requests outside the 17 failures, approximate receiver-to-first-result latency was P50 0.302s, P90 0.882s, P95 1.015s, P99 5.144s, maximum 14.616s. These are transport completion timings, not a count of successful focus moves. Family Care exposes the contract defect when its native-tree collection is slow. The exact node operation responsible for that collection latency is not established by the existing stage logs; changing candidate construction or traversal semantics is outside this fix.

The retry audit found one immediate attempt with `wait_seconds=0` and `run_immediately=True`; SMART_NEXT was not blindly retried after timeout. Each new action had its own request ID. The local fix retains this policy.

## Local fix scope

The primary fix class is `SHORT_RECEIVER_ASYNC_EXECUTION`, with separate command ACK/result waiting:

1. A service-owned `SmartNextDispatcher` serializes navigation work. The receiver enqueues work and returns without holding a pending broadcast. Duplicate request IDs do not enqueue another action. Service destruction closes new submissions while accepted work drains.
2. The producer retains the existing one final result after evidence attachment and the existing Base64 chunks, SHA256, missing/duplicate checks, and legacy compatibility. Optional reply-broadcast failure cannot emit a second result.
3. SMART_NEXT command failure is surfaced explicitly as a transport failure, retaining partial stdout/stderr and the unchanged 30-second command limit. No navigation retry follows uncertain delivery.
4. The correlated result wait has a separate 75-second bound, justified by the observed 55.903-second late response and roughly 60-second ANR cutoff. This is not a larger ADB timeout. Missing results, results returned after the deadline, and reused request IDs remain failures. Retired results are logged and ignored during subsequent existing polls. SMART_NEXT now uses full UUID request IDs.

No navigator, target-focus semantics, max_steps, starvation policy, Phase 4, English policy, Home Safe, candidate contract, or TalkBack window-lifecycle behavior was changed.

## Tests and targeted validation

- Python focused transport/trace/chunk tests: **41 passed**. Coverage includes command success, delivery timeout, nonzero command failure, delayed result after ACK, missing/wrong correlation, result deadline, late-result retirement, duplicate IDs, no retry/no false credit, and unchanged generic ADB failure behavior.
- Python full repository test collection: **3,090 unique tests passed, 1 skipped**. The first run had 3,054 passes and 36 fixture setup errors caused by sandbox access to `.test_tmp`; rerunning the affected parser file with the required access yielded 41 passes, including five tests already counted. No fixture or validator was changed. Logs: `python_full_suite.log`, `python_fixture_rerun.log`.
- Full Helper tests: **376 passed, zero failures/errors**. New tests exercise ordered-broadcast completion before queued service work, long worker execution without blocking submission, request ID preservation, one result per request, duplicate suppression, explicit worker failure, and closed-service rejection.
- Debug APK: **BUILD SUCCESSFUL**; installed successfully on `R3CX40QFDBP`.

The only device attempt was `batch_20261008_060650`, selecting only `life_family_care_plugin`, with run kind `CUSTOM`, Korean locale and lifecycle monitoring. It started at 06:06:50 and was stopped at 06:07:06 KST. **It reached zero observed scenarios and sent zero SMART_NEXT requests.**

At 06:07:03.493, TalkBack PID 21432 logged `SimpleOverlay: Overlay not shown. Ignoring thrown BadTokenException`, followed by a null-token exception in `TextToSpeechOverlay$OverlayHandler` → `SimpleOverlay.show`. The monitor stopped immediately because the user requires no BadToken. TalkBack caught this exception; PID stayed 21432 and the newest crash ExitInfo remains the historical 2026-10-07 22:35:13.478 entry. No new TalkBack crash or window-count fatal was observed.

This occurred during environment initialization before scenario entry and before any SMART_NEXT, so it neither validates nor disproves the transport change. It is different from an uncaught TalkBack fatal. No repeated Family Care run or control scenario was started, and no lifecycle change was added. Evidence is in `family_single/monitor_state.json`, `family_single/logcat.txt` (exception begins around line 30138), `family_single/talkback_exit_info_after.txt`, and the batch runner log.

Stopped-validation evidence: failure stage is environment initialization; SMART_NEXT request ID and ADB command result are not applicable because no request was issued. Helper SMART_NEXT receipt, result emission, and correlation are not exercised. The missing evidence is a completed Family Care single run, repeated Family Care runs, and the control run using the installed fix under the strict no-BadToken gate.

## Final scope audit

`git diff --check` passed. The five tracked production changes are `A11yCommandReceiver.kt`, `A11yHelperService.kt`, `talkback_lib/__init__.py`, `talkback_lib/adb_device.py`, and `talkback_lib/helper_bridge.py` (110 insertions, 24 deletions). The four new scope files are `SmartNextDispatcher.kt`, `SmartNextDispatcherTest.kt`, `tests/test_smart_next_transport_contract.py`, and this document. Existing rejection evidence and generated `out/`, `tests/out/`, `s1/`, and `tests/s1/` are preserved and excluded. QA artifacts remain under `qa_frontend_runs/`.

The current branch is `fix/smart-next-transport-timeout`. Final local `HEAD` and the `origin/main` tracking ref both equal `a9ddec864415bc9ebce76b9aa77fde6f5784c09e`. No stage, commit, branch push, main merge, or main push was performed after the device gate stopped validation.

## Disposition and smallest next investigation

The original request/result failure is classified with high confidence; the specific cause of slow native-tree collection remains bounded to an existing navigator stage. The local transport fix has unit/build evidence but lacks device validation. It remains uncommitted on `fix/smart-next-transport-timeout`; main and `origin/main` remain at the starting SHA. Preserved/generated output folders and the earlier untracked rejection report are excluded from the code scope.

The next investigation is the caught null-token TTS-overlay exception during clean SmartThings launch/environment initialization. Compare overlay token availability and TalkBack service/window state immediately around startup; do not treat it as a SMART_NEXT response failure or automatically alter the Clothing Care lifecycle fix. Once the strict no-BadToken gate can be met, the pending device gates are the Family Care single run, short repeated Family Care validation, and `life_home_monitor_plugin` control. Korean Full32 readiness remains **NO**.

## Final report

```text
OVERALL_VERDICT=RCA_CLASSIFIED_FIX_IMPLEMENTED_DEVICE_VALIDATION_BLOCKED
START_HEAD=a9ddec864415bc9ebce76b9aa77fde6f5784c09e
FINAL_HEAD=a9ddec864415bc9ebce76b9aa77fde6f5784c09e
FAILED_FULL32_RUN=batch_20261007_231704
FAILED_SCENARIO=life_family_care_plugin
FAILED_SMART_NEXT_COUNT=17
ADB_TIMEOUT_SECONDS=30 unchanged
ADB_TIMEOUT_SOURCE=talkback_lib.constants.DEFAULT_TIMEOUT_SECONDS through AdbDevice subprocess.run
RESULT_WAIT_TIMEOUT_SECONDS=3 before; 75 after, separate from delivery timeout
FAILURE_STAGE_COUNTS=RESULT_CORRELATION_TIMEOUT:7; HELPER_RECEIVED_SERVICE_BLOCKED:10; all other classes:0
LATE_RESULT_COUNT=7
PRIMARY_ROOT_CAUSE=goAsync pending broadcast retained through slow service navigation; ordered am broadcast waits and Helper hits broadcast ANR deadline
ROOT_CAUSE_CONFIDENCE=HIGH for transport lifetime failure; exact slow node operation not established
FAMILY_CARE_SPECIFIC=Family Care UI latency exposed a general broadcast/result contract defect; control not yet run
SUCCESS_LATENCY_P50=0.302 seconds
SUCCESS_LATENCY_P90=0.882 seconds
SUCCESS_LATENCY_P95=1.015 seconds
SUCCESS_LATENCY_P99=5.144 seconds
SUCCESS_LATENCY_MAX=14.616 seconds
FIX_CLASS=A SHORT_RECEIVER_ASYNC_EXECUTION; E SEPARATE_COMMAND_ACK_FROM_NAV_RESULT; D bounded independent result wait
FIX_DESCRIPTION=service owns serialized work; receiver returns promptly; strict delivery failure; correlated bounded results; no blind retry or duplicate navigation
ADB_COMMAND_TIMEOUTS_AFTER_FIX=NOT EXERCISED; 0 SMART_NEXT requests in stopped device attempt
MISSING_SMART_NAV_RESULTS_AFTER_FIX=NOT EXERCISED
SMART_NAV_PARSE_ERRORS_AFTER_FIX=NOT EXERCISED
DUPLICATE_NAV_ACTIONS_AFTER_FIX=NOT EXERCISED
TARGETED_PYTHON_TESTS=41 passed
FULL_PYTHON_SUITE=3090 unique passed, 1 skipped; fixture permission failures rerun successfully
HELPER_CHANGED=YES
HELPER_TESTS=376 passed, 0 failures/errors
APK_BUILD=PASS; installed
FAMILY_CARE_SINGLE_RESULT=BLOCKED_BEFORE_SCENARIO; caught TalkBack TTS-overlay BadToken during startup
FAMILY_CARE_REPEAT_RUNS=0
FAMILY_CARE_REPEAT_DURATION=00:00
FAMILY_CARE_REPEAT_FAILURES=NOT RUN
CONTROL_SCENARIO=life_home_monitor_plugin planned
CONTROL_RESULT=NOT RUN
TALKBACK_PID_CHANGE_COUNT=0
WINDOW_FATAL_REPRODUCED=NO
BADTOKEN_REPRODUCED=YES; caught nonfatal TextToSpeechOverlay exception
FILES_CHANGED=5 tracked production files; 1 new dispatcher; 2 new test files; this RCA document
COMMIT=NOT CREATED
BRANCH_PUSH=NOT PERFORMED
MAIN_MERGE=NOT PERFORMED
MAIN_PUSH=NOT PERFORMED
HEAD_ORIGIN_MAIN_MATCH=YES
FULL32_RUN=NO
ENGLISH_RUN=NO
PHASE4_CHANGED=NO
NEXT_KOREAN_FULL_RUN_READY=NO
REMAINING_KOREAN_BLOCKERS=startup caught BadToken; transport device single/repeat/control gates unvalidated
NEXT_RECOMMENDED_STEP=Investigate startup TTS-overlay null token, then complete targeted transport validation
```


## Follow-up: shared focus transport closure

The earlier `batch_20261008_062014` blocker/disposition above remain historical evidence. FOCUS_IN_BOUNDS and TARGET_FOCUS_COMMIT shared the receiver-lifetime defect and are now addressed alongside SMART_NEXT. See [FOCUS command transport RCA and final gates](focus-command-transport-contract-20261008.md).

New Family single, 21m03.830s repeated stress, and Home Monitor passed their transport gates: **141 SMART_NEXT, 9 FOCUS_IN_BOUNDS, 15 TARGET_FOCUS_COMMIT results matched**; zero ADB/result timeouts, missing results, parser/correlation errors, duplicates, Helper ANRs or fatal TalkBack lifecycle failures. One explicitly caught nonfatal SimpleOverlay BadToken at repeat startup is documented in the follow-up; PID remained stable. Full Python: **3105 passed, 1 skipped**; Helper: **383 passed**; APK build/install: PASS. ADB timeout remains 30s, independent result wait 75s. Coverage limitations remain; final Korean acceptance requires a monitored Full32 and separate review. No Full32, English run, Phase 4, max_steps, starvation, timestamp or target-focus semantic change was made here.
