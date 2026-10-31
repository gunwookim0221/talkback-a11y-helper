# TalkBack Phase 6E scroll owner and edge closure

## Accepted source and verdict

- Authoritative branch: `integration/phase3-current-main`.
- Phase 6E starting baseline: `862ad6122102621d9ca06bdc86f3b9735c6c781a`.
- Committed scroll model and arbitration parent: `e1166bf2c3e743eba55bf6e756384a267535727c`.
- Verdict: `PASS_WITH_LIMITATIONS`. A real scroll followed by a production
  traversal and visit update was not observed in one run.

## Contracts

- Resolve each vertical scroll owner from the current sealed hierarchy and
  state. Explicit targets must match the current path and bounds; accessibility
  fallback requires one unique current owner. Missing, ambiguous, mismatched,
  or stale owner evidence fails closed. Multiple containers remain distinct.
- Bind the action to its current request, dispatch receipt, result, and current
  pre/post captures. A `SCROLL_FORWARD` edge requires evidenced content, state,
  or viewport change. A no-op or boundary alone creates no scroll edge.
- On a current `SMART_NEXT` `reached_end`, require its matching invocation,
  latest native dispatch receipt, and confirmed unchanged focus before
  considering the current vertical scroll opportunity. A valid plateau scroll
  takes precedence over no-progress termination; capability alone does not
  cause unconditional scrolling, and an end request is not progress.
- Accessibility focus and the existing production reconciliation remain the
  authority for visits. Scroll owner identity excludes volatile request IDs,
  timestamps, and action state. The Phase 6B graph remains observational;
  Phase 6C/6D capture and currentness paths are reused.

## Evidence and verification

The bounded Devices acceptance observed one real downward scroll, request
`7ea69b8b`, with unique current `card_recycler` owner. Its current source and
result captures were correlated with the action, and state, viewport, and
content changed. The acceptance harness projected one `SCROLL_FORWARD` edge
from those real captures and transition; it was not emitted by a complete
production traversal loop. No scroll visit credit or stale acceptance was
observed. No-op and boundary behavior was covered offline, not exercised live.

An earlier Life route exposed a current scroll-capable candidate but the
production scheduler continued traversal while the viewport was unstable and
unseen candidates remained. Repeated `reached_end` results occurred in an
overlay; they did not establish a simultaneous current root scroll opportunity
or false progress. The arbitration repair addresses the separately reproduced
current-end fallback and pre-dispatch owner checks.

The final single Life acceptance, run
`run_3b5b57ae4dcf4c8399dda0d636489c2c`, was `NOT_EXERCISED`: the current
capture reported `SCROLL_NOT_CAPABLE` and vertical forward false. No scroll or
post-scroll traversal occurred. Its evidence reconciliation passed with 11
events and no orphans; the emitted shadow graph had zero edges and one
unresolved observation. This is not evidence of a same-run scroll-to-traversal
pass.

The hash-bound arbitration candidate had identical before/after manifest
SHA-256 `e3b9fa5a631d45b17ae5530edd3a2f3e2493e94f92a731a47b4223e38846ea18`.
Focused tests passed 157; related scroll/capture tests passed 219, frontier
tests passed 191, and selected collection-flow tests passed 30. The final live
preflight accepted `COMPATIBLE_SAME_HELPER_INPUT` with matching helper input,
APK, PING/CAP identity, and service schemas. The evidence for the final Life
run was hash-verified in the session temporary directory; artifact-directory
copying was unavailable due to an access error.

## Phase 6F runtime carryover

In a single real run, observe a current owner-bound scroll with evidenced change,
then a production traversal decision and action, actual accessibility-focus
reconciliation, and the corresponding visit/state update. Verify that the
post-scroll step does not reuse stale pre-scroll evidence or grant false visit
credit. Do not manufacture an opportunity or treat the separate Devices and
Life runs as one chain.
