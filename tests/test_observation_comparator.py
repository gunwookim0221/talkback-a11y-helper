from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from tb_runner.comparison_input import (
    adapt_approved_baseline,
    candidate_input_from_baseline,
)
from tb_runner.coverage_transition_comparator import compare_coverage_transitions
from tb_runner.limitation_matcher import bind_limitations
from tb_runner.node_matcher import match_observations
from tb_runner.observation_adapter import load_observation_set
from tb_runner.observation_comparator import compare_observation_sets
from tb_runner.observation_normalizer import build_observation, normalize_text
from tb_runner.observation_schema import (
    OBSERVATION_SET_SCHEMA_VERSION,
    ObservationAvailability,
    ObservationSet,
)
from tb_runner.text_speech_comparator import classify_text_speech


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "baselines" / "com.samsung.android.oneconnect"
ENGLISH_ID = "baseline_8f00aed49e61a07b_r0001"
KOREAN_ID = "baseline_1f697e9b60c655df_r0001"


def _obs(
    *,
    scenario="scenario",
    step=1,
    transaction="tx-1",
    resource="id/control",
    class_name="android.widget.Button",
    bounds="[0,0,100,100]",
    text="Label",
    speech="Label",
    mismatch="",
    result="PASS",
    coverage="COVERED",
    parent="root",
    sibling="prev|next",
    locale="en-US",
    stop_reason="",
):
    return build_observation(
        {
            "scenario_id": scenario,
            "step_index": step,
            "transaction_id": transaction,
            "resource_id": resource,
            "class_name": class_name,
            "bounds": bounds,
            "visible_text": text,
            "talkback_speech": speech,
            "mismatch_type": mismatch,
            "raw_result": result,
            "coverage_status": coverage,
            "parent_signature": parent,
            "sibling_signature": sibling,
            "stop_reason": stop_reason,
            "xlsx_row_number": step + 1,
            "focusable": True,
        },
        locale=locale,
        provenance=({"artifact_digest": "a" * 64, "row_record_locator": f"row={step + 1}"},),
    )


def _set(items, *, kind, source_id, availability=ObservationAvailability.COMPLETE, locale="en-US"):
    values = tuple(items)
    digest = hashlib.sha256("|".join(item.observation_id for item in values).encode()).hexdigest() if values else None
    return ObservationSet(
        observation_set_schema=OBSERVATION_SET_SCHEMA_VERSION,
        source_kind=kind,
        source_id=source_id,
        locale=locale,
        app_package="com.samsung.android.oneconnect",
        app_version_name="1.8.47.24",
        app_version_code=184724010,
        availability=availability,
        source_quality="TEST",
        observations=values,
        artifacts=(),
        observation_identity_digest=digest,
    )


def _matched(left, right):
    return match_observations([left], [right])[0]


def test_01_exact_resource_id_match():
    match = _matched(_obs(), _obs())
    assert match["match_type"] == "TIER_1_STABLE_EXACT"
    assert match["confidence"] == "HIGH"


def test_02_duplicate_resource_id_structural_disambiguation():
    left = [_obs(step=1, transaction="a"), _obs(step=2, transaction="b")]
    right = [_obs(step=2, transaction="b"), _obs(step=1, transaction="a")]
    matches = match_observations(left, right)
    assert {item["node_delta"] for item in matches} <= {"SAME_NODE_UNCHANGED", "SAME_NODE_CHANGED_ORDER"}
    assert not any(item["ambiguity"] for item in matches)


def test_03_resource_id_changed_semantic_structure_same():
    match = _matched(_obs(resource="old"), _obs(resource="new"))
    assert match["match_type"] in {"TIER_2_SEMANTIC_STRUCTURE", "TIER_3_TRAVERSAL_NEIGHBORHOOD"}


def test_04_label_changed_speech_same():
    delta = classify_text_speech(_obs(text="Old"), _obs(text="New"))
    assert delta["classification"] == "TEXT_CHANGED_SPEECH_MATCHED"


def test_05_label_same_speech_changed():
    delta = classify_text_speech(_obs(speech="Old"), _obs(speech="New"))
    assert delta["classification"] == "TEXT_MATCHED_SPEECH_CHANGED"


def test_06_dynamic_percentage_only():
    delta = classify_text_speech(
        _obs(text="Battery 87%", speech="Battery 87%"),
        _obs(text="Battery 100%", speech="Battery 100%"),
    )
    assert delta["classification"] == "DYNAMIC_VALUE_ONLY"


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("Hello!", "Hello", "PUNCTUATION_ONLY"),
        ("Hello  world", "Hello world", "WHITESPACE_ONLY"),
    ],
)
def test_07_punctuation_and_whitespace_only(before, after, expected):
    assert classify_text_speech(_obs(text=before, speech=before), _obs(text=after, speech=after))["classification"] == expected


def test_08_speech_missing():
    assert classify_text_speech(_obs(), _obs(speech=""))["classification"] == "SPEECH_MISSING"


def test_09_new_empty_visible():
    candidate = _obs(text="", speech="", mismatch="EMPTY_VISIBLE", result="FAIL")
    assert classify_text_speech(_obs(), candidate)["classification"] == "NEW_EMPTY_VISIBLE"


def test_10_resolved_empty_visible():
    baseline = _obs(text="", speech="", mismatch="EMPTY_VISIBLE", result="FAIL")
    assert classify_text_speech(baseline, _obs())["classification"] == "RESOLVED_EMPTY_VISIBLE"


def _limitation(**overrides):
    value = {
        "issue_id": "ISSUE-1",
        "scenario_id": "scenario",
        "scenario_scope": ["scenario"],
        "resource_id": "id/control",
        "class": "android.widget.Button",
        "bounds": "[0,0,100,100]",
        "match_signature": {
            "resource_id": "id/control",
            "class": "android.widget.Button",
            "bounds": "[0,0,100,100]",
            "mismatch_type": "EMPTY_VISIBLE",
        },
        "environment_scope": {"locale": "en-US", "app_release_train": "1.8.47.24"},
        "review_status": "REVIEWED",
        "expires_at": "2099-01-01T00:00:00Z",
        "raw_fail_retained": True,
    }
    value.update(overrides)
    return value


def _failure(**kwargs):
    return _obs(text="", speech="", mismatch="EMPTY_VISIBLE", result="FAIL", **kwargs)


def test_11_known_limitation_unchanged():
    rows = bind_limitations([_limitation()], [_failure()], [_failure()], generated_at="2026-07-17T00:00:00Z")
    assert rows[0]["status"] == "KNOWN_LIMITATION_UNCHANGED"
    assert rows[0]["raw_fail_retained"] is True


def test_12_limitation_signature_drift():
    rows = bind_limitations([_limitation()], [_failure()], [_failure(bounds="[0,0,200,200]")])
    assert rows[0]["status"] == "KNOWN_LIMITATION_CHANGED"
    assert "BOUNDS_DRIFT" in rows[0]["review_reasons"]


def test_13_limitation_resolved():
    rows = bind_limitations([_limitation()], [_failure()], [])
    assert rows[0]["status"] == "KNOWN_LIMITATION_RESOLVED"


def test_14_limitation_scope_expanded():
    limitation = _limitation()
    candidate = _failure(scenario="other")
    rows = bind_limitations([limitation], [_failure()], [candidate])
    assert rows[-1]["status"] == "LIMITATION_SCOPE_EXPANDED"


def test_15_derivative_repeated_row():
    limitation = _limitation(derivation="DUPLICATE_DERIVED_FAILURE")
    rows = bind_limitations([limitation], [_failure()], [_failure()])
    assert rows[0]["status"] == "DERIVATIVE_DUPLICATE"


def test_16_added_node():
    assert match_observations([], [_obs()])[0]["node_delta"] == "ADDED_NODE"


def test_17_removed_node():
    assert match_observations([_obs()], [])[0]["node_delta"] == "REMOVED_NODE"


def test_18_traversal_order_changed():
    match = _matched(_obs(step=1, transaction=""), _obs(step=2, transaction=""))
    assert match["node_delta"] == "SAME_NODE_CHANGED_ORDER"


def test_19_ambiguous_match_is_not_forced():
    baseline = _obs(transaction="")
    candidates = [_obs(step=2, transaction=""), _obs(step=3, transaction="")]
    match = match_observations([baseline], candidates)[0]
    assert match["node_delta"] == "AMBIGUOUS_MATCH"
    assert match["rejected_alternatives"]


def test_20_split_node():
    baseline = _obs(class_name="android.widget.Button")
    candidates = [
        _obs(step=2, class_name="android.widget.TextView", transaction="b"),
        _obs(step=3, class_name="android.widget.TextView", transaction="c"),
    ]
    assert "SPLIT_NODE" in {item["node_delta"] for item in match_observations([baseline], candidates)}


def test_21_merged_node():
    baselines = [
        _obs(step=2, class_name="android.widget.TextView", transaction="b"),
        _obs(step=3, class_name="android.widget.TextView", transaction="c"),
    ]
    candidate = _obs(class_name="android.widget.Button")
    assert "MERGED_NODE" in {item["node_delta"] for item in match_observations(baselines, [candidate])}


@pytest.mark.parametrize(
    ("before", "after", "transition"),
    [("COVERED", "MISSED", "COVERED → MISSED"), ("MISSED", "COVERED", "MISSED → COVERED")],
)
def test_22_23_coverage_common_cohort(before, after, transition):
    baseline, candidate = _obs(coverage=before), _obs(coverage=after)
    result = compare_coverage_transitions(match_observations([baseline], [candidate]), [baseline], [candidate])
    assert result["transitions"][0]["transition"] == transition
    assert result["by_scenario"]["scenario"][transition] == 1


def test_24_added_denominator_candidate():
    candidate = _obs(coverage="MISSED")
    result = compare_coverage_transitions(match_observations([], [candidate]), [], [candidate])
    assert result["transitions"][0]["transition"] == "ADDED_CANDIDATE"


def test_25_optional_observation_unavailable():
    baseline = _set([], kind="BASELINE", source_id="b", availability=ObservationAvailability.UNAVAILABLE)
    candidate = _set([], kind="CANDIDATE", source_id="c", availability=ObservationAvailability.UNAVAILABLE)
    assert compare_observation_sets(baseline, candidate)["observation_availability"]["status"] == "DATA_UNAVAILABLE"


def test_26_corrupt_observation_artifact(tmp_path):
    source = adapt_approved_baseline(APP_ROOT / ENGLISH_ID)
    digest = "0" * 64
    payload = tmp_path / "sha256" / "00" / digest / "payload"
    payload.parent.mkdir(parents=True)
    payload.write_text("not the expected digest", encoding="utf-8")
    artifacts = copy.deepcopy(source.artifacts)
    artifacts["optional"] = [{
        "artifact_type": "evidence_ledger",
        "availability": "AVAILABLE",
        "reference": f"artifact://sha256/{digest}",
        "digest": digest,
        "required": False,
        "schema_version": "evidence-event-v1",
    }]
    artifacts["required"] = []
    artifacts["optional_observations"] = {"evidence_ledger": {"status": "AVAILABLE"}}
    result = load_observation_set(replace(source, artifacts=artifacts), artifact_root=tmp_path)
    assert result.availability == ObservationAvailability.CORRUPT


def test_27_asymmetric_availability_blocks_full_comparison():
    baseline = _set([_obs()], kind="BASELINE", source_id="b")
    candidate = _set([], kind="CANDIDATE", source_id="c", availability=ObservationAvailability.PARTIAL)
    result = compare_observation_sets(baseline, candidate)
    assert result["observation_availability"]["reason"] == "ASYMMETRIC_OBSERVATION_AVAILABILITY"


def test_28_deterministic_output():
    baseline = _set([_obs()], kind="BASELINE", source_id="b")
    candidate = _set([_obs()], kind="CANDIDATE", source_id="c")
    first = compare_observation_sets(baseline, candidate, generated_at="2026-07-17T00:00:00Z")
    second = compare_observation_sets(baseline, candidate, generated_at="2026-07-17T00:00:00Z")
    assert first == second


def test_29_read_only_adapter(tmp_path):
    source = adapt_approved_baseline(APP_ROOT / ENGLISH_ID)
    before = source.to_dict()
    load_observation_set(source, qa_runs_root=tmp_path, artifact_root=tmp_path)
    assert source.to_dict() == before
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize(
    ("baseline_id", "locale"),
    [(ENGLISH_ID, "en-US"), (KOREAN_ID, "ko-KR")],
)
def test_30_31_real_approved_limitation_fixtures(baseline_id, locale):
    source = adapt_approved_baseline(APP_ROOT / baseline_id)
    observations = load_observation_set(
        source,
        qa_runs_root=ROOT / "qa_frontend_runs",
        artifact_root=ROOT / ".baseline-artifacts",
    )
    assert observations.availability == ObservationAvailability.COMPLETE
    assert observations.locale == locale
    assert len(observations.observations) > 500
    failures = {item.scenario_id for item in observations.observations if item.mismatch_type == "EMPTY_VISIBLE"}
    assert {"device_water_leak_sensor_plugin", "life_home_monitor_plugin"} <= failures


def test_normalization_keeps_dynamic_placeholders_and_no_cross_locale_equivalence():
    en = normalize_text("Battery 87 percent", locale="en-US")
    ko = normalize_text("배터리 100%", locale="ko-KR")
    assert "<percent>" in en["semantic"]
    assert "<percent>" in ko["semantic"]
    assert en["semantic"] != ko["semantic"]
