from __future__ import annotations

import copy
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tb_runner.comparison_input import (
    adapt_approved_baseline,
    candidate_input_from_baseline,
)
from tb_runner.comparison_replay import (
    replay_selected_inputs,
    run_comparison_replay,
)
from tb_runner.comparison_report import (
    canonical_report_json,
    render_markdown_report,
    write_comparison_report,
)
from tb_runner.observation_bundle import (
    ObservationBundleError,
    load_bundle_index,
    load_observation_bundle,
)
from tb_runner.verdict_engine import (
    finalize_comparison_result,
    reduce_verdict,
)


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "baselines" / "com.samsung.android.oneconnect"
ENGLISH_ID = "baseline_8f00aed49e61a07b_r0001"
KOREAN_ID = "baseline_1f697e9b60c655df_r0001"


@pytest.fixture(scope="module")
def english_baseline():
    return adapt_approved_baseline(APP_ROOT / ENGLISH_ID)


@pytest.fixture(scope="module")
def korean_baseline():
    return adapt_approved_baseline(APP_ROOT / KOREAN_ID)


@pytest.fixture(scope="module")
def english_replay(english_baseline):
    return replay_selected_inputs(
        english_baseline,
        candidate_input_from_baseline(english_baseline),
        repository_root=ROOT,
    )


def _mutable_result(english_replay):
    value = copy.deepcopy(english_replay.result)
    value.pop("verdict", None)
    return value


def test_english_self_compare_acceptance(english_replay):
    assert english_replay.result["verdict"]["overall"] == "PASS_WITH_LIMITATIONS"
    assert english_replay.result["node_match_summary"]["node_delta_counts"] == {
        "SAME_NODE_UNCHANGED": 947
    }


def test_korean_self_compare_acceptance(korean_baseline):
    replay = replay_selected_inputs(
        korean_baseline,
        candidate_input_from_baseline(korean_baseline),
        repository_root=ROOT,
    )
    assert replay.result["verdict"]["overall"] == "PASS_WITH_LIMITATIONS"
    assert replay.result["node_match_summary"]["node_delta_counts"] == {
        "SAME_NODE_UNCHANGED": 879
    }


def test_synthetic_app_upgrade_requires_limitation_scope_review(english_baseline):
    candidate = candidate_input_from_baseline(english_baseline)
    environment = copy.deepcopy(candidate.environment)
    environment["app_version_name"] = "1.8.48"
    environment["app_version_code"] = 184800000
    replay = replay_selected_inputs(
        english_baseline,
        replace(candidate, environment=environment),
        repository_root=ROOT,
    )
    assert replay.result["compatibility_grade"] == "COMPATIBLE_PREDECESSOR"
    assert replay.result["verdict"]["overall"] == "REVIEW_REQUIRED"
    assert (
        replay.result["limitation_binding_deltas"]["status_counts"][
            "LIMITATION_SCOPE_EXPANDED"
        ]
        == 5
    )


def test_synthetic_ui_addition_requires_review(english_replay):
    result = _mutable_result(english_replay)
    result["accessibility_failure_summary"]["classification_counts"] = {
        "NO_ACCESSIBILITY_FAILURE": 947,
        "STRUCTURAL_CHANGE": 1,
    }
    result["node_match_summary"]["node_delta_counts"] = {
        "SAME_NODE_UNCHANGED": 947,
        "ADDED_NODE": 1,
    }
    assert reduce_verdict(result)["overall"] == "REVIEW_REQUIRED"


def test_known_limitation_unchanged_is_pass_with_limitations(english_replay):
    assert reduce_verdict(english_replay.result)["overall"] == (
        "PASS_WITH_LIMITATIONS"
    )


def test_known_limitation_resolved_can_pass(english_replay):
    result = _mutable_result(english_replay)
    result["limitation_binding_deltas"] = {
        "status": "AVAILABLE",
        "bindings": [
            {
                "issue_id": "ISSUE-1",
                "status": "KNOWN_LIMITATION_RESOLVED",
            }
        ],
        "status_counts": {"KNOWN_LIMITATION_RESOLVED": 1},
    }
    result["accessibility_failure_summary"]["classification_counts"] = {
        "NO_ACCESSIBILITY_FAILURE": 947,
        "RESOLVED_FAILURE": 1,
    }
    result["limitation_summary_delta"]["status"] = "STRUCTURAL_CHANGE"
    assert reduce_verdict(result)["overall"] == "PASS"


def test_new_empty_visible_fails(english_replay):
    result = _mutable_result(english_replay)
    result["accessibility_failure_summary"]["classification_counts"] = {
        "NO_ACCESSIBILITY_FAILURE": 947,
        "NEW_ACCESSIBILITY_FAILURE": 1,
    }
    assert reduce_verdict(result)["overall"] == "FAIL"


def test_data_unavailable_requires_review(english_replay):
    result = _mutable_result(english_replay)
    result["observation_availability"] = {
        "status": "DATA_UNAVAILABLE",
        "reason": "OBSERVATION_UNAVAILABLE",
    }
    assert reduce_verdict(result)["overall"] == "REVIEW_REQUIRED"


def test_explicit_compatibility_review_required(english_replay):
    result = _mutable_result(english_replay)
    result["compatibility_grade"] = "REVIEW_REQUIRED"
    assert reduce_verdict(result)["overall"] == "REVIEW_REQUIRED"


def test_incomparable_precedes_fail(english_replay):
    result = _mutable_result(english_replay)
    result["compatibility_grade"] = "INCOMPARABLE"
    result["accessibility_failure_summary"]["classification_counts"] = {
        "NEW_ACCESSIBILITY_FAILURE": 3
    }
    assert reduce_verdict(result)["overall"] == "INCOMPARABLE"


def test_accessibility_aggregate_regression_fails(english_replay):
    result = _mutable_result(english_replay)
    result["coverage_aggregate_delta"]["status"] = "REGRESSED"
    assert reduce_verdict(result)["overall"] == "FAIL"


def test_profiler_regression_does_not_fail_accessibility(english_replay):
    result = _mutable_result(english_replay)
    result["profiler_aggregate_delta"]["status"] = "REGRESSED"
    verdict = reduce_verdict(result)
    assert verdict["overall"] == "PASS_WITH_LIMITATIONS"
    assert verdict["performance_affects_accessibility_verdict"] is False


def test_report_contains_required_sections(english_replay):
    markdown = render_markdown_report(english_replay.result)
    for title in (
        "Environment",
        "Version",
        "Compatibility",
        "Coverage",
        "Identity",
        "Traversal",
        "Recovery",
        "Profiler",
        "Known Limitation",
        "New Failure",
        "Resolved Failure",
        "Review Items",
        "Recommendation",
    ):
        assert f"## {title}" in markdown


def test_replay_is_byte_deterministic(english_baseline):
    candidate = candidate_input_from_baseline(english_baseline)
    first = replay_selected_inputs(
        english_baseline, candidate, repository_root=ROOT
    )
    second = replay_selected_inputs(
        english_baseline, candidate, repository_root=ROOT
    )
    assert first.result["comparison_id"] == second.result["comparison_id"]
    assert first.result["verdict"] == second.result["verdict"]
    assert first.canonical_json == second.canonical_json
    assert first.markdown == second.markdown


def test_canonical_report_excludes_wall_clock(english_replay):
    changed = dict(english_replay.result)
    changed["generated_at"] = "2099-01-01T00:00:00Z"
    assert canonical_report_json(changed) == english_replay.canonical_json


def test_report_writer_is_immutable_and_idempotent(english_replay, tmp_path):
    first = write_comparison_report(english_replay.result, tmp_path)
    second = write_comparison_report(english_replay.result, tmp_path)
    assert first == second
    payload = json.loads(first.comparison_json.read_text(encoding="utf-8"))
    assert payload["comparison"]["verdict"]["overall"] == "PASS_WITH_LIMITATIONS"


def test_portable_bundle_replay_without_source_run(
    english_baseline, tmp_path
):
    shutil.copytree(ROOT / "observation_bundles", tmp_path / "observation_bundles")
    replay = replay_selected_inputs(
        english_baseline,
        candidate_input_from_baseline(english_baseline),
        repository_root=tmp_path,
    )
    availability = replay.result["observation_availability"]
    assert availability["status"] == "COMPLETE"
    assert availability["baseline"]["source_quality"] == (
        "PORTABLE_CANONICAL_BUNDLE"
    )
    assert replay.result["verdict"]["overall"] == "PASS_WITH_LIMITATIONS"


def test_bundle_index_and_documents_verify():
    index = load_bundle_index(ROOT / "observation_bundles" / "index.json")
    assert len(index["entries"]) == 2
    for entry in index["entries"]:
        bundle = load_observation_bundle(
            ROOT / "observation_bundles" / entry["relative_path"],
            expected_document_digest=entry["document_digest"],
        )
        assert len(bundle.observations) == entry["observation_count"]


def test_corrupt_bundle_is_rejected(tmp_path):
    source = ROOT / "observation_bundles" / (
        f"{ENGLISH_ID}.observations.json"
    )
    target = tmp_path / source.name
    target.write_bytes(source.read_bytes() + b"x")
    with pytest.raises(ObservationBundleError):
        load_observation_bundle(target)


def test_finalization_changes_policy_identity_deterministically(english_replay):
    result = _mutable_result(english_replay)
    first = finalize_comparison_result(result)
    second = finalize_comparison_result(result)
    assert first["comparison_id"] == second["comparison_id"]
    assert first["observation_comparison_id"] == result["comparison_id"]
    assert first["comparison_schema"] == "talkback-final-comparison-result-v1"


def test_operational_replay_includes_baseline_selection(english_baseline):
    replay = run_comparison_replay(
        candidate_input_from_baseline(english_baseline),
        ROOT / "baselines",
    )
    assert replay.result["baseline_reference"]["source_id"] == ENGLISH_ID
    assert replay.result["verdict"]["overall"] == "PASS_WITH_LIMITATIONS"
