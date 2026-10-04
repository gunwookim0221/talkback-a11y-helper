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


def _selected_tab(observation: Mapping[str, Any], nodes: list[dict[str, Any]]) -> tuple[str | None, str]:
    explicit = observation.get("selected_tab")
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
    all_nodes = list(flat_nodes(raw_nodes or []))
    nodes = [n for n in all_nodes if _boolean(n, ("isVisibleToUser", "visibleToUser", "visible")) is not False]
    display = _bounds({"bounds": observation.get("display_bounds")})
    semantic_nodes = sorted((_semantic_node(n, display) for n in nodes), key=canonical_json)
    selected, selected_status = _selected_tab(observation, nodes)
    core_nodes = observation.get("core_nodes", [])
    if not isinstance(core_nodes, list):
        raise ValueError("core_nodes must be a list")
    # Caller-scoped persistent markers omit geometry; duplicate markers remain.
    markers = [_semantic_node(n, None) for n in flat_nodes(core_nodes)]
    package = str(observation.get("package_name") or "").strip() or None
    activity = str(observation.get("activity_name") or "").strip() or None
    # Android ComponentName's short and full class forms are the same observed
    # component. Expansion requires the observed package, never a default app.
    if package and activity and activity.startswith("."):
        activity = package + activity
    core = dict(
        normalization_version=NORMALIZATION_VERSION,
        package_name=package, activity_name=activity,
        navigation_context=observation.get("navigation_context"),
        selected_tab=selected, selected_tab_status=selected_status,
        screen_markers=sorted(markers, key=canonical_json),
    )
    cap = observation.get("capability") or {}
    if not isinstance(cap, Mapping):
        raise ValueError("capability must be a mapping")
    viewport = dict(
        semantic_nodes=semantic_nodes,
        observation_status="OBSERVED_PARTIAL" if nodes else "UNOBSERVED",
        bounds_strategy="relative-grid32" if display else "UNKNOWN_NO_DISPLAY_BOUNDS",
        scroll={key: cap.get(key) for key in (
            "status", "axis", "axis_contract", "can_scroll_forward",
            "vertical_can_scroll_forward", "horizontal_can_scroll_forward", "contradictory")},
    )
    overlay_input = observation.get("overlay") or {}
    if not isinstance(overlay_input, Mapping):
        raise ValueError("overlay must be a mapping")
    overlay_nodes = overlay_input.get("nodes", [])
    if not isinstance(overlay_nodes, list):
        raise ValueError("overlay nodes must be a list")
    overlay = dict(kind=_text(overlay_input.get("kind")) or "unknown",
                   observed=overlay_input.get("observed") is True,
                   semantic_nodes=sorted((_semantic_node(n, display) for n in flat_nodes(overlay_nodes)), key=canonical_json))
    positional_ids = sorted(instance_id(dict(
        scenario_id=observation.get("scenario_id", ""), view_id=_resource(n),
        bounds=normalized_bounds(_first(n, "boundsInScreen", "bounds")), label=_label(n),
        class_name=_first(n, "className", "class"), stable_node_path=n.get("stable_node_path"),
    )) for n in nodes)
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
        missing_fields=sorted(name for name in ("package_name", "activity_name", "navigation_context")
                              if core.get(name) is None),
        unknown_node_fields={name: sum(n["flags"][name] is None for n in semantic_nodes) for name in _BOOL_FIELDS},
        invalid_bounds_count=sum(_bounds(n) is None for n in nodes),
        unknown_visibility_count=sum(_boolean(n, ("isVisibleToUser", "visibleToUser", "visible")) is None for n in nodes),
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
