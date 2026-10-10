# TalkBack Window Lifecycle Final Stress RCA — 2026-10-07

## Verdict

```text
WINDOW_LEAK_CLASSIFICATION=TRANSIENT_WINDOW_SPIKES_ONLY
AUTOMATION_TRIGGERED=UNPROVEN
NEXT_KOREAN_FULL_RUN_READY=YES_WITH_MONITORING
```

The targeted stress did not reproduce the historical TalkBack fatal, a TalkBack PID change, or persistent growth in TalkBack-owned windows. WindowManager totals fluctuated from 20 to 23. After Camera plugin runs, one additional SmartThings application activity remained in the task stack, so the final total was 22 instead of the 21-window idle baseline. TalkBack itself remained at one hidden SearchScreenOverlay window in the final idle samples.

No window leak cause was demonstrated, so no window creation or traversal behavior was changed. The audit did find that the runner recorded PID changes without interrupting traversal. A narrow opt-in safety change now invalidates traversal continuity and reports `INCOMPLETE_ERROR` when the lifecycle recorder observes a restart. A lightweight PID/service probe continues after the 256 full-snapshot cap.

## Historical incident

The preserved evidence in `docs/design/talkback-window-lifecycle-rca-20261007.md` records a real TalkBack `IllegalStateException: window count is over max!!` from `SearchScreenOverlay.createUIElements`, followed by TalkBack process death and service restart. The source log timestamp is `2026-10-06 10:53:19.577`. About 50 `WindowManagerGlobal.addView` calls for `SearchScreenOverlayLayout` appeared in roughly 13 ms before the exception. Two earlier TextToSpeechOverlay window-limit errors were also recorded.

That log places the event near Life Home Monitor entry and scroll work, but does not prove that the runner caused the overlay creation or leak. The prior attribution to `life_main` step 34 is not established by that artifact.

## Device and instrumentation

- Device: `R3CX40QFDBP` / `SM-F741N`, locale `ko-KR,en-US`.
- TalkBack PID at baseline and throughout stress: `18593`.
- Instrumentation: existing opt-in `TALKBACK_WINDOW_LIFECYCLE=1` action samples included timestamp, scenario, step, action/phase, foreground and accessibility focus, bounded WindowManager details, TalkBack PID, restart state, and SearchScreenOverlay visibility. No additional full window snapshots or periodic polling were added; after the full-snapshot cap, a PID/service-only probe now runs at existing capture points.
- No Helper APK or Helper source changes were made.

## Baseline and stress plan

The no-automation baseline ran for about 92 seconds with seven samples at 15-second intervals, from `2026-10-06T21:34:07Z` through `21:35:40Z`:

| Measure | Baseline |
| --- | ---: |
| WindowManager count | 21–21; stable |
| TalkBack-owned windows | 1 |
| SearchScreenOverlay | 1, hidden (`has_surface=false`, `ready=false`) |
| TalkBack PID | `18593` |

Four sequential cycles ran only `life_main`, `life_home_monitor_plugin`, `device_home_camera_plugin`, and `home_main`. No Full32, English locale, Phase 4, or step-limit changes were used. Scenario execution took about 29 minutes in aggregate; the first scenario began around `21:40:51Z` and the fourth cycle ended at `22:19:21Z`, a 38-minute-30-second stress interval. Including pre- and post-stress idle controls, observation spanned about 48 minutes.

| Scenario | Runs | Traversal result | Active total window range | Post-run idle |
| --- | ---: | --- | ---: | ---: |
| `life_main` | 4 | Cycle 1 attempted 6 steps and stopped at the safety limit; cycles 2–4 failed entry with `tab_or_anchor_failed` | 21–23 | Varied with foreground app state |
| `life_home_monitor_plugin` | 4 | All 4 traversals started; 8 attempted steps per run; safety-limited | 20–22 | 21 in all 4 runs |
| `device_home_camera_plugin` | 4 | All 4 traversals started; 8 attempted steps per run; safety-limited | 20–23 | 22 in all 4 runs |
| `home_main` | 4 | All 4 failed entry with `tab_or_anchor_failed`; no traversal | 22–23 | 22–23 |

These are diagnostic stress runs, not scenario acceptance passes. `home_main` and three `life_main` runs ended before traversal and are recorded as such.

## Window trend and action correlation

- Across 277 in-scenario lifecycle samples, total window count ranged from 20 to 23. There was no monotonic increase across cycles.
- TalkBack-owned snapshot counts ranged from 0 to 2 during actions and were 1 at both idle controls. SearchScreenOverlay snapshots showed at most one registered window and it was never visible.
- Every Life Home Monitor run returned to a 21-window idle count, matching baseline.
- Every Camera plugin run returned to 22. The bounded window details identify the extra count as the foreground `com.samsung.android.oneconnect/...plugin.camera.MainActivity`, with the underlying `SCMainActivity` retained without a surface. This is a SmartThings activity-stack residual, not an extra TalkBack window. The post-stress idle sample remained at 22 for the same reason.
- `TARGET_FOCUS_COMMIT`: 21 before/after pairs were observed. Counts fluctuated by at most one around the scenario baseline; no persistent TalkBack window increase followed the commit.
- `SMART_NEXT`: 70 before/after pairs were observed. Counts fluctuated between 21 and 23, with no increasing trend or persistent TalkBack residual.
- Scroll: 19 before/after action pairs were observed. Some downward scroll samples rose by one total window, but Life Home Monitor returned to baseline after each run.
- Plugin transitions: Camera entry introduced or retained a SmartThings base-application activity window. Life Home Monitor did not retain a new TalkBack window. No stale TalkBack accessibility window accumulated on Back or scenario exit.

The captures do not identify a single first-growth action because persistent TalkBack window growth was not observed. Target focus, `SMART_NEXT`, scroll, and plugin navigation remain temporally near some TalkBack service binds, but that association does not establish automation causality.

## SearchScreenOverlay and logcat

The precise monitor ran from `22:07:18Z` through `22:24:48Z`, using a live log start. It recorded:

- 35 `TalkBackService: System bound to service` messages.
- 35 `WindowManagerGlobal#addView` messages from `SearchScreenOverlay.createUIElements`; every addView occurred within 35 ms of a service-bound message and used PID `18593`.
- Each logged overlay view was a `ty=2032` `SearchScreenOverlayLayout` with bounds `0,0-0,0`. The lifecycle snapshots continued to show no visible search UI and no accumulated TalkBack windows.
- Zero precise `FATAL EXCEPTION` / `window count is over max` markers and zero TalkBack process-death markers. No PID change was observed in lifecycle samples.
- No service-bound or SearchScreenOverlay addView marker occurred during the post-stress no-automation control after the last scenario completed.

The repeated hidden overlay creation is real runtime activity and aligns with TalkBack service binding, but the trigger for those binds is unknown. It did not produce observable window accumulation during this run.

Monitor caveats: an initial monitor read historical log backlog; a second monitor treated ordinary service-bound messages as a fatal signal and stopped early; a broad `IllegalStateException` pattern later matched an unrelated SmartThings `WM-WorkerWrapper` constraints error at `22:03:14.978Z`. The precise monitor found no TalkBack fatal or process death. These monitor false positives are not counted as reproduced incidents.

## Runner restart safety

Before this change, `WindowLifecycleRecorder` emitted `talkback_restart_detected`, but `_main_loop_phase` and the scenario start pipeline ignored it. If a PID change were observed, the runner could continue and treat subsequent focus observations as part of the same traversal.

With lifecycle instrumentation enabled, the recorder now keeps the first restart event with timestamp, scenario, step, action, previous/new PID, process event, and window counts. The runner checks at entry, post-open focus, anchor focus, immediately after traversal actions, and before continuing after terminal or overlay work. It stops the current scenario with `stop_reason=talkback_restarted`; the uncertain current step is not credited when detection occurs before persistence. Entry-stage interruptions produce an explicit `INCOMPLETE_ERROR` terminal row. `termination_status("talkback_restarted")` resolves to `INCOMPLETE_ERROR`.

Once the 256 full lifecycle snapshots are capped, only a lightweight accessibility-service/PID probe continues. It does not append additional full window snapshots, but still detects and reports a later PID transition.

## Readiness and limits

`YES_WITH_MONITORING` is supported because four targeted cycles ran for 38 minutes 30 seconds, including repeated navigation, target focus, scroll, and plugin transitions, without a TalkBack fatal, PID change, or persistent TalkBack-owned window growth. The historical event remains an unresolved TalkBack-side risk, and 35 hidden overlay creations were seen during live scenario intervals.

The next Korean Full Run must set `TALKBACK_WINDOW_LIFECYCLE=1`. If a restart recurs, the runner will invalidate the scenario instead of silently continuing, and the lifecycle artifact plus precise logcat capture should be retained. Full32 was not run in this task.

## Verification

- Focused lifecycle/restart regressions: `7 passed`.
- Related runner and lifecycle tests: `519 passed`.
- Full Python test coverage: `3033 passed, 1 skipped` across two working-directory-correct invocations. The suite uses a custom `.test_tmp` directory denied by the workspace sandbox at repository root, so the main run used the writable `tests/` directory; the two tests that read `qa_frontend/...` relative to the repository root were rerun there and passed.
- Helper tests and APK build: not run; Helper was unchanged.

## Evidence artifacts

- Existing RCA: `docs/design/talkback-window-lifecycle-rca-20261007.md`
- Baseline snapshots: `qa_frontend_runs/window_fatal_stress_20261007/baseline_idle/talkback_window_lifecycle.jsonl`
- Four-cycle summary: `qa_frontend_runs/window_fatal_stress_20261007/stress_scenario_summary.jsonl`
- Post-stress idle snapshots: `qa_frontend_runs/window_fatal_stress_20261007/post_stress_idle_control/talkback_window_lifecycle.jsonl`
- Precise logcat summary and markers: `qa_frontend_runs/window_fatal_stress_20261007/logcat_monitor_precise/`
- Preserved stress run outputs: `qa_frontend_runs/window_fatal_stress_20261007/cycle_01/` through `cycle_04/`
