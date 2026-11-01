"""Conservative positional aliases, separate from actual accessibility visits.

Absence alone never retires an obligation. A relocation must be one-to-one in
both fresh frames and supported by a multi-object vertical translation cohort.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
from typing import Mapping

from tb_runner.traversal_reliability import normalized, normalized_bounds
from tb_runner.utils import parse_bounds_str


def structural_signature(item, include_label=True):
    b=parse_bounds_str(normalized_bounds(item.get("bounds")))
    if not b: return None
    # Stable logical IDs can support a changed state label; path alone can be
    # recycled and is deliberately not treated as a logical object ID.
    stable=item.get("stable_logical_id")
    label=normalized(item.get("label")) if include_label and not stable else ""
    return (normalized(item.get("view_id")),label,normalized(item.get("class_name")),
            normalized(item.get("role")),item.get("focusable"),item.get("clickable"),
            b[2]-b[0],b[3]-b[1],item.get("ancestor_id", ""),stable)


def relocation_cohort(before, after):
    old,new=defaultdict(list),defaultdict(list)
    for key,item in before.items(): old[structural_signature(item)].append((key,item))
    for key,item in after.items(): new[structural_signature(item)].append((key,item))
    pairs=[]
    for signature,items in old.items():
        matches=new.get(signature,[])
        if signature is None or len(items)!=1 or len(matches)!=1: continue
        a,ai=items[0]; b,bi=matches[0]
        if a==b or a in after or b in before: continue
        ab,bb=parse_bounds_str(ai["bounds"]),parse_bounds_str(bi["bounds"])
        dx,dy=bb[0]-ab[0],bb[1]-ab[1]
        if abs(dy)>=24 or abs(dx)>=24:
            pairs.append((a,b,dx,dy,signature))
    counts=Counter((p[2],p[3]) for p in pairs)
    if not counts: return [],dict(axis="UNKNOWN",confidence="insufficient_persisted_objects",matched_objects=0)
    vector,count=counts.most_common(1)[0]
    if count<3 or count/len(pairs)<.6:
        return [],dict(axis="UNKNOWN",confidence="incoherent_translation",matched_objects=count)
    selected=[p for p in pairs if p[2:4]==vector]
    axis="VERTICAL" if abs(vector[1])>=24 and abs(vector[0])<=16 else "HORIZONTAL" if abs(vector[0])>=24 and abs(vector[1])<=16 else "UNKNOWN"
    return selected if axis=="VERTICAL" else [],dict(axis=axis,confidence="multi_object_translation",matched_objects=count,
                         median_delta_x=vector[0],median_delta_y=vector[1],coherent_fraction=count/len(pairs))


def _verified_visit_scroll(evidence, expected_scope):
    """Whether Phase6E bound this relocation to one current native scroll."""
    if not isinstance(evidence, Mapping):
        return False
    owner = evidence.get("owner")
    if not isinstance(owner, Mapping) or not isinstance(expected_scope, tuple) or len(expected_scope) != 3:
        return False
    owner_scope = (
        str(owner.get("class_name") or "").strip(),
        str(owner.get("resource_id") or "").strip(),
        str(owner.get("axis") or "").strip().upper(),
    )
    lifecycle_scope = (
        str(expected_scope[0] or "").strip(),
        str(expected_scope[1] or "").strip(),
        str(expected_scope[2] or "").strip().upper(),
    )
    if owner_scope != lifecycle_scope:
        return False
    source_capture = str(evidence.get("source_capture_id") or "").strip()
    result_capture = str(evidence.get("result_capture_id") or "").strip()
    source_state = str(evidence.get("source_state_id") or "").strip()
    result_state = str(evidence.get("result_state_id") or "").strip()
    request_id = str(evidence.get("action_request_id") or "").strip()
    result_request_id = str(evidence.get("result_request_id") or "").strip()
    return bool(
        evidence.get("schema_version") == "phase6e-scroll-evidence.v1"
        and evidence.get("classification") == "SCROLL_MOVED"
        and evidence.get("valid_for_edge") is True
        and evidence.get("owner_status") == "RESOLVED"
        and evidence.get("action_type") in {"SCROLL_FORWARD", "SCROLL_BACKWARD"}
        and request_id and result_request_id == request_id
        and evidence.get("action_result_correlated") is True
        and evidence.get("dispatch_receipt_correlated") is True
        and evidence.get("action_dispatched") is True
        and evidence.get("action_success") is True
        and evidence.get("source_capture_current") is True
        and evidence.get("result_capture_current") is True
        and evidence.get("capture_linked_to_invocation") is True
        and source_capture and result_capture and source_capture != result_capture
        and source_state and result_state
        and evidence.get("meaningful_change") is True
        and evidence.get("boundary") is not True
    )


def classify_visit_identity(actual_id, visited_ids, aliases=None, alias_provenance=None):
    """Compare visit IDs through only scroll-verified relocation aliases.

    A proven alias can establish that a newly positioned actual-focus ID is an
    already visited instance. An unverified alias match is ambiguous and must
    fail closed; a candidate or movement alone never grants a visit.
    """
    actual = str(actual_id or "").strip()
    if not actual:
        return "UNAVAILABLE"
    visited = {str(value or "").strip() for value in visited_ids or ()
               if str(value or "").strip()}
    if actual in visited:
        return "ALREADY_VISITED"
    aliases = aliases if isinstance(aliases, Mapping) else {}
    provenance = alias_provenance if isinstance(alias_provenance, Mapping) else {}

    def resolve(value):
        current = value
        proven = True
        seen = set()
        while current in aliases:
            if current in seen:
                return current, False
            seen.add(current)
            proven = proven and provenance.get(current) == "VERIFIED_PHASE6E_SCROLL"
            successor = str(aliases.get(current) or "").strip()
            if not successor:
                return current, False
            current = successor
        return current, proven

    actual_target, actual_proven = resolve(actual)
    for prior in visited:
        prior_target, prior_proven = resolve(prior)
        if prior_target == actual_target:
            return "ALREADY_VISITED" if actual_proven and prior_proven else "AMBIGUOUS"
    return "NEW_VISIT"


@dataclass
class CandidateLifecycle:
    previous: dict = field(default_factory=dict)
    previous_scope: tuple = ()
    aliases: dict = field(default_factory=dict)
    visit_alias_provenance: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    origins: dict = field(default_factory=dict)
    last_seen: dict = field(default_factory=dict)
    viewport_index: int = -1
    previous_ids: set = field(default_factory=set)
    last_movement: dict = field(default_factory=dict)

    def observe(self, current, capability, step, valid=True, scope_verified=True,
                visit_scroll_evidence=None):
        changes=[]
        if not valid or not scope_verified:
            # Missing frames cannot prove movement, scope, or alias freshness.
            self.previous={}; self.previous_scope=(); self.last_movement={}
            for key in self.aliases:
                self.visit_alias_provenance[key] = "UNVERIFIED_RELOCATION"
            return changes
        ids=set(current)
        if ids!=self.previous_ids:
            self.viewport_index+=1
        for key in ids:
            self.origins.setdefault(key,self.viewport_index)
            self.last_seen[key]=self.viewport_index
            if key in self.aliases:
                successor=self.aliases.pop(key)
                self.visit_alias_provenance.pop(key, None)
                changes.append(dict(old_instance=key,new_instance=successor,relation="REACTIVATED_CURRENT_INSTANCE",step_index=step,confidence="fresh_presence"))
        container=capability.get("container") or {}
        scope=(container.get("className"),container.get("viewIdResourceName"),container.get("axis"))
        eligible_axis=container.get("axis") in {"VERTICAL","BIDIRECTIONAL"}
        if self.previous and scope != self.previous_scope:
            for key in self.aliases:
                self.visit_alias_provenance[key] = "UNVERIFIED_RELOCATION"
        self.last_movement={}
        if self.previous and scope==self.previous_scope and eligible_axis:
            pairs,movement=relocation_cohort(self.previous,current)
            self.last_movement=movement
            for old,new,dx,dy,signature in pairs:
                self.aliases[old]=new
                self.visit_alias_provenance[old] = (
                    "VERIFIED_PHASE6E_SCROLL" if _verified_visit_scroll(visit_scroll_evidence, scope)
                    else "UNVERIFIED_RELOCATION"
                )
                changes.append(dict(old_instance=old,new_instance=new,relation="RELOCATED_AFTER_SCROLL",
                    confidence="multi_object_translation_and_unique_structure",step_index=step,
                    movement=movement,container_scope=scope,
                    logical_signature=hashlib.sha256(json.dumps(signature,default=str).encode()).hexdigest(),
                    visit_identity_provenance=self.visit_alias_provenance[old],
                    origin_viewport=self.origins[old],last_seen_viewport=self.last_seen[old],replacement_viewport=self.viewport_index))
        self.previous=dict(current); self.previous_scope=scope; self.previous_ids=ids
        self.events.extend(changes)
        return changes

    def successor(self,key):
        seen=set()
        while key in self.aliases and key not in seen:
            seen.add(key); key=self.aliases[key]
        return key

    def covered_targets(self, witnessed):
        return {self.successor(key) for key in witnessed}

    def lifecycle_records(self, records, visited, semantic):
        result=[]
        for key,item in records.items():
            state="VISITED" if key in visited else "SEMANTICALLY_COVERED" if key in semantic else "STALE" if key in self.aliases else "ACTIVE"
            result.append(dict(item,lifecycle=state,stale_alias=key in self.aliases,
                replacement_instance=self.aliases.get(key),logical_target=self.successor(key),
                origin_viewport=self.origins.get(key),last_seen_viewport=self.last_seen.get(key),current_presence=key in self.previous_ids))
        return result
