"""Reproduce the entry geometry and parent ownership seen in Korean Full32."""
from types import SimpleNamespace

import pytest

from tb_runner import collection_flow
from tb_runner.scenario_config import TAB_CONFIGS


def node(label="", rid="", bounds="0,0,1080,2640", *, clickable=False, children=None):
    return {
        "text": label, "contentDescription": "", "viewIdResourceName": rid,
        "className": "android.widget.FrameLayout", "boundsInScreen": bounds,
        "visibleToUser": True, "clickable": clickable, "focusable": True,
        "effectiveClickable": clickable, "children": children or [],
    }


def chrome():
    return [
        node(rid="com.samsung.android.oneconnect:id/tab_title", bounds="168,136,732,256", clickable=True),
        node(rid="com.samsung.android.oneconnect:id/home_button_container", bounds="36,124,168,268", clickable=True),
        node(rid="com.samsung.android.oneconnect:id/bottom_navigation", bounds="60,2304,1020,2472"),
    ]


def run_entry(monkeypatch, scenario, pages):
    cfg = next(c for c in TAB_CONFIGS if c["scenario_id"] == scenario)
    page_iter = iter(pages)
    taps, scrolls = [], []
    client = SimpleNamespace(
        scroll=lambda dev, direction: scrolls.append(direction) or True,
        tap_xy_adb=lambda dev, x, y: taps.append((x, y)) or True,
    )
    monkeypatch.setattr(collection_flow, "_load_scrolltouch_xml_nodes", lambda **kw: (next(page_iter), "ok"))
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **kw: (True, "plugin_open_verified"))
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    result = collection_flow._run_xml_scroll_search_tap(
        client, "SERIAL", tab_cfg=cfg, target=cfg["pre_navigation"][0]["target"],
        type_="a", max_scroll_search_steps=2, step_wait_seconds=.2, transition_fast_path=False,
    )
    return result, taps, scrolls


@pytest.mark.parametrize("scenario,label,bounds,expected_y", [
    ("life_air_care_plugin", "에어 케어", "30,2054,1050,2558", 2179),
    ("life_energy_plugin", "에너지", "30,1903,1050,2407", 2103),
])
def test_partly_bottom_obstructed_card_uses_safe_visible_region(monkeypatch, scenario, label, bounds, expected_y):
    result, taps, scrolls = run_entry(monkeypatch, scenario, [[node(label, bounds=bounds, clickable=True), *chrome()]])
    assert result == (True, "xml_entry_success")
    assert taps == [(540, expected_y)]
    assert scrolls == []
    assert taps[0][1] < 2304


def test_air_care_thin_top_strip_is_repositioned_without_tapping_room_menu(monkeypatch):
    result, taps, scrolls = run_entry(monkeypatch, "life_air_care_plugin", [
        [node("에어 케어", bounds="30,0,1050,287", clickable=True), *chrome()],
        [node("에어 케어", bounds="30,1104,1050,1608", clickable=True), *chrome()],
    ])
    assert result == (True, "xml_entry_success")
    assert scrolls == ["up"]
    assert taps == [(540, 1356)]


def test_energy_top_card_tap_avoids_fixed_header(monkeypatch):
    result, taps, scrolls = run_entry(monkeypatch, "life_energy_plugin", [
        [node("에너지", bounds="30,0,1050,422", clickable=True), *chrome()],
    ])
    assert result == (True, "xml_entry_success")
    assert taps == [(540, 345)]
    assert scrolls == []


def test_find_actionable_map_owns_entry_instead_of_promoting_to_recycler(monkeypatch):
    map_node = node(rid="com.samsung.android.oneconnect:id/map_area", bounds="30,771,1050,1125", clickable=True)
    map_node["contentDescription"] = "파인드, 현재 폰, 최근 위치 확인: 4시간 전"
    recycler = node(rid="com.samsung.android.oneconnect:id/recycler_view", children=[map_node])
    recycler["className"] = "android.widget.GridView"
    result, taps, scrolls = run_entry(monkeypatch, "life_find_plugin", [[recycler, *chrome()]])
    assert result == (True, "xml_entry_success")
    assert taps == [(540, 948)]
    assert scrolls == []


def test_fully_obstructed_card_is_not_made_eligible():
    bounds, reason = collection_flow._xml_entry_candidate_tap_bounds((30,2437,1050,2640), chrome())
    assert bounds is None
    assert reason.endswith("bottom_navigation")


def test_other_plugins_retain_original_bottom_obstruction_contract(monkeypatch):
    result, taps, scrolls = run_entry(monkeypatch, "life_pet_care_plugin", [
        [node("펫 케어", bounds="30,2054,1050,2558", clickable=True), *chrome()],
        [node("펫 케어", bounds="30,1104,1050,1608", clickable=True), *chrome()],
    ])
    assert result == (True, "xml_entry_success")
    assert scrolls == ["down"]
    assert taps == [(540, 1356)]
