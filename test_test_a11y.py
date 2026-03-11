import unittest

from test_a11y import (
    ACTION_CLICK_FOCUSED,
    ACTION_CLICK_TARGET,
    ACTION_FOCUS_TARGET,
    ACTION_GET_FOCUS,
    ACTION_NEXT,
    ACTION_PREV,
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
        super().__init__(adb_path="adb", package_name="com.example.custom")
        self.calls = []
        self.logcat_payload = ""

    def _run(self, args, timeout: float = 10.0):  # pylint: disable=unused-argument
        self.calls.append(args)
        if args == ["logcat", "-c"]:
            return ""
        if args[:3] == ["shell", "am", "broadcast"]:
            return "broadcast ok"
        if args == ["logcat", "-d"]:
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

    def test_touch_object_uses_click_action(self):
        client = FakeA11yClient()
        client.logcat_payload = (
            'I/A11Y_HELPER: TARGET_ACTION_RESULT '
            '{"success":true,"reason":"ok","action":"CLICK"}'
        )

        result = client.touch_object(text="확인")

        self.assertTrue(result["success"])
        self.assertIn(ACTION_CLICK_TARGET, client.calls[1])

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


if __name__ == "__main__":
    unittest.main()
