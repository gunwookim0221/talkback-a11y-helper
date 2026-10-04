"""Conservative, deterministic Phase 2B equality. No runtime control or I/O."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
import json
import re
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.state_observation import StateObservation, observation_problems

EQUALITY_SCHEMA = "state-equality-v1"
IDENTITY_SCHEMA = "logical-state-identity-v1"
SCROLL_EVIDENCE_SCHEMA = "state-scroll-continuity-v1"


class EqualityVerdict(str, Enum):
    SAME = "SAME"
    DIFFERENT = "DIFFERENT"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class StateIdentity:
    """Allocated/persisted logical ID; scope_index_key is only a coarse index."""
    state_id: str
    scope_index_key: str
    schema_version: str = IDENTITY_SCHEMA


@dataclass(frozen=True)
class StateEqualityResult:
    verdict: EqualityVerdict
    base_verdict: EqualityVerdict
    viewport_equal: bool | None
    overlay_equal: bool | None
    reasons: tuple[str, ...]
    matching_components: tuple[str, ...]
    differing_components: tuple[str, ...]
    confidence: str
    _diagnostic_json: str = field(repr=False)
    schema_version: str = EQUALITY_SCHEMA

    @property
    def logical_state_equal(self) -> bool | None:
        return None if self.verdict == EqualityVerdict.AMBIGUOUS else self.verdict == EqualityVerdict.SAME

    @property
    def base_state_equal(self) -> bool | None:
        return None if self.base_verdict == EqualityVerdict.AMBIGUOUS else self.base_verdict == EqualityVerdict.SAME

    def to_dict(self) -> dict[str, Any]:
        return dict(schema_version=self.schema_version, verdict=self.verdict.value,
                    base_verdict=self.base_verdict.value, logical_state_equal=self.logical_state_equal,
                    base_state_equal=self.base_state_equal, viewport_equal=self.viewport_equal,
                    overlay_equal=self.overlay_equal, reasons=list(self.reasons),
                    matching_components=list(self.matching_components), differing_components=list(self.differing_components),
                    confidence=self.confidence, diagnostic=json.loads(self._diagnostic_json))

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True)
class VerifiedScrollEvidence:
    before_observation_id: str
    after_observation_id: str
    _document_json: str = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._document_json)

    def links(self, left: StateObservation, right: StateObservation) -> bool:
        return {left.observation_id, right.observation_id} == {self.before_observation_id, self.after_observation_id}

    @classmethod
    def from_transition(cls, before: StateObservation, after: StateObservation,
                        transition: Mapping[str, Any]) -> "VerifiedScrollEvidence":
        bp = before.fingerprint.to_dict()["transient"].get("legacy_viewport") or {}
        ap = after.fingerprint.to_dict()["transient"].get("legacy_viewport") or {}
        tb, ta = transition.get("before", {}), transition.get("after", {})
        if not (transition.get("status") == "SCROLL_MOVED" and transition.get("action_success") is True
                and transition.get("viewport_changed") is True and bp.get("valid") is True and ap.get("valid") is True
                and bp.get("signature") == tb.get("signature") and ap.get("signature") == ta.get("signature")
                and bp.get("signature") != ap.get("signature") and before.observation_id != after.observation_id
                and before.fingerprint.viewport_signature != after.fingerprint.viewport_signature):
            raise ValueError("scroll continuity requires linked observed movement, not an ACK")
        cap = transition.get("capability_before", {})
        container = cap.get("container") or {}
        if cap.get("axis") not in {"VERTICAL", "BIDIRECTIONAL"} or cap.get("contradictory") is True:
            raise ValueError("scroll continuity requires verified vertical scope")
        doc = dict(schema_version=SCROLL_EVIDENCE_SCHEMA, kind="VERIFIED_SCROLL",
                   before_observation_id=before.observation_id, after_observation_id=after.observation_id,
                   before_viewport_signature=bp["signature"], after_viewport_signature=ap["signature"],
                   axis=cap["axis"], container_path=container.get("path"), source=cap.get("source"),
                   action_success=True, viewport_changed=True, movement_status="SCROLL_MOVED")
        return cls(before.observation_id, after.observation_id, canonical_json(doc))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], observations: Mapping[str, StateObservation]) -> "VerifiedScrollEvidence":
        if value.get("schema_version") != SCROLL_EVIDENCE_SCHEMA or value.get("kind") != "VERIFIED_SCROLL":
            raise ValueError("incompatible scroll evidence")
        try:
            before, after = (observations[value[k]] for k in ("before_observation_id", "after_observation_id"))
        except KeyError as exc:
            raise ValueError("orphan scroll evidence") from exc
        transition = dict(status=value.get("movement_status"), action_success=value.get("action_success"),
                          viewport_changed=value.get("viewport_changed"),
                          before=dict(signature=value.get("before_viewport_signature")),
                          after=dict(signature=value.get("after_viewport_signature")),
                          capability_before=dict(axis=value.get("axis"), source=value.get("source"),
                                                 container=dict(path=value.get("container_path"))))
        return cls.from_transition(before, after, transition)


def scope_index_key(observation: StateObservation) -> str:
    core = observation.fingerprint.to_dict()["core"]
    return canonical_sha256({key: core.get(key) for key in (
        "package_name", "activity_name", "navigation_context", "selected_tab")})


def _matching_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize one observed typed age field on both live and saved evidence.

    Life map_area says 'recent location check: 59 minutes ago', then '1 hour
    ago'. Keep device name, state words and every other label discriminator.
    Comparison-time normalization preserves old sidecars and fingerprint bytes.
    """
    result = []
    for node in nodes:
        label = node["label"]
        if str(node["semantic"].get("resource_id") or "").endswith("/map_area"):
            label = re.sub(r"(최근 위치 확인\s*:\s*)(?:지금|방금|(?:\d+\s*(?:일|시간|분|초)\s*)+전)(?=\s*(?:,|$))", r"\1<location_age>", label)
            label = re.sub(r"(last location (?:update|check|seen)\s*:\s*)(?:now|just now|(?:\d+\s*(?:days?|hours?|minutes?|seconds?)\s*)+ago)(?=\s*(?:,|$))", r"\1<location_age>", label)
        result.append(dict(node,label=label))
    return sorted(result,key=canonical_json)


def _aligned_state_changes(left_nodes: list, right_nodes: list) -> tuple[bool, bool]:
    """Compare only unambiguous same-position structural correspondences.

    Changes elsewhere may be new viewport content; never infer logical object
    identity merely from a shared resource ID. Unknown flags are ambiguous.
    """
    def groups(nodes):
        result = defaultdict(list)
        for node in nodes:
            sem = node["semantic"]
            key = canonical_json({k: sem.get(k) for k in ("resource_id", "class_name", "role", "layout_bucket")})
            result[key].append(node)
        return result
    ag, bg = groups(left_nodes), groups(right_nodes)
    changed, unknown = False, False
    for key in ag.keys() & bg.keys():
        if len(ag[key]) != 1 or len(bg[key]) != 1:
            # Neutral duplicated layout containers can appear/disappear during
            # scrolling. Counts belong to viewport, not a guessed object match.
            # A changed set of meaningful states remains ambiguous.
            def states(nodes):
                return {canonical_json(dict(value=n.get("semantic_value"),
                    state=n["semantic"].get("semantic_state"), description=n["semantic"].get("state_description"),
                    flags={f: n["semantic"].get("flags", {}).get(f) for f in ("enabled", "checked", "selected")})) for n in nodes}
            if states(ag[key]) != states(bg[key]):
                unknown = True
            continue
        a, b = ag[key][0], bg[key][0]
        av, bv = a["semantic"], b["semantic"]
        for field in ("semantic_value",):
            if a.get(field) != b.get(field):
                if a.get(field) is None or b.get(field) is None:
                    unknown = True
                else:
                    changed = True
        for field in ("semantic_state", "state_description"):
            if av.get(field) != bv.get(field):
                if av.get(field) is None or bv.get(field) is None:
                    unknown = True
                else:
                    changed = True
        for field in ("enabled", "checked", "selected"):
            aa, bb = av.get("flags", {}).get(field), bv.get("flags", {}).get(field)
            if aa != bb:
                if aa is None or bb is None:
                    unknown = True
                else:
                    changed = True
    return changed, unknown


def evaluate_state_equality(left: StateObservation, right: StateObservation,
                            continuity: VerifiedScrollEvidence | None = None) -> StateEqualityResult:
    """SAME is scoped to observed components, never whole-app completeness."""
    if not isinstance(left, StateObservation) or not isinstance(right, StateObservation):
        raise TypeError("equality requires StateObservation secondary evidence, not a bare hash")
    a, b = left.fingerprint.to_dict(), right.fingerprint.to_dict()
    sa, sb = left.secondary, right.secondary
    sa["nodes"], sb["nodes"] = _matching_nodes(sa["nodes"]), _matching_nodes(sb["nodes"])
    matches, differences, reasons = [], [], []
    viewport_equal = a["viewport"] == b["viewport"]
    overlay_equal = a["overlay"] == b["overlay"] and sa["overlay_nodes"] == sb["overlay_nodes"]
    problems = sorted(set(observation_problems(left) + observation_problems(right)))
    hard_changed = []
    for field in ("package_name", "activity_name", "navigation_context", "selected_tab"):
        av, bv = a["core"].get(field), b["core"].get(field)
        (matches if av == bv else differences).append(field)
        if av and bv and av != bv:
            hard_changed.append(field)
    for field in ("environment_partition",):
        av, bv = sa.get(field), sb.get(field)
        if av != bv:
            differences.append(field)
            if av is not None and bv is not None:
                hard_changed.append(field)
            else:
                problems.append("MISSING_ENVIRONMENT_PARTITION")
    if a["core"].get("normalization_version") != b["core"].get("normalization_version"):
        problems.append("INCOMPATIBLE_NORMALIZATION")
    if left.coverage != right.coverage:
        problems.append("COVERAGE_MISMATCH")
    (matches if viewport_equal else differences).append("viewport")
    (matches if overlay_equal else differences).append("overlay")
    (matches if sa["nodes"] == sb["nodes"] else differences).append("secondary_semantics")
    if hard_changed:
        base = EqualityVerdict.DIFFERENT
        reasons.append("HARD_SCOPE_CHANGED")
    elif problems:
        base = EqualityVerdict.AMBIGUOUS
        reasons.extend(problems)
    elif a["core"]["screen_markers"] != b["core"]["screen_markers"]:
        base = EqualityVerdict.DIFFERENT
        differences.append("persistent_markers")
        reasons.append("OBSERVED_PERSISTENT_MARKERS_CHANGED")
    else:
        changed, unknown = _aligned_state_changes(sa["nodes"], sb["nodes"])
        if changed:
            base = EqualityVerdict.DIFFERENT
            reasons.append("MEANINGFUL_SEMANTIC_STATE_CHANGED")
        elif unknown:
            base = EqualityVerdict.AMBIGUOUS
            reasons.append("SEMANTIC_AVAILABILITY_OR_INSTANCE_AMBIGUITY")
        elif sa["markers"] != sb["markers"]:
            base = EqualityVerdict.AMBIGUOUS
            reasons.append("PERSISTENT_LABEL_COLLISION_OR_LOCALE_CHANGE")
        elif sa["nodes"] == sb["nodes"]:
            base = EqualityVerdict.SAME
            reasons.append("OBSERVED_SEMANTIC_MULTISET_MATCH")
        elif continuity is not None and continuity.links(left, right):
            base = EqualityVerdict.SAME
            reasons.append("LINKED_VERIFIED_SCROLL_CONTINUITY")
        else:
            base = EqualityVerdict.AMBIGUOUS
            reasons.append("COARSE_CORE_MATCH_WITHOUT_SECONDARY_CONTINUITY")
    # A demonstrated overlay is a distinct interaction state on a related base.
    if base == EqualityVerdict.SAME and not overlay_equal:
        if a["overlay"].get("observed") is True or b["overlay"].get("observed") is True:
            verdict = EqualityVerdict.DIFFERENT
            reasons.append("OBSERVED_OVERLAY_CHANGED")
        else:
            verdict = EqualityVerdict.AMBIGUOUS
            reasons.append("OVERLAY_AVAILABILITY_CHANGED")
    else:
        verdict = base
    if not a["overlay"].get("observed") and a["overlay"].get("kind") == "unknown":
        reasons.append("OVERLAY_ABSENCE_UNPROVEN")
    diagnostic = dict(left_observation_id=left.observation_id, right_observation_id=right.observation_id,
                      left_fingerprint_hash=left.fingerprint.fingerprint_hash,
                      right_fingerprint_hash=right.fingerprint.fingerprint_hash,
                      same_coarse_core=left.fingerprint.core_signature == right.fingerprint.core_signature,
                      coverage=[left.coverage, right.coverage],
                      continuity_used="LINKED_VERIFIED_SCROLL_CONTINUITY" in reasons)
    return StateEqualityResult(verdict, base, viewport_equal, overlay_equal, tuple(sorted(set(reasons))),
                               tuple(sorted(set(matches))), tuple(sorted(set(differences))),
                               "AMBIGUOUS" if verdict == EqualityVerdict.AMBIGUOUS else "BOUNDED_OBSERVED",
                               canonical_json(diagnostic))
