"""Phase 2A observation fingerprints; no state identity or runtime decisions.

Core describes observed navigation context. Visible content belongs to viewport,
not to a whole-screen equality oracle. Focus, raw values and positional IDs are
diagnostics. Hash agreement is never a claim that two observations are one state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.label_matcher import canonicalize_label
from tb_runner.scroll_reliability import flat_nodes
from tb_runner.traversal_reliability import instance_id, normalized_bounds
from tb_runner.utils import parse_bounds_str

SCHEMA_VERSION = "state-fingerprint-v1"
NORMALIZATION_VERSION = "semantic-values-v1-relative32"

# Explicit state vocabulary, independent of activation safety. Never mask these.
_STATE_LABELS = {
    "locked": "locked", "door locked": "locked", "잠김": "locked",
    "잠금": "locked", "문 잠김": "locked", "unlocked": "unlocked",
    "door unlocked": "unlocked", "잠금 해제": "unlocked",
    "door open": "open", "문 열림": "open", "door closed": "closed", "문 닫힘": "closed",
    "online": "online", "offline": "offline", "오프라인": "offline",
    "온라인": "online", "loading": "loading", "로딩 중": "loading",
}
_BOTTOM_IDS = {
    "menu_favorites": "home", "menu_devices": "devices", "menu_services": "life",
    "menu_automations": "routines", "menu_more": "menu",
}
_BOOL_FIELDS = {
    "enabled": ("enabled", "isEnabled"), "checked": ("checked", "isChecked"),
    "selected": ("selected", "isSelected"), "clickable": ("clickable", "effectiveClickable"),
    "focusable": ("focusable",), "scrollable": ("scrollable", "isScrollable"),
}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _first(node: Mapping[str, Any], *names: str) -> Any:
    return next((node[n] for n in names if node.get(n) is not None), None)


def _boolean(node: Mapping[str, Any], names: tuple[str, ...]) -> bool | None:
    value = _first(node, *names)
    return value if isinstance(value, bool) else None


def normalize_dynamic_text(value: Any) -> str:
    """Mask typed measurements and contextual clocks; keep general numbers/state.

    Not a general text scrubber: model numbers, prices, dates, countdowns and
    unrecognized measurements remain visible discriminators until reviewed.
    """
    text = _text(value)
    text = re.sub(r"(?<![\w.])[+-]?\d+(?:[.,]\d+)?\s*(?:°\s*[cf]|℃|℉)(?!\w)",
                  "<temperature>", text)
    if re.search(r"battery|배터리", text) or re.fullmatch(r"\d+(?:[.,]\d+)?\s*%", text):
        text = re.sub(r"\d+(?:[.,]\d+)?\s*%", "<percentage>", text)
    if re.search(r"\b(time|clock)\b|시간|시각", text) or re.fullmatch(r"\d{1,2}:\d{2}(?:\s*[ap]m)?", text):
        text = re.sub(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[ap]m)?\b", "<clock>", text)
    return text


def _label(node: Mapping[str, Any]) -> str:
    return next((str(node[name]) for name in ("text", "contentDescription", "talkbackLabel", "label")
                 if _text(node.get(name))), "")


def _semantic_state(node: Mapping[str, Any]) -> str | None:
    # Full-label matches avoid confusing "unlock door" (an action) with unlocked.
    for name in ("semantic_state", "stateDescription", "text", "contentDescription"):
        normalized = _text(node.get(name))
        if normalized in _STATE_LABELS:
            return _STATE_LABELS[normalized]
    return None


def _resource(node: Mapping[str, Any]) -> str:
    return str(_first(node, "viewIdResourceName", "resourceId", "resource_id", "view_id") or "").strip()


def _bounds(node: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    value = _first(node, "boundsInScreen", "bounds")
    if isinstance(value, (tuple, list)) and len(value) == 4:
        value = ",".join(str(v) for v in value)
    return parse_bounds_str(normalized_bounds(value))


def validated_capture_root_tree(
    observation: Mapping[str, Any], authority: Any | None = None,
) -> Mapping[str, Any] | None:
    """Return the exact helper root only when its bytes still match sealed authority."""
    from talkback_lib.reliable_hierarchy_schema import (
        capture_canonical_sha256, validate_capture_authority,
    )

    capture_authority = validate_capture_authority(
        authority if authority is not None else observation.get("capture_authority")
    )
    root = observation.get("_capture_root_tree")
    if capture_authority is None or not isinstance(root, Mapping):
        return None
    try:
        if capture_canonical_sha256(root) != capture_authority.root_digest:
            return None
    except (TypeError, ValueError):
        return None
    bounds = root.get("boundsInScreen", root.get("bounds"))
    if isinstance(bounds, Mapping):
        root_bounds = tuple(bounds.get(key, bounds.get(alias)) for key, alias in
                             (("l", "left"), ("t", "top"), ("r", "right"), ("b", "bottom")))
    else:
        root_bounds = _bounds({"bounds": bounds})
    if (root.get("packageName") != capture_authority.hierarchy_package_name
            or type(root.get("windowId")) is not int
            or root.get("windowId") != capture_authority.hierarchy_window_id
            or root.get("className") != capture_authority.hierarchy_root_class_name
            or root.get("sourceNodeId") != capture_authority.hierarchy_root_source_node_id
            or root_bounds != capture_authority.hierarchy_root_bounds):
        return None
    expected = {
        "capture_id": capture_authority.capture_key,
        "hierarchy_capture_id": capture_authority.capture_key,
        "hierarchy_snapshot_id": capture_authority.capture_key,
        "hierarchy_request_id": capture_authority.request_id,
        "hierarchy_capture_sequence": capture_authority.capture_sequence,
        "hierarchy_process_epoch": capture_authority.process_epoch,
        "hierarchy_generation": capture_authority.generation,
        "hierarchy_service_instance_id": capture_authority.service_instance_id,
        "hierarchy_root_digest": capture_authority.root_digest,
        "hierarchy_candidate_digest": capture_authority.candidate_digest,
        "traversal_root_digest": capture_authority.root_digest,
        "package_name": capture_authority.hierarchy_package_name,
        "traversal_root_ref": capture_authority.root_ref,
        "traversal_root_window_id": capture_authority.hierarchy_window_id,
        "traversal_root_class_name": capture_authority.hierarchy_root_class_name,
        "traversal_root_source_node_id": capture_authority.hierarchy_root_source_node_id,
    }
    for key, value in expected.items():
        if observation.get(key) != value:
            return None
    expected_bounds = (list(capture_authority.hierarchy_root_bounds)
                       if capture_authority.hierarchy_root_bounds is not None else None)
    for key in ("hierarchy_root_bounds", "traversal_root_bounds", "capture_root_bounds"):
        if observation.get(key) != expected_bounds:
            return None
    return root


def _layout(bounds: tuple[int, ...] | None, display: tuple[int, ...] | None) -> list[int] | None:
    if bounds is None or display is None:
        return None
    l, t, r, b = display
    return [round((v - (l if i % 2 == 0 else t)) * 32 / ((r-l) if i % 2 == 0 else (b-t)))
            for i, v in enumerate(bounds)]


def _semantic_node(node: Mapping[str, Any], display: tuple[int, ...] | None) -> dict[str, Any]:
    rid = _resource(node)
    semantic = _semantic_state(node)
    state_description = normalize_dynamic_text(node.get("stateDescription")) or None
    return {
        "resource_id": rid or None,
        "class_name": str(_first(node, "className", "class", "class_name") or "").strip() or None,
        "role": _text(_first(node, "role", "accessibilityRole")) or None,
        "semantic_state": semantic,
        "state_description": semantic or state_description,
        "text_fallback": normalize_dynamic_text(_label(node)) if not rid else None,
        "flags": {name: _boolean(node, aliases) for name, aliases in _BOOL_FIELDS.items()},
        "layout_bucket": _layout(_bounds(node), display),
    }


def _hierarchy_overlay_kind(node: Mapping[str, Any]) -> str | None:
    class_name = str(_first(node, "className", "class", "class_name") or "").casefold()
    resource = _resource(node).casefold()
    role = _text(_first(node, "role", "accessibilityRole"))
    tokens = " ".join((class_name, resource, role))
    if "dialog" in tokens or "alert" in tokens:
        return "dialog"
    if "bottomsheet" in tokens or "bottom_sheet" in tokens:
        return "bottom_sheet"
    if "popup" in tokens:
        return "popup"
    if "permission" in tokens or "modal" in tokens:
        return "hierarchy_modal"
    return None


def hierarchy_overlay_projection(
    nodes: list[Mapping[str, Any]], root_bounds: tuple[int, ...] | None,
) -> tuple[str, list[Mapping[str, Any]]]:
    """Project only a full-screen modal subtree present in the captured tree.

    WMS, Activity, popup classification, and caller-supplied ``overlay`` values
    do not participate. A candidate must be a modal-shaped hierarchy node whose
    own bounds cover at least 85% of the validated traversal root.
    """
    if (not root_bounds or len(root_bounds) != 4
            or any(type(value) is not int for value in root_bounds)):
        return "unknown", []
    left, top, right, bottom = root_bounds
    root_area = max(0, right - left) * max(0, bottom - top)
    if not root_area:
        return "unknown", []

    modal_roots: list[tuple[Mapping[str, Any], str]] = []
    for node in nodes:
        kind = _hierarchy_overlay_kind(node)
        bounds = _bounds(node)
        if kind is None or bounds is None:
            continue
        l, t, r, b = bounds
        covered = max(0, min(right, r) - max(left, l)) * max(0, min(bottom, b) - max(top, t))
        if covered / root_area >= 0.85:
            modal_roots.append((node, kind))
    if not modal_roots:
        return "unknown", []

    selected: list[Mapping[str, Any]] = []
    selected_ids: set[int] = set()
    kinds = set()
    for root, kind in modal_roots:
        kinds.add(kind)
        root_path = str(root.get("stable_node_path") or "")
        if root_path:
            subtree = [node for node in nodes
                       if (str(node.get("stable_node_path") or "") == root_path
                           or str(node.get("stable_node_path") or "").startswith(root_path + "."))]
        else:
            subtree = list(flat_nodes([root]))
        for node in subtree:
            if id(node) not in selected_ids:
                selected_ids.add(id(node))
                selected.append(node)
    kind = next(iter(kinds)) if len(kinds) == 1 else "mixed_modal"
    return kind, selected


def _selected_tab(observation: Mapping[str, Any], nodes: list[dict[str, Any]], *,
                  allow_explicit: bool = True) -> tuple[str | None, str]:
    explicit = observation.get("selected_tab") if allow_explicit else None
    if isinstance(explicit, Mapping) and explicit.get("verified") is True:
        name = _text(explicit.get("name"))
        if name:
            return canonicalize_label(name, domain="bottom_tab") or name, "explicit_verified"
    candidates = []
    for node in nodes:
        if _boolean(node, ("selected", "isSelected")) is not True:
            continue
        suffix = _resource(node).rsplit("/", 1)[-1]
        tab = _BOTTOM_IDS.get(suffix)
        if not tab and (node.get("isBottomNavigationBar") is True or _text(node.get("role")) == "tab"):
            tab = canonicalize_label(_label(node), domain="bottom_tab")
        if tab:
            candidates.append(tab)
    # Two selected nodes are ambiguous even if they carry the same label.
    if len(candidates) == 1:
        return candidates[0], "observed_selected_node"
    return None, "ambiguous" if candidates else "unknown"


@dataclass(frozen=True)
class StateFingerprint:
    """Immutable canonical sections; to_dict returns independent mutable copies."""
    schema_version: str
    core_signature: str
    viewport_signature: str
    overlay_signature: str
    fingerprint_hash: str
    _core_json: str = field(repr=False)
    _viewport_json: str = field(repr=False)
    _overlay_json: str = field(repr=False)
    _transient_json: str = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        import json
        return dict(schema_version=self.schema_version,
                    core_signature=self.core_signature, viewport_signature=self.viewport_signature,
                    overlay_signature=self.overlay_signature, fingerprint_hash=self.fingerprint_hash,
                    core=json.loads(self._core_json), viewport=json.loads(self._viewport_json),
                    overlay=json.loads(self._overlay_json), transient=json.loads(self._transient_json))

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def build_state_fingerprint(observation: Mapping[str, Any]) -> StateFingerprint:
    """Pure, no I/O. Input values must be observed facts, never requested routes.

    nodes is a partial visible observation. core_nodes, if supplied, must be
    observed persistent screen markers, not arbitrary body nodes. No cross-run
    equality, state ID, registry, graph or action selection is implemented here.
    """
    raw_nodes = observation.get("nodes")
    if raw_nodes is not None and not isinstance(raw_nodes, list):
        raise ValueError("nodes must be a list or missing")
    input_nodes = list(flat_nodes(raw_nodes or []))
    # A sealed capture fingerprints only the exact DTO-derived root subtree.
    # The separately flattened compatibility view is diagnostic input only.
    from talkback_lib.reliable_hierarchy_schema import validate_capture_authority
    capture_authority = validate_capture_authority(observation.get("capture_authority"))
    capture_root_tree = validated_capture_root_tree(observation, capture_authority)
    capture_matches = capture_authority is not None and capture_root_tree is not None
    # The window root binds package/window/geometry; Phase2 semantic node
    # projection starts at its children, matching the legacy hierarchy view.
    all_nodes = (list(flat_nodes(capture_root_tree.get("children", [])))
                 if capture_matches else input_nodes)
    nodes = [n for n in all_nodes if _boolean(n, ("isVisibleToUser", "visibleToUser", "visible")) is not False]
    capture_root_bounds = (capture_authority.hierarchy_root_bounds if capture_matches else None)
    capture_root = _bounds({"bounds": capture_root_bounds})
    overlay_source_nodes = list(flat_nodes([capture_root_tree])) if capture_matches else []
    overlay_kind, hierarchy_overlay_nodes = hierarchy_overlay_projection(
        overlay_source_nodes, capture_root if capture_matches else None)
    overlay_node_ids = {id(node) for node in hierarchy_overlay_nodes}
    # A hierarchy-confirmed full-screen modal is a separate interaction
    # identity. Keep its subtree in the overlay projection and out of the
    # underlying viewport/root projection so it does not make the base opaque.
    base_nodes = [node for node in nodes if id(node) not in overlay_node_ids]
    semantic_nodes = sorted((_semantic_node(n, capture_root) for n in base_nodes), key=canonical_json)
    selected, selected_status = _selected_tab(observation, nodes, allow_explicit=not capture_matches)
    core_nodes = observation.get("core_nodes", [])
    if not isinstance(core_nodes, list):
        raise ValueError("core_nodes must be a list")
    # Caller-scoped persistent markers omit geometry; duplicate markers remain.
    markers = [_semantic_node(n, None) for n in flat_nodes(core_nodes)]
    package = (capture_authority.hierarchy_package_name if capture_matches else None)
    # Activity and WMS/window component strings are separately sampled
    # diagnostics. They are never authoritative fingerprint identity.
    activity = None
    core = dict(
        normalization_version=NORMALIZATION_VERSION,
        package_name=package, activity_name=activity,
        navigation_context=({"bottom_tab": selected} if selected else None)
                            if capture_matches else observation.get("navigation_context"),
        selected_tab=selected, selected_tab_status=selected_status,
        screen_markers=sorted(markers, key=canonical_json),
    )
    cap = observation.get("capability") or {}
    if not isinstance(cap, Mapping):
        raise ValueError("capability must be a mapping")
    viewport = dict(
        semantic_nodes=semantic_nodes,
        observation_status="OBSERVED_PARTIAL" if nodes else "UNOBSERVED",
        bounds_strategy="relative-grid32" if capture_root else "UNKNOWN_CAPTURE_ROOT_BOUNDS",
        scroll={key: cap.get(key) for key in (
            "status", "axis", "axis_contract", "can_scroll_forward",
            "vertical_can_scroll_forward", "horizontal_can_scroll_forward", "contradictory")},
    )
    overlay_input = observation.get("overlay") or {}
    if not isinstance(overlay_input, Mapping):
        raise ValueError("overlay must be a mapping")
    diagnostic_overlay_nodes = overlay_input.get("nodes", [])
    if not isinstance(diagnostic_overlay_nodes, list):
        raise ValueError("overlay nodes must be a list")
    overlay = dict(kind=overlay_kind, observed=bool(hierarchy_overlay_nodes),
                   semantic_nodes=sorted((_semantic_node(n, capture_root) for n in hierarchy_overlay_nodes),
                                         key=canonical_json))
    positional_ids = sorted(instance_id(dict(
        scenario_id=observation.get("scenario_id", ""), view_id=_resource(n),
        bounds=normalized_bounds(_first(n, "boundsInScreen", "bounds")), label=_label(n),
        class_name=_first(n, "className", "class"), stable_node_path=n.get("stable_node_path"),
    )) for n in base_nodes)
    # Full raw node payload is not copied into the artifact. Digest retains raw
    # value drift; sorted flat nodes make raw order changes diagnostic-stable.
    raw_digest = canonical_sha256(sorted(
        ({k: v for k, v in n.items() if k != "children"} for n in all_nodes), key=canonical_json))
    focus = observation.get("focus_node") or {}
    if not isinstance(focus, Mapping):
        raise ValueError("focus_node must be a mapping")
    transient = dict(
        timestamp=observation.get("timestamp"), scenario_id=observation.get("scenario_id"),
        step=observation.get("step", observation.get("step_index")),
        source=observation.get("source", observation.get("evidence", "unspecified")),
        context_source=observation.get("context_source", "unspecified"),
        raw_context={name: observation.get(name) for name in ("package_name", "activity_name")},
        raw_observation_digest=raw_digest, positional_instance_ids=positional_ids,
        focused_element_summary=dict(resource_id=_resource(focus) or None,
            bounds=normalized_bounds(_first(focus, "boundsInScreen", "bounds")) or None,
            accessibility_focused=_boolean(focus, ("accessibilityFocused", "accessibility_focused")),
            input_focused=_boolean(focus, ("focused",)),
            normalized_label=normalize_dynamic_text(_label(focus))),
        scroll_source=cap.get("source"), legacy_viewport=observation.get("viewport"),
        selected_tab_source=(observation.get("selected_tab") or {}).get("source")
                            if isinstance(observation.get("selected_tab"), Mapping) else selected_status,
        overlay_source=overlay_input.get("source", "unspecified"),
        overlay_diagnostic={key: overlay_input.get(key) for key in
                            ("kind", "observed", "classification", "candidate_present", "modal_evidence")},
        missing_fields=sorted(name for name in ("package_name", "activity_name", "navigation_context")
                              if core.get(name) is None),
        unknown_node_fields={name: sum(n["flags"][name] is None for n in semantic_nodes) for name in _BOOL_FIELDS},
        invalid_bounds_count=sum(_bounds(n) is None for n in base_nodes),
        unknown_visibility_count=sum(_boolean(n, ("isVisibleToUser", "visibleToUser", "visible")) is None for n in base_nodes),
        notes=observation.get("notes", []),
    )
    normalized = dict(schema_version=SCHEMA_VERSION, core=core, viewport=viewport, overlay=overlay)
    return StateFingerprint(SCHEMA_VERSION, canonical_sha256(core), canonical_sha256(viewport),
                            canonical_sha256(overlay), canonical_sha256(normalized),
                            canonical_json(core), canonical_json(viewport), canonical_json(overlay), canonical_json(transient))


def write_fingerprint_record(path: str | Path, fingerprint: StateFingerprint) -> None:
    """Explicit diagnostic append; no caller in production traversal paths."""
    record = fingerprint.to_dict()
    record.update(timestamp=record["transient"]["timestamp"],
                  scenario_id=record["transient"]["scenario_id"], step=record["transient"]["step"])
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(record) + "\n")
