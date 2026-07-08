from types import SimpleNamespace

from tb_runner import collection_flow
from tb_runner.overlay_logic import is_overlay_candidate
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.context_verifier import verify_context


def _safe_cfg():
    return next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "home_safe_plugin")


def _safe_card_ko_nodes():
    return [
        {
            "viewIdResourceName": "com.samsung.android.oneconnect:id/favorite_device_card",
            "className": "android.view.ViewGroup",
            "clickable": True,
            "focusable": True,
            "visibleToUser": True,
            "boundsInScreen": "42,1606,519,1951",
            "children": [
                {
                    "viewIdResourceName": "com.samsung.android.oneconnect:id/device_name",
                    "text": "세이프 버튼",
                    "visibleToUser": True,
                    "boundsInScreen": "72,1760,330,1830",
                },
                {
                    "viewIdResourceName": "com.samsung.android.oneconnect:id/device_status",
                    "text": "대기",
                    "visibleToUser": True,
                    "boundsInScreen": "72,1840,180,1900",
                },
                {
                    "viewIdResourceName": "com.samsung.android.oneconnect:id/image_button",
                    "contentDescription": "도움 요청",
                    "className": "android.widget.ImageButton",
                    "clickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "381,1624,501,1744",
                },
            ],
        }
    ]


def _safe_card_en_hidden_label_nodes():
    return [
        {
            "viewIdResourceName": "com.samsung.android.oneconnect:id/favorite_device_card",
            "className": "android.view.ViewGroup",
            "clickable": True,
            "focusable": True,
            "visibleToUser": True,
            "boundsInScreen": "42,2120,519,2316",
            "children": [
                {
                    "viewIdResourceName": "com.samsung.android.oneconnect:id/image_button",
                    "contentDescription": "Ask for help",
                    "className": "android.widget.ImageButton",
                    "clickable": True,
                    "visibleToUser": True,
                    "boundsInScreen": "381,2138,501,2258",
                }
            ],
        }
    ]


class _SafeClient:
    def __init__(self, dumps):
        self.dumps = list(dumps)
        self.tap_xy_adb_calls = []
        self.scroll_calls = []
        self.scroll_to_top_calls = []
        self.last_start_open_summary = {}

    def dump_tree(self, **_kwargs):
        if self.dumps:
            return self.dumps.pop(0)
        return []

    def tap_xy_adb(self, **kwargs):
        self.tap_xy_adb_calls.append(kwargs)
        return True

    def scroll_to_top(self, **kwargs):
        self.scroll_to_top_calls.append(kwargs)
        return {"ok": True}

    def scroll(self, dev, direction, step_=50, time_=1000, bounds_=None):
        self.scroll_calls.append({"dev": dev, "direction": direction, "step": step_, "time": time_, "bounds": bounds_})
        return True


def test_safe_card_discovery_korean_taps_parent_card_not_help_button(monkeypatch):
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "safe"))
    client = _SafeClient([_safe_card_ko_nodes()])

    ok, reason = collection_flow._run_enter_safe_favorite_card(
        client,
        "SERIAL",
        _safe_cfg(),
        {"scroll_to_top": False},
        max_scroll_search_steps=1,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "safe_card_opened"
    assert client.tap_xy_adb_calls
    assert client.tap_xy_adb_calls[0]["x"] < 381


def test_safe_card_discovery_english_hidden_label_uses_ask_for_help_evidence(monkeypatch):
    monkeypatch.setattr(collection_flow, "_confirm_click_focused_transition", lambda **_kwargs: (True, "safe"))
    client = _SafeClient([_safe_card_en_hidden_label_nodes()])

    ok, reason = collection_flow._run_enter_safe_favorite_card(
        client,
        "SERIAL",
        _safe_cfg(),
        {"scroll_to_top": False},
        max_scroll_search_steps=1,
        step_wait_seconds=0,
        transition_fast_path=True,
    )

    assert ok is True
    assert reason == "safe_card_opened"
    assert client.tap_xy_adb_calls[0]["x"] < 381


def test_safe_card_not_found_is_optional_not_available(monkeypatch, tmp_path):
    monkeypatch.setattr(collection_flow, "open_scenario", lambda client, *_args, **_kwargs: False)
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(collection_flow, "_save_focusable_inventory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(collection_flow, "_save_focusable_coverage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(collection_flow, "_maybe_execute_coverage_probe_engine", lambda *_args, **_kwargs: None)
    client = SimpleNamespace(
        last_start_open_summary={
            "entry_contract_reason": "optional_not_available",
            "entry_contract_detail": "safe_optional_not_available",
        },
        last_crash_guard_result={},
    )

    rows = collection_flow.collect_tab_rows(
        client,
        "SERIAL",
        _safe_cfg(),
        [],
        str(tmp_path / "out.xlsx"),
        str(tmp_path),
    )

    assert rows[0]["status"] == "OPTIONAL_NOT_AVAILABLE"
    assert rows[0]["stop_reason"] == "safe_optional_not_available"


def test_safe_internal_identity_context_verifies_korean_main_screen():
    result = verify_context(
        {
            "visible_label": "SmartThings Safe plugin 세이프 버튼 기록 아직 사용 기록이 없습니다 도움 요청",
            "merged_announcement": "",
            "focus_view_id": "android.webkit.WebView",
            "dump_tree_nodes": [],
        },
        _safe_cfg(),
    )

    assert result["ok"] is True


def test_safe_more_options_overlay_policy_allows_menu_and_blocks_remove():
    cfg = _safe_cfg()
    more_row = {
        "visible_label": "More options",
        "normalized_visible_label": "more options",
        "merged_announcement": "More options",
        "focus_view_id": "SafeMain-more-options",
        "focus_bounds": "900,70,1030,190",
        "focus_class_name": "android.widget.Button",
    }
    remove_row = {
        "visible_label": "Remove device",
        "normalized_visible_label": "remove device",
        "merged_announcement": "Remove device",
        "focus_view_id": "menu_remove",
        "focus_class_name": "android.widget.TextView",
    }

    assert collection_flow._is_plugin_screen_top_bar_more_options(more_row, cfg) is True
    assert is_overlay_candidate(more_row, cfg)[0] is True
    assert is_overlay_candidate(remove_row, cfg)[0] is False


def test_safe_dangerous_actions_are_not_overlay_candidates():
    cfg = _safe_cfg()
    for label in ("도움 요청", "Ask for help", "Remove device", "기기 삭제", "삭제"):
        row = {
            "visible_label": label,
            "normalized_visible_label": label.lower(),
            "merged_announcement": label,
            "focus_view_id": "danger",
            "focus_class_name": "android.widget.Button",
        }
        assert is_overlay_candidate(row, cfg)[0] is False

