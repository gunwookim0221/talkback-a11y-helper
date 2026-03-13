import unittest
from unittest.mock import patch

from talkback_lib import (
    ACTION_CHECK_TARGET,
    ACTION_CLICK_TARGET,
    ACTION_FOCUS_TARGET,
    ACTION_SCROLL,
    ACTION_SET_TEXT,
    A11yAdbClient,
)


class Dev:
    def __init__(self, serial: str):
        self.serial = serial


class FakeA11yClient(A11yAdbClient):
    def __init__(self):
        super().__init__(adb_path="adb", package_name="com.example.custom", start_monitor=False)
        self.calls = []
        self.logcat_payload = ""
        self.needs_update = False
        self.package_list_payload = "package:com.example.custom"
        self.enabled_services_payload = ""

    def _run(self, args, dev=None, timeout: float = 10.0):  # pylint: disable=unused-argument
        self.calls.append((args, dev))
        if args == ["logcat", "-c"]:
            return ""
        if args[:3] == ["shell", "am", "broadcast"]:
            return "broadcast ok"
        if args == ["logcat", "-d"]:
            return self.logcat_payload
        if args == ["logcat", "-v", "time", "-d"]:
            return self.logcat_payload
        if args == ["shell", "pm", "list", "packages"]:
            return self.package_list_payload
        if args == ["shell", "settings", "get", "secure", "enabled_accessibility_services"]:
            return self.enabled_services_payload
        if args[:3] == ["shell", "input", "text"]:
            return ""
        raise AssertionError(f"unexpected args: {args}")


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
                "--es", "targetName", "'설정'",
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

    def test_select_uses_focus_target_and_returns_true(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reqId":"REQID003"}'

        with patch("talkback_lib.uuid.uuid4", return_value="REQID003-xxxx"):
            ok = client.select("SER", name="다음", wait_=1, type_="t", index_=3)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_FOCUS_TARGET,
                "-p", "com.example.custom",
                "--es", "targetName", "'다음'",
                "--es", "targetType", "t",
                "--ei", "targetIndex", "3",
                "--ez", "isLongClick", "false",
                "--es", "reqId", "REQID003",
            ],
        )


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
        self.assertIn("'확인'", broadcast)
        self.assertIn("targetId", broadcast)
        self.assertIn("'com.example:id/btn_ok'", broadcast)
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
        self.assertIn("'로그인'", broadcast)
        self.assertIn("targetId", broadcast)
        self.assertIn("'.*id/btn_login'", broadcast)

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
        isin_mock.assert_any_call("SER", "설정", wait_=0, type_="t")

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

        def fake_run(args, dev=None, timeout=10.0):
            calls.append((args, dev))
            return ""

        with patch.object(client, "_run", side_effect=fake_run):
            client.clear_logcat()

        self.assertEqual(calls, [(["logcat", "-c"], None)])

    def test_run_applies_default_serial_when_dev_is_missing(self):
        client = A11yAdbClient(adb_path="adb", dev_serial="R3CX40QFDBP", start_monitor=False)

        with patch("talkback_lib.subprocess.run") as run_mock:
            run_mock.return_value.stdout = "ok"
            result = client._run(["devices"])

        self.assertEqual(result, "ok")
        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[:3], ["adb", "-s", "R3CX40QFDBP"])

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

        with patch("talkback_lib.uuid.uuid4", return_value="REQID801-xxxx"), patch.object(client, "clear_logcat", return_value=""), patch.object(client, "_broadcast", return_value="ok") as broadcast_mock, patch.object(
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

        with patch("talkback_lib.uuid.uuid4", return_value="REQID802-xxxx"), patch.object(client, "clear_logcat", return_value=""), patch.object(client, "_broadcast", return_value="ok"), patch.object(
            client,
            "_run",
            return_value=log_payload,
        ):
            result = client.dump_tree(dev="SER", wait_seconds=0.1)

        self.assertEqual(result, [{"id": 3}])

    def test_check_talkback_status_uses_helper_logs_when_helper_installed(self):
        client = FakeA11yClient()
        client.package_list_payload = "package:com.example.custom\npackage:other"
        client.logcat_payload = "01-01 00:00:00.000 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 안내"

        self.assertTrue(client.check_talkback_status(dev="SER"))

    def test_check_talkback_status_falls_back_to_settings_without_helper(self):
        client = FakeA11yClient()
        client.package_list_payload = "package:com.other"
        client.enabled_services_payload = "service:a:b:com.google.android.marvin.talkback/.TalkBackService"

        self.assertTrue(client.check_talkback_status(dev="SER"))

    def test_check_talkback_status_returns_false_on_adb_failure(self):
        client = A11yAdbClient(start_monitor=False)

        def fail_run(args, dev=None, timeout=10.0):  # pylint: disable=unused-argument
            raise RuntimeError("adb failed")

        with patch.object(client, "_run", side_effect=fail_run):
            self.assertFalse(client.check_talkback_status(dev="SER"))

    def test_get_announcements_logs_message_when_talkback_is_off(self):
        client = A11yAdbClient(start_monitor=False)

        with patch.object(client, "check_talkback_status", return_value=False), patch("builtins.print") as print_mock:
            result = client.get_announcements(dev="SER", wait_seconds=0.0)

        self.assertEqual(result, [])
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


if __name__ == "__main__":
    unittest.main()
