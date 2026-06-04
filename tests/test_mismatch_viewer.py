import openpyxl

from qa_frontend.backend.mismatch_viewer import get_mismatch_summary_from_xlsx


def test_mismatch_summary_exposes_repeated_issue_metadata(tmp_path):
    output_path = tmp_path / "result.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "result"
    sheet.append(
        [
            "scenario_id",
            "plugin_name",
            "step",
            "visible_label",
            "merged_announcement",
            "mismatch_type",
            "final_result",
            "failure_reason",
            "focus_confidence",
            "context_type",
            "review_note",
            "result_crop_thumbnail",
            "repeat_count",
            "first_step",
            "last_step",
            "steps",
            "is_repeated_issue_group",
        ]
    )
    sheet.append(
        [
            "life_energy_plugin",
            "Energy",
            23,
            "Activity New notification",
            "Activity New notification",
            "LABEL_MISMATCH",
            "FAIL",
            "move_failed",
            "LOW",
            "main",
            "반복 이슈 group (3 rows)",
            "",
            3,
            23,
            25,
            "23,24,25",
            True,
        ]
    )
    workbook.save(output_path)
    workbook.close()

    summary = get_mismatch_summary_from_xlsx(output_path)

    signal = summary["signals"][0]
    assert signal["repeat_count"] == 3
    assert signal["first_step"] == "23"
    assert signal["last_step"] == "25"
    assert signal["steps"] == "23,24,25"
    assert signal["is_repeated_issue_group"] is True
