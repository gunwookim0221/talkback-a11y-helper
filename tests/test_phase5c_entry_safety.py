"""Portable regressions for the Phase 5C entry safety boundary."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from tb_runner import entry_safety
from tb_runner.entry_safety import (authorize_entry, classify_post_open,
    click_events, hierarchy_digest, resolve_navigation_owner, verify_actual_hit)

_BASE_ENTRY_SAFETY_CONFIG = entry_safety.default_config


@pytest.fixture(autouse=True)
def explicit_read_only_effect_for_positive_harness_cases(monkeypatch):
    def test_config():
        config = deepcopy(_BASE_ENTRY_SAFETY_CONFIG())
        config.setdefault("metadata_rules", []).append({
            "match": {"resource_id": ".*", "context_kind": "plugin_entry"},
            "effect": "read_only_navigation",
        })
        return config
    monkeypatch.setattr(entry_safety, "default_config", test_config)


def test_absent_configured_read_only_effect_is_not_granted_by_default(monkeypatch):
    monkeypatch.setattr(entry_safety, "default_config", _BASE_ENTRY_SAFETY_CONFIG)
    card = node("app:id/plain", "Example Service", "[20,100][1000,600]", clickable=True)
    result = resolve_navigation_owner([card], card, "Example Service")
    decision = authorize_entry(result, [card], scenario="example", matched_phrase="Example Service")
    assert decision["authorized"] is False
    assert decision["reason"] == "ENTRY_TARGET_RISK_OR_CONFIG_CONFLICT"


def test_entry_click_capture_helper_action_is_registered_with_permission_gate():
    project_root = Path(__file__).resolve().parents[1]
    manifest = ET.parse(project_root / "app/src/main/AndroidManifest.xml").getroot()
    android = "{http://schemas.android.com/apk/res/android}"
    receiver = next(node for node in manifest.iter("receiver")
                    if node.get(android + "name") == ".A11yCommandReceiver")
    actions = {node.get(android + "name") for node in receiver.findall(".//action")}
    assert receiver.get(android + "exported") == "true"
    assert receiver.get(android + "permission") == "android.permission.DUMP"
    assert "com.iotpart.sqe.talkbackhelper.ENTRY_CLICK_CAPTURE" in actions

    receiver_source = (project_root / "app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yCommandReceiver.kt").read_text(encoding="utf-8")
    assert "ACTION_ENTRY_CLICK_CAPTURE -> handleEntryClickCapture(intent)" in receiver_source


def node(rid, label, bounds, *, clickable=False, children=None, klass="android.view.ViewGroup", checkable=False):
    return dict(viewIdResourceName=rid, contentDescription=label, text="", className=klass,
                boundsInScreen=bounds, clickable=clickable, enabled=True, checkable=checkable,
                sourceNodeId=f"stable:{rid}" if rid else None, windowId=4,
                children=children or [])


def mixed_card():
    header = node("app:id/header", "Example Service", "[20,120][1000,180]", clickable=True)
    header.update(role="button", actions=[16])
    child = node("app:id/mode", "Armed Stay", "[400,300][700,540]", clickable=True, checkable=True)
    card = node("app:id/card", "Example Service", "[20,100][1000,600]", clickable=True,
                children=[header, child])
    card.update(role="button", actions=[16])
    return [card], card, header, child


def current_focus_observation(*, request_id, transaction_id, capture_id, connection_id,
                              click_event_id, dispatch_ms, click_captured_ms, focus_label="Destination",
                              owner_lease=None):
    observation = dict(
        event_id="post-focus-event", request_id=request_id, transaction_id=transaction_id,
        capture_id=capture_id, connection_id=connection_id, source_click_event_id=click_event_id,
        dispatch_uptime_ms=dispatch_ms, source_click_captured_elapsed_realtime_ms=click_captured_ms,
        captured_elapsed_realtime_ms=click_captured_ms + 100, current_capture_id="post-capture-id",
        root_window_id=9, focus_node_id="focus-node", focus_window_id=9, accessibility_focused=True,
        current_hierarchy=dict(sourceNodeId="focus-node", windowId=9, accessibilityFocused=True,
                               text=focus_label, contentDescription="", children=[]),
    )
    if isinstance(owner_lease, dict):
        for payload_key, observation_key in (
            ("ownerLeaseId", "owner_lease_id"), ("runId", "run_id"),
            ("invocationId", "invocation_id"), ("helperSnapshotId", "owner_helper_snapshot_id"),
            ("ownerDescriptorDigest", "owner_descriptor_digest"),
        ):
            observation[observation_key] = owner_lease.get(payload_key)
    return observation


def nested_action_card():
    away = node("demo:id/action_away", "Armed Away", "[80,340][350,520]", clickable=True, checkable=True)
    stay = node("demo:id/action_stay", "Armed Stay", "[390,340][660,520]", clickable=True, checkable=True)
    disarm = node("demo:id/action_disarm", "Disarm", "[700,340][970,520]", clickable=True, checkable=True)
    header = node("demo:id/navigation_header", "Home Monitor", "[30,120][1050,180]", clickable=True)
    header.update(role="button", actions=[16])
    inner = node("demo:id/card_content", "Home Monitor", "[20,100][1060,600]", clickable=True,
                 children=[header, away, stay, disarm])
    inner.update(role="button", actions=[16])
    outer = node("demo:id/service_card", "Home Monitor", "[10,80][1070,620]", clickable=True,
                 children=[inner])
    outer.update(role="button", actions=[16])
    return [outer], outer, inner, header, [away, stay, disarm]


def test_mixed_card_resolves_named_navigation_owner_away_from_independent_child():
    roots, card, header, child = mixed_card()
    result = resolve_navigation_owner(roots, card, "Example Service")
    assert result["ok"] and result["owner"] is header
    assert result["point"] == (510, 150)
    assert not (400 <= result["point"][0] < 700 and 300 <= result["point"][1] < 540)
    permit = authorize_entry(result, roots, scenario="life_example_plugin", matched_phrase="Example Service")
    assert permit["authorized"] and permit["target_identity"]["resource_id"] == "app:id/header"


def test_full_tree_lineage_makes_outer_and_header_selection_order_invariant():
    roots, outer, inner, header, controls = nested_action_card()
    outer_result = resolve_navigation_owner(roots, outer, "Home Monitor")
    header_result = resolve_navigation_owner(roots, header, "Home Monitor")

    assert outer_result["ok"] and header_result["ok"]
    assert outer_result["owner"] is header_result["owner"] is header
    assert outer_result["point"] == header_result["point"]
    assert outer_result["candidate_lineage"] == []
    assert [item["resource_id"] for item in header_result["candidate_lineage"]] == [
        "demo:id/service_card", "demo:id/card_content"]
    assert header_result["owner_lineage"] == header_result["candidate_lineage"]
    assert all(control is not outer_result["owner"] for control in controls)
    assert all(not (bounds[0] <= outer_result["point"][0] < bounds[2]
                    and bounds[1] <= outer_result["point"][1] < bounds[3])
               for bounds in ((80, 340, 350, 520), (390, 340, 660, 520), (700, 340, 970, 520)))


def test_unknown_clickable_ancestor_remains_a_competing_owner():
    roots, _outer, _inner, header, _controls = nested_action_card()
    outer = roots[0]
    outer["contentDescription"] = ""
    outer.pop("role")
    outer.pop("actions")

    result = resolve_navigation_owner(roots, header, "Home Monitor")
    assert not result["ok"] and result["reason"] == "HIT_OWNER_AMBIGUOUS"
    assert result["conflicting_owner_identities"][0]["resource_id"] == "demo:id/service_card"


def test_actionable_ancestor_with_distinct_action_semantics_remains_a_competitor():
    roots, _outer, _inner, header, _controls = nested_action_card()
    outer = roots[0]
    outer["contentDescription"] = ""
    outer.update(role="group", actions=[16, 32], checkable=True)

    result = resolve_navigation_owner(roots, header, "Home Monitor")
    assert not result["ok"] and result["reason"] == "HIT_OWNER_AMBIGUOUS"
    assert result["conflicting_owner_identities"][0]["resource_id"] == "demo:id/service_card"


def test_independent_actionable_descendant_overlapping_owner_point_is_rejected():
    roots, outer, _inner, header, _controls = nested_action_card()
    control = node("demo:id/overlapping_action", "Turn off", "[400,120][700,180]",
                   clickable=True, checkable=True)
    outer["children"][0]["children"].append(control)

    result = resolve_navigation_owner(roots, header, "Home Monitor")
    assert not result["ok"]
    assert result["reason"] in {"NO_UNOCCUPIED_OWNER_HIT_AREA", "HIT_OWNER_AMBIGUOUS"}


def test_unrelated_overlapping_sibling_remains_a_competitor():
    roots, outer, _inner, header, _controls = nested_action_card()
    sibling = node("demo:id/overlap", "Other action", "[400,120][700,180]", clickable=True)
    outer["children"].append(sibling)

    result = resolve_navigation_owner(roots, header, "Home Monitor")
    assert not result["ok"] and result["reason"] == "HIT_OWNER_AMBIGUOUS"


def test_detached_or_corrupt_full_tree_lineage_fails_closed():
    roots, _outer, _inner, header, _controls = nested_action_card()
    detached = deepcopy(header)
    assert resolve_navigation_owner(roots, detached, "Home Monitor") == {
        "ok": False, "reason": "HIERARCHY_LINEAGE_UNPROVEN"}

    roots[0]["children"] = "not-a-child-list"
    result = resolve_navigation_owner(roots, roots[0], "Home Monitor")
    assert not result["ok"] and result["reason"] == "HIERARCHY_LINEAGE_UNPROVEN"


def test_parent_center_cannot_inherit_navigation_authorization_for_security_child():
    roots, card, header, child = mixed_card()
    permit = authorize_entry(resolve_navigation_owner(roots, card, "Example Service"), roots,
                             scenario="life_example_plugin", matched_phrase="Example Service")
    assert permit["point"] != (510, 350)
    event = dict(event_id="click-event", package="com.samsung.android.oneconnect",
                 transaction_id=permit["transaction_id"], source_node_id=child["sourceNodeId"],
                 window_id=child["windowId"], class_name="android.view.ViewGroup",
                 text="[Armed, Stay]", bounds=(400, 300, 700, 540))
    result = verify_actual_hit(permit, {}, {"click-event": event}, roots=roots)
    assert result["matched"] is False and result["reason"] == "ACTIVATED_SOURCE_AMBIGUOUS"


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
    content["focusable"] = True
    wrapper = node("app:id/card", "", "[20,100][1000,600]", clickable=True, children=[content])
    wrapper["focusable"] = True
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


def test_helper_hierarchy_does_not_invent_missing_xmlentry_target_identity():
    from talkback_lib.hierarchy_snapshot import legacy_scroll_nodes

    candidate = dict(
        className="android.widget.RelativeLayout",
        packageName="com.samsung.android.oneconnect",
        viewIdResourceName="",
        text="",
        contentDescription="Air Care",
        boundsInScreen={"left": 30, "top": 2054, "right": 1050, "bottom": 2558},
        clickable=True,
        enabled=True,
        windowId=45518,
        sourceNodeId=None,
        children=[],
    )
    snapshot = {
        "success": True,
        "windows": [{
            "id": 45518,
            "active": True,
            "focused": True,
            "root": {
                "className": "android.widget.FrameLayout",
                "packageName": "com.samsung.android.oneconnect",
                "boundsInScreen": {"left": 0, "top": 0, "right": 1080, "bottom": 2400},
                "windowId": 45518,
                "children": [candidate],
            },
        }],
    }
    roots = legacy_scroll_nodes(snapshot)
    adapted_candidate = roots[0]["children"][0]

    assert adapted_candidate["sourceNodeId"] is None
    assert adapted_candidate["windowId"] == 45518
    resolution = resolve_navigation_owner(roots, adapted_candidate, "Air Care")
    assert resolution["ok"] is True
    decision = authorize_entry(resolution, roots, scenario="life_air_care_plugin", matched_phrase="Air Care")
    assert decision["authorized"] is False
    assert decision["reason"] == "ENTRY_TARGET_STABLE_IDENTITY_UNAVAILABLE"


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
    assert not decision["authorized"] and decision["reason"] == "ENTRY_TARGET_RISK_OR_CONFIG_CONFLICT"


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
    click = dict(
        event_id="click-event", event_time="1100", event_ingestion_elapsed_realtime_ms=1100,
        dispatch_uptime_ms=1000, package="com.samsung.android.oneconnect",
        transaction_id=permit["transaction_id"], request_id="request-1", capture_id="capture-1",
        connection_id="connection-1", source_node_id=header["sourceNodeId"], window_id=header["windowId"],
    )
    collection = dict(
        req_id="request-1", transaction_id=permit["transaction_id"], capture_id="capture-1",
        connection_id="connection-1", deadline_uptime_ms=2000,
        post_action_observations=[current_focus_observation(
            request_id="request-1", transaction_id=permit["transaction_id"], capture_id="capture-1",
            connection_id="connection-1", click_event_id="click-event", dispatch_ms=1000,
            click_captured_ms=1100)],
    )
    hit = verify_actual_hit(
        permit, {}, {"click-event": click}, roots=roots, dispatch_uptime_ms=1000,
        collection=collection, required_anchor_patterns={"anchor_text": "Destination"},
    )
    assert hit["matched"] is True
    click["source_node_id"] = child["sourceNodeId"]
    hit = verify_actual_hit(
        permit, {}, {"click-event": click}, roots=roots, dispatch_uptime_ms=1000,
        collection=collection, required_anchor_patterns={"anchor_text": "Destination"},
    )
    assert not hit["matched"] and hit["reason"] == "ACTIVATED_SOURCE_AMBIGUOUS"


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
    header.update(_helperNodePath=[0], _helperNodeDescriptorDigest="d" * 64,
                  _helperSourceSnapshotId="source-snapshot")
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
    capture_sessions = []
    def begin_capture(_client, _dev, *, transaction_id, target_node, scenario_id):
        assert target_node is header
        armed = dict(ok=True, reqId="capture", captureReqId="capture",
            requestedTransactionId=transaction_id, transactionId=transaction_id,
            captureId="capture-id", connectionId="connection-1", runId="run-1",
            invocationId="invocation-1", ownerLeaseId="lease-1", ownerWindowId=4,
            ownerPath=[0], ownerDescriptorDigest="d" * 64,
            sourceSnapshotId="source-snapshot", helperSnapshotId="helper-snapshot",
            leaseDeadlineElapsedRealtimeMs=999999)
        capture = dict(req_id="capture", transaction_id=transaction_id, capture_id="capture-id",
                       connection_id="connection-1", armed=armed, talkback_baseline={})
        capture_sessions.append(capture)
        return capture
    monkeypatch.setattr(entry_safety, "begin_transaction_click_capture", begin_capture)
    monkeypatch.setattr(entry_safety, "validate_transaction_click_capture",
                        lambda *_a, **_k: {"ok": True, "reason": "TARGET_CURRENT"})
    def dispatch(client, _dev, point):
        client.taps.append(tuple(point))
        return dict(executed=True, dispatch_uptime_ms=1000, dispatch_started_monotonic_ns=1_000_000_000)
    monkeypatch.setattr(entry_safety, "dispatch_authorized_entry_tap", dispatch)
    monkeypatch.setattr(entry_safety, "mark_transaction_click_dispatch", lambda *_a, **_k: {"ok": True})
    def collect(*_args, **kwargs):
        capture = capture_sessions[0]
        permit = kwargs["permit"]
        request_id = capture["req_id"]
        transaction_id = permit["transaction_id"]
        click = dict(
            event_id="click-event", event_time="1500", event_ingestion_elapsed_realtime_ms=1501,
            event_time_elapsed_realtime_ms=1500,
            dispatch_uptime_ms=1000, package="com.samsung.android.oneconnect",
            transaction_id=transaction_id, request_id=request_id, capture_id=capture["capture_id"],
            connection_id=capture["connection_id"], source_node_id=header["sourceNodeId"],
            window_id=header["windowId"], bounds=(20,120,1000,180), text="[Example Service]",
            owner_relation="EXACT_RETAINED_NODE_REFERENCE", owner_exact=True, owner_lease_id="lease-1",
            owner_window_id=4, owner_helper_snapshot_id="helper-snapshot",
            owner_descriptor_digest="d" * 64, run_id="run-1", invocation_id="invocation-1",
        )
        post = current_focus_observation(
            request_id=request_id, transaction_id=transaction_id, capture_id=capture["capture_id"],
            connection_id=capture["connection_id"], click_event_id="click-event",
            dispatch_ms=1000, click_captured_ms=1501, owner_lease=capture["armed"],
        )
        return dict(ok=True, req_id=request_id, transaction_id=transaction_id,
                    capture_id=capture["capture_id"], connection_id=capture["connection_id"],
                    candidate_events=[click], post_action_observations=[post], deadline_uptime_ms=2000)
    monkeypatch.setattr(entry_safety, "collect_transaction_click_events", collect)
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg={"scenario_id": "life_example_plugin",
                                   "anchor": {"text_regex": "Destination"}},
        target="Example Service", type_="card", max_scroll_search_steps=0,
        step_wait_seconds=.1, transition_fast_path=True)
    assert ok and reason == "xml_entry_success"
    assert client.taps == [(510,150)]
    audit = (tmp_path / "phase5c_entry_actions.jsonl").read_text(encoding="utf8")
    assert audit.index("ENTRY_AUTHORIZATION") < audit.index("ENTRY_CLICK_CAPTURE_PRE_DISPATCH_VALIDATION") \
        < audit.index("ENTRY_DISPATCH") < audit.index("ENTRY_ACTUAL_HIT")

    client.taps.clear()
    monkeypatch.setattr(entry_safety, "validate_transaction_click_capture",
                        lambda *_a, **_k: {"ok": False, "reason": "ENTRY_CLICK_CAPTURE_TARGET_STALE"})
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg={"scenario_id": "life_example_plugin",
                                   "anchor": {"text_regex": "Destination"}},
        target="Example Service", type_="card", max_scroll_search_steps=0,
        step_wait_seconds=.1, transition_fast_path=True)
    assert not ok and "ENTRY_CLICK_CAPTURE_TARGET_STALE" in reason
    assert client.taps == []


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
    capture = dict(req_id="capture", armed={"ok": True}, talkback_baseline={})
    monkeypatch.setattr(entry_safety, "begin_transaction_click_capture", lambda *_a, **_k: capture)
    def dispatch(client, _dev, point):
        client.taps.append(tuple(point))
        return dict(executed=True, dispatch_uptime_ms=1000, dispatch_started_monotonic_ns=1_000_000_000)
    monkeypatch.setattr(entry_safety, "dispatch_authorized_entry_tap", dispatch)
    monkeypatch.setattr(entry_safety, "mark_transaction_click_dispatch", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(entry_safety, "collect_transaction_click_events", lambda *_a, **_k: dict(
        ok=True, candidate_events=[], deadline_uptime_ms=2000))
    class Client:
        taps = []
        def dump_tree(self, **_): return wrapped
        def tap_xy_adb(self, **kw): self.taps.append((kw["x"],kw["y"])); return True
    client = Client()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg={"scenario_id": "life_example_plugin"},
        target="Example Service", type_="card", max_scroll_search_steps=0,
        step_wait_seconds=.1, transition_fast_path=True)
    assert not ok and "ENTRY_TARGET_OBSERVATION_LEASE_MISMATCH" in reason
    assert client.taps == []
