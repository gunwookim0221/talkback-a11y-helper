"""Conservative deterministic Tier 1-3 observation matching."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from tb_runner.observation_schema import CanonicalObservation


def _ref(item: CanonicalObservation) -> dict[str, Any]:
    return {
        "observation_id": item.observation_id,
        "scenario_id": item.scenario_id,
        "step_index": item.step_index,
        "resource_id": item.resource_id,
    }


def _semantic(item: CanonicalObservation) -> str:
    return str(item.normalized_text.get("semantic") or "")


def _compatible(left: CanonicalObservation, right: CanonicalObservation) -> bool:
    left_type = left.role or left.class_name
    right_type = right.role or right.class_name
    return not left_type or not right_type or left_type == right_type


def _tier(
    baseline: CanonicalObservation,
    candidate: CanonicalObservation,
) -> tuple[str | None, str, list[str], list[str]]:
    evidence: list[str] = []
    conflicts: list[str] = []
    if baseline.scenario_id != candidate.scenario_id:
        return None, "INDETERMINATE", evidence, ["SCENARIO_MISMATCH"]
    if baseline.observation_id == candidate.observation_id:
        return (
            "TIER_1_STABLE_EXACT",
            "HIGH",
            ["OBSERVATION_ID_EXACT"],
            conflicts,
        )
    compatible = _compatible(baseline, candidate)
    semantic_equal = bool(_semantic(baseline)) and _semantic(baseline) == _semantic(candidate)
    if (
        baseline.resource_id
        and baseline.resource_id == candidate.resource_id
        and compatible
        and (semantic_equal or not _semantic(baseline) or not _semantic(candidate))
    ):
        evidence.extend(("RESOURCE_ID_EXACT", "CLASS_ROLE_COMPATIBLE"))
        if semantic_equal:
            evidence.append("SEMANTIC_IDENTITY_EXACT")
        return "TIER_1_STABLE_EXACT", "HIGH", evidence, conflicts
    structure_score = 0
    if semantic_equal:
        structure_score += 2
        evidence.append("NORMALIZED_SEMANTIC_EXACT")
    if compatible:
        structure_score += 1
        evidence.append("CLASS_ROLE_COMPATIBLE")
    if baseline.ancestor_signature and baseline.ancestor_signature == candidate.ancestor_signature:
        structure_score += 1
        evidence.append("ANCESTOR_SIGNATURE_EXACT")
    if baseline.bounds_region and baseline.bounds_region == candidate.bounds_region:
        structure_score += 1
        evidence.append("RELATIVE_REGION_EXACT")
    if baseline.focusable == candidate.focusable:
        structure_score += 1
        evidence.append("FOCUSABILITY_COMPATIBLE")
    if structure_score >= 4 and semantic_equal and compatible:
        return "TIER_2_SEMANTIC_STRUCTURE", "MEDIUM", evidence, conflicts
    if baseline.resource_id and candidate.resource_id and baseline.resource_id != candidate.resource_id:
        conflicts.append("RESOURCE_ID_CHANGED")
    step_gap = (
        abs(baseline.step_index - candidate.step_index)
        if baseline.step_index is not None and candidate.step_index is not None
        else 999
    )
    speech_equal = bool(baseline.normalized_speech.get("semantic")) and (
        baseline.normalized_speech.get("semantic")
        == candidate.normalized_speech.get("semantic")
    )
    neighborhood = (
        baseline.sibling_signature
        and baseline.sibling_signature == candidate.sibling_signature
    )
    if compatible and step_gap <= 2 and (semantic_equal or speech_equal or neighborhood):
        evidence.extend(
            item
            for item, active in (
                ("SCENARIO_LOCAL_STEP_NEIGHBORHOOD", step_gap <= 2),
                ("SPEECH_PAIR_EXACT", speech_equal),
                ("SIBLING_NEIGHBORHOOD_EXACT", neighborhood),
            )
            if active
        )
        return "TIER_3_TRAVERSAL_NEIGHBORHOOD", "LOW", evidence, conflicts
    return None, "INDETERMINATE", evidence, conflicts


def _node_delta(left: CanonicalObservation, right: CanonicalObservation) -> str:
    if (left.role or left.class_name) != (right.role or right.class_name):
        return "SAME_NODE_CHANGED_ROLE"
    if _semantic(left) != _semantic(right):
        return "SAME_NODE_CHANGED_LABEL"
    if left.normalized_speech.get("semantic") != right.normalized_speech.get("semantic"):
        return "SAME_NODE_CHANGED_SPEECH"
    if (
        left.selected,
        left.checked,
        left.enabled,
        left.state_description,
    ) != (
        right.selected,
        right.checked,
        right.enabled,
        right.state_description,
    ):
        return "SAME_NODE_CHANGED_STATE"
    if left.bounds != right.bounds:
        return "SAME_NODE_CHANGED_BOUNDS"
    if left.step_index != right.step_index:
        return "SAME_NODE_CHANGED_ORDER"
    return "SAME_NODE_UNCHANGED"


def _tie_score(left: CanonicalObservation, right: CanonicalObservation) -> int:
    return sum(
        (
            16 if left.observation_id == right.observation_id else 0,
            8 if left.transaction_id and left.transaction_id == right.transaction_id else 0,
            4 if left.request_id and left.request_id == right.request_id else 0,
            3 if left.step_index == right.step_index else 0,
            2 if left.bounds and left.bounds == right.bounds else 0,
            1 if left.parent_signature and left.parent_signature == right.parent_signature else 0,
            1 if left.sibling_signature and left.sibling_signature == right.sibling_signature else 0,
        )
    )


def match_observations(
    baseline: Iterable[CanonicalObservation],
    candidate: Iterable[CanonicalObservation],
) -> list[dict[str, Any]]:
    left = list(baseline)
    right = list(candidate)
    proposals: dict[int, list[tuple[int, str, str, list[str], list[str]]]] = defaultdict(list)
    ranks = {
        "TIER_1_STABLE_EXACT": 1,
        "TIER_2_SEMANTIC_STRUCTURE": 2,
        "TIER_3_TRAVERSAL_NEIGHBORHOOD": 3,
    }
    for li, base in enumerate(left):
        candidates = []
        for ri, cand in enumerate(right):
            tier, confidence, evidence, conflicts = _tier(base, cand)
            if tier:
                candidates.append((ri, tier, confidence, evidence, conflicts))
        if candidates:
            best_rank = min(ranks[item[1]] for item in candidates)
            best = [item for item in candidates if ranks[item[1]] == best_rank]
            best_score = max(_tie_score(base, right[item[0]]) for item in best)
            proposals[li] = [
                item for item in best
                if _tie_score(base, right[item[0]]) == best_score
            ]

    results: list[dict[str, Any]] = []
    used_right: set[int] = set()
    ambiguous_left: set[int] = set()
    for li in sorted(proposals):
        options = [item for item in proposals[li] if item[0] not in used_right]
        if len(options) != 1:
            ambiguous_left.add(li)
            results.append(
                {
                    "match_type": "AMBIGUOUS",
                    "node_delta": "AMBIGUOUS_MATCH",
                    "confidence": "INDETERMINATE",
                    "baseline": _ref(left[li]),
                    "candidate": None,
                    "supporting_evidence": [],
                    "conflicting_evidence": ["MULTIPLE_EQUIVALENT_CANDIDATES"],
                    "ambiguity": True,
                    "rejected_alternatives": [_ref(right[item[0]]) for item in options],
                }
            )
            continue
        ri, tier, confidence, evidence, conflicts = options[0]
        competing = [
            other_li for other_li, choices in proposals.items()
            if other_li != li and any(choice[0] == ri and choice[1] == tier for choice in choices)
        ]
        if competing:
            ambiguous_left.add(li)
            results.append(
                {
                    "match_type": "AMBIGUOUS",
                    "node_delta": "AMBIGUOUS_MATCH",
                    "confidence": "INDETERMINATE",
                    "baseline": _ref(left[li]),
                    "candidate": _ref(right[ri]),
                    "supporting_evidence": evidence,
                    "conflicting_evidence": ["MANY_TO_ONE_CANDIDATE"],
                    "ambiguity": True,
                    "rejected_alternatives": [_ref(left[index]) for index in competing],
                }
            )
            continue
        used_right.add(ri)
        results.append(
            {
                "match_type": tier,
                "node_delta": _node_delta(left[li], right[ri]),
                "confidence": confidence,
                "baseline": _ref(left[li]),
                "candidate": _ref(right[ri]),
                "supporting_evidence": evidence,
                "conflicting_evidence": conflicts,
                "ambiguity": False,
                "rejected_alternatives": [
                    _ref(right[item[0]]) for item in proposals[li] if item[0] != ri
                ],
            }
        )

    unmatched_left = [
        index for index in range(len(left))
        if index not in proposals and index not in ambiguous_left
    ]
    unmatched_right = [index for index in range(len(right)) if index not in used_right]
    left_semantics = Counter((left[i].scenario_id, _semantic(left[i])) for i in unmatched_left)
    right_semantics = Counter((right[i].scenario_id, _semantic(right[i])) for i in unmatched_right)
    for li in unmatched_left:
        key = (left[li].scenario_id, _semantic(left[li]))
        split = bool(key[1]) and left_semantics[key] == 1 and right_semantics[key] > 1
        results.append(
            {
                "match_type": "SPLIT" if split else "UNMATCHED",
                "node_delta": "SPLIT_NODE" if split else "REMOVED_NODE",
                "confidence": "LOW" if split else "HIGH",
                "baseline": _ref(left[li]),
                "candidate": None,
                "supporting_evidence": ["ONE_TO_MANY_SEMANTIC_COHORT"] if split else [],
                "conflicting_evidence": [],
                "ambiguity": False,
                "rejected_alternatives": [],
            }
        )
    for ri in unmatched_right:
        key = (right[ri].scenario_id, _semantic(right[ri]))
        merged = bool(key[1]) and right_semantics[key] == 1 and left_semantics[key] > 1
        results.append(
            {
                "match_type": "MERGED" if merged else "UNMATCHED",
                "node_delta": "MERGED_NODE" if merged else "ADDED_NODE",
                "confidence": "LOW" if merged else "HIGH",
                "baseline": None,
                "candidate": _ref(right[ri]),
                "supporting_evidence": ["MANY_TO_ONE_SEMANTIC_COHORT"] if merged else [],
                "conflicting_evidence": [],
                "ambiguity": False,
                "rejected_alternatives": [],
            }
        )
    return sorted(
        results,
        key=lambda item: (
            (item["baseline"] or item["candidate"] or {}).get("scenario_id", ""),
            (item["baseline"] or item["candidate"] or {}).get("step_index") or -1,
            item["node_delta"],
        ),
    )


__all__ = ["match_observations"]
