import json

from tb_runner import coverage_probe_engine, coverage_probe_validation
from tb_runner.excel_report import build_probe_shadow_rows


def _candidate(label: str, scenario_id: str, bounds: str = "10,20,110,120") -> dict:
    return {
        "label": label,
        "normalized_label": label.lower(),
        "scenario_id": scenario_id,
        "tab_name": scenario_id,
        "view_id": label,
        "bounds": bounds,
        "taxonomy": "REQUIRED",
        "coverage_status": "MISSED",
        "coverage_reason": "no_matching_row",
        "probe_intent": "VERIFY_MISSING_NODE",
        "probe_priority": 1,
        "probe_eligible": True,
        "probe_method_candidate": "helper_focus_in_bounds",
    }


def _plan(candidates: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "source": "v8_coverage_probe_plan",
        "summary": {"candidate_count": len(candidates)},
        "candidates": candidates,
    }


class _Client:
    def __init__(self, labels: list[str] | None = None):
        self.labels = list(labels or [])
        self.focus_in_bounds_calls = []
        self.last_merged_announcement = ""
        self.last_announcements = []

    def focus_in_bounds(self, **kwargs):
        self.focus_in_bounds_calls.append(kwargs)
        label = self.labels.pop(0) if self.labels else "Focused"
        self.last_merged_announcement = label
        self.last_announcements = [label]
        return {
            "success": True,
            "status": "moved",
            "detail": "content_like_focused_row",
            "raw": {
                "success": True,
                "reason": "content_like_focused_row",
                "focused": {
                    "mergedLabel": label,
                    "talkbackLabel": label,
                    "text": label,
                    "viewIdResourceName": label,
                    "boundsInScreen": {"l": 10, "t": 20, "r": 110, "b": 120},
                },
            },
        }

    def get_focus(self, **_kwargs):
        return {
            "mergedLabel": self.last_merged_announcement,
            "talkbackLabel": self.last_merged_announcement,
            "text": self.last_merged_announcement,
            "viewIdResourceName": self.last_merged_announcement,
            "packageName": "com.samsung.android.oneconnect",
        }

    def scroll(self, **_kwargs):
        return False

    def _run(self, args, **_kwargs):
        command = " ".join(args)
        if "dumpsys window policy" in command:
            return "isStatusBarKeyguard=false"
        if "dumpsys window" in command:
            return "mCurrentFocus=Window{42 u0 com.samsung.android.oneconnect/.MainActivity}"
        if "dumpsys power" in command:
            return "mWakefulness=Awake\nDisplay Power: state=ON"
        return ""


def _write_plan(output_path, candidates: list[dict]):
    path = coverage_probe_engine.coverage_probe_plan_path(str(output_path))
    path.write_text(json.dumps(_plan(candidates), ensure_ascii=False), encoding="utf-8")
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_single_scenario_creates_probe_aggregates(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    _write_plan(output_path, [_candidate("100%", "scenario_a")])

    coverage_probe_engine.execute_probe_plan_file(
        _Client(["100%"]),
        "device",
        output_path=str(output_path),
        enabled=True,
        current_scenario_id="scenario_a",
    )

    result_aggregate = _read(coverage_probe_engine.coverage_probe_results_aggregate_path(str(output_path)))
    validation_aggregate = _read(coverage_probe_validation.coverage_probe_validation_aggregate_path(str(output_path)))
    assert result_aggregate["scenario_count"] == 1
    assert result_aggregate["scenarios"][0]["scenario_id"] == "scenario_a"
    assert validation_aggregate["scenario_count"] == 1
    assert validation_aggregate["scenarios"][0]["scenario_id"] == "scenario_a"


def test_three_scenarios_accumulate_without_overwrite(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    scenarios = ["scenario_a", "scenario_b", "scenario_c"]

    for scenario in scenarios:
        _write_plan(output_path, [_candidate(scenario.upper(), scenario)])
        coverage_probe_engine.execute_probe_plan_file(
            _Client([scenario.upper()]),
            "device",
            output_path=str(output_path),
            enabled=True,
            current_scenario_id=scenario,
        )

    result_aggregate = _read(coverage_probe_engine.coverage_probe_results_aggregate_path(str(output_path)))
    assert result_aggregate["scenario_count"] == 3
    assert [item["scenario_id"] for item in result_aggregate["scenarios"]] == scenarios
    assert [item["candidate_count"] for item in result_aggregate["scenarios"]] == [1, 1, 1]


def test_aggregate_totals_equal_scenario_sums(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    _write_plan(output_path, [_candidate("A", "scenario_a")])
    coverage_probe_engine.execute_probe_plan_file(
        _Client(["A"]),
        "device",
        output_path=str(output_path),
        enabled=True,
        current_scenario_id="scenario_a",
    )
    _write_plan(output_path, [_candidate("B", "scenario_b"), _candidate("C", "scenario_b", "20,30,120,130")])
    coverage_probe_engine.execute_probe_plan_file(
        _Client(["B", "C"]),
        "device",
        output_path=str(output_path),
        enabled=True,
        current_scenario_id="scenario_b",
    )

    aggregate = _read(coverage_probe_engine.coverage_probe_results_aggregate_path(str(output_path)))
    scenarios = aggregate["scenarios"]
    assert aggregate["total_candidate_count"] == sum(item["candidate_count"] for item in scenarios)
    assert aggregate["total_attempted_count"] == sum(item["attempted_count"] for item in scenarios)
    assert aggregate["total_success_count"] == sum(item["success_count"] for item in scenarios)
    assert aggregate["total_failed_count"] == sum(item["failed_count"] for item in scenarios)
    assert aggregate["total_skipped_count"] == sum(item["skipped_count"] for item in scenarios)


def test_validation_aggregate_accumulates_totals_and_validations(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    for scenario, label in [("scenario_a", "Alpha"), ("scenario_b", "Beta")]:
        _write_plan(output_path, [_candidate(label, scenario)])
        coverage_probe_engine.execute_probe_plan_file(
            _Client([label]),
            "device",
            output_path=str(output_path),
            enabled=True,
            current_scenario_id=scenario,
        )

    aggregate = _read(coverage_probe_validation.coverage_probe_validation_aggregate_path(str(output_path)))
    assert aggregate["scenario_count"] == 2
    assert aggregate["total_result_count"] == 2
    assert aggregate["total_match_count"] == 2
    assert len(aggregate["validations"]) == 2
    assert [item["scenario_id"] for item in aggregate["scenarios"]] == ["scenario_a", "scenario_b"]


def test_per_scenario_compatibility_files_remain_last_scenario_payload(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    for scenario, label in [("scenario_a", "Alpha"), ("scenario_b", "Beta")]:
        _write_plan(output_path, [_candidate(label, scenario)])
        coverage_probe_engine.execute_probe_plan_file(
            _Client([label]),
            "device",
            output_path=str(output_path),
            enabled=True,
            current_scenario_id=scenario,
        )

    result_payload = _read(coverage_probe_engine.coverage_probe_results_path(str(output_path)))
    validation_payload = _read(coverage_probe_validation.coverage_probe_validation_path(str(output_path)))
    assert result_payload["summary"]["candidate_count"] == 1
    assert result_payload["results"][0]["scenario_id"] == "scenario_b"
    assert validation_payload["summary"]["result_count"] == 1
    assert validation_payload["validations"][0]["scenario_id"] == "scenario_b"


def test_backward_compatibility_paths_are_preserved(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    assert coverage_probe_engine.coverage_probe_results_path(str(output_path)).name == "talkback_compare.coverage_probe_results.json"
    assert coverage_probe_validation.coverage_probe_validation_path(str(output_path)).name == "talkback_compare.coverage_probe_validation.json"
    assert coverage_probe_engine.coverage_probe_results_aggregate_path(str(output_path)).name == (
        "talkback_compare.coverage_probe_results.aggregate.json"
    )
    assert coverage_probe_validation.coverage_probe_validation_aggregate_path(str(output_path)).name == (
        "talkback_compare.coverage_probe_validation.aggregate.json"
    )


def test_shadow_row_generation_uses_existing_validation_payload_shape(tmp_path):
    output_path = tmp_path / "talkback_compare.xlsx"
    _write_plan(output_path, [_candidate("100%", "scenario_a")])
    coverage_probe_engine.execute_probe_plan_file(
        _Client(["100%"]),
        "device",
        output_path=str(output_path),
        enabled=True,
        current_scenario_id="scenario_a",
    )

    validation_payload = _read(coverage_probe_validation.coverage_probe_validation_path(str(output_path)))
    rows = build_probe_shadow_rows(validation_payload)
    assert len(rows) == 1
    assert rows[0]["probe_validation_status"] == "MATCH"
