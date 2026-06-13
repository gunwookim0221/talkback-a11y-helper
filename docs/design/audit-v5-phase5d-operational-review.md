# Audit V5 Phase 5D Operational Review

## 1. Purpose

Phase 5D reviews whether the current Audit V5 parser is operationally usable for repeated run-to-run monitoring.

The goal is not to expand parser behavior.

The goal is to decide:

- what the current reports already expose
- which metrics are operationally meaningful
- which changes should be treated as regression signals
- which plugins should stay on a watchlist
- whether the parser is operationally ready as a monitoring aid

This phase is document-only.

## 2. Current Output

The current parser emits two report formats:

### 2.1 JSON report

Current output file:

- `traversal_audit.json`

Top-level structure:

- `schema_version`
- `run_metadata`
- `scenario_summaries`
- `candidate_ledgers`
- `event_samples`
- `root_cause_summary`
- `metrics`

Current `metrics` fields:

- `discovered_count`
- `selected_count`
- `activation_attempt_count`
- `activation_success_count`
- `visited_count`
- `missed_count`
- `unknown_miss_count`
- `activation_success_rate`
- `visit_rate`
- `miss_attribution_rate`

Current `run_metadata` fields:

- `created_at`
- `loader_status`
- `run_id`
- `runner_behavior_changed`
- `scenario_ids`
- `shadow_policy_name`
- `source_output_dir`
- `tool_version`
- `v3_authoritative`

Current `candidate_ledgers` value:

- per-candidate state summary
- root cause
- root cause confidence
- selected / activation / realign / recovery / local-tab / visited flags
- evidence samples and event ids

Operational value:

- strongest artifact for machine comparison across runs
- strongest artifact for candidate-level investigations

### 2.2 Markdown report

Current output file:

- `traversal_audit.md`

Current summary content:

- schema id
- run id
- source directory
- runner behavior changed flag
- metrics summary
- root cause breakdown
- scenario summaries
- top missed candidates

Operational value:

- strongest artifact for human review
- fast triage surface for run summary and top unresolved misses

### 2.3 Current output judgment

The output is already sufficient for lightweight monitoring.

The JSON report is suitable for structured diffing.

The Markdown report is suitable for operator review.

## 3. Recommended Metrics

Recommended core monitoring metrics:

- `discovered_count`
- `visited_count`
- `missed_count`
- `unknown_miss_count`
- `miss_attribution_rate`

Recommended supporting metrics:

- `selected_count`
- `activation_attempt_count`
- `activation_success_count`
- `activation_success_rate`
- `visit_rate`

Recommended interpretation:

- `discovered_count` tracks discovered surface size and XML denominator drift.
- `visited_count` tracks how much of the discovered set was actually committed as traversal evidence.
- `missed_count` tracks total unresolved traversal surface after visit cleanup.
- `unknown_miss_count` tracks how much of the missed surface still lacks a useful explanation.
- `miss_attribution_rate` tracks parser explainability, not product quality.
- `selected_count` helps distinguish discovery drift from target selection drift.
- `activation_success_rate` helps separate selection problems from activation/focus problems.
- `visit_rate` is the best compact health metric when compared only within the same plugin family.

Operational recommendation:

- treat `unknown_miss_count` and `miss_attribution_rate` as first-class monitoring metrics
- treat `visit_rate` as the primary roll-up health signal
- treat `discovered_count` as a context metric, not as a success metric by itself

## 4. Regression Signals

The following changes are reasonable regression signals for repeated monitoring:

### 4.1 High-signal regressions

- `unknown_miss_count` increases for the same plugin and comparable scenario input
- `miss_attribution_rate` decreases materially for the same plugin
- `visit_rate` drops materially for the same plugin
- `missed_count` rises while `discovered_count` stays flat or near-flat
- previously explained root causes collapse back into `UNKNOWN`

### 4.2 Medium-signal regressions

- `activation_success_rate` drops while `selected_count` remains stable
- `selected_count` drops while `discovered_count` remains stable
- root-cause mix shifts sharply from discard/policy buckets into unexplained buckets

### 4.3 Non-regression cases

These changes should not be treated as automatic regressions:

- `discovered_count` rises because XML surface legitimately grew
- `missed_count` rises with a matching rise in `discovered_count`
- `unknown_miss_count` stays constant for already-known XML-only surfaces
- root-cause mix changes while total explainability remains stable

### 4.4 Practical monitoring rule

Use regression alerts when one of these happens:

- `unknown_miss_count` increases by 1 or more on a stable plugin
- `miss_attribution_rate` drops below the plugin's recent baseline
- `visit_rate` drops below the plugin's recent baseline

Do not use one global threshold across all plugins.

Plugin-local baselines are more defensible.

## 5. Watchlist Plugins

Recommended watchlist:

- `Family Care`
- `Motion Sensor`

### 5.1 Family Care

Reason:

- highest discovered surface among current monitored plugins
- known-risk plugin from Phase 4 and Phase 5C
- remaining `UNKNOWN` includes profile/header and active-strip semantics
- local-tab and bottom-strip behavior make it the best early warning surface for traversal explainability regressions

Current profile:

- `discovered=39`
- `visited=33`
- `missed=8`
- `unknown=3`
- `miss_attribution_rate=0.625`

### 5.2 Motion Sensor

Reason:

- smallest remaining device-side unresolved case
- still contains one XML-only instructional/status candidate
- good sentinel for "normal UNKNOWN" vs parser regression
- useful control sample for repeated device-plugin monitoring

Current profile:

- `discovered=13`
- `visited=10`
- `missed=3`
- `unknown=1`
- `miss_attribution_rate=0.6667`

### 5.3 Non-watchlist stable plugins

Current low-risk monitoring set:

- `Smoke Sensor`
- `Door Lock`
- `Home Care`

Reason:

- current `unknown_miss_count=0`
- stable attribution structure
- suitable as regression controls, but not the primary watchlist

## 6. Known Limitation Monitoring

The current parser can monitor known limitations over time even when it cannot fully resolve them.

Trackable limitation groups:

- Family Care profile/header surface candidates
- current active bottom-strip tab semantics
- XML-only candidates without traversal evidence
- ambiguous compound or composite labels

Recommended monitoring method:

- track repeated appearance of the same `stable_label` in `UNKNOWN`
- track whether a previously `UNKNOWN` candidate moves into discard, policy, bottom-strip, local-tab, activation, or visited states
- track whether `UNKNOWN` candidates stay confined to known surfaces rather than spreading into stable plugins

Operational meaning:

- shrinking repeated `UNKNOWN` sets suggests instrumentation quality is improving
- stable, bounded `UNKNOWN` sets are acceptable operational debt
- spreading `UNKNOWN` into previously stable plugins is a real monitoring signal

## 7. Operational Readiness

Operational readiness assessment:

```text
READY_WITH_LIMITATIONS
```

Rationale:

- JSON and Markdown outputs are already good enough for repeated reporting
- core metrics are stable and understandable
- stable plugins already show strong attribution quality
- remaining `UNKNOWN` is bounded and explainable
- parser explainability is good enough for monitoring, but not complete enough for authoritative gating

What blocks `READY`:

- Family Care still contains profile/header and current-tab unresolved candidates
- Motion still contains one XML-only instructional/status candidate
- no run-to-run baseline framework exists yet inside the tool itself

## 8. Recommended Usage

Recommended current uses:

- offline audit reporting
- run-to-run regression signal review
- candidate-level root cause investigation
- plugin-specific monitoring dashboards or spreadsheets built from JSON output
- watchlist review for Family Care and Motion Sensor

Recommended operator posture:

- compare plugins against their own historical baselines
- treat `UNKNOWN` movement as an explainability signal
- use Markdown for human triage and JSON for trend analysis

## 9. Non-Recommended Usage

Not recommended at the current maturity level:

- authoritative pass/fail gating for product verdicts
- direct replacement for V3 verdicts
- global threshold alerts applied uniformly across all plugins
- interpreting raw `discovered_count` as a quality score
- treating every `UNKNOWN` as a traversal bug

## 10. V5D Conclusion

The current V5 parser is operationally usable for repeated monitoring, but only in a bounded reporting role.

It is strong enough to support:

- structured reporting
- run-to-run metric comparison
- regression signal review
- targeted root-cause investigation

It is not yet strong enough to serve as an authoritative operational gate.

The correct operational stance is:

```text
READY_WITH_LIMITATIONS for monitoring
```

Phase 5D therefore concludes that the parser can enter controlled monitoring use now, with Family Care and Motion Sensor kept on watchlist review.

## 11. Code Change Status

No code changes were made for Phase 5D.

This phase adds only this design document.

## 12. Test Status

Pytest was not run.

This phase is document-only and uses existing parser outputs and Phase 5C validation results.

## 13. Git Status

Expected working tree delta after this phase:

- `docs/design/audit-v5-phase5d-operational-review.md`
