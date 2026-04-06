import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
from PIL import Image

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
    assert result.columns[-4] == "debug_log_path"
    assert result.columns[-3] == "debug_log_name"
    assert result.columns[-2] == "crop_image_path"
    assert result.columns[-1] == "result_crop_thumbnail"


def test_make_result_df_uses_get_focus_req_id_when_req_id_missing():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s_req",
                "tab_name": "home",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Home",
                "merged_announcement": "Home",
                "move_result": "failed",
                "focus_view_id": "id/home",
                "focus_bounds": "[0,0][10,10]",
                "fallback_used": False,
                "step_dump_used": False,
                "get_focus_req_id": "focus_req_123",
                "step_elapsed_sec": 0.2,
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["req_id"] == "focus_req_123"


def test_make_result_df_skips_anchor_baseline_rows(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr("tb_runner.excel_report.log", lambda msg, level="NORMAL": logs.append(msg))

    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s1",
                "tab_name": "main",
                "step_index": 0,
                "context_type": "main",
                "status": "ANCHOR",
                "visible_label": "Navigate up",
                "merged_announcement": "Navigate up",
                "move_result": "",
            },
            {
                "scenario_id": "s1",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "status": "OK",
                "visible_label": "Notifications",
                "merged_announcement": "Notifications",
                "move_result": "moved",
            },
        ]
    )

    result = make_result_df(filtered_df)

    assert len(result) == 1
    assert int(result.iloc[0]["step"]) == 1
    assert result.iloc[0]["final_result"] == "PASS"
    assert any("[RESULT] skipped anchor rows count=1" in msg for msg in logs)


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

    assert "crop_image_path" in headers
    assert crop_cell.value == crop_file.name
    assert crop_cell.hyperlink is not None
    assert crop_cell.hyperlink.target == str(crop_file.resolve())


def test_save_excel_writes_debug_log_only_for_warn_fail_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tb_runner.excel_report.get_recent_logs",
        lambda limit=200: [
            "[12:00:00] [STEP] START tab='home' step=2",
            "[12:00:01] [ROW] fingerprint='abc'",
            "[12:00:02] [STOP][eval] step=2 decision='stop' reason='repeat_no_progress'",
            "[12:00:03] [STEP] END tab='home' step=2 req_id='repeat_no_progress'",
        ],
    )

    rows = [
        {
            "scenario_id": "s_pass",
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
            "req_id": "r_pass",
            "step_elapsed_sec": 0.1,
        },
        {
            "scenario_id": "s_fail",
            "tab_name": "home",
            "step_index": 2,
            "context_type": "main",
            "visible_label": "Step 2",
            "merged_announcement": "Smart Things Cooking",
            "move_result": "failed",
            "focus_view_id": "id/fail",
            "focus_bounds": "[0,10][10,20]",
            "fallback_used": True,
            "step_dump_used": True,
            "req_id": "repeat_no_progress",
            "step_elapsed_sec": 0.2,
        },
    ]
    output_path = tmp_path / "report_debug_logs.xlsx"
    save_excel(rows, str(output_path), with_images=False)

    debug_dir = tmp_path / "debug_logs"
    debug_files = list(debug_dir.glob("*.log"))
    assert len(debug_files) == 1
    assert "s_fail_step_2_req_repeat_no_progress.log" == debug_files[0].name
    content = debug_files[0].read_text(encoding="utf-8")
    assert "[ROW_CONTEXT]" in content
    assert "final_result=FAIL" in content
    assert "[ANN_TRACE]" in content
    assert "[ANN][baseline]" in content
    assert "[ANN][poll]" in content
    assert "[ANN][stable]" in content
    assert "[ANN][select]" in content
    assert "[STEP_TRACE]" in content
    assert "[SCROLL_TRACE]" in content
    assert "[FOCUS_TRACE]" in content

    wb = openpyxl.load_workbook(output_path)
    ws = wb["result"]
    headers = [cell.value for cell in ws[1]]
    debug_col_idx = headers.index("debug_log_path") + 1
    pass_debug_cell = ws.cell(row=2, column=debug_col_idx)
    fail_debug_cell = ws.cell(row=3, column=debug_col_idx)

    assert pass_debug_cell.value in {"", None}
    assert fail_debug_cell.value == debug_files[0].name
    assert fail_debug_cell.hyperlink is not None
    assert fail_debug_cell.hyperlink.target == str(debug_files[0].resolve())


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


def test_save_excel_with_images_false_skips_result_thumbnail_and_keeps_status_color(tmp_path):
    pass_crop = tmp_path / "crops" / "pass.png"
    warn_crop = tmp_path / "crops" / "warn.png"
    fail_crop = tmp_path / "crops" / "fail.png"
    pass_crop.parent.mkdir(parents=True, exist_ok=True)
    for path in [pass_crop, warn_crop, fail_crop]:
        Image.new("RGB", (300, 100), color="white").save(path)

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
            "crop_image_path": str(pass_crop),
        },
        {
            "scenario_id": "s1",
            "tab_name": "home",
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
            "crop_image_path": str(warn_crop),
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
            "crop_image_path": str(fail_crop),
        },
    ]
    output_path = tmp_path / "report_thumbnail.xlsx"

    save_excel(rows, str(output_path), with_images=False)

    wb = openpyxl.load_workbook(output_path)
    ws = wb["result"]
    headers = [cell.value for cell in ws[1]]
    thumb_col_idx = headers.index("result_crop_thumbnail") + 1
    final_col_idx = headers.index("final_result") + 1

    final_results = [ws.cell(row=i, column=final_col_idx).value for i in range(2, 5)]
    assert final_results == ["PASS", "WARN", "FAIL"]
    assert ws.cell(row=2, column=thumb_col_idx).value == ""
    assert ws.cell(row=3, column=thumb_col_idx).value == ""
    assert ws.cell(row=4, column=thumb_col_idx).value == ""
    assert len(ws._images) == 0

    fill_colors = [ws.cell(row=i, column=1).fill.start_color.rgb for i in range(2, 5)]
    assert fill_colors == ["00C6EFCE", "00FFEB9C", "00FFC7CE"]


def test_save_excel_with_images_true_adds_result_thumbnail(tmp_path):
    warn_crop = tmp_path / "crops" / "warn.png"
    fail_crop = tmp_path / "crops" / "fail.png"
    warn_crop.parent.mkdir(parents=True, exist_ok=True)
    for path in [warn_crop, fail_crop]:
        Image.new("RGB", (300, 100), color="white").save(path)

    rows = [
        {
            "scenario_id": "s1",
            "tab_name": "home",
            "step_index": 1,
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
            "crop_image_path": str(warn_crop),
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
            "crop_image_path": str(fail_crop),
        },
    ]
    output_path = tmp_path / "report_thumbnail_with_images.xlsx"

    save_excel(rows, str(output_path), with_images=True)

    wb = openpyxl.load_workbook(output_path)
    ws = wb["result"]
    headers = [cell.value for cell in ws[1]]
    thumb_col_idx = headers.index("result_crop_thumbnail") + 1

    assert ws.cell(row=2, column=thumb_col_idx).value == "warn.png"
    assert ws.cell(row=3, column=thumb_col_idx).value == "fail.png"
    image_anchors = sorted(img.anchor._from.row + 1 for img in ws._images)
    assert image_anchors == [2, 3]


def test_save_excel_xlsxwriter_thumbnail_insert_does_not_raise_file_not_found(tmp_path, monkeypatch):
    pytest.importorskip("xlsxwriter")
    original_excel_writer = pd.ExcelWriter

    def _xlsxwriter_excel_writer(*args, **kwargs):
        kwargs.setdefault("engine", "xlsxwriter")
        return original_excel_writer(*args, **kwargs)

    monkeypatch.setattr("tb_runner.excel_report.pd.ExcelWriter", _xlsxwriter_excel_writer)

    fail_crop = tmp_path / "crops" / "fail.png"
    fail_crop.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 100), color="white").save(fail_crop)

    rows = [
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
            "crop_image_path": str(fail_crop),
            "crop_image": "thumbnail",
        },
    ]
    output_path = tmp_path / "report_xlsxwriter.xlsx"

    save_excel(rows, str(output_path), with_images=True)

    assert output_path.exists()


def test_save_excel_raw_sheet_uses_resized_thumbnail_and_rightmost_image_column(tmp_path):
    crop_file = tmp_path / "crops" / "raw_large.png"
    crop_file.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1200, 600), color="white").save(crop_file)

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
            "crop_image": "thumbnail",
        }
    ]
    output_path = tmp_path / "report_raw_thumbnail.xlsx"

    save_excel(rows, str(output_path), with_images=True)

    wb = openpyxl.load_workbook(output_path)
    ws = wb["raw"]
    headers = [cell.value for cell in ws[1]]
    image_col_idx = headers.index("crop_image") + 1

    assert headers[-1] == "crop_image"
    assert ws.cell(row=2, column=image_col_idx).value in {None, "thumbnail"}
    assert len(ws._images) == 1
    assert ws._images[0].width <= 160
    assert ws._images[0].height <= 96
