# Audit V4 Provisional-Only Policy

## 1. Background

Phase 4C-3 corrected shadow input aggregation without changing the Balanced
thresholds:

- `UNKNOWN` candidates now aggregate into `PROVISIONAL`
- `ready_empty_denominator` no longer blocks `PASS` when shadow-required inputs
  are valid
- provisional-heavy plugins now retain advisory risk labels in
  `known_risk_labels` and `reason`

That resolved the earlier input overcount problem, but it exposed a new policy
question:

- how should a plugin be interpreted when
  `required_denominator_count = 0`
  and
  `provisional_candidate_count > 0`

This note answers that question for Phase 4D planning only. It does not change
runtime behavior.

## 2. Current Energy/Air Care State

Current post-4C-3 dry-run state:

| Plugin | V3 | Shadow | XML status | Coverage status | Required denominator | Required missing | Provisional count | Known risk sample |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| `life_energy_plugin` | `REVIEW` | `REVIEW` | `xml_present_parsed` | `ready` | 0 | 0 | 28 | `10th monitoring`, `5th monitoring`, `AI Energy Mode Save energy in your home with AI Energy Mode.`, `AI Energy Mode activities, Heading`, `Activity New notification` |
| `life_air_care_plugin` | `REVIEW` | `REVIEW` | `xml_present_parsed` | `ready_empty_denominator` | 0 | 0 | 11 | `Air Care`, `Dismiss`, `Find out more about air control`, `Information`, `Is your family sensitive to air quality?...` |

Interpretation:

- both plugins now avoid false required undercount
- neither plugin currently has a stable required denominator
- both plugins remain explainable because provisional uncertainty is now carried
  forward as explicit shadow metadata

This is materially different from the earlier false-fail Energy state. The
question is no longer "is the denominator wrong?" but "what should shadow
policy do when only provisional content exists?"

## 3. Option A/B/C

### Option A

Keep provisional-only plugins as `REVIEW`.

Reading:

- no stable required denominator means no stable shadow pass decision
- provisional-only state remains a manual-review/watchlist case

### Option B

Introduce a `PASS_WITH_RISK`-like outcome.

Reading:

- treat stable artifacts with provisional-only content as pass-adjacent
- preserve warning semantics without using plain `REVIEW`

### Option C

Delay policy judgment until runtime subtype tagging is extended for:

- `LIFE_TAB`
- `INFO_BUTTON`
- `METRIC_CARD`
- `TIP_CARD`
- `PROGRAM_CARD`
- `EMPTY_OR_NO_DATA_STATUS`

Reading:

- do not make a final policy choice now
- first reduce the provisional-only population by improving runtime subtype
  diagnostics

## 4. Tradeoff Analysis

| Option | Safety | Implementation cost | Operational interpretation | Phase 4D impact |
| --- | --- | --- | --- | --- |
| `A. REVIEW 유지` | High | None | Simple | Allows Phase 4D immediately |
| `B. PASS_WITH_RISK` | Medium | Medium to High | More complex | Delays Phase 4D until new semantics land |
| `C. Subtype tagging 후 판단` | High long-term | High | Clean once finished | Delays Phase 4D on Energy/Air |

### Option A Analysis

Pros:

- aligns with the original shadow-verdict philosophy that `PASS` should mean
  stable required coverage is actually known
- requires no new verdict category
- avoids false confidence from provisional-heavy dashboards
- fits Diagnostic Only operation well

Cons:

- Energy and Air Care remain `REVIEW`
- shadow pass rate stays lower than it would under a more permissive reading

### Option B Analysis

Pros:

- better distinguishes "stable miss" from "provisional uncertainty"
- may reduce unnecessary `REVIEW` volume during shadow monitoring

Cons:

- `PASS_WITH_RISK` is effectively a new verdict meaning
- JSON/CSV/MD consumers would need interpretation changes
- it weakens direct comparability against V3's existing four-state vocabulary
- it is outside the scope of the current Balanced design

### Option C Analysis

Pros:

- most accurate long-term answer
- would let Energy and Air Care move out of provisional-only status if stable
  subtype evidence is available
- better matches the original simulation intent that Energy and Air Care should
  eventually become shadow-passable

Cons:

- this is implementation work, not a policy-only decision
- it delays the shadow rollout decision even though the current output is now
  explainable
- it is not required to keep Phase 4 shadow monitoring safe

## 5. Recommended Policy

Recommended policy: `A. Provisional-only는 REVIEW 유지`

Reasoning:

- `PASS` in the current Balanced model is supposed to mean the stable required
  surface is covered, not merely that the artifact looks healthy
- when `required_denominator_count = 0`, there is no stable required surface to
  certify yet
- provisional uncertainty is now visible in `known_risk_labels` and `reason`,
  so a `REVIEW` result is no longer opaque
- this keeps Phase 4D conservative without introducing new verdict semantics

This recommendation is specifically for the shadow period. It should be read as:

- `REVIEW` because stable denominator is absent
- not `REVIEW` because traversal is broken
- not `REVIEW` because the artifact is unusable

Operationally, Energy and Air Care should be treated as:

- valid shadow artifacts
- policy-deferred plugins
- not blockers for Device/Home Care shadow readiness

## 6. Phase 4D Readiness

Judgment: `READY_FOR_4D`

Why:

- Device plugins already behave as intended
- Home Care now behaves as intended
- Family Care remains a known localized watchlist case
- Energy and Air Care are now explainable provisional-only `REVIEW` cases
- no further implementation is required to keep shadow operation safe

What this does not mean:

- it does not mean Energy and Air Care are fully modeled
- it does not mean provisional-heavy Life dashboards are ready for production
  verdict use
- it only means shadow monitoring can proceed with a conservative reading

## 7. Next Step

Recommended next step after Phase 4D start:

1. Use `Option A` operationally during the first shadow period.
2. Track provisional-only frequency for Energy and Air Care over multiple runs.
3. Plan `Option C` as the next improvement step:
   runtime subtype tagging for provisional Life structures.
4. Revisit whether Energy and Air Care can graduate from provisional-only once
   stable subtype evidence exists.

This keeps the immediate shadow rollout simple while preserving a clear path to
reduce review volume later.
