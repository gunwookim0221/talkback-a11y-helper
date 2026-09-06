import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault(
    "pandas",
    SimpleNamespace(DataFrame=object, ExcelWriter=object, Series=object),
)
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow
from talkback_lib import A11yAdbClient


CARD_ID = "com.samsung.android.oneconnect:id/device_card"
NAME_ID = "com.samsung.android.oneconnect:id/device_name"


def _node(label, rid, bounds, *, clickable=True, focusable=True, effective=True):
    return {
        "text": label,
        "contentDescription": label,
        "mergedLabel": label,
        "className": "android.view.ViewGroup",
        "viewIdResourceName": rid,
        "boundsInScreen": bounds,
        "clickable": clickable,
        "focusable": focusable,
        "effectiveClickable": effective,
        "isVisibleToUser": True,
        "children": [],
    }


def _card(name, bounds=(42, 628, 519, 973), *, clickable=True):
    left, top, right, bottom = bounds
    card = _node(f"{name} Connected", CARD_ID, {"l": left, "t": top, "r": right, "b": bottom}, clickable=clickable, focusable=clickable, effective=clickable)
    card["children"] = [
        _node(
            name,
            NAME_ID,
            {"l": left + 24, "t": top + 24, "r": left + 220, "b": min(bottom - 24, top + 82)},
            clickable=False,
            focusable=False,
            effective=False,
        )
    ]
    return card


def _evidence(cards, *, verified=True, viewport=(0, 0, 1080, 1900)):
    left, top, right, bottom = viewport
    return {
        "verified": verified,
        "path": "0.0.1.0.0",
        "scrollForwardSupported": True,
        "scrollBackwardSupported": False,
        "boundsInScreen": {"l": left, "t": top, "r": right, "b": bottom},
        "cardBounds": [
            {
                "path": f"0.0.1.0.0.{index}",
                "boundsInScreen": card["boundsInScreen"],
                "label": card.get("text"),
            }
            for index, card in enumerate(cards)
        ],
    }


def test_valid_card_inside_verified_collection_is_direct_entry_eligible():
    card = _card("Smoke sensor")
    selected, geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card],
        ["Smoke sensor"],
        collection_evidence=_evidence([card]),
    )

    assert selected is not None
    assert geometry["verified_collection"] is True


def test_missing_flattened_scrollable_bounds_can_use_verified_collection():
    card = _card("Camera")
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card],
        ["Camera"],
        collection_evidence=_evidence([card]),
    )

    assert selected is not None


def test_target_outside_verified_collection_fails_closed():
    card = _card("Camera")
    evidence_card = _card("Other", bounds=(561, 628, 1038, 973))
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card],
        ["Camera"],
        collection_evidence=_evidence([evidence_card]),
    )

    assert selected is None


def test_duplicate_identity_fails_closed():
    first = _card("Camera", bounds=(42, 628, 519, 973))
    second = _card("Camera", bounds=(561, 628, 1038, 973))
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [first, second],
        ["Camera"],
        collection_evidence=_evidence([first, second]),
    )

    assert selected is None


def test_partially_visible_target_fails_closed():
    card = _card("Camera", bounds=(42, 1800, 519, 2200))
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card],
        ["Camera"],
        collection_evidence=_evidence([card], viewport=(0, 0, 1080, 1900)),
    )

    assert selected is None


def test_non_actionable_target_fails_closed():
    card = _card("Camera", clickable=False)
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card],
        ["Camera"],
        collection_evidence=_evidence([card]),
    )

    assert selected is None


def test_stale_or_missing_structural_evidence_fails_closed_without_legacy_bounds():
    card = _card("Camera")
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card],
        ["Camera"],
        collection_evidence=_evidence([card], verified=False),
    )

    assert selected is None


def test_verified_collection_without_card_ownership_fails_closed():
    card = _card("Camera")
    evidence = _evidence([card])
    evidence["cardBounds"] = []
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card],
        ["Camera"],
        collection_evidence=evidence,
    )

    assert selected is None


def test_verified_collection_with_non_containing_card_ownership_fails_closed():
    card = _card("Camera")
    evidence = _evidence([card])
    evidence["cardBounds"][0]["boundsInScreen"] = {"l": 0, "t": 0, "r": 10, "b": 10}
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card],
        ["Camera"],
        collection_evidence=evidence,
    )

    assert selected is None


def test_legacy_scrollable_bounds_remain_compatible():
    card = _card("Camera")
    viewport = _node("", "com.example:id/content_recycler", {"l": 0, "t": 0, "r": 1080, "b": 1900}, clickable=False, focusable=False, effective=False)
    viewport["scrollable"] = True
    selected, _geometry = collection_flow._find_safe_visible_device_card_for_direct_entry(
        [card, viewport],
        ["Camera"],
    )

    assert selected is not None


def test_scroll_to_top_requests_fresh_device_collection_evidence_after_movement(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    before = [{"text": "Below", "boundsInScreen": "0,500,200,700"}]
    after = [{"text": "Smoke sensor", "boundsInScreen": "0,80,200,200"}]
    client.dump_tree = Mock(side_effect=[before, after])
    client.scroll = Mock(side_effect=lambda *args, **kwargs: setattr(client, "last_scroll_result", {"success": True}) or True)
    monkeypatch.setattr("talkback_lib.time.sleep", lambda _seconds: None)

    result = client.scroll_to_top(
        dev="SERIAL",
        max_swipes=1,
        pause=0,
        device_list_normalization=True,
        top_evidence=lambda nodes: {"ok": nodes[0]["text"] == "Smoke sensor", "reason": "anchor"},
    )

    assert result["status"] == "VERIFIED_TOP"
    assert all(call.kwargs.get("include_device_collection") is True for call in client.dump_tree.call_args_list)
    assert client.scroll.call_args.kwargs["device_list_normalization"] is True


def test_unverified_top_handoff_requires_verified_forward_collection():
    result = {
        "ok": False,
        "reached_top": False,
        "status": "TOP_BOUNDARY_UNVERIFIED",
        "reason": "validated_collection_boundary_unverified",
        "evidence": "top_anchor_not_first_visible_card",
    }
    evidence = _evidence([_card("Other")])

    assert collection_flow._can_handoff_unverified_device_top_to_forward_search(result, evidence) is True

    evidence["scrollForwardSupported"] = False
    assert collection_flow._can_handoff_unverified_device_top_to_forward_search(result, evidence) is False

    evidence["scrollForwardSupported"] = True
    evidence["verified"] = False
    assert collection_flow._can_handoff_unverified_device_top_to_forward_search(result, evidence) is False

    evidence["verified"] = True
    result["evidence"] = ""
    assert collection_flow._can_handoff_unverified_device_top_to_forward_search(result, evidence) is False


def test_unverified_top_handoff_reaches_existing_bounded_forward_search(monkeypatch):
    before_card = _card("Other")
    after_card = _card("Door Lock", bounds=(561, 628, 1038, 973))

    def location_node():
        return _node(
            "모든 기기 모든 기기",
            "",
            {"l": 171, "t": 319, "r": 410, "b": 469},
            clickable=False,
            focusable=True,
            effective=False,
        )

    before_nodes = [location_node(), before_card]
    after_nodes = [location_node(), after_card]

    class ForwardHandoffClient:
        def __init__(self):
            self.last_device_collection = {}
            self.last_scroll_result = {}
            self.dump_count = 0
            self.taps = []

        def dump_tree(self, **_kwargs):
            nodes = before_nodes if self.dump_count == 0 else after_nodes
            cards = [before_card] if self.dump_count == 0 else [after_card]
            self.last_device_collection = _evidence(cards)
            self.dump_count += 1
            return nodes

        def scroll_to_top(self, **kwargs):
            kwargs["top_evidence"](before_nodes)
            return {
                "ok": False,
                "reached_top": False,
                "status": "TOP_BOUNDARY_UNVERIFIED",
                "reason": "validated_collection_boundary_unverified",
                "evidence": "top_anchor_not_first_visible_card",
            }

        def scroll(self, **_kwargs):
            self.last_scroll_result = {
                "success": True,
                "action": "SCROLL_FORWARD",
                "actionSupported": True,
                "actionAttempted": True,
                "validatedDeviceCollection": True,
            }
            return True

        def tap_xy_adb(self, **kwargs):
            self.taps.append(kwargs)
            return True

    client = ForwardHandoffClient()
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "screen_text"))
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_door_lock_plugin"},
        step={
            "target_stable_labels": ["Door Lock"],
            "top_anchor_stable_labels": ["Other"],
        },
        target="Door Lock",
        max_scroll_search_steps=2,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "device_card_opened"
    assert len(client.taps) == 1
