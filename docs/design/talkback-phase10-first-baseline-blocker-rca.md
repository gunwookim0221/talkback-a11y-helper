# Phase 10 First Baseline Blocker Root Cause Analysis

## 1. Executive Summary

This RCA compares the English Full Run `batch_20260715_223507`, the Korean Full Run `batch_20260716_082517`, and the last Phase 9.5.4 comparison run `batch_20260715_082735`. No new Full Run was executed.

The approval blockers do not have one common cause. There are four confirmed causal groups:

1. Runtime Profiler was explicitly resolved as disabled (`runtime_profiler=false`) in both approval-target runs. The request-to-runner propagation path is correct; this is a run configuration/user-option issue, not packaging or artifact discovery.
2. Home Care and Clothing Care share one post-entry accessibility-evidence failure. Their cards were found, scored, tapped, and transitioned. The current runs then received truncated WebView `FOCUS_RESULT` payloads whose root `text`, `contentDescription`, and resource ID were empty. Phase 9.5.4 received the same kind of truncated payload but with a usable root title, so its existing partial parser could retain trusted focus evidence.
3. Korean Air Care entered successfully and handled a setup screen successfully, but the QA Frontend summary parser recognizes only `entry_contract success`, not `entry_contract handled`. It consequently rewrote a handled one-step run as `NO_TARGET_CANDIDATE`.
4. Korean Pet Care entered the plugin, but its post-open screen exposed Korean labels such as `프로필 추가`, `산책 시작`, `활동`, and `케어`. The scenario's verification tokens do not include those labels, so the entry contract failed with `post_open_verify_miss`.

`NO_TARGET_CANDIDATE`, anchor abort, and terminal parity are therefore related as downstream reporting/gating states, but they are not interchangeable root causes. For Home/Clothing, `NO_TARGET_CANDIDATE` is especially misleading: the target card candidate did exist.

Recommended boundary: three work units—(1) profiler run configuration validation, (2) Life post-entry evidence and handled-terminal reporting, and (3) Pet Care Korean verification. Final disposition: **SPLIT INTO THREE FIXES**.

## 2. Run Environment Comparison

### 2.1 Environment and selection

| Item | English Full Run | Korean Full Run | Phase 9.5.4 comparison |
|---|---|---|---|
| Batch | `batch_20260715_223507` | `batch_20260716_082517` | `batch_20260715_082735` |
| Recorded commit | `74643d31c36e469c64ed0557e72605839c154dbe` | same | not recorded (pre-Phase-10 environment profile) |
| Dirty | `false` | `false` | not recorded |
| Device | `SM-F741N` | same | same |
| SmartThings | `com.samsung.android.oneconnect` `1.8.47.24` (`184724010`) | same | same observed test target |
| TalkBack | Samsung `15.1.01.1` (`1510101000`) | same | same device |
| Helper | `1.0` | `1.0` | same helper generation |
| Requested/effective locale | `current` / `en-US`, verified | `current` / `ko-KR`, verified | English UI observed; locale not canonically recorded |
| Fingerprint | COMPLETE, `3c5dcb739f62d1bef21ea413cee750067c7c6e6ad8064ed0a261900153499f36` | COMPLETE, `799b1f430ccb599b37caa5c3cf93455441ca5bda0df46b75d9fe971c9867d29f` | not available before Phase 10.1A |
| Scenario registry hash | `ec65d2c5acae8ffa92f03482041d0b531bb7c487ab2ef7ec53bcb28c3e1d21a7` | same | not recorded |
| Runtime config hash | `bec16a029ee36a555dd05e8a216f9f9b8db2a93d966c113403417b2f63fdfd95` | same | not recorded |
| Feature flags | Evidence, Identity Shadow V2, Traversal Identity V2, coverage ON; profiler OFF | same | same identity flags; profiler ON |
| Selected order | 32-scenario Full order | identical 32-scenario Full order | identical 32-scenario Full order |
| Executed / terminal | 30 / 30 of 32 | 29 / 28 of 32 | 32 / 32 |
| Anchor aborts | 2 | 3 | 0 |
| Reconciliation | PASS, 25,194 events | PASS, 23,676 events | PASS, 27,395 events |
| Profiler | absent | absent | JSON directory and `.profiler.zip` present |

The selected order in all three runs is the Full registry order beginning with `global_nav_main`, `home_main`, `home_safe_plugin`, device scenarios, and then Life scenarios. The four scenarios analyzed here occur in the order Air Care, Home Care, Pet Care, and Clothing Care, with other Life scenarios between them.

### 2.2 Artifact audit

Both target roots contain the expected batch summary, device summary, runner log, normal log, XLSX (`raw`, `filtered`, `summary`, `result` sheets), environment profile, evidence manifest, reconciliation report, evidence JSONL, focusable inventory, focusable coverage, and runtime-config snapshot. Both evidence manifests carry the EnvironmentProfile reference and Phase 10 comparison contracts. Both reconciliation reports are `PASS`, have zero orphan evidence, and preserve the anchor-abort scenarios without contradictory terminal events.

The English evidence JSONL is approximately 42.3 MB and the Korean evidence JSONL approximately 40.0 MB. The ordinary `talkback_compare_*.zip` files contain normal run/crop evidence and are not profiler archives. Neither target root contains a profiler directory, profiler JSON, or `*.profiler.zip`. Phase 9.5.4 contains per-scenario profiler JSON files and `talkback_compare_20260715_082745.profiler.zip`.

## 3. Profiler Blocker RCA

### 3.1 Propagation trace

The path is internally consistent:

1. `qa_frontend/frontend/src/App.tsx` initializes `traversalProfiler` to `false`.
2. `RunPanel.tsx` sends the checkbox value as `traversal_profiler` in the batch request.
3. `backend/main.py` accepts and logs that request field.
4. `backend/batch_runner.py` resolves it into the batch feature flags, writes it into the batch/device summaries, and creates `RunSpec(traversal_profiler=...)`.
5. `tb_runner/run_spec.py` adds `TB_TRAVERSAL_PROFILER_ENABLED=1` only when true and removes it when false.
6. `script_test.py` resolves the same flag and logs the profiler enable gate.
7. When enabled, collection writes per-scenario profiler JSON and packages `*.profiler.zip`.
8. `baseline_candidate_builder.py` deliberately discovers only `*.profiler.zip`; it does not confuse the ordinary evidence ZIP with profiler output.

### 3.2 Direct evidence

English and Korean `batch_summary.json`, `summary.json`, and `runner.log` all record `runtime_profiler=false`. Their runner logs say:

```text
[FEATURE_FLAGS][runspec] ... runtime_profiler=False
[PROFILER][startup] enabled=False artifact_root='...talkback_compare_....profiler'
```

Phase 9.5.4 records `runtime_profiler=true`, logs `enabled=True`, emits per-scenario `[PROFILER] ... artifact=...profiler.json` lines, and produces the profiler ZIP. This proves the generator and packaging/discovery conventions work when enabled.

The Phase 10 diff adds environment/candidate metadata but does not alter the frontend profiler checkbox, `RunSpec` profiler environment behavior, profiler generator, or packager. Runtime profiler is also independent of Evidence and Identity flags: `resolve_identity_feature_flags()` resolves it directly from `traversal_profiler`.

### 3.3 Classification

- Primary category: `CONFIGURATION_DEFECT` / user option not selected.
- Excluded: UI transfer defect, backend RunSpec defect, runner gate defect, artifact packaging/discovery defect, and Phase 10 regression.
- First failure point: the run request resolves profiler to false before subprocess launch.
- Minimum unblock: explicitly enable Runtime Profiler and verify the request/RunSpec/startup three-point trace before a Full Run.
- Optional product hardening: expose an explicit pre-run warning for a baseline-production run with profiler disabled; do not make profiler depend on Evidence/Identity and do not weaken the approval gate.

## 4. English Life Scenario RCA

### 4.1 Air Care

Air Care is healthy in English. Discovery scrolled to step 2, matched `Air Care`, selected `llCard` at `42,1752,1038,2316`, confirmed a transition, passed the anchor, and completed the entry contract. First failure: none relevant to approval.

### 4.2 Home Care

The first failed layer is post-entry focus/anchor verification, not discovery:

- Candidate discovery: five candidates; rank 1 actionable container, descendant title `Home Care`, bounds `42,1858,1038,2316`.
- Tap/transition: `XMLENTRY result success=true reason='transition_confirmed'`.
- First failure: the next WebView `FOCUS_RESULT` is truncated near 4 KB and its root has `text=""`, `contentDescription=null`, and no resource ID. The trace therefore records empty `focus_label`, empty announcement, and `focus_payload_final_source='none'`.
- XML still exposes top content `Home Care Home Care`, but focusing that synthetic duplicate label fails and the fallback lacks trusted new-screen focus evidence.
- Terminal: anchor abort with `insufficient_new_screen_evidence`; summary later maps it to `NO_TARGET_CANDIDATE`.

### 4.3 Clothing Care

Clothing Care follows the same failure chain:

- Candidate discovery: six candidates; rank 1 actionable container, descendant title `Clothing Care`, bounds `42,978,1038,1710`.
- Tap/transition: confirmed.
- First failure: truncated WebView `FOCUS_RESULT` with empty root identity, producing no usable focus label.
- Fallback XML exposes `Clothing Care Clothing Care`, but repeated focus and anchor verification do not establish trusted new-screen evidence.
- Terminal: anchor abort with `insufficient_new_screen_evidence`, summarized as `NO_TARGET_CANDIDATE`.

### 4.4 Phase 9.5.1 parser regression check

Commit `74643d3` contains `738e9fd` (`git merge-base --is-ancestor` succeeds). The current focused parser regression suite passes: `15 passed` in `tests/test_focus_result_parser.py`.

Phase 9.5.4 also produced truncated WebView payloads, but their root fields were materially different:

| Scenario | Phase 9.5.4 root text | Current English root text | Parser outcome used by traversal |
|---|---|---|---|
| Home Care | `SmartThings Home Care` | empty | trusted partial label vs no final focus evidence |
| Clothing Care | `Clothing Care` | empty | trusted partial label vs no final focus evidence |

The parser correctly restricts salvage to root fields and refuses to promote child labels into root identity. The current failure is therefore not a recurrence of the pre-`738e9fd` parser bug. It is an accessibility payload/state delta combined with the absence of another sufficiently strong, bounded post-transition identity proof.

## 5. Korean Life Scenario RCA

### 5.1 Air Care

Air Care did not fail candidate discovery. The Korean alias `에어 케어` matched five candidates; the rank-1 actionable container was tapped, transition was confirmed, and anchor verification succeeded. The plugin displayed a location/setup screen containing `위치 설정`. Collection classified and handled it as `setup_needed_or_empty_state`, returned to the Life list, and logged `entry_contract handled ... special_state_handled`.

The first failure is in `qa_frontend/backend/runtime_dashboard.py`: only the literal log form `[SCENARIO][entry_contract] success` enters `entry_success_scenarios`. A handled entry is therefore treated as having no entry, and the generic one-step `xml_scroll_search_tap` availability rule emits `NO_TARGET_CANDIDATE`. This is a confirmed summary/terminal classification defect, not a locale alias defect and not an app-entry failure.

### 5.2 Home Care

The Korean alias `홈 케어` matched five candidates at the same bounds and resource structure as English. Tap and transition succeeded. The first failure is again the truncated WebView root with empty identity fields. XML exposes `홈 케어 홈 케어`, but anchor verification cannot convert that into trusted new-screen focus evidence. It aborts with `insufficient_new_screen_evidence`.

### 5.3 Clothing Care

The Korean alias `클로딩 케어` matched five candidates at the same card bounds and resource structure as English. Tap and transition succeeded. The first failure is the same empty-root truncated WebView focus evidence. XML exposes `클로딩 케어 클로딩 케어`, but anchor verification cannot establish a stable trusted focus and aborts.

## 6. Pet Care RCA

Pet Care is independent of the Home/Clothing anchor-abort path:

- The Korean card `펫 케어` is found (five candidates), selected, and transition-confirmed.
- The fallback sees `산책 시작 산책 시작`, establishes new-screen evidence, and enters low-confidence start mode. It does not anchor-abort.
- Repeated complete `FOCUS_RESULT` payloads expose an unnamed WebView root. Visible content contains `프로필 추가`, `산책 시작`, `활동`, and `케어`; a back button is present.
- `scenario_config.py` includes Korean discovery/anchor aliases (`펫 케어`, `반려`) but its post-open `verify_tokens` are predominantly English and do not include the observed Korean body labels.
- The first failure is `verify_hit=false` in post-open identity, followed by `entry_contract failed ... post_open_verify_miss`.
- There is no exception, crash, non-zero subprocess return, or reconciliation failure. Batch return code remains zero and evidence reconciliation is PASS.

Primary category: `LOCALE_ALIAS_DEFECT`. The app accessibility surface contributes an unnamed WebView root, but the deterministic failure is the incomplete Korean post-open verification contract.

## 7. Locale Delta Analysis

System locale, requested locale, and observed SmartThings UI agree in both target runs. The runner records `language_mode='current'`, the device locale (`en-US` or `ko-KR`), `changed=false`, and `verified=true`. English bottom navigation/card labels are English; Korean bottom navigation/card labels are Korean. There is no evidence of a stale app-language cache or failed locale switch.

| Scenario | English card / selected structure | Korean card / selected structure | Locale effect |
|---|---|---|---|
| Air Care | `Air Care`; `llCard`/container; `42,1752,1038,2316` | `에어 케어`; same structure/bounds | Discovery succeeds in both. Korean app state is a setup screen; summary misclassifies handled terminal. |
| Home Care | `Home Care`; rank-1 container; `42,1858,1038,2316` | `홈 케어`; same structure/bounds | Discovery succeeds in both. Empty WebView root affects both. |
| Clothing Care | `Clothing Care`; rank-1 container; `42,978,1038,1710` | `클로딩 케어`; same structure/bounds | Discovery succeeds in both. Empty WebView root affects both. |
| Pet Care | `Pet Care`; rank-1 container; `42,1418,1038,2150` | `펫 케어`; same structure/bounds | Discovery succeeds in both. English verification sees `Navigate up`/English tokens; Korean body tokens are absent from `verify_tokens`. |

Resource IDs are stable at the card-list layer (`frameLayout`, `llCard`), while the selected rank-1 actionable wrapper often has no resource ID. This is not the cause of the locale-only Pet failure because selection and transition already succeeded.

## 8. Root Cause Matrix

| Problem | Classification | Direct evidence / first failure | Scope | Phase 10 causal? | Minimum correction | Regression risk |
|---|---|---|---|---|---|---|
| Profiler missing | `CONFIGURATION_DEFECT` (user option unselected) | request summaries and RunSpec are false; startup gate false; no JSON generated | both target runs | No | enable and assert request→RunSpec→startup before Full | Low; avoid changing independent flag semantics |
| Home Care | `APP_ACCESSIBILITY_LIMITATION` with dynamic payload delta | card/tap/transition pass; truncated WebView root identity empty; anchor lacks trusted evidence | English + Korean | No | add bounded, corroborated post-transition evidence path without weakening anchor gate | Medium/high; false-positive entry risk |
| Clothing Care | same common root as Home | same sequence and empty root identity | English + Korean | No | same framework correction | Medium/high |
| Korean Air Care | `CONFIRMED_CODE_DEFECT` | handled special state omitted from entry-success/terminal set and reclassified | Korean reporting only | No; code predates Phase 10 | recognize handled contract as an executed terminal outcome | Low/medium; counts and history API change |
| Korean Pet Care | `LOCALE_ALIAS_DEFECT` | plugin entered; observed Korean body tokens do not match verify contract | Korean only | No | add specific Korean post-open proof tokens/tests | Medium; broad tokens such as bare `케어` must be avoided |
| Anchor abort / terminal parity | downstream gate state, not another root | reconciliation preserves 2/3 aborts; candidate validator requires zero abort and 32/32 terminal | both | Gate added by Phase 10, failures not caused by it | resolve upstream entry/summary causes; keep gates | Low if gate untouched |

There is one shared root cause (Home + Clothing) and three independent causes (profiler configuration, Air summary classification, Pet locale verification). Reconciliation is functioning correctly: PASS means ledger consistency, not baseline eligibility. The candidate validator separately and correctly rejects any anchor abort, missing profiler, or incomplete execution/terminal parity.

## 9. Recommended Fix Boundaries

### Work unit 1: Profiler configuration validation

No propagation or packaging code fix is required to unblock. Run a short targeted QA Frontend scenario with the Runtime Profiler checkbox explicitly enabled and assert the batch summary, RunSpec log, startup log, one profiler JSON, and profiler ZIP. If product hardening is desired, the smallest UI boundary is `qa_frontend/frontend/src/components/RunPanel.tsx` plus frontend tests; do not silently couple it to Evidence/Identity or remove the candidate requirement.

### Work unit 2: Life post-entry evidence and terminal reporting

Keep this at the common framework boundary, not plugin-name bypasses:

- In `tb_runner/collection_flow.py`, define a bounded corroboration path for WebView roots with empty identity: confirmed card transition + stable post-open package/back-button/body evidence + XML/focus evidence tied to the new screen. Do not accept XML title alone and do not relax the anchor gate globally.
- Preserve the `738e9fd` root-only parser trust rule in `talkback_lib/action_result_parser.py`; no parser change is currently proven necessary.
- In `qa_frontend/backend/runtime_dashboard.py`, treat `entry_contract handled ... special_state_handled` as an executed terminal outcome rather than an availability candidate.
- Add focused cases to `tests/test_collection_flow.py`, `tests/test_focus_result_parser.py` only if parser behavior is touched, and `tests/test_qa_frontend_runtime_dashboard.py`.

### Work unit 3: Pet Care Korean verification

Update the Pet Care contract in `tb_runner/scenario_config.py` with specific Korean post-open evidence observed in the run (for example, combined/specific `프로필 추가` and `산책 시작` patterns), not a broad bare `케어` token. Add configuration and entry-verification cases in `tests/test_scenario_config.py` and `tests/test_collection_flow.py`.

## 10. Validation Plan

Before another Full Run:

1. Profiler smoke through QA Frontend: one scenario, profiler ON; verify all three flag checkpoints, per-scenario JSON schema, ZIP name, and Candidate discovery. Also verify the ordinary evidence ZIP is still ignored as a profiler artifact.
2. Replay/unit test the exact empty-root truncated Home/Clothing payload shape and verify root-only child isolation remains intact.
3. Targeted English and Korean Home/Clothing runs: require card candidate, confirmed transition, stable bounded post-entry evidence, entry-contract success, no anchor abort, and reconciliation PASS.
4. Runtime-dashboard fixture for Korean Air: `special_state_handled` must count executed and terminal and must not become `NO_TARGET_CANDIDATE`.
5. Korean Pet fixture/run: `펫 케어` discovery plus observed Korean post-open labels must pass; a Life-list false positive and unrelated Korean `케어` text must still fail.
6. Run current parser and dashboard suites, Candidate builder/validator suites, and scenario/collection tests before a new Full Run.
7. Only after the above, run new English and Korean Full Runs with profiler ON and require 32 selected, 32 executed, 32 terminal, zero anchor abort, reconciliation PASS, required contracts, clean repository, and complete required artifacts.

## 11. Baseline Approval Readiness

Neither target run is approvable.

- English: profiler is missing; 2 anchor aborts; 30/32 execution and terminal parity. Its persisted candidate `candidate_e90896ecf3f362d604014a6d` is correctly `NOT_ELIGIBLE` with profiler, reconciliation-integrity (anchor-abort), scenario-terminal, and required-artifact gates failing.
- Korean: profiler is missing; 3 anchor aborts; 29/32 executed and 28/32 terminal; Pet Care is hard failed. No persisted candidate file was found in the batch root during this RCA, but applying the same validator contract necessarily fails the profiler, anchor-abort/reconciliation-integrity, terminal, and required-artifact requirements.

Fingerprint completeness does not override these gates. It proves comparison identity completeness, not run completeness or artifact completeness.

## 12. Residual Unknowns

- The artifacts prove that the current Home/Clothing WebView root identity is empty, but they do not prove why SmartThings changed from a named root in Phase 9.5.4 to an unnamed root later the same day. Possible app remote-content/state/accessibility-tree timing causes remain unproven. The correction should therefore validate evidence, not assume a timing cause or add arbitrary sleep/retry.
- Phase 9.5.4 predates EnvironmentProfile capture, so its exact commit and dirty state are not canonically recorded. Its timestamp follows `738e9fd`, and its logs demonstrate the fixed partial-root behavior, but this RCA does not claim an unrecorded exact SHA.
- The QA Frontend HTTP request body/server log is not retained in the batch artifacts. Nevertheless, the batch summary, device summary, RunSpec line, startup gate, and successful true-path comparison are sufficient to prove the resolved input value and exclude a downstream propagation/packaging loss.
- Air Care's Korean setup screen may be legitimate per-account dynamic state. The collection path handled it; only its summary classification is confirmed defective.

**Final verdict: SPLIT INTO THREE FIXES**
