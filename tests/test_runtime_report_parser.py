from pathlib import Path
import shutil
import uuid

import pytest

from tools import runtime_report_parser as parser


@pytest.fixture
def tmp_path():
    base = Path.cwd() / ".test_tmp" / f"runtime_report_parser_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=False)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _write_log(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _baseline_log(
    *,
    stop_reason: str = "safety_limit",
    labels: str = "Medication\nHospital\nEvent\n",
    fatal_line: str = "",
    total_steps: int = 39,
    filtered_rows: int = 37,
    raw_rows: int = 39,
) -> str:
    return f"""
[STOP][summary] reason={stop_reason}
[PERF][scenario_summary] total_steps={total_steps}
[SAVE] filtered rows={filtered_rows} raw rows={raw_rows}
{labels}
[STEP][local_tab_force_navigation_set]
[STEP][local_tab_force_navigation_set]
[STEP][local_tab_force_navigation_set]
[STEP][local_tab_commit]
{fatal_line}
"""


def test_runtime_report_parser_baseline_pass(tmp_path):
    path = _write_log(tmp_path, "baseline.log", _baseline_log())

    summary = parser.parse_log(path)

    assert summary.fatal is False
    assert summary.stop_reason == "safety_limit"
    assert summary.total_steps == 39
    assert summary.raw_rows == 39
    assert summary.filtered_rows == 37
    assert summary.reached_medication is True
    assert summary.reached_hospital is True
    assert summary.reached_event is True
    assert summary.local_tab_force_navigation_set >= 1
    assert summary.local_tab_commit == 1
    assert summary.baseline_pass is True
    assert summary.baseline_reason == "ok"


def test_runtime_report_parser_fails_when_required_labels_missing(tmp_path):
    path = _write_log(
        tmp_path,
        "missing_labels.log",
        _baseline_log(labels="Event\n"),
    )

    summary = parser.parse_log(path)

    assert summary.reached_medication is False
    assert summary.reached_hospital is False
    assert summary.baseline_pass is False
    assert "missing_" in summary.baseline_reason


def test_runtime_report_parser_detects_fatal_signals(tmp_path):
    fatal_lines = [
        "Traceback (most recent call last):",
        "[ERROR] failed to collect focus",
        "adb command timed out after 30s",
    ]
    for index, fatal_line in enumerate(fatal_lines):
        path = _write_log(
            tmp_path,
            f"fatal_{index}.log",
            _baseline_log(fatal_line=fatal_line),
        )

        summary = parser.parse_log(path)

        assert summary.fatal is True
        assert summary.baseline_pass is False
        assert summary.baseline_reason == "fatal_detected"


def test_runtime_report_parser_fails_on_wrong_stop_reason(tmp_path):
    path = _write_log(
        tmp_path,
        "wrong_stop.log",
        _baseline_log(stop_reason="repeat_no_progress"),
    )

    summary = parser.parse_log(path)

    assert summary.stop_reason == "repeat_no_progress"
    assert summary.baseline_pass is False
    assert summary.baseline_reason == "wrong_stop_reason"


def test_runtime_report_parser_extracts_counts(tmp_path):
    path = _write_log(
        tmp_path,
        "counts.log",
        _baseline_log(total_steps=43, filtered_rows=40, raw_rows=42),
    )

    summary = parser.parse_log(path)

    assert summary.total_steps == 43
    assert summary.raw_rows == 42
    assert summary.filtered_rows == 40


def test_runtime_report_parser_aggregates_multiple_logs(tmp_path, capsys):
    passing = parser.parse_log(_write_log(tmp_path, "pass.log", _baseline_log()))
    failing = parser.parse_log(
        _write_log(
            tmp_path,
            "fail.log",
            _baseline_log(labels="Medication\nEvent\n"),
        )
    )

    parser.print_aggregate([passing, failing])

    output = capsys.readouterr().out
    assert "[BASELINE][aggregate]" in output
    assert "runs=2" in output
    assert "passed=1" in output
    assert "failed=1" in output
    assert "fail.log" in output


def test_runtime_report_parser_default_uses_family_care_labels(tmp_path):
    path = _write_log(
        tmp_path,
        "default_family_missing.log",
        _baseline_log(labels="Medication\nEvent\n"),
    )

    summary = parser.parse_log(path)

    assert summary.scenario == "life_family_care_plugin"
    assert summary.expected_labels == ("Medication", "Hospital", "Event")
    assert summary.reached_labels["Hospital"] is False
    assert summary.baseline_pass is False
    assert summary.baseline_reason == "missing_hospital"


def test_runtime_report_parser_scenario_family_care_labels(tmp_path):
    path = _write_log(tmp_path, "family.log", _baseline_log())

    summary = parser.parse_log(path, scenario="life_family_care_plugin")

    assert summary.scenario == "life_family_care_plugin"
    assert summary.expected_labels == ("Medication", "Hospital", "Event")
    assert summary.baseline_pass is True
    assert summary.baseline_reason == "ok"


def test_runtime_report_parser_non_family_plugin_allows_empty_expected_labels(tmp_path):
    path = _write_log(
        tmp_path,
        "air.log",
        _baseline_log(labels=""),
    )

    summary = parser.parse_log(path, scenario="life_air_care_plugin")

    assert summary.scenario == "life_air_care_plugin"
    assert summary.expected_labels == ()
    assert summary.reached_labels == {}
    assert summary.baseline_pass is True
    assert summary.baseline_reason == "ok_no_expected_labels"


def test_runtime_report_parser_custom_expected_labels_override_scenario(tmp_path):
    path = _write_log(
        tmp_path,
        "custom.log",
        _baseline_log(labels="Medication\n"),
    )

    summary = parser.parse_log(
        path,
        scenario="life_air_care_plugin",
        expected_labels=["Medication", "Hospital"],
    )

    assert summary.scenario == "life_air_care_plugin"
    assert summary.expected_labels == ("Medication", "Hospital")
    assert summary.reached_labels["Medication"] is True
    assert summary.reached_labels["Hospital"] is False
    assert summary.baseline_pass is False
    assert summary.baseline_reason == "missing_hospital"


def test_runtime_report_parser_output_includes_expected_labels(tmp_path, capsys):
    path = _write_log(tmp_path, "family_output.log", _baseline_log())
    summary = parser.parse_log(path, scenario="life_family_care_plugin")

    parser.print_summary(summary, include_path=False)

    output = capsys.readouterr().out
    assert "scenario=life_family_care_plugin" in output
    assert "expected_labels=Medication,Hospital,Event" in output
    assert "reached_Medication=True" in output
    assert "reached_Hospital=True" in output
    assert "reached_Event=True" in output


def test_runtime_report_parser_suggests_top_labels():
    text = """
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Hospital' speech='Hospital'
[STEP] END visible='Event' speech='Event'
visible_label='Event'
"""

    candidates = parser.extract_label_candidates(text)
    suggestions = parser.suggest_expected_labels(text)

    assert candidates["Medication"] == 4
    assert candidates["Hospital"] == 2
    assert candidates["Event"] == 3
    assert suggestions[:3] == ["Medication", "Event", "Hospital"]


def test_runtime_report_parser_suggest_labels_filters_noise():
    text = """
[STEP] END visible='Home' speech='Life'
[STEP] END visible='Map' speech='Current location'
[STEP] END visible='Navigate' speech='Back'
[STEP] END visible='Medication' speech='Medication'
merged_announcement='123 Main Street'
visible_label='9:51 am'
speech='0 steps / 6000 %'
"""

    candidates = parser.extract_label_candidates(text)

    assert "Medication" in candidates
    assert "Home" not in candidates
    assert "Life" not in candidates
    assert "Map" not in candidates
    assert "Current location" not in candidates
    assert "Navigate" not in candidates
    assert "123 Main Street" not in candidates
    assert "9:51 am" not in candidates
    assert "0 steps / 6000 %" not in candidates


def test_runtime_report_parser_suggest_label_limit():
    text = """
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Hospital' speech='Hospital'
[STEP] END visible='Event' speech='Event'
"""

    suggestions = parser.suggest_expected_labels(text, limit=2)

    assert len(suggestions) == 2


def test_runtime_report_parser_suggest_labels_outputs_python_snippet(capsys):
    candidates = parser.extract_label_candidates(
        """
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Hospital' speech='Hospital'
"""
    )

    parser.print_label_suggestions(
        candidates,
        scenario="life_family_care_plugin",
        limit=2,
    )

    output = capsys.readouterr().out
    assert "[LABEL_SUGGESTION][python]" in output
    assert '"life_family_care_plugin": [' in output
    assert "'Medication'" in output
    assert "'Hospital'" in output


def test_runtime_report_parser_suggest_labels_does_not_change_baseline_pass(tmp_path):
    path = _write_log(
        tmp_path,
        "baseline.log",
        _baseline_log(
            labels="""
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Hospital' speech='Hospital'
[STEP] END visible='Event' speech='Event'
"""
        ),
    )

    before = parser.parse_log(path)
    candidates = parser.extract_label_candidates(path.read_text(encoding="utf-8"))
    parser.suggest_expected_labels(path.read_text(encoding="utf-8"))
    after = parser.parse_log(path)

    assert candidates
    assert before.baseline_pass is True
    assert after.baseline_pass is before.baseline_pass
    assert after.baseline_reason == before.baseline_reason
