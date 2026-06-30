from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tb_runner.device_inventory import (
    INVENTORY_ARTIFACT_VERSION,
    INVENTORY_SCHEMA_VERSION,
    InventoryCollectionOptions,
    collect_runtime_inventory,
    run_inventory_shadow_if_enabled,
    write_inventory_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVICE_CARD_RESOURCE_ID = "com.samsung.android.oneconnect:id/device_card"


def _card(label: str, bounds: str, *, resource_id: str = DEVICE_CARD_RESOURCE_ID) -> dict:
    return {
        "text": label,
        "viewIdResourceName": resource_id,
        "className": "android.view.ViewGroup",
        "boundsInScreen": bounds,
        "clickable": True,
        "visibleToUser": True,
    }


def _fixed_clock() -> datetime:
    return datetime(2026, 6, 30, 3, 0, 0, tzinfo=timezone.utc)


def _replay(viewports: list[list[dict]], *, max_scrolls: int = 6) -> dict:
    state = {"index": 0}

    def capture() -> list[dict]:
        return viewports[state["index"]]

    def scroll(_nodes: list[dict]) -> bool:
        if state["index"] + 1 >= len(viewports):
            return False
        state["index"] += 1
        return True

    return collect_runtime_inventory(
        capture,
        scroll_down=scroll,
        options=InventoryCollectionOptions(max_scrolls=max_scrolls),
        clock=_fixed_clock,
        sleep=lambda _seconds: None,
    )


def test_inventory_schema_contains_required_runtime_card_fields():
    inventory = collect_runtime_inventory(
        lambda: [_card("거실 모션 Motion detected", "40,420,1040,760")],
        clock=_fixed_clock,
    )

    assert inventory["schema_version"] == INVENTORY_SCHEMA_VERSION
    assert inventory["artifact_version"] == INVENTORY_ARTIFACT_VERSION
    assert inventory["termination_reason"] == "viewport_only"
    item = inventory["items"][0]
    assert {
        "runtime_card_id",
        "inventory_id",
        "display_label",
        "stable_label",
        "bounds",
        "room",
        "section",
        "viewport_index",
        "scroll_generation",
        "resource_id",
        "class_name",
        "source",
        "confidence",
        "capture_timestamp",
        "locator_evidence",
        "artifact_version",
    }.issubset(item)
    assert item["display_label"] == "거실 모션 Motion detected"
    assert item["stable_label"] == "거실 모션"
    assert item["identify_status"] == "not_attempted"


def test_runtime_card_ids_are_unique_and_session_scoped():
    nodes = [
        _card("Shared name", "40,420,1040,760"),
        _card("Shared name", "40,800,1040,1140"),
    ]

    first = collect_runtime_inventory(lambda: nodes, clock=_fixed_clock)
    second = collect_runtime_inventory(lambda: nodes, clock=_fixed_clock)

    first_ids = {item["runtime_card_id"] for item in first["items"]}
    second_ids = {item["runtime_card_id"] for item in second["items"]}
    assert len(first_ids) == 2
    assert first_ids.isdisjoint(second_ids)
    assert first["inventory_id"] != second["inventory_id"]


def test_duplicate_labels_remain_separate_inventory_items():
    inventory = collect_runtime_inventory(
        lambda: [
            _card("Motion Sensor", "40,420,1040,760"),
            _card("Motion Sensor", "40,800,1040,1140"),
        ],
        clock=_fixed_clock,
    )

    matching = [item for item in inventory["items"] if item["stable_label"] == "Motion Sensor"]
    assert len(matching) == 2
    assert matching[0]["runtime_card_id"] != matching[1]["runtime_card_id"]


def test_unique_composite_fingerprint_merges_boundary_observation():
    inventory = _replay(
        [
            [_card("Motion Sensor No motion", "40,420,1040,760")],
            [
                _card("Motion Sensor No motion", "40,120,1040,460"),
                _card("Door Lock Locked", "40,500,1040,840"),
            ],
        ]
    )

    motion = [item for item in inventory["items"] if item["stable_label"] == "Motion Sensor"]
    assert len(motion) == 1
    assert motion[0]["observed_viewport_indexes"] == [0, 1]
    assert len(motion[0]["observations"]) == 2
    assert inventory["item_count"] == 2


def test_scroll_terminates_on_repeated_viewport():
    viewport = [_card("Motion Sensor", "40,420,1040,760")]
    inventory = _replay([viewport, viewport, viewport])

    assert inventory["termination_reason"] == "repeated_viewport"
    assert inventory["viewport_count"] == 1
    assert inventory["item_count"] == 1


def test_scroll_terminates_at_bounded_maximum():
    inventory = _replay(
        [
            [_card("A", "40,420,1040,760")],
            [_card("B", "40,420,1040,760")],
            [_card("C", "40,420,1040,760")],
        ],
        max_scrolls=1,
    )

    assert inventory["termination_reason"] == "max_scrolls_reached"
    assert inventory["scope"] == "partial"
    assert inventory["scroll_generation_count"] == 1
    assert "bounded_scroll_limit_reached" in inventory["warnings"]


def test_feature_flag_off_does_not_touch_client_or_write_artifact(tmp_path):
    class ExplodingClient:
        def dump_tree(self, **_kwargs):
            raise AssertionError("feature-off inventory touched the client")

    result = run_inventory_shadow_if_enabled(
        ExplodingClient(),
        "serial",
        {"feature_flags": {"inventory_enabled": False}},
        artifact_dir=tmp_path,
    )

    assert result == {"status": "disabled", "inventory": None, "artifact_path": ""}
    assert list(tmp_path.iterdir()) == []


def test_feature_flag_on_captures_helper_nodes_and_writes_only_inventory_artifact(tmp_path):
    class FakeClient:
        def __init__(self):
            self.dump_count = 0

        def dump_tree(self, **_kwargs):
            self.dump_count += 1
            return [_card("Bedroom Motion", "40,420,1040,760")]

        def scroll(self, **_kwargs):
            return False

    client = FakeClient()
    result = run_inventory_shadow_if_enabled(
        client,
        "serial-1",
        {"feature_flags": {"inventory_enabled": True}},
        artifact_dir=tmp_path,
        clock=_fixed_clock,
    )

    assert result["status"] == "captured"
    assert result["inventory"]["device_serial"] == "serial-1"
    assert result["inventory"]["termination_reason"] == "end_of_list"
    assert client.dump_count == 1
    artifact_path = Path(result["artifact_path"])
    assert artifact_path.parent == tmp_path
    assert artifact_path.suffix == ".json"
    assert [path.name for path in tmp_path.iterdir()] == [artifact_path.name]


def test_artifact_writer_preserves_schema_and_item_count(tmp_path):
    inventory = collect_runtime_inventory(
        lambda: [_card("Bedroom Motion", "40,420,1040,760")],
        clock=_fixed_clock,
    )

    artifact_path = write_inventory_artifact(inventory, artifact_dir=tmp_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == INVENTORY_SCHEMA_VERSION
    assert payload["artifact_version"] == INVENTORY_ARTIFACT_VERSION
    assert payload["inventory_id"] == inventory["inventory_id"]
    assert payload["item_count"] == len(payload["items"]) == 1
    assert payload["items"][0]["artifact_version"] == INVENTORY_ARTIFACT_VERSION


def test_fixture_replay_collects_duplicate_names_and_stops_on_repeat():
    fixture_path = REPO_ROOT / "tests/fixtures/v10/inventory/device_cards_scroll.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    inventory = _replay(fixture["viewports"])

    assert inventory["termination_reason"] == fixture["expected"]["termination_reason"]
    assert inventory["item_count"] >= fixture["expected"]["minimum_item_count"]
    assert (
        len([item for item in inventory["items"] if item["stable_label"] == "Shared name"])
        == fixture["expected"]["shared_name_count"]
    )
