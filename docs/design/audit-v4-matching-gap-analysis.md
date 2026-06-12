# Audit V4 Matching Gap Analysis

## 1. Background

This note quantifies how much Audit V4 required coverage would improve if
matching rules became less strict.

It is analysis-only.

It does not change:

- coverage engine behavior
- matching implementation
- KEEP / REVIEW / EXCLUDE classification
- coverage calculation
- verdict integration
- V3 verdict logic
- traversal or TalkBack collection

Phase 3.15 concluded:

- coverage-relevant missing: `60`
- required missing: `11`
- required-miss root causes:
  `MATCHING_GAP 7`
  `TRAVERSAL_GAP 4`
  `TAXONOMY_GAP 0`

This phase re-checks those `7` matching-gap items against actual XML and
traversal artifacts and simulates several paper-only matching relaxations.

## 2. Matching Inventory

### 2.1 Phase 3.15 Classified Inventory

The Phase 3.15 `MATCHING_GAP` inventory is:

| Plugin | XML candidate | Intended traversal counterpart | Notes |
| --- | --- | --- | --- |
| `device_motion_sensor_plugin` | `Motion detected` | `Motion sensor History Motion detected` | device status text is embedded in a compound label |
| `device_smoke_sensor_plugin` | `Clear` | `Smoke detector History Clear` | state value appears inside a compound label |
| `device_door_lock_plugin` | `Locked` | `Lock state Locked switch` | state value is embedded in a larger control label |
| `life_family_care_plugin` | `ActivityButton` | `Activity` | suffix variation |
| `life_family_care_plugin` | `EventsButton` | expected simplified form `Events` | not observed in current traversal artifact |
| `life_family_care_plugin` | `LocationButton` | expected simplified form `Location` | not observed in current traversal artifact |
| `life_family_care_plugin` | `Mobile usageButton` | expected simplified form `Mobile usage` | not observed in current traversal artifact |

### 2.2 Evidence Strength

The inventory above contains two different confidence levels.

Directly evidenced in current artifacts:

- `Motion detected`
- `Clear`
- `Locked`
- `ActivityButton`

Classified as matching-shaped in Phase 3.15 but not directly recoverable from
the current traversal labels:

- `EventsButton`
- `LocationButton`
- `Mobile usageButton`

Why those three are weaker:

- Current Family Care traversal labels include `Activity`, but do not include
  `Events`, `Location`, or `Mobile usage`
- That means suffix normalization alone cannot recover them in this artifact set
- They remain important diagnostic suspects, but they behave like optimistic
  matching candidates rather than proven recoverable misses

## 3. Gap Categories

### 3.1 Category Definitions

| Category | Meaning |
| --- | --- |
| `CONTAINED_IN_COMPOUND_LABEL` | Candidate text appears as one part of a larger traversal label. |
| `BUTTON_SUFFIX` | XML has `...Button` while traversal exposes the underlying title without the suffix. |
| `STATE_VALUE_EMBEDDED` | The state word is embedded in a larger status/control label. |
| `PREFIX_SUFFIX_VARIATION` | Same semantic label with non-button prefix/suffix differences. |
| `CASE_ONLY` | Only case differs. |
| `WHITESPACE_ONLY` | Only whitespace differs. |
| `OTHER` | Matching-shaped, but not explained by the above patterns. |

### 3.2 Classified Distribution

Distribution across the full Phase 3.15 matching inventory:

| Category | Count |
| --- | ---: |
| `BUTTON_SUFFIX` | 4 |
| `CONTAINED_IN_COMPOUND_LABEL` | 2 |
| `STATE_VALUE_EMBEDDED` | 1 |
| `PREFIX_SUFFIX_VARIATION` | 0 |
| `CASE_ONLY` | 0 |
| `WHITESPACE_ONLY` | 0 |
| `OTHER` | 0 |

Distribution across directly evidenced recoverable items only:

| Category | Count |
| --- | ---: |
| `CONTAINED_IN_COMPOUND_LABEL` | 2 |
| `BUTTON_SUFFIX` | 1 |
| `STATE_VALUE_EMBEDDED` | 1 |

Interpretation:

- Phase 3.15 matching inventory is real, but not every classified item is
  recoverable in the current artifact set
- The strongest observed patterns are not suffix-only; they are compound-label
  embedding patterns

## 4. Simulation Scenarios

All simulations are paper-only.

Simulation A:

- Current behavior: `normalized_exact`

Simulation B:

- Simulation A
- plus `Button` suffix removal

Simulation C:

- Simulation B
- plus `contained-in-compound` allowance

Simulation D:

- Simulation C
- plus `state value embedded` allowance

Important scope note:

- Coverage impact below is computed on the `Required` inventory only
- Total required denominator across the seven analyzed plugins is `30`

## 5. Coverage Impact

### 5.1 Required Coverage Summary

| Simulation | Required matched | Required missing | Required coverage |
| --- | ---: | ---: | ---: |
| A | 19 | 11 | 63.3% |
| B | 20 | 10 | 66.7% |
| C | 22 | 8 | 73.3% |
| D | 23 | 7 | 76.7% |

Required miss reduction from baseline:

- B vs A: `-1`
- C vs A: `-3`
- D vs A: `-4`

### 5.2 Per-Plugin Required Coverage

| Plugin | A | B | C | D |
| --- | ---: | ---: | ---: | ---: |
| `device_motion_sensor_plugin` | 5 / 6 | 5 / 6 | 6 / 6 | 6 / 6 |
| `device_smoke_sensor_plugin` | 4 / 6 | 4 / 6 | 5 / 6 | 5 / 6 |
| `device_door_lock_plugin` | 3 / 5 | 3 / 5 | 3 / 5 | 4 / 5 |
| `life_family_care_plugin` | 1 / 7 | 2 / 7 | 2 / 7 | 2 / 7 |
| `life_home_care_plugin` | 2 / 2 | 2 / 2 | 2 / 2 | 2 / 2 |
| `life_energy_plugin` | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |
| `life_air_care_plugin` | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |

### 5.3 Recovered Labels By Scenario

Simulation B recovers:

- `ActivityButton` -> `Activity`

Simulation C additionally recovers:

- `Motion detected` -> `Motion sensor History Motion detected`
- `Clear` -> `Smoke detector History Clear`

Simulation D additionally recovers:

- `Locked` -> `Lock state Locked switch`

Not recovered even in Simulation D:

- `device_smoke_sensor_plugin`: `Controls`
- `device_door_lock_plugin`: `Controls`
- `life_family_care_plugin`: `Add family member`, `View profile`
- `life_family_care_plugin`: `EventsButton`, `LocationButton`, `Mobile usageButton`

### 5.4 Why `11 - 7 = 4` Does Not Hold In Actual Simulation

The naive subtraction from Phase 3.15 is:

```text
Required miss 11
- Matching gap 7
= 4
```

Actual Simulation D result is:

```text
Required miss 7
```

Reason:

- Only `4` of the `7` matching-gap items are directly recoverable in the current
  artifacts
- The remaining `3` classified `BUTTON_SUFFIX` items do not have direct
  traversal counterparts in the current Family Care run
- That means the Phase 3.15 `MATCHING_GAP 7` value is a valid diagnostic
  classification count, but an optimistic upper bound for recoverable misses

## 6. False Positive Risk

### 6.1 Risk Table

| Simulation | Main added behavior | Risk | Reason |
| --- | --- | --- | --- |
| A | `normalized_exact` | `LOW` | current strict baseline |
| B | button suffix removal | `LOW` | still equality-based after deterministic suffix stripping |
| C | contained-in-compound | `HIGH` | substring allowance can match unrelated larger labels |
| D | state value embedded | `MEDIUM` | safer than generic containment if constrained to known state tokens, but still wider than exact |

### 6.2 Risk Notes

Simulation B:

- `ActivityButton` -> `Activity` is narrow
- False positive risk is low because equality still applies after a specific
  normalization step

Simulation C:

- `Activity` could incorrectly match `Recent Activity`
- short labels such as `Clear` can appear inside unrelated longer strings
- generic containment is therefore high risk without strong structural guards

Simulation D:

- If limited to state-value embedding, `Locked` inside
  `Lock state Locked switch` is useful
- But if implemented too loosely, state words could be granted credit inside
  semantically different labels
- Example risk to avoid: treating `Lock` as satisfied by `Locked`

Practical conclusion:

- `BUTTON_SUFFIX` is the safest relaxation
- compound containment has the highest false-positive risk
- state-embedded matching is only acceptable if explicitly narrower than generic
  containment

## 7. Phase 4 Impact

### 7.1 Blocker Re-evaluation

Result: `A` is not yet achieved.

Reasoning:

- Matching relaxation helps, but it does not eliminate most required misses
- Required miss falls from `11` to `7`, not to `4`
- Family Care remains weak even after all simulated matching relaxations because
  three suspected suffix cases do not have observed traversal counterparts
- Remaining misses after Simulation D are:
  `TRAVERSAL_GAP` plus unrecovered Family Care misses that cannot be proven as
  pure matching issues from the current artifact set

### 7.2 Updated Reading

- Matching is still a real Phase 4 blocker
- But the effect size is smaller than the raw `MATCHING_GAP 7` count suggests
- The current artifact set supports this statement:
  matching-policy relaxation improves required coverage meaningfully
  but does not by itself make Family Care Phase-4-ready

## 8. Recommendation

Recommended next step: `Phase 3.16 Traversal Gap Investigation`, immediately
after documenting the matching findings.

Why:

- This analysis confirms matching matters
- But it also shows matching alone recovers only `4` required misses in the
  current artifacts
- The unrecovered required misses are now concentrated in:
  `Controls` local-tab misses
  `Add family member`
  `View profile`
  and three Family Care nav candidates with no observed simplified traversal
  counterparts

Practical priority:

1. Keep `BUTTON_SUFFIX` as the lowest-risk future matching candidate
2. Treat generic compound containment as high-risk and not Phase-4-safe without
   additional guardrails
3. Re-check Family Care and device local-tab misses from a traversal perspective
   before assuming matching alone can unblock verdict integration
