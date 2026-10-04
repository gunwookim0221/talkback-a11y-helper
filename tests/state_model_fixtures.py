"""Reviewed synthetic inputs for Phase 2. Not claims of real UI captures."""
from copy import deepcopy

from tb_runner.scroll_reliability import capability, viewport, transition
from tb_runner.state_observation import build_state_observation
from tb_runner.state_equality import VerifiedScrollEvidence


def node(rid="pkg:id/card", text="Device", bounds="0,100,500,200", **values):
    result = dict(viewIdResourceName=rid, text=text, className="android.widget.TextView",
                  boundsInScreen=bounds, visibleToUser=True, enabled=True, checked=False,
                  selected=False, clickable=True, focusable=True, scrollable=False)
    result.update(values)
    return result


def observation(root="home", **values):
    ids = {"home": "menu_favorites", "devices": "menu_devices", "life": "menu_services"}
    raw = dict(package_name="pkg", activity_name="pkg.MainActivity", display_bounds=[0, 0, 1000, 1000],
               nodes=[node(), node("pkg:id/"+ids[root], root, "0,900,200,1000", selected=True)],
               navigation_context={"bottom_tab": root}, selected_tab={"name": root, "verified": True},
               timestamp="2026-10-05T01:00:00+09:00", scenario_id="synthetic", step=0,
               source="reviewed_synthetic_fixture", context_source="synthetic_observed_context")
    raw.update(values)
    return raw


def scroll_pair():
    a, b = observation(), observation()
    b["step"] = 1
    b["nodes"][0]["boundsInScreen"] = "0,300,500,400"
    cap = capability([], {"canScrollDown": True}, [dict(className="android.widget.ScrollView",
        path="0.1", boundsInScreen="0,0,1000,1000", scroll_forward_supported=True)])
    for raw in (a, b):
        raw["capability"] = deepcopy(cap)
        raw["viewport"] = viewport(raw["nodes"], "synthetic_scroll")
    result = transition(a["viewport"], b["viewport"], True, cap)
    result.update(capability_before=cap, capability_after=cap)
    oa, ob = build_state_observation(a), build_state_observation(b)
    return a, b, result, VerifiedScrollEvidence.from_transition(oa, ob, result)


def reviewed_replay_suite():
    """Human-specified relation/group oracles; never derived from the evaluator."""
    datasets=[]
    def add(name,a,b,verdict,groups=("base","base"),viewport_equal=None,proof=None,bare=False):
        mode="fingerprint" if bare else "raw"
        sources=[dict(key=key,**{mode:build_state_observation(raw).fingerprint.to_dict() if bare else raw})
                 for key,raw in (("a",a),("b",b))]
        pair=dict(name=name,left="a",right="b",expected=verdict,use_continuity=proof is not None)
        if viewport_equal is not None: pair["viewport_equal"]=viewport_equal
        datasets.append(dict(schema_version="state-replay-manifest-v1",name=name,namespace=name,
            fixture_kind="REVIEWED_SYNTHETIC",observations=sources,expected_groups=dict(zip(("a","b"),groups)),
            pairs=[pair],continuities=[{"evidence":proof.to_dict()}] if proof else []))
    a,b=observation(),observation()
    add("exact",a,b,"SAME",viewport_equal=True)
    b=deepcopy(a); b["focus_node"]=node(accessibilityFocused=True); b["nodes"][0]["accessibilityFocused"]=True
    add("focus",a,b,"SAME",viewport_equal=True)
    add("home-devices",a,observation("devices"),"DIFFERENT",("home","devices"))
    add("home-life",a,observation("life"),"DIFFERENT",("home","life"))
    sa,sb,_,proof=scroll_pair()
    add("scroll",sa,sb,"SAME",viewport_equal=False,proof=proof)
    add("unlinked-viewport",sa,sb,"AMBIGUOUS",("base",None))
    b=deepcopy(a); b["overlay"]={"kind":"dialog","observed":True,"nodes":[node("dialog","Permission")]}
    add("overlay",a,b,"DIFFERENT",("base","overlay"),True)
    for name,before,after in (("temperature","23°C","24°C"),("battery","battery 75%","battery 74%"),
                              ("clock","time 10:31","time 10:32"),("locked","locked","unlocked"),
                              ("connected","connected","disconnected")):
        aa,bb=observation(),observation()
        aa["nodes"][0]["text"],bb["nodes"][0]["text"]=before,after
        semantic=name in ("locked","connected")
        add(name,aa,bb,"DIFFERENT" if semantic else "SAME",("before","after") if semantic else ("base","base"))
    for flag in ("enabled","checked"):
        b=deepcopy(a); b["nodes"][0][flag]=not b["nodes"][0][flag]
        add(flag,a,b,"DIFFERENT",("before","after"))
    b=deepcopy(a); b["nodes"].reverse()
    add("ordering",a,b,"SAME",viewport_equal=True)
    aa,bb=observation(),observation()
    aa["nodes"][0]["text"],aa["nodes"][1]["text"]="장치","홈"
    aa["locale"],bb["locale"]="ko-KR","en-US"
    add("locale",aa,bb,"SAME",viewport_equal=True)
    aa,bb=observation(),observation()
    aa["nodes"][0]["text"],bb["nodes"][0]["text"]="Settings subpage","Details subpage"
    add("coarse-collision",aa,bb,"AMBIGUOUS",("known",None))
    add("missing-activity",observation(activity_name=None),observation(activity_name=None),"AMBIGUOUS",(None,None))
    add("partial-full",a,observation(observation_coverage="OBSERVED_FULL"),"AMBIGUOUS",("base",None))
    b=deepcopy(a); b["nodes"].pop(0)
    add("partial-subset",a,b,"AMBIGUOUS",("base",None))
    add("fingerprint-only",a,a,"AMBIGUOUS",(None,None),bare=True)
    return dict(schema_version="state-replay-suite-v1",review_note="Expected relations/groups specified in tests/state_model_fixtures.py; synthetic, not real device evidence.",datasets=datasets)
