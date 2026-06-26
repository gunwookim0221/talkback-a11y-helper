import json

from tb_runner import coverage_probe_engine, coverage_probe_validation


def _result(**overrides):
    base = {
        "label": "100%",
        "normalized_label": "100%",
        "attempted": True,
        "probe_success": True,
        "probe_success_source": "HELPER_SUCCESS",
        "captured_speech": "",
        "captured_visible_text": "",
    }
    base.update(overrides)
    return base


def _status(result):
    validation = coverage_probe_validation.validate_probe_result(result)
    return validation["validation_status"], validation["validation_confidence"], validation


def test_exact_speech_match_is_high_confidence_match():
    status, confidence, validation = _status(_result(captured_speech="100%"))

    assert status == "MATCH"
    assert confidence == "HIGH"
    assert validation["validation_reason"] == "exact_normalized_match"
    assert validation["matched_channels"] == ["speech"]


def test_exact_visible_text_match_is_high_confidence_match():
    status, confidence, validation = _status(_result(captured_visible_text="100%"))

    assert status == "MATCH"
    assert confidence == "HIGH"
    assert validation["matched_channels"] == ["visible_text"]


def test_full_token_containment_is_high_confidence_match():
    status, confidence, validation = _status(
        _result(
            label="Motion detected",
            normalized_label="motion detected",
            captured_speech="Motion detected",
        )
    )

    assert status == "MATCH"
    assert confidence == "HIGH"
    assert validation["matched_terms"] == ["motion", "detected"]


def test_partial_token_overlap_is_partial_match():
    status, confidence, validation = _status(
        _result(
            label="Motion detected",
            normalized_label="motion detected",
            captured_speech="Motion sensor History",
        )
    )

    assert status == "PARTIAL_MATCH"
    assert confidence == "MEDIUM"
    assert validation["matched_terms"] == ["motion"]
    assert validation["missing_terms"] == ["detected"]


def test_no_overlap_is_mismatch():
    status, confidence, validation = _status(
        _result(
            label="Motion detected",
            normalized_label="motion detected",
            captured_speech="Battery level",
        )
    )

    assert status == "MISMATCH"
    assert confidence == "LOW"
    assert validation["missing_terms"] == ["motion", "detected"]


def test_success_without_speech_or_visible_text_is_no_speech_or_text():
    status, confidence, validation = _status(_result())

    assert status == "NO_SPEECH_OR_TEXT"
    assert confidence == "NONE"
    assert validation["validation_reason"] == "no_speech_or_visible_text"


def test_failed_probe_is_not_validated():
    status, confidence, validation = _status(_result(probe_success=False, failure_reason="focus_failed"))

    assert status == "NOT_VALIDATED"
    assert confidence == "NONE"
    assert validation["validation_reason"] == "probe_failed"


def test_skipped_probe_is_not_validated():
    status, confidence, validation = _status(_result(attempted=False, probe_success=False))

    assert status == "NOT_VALIDATED"
    assert confidence == "NONE"
    assert validation["validation_reason"] == "probe_skipped"


def test_numeric_percent_value_matches_percent_word_form():
    status, confidence, validation = _status(_result(captured_speech="Battery 100 percent"))

    assert status == "MATCH"
    assert confidence == "HIGH"
    assert validation["validation_reason"] == "numeric_value_match"


def test_build_validation_payload_counts_statuses():
    payload = coverage_probe_validation.build_validation_payload(
        {
            "results": [
                _result(captured_speech="100%"),
                _result(label="Motion detected", captured_speech="Motion sensor History"),
                _result(label="Motion detected", captured_speech="Battery level"),
                _result(probe_success=False),
            ]
        },
        probe_results_path="talkback_compare.coverage_probe_results.json",
        output_path="talkback_compare.xlsx",
    )

    assert payload["source"] == "v8_coverage_probe_validation"
    assert payload["summary"]["result_count"] == 4
    assert payload["summary"]["validated_count"] == 3
    assert payload["summary"]["match_count"] == 1
    assert payload["summary"]["partial_match_count"] == 1
    assert payload["summary"]["mismatch_count"] == 1
    assert payload["summary"]["not_validated_count"] == 1


def test_execute_probe_plan_file_writes_validation_artifact(tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    plan_path = coverage_probe_engine.coverage_probe_plan_path(output_path)
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "v8_coverage_probe_plan",
                "candidates": [
                    {
                        "label": "100%",
                        "normalized_label": "100%",
                        "scenario_id": "device_motion_sensor_plugin",
                        "tab_name": "Motion Sensor",
                        "view_id": "lowBattery",
                        "bounds": "747,310,933,382",
                        "taxonomy": "REQUIRED",
                        "coverage_status": "UNKNOWN",
                        "coverage_reason": "related_bounds_only",
                        "probe_intent": "VERIFY_RELATED_BOUNDS",
                        "probe_priority": 2,
                        "probe_eligible": True,
                        "probe_method_candidate": "helper_focus_in_bounds",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class Client:
        last_merged_announcement = ""

        def focus_in_bounds(self, **_kwargs):
            self.last_merged_announcement = "100%"
            return {
                "success": True,
                "raw": {
                    "success": True,
                    "focused": {
                        "mergedLabel": "100%",
                        "text": "100%",
                        "viewIdResourceName": "lowBattery",
                    },
                },
            }

        def get_focus(self, **_kwargs):
            return {"mergedLabel": "100%", "text": "100%", "viewIdResourceName": "lowBattery"}

    coverage_probe_engine.execute_probe_plan_file(Client(), "device", output_path=output_path, enabled=True)

    validation_path = coverage_probe_validation.coverage_probe_validation_path(output_path)
    assert validation_path.exists()
    validation_payload = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation_payload["summary"]["match_count"] == 1
    assert validation_payload["validations"][0]["validation_status"] == "MATCH"
