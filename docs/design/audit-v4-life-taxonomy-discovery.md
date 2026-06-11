# Audit V4 Phase 3.9 Life Taxonomy Discovery

## Scope

This note records Life plugin candidate evidence from Phase 3.8 artifacts. It is
diagnostic-only discovery material. It does not change KEEP / REVIEW / EXCLUDE
classification, coverage denominator policy, matching policy, traversal, TalkBack
collection, V3 verdict logic, or verdict integration.

Source artifacts:

- `output/audit_v4_phase3_8_evidence/life_family_care_plugin`
- `output/audit_v4_phase3_8_evidence/life_home_care_plugin`
- `output/audit_v4_phase3_8_evidence/life_food_plugin`
- `out/life_energy_plugin`

## Artifact Readiness

| Scenario | XML status | Traversal artifact | Coverage status | Notes |
| --- | --- | --- | --- | --- |
| `life_family_care_plugin` | parsed, 2 XML dumps | yes | `ready_empty_denominator` | 40 merged candidates, all non-chrome candidates are REVIEW |
| `life_home_care_plugin` | parsed, 5 XML dumps | yes | `ready_empty_denominator` | 10 merged candidates, all candidates are REVIEW |
| `life_food_plugin` | empty/missing XML evidence | partial run artifact | `xml_missing` or empty | run failed before plugin evidence |
| `life_energy_plugin` | empty XML directory only | no current traversal artifact | not ready | no taxonomy evidence |

## Family Care Candidate Inventory

Observed REVIEW candidates:

- `%`
- `/`
- `0`
- `1`
- `10`
- `11:46`
- `13`
- `35`
- `4:00`
- `6000`
- `Active now`
- `Activity`
- `ActivityButton`
- `Add family member`
- `Add home information`
- `AM`
- `Avg (week)`
- `Device usage`
- `Events`
- `EventsButton`
- `Family Care`
- `First activity`
- `h`
- `It's time to go to bed so you can feel well rested tomorrow.`
- `Latest activity`
- `Location`
- `LocationButton`
- `m`
- `Me`
- `Mobile usage`
- `Mobile usageButton`
- `PM`
- `Steps`
- `Today`
- `View information`
- `View profile`
- `Weather information, Icon. Add home information`
- `건우의 Z Flip6`

Observed EXCLUDE candidates:

- `More options`
- `Navigate up`

Current UNKNOWN candidates:

- `ActivityButton`

Discovery grouping:

- `CTA`: `Add family member`, `View information`, `View profile`
- `NAV_TILE`: `ActivityButton`, `EventsButton`, `LocationButton`, `Mobile usageButton`
- `STATUS_METRIC`: `%`, `0`, `6000`, `Steps`, `Today`, `Avg (week)`, `11:46`, `4:00`, `AM`, `PM`
- `STATUS_LABEL`: `Active now`, `Activity`, `Device usage`, `Events`, `Family Care`, `First activity`, `Latest activity`, `Location`, `Me`, `Mobile usage`
- `ONBOARDING`: `Add home information`, `Weather information, Icon. Add home information`
- `INSTRUCTIONAL_STATUS`: `It's time to go to bed so you can feel well rested tomorrow.`
- `CHROME`: `More options`, `Navigate up`

Coverage candidacy notes:

- Likely coverage candidates: CTA, NAV_TILE, high-level service labels, status cards
- Needs review before denominator: standalone units and bare values such as `%`, `/`, `h`, `m`, `AM`, `PM`
- Exclude: shell chrome

## Home Care Candidate Inventory

Observed REVIEW candidates:

- `,`
- `, Connect Samsung home appliances and get smart care using the latest AI technology.`
- `Air purifier,Self-diagnosis if fine dust count does not decrease, Room air conditioner,How to clean the microfilter, Refrigerator,How to dispense ice`
- `Connect home appliances`
- `Device care`
- `Home Care`
- `Samsung Care+`
- `Smart Forward, Update your device and check out the new features of Home Life service.`
- `SmartThings Home Care`
- `Usage guide`

Current UNKNOWN candidates:

- `Air purifier,Self-diagnosis if fine dust count does not decrease, Room air conditioner,How to clean the microfilter, Refrigerator,How to dispense ice`
- `Connect home appliances`
- `Device care`
- `Home Care`
- `SmartThings Home Care`
- `Usage guide`

Discovery grouping:

- `SERVICE_TILE`: `Connect home appliances`, `Device care`, `Samsung Care+`, `Smart Forward, Update your device and check out the new features of Home Life service.`, `Usage guide`
- `CONTENT_CARD`: `Air purifier,Self-diagnosis if fine dust count does not decrease, Room air conditioner,How to clean the microfilter, Refrigerator,How to dispense ice`
- `SCREEN_TITLE`: `Home Care`, `SmartThings Home Care`
- `PROMOTION_OR_SERVICE_CARD`: `Samsung Care+`, `Smart Forward, Update your device and check out the new features of Home Life service.`
- `INSTRUCTIONAL_STATUS`: `, Connect Samsung home appliances and get smart care using the latest AI technology.`
- `LOW_VALUE_LABEL`: `,`

Coverage candidacy notes:

- Likely coverage candidates: SERVICE_TILE, CONTENT_CARD, CTA-like service cards
- Needs review before denominator: screen title and instructional copy
- Likely exclude or normalize away: `,`

## Food And Energy Evidence

`life_food_plugin` did not produce usable XML evidence in the Phase 3.8 run. The
run ended with `ENVIRONMENT_ERROR` before plugin XML capture.

`life_energy_plugin` has only an empty XML directory in current local artifacts.
There is not enough evidence for taxonomy discovery.

## Candidate Type Proposal

Current shared types remain useful:

- `ACTIONABLE`
- `STATUS`
- `EMPTY_STATE`
- `INSTRUCTIONAL`
- `CHROME`
- `UNKNOWN`

Life-specific candidates suggest adding policy-level taxonomy concepts later:

- `CTA`
- `NAV_TILE`
- `SERVICE_TILE`
- `CONTENT_CARD`
- `SCREEN_TITLE`
- `ONBOARDING`
- `PROMOTION_OR_SERVICE_CARD`
- `STATUS_METRIC`
- `STATUS_LABEL`
- `INSTRUCTIONAL_STATUS`
- `LOW_VALUE_LABEL`

## Unified Taxonomy Assessment

A unified Device + Life taxonomy is possible if it has general primitives plus
domain-specialized subtypes. Device plugins are mostly local tabs, status values,
action buttons, empty states, and shell chrome. Life plugins add WebView-like
service tiles, content cards, onboarding prompts, dashboard metrics, and
promotional service cards.

Recommended shape for Phase 3.10:

- Keep shared top-level buckets: `ACTIONABLE`, `STATUS`, `EMPTY_STATE`, `INSTRUCTIONAL`, `CHROME`, `UNKNOWN`
- Add diagnostic subtypes for Life candidates first, without changing denominator
- Use XML metadata and traversal evidence to decide which Life subtypes can move
  from REVIEW to KEEP in a later policy phase

## Phase 3.10 Readiness

Phase 3.10 is appropriate before Phase 4. The immediate next step should be
diagnostic-only subtype tagging for Life candidates. Coverage policy and verdict
integration should remain unchanged until Life subtype behavior is stable across
more than Family Care and Home Care.
