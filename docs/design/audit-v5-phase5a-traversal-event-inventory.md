# Audit V5 Phase 5A Traversal Event Inventory

## 1. Scope

This document inventories existing traversal instrumentation for Audit V5 Phase 5A.

This is **not** an implementation document.

This document only answers:

- what traversal-related events, logs, and state already exist
- where they are emitted
- how well they map to the V5 traversal audit pipeline

Reference framing:

- Audit V4 is closed as XML-backed coverage plus reporting-only shadow verdict.
- Audit V5 is explicitly framed as `Traversal Engine Audit`, not as more coverage tuning.

## 2. Traversal Pipeline: Actual Implementation Locations

The current codebase does not implement the V5 pipeline as one single ledger.

Instead, the pipeline is distributed across three layers:

### 2.1 Discovery layer

Primary files:

- `tools/audit_xml_candidates.py`
- `tools/audit_xml_policy.py`
- `tools/audit_xml_coverage.py`
- `tools/audit_shadow_verdict.py`
- `tools/audit_device_plugins.py`
- `tb_runner/collection_flow.py`

Current role:

- XML capture is produced by runner code and persisted into scenario `xml_dumps`.
- post-run audit tools parse XML dumps into node candidates and merged candidates.
- candidate type, subtype, and policy recommendation are assigned after merge.

### 2.2 Runtime traversal layer

Primary files:

- `tb_runner/collection_flow.py`
- `tb_runner/local_tab_logic.py`
- `tb_runner/focus_realign_logic.py`
- `tb_runner/scroll_exhaustion_logic.py`
- `tb_runner/container_group_logic.py`

Current role:

- runtime candidate grouping
- representative selection
- candidate filtering and discard
- local-tab and bottom-strip progression
- forced activation and retry
- focus realign
- row persistence into traversal artifacts

### 2.3 Audit reconstruction layer

Primary files:

- `tools/audit_device_plugins.py`
- `tools/audit_xml_coverage.py`
- `tools/audit_shadow_verdict.py`

Current role:

- rehydrate traversal labels from logs and `.xlsx`
- reconstruct visited tabs
- compute XML-vs-traversal coverage
- derive shadow-required/optional/provisional counts

Conclusion:

- `DISCOVERED` is currently strongest in post-run XML tooling
- `SELECTED -> ACTIVATION -> FOCUS -> STATE -> VISIT` is currently strongest in runtime logs and row state
- there is no single canonical per-object event ledger yet

## 3. Discovery Inventory

### 3.1 XML candidate generation

Primary code:

- `tb_runner/collection_flow.py`
  - `_capture_audit_v4_xml()`
  - `_capture_audit_v4_xml_for_row()`
- `tools/audit_device_plugins.py`
  - `find_xml_dump_dir()`
- `tools/audit_xml_candidates.py`
  - `extract_xml_candidates()`

Current behavior:

- runner persists XML files under `<output>/<scenario_id>/xml_dumps`
- filename shape includes step and phase context
- post-run tooling locates the XML directory and parses all dumps

Discovery-side runtime artifact:

- XML file per captured phase

Current output structure from `extract_xml_candidates()`:

- `xml_candidates`
- `merged_candidates`
- `xml_unique_labels`
- `xml_diagnostic_status`
- `candidate_tab_distribution`
- `candidate_source_summary`

No dedicated runtime log event exists specifically named `DISCOVERED`.

### 3.2 Merged candidate generation

Primary code:

- `tools/audit_xml_candidates.py`
  - `extract_xml_candidates()`
  - `_infer_tab_from_dump_name()`
  - `_candidate_source_summary()`

Current behavior:

- raw node candidates are keyed by `(label, rid, class, bounds)`
- merged candidates are keyed by normalized label
- per-candidate sets are aggregated:
  - `tabs`
  - `dump_files`
  - `resource_ids`
  - `classes`
  - `bounds`
  - `focusable_values`
  - `clickable_values`
  - `xml_dump_count`

This is the strongest current implementation of `DISCOVERED`.

### 3.3 Candidate filtering

Primary code:

- `tools/audit_xml_candidates.py`
  - package filter
  - zero-bounds filter
  - empty text/desc/rid filter
- `tools/audit_xml_filters.py`
  - `classify_xml_candidate()`
- `tools/audit_xml_coverage.py`
  - `calculate_xml_coverage()` keeps only `classification == KEEP`

Current filtering observations:

- XML parsing applies low-level structural filtering
- coverage denominator applies `KEEP` filtering
- shadow logic later reinterprets merged candidates by eligibility

### 3.4 Candidate classification

Primary code:

- `tools/audit_xml_policy.py`
  - `classify_candidate_type()`
  - `recommend_candidate_policy()`
  - `classify_candidate_subtype()`
  - `apply_candidate_policy_diagnostics()`
- `tools/audit_xml_candidates.py`
  - applies the policy diagnostics to each merged candidate

Produced fields:

- `classification`
- `candidate_type`
- `candidate_type_reason`
- `candidate_subtype`
- `candidate_subtype_reason`
- `policy_recommendation`
- `policy_recommendation_reason`

Discovery assessment:

- `DISCOVERED` is already strongly traceable at post-run candidate level
- candidate classification metadata is strong enough for first-pass V5 discovery inventory reuse

## 4. Selection Inventory

### 4.1 Representative selection and prioritization

Primary code:

- `tb_runner/collection_flow.py`
  - `_collect_step_candidate_priority_groups()`
  - `_filter_content_candidates_for_phase()`
  - `_apply_spatial_priority_to_candidates()`
- `tb_runner/local_tab_logic.py`
  - selection and progression helpers

Current selection stages:

- raw visible nodes are grouped into:
  - content candidates
  - bottom-strip candidates
  - chrome-excluded candidates
- content candidates are filtered into:
  - status candidates
  - low-value leaf rejects
  - section-header deferred
  - visited rejects
  - revisit rejects
  - cluster-consumed rejects
  - consumed rejects
  - representative candidates
  - exhaustion candidates

Key selection logs:

- `candidate_priority`
- `candidate_sort_key`
- `selection_candidates`
- `status_exhausted_excluded`
- `section_header_deferred`
- `container_candidate_promoted`
- `container_priority_applied`
- `container_priority_skip`
- `representative_exhausted_eval`
- `exhaustion_candidates`
- `viewport_exhausted_eval`

### 4.2 Candidate exhaustion

Primary code:

- `tb_runner/local_tab_logic.py`
  - selection phase inside `_maybe_select_next_local_tab()`
- `tb_runner/collection_flow.py`
  - `_filter_content_candidates_for_phase()`

Current signals:

- `representative_exhausted_eval`
- `viewport_exhausted_eval`
- `viewport_exhausted`
- `content_phase_exhausted`

Current meaning:

- content candidates remain, so local-tab progression is blocked
- or content candidates are exhausted, so strip progression / scroll fallback may start

### 4.3 Discard logic

Primary discard buckets already exist, but are not exported as one canonical ledger.

Observed discard categories:

- passive status excluded
- low-value leaf rejected
- section header deferred
- visited logical signature rejected
- recent signature rejected
- consumed signature rejected
- consumed cluster rejected
- completed container-group rejected
- chrome excluded

Observed logs:

- `status_exhausted_excluded`
- `section_header_deferred`
- `selection_candidates`
- `representative_exhausted_guard`
- `container_group_skip`
- `row_filter`

Selection assessment:

- `SELECTED` is partially traceable
- `CANDIDATE_DISCARDED` is also partially traceable
- the code has strong intermediate buckets, but no explicit exported event schema yet

## 5. Activation Inventory

### 5.1 Primary activation path

Primary code:

- `tb_runner/local_tab_logic.py`
  - `_record_pending_local_tab_progression()`
  - `_activate_forced_local_tab_target()`
  - `_tap_local_tab_bounds_center()`
  - `_commit_forced_local_tab_target_success()`

Actual path:

```text
local tab progression selected
-> pending + forced target written
-> tap_bounds_center attempt if bounds available
-> post-action row collected
-> match check against pending target
-> fallback select_rid / select_label attempts
-> post-action row collected
-> match check
-> fail path with retry / move_smart_next fallback / guard
```

### 5.2 Activation logs

Strong existing activation logs:

- `local_tab_target_activate`
- `local_tab_target_activate_success`
- `local_tab_target_activate_no_match`
- `local_tab_target_activate_fail`
- `local_tab_target_activate_skip`
- `local_tab_force_navigation_set`
- `local_tab_force_navigation_retry`
- `local_tab_force_navigation_resolved`
- `local_tab_force_navigation_clear`

### 5.3 Activation fail reasons observed

Observed explicit reasons:

- `bounds_missing`
- `tap_primitive_missing`
- `viewport_unknown`
- `bounds_parse_failed`
- `focus_not_target_after_tap`
- `no_match_after_all_methods`
- `max_attempts_reached`
- `activation_guard`
- `pending_ttl_expired`

### 5.4 Activation success judgment

Success is currently judged by `_row_matches_pending_local_tab()`:

- resource-id match
- compact resource-id similarity
- normalized label exact match
- normalized label containment
- bounds overlap

Activation assessment:

- `ACTIVATION_ATTEMPT` is strongly traceable
- `ACTIVATION_SUCCESS/FAIL` is strongly traceable for forced local-tab targets
- non-local-tab generic activation is less explicitly normalized

## 6. Focus Outcome Inventory

### 6.1 Primary focus realign code

Primary code:

- `tb_runner/focus_realign_logic.py`
  - `_focus_anchor_match_reason()`
  - `_maybe_realign_focus_to_representative_impl()`
- `tb_runner/local_tab_logic.py`
  - realign selection / skip / record logic around representative selection
- `tb_runner/collection_flow.py`
  - wrapper calls and state storage

### 6.2 Focus logs

Strong existing focus logs:

- `focus_context_mismatch`
- `focus_realign`
- `focus_realign_success`
- `focus_realign_fail`
- `focus_force_realign`
- `focus_force_realign_success`
- `focus_force_realign_fail`
- `focus_realign_skip`
- `focus_realign_candidates`
- `focus_realign_record`

### 6.3 Success / fail judgment

Current focus-realign success judgment relies on `_representative_focus_matches()` and `_focus_anchor_match_reason()`:

- target resource-id match
- target label exact match
- bounds overlap
- cluster signature match

Current failure conditions:

- alignment primitives unavailable
- select attempt produces no matching focus payload
- recent resolved / failed signatures cause skip

### 6.4 Drift evidence

Current code does not emit a dedicated `FOCUS_DRIFT` event name.

But drift is already inferable from:

- `focus_context_mismatch`
- `focus_force_realign`
- `focus_realign_fail`
- mismatch between selected target and resolved focus

Focus assessment:

- `FOCUS_OUTCOME` is strongly instrumented
- `FOCUS_DRIFT` is partially traceable through existing mismatch/realign events
- `REALIGN_FAIL` is strongly traceable

## 7. State Outcome Inventory

### 7.1 State structures

Primary state structures:

- `tb_runner/local_tab_logic.py`
  - `LocalTabState`
- `tb_runner/collection_flow.py`
  - `MainLoopState`
  - `FocusRealignState`
  - `ScrollState`
  - `BottomStripRepetitionGuardState`

Important existing fields in `LocalTabState`:

- `signature`
- `active_label`
- `active_rid`
- `active_age`
- `pending_signature`
- `pending_label`
- `pending_rid`
- `pending_bounds`
- `pending_age`
- `forced_signature`
- `forced_label`
- `forced_rid`
- `forced_bounds`
- `forced_attempt_count`
- `last_selected_signature`
- `last_selected_label`
- `last_selected_rid`
- `last_selected_bounds`
- `visited_by_signature`
- `exhausted_signatures`
- `candidates_by_signature`

Important mirrored fields in `MainLoopState`:

- current local-tab identity
- pending progression target
- forced activation target
- activation failure counters
- visited local tabs by signature
- consumed representative and cluster signatures
- completed container groups
- focus realign state

### 7.2 Local-tab progression

Primary code:

- `tb_runner/local_tab_logic.py`
  - `_maybe_select_next_local_tab()`
  - `_resolve_active_local_tab_candidate_for_progression()`
  - `_record_pending_local_tab_progression()`
  - `_maybe_commit_pending_local_tab_progression()`

Strong state/progression logs:

- `local_tab_gate`
- `local_tab_allowed`
- `local_tab_progression`
- `local_tab_pending`
- `local_tab_select`
- `local_tab_pending_eval`
- `local_tab_commit_match`
- `local_tab_state_write`
- `local_tab_commit`
- `local_tab_pending_skip`
- `local_tab_pending_clear`

### 7.3 Bottom-strip progression

Primary code:

- `tb_runner/local_tab_logic.py`
  - `_recover_local_tab_state_from_bottom_strip()`
  - bottom-strip context evaluation in `_maybe_select_next_local_tab()`

Strong bottom-strip logs:

- `bottom_strip_policy`
- `bottom_strip_context_eval`
- `local_tab_recover`
- `local_tab_recover_fail`
- `last_scroll_fallback_eval`
- `last_scroll_fallback`
- `last_scroll_fallback_result`

Current meaning:

- strip candidates are known
- strip may be deferred while content remains
- strip state may later be reconstructed from dump candidates

### 7.4 Recovery paths

Observed recovery paths:

- bottom-strip state recovery
- pending local-tab commit recovery
- onboarding special-case recovery
- scroll fallback before local-tab progression

Strong recovery logs:

- `local_tab_recover`
- `local_tab_recover_fail`
- `local_tab_state_clear`
- `local_tab_pending_clear`
- `last_scroll_fallback_result`

State assessment:

- `STATE_OUTCOME` is strongly instrumented for local-tab/bottom-strip state
- `STATE_RECOVERY_FAIL` is partially traceable
- the main gap is lack of one normalized recovery event schema

## 8. Visit Commit Inventory

### 8.1 Runtime commit

There are two different meanings of “visit commit” in current code.

#### A. Runtime state commit

Primary code:

- `tb_runner/local_tab_logic.py`
  - `_maybe_commit_pending_local_tab_progression()`
  - `_commit_forced_local_tab_target_success()`

Strong logs:

- `local_tab_commit`
- `local_tab_state_write kind='committed'`
- `local_tab_force_navigation_resolved`

Meaning:

- local-tab target is accepted as active / committed

#### B. Traversal row persistence

Primary code:

- `tb_runner/collection_flow.py`
  - `_apply_row_quality_phase_impl()`
  - `_apply_row_persistence_phase_impl()`
  - `_build_persisted_row_semantics()`

Strong logs:

- `STEP END`
- `ROW`
- `row_filter`

Persistence behavior:

- row is annotated
- row may be suppressed by filter
- otherwise `_build_persisted_row_semantics()` persists it
- persisted row is appended to:
  - `rows`
  - `all_rows`
- then recorded into `ScenarioPerfStats`
- then eventually saved into `.xlsx`

### 8.2 Audit reuse value

The strongest current audit reuse point for `VISITED` is not a dedicated event.

It is the persisted row plus its label fields:

- `visible_label`
- `merged_announcement`
- `focus_view_id`
- `focus_bounds`
- `row_lifecycle_kind`
- `row_lifecycle_source`

`tools/audit_device_plugins.py` currently reconstructs visit evidence from:

- `[STEP] END`
- `[STEP][focus_realign_record]`
- local-tab transition and active-state logs
- `.xlsx` visible-label sets

Visit assessment:

- `VISITED` is partially traceable
- visited evidence exists, but not yet as a first-class canonical event type

## 9. Event Inventory Table

| Event | File | Function | Meaning | Reuse Value |
| ----- | ---- | -------- | ------- | ----------- |
| `xml_dump_capture` | `tb_runner/collection_flow.py` | `_capture_audit_v4_xml`, `_capture_audit_v4_xml_for_row` | Persist XML evidence for discovery-side audit | High |
| `merged_candidates` | `tools/audit_xml_candidates.py` | `extract_xml_candidates` | Build discovered-object inventory from XML dumps | High |
| `candidate_type/classification/policy` | `tools/audit_xml_policy.py` | `classify_candidate_type`, `classify_candidate_subtype`, `recommend_candidate_policy`, `apply_candidate_policy_diagnostics` | Attach candidate metadata for audit interpretation | High |
| `selection_candidates` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Show all candidates vs filtered candidates after selection pipeline | High |
| `candidate_priority` | `tb_runner/local_tab_logic.py` | representative selection path | Explain why current representative candidate was preferred | High |
| `status_exhausted_excluded` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Passive-status discard evidence | High |
| `section_header_deferred` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Section-header deferral evidence | High |
| `container_candidate_promoted` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Container promoted into selection surface | Medium |
| `representative_exhausted_eval` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Representative candidate exhaustion state | High |
| `viewport_exhausted_eval` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Viewport exhaustion state before scroll/local-tab progression | High |
| `bottom_strip_policy` | `tb_runner/local_tab_logic.py` | representative selection path | Explicit bottom-strip deferral while content remains | High |
| `LIFECYCLE` | `tb_runner/local_tab_logic.py` | `_annotate_row_lifecycle_kind` | Classify current row as local-tab/chrome/status/content/unknown | High |
| `focus_context_mismatch` | `tb_runner/focus_realign_logic.py`, `tb_runner/local_tab_logic.py` | realign path | Selected representative differs from current focus context | High |
| `focus_realign` | `tb_runner/focus_realign_logic.py` | `_maybe_realign_focus_to_representative_impl` | Attempt to align focus to selected representative | High |
| `focus_realign_success` | `tb_runner/focus_realign_logic.py` | `_maybe_realign_focus_to_representative_impl` | Focus aligned to intended representative | High |
| `focus_realign_fail` | `tb_runner/focus_realign_logic.py` | `_maybe_realign_focus_to_representative_impl` | Realign attempt failed | High |
| `focus_force_realign` | `tb_runner/focus_realign_logic.py` | `_maybe_realign_focus_to_representative_impl` | Forced realign attempt for higher-risk mismatch path | High |
| `focus_force_realign_success` | `tb_runner/focus_realign_logic.py` | `_maybe_realign_focus_to_representative_impl` | Forced realign succeeded | High |
| `focus_force_realign_fail` | `tb_runner/focus_realign_logic.py` | `_maybe_realign_focus_to_representative_impl` | Forced realign failed | High |
| `focus_realign_record` | `tb_runner/local_tab_logic.py` | representative selection path | Persist resolved representative target into row/log stream | High |
| `local_tab_gate` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Whether local-tab progression is currently allowed | High |
| `local_tab_progression` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Show current active tab and next target tab | High |
| `local_tab_state_write kind='pending'` | `tb_runner/local_tab_logic.py` | `_record_pending_local_tab_progression` | Pending progression target written | High |
| `local_tab_pending_eval` | `tb_runner/local_tab_logic.py` | `_maybe_commit_pending_local_tab_progression` | Evaluate whether current row resolves pending tab target | High |
| `local_tab_commit` | `tb_runner/local_tab_logic.py` | `_maybe_commit_pending_local_tab_progression`, `_commit_forced_local_tab_target_success` | Active tab committed | High |
| `local_tab_recover` | `tb_runner/local_tab_logic.py` | `_recover_local_tab_state_from_bottom_strip` | Recover local-tab state from bottom-strip candidates | High |
| `local_tab_recover_fail` | `tb_runner/local_tab_logic.py` | `_recover_local_tab_state_from_bottom_strip` | Recovery failed due to missing strip evidence/signature | High |
| `local_tab_target_activate` | `tb_runner/local_tab_logic.py` | `_tap_local_tab_bounds_center`, `_activate_forced_local_tab_target` | Activation attempt for target tab | High |
| `local_tab_target_activate_success` | `tb_runner/local_tab_logic.py` | `_activate_forced_local_tab_target` | Activation landed on target | High |
| `local_tab_target_activate_no_match` | `tb_runner/local_tab_logic.py` | `_activate_forced_local_tab_target` | Activation attempt ran, but post-action focus did not match target | High |
| `local_tab_target_activate_fail` | `tb_runner/local_tab_logic.py` | `_activate_forced_local_tab_target` | All activation methods failed to land target | High |
| `local_tab_force_navigation_resolved` | `tb_runner/local_tab_logic.py` | `_activate_forced_local_tab_target` | Forced activation path resolved target | High |
| `last_scroll_fallback_eval` | `tb_runner/local_tab_logic.py` | `_maybe_select_next_local_tab` | Decide if one final scroll is allowed before global exhaust / local-tab progression | Medium |
| `STEP END` | `tb_runner/collection_flow.py` | `_apply_row_quality_phase_impl` | End-of-step persisted traversal evidence summary | High |
| `row_filter` | `tb_runner/collection_flow.py` | `_apply_row_persistence_phase_impl` | Row persistence suppression evidence | Medium |

## 10. Reusable Instrumentation

### 10.1 Strong reuse candidates

- XML dump persistence
- merged candidate inventory
- candidate type/subtype/policy metadata
- selection/discard logs
- bottom-strip deferral logs
- focus realign logs
- local-tab activation logs
- local-tab recovery logs
- persisted traversal rows and `.xlsx` visible labels

### 10.2 Best first-pass reuse set for V5 MVP

- `extract_xml_candidates()` output as `DISCOVERED`
- runtime selection logs as `SELECTED` and discard evidence
- `local_tab_target_activate*` logs as `ACTIVATION_ATTEMPT/SUCCESS/FAIL`
- `focus_*realign*` logs as `FOCUS_OUTCOME` and `REALIGN_FAIL`
- `local_tab_*`, `bottom_strip_*`, `local_tab_recover*` as `STATE_OUTCOME`
- persisted rows plus `.xlsx` labels as `VISITED`

## 11. V5 Taxonomy Mapping

### `DISCOVERED`

- Status: `already traceable`
- Basis:
  - `extract_xml_candidates()`
  - `merged_candidates`
  - XML dump persistence

### `SELECTED`

- Status: `partially traceable`
- Basis:
  - `candidate_priority`
  - `selection_candidates`
  - `focus_realign_record`
- Gap:
  - no single canonical “selected object” ledger row per step

### `ACTIVATION_FAIL`

- Status: `already traceable`
- Basis:
  - `local_tab_target_activate_no_match`
  - `local_tab_target_activate_fail`
  - explicit failure reasons

### `FOCUS_DRIFT`

- Status: `partially traceable`
- Basis:
  - `focus_context_mismatch`
  - `focus_force_realign`
  - mismatch between selected target and resolved focus
- Gap:
  - no dedicated `FOCUS_DRIFT` event label

### `REALIGN_FAIL`

- Status: `already traceable`
- Basis:
  - `focus_realign_fail`
  - `focus_force_realign_fail`
  - failed-signature state

### `LOCAL_TAB_MISS`

- Status: `partially traceable`
- Basis:
  - `local_tab_gate`
  - `local_tab_progression`
  - `local_tab_pending_*`
  - `local_tab_commit`
  - `local_tab_target_activate_fail`
- Gap:
  - no final classifier that says “this miss is specifically local-tab miss”

### `BOTTOM_STRIP_MISS`

- Status: `partially traceable`
- Basis:
  - `bottom_strip_policy`
  - `bottom_strip_context_eval`
  - `local_tab_recover`
  - `local_tab_target_activate_fail`
- Gap:
  - no normalized bottom-strip miss verdict event

### `POLICY_DEPRIORITIZED`

- Status: `partially traceable`
- Basis:
  - `bottom_strip_policy`
  - `section_header_deferred`
  - `status_exhausted_excluded`
  - `container_priority_*`
- Gap:
  - current evidence is distributed across many logs

### `CANDIDATE_DISCARDED`

- Status: `partially traceable`
- Basis:
  - filter buckets in `_filter_content_candidates_for_phase()`
  - `selection_candidates`
  - `row_filter`
- Gap:
  - no exported per-candidate discard event stream

### `STATE_RECOVERY_FAIL`

- Status: `partially traceable`
- Basis:
  - `local_tab_recover_fail`
  - pending TTL expiration
  - `local_tab_pending_clear`
- Gap:
  - recovery failure is spread across local-tab and activation paths

## 12. Missing or Weak Events

The main missing pieces are not raw logs. The main missing pieces are normalized audit semantics.

### 12.1 Missing canonical selected-object event

Current weakness:

- selected target can be inferred from multiple logs
- there is no single step-level `SELECTED` event with stable object identity

### 12.2 Missing canonical visited-object commit event

Current weakness:

- row persistence plus `STEP END` is strong evidence
- but “visited” is reconstructed, not emitted as a dedicated audit event

### 12.3 Missing explicit focus-drift classification

Current weakness:

- drift is visible through mismatch and realign logs
- but there is no direct `FOCUS_DRIFT` event

### 12.4 Missing per-candidate discard export

Current weakness:

- discard buckets exist in memory and some logs
- but not as normalized emitted events tied to candidate identity

### 12.5 Missing unified state-recovery schema

Current weakness:

- recovery paths exist
- but “attempt / success / fail” is not consistently normalized across all state-recovery mechanisms

## 13. MVP Feasibility Assessment

Judgment:

- `Phase 5A MVP is feasible without runner refactor`

Why:

- discovery-side evidence is already strong
- activation-side evidence is already strong
- focus-realign evidence is already strong
- local-tab and bottom-strip state evidence is already strong
- visit evidence is reconstructable from persisted rows and current audit parsing

What is feasible immediately for MVP:

- event inventory
- normalized event vocabulary
- scenario-level discovered / visited / missed counts
- first-pass mapping for:
  - activation fail
  - realign fail
  - local-tab miss
  - bottom-strip miss
  - policy deprioritized

What is not yet clean enough without new implementation:

- one canonical per-object traversal ledger
- exhaustive per-candidate discard export
- strong automatic separation of `FOCUS_DRIFT` vs generic mismatch in every case
- generic `VISITED` commit event across all traversal modes

Practical conclusion:

- V5A should begin by normalizing existing logs, not by changing runner behavior
- most of the missing work is schema and reconstruction logic, not instrumentation creation from scratch
