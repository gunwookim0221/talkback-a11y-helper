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


def _samsung_account_popup_ko_row():
    return {
        "focus_node": _node(
            "나중에",
            clickable=True,
            class_name="android.widget.Button",
            bounds="102,2280,463,2388",
            resource_id="android:id/button3",
        ),
        "dump_tree_nodes": [
            {
                "className": "android.app.Dialog",
                "boundsInScreen": "80,720,1000,2400",
                "visibleToUser": True,
                "children": [
                    _node("삼성 계정을 더 안전하게", bounds="102,1500,978,1600", resource_id="android:id/alertTitle"),
                    _node(
                        "2단계 인증을 설정하면 다른 사람이 내 비밀번호를 알게 되어도 내 계정을 안전하게 보호할 수 있습니다.",
                        bounds="102,1640,978,2040",
                        resource_id="android:id/message",
                    ),
                    _node(
                        "나중에",
                        clickable=True,
                        class_name="android.widget.Button",
                        bounds="102,2280,463,2388",
                        resource_id="android:id/button3",
                    ),
                    _node(
                        "지금 설정하기",
                        clickable=True,
                        class_name="android.widget.Button",
                        bounds="466,2280,978,2388",
                        resource_id="android:id/button1",
                    ),
                ],
            }
        ],
    }


def _generic_later_popup_row():
    return {
        "focus_node": _node(
            "Later",
            clickable=True,
            class_name="android.widget.Button",
            bounds="120,1760,360,1860",
            resource_id="com.example:id/later",
        ),
        "dump_tree_nodes": [
            {
                "className": "android.app.Dialog",
                "boundsInScreen": "80,720,1000,1900",
                "visibleToUser": True,
                "children": [
                    _node("Weekly tips", bounds="120,820,900,920"),
                    _node("See tips next time?", bounds="120,940,900,1120"),
                    _node(
                        "Later",
                        clickable=True,
                        class_name="android.widget.Button",
                        bounds="120,1760,360,1860",
                        resource_id="com.example:id/later",
                    ),
                    _node(
                        "Open now",
                        clickable=True,
                        class_name="android.widget.Button",
                        bounds="700,1760,940,1860",
                        resource_id="com.example:id/open_now",
                    ),
                ],
            }
        ],
    }


def _camera_pip_row():
    def pip(resource, bounds, cls, *, label="", focusable=False, enabled=True):
        return _node(label, clickable=False, class_name=cls, bounds=bounds,
                     resource_id="com.example:id/" + resource) | {
            "contentDescription": label, "focusable": focusable, "enabled": enabled,
            "ancestors": [{"resource_id": "com.example:id/live_overlay_layout", "class_name": "android.view.ViewGroup"}],
        }
    focus = _node("Navigate up", clickable=True, class_name="android.widget.ImageButton", bounds="0,106,180,286") | {
        "accessibilityFocused": True, "enabled": True,
    }
    nodes = [
        _node("talkback test room", class_name="android.widget.TextView", bounds="180,216,912,270"),
        _node("More options", clickable=True, class_name="android.widget.ImageButton", bounds="912,142,1032,262", resource_id="com.example:id/toolbar_more_menu"),
        _node("Flash", clickable=True, class_name="android.widget.ImageButton", bounds="762,316,870,424", resource_id="com.example:id/flash_icon"),
        _node("Camera switch", clickable=True, class_name="android.widget.ImageButton", bounds="882,316,990,424", resource_id="com.example:id/camera_switch_icon"),
        pip("btn_popup_play_parent", "634,721,821,853", "android.widget.LinearLayout"),
        pip("btn_popup_play_frame", "679,739,775,835", "android.widget.FrameLayout", focusable=True, enabled=False),
        pip("btn_popup_play", "694,754,760,820", "android.widget.ImageButton", label="PIP", focusable=True),
        _node("Screen capture", clickable=True, class_name="android.widget.ImageButton", bounds="117,739,213,835", resource_id="com.example:id/btn_capture") | {"enabled": True},
    ]
    return dict(focus_node=focus, dump_tree_nodes=nodes, display_bounds=[0, 0, 1080, 2640],
        package_name="com.example", activity_name="com.example.CameraActivity", context_source="window_current_focus",
        window_evidence=dict(window_count=3, focused_window_type="BASE_APPLICATION",
            focused_window_component="com.example.CameraActivity", focused_activity_matches=True,
            focused_window_is_dialog=False))


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


def test_korean_samsung_account_popup_selects_later_only():
    candidate = popup_handler.detect_popup_candidate(_samsung_account_popup_ko_row())

    assert candidate.detected is True
    assert candidate.popup_kind == "samsung_account_two_step"
    assert [button["label"] for button in candidate.safe_buttons] == ["나중에", "나중에"]
    assert all(button["label"] != "지금 설정하기" for button in candidate.safe_buttons)


def test_samsung_account_popup_tap_prefers_button3_resource_id():
    client = _Client()
    candidate = popup_handler.detect_popup_candidate(_samsung_account_popup_row())

    assert popup_handler.tap_popup_button(client, "SERIAL", candidate.safe_buttons[0]) is True
    assert client.touch_calls == [{"dev": "SERIAL", "type_": "resourceId", "name": "^android:id/button3$"}]
    assert client.tap_xy_adb_calls == []


def test_generic_later_popup_is_not_treated_as_safe_without_samsung_evidence():
    candidate = popup_handler.detect_popup_candidate(_generic_later_popup_row())

    assert candidate.detected is False
    assert candidate.reason == "no_safe_action"


def test_non_samsung_popup_without_safe_action_is_noop():
    row = {
        "focus_node": _node("Camera", clickable=True),
        "dump_tree_nodes": [_node("Camera", clickable=True)],
    }

    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.detected is False
    assert candidate.reason == "no_safe_action"


def test_camera_pip_popup_named_subtree_is_non_modal_with_background_and_external_focus():
    candidate = popup_handler.detect_popup_candidate(_camera_pip_row())
    assessment = candidate.modal_assessment

    assert candidate.detected is False
    assert candidate.modal_classification == "NON_MODAL_CONTROL"
    assert candidate.candidate_evidence == ["popup_resource"]
    assert "popup_resource" not in candidate.modal_evidence
    assert assessment["focused_activity_matches"] is True
    assert assessment["background_accessible"] is True
    assert assessment["background_actionable_count"] >= 3
    assert assessment["accessibility_focus_outside"] is True
    assert assessment["candidate_area_ratio"] < 0.02


def test_popup_resource_token_alone_never_establishes_modal():
    for resource in ("btn_popup_play", "popup_player_button", "popup_preview_control"):
        row = {"focus_node": _node("More options", clickable=True, resource_id="pkg:id/toolbar"),
               "dump_tree_nodes": [_node("PIP", clickable=True, resource_id="pkg:id/" + resource)]}
        candidate = popup_handler.detect_popup_candidate(row)

        assert candidate.modal_classification == "AMBIGUOUS_OVERLAY"
        assert candidate.detected is False
        assert "popup_resource" in candidate.candidate_evidence
        assert "popup_resource" not in candidate.modal_evidence


def test_dialog_root_and_inaccessible_background_is_verified_modal():
    candidate = popup_handler.detect_popup_candidate(_dialog_row("Notice", "Close") | {"background_accessible": False})

    assert candidate.modal_classification == "VERIFIED_MODAL"
    assert "dialog_class" in candidate.modal_evidence
    assert "background_inaccessible" in candidate.modal_evidence
    assert candidate.detected is True


def test_substantial_blocking_overlay_with_dismiss_action_is_conservatively_blocked():
    node = _node("Close", clickable=True, class_name="android.widget.Button", bounds="800,1700,1000,1900")
    candidate = popup_handler.detect_popup_candidate({"focus_node": node, "dump_tree_nodes": [node],
        "display_bounds": [0, 0, 1080, 2400], "blocking_overlay_bounds": [40, 300, 1040, 2100],
        "background_accessible": False})

    assert candidate.modal_classification == "VERIFIED_MODAL"
    assert "blocking_region_substantial" in candidate.modal_evidence
    assert "dismiss_action_present" in candidate.modal_evidence


def test_small_pip_without_window_or_background_proof_stays_ambiguous():
    row = _camera_pip_row()
    row["window_evidence"] = {}
    row.pop("context_source")
    row["focus_node"]["accessibilityFocused"] = False
    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.modal_classification == "AMBIGUOUS_OVERLAY"
    assert candidate.detected is False


def test_dialog_window_type_overrides_small_non_modal_geometry():
    row = _camera_pip_row()
    row["window_evidence"]["focused_window_type"] = "APPLICATION_ATTACHED_DIALOG"
    row["window_evidence"]["focused_window_is_dialog"] = True
    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.modal_classification == "VERIFIED_MODAL"
    assert "focused_dialog_window" in candidate.modal_evidence


def test_dialog_root_without_observed_background_state_is_likely_and_stays_blocked():
    candidate = popup_handler.detect_popup_candidate(_dialog_row("System notice", "Close"))

    assert candidate.modal_classification == "LIKELY_MODAL"
    assert candidate.detected is True


def test_input_focus_cannot_substitute_for_accessibility_focus_outside_pip():
    row = _camera_pip_row()
    row["focus_node"]["accessibilityFocused"] = False
    row["focus_node"]["focused"] = True

    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.modal_classification == "AMBIGUOUS_OVERLAY"


def test_non_candidate_foreground_window_mismatch_stays_ambiguous():
    row = {"focus_node": _node("Close", clickable=True), "dump_tree_nodes": [],
           "activity_name": "com.example.MainActivity",
           "window_evidence": {"window_count": 2, "focused_window_component": "com.android.systemui.NotificationShade",
                               "focused_window_type": "NOTIFICATION_SHADE"}}

    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.modal_classification == "AMBIGUOUS_OVERLAY"


def test_regular_foreground_app_window_without_popup_candidate_is_non_modal():
    row = {"focus_node": _node("Open", clickable=True), "dump_tree_nodes": [],
           "activity_name": "com.example.MainActivity",
           "window_evidence": {"window_count": 2, "focused_window_component": "com.example.MainActivity",
                               "focused_window_type": "BASE_APPLICATION", "focused_activity_matches": True}}

    candidate = popup_handler.detect_popup_candidate(row)

    assert candidate.modal_classification == "NON_MODAL_CONTROL"
