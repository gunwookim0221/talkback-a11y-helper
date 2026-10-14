"""Portable regressions for the Phase 5C entry safety boundary."""
from copy import deepcopy

from tb_runner.entry_safety import (authorize_entry, classify_post_open,
    click_events, hierarchy_digest, resolve_navigation_owner, verify_actual_hit)


def node(rid, label, bounds, *, clickable=False, children=None, klass="android.view.ViewGroup", checkable=False):
    return dict(viewIdResourceName=rid, contentDescription=label, text="", className=klass,
                boundsInScreen=bounds, clickable=clickable, enabled=True, checkable=checkable,
                children=children or [])


def mixed_card():
    header = node("app:id/header", "Example Service", "[20,120][1000,180]", clickable=True)
    child = node("app:id/mode", "Armed Stay", "[400,300][700,540]", clickable=True, checkable=True)
    card = node("app:id/card", "", "[20,100][1000,600]", clickable=True,
                children=[header, child])
    return [card], card, header, child


def test_mixed_card_resolves_named_navigation_owner_away_from_independent_child():
    roots, card, header, child = mixed_card()
    result = resolve_navigation_owner(roots, card, "Example Service")
    assert result["ok"] and result["owner"] is header
    assert result["point"] == (510, 150)
    assert not (400 <= result["point"][0] < 700 and 300 <= result["point"][1] < 540)
    permit = authorize_entry(result, roots, scenario="life_example_plugin", matched_phrase="Example Service")
    assert permit["authorized"] and permit["target_identity"]["resource_id"] == "app:id/header"


def test_parent_center_cannot_inherit_navigation_authorization_for_security_child():
    roots, card, header, child = mixed_card()
    permit = authorize_entry(resolve_navigation_owner(roots, card, "Example Service"), roots,
                             scenario="life_example_plugin", matched_phrase="Example Service")
    assert permit["point"] != (510, 350)
    hit = {"1": dict(package="com.samsung.android.oneconnect", class_name="android.view.ViewGroup",
                          text="[Armed, Stay]", bounds=(400, 300, 700, 540))}
    result = verify_actual_hit(permit, {}, hit)
    assert result["matched"] is False and result["reason"] == "ACTIVATED_TARGET_MISMATCH"


def test_ambiguous_named_actions_fail_closed():
    roots, card, header, child = mixed_card()
    card["children"].append(node("app:id/other", "Example Service", "[20,190][1000,250]", clickable=True))
    result = resolve_navigation_owner(roots, card, "Example Service")
    assert result == {"ok": False, "reason": "MULTIPLE_NAMED_ACTION_OWNERS"}
    assert authorize_entry(result, roots, scenario="example", matched_phrase="Example Service")["authorized"] is False


def test_equal_geometry_independent_toggle_blocks_wrapper_authorization():
    switch = node("app:id/switch", "", "[20,100][1000,600]", clickable=True, checkable=True)
    card = node("app:id/card", "Example Service", "[20,100][1000,600]", clickable=True,
                children=[switch])
    result = resolve_navigation_owner([card], card, "Example Service")
    assert not result["ok"] and result["reason"] == "NO_UNOCCUPIED_OWNER_HIT_AREA"


def test_equal_geometry_named_navigation_descendant_can_own_entry():
    content = node("app:id/content", "Video, No clips detected today", "[20,100][1000,600]", clickable=True)
    wrapper = node("app:id/card", "", "[20,100][1000,600]", clickable=True, children=[content])
    result = resolve_navigation_owner([wrapper], wrapper, "video")
    assert result["ok"] and result["owner"] is content
    assert authorize_entry(result, [wrapper], scenario="life_video_plugin", matched_phrase="video")["authorized"]


def test_plain_card_preserves_navigation_and_unknown_target_blocks():
    card = node("app:id/plain", "Example Service", "[20,100][1000,600]", clickable=True)
    roots = [card]
    result = resolve_navigation_owner(roots, card, "Example Service")
    assert result["ok"] and result["point"] == (510, 350)
    assert authorize_entry(result, roots, scenario="example", matched_phrase="Example Service")["authorized"]
    unknown = deepcopy(card)
    unknown["clickable"] = False
    assert not authorize_entry(resolve_navigation_owner([unknown], unknown, "Example Service"), [unknown],
                               scenario="example", matched_phrase="Example Service")["authorized"]


def test_risky_and_configured_forbidden_entry_actions_are_blocked(monkeypatch):
    from tb_runner import entry_safety
    risky = node("app:id/delete", "Delete account", "[20,100][1000,600]", clickable=True)
    decision = authorize_entry(resolve_navigation_owner([risky], risky, "Delete account"), [risky],
                               scenario="example", matched_phrase="Delete account")
    assert not decision["authorized"] and decision["classification"]["safety_class"] == "RISKY"
    forbidden = node("app:id/forbidden", "Example Service", "[20,100][1000,600]", clickable=True)
    config = entry_safety.default_config()
    config["metadata_rules"] = [{"match": {"resource_id": "app:id/forbidden"},
                                 "effect": "read_only_navigation", "forbidden": True}]
    monkeypatch.setattr(entry_safety, "default_config", lambda: config)
    decision = authorize_entry(resolve_navigation_owner([forbidden], forbidden, "Example Service"), [forbidden],
                               scenario="example", matched_phrase="Example Service")
    assert not decision["authorized"] and decision["classification"]["safety_class"] == "FORBIDDEN"


def test_hierarchy_change_or_target_change_invalidates_exact_permit():
    roots, card, header, child = mixed_card()
    result = resolve_navigation_owner(roots, card, "Example Service")
    changed = deepcopy(roots)
    changed[0]["children"][0]["boundsInScreen"] = "[20,122][1000,182]"
    assert authorize_entry(result, changed, scenario="example", matched_phrase="Example Service")["reason"] == "HIERARCHY_CHANGED"


def test_unresolved_or_ambiguous_actual_click_fails_closed():
    roots, card, header, child = mixed_card()
    permit = authorize_entry(resolve_navigation_owner(roots, card, "Example Service"), roots,
                             scenario="example", matched_phrase="Example Service")
    assert not verify_actual_hit(permit, {}, {})["matched"]
    events = {str(i): dict(package="com.samsung.android.oneconnect", bounds=(20,120,1000,180),
                           text="[Example Service]") for i in (1,2)}
    assert not verify_actual_hit(permit, {}, events)["matched"]


def test_actual_click_bounds_and_semantics_match_exact_owner():
    roots, card, header, child = mixed_card()
    permit = authorize_entry(resolve_navigation_owner(roots, card, "Example Service"), roots,
                             scenario="example", matched_phrase="Example Service")
    hit = {"1": dict(package="com.samsung.android.oneconnect", bounds=(20,120,1000,180),
                          text="[Example Service]")}
    assert verify_actual_hit(permit, {}, hit)["matched"]
    hit["1"]["text"] = "[Armed Stay]"
    assert not verify_actual_hit(permit, {}, hit)["matched"]


def test_logcat_click_parser_correlates_event_bounds():
    raw = ("talkback eventId=type:EVENT_TYPE_ACCESSIBILITY subtype:TYPE_VIEW_CLICKED "
           "time:77 event=null interpretation=UiChange{sourceBoundsInScreen=Rect(20, 120 - 1000, 180)}\n"
           "talkback event=EventType: TYPE_VIEW_CLICKED; EventTime: 77; "
           "PackageName: com.samsung.android.oneconnect; Action: 0; "
           "[ ClassName: android.view.ViewGroup; Text: [Example Service]; Enabled: true ]\n")
    assert click_events(raw)["77"]["bounds"] == (20,120,1000,180)


def test_entry_audit_is_append_only(monkeypatch, tmp_path):
    import json
    from tb_runner.entry_safety import append_entry_audit
    monkeypatch.setenv("TB_PHASE4C_SMOKE_OUT", str(tmp_path))
    append_entry_audit(dict(event="ENTRY_AUTHORIZATION", transaction_id="one"))
    append_entry_audit(dict(event="ENTRY_ACTUAL_HIT", transaction_id="one"))
    rows = [json.loads(line) for line in (tmp_path / "phase5c_entry_actions.jsonl").read_text(encoding="utf8").splitlines()]
    assert [row["event"] for row in rows] == ["ENTRY_AUTHORIZATION", "ENTRY_ACTUAL_HIT"]


def test_unchanged_source_list_label_never_verifies_plugin_body():
    card = node("app:id/serviceCardBody", "Example Service", "[20,100][1000,600]", clickable=True)
    roots = [node("app:id/bottom_navigation", "Life", "[0,900][1080,1000]"), card]
    verdict = classify_post_open(roots, source_digest=hierarchy_digest(roots), target_title_present=True)
    assert verdict == dict(state="SOURCE_LIST_CONTEXT", destination_identity=False, root_plugin_body=False)


def test_transition_confirmation_rejects_unchanged_source_title(monkeypatch):
    from tb_runner import collection_flow
    card = node("app:id/serviceCardBody", "Example Service", "[20,100][1000,600]", clickable=True)
    roots = [node("app:id/bottom_navigation", "Life", "[0,900][1080,1000]"), card]
    class Client:
        def dump_tree(self, **_): return roots
        def get_focus(self, **_): return card
    monkeypatch.setenv("TB_PHASE5B_CONTROLLED", "1")
    monkeypatch.setenv("TB_PHASE5A_ACTION_SAFETY_MODE", "enforce")
    monkeypatch.setattr(collection_flow, "_extract_window_focus_line", lambda *_: "source")
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    ok, reason = collection_flow._confirm_click_focused_transition(
        Client(), "SERIAL", dict(scenario_id="life_example_plugin", screen_context_mode="new_screen",
                                 context_verify=dict(text_regex="Example Service")),
        transition_fast_path=True, baseline_nodes=roots, baseline_window_focus="source")
    assert not ok and reason == "source_list_context"


def test_entry_safety_failure_cannot_fall_through_to_helper_scrolltouch(monkeypatch):
    from tb_runner import collection_flow
    monkeypatch.setenv("TB_PHASE5B_CONTROLLED", "1")
    monkeypatch.setenv("TB_PHASE5A_ACTION_SAFETY_MODE", "enforce")
    monkeypatch.setattr(collection_flow, "_run_xml_scroll_search_tap",
                        lambda *a, **k: (False, "entry_safety:NO_UNOCCUPIED_OWNER_HIT_AREA"))
    class Client:
        def scrollTouch(self, **_):
            raise AssertionError("unowned fallback must never dispatch")
    client = Client()
    ok = collection_flow._run_pre_navigation_steps(client, "SERIAL", dict(
        scenario_id="life_example_plugin", screen_context_mode="new_screen",
        stabilization_mode="anchor_only", pre_navigation=[dict(
            action="xml_scroll_search_tap", target="Example Service", type="card")]))
    assert not ok
    assert client.last_pre_nav_failure_reason.startswith("xml_entry_failed:entry_safety:")


def test_intermediate_and_same_activity_plugin_body_remain_distinct():
    source = [node("app:id/source", "Example Service", "[0,0][100,100]")]
    loading = [node("app:id/loading", "Loading", "[0,0][100,100]")]
    body = [node("app:id/navigate_up", "Navigate up", "[0,0][100,30]"),
            node("app:id/body", "Example Service", "[0,30][100,100]")]
    digest = hierarchy_digest(source)
    assert classify_post_open(loading, source_digest=digest, target_title_present=False)["state"] == "INTERMEDIATE_STATE"
    verdict = classify_post_open(body, source_digest=digest, activity_changed=False, target_title_present=True)
    assert verdict["state"] == "PLUGIN_BODY" and verdict["root_plugin_body"]


def test_xml_entry_enforces_exact_owner_before_physical_tap(monkeypatch, tmp_path):
    from tb_runner import collection_flow, entry_safety
    roots, card, header, child = mixed_card()
    wrapped = [node("", "", "[0,0][1,1]", children=roots)]
    # The real hierarchy loader supplies a root wrapper around service nodes.
    monkeypatch.setenv("TB_PHASE5B_CONTROLLED", "1")
    monkeypatch.setenv("TB_PHASE5A_ACTION_SAFETY_MODE", "enforce")
    monkeypatch.setenv("TB_PHASE4C_SMOKE_OUT", str(tmp_path))
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **_: (wrapped, "ok"))
    monkeypatch.setattr(collection_flow, "_run_recoverable_precondition_gate", lambda **_: {})
    monkeypatch.setattr(collection_flow, "_extract_window_focus_line", lambda *_: "source")
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_: (True, "destination_body_verify"))
    class Client:
        taps = []
        last_start_open_summary = {}
        def dump_tree(self, **_): return wrapped
        def tap_xy_adb(self, **kw): self.taps.append((kw["x"],kw["y"])); return True
    client = Client()
    events = iter([{}, {"7": dict(package="com.samsung.android.oneconnect",
                                  bounds=(20,120,1000,180), text="[Example Service]")}])
    monkeypatch.setattr(entry_safety, "capture_click_events", lambda *_: next(events))
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg={"scenario_id": "life_example_plugin"},
        target="Example Service", type_="card", max_scroll_search_steps=0,
        step_wait_seconds=.1, transition_fast_path=True)
    assert ok and reason == "xml_entry_success"
    assert client.taps == [(510,150)]
    audit = (tmp_path / "phase5c_entry_actions.jsonl").read_text(encoding="utf8")
    assert audit.index("ENTRY_AUTHORIZATION") < audit.index("ENTRY_DISPATCH") < audit.index("ENTRY_ACTUAL_HIT")


def test_xml_entry_blocks_unproven_actual_hit_and_does_not_confirm(monkeypatch, tmp_path):
    from tb_runner import collection_flow, entry_safety
    roots, card, header, child = mixed_card()
    wrapped = [node("", "", "[0,0][1,1]", children=roots)]
    monkeypatch.setenv("TB_PHASE5B_CONTROLLED", "1")
    monkeypatch.setenv("TB_PHASE5A_ACTION_SAFETY_MODE", "enforce")
    monkeypatch.setenv("TB_PHASE4C_SMOKE_OUT", str(tmp_path))
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **_: (wrapped, "ok"))
    monkeypatch.setattr(collection_flow, "_run_recoverable_precondition_gate", lambda **_: {})
    monkeypatch.setattr(collection_flow, "_extract_window_focus_line", lambda *_: "source")
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition",
                        lambda **_: (_ for _ in ()).throw(AssertionError("must stop before confirm")))
    monkeypatch.setattr(entry_safety, "capture_click_events", lambda *_: {})
    class Client:
        taps = []
        def dump_tree(self, **_): return wrapped
        def tap_xy_adb(self, **kw): self.taps.append((kw["x"],kw["y"])); return True
    client = Client()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg={"scenario_id": "life_example_plugin"},
        target="Example Service", type_="card", max_scroll_search_steps=0,
        step_wait_seconds=.1, transition_fast_path=True)
    assert not ok and "CLICK_EVENT_MISSING_OR_AMBIGUOUS" in reason
    assert client.taps == [(510,150)]
