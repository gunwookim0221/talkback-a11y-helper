# Phase 4C action audit linkage recovery

## Source and scope

Worktree: integration/phase3-current-main. Start/origin integration
`a4795a14501f7c6956e1bfe45ee1dd87f687b2b6`; main/origin
`6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`; original Phase 3
`fb4d01c489a0b3d56883e074771eb823c453d4f2`. Existing local Phase 4C changes
are preserved. No pull, main modification or Phase 5 implementation.

The new surface is evidence reading, provenance serialization and acceptance
validation. Planner ranking/authority, transport dispatch, candidate/focus
identity, recovery choice, scroll, visit/attempt accounting and traversal
termination are unchanged. The existing production final row still represents
the final recovered outcome. Audit linkage creates no visit and does not replace
any old outcome field used by the traversal budget/session.

## Exact Food step 11 RCA

Immutable prior root: `../phase4c_context_recovery_20261011/`. Its verdict remains
PHASE4_PLUGIN_CONTEXT_RECOVERY_REJECT. The original mismatch is retained.
`food_actor_audit_rca.json` contains original hashes and the native recovery log.

The controlled primary TARGET_FOCUS_COMMIT request
`2e989e3a29364a4b842db8b27491a6b2` targeted a Button at 864,1567,954,1660.
Its correlated Helper result and actual accessibility focus agree. Native event
`evt_69c7368b26cb40beb0387eb5e50e459e` records CONFIRMED_MOVED, EXACT mapping,
physical_visit_confirmed=true and RECORDED.

Subsequent normal production V2 recovery makes three FOCUS_IN_BOUNDS attempts.
The first two remain INDETERMINATE; the third production gate confirms movement
and a visit. Its request is `e982c50a2c874b839beaacf05620e7d5`, transaction
`tx_f6a455776895418ca671a4c6b329cd2b`. The final accessibility-focused View is
at 90,883,501,1033; final GET_FOCUS request `34ec6d03`.

`_main_loop_phase` assigns `row = recovery_outcome.row`. That new row does not
contain the earlier legacy focus_reconciliation_evidence/status fields.
`observed_persist` copied the final row, so the acceptance checker compared its
valid actual identity against an empty legacy reconciliation identity. Native
primary and recovery events were never erased from the append-only journal.
The missing part was their relationship to the final row and controlling actor.

ORIGINAL_ACTION_EVIDENCE_EXISTED=YES
RECONCILIATION_EVIDENCE_EXISTED=YES
RECOVERY_REPLACED_ROW=YES
PROVENANCE_LINK_LOST=YES
ROOT_CAUSE_PROVEN=YES
FAILURE_CLASSIFICATION=AUDIT_ROW_REPLACEMENT_ONLY+PROVENANCE_LINKAGE_MISSING
ACTUAL_WRONG_FOCUS_MOVEMENT_PROVEN=NO

## Pipeline

| Boundary | Existing function / new observational reader |
|---|---|
| Planner/gate | tools.phase4b_controlled_smoke.observed_step; plan_shadow; execution_gate |
| Dispatch | phase4b_execution.controlled_collect; collection_flow._maybe_realign_focus_to_representative |
| Request/ACK | A11yAdbClient._evidence_action_sent, _evidence_helper_ack; correlated_result; _read_recovery_action_ack |
| Focus | collect_focus_step; collection_flow._apply_focus_reconciliation |
| Recovery | RecoveryExecutor.execute; RecoveryCoordinator.run; _attempt_identity_recovery |
| Production recovery outcome | _resolve_traversal_evidence_decision; native PRODUCTION_TRAVERSAL_GATE_DECIDED and RECOVERY_CANDIDATE_RESULT |
| Final replacement | collection_flow._main_loop_phase: row = recovery_outcome.row |
| Persistence | _apply_row_persistence_phase; explicit harness observed_persist |
| New linkage | EvidenceRuntime.events_for_step; action_provenance.build_action_chain |
| Acceptance | action_chain_failures; final_actor_proven; generalized validate_scenario |

## Ownership and immutable evidence

STEP_ACTION_ID is deterministic JSON of schema, existing native run ID, existing
scenario transaction ID, scenario ID and integer traversal step. Existing native
transaction/action/request IDs remain unchanged. Each native primary or recovery
transaction links under that step; explicit scroll transport uses its exact
SCROLL_RESULT request. Verification observations are recorded separately.

`events_for_step` reads only the current native scenario transaction and this
step or its `step:recovery:number` keys. The chain snapshots existing native
ACTION_SENT, HELPER_ACK_RECEIVED, POST_FOCUS_OBSERVED, FOCUS_RECONCILIATION,
production gate, recovery result and transaction-close events. It also retains
planner/gate/target and primary production verification evidence.

`phase4c_step_action_evidence.jsonl` appends the complete immutable chain.
The production final row adds only step_action_id and step_action_provenance
(file reference, schema, ID and SHA256). The existing row is not replaced with
the primary row. Final focus, outcome and recovery actor remain separate from
primary reconciliation. No native transaction is reassigned or retrospectively
credited. Native evidence and the prior rejection are not rewritten.

This collection is enabled only in the explicit generalized traversal harness.
Default normal production smart traversal stays OFF. The native runtime gains
only a read method; regular production execution does not call the new collector.

## Acceptance contract

Every dispatched native request needs its own transaction-bound ACTION_SENT and
ACK. Request IDs and available run/scenario/transaction correlation must agree;
duplicate request ownership, stale results and cross-step/scenario references
reject. Primary and unsuccessful recovery evidence remains visible.

For a recovered final actor, acceptance requires its own exact request/ACK,
fresh runner POST_FOCUS_OBSERVED with actual accessibility focus, class/identity
agreement, a same-transaction production gate proving physical movement and
visited=true, and strong RECOVERY_CANDIDATE_RESULT. Primary target metadata,
movement preview and request predicates retain all existing checks. Missing
legacy fields are accepted only with this complete separate actor proof, never
merely because recovery was attempted. A changed chain hash or missing sidecar
rejects. Input focus alone cannot complete the recovery proof.

Primary outcomes use existing production row identity fallback precedence and
retain raw focus separately. This preserves accepted Energy rows where native
resource ID is absent and the coherent production row carries a resource fallback;
the audit does not change identity or award visits. Captured row credits and
native production gate decisions are reported separately.

## Offline results and pending live gates

Exact fixture: tests/fixtures/phase4c_food_step11_audit.json, derived from preserved
original trace/native events. Old acceptance mismatch is reproduced. New chain
preserves primary and all three recoveries and proves the final native actor.
All 67 previous B/C step chains validate; all 47 pre-Food planner/gate/context
decisions, plus the 20 Food decisions, replay exactly. Original hashes unchanged.

The generic test matrix covers success/no recovery, primary failure/recovery,
ACK failure with real movement, ambiguity, row replacement, multiple requests,
stale ownership, next step/scenario isolation, production fallback, immutable
snapshots, hash tampering and false focus/visit proof. Current focused result:
52 passed; broader audit/recovery/evidence focused group: 87 passed.

Live acceptance will use normal entry and a fresh output root: Food-only 20;
then shared-audit Stage B sanity (all four, 10 each), complete Stage C
(Energy10/Food20/Family10), then Camera20 only after Stage C passes. No automatic
retry after a true hard failure. Full test/replay/frozen-source gates precede live.
Final results and closure will be appended after these gates complete.

## Completed live acceptance and closure

# Food audit linkage recovery — closure retry

The previous rejection sections above remain historical. Original Food step 11
and its mismatch are preserved byte for byte. This retry changes only generic
audit/provenance/recovery correlation relative to that rejected source; the
accumulated justified Phase 4C context/traversal work is also included for
integration publication. No Phase 5 implementation or main merge is performed.

## Proven RCA and ownership contract

Food step 11's primary target/request and native production reconciliation were
valid. Later normal production V2 recovery replaced the final row. Its omitted
legacy reconciliation fields disconnected primary evidence from the final
recovery actor. The classification is AUDIT_ROW_REPLACEMENT_ONLY plus
PROVENANCE_LINKAGE_MISSING; actual incorrect physical focus movement was not
proven. See `talkback-phase4c-audit-linkage-rca-20261011.md` for the exact IDs,
events, pipeline and strict acceptance conditions.

The deterministic STEP_ACTION_ID composes schema, existing run/scenario
transaction, scenario ID and traversal step. Primary requests, native focus
reconciliation, recovery requests/results and verification observations remain
separate actors under that owner. Append-only step evidence snapshots the native
journal. The final row retains the actual recovered outcome and adds only an ID
and hash/reference to the immutable chain. It does not restore the first row or
overwrite final outcome/visit fields. Audit linkage has no visit authority.

The checker keeps all primary target, predicate, actual movement and exact
request checks. A later actor requires its own native request/ACK, actual
accessibility focus observation, production physical-move/visit gate and strong
recovery result in the same transaction. Missing, stale, mismatched or cross-step/
scenario evidence rejects. The sidecar must agree exactly with its hash/reference.
No Food special case or acceptance flag override is used.

Planner ranking/authority, focus commands, candidate/focus identity, fallback and
recovery selection, scroll, visit accounting, starvation and termination are
unchanged by this audit repair. Critical pre-retry source hashes and the original
EvidenceRuntime AST (excluding the new read-only step reader) are unchanged.
Default production Smart Traversal stays OFF.

## Offline gates

- Generic audit/recovery/evidence focused: 87 passed (43 new provenance cases).
- Phase 3 focused: 58 passed; production focused: 442 passed;
  Phase 4 focused: 217 passed.
- Full Python: **3751 passed, 1 skipped, 0 failed**.
- Helper source unchanged (47 hashes); prior accepted 408-pass result retained;
  no new Helper test run is claimed.
- Historical Phase 3: 16 exact; accepted Phase 4A: 30 exact;
  Phase 4B: 30 exact; accepted six-scenario baseline gates pass.
- All 47 pre-Food decisions and all 67 prior B/C decisions replay exactly.
  Existing planner/context/gate and production identity semantics are preserved.
- Exact Food step 11 fixture reproduces the old mismatch and proves a new
  complete chain including all three original recovery attempts and final actor.
- All 67 reconstructed native chains validate; originals remain unchanged.

## Live retry

Serial R3CX40QFDBP; locale en-US unchanged. TalkBack PID 19549 and Helper PID
18024 remain stable. All scenarios use normal production entry, validated clean
start, frozen tested source and the corrected hard-stop monitor. No Full32,
manual correction, automatic scenario retry or locale change occurred.
Shared audit impact justified a full Stage B rerun. Stage C followed Food-only.
Family Care rejected at the completed 10-step acceptance boundary because no
controlled action executed. Camera was not run, as required by the Stage C gate.

| Run / scenario | Context counts | Steps | Controlled focus / scroll | Fallback | Native primary visits / recovery visits | Complete chains | Result |
|---|---|---:|---:|---:|---:|---:|---|
| food_validation / life_food_plugin | PARTIAL_CONTEXT: 20 | 20 | 17 / 3 | 0 | 18 / 1 | 20 | PASS |
| stage_b / life_find_plugin | VERIFIED_PLUGIN_CONTEXT: 1, UNRESOLVED_CONTEXT: 9 | 10 | 1 / 0 | 9 | 8 / 0 | 10 | PASS |
| stage_b / device_smoke_sensor_plugin | VERIFIED_PLUGIN_CONTEXT: 7 | 7 | 7 / 0 | 0 | 7 / 0 | 7 | PASS |
| stage_b / device_tv_plugin | PARTIAL_CONTEXT: 10 | 10 | 10 / 0 | 0 | 10 / 0 | 10 | PASS |
| stage_b / device_washer_plugin | PARTIAL_CONTEXT: 10 | 10 | 10 / 0 | 0 | 10 / 0 | 10 | PASS |
| stage_c / life_energy_plugin | VERIFIED_PLUGIN_CONTEXT: 1, UNRESOLVED_CONTEXT: 9 | 10 | 1 / 0 | 9 | 10 / 0 | 10 | PASS |
| stage_c / life_food_plugin | PARTIAL_CONTEXT: 20 | 20 | 17 / 3 | 0 | 17 / 2 | 20 | PASS |
| stage_c / life_family_care_plugin | VERIFIED_PLUGIN_CONTEXT: 1, UNRESOLVED_CONTEXT: 9 | 10 | 0 / 0 | 10 | 10 / 0 | 10 | REJECT |

Food-only experienced real later production recovery; its primary and recovery
requests/results remain linked. Stage C Food also retains its later recovery
attempts. Per-step actor IDs/results are in each *_audit_metrics.json and the
immutable phase4c_step_action_evidence.jsonl. Native primary RECORDED events,
native strong recovery visit events and copied final-row credits are reported
separately. Their counts are not silently normalized or used to award visits.

The standalone Food monitor/scenario passed before a wrapper summary reader
raised a CP949/UTF8 decoding exception. The artifact driver was corrected to
UTF8; Food was not rerun. The first offline replay used an unaccepted Phase 4A
input and failed its input comparison; the corrected accepted input passes.
Both original diagnostic outputs remain available.

## Scroll proof and coverage

| Run | Step | Exact Helper request | New candidates |
|---|---:|---|---:|
| food_validation | 8 | c4cb3266 | 4 |
| food_validation | 13 | b7fcca12 | 3 |
| food_validation | 17 | 2b4c51cf | 5 |
| stage_c | 6 | 2277b515 | 6 |
| stage_c | 13 | 99f73c89 | 5 |
| stage_c | 19 | 85fa684d | 4 |

Every listed scroll has the exact Helper-owned PID18024 SCROLL_RESULT,
matching request/ACK, explicit target, fresh after-scroll refresh and hashed
before/after viewport captures in scroll_validation.json. Resolved state IDs
remain null in PARTIAL_CONTEXT; the evidence does not invent plugin state IDs.

| Scenario | Bounded comparison | Native primary visits | Accepted baseline prefix | Terminal status / reason |
|---|---|---:|---:|---|
| life_find_plugin | EQUIVALENT | 8 | 8 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_smoke_sensor_plugin | IMPROVED | 7 | 6 | COMPLETED / plugin_boundary_global_nav |
| device_tv_plugin | EQUIVALENT | 10 | 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_washer_plugin | EQUIVALENT | 10 | 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_energy_plugin | EQUIVALENT | 10 | 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_food_plugin | ACCEPTABLE_VARIANCE | 17 | 19 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| life_family_care_plugin | ACCEPTABLE_VARIANCE | 10 | 10 | INCOMPLETE_SAFETY_LIMIT / safety_limit |
| device_camera_plugin | INSUFFICIENT_EVIDENCE | — | — | — / — |

These are bounded live comparisons, not Full32 or complete coverage equivalence.
Food/Family content and state can vary; raw counts across different complex
states are not direct coverage claims. Family is observed ACTIVE (Active now).
Smoke's normal global-navigation boundary
can end before its cap. Find/Energy/Family context can become unresolved after
existing navigation invalidates the entry epoch, leading to bounded production
fallback. Partial context remains explicit for safe structural plugin targets.
Camera has no new evidence in this retry; coverage-first production termination
is unchanged. Historical Stage A roots are
carried through semantic replay, not represented as new live runs.

## Final closure

OVERALL_VERDICT=PHASE4_AUDIT_LINKAGE_RECOVERY_REJECT
PHASE4_COMPLETE=NO
READY_FOR_PHASE5=NO
PHASE5_IMPLEMENTED=NO
DEFAULT_PRODUCTION_SMART_TRAVERSAL=OFF

All six audit, six execution-safety and ten lifecycle/transport hard gates are
zero across the 97 executed steps. The Food linkage repair passes replay and both
live Food runs, including actual later recovery. Overall closure nevertheless
rejects: Family Care executed zero controlled actions. Its first recommendation
snapshot has state_id=null; immediate fresh snapshot has
phase4b-controlled-smoke:state:00000002 and different fingerprint/viewport.
The unchanged authority gate denies STATE_OR_SUBSTATE_CHANGED. Step2 denies
RECOVERY_CONFLICT; steps3-10 deny CONTEXT_INSUFFICIENT after the existing
navigation epoch is invalidated. Ten safe production fallbacks confirm actual
focus and native visits. They do not demonstrate generalized controlled execution.
family_controlled_execution_blocker.json retains this separate new blocker.

CONTROLLED_EXECUTION_REGRESSION=YES is scoped to missing acceptance evidence,
not unsafe targeting or a proven audit-induced production behavior change.
COVERAGE_REGRESSION=NO means no proven material observed loss; Camera has
INSUFFICIENT_EVIDENCE and representative closure remains incomplete.
No authority/context policy is relaxed and no new retry is attempted.
Generalized traversal remains bounded and opt-in. Valid local Phase 4C changes
are preserved; no commit, push or main merge occurs under the rejection policy.
Phase 4 remains incomplete and Phase 5 readiness is NO. Phase 5 is not implemented.

Source start/origin integration: a4795a14501f7c6956e1bfe45ee1dd87f687b2b6.
Main/origin remain 6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee; original Phase 3
remains fb4d01c489a0b3d56883e074771eb823c453d4f2. Integration HEAD and origin
remain the starting commit; no publication occurs for this rejection.

Evidence root: ../phase4c_audit_recovery_20261011/. See final_report.json/.txt,
coverage_comparison.json, source/test/frozen hashes, production_behavior_proof.json,
corrected replay summaries, food_step11_old_new.json, scroll_validation.json,
per-run audit metrics, original traces, native journals, acceptance files and
hard-stop monitor results. Prior rejection artifacts remain unchanged.
