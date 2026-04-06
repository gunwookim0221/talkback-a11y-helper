import pytest

pd = pytest.importorskip("pandas")

from tb_runner.excel_report import (
    add_status_columns,
    make_filtered_df,
    make_result_df,
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
