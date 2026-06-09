from __future__ import annotations

from tb_runner.plugin_probe import start_plugin_probe


def test_probe_request_validation_requires_bounds_or_resource():
    result = start_plugin_probe(
        {
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
            }
        },
        client=object(),
    )

    assert result["ok"] is False
    assert result["diagnostics"]["failure_reason"] == "invalid_request"


def test_life_bounds_tap_probe_returns_seed_preview():
    class FakeLifeClient:
        def tap_xy_adb(self, **_kwargs):
            return True

        def collect_focus_step(self, **kwargs):
            step_index = kwargs["step_index"]
            return {
                "step_index": step_index,
                "visible_label": "Home Care" if step_index == 0 else "Suggestions",
                "merged_announcement": "Home Care" if step_index == 0 else "Suggestions",
                "focus_view_id": "com.pkg:id/title",
                "focus_bounds": "40,120,1040,220",
                "dump_tree_nodes": [
                    {
                        "text": "Home Care",
                        "viewIdResourceName": "com.pkg:id/title",
                        "className": "android.widget.TextView",
                        "boundsInScreen": "40,120,1040,220",
                    }
                ],
            }

        def dump_tree(self, **_kwargs):
            return [
                {
                    "text": "Home Care",
                    "viewIdResourceName": "com.pkg:id/title",
                    "className": "android.widget.TextView",
                    "boundsInScreen": "40,120,1040,220",
                }
            ]

        def _run(self, args, **_kwargs):
            if args[:3] == ["shell", "uiautomator", "dump"]:
                return "UI hierchary dumped to: /sdcard/window_dump_plugin_probe.xml"
            if args[:2] == ["shell", "cat"]:
                return """
                <hierarchy>
                  <node text="Home Care" class="android.widget.TextView" resource-id="com.pkg:id/title" bounds="[40,120][1040,220]"/>
                  <node text="Suggestions" class="android.widget.TextView" resource-id="com.pkg:id/header" bounds="[40,360][520,430]"/>
                  <node text="More options" class="android.widget.Button" resource-id="com.pkg:id/more_menu_button" bounds="[940,20][1040,120]"/>
                </hierarchy>
                """
            return ""

    result = start_plugin_probe(
        {
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "bounds": "40,420,1040,760",
                "resource_id": "com.pkg:id/preInstalledServiceCard",
            },
            "max_probe_steps": 3,
            "include_xml": True,
            "include_helper_dump": True,
        },
        client=FakeLifeClient(),
    )

    assert result["ok"] is True
    assert result["schema_version"] == "plugin-probe-v1"
    assert result["entry"]["method"] == "life_bounds_tap"
    assert result["entry"]["open_confirmed"] is True
    assert result["summary"]["suggested_entry_method"] == "xml_scroll_search_tap"
    assert "Home Care" in result["seed"]["verify_tokens"]
    assert "Home Care" in result["seed"]["headers"]
    assert "More options" in result["seed"]["overlay_hints"]
    assert result["artifacts"]["focus_steps"] == 3


def test_device_visible_card_tap_probe_returns_entry_method():
    class FakeDeviceClient:
        def tap_xy_adb(self, **_kwargs):
            return True

        def collect_focus_step(self, **kwargs):
            step_index = kwargs["step_index"]
            return {
                "step_index": step_index,
                "visible_label": "Audio" if step_index == 0 else "Now playing",
                "merged_announcement": "Audio" if step_index == 0 else "Now playing",
                "focus_view_id": "com.pkg:id/audio_title",
                "focus_bounds": "40,120,1040,220",
                "dump_tree_nodes": [],
            }

        def dump_tree(self, **_kwargs):
            return [
                {
                    "text": "Audio Pause",
                    "viewIdResourceName": "com.samsung.android.oneconnect:id/device_card",
                    "className": "android.view.ViewGroup",
                    "boundsInScreen": "40,420,1040,760",
                    "clickable": True,
                }
            ]

    result = start_plugin_probe(
        {
            "card": {
                "id": "device:audio:0",
                "label": "Audio",
                "stable_label": "Audio",
                "type": "device",
                "bounds": "40,420,1040,760",
                "resource_id": "com.samsung.android.oneconnect:id/device_card",
            },
            "max_probe_steps": 3,
            "include_xml": False,
            "include_helper_dump": True,
        },
        client=FakeDeviceClient(),
    )

    assert result["ok"] is True
    assert result["entry"]["method"] == "device_visible_card_tap"
    assert result["summary"]["suggested_entry_method"] == "enter_device_card_plugin"
    assert result["seed"]["entry_candidate"]["action"] == "enter_device_card_plugin"


def test_partial_probe_response_is_not_treated_as_failure():
    class PartialClient:
        def tap_xy_adb(self, **_kwargs):
            return True

        def collect_focus_step(self, **kwargs):
            if kwargs["step_index"] > 1:
                raise RuntimeError("timeout")
            return {
                "step_index": kwargs["step_index"],
                "visible_label": "Home Care",
                "merged_announcement": "Home Care",
                "focus_view_id": "com.pkg:id/title",
                "focus_bounds": "40,120,1040,220",
                "dump_tree_nodes": [],
            }

        def dump_tree(self, **_kwargs):
            return []

    result = start_plugin_probe(
        {
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "bounds": "40,420,1040,760",
            },
            "max_probe_steps": 5,
            "include_xml": False,
            "include_helper_dump": False,
        },
        client=PartialClient(),
    )

    assert result["ok"] is True
    assert result["probe_status"] == "collector_partial_only"
    assert result["diagnostics"]["failure_reason"] == "collector_partial_only"


def test_probe_homecare_webview_alias_open_is_confirmed():
    class FakeHomecareWebViewClient:
        def tap_xy_adb(self, **_kwargs):
            return True

        def collect_focus_step(self, **kwargs):
            labels = [
                "Home Care",
                "My device list",
                "Care options",
                "Samsung Care+",
            ]
            step_index = kwargs["step_index"]
            label = labels[min(step_index, len(labels) - 1)]
            return {
                "step_index": step_index,
                "visible_label": label,
                "merged_announcement": label,
                "focus_view_id": "usageGuide" if label == "My device list" else "samsungCarePlus",
                "focus_bounds": "40,120,1040,220",
                "dump_tree_nodes": [],
            }

        def dump_tree(self, **_kwargs):
            return [
                {"text": "Home Care", "className": "android.widget.TextView", "boundsInScreen": "154,103,936,264"},
                {"text": "Suggestions", "className": "android.widget.TextView", "boundsInScreen": "53,309,1026,376"},
                {"text": "My device list", "className": "android.view.View", "viewIdResourceName": "DASH_0102-5", "boundsInScreen": "25,654,1054,812"},
                {"text": "Care options", "className": "android.widget.TextView", "boundsInScreen": "53,1408,348,1470"},
                {"text": "Samsung Care+", "className": "android.widget.Button", "viewIdResourceName": "samsungCarePlus", "boundsInScreen": "556,1501,787,1841"},
            ]

        def _run(self, args, **_kwargs):
            if args[:3] == ["shell", "uiautomator", "dump"]:
                return "UI hierchary dumped to: /sdcard/window_dump_plugin_probe.xml"
            if args[:2] == ["shell", "cat"]:
                return """
                <hierarchy>
                  <node text="" class="android.widget.RelativeLayout" resource-id="com.samsung.android.oneconnect:id/activity_plugin_web" bounds="[0,84][1080,2205]"/>
                  <node text="" class="android.webkit.WebView" bounds="[0,84][1080,2205]"/>
                  <node text="SmartThings Home Care" class="android.webkit.WebView" bounds="[0,84][1080,2205]"/>
                  <node text="Home Care" class="android.widget.TextView" bounds="[154,103][936,264]"/>
                  <node text="My device list" class="android.widget.Button" bounds="[25,654][1054,812]"/>
                  <node text="Care options" class="android.widget.TextView" bounds="[53,1408][348,1470]"/>
                  <node text="Usage guide" class="android.widget.Button" resource-id="usageGuide" bounds="[25,1501][255,1841]"/>
                  <node text="Accessories" class="android.widget.Button" resource-id="accessories" bounds="[292,1501][523,1841]"/>
                  <node text="Samsung Care+" class="android.widget.Button" resource-id="samsungCarePlus" bounds="[556,1501][787,1841]"/>
                </hierarchy>
                """
            return ""

    result = start_plugin_probe(
        {
            "card": {
                "id": "life:homecare_manager:0",
                "label": "Homecare Manager (개발자)",
                "stable_label": "Homecare Manager (개발자)",
                "type": "life",
                "bounds": "40,420,1040,760",
                "resource_id": "com.pkg:id/preInstalledServiceCard",
            },
            "max_probe_steps": 4,
            "include_xml": True,
            "include_helper_dump": True,
        },
        client=FakeHomecareWebViewClient(),
    )

    assert result["ok"] is True
    assert result["probe_status"] == "opened_partial_observed"
    assert result["entry"]["open_confirmed"] is True
    assert result["entry"]["reason"] == "transition_or_anchor_seen"
    assert result["diagnostics"]["failure_reason"] == ""
    assert result["summary"]["plugin_open_verified_candidate"] is True


def test_probe_wrong_known_plugin_still_rejected():
    class FakeWrongPluginClient:
        def tap_xy_adb(self, **_kwargs):
            return True

        def collect_focus_step(self, **kwargs):
            label = "Air Care"
            return {
                "step_index": kwargs["step_index"],
                "visible_label": label,
                "merged_announcement": label,
                "focus_view_id": "com.pkg:id/title",
                "focus_bounds": "40,120,1040,220",
                "dump_tree_nodes": [],
            }

        def dump_tree(self, **_kwargs):
            return [{"text": "Air Care", "className": "android.widget.TextView", "boundsInScreen": "40,120,1040,220"}]

        def _run(self, args, **_kwargs):
            if args[:3] == ["shell", "uiautomator", "dump"]:
                return "UI hierchary dumped to: /sdcard/window_dump_plugin_probe.xml"
            if args[:2] == ["shell", "cat"]:
                return """
                <hierarchy>
                  <node text="Air Care" class="android.widget.TextView" resource-id="com.pkg:id/title" bounds="[40,120][1040,220]"/>
                  <node text="Outdoor air quality" class="android.widget.TextView" resource-id="com.pkg:id/subtitle" bounds="[40,260][1040,320]"/>
                </hierarchy>
                """
            return ""

    result = start_plugin_probe(
        {
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "bounds": "40,420,1040,760",
                "resource_id": "com.pkg:id/preInstalledServiceCard",
            },
            "max_probe_steps": 3,
            "include_xml": True,
            "include_helper_dump": True,
        },
        client=FakeWrongPluginClient(),
    )

    assert result["ok"] is False
    assert result["entry"]["open_confirmed"] is False
    assert result["diagnostics"]["failure_reason"] == "wrong_plugin_open_suspected"


def test_probe_webview_without_verify_hit_is_not_auto_confirmed():
    class FakeBareWebViewClient:
        def tap_xy_adb(self, **_kwargs):
            return True

        def collect_focus_step(self, **kwargs):
            return {
                "step_index": kwargs["step_index"],
                "visible_label": "Random content",
                "merged_announcement": "Random content",
                "focus_view_id": "com.pkg:id/random",
                "focus_bounds": "40,120,1040,220",
                "dump_tree_nodes": [],
            }

        def dump_tree(self, **_kwargs):
            return [{"text": "Random content", "className": "android.widget.TextView", "boundsInScreen": "40,120,1040,220"}]

        def _run(self, args, **_kwargs):
            if args[:3] == ["shell", "uiautomator", "dump"]:
                return "UI hierchary dumped to: /sdcard/window_dump_plugin_probe.xml"
            if args[:2] == ["shell", "cat"]:
                return """
                <hierarchy>
                  <node text="" class="android.widget.RelativeLayout" resource-id="com.samsung.android.oneconnect:id/activity_plugin_web" bounds="[0,84][1080,2205]"/>
                  <node text="" class="android.webkit.WebView" bounds="[0,84][1080,2205]"/>
                  <node text="Random content" class="android.widget.TextView" resource-id="com.pkg:id/random" bounds="[40,120][1040,220]"/>
                </hierarchy>
                """
            return ""

    result = start_plugin_probe(
        {
            "card": {
                "id": "life:homecare_manager:0",
                "label": "Homecare Manager (개발자)",
                "stable_label": "Homecare Manager (개발자)",
                "type": "life",
                "bounds": "40,420,1040,760",
            },
            "max_probe_steps": 3,
            "include_xml": True,
            "include_helper_dump": True,
        },
        client=FakeBareWebViewClient(),
    )

    assert result["entry"]["open_confirmed"] is False
    assert result["summary"]["plugin_open_verified_candidate"] is False
