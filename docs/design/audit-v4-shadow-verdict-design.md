# Audit V4 Shadow Verdict Design

## 1. Background

Audit V4 can now calculate XML-vs-traversal coverage and has supporting
analysis for taxonomy, eligibility, matching gaps, traversal gaps, and Family
Care residual misses.

Current state:

- V3 remains the production verdict.
- V4 remains diagnostic only.
- Coverage, taxonomy, and eligibility are available.
- Matching and traversal failure causes are now better understood.
- Evidence-corrected required coverage across the current seven-plugin analysis
  set is `25 / 23 / 2 = 92.0%`.

Known residual risks:

- Family Care `EventsButton`: high-confidence traversal-side miss
- Family Care `LocationButton`: medium-confidence traversal-side miss
- Energy / Air Care provisional subtype uncertainty

The Phase 4A goal is not implementation. It is to define a safe shadow-verdict
policy shape before any production integration work starts.

## 2. Current V3 Verdict Structure

Current V3 verdicts are:

- `PASS`
- `REVIEW`
- `FAIL`
- `ENVIRONMENT_ERROR`

Practical V3 reading from current audit flow:

- `PASS`: target entered successfully, traversal completed, and expected
  coverage/content checks did not raise review signals.
- `REVIEW`: traversal completed but manual inspection is needed because of
  missed tabs, missing expected content, suspicious coverage, value exclusion,
  or repeat-no-progress style warnings.
- `FAIL`: hard scenario failure such as wrong target handling or unrecovered
  plugin failure.
- `ENVIRONMENT_ERROR`: preflight, crash, dump, helper, ADB, or contamination
  instability.

Important constraint:

- Phase 4 must not replace this structure yet.
- Shadow verdict must coexist with V3, not override it.

## 3. Why Shadow Verdict First

Shadow verdict is needed because V4 is now directionally useful, but not yet
proven safe enough for production gating.

Why not switch directly:

- Family Care still has one strong unresolved required traversal miss
  (`EventsButton`) and one weaker residual miss (`LocationButton`).
- Energy and Air Care still include provisional subtype uncertainty outside the
  stable required core.
- Current V4 quality comes from multiple analysis passes, not yet from one
  battle-tested reporting path.
- We need side-by-side comparison between V3 and V4 before changing production
  pass/review behavior.

Why shadow operation is the right next step:

- It measures how often V4 agrees or disagrees with V3.
- It exposes threshold mistakes without affecting production verdicts.
- It lets Family Care and provisional-subtype edge cases be monitored in real
  runs instead of only in paper analysis.

## 4. Shadow Verdict Inputs

The shadow policy should use only values that are already derivable from the
current V4 artifacts and analysis rules.

### 4.1 Minimum Gating Inputs

| Input | Meaning | Source |
| --- | --- | --- |
| `environment_error` | whether the run is unstable and should short-circuit | current audit verdict / run diagnostics |
| `v3_verdict` | existing production verdict for comparison only | current audit report |
| `required_denominator_count` | required coverage denominator after eligibility mapping | merged candidates + current eligibility policy |
| `required_matched_count` | required candidates matched by traversal | merged candidates + traversal labels |
| `required_missing_count` | unmatched required candidates | derived from required denominator and matches |
| `required_coverage` | `required_matched_count / required_denominator_count` | derived |

### 4.2 Advisory Inputs

| Input | Meaning | Current status |
| --- | --- | --- |
| `optional_denominator_count` | optional coverage denominator | calculable from eligibility map |
| `optional_matched_count` | matched optional candidates | calculable |
| `optional_coverage` | optional match ratio | calculable |
| `provisional_candidate_count` | unresolved provisional subtype load | calculable from subtype tagging |
| `matching_gap_count` | required misses classified as matching-shape gaps | calculable from current Phase 3.15 / 3.16 classifier logic |
| `traversal_gap_count` | required misses classified as traversal gaps | calculable from current Phase 3.15 / 3.17 classifier logic |
| `taxonomy_gap_count` | required misses classified as taxonomy gaps | calculable from current Phase 3.15 classifier logic |
| `known_risk_labels` | sample labels such as `EventsButton` | calculable from missing inventory |

Design note:

- The first shadow-verdict pass should gate mainly on required coverage and
  environment stability.
- Matching / traversal / taxonomy counts are better treated as explanation
  fields, not first-pass hard gates, except where a known high-confidence
  traversal blocker is already established.

## 5. Candidate Policies

### 5.1 Conservative

Conditions:

- `ENVIRONMENT_ERROR`
  - if `environment_error = true`
- `PASS`
  - if `required_coverage = 100%`
  - and `required_missing_count = 0`
  - and `traversal_gap_count = 0`
  - and `taxonomy_gap_count = 0`
  - and `provisional_candidate_count = 0`
- `FAIL`
  - if `v3_verdict = FAIL`
  - or `required_coverage < 50%`
  - or `required_missing_count >= 4`
- `REVIEW`
  - otherwise

Pros:

- safest rollout posture
- keeps provisional-heavy plugins under manual watch
- minimizes false-pass risk

Cons:

- too strict for Energy and Air Care at the current maturity level
- would keep shadow review volume artificially high

### 5.2 Balanced

Conditions:

- `ENVIRONMENT_ERROR`
  - if `environment_error = true`
- `PASS`
  - if `required_coverage >= 90%`
  - and `required_missing_count <= 1`
  - and `traversal_gap_count = 0`
  - and `taxonomy_gap_count = 0`
- `FAIL`
  - if `v3_verdict = FAIL`
  - or `required_coverage < 50%`
  - or `required_missing_count >= 4`
- `REVIEW`
  - otherwise

Pros:

- keeps the policy centered on the required denominator
- allows Energy and Air Care to pass when their stable required surface is
  clean
- keeps Family Care in review because the remaining miss is real and localized

Cons:

- still depends on accurate traversal-gap classification
- may be slightly permissive for provisional-heavy dashboards if required
  coverage alone is over-trusted

### 5.3 Aggressive

Conditions:

- `ENVIRONMENT_ERROR`
  - if `environment_error = true`
- `PASS`
  - if `required_coverage >= 85%`
  - and `required_missing_count <= 2`
  - and `taxonomy_gap_count = 0`
- `FAIL`
  - if `v3_verdict = FAIL`
  - or `required_coverage < 40%`
  - or `required_missing_count >= 5`
- `REVIEW`
  - otherwise

Pros:

- highest alignment with the current evidence-corrected global coverage level
- very low review volume

Cons:

- too easy to pass Family Care while `EventsButton` is still unresolved
- weak as an early-warning policy during the shadow period

## 6. Simulation Against Current Evidence

Evidence-corrected per-plugin required baseline for shadow planning:

| Plugin | Required matched | Required denominator | Required coverage | Key note |
| --- | ---: | ---: | ---: | --- |
| Motion Sensor | 5 | 5 | 100.0% | `Controls` treated as structural |
| Smoke Sensor | 5 | 5 | 100.0% | `Controls` treated as structural |
| Door Lock | 4 | 4 | 100.0% | `Controls` treated as structural |
| Family Care | 3 | 5 | 60.0% | residual `EventsButton`, `LocationButton` |
| Home Care | 2 | 2 | 100.0% | clean required surface |
| Energy | 3 | 3 | 100.0% | provisional dashboard layer remains |
| Air Care | 1 | 1 | 100.0% | provisional dashboard layer remains |

Expected shadow verdict by policy:

| Plugin | Conservative | Balanced | Aggressive |
| --- | --- | --- | --- |
| Motion Sensor | `PASS` | `PASS` | `PASS` |
| Smoke Sensor | `PASS` | `PASS` | `PASS` |
| Door Lock | `PASS` | `PASS` | `PASS` |
| Family Care | `REVIEW` | `REVIEW` | `PASS` |
| Home Care | `PASS` | `PASS` | `PASS` |
| Energy | `REVIEW` | `PASS` | `PASS` |
| Air Care | `REVIEW` | `PASS` | `PASS` |

Interpretation:

- All three policies agree that Motion, Smoke, Door Lock, and Home Care are
  already shadow-pass candidates.
- The main discriminator is how to treat Family Care and provisional-heavy
  Life dashboards.
- Conservative is too sticky on provisional uncertainty.
- Aggressive over-passes Family Care before the known traversal risk is fixed or
  explicitly accepted.

## 7. Recommended Policy

Recommended policy: `Balanced`

Why this is the best fit now:

- It preserves a real watchlist signal for Family Care.
- It does not let one localized Family Care problem block all other plugins.
- It treats Energy and Air Care as operationally acceptable when the stable
  required layer is covered.
- It keeps the first shadow rollout simple: required coverage drives the verdict
  and root-cause counts mainly explain it.

Recommended practical reading:

- `PASS` means the stable required surface is covered well enough for shadow
  confidence.
- `REVIEW` means there is still a meaningful residual coverage question, even if
  the overall program is close to ready.
- `FAIL` should remain reserved for clearly broken runs, not ordinary coverage
  drift.

## 8. Phase 4B Implementation Scope

Recommended storage plan:

### 8.1 `audit_report.json`

Add one new object per scenario:

```json
{
  "shadow_verdict_v4": {
    "policy_name": "balanced_v1",
    "verdict": "PASS",
    "required_denominator_count": 5,
    "required_matched_count": 5,
    "required_missing_count": 0,
    "required_coverage": 100.0,
    "optional_coverage": 25.0,
    "provisional_candidate_count": 0,
    "matching_gap_count": 0,
    "traversal_gap_count": 0,
    "taxonomy_gap_count": 0,
    "known_risk_labels": [],
    "reason": "required_coverage>=90 and no required residual blockers"
  }
}
```

This should be the authoritative shadow output.

### 8.2 `audit_report.csv`

Add flattened columns for filtering and sorting:

- `shadow_policy_name`
- `shadow_verdict_v4`
- `shadow_required_coverage`
- `shadow_required_missing_count`
- `shadow_traversal_gap_count`
- `shadow_taxonomy_gap_count`
- `shadow_known_risks`

### 8.3 `audit_report.md`

Add two new sections:

- `Shadow Verdict Summary`
- `V3 vs V4 Shadow Comparison`

This is the lowest-friction way to review disagreement cases during Phase 4B.

### 8.4 XLSX Recommendation

Do not make XLSX a Phase 4B requirement.

Reason:

- shadow verdict is a scenario-level post-analysis result
- the authoritative scenario report already lives better in JSON / CSV / MD
- touching traversal XLSX artifacts increases implementation surface without
  improving first-pass decision quality

If spreadsheet exposure is later needed, add a summary workbook or summary sheet
after JSON / CSV / MD are stable.

Implementation difficulty:

- `MEDIUM`

Reason:

- no runner change is required
- no V3 verdict replacement is required
- but eligibility-aware required/optional aggregation and shadow-summary
  serialization still need careful schema work

## 9. Go / No-Go

Judgment: `A. Shadow Verdict implementation possible`

Why this is a `Go`:

- the required denominator is now stable enough for first-pass shadow use
- evidence-corrected global required coverage is already about `92%`
- the residual risk is narrow and named, not broad and unexplained

Why this is not a full production-verdict `Go`:

- Family Care `EventsButton` remains a real unresolved traversal-side miss
- provisional subtype interpretation in Energy / Air Care should keep being
  watched during shadow collection

Bottom line:

- Phase 4B should implement `Balanced` shadow verdict in reporting only
- V3 remains authoritative
- Family Care bottom-strip issues remain explicit known-risk notes during the
  shadow period
