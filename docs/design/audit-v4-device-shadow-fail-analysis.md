# Audit V4 Device Shadow FAIL Analysis

## Background

Phase 4E monitoring artifacts exposed two device plugins with `V3=PASS` but `V4 Shadow=FAIL`:

- `device_camera_plugin`
- `device_air_purifier_plugin`

This document analyzes those FAIL results using only existing artifacts under `output/audit_v4_monitoring_full_after_popup_push`. No audit rerun, code change, or policy change was performed.

## Source Artifacts

Primary inputs:

- `output/audit_v4_monitoring_full_after_popup_push/audit_report.json`
- `output/audit_v4_monitoring_full_after_popup_push/audit_report.csv`
- `output/audit_v4_monitoring_full_after_popup_push/audit_report.md`
- `output/audit_v4_monitoring_full_after_popup_push/device_camera_plugin/talkback_compare_20260613_121223.normal.log`
- `output/audit_v4_monitoring_full_after_popup_push/device_camera_plugin/talkback_compare_20260613_121223.xlsx`
- `output/audit_v4_monitoring_full_after_popup_push/device_camera_plugin/talkback_compare_20260613_121223/device_camera_plugin/xml_dumps/*.xml`
- `output/audit_v4_monitoring_full_after_popup_push/device_air_purifier_plugin/talkback_compare_20260613_114715.normal.log`
- `output/audit_v4_monitoring_full_after_popup_push/device_air_purifier_plugin/talkback_compare_20260613_114715.xlsx`
- `output/audit_v4_monitoring_full_after_popup_push/device_air_purifier_plugin/talkback_compare_20260613_114715/device_air_purifier_plugin/xml_dumps/*.xml`

Shadow summary from `audit_report.json`:

- Camera: `required_denominator=7`, `required_matched=3`, `required_missing=4`, `required_coverage=42.9`, `shadow=FAIL`
- Air Purifier: `required_denominator=18`, `required_matched=13`, `required_missing=5`, `required_coverage=72.2`, `shadow=FAIL`

## Camera Shadow FAIL Analysis

### Artifact Summary

- V3 verdict: `PASS`
- V3 reason: `All detected tabs visited, exhausted, and content present | (0 local tabs detected)`
- Shadow verdict: `FAIL`
- Shadow reason: `required_coverage<50; provisional_risk_count=11`
- Coverage source: `xlsx`
- XML status: `xml_present_parsed`
- Coverage diagnostic status: `ready`
- Local tabs: none

### Required Missing Inventory

Camera required misses are the four labels below. They are all XML-present, non-clickable, non-focusable text leaves.

| Label | Type/Subtype | Classification | Policy | XML location | Traversal evidence | Root cause |
| --- | --- | --- | --- | --- | --- | --- |
| `06:31` | `STATUS/STATUS_METRIC` | `REVIEW` | `KEEP` | `time_text`, `TextView`, bounds `[45,1195][192,1267]`, tab `unknown` | No exact traversal hit. Log shows `leaf_hard_filter rejected='06:31'` and representative exhaustion around `No history|06:31`. | `EMPTY_STATE_OR_STATUS` |
| `07:39` | `STATUS/STATUS_METRIC` | `REVIEW` | `KEEP` | `time_text`, `TextView`, bounds `[45,1195][192,1267]`, tab `unknown` | No exact traversal hit. Log shows `leaf_hard_filter rejected='07:39'`; representative `07:30 07:30` was traversed instead. | `EMPTY_STATE_OR_STATUS` |
| `08:48` | `STATUS/STATUS_METRIC` | `REVIEW` | `KEEP` | `time_text`, `TextView`, bounds `[45,1195][192,1267]`, tab `unknown` | No exact traversal hit. Log shows `leaf_hard_filter rejected='08:48'`; representative `08:30 08:30` was traversed instead. | `EMPTY_STATE_OR_STATUS` |
| `Camera` | `STATUS/STATUS_LABEL` | `REVIEW` | `KEEP` | `device_text_view`, `TextView`, bounds `[168,165][972,246]`, tabs `entry,unknown` | Never focused. Log repeatedly applies `chrome_penalty` to `Camera|Navigate up|More options|talkback test room`. | `CHROME_OR_SECONDARY_ACTION` |

### Provisional / Suspicious Labels

These labels were highlighted as known risks but did not drive the required-missing count:

| Label | XML characteristics | Traversal evidence | Interpretation |
| --- | --- | --- | --- |
| `Increase` | `ImageButton`, `clickable=true`, `focusable=true` | Traversed exactly multiple times | Camera overlay control, not the FAIL driver |
| `Mute` | `ImageButton`, `focusable=true`, `clickable=false` | Traversed exactly multiple times | Camera overlay control, not the FAIL driver |
| `PIP` | `ImageButton`, `focusable=true`, `clickable=false` | Traversed exactly | Camera overlay control, not the FAIL driver |
| `Motion detection icon` | `ImageView`, `focusable=false`, `clickable=false` | Present in log as `visible='Motion detection icon'`, but absent from xlsx-derived traversal label set | `ARTIFACT_OR_ENVIRONMENT` signal between log and xlsx sources |
| `No history` | `TextView`, `focusable=false`, `clickable=false` | Traversed exactly | Empty-state text, not the FAIL driver |

### Camera Root Cause

Camera FAIL is not explained by missed core traversal of camera controls. The runner clearly traversed the overlay actions `Increase`, `Mute`, `PIP`, `Turn on mic`, `Screen capture`, and the status row `Motion detected`.

The FAIL is instead driven by required denominator inflation:

- timestamp leaves `06:31`, `07:39`, `08:48` were promoted to required because they were typed as `STATUS_METRIC` and policy fell through to `KEEP`
- those timestamp leaves are non-focusable history-row fragments and the runner intentionally treated them as low-value leaves
- `Camera` is a top header/title, not a content target the runner is expected to focus

The artifact also shows one source-quality issue:

- `Motion detection icon` was focused in the log, but because this scenario had `coverage_source=xlsx`, that evidence did not survive into the traversal label set used by shadow input aggregation

### Camera Conclusion

Best-fit explanation:

- primary: `shadow eligibility too strict`
- secondary: `camera UI overlay/control structure mismatch`
- minor supporting issue: `artifact issue` for the log/xlsx discrepancy on `Motion detection icon`

Camera does not look like a genuine runner traversal failure.

## Air Purifier Shadow FAIL Analysis

### Artifact Summary

- V3 verdict: `PASS`
- V3 reason: `All detected tabs visited; repeat_no_progress after exhaustion`
- Shadow verdict: `FAIL`
- Shadow reason: `required_missing_count>=4; provisional_risk_count=8`
- Coverage source: `both`
- XML status: `xml_present_parsed`
- Coverage diagnostic status: `ready`
- Detected/visited tabs: `Controls`, `Routines`, `History`

### Required Missing Inventory

Air Purifier required misses are the five labels below. All five are non-focusable `TextView` leaves under the `Controls` surface.

| Label | Type/Subtype | Classification | Policy | XML location | Traversal evidence | Root cause |
| --- | --- | --- | --- | --- | --- | --- |
| `Air conditioner fan mode` | `STATUS/STATUS_LABEL` | `REVIEW` | `KEEP` | `AirConditionerFanModeCapabilityCardView_header_title`, `TextView`, bounds `[84,2014][936,2086]` | No direct traversal hit. No compound hit containing this exact phrase in saved traversal labels. | `TAXONOMY_GAP` |
| `Air purifier fan mode` | `STATUS/STATUS_LABEL` | `REVIEW` | `KEEP` | `AirPurifierFanModeCapabilityCardView_header_title`, `TextView`, bounds `[84,1702][936,1774]` | No direct traversal hit. Nearby card contains `Sleep` and `Change` but was not stabilized as a saved focus step. | `TAXONOMY_GAP` |
| `Fine dust level` | `STATUS/STATUS_LABEL` | `REVIEW` | `KEEP` | `DustHealthConcernMultiCapabilityCardView_header_title`, `TextView`, bounds `[84,886][936,958]` and `[84,1750][936,1822]` | No direct traversal hit. Log repeatedly reports scroll fallback representative `Fine dust level PM 10 Good PM 2.5 Good PM 1.0 Good`, but that representative never became a saved focus label. | `MATCHING_GAP` |
| `Good` | `STATUS/STATUS_LABEL` | `REVIEW` | `KEEP` | Three non-focusable `TextView` value leaves in the `Fine dust level` card | No direct traversal hit. Present only inside the compound representative `Fine dust level PM 10 Good PM 2.5 Good PM 1.0 Good`. | `MATCHING_GAP` |
| `Sleep` | `STATUS/STATUS_LABEL` | `REVIEW` | `KEEP` | non-focusable `TextView` in fan-mode card, bounds `[84,1816][918,1927]` | No direct traversal hit. Nearby actionable `Change` exists, but no saved focus step for a `Sleep` compound card. | `ELIGIBILITY_GAP` |

### Provisional / Suspicious Labels

These labels were highlighted separately and are useful for diagnosis:

| Label | XML characteristics | Traversal evidence | Interpretation |
| --- | --- | --- | --- |
| `Add routine` | `Button`, `clickable=true`, `focusable=true`, tab `Routines` | No traversal hit | Empty-state CTA in `Routines`; should not drive FAIL |
| `Change` | `Button`, `clickable=true`, `focusable=true`, tab `Controls` | No traversal hit | Secondary action inside fan-mode card; structural ambiguity |
| `History` | Mixed use: local tab plus graph buttons plus `history` view | Traversed exactly | Overloaded label, but not the FAIL driver |
| `No history` | `TextView`, `focusable=false`, tab `History` | No traversal hit | Empty-state text; should not drive FAIL |
| `No routines include this device` | `TextView`, `focusable=true`, tab `Routines` | Traversed exactly | Empty-state body text, not the FAIL driver |

### Air Purifier Root Cause

Air Purifier FAIL is also not best explained as a runner failure:

- all local tabs were detected and visited
- log evidence shows the runner traversed the main control surface and repeatedly selected compound representatives such as:
  - `Air quality History CAQI 0 0100`
  - `Fine dust History PM 10 0 μg/㎥ 0999 PM 2.5 0 μg/㎥ 0999 PM 1.0 0 μg/㎥ 0999`
- log evidence also shows scroll fallback discovering a richer compound representative:
  - `Fine dust level PM 10 Good PM 2.5 Good PM 1.0 Good`

The FAIL comes from requiring internal card headers and leaf values individually:

- `Fine dust level` and `Good` are part of a compound card that the runner reasoned about structurally, but the shadow aggregator only checked saved visible labels
- `Air purifier fan mode`, `Air conditioner fan mode`, and `Sleep` are non-focusable card header/value leaves, not direct TalkBack focus targets in the artifact
- `Add routine` and `No history` are empty-state / secondary-action cases that were already treated as non-core in prior motion-sensor analysis

### Air Purifier Conclusion

Best-fit explanation:

- primary: `empty-state/secondary-action eligibility issue`
- secondary: `device-control taxonomy gap`

This is much closer to a shadow-input / eligibility false positive than a real traversal miss.

## Root Cause Classification Table

| Plugin | Label | Category | Why |
| --- | --- | --- | --- |
| Camera | `06:31` | `EMPTY_STATE_OR_STATUS` | non-focusable time leaf filtered as low-value |
| Camera | `07:39` | `EMPTY_STATE_OR_STATUS` | non-focusable time leaf filtered as low-value |
| Camera | `08:48` | `EMPTY_STATE_OR_STATUS` | non-focusable time leaf filtered as low-value |
| Camera | `Camera` | `CHROME_OR_SECONDARY_ACTION` | header/title penalized as top chrome |
| Camera | `Increase` | `CHROME_OR_SECONDARY_ACTION` | traversed overlay control |
| Camera | `Mute` | `CHROME_OR_SECONDARY_ACTION` | traversed overlay control |
| Camera | `PIP` | `CHROME_OR_SECONDARY_ACTION` | traversed overlay control |
| Camera | `Motion detection icon` | `ARTIFACT_OR_ENVIRONMENT` | focused in log but absent from xlsx-derived traversal labels |
| Camera | `No history` | `EMPTY_STATE_OR_STATUS` | empty-state text, traversed |
| Air Purifier | `Air conditioner fan mode` | `TAXONOMY_GAP` | control-card header treated as required leaf |
| Air Purifier | `Air purifier fan mode` | `TAXONOMY_GAP` | control-card header treated as required leaf |
| Air Purifier | `Fine dust level` | `MATCHING_GAP` | present inside compound representative, not as standalone focus label |
| Air Purifier | `Good` | `MATCHING_GAP` | present only inside compound representative |
| Air Purifier | `Sleep` | `ELIGIBILITY_GAP` | fan-mode state leaf should not be independently required |
| Air Purifier | `Add routine` | `OPTIONAL_CANDIDATE` | Routines empty-state CTA |
| Air Purifier | `Change` | `OPTIONAL_CANDIDATE` | secondary action inside control card |
| Air Purifier | `History` | `STRUCTURAL_CANDIDATE` | overloaded local-tab / graph-action label |
| Air Purifier | `No history` | `EMPTY_STATE_OR_STATUS` | History empty-state text |
| Air Purifier | `No routines include this device` | `EMPTY_STATE_OR_STATUS` | Routines empty-state body text |

## Shadow Policy Impact

### Camera

Assessment: `Shadow REVIEW` is more appropriate than `Shadow FAIL`.

Rationale:

- required misses are header/time leaves, not missed core controls
- provisional controls are mostly traversed successfully
- one provisional label shows a source artifact mismatch between log and xlsx

`Shadow PASS` is possible only after camera-specific eligibility cleanup; current artifacts still contain enough ambiguity to keep it at `REVIEW`.

### Air Purifier

Assessment: `Shadow REVIEW` is more appropriate than `Shadow FAIL`.

Rationale:

- required misses are mostly card-internal labels and values
- tabs were visited and key control cards were traversed as compound representatives
- empty-state and secondary-action labels should not be escalated into a FAIL signal

`Shadow PASS` is plausible after device-control eligibility/taxonomy refinement, but current artifacts still justify a cautious `REVIEW`.

## Recommended Fix Priority

1. Device-control eligibility refinement for non-focusable card headers and leaf values.
   Impact: highest for both Camera and Air Purifier.
   Risk: medium, because over-relaxation could hide legitimate device-control misses.

2. Device-control taxonomy expansion for compound control cards.
   Impact: high for Air Purifier.
   Risk: medium, because new subtypes must be kept consistent across other appliance plugins.

3. Camera-specific overlay/control treatment review.
   Impact: medium for Camera.
   Risk: low to medium, because `Increase`, `Mute`, `PIP`, and icon leaves are structurally unlike standard status cards.

4. Traversal-to-shadow input source alignment for non-local-tab device pages.
   Impact: medium.
   Risk: medium, because Camera showed a log/xlsx discrepancy where `Motion detection icon` existed in the log but not in the shadow traversal label set.

5. Matching enhancement for compound status-card labels.
   Impact: medium for Air Purifier.
   Risk: medium to high, because loose compound matching can create false positives across unrelated cards.

6. Shadow threshold tuning.
   Impact: low as a first fix.
   Risk: high if done before label eligibility is corrected, because it would mask bad denominator construction instead of fixing it.

Artifact recollection is low priority here because the current artifacts are already sufficient to explain both FAILs.

## Conclusion

Both `device_camera_plugin` and `device_air_purifier_plugin` look like shadow false positives rather than true accessibility regressions.

- Camera FAIL is driven by header/time leaves being treated as required content.
- Air Purifier FAIL is driven by card-internal status headers/values and empty-state/secondary-action ambiguity.

The common pattern is not "runner missed core content". The common pattern is "shadow required denominator includes labels that are not reliable direct TalkBack focus targets in these device UIs".
