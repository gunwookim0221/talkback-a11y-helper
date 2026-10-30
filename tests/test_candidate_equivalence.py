from __future__ import annotations

import json
from pathlib import Path

import pytest

from talkback_lib.candidate_equivalence import (
    compare_candidate_responses,
    run_candidate_equivalence,
)


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "app/src/test/resources/candidate_equivalence/inputs.json"
PAIRS = ROOT / "app/src/test/resources/candidate_equivalence"


def _pair_paths() -> list[Path]:
    return sorted(PAIRS.glob("pairs_api*.json"))


def test_generated_pairs_cover_expected_fixed_inputs_and_home_monitor():
    pair_paths = _pair_paths()
    if not pair_paths:
        pytest.skip("Kotlin C4 pair artifacts have not been generated yet")

    result = run_candidate_equivalence(INPUTS, pair_paths)

    assert result["fixture_count"] == 20
    assert result["paired_fixture_count"] == 20
    assert result["extra_pair_ids"] == []
    assert result["home_monitor_pair_present"] is True
    assert result["home_monitor_equivalence_pass"] is True
    assert result["incompatible_count"] == 0
    assert result["noncomparable_count"] == 0
    assert result["traversal_impacting_difference_count"] == 0
    assert result["root_binding_all_pass"] is True
    assert result["schema_versions_all_pass"] is True
    assert result["no_legacy_rescue"] is True
    assert result["no_raw_flattening_fallback"] is True
    assert result["passed"] is True


def test_pair_harness_rejects_same_id_with_different_fixture_digest(tmp_path):
    fixture = json.loads(INPUTS.read_text(encoding="utf-8"))["fixtures"][0]
    assert fixture["fixture_id"] == "simple_button_api27_null_focusable"

    # A digest mismatch is a provenance failure, even if candidate JSON happens to match.
    pair_path = next((path for path in _pair_paths() if "api27" in path.name), None)
    if pair_path is None:
        pytest.skip("Kotlin API 27 C4 pair artifact has not been generated yet")
    body = json.loads(pair_path.read_text(encoding="utf-8"))
    body["pairs"][0]["input_sha256"] = "0" * 64
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(body), encoding="utf-8")

    result = run_candidate_equivalence(INPUTS, [broken, *[p for p in _pair_paths() if p != pair_path]])
    first = next(row for row in result["results"] if row["fixture_id"] == fixture["fixture_id"])
    assert first["verdict"] == "NONCOMPARABLE"
    assert first["root_binding_valid"] is True


def test_pair_harness_rejects_missing_capture_transport_metadata(tmp_path):
    pair_path = next((path for path in _pair_paths() if "api27" in path.name), None)
    api34 = next((path for path in _pair_paths() if "api34" in path.name), None)
    if pair_path is None or api34 is None:
        pytest.skip("Kotlin C4 pair artifacts have not been generated yet")
    body = json.loads(pair_path.read_text(encoding="utf-8"))
    fixture_id = body["pairs"][0]["fixture_id"]
    del body["pairs"][0]["capture_transport_metadata"]
    broken = tmp_path / "missing_capture_transport.json"
    broken.write_text(json.dumps(body), encoding="utf-8")

    result = run_candidate_equivalence(INPUTS, [broken, api34])
    row = next(row for row in result["results"] if row["fixture_id"] == fixture_id)
    assert row["verdict"] == "NONCOMPARABLE"
    assert row["root_binding_valid"] is False
    assert row["decode_error"] == "C4_PAIR_CAPTURE_TRANSPORT_METADATA_MISSING"


def test_pair_harness_rejects_raw_scroll_metadata_that_differs_from_fixed_input(tmp_path):
    pair_path = next((path for path in _pair_paths() if "api34" in path.name), None)
    if pair_path is None:
        pytest.skip("Kotlin API 34 C4 pair artifact has not been generated yet")
    body = json.loads(pair_path.read_text(encoding="utf-8"))
    pair = next(row for row in body["pairs"] if row["fixture_id"] == "scrollable_container_metadata")
    scroll_node = pair["v2_payload"]["windows"][0]["root"]["children"][0]
    scroll_node["scrollable"] = False
    scroll_node["isScrollable"] = False
    scroll_node["actions"] = []
    broken = tmp_path / "broken_raw_input.json"
    broken.write_text(json.dumps(body), encoding="utf-8")

    api27 = next(path for path in _pair_paths() if "api27" in path.name)
    result = run_candidate_equivalence(INPUTS, [api27, broken])
    row = next(row for row in result["results"] if row["fixture_id"] == "scrollable_container_metadata")
    assert row["verdict"] == "NONCOMPARABLE"
    assert row["raw_input_match"] is False
    assert result["raw_input_all_pass"] is False
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("legacy", "candidate", "expected_class"),
    [
        (
            {"algorithmVersion": "2.76.3", "canScrollDown": False, "nodes": []},
            {"algorithmVersion": "2.76.3", "canScrollDown": False, "nodes": [{"text": "New"}]},
            "CANDIDATE_MEMBERSHIP",
        ),
        (
            {"algorithmVersion": "2.76.3", "canScrollDown": False, "nodes": [{"text": "Old"}]},
            {"algorithmVersion": "2.76.3", "canScrollDown": False, "nodes": [{"text": "New"}]},
            "LABEL",
        ),
        (
            {"algorithmVersion": "2.76.3", "canScrollDown": False, "nodes": []},
            {"algorithmVersion": "2.76.3", "canScrollDown": True, "nodes": []},
            "SCROLL_METADATA",
        ),
    ],
)
def test_difference_classifier_marks_semantic_differences_as_traversal_impacting(
    legacy, candidate, expected_class
):
    differences = compare_candidate_responses(legacy, candidate)
    assert differences
    assert differences[0].difference_class == expected_class
    assert differences[0].traversal_impacting is True
