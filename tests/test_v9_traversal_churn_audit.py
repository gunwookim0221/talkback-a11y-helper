from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import Workbook

from tools import v9_traversal_churn_audit as audit


def _write_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "result"
    sheet.append(
        [
            "scenario_id",
            "step",
            "context_type",
            "visible_label",
            "merged_announcement",
            "row_source",
            "final_result",
            "focus_view_id",
        ]
    )
    sheet.append(["life_energy_plugin", 1, "main", "Energy", "Energy", "actual_focus", "PASS", "energy"])
    sheet.append(["life_energy_plugin", 4, "main", "Use less energy", "Use less energy", "actual_focus", "PASS", "tips"])
    sheet.append(["life_energy_plugin", -1, "main", "Summary note", "Summary note", "", "WARN", ""])
    sheet.append(["device_washer_plugin", 1, "main", "Washer", "Washer", "actual_focus", "PASS", "washer"])
    workbook.save(path)


def _write_log(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[10:00:00] [SCENARIO][stabilization] scenario='life_energy_plugin'",
                "[10:00:01] [STEP] START scenario='life_energy_plugin' step=1",
                "[10:00:02] [STEP] END scenario='life_energy_plugin' step=1 final_result='PASS'",
                "[10:00:03] [STEP] START scenario='life_energy_plugin' step=2",
                "[10:00:04] [STEP][row_filter] label='Energy' reason='visited_logical_signature'",
                "[10:00:05] [STOP][eval] step=2 scenario='life_energy_plugin' reason='repeat_no_progress'",
                "[10:00:06] [STEP] START scenario='life_energy_plugin' step=3",
                "[10:00:07] [STEP][local_tab_gate] allowed=false reason='no_unvisited_local_tab' tabs='Activity|Location' active='Activity' unvisited='none'",
                "[10:00:08] [STEP][pre_stop_summary] strip_focus_context=true scroll_fallback_allowed=false scroll_fallback_block_reason='bottom_strip_context_scrollable_uncertain' local_tab_block_reason='no_unvisited_local_tab'",
                "[10:00:09] [STEP] START scenario='life_energy_plugin' step=4",
                "[10:00:10] [STEP][viewport_exhausted_eval] result=true reason='no_representative_candidates'",
                "[10:00:11] [STEP][local_tab_gate] allowed=false reason='local_tab_state_missing' tabs='none' active='none' unvisited='none'",
                "[10:00:12] [STEP][last_scroll_fallback_eval] allowed=true reason='bottom_strip_context_scrollable_uncertain'",
                "[10:00:13] [STEP] END scenario='life_energy_plugin' step=4 final_result='PASS'",
                "[10:00:14] [STOP][summary] scenario='life_energy_plugin' stop_triggered=true stop_step=4 reason='repeat_no_progress'",
                "[10:00:15] [PERF][scenario_summary] scenario=life_energy_plugin total_runtime=15.0 total_steps=2",
                "[10:01:00] [SCENARIO][stabilization] scenario='device_washer_plugin'",
                "[10:01:01] [STEP] START scenario='device_washer_plugin' step=1",
                "[10:01:02] [OVERLAY] candidate matched scenario='device_washer_plugin' step=1 view_id='more' label='More options' reason='plugin_more_options'",
                "[10:01:03] [STEP] END scenario='device_washer_plugin' step=1 final_result='PASS'",
                "[10:01:04] [STEP] START scenario='device_washer_plugin' step=2",
                "[10:01:05] [STEP][viewport_exhausted_eval] result=true reason='no_representative_candidates'",
                "[10:01:06] [STOP][summary] scenario='device_washer_plugin' stop_triggered=true stop_step=2 reason='safety_limit'",
                "[10:01:07] [PERF][scenario_summary] scenario=device_washer_plugin total_runtime=7.0 total_steps=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_profile_json(path: Path) -> None:
    path.write_text(json.dumps({"summary": {"total_attempted_steps": 6}}), encoding="utf-8")


def _artifact_set(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "xlsx": tmp_path / "talkback_compare_20260629_000001.xlsx",
        "log": tmp_path / "talkback_compare_20260629_000001.normal.log",
        "profile_json": tmp_path / "v8_fullrun_profile.json",
    }
    _write_xlsx(paths["xlsx"])
    _write_log(paths["log"])
    _write_profile_json(paths["profile_json"])
    return paths


def _scenario(payload: dict, scenario_id: str) -> dict:
    return next(row for row in payload["scenarios"] if row["scenario_id"] == scenario_id)


def test_build_audit_classifies_steps_and_counts_metrics(tmp_path):
    paths = _artifact_set(tmp_path)

    payload = audit.build_audit(**paths)
    energy = _scenario(payload, "life_energy_plugin")
    washer = _scenario(payload, "device_washer_plugin")

    assert energy["attempted_step_count"] == 4
    assert energy["persisted_step_count"] == 2
    assert energy["suppressed_row_count"] == 2
    assert energy["nonstep_result_row_count"] == 1
    assert energy["productive_count"] == 2
    assert energy["unique_meaningful_count"] == 2
    assert energy["duplicate_count"] == 1
    assert energy["bottom_strip_churn_count"] == 1
    assert energy["local_tab_churn_count"] == 0
    assert energy["scroll_retry_churn_count"] == 0
    assert energy["viewport_exhausted_churn_count"] == 0
    assert energy["repeat_no_progress_count"] == 1
    assert energy["stop_reason"] == "repeat_no_progress"
    assert energy["churn_ratio"] == 0.5
    assert energy["productive_ratio"] == 0.5

    assert washer["attempted_step_count"] == 2
    assert washer["persisted_step_count"] == 1
    assert washer["overlay_churn_count"] == 0
    assert washer["viewport_exhausted_churn_count"] == 1
    assert washer["productive_count"] == 1
    assert washer["stop_reason"] == "safety_limit"

    categories = {step["step"]: step["classification"] for step in energy["steps"]}
    assert categories[1] == audit.CATEGORY_PRODUCTIVE
    assert categories[2] == audit.CATEGORY_DUPLICATE
    assert categories[3] == audit.CATEGORY_BOTTOM_STRIP
    assert categories[4] == audit.CATEGORY_PRODUCTIVE
    assert (
        energy["productive_count"]
        + energy["duplicate_count"]
        + energy["bottom_strip_churn_count"]
        + energy["local_tab_churn_count"]
        + energy["overlay_churn_count"]
        + energy["scroll_retry_churn_count"]
        + energy["viewport_exhausted_churn_count"]
        + energy["unknown_count"]
    ) == energy["attempted_step_count"]


def test_writes_json_markdown_and_csv_outputs(tmp_path):
    paths = _artifact_set(tmp_path)
    payload = audit.build_audit(**paths)
    output_dir = tmp_path / "churn"

    outputs = audit.write_outputs(payload, output_dir)

    assert set(outputs) == {"json", "markdown", "csv"}
    assert all(path.is_file() for path in outputs.values())
    loaded = json.loads(outputs["json"].read_text(encoding="utf-8"))
    assert loaded["summary"]["scenario_count"] == 2
    markdown = outputs["markdown"].read_text(encoding="utf-8")
    assert "## Run Summary" in markdown
    assert "## Scenario Table" in markdown
    assert "## Priority Scenarios" in markdown
    with outputs["csv"].open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert [row["scenario_id"] for row in rows] == ["life_energy_plugin", "device_washer_plugin"]
    assert list(rows[0]) == audit.SCENARIO_FIELDS
    assert rows[0]["duplicate_count"] == "1"


def test_main_resolves_artifact_dir_and_optional_profile_json(tmp_path, capsys):
    paths = _artifact_set(tmp_path)
    output_dir = tmp_path / "rendered"

    exit_code = audit.main(["--artifact-dir", str(tmp_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "audited 2 scenarios" in captured
    assert (output_dir / audit.AUDIT_JSON).is_file()
    assert (output_dir / audit.AUDIT_MARKDOWN).is_file()
    assert (output_dir / audit.AUDIT_CSV).is_file()
