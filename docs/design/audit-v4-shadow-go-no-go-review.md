# Audit V4 Shadow Go/No-Go Review

## 1. Background

Audit V4 still remains diagnostic-only.

Current milestone state:

- Phase 4B added `shadow_verdict_v4` reporting without changing the operational
  V3 verdict
- Phase 4C-3 corrected shadow input interpretation
- V3 remains authoritative
- Shadow remains reporting-only

Relevant implemented and analyzed state:

- Device plugins now align cleanly with the Balanced shadow policy
- `life_home_care_plugin` now shadows as a clean `PASS`
- `life_energy_plugin` and `life_air_care_plugin` remain explainable
  provisional-only `REVIEW`
- `life_family_care_plugin` remains a known-risk `REVIEW` case under the
  evidence-corrected baseline
- Food is still not a stable readiness anchor

This phase answers one operational question only:

- is the current Shadow Verdict safe enough to run continuously alongside V3

## 2. Current Shadow State

Current post-4C-3 working interpretation:

| Plugin | V3 | Shadow | Current reading |
| --- | --- | --- | --- |
| `device_motion_sensor_plugin` | `PASS` | `PASS` | stable agreement |
| `device_smoke_sensor_plugin` | `PASS` | `PASS` | stable agreement |
| `device_door_lock_plugin` | `PASS` | `PASS` | stable agreement |
| `life_home_care_plugin` | `REVIEW` | `PASS` | V4 required surface is clean; V3 remains more conservative |
| `life_family_care_plugin` | `REVIEW` on normal evidence baseline | `REVIEW` | known residual bottom-strip risk |
| `life_energy_plugin` | `REVIEW` | `REVIEW` | provisional-only plugin |
| `life_air_care_plugin` | `REVIEW` | `REVIEW` | provisional-only plugin |
| `life_food_plugin` | mixed historical basis | not used as readiness anchor | needs more evidence |

Operational implications:

- the Device set already behaves like a stable shadow baseline
- Home Care is the strongest proof that V4 can recognize a clean required
  surface that V3 still leaves in `REVIEW`
- Family Care remains intentionally conservative because the residual miss is
  real and localized
- Energy and Air Care are no longer false-fail cases; they are policy-deferred
  provisional-only `REVIEW`

## 3. Plugin Classification

Required classification for Phase 4D:

| Plugin | Classification | Basis |
| --- | --- | --- |
| `device_motion_sensor_plugin` | `SHADOW_PASS_STABLE` | `V3 PASS / Shadow PASS`, no known residual risk |
| `device_smoke_sensor_plugin` | `SHADOW_PASS_STABLE` | `V3 PASS / Shadow PASS`, no known residual risk |
| `device_door_lock_plugin` | `SHADOW_PASS_STABLE` | `V3 PASS / Shadow PASS`, no known residual risk |
| `life_home_care_plugin` | `SHADOW_PASS_STABLE` | clean required surface, `required_missing_count = 0`, no provisional burden |
| `life_family_care_plugin` | `SHADOW_REVIEW_KNOWN_RISK` | evidence-corrected baseline keeps `EventsButton` and `LocationButton` as explicit residual risks |
| `life_energy_plugin` | `SHADOW_REVIEW_PROVISIONAL_ONLY` | `required_denominator_count = 0`, provisional-heavy output, explainable advisory review |
| `life_air_care_plugin` | `SHADOW_REVIEW_PROVISIONAL_ONLY` | `required_denominator_count = 0`, provisional-heavy output, explainable advisory review |
| `life_food_plugin` | `NEEDS_MORE_EVIDENCE` | Food entry/onboarding remains secondary and should not be used as a readiness anchor |

Special note:

- regenerated Family Care artifacts can still appear as `ENVIRONMENT_ERROR`
  variants, but that is an artifact-state classification, not the normal plugin
  baseline classification

## 4. Go / No-Go Assessment

Evaluation dimensions:

| Dimension | Assessment | Reading |
| --- | --- | --- |
| Safety | High | V3 remains authoritative; Shadow does not change production verdicts |
| Explainability | High enough | Family Care known risks and Energy/Air provisional-only status are now explicit |
| Coexistence with V3 | Strong | V3 and Shadow can run in parallel without verdict collision |
| False-positive risk | Low to Medium | Shadow `PASS` is currently limited to stable required surfaces |
| Miss / under-modeling risk | Medium | Energy/Air still depend on provisional classification, and Family Care still carries a localized traversal issue |
| Operational burden | Moderate | review interpretation is needed for Family Care, Energy, Air Care, and Food watchlist handling |

Decision:

- `GO_LIMITED_SHADOW_OPERATION`

Why this is not full `GO_SHADOW_OPERATION`:

- Family Care still has a real known-risk miss
- Energy and Air Care are still provisional-only rather than fully modeled
- Food still lacks stable post-entry evidence quality

Why this is not `NO_GO`:

- none of the remaining issues require V3 behavior changes
- shadow outputs are now explainable enough to monitor safely
- the unstable cases already degrade to `REVIEW`, not silent `PASS`

## 5. Known Risks

### 5.1 Family Care

Known residual risk:

- `EventsButton`
- `LocationButton`

Interpretation:

- this is a localized bottom-strip traversal/state issue
- it is already well understood and explicitly visible in shadow reporting
- it should remain a watchlist item during shadow operation

### 5.2 Energy / Air Care

Known residual risk:

- provisional-only coverage state
- no stable required denominator yet
- runtime subtype tagging is still not rich enough to graduate these plugins
  into fully modeled stable coverage surfaces

Interpretation:

- these are not hard traversal failures
- these are not hidden false `PASS` cases
- they are conservative `REVIEW` outputs by policy

### 5.3 Food

Known residual risk:

- Food evidence remains historically entry/onboarding-sensitive
- Food is still treated as secondary in taxonomy and readiness discussions

Interpretation:

- Food should remain outside the main Phase 4D readiness signal
- it belongs on a separate evidence follow-up watchlist

### 5.4 Artifact Variants

Known residual risk:

- Family Care can still produce regenerated `ENVIRONMENT_ERROR` artifacts

Interpretation:

- this does not invalidate shadow policy behavior
- it does reduce comparison convenience and should be tracked operationally

## 6. Operation Recommendation

Recommended operating mode:

1. Start Phase 4D as shadow-only reporting with V3 unchanged.
2. Treat Device plugins and Home Care as the stable reference set.
3. Treat Family Care as `SHADOW_REVIEW_KNOWN_RISK`.
4. Treat Energy and Air Care as `SHADOW_REVIEW_PROVISIONAL_ONLY`.
5. Keep Food off the primary readiness scorecard until evidence quality
   improves.

Recommended interpretation rule during shadow operation:

- `PASS` means the stable required surface is covered
- `REVIEW` can mean either known residual risk or provisional-only uncertainty
- `ENVIRONMENT_ERROR` remains an artifact/runtime short-circuit, not a policy
  statement about coverage quality

This is operationally safe because Shadow is not replacing V3 and the remaining
non-pass cases are explainable.

## 7. Next Work Items

Recommended priority after Phase 4D start:

1. `Phase 4E - Shadow Operation Monitoring`
2. Family Care bottom-strip remediation design and implementation
3. Runtime subtype tagging enhancement for provisional-heavy Life structures
4. Food evidence follow-up with stable post-entry artifacts

Priority rationale:

- monitoring can begin now because current outputs are safe enough to observe
- Family Care is the clearest non-provisional functional miss
- Energy and Air Care need better subtype resolution, but not before shadow
  monitoring starts
- Food remains an evidence-quality follow-up item, not a Phase 4D blocker

Bottom line:

- current state is good enough for limited shadow operation
- current state is not yet good enough to treat all Life plugins as equally
  stable
- the right decision is conservative rollout with explicit watchlists, not
  delay for wholesale redesign
