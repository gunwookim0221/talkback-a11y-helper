# Phase 10.2.2B: Air Care summary classification

## Problem Summary

Korean Air Care can enter a setup/onboarding special state after a successful
card entry.  The runner recovers back to the Life list and records a handled
entry contract, but the dashboard previously only treated the literal
`entry_contract success` form as an entry.  A one-step run with no Excel row
was consequently classified as `NO_TARGET_CANDIDATE`.

## Artifact Evidence

`batch_20260716_082517` records a selected Air Care candidate, confirmed
transition, special-state recovery, and then:

`[SCENARIO][entry_contract] handled ... reason='special_state_handled'
detail='onboarding_back_exit_recovered'`.

The same scenario has `PERF scenario_summary total_steps=1 save_excel_count=0`.

## Canonical Signal

The summary parser accepts only the scenario-scoped handled contract with the
current canonical reason/detail pair, preceded by the scenario-scoped special
state record with `handling='back_after_read'`.  This is an entry-contract
signal, not a locale, scenario-id, or free-text `handled` heuristic.

## Incorrect Classification Path

Without a recognized entry, the generic one-step XML/scroll entry rule sees
zero saved rows and assigns `NO_TARGET_CANDIDATE`.  That rule is correct for a
real anchor/search failure, but not after the recovered handled terminal.

## Fix

`runtime_dashboard.parse_runtime_log` adds qualifying handled contracts to the
same internal entry set used by a literal entry success.  It records additive
per-scenario metadata (`entry_contract_status: handled`,
`special_state_handled: true`) and an additive aggregate count.  Run Summary
and batch device summary propagate those fields; no runner, traversal, anchor,
or scenario configuration changes are made.

## Status/Terminal Semantics

A qualifying handled terminal is `passed`, therefore counted as executed and
completed.  It is not an availability candidate.  Failed contracts, missing
summaries, and real target/anchor failures retain their existing classifications.

## False-positive Protection

Both canonical records and their order are required: special-state detection
must precede the exact handled entry contract.  A bare `handled` line, a
different detail, or a special-state line emitted after the contract cannot
convert an XML anchor attempt into success.

## Tests

Tests cover the handled terminal, executed/completed/no-target counts, a
missing-prior-state false positive, a failed contract, existing real
`NO_TARGET_CANDIDATE` behavior, Run Summary propagation, and Candidate terminal
parity.  Existing Home/global-nav and general availability tests remain in the
same parser suite.

## Targeted Device Result

`batch_20260716_215023` ran only `life_air_care_plugin` on SM-F741N in
`ko-KR`, with profiler, evidence, identity, and traversal flags enabled and
coverage disabled.  It recorded the handled contract and finished `passed`;
the device summary reports `passed=1`, `executed=1`, `completed=1`, and
`no_target_candidate=0`.

## Candidate Eligibility Impact

Candidate construction already consumes `executed_scenarios`,
`completed_scenarios`, and terminal totals from Run Summary.  With the corrected
source status, a handled scenario now contributes one executed and one terminal
scenario without changing Candidate Builder semantics.

## Residual Risk

This recognizes only the currently emitted recovery contract.  A future
special-state recovery with a different canonical detail must deliberately add
its contract taxonomy and tests; it will not silently be accepted.

## Phase 10.2.2C Readiness

The classification is isolated to reporting and leaves Pet Care, profiler
option propagation, traversal, anchors, scenario configuration, baseline
repository state, and approval workflow unchanged.  Phase 10.2.2C can build
on the additive summary metadata after targeted evidence is reviewed.


## Phase 6F destination reference and contract status

### Confirmed Air Care destination reference

A read-only screenshot showed the Air Care detail title 에어 케어 and the normal empty/setup sentence: 방에 에어컨이나 공기청정기를 추가하여 방 안의 공기를 자동으로 관리해 보세요. The matching sealed hierarchy reference showed a OneConnect `WebPluginActivity` rooted at `android.widget.FrameLayout`, a unique `Button` resource `back` labelled 상위 메뉴로 이동, `paneContainer`, two WebView nodes, and no Life GridView. The screenshot and reference hierarchy are not strict transaction proof.

The earlier diagnostic transaction recorded the exact declared direct `FrameLayout` child click in action window 150 and then observed a same-service active destination window 192. Its poll trace had 92 `ACTION_WINDOW_NOT_ACTIVE_TYPE1` skips. Diagnostic mode remains no-credit.

### Current production Run 3 strict-navigation result (2026-11-17)

The request-binding repair was built and installed with exact source provenance:

- HEAD `129a26ab2de1a5002c8fcfc30587b47a64c2080d`, dirty source state
- Helper input `2e4d2168a9a537ad7867022d6d1fad165d539f039d53cd9b34faf16cc4d418dc`
- BuildID `a84e02f602bc5fd9f62ce0bb1ce9acc2db2efe359e6f9802c50d7ca33a244d3d`
- Debug APK SHA-256 `2B4FD12AB65DF4654570DC0C4DEE5C7D15B0447C7D338BF2FB716964F0B955CD`; signer `f94c4831ebb6990515e98b791e0ea337e546ee068a9d65aa5ec173189fbbe1a8`; installed/pulled bytes matched.
- Normal-user Android tests: `NavigationActionCapabilityTest` 40/40 and `EntryClickCaptureTest` 11/11; assemble passed. Host bridge/entry and packaged policy regressions passed 179/179; focused identity/provider/transport regressions passed 127/127.

The accepted focused Android build ran as `DESKTOP-H6PQG3O\smani` at Medium integrity (`S-1-16-8192`) using the normal Android Studio JBR `C:\Program Files\Android\Android Studio\jbr`, SDK `D:\tmp\phase6f-build-3a67c8ebf6eb4610bcfd5b8611eddc2a\sdk`, Gradle home `D:\tmp\phase6f-build-3a67c8ebf6eb4610bcfd5b8611eddc2a\gradle-home`, and the existing AGP mapping init script. The source identity and installed APK signer/bytes above match the fresh Helper precheck.

Strict navigation is **PASS** for `run_21e3dfb01b6442bfb7004df0aa134f96`, scenario `life_air_care_plugin`, request `3dd98be1-65f7-4537-9906-f598ea80fe03`, transaction `tx_c73cfb2ce9f749408cd62579c6e433e7`. The retained owner capture request is `entry_click_b1cd7940b6984ed9979887fe4a279e7b`, lease `f35cb341-ab37-45e5-8b6b-40eac35fbe6d`; both distinct request IDs remain explicitly bound to that transaction, service/connection `8c31e75d-361c-4f32-9abb-6da693bff0fb`, and lease.

The exact direct child at `[0,1,4,0]` was clicked once under its authorized parent `[0,1,4]`. Owner exactness and pre-dispatch currentness passed. The action/click event belongs to window 150. A complete fresh post-action capture in unique active type-1 window 221 contained the exact destination signature, unique back anchor, and current focus. The receipt records hierarchy digest `182a4461ea19d13a2471a5abf5881d9d724743b376279df5df71fbf9881a5c2a`, embedded sample SHA-256 `7a028c92e82dfa75c6975c404ccecfdf275d490d1c7aaf8e61ec6920c0fbffdc`, and a decision before the original dispatch deadline. The full 15-chunk receipt reassembles to SHA-256 `ade44213fa806f2791b82768bda0ba9dbf5e28322cb356839f196498ae063ccc` and is preserved in the `batch_20261117_200843` logcat evidence. Navigation receipt has `verified_navigation=true`, `visit_authority=false`, and `c5_credit=false`.

### Reusable strict-navigation proof conditions

A strict result is reusable only inside its original request/transaction. Keep the policy-authorized parent `[0,1,4]` and its one declared direct `FrameLayout` child `[0,1,4,0]` distinct; require both fresh/current before dispatch. The event owner remains the exact child, while the authorization lease remains bound to the parent relation. The navigation request ID and owner-capture request ID stay distinct and explicitly linked to the same transaction, lease, service/connection epoch, action window, event, and deadline.

Keep the action window as source authority (150). A post-dispatch destination may use a different window only when the same request/transaction/service/connection observes one unique active type-1 window after dispatch and captures it completely before the original deadline. Require the exact Air Care empty-state signature, expected WebView/container/back structure, exactly one anchor, and focus current in that same destination hierarchy. A changed window or title alone is insufficient; do not mix transactions or accept secondary-window evidence as proof. The receipt remains navigation-only (`visit_authority=false`, `c5_credit=false`); diagnostic mode remains no-credit.

### Run 1/Run 2 resolution gates

The preserved Run 1 resolution remains fail-closed for unavailable provider reads; the Run 2 resolution requires current-prefix, digest, and currentness agreement and grants no credit to the unavailable historical `+1` read. These are resolution gates, not two plugin traversal passes. The relevant provider/identity/transport regression set passed 127/127 against this source, and a fresh sealed read returned `EXACT_BUILD_PROVENANCE_MATCH`, complete hierarchy, verified capability, and the expected current service identity. The historical `+1` remains no-credit.

### Targeted traversal batch status

Batch `batch_20261117_200843` was stopped while the `life_air_care_plugin` scenario was still in progress. The saved records show eight traversal steps marked `PASS_MOVED`; the stop response occurred during step 7. The batch summary therefore says `scenario_result_status=failed` and `completed_scenarios=0`. This is an interrupted targeted traversal, not a full scenario pass or a strict navigation failure. The actual action ledger contains traversal/focus, the approved navigation, and safe overlay realignment; it contains no delete, settings-change, or device-control activation.

### Full31 scope and safety boundary

The prescribed first 31 IDs were retained exactly; `life_music_sync_plugin` at position 32 remains excluded. The `settings_entry_example` route was made fail-closed without coordinates by switching its shared `enter_settings` step and canonical `TAB_CONFIGS` step to the existing `select_and_click_focused` action. That generic action clicks only after successful exact selection or an observed accessibility-focused target; otherwise it returns failure and does not tap. No setting is changed. Focused host tests verify the successful focused-node path and missing-focus denial with zero tap calls; the focused collection-flow set passed 7 tests and the safe-navigation asset test passed 1.

The normal Helper input and BuildID remain `2e4d2168a9a537ad7867022d6d1fad165d539f039d53cd9b34faf16cc4d418dc` and `a84e02f602bc5fd9f62ce0bb1ce9acc2db2efe359e6f9802c50d7ca33a244d3d`, so the installed APK identity is still valid. The existing batch API writes a fresh per-run runtime config and starts a new runner subprocess; the generated Full31 config reports exactly 31 enabled IDs and the focused-only settings action.

Full31 attempt 1/3 is running as batch `batch_20261117_204754` in full mode with exactly the first 31 canonical IDs; `life_music_sync_plugin` at position 32 is not enabled. The generated per-run config reports 31 enabled scenarios and `enter_settings` action `select_and_click_focused`.

At the 2026-11-17 22:20 KST status check it was at `device_door_lock_plugin`, step 1. Raw terminal summaries so far: `global_nav_main` completed; `home_main` and `devices_main` ended `INCOMPLETE_NO_PROGRESS`; `home_safe_plugin`, `life_home_care_plugin`, and `life_energy_plugin` ended `INCOMPLETE_NO_PROGRESS`; `life_food_plugin` ended `INCOMPLETE_ERROR/scroll_owner_unresolved`; `life_air_care_plugin` ended `INCOMPLETE_ERROR/tab_or_anchor_failed`; smoke sensor, water-leak, and motion plugin scenarios completed at `plugin_boundary_global_nav`. These are observed scenario outcomes, not yet the terminal Full31 result. The live dashboard counts remain provisional.

The actual event action names so far are limited to evidence/focus/traversal, PING, and entry-capture requests; the current logs contain no tap-fallback or delete/power/toggle marker. This audit is limited to records written so far. Full31 remains in progress, not accepted.

### Full31 progress update (2026-11-17 22:36 KST)

The same attempt `batch_20261117_204754` remains running in `device_tv_plugin`, step 8. Raw terminal outcomes added since the prior update: `device_door_lock_plugin` completed at `plugin_boundary_global_nav`; `device_air_purifier_plugin` ended `INCOMPLETE_NO_PROGRESS/repeat_no_progress`. The full run has not reached `settings_entry_example`; its generated config remains focused-only and no coordinate-fallback marker has appeared. Do not treat live dashboard counters as the final acceptance result.



### Full31 progress update (2026-11-17 22:44 KST)

The same first-31 attempt `batch_20261117_204754` is still running. The latest status is `device_washer_plugin`, step 12, with a traversal `PASS`; the batch is not terminal and Full31 is not accepted. The API dashboard counters are inconsistent with the raw terminal summaries and remain provisional. The inspected action records remain limited to accessibility evidence, focus, traversal, PING, and entry-capture requests; no coordinate fallback or delete/settings/device-control activation has been observed in the reviewed records. This is a bounded status observation, not a final action-ledger audit.


## Phase 6F verification correction (2026-11-18)

### Scroll-owner path binding

The local-tab scroll fallback now keeps capability metadata paired with its one complete, current hierarchy capture and resolves a unique owner only from that capture. `flatten_service_hierarchy` paths include both the active-window projection and root indices; the Helper scroll protocol starts at `rootInActiveWindow` and consumes a root sentinel followed by root-relative child indices. The resolver therefore converts an active-window flat path such as `0.0.0.7.2` to Helper path `0.0.7.2`, requiring window index 0, the expected root prefix, valid numeric segments, unique exact node, and matching bounds. Missing, stale, or ambiguous authority remains no-dispatch. Saved XML is not used as current owner authority.

Focused host regressions after this correction passed: 204 tests across RunSpec, entry/bridge, scroll arbitration/reliability, and state graph; 3 local-tab collection consumers passed (535 deselected). The separate scroll arbitration/state graph/reliability set passed 114 tests. Diagnostic child activation is forcibly removed from the inherited environment at both canonical subprocess construction and the `script_test.py` entrypoint; tests cover inherited opt-in suppression.

### Targeted camera result

Targeted batch `batch_20261118_105445` completed for `device_camera_plugin` (runner return code 0), but its scenario result is a warning with `INCOMPLETE_NO_PROGRESS`, not a scenario pass. The raw evidence contains three `SCROLL_ATTEMPTED` records and three correlated `SCROLL_TRANSITION` receipts. Each used explicit Helper path `0.0.7.2`, bounds `30,1190,1050,2496`, `SCROLL_FORWARD`, `actionAttempted=true`, `explicitTarget=true`, `target_dispatch_verified=true`, and `SCROLL_MOVED`. New visible nodes were 5, 5, and 4 across the three transitions. The final traversal summary remains incomplete (`repeat_no_progress`; 23 unique visited instances; 7 missed and 3 unknown of 33 expected). This establishes that the owner was resolved and scrolling moved content, not that camera traversal passed.

The runner action ledger contains SMART_NEXT, TARGET_FOCUS_COMMIT, and FOCUS_IN_BOUNDS actions; it contains no `ACTION_API_RESULT` with `INPUT_TAP`. Diagnostic-only entry-correlation payloads are not treated as action receipts. The evidence ledger is `qa_frontend_runs/batch_20261118_105445/device_SM_F741N_R3CX40QFDBP/talkback_compare_20261118_105456.evidence.jsonl`; normal log and summary are alongside it. No Android source changed for this host repair, so the existing Helper identity remains BuildID `77cbc292c1466176eb49d6763ac6350cc884c67d0af9904522437df31927eaf3`, input `27e9110ccbb84a41f8b38a3593fd84a7c9b5699a6618befa98c25b58b76c3c70`, with installed/local APK bytes matching at SHA-256 `8077B65CE703F5E7517C84EEF9EFA788D9CD41C09797D2B9EE64E86FE6E1AE9D` and the expected debug signer `f94c4831ebb6990515e98b791e0ea337e546ee068a9d65aa5ec173189fbbe1a8`.

### Full31 attempt 1 terminal record and handoff

The first Full31 attempt `batch_20261117_204754` terminated with raw totals: 10 completed, 7 `INCOMPLETE_ERROR`, 12 `INCOMPLETE_NO_PROGRESS`, and 2 `INCOMPLETE_SAFETY_LIMIT`. It is not accepted. The targeted camera improvement above is separate from that Full31 outcome and from the earlier strict Air Care Run 3 receipt. Full31 attempt 2 has not been launched by this worker. The designated Luna worker owns the next first-31 canonical run, after receiving the current source/test/provenance and targeted evidence handoff; attempt 3 is not automatic.

### Phase6F reference-bound Life selector and single Back diagnostic (2026-11-20)

The bottom-tab Life candidate projection can display an aggregate label (`라이프 라이프`) even though the raw actionable `LinearLayout` has empty text and contentDescription `라이프`, under `HorizontalScrollView` resource `bottom_navigation` at `children[1].children[2]`. Use the existing locale-aware candidate matcher to identify the unique tab, then select the raw contentDescription with type `b`; do not send the aggregate projection string as an exact selector.

The current Air Care start state was saved as reference-only. The new scenario run kept its own run/transaction/service bindings. The preceding card entry run (`run_85b0160fc3e04baeac444f53df5e21f9`) recorded one click event but ended `NAVIGATION_OWNER_RECEIPT_UNVERIFIED`; it grants no navigation credit and is not reused as Back proof.

The one configured Back recovery (`run_567dc3f30b6a4ef8a0fa1972fda05954`, `stx_64551d94084746d7b94ccfb0e9b66219`, `tx_a5767c040a2549f4a40b1fe91a82f23a`, request `1ceac770-5695-4607-8977-c2c1fe6e29ce`) produced exactly one owner-bound click event. The owner was exact, dispatch was marked, currentness was accepted, and the click event was in action window 2027. Its same-request/transaction/service post capture completed in window 1820. Destination matched, but three nodes matched `required_anchor_label` (`[0,6]` TextView; `[1,2]` LinearLayout under `bottom_navigation`; `[1,2,0]` title TextView), so the strict result was rejected at `required_destination_anchor_unproven` / `NAVIGATION_DESTINATION_FOCUS_ANCHOR_UNPROVEN`. The sample recorded `destination_label` and `required_anchor_label`; it emitted no semantic-status field and no acknowledgement/empty-state policy node, so acknowledgement meaning remains unknown. No second Back or Full31 attempt 3 followed.

The complete 57-node same-action sample SHA-256 is `1f7f3a20bb77eaa21f5cfc7fb94d6e6f1f5289b89243ff0b8c2a5b49cf77ff51` (recomputed match); the runtime ledger SHA-256 is `40d59f841e5deb9750b4da84d98cf6f658198a2c2129751fc9bcc91d4de922f9`. The Helper build/input remain `398183ba59216e7a4c23faa7193b3610f7a75042204892e1fb61b5d30ad9915e` / `39bba9c58323378d39119c8b3368205be62a3f25dbd9ce09e79751fa557e9308`; installed and source APK bytes remain SHA-256 `88f5b4f0f70b5fafa5906547f37928978c0092de7943db0c2c3658ae617cb4c9`. The focused Host suites remain green at 85/85; no Android source or APK changed.

### Phase6F structural Life Back anchor update (2026-11-20)

The locally reviewed `life_plugin_navigate_up_to_landing` policy now optionally requires a structural anchor: the Life-labeled `LinearLayout` must have a direct `HorizontalScrollView` parent with resource `com.samsung.android.oneconnect:id/bottom_navigation`. Matching uses the complete captured hierarchy's node/parent class, parent resource, package, and window; it does not pin a numeric path or count the body text/title child. When this optional policy is absent, the prior label-count behavior remains unchanged. The configured Back receipt still requires the existing destination, owner, request/transaction/service/window/currentness, focus, and deadline checks.

The 57-node saved-shape regression passed with one structural anchor and rejected body-only, title-child-only, wrong or missing parent/container/class, duplicate, foreign-package, and stale-window cases. The configured strict-receipt test passes only with a same-window structural sample. `NavigationActionCapabilityTest` passed 44/44; related Host entry-flow and mirrored-policy tests passed 47/47. Build ID `b9c812ad27271a9e821bbcf48d57f2d9d6deca541529c49a363fc8dbf2a7f6d5` matches input digest `7ff0945f162904e357e893c4455b166a58f03d2dfdd69e018779344ecc9e83fa`. Source and pulled installed APK bytes match at SHA-256 `f9db33437d556145c20c8d66c79fcf1a1e8c33cc4bd34ff3b0768be59e78aa4e`; signer SHA-256 is `f94c4831ebb6990515e98b791e0ea337e546ee068a9d65aa5ec173189fbbe1a8`.

Two strict card-entry preparations are separate from the Back attempt and remain uncredited. The first used action-context service `788bac54-f76c-4ebc-b64c-8018168a34a5` while its sealed Helper hierarchy had reconnected to `75b6dbd2-eb45-4384-8acc-23636b06e172`; native owner dispatch rejected `ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE` before any click event. The one authorized fresh-service preparation then had one card click and one post-action event, but its entry receipt was rejected as `NAVIGATION_OWNER_RECEIPT_UNVERIFIED` (`EXACT_OWNER_CLICK_CONFIRMED`). A separate current reference verified the reviewed detail start; that reference did not grant entry credit.

The one Back recovery (`run_3ed6881a2208441e8f5f1299eb5bfcc9`, `stx_b1651b92799e430485eda3bbcf72c46a`, `tx_984b47d7d99a42a8971ecb8b0bd412ce`, request `27ff6179-b6fb-4842-8484-8afff706c7aa`) produced one exact owner click in action window 2039. Its same-request/transaction/service post authority transitioned to window 1820; destination matched and the structural anchor outcome was `MATCHED` with count 1. The strict receipt rejected at `NAVIGATION_POST_STATE_STALE_OR_INCOMPLETE` because `accessibility_focus_missing`, `focus_not_in_current_hierarchy`, and `focus_window_mismatch` remained true. The receipt granted no navigation/visit credit. This consumes the one Back action budget; no retry or Full31 attempt 3 followed.

The strict diagnostics report `post_capture_sample_persistence_status=EMBEDDED_COMPLETE`, 58 nodes, and hierarchy digest `9fa0faae203d3976acd81d525e1aa3ebd4a94126b02eee3c46775b81441a7749`. The saved runtime ledger `C:\Users\smani\AppData\Local\Temp\phase6f-back-only-runtime-e9862730826140b7a046ab808c86e0dd.evidence.jsonl` has SHA-256 `0b9fd7254d6b4458fba78ccf16e497cafe150f2912bb73ea59e9534ab9c7252a`, but does not contain a `post_capture_sample_artifact` payload or its artifact SHA-256; only the count/digest/status metadata is available in that ledger. A separate sealed Helper observation used service `e6521e4d-551c-4d87-bce5-9acd5733733c`, so it is not promoted or mixed with the strict action sample.

### Phase6F independent-start acceptance gate (2026-11-20)

This is an acceptance direction, not execution approval. It preserves all earlier run evidence and result records.

Strict Back verification requires its own exact-node target, click-event owner, and transaction-bound evidence. A Life landing/start-state never supplies Back owner or visit credit. A missing exact Back click-event owner does not by itself gate an independent scenario or Full31 progression once a fresh, safe Life start is independently verified and its provenance remains bound to that scenario/run.

After a scenario-local failure, a batch may continue only when a safe, independently verified next start is available and its provenance can be preserved. Stop the batch globally for safety, authority, or result-accuracy risk, including inability to establish that safe next start. Decouple phase prerequisites that do not protect those core properties.

Record each gate as PASS, FAIL, or UNVERIFIED, with exact attempted, completed, terminal, and coverage counts. PASS_WITH_LIMITATIONS is available only after core acceptance and declared coverage thresholds pass; an unresolved core authority, safety, or result-accuracy condition is not a limitation.

The historical strict AirCare entry proof (run_21e3dfb01b6442bfb7004df0aa134f96) and its original receipt evidence remain unchanged. On the later changed candidate, entry run run_668f63f4965a49ec9575195fc8f0766b / transaction tx_2a330558a4f2469295b10f88263b5ce8 returned VERIFIED_NAVIGATION; this is an entry-only PASS, not Back proof. Run3 remains UNRESOLVED and Back owner remains UNVERIFIED: the latest Back attempt (run_87cec407f0064d538818230888710a75, request d483f041-3400-4e3f-8419-f1d66322c0ba, transaction tx_80b7f1e15c12485f838c7427fd3c0e99) was rejected as NAVIGATION_EVENT_SOURCE_MISMATCH / CALLBACK_SOURCE_ABSENT before post-action focus verification. It grants no Back or Run3 credit and does not replace the prior records.

Full31 has a maximum of three total attempts; its successful count remains 0/3. All previously recorded attempt histories, statuses, and outcomes above remain authoritative and unchanged. This update does not authorize or initiate another Full31 run; the focused Settings/no-runner boundary is unchanged.