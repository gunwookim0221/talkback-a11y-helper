from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from tb_runner import device_tab_logic
from tb_runner.utils import parse_bounds_str
from tb_runner.v10_preparation import V10_ARTIFACT_ROOT

INVENTORY_SCHEMA_VERSION = "v10-runtime-inventory-v1"
INVENTORY_ARTIFACT_VERSION = "v10-inventory-artifact-v1"
DEFAULT_MAX_SCROLLS = 6
DEFAULT_MAX_DURATION_SECONDS = 45.0

CaptureNodes = Callable[[], list[dict[str, Any]]]
ScrollDown = Callable[[list[dict[str, Any]]], bool]
Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _digest(parts: list[Any]) -> str:
    payload = "\x1f".join(_normalized(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _bounds_parts(value: Any) -> tuple[int, int, int, int] | None:
    return parse_bounds_str(value)


def _structural_fingerprint(card: Mapping[str, Any]) -> str:
    bounds = _bounds_parts(card.get("bounds"))
    left, top, right, bottom = bounds or (0, 0, 0, 0)
    width = max(0, right - left)
    height = max(0, bottom - top)
    stable_label = device_tab_logic.normalize_device_stable_label(
        str(card.get("stable_label") or card.get("label") or "")
    )
    return _digest(
        [
            stable_label,
            card.get("resource_id") or card.get("rid"),
            card.get("class_name"),
            left,
            width,
            height,
        ]
    )


def _observation_fingerprint(card: Mapping[str, Any]) -> str:
    return _digest(
        [
            _structural_fingerprint(card),
            card.get("bounds"),
            card.get("label"),
        ]
    )


def _viewport_signature(cards: list[dict[str, Any]]) -> str:
    parts = [
        _observation_fingerprint(card)
        for card in sorted(
            cards,
            key=lambda item: (
                int(item.get("top", 0) or 0),
                int(item.get("left", 0) or 0),
                str(item.get("stable_label", "") or ""),
            ),
        )
    ]
    return _digest(parts or ["empty-viewport"])


def _visibility(card: Mapping[str, Any]) -> str:
    return "visible" if _bounds_parts(card.get("bounds")) else "visible_without_bounds"


@dataclass(frozen=True)
class InventoryObservation:
    viewport_index: int
    scroll_generation: int
    display_label: str
    stable_label: str
    bounds: str
    resource_id: str
    class_name: str
    source: str
    capture_timestamp: str
    fingerprint: str


@dataclass
class RuntimeInventoryItem:
    runtime_card_id: str
    inventory_id: str
    display_label: str
    stable_label: str
    bounds: str
    room: str
    section: str
    viewport_index: int
    scroll_generation: int
    resource_id: str
    class_name: str
    source: str
    confidence: str
    capture_timestamp: str
    locator_evidence: dict[str, Any]
    artifact_version: str
    visibility: str = "visible"
    identity_confidence: str = "high"
    identify_status: str = "not_attempted"
    observed_viewport_indexes: list[int] = field(default_factory=list)
    observations: list[InventoryObservation] = field(default_factory=list)
    evidence_fingerprint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InventoryCollectionOptions:
    max_scrolls: int = DEFAULT_MAX_SCROLLS
    max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS
    scroll_settle_seconds: float = 0.6

    def normalized(self) -> InventoryCollectionOptions:
        return InventoryCollectionOptions(
            max_scrolls=max(0, int(self.max_scrolls)),
            max_duration_seconds=max(1.0, float(self.max_duration_seconds)),
            scroll_settle_seconds=max(0.0, min(float(self.scroll_settle_seconds), 5.0)),
        )


def _make_observation(
    card: Mapping[str, Any],
    *,
    viewport_index: int,
    scroll_generation: int,
    captured_at: str,
) -> InventoryObservation:
    display_label = str(card.get("label") or "")
    stable_label = device_tab_logic.normalize_device_stable_label(
        str(card.get("stable_label") or display_label)
    )
    return InventoryObservation(
        viewport_index=viewport_index,
        scroll_generation=scroll_generation,
        display_label=display_label,
        stable_label=stable_label,
        bounds=str(card.get("bounds") or ""),
        resource_id=str(card.get("resource_id") or card.get("rid") or ""),
        class_name=str(card.get("class_name") or ""),
        source="helper",
        capture_timestamp=captured_at,
        fingerprint=_observation_fingerprint(card),
    )


def _make_item(
    card: Mapping[str, Any],
    observation: InventoryObservation,
    *,
    inventory_id: str,
    sequence: int,
) -> RuntimeInventoryItem:
    runtime_card_id = f"card-{sequence:04d}-{uuid.uuid4().hex[:8]}"
    actionable = bool(
        card.get("clickable")
        or card.get("focusable")
        or card.get("effective_clickable")
    )
    return RuntimeInventoryItem(
        runtime_card_id=runtime_card_id,
        inventory_id=inventory_id,
        display_label=observation.display_label,
        stable_label=observation.stable_label,
        bounds=observation.bounds,
        room="",
        section="",
        viewport_index=observation.viewport_index,
        scroll_generation=observation.scroll_generation,
        resource_id=observation.resource_id,
        class_name=observation.class_name,
        source=observation.source,
        confidence="high" if actionable and observation.bounds else "medium",
        capture_timestamp=observation.capture_timestamp,
        locator_evidence={
            "bounds": observation.bounds,
            "resource_id": observation.resource_id,
            "class_name": observation.class_name,
            "display_label": observation.display_label,
            "stable_label": observation.stable_label,
            "actionable": actionable,
            "source_index": int(card.get("source_index", -1) or -1),
        },
        artifact_version=INVENTORY_ARTIFACT_VERSION,
        visibility=_visibility(card),
        observed_viewport_indexes=[observation.viewport_index],
        observations=[observation],
        evidence_fingerprint=_structural_fingerprint(card),
    )


def _merge_observation(item: RuntimeInventoryItem, observation: InventoryObservation) -> None:
    if observation.fingerprint in {entry.fingerprint for entry in item.observations}:
        return
    item.observations.append(observation)
    if observation.viewport_index not in item.observed_viewport_indexes:
        item.observed_viewport_indexes.append(observation.viewport_index)


def collect_runtime_inventory(
    capture_nodes: CaptureNodes,
    *,
    scroll_down: ScrollDown | None = None,
    device_serial: str = "",
    options: InventoryCollectionOptions | None = None,
    clock: Clock = _utc_now,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    settings = (options or InventoryCollectionOptions()).normalized()
    inventory_id = f"inventory-{clock().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    started_at = clock()
    started_monotonic = time.monotonic()
    items: list[RuntimeInventoryItem] = []
    seen_viewports: set[str] = set()
    warnings: list[str] = []
    viewport_count = 0
    scroll_generation = 0
    termination_reason = "not_started"
    scope = "bounded_scroll"

    while True:
        if time.monotonic() - started_monotonic > settings.max_duration_seconds:
            termination_reason = "timeout"
            scope = "partial"
            warnings.append("collection_timeout")
            break
        try:
            nodes = capture_nodes()
        except Exception as exc:
            termination_reason = "capture_failed"
            scope = "partial"
            warnings.append(f"helper_dump_failed:{exc}")
            break
        nodes = nodes if isinstance(nodes, list) else []
        cards = device_tab_logic.collect_visible_device_cards(nodes)
        signature = _viewport_signature(cards)
        if signature in seen_viewports:
            termination_reason = "repeated_viewport"
            break
        seen_viewports.add(signature)

        viewport_index = viewport_count
        viewport_count += 1
        captured_at = _timestamp(clock())
        matched_item_ids: set[str] = set()
        structural_groups: dict[str, list[RuntimeInventoryItem]] = {}
        for item in items:
            if item.observed_viewport_indexes[-1] == viewport_index - 1:
                structural_groups.setdefault(item.evidence_fingerprint, []).append(item)

        for card in cards:
            observation = _make_observation(
                card,
                viewport_index=viewport_index,
                scroll_generation=scroll_generation,
                captured_at=captured_at,
            )
            structural_key = _structural_fingerprint(card)
            candidates = [
                item
                for item in structural_groups.get(structural_key, [])
                if item.runtime_card_id not in matched_item_ids
            ]
            if len(candidates) == 1:
                item = candidates[0]
                _merge_observation(item, observation)
                matched_item_ids.add(item.runtime_card_id)
                continue
            if len(candidates) > 1:
                warnings.append(
                    f"ambiguous_boundary_match:viewport={viewport_index}:fingerprint={structural_key}"
                )
            item = _make_item(
                card,
                observation,
                inventory_id=inventory_id,
                sequence=len(items) + 1,
            )
            if len(candidates) > 1:
                item.identity_confidence = "low"
            items.append(item)
            matched_item_ids.add(item.runtime_card_id)

        if scroll_down is None:
            termination_reason = "viewport_only"
            scope = "viewport"
            break
        if scroll_generation >= settings.max_scrolls:
            termination_reason = "max_scrolls_reached"
            scope = "partial"
            warnings.append("bounded_scroll_limit_reached")
            break
        try:
            did_scroll = bool(scroll_down(nodes))
        except Exception as exc:
            termination_reason = "scroll_failed"
            scope = "partial"
            warnings.append(f"scroll_failed:{exc}")
            break
        if not did_scroll:
            termination_reason = "end_of_list"
            break
        scroll_generation += 1
        sleep(settings.scroll_settle_seconds)

    completed_at = clock()
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "artifact_version": INVENTORY_ARTIFACT_VERSION,
        "inventory_id": inventory_id,
        "captured_at": _timestamp(started_at),
        "completed_at": _timestamp(completed_at),
        "device_serial": str(device_serial or ""),
        "scope": scope,
        "termination_reason": termination_reason,
        "viewport_count": viewport_count,
        "scroll_generation_count": scroll_generation,
        "item_count": len(items),
        "warnings": warnings,
        "items": [item.as_dict() for item in items],
    }


def write_inventory_artifact(
    inventory: Mapping[str, Any],
    *,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "inventory",
) -> Path:
    output_dir = Path(artifact_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory_id = str(inventory.get("inventory_id") or "inventory-unknown")
    output_path = output_dir / f"{inventory_id}.json"
    output_path.write_text(
        json.dumps(dict(inventory), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _client_scroll_down(client: Any, dev: str | None, nodes: list[dict[str, Any]]) -> bool:
    adb_device = getattr(client, "_adb_device", None)
    swipe_fn = getattr(adb_device, "_swipe", None)
    if callable(swipe_fn):
        max_right = 1080
        max_bottom = 2400
        for node in nodes:
            if not isinstance(node, dict):
                continue
            bounds = _bounds_parts(node.get("boundsInScreen", node.get("bounds", "")))
            if bounds:
                max_right = max(max_right, bounds[2])
                max_bottom = max(max_bottom, bounds[3])
        swipe_fn(
            dev=dev,
            x1=int(max_right * 0.5),
            y1=int(max_bottom * 0.78),
            x2=int(max_right * 0.5),
            y2=int(max_bottom * 0.45),
            duration_ms=500,
        )
        return True
    scroll_fn = getattr(client, "scroll", None)
    if callable(scroll_fn):
        return bool(scroll_fn(dev=dev, direction="down"))
    return False


def run_inventory_shadow_if_enabled(
    client: Any,
    dev: str | None,
    v10_config: Mapping[str, Any] | None,
    *,
    artifact_dir: str | Path = V10_ARTIFACT_ROOT / "inventory",
    options: InventoryCollectionOptions | None = None,
    clock: Clock = _utc_now,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    raw = v10_config if isinstance(v10_config, Mapping) else {}
    flags = raw.get("feature_flags") if isinstance(raw.get("feature_flags"), Mapping) else {}
    if flags.get("inventory_enabled") is not True:
        return {
            "status": "disabled",
            "inventory": None,
            "artifact_path": "",
        }

    dump_tree = getattr(client, "dump_tree", None)
    if not callable(dump_tree):
        return {
            "status": "failed",
            "inventory": None,
            "artifact_path": "",
            "error": "helper_dump_unavailable",
        }

    def capture_nodes() -> list[dict[str, Any]]:
        payload = dump_tree(dev=dev)
        if isinstance(payload, dict) and isinstance(payload.get("nodes"), list):
            return [node for node in payload["nodes"] if isinstance(node, dict)]
        return [node for node in payload if isinstance(node, dict)] if isinstance(payload, list) else []

    inventory = collect_runtime_inventory(
        capture_nodes,
        scroll_down=lambda nodes: _client_scroll_down(client, dev, nodes),
        device_serial=str(dev or ""),
        options=options,
        clock=clock,
        sleep=sleep,
    )
    artifact_path = write_inventory_artifact(inventory, artifact_dir=artifact_dir)
    return {
        "status": "captured",
        "inventory": inventory,
        "artifact_path": str(artifact_path),
    }
