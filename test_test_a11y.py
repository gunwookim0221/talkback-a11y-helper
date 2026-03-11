import unittest

from test_a11y import A11yAdbClient


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


if __name__ == "__main__":
    unittest.main()
