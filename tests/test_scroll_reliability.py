import pytest
from tb_runner.scroll_reliability import capability, classify_container, viewport, transition
from tb_runner.traversal_reliability import termination_status


def node(rid="card", bounds="0,0,100,100", label="On", cls="android.widget.GridView", **extra):
    return dict(viewIdResourceName=rid, boundsInScreen=bounds, text=label, className=cls, **extra)


def _record_targeted_scroll(client, kwargs, success=True, *, explicit=True, request_id="scroll-1"):
    client.last_scroll_request_id = request_id
    client.last_scroll_result = {
        "reqId": request_id,
        "action": "SCROLL_FORWARD",
        "direction": kwargs.get("direction"),
        "success": bool(success),
        "actionAttempted": True,
        "explicitTarget": explicit,
        "scrollContainerPath": kwargs.get("container_path") if explicit else None,
    }
    return bool(success)


@pytest.mark.parametrize("value,status", [(True,"SCROLL_CAPABLE"),(False,"SCROLL_NOT_CAPABLE")])
def test_metadata_reaches_capability(value,status):
    assert capability([],dict(canScrollDown=value))["status"] == status


def test_absent_metadata_is_unknown():
    assert capability([],{})["status"] == "SCROLL_CAPABILITY_UNKNOWN"


def test_flattened_scrollable_is_distinct_source():
    c=capability([node(scrollable=True)],{})
    assert c["source"] == "flattened_node"
    assert c["can_scroll_forward"] is None  # Scrollable alone does not prove direction/end.


def test_xml_fallback_is_distinct_source():
    c=capability([],{},raw_xml='<hierarchy><node class="android.widget.GridView" scrollable="true" bounds="[0,0][100,100]"/></hierarchy>')
    assert c["source"] == "raw_xml_fallback"


@pytest.mark.parametrize("cls,kind",[("RecyclerView","VERTICAL_CONTENT_SCROLL"),("GridView","VERTICAL_CONTENT_SCROLL"),("HorizontalScrollView","HORIZONTAL_TAB_SCROLL"),("ViewPager","PAGER"),("Custom","UNKNOWN_SCROLL_CONTAINER")])
def test_container_classes(cls,kind):
    assert classify_container(cls) == kind


def test_dynamic_labels_do_not_change_viewport():
    assert viewport([node(label="12:00")],"s")["signature"] == viewport([node(label="12:01")],"s")["signature"]


def test_identical_viewport_is_no_change():
    v=viewport([node()],"s")
    assert transition(v,v,True,capability([],dict(canScrollDown=True)))["status"] == "SCROLL_NO_CHANGE"


def test_new_and_persisted_diff():
    before=viewport([node("a"),node("b")],"s")
    after=viewport([node("b"),node("c")],"s")
    t=transition(before,after,True,capability([],dict(canScrollDown=True)))
    assert t["status"] == "SCROLL_MOVED"
    assert (t["persisted_count"],t["new_count"],t["disappeared_count"]) == (1,1,1)


def test_duplicate_reappearance_not_new():
    v=viewport([node(),node()],"s")
    t=transition(v,v,True,capability([],dict(canScrollDown=False)))
    assert t["new_count"] == 0 and t["viewport_end"]


def test_unknown_unchanged_is_incomplete():
    v=viewport([node()],"s")
    assert transition(v,v,True,capability([],{}))["termination_reason"] == "scroll_unverified"
    assert termination_status("scroll_unverified") == "INCOMPLETE_SCROLL_UNVERIFIED"


def test_action_failure_is_error():
    v=viewport([node()],"s")
    assert transition(v,v,False,capability([],{}))["termination_reason"] == "scroll_error"
    assert termination_status("scroll_error") == "INCOMPLETE_SCROLL_ERROR"


def test_horizontal_does_not_become_vertical():
    c=capability([],dict(canScrollDown=False),[node(cls="HorizontalScrollView",scroll_forward_supported=True)])
    assert c["container"] is None and c["can_scroll_forward"] is False


def test_contradictory_capability_is_unknown():
    c=capability([],dict(canScrollDown=False),[node(scroll_forward_supported=True)])
    assert c["status"] == "SCROLL_CAPABILITY_UNKNOWN" and c["contradictory"]


@pytest.mark.parametrize("success,status", [(True,"SCROLL_NO_CHANGE"),(False,"SCROLL_FAILED")])
def test_verified_scroll_always_redumps(monkeypatch, success, status):
    from tb_runner import scroll_reliability as sr
    class Client:
        last_dump_metadata = {"canScrollDown": True}
        last_scroll_capabilities = [node("list", path="0.1", scroll_forward_supported=True)]
        calls = 0
        def dump_tree(self, **kwargs):
            self.calls += 1
            assert kwargs["include_scroll_capabilities"]
            return [node()]
        def scroll(self, **kwargs):
            self.scroll_kwargs = kwargs
            return _record_targeted_scroll(self, kwargs, success)
    monkeypatch.setattr(sr.time,"sleep",lambda _:None)
    client=Client()
    result,after=sr.verified_scroll(client,"d","s",1)
    assert client.calls == 2 and after["viewport"]["valid"]
    assert client.scroll_kwargs["container_path"] == "0.1"
    assert client.scroll_kwargs["container_bounds"] == "0,0,100,100"
    assert "accessibility_fallback" not in client.scroll_kwargs
    assert result["status"] == status


def test_verified_target_and_saved_after_dump(monkeypatch,tmp_path):
    from tb_runner import scroll_reliability as sr
    class Client:
        last_dump_metadata = {"canScrollDown": True}
        last_scroll_capabilities = [node(path="0.1",scroll_forward_supported=True)]
        def dump_tree(self, **kwargs):
            return [node()]
        def scroll(self, **kwargs):
            self.target=kwargs
            return _record_targeted_scroll(self, kwargs)
    monkeypatch.setattr(sr.time,"sleep",lambda _:None)
    client=Client();result,_=sr.verified_scroll(client,"d","s",1,output_base_dir=tmp_path)
    assert client.target["container_path"] == "0.1"
    assert client.target["container_bounds"] == "0,0,100,100"
    assert "accessibility_fallback" not in client.target
    from pathlib import Path
    assert Path(result["after_dump_path"]).is_file()


def test_global_capability_without_a_current_owner_does_not_dispatch():
    from tb_runner import scroll_reliability as sr

    class Client:
        last_dump_metadata = {"canScrollDown": True}
        last_scroll_capabilities = []

        def __init__(self):
            self.scroll_calls = []

        def dump_tree(self, **_kwargs):
            # Global capability can exist without any current owner evidence.
            return [node(cls="android.view.View", scrollable=True, actions=[4096])]

        def scroll(self, **kwargs):
            self.scroll_calls.append(kwargs)
            raise AssertionError("unowned fallback scroll must not reach dispatch")

    client = Client()
    before = sr.capture(client, "d", "s", step_index=27)
    assert before["capability"]["status"] == "SCROLL_CAPABLE"
    assert before["capability"]["axis"] == "UNKNOWN"
    assert before["capability"]["container"] is None
    assert before["capability"]["containers"] == []

    result, after = sr.verified_scroll(client, "d", "s", 27, before=before)

    assert client.scroll_calls == []
    assert after is before
    assert result["status"] == "SCROLL_BLOCKED"
    assert result["action_state"] == "SCROLL_NOT_DISPATCHED"
    assert result["action_result"]["actionAttempted"] is False
    assert result["action_target"]["mode"] == "UNRESOLVED_CONTAINER"
    assert result["termination_reason"] == "scroll_owner_unresolved"


def test_unknown_axis_container_is_not_sent_through_accessibility_fallback():
    from tb_runner import scroll_reliability as sr

    class Client:
        last_dump_metadata = {"canScrollDown": True}
        last_scroll_capabilities = [node("custom", path="0.1", cls="CustomScrollNode",
                                         scrollable=True, scroll_forward_supported=True)]

        def __init__(self):
            self.scroll_calls = []

        def dump_tree(self, **_kwargs):
            return [node()]

        def scroll(self, **kwargs):
            self.scroll_calls.append(kwargs)
            raise AssertionError("unknown-axis owner must not be dispatched")

    client = Client()
    before = sr.capture(client, "d", "s")
    assert before["capability"]["container"] is None
    assert before["capability"]["unknown_axis_containers"] == 1
    result, _after = sr.verified_scroll(client, "d", "s", 1, before=before)

    assert client.scroll_calls == []
    assert result["status"] == "SCROLL_BLOCKED"
    assert result["action_result"]["actionAttempted"] is False


def test_successful_unowned_helper_fallback_is_not_accepted_as_scroll_progress(monkeypatch):
    from tb_runner import scroll_reliability as sr

    class Client:
        last_dump_metadata = {"canScrollDown": True}
        last_scroll_capabilities = [node("list", path="0.1", scroll_forward_supported=True)]

        def __init__(self):
            self.reads = 0

        def dump_tree(self, **_kwargs):
            self.reads += 1
            return [node("before" if self.reads == 1 else "after")]

        def scroll(self, **kwargs):
            return _record_targeted_scroll(self, kwargs, True, explicit=False)

    logs = []
    monkeypatch.setattr(sr, "log", lambda message: logs.append(message))
    monkeypatch.setattr(sr.time, "sleep", lambda _seconds: None)
    client = Client()

    result, _after = sr.verified_scroll(client, "d", "s", 27)

    assert result["viewport_changed"] is True
    assert result["new_count"] == 1
    assert result["status"] == "SCROLL_UNVERIFIED"
    assert result["termination_reason"] == "scroll_owner_unverified"
    assert result["target_dispatch_verified"] is False
    assert result["observed_action_success"] is True
    assert result["action_success"] is False
    assert any(message.startswith("PHASE6F_ACCEPTANCE_BLOCKER ") for message in logs)


def test_owner_without_targeted_client_contract_does_not_dispatch(monkeypatch):
    from tb_runner import scroll_reliability as sr

    class Client:
        last_dump_metadata = {"canScrollDown": True}
        last_scroll_capabilities = [node("list", path="0.1", scroll_forward_supported=True)]

        def dump_tree(self, **_kwargs):
            return [node()]

        def scroll(self, dev, direction):
            raise AssertionError("path-less client dispatch must not run")

    monkeypatch.setattr(sr.time, "sleep", lambda _seconds: None)
    client = Client()
    before = sr.capture(client, "d", "s")
    result, _after = sr.verified_scroll(client, "d", "s", 1, before=before)

    assert result["status"] == "SCROLL_BLOCKED"
    assert result["action_result"]["reason"] == "targeted_scroll_dispatch_unsupported"


def test_resolved_phase6e_owner_is_dispatched_explicitly_when_legacy_target_is_absent(monkeypatch):
    from tb_runner import scroll_reliability as sr

    class Client:
        last_dump_metadata = {"canScrollDown": True}
        last_scroll_capabilities = []

        def __init__(self):
            self.scroll_kwargs = None

        def dump_tree(self, **_kwargs):
            return [node()]

        def scroll(self, **kwargs):
            self.scroll_kwargs = kwargs
            return _record_targeted_scroll(self, kwargs)

    monkeypatch.setattr(sr.time, "sleep", lambda _seconds: None)
    client = Client()
    before = {"nodes": [node()], "capability": {"can_scroll_forward": True,
              "vertical_can_scroll_forward": True, "contradictory": False, "container": None,
              "containers": []}, "viewport": sr.viewport([node()], "s")}
    resolved_owner = {"status": "RESOLVED", "identity": "owner-1", "path": "0.1", "bounds": "0,0,100,100",
                      "axis": "VERTICAL", "state": {"scrollable": True,
                      "visible": True, "enabled": True}}

    sr.verified_scroll(client, "d", "s", 1, before=before, resolved_owner=resolved_owner)

    assert client.scroll_kwargs["container_path"] == "0.1"
    assert client.scroll_kwargs["container_bounds"] == "0,0,100,100"
    assert "accessibility_fallback" not in client.scroll_kwargs


def test_failed_dump_does_not_reuse_stale_metadata():
    from talkback_lib import A11yAdbClient
    client=object.__new__(A11yAdbClient)
    client.last_dump_metadata={"canScrollDown":True}
    client.check_helper_status=lambda **kwargs:False
    assert client.dump_tree() == []
    assert client.last_dump_metadata == {} and client.last_scroll_capabilities == []


def test_false_metadata_overrides_flattened_hint():
    c=capability([node(scrollable=True)],{"canScrollDown":False})
    assert c["source"] == "helper_metadata" and c["can_scroll_forward"] is False


def test_invisible_container_not_targeted():
    c=capability([],{},[node(isVisibleToUser=False,scroll_forward_supported=True)])
    assert c["container"] is None


def test_same_resource_different_bounds_are_distinct():
    assert viewport([node(),node(bounds="0,100,100,200")],"s")["count"] == 2


def test_empty_dump_cannot_prove_end():
    v=viewport([],"s")
    assert transition(v,v,True,capability([],{"canScrollDown":False}))["termination_reason"] == "scroll_unverified"


def test_non_scrollable_decoration_is_not_target():
    c=capability([],{},[node("decoration",bounds="0,0,1000,1000",isScrollable=False),node("grid",scroll_forward_supported=True,isScrollable=True)])
    assert c["container"]["viewIdResourceName"] == "grid"


def test_true_metadata_without_rich_forward_action_is_contradictory():
    c=capability([],{"canScrollDown":True},[node(isScrollable=True,scroll_forward_supported=False)])
    assert c["contradictory"] and c["can_scroll_forward"] is None


def test_reappeared_instance_not_counted_as_newly_observed(monkeypatch):
    from tb_runner import scroll_reliability as sr
    class Client:
        last_dump_metadata = {"canScrollDown":True}
        last_scroll_capabilities = [node("list", path="0.1", scroll_forward_supported=True)]
        remaining=[[node("b")],[node("a")]]
        def dump_tree(self,**kwargs): return self.remaining.pop(0)
        def scroll(self,**kwargs): return _record_targeted_scroll(self,kwargs)
    monkeypatch.setattr(sr.time,"sleep",lambda _:None)
    client=Client();before=sr.capture(client,"d","s",nodes=[node("a")])
    first,after=sr.verified_scroll(client,"d","s",1,before=before)
    second,_=sr.verified_scroll(client,"d","s",2,before=after)
    assert first["newly_observed_count"] == 1
    assert second["new_count"] == 1 and second["newly_observed_count"] == 0
    assert len(second["reappeared"]) == 1


def _reliable_snapshot(step):
    candidate = node(
        "same-card",
        f"10,{step * 100},310,{step * 100 + 80}",
        f"Item {step}",
        cls="android.widget.Button",
    )
    scroll_container = {
        "className": "android.widget.ScrollView",
        "viewIdResourceName": "app:id/list",
        "boundsInScreen": {"l": 0, "t": 0, "r": 400, "b": 1000},
        "scrollable": True,
        "enabled": True,
        "visibleToUser": True,
        "actions": [16908346],
        "children": [],
    }
    root = {
        "className": "android.widget.FrameLayout",
        "viewIdResourceName": "app:id/root",
        "boundsInScreen": {"l": 0, "t": 0, "r": 400, "b": 1000},
        "children": [scroll_container],
    }
    raw = {
        "success": True,
        "windows": [{"focused": True, "active": True, "root": root}],
    }
    return type("ReliableSnapshot", (), {"candidates": [candidate], "raw_hierarchy": raw})()


def test_multistep_scroll_uses_three_same_snapshot_reliable_candidate_reads(monkeypatch):
    from tb_runner import scroll_reliability as sr

    class Client:
        last_dump_metadata = {"canScrollDown": True, "transportMode": "RELIABLE_FILE_PFD"}
        last_scroll_capabilities = [node("list", bounds="0,0,400,1000", path="0.1",
                                         scroll_down_supported=True)]

        def __init__(self):
            self.reads = 0
            self.legacy_reads = 0

        def get_traversal_candidate_snapshot(self, **_kwargs):
            self.reads += 1
            return _reliable_snapshot(self.reads)

        def dump_tree(self, **_kwargs):
            self.legacy_reads += 1
            raise AssertionError("authoritative legacy hierarchy read")

        def scroll(self, **_kwargs):
            return _record_targeted_scroll(self, _kwargs)

    monkeypatch.setattr(sr.time, "sleep", lambda _seconds: None)
    client = Client()
    before = sr.capture(client, "device", "scenario", step_index=0)
    first, after_first = sr.verified_scroll(client, "device", "scenario", 1, before=before)
    second, after_second = sr.verified_scroll(client, "device", "scenario", 2, before=after_first)

    assert first["status"] == second["status"] == "SCROLL_MOVED"
    assert client.reads == 3
    assert client.legacy_reads == 0
    assert after_second["nodes"][0]["text"] == "Item 3"


def test_reliable_scroll_failure_after_success_stays_incomplete_without_legacy_rescue(monkeypatch):
    from tb_runner import scroll_reliability as sr

    class Client:
        last_dump_metadata = {"canScrollDown": True, "transportMode": "RELIABLE_FILE_PFD"}
        last_scroll_capabilities = [node("list", bounds="0,0,400,1000", path="0.1",
                                         scroll_down_supported=True)]

        def __init__(self):
            self.reads = 0
            self.legacy_reads = 0

        def get_traversal_candidate_snapshot(self, **_kwargs):
            self.reads += 1
            if self.reads == 3:
                raise RuntimeError("PFD_READ_FAILED")
            return _reliable_snapshot(self.reads)

        def dump_tree(self, **_kwargs):
            self.legacy_reads += 1
            raise AssertionError("legacy rescue must remain unused")

        def scroll(self, **_kwargs):
            return _record_targeted_scroll(self, _kwargs)

    monkeypatch.setattr(sr.time, "sleep", lambda _seconds: None)
    client = Client()
    before = sr.capture(client, "device", "scenario", step_index=0)
    success, after_success = sr.verified_scroll(client, "device", "scenario", 1, before=before)
    failed, after_failure = sr.verified_scroll(client, "device", "scenario", 2, before=after_success)

    assert success["status"] == "SCROLL_MOVED"
    assert failed["termination_reason"] == "scroll_unverified"
    assert after_failure["nodes"] == []
    assert after_failure["viewport"]["valid"] is False
    assert client.reads == 3
    assert client.legacy_reads == 0
