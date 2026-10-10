# TalkBack Window Lifecycle RCA — 2026-10-07

## Verdict

`WINDOW_LEAK_CLASSIFICATION=INCONCLUSIVE`

The historical TalkBack fatal and service restart are confirmed. The available evidence does not establish that automation caused or amplified a window leak. No behavior fix was made. Opt-in lifecycle instrumentation was added to collect better action-correlated evidence in future Korean runs.

The requested source RCA, `talkback-korean-full-run-acceptance-blockers-rca-20261006.md`, was not present in this checkout. The historical run log and current preserved QA artifacts were used directly; the missing RCA's scenario-step attribution could not be independently verified.

## Historical fatal

In `qa_frontend_runs/batch_20261006_082514/device_SM-F741N_R3CX40QFDBP/logcat.txt`, TalkBack threw `IllegalStateException: window count is over max!!` at `2026-10-06 10:53:19.577` from `SearchScreenOverlay.createUIElements`, through `UniversalSearchActor` construction and `TalkBackService.onServiceConnected`. ActivityManager recorded TalkBack PID `11228` dying at `10:53:19.733`; the service restarted and PID `6187` was bound at `10:53:33.671`.

About 50 `WindowManagerGlobal.addView` / `SearchScreenOverlayLayout` messages preceded the exception in roughly 13 ms. Two earlier `TextToSpeechOverlay` window-limit errors were also logged. The crash was temporally near `life_home_monitor_plugin` XML-entry and scroll work in that run. This correlation does not show that the runner invoked `SearchScreenOverlay` or caused the accumulation. The fatal was not established as `life_main` step 34 in this artifact.

## Targeted observations

Only Korean targeted diagnostics were run; Full32 was not run.

| Scenario | Artifact | Samples | Window count | Surfaced windows | Result |
| --- | --- | ---: | ---: | ---: | --- |
| `life_main` | `qa_frontend_runs/window_rca_life_main_retry_20261007/talkback_compare_20261007_020107/talkback_window_lifecycle.jsonl` | 17 | 20–22 | 8–9 | Traversal began, 6 steps, ended `INCOMPLETE_SAFETY_LIMIT`; PID stayed `18593`; no restart |
| `life_home_monitor_plugin` | `qa_frontend_runs/window_rca_life_home_monitor_20261007/talkback_compare_20261007_020538/talkback_window_lifecycle.jsonl` | 27 | 20–22 | 8–9 | Traversal began, 8 attempted steps, ended `INCOMPLETE_SAFETY_LIMIT`; PID stayed `18593`; no restart |

Across those action samples, counts fluctuated by at most two and did not grow monotonically. The target-focus before/after sample was stable. Scroll and `SMART_NEXT` samples had occasional one-window changes but no persistent increase. The Search overlay window titled `화면 검색` was registered in the WindowManager list but had no surface and was not ready for display, so it was classified hidden. Special-state handling was not exercised by these targeted runs.

A short no-automation control sampled the same foreground and TalkBack PID three times, eight seconds apart: WindowManager count stayed at 22 and surfaced count at 8. This brief control supports short-term stability only; it does not rule out a longer-term TalkBack issue.

## Answers to the RCA questions

- Monotonic growth: not reproduced in the targeted run samples.
- Return to baseline: counts fluctuated around 20–22; no persistent rise was observed. The short control stayed at 22.
- Action correlation: no persistent increase followed target focus, `SMART_NEXT`, or scroll. Special-state Back was not exercised.
- Target focus contribution: no increase in its before/after sample.
- Search overlay: a hidden TalkBack accessibility window was registered; visible search UI was not observed.
- TalkBack restart: none in either targeted scenario. The historical fatal did cause a process death and restart.
- Without automation: the short control was stable; long-duration behavior remains unknown.

Therefore, `AUTOMATION_TRIGGERED_WINDOW_LEAK=UNPROVEN`. The historical internal TalkBack window-limit failure remains an acceptance risk until longer action-correlated evidence resolves its cause.

## Instrumentation

Set `TALKBACK_WINDOW_LIFECYCLE=1` to enable sampling. It is disabled by default. Each bounded JSONL event includes timestamp, scenario, step, action/phase, window counts, surfaced/ready counts, bounded window/package/type details, foreground package, helper-observed accessibility-focus package and its age, TalkBack enabled state/PID, restart detection, and Search overlay registration/visibility. Events are written to the scenario's `talkback_window_lifecycle.jsonl`; collection is capped at 256 events and at most 12 window details per event. Device command output is filtered and bounded. Samples are taken at scenario start, before/after relevant actions, after post-entry focus observation, and on observed exceptions; no polling loop was added.

No arbitrary delay, TalkBack recovery policy, acceptance-validator change, or traversal behavior change was introduced.
