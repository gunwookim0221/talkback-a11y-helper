from __future__ import annotations

from types import SimpleNamespace

from tb_runner.traversal_evidence_gate import evaluate_traversal_gate
from tb_runner.traversal_orchestration import (
    RecoveryCoordinator,
    StopPolicy,
    TraversalCoordinator,
    VisitTracker,
)


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
