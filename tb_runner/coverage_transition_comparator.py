"""Scenario-local coverage common-cohort transitions."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from tb_runner.observation_schema import CanonicalObservation


def _status(value: str) -> str:
    upper = str(value or "UNKNOWN").upper()
    return upper if upper in {"COVERED", "MISSED"} else "UNKNOWN"


def compare_coverage_transitions(
    matches: Iterable[dict[str, Any]],
    baseline: Iterable[CanonicalObservation],
    candidate: Iterable[CanonicalObservation],
) -> dict[str, Any]:
    left = {item.observation_id: item for item in baseline}
    right = {item.observation_id: item for item in candidate}
    rows: list[dict[str, Any]] = []
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for match in matches:
        bref = match.get("baseline") or {}
        cref = match.get("candidate") or {}
        base = left.get(bref.get("observation_id"))
        cand = right.get(cref.get("observation_id"))
        scenario = (base or cand).scenario_id if (base or cand) else ""
        if match.get("ambiguity"):
            transition = "AMBIGUOUS_COHORT"
        elif base is None:
            transition = "ADDED_CANDIDATE"
        elif cand is None:
            transition = "REMOVED_CANDIDATE"
        else:
            transition = f"{_status(base.coverage_status)} \u2192 {_status(cand.coverage_status)}"
        rows.append(
            {
                "scenario_id": scenario,
                "transition": transition,
                "baseline_observation_id": base.observation_id if base else None,
                "candidate_observation_id": cand.observation_id if cand else None,
                "baseline_coverage_signature": base.coverage_signature if base else None,
                "candidate_coverage_signature": cand.coverage_signature if cand else None,
            }
        )
        counts[scenario][transition] += 1
    return {
        "transitions": rows,
        "by_scenario": {
            scenario: dict(sorted(counter.items()))
            for scenario, counter in sorted(counts.items())
        },
    }


__all__ = ["compare_coverage_transitions"]
