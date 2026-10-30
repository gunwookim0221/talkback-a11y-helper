"""Immutable Phase 2B sidecar. Retains discriminators omitted by Phase 2A.

No UI I/O. Caller input is observed evidence, never an expected route. The
fingerprint contract remains unchanged; equality needs this secondary evidence
to distinguish a coarse-hash collision from focus/value/ordering changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from copy import deepcopy
from collections import Counter
from typing import Any, Mapping
import unicodedata

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.label_matcher import canonicalize_label
from tb_runner.scroll_reliability import flat_nodes
from tb_runner.state_fingerprint import (
    SCHEMA_VERSION as FINGERPRINT_SCHEMA, NORMALIZATION_VERSION, StateFingerprint,
    _bounds, _boolean, _label, _semantic_node, build_state_fingerprint,
    hierarchy_overlay_projection, normalize_dynamic_text, validated_capture_root_tree,
)
from tb_runner.phase3_context import resolve_phase3_context
from tb_runner.semantic_substate import (
    LEGACY_SIDECAR_VERSION, SUBSTATE_SIDECAR_VERSION,
    extract_semantic_substates, legacy_substates, normalize_substate_records,
)

OBSERVATION_SCHEMA = "state-observation-v1"
SECONDARY_VERSION = SUBSTATE_SIDECAR_VERSION
COVERAGES = frozenset({"OBSERVED_PARTIAL", "OBSERVED_FULL", "UNOBSERVED"})
_STATUS = {
    "locked": "locked", "door locked": "locked", "잠김": "locked", "잠금": "locked", "문 잠김": "locked",
    "unlocked": "unlocked", "door unlocked": "unlocked", "잠금 해제": "unlocked",
    "connected": "connected", "연결됨": "connected", "연결됨 상태": "connected",
    "disconnected": "disconnected", "연결 끊김": "disconnected", "연결 해제됨": "disconnected",
    "online": "online", "온라인": "online", "offline": "offline", "오프라인": "offline",
    "door open": "open", "문 열림": "open", "door closed": "closed", "문 닫힘": "closed",
    "loading": "loading", "로딩 중": "loading",
}
_LOCALE_LABELS = {"device": "device", "장치": "device"}


def _normalized_label(value: Any) -> str:
    normalized = normalize_dynamic_text(unicodedata.normalize("NFC", str(value or "")))
    return (_STATUS.get(normalized) or _LOCALE_LABELS.get(normalized)
            or canonicalize_label(normalized, domain="bottom_tab") or normalized)


def _secondary_node(node: Mapping[str, Any], display: Any) -> dict[str, Any]:
    semantic = _semantic_node(node, display)
    state = next((_STATUS[value] for name in ("semantic_state", "stateDescription", "text", "contentDescription")
                  if (value := normalize_dynamic_text(unicodedata.normalize("NFC", str(node.get(name) or "")))) in _STATUS), None)
    return dict(semantic=semantic, label=_normalized_label(_label(node)), semantic_value=state)


def fingerprint_from_dict(value: Mapping[str, Any]) -> StateFingerprint:
    """Validate existing Phase 2A hashes before accepting a saved fingerprint."""
    if value.get("schema_version") != FINGERPRINT_SCHEMA:
        raise ValueError("incompatible fingerprint schema")
    sections = {}
    for key in ("core", "viewport", "overlay", "transient"):
        if not isinstance(value.get(key), dict):
            raise ValueError("invalid fingerprint section: " + key)
        sections[key] = value[key]
    if sections["core"].get("normalization_version") != NORMALIZATION_VERSION:
        raise ValueError("incompatible fingerprint normalization")
    for key in ("core", "viewport", "overlay"):
        if value.get(key + "_signature") != canonical_sha256(sections[key]):
            raise ValueError("fingerprint component checksum mismatch: " + key)
    normalized = dict(schema_version=FINGERPRINT_SCHEMA, **{k: sections[k] for k in ("core", "viewport", "overlay")})
    if value.get("fingerprint_hash") != canonical_sha256(normalized):
        raise ValueError("fingerprint checksum mismatch")
    return StateFingerprint(FINGERPRINT_SCHEMA, value["core_signature"], value["viewport_signature"],
                            value["overlay_signature"], value["fingerprint_hash"],
                            *(canonical_json(sections[k]) for k in ("core", "viewport", "overlay", "transient")))


@dataclass(frozen=True)
class StateObservation:
    observation_id: str
    fingerprint: StateFingerprint
    coverage: str
    _secondary_json: str = field(repr=False)
    _document_json: str = field(repr=False)

    @property
    def secondary(self) -> dict[str, Any]:
        return json.loads(self._secondary_json)

    @property
    def semantic_substates(self) -> list[dict[str, Any]]:
        sidecar = self.secondary
        if sidecar.get("version") == LEGACY_SIDECAR_VERSION:
            return legacy_substates(sidecar, self.fingerprint.to_dict()["core"])
        return deepcopy(sidecar.get("semantic_substates", []))

    def to_dict(self) -> dict[str, Any]:
        return dict(observation_id=self.observation_id, **json.loads(self._document_json))

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateObservation":
        if not isinstance(value, Mapping) or value.get("schema_version") != OBSERVATION_SCHEMA:
            raise ValueError("incompatible observation schema")
        document = {k: v for k, v in value.items() if k != "observation_id"}
        if value.get("observation_id") != canonical_sha256(document):
            raise ValueError("observation checksum mismatch")
        coverage = document.get("coverage")
        secondary = document.get("secondary")
        if (coverage not in COVERAGES or not isinstance(secondary, dict)
                or secondary.get("version") not in {LEGACY_SIDECAR_VERSION, SECONDARY_VERSION}):
            raise ValueError("invalid secondary observation contract")
        for key in ("nodes", "markers", "overlay_nodes"):
            nodes = secondary.get(key)
            if not isinstance(nodes, list) or any(not isinstance(n, dict) or not isinstance(n.get("semantic"), dict)
                                                 or not isinstance(n.get("label"), str) for n in nodes):
                raise ValueError("invalid secondary nodes: " + key)
        if secondary["version"] == SECONDARY_VERSION:
            records = normalize_substate_records(secondary.get("semantic_substates"))
            if records != secondary["semantic_substates"]:
                raise ValueError("semantic substate ordering or structure mismatch")
            available = Counter(canonical_json(n["semantic"]) for n in secondary["nodes"])
            for record in records:
                required = Counter(canonical_json(n) for n in record.get("evidence", {}).get("root_projection_nodes", []))
                if any(count > available[key] for key, count in required.items()):
                    raise ValueError("semantic substate root evidence is not present in the observation")
        fp = fingerprint_from_dict(document.get("fingerprint", {}))
        return cls(value["observation_id"], fp, coverage, canonical_json(secondary), canonical_json(document))


def build_state_observation(raw: Mapping[str, Any]) -> StateObservation:
    context = resolve_phase3_context(raw)
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    authority = validate_capture_authority(raw.get("capture_authority"))
    capture_root_tree = validated_capture_root_tree(raw, authority)
    root_is_current = authority is not None and capture_root_tree is not None
    capture_local_hierarchy = (root_is_current and context.get("status") == "UNRESOLVED_CONTEXT"
                               and context.get("reasons") == ["CAPTURE_COMPONENT_UNKNOWN"])
    fingerprint_input = raw
    if capture_local_hierarchy:
        # This marker is assigned only after validating the immutable authority
        # and matching both hierarchy IDs; callers cannot assert it themselves.
        fingerprint_input = dict(raw, context_source="capture_local_hierarchy_only")
    elif context.get("status") == "VERIFIED_PLUGIN_CONTEXT" and context.get("verified") is True:
        fingerprint_input = dict(raw)
        fingerprint_input["navigation_context"] = {
            "plugin": {"type": context["context_type"], "id": context["context_id"]}}
        fingerprint_input["context_source"] = "phase3_plugin_context_verified"
    elif context.get("status") == "VERIFIED_ROOT_CONTEXT" and context.get("verified") is True:
        fingerprint_input = dict(raw)
        fingerprint_input["navigation_context"] = {"bottom_tab": context["context_id"]}
        fingerprint_input["context_source"] = "phase3_root_context_verified"
    fp = build_state_fingerprint(fingerprint_input)
    # The tree root is the only viewport normalization source accepted here.
    display = _bounds({"bounds": authority.hierarchy_root_bounds}) if root_is_current else None
    # The exact root supplies package/window/geometry authority; preserve
    # the legacy Phase2 projection of its children as semantic nodes.
    hierarchy_nodes = (flat_nodes(capture_root_tree.get("children", [])) if root_is_current
                       else flat_nodes(raw.get("nodes", [])))
    nodes = [n for n in hierarchy_nodes
             if _boolean(n, ("isVisibleToUser", "visibleToUser", "visible")) is not False]
    overlay_source_nodes = list(flat_nodes([capture_root_tree])) if root_is_current else []
    _overlay_kind, hierarchy_overlay_nodes = hierarchy_overlay_projection(
        overlay_source_nodes, display if root_is_current else None)
    overlay_node_ids = {id(node) for node in hierarchy_overlay_nodes}
    # Preserve the base tree and modal subtree as separate hierarchy-bound
    # identities, matching the Phase 2 overlay contract.
    base_nodes = [node for node in nodes if id(node) not in overlay_node_ids]
    secondary_nodes = sorted((_secondary_node(n, display) for n in base_nodes), key=canonical_json)
    secondary_overlay_nodes = sorted((_secondary_node(n, display) for n in hierarchy_overlay_nodes),
                                     key=canonical_json)
    substates = extract_semantic_substates(raw, base_nodes, display)
    secondary_version = SECONDARY_VERSION if substates else LEGACY_SIDECAR_VERSION
    secondary = dict(version=secondary_version,
        nodes=secondary_nodes,
        markers=sorted((_secondary_node(n, None) for n in flat_nodes(raw.get("core_nodes", []))), key=canonical_json),
        # Only the same full-screen modal subtree already projected from the
        # authority-bound tree may participate in overlay identity.
        overlay_nodes=secondary_overlay_nodes,
        environment_partition=raw.get("environment_partition"),
        locale=raw.get("locale"), source=raw.get("source", "unspecified"))
    if substates:
        secondary["semantic_substates"] = substates
    coverage = raw.get("observation_coverage", "OBSERVED_PARTIAL")
    if coverage not in COVERAGES:
        raise ValueError("invalid observation coverage")
    document = dict(schema_version=OBSERVATION_SCHEMA, fingerprint=fp.to_dict(),
                    coverage=coverage, secondary=secondary)
    return StateObservation(canonical_sha256(document), fp, coverage, canonical_json(secondary), canonical_json(document))


def observation_problems(observation: StateObservation) -> tuple[str, ...]:
    data = observation.fingerprint.to_dict()
    core, viewport = data["core"], data["viewport"]
    transient = data["transient"]
    problems = []
    verified_plugin = transient.get("context_source") == "phase3_plugin_context_verified"
    verified_root = transient.get("context_source") == "phase3_root_context_verified"
    verified_context = verified_plugin or verified_root
    # build_state_observation sets this marker only after validating authority
    # and matching capture IDs; it never means Activity/screen context is VERIFIED.
    capture_local_hierarchy = bool(core.get("package_name") and
        transient.get("context_source") == "capture_local_hierarchy_only")
    required_fields = (("package_name",) if capture_local_hierarchy else
                       ("navigation_context",) + (() if verified_context else ("package_name", "activity_name")))
    for field in required_fields:
        if not core.get(field):
            problems.append("MISSING_" + field.upper())
    if (not verified_context and not capture_local_hierarchy
            and (not core.get("selected_tab") or core.get("selected_tab_status") not in {"explicit_verified", "observed_selected_node"})):
        problems.append("UNVERIFIED_SELECTED_CONTEXT")
    if not viewport.get("semantic_nodes") or observation.coverage == "UNOBSERVED":
        problems.append("UNOBSERVED_VIEWPORT")
    if viewport.get("bounds_strategy") != "relative-grid32":
        problems.append("UNKNOWN_GEOMETRY")
    if viewport.get("scroll", {}).get("contradictory") is True:
        problems.append("CONTRADICTORY_CAPABILITY")
    if transient.get("context_source") == "conflicting_observation":
        problems.append("CONFLICTING_CONTEXT")
    scenario_id = str(transient.get("scenario_id") or "")
    if scenario_id in {"life_food_plugin", "life_family_care_plugin", "life_find_plugin", "device_smoke_sensor_plugin"} \
            and not verified_plugin and not capture_local_hierarchy \
            and (core.get("navigation_context") or core.get("selected_tab")):
        problems.append("UNVERIFIED_PLUGIN_CONTEXT")
    return tuple(sorted(problems))
