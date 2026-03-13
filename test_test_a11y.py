import unittest
from unittest.mock import patch

from test_a11y import (
    ACTION_CHECK_TARGET,
    ACTION_CLICK_TARGET,
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
        raise AssertionError(f"unexpected args: {args}")


class TouchIsinTest(unittest.TestCase):
    def test_touch_success_sends_new_extras_and_waits_speech(self):
        client = FakeA11yClient()
        dev = Dev("SER123")
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reason":"ok"}'

        with patch.object(client, "_wait_for_speech_if_needed") as wait_mock:
            ok = client.touch(dev, name="확인", wait_=1, type_="b", index_=2, long_=True)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(broadcast[1], dev)
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_CLICK_TARGET,
                "-p", "com.example.custom",
                "--es", "targetName", "확인",
                "--es", "targetType", "b",
                "--ei", "targetIndex", "2",
                "--ez", "isLongClick", "true",
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

        with patch("test_a11y.time.monotonic", side_effect=fake_monotonic), patch("test_a11y.time.sleep", side_effect=fake_sleep):
            ok = client.touch(dev, name="없음", wait_=1, type_="a", index_=0, long_=False)

        self.assertFalse(ok)
        broadcast_count = len([c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]])
        self.assertGreaterEqual(broadcast_count, 2)

    def test_isin_uses_check_target_and_returns_true(self):
        client = FakeA11yClient()
        dev = "SERIAL"
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":true,"reason":"found"}'

        ok = client.isin(dev, name="설정", wait_=1, type_="r", index_=1)

        self.assertTrue(ok)
        broadcast = [c for c in client.calls if c[0][:3] == ["shell", "am", "broadcast"]][0]
        self.assertEqual(
            broadcast[0],
            [
                "shell", "am", "broadcast", "-a", ACTION_CHECK_TARGET,
                "-p", "com.example.custom",
                "--es", "targetName", "설정",
                "--es", "targetType", "r",
                "--ei", "targetIndex", "1",
                "--ez", "isLongClick", "false",
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

        with patch("test_a11y.time.monotonic", side_effect=fake_monotonic), patch("test_a11y.time.sleep", side_effect=fake_sleep):
            client.touch("SER", name="없음", wait_=0)

        self.assertEqual(client.last_announcements, [])

        client.last_announcements = ["이전 안내"]
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":false,"reason":"not found"}'
        with patch("test_a11y.time.monotonic", side_effect=fake_monotonic), patch("test_a11y.time.sleep", side_effect=fake_sleep):
            client.isin("SER", name="없음", wait_=0)

        self.assertEqual(client.last_announcements, [])

    def test_refresh_tree_if_needed_called_in_touch_and_isin(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true}'
        with patch.object(client, "_refresh_tree_if_needed") as refresh_mock:
            client.touch("SER", name="확인", wait_=1)
        refresh_mock.assert_called()

        client.calls.clear()
        client.logcat_payload = 'I/A11Y_HELPER: CHECK_TARGET_RESULT {"success":true}'
        with patch.object(client, "_refresh_tree_if_needed") as refresh_mock:
            client.isin("SER", name="확인", wait_=1)
        refresh_mock.assert_called()


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

        with patch("test_a11y.subprocess.run") as run_mock:
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
                'A11Y_HELPER DUMP_TREE_PART [{"id":1},',
                'A11Y_HELPER DUMP_TREE_PART {"id":2}]',
                "A11Y_HELPER DUMP_TREE_END",
            ]
        )

        with patch.object(client, "clear_logcat", return_value=""), patch.object(client, "_broadcast", return_value="ok"), patch.object(
            client,
            "_run",
            return_value=log_payload,
        ):
            result = client.dump_tree(dev="R3CX40QFDBP", wait_seconds=0.1)

        self.assertEqual(result, [{"id": 1}, {"id": 2}])


if __name__ == "__main__":
    unittest.main()
