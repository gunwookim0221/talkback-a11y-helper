import sys
from types import SimpleNamespace

sys.modules.setdefault("pandas", SimpleNamespace(DataFrame=object, ExcelWriter=object))
sys.modules.setdefault("openpyxl", SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None))
sys.modules.setdefault("openpyxl.drawing.image", SimpleNamespace(Image=object))

from tb_runner import collection_flow


class DummyDeviceClient:
    def __init__(self, dump_tree_sequence):
        self.dump_tree_sequence = list(dump_tree_sequence)
        self.tap_xy_adb_calls = []
        self.scroll_calls = []
        self.swipe_calls = []
        self.scroll_to_top_calls = []
        self.last_target_action_result = {}
        self._adb_device = SimpleNamespace(_swipe=self._swipe)

    def dump_tree(self, **_kwargs):
        if self.dump_tree_sequence:
            return self.dump_tree_sequence.pop(0)
        return []

    def tap_xy_adb(self, **kwargs):
        self.tap_xy_adb_calls.append(kwargs)
        return True

    def scroll(self, **kwargs):
        self.scroll_calls.append(kwargs)
        return True

    def _swipe(self, **kwargs):
        self.swipe_calls.append(kwargs)
        return ""

    def scroll_to_top(self, **kwargs):
        self.scroll_to_top_calls.append(kwargs)
        return {"ok": True}


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
):
    return {
        "text": label,
        "contentDescription": label,
        "mergedLabel": label,
        "talkbackLabel": label,
        "className": class_name,
        "viewIdResourceName": rid,
        "boundsInScreen": bounds,
        "clickable": clickable,
        "focusable": focusable,
        "effectiveClickable": effective_clickable,
        "selected": selected,
        "isVisibleToUser": True,
    }


def _device_card(label, left, top):
    return _node(
        label,
        "com.samsung.android.oneconnect:id/device_card",
        {"l": left, "t": top, "r": left + 477, "b": top + 345},
    )


def _assign_room_cta():
    return _node(
        "방 지정하기",
        "com.samsung.android.oneconnect:id/move_devices_button",
        {"l": 216, "t": 2112, "r": 864, "b": 2268},
        class_name="android.widget.TextView",
    )


def _all_devices(label="모든 기기 모든 기기", *, focusable=True):
    return _node(
        label,
        "",
        {"l": 171, "t": 319, "r": 410, "b": 469},
        class_name="android.widget.LinearLayout",
        clickable=not focusable,
        focusable=focusable,
        effective_clickable=not focusable,
    )


def _room_none(label="지정된 방 없음 지정된 방 없음", *, focusable=True):
    return _node(
        label,
        "",
        {"l": 560, "t": 319, "r": 888, "b": 469},
        class_name="android.widget.LinearLayout",
        clickable=not focusable,
        focusable=focusable,
        effective_clickable=not focusable,
    )


def test_enter_device_card_plugin_opens_smoke_card_by_stable_label(monkeypatch):
    client = DummyDeviceClient([[_all_devices(), _device_card("연기 감지 안 됨", 42, 628)]])
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "screen_text"))
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_smoke_sensor_plugin"},
        step={"target_stable_labels": ["연기", "Smoke sensor"]},
        target="연기",
        max_scroll_search_steps=2,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "device_card_opened"
    assert client.tap_xy_adb_calls[-1]["x"] == 280
    assert client.tap_xy_adb_calls[-1]["y"] == 800


def test_enter_device_card_plugin_matches_visible_target_before_room_expand(monkeypatch):
    collapsed_room = _node(
        "접힘 거실 거실",
        "com.samsung.android.oneconnect:id/subheader_card",
        {"l": 42, "t": 520, "r": 1038, "b": 628},
    )
    smoke = _device_card("연기 Clear", 42, 628)
    client = DummyDeviceClient([[_all_devices(), collapsed_room, smoke]])
    logs = []
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "screen_text"))
    monkeypatch.setattr(collection_flow, "log", lambda message, *_args, **_kwargs: logs.append(str(message)))

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_smoke_sensor_plugin"},
        step={"target_stable_labels": ["연기", "Smoke sensor"]},
        target="연기",
        max_scroll_search_steps=2,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "device_card_opened"
    assert len(client.tap_xy_adb_calls) == 1
    assert client.tap_xy_adb_calls[0]["x"] == 280
    assert client.tap_xy_adb_calls[0]["y"] == 800
    assert client.swipe_calls == []
    assert any("phase='before_expand'" in line and "count=1" in line for line in logs)
    assert any("phase='before_expand'" in line and "stable='연기'" in line for line in logs)
    assert any("skipped reason='target_already_visible'" in line for line in logs)


def test_enter_device_card_plugin_opens_water_leak_after_bounded_scroll(monkeypatch):
    scrolled_nodes = [_all_devices(), _room_none(focusable=False), _device_card("누수 물기 없음", 561, 628)]
    client = DummyDeviceClient([
        [_all_devices(), _device_card("연기 감지 안 됨", 42, 628)],
        scrolled_nodes,
        scrolled_nodes,
    ])
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "screen_text"))
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_water_leak_sensor_plugin"},
        step={"target_stable_labels": ["누수", "Water leak sensor"]},
        target="누수",
        max_scroll_search_steps=2,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "device_card_opened"
    assert len(client.scroll_calls) == 0
    assert len(client.swipe_calls) == 1
    assert client.tap_xy_adb_calls[-1]["x"] == 799


def test_enter_device_card_plugin_returns_failure_for_missing_target_after_bound(monkeypatch):
    repeated_nodes = [_all_devices(), _room_none(focusable=False), _device_card("연기 감지 안 됨", 42, 628)]
    client = DummyDeviceClient([repeated_nodes, repeated_nodes, repeated_nodes])
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_water_leak_sensor_plugin"},
        step={"target_stable_labels": ["누수"]},
        target="누수",
        max_scroll_search_steps=2,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is False
    assert reason == "target_not_found"


def test_enter_device_card_plugin_uses_adb_swipe_for_bounded_device_search(monkeypatch):
    scrolled_nodes = [_all_devices(), _room_none(focusable=False), _device_card("누수 물기 없음", 561, 628)]
    client = DummyDeviceClient([
        [_all_devices(), _device_card("연기 감지 안 됨", 42, 628)],
        scrolled_nodes,
        scrolled_nodes,
    ])
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "screen_text"))
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_water_leak_sensor_plugin"},
        step={"target_stable_labels": ["누수"]},
        target="누수",
        max_scroll_search_steps=2,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "device_card_opened"
    assert len(client.swipe_calls) == 1
    assert client.scroll_calls == []


def test_enter_device_card_plugin_fails_when_device_list_scroll_drift_detected(monkeypatch):
    client = DummyDeviceClient([
        [_all_devices(), _device_card("연기 감지 안 됨", 42, 628)],
        [_room_none(), _device_card("누수 물기 없음", 561, 628), _assign_room_cta()],
    ])
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, *_args, **_kwargs: logs.append(str(message)))

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_water_leak_sensor_plugin"},
        step={"target_stable_labels": ["누수"]},
        target="누수",
        max_scroll_search_steps=2,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is False
    assert reason == "device_list_scroll_filter_drift"
    assert len(client.swipe_calls) == 1
    assert any("filter_drift detected" in line for line in logs)


def test_enter_device_card_plugin_marks_exhaustion_after_repeated_inventory_signature(monkeypatch):
    repeated_nodes = [_all_devices(), _room_none(focusable=False), _device_card("연기 감지 안 됨", 42, 628)]
    client = DummyDeviceClient([
        repeated_nodes,
        repeated_nodes,
        repeated_nodes,
        repeated_nodes,
        repeated_nodes,
    ])
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_water_leak_sensor_plugin"},
        step={"target_stable_labels": ["누수"]},
        target="누수",
        max_scroll_search_steps=3,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is False
    assert reason == "bounded_scroll_exhausted"
    assert len(client.swipe_calls) == 2


def test_enter_device_card_plugin_taps_all_devices_and_high_confidence_collapsed_room(monkeypatch):
    all_devices_unselected = _all_devices("All devices All devices", focusable=False)
    all_devices_selected = _all_devices("All devices All devices", focusable=True)
    collapsed_room = _node(
        "접힘 거실 거실",
        "com.samsung.android.oneconnect:id/subheader_card",
        {"l": 42, "t": 520, "r": 1038, "b": 628},
    )
    smoke = _device_card("연기 감지 안 됨", 42, 628)
    client = DummyDeviceClient([
        [all_devices_unselected, collapsed_room],
        [all_devices_selected, collapsed_room],
        [smoke],
    ])
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "screen_text"))
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_smoke_sensor_plugin"},
        step={"target_stable_labels": ["연기"]},
        target="연기",
        max_scroll_search_steps=1,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "device_card_opened"
    assert len(client.tap_xy_adb_calls) == 3
    assert client.tap_xy_adb_calls[0]["x"] == 290
    assert client.tap_xy_adb_calls[1]["x"] == 540
    assert client.tap_xy_adb_calls[2]["x"] == 280


def test_enter_device_card_plugin_retries_all_devices_selection_once(monkeypatch):
    all_devices_unselected = _all_devices("모든 기기 모든 기기", focusable=False)
    room_selected = _room_none()
    all_devices_selected = _all_devices("모든 기기 모든 기기", focusable=True)
    smoke = _device_card("연기 감지 안 됨", 42, 628)
    client = DummyDeviceClient([
        [all_devices_unselected, room_selected],
        [all_devices_unselected, room_selected],
        [all_devices_selected, smoke],
    ])
    logs = []
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "screen_text"))
    monkeypatch.setattr(collection_flow, "log", lambda message, *_args, **_kwargs: logs.append(str(message)))

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_smoke_sensor_plugin"},
        step={"target_stable_labels": ["연기"]},
        target="연기",
        max_scroll_search_steps=1,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "device_card_opened"
    assert len(client.tap_xy_adb_calls) == 3
    assert any("selected_before='지정된 방 없음'" in line for line in logs)
    assert any("retry=1" in line for line in logs)
    assert any("selected_after='모든 기기'" in line for line in logs)


def test_enter_device_card_plugin_fails_when_all_devices_selection_retry_does_not_verify(monkeypatch):
    all_devices_unselected = _all_devices("모든 기기 모든 기기", focusable=False)
    room_selected = _room_none()
    client = DummyDeviceClient([
        [all_devices_unselected, room_selected],
        [all_devices_unselected, room_selected],
        [all_devices_unselected, room_selected],
    ])
    logs = []
    monkeypatch.setattr(collection_flow, "log", lambda message, *_args, **_kwargs: logs.append(str(message)))

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_smoke_sensor_plugin"},
        step={"target_stable_labels": ["연기"]},
        target="연기",
        max_scroll_search_steps=1,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is False
    assert reason == "all_devices_selection_verify_failed"
    assert len(client.tap_xy_adb_calls) == 2
    assert client.scroll_calls == []
    assert any("selection_verify_failed" in line for line in logs)


def test_enter_device_card_plugin_uses_safe_tap_when_card_center_overlaps_cta(monkeypatch):
    card = _node(
        "온습도 센서 진동 감지됨",
        "com.samsung.android.oneconnect:id/device_card",
        {"l": 42, "t": 2068, "r": 519, "b": 2316},
    )
    client = DummyDeviceClient([[_all_devices(), card, _assign_room_cta()]])
    logs = []
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "screen_text"))
    monkeypatch.setattr(collection_flow, "log", lambda message, *_args, **_kwargs: logs.append(str(message)))

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_temperature_humidity_sensor_plugin"},
        step={"target_stable_labels": ["온습도 센서"]},
        target="온습도 센서",
        max_scroll_search_steps=1,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "device_card_opened"
    tap = client.tap_xy_adb_calls[-1]
    assert tap["x"] != 280 or tap["y"] != 2192
    assert 42 < tap["x"] < 519
    assert 2068 < tap["y"] < 2316
    assert not (216 <= tap["x"] <= 864 and 2112 <= tap["y"] <= 2268)
    assert any("[DEVICE_ENTRY][safe_tap]" in line and "strategy='upper" in line for line in logs)


def test_enter_device_card_plugin_fails_when_safe_tap_point_unavailable(monkeypatch):
    card = _node(
        "온습도 센서 진동 감지됨",
        "com.samsung.android.oneconnect:id/device_card",
        {"l": 42, "t": 2068, "r": 519, "b": 2316},
    )
    covered_cta = _node(
        "방 지정하기",
        "com.samsung.android.oneconnect:id/move_devices_button",
        {"l": 0, "t": 2000, "r": 1080, "b": 2400},
        class_name="android.widget.TextView",
    )
    client = DummyDeviceClient([[_all_devices(), card, covered_cta]])
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    ok, reason = collection_flow._run_enter_device_card_plugin(
        client=client,
        dev="SERIAL",
        tab_cfg={"scenario_id": "device_temperature_humidity_sensor_plugin"},
        step={"target_stable_labels": ["온습도 센서"]},
        target="온습도 센서",
        max_scroll_search_steps=1,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is False
    assert reason == "device_card_safe_tap_point_unavailable"
    assert client.tap_xy_adb_calls == []
