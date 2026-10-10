# Phase 3 and accepted current main consistency — 2026-10-11

## Scope and source gate

This is an isolated integration audit. Production main, the original Phase 3 branch, Camera termination, Family Care production logic and Phase 4 policy are preserved. No Full32 was run.

- Accepted main and origin/main: `6cb2fe21c4006caa1d188a97a69cf2a6409ee9ee`.
- Original Phase 3 local and remote branch: `feature/phase3c-transition-stability-closure`.
- Original Phase 3 tip: `fb4d01c489a0b3d56883e074771eb823c453d4f2`.
- Integration branch: `integration/phase3-current-main`.
- Separate worktree: `out/phase3_current_main_20261011/source`.
- Merge-base: `f89836a36ed12b2749f7f8203ead0d8dcebd4a5d` (Phase 3B).
- `git fetch --all --prune` succeeded after sandbox escalation for `.git/FETCH_HEAD`.
- Normal `git merge --no-commit main` succeeded. Conflict count **0**; conflict files **NONE**. No mechanical, semantic or architectural merge conflicts.

## Lineage and implemented intent

Ancestry is Phase 1 `4c829536` → Phase 2 `ec36a2e8` → Phase 3A `f2427770` → Phase 3B `f89836a3` → Phase 3C/3D `fb4d01c4`. The only local/remote feature refs containing the last commit are the branch named above. Its tip is exactly that commit; there is no guessed successor.

Source of truth: `phase1-state-auto-discovery-gap-analysis.md`, Phase 2 fingerprint/equality/registry closure docs, `phase3a-auto-discovery-integration.md`, `phase3b-transition-observation-contract.md`, and **§26** of `phase3-state-discovery-transition-closure.md`. §26 supersedes earlier Home blocker/readiness sections. The final original Phase 3D result closed logical Home identity and allowed Phase 4 with explicit camera-event and focus-effect limitations.

| Aspect | Existing Phase 3 contract |
|---|---|
| State representation | Immutable fingerprint plus versioned secondary observation; logical root, viewport, overlay and transient evidence remain separate. |
| Discovery | Immutable snapshot of existing observed candidates; no automatic activation, action choice or physical visit credit. |
| Transition | Caller-controlled `prepare → execute externally → complete`; deterministic occurrence/type identity, exact source candidate binding, evidence and safe ambiguity. |
| Semantic substate | Camera card condition is a child observation of verified Home. Exact evidence tokens may be projected out of logical root comparison; full-screen/context-significant overlays stay in root identity. Event type remains UNKNOWN without a trusted typed producer. |
| State identity | Registry namespace and persisted allocation; incomplete/coarse-collision/context-unknown observations remain unbound. No forced state merge. Legacy documents retain bytes/checksums and matching provenance. |
| Focus | Strict actual accessibility focus and observed movement; ACK is separate evidence. Input focus alone is insufficient. Actual fields can override representative focus. |
| Visits | Discovery and transition diagnostics always credit zero. Existing production ledger remains authoritative. |
| Candidate identity | Logical state scope + action kind + positional resource ID/exact bounds. Untargeted FOCUS_NEXT is a singleton operation, not a predicted target. |
| Scroll | Axis, container and movement evidence; verified observation-linked continuity can preserve root identity. Unverified continuity is not imported optimistically. |
| Starvation | No new Phase 3 scheduler. Current planner-valid never-attempted production candidate behavior is preserved. |
| Termination | No Phase 3 execution termination owner. Existing completeness and incomplete terminal reasons remain unchanged. |
| Entry boundary | Existing scenario/plugin selection and stable entry precede optional Phase 3 analysis. Diagnostics do not replace entry. |

## Main changes since divergence

`git log f89836a..main` contains 20 production commits. Production runtime, config, Helper and frontend in the merged tree are identical to accepted main; Phase 3 differences are its state/discovery/transition modules, tests, tools and docs.

| Production change | Interaction classification | Evidence / disposition |
|---|---|---|
| Service-preserving hierarchy acquisition | DIRECT_PHASE3_INTERACTION | Phase 3 capture still called suppressing UIAutomator; compatibility adaptation below. |
| Avoid suppressing UIAutomator dump | DIRECT_PHASE3_INTERACTION | Main `_run` does not intercept arbitrary shell dump commands; legacy diagnostic collectors needed explicit migration. |
| TalkBack lifecycle stabilization | POTENTIAL_PHASE3_INTERACTION | Captures must preserve service lifecycle; no Phase 3 runtime restart integration. |
| Helper DUMP_HIERARCHY | DIRECT_PHASE3_INTERACTION | Existing service API and XML semantic adapter reused. |
| Targeted focus semantics | DIRECT_PHASE3_INTERACTION | Shared `focus_reconciliation`, positional identity and strict focus evidence. |
| Actual accessibility focus versus ACK | DIRECT_PHASE3_INTERACTION | Transition actual state/viewport/focus precedence retained. |
| False-focus fallback | DIRECT_PHASE3_INTERACTION | Shared strict focus gate; discovery/transition have no visit writer. |
| Starvation handling | NO_PHASE3_INTERACTION | Phase 3 remains observational; merged production fairness unchanged. |
| SMART_NEXT behavior | DIRECT_PHASE3_INTERACTION | FOCUS_NEXT remains untargeted; no target guarantees added. |
| SMART_NEXT correlation | POTENTIAL_PHASE3_INTERACTION | Shared Helper bridge/transport; Phase 3 does not implement its own transport. |
| Family parent/child snapshot cache | POTENTIAL_PHASE3_INTERACTION | Diagnostic consumers depend on unchanged metadata; 404 Helper tests cover cache/equivalence. |
| Menu tab_context entry | NO_PHASE3_INTERACTION | Production entry module identical to main. |
| Air Care targeted entry | NO_PHASE3_INTERACTION | Production entry module identical to main. |
| Energy targeted entry | NO_PHASE3_INTERACTION | Production entry module identical to main. |
| Find targeted entry | NO_PHASE3_INTERACTION | Production entry module identical to main; bounded smoke exercises it. |
| English locale stabilization | POTENTIAL_PHASE3_INTERACTION | Shared label/context normalization; no locale switch performed. |
| Devices-specific anchor | NO_PHASE3_INTERACTION | Production entry retained. |
| Horizontal All devices recovery | NO_PHASE3_INTERACTION | Production entry retained; smoke exercises smoke-sensor entry. |
| Terminal hard-stop monitor | POTENTIAL_PHASE3_INTERACTION | Current monitor reused with exact request ownership/correlation and fresh logs. |

## Compatibility resolution

One real compatibility issue was proven statically: `tools/state_fingerprint_diagnostic.capture_observation` used `client._run(['shell','uiautomator','dump',...])`. Main's `_run` delegates directly to ADB, so this diagnostic path could reintroduce suppression despite the reliable production foundation.

Changes are confined to diagnostic acquisition and its tests:

1. `capture_observation` calls current `client.dump_hierarchy` and `service_hierarchy_to_xml`, retaining the existing observation normalization. Selected provenance identifies the service hierarchy. Accessibility focus is preserved separately from input focus. Hierarchy failure retains partial Helper evidence with an explicit note; no UIAutomator fallback.
2. `camera_overlay_probe.EventProbe.capture` brackets the service hierarchy API for the existing bounded screenshot timing capture. It uses the captured hierarchy, not a stale device XML file. Camera termination and semantic extraction are unchanged.
3. `camera_alert_diagnostic.capture` uses the service XML adapter. The unsupported compressed UIAutomator comparison is explicitly unavailable; it is not represented as equivalent service evidence.
4. The old collector transport mock is **OUTDATED_TEST**: requiring UIAutomator would violate accepted main's lifecycle contract. Its flag/unknown/context expectations remain, with service provenance updated. New tests reject UIAutomator fallback and distinguish actual accessibility focus from input focus.

No Phase 3 state/discovery/substate redesign, production focus change, Family cache change or traversal strategy was necessary. No `ours`/`theirs` conflict selection was used.

## Semantic-contract matrix

PASS means preserved and supported by source/tests. Phase 3 observation itself does not prove production-wide coverage.

| Contract | Result | Source / evidence |
|---|---|---|
| 01 Same resource ID, distinct bounds/instances | PASS | `traversal_reliability.instance_id`, discovery `_target`, identity/discovery tests. |
| 02 False focus fallback earns no visit | PASS | `focus_instance`, `focus_reconciliation`; discovery/transition fixed zero visit credit. |
| 03 Input focus differs from accessibility focus | PASS | Strict focus helpers; new service capture flag test. |
| 04 Failed ACK plus actual focus movement may count | PASS | Production reconciliation; transition `_focus` and outcome precedence; accepted Family replay includes later actual-focus proof. |
| 05 Successful ACK without movement is not a visit | PASS | Transition outcome and zero-credit contract; production visit gate unchanged. |
| 06 Valid vertical scroll before NO_PROGRESS | PASS | Main `collection_flow` unchanged; scroll opportunity tests. Phase 3 does not choose termination. |
| 07 GlobalNav separate from content | PASS | `global_navigation`, discovery navigation inventory; production traversal unchanged. |
| 08 Incomplete terminal states visible | PASS | Production terminal emitter/completeness unchanged; accepted terminal payloads preserved in replay. |
| 09 Coverage need not mimic swipe order exactly | PASS | Existing target coverage planner retained; no Phase 3 swipe-order requirement. |
| 10 Exact bounds + metadata for target focus | PASS | `TargetFocusMatcher`, focused Python/Helper tests; no executor replacement. |
| 11 Actual focus overrides misleading ACK | PASS | `TransitionObserver.complete`, `_focus_row`, current reconciliation; representative focus never substituted for later actual proof. |
| 12 SMART_NEXT sequential/untargeted | PASS | `FOCUS_NEXT` operation candidate and existing Helper dispatch; smoke observes existing SMART_NEXT only. |
| 13 Planner-valid never-attempted priority | PASS | Accepted production fairness code unchanged; seven starvation tests. |
| 14 Attempt differs from visit | PASS | Production accounting retained; Phase 3 diagnostics always zero credit. |

All 12 cross-layer compatibility dimensions are PASS: hierarchy acquisition (after adaptation), focus, visit accounting, candidate identity, SMART_NEXT, scroll, starvation, termination, entry, locale, Family cache and monitor. No unresolved semantic contract conflict was found. Runtime observations and replay limitations are recorded separately below.

## Tests and replay

Evidence root: `out/phase3_current_main_20261011/` in the preserved production checkout. XML/log files and replay summaries are stored there, outside tracked source.

- Phase 3-specific suite: **422 passed**, 15 test files; `phase3_focused.xml` and inventory text.
- Focused production suite: **320 passed**, 17 test files; `production_focused.xml` and inventory text.
- Collector compatibility subset: **43 passed**; `capture_compatibility.xml`.
- Full Python acceptance suite: **3320 passed, 1 skipped, 0 failed, 0 errors**; `full_python_complete.xml` / `.log`.
- Full Helper suite: **404 tests, 0 failures, 0 errors**, Gradle BUILD SUCCESSFUL; `helper_tests_final.log`, worktree `app/build/test-results/testDebugUnitTest/`.
- Helper tests are required because integrating main updates Helper relative to original Phase 3, even though the final Helper tree is identical to main. No APK installation was needed.

The first isolated full run failed from canonical JSON checkout line endings and absent ignored fixtures. Subsequent artifacts exposed missing candidate environment profiles. These were **environment/fixture failures**, not rewritten tests or accepted regressions. Canonical JSON/JSONL bytes were restored from the integrated Git index; original approved packages, content-addressed store, V10 fixtures, source candidates and environment profiles were copied into the isolated worktree. Final full suite is clean. The two original frozen Motion/Safe ledgers were then supplied and their four cases exercised successfully. Only the pre-existing optional xlsxwriter dependency test remains skipped. Earlier 3316-pass/5-skip results remain preserved as intermediate fixture evidence. Published integration tests do not include unrelated untracked experiments from main.

| Test category (overlap intentional) | Cases | Result |
|---|---:|---|
| State model | 143 | PASS |
| Discovery | 77 | PASS |
| Transition | 76 | PASS |
| Semantic substate | 80 | PASS |
| Focus contract | 49 | PASS |
| Identity | 194 | PASS |
| Scroll | 53 | PASS |
| Starvation | 7 | PASS |
| Replay | 63 | PASS |

Historical Phase 3D: **16/16 exact transition document replay**, using the preserved seed Registry and saved bracket inputs; zero collision/binding/churn mismatch. The latest saved Phase 3D matrix is the oracle, not the superseded unresolved-Home Phase 3C matrix.

Accepted English Full32 `batch_20261010_214943` was reused read-only for Home, Devices, Food, Family Care and Find. Discovery identity and zero diagnostic visit credit are valid, and actual-focus projection agrees with authoritative production reconciliation. Partial tree events lack activity/context, so state recognition remains safely unbound; production termination reasoning is retained as evidence and is not reinterpreted by a nonexistent Phase 3 termination engine. See `replay/summary.json` and the five per-scenario JSONs.

The initial naive focus replay used `POST_FOCUS_OBSERVED`, which can precede realignment. Two Family Care cases incorrectly looked unchanged while later `FOCUS_RECONCILIATION` proved a new actual target; one had failed ACK with real movement. The replay adapter now preserves representative focus and supplies the later actual resource ID/bounds/accessibility-focus proof separately through the existing Phase 3 API. **No Family Care logic was changed.** This is evidence-order/adapter correctness, not a production regression. Incomplete flat-focus records remain UNKNOWN where authoritative proof is unavailable.

## Device smoke

Completed; final evidence and gates are appended below. This smoke uses existing stable entry and production traversal, with a separate diagnostic client/Registry. Phase 3 state, discovery, transition and substate values are **shadow/observational**. Production attempted steps, visits and terminal reasons remain **execution-driving**. Only the first two existing SMART_NEXT actions per entered scenario are bracketed; no new SMART_NEXT action is inserted.

The smoke-only runtime config caps the six selected scenarios at five steps. This intentionally measures startup semantics, not complete coverage or Family runtime. Camera entry is preserved statically; Camera smoke is optional and omitted. No locale is changed.

The first attempt was stopped on an anchored Home terminal entry failure; its initial foreground was NotificationShade. Evidence is preserved in `smoke/`. It did not reach the Phase 3 analysis hook and has zero lifecycle/transport blockers. It is not treated as an integration code regression: production entry is byte-identical to main, and the next fresh service observation verified SmartThings/Life. The follow-up smoke uses `smoke_verified/`; the rejected attempt is not silently discarded.

## Completed smoke evidence

| Scenario | Entry | State ID | Candidates | Transitions | Attempts | Visits | Terminal | Runtime s |
|---|---|---|---:|---:|---:|---:|---|---:|
| home_main | PASS | phase3-main-smoke:state:00000001 | 56 | 2 | 5 | 6 | INCOMPLETE_SAFETY_LIMIT / safety_limit | 95.2 |
| life_food_plugin | PASS | UNRESOLVED | 31 | 2 | 5 | 5 | INCOMPLETE_SAFETY_LIMIT / safety_limit | 84.5 |
| devices_main | PASS | phase3-main-smoke:state:00000002 | 77 | 2 | 5 | 5 | INCOMPLETE_SAFETY_LIMIT / safety_limit | 106.7 |
| device_smoke_sensor_plugin | PASS | UNRESOLVED | 21 | 2 | 5 | 6 | INCOMPLETE_SAFETY_LIMIT / safety_limit | 80.6 |
| life_family_care_plugin | PASS | UNRESOLVED | 23 | 2 | 5 | 6 | INCOMPLETE_SAFETY_LIMIT / safety_limit | 229.0 |
| life_find_plugin | PASS | UNRESOLVED | 18 | 2 | 5 | 5 | INCOMPLETE_SAFETY_LIMIT / safety_limit | 147.1 |

Full per-scenario observation fields, semantic substate values, binding reasons, focus observations, terminals and gates are in `integration_gate.json`; raw captures and bracket documents are in `smoke_verified/phase3_observations.json`.

Monitor: 136 samples; TalkBack PID 19549, Helper PID 12034, no PID change and no hard blocker. All ten requested lifecycle/transport hard-gate counts are zero. The monitor uses current Helper ownership/exact request-ID logic, not false-valued JSON keys or unanchored substring matches. FOCUS transport timeout means `focus_result_wait_timeout`, not a per-attempt focus polling failure.

Every selected entry passed and traversal started. Capped smoke visits remain positive; no immediate candidate/visit corruption or catastrophic startup coverage drop was observed. Coverage completeness was not claimed. The five-step safety limit is deliberate, and diagnostic captures add overhead; these runtimes are not comparable to Full32 performance.

Home and Devices state binding is supported where resolved. Plugin observations can remain safely unresolved with `MISSING_NAVIGATION_CONTEXT` / `UNVERIFIED_SELECTED_CONTEXT`: successful scenario entry alone is not imported as generic state identity. This existing diagnostic adapter gap is explicit, not repaired by injecting a scenario name as a verified state. Transitions preserve ambiguity and zero visit credit. Live SMART_NEXT focus proof remains limited when the diagnostic capture lacks coherent actual before/after focus, even while the production reconciliation records visits.

## Verdict and continuation

**PHASE3_CURRENT_MAIN_COMPATIBLE_WITH_LIMITATIONS**. Phase 3 core semantics survived integration; tests and replay are clean, all six bounded entries/traversals worked, and lifecycle/transport gates are clear. No production reliability code was changed relative to accepted main.

`READY_TO_CONTINUE_PHASE3_DEVELOPMENT=YES`. `READY_FOR_PHASE4=NO` for a general scenario/plugin traversal policy: first define and prove the adapter from verified production plugin entry to Phase 3 navigation/context evidence, and prove coherent focus observation at the execution boundary. This recommendation does not reopen the already-closed Home root/substate issue or claim a new production regression. Camera event typing/live-present accessibility comparison remains a retained non-blocking limitation. No Phase 4 strategy was implemented.

The integration branch is committed locally for continuation, without pushing main or changing the original feature ref. Git commit/hash and final preserved-ref checks are recorded in `publication_gate.json` after commit.
