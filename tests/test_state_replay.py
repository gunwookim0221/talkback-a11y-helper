from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from state_model_fixtures import reviewed_replay_suite
from tb_runner.state_registry import StateRegistry
from tb_runner.state_replay import replay_dataset


@pytest.mark.parametrize("dataset",reviewed_replay_suite()["datasets"],ids=lambda d:d["name"])
def test_reviewed_replay_case(dataset):
    report,registry=replay_dataset(dataset)
    assert report["verdict"] in ("PASS","PASS_WITH_LIMITATIONS")
    m=report["metrics"]
    assert m["FINGERPRINT_STABLE"]==m["TOTAL_REPLAY_CASES"]
    assert m["EQUALITY_STABLE"]==m["EQUALITY_CASE_COUNT"]
    assert m["REGISTRY_RESOLUTION_STABLE"]==m["TOTAL_REPLAY_CASES"]
    assert m["STATE_COLLISIONS"]==m["UNSAFE_MERGES"]==m["UNEXPECTED_STATE_SPLITS"]==0
    assert report["persistence_roundtrip"] is True


def test_reviewed_fixture_file_matches_source_oracles():
    path=Path(__file__).parent/"state_model_data"/"replay_cases.json"
    assert json.loads(path.read_text(encoding="utf-8"))==reviewed_replay_suite()


def test_fingerprint_only_is_ambiguous_and_never_creates_state():
    dataset=next(d for d in reviewed_replay_suite()["datasets"] if d["name"]=="fingerprint-only")
    report,registry=replay_dataset(dataset)
    assert registry.state_count==0
    assert report["metrics"]["AMBIGUOUS_CASES"]==2
    assert report["metrics"]["FINGERPRINT_ONLY_CASES"]==2


def test_reverse_scroll_insertion_keeps_one_partition_without_unlinked_merge():
    dataset=next(d for d in reviewed_replay_suite()["datasets"] if d["name"]=="scroll")
    dataset["registration_order"]=["b","a"]
    report,registry=replay_dataset(dataset)
    assert report["verdict"]=="PASS" and registry.state_count==1


def test_wrong_oracle_causes_failure_instead_of_adjusting_contract():
    dataset=reviewed_replay_suite()["datasets"][0]
    dataset["pairs"][0]["expected"]="DIFFERENT"
    report,registry=replay_dataset(dataset)
    assert report["verdict"]=="FAIL"
    assert report["failures"]==["equality:exact"]


def test_wrong_group_oracle_reports_collision():
    dataset=reviewed_replay_suite()["datasets"][0]
    dataset["expected_groups"]["b"]="other-state"
    report,registry=replay_dataset(dataset)
    assert report["verdict"]=="FAIL"
    assert report["metrics"]["STATE_COLLISIONS"]==1


@pytest.mark.parametrize("mutation",["schema","duplicate_source","unknown_ref","no_oracle","unreviewed_pair","order"])
def test_invalid_replay_manifests_fail_closed(mutation):
    dataset=reviewed_replay_suite()["datasets"][0]
    if mutation=="schema": dataset["schema_version"]="unknown"
    elif mutation=="duplicate_source": dataset["observations"].append(deepcopy(dataset["observations"][0]))
    elif mutation=="unknown_ref": dataset["pairs"][0]["left"]="missing"
    elif mutation=="no_oracle": dataset.pop("expected_groups")
    elif mutation=="unreviewed_pair": dataset["pairs"][0].pop("expected")
    elif mutation=="order": dataset["registration_order"]=["missing"]
    with pytest.raises(ValueError): replay_dataset(dataset)


def test_registry_namespace_mismatch_is_rejected():
    dataset=reviewed_replay_suite()["datasets"][0]
    with pytest.raises(ValueError): replay_dataset(dataset,StateRegistry("other"))


def test_new_process_cli_restart_preserves_state_mapping(tmp_path):
    dataset=next(d for d in reviewed_replay_suite()["datasets"] if d["name"]=="scroll")
    manifest=tmp_path/"manifest.json"
    manifest.write_text(json.dumps(dataset,ensure_ascii=False),encoding="utf-8")
    root=Path(__file__).resolve().parents[1]
    first,second=tmp_path/"first.json",tmp_path/"second.json"
    common=[sys.executable,"-m","tools.state_model_replay","--manifest",str(manifest)]
    a=subprocess.run(common+["--registry-out",str(first),"--report-out",str(tmp_path/"report1.json")],cwd=root,capture_output=True,text=True,timeout=60)
    assert a.returncode==0,a.stderr
    b=subprocess.run(common+["--registry-in",str(first),"--registry-out",str(second),"--report-out",str(tmp_path/"report2.json")],cwd=root,capture_output=True,text=True,timeout=60)
    assert b.returncode==0,b.stderr
    ra,rb=StateRegistry.load(first),StateRegistry.load(second)
    assert [s["state_id"] for s in ra.states]==[s["state_id"] for s in rb.states]
    assert ra.state_count==rb.state_count==1
    assert rb.observation_count==ra.observation_count*2


def test_suite_cli_keeps_dotted_names_as_distinct_files(tmp_path,monkeypatch,capsys):
    from tools import state_model_replay
    first=reviewed_replay_suite()["datasets"][0]
    second=deepcopy(first)
    first["name"],first["namespace"]="fixture.a","fixture.a"
    second["name"],second["namespace"]="fixture.b","fixture.b"
    manifest=tmp_path/"suite.json"
    manifest.write_text(json.dumps({"schema_version":"state-replay-suite-v1","datasets":[first,second]}),encoding="utf-8")
    output=tmp_path/"registries"
    monkeypatch.setattr(sys,"argv",["replay","--manifest",str(manifest),"--registry-out",str(output),"--report-out",str(tmp_path/"report.json")])
    assert state_model_replay.main()==0
    assert sorted(p.name for p in output.iterdir())==["fixture.a.json","fixture.b.json"]


def test_source_observation_replay_and_duplicate_counts_are_stable():
    from tb_runner.state_observation import build_state_observation
    dataset=reviewed_replay_suite()["datasets"][0]
    for source in dataset["observations"]:
        source["observation"]=build_state_observation(source.pop("raw")).to_dict()
    dataset["registration_order"]=["a","b","a","b"]
    report,registry=replay_dataset(dataset)
    assert report["verdict"]=="PASS"
    assert registry.observation_count==4 and registry.state_count==1
