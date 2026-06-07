from __future__ import annotations

from qa_frontend.backend.runtime_config_selection import write_selected_runtime_config
from tb_runner.plugin_draft import (
    build_plugin_smoke_command,
    normalize_plugin_smoke_request,
    parse_plugin_smoke_summary,
)

import json


def test_smoke_request_validation_requires_scenario_id():
    result = normalize_plugin_smoke_request({"max_steps": 5, "mode": "smoke"})

    assert result["ok"] is False
    assert result["summary"]["failure_reason"] == "scenario_id_missing"


def test_smoke_request_rejects_max_steps_over_limit():
    result = normalize_plugin_smoke_request({"scenario_id": "life_preview_plugin", "max_steps": 11, "mode": "smoke"})

    assert result["ok"] is False
    assert result["summary"]["failure_reason"] == "max_steps_too_high"


def test_smoke_command_builder_returns_single_scenario_smoke_command():
    result = build_plugin_smoke_command("life_preview_plugin", 5)

    assert result["ok"] is True
    assert result["mode"] == "smoke"
    assert result["scenario_ids"] == ["life_preview_plugin"]
    assert result["max_steps_overrides"] == {"life_preview_plugin": 5}
    assert result["argv"] == ["python", "script_test.py", "--mode", "smoke", "--scenario", "life_preview_plugin"]


def test_smoke_summary_parser_success():
    log_text = "\n".join(
        [
            "[SCENARIO][pre_nav] success",
            "[SCENARIO][entry_contract] success scenario='life_preview_plugin' entry_type='card'",
            "[STEP] END scenario='life_preview_plugin' step=0 visible='Preview'",
            "[STEP] END scenario='life_preview_plugin' step=1 visible='Suggestions'",
            "[PERF][scenario_summary] scenario=life_preview_plugin total_steps=2 save_excel_count=1",
        ]
    )

    summary = parse_plugin_smoke_summary(log_text, "life_preview_plugin")

    assert summary["pre_navigation_success"] is True
    assert summary["plugin_open_verified"] is True
    assert summary["steps_collected"] == 2
    assert summary["failure_reason"] == ""
    assert summary["result_status"] == "PASS"


def test_smoke_summary_parser_warn_for_non_fatal_failure_with_steps():
    log_text = "\n".join(
        [
            "[SCENARIO][pre_nav] success",
            "[STEP] END scenario='life_preview_plugin' step=0 visible='Preview'",
            "[STOP][eval] step=1 scenario='life_preview_plugin' failure_reason='repeat_no_progress'",
        ]
    )

    summary = parse_plugin_smoke_summary(log_text, "life_preview_plugin")

    assert summary["result_status"] == "WARN"
    assert summary["failure_reason"] == "repeat_no_progress"


def test_smoke_summary_parser_fail_when_no_steps_after_failure():
    log_text = "\n".join(
        [
            "[SCENARIO][pre_nav] failed reason='action_failed' step=1",
            "[PERF][scenario_summary] scenario=life_preview_plugin total_steps=0 save_excel_count=0",
        ]
    )

    summary = parse_plugin_smoke_summary(log_text, "life_preview_plugin")

    assert summary["result_status"] == "FAIL"
    assert summary["failure_reason"] == "pre_navigation_failed"


def test_smoke_summary_parser_traceback_or_fatal():
    summary = parse_plugin_smoke_summary("Traceback\nfatal crash\n", "life_preview_plugin")

    assert summary["plugin_open_verified"] is False
    assert summary["failure_reason"] == "traceback_or_fatal"
    assert summary["result_status"] == "FAIL"


def test_selected_runtime_config_accepts_explicit_smoke_max_steps_override(tmp_path):
    source_path = tmp_path / "runtime_config.json"
    output_path = tmp_path / "run" / "runtime_config.json"
    source_path.write_text(
        json.dumps({"scenarios": {"life_preview_plugin": {"enabled": False, "max_steps": 50}}}),
        encoding="utf-8",
    )

    result = write_selected_runtime_config(
        source_path=source_path,
        output_path=output_path,
        scenario_ids=["life_preview_plugin"],
        mode="smoke",
        max_steps_overrides={"life_preview_plugin": 5},
    )

    generated = json.loads(output_path.read_text(encoding="utf-8"))
    assert generated["scenarios"]["life_preview_plugin"]["enabled"] is True
    assert generated["scenarios"]["life_preview_plugin"]["max_steps"] == 5
    assert result["scenario_steps"][0]["policy"] == "explicit_override"
