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
