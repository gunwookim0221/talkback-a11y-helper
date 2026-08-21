from __future__ import annotations

from qa_frontend.backend.quality_issues import (
    classify_quality_signals,
    normalize_legacy_quality_issues,
)


def test_quality_issues_follow_review_workbook_domain_and_preserve_raw_signal() -> None:
    result = classify_quality_signals(
        [
            {
                "scenario_id": "device_motion_sensor_plugin",
                "step": "2",
                "mismatch_type": "EMPTY_VISIBLE",
                "failure_reason": "speech_visible_diverged",
                "final_result": "FAIL",
                "visible_label": "",
                "merged_announcement": "",
            },
            {
                "scenario_id": "life_clothing_care_plugin",
                "step": "2",
                "mismatch_type": "EMPTY_VISIBLE",
                "failure_reason": "terminal_not_handled",
                "final_result": "FAIL",
                "visible_label": "",
                "merged_announcement": "",
            },
            {
                "scenario_id": "life_home_monitor_plugin",
                "step": "4",
                "mismatch_type": "TEXT_MISMATCH",
                "failure_reason": "speech_visible_diverged",
                "final_result": "FAIL",
                "visible_label": "Set up now",
                "merged_announcement": "Set up",
            },
        ]
    )

    assert [item["scenario_id"] for item in result.quality_issues] == [
        "device_motion_sensor_plugin",
        "life_home_monitor_plugin",
    ]
    assert [item["scenario_id"] for item in result.automation_diagnostics] == [
        "life_clothing_care_plugin",
    ]
    assert result.quality_issues[0]["review_domain"] == "qa_accessibility"
    assert result.quality_issues[0]["validator_status"] == "QA_REVIEW"
    assert result.quality_issues[0]["raw_final_result"] == "FAIL"
    assert result.quality_issues[1]["mismatch_type"] == "TEXT_MISMATCH"
    assert result.automation_diagnostics[0]["review_domain"] == "automation_engine"
    assert result.automation_diagnostics[0]["validator_status"] == "AUTOMATION_DIAGNOSTIC"
    assert result.contract == {
        "schema_version": "quality-issues-v1",
        "classification_source": "review_workbook_contract",
        "qa_review_count": 2,
        "automation_diagnostic_count": 1,
        "classification_unavailable_count": 0,
    }


def test_legacy_quality_issues_remain_unclassified_and_are_not_promoted_to_qa() -> None:
    normalized = normalize_legacy_quality_issues(
        [
            {
                "scenario_id": "legacy_scenario",
                "step": "1",
                "final_result": "FAIL",
                "mismatch_type": "EMPTY_VISIBLE",
            }
        ]
    )

    assert normalized[0]["validator_status"] == "CLASSIFICATION_UNAVAILABLE"
    assert normalized[0]["review_domain"] == "unknown"
    assert normalized[0]["classification_source"] == "legacy_summary_raw_signal"
    assert normalized[0]["raw_final_result"] == "FAIL"
    assert "QA_REVIEW" not in normalized[0].values()
