# Audit V4 Residual Required Miss Analysis

## 1. Background

Audit V4 remains diagnostic-only.

By Phase 3.19, the following reclassifications became well supported:

- `Controls` -> `STRUCTURAL` candidate
- `Add family member` -> `OPTIONAL` candidate
- `View profile` -> `OPTIONAL` candidate

That produced the current paper baseline:

- required denominator: `25`
- required matched: `22`
- required missing: `3`
- required coverage: `88.0%`

This phase validates whether the remaining required misses are real blockers or
whether they are partly residual policy/reporting artifacts.

This document is analysis only. It does not change matching, traversal, runner
behavior, taxonomy implementation, coverage engine behavior, or verdict logic.

## 2. Residual Miss Inventory

### 2.1 Paper Baseline Inventory

Based on the Phase 3.19 denominator simulation, the paper residual required
misses are:

- `EventsButton`
- `LocationButton`
- `Mobile usageButton`

### 2.2 Evidence-Corrected Inventory

Direct normal-log evidence shows that `Mobile usageButton` is actually focused
and spoken during the Family Care run:

- step 14 ends with `visible='Mobile usageButton'`
- focus realignment resolves to `Mobile usageButton`

Therefore the evidence-corrected residual required inventory is:

- `EventsButton`
- `LocationButton`

Inventory summary:

| View | Residual required miss count | Items |
| --- | ---: | --- |
| Paper baseline | 3 | `EventsButton`, `LocationButton`, `Mobile usageButton` |
| Evidence-corrected | 2 | `EventsButton`, `LocationButton` |

### 2.3 Non-Residual But Relevant Required Candidates

For context:

- `ActivityButton` is not residual after suffix-normalization simulation because
  direct traversal evidence includes `Activity`
- `Mobile usageButton` is not residual after direct evidence review because the
  normal log contains an exact spoken focus hit

## 3. Root Cause Classification

| Candidate | Paper status | Evidence-corrected status | Root cause | Confidence |
| --- | --- | --- | --- | --- |
| `ActivityButton` | previously missing | not residual | `MATCHING_GAP` | high |
| `EventsButton` | residual | residual | `TRAVERSAL_GAP` | high |
| `LocationButton` | residual | residual | `TRAVERSAL_GAP` | medium |
| `Mobile usageButton` | residual | not residual | `UNKNOWN` paper artifact resolved by direct evidence | high |

Interpretation:

- `ActivityButton` was a true label-shape problem and is already explainable by
  `ActivityButton` -> `Activity`
- `EventsButton` now looks like the strongest remaining real runner-side miss
- `LocationButton` also looks runner-related, but with weaker direct evidence
  than `EventsButton`
- `Mobile usageButton` should not remain in the residual blocker set

## 4. Family Care Nav Tile Analysis

### 4.1 XML And Position Summary

Source XML:

- `output/audit_v4_phase3_8_evidence/life_family_care_plugin/talkback_compare_20260611_234540/life_family_care_plugin/xml_dumps/000_step_001_entry.xml`
- `output/audit_v4_phase3_8_evidence/life_family_care_plugin/talkback_compare_20260611_234540/life_family_care_plugin/xml_dumps/001_step_019_viewport_exhausted.xml`

| Candidate | XML exists | Clickable | Focusable | Selected | Bounds | Position | Subtype |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ActivityButton` | yes | `false` | `true` | `true` | `[30,2316][370,2496]` | bottom strip | `NAV_TILE` |
| `LocationButton` | yes | `true` | `true` | `false` | `[370,2316][710,2496]` | bottom strip | `NAV_TILE` |
| `EventsButton` | yes | `true` | `true` | `false` | `[710,2316][1050,2496]` | bottom strip | `NAV_TILE` |
| `Mobile usageButton` | yes | `true` | `true` | `true` | `[78,1729][430,1837]` | content card / in-body tile | `NAV_TILE` in prior policy, but behavior is content-tile-like |

### 4.2 Traversal Evidence Summary

| Candidate | Actual traversal counterpart | Traversal hit | Notes |
| --- | --- | --- | --- |
| `ActivityButton` | `Activity` | yes | direct step-end focus hit |
| `LocationButton` | none directly observed | no | appears in recovered local-tab state as current row |
| `EventsButton` | none directly observed | no | local-tab lifecycle and activation attempts observed, but focus never lands |
| `Mobile usageButton` | `Mobile usageButton` | yes | direct exact focus hit at step 14 |

### 4.3 Detailed Findings

`ActivityButton`

- XML exists in the bottom strip.
- Normal log contains direct focus evidence:
  `visible='Activity'`.
- This remains the cleanest confirmed `BUTTON_SUFFIX` case.

`EventsButton`

- XML exists and is clickable/focusable.
- Normal log contains:
  `LIFECYCLE step=16 kind='local_tab' label='EventsButton'`
- After bottom-strip recovery, the runner attempts to progress from
  `LocationButton Location` to `EventsButton Events`.
- Activation attempts fail:
  `local_tab_target_activate_fail target='EventsButton Events'`
- No final spoken focus hit for `EventsButton` or `Events` is observed.

Interpretation:

- This is the strongest confirmed residual required miss.
- It behaves like a real traversal/local-tab activation gap.

`LocationButton`

- XML exists and is clickable/focusable.
- No direct spoken focus hit for `LocationButton` or `Location` is observed.
- However, bottom-strip recovery later reports:
  `active='LocationButton Location'`
  and uses it as the current row when progressing to `EventsButton Events`.

Interpretation:

- This is weaker than `EventsButton`, because the log shows recovered state but
  not a direct user-facing focus event.
- Still, because `Activity` is spoken and the strip itself is clearly
  focusable/clickable, the missing `LocationButton` is more plausibly a
  traversal gap than a denominator mistake.

`Mobile usageButton`

- XML exists in the content body and is clickable/focusable.
- The runner explicitly realigns focus to it.
- Step 14 ends with:
  `visible='Mobile usageButton' speech='Mobile usageButton'`

Interpretation:

- This should not be kept in the residual required miss inventory.

## 5. TalkBack Expectation

### 5.1 Candidate-Level Expectation

| Candidate | Should TalkBack read it? | Should it always be expected? | Proposed eligibility |
| --- | --- | --- | --- |
| `ActivityButton` | yes | yes | `REQUIRED` |
| `EventsButton` | yes | yes | `REQUIRED` |
| `LocationButton` | yes | yes | `REQUIRED` |
| `Mobile usageButton` | yes | yes | `REQUIRED` |

Reasoning:

- All four are focusable plugin-local actionable navigation surfaces.
- `ActivityButton` and `Mobile usageButton` already show direct evidence that the
  user can hear them.
- The existence of spoken hits on adjacent strip/content tiles strengthens the
  expectation that `EventsButton` and `LocationButton` are legitimate required
  targets rather than optional decoration.

### 5.2 Policy Implication

This phase does not support moving `EventsButton` or `LocationButton` out of the
required denominator.

It also does not support `STRUCTURAL` for these labels:

- unlike `Controls`, these are not hidden structural state tokens
- they are clickable and intended for direct navigation between Family Care
  sections

Recommended eligibility:

- `EventsButton` -> `REQUIRED`
- `LocationButton` -> `REQUIRED`
- `Mobile usageButton` -> `REQUIRED`, but already matched

## 6. Coverage Impact

### 6.1 Paper Baseline

From Phase 3.19:

- denominator `25`
- matched `22`
- missing `3`
- coverage `88.0%`

### 6.2 Evidence-Corrected Baseline

Because `Mobile usageButton` is directly matched in the normal log, the
evidence-corrected residual state is:

- denominator `25`
- matched `23`
- missing `2`
- coverage `92.0%`

### 6.3 Removal Simulation

Using the evidence-corrected baseline:

| Case | Denominator | Matched | Missing | Coverage |
| --- | ---: | ---: | ---: | ---: |
| Current evidence-corrected baseline | 25 | 23 | 2 | 92.0% |
| Remove `EventsButton` only | 24 | 23 | 1 | 95.8% |
| Remove `LocationButton` only | 24 | 23 | 1 | 95.8% |
| Remove both | 23 | 23 | 0 | 100.0% |

Interpretation:

- The remaining gap is numerically small.
- But the remaining gap is concentrated in a narrow, meaningful navigation
  surface, not in static text or denominator noise.

## 7. Phase 4 Blocker Assessment

| Candidate | Blocker level | Reason |
| --- | --- | --- |
| `EventsButton` | `BLOCKER` | strongest remaining real navigation miss with direct activation-failure evidence |
| `LocationButton` | `MINOR` | likely real miss, but evidence is weaker and partly state-recovery-based |
| `Mobile usageButton` | `NON_BLOCKER` | directly matched in traversal evidence |

Net assessment:

- The residual set is not large enough to be treated as a broad Phase 4
  policy blocker.
- But it is not purely a policy artifact either.
- The remaining blocker is concentrated in Family Care bottom-strip traversal,
  especially `EventsButton`.

Practical reading:

- this is a localized runner/traversal-quality issue
- not a taxonomy problem
- not a denominator-eligibility problem
- not a major program-wide blocker

## 8. Shadow Verdict Readiness

Result: `PARTIAL`

Why not `READY`:

- there is still at least one strong residual required miss on a core
  navigation surface
- `EventsButton` is difficult to dismiss as a policy artifact

Why not `NOT_READY`:

- denominator ambiguity has been reduced substantially
- Family Care CTA ambiguity has been removed from the required set
- the remaining miss set is small, specific, and understandable
- evidence-corrected required coverage is already about `92%`

Working conclusion:

- Shadow verdict exploration can proceed, but Family Care bottom-strip
  navigation should remain a known watchlist item

## 9. Recommendation

Recommended conclusions:

1. Correct the residual required miss inventory conceptually from `3` to `2`
   by removing `Mobile usageButton` from the unresolved set
2. Keep `EventsButton` and `LocationButton` as `REQUIRED`
3. Treat `EventsButton` as the primary remaining real blocker
4. Treat `LocationButton` as a secondary residual miss with medium-confidence
   runner/traversal explanation

Recommended next step:

- proceed to `Phase 4 Shadow Verdict` planning with an explicit known-risk note
  for Family Care bottom-strip navigation

Bottom line:

- the remaining required misses are real enough to matter
- but they are too small and too localized to justify blocking all Phase 4
  shadow-verdict work
