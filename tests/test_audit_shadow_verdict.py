from tools.audit_shadow_verdict import (
    add_shadow_verdict_fields,
    calculate_balanced_shadow_verdict,
    calculate_shadow_coverage_inputs,
)


def _base_report(**overrides):
    report = {
        "verdict": "PASS",
        "coverage_diagnostic_status": "ready",
        "coverage_denominator_count": 5,
        "coverage_matched_count": 5,
        "coverage_missing_count": 0,
        "coverage_percent": 100.0,
        "coverage_missing_labels_sample": "",
        "coverage_missing_reason_sample": "",
    }
    report.update(overrides)
    return report


def test_balanced_shadow_verdict_passes_clean_required_coverage():
    shadow = calculate_balanced_shadow_verdict(_base_report())

    assert shadow["policy_name"] == "balanced_v1"
    assert shadow["verdict"] == "PASS"
    assert shadow["required_coverage"] == 100.0
    assert shadow["required_missing_count"] == 0
    assert shadow["traversal_gap_count"] == 0
    assert shadow["taxonomy_gap_count"] == 0


def test_balanced_shadow_verdict_reviews_threshold_miss():
    shadow = calculate_balanced_shadow_verdict(
        _base_report(
            coverage_denominator_count=10,
            coverage_matched_count=8,
            coverage_missing_count=2,
            coverage_percent=80.0,
        )
    )

    assert shadow["verdict"] == "REVIEW"
    assert shadow["reason"] == "balanced_policy_review_threshold"


def test_balanced_shadow_verdict_fails_low_required_coverage():
    shadow = calculate_balanced_shadow_verdict(
        _base_report(
            coverage_denominator_count=10,
            coverage_matched_count=4,
            coverage_missing_count=6,
            coverage_percent=40.0,
        )
    )

    assert shadow["verdict"] == "FAIL"
    assert shadow["reason"] == "required_coverage<50"


def test_balanced_shadow_verdict_fails_when_v3_fails():
    shadow = calculate_balanced_shadow_verdict(_base_report(verdict="FAIL"))

    assert shadow["verdict"] == "FAIL"
    assert shadow["reason"] == "v3_verdict=FAIL"


def test_balanced_shadow_verdict_keeps_environment_error():
    shadow = calculate_balanced_shadow_verdict(_base_report(verdict="ENVIRONMENT_ERROR"))

    assert shadow["verdict"] == "ENVIRONMENT_ERROR"
    assert shadow["reason"] == "environment_error=true"


def test_balanced_shadow_verdict_reviews_unready_coverage():
    shadow = calculate_balanced_shadow_verdict(
        _base_report(
            coverage_diagnostic_status="xml_missing",
            coverage_denominator_count=0,
            coverage_matched_count=0,
            coverage_missing_count=0,
            coverage_percent=0.0,
        )
    )

    assert shadow["verdict"] == "REVIEW"
    assert shadow["reason"] == "coverage_not_ready:xml_missing"


def test_balanced_shadow_verdict_allows_ready_empty_denominator_with_required_inputs():
    shadow = calculate_balanced_shadow_verdict(
        _base_report(
            coverage_diagnostic_status="ready_empty_denominator",
            coverage_denominator_count=0,
            coverage_matched_count=0,
            coverage_missing_count=0,
            coverage_percent=0.0,
            required_denominator_count=2,
            required_matched_count=2,
            required_missing_count=0,
            required_coverage=100.0,
            traversal_gap_count=0,
            taxonomy_gap_count=0,
        )
    )

    assert shadow["verdict"] == "PASS"
    assert shadow["reason"] == "required_coverage>=90 and required_missing_count<=1 and no traversal/taxonomy gaps"


def test_balanced_shadow_verdict_blocks_missing_xml_even_with_required_inputs():
    shadow = calculate_balanced_shadow_verdict(
        _base_report(
            coverage_diagnostic_status="xml_missing",
            required_denominator_count=2,
            required_matched_count=2,
            required_missing_count=0,
            required_coverage=100.0,
        )
    )

    assert shadow["verdict"] == "REVIEW"
    assert shadow["reason"] == "coverage_not_ready:xml_missing"


def test_shadow_coverage_inputs_treat_device_keep_status_as_required():
    candidates = [
        {
            "label": "Motion sensor",
            "candidate_type": "STATUS",
            "candidate_subtype": "STATUS_LABEL",
            "policy_recommendation": "KEEP",
        },
        {
            "label": "Controls",
            "candidate_type": "ACTIONABLE",
            "candidate_subtype": "UNKNOWN",
            "policy_recommendation": "KEEP",
        },
        {
            "label": "No history",
            "candidate_type": "EMPTY_STATE",
            "candidate_subtype": "UNKNOWN",
            "policy_recommendation": "REVIEW",
        },
    ]
    tab_stats = {"Controls": {"visible_labels_set": {"Motion sensor"}}}

    shadow_inputs = calculate_shadow_coverage_inputs(candidates, tab_stats, "device_motion_sensor_plugin")

    assert shadow_inputs["required_denominator_count"] == 1
    assert shadow_inputs["required_matched_count"] == 1
    assert shadow_inputs["optional_denominator_count"] == 0
    assert shadow_inputs["provisional_candidate_count"] == 1


def test_shadow_coverage_inputs_treat_unknown_actionable_keep_as_provisional():
    candidates = [
        {
            "label": "Demand Response",
            "candidate_type": "ACTIONABLE",
            "candidate_subtype": "UNKNOWN",
            "policy_recommendation": "KEEP",
            "clickable_values": ["true"],
        },
        {
            "label": "Monitor",
            "candidate_type": "ACTIONABLE",
            "candidate_subtype": "LIFE_TAB",
            "policy_recommendation": "KEEP",
        },
    ]
    tab_stats = {"entry": {"visible_labels_set": {"Monitor"}}}

    shadow_inputs = calculate_shadow_coverage_inputs(candidates, tab_stats, "life_energy_plugin")

    assert shadow_inputs["required_denominator_count"] == 1
    assert shadow_inputs["required_matched_count"] == 1
    assert shadow_inputs["provisional_candidate_count"] == 1
    assert shadow_inputs["known_risk_labels"] == ["Demand Response"]
    assert shadow_inputs["provisional_labels_sample"] == "Demand Response"


def test_shadow_coverage_inputs_treat_life_status_metric_as_optional():
    candidates = [
        {
            "label": "6000",
            "candidate_type": "STATUS",
            "candidate_subtype": "STATUS_METRIC",
            "policy_recommendation": "KEEP",
        },
        {
            "label": "EventsButton",
            "candidate_type": "ACTIONABLE",
            "candidate_subtype": "NAV_TILE",
            "policy_recommendation": "KEEP",
            "clickable_values": ["true"],
        },
    ]
    tab_stats = {"entry": {"visible_labels_set": {"6000"}}}

    shadow_inputs = calculate_shadow_coverage_inputs(candidates, tab_stats, "life_family_care_plugin")

    assert shadow_inputs["required_denominator_count"] == 1
    assert shadow_inputs["required_missing_count"] == 1
    assert shadow_inputs["optional_denominator_count"] == 1
    assert shadow_inputs["known_risk_labels"] == ["EventsButton"]


def test_balanced_shadow_verdict_reports_provisional_risk_without_blocking_pass():
    shadow = calculate_balanced_shadow_verdict(
        _base_report(
            required_denominator_count=3,
            required_matched_count=3,
            required_missing_count=0,
            required_coverage=100.0,
            provisional_candidate_count=2,
            provisional_labels_sample="Demand Response, Energy level Information",
        )
    )

    assert shadow["verdict"] == "PASS"
    assert shadow["known_risk_labels"] == ["Demand Response", "Energy level Information"]
    assert shadow["reason"].endswith("provisional_risk_count=2")


def test_balanced_shadow_verdict_reports_provisional_risk_on_zero_required_review():
    shadow = calculate_balanced_shadow_verdict(
        _base_report(
            required_denominator_count=0,
            required_matched_count=0,
            required_missing_count=0,
            required_coverage=0.0,
            provisional_candidate_count=2,
            provisional_labels_sample="Demand Response, Energy level Information",
        )
    )

    assert shadow["verdict"] == "REVIEW"
    assert shadow["known_risk_labels"] == ["Demand Response", "Energy level Information"]
    assert shadow["reason"] == "coverage_not_ready:ready; provisional_risk_count=2"


def test_balanced_shadow_verdict_detects_known_family_care_risks():
    shadow = calculate_balanced_shadow_verdict(
        _base_report(
            coverage_denominator_count=25,
            coverage_matched_count=23,
            coverage_missing_count=2,
            coverage_percent=92.0,
            coverage_missing_labels_sample="EventsButton, LocationButton",
        )
    )

    assert shadow["verdict"] == "REVIEW"
    assert shadow["known_risk_labels"] == ["EventsButton", "LocationButton"]
    assert shadow["traversal_gap_count"] == 2


def test_add_shadow_verdict_fields_adds_json_and_csv_fields():
    report = add_shadow_verdict_fields(_base_report())

    assert report["shadow_verdict_v4"]["verdict"] == "PASS"
    assert report["shadow_policy_name"] == "balanced_v1"
    assert report["shadow_verdict_v4_value"] == "PASS"
    assert report["shadow_required_coverage"] == 100.0
    assert report["shadow_required_missing_count"] == 0
    assert report["shadow_traversal_gap_count"] == 0
    assert report["shadow_taxonomy_gap_count"] == 0
    assert report["shadow_known_risks"] == ""
