"""Versioned, observed semantic children of a logical screen.

Substates are evidence attached to an observation. They never allocate a root
state or supply missing navigation context. The camera adapter recognizes the
card-local alert *family* inside the camera card and leaves the displayed event
type UNKNOWN unless a producer supplied a typed observation.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.scroll_reliability import flat_nodes

SUBSTATE_SCHEMA = "semantic-substate-v1"
SUBSTATE_SIDECAR_VERSION = "observed-discriminators-v2"
LEGACY_SIDECAR_VERSION = "observed-discriminators-v1"
CONFIDENCE = frozenset({"OBSERVED_EXACT", "BOUNDED_OBSERVED", "UNKNOWN"})
CAMERA_CARD_ID_TOKEN = "camera_card"
CAMERA_ALERT_ID_PREFIX = "camera_card_alert_"
_CAMERA_DOMAIN_VALUE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def _resource(node: Mapping[str, Any]) -> str:
    return str(next((node[k] for k in ("viewIdResourceName", "resourceId", "resource_id", "view_id", "resource-id")
                     if node.get(k) is not None), "") or "").strip()


def _visible(node: Mapping[str, Any]) -> bool:
    return not any(node.get(k) is False for k in ("visibleToUser", "isVisibleToUser", "visible"))


def _is_camera_card(resource_id: str) -> bool:
    tail = resource_id.rsplit("/", 1)[-1].casefold()
    return "camera" in tail and "card" in tail and "alert" not in tail


def _is_camera_alert(resource_id: str) -> bool:
    return resource_id.rsplit("/", 1)[-1].casefold().startswith(CAMERA_ALERT_ID_PREFIX)


def _under_camera_card(node: Mapping[str, Any], camera_card_paths: set[str]) -> bool:
    ancestors = node.get("ancestors")
    if isinstance(ancestors, list):
        for ancestor in ancestors:
            if isinstance(ancestor, Mapping) and _is_camera_card(_resource(ancestor)):
                return True
    path = str(node.get("stable_node_path") or "")
    return any(path.startswith(parent + ".") for parent in camera_card_paths if path)


def normalize_substate_records(records: Any) -> list[dict[str, Any]]:
    """Validate caller-supplied typed evidence without interpreting its value."""
    if not isinstance(records, list):
        raise ValueError("semantic_substates must be a list")
    normalized = []
    seen = set()
    required = {"schema_version", "category", "key", "value", "confidence", "evidence", "provenance"}
    for record in records:
        if not isinstance(record, Mapping) or set(record) != required:
            raise ValueError("invalid semantic substate fields")
        category, key, value = (record.get(k) for k in ("category", "key", "value"))
        if (record.get("schema_version") != SUBSTATE_SCHEMA or not isinstance(category, str)
                or not _CAMERA_DOMAIN_VALUE.fullmatch(category) or not isinstance(key, str)
                or not _CAMERA_DOMAIN_VALUE.fullmatch(key) or not isinstance(value, str)
                or not _CAMERA_DOMAIN_VALUE.fullmatch(value)):
            raise ValueError("invalid semantic substate identity")
        if record.get("confidence") not in CONFIDENCE:
            raise ValueError("invalid semantic substate confidence")
        evidence, provenance = record.get("evidence"), record.get("provenance")
        if not isinstance(evidence, Mapping) or not evidence or not isinstance(provenance, Mapping):
            raise ValueError("semantic substate needs observed evidence and provenance")
        producer, source = provenance.get("producer"), provenance.get("source")
        if not isinstance(producer, str) or not producer.strip() or not isinstance(source, str) or not source.strip():
            raise ValueError("semantic substate provenance is incomplete")
        identity = (category, key)
        if identity in seen:
            raise ValueError("duplicate semantic substate key")
        seen.add(identity)
        normalized.append(dict(schema_version=SUBSTATE_SCHEMA, category=category, key=key, value=value,
            confidence=record["confidence"], evidence=deepcopy(dict(evidence)), provenance=deepcopy(dict(provenance))))
    return sorted(normalized, key=lambda item: (item["category"], item["key"]))


def _node_map(nodes: list[dict[str, Any]], display: Any) -> dict[str, Any]:
    from tb_runner.state_observation import _secondary_node
    result = {}
    for node in nodes:
        if not _visible(node):
            continue
        rid = _resource(node)
        if rid:
            result.setdefault(rid, []).append(_secondary_node(node, display))
    return result


def extract_semantic_substates(raw: Mapping[str, Any], nodes: list[dict[str, Any]], display: Any) -> list[dict[str, Any]]:
    """Build versioned child observations from explicit or card-local evidence.

    Human-readable event names are accepted only from an explicit typed
    producer. UI resource IDs establish the camera semantic domain, never the
    specific HUMAN/MOTION/PET event type.
    """
    supplied = normalize_substate_records(raw.get("semantic_substates", []))
    selected = raw.get("selected_tab") or {}
    home = isinstance(selected, Mapping) and selected.get("name") == "home" and selected.get("verified") is True
    if not home:
        return supplied

    cards = [n for n in nodes if _visible(n) and _is_camera_card(_resource(n))]
    card_paths = {str(n.get("stable_node_path")) for n in cards if n.get("stable_node_path")}
    alert_nodes = [n for n in nodes if _visible(n) and _is_camera_alert(_resource(n))
                   and _under_camera_card(n, card_paths)]
    if not cards:
        if raw.get("package_name") != "com.samsung.android.oneconnect":
            return supplied
        camera_value, overlay_value = "UNKNOWN", "UNKNOWN"
        camera_confidence = overlay_confidence = "UNKNOWN"
        source = "camera_card_not_observed"
    elif not alert_nodes:
        camera_value, overlay_value = "NONE", "ABSENT"
        camera_confidence = overlay_confidence = "BOUNDED_OBSERVED"
        source = "camera_card_alert_family_absent"
    else:
        resources = {_resource(n).rsplit("/", 1)[-1].casefold() for n in alert_nodes}
        current_background = any(name.endswith("_current") for name in resources) or any(name.endswith("_background") for name in resources)
        previous_only = all(name.endswith("_previous") for name in resources)
        camera_value = "UNKNOWN"
        overlay_value = "ACTIVE_UNKNOWN" if current_background else "UNKNOWN"
        camera_confidence = "UNKNOWN"
        overlay_confidence = "BOUNDED_OBSERVED" if current_background else "UNKNOWN"
        source = "camera_alert_family_current_or_background" if current_background else (
            "camera_alert_family_previous_only" if previous_only else "camera_alert_family_unclassified")

    by_resource = _node_map(nodes, display)
    evidence_nodes = []
    for node in alert_nodes:
        evidence_nodes.extend(by_resource.get(_resource(node), []))
    excluded = [item["semantic"] for item in evidence_nodes]
    evidence = dict(camera_card_observed=bool(cards),
        camera_card_resource_ids=sorted({_resource(n) for n in cards}),
        alert_resource_ids=sorted(_resource(n) for n in alert_nodes),
        alert_nodes=evidence_nodes, root_projection_nodes=excluded)
    provenance = dict(producer="phase2.semantic_substate.camera_card_adapter",
        source=source, mapping_version="camera-alert-family-v1")
    derived = [dict(schema_version=SUBSTATE_SCHEMA, category="CAMERA", key="detection_event",
                    value=camera_value, confidence=camera_confidence, evidence=evidence, provenance=provenance),
               dict(schema_version=SUBSTATE_SCHEMA, category="CAMERA", key="overlay_state",
                    value=overlay_value, confidence=overlay_confidence, evidence=evidence, provenance=provenance)]
    # Explicit typed telemetry, when supplied by a future shadow collector, is
    # authoritative for the same key and remains separately auditable.
    supplied_by_key = {(r["category"], r["key"]): r for r in supplied}
    output = []
    for derived_record in derived:
        key = (derived_record["category"], derived_record["key"])
        typed = supplied_by_key.get(key)
        if typed is None:
            output.append(derived_record)
        else:
            # Typed domain values replace only the unknown value. Raw node
            # evidence and the exact root-projection proof remain attached.
            merged_evidence = dict(evidence)
            merged_evidence.update(typed["evidence"])
            output.append(dict(typed, evidence=merged_evidence,
                provenance=dict(typed["provenance"], ui_adapter=provenance)))
    output.extend(r for r in supplied if (r["category"], r["key"]) not in {("CAMERA", "detection_event"), ("CAMERA", "overlay_state")})
    return sorted(output, key=lambda item: (item["category"], item["key"]))


def legacy_substates(secondary: Mapping[str, Any], core: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Explicit v1 adapter for saved Phase 2/3 observations; never edits bytes."""
    if secondary.get("version") != LEGACY_SIDECAR_VERSION or core.get("selected_tab") != "home":
        return []
    semantics = [n.get("semantic", {}) for n in secondary.get("nodes", []) if isinstance(n, Mapping)]
    cards = [n for n in semantics if _is_camera_card(str(n.get("resource_id") or ""))]
    alerts = [n for n in semantics if _is_camera_alert(str(n.get("resource_id") or ""))]
    if not cards:
        return []
    resources = [str(n.get("resource_id") or "") for n in alerts]
    current_background = any(r.rsplit("/", 1)[-1].casefold().endswith(("_current", "_background")) for r in resources)
    camera_value = "UNKNOWN" if alerts else "NONE"
    overlay_value = "ACTIVE_UNKNOWN" if alerts and current_background else "UNKNOWN" if alerts else "ABSENT"
    confidence = "BOUNDED_OBSERVED" if current_background or not alerts else "UNKNOWN"
    evidence = dict(camera_card_observed=True, camera_card_resource_ids=sorted(n["resource_id"] for n in cards),
        alert_resource_ids=sorted(resources), alert_nodes=alerts,
        root_projection_nodes=alerts)
    provenance = dict(producer="phase2.semantic_substate.legacy_adapter", source="saved_v1_semantic_node_family",
        mapping_version="legacy-camera-alert-family-adapter-v1")
    return [dict(schema_version=SUBSTATE_SCHEMA, category="CAMERA", key=key, value=value,
        confidence=confidence, evidence=evidence, provenance=provenance)
        for key, value in (("detection_event", camera_value), ("overlay_state", overlay_value))]


def root_evidence_nodes(substates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {canonical_json(node): deepcopy(node) for item in substates
              for node in item.get("evidence", {}).get("root_projection_nodes", [])}
    return [unique[key] for key in sorted(unique)]


def logical_semantic_nodes(nodes: list[dict[str, Any]], substates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove only evidence explicitly preserved as a semantic child."""
    exclusions = Counter(canonical_json(n) for n in root_evidence_nodes(substates))
    result = []
    for node in nodes:
        key = canonical_json(node["semantic"])
        if exclusions[key]:
            exclusions[key] -= 1
        else:
            result.append(node)
    return sorted(result, key=canonical_json)


def compare_substates(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    a = {(item["category"], item["key"]): item for item in left}
    b = {(item["category"], item["key"]): item for item in right}
    changes = []
    for identity in sorted(a.keys() | b.keys()):
        av, bv = a.get(identity), b.get(identity)
        left_value = av.get("value") if av else None
        right_value = bv.get("value") if bv else None
        if av is None or bv is None or left_value != right_value:
            changes.append(dict(category=identity[0], key=identity[1], left=left_value, right=right_value,
                relation="UNKNOWN" if av is None or bv is None else "DIFFERENT",
                left_substate_hash=canonical_sha256(av) if av else None,
                right_substate_hash=canonical_sha256(bv) if bv else None))
    return dict(relation="DIFFERENT" if changes else "SAME", equal=not changes, changes=changes,
        left_hash=canonical_sha256(left), right_hash=canonical_sha256(right))
