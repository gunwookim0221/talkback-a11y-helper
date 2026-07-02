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
    visible_order: int


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
    merge_reason: str = "new_runtime_card"
    identity_diagnostics: list[dict[str, Any]] = field(default_factory=list)

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
    visible_order: int,
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
        visible_order=visible_order,
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
            "visible_order": observation.visible_order,
        },
        artifact_version=INVENTORY_ARTIFACT_VERSION,
        visibility=_visibility(card),
        observed_viewport_indexes=[observation.viewport_index],
        observations=[observation],
        evidence_fingerprint=_structural_fingerprint(card),
        identity_diagnostics=[
            {
                "decision": "created",
                "reason": "new_runtime_card",
                "viewport_index": observation.viewport_index,
                "visible_order": observation.visible_order,
            }
        ],
    )


def _record_identity_diagnostic(
    item: RuntimeInventoryItem,
    *,
    decision: str,
    reason: str,
    observation: InventoryObservation,
    evidence: Mapping[str, Any] | None = None,
) -> None:
    diagnostic = {
        "decision": decision,
        "reason": reason,
        "viewport_index": observation.viewport_index,
        "visible_order": observation.visible_order,
    }
    if evidence:
        diagnostic["evidence"] = dict(evidence)
    item.identity_diagnostics.append(diagnostic)


def _merge_observation(
    item: RuntimeInventoryItem,
    observation: InventoryObservation,
    *,
    reason: str,
    evidence: Mapping[str, Any] | None = None,
) -> None:
    if observation.fingerprint in {entry.fingerprint for entry in item.observations}:
        _record_identity_diagnostic(
            item,
            decision="ignored",
            reason="same_viewport_exact_duplicate",
            observation=observation,
        )
        return
    item.observations.append(observation)
    if observation.viewport_index not in item.observed_viewport_indexes:
        item.observed_viewport_indexes.append(observation.viewport_index)
    item.merge_reason = reason
    _record_identity_diagnostic(
        item,
        decision="merged",
        reason=reason,
        observation=observation,
        evidence=evidence,
    )


def _observation_bounds(
    observation: InventoryObservation,
) -> tuple[int, int, int, int] | None:
    return _bounds_parts(observation.bounds)


def _observation_structural_fingerprint(observation: InventoryObservation) -> str:
    bounds = _observation_bounds(observation)
    left, top, right, bottom = bounds or (0, 0, 0, 0)
    return _digest(
        [
            observation.stable_label,
            observation.resource_id,
            observation.class_name,
            left,
            max(0, right - left),
            max(0, bottom - top),
        ]
    )


def _same_descriptor(
    previous: InventoryObservation,
    current: InventoryObservation,
) -> bool:
    previous_bounds = _observation_bounds(previous)
    current_bounds = _observation_bounds(current)
    if not previous_bounds or not current_bounds:
        return False
    previous_left, _previous_top, previous_right, _previous_bottom = previous_bounds
    current_left, _current_top, current_right, _current_bottom = current_bounds
    return bool(
        _normalized(previous.stable_label)
        and _normalized(previous.stable_label) == _normalized(current.stable_label)
        and _normalized(previous.display_label) == _normalized(current.display_label)
        and previous.resource_id
        and previous.resource_id == current.resource_id
        and previous.class_name
        and previous.class_name == current.class_name
        and previous_left == current_left
        and previous_right == current_right
    )


def _is_full_card_transition_match(
    item: RuntimeInventoryItem,
    observation: InventoryObservation,
) -> bool:
    previous = item.observations[-1]
    if not _same_descriptor(previous, observation):
        return False
    previous_bounds = _observation_bounds(previous)
    current_bounds = _observation_bounds(observation)
    if not previous_bounds or not current_bounds:
        return False
    _left, previous_top, _right, previous_bottom = previous_bounds
    _left, current_top, _right, current_bottom = current_bounds
    return bool(
        current_top < previous_top
        and current_bottom < previous_bottom
        and (previous_bottom - previous_top) == (current_bottom - current_top)
    )


def _dominant_scroll_delta(
    previous_items: list[RuntimeInventoryItem],
    observations: list[InventoryObservation],
) -> int | None:
    previous_groups: dict[str, list[RuntimeInventoryItem]] = {}
    current_groups: dict[str, list[InventoryObservation]] = {}
    for item in previous_items:
        previous_groups.setdefault(item.evidence_fingerprint, []).append(item)
    for observation in observations:
        current_groups.setdefault(
            _observation_structural_fingerprint(observation),
            [],
        ).append(observation)

    deltas: list[int] = []
    for structural_key, items in previous_groups.items():
        current = current_groups.get(structural_key, [])
        if len(items) != 1 or len(current) != 1:
            continue
        previous_observation = items[0].observations[-1]
        current_observation = current[0]
        if not _is_full_card_transition_match(items[0], current_observation):
            continue
        previous_bounds = _observation_bounds(previous_observation)
        current_bounds = _observation_bounds(current_observation)
        if previous_bounds and current_bounds:
            deltas.append(current_bounds[1] - previous_bounds[1])
    if not deltas:
        return None
    counts = {delta: deltas.count(delta) for delta in set(deltas)}
    highest_count = max(counts.values())
    winners = [delta for delta, count in counts.items() if count == highest_count]
    return winners[0] if len(winners) == 1 else None


def _matches_scroll_delta(
    item: RuntimeInventoryItem,
    observation: InventoryObservation,
    *,
    scroll_delta: int | None,
    tolerance: int = 8,
) -> bool:
    if scroll_delta is None:
        return False
    previous_bounds = _observation_bounds(item.observations[-1])
    current_bounds = _observation_bounds(observation)
    if not previous_bounds or not current_bounds:
        return False
    return abs((current_bounds[1] - previous_bounds[1]) - scroll_delta) <= tolerance


def _is_boundary_overlap_match(
    item: RuntimeInventoryItem,
    observation: InventoryObservation,
    *,
    scroll_delta: int | None,
    viewport_top: int,
    edge_tolerance: int = 8,
    boundary_tolerance: int = 12,
) -> bool:
    if scroll_delta is None or scroll_delta >= 0:
        return False
    previous = item.observations[-1]
    if not _same_descriptor(previous, observation):
        return False
    previous_bounds = _observation_bounds(previous)
    current_bounds = _observation_bounds(observation)
    if not previous_bounds or not current_bounds:
        return False
    _left, previous_top, _right, previous_bottom = previous_bounds
    _left, current_top, _right, current_bottom = current_bounds
    projected_top = previous_top + scroll_delta
    projected_bottom = previous_bottom + scroll_delta
    return bool(
        abs(current_top - viewport_top) <= boundary_tolerance
        and current_top > projected_top + edge_tolerance
        and abs(current_bottom - projected_bottom) <= edge_tolerance
        and current_bottom > current_top
        and (current_bottom - current_top) < (previous_bottom - previous_top)
    )


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
        current_observation_items: dict[str, RuntimeInventoryItem] = {}
        observations = [
            _make_observation(
                card,
                viewport_index=viewport_index,
                scroll_generation=scroll_generation,
                captured_at=captured_at,
                visible_order=visible_order,
            )
            for visible_order, card in enumerate(cards)
        ]
        previous_items = [
            item
            for item in items
            if item.observed_viewport_indexes[-1] == viewport_index - 1
        ]
        scroll_delta = _dominant_scroll_delta(previous_items, observations)
        viewport_tops = [
            bounds[1]
            for observation in observations
            if (bounds := _observation_bounds(observation))
        ]
        viewport_top = min(viewport_tops, default=0)
        structural_groups: dict[str, list[RuntimeInventoryItem]] = {}
        for item in previous_items:
            structural_groups.setdefault(item.evidence_fingerprint, []).append(item)

        for card, observation in zip(cards, observations):
            duplicate_item = current_observation_items.get(observation.fingerprint)
            if duplicate_item is not None:
                _merge_observation(
                    duplicate_item,
                    observation,
                    reason="same_viewport_exact_duplicate",
                )
                continue

            structural_key = _structural_fingerprint(card)
            candidates = [
                item
                for item in structural_groups.get(structural_key, [])
                if item.runtime_card_id not in matched_item_ids
                and _is_full_card_transition_match(item, observation)
                and _matches_scroll_delta(
                    item,
                    observation,
                    scroll_delta=scroll_delta,
                )
            ]
            if len(candidates) == 1:
                item = candidates[0]
                previous_bounds = _observation_bounds(item.observations[-1])
                current_bounds = _observation_bounds(observation)
                transition_delta = (
                    current_bounds[1] - previous_bounds[1]
                    if previous_bounds and current_bounds
                    else None
                )
                _merge_observation(
                    item,
                    observation,
                    reason="adjacent_viewport_composite_match",
                    evidence={
                        "scroll_direction": "down",
                        "top_delta": transition_delta,
                        "descriptor_match": True,
                        "full_card_geometry_match": True,
                    },
                )
                matched_item_ids.add(item.runtime_card_id)
                current_observation_items[observation.fingerprint] = item
                continue

            boundary_candidates = [
                item
                for item in previous_items
                if item.runtime_card_id not in matched_item_ids
                and _is_boundary_overlap_match(
                    item,
                    observation,
                    scroll_delta=scroll_delta,
                    viewport_top=viewport_top,
                )
            ]
            if len(boundary_candidates) == 1:
                item = boundary_candidates[0]
                _merge_observation(
                    item,
                    observation,
                    reason="boundary_overlap_translated_edge",
                    evidence={
                        "scroll_direction": "down",
                        "dominant_scroll_delta": scroll_delta,
                        "viewport_top": viewport_top,
                        "descriptor_match": True,
                        "translated_bottom_edge_match": True,
                    },
                )
                matched_item_ids.add(item.runtime_card_id)
                current_observation_items[observation.fingerprint] = item
                continue

            ambiguous_candidates = candidates or boundary_candidates
            if len(ambiguous_candidates) > 1:
                warnings.append(
                    f"ambiguous_boundary_match:viewport={viewport_index}:"
                    f"fingerprint={structural_key}"
                )
            same_label_previous = [
                item
                for item in previous_items
                if _normalized(item.stable_label) == _normalized(observation.stable_label)
            ]
            item = _make_item(
                card,
                observation,
                inventory_id=inventory_id,
                sequence=len(items) + 1,
            )
            if len(ambiguous_candidates) > 1:
                item.identity_confidence = "low"
                item.merge_reason = "ambiguous_duplicate"
                _record_identity_diagnostic(
                    item,
                    decision="not_merged",
                    reason="ambiguous_duplicate",
                    observation=observation,
                    evidence={"candidate_count": len(ambiguous_candidates)},
                )
            elif same_label_previous:
                item.merge_reason = "not_merged_same_label"
                _record_identity_diagnostic(
                    item,
                    decision="not_merged",
                    reason="not_merged_same_label",
                    observation=observation,
                    evidence={
                        "candidate_count": len(same_label_previous),
                        "strong_boundary_evidence": False,
                    },
                )
            items.append(item)
            matched_item_ids.add(item.runtime_card_id)
            current_observation_items[observation.fingerprint] = item

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
