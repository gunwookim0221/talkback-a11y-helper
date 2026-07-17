"""Conservative One Connect version parsing and predecessor ordering."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from tb_runner.canonical_json import normalize_canonical_value
from tb_runner.comparator_schema import (
    ONECONNECT_VERSION_POLICY_ID,
    VersionRelation,
)


_DOTTED_NUMERIC = re.compile(r"^\d+(?:\.\d+)+$")


@dataclass(frozen=True)
class ParsedAppVersion:
    raw_version_name: str | None
    normalized_numeric_tuple: tuple[int, ...] | None
    numeric_ordering_available: bool
    release_train: str | None
    version_code: int | None
    scheme: str
    policy_id: str = ONECONNECT_VERSION_POLICY_ID

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))


@dataclass(frozen=True)
class AppVersionComparison:
    baseline: ParsedAppVersion
    candidate: ParsedAppVersion
    relation: VersionRelation
    ordering_basis: str
    confidence: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))


def _version_code(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def parse_app_version(
    version_name: Any,
    version_code: Any = None,
) -> ParsedAppVersion:
    raw = str(version_name).strip() if version_name is not None else ""
    raw_value = raw or None
    numeric: tuple[int, ...] | None = None
    scheme = "MISSING" if not raw else "OPAQUE"
    release_train: str | None = None
    if raw and _DOTTED_NUMERIC.fullmatch(raw):
        numeric = tuple(int(part) for part in raw.split("."))
        scheme = "DOTTED_NUMERIC"
        if len(numeric) >= 2:
            release_train = f"{numeric[0]}.{numeric[1]}"
    return ParsedAppVersion(
        raw_version_name=raw_value,
        normalized_numeric_tuple=numeric,
        numeric_ordering_available=numeric is not None,
        release_train=release_train,
        version_code=_version_code(version_code),
        scheme=scheme,
    )


def compare_app_versions(
    baseline: ParsedAppVersion,
    candidate: ParsedAppVersion,
) -> AppVersionComparison:
    reasons: list[str] = []

    if (
        baseline.raw_version_name == candidate.raw_version_name
        and baseline.version_code == candidate.version_code
    ):
        return AppVersionComparison(
            baseline,
            candidate,
            VersionRelation.SAME,
            "VERSION_NAME_AND_CODE",
            "HIGH",
            (),
        )

    numeric_relation: VersionRelation | None = None
    if (
        baseline.normalized_numeric_tuple is not None
        and candidate.normalized_numeric_tuple is not None
    ):
        if candidate.normalized_numeric_tuple > baseline.normalized_numeric_tuple:
            numeric_relation = VersionRelation.UPGRADE
        elif candidate.normalized_numeric_tuple < baseline.normalized_numeric_tuple:
            numeric_relation = VersionRelation.DOWNGRADE
        else:
            numeric_relation = VersionRelation.SAME

    code_relation: VersionRelation | None = None
    if baseline.version_code is not None and candidate.version_code is not None:
        if candidate.version_code > baseline.version_code:
            code_relation = VersionRelation.UPGRADE
        elif candidate.version_code < baseline.version_code:
            code_relation = VersionRelation.DOWNGRADE
        else:
            code_relation = VersionRelation.SAME

    if numeric_relation is not None:
        if (
            code_relation is not None
            and numeric_relation != VersionRelation.SAME
            and code_relation not in {numeric_relation, VersionRelation.SAME}
        ):
            reasons.append("VERSION_NAME_CODE_ORDER_CONFLICT")
            return AppVersionComparison(
                baseline,
                candidate,
                VersionRelation.UNKNOWN_ORDER,
                "CONFLICT",
                "LOW",
                tuple(reasons),
            )
        if numeric_relation == VersionRelation.SAME and code_relation is not None:
            reasons.append("SAME_VERSION_NAME_DIFFERENT_VERSION_CODE")
            return AppVersionComparison(
                baseline,
                candidate,
                code_relation,
                "VERSION_CODE",
                "HIGH",
                tuple(reasons),
            )
        return AppVersionComparison(
            baseline,
            candidate,
            numeric_relation,
            "DOTTED_NUMERIC",
            "HIGH",
            tuple(reasons),
        )

    if baseline.raw_version_name == candidate.raw_version_name and code_relation is not None:
        reasons.append("OPAQUE_OR_UNPARSED_NAME_ORDERED_BY_VERSION_CODE")
        return AppVersionComparison(
            baseline,
            candidate,
            code_relation,
            "VERSION_CODE",
            "MEDIUM",
            tuple(reasons),
        )

    if code_relation is not None and code_relation != VersionRelation.SAME:
        reasons.append("NON_STANDARD_VERSION_ORDERED_BY_VERSION_CODE")
        return AppVersionComparison(
            baseline,
            candidate,
            code_relation,
            "VERSION_CODE",
            "MEDIUM",
            tuple(reasons),
        )

    reasons.append("VERSION_ORDER_UNAVAILABLE")
    return AppVersionComparison(
        baseline,
        candidate,
        VersionRelation.UNKNOWN_ORDER,
        "NONE",
        "LOW",
        tuple(reasons),
    )


def version_distance(
    baseline: ParsedAppVersion,
    candidate: ParsedAppVersion,
) -> tuple[int, ...] | None:
    """Return a sortable candidate-baseline distance for numeric predecessors."""
    left = baseline.normalized_numeric_tuple
    right = candidate.normalized_numeric_tuple
    if left is None or right is None:
        if baseline.version_code is None or candidate.version_code is None:
            return None
        return (candidate.version_code - baseline.version_code,)
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    return tuple(r - l for l, r in zip(padded_left, padded_right))


__all__ = [
    "AppVersionComparison",
    "ParsedAppVersion",
    "compare_app_versions",
    "parse_app_version",
    "version_distance",
]
