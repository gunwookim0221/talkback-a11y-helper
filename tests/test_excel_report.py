import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
from PIL import Image

from tb_runner.excel_report import (
    RESULT_SHEET_COLUMNS,
    _to_int_or_zero,
    add_status_columns,
    annotate_plugin_metadata,
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

    assert list(result.columns[: len(RESULT_SHEET_COLUMNS)]) == RESULT_SHEET_COLUMNS
    assert "final_result" in result.columns
    assert set(result["final_result"].tolist()) == {"PASS", "WARN", "FAIL"}
    assert "_debug_log_path" in result.columns
    assert "_debug_log_name" in result.columns
    assert "_crop_image_path" in result.columns
    assert result.columns[len(RESULT_SHEET_COLUMNS) - 1] == "result_crop_thumbnail"


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

    assert result.iloc[0]["_req_id"] == "focus_req_123"


def test_make_result_df_treats_successful_move_result_dict_as_pass_moved():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s_nav",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Devices",
                "merged_announcement": "QR code Devices",
                "move_result": "{'success': true, 'status': 'moved', 'detail': 'moved'}",
                "last_smart_nav_result": "moved",
                "smart_nav_success": True,
                "focus_view_id": "com.samsung.android.oneconnect:id/menu_devices",
                "focus_bounds": "[0,0][10,10]",
                "fallback_used": False,
                "step_dump_used": False,
                "req_id": "r_nav_1",
                "post_move_verdict_source": "smart_nav_result_resource_match",
                "step_elapsed_sec": 0.2,
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["_traversal_result"] == "PASS_MOVED"
    assert result.iloc[0]["failure_reason"] == ""
    assert result.iloc[0]["final_result"] == "PASS"


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


def test_make_result_df_skips_placeholder_rows(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr("tb_runner.excel_report.log", lambda msg, level="NORMAL": logs.append(msg))
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s1",
                "tab_name": "main",
                "step_index": -1,
                "context_type": "main",
                "req_id": "nan",
                "move_result": "nan",
                "visible_label": "nan",
                "merged_announcement": "nan",
                "focus_view_id": "nan",
                "focus_bounds": "nan",
            },
            {
                "scenario_id": "s1",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Home",
                "merged_announcement": "Home",
                "move_result": "moved",
            },
        ]
    )

    result = make_result_df(filtered_df)

    assert len(result) == 1
    assert int(result.iloc[0]["step"]) == 1
    assert any("[RESULT] skipped placeholder rows count=1" in msg for msg in logs)


def test_make_result_df_keeps_local_tab_probe_success_placeholder_row():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "motion_sensor_main",
                "tab_name": "main",
                "step_index": -1,
                "context_type": "main",
                "visible_label": "Motion detection notifications",
                "merged_announcement": "Motion detection notifications",
                "move_result": "moved",
                "local_tab_content_entered": True,
                "local_tab_content_candidate_visited": True,
                "local_tab_content_visit_source": "content_entry_probe:content_like_focused_row",
                "local_tab_content_entry_probe_result": "success",
            },
            {
                "scenario_id": "motion_sensor_main",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "History",
                "merged_announcement": "History",
                "move_result": "moved",
            },
        ]
    )

    result = make_result_df(filtered_df)

    labels = result["visible_label"].tolist()
    assert "Motion detection notifications" in labels
    assert "History" in labels


def test_make_result_df_prefers_upstream_classification():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s_up",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Labs",
                "merged_announcement": "Labs",
                "move_result": "scrolled",
                "traversal_result": "PASS_SCROLLED",
                "speech_match_result": "PASS_SMART_NAV",
                "final_result": "PASS",
                "failure_reason": "",
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["_traversal_result"] == "PASS_SCROLLED"
    assert result.iloc[0]["final_result"] == "PASS"


def test_make_filtered_df_keeps_noise_row_with_review_worthy_mismatch():
    raw_df = pd.DataFrame(
        [
            {
                "scenario_id": "s1",
                "tab_name": "main",
                "step_index": 1,
                "is_noise_step": True,
                "is_duplicate_step": False,
                "is_recent_duplicate_step": False,
                "final_result": "WARN",
                "visible_label": "Special suggestions Get helpful offers or news on products.",
                "merged_announcement": "Battery 100 per cent. Special suggestions Get helpful offers or news on products. Off",
                "review_note": "visible/speech mismatch",
                "failure_reason": "speech_visible_diverged",
                "move_result": "moved",
            }
        ]
    )

    filtered_df = make_filtered_df(raw_df)
    result_df = make_result_df(filtered_df)

    assert len(filtered_df) == 1
    assert len(result_df) == 1
    assert result_df.iloc[0]["final_result"] in {"WARN", "FAIL"}


def test_make_filtered_df_drops_meaningless_noise_pass_row():
    raw_df = pd.DataFrame(
        [
            {
                "scenario_id": "s1",
                "tab_name": "main",
                "step_index": 1,
                "is_noise_step": True,
                "is_duplicate_step": False,
                "is_recent_duplicate_step": False,
                "final_result": "PASS",
                "visible_label": "Home",
                "merged_announcement": "Home",
                "review_note": "",
                "failure_reason": "",
                "move_result": "moved",
                "rule_compare": "SAME",
                "speech_match_result": "PASS_EXACT",
            }
        ]
    )

    filtered_df = make_filtered_df(raw_df)
    assert filtered_df.empty


def test_make_filtered_df_keeps_warn_fail_rows_even_when_noise():
    raw_df = pd.DataFrame(
        [
            {
                "scenario_id": "s_warn",
                "tab_name": "main",
                "step_index": 1,
                "is_noise_step": True,
                "is_duplicate_step": False,
                "is_recent_duplicate_step": False,
                "final_result": "WARN",
            },
            {
                "scenario_id": "s_fail",
                "tab_name": "main",
                "step_index": 2,
                "is_noise_step": True,
                "is_duplicate_step": False,
                "is_recent_duplicate_step": False,
                "final_result": "FAIL",
            },
        ]
    )

    filtered_df = make_filtered_df(raw_df)
    assert filtered_df["final_result"].tolist() == ["WARN", "FAIL"]


def test_save_excel_adds_result_crop_hyperlink(tmp_path):
    crop_file = tmp_path / "crops" / "sample_step_1.png"
    crop_file.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 100), color="white").save(crop_file)

    rows = [
        {
            "scenario_id": "device_water_leak_sensor_plugin",
            "scenario_type": "content",
            "tab_name": "home",
            "step_index": 1,
            "context_type": "main",
            "visible_label": "Home",
            "merged_announcement": "Home updated",
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

    save_excel(rows, str(output_path), with_images=True)

    wb = openpyxl.load_workbook(output_path)
    ws = wb["result"]
    headers = [cell.value for cell in ws[1]]
    crop_col_idx = headers.index("result_crop_thumbnail") + 1
    crop_cell = ws.cell(row=2, column=crop_col_idx)
    result_row = [ws.cell(row=2, column=i).value for i in range(1, len(RESULT_SHEET_COLUMNS) + 1)]
    raw_headers = [cell.value for cell in wb["raw"][1]]
    raw_row = [cell.value for cell in wb["raw"][2][:5]]

    assert headers == RESULT_SHEET_COLUMNS
    assert raw_headers[:3] == ["plugin_group", "plugin_name", "scenario_id"]
    assert result_row[:3] == ["Devices", "누수센서", "device_water_leak_sensor_plugin"]
    assert raw_row[:3] == ["Devices", "누수센서", "device_water_leak_sensor_plugin"]
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
    assert "debug_log_path" not in headers
    assert "debug_log_name" not in headers


def _build_debug_target_rows() -> list[dict]:
    return [
        {
            "scenario_id": "scenario_menu",
            "tab_name": "menu",
            "step_index": 8,
            "context_type": "main",
            "visible_label": "Special suggestions",
            "merged_announcement": "Navigate up Special suggestions Get helpful offers Off",
            "move_result": "moved",
            "focus_view_id": "id/menu8",
            "focus_bounds": "[0,10][10,20]",
            "fallback_used": False,
            "step_dump_used": False,
            "req_id": "menu_req_8",
            "step_elapsed_sec": 0.2,
        }
    ]


def _render_debug_log_content(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(
        "tb_runner.excel_report.get_recent_logs",
        lambda limit=260: [
            "[12:00:00] [STEP] START scenario='scenario_life' tab='life' step=8 req_id='life_req_8'",
            "[12:00:01] [STEP] END scenario='scenario_life' tab='life' step=8 req_id='life_req_8' move_result='moved'",
            "[12:00:02] [STEP] START scenario='scenario_menu' tab='menu' step=8 req_id='menu_req_8'",
            "[12:00:03] [ANN][poll] req_id=menu_req_8 candidate='Navigate up Special suggestions Get helpful offers Off'",
            "[12:00:04] [STEP] END scenario='scenario_menu' tab='menu' step=8 req_id='menu_req_8' move_result='moved'",
            "[12:00:05] [STOP][eval] scenario='scenario_menu' tab='menu' step=8 reason='speech_visible_diverged' req_id='menu_req_8'",
        ],
    )
    output_path = tmp_path / "report_debug_scope.xlsx"
    save_excel(_build_debug_target_rows(), str(output_path), with_images=False)
    debug_file = next((tmp_path / "debug_logs").glob("*.log"))
    return debug_file.read_text(encoding="utf-8")


def test_debug_log_filters_out_other_tab_same_step(tmp_path, monkeypatch):
    content = _render_debug_log_content(tmp_path, monkeypatch)

    assert "req_id='life_req_8'" not in content
    assert "tab='life'" not in content
    assert "req_id='menu_req_8'" in content


def test_debug_log_records_baseline_empty_reason(tmp_path, monkeypatch):
    content = _render_debug_log_content(tmp_path, monkeypatch)
    assert "[ANN][baseline]" in content
    assert "empty_reason='no_prev_step_row'" in content


def test_debug_log_always_includes_trim_trace(tmp_path, monkeypatch):
    content = _render_debug_log_content(tmp_path, monkeypatch)
    assert "[ANN][trim]" in content
    assert "considered=false" in content


def test_debug_log_snapshot_select_reason_is_recorded(tmp_path, monkeypatch):
    content = _render_debug_log_content(tmp_path, monkeypatch)
    assert "[ANN][select]" in content
    assert "used_snapshot=true" in content
    assert "snapshot_reason='no_better_recent_poll_candidate'" in content


def test_debug_log_focus_missing_reason_when_no_get_focus_trace(tmp_path, monkeypatch):
    content = _render_debug_log_content(tmp_path, monkeypatch)
    assert "[FOCUS]" in content
    assert "missing_reason='no_direct_get_focus_trace_found'" in content


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
    crop_col_idx = headers.index("result_crop_thumbnail") + 1
    crop_cell = ws.cell(row=2, column=crop_col_idx)

    assert crop_cell.value in {"", None}
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


def test_make_result_df_marks_representative_context_and_keeps_representative_visible():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "device_camera_plugin",
                "tab_name": "devices",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "More options",
                "merged_announcement": "More options",
                "representative_visible": "Increase",
                "row_source": "actual_focus",
                "representative_row_source": "representative",
                "move_result": "moved",
                "focus_view_id": "id/more",
                "focus_bounds": "[1,1][2,2]",
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["visible_label"] == "More options"
    assert result.iloc[0]["representative_visible"] == "Increase"
    assert result.iloc[0]["mismatch_type"] == "REPRESENTATIVE_CONTEXT"


def test_make_result_df_preserves_semantic_card_metadata_without_changing_result():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "generic_card",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Mode",
                "merged_announcement": "Mode",
                "move_result": "moved",
                "focus_view_id": "GenericCapabilityCardView_header_title",
                "focus_bounds": "84,586,936,655",
                "semantic_card_id": "semantic_card:generic||30,538,1050,850||mode",
                "semantic_card_role": "title",
                "semantic_card_title": "Mode",
                "semantic_card_values": "Auto",
                "semantic_card_actions": "Change",
                "semantic_card_bounds": "30,538,1050,850",
                "semantic_card_member_count": 4,
                "semantic_card_is_value_covered": False,
                "semantic_card_is_action_only": False,
                "semantic_card_is_title_only": False,
            }
        ]
    )

    result = make_result_df(filtered_df)

    row = result.iloc[0]
    assert row["semantic_card_id"] == "semantic_card:generic||30,538,1050,850||mode"
    assert row["semantic_card_role"] == "title"
    assert row["semantic_card_title"] == "Mode"
    assert row["semantic_card_values"] == "Auto"
    assert row["semantic_card_actions"] == "Change"
    assert row["semantic_card_member_count"] == 4
    assert row["mismatch_type"] == "EXACT_MATCH"
    assert row["final_result"] == "PASS"


def test_make_result_df_uses_representative_when_actual_focus_is_empty():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "life_home_monitor_plugin",
                "tab_name": "life",
                "step_index": 2,
                "context_type": "main",
                "visible_label": "",
                "merged_announcement": "",
                "representative_visible": "Arm (stay)",
                "representative_resource_id": "com.samsung.android.oneconnect:id/shmBannerStayButton",
                "row_source": "actual_focus",
                "representative_row_source": "representative",
                "move_result": "moved",
                "focus_view_id": "com.samsung.android.oneconnect:id/shm_setting_button",
                "focus_bounds": "[804,118][924,310]",
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["visible_label"] == "Arm (stay)"
    assert result.iloc[0]["merged_announcement"] == "Arm (stay)"
    assert result.iloc[0]["focus_view_id"] == "com.samsung.android.oneconnect:id/shmBannerStayButton"
    assert result.iloc[0]["mismatch_type"] == "EXACT_MATCH"
    assert result.iloc[0]["final_result"] == "PASS"


def test_make_result_df_uses_focus_node_label_fallback_for_icon_only_rows():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s_icon",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "",
                "merged_announcement": "",
                "move_result": "moved",
                "focus_view_id": "id/settings",
                "focus_bounds": "[1,1][2,2]",
                "focus_node": {
                    "className": "android.widget.ImageButton",
                    "text": None,
                    "contentDescription": "Settings",
                    "mergedLabel": "Settings",
                    "talkbackLabel": "Settings",
                },
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["visible_label"] == "Settings"
    assert result.iloc[0]["merged_announcement"] == "Settings"
    assert result.iloc[0]["mismatch_type"] == "EXACT_MATCH"
    assert result.iloc[0]["final_result"] == "PASS"


def test_make_result_df_downgrades_exact_match_repeat_stop_to_warn():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "global_nav_main",
                "tab_name": "main",
                "step_index": 3,
                "context_type": "main",
                "visible_label": "Menu, Tab 5 of 5., New content available",
                "merged_announcement": "Menu, Tab 5 of 5., New content available",
                "move_result": "moved",
                "focus_view_id": "id/menu",
                "focus_bounds": "[1,1][2,2]",
            },
            {
                "scenario_id": "global_nav_main",
                "tab_name": "main",
                "step_index": 4,
                "context_type": "main",
                "visible_label": "Menu, Tab 5 of 5., New content available",
                "merged_announcement": "Menu, Tab 5 of 5., New content available",
                "move_result": "failed",
                "focus_view_id": "id/menu",
                "focus_bounds": "[1,1][2,2]",
                "req_id": "repeat_no_progress",
                "final_result": "FAIL",
                "failure_reason": "repeat_no_progress",
            },
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[-1]["mismatch_type"] == "EXACT_MATCH"
    assert result.iloc[-1]["final_result"] == "WARN"
    assert result.iloc[-1]["review_note"] == "발화 일치, 탐색 종료 reason 있음"


def test_make_result_df_collapses_repeated_issue_group_by_fingerprint():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "life_energy_plugin",
                "tab_name": "life",
                "step_index": 23,
                "context_type": "main",
                "visible_label": "Activity New notification",
                "merged_announcement": "Activity New notification",
                "move_result": "failed",
                "focus_view_id": "activity",
                "focus_bounds": "879,2405",
                "failure_reason": "move_failed",
                "final_result": "FAIL",
            },
            {
                "scenario_id": "life_energy_plugin",
                "tab_name": "life",
                "step_index": 24,
                "context_type": "main",
                "visible_label": "Activity New notification",
                "merged_announcement": "Activity New notification",
                "move_result": "failed",
                "focus_view_id": "activity",
                "focus_bounds": "879,2405",
                "failure_reason": "move_failed",
                "final_result": "FAIL",
                "is_recent_duplicate_step": True,
                "recent_duplicate_distance": 1,
            },
            {
                "scenario_id": "life_energy_plugin",
                "tab_name": "life",
                "step_index": 25,
                "context_type": "main",
                "visible_label": "Activity New notification",
                "merged_announcement": "Activity New notification",
                "move_result": "failed",
                "focus_view_id": "activity",
                "focus_bounds": "879,2405",
                "failure_reason": "move_failed",
                "final_result": "FAIL",
                "is_duplicate_step": True,
            },
        ]
    )

    result = make_result_df(filtered_df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["visible_label"] == "Activity New notification"
    assert row["focus_view_id"] == "activity"
    assert row["failure_reason"] == "move_failed"
    assert row["repeat_count"] == 3
    assert row["first_step"] == 23
    assert row["last_step"] == 25
    assert row["steps"] == "23,24,25"
    assert bool(row["is_repeated_issue_group"]) is True


def test_make_result_df_keeps_label_mismatch_as_fail_even_with_repeat_stop():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s_fail",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Menu",
                "merged_announcement": "Settings",
                "move_result": "failed",
                "focus_view_id": "id/fail",
                "focus_bounds": "[1,1][2,2]",
                "req_id": "repeat_no_progress",
                "failure_reason": "repeat_no_progress",
                "final_result": "FAIL",
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["mismatch_type"] == "LABEL_MISMATCH"
    assert result.iloc[0]["final_result"] == "FAIL"


def test_make_result_df_keeps_empty_speech_as_fail():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "s_empty",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Menu",
                "merged_announcement": "",
                "move_result": "moved",
                "focus_view_id": "id/menu",
                "focus_bounds": "[1,1][2,2]",
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["mismatch_type"] == "EMPTY_SPEECH"
    assert result.iloc[0]["final_result"] == "FAIL"


def test_make_result_df_downgrades_empty_visible_when_contained_child_label_exists():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "generic_card",
                "tab_name": "main",
                "step_index": 10,
                "context_type": "main",
                "visible_label": "",
                "merged_announcement": "",
                "move_result": "moved",
                "last_smart_nav_result": "moved",
                "smart_nav_success": True,
                "post_move_verdict_source": "smart_nav_result",
                "focus_view_id": "GenericCapabilityCardView",
                "focus_bounds": "0,0,100,100",
                "req_id": "empty_parent",
            },
            {
                "scenario_id": "generic_card",
                "tab_name": "main",
                "step_index": 11,
                "context_type": "main",
                "visible_label": "Enabled",
                "merged_announcement": "Enabled",
                "move_result": "moved",
                "focus_view_id": "",
                "focus_bounds": "10,10,90,90",
                "req_id": "contained_child",
            },
        ]
    )

    result = make_result_df(filtered_df)

    row = result.iloc[0]
    assert row["mismatch_type"] == "REPRESENTATIVE_CONTEXT"
    assert row["representative_visible"] == "Enabled"
    assert row["final_result"] == "WARN"


def test_make_result_df_keeps_empty_visible_fail_without_nearby_child_label():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "generic_card",
                "tab_name": "main",
                "step_index": 10,
                "context_type": "main",
                "visible_label": "",
                "merged_announcement": "",
                "move_result": "moved",
                "last_smart_nav_result": "moved",
                "smart_nav_success": True,
                "post_move_verdict_source": "smart_nav_result",
                "focus_view_id": "GenericCapabilityCardView",
                "focus_bounds": "0,0,100,100",
                "req_id": "empty_parent",
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["mismatch_type"] == "EMPTY_VISIBLE"
    assert result.iloc[0]["final_result"] == "FAIL"


def test_make_result_df_keeps_empty_visible_fail_when_nearby_label_bounds_unrelated():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "generic_card",
                "tab_name": "main",
                "step_index": 10,
                "context_type": "main",
                "visible_label": "",
                "merged_announcement": "",
                "move_result": "moved",
                "last_smart_nav_result": "moved",
                "smart_nav_success": True,
                "post_move_verdict_source": "smart_nav_result",
                "focus_view_id": "GenericCapabilityCardView",
                "focus_bounds": "0,0,100,100",
                "req_id": "empty_parent",
            },
            {
                "scenario_id": "generic_card",
                "tab_name": "main",
                "step_index": 11,
                "context_type": "main",
                "visible_label": "Unrelated",
                "merged_announcement": "Unrelated",
                "move_result": "moved",
                "focus_view_id": "",
                "focus_bounds": "300,300,400,400",
                "req_id": "unrelated_label",
            },
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["mismatch_type"] == "EMPTY_VISIBLE"
    assert result.iloc[0]["final_result"] == "FAIL"


def test_make_result_df_keeps_non_empty_normal_row_exact_match():
    filtered_df = pd.DataFrame(
        [
            {
                "scenario_id": "normal",
                "tab_name": "main",
                "step_index": 1,
                "context_type": "main",
                "visible_label": "Normal label",
                "merged_announcement": "Normal label",
                "move_result": "moved",
                "focus_view_id": "normal/id",
                "focus_bounds": "0,0,100,100",
                "req_id": "normal_row",
            }
        ]
    )

    result = make_result_df(filtered_df)

    assert result.iloc[0]["mismatch_type"] == "EXACT_MATCH"
    assert result.iloc[0]["final_result"] == "PASS"


def test_annotate_plugin_metadata_uses_mapping_and_fallback():
    df = pd.DataFrame(
        [
            {"scenario_id": "device_water_leak_sensor_plugin", "scenario_type": "content"},
            {"scenario_id": "unknown_scenario", "scenario_type": "content"},
            {"scenario_id": "global_nav_main", "scenario_type": "global_nav"},
        ]
    )

    result = annotate_plugin_metadata(df)

    assert result.loc[0, "plugin_group"] == "Devices"
    assert result.loc[0, "plugin_name"] == "누수센서"
    assert result.loc[1, "plugin_group"] == "Unknown"
    assert result.loc[1, "plugin_name"] == "unknown_scenario"
    assert result.loc[2, "plugin_group"] == "Global"
    assert result.loc[2, "plugin_name"] == "Global Navigation"


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
    assert ws.cell(row=2, column=thumb_col_idx).value in {"", None}
    assert ws.cell(row=3, column=thumb_col_idx).value in {"", None}
    assert ws.cell(row=4, column=thumb_col_idx).value in {"", None}
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
    if ws._images:
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
    if ws._images:
        assert len(ws._images) == 1
        assert ws._images[0].width <= 160
        assert ws._images[0].height <= 96


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0),
        (float("nan"), 0),
        (pd.NA, 0),
        (pytest.importorskip("numpy").nan, 0),
        ("3", 3),
        (3, 3),
        (0, 0),
    ],
)
def test_to_int_or_zero_handles_nan_and_numeric_values(value, expected):
    assert _to_int_or_zero(value) == expected


def test_save_excel_handles_nan_announcement_count_in_debug_log_build(tmp_path):
    rows = [
        {
            "scenario_id": "device_motion_sensor_plugin",
            "tab_name": "main",
            "step_index": 1,
            "context_type": "main",
            "visible_label": "Controls",
            "merged_announcement": "Controls",
            "move_result": "moved",
            "focus_view_id": "control",
            "focus_bounds": "[0,0][10,10]",
            "fallback_used": False,
            "step_dump_used": False,
            "req_id": "motion_req_1",
            "announcement_count": float("nan"),
            "step_elapsed_sec": 0.1,
        },
        {
            "scenario_id": "device_motion_sensor_plugin",
            "tab_name": "main",
            "step_index": 2,
            "context_type": "main",
            "visible_label": "Motion detection notifications",
            "merged_announcement": "Motion detection notifications",
            "move_result": "failed",
            "failure_reason": "move_failed",
            "focus_view_id": "active",
            "focus_bounds": "[0,10][10,20]",
            "fallback_used": False,
            "step_dump_used": False,
            "req_id": "motion_req_2",
            "announcement_count": float("nan"),
            "step_elapsed_sec": 0.2,
        },
    ]
    output_path = tmp_path / "report_nan_announcement_count.xlsx"

    save_excel(rows, str(output_path), with_images=False)

    assert output_path.exists()
