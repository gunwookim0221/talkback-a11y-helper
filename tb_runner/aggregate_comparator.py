"""Aggregate-only comparison for Phase 10.3B (no node/text/speech matching)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from tb_runner.app_version import compare_app_versions, parse_app_version
from tb_runner.comparator_schema import AggregateStatus, ComparatorInput


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _delta(baseline: Any, candidate: Any) -> float:
    return _number(candidate) - _number(baseline)


def _status(value: AggregateStatus) -> str:
    return value.value


def compare_environment(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> tuple[dict[str, Any], dict[str, Any]]:
    left = baseline.environment
    right = candidate.environment
    fields = (
        "app_package",
        "locale",
        "android_major",
        "one_ui_major",
        "talkback_package",
        "talkback_major",
        "device_family",
        "form_factor",
        "traversal_contract",
        "identity_contract",
        "runtime_config_hash",
        "normalized_runtime_config_hash",
        "scenario_registry_hash",
    )
    changes = {
        name: {"baseline": left.get(name), "candidate": right.get(name)}
        for name in fields
        if left.get(name) != right.get(name)
    }
    left_flags = _mapping(left.get("feature_flags"))
    right_flags = _mapping(right.get("feature_flags"))
    flag_names = sorted(set(left_flags) | set(right_flags))
    flag_delta = {
        name: {"baseline": left_flags.get(name), "candidate": right_flags.get(name)}
        for name in flag_names
        if left_flags.get(name) != right_flags.get(name)
    }
    contracts_changed = (
        left.get("traversal_contract") != right.get("traversal_contract")
        or left.get("identity_contract") != right.get("identity_contract")
        or left.get("collection_contract_versions")
        != right.get("collection_contract_versions")
    )
    review_fields = {
        "android_major",
        "one_ui_major",
        "talkback_package",
        "talkback_major",
        "runtime_config_hash",
        "scenario_registry_hash",
    }
    status = (
        AggregateStatus.REVIEW_REQUIRED
        if contracts_changed or review_fields.intersection(changes) or flag_delta
        else AggregateStatus.STRUCTURAL_CHANGE
        if changes
        else AggregateStatus.UNCHANGED
    )
    environment_delta = {
        "status": _status(status),
        "changes": changes,
        "feature_flag_delta": flag_delta,
        "collection_contract_delta": {
            "baseline": left.get("collection_contract_versions") or {},
            "candidate": right.get("collection_contract_versions") or {},
            "changed": left.get("collection_contract_versions")
            != right.get("collection_contract_versions"),
        },
    }
    version = compare_app_versions(
        parse_app_version(left.get("app_version_name"), left.get("app_version_code")),
        parse_app_version(
            right.get("app_version_name"), right.get("app_version_code")
        ),
    )
    return environment_delta, version.to_dict()


def compare_scenarios(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    left_ids = list(baseline.scenario.get("selected_ids") or [])
    right_ids = list(candidate.scenario.get("selected_ids") or [])
    left_set = set(left_ids)
    right_set = set(right_ids)
    added = sorted(right_set - left_set)
    removed = sorted(left_set - right_set)
    common = sorted(left_set & right_set)
    order_changed = left_ids != right_ids
    order_only = order_changed and left_set == right_set
    executed_delta = _delta(
        baseline.scenario.get("executed_count"),
        candidate.scenario.get("executed_count"),
    )
    terminal_delta = _delta(
        baseline.scenario.get("terminal_count"),
        candidate.scenario.get("terminal_count"),
    )
    if terminal_delta < 0 or executed_delta < 0:
        status = AggregateStatus.REGRESSED
    elif added or removed or order_changed:
        status = AggregateStatus.STRUCTURAL_CHANGE
    else:
        status = AggregateStatus.UNCHANGED
    return {
        "status": _status(status),
        "added_scenarios": added,
        "removed_scenarios": removed,
        "common_scenarios": common,
        "order_changed": order_changed,
        "order_only_change": order_only,
        "executed_delta": executed_delta,
        "terminal_delta": terminal_delta,
        "baseline": baseline.scenario,
        "candidate": candidate.scenario,
    }


def _scenario_totals(summary: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    values = summary.get("scenarios")
    if not isinstance(values, list):
        return {}
    result: dict[str, dict[str, float]] = {}
    for item in values:
        if not isinstance(item, Mapping):
            continue
        scenario_id = item.get("scenario_id") or item.get("id")
        if not scenario_id:
            continue
        result[str(scenario_id)] = {
            "expected": _number(item.get("expected_count")),
            "covered": _number(item.get("covered_count")),
            "missed": _number(item.get("missed_count")),
            "unknown": _number(item.get("unknown_count")),
        }
    return result


def _coverage_totals(summary: Mapping[str, Any]) -> dict[str, float]:
    return {
        "expected": _number(summary.get("expected_count")),
        "covered": _number(summary.get("covered_count")),
        "missed": _number(summary.get("missed_count")),
        "unknown": _number(summary.get("unknown_count")),
    }


def _sum_scenarios(
    scenarios: Mapping[str, Mapping[str, float]],
    ids: Iterable[str],
) -> dict[str, float]:
    result = {"expected": 0.0, "covered": 0.0, "missed": 0.0, "unknown": 0.0}
    for scenario_id in ids:
        values = scenarios.get(scenario_id, {})
        for name in result:
            result[name] += _number(values.get(name))
    return result


def compare_coverage(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
    scenario_delta: Mapping[str, Any],
) -> dict[str, Any]:
    left = _mapping(baseline.aggregates.get("coverage"))
    right = _mapping(candidate.aggregates.get("coverage"))
    if left.get("available") is not True or right.get("available") is not True:
        return {
            "status": _status(AggregateStatus.DATA_UNAVAILABLE),
            "reason": "COVERAGE_SUMMARY_UNAVAILABLE",
        }
    left_totals = _coverage_totals(left)
    right_totals = _coverage_totals(right)
    totals_delta = {
        name: right_totals[name] - left_totals[name] for name in left_totals
    }
    common_ids = scenario_delta.get("common_scenarios") or []
    left_scenarios = _scenario_totals(left)
    right_scenarios = _scenario_totals(right)
    left_common = _sum_scenarios(left_scenarios, common_ids)
    right_common = _sum_scenarios(right_scenarios, common_ids)
    common_delta = {
        name: right_common[name] - left_common[name] for name in left_common
    }
    denominator_changed = totals_delta["expected"] != 0
    structural = bool(
        denominator_changed
        or scenario_delta.get("added_scenarios")
        or scenario_delta.get("removed_scenarios")
    )
    added_common_denominator = max(common_delta["expected"], 0)
    unexplained_missed_increase = (
        common_delta["missed"] > added_common_denominator
    )
    unexplained_unknown_increase = (
        common_delta["unknown"] > added_common_denominator
    )
    if (
        common_delta["covered"] < 0
        or unexplained_missed_increase
        or unexplained_unknown_increase
    ):
        status = AggregateStatus.REGRESSED
    elif (
        common_delta["covered"] > 0
        and common_delta["missed"] <= 0
        and common_delta["unknown"] <= 0
    ):
        status = AggregateStatus.IMPROVED
    elif structural:
        status = AggregateStatus.STRUCTURAL_CHANGE
    else:
        status = AggregateStatus.UNCHANGED
    baseline_rate = (
        left_totals["covered"] / left_totals["expected"]
        if left_totals["expected"]
        else None
    )
    candidate_rate = (
        right_totals["covered"] / right_totals["expected"]
        if right_totals["expected"]
        else None
    )
    return {
        "status": _status(status),
        "baseline_totals": left_totals,
        "candidate_totals": right_totals,
        "totals_delta": totals_delta,
        "baseline_rate": baseline_rate,
        "candidate_rate": candidate_rate,
        "rate_delta": (
            candidate_rate - baseline_rate
            if baseline_rate is not None and candidate_rate is not None
            else None
        ),
        "denominator_changed": denominator_changed,
        "structural_change": structural,
        "common_scenario_baseline": left_common,
        "common_scenario_candidate": right_common,
        "common_scenario_delta": common_delta,
        "scenario_delta": {
            scenario_id: {
                name: right_scenarios.get(scenario_id, {}).get(name, 0)
                - left_scenarios.get(scenario_id, {}).get(name, 0)
                for name in ("expected", "covered", "missed", "unknown")
            }
            for scenario_id in common_ids
        },
    }


def _identity_counts(summary: Mapping[str, Any]) -> dict[str, float]:
    completeness = _mapping(summary.get("completeness"))
    verdicts = _mapping(summary.get("verdicts"))
    return {
        "transactions": _number(summary.get("transaction_count")),
        "complete": _number(completeness.get("COMPLETE")),
        "partial": _number(completeness.get("PARTIAL")),
        "indeterminate": max(
            _number(completeness.get("INDETERMINATE")),
            _number(verdicts.get("INDETERMINATE")),
        ),
    }


def compare_identity(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    left = _mapping(baseline.aggregates.get("identity"))
    right = _mapping(candidate.aggregates.get("identity"))
    if left.get("available") is not True or right.get("available") is not True:
        return {
            "status": _status(AggregateStatus.DATA_UNAVAILABLE),
            "reason": "IDENTITY_SUMMARY_UNAVAILABLE",
        }
    baseline_counts = _identity_counts(left)
    candidate_counts = _identity_counts(right)
    deltas = {
        name: candidate_counts[name] - baseline_counts[name]
        for name in baseline_counts
    }
    baseline_ratio = (
        baseline_counts["complete"] / baseline_counts["transactions"]
        if baseline_counts["transactions"]
        else None
    )
    candidate_ratio = (
        candidate_counts["complete"] / candidate_counts["transactions"]
        if candidate_counts["transactions"]
        else None
    )
    if deltas["indeterminate"] > 0 or deltas["partial"] > 0:
        status = AggregateStatus.REGRESSED
    elif deltas["indeterminate"] < 0 or deltas["partial"] < 0:
        status = AggregateStatus.IMPROVED
    elif any(value != 0 for value in deltas.values()):
        status = AggregateStatus.STRUCTURAL_CHANGE
    else:
        status = AggregateStatus.UNCHANGED
    return {
        "status": _status(status),
        "baseline_counts": baseline_counts,
        "candidate_counts": candidate_counts,
        "count_delta": deltas,
        "baseline_complete_ratio": baseline_ratio,
        "candidate_complete_ratio": candidate_ratio,
        "complete_ratio_delta": (
            candidate_ratio - baseline_ratio
            if baseline_ratio is not None and candidate_ratio is not None
            else None
        ),
    }


def _run_scenarios(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    scenarios = run.get("scenarios")
    return [item for item in scenarios if isinstance(item, Mapping)] if isinstance(
        scenarios, list
    ) else []


def _stop_distribution(run: Mapping[str, Any]) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                str(item.get("stop_reason") or "NONE")
                for item in _run_scenarios(run)
            ).items()
        )
    )


def compare_traversal(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    left_run = _mapping(baseline.aggregates.get("run"))
    right_run = _mapping(candidate.aggregates.get("run"))
    left_recon = _mapping(baseline.aggregates.get("reconciliation"))
    right_recon = _mapping(candidate.aggregates.get("reconciliation"))
    left_steps = sum(_number(item.get("steps")) for item in _run_scenarios(left_run))
    right_steps = sum(_number(item.get("steps")) for item in _run_scenarios(right_run))
    baseline_values = {
        "steps": left_steps,
        "terminal": _number(left_run.get("terminal_scenarios")),
        "executed": _number(left_run.get("executed_scenarios")),
        "anchor_abort": _number(left_recon.get("anchor_abort_count")),
        "repeat_no_progress": sum(
            1
            for item in _run_scenarios(left_run)
            if item.get("stop_reason") == "repeat_no_progress"
        ),
    }
    candidate_values = {
        "steps": right_steps,
        "terminal": _number(right_run.get("terminal_scenarios")),
        "executed": _number(right_run.get("executed_scenarios")),
        "anchor_abort": _number(right_recon.get("anchor_abort_count")),
        "repeat_no_progress": sum(
            1
            for item in _run_scenarios(right_run)
            if item.get("stop_reason") == "repeat_no_progress"
        ),
    }
    deltas = {
        name: candidate_values[name] - baseline_values[name]
        for name in baseline_values
    }
    left_stop = _stop_distribution(left_run)
    right_stop = _stop_distribution(right_run)
    if deltas["terminal"] < 0 or deltas["executed"] < 0 or deltas["anchor_abort"] > 0:
        status = AggregateStatus.REGRESSED
    elif deltas["anchor_abort"] < 0:
        status = AggregateStatus.IMPROVED
    elif any(value != 0 for value in deltas.values()) or left_stop != right_stop:
        status = AggregateStatus.STRUCTURAL_CHANGE
    else:
        status = AggregateStatus.UNCHANGED
    return {
        "status": _status(status),
        "baseline": baseline_values,
        "candidate": candidate_values,
        "delta": deltas,
        "baseline_stop_reason_distribution": left_stop,
        "candidate_stop_reason_distribution": right_stop,
    }


def compare_recovery(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    left = _mapping(baseline.aggregates.get("recovery"))
    right = _mapping(candidate.aggregates.get("recovery"))
    if left.get("available") is not True or right.get("available") is not True:
        return {
            "status": _status(AggregateStatus.DATA_UNAVAILABLE),
            "reason": "RECOVERY_SUMMARY_UNAVAILABLE",
        }
    names = ("attempts", "recovered", "failed")
    baseline_values = {name: _number(left.get(name)) for name in names}
    candidate_values = {name: _number(right.get(name)) for name in names}
    deltas = {
        name: candidate_values[name] - baseline_values[name] for name in names
    }
    if deltas["failed"] > 0:
        status = AggregateStatus.REGRESSED
    elif deltas["failed"] < 0 or deltas["recovered"] > 0:
        status = AggregateStatus.IMPROVED
    elif any(value != 0 for value in deltas.values()):
        status = AggregateStatus.STRUCTURAL_CHANGE
    else:
        status = AggregateStatus.UNCHANGED
    return {
        "status": _status(status),
        "baseline": baseline_values,
        "candidate": candidate_values,
        "delta": deltas,
        "baseline_failure_distribution": left.get("result_distribution") or {},
        "candidate_failure_distribution": right.get("result_distribution") or {},
    }


def compare_reconciliation(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    left = _mapping(baseline.aggregates.get("reconciliation"))
    right = _mapping(candidate.aggregates.get("reconciliation"))
    names = (
        "orphan_count",
        "duplicate_event_count",
        "write_failure_count",
        "anchor_abort_count",
    )
    deltas = {name: _delta(left.get(name), right.get(name)) for name in names}
    regressed = right.get("status") != "PASS" or any(value > 0 for value in deltas.values())
    improved = (
        left.get("status") != "PASS"
        and right.get("status") == "PASS"
        and not regressed
    )
    status = (
        AggregateStatus.REGRESSED
        if regressed
        else AggregateStatus.IMPROVED
        if improved
        else AggregateStatus.UNCHANGED
        if left.get("status") == right.get("status") and not any(deltas.values())
        else AggregateStatus.STRUCTURAL_CHANGE
    )
    return {
        "status": _status(status),
        "baseline_status": left.get("status"),
        "candidate_status": right.get("status"),
        "integrity_delta": deltas,
    }


def _profiler_values(summary: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = summary.get("scenarios")
    items = [item for item in scenarios if isinstance(item, Mapping)] if isinstance(
        scenarios, list
    ) else []
    scenario_runtime = {
        str(item.get("scenario_id")): _number(item.get("runtime_ms"))
        for item in items
        if item.get("scenario_id")
    }
    metric_totals: dict[str, dict[str, float]] = {}
    for item in items:
        metrics = item.get("metrics")
        if not isinstance(metrics, Mapping):
            continue
        for name, raw in metrics.items():
            if not isinstance(raw, Mapping):
                continue
            target = metric_totals.setdefault(
                str(name), {"count": 0.0, "duration_ms": 0.0}
            )
            target["count"] += _number(raw.get("count"))
            target["duration_ms"] += _number(raw.get("duration_ms"))
    return {
        "total_runtime_ms": sum(scenario_runtime.values()),
        "scenario_runtime_ms": scenario_runtime,
        "metrics": metric_totals,
    }


def compare_profiler(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    left = _mapping(baseline.aggregates.get("profiler"))
    right = _mapping(candidate.aggregates.get("profiler"))
    if left.get("available") is not True or right.get("available") is not True:
        return {
            "status": _status(AggregateStatus.DATA_UNAVAILABLE),
            "reason": "PROFILER_SUMMARY_UNAVAILABLE",
        }
    baseline_values = _profiler_values(left)
    candidate_values = _profiler_values(right)
    runtime_delta = (
        candidate_values["total_runtime_ms"] - baseline_values["total_runtime_ms"]
    )
    metric_names = sorted(
        set(baseline_values["metrics"]) | set(candidate_values["metrics"])
    )
    metric_delta = {
        name: {
            field: candidate_values["metrics"].get(name, {}).get(field, 0)
            - baseline_values["metrics"].get(name, {}).get(field, 0)
            for field in ("count", "duration_ms")
        }
        for name in metric_names
    }
    bottleneck = max(
        metric_delta,
        key=lambda name: metric_delta[name]["duration_ms"],
        default=None,
    )
    status = (
        AggregateStatus.REGRESSED
        if runtime_delta > 0
        else AggregateStatus.IMPROVED
        if runtime_delta < 0
        else AggregateStatus.STRUCTURAL_CHANGE
        if any(any(value != 0 for value in item.values()) for item in metric_delta.values())
        else AggregateStatus.UNCHANGED
    )
    return {
        "status": _status(status),
        "accessibility_verdict_effect": "NONE",
        "baseline": baseline_values,
        "candidate": candidate_values,
        "total_runtime_delta_ms": runtime_delta,
        "metric_delta": metric_delta,
        "major_bottleneck_delta": {
            "metric": bottleneck,
            "duration_delta_ms": (
                metric_delta[bottleneck]["duration_ms"] if bottleneck else 0
            ),
        },
    }


def _limitation_bindings(source: ComparatorInput) -> tuple[set[str], int]:
    issue_ids = {
        str(item.get("issue_id"))
        for item in source.reviewed_limitations
        if item.get("issue_id")
    }
    return issue_ids, len(source.reviewed_limitations)


def compare_limitations(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    left_ids, left_count = _limitation_bindings(baseline)
    right_ids, right_count = _limitation_bindings(candidate)
    added = sorted(right_ids - left_ids)
    removed = sorted(left_ids - right_ids)
    status = (
        AggregateStatus.STRUCTURAL_CHANGE
        if added or removed or left_count != right_count
        else AggregateStatus.UNCHANGED
    )
    return {
        "status": _status(status),
        "baseline_issue_ids": sorted(left_ids),
        "candidate_issue_ids": sorted(right_ids),
        "added_issue_ids": added,
        "removed_issue_ids": removed,
        "baseline_binding_count": left_count,
        "candidate_binding_count": right_count,
        "binding_count_delta": right_count - left_count,
        "raw_failure_suppression_applied": False,
        "exact_signature_matching": "DEFERRED_TO_PHASE_10_3C",
    }


def compare_aggregates(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
) -> dict[str, Any]:
    environment_delta, app_version_delta = compare_environment(baseline, candidate)
    scenario_delta = compare_scenarios(baseline, candidate)
    return {
        "environment_delta": environment_delta,
        "app_version_delta": app_version_delta,
        "scenario_delta": scenario_delta,
        "coverage_aggregate_delta": compare_coverage(
            baseline, candidate, scenario_delta
        ),
        "identity_aggregate_delta": compare_identity(baseline, candidate),
        "traversal_aggregate_delta": compare_traversal(baseline, candidate),
        "recovery_aggregate_delta": compare_recovery(baseline, candidate),
        "reconciliation_delta": compare_reconciliation(baseline, candidate),
        "profiler_aggregate_delta": compare_profiler(baseline, candidate),
        "limitation_summary_delta": compare_limitations(baseline, candidate),
    }


__all__ = [
    "compare_aggregates",
    "compare_coverage",
    "compare_environment",
    "compare_identity",
    "compare_limitations",
    "compare_profiler",
    "compare_reconciliation",
    "compare_recovery",
    "compare_scenarios",
    "compare_traversal",
]
