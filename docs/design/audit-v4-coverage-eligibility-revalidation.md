# Audit V4 Coverage Eligibility Revalidation

## 1. Background

Audit V4 remains diagnostic-only.

Phase 3.17 split the residual required-miss problem into two different classes:

- structural local-tab labels, especially `Controls`
- real CTA reachability misses, especially `Add family member` and `View profile`

This phase revalidates denominator eligibility for local-tab labels. The main question is whether labels such as `Controls`, `History`, and `Routines` should remain required TalkBack coverage targets, or whether some of them behave more like structural navigation state than spoken traversal content.

This document is policy analysis only. It does not change coverage engine behavior, eligibility implementation, matching, traversal, verdict logic, or V3 behavior.

## 2. Local Tab Label Analysis

### 2.1 Scope

This review focuses on the device-plugin local-tab labels:

- `Controls`
- `History`
- `Routines`

These labels appear across the device evidence set:

- `device_motion_sensor_plugin`
- `device_smoke_sensor_plugin`
- `device_door_lock_plugin`

### 2.2 Evidence Summary

| Label | XML candidate exists | local-tab visited / activated | Direct TalkBack focus observed | Current denominator fit |
| --- | --- | --- | --- | --- |
| `Controls` | yes | yes | no in Smoke / Door Lock evidence | weak |
| `History` | yes | yes | yes | strong |
| `Routines` | yes | yes | yes | strong |

Key observations:

`Controls`

- Exists in XML as a local-tab actionable candidate.
- Is detected and operationally visited in all three device plugins.
- In Smoke and Door Lock, traversal logs show successful local-tab activation and commit, but no direct TalkBack focus hit for literal `Controls`.
- After activation, focus moves immediately into content within the selected tab.

Interpretation:

- `Controls` behaves like a structural state token for tab selection more than a stable spoken traversal target.

`History`

- Exists in XML as a local-tab actionable candidate.
- Is detected and visited.
- Direct TalkBack focus hits for literal `History` are repeatedly observed in Motion, Smoke, and Door Lock logs.

Interpretation:

- `History` is not merely structural. It is exposed as a spoken focus target and is a defensible required coverage candidate.

`Routines`

- Exists in XML as a local-tab actionable candidate.
- Is detected and visited.
- Direct TalkBack focus hits for literal `Routines` are observed in Motion evidence.
- There is less repeated direct evidence than `History`, but it is still materially stronger than `Controls`.

Interpretation:

- `Routines` is closer to normal spoken tab content than to a purely structural token.

### 2.3 User-Expectation Assessment

Expected TalkBack user experience by label:

| Label | Is it reasonable to expect the user to hear it during traversal? | Assessment |
| --- | --- | --- |
| `Controls` | not reliably | weak expectation |
| `History` | yes | strong expectation |
| `Routines` | yes | strong expectation |

Reasoning:

- A TalkBack user should reasonably hear `History` and `Routines` if those tabs become focused targets during movement.
- The current evidence does not support the same expectation for `Controls`. It is used to place the traversal back into the default tab, but the label itself is not reliably spoken after activation.

## 3. Structural Candidate Proposal

### 3.1 Proposed Eligibility Classification

This is a proposal only.

| Label | Proposed class | Rationale |
| --- | --- | --- |
| `Controls` | `STRUCTURAL` | important for tab-state management, but not reliably exposed as direct spoken focus content |
| `History` | `REQUIRED` | directly observed as spoken focus and meaningful user-visible navigation target |
| `Routines` | `REQUIRED` | observed as spoken focus and meaningful navigation target |

### 3.2 Meaning of `STRUCTURAL`

Proposed meaning:

- required for screen structure understanding
- relevant for runner state and tab activation
- not necessarily appropriate for TalkBack focus coverage denominator

This bucket is useful specifically for items that are:

- operationally important
- visible in XML
- sometimes activated by the runner
- but not reliably surfaced as spoken focus targets

`Controls` matches this pattern better than either `History` or `Routines`.

### 3.3 Why Not Reclassify All Local Tabs

A broad rule such as:

- all local-tab labels -> `STRUCTURAL`

is not supported by the evidence.

Why:

- `History` is repeatedly read as direct focus.
- `Routines` is also read as direct focus.
- Reclassifying all local tabs would remove legitimate spoken traversal targets from the denominator and would weaken the coverage model.

The evidence supports a narrow rule:

- `Controls` is the structural outlier
- `History` and `Routines` are not

## 4. Required Coverage Simulation

### 4.1 Simulation Inputs

Inputs preserved from earlier phases:

- seven-plugin analysis set
- Phase 3.16 Simulation D as the strongest paper-only matching scenario
- required denominator at baseline: `30`

Current reference points:

- Phase 3.16 Simulation A: `19 / 30` matched, `11` missing, `63.3%`
- Phase 3.16 Simulation D: `23 / 30` matched, `7` missing, `76.7%`

`Controls` appears as a required local-tab label in:

- `device_motion_sensor_plugin`
- `device_smoke_sensor_plugin`
- `device_door_lock_plugin`

Under Simulation D:

- `Controls` is matched in Motion
- `Controls` is missing in Smoke
- `Controls` is missing in Door Lock

Therefore excluding only `Controls` from the required denominator changes the totals by:

- denominator: `-3`
- matched: `-1`
- missing: `-2`

### 4.2 Simulation Table

| Scenario | Required denominator | Required matched | Required missing | Required coverage |
| --- | ---: | ---: | ---: | ---: |
| A. Current baseline | 30 | 19 | 11 | 63.3% |
| B. Matching Simulation D | 30 | 23 | 7 | 76.7% |
| C. Matching D + `Controls` as `STRUCTURAL` | 27 | 22 | 5 | 81.5% |
| D. Matching D + `Controls` structural + CTA unresolved | 27 | 22 | 5 | 81.5% |

### 4.3 Interpretation

Important result:

- Reclassifying only `Controls` improves required coverage from `76.7%` to `81.5%`
- Required misses drop from `7` to `5`

Why scenario D equals scenario C:

- `Add family member` and `View profile` remain required and unresolved
- the structural reclassification only removes `Controls`
- no additional denominator change is implied by CTA separation alone

### 4.4 Sensitivity Note

If all device local-tab labels (`Controls`, `History`, `Routines`) were excluded, the denominator would shrink further, but the model quality would get worse because it would also remove labels that are directly spoken today.

This is exactly why the evidence supports a narrow `Controls` reclassification, not a broad local-tab exclusion rule.

## 5. CTA Reachability Separation

The separation proposed in Phase 3.17 remains valid.

`Controls`

- primarily an eligibility / structural problem
- not a strong runner-bug signal

`Add family member`

- primarily a runner reachability problem
- visible, clickable, focusable, but deprioritized during traversal

`View profile`

- also closer to runner reachability than eligibility
- visible and actionable in XML, but not shown as a direct traversal hit

This separation is useful because it prevents two different issues from being mixed together:

- denominator overreach on structural tab tokens
- real traversal failure on user-action CTAs

Without this split, `Controls` can incorrectly inflate the severity of the traversal problem.

## 6. Phase 4 Readiness

### 6.1 Readiness Rating

Result: `PARTIAL`

### 6.2 Reasoning

Positive movement:

- Matching Simulation D raised required coverage to `76.7%`
- Reclassifying `Controls` as structural raises it further to `81.5%`
- The remaining required misses become more interpretable and less polluted by denominator ambiguity

Why not `READY` yet:

- `Add family member` and `View profile` remain unresolved CTA reachability misses
- Family Care still has residual required misses beyond the local-tab issue
- Phase 4 should not adopt a shadow verdict while structural ambiguity and CTA reachability remain mixed operationally

Why not `NOT_READY`:

- The denominator question is now much narrower
- The evidence supports a specific eligibility refinement candidate rather than a broad policy rewrite
- The remaining blockers are no longer primarily taxonomy-driven

### 6.3 Net Effect

Reclassifying `Controls` as `STRUCTURAL` would improve Phase 4 readiness materially, but not fully.

Practical reading:

- denominator policy becomes cleaner
- traversal residuals become easier to interpret
- shadow-verdict discussion gets closer, but runner-side CTA work still blocks full readiness

## 7. Recommendation

Recommended policy conclusion for analysis:

1. Keep `History` as `REQUIRED`
2. Keep `Routines` as `REQUIRED`
3. Re-evaluate `Controls` as a `STRUCTURAL` candidate rather than a required spoken-focus target

Recommended next step:

- `Phase 3.19 - CTA Reachability / Traversal Remediation Design`

Reasoning:

- the denominator ambiguity around local-tab labels is now narrow and explainable
- excluding `Controls` from required coverage would remove a misleading structural miss class
- the most important remaining misses are no longer structural; they are top-of-screen CTA reachability failures

Bottom line:

- `Controls` should not be treated the same way as `History` and `Routines`
- the evidence supports `Controls -> STRUCTURAL` as a policy proposal
- after that separation, the main unresolved blocker is runner reachability, not denominator design
