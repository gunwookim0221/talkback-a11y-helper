# Audit V4 Shadow Policy Tuning Analysis

## 1. Background

Phase 4B implemented `balanced_v1` shadow verdict reporting. Phase 4C then
compared V3 and V4 shadow outputs and found that Device behavior matched design
expectations, while three Life plugins did not:

- `life_home_care_plugin`
- `life_energy_plugin`
- `life_air_care_plugin`

This phase does not change code or policy. It isolates whether the mismatch
comes from:

- the Balanced thresholds themselves
- shadow eligibility aggregation
- readiness gating
- artifact quality
- known-risk explanation gaps

Primary policy references:

- [audit-v4-shadow-verdict-design.md](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v4-shadow-verdict-design.md:145)
- [audit-v4-shadow-verdict-comparison.md](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v4-shadow-verdict-comparison.md:35)
- [audit-v4-unified-taxonomy-policy.md](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v4-unified-taxonomy-policy.md:171)
- [audit-v4-coverage-simulation.md](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v4-coverage-simulation.md:151)

Relevant implementation points:

- [audit_shadow_verdict.py](/d:/Python%20test/talkback-a11y-helper/tools/audit_shadow_verdict.py:67)
- [audit_shadow_verdict.py](/d:/Python%20test/talkback-a11y-helper/tools/audit_shadow_verdict.py:246)
- [audit_device_plugins.py](/d:/Python%20test/talkback-a11y-helper/tools/audit_device_plugins.py:369)

## 2. Energy Input Analysis

### 2.1 Emitted Shadow Input

Current regenerated `life_energy_plugin` shadow input:

- `required_denominator_count = 23`
- `required_matched_count = 11`
- `required_missing_count = 12`
- `required_coverage = 47.8`
- `optional_denominator_count = 9`
- `optional_matched_count = 7`
- `optional_coverage = 77.8`
- `provisional_candidate_count = 0`
- `matching_gap_count = 0`
- `traversal_gap_count = 12`
- `taxonomy_gap_count = 0`
- `known_risk_labels = []`
- `coverage_diagnostic_status = ready`
- `shadow verdict = FAIL`
- `shadow reason = required_coverage<50`

Artifact quality itself is not the main problem:

- `xml_diagnostic_status = xml_present_parsed`
- there is no readiness gate here
- the failure is driven directly by the emitted required denominator

### 2.2 Required Candidate Inventory

Current implementation treats the following 23 labels as `REQUIRED`:

- `10th monitoring`
- `5th monitoring`
- `Activity badges,`
- `Activity New notification`
- `AI Energy Mode Save energy in your home with AI Energy Mode.`
- `Carbon emissions aware Information`
- `Carbon emissions aware, Current carbon intensity 445 grams per kilowatt-hours Carbon emissions are relatively low during this time of day.`
- `Demand Response (D R), Join the SmartThings Energy Demand Response (DR) program.`
- `Device energy usage, Loading… Loading… Usage No data Savings 0 watt-hours`
- `Dismiss`
- `Energy level Information`
- `First steps to monitoring`
- `Monitor`
- `More`
- `More saving activities, Heading`
- `Page 1 of 5`
- `Page 2 of 5`
- `Page 3 of 5`
- `Page 4 of 5`
- `Page 5 of 5`
- `Save`
- `Savings ranking, No energy saving devices`
- `Total energy usage, 0 kilowatt-hours No energy used this month.`

Required misses are 12:

- `10th monitoring`
- `5th monitoring`
- `Activity badges,`
- `Carbon emissions aware, Current carbon intensity 445 grams per kilowatt-hours Carbon emissions are relatively low during this time of day.`
- `Demand Response (D R), Join the SmartThings Energy Demand Response (DR) program.`
- `First steps to monitoring`
- `More saving activities, Heading`
- `Page 3 of 5`
- `Page 4 of 5`
- `Page 5 of 5`
- `Savings ranking, No energy saving devices`
- `Total energy usage, 0 kilowatt-hours No energy used this month.`

Optional labels are only 9:

- `AI Energy Mode activities, Heading`
- `Energy`
- `Energy level, Brown, Energy monitoring, 28, 84 Points, Savings, 0 watt-hours, 0 Points, Score, , 84 Points,`
- `Energy saving tips`
- `Find out more savers`
- `Remove larger pieces of dirt before washing to use less energy by making spinning and draining more efficient.`
- `Smart Energy`
- `Update June 12 12:19 AM`
- `You haven't added any supported devices yet. Check today's carbon intensity to find out the best time to use energy and reduce emissions.`

Current emitted provisional set is empty:

- `provisional_candidate_count = 0`
- `provisional_labels = []`

### 2.3 Why Those Labels Became Required

This is the key mismatch.

All 23 current required Energy labels became required through the same fallback:

- subtype: `UNKNOWN`
- candidate type: `ACTIONABLE`
- policy recommendation: `KEEP`
- implementation path: `policy == "KEEP" and candidate_type in {"ACTIONABLE", "STATUS"} -> REQUIRED`

This behavior comes from [audit_shadow_verdict.py](/d:/Python%20test/talkback-a11y-helper/tools/audit_shadow_verdict.py:84).

That means Energy did not fail because Balanced is harsh. It failed because
unknown provisional-heavy dashboard surfaces were upgraded into required
coverage.

### 2.4 Policy Comparison

Design expectation from Phase 4A:

- stable required layer should be small and local-tab-centered
- provisional dashboard card surfaces should remain advisory
- Energy should be shadow-passable under Balanced

Current implementation input:

- `UNKNOWN` actionables become `REQUIRED`
- `UNKNOWN` does not survive into `PROVISIONAL` in this case
- `provisional_candidate_count` becomes `0`

Conclusion for Energy:

- primary issue: `Eligibility aggregation / implementation interpretation`
- not primary issue: `Balanced threshold`
- not primary issue: `artifact quality`

## 3. Home Care Input Analysis

### 3.1 Emitted Shadow Input

Current regenerated `life_home_care_plugin` shadow input:

- `required_denominator_count = 2`
- `required_matched_count = 2`
- `required_missing_count = 0`
- `required_coverage = 100.0`
- `optional_denominator_count = 7`
- `optional_matched_count = 7`
- `optional_coverage = 100.0`
- `provisional_candidate_count = 0`
- `matching_gap_count = 0`
- `traversal_gap_count = 0`
- `taxonomy_gap_count = 0`
- `coverage_diagnostic_status = ready_empty_denominator`
- `xml_diagnostic_status = xml_present_parsed`
- `shadow verdict = REVIEW`
- `shadow reason = coverage_not_ready:ready_empty_denominator`

Required labels are exactly the expected two:

- `Connect home appliances`
- `Device care`

This matches the design expectation for Home Care's stable required layer.

### 3.2 Why It Still Became REVIEW

The decision path is explicit:

- `evaluate_scenario()` sets `coverage_diagnostic_status = "ready_empty_denominator"`
  when the legacy XML coverage denominator is zero
- `calculate_balanced_shadow_verdict()` converts any `coverage_status != "ready"`
  into `REVIEW` before evaluating the Balanced pass thresholds

Relevant code:

- [audit_device_plugins.py](/d:/Python%20test/talkback-a11y-helper/tools/audit_device_plugins.py:369)
- [audit_shadow_verdict.py](/d:/Python%20test/talkback-a11y-helper/tools/audit_shadow_verdict.py:246)

This is a readiness-gate issue, not a threshold issue:

- required coverage is already fully calculable
- shadow-specific required denominator is nonzero
- shadow-specific required metrics are perfect
- but a legacy KEEP-only coverage status still blocks `PASS`

### 3.3 Policy Comparison

Design expectation from Phase 4A:

- Home Care should be `PASS`
- clean required surface should be sufficient

Current implementation input:

- the shadow verdict depends on `coverage_diagnostic_status`
- `coverage_diagnostic_status` comes from the legacy `calculate_xml_coverage()`
  denominator, not from shadow-required eligibility

Conclusion for Home Care:

- primary issue: `Readiness gate interpretation`
- not primary issue: `Eligibility mapping`
- not primary issue: `Balanced threshold`
- not primary issue: `artifact quality`

## 4. Air Care Input Analysis

### 4.1 Emitted Shadow Input

Current regenerated `life_air_care_plugin` shadow input:

- `required_denominator_count = 6`
- `required_matched_count = 5`
- `required_missing_count = 1`
- `required_coverage = 83.3`
- `optional_denominator_count = 6`
- `optional_matched_count = 4`
- `optional_coverage = 66.7`
- `provisional_candidate_count = 0`
- `matching_gap_count = 0`
- `traversal_gap_count = 1`
- `taxonomy_gap_count = 0`
- `known_risk_labels = []`
- `coverage_diagnostic_status = ready_empty_denominator`
- `xml_diagnostic_status = xml_present_parsed`
- `shadow verdict = REVIEW`
- `shadow reason = coverage_not_ready:ready_empty_denominator`

### 4.2 Required Candidate Inventory

Current implementation treats these 6 labels as `REQUIRED`:

- `Dismiss`
- `Find out more about air control`
- `Information`
- `Is your family sensitive to air quality?, You can monitor the air quality in each room and keep it clean.`
- `Set geolocation`
- `Set the perfect temperature and humidity, You can automatically manage the thermal comfort that people feel in each room.`

Only one required miss remains:

- `Dismiss`

Optional labels are:

- `Air Care`
- `Outdoor air quality (fine dust)`
- `PM 10, Outdoor No data`
- `PM 2.5, Outdoor No data`
- `Set geolocation to monitor outdoor air quality`
- `smartthings-air-plugin`

Again, provisional is empty:

- `provisional_candidate_count = 0`

### 4.3 Why It Looks Different From Design

Phase 4A and Phase 3 simulation expected something closer to:

- `Set geolocation` as the core required item
- Air Care metric-card and advice-heavy surfaces to remain optional or
  provisional

Current implementation instead upgrades all six actionable unknowns to
`REQUIRED` via the same fallback rule seen in Energy.

So Air Care has two separate issues:

- `83.3%` arises from eligibility escalation
- final `REVIEW` reason is still dominated by `ready_empty_denominator`

Conclusion for Air Care:

- primary issues: `Eligibility aggregation` and `Readiness gate interpretation`
- secondary issue: `Known-risk reporting gap`
- not primary issue: `Balanced threshold`

## 5. Policy vs Implementation Gap

### 5.1 Expected Policy

Documented policy shape:

- `CTA`, `NAV_TILE`, `SERVICE_TILE`, `LIFE_TAB` -> `REQUIRED`
- `CONTENT_CARD`, `SCREEN_TITLE`, `ONBOARDING`,
  `PROMOTION_OR_SERVICE_CARD`, `STATUS_METRIC`, `STATUS_LABEL`,
  `INSTRUCTIONAL_STATUS`, `INFO_BUTTON`, `TIP_CARD`,
  `EMPTY_OR_NO_DATA_STATUS` -> `OPTIONAL`
- `LOW_VALUE_LABEL`, `CHROME` -> `EXCLUDED`
- `METRIC_CARD`, `PROGRAM_CARD`, `UNKNOWN` -> `PROVISIONAL`

### 5.2 Current Implementation Behavior

Observed implementation differences:

1. `UNKNOWN` is not stably preserved as `PROVISIONAL`.

   In practice, Life candidates hit one of these earlier branches first:

   - `policy == REVIEW` -> `OPTIONAL`
   - `policy == KEEP` and `candidate_type in ACTIONABLE/STATUS` -> `REQUIRED`

   Result:

   - Energy `UNKNOWN` dashboard candidates become `REQUIRED`
   - Air Care `UNKNOWN` actionable candidates become `REQUIRED`
   - `provisional_candidate_count` collapses to `0`

2. `coverage_diagnostic_status` is inherited from legacy coverage, not from
   shadow-required eligibility.

   Result:

   - Home Care cleanly computes `2 / 2 = 100%` but still becomes `REVIEW`
   - Air Care computes a nonzero required denominator but still becomes `REVIEW`

3. `known_risk_labels` is too narrow for provisional-heavy Life plugins.

   Current special labels are only:

   - `EventsButton`
   - `LocationButton`

   Result:

   - Energy and Air Care do not preserve provisional uncertainty in a readable
     risk field

### 5.3 Bottom-Line Gap Classification

| Plugin | Main gap | Secondary gap |
| --- | --- | --- |
| Home Care | readiness gate | none |
| Energy | eligibility aggregation | known-risk reporting |
| Air Care | eligibility aggregation + readiness gate | known-risk reporting |

Balanced threshold mismatch is not the main problem in any of the three cases.

## 6. Recommended Fixes

This section is still analysis only. No changes are proposed for this phase.

### 6.1 Fix Direction Selection

`A. Balanced threshold change needed`

- Not recommended as the first fix.
- The threshold behaves sensibly once the intended required denominator is used.

`B. Eligibility mapping implementation fix needed`

- Yes.
- Highest priority for Energy.
- Also relevant for Air Care.

`C. Readiness gate fix needed`

- Yes.
- Highest priority for Home Care.
- Also relevant for Air Care.

`D. Artifact re-collection needed`

- Limited need only.
- Not required to explain Home Care, Energy, or Air Care current mismatch.
- Still useful later for a normal Family Care comparison artifact.

`E. Known risk label reporting improvement needed`

- Yes.
- Needed so provisional-heavy dashboards do not look like unexplained hard
  failures.

### 6.2 Recommended Order

1. `B. Eligibility mapping implementation fix`
2. `C. Readiness gate interpretation fix`
3. `E. Known risk reporting improvement`
4. `D. Family Care normal artifact refresh if needed`
5. `A. Threshold tuning only if mismatch remains after input alignment`

## 7. Phase 4D Readiness

Current judgment: `NEEDS_POLICY_TUNING_IMPLEMENTATION`

Reasoning:

- Device shadow behavior is already aligned.
- Family Care comparison still needs artifact separation, but that is not the
  main blocker for the current policy mismatch.
- Home Care proves that shadow-required metrics can already be clean while the
  readiness gate still prevents `PASS`.
- Energy proves that unknown provisional-heavy dashboard candidates are
  currently being interpreted as required.
- Air Care shows both problems at once.

Therefore:

- this is not mainly a design-revision problem
- this is not mainly a missing-artifact problem
- this is mainly an implementation-interpretation gap between the documented
  policy and the emitted shadow inputs

Phase 4D should not proceed as a pure rollout step until that gap is resolved.
