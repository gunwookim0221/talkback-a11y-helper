# Audit V5 Phase Closure

## 1. Purpose

Audit V5 was started because Audit V4 solved the wrong layer for the next question.

Audit V4 established XML-backed coverage audit and reporting-only shadow verdicts. That made discovered objects visible and made verdict comparison safer, but it did not fully answer the traversal-engine questions:

- What did the runner discover?
- What did the runner actually visit?
- What did the runner miss?
- Why did the miss happen?

Audit V5 re-centered the work around **Traversal Engine Audit**, not coverage expansion.

The purpose was to make traversal behavior explainable from existing artifacts without changing runner behavior.

## 2. What V5 Delivered

V5 delivered the following assets:

- Traversal Event Inventory: documented existing lifecycle, focus, activation, local-tab, discovery, selection, and recovery signals.
- Normalized Event Schema: defined canonical event semantics for `DISCOVERED`, `SELECTED`, activation, focus, state, `VISITED`, and `MISSED`.
- Offline Traversal Parser: implemented an offline parser that reconstructs traversal audit events from existing artifacts.
- Candidate Ledger: built a candidate-level ledger with discovery, selection, activation, focus, recovery, visit, miss, and root-cause state.
- Root Cause Attribution: added event-backed attribution for activation failure, realign failure, state recovery failure, bottom-strip misses, local-tab misses, discarded candidates, policy/deprioritized candidates, focus drift, and unknowns.
- Miss Attribution Calibration: reduced over-broad `UNKNOWN` outcomes by using existing bottom-strip, local-tab, chrome exclusion, composite-row, and focus-realign evidence.
- Operational Monitoring Guidance: defined metrics, regression signals, watchlist plugins, known limitation monitoring, and readiness posture.

Primary implementation files:

- `tools/audit_v5_traversal_engine.py`
- `tools/audit_v5_traversal_core.py`
- `tools/audit_v5_traversal_report.py`
- `tests/test_audit_v5_traversal_engine.py`

Primary design documents:

- `docs/design/audit-v5-traversal-engine-audit.md`
- `docs/design/audit-v5-phase5a-traversal-event-inventory.md`
- `docs/design/audit-v5-phase5a-normalized-event-schema.md`
- `docs/design/audit-v5-phase5c-traversal-audit-validation.md`
- `docs/design/audit-v5-phase5d-operational-review.md`

## 3. Validation Results

Final validation used the Phase 5B sample reports:

- `output/audit_v5_phase5b_motion_after/traversal_audit.json`
- `output/audit_v5_phase5b_smoke_after/traversal_audit.json`
- `output/audit_v5_phase5b_door_lock_after/traversal_audit.json`
- `output/audit_v5_phase5b_home_after/traversal_audit.json`
- `output/audit_v5_phase5b_family_after/traversal_audit.json`

| Plugin | Discovered | Visited | Missed | Unknown | Attribution Rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Motion Sensor | 13 | 10 | 3 | 1 | 0.6667 |
| Smoke Sensor | 13 | 11 | 2 | 0 | 1.0000 |
| Door Lock | 13 | 11 | 2 | 0 | 1.0000 |
| Home Care | 10 | 9 | 1 | 0 | 1.0000 |
| Family Care | 39 | 33 | 8 | 3 | 0.6250 |

Root-cause summary:

| Plugin | Root Cause Summary |
| --- | --- |
| Motion Sensor | `CANDIDATE_DISCARDED=2`, `UNKNOWN=1` |
| Smoke Sensor | `CANDIDATE_DISCARDED=2` |
| Door Lock | `CANDIDATE_DISCARDED=2` |
| Home Care | `CANDIDATE_DISCARDED=1` |
| Family Care | `BOTTOM_STRIP_MISS=1`, `CANDIDATE_DISCARDED=4`, `UNKNOWN=3` |

Final readiness assessment:

```text
READY_WITH_LIMITATIONS
```

## 4. Why V5 Was Successful

V5 was successful because it made traversal outcomes explainable from existing artifacts.

Specific outcomes:

- Family Care `UNKNOWN` misses were reduced from 14 to 3 after miss attribution calibration.
- Stable PASS plugins now show bounded unknowns: Home Care `0`, Smoke Sensor `0`, Door Lock `0`, Motion Sensor `1`.
- The parser separates actual visit evidence from discovered-only XML evidence.
- Misses are now grouped into event-backed root causes instead of collapsing into generic coverage gaps.
- The output supports offline audit, run-to-run comparison, and candidate-level investigation.
- Runner behavior was not changed to achieve these audit results.

The most important success criterion was not perfect accuracy.

The most important success criterion was explainability.

V5 met that criterion.

## 5. Current Governance State

Audit governance now has three layers:

- V3 verdict remains authoritative.
- V4 shadow verdict remains reporting-only.
- V5 traversal audit remains reporting-only.

Operational relationship:

- V3 decides the authoritative scenario result.
- V4 compares coverage and shadow verdict behavior without replacing V3.
- V5 explains traversal behavior and root causes without replacing V3 or V4.

V5 should be used to investigate and monitor traversal quality.

It should not be used as an authoritative verdict system.

## 6. Known Limitations

Known limitations at V5 closure:

- Profile/header surface candidates can remain `UNKNOWN` when no selection, visit, or discard signal is emitted.
- XML-only candidates remain `UNKNOWN` when discovery is the only available evidence.
- Current active bottom-strip tab semantics are not yet modeled as canonical current-state or visited outcomes.
- Ambiguous compound labels still require conservative matching.
- `UNKNOWN` means insufficient normalized evidence, not automatically a traversal defect.
- The parser explains observed artifacts; it does not infer runner intent from XML alone.

Current known residual examples:

- Family Care: `ActivityButton`, `Me`, `View profile`
- Motion Sensor: `Motion detection notifications, Example: every day, 6:00 PM - 10:00 PM`

## 7. Problems Solved

V5 solved these problems:

- Converted distributed lifecycle, XML, focus, activation, and local-tab signals into a normalized audit model.
- Created a candidate ledger that tracks per-object state instead of only aggregate coverage.
- Reconstructed `DISCOVERED`, `VISITED`, `MISSED`, and root-cause outcomes offline.
- Distinguished policy/discard misses from unexplained misses.
- Added explainability for bottom-strip and local-tab related outcomes.
- Added report formats suitable for humans and machines.
- Established operational metrics and regression signals for run-to-run monitoring.

## 8. Problems Intentionally Not Solved

V5 intentionally did not solve these problems:

- It did not improve traversal behavior.
- It did not change candidate selection.
- It did not change focus realign algorithms.
- It did not change local-tab algorithms.
- It did not change V4 shadow verdict policy.
- It did not tune coverage thresholds.
- It did not replace V3 verdicts.
- It did not create an authoritative release gate.
- It did not infer missing traversal decisions from XML-only evidence.

These were explicitly out of scope because V5 was an audit and reporting phase, not a runner behavior phase.

## 9. Recommended Operational Usage

Recommended uses:

- audit tool for discovered / visited / missed accounting
- regression signal for `unknown_miss_count`, `miss_attribution_rate`, `visit_rate`, and root-cause mix
- root-cause investigation tool for activation, focus, local-tab, bottom-strip, discard, and policy outcomes
- watchlist monitoring for Family Care and Motion Sensor
- stable-plugin control signal for Home Care, Smoke Sensor, and Door Lock

Not recommended uses:

- authoritative verdict
- release gate
- V3 replacement
- V4 shadow verdict replacement
- global threshold system across all plugins
- raw `UNKNOWN` count as a standalone failure signal

## 10. Transition Meaning

Audit V5 closure does not imply that V6 is required.

The next step depends on operational needs.

If further work is pursued, plausible directions include:

- add baseline comparison tooling for run-to-run monitoring
- improve current active bottom-strip tab semantics
- add profile/header surface instrumentation if those candidates become operationally important
- add dashboard or batch aggregation around existing JSON reports

If no further work is pursued immediately, V5 is still useful as a controlled reporting and investigation layer.

## 11. Closure Declaration

Audit V5 is closed.

Closure basis:

- the V5 north star was defined as Traversal Engine Audit
- the existing event inventory was documented
- a normalized event schema was designed
- an offline parser was implemented
- candidate ledger and root-cause attribution were implemented
- miss attribution calibration improved explainability
- validation showed `READY_WITH_LIMITATIONS`
- operational reporting and monitoring guidance was documented
- V3/V4/V5 governance boundaries remain clear

Audit V5 ends as a reporting-only traversal audit system that is ready for controlled operational use with known limitations.

## 12. Code Change Status

No code changes were made for this closure document.

## 13. Test Status

Pytest was not run for this closure document.

## 14. Git Status

Expected working tree delta after this document:

- `docs/design/audit-v5-phase-closure.md`
