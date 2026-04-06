import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from talkback_lib import (
    ACTION_CHECK_TARGET,
    ACTION_CLICK_FOCUSED,
    ACTION_CLICK_TARGET,
    ACTION_FOCUS_TARGET,
    ACTION_GET_FOCUS,
    ACTION_NEXT,
    ACTION_PREV,
    ACTION_SMART_NEXT,
    ACTION_SCROLL,
    ACTION_SET_TEXT,
    ACTION_PING,
    ACTION_COMMAND,
    LOGCAT_FILTER_SPECS,
    A11yAdbClient,
    CLIENT_ALGORITHM_VERSION,
)


class Dev:
    def __init__(self, serial: str):
        self.serial = serial


class DeviceWithId:
    def __init__(self, device_id: str):
        self.device_id = device_id


class FakeA11yClient(A11yAdbClient):
    def __init__(self):
        super().__init__(adb_path="adb", package_name="com.example.custom", start_monitor=False)
        self.calls = []
        self.logcat_payload = ""
        self.needs_update = False
        self.package_list_payload = "package:com.example.custom"
        self.accessibility_enabled_payload = "1"
        self.enabled_services_payload = "foo:com.example.custom/.A11yService"
        self._dump_counter = 0
        self.ping_ready = True

    def ping(self, dev=None, wait_=3.0):  # pylint: disable=unused-argument
        return self.ping_ready

    def dump_tree(self, dev=None, wait_seconds: float = 5.0):  # pylint: disable=unused-argument
        self._dump_counter += 1
        return [{"text": f"dump-{self._dump_counter}"}]

    def _run(self, args, dev=None, timeout: float = 30.0):  # pylint: disable=unused-argument
        self.calls.append((args, dev))
        if args == ["logcat", "-c"]:
            return ""
        if args[:3] == ["shell", "am", "broadcast"]:
            return "broadcast ok"
        if args == ["logcat", "-d", *LOGCAT_FILTER_SPECS]:
            return self.logcat_payload
        if args == ["logcat", "-v", "time", "-d", *LOGCAT_FILTER_SPECS]:
            return self.logcat_payload
        if args == ["logcat", "-v", "raw", "-d", *LOGCAT_FILTER_SPECS]:
            return self.logcat_payload
        if args == ["shell", "pm", "list", "packages"]:
            return self.package_list_payload
        if args == ["shell", "settings", "get", "secure", "accessibility_enabled"]:
            return self.accessibility_enabled_payload
        if args == ["shell", "settings", "get", "secure", "enabled_accessibility_services"]:
            return self.enabled_services_payload
        if args == ["shell", "input", "keyevent", "4"]:
            return ""
        if args[:3] == ["shell", "input", "tap"]:
            return ""
        if args[:3] == ["shell", "input", "text"]:
            return ""
        raise AssertionError(f"unexpected args: {args}")




class CollectFocusStepClient(FakeA11yClient):
    def __init__(self):
        super().__init__()
        self.partial_calls = []
        self.merged_calls = []
        self.focus_calls = []
        self.move_focus_calls = []
        self.move_focus_smart_calls = []
        self.dump_tree_calls = []
        self.partial_payload = ["  Hello  ", "버튼"]
        self.partial_payload_sequence = []
        self.merged_payload = "Hello Button"
        self.focus_payload = {
            "text": "  Hello  ",
            "contentDescription": "ignored",
            "viewIdResourceName": "com.example:id/hello",
            "boundsInScreen": {"l": 1, "t": 2, "r": 3, "b": 4},
        }
        self.dump_payload = [{"text": "node-1"}]

    def get_partial_announcements(self, dev=None, wait_seconds: float = 2.0, only_new: bool = True):
        self.partial_calls.append((dev, wait_seconds, only_new))
        if self.partial_payload_sequence:
            payload = list(self.partial_payload_sequence.pop(0))
        else:
            payload = list(self.partial_payload)
        self.last_announcements = list(payload)
        self.last_merged_announcement = " ".join(item.strip() for item in payload if item.strip())
        return payload

    def get_announcements(self, dev=None, wait_seconds: float = 2.0, only_new: bool = True):
        self.merged_calls.append((dev, wait_seconds, only_new))
        self.last_merged_announcement = self.merged_payload
        return self.merged_payload

    def get_focus(self, dev=None, wait_seconds: float = 2.0):
        self.focus_calls.append((dev, wait_seconds))
        return dict(self.focus_payload)

    def move_focus(self, dev=None, direction: str = "next"):
        self.move_focus_calls.append((dev, direction))
        return True

    def move_focus_smart(self, dev=None, direction: str = "next"):
        self.move_focus_smart_calls.append((dev, direction))
        return "moved"

    def dump_tree(self, dev=None, wait_seconds: float = 5.0):
        self.dump_tree_calls.append((dev, wait_seconds))
        # 실제 dump_tree()처럼 마지막 발화 상태를 초기화하는 부작용을 재현한다.
        self.last_announcements = []
        self.last_merged_announcement = ""
        return list(self.dump_payload)

class TouchIsinTest(unittest.TestCase):
    def test_escape_adb_string_handles_empty_space_and_single_quote(self):
        self.assertEqual(A11yAdbClient._escape_adb_string(""), '""')
        self.assertEqual(A11yAdbClient._escape_adb_string("수면 환경"), "'수면 환경'")
        self.assertEqual(A11yAdbClient._escape_adb_string("O'Reilly"), "'O'\\''Reilly'")

    def test_touch_success_sends_new_extras_and_waits_speech(self):
        client = FakeA11yClient()
        dev = Dev("SER123")
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reason":"ok","reqId":"REQID001"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID001-xxxx"), patch.object(client, "_wait_for_speech_if_needed") as wait_mock:
            ok = client.touch(dev, name="확인", wait_=1, type_="b", index_=2, long_=True)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(broadcast[1], dev)
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_CLICK_TARGET,
                "-p", "com.example.custom",
                "--es", "targetName", "'확인'",
                "--es", "targetType", "b",
                "--ei", "targetIndex", "2",
                "--ez", "isLongClick", "true",
                "--es", "reqId", "REQID001",
            ],
        )
        wait_mock.assert_called_once_with(dev)

    def test_touch_polling_until_timeout_returns_false(self):
        client = FakeA11yClient()
        dev = "SERIAL"
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":false,"reason":"not found"}'

        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch("talkback_lib.time.sleep", side_effect=fake_sleep):
            ok = client.touch(dev, name="없음", wait_=1, type_="a", index_=0, long_=False)

        self.assertFalse(ok)
        broadcast_count = len([c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]])
        self.assertGreaterEqual(broadcast_count, 1)

    def test_click_focused_success(self):
        client = FakeA11yClient()
        dev = Dev("SER123")
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reason":"ok","reqId":"REQCF001"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQCF001-xxxx"), patch.object(client, "_wait_for_speech_if_needed") as wait_mock:
            ok = client.click_focused(dev, wait_=1)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_CLICK_FOCUSED,
                "-p", "com.example.custom",
                "--es", "reqId", "REQCF001",
            ],
        )
        wait_mock.assert_called_once_with(dev)

    def test_click_focused_timeout_sets_reason(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":false,"reason":"no_focused_node"}'
        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch("talkback_lib.time.sleep", side_effect=fake_sleep):
            ok = client.click_focused("SERIAL", wait_=1)

        self.assertFalse(ok)
        self.assertEqual(client.last_target_action_result.get("reason"), "timeout")

    def test_isin_uses_check_target_and_returns_true(self):
        client = FakeA11yClient()
        dev = "SERIAL"
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":true,"reason":"found","reqId":"REQID002"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID002-xxxx"):
            ok = client.isin(dev, name="설정", wait_=1, type_="r", index_=1)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_CHECK_TARGET,
                "-p", "com.example.custom",
                "--es", "targetName", "'(?i)설정'",
                "--es", "targetType", "r",
                "--ei", "targetIndex", "1",
                "--ez", "isLongClick", "false",
                "--es", "reqId", "REQID002",
            ],
        )


    def test_actions_reset_last_announcements_first(self):
        client = FakeA11yClient()
        client.last_announcements = ["이전 안내"]
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":false,"reason":"not found"}'

        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch("talkback_lib.time.sleep", side_effect=fake_sleep):
            client.touch("SER", name="없음", wait_=0)

        self.assertEqual(client.last_announcements, [])

        client.last_announcements = ["이전 안내"]
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":false,"reason":"not found"}'
        with patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch("talkback_lib.time.sleep", side_effect=fake_sleep):
            client.isin("SER", name="없음", wait_=0)

        self.assertEqual(client.last_announcements, [])

    def test_refresh_tree_if_needed_called_in_touch_and_isin(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reqId":"REQID003"}'
        with patch.object(client, "_refresh_tree_if_needed") as refresh_mock:
            client.touch("SER", name="확인", wait_=1)
        refresh_mock.assert_called()

        client.calls.clear()
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":true,"reqId":"REQID004"}'
        with patch.object(client, "_refresh_tree_if_needed") as refresh_mock:
            client.isin("SER", name="확인", wait_=1)
        refresh_mock.assert_called()


    def test_isin_logs_target_name_and_type_at_start(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":true,"reqId":"REQID777"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID777-xxxx"), patch("builtins.print") as print_mock:
            ok = client.isin("SER", name="설정", wait_=1, type_="text")

        self.assertTrue(ok)
        print_mock.assert_any_call("[DEBUG][isin] 검색 시작 targetName=설정, targetType=text")

    def test_isin_logs_visible_text_samples_when_result_false(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":false,"reqId":"REQID778"}'

        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch("talkback_lib.time.sleep", side_effect=fake_sleep), patch.object(
            client, "_log_visible_text_samples"
        ) as sample_mock:
            client.isin("SER", name="없음", wait_=0.6, type_="all")

        self.assertGreaterEqual(sample_mock.call_count, 1)

    def test_collect_text_samples_limits_to_ten(self):
        nodes = [
            {
                "text": "first",
                "children": [
                    {"contentDescription": "second"},
                    {"talkback": "third"},
                ],
            }
        ] + [{"text": f"item-{i}"} for i in range(20)]

        samples = A11yAdbClient._collect_text_samples(nodes, max_samples=10)

        self.assertEqual(len(samples), 10)
        self.assertEqual(samples[0], "first")

    def test_scrollfind_logs_scroll_attempt_count(self):
        client = FakeA11yClient()

        with patch.object(client, "isin", side_effect=[False, False, True]), patch.object(
            client,
            "scroll",
            return_value=True,
        ), patch("talkback_lib.time.sleep", return_value=None), patch("builtins.print") as print_mock:
            ok = client.scrollFind("SER", "설정", wait_=1, direction_="down", type_="text")

        self.assertTrue(ok)
        printed = [c.args[0] for c in print_mock.call_args_list if c.args]
        self.assertTrue(any("[DEBUG][scrollFind] 스크롤 시도 #1" in msg for msg in printed))
        self.assertTrue(any("[DEBUG][scrollFind] 스크롤 시도 #2" in msg for msg in printed))

    def test_isin_adds_case_insensitive_prefix_to_target_name(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":true,"reqId":"REQID900"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID900-xxxx"):
            client.isin("SER", name="Pet.*", wait_=1, type_="text")

        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertEqual(broadcast[broadcast.index("targetName") + 1], "'(?i)Pet.*'")

    def test_scrollfind_breaks_when_before_and_after_dump_are_identical(self):
        client = FakeA11yClient()
        same_tree = [{"text": "A", "boundsInScreen": {"l": 1, "t": 1, "r": 2, "b": 2}}]

        with patch.object(client, "isin", return_value=False), patch.object(client, "scroll", return_value=True) as scroll_mock, patch.object(
            client,
            "dump_tree",
            side_effect=[same_tree, same_tree],
        ), patch("builtins.print") as print_mock:
            result = client.scrollFind("SER", "없음", wait_=1, direction_="down", type_="all")

        self.assertIsNone(result)
        self.assertEqual(scroll_mock.call_count, 1)
        printed = [c.args[0] for c in print_mock.call_args_list if c.args]
        self.assertTrue(any("화면 끝 도달 감지: 스크롤 전/후 텍스트/위치 변화가 없습니다." in msg for msg in printed))


    def test_isin_uses_case_insensitive_tree_regex_matching_before_broadcast(self):
        client = FakeA11yClient()

        with patch.object(client, "dump_tree", return_value=[{"text": "PET care"}]), patch.object(client, "_broadcast") as broadcast_mock:
            ok = client.isin("SER", name="Pet.*", wait_=0.1, type_="text")

        self.assertTrue(ok)
        broadcast_mock.assert_not_called()

    def test_isin_text_type_matches_contentdescription_case_insensitive(self):
        client = FakeA11yClient()

        with patch.object(client, "dump_tree", return_value=[{"contentDescription": "PET care"}]), patch.object(client, "_broadcast") as broadcast_mock:
            ok = client.isin("SER", name="Pet.*", wait_=0.1, type_="text")

        self.assertTrue(ok)
        broadcast_mock.assert_not_called()

    def test_log_visible_text_samples_prints_full_text_list(self):
        client = FakeA11yClient()

        with patch.object(client, "dump_tree", return_value=[{"text": "Energy", "children": [{"contentDescription": "Pet care"}]}]), patch(
            "builtins.print"
        ) as print_mock:
            client._log_visible_text_samples("SER")

        print_mock.assert_any_call("[DEBUG][isin] 현재 화면 텍스트: ['Energy', 'Pet care']")

    def test_select_uses_focus_target_and_returns_true(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reqId":"REQID003"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID003-xxxx"):
            ok = client.select("SER", name="다음", wait_=1, type_="t", index_=3)

        self.assertTrue(ok)
        self.assertEqual(client.last_target_action_result.get("reqId"), "REQID003")
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_FOCUS_TARGET,
                "-p", "com.example.custom",
                "--es", "targetName", "'(?i)다음'",
                "--es", "targetType", "t",
                "--ei", "targetIndex", "3",
                "--ez", "isLongClick", "false",
                "--es", "reqId", "REQID003",
            ],
        )

    def test_select_resource_id_does_not_add_case_insensitive_prefix(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reqId":"REQID003"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID003R-xxxx"):
            ok = client.select("SER", name="com.example.app:id/setting_button_layout", wait_=1, type_="r", index_=0)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertEqual(
            broadcast[broadcast.index("targetName") + 1],
            "'com.example.app:id/setting_button_layout'",
        )
        self.assertEqual(broadcast[broadcast.index("targetType") + 1], "r")

    def test_select_preserves_failed_target_action_payload(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: TARGET_ACTION_RESULT '
            '{"success":false,"reason":"ACTION_ACCESSIBILITY_FOCUS failed","reqId":"REQFAIL0",'
            '"target":{"accessibilityFocused":true,"text":"확인"}}'
        )

        with patch("talkback_lib.uuid.uuid4", return_value="REQFAIL0-xxxx"):
            ok = client.select("SER", name="확인", wait_=1, type_="t")

        self.assertFalse(ok)
        self.assertEqual(client.last_target_action_result.get("reqId"), "REQFAIL0")
        self.assertFalse(client.last_target_action_result.get("success"))
        self.assertEqual(client.last_target_action_result.get("target", {}).get("accessibilityFocused"), True)

    def test_select_uses_timeout_fallback_only_when_result_payload_missing(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":false,"reason":"other","reqId":"OTHER001"}'
        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch("talkback_lib.time.sleep", side_effect=fake_sleep):
            ok = client.select("SER", name="확인", wait_=1, type_="t")

        self.assertFalse(ok)
        self.assertEqual(client.last_target_action_result, {"success": False, "reason": "timeout"})


    def test_touch_supports_additional_filters(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reqId":"REQID101"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID101-xxxx"), patch.object(client, "_wait_for_speech_if_needed"):
            ok = client.touch(
                "SER",
                name="확인",
                type_="a",
                class_name="android.widget.Button",
                clickable=True,
                focusable=False,
            )

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertIn("className", broadcast[0])
        self.assertIn("clickable", broadcast[0])
        self.assertIn("focusable", broadcast[0])

    def test_isin_supports_and_list_name_to_target_text_and_id(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":true,"reqId":"REQID102"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID102-xxxx"):
            ok = client.isin("SER", name=["확인", "com.example:id/btn_ok"], type_="and", index_=0)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertIn("targetText", broadcast)
        self.assertIn("'(?i)확인'", broadcast)
        self.assertIn("targetId", broadcast)
        self.assertIn("'(?i)com.example:id/btn_ok'", broadcast)
        self.assertEqual(broadcast[broadcast.index("targetName") + 1], '""')
        self.assertEqual(broadcast[broadcast.index("targetType") + 1], "")

    def test_select_supports_and_list_name_with_regex_id(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reqId":"REQID103"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID103-xxxx"):
            ok = client.select("SER", name=["로그인", ".*id/btn_login"], type_="and")

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertIn("targetText", broadcast)
        self.assertIn("'(?i)로그인'", broadcast)
        self.assertIn("targetId", broadcast)
        self.assertIn("'(?i).*id/btn_login'", broadcast)

    def test_tap_bounds_center_adb_computes_center_and_sends_adb_tap(self):
        client = FakeA11yClient()
        with patch.object(client, "tap_xy_adb", return_value=True) as tap_mock, patch.object(client, "_wait_for_speech_if_needed"):
            ok = client.tap_bounds_center_adb(
                dev="SER",
                name="com.test:id/settings_image",
                type_="r",
                dump_nodes=[
                    {
                        "viewIdResourceName": "com.test:id/settings_image",
                        "boundsInScreen": {"l": 100, "t": 200, "r": 300, "b": 500},
                    }
                ],
            )

        self.assertTrue(ok)
        tap_mock.assert_called_once_with(dev="SER", x=200, y=350)
        self.assertEqual(client.last_target_action_result.get("reason"), "adb_input_tap_sent")
        self.assertEqual(client.last_target_action_result.get("target", {}).get("bounds"), "100,200,300,500")

    def test_tap_bounds_center_adb_returns_false_when_bounds_not_found(self):
        client = FakeA11yClient()
        with patch.object(client, "dump_tree", return_value=[]):
            ok = client.tap_bounds_center_adb(dev="SER", name="missing", type_="t", dump_nodes=[])

        self.assertFalse(ok)
        self.assertEqual(client.last_target_action_result.get("reason"), "bounds_not_found")

    def test_tap_bounds_center_adb_lazy_dump_retry_finds_bounds(self):
        client = FakeA11yClient()
        with patch.object(client, "dump_tree", return_value=[{"text": "Settings", "boundsInScreen": "[10,20][30,40]"}]), patch.object(
            client, "tap_xy_adb", return_value=True
        ) as tap_mock, patch.object(client, "_wait_for_speech_if_needed"):
            ok = client.tap_bounds_center_adb(dev="SER", name="Settings", type_="text", dump_nodes=[])

        self.assertTrue(ok)
        tap_mock.assert_called_once_with(dev="SER", x=20, y=30)
        self.assertTrue(client.last_target_action_result.get("target", {}).get("lazy_dump_used"))

    def test_tap_bounds_center_adb_falls_back_to_wrapper_bounds_when_child_missing_bounds(self):
        client = FakeA11yClient()
        nodes = [
            {
                "viewIdResourceName": "com.test:id/setting_button_layout",
                "boundsInScreen": {"l": 2, "t": 4, "r": 102, "b": 204},
                "children": [{"viewIdResourceName": "com.test:id/settings_image"}],
            }
        ]
        with patch.object(client, "tap_xy_adb", return_value=True) as tap_mock, patch.object(client, "_wait_for_speech_if_needed"):
            ok = client.tap_bounds_center_adb(dev="SER", name="com.test:id/settings_image", type_="r", dump_nodes=nodes)

        self.assertTrue(ok)
        tap_mock.assert_called_once_with(dev="SER", x=52, y=104)

    def test_tap_xy_adb_returns_false_on_subprocess_failure(self):
        client = FakeA11yClient()
        with patch("talkback_lib.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="boom")):
            ok = client.tap_xy_adb(dev="SER", x=1, y=2)
        self.assertFalse(ok)



    def test_ping_returns_true_on_ready_status(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: PING_RESULT {"success":true,"status":"READY","reqId":"REQID401"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID401-xxxx"):
            ok = A11yAdbClient.ping(client, "SER", wait_=1.0)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertEqual(
            broadcast,
            [
                "shell", "am", "broadcast", "-a", ACTION_PING,
                "-p", "com.example.custom",
                "--es", "reqId", "REQID401",
            ],
        )

    def test_check_helper_status_fails_when_ping_not_ready(self):
        client = FakeA11yClient()
        client.ping_ready = False

        ok = client.check_helper_status("SER")

        self.assertFalse(ok)

    def test_check_helper_status_returns_true_when_service_enabled_and_ping_ready(self):
        client = FakeA11yClient()
        client.ping_ready = True

        ok = client.check_helper_status("SER")

        self.assertTrue(ok)

    def test_check_talkback_ready_returns_disabled_when_talkback_off(self):
        client = FakeA11yClient()
        client.accessibility_enabled_payload = "0"
        client.enabled_services_payload = ""

        result = client.check_talkback_ready("SER")

        self.assertEqual(result, {"status": "disabled", "reason": "talkback_off"})

    def test_check_talkback_ready_returns_enabled_but_not_ready_when_helper_not_ready(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "foo:com.google.android.marvin.talkback/.TalkBackService"

        with patch.object(client, "check_helper_status", return_value=False):
            result = client.check_talkback_ready("SER")

        self.assertEqual(result, {"status": "enabled_but_not_ready", "reason": "talkback_not_ready"})

    def test_check_talkback_ready_returns_false_positive_when_sanity_and_probe_fail(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "foo:com.google.android.marvin.talkback/.TalkBackService"

        with patch.object(client, "check_helper_status", return_value=True), patch.object(
            client, "get_focus", return_value={}
        ), patch.object(client, "move_focus", return_value=False):
            result = client.check_talkback_ready("SER")

        self.assertEqual(result, {"status": "enabled_but_not_ready", "reason": "false_positive_enabled"})

    def test_check_talkback_ready_returns_enabled_when_sanity_retry_succeeds(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "foo:com.google.android.marvin.talkback/.TalkBackService"
        focus_nodes = [
            {},
            {"text": "Wi-Fi", "boundsInScreen": {"l": 0, "t": 0, "r": 10, "b": 10}},
        ]

        with patch.object(client, "check_helper_status", return_value=True), patch.object(
            client,
            "get_focus",
            side_effect=focus_nodes,
        ) as get_focus_mock, patch("talkback_lib.time.sleep") as sleep_mock:
            result = client.check_talkback_ready("SER")

        self.assertEqual(result, {"status": "enabled", "reason": "ok"})
        self.assertEqual(get_focus_mock.call_count, 2)
        sleep_mock.assert_called_once_with(0.4)

    def test_check_talkback_ready_retries_sanity_then_probe_passes(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "foo:com.google.android.marvin.talkback/.TalkBackService"

        with patch.object(client, "check_helper_status", return_value=True), patch.object(
            client,
            "get_focus",
            side_effect=[{}, {}, {}, {"text": "Wi-Fi", "boundsInScreen": {"l": 0, "t": 0, "r": 10, "b": 10}}],
        ) as get_focus_mock, patch("talkback_lib.time.sleep") as sleep_mock, patch.object(
            client, "move_focus", return_value=True
        ) as move_focus_mock:
            result = client.check_talkback_ready("SER")

        self.assertEqual(result, {"status": "enabled", "reason": "ok"})
        self.assertEqual(get_focus_mock.call_count, 4)
        self.assertEqual(sleep_mock.call_count, 2)
        move_focus_mock.assert_called_once_with(dev="SER", direction="next")

    def test_check_talkback_ready_returns_enabled_when_talkback_and_helper_ready(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "foo:com.samsung.android.accessibility.talkback/.TalkBackService"

        with patch.object(client, "check_helper_status", return_value=True), patch.object(
            client,
            "get_focus",
            return_value={"text": "Wi-Fi", "boundsInScreen": {"l": 0, "t": 0, "r": 10, "b": 10}},
        ):
            result = client.check_talkback_ready("SER")

        self.assertEqual(result, {"status": "enabled", "reason": "ok"})

    def test_scroll_parses_direction_and_returns_success(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SCROLL_RESULT {"success":true,"reqId":"REQID004"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID004-xxxx"):
            ok = client.scroll("SER", "left", step_=10, time_=500, bounds_=(0, 0, 100, 100))

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_SCROLL,
                "-p", "com.example.custom",
                "--ez", "forward", "false",
                "--es", "direction", "left",
                "--es", "reqId", "REQID004",
            ],
        )

    def test_scroll_normalizes_right_shortcut(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SCROLL_RESULT {"success":true,"reqId":"REQID200"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID200-xxxx"):
            ok = client.scroll("SER", "r")

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertIn("--es", broadcast)
        self.assertEqual(broadcast[broadcast.index("direction") + 1], "right")
        self.assertEqual(broadcast[broadcast.index("forward") + 1], "true")


    def test_scrollselect_calls_select_when_scrollfind_succeeds(self):
        client = FakeA11yClient()

        with patch.object(client, "scrollFind", return_value=True) as find_mock, patch.object(client, "select", return_value=True) as select_mock, patch("talkback_lib.time.sleep") as sleep_mock:
            ok = client.scrollSelect(
                "SER",
                name="설정",
                wait_=12,
                direction_="down",
                type_="text",
                index_=1,
                class_name="android.widget.TextView",
                clickable=True,
                focusable=False,
            )

        self.assertTrue(ok)
        find_mock.assert_called_once_with("SER", "설정", wait_=12, direction_="down", type_="text")
        sleep_mock.assert_called_once_with(1.5)
        select_mock.assert_called_once_with(
            "SER",
            "설정",
            wait_=10,
            type_="text",
            index_=1,
            class_name="android.widget.TextView",
            clickable=True,
            focusable=False,
        )

    def test_scrollselect_normalizes_all_to_a(self):
        client = FakeA11yClient()

        with patch.object(client, "scrollFind", return_value=True) as find_mock, patch.object(client, "select", return_value=True) as select_mock, patch("talkback_lib.time.sleep"):
            ok = client.scrollSelect("SER", name="설정", type_="all")

        self.assertTrue(ok)
        find_mock.assert_called_once_with("SER", "설정", wait_=60, direction_="updown", type_="a")
        select_mock.assert_called_once_with(
            "SER",
            "설정",
            wait_=10,
            type_="a",
            index_=0,
            class_name=None,
            clickable=None,
            focusable=None,
        )

    def test_scrollselect_returns_false_when_scrollfind_fails(self):
        client = FakeA11yClient()

        with patch.object(client, "scrollFind", return_value=None), patch.object(client, "select") as select_mock:
            ok = client.scrollSelect("SER", name="없음")

        self.assertFalse(ok)
        select_mock.assert_not_called()

    def test_scrolltouch_calls_touch_when_scrollfind_succeeds(self):
        client = FakeA11yClient()

        with patch.object(client, "scrollFind", return_value=True) as find_mock, patch.object(client, "touch", return_value=True) as touch_mock, patch("talkback_lib.time.sleep") as sleep_mock:
            ok = client.scrollTouch(
                "SER",
                name="확인",
                wait_=8,
                direction_="updown",
                type_="all",
                index_=2,
                long_=True,
                class_name="android.widget.Button",
                clickable=True,
                focusable=True,
            )

        self.assertTrue(ok)
        find_mock.assert_called_once_with("SER", "확인", wait_=8, direction_="updown", type_="a")
        sleep_mock.assert_called_once_with(1.5)
        touch_mock.assert_called_once_with(
            "SER",
            "확인",
            wait_=10,
            type_="a",
            index_=2,
            long_=True,
            class_name="android.widget.Button",
            clickable=True,
            focusable=True,
        )

    def test_scrollselect_default_type_is_a(self):
        client = FakeA11yClient()

        with patch.object(client, "scrollFind", return_value=True) as find_mock, patch.object(client, "select", return_value=True) as select_mock, patch("talkback_lib.time.sleep"):
            ok = client.scrollSelect("SER", name="설정")

        self.assertTrue(ok)
        find_mock.assert_called_once_with("SER", "설정", wait_=60, direction_="updown", type_="a")
        select_mock.assert_called_once_with(
            "SER",
            "설정",
            wait_=10,
            type_="a",
            index_=0,
            class_name=None,
            clickable=None,
            focusable=None,
        )

    def test_scrolltouch_default_type_is_a(self):
        client = FakeA11yClient()

        with patch.object(client, "scrollFind", return_value=True) as find_mock, patch.object(client, "touch", return_value=True) as touch_mock, patch("talkback_lib.time.sleep"):
            ok = client.scrollTouch("SER", name="확인")

        self.assertTrue(ok)
        find_mock.assert_called_once_with("SER", "확인", wait_=60, direction_="updown", type_="a")
        touch_mock.assert_called_once_with(
            "SER",
            "확인",
            wait_=10,
            type_="a",
            index_=0,
            long_=False,
            class_name=None,
            clickable=None,
            focusable=None,
        )

    def test_scrolltouch_returns_false_when_scrollfind_fails(self):
        client = FakeA11yClient()

        with patch.object(client, "scrollFind", return_value=False), patch.object(client, "touch") as touch_mock:
            ok = client.scrollTouch("SER", name="없음", long_=True)

        self.assertFalse(ok)
        touch_mock.assert_not_called()

    def test_scrollfind_returns_true_when_target_appears(self):
        client = FakeA11yClient()

        with patch.object(client, "isin", side_effect=[False, False, True]) as isin_mock, patch.object(
            client,
            "scroll",
            return_value=True,
        ) as scroll_mock, patch("talkback_lib.time.sleep", return_value=None):
            ok = client.scrollFind("SER", "설정", wait_=1, direction_="updown", type_="text")

        self.assertTrue(ok)
        self.assertEqual(scroll_mock.call_count, 2)
        isin_mock.assert_any_call("SER", "설정", wait_=1, type_="t")

    def test_scrollfind_updown_flips_only_after_scroll_failure(self):
        client = FakeA11yClient()
        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch.object(client, "isin", return_value=False), patch.object(
            client,
            "scroll",
            side_effect=[True, False, True],
        ) as scroll_mock, patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch(
            "talkback_lib.time.sleep",
            side_effect=fake_sleep,
        ):
            result = client.scrollFind("SER", "없음", wait_=1.1, direction_="updown", type_="all")

        self.assertIsNone(result)
        self.assertEqual([call.args[1] for call in scroll_mock.call_args_list], ["down", "down"])

    def test_scrollfind_downup_starts_up_and_flips_once(self):
        client = FakeA11yClient()
        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch.object(client, "isin", return_value=False), patch.object(
            client,
            "scroll",
            side_effect=[False, False, True],
        ) as scroll_mock, patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch(
            "talkback_lib.time.sleep",
            side_effect=fake_sleep,
        ):
            result = client.scrollFind("SER", "없음", wait_=1.1, direction_="downup", type_="all")

        self.assertIsNone(result)
        self.assertEqual([call.args[1] for call in scroll_mock.call_args_list], ["up", "down"])

    def test_scroll_to_top_stops_when_no_visible_change(self):
        client = FakeA11yClient()
        dumps = [
            [{"text": "a", "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 100}}],
            [{"text": "a", "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 100}}],
        ]

        with patch.object(client, "dump_tree", side_effect=dumps), patch.object(client, "scroll", return_value=True) as scroll_mock, patch(
            "talkback_lib.time.sleep",
            return_value=None,
        ):
            result = client.scroll_to_top("SER", max_swipes=5, pause=0.0)

        self.assertTrue(result["ok"])
        self.assertTrue(result["reached_top"])
        self.assertEqual(result["reason"], "no_visible_change")
        self.assertEqual(scroll_mock.call_count, 1)

    def test_scroll_to_top_falls_back_to_max_swipes(self):
        client = FakeA11yClient()
        dumps = [
            [{"text": "a", "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 100}}],
            [{"text": "b", "boundsInScreen": {"l": 0, "t": 20, "r": 100, "b": 120}}],
            [{"text": "c", "boundsInScreen": {"l": 0, "t": 40, "r": 100, "b": 140}}],
        ]

        with patch.object(client, "dump_tree", side_effect=dumps), patch.object(client, "scroll", return_value=True) as scroll_mock, patch(
            "talkback_lib.time.sleep",
            return_value=None,
        ):
            result = client.scroll_to_top("SER", max_swipes=2, pause=0.0)

        self.assertTrue(result["ok"])
        self.assertFalse(result["reached_top"])
        self.assertEqual(result["reason"], "max_swipes")
        self.assertEqual(scroll_mock.call_count, 2)


    def test_scrollfind_marks_tree_dirty_only_when_scrolled(self):
        client = FakeA11yClient()
        client.needs_update = False
        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch.object(client, "isin", return_value=False), patch.object(
            client,
            "scroll",
            side_effect=[False, True],
        ), patch("talkback_lib.time.monotonic", side_effect=fake_monotonic), patch(
            "talkback_lib.time.sleep",
            side_effect=fake_sleep,
        ):
            client.scrollFind("SER", "없음", wait_=1.1, direction_="down", type_="all")

        self.assertTrue(client.needs_update)

    def test_scrollfind_waits_0_8_seconds_between_scrolls(self):
        client = FakeA11yClient()
        sleeps = []
        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            sleeps.append(sec)
            clock["t"] += sec

        with patch.object(client, "isin", return_value=False), patch.object(client, "scroll", return_value=False), patch(
            "talkback_lib.time.monotonic",
            side_effect=fake_monotonic,
        ), patch("talkback_lib.time.sleep", side_effect=fake_sleep):
            client.scrollFind("SER", "없음", wait_=0.81, direction_="down", type_="all")

        self.assertIn(0.8, sleeps)

    def test_scroll_waits_1_5_seconds_after_action_scroll(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SCROLL_RESULT {"success":true,"reqId":"REQID301"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID301-xxxx"), patch("talkback_lib.time.sleep") as sleep_mock:
            ok = client.scroll("SER", "down")

        self.assertTrue(ok)
        sleep_mock.assert_called_once_with(1.5)

    def test_scrollfind_logs_center_region_texts(self):
        client = FakeA11yClient()
        tree = [
            {"text": "Header", "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 40}},
            {"text": "Pet care", "boundsInScreen": {"l": 0, "t": 200, "r": 100, "b": 260}},
            {"text": "Footer", "boundsInScreen": {"l": 0, "t": 500, "r": 100, "b": 700}},
        ]

        with patch.object(client, "isin", return_value=False), patch.object(client, "scroll", return_value=True), patch.object(
            client,
            "dump_tree",
            side_effect=[tree, tree],
        ), patch("builtins.print") as print_mock:
            client.scrollFind("SER", "없음", wait_=1, direction_="down", type_="all")

        printed = [c.args[0] for c in print_mock.call_args_list if c.args]
        self.assertTrue(any("중앙 70% 영역 텍스트 노드 개수" in msg for msg in printed))
        self.assertTrue(any("중앙 70% 영역 텍스트 목록: ['Pet care']" in msg for msg in printed))

    def test_move_focus_next_uses_nav_result_and_waits_speech(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: NAV_RESULT {"success":true,"reason":"ok","reqId":"REQID501"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID501-xxxx"), patch.object(client, "_wait_for_speech_if_needed") as wait_mock:
            ok = client.move_focus("SER", direction="next")

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertEqual(
            broadcast,
            [
                "shell", "am", "broadcast", "-a", ACTION_NEXT,
                "-p", "com.example.custom",
                "--es", "reqId", "REQID501",
            ],
        )
        wait_mock.assert_called_once_with("SER")

    def test_move_focus_prev_uses_prev_action(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: NAV_RESULT {"success":true,"reason":"ok","reqId":"REQID502"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID502-xxxx"), patch.object(client, "_wait_for_speech_if_needed"):
            ok = client.move_focus("SER", direction="prev")

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertEqual(broadcast[4], ACTION_PREV)

    def test_move_focus_returns_false_and_logs_reason_on_failure(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: NAV_RESULT {"success":false,"reason":"end reached","reqId":"REQID503"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID503-xxxx"), patch("builtins.print") as print_mock, patch.object(
            client,
            "_wait_for_speech_if_needed",
        ) as wait_mock:
            ok = client.move_focus("SER", direction="next")

        self.assertFalse(ok)
        wait_mock.assert_not_called()
        print_mock.assert_any_call("[ERROR] move_focus 실패(direction=next): end reached")

    def test_move_focus_invalid_direction_returns_false_without_broadcast(self):
        client = FakeA11yClient()

        with patch("builtins.print") as print_mock:
            ok = client.move_focus("SER", direction="left")

        self.assertFalse(ok)
        print_mock.assert_any_call("[ERROR] 지원하지 않는 direction: left. 'next' 또는 'prev'를 사용해 주세요.")
        broadcasts = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]]
        self.assertEqual(len(broadcasts), 0)

    def test_has_screen_meaningful_change_detects_bottom_node_difference(self):
        before = [
            {"text": "Header", "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 40}},
            {"text": "Item1", "boundsInScreen": {"l": 0, "t": 300, "r": 100, "b": 350}},
        ]
        after = [
            {"text": "Header", "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 40}},
            {"text": "Item2", "boundsInScreen": {"l": 0, "t": 300, "r": 100, "b": 350}},
        ]

        self.assertTrue(A11yAdbClient._has_screen_meaningful_change(before, after))

    def test_has_screen_meaningful_change_ignores_bottom_fixed_tab_change(self):
        before = [
            {"text": "Header", "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 80}},
            {"text": "Item1", "boundsInScreen": {"l": 0, "t": 250, "r": 100, "b": 320}},
            {"text": "Home", "boundsInScreen": {"l": 0, "t": 880, "r": 100, "b": 980}},
        ]
        after = [
            {"text": "Header", "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 80}},
            {"text": "Item1", "boundsInScreen": {"l": 0, "t": 250, "r": 100, "b": 320}},
            {"text": "Settings", "boundsInScreen": {"l": 0, "t": 880, "r": 100, "b": 980}},
        ]

        self.assertFalse(A11yAdbClient._has_screen_meaningful_change(before, after))

    def test_scrollfind_timeout_returns_none(self):
        client = FakeA11yClient()
        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        def fake_sleep(sec: float):
            clock["t"] += sec

        with patch.object(client, "isin", return_value=False), patch.object(client, "scroll", return_value=True), patch(
            "talkback_lib.time.monotonic",
            side_effect=fake_monotonic,
        ), patch("talkback_lib.time.sleep", side_effect=fake_sleep):
            result = client.scrollFind("SER", "없음", wait_=1, direction_="down", type_="all")

        self.assertIsNone(result)

    def test_typing_runs_adb_input_when_adbtyping_true(self):
        client = FakeA11yClient()

        result = client.typing("SER", "hello world", adbTyping=True)

        self.assertIsNone(result)
        self.assertIn((['shell', 'input', 'text', "'hello world'"], 'SER'), client.calls)

    def test_typing_broadcasts_set_text_and_returns_none(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SET_TEXT_RESULT {"success":true,"reqId":"REQID005"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID005-xxxx"):
            result = client.typing("SER", "테스트", adbTyping=False)

        self.assertIsNone(result)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_SET_TEXT,
                "-p", "com.example.custom",
                "--es", "text", "'테스트'",
                "--es", "reqId", "REQID005",
            ],
        )

    def test_typing_escapes_single_quote_in_text(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SET_TEXT_RESULT {"success":true,"reqId":"REQID006"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID006-xxxx"):
            result = client.typing("SER", "O'Reilly", adbTyping=False)

        self.assertIsNone(result)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(broadcast[0][9], "'O'\\''Reilly'")
        self.assertEqual(broadcast[0][-1], "REQID006")

    def test_waitforactivity_returns_true_when_activity_found(self):
        client = A11yAdbClient(start_monitor=False)

        with patch.object(client, "_run", return_value="mCurrentFocus=Window{u0 com.pkg/.MainActivity}"), patch(
            "talkback_lib.time.sleep",
            return_value=None,
        ):
            result = client.waitForActivity("SER", "MainActivity", 1000)

        self.assertTrue(result)


class ClientInterfaceCompatTest(unittest.TestCase):
    def test_clear_logcat_is_public_and_uses_default_dev_serial(self):
        client = A11yAdbClient(dev_serial="R3CX40QFDBP", start_monitor=False)
        calls = []

        def fake_run(args, dev=None, timeout=30.0):
            calls.append((args, dev))
            return ""

        with patch.object(client, "_run", side_effect=fake_run):
            client.clear_logcat()

        self.assertEqual(calls, [(["logcat", "-c"], None)])

    def test_clear_logcat_returns_empty_string_on_timeout(self):
        client = A11yAdbClient(start_monitor=False)

        with patch.object(
            client,
            "_run",
            side_effect=subprocess.TimeoutExpired(cmd=["adb", "logcat", "-c"], timeout=5.0),
        ), patch("builtins.print") as print_mock:
            result = client.clear_logcat(dev="SER")

        self.assertEqual(result, "")
        print_mock.assert_called_once_with("[WARN] logcat -c timed out, skipping...")

    def test_run_applies_default_serial_when_dev_is_missing(self):
        client = A11yAdbClient(adb_path="adb", dev_serial="R3CX40QFDBP", start_monitor=False)

        with patch("talkback_lib.subprocess.run") as run_mock:
            run_mock.return_value.stdout = "ok"
            run_mock.return_value.returncode = 0
            run_mock.return_value.stderr = ""
            result = client._run(["devices"])

        self.assertEqual(result, "ok")
        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[:3], ["adb", "-s", "R3CX40QFDBP"])
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 30.0)

    def test_dump_tree_joins_all_part_payloads(self):
        client = A11yAdbClient(start_monitor=False)
        log_payload = "\n".join(
            [
                'A11Y_HELPER DUMP_TREE_PART other [{"id":9}]',
                'A11Y_HELPER DUMP_TREE_PART REQID801 [{"id":1},',
                'A11Y_HELPER DUMP_TREE_PART REQID801 {"id":2}]',
                'A11Y_HELPER DUMP_TREE_END REQID801',
            ]
        )

        with patch("talkback_lib.uuid.uuid4", return_value="REQID801-xxxx"), patch.object(client, "check_helper_status", return_value=True), patch.object(client, "clear_logcat", return_value=""), patch.object(client, "_broadcast", return_value="ok") as broadcast_mock, patch.object(
            client,
            "_run",
            return_value=log_payload,
        ):
            result = client.dump_tree(dev="R3CX40QFDBP", wait_seconds=0.1)

        broadcast_mock.assert_called_once_with("R3CX40QFDBP", "com.iotpart.sqe.talkbackhelper.DUMP_TREE", ["--es", "reqId", "REQID801"])
        self.assertEqual(result, [{"id": 1}, {"id": 2}])


    def test_dump_tree_supports_single_result_with_req_id(self):
        client = A11yAdbClient(start_monitor=False)
        log_payload = "A11Y_HELPER DUMP_TREE_RESULT REQID802 [{\"id\":3}]\nA11Y_HELPER DUMP_TREE_END REQID802"

        with patch("talkback_lib.uuid.uuid4", return_value="REQID802-xxxx"), patch.object(client, "check_helper_status", return_value=True), patch.object(client, "clear_logcat", return_value=""), patch.object(client, "_broadcast", return_value="ok"), patch.object(
            client,
            "_run",
            return_value=log_payload,
        ):
            result = client.dump_tree(dev="SER", wait_seconds=0.1)

        self.assertEqual(result, [{"id": 3}])

    def test_check_talkback_status_returns_true_when_talkback_enabled(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "service:a:b:com.google.android.marvin.talkback/.TalkBackService"

        self.assertTrue(client.check_talkback_status(dev="SER"))
        self.assertIn(
            (["shell", "settings", "get", "secure", "enabled_accessibility_services"], "SER"),
            client.calls,
        )
        self.assertNotIn((['shell', 'pm', 'list', 'packages'], 'SER'), client.calls)

    def test_check_talkback_status_returns_false_when_talkback_disabled(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "service:a:b:com.example.custom/.A11yService"

        self.assertFalse(client.check_talkback_status(dev="SER"))

    def test_check_talkback_status_returns_false_on_adb_failure(self):
        client = A11yAdbClient(start_monitor=False)

        def fail_run(args, dev=None, timeout=30.0):  # pylint: disable=unused-argument
            raise RuntimeError("adb failed")

        with patch.object(client, "_run", side_effect=fail_run):
            self.assertFalse(client.check_talkback_status(dev="SER"))

    def test_get_announcements_logs_message_when_talkback_is_off(self):
        client = A11yAdbClient(start_monitor=False)

        with patch.object(client, "check_talkback_status", return_value=False), patch("builtins.print") as print_mock:
            result = client.get_announcements(dev="SER", wait_seconds=0.0)

        self.assertEqual(result, "")
        print_mock.assert_called_once_with("TalkBack이 꺼져 있어 음성을 수집할 수 없습니다")

    def test_read_log_result_filters_by_req_id(self):
        client = FakeA11yClient()
        client.logcat_payload = "\n".join([
            'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reqId":"other"}',
            'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":false,"reqId":"mine","reason":"no"}',
        ])

        result = client._read_log_result("SER", "TARGET_ACTION_RESULT", "mine", wait_seconds=0.1)

        self.assertEqual(result.get("reqId"), "mine")
        self.assertFalse(result.get("success"))




class HelperStatusGuardTest(unittest.TestCase):
    def test_check_helper_status_true_when_service_enabled(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "foo:com.example.custom/.A11yService:bar"

        self.assertTrue(client.check_helper_status(dev="SER"))

    def test_check_helper_status_prints_colored_error_when_disabled(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "foo:bar"

        with patch("builtins.print") as print_mock:
            result = client.check_helper_status(dev="SER")

        self.assertFalse(result)
        self.assertGreaterEqual(print_mock.call_count, 1)
        printed = print_mock.call_args_list[0].args[0]
        self.assertIn("\033[91m", printed)
        self.assertIn("헬퍼 앱의 접근성 서비스가 꺼져 있습니다", printed)
        self.assertIn("\033[0m", printed)

    def test_touch_returns_false_without_action_when_helper_disabled(self):
        client = FakeA11yClient()

        with patch.object(client, "check_helper_status", return_value=False):
            ok = client.touch("SER", name="확인")

        self.assertFalse(ok)
        self.assertEqual([c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]], [])

    def test_check_helper_status_uses_positive_cache_for_same_serial(self):
        client = FakeA11yClient()
        client.enabled_services_payload = "foo:com.example.custom/.A11yService"

        first = client.check_helper_status(dev="SER")
        second = client.check_helper_status(dev="SER")

        self.assertTrue(first)
        self.assertTrue(second)
        settings_calls = [c for c in client.calls if c[0] == ["shell", "settings", "get", "secure", "enabled_accessibility_services"]]
        self.assertEqual(len(settings_calls), 1)

class VerifySpeechTest(unittest.TestCase):
    def test_verify_speech_success_deletes_temp_snapshot(self):
        client = A11yAdbClient(start_monitor=False)

        with patch.object(client, "_take_snapshot") as snap_mock, patch.object(
            client, "get_announcements", return_value="Pet detail card"
        ), patch("talkback_lib.os.remove") as remove_mock, patch("talkback_lib.Path.exists", return_value=True):
            ok = client.verify_speech("SER", expected_regex="Pet.*")

        self.assertTrue(ok)
        snap_mock.assert_called_once_with("SER", "temp_Pet.png")
        remove_mock.assert_called_once_with(Path("temp_Pet.png"))

    def test_verify_speech_failure_saves_error_snapshot(self):
        client = A11yAdbClient(start_monitor=False)

        with patch.object(client, "_take_snapshot"), patch.object(
            client, "get_announcements", return_value="다른 문장"
        ), patch.object(client, "_save_failure_image") as save_mock, patch("talkback_lib.Path.exists", return_value=True):
            ok = client.verify_speech("SER", expected_regex="Pet.*")

        self.assertFalse(ok)
        save_mock.assert_called_once_with(Path("temp_Pet.png"), "Pet.*", "다른 문장")

    def test_save_failure_image_sanitizes_windows_filename_chars(self):
        client = A11yAdbClient(start_monitor=False)
        snapshot_path = Path("dummy.png")

        image_mock = unittest.mock.MagicMock()
        image_mock.convert.return_value = image_mock
        image_mock.size = (200, 100)
        alpha_mock = unittest.mock.MagicMock()
        alpha_mock.convert.return_value = alpha_mock

        with patch("talkback_lib.Image.open", return_value=image_mock), patch(
            "talkback_lib.Image.new", return_value=unittest.mock.MagicMock()
        ), patch("talkback_lib.ImageDraw.Draw"), patch("talkback_lib.ImageFont.truetype", side_effect=OSError), patch(
            "talkback_lib.ImageFont.load_default", return_value=unittest.mock.MagicMock()
        ), patch("talkback_lib.Image.alpha_composite", return_value=alpha_mock):
            client._save_failure_image(snapshot_path, 'Pet:/\*?"<>|', "actual")

        saved_path = alpha_mock.convert.return_value.save.call_args.args[0]
        self.assertEqual(saved_path, Path("error_log/fail_Pet_________.png"))


class SmartMoveFocusTest(unittest.TestCase):
    def test_get_focus_returns_focus_node_from_focus_result(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: FOCUS_RESULT {"success":true,"reqId":"REQID601","node":{"text":"설정","viewIdResourceName":"id/settings"}}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID601-xxxx"):
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "설정")
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0][0]
        self.assertEqual(broadcast[4], ACTION_GET_FOCUS)

    def test_get_focus_keeps_get_focus_result_and_skips_dump_fallback(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: FOCUS_RESULT {"success":true,"reqId":"REQID611","node":{"text":"직접 포커스","viewIdResourceName":"id/direct"}}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID611-xxxx"), patch.object(client, "dump_tree") as dump_mock:
            result = client.get_focus("SER")

        self.assertEqual(result, {"text": "직접 포커스", "viewIdResourceName": "id/direct"})
        dump_mock.assert_not_called()

    def test_get_focus_fallback_prefers_accessibility_focused_node(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: FOCUS_RESULT {"success":true,"reqId":"REQID612","node":{}}'
        dump_nodes = [
            {"text": "일반"},
            {"text": "복구 노드", "accessibilityFocused": True, "viewIdResourceName": "id/recovered"},
        ]

        with patch("talkback_lib.uuid.uuid4", return_value="REQID612-xxxx"), patch.object(client, "dump_tree", return_value=dump_nodes):
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "복구 노드")
        self.assertTrue(result.get("accessibilityFocused"))

    def test_get_focus_fallback_uses_focused_when_accessibility_not_found(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: FOCUS_RESULT {"success":true,"reqId":"REQID613","node":{}}'
        dump_nodes = [
            {"text": "노드1"},
            {"text": "포커스됨", "focused": True, "viewIdResourceName": "id/focused"},
        ]

        with patch("talkback_lib.uuid.uuid4", return_value="REQID613-xxxx"), patch.object(client, "dump_tree", return_value=dump_nodes):
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "포커스됨")
        self.assertTrue(result.get("focused"))

    def test_get_focus_fallback_returns_empty_when_no_focus_flags(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: FOCUS_RESULT {"success":true,"reqId":"REQID614","node":{}}'
        dump_nodes = [{"text": "A"}, {"text": "B", "focused": False, "accessibilityFocused": False}]

        with patch("talkback_lib.uuid.uuid4", return_value="REQID614-xxxx"), patch.object(client, "dump_tree", return_value=dump_nodes):
            result = client.get_focus("SER")

        self.assertEqual(result, {})

    def test_get_focus_fallback_finds_nested_children_focus_node(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: FOCUS_RESULT {"success":true,"reqId":"REQID615","node":{}}'
        dump_nodes = [
            {
                "text": "parent",
                "children": [
                    {"text": "child-1"},
                    {
                        "text": "child-2",
                        "children": [
                            {"text": "nested target", "accessibilityFocused": True, "contentDescription": "Sleep environment Learn more"}
                        ],
                    },
                ],
            }
        ]

        with patch("talkback_lib.uuid.uuid4", return_value="REQID615-xxxx"), patch.object(client, "dump_tree", return_value=dump_nodes):
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "nested target")
        self.assertEqual(result.get("contentDescription"), "Sleep environment Learn more")

    def test_get_focus_accepts_top_level_payload_without_success_field(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"reqId":"REQID616","text":"Map View","contentDescription":"Map View",'
            '"viewIdResourceName":"com.samsung.android.oneconnect:id/mapview_button",'
            '"boundsInScreen":{"l":708,"t":142,"r":810,"b":286},"accessibilityFocused":true}'
        )

        with patch("talkback_lib.uuid.uuid4", return_value="REQID616-xxxx"), patch.object(client, "dump_tree") as dump_mock:
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "Map View")
        self.assertTrue(result.get("accessibilityFocused"))
        dump_mock.assert_not_called()
        self.assertFalse(client.last_get_focus_trace.get("success_field_present"))
        self.assertFalse(client.last_get_focus_trace.get("success_false_top_level_dump_attempted"))
        self.assertFalse(client.last_get_focus_trace.get("success_false_top_level_dump_found"))
        self.assertTrue(client.last_get_focus_trace.get("success_false_top_level_dump_skipped"))
        self.assertEqual(client.last_get_focus_trace.get("dump_skip_reason"), "strong_top_level_payload")

    def test_get_focus_accepts_top_level_payload_when_success_false(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"success":false,"reqId":"REQID617","contentDescription":"Map View",'
            '"viewIdResourceName":"com.samsung.android.oneconnect:id/mapview_button",'
            '"boundsInScreen":{"l":708,"t":142,"r":810,"b":286}}'
        )

        with patch("talkback_lib.uuid.uuid4", return_value="REQID617-xxxx"), patch.object(client, "dump_tree") as dump_mock:
            result = client.get_focus("SER")

        self.assertEqual(result.get("contentDescription"), "Map View")
        self.assertEqual(result.get("viewIdResourceName"), "com.samsung.android.oneconnect:id/mapview_button")
        dump_mock.assert_not_called()
        self.assertFalse(client.last_get_focus_trace.get("success_false_top_level_dump_attempted"))
        self.assertFalse(client.last_get_focus_trace.get("success_false_top_level_dump_found"))
        self.assertTrue(client.last_get_focus_trace.get("success_false_top_level_dump_skipped"))
        self.assertEqual(client.last_get_focus_trace.get("final_payload_source"), "top_level")
        self.assertEqual(client.last_get_focus_trace.get("final_focus_reason"), "success_false_top_level_policy_skip_dump")

    def test_get_focus_accepts_success_false_payload_with_merged_label_and_class(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"success":false,"reqId":"REQID617","mergedLabel":"Map View","className":"android.widget.Button",'
            '"boundsInScreen":{"l":708,"t":142,"r":810,"b":286}}'
        )

        with patch("talkback_lib.uuid.uuid4", return_value="REQID617-xxxx"), patch.object(client, "dump_tree") as dump_mock:
            result = client.get_focus("SER")

        self.assertEqual(result.get("mergedLabel"), "Map View")
        self.assertEqual(result.get("className"), "android.widget.Button")
        self.assertTrue(client.last_get_focus_trace.get("top_level_payload_sufficient"))
        dump_mock.assert_not_called()

    def test_get_focus_success_false_weak_top_level_payload_keeps_dump_fallback(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"success":false,"reqId":"REQID617A","focused":true}'
        )
        dump_nodes = [{"text": "복구 노드", "accessibilityFocused": True, "viewIdResourceName": "id/recovered"}]

        with patch("talkback_lib.uuid.uuid4", return_value="REQID617A-xxxx"), patch.object(client, "dump_tree", return_value=dump_nodes) as dump_mock:
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "복구 노드")
        dump_mock.assert_called_once()
        self.assertFalse(client.last_get_focus_trace.get("success_false_top_level_dump_skipped"))
        self.assertEqual(client.last_get_focus_trace.get("dump_skip_reason"), "")

    def test_get_focus_fast_mode_keeps_bounds_only_top_level_without_dump(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"success":false,"reqId":"REQID617","boundsInScreen":{"l":10,"t":20,"r":40,"b":80}}'
        )
        dump_nodes = [{"text": "복구 노드", "accessibilityFocused": True}]

        with patch("talkback_lib.uuid.uuid4", return_value="REQID617-xxxx"), patch.object(
            client, "dump_tree", return_value=dump_nodes
        ) as dump_mock:
            result = client.get_focus("SER", mode="fast")

        self.assertEqual(result.get("boundsInScreen"), {"l": 10, "t": 20, "r": 40, "b": 80})
        self.assertTrue(client.last_get_focus_trace.get("success_false_top_level_dump_skipped"))
        self.assertEqual(client.last_get_focus_trace.get("mode"), "fast")
        dump_mock.assert_not_called()

    def test_get_focus_normal_mode_uses_dump_for_bounds_only_top_level(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"success":false,"reqId":"REQID617","boundsInScreen":{"l":10,"t":20,"r":40,"b":80}}'
        )
        dump_nodes = [{"text": "복구 노드", "accessibilityFocused": True, "viewIdResourceName": "id/recovered"}]

        with patch("talkback_lib.uuid.uuid4", return_value="REQID617-xxxx"), patch.object(
            client, "dump_tree", return_value=dump_nodes
        ) as dump_mock:
            result = client.get_focus("SER", mode="normal")

        self.assertEqual(result.get("text"), "복구 노드")
        self.assertEqual(client.last_get_focus_trace.get("mode"), "normal")
        self.assertTrue(client.last_get_focus_trace.get("success_false_top_level_dump_attempted"))
        dump_mock.assert_called_once()

    def test_get_focus_flags_only_payload_is_meaningful(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"success":false,"reqId":"REQID618","focused":false,"accessibilityFocused":true}'
        )

        with patch("talkback_lib.uuid.uuid4", return_value="REQID618-xxxx"), patch.object(client, "dump_tree") as dump_mock:
            result = client.get_focus("SER")

        self.assertTrue(result.get("accessibilityFocused"))
        dump_mock.assert_called_once()

    def test_get_focus_success_false_top_level_payload_replaced_by_dump_focus_node(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"success":false,"reqId":"REQID619","contentDescription":"Map View"}'
        )
        dump_nodes = [
            {"text": "general"},
            {"text": "복구 노드", "accessibilityFocused": True, "viewIdResourceName": "id/recovered"},
        ]

        with (
            patch("talkback_lib.uuid.uuid4", return_value="REQID619-xxxx"),
            patch.object(client, "dump_tree", return_value=dump_nodes) as dump_mock,
        ):
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "복구 노드")
        self.assertTrue(result.get("accessibilityFocused"))
        self.assertEqual(client.last_get_focus_trace.get("focus_payload_source"), "fallback_dump")
        self.assertEqual(client.last_get_focus_trace.get("final_payload_source"), "fallback_dump")
        self.assertTrue(client.last_get_focus_trace.get("success_false_top_level_dump_attempted"))
        self.assertTrue(client.last_get_focus_trace.get("success_false_top_level_dump_found"))
        dump_mock.assert_called_once()

    def test_get_focus_skips_helper_status_probe_when_recent_cache_is_ready(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: FOCUS_RESULT '
            '{"success":true,"reqId":"REQID620","node":{"text":"cached","viewIdResourceName":"id/cached"}}'
        )
        client._update_helper_status_cache(serial="SER", result=True)

        with patch("talkback_lib.uuid.uuid4", return_value="REQID620-xxxx"), patch.object(
            client, "check_helper_status", side_effect=AssertionError("helper status should be cached")
        ):
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "cached")

    def test_get_focus_parse_error_sets_reason_and_uses_fallback(self):
        client = FakeA11yClient()
        dump_nodes = [{"text": "복구", "accessibilityFocused": True}]

        with patch("talkback_lib.uuid.uuid4", return_value="REQID619-xxxx"), patch.object(
            client, "_read_log_result", side_effect=RuntimeError("FOCUS_RESULT JSON 파싱 실패")
        ), patch.object(client, "dump_tree", return_value=dump_nodes):
            result = client.get_focus("SER")

        self.assertEqual(result.get("text"), "복구")
        self.assertEqual(client.last_get_focus_trace.get("empty_reason"), "parse_error")
        self.assertEqual(client.last_get_focus_trace.get("fallback_reason"), "parse_error")

    def test_reset_focus_history_broadcasts_reset_for_string_device(self):
        client = FakeA11yClient()

        with patch("builtins.print") as print_mock:
            client.reset_focus_history("SER-RESET")

        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][-1][0]
        self.assertEqual(
            broadcast,
            [
                "shell", "am", "broadcast", "-a", ACTION_COMMAND,
                "-p", "com.example.custom",
                "--es", "command", "reset",
            ],
        )
        print_mock.assert_called_once_with("[SER-RESET] Focus history has been explicitly reset.")

    def test_reset_focus_history_accepts_device_id_object(self):
        client = FakeA11yClient()

        with patch("builtins.print") as print_mock:
            client.reset_focus_history(DeviceWithId("DEVICE-ID-01"))

        print_mock.assert_called_once_with("[DEVICE-ID-01] Focus history has been explicitly reset.")

    def test_move_focus_smart_uses_android_side_smart_next_status(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SMART_NAV_RESULT {"success":true,"status":"scrolled","reqId":"REQID701"}'

        with patch.object(client, "check_helper_status", return_value=True), patch(
            "talkback_lib.uuid.uuid4", return_value="REQID701-xxxx"
        ):
            result = client.move_focus_smart("SER", direction="next")

        self.assertEqual(result, "scrolled")
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][-1][0]
        self.assertEqual(broadcast[4], ACTION_SMART_NEXT)

    def test_move_focus_smart_returns_failed_when_status_invalid(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SMART_NAV_RESULT {"success":true,"status":"unknown","reqId":"REQID702"}'

        with patch.object(client, "check_helper_status", return_value=True), patch(
            "talkback_lib.uuid.uuid4", return_value="REQID702-xxxx"
        ):
            result = client.move_focus_smart("SER", direction="next")

        self.assertEqual(result, "failed")



    def test_move_focus_smart_maps_legacy_bottom_bar_status_to_moved(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SMART_NAV_RESULT {"success":true,"status":"moved_to_bottom_bar_direct","reqId":"REQID705"}'

        with patch.object(client, "check_helper_status", return_value=True), patch(
            "talkback_lib.uuid.uuid4", return_value="REQID705-xxxx"
        ):
            result = client.move_focus_smart("SER", direction="next")

        self.assertEqual(result, "moved")

    def test_move_focus_smart_uses_detail_when_status_unknown(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SMART_NAV_RESULT {"success":true,"status":"unknown","detail":"moved_aligned","reqId":"REQID706"}'

        with patch.object(client, "check_helper_status", return_value=True), patch(
            "talkback_lib.uuid.uuid4", return_value="REQID706-xxxx"
        ):
            result = client.move_focus_smart("SER", direction="next")

        self.assertEqual(result, "moved")

    def test_move_focus_smart_marks_terminal_when_end_of_sequence_detail_returned(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: SMART_NAV_RESULT '
            '{"success":false,"status":"failed","detail":"end_of_sequence","flags":["terminal"],"reqId":"REQID707"}'
        )

        with patch.object(client, "check_helper_status", return_value=True), patch(
            "talkback_lib.uuid.uuid4", return_value="REQID707-xxxx"
        ):
            result = client.move_focus_smart("SER", direction="next")

        self.assertEqual(result, "failed")
        self.assertTrue(client.last_smart_nav_terminal)
        self.assertEqual(client.last_smart_nav_result.get("detail"), "end_of_sequence")

    def test_move_focus_smart_next_does_not_clear_logcat(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SMART_NAV_RESULT {"success":true,"status":"moved","reqId":"REQID704"}'

        with patch.object(client, "check_helper_status", return_value=True), patch(
            "talkback_lib.uuid.uuid4", return_value="REQID704-xxxx"
        ):
            result = client.move_focus_smart("SER", direction="next")

        self.assertEqual(result, "moved")
        logcat_clear_calls = [args for args, _ in client.calls if args == ["logcat", "-c"]]
        self.assertEqual(logcat_clear_calls, [])

    def test_move_focus_smart_next_does_not_call_dump_or_get_focus(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SMART_NAV_RESULT {"success":true,"status":"moved","reqId":"REQID703"}'

        with patch.object(client, "check_helper_status", return_value=True), patch(
            "talkback_lib.uuid.uuid4", return_value="REQID703-xxxx"
        ), patch.object(client, "dump_tree", side_effect=AssertionError("dump_tree should not be called")), patch.object(
            client, "get_focus", side_effect=AssertionError("get_focus should not be called")
        ):
            result = client.move_focus_smart("SER", direction="next")

        self.assertEqual(result, "moved")

    def test_move_focus_smart_uses_recent_helper_cache(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: SMART_NAV_RESULT {"success":true,"status":"moved","reqId":"REQID709"}'
        client._update_helper_status_cache(serial="SER", result=True)

        with patch.object(client, "check_helper_status", side_effect=AssertionError("helper status should be cached")), patch(
            "talkback_lib.uuid.uuid4", return_value="REQID709-xxxx"
        ):
            result = client.move_focus_smart("SER", direction="next")

        self.assertEqual(result, "moved")


    def test_press_back_and_recover_focus_matches_anchor_without_select(self):
        client = FakeA11yClient()

        with patch.object(client, "get_focus", return_value={"text": "설정"}) as focus_mock, patch.object(
            client, "select", return_value=False
        ) as select_mock:
            result = client.press_back_and_recover_focus(
                "SER",
                expected_parent_anchor="설정",
                wait_seconds=0,
                retry=2,
                type_="a",
            )

        self.assertTrue(result["back_sent"])
        self.assertTrue(result["focus_found"])
        self.assertTrue(result["focus_recovered"])
        self.assertEqual(result["recovered_by"], "anchor_match")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["current_label"], "설정")
        select_mock.assert_not_called()
        focus_mock.assert_called_once()

    def test_press_back_and_recover_focus_retries_select_when_anchor_mismatch(self):
        client = FakeA11yClient()

        with patch.object(client, "get_focus", side_effect=[{"text": "다른 항목"}, {"text": "상위 목록"}]), patch.object(
            client, "select", side_effect=[False, True]
        ) as select_mock:
            result = client.press_back_and_recover_focus(
                "SER",
                expected_parent_anchor="상위 목록",
                wait_seconds=0,
                retry=2,
                type_="a",
            )

        self.assertTrue(result["back_sent"])
        self.assertTrue(result["focus_recovered"])
        self.assertEqual(result["recovered_by"], "select_anchor")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["current_label"], "상위 목록")
        self.assertEqual(select_mock.call_count, 2)

    def test_press_back_and_recover_focus_returns_partial_when_select_fails(self):
        client = FakeA11yClient()

        with patch.object(client, "get_focus", return_value={"text": "다른 항목"}), patch.object(
            client, "select", return_value=False
        ) as select_mock:
            result = client.press_back_and_recover_focus(
                "SER",
                expected_parent_anchor="상위 목록",
                wait_seconds=0,
                retry=1,
            )

        self.assertTrue(result["back_sent"])
        self.assertFalse(result["focus_recovered"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["reason"], "anchor_mismatch_and_select_failed")
        select_mock.assert_called_once()

    def test_move_focus_smart_non_next_falls_back_to_move_focus(self):
        client = FakeA11yClient()

        with patch.object(client, "move_focus", return_value=True) as move_mock:
            result = client.move_focus_smart("SER", direction="prev")

        self.assertEqual(result, "moved")
        move_mock.assert_called_once_with(dev="SER", direction="prev")



class FocusHelpersTest(unittest.TestCase):
    def test_client_algorithm_version_is_updated(self):
        self.assertEqual(CLIENT_ALGORITHM_VERSION, "1.7.37")

    def test_extract_visible_label_from_focus_prefers_text(self):
        focus_node = {"text": "  Visible Text  ", "contentDescription": "Desc"}

        self.assertEqual(A11yAdbClient.extract_visible_label_from_focus(focus_node), "Visible Text")

    def test_extract_visible_label_from_focus_falls_back_to_content_description(self):
        focus_node = {"text": "   ", "contentDescription": "  Desc Label  ", "talkback": "TB"}

        self.assertEqual(A11yAdbClient.extract_visible_label_from_focus(focus_node), "Desc Label")

    def test_extract_visible_label_from_focus_returns_empty_for_invalid_input(self):
        self.assertEqual(A11yAdbClient.extract_visible_label_from_focus(None), "")
        self.assertEqual(A11yAdbClient.extract_visible_label_from_focus("not-a-dict"), "")

    def test_extract_visible_label_from_focus_uses_child_text_when_parent_is_empty(self):
        focus_node = {
            "text": " ",
            "contentDescription": "",
            "children": [
                {"text": "  Child Visible Text  "},
            ],
        }

        self.assertEqual(A11yAdbClient.extract_visible_label_from_focus(focus_node), "Child Visible Text")

    def test_extract_visible_label_from_focus_uses_child_content_description_when_parent_is_empty(self):
        focus_node = {
            "text": "",
            "contentDescription": "   ",
            "children": [
                {"text": " "},
                {"contentDescription": "  Child Desc  "},
            ],
        }

        self.assertEqual(A11yAdbClient.extract_visible_label_from_focus(focus_node), "Child Desc")

    def test_extract_visible_label_from_focus_returns_first_valid_value_in_dfs_preorder(self):
        focus_node = {
            "text": "",
            "children": [
                {
                    "text": "",
                    "children": [
                        {"text": "  First DFS Value  "},
                    ],
                },
                {"text": "Second Value"},
            ],
        }

        self.assertEqual(A11yAdbClient.extract_visible_label_from_focus(focus_node), "First DFS Value")

    def test_normalize_for_comparison_applies_whitespace_case_and_phrase_cleanup(self):
        text = "  설정\n\t버튼   선택됨 | Double Tap to Activate  "

        self.assertEqual(A11yAdbClient.normalize_for_comparison(text), "설정")

    def test_collect_focus_step_without_move_collects_current_state(self):
        client = CollectFocusStepClient()

        step = client.collect_focus_step(dev="SERIAL", step_index=3, move=False, wait_seconds=0.2)

        self.assertIsNone(step["move_result"])
        self.assertEqual(client.move_focus_calls, [])
        self.assertEqual(client.move_focus_smart_calls, [])
        self.assertEqual(step["step_index"], 3)
        self.assertEqual(step["visible_label"], "Hello")
        self.assertEqual(step["normalized_visible_label"], "hello")
        self.assertEqual(step["focus_text"], "  Hello  ")
        self.assertEqual(step["focus_content_description"], "ignored")
        self.assertEqual(step["focus_view_id"], "com.example:id/hello")
        self.assertEqual(step["focus_bounds"], "1,2,3,4")
        self.assertEqual(step["dump_tree_nodes"], [])
        self.assertEqual(step["step_dump_tree_elapsed_sec"], 0.0)
        self.assertFalse(step["step_dump_tree_used"])
        self.assertEqual(step["step_dump_tree_reason"], "focus_payload_sufficient")

    def test_collect_focus_step_move_next_uses_move_focus_smart(self):
        client = CollectFocusStepClient()

        step = client.collect_focus_step(dev="SERIAL", step_index=1, move=True, direction="next", wait_seconds=0.2)

        self.assertEqual(client.move_focus_smart_calls, [("SERIAL", "next")])
        self.assertEqual(client.move_focus_calls, [])
        self.assertEqual(step["move_result"], "moved")

    def test_collect_focus_step_includes_partial_merged_and_normalized_values(self):
        client = CollectFocusStepClient()
        client.partial_payload = ["  설정  ", "버튼"]
        client.focus_payload = {"contentDescription": "설정 버튼"}

        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertEqual(step["partial_announcements"], ["  설정  ", "버튼"])
        self.assertEqual(step["merged_announcement"], "설정 버튼")
        self.assertEqual(step["normalized_announcement"], "설정")
        self.assertEqual(step["last_announcements"], ["  설정  ", "버튼"])
        self.assertEqual(step["last_merged_announcement"], "설정 버튼")
        self.assertEqual(client.merged_calls, [])

    def test_collect_focus_step_visible_fallback_uses_accessibility_label_when_text_empty(self):
        client = CollectFocusStepClient()
        client.focus_payload = {
            "text": " ",
            "contentDescription": " ",
            "accessibilityLabel": "Settings",
            "viewIdResourceName": "com.example:id/settings",
        }

        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertEqual(step["visible_label"], "Settings")
        self.assertEqual(step["normalized_visible_label"], "settings")

    def test_collect_focus_step_reuses_get_focus_fallback_nodes_without_step_dump(self):
        client = CollectFocusStepClient()

        def _focus_with_trace(dev=None, wait_seconds: float = 2.0):
            client.last_get_focus_trace = {
                "fallback_dump_nodes": [{"text": "fallback-node", "accessibilityFocused": True}],
                "fallback_dump_elapsed_sec": 1.234,
                "empty_reason": "empty_json",
                "fallback_used": True,
                "fallback_found": True,
                "req_id": "REQID-TRACE",
                "total_elapsed_sec": 2.345,
            }
            return {"text": "복구 포커스"}

        client.get_focus = _focus_with_trace
        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertEqual(step["dump_tree_nodes"], [{"text": "fallback-node", "accessibilityFocused": True}])
        self.assertEqual(step["get_focus_fallback_dump_elapsed_sec"], 1.234)
        self.assertEqual(step["step_dump_tree_elapsed_sec"], 0.0)
        self.assertFalse(step["step_dump_tree_used"])
        self.assertEqual(step["step_dump_tree_reason"], "fallback_nodes_reused")

    def test_collect_focus_step_falls_back_to_top_level_talkback_label_when_speech_empty(self):
        client = CollectFocusStepClient()
        client.partial_payload = []
        client.focus_payload = {
            "text": "",
            "contentDescription": "",
            "talkbackLabel": "우리 집",
            "viewIdResourceName": "com.example:id/location",
            "boundsInScreen": {"l": 1, "t": 2, "r": 3, "b": 4},
        }

        def _focus_with_trace(dev=None, wait_seconds: float = 2.0):
            client.last_get_focus_trace = {
                "top_level_payload_sufficient": True,
                "final_payload_source": "top_level",
            }
            return dict(client.focus_payload)

        client.get_focus = _focus_with_trace
        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertEqual(step["merged_announcement"], "우리 집")
        self.assertEqual(step["normalized_announcement"], "우리 집")

    def test_collect_focus_step_falls_back_to_top_level_merged_label_when_speech_empty(self):
        client = CollectFocusStepClient()
        client.partial_payload = []
        client.focus_payload = {
            "text": "",
            "contentDescription": "",
            "mergedLabel": "QR code",
            "viewIdResourceName": "com.example:id/qr",
            "boundsInScreen": {"l": 1, "t": 2, "r": 3, "b": 4},
        }

        def _focus_with_trace(dev=None, wait_seconds: float = 2.0):
            client.last_get_focus_trace = {
                "top_level_payload_sufficient": True,
                "final_payload_source": "top_level",
            }
            return dict(client.focus_payload)

        client.get_focus = _focus_with_trace
        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertEqual(step["merged_announcement"], "QR code")
        self.assertEqual(step["normalized_announcement"], "qr code")

    def test_collect_focus_step_does_not_force_fallback_when_top_level_payload_not_sufficient(self):
        client = CollectFocusStepClient()
        client.partial_payload = []
        client.focus_payload = {
            "talkbackLabel": "우리 집",
            "viewIdResourceName": "com.example:id/location",
            "boundsInScreen": {"l": 1, "t": 2, "r": 3, "b": 4},
        }

        def _focus_with_trace(dev=None, wait_seconds: float = 2.0):
            client.last_get_focus_trace = {
                "top_level_payload_sufficient": False,
                "final_payload_source": "top_level",
            }
            return dict(client.focus_payload)

        client.get_focus = _focus_with_trace
        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertEqual(step["merged_announcement"], "")
        self.assertEqual(step["normalized_announcement"], "")

    def test_collect_focus_step_does_not_override_existing_announcement_with_top_level_fallback(self):
        client = CollectFocusStepClient()
        client.partial_payload = ["기존 안내"]
        client.focus_payload = {
            "talkbackLabel": "대체 안내",
            "viewIdResourceName": "com.example:id/location",
            "boundsInScreen": {"l": 1, "t": 2, "r": 3, "b": 4},
        }

        def _focus_with_trace(dev=None, wait_seconds: float = 2.0):
            client.last_get_focus_trace = {
                "top_level_payload_sufficient": True,
                "final_payload_source": "top_level",
            }
            return dict(client.focus_payload)

        client.get_focus = _focus_with_trace
        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertEqual(step["merged_announcement"], "기존 안내")
        self.assertEqual(step["normalized_announcement"], "기존 안내")

    def test_collect_focus_step_waits_extra_until_idle_timeout(self):
        client = CollectFocusStepClient()
        responses = [["안내 1"], ["안내 2"], []]
        clock = {"value": 0.0}

        def fake_monotonic():
            return clock["value"]

        def fake_sleep(seconds):
            clock["value"] += seconds

        def fake_get_partial_announcements(dev=None, wait_seconds: float = 2.0, only_new: bool = True):
            del dev, only_new
            clock["value"] += wait_seconds
            payload = responses.pop(0) if responses else []
            client.last_announcements = list(payload)
            client.last_merged_announcement = " ".join(item.strip() for item in payload if item.strip())
            return list(payload)

        with patch.object(client, "get_partial_announcements", side_effect=fake_get_partial_announcements), patch(
            "talkback_lib.time.monotonic", side_effect=fake_monotonic
        ), patch(
            "talkback_lib.time.sleep", side_effect=fake_sleep
        ):
            step = client.collect_focus_step(
                dev="SERIAL",
                move=False,
                wait_seconds=0.2,
                announcement_wait_seconds=0.2,
                announcement_idle_wait_seconds=0.3,
                announcement_max_extra_wait_seconds=1.0,
            )

        self.assertEqual(step["partial_announcements"], ["안내 1", "안내 2"])
        self.assertGreaterEqual(step["announcement_extra_wait_sec"], 0.3)

    def test_collect_focus_step_stability_wait_stops_at_max_extra_wait(self):
        client = CollectFocusStepClient()
        responses = [["안내 1"], ["안내 2"], ["안내 3"], ["안내 4"], ["안내 5"], ["안내 6"]]
        clock = {"value": 0.0}

        def fake_monotonic():
            return clock["value"]

        def fake_sleep(seconds):
            clock["value"] += seconds

        def fake_get_partial_announcements(dev=None, wait_seconds: float = 2.0, only_new: bool = True):
            del dev, only_new
            clock["value"] += wait_seconds
            payload = responses.pop(0) if responses else []
            client.last_announcements = list(payload)
            client.last_merged_announcement = " ".join(item.strip() for item in payload if item.strip())
            return list(payload)

        with patch.object(client, "get_partial_announcements", side_effect=fake_get_partial_announcements), patch(
            "talkback_lib.time.monotonic", side_effect=fake_monotonic
        ), patch(
            "talkback_lib.time.sleep", side_effect=fake_sleep
        ):
            step = client.collect_focus_step(
                dev="SERIAL",
                move=False,
                wait_seconds=0.2,
                announcement_wait_seconds=0.2,
                announcement_idle_wait_seconds=0.5,
                announcement_max_extra_wait_seconds=0.35,
            )

        self.assertEqual(step["partial_announcements"], ["안내 1", "안내 2", "안내 3", "안내 4"])
        self.assertGreaterEqual(step["announcement_extra_wait_sec"], 0.35)

    def test_collect_focus_step_trims_previous_prefix_from_selected_speech(self):
        client = CollectFocusStepClient()
        client.last_merged_announcement = "Navigate up"
        client.partial_payload = ["Navigate up Special suggestions Get helpful offers or news on products. Off"]

        step = client.collect_focus_step(
            dev="SERIAL",
            move=False,
            wait_seconds=0.2,
            announcement_wait_seconds=0.2,
            announcement_idle_wait_seconds=0.0,
            announcement_max_extra_wait_seconds=0.0,
        )

        self.assertEqual(
            step["merged_announcement"],
            "Special suggestions Get helpful offers or news on products. Off",
        )
        self.assertEqual(
            step["partial_announcements"],
            ["Navigate up Special suggestions Get helpful offers or news on products. Off"],
        )

    def test_collect_focus_step_visible_anchor_trim_without_baseline(self):
        client = CollectFocusStepClient()
        client.last_merged_announcement = ""
        client.partial_payload = ["Navigate up Special suggestions Get helpful offers or news on products. Off"]
        client.focus_payload = {"text": "Special suggestions Get helpful offers or news on products."}

        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertTrue(step["snapshot_contaminated"])
        self.assertEqual(step["trim_reason"], "visible_anchor_prefix_trim")
        self.assertTrue(step["trim_applied"])
        self.assertEqual(
            step["merged_announcement"],
            "Special suggestions Get helpful offers or news on products. Off",
        )
        self.assertEqual(step["announcement_stable_source"], "trimmed_candidate")
        self.assertFalse(step["used_snapshot"])

    def test_collect_focus_step_keeps_normal_trailing_state_without_trim(self):
        client = CollectFocusStepClient()
        client.last_merged_announcement = ""
        client.partial_payload = ["Sync favourites On"]
        client.focus_payload = {"text": "Sync favourites"}

        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertFalse(step["trim_applied"])
        self.assertEqual(step["merged_announcement"], "Sync favourites On")
        self.assertEqual(step["trim_reason"], "")

    def test_collect_focus_step_does_not_trim_when_visible_anchor_not_found(self):
        client = CollectFocusStepClient()
        client.last_merged_announcement = ""
        client.partial_payload = ["Weather card added successfully"]
        client.focus_payload = {"text": "Special suggestions Get helpful offers or news on products."}

        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertFalse(step["trim_applied"])
        self.assertEqual(step["merged_announcement"], "Weather card added successfully")
        self.assertFalse(step["snapshot_contaminated"])

    def test_collect_focus_step_prefers_trimmed_candidate_over_contaminated_snapshot(self):
        client = CollectFocusStepClient()
        client.last_merged_announcement = ""
        client.partial_payload = ["Navigate up Special suggestions Get helpful offers or news on products. Off"]
        client.focus_payload = {"text": "Special suggestions Get helpful offers or news on products."}

        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertTrue(step["snapshot_contaminated"])
        self.assertFalse(step["used_snapshot"])
        self.assertEqual(step["announcement_stable_source"], "trimmed_candidate")
        self.assertEqual(step["snapshot_reason"], "prefix_before_visible_anchor")

    def test_collect_focus_step_keeps_contaminated_snapshot_as_fallback_when_no_anchor(self):
        client = CollectFocusStepClient()
        client.last_merged_announcement = ""
        client.partial_payload = ["Navigate up Special suggestions Get helpful offers or news on products. Off"]
        client.focus_payload = {"text": ""}

        step = client.collect_focus_step(dev="SERIAL", move=False, wait_seconds=0.2)

        self.assertEqual(
            step["merged_announcement"],
            "Navigate up Special suggestions Get helpful offers or news on products. Off",
        )
        self.assertTrue(step["used_snapshot"])
        self.assertFalse(step["trim_applied"])


if __name__ == "__main__":
    unittest.main()
