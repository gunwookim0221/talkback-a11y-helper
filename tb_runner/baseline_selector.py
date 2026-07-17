"""Read-only active/historical Approved Baseline discovery and selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tb_runner.app_version import parse_app_version
from tb_runner.canonical_json import canonical_sha256
from tb_runner.comparison_compatibility import assess_compatibility
from tb_runner.comparison_input import adapt_approved_baseline
from tb_runner.comparator_schema import (
    CompatibilityAssessment,
    CompatibilityGrade,
    ComparatorContractError,
    ComparatorInput,
    SelectionResult,
    VersionRelation,
    reason,
)


@dataclass(frozen=True)
class BaselineDiscoveryRecord:
    package_path: Path
    baseline_id: str
    state: str
    expected_checksums: dict[str, str]
    input: ComparatorInput | None
    errors: tuple[dict[str, Any], ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_lifecycle(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = root / "lifecycle.jsonl"
    events: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.is_file():
        return [], [reason("LIFECYCLE_MISSING")]
    previous: str | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return [], [reason("LIFECYCLE_CORRUPT")]
    for line_number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append(reason("LIFECYCLE_CORRUPT", line=line_number))
            continue
        if not isinstance(event, dict):
            errors.append(reason("LIFECYCLE_CORRUPT", line=line_number))
            continue
        source = {
            key: value
            for key, value in event.items()
            if key not in {"event_id", "event_hash"}
        }
        expected = canonical_sha256(source)
        actual = str(event.get("event_hash") or "")
        if actual != expected or event.get("previous_event_hash") != previous:
            errors.append(reason("LIFECYCLE_HASH_CHAIN_MISMATCH", line=line_number))
        previous = actual
        events.append(event)
    return events, errors


def _lifecycle_state(
    events: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    states: dict[str, str] = {}
    checksums: dict[str, dict[str, str]] = {}
    for event in events:
        event_type = event.get("event_type")
        baseline_id = str(event.get("baseline_id") or "")
        if event_type == "APPROVED" and baseline_id:
            supersedes = str(event.get("supersedes") or "")
            if supersedes:
                states[supersedes] = "SUPERSEDED"
            states[baseline_id] = "APPROVED"
            raw_checksums = event.get("core_checksums")
            checksums[baseline_id] = (
                {
                    str(name): str(value)
                    for name, value in raw_checksums.items()
                }
                if isinstance(raw_checksums, Mapping)
                else {}
            )
        elif event_type == "SUPERSEDED" and baseline_id:
            states[baseline_id] = "SUPERSEDED"
        elif event_type == "ARCHIVED" and baseline_id:
            states[baseline_id] = "ARCHIVED"
    return states, checksums


def discover_baselines_read_only(
    repository_root: str | Path,
) -> tuple[tuple[BaselineDiscoveryRecord, ...], tuple[dict[str, Any], ...]]:
    root = Path(repository_root)
    events, lifecycle_errors = _read_lifecycle(root)
    states, checksum_map = _lifecycle_state(events)
    records: list[BaselineDiscoveryRecord] = []
    for package in sorted(root.glob("*/baseline_*")):
        if not package.is_dir():
            continue
        baseline_path = package / "baseline.json"
        baseline_id = package.name
        state = states.get(baseline_id, "ORPHANED")
        errors: list[dict[str, Any]] = list(lifecycle_errors)
        expected = checksum_map.get(baseline_id, {})
        for filename in (
            "baseline.json",
            "environment_profile.json",
            "artifact_manifest.json",
        ):
            path = package / filename
            expected_digest = expected.get(filename)
            if not path.is_file():
                errors.append(reason("BASELINE_CORE_MISSING", file=filename))
            elif not expected_digest:
                errors.append(reason("BASELINE_CORE_CHECKSUM_MISSING", file=filename))
            elif _sha256_file(path) != expected_digest:
                errors.append(reason("BASELINE_CORE_CHECKSUM_MISMATCH", file=filename))
        adapted: ComparatorInput | None = None
        if not errors and state in {"APPROVED", "SUPERSEDED"}:
            try:
                adapted = adapt_approved_baseline(package, repository_state=state)
            except ComparatorContractError as exc:
                errors.append(exc.to_dict())
        records.append(
            BaselineDiscoveryRecord(
                package,
                baseline_id,
                state,
                expected,
                adapted,
                tuple(errors),
            )
        )
    return tuple(records), tuple(lifecycle_errors)


def _reference(source: ComparatorInput, state: str) -> dict[str, Any]:
    return {
        "baseline_id": source.source_id,
        "revision": source.provenance.get("revision"),
        "repository_state": state,
        "app_version_name": source.environment.get("app_version_name"),
        "app_version_code": source.environment.get("app_version_code"),
        "locale": source.environment.get("locale"),
    }


def _rank(
    source: ComparatorInput,
    assessment: CompatibilityAssessment,
    state: str,
) -> tuple[Any, ...]:
    grade_rank = {
        CompatibilityGrade.EXACT_MATCH: 5,
        CompatibilityGrade.COMPATIBLE_PREDECESSOR: 4,
        CompatibilityGrade.COMPATIBLE_FAMILY: 3,
    }.get(assessment.grade, 0)
    parsed = parse_app_version(
        source.environment.get("app_version_name"),
        source.environment.get("app_version_code"),
    )
    numeric = parsed.normalized_numeric_tuple or ()
    code = parsed.version_code if parsed.version_code is not None else -1
    revision = int(source.provenance.get("revision") or 0)
    approved_at = str(source.provenance.get("approved_at") or "")
    return (
        grade_rank,
        1 if state == "APPROVED" else 0,
        numeric,
        code,
        revision,
        approved_at,
    )


def select_discovered_baselines(
    candidate: ComparatorInput,
    records: tuple[BaselineDiscoveryRecord, ...],
    *,
    discovery_errors: tuple[dict[str, Any], ...] = (),
) -> SelectionResult:
    rejected: list[dict[str, Any]] = []
    eligible: list[
        tuple[
            tuple[Any, ...],
            BaselineDiscoveryRecord,
            ComparatorInput,
            CompatibilityAssessment,
        ]
    ] = []
    review_assessments: list[tuple[BaselineDiscoveryRecord, CompatibilityAssessment]] = []

    for record in records:
        if record.state == "ARCHIVED":
            rejected.append(
                {
                    "baseline_id": record.baseline_id,
                    "state": record.state,
                    "reasons": [reason("ARCHIVED_BASELINE_EXCLUDED")],
                }
            )
            continue
        if record.errors or record.input is None:
            rejected.append(
                {
                    "baseline_id": record.baseline_id,
                    "state": record.state,
                    "reasons": list(record.errors)
                    or [reason("BASELINE_NOT_APPROVED")],
                }
            )
            continue
        assessment = assess_compatibility(record.input, candidate)
        if assessment.grade == CompatibilityGrade.INCOMPARABLE:
            rejected.append(
                {
                    "baseline_id": record.baseline_id,
                    "state": record.state,
                    "compatibility_grade": assessment.grade.value,
                    "version_relation": assessment.version_relation.value,
                    "reasons": list(assessment.reasons),
                }
            )
            continue
        if (
            assessment.grade == CompatibilityGrade.REVIEW_REQUIRED
            or assessment.version_relation
            in {VersionRelation.DOWNGRADE, VersionRelation.UNKNOWN_ORDER}
        ):
            review_assessments.append((record, assessment))
            rejected.append(
                {
                    "baseline_id": record.baseline_id,
                    "state": record.state,
                    "compatibility_grade": assessment.grade.value,
                    "version_relation": assessment.version_relation.value,
                    "reasons": list(assessment.reasons)
                    + list(assessment.review_items),
                }
            )
            continue
        eligible.append(
            (
                _rank(record.input, assessment, record.state),
                record,
                record.input,
                assessment,
            )
        )

    if not eligible:
        if review_assessments:
            assessment = review_assessments[0][1]
            return SelectionResult(
                None,
                None,
                CompatibilityAssessment(
                    CompatibilityGrade.REVIEW_REQUIRED,
                    assessment.version_relation,
                    assessment.reasons,
                    assessment.review_items,
                ),
                (),
                tuple(rejected),
                False,
                tuple(discovery_errors),
            )
        return SelectionResult(
            None,
            None,
            CompatibilityAssessment(
                CompatibilityGrade.INCOMPARABLE,
                VersionRelation.UNKNOWN_ORDER,
                (reason("NO_COMPARABLE_BASELINE"),),
            ),
            (),
            tuple(rejected),
            False,
            tuple(discovery_errors)
            + (() if records else (reason("NO_BASELINE"),)),
        )

    eligible.sort(key=lambda item: item[0], reverse=True)
    top_rank = eligible[0][0]
    tied = [item for item in eligible if item[0] == top_rank]
    if len(tied) > 1:
        for _, record, _, assessment in tied:
            rejected.append(
                {
                    "baseline_id": record.baseline_id,
                    "state": record.state,
                    "compatibility_grade": assessment.grade.value,
                    "version_relation": assessment.version_relation.value,
                    "reasons": [reason("MULTIPLE_BASELINE_TIE")],
                }
            )
        return SelectionResult(
            None,
            None,
            CompatibilityAssessment(
                CompatibilityGrade.REVIEW_REQUIRED,
                tied[0][3].version_relation,
                (reason("MULTIPLE_BASELINE_TIE"),),
                (reason("MANUAL_BASELINE_SELECTION_REQUIRED"),),
            ),
            (),
            tuple(rejected),
            True,
            tuple(discovery_errors),
        )

    _, record, selected, assessment = eligible[0]
    for _, other_record, _, other_assessment in eligible[1:]:
        rejected.append(
            {
                "baseline_id": other_record.baseline_id,
                "state": other_record.state,
                "compatibility_grade": other_assessment.grade.value,
                "version_relation": other_assessment.version_relation.value,
                "reasons": [reason("LOWER_SELECTION_RANK")],
            }
        )
    rationale = (
        reason("APP_PACKAGE_EXACT"),
        reason("LOCALE_EXACT"),
        reason(
            "BASELINE_SELECTED",
            state=record.state,
            grade=assessment.grade.value,
            version_relation=assessment.version_relation.value,
        ),
    )
    return SelectionResult(
        selected,
        _reference(selected, record.state),
        assessment,
        rationale,
        tuple(rejected),
        False,
        tuple(discovery_errors),
    )


def select_baseline(
    candidate: ComparatorInput,
    repository_root: str | Path,
) -> SelectionResult:
    records, discovery_errors = discover_baselines_read_only(repository_root)
    return select_discovered_baselines(
        candidate,
        records,
        discovery_errors=discovery_errors,
    )


__all__ = [
    "BaselineDiscoveryRecord",
    "discover_baselines_read_only",
    "select_discovered_baselines",
    "select_baseline",
]
