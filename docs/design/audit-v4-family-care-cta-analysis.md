# Audit V4 Family Care CTA Analysis

## 1. Background

Audit V4 remains diagnostic-only.

After matching-gap analysis, traversal-gap analysis, and local-tab eligibility
revalidation, the main unresolved Family Care required misses are:

- `Add family member`
- `View profile`

The key question is whether these two CTA candidates are truly required TalkBack
coverage targets, or whether they are secondary header/profile actions that
should not remain in the required denominator.

This document is analysis only. It does not change runner behavior, traversal,
coverage engine behavior, matching, verdict logic, or TalkBack collection.

## 2. CTA Inventory

Source XML:

- `output/audit_v4_phase3_8_evidence/life_family_care_plugin/talkback_compare_20260611_234540/life_family_care_plugin/xml_dumps/000_step_001_entry.xml`

| CTA | Resource ID | Class | Clickable | Focusable | Bounds | Screen position | Candidate subtype |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Add family member` | `com.samsung.android.plugin.care:id/menu_main_invite_member` | `android.widget.Button` | `true` | `true` | `[804,118][924,310]` | top-right header | `CTA` |
| `View profile` | `com.samsung.android.plugin.care:id/profile_icon` | `android.widget.ImageView` | `true` | `true` | `[798,346][1008,556]` | right side of profile header | `CTA` |

Shared properties:

- both exist in the entry XML
- both are actionable
- both are visible in the initial viewport
- both are classified in prior analysis as `CTA`

## 3. UI Position Analysis

### 3.1 `Add family member`

Parent region evidence:

- parent header region bounds: `[0,94][1080,310]`
- sibling controls: `Navigate up`, `Family Care`, `More options`
- immediate container is the action-bar right-side layout

Position classification:

- `top app chrome / action-bar secondary action`

Interpretation:

- Although it is plugin-specific rather than system chrome, it is structurally
  colocated with normal app-bar controls.
- It behaves more like a top-level secondary management action than like main
  dashboard content.

### 3.2 `View profile`

Parent region evidence:

- parent profile-selector region bounds: `[30,310][1050,622]`
- nearby labels: `Me`, `Active now`
- content body starts below this region at the main viewpager area

Position classification:

- `profile header`

Interpretation:

- It is not top app chrome.
- It is also not part of the main content feed.
- It is a header-level profile affordance attached to the current selected
  person/account state.

## 4. TalkBack Expectation

### 4.1 `Add family member`

Expectation judgment:

- `C` - chrome-adjacent / not a strong required spoken target

Reasoning:

- It is placed inside the same header strip as `Navigate up`, title, and
  `More options`.
- The runner repeatedly treats it as part of the top chrome set during content
  traversal.
- It is a valid accessible action, but the evidence does not support treating
  it the same way as a main body CTA such as a content card action.

Practical reading:

- A TalkBack user may encounter it when explicitly navigating the top header.
- But it is not strong evidence for inclusion in required traversal coverage of
  the Family Care content surface.

### 4.2 `View profile`

Expectation judgment:

- `B` - may be read, but not a stable required content target

Reasoning:

- It is actionable and visibly exposed in the profile header.
- It is outside the main content list and is attached to the current selected
  profile rather than to the dashboard body.
- It is more content-adjacent than `Add family member`, but it is still a
  header/profile action rather than a core feed traversal target.

Practical reading:

- A TalkBack user could reasonably hear it in some navigation paths.
- But the current evidence is not strong enough to require it as a core
  denominator target for coverage scoring.

## 5. Reachability Evidence

### 5.1 `Add family member`

Observed evidence:

- XML exists: yes
- clickable: `true`
- focusable: `true`
- visible in entry viewport: yes
- TalkBack focus evidence: none in collected traversal
- Traversal hit: none
- chrome-penalty evidence: yes, repeatedly

Strong log evidence:

- entry identity includes `Add family member` in top visible labels
- content-phase logs repeatedly show:
  `chrome_penalty deprioritized='Navigate up|Family Care|Add family member|More options'`

Assessment:

- This is not an XML-missing case.
- It is not a hidden case.
- The runner treats it as a header/chrome-adjacent action and therefore does
  not revisit it as a content target.

### 5.2 `View profile`

Observed evidence:

- XML exists: yes
- clickable: `true`
- focusable: `true`
- visible in entry viewport: yes
- TalkBack focus evidence: none in collected traversal
- Traversal hit: none
- chrome-penalty evidence: no direct explicit exclusion line

Relevant log evidence:

- entry body text includes `View profile`
- entry focus-visible set includes `View profile`
- later traversal proceeds through content and lower navigation without a direct
  focus hit on `View profile`

Assessment:

- This is also not an XML-missing case.
- The evidence is weaker than for `Add family member` in proving active runner
  suppression.
- However, it still behaves like a header-level action that is bypassed by the
  current traversal path.

## 6. Eligibility Recommendation

This is a policy proposal only.

| CTA | Recommended eligibility | Why |
| --- | --- | --- |
| `Add family member` | `OPTIONAL` | action-bar-adjacent secondary management CTA, not strong core-content denominator candidate |
| `View profile` | `OPTIONAL` | profile-header CTA, accessible and useful, but not a stable main-content traversal target |

Why not `REQUIRED`:

- neither CTA has direct TalkBack focus evidence in the collected run
- both sit outside the main content body
- `Add family member` is repeatedly treated as header chrome by the traversal logic

Why not `STRUCTURAL`:

- unlike `Controls`, these are real actionable CTAs, not structural state tokens
- they should remain visible in analysis, just not in the strict required denominator

Why not `EXCLUDED`:

- both are meaningful user actions
- removing them entirely would hide useful diagnostic evidence

Recommended classification shape:

- `Add family member` -> `OPTIONAL`
- `View profile` -> `OPTIONAL`

## 7. Coverage Simulation

Starting point from Phase 3.18:

- required denominator: `27`
- required matched: `22`
- required missing: `5`
- required coverage: `81.5%`

The two Family Care CTA misses are both currently unmatched, so moving them out
of `REQUIRED` changes only denominator and missing count.

| Case | CTA policy | Required denominator | Required matched | Required missing | Required coverage |
| --- | --- | ---: | ---: | ---: | ---: |
| A | keep both `REQUIRED` | 27 | 22 | 5 | 81.5% |
| B | move both to `OPTIONAL` | 25 | 22 | 3 | 88.0% |
| C | move both to `STRUCTURAL` | 25 | 22 | 3 | 88.0% |

Interpretation:

- Case B and C produce the same coverage numbers
- but `STRUCTURAL` is the wrong semantic fit for these CTA nodes
- therefore the best policy reading is Case B, not Case C

Residual required misses after Case B would be:

- Family Care nav residuals such as `EventsButton`, `LocationButton`,
  `Mobile usageButton`

That means removing these CTAs from `REQUIRED` does not hide the remaining
Family Care problems. It only removes header/profile actions that are weak
required targets.

## 8. Phase 4 Impact

Phase 4 judgment for this CTA question:

- best fit: `B`

Meaning:

- these CTAs are better treated as `OPTIONAL`
- therefore they should not block Phase 4 readiness as required-miss items

Why not `A`:

- the evidence does not support keeping both CTAs as strong required targets
- `Add family member` in particular is too header-chrome-adjacent

Why not `C`:

- the current evidence is sufficient to make a policy recommendation
- there is uncertainty about exact TalkBack behavior in every path, but not so
  much uncertainty that further device evidence is required before making an
  analysis-only recommendation

Important boundary:

- This does not mean Family Care is fully Phase-4-ready overall
- it means these two CTA misses should not remain the primary readiness blocker

## 9. Recommendation

Recommended policy conclusion:

1. Reclassify `Add family member` from required CTA to `OPTIONAL`
2. Reclassify `View profile` from required CTA to `OPTIONAL`
3. Do not use `STRUCTURAL` for these nodes
4. Keep them in diagnostic reporting as visible actionable header/profile CTAs

Recommended next step:

- revisit the remaining Family Care required residuals after removing
  `Controls`, `Add family member`, and `View profile` from the strict required
  denominator

Bottom line:

- `Add family member` is best understood as an action-bar-adjacent secondary CTA
- `View profile` is best understood as a profile-header CTA
- both are real accessible actions, but neither is a strong required coverage
  target for Family Care traversal scoring
