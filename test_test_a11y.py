import unittest
from unittest.mock import patch

from test_a11y import (
    ACTION_CLICK_FOCUSED,
    ACTION_FOCUS_TARGET,
    ACTION_GET_FOCUS,
    ACTION_NEXT,
    ACTION_PREV,
    ACTION_SCROLL,
    ACTION_SET_TEXT,
    A11yAdbClient,
)


class TargetActionResultTest(unittest.TestCase):
    def test_parse_target_action_result_success(self):
        payload = '{"success":true,"reason":"CLICK success","action":"CLICK"}'
        result = A11yAdbClient._parse_target_action_result(payload)
        self.assertTrue(result["success"])
        self.assertEqual(result["reason"], "CLICK success")

    def test_parse_target_action_result_invalid_json(self):
        with self.assertRaises(RuntimeError):
            A11yAdbClient._parse_target_action_result('{"success":true')

    def test_format_target_action_result_failure_with_conditions(self):
        result = {
            "success": False,
            "reason": "No matching target node",
            "action": "FOCUS",
        }
        output = A11yAdbClient._format_target_action_result(
            result,
            text="확인",
            view_id="com.test:id/ok",
            class_name="android.widget.Button",
        )
        self.assertIn("success: False", output)
        self.assertIn("reason : No matching target node", output)
        self.assertIn("targetText: 확인", output)
        self.assertIn("targetViewId: com.test:id/ok", output)
        self.assertIn("targetClassName: android.widget.Button", output)


class FakeA11yClient(A11yAdbClient):
    def __init__(self):
        super().__init__(adb_path="adb", package_name="com.example.custom", start_monitor=False)
        self.calls = []
        self.logcat_payload = ""
        self.needs_update = False

    def _run(self, args, timeout: float = 10.0):  # pylint: disable=unused-argument
        self.calls.append(args)
        if args == ["logcat", "-c"]:
            return ""
        if args[:3] == ["shell", "am", "broadcast"]:
            return "broadcast ok"
        if args == ["logcat", "-d"]:
            return self.logcat_payload
        if args == ["logcat", "-v", "time", "-d"]:
            return self.logcat_payload
        raise AssertionError(f"unexpected args: {args}")


class ClientBehaviorTest(unittest.TestCase):
    def test_select_object_uses_package_and_all_filters(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: TARGET_ACTION_RESULT '
            '{"success":true,"reason":"ok","action":"FOCUS"}'
        )

        result = client.select_object(t="확인", r="com.app:id/ok", c="android.widget.Button")

        self.assertTrue(result["success"])
        broadcast = client.calls[1]
        self.assertEqual(
            broadcast,
            [
                "shell", "am", "broadcast", "-a", ACTION_FOCUS_TARGET,
                "-p", "com.example.custom",
                "--es", "targetText", "확인",
                "--es", "targetViewId", "com.app:id/ok",
                "--es", "targetClassName", "android.widget.Button",
            ],
        )

    def test_touch_object_runs_focus_wait_click_flow_in_order(self):
        client = FakeA11yClient()
        client.logcat_payload = '\n'.join([
            'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reason":"ok","action":"FOCUS"}',
            'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"reason":"ok","action":"CLICK_FOCUSED"}',
            '01-01 00:00:00.100 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 확인 버튼',
        ])

        events = []

        original_broadcast = client._broadcast

        def tracking_broadcast(action, extras=None):
            events.append(("broadcast", action))
            return original_broadcast(action, extras)

        client._broadcast = tracking_broadcast

        def tracking_get_announcements(wait_seconds=2.0):
            events.append(("wait", wait_seconds))
            return ["확인 버튼"]

        client.get_announcements = tracking_get_announcements

        with patch("test_a11y.time.sleep") as mock_sleep:
            result = client.touch_object(
                text="무시됨",
                view_id="com.ignore:id/value",
                class_name="android.view.View",
                t="확인",
                r="com.app:id/ok",
                c="android.widget.Button",
            )

        self.assertTrue(result["success"])
        self.assertEqual(events[0], ("broadcast", ACTION_FOCUS_TARGET))
        self.assertEqual(events[1], ("wait", 1.5))
        self.assertEqual(events[2], ("broadcast", ACTION_CLICK_FOCUSED))
        mock_sleep.assert_called_once_with(0.6)

    def test_navigation_and_focus_helpers(self):
        client = FakeA11yClient()

        client.logcat_payload = 'I/A11Y_HELPER: NAV_RESULT {"success":true,"direction":"NEXT"}'
        next_result = client.move_next()
        self.assertTrue(next_result["success"])
        self.assertIn(ACTION_NEXT, client.calls[1])

        client.calls.clear()
        client.logcat_payload = 'I/A11Y_HELPER: NAV_RESULT {"success":false,"direction":"PREV"}'
        prev_result = client.move_prev()
        self.assertFalse(prev_result["success"])
        self.assertIn(ACTION_PREV, client.calls[1])

        client.calls.clear()
        client.logcat_payload = 'I/A11Y_HELPER: TARGET_ACTION_RESULT {"success":true,"action":"CLICK_FOCUSED"}'
        click_focused_result = client.click_focused()
        self.assertTrue(click_focused_result["success"])
        self.assertIn(ACTION_CLICK_FOCUSED, client.calls[1])

        client.calls.clear()
        client.logcat_payload = 'I/A11Y_HELPER: FOCUS_RESULT {"text":"확인","className":"android.widget.Button"}'
        focus_result = client.get_current_focus()
        self.assertEqual(focus_result["text"], "확인")
        self.assertIn(ACTION_GET_FOCUS, client.calls[1])

    def test_scroll_and_set_text_helpers(self):
        client = FakeA11yClient()

        client.logcat_payload = 'I/A11Y_HELPER: SCROLL_RESULT {"success":true,"action":"SCROLL_FORWARD"}'
        next_result = client.scroll_next()
        self.assertTrue(next_result["success"])
        self.assertEqual(
            client.calls[1],
            [
                "shell", "am", "broadcast", "-a", ACTION_SCROLL,
                "-p", "com.example.custom", "--ez", "forward", "true",
            ],
        )

        client.calls.clear()
        client.logcat_payload = 'I/A11Y_HELPER: SCROLL_RESULT {"success":false,"action":"SCROLL_BACKWARD"}'
        prev_result = client.scroll_prev()
        self.assertFalse(prev_result["success"])
        self.assertEqual(
            client.calls[1],
            [
                "shell", "am", "broadcast", "-a", ACTION_SCROLL,
                "-p", "com.example.custom", "--ez", "forward", "false",
            ],
        )

        client.calls.clear()
        client.logcat_payload = 'I/A11Y_HELPER: SET_TEXT_RESULT {"success":true,"action":"SET_TEXT","text":"안녕"}'
        text_result = client.input_text("안녕")
        self.assertTrue(text_result["success"])
        self.assertEqual(
            client.calls[1],
            [
                "shell", "am", "broadcast", "-a", ACTION_SET_TEXT,
                "-p", "com.example.custom", "--es", "text", "안녕",
            ],
        )

    def test_get_announcements(self):
        client = FakeA11yClient()
        client.logcat_payload = "\n".join([
            "01-01 00:00:00.100 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 첫번째",
            "01-01 00:00:00.200 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 두번째",
        ])

        result = client.get_announcements(wait_seconds=0.1)

        self.assertEqual(result, ["첫번째", "두번째"])

    def test_select_object_refreshes_tree_when_needs_update(self):
        class RefreshAwareClient(FakeA11yClient):
            def __init__(self):
                super().__init__()
                self.dump_count = 0

            def dump_tree(self, wait_seconds: float = 3.0):
                self.dump_count += 1
                self.needs_update = False
                return []

        client = RefreshAwareClient()
        client.needs_update = True
        client.logcat_payload = (
            'I/A11Y_HELPER: TARGET_ACTION_RESULT '
            '{"success":true,"reason":"ok","action":"FOCUS"}'
        )

        client.select_object(t="확인")

        self.assertEqual(client.dump_count, 1)
        self.assertFalse(client.needs_update)

    def test_dump_tree_success_sets_needs_update_false(self):
        client = FakeA11yClient()
        client.logcat_payload = 'I/A11Y_HELPER: DUMP_TREE_RESULT [{"text":"확인"}]'
        client.needs_update = True

        result = client.dump_tree(wait_seconds=0.1)

        self.assertEqual(result, [{"text": "확인"}])
        self.assertFalse(client.needs_update)


if __name__ == "__main__":
    unittest.main()
