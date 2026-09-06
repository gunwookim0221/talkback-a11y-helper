from unittest.mock import Mock

import talkback_lib
from talkback_lib import A11yAdbClient


def _node(label: str, bounds: str) -> dict:
    return {
        "text": label,
        "contentDescription": label,
        "boundsInScreen": bounds,
        "visibleToUser": True,
    }


def test_scroll_to_top_uses_one_accessibility_tree_fallback_after_primary_failure(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    before = [_node("Below", "[0,400][200,520]")]
    after = [_node("Top card", "[0,80][200,200]")]
    client.dump_tree = Mock(side_effect=[before, after])
    client.scroll = Mock(side_effect=[False, True])
    monkeypatch.setattr(talkback_lib.time, "sleep", lambda _seconds: None)

    result = client.scroll_to_top(
        dev="SERIAL",
        max_swipes=3,
        pause=0,
        top_evidence=lambda nodes: {"ok": nodes[0]["text"] == "Top card", "reason": "first_card"},
    )

    assert result["status"] == "VERIFIED_TOP"
    assert client.scroll.call_args_list[0].kwargs.get("accessibility_fallback", False) is False
    assert client.scroll.call_args_list[1].kwargs["accessibility_fallback"] is True


def test_scroll_to_top_fails_closed_when_fallback_does_not_move_or_prove_top(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    nodes = [_node("Below", "[0,400][200,520]")]
    client.dump_tree = Mock(side_effect=[nodes, nodes])
    client.scroll = Mock(side_effect=[False, True])
    monkeypatch.setattr(talkback_lib.time, "sleep", lambda _seconds: None)

    result = client.scroll_to_top(
        dev="SERIAL",
        max_swipes=3,
        pause=0,
        top_evidence=lambda _nodes: False,
    )

    assert result["status"] == "NO_VISIBLE_CHANGE_UNVERIFIED"
    assert result["reached_top"] is False


def test_scroll_to_top_stops_after_primary_and_single_fallback_failure(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    nodes = [_node("Below", "[0,400][200,520]")]
    client.dump_tree = Mock(return_value=nodes)
    client.scroll = Mock(return_value=False)
    monkeypatch.setattr(talkback_lib.time, "sleep", lambda _seconds: None)

    result = client.scroll_to_top(
        dev="SERIAL",
        max_swipes=3,
        pause=0,
        top_evidence=lambda _nodes: False,
    )

    assert result["status"] == "FAILED"
    assert result["reason"] == "scroll_failed"
    assert client.scroll.call_count == 2
