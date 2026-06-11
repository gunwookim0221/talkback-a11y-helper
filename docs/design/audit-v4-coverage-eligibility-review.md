# Audit V4 Phase 3.11 Coverage Candidate Eligibility Review

## Scope

This document evaluates coverage denominator eligibility using the current Phase
3.10 diagnostics. It is policy review material only.

No implementation policy is changed here:

- Coverage denominator remains unchanged.
- Coverage calculation remains unchanged.
- KEEP / REVIEW / EXCLUDE classification remains unchanged.
- Matching remains `normalized_exact`.
- V3 verdict logic and verdict integration are unchanged.
- Traversal and TalkBack collection are unchanged.

Source evidence:

- `output/audit_v4_phase3_8_evidence/device_motion_sensor_plugin`
- `output/audit_v4_phase3_8_evidence/device_smoke_sensor_plugin`
- `output/audit_v4_phase3_8_evidence/device_door_lock_plugin`
- `output/audit_v4_phase3_8_evidence/life_family_care_plugin`
- `output/audit_v4_phase3_8_evidence/life_home_care_plugin`
- `output/audit_v4_phase3_8_evidence/life_food_plugin`
- `out/life_energy_plugin`

## Subtype Eligibility Draft

| Subtype | Coverage candidate? | Rationale |
| --- | --- | --- |
| `CTA` | YES | Primary user-facing actions are expected TalkBack traversal targets. |
| `NAV_TILE` | YES | Navigation tiles are focusable plugin content and should be reachable. |
| `SERVICE_TILE` | YES | Life dashboard service tiles are primary content cards. |
| `CONTENT_CARD` | YES | Content cards represent visible, focusable Life content. |
| `STATUS_LABEL` | YES | Status labels describe visible state or dashboard content. |
| `STATUS_METRIC` | MAYBE | Metrics are meaningful when paired with labels, but standalone units/values can over-count. |
| `SCREEN_TITLE` | MAYBE | Titles are useful context, but may duplicate plugin identity or shell titles. |
| `ONBOARDING` | MAYBE | Setup prompts can be real content, but may be conditional or transient. |
| `PROMOTION_OR_SERVICE_CARD` | MAYBE | Service cards may be useful content; pure promotion should not be required. |
| `INSTRUCTIONAL_STATUS` | MAYBE | Instructions may be static text and may not always be focusable as separate items. |
| `EMPTY_STATE` | MAYBE | Empty states are useful diagnostic evidence but should not always be required coverage. |
| `LOW_VALUE_LABEL` | NO | Punctuation-only or structural labels are not useful coverage targets. |
| `CHROME` | NO | Shell and toolbar controls should stay outside plugin coverage denominator. |
| `UNKNOWN` | MAYBE | Needs subtype or explicit policy before denominator inclusion. |

## Proposed Tier Vocabulary

The safest next policy shape is:

- `REQUIRED`: Core plugin content that should be traversed.
- `OPTIONAL`: Useful diagnostic content but too conditional, duplicated, or unstable for required denominator.
- `EXCLUDED`: Shell chrome, low-value labels, or non-plugin verification targets.

This is only a proposal. The current code does not implement these tiers.

## Device Candidate Re-Evaluation

Device plugins are mostly covered by existing top-level types.

Likely `REQUIRED`:

- Local tabs: `Controls`, `History`, `Routines`
- Device state labels: `Motion sensor`, `Motion detected`, `Smoke detector`, `Carbon monoxide detector`, `Clear`, `Lock state`, `Locked`
- Meaningful device values: `100%`

Likely `OPTIONAL`:

- `Add routine`: actionable but toolbar/secondary action-like
- `No history`, `No routines include this device`: empty-state text
- Device/plugin titles such as `Door Lock, talkback test room`
- Instructional routine examples
- Generic controls such as `switch` until better subtype evidence exists

Likely `EXCLUDED`:

- `Navigate up`
- `More options`
- `SmartThings Plugin`

## Denominator Simulation

This simulation uses the proposed `REQUIRED` / `OPTIONAL` / `EXCLUDED` tiers. It
does not change runtime coverage.

| Scenario | Merged | Current KEEP/REVIEW/EXCLUDE | Simulated REQUIRED | Simulated OPTIONAL | Simulated EXCLUDED |
| --- | ---: | --- | ---: | ---: | ---: |
| `device_motion_sensor_plugin` | 13 | 8 / 3 / 2 | 6 | 4 | 3 |
| `device_smoke_sensor_plugin` | 13 | 5 / 6 / 2 | 6 | 4 | 3 |
| `device_door_lock_plugin` | 13 | 5 / 6 / 2 | 5 | 5 | 3 |
| `life_family_care_plugin` | 40 | 0 / 38 / 2 | 21 | 17 | 2 |
| `life_home_care_plugin` | 10 | 0 / 10 / 0 | 4 | 5 | 1 |

### Device Simulation Details

`device_motion_sensor_plugin`

- REQUIRED: `100%`, `Controls`, `History`, `Motion detected`, `Motion sensor`, `Routines`
- OPTIONAL: `Add routine`, `Motion detection notifications, Example: every day, 6:00 PM - 10:00 PM`, `No history`, `모션센서, talkback test room - 거실`
- EXCLUDED: `More options`, `Navigate up`, `SmartThings Plugin`

`device_smoke_sensor_plugin`

- REQUIRED: `Carbon monoxide detector`, `Clear`, `Controls`, `History`, `Routines`, `Smoke detector`
- OPTIONAL: `Add routine`, `No history`, `No routines include this device`, `연기, talkback test room - 거실`
- EXCLUDED: `More options`, `Navigate up`, `SmartThings Plugin`

`device_door_lock_plugin`

- REQUIRED: `Controls`, `History`, `Lock state`, `Locked`, `Routines`
- OPTIONAL: `Add routine`, `Door Lock, talkback test room`, `No history`, `No routines include this device`, `switch`
- EXCLUDED: `More options`, `Navigate up`, `SmartThings Plugin`

### Life Simulation Details

`life_family_care_plugin`

- REQUIRED: `CTA`, `NAV_TILE`, and `STATUS_LABEL` candidates such as `Add family member`, `ActivityButton`, `EventsButton`, `LocationButton`, `Mobile usageButton`, `Active now`, `Activity`, `Device usage`, `Family Care`, `Location`, `Me`, `Mobile usage`, `Steps`, `Today`, `View information`, `View profile`
- OPTIONAL: `STATUS_METRIC`, `SCREEN_TITLE`, `ONBOARDING`, and unit-like candidates such as `%`, `/`, `0`, `11:46`, `6000`, `AM`, `PM`, `Add home information`, `Weather information, Icon. Add home information`
- EXCLUDED: `More options`, `Navigate up`

`life_home_care_plugin`

- REQUIRED: `Connect home appliances`, `Device care`, `Air purifier,Self-diagnosis if fine dust count does not decrease, Room air conditioner,How to clean the microfilter, Refrigerator,How to dispense ice`, `, Connect Samsung home appliances and get smart care using the latest AI technology.`
- OPTIONAL: `Home Care`, `SmartThings Home Care`, `Usage guide`, `Samsung Care+`, `Smart Forward, Update your device and check out the new features of Home Life service.`
- EXCLUDED: `,`

## Food And Energy Impact

Food and Energy remain evidence gaps.

- `life_food_plugin`: the Phase 3.8 run ended before usable plugin XML capture, so there is no reliable candidate inventory.
- `life_energy_plugin`: current local artifacts contain no usable XML/traversal evidence.

The current taxonomy likely covers service tiles, content cards, CTAs, and
promotions that may appear in Food/Energy, but this is not proven. Phase 4 should
not rely on Life coverage policy until at least one Food or Energy run has usable
XML plus traversal evidence.

## Phase 4 Readiness

Result: **B. Food/Energy evidence needed**.

Device policy is close to Phase 4 design readiness. Life policy is not ready for
verdict integration because Family/Home Care are only two Life surfaces and
Food/Energy evidence is missing. The next safe step is diagnostic-only tier
simulation in reports, or additional Life evidence collection, not verdict
integration.

## Residual Risks

- `STATUS_METRIC` may over-count standalone values and units.
- `SCREEN_TITLE` may duplicate shell/plugin identity rather than plugin content.
- `PROMOTION_OR_SERVICE_CARD` mixes useful service cards with possible marketing content.
- `LOW_VALUE_LABEL` shows XML over-detection and should be excluded or normalized before any denominator policy.
- Food/Energy could introduce card types not represented by Family/Home Care.
