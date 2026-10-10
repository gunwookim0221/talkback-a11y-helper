# English TalkBack targeted stabilization — 2026-10-10

Verdict: **ENGLISH_TARGETED_FIX_PASS_WITH_LIMITATIONS**.
All targeted entry/traversal gates pass. The remaining limitation is incomplete
content coverage under the unchanged terminal policies.

## Source and device

Published baseline: `39137967921c38f164ee5dd359f36d8db5986458`.
The source gate confirmed HEAD equals origin/main and the tracked worktree was
clean before creating `fix/english-locale-targeted-stabilization`.
Device: `SM-F741N`, serial `R3CX40QFDBP`. The supported locale method verified
`en-US`; SmartThings has no app override and follows the English system locale.
TalkBack PID `17467`, Helper PID `12034`. Both accessibility services were enabled.

Evidence root: `out/english_targeted_stabilization_20261010`.
Initial current-main batch: `batch_20261010_152915`, six targeted scenarios only.

## Current-main reproduction

| Prior RCA item | Current observation | Classification |
| --- | --- | --- |
| Home normal English chrome rejected | Correct Home selected, root verified, traversal started. Guard rejection did not reproduce. | PASS_CURRENT_MAIN for entry |
| Devices normal English chrome rejected | Correct Devices selected, root verified, traversal started. Guard rejection did not reproduce. | Guard already resolved |
| Devices reuses Home QR config | Effective config still inherited `home_tab_anchor`; QR did not match and the existing body fallback selected Search. | RUNTIME_CONFIG_DEFECT |
| Food English CTA missing | `Send to Shopping list` visible; post-open verification returned `post_open_verify_miss` and traversal did not start. Korean CTA replay matched. | LOCALE_TEXT_DEFECT |
| Family Care generic failure | Entry and traversal succeeded without lifecycle/transport blockers; 67 attempts, 1658.957 seconds through terminal evidence. | PASS_CURRENT_MAIN for entry/lifecycle |
| Find generic failure | No crash. The actionable map description `Find, …, Last updated: …` was rejected because plain `find` was allowed only as title text. | Changed: LOCALE_TEXT_DEFECT |

GlobalNav verified Home, Devices, Life, Routines, Menu: 5/5.
Historical `menu_favorites` and `menu_devices` IDs were not exposed on the current
semantic tab nodes. Recorded tab title leaves share the generic `id/title` ID;
the existing bottom-tab aliases and selected-tab verification established identity.
No new English-only tab-selection path was added.

## Minimal fixes

1. Add `send to shopping list` to the existing verification alias for
   `쇼핑리스트로 보내기`. The existing casefolded semantic candidate matching
   supports text, contentDescription, and visible-body evidence. The Korean
   verification token and all negative-focus guards remain intact.
2. Remove Devices' `home_tab_anchor` runtime reference. Give Devices the
   scenario-specific `id/search_icon` body anchor already selected and doubly
   verified by the prior fallback in both accepted Korean and current English
   recordings. Selected-Devices context and double accessibility-focus
   verification remain required.
3. For Find only, accept a leading `Find,`, `Find.`, or `Find:` description on
   the exact actionable `com.samsung.android.oneconnect:id/map_area` node or
   its observed `id/fme_view` card container. The six-scenario patched run exposed
   `Find, Loading…` on the latter resource, so map-only matching was insufficient.
   Generic descriptions, other resource IDs, non-actionable nodes, other
   scenarios, and competing plugin phrases remain ineligible. Existing Korean
   strict phrase matching and map action ownership remain unchanged.

No Home, Family Care, Camera, Home Camera, Phase 4, step-limit, or traversal
policy change has been made.

## Korean regression evidence

`config_comparison.json` confirms only the Devices anchor fields differ; every
other effective scenario config is identical to baseline. Step limits are unchanged.

Bilingual recorded fixtures join normalized semantic nodes with selected metadata
from the same snapshot by exact bounds. They replay the old fallback and new
Devices anchor against identical inputs, asserting the same resource selection,
correct selected-tab context, and two verification reads. Wrong Home context
cannot pass even with the same Search resource. Food tests preserve Korean CTA
matching and cover English casing and all three evidence channels. Generic
recipe/card copy and negative chrome signals still fail their respective guards.

Focused tests after the final Find fix: 592 passed. Baseline canonical Python suite: 3159 passed, 1 skipped.
The first postfix run had one obsolete test requiring Devices to share the Home
QR anchor (3180 passed, 1 skipped); that assertion now explicitly checks the
Devices boundary and retains QR expectations for Home, Life, and Routines.
The Food/Devices full-suite result was 3181 passed, 1 skipped. Map-only Find
changes passed 3189 tests with 1 skipped. Final map/card changes passed
3191 tests with 1 skipped in 125.75 seconds.

Find diagnosis captured five English Life viewports and the observed actionable
map node in `english_life_inventory.json` and `english_life_viewport_*.json`.
The initial search's scroll-to-top failure was not sufficient to explain the
failure: the exact English map description was visible in the inventory, and
same-input replay confirmed its matcher rejection. Before the scoped fix,
English replay failed and Korean replay passed (29 passed, 1 failed). Afterward,
both replay successfully with the same map tap; six negative cases remain rejected.
The later loading-card replay separately failed in English and passed in Korean
before allowing the observed actionable card resource (31 passed, 1 failed).
Bilingual card tests also require a confirmed post-click transition and reject
a tap that leaves the same screen visible.

Unscoped pytest collected historical output/snapshot directories and produced
830 collection errors. The repository's canonical `tests` scope reproduced the
stated baseline; no historical artifact directories were modified to resolve this.
Helper source is unchanged, so Helper tests are not required for these fixes.

## Targeted device validation

| Batch | Purpose | Result |
| --- | --- | --- |
| `batch_20261010_152915` | Current-main six-scenario reproduction | GlobalNav 5/5; Home, Devices, Family enter/traverse; Food and Find entry failures reproduced |
| `batch_20261010_162536` | Six-scenario patched validation | GlobalNav 5/5; Home, Devices, Food, Family entry/traversal verified; Find failed on its loading-card representation, prompting the final scoped extension |
| `batch_20261010_174224` | Find after final scoped extension | Entry verified, traversal started, no anchor abort; 10 attempts |
| `batch_20261010_174706` | Second Food/Devices/Find validation | All three enter and traverse; Food 100 attempts, Devices 91, Find 10; no entry failure or anchor abort |
| `batch_20261010_183208` | Additional cold-start Find check | Entry verified, traversal started, no anchor abort; 10 attempts, 216.210 seconds; ready map selected |

The final card-resource extension is gated exclusively to `life_find_plugin`.
The other scenarios' tested execution paths remained identical; Find was rerun
after the extension. The backend's device-level `passed` status was not used to
certify entry: individual entry contracts and traversal evidence were checked,
including the failed Find entry in the first patched batch.

| Scenario | Entry/traversal gate | Terminal content result | Runtime through terminal (seconds) |
| --- | --- | --- | ---: |
| GlobalNav | 5/5 destinations verified | COMPLETED | 29.386 |
| Home | Correct tab, root verified; no false-success rejection; traversal started | INCOMPLETE_NO_PROGRESS / content_no_progress, 29 attempts | 456.515 |
| Devices, first patched run | Independent Search resource anchor, selected Devices, double verification; traversal started | INCOMPLETE_NO_PROGRESS / content_no_progress, 62 attempts | 848.846 |
| Devices, second run | Same entry gates passed | INCOMPLETE_NO_PROGRESS / content_no_progress, 91 attempts | 1052.100 |
| Food, first patched run | CTA detected, entry verified; traversal started | INCOMPLETE_SAFETY_LIMIT / safety_limit, 100 attempts | 1396.234 |
| Food, second run | Same entry gates passed | INCOMPLETE_SAFETY_LIMIT / safety_limit, 100 attempts | 1214.085 |
| Family Care | Entry verified; traversal started; no crash/timeout | INCOMPLETE_NO_PROGRESS / repeat_no_progress, 56 attempts | 1417.236 |
| Find, first successful run | Actionable map selected, plugin body verified; traversal started; no anchor abort | INCOMPLETE_NO_PROGRESS / repeat_no_progress, 10 attempts | 200.541 |
| Find, second successful run | Same entry gates passed | INCOMPLETE_NO_PROGRESS / repeat_no_progress, 10 attempts | 205.208 |

Devices' first patched run retained the baseline's 62 attempts and essentially
the same runtime (849.990 seconds before, 848.846 after), with 44 versus 45 unique
visited instances. No coverage limit was reduced. Family Care's different attempt
count is not interpreted as a coverage improvement across dynamic profile states.

Food CTA nodes in `food_cta_node_evidence.json` have null resource IDs and expose
`Send to Shopping list` through text and contentDescription. The failure was a
missing locale alias, not casing, absence, wrong screen, or a stable-ID mismatch.

Family Care current-main SMART_NEXT: 76 correlated requests, average 8036.918 ms,
p95 15419.692 ms. Patched-worktree check: 65 correlated requests, average 7203.706 ms,
p95 15067.990 ms. Both runs had zero SMART_NEXT/FOCUS timeouts, zero TalkBack PID
changes, and zero unexpected Helper PID changes. These counts include profile
setup navigation attributed to the scenario, not only the main attempted steps.

SMART_NEXT measurements use the runner monotonic interval from ACTION_SENT
to correlated HELPER_ACK_RECEIVED, rather than the transport-only
`deliveryElapsedSeconds` field. Scenario runtime includes entry through terminal
evidence; it can differ slightly from profiler collection-loop runtime.

## Lifecycle and transport

Monitoring used Helper ownership and exact request-ID correlation,
package-specific PID sampling, and explicit lifecycle/integrity predicates.
Across completed baseline, six-scenario patched, Find-only, repeat, and cold-start batches:

| Gate | Count |
| --- | ---: |
| TALKBACK_PID_CHANGE_COUNT | 0 |
| HELPER_UNEXPECTED_PID_CHANGE_COUNT | 0 |
| WINDOW_FATAL_COUNT | 0 |
| FATAL_BADTOKEN_COUNT | 0 |
| HELPER_ANR_COUNT | 0 |
| SMART_NEXT_TIMEOUT_COUNT | 0 |
| FOCUS_TIMEOUT_COUNT | 0 |
| CHUNK_ERROR_COUNT | 0 |
| INSPECTION_SUPPRESSION_COUNT | 0 |
| TALKBACK_RECONNECT_COUNT | 0 |

Raw lifecycle JSONL was not emitted for these batches. PID evidence comes from
fresh package-specific sampling; fatal, ANR, transport, suppression, reconnect,
and integrity evidence comes from freshly tailed runner/logcat records plus
offline process-aware replay. Informational JSON keys with false values were not
counted as events. Fatal BadToken requires an associated TalkBack termination/PID
change; caught exceptions alone are not counted.

## Remaining limitation and readiness

Known content coverage remains incomplete under the existing no-progress and
safety-limit terminal policies. This is the acceptance limitation: entry and
traversal are verified, but these results do not claim exhaustive content coverage.
No guard, limit, or termination policy was weakened to obtain entry acceptance.

The ready map resource was exercised in successful live Find validations.
The observed loading-card representation is covered by bilingual same-input
replay and transition-rejection tests; successful live selections used the ready
map. The extra post-run entry diagnostic also verified the ready map with
unchanged TalkBack and Helper PIDs.

No English Full32 or Korean Full32 was run. Camera/Home Camera termination,
Family Care SMART_NEXT cache, and Phase 4 remain unchanged.
Readiness for English Full32: **YES**, as the next separately authorized acceptance
run. English Full32 has not been run in this task. Publication follows the user's
requested branch push, fast-forward merge to main, and main push.
