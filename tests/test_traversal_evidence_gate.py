from __future__ import annotations

import json
from collections import Counter
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from tb_runner.evidence_identity import replay_shadow_v2
from tb_runner.traversal_evidence_gate import (
    ALLOWED_REDUCER_VERSIONS,
    ProgressDecision,
    RecoveryCandidate,
    TRAVERSAL_DIAGNOSTICS_SCHEMA,
    TraversalDiagnostics,
    VisitDecision,
    detect_representative_only,
    diagnostics_payload_schema,
    evaluate_traversal_gate,
    select_recovery_candidate,
    traversal_identity_v2_enabled,
)


REDUCER_VERSION = next(iter(ALLOWED_REDUCER_VERSIONS))


def _identity_result(
    verdict: str,
    *,
    complete: bool = True,
    stable: bool = True,
    confidence: str = "HIGH_CONFIDENCE",
    reducer_version: str = REDUCER_VERSION,
    transaction_id: str = "tx-1",
    transaction_state: str = "closed",
    orphan_count: int = 0,
    malformed_count: int = 0,
    transport: str = "ACKED",
    action_api: str | None = None,
    action_reason: str = "",
    physical_delta: str | None = None,
    pre_post_contradictions: list[str] | None = None,
    target_relation: str = "STRONG_PHYSICAL_LINK",
    target_contradictions: list[str] | None = None,
    target_confidence: str = "HIGH_CONFIDENCE",
    allows_move: bool = True,
) -> dict:
    is_move = verdict == "MOVE_CONFIRMED"
    return {
        "reducer_version": reducer_version,
        "verdict": verdict,
        "confidence": confidence,
        "evidence_complete": complete,
        "evidence_completeness": "COMPLETE" if complete else "PARTIAL",
        "transport": transport,
        "action_api": action_api or "ACCEPTED",
        "action_reason": action_reason or None,
        "physical_focus_delta": physical_delta or ("CHANGED" if is_move else "UNCHANGED"),
        "temporal_relation": "STABLE_LANDING" if stable else "UNSTABLE",
        "runtime_transaction_id": transaction_id,
        "runtime_transaction_state": transaction_state,
        "runtime_orphan_count": orphan_count,
        "runtime_malformed_count": malformed_count,
        "identity_diagnostics": {
            "pre_post": {"contradictions": list(pre_post_contradictions or [])},
            "target_landing": {
                "aggregate_relation": target_relation,
                "confidence": target_confidence,
                "contradictions": list(target_contradictions or []),
                "allows_move_confirmation": allows_move,
            },
        },
    }


def _evaluate(result: dict | None, **overrides):
    kwargs = {
        "transaction_id": "tx-1",
        "evidence_transaction_id": "tx-1",
        "legacy_progressed": True,
        "legacy_visited": True,
        "legacy_consumed": True,
        "row": {"move_result": "moved", "row_source": "actual_focus"},
        "enabled": True,
    }
    kwargs.update(overrides)
    return evaluate_traversal_gate(result, **kwargs)


def _candidate(
    candidate_id: str,
    *,
    label: str = "Help",
    bounds: str = "[10,100][210,220]",
    scenario_id: str = "safe",
    local_tab_signature: str = "surface-1",
    **overrides,
) -> dict:
    value = {
        "canonical_id": candidate_id,
        "scenario_id": scenario_id,
        "local_tab_signature": local_tab_signature,
        "label": label,
        "view_id": f"pkg:id/{candidate_id}",
        "class_name": "android.widget.Button",
        "bounds": bounds,
        "clickable": True,
        "focusable": True,
        "enabled": True,
        "taxonomy": "REQUIRED",
    }
    value.update(overrides)
    return value


def test_feature_flag_defaults_off_and_accepts_run_env(monkeypatch):
    monkeypatch.delenv("TB_TRAVERSAL_IDENTITY_V2_ENABLED", raising=False)
    assert traversal_identity_v2_enabled() is False
    assert traversal_identity_v2_enabled({}) is False
    assert traversal_identity_v2_enabled({"TB_TRAVERSAL_IDENTITY_V2_ENABLED": "1"}) is True


def test_decision_models_are_immutable():
    progress, visit = _evaluate(_identity_result("MOVE_CONFIRMED"))
    with pytest.raises(FrozenInstanceError):
        progress.accepted = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        visit.consumed = False  # type: ignore[misc]
    candidate = RecoveryCandidate(
        "id", "key", "s", "surface", "label", "rid", "class", (1, 2, 3, 4),
        True, True, True, "REQUIRED", 1, 0,
    )
    with pytest.raises(FrozenInstanceError):
        candidate.enabled = False  # type: ignore[misc]


def test_disabled_gate_preserves_distinct_legacy_visit_and_consumption():
    progress, visit = _evaluate(
        _identity_result("STATIC_FOCUS"),
        enabled=False,
        legacy_progressed=True,
        legacy_visited=True,
        legacy_consumed=False,
    )
    assert progress.progressed is True
    assert progress.gate_applied is False
    assert progress.reason == "feature_disabled"
    assert visit.visited is True
    assert visit.consumed is False


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"complete": False}, "evidence_incomplete"),
        ({"stable": False}, "landing_not_stable"),
        ({"confidence": "PLAUSIBLE"}, "confidence_insufficient"),
        ({"reducer_version": "target-relation-v1"}, "reducer_version_not_allowed"),
        ({"transaction_state": "open"}, "transaction_not_closed"),
        ({"orphan_count": 1}, "transaction_evidence_invalid"),
        ({"malformed_count": 1}, "transaction_evidence_invalid"),
        ({"transport": "INDETERMINATE"}, "helper_ack_missing"),
    ],
)
def test_strict_gate_failures_fall_back_to_legacy(override, reason):
    progress, visit = _evaluate(_identity_result("STATIC_FOCUS", **override))
    assert progress.progressed is True
    assert progress.used_legacy_fallback is True
    assert progress.reason == reason
    assert visit.visited is True
    assert visit.consumed is True


def test_same_closed_transaction_is_required():
    progress, _ = _evaluate(_identity_result("STATIC_FOCUS"), evidence_transaction_id="tx-other")
    assert progress.reason == "transaction_mismatch"
    progress, _ = _evaluate(_identity_result("STATIC_FOCUS", transaction_id="tx-other"))
    assert progress.reason == "transaction_not_closed"


def test_complete_stable_static_focus_suppresses_false_progress_but_keeps_planning_consumed():
    progress, visit = _evaluate(_identity_result("STATIC_FOCUS"))
    assert isinstance(progress, ProgressDecision)
    assert isinstance(visit, VisitDecision)
    assert progress.gate_applied is True
    assert progress.physical_progress is False
    assert progress.progressed is False
    assert progress.reason == "identity_v2_static_focus"
    assert visit.visited is False
    assert visit.consumed is True


def test_representative_only_static_focus_withholds_visit_but_consumes_planning_attempt():
    row = {
        "move_result": "moved",
        "row_source": "representative",
        "actual_focus_resource_id": "pkg:id/container",
        "actual_focus_bounds": "[0,0][100,100]",
        "focus_view_id": "pkg:id/child",
        "focus_bounds": "[10,10][90,90]",
    }
    assert detect_representative_only(row) is True
    progress, visit = _evaluate(_identity_result("STATIC_FOCUS"), row=row)
    assert progress.physical_progress is False
    assert visit.representative_only is True
    assert visit.visited is False
    assert visit.consumed is True


def test_strong_compatible_move_confirms_actual_visit():
    progress, visit = _evaluate(_identity_result("MOVE_CONFIRMED"))
    assert progress.progressed is True
    assert progress.gate_applied is True
    assert progress.physical_progress is True
    assert visit.visited is True
    assert visit.consumed is True


@pytest.mark.parametrize(
    "result",
    [
        _identity_result("MOVE_CONFIRMED", target_relation="SAME_SEMANTIC_OBJECT"),
        _identity_result("MOVE_CONFIRMED", target_contradictions=["window_id"]),
        _identity_result("MOVE_CONFIRMED", target_confidence="PLAUSIBLE"),
        _identity_result("MOVE_CONFIRMED", allows_move=False),
        _identity_result("MOVE_CONFIRMED", physical_delta="UNCHANGED"),
    ],
)
def test_move_confirmation_requires_strong_compatible_target(result):
    progress, _ = _evaluate(result)
    assert progress.used_legacy_fallback is True
    assert progress.reason == "target_compatibility_not_strong"


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        ("INDETERMINATE", "identity_v2_indeterminate"),
        ("MOVE_TO_OTHER_NODE", "other_node_conservative_fallback"),
        ("SNAP_BACK", "snap_back_conservative_fallback"),
    ],
)
def test_unpromoted_verdicts_never_become_production_success_or_failure(verdict, reason):
    progress, visit = _evaluate(
        _identity_result(verdict),
        legacy_progressed=False,
        legacy_visited=False,
        legacy_consumed=True,
    )
    assert progress.gate_applied is False
    assert progress.progressed is False
    assert progress.reason == reason
    assert visit.visited is False
    assert visit.consumed is True


def test_successful_post_transaction_realign_and_scroll_preserve_legacy_behavior():
    progress, _ = _evaluate(
        _identity_result("STATIC_FOCUS"),
        row={"move_result": "moved", "cta_focus_align_requested": True, "cta_focus_align_success": True},
    )
    assert progress.reason == "post_transaction_navigation_applied"
    progress, _ = _evaluate(
        _identity_result("STATIC_FOCUS"),
        row={"move_result": "scrolled"},
    )
    assert progress.reason == "non_focus_scroll_progress_preserved"


def test_diagnostics_exposes_exact_required_counter_set():
    progress, visit = _evaluate(_identity_result("STATIC_FOCUS"))
    diagnostics = TraversalDiagnostics().record_gate(progress, visit).record_recovery_attempt().record_recovery_visit().record_stop_prevented()
    payload = diagnostics.to_payload()
    assert payload["schema"] == TRAVERSAL_DIAGNOSTICS_SCHEMA
    counters = {key for key in payload if key not in {"available", "schema"}}
    assert counters == set(diagnostics_payload_schema()["counters"])
    assert len(counters) == 7
    assert payload["false_progress_suppressed"] == 1


def test_recovery_candidate_uses_actual_inventory_schema_and_strict_scope():
    inventory = [
        _candidate("wrong-scenario", scenario_id="motion"),
        _candidate("wrong-surface", local_tab_signature="surface-2"),
        _candidate("missing-surface", local_tab_signature=""),
        _candidate("invalid-bounds", bounds="[10,10][10,20]"),
        _candidate("disabled", enabled=False),
        _candidate("passive", clickable=False, focusable=False, class_name="android.widget.TextView"),
        _candidate("ignored", taxonomy="IGNORE"),
        _candidate("chrome", is_chrome=True),
        _candidate("localized-back", label="상위 메뉴로 이동", view_id="back"),
        _candidate("localized-more", label="옵션 더보기", view_id="more"),
        _candidate("fullscreen", bounds="[0,0][1080,1920]"),
        _candidate("eligible", bounds="[20,300][420,500]"),
    ]
    selected = select_recovery_candidate(
        inventory,
        scenario_id="safe",
        surface_id="surface-1",
        viewport_bounds=(0, 0, 1080, 1920),
    )
    assert selected is not None
    assert selected.candidate_id == "eligible"
    assert selected.bounds == (20, 300, 420, 500)


def test_recovery_candidate_dedup_and_same_label_different_bounds():
    inventory = [
        _candidate("dup-1", bounds="[10,100][210,220]", view_id="pkg:id/help"),
        _candidate("dup-2", bounds="[10,100][210,220]", view_id="pkg:id/help"),
        _candidate("other-location", bounds="[10,300][210,420]", view_id="pkg:id/help"),
    ]
    first = select_recovery_candidate(
        inventory,
        scenario_id="safe",
        surface_id="surface-1",
        viewport_bounds=(0, 0, 1080, 1920),
    )
    assert first is not None
    second = select_recovery_candidate(
        inventory,
        scenario_id="safe",
        surface_id="surface-1",
        viewport_bounds=(0, 0, 1080, 1920),
        attempted={first.candidate_id, first.canonical_key},
    )
    assert second is not None
    assert second.candidate_id == "other-location"


def test_recovery_returns_none_for_no_candidate_and_serializes_bounds():
    assert select_recovery_candidate(
        [_candidate("ignored", taxonomy="IGNORE")],
        scenario_id="safe",
        surface_id="surface-1",
        viewport_bounds=(0, 0, 1080, 1920),
    ) is None
    selected = select_recovery_candidate(
        [_candidate("eligible")],
        scenario_id="safe",
        surface_id="surface-1",
        viewport_bounds=(0, 0, 1080, 1920),
    )
    assert selected is not None
    assert selected.to_payload()["bounds"] == [10, 100, 210, 220]


@pytest.mark.parametrize(
    ("scenario", "relative_path", "expected", "suppressed"),
    [
        (
            "Motion",
            "qa_frontend_runs/batch_20260711_212123/device_SM-F741N_R3CX40QFDBP/"
            "talkback_compare_20260711_212134.evidence.jsonl",
            {"MOVE_CONFIRMED": 11, "STATIC_FOCUS": 5},
            3,
        ),
        (
            "Safe",
            "qa_frontend_runs/batch_20260711_212734/device_SM-F741N_R3CX40QFDBP/"
            "talkback_compare_20260711_212745.evidence.jsonl",
            {"MOVE_CONFIRMED": 11, "STATIC_FOCUS": 9},
            6,
        ),
    ],
)
def test_frozen_replay_promotes_only_complete_strong_facts(
    scenario: str,
    relative_path: str,
    expected: dict[str, int],
    suppressed: int,
) -> None:
    path = Path(__file__).resolve().parents[1] / relative_path
    if not path.exists():
        pytest.skip(f"local frozen {scenario} ledger unavailable: {path}")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    verdicts: Counter[str] = Counter()
    diagnostics = TraversalDiagnostics()
    for transaction_id, replayed in replay_shadow_v2(events).items():
        result = {
            **replayed,
            "runtime_transaction_id": transaction_id,
            "runtime_transaction_state": "closed",
            "runtime_orphan_count": 0,
            "runtime_malformed_count": 0,
        }
        legacy_progressed = result.get("action_api") == "ACCEPTED"
        progress, visit = evaluate_traversal_gate(
            result,
            transaction_id=transaction_id,
            evidence_transaction_id=transaction_id,
            legacy_progressed=legacy_progressed,
            legacy_visited=legacy_progressed,
            legacy_consumed=legacy_progressed,
            row={"move_result": "moved" if legacy_progressed else "failed", "row_source": "actual_focus"},
            enabled=True,
        )
        assert progress.gate_applied is True
        diagnostics = diagnostics.record_gate(progress, visit)
        verdicts[progress.verdict] += 1
    assert verdicts == expected
    assert diagnostics.false_progress_suppressed == suppressed
    assert diagnostics.fallback_to_legacy_count == 0
    assert diagnostics.indeterminate_count == 0
