from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from tb_runner import collection_flow
from tb_runner.diagnostics import should_stop
from tb_runner.traversal_evidence_gate import (
    RecoveryCandidate,
    TraversalDiagnostics,
    evaluate_traversal_gate,
)


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        recent_representative_signatures=deque(maxlen=5),
        consumed_representative_signatures=set(),
        visited_logical_signatures=set(),
        consumed_cluster_signatures=set(),
        consumed_cluster_logical_signatures=set(),
        consumed_semantic_card_signatures=set(),
        current_local_tab_signature="",
        current_local_tab_active_rid="",
        active_container_group_signature="",
        active_container_group_remaining=set(),
        active_container_group_labels={},
        completed_container_groups=set(),
        recovery_attempted_candidate_ids=set(),
        recovery_hard_failed_candidate_ids=set(),
        recovery_visited_candidate_ids=set(),
        traversal_diagnostics=TraversalDiagnostics(),
    )


def _identity_result(verdict: str) -> dict:
    return {
        "reducer_version": "target-relation-v2",
        "verdict": verdict,
        "confidence": "HIGH_CONFIDENCE",
        "evidence_complete": True,
        "evidence_completeness": "COMPLETE",
        "transport": "ACKED",
        "action_api": "ACCEPTED",
        "physical_focus_delta": "CHANGED" if verdict == "MOVE_CONFIRMED" else "UNCHANGED",
        "temporal_relation": "STABLE_LANDING",
        "runtime_transaction_id": "tx-1",
        "runtime_transaction_state": "closed",
        "runtime_orphan_count": 0,
        "runtime_malformed_count": 0,
        "identity_diagnostics": {
            "pre_post": {"contradictions": []},
            "target_landing": {
                "aggregate_relation": "STRONG_PHYSICAL_LINK",
                "confidence": "HIGH_CONFIDENCE",
                "contradictions": [],
                "allows_move_confirmation": True,
            },
        },
    }


def _decision(verdict: str, row: dict):
    return evaluate_traversal_gate(
        _identity_result(verdict),
        transaction_id="tx-1",
        evidence_transaction_id="tx-1",
        legacy_progressed=True,
        legacy_visited=True,
        legacy_consumed=True,
        row=row,
        enabled=True,
    )


def test_flag_off_does_not_read_identity_or_mutate_row(monkeypatch):
    monkeypatch.delenv("TB_TRAVERSAL_IDENTITY_V2_ENABLED", raising=False)

    class Client:
        def _evidence_transaction_for_step(self, _step):
            raise AssertionError("flag OFF must not read the transaction")

        def _evidence_identity_result_for_step(self, _step):
            raise AssertionError("flag OFF must not read Identity V2")

    row = {"step_index": 1, "move_result": "moved", "visible_label": "A"}
    before = dict(row)
    progress, visit = collection_flow._resolve_traversal_evidence_decision(
        client=Client(), row=row, state=_state()
    )
    assert (progress, visit) == (None, None)
    assert row == before


def test_runtime_gate_consumes_attempted_representative_without_granting_static_visit(monkeypatch):
    monkeypatch.setenv("TB_TRAVERSAL_IDENTITY_V2_ENABLED", "1")

    class Client:
        def _evidence_transaction_for_step(self, _step):
            return "tx-1"

        def _evidence_identity_result_for_step(self, _step):
            return _identity_result("STATIC_FOCUS")

    row = {
        "step_index": 1,
        "move_result": "moved",
        "row_source": "representative",
        "focus_view_id": "pkg:id/child",
        "focus_bounds": "[10,10][90,90]",
        "actual_focus_resource_id": "pkg:id/container",
        "actual_focus_bounds": "[0,0][100,100]",
    }
    progress, visit = collection_flow._resolve_traversal_evidence_decision(
        client=Client(), row=row, state=_state()
    )

    assert progress is not None and progress.physical_progress is False
    assert visit is not None and visit.visited is False
    assert visit.consumed is True


def test_legacy_recording_is_unchanged_without_gate_decision():
    state = _state()
    row = {
        "move_result": "moved",
        "focus_view_id": "pkg:id/card",
        "visible_label": "Card",
        "focus_bounds": "[0,0][100,100]",
        "focus_cluster_signature": "cluster",
    }
    collection_flow._record_recent_representative_signature(state, row)
    assert "pkg:id/card||card||none" in state.visited_logical_signatures
    assert state.consumed_representative_signatures
    assert state.consumed_cluster_signatures == {"cluster"}


def test_static_representative_is_not_visited_but_attempt_is_consumed():
    state = _state()
    row = {
        "move_result": "moved",
        "row_source": "representative",
        "focus_view_id": "pkg:id/child",
        "visible_label": "Child",
        "focus_bounds": "[10,10][90,90]",
        "focus_cluster_signature": "representative-cluster",
        "actual_focus_resource_id": "pkg:id/container",
        "actual_focus_visible": "Container",
        "actual_focus_bounds": "[0,0][100,100]",
    }
    progress, visit = _decision("STATIC_FOCUS", row)
    collection_flow._record_recent_representative_signature(
        state, row, progress_decision=progress, visit_decision=visit
    )
    assert state.visited_logical_signatures == set()
    assert state.consumed_representative_signatures
    assert state.consumed_cluster_signatures == {"representative-cluster"}


def test_confirmed_move_visits_actual_focus_not_representative():
    state = _state()
    row = {
        "move_result": "moved",
        "row_source": "representative",
        "focus_view_id": "pkg:id/child",
        "visible_label": "Child",
        "focus_bounds": "[10,10][90,90]",
        "actual_focus_resource_id": "pkg:id/container",
        "actual_focus_visible": "Container",
        "actual_focus_bounds": "[0,0][100,100]",
    }
    progress, visit = _decision("MOVE_CONFIRMED", row)
    collection_flow._record_recent_representative_signature(
        state, row, progress_decision=progress, visit_decision=visit
    )
    assert "pkg:id/container||container||none" in state.visited_logical_signatures
    assert "pkg:id/child||child||none" not in state.visited_logical_signatures
    assert state.consumed_representative_signatures


def test_static_focus_prevents_representative_changes_from_resetting_stop_window():
    prev_fingerprint = ("anchor", "pkg:id/anchor", "[0,0][1,1]")
    previous = {"visible_label": "Anchor", "focus_view_id": "pkg:id/anchor", "focus_bounds": "[0,0][1,1]"}
    fail_count = 0
    same_count = 0
    stop = False
    reason = ""
    for index in range(1, 5):
        row = {
            "move_result": "moved",
            "visible_label": f"Representative {index}",
            "normalized_visible_label": f"representative {index}",
            "focus_view_id": f"pkg:id/representative_{index}",
            "focus_bounds": f"[{index},0][{index + 1},1]",
            "recent_semantic_unique_count": 0,
        }
        progress, _visit = _decision("STATIC_FOCUS", row)
        stop, fail_count, same_count, reason, prev_fingerprint, _details = should_stop(
            row=row,
            prev_fingerprint=prev_fingerprint,
            fail_count=fail_count,
            same_count=same_count,
            previous_row=previous,
            progress_override=progress,
        )
        previous = row
    assert same_count == 4
    assert stop is True
    assert reason == "repeat_no_progress"


def test_strong_recovery_requires_an_evidence_transaction(monkeypatch):
    monkeypatch.setenv("TB_TRAVERSAL_IDENTITY_V2_ENABLED", "1")
    candidate = RecoveryCandidate(
        "candidate", "key", "scenario", "", "Help", "pkg:id/help", "android.widget.Button",
        (10, 20, 110, 120), True, True, True, "REQUIRED", 31, 0,
    )
    monkeypatch.setattr(collection_flow, "_select_identity_recovery_candidate", lambda **_kwargs: candidate)

    class Client:
        def _evidence_set_step(self, *_args, **_kwargs):
            pass

        def _evidence_begin_target_action(self, *_args, **_kwargs):
            return None

        def focus_in_bounds(self, **_kwargs):
            raise AssertionError("no production recovery without an evidence transaction")

    phase = SimpleNamespace(
        tab_cfg={"scenario_id": "scenario", "tab_name": "Scenario", "scenario_type": "content"},
        output_path="out.xlsx",
        output_base_dir="out",
        all_rows=[],
        main_step_wait_seconds=0,
        main_announcement_wait_seconds=0,
        main_announcement_idle_wait_seconds=0,
        main_announcement_max_extra_wait_seconds=0,
    )
    outcome = collection_flow._attempt_identity_recovery(
        client=Client(), dev="SER", phase_ctx=phase, state=_state(), row={}, step_idx=4
    )
    assert outcome["attempted"] is False
    assert outcome["recovered"] is False


def test_strong_recovery_records_visit_and_prevents_stop(monkeypatch):
    monkeypatch.setenv("TB_TRAVERSAL_IDENTITY_V2_ENABLED", "1")
    candidate = RecoveryCandidate(
        "candidate", "key", "scenario", "", "Help", "pkg:id/help", "android.widget.Button",
        (10, 20, 110, 120), True, True, True, "REQUIRED", 31, 0,
    )
    monkeypatch.setattr(collection_flow, "_select_identity_recovery_candidate", lambda **_kwargs: candidate)
    monkeypatch.setattr(collection_flow, "maybe_capture_focus_crop", lambda _client, _dev, row, _base: row)
    monkeypatch.setattr(collection_flow, "_register_focusable_inventory_from_row", lambda *_args, **_kwargs: None)
    strong_progress, strong_visit = _decision("MOVE_CONFIRMED", {"move_result": "moved"})
    monkeypatch.setattr(
        collection_flow,
        "_resolve_traversal_evidence_decision",
        lambda **_kwargs: (strong_progress, strong_visit),
    )

    class Client:
        evidence_runtime = None

        def _evidence_set_step(self, *_args, **_kwargs):
            pass

        def _evidence_begin_target_action(self, *_args, **_kwargs):
            return {"transaction_id": "tx-1"}

        def focus_in_bounds(self, **_kwargs):
            return {"success": True, "status": "moved"}

        def collect_focus_step(self, **kwargs):
            return {
                "step_index": kwargs["step_index"],
                "move_result": "",
                "focus_view_id": "pkg:id/help",
                "visible_label": "Help",
                "focus_bounds": "[10,20][110,120]",
                "actual_focus_resource_id": "pkg:id/help",
                "actual_focus_visible": "Help",
                "actual_focus_bounds": "[10,20][110,120]",
            }

    state = _state()
    phase = SimpleNamespace(
        tab_cfg={"scenario_id": "scenario", "tab_name": "Scenario", "scenario_type": "content"},
        output_path="out.xlsx",
        output_base_dir="out",
        all_rows=[],
        main_step_wait_seconds=0,
        main_announcement_wait_seconds=0,
        main_announcement_idle_wait_seconds=0,
        main_announcement_max_extra_wait_seconds=0,
    )
    outcome = collection_flow._attempt_identity_recovery(
        client=Client(), dev="SER", phase_ctx=phase, state=state, row={}, step_idx=4
    )
    assert outcome["attempted"] is True
    assert outcome["recovered"] is True
    assert outcome["block_stop"] is True
    assert outcome["row"]["step_index"] == 4
    assert outcome["row"]["move_result"] == "moved"
    assert state.traversal_diagnostics.recovered_candidate_attempts == 1
    assert state.traversal_diagnostics.recovered_visits == 1
    assert state.traversal_diagnostics.premature_stop_prevented == 1
