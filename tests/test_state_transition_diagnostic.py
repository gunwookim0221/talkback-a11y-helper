import json

import pytest

from state_model_fixtures import observation
from tb_runner.state_registry import StateRegistry
from tools import state_transition_diagnostic as tool


def fixture():
    return dict(before_raw=observation(), after_raw=observation(),
                action=dict(occurrence_id="replay:1", action_kind="FOCUS_NEXT", producer="saved-controlled-action"),
                command_ack=dict(success=True, status="moved"), evidence_refs={"before": "saved/before.json"})


def test_replay_duplicate_occurrence_count_and_serialization():
    records, metrics = tool.replay([fixture(), fixture()], StateRegistry("replay-test"))
    assert records[0].transition_id == records[1].transition_id
    assert records[0].semantic_hash == records[1].semantic_hash
    assert metrics["TOTAL_TRANSITIONS_OBSERVED"] == 1
    assert metrics["UNSAFE_TRANSITION_BIND_COUNT"] == 0


def test_cli_saved_input_only_and_does_not_overwrite(tmp_path, monkeypatch, capsys):
    source, output, registry = (tmp_path / name for name in ("input.json", "state_transitions.jsonl", "registry.json"))
    source.write_text(json.dumps([fixture(), fixture()]), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["diagnostic", "--input", str(source), "--output", str(output), "--registry-out", str(registry)])
    assert tool.main() == 0
    assert len(output.read_text(encoding="utf-8").splitlines()) == 1
    assert json.loads(capsys.readouterr().out)["TOTAL_TRANSITIONS_OBSERVED"] == 1
    assert StateRegistry.load(registry).state_count == 1
    contents = output.read_bytes()
    with pytest.raises(SystemExit):
        tool.main()
    assert output.read_bytes() == contents


def test_cli_can_use_existing_registry_namespace(tmp_path, monkeypatch):
    path = tmp_path / "registry-in.json"
    StateRegistry("persisted-allocation").save(path)
    source = tmp_path / "input.json"
    source.write_text(json.dumps([fixture()]), encoding="utf-8")
    output = tmp_path / "transitions.jsonl"
    monkeypatch.setattr("sys.argv", ["diagnostic", "--input", str(source), "--registry-in", str(path),
                                   "--registry-out", str(tmp_path / "saved.json"), "--output", str(output)])
    assert tool.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["provenance"]["registry_namespace"] == "persisted-allocation"
