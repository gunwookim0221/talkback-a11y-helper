import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")

from tb_runner.excel_report import (
    add_status_columns,
    make_filtered_df,
    make_result_df,
    save_excel,
    make_summary_df,
)


def test_add_status_columns_falls_back_without_merged_announcement():
    df = pd.DataFrame(
        [
            {
                "announcement": "Selected, Devices, Tab 2 of 5, New content available",
                "text": "Devices",
            }
        ]
    )

    result = add_status_columns(df.copy())

    assert result.loc[0, "speech_main"] == "devices"
    assert "selected" in result.loc[0, "speech_status_tokens"]
    assert result.loc[0, "visible_main"] == "devices"


def test_add_status_columns_handles_missing_source_columns_and_empty_df():
    empty_df = pd.DataFrame()

    result = add_status_columns(empty_df.copy())
    filtered = make_filtered_df(result)
    summary = make_summary_df(result, filtered)

    assert "speech_main" in result.columns
    assert "visible_main" in result.columns
    assert len(result) == 0
    assert len(filtered) == 0
    assert int(summary.loc[summary["metric"] == "raw_rows", "value"].iloc[0]) == 0


def test_make_result_df_generates_pass_warn_fail_rows():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s1",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Notifications",
                "merged_announcement": "Notifications",
                "move_result": "moved",
                "focus_view_id": "id/noti",
                "focus_bounds": "[0,0][10,10]",
                "fallback_used": False,
                "step_dump_used": False,
                "req_id": "r1",
                "step_elapsed_sec": 0.1,
            },
            {
                "scenario_id": "s1",
                "tab_name": "main",
                "step_index": 2,
                "context_type": "main",
                "visible_label": "Step 2",
                "merged_announcement": "Smart Things Cooking Step 2",
                "move_result": "moved",
                "focus_view_id": "id/step2",
                "focus_bounds": "[0,10][10,20]",
                "fallback_used": False,
                "step_dump_used": False,
                "req_id": "r2",
                "step_elapsed_sec": 0.2,
            },
            {
                "scenario_id": "s2",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "블루베리핫케이크 만드는 법",
                "merged_announcement": "Smart Things Cooking",
                "move_result": "failed",
                "focus_view_id": "id/fail",
                "focus_bounds": "[0,20][10,30]",
                "fallback_used": True,
                "step_dump_used": True,
                "req_id": "repeat_no_progress",
                "step_elapsed_sec": 0.3,
            },
        ]
    )

    result = make_result_df(filtered_df)

    assert list(result.columns)[:4] == ["scenario_id", "tab", "step", "context_type"]
    assert "final_result" in result.columns
    assert set(result["final_result"].tolist()) == {"PASS", "WARN", "FAIL"}
    assert "speech_visible_diverged" in set(result["failure_reason"].tolist())
    assert result.columns[-1] == "crop_image_path"


def test_save_excel_adds_result_crop_hyperlink(tmp_path):
    crop_file = tmp_path / "crops" / "sample_step_1.png"
    crop_file.parent.mkdir(parents=True, exist_ok=True)
    crop_file.write_bytes(b"fake")

    rows = [
        {
            "scenario_id": "s1",
            "tab_name": "home",
            "step_index": 1,
            "context_type": "main",
            "visible_label": "Home",
            "merged_announcement": "Home",
            "move_result": "moved",
            "focus_view_id": "id/home",
            "focus_bounds": "[0,0][10,10]",
            "fallback_used": False,
            "step_dump_used": False,
            "req_id": "r1",
            "step_elapsed_sec": 0.1,
            "crop_image_path": str(crop_file),
        }
    ]
    output_path = tmp_path / "report.xlsx"

    save_excel(rows, str(output_path), with_images=False)

    wb = openpyxl.load_workbook(output_path)
    ws = wb["result"]
    headers = [cell.value for cell in ws[1]]
    crop_col_idx = headers.index("crop_image_path") + 1
    crop_cell = ws.cell(row=2, column=crop_col_idx)

    assert headers[-1] == "crop_image_path"
    assert crop_cell.value == crop_file.name
    assert crop_cell.hyperlink is not None
    assert crop_cell.hyperlink.target == str(crop_file)


def test_save_excel_handles_windows_style_crop_path_without_row_warn_spam(tmp_path, monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr("tb_runner.excel_report.log", lambda msg, level="NORMAL": logs.append(msg))
    windows_style_path = r"output\talkback_compare_20260406_151119\crops\file.png"

    rows = [
        {
            "scenario_id": "s1",
            "tab_name": "home",
            "step_index": 1,
            "context_type": "main",
            "visible_label": "Home",
            "merged_announcement": "Home",
            "move_result": "moved",
            "focus_view_id": "id/home",
            "focus_bounds": "[0,0][10,10]",
            "fallback_used": False,
            "step_dump_used": False,
            "req_id": "r1",
            "step_elapsed_sec": 0.1,
            "crop_image_path": windows_style_path,
        },
    ]
    output_path = tmp_path / "report_windows_path.xlsx"

    save_excel(rows, str(output_path), with_images=False)

    wb = openpyxl.load_workbook(output_path)
    ws = wb["result"]
    headers = [cell.value for cell in ws[1]]
    crop_col_idx = headers.index("crop_image_path") + 1
    crop_cell = ws.cell(row=2, column=crop_col_idx)

    assert crop_cell.value == "file.png"
    assert not any("row=" in message for message in logs)


def test_save_excel_summarizes_skipped_crop_hyperlink_warning(tmp_path, monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr("tb_runner.excel_report.log", lambda msg, level="NORMAL": logs.append(msg))

    rows = []
    for idx in range(2):
        rows.append(
            {
                "scenario_id": "s1",
                "tab_name": "home",
                "step_index": idx + 1,
                "context_type": "main",
                "visible_label": "Home",
                "merged_announcement": "Home",
                "move_result": "moved",
                "focus_view_id": "id/home",
                "focus_bounds": "[0,0][10,10]",
                "fallback_used": False,
                "step_dump_used": False,
                "req_id": f"r{idx}",
                "step_elapsed_sec": 0.1,
                "crop_image_path": f"output/crops/file_{idx}.txt",
            }
        )

    output_path = tmp_path / "report_skip_warn.xlsx"
    save_excel(rows, str(output_path), with_images=False)

    warn_logs = [message for message in logs if "result crop hyperlink skipped" in message]
    assert len(warn_logs) == 1
    assert "2 rows" in warn_logs[0]
