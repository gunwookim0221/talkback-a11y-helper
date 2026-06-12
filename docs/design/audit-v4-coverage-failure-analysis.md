# Audit V4 Coverage Failure Analysis

## 1. Background

This note decomposes Audit V4 coverage failures into root-cause categories.
It is analysis-only.

It does not change:

- Coverage engine behavior
- Coverage denominator selection
- KEEP / REVIEW / EXCLUDE classification
- Matching implementation
- Verdict integration
- V3 verdict behavior
- Traversal or TalkBack collection
- Taxonomy implementation

The purpose of this phase is to explain why coverage is low before deciding
whether subtype expansion, matching review, or runner work should come next.

## 2. Input Evidence

Primary design inputs:

- `docs/design/audit-v4-xml-coverage-design.md`
- `docs/design/audit-v4-life-taxonomy-discovery.md`
- `docs/design/audit-v4-coverage-eligibility-review.md`
- `docs/design/audit-v4-unified-taxonomy-policy.md`
- `docs/design/audit-v4-coverage-simulation.md`

Primary runtime evidence:

- `output/audit_v4_phase3_8_evidence/audit_report.json`
- `output/audit_v4_phase3_12_food_energy/audit_report.json`
- `output/audit_v4_phase3_12_life_optional/audit_report.json`
- XML dumps under each plugin output directory used by `tools.audit_xml_candidates.extract_xml_candidates`

Analysis assumptions:

- Traversal matching assumption remains `normalized_exact`
- Missing inventory uses the Phase 3.14 simulation tiers: `Required`, `Optional`, `Provisional`
- Distribution numbers below are computed from coverage-relevant inventory only
  (`Required + Optional + Provisional`)
- Excluded chrome labels observed outside that inventory are noted separately and
  not used as denominator-facing blockers

## 3. Failure Inventory

### 3.1 Inventory Summary

| Plugin | Required Missing | Optional Missing | Provisional Missing | Notes |
| --- | ---: | ---: | ---: | --- |
| `device_motion_sensor_plugin` | 1 | 3 | 0 | device required miss is status-label matching |
| `device_smoke_sensor_plugin` | 2 | 2 | 0 | one local-tab miss, one status-label miss |
| `device_door_lock_plugin` | 2 | 3 | 0 | one local-tab miss, one embedded state-value miss |
| `life_family_care_plugin` | 6 | 21 | 0 | raw miss volume is mostly static dashboard text |
| `life_home_care_plugin` | 0 | 1 | 0 | only screen-title miss remains |
| `life_energy_plugin` | 0 | 4 | 12 | miss volume is concentrated in provisional dashboard cards |
| `life_air_care_plugin` | 0 | 1 | 2 | no required miss |

Coverage-relevant inventory total: `60` missing labels.

Observed excluded-only misses outside that inventory:

- `life_family_care_plugin`: `More options`
- `life_air_care_plugin`: `More options`

### 3.2 Plugin Inventories

`device_motion_sensor_plugin`

- Required Missing: `Motion detected`
- Optional Missing: `Add routine`, `Motion detection notifications, Example: every day, 6:00 PM - 10:00 PM`, `No history`
- Provisional Missing: none

`device_smoke_sensor_plugin`

- Required Missing: `Clear`, `Controls`
- Optional Missing: `Add routine`, `No history`
- Provisional Missing: none

`device_door_lock_plugin`

- Required Missing: `Controls`, `Locked`
- Optional Missing: `Add routine`, `No history`, `switch`
- Provisional Missing: none

`life_family_care_plugin`

- Required Missing: `ActivityButton`, `Add family member`, `EventsButton`, `LocationButton`, `Mobile usageButton`, `View profile`
- Optional Missing: `0`, `1`, `10`, `13`, `35`, `6000`, `Active now`, `Add home information`, `AM`, `Avg (week)`, `Device usage`, `Events`, `h`, `It's time to go to bed so you can feel well rested tomorrow.`, `Location`, `m`, `Me`, `Mobile usage`, `PM`, `Today`, `Weather information, Icon. Add home information`
- Provisional Missing: none

`life_home_care_plugin`

- Required Missing: none
- Optional Missing: `Home Care`
- Provisional Missing: none

`life_energy_plugin`

- Required Missing: none
- Optional Missing: `Find out more savers`, `First steps to monitoring`, `Savings ranking, No energy saving devices`, `Total energy usage, 0 kilowatt-hours No energy used this month.`
- Provisional Missing: `10th monitoring`, `5th monitoring`, `Activity badges,`, `AI Energy Mode activities, Heading`, `Carbon emissions aware, Current carbon intensity 445 grams per kilowatt-hours Carbon emissions are relatively low during this time of day.`, `Demand Response (D R), Join the SmartThings Energy Demand Response (DR) program.`, `Energy level Information`, `Energy level, Brown, Energy monitoring, 28, 84 Points, Savings, 0 watt-hours, 0 Points, Score, , 84 Points,`, `More saving activities, Heading`, `Page 3 of 5`, `Page 4 of 5`, `Page 5 of 5`

`life_air_care_plugin`

- Required Missing: none
- Optional Missing: `Set geolocation to monitor outdoor air quality`
- Provisional Missing: `Dismiss`, `smartthings-air-plugin`

## 4. Root Cause Categories

The following categories were applied to each missing label.

| Category | Meaning |
| --- | --- |
| `MATCHING_GAP` | XML candidate and traversal evidence are semantically the same, but exact label shape differs. |
| `TAXONOMY_GAP` | Missing item fits a new Life structure that is not yet stable enough in the current taxonomy model. |
| `TRAVERSAL_GAP` | No equivalent traversal hit was observed even though the surface appears reachable and should be visited. |
| `OPTIONAL_CONTENT` | Secondary, dismissible, onboarding, pagination, or other non-core content. |
| `STATIC_TEXT` | Titles, dashboard labels, fragmented metrics, or advisory text that inflate raw miss count without indicating core traversal loss. |
| `EMPTY_STATE` | `No history`, `No data`, `No devices`, or similar absence states. |
| `CHROME` | Toolbar, shell, or plugin-identity labels that are not plugin-content coverage targets. |
| `UNKNOWN` | Evidence is insufficient to assign a stronger category. |

## 5. Device Analysis

### 5.1 Root-Cause Summary

| Plugin | Missing | Matching | Traversal | Optional | Static | Empty |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `device_motion_sensor_plugin` | 4 | 1 | 0 | 1 | 1 | 1 |
| `device_smoke_sensor_plugin` | 4 | 1 | 1 | 1 | 0 | 1 |
| `device_door_lock_plugin` | 5 | 2 | 1 | 1 | 0 | 1 |

Device total: `13` misses

- `MATCHING_GAP`: 4
- `TRAVERSAL_GAP`: 2
- `OPTIONAL_CONTENT`: 3
- `STATIC_TEXT`: 1
- `EMPTY_STATE`: 3

### 5.2 Findings

- Device required misses are concentrated in exact-label undercount and local-tab under-read, not taxonomy.
- Required-miss breakdown is `7 MATCHING_GAP` vs `4 TRAVERSAL_GAP` across all device and Family required misses combined.
- Representative examples:
  `Motion detected` was present only inside compound traversal labels.
  `Clear` was embedded in `Smoke detector History Clear`.
  `Locked` and `switch` were embedded in `Lock state Locked switch`.
  `Controls` was visible in XML but never surfaced as a traversal hit in Smoke and Door Lock.

Device conclusion:

- Main device blocker is `MATCHING_GAP`, with smaller but real `TRAVERSAL_GAP`.
- Device evidence does not justify subtype expansion.

## 6. Life Analysis

### 6.1 Root-Cause Summary

| Plugin | Missing | Matching | Taxonomy | Traversal | Optional | Static | Empty | Chrome |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `life_family_care_plugin` | 27 | 4 | 0 | 2 | 2 | 19 | 0 | 0 |
| `life_home_care_plugin` | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| `life_energy_plugin` | 16 | 0 | 11 | 0 | 3 | 0 | 2 | 0 |
| `life_air_care_plugin` | 3 | 0 | 0 | 0 | 2 | 0 | 0 | 1 |

Life total: `47` misses

- `STATIC_TEXT`: 20
- `TAXONOMY_GAP`: 11
- `OPTIONAL_CONTENT`: 7
- `MATCHING_GAP`: 4
- `TRAVERSAL_GAP`: 2
- `EMPTY_STATE`: 2
- `CHROME`: 1

### 6.2 Family Care

- Family Care raw miss count is high, but the largest share is not required navigation loss.
- `19 / 27` misses are `STATIC_TEXT`: fragmented metrics, units, advisory text, and dashboard labels.
- Required misses split into:
  `MATCHING_GAP`: `ActivityButton`, `EventsButton`, `LocationButton`, `Mobile usageButton`
  `TRAVERSAL_GAP`: `Add family member`, `View profile`

Interpretation:

- Family Care looks worse in raw count than in core-surface risk.
- The most important Family miss pattern is label-shape mismatch on `NAV_TILE`-like candidates.

### 6.3 Home Care

- Home Care has one remaining miss: `Home Care`
- Root cause is `STATIC_TEXT`

Interpretation:

- Home Care is not a blocker.

### 6.4 Energy

- Energy miss volume is dominated by `TAXONOMY_GAP`: `11 / 16`
- Misses cluster around provisional dashboard structures:
  metric-card-like composites, program cards, activity cards, ranking cards, and carousel surfaces
- `EMPTY_STATE` still exists but is smaller:
  `Savings ranking, No energy saving devices`
  `Total energy usage, 0 kilowatt-hours No energy used this month.`

Interpretation:

- Energy is the strongest signal that provisional Life dashboard structures are still under-modeled for analysis.
- This is a taxonomy-validation problem, not a runner reachability problem.

### 6.5 Air Care

- Air Care has no required miss
- Remaining misses are low-risk:
  `OPTIONAL_CONTENT`: `Set geolocation to monitor outdoor air quality`, `Dismiss`
  `CHROME`: `smartthings-air-plugin`

Interpretation:

- Air Care does not currently justify urgent traversal or matching work.

## 7. Failure Distribution

Distribution across `60` coverage-relevant missing labels:

| Category | Count | Share |
| --- | ---: | ---: |
| `STATIC_TEXT` | 21 | 35.0% |
| `TAXONOMY_GAP` | 11 | 18.3% |
| `OPTIONAL_CONTENT` | 10 | 16.7% |
| `MATCHING_GAP` | 8 | 13.3% |
| `EMPTY_STATE` | 5 | 8.3% |
| `TRAVERSAL_GAP` | 4 | 6.7% |
| `CHROME` | 1 | 1.7% |
| `UNKNOWN` | 0 | 0.0% |

Required-only distribution across `11` required misses:

- `MATCHING_GAP`: 7
- `TRAVERSAL_GAP`: 4
- `TAXONOMY_GAP`: 0

Interpretation:

- Raw miss volume is led by `STATIC_TEXT`, not by core traversal failure.
- Required misses are led by `MATCHING_GAP`, not by taxonomy.
- Taxonomy pressure is concentrated in Energy provisional content, not in already-established required surfaces.

## 8. Phase 4 Blockers

Result: `D. Composite problem`

Why it is not `A` only:

- `TAXONOMY_GAP` is large in Energy, but required misses are not taxonomy-driven.

Why it is not `B` only:

- `MATCHING_GAP` dominates required misses, but Family raw count is inflated by static optional text and Energy still has a large provisional taxonomy bucket.

Why it is not `C` only:

- `TRAVERSAL_GAP` exists, but it is smaller than matching and taxonomy issues.

Priority order of blockers:

1. Required-surface false undercount from `MATCHING_GAP`
2. Energy provisional dashboard inventory driven by `TAXONOMY_GAP`
3. Smaller but real `TRAVERSAL_GAP` on local tabs and primary CTAs

## 9. Recommended Next Step

Recommended next step: `Phase 3.16 Matching Gap Analysis`

Reasoning:

- Every required miss is already explainable as either `MATCHING_GAP` or `TRAVERSAL_GAP`
- Required misses skew toward matching: `7 / 11`
- Device and Family are closer to Phase 4 relevance than Energy provisional cards
- If matching remains unresolved, any future shadow verdict will undercount already-modeled required content even before subtype expansion is considered

Recommended follow-up order:

1. `Phase 3.16 Matching Gap Analysis`
2. `Phase 3.16 Taxonomy Gap Validation`
3. `Phase 3.16 Traversal Gap Investigation`
4. `Phase 4 Shadow Verdict`

Working recommendation:

- Do not expand subtype implementation yet
- First verify whether exact-match undercount on required surfaces can be quantified and bounded
- Then validate which Energy provisional structures truly deserve stable subtype promotion
