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
