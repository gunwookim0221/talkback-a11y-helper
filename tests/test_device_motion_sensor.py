import pytest
from tb_runner import device_tab_logic
from tb_runner.collection_flow import _perform_device_list_adb_swipe

def _node(
    label,
    rid,
    bounds,
    *,
    class_name="android.view.ViewGroup",
    clickable=True,
    focusable=True,
    effective_clickable=True,
    selected=False,
    checked=False,
    accessibility_focused=False,
    focused=False,
    state_description=None,
    visible=True,
    has_clickable_descendant=False,
    actionable_descendant_resource_id=None,
):
    return {
        "text": label,
        "contentDescription": label,
        "resourceId": rid,
        "boundsInScreen": bounds,
        "className": class_name,
        "clickable": clickable,
        "focusable": focusable,
        "effective_clickable": effective_clickable,
        "selected": selected,
        "checked": checked,
        "accessibilityFocused": accessibility_focused,
        "focused": focused,
        "stateDescription": state_description,
        "visibleToUser": visible,
        "has_clickable_descendant": has_clickable_descendant,
        "actionable_descendant_resource_id": actionable_descendant_resource_id,
    }


def test_motion_sensor_target_matching():
    # 1. "Motion Sensor No motion"
    node1 = _node("Motion Sensor No motion", "com.samsung.android.oneconnect:id/device_card", "[0,100][100,200]")
    stable1 = device_tab_logic.normalize_device_stable_label(node1["contentDescription"])
    assert stable1 == "Motion Sensor"
    
    # 2. "Motion Sensor"
    node2 = _node("Motion Sensor", "com.samsung.android.oneconnect:id/device_card", "[0,100][100,200]")
    stable2 = device_tab_logic.normalize_device_stable_label(node2["contentDescription"])
    assert stable2 == "Motion Sensor"

    # 3. "Motion Sensor Motion" - Ensure "Motion" is not stripped destructively
    node3 = _node("Motion Sensor Motion", "com.samsung.android.oneconnect:id/device_card", "[0,100][100,200]")
    stable3 = device_tab_logic.normalize_device_stable_label(node3["contentDescription"])
    # If "motion" suffix was blindly removed, this would become "Motion Sensor", but we removed "motion"
    # from suffixes. So it stays "Motion Sensor Motion". It shouldn't break the base name.
    assert stable3 == "Motion Sensor Motion"


class MockAdbClient:
    def __init__(self):
        self._adb_device = self
        self.swipes = []

    def _swipe(self, dev, x1, y1, x2, y2, duration_ms):
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        return "OK"

def test_scroll_search_finds_motion_sensor():
    # Cam 360, Motion Sensor, Light above/below
    nodes = [
        _node("Cam 360", "com.samsung.android.oneconnect:id/device_card", "[0,0][1080,500]"),
        _node("Motion Sensor No motion", "com.samsung.android.oneconnect:id/device_card", "[0,500][1080,1000]"),
        _node("Light On", "com.samsung.android.oneconnect:id/device_card", "[0,1000][1080,1500]"),
    ]
    
    client = MockAdbClient()
    success, meta = _perform_device_list_adb_swipe(client, "dev1", nodes=nodes)
    
    assert success is True
    assert meta["y_start"] == int(1500 * 0.82)
    assert meta["y_end"] == int(1500 * 0.38)


def test_device_list_swipe_stays_inside_scrollable_viewport_above_bottom_navigation():
    nodes = [
        _node(
            "",
            "com.samsung.android.oneconnect:id/device_list",
            "[0,180][1248,1775]",
            class_name="androidx.recyclerview.widget.RecyclerView",
        ) | {"scrollable": True},
        _node("Door Lock", "com.samsung.android.oneconnect:id/device_card", "[42,520][606,900]"),
        _node("TV", "com.samsung.android.oneconnect:id/device_card", "[642,520][1206,900]"),
        _node("Devices", "com.samsung.android.oneconnect:id/menu_devices", "[510,1775][740,1933]"),
    ]

    client = MockAdbClient()

    success, meta = _perform_device_list_adb_swipe(client, "fold8", nodes=nodes)

    assert success is True
    assert meta["viewport_before"] == "0,180,1248,1775"
    assert 180 < meta["y_end"] < meta["y_start"] < 1775
    assert meta["bottom_navigation_overlap"] is False
    assert meta["visible_card_count_before"] == 2


def test_device_list_swipe_prefers_scrollable_viewport_that_contains_device_cards():
    nodes = [
        _node("", "com.samsung.android.oneconnect:id/root", "[0,80][1248,1775]", class_name="android.widget.ScrollView") | {"scrollable": True},
        _node("", "com.samsung.android.oneconnect:id/device_list", "[0,400][1248,1650]", class_name="androidx.recyclerview.widget.RecyclerView") | {"scrollable": True},
        _node("Door Lock", "com.samsung.android.oneconnect:id/device_card", "[42,520][606,900]"),
        _node("TV", "com.samsung.android.oneconnect:id/device_card", "[642,520][1206,900]"),
        _node("Devices", "com.samsung.android.oneconnect:id/menu_devices", "[510,1775][740,1933]"),
    ]

    success, meta = _perform_device_list_adb_swipe(MockAdbClient(), "fold8", nodes=nodes)

    assert success is True
    assert meta["viewport_before"] == "0,400,1248,1650"
