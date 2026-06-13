# Audit V4 Shadow Operation Monitoring

## 1. Background

Audit V4 Shadow Verdict is now approved for limited shadow operation.

Current operating principles:

- V3 remains the authoritative production verdict
- V4 Shadow remains reporting-only
- Shadow results do not change operational pass/review/fail handling
- Shadow is used for comparison, monitoring, and policy validation

Phase 4D concluded:

- `GO_LIMITED_SHADOW_OPERATION`

That decision was based on the current post-4C-3 state:

- Device plugins are stable shadow-pass cases
- Home Care is a stable shadow-pass case
- Family Care remains a known-risk review case
- Energy and Air Care remain explainable provisional-only review cases
- Food still belongs to evidence follow-up rather than readiness scoring

This phase defines how to monitor that state without changing policy or code.

## 2. Monitoring Scope

### 2.1 Stable Shadow Pass Group

Primary baseline group:

- `device_motion_sensor_plugin`
- `device_smoke_sensor_plugin`
- `device_door_lock_plugin`
- `life_home_care_plugin`

Monitoring goal:

- confirm that stable required surfaces keep producing expected `PASS`
- detect regressions where stable scenarios fall from `PASS` to `REVIEW` or
  `FAIL`
- use this group as the main health signal for Shadow operation quality

### 2.2 Known-Risk Review Group

Focused watchlist:

- `life_family_care_plugin`

Monitoring goal:

- confirm that the current shadow `REVIEW` remains narrow and explainable
- verify that known risk labels remain centered on:
  `EventsButton`, `LocationButton`
- detect any expansion beyond the known bottom-strip risk

### 2.3 Provisional-Only Review Group

Policy-deferred group:

- `life_energy_plugin`
- `life_air_care_plugin`

Monitoring goal:

- confirm that these remain explainable provisional-only `REVIEW`
- track whether provisional load is stable, shrinking, or unexpectedly growing
- confirm that these do not turn into unexplained `FAIL` or unstable
  environment cases

### 2.4 Evidence Follow-Up Group

Secondary evidence group:

- `life_food_plugin`

Monitoring goal:

- keep Food out of the primary readiness baseline
- track whether post-entry evidence quality becomes stable enough for later
  shadow inclusion

## 3. Metrics

Recommended monitoring metrics per scenario:

| Metric | Meaning | Why monitor it |
| --- | --- | --- |
| `v3_verdict` | production verdict | authoritative baseline |
| `shadow_verdict_v4` | shadow-only verdict | core Phase 4 signal |
| `v3_shadow_agreement` | agreement / disagreement category | quick mismatch detection |
| `shadow_required_coverage` | required coverage percentage | primary shadow quality indicator |
| `shadow_required_missing_count` | count of missing required candidates | tracks residual coverage misses |
| `shadow_traversal_gap_count` | required misses classified as traversal gaps | detects likely runner-side regression |
| `shadow_taxonomy_gap_count` | required misses classified as taxonomy gaps | detects policy/modeling drift |
| `shadow_matching_gap_count` | required misses classified as matching gaps | detects label-shape drift |
| `shadow_known_risk_labels` | sampled labels behind the shadow result | explanation and drift detection |
| `provisional_candidate_count` | provisional candidate load | tracks provisional-only behavior |
| `shadow_reason` | summarized decision explanation | fast triage field |
| `environment_error` or `ENVIRONMENT_ERROR` count | run instability signal | separates policy issues from artifact/runtime issues |

Recommended aggregate metrics across repeated runs:

- stable-group shadow pass rate
- stable-group V3/Shadow agreement rate
- Family Care known-risk label stability rate
- provisional-only review frequency for Energy and Air Care
- environment error rate by plugin

## 4. Alert Rules

### 4.1 Immediate Review Alerts

Trigger immediate review when:

- `shadow_verdict_v4 = FAIL`
- a stable shadow pass plugin changes from `PASS` to `REVIEW` or `FAIL`
- `life_family_care_plugin` produces new required misses beyond
  `EventsButton` and `LocationButton`
- `environment_error` appears repeatedly in the stable group

Interpretation:

- these are the strongest signals of either regression or reporting drift

### 4.2 Comparison Alerts

Investigate when:

- `V3 PASS` but `Shadow REVIEW`
- `V3 PASS` but `Shadow FAIL`
- `V3 REVIEW` but `Shadow PASS`

Interpretation:

- `V3 PASS` with worse shadow usually means a new required-surface miss,
  traversal regression, or eligibility drift
- `V3 REVIEW` with shadow `PASS` may indicate V3 expected-content conservatism
  rather than a real V4 problem

### 4.3 Watchlist Drift Alerts

Investigate watchlist drift when:

- `shadow_known_risk_labels` changes materially for Family Care
- `provisional_candidate_count` spikes for Energy or Air Care
- `shadow_reason` changes from provisional-only wording to traversal- or
  coverage-failure wording
- `shadow_traversal_gap_count` becomes nonzero in a plugin that was previously
  provisional-only

Interpretation:

- these patterns suggest taxonomy drift, artifact drift, or a newly emerging
  traversal issue

### 4.4 Environment Alerts

Investigate environment health when:

- `ENVIRONMENT_ERROR` frequency increases over repeated runs
- Family Care regenerated artifacts repeatedly land in environment-error state
- stable-group scenarios start failing before shadow-specific logic is even
  evaluated

Interpretation:

- these alerts are not shadow-policy failures first
- they usually indicate device, preflight, artifact, or runner-environment
  instability

## 5. Run Cadence

### 5.1 Smoke-Level Cadence

Run the stable baseline group:

- `device_motion_sensor_plugin`
- `device_smoke_sensor_plugin`
- `device_door_lock_plugin`
- `life_home_care_plugin`

Recommended cadence:

- daily if the team is actively touching audit logic
- otherwise after any change that affects audit reporting, eligibility,
  traversal interpretation, or scenario selection

Purpose:

- keep the fastest possible early-warning set

### 5.2 Watchlist Cadence

Run the watchlist group:

- `life_family_care_plugin`
- `life_energy_plugin`
- `life_air_care_plugin`
- `life_food_plugin`

Recommended cadence:

- weekly during limited shadow operation
- additionally after any plugin-specific UI, traversal, or subtype-related
  change

Purpose:

- monitor known unstable or policy-deferred cases without making them the daily
  health anchor

### 5.3 Full Comparison Cadence

Run the full shadow comparison set before:

- releases
- major audit refactors
- shadow reporting schema changes
- any future go/no-go re-evaluation

Purpose:

- validate that limited shadow operation still matches the intended safety
  posture

## 6. Exit Criteria

Recommended exit criteria for graduating beyond early limited shadow operation:

1. Stable group keeps `PASS` agreement across at least 2 to 3 consecutive runs.
2. No new stable-group `Shadow REVIEW` or `Shadow FAIL` appears without a clear
   artifact/environment explanation.
3. Family Care remains bounded to the current known-risk set or improves.
4. Energy and Air Care remain explainable provisional-only `REVIEW` with no
   unexplained drift in `shadow_reason` or `known_risk_labels`.
5. No recurring unexplained `Shadow FAIL` appears in any monitored plugin.
6. `ENVIRONMENT_ERROR` cases are separable as runtime/artifact issues rather
   than shadow-policy ambiguity.

Recommended interpretation:

- exit does not mean production verdict replacement
- exit means the shadow monitoring layer is stable enough to support the next
  implementation or integration decision

## 7. Watchlist

### 7.1 Family Care Watchlist

Items:

- `EventsButton`
- `LocationButton`
- regenerated `ENVIRONMENT_ERROR` artifact recurrence

Question to monitor:

- does the review remain the same localized bottom-strip problem

### 7.2 Energy Watchlist

Items:

- provisional-only review persistence
- provisional candidate count trend
- known risk label stability

Question to monitor:

- does Energy remain policy-deferred, or does it show signals that subtype
  tagging work should be prioritized sooner

### 7.3 Air Care Watchlist

Items:

- provisional-only review persistence
- provisional candidate count trend
- drift from advisory review into required-gap behavior

Question to monitor:

- does Air Care stay stable as a provisional-only case

### 7.4 Food Watchlist

Items:

- evidence quality after entry/onboarding
- repeatability of post-entry artifact capture

Question to monitor:

- is Food becoming stable enough to join the main shadow comparison set

## 8. Next Work Items

Recommended priority:

1. Family Care bottom-strip remediation
2. Runtime subtype tagging enhancement for Energy and Air Care
3. Food evidence follow-up
4. Shadow dashboard / report UX improvement
5. Later: limited production integration planning

Rationale:

- Family Care is the clearest real functional miss still visible in shadow
- Energy and Air Care are explainable today, but subtype tagging is the main
  route to reducing provisional-only review volume
- Food remains an evidence-readiness problem, not a primary shadow blocker
- better reporting UX becomes more valuable once monitoring is running
- production integration should come only after shadow monitoring proves stable

Bottom line:

- the monitoring plan should treat Device plugins and Home Care as the stable
  baseline
- Family Care should stay on an explicit known-risk watchlist
- Energy and Air Care should stay on a provisional-only watchlist
- Food should remain an evidence follow-up case until its artifacts are stable
