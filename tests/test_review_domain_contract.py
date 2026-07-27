from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

from tb_runner.baseline_candidate_builder import build_baseline_candidate
from tb_runner.baseline_candidate_schema import BASELINE_CANDIDATE_SCHEMA_VERSION_V1
from tb_runner.baseline_candidate_validator import validate_baseline_candidate
from tb_runner.approval_contract import validate_v2_approval
from tb_runner.comparison_input import adapt_approved_baseline, adapt_candidate
from tb_runner.review_classification import ReviewDomain, classify_review_domain
from tests.test_baseline_candidate_builder import _create_run, _write_json


@pytest.mark.parametrize(
    ("mismatch_type", "failure_reason", "expected"),
    [
        ("EMPTY_VISIBLE", "", ReviewDomain.QA_ACCESSIBILITY),
        ("EMPTY_SPEECH", "", ReviewDomain.QA_ACCESSIBILITY),
        ("TEXT_MISMATCH", "", ReviewDomain.QA_ACCESSIBILITY),
        ("SPEECH_MISMATCH", "", ReviewDomain.QA_ACCESSIBILITY),
        ("NEW_FOCUSABLE_SPEECH_ONLY", "", ReviewDomain.QA_ACCESSIBILITY),
        ("NEW_ACCESSIBILITY_FAILURE", "", ReviewDomain.QA_ACCESSIBILITY),
        ("", "speech_visible_diverged", ReviewDomain.QA_ACCESSIBILITY),
        ("EMPTY_VISIBLE", "terminal_not_handled", ReviewDomain.AUTOMATION_ENGINE),
        ("EMPTY_VISIBLE", "move_failed", ReviewDomain.AUTOMATION_ENGINE),
        ("EMPTY_VISIBLE", "repeat_no_progress", ReviewDomain.AUTOMATION_ENGINE),
        ("EMPTY_VISIBLE", "target_not_found", ReviewDomain.AUTOMATION_ENGINE),
        ("EMPTY_VISIBLE", "recovery_only", ReviewDomain.AUTOMATION_ENGINE),
        ("UNRECOGNIZED_MISMATCH", "", ReviewDomain.UNKNOWN),
    ],
)
def test_review_domain_contract_prioritizes_automation_reasons(
    mismatch_type: str,
    failure_reason: str,
    expected: ReviewDomain,
) -> None:
    classification = classify_review_domain(
        mismatch_type=mismatch_type,
        failure_reason=failure_reason,
    )

    assert classification.review_domain is expected


def _write_s22_policy_fixture(run_root: Path) -> None:
    workbook_path = run_root / "talkback_compare.xlsx"
    workbook = openpyxl.Workbook()
    result = workbook.active
    result.title = "result"
    result.append(
        [
            "scenario_id",
            "step",
            "mismatch_type",
            "final_result",
            "failure_reason",
            "focus_view_id",
        ]
    )
    rows = [
        (
            "device_water_leak_sensor_plugin",
            2,
            "EMPTY_VISIBLE",
            "FAIL",
            "",
            "lowBattery",
        ),
        ("device_motion_sensor_plugin", 2, "EMPTY_VISIBLE", "FAIL", "", "lowBattery"),
        (
            "life_clothing_care_plugin",
            1,
            "EMPTY_VISIBLE",
            "FAIL",
            "terminal_not_handled",
            "DASC_0127-25",
        ),
        (
            "life_clothing_care_plugin",
            2,
            "EMPTY_VISIBLE",
            "FAIL",
            "move_failed",
            "DASC_0127-25",
        ),
        (
            "life_clothing_care_plugin",
            3,
            "EMPTY_VISIBLE",
            "FAIL",
            "repeat_no_progress",
            "DASC_0127-25",
        ),
        (
            "life_home_monitor_plugin",
            1,
            "EMPTY_VISIBLE",
            "FAIL",
            "",
            "com.samsung.android.oneconnect:id/shm_setting_button",
        ),
    ]
    for row in rows:
        result.append(row)
    workbook.save(workbook_path)

    evidence_path = run_root / "talkback_compare.evidence.jsonl"
    evidence_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "event_type": "POST_FOCUS_OBSERVED",
                    "scenario_id": scenario_id,
                    "step_index": step,
                    "transaction_id": f"tx-{index}",
                    "payload": {"observation": {"resource_id": resource_id}},
                },
                sort_keys=True,
            )
            for index, (scenario_id, step, _, _, _, resource_id) in enumerate(rows, 1)
        )
        + "\n",
        encoding="utf-8",
    )

    summary_path = run_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["scenario_result_status"] = "warning"
    summary["xlsx_path"] = str(workbook_path)
    summary["quality_issues"] = [
        {
            "scenario_id": scenario_id,
            "step": str(step),
            "mismatch_type": mismatch_type,
            "final_result": final_result,
        }
        for scenario_id, step, mismatch_type, final_result, _, _ in rows
    ]
    _write_json(summary_path, summary)


def test_candidate_preview_preserves_review_domains_and_source_provenance(
    tmp_path: Path,
) -> None:
    run_root = _create_run(tmp_path / "run")
    _write_s22_policy_fixture(run_root)

    preview = build_baseline_candidate(run_root, write=False, integrate=False)

    assert preview.path is None
    assert preview.candidate.candidate_schema == "talkback-baseline-candidate-v2"
    assert len(preview.candidate.limitations) == 3
    assert len(preview.candidate.automation_diagnostics) == 3
    assert preview.candidate.review_requirements == {
        "qa_reviewer_decisions": 3,
        "automation_acknowledgments": 3,
    }
    assert {item["review_domain"] for item in preview.candidate.limitations} == {
        "qa_accessibility"
    }
    assert {
        item["review_domain"] for item in preview.candidate.automation_diagnostics
    } == {"automation_engine"}
    clothing = preview.candidate.automation_diagnostics[0]
    assert clothing["failure_reason"] == "terminal_not_handled"
    assert clothing["source_signature"]["step"] == "1"
    assert clothing["source_signature"]["resource_id"] == "DASC_0127-25"
    assert clothing["source_transaction_id"] == "tx-3"


def test_v2_review_matching_does_not_collapse_same_scenario_and_mismatch() -> None:
    candidate = {
        "limitations": [
            {
                "review_domain": "qa_accessibility",
                "scenario_id": "same_scenario",
                "step": step,
                "mismatch_type": "EMPTY_VISIBLE",
                "resource_id": "same-resource",
                "source_transaction_id": f"tx-{step}",
                "source_signature": {
                    "step": step,
                    "resource_id": "same-resource",
                    "transaction_id": f"tx-{step}",
                },
            }
            for step in ("1", "2")
        ],
        "automation_diagnostics": [],
    }
    reviewed = [
        {
            "owner": "accessibility-team",
            "scenario_id": "same_scenario",
            "step": "1",
            "resource_id": "same-resource",
            "environment_scope": {"locale": "en-US"},
            "match_signature": {
                "mismatch_type": "EMPTY_VISIBLE",
                "step": "1",
                "resource_id": "same-resource",
            },
                "review_at": "2026-07-27T00:00:00Z",
                "evidence_references": [f"qa-run://run#transaction=tx-{index}"],
                "review_decision": "실제 접근성 문제",
            }
        for index in ("1", "1")
    ]

    failures = validate_v2_approval(
        candidate,
        structured_limitations=reviewed,
        known_limitation_snapshot=reviewed,
        automation_acknowledgments=[],
        acceptance_result="PASS WITH LIMITATIONS",
        explicitly_accepted=True,
    )

    assert "reviewed_limitations_candidate_1_unmatched" in failures
    assert "qa_review_incomplete" in failures


def test_v1_candidate_and_approved_flip_baselines_remain_readable(
    tmp_path: Path,
) -> None:
    run_root = _create_run(tmp_path / "run")
    preview = build_baseline_candidate(run_root, write=False, integrate=False)
    legacy = preview.candidate.to_dict()
    legacy["candidate_schema"] = BASELINE_CANDIDATE_SCHEMA_VERSION_V1
    legacy.pop("automation_diagnostics")
    legacy.pop("review_requirements")

    report = validate_baseline_candidate(legacy)
    candidate_input = adapt_candidate(legacy)
    repository_root = Path(__file__).resolve().parents[1]
    baseline_paths = sorted(
        (repository_root / "baselines" / "com.samsung.android.oneconnect").glob(
            "baseline_*/"
        )
    )
    baseline_inputs = [adapt_approved_baseline(path) for path in baseline_paths]

    assert report["approval_eligible"] is True
    assert (
        candidate_input.schema_versions["source"]
        == BASELINE_CANDIDATE_SCHEMA_VERSION_V1
    )
    assert len(baseline_inputs) == 2
