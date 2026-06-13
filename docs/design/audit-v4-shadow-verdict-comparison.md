# Audit V4 Shadow Verdict Comparison

## 1. Background

Phase 4B added `shadow_verdict_v4` without changing the operational V3 verdict.
This phase validates whether the implemented `balanced_v1` shadow policy behaves
the way the Phase 4A design expected when applied to existing audit artifacts.

The comparison target is not code correctness in isolation. The real question is
whether current emitted V4 shadow outputs are:

- consistent with the evidence-corrected Phase 3 conclusions
- stricter or looser than intended
- usable as the basis for Phase 4D shadow monitoring

## 2. Compared Artifacts

Primary generated reports used in this comparison:

- `output/audit_v4_phase3_8_evidence/audit_report.json`
- `output/audit_v4_phase3_12_food_energy/audit_report.json`
- `output/audit_v4_phase3_12_life_optional/audit_report.json`

Family Care normal-artifact reference used for separation analysis:

- `output/audit_v4_phase3_8_evidence/life_family_care_plugin/talkback_compare_20260611_234540.normal.log`
- [audit-v4-residual-required-miss-analysis.md](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v4-residual-required-miss-analysis.md:214)
- [audit-v4-family-care-bottom-strip-root-cause.md](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v4-family-care-bottom-strip-root-cause.md:15)

Comparison scope:

- `device_motion_sensor_plugin`
- `device_smoke_sensor_plugin`
- `device_door_lock_plugin`
- `life_family_care_plugin`
- `life_home_care_plugin`
- `life_energy_plugin`
- `life_air_care_plugin`

## 3. Comparison Matrix

| scenario_id | artifact basis | v3_verdict | v3_reason | shadow_verdict_v4 | shadow_reason | required_coverage | required_missing_count | known_risk_labels | agreement |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| `device_motion_sensor_plugin` | regenerated report | `PASS` | `All detected tabs visited; repeat_no_progress after exhaustion` | `PASS` | `required_coverage>=90 and required_missing_count<=1 and no traversal/taxonomy gaps` | 100.0 | 0 | - | `AGREE` |
| `device_smoke_sensor_plugin` | regenerated report | `PASS` | `All detected tabs visited; repeat_no_progress after exhaustion` | `PASS` | `required_coverage>=90 and required_missing_count<=1 and no traversal/taxonomy gaps` | 100.0 | 0 | - | `AGREE` |
| `device_door_lock_plugin` | regenerated report | `PASS` | `All detected tabs visited; repeat_no_progress after exhaustion` | `PASS` | `required_coverage>=90 and required_missing_count<=1 and no traversal/taxonomy gaps` | 100.0 | 0 | - | `AGREE` |
| `life_family_care_plugin` | current regenerated report | `ENVIRONMENT_ERROR` | `Failed to reach device inventory` | `ENVIRONMENT_ERROR` | `environment_error=true` | 40.0 | 3 | `EventsButton`, `LocationButton` | `V3_ENV_SHADOW_ENV` |
| `life_family_care_plugin` | evidence-corrected normal artifact, inferred from Phase 3 docs | `REVIEW` | normal traversal artifact with residual bottom-strip miss | `REVIEW` | expected balanced outcome with residual required miss retained | 92.0 | 2 | `EventsButton`, `LocationButton` | `V3_REVIEW_SHADOW_REVIEW` |
| `life_home_care_plugin` | regenerated report | `REVIEW` | `repeat_no_progress` | `REVIEW` | `coverage_not_ready:ready_empty_denominator` | 100.0 | 0 | - | `AGREE` |
| `life_energy_plugin` | regenerated report | `REVIEW` | `repeat_no_progress` | `FAIL` | `required_coverage<50` | 47.8 | 12 | - | `V3_REVIEW_SHADOW_FAIL` |
| `life_air_care_plugin` | regenerated report | `REVIEW` | `repeat_no_progress` | `REVIEW` | `coverage_not_ready:ready_empty_denominator` | 83.3 | 1 | - | `AGREE` |

Notes:

- The second Family Care row is not reconstructed from a preserved
  `audit_report.json`. It is an evidence-corrected analytical row derived from
  the Phase 3.20 and Phase 3.21 documents.
- The current regenerated Family Care report is contaminated by an
  `ENVIRONMENT_ERROR` artifact and should not be treated as the normal Family
  Care comparison baseline.

## 4. Disagreement Analysis

### 4.1 Exact Disagreement

Only one direct verdict disagreement appears in the regenerated reports:

- `life_energy_plugin`: `V3 REVIEW` vs `V4 shadow FAIL`

Root cause:

- V3 stays at `REVIEW` because traversal completed with `repeat_no_progress`
  style ambiguity.
- V4 shadow falls to `FAIL` because the current emitted required denominator is
  `23`, matched is `11`, and required coverage drops to `47.8%`.
- This is materially stricter than the Phase 4A design assumption, which treated
  Energy as a case where the stable required surface was effectively covered and
  provisional uncertainty should remain advisory.

Interpretation:

- This is not evidence that Balanced is too loose.
- It is evidence that the current emitted inputs feeding Balanced are more
  aggressive than the design baseline expected.

### 4.2 Semantic Mismatch Without Verdict Mismatch

Two plugins keep the same top-level verdict as V3, but for reasons that suggest
the current shadow output is still not policy-clean:

- `life_home_care_plugin`
  - V3: `REVIEW`
  - Shadow: `REVIEW`
  - Required metrics are actually clean: `100%`, `0` miss, `0` traversal gap,
    `0` taxonomy gap.
  - The shadow verdict remains `REVIEW` only because of
    `coverage_not_ready:ready_empty_denominator`.

- `life_air_care_plugin`
  - V3: `REVIEW`
  - Shadow: `REVIEW`
  - Required metrics are not catastrophic: `83.3%`, `1` miss, `1` traversal
    gap.
  - The emitted reason again depends on `ready_empty_denominator`, not on the
    balanced thresholds alone.

Interpretation:

- These rows do not show policy looseness.
- They show that the current shadow output still carries a readiness gate that
  can dominate the policy result even when required metrics are already
  interpretable.

## 5. Family Care Artifact Notes

Family Care must be split into two cases.

### 5.1 Current Regenerated Artifact

Current regenerated dry-run result:

- V3: `ENVIRONMENT_ERROR`
- Shadow: `ENVIRONMENT_ERROR`
- reason: `Failed to reach device inventory`

This confirms the Phase 4B short-circuit behavior is working correctly.
This row is useful for verifying `environment_error=true` handling, but it is
not useful for evaluating normal Family Care shadow quality.

### 5.2 Normal Family Care Baseline

The Phase 3 evidence-corrected Family Care baseline remains:

- denominator `25`
- matched `23`
- missing `2`
- coverage `92.0%`
- residual required misses: `EventsButton`, `LocationButton`

That baseline supports the intended Balanced interpretation:

- Family Care should remain `REVIEW`
- the known residual risk should stay explicit
- Family Care should not be reclassified to `FAIL`

Conclusion:

- Family Care does not currently block shadow verdict logic by itself.
- The real comparison limitation is artifact availability, not policy intent.

## 6. Balanced Policy Assessment

### 6.1 What Looks Good

- Device plugins behave exactly as intended.
  - Motion, Smoke, and Door Lock all stay `PASS`.
  - No unnecessary downgrade to `REVIEW`.
- `ENVIRONMENT_ERROR` short-circuit works correctly.
  - Current Family Care regenerated artifact proves this.
- Family Care known-risk preservation is at least partially visible.
  - `EventsButton` and `LocationButton` are still emitted on the env-error row.

### 6.2 What Looks Too Strict

- Energy is substantially stricter than the Phase 4A design target.
  - Design expectation: `PASS`
  - Current implementation on existing artifact: `FAIL`
- Home Care is not allowed to become a clean shadow `PASS` even with
  `100 / 0 / 0 / 0` required metrics because `ready_empty_denominator`
  overrides the balanced threshold interpretation.
- Air Care also remains trapped in a readiness-driven `REVIEW`.

### 6.3 Known-Risk Preservation Gap

- Energy and Air Care do not currently preserve provisional-risk context in
  `known_risk_labels`.
- That means the output is stricter in verdict terms while weaker in advisory
  explanation than the design intended.

Overall assessment:

- Balanced is not too loose.
- In the current emitted comparison outputs, it is effectively too strict for
  Energy and too readiness-gated for Home Care and Air Care.

## 7. Phase 4D Readiness

Current judgment: `NEEDS_POLICY_TUNING`

Reasoning:

- The core shadow framework is usable.
- Device plugins validate the basic PASS path.
- `ENVIRONMENT_ERROR` behavior is correct.
- Family Care normal evidence still supports a meaningful `REVIEW` watchlist.
- However, current generated outputs do not line up with the Phase 4A design
  expectation for Home Care, Energy, and Air Care.

This is not primarily a runner problem:

- no new runner-side failure pattern is needed to explain the comparison result
- the main mismatch is between intended balanced interpretation and currently
  emitted shadow inputs / readiness gating

This is also not primarily an artifact-volume problem:

- more artifacts may help, especially for Family Care normal reruns
- but the strongest discrepancy already appears in Energy with a concrete report

## 8. Recommendation

Proceed to Phase 4D only after reconciling shadow-policy behavior with the
comparison findings.

Recommended priority:

1. Treat Home Care and Air Care `coverage_not_ready:ready_empty_denominator`
   outcomes as a shadow-policy quality issue to be reviewed before rollout.
2. Reconcile why Energy is currently emitted as `47.8%` required coverage when
   the Phase 4A design treated its stable required layer as shadow-passable.
3. Keep Family Care split into:
   - normal evidence-corrected `REVIEW`
   - contaminated regenerated `ENVIRONMENT_ERROR`
4. Preserve known-risk explanation better for provisional-heavy Life plugins so
   a future shadow comparison can distinguish strict failure from advisory risk.

Until those are resolved, Phase 4D should be treated as a policy-tuning step,
not as a pure rollout step.
