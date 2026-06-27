import json

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")

from tb_runner.excel_report import (
    PROBE_SHADOW_ROW_SOURCE,
    append_probe_shadow_rows,
    build_probe_shadow_rows,
    make_result_df,
    save_excel,
)


def _validation(label="100%", status="MATCH", success=True, **overrides):
    base = {
        "label": label,
        "normalized_label": label.lower(),
        "scenario_id": "device_motion_sensor_plugin",
        "tab_name": "Motion Sensor",
        "view_id": "lowBattery",
        "probe_success": success,
        "probe_success_source": "HELPER_SUCCESS",
        "probe_intent": "VERIFY_RELATED_BOUNDS",
        "probe_target_strategy": "original_bounds",
        "probe_target_view_id": "lowBattery",
        "captured_speech": label,
        "captured_visible_text": label,
        "validation_status": status,
        "validation_reason": "exact_normalized_match",
        "validation_confidence": "HIGH",
    }
    base.update(overrides)
    return base


def _payload(*validations):
    return {
        "schema_version": 1,
        "source": "v8_coverage_probe_validation",
        "validations": list(validations),
    }


def _traversal_df(final_result="PASS"):
    return pd.DataFrame(
        [
            {
                "scenario_id": "device_motion_sensor_plugin",
                "tab_name": "Motion Sensor",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Motion sensor",
                "merged_announcement": "Motion sensor",
                "move_result": "moved",
                "focus_view_id": "MotionSensorCapabilityCardView",
                "final_result": final_result,
            }
        ]
    )


def test_match_validation_creates_one_shadow_row():
    rows = build_probe_shadow_rows(_payload(_validation("100%", "MATCH")))

    assert len(rows) == 1
    assert rows[0]["row_source"] == PROBE_SHADOW_ROW_SOURCE
    assert rows[0]["final_result"] == "SHADOW"
    assert rows[0]["probe_validation_status"] == "MATCH"


def test_partial_match_validation_creates_one_shadow_row():
    rows = build_probe_shadow_rows(
        _payload(
            _validation(
                "Motion detected",
                "PARTIAL_MATCH",
                probe_success_source="LATE_FOCUS_VERIFIED",
                probe_target_strategy="promote_to_enclosing_actionable_container",
                captured_speech="Motion sensor History",
                captured_visible_text="Motion sensor History",
                validation_confidence="MEDIUM",
            )
        )
    )

    assert len(rows) == 1
    assert rows[0]["visible_label"] == "Motion detected"
    assert rows[0]["probe_validation_status"] == "PARTIAL_MATCH"
    assert rows[0]["probe_validation_confidence"] == "MEDIUM"
    assert rows[0]["probe_success_source"] == "LATE_FOCUS_VERIFIED"


def test_mismatch_validation_does_not_create_shadow_row():
    assert build_probe_shadow_rows(_payload(_validation("Motion detected", "MISMATCH"))) == []


def test_not_validated_does_not_create_shadow_row():
    assert build_probe_shadow_rows(_payload(_validation("Motion detected", "NOT_VALIDATED", success=False))) == []


def test_shadow_rows_append_after_existing_rows_and_do_not_mutate_existing_result():
    result_df = make_result_df(_traversal_df("PASS"))
    appended = append_probe_shadow_rows(result_df, _payload(_validation("100%", "MATCH")))

    assert len(appended) == len(result_df) + 1
    assert appended.iloc[0]["visible_label"] == result_df.iloc[0]["visible_label"]
    assert appended.iloc[0]["final_result"] == "PASS"
    assert appended.iloc[-1]["row_source"] == PROBE_SHADOW_ROW_SOURCE
    assert appended.iloc[-1]["final_result"] == "SHADOW"


def test_existing_warn_fail_values_are_unchanged_by_shadow_append():
    result_df = make_result_df(
        pd.DataFrame(
            [
                {
                    "scenario_id": "s1",
                    "tab_name": "main",
                    "step_index": 1,
                    "context_type": "main",
                    "visible_label": "A",
                    "merged_announcement": "A",
                    "move_result": "moved",
                },
                {
                    "scenario_id": "s1",
                    "tab_name": "main",
                    "step_index": 2,
                    "context_type": "main",
                    "visible_label": "B",
                    "merged_announcement": "C",
                    "move_result": "failed",
                },
            ]
        )
    )
    before = result_df["final_result"].tolist()
    appended = append_probe_shadow_rows(result_df, _payload(_validation("100%", "MATCH")))

    assert appended["final_result"].tolist()[: len(before)] == before
    assert appended["final_result"].tolist()[-1] == "SHADOW"


def test_generated_xlsx_contains_probe_shadow_columns_and_appended_row(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    validation_path = tmp_path / "talkback_compare.coverage_probe_validation.json"
    validation_path.write_text(
        json.dumps(
            _payload(
                _validation("100%", "MATCH"),
                _validation(
                    "Motion detected",
                    "PARTIAL_MATCH",
                    probe_success_source="LATE_FOCUS_VERIFIED",
                    captured_speech="Motion sensor History",
                    captured_visible_text="Motion sensor History",
                    validation_confidence="MEDIUM",
                ),
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    save_excel(_traversal_df().to_dict("records"), str(output_path), with_images=False)

    workbook = openpyxl.load_workbook(output_path)
    worksheet = workbook["result"]
    headers = [cell.value for cell in worksheet[1]]
    assert "row_source" in headers
    assert "probe_validation_status" in headers
    assert "probe_success_source" in headers

    row_source_col = headers.index("row_source") + 1
    status_col = headers.index("probe_validation_status") + 1
    final_col = headers.index("final_result") + 1
    visible_col = headers.index("visible_label") + 1

    assert worksheet.cell(row=2, column=final_col).value == "PASS"
    assert worksheet.cell(row=3, column=row_source_col).value == PROBE_SHADOW_ROW_SOURCE
    assert worksheet.cell(row=3, column=visible_col).value == "100%"
    assert worksheet.cell(row=3, column=status_col).value == "MATCH"
    assert worksheet.cell(row=4, column=row_source_col).value == PROBE_SHADOW_ROW_SOURCE
    assert worksheet.cell(row=4, column=visible_col).value == "Motion detected"
    assert worksheet.cell(row=4, column=status_col).value == "PARTIAL_MATCH"


def test_generated_xlsx_prefers_aggregate_probe_validation(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    per_scenario_path = tmp_path / "talkback_compare.coverage_probe_validation.json"
    aggregate_path = tmp_path / "talkback_compare.coverage_probe_validation.aggregate.json"
    per_scenario_path.write_text(
        json.dumps(_payload(_validation("Last scenario only", "MATCH")), ensure_ascii=False),
        encoding="utf-8",
    )
    aggregate_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "v8_probe_validation_aggregate",
                "validations": [
                    _validation("Water Leak 100%", "MATCH", scenario_id="device_water_leak_sensor_plugin"),
                    _validation("Motion 100%", "PARTIAL_MATCH"),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    save_excel(_traversal_df().to_dict("records"), str(output_path), with_images=False)

    worksheet = openpyxl.load_workbook(output_path)["result"]
    headers = [cell.value for cell in worksheet[1]]
    visible_col = headers.index("visible_label") + 1
    row_source_col = headers.index("row_source") + 1
    shadow_labels = [
        worksheet.cell(row=row_index, column=visible_col).value
        for row_index in range(2, worksheet.max_row + 1)
        if worksheet.cell(row=row_index, column=row_source_col).value == PROBE_SHADOW_ROW_SOURCE
    ]
    assert shadow_labels == ["Water Leak 100%", "Motion 100%"]


def test_generated_xlsx_falls_back_to_per_scenario_validation_without_aggregate(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    validation_path = tmp_path / "talkback_compare.coverage_probe_validation.json"
    validation_path.write_text(
        json.dumps(_payload(_validation("Fallback match", "MATCH")), ensure_ascii=False),
        encoding="utf-8",
    )

    save_excel(_traversal_df().to_dict("records"), str(output_path), with_images=False)

    worksheet = openpyxl.load_workbook(output_path)["result"]
    headers = [cell.value for cell in worksheet[1]]
    visible_col = headers.index("visible_label") + 1
    row_source_col = headers.index("row_source") + 1
    shadow_labels = [
        worksheet.cell(row=row_index, column=visible_col).value
        for row_index in range(2, worksheet.max_row + 1)
        if worksheet.cell(row=row_index, column=row_source_col).value == PROBE_SHADOW_ROW_SOURCE
    ]
    assert shadow_labels == ["Fallback match"]
