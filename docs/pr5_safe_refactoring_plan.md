# PR5+ Safe Refactoring Plan (Incremental, No Runtime Contract Change)

## Scope and Non-Negotiables
- Runtime contract is fixed: `open -> main loop -> overlay -> realign -> stop -> persist`.
- Android helper (`app/*`) is out of scope.
- Big-bang modularization is prohibited; only behavior-preserving incremental refactors are allowed.

## Current State Snapshot
- `tb_runner/collection_flow.py` is still a large orchestrator (>2500 lines).
- `talkback_lib.py` family remains large (~2000 lines across dense responsibilities).
- PR1~PR3 stabilized the execution flow and stop-policy behavior.
- PR4 overlay structural split attempt regressed and was rolled back.

## Priority Refactoring Backlog (Top 5)

### P1. Extract and freeze decision-data normalization layer in runner
**What**
- Centralize row/decision normalization and fingerprint quality annotation paths used by `main`, `overlay`, and `stop` evaluation.
- Keep call graph shape identical; move only pure transformations first.

**Why (smell)**
- Same conceptual decision inputs are re-derived in multiple branches (main vs overlay vs post-realign), which increases silent divergence risk.

**Expected effect**
- Better testability (pure-function snapshot tests), easier regression diffing, less duplicated logic drift.

**Risk**: `low`

**When**: `now`
- This yields immediate safety for all future refactors because shared decision semantics become explicit.

---

### P2. Introduce a single phase context object for `collection_flow` (without moving phases yet)
**What**
- Replace large mutable parameter passing with one typed phase context (or dataclass) that carries phase-invariant state.
- No phase order change, no policy change.

**Why (smell)**
- Massive function signatures and cross-branch mutable flags make local edits high-risk and review-unfriendly.

**Expected effect**
- Reduced accidental state mismatch, easier fixture setup in tests, clearer ownership of state transitions.

**Risk**: `medium`

**When**: `now`
- Do this before file split; otherwise split only relocates complexity.

---

### P3. Stop-policy observability hardening (logic freeze + explainability)
**What**
- Keep policy decisions identical, but standardize stop evidence payloads and trace IDs per step.
- Add invariant checks in tests: decision reason, no-progress class, repeat class, terminal precedence.

**Why (smell)**
- Current policy is improved (PR3) but diagnosing false stop/late stop still needs log forensics.

**Expected effect**
- Faster incident triage, safer future tuning, deterministic replay checks.

**Risk**: `low`

**When**: `now`
- High ROI because it reduces fear of touching stop-adjacent code.

---

### P4. Overlay orchestration seam extraction (retry-safe wrapper only)
**What**
- Re-attempt PR4 scope in a narrower way: extract orchestration seam boundaries (`candidate -> click -> classify -> expand -> recover -> realign`) behind stable adapters while keeping existing implementations.
- No new fallback behavior; only explicit boundary wrappers and contracts.

**Why (smell)**
- Overlay regressions happened because policy/execution/persist coupling was too implicit.

**Expected effect**
- Isolated overlay tests and safer changes, without repeating a full structural rewrite.

**Risk**: `medium-high`

**When**: `later (after P1~P3)`
- Must wait until shared decision/state semantics are stabilized.

---

### P5. talkback_lib command/response contract consolidation
**What**
- Consolidate duplicated command invocation/parsing paths into one contract layer (request builder + response validator) while preserving existing command set.

**Why (smell)**
- Library-side reliability issues often come from subtle response-shape drift and ad-hoc parsing variance.

**Expected effect**
- Better extensibility for new commands, less parser divergence, simpler unit testing.

**Risk**: `medium`

**When**: `later (parallelizable after P2)`
- Valuable, but runner-side orchestration risk is currently higher priority.

## Explicit Judgements

### Q1. Are 2000~2500 line files acceptable *at this stage*?
- **Conditionally yes.**
- Given recent stabilization, file size alone is not an immediate blocker if behavior contracts are protected by tests and observability.
- However, this is **technical risk debt** and should be reduced incrementally with seam-first refactoring.

### Q2. Should `collection_flow.py` be split now?
- **Not immediately as a physical split-first move.**
- First stabilize shared data semantics and state ownership (P1/P2), then split by seam.
- Split-first would likely recreate PR4-style regression risk.

### Q3. Next priority: `runner(collection_flow)` or `talkback_lib`?
- **Runner first.**
- Reason: most recent regressions and policy complexity are centered around flow orchestration (`main/overlay/realign/stop` coupling).
- `talkback_lib` should follow once runner seam and state contracts are explicit.

## PR-by-PR Safe Roadmap

### PR5: Decision-data normalization extraction (pure functions only)
- Scope: move/centralize normalization and repeat-quality annotation helpers used by stop evaluation.
- Guardrail: no branch condition changes.
- Tests: golden row fixtures + stop-decision parity tests.
- Exit criteria: before/after run produces identical stop reason distribution for baseline scenarios.

### PR6: Phase context introduction in `collection_flow`
- Scope: replace mutable scattered locals with explicit context object.
- Guardrail: phase order and called functions remain unchanged.
- Tests: existing `tests/test_collection_flow.py` plus new context integrity tests.
- Exit criteria: no diff in persisted row fields for replayed scenarios.

### PR7: Stop explainability/log schema unification
- Scope: unify stop evaluation evidence fields and log key schema; keep verdict logic frozen.
- Guardrail: same stop decisions expected on replay.
- Tests: stop log snapshot tests + reason precedence tests.
- Exit criteria: deterministic explainability for every stopped scenario.

### PR8: Overlay seam extraction (narrow PR4 retry)
- Scope: adapter interfaces for overlay orchestration boundaries only; internal algorithms unchanged.
- Guardrail: retain existing candidate, classify, expand, recovery, realign implementations.
- Tests: targeted overlay regression suite (`overlay -> realign -> main resume`).
- Exit criteria: PR4 regression scenarios pass with identical outcome classification.

### PR9: talkback_lib command contract consolidation
- Scope: request/response parsing consolidation and shared validators.
- Guardrail: same public API behavior, same retries/timeouts.
- Tests: command parsing contract tests + mocked adb response matrix.
- Exit criteria: no change in command success/failure semantics under existing tests.

## Done Definition for Every PR
- Independent testability: each PR introduces or updates tests proving behavior parity.
- Runtime contract preservation: no change to `open -> main -> overlay -> realign -> stop -> persist` sequence.
- No helper explosion: prefer modifying/merging existing logic over adding parallel decision paths.
- Dead-code cleanup included: remove superseded branches/helpers/constants/logs in same PR when safe.
