# TalkBack Service-Preserving Hierarchy Fix — 2026-10-09

## Decision and scope

The service-preserving hierarchy change and the narrow `menu_main` compatibility
change passed the final pre-publish regression gate on branch
`fix/service-preserving-hierarchy-acquisition`, starting from
`b26c6432cc8edc8eacdc724ffb3e05a54e737451` (`origin/main`). This document records
the implementation and the evidence that allowed publication to proceed. It does
not claim a Full32 result; Full32 is a separate single-run acceptance phase.

The worktree and all existing evidence under `out/`, `output/`, `tests/out/`,
`qa_frontend_runs/`, and the `s1/` directories were preserved.

## Proven lifecycle cause

The reproduced failure chain is:

1. Normal QA paths acquired hierarchy through a suppressing UIAutomation /
   `uiautomator dump` call.
2. Android removed the active accessibility service connection and its overlay
   token while UIAutomation was registered.
3. TalkBack reconnected in the same process and attached a new Search overlay
   without removing its old client-side view record.
4. Repeated service suppression/reconnection accumulated Search overlay client
   records until TalkBack reported `window count is over max!!` and later failed
   while attaching an overlay.

The causal timeline, device traces, and limits of the evidence are preserved in
[`talkback-window-fatal-rca-20261009.md`](talkback-window-fatal-rca-20261009.md).
The issue was automation-triggered; this fix does not claim that the underlying
TalkBack overlay cleanup behavior has changed.

## Acquisition architecture

The old `AdbDevice._dump_ui()` path launched the Android `uiautomator dump`
command. Runner fallback readers also reached the same suppressing acquisition
path for context, plugin, and supplementary evidence.

The active QA path now requests a snapshot from the already-enabled Helper
`AccessibilityService`:

1. The runner sends `DUMP_HIERARCHY` with a unique request ID.
2. The service copies its service-owned active-window hierarchy and emits a
   request-correlated payload, chunked when needed, followed by a terminal
   marker.
3. The client validates request identity, chunk completeness, and terminal
   count. Missing or malformed data is an explicit acquisition/transport error;
   it does not fall back to UIAutomation.
4. Compatibility XML used by legacy parsers is serialized from that same Helper
   snapshot. It is not an independent UIAutomator capture.

This preserves the hierarchy information required by the runner while keeping
the TalkBack accessibility service connected.

## Active call-site audit

The production QA path was audited across `qa_frontend/backend`, `tb_runner`,
`talkback_lib`, `script_test.py`, and the Helper service. No suppressing
hierarchy acquisition call remains reachable from normal QA execution. The old
`AdbDevice._dump_ui()` method was removed. `plugin_probe` and crash capture
serialize the service-owned snapshot; XML parsers and bounds parsers do not
acquire a hierarchy themselves.

Standalone manual/diagnostic utilities still contain UIAutomator acquisition
and are not referenced by the normal QA runner, frontend backend, or
`script_test.py`:

| Utility | Purpose |
| --- | --- |
| `capture_debug_bundle.py`, `capture_debug_single.py`, `capture_focus_probe.py` | Explicit debug/focus evidence bundles |
| `talkback_visualizer.py` | Standalone visualizer capture |
| `tools/capture_devices_tab.py` | Manual Devices-tab cross-check |
| `tools/state_fingerprint_diagnostic.py` | Standalone state-fingerprint diagnostic |
| `compare_trees.py` | Manual `uiautomator2` tree comparison |

These tools must not be invoked as part of a TalkBack-active QA run. Their XML
must not be used as required acceptance evidence. The UIAutomator commands in
historical RCA text and preserved capture bundles are evidence, not active code.

## Lifecycle validation

Preserved device evidence is under
`qa_frontend_runs/service_preserving_hierarchy_20261009/` and
`qa_frontend_runs/batch_20261009_085505/`.

- Service hierarchy micro-read: `micro_result_chunked_v2.json` reports 120
  requested, 120 completed, zero failures, `status=PASS`, and the same TalkBack
  PID (`17467`) before and after. The observed Helper window count stayed at 4.
- Targeted lifecycle stress: batch `batch_20261009_085505` ran on
  `SM-F741N` / `R3CX40QFDBP` for 45m17s; PID `17467` remained stable, all five
  selected scenarios reached terminal state, and the monitor stop reason was
  empty. A separate active-window monitoring interval is preserved alongside
  it. The recorded combined targeted exposure was 72m56s.
- The stress runner log has no UIAutomator dump, window-count fatal,
  `BadTokenException`, Helper ANR, TalkBack PID-change event, or inspection
  reconnect. Search overlay count stayed bounded; no accumulation was reported.
- The stress batch predates the Menu-only compatibility change. Its
  `menu_main` entry failure is the known pre-fix reproduction and is not used as
  post-fix Menu acceptance evidence.

The `batch_20261009_085505` status includes scenario warnings and a pre-fix Menu
entry failure. Its lifecycle evidence is used only for the hierarchy lifecycle
gate, not to claim that all five scenarios passed.

## Menu semantic compatibility RCA and fix

The historical `scope_not_eligible` message was emitted by
`evaluate_post_entry_landing_evidence()`, after Menu tab selection and content
readiness had already succeeded. Its `scenario_start` guard expected
`screen_context_mode=new_screen`, while `menu_main` correctly used
`bottom_tab`; the later stabilization contract also expected
`anchor_only` instead of Menu's `anchor_then_context`. The generic fallback
anchor therefore failed to satisfy an unrelated content-screen landing
contract. This was not evidence that the Helper hierarchy had changed Menu
semantics.

The compatibility change is limited to `menu_main`:

- `screen_context_mode=bottom_tab` remains unchanged.
- `stabilization_mode=tab_context` uses the verified selected Menu tab and
  ready content root for entry.
- The base scenario and `config/runtime_config.json` runtime override both set
  the mode because the runtime override is applied after the base definition.
- Other tabs retain their existing anchor contract. No global anchor, scope,
  or safety predicate was weakened.

Post-fix device evidence:

| Run | Scenario | Entry / traversal | Result |
| --- | --- | --- | --- |
| `20261009_135521` | `menu_main` | selected Menu context and ready root accepted; `attempted_steps=6`, 5 successful moves | expected explicit 5-step `INCOMPLETE_SAFETY_LIMIT`; no anchor abort, `scope_not_eligible`, crash, possible crash, or timeout |
| `20261009_135722` | `menu_main` repeat | same entry result; `attempted_steps=6`, 5 successful moves | same expected safety limit; no listed failure |
| `20261009_135915` | `home_main` control | remained `anchor_then_context`; 6 attempts, 6 successful moves | expected explicit safety limit; no crash, possible crash, or timeout |

All three runs finalized their evidence ledger with `PASS` and process return
code 0. The two Menu runs demonstrate entry and traversal start, not full
scenario completion. The Python scenario change is restricted to Menu; the
Home control confirms its prior anchor contract remains active.

## Final pre-publish regression

| Gate | Result |
| --- | --- |
| Python suite | `3124 passed, 1 skipped`; invoked with `tests/` as the sole pytest collection target so preserved output folders were not collected |
| Helper unit suite | `384 tests, 0 failures, 0 errors, 0 skipped` |
| APK | `assembleDebug` PASS; rebuilt APK reinstalled on `R3CX40QFDBP`; installed SHA-256 equals build SHA-256 `a9f9315817cc9e8c4a5a1f994a4d0db552558c10c307f545200814b8dcab8a74` |
| Active suppressing hierarchy calls | `0` in normal QA execution; remaining standalone diagnostic utilities are listed above |
| Menu compatibility | confirmed by two Menu device runs and the Home control; runtime effective mode is `tab_context` for Menu |
| Diff check | one pre-existing `talkback_lib/adb_device.py:190` blank-line-at-EOF warning; no other whitespace errors |

**Pre-publish gate: PASS.** The validated fix commit exists locally. Automatic
approval review blocked pushing it to the configured `origin` because remote
ownership was not verified. Main merge and the separately monitored Korean
Full32 acceptance run have therefore not started.
