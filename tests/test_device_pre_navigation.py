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
        self.scroll_to_top_calls = []
        self.last_target_action_result = {}

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


def test_enter_device_card_plugin_opens_water_leak_after_bounded_scroll(monkeypatch):
    client = DummyDeviceClient([
        [_all_devices(), _device_card("연기 감지 안 됨", 42, 628)],
        [_device_card("누수 물기 없음", 561, 628)],
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
    assert len(client.scroll_calls) == 1
    assert client.tap_xy_adb_calls[-1]["x"] == 799


def test_enter_device_card_plugin_returns_failure_for_missing_target_after_bound(monkeypatch):
    client = DummyDeviceClient([[_all_devices(), _device_card("연기 감지 안 됨", 42, 628)]])
    client.scroll = lambda **kwargs: False
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
    assert reason == "bounded_scroll_exhausted"


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
