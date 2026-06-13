# Audit V5 Phase 5C Traversal Audit Validation

## 1. Purpose

Phase 5C validates whether the Audit V5 offline parser is explainable enough to operate as a traversal audit tool.

The validation target is not perfect accuracy. The target is whether the parser can give useful, auditable answers for:

- discovered candidates
- visited candidates
- missed candidates
- attributed root causes
- remaining unknowns

The parser remains reporting-only. Runner behavior, traversal logic, V4 shadow verdict policy, report schema, and root-cause priority are unchanged.

## 2. Supported Plugin Scope

Phase 5C covers the currently exercised plugin set:

- Motion Sensor
- Smoke Sensor
- Door Lock
- Home Care
- Family Care

These scenarios cover stable device plugins, a stable service plugin, and the known-risk Family Care plugin with local-tab and bottom-strip behavior.

## 3. Plugin Summary Table

Source reports:

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

## 4. Remaining UNKNOWN Analysis

### Family Care

Remaining `UNKNOWN` candidates:

- `ActivityButton`
- `Me`
- `View profile`

#### `ActivityButton`

Evidence:

- Discovered from XML in `000_step_001_entry.xml` and `001_step_019_viewport_exhausted.xml`.
- Candidate metadata: `candidate_subtype=NAV_TILE`, `policy_recommendation=REVIEW`.
- The XML node is the selected bottom-strip tab surface.

Assessment:

- This is likely a parser limitation around selected/current bottom-strip tab semantics.
- The runner sees `ActivityButton` as the active tab, but the normalized parser does not yet model "already active tab" as an explicit visit or discard outcome.
- It should remain `UNKNOWN` until V5 introduces a canonical active-tab/current-tab event or an explicit current-tab visited rule.

Classification:

- Parser gap, but acceptable for Phase 5C because it is explainable and isolated to current-tab strip semantics.

#### `Me`

Evidence:

- Discovered from XML in `000_step_001_entry.xml` and `001_step_019_viewport_exhausted.xml`.
- Candidate metadata: `candidate_type=STATUS`, `candidate_subtype=STATUS_LABEL`, `policy_recommendation=KEEP`.
- Appears in the Family Care profile/header surface.

Assessment:

- The candidate is visible in the header/profile area, but no traversal event commits it as visited and no policy event discards it.
- Treating it as visited from XML alone would overstate traversal evidence.
- Treating it as discarded would require a header/profile policy signal that the runner does not currently emit.

Classification:

- Normal `UNKNOWN` for Phase 5C.

#### `View profile`

Evidence:

- Discovered from XML in `000_step_001_entry.xml` and `001_step_019_viewport_exhausted.xml`.
- Candidate metadata: `candidate_type=ACTIONABLE`, `candidate_subtype=CTA`, `policy_recommendation=KEEP`.
- Appears in the Family Care profile/header surface.

Assessment:

- This is an actionable profile/header CTA with XML evidence, but no selected, activation, focus, recovery, visited, or discard event.
- It may be a real traversal gap, but the offline parser cannot attribute it without a runner signal distinguishing skipped header/profile action from unvisited content.

Classification:

- Normal `UNKNOWN` with a likely instrumentation gap.

### Motion Sensor

Remaining `UNKNOWN` candidate:

- `Motion detection notifications, Example: every day, 6:00 PM - 10:00 PM`

Evidence:

- Discovered from XML in `001_step_004_local_tab_transition_Routines.xml`.
- Candidate metadata: `candidate_type=INSTRUCTIONAL`, `candidate_subtype=INSTRUCTIONAL_STATUS`, `policy_recommendation=REVIEW`.
- No selected, activation, focus, local-tab recovery, visited, discarded, or policy-deprioritized event exists for this candidate.

Assessment:

- Keeping this candidate as `UNKNOWN` is correct.
- The parser has only XML discovery evidence. Assigning a root cause would require a heuristic that is not grounded in traversal events.
- This is a useful residual signal: the Routines tab exposes an instructional/status row that the current instrumentation does not explain.

Classification:

- Normal `UNKNOWN`.

## 5. Readiness Assessment

Overall assessment:

```text
READY_WITH_LIMITATIONS
```

Rationale:

- The parser explains all misses in Home Care, Smoke Sensor, and Door Lock.
- Motion Sensor has one unresolved XML-only instructional candidate.
- Family Care still has three unresolved profile/header/current-tab candidates, but the unresolved cases are bounded and understandable.
- The parser now distinguishes traversal misses from policy/discard outcomes well enough to support investigation.
- The parser is not yet strong enough to be treated as an authoritative correctness metric.

## 6. Known Limitations

- Profile/header surface candidates can remain `UNKNOWN` when the runner does not emit selection, visit, or discard evidence.
- XML-only candidates remain `UNKNOWN` unless they are connected to lifecycle, focus, local-tab, activation, visited-row, or policy signals.
- Current active bottom-strip tabs are not yet modeled as canonical visited/current-state outcomes.
- Ambiguous compound labels still depend on conservative contained-label matching.
- The parser can explain observed events; it should not infer missing traversal decisions from XML alone.
- `UNKNOWN` should be interpreted as "insufficient normalized evidence", not automatically as a traversal defect.

## 7. Operational Recommendation

Recommended uses:

- Use as an audit tool for discovered / visited / missed accounting.
- Use as a regression signal for unexpected increases in `missed_count`, `unknown_miss_count`, or drops in `miss_attribution_rate`.
- Use as a root-cause investigation aid when reviewing activation, focus, local-tab, bottom-strip, and discard behavior.

Not recommended uses:

- Do not use as the authoritative product verdict.
- Do not use as a replacement for V3 verdicts or V4 shadow verdict.
- Do not use raw `UNKNOWN` count as a failure threshold without plugin-specific review.
- Do not use as a coverage-threshold tuning mechanism.

## 8. Phase 5C Conclusion

Phase 5C validates that the V5 parser has crossed the minimum explainability bar for offline traversal auditing.

It can now answer:

- what was discovered
- what was visited
- what was missed
- which misses have event-backed root causes
- which misses remain unresolved due to insufficient instrumentation

The parser is ready for controlled operational use as a reporting and investigation tool, with limitations around profile/header surfaces, XML-only candidates, and current active bottom-strip semantics.

No runner behavior changes are required for this readiness level.

## 9. Code Change Status

No code changes were made for Phase 5C.

This document is the only Phase 5C change.

## 10. Test Status

Pytest was not required for Phase 5C document creation.

The validation data is based on existing Phase 5B sample reports.

## 11. Git Status

Expected working tree delta after this document:

- `docs/design/audit-v5-phase5c-traversal-audit-validation.md`
