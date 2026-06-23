# Semantic Value Shadow Audit

## 1. Purpose

This document explains the reporting-only semantic value audit layer that now
exists alongside the core TalkBack result pipeline.

It covers:

- semantic value discovery from semantic card metadata;
- speech matching and nearby evidence;
- semantic value quality and importance;
- semantic value confidence;
- media card semantic extraction;
- shadow review and gate candidate semantics;
- known limitations.

This layer does not change traversal behavior and does not change the primary
`PASS`, `WARN`, `FAIL`, or `mismatch_type` outputs.

## 2. Scope

Included:

- `semantic_card_values`
- `semantic_value_*` result columns
- semantic value summary metrics
- semantic value confidence rules
- media card semantic extraction rules
- shadow review / gate candidate interpretation

Explicitly excluded:

- TalkBack traversal movement
- candidate selection
- local tab progression
- `final_result`
- `mismatch_type`
- shadow verdict enforcement

## 3. Semantic Value Coverage

Semantic value coverage starts from semantic card metadata generated during row
collection. The key input is:

- `semantic_card_values`

That value is projected into reporting columns:

- `semantic_value_labels`
- `semantic_value_covered`
- `semantic_value_missing`
- `semantic_value_total_count`
- `semantic_value_matched_count`
- `semantic_value_match_source`

The intent is to answer:

- "Was the user-meaningful value for this card or row actually observed in the
  TalkBack speech evidence?"

Examples:

Washer:

- `Rinse mode` / `Normal`
- `Status` / `Stopped`
- `On`

TV:

- `picturemode` / `Standard`

Air Purifier:

- PM reading / `0 ug/m3`
- air quality labels such as `CAQI`

Audio:

- `Spotify`
- `25`
- actions such as `Play`, `Mute`, `Next`

## 4. Coverage Matching

Semantic value matching is reporting-only and text-based.

Current evidence sources:

- `announcement`
- `representative`
- `nearby_announcement`

Matching flow:

1. Extract semantic value labels from `semantic_card_values`.
2. Try direct match against the row announcement text.
3. If not fully covered, try representative text evidence.
4. If still not fully covered, try nearby announcement evidence using a strict
   same-card / nearby-row relation.

Important policy:

- representative evidence can contribute to semantic value coverage;
- this does not mean the representative row is treated as a primary TalkBack
  focus row for V7 focusable coverage;
- semantic value coverage and focusable coverage are different audit layers.

`semantic_value_match_source` stores the winning evidence sources joined by `|`.

Typical values:

- `announcement`
- `representative`
- `nearby_announcement`
- combinations such as `announcement|nearby_announcement`

## 5. Semantic Value Shadow Quality

Semantic value quality is a reporting-only classification that summarizes value
coverage completeness.

Values:

- `VALUE_NOT_APPLICABLE`
- `VALUE_FULLY_COVERED`
- `VALUE_PARTIALLY_COVERED`
- `VALUE_MISSING`

Definitions:

- `VALUE_NOT_APPLICABLE`
  No semantic value labels are available for the row.
- `VALUE_FULLY_COVERED`
  All discovered semantic value labels matched allowed speech evidence.
- `VALUE_PARTIALLY_COVERED`
  At least one value matched, but not all values matched.
- `VALUE_MISSING`
  Semantic value labels were expected, but none were matched strongly enough.

These values do not alter:

- `final_result`
- `mismatch_type`
- `PASS` / `WARN` / `FAIL`

They are shadow / reporting signals only.

## 6. Semantic Value Importance

Each semantic value row is also classified by importance:

- `high`
- `medium`
- `low`
- `ignore`

Current intent:

- `high`
  State or status values that directly affect user understanding.
- `medium`
  Secondary mode / cycle / preset values that still matter but are less urgent.
- `low`
  Values with weaker operational importance or lower confidence as a gate input.
- `ignore`
  Action-like or UI chrome labels that should not drive semantic value quality
  escalation.

Examples:

- `high`
  `On`, `Off`, `Locked`, `Unlocked`, `Stopped`, battery values, PM values,
  volume values, channel values
- `medium`
  `Normal`, `Standard`, mode values, cycle values
- `ignore`
  `Change`, `Edit`, `History`, `More`

This importance classification is still shadow-only and is intended to guide
review prioritization rather than verdict enforcement.

## 7. Semantic Value Confidence

Semantic value confidence indicates how strong the speech evidence is for the
 value match.

Values:

- `HIGH`
- `MEDIUM`
- `LOW`
- `NONE`

Definitions:

- `HIGH`
  Direct match from the row announcement.
- `MEDIUM`
  Match found only through representative evidence.
- `LOW`
  Match found only through nearby announcement evidence.
- `NONE`
  No coverage evidence exists, or the row is not applicable.

Companion field:

- `semantic_value_confidence_reason`

Typical reasons:

- `announcement`
- `representative`
- `nearby_announcement`
- `not_applicable`
- `no_evidence`

Important limitation:

- representative evidence is weaker than direct announcement evidence;
- confidence affects semantic value review interpretation only;
- confidence does not change `final_result` by itself.

## 8. Media Card Semantic Extraction

Media semantic extraction is intentionally narrower than generic capability card
extraction.

Current policy:

- Only clear Music Player / Media Player style surfaces are treated as media
  semantic cards.
- Broad keywords such as `audio`, `speaker`, or generic `volume` are not enough
  by themselves.
- This narrower rule exists to avoid TV contamination such as `Volume Mute`
  being misclassified as audio media semantics.

Current supported behavior:

- `MusicPlayerCapabilityCardView` or equivalent media-player resource families
  can produce semantic values and actions.

Audio examples:

- values
  `Spotify`, `25`
- actions
  `Play`, `Pause`, `Next`, `Mute`

TV limitation:

- TV `Volume Mute` is intentionally not treated as media semantic extraction in
  this phase.
- TV audio / volume semantics require a separate phase with device-specific
  precision checks.

## 9. Shadow Review And Gate Candidates

Two reporting fields surface rows that deserve extra attention:

- `semantic_value_review_candidate`
- `semantic_value_gate_candidate`

Meaning:

- `semantic_value_review_candidate`
  The row should be reviewed because the semantic value signal is incomplete or
  weak enough to warrant manual inspection.
- `semantic_value_gate_candidate`
  The row is a potential future enforcement candidate, but is not enforced
  today.

Current operational policy:

- both are reporting-only;
- neither one changes `PASS`, `WARN`, `FAIL`;
- neither one activates automatic gate failure.

It is valid for:

- `semantic_value_review_candidate > 0`
- `semantic_value_gate_candidate = 0`

This can happen after false-positive reduction has removed unsafe gate
classifications while still leaving rows worth reviewing.

## 10. Result And Summary Columns

Current result-sheet semantic value fields include:

- `semantic_card_values`
- `semantic_value_labels`
- `semantic_value_covered`
- `semantic_value_missing`
- `semantic_value_total_count`
- `semantic_value_matched_count`
- `semantic_value_match_source`
- `semantic_value_confidence`
- `semantic_value_confidence_reason`
- `semantic_value_quality`
- `semantic_value_importance`
- `semantic_value_gate_candidate`
- `semantic_value_review_candidate`
- `semantic_value_quality_reason`

Current summary metrics include coverage, quality, and confidence aggregates.

Examples:

- `semantic_value_total`
- `semantic_value_covered`
- `semantic_value_missing`
- `semantic_value_coverage_rate`
- `semantic_value_quality_total`
- `semantic_value_quality_full`
- `semantic_value_quality_partial`
- `semantic_value_quality_missing`
- `semantic_value_confidence_high`
- `semantic_value_confidence_medium`
- `semantic_value_confidence_low`
- `semantic_value_confidence_none`

## 11. Relationship To Shadow Verdict

Shadow verdict is a separate reporting layer.

Semantic value signals can influence shadow interpretation, but they do not
replace the row-quality pipeline.

In particular:

- semantic value quality is not a replacement for row mismatch analysis;
- semantic value confidence is not a replacement for focus confidence;
- review / gate candidate fields are not enforcement verdicts.

## 12. Known Limitations

Current limitations:

- Rows without semantic metadata remain `VALUE_NOT_APPLICABLE`.
- Representative-based confidence is weaker than direct announcement evidence.
- Nearby announcement evidence is weaker than representative evidence.
- Media semantic extraction is still Audio-centered.
- TV volume semantics are intentionally excluded in the current media phase.
- Gate candidates are still under operational validation and are not enforced.
- Capability-card coverage and semantic value coverage can disagree when a value
  is inferable from context but not persisted as its own TalkBack row.

## 13. Recommended Reading

Related design documents:

- [Audit V7 Focusable Coverage Design](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v7-focusable-coverage-design.md)
- [Audit V4 Shadow Verdict Design](/d:/Python%20test/talkback-a11y-helper/docs/design/audit-v4-shadow-verdict-design.md)
