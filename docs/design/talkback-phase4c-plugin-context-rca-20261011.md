# Phase 4C generic plugin context recovery

## Proven TV blocker

Previous immutable evidence: `../phase4c_generalized_20261011/acceptance`.
The TV normal production entry succeeded with `success_verified / plugin_open_verified`.
The pre-loop anchor was actual accessibility focus. Every current capture observed
SmartThings `com.samsung.android.oneconnect.webplugin.WebPluginActivity`, no selected
bottom tab, and a real body with `GenericMainPageView`, `paneContainer`,
`SwitchCapabilityCardView`, `AudioVolumeMuteCardView`, `TvChannelCapabilityCardView`,
and configured device controls. Native post-open diagnostics had `verify_hit=false`:
the visible body lacked the configured TV text marker. Production accepted its
existing structural landing evidence; the context adapter did not consume that
post-open result for unregistered plugins.

`phase3_context._PLUGIN_IDS` described Food, Family, Find and Smoke only. The unknown
plugin branch discarded current entry evidence and returned `NO_VERIFIED_CONTEXT_CONTRACT`.
Phase 4 consequently blocked all ten controlled actions with `CONTEXT_INSUFFICIENT`.
Normal fallback moved focus and reconciled ten new visits. There was no entry,
transport, identity, or visit-accounting failure.

Classification: **POST_OPEN_EVIDENCE_NOT_PROPAGATED** and
**CONTEXT_ADAPTER_REQUIRES_WRONG_SIGNAL** (limited profile registration).
The configured TV body text remained incomplete; it has not been weakened.

## Pipeline

- Entry/post-open: `collection_flow.open_scenario`, `_matches_post_open_verify`,
  `_collect_post_open_identity_snapshot`, existing `last_start_open_summary`.
- Main-loop boundary: `collection_flow._main_loop_phase` after successful
  `_run_start_pipeline`; actual `verified_pre_loop_anchor`.
- Entry proof: `phase3_context.phase3_entry_evidence_from_main_loop`.
- Generic post-open projection: `plugin_context_contract.plugin_context_evidence`.
- Current observation: `state_fingerprint_diagnostic.capture_observation`.
- Context adapter: `phase3_context.resolve_phase3_context` delegates to
  `plugin_context_contract.generic_plugin_context` for configured new screens.
- State: `discovery_candidates.build_discovery_snapshot`,
  `state_fingerprint_diagnostic.build_state_observation`, and `StateRegistry.observe`
  consume the context result; PARTIAL does not invent a resolved plugin state.
- Authority: `phase4b_authority.execution_gate` retains independent current
  target, focus, geometry, lifetime, request, recovery and history checks.

## Generic evidence contract v1

Required proof fields: schema/source, scenario/run owner, navigation epoch,
configured entry-contract digest/destination identity, capture ID and ordered
timestamps, native successful post-open summary, actual pre-loop accessibility
focus, observed package/activity/source, observed body resource IDs.

The config supplies destination markers; there is no TV branch. Current evidence
must agree with its owned entry component. A different package/activity, root
activity, selected tab, or independently supported different destination rejects
context. Shared words such as History cannot prove a different destination:
another body matcher must also match its configured entry title/alias, or a
strict existing component/resource profile must match.

Tiers:

| Tier | Evidence | Action authority |
|---|---|---|
| VERIFIED_PLUGIN_CONTEXT | Owned normal entry, successful post-open, current bound OS component, shared body resource and configured destination body | Existing full candidate gate |
| PARTIAL_PLUGIN_CONTEXT | Owned normal entry/post-open and current bound component, incomplete noncontradictory body | Independently proven structural targets only |
| UNRESOLVED_CONTEXT | Missing/stale ownership, epoch, proof or current component | Production fallback |
| CONTRADICTORY_CONTEXT | Conflicting current destination/window/navigation evidence | Controlled execution denied |

PARTIAL_PLUGIN_CONTEXT is exposed as `context_tier`; the existing status string
`PARTIAL_CONTEXT` remains compatible with Phase 3/4 contracts. Explicit
`plugin_context_required=True` still requires VERIFIED_PLUGIN_CONTEXT.

## Freshness and ownership

Every scenario creates a fresh main-loop run ID and entry epoch. The proof must
match the current scenario, run, epoch and entry-contract digest. A process-local
observer invalidates the epoch on existing click/tap, Back/Home or activity
launch attempts, including failed attempts. Focus and scroll do not invalidate
the epoch. Wrappers forward original arguments/results and restore the client
on success or exception. No navigation action or visit is created by observers.
Only a new successful production entry may establish a new proof.

Existing Phase 3 v1 historical replay contracts remain supported. Generalized
Phase 4C explicitly supplies the new proof and must satisfy the new ownership
checks; default production and Phase 4B remain unchanged.

## Offline recovery

`phase4c_context_recovery_20261011/context_replay.py` reconstructs the native
post-open summary from the original successful entry log, verifies the original
actual anchor, and creates derived proof copies without changing original files.
All 57 pre-stop recommendations and gates replay exactly. Non-TV decisions remain
unchanged with the generic contract. TV is correctly **PARTIAL_CONTEXT**, with
10/10 hypothetical safe structural execution gates. These are offline decisions,
not device actions or visit credit. Source hashes remain unchanged.

Eight-plugin accepted replay keeps missing activity/post-open evidence explicit:
it does not manufacture VERIFIED context from an accepted terminal alone.
The current live captures provide stronger proof for Find, Smoke and TV.

## Recovery acceptance

The first setup attempt found the Android keyguard (`Emergency call`, SystemUI),
before any scenario subprocess or main-loop step started. Its logs and precheck
are preserved in `phase4c_context_recovery_20261011/tv_only`. A missing selected
tab exposed a precondition-reporting `None.get` error. The report now reuses the
already guarded `tab_verified` value; two regression cases prove that locked or
missing-tab observations produce `start_state_valid=false` without crashing.
This does not weaken the clean-start requirement. TV validation uses a fresh
`tv_validation` artifact directory after the user unlocks the device.

Results and closure are recorded in the main Phase 4C design document and
`../phase4c_context_recovery_20261011/final_report.json` after TV-only validation
and the requested B → C → D sequence. Phase 5 is outside this task.

## Final recovery result

TV-only passed all 10 controlled focus steps with correctly PARTIAL_CONTEXT,
zero fallback and zero hard lifecycle/transport gates. Stage B passed all four
plugins. Energy passed; Food then rejected the final-row focus audit, stopping
the sequence before Family Care and Camera. The generic TV context blocker is
resolved; overall recovery remains PHASE4_PLUGIN_CONTEXT_RECOVERY_REJECT.

The new blocker is proven from Food step 11: the controlled target matched actual
accessibility focus and its native reconciliation recorded a visit. Later normal
production V2 recovery replaced the persisted row with a different focused node,
without the legacy reconciliation fields. The acceptance observer cannot bind
the final actor to its outcome. The FALSE_FOCUS_MOVEMENT flag remains 1; actual
false movement is not proven. Original artifacts and verdict are not rewritten.
See `food_actor_audit_rca.json` for request IDs, native events, final focus,
three recovery attempts and original hashes. Audit/new native visit counts are
17/18; native unique visits are 20. A separate actor-aware reconciliation/audit
recovery is required before new staged acceptance and closure.

Final full Python: 3708 passed, 1 skipped, 0 failures. All focused/replay gates
passed, including 57 rebuilt-candidate semantic comparisons. Helper unchanged;
prior 408-pass suite retained. Current live scroll proved three request-correlated
Food moves. Find/Energy use conservative fallback after production navigation
invalidates the epoch; no stale proof is retained or forcibly refreshed.

The main design document records scenario metrics, scope, coverage limits,
scroll/saturation evidence and closure. `final_report.json` is the complete
machine-readable verdict. PHASE4_COMPLETE=NO, READY_FOR_PHASE5=NO; Phase 5 not
implemented; default production traversal OFF. Integration/main/original Phase 3
refs unchanged. Local justified fixes preserved; no new commit, push or merge.
