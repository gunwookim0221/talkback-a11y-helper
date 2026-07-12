from __future__ import annotations

import json
from pathlib import Path

from qa_frontend.backend.evidence_identity_reporting import _load


def _event(kind: str, tx: str, payload: dict, event_id: str) -> str:
    return json.dumps({"event_id": event_id, "event_type": kind, "transaction_id": tx, "scenario_id": "home_safe_plugin", "step_index": 1, "payload": payload})


def test_identity_report_joins_legacy_v2_and_deduplicates(tmp_path: Path):
    path = tmp_path / "safe.evidence.jsonl"
    path.write_text("\n".join([
        _event("SHADOW_ACTION_REDUCED", "tx-1", {"verdict": "MOVE_TO_OTHER_NODE"}, "a"),
        _event("SHADOW_ACTION_REDUCED_V2", "tx-1", {"result": {"verdict": "MOVE_CONFIRMED", "target_relation": "STRONG_PHYSICAL_LINK", "evidence_complete": True}}, "b"),
        _event("POST_ACTION_OBSERVATION", "tx-1", {"observation": {"text": "Safe", "resource_id": "id/safe", "secret": "never exposed"}}, "c"),
        _event("SHADOW_ACTION_REDUCED", "tx-1", {"verdict": "MOVE_TO_OTHER_NODE"}, "a"),
    ]), encoding="utf-8")
    report = _load(path)
    assert report["availability"] == "V2_AVAILABLE"
    assert report["summary"]["transactions"] == 1
    row = report["transactions"][0]
    assert row["verdict_changed"] is True
    assert row["landing_summary"] == {"text": "Safe", "resource_id": "id/safe"}


def test_identity_report_projects_nested_v2_diagnostics_and_pre_focus(tmp_path: Path):
    path = tmp_path / "nested.evidence.jsonl"
    path.write_text("\n".join([
        _event("PRE_FOCUS_OBSERVED", "tx-1", {"observation": {"text": "Before", "resource_id": "id/before"}}, "a"),
        _event("SHADOW_ACTION_REDUCED_V2", "tx-1", {
            "verdict": "MOVE_CONFIRMED",
            "evidence_completeness": "COMPLETE",
            "stability": "STABLE_LANDING",
            "identity_diagnostics": {
                "target_landing": {
                    "aggregate_relation": "STRONG_PHYSICAL_LINK",
                    "physical_relation": "STRONG_PHYSICAL_LINK",
                    "semantic_relation": "SAME_SEMANTIC_OBJECT",
                    "hierarchy_relation": "INSUFFICIENT_EVIDENCE",
                    "temporal_relation": "STABLE_LANDING",
                    "confidence": "HIGH_CONFIDENCE",
                    "supporting_fields": ["bounds", "class_name"],
                    "contradictions": ["window_id"],
                    "missing_fields": ["node_path"],
                },
            },
        }, "b"),
    ]), encoding="utf-8")

    report = _load(path)
    row = report["transactions"][0]
    assert row["target_relation"] == "STRONG_PHYSICAL_LINK"
    assert row["physical_relation"] == "STRONG_PHYSICAL_LINK"
    assert row["semantic_relation"] == "SAME_SEMANTIC_OBJECT"
    assert row["hierarchy_relation"] == "INSUFFICIENT_EVIDENCE"
    assert row["temporal_relation"] == "STABLE_LANDING"
    assert row["confidence"] is None
    assert row["supporting_fields"] == ["bounds", "class_name"]
    assert row["contradicting_fields"] == ["window_id"]
    assert row["missing_fields"] == ["node_path"]
    assert row["evidence_complete"] is True
    assert row["pre_focus_summary"] == {"text": "Before", "resource_id": "id/before"}
    assert report["summary"]["incomplete"] == 0
    assert report["summary"]["confidence_counts"] == {"UNAVAILABLE": 1}
    assert report["summary"]["confidence_percentages"] == {"UNAVAILABLE": 100.0}


def test_identity_report_adds_v2_only_distribution_percentages(tmp_path: Path):
    path = tmp_path / "distribution.evidence.jsonl"

    def v2(verdict: str, relation: str, confidence: str) -> dict:
        return {
            "verdict": verdict,
            "confidence": confidence,
            "evidence_completeness": "COMPLETE",
            "identity_diagnostics": {
                "target_landing": {
                    "aggregate_relation": relation,
                    "confidence": confidence,
                },
            },
        }

    path.write_text("\n".join([
        _event("SHADOW_ACTION_REDUCED_V2", "tx-1", v2("MOVE_CONFIRMED", "STRONG_PHYSICAL_LINK", "HIGH_CONFIDENCE"), "a"),
        _event("SHADOW_ACTION_REDUCED_V2", "tx-2", v2("MOVE_CONFIRMED", "STRONG_PHYSICAL_LINK", "HIGH_CONFIDENCE"), "b"),
        _event("SHADOW_ACTION_REDUCED_V2", "tx-3", v2("STATIC_FOCUS", "DIFFERENT_PHYSICAL_NODE", "CONFIRMED"), "c"),
        _event("SHADOW_ACTION_REDUCED", "tx-legacy", {"verdict": "INDETERMINATE"}, "d"),
    ]), encoding="utf-8")

    summary = _load(path)["summary"]
    assert summary["transactions"] == 4
    assert summary["v2_verdicts"] == {"MOVE_CONFIRMED": 2, "STATIC_FOCUS": 1, "NO_V2": 1}
    assert summary["v2_verdict_percentages"] == {
        "MOVE_CONFIRMED": 66.7,
        "STATIC_FOCUS": 33.3,
        "MOVE_TO_OTHER_NODE": 0.0,
        "SNAP_BACK": 0.0,
        "INDETERMINATE": 0.0,
    }
    assert summary["confidence_counts"] == {"CONFIRMED": 1, "HIGH_CONFIDENCE": 2}
    assert summary["confidence_percentages"] == {"CONFIRMED": 33.3, "HIGH_CONFIDENCE": 66.7}
    assert summary["relation_counts"] == {"DIFFERENT_PHYSICAL_NODE": 1, "STRONG_PHYSICAL_LINK": 2}
    assert summary["relation_percentages"] == {"DIFFERENT_PHYSICAL_NODE": 33.3, "STRONG_PHYSICAL_LINK": 66.7}


def test_identity_report_handles_partial_and_malformed_ledger(tmp_path: Path):
    path = tmp_path / "partial.evidence.jsonl"
    path.write_text("not-json\n" + _event("SHADOW_ACTION_REDUCED", "tx-1", {"verdict": "STATIC_FOCUS"}, "a"), encoding="utf-8")
    report = _load(path)
    assert report["availability"] == "LEGACY_ONLY"
    assert report["parse_warnings"] == 1
    assert report["transactions"][0]["v2_verdict"] is None
    assert report["summary"]["v2_verdict_percentages"] == {
        "MOVE_CONFIRMED": 0.0,
        "STATIC_FOCUS": 0.0,
        "MOVE_TO_OTHER_NODE": 0.0,
        "SNAP_BACK": 0.0,
        "INDETERMINATE": 0.0,
    }


def test_identity_report_cache_reloads_when_file_state_changes(tmp_path: Path):
    path = tmp_path / "state.evidence.jsonl"
    path.write_text(_event("SHADOW_ACTION_REDUCED", "tx-1", {"verdict": "STATIC_FOCUS"}, "a"), encoding="utf-8")
    assert _load(path)["summary"]["transactions"] == 1
    path.write_text(path.read_text(encoding="utf-8") + "\n" + _event("SHADOW_ACTION_REDUCED", "tx-2", {"verdict": "STATIC_FOCUS"}, "b"), encoding="utf-8")
    assert _load(path)["summary"]["transactions"] == 2
