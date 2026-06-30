from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tb_runner.quick_plugin_identify import (
    ALLOWED_DECISIONS,
    IDENTIFY_ARTIFACT_VERSION,
    IDENTIFY_SCHEMA_VERSION,
    classify_plugin_family,
    collect_identify_evidence,
    identify_from_snapshots,
    run_quick_identify_if_enabled,
    write_identify_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVICE_CARD_ID = "com.samsung.android.oneconnect:id/device_card"


def _clock_factory():
    values = iter(
        [
            datetime(2026, 6, 30, 4, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 30, 4, 0, 1, tzinfo=timezone.utc),
        ]
    )
    return lambda: next(values)


def _inventory(display_label: str = "Custom device") -> dict:
    return {
        "schema_version": "v10-runtime-inventory-v1",
        "inventory_id": "inventory-test",
        "items": [
            {
                "inventory_id": "inventory-test",
                "runtime_card_id": "card-0001-test",
                "display_label": display_label,
                "stable_label": display_label,
                "bounds": "40,420,1040,760",
                "resource_id": DEVICE_CARD_ID,
                "class_name": "android.view.ViewGroup",
                "viewport_index": 0,
                "locator_evidence": {
                    "resource_id": DEVICE_CARD_ID,
                    "class_name": "android.view.ViewGroup",
                    "bounds": "40,420,1040,760"
                }
            }
        ]
    }


def _resource_node(resource_id: str, text: str = "") -> dict:
    return {
        "text": text,
        "viewIdResourceName": resource_id,
        "className": "android.view.ViewGroup",
        "children": []
    }


def _xml(resource_ids: list[str]) -> str:
    nodes = "".join(
        f'<node resource-id="{resource_id}" text="" class="android.view.ViewGroup" />'
        for resource_id in resource_ids
    )
    return f"<hierarchy>{nodes}</hierarchy>"


def test_result_schema_contains_required_fields_and_no_scenario():
    resource = "com.example:id/MotionSensorCapabilityCardView"
    result = identify_from_snapshots(
        _inventory("거실 센서"),
        "card-0001-test",
        helper_nodes=[_resource_node(resource, "No motion")],
        xml_text=_xml([resource]),
        clock=_clock_factory(),
    )

    assert result["schema_version"] == IDENTIFY_SCHEMA_VERSION
    assert result["artifact_version"] == IDENTIFY_ARTIFACT_VERSION
    assert result["decision"] == "identified"
    assert result["plugin_family_candidate"] == "MotionSensorCapability"
    assert result["decision"] in ALLOWED_DECISIONS
    assert {
        "inventory_id",
        "runtime_card_id",
        "confidence",
        "evidence",
        "snapshot_timestamp",
        "identify_duration",
        "restore_success",
    }.issubset(result)
    assert "scenario_id" not in result
    assert "scenario_candidate" not in result


def test_display_name_and_labels_alone_are_unknown():
    evidence = collect_identify_evidence(
        [_resource_node("com.example:id/GenericCapabilityCardView", "Motion Sensor")],
        _xml(["com.example:id/GenericCapabilityCardView"]),
        _inventory("Motion Sensor")["items"][0],
        talkback_speech="Motion detected",
    )
    result = classify_plugin_family(evidence)

    assert result["decision"] == "unknown"
    assert result["plugin_family_candidate"] == "unknown"
    assert result["confidence"] < 40


def test_capability_resource_has_priority_over_display_name():
    lock_resource = "com.example:id/LockCapabilityCardView"
    result = identify_from_snapshots(
        _inventory("Motion Sensor"),
        "card-0001-test",
        helper_nodes=[_resource_node(lock_resource, "Locked")],
        xml_text=_xml([lock_resource]),
        clock=_clock_factory(),
    )

    assert result["decision"] == "identified"
    assert result["plugin_family_candidate"] == "GenericLockCapability"
    assert any(
        item["kind"] == "display_name"
        and item["candidate_types"] == ["MotionSensorCapability"]
        for item in result["evidence"]
    )


def test_single_structural_source_can_be_high_but_not_definite():
    resource = "com.example:id/SmokeSensorCapabilityCardView"
    result = identify_from_snapshots(
        _inventory("Safety"),
        "card-0001-test",
        helper_nodes=[_resource_node(resource, "Clear")],
        xml_text="",
        clock=_clock_factory(),
    )

    assert result["decision"] == "identified"
    assert result["confidence_band"] == "high"
    assert 80 <= result["confidence"] < 95


def test_conflicting_strong_families_are_ambiguous():
    motion = "com.example:id/MotionSensorCapabilityCardView"
    lock = "com.example:id/LockCapabilityCardView"
    result = identify_from_snapshots(
        _inventory(),
        "card-0001-test",
        helper_nodes=[_resource_node(motion), _resource_node(lock)],
        xml_text=_xml([motion, lock]),
        clock=_clock_factory(),
    )

    assert result["decision"] == "ambiguous"
    assert result["plugin_family_candidate"] == "unknown"
    assert result["contradictions"]


def test_missing_runtime_card_is_unknown_and_duplicate_id_is_ambiguous():
    missing = identify_from_snapshots(
        _inventory(),
        "missing",
        helper_nodes=[],
        xml_text="",
        clock=_clock_factory(),
    )
    duplicate_inventory = _inventory()
    duplicate_inventory["items"].append(dict(duplicate_inventory["items"][0]))
    duplicate = identify_from_snapshots(
        duplicate_inventory,
        "card-0001-test",
        helper_nodes=[],
        xml_text="",
        clock=_clock_factory(),
    )

    assert missing["decision"] == "unknown"
    assert duplicate["decision"] == "ambiguous"


def test_restore_failure_overrides_identified_result_to_failed():
    resource = "com.example:id/MotionSensorCapabilityCardView"
    result = identify_from_snapshots(
        _inventory(),
        "card-0001-test",
        helper_nodes=[_resource_node(resource)],
        xml_text=_xml([resource]),
        restore_success=False,
        clock=_clock_factory(),
    )

    assert result["decision"] == "failed"
    assert result["restore_success"] is False
    assert "inventory_restore_failed" in result["errors"]


def test_identify_artifact_preserves_schema(tmp_path):
    resource = "com.example:id/MotionSensorCapabilityCardView"
    result = identify_from_snapshots(
        _inventory(),
        "card-0001-test",
        helper_nodes=[_resource_node(resource)],
        xml_text=_xml([resource]),
        clock=_clock_factory(),
    )
    path = write_identify_artifact(result, artifact_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == IDENTIFY_SCHEMA_VERSION
    assert payload["artifact_version"] == IDENTIFY_ARTIFACT_VERSION
    assert path.parent == tmp_path


def test_feature_flag_off_has_zero_client_and_artifact_side_effects(tmp_path):
    class ExplodingClient:
        def __getattr__(self, _name):
            raise AssertionError("feature-off identify touched client")

    result = run_quick_identify_if_enabled(
        ExplodingClient(),
        "serial",
        {"feature_flags": {"quick_identify_enabled": False}},
        _inventory(),
        "card-0001-test",
        artifact_dir=tmp_path,
    )

    assert result == {"status": "disabled", "result": None, "artifact_path": ""}
    assert list(tmp_path.iterdir()) == []


def test_runtime_lifecycle_opens_captures_restores_and_writes_identify_only(
    tmp_path,
    monkeypatch,
):
    card = {
        "text": "Custom device",
        "viewIdResourceName": DEVICE_CARD_ID,
        "className": "android.view.ViewGroup",
        "boundsInScreen": "40,420,1040,760",
        "clickable": True,
        "visibleToUser": True
    }
    capability = _resource_node("com.example:id/MotionSensorCapabilityCardView", "No motion")

    class FakeClient:
        def __init__(self):
            self.screen = "inventory"
            self.taps = 0

        def dump_tree(self, **_kwargs):
            return [card] if self.screen == "inventory" else [capability]

        def tap_xy_adb(self, **_kwargs):
            self.taps += 1
            self.screen = "plugin"
            return True

        def _run(self, args, **_kwargs):
            if args[:4] == ["shell", "input", "keyevent", "4"]:
                self.screen = "inventory"
                return ""
            if args[:3] == ["shell", "uiautomator", "dump"]:
                return "dumped"
            if args[:2] == ["shell", "cat"]:
                return _xml(["com.example:id/MotionSensorCapabilityCardView"])
            return ""

    client = FakeClient()
    monkeypatch.setattr(
        "tb_runner.quick_plugin_identify.device_tab_logic.detect_selected_device_location",
        lambda nodes: {"selected": client.screen == "inventory" and bool(nodes)},
    )
    result = run_quick_identify_if_enabled(
        client,
        "serial",
        {"feature_flags": {"quick_identify_enabled": True}},
        _inventory(),
        "card-0001-test",
        artifact_dir=tmp_path,
        stabilize_seconds=0,
        restore_seconds=0,
        clock=_clock_factory(),
        sleep=lambda _seconds: None,
    )

    assert result["status"] == "identified"
    assert result["result"]["restore_success"] is True
    assert client.screen == "inventory"
    assert client.taps == 1
    assert Path(result["artifact_path"]).parent == tmp_path
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_runtime_locator_replays_inventory_viewport_with_bounded_scroll(
    tmp_path,
    monkeypatch,
):
    first_card = {
        "text": "First device",
        "viewIdResourceName": DEVICE_CARD_ID,
        "className": "android.view.ViewGroup",
        "boundsInScreen": "40,420,1040,760",
        "clickable": True,
        "visibleToUser": True,
    }
    target_card = {
        "text": "Custom device",
        "viewIdResourceName": DEVICE_CARD_ID,
        "className": "android.view.ViewGroup",
        "boundsInScreen": "40,420,1040,760",
        "clickable": True,
        "visibleToUser": True,
    }
    capability = _resource_node("com.example:id/SmokeSensorCapabilityCardView", "Clear")
    inventory = _inventory()
    inventory["items"][0]["viewport_index"] = 1
    inventory["items"][0]["observed_viewport_indexes"] = [1]

    class FakeClient:
        def __init__(self):
            self.screen = "inventory"
            self.viewport = 0
            self.scroll_calls = 0

        def scroll_to_top(self, **_kwargs):
            self.viewport = 0

        def scroll(self, **_kwargs):
            self.viewport = 1
            self.scroll_calls += 1
            return True

        def dump_tree(self, **_kwargs):
            if self.screen == "plugin":
                return [capability]
            return [first_card] if self.viewport == 0 else [target_card]

        def tap_xy_adb(self, **_kwargs):
            self.screen = "plugin"
            return True

        def _run(self, args, **_kwargs):
            if args[:4] == ["shell", "input", "keyevent", "4"]:
                self.screen = "inventory"
                return ""
            if args[:3] == ["shell", "uiautomator", "dump"]:
                return "dumped"
            if args[:2] == ["shell", "cat"]:
                return _xml(["com.example:id/SmokeSensorCapabilityCardView"])
            return ""

    client = FakeClient()
    monkeypatch.setattr(
        "tb_runner.quick_plugin_identify.device_tab_logic.detect_selected_device_location",
        lambda nodes: {"selected": client.screen == "inventory" and bool(nodes)},
    )
    result = run_quick_identify_if_enabled(
        client,
        "serial",
        {"feature_flags": {"quick_identify_enabled": True}},
        inventory,
        "card-0001-test",
        artifact_dir=tmp_path,
        stabilize_seconds=0,
        restore_seconds=0,
        locate_scroll_settle_seconds=0,
        clock=_clock_factory(),
        sleep=lambda _seconds: None,
    )

    assert result["status"] == "identified"
    assert result["result"]["plugin_family_candidate"] == "SmokeDetectorCapability"
    assert result["result"]["restore_success"] is True
    assert client.scroll_calls == 1
    assert client.viewport == 1


def test_fixture_replay_covers_six_families_and_unknown():
    fixture = json.loads(
        (REPO_ROOT / "tests/fixtures/v10/identify/quick_identify_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(fixture["cases"]) >= 7

    for case in fixture["cases"]:
        result = identify_from_snapshots(
            _inventory(case["display_label"]),
            "card-0001-test",
            helper_nodes=case["helper_nodes"],
            xml_text=case["window_xml"],
            clock=_clock_factory(),
        )
        assert result["decision"] == case["expected_decision"], case["id"]
        assert result["plugin_family_candidate"] == case["expected_family"], case["id"]
