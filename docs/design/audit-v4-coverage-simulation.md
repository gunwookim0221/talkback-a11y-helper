# Audit V4 Coverage Policy Simulation

## 1. Inputs

This document simulates a future coverage policy using the current taxonomy and
eligibility proposal. It is simulation-only.

It does not change:

- coverage engine behavior
- denominator selection
- KEEP / REVIEW / EXCLUDE classification
- matching policy
- coverage calculation
- verdict integration
- V3 verdict logic
- traversal or TalkBack collection

Input policy documents:

- `docs/design/audit-v4-xml-coverage-design.md`
- `docs/design/audit-v4-life-taxonomy-discovery.md`
- `docs/design/audit-v4-coverage-eligibility-review.md`
- `docs/design/audit-v4-unified-taxonomy-policy.md`

Input evidence artifacts:

- `output/audit_v4_phase3_8_evidence/device_motion_sensor_plugin`
- `output/audit_v4_phase3_8_evidence/device_smoke_sensor_plugin`
- `output/audit_v4_phase3_8_evidence/device_door_lock_plugin`
- `output/audit_v4_phase3_8_evidence/life_family_care_plugin`
- `output/audit_v4_phase3_8_evidence/life_home_care_plugin`
- `output/audit_v4_phase3_12_food_energy/life_energy_plugin`
- `output/audit_v4_phase3_12_life_optional/life_air_care_plugin`

Food is referenced only as a cautionary note. It is not used as a primary basis
for this simulation.

## 2. Simulation Method

### 2.1 Matching Assumption

The simulation keeps the current runtime matching assumption:

- normalized exact label matching only

That means the simulation intentionally does not grant credit for:

- containment
- alias mapping
- token overlap
- button/title suffix normalization such as `ActivityButton` -> `Activity`

### 2.2 Eligibility Mapping

The following mapping is applied as a paper simulation only.

`REQUIRED`

- `CTA`
- `NAV_TILE`
- `SERVICE_TILE`
- `LIFE_TAB`

`OPTIONAL`

- `CONTENT_CARD`
- `SCREEN_TITLE`
- `ONBOARDING`
- `PROMOTION_OR_SERVICE_CARD`
- `STATUS_METRIC`
- `STATUS_LABEL`
- `INSTRUCTIONAL_STATUS`
- `INFO_BUTTON`
- `TIP_CARD`
- `EMPTY_OR_NO_DATA_STATUS`

`EXCLUDED`

- `LOW_VALUE_LABEL`
- `CHROME`

`PROVISIONAL`

- `METRIC_CARD`
- `PROGRAM_CARD`
- `UNKNOWN`

### 2.3 Device Mapping

Device plugins do not yet have the richer Life subtypes, so the simulation uses
the Phase 3.11 device grouping:

- `REQUIRED`: local tabs and primary device state labels
- `OPTIONAL`: empty states, secondary actions, plugin titles, instructional
  content
- `EXCLUDED`: shell chrome and non-plugin labels

## 3. Device Simulation

| Scenario | Merged | Required | Optional | Excluded | Required matched | Optional matched | Required coverage | Optional coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `device_motion_sensor_plugin` | 13 | 6 | 4 | 3 | 5 | 1 | 83.3% | 25.0% |
| `device_smoke_sensor_plugin` | 13 | 6 | 4 | 3 | 4 | 2 | 66.7% | 50.0% |
| `device_door_lock_plugin` | 13 | 5 | 5 | 3 | 3 | 2 | 60.0% | 40.0% |

### Motion Sensor

- Required candidates: `100%`, `Controls`, `History`, `Motion detected`,
  `Motion sensor`, `Routines`
- Required matched under exact matching: all except `Motion detected`
- Optional misses are mostly expected and not runner-critical:
  `Add routine`, `No history`, routine example text

Interpretation:

- Device policy is plausible
- Current gap is concentrated in one meaningful required status label

### Smoke Sensor

- Required candidates: `Carbon monoxide detector`, `Clear`, `Controls`,
  `History`, `Routines`, `Smoke detector`
- Exact matching misses `Clear` and `Controls`
- Optional matches come mostly from plugin title and empty-state text

Interpretation:

- Required coverage is still workable
- Combined traversal labels such as `Smoke detector History Clear` reduce exact
  match efficiency

### Door Lock

- Required candidates: `Controls`, `History`, `Lock state`, `Locked`,
  `Routines`
- Exact matching misses `Controls` and `Locked`
- Optional matches come mostly from title and routines empty-state text

Interpretation:

- Policy still looks usable
- Exact matching undercounts state values embedded in compound traversal labels

## 4. Life Simulation

### Summary Table

| Scenario | Merged | Required | Optional | Provisional | Excluded | Required matched | Optional matched | Required coverage | Optional coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `life_family_care_plugin` | 40 | 7 | 31 | 0 | 2 | 1 | 8 | 14.3% | 25.8% |
| `life_home_care_plugin` | 10 | 2 | 7 | 0 | 1 | 2 | 6 | 100.0% | 85.7% |
| `life_energy_plugin` | 34 | 3 | 10 | 19 | 2 | 3 | 8 | 100.0% | 80.0% |
| `life_air_care_plugin` | 14 | 1 | 6 | 5 | 2 | 1 | 5 | 100.0% | 83.3% |

### Family Care

Required:

- `CTA`: `Add family member`, `View information`, `View profile`
- `NAV_TILE`: `ActivityButton`, `EventsButton`, `LocationButton`,
  `Mobile usageButton`

Observed exact matches:

- `View information` only

Main reason:

- Traversal visible labels often surface simplified labels such as `Activity`
  while XML candidate labels use subtype-specific forms such as
  `ActivityButton`

Interpretation:

- This is not a denominator-size problem
- It is mainly a label-shape problem under exact matching

### Home Care

Required:

- `CTA`: `Connect home appliances`
- `SERVICE_TILE`: `Device care`

Observed exact matches:

- both required labels are present in traversal evidence

Optional:

- `CONTENT_CARD`
- `SCREEN_TITLE`
- `ONBOARDING`
- `PROMOTION_OR_SERVICE_CARD`
- one `STATUS_LABEL`

Interpretation:

- Home Care is the cleanest Life case
- The policy looks operationally realistic here

### Energy

This simulation is best-effort because the new provisional subtypes are not yet
tagged in runtime diagnostics.

Required:

- `LIFE_TAB`: `Monitor`, `Save`, `Activity New notification`

Optional:

- `INFO_BUTTON`: `Information`, `How to use`, `Carbon emissions aware Information`
- `TIP_CARD`: `Energy saving tips`, `Find out more savers`, `First steps to monitoring`
- `EMPTY_OR_NO_DATA_STATUS`: no-device and no-data messaging
- `SCREEN_TITLE` / `STATUS_LABEL`: `Energy`, `Smart Energy`

Provisional:

- `METRIC_CARD`: energy usage, carbon intensity, energy level composite cards
- `PROGRAM_CARD`: `AI Energy Mode...`, `Demand Response...`
- remaining `UNKNOWN` actionables such as monitoring cards and badge cards

Interpretation:

- Required coverage is good because local tabs are clearly reachable
- Optional coverage is also decent
- The largest unresolved share is the provisional metric/program dashboard layer

### Air Care

This simulation is also best-effort because runtime subtype tagging does not yet
cover the provisional Air Care shapes.

Required:

- `CTA`: `Set geolocation`

Optional:

- `INFO_BUTTON`: `Information`
- `TIP_CARD`: `Find out more about air control`
- `CONTENT_CARD`: air-quality advice cards
- `SCREEN_TITLE`: `Air Care`
- `EMPTY_OR_NO_DATA_STATUS`: `PM 10, Outdoor No data`,
  `PM 2.5, Outdoor No data`

Provisional:

- `METRIC_CARD`: `Outdoor air quality (fine dust)`
- remaining unknown candidate shapes such as plugin-local text surfaces

Interpretation:

- Required coverage is fine
- Optional coverage is mostly fine
- Air Care still depends on provisional metric-card interpretation

## 5. Coverage Distribution Analysis

### Subtypes That Pull Coverage Down

`UNKNOWN`

- Biggest unresolved bucket in Device, Energy, and Air Care
- This is the main reason simulation confidence is lower than raw percentages

`NAV_TILE`

- Family Care required coverage collapses because XML uses `ActivityButton`-like
  labels while traversal surfaces simplified labels

`STATUS_METRIC`

- Family Care produces many metric-like labels
- These are better treated as optional than required

`SCREEN_TITLE`

- Usually visible, but duplicative
- It does not materially help bug-finding if moved into required denominator

`METRIC_CARD` and `PROGRAM_CARD`

- These dominate Energy dashboard complexity
- They should stay provisional until subtype tagging becomes stable

### Why Device And Life Behave Differently

Device gaps are mostly:

- missing exact state labels
- combined traversal labels

Life gaps are mostly:

- subtype richness
- exact-match label shape differences
- provisional dashboard-card surfaces

## 6. Policy Findings

### A. Policy Areas That Already Look Realistic

- Device required policy is workable
- Home Care policy is workable
- Energy and Air Care show that `LIFE_TAB`, `INFO_BUTTON`, and `TIP_CARD` are
  useful taxonomy additions

### B. Policy Areas That Need Caution

- Family Care required coverage is too low under exact matching
- The issue is not only taxonomy richness; it is also label-form mismatch
- `STATUS_LABEL` and `SCREEN_TITLE` should remain optional
- `METRIC_CARD` and `PROGRAM_CARD` should remain provisional

### C. Practical Reading Of The Simulation

- If Phase 4 used this policy today, Device would be close
- Life would be split:
  Home Care is close
  Energy and Air Care are structurally promising but still provisional-heavy
  Family Care is not ready under exact matching

## 7. Risks

- Simulation counts for Energy and Air Care are best-effort because provisional
  subtypes are not yet runtime-tagged
- Family Care may look artificially weak until label-shape normalization is
  addressed in a later phase
- Device exact-match undercount remains visible for compound traversal labels
- Food still should not be used as a readiness anchor

## 8. Phase 4 Readiness

Result: `PARTIAL`

Reasoning:

- Device policy is close enough for Phase 4 design discussion
- Home Care is close enough to support the Life side
- Energy and Air Care justify the provisional subtype model, but not final
  denominator policy
- Family Care is the strongest signal that exact matching and required subtype
  selection still need another validation pass before verdict integration

## 9. Recommended Next Step

Phase 3.15 should implement diagnostic-only subtype tagging for:

- `INFO_BUTTON`
- `LIFE_TAB`
- `METRIC_CARD`
- `TIP_CARD`
- `PROGRAM_CARD`
- `EMPTY_OR_NO_DATA_STATUS`

After that, rerun:

- `life_family_care_plugin`
- `life_home_care_plugin`
- `life_energy_plugin`
- `life_air_care_plugin`

Only after those subtype counts stabilize should Phase 4 verdict integration be
considered.
