# Audit V7 Focusable Coverage Design

## 1. Problem Statement

Audit V6 can explain row quality, semantic value coverage, and shadow verdicts,
but it still assumes that the collected result rows are a sufficiently complete
view of the TalkBack traversal.

The Motion Sensor plugin exposed a new class of gap:

- TalkBack appears to read focusable elements on screen.
- Some of those elements are not present as persisted result rows.
- Therefore row-level quality can look acceptable while actual TalkBack
  focusable coverage is incomplete.

Observed Motion Sensor examples include:

- `Motion detected`
- `100%`
- `>`
- `Graph button`, collapsed button

Comparable misses can happen for:

- battery values such as `100%`
- chevron or navigation affordances such as `>`
- collapsed / expanded buttons
- `More options`
- state values
- other focusable nodes that TalkBack can land on but reporting does not retain

The core V7 question is:

- "Which TalkBack focusable nodes existed, and which of them were represented by
  persisted rows?"

This is intentionally different from V6:

- V6 asks whether a known semantic value was spoken.
- V7 asks whether each expected focusable node was discovered, covered, or
  missing from the result artifact.

## 2. Existing System Analysis

### 2.1 Traversal Engine

The traversal engine drives movement through the UI, usually with TalkBack
navigation primitives such as next / previous focus movement, local tab
activation, and stop conditions.

It can visit a real TalkBack focusable node without necessarily producing a
stable persisted row if:

- the focus payload is used only as movement evidence;
- the node is treated as representative context instead of the actual row;
- the row is suppressed as duplicate / consumed / terminal noise;
- the node appears in a helper dump but is never selected as a candidate;
- the node is visible only during a transient state;
- the node is outside current row-level quality issue filters.

### 2.2 Collection Flow

Collection flow currently builds rows from a mixture of:

- actual focus payloads;
- dump-derived candidates;
- inventory-only helper dump snapshots;
- selected / representative candidates;
- local-tab lifecycle signals;
- bottom-strip and terminal movement state;
- result persistence suppression.

This means "TalkBack focused it" and "XLSX result has a row for it" are not the
same invariant.

V7 should make that invariant explicit by introducing a focusable coverage audit
layer that compares expected focusable nodes with persisted row evidence.

The initial Phase 1 implementation extracted inventory from focus payloads and
from `dump_tree_nodes` already attached to rows. Motion Sensor live validation
showed that this is insufficient: successful focus payload paths can mark the
payload as sufficient and skip dump fallback, so `dump_tree_nodes` remains empty
even though readable / actionable child nodes are present on screen.

V7 therefore also needs an inventory-only helper dump snapshot. The snapshot is
used only to populate focusable inventory artifacts. It must not affect
traversal movement, candidate selection, row persistence, mismatch calculation,
semantic value quality, or shadow verdicts.

### 2.3 Actual Focus Row

Actual focus rows are strongest evidence that TalkBack landed on a node.
However, actual focus can still fail to become an auditable row when:

- a fallback representative row overwrites the useful node identity;
- a later persistence phase suppresses the row;
- only a composite label is saved, hiding child focusables;
- the focus payload omits child / state metadata;
- an artifact row lacks enough bounds / id metadata to match back to the node.

### 2.4 Representative Row

Representative rows were introduced to reduce false positives and preserve
context. They are useful for card-style UI, but they can hide a focusable
coverage gap.

Example risk:

```text
focusable node: Graph button
representative row: Motion detected
```

If only the representative row remains, V6 may see useful speech while V7 should
still report that the `Graph button` focusable needs coverage evidence.

### 2.5 Semantic Value Extraction

Semantic value extraction handles structures such as:

```text
Card:
  title = Status
  value = Stopped
  action = Start
```

It does not prove that every focusable child was captured as a row. A value can
be covered in speech while a separate focusable control inside the same card is
missing from persistence.

V7 should reuse semantic metadata as evidence, but should not redefine semantic
value quality.

### 2.6 Shadow Verdict

V6 shadow verdict combines row quality signals into a reporting-only verdict.
It is row-centric:

- `EMPTY_VISIBLE`
- `REPRESENTATIVE_CONTEXT`
- semantic value missing
- movement warnings
- local tab traversal failures

V7 should add focusable coverage metrics as another shadow input, but Phase 1
must remain reporting-only and must not change `PASS`, `WARN`, `FAIL`,
`mismatch_type`, or V6 shadow verdict semantics.

## 3. Scope

### 3.1 Included

Audit V7 includes:

- TalkBack focusable node discovery.
- Missing focusable discovery.
- Focusable coverage measurement.
- Shadow-only focusable coverage reporting.
- Per-scenario and per-plugin focusable coverage summaries.
- Evidence links from expected focusable nodes to covering rows.

### 3.2 Excluded

Audit V7 explicitly excludes:

- changing existing `PASS`, `WARN`, `FAIL`;
- changing `mismatch_type`;
- traversal engine redesign;
- local tab rewrite;
- candidate selection rewrite;
- semantic value verdict policy changes;
- enforcing focusable coverage as a hard gate in the initial phase.

## 4. Focusable Taxonomy

V7 needs a taxonomy because not every focusable node has the same accessibility
importance.

Initial categories:

- `required`
- `review`
- `optional`
- `ignore`

### 4.1 Required

Required focusables are user-meaningful elements whose absence from persisted
coverage likely hides an accessibility or traversal issue.

Examples:

- state value: `Motion detected`, `Locked`, `Stopped`
- battery percentage: `100%`
- toggle state: `On`, `Off`
- selected item / selected mode
- active device status
- alarm / alert state
- sensor reading that communicates current state

Expected behavior:

- must be covered by an actual row, representative row with strong relation, or
  explicit semantic evidence;
- missing required focusables should appear in V7 shadow reporting.

### 4.2 Review

Review focusables are meaningful controls or structural affordances that may be
validly represented by nearby context, but deserve manual inspection if missing.

Examples:

- graph button
- collapsed / expanded button
- overflow menu / `More options`
- chevron `>`
- history / details button
- CTA button where context may be represented elsewhere

Expected behavior:

- missing review focusables should not immediately fail;
- they should be surfaced in a V7 review section.

### 4.3 Optional

Optional focusables are low-risk or redundant nodes where missing row evidence is
not enough to indicate a quality problem.

Examples:

- decorative label that is also included in a parent row;
- duplicate card title;
- repeated section header;
- non-state text repeated in a composite row.

Expected behavior:

- tracked for diagnostics;
- not counted as required missing by default.

### 4.4 Ignore

Ignored focusables are expected artifacts or implementation details.

Examples:

- duplicate focus artifact;
- off-screen stale node;
- invisible / zero-sized helper node;
- overlay artifact unrelated to current plugin;
- tab strip item outside the current content audit scope;
- transient focus target that disappears before stable collection.

Expected behavior:

- excluded from denominator;
- retained only in debug evidence if needed.

## 5. Focusable Coverage Model

V7 introduces a separate accounting model:

```text
focusable_expected
-> focusable_covered
-> focusable_missing
```

### 5.1 Expected Focusable

An expected focusable is a node that V7 believes TalkBack can or should visit in
the current screen / local tab scope.

Candidate evidence sources:

- actual TalkBack focus payloads;
- helper accessibility dump nodes;
- inventory-only helper dump snapshots;
- Android XML / window dump nodes;
- candidate list before filtering;
- semantic card children;
- representative row sources;
- movement log labels.

Expected focusables should carry:

- stable node identity if available;
- bounds;
- class name;
- resource id;
- text / content description / state description;
- semantic card id if available;
- local tab scope;
- taxonomy category;
- evidence source.

### 5.2 Covered Focusable

A focusable is covered when a persisted row can be linked to it with sufficient
confidence.

Coverage evidence can include:

- same focus payload id / resource id;
- same bounds or contained bounds;
- same semantic card id and same role/value/action;
- same normalized label in the same local tab scope;
- representative row with source bounds matching the expected focusable;
- direct speech evidence for a required value.

Coverage should record:

- `focusable_coverage_status = covered`
- `focusable_covering_row_step`
- `focusable_covering_row_type`
- `focusable_match_confidence`
- `focusable_match_reason`

### 5.3 Missing Focusable

A focusable is missing when it is expected but no persisted row can be linked.

Missing focusables should record:

- `focusable_coverage_status = missing`
- `focusable_missing_reason`
- `focusable_taxonomy`
- `focusable_importance`
- `focusable_evidence_source`

Initial missing reasons:

- `no_persisted_row`
- `representative_only_no_node_row`
- `suppressed_duplicate_or_consumed`
- `candidate_filtered`
- `focus_payload_not_persisted`
- `bounds_or_id_unmatched`
- `taxonomy_review_required`

## 6. Audit Phase Plan

### Phase 1: Focusable Discovery Audit

Goal: discover and report focusable coverage without changing traversal or
verdicts.

Add reporting-only metrics:

- `focusable_expected_count`
- `focusable_covered_count`
- `focusable_missing_count`
- `focusable_coverage_rate`

Row-level / evidence outputs:

- expected focusable inventory sheet;
- per-focusable taxonomy;
- covering row link where available;
- missing reason.

Discovery sources:

- `focus_payload`: actual focus rows already collected by traversal;
- `dump_tree`: dump nodes already present on a row;
- `helper_snapshot`: inventory-only helper dump collected after scenario entry
  / anchor stabilization;
- `actionable_descendant`: separate action item derived from helper metadata
  such as `actionableDescendantContentDescription` and
  `actionableDescendantResourceId`.

Source priority for de-duplication:

```text
focus_payload > helper_snapshot > dump_tree > actionable_descendant
```

The recommended initial snapshot location is immediately after the scenario
anchor row is established and before main traversal starts. This gives V7 an
independent view of visible readable / actionable nodes while preserving the
existing traversal and reporting behavior.

No enforcement.

### Phase 2: Focusable Coverage Calculation

Goal: compare discovered inventory with persisted rows and produce a
reporting-only coverage artifact.

Artifacts:

- `focusable_inventory.json`: raw discovery records from `focus_payload`,
  `helper_snapshot`, `dump_tree`, and `actionable_descendant`;
- `focusable_coverage.json`: canonical focusable items, coverage status, match
  reason, and per-scenario summary.

Raw inventory records are first canonicalized so source-expanded duplicates do
not inflate coverage:

```text
raw inventory records
-> canonical focusable items
-> coverage records
-> scenario summary
```

Canonical key:

- `scenario_id` plus normalized `view_id` when a view id exists;
- otherwise `scenario_id` plus normalized `label` and normalized bounds bucket.

This keeps same-label controls separate when they represent different nodes. For
example, bottom tab `History` with `view_id=history` is distinct from graph
button `History` with `view_id=MotionSensorCapabilityCardView_header_graphButton`.

Bounds are normalized through the common bounds parser so comma strings and dict
strings such as `30,2338,372,2473` and `{'l': 30, 't': 2338, ...}` can collapse
to the same canonical item when the label and scenario also match.

Coverage statuses:

- `COVERED`: a persisted row confidently matches the canonical item;
- `MISSED`: no persisted row matches the canonical item;
- `UNKNOWN`: there is related evidence, but it is ambiguous or not specific
  enough to prove coverage.

Matching precedence:

```text
view_id exact
> normalized label exact
> same semantic card
> related bounds
```

If a label match exists but the result row has a different view id, the status is
`UNKNOWN`. If multiple rows match only by label, the status is also `UNKNOWN`.

Phase 2 deliberately excludes `representative_visible` and
`representative_speech` as coverage evidence. Representative context can prove
that useful text exists nearby, but it does not prove that the expected focusable
node itself persisted as a result row.

`focusable_coverage.json` summary fields:

- `raw_inventory_count`
- `expected_count`
- `canonical_expected_count`
- `covered_count`
- `missed_count`
- `unknown_count`
- `coverage_rate`

`expected_count` and `canonical_expected_count` are canonical item counts in
Phase 2. `raw_inventory_count` preserves the source-expanded count for
diagnostics.

Current limitations:

- taxonomy is not applied yet, so chrome and content items share the denominator;
- coverage does not affect `PASS`, `WARN`, `FAIL`, `mismatch_type`, semantic
  value metrics, or shadow verdicts;
- `UNKNOWN` requires manual review until taxonomy and stronger matching evidence
  are validated.

### Phase 3: Taxonomy Validation

Goal: validate required / review / optional / ignore classification against
real artifacts.

Tasks:

- review Motion Sensor, Door Lock, TV, Audio, Washer, Air Purifier;
- tune taxonomy based on false positives;
- add metadata confidence;
- identify plugin-agnostic rules.

Expected output:

- `focusable_required_expected_count`
- `focusable_required_missing_count`
- `focusable_review_missing_count`
- taxonomy false-positive notes.

### Phase 4: Shadow Coverage

Goal: make missing focusables visible in V6-style shadow reporting without
changing production verdicts.

New metrics:

- `focusable_expected_count`
- `focusable_covered_count`
- `focusable_missing_count`
- `focusable_coverage_rate`
- `focusable_required_missing_count`
- `focusable_review_missing_count`

Possible shadow interpretation:

- missing required focusable -> V7 shadow review / warning candidate;
- missing review focusable -> V7 shadow review;
- missing optional focusable -> diagnostic only;
- ignored focusable -> excluded.

Production `PASS`, `WARN`, `FAIL` remains unchanged.

### Phase 5: Frontend Reporting

Goal: surface V7 evidence in QA Frontend without changing existing result UX.

Display locations:

- XLSX summary sheet;
- dedicated `focusable_coverage` sheet;
- QA Frontend Shadow section;
- Scenario Evidence / run detail view.

Suggested UI:

```text
Focusable Coverage
Expected: 4
Covered: 4
Missing: 0
Required Missing: 0
Review Missing: 0
Coverage: 100%
```

Missing focusables should include:

- label;
- taxonomy;
- bounds;
- source;
- reason;
- nearest covering row candidate if any.

## 7. Motion Sensor Example

### 7.1 Observed Screen

Motion Sensor screen has TalkBack-readable elements:

- `Motion detected`
- `100%`
- `>`
- `Graph button`, collapsed button

Current result rows may include only a subset. This creates ambiguity:

- Did traversal miss the node?
- Did traversal visit the node but persistence suppress it?
- Did representative context absorb it?
- Did semantic extraction fail to classify it?

### 7.2 Expected V7 Focusable Inventory

Example expected inventory:

| label | taxonomy | rationale |
| --- | --- | --- |
| `Motion detected` | `required` | current motion state |
| `100%` | `required` | battery value |
| `>` | `review` | navigational affordance / chevron |
| `Graph button` | `review` | user-actionable collapsed control |

Phase 1 inventory should include these nodes from either focus payload or helper
snapshot evidence:

| label / id | preferred source |
| --- | --- |
| `Motion detected` | `helper_snapshot` readable node or `focus_payload` |
| `100%` | `helper_snapshot` readable value node |
| `MotionSensorCapabilityCardView_header_graphButton` / `History` | `actionable_descendant` |
| `Controls`, `Routines`, `History` | `focus_payload` or `helper_snapshot` |

### 7.3 Current Coverage Example

Illustrative current state:

| label | expected | covered | possible reason |
| --- | --- | --- | --- |
| `Motion detected` | yes | partial / unknown | may be spoken but not persisted |
| `100%` | yes | missing / unknown | value may lack row |
| `>` | yes | missing / unknown | affordance may be filtered |
| `Graph button` | yes | missing / unknown | collapsed button may be represented indirectly |

### 7.4 Future Coverage Example

Target V7 output:

```text
focusable_expected_count = 4
focusable_covered_count = 4
focusable_missing_count = 0
focusable_coverage_rate = 100.0%
focusable_required_missing_count = 0
focusable_review_missing_count = 0
```

If `Graph button` remains unlinked:

```text
focusable_expected_count = 4
focusable_covered_count = 3
focusable_missing_count = 1
focusable_review_missing_count = 1
focusable_coverage_rate = 75.0%
```

This should not change production `PASS/WARN/FAIL` in early phases, but should
appear in V7 shadow reporting.

## 8. Risk Analysis

### 8.1 False Positive Risks

Potential false positives:

- duplicate representative rows counted as missing focusables;
- collapsed controls that are intentionally summarized by parent rows;
- hidden nodes from stale dumps;
- overlay artifacts from other apps;
- off-screen nodes included in a dump but not reachable in current viewport;
- chevrons / decorative affordances treated as required;
- local tab strip nodes mixed into content scope;
- synthetic helper nodes that TalkBack cannot actually focus.

### 8.2 False Negative Risks

Potential false negatives:

- focusable node merged into a composite label and treated as covered too
  broadly;
- same label appears in unrelated row;
- stale focus bounds create incorrect coverage relation;
- semantic card id over-groups unrelated children;
- nearby representative evidence hides an actually missing focusable.

### 8.3 Mitigation

Initial safeguards:

- require same local tab scope for coverage matching;
- prefer exact id / bounds / semantic relation over label-only match;
- separate `required` from `review`;
- treat chevrons and collapsed controls as `review` until validated;
- keep V7 reporting-only until precision is measured;
- expose match reason and confidence for each coverage link.

## 9. Exit Criteria

Audit V7 is complete when the system can answer, per scenario:

- how many TalkBack focusable nodes were expected;
- how many were covered by persisted rows;
- which were missing;
- which missing nodes are required vs review;
- why each missing node was not covered;
- whether the gap is traversal, persistence, taxonomy, or artifact quality.

Minimum Motion Sensor exit criteria:

```text
expected focusables = 4
covered focusables = 4
missing focusables = 0
coverage rate = 100%
missing required focusables = 0
```

General rollout criteria:

- required focusable false-positive rate is low enough for shadow reporting;
- no regression to V6 semantic value / shadow verdict behavior;
- old artifacts without V7 sheets remain readable;
- QA Frontend can show V7 metrics without changing production verdict UX;
- per-focusable evidence is auditable from the XLSX.

## 10. Expected Implementation Touch Points

Likely implementation files:

- `tb_runner/collection_flow.py`
- `tb_runner/excel_report.py`
- `talkback_lib/focus_service.py`
- `talkback_lib/step_collection_service.py`
- `qa_frontend/backend/mismatch_viewer.py`
- `qa_frontend/backend/recent_runs.py`
- `qa_frontend/frontend/src/components/RecentRunsPanel.tsx`
- `qa_frontend/frontend/src/api.ts`

Implementation should start in reporting / artifact generation, not traversal
movement.

Recommended order:

1. Add focusable inventory extraction from existing dumps / focus payloads.
2. Add inventory-only helper snapshot extraction for cases where row dumps are
   skipped by successful focus payload paths.
3. Add XLSX-only focusable coverage sheet and summary metrics.
4. Validate taxonomy on Motion Sensor and several device plugins.
5. Add shadow-only frontend display.
6. Consider V7 shadow verdict integration only after precision is measured.
