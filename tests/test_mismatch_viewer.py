import json

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


def _write_probe_workbook(path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "result"
    sheet.append(RESULT_HEADERS + ["row_source", "promotion_dedup_status"])
    base_row = [
        "device_motion_sensor_plugin",
        "Motion Sensor",
        1,
        "100%",
        "100%",
        "EXACT_MATCH",
        "PASS",
        "",
        "HIGH",
        "main",
        "",
        "",
        1,
        1,
        1,
        "1",
        False,
    ]
    sheet.append(base_row + ["COVERAGE_PROBE_SHADOW", "SKIPPED"])
    sheet.append(base_row + ["COVERAGE_PROBE_PROMOTED", "PROMOTED"])
    workbook.save(path)
    workbook.close()


def test_coverage_probe_summary_prefers_aggregate_artifacts(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_probe_workbook(output_path)
    (tmp_path / "result.coverage_probe_validation.aggregate.json").write_text(
        json.dumps(
            {
                "promotable_count": 10,
                "total_screen_skipped_count": 2,
                "total_scenario_filtered_count": 7,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "result.coverage_probe_validation.json").write_text(
        json.dumps({"summary": {"promotable_count": 1}}),
        encoding="utf-8",
    )
    (tmp_path / "result.coverage_probe_results.aggregate.json").write_text(
        json.dumps(
            {
                "total_candidate_count": 24,
                "total_attempted_count": 23,
                "total_success_count": 18,
                "total_failed_count": 5,
            }
        ),
        encoding="utf-8",
    )

    response = get_mismatch_summary_from_xlsx(output_path)
    summary = response["coverage_probe_summary"]

    assert summary == {
        "available": True,
        "source": "aggregate",
        "results_artifact": "result.coverage_probe_results.aggregate.json",
        "validation_artifact": "result.coverage_probe_validation.aggregate.json",
        "candidate_count": 24,
        "attempted_count": 23,
        "success_count": 18,
        "failed_count": 5,
        "match_count": 0,
        "promotable_count": 10,
        "not_promotable_count": 0,
        "promoted_row_count": 1,
        "dedup_skipped_count": 1,
        "screen_skipped_count": 2,
        "scenario_filtered_count": 7,
    }
    assert response["coverage_probe"] == summary


def test_coverage_probe_summary_falls_back_to_per_scenario_artifacts(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_probe_workbook(output_path)
    (tmp_path / "result.coverage_probe_validation.json").write_text(
        json.dumps(
            {
                "summary": {
                    "promotable_count": 3,
                    "screen_skipped_count": 1,
                    "scenario_filtered_count": 4,
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "result.coverage_probe_results.json").write_text(
        json.dumps(
            {
                "summary": {
                    "candidate_count": 6,
                    "attempted_count": 5,
                    "success_count": 4,
                    "failed_count": 1,
                }
            }
        ),
        encoding="utf-8",
    )

    summary = get_mismatch_summary_from_xlsx(output_path)["coverage_probe_summary"]

    assert summary["source"] == "scenario"
    assert summary["results_artifact"] == "result.coverage_probe_results.json"
    assert summary["validation_artifact"] == "result.coverage_probe_validation.json"
    assert summary["candidate_count"] == 6
    assert summary["attempted_count"] == 5
    assert summary["success_count"] == 4
    assert summary["failed_count"] == 1
    assert summary["promotable_count"] == 3
    assert summary["screen_skipped_count"] == 1
    assert summary["scenario_filtered_count"] == 4


def test_coverage_probe_summary_is_unavailable_without_validation_artifact(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_probe_workbook(output_path)

    summary = get_mismatch_summary_from_xlsx(output_path)

    assert summary["coverage_probe_summary"] == {
        "available": False,
        "source": "none",
        "results_artifact": None,
        "validation_artifact": None,
    }
    assert summary["coverage_probe"] == summary["coverage_probe_summary"]


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


def test_empty_visible_with_empty_speech_and_fail_result_is_fail_and_included_in_quality_preview(tmp_path):
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

    assert summary["summary"]["fail_count"] == 1
    assert summary["summary"]["issue_count"] == 0
    assert summary["summary"]["empty_visible"] == 1
    assert len(summary["signals"]) == 1
    assert summary["signals"][0]["top_category"] == "FAIL"


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
    assert summary["summary"]["fail_count"] == 1
    assert summary["summary"]["issue_count"] == 1
    assert [signal["scenario_id"] for signal in summary["signals"]] == ["review_empty_empty", "issue_empty_visible"]
    assert all(signal["top_category"] in {"FAIL", "ISSUE"} for signal in summary["signals"])


def test_result_sheet_fail_rows_are_counted_in_run_history_summary(tmp_path):
    output_path = tmp_path / "result.xlsx"
    _write_result_workbook(
        output_path,
        [
            [
                "menu_main",
                "Menu",
                1,
                "",
                "",
                "EMPTY_VISIBLE",
                "FAIL",
                "",
                "HIGH",
                "main",
                "",
                "",
                1,
                1,
                1,
                "1",
                False,
            ],
            [
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
                "",
                "",
                1,
                1,
                1,
                "1",
                False,
            ],
            [
                "life_energy_plugin",
                "Energy",
                2,
                "Energy",
                "Energy",
                "NORMALIZED_MATCH",
                "PASS",
                "",
                "HIGH",
                "main",
                "",
                "",
                1,
                2,
                2,
                "2",
                False,
            ],
            [
                "life_family_care_plugin",
                "Family Care",
                3,
                "Profile",
                "Profile settings",
                "PARTIAL_MATCH",
                "WARN",
                "",
                "MEDIUM",
                "main",
                "",
                "",
                1,
                3,
                3,
                "3",
                False,
            ],
        ],
    )

    summary = get_mismatch_summary_from_xlsx(output_path)

    assert summary["summary"]["fail_count"] == 2
    assert summary["summary"]["issue_count"] == 0
    assert summary["summary"]["review_count"] == 1
    assert summary["summary"]["clean_count"] == 1
