# TalkBack State Graph: Phase 6+ Roadmap

> **Provisional planning direction.** This note supplements
> [the accessibility crawl roadmap](talkback-state-graph-accessibility-crawl-roadmap.md).
> It does not revise that architecture note or claim that the future crawl is implemented.

## Phase boundaries and intent

### Phase 6 — production-safe state-graph exploration foundation

The provisional Phase 6 end is a **production-safe foundation for bounded state-graph exploration**. Its proposed foundation scope names resolved state identity, a state registry, a frontier, safe-navigation candidate evaluation, bounded redirect and exploration, and fail-closed handling of `UNKNOWN`. These are scope items, not claims that they are implemented or accepted. Phase 6 does not require a full accessibility crawler, automatic traversal of every state, or automatic discovery of every object within a state.

**The Phase 7 crawler scope is explicitly outside Phase 6.** Phase 6 completion must not be read as evidence that hybrid crawling or Full32 automatic crawl is available.

### Phase 7 — Hybrid Accessibility Crawl

Scenario navigation remains responsible for reaching screen entry points and for exceptional navigation, policy, and safety cases. Within an entered state, the provisional crawler direction includes safe-navigation exploration under explicit safety policy and ordinary internal work over time:

- dynamically discover accessibility candidates and states;
- evaluate and explore approved safe-navigation candidates to discover internal states;
- traverse ordinary objects using actual TalkBack focus and speech evidence;
- scroll, rediscover newly exposed content, and continue traversal;
- use scenario behavior as a fallback or reference for exceptional cases and comparison.

The direction is for dynamic discovery and observed TalkBack behavior to replace ordinary object-by-object hardcoding incrementally. Scenario entry and explicit safety handling remain part of the model.

### Phase 8 — Automatic Crawl Acceptance and Resilience

Phase 8 is a provisional direction for broader acceptance and resilient operation. It may cover:

- representative and full scenario acceptance;
- state coverage and reconciliation, including `MISSED` and `UNEXPECTED` outcomes;
- bounded exploration budgets and depth;
- resilience to UI and app-version changes;
- locale and device variation where applicable;
- regression comparison against existing scenario-driven validation and controlled promotion of validated automatic traversal.

These topics describe intended scope, not completed acceptance criteria or a claim that such acceptance has passed.

## Maintenance direction

The intended maintenance shift is from maintaining ordinary internal object definitions toward maintaining scenario entry, state and identity understanding, exceptional component handling, and safety policy. This is not a zero-configuration goal: entry paths, identity exceptions, safety boundaries, and fallback behavior still need deliberate maintenance. The expected reduction in object-specific upkeep is qualitative until measured.

## Current authority and status

Current behavior and acceptance are governed by the current source, the
[operational runbook](../operations/talkback-operational-runbook.md), and the
applicable validation and phase contracts. This roadmap does not supersede them.

Phase 7 and Phase 8 remain provisional. Phase 6D3A is not activated; positive ACTIVE live acceptance is incomplete. A CHECKPOINT freezes a baseline only and is not activation or positive live acceptance. Full32 automatic crawl is not implemented or claimed here.

- `SAFE_TO_RETRY_BOUNDED_ACTIVE_LIVE=NO`
- `SAFE_TO_ACTIVATE_6D3A=NO`
