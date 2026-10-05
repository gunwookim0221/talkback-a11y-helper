"""Phase 3A observation adapter. No client, executor, traversal ledger or graph.

Reuse Phase 0 positional populations, strict focus, axis-v1 and Global Nav.
Candidates describe observations; neither availability nor a safety hint grants
permission to activate. The caller's diagnostic Registry is the only mutation.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from tb_runner import completeness, global_navigation, plugin_card_discovery
from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.scenario_config import BOTTOM_TAB_GLOBAL_NAV
from tb_runner.scroll_reliability import flat_nodes
from tb_runner.state_equality import VerifiedScrollEvidence, _matching_nodes
from tb_runner.state_fingerprint import _bounds, _label
from tb_runner.state_observation import StateObservation, _secondary_node, build_state_observation
from tb_runner.state_registry import StateRegistry, StateResolution
from tb_runner.traversal_reliability import focus_instance, instance_id

CANDIDATE_SCHEMA = "discovery-action-candidate-v1"
SNAPSHOT_SCHEMA = "discovery-snapshot-v1"

# An inventory, not an executable routing table or safety classifier.
ACTION_INVENTORY = {
    "FOCUS_NEXT": ("AVAILABLE_NOW", "Helper selects next; no desired-target guarantee"),
    "FOCUS_TARGET": ("AVAILABLE_WITH_ADAPTER", "Existing explicit bounds focus; landing still needs verification"),
    "CLICK": ("UNSAFE_FOR_AUTO_ACTIVATION", "Existing click transport; target effects unknown"),
    "ACTIVATE": ("FUTURE", "A common activation contract is not implemented"),
    "BOTTOM_NAV": ("AVAILABLE_WITH_ADAPTER", "Reuse observed destinations; execution/verification stays separate"),
    "SCROLL_FORWARD_VERTICAL": ("AVAILABLE_WITH_ADAPTER", "axis-v1 forward evidence"),
    "SCROLL_BACKWARD_VERTICAL": ("AVAILABLE_WITH_ADAPTER", "axis-v1 backward evidence"),
    "SCROLL_FORWARD_HORIZONTAL": ("AVAILABLE_WITH_ADAPTER", "Directional/class evidence; not a vertical-content scroll"),
    "SCROLL_BACKWARD_HORIZONTAL": ("AVAILABLE_WITH_ADAPTER", "Directional/class evidence; separate executor semantics"),
    "MORE": ("FUTURE", "A label alone does not prove a navigation operation"),
    "EXPAND": ("FUTURE", "Requires supported action and resulting-context contract"),
    "BACK": ("UNSAFE_FOR_AUTO_ACTIVATION", "Existing key transport; app exit/unsaved effects possible"),
    "PLUGIN_NAVIGATION": ("AVAILABLE_WITH_ADAPTER", "Current-view card provenance, not a generic safe route"),
}


def collect_audit_inventory(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reuse V7's registration producer on an isolated, non-device sink.

    No snapshot capture/probe/coverage executor or user's runtime client is
    called. V7's focusability hints never override the current raw node flags.
    """
    from tb_runner.collection_flow import _register_focusable_inventory_node
    sink = SimpleNamespace()
    for node in flat_nodes(raw.get("nodes", [])):
        _register_focusable_inventory_node(sink,output_path="phase3-diagnostic-only",
            scenario_id=str(raw.get("scenario_id") or "diagnostic"),tab_name="",
            step_index=raw.get("step"),node=_node(node),source="dump_tree")
    return deepcopy(getattr(sink,"_focusable_inventory",[]))


def _node(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt legacy Audit names without turning focus flags into focusability."""
    n = deepcopy(dict(raw))
    n["viewIdResourceName"] = n.get("viewIdResourceName") or n.get("view_id") or n.get("resource_id") or n.get("resourceId") or ""
    n["className"] = n.get("className") or n.get("class_name") or n.get("class") or ""
    if not _label(n) and n.get("stable_label"):
        n["text"] = n["stable_label"]
    b = _bounds(n)
    n["boundsInScreen"] = ",".join(map(str, b)) if b else ""
    return n


def _target(node: dict[str, Any], scope: str) -> dict[str, Any]:
    item = completeness.candidate(node, scope)
    return dict(instance_id=instance_id(item), resource_id=item["view_id"],
                bounds=item["bounds"], class_name=item["class_name"], identity_confidence="POSITIONAL_ONLY")


def _semantics(node: dict[str, Any], display: Any) -> dict[str, Any]:
    secondary = _matching_nodes([_secondary_node(node, _bounds({"bounds": display}))])[0]
    semantic = secondary["semantic"]
    return dict(normalized_label=secondary["label"], semantic_value=secondary["semantic_value"],
                semantic_state=semantic["semantic_state"], state_description=semantic["state_description"],
                role=semantic["role"], flags=semantic["flags"])


@dataclass(frozen=True)
class DiscoveryActionCandidate:
    candidate_id: str
    state_id: str | None
    action_kind: str
    _document_json: str = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._document_json)

    def to_json(self) -> str:
        return self._document_json


def _behavior(candidate: dict[str, Any]) -> dict[str, Any]:
    # Sources/current-focus/timestamps/viewport references are diagnostics.
    return {k: candidate[k] for k in ("candidate_id", "state_id", "binding_status", "action_kind",
                                    "target_identity", "target_semantics", "eligibility", "safety_hint")}


@dataclass(frozen=True)
class DiscoverySnapshot:
    state_id: str | None
    candidate_set_hash: str
    candidates: tuple[DiscoveryActionCandidate, ...]
    _document_json: str = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._document_json)

    def to_json(self) -> str:
        return self._document_json


def _collect(raw: Mapping[str, Any], observation: StateObservation, resolution: StateResolution,
             registry_event: int, audit_inventory: list, lifecycle_records: list) -> DiscoverySnapshot:
    sid = resolution.state_id
    scope = sid or "unresolved:" + observation.observation_id
    display = raw.get("display_bounds")
    nodes = [_node(n) for n in flat_nodes(raw.get("nodes", []))]
    excluded: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        item = completeness.candidate(node, scope)
        eligible, reason = completeness.eligibility(item)
        if reason == "no_label_or_role" and (item["focusable"] is True or item["clickable"] is True):
            # Same root ContentTerminal exception, explicitly kept diagnostic.
            eligible, reason = "EXPECTED", "actionable_without_label"
        target = _target(node, scope)
        if eligible == "OUT_OF_SCOPE":
            excluded.append(dict(target_identity=target, reason=reason, source="ACCESSIBILITY_TREE"))
            continue
        groups[canonical_json(target)].append(dict(node=node, eligibility=eligible, reason=reason))

    # Reuse current-view plugin producers only for provenance. Their label-based
    # dedup/ordinal IDs never replace instance-v1 or suppress a raw tree target.
    core = observation.fingerprint.to_dict()["core"]
    root = core.get("selected_tab")
    plugins = plugin_card_discovery.discover_device_cards(nodes) if root == "devices" else (
        plugin_card_discovery.discover_life_cards_from_nodes(nodes) if root == "life" else [])
    audit_by_target: dict[str, list] = defaultdict(list)
    for record in audit_inventory:
        n = _node(record)
        key = canonical_json(_target(n, scope))
        foreign = record.get("state_id") is not None and record["state_id"] != sid
        epoch = record.get("observation_id")
        if foreign or epoch is not None and epoch != observation.observation_id or key not in groups:
            excluded.append(dict(target_identity=_target(n, scope), source="AUDIT_EXPECTED",
                                 reason="STATE_SCOPE_MISMATCH" if foreign else "NOT_CURRENT_OBSERVATION"))
        else:
            audit_by_target[key].append(record)

    stale = set()
    for record in lifecycle_records:
        key = canonical_json(_target(_node(record), scope))
        # Historical aliases cannot cross a state or snapshot boundary. Fresh
        # tree presence is not retired by an unscoped old STALE flag.
        scoped = sid is not None and record.get("state_id") == sid and record.get("observation_id") == observation.observation_id
        if scoped and (record.get("lifecycle") == "STALE" or record.get("stale_alias") is True or record.get("current_presence") is False):
            stale.add(key)
        elif not scoped:
            excluded.append(dict(source="CANDIDATE_LIFECYCLE", reason="UNVERIFIED_LIFECYCLE_SCOPE", target_identity=_target(_node(record), scope)))

    focus = _node(raw.get("focus_node") or {})
    focus_row = dict(scenario_id=scope, focus_node=focus, focus_view_id=focus["viewIdResourceName"],
                     focus_bounds=focus["boundsInScreen"], visible_label=_label(focus))
    for name in ("actual_focus_node", "actual_focus_accessibility_focused", "actual_focus_input_focused",
                 "actual_focus_resource_id", "actual_focus_bounds", "actual_focus_visible", "actual_focus_speech",
                 "focus_transition_status", "focus_reconciliation_confidence", "physical_visited"):
        if name in raw: focus_row[name] = raw[name]
    actual = focus_instance(focus_row)
    focus_id = instance_id(actual) if actual else None
    nav = global_navigation.discover(nodes, dict(global_nav=BOTTOM_TAB_GLOBAL_NAV))
    nav_by_target = {_target(_node(n), scope)["instance_id"]: n for n in nav}
    rows: list[dict[str, Any]] = []
    collisions = 0

    def add(kind, target, semantic, sources, availability, evidence, safety="UNKNOWN", observed_eligibility="EXPECTED"):
        identity = dict(schema_version=CANDIDATE_SCHEMA, state_scope=scope, action_kind=kind, target_identity=target)
        cid = "discovery:" + canonical_sha256(identity)
        rows.append(dict(schema_version=CANDIDATE_SCHEMA, candidate_id=cid, state_id=sid,
            binding_status="RESOLVED" if sid is not None else "UNRESOLVED", action_kind=kind,
            target_identity=target, target_semantics=semantic, source=sorted(set(sources)),
            confidence="BOUNDED_OBSERVED" if availability == "AVAILABLE" else "UNKNOWN",
            safety_hint=safety, eligibility=dict(observed=observed_eligibility, availability=availability,
                auto_activation_allowed=False), evidence=evidence,
            context=dict(observation_id=observation.observation_id, viewport_signature=observation.fingerprint.viewport_signature),
            physical_visit_credited=False))

    focus_targets = 0
    for key in sorted(groups):
        members = groups[key]
        variants = {canonical_json(_semantics(m["node"], display)) for m in members}
        target = json.loads(key)
        if len(variants) != 1:
            collisions += 1
            excluded.append(dict(source="ACCESSIBILITY_TREE", target_identity=target, reason="TARGET_IDENTITY_COLLISION",
                                 semantic_variants=[json.loads(v) for v in sorted(variants)]))
            continue
        if key in stale:
            excluded.append(dict(source="CANDIDATE_LIFECYCLE", target_identity=target, reason="STALE_NOT_ACTIONABLE"))
            continue
        semantic = json.loads(next(iter(variants)))
        flags = semantic["flags"]
        sources = ["ACCESSIBILITY_TREE"]
        if audit_by_target[key]: sources.append("AUDIT_EXPECTED")
        if target["instance_id"] == focus_id: sources.append("CURRENT_FOCUS")
        matching_plugins = [p for p in plugins if p.get("bounds") == target["bounds"] and p.get("resource_id") == target["resource_id"]]
        if matching_plugins: sources.append("PLUGIN_NAVIGATION")
        evidence = dict(producer="completeness.candidate/eligibility", eligibility_reason=members[0]["reason"],
            current_presence=True, strict_current_focus=target["instance_id"] == focus_id,
            audit_sources=sorted({str(a.get("source", "unknown")) for a in audit_by_target[key]}),
            plugin_provenance=sorted({str(p.get("existing_scenario_id") or p.get("type")) for p in matching_plugins}),
            visit_credit=0)
        availability = "DISABLED" if flags["enabled"] is False else "AVAILABLE" if flags["enabled"] is True else "UNKNOWN"
        if flags["focusable"] is True:
            focus_targets += availability == "AVAILABLE"
            add("FOCUS_TARGET", target, semantic, sources, availability, evidence, "READ_ONLY", members[0]["eligibility"])
        destination = nav_by_target.get(target["instance_id"])
        if destination:
            add("BOTTOM_NAV", dict(target, destination=destination["logical_name"]), semantic,
                [*sources, "GLOBAL_NAV"], "ALREADY_SELECTED" if destination["selected"] else availability,
                dict(evidence, nav_source=destination["evidence_source"]), "NAVIGATION")
        elif flags["clickable"] is True:
            add("CLICK", target, semantic, sources, availability, evidence, observed_eligibility=members[0]["eligibility"])

    if focus_targets:
        add("FOCUS_NEXT", dict(operation="HELPER_SMART_NEXT_UNTARGETED"), {}, ["SMART_NEXT"], "AVAILABLE",
            dict(selection="HELPER_SELECTS_NEXT_NOT_DESIRED_TARGET", action_executed=False, visit_credit=0), "READ_ONLY")

    cap = raw.get("capability") or {}
    containers = cap.get("containers") or ([cap["container"]] if cap.get("container") else [])
    for container in containers:
        n = _node(container)
        target = _target(n, scope)
        bounds = _bounds(n)
        axis = container.get("axis")
        if cap.get("axis_contract") != "axis-v1" or axis not in {"VERTICAL", "HORIZONTAL", "BIDIRECTIONAL"} or not bounds or cap.get("contradictory") is True:
            excluded.append(dict(source="SCROLL_CAPABILITY", target_identity=target, reason="UNVERIFIED_SCROLL_AXIS_OR_TARGET"))
            continue
        if container.get("isVisibleToUser", container.get("visibleToUser")) is False or container.get("isEnabled",container.get("enabled")) is False:
            continue
        actions = {a.get("id") if isinstance(a, dict) else a for a in container.get("actions", [])}
        for dimension in ("VERTICAL", "HORIZONTAL"):
            if axis not in {dimension, "BIDIRECTIONAL"}: continue
            for direction in ("FORWARD", "BACKWARD"):
                field, action_id = {("VERTICAL","FORWARD"):("scroll_down_supported",16908346),
                    ("VERTICAL","BACKWARD"):("scroll_up_supported",16908344),
                    ("HORIZONTAL","FORWARD"):("scroll_right_supported",16908347),
                    ("HORIZONTAL","BACKWARD"):("scroll_left_supported",16908345)}[(dimension,direction)]
                signals = []
                if container.get(field) is True: signals.append(field)
                if action_id in actions: signals.append("action_id:"+str(action_id))
                # Generic direction cannot select a dimension on bidirectional
                # containers. A known single axis may use generic action codes.
                if axis == dimension:
                    generic = "scroll_forward_supported" if direction == "FORWARD" else "scroll_backward_supported"
                    fallback = "canScrollForward" if direction == "FORWARD" else "canScrollBackward"
                    if container.get(generic) is True: signals.append(generic)
                    elif generic not in container and container.get(fallback) is True: signals.append(fallback)
                    generic_id = 4096 if direction == "FORWARD" else 8192
                    if generic_id in actions: signals.append("action_id:"+str(generic_id))
                if signals:
                    add("SCROLL_"+direction+"_"+dimension, target, dict(axis=dimension), ["SCROLL_CAPABILITY"], "AVAILABLE",
                        dict(capability_source=cap.get("source"), axis_source=container.get("axis_source"),
                             axis_contract=cap["axis_contract"], requested_direction=field,
                             supporting_signals=sorted(signals), action_executed=False), "READ_ONLY")

    # Identical producer duplicates are merged deterministically. Conflicting
    # action records are never silently collapsed by a last-write-wins rule.
    by_id: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=canonical_json):
        prior = by_id.get(row["candidate_id"])
        if prior is not None and _behavior(prior) != _behavior(row):
            raise ValueError("conflicting discovery action identity")
        if prior is None: by_id[row["candidate_id"]] = row
        else: prior["source"] = sorted(set(prior["source"] + row["source"]))
    candidates = tuple(DiscoveryActionCandidate(r["candidate_id"],sid,r["action_kind"],canonical_json(r)) for r in sorted(by_id.values(),key=lambda r:r["candidate_id"]))
    set_hash = canonical_sha256([_behavior(c.to_dict()) for c in candidates])
    fp = observation.fingerprint.to_dict()
    document = dict(schema_version=SNAPSHOT_SCHEMA, state_id=sid, binding_status="RESOLVED" if sid else "UNRESOLVED",
        state_resolution=dict(status=resolution.status,reasons=list(resolution.reasons),candidate_state_ids=list(resolution.candidate_state_ids)),
        registry_event_sequence=registry_event, fingerprint_hash=observation.fingerprint.fingerprint_hash,
        observation_id=observation.observation_id, observation_status=observation.coverage,
        timestamp=fp["transient"].get("timestamp"), scenario_context=dict(scenario_id=fp["transient"].get("scenario_id"),observed=core["navigation_context"]),
        viewport_signature=observation.fingerprint.viewport_signature, candidate_count=len(candidates),
        candidate_set_hash=set_hash,candidates=[c.to_dict() for c in candidates],
        sources=sorted({s for c in candidates for s in c.to_dict()["source"]}),
        strict_current_focus=dict(confirmed=focus_id is not None,instance_id=focus_id,physical_visit_credited=False),
        excluded=sorted(excluded,key=canonical_json), candidate_id_collision_count=collisions,
        safety_contract="HINT_ONLY_NO_AUTO_ACTIVATION",action_executed=False,visit_credit=0)
    semantic_substates = observation.semantic_substates
    if semantic_substates:
        # Candidate identity is bound to the logical root. The exact current
        # candidate set and camera semantic evidence remain in this snapshot.
        document["semantic_substates"] = semantic_substates
        document["semantic_substate_hash"] = canonical_sha256(semantic_substates)
    return DiscoverySnapshot(sid,set_hash,candidates,canonical_json(document))


def build_discovery_snapshot(raw: Mapping[str, Any], registry: StateRegistry, *,
                             continuity: VerifiedScrollEvidence | None = None,
                             audit_inventory: list | None = None, lifecycle_records: list | None = None) -> DiscoverySnapshot:
    """Resolve THIS observation; callers cannot inject a foreign state_id.

    Optional Audit/Lifecycle output is read-only. Only fresh target matches are
    admitted; historical unseen is not a claim of present action availability.
    """
    if not isinstance(raw, Mapping) or not isinstance(registry,StateRegistry):
        raise TypeError("discovery requires raw observation and diagnostic StateRegistry")
    for values in (audit_inventory,lifecycle_records):
        if values is not None and (not isinstance(values,list) or any(not isinstance(v,dict) for v in values)):
            raise ValueError("invalid discovery producer output")
    observation = build_state_observation(raw)
    resolution = registry.observe(observation,continuity)
    inventory = collect_audit_inventory(raw) if audit_inventory is None else audit_inventory
    return _collect(raw,observation,resolution,registry.observation_count,inventory,lifecycle_records or [])


def build_fingerprint_only_snapshot(fingerprint: Mapping[str, Any], registry: StateRegistry) -> DiscoverySnapshot:
    from tb_runner.state_replay import _fingerprint_only
    observation = _fingerprint_only(fingerprint)
    resolution = registry.observe(observation)
    assert resolution.state_id is None
    return _collect({},observation,resolution,registry.observation_count,[],[])


def candidate_set_delta(before: DiscoverySnapshot, after: DiscoverySnapshot) -> dict[str, Any]:
    left={c.candidate_id:_behavior(c.to_dict()) for c in before.candidates}
    right={c.candidate_id:_behavior(c.to_dict()) for c in after.candidates}
    comparable = before.state_id is not None and before.state_id == after.state_id
    changed = sorted(k for k in left.keys() & right.keys() if left[k] != right[k])
    return dict(comparable=comparable,CANDIDATE_SET_STABLE=comparable and before.candidate_set_hash==after.candidate_set_hash,
                NEW_CANDIDATE=len(right.keys()-left.keys()),REMOVED_CANDIDATE=len(left.keys()-right.keys()),
                CHANGED_CANDIDATE=len(changed),new_ids=sorted(right.keys()-left.keys()),
                removed_ids=sorted(left.keys()-right.keys()),changed_ids=changed,
                reason="SAME_LOGICAL_STATE" if comparable else "UNRESOLVED_OR_DIFFERENT_STATE")


def write_discovery_snapshot(path: str | Path, snapshot: DiscoverySnapshot) -> None:
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("a",encoding="utf-8",newline="\n") as stream:
        stream.write(snapshot.to_json()+"\n")
