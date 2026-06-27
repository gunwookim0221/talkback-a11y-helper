from tb_runner.coverage_probe_promotion import evaluate_probe_promotion
from tb_runner.coverage_probe_validation import (
    append_validation_aggregate_file,
    build_validation_payload,
)
from tb_runner.excel_report import append_probe_shadow_rows, build_probe_shadow_rows, make_result_df


def _validation(**overrides):
    item = {
        "probe_success": True,
        "probe_success_source": "HELPER_SUCCESS",
        "probe_skipped": False,
        "skip_reason": "",
        "validation_status": "MATCH",
    }
    item.update(overrides)
    return item


def _result(**overrides):
    item = {
        "label": "100%",
        "scenario_id": "motion",
        "tab_name": "Motion Sensor",
        "attempted": True,
        "probe_success": True,
        "probe_success_source": "HELPER_SUCCESS",
        "probe_skipped": False,
        "captured_speech": "100%",
        "captured_visible_text": "100%",
    }
    item.update(overrides)
    return item


def test_match_is_promotable():
    assert evaluate_probe_promotion(_validation()) == {
        "promotion_status": "PROMOTABLE",
        "promotion_reason": "exact_probe_match",
    }


def test_partial_match_is_not_promotable():
    decision = evaluate_probe_promotion(_validation(validation_status="PARTIAL_MATCH"))
    assert decision == {
        "promotion_status": "NOT_PROMOTABLE",
        "promotion_reason": "partial_validation",
    }


def test_helper_success_is_promotable():
    assert evaluate_probe_promotion(_validation(probe_success_source="HELPER_SUCCESS"))["promotion_status"] == "PROMOTABLE"


def test_late_focus_verified_is_promotable():
    assert (
        evaluate_probe_promotion(_validation(probe_success_source="LATE_FOCUS_VERIFIED"))["promotion_status"]
        == "PROMOTABLE"
    )


def test_probe_failed_is_not_promotable():
    decision = evaluate_probe_promotion(_validation(probe_success=False, probe_success_source="FAILED"))
    assert decision["promotion_status"] == "NOT_PROMOTABLE"
    assert decision["promotion_reason"] == "probe_failed"


def test_screen_skip_is_not_promotable():
    decision = evaluate_probe_promotion(
        _validation(
            probe_success=False,
            probe_success_source="FAILED",
            probe_skipped=True,
            skip_reason="screen_not_active",
        )
    )
    assert decision["promotion_status"] == "NOT_PROMOTABLE"
    assert decision["promotion_reason"] == "screen_skip"


def test_environment_skip_is_not_promotable():
    decision = evaluate_probe_promotion(
        _validation(
            probe_success=False,
            probe_success_source="FAILED",
            probe_skipped=True,
            skip_reason="foreground_not_target_app",
        )
    )
    assert decision["promotion_status"] == "NOT_PROMOTABLE"
    assert decision["promotion_reason"] == "environment_skip"


def test_validation_payload_has_correct_promotion_counts():
    payload = build_validation_payload(
        {
            "summary": {},
            "results": [
                _result(),
                _result(
                    label="Motion detected",
                    captured_speech="Motion sensor History",
                    captured_visible_text="Motion sensor History",
                    probe_success_source="LATE_FOCUS_VERIFIED",
                ),
                _result(
                    label="Skipped",
                    attempted=False,
                    probe_success=False,
                    probe_success_source="FAILED",
                    probe_skipped=True,
                    skip_reason="screen_not_active",
                    captured_speech="",
                    captured_visible_text="",
                ),
            ],
        },
        probe_results_path="probe.json",
        output_path="report.xlsx",
    )

    assert payload["summary"]["promotable_count"] == 1
    assert payload["summary"]["not_promotable_count"] == 2
    assert [item["promotion_status"] for item in payload["validations"]] == [
        "PROMOTABLE",
        "NOT_PROMOTABLE",
        "NOT_PROMOTABLE",
    ]


def test_aggregate_has_correct_promotion_counts_and_scenario_summaries(tmp_path):
    output_path = str(tmp_path / "report.xlsx")
    first = build_validation_payload(
        {
            "summary": {},
            "results": [
                _result(),
                _result(
                    label="Motion detected",
                    captured_speech="Motion sensor History",
                    captured_visible_text="Motion sensor History",
                    probe_success_source="LATE_FOCUS_VERIFIED",
                ),
            ],
        },
        probe_results_path="first.json",
        output_path=output_path,
    )
    second = build_validation_payload(
        {"summary": {}, "results": [_result(label="50%", captured_speech="50%", captured_visible_text="50%")]},
        probe_results_path="second.json",
        output_path=output_path,
    )

    append_validation_aggregate_file(first, output_path=output_path, current_scenario_id="scenario_a")
    aggregate = append_validation_aggregate_file(second, output_path=output_path, current_scenario_id="scenario_b")

    assert aggregate["promotable_count"] == 2
    assert aggregate["not_promotable_count"] == 1
    assert [(item["promotable_count"], item["not_promotable_count"]) for item in aggregate["scenarios"]] == [
        (1, 1),
        (1, 0),
    ]
    assert aggregate["scenarios"][0]["summary"]["promotable_count"] == 1
    assert aggregate["scenarios"][0]["summary"]["not_promotable_count"] == 1


def test_shadow_rows_and_existing_pass_rows_are_unchanged():
    import pandas as pd

    traversal = make_result_df(
        pd.DataFrame(
            [
                {
                    "scenario_id": "motion",
                    "tab_name": "Motion Sensor",
                    "step_index": 1,
                    "context_type": "main",
                    "visible_label": "Motion sensor",
                    "merged_announcement": "Motion sensor",
                    "move_result": "moved",
                    "focus_view_id": "MotionSensorCapabilityCardView",
                    "final_result": "PASS",
                }
            ]
        )
    )
    payload = {
        "validations": [
            {
                **_validation(),
                "label": "100%",
                "scenario_id": "motion",
                "captured_speech": "100%",
                "captured_visible_text": "100%",
                "validation_confidence": "HIGH",
            },
            {
                **_validation(
                    validation_status="PARTIAL_MATCH",
                    probe_success_source="LATE_FOCUS_VERIFIED",
                ),
                "label": "Motion detected",
                "scenario_id": "motion",
                "captured_speech": "Motion sensor History",
                "captured_visible_text": "Motion sensor History",
                "validation_confidence": "MEDIUM",
            },
        ]
    }

    shadow_rows = build_probe_shadow_rows(payload)
    appended = append_probe_shadow_rows(traversal, payload)

    assert len(shadow_rows) == 2
    assert [row["final_result"] for row in shadow_rows] == ["SHADOW", "SHADOW"]
    assert [row["promotion_status"] for row in shadow_rows] == ["PROMOTABLE", "NOT_PROMOTABLE"]
    assert appended.iloc[0]["final_result"] == "PASS"
