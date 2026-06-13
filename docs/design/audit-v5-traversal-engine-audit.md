# Audit V5 Traversal Engine Audit

## 1. North Star

Audit V5 is **not** a Coverage Audit expansion.

Audit V5 is a **Traversal Engine Audit**.

The primary question is no longer:

- "How much XML coverage did we get?"

The primary question becomes:

- "What did the traversal engine discover?"
- "What did it actually visit?"
- "What did it fail to visit?"
- "Why did that miss happen?"

Coverage remains useful, but only as one input into traversal validation.

## 2. Purpose

The purpose of Audit V5 is to validate traversal behavior end to end.

That means producing auditable answers for:

- discovered objects
- visited objects
- unvisited objects
- discarded objects
- activation failures
- focus drift
- local-tab progression failures
- bottom-strip progression failures
- recovery failures

The output of V5 should let the team reason about traversal quality mechanically, not infer it indirectly from top-level verdicts.

## 3. Core Questions

V5 should answer these questions per scenario and, where possible, per tab / strip / phase:

- How many objects were discovered?
- How many discovered objects were visited?
- How many discovered objects were missed?
- Which missed objects were intentionally deprioritized?
- Which missed objects were discarded by policy?
- Which missed objects failed because activation did not land on target?
- Which misses happened after focus drift?
- Which misses happened after state recovery failed?

Minimal core accounting:

- `discovered_count`
- `visited_count`
- `missed_count`

## 4. Audit Model

The V5 audit model should treat traversal as a pipeline:

```text
discovered
-> selected
-> activation attempted
-> focus landed or drifted
-> state committed or recovered
-> visited or missed
```

Coverage answers only the first and last edge.

Traversal audit must explain the middle edges too.

## 5. Root Cause Taxonomy

Initial root-cause classification for missed or degraded traversal outcomes:

- `ACTIVATION_FAIL`
- `FOCUS_DRIFT`
- `REALIGN_FAIL`
- `LOCAL_TAB_MISS`
- `BOTTOM_STRIP_MISS`
- `POLICY_DEPRIORITIZED`
- `CANDIDATE_DISCARDED`
- `STATE_RECOVERY_FAIL`
- `UNKNOWN`

Recommended operational meaning:

### `ACTIVATION_FAIL`

Selection target existed, activation was attempted, but focus did not land on the intended target.

### `FOCUS_DRIFT`

The engine selected one object, but focus context moved to a different object before the visit could be committed.

### `REALIGN_FAIL`

Representative selection required focus realign, but realign primitives failed or could not re-anchor focus to the intended object.

### `LOCAL_TAB_MISS`

Local-tab progression should have happened, but did not reach the target tab or did not commit active-tab state correctly.

### `BOTTOM_STRIP_MISS`

Bottom-strip candidates existed, but progression was deferred, recovered too late, or failed during strip activation.

### `POLICY_DEPRIORITIZED`

A discovered candidate was intentionally delayed because higher-priority content remained.

### `CANDIDATE_DISCARDED`

A discovered candidate was filtered out by candidate-selection or exhaustion logic before it became a visit target.

### `STATE_RECOVERY_FAIL`

The engine needed recovered state to continue traversal, but recovery did not produce a stable active target or progression path.

### `UNKNOWN`

Evidence is insufficient or signals conflict.

## 6. Metric Draft

Recommended first-pass metrics:

- `discovered_count`
- `visited_count`
- `missed_count`
- `activation_fail_count`
- `focus_drift_count`
- `realign_fail_count`
- `local_tab_miss_count`
- `bottom_strip_miss_count`
- `policy_deprioritized_count`
- `candidate_discarded_count`
- `state_recovery_fail_count`
- `unknown_miss_count`

Recommended supporting metrics:

- `selection_attempt_count`
- `activation_attempt_count`
- `activation_success_count`
- `focus_realign_attempt_count`
- `focus_realign_success_count`
- `local_tab_transition_attempt_count`
- `local_tab_transition_success_count`
- `state_recovery_attempt_count`
- `state_recovery_success_count`

Recommended derived rates:

- `visit_rate = visited / discovered`
- `activation_success_rate = activation_success / activation_attempt`
- `realign_success_rate = realign_success / realign_attempt`
- `local_tab_success_rate = local_tab_transition_success / local_tab_transition_attempt`

## 7. Reuse of Existing Assets

V5 should reuse existing signals before inventing new ones.

### 7.1 Lifecycle logs

Already useful for:

- local-tab candidate discovery
- local-tab progression and transition success
- bottom-strip context evaluation
- gate reasons such as `content_not_exhausted`
- deferred strip handling

Practical evidence already present:

- `bottom_strip_policy`
- `local_tab_gate`
- `local_tab_active_resolved`
- `local_tab_progression`
- `local_tab_select`
- `local_tab_force_navigation_resolved`

Reuse judgment:

- high reuse value
- likely enough for first-pass `LOCAL_TAB_MISS`, `BOTTOM_STRIP_MISS`, `POLICY_DEPRIORITIZED`

### 7.2 Local-tab state

Current implementation already tracks active, pending, visited, exhausted, and recovered strip/tab state inside `tb_runner/local_tab_logic.py` and `collection_flow.py`.

Observed reusable state dimensions:

- current active local tab
- pending progression target
- visited tab identities by signature
- recovery from bottom-strip candidates
- activation failure guard history

Reuse judgment:

- high reuse value
- especially strong for local-tab / bottom-strip miss attribution

### 7.3 Focus realign logs

Current focus realign implementation already emits:

- `focus_context_mismatch`
- `focus_realign`
- `focus_realign_success`
- `focus_realign_fail`
- `focus_force_realign`
- `focus_force_realign_success`
- `focus_force_realign_fail`

Reuse judgment:

- high reuse value
- enough for first-pass `FOCUS_DRIFT` and `REALIGN_FAIL`

### 7.4 Activation logs

Current local-tab activation path already emits:

- `local_tab_target_activate`
- `local_tab_target_activate_success`
- `local_tab_target_activate_no_match`
- `local_tab_target_activate_fail`

This is especially important because it already captures explicit failures such as:

- `focus_not_target_after_tap`
- `no_match_after_all_methods`

Reuse judgment:

- very high reuse value
- directly suitable for `ACTIVATION_FAIL`

### 7.5 XML dumps

Existing XML persistence should remain as the discovery-side substrate.

Current reuse:

- discovered-object inventory
- object metadata
- bounds/resource-id/label evidence
- local-tab/bottom-strip candidate reconstruction

Reuse judgment:

- high reuse value
- but XML should now be treated as discovery evidence, not the end goal

## 8. What V5 Can Already Infer

With current assets, V5 can likely infer these without major runner redesign:

- discovered object count from merged XML candidates
- visited object count from traversal rows / representative labels
- local-tab transition attempts and successes from existing logs
- focus realign attempts and failures from existing logs
- explicit local-tab activation failure cases
- bottom-strip deferral patterns
- some state recovery attempts from bottom-strip recovery logs

What V5 probably cannot do cleanly yet without additional audit logic:

- a single canonical object ledger joining discovery, selection, activation, and visit outcomes
- complete candidate-discard reasons for every non-selected object
- strong per-object causal attribution in all ambiguous cases

## 9. MVP Scope

V5 MVP should stay narrow.

### Included

- build a traversal-audit ledger from existing XML + log signals
- count discovered / visited / missed objects
- classify a first-pass root cause for missed objects
- emit per-scenario metrics and sampled evidence
- preserve explicit evidence for Family Care style bottom-strip failures

### MVP Output Shape

Recommended first output:

- JSON-first scenario audit summary
- flat CSV columns for core metrics
- short Markdown summary focused on misses and root causes

### MVP Success Condition

A run is successful if the team can answer, for any missed object:

- was it discovered?
- was it ever selected or considered?
- was activation attempted?
- did focus drift?
- did state recovery fail?
- or was it simply deprioritized / discarded by policy?

## 10. Non-Scope

These are explicitly out of scope for V5 initial work:

- Shadow Verdict expansion
- Coverage threshold tuning
- Matching policy changes
- Eligibility policy changes
- Taxonomy expansion

Important interpretation:

V5 should consume the current system as evidence.

V5 should not begin by reopening V4 policy semantics unless that becomes strictly necessary later.

## 11. Implementation Shape

Recommended architecture:

### 11.1 Discovery layer

Reuse merged XML candidates as the discovered-object set.

### 11.2 Event extraction layer

Parse traversal logs into normalized audit events such as:

- discovery context
- representative selection
- focus realign attempt / result
- local-tab gate / progression
- local-tab activation attempt / result
- state recovery attempt / result
- visit commit

### 11.3 Attribution layer

Join candidates and events into an object ledger.

### 11.4 Summary layer

Emit counts, rates, and sampled evidence per root cause.

## 12. Phase Roadmap

### Phase 5A

Traversal event inventory and schema definition.

Deliverables:

- audit event vocabulary
- normalized parser for current lifecycle / realign / activation signals
- scenario-level discovered / visited / missed counts

Goal:

- establish one auditable data model

### Phase 5B

First-pass miss attribution.

Deliverables:

- root-cause classifier for missed objects
- counts for activation fail / focus drift / realign fail / local-tab miss / bottom-strip miss
- sampled evidence per scenario

Goal:

- turn misses into explainable classes

### Phase 5C

State-recovery and candidate-discard accounting.

Deliverables:

- explicit state-recovery attempt / success metrics
- policy-deprioritized and candidate-discarded counts
- better separation between “not attempted yet” and “attempted but failed”

Goal:

- explain middle-pipeline failure points, not only terminal misses

### Phase 5D

Operational reporting and regression monitoring.

Deliverables:

- compact JSON / CSV / MD reporting
- watchlist views for Family Care style failures
- stable baseline regression signals

Goal:

- make traversal audit usable in repeated runs

## 13. Why This Is The Correct Next Step

The original project goal was not merely to compute coverage.

The real engineering problem is validating whether the traversal engine behaves correctly under:

- content-vs-strip priority
- focus realignment
- local-tab progression
- recovery after ambiguity
- activation on unstable surfaces

V4 built the evidence substrate.

V5 should validate the engine itself.

## 14. Phase 5 North Star Definition

North star:

- `Traversal Engine Audit answers not only what was missed, but why it was missed.`

If V5 is successful, the project will stop depending on top-level verdict interpretation as the main debugging entry point.

Instead, it will have a direct audit path from:

- discovery
- selection
- activation
- focus outcome
- state outcome
- visit / miss result

That is the right continuation after Audit V4 closure.
