"""Canonical identity and target-relation analysis for evidence-only shadow use.

Raw observation schemas are accepted only by :func:`normalize_observation`.
Every comparator in this module accepts ``CanonicalObservation`` instances and
must not inspect camelCase, snake_case, or producer-specific raw payloads.
Nothing in this module is a production traversal decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence


IDENTITY_SHADOW_ENABLED_ENV = "TB_EVIDENCE_IDENTITY_SHADOW_ENABLED"
IDENTITY_NORMALIZATION_VERSION = "canonical-observation-v1"
IDENTITY_RULE_VERSION = "target-relation-v2"
REQUIRED_DELAYED_OFFSETS_MS = (100, 300, 1000)


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class FieldAvailability(_StringEnum):
    KNOWN = "KNOWN"
    UNAVAILABLE_AT_SOURCE = "UNAVAILABLE_AT_SOURCE"
    OMITTED_BY_TRANSPORT = "OMITTED_BY_TRANSPORT"
    PARSE_FAILED = "PARSE_FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FieldComparison(_StringEnum):
    EQUAL = "EQUAL"
    DIFFERENT = "DIFFERENT"
    LEFT_MISSING = "LEFT_MISSING"
    RIGHT_MISSING = "RIGHT_MISSING"
    BOTH_MISSING = "BOTH_MISSING"
    INCOMPARABLE_SCOPE = "INCOMPARABLE_SCOPE"


class TargetRelation(_StringEnum):
    EXACT_PHYSICAL_NODE = "EXACT_PHYSICAL_NODE"
    STRONG_PHYSICAL_LINK = "STRONG_PHYSICAL_LINK"
    WEAK_PHYSICAL_LINK = "WEAK_PHYSICAL_LINK"
    DIFFERENT_PHYSICAL_NODE = "DIFFERENT_PHYSICAL_NODE"
    SAME_SEMANTIC_OBJECT = "SAME_SEMANTIC_OBJECT"
    TARGET_ANCESTOR = "TARGET_ANCESTOR"
    TARGET_DESCENDANT = "TARGET_DESCENDANT"
    CONTAINER_PARENT = "CONTAINER_PARENT"
    CONTAINER_CHILD = "CONTAINER_CHILD"
    ALIAS_EQUIVALENT = "ALIAS_EQUIVALENT"
    ANNOUNCEMENT_EQUIVALENT = "ANNOUNCEMENT_EQUIVALENT"
    RELATED_BOUNDS = "RELATED_BOUNDS"
    SAME_RESOURCE_DIFFERENT_INSTANCE = "SAME_RESOURCE_DIFFERENT_INSTANCE"
    SAME_LABEL_DIFFERENT_LOCATION = "SAME_LABEL_DIFFERENT_LOCATION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class TemporalRelation(_StringEnum):
    STABLE_LANDING = "STABLE_LANDING"
    TRANSIENT_LANDING = "TRANSIENT_LANDING"
    SNAP_BACK = "SNAP_BACK"
    DELAYED_COMMIT = "DELAYED_COMMIT"
    INTERMEDIATE_CONTAINER = "INTERMEDIATE_CONTAINER"
    NODE_REPLACEMENT = "NODE_REPLACEMENT"
    ANNOUNCEMENT_ONLY_MOVEMENT = "ANNOUNCEMENT_ONLY_MOVEMENT"
    UNSTABLE = "UNSTABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


def identity_shadow_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env or os.environ
    truthy = {"1", "true", "yes", "on"}
    return (
        source.get(IDENTITY_SHADOW_ENABLED_ENV, "").strip().lower() in truthy
        or source.get("TB_TRAVERSAL_IDENTITY_V2_ENABLED", "").strip().lower() in truthy
    )


@dataclass(frozen=True)
class CanonicalObservation:
    canonical_observation_id: str
    source_observation_id: str
    source_type: str
    producer: str
    run_id: str
    scenario_tx_id: str
    transaction_id: str
    capture_time: str
    runner_receive_time: str
    producer_sequence: int | None
    snapshot_id: str
    surface_id: str
    surface_revision: int | None
    package_name: str | None
    window_id: str | None
    display_id: str | None
    class_name: str | None
    resource_id: str | None
    resource_id_short: str | None
    bounds_screen: tuple[int, int, int, int] | None
    bounds_normalized: tuple[int, int, int, int] | None
    coordinate_space: str | None
    text_normalized: str | None
    content_description_normalized: str | None
    talkback_label_normalized: str | None
    node_path: str | None
    parent_path: str | None
    child_index: int | None
    accessibility_node_id: str | None
    semantic_role: str | None
    clickable: bool | None
    focusable: bool | None
    accessibility_focused: bool | None
    selected: bool | None
    enabled: bool | None
    capture_source: str
    capture_status: str
    field_availability: Mapping[str, FieldAvailability] = field(default_factory=dict)
    normalization_version: str = IDENTITY_NORMALIZATION_VERSION

    @property
    def semantic_label(self) -> str | None:
        return self.talkback_label_normalized or self.content_description_normalized or self.text_normalized

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["field_availability"] = {key: str(state) for key, state in self.field_availability.items()}
        return value


class ObservationAdapter(Protocol):
    """Producer adapter contract.  Adapters must return canonical observations."""

    def normalize(
        self,
        raw: Mapping[str, Any] | None,
        *,
        source_type: str,
        envelope: Mapping[str, Any] | None = None,
    ) -> CanonicalObservation:
        ...


@dataclass(frozen=True)
class ComparatorPolicy:
    purpose: str = "shadow_focus"
    bounds_tolerance_px: int = 0
    min_strong_signals: int = 3
    min_weak_signals: int = 2
    allow_semantic_target_compatibility: bool = True
    allow_hierarchy_target_compatibility: bool = True
    allows_direct_visit_credit: bool = False
    rule_version: str = IDENTITY_RULE_VERSION


@dataclass(frozen=True)
class IdentityAssertion:
    assertion_id: str
    source_observation_id: str
    target_observation_id: str
    relation: TargetRelation
    evidence_event_ids: tuple[str, ...] = ()
    confidence: str = "INDETERMINATE"
    surface_id: str = ""
    window_id: str = ""
    valid_from: str = ""
    valid_until: str = ""
    producer: str = "shadow"
    rule_version: str = IDENTITY_RULE_VERSION
    allows_direct_visit_credit: bool = False


@dataclass(frozen=True)
class PhysicalIdentityResult:
    relation: TargetRelation
    confidence: str
    field_comparisons: Mapping[str, FieldComparison]
    supporting_fields: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    rule_version: str = IDENTITY_RULE_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["relation"] = str(self.relation)
        value["field_comparisons"] = {key: str(state) for key, state in self.field_comparisons.items()}
        return value


@dataclass(frozen=True)
class SemanticIdentityResult:
    relation: TargetRelation
    confidence: str
    supporting_fields: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    allows_direct_visit_credit: bool = False
    rule_version: str = IDENTITY_RULE_VERSION


@dataclass(frozen=True)
class HierarchyRelationResult:
    relation: TargetRelation
    container_relation: TargetRelation = TargetRelation.INSUFFICIENT_EVIDENCE
    confidence: str = "INDETERMINATE"
    supporting_fields: tuple[str, ...] = ()
    assertion_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    allows_direct_visit_credit: bool = False
    rule_version: str = IDENTITY_RULE_VERSION


@dataclass(frozen=True)
class TemporalStabilityResult:
    relation: TemporalRelation
    confidence: str
    observation_ids: tuple[str, ...] = ()
    supporting_relations: tuple[str, ...] = ()
    missing_samples: tuple[str, ...] = ()
    rule_version: str = IDENTITY_RULE_VERSION


@dataclass(frozen=True)
class TargetRelationResult:
    physical_relation: TargetRelation
    hierarchy_relation: TargetRelation
    semantic_relation: TargetRelation
    temporal_relation: TemporalRelation
    aggregate_relation: TargetRelation
    confidence: str
    supporting_fields: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    rule_version: str = IDENTITY_RULE_VERSION
    allows_move_confirmation: bool = False
    allows_direct_visit_credit: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("physical_relation", "hierarchy_relation", "semantic_relation", "temporal_relation", "aggregate_relation"):
            value[key] = str(value[key])
        return value


def _known(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _first(raw: Mapping[str, Any], aliases: Sequence[str]) -> tuple[Any, str | None, bool]:
    for key in aliases:
        if key in raw:
            value = raw.get(key)
            return value, key, _known(value)
    return None, None, False


def _text(value: Any) -> str | None:
    if not _known(value):
        return None
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = " ".join(normalized.strip().lower().split())
    return normalized or None


def _identifier(value: Any) -> str | None:
    if not _known(value):
        return None
    result = str(value).strip()
    return result or None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bounds(value: Any) -> tuple[int, int, int, int] | None:
    if isinstance(value, Mapping):
        keys = ("l", "t", "r", "b") if any(key in value for key in ("l", "t", "r", "b")) else ("left", "top", "right", "bottom")
        parsed = tuple(_integer(value.get(key)) for key in keys)
        return parsed if all(item is not None for item in parsed) else None  # type: ignore[return-value]
    if _known(value):
        numbers = [int(item) for item in re.findall(r"-?\d+", str(value))]
        if len(numbers) >= 4:
            return tuple(numbers[:4])  # type: ignore[return-value]
    return None


def _availability(raw: Mapping[str, Any], aliases: Sequence[str], value: Any, *, parse_failed: bool = False) -> FieldAvailability:
    present = any(key in raw for key in aliases)
    if parse_failed:
        return FieldAvailability.PARSE_FAILED
    if _known(value):
        return FieldAvailability.KNOWN
    if raw.get("transportTruncated") is True:
        return FieldAvailability.OMITTED_BY_TRANSPORT
    return FieldAvailability.UNAVAILABLE_AT_SOURCE if present else FieldAvailability.UNAVAILABLE_AT_SOURCE


def _resource_short(value: str | None) -> str | None:
    if not value:
        return None
    result = value.rsplit("/", 1)[-1]
    return result.rsplit(":id/", 1)[-1] or None


def _envelope_mapping(envelope: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return envelope if isinstance(envelope, Mapping) else {}


def normalize_observation(
    raw: Mapping[str, Any] | None,
    *,
    source_type: str,
    envelope: Mapping[str, Any] | None = None,
) -> CanonicalObservation:
    """Convert one producer observation into the only comparator input type."""

    source = dict(raw or {})
    env = _envelope_mapping(envelope)

    aliases: dict[str, tuple[str, ...]] = {
        "source_observation_id": ("canonical_observation_id", "observation_id", "observationId", "source_observation_id"),
        "package_name": ("package_name", "packageName", "package"),
        "window_id": ("window_id", "windowId", "window"),
        "display_id": ("display_id", "displayId"),
        "class_name": ("class_name", "className", "class"),
        "resource_id": ("resource_id", "viewIdResourceName", "resourceId", "view_id", "resource-id"),
        "bounds": ("bounds_screen", "boundsInScreen", "bounds"),
        "text": ("text_normalized", "normalized_text", "text"),
        "content_description": ("content_description_normalized", "normalized_content_description", "contentDescription", "content_description", "content-desc"),
        "talkback_label": ("talkback_label_normalized", "normalized_talkback_label", "talkbackLabel", "talkback_label", "mergedLabel", "label"),
        "node_path": ("node_path", "nodePath"),
        "parent_path": ("parent_path", "parentPath"),
        "child_index": ("child_index", "childIndex", "index"),
        "accessibility_node_id": ("accessibility_node_id", "accessibilityNodeId", "source_node_id", "sourceNodeId"),
        "semantic_role": ("semantic_role", "semanticRole", "role"),
        "coordinate_space": ("coordinate_space", "coordinateSpace"),
        "capture_time": ("capture_time", "captured_at", "capturedAt", "timestamp"),
        "capture_source": ("capture_source", "captureSource", "source"),
        "capture_status": ("capture_status", "captureStatus"),
        "snapshot_id": ("snapshot_id", "snapshotId"),
        "surface_id": ("surface_id", "surfaceId"),
        "surface_revision": ("surface_revision", "surfaceRevision"),
    }

    values = {name: _first(source, names)[0] for name, names in aliases.items()}
    parsed_bounds = _bounds(values["bounds"])
    bounds_parse_failed = _known(values["bounds"]) and parsed_bounds is None

    package_name = _identifier(values["package_name"])
    window_id = _identifier(values["window_id"])
    display_id = _identifier(values["display_id"])
    class_name = _identifier(values["class_name"])
    resource_id = _identifier(values["resource_id"])
    node_path = _identifier(values["node_path"])
    parent_path = _identifier(values["parent_path"])
    accessibility_node_id = _identifier(values["accessibility_node_id"])
    semantic_role = _identifier(values["semantic_role"])
    coordinate_space = _identifier(values["coordinate_space"]) or "screen"

    field_availability = {
        "package_name": _availability(source, aliases["package_name"], package_name),
        "window_id": _availability(source, aliases["window_id"], window_id),
        "display_id": _availability(source, aliases["display_id"], display_id),
        "class_name": _availability(source, aliases["class_name"], class_name),
        "resource_id": _availability(source, aliases["resource_id"], resource_id),
        "bounds_screen": _availability(source, aliases["bounds"], parsed_bounds, parse_failed=bounds_parse_failed),
        "node_path": _availability(source, aliases["node_path"], node_path),
        "parent_path": _availability(source, aliases["parent_path"], parent_path),
        "accessibility_node_id": _availability(source, aliases["accessibility_node_id"], accessibility_node_id),
    }

    run_id = _identifier(source.get("run_id")) or _identifier(env.get("run_id")) or ""
    scenario_tx_id = _identifier(source.get("scenario_tx_id")) or _identifier(env.get("scenario_tx_id")) or ""
    transaction_id = _identifier(source.get("transaction_id")) or _identifier(env.get("transaction_id")) or ""
    snapshot_id = _identifier(values["snapshot_id"]) or _identifier(env.get("snapshot_id")) or ""
    surface_id = _identifier(values["surface_id"]) or _identifier(env.get("surface_id")) or ""
    surface_revision = _integer(values["surface_revision"] if values["surface_revision"] is not None else env.get("surface_revision"))
    source_observation_id = _identifier(values["source_observation_id"]) or ""
    capture_time = _identifier(values["capture_time"]) or _identifier(env.get("wall_time_utc")) or ""
    producer = _identifier(env.get("producer")) or _identifier(source.get("producer")) or ""
    producer_sequence = _integer(env.get("producer_sequence"))
    runner_receive_time = _identifier(env.get("runner_received_wall_time_utc")) or ""
    capture_source = _identifier(values["capture_source"]) or source_type
    capture_status = _identifier(values["capture_status"]) or "captured"

    identity_material = {
        "version": IDENTITY_NORMALIZATION_VERSION,
        "source_type": source_type,
        "source_observation_id": source_observation_id,
        "event_id": _identifier(env.get("event_id")) or "",
        "run_id": run_id,
        "transaction_id": transaction_id,
        "snapshot_id": snapshot_id,
        "surface_id": surface_id,
        "surface_revision": surface_revision,
        "capture_time": capture_time,
        "package_name": package_name,
        "window_id": window_id,
        "class_name": class_name,
        "resource_id": resource_id,
        "node_path": node_path,
        "bounds": parsed_bounds,
    }
    digest = hashlib.sha256(
        json.dumps(identity_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]

    return CanonicalObservation(
        canonical_observation_id=f"coid:v1:{digest}",
        source_observation_id=source_observation_id,
        source_type=source_type,
        producer=producer,
        run_id=run_id,
        scenario_tx_id=scenario_tx_id,
        transaction_id=transaction_id,
        capture_time=capture_time,
        runner_receive_time=runner_receive_time,
        producer_sequence=producer_sequence,
        snapshot_id=snapshot_id,
        surface_id=surface_id,
        surface_revision=surface_revision,
        package_name=package_name,
        window_id=window_id,
        display_id=display_id,
        class_name=class_name,
        resource_id=resource_id,
        resource_id_short=_resource_short(resource_id),
        bounds_screen=parsed_bounds,
        bounds_normalized=parsed_bounds,
        coordinate_space=coordinate_space,
        text_normalized=_text(values["text"]),
        content_description_normalized=_text(values["content_description"]),
        talkback_label_normalized=_text(values["talkback_label"]),
        node_path=node_path,
        parent_path=parent_path,
        child_index=_integer(values["child_index"]),
        accessibility_node_id=accessibility_node_id,
        semantic_role=semantic_role,
        clickable=_boolean(source.get("clickable")),
        focusable=_boolean(source.get("focusable")),
        accessibility_focused=_boolean(source.get("accessibilityFocused", source.get("accessibility_focused"))),
        selected=_boolean(source.get("selected")),
        enabled=_boolean(source.get("enabled")),
        capture_source=capture_source,
        capture_status=capture_status,
        field_availability=field_availability,
    )


def _field_compare(left: Any, right: Any) -> FieldComparison:
    left_known = _known(left)
    right_known = _known(right)
    if not left_known and not right_known:
        return FieldComparison.BOTH_MISSING
    if not left_known:
        return FieldComparison.LEFT_MISSING
    if not right_known:
        return FieldComparison.RIGHT_MISSING
    return FieldComparison.EQUAL if left == right else FieldComparison.DIFFERENT


def _bounds_compatible(left: CanonicalObservation, right: CanonicalObservation, tolerance: int) -> FieldComparison:
    comparison = _field_compare(left.bounds_normalized, right.bounds_normalized)
    if comparison not in {FieldComparison.EQUAL, FieldComparison.DIFFERENT}:
        return comparison
    if left.coordinate_space and right.coordinate_space and left.coordinate_space != right.coordinate_space:
        return FieldComparison.INCOMPARABLE_SCOPE
    if left.display_id and right.display_id and left.display_id != right.display_id:
        return FieldComparison.INCOMPARABLE_SCOPE
    if comparison == FieldComparison.EQUAL:
        return comparison
    assert left.bounds_normalized is not None and right.bounds_normalized is not None
    return (
        FieldComparison.EQUAL
        if all(abs(a - b) <= max(0, tolerance) for a, b in zip(left.bounds_normalized, right.bounds_normalized))
        else FieldComparison.DIFFERENT
    )


def compare_physical(
    left: CanonicalObservation,
    right: CanonicalObservation,
    policy: ComparatorPolicy | None = None,
) -> PhysicalIdentityResult:
    policy = policy or ComparatorPolicy()
    comparisons: dict[str, FieldComparison] = {
        "package_name": _field_compare(left.package_name, right.package_name),
        "window_id": _field_compare(left.window_id, right.window_id),
        "display_id": _field_compare(left.display_id, right.display_id),
        "class_name": _field_compare(left.class_name, right.class_name),
        "resource_id": _field_compare(left.resource_id, right.resource_id),
        "bounds": _bounds_compatible(left, right, policy.bounds_tolerance_px),
        "node_path": _field_compare(left.node_path, right.node_path),
        "parent_path": _field_compare(left.parent_path, right.parent_path),
        "accessibility_node_id": _field_compare(left.accessibility_node_id, right.accessibility_node_id),
        "semantic_label": _field_compare(left.semantic_label, right.semantic_label),
    }
    if left.run_id and right.run_id and left.run_id != right.run_id:
        comparisons["run_scope"] = FieldComparison.INCOMPARABLE_SCOPE

    missing = tuple(
        name
        for name, state in comparisons.items()
        if state in {FieldComparison.LEFT_MISSING, FieldComparison.RIGHT_MISSING, FieldComparison.BOTH_MISSING}
    )
    equal = tuple(name for name, state in comparisons.items() if state == FieldComparison.EQUAL)
    different = tuple(name for name, state in comparisons.items() if state == FieldComparison.DIFFERENT)
    incomparable = tuple(name for name, state in comparisons.items() if state == FieldComparison.INCOMPARABLE_SCOPE)
    evidence_ids = (left.canonical_observation_id, right.canonical_observation_id)

    same_observation = left is right or bool(
        left.source_observation_id
        and left.source_observation_id == right.source_observation_id
        and left.run_id == right.run_id
    )
    if same_observation:
        return PhysicalIdentityResult(
            TargetRelation.EXACT_PHYSICAL_NODE,
            "CONFIRMED",
            comparisons,
            equal,
            (),
            missing,
            evidence_ids,
            policy.rule_version,
        )

    strong_scope_conflict = any(comparisons[name] == FieldComparison.DIFFERENT for name in ("package_name", "window_id"))
    node_id_conflict = (
        comparisons["accessibility_node_id"] == FieldComparison.DIFFERENT
        and comparisons["window_id"] == FieldComparison.EQUAL
    )
    structural_conflicts = {name for name in different if name in {"class_name", "resource_id", "bounds", "node_path"}}
    label_and_geometry_conflict = (
        comparisons["bounds"] == FieldComparison.DIFFERENT
        and comparisons["semantic_label"] == FieldComparison.DIFFERENT
    )
    multi_structural_conflict = len(structural_conflicts) >= 2

    if incomparable:
        return PhysicalIdentityResult(
            TargetRelation.INSUFFICIENT_EVIDENCE,
            "INDETERMINATE",
            comparisons,
            equal,
            incomparable,
            missing,
            evidence_ids,
            policy.rule_version,
        )
    if strong_scope_conflict or node_id_conflict or multi_structural_conflict or label_and_geometry_conflict:
        contradictions = tuple(sorted(set(different) | ({"accessibility_node_id"} if node_id_conflict else set())))
        return PhysicalIdentityResult(
            TargetRelation.DIFFERENT_PHYSICAL_NODE,
            "HIGH_CONFIDENCE" if not strong_scope_conflict else "CONFIRMED",
            comparisons,
            equal,
            contradictions,
            missing,
            evidence_ids,
            policy.rule_version,
        )

    node_id_equal = comparisons["accessibility_node_id"] == FieldComparison.EQUAL
    compatible_scope = comparisons["package_name"] == FieldComparison.EQUAL and comparisons["window_id"] in {
        FieldComparison.EQUAL,
        FieldComparison.LEFT_MISSING,
        FieldComparison.RIGHT_MISSING,
        FieldComparison.BOTH_MISSING,
    }
    if node_id_equal and compatible_scope:
        return PhysicalIdentityResult(
            TargetRelation.EXACT_PHYSICAL_NODE,
            "CONFIRMED",
            comparisons,
            equal,
            different,
            missing,
            evidence_ids,
            policy.rule_version,
        )

    identity_signals = {
        name
        for name in ("package_name", "window_id", "class_name", "resource_id", "bounds", "node_path", "parent_path")
        if comparisons[name] == FieldComparison.EQUAL
    }
    if len(identity_signals) >= policy.min_strong_signals and comparisons["package_name"] == FieldComparison.EQUAL:
        return PhysicalIdentityResult(
            TargetRelation.STRONG_PHYSICAL_LINK,
            "HIGH_CONFIDENCE",
            comparisons,
            tuple(sorted(identity_signals)),
            different,
            missing,
            evidence_ids,
            policy.rule_version,
        )
    if len(identity_signals) >= policy.min_weak_signals:
        return PhysicalIdentityResult(
            TargetRelation.WEAK_PHYSICAL_LINK,
            "PLAUSIBLE",
            comparisons,
            tuple(sorted(identity_signals)),
            different,
            missing,
            evidence_ids,
            policy.rule_version,
        )
    return PhysicalIdentityResult(
        TargetRelation.INSUFFICIENT_EVIDENCE,
        "INDETERMINATE",
        comparisons,
        equal,
        different,
        missing,
        evidence_ids,
        policy.rule_version,
    )


def _bounds_relation(left: tuple[int, int, int, int] | None, right: tuple[int, int, int, int] | None) -> str:
    if left is None or right is None:
        return "missing"
    if left == right:
        return "equal"
    ll, lt, lr, lb = left
    rl, rt, rr, rb = right
    if ll <= rl and lt <= rt and lr >= rr and lb >= rb:
        return "contains"
    if rl <= ll and rt <= lt and rr >= lr and rb >= lb:
        return "contained_by"
    if max(ll, rl) < min(lr, rr) and max(lt, rt) < min(lb, rb):
        return "overlaps"
    return "different"


def compare_semantic(
    left: CanonicalObservation,
    right: CanonicalObservation,
    context: Mapping[str, Any] | None = None,
) -> SemanticIdentityResult:
    context = context or {}
    evidence_ids = (left.canonical_observation_id, right.canonical_observation_id)
    resource = _field_compare(left.resource_id, right.resource_id)
    label = _field_compare(left.semantic_label, right.semantic_label)
    role = _field_compare(left.semantic_role, right.semantic_role)
    bounds_relation = _bounds_relation(left.bounds_normalized, right.bounds_normalized)
    missing = tuple(
        name
        for name, state in {"resource_id": resource, "semantic_label": label, "semantic_role": role}.items()
        if state in {FieldComparison.LEFT_MISSING, FieldComparison.RIGHT_MISSING, FieldComparison.BOTH_MISSING}
    )

    if resource == FieldComparison.EQUAL and bounds_relation == "different":
        return SemanticIdentityResult(
            TargetRelation.SAME_RESOURCE_DIFFERENT_INSTANCE,
            "HIGH_CONFIDENCE",
            ("resource_id",),
            ("bounds",),
            missing,
            evidence_ids,
        )
    if label == FieldComparison.EQUAL and bounds_relation == "different":
        return SemanticIdentityResult(
            TargetRelation.SAME_LABEL_DIFFERENT_LOCATION,
            "HIGH_CONFIDENCE",
            ("semantic_label",),
            ("bounds",),
            missing,
            evidence_ids,
        )
    if label == FieldComparison.EQUAL and bounds_relation == "equal" and role != FieldComparison.DIFFERENT:
        support = ("semantic_label", "bounds") + (("semantic_role",) if role == FieldComparison.EQUAL else ())
        return SemanticIdentityResult(
            TargetRelation.SAME_SEMANTIC_OBJECT,
            "HIGH_CONFIDENCE",
            support,
            (),
            missing,
            evidence_ids,
        )
    announcement = _text(context.get("announcement"))
    target_label = left.semantic_label
    if announcement and target_label:
        target_tokens = set(target_label.split())
        announcement_tokens = set(announcement.split())
        if target_tokens and target_tokens.issubset(announcement_tokens):
            return SemanticIdentityResult(
                TargetRelation.ANNOUNCEMENT_EQUIVALENT,
                "PLAUSIBLE",
                ("announcement", "semantic_label"),
                (),
                missing,
                evidence_ids,
            )
    if bounds_relation in {"contains", "contained_by", "overlaps"}:
        return SemanticIdentityResult(
            TargetRelation.RELATED_BOUNDS,
            "PLAUSIBLE",
            (f"bounds:{bounds_relation}",),
            (),
            missing,
            evidence_ids,
        )
    return SemanticIdentityResult(
        TargetRelation.INSUFFICIENT_EVIDENCE,
        "INDETERMINATE",
        (),
        tuple(name for name, state in (("resource_id", resource), ("semantic_label", label), ("semantic_role", role)) if state == FieldComparison.DIFFERENT),
        missing,
        evidence_ids,
    )


def _path_parts(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part for part in re.split(r"[/>.]+", value.strip(" />.")) if part)


def _is_prefix(parent: tuple[str, ...], child: tuple[str, ...]) -> bool:
    return bool(parent) and len(parent) < len(child) and child[: len(parent)] == parent


def evaluate_hierarchy(
    target: CanonicalObservation,
    landing: CanonicalObservation,
    assertions: Sequence[IdentityAssertion] = (),
) -> HierarchyRelationResult:
    evidence_ids = (target.canonical_observation_id, landing.canonical_observation_id)
    for assertion in assertions:
        if {
            assertion.source_observation_id,
            assertion.target_observation_id,
        } == {target.canonical_observation_id, landing.canonical_observation_id}:
            return HierarchyRelationResult(
                assertion.relation,
                confidence=assertion.confidence,
                supporting_fields=("identity_assertion",),
                assertion_ids=(assertion.assertion_id,),
                evidence_ids=evidence_ids,
                allows_direct_visit_credit=assertion.allows_direct_visit_credit,
                rule_version=assertion.rule_version,
            )

    target_path = _path_parts(target.node_path)
    landing_path = _path_parts(landing.node_path)
    if _is_prefix(landing_path, target_path):
        return HierarchyRelationResult(
            TargetRelation.TARGET_ANCESTOR,
            TargetRelation.CONTAINER_PARENT,
            "HIGH_CONFIDENCE",
            ("node_path",),
            evidence_ids=evidence_ids,
        )
    if _is_prefix(target_path, landing_path):
        return HierarchyRelationResult(
            TargetRelation.TARGET_DESCENDANT,
            TargetRelation.CONTAINER_CHILD,
            "HIGH_CONFIDENCE",
            ("node_path",),
            evidence_ids=evidence_ids,
        )
    if landing.node_path and target.parent_path and landing.node_path == target.parent_path:
        return HierarchyRelationResult(
            TargetRelation.TARGET_ANCESTOR,
            TargetRelation.CONTAINER_PARENT,
            "HIGH_CONFIDENCE",
            ("parent_path",),
            evidence_ids=evidence_ids,
        )
    if target.node_path and landing.parent_path and target.node_path == landing.parent_path:
        return HierarchyRelationResult(
            TargetRelation.TARGET_DESCENDANT,
            TargetRelation.CONTAINER_CHILD,
            "HIGH_CONFIDENCE",
            ("parent_path",),
            evidence_ids=evidence_ids,
        )
    return HierarchyRelationResult(
        TargetRelation.INSUFFICIENT_EVIDENCE,
        confidence="INDETERMINATE",
        evidence_ids=evidence_ids,
    )


def _same_link(result: PhysicalIdentityResult) -> bool:
    if result.relation == TargetRelation.EXACT_PHYSICAL_NODE:
        return True
    physical_contradictions = {
        "package_name",
        "window_id",
        "display_id",
        "class_name",
        "resource_id",
        "bounds",
        "node_path",
        "parent_path",
        "accessibility_node_id",
    }
    return (
        result.relation == TargetRelation.STRONG_PHYSICAL_LINK
        and not physical_contradictions.intersection(result.contradictions)
    )


def evaluate_stability(
    pre: CanonicalObservation | None,
    immediate: CanonicalObservation | None,
    delayed: Sequence[CanonicalObservation],
    events: Sequence[Any] = (),
    *,
    resolved: CanonicalObservation | None = None,
    delayed_offsets_ms: Sequence[int] | None = None,
    policy: ComparatorPolicy | None = None,
) -> TemporalStabilityResult:
    del events  # reserved for future event-stream attribution; observations remain authoritative here
    policy = policy or ComparatorPolicy(purpose="shadow_stability")
    ordered = list(delayed)
    observation_ids = tuple(
        item.canonical_observation_id for item in (pre, immediate, resolved, *ordered) if item is not None
    )
    missing: list[str] = []
    if immediate is None:
        missing.append("immediate")
    if not ordered:
        missing.append("delayed")
    if delayed_offsets_ms is None:
        delayed_window_complete = len(ordered) >= len(REQUIRED_DELAYED_OFFSETS_MS)
        if not delayed_window_complete:
            missing.append("delayed_window")
    else:
        observed_offsets = {int(offset) for offset in delayed_offsets_ms}
        missing_offsets = [offset for offset in REQUIRED_DELAYED_OFFSETS_MS if offset not in observed_offsets]
        delayed_window_complete = not missing_offsets
        missing.extend(f"delayed_{offset}ms" for offset in missing_offsets)

    anchor = immediate or resolved or (ordered[0] if ordered else None)
    if anchor is None or not ordered:
        return TemporalStabilityResult(
            TemporalRelation.INSUFFICIENT_EVIDENCE,
            "INDETERMINATE",
            observation_ids,
            (),
            tuple(missing),
            policy.rule_version,
        )

    delayed_links = [compare_physical(anchor, sample, policy) for sample in ordered]
    all_delayed_same = all(_same_link(result) for result in delayed_links)
    pre_to_anchor = compare_physical(pre, anchor, policy) if pre is not None else None
    final_to_pre = compare_physical(pre, ordered[-1], policy) if pre is not None else None

    # A resolved target is an action-plan fact, not proof that focus ever landed
    # there.  Snap-back therefore requires an observed immediate focus (A -> B
    # -> A), even though resolved may still anchor a delayed-only stable series.
    if (
        immediate is not None
        and pre_to_anchor
        and pre_to_anchor.relation == TargetRelation.DIFFERENT_PHYSICAL_NODE
        and final_to_pre
        and _same_link(final_to_pre)
    ):
        return TemporalStabilityResult(
            TemporalRelation.SNAP_BACK,
            "HIGH_CONFIDENCE",
            observation_ids,
            (str(pre_to_anchor.relation), str(final_to_pre.relation)),
            tuple(missing),
            policy.rule_version,
        )
    if not delayed_window_complete:
        return TemporalStabilityResult(
            TemporalRelation.INSUFFICIENT_EVIDENCE,
            "INDETERMINATE",
            observation_ids,
            tuple(str(result.relation) for result in delayed_links),
            tuple(missing),
            policy.rule_version,
        )
    if pre_to_anchor and _same_link(pre_to_anchor) and final_to_pre and final_to_pre.relation == TargetRelation.DIFFERENT_PHYSICAL_NODE:
        final_links = [compare_physical(ordered[-1], sample, policy) for sample in ordered[-2:]]
        if all(_same_link(result) for result in final_links):
            return TemporalStabilityResult(
                TemporalRelation.DELAYED_COMMIT,
                "HIGH_CONFIDENCE",
                observation_ids,
                tuple(str(result.relation) for result in final_links),
                tuple(missing),
                policy.rule_version,
            )
    if all_delayed_same:
        return TemporalStabilityResult(
            TemporalRelation.STABLE_LANDING,
            "HIGH_CONFIDENCE",
            observation_ids,
            tuple(str(result.relation) for result in delayed_links),
            tuple(missing),
            policy.rule_version,
        )
    return TemporalStabilityResult(
        TemporalRelation.UNSTABLE,
        "HIGH_CONFIDENCE",
        observation_ids,
        tuple(str(result.relation) for result in delayed_links),
        tuple(missing),
        policy.rule_version,
    )


def evaluate_target_relation(
    requested: CanonicalObservation | None,
    resolved: CanonicalObservation | None,
    landing: CanonicalObservation | None,
    context: Mapping[str, Any] | None = None,
    *,
    policy: ComparatorPolicy | None = None,
    assertions: Sequence[IdentityAssertion] = (),
    temporal_relation: TemporalRelation = TemporalRelation.INSUFFICIENT_EVIDENCE,
) -> TargetRelationResult:
    policy = policy or ComparatorPolicy(purpose="shadow_target")
    context = context or {}
    target = resolved or requested
    if target is None or landing is None:
        missing = tuple(name for name, value in (("target", target), ("landing", landing)) if value is None)
        return TargetRelationResult(
            TargetRelation.INSUFFICIENT_EVIDENCE,
            TargetRelation.INSUFFICIENT_EVIDENCE,
            TargetRelation.INSUFFICIENT_EVIDENCE,
            temporal_relation,
            TargetRelation.INSUFFICIENT_EVIDENCE,
            "INDETERMINATE",
            missing_fields=missing,
            rule_version=policy.rule_version,
        )

    physical = compare_physical(target, landing, policy)
    hierarchy = evaluate_hierarchy(target, landing, assertions)
    semantic = compare_semantic(target, landing, context)

    aggregate = TargetRelation.INSUFFICIENT_EVIDENCE
    confidence = "INDETERMINATE"
    allows_move = False
    scope_contradiction = bool(
        {"package_name", "window_id"}.intersection(physical.contradictions)
    )
    if physical.relation in {TargetRelation.EXACT_PHYSICAL_NODE, TargetRelation.STRONG_PHYSICAL_LINK}:
        aggregate = physical.relation
        confidence = physical.confidence
        allows_move = True
    elif (
        hierarchy.relation != TargetRelation.INSUFFICIENT_EVIDENCE
        and policy.allow_hierarchy_target_compatibility
        and not scope_contradiction
    ):
        aggregate = hierarchy.container_relation if hierarchy.container_relation != TargetRelation.INSUFFICIENT_EVIDENCE else hierarchy.relation
        confidence = hierarchy.confidence
        allows_move = True
    elif (
        semantic.relation == TargetRelation.SAME_SEMANTIC_OBJECT
        and policy.allow_semantic_target_compatibility
        and not scope_contradiction
    ):
        aggregate = semantic.relation
        confidence = semantic.confidence
        allows_move = True
    elif physical.relation == TargetRelation.DIFFERENT_PHYSICAL_NODE:
        # Positive physical contradiction must not be hidden by weak semantic
        # diagnostics such as a repeated resource-id or label.
        aggregate = physical.relation
        confidence = physical.confidence
    elif semantic.relation in {
        TargetRelation.ANNOUNCEMENT_EQUIVALENT,
        TargetRelation.SAME_RESOURCE_DIFFERENT_INSTANCE,
        TargetRelation.SAME_LABEL_DIFFERENT_LOCATION,
        TargetRelation.RELATED_BOUNDS,
    }:
        aggregate = semantic.relation
        confidence = semantic.confidence
    elif physical.relation == TargetRelation.WEAK_PHYSICAL_LINK:
        aggregate = physical.relation
        confidence = physical.confidence

    return TargetRelationResult(
        physical.relation,
        hierarchy.relation,
        semantic.relation,
        temporal_relation,
        aggregate,
        confidence,
        tuple(sorted(set(physical.supporting_fields + hierarchy.supporting_fields + semantic.supporting_fields))),
        tuple(sorted(set(physical.contradictions + semantic.contradictions))),
        tuple(sorted(set(physical.missing_fields + semantic.missing_fields))),
        tuple(sorted(set(physical.evidence_ids + hierarchy.evidence_ids + semantic.evidence_ids))),
        policy.rule_version,
        allows_move,
        False,
    )


def _event_dict(event: Any) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        return event
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        return value if isinstance(value, Mapping) else {}
    return {}


def _event_payload(event: Any) -> Mapping[str, Any]:
    value = _event_dict(event).get("payload")
    return value if isinstance(value, Mapping) else {}


def _event_type(event: Any) -> str:
    return str(_event_dict(event).get("event_type") or "")


def _minimum_confidence(*values: str) -> str:
    order = {
        "INDETERMINATE": 0,
        "SPECULATION": 1,
        "PLAUSIBLE": 2,
        "HIGH_CONFIDENCE": 3,
        "CONFIRMED": 4,
    }
    normalized = [str(value or "INDETERMINATE") for value in values]
    return min(normalized, key=lambda value: order.get(value, 0)) if normalized else "INDETERMINATE"


def reduce_shadow_v2(events: Sequence[Any]) -> dict[str, Any]:
    """Deterministically reduce one action transaction using canonical inputs only."""

    transaction_events = list(events)
    event_types = {_event_type(event) for event in transaction_events}
    normalization_cache: dict[tuple[str, str], CanonicalObservation] = {}

    def canonical(event: Any, role: str, raw: Mapping[str, Any] | None) -> CanonicalObservation | None:
        if not isinstance(raw, Mapping):
            return None
        envelope = _event_dict(event)
        key = (str(envelope.get("event_id") or id(event)), role)
        if key not in normalization_cache:
            normalization_cache[key] = normalize_observation(raw, source_type=role, envelope=envelope)
        return normalization_cache[key]

    def observations(event_type: str, payload_key: str = "observation") -> list[CanonicalObservation]:
        result: list[CanonicalObservation] = []
        for event in transaction_events:
            if _event_type(event) != event_type:
                continue
            raw = _event_payload(event).get(payload_key)
            value = canonical(event, f"{event_type.lower()}:{payload_key}", raw if isinstance(raw, Mapping) else None)
            if value is not None:
                result.append(value)
        return result

    pre_values = observations("PRE_FOCUS_OBSERVED")
    resolved_values = observations("TARGET_RESOLVED", "resolvedTarget")
    helper_post_values = observations("POST_ACTION_OBSERVATION")
    runner_post_values = observations("POST_FOCUS_OBSERVED")

    delayed_pairs: list[tuple[int, CanonicalObservation]] = []
    for event in transaction_events:
        if _event_type(event) != "DELAYED_OBSERVATION":
            continue
        payload = _event_payload(event)
        raw = payload.get("observation")
        value = canonical(event, "delayed_observation:observation", raw if isinstance(raw, Mapping) else None)
        if value is not None:
            delayed_pairs.append((_integer(payload.get("offsetMs")) or 0, value))
    delayed_pairs.sort(key=lambda item: item[0])
    delayed_offsets = [offset for offset, _ in delayed_pairs]
    delayed = [value for _, value in delayed_pairs]

    requested: CanonicalObservation | None = None
    for event in transaction_events:
        if _event_type(event) != "TARGET_REQUESTED":
            continue
        payload = _event_payload(event)
        for key in ("requestedTarget", "target", "observation"):
            raw = payload.get(key)
            requested = canonical(event, f"target_requested:{key}", raw if isinstance(raw, Mapping) else None)
            if requested is not None:
                break
        if requested is not None:
            break

    pre = pre_values[0] if pre_values else None
    resolved = resolved_values[0] if resolved_values else None
    immediate = helper_post_values[-1] if helper_post_values else (runner_post_values[-1] if runner_post_values else None)
    landing = immediate or (delayed[0] if delayed else None)

    stability = evaluate_stability(
        pre,
        immediate,
        delayed,
        transaction_events,
        resolved=resolved,
        delayed_offsets_ms=delayed_offsets,
    )

    announcements = [
        str(_event_payload(event).get("text") or "").strip()
        for event in transaction_events
        if _event_type(event) == "ANNOUNCEMENT_OBSERVED"
    ]
    announcement = next((value for value in announcements if value), "")
    target_relation = evaluate_target_relation(
        requested,
        resolved,
        landing,
        {"announcement": announcement},
        temporal_relation=stability.relation,
    )

    delta_result = compare_physical(pre, landing) if pre is not None and landing is not None else None
    if delta_result and _same_link(delta_result):
        physical_delta = "UNCHANGED"
    elif delta_result and delta_result.relation == TargetRelation.DIFFERENT_PHYSICAL_NODE:
        physical_delta = "CHANGED"
    else:
        physical_delta = "INDETERMINATE"

    action_results = [
        _event_payload(event) for event in transaction_events if _event_type(event) == "ACTION_API_RESULT"
    ]
    action_api = "INDETERMINATE"
    action_reason = ""
    if action_results:
        action_api = "ACCEPTED" if any(bool(payload.get("success")) or payload.get("result") == "ACCEPTED" for payload in action_results) else "REJECTED"
        for payload in reversed(action_results):
            helper_payload = payload.get("helper_payload")
            helper_reason = helper_payload.get("reason") if isinstance(helper_payload, Mapping) else None
            action_reason = str(payload.get("reason") or helper_reason or "").strip()
            if action_reason:
                break

    complete = bool(
        pre is not None
        and landing is not None
        and (resolved is not None or requested is not None)
        and action_results
        and set(REQUIRED_DELAYED_OFFSETS_MS).issubset(delayed_offsets)
        and "HELPER_ACK_RECEIVED" in event_types
    )
    stable_landing = stability.relation == TemporalRelation.STABLE_LANDING
    unchanged_without_contradiction = bool(
        delta_result
        and _same_link(delta_result)
    )
    verdict_confidence = "INDETERMINATE"
    verdict_reason = "INSUFFICIENT_EVIDENCE"
    if stability.relation == TemporalRelation.SNAP_BACK:
        verdict = "SNAP_BACK"
        verdict_confidence = stability.confidence
        verdict_reason = "SNAP_BACK_OBSERVED"
    elif (
        complete
        and stable_landing
        and physical_delta == "UNCHANGED"
        and unchanged_without_contradiction
        and action_api == "ACCEPTED"
    ):
        verdict = "STATIC_FOCUS"
        verdict_confidence = _minimum_confidence(delta_result.confidence, stability.confidence)
        verdict_reason = "ACCEPTED_STABLE_UNCHANGED"
    elif (
        complete
        and stable_landing
        and physical_delta == "UNCHANGED"
        and unchanged_without_contradiction
        and action_api == "REJECTED"
        and action_reason == "reached_end"
    ):
        verdict = "STATIC_FOCUS"
        verdict_confidence = _minimum_confidence(delta_result.confidence, stability.confidence)
        verdict_reason = "REACHED_END_STABLE_UNCHANGED"
    elif (
        complete
        and stable_landing
        and action_api == "ACCEPTED"
        and physical_delta == "CHANGED"
        and target_relation.allows_move_confirmation
    ):
        verdict = "MOVE_CONFIRMED"
        verdict_confidence = _minimum_confidence(
            delta_result.confidence if delta_result else "INDETERMINATE",
            target_relation.confidence,
            stability.confidence,
        )
        verdict_reason = "ACCEPTED_STABLE_TARGET_LANDING"
    elif (
        complete
        and stable_landing
        and action_api == "ACCEPTED"
        and physical_delta == "CHANGED"
        and target_relation.aggregate_relation == TargetRelation.DIFFERENT_PHYSICAL_NODE
    ):
        verdict = "MOVE_TO_OTHER_NODE"
        verdict_confidence = _minimum_confidence(
            delta_result.confidence if delta_result else "INDETERMINATE",
            target_relation.confidence,
            stability.confidence,
        )
        verdict_reason = "ACCEPTED_STABLE_OTHER_NODE"
    else:
        verdict = "INDETERMINATE"
        if not complete:
            verdict_reason = "EVIDENCE_INCOMPLETE"
        elif stability.relation == TemporalRelation.DELAYED_COMMIT:
            verdict_reason = "DELAYED_COMMIT_UNCONFIRMED"
        elif not stable_landing:
            verdict_reason = "LANDING_NOT_STABLE"
        elif action_api != "ACCEPTED":
            verdict_reason = "ACTION_NOT_ACCEPTED"
        elif physical_delta == "INDETERMINATE":
            verdict_reason = "PHYSICAL_DELTA_INDETERMINATE"
        else:
            verdict_reason = "TARGET_RELATION_INDETERMINATE"

    supporting_fields = tuple(
        sorted(
            set((delta_result.supporting_fields if delta_result else ()))
            | set(target_relation.supporting_fields)
        )
    )
    contradicting_fields = tuple(
        sorted(
            set((delta_result.contradictions if delta_result else ()))
            | set(target_relation.contradictions)
        )
    )
    missing_fields = tuple(
        sorted(
            set((delta_result.missing_fields if delta_result else ()))
            | set(target_relation.missing_fields)
            | set(stability.missing_samples)
        )
    )
    return {
        "reducer_version": IDENTITY_RULE_VERSION,
        "normalization_version": IDENTITY_NORMALIZATION_VERSION,
        "transport": "ACKED" if "HELPER_ACK_RECEIVED" in event_types else "INDETERMINATE",
        "action_api": action_api,
        "action_reason": action_reason or None,
        "target_relation": str(target_relation.aggregate_relation),
        "physical_relation": str(target_relation.physical_relation),
        "semantic_relation": str(target_relation.semantic_relation),
        "hierarchy_relation": str(target_relation.hierarchy_relation),
        "temporal_relation": str(stability.relation),
        "confidence": verdict_confidence,
        "focus_commit_claim": "CLAIMED" if "FOCUS_COMMIT_CLAIMED" in event_types else "INDETERMINATE",
        "physical_focus_delta": physical_delta,
        "target_landing": str(target_relation.aggregate_relation),
        "stability": str(stability.relation),
        "announcement": "OBSERVED" if announcement else "INDETERMINATE",
        "evidence_completeness": "COMPLETE" if complete else "PARTIAL",
        "evidence_complete": complete,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "supporting_fields": supporting_fields,
        "contradicting_fields": contradicting_fields,
        "missing_fields": missing_fields,
        "normalization_count": len(normalization_cache),
        "identity_diagnostics": {
            "pre_post": delta_result.to_dict() if delta_result else None,
            "target_landing": target_relation.to_dict(),
            "stability": {
                **asdict(stability),
                "relation": str(stability.relation),
            },
        },
    }


def replay_shadow_v2(events: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """Replay a ledger without mutating it, grouped by action transaction ID."""

    grouped: dict[str, list[Any]] = {}
    for event in events:
        transaction_id = str(_event_dict(event).get("transaction_id") or "")
        if transaction_id:
            grouped.setdefault(transaction_id, []).append(event)
    return {transaction_id: reduce_shadow_v2(grouped[transaction_id]) for transaction_id in sorted(grouped)}
