# Korean plugin entry and acceptance monitor closure — 2026-10-09

## Scope and source

This task addresses Air Care, Energy, Find entry aborts and the acceptance
monitor's SMART_NEXT request correlation. It does not approve a new Full32
baseline. No Full32, English run, or Phase 4 change is part of this task.

```text
START_HEAD=eedfe0599fc714915e0ef7fb576f7c1488b31f28
START_ORIGIN_MAIN=eedfe0599fc714915e0ef7fb576f7c1488b31f28
START_HEAD_ORIGIN_MAIN_MATCH=YES
START_TRACKED_WORKTREE_CLEAN=YES
WORK_BRANCH=fix/korean-anchor-aborts-and-monitor-correlation
```

`main` was checked out and pulled with `--ff-only` before creating the branch.
Existing untracked monitor tooling, prior rejection documents, and generated
QA evidence were preserved. The origin remains the approved repository:
`https://github.com/gunwookim0221/talkback-a11y-helper.git`.

Primary historical evidence is `batch_20261009_175807`, device
`SM-F741N_R3CX40QFDBP`, under
`%TEMP%/talkback-full32-20261009-monitor-output/qa_frontend_runs/`.
The runner log, normal runtime log, runtime configuration, and original
logcat are preserved there. Twenty-three original service hierarchy snapshots
were reassembled from the logcat's correlated, SHA-256 checked
`DUMP_HIERARCHY_RESULT_CHUNK` records into
`output/targeted_anchor_monitor_20261009/historical/`.
No UIAutomation/XML acquisition was used to reconstruct them.

## Independent entry RCA

All three configurations use Life card entry, `new_screen`, and
`anchor_only`. The Life tab was selected and verified using the service
hierarchy. The configured post-entry anchor already accepts
`navigate up`, `위로 이동`, and `상위 메뉴로 이동`.
The initial `context_ok=false / anchor_matched=false` occurs before card
pre-navigation in `new_screen` mode; it is not the first failed entry contract.
Runtime overrides contain `enabled=true` and `max_steps=100`, without stale
anchor, context, or stabilization overrides.

### Air Care

```text
SCENARIO=life_air_care_plugin
EXPECTED_ENTRY_PATH=selected Life -> exact Air Care card -> plugin verification -> navigation-up anchor
EXPECTED_ENTRY_TARGET=에어 케어 / configured Air Care title patterns
OBSERVED_CONTEXT=Life selected; active/focused OneConnect application window
ROOT_CAUSE_CLASS=CARD_ENTRY_FALSE_GUARD
AIR_CARE_OLD_FALSE_SPECIAL_STATE_REPRODUCED=NO
```

At 18:20:27, the exact `에어 케어` title exists on `llCard`. Its matching
RelativeLayout and `frameLayout` candidates have bounds
`30,2054,1050,2558`, score 240, and are visible and actionable.
The bottom navigation occupies `60,2304,1020,2472`.
`_xml_entry_candidate_obstruction_reason` rejects the entire card for any
intersection, despite an unobstructed upper portion remaining.
This is the first failed condition.

The next full scroll overshoots. At 18:20:31 the candidates are still correctly
matched, with clipped bounds `30,0,1050,287`, score 240. The old entry code taps
their unqualified center `(540,143)`, inside the fixed `tab_title` room menu
(`168,136,732,256`). No plugin transition is confirmed. Subsequent hierarchy
captures show the room-selection ListView, including the selected test room.
Retries search that menu and finally abort with
`INCOMPLETE_ERROR / tab_or_anchor_failed / NO_TARGET_CANDIDATE`.

The abort is a card geometry/entry problem, not special-state detection or
post-entry anchor label drift. No `설정하기` special-state decision caused this
failure. The targeted run subsequently records `verify_hit=true` and
`special_token_hit=false` on the real Air Care plugin screen.

### Energy

```text
SCENARIO=life_energy_plugin
EXPECTED_ENTRY_PATH=selected Life -> exact Energy card -> plugin verification -> navigation-up anchor
EXPECTED_ENTRY_TARGET=에너지
ENERGY_TARGET_PRESENT=YES
ENERGY_TARGET_MATCHABLE=YES
ROOT_CAUSE_CLASS=CARD_ENTRY_FALSE_GUARD
```

The title `에너지` is present on `llCard`, with the Korean body CTA
`가전제품을 추가하고 에너지 사용량을 확인해 보세요.` on `tvLine2`.
At 18:24:52, three matching candidates score 240 and have bounds
`30,1903,1050,2407`. The same whole-card bottom-overlay predicate rejects
all three. This is the first failed condition, not a resource-ID or Korean
text mismatch.

After scrolling, the target is clipped to `30,0,1050,422`. The old center
`(540,211)` hits the same fixed room selector. Transition verification returns
`tap_dispatched_but_no_transition`, retries observe the room menu, and the
same final abort is emitted. The foreground package remains OneConnect.
The scenario's title matching, resource hints, context regex, and runtime
configuration already recognize the actual target.

### Find

```text
SCENARIO=life_find_plugin
EXPECTED_ENTRY_PATH=selected Life -> exact Find map entry -> fme plugin verification -> navigation-up anchor
EXPECTED_ENTRY_TARGET=파인드 / configured Find title patterns
FIND_TARGET_PRESENT=YES
ROOT_CAUSE_CLASS=TARGET_PRESENT_BUT_FILTERED
FIND_FALSE_POSSIBLE_CRASH_REPRODUCED=NO
```

At 22:12:03 the Life hierarchy contains the visible, enabled, clickable,
focusable `com.samsung.android.oneconnect:id/map_area` at
`30,771,1050,1125`. Its description starts with `파인드`, followed by the selected
device and last-location text. This satisfies the existing strict Korean
phrase matcher. It is the embedded Find card, not evidence of an already-open
plugin screen.

The entry promotion loop nevertheless moves this actionable node to its
focusable parent, `com.samsung.android.oneconnect:id/recycler_view`
(`android.widget.GridView`). The generic chrome exclusion regex contains
`recycler`, so the promoted candidate is rejected. This is the exact first
failed condition. The visible Find target is never ranked into the eligible
list; later scrolls pass it, and retries end with `no_target_candidate_yet`,
then `tab_or_anchor_failed / NO_TARGET_CANDIDATE`.

No foreground verifier or crash guard rejects a valid Find plugin here:
pre-navigation never opens it. In targeted validation the actual plugin
back-button resource is `com.samsung.android.plugin.fme:id/back_button`,
the Korean navigation-up anchor is verified, and plugin entry succeeds.

### Shared-cause decision and applied changes

`THREE_FAILURES_SHARE_ROOT_CAUSE=NO`. Air Care and Energy share the card geometry
defect; Find has a different actionable-node promotion defect. Their matcher,
entry function, context mode, and override shape are shared, but their first
failed predicates are not.

The production change is confined to card pre-navigation in
`tb_runner/collection_flow.py`:

- Air Care and Energy compute tap bounds from the card's visible region outside
  the observed fixed top controls and bottom navigation. They use those bounds
  for the tap, including after recoverable-precondition target refresh.
  A clipped strip smaller than 48 pixels is rejected; a target hidden at the
  top is repositioned with a bounded upward search using the existing search
  budget. Fully bottom-obstructed targets remain rejected.
- Find preserves a strictly matched, already clickable/effectively clickable
  node instead of promoting it into a recycler.
- Compatibility guards are restricted to the affected scenario IDs.
  Other plugins retain the original promotion and bottom obstruction rules;
  a dedicated regression test verifies that restriction.

The source does not change scenario labels, runtime overrides, anchor/context
acceptance, hierarchy acquisition, Helper behavior, transport implementation,
starvation, max steps, Home semantic substates, or Phase 0/1/2/3 contracts.
It does not downgrade anchor failures to warnings.

The published entry function was replayed directly from commit `eedfe059` on
the preserved service snapshots, independently reproducing whole-card
rejections, the unsafe `(540,143)` and `(540,211)` taps, and the missing eligible
Find candidate. Corrected candidate replay selects safe points
`(540,2179)`, `(540,2103)`, and Find's own `map_area` at `(540,948)`.
The replay simulates transition confirmation only; real transitions are
validated separately on the device.

## SMART_NEXT monitor RCA and fix

The two historical requests are:

| Request ID | Delivery seconds | Result wait limit | First timeout runner line |
|---|---:|---:|---:|
| `cadd5b13ac014f3590c92fd9368eb897` | 0.159 | 75 s | 110479 |
| `7e5efd2f8449440bb04a7f9e7d26d0c3` | 0.155 | 75 s | 114890 |

Both chains contain a generated request ID, a fresh
`[SMART_NEXT_TRACE] before_broadcast` action owned by
`com.iotpart.sqe.talkbackhelper.SMART_NEXT`, an explicit broadcast to the
Helper package, a `SMART_NAV_RESULT` wait start with the same `req_id`, a
`read_log_result_miss` with `smart_nav_result_wait_timeout`, and a
`[SMART_NEXT_TRANSPORT] completed` record with `status=transport_error` and
`retry=false`. The observed Helper logcat PID is `13706`. The terminal runner
lines do not repeat package/PID identity.

The monitor had three distinct parsing/correlation gaps:

1. Its request-ID regex accepted `request_id`/`correlation_id`, not the actual
   `req_id`/`reqId` fields.
2. `\bSMART_NEXT\b` does not recognize the underscore suffix in the real
   `SMART_NEXT_TRACE`/`SMART_NEXT_TRANSPORT` tags.
3. It demanded Helper identity on each terminal line and never retained the
   preceding broadcast's ownership.

`tools/full32_acceptance_monitor.py` now maintains a small request ledger
containing exact request ID, command, Helper package/current PID generation,
start timestamp, and terminal status/timestamp. Only fresh recognized runner
broadcasts create entries. The ledger is bounded to 512 requests with a
five-minute expiry; successful or failed terminal requests are retired.
Known Helper-owned SMART_NEXT terminal timeouts or equivalent transport errors
raise one hard blocker even when the result line omits package/PID.
Unowned, different, stale, expired, unrelated, or already retired requests do
not establish a timeout failure. FOCUS_IN_BOUNDS and TARGET_FOCUS_COMMIT
correlated transport errors retain hard-blocker handling.

Timestamped records preceding monitor start remain ignored. Untimestamped
records rely on the existing tail-offset freshness contract and record their
arrival time; callers must not feed historical untimestamped records as live
input. Replay supplies the last observed runner timestamp explicitly.

Command/lifecycle replay of the entire historical runner file evaluates
2,338 command records, identifies the two real SMART_NEXT timeouts exactly
once each, and ignores 2,417 false restart keys. No other command/lifecycle
blocker is emitted in that replay. No production transport fault is injected.

## Verification and device evidence

Offline evidence resides in `output/targeted_anchor_monitor_20261009/`:

- `published_entry_failure_replay.json`: reproduced published failures.
- `entry_candidate_replay.json`: corrected candidate decisions and simulated
  taps; not a substitute for device transition evidence.
- `final_scoped_candidate_replay.json`: the final scenario-restricted source
  reproduces the same three safe tap coordinates on the original snapshots.
- `monitor_full32_replay.json`: both real timeout requests detected.
- `python-suite-final.log`: **3153 passed, 1 skipped**; baseline was
  3124 passed, 1 skipped.
- Focused config/anchor/context/hierarchy/entry/monitor run: **164 passed**.
  The final full suite also includes the subsequent scenario-scope guard test.
- Monitor tests: **22 passed** in the full suite. They cover owned timeout,
  success, unowned/different/stale/expired requests, bounded eviction,
  FOCUS/TARGET transport errors, exact real runner field/tag forms, false
  restart keys, real TalkBack restart, real Helper ANR, and benign ANR text.
- Helper JVM suite: **384 tests, 0 failures, 0 errors**, `BUILD SUCCESSFUL`.

Only Air Care, Energy, and Find were selected on `R3CX40QFDBP` in Korean.
The existing Full profile's runtime settings, including max steps 100,
were retained. Device artifacts are under
`output/targeted_anchor_monitor_20261009/device_20261009_230532/`, including
the launch specification, runner/normal log, raw logcat, lifecycle JSONL,
traversal summary, workbook, and live monitor samples.

| Scenario | Entry | Attempted traversal steps | Terminal status |
|---|---|---:|---|
| Air Care | `plugin_open_verified`; anchor/context verified | 10 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |
| Energy | `plugin_open_verified`; anchor/context verified | 41 | `COMPLETED / scroll_exhausted` |
| Find | `plugin_open_verified`; anchor/context verified | 10 | `INCOMPLETE_NO_PROGRESS / repeat_no_progress` |

Air Care and Find pass the entry/traversal-start requirement, but their
no-progress terminations remain warnings and are not reported as complete
traversal.
Energy's real entry used the safe clipped region `30,1903,1050,2304`, tapping
`(540,2103)` instead of the header. Find's real entry selects `map_area` and
verifies the `fme` plugin's back button.

The targeted supervisor completed with exit code 0 and no hard blockers.
All three entry contracts succeeded. The final normal log contains zero
`tab_or_anchor_failed`, `NO_TARGET_CANDIDATE`, or `possible_crash` markers.
The 180 lifecycle samples retain TalkBack PID `17467`, with zero restart
events and at most one Search overlay window (zero accumulation).
Fresh raw logcat after the recorded monitor start contains zero window-limit
fatal, fatal-exception, BadToken, or Helper ANR markers, and zero TalkBack
service connect/unbind/destroy events. Inspection suppression and induced
reconnect markers are absent. The source retains service-only acquisition.
Details are preserved in `targeted_acceptance_review.json`.

The device process loaded the entry fix before the final scenario restriction
was added. That restriction preserves the validated safe tap behavior for
Air Care/Energy and the actionable `map_area` behavior for Find. Air/Energy
retain their original ancestor promotion in the final source; the chosen
ancestor has the same card bounds and tap point. Final scoped snapshot replay
and the final full Python suite verify this restriction. This is not a claim
that the running device process loaded the final file hash.

## Limitations and decision

The previous Full32 rejection and its broader warning/coverage findings remain
preserved. This task makes no final accessibility-baseline approval and does
not attempt to repair Air Care's no-progress warning or other scenarios.
The monitor detects transport failures; it does not repair their production
cause. Any future real timeout remains a hard blocker.

```text
READINESS_VERDICT=READY_FOR_KOREAN_FULL32_RETRY
FULL32_RUN=NO
ENGLISH_RUN=NO
PHASE4_CHANGED=NO
```
