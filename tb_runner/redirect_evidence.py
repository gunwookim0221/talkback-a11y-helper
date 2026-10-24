"""Pure selected-frontier evidence contract, with no execution authority.

Completion of an inventory and readiness of one target are independent facts.
READY describes current evidence only; future execution must re-enter the
existing Phase4 gate/resolver and Phase5 FOCUS authorization at dispatch time.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

_KINDS = {"planner": ("ELIGIBLE", "PLANNER_BLOCKED"),
          "safety": ("ALLOWED", "SAFETY_BLOCKED"),
          "binding": ("RESOLVED", "TARGET_UNRESOLVED"),
          "presence": ("PRESENT", "TARGET_NOT_PRESENT")}
_BLOCKED = {"BLOCKED", "DENIED", "INELIGIBLE", "UNSUPPORTED", "UNSAFE", "RISKY", "FORBIDDEN", "MISSING", "ABSENT", "AMBIGUOUS", "UNRESOLVED"}
_SCOPE = ("scope_id", "state_id", "substate_ref", "observation_id", "observation_sequence",
          "action_epoch", "decision_watermark", "ownership_ref")
SOURCES = {"planner": "phase4b.execution_gate", "safety": "phase5b.authorize_focus_target",
           "binding": "phase4b.resolve_focus_target", "presence": "phase4b.resolve_focus_target"}


def _identity_document_status(identity):
    """Normalize a bounded identity document without comparing opaque IDs."""
    from tb_runner.traversal_reliability import redirect_identity_attributes

    if not isinstance(identity, Mapping):
        return "PARTIAL_UNKNOWN", {}, "", "IDENTITY_DOCUMENT_UNAVAILABLE"
    domain = str(identity.get("identity_domain") or "")
    opaque_id = str(identity.get("instance_id") or "")
    attrs, source, problem = redirect_identity_attributes(identity)
    if problem or domain not in {"production_scenario_scope_v1", "discovery_state_scope_v1"}:
        return "PARTIAL_UNKNOWN", attrs, domain, problem or "IDENTITY_DOMAIN_UNAVAILABLE"
    if not opaque_id or any(not attrs.get(key) for key in ("resource_id", "bounds", "class_name")):
        return "PARTIAL_UNKNOWN", attrs, domain, "IDENTITY_ATTRIBUTES_INCOMPLETE"
    return "COMPLETE", attrs, domain, source


def _identity_agreement(proof_identity, frontier_identity, *, identity_bridge=None):
    proof_status, proof_attrs, proof_domain, proof_source = _identity_document_status(proof_identity)
    frontier_status, frontier_attrs, frontier_domain, frontier_source = _identity_document_status(frontier_identity)
    agreement = {"status": "PARTIAL_UNKNOWN", "proof_domain": proof_domain,
                 "frontier_domain": frontier_domain, "proof_source": proof_source,
                 "frontier_source": frontier_source}
    if proof_status != "COMPLETE" or frontier_status != "COMPLETE":
        return agreement
    keys = ("resource_id", "bounds", "class_name")
    if any(proof_attrs.get(key) != frontier_attrs.get(key) for key in keys):
        agreement["status"] = "DISAGREEMENT"
        return agreement
    if proof_domain == frontier_domain:
        agreement["status"] = ("EXACT_MATCH"
            if proof_identity.get("instance_id") == frontier_identity.get("instance_id")
            else "DISAGREEMENT")
        return agreement

    # Opaque IDs from distinct domains are never compared. Cross-domain
    # compatibility needs a separately proven unique current-target bridge.
    bridge = identity_bridge if isinstance(identity_bridge, Mapping) else {}
    bridge_target = bridge.get("target_identity") if isinstance(bridge.get("target_identity"), Mapping) else {}
    bridge_candidate = bridge.get("candidate_identity") if isinstance(bridge.get("candidate_identity"), Mapping) else {}
    target_status, target_attrs, target_domain, _ = _identity_document_status(bridge_target)
    candidate_status, candidate_attrs, candidate_domain, _ = _identity_document_status(bridge_candidate)
    bridged = (bridge.get("status") == "EXACT_ONE"
        and target_status == candidate_status == "COMPLETE"
        and {target_domain, candidate_domain} == {proof_domain, frontier_domain}
        and target_attrs == proof_attrs and candidate_attrs == frontier_attrs)
    agreement["status"] = "COMPATIBLE_CURRENT_TARGET" if bridged else "PARTIAL_UNKNOWN"
    return agreement


def _production_target_identity(instance, raw, scenario_id=None):
    """Build the same scoped identity document as the production frontier."""
    from tb_runner import scroll_reliability
    from tb_runner.frontier_shadow import production_candidate
    from tb_runner.state_graph import build_graph_state_identity

    instance = str(instance or "")
    scenario = str(scenario_id or (raw.get("scenario_id") if isinstance(raw, Mapping) else "") or "")
    if not scenario:
        try:
            import json
            parsed = json.loads(instance)
            scenario = str(parsed[1]) if isinstance(parsed, list) and len(parsed) > 1 else ""
        except (ValueError, TypeError):
            scenario = ""
    partial = {"identity_domain": "production_scenario_scope_v1", "instance_id": instance,
               "identity_attributes": {"resource_id": "", "bounds": "", "class_name": ""}}
    if not isinstance(raw, Mapping) or not scenario or not instance:
        return partial, "PARTIAL_UNKNOWN", "PRODUCTION_HIERARCHY_CONTEXT_UNAVAILABLE"
    state_id = build_graph_state_identity(raw).state_id or ""
    identities = []
    for node in scroll_reliability.flat_nodes(raw.get("nodes", [])):
        candidate = production_candidate(state_id=state_id, scenario_id=scenario, candidate=node)
        if candidate and candidate.get("target_identity", {}).get("instance_id") == instance:
            identities.append(candidate["target_identity"])
    if not identities:
        return partial, "PARTIAL_UNKNOWN", "PRODUCTION_TARGET_IDENTITY_NOT_FOUND"
    identity = identities[0]
    if any(other != identity for other in identities[1:]):
        return partial, "PARTIAL_UNKNOWN", "PRODUCTION_TARGET_IDENTITY_AMBIGUOUS"
    status, _attrs, _domain, reason = _identity_document_status(identity)
    return identity, status, "PRODUCTION_FRONTIER_CANDIDATE" if status == "COMPLETE" else reason


def evaluate_redirect_evidence(*, selected, sources=None, context=None):
    selected = selected if isinstance(selected, Mapping) else {}
    sources = sources if isinstance(sources, Mapping) else {}
    sources = {kind: sources.get(kind) if isinstance(sources.get(kind), Mapping) else {} for kind in _KINDS}
    context = context if isinstance(context, Mapping) else {}
    result = {
        "frontier_id": selected.get("frontier_id"), "candidate_id": selected.get("candidate_id"),
        "state_id": selected.get("state_id"), "edge_type": selected.get("edge_type", selected.get("action_type")),
        "target_identity": deepcopy(selected.get("target_identity") or {}),
        "decision_watermark": context.get("decision_watermark"),
        "scope_id": context.get("scope_id"),
        "active_scope_id": context.get("active_scope_id"),
        "action_epoch": context.get("action_epoch"), "observation_epoch": context.get("observation_epoch"),
        "observation_id": context.get("observation_id"), "observation_sequence": context.get("observation_sequence"),
        "substate_ref": context.get("substate_ref"),
        "action_ownership": deepcopy(context.get("action_ownership") or {}),
        "recommendation_owner": "SHADOW_ONLY", "execution_authority": "NONE",
        "requires_dispatch_time_revalidation": True,
        "revalidation_status": "REQUIRES_DISPATCH_TIME_REVALIDATION",
        "evidence_current": False, "selected_frontier_execution_ready": False,
        "status": "UNKNOWN", "reason_codes": [], "proofs": {},
        "target_identity_agreement": {},
        "frontier_target": deepcopy(selected.get("target_identity") or {}),
        "planner_revalidated_target": deepcopy((sources.get("planner") or {}).get("target_identity") or {}),
    }
    def fail(status, reason):
        result.update(status=status, reason_codes=[reason])
        return result
    # Copy only bounded references/statuses, never hierarchy or UI labels.
    for kind in _KINDS:
        proof = sources.get(kind)
        proof = proof if isinstance(proof, Mapping) else {}
        result["proofs"][kind] = {key: proof.get(key) for key in
            ("status", "source", "proof_ref", "policy_ref", "resolver_ref", "action_type",
             "target_identity_source", "target_identity_status", *_SCOPE)}
        result[kind + "_evidence_status"] = proof.get("status", "UNKNOWN")
        result[kind + "_evidence_ref"] = proof.get("proof_ref")
    result["planner_eligible"] = (sources.get("planner") or {}).get("status") == "ELIGIBLE"
    result["action_specific_safety"] = result["safety_evidence_status"]
    result["target_binding_status"] = result["binding_evidence_status"]
    result["target_present"] = (sources.get("presence") or {}).get("status") == "PRESENT"
    if (not selected.get("frontier_id") or not isinstance(selected.get("target_identity"), Mapping)
            or not selected["target_identity"].get("instance_id")):
        return fail("UNKNOWN", "SELECTED_FRONTIER_UNAVAILABLE")
    scope_id = context.get("scope_id")
    active_scope_id = context.get("active_scope_id")
    if (not isinstance(scope_id, str) or not scope_id
            or not isinstance(active_scope_id, str) or not active_scope_id):
        return fail("STALE", "OBSERVATION_SCOPE_UNAVAILABLE")
    if scope_id != active_scope_id:
        return fail("STALE", "OBSERVATION_SCOPE_MISMATCH")
    sequence = context.get("observation_sequence")
    if type(sequence) is not int or context.get("observation_id") != f"observation:{scope_id}:{sequence}":
        return fail("STALE", "OBSERVATION_SCOPE_MISMATCH")
    if context.get("evidence_current") is not True:
        return fail("STALE", "OBSERVATION_NOT_CURRENT")
    if (type(context.get("action_epoch")) is not int or type(context.get("observation_epoch")) is not int
            or context.get("observation_epoch") != context.get("action_epoch")):
        return fail("EPOCH_MISMATCH", "ACTION_OBSERVATION_EPOCH_MISMATCH")
    if any(type(context.get(key)) is not int for key in ("decision_watermark", "observation_sequence")):
        return fail("UNKNOWN", "DECISION_OR_OBSERVATION_SEQUENCE_UNAVAILABLE")
    if not context.get("state_id") or selected.get("state_id") != context.get("state_id"):
        return fail("STATE_MISMATCH", "SELECTED_STATE_MISMATCH")
    expected_action_id = f"dispatch:{active_scope_id}:{context.get('action_epoch')}"
    if (context.get("pending_action") is not False or not context.get("ownership_ref")
            or (context.get("action_ownership") or {}).get("ownership_status") != "KNOWN"
            or (context.get("action_ownership") or {}).get("action_id") != context.get("ownership_ref")
            or (context.get("action_ownership") or {}).get("action_epoch") != context.get("action_epoch")
            or context.get("ownership_ref") != expected_action_id
            or (context.get("action_ownership") or {}).get("action_id")
               != expected_action_id):
        return fail("OWNERSHIP_UNRESOLVED", "ACTION_OWNERSHIP_UNRESOLVED")
    if result["edge_type"] != "TARGETED_FOCUS":
        return fail("UNKNOWN", "ONLY_FOCUS_EVIDENCE_CONTRACT_SUPPORTED")
    for kind, (allowed, blocked) in _KINDS.items():
        proof = sources.get(kind) or {}
        if not isinstance(proof, Mapping) or not proof.get("proof_ref") or not proof.get("source"):
            return fail("UNKNOWN", kind.upper() + "_PROOF_UNAVAILABLE")
        if proof.get("source") != SOURCES[kind]:
            return fail("UNKNOWN", kind.upper() + "_PRODUCTION_SOURCE_UNPROVEN")
        if proof.get("status") != allowed:
            return fail(blocked if proof.get("status") in _BLOCKED else "UNKNOWN", kind.upper() + "_NOT_PROVEN")
        bridges = context.get("identity_bridges")
        bridge = bridges.get(kind) if isinstance(bridges, Mapping) else None
        agreement = _identity_agreement(proof.get("target_identity"),
                                        selected.get("target_identity"),
                                        identity_bridge=bridge)
        result["target_identity_agreement"][kind] = agreement
        result["proofs"][kind]["target_identity_agreement"] = agreement["status"]
        if agreement["status"] not in {"EXACT_MATCH", "COMPATIBLE_CURRENT_TARGET"}:
            if agreement["status"] == "DISAGREEMENT":
                return fail("PLANNER_BLOCKED" if kind == "planner" else "TARGET_UNRESOLVED",
                            kind.upper() + "_TARGET_DISAGREEMENT")
            return fail("UNKNOWN", kind.upper() + "_TARGET_IDENTITY_UNKNOWN")
        for key in _SCOPE:
            if (context.get(key) is None or context.get(key) == "" or proof.get(key) != context.get(key)
                    or type(proof.get(key)) is not type(context.get(key))):
                status = "EPOCH_MISMATCH" if key == "action_epoch" else "STATE_MISMATCH" if key in {"state_id", "substate_ref"} else "STALE"
                return fail(status, kind.upper() + "_" + key.upper() + "_MISMATCH")
        if kind in {"planner", "safety", "binding"}:
            policy = context.get(kind + "_policy_ref")
            if not policy or proof.get("policy_ref") != policy:
                return fail("STALE", kind.upper() + "_POLICY_NOT_CURRENT")
        if kind == "safety" and proof.get("action_type") != "FOCUS":
            return fail("SAFETY_BLOCKED", "ACTION_SPECIFIC_FOCUS_PROOF_REQUIRED")
        if kind in {"binding", "presence"} and not proof.get("resolver_ref"):
            return fail("TARGET_UNRESOLVED", "EXACT_RESOLVER_REFERENCE_REQUIRED")
    result.update(status="READY", evidence_current=True, selected_frontier_execution_ready=True)
    return result


def record_existing_proof(client, *, kind, status, instance, raw, step, proof, policy_ref):
    """Observe an already executed production gate/resolver; never run one here.

    Missing capture provenance is deliberately retained as UNKNOWN scope. In
    particular the producer must never stamp an old raw tree with the live epoch.
    A future active preparation must supply provenance from its own reacquisition.
    """
    from talkback_lib.exploration_evidence_clock import clock_for
    from tb_runner.canonical_json import canonical_sha256
    from tb_runner.state_graph import build_graph_state_identity
    clock = clock_for(client)
    if clock is None:
        return
    try:
        capture = raw.get("_exploration_observation") or {}
        state = build_graph_state_identity(raw)
        owner = capture.get("action_ownership") or {}
        context = dict(scope_id=capture.get("scope_id"), active_scope_id=clock.scope_id,
                       state_id=state.state_id, substate_ref=state.state_id,
                       observation_id=capture.get("observation_id"), observation_sequence=capture.get("observation_sequence"),
                       observation_epoch=capture.get("action_epoch"), action_epoch=capture.get("action_epoch"),
                       decision_watermark=step, ownership_ref=owner.get("action_id"),
                       action_ownership=deepcopy(owner), pending_action=False)
        sources = getattr(client, "_phase6_redirect_proofs", {})
        sources = dict(sources) if isinstance(sources, Mapping) else {}
        context_before = getattr(client, "_phase6_redirect_context", {})
        for key in ("planner_policy_ref", "safety_policy_ref", "binding_policy_ref"):
            if isinstance(context_before, Mapping) and key in context_before:
                context[key] = context_before[key]
        context[kind + "_policy_ref"] = policy_ref
        source_ref = SOURCES[kind] + ":" + canonical_sha256(proof)
        target_identity, identity_status, identity_source = _production_target_identity(
            instance, raw, scenario_id=(raw.get("scenario_id") if isinstance(raw, Mapping) else None))
        sources[kind] = {**{k: context.get(k) for k in _SCOPE}, "status": status,
                         "source": SOURCES[kind], "proof_ref": source_ref, "policy_ref": policy_ref,
                         "resolver_ref": source_ref if kind in {"binding", "presence"} else None,
                         "action_type": "FOCUS", "target_identity": target_identity,
                         "target_identity_status": identity_status,
                         "target_identity_source": identity_source}
        client._phase6_redirect_proofs = sources
        client._phase6_redirect_context = context
    except Exception:
        # Observability failure removes proof, never changes production behavior.
        client._phase6_redirect_proofs = {}


def current_execution_context(client, observation, *, state_id, watermark, production_state=None):
    """Pure projection from already available evidence; no acquisition or planning."""
    from talkback_lib.exploration_evidence_clock import clock_for
    clock = clock_for(client)
    context = dict(getattr(client, "_phase6_redirect_context", {}) or {})
    owner = observation.get("action_ownership") or {}
    context.update(scope_id=observation.get("scope_id"),
                   active_scope_id=clock.scope_id if clock else None,
                   state_id=state_id, substate_ref=state_id, decision_watermark=watermark,
                   action_epoch=clock.action_epoch if clock else None,
                   observation_epoch=observation.get("action_epoch"), observation_id=observation.get("observation_id"),
                   observation_sequence=observation.get("observation_sequence"), action_ownership=owner,
                   ownership_ref=owner.get("action_id"), evidence_current=clock.current(observation) if clock else False)
    # A cached proof cannot assert that the current production action queue is
    # idle. Project the existing in-memory recovery/tab/realignment state.
    pending_fields = ("food_scan_recovery_pending", "forced_local_tab_target_rid",
                      "forced_local_tab_target_action_label", "post_realign_pending_steps",
                      "pending_scroll_ready_cluster_signature")
    context["pending_action"] = (any(bool(getattr(production_state, key, False)) for key in pending_fields)
                                 if production_state is not None else None)
    return context


# RF1 contracts below are deliberately additive. The runtime still uses the
# compatibility mapping API above until a separately reviewed migration.
from collections.abc import Iterator
from dataclasses import dataclass, field
from tb_runner.traversal_reliability import redirect_identity_attributes as _redirect_identity_attributes


@dataclass(frozen=True)
class FrozenEvidenceMap(Mapping):
    """Small recursively frozen mapping used at evidence boundaries."""

    entries: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self):
        raw = self.entries.items() if isinstance(self.entries, Mapping) else self.entries
        frozen = tuple(sorted(((str(key), _freeze_evidence(value)) for key, value in raw),
                              key=lambda item: item[0]))
        object.__setattr__(self, "entries", frozen)

    def __getitem__(self, key: str) -> Any:
        for name, value in self.entries:
            if name == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self.entries)

    def __len__(self) -> int:
        return len(self.entries)


def _freeze_evidence(value: Any) -> Any:
    if isinstance(value, FrozenEvidenceMap):
        return value
    if isinstance(value, Mapping):
        return FrozenEvidenceMap(tuple(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_evidence(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze_evidence(item) for item in value), key=repr))
    return value


def _evidence_document(value: Any) -> dict[str, Any]:
    """Return a detached JSON-like document from a frozen contract value."""
    if isinstance(value, Mapping):
        return {str(key): _evidence_document(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_evidence_document(item) for item in value]
    return value


@dataclass(frozen=True)
class CanonicalTargetIdentity:
    """Immutable target description, not a permit or a visit identity oracle."""

    identity_domain: str = ""
    instance_id: str = ""
    resource_id: str = ""
    bounds: str = ""
    class_name: str = ""
    status: str = "PARTIAL"
    source: str = "UNKNOWN"
    source_shape: str = "UNKNOWN"
    source_ref: str = ""
    reason: str = ""

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_domain": self.identity_domain,
            "instance_id": self.instance_id,
            "identity_attributes": {
                "resource_id": self.resource_id,
                "bounds": self.bounds,
                "class_name": self.class_name,
            },
            "status": self.status,
            "source": self.source,
            "source_shape": self.source_shape,
            "source_ref": self.source_ref,
            "reason": self.reason,
        }


_IDENTITY_DOMAINS = {"production_scenario_scope_v1", "discovery_state_scope_v1"}


def canonical_target_identity(identity: Any, *, source: str = "IDENTITY_DOCUMENT",
                              expected_domain: str | None = None,
                              source_ref: str = "") -> CanonicalTargetIdentity:
    """Normalize nested/legacy identity shapes and retain conflict as INVALID."""
    if not isinstance(identity, Mapping):
        return CanonicalTargetIdentity(status="PARTIAL", source_shape="UNKNOWN",
                                       source_ref=str(source_ref or ""),
                                       reason="IDENTITY_DOCUMENT_UNAVAILABLE")
    domain = str(identity.get("identity_domain") or "").strip()
    instance = str(identity.get("instance_id") or "").strip()
    attrs, shape, problem = _redirect_identity_attributes(identity)
    if problem == "IDENTITY_ATTRIBUTE_CONFLICT" or problem == "NESTED_IDENTITY_ATTRIBUTES_INVALID":
        status = "INVALID"
    elif not domain or domain not in _IDENTITY_DOMAINS:
        status = "INVALID" if domain else "PARTIAL"
        problem = problem or "IDENTITY_DOMAIN_UNAVAILABLE"
    elif expected_domain and domain != expected_domain:
        status = "INVALID"
        problem = "IDENTITY_DOMAIN_MISMATCH"
    elif problem:
        status = "PARTIAL"
    elif not instance or any(not attrs.get(name) for name in ("resource_id", "bounds", "class_name")):
        status = "PARTIAL"
        problem = "IDENTITY_ATTRIBUTES_INCOMPLETE"
    else:
        status = "COMPLETE"
    return CanonicalTargetIdentity(
        identity_domain=domain,
        instance_id=instance,
        resource_id=str(attrs.get("resource_id") or ""),
        bounds=str(attrs.get("bounds") or ""),
        class_name=str(attrs.get("class_name") or ""),
        status=status,
        source=str(source or "UNKNOWN"),
        source_shape=str(shape or "UNKNOWN"),
        source_ref=str(source_ref or ""),
        reason=str(problem or ""),
    )


def _target_identity_document(value: Any) -> Any:
    if isinstance(value, Mapping) and isinstance(value.get("target_identity"), Mapping):
        return value["target_identity"]
    return value


def adapt_production_frontier_identity(value: Any, *, source_ref: str = "") -> CanonicalTargetIdentity:
    return canonical_target_identity(_target_identity_document(value), source="PRODUCTION_FRONTIER",
        expected_domain="production_scenario_scope_v1", source_ref=source_ref)


def adapt_discovery_candidate_identity(value: Any, *, source_ref: str = "") -> CanonicalTargetIdentity:
    return canonical_target_identity(_target_identity_document(value), source="DISCOVERY_CANDIDATE",
        expected_domain="discovery_state_scope_v1", source_ref=source_ref)


def adapt_proof_target_identity(value: Any, *, source_ref: str = "") -> CanonicalTargetIdentity:
    document = _target_identity_document(value)
    return canonical_target_identity(document, source="PRODUCTION_PROOF",
                                     source_ref=source_ref)


@dataclass(frozen=True)
class IdentityBridgeEvidence:
    """Recorded bridge result; cross-domain opaque IDs are never compared."""

    status: str = "UNKNOWN"
    target_identity: CanonicalTargetIdentity = field(default_factory=CanonicalTargetIdentity)
    candidate_identity: CanonicalTargetIdentity = field(default_factory=CanonicalTargetIdentity)
    reason: str = ""
    source_ref: str = ""

    def __post_init__(self):
        if not isinstance(self.target_identity, CanonicalTargetIdentity):
            raise TypeError("target_identity must be a CanonicalTargetIdentity")
        if not isinstance(self.candidate_identity, CanonicalTargetIdentity):
            raise TypeError("candidate_identity must be a CanonicalTargetIdentity")


def identity_bridge_evidence(target_identity: Any, bridge_result: Any, *,
                             source_ref: str = "") -> IdentityBridgeEvidence:
    target = adapt_production_frontier_identity(target_identity, source_ref=source_ref)
    candidate = None
    if isinstance(bridge_result, Mapping):
        candidate = bridge_result.get("candidate")
        status = str(bridge_result.get("status") or "UNKNOWN")
        reason = str(bridge_result.get("reason") or "")
    else:
        candidate = getattr(bridge_result, "candidate", None)
        status = str(getattr(bridge_result, "status", "UNKNOWN") or "UNKNOWN")
        reason = str(getattr(bridge_result, "reason", "") or "")
    candidate_identity = adapt_discovery_candidate_identity(candidate, source_ref=source_ref)
    return IdentityBridgeEvidence(status=status, target_identity=target,
                                  candidate_identity=candidate_identity,
                                  reason=reason, source_ref=source_ref)


def compare_canonical_identities(left: CanonicalTargetIdentity,
                                 right: CanonicalTargetIdentity,
                                 bridge: IdentityBridgeEvidence | None = None) -> str:
    """Compare one target across sources without equating foreign opaque IDs."""
    if not isinstance(left, CanonicalTargetIdentity) or not isinstance(right, CanonicalTargetIdentity):
        return "UNKNOWN"
    if left.status != "COMPLETE" or right.status != "COMPLETE":
        return "UNKNOWN"
    left_attrs = (left.resource_id, left.bounds, left.class_name)
    right_attrs = (right.resource_id, right.bounds, right.class_name)
    if left_attrs != right_attrs:
        return "DISAGREEMENT"
    if left.identity_domain == right.identity_domain:
        return "EXACT_MATCH" if left.instance_id == right.instance_id else "DISAGREEMENT"
    if not isinstance(bridge, IdentityBridgeEvidence) or bridge.status != "EXACT_ONE":
        return "UNKNOWN"
    if (bridge.target_identity.identity_domain != left.identity_domain
            or bridge.candidate_identity.identity_domain != right.identity_domain
            or bridge.target_identity.status != "COMPLETE"
            or bridge.candidate_identity.status != "COMPLETE"
            or bridge.target_identity.instance_id != left.instance_id
            or bridge.candidate_identity.instance_id != right.instance_id
            or (bridge.target_identity.resource_id, bridge.target_identity.bounds,
                bridge.target_identity.class_name) != left_attrs
            or (bridge.candidate_identity.resource_id, bridge.candidate_identity.bounds,
                bridge.candidate_identity.class_name) != right_attrs):
        return "UNKNOWN"
    return "COMPATIBLE_CURRENT_TARGET"


@dataclass(frozen=True)
class EvidenceStateReference:
    """A state ID plus provenance; graph and discovery IDs stay separate."""

    identity_domain: str = ""
    state_id: str = ""
    observation_id: str = ""
    observation_sequence: int | None = None
    scope_id: str = ""
    action_epoch: int | None = None
    context_revision: int | None = None


@dataclass(frozen=True)
class ProductionEvidenceFrame:
    """One immutable production observation cut; grants no execution authority."""

    run_id: str = ""
    decision_id: str = ""
    decision_watermark: int | None = None
    observation_id: str = ""
    observation_sequence: int | None = None
    scope_id: str = ""
    action_epoch: int | None = None
    observation_epoch: int | None = None
    context_revision: int | None = None
    # Runtime currentness is captured before the production collector advances
    # the action epoch.  It is optional for RF1 compatibility and fail-closed
    # in the common evaluator when absent.
    evidence_current: bool | None = None
    inventory_complete: bool | None = None
    graph_state_ref: EvidenceStateReference | None = None
    discovery_state_ref: EvidenceStateReference | None = None
    plugin_context: Any = None
    substate: Any = ()
    lifecycle_status: str | None = None
    lifecycle_evidence: Any = None
    decision_alignment: Any = None
    helper_evidence: FrozenEvidenceMap = field(default_factory=FrozenEvidenceMap)
    helper_status: str | None = None
    overlay_status: str | None = None
    recovery_status: str | None = None
    transition_status: str | None = None

    def __post_init__(self):
        for name in ("graph_state_ref", "discovery_state_ref"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, EvidenceStateReference):
                raise TypeError(name + " must be an EvidenceStateReference or None")
        object.__setattr__(self, "plugin_context", _freeze_evidence(self.plugin_context))
        object.__setattr__(self, "substate", _freeze_evidence(self.substate))
        object.__setattr__(self, "lifecycle_evidence", _freeze_evidence(self.lifecycle_evidence))
        object.__setattr__(self, "decision_alignment", _freeze_evidence(self.decision_alignment))
        object.__setattr__(self, "helper_evidence", _freeze_evidence(self.helper_evidence))


@dataclass(frozen=True)
class ProofProvenance:
    run_id: str = ""
    decision_id: str = ""
    decision_watermark: int | None = None
    observation_id: str = ""
    observation_sequence: int | None = None
    scope_id: str = ""
    action_epoch: int | None = None
    observation_epoch: int | None = None
    context_revision: int | None = None
    graph_state_id: str = ""
    discovery_state_id: str = ""
    substate: Any = ()

    def __post_init__(self):
        object.__setattr__(self, "substate", _freeze_evidence(self.substate))


def proof_provenance_for(frame: ProductionEvidenceFrame) -> ProofProvenance:
    graph_id = frame.graph_state_ref.state_id if frame.graph_state_ref else ""
    discovery_id = frame.discovery_state_ref.state_id if frame.discovery_state_ref else ""
    return ProofProvenance(
        run_id=frame.run_id, decision_id=frame.decision_id,
        decision_watermark=frame.decision_watermark,
        observation_id=frame.observation_id,
        observation_sequence=frame.observation_sequence, scope_id=frame.scope_id,
        action_epoch=frame.action_epoch, observation_epoch=frame.observation_epoch,
        context_revision=frame.context_revision, graph_state_id=graph_id,
        discovery_state_id=discovery_id, substate=frame.substate)


@dataclass(frozen=True)
class TargetProofSet:
    """Read-only outputs from real planner/gate/resolver/assessment APIs."""

    target_identity: CanonicalTargetIdentity = field(default_factory=CanonicalTargetIdentity)
    production_target_identity: CanonicalTargetIdentity = field(default_factory=CanonicalTargetIdentity)
    identity_bridge: IdentityBridgeEvidence = field(default_factory=IdentityBridgeEvidence)
    planner_status: str = "UNKNOWN"
    phase4_gate_status: str = "UNKNOWN"
    binding_status: str = "UNKNOWN"
    presence_status: str = "UNKNOWN"
    safety_assessment_status: str = "UNKNOWN"
    proof_complete: bool = False
    planner_state_id: str = ""
    proof_refs: FrozenEvidenceMap = field(default_factory=FrozenEvidenceMap)
    source_refs: FrozenEvidenceMap = field(default_factory=FrozenEvidenceMap)
    provenance: ProofProvenance = field(default_factory=ProofProvenance)
    assessment_kind: str = "READ_ONLY_ASSESSMENT"
    reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.target_identity, CanonicalTargetIdentity):
            raise TypeError("target_identity must be a CanonicalTargetIdentity")
        if not isinstance(self.production_target_identity, CanonicalTargetIdentity):
            raise TypeError("production_target_identity must be a CanonicalTargetIdentity")
        if not isinstance(self.identity_bridge, IdentityBridgeEvidence):
            raise TypeError("identity_bridge must be IdentityBridgeEvidence")
        if not isinstance(self.provenance, ProofProvenance):
            raise TypeError("provenance must be ProofProvenance")
        object.__setattr__(self, "proof_refs", _freeze_evidence(self.proof_refs))
        object.__setattr__(self, "source_refs", _freeze_evidence(self.source_refs))
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True)
class RedirectEvidenceBundle:
    """Evidence snapshot for readiness only; it is never a Phase 5 permit."""

    run_id: str = ""
    decision_id: str = ""
    frontier_id: str = ""
    frontier_state_id: str = ""
    frontier_action: str = ""
    frame: ProductionEvidenceFrame = field(default_factory=ProductionEvidenceFrame)
    frontier_target: CanonicalTargetIdentity = field(default_factory=CanonicalTargetIdentity)
    proof_set: TargetProofSet = field(default_factory=TargetProofSet)
    frontier_recommendation: FrozenEvidenceMap = field(default_factory=FrozenEvidenceMap)

    def __post_init__(self):
        if not isinstance(self.frame, ProductionEvidenceFrame):
            raise TypeError("frame must be ProductionEvidenceFrame")
        if not isinstance(self.frontier_target, CanonicalTargetIdentity):
            raise TypeError("frontier_target must be CanonicalTargetIdentity")
        if not isinstance(self.proof_set, TargetProofSet):
            raise TypeError("proof_set must be TargetProofSet")
        object.__setattr__(self, "frontier_recommendation", _freeze_evidence(self.frontier_recommendation))


@dataclass(frozen=True)
class ReadinessAssessment:
    """Pure readiness result; READY still requires dispatch-time Phase 4/5 checks."""

    status: str = "UNKNOWN"
    reason_codes: tuple[str, ...] = ()
    bundle_id: str = ""
    evidence_current: bool = False
    execution_authority: str = "NONE"
    phase5_permit_issued: bool = False

    def __post_init__(self):
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True)
class RedirectRevalidationStamp:
    """Freshness summary, explicitly separate from a Phase 5 FOCUS permit."""

    bundle_id: str
    scope_id: str
    action_epoch: int | None
    observation_epoch: int | None
    context_revision: int | None
    decision_watermark: int | None
    graph_state_id: str
    discovery_state_id: str
    target_status: str
    readiness_status: str
    permit: bool = False


def _status(value: Any) -> str:
    return str(value or "").strip().upper()


def _frame_reasons(frame: ProductionEvidenceFrame) -> list[str]:
    reasons: list[str] = []
    if not frame.run_id or not frame.decision_id:
        reasons.append("RUN_OR_DECISION_ID_UNKNOWN")
    if type(frame.decision_watermark) is not int or frame.decision_watermark < 0:
        reasons.append("DECISION_WATERMARK_UNKNOWN")
    if (not frame.observation_id or type(frame.observation_sequence) is not int
            or frame.observation_sequence < 0 or not frame.scope_id):
        reasons.append("OBSERVATION_PROVENANCE_UNKNOWN")
    if (type(frame.action_epoch) is not int or type(frame.observation_epoch) is not int
            or frame.action_epoch != frame.observation_epoch):
        reasons.append("ACTION_OBSERVATION_EPOCH_MISMATCH")
    if type(frame.context_revision) is not int or frame.context_revision < 0:
        reasons.append("CONTEXT_REVISION_UNKNOWN")
    for name, ref, domain in (
        ("GRAPH", frame.graph_state_ref, "graph_state_ref_v1"),
        ("DISCOVERY", frame.discovery_state_ref, "discovery_state_scope_v1"),
    ):
        if not isinstance(ref, EvidenceStateReference) or not ref.state_id:
            reasons.append(name + "_STATE_UNKNOWN")
            continue
        if ref.identity_domain != domain:
            reasons.append(name + "_STATE_DOMAIN_INVALID")
        if (ref.observation_id != frame.observation_id
                or ref.observation_sequence != frame.observation_sequence
                or ref.scope_id != frame.scope_id
                or ref.action_epoch != frame.action_epoch
                or ref.context_revision != frame.context_revision):
            reasons.append(name + "_STATE_PROVENANCE_MISMATCH")
    return reasons


def _condition_status(value: Any, *, clear: set[str], blocked: set[str], name: str,
                      reasons: list[str]) -> bool:
    status = _status(value)
    if status in blocked:
        reasons.append(name + "_BLOCKED")
        return False
    if status not in clear:
        reasons.append(name + "_UNKNOWN")
        return False
    return True


def evaluate_redirect_readiness(bundle: RedirectEvidenceBundle) -> ReadinessAssessment:
    """Pure, fail-closed readiness evaluator. It never issues an execution permit."""
    if not isinstance(bundle, RedirectEvidenceBundle):
        return ReadinessAssessment(reason_codes=("BUNDLE_UNAVAILABLE",))
    reasons: list[str] = []
    frame = bundle.frame
    proof = bundle.proof_set
    reasons.extend(_frame_reasons(frame))
    if frame.evidence_current is not True:
        reasons.append("OBSERVATION_NOT_CURRENT")
    if frame.inventory_complete is not True:
        reasons.append("FRONTIER_INVENTORY_INCOMPLETE")
    blocked = False
    condition_specs = (
        ("LIFECYCLE", frame.lifecycle_status,
         {"CLEAR", "SETTLED", "READY"}, {"BLOCKED", "RESTART", "RESTARTED", "UNSETTLED", "UNAVAILABLE", "FAILED"}),
        ("HELPER", frame.helper_status,
         {"READY", "AVAILABLE", "HEALTHY", "MATCH"}, {"BLOCKED", "UNAVAILABLE", "NOT_READY", "FAILED", "MISMATCH"}),
        ("OVERLAY", frame.overlay_status,
         {"CLEAR", "NONE", "ABSENT", "NO_OVERLAY"}, {"BLOCKED", "PRESENT_BLOCKING", "UNSAFE", "UNKNOWN_MODAL"}),
        ("RECOVERY", frame.recovery_status,
         {"CLEAR", "NONE"}, {"BLOCKED", "PENDING", "ACTIVE", "FAILED"}),
        ("TRANSITION", frame.transition_status,
         {"CLEAR", "NONE", "SETTLED"}, {"BLOCKED", "PENDING", "ACTIVE", "UNSETTLED"}),
    )
    for name, value, clear, is_blocked in condition_specs:
        before = len(reasons)
        ok = _condition_status(value, clear=clear, blocked=is_blocked,
                               name=name, reasons=reasons)
        if len(reasons) > before and reasons[-1].endswith("_BLOCKED"):
            blocked = True

    if bundle.run_id != frame.run_id or bundle.decision_id != frame.decision_id:
        reasons.append("BUNDLE_FRAME_PROVENANCE_MISMATCH")
    plugin_context_status = ""
    if isinstance(frame.plugin_context, Mapping):
        plugin_context_status = _status(frame.plugin_context.get("status"))
    else:
        plugin_context_status = _status(frame.plugin_context)
    if plugin_context_status in {"WRONG_CONTEXT", "CONTRADICTORY_CONTEXT", "BLOCKED"}:
        reasons.append("PLUGIN_CONTEXT_BLOCKED")
        blocked = True
    elif plugin_context_status not in {"VERIFIED_PLUGIN_CONTEXT"}:
        reasons.append("PLUGIN_CONTEXT_UNKNOWN")
    if not bundle.frontier_id or bundle.frontier_action != "TARGETED_FOCUS":
        reasons.append("SUPPORTED_FRONTIER_UNAVAILABLE")
    recommendation = bundle.frontier_recommendation
    if (not isinstance(recommendation, Mapping)
            or recommendation.get("frontier_id") != bundle.frontier_id
            or recommendation.get("state_id") != bundle.frontier_state_id
            or str(recommendation.get("edge_type") or recommendation.get("action_type") or "")
               != bundle.frontier_action
            or type(recommendation.get("decision_watermark")) is not int
            or recommendation.get("decision_watermark") != frame.decision_watermark):
        reasons.append("FRONTIER_RECOMMENDATION_PROVENANCE_MISMATCH")
    if ("substate" in recommendation
            and _freeze_evidence(recommendation.get("substate")) != frame.substate):
        reasons.append("FRONTIER_SUBSTATE_MISMATCH")
    recommendation_target = adapt_production_frontier_identity(recommendation)
    recommendation_match = compare_canonical_identities(
        bundle.frontier_target, recommendation_target)
    if recommendation_match == "DISAGREEMENT":
        reasons.append("FRONTIER_RECOMMENDATION_TARGET_DISAGREEMENT")
        blocked = True
    elif recommendation_match != "EXACT_MATCH":
        reasons.append("FRONTIER_RECOMMENDATION_TARGET_UNKNOWN")
    if (not frame.graph_state_ref or bundle.frontier_state_id != frame.graph_state_ref.state_id):
        reasons.append("FRONTIER_GRAPH_STATE_MISMATCH")
    provenance = proof.provenance if isinstance(proof, TargetProofSet) else None
    expected_provenance = proof_provenance_for(frame)
    if not isinstance(provenance, ProofProvenance) or provenance != expected_provenance:
        reasons.append("PROOF_PROVENANCE_MISMATCH")
    if (not frame.discovery_state_ref
            or proof.planner_state_id != frame.discovery_state_ref.state_id):
        reasons.append("PLANNER_DISCOVERY_STATE_MISMATCH")

    if not isinstance(bundle.frontier_target, CanonicalTargetIdentity):
        reasons.append("FRONTIER_TARGET_UNKNOWN")
    elif bundle.frontier_target.status == "INVALID":
        reasons.append("FRONTIER_TARGET_INVALID")
        blocked = True
    elif bundle.frontier_target.status != "COMPLETE":
        reasons.append("FRONTIER_TARGET_PARTIAL")

    if not isinstance(proof, TargetProofSet):
        reasons.append("TARGET_PROOF_SET_UNKNOWN")
    else:
        agreement = compare_canonical_identities(
            bundle.frontier_target, proof.production_target_identity)
        if agreement == "DISAGREEMENT":
            reasons.append("PRODUCTION_TARGET_DISAGREEMENT")
            blocked = True
        elif agreement != "EXACT_MATCH":
            reasons.append("PRODUCTION_TARGET_IDENTITY_UNKNOWN")
        cross = compare_canonical_identities(
            bundle.frontier_target, proof.target_identity, proof.identity_bridge)
        if cross == "DISAGREEMENT":
            reasons.append("PROOF_TARGET_DISAGREEMENT")
            blocked = True
        elif cross != "COMPATIBLE_CURRENT_TARGET":
            if proof.identity_bridge.status == "NONE":
                reasons.append("IDENTITY_BRIDGE_NONE")
                blocked = True
            elif proof.identity_bridge.status == "AMBIGUOUS":
                reasons.append("IDENTITY_BRIDGE_AMBIGUOUS")
            else:
                reasons.append("IDENTITY_BRIDGE_UNKNOWN")
        if not proof.proof_complete:
            reasons.append("PROOF_SET_INCOMPLETE")
        for name, value, accepted, blocked_values in (
            ("PLANNER", proof.planner_status, {"ELIGIBLE"}, {"BLOCKED", "INELIGIBLE", "UNSUPPORTED"}),
            ("PHASE4_GATE", proof.phase4_gate_status, {"ALLOWED"}, {"BLOCKED", "DENIED"}),
            ("BINDING", proof.binding_status, {"RESOLVED"}, {"BLOCKED", "UNRESOLVED", "STALE"}),
            ("PRESENCE", proof.presence_status, {"PRESENT"}, {"BLOCKED", "ABSENT", "NOT_PRESENT"}),
            ("SAFETY_ASSESSMENT", proof.safety_assessment_status, {"ALLOWED"}, {"BLOCKED", "DENIED", "RISKY", "FORBIDDEN"}),
        ):
            status = _status(value)
            if status not in accepted:
                reasons.append(name + ("_BLOCKED" if status in blocked_values else "_UNKNOWN"))
                if status in blocked_values:
                    blocked = True

    if reasons:
        status = "BLOCKED" if blocked else "UNKNOWN"
        return ReadinessAssessment(status=status, reason_codes=tuple(dict.fromkeys(reasons)),
                                   bundle_id=bundle.decision_id,
                                   evidence_current=False, execution_authority="NONE",
                                   phase5_permit_issued=False)
    return ReadinessAssessment(status="READY", reason_codes=(), bundle_id=bundle.decision_id,
                               evidence_current=True, execution_authority="NONE",
                               phase5_permit_issued=False)


def redirect_revalidation_stamp(bundle: RedirectEvidenceBundle,
                                assessment: ReadinessAssessment) -> RedirectRevalidationStamp:
    frame = bundle.frame
    return RedirectRevalidationStamp(
        bundle_id=assessment.bundle_id, scope_id=frame.scope_id,
        action_epoch=frame.action_epoch, observation_epoch=frame.observation_epoch,
        context_revision=frame.context_revision,
        decision_watermark=frame.decision_watermark,
        graph_state_id=frame.graph_state_ref.state_id if frame.graph_state_ref else "",
        discovery_state_id=frame.discovery_state_ref.state_id if frame.discovery_state_ref else "",
        target_status=bundle.proof_set.target_identity.status,
        readiness_status=assessment.status, permit=False)


@dataclass(frozen=True)
class ProductionProofBuildResult:
    """Fresh read-only API outputs projected into typed contracts."""

    proof_set: TargetProofSet = field(default_factory=TargetProofSet)
    frontier_recommendation: FrozenEvidenceMap = field(default_factory=FrozenEvidenceMap)
    production_target: CanonicalTargetIdentity = field(default_factory=CanonicalTargetIdentity)
    phase4_gate_ref: str = ""
    binding_ref: str = ""
    safety_assessment_ref: str = ""
    build_status: str = "UNKNOWN"
    reason: str = ""

    def __post_init__(self):
        object.__setattr__(self, "frontier_recommendation", _freeze_evidence(self.frontier_recommendation))


class ProductionRedirectProofProvider:
    """Read-only adapter over the existing Phase 4 and Phase 5A APIs.

    It calls plan_shadow, execution_gate, resolve_focus_target, and
    SafetySession.assess. It never calls Phase 5 authorization and never
    produces a permit, dispatch, focus result, or visit credit.
    """

    def build_target_proof_set(self, frame: ProductionEvidenceFrame, planner_input: Any,
                               raw: Mapping[str, Any], *, authority_evidence: Any = None,
                               current_input: Any = None, actions_used: int = 0,
                               degraded: bool = False, action_limit: int = 5) -> ProductionProofBuildResult:
        from tb_runner.canonical_json import canonical_sha256
        from tb_runner.frontier_shadow import production_candidate
        from tb_runner.phase4a_planner import plan_shadow
        from tb_runner.phase4b_authority import AuthorityEvidence, execution_gate
        from tb_runner.phase4b_target_binding import resolve_focus_target
        from tb_runner.phase5a_safety import SafetySession
        from tb_runner.state_graph import build_graph_state_identity
        from tb_runner.exploration_redirect import bridge_production_target_to_current_candidate

        empty_proof = TargetProofSet(provenance=proof_provenance_for(frame)
            if isinstance(frame, ProductionEvidenceFrame) else ProofProvenance())
        if not isinstance(frame, ProductionEvidenceFrame) or not isinstance(raw, Mapping):
            return ProductionProofBuildResult(proof_set=empty_proof,
                build_status="UNKNOWN", reason="FRAME_OR_RAW_OBSERVATION_UNAVAILABLE")
        try:
            snapshot = planner_input.snapshot.to_dict()
            capture = raw.get("_exploration_observation")
            capture = capture if isinstance(capture, Mapping) else {}
            graph_state_id = build_graph_state_identity(raw).state_id or ""
            graph_ref = frame.graph_state_ref
            discovery_ref = frame.discovery_state_ref
            provenance_matches = bool(
                capture.get("capture_complete") is True
                and capture.get("capture_end_action_epoch") == frame.action_epoch
                and capture.get("observation_id") == frame.observation_id
                and capture.get("observation_sequence") == frame.observation_sequence
                and capture.get("scope_id") == frame.scope_id
                and capture.get("action_epoch") == frame.action_epoch
                and capture.get("context_revision") == frame.context_revision
                and isinstance(graph_ref, EvidenceStateReference)
                and graph_ref.identity_domain == "graph_state_ref_v1"
                and graph_ref.state_id == graph_state_id
                and isinstance(discovery_ref, EvidenceStateReference)
                and discovery_ref.identity_domain == "discovery_state_scope_v1"
                and discovery_ref.state_id == snapshot.get("state_id"))
            if provenance_matches:
                for ref in (graph_ref, discovery_ref):
                    provenance_matches = provenance_matches and (
                        ref.observation_id == frame.observation_id
                        and ref.observation_sequence == frame.observation_sequence
                        and ref.scope_id == frame.scope_id
                        and ref.action_epoch == frame.action_epoch
                        and ref.context_revision == frame.context_revision)
            if (type(frame.action_epoch) is not int
                    or frame.observation_epoch != frame.action_epoch):
                provenance_matches = False
            if not provenance_matches:
                return ProductionProofBuildResult(proof_set=empty_proof,
                    build_status="UNKNOWN", reason="PRODUCTION_OBSERVATION_PROVENANCE_MISMATCH")

            recommendation_obj = plan_shadow(planner_input)
            recommendation = recommendation_obj.to_dict()
            if _freeze_evidence(recommendation.get("semantic_substates", [])) != frame.substate:
                return ProductionProofBuildResult(proof_set=empty_proof,
                    build_status="UNKNOWN", reason="PRODUCTION_SUBSTATE_PROVENANCE_MISMATCH")
            target_identity = adapt_discovery_candidate_identity(
                recommendation.get("recommended_target"),
                source_ref=str(recommendation.get("recommended_candidate_id") or ""))
            action = str(recommendation.get("recommended_action") or "")
            candidate_id = str(recommendation.get("recommended_candidate_id") or "")
            planner_status = "ELIGIBLE" if action == "FOCUS_CANDIDATE" and candidate_id else (
                "BLOCKED" if action == "RECOVERY_OR_NONE" else "UNKNOWN")
            current_selected = [candidate for candidate in snapshot.get("candidates", [])
                                if isinstance(candidate, Mapping)
                                and candidate.get("candidate_id") == candidate_id
                                and candidate.get("action_kind") == "FOCUS_TARGET"]
            if len(current_selected) != 1:
                planner_status = "UNKNOWN"
                target_identity = CanonicalTargetIdentity(
                    status="PARTIAL", source_shape="DISCOVERY_CANDIDATE",
                    source_ref=candidate_id, reason="SELECTED_DISCOVERY_CANDIDATE_NOT_UNIQUE")
            else:
                current_identity = adapt_discovery_candidate_identity(
                    current_selected[0], source_ref=candidate_id)
                if compare_canonical_identities(target_identity, current_identity) != "EXACT_MATCH":
                    planner_status = "UNKNOWN"
                target_identity = current_identity

            if isinstance(authority_evidence, AuthorityEvidence):
                gate = execution_gate(planner_input, recommendation_obj,
                    current_input if current_input is not None else planner_input,
                    authority_evidence, actions_used=actions_used, degraded=degraded,
                    action_limit=action_limit)
                gate_status = "ALLOWED" if gate.allowed and gate.mode == "CONTROLLED_TARGET_FOCUS" else "BLOCKED"
                gate_doc = gate.to_dict()
                gate_ref = "phase4b_authority.execution_gate:" + canonical_sha256(gate_doc)
            else:
                gate_status, gate_doc, gate_ref = "UNKNOWN", {}, ""

            binding_node = None
            binding_doc: dict[str, Any] = {}
            binding_status = presence_status = "UNKNOWN"
            if action == "FOCUS_CANDIDATE" and candidate_id:
                try:
                    binding_node, binding_doc = resolve_focus_target(
                        raw, recommendation, planner_input.history.scenario_id)
                    binding_status = "RESOLVED" if binding_node is not None else "UNRESOLVED"
                    presence_status = "PRESENT" if binding_node is not None else "ABSENT"
                except Exception:
                    binding_doc = {}
                    binding_status = presence_status = "UNKNOWN"
            binding_ref = ("phase4b_target_binding.resolve_focus_target:"
                           + canonical_sha256(binding_doc)) if binding_doc else ""

            safety_status = "UNKNOWN"
            safety_doc: Any = None
            try:
                safety_rows = SafetySession(mode="shadow").assess(planner_input, raw)
                matched = [row for row in safety_rows
                           if row.get("candidate_id") == candidate_id
                           and row.get("action_kind") == "FOCUS_TARGET"]
                if len(matched) == 1:
                    safety_doc = matched[0]
                    policy = safety_doc.get("policy") or {}
                    safety_status = "ALLOWED" if policy.get("eligible") is True else "BLOCKED"
            except Exception:
                safety_doc = None
            safety_ref = ("phase5a_safety.SafetySession.assess:"
                          + canonical_sha256(safety_doc)) if safety_doc is not None else ""

            production_target = CanonicalTargetIdentity()
            bridge = IdentityBridgeEvidence()
            if binding_node is not None:
                produced = production_candidate(state_id=graph_state_id,
                    scenario_id=planner_input.history.scenario_id, candidate=binding_node)
                if produced:
                    production_target = adapt_production_frontier_identity(
                        produced, source_ref=str(produced.get("candidate_id") or ""))
                    bridge_result = bridge_production_target_to_current_candidate(
                        produced.get("target_identity") or {}, snapshot.get("candidates", []))
                    bridge = identity_bridge_evidence(produced.get("target_identity") or {},
                                                      bridge_result, source_ref=frame.observation_id)
                    if (bridge.status == "EXACT_ONE"
                            and compare_canonical_identities(
                                target_identity, bridge.candidate_identity) != "EXACT_MATCH"):
                        bridge = IdentityBridgeEvidence(
                            status="UNKNOWN", target_identity=bridge.target_identity,
                            candidate_identity=bridge.candidate_identity,
                            reason="BRIDGE_DOES_NOT_MATCH_PLANNER_CANDIDATE",
                            source_ref=bridge.source_ref)

            refs = {key: value for key, value in (
                ("planner", "phase4a_planner.plan_shadow"),
                ("phase4_gate", gate_ref), ("binding", binding_ref),
                ("presence", binding_ref), ("safety_assessment", safety_ref)) if value}
            proof_refs = {key: canonical_sha256(doc) for key, doc in (
                ("planner", recommendation), ("phase4_gate", gate_doc),
                ("binding", binding_doc), ("safety_assessment", safety_doc or {})) if doc}
            proof_set = TargetProofSet(
                target_identity=target_identity,
                production_target_identity=production_target,
                identity_bridge=bridge,
                planner_status=planner_status,
                phase4_gate_status=gate_status,
                binding_status=binding_status,
                presence_status=presence_status,
                safety_assessment_status=safety_status,
                proof_complete=bool(target_identity.complete and production_target.complete
                    and bridge.status == "EXACT_ONE" and gate_status == "ALLOWED"
                    and binding_status == "RESOLVED" and presence_status == "PRESENT"
                    and safety_status == "ALLOWED"),
                planner_state_id=str(snapshot.get("state_id") or ""),
                proof_refs=FrozenEvidenceMap(tuple(proof_refs.items())),
                source_refs=FrozenEvidenceMap(tuple(refs.items())),
                provenance=proof_provenance_for(frame),
                assessment_kind="PHASE5A_READ_ONLY_ASSESSMENT",
                reasons=tuple(() if safety_status != "UNKNOWN" else ("SAFETY_ASSESSMENT_UNAVAILABLE",)))
            return ProductionProofBuildResult(
                proof_set=proof_set,
                frontier_recommendation=FrozenEvidenceMap(tuple(recommendation.items())),
                production_target=production_target,
                phase4_gate_ref=gate_ref, binding_ref=binding_ref,
                safety_assessment_ref=safety_ref,
                build_status="COMPLETE" if proof_set.proof_complete else "PARTIAL",
                reason="" if proof_set.proof_complete else "PROOF_EVIDENCE_INCOMPLETE")
        except Exception as exc:
            return ProductionProofBuildResult(proof_set=empty_proof,
                build_status="UNKNOWN", reason="PRODUCTION_PROOF_PROVIDER_ERROR:" + type(exc).__name__)


@dataclass(frozen=True)
class RedirectReadinessTraceEvent:
    event_id: str
    run_id: str
    decision_id: str
    event_type: str
    status: str
    reason_codes: tuple[str, ...] = ()
    provenance: ProofProvenance = field(default_factory=ProofProvenance)

    def __post_init__(self):
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True)
class RedirectDispatchTraceEvent:
    event_id: str
    run_id: str
    decision_id: str
    operation_id: str
    request_id: str | None
    receipt_seq: int | None
    dispatch_status: str
    evidence_source: str


@dataclass(frozen=True)
class RedirectOutcomeTraceEvent:
    event_id: str
    run_id: str
    decision_id: str
    production_reconciliation_ref: str
    outcome_status: str
    visit_authority: str = "PRODUCTION_LEDGER_ONLY"
    new_state_authority: str = "FINALIZED_PHASE6_PROGRESS_ONLY"
