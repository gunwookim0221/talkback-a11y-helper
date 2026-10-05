"""Home blocker regression: typed metadata must not hide real UI changes."""
from copy import deepcopy

import pytest

from state_model_fixtures import node, observation
from tb_runner.discovery_candidates import build_discovery_snapshot
from tb_runner.canonical_json import canonical_sha256
from tb_runner.state_equality import LEGACY_MATCHING_POLICY, MATCHING_POLICY, evaluate_state_equality
from tb_runner.state_observation import build_state_observation
from tb_runner.state_registry import StateRegistry
from tb_runner.transition_observation import TransitionObserver
from tools.home_identity_closure import pair_diff, summarize


def timestamp_observation(label, resource="pkg:id/update_metadata"):
    raw=observation()
    raw["nodes"].append(node(resource,label,className="android.widget.TextView",focusable=False,clickable=False,
                             bounds="0,400,500,450"))
    return raw


def verdict(a,b):
    return evaluate_state_equality(build_state_observation(a),build_state_observation(b)).verdict.value


@pytest.mark.parametrize("before,after", [
    ("마지막 업데이트: 10/05 4:46 AM", "마지막 업데이트: 10/05 11:26 AM"),
    ("최근 업데이트: 10/05 09:16", "최근 업데이트: 10/06 17:20"),
    ("Last updated: 10/05 4:46 AM", "Last updated: 10/05 9:16 AM"),
    ("Last update: 2026-10-05 04:46", "Last update: 2026-10-06 09:16"),
    ("Updated at: 10/05 4:46 AM", "Updated at: 10/05 9:16 AM"),
])
@pytest.mark.parametrize("resource", ["pkg:id/update_metadata", "org.other:id/reading_age"])
def test_typed_passive_update_timestamp_equivalence_is_generic(before,after,resource):
    a,b=timestamp_observation(before,resource),timestamp_observation(after,resource)
    frozen=deepcopy((a,b))
    assert verdict(a,b)=="SAME"
    assert (a,b)==frozen
    # Saved evidence and Phase 2A fingerprints retain the original label bytes.
    assert build_state_observation(a).to_dict()!=build_state_observation(b).to_dict()
    assert build_state_observation(a).fingerprint.to_dict()==build_state_observation(frozen[0]).fingerprint.to_dict()


@pytest.mark.parametrize("before,after", [
    ("Expires: 10/05 4:46 AM", "Expires: 10/05 9:16 AM"),
    ("10/05 4:46 AM", "10/05 9:16 AM"),
    ("Last updated: 10/05 4:46 AM locked", "Last updated: 10/05 9:16 AM unlocked"),
    ("Last updated: 13/05 4:46 AM", "Last updated: 13/05 9:16 AM"),
    ("Last updated: 10/05 25:46", "Last updated: 10/05 29:16"),
    ("Last updated: model 123", "Last updated: model 456"),
    ("Last updated: locked", "Last updated: unlocked"),
])
def test_unreviewed_dates_values_or_control_suffixes_stay_ambiguous(before,after):
    assert verdict(timestamp_observation(before),timestamp_observation(after))=="AMBIGUOUS"


@pytest.mark.parametrize("changes", [{"clickable":True},{"focusable":True},
    {"className":"android.widget.EditText"},{"checked":True},{"selected":True},
    {"focusable":None},{"clickable":None},{"viewIdResourceName":""}])
def test_actionable_unknown_or_unanchored_timestamp_is_not_normalized(changes):
    a,b=timestamp_observation("Last updated: 10/05 4:46 AM"),timestamp_observation("Last updated: 10/05 9:16 AM")
    for raw in (a,b): raw["nodes"][-1].update(changes)
    assert verdict(a,b)=="AMBIGUOUS"


@pytest.mark.parametrize("flag", ["enabled","checked","selected"])
def test_real_control_change_remains_different(flag):
    a,b=timestamp_observation("Last updated: 10/05 4:46 AM"),timestamp_observation("Last updated: 10/05 9:16 AM")
    b["nodes"][0][flag]=not a["nodes"][0][flag]
    assert verdict(a,b)=="DIFFERENT"


def test_real_state_description_preserved():
    a,b=timestamp_observation("Last updated: 10/05 4:46 AM"),timestamp_observation("Last updated: 10/05 9:16 AM")
    a["nodes"][-1]["stateDescription"]="locked"
    b["nodes"][-1]["stateDescription"]="unlocked"
    assert verdict(a,b)=="DIFFERENT"


def test_partial_observation_stays_ambiguous():
    a=timestamp_observation("Last updated: 10/05 4:46 AM"); b=deepcopy(a)
    b["nodes"].pop(0)
    assert verdict(a,b)=="AMBIGUOUS"


def test_overlay_is_distinct():
    a=timestamp_observation("Last updated: 10/05 4:46 AM"); b=deepcopy(a)
    b["overlay"]=dict(kind="dialog",observed=True,nodes=[node("pkg:id/permission","Allow?")])
    assert verdict(a,b)=="DIFFERENT"


def test_real_positional_instances_remain_distinct():
    raw=timestamp_observation("Last updated: 10/05 4:46 AM")
    raw["nodes"].append(node("pkg:id/action","Device",bounds="0,500,500,600"))
    raw["nodes"].append(node("pkg:id/action","Device",bounds="0,650,500,750"))
    snap=build_discovery_snapshot(raw,StateRegistry("positions"))
    targets=[c.to_dict()["target_identity"] for c in snap.candidates
             if c.to_dict()["target_identity"].get("resource_id")=="pkg:id/action"]
    assert len({t["instance_id"] for t in targets})==2


def test_unlinked_viewport_and_large_geometry_change_stay_ambiguous():
    a=timestamp_observation("Last updated: 10/05 4:46 AM"); b=deepcopy(a)
    b["nodes"][0]["boundsInScreen"]="0,700,500,800"
    assert verdict(a,b)=="AMBIGUOUS"


def test_registry_restart_and_candidate_snapshot_stability(tmp_path):
    a,b=timestamp_observation("Last updated: 10/05 4:46 AM"),timestamp_observation("Last updated: 10/05 9:16 AM")
    reg=StateRegistry("home-restart")
    first=build_discovery_snapshot(a,reg); reg.save(tmp_path/"registry.json")
    loaded=StateRegistry.load(tmp_path/"registry.json")
    after=build_discovery_snapshot(b,loaded)
    assert first.state_id==after.state_id
    assert first.candidate_set_hash==after.candidate_set_hash
    assert loaded.state_count==1 and loaded.unresolved_count==0


def test_legacy_registry_replays_exactly_then_new_event_uses_versioned_policy(tmp_path):
    a,b=timestamp_observation("Last updated: 10/05 4:46 AM"),timestamp_observation("Last updated: 10/05 9:16 AM")
    legacy=StateRegistry("legacy",matching_policy=LEGACY_MATCHING_POLICY)
    sid=build_discovery_snapshot(a,legacy).state_id
    assert build_discovery_snapshot(b,legacy).state_id is None
    before=legacy.to_json();legacy.save(tmp_path/"registry.json")
    current=StateRegistry.load(tmp_path/"registry.json")
    assert current.to_json()==before
    assert build_discovery_snapshot(b,current).state_id==sid
    assert current.to_dict()["events"][-1]["secondary_matching_policy"]==MATCHING_POLICY
    current.save(tmp_path/"mixed.json")
    assert StateRegistry.load(tmp_path/"mixed.json").to_json()==current.to_json()


def test_unknown_saved_policy_is_rejected_even_with_valid_checksum():
    reg=StateRegistry("invalid-policy");build_discovery_snapshot(observation(),reg)
    data=reg.to_dict();data["events"][0]["secondary_matching_policy"]="future-unknown"
    data["content_sha256"]=canonical_sha256({k:v for k,v in data.items() if k!="content_sha256"})
    with pytest.raises(ValueError,match="policy"):
        StateRegistry.from_dict(data)


def test_policy_tag_cannot_rewrite_historical_resolution():
    a,b=timestamp_observation("Last updated: 10/05 4:46 AM"),timestamp_observation("Last updated: 10/05 9:16 AM")
    reg=StateRegistry("tampered",matching_policy=LEGACY_MATCHING_POLICY)
    build_discovery_snapshot(a,reg);build_discovery_snapshot(b,reg)
    data=reg.to_dict();data["events"][-1]["secondary_matching_policy"]=MATCHING_POLICY
    data["content_sha256"]=canonical_sha256({k:v for k,v in data.items() if k!="content_sha256"})
    with pytest.raises(ValueError,match="saved resolution does not replay"):
        StateRegistry.from_dict(data)


def test_return_home_transition_has_resolved_result():
    home=timestamp_observation("Last updated: 10/05 4:46 AM")
    registry=StateRegistry("return-home"); home_id=build_discovery_snapshot(home,registry).state_id
    source=observation("devices")
    observer=TransitionObserver(registry)
    prepared=observer.prepare(source,dict(occurrence_id="return:1",producer="test",action_kind="BOTTOM_NAV",target_identity={"destination":"home"}))
    result=observer.complete(prepared,timestamp_observation("Last updated: 10/05 9:16 AM"),command_ack={"success":True,"status":"activated"})
    assert result.resulting_snapshot.state_id==home_id
    assert result.to_dict()["resulting_state_id"]==home_id


def _bundle(raw,registry,index):
    snap=build_discovery_snapshot(raw,registry)
    return dict(index=index,observation=build_state_observation(raw).to_dict(),snapshot=snap.to_dict())


def test_pair_diff_identifies_unresolved_binding_as_candidate_hash_cause():
    raw=observation(activity_name=None); registry=StateRegistry("unresolved")
    a=_bundle(raw,registry,1); raw=deepcopy(raw);raw["timestamp"]="later"
    b=_bundle(raw,registry,2); pair=pair_diff(a,b)
    assert pair["differences"]["CANDIDATE_SET"] is True
    assert pair["candidate_physical_delta"]=={"REMOVED":[],"ADDED":[]}
    assert pair["equality"]["verdict"]=="AMBIGUOUS"
    metrics=summarize([a,b],[pair])
    assert metrics["HOME_UNRESOLVED_COUNT"]==2
    assert metrics["HOME_UNSAFE_MERGE_COUNT"]==0


def test_coarse_core_collision_never_forces_merge():
    a,b=observation(),observation()
    a["nodes"][0]["text"]="Settings page";b["nodes"][0]["text"]="Other page"
    reg=StateRegistry("collision");first=build_discovery_snapshot(a,reg);after=build_discovery_snapshot(b,reg)
    assert first.state_id is not None and after.state_id is None
