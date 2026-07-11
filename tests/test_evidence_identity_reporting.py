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


def test_identity_report_handles_partial_and_malformed_ledger(tmp_path: Path):
    path = tmp_path / "partial.evidence.jsonl"
    path.write_text("not-json\n" + _event("SHADOW_ACTION_REDUCED", "tx-1", {"verdict": "STATIC_FOCUS"}, "a"), encoding="utf-8")
    report = _load(path)
    assert report["availability"] == "LEGACY_ONLY"
    assert report["parse_warnings"] == 1
    assert report["transactions"][0]["v2_verdict"] is None


def test_identity_report_cache_reloads_when_file_state_changes(tmp_path: Path):
    path = tmp_path / "state.evidence.jsonl"
    path.write_text(_event("SHADOW_ACTION_REDUCED", "tx-1", {"verdict": "STATIC_FOCUS"}, "a"), encoding="utf-8")
    assert _load(path)["summary"]["transactions"] == 1
    path.write_text(path.read_text(encoding="utf-8") + "\n" + _event("SHADOW_ACTION_REDUCED", "tx-2", {"verdict": "STATIC_FOCUS"}, "b"), encoding="utf-8")
    assert _load(path)["summary"]["transactions"] == 2
