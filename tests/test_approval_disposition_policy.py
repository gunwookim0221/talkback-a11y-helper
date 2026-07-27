from __future__ import annotations

import pytest
from typing import Any

from tb_runner.approval_contract import validate_v2_approval_report


def _qa_item(step: str) -> dict[str, Any]:
    return {
        "review_domain": "qa_accessibility",
        "scenario_id": "scenario",
        "step": step,
        "mismatch_type": "EMPTY_VISIBLE",
        "resource_id": f"resource-{step}",
        "source_transaction_id": f"tx-{step}",
        "source_signature": {
            "step": step,
            "mismatch_type": "EMPTY_VISIBLE",
            "resource_id": f"resource-{step}",
            "transaction_id": f"tx-{step}",
        },
    }


def _review(step: str, decision: str) -> dict[str, Any]:
    return {
        "owner": "accessibility-team",
        "scenario_id": "scenario",
        "step": step,
        "resource_id": f"resource-{step}",
        "environment_scope": {"locale": "en-US"},
        "match_signature": {
            "mismatch_type": "EMPTY_VISIBLE",
            "step": step,
            "resource_id": f"resource-{step}",
        },
        "review_at": "2026-07-27T00:00:00Z",
        "evidence_references": [f"qa-run://run#transaction=tx-{step}"],
        "review_decision": decision,
    }


def _automation_item(step: str) -> dict[str, Any]:
    return {
        "review_domain": "automation_engine",
        "scenario_id": "clothing",
        "step": step,
        "failure_reason": "move_failed",
        "source_transaction_id": f"auto-{step}",
    }


def _acknowledgment(step: str) -> dict[str, Any]:
    return {
        "acknowledged_by": "automation.owner",
        "acknowledged_at": "2026-07-27T00:00:00Z",
        "owner": "automation-team",
        "domain": "automation_engine",
        "scenario_id": "clothing",
        "step": step,
        "failure_reason": "move_failed",
        "evidence_references": [f"qa-run://run#transaction=auto-{step}"],
        "disposition": "tracked_backlog",
    }


@pytest.mark.parametrize("decision", ["정상 발화", "False Positive", "재현 불가"])
def test_completed_non_limitation_review_requires_no_snapshot(decision: str) -> None:
    candidate = {"limitations": [_qa_item("1")], "automation_diagnostics": []}

    report = validate_v2_approval_report(
        candidate,
        structured_limitations=[_review("1", decision)],
        known_limitation_snapshot=[],
        automation_acknowledgments=[],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )

    assert report.failures == ()
    assert report.qa_completed_rows == 1
    assert report.qa_snapshot_required == 0
    assert report.qa_snapshot_present == 0


@pytest.mark.parametrize("decision", ["실제 접근성 문제", "Accepted Known Limitation"])
def test_limitation_review_requires_exact_snapshot(decision: str) -> None:
    candidate = {"limitations": [_qa_item("1")], "automation_diagnostics": []}
    review = _review("1", decision)

    missing = validate_v2_approval_report(
        candidate,
        structured_limitations=[review],
        known_limitation_snapshot=[],
        automation_acknowledgments=[],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )
    complete = validate_v2_approval_report(
        candidate,
        structured_limitations=[review],
        known_limitation_snapshot=[review],
        automation_acknowledgments=[],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )

    assert "known_limitation_snapshot_missing" in missing.failures
    assert missing.qa_snapshot_required == 1
    assert missing.qa_snapshot_present == 0
    assert complete.failures == ()
    assert complete.qa_snapshot_present == 1


@pytest.mark.parametrize("decision", ["추가 조사 필요", "미검토"])
def test_incomplete_review_holds_approval(decision: str) -> None:
    candidate = {"limitations": [_qa_item("1")], "automation_diagnostics": []}

    report = validate_v2_approval_report(
        candidate,
        structured_limitations=[_review("1", decision)],
        known_limitation_snapshot=[],
        automation_acknowledgments=[],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )

    assert "qa_review_incomplete" in report.failures
    assert report.qa_completed_rows == 0


def test_automation_requires_acknowledgment_but_not_snapshot() -> None:
    candidate = {
        "limitations": [_qa_item("1")],
        "automation_diagnostics": [_automation_item("2")],
    }

    report = validate_v2_approval_report(
        candidate,
        structured_limitations=[_review("1", "False Positive")],
        known_limitation_snapshot=[],
        automation_acknowledgments=[_acknowledgment("2")],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )

    assert report.failures == ()
    assert report.qa_snapshot_required == 0
    assert report.automation_acknowledgments_required == 1
    assert report.automation_acknowledgments_present == 1


def test_s22_policy_preview_requires_one_snapshot_for_three_reviews() -> None:
    candidate = {
        "limitations": [
            {**_qa_item("1"), "scenario_id": "device_water_leak_sensor_plugin"},
            {**_qa_item("2"), "scenario_id": "device_motion_sensor_plugin"},
            {**_qa_item("3"), "scenario_id": "life_home_monitor_plugin"},
        ],
        "automation_diagnostics": [_automation_item(step) for step in ("1", "2", "3")],
    }
    reviews = [
        {**_review("1", "정상 발화"), "scenario_id": "device_water_leak_sensor_plugin"},
        {**_review("2", "False Positive"), "scenario_id": "device_motion_sensor_plugin"},
        {**_review("3", "실제 접근성 문제"), "scenario_id": "life_home_monitor_plugin"},
    ]

    report = validate_v2_approval_report(
        candidate,
        structured_limitations=reviews,
        known_limitation_snapshot=[reviews[2]],
        automation_acknowledgments=[_acknowledgment(step) for step in ("1", "2", "3")],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )

    assert report.failures == ()
    assert report.qa_review_rows == 3
    assert report.qa_completed_rows == 3
    assert report.qa_snapshot_required == 1
    assert report.qa_snapshot_present == 1
    assert report.automation_acknowledgments_required == 3
    assert report.automation_acknowledgments_present == 3
