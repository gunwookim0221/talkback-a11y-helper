import json

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")

from tb_runner.excel_report import (
    PROBE_PROMOTED_ROW_SOURCE,
    PROBE_SHADOW_ROW_SOURCE,
    append_probe_promoted_rows,
    append_probe_shadow_rows,
    make_result_df,
    save_excel,
)


def _validation(label="100%", status="MATCH", **overrides):
    item = {
        "label": label,
        "scenario_id": "device_motion_sensor_plugin",
        "probe_success": True,
        "probe_success_source": "HELPER_SUCCESS",
        "probe_target_view_id": "probeValue",
        "probe_bounds": "10,20,110,120",
        "captured_speech": label,
        "captured_visible_text": label,
        "validation_status": status,
        "validation_confidence": "HIGH",
        "promotion_status": "PROMOTABLE" if status == "MATCH" else "NOT_PROMOTABLE",
        "promotion_reason": "exact_probe_match" if status == "MATCH" else "partial_validation",
    }
    item.update(overrides)
    return item


def _payload(*items):
    return {"validations": list(items)}


def _traversal(label="Motion sensor", **overrides):
    row = {
        "scenario_id": "device_motion_sensor_plugin",
        "step_index": 1,
        "context_type": "main",
        "visible_label": label,
        "merged_announcement": label,
        "move_result": "moved",
        "focus_view_id": "MotionSensorCapabilityCardView",
        "focus_bounds": "0,0,500,500",
        "final_result": "PASS",
    }
    row.update(overrides)
    return make_result_df(pd.DataFrame([row]))


def _append(result_df, *validations):
    with_shadow = append_probe_shadow_rows(result_df, _payload(*validations))
    return append_probe_promoted_rows(with_shadow)


def test_promotable_match_creates_one_promoted_pass_row():
    result = _append(_traversal(), _validation())
    promoted = result.loc[result["row_source"] == PROBE_PROMOTED_ROW_SOURCE]

    assert len(promoted) == 1
    assert promoted.iloc[0]["final_result"] == "PASS"
    assert promoted.iloc[0]["promotion_applied"]


def test_not_promotable_match_does_not_create_promoted_row():
    result = _append(
        _traversal(),
        _validation(promotion_status="NOT_PROMOTABLE", promotion_reason="unsupported_success_source"),
    )

    assert PROBE_PROMOTED_ROW_SOURCE not in result["row_source"].tolist()


def test_partial_match_does_not_create_promoted_row():
    result = _append(_traversal(), _validation("Motion detected", "PARTIAL_MATCH"))

    assert PROBE_PROMOTED_ROW_SOURCE not in result["row_source"].tolist()


def test_failed_probe_shadow_cannot_be_promoted():
    with_shadow = append_probe_shadow_rows(_traversal(), _payload(_validation()))
    shadow_index = with_shadow.index[with_shadow["row_source"] == PROBE_SHADOW_ROW_SOURCE][0]
    with_shadow.at[shadow_index, "_probe_success"] = False

    result = append_probe_promoted_rows(with_shadow)

    assert PROBE_PROMOTED_ROW_SOURCE not in result["row_source"].tolist()


def test_existing_traversal_row_remains_unchanged():
    original = _traversal()
    result = _append(original, _validation())

    pd.testing.assert_series_equal(
        result.iloc[0][original.columns],
        original.iloc[0],
        check_names=False,
    )


def test_shadow_row_remains_and_keeps_shadow_result():
    result = _append(_traversal(), _validation())
    shadow = result.loc[result["row_source"] == PROBE_SHADOW_ROW_SOURCE]

    assert len(shadow) == 1
    assert shadow.iloc[0]["final_result"] == "SHADOW"
    assert shadow.iloc[0]["visible_label"] == "100%"


def test_promoted_rows_are_appended_after_all_shadow_rows():
    result = _append(
        _traversal(),
        _validation("100%"),
        _validation("Battery 50%", probe_target_view_id="battery", probe_bounds="20,30,120,130"),
    )
    sources = result["row_source"].tolist()

    assert sources == [
        "",
        PROBE_SHADOW_ROW_SOURCE,
        PROBE_SHADOW_ROW_SOURCE,
        PROBE_PROMOTED_ROW_SOURCE,
        PROBE_PROMOTED_ROW_SOURCE,
    ]


def test_duplicate_normal_label_prevents_promoted_duplicate():
    result = _append(_traversal("100%"), _validation("100%"))

    assert PROBE_PROMOTED_ROW_SOURCE not in result["row_source"].tolist()


def test_dedup_skip_reason_is_recorded_on_shadow_row():
    result = _append(_traversal("100%"), _validation("100%"))
    shadow = result.loc[result["row_source"] == PROBE_SHADOW_ROW_SOURCE].iloc[0]

    assert shadow["promotion_applied"] is False or not bool(shadow["promotion_applied"])
    assert shadow["promotion_dedup_status"] == "SKIPPED"
    assert shadow["promotion_dedup_reason"] == "existing_production_row_match:speech,visible_label"


def test_dedup_uses_resource_id_and_bounds_in_same_scenario():
    result = _append(
        _traversal(
            "Different",
            merged_announcement="Different speech",
            focus_view_id="probeValue",
            focus_bounds="[10,20][110,120]",
        ),
        _validation("100%"),
    )
    shadow = result.loc[result["row_source"] == PROBE_SHADOW_ROW_SOURCE].iloc[0]

    assert shadow["promotion_dedup_status"] == "SKIPPED"
    assert shadow["promotion_dedup_reason"] == "existing_production_row_match:bounds,resource_id"


def test_promotion_summary_counts_promotable_promoted_and_dedup_skipped():
    result = _append(
        _traversal("Existing"),
        _validation("Existing"),
        _validation("New value", probe_target_view_id="newValue", probe_bounds="30,40,130,140"),
        _validation("Partial", "PARTIAL_MATCH"),
    )

    assert result.attrs["probe_promotion_summary"] == {
        "promotable_count": 2,
        "promoted_row_count": 1,
        "promotion_dedup_skipped_count": 1,
    }


def test_generated_xlsx_exports_shadow_then_promoted_rows_and_metadata(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    validation_path = tmp_path / "talkback_compare.coverage_probe_validation.json"
    validation_path.write_text(
        json.dumps(_payload(_validation("100%")), ensure_ascii=False),
        encoding="utf-8",
    )

    save_excel(
        [
            {
                "scenario_id": "device_motion_sensor_plugin",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Motion sensor",
                "merged_announcement": "Motion sensor",
                "move_result": "moved",
                "focus_view_id": "MotionSensorCapabilityCardView",
            }
        ],
        str(output_path),
        with_images=False,
    )

    worksheet = openpyxl.load_workbook(output_path)["result"]
    headers = [cell.value for cell in worksheet[1]]
    row_source_col = headers.index("row_source") + 1
    final_result_col = headers.index("final_result") + 1
    applied_col = headers.index("promotion_applied") + 1
    dedup_status_col = headers.index("promotion_dedup_status") + 1
    dedup_reason_col = headers.index("promotion_dedup_reason") + 1

    assert worksheet.cell(3, row_source_col).value == PROBE_SHADOW_ROW_SOURCE
    assert worksheet.cell(4, row_source_col).value == PROBE_PROMOTED_ROW_SOURCE
    assert worksheet.cell(4, final_result_col).value == "PASS"
    assert worksheet.cell(4, applied_col).value is True
    assert worksheet.cell(4, dedup_status_col).value == "PROMOTED"
    assert worksheet.cell(4, dedup_reason_col).value == "no_existing_production_match"
