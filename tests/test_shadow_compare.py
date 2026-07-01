from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tb_runner.shadow_compare import (
    ALLOWED_COMPARISON_RESULTS,
    SHADOW_ARTIFACT_VERSION,
    SHADOW_COMPARISON_SCHEMA_VERSION,
    SHADOW_REPORT_SCHEMA_VERSION,
    build_shadow_report,
    calculate_shadow_metrics,
    compare_shadow_candidate,
    render_shadow_report_markdown,
    run_shadow_compare_if_enabled,
    write_shadow_markdown_artifact,
    write_shadow_report_artifact,
)
from tb_runner.v10_preparation import V10VersionSchema

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests/fixtures/v10/shadow/shadow_compare_cases.json"


def _clock():
    return datetime(2026, 7, 1, 4, 0, 0, tzinfo=timezone.utc)


def _legacy(
    scenario: str = "device_motion_sensor_plugin",
    *,
    inventory_id: str = "inventory-test",
    runtime_card_id: str = "card-test",
    decision: str = "resolved",
    fallback_used: bool = False,
) -> dict:
    return {
        "inventory_id": inventory_id,
        "runtime_card_id": runtime_card_id,
        "display_label": "Motion Sensor",
        "stable_label": "Motion sensor",
        "run_id": "run-001",
        "device_name": "QA Device",
        "legacy_scenario": scenario,
        "decision": decision,
        "fallback_used": fallback_used,
    }


def _candidate(
    scenario: str = "device_motion_sensor_plugin",
    *,
    inventory_id: str = "inventory-test",
    runtime_card_id: str = "card-test",
    eligibility: str = "eligible",
) -> dict:
    return {
        "inventory_id": inventory_id,
        "runtime_card_id": runtime_card_id,
        "display_label": "Motion Sensor",
        "stable_label": "Motion sensor",
        "run_id": "run-001",
        "device_name": "QA Device",
        "scenario_candidate": scenario,
        "eligibility": eligibility,
        "confidence": 96,
        "mapping_revision": 3,
        "policy_version": "policy-test",
        "registry_version": "registry-test",
        "traversal_allowed": False,
        "routing_performed": False,
    }


def test_match_record_preserves_authoritative_legacy_and_versions():
    record = compare_shadow_candidate(_legacy(), _candidate(), clock=_clock)

    assert record["schema_version"] == SHADOW_COMPARISON_SCHEMA_VERSION
    assert record["artifact_version"] == SHADOW_ARTIFACT_VERSION
    assert record["comparison_result"] == "MATCH"
    assert record["comparison_reason"] == "scenario_exact_match"
    assert record["legacy_authoritative"] is True
    assert record["promotion_eligible"] is True
    assert record["v10_routing_performed"] is False
    assert record["v10_traversal_allowed"] is False
    assert record["mapping_revision"] == 3
    assert record["policy_version"] == "policy-test"
    assert record["registry_version"] == "registry-test"


def test_mismatch_is_reported_without_changing_legacy():
    record = compare_shadow_candidate(
        _legacy("device_door_lock_plugin"),
        _candidate("device_motion_sensor_plugin"),
        clock=_clock,
    )

    assert record["comparison_result"] == "MISMATCH"
    assert record["legacy_scenario"] == "device_door_lock_plugin"
    assert record["shadow_candidate"] == "device_motion_sensor_plugin"
    assert record["promotion_eligible"] is False
    assert record["legacy_authoritative"] is True


def test_unknown_ambiguous_and_failed_are_fail_closed():
    cases = (
        (_legacy(), _candidate("", eligibility="unknown"), "UNKNOWN"),
        (_legacy(), _candidate("", eligibility="ambiguous"), "AMBIGUOUS"),
        (_legacy(), _candidate("", eligibility="failed"), "FAILED"),
        (_legacy(decision="ambiguous"), _candidate(), "AMBIGUOUS"),
        (_legacy(decision="failed"), _candidate(), "FAILED"),
    )

    for legacy, candidate, expected in cases:
        record = compare_shadow_candidate(legacy, candidate, clock=_clock)
        assert record["comparison_result"] == expected
        assert record["comparison_result"] in ALLOWED_COMPARISON_RESULTS
        assert record["promotion_eligible"] is False
        assert record["v10_traversal_allowed"] is False


def test_different_inventory_or_runtime_card_identity_fails_comparison():
    inventory_mismatch = compare_shadow_candidate(
        _legacy(inventory_id="inventory-a"),
        _candidate(inventory_id="inventory-b"),
        clock=_clock,
    )
    card_mismatch = compare_shadow_candidate(
        _legacy(runtime_card_id="card-a"),
        _candidate(runtime_card_id="card-b"),
        clock=_clock,
    )

    assert inventory_mismatch["comparison_result"] == "FAILED"
    assert card_mismatch["comparison_result"] == "FAILED"
    assert inventory_mismatch["comparison_reason"] == "comparison_identity_mismatch"


def test_shadow_only_candidate_can_compare_but_is_not_promotion_eligible():
    record = compare_shadow_candidate(
        _legacy(),
        _candidate(eligibility="shadow_only"),
        clock=_clock,
    )

    assert record["comparison_result"] == "MATCH"
    assert record["promotion_eligible"] is False


def test_metrics_use_comparable_match_rate_and_include_fail_closed_counts():
    records = [
        compare_shadow_candidate(_legacy(), _candidate(), clock=_clock),
        compare_shadow_candidate(
            _legacy("device_tv_plugin"),
            _candidate("device_audio_plugin"),
            clock=_clock,
        ),
        compare_shadow_candidate(
            _legacy(fallback_used=True),
            _candidate("", eligibility="unknown"),
            clock=_clock,
        ),
        compare_shadow_candidate(
            _legacy(),
            _candidate("", eligibility="ambiguous"),
            clock=_clock,
        ),
        compare_shadow_candidate(
            _legacy(),
            _candidate("", eligibility="failed"),
            clock=_clock,
        ),
    ]
    metrics = calculate_shadow_metrics(records, eligible_inventory_count=10)

    assert metrics == {
        "attempt_count": 5,
        "match_count": 1,
        "mismatch_count": 1,
        "unknown_count": 1,
        "ambiguous_count": 1,
        "failed_count": 1,
        "match_rate": 0.5,
        "shadow_coverage": 0.4,
        "fallback_count": 1,
        "fallback_rate": 0.2,
        "promotion_eligible_count": 1,
    }


def test_report_and_artifact_are_separate_from_legacy_outputs(tmp_path):
    versions = V10VersionSchema(shadow_validation_version="shadow-test-v2")
    record = compare_shadow_candidate(
        _legacy(),
        _candidate(),
        versions=versions,
        clock=_clock,
    )
    report = build_shadow_report(
        [record],
        versions=versions,
        clock=_clock,
    )
    path = write_shadow_report_artifact(report, artifact_dir=tmp_path / "shadow")
    markdown_path = write_shadow_markdown_artifact(report, artifact_dir=tmp_path / "shadow")
    saved = json.loads(path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    assert report["schema_version"] == SHADOW_REPORT_SCHEMA_VERSION
    assert report["mode"] == "comparison_only"
    assert report["shadow_validation_version"] == "shadow-test-v2"
    assert report["v10_routing_performed"] is False
    assert report["v10_traversal_allowed"] is False
    assert path.parent.name == "shadow"
    assert saved == report
    assert markdown_path.parent == path.parent
    assert "# V10 Shadow Validation Report" in markdown
    assert "## Summary" in markdown


def test_markdown_summary_counts_match_json_metrics():
    records = [
        compare_shadow_candidate(_legacy(), _candidate(), clock=_clock),
        compare_shadow_candidate(
            _legacy("device_tv_plugin"),
            _candidate("device_audio_plugin"),
            clock=_clock,
        ),
        compare_shadow_candidate(
            _legacy(),
            _candidate("", eligibility="unknown"),
            clock=_clock,
        ),
    ]
    report = build_shadow_report(records, clock=_clock)
    markdown = render_shadow_report_markdown(report)

    assert f"- total comparisons: `{report['metrics']['attempt_count']}`" in markdown
    assert f"- MATCH count: `{report['metrics']['match_count']}`" in markdown
    assert f"- MISMATCH count: `{report['metrics']['mismatch_count']}`" in markdown
    assert f"- UNKNOWN count: `{report['metrics']['unknown_count']}`" in markdown
    assert f"- match rate: `{report['metrics']['match_rate'] * 100:.2f}%`" in markdown


def test_markdown_includes_blocking_and_review_sections():
    records = [
        compare_shadow_candidate(
            _legacy("device_door_lock_plugin"),
            _candidate("device_motion_sensor_plugin"),
            clock=_clock,
        ),
        compare_shadow_candidate(
            _legacy(),
            _candidate("", eligibility="unknown"),
            clock=_clock,
        ),
    ]
    report = build_shadow_report(records, clock=_clock)
    markdown = render_shadow_report_markdown(report)

    assert "## Blocking / Needs Review" in markdown
    assert "scenario_conflict" in markdown
    assert "shadow_candidate_unknown" in markdown
    assert "| Motion Sensor | MISMATCH |" in markdown
    assert "| Motion Sensor | UNKNOWN |" in markdown


def test_feature_flag_off_performs_no_comparison_or_artifact(tmp_path):
    output = run_shadow_compare_if_enabled(
        {"feature_flags": {"shadow_validation_enabled": False}},
        [{"legacy": _legacy(), "shadow_candidate": _candidate()}],
        artifact_dir=tmp_path,
        clock=_clock,
    )

    assert output == {
        "status": "disabled",
        "result": None,
        "artifact_path": "",
    }
    assert list(tmp_path.iterdir()) == []


def test_feature_flag_on_writes_shadow_only_report(tmp_path):
    output = run_shadow_compare_if_enabled(
        {
            "feature_flags": {"shadow_validation_enabled": True},
            "versions": V10VersionSchema().as_dict(),
        },
        [{"legacy": _legacy(), "shadow_candidate": _candidate()}],
        artifact_dir=tmp_path,
        clock=_clock,
    )

    assert output["status"] == "completed"
    assert output["result"]["metrics"]["match_count"] == 1
    assert output["result"]["legacy_authoritative"] is True
    assert output["result"]["v10_routing_performed"] is False
    assert Path(output["artifact_path"]).is_file()
    assert Path(output["markdown_artifact_path"]).is_file()


def test_fixture_replay():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in payload["cases"]:
        record = compare_shadow_candidate(
            _legacy(case["legacy_scenario"], decision=case["legacy_decision"]),
            _candidate(
                case["shadow_scenario"],
                eligibility=case["shadow_eligibility"],
            ),
            clock=_clock,
        )
        assert record["comparison_result"] == case["expected_result"]
