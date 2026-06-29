from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import Workbook

from tools import v8_fullrun_profile as profiler


def _write_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "result"
    sheet.append(
        [
            "scenario_id",
            "step",
            "final_result",
            "row_source",
            "promotion_dedup_status",
        ]
    )
    sheet.append(["scenario_one", 0, "PASS", "actual_focus", ""])
    sheet.append(["scenario_one", 1, "FAIL", "actual_focus", ""])
    sheet.append(["scenario_one", "", "SHADOW", "COVERAGE_PROBE_SHADOW", "SKIPPED"])
    sheet.append(["scenario_one", "", "PASS", "COVERAGE_PROBE_PROMOTED", "PROMOTED"])
    sheet.append(["scenario_two", 0, "WARN", "actual_focus", ""])
    workbook.save(path)


def _write_log(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[10:00:00] [SCENARIO][stabilization] scenario='scenario_one'",
                "[10:00:01] [STEP] START scenario='scenario_one' step=0",
                "[10:00:02] [STEP] END scenario='scenario_one' step=0 final_result='PASS'",
                "[10:00:03] [STEP][viewport_exhausted_eval] result=false",
                "[10:00:04] [STEP][local_tab_content_entry_probe_success] reason='content_like_focused_row'",
                "[10:00:05] [STOP][eval] step=1 scenario='scenario_one' reason='repeat_no_progress'",
                "[10:00:06] [STOP][eval] step=2 scenario='scenario_one' reason='repeat_no_progress'",
                "[10:00:07] [STOP][eval] step=3 scenario='scenario_one' reason='repeat_no_progress'",
                "[10:00:08] [STEP] START scenario='scenario_one' step=1",
                "[10:00:09] [STEP] END scenario='scenario_one' step=1 final_result='FAIL'",
                "[10:00:10] [STEP] START scenario='scenario_one' step=2",
                "[10:00:11] [STEP][row_filter] label='duplicate row' reason='visited_logical_signature'",
                "[10:00:12] [STEP] START scenario='scenario_one' step=3",
                "[10:00:13] [STEP] END scenario='scenario_one' step=3 final_result='PASS'",
                "[10:00:14] [ADAPTIVE_MAX_STEPS] scenario='scenario_one' step=4 current_limit=2 hard_limit=5 lookback_steps=2 meaningful_new_count=2 decision='extend' new_limit=4 reason='productive_tail'",
                "[10:00:15] [STEP] START scenario='scenario_one' step=4",
                "[10:00:16] [STEP] END scenario='scenario_one' step=4 final_result='PASS'",
                "[10:00:17] [ADAPTIVE_MAX_STEPS] scenario='scenario_one' step=5 current_limit=4 hard_limit=5 lookback_steps=2 meaningful_new_count=1 decision='stop' new_limit=4 reason='unproductive_tail'",
                "[10:00:18] [PERF][scenario_summary] scenario=scenario_one total_runtime=18.0 total_steps=4",
                "[10:00:20] [SCENARIO][stabilization] scenario='scenario_two'",
                "[10:00:21] [STEP] END scenario='scenario_two' step=5 final_result='WARN'",
                "[10:00:22] [STEP] START scenario='scenario_two' step=5",
                "[10:00:23] [STEP] START scenario='scenario_two' step=6",
                "[10:00:24] [STEP] END scenario='scenario_two' step=6 final_result='WARN'",
                "[10:00:25] [ADAPTIVE_MAX_STEPS] scenario='scenario_two' step=7 current_limit=6 hard_limit=6 lookback_steps=2 meaningful_new_count=0 decision='hard_stop' new_limit=6 reason='hard_limit'",
                "[10:00:26] [PERF][scenario_summary] scenario=scenario_two total_runtime=5.0 total_steps=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_probe_results(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "scenario_count": 2,
                "scenarios": [
                    {
                        "scenario_id": "scenario_one",
                        "candidate_count": 4,
                        "attempted_count": 4,
                        "success_count": 1,
                        "failed_count": 3,
                        "skipped_count": 2,
                        "screen_skipped_count": 1,
                        "scenario_filtered_count": 1,
                    },
                    {
                        "scenario_id": "scenario_two",
                        "summary": {
                            "candidate_count": 1,
                            "attempted_count": 1,
                            "success_count": 1,
                            "failed_count": 0,
                            "skipped_count": 0,
                            "screen_skipped_count": 0,
                            "scenario_filtered_count": 0,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_probe_validation(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "scenario_count": 2,
                "scenarios": [
                    {
                        "scenario_id": "scenario_one",
                        "match_count": 1,
                        "partial_match_count": 1,
                        "promotable_count": 1,
                    },
                    {
                        "scenario_id": "scenario_two",
                        "summary": {
                            "match_count": 1,
                            "partial_match_count": 0,
                            "promotable_count": 1,
                            "promoted_row_count": 0,
                            "promotion_dedup_skipped_count": 0,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _artifact_set(tmp_path: Path) -> dict[str, Path]:
    stem = "talkback_compare_20260628_000108"
    paths = {
        "xlsx": tmp_path / f"{stem}.xlsx",
        "log": tmp_path / f"{stem}.normal.log",
        "probe_results": tmp_path / f"{stem}.coverage_probe_results.aggregate.json",
        "probe_validation": tmp_path / f"{stem}.coverage_probe_validation.aggregate.json",
    }
    _write_xlsx(paths["xlsx"])
    _write_log(paths["log"])
    _write_probe_results(paths["probe_results"])
    _write_probe_validation(paths["probe_validation"])
    return paths


def _scenario(profile: dict, scenario_id: str) -> dict:
    return next(row for row in profile["scenarios"] if row["scenario_id"] == scenario_id)


def test_parses_xlsx_result_rows_by_scenario(tmp_path):
    paths = _artifact_set(tmp_path)

    profile = profiler.build_profile(**paths)
    scenario = _scenario(profile, "scenario_one")

    assert scenario["result_row_count"] == 4
    assert scenario["fail_row_count"] == 1
    assert scenario["review_row_count"] == 0
    assert scenario["clean_row_count"] == 2
    assert scenario["promoted_count"] == 1
    assert scenario["dedup_skipped_count"] == 1


def test_parses_probe_and_validation_aggregate_summaries(tmp_path):
    paths = _artifact_set(tmp_path)

    profile = profiler.build_profile(**paths)
    first = _scenario(profile, "scenario_one")
    second = _scenario(profile, "scenario_two")

    assert first["probe_candidate_count"] == 4
    assert first["probe_attempted_count"] == 4
    assert first["probe_success_count"] == 1
    assert first["probe_failed_count"] == 3
    assert first["probe_skipped_count"] == 2
    assert first["screen_skipped_count"] == 1
    assert first["scenario_filtered_count"] == 1
    assert first["validation_match_count"] == 1
    assert first["validation_partial_match_count"] == 1
    assert first["promotable_count"] == 1
    assert second["probe_candidate_count"] == 1
    assert second["validation_match_count"] == 1


def test_log_metrics_and_high_repeat_finding(tmp_path):
    paths = _artifact_set(tmp_path)

    profile = profiler.build_profile(**paths)
    scenario = _scenario(profile, "scenario_one")

    assert scenario["step_count"] == 4
    assert scenario["attempted_step_count"] == 5
    assert scenario["persisted_step_count"] == 4
    assert scenario["suppressed_row_count"] == 1
    assert scenario["suppressed_row_count_estimated"] is False
    assert scenario["first_step"] == 0
    assert scenario["last_step"] == 4
    assert scenario["duration_sec"] == 18.0
    assert scenario["repeat_no_progress_count"] == 3
    assert scenario["viewport_exhausted_eval_count"] == 1
    assert scenario["local_tab_probe_success_count"] == 1
    assert scenario["adaptive_extension_count"] == 1
    assert scenario["adaptive_hard_limit_count"] == 0
    assert scenario["adaptive_safety_stop_count"] == 1
    assert scenario["post_soft_limit_new_rows"] == 2
    assert scenario["post_soft_limit_suppressed_rows"] == 0
    assert scenario["soft_limit_extension_rows"] == 2
    assert any(
        finding["scenario_id"] == "scenario_one"
        and finding["code"] == "high_repeat_no_progress"
        for finding in profile["findings"]
    )


def test_missing_probe_files_are_warnings_not_errors(tmp_path):
    paths = _artifact_set(tmp_path)
    paths["probe_results"].unlink()
    paths["probe_validation"].unlink()

    profile = profiler.build_profile(**paths)

    assert profile["summary"]["scenario_count"] == 2
    assert _scenario(profile, "scenario_one")["probe_candidate_count"] == 0
    assert len(profile["warnings"]) == 2
    assert all("not found" in warning for warning in profile["warnings"])


def test_writes_json_markdown_and_scenario_csv(tmp_path):
    paths = _artifact_set(tmp_path)
    profile = profiler.build_profile(**paths)
    output_dir = tmp_path / "profile"

    outputs = profiler.write_outputs(profile, output_dir)

    assert set(outputs) == {"json", "markdown", "csv"}
    assert all(path.is_file() for path in outputs.values())
    loaded = json.loads(outputs["json"].read_text(encoding="utf-8"))
    assert loaded["summary"]["scenario_count"] == 2
    assert loaded["scenarios"][0]["attempted_step_count"] == 5
    markdown = outputs["markdown"].read_text(encoding="utf-8")
    assert "## Run Summary" in markdown
    assert "## Step Accounting" in markdown
    assert "## Adaptive Max Steps" in markdown
    assert "attempted_step_count" in markdown
    assert "## Top Slow / Heavy Scenarios" in markdown
    with outputs["csv"].open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert [row["scenario_id"] for row in rows] == ["scenario_one", "scenario_two"]
    assert list(rows[0]) == profiler.SCENARIO_FIELDS
    assert rows[0]["attempted_step_count"] == "5"
    assert rows[0]["adaptive_extension_count"] == "1"


def test_summary_totals_and_rankings_are_consistent(tmp_path):
    paths = _artifact_set(tmp_path)

    profile = profiler.build_profile(**paths)
    summary = profile["summary"]

    assert summary["scenario_count"] == 2
    assert summary["total_steps"] == 5
    assert summary["total_attempted_steps"] == 7
    assert summary["total_persisted_steps"] == 5
    assert summary["total_suppressed_rows"] == 2
    assert summary["total_duration_sec"] == 23.0
    assert summary["total_repeat_no_progress"] == 3
    assert summary["total_probe_candidates"] == 5
    assert summary["total_probe_attempted"] == 5
    assert summary["total_probe_success"] == 2
    assert summary["total_promoted"] == 1
    assert summary["total_dedup_skipped"] == 1
    assert summary["total_adaptive_extensions"] == 1
    assert summary["total_adaptive_hard_limits"] == 1
    assert summary["total_adaptive_safety_stops"] == 1
    assert summary["total_post_soft_limit_new_rows"] == 2
    assert summary["total_post_soft_limit_suppressed_rows"] == 0
    assert summary["slowest_scenarios"][0] == {"scenario_id": "scenario_one", "value": 18.0}
    assert summary["highest_probe_failure_scenarios"][0]["scenario_id"] == "scenario_one"


def test_estimates_suppressed_rows_when_row_filter_logs_are_missing(tmp_path):
    paths = _artifact_set(tmp_path)
    paths["log"].write_text(
        "\n".join(
            [
                "[10:00:00] [SCENARIO][stabilization] scenario='scenario_three'",
                "[10:00:01] [STEP] START scenario='scenario_three' step=0",
                "[10:00:02] [STEP] START scenario='scenario_three' step=1",
                "[10:00:03] [PERF][scenario_summary] scenario=scenario_three total_runtime=3.0 total_steps=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    profile = profiler.build_profile(**paths)
    scenario = _scenario(profile, "scenario_three")

    assert scenario["attempted_step_count"] == 2
    assert scenario["persisted_step_count"] == 1
    assert scenario["suppressed_row_count"] == 1
    assert scenario["suppressed_row_count_estimated"] is True


def test_artifact_dir_resolves_latest_same_stem_files(tmp_path):
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    older.mkdir()
    newer.mkdir()
    old_paths = _artifact_set(older)
    new_stem = "talkback_compare_20260628_010000"
    for key, suffix in (
        ("xlsx", ".xlsx"),
        ("log", ".normal.log"),
        ("probe_results", ".coverage_probe_results.aggregate.json"),
        ("probe_validation", ".coverage_probe_validation.aggregate.json"),
    ):
        old_paths[key].replace(newer / f"{new_stem}{suffix}")

    resolved = profiler.resolve_artifacts(tmp_path)

    assert all(path.parent == newer for path in resolved.values())
    assert resolved["xlsx"].name == f"{new_stem}.xlsx"
