from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from tb_runner.aggregate_comparator import compare_aggregates
from tb_runner.app_version import compare_app_versions, parse_app_version
from tb_runner.baseline_candidate_builder import build_baseline_candidate
from tb_runner.baseline_selector import (
    BaselineDiscoveryRecord,
    discover_baselines_read_only,
    select_baseline,
    select_discovered_baselines,
)
from tb_runner.comparison_compatibility import (
    assess_compatibility,
    build_compatibility_key,
)
from tb_runner.comparison_input import (
    adapt_approved_baseline,
    adapt_candidate,
    candidate_input_from_baseline,
)
from tb_runner.comparator_core import (
    compare_selected_inputs,
    run_comparator_core,
)
from tb_runner.comparator_schema import (
    CompatibilityGrade,
    ComparatorContractError,
    VersionRelation,
)
from tests.test_baseline_candidate_builder import _create_run


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINES = REPO_ROOT / "baselines"
APP_ROOT = BASELINES / "com.samsung.android.oneconnect"
ENGLISH_ID = "baseline_8f00aed49e61a07b_r0001"
KOREAN_ID = "baseline_1f697e9b60c655df_r0001"


@pytest.fixture(scope="module")
def english_baseline():
    return adapt_approved_baseline(APP_ROOT / ENGLISH_ID)


@pytest.fixture(scope="module")
def korean_baseline():
    return adapt_approved_baseline(APP_ROOT / KOREAN_ID)


def _candidate(baseline, *, version=None, code=None, source_id="candidate_test"):
    candidate = candidate_input_from_baseline(baseline, source_id=source_id)
    environment = copy.deepcopy(candidate.environment)
    if version is not None:
        environment["app_version_name"] = version
    if code is not None or version is not None:
        environment["app_version_code"] = code
    return replace(candidate, environment=environment)


def _baseline_version(baseline, version, code, source_id, *, state="APPROVED"):
    environment = copy.deepcopy(baseline.environment)
    environment["app_version_name"] = version
    environment["app_version_code"] = code
    provenance = copy.deepcopy(baseline.provenance)
    provenance.update(
        {
            "repository_state": state,
            "revision": 1,
            "approved_at": "2026-07-17T00:00:00Z",
        }
    )
    return replace(
        baseline,
        source_id=source_id,
        environment=environment,
        provenance=provenance,
    )


def _record(source, state):
    return BaselineDiscoveryRecord(
        Path(source.source_id),
        source.source_id,
        state,
        {},
        source,
        (),
    )


def _mutate_aggregate(candidate, name, callback):
    aggregates = copy.deepcopy(candidate.aggregates)
    callback(aggregates[name])
    return replace(candidate, aggregates=aggregates)


def _file_snapshot(root: Path):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_english_baseline_self_compare_is_exact(english_baseline):
    candidate = candidate_input_from_baseline(english_baseline)
    result = compare_selected_inputs(
        english_baseline,
        candidate,
        generated_at="2026-07-17T00:00:00Z",
    )

    assert result["compatibility_grade"] == "EXACT_MATCH"
    assert result["coverage_aggregate_delta"]["status"] == "UNCHANGED"
    assert result["limitation_summary_delta"]["status"] == "UNCHANGED"


def test_korean_baseline_self_compare_is_exact(korean_baseline):
    candidate = candidate_input_from_baseline(korean_baseline)
    result = compare_selected_inputs(korean_baseline, candidate)

    assert result["compatibility_grade"] == "EXACT_MATCH"
    assert result["candidate_reference"]["source_id"].startswith("candidate_from_")
    assert result["identity_aggregate_delta"]["status"] == "UNCHANGED"


def test_patch_upgrade_is_compatible_predecessor(english_baseline):
    candidate = _candidate(english_baseline, version="1.8.48", code=184800000)
    assessment = assess_compatibility(english_baseline, candidate)

    assert assessment.grade == CompatibilityGrade.COMPATIBLE_PREDECESSOR
    assert assessment.version_relation == VersionRelation.UPGRADE
    assert (
        build_compatibility_key(english_baseline).digest
        == build_compatibility_key(candidate).digest
    )


def test_locale_mismatch_is_incomparable(english_baseline):
    candidate = _candidate(english_baseline)
    environment = copy.deepcopy(candidate.environment)
    environment["locale"] = "ko-KR"
    assessment = assess_compatibility(
        english_baseline, replace(candidate, environment=environment)
    )

    assert assessment.grade == CompatibilityGrade.INCOMPARABLE
    assert assessment.reasons[0]["code"] == "LOCALE_MISMATCH"


def test_package_mismatch_is_incomparable(english_baseline):
    candidate = _candidate(english_baseline)
    environment = copy.deepcopy(candidate.environment)
    environment["app_package"] = "example.other"
    assessment = assess_compatibility(
        english_baseline, replace(candidate, environment=environment)
    )

    assert assessment.grade == CompatibilityGrade.INCOMPARABLE
    assert assessment.reasons[0]["code"] == "APP_PACKAGE_MISMATCH"


def test_newer_candidate_selects_active_predecessor(english_baseline):
    candidate = _candidate(english_baseline, version="1.8.48", code=184800000)
    selection = select_baseline(candidate, BASELINES)

    assert selection.selected is not None
    assert selection.selected.source_id == ENGLISH_ID
    assert selection.assessment.grade == CompatibilityGrade.COMPATIBLE_PREDECESSOR
    assert selection.assessment.version_relation == VersionRelation.UPGRADE
    assert any(
        item["baseline_id"] == KOREAN_ID
        and item["reasons"][0]["code"] == "LOCALE_MISMATCH"
        for item in selection.rejected
    )


def test_active_newer_baseline_falls_back_to_historical_predecessor(
    english_baseline,
):
    active = _baseline_version(
        english_baseline,
        "1.8.50",
        185000000,
        "baseline_active_newer",
    )
    historical = _baseline_version(
        english_baseline,
        "1.8.47.24",
        184724010,
        "baseline_historical",
        state="SUPERSEDED",
    )
    candidate = _candidate(
        english_baseline, version="1.8.49", code=184900000
    )
    selection = select_discovered_baselines(
        candidate,
        (_record(active, "APPROVED"), _record(historical, "SUPERSEDED")),
    )

    assert selection.selected is not None
    assert selection.selected.source_id == "baseline_historical"
    assert selection.assessment.version_relation == VersionRelation.UPGRADE
    assert any(
        item["baseline_id"] == "baseline_active_newer"
        and item["version_relation"] == "DOWNGRADE"
        for item in selection.rejected
    )


def test_downgrade_is_review_required(english_baseline):
    baseline = _baseline_version(
        english_baseline, "1.8.48", 184800000, "baseline_newer"
    )
    candidate = _candidate(
        english_baseline, version="1.8.47.24", code=184724010
    )
    assessment = assess_compatibility(baseline, candidate)

    assert assessment.grade == CompatibilityGrade.REVIEW_REQUIRED
    assert assessment.version_relation == VersionRelation.DOWNGRADE


def test_unknown_version_ordering_is_review_required(english_baseline):
    baseline = _baseline_version(
        english_baseline, "release-alpha", None, "baseline_opaque"
    )
    candidate = _candidate(
        english_baseline, version="release-canary", code=None
    )
    assessment = assess_compatibility(baseline, candidate)

    assert assessment.grade == CompatibilityGrade.REVIEW_REQUIRED
    assert assessment.version_relation == VersionRelation.UNKNOWN_ORDER
    assert any(
        item["code"] == "UNKNOWN_VERSION_ORDERING"
        for item in assessment.review_items
    )


def test_scenario_added_is_structural_change(english_baseline):
    candidate = _candidate(english_baseline)
    scenario = copy.deepcopy(candidate.scenario)
    scenario["selected_ids"].append("new_scenario")
    scenario["selected_count"] += 1
    result = compare_selected_inputs(
        english_baseline, replace(candidate, scenario=scenario)
    )

    assert result["scenario_delta"]["added_scenarios"] == ["new_scenario"]
    assert result["scenario_delta"]["status"] == "STRUCTURAL_CHANGE"


def test_scenario_removed_is_structural_change(english_baseline):
    candidate = _candidate(english_baseline)
    removed = candidate.scenario["selected_ids"][-1]
    scenario = copy.deepcopy(candidate.scenario)
    scenario["selected_ids"] = scenario["selected_ids"][:-1]
    scenario["selected_count"] -= 1
    result = compare_selected_inputs(
        english_baseline, replace(candidate, scenario=scenario)
    )

    assert result["scenario_delta"]["removed_scenarios"] == [removed]
    assert result["scenario_delta"]["status"] == "STRUCTURAL_CHANGE"


def test_scenario_order_only_change(english_baseline):
    candidate = _candidate(english_baseline)
    scenario = copy.deepcopy(candidate.scenario)
    scenario["selected_ids"] = list(reversed(scenario["selected_ids"]))
    result = compare_selected_inputs(
        english_baseline, replace(candidate, scenario=scenario)
    )

    assert result["scenario_delta"]["order_changed"] is True
    assert result["scenario_delta"]["order_only_change"] is True
    assert result["scenario_delta"]["added_scenarios"] == []
    assert result["scenario_delta"]["removed_scenarios"] == []


def test_coverage_denominator_increase_is_not_regressed(english_baseline):
    candidate = _candidate(english_baseline)

    def mutate(coverage):
        coverage["expected_count"] += 5
        coverage["unknown_count"] += 5
        coverage["scenarios"][0]["expected_count"] += 5
        coverage["scenarios"][0]["unknown_count"] += 5

    candidate = _mutate_aggregate(candidate, "coverage", mutate)
    delta = compare_aggregates(english_baseline, candidate)[
        "coverage_aggregate_delta"
    ]

    assert delta["denominator_changed"] is True
    assert delta["status"] in {"STRUCTURAL_CHANGE", "REVIEW_REQUIRED"}
    assert delta["status"] != "REGRESSED"


def test_coverage_covered_to_missed_aggregate_is_regressed(english_baseline):
    candidate = _candidate(english_baseline)

    def mutate(coverage):
        coverage["covered_count"] -= 1
        coverage["missed_count"] += 1
        coverage["scenarios"][0]["covered_count"] -= 1
        coverage["scenarios"][0]["missed_count"] += 1

    candidate = _mutate_aggregate(candidate, "coverage", mutate)
    delta = compare_aggregates(english_baseline, candidate)[
        "coverage_aggregate_delta"
    ]

    assert delta["status"] == "REGRESSED"
    assert delta["common_scenario_delta"]["covered"] == -1
    assert delta["common_scenario_delta"]["missed"] == 1


def test_identity_indeterminate_increase_is_regressed(english_baseline):
    candidate = _candidate(english_baseline)

    def mutate(identity):
        identity["verdicts"]["INDETERMINATE"] += 2
        identity["transaction_count"] += 2

    candidate = _mutate_aggregate(candidate, "identity", mutate)
    delta = compare_aggregates(english_baseline, candidate)[
        "identity_aggregate_delta"
    ]

    assert delta["status"] == "REGRESSED"
    assert delta["count_delta"]["indeterminate"] == 2


def test_reconciliation_failure_is_regressed(english_baseline):
    candidate = _candidate(english_baseline)

    def mutate(reconciliation):
        reconciliation["status"] = "FAIL"
        reconciliation["orphan_count"] = 1

    candidate = _mutate_aggregate(candidate, "reconciliation", mutate)
    delta = compare_aggregates(english_baseline, candidate)[
        "reconciliation_delta"
    ]

    assert delta["status"] == "REGRESSED"
    assert delta["candidate_status"] == "FAIL"


def test_profiler_runtime_regression_is_separate(english_baseline):
    candidate = _candidate(english_baseline)

    def mutate(profiler):
        profiler["scenarios"][0]["runtime_ms"] += 1000

    candidate = _mutate_aggregate(candidate, "profiler", mutate)
    delta = compare_aggregates(english_baseline, candidate)[
        "profiler_aggregate_delta"
    ]

    assert delta["status"] == "REGRESSED"
    assert delta["total_runtime_delta_ms"] == 1000
    assert delta["accessibility_verdict_effect"] == "NONE"


def test_optional_observation_missing_is_data_unavailable(english_baseline):
    candidate = _candidate(english_baseline)
    artifacts = copy.deepcopy(candidate.artifacts)
    for item in artifacts["optional_observations"].values():
        item["status"] = "DATA_UNAVAILABLE"
        item["reason"] = "OPTIONAL_ARTIFACT_UNAVAILABLE"
    result = compare_selected_inputs(
        english_baseline, replace(candidate, artifacts=artifacts)
    )

    assert result["data_availability"]["node_text_speech"]["status"] == (
        "DATA_UNAVAILABLE"
    )
    assert result["data_availability"]["optional_observations"]["candidate"][
        "evidence_ledger"
    ]["status"] == "DATA_UNAVAILABLE"


def test_multiple_baseline_tie_requires_review(english_baseline):
    first = _baseline_version(
        english_baseline, "1.8.47.24", 184724010, "baseline_tie_a"
    )
    second = replace(first, source_id="baseline_tie_b")
    candidate = _candidate(
        english_baseline, version="1.8.48", code=184800000
    )
    selection = select_discovered_baselines(
        candidate,
        (_record(first, "APPROVED"), _record(second, "APPROVED")),
    )

    assert selection.selected is None
    assert selection.tie is True
    assert selection.assessment.grade == CompatibilityGrade.REVIEW_REQUIRED


def test_comparison_id_excludes_generated_at(english_baseline):
    candidate = _candidate(english_baseline)
    first = compare_selected_inputs(
        english_baseline,
        candidate,
        generated_at="2026-07-17T00:00:00Z",
    )
    second = compare_selected_inputs(
        english_baseline,
        candidate,
        generated_at="2026-07-18T00:00:00Z",
    )

    assert first["comparison_id"] == second["comparison_id"]
    assert first["generated_at"] != second["generated_at"]


def test_comparator_is_read_only_for_real_repository(english_baseline):
    before = _file_snapshot(BASELINES)
    candidate = _candidate(
        english_baseline, version="1.8.48", code=184800000
    )
    result = run_comparator_core(
        candidate,
        BASELINES,
        generated_at="2026-07-17T00:00:00Z",
    )
    after = _file_snapshot(BASELINES)

    assert result["baseline_reference"]["source_id"] == ENGLISH_ID
    assert before == after


def test_unsupported_candidate_schema_returns_structured_error():
    result = run_comparator_core(
        {"candidate_schema": "unsupported-v99"},
        BASELINES,
        generated_at="2026-07-17T00:00:00Z",
    )

    assert result["compatibility_grade"] == "INCOMPARABLE"
    assert result["errors"][0]["code"] == "UNSUPPORTED_SCHEMA"


def test_corrupted_fingerprint_digest_is_rejected(tmp_path):
    run_root = _create_run(tmp_path)
    built = build_baseline_candidate(run_root, write=False)
    payload = built.candidate.to_dict()
    payload["environment_fingerprint"]["hash"] = "0" * 64

    with pytest.raises(ComparatorContractError) as raised:
        adapt_candidate(payload)

    assert raised.value.code == "CORRUPT_FINGERPRINT"


def test_corrupted_required_artifact_reference_is_rejected(tmp_path):
    run_root = _create_run(tmp_path)
    built = build_baseline_candidate(run_root, write=False)
    payload = built.candidate.to_dict()
    required = next(
        item
        for item in payload["artifact_manifest"]["artifacts"]
        if item["required"]
    )
    required["relative_reference"] = str(
        tmp_path / "absolute-path-is-not-canonical"
    )

    with pytest.raises(ComparatorContractError) as raised:
        adapt_candidate(payload)

    assert raised.value.code == "CORRUPT_REQUIRED_ARTIFACT_REFERENCE"


def test_version_parser_same_name_code_hotfix_and_unknown():
    baseline = parse_app_version("1.8.47.24", 184724010)
    hotfix = parse_app_version("1.8.47.24", 184724011)
    opaque = compare_app_versions(
        parse_app_version("release-alpha"),
        parse_app_version("release-beta"),
    )

    assert baseline.normalized_numeric_tuple == (1, 8, 47, 24)
    assert baseline.release_train == "1.8"
    assert compare_app_versions(baseline, hotfix).relation == VersionRelation.UPGRADE
    assert opaque.relation == VersionRelation.UNKNOWN_ORDER


def test_real_repository_discovery_validates_both_approved_packages():
    records, errors = discover_baselines_read_only(BASELINES)

    assert errors == ()
    assert {record.baseline_id for record in records} == {ENGLISH_ID, KOREAN_ID}
    assert all(record.state == "APPROVED" for record in records)
    assert all(record.input is not None and not record.errors for record in records)
