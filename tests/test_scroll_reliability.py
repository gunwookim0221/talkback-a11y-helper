import pytest
from tb_runner.scroll_reliability import capability, classify_container, viewport, transition
from tb_runner.traversal_reliability import termination_status


def node(rid="card", bounds="0,0,100,100", label="On", cls="android.widget.GridView", **extra):
    return dict(viewIdResourceName=rid, boundsInScreen=bounds, text=label, className=cls, **extra)


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
        last_scroll_capabilities = []
        calls = 0
        def dump_tree(self, **kwargs):
            self.calls += 1
            assert kwargs["include_scroll_capabilities"]
            return [node()]
        def scroll(self, dev, direction):
            return success
    monkeypatch.setattr(sr.time,"sleep",lambda _:None)
    client=Client()
    result,after=sr.verified_scroll(client,"d","s",1)
    assert client.calls == 2 and after["viewport"]["valid"]
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
            return True
    monkeypatch.setattr(sr.time,"sleep",lambda _:None)
    client=Client();result,_=sr.verified_scroll(client,"d","s",1,output_base_dir=tmp_path)
    assert client.target["container_path"] == "0.1"
    assert client.target["container_bounds"] == "0,0,100,100"
    from pathlib import Path
    assert Path(result["after_dump_path"]).is_file()


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
        last_scroll_capabilities = []
        remaining=[[node("b")],[node("a")]]
        def dump_tree(self,**kwargs): return self.remaining.pop(0)
        def scroll(self,**kwargs): return True
    monkeypatch.setattr(sr.time,"sleep",lambda _:None)
    client=Client();before=sr.capture(client,"d","s",nodes=[node("a")])
    first,after=sr.verified_scroll(client,"d","s",1,before=before)
    second,_=sr.verified_scroll(client,"d","s",2,before=after)
    assert first["newly_observed_count"] == 1
    assert second["new_count"] == 1 and second["newly_observed_count"] == 0
    assert len(second["reappeared"]) == 1
