from __future__ import annotations

from types import SimpleNamespace

import pytest

from tb_runner.traversal_evidence_gate import evaluate_traversal_gate
from tb_runner.traversal_orchestration import (
    RecoveryExecutionServices,
    RecoveryCoordinator,
    RecoveryExecutor,
    StopPolicy,
    TraversalCoordinator,
    VisitTracker,
)


def test_blocked_recovery_dispatch_has_no_post_action_observation_or_visit():
    class Candidate:
        candidate_id = "candidate:blocked"
        canonical_key = "instance:blocked"
        bounds = (66, 316, 525, 1012)
        label = "Unknown"

        def requested_observation(self):
            return {"bounds": "66,316,525,1012"}

    class Diagnostics:
        recovered_candidate_attempts = 0

        def record_recovery_attempt(self):
            return self

    state = SimpleNamespace(
        traversal_diagnostics=Diagnostics(),
        recovery_attempted_candidate_ids=set(),
        recovery_hard_failed_candidate_ids=set(),
        recovery_visited_candidate_ids=set(),
    )
    closed = []
    logs = []
    candidate = Candidate()
    select_calls = []

    def select_candidate():
        select_calls.append(True)
        return candidate if len(select_calls) == 1 else None

    client = SimpleNamespace(
        _evidence_begin_target_action=lambda *a, **kw: {"transaction_id": "tx:blocked"},
        _evidence_set_step=lambda *a, **kw: None,
        _evidence_active_transaction={"transaction_id": "tx:blocked"},
        evidence_runtime=SimpleNamespace(close_transaction=lambda tx, **kw: closed.append((tx, kw))),
        focus_in_bounds=lambda **kw: {"success": False, "dispatch_status": "BLOCKED_BEFORE_DISPATCH"},
        collect_focus_step=lambda **kw: pytest.fail("blocked recovery must not observe or reconcile movement"),
    )
    services = RecoveryExecutionServices(
        enabled=lambda: True,
        select_candidate=select_candidate,
        resolve_decision=lambda row: pytest.fail("blocked recovery cannot award a visit"),
        emit_evidence=lambda *a, **kw: pytest.fail("blocked recovery has no dispatched action result"),
        capture_crop=lambda *a, **kw: pytest.fail("blocked recovery cannot capture a visit"),
        register_inventory=lambda *a, **kw: pytest.fail("blocked recovery cannot register a visit"),
        log=logs.append,
        truncate=lambda value, count: value[:count],
        monotonic=lambda: 1.0,
        action_wait_seconds=0.1,
    )
    outcome = RecoveryExecutor.execute(
        client=client,
        dev="serial",
        phase_ctx=SimpleNamespace(tab_cfg={"tab_name": "Life"}),
        state=state,
        row={},
        step_idx=9,
        services=services,
    )

    assert outcome["attempted"] and not outcome["recovered"]
    assert not outcome["block_stop"]
    assert closed and closed[0][1]["status"] == "blocked"
    assert client._evidence_active_transaction is None
    assert state.recovery_hard_failed_candidate_ids == {candidate.candidate_id, candidate.canonical_key}
    assert any("recovery_blocked" in line for line in logs)


def test_traversal_coordinator_preserves_gate_arguments_and_results():
    row = {"step_index": 3, "move_result": "moved"}
    expected_progress, expected_visit = evaluate_traversal_gate(
        None,
        transaction_id="tx-3",
        evidence_transaction_id="",
        legacy_progressed=True,
        legacy_visited=True,
        legacy_consumed=True,
        row=row,
        enabled=True,
    )

    decision = TraversalCoordinator(
        stop_policy=StopPolicy(frozenset({"repeat_no_progress"}))
    ).resolve_decision(
        result=None,
        transaction_id="tx-3",
        evidence_transaction_id="",
        legacy_progressed=True,
        row=row,
    )

    assert decision.progress == expected_progress
    assert decision.visit == expected_visit


def test_visit_tracker_preserves_legacy_and_gated_semantics():
    legacy = VisitTracker.resolve(
        progress=None,
        visit=None,
        legacy_move_result="moved",
    )
    assert legacy.gate_applied is False
    assert legacy.planning_consumed is True
    assert legacy.physical_visited is True

    gated = VisitTracker.resolve(
        progress=SimpleNamespace(gate_applied=True),
        visit=SimpleNamespace(consumed=True, visited=False),
        legacy_move_result="moved",
    )
    assert gated.gate_applied is True
    assert gated.planning_consumed is True
    assert gated.physical_visited is False


def test_recovery_coordinator_preserves_attempt_until_settled_order():
    results = iter(
        [
            {"attempted": True, "block_stop": True, "recovered": False},
            {"attempted": True, "block_stop": True, "recovered": False},
            {
                "attempted": True,
                "block_stop": True,
                "recovered": True,
                "row": {"step_index": 4},
            },
        ]
    )
    calls: list[int] = []

    def attempt():
        calls.append(len(calls) + 1)
        return next(results)

    outcome = RecoveryCoordinator.run(attempt)

    assert calls == [1, 2, 3]
    assert outcome.recovered is True
    assert outcome.row == {"step_index": 4}


def test_traversal_coordinator_does_not_call_recovery_outside_stop_policy():
    coordinator = TraversalCoordinator(
        stop_policy=StopPolicy(frozenset({"repeat_no_progress"}))
    )
    calls = 0

    def attempt():
        nonlocal calls
        calls += 1
        return {"attempted": True}

    assert coordinator.recover(stop=False, reason="repeat_no_progress", attempt=attempt) is None
    assert coordinator.recover(stop=True, reason="safety_limit", attempt=attempt) is None
    assert calls == 0
