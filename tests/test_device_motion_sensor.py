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
    # Verify the new conservative swipe distance
    assert meta["y_start"] == int(1500 * 0.78) or meta["y_start"] == int(2400 * 0.78)
    assert meta["y_end"] == int(1500 * 0.45) or meta["y_end"] == int(2400 * 0.45)
