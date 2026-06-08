from types import SimpleNamespace

from tb_runner import popup_handler


class _Client:
    def __init__(self):
        self.tap_xy_adb_calls = []
        self.touch_calls = []

    def tap_xy_adb(self, **kwargs):
        self.tap_xy_adb_calls.append(kwargs)
        return True

    def touch(self, **kwargs):
        self.touch_calls.append(kwargs)
        return True


def _node(label, *, clickable=False, class_name="android.widget.TextView", bounds="10,10,100,80", resource_id=""):
    return {
        "text": label,
        "contentDescription": label,
        "viewIdResourceName": resource_id,
        "className": class_name,
        "clickable": clickable,
        "focusable": clickable,
        "effectiveClickable": clickable,
        "visibleToUser": True,
        "boundsInScreen": bounds,
        "children": [],
    }


def _dialog_row(title, button, *, button_class="android.widget.Button"):
    return {
        "focus_node": _node(button, clickable=True, class_name=button_class, bounds="420,1760,660,1860"),
        "dump_tree_nodes": [
            {
                "className": "android.app.Dialog",
                "boundsInScreen": "80,720,1000,1900",
                "visibleToUser": True,
                "children": [
                    _node(title, bounds="120,820,900,920"),
                    _node("Some popup body", bounds="120,940,900,1120"),
                    _node(button, clickable=True, class_name=button_class, bounds="420,1760,660,1860"),
                ],
            }
        ],
    }


def _samsung_account_popup_row():
    return {
        "focus_node": _node(
            "Later",
            clickable=True,
            class_name="android.widget.Button",
            bounds="120,1760,360,1860",
            resource_id="android:id/button3",
        ),
        "dump_tree_nodes": [
            {
                "className": "android.app.Dialog",
                "boundsInScreen": "80,720,1000,1900",
                "visibleToUser": True,
                "children": [
                    _node(
                        "Protect your Samsung account",
                        bounds="120,820,900,920",
                        resource_id="android:id/alertTitle",
                    ),
                    _node(
                        "Set up two-step verification to keep your account safe and secure, even if someone has your password.",
                        bounds="120,940,900,1120",
                        resource_id="android:id/message",
                    ),
                    _node(
                        "Later",
                        clickable=True,
                        class_name="android.widget.Button",
                        bounds="120,1760,360,1860",
                        resource_id="android:id/button3",
                    ),
                    _node(
                        "Set up now",
                        clickable=True,
                        class_name="android.widget.Button",
                        bounds="700,1760,940,1860",
                        resource_id="android:id/button1",
                    ),
                ],
            }
        ],
    }


def test_korean_policy_update_popup_with_confirm_is_safe():
    candidate = popup_handler.detect_popup_candidate(_dialog_row("클립 공유 정책 업데이트", "확인"))

    assert candidate.detected is True
    assert candidate.reason == "modal_candidate"
    assert candidate.title == "클립 공유 정책 업데이트"
    assert [button["label"] for button in candidate.safe_buttons] == ["확인", "확인"]


def test_dangerous_delete_popup_is_blocked():
    candidate = popup_handler.detect_popup_candidate(_dialog_row("Delete device", "Delete"))

    assert candidate.detected is False
    assert candidate.reason == "dangerous_action_present"
    assert candidate.dangerous_buttons


def test_permission_allow_popup_is_blocked_in_v1():
    candidate = popup_handler.detect_popup_candidate(_dialog_row("권한 요청", "허용"))

    assert candidate.detected is False
    assert candidate.reason == "dangerous_action_present"


def test_notice_close_popup_is_safe():
    candidate = popup_handler.detect_popup_candidate(_dialog_row("공지사항", "닫기"))

    assert candidate.detected is True
    assert [button["label"] for button in candidate.safe_buttons] == ["닫기", "닫기"]


def test_whats_new_got_it_popup_is_safe():
    candidate = popup_handler.detect_popup_candidate(_dialog_row("What's new", "Got it"))

    assert candidate.detected is True
    assert [button["label"] for button in candidate.safe_buttons] == ["Got it", "Got it"]


def test_general_card_with_safe_label_is_not_popup_without_modal_evidence():
    row = {
        "focus_node": _node("OK", clickable=True, class_name="android.widget.Button", bounds="80,600,280,720"),
        "dump_tree_nodes": [
            _node("Camera", clickable=True, class_name="android.view.ViewGroup", bounds="40,400,1040,620"),
            _node("OK", clickable=True, class_name="android.widget.Button", bounds="80,600,280,720"),
        ],
    }

    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.detected is False
    assert candidate.reason == "missing_modal_evidence"


def test_bottom_nav_safe_like_label_is_ignored():
    row = {
        "focus_node": _node("Menu", clickable=True, resource_id="com.samsung.android.oneconnect:id/menu_more"),
        "dump_tree_nodes": [
            _node("Home", clickable=True, resource_id="com.samsung.android.oneconnect:id/menu_favorites"),
            _node("Menu", clickable=True, resource_id="com.samsung.android.oneconnect:id/menu_more"),
        ],
    }

    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.detected is False
    assert candidate.reason == "no_safe_action"


def test_popup_requires_limited_actionable_count():
    row = _dialog_row("공지사항", "확인")
    dialog = row["dump_tree_nodes"][0]
    for index in range(6):
        dialog["children"].append(_node(f"Extra {index}", clickable=True, bounds=f"10,{100 + index * 80},120,{150 + index * 80}"))

    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.detected is False
    assert candidate.reason == "too_many_actionable_candidates"


def test_tap_popup_button_prefers_bounds_tap():
    client = _Client()
    candidate = popup_handler.detect_popup_candidate(_dialog_row("공지사항", "확인"))

    assert popup_handler.tap_popup_button(client, "SERIAL", candidate.safe_buttons[0]) is True
    assert client.tap_xy_adb_calls == [{"dev": "SERIAL", "x": 540, "y": 1810}]
    assert client.touch_calls == []


def test_samsung_account_popup_selects_later_only():
    candidate = popup_handler.detect_popup_candidate(_samsung_account_popup_row())

    assert candidate.detected is True
    assert candidate.popup_kind == "samsung_account_two_step"
    assert [button["label"] for button in candidate.safe_buttons] == ["Later", "Later"]
    assert candidate.dangerous_buttons == []
    assert all(button["label"] != "Set up now" for button in candidate.safe_buttons)


def test_samsung_account_popup_tap_prefers_button3_resource_id():
    client = _Client()
    candidate = popup_handler.detect_popup_candidate(_samsung_account_popup_row())

    assert popup_handler.tap_popup_button(client, "SERIAL", candidate.safe_buttons[0]) is True
    assert client.touch_calls == [{"dev": "SERIAL", "type_": "resourceId", "name": "^android:id/button3$"}]
    assert client.tap_xy_adb_calls == []


def test_non_samsung_popup_without_safe_action_is_noop():
    row = {
        "focus_node": _node("Camera", clickable=True),
        "dump_tree_nodes": [_node("Camera", clickable=True)],
    }

    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.detected is False
    assert candidate.reason == "no_safe_action"
