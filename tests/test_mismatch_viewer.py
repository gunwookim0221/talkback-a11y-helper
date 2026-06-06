import openpyxl

from qa_frontend.backend.mismatch_viewer import get_mismatch_summary_from_xlsx


RESULT_HEADERS = [
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


def _write_result_workbook(path, rows):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "result"
    sheet.append(RESULT_HEADERS)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def test_mismatch_summary_exposes_repeated_issue_metadata(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_result_workbook(
        output_path,
        [[
            "life_energy_plugin",
            "Energy",
            23,
            "Activity New notification",
            "Activity",
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
        ]]
    )

    summary = get_mismatch_summary_from_xlsx(output_path)

    signal = summary["signals"][0]
    assert signal["repeat_count"] == 3
    assert signal["first_step"] == "23"
    assert signal["last_step"] == "25"
    assert signal["steps"] == "23,24,25"
    assert signal["is_repeated_issue_group"] is True


def test_exact_match_fail_is_clean_and_excluded_from_quality_preview(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_result_workbook(
        output_path,
        [[
            "life_family_care_plugin",
            "Family Care",
            4,
            "Set up now",
            "Set up now",
            "EXACT_MATCH",
            "FAIL",
            "move_failed",
            "LOW",
            "main",
            "speech와 visible 불일치",
            "",
            1,
            4,
            4,
            "4",
            False,
        ]],
    )

    summary = get_mismatch_summary_from_xlsx(output_path)

    assert summary["summary"]["clean_count"] == 1
    assert summary["summary"]["fail_count"] == 0
    assert summary["summary"]["issue_count"] == 0
    assert summary["signals"] == []


def test_empty_visible_with_empty_speech_is_review_and_excluded_from_quality_preview(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_result_workbook(
        output_path,
        [[
            "life_home_monitor_plugin",
            "Home Monitor",
            1,
            "",
            "",
            "EMPTY_VISIBLE",
            "FAIL",
            "",
            "HIGH",
            "main",
            "이동/발화 결과 재검토 필요",
            "",
            1,
            1,
            1,
            "1",
            False,
        ]],
    )

    summary = get_mismatch_summary_from_xlsx(output_path)

    assert summary["summary"]["review_count"] == 1
    assert summary["summary"]["issue_count"] == 0
    assert summary["summary"]["empty_visible"] == 1
    assert summary["signals"] == []


def test_empty_visible_with_speech_is_issue_and_included_in_quality_preview(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_result_workbook(
        output_path,
        [[
            "device_camera_plugin",
            "Camera",
            8,
            "",
            "Camera",
            "EMPTY_VISIBLE",
            "FAIL",
            "",
            "LOW",
            "main",
            "이동/발화 결과 재검토 필요",
            "",
            1,
            8,
            8,
            "8",
            False,
        ]],
    )

    summary = get_mismatch_summary_from_xlsx(output_path)

    assert summary["summary"]["issue_count"] == 1
    assert summary["summary"]["fail_count"] == 0
    assert len(summary["signals"]) == 1
    assert summary["signals"][0]["top_category"] == "ISSUE"


def test_empty_speech_with_visible_is_fail_and_included_in_quality_preview(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_result_workbook(
        output_path,
        [[
            "device_lock_plugin",
            "Door Lock",
            2,
            "Lock",
            "",
            "EMPTY_SPEECH",
            "FAIL",
            "",
            "LOW",
            "main",
            "이동/발화 결과 재검토 필요",
            "",
            1,
            2,
            2,
            "2",
            False,
        ]],
    )

    summary = get_mismatch_summary_from_xlsx(output_path)

    assert summary["summary"]["fail_count"] == 1
    assert summary["summary"]["issue_count"] == 0
    assert len(summary["signals"]) == 1
    assert summary["signals"][0]["top_category"] == "FAIL"


def test_quality_preview_only_contains_fail_or_issue_categories(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_result_workbook(
        output_path,
        [
            [
                "clean_fail_runtime",
                "Clean Runtime",
                1,
                "Ready",
                "Ready",
                "EXACT_MATCH",
                "FAIL",
                "move_failed",
                "LOW",
                "main",
                "speech와 visible 불일치",
                "",
                1,
                1,
                1,
                "1",
                False,
            ],
            [
                "review_empty_empty",
                "Review",
                1,
                "",
                "",
                "EMPTY_VISIBLE",
                "FAIL",
                "",
                "HIGH",
                "main",
                "이동/발화 결과 재검토 필요",
                "",
                1,
                1,
                1,
                "1",
                False,
            ],
            [
                "issue_empty_visible",
                "Issue",
                1,
                "",
                "Issue speech",
                "EMPTY_VISIBLE",
                "FAIL",
                "",
                "LOW",
                "main",
                "이동/발화 결과 재검토 필요",
                "",
                1,
                1,
                1,
                "1",
                False,
            ],
        ],
    )

    summary = get_mismatch_summary_from_xlsx(output_path)

    assert summary["summary"]["clean_count"] == 1
    assert summary["summary"]["review_count"] == 1
    assert summary["summary"]["issue_count"] == 1
    assert [signal["scenario_id"] for signal in summary["signals"]] == ["issue_empty_visible"]
    assert all(signal["top_category"] in {"FAIL", "ISSUE"} for signal in summary["signals"])
