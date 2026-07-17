"""Deterministic Phase 10.3D comparison replay orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tb_runner.comparison_input import adapt_candidate
from tb_runner.comparator_core import (
    compare_selected_inputs,
    run_comparator_core,
)
from tb_runner.comparator_schema import ComparatorInput
from tb_runner.comparison_report import (
    canonical_report_json,
    render_markdown_report,
)
from tb_runner.verdict_engine import finalize_comparison_result


_REPLAY_EPOCH = "1970-01-01T00:00:00.000Z"


@dataclass(frozen=True)
class ComparisonReplay:
    result: dict[str, Any]
    canonical_json: str
    markdown: str


def _evaluation_at(
    candidate: ComparatorInput,
    baseline: ComparatorInput | None = None,
) -> str:
    return str(
        candidate.provenance.get("created_at")
        or (baseline.provenance.get("approved_at") if baseline else None)
        or _REPLAY_EPOCH
    )


def _replay(result: Mapping[str, Any]) -> ComparisonReplay:
    finalized = finalize_comparison_result(result)
    return ComparisonReplay(
        finalized,
        canonical_report_json(finalized),
        render_markdown_report(finalized),
    )


def replay_selected_inputs(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
    *,
    repository_root: str | Path = ".",
) -> ComparisonReplay:
    result = compare_selected_inputs(
        baseline,
        candidate,
        repository_root=repository_root,
        generated_at=_evaluation_at(candidate, baseline),
    )
    return _replay(result)


def run_comparison_replay(
    candidate_source: str | Path | Mapping[str, Any] | ComparatorInput,
    repository_root: str | Path,
    *,
    environment_profile: str | Path | Mapping[str, Any] | None = None,
) -> ComparisonReplay:
    candidate = (
        candidate_source
        if isinstance(candidate_source, ComparatorInput)
        else adapt_candidate(
            candidate_source,
            environment_profile=environment_profile,
        )
    )
    result = run_comparator_core(
        candidate,
        repository_root,
        generated_at=_evaluation_at(candidate),
    )
    return _replay(result)


__all__ = [
    "ComparisonReplay",
    "replay_selected_inputs",
    "run_comparison_replay",
]
