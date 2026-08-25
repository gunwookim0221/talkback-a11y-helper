from __future__ import annotations

import openpyxl

from qa_frontend.backend.coverage_health import build_coverage_health_report


RESULT_HEADERS = [
    "scenario_id",
    "semantic_value_total_count",
    "semantic_value_matched_count",
]


def _write_result(path, rows):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "result"
    sheet.append(RESULT_HEADERS)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def _scenario(scenario_id: str, **values):
    return {"id": scenario_id, "status": "passed", **values}


def _log(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _write_log(tmp_path, text: str):
    path = tmp_path / "run.normal.log"
    path.write_text(text, encoding="utf-8")
    return path


def _one_report(tmp_path, scenario, *, log_lines, rows=None, focusable=None):
    log_path = _write_log(tmp_path, _log(*log_lines))
    xlsx_path = tmp_path / "result.xlsx"
    _write_result(xlsx_path, rows or [])
    report = build_coverage_health_report(
        scenarios=[scenario],
        log_path=log_path,
        xlsx_path=xlsx_path,
        focusable_coverage=focusable,
    )
    return report["scenarios"][0], report


def test_anchor_mode_with_substantial_content_is_content_traversed(tmp_path):
    scenario, _ = _one_report(
        tmp_path,
        _scenario("device_smoke_sensor_plugin", status="warning", traversal_result="FAIL_STUCK"),
        log_lines=[
            "[SCENARIO][stabilization] scenario='device_smoke_sensor_plugin' screen_context_mode='new_screen' stabilization_mode='anchor_only'",
            "[ANCHOR][scenario_start] success scenario='device_smoke_sensor_plugin' selected=True matched=True stable=True context_ok=True reason='selected_and_verified'",
            "[SCENARIO][entry_contract] success scenario='device_smoke_sensor_plugin' entry_type='card' reason='success_verified' detail='plugin_open_verified'",
        ],
        rows=[("device_smoke_sensor_plugin", 0, 0)] * 15,
    )

    assert scenario["stabilization_mode"] == "anchor_only"
    assert scenario["anchor_present"] is True
    assert scenario["content_entered"] is True
    assert scenario["entry_failed"] is False
    assert scenario["content_row_count"] == 15
    assert scenario["derived_classification"] == "CONTENT_TRAVERSED"
    assert scenario["traversal_terminal_state"] == "FAIL_STUCK"


def test_smoke_like_result_row_count_is_retained(tmp_path):
    scenario, _ = _one_report(
        tmp_path,
        _scenario("device_smoke_sensor_plugin"),
        log_lines=[
            "[SCENARIO][stabilization] scenario='device_smoke_sensor_plugin' stabilization_mode='anchor_only'",
            "[SCENARIO][entry_contract] success scenario='device_smoke_sensor_plugin' detail='plugin_open_verified'",
        ],
        rows=[("device_smoke_sensor_plugin", 0, 0)] * 15,
    )
    assert scenario["content_entered"] is True
    assert scenario["content_row_count"] == 15


def test_unavailable_target_is_entry_failed_not_content(tmp_path):
    scenario, _ = _one_report(
        tmp_path,
        _scenario(
            "life_air_care_plugin",
            status="no_target_candidate",
            availability_status="NO_TARGET_CANDIDATE",
        ),
        log_lines=[
            "[SCENARIO][stabilization] scenario='life_air_care_plugin' stabilization_mode='anchor_only'",
        ],
        rows=[],
    )
    assert scenario["content_entered"] is False
    assert scenario["entry_failed"] is True
    assert scenario["content_row_count"] == 0
    assert scenario["availability_state"] == "NO_TARGET_CANDIDATE"
    assert scenario["derived_classification"] == "ENTRY_FAILED_OR_UNAVAILABLE"


def test_handled_settings_state_is_conservative(tmp_path):
    scenario, _ = _one_report(
        tmp_path,
        _scenario("settings_entry_example", special_state_handled=True, entry_contract_status="handled"),
        log_lines=[
            "[SCENARIO][stabilization] scenario='settings_entry_example' stabilization_mode='anchor_only'",
            "[ANCHOR][scenario_start] success scenario='settings_entry_example' selected=False matched=True stable=True context_ok=True reason='verified_without_select'",
            "[SCENARIO][entry_contract] handled scenario='settings_entry_example' reason='special_state_handled'",
        ],
    )
    assert scenario["content_entered"] is False
    assert scenario["entry_failed"] is False
    assert scenario["derived_classification"] == "HANDLED_SPECIAL_STATE"
    assert scenario["availability_state"] == "HANDLED_SPECIAL_STATE"


def test_internal_stabilization_mode_is_preserved_in_projection(tmp_path):
    scenario, _ = _one_report(
        tmp_path,
        _scenario("life_food_plugin"),
        log_lines=[
            "[SCENARIO][stabilization] scenario='life_food_plugin' stabilization_mode='anchor_only'",
            "[SCENARIO][entry_contract] success scenario='life_food_plugin' detail='plugin_open_verified'",
        ],
        rows=[("life_food_plugin", 0, 0)],
    )
    assert scenario["stabilization_mode"] == "anchor_only"


def test_fail_stuck_after_entry_preserves_terminal_and_content(tmp_path):
    scenario, _ = _one_report(
        tmp_path,
        _scenario("life_energy_plugin", status="warning", traversal_result="FAIL_STUCK", stop_reason="none"),
        log_lines=[
            "[SCENARIO][stabilization] scenario='life_energy_plugin' stabilization_mode='anchor_only'",
            "[SCENARIO][entry_contract] success scenario='life_energy_plugin' detail='plugin_open_verified'",
        ],
        rows=[("life_energy_plugin", 0, 0)] * 3,
    )
    assert scenario["content_entered"] is True
    assert scenario["entry_failed"] is False
    assert scenario["traversal_terminal_state"] == "FAIL_STUCK"
    assert scenario["scenario_result"] == "warning"


def test_entry_failure_remains_distinct_from_fail_stuck(tmp_path):
    scenario, _ = _one_report(
        tmp_path,
        _scenario("device_tv_plugin", status="not_available_candidate", availability_status="NOT_AVAILABLE_CANDIDATE"),
        log_lines=[
            "[SCENARIO][stabilization] scenario='device_tv_plugin' stabilization_mode='anchor_only'",
            "[ANCHOR][scenario_start] abort scenario='device_tv_plugin' reason='insufficient_new_screen_evidence'",
        ],
    )
    assert scenario["entry_failed"] is True
    assert scenario["content_entered"] is False
    assert scenario["traversal_terminal_state"] is None
    assert scenario["derived_classification"] == "ENTRY_FAILED_OR_UNAVAILABLE"


def test_focusable_metric_is_candidate_coverage_with_explicit_counts(tmp_path):
    _, report = _one_report(
        tmp_path,
        _scenario("life_family_care_plugin"),
        log_lines=[],
        focusable={
            "summary": {
                "focusable_expected_count": 347,
                "focusable_covered_count": 165,
                "focusable_missed_count": 85,
                "focusable_unknown_count": 97,
                "focusable_ignored_count": 46,
                "focusable_coverage_rate": 47.6,
            }
        },
    )
    coverage = report["focusable_candidate_coverage"]
    assert coverage["label"] == "Focusable candidate coverage"
    assert coverage["formula"] == "covered / expected"
    assert coverage["covered_count"] == 165
    assert coverage["expected_count"] == 347
    assert coverage["missed_count"] == 85
    assert coverage["unknown_count"] == 97
    assert coverage["ignored_count"] == 46
    assert coverage["rate"] == 47.6


def test_semantic_value_coverage_is_separate_from_focusable_metric(tmp_path):
    _, report = _one_report(
        tmp_path,
        _scenario("routines_main"),
        log_lines=[],
        rows=[("routines_main", 39, 36)],
        focusable={"summary": {"focusable_expected_count": 1, "focusable_covered_count": 1}},
    )
    semantic = report["semantic_value_coverage"]
    assert semantic["label"] == "Semantic value coverage"
    assert semantic["formula"] == "covered / expected"
    assert semantic["covered_count"] == 36
    assert semantic["expected_count"] == 39
    assert semantic["rate"] == 92.3
    assert report["focusable_candidate_coverage"]["expected_count"] == 1


def test_anchor_mode_aggregate_classification_has_no_implicit_failure(tmp_path):
    scenarios = []
    log_lines = []
    rows = []
    for index in range(16):
        scenario_id = f"content_{index}"
        scenarios.append(_scenario(scenario_id))
        log_lines.extend(
            [
                f"[SCENARIO][stabilization] scenario='{scenario_id}' stabilization_mode='anchor_only'",
                f"[SCENARIO][entry_contract] success scenario='{scenario_id}' detail='plugin_open_verified'",
            ]
        )
        rows.append((scenario_id, 0, 0))
    for index in range(9):
        scenario_id = f"unavailable_{index}"
        scenarios.append(
            _scenario(
                scenario_id,
                status="not_available_candidate",
                availability_status="NOT_AVAILABLE_CANDIDATE",
            )
        )
        log_lines.append(
            f"[SCENARIO][stabilization] scenario='{scenario_id}' stabilization_mode='anchor_only'"
        )
    scenarios.append(_scenario("settings_entry_example", special_state_handled=True))
    log_lines.extend(
        [
            "[SCENARIO][stabilization] scenario='settings_entry_example' stabilization_mode='anchor_only'",
            "[SCENARIO][entry_contract] handled scenario='settings_entry_example' reason='special_state_handled'",
        ]
    )
    log_path = _write_log(tmp_path, _log(*log_lines))
    xlsx_path = tmp_path / "result.xlsx"
    _write_result(xlsx_path, rows)

    report = build_coverage_health_report(scenarios=scenarios, log_path=log_path, xlsx_path=xlsx_path)
    assert report["summary"] == {
        "anchor_mode_count": 26,
        "true_anchor_traversal_failure_count": 0,
        "anchor_mode_content_traversed_count": 16,
        "unavailable_or_no_target_count": 9,
        "handled_or_ambiguous_count": 1,
        "content_entered_count": 16,
        "entry_failed_count": 9,
    }


def test_existing_scenario_outcome_fields_are_only_projected_not_reclassified(tmp_path):
    scenario, _ = _one_report(
        tmp_path,
        _scenario("life_home_monitor_plugin", status="passed", traversal_result="WARN_PLUGIN_BOUNDARY"),
        log_lines=[
            "[SCENARIO][stabilization] scenario='life_home_monitor_plugin' stabilization_mode='anchor_only'",
            "[SCENARIO][entry_contract] success scenario='life_home_monitor_plugin' detail='plugin_open_verified'",
        ],
        rows=[("life_home_monitor_plugin", 0, 0)],
    )
    assert scenario["scenario_result"] == "passed"
    assert scenario["traversal_terminal_state"] == "WARN_PLUGIN_BOUNDARY"
    assert scenario["derived_classification"] == "CONTENT_TRAVERSED"
