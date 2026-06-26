import json
from types import SimpleNamespace

from tb_runner import collection_flow


def _plan_from_records(records, tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    coverage_payload = {
        "schema_version": "audit-v7-focusable-coverage-v1",
        "output_path": output_path,
        "summary": [],
        "records": records,
    }
    return collection_flow._build_coverage_probe_plan_payload(coverage_payload, output_path)


def test_probe_plan_required_missed_with_bounds_is_eligible(tmp_path):
    payload = _plan_from_records(
        [
            {
                "scenario_id": "device_motion_sensor_plugin",
                "tab_name": "Motion Sensor",
                "label": "Motion detected",
                "view_id": "motion_state",
                "bounds": "123,456,789,999",
                "class_name": "android.widget.TextView",
                "taxonomy": "REQUIRED",
                "taxonomy_reason": "user_state_or_sensor_value",
                "coverage_status": "MISSED",
                "coverage_reason": "no_matching_row",
                "source": "helper_snapshot",
                "local_tab_signature": "history",
            }
        ],
        tmp_path,
    )

    assert payload["summary"]["candidate_count"] == 1
    assert payload["summary"]["eligible_count"] == 1
    candidate = payload["candidates"][0]
    assert candidate["label"] == "Motion detected"
    assert candidate["normalized_label"] == "motion detected"
    assert candidate["probe_eligible"] is True
    assert candidate["probe_ineligible_reason"] == ""
    assert candidate["probe_method_candidate"] == "helper_focus_in_bounds"
    assert candidate["coverage_reason"] == "no_matching_row"
    assert candidate["probe_intent"] == "VERIFY_MISSING_NODE"
    assert candidate["probe_priority"] == 1
    assert candidate["missing_reason"] == "no_persisted_row"


def test_probe_plan_required_missed_with_only_view_id_is_eligible_unresolved(tmp_path):
    payload = _plan_from_records(
        [
            {
                "scenario_id": "device_motion_sensor_plugin",
                "tab_name": "Motion Sensor",
                "label": "100%",
                "view_id": "lowBattery",
                "bounds": "",
                "taxonomy": "REQUIRED",
                "taxonomy_reason": "percentage_value",
                "coverage_status": "MISSED",
                "coverage_reason": "no_matching_row",
                "source": "helper_snapshot",
            }
        ],
        tmp_path,
    )

    candidate = payload["candidates"][0]
    assert candidate["probe_eligible"] is True
    assert candidate["probe_ineligible_reason"] == ""
    assert candidate["probe_method_candidate"] == "unresolved_view_id_only"
    assert candidate["probe_intent"] == "VERIFY_MISSING_NODE"
    assert candidate["probe_priority"] == 1


def test_probe_plan_required_unknown_related_bounds_is_eligible_with_intent(tmp_path):
    payload = _plan_from_records(
        [
            {
                "scenario_id": "device_motion_sensor_plugin",
                "tab_name": "Motion Sensor",
                "label": "100%",
                "view_id": "lowBattery",
                "bounds": "{'l': 747, 't': 310, 'r': 933, 'b': 382}",
                "taxonomy": "REQUIRED",
                "taxonomy_reason": "percentage_value",
                "coverage_status": "UNKNOWN",
                "coverage_reason": "related_bounds_only",
                "source": "helper_snapshot",
            }
        ],
        tmp_path,
    )

    assert payload["summary"]["candidate_count"] == 1
    assert payload["summary"]["required_missed_input_count"] == 0
    assert payload["summary"]["required_unknown_related_bounds_input_count"] == 1
    candidate = payload["candidates"][0]
    assert candidate["probe_eligible"] is True
    assert candidate["coverage_status"] == "UNKNOWN"
    assert candidate["coverage_reason"] == "related_bounds_only"
    assert candidate["probe_intent"] == "VERIFY_RELATED_BOUNDS"
    assert candidate["probe_method_candidate"] == "helper_focus_in_bounds"
    assert candidate["probe_priority"] == 2


def test_probe_plan_required_missed_without_target_is_ineligible(tmp_path):
    payload = _plan_from_records(
        [
            {
                "scenario_id": "device_motion_sensor_plugin",
                "tab_name": "Motion Sensor",
                "label": "Motion detected",
                "view_id": "",
                "bounds": "",
                "taxonomy": "REQUIRED",
                "taxonomy_reason": "user_state_or_sensor_value",
                "coverage_status": "MISSED",
                "coverage_reason": "no_matching_row",
                "source": "helper_snapshot",
            }
        ],
        tmp_path,
    )

    candidate = payload["candidates"][0]
    assert candidate["probe_eligible"] is False
    assert candidate["probe_ineligible_reason"] == "ineligible_no_target"
    assert candidate["probe_method_candidate"] == "ineligible_no_target"
    assert candidate["probe_intent"] == "VERIFY_MISSING_NODE"
    assert candidate["probe_priority"] == 1
    assert payload["summary"]["ineligible_count"] == 1


def test_probe_plan_excludes_non_phase_one_records(tmp_path):
    payload = _plan_from_records(
        [
            {"label": "Graph button", "taxonomy": "REVIEW", "coverage_status": "UNKNOWN"},
            {"label": "No history", "taxonomy": "OPTIONAL", "coverage_status": "MISSED"},
            {"label": "Navigate up", "taxonomy": "IGNORE", "coverage_status": "MISSED"},
            {"label": "100%", "taxonomy": "REQUIRED", "coverage_status": "COVERED"},
            {"label": "Motion detected", "taxonomy": "REQUIRED", "coverage_status": "UNKNOWN", "coverage_reason": "ambiguous_label_match"},
            {"label": "100%", "taxonomy": "REQUIRED", "coverage_status": "UNKNOWN", "coverage_reason": "label_match_view_id_mismatch"},
        ],
        tmp_path,
    )

    assert payload["summary"]["candidate_count"] == 0
    assert payload["candidates"] == []


class _NoFocusClient(SimpleNamespace):
    def __init__(self):
        super().__init__()
        self.focus_in_bounds_calls = 0

    def focus_in_bounds(self, **_kwargs):
        self.focus_in_bounds_calls += 1
        raise AssertionError("focus_in_bounds must not be called while saving probe plans")


def test_saving_focusable_coverage_also_saves_probe_plan_without_focus_movement(tmp_path):
    client = _NoFocusClient()
    output_path = str(tmp_path / "talkback_compare.xlsx")
    collection_flow._register_focusable_inventory_item(
        client,
        output_path=output_path,
        scenario_id="device_motion_sensor_plugin",
        tab_name="Motion Sensor",
        step_index=1,
        label="Motion detected",
        view_id="motion_state",
        bounds="123,456,789,999",
        source="helper_snapshot",
        class_name="android.widget.TextView",
        local_tab_signature="history",
    )
    rows = [
        {
            "scenario_id": "device_motion_sensor_plugin",
            "visible_label": "Motion sensor card",
            "focus_view_id": "motion_card",
            "focus_bounds": "1,2,3,4",
            "final_result": "PASS",
            "mismatch_type": "EXACT_MATCH",
        }
    ]

    collection_flow._save_focusable_coverage(client, output_path, rows)

    coverage_artifact = tmp_path / "talkback_compare.focusable_coverage.json"
    probe_artifact = tmp_path / "talkback_compare.coverage_probe_plan.json"
    coverage_payload = json.loads(coverage_artifact.read_text(encoding="utf-8"))
    probe_payload = json.loads(probe_artifact.read_text(encoding="utf-8"))
    assert coverage_payload["schema_version"] == "audit-v7-focusable-coverage-v1"
    assert coverage_payload["records"][0]["coverage_status"] == "MISSED"
    assert probe_payload["schema_version"] == 1
    assert probe_payload["source"] == "v8_coverage_probe_plan"
    assert probe_payload["summary"]["candidate_count"] == 1
    assert probe_payload["candidates"][0]["probe_intent"] == "VERIFY_MISSING_NODE"
    assert probe_payload["candidates"][0]["probe_method_candidate"] == "helper_focus_in_bounds"
    assert client.focus_in_bounds_calls == 0
    assert rows[0]["final_result"] == "PASS"
    assert rows[0]["mismatch_type"] == "EXACT_MATCH"
