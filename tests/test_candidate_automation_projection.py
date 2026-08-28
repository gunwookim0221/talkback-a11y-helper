from __future__ import annotations

import json
from pathlib import Path

from tb_runner.approval_contract import validate_v2_approval_report
from tb_runner.baseline_candidate_builder import build_baseline_candidate
from tb_runner.candidate_review_issues import classify_candidate_review_issues
from tb_runner.canonical_json import canonical_json_bytes
from tests.test_baseline_candidate_builder import _create_run, _write_json


def _set_signals(
    run_root: Path,
    *,
    quality_issues: list[dict[str, object]] | None = None,
    automation_diagnostics: list[dict[str, object]] | None = None,
) -> None:
    summary_path = run_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["quality_issues"] = quality_issues or []
    summary["automation_diagnostics"] = automation_diagnostics or []
    _write_json(summary_path, summary)


def _automation(
    scenario_id: str,
    step: str,
    failure_reason: str,
    *,
    transaction_id: str = "",
) -> dict[str, object]:
    return {
        "scenario_id": scenario_id,
        "step": step,
        "mismatch_type": "EMPTY_VISIBLE",
        "final_result": "FAIL",
        "failure_reason": failure_reason,
        "transaction_id": transaction_id,
        "review_domain": "automation_engine",
        "validator_status": "AUTOMATION_DIAGNOSTIC",
    }


def _quality(scenario_id: str, step: str) -> dict[str, object]:
    return {
        "scenario_id": scenario_id,
        "step": step,
        "mismatch_type": "EMPTY_VISIBLE",
        "final_result": "FAIL",
    }


def test_separate_automation_collection_projects_zero_one_and_multiple_signals(
    tmp_path: Path,
) -> None:
    run_root = _create_run(tmp_path / "run")
    _set_signals(run_root)
    assert classify_candidate_review_issues(
        run_root, json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    )[1] == ()

    diagnostics = [
        _automation("scenario_b", "2", "repeat_no_progress"),
        _automation("scenario_a", "3", "move_failed"),
        _automation("scenario_a", "1", "terminal_not_handled"),
    ]
    _set_signals(run_root, automation_diagnostics=diagnostics)
    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    _, projected, unknown = classify_candidate_review_issues(run_root, summary)

    assert len(projected) == 3
    assert unknown == ()
    assert [(item["scenario_id"], item["step"]) for item in projected] == [
        ("scenario_a", "1"),
        ("scenario_a", "3"),
        ("scenario_b", "2"),
    ]
    assert {item["failure_reason"] for item in projected} == {
        "terminal_not_handled",
        "move_failed",
        "repeat_no_progress",
    }


def test_multiple_scenarios_and_same_scenario_diagnostics_are_not_collapsed(
    tmp_path: Path,
) -> None:
    run_root = _create_run(tmp_path / "run")
    diagnostics = [
        _automation("scenario_same", "1", "terminal_not_handled"),
        _automation("scenario_same", "2", "repeat_no_progress"),
        _automation("scenario_other", "1", "move_failed"),
    ]
    _set_signals(run_root, automation_diagnostics=diagnostics)

    preview = build_baseline_candidate(
        run_root, write=False, integrate=False, created_at="2026-08-28T00:00:00Z"
    )

    assert len(preview.candidate.automation_diagnostics) == 3
    assert {
        (item["scenario_id"], item["step"])
        for item in preview.candidate.automation_diagnostics
    } == {("scenario_same", "1"), ("scenario_same", "2"), ("scenario_other", "1")}


def test_duplicate_quality_fallback_and_canonical_collection_project_once(
    tmp_path: Path,
) -> None:
    run_root = _create_run(tmp_path / "run")
    diagnostic = _automation("scenario", "1", "terminal_not_handled")
    _set_signals(
        run_root,
        quality_issues=[_quality("qa_scenario", "1"), diagnostic],
        automation_diagnostics=[diagnostic],
    )

    preview = build_baseline_candidate(run_root, write=False, integrate=False)

    assert len(preview.candidate.automation_diagnostics) == 1
    assert len(preview.candidate.limitations) == 1
    assert preview.candidate.limitations[0]["scenario_id"] == "qa_scenario"


def test_identical_inputs_have_identical_candidate_bytes_digest_and_id(
    tmp_path: Path,
) -> None:
    run_root = _create_run(tmp_path / "run")
    _set_signals(
        run_root,
        automation_diagnostics=[
            _automation("scenario", "2", "repeat_no_progress", transaction_id="tx-2"),
            _automation("scenario", "1", "terminal_not_handled", transaction_id="tx-1"),
        ],
    )

    first = build_baseline_candidate(
        run_root, write=False, integrate=False, created_at="2026-08-28T00:00:00Z"
    )
    second = build_baseline_candidate(
        run_root, write=False, integrate=False, created_at="2026-08-28T00:00:00Z"
    )

    assert canonical_json_bytes(first.candidate.to_dict()) == canonical_json_bytes(
        second.candidate.to_dict()
    )
    assert first.document_digest == second.document_digest
    assert first.candidate.candidate_id == second.candidate.candidate_id


def test_projected_diagnostic_matches_acknowledgment_and_unacknowledged_fails(
    tmp_path: Path,
) -> None:
    run_root = _create_run(tmp_path / "run")
    _set_signals(
        run_root,
        automation_diagnostics=[
            _automation("scenario", "1", "terminal_not_handled", transaction_id="tx-1")
        ],
    )
    candidate = build_baseline_candidate(run_root, write=False, integrate=False).candidate
    acknowledgment = {
        "acknowledged_by": "qa-reviewer",
        "acknowledged_at": "2026-08-28T00:00:00Z",
        "owner": "automation-team",
        "domain": "automation_engine",
        "scenario_id": "scenario",
        "step": "1",
        "failure_reason": "terminal_not_handled",
        "evidence_references": ["qa-run://batch/device/evidence#transaction=tx-1"],
        "disposition": "non_blocking_terminal_diagnostic",
    }

    acknowledged = validate_v2_approval_report(
        candidate.to_dict(),
        structured_limitations=[],
        known_limitation_snapshot=[],
        automation_acknowledgments=[acknowledgment],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )
    unacknowledged = validate_v2_approval_report(
        candidate.to_dict(),
        structured_limitations=[],
        known_limitation_snapshot=[],
        automation_acknowledgments=[],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )

    assert acknowledged.failures == ()
    assert "automation_acknowledgments_missing" in unacknowledged.failures


def test_malformed_separate_diagnostic_fails_closed_as_unknown(tmp_path: Path) -> None:
    run_root = _create_run(tmp_path / "run")
    _set_signals(
        run_root,
        automation_diagnostics=[
            {"scenario_id": "scenario", "step": "1", "failure_reason": "move_failed"}
        ],
    )

    preview = build_baseline_candidate(run_root, write=False, integrate=False)

    assert preview.candidate.automation_diagnostics == ()
    assert any(
        item["code"] == "MALFORMED_AUTOMATION_DIAGNOSTIC"
        and item["review_domain"] == "unknown"
        for item in preview.candidate.limitations
    )
    approval = validate_v2_approval_report(
        preview.candidate.to_dict(),
        structured_limitations=[],
        known_limitation_snapshot=[],
        automation_acknowledgments=[],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )
    assert "unknown_review_domain" in approval.failures


def test_quality_issue_like_product_anomaly_is_not_auto_acknowledged(
    tmp_path: Path,
) -> None:
    run_root = _create_run(tmp_path / "run")
    _set_signals(run_root, quality_issues=[_quality("product_anomaly", "1")])

    candidate = build_baseline_candidate(run_root, write=False, integrate=False).candidate
    report = validate_v2_approval_report(
        candidate.to_dict(),
        structured_limitations=[],
        known_limitation_snapshot=[],
        automation_acknowledgments=[],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )

    assert len(candidate.limitations) == 1
    assert candidate.limitations[0]["review_domain"] == "qa_accessibility"
    assert candidate.automation_diagnostics == ()
    assert "reviewed_limitations_missing" in report.failures
