# Audit V4 Unified Taxonomy Policy Draft

## 1. Background

This note consolidates Audit V4 taxonomy evidence gathered through Phase 3.12.
It is a diagnostic and policy draft only.

It does not change:

- coverage denominator
- KEEP / REVIEW / EXCLUDE classification
- matching policy
- coverage calculation
- verdict integration
- V3 verdict logic
- traversal or TalkBack collection

Primary source documents:

- `docs/design/audit-v4-xml-coverage-design.md`
- `docs/design/audit-v4-life-taxonomy-discovery.md`
- `docs/design/audit-v4-coverage-eligibility-review.md`

Primary evidence artifacts:

- `output/audit_v4_phase3_8_evidence/life_family_care_plugin`
- `output/audit_v4_phase3_8_evidence/life_home_care_plugin`
- `output/audit_v4_phase3_12_food_energy/life_energy_plugin`
- `output/audit_v4_phase3_12_life_optional/life_air_care_plugin`

Food evidence is intentionally treated as secondary in this draft. Food entry and
onboarding handling were stabilized in commit
`fddf96ddd70e0a4ba4cf84b5afe9e1d28737f215`, but Food is not yet a stable basis
for taxonomy finalization.

## 2. Device Taxonomy Summary

Device plugins are already explainable with the current top-level structure:

- `ACTIONABLE`: `Add routine`, local-tab actions, toggle-like controls
- `STATUS`: `Motion detected`, `Locked`, `Clear`, percentage values
- `EMPTY_STATE`: `No history`, `No routines include this device`
- `INSTRUCTIONAL`: routine examples or guidance copy
- `CHROME`: `Navigate up`, `More options`
- `UNKNOWN`: plugin titles or ambiguous compound labels

Representative device evidence from Motion Sensor, Smoke Sensor, and Door Lock
shows that the current top-level buckets are sufficient. The main remaining
device question is not taxonomy shape, but denominator eligibility tiering.

## 3. Life Taxonomy Summary

### 3.1 Top-Level Buckets

Life plugins can continue to use the same top-level buckets as Device:

- `ACTIONABLE`
- `STATUS`
- `EMPTY_STATE`
- `INSTRUCTIONAL`
- `CHROME`
- `UNKNOWN`

This keeps the high-level model unified across Device and Life.

### 3.2 Consolidated Life Subtypes

The following subtype list is the current consolidated Life draft.

| Subtype | Status | Typical meaning | Evidence |
| --- | --- | --- | --- |
| `CTA` | established | primary action entry or call-to-action | Family Care, Home Care |
| `NAV_TILE` | established | navigational tile inside Life dashboard | Family Care |
| `SERVICE_TILE` | established | service dashboard tile | Home Care |
| `CONTENT_CARD` | established | focusable content or article card | Home Care |
| `SCREEN_TITLE` | established | service or screen title | Home Care |
| `ONBOARDING` | established | setup or guide entry point | Family Care, Home Care |
| `PROMOTION_OR_SERVICE_CARD` | established | card that may be service content or promotion | Home Care |
| `STATUS_METRIC` | established | value-like metric candidate | Family Care |
| `STATUS_LABEL` | established | descriptive status or state label | Family Care |
| `INSTRUCTIONAL_STATUS` | established | static advisory or instruction-like status | Family Care |
| `LOW_VALUE_LABEL` | established | punctuation-only or low-value structural label | Home Care |
| `INFO_BUTTON` | provisional | info/help affordance attached to card or metric | Energy, Air Care |
| `LIFE_TAB` | provisional | Life-local tab or strip tab such as `Monitor`, `Save`, `Activity` | Energy |
| `METRIC_CARD` | provisional | dashboard card mixing title, value, state, and summary metric | Energy, Air Care |
| `TIP_CARD` | provisional | advice or recommendation card | Energy, Air Care |
| `PROGRAM_CARD` | provisional | feature/program enrollment card | Energy |
| `EMPTY_OR_NO_DATA_STATUS` | provisional | explicit no-data state embedded in Life content | Energy, Air Care |

### 3.3 Plugin Evidence Summary

`life_family_care_plugin`

- Strong evidence for `CTA`, `NAV_TILE`, `STATUS_METRIC`, `STATUS_LABEL`,
  `ONBOARDING`, `INSTRUCTIONAL_STATUS`
- Example labels: `Add family member`, `ActivityButton`, `LocationButton`,
  `Steps`, `Today`, `Add home information`

`life_home_care_plugin`

- Strong evidence for `SERVICE_TILE`, `CONTENT_CARD`, `SCREEN_TITLE`,
  `PROMOTION_OR_SERVICE_CARD`, `ONBOARDING`, `LOW_VALUE_LABEL`
- Example labels: `Connect home appliances`, `Device care`, `Usage guide`,
  `Samsung Care+`, `SmartThings Home Care`, `,`

`life_energy_plugin`

- Stronger evidence than earlier phases and enough to justify provisional
  subtypes
- Observed local structure: `Monitor`, `Save`, `Activity`
- Observed candidate patterns:
  `Carbon emissions aware Information`,
  `Device energy usage, Loading... Usage No data Savings 0 watt-hours`,
  `AI Energy Mode Save energy in your home with AI Energy Mode.`,
  `Demand Response (D R), Join the SmartThings Energy Demand Response (DR) program.`,
  `Energy saving tips`
- These support provisional `INFO_BUTTON`, `LIFE_TAB`, `METRIC_CARD`,
  `TIP_CARD`, `PROGRAM_CARD`, and `EMPTY_OR_NO_DATA_STATUS`

`life_air_care_plugin`

- Enough evidence for provisional subtype review, but not yet enough for a
  fully stable final policy
- Observed candidate patterns:
  `Information`,
  `Find out more about air control`,
  `Outdoor air quality (fine dust)`,
  `PM 10, Outdoor No data`,
  `PM 2.5, Outdoor No data`,
  `Set geolocation`,
  `Set geolocation to monitor outdoor air quality`
- These support provisional `INFO_BUTTON`, `METRIC_CARD`, `TIP_CARD`, and
  `EMPTY_OR_NO_DATA_STATUS`

## 4. Subtype Definitions

`CTA`

- A primary user action that moves the user into setup, profile, or service use
- Example: `Add family member`

`NAV_TILE`

- A tile-like navigation affordance that changes section or mode within the
  plugin
- Example: `ActivityButton`

`SERVICE_TILE`

- A service dashboard tile representing a product or service surface
- Example: `Device care`

`CONTENT_CARD`

- A card-like focusable content block, usually article, recommendation, or guide
- Example: Home Care article bundle card

`SCREEN_TITLE`

- A title that identifies the current Life surface rather than an action
- Example: `SmartThings Home Care`

`ONBOARDING`

- A setup or guide-related entry that helps establish initial configuration
- Example: `Usage guide`

`PROMOTION_OR_SERVICE_CARD`

- A card that can be either promotional or a meaningful service feature, but is
  not yet cleanly separable
- Example: `Samsung Care+`

`STATUS_METRIC`

- A value-heavy metric candidate, often numeric or unit-shaped
- Example: `6000`, `11:46`

`STATUS_LABEL`

- A descriptive status text that provides meaningful state without being a
  direct action
- Example: `Active now`

`INSTRUCTIONAL_STATUS`

- Instructional text that explains behavior or suggests action but is primarily
  descriptive
- Example: bedtime advisory text in Family Care

`LOW_VALUE_LABEL`

- A structurally present but semantically weak label
- Example: `,`

`INFO_BUTTON` (provisional)

- A small info or help control associated with a larger card or metric
- Example: `Information`

`LIFE_TAB` (provisional)

- A local tab or strip item inside a Life plugin
- Example: `Monitor`, `Save`, `Activity`

`METRIC_CARD` (provisional)

- A focusable card whose main payload is a metric summary rather than a single
  label or simple button
- Example: Energy usage and carbon intensity cards

`TIP_CARD` (provisional)

- A focusable recommendation or advice card
- Example: `Energy saving tips`, `Find out more about air control`

`PROGRAM_CARD` (provisional)

- A feature enrollment or program participation card
- Example: Demand Response card, AI Energy Mode card

`EMPTY_OR_NO_DATA_STATUS` (provisional)

- A no-data or not-yet-configured state rendered as real plugin content
- Example: `PM 10, Outdoor No data`, `Your supported devices` no-data messaging

## 5. Coverage Eligibility Proposal

This is a proposal only. No runtime policy is changed here.

| Subtype | Proposed eligibility | Rationale |
| --- | --- | --- |
| `CTA` | `REQUIRED` | Primary task entry and user-visible actions should be traversed. |
| `NAV_TILE` | `REQUIRED` | Navigation tiles are core plugin content. |
| `SERVICE_TILE` | `REQUIRED` | Service tiles are central Life dashboard elements. |
| `CONTENT_CARD` | `OPTIONAL` | Often important, but card semantics vary between content and recommendation. |
| `SCREEN_TITLE` | `OPTIONAL` | Useful context, but may duplicate screen identity. |
| `ONBOARDING` | `OPTIONAL` | Real content, but conditional and state-dependent. |
| `PROMOTION_OR_SERVICE_CARD` | `OPTIONAL` | Mixed service value and promo semantics. |
| `STATUS_METRIC` | `OPTIONAL` | Can be useful when contextualized, but raw values can over-count. |
| `STATUS_LABEL` | `OPTIONAL` | Often meaningful, but some are duplicative headers or static context. |
| `INSTRUCTIONAL_STATUS` | `OPTIONAL` | Useful evidence but not always a required traversal denominator. |
| `LOW_VALUE_LABEL` | `EXCLUDED` | Low semantic value and strong over-detection risk. |
| `INFO_BUTTON` | `OPTIONAL` | Useful secondary control, but rarely core coverage target. |
| `LIFE_TAB` | `REQUIRED` | If local-tab structure is part of plugin content, it should be reachable. |
| `METRIC_CARD` | `PROVISIONAL` | Likely important, but Energy/Air Care evidence is still narrow. |
| `TIP_CARD` | `OPTIONAL` | Often useful but not always central functionality. |
| `PROGRAM_CARD` | `PROVISIONAL` | Important in Energy, but still plugin-specific and not widely proven. |
| `EMPTY_OR_NO_DATA_STATUS` | `OPTIONAL` | Valuable for diagnostics, but may be too conditional for strict requirement. |
| `CHROME` | `EXCLUDED` | Shell controls remain outside plugin denominator. |
| `UNKNOWN` | `PROVISIONAL` | Must not become denominator without subtype or explicit policy. |

## 6. Device And Life Compatibility

There is no structural conflict between Device and Life taxonomies if the
taxonomy remains two-layered.

Recommended unified shape:

- top-level shared buckets for both domains
- domain-specific subtypes beneath those buckets

That means Device does not need a separate top-level taxonomy. Device-specific
concepts such as local tabs, empty states, and state labels fit naturally into
the same top-level buckets already used by Life.

The main asymmetry is subtype richness:

- Device currently needs fewer subtypes
- Life needs additional service-card and dashboard-card subtypes

This is acceptable. The taxonomy can stay unified at the top level and richer on
the Life side underneath.

## 7. Open Risks

- `STATUS_LABEL` may still mix meaningful plugin status with decorative headers.
- `METRIC_CARD` is evidence-backed but not yet stable across multiple Life
  plugins.
- `PROGRAM_CARD` currently depends mostly on Energy evidence.
- `EMPTY_OR_NO_DATA_STATUS` may need separation between actionable empty states
  and passive no-data text.
- `INFO_BUTTON` may be too small and secondary to count as required coverage.
- Air Care evidence is narrower than Family/Home/Energy and should remain
  provisional where uncertainty exists.
- Food should not be used as a taxonomy anchor until its post-entry surfaces are
  stable enough for clean evidence collection.

## 8. Phase 3.14 Implementation Plan

Recommended next step for Phase 3.14:

1. Implement diagnostic-only subtype tagging for the new provisional Life
   subtypes: `INFO_BUTTON`, `LIFE_TAB`, `METRIC_CARD`, `TIP_CARD`,
   `PROGRAM_CARD`, `EMPTY_OR_NO_DATA_STATUS`
2. Keep existing coverage denominator, matching, and verdict behavior unchanged
3. Extend reports to show provisional subtype counts separately from established
   subtype counts
4. Re-run Energy and Air Care evidence collection and compare subtype
   distribution stability
5. Revisit eligibility only after provisional subtype drift is low enough across
   multiple runs

Phase 4 verdict integration should remain blocked until provisional Life
subtypes have better cross-plugin evidence.
