# TalkBack Phase 6D closure (2026-10-30)

## Accepted source

- Authoritative branch: `integration/phase3-current-main`
- Validated live source before closure commits: `6476be807a3169c7358c62e5a40142997e1239a9`
- State graph mode: `TB_STATE_GRAPH_MODE=SHADOW`
- Verdict: `PASS_WITH_LIMITATIONS`

The repaired NAV acceptance passed. The single `6D-ACCEPT-1` run passed with limitations.

## Live evidence

The current post-entry hierarchy root was `CURRENT_COMPLETE`. Its `CapabilityCardView` body anchor matched the selected card evidence. The selected card, current tap, matching operation/receipt, run and invocation, navigation epoch, and resulting root resolved as `ENTRY_TRANSACTION_RESOLVED`.

The current production `PRE_DECISION` step 0 referenced the post-entry capture and validated as current/resolved. A separate initial graph seed placeholder remained `FOCUS_UNKNOWN`/`UNRESOLVED`; it did not grant entry, state, or visit authority. State-graph observation and frontier records had no borrowed invocation, request, or result evidence.

Traversal recorded 8 successful accessibility-focus moves and 5 new visits. Stale evidence accepted: `NO`. Wrong visit credit: `NO`.

Frontier records for `UNTARGETED_SMART_NEXT` were `NOT_COMPARABLE`; normal targetless content traversal was otherwise valid. No redirect or plateau was forced, and full scenario coverage is not claimed. The run retained its 8-step safety limit.

## Verification evidence

- Focused tests: 96 passed
- Related regression: 269 passed
- Helper/preflight regression: 128 passed
- `git diff --check`: passed

These results are retained from the accepted source state. Code tests were not repeated for documentation-only closure edits.

## Limitations and phase decision

- Stable semantic device/plugin identity remains `UNKNOWN`; no semantic identity was fabricated. Causal entry authority is independently established by the transaction and current-root evidence above.
- `UNTARGETED_SMART_NEXT` frontier comparison remains non-comparable.
- The AO runtime issue is a separate infrastructure limitation and was not used to establish TalkBack correctness.

No production-reachable correctness, authority, or safety blocker remained for this acceptance.

`SAFE_TO_CLOSE_PHASE6D=YES`

`SAFE_TO_START_PHASE6E=YES`
