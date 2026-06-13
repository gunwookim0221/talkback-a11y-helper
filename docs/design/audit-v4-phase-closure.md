# Audit V4 Phase Closure

## 1. Purpose

This document closes Audit V4.

Audit V4 started as two connected tracks:

- XML-backed Coverage Audit
- reporting-only Shadow Verdict

It did **not** aim to replace V3 during this phase. The intended outcome was:

- build a ground-truth candidate surface from XML
- compare it against actual traversal evidence
- classify current plugin readiness conservatively
- keep V3 authoritative while V4 runs beside it

That outcome has been reached at the limited-shadow-operation level.

## 2. Phase 3 Summary

Phase 3 established the technical basis for V4.

Delivered capabilities:

- XML dumps are persisted under scenario `xml_dumps` output and can be reused for post-analysis.
- Candidate extraction, merging, classification, subtype tagging, and policy recommendation are available.
- XML-vs-traversal coverage can be computed from merged candidates and traversal labels.
- Required / optional / provisional interpretation is available for shadow planning.
- Taxonomy, matching, and traversal-gap analysis were pushed far enough to separate:
  - UI-absent cases
  - taxonomy/modeling issues
  - matching-shape issues
  - likely traversal misses

Most important Phase 3 outcome:

- the program stopped treating static expected-content misses as automatically authoritative
- the program gained an XML-grounded explanation layer for what was visible versus what was actually traversed

Evidence-corrected stable baseline reached by the end of Phase 3:

- Motion Sensor: stable clean coverage
- Smoke Sensor: stable clean coverage
- Door Lock: stable clean coverage
- Home Care: stable clean coverage
- Family Care: narrowed to bottom-strip residual misses
- Energy / Air Care: explainable provisional-heavy cases
- Food: still evidence-follow-up territory

## 3. Phase 4 Shadow Verdict Summary

Phase 4 turned the Phase 3 analysis into an operationally safe shadow layer.

Delivered capabilities:

- `shadow_verdict_v4` is emitted in reporting.
- V3 remains authoritative.
- V4 Shadow is reporting-only.
- `balanced_v1` policy exists as the first operational shadow policy.
- comparison, policy-tuning, provisional-only interpretation, go/no-go review, and monitoring guidance were documented.

Final Phase 4 policy reading:

- `PASS` means the stable required surface is covered well enough for shadow confidence.
- `REVIEW` means either a known residual risk or a provisional-only / policy-deferred state.
- `FAIL` remains reserved for materially broken required coverage or hard V3 failure inheritance.
- `ENVIRONMENT_ERROR` remains a runtime/artifact short-circuit.

Operationally important corrections made during Phase 4:

- `UNKNOWN` provisional-heavy Life structures no longer have to collapse into false required failure by policy intent.
- `ready_empty_denominator` no longer blocks clearly interpretable shadow-required metrics by design intent.
- provisional-only plugins are explainable review cases rather than opaque false fails.

## 4. Current State

Current working interpretation is:

### Stable Shadow PASS

- `device_motion_sensor_plugin`
- `device_smoke_sensor_plugin`
- `device_door_lock_plugin`
- `life_home_care_plugin`

### Known Risk REVIEW

- `life_family_care_plugin`
  - `EventsButton`
  - `LocationButton`
  - bottom-strip traversal/state issue

### Provisional-only REVIEW

- `life_energy_plugin`
- `life_air_care_plugin`

### Evidence Follow-up

- `life_food_plugin`

Current governance state:

- V3 verdict is authoritative.
- V4 Shadow is reporting-only.
- Shadow and V3 run side-by-side.
- current program state is `GO_LIMITED_SHADOW_OPERATION`.

## 5. Why GO_LIMITED_SHADOW_OPERATION Was Correct

The go/no-go decision is justified by four facts.

### 5.1 Stable baseline exists

The Device set plus Home Care provide a stable reference group where shadow behavior is already directionally correct and operationally useful.

### 5.2 Residual risk is narrow and named

The main unresolved functional miss is no longer broad unexplained drift. It is concentrated in Family Care bottom-strip behavior, primarily around `EventsButton`, with `LocationButton` as secondary residual risk.

### 5.3 Provisional-heavy cases are conservative

Energy and Air Care are not silently promoted to pass. They remain conservative `REVIEW` cases because they do not yet expose a stable required denominator.

### 5.4 V3 remains authoritative

Even if V4 shadow interpretation is incomplete, it does not alter production verdict handling. This makes limited parallel operation safe.

## 6. Remaining Known Risks

### 6.1 Family Care

Known residual risk:

- bottom-strip progression is deferred while content remains
- local-tab state is partly reconstructed from dump evidence instead of committed focus history
- activation can fail after late recovery
- focus realign can amplify strip-context loss

Practical reading:

- primary unresolved miss: `EventsButton`
- secondary residual miss: `LocationButton`

### 6.2 Energy / Air Care

Known residual risk:

- stable required denominator is still absent
- provisional-heavy dashboard structures remain only partially modeled
- runtime subtype tagging is not yet rich enough to graduate these plugins into stable required-surface evaluation

### 6.3 Food

Known residual risk:

- evidence quality after entry/onboarding remains weaker than the rest of the set
- Food should not be used as a readiness anchor yet

### 6.4 Artifact Variants

Known residual risk:

- regenerated artifacts can still contain environment contamination variants
- these reduce comparison convenience even when policy intent is otherwise clear

## 7. Problems Solved by V4

V4 solved these concrete problems.

### 7.1 Static expected-content false reviews

The system no longer has to interpret every missing expected string as a traversal miss. XML now provides a reality check for what was actually rendered.

### 7.2 Coverage denominator grounding

The denominator is no longer purely paper-defined. It can be derived from persisted runtime XML candidates.

### 7.3 Side-by-side verdict experimentation

Shadow Verdict now exists as a reporting layer that can be monitored without destabilizing V3.

### 7.4 Residual risk naming

The program can now describe risk more specifically:

- known Family Care bottom-strip miss
- provisional-only Life dashboards
- evidence-follow-up Food cases

### 7.5 Explainability improvement

V4 introduced the structure needed to distinguish:

- visible but unvisited candidates
- provisional candidates
- known-risk labels
- matching/traversal/taxonomy explanations

## 8. Problems Intentionally Not Solved by V4

V4 deliberately leaves several problems for later work.

### 8.1 V3 replacement

V4 does not replace V3 verdict authority.

### 8.2 Full traversal-engine root-cause accounting

V4 Coverage tells us more about visible-versus-visited surface area, but it does not yet produce a complete first-class audit of:

- why a candidate was not visited
- where focus drift occurred
- why state recovery failed
- why activation failed
- why a candidate was deprioritized or discarded

### 8.3 Full Life dashboard modeling

Energy and Air Care remain provisional-heavy by design.

### 8.4 Family Care remediation

V4 documents and isolates the bottom-strip issue, but does not fix it.

### 8.5 Food evidence stabilization

Food remains outside the primary readiness baseline.

## 9. Transition Meaning

Audit V4 should now be considered complete in scope.

What “complete” means here:

- XML-backed coverage infrastructure exists
- shadow-verdict infrastructure exists
- limited shadow operation is justified
- stable plugins are separated from known-risk and provisional-only plugins

What “complete” does **not** mean:

- traversal engine validation is finished
- all misses are root-caused automatically
- V4 is ready to replace V3

## 10. V4 Closure Declaration

Audit V4 is closed.

Closure basis:

- Phase 3 delivered XML-backed coverage and candidate interpretation.
- Phase 4 delivered reporting-only shadow verdict and limited-operation readiness.
- remaining issues are no longer V4-closure blockers; they are next-phase work items.

The next phase should not be framed as “more coverage tuning.”

The next phase should be framed as:

- `Traversal Engine Validation`
- `Traversal Engine Audit`

That is the correct continuation of the original project goal.
