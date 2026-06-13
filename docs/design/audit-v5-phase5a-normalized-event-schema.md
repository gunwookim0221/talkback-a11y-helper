# Audit V5 Phase 5A-2 Normalized Audit Event Schema

## 1. Purpose

This document defines the normalized audit event schema for Audit V5 Traversal Engine Audit.

The schema is based on the Phase 5A traversal event inventory and is intentionally designed around reconstruction from existing assets:

- XML candidates
- lifecycle logs
- selection / discard logs
- local-tab state logs
- activation logs
- focus realign logs
- persisted traversal rows
- `.xlsx` visible-label artifacts

The goal is to create one canonical event vocabulary and object ledger that can explain traversal outcomes without changing runner behavior in the MVP.

Target pipeline:

```text
DISCOVERED
-> SELECTED
-> ACTIVATION_ATTEMPT
-> ACTIVATION_SUCCESS / ACTIVATION_FAIL
-> FOCUS_OUTCOME
-> STATE_OUTCOME
-> VISITED / MISSED
```

## 2. Current Gap

Current instrumentation is rich, but the semantics are distributed.

Already present:

- XML-backed discovery through `merged_candidates`
- candidate classification and policy metadata
- selection and exhaustion logs
- local-tab progression logs
- bottom-strip deferral and recovery logs
- activation attempt / success / fail logs
- focus mismatch and realign logs
- persisted rows and `.xlsx` visit evidence

Missing canonical semantics:

- canonical `SELECTED` event
- canonical `VISITED` commit event
- explicit `FOCUS_DRIFT` event
- per-candidate discard event
- unified recovery event schema

Design implication:

- V5 MVP should normalize existing logs and artifacts first.
- Runner behavior, V4 shadow verdict policy, matching policy, eligibility policy, and coverage thresholds should remain unchanged.

## 3. Normalized Event Vocabulary

Each normalized event type has a stable meaning, source signal, field requirements, and root-cause relationship.

### 3.1 `DISCOVERED`

Meaning:

- A candidate object exists in the discovered UI surface.

Source signal:

- `tools/audit_xml_candidates.py::extract_xml_candidates()`
- `xml_candidates`
- `merged_candidates`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `confidence`

Optional fields:

- `candidate_type`
- `candidate_subtype`
- `policy_recommendation`
- `bounds`
- `resource_id`
- `class_name`
- `xml_dump_count`
- `dump_files`
- `tabs`

Root-cause relationship:

- base denominator for `MISSED`
- not a root cause by itself

### 3.2 `SELECTED`

Meaning:

- Traversal selected or attempted to promote a candidate as the next representative / target.

Source signal:

- `candidate_priority`
- `focus_realign_record`
- `local_tab_progression`
- `local_tab_state_write kind='pending'`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `reason`
- `confidence`

Optional fields:

- `selection_rank`
- `selection_group`
- `selected_by`
- `current_focus_label`
- `candidate_set_sample`
- `active_tab`
- `next_tab`

Root-cause relationship:

- establishes whether a missed candidate was ever attempted
- absence after discovery may support `CANDIDATE_DISCARDED`, `POLICY_DEPRIORITIZED`, or `UNKNOWN`

### 3.3 `ACTIVATION_ATTEMPT`

Meaning:

- Runner attempted to activate a selected target.

Source signal:

- `local_tab_target_activate`
- `local_tab_force_navigation_retry`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `activation_method`
- `confidence`

Optional fields:

- `bounds`
- `tap`
- `attempt_index`
- `resource_id`
- `visible_label`
- `raw_target`

Root-cause relationship:

- paired with `ACTIVATION_SUCCESS` or `ACTIVATION_FAIL`
- absence after `SELECTED` may support `LOCAL_TAB_MISS` or `STATE_RECOVERY_FAIL`

### 3.4 `ACTIVATION_SUCCESS`

Meaning:

- Activation landed on the intended target.

Source signal:

- `local_tab_target_activate_success`
- `local_tab_force_navigation_resolved`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `matched_by`
- `confidence`

Optional fields:

- `activation_method`
- `post_focus_label`
- `post_focus_resource_id`
- `post_focus_bounds`

Root-cause relationship:

- clears activation failure suspicion
- supports `visited` or state success if followed by commit / row evidence

### 3.5 `ACTIVATION_FAIL`

Meaning:

- Activation was attempted but did not land on the intended target.

Source signal:

- `local_tab_target_activate_no_match`
- `local_tab_target_activate_fail`
- `local_tab_target_activate_skip`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `reason`
- `confidence`

Optional fields:

- `activation_method`
- `fallback`
- `attempt_index`
- `post_focus_label`
- `post_focus_resource_id`
- `bounds`

Root-cause relationship:

- directly maps to root cause `ACTIVATION_FAIL`
- high priority for missed candidates

### 3.6 `FOCUS_CONTEXT_MISMATCH`

Meaning:

- Selected target and current focus context disagree.

Source signal:

- `focus_context_mismatch`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `current_focus_label`
- `reason`
- `confidence`

Optional fields:

- `current_focus_resource_id`
- `current_focus_bounds`
- `selected_resource_id`
- `selected_bounds`

Root-cause relationship:

- evidence for `FOCUS_DRIFT`
- if followed by realign success, not necessarily a terminal miss cause

### 3.7 `FOCUS_REALIGN_ATTEMPT`

Meaning:

- Runner attempted to align focus to a selected representative.

Source signal:

- `focus_realign`
- `focus_force_realign`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `realign_method`
- `confidence`

Optional fields:

- `force_reason`
- `attempt_index`
- `target_resource_id`
- `target_bounds`

Root-cause relationship:

- parent signal for `FOCUS_REALIGN_SUCCESS` or `FOCUS_REALIGN_FAIL`

### 3.8 `FOCUS_REALIGN_SUCCESS`

Meaning:

- Focus realign resolved to the intended representative.

Source signal:

- `focus_realign_success`
- `focus_force_realign_success`
- `focus_realign_record`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `resolved_focus`
- `confidence`

Optional fields:

- `realign_method`
- `matched_by`
- `target_bounds`

Root-cause relationship:

- clears `REALIGN_FAIL`
- may still leave prior `FOCUS_CONTEXT_MISMATCH` as non-terminal drift evidence

### 3.9 `FOCUS_REALIGN_FAIL`

Meaning:

- Focus realign failed to resolve to the selected representative.

Source signal:

- `focus_realign_fail`
- `focus_force_realign_fail`
- `focus_realign_skip` when reason is prior failure

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `reason`
- `confidence`

Optional fields:

- `realign_method`
- `attempt_index`
- `current_focus_label`
- `target_bounds`

Root-cause relationship:

- directly maps to root cause `REALIGN_FAIL`
- more specific than generic `FOCUS_DRIFT`

### 3.10 `STATE_RECOVERY_ATTEMPT`

Meaning:

- Runner attempted to reconstruct or stabilize traversal state.

Source signal:

- `local_tab_recover`
- `last_scroll_fallback_eval`
- `local_tab_pending_eval`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `recovery_kind`
- `reason`
- `confidence`

Optional fields:

- `active_before`
- `pending_before`
- `candidate_set_sample`
- `bottom_strip_context`
- `scrollable`

Root-cause relationship:

- parent signal for state recovery success / fail

### 3.11 `STATE_RECOVERY_SUCCESS`

Meaning:

- Recovery produced usable traversal state.

Source signal:

- `local_tab_recover`
- `local_tab_state_write kind='committed'`
- `local_tab_commit`
- `last_scroll_fallback_result` with resumed content

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `recovery_kind`
- `confidence`

Optional fields:

- `active_after`
- `candidate_set_sample`
- `matched_by`

Root-cause relationship:

- clears state recovery failure suspicion unless later events fail

### 3.12 `STATE_RECOVERY_FAIL`

Meaning:

- Recovery was needed but did not produce a stable continuation target.

Source signal:

- `local_tab_recover_fail`
- `local_tab_pending_clear`
- pending TTL expiration
- `last_scroll_fallback_result` with no resumed content when recovery was required

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `recovery_kind`
- `reason`
- `confidence`

Optional fields:

- `active_before`
- `pending_before`
- `candidate_set_sample`

Root-cause relationship:

- directly maps to root cause `STATE_RECOVERY_FAIL`

### 3.13 `LOCAL_TAB_TRANSITION_ATTEMPT`

Meaning:

- Runner attempted or prepared local-tab progression.

Source signal:

- `local_tab_progression`
- `local_tab_state_write kind='pending'`
- `local_tab_select`
- `local_tab_force_navigation_set`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `active_tab`
- `target_tab`
- `confidence`

Optional fields:

- `signature`
- `target_bounds`
- `target_resource_id`
- `reason`

Root-cause relationship:

- parent signal for local-tab success / fail

### 3.14 `LOCAL_TAB_TRANSITION_SUCCESS`

Meaning:

- Local-tab transition reached and committed the target tab.

Source signal:

- `local_tab_commit`
- `local_tab_force_navigation_resolved`
- `local_tab_state_write kind='committed'`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `target_tab`
- `confidence`

Optional fields:

- `matched_by`
- `active_after`
- `signature`

Root-cause relationship:

- clears `LOCAL_TAB_MISS` for that target

### 3.15 `LOCAL_TAB_TRANSITION_FAIL`

Meaning:

- Local-tab progression was attempted or required but did not reach the target.

Source signal:

- `local_tab_gate allowed=false` when target remains unvisited
- `local_tab_pending_clear`
- `local_tab_target_activate_fail`
- activation guard skip

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `reason`
- `confidence`

Optional fields:

- `target_tab`
- `active_tab`
- `pending_age`
- `activation_fail_reason`

Root-cause relationship:

- maps to root cause `LOCAL_TAB_MISS`
- can be superseded by `BOTTOM_STRIP_MISS` if target belongs to bottom strip

### 3.16 `BOTTOM_STRIP_DEFERRED`

Meaning:

- Bottom-strip candidate existed but traversal intentionally preferred content first.

Source signal:

- `bottom_strip_policy`
- `candidate_priority reason='content_candidate_preferred_over_bottom_strip'`
- `local_tab_gate reason='content_not_exhausted'`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `reason`
- `confidence`

Optional fields:

- `bottom_strip_candidates`
- `selected_content_candidate`
- `active_tab`

Root-cause relationship:

- maps to `POLICY_DEPRIORITIZED` while content remains
- maps to `BOTTOM_STRIP_MISS` only if candidate remains unvisited at terminal state

### 3.17 `POLICY_DEPRIORITIZED`

Meaning:

- Candidate was intentionally delayed by traversal policy, not necessarily missed.

Source signal:

- `bottom_strip_policy`
- `section_header_deferred`
- `status_exhausted_excluded`
- `container_priority_applied`
- `container_priority_skip`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `reason`
- `confidence`

Optional fields:

- `deprioritized_by`
- `selected_instead`
- `candidate_set_sample`

Root-cause relationship:

- terminal root cause only when candidate remains unvisited and no later attempt exists
- otherwise a non-terminal deferred state

### 3.18 `CANDIDATE_DISCARDED`

Meaning:

- Candidate was filtered out of the candidate set before becoming a selected traversal target.

Source signal:

- `selection_candidates`
- `status_exhausted_excluded`
- `section_header_deferred`
- `representative_exhausted_guard`
- `container_group_skip`
- `row_filter`

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `discard_reason`
- `confidence`

Optional fields:

- `discard_bucket`
- `selected_instead`
- `candidate_set_sample`

Root-cause relationship:

- maps to `CANDIDATE_DISCARDED` when terminal missed candidate has discard evidence and no stronger failure event

### 3.19 `VISITED`

Meaning:

- Candidate was actually observed as traversal output or committed as reached.

Source signal:

- `STEP END`
- persisted row in `.xlsx`
- `local_tab_commit`
- `local_tab_force_navigation_resolved`
- `focus_realign_record` when representative is persisted as traversal evidence

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `step_index`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `confidence`

Optional fields:

- `visible_label`
- `speech`
- `focus_view_id`
- `focus_bounds`
- `row_lifecycle_kind`
- `row_lifecycle_source`
- `visited_by`

Root-cause relationship:

- terminal success state
- clears `MISSED`

### 3.20 `MISSED`

Meaning:

- Candidate was discovered but no matching visited evidence exists by terminal audit time.

Source signal:

- derived from candidate ledger, not a raw runner log

Required fields:

- `event_type`
- `run_id`
- `scenario_id`
- `candidate_id`
- `stable_label`
- `source_event_name`
- `root_cause`
- `confidence`

Optional fields:

- `last_seen_step_index`
- `last_event_type`
- `root_cause_evidence`
- `miss_reason`

Root-cause relationship:

- terminal output event carrying the attributed root cause

## 4. Common Event Schema

Recommended normalized event object:

```json
{
  "run_id": "audit_run_20260613_010203",
  "scenario_id": "life_family_care_plugin",
  "plugin_id": "life_family_care_plugin",
  "phase": "main_loop",
  "event_type": "ACTIVATION_FAIL",
  "step_index": 20,
  "timestamp": null,
  "source_file": "tb_runner/local_tab_logic.py",
  "source_function": "_activate_forced_local_tab_target",
  "source_event_name": "local_tab_target_activate_fail",
  "candidate_id": "cid:v1:...",
  "stable_label": "EventsButton",
  "visible_label": "EventsButton Events",
  "candidate_type": "ACTIONABLE",
  "candidate_subtype": "NAV_TILE",
  "bounds": "710,2316,1050,2496",
  "resource_id": "eventsbutton",
  "class_name": "android.widget.LinearLayout",
  "confidence": "high",
  "reason": "no_match_after_all_methods",
  "evidence": {
    "matched_by": "none",
    "activation_method": "select_label",
    "post_focus_label": ""
  },
  "raw_payload": {
    "raw_log_line": "[STEP][local_tab_target_activate_fail] ..."
  }
}
```

Common required fields:

- `run_id`
- `scenario_id`
- `plugin_id`
- `phase`
- `event_type`
- `source_file`
- `source_event_name`
- `candidate_id`
- `stable_label`
- `confidence`
- `evidence`

Common optional fields:

- `step_index`
- `timestamp`
- `source_function`
- `visible_label`
- `candidate_type`
- `candidate_subtype`
- `bounds`
- `resource_id`
- `class_name`
- `reason`
- `raw_payload`

Field guidance:

- `step_index` is the MVP primary time coordinate because existing logs are step-oriented.
- `timestamp` can remain nullable until logs expose a stable timestamp source.
- `phase` should use values such as `xml_discovery`, `entry`, `main_loop`, `local_tab_transition`, `recovery`, `post_analysis`.
- `confidence` should use `high`, `medium`, or `low`.
- `evidence` should be structured enough for reporting.
- `raw_payload` should retain source-specific fields or raw line excerpts for debugging.

## 5. Candidate ID Strategy

Candidate IDs are the join key between discovery candidates, runtime events, persisted rows, and final ledger state.

### 5.1 Option A: stable-label based

Shape:

```text
cid:v1:label:<normalized_label>
```

Pros:

- simple
- easy to match with current `.xlsx` and log labels
- robust when bounds change across scroll captures

Cons:

- collisions when the same label appears in multiple places
- weak for repeated cards, repeated values, or localized compound labels
- loses resource and bounds identity

### 5.2 Option B: visible-label + bounds based

Shape:

```text
cid:v1:label_bounds:<normalized_label>|<normalized_bounds>
```

Pros:

- separates repeated labels when bounds differ
- useful for XML-origin candidates
- helpful for bottom-strip and card positions

Cons:

- unstable across scroll, viewport, device size, and layout changes
- hard to match against row logs that have different or missing bounds

### 5.3 Option C: resource-id + label based

Shape:

```text
cid:v1:rid_label:<resource_id>|<normalized_label>
```

Pros:

- strong for local tabs and actionable controls
- aligns with activation matching logic
- less fragile than bounds when resource IDs are present

Cons:

- weak for static text and status labels
- resource IDs may be missing or generic
- collisions still possible for repeated resource templates

### 5.4 Option D: XML candidate hash based

Shape:

```text
cid:v1:hash:<sha1(label|resource_ids|classes|bounds|tabs)>
```

Pros:

- deterministic
- compact
- can include all available discovery identity fields
- works for merged candidates

Cons:

- harder to debug by eye
- runtime-only events must reconstruct enough identity to match the same hash
- changes if input field set changes

### 5.5 MVP recommendation

Recommended MVP strategy:

```text
candidate_id = cid:v1:<scenario_id>:<identity_hash>
identity_hash = sha1(
  normalized_label
  + primary_resource_id_or_empty
  + primary_class_or_empty
  + canonical_bounds_bucket_or_empty
)
```

Also store human-readable join fields:

- `stable_label`
- `normalized_label`
- `resource_id`
- `bounds`
- `candidate_key_debug`

MVP matching fallback order:

1. exact `candidate_id`
2. `resource_id + normalized_label`
3. `normalized_label + bounds overlap`
4. `normalized_label`
5. containment match with reduced confidence

Reasoning:

- hash ID gives stable ledger keys
- label/resource/bounds fallback preserves practical matching with existing logs
- debug fields keep reports readable

## 6. Candidate Ledger Schema

The candidate ledger is the object-level state produced by folding normalized events.

Recommended ledger row:

```json
{
  "candidate_id": "cid:v1:...",
  "scenario_id": "life_family_care_plugin",
  "plugin_id": "life_family_care_plugin",
  "stable_label": "EventsButton",
  "normalized_label": "eventsbutton",
  "candidate_type": "ACTIONABLE",
  "candidate_subtype": "NAV_TILE",
  "policy_recommendation": "KEEP",
  "bounds": ["710,2316,1050,2496"],
  "resource_ids": ["eventsbutton"],
  "classes": ["android.widget.LinearLayout"],
  "discovered": true,
  "selected": true,
  "activation_attempted": true,
  "activation_succeeded": false,
  "focus_drifted": true,
  "realign_attempted": true,
  "realign_succeeded": false,
  "state_recovery_attempted": true,
  "state_recovery_succeeded": true,
  "visited": false,
  "missed": true,
  "root_cause": "ACTIVATION_FAIL",
  "root_cause_confidence": "high",
  "event_ids": ["evt-001", "evt-002"],
  "last_event_type": "MISSED",
  "last_step_index": 20,
  "evidence_sample": []
}
```

Required state fields and source events:

| Ledger State | Source Event |
| --- | --- |
| `discovered` | `DISCOVERED` |
| `selected` | `SELECTED`, `LOCAL_TAB_TRANSITION_ATTEMPT` |
| `activation_attempted` | `ACTIVATION_ATTEMPT` |
| `activation_succeeded` | `ACTIVATION_SUCCESS` |
| `focus_drifted` | `FOCUS_CONTEXT_MISMATCH` without later clearing success, or mismatch followed by terminal miss |
| `realign_attempted` | `FOCUS_REALIGN_ATTEMPT` |
| `realign_succeeded` | `FOCUS_REALIGN_SUCCESS` |
| `state_recovery_attempted` | `STATE_RECOVERY_ATTEMPT` |
| `state_recovery_succeeded` | `STATE_RECOVERY_SUCCESS` |
| `visited` | `VISITED` |
| `missed` | derived terminal state when `discovered=true` and `visited=false` |
| `root_cause` | derived by attribution rules |

Ledger folding principle:

- raw events are append-only
- ledger state is derived
- `MISSED` is a terminal derived event, not a raw runner source

## 7. Root Cause Attribution Rules

Root cause attribution should be deterministic and conservative.

### 7.1 Priority order

Recommended priority for terminal missed candidates:

1. `ACTIVATION_FAIL`
2. `REALIGN_FAIL`
3. `STATE_RECOVERY_FAIL`
4. `BOTTOM_STRIP_MISS`
5. `LOCAL_TAB_MISS`
6. `CANDIDATE_DISCARDED`
7. `POLICY_DEPRIORITIZED`
8. `FOCUS_DRIFT`
9. `UNKNOWN`

Reasoning:

- explicit fail events beat inferred state
- activation failure is the most direct signal when present
- realign failure is more specific than generic focus drift
- bottom-strip miss is more specific than local-tab miss
- policy deprioritization should be terminal only if the candidate never becomes attempted and remains unvisited

### 7.2 `ACTIVATION_FAIL`

Rule:

- candidate has `ACTIVATION_ATTEMPT`
- candidate has `ACTIVATION_FAIL`
- candidate has no later `ACTIVATION_SUCCESS` or `VISITED`

Confidence:

- high when source is `local_tab_target_activate_fail`
- medium when source is only `local_tab_target_activate_skip`

### 7.3 `FOCUS_DRIFT`

Rule:

- candidate has `FOCUS_CONTEXT_MISMATCH`
- no later `FOCUS_REALIGN_SUCCESS`
- no stronger activation / realign / state failure applies
- candidate remains unvisited

Confidence:

- medium by default
- high only when selected target and resolved focus are both extractable and clearly different

### 7.4 `REALIGN_FAIL`

Rule:

- candidate has `FOCUS_REALIGN_ATTEMPT`
- candidate has `FOCUS_REALIGN_FAIL`
- no later `FOCUS_REALIGN_SUCCESS` or `VISITED`

Confidence:

- high for `focus_realign_fail` or `focus_force_realign_fail`
- medium for `focus_realign_skip` due to previous failed signature

Conflict rule:

- `REALIGN_FAIL` outranks `FOCUS_DRIFT` because it is a more specific mechanism.

### 7.5 `LOCAL_TAB_MISS`

Rule:

- candidate is local-tab-like or nav-tile-like
- candidate has `LOCAL_TAB_TRANSITION_ATTEMPT` or local-tab gate evidence
- no `LOCAL_TAB_TRANSITION_SUCCESS`
- no `VISITED`
- no more specific bottom-strip classification applies

Confidence:

- high when pending target or forced target identity matches candidate
- medium when only gate/progression context is available

### 7.6 `BOTTOM_STRIP_MISS`

Rule:

- candidate appears in bottom-strip candidate set
- candidate has `BOTTOM_STRIP_DEFERRED`, `bottom_strip_context_eval`, or `local_tab_recover` evidence
- candidate remains unvisited
- transition or activation does not resolve it

Confidence:

- high when candidate has activation fail or recovery evidence in bottom-strip context
- medium when only repeated deferral exists

Conflict rule:

- `BOTTOM_STRIP_MISS` outranks `LOCAL_TAB_MISS` because it identifies the specific local-tab surface and policy context.

### 7.7 `POLICY_DEPRIORITIZED`

Rule:

- candidate has `POLICY_DEPRIORITIZED` or `BOTTOM_STRIP_DEFERRED`
- candidate has no activation or realign failure
- candidate remains unvisited

Important distinction:

- if later selected or activated, policy deprioritization is not terminal root cause
- while content remains, this is a deferred state, not a miss
- only terminal unvisited candidates can receive this root cause

Confidence:

- medium by default
- low when derived only from aggregate candidate samples

### 7.8 `CANDIDATE_DISCARDED`

Rule:

- candidate has `CANDIDATE_DISCARDED`
- candidate has no `SELECTED`
- candidate remains unvisited
- no stronger root cause applies

Confidence:

- high when discard bucket is explicit and candidate identity is strong
- medium when inferred from list samples

### 7.9 `STATE_RECOVERY_FAIL`

Rule:

- candidate has `STATE_RECOVERY_ATTEMPT`
- candidate has `STATE_RECOVERY_FAIL`
- candidate remains unvisited
- no stronger activation fail applies

Confidence:

- high for `local_tab_recover_fail`
- medium for pending TTL expiration when target identity is partial

### 7.10 `UNKNOWN`

Rule:

- candidate is discovered and unvisited
- no sufficient event combination explains the miss

Confidence:

- low

## 8. MVP Report Schema

The MVP report should be JSON-first.

Recommended top-level shape:

```json
{
  "schema_version": "audit_v5_events_v1",
  "run_metadata": {
    "run_id": "audit_run_20260613_010203",
    "created_at": null,
    "source_output_dir": "output/...",
    "tool_version": "phase5a-mvp",
    "v3_authoritative": true,
    "shadow_policy_name": "balanced_v1"
  },
  "scenario_summaries": [],
  "candidate_ledgers": [],
  "event_samples": [],
  "root_cause_summary": {},
  "metrics": {}
}
```

### 8.1 Run metadata

Recommended fields:

- `run_id`
- `created_at`
- `source_output_dir`
- `scenario_ids`
- `tool_version`
- `v3_authoritative`
- `shadow_policy_name`

### 8.2 Scenario summary

Recommended fields:

- `scenario_id`
- `plugin_id`
- `v3_verdict`
- `shadow_verdict_v4`
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
- `top_root_causes`

### 8.3 Candidate ledger

Recommended fields:

- all fields from Candidate Ledger Schema
- plus compact event references and evidence samples

### 8.4 Event samples

Recommended fields:

- `scenario_id`
- `candidate_id`
- `event_type`
- `source_event_name`
- `step_index`
- `stable_label`
- `reason`
- `confidence`
- `evidence`

### 8.5 Root cause summary

Recommended shape:

```json
{
  "ACTIVATION_FAIL": 1,
  "REALIGN_FAIL": 0,
  "STATE_RECOVERY_FAIL": 0,
  "BOTTOM_STRIP_MISS": 2,
  "LOCAL_TAB_MISS": 0,
  "CANDIDATE_DISCARDED": 0,
  "POLICY_DEPRIORITIZED": 0,
  "FOCUS_DRIFT": 0,
  "UNKNOWN": 0
}
```

### 8.6 Required metrics

Required MVP metrics:

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

Metric formulas:

```text
activation_success_rate = activation_success_count / max(activation_attempt_count, 1)
visit_rate = visited_count / max(discovered_count, 1)
miss_attribution_rate = (missed_count - unknown_miss_count) / max(missed_count, 1)
```

## 9. Source Signal Mapping

| Source Event Name | Normalized Event Type | Extraction Difficulty | Reliability | MVP Inclusion |
| --- | --- | --- | --- | --- |
| `merged_candidates` | `DISCOVERED` | low | high | yes |
| `xml_candidates` | `DISCOVERED` | low | high | yes |
| `candidate_type/classification/policy` | `DISCOVERED` metadata | low | high | yes |
| `candidate_priority` | `SELECTED`, `POLICY_DEPRIORITIZED` | medium | medium | yes |
| `candidate_sort_key` | `SELECTED` metadata | medium | medium | no |
| `selection_candidates` | `SELECTED`, `CANDIDATE_DISCARDED` | medium | medium | yes |
| `status_exhausted_excluded` | `CANDIDATE_DISCARDED`, `POLICY_DEPRIORITIZED` | low | high | yes |
| `section_header_deferred` | `POLICY_DEPRIORITIZED` | low | high | yes |
| `container_candidate_promoted` | `SELECTED` metadata | medium | medium | no |
| `container_priority_applied` | `POLICY_DEPRIORITIZED`, `SELECTED` metadata | medium | medium | yes |
| `representative_exhausted_eval` | `CANDIDATE_DISCARDED`, `POLICY_DEPRIORITIZED` | medium | medium | yes |
| `viewport_exhausted_eval` | state metadata | low | high | yes |
| `bottom_strip_policy` | `BOTTOM_STRIP_DEFERRED`, `POLICY_DEPRIORITIZED` | low | high | yes |
| `LIFECYCLE kind='local_tab'` | `SELECTED` metadata, `VISITED` metadata | medium | high | yes |
| `focus_context_mismatch` | `FOCUS_CONTEXT_MISMATCH` | low | high | yes |
| `focus_realign` | `FOCUS_REALIGN_ATTEMPT` | low | high | yes |
| `focus_force_realign` | `FOCUS_REALIGN_ATTEMPT` | low | high | yes |
| `focus_realign_success` | `FOCUS_REALIGN_SUCCESS` | low | high | yes |
| `focus_force_realign_success` | `FOCUS_REALIGN_SUCCESS` | low | high | yes |
| `focus_realign_fail` | `FOCUS_REALIGN_FAIL` | low | high | yes |
| `focus_force_realign_fail` | `FOCUS_REALIGN_FAIL` | low | high | yes |
| `focus_realign_record` | `FOCUS_REALIGN_SUCCESS`, `VISITED` evidence | low | high | yes |
| `focus_realign_skip` | `FOCUS_REALIGN_FAIL` metadata | medium | medium | no |
| `local_tab_gate` | `LOCAL_TAB_TRANSITION_ATTEMPT`, `POLICY_DEPRIORITIZED` | medium | medium | yes |
| `local_tab_progression` | `LOCAL_TAB_TRANSITION_ATTEMPT` | low | high | yes |
| `local_tab_state_write kind='pending'` | `LOCAL_TAB_TRANSITION_ATTEMPT` | low | high | yes |
| `local_tab_pending_eval` | `STATE_RECOVERY_ATTEMPT` | medium | medium | yes |
| `local_tab_commit_match` | `STATE_RECOVERY_SUCCESS` metadata | medium | medium | yes |
| `local_tab_state_write kind='committed'` | `LOCAL_TAB_TRANSITION_SUCCESS`, `STATE_RECOVERY_SUCCESS` | low | high | yes |
| `local_tab_commit` | `LOCAL_TAB_TRANSITION_SUCCESS`, `VISITED` | low | high | yes |
| `local_tab_recover` | `STATE_RECOVERY_ATTEMPT`, `STATE_RECOVERY_SUCCESS` | low | high | yes |
| `local_tab_recover_fail` | `STATE_RECOVERY_FAIL` | low | high | yes |
| `local_tab_target_activate` | `ACTIVATION_ATTEMPT` | low | high | yes |
| `local_tab_target_activate_success` | `ACTIVATION_SUCCESS` | low | high | yes |
| `local_tab_target_activate_no_match` | `ACTIVATION_FAIL` | low | high | yes |
| `local_tab_target_activate_fail` | `ACTIVATION_FAIL` | low | high | yes |
| `local_tab_target_activate_skip` | `ACTIVATION_FAIL` metadata | low | medium | yes |
| `local_tab_force_navigation_resolved` | `ACTIVATION_SUCCESS`, `LOCAL_TAB_TRANSITION_SUCCESS` | low | high | yes |
| `local_tab_pending_clear` | `STATE_RECOVERY_FAIL`, `LOCAL_TAB_TRANSITION_FAIL` | medium | medium | yes |
| `last_scroll_fallback_eval` | `STATE_RECOVERY_ATTEMPT` metadata | medium | medium | no |
| `last_scroll_fallback_result` | `STATE_RECOVERY_SUCCESS` or `STATE_RECOVERY_FAIL` metadata | medium | medium | no |
| `STEP END` | `VISITED` | low | high | yes |
| `.xlsx visible_label` | `VISITED` | low | high | yes |
| `row_filter` | `CANDIDATE_DISCARDED` metadata | medium | medium | no |

## 10. MVP Boundary

Included in MVP:

- reconstruct normalized events from existing XML candidates, logs, and persisted rows
- create candidate ledger by folding normalized events
- emit scenario metrics and root-cause summaries
- derive terminal `MISSED` events from discovered-but-unvisited ledger rows
- support first-pass attribution for activation, realign, local-tab, bottom-strip, policy, discard, recovery, and unknown cases

Excluded from MVP:

- runner behavior changes
- V4 shadow verdict changes
- coverage threshold tuning
- matching policy changes
- eligibility policy changes
- taxonomy expansion
- new runtime instrumentation requirements
- production verdict integration

MVP quality bar:

- every `MISSED` candidate should either have a root cause or be explicitly counted under `UNKNOWN`
- `UNKNOWN` should be visible as a metric, not hidden inside generic review text

## 11. Open Questions

1. Should candidate identity prefer merged XML candidates or raw node candidates for repeated labels?

MVP answer:

- use merged candidates for first pass, preserve raw node evidence in `raw_payload` and debug fields

2. Should `POLICY_DEPRIORITIZED` count as a miss?

MVP answer:

- not by itself
- only terminal discovered-but-unvisited candidates can receive it as root cause

3. Should `FOCUS_CONTEXT_MISMATCH` always become `FOCUS_DRIFT`?

MVP answer:

- no
- it becomes terminal `FOCUS_DRIFT` only when no successful realign or stronger root cause follows

4. Should `REALIGN_FAIL` outrank `FOCUS_DRIFT`?

MVP answer:

- yes
- realign failure is the more specific mechanism

5. Should `BOTTOM_STRIP_MISS` outrank `LOCAL_TAB_MISS`?

MVP answer:

- yes
- bottom strip identifies the specific local-tab surface and policy context

6. Is `VISITED` based on persisted row or committed local-tab state?

MVP answer:

- both can emit `VISITED`
- persisted row evidence is primary for content
- local-tab commit evidence is primary for local-tab state

## 12. Code Change Status

No code changes are included in this phase.

This document defines schema only.

## 13. Test Status

`pytest` was not run.

Reason:

- this phase is documentation-only schema design
- no code was modified

## 14. Git Status

Expected git status after this document is created:

```text
?? docs/design/audit-v4-phase-closure.md
?? docs/design/audit-v5-phase5a-normalized-event-schema.md
?? docs/design/audit-v5-phase5a-traversal-event-inventory.md
?? docs/design/audit-v5-traversal-engine-audit.md
```

No `git add`, `git commit`, or branch operation was performed.
