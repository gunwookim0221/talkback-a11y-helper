import pytest
from tb_runner import device_tab_logic

def _node(label: str, resource_id: str, class_name: str = "android.widget.TextView", bounds: str = "[0,0][100,100]", visible: bool = True, **kwargs):
    node = {
        "text": label,
        "resourceId": resource_id,
        "className": class_name,
        "boundsInScreen": bounds,
        "isVisibleToUser": visible,
        "clickable": True,
    }
    node.update(kwargs)
    return node

def test_find_collapsed_room_sections_ignores_device_cards():
    nodes = [
        _node("Cam 360 접힘", "com.samsung.android.oneconnect:id/device_card_camera", "android.view.ViewGroup"),
        _node("Smoke Sensor 펼쳐짐", "com.samsung.android.oneconnect:id/device_card", "android.view.ViewGroup"),
        _node("거실 접힘", "com.samsung.android.oneconnect:id/room_header", "android.widget.TextView"),
    ]
    sections = device_tab_logic.find_collapsed_room_sections(nodes)
    assert len(sections) == 1
    assert sections[0]["label"] == "거실 접힘"

def test_find_collapsed_room_sections_ignores_expanded_sections():
    nodes = [
        _node("Expanded c2c", "com.samsung.android.oneconnect:id/room_header", "android.widget.TextView"),
        _node("Expanded GHM", "com.samsung.android.oneconnect:id/room_header", "android.widget.TextView"),
        _node("Collapsed c2c", "com.samsung.android.oneconnect:id/room_header", "android.widget.TextView"),
    ]
    sections = device_tab_logic.find_collapsed_room_sections(nodes)
    assert len(sections) == 1
    assert sections[0]["label"] == "Collapsed c2c"
