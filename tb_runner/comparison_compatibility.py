"""ComparisonCompatibilityKey and compatibility-grade evaluation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from tb_runner.app_version import compare_app_versions, parse_app_version
from tb_runner.canonical_json import canonical_sha256, normalize_canonical_value
from tb_runner.comparator_schema import (
    COMPARISON_COMPATIBILITY_KEY_SCHEMA_VERSION,
    CompatibilityAssessment,
    CompatibilityGrade,
    CompatibilityKeyStatus,
    ComparatorInput,
    ONECONNECT_VERSION_POLICY_ID,
    VersionRelation,
    reason,
)


@dataclass(frozen=True)
class ComparisonCompatibilityKey:
    key_schema: str
    status: CompatibilityKeyStatus
    digest: str | None
    key_source: dict[str, Any]
    missing_fields: tuple[str, ...]
    incompatible_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return normalize_canonical_value(asdict(self))


def _contract_major(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.match(r"^(\d+)(?:\.\d+)*$", text)
    if match:
        return match.group(1)
    match = re.search(r"^(.*?-v\d+)(?:[.+-].*)?$", text)
    if match:
        return match.group(1)
    return text


def _collection_majors(value: Any) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(name): _contract_major(version)
        for name, version in sorted(value.items(), key=lambda item: str(item[0]))
    }


def build_compatibility_key(source: ComparatorInput) -> ComparisonCompatibilityKey:
    environment = source.environment
    parsed_version = parse_app_version(
        environment.get("app_version_name"),
        environment.get("app_version_code"),
    )
    key_source = {
        "key_schema": COMPARISON_COMPATIBILITY_KEY_SCHEMA_VERSION,
        "identity": {
            "app_package": environment.get("app_package"),
            "locale": environment.get("locale"),
        },
        "device_family": {
            "device_family": environment.get("device_family"),
            "form_factor": environment.get("form_factor"),
        },
        "platform_family": {
            "android_major": environment.get("android_major"),
            "one_ui_major": environment.get("one_ui_major"),
            "talkback_package": environment.get("talkback_package"),
            "talkback_major": environment.get("talkback_major"),
        },
        "semantic_contracts": {
            "traversal_contract_major": _contract_major(
                environment.get("traversal_contract")
            ),
            "identity_contract_major": _contract_major(
                environment.get("identity_contract")
            ),
            "collection_contract_majors": _collection_majors(
                environment.get("collection_contract_versions")
            ),
            "core_feature_flags": environment.get("feature_flags") or {},
        },
        "app_policy": {
            "policy_id": ONECONNECT_VERSION_POLICY_ID,
            "release_train": parsed_version.release_train,
        },
    }
    missing: list[str] = []
    for group_name, group in key_source.items():
        if group_name == "key_schema" or not isinstance(group, Mapping):
            continue
        for field_name, value in group.items():
            if value is None or value == {}:
                missing.append(f"{group_name}.{field_name}")
    identity_missing = {
        "identity.app_package",
        "identity.locale",
    }.intersection(missing)
    if identity_missing:
        status = CompatibilityKeyStatus.UNUSABLE
    elif missing:
        status = CompatibilityKeyStatus.INCOMPLETE
    else:
        status = CompatibilityKeyStatus.COMPLETE
    digest = (
        canonical_sha256(key_source)
        if status == CompatibilityKeyStatus.COMPLETE
        else None
    )
    return ComparisonCompatibilityKey(
        key_schema=COMPARISON_COMPATIBILITY_KEY_SCHEMA_VERSION,
        status=status,
        digest=digest,
        key_source=key_source,
        missing_fields=tuple(sorted(missing)),
        incompatible_fields=(),
    )


def _changed(left: Mapping[str, Any], right: Mapping[str, Any], name: str) -> bool:
    return left.get(name) != right.get(name)


def assess_compatibility(
    baseline: ComparatorInput,
    candidate: ComparatorInput,
    *,
    compatible_family_pairs: Iterable[tuple[str, str]] = (),
) -> CompatibilityAssessment:
    baseline_env = baseline.environment
    candidate_env = candidate.environment
    reasons: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []

    baseline_key = build_compatibility_key(baseline)
    candidate_key = build_compatibility_key(candidate)
    if baseline_key.status == CompatibilityKeyStatus.UNUSABLE:
        return CompatibilityAssessment(
            CompatibilityGrade.INCOMPARABLE,
            VersionRelation.UNKNOWN_ORDER,
            (
                reason(
                    "INCOMPLETE_COMPATIBILITY_KEY",
                    side="baseline",
                    missing=list(baseline_key.missing_fields),
                ),
            ),
        )
    if candidate_key.status == CompatibilityKeyStatus.UNUSABLE:
        return CompatibilityAssessment(
            CompatibilityGrade.INCOMPARABLE,
            VersionRelation.UNKNOWN_ORDER,
            (
                reason(
                    "INCOMPLETE_COMPATIBILITY_KEY",
                    side="candidate",
                    missing=list(candidate_key.missing_fields),
                ),
            ),
        )

    if _changed(baseline_env, candidate_env, "app_package"):
        return CompatibilityAssessment(
            CompatibilityGrade.INCOMPARABLE,
            VersionRelation.UNKNOWN_ORDER,
            (reason("APP_PACKAGE_MISMATCH", field="app_package"),),
        )
    if _changed(baseline_env, candidate_env, "locale"):
        return CompatibilityAssessment(
            CompatibilityGrade.INCOMPARABLE,
            VersionRelation.UNKNOWN_ORDER,
            (reason("LOCALE_MISMATCH", field="locale"),),
        )
    if _changed(baseline_env, candidate_env, "form_factor"):
        return CompatibilityAssessment(
            CompatibilityGrade.INCOMPARABLE,
            VersionRelation.UNKNOWN_ORDER,
            (reason("INCOMPATIBLE_FORM_FACTOR", field="form_factor"),),
        )

    for name in ("traversal_contract", "identity_contract"):
        if _contract_major(baseline_env.get(name)) != _contract_major(
            candidate_env.get(name)
        ):
            return CompatibilityAssessment(
                CompatibilityGrade.INCOMPARABLE,
                VersionRelation.UNKNOWN_ORDER,
                (reason("INCOMPATIBLE_SEMANTIC_CONTRACT", field=name),),
            )
    if _collection_majors(
        baseline_env.get("collection_contract_versions")
    ) != _collection_majors(candidate_env.get("collection_contract_versions")):
        return CompatibilityAssessment(
            CompatibilityGrade.INCOMPARABLE,
            VersionRelation.UNKNOWN_ORDER,
            (reason("INCOMPATIBLE_COLLECTION_CONTRACTS"),),
        )

    version = compare_app_versions(
        parse_app_version(
            baseline_env.get("app_version_name"),
            baseline_env.get("app_version_code"),
        ),
        parse_app_version(
            candidate_env.get("app_version_name"),
            candidate_env.get("app_version_code"),
        ),
    )
    reasons.append(
        reason(
            "APP_VERSION_RELATION",
            relation=version.relation.value,
            ordering_basis=version.ordering_basis,
        )
    )

    baseline_family = str(baseline_env.get("device_family") or "")
    candidate_family = str(candidate_env.get("device_family") or "")
    family_pair = (baseline_family, candidate_family)
    compatible_pairs = set(compatible_family_pairs)
    family_changed = baseline_family != candidate_family
    family_compatible = family_pair in compatible_pairs
    if family_changed and not family_compatible:
        review_items.append(reason("DEVICE_FAMILY_POLICY_REQUIRED"))
    elif family_changed:
        reasons.append(reason("VALIDATED_COMPATIBLE_DEVICE_FAMILY"))

    for name in (
        "android_major",
        "one_ui_major",
        "talkback_package",
        "talkback_major",
    ):
        if _changed(baseline_env, candidate_env, name):
            review_items.append(reason("PLATFORM_FAMILY_CHANGED", field=name))

    for name in ("runtime_config_hash", "scenario_registry_hash"):
        if _changed(baseline_env, candidate_env, name):
            review_items.append(reason("RUNTIME_SCENARIO_CONTRACT_CHANGED", field=name))

    if baseline_env.get("feature_flags") != candidate_env.get("feature_flags"):
        review_items.append(reason("COMPARISON_FEATURE_FLAGS_CHANGED"))

    baseline_scenarios = set(baseline.scenario.get("selected_ids") or [])
    candidate_scenarios = set(candidate.scenario.get("selected_ids") or [])
    if baseline_scenarios != candidate_scenarios:
        review_items.append(
            reason(
                "SCENARIO_SET_CHANGED",
                added=sorted(candidate_scenarios - baseline_scenarios),
                removed=sorted(baseline_scenarios - candidate_scenarios),
            )
        )

    if version.relation == VersionRelation.UNKNOWN_ORDER:
        review_items.append(reason("UNKNOWN_VERSION_ORDERING"))
    elif version.relation == VersionRelation.DOWNGRADE:
        review_items.append(reason("APP_VERSION_DOWNGRADE"))
    elif (
        version.baseline.release_train
        and version.candidate.release_train
        and version.baseline.release_train != version.candidate.release_train
    ):
        review_items.append(
            reason(
                "APP_RELEASE_TRAIN_CHANGED",
                baseline=version.baseline.release_train,
                candidate=version.candidate.release_train,
            )
        )

    if (
        baseline_key.status != CompatibilityKeyStatus.COMPLETE
        or candidate_key.status != CompatibilityKeyStatus.COMPLETE
    ):
        review_items.append(
            reason(
                "INCOMPLETE_COMPATIBILITY_KEY",
                baseline_missing=list(baseline_key.missing_fields),
                candidate_missing=list(candidate_key.missing_fields),
            )
        )

    if review_items:
        return CompatibilityAssessment(
            CompatibilityGrade.REVIEW_REQUIRED,
            version.relation,
            tuple(reasons),
            tuple(review_items),
        )
    if family_changed and family_compatible:
        return CompatibilityAssessment(
            CompatibilityGrade.COMPATIBLE_FAMILY,
            version.relation,
            tuple(reasons),
        )
    if (
        version.relation == VersionRelation.SAME
        and baseline.environment_fingerprint.get("fingerprint_source")
        == candidate.environment_fingerprint.get("fingerprint_source")
        and baseline.scenario == candidate.scenario
    ):
        return CompatibilityAssessment(
            CompatibilityGrade.EXACT_MATCH,
            version.relation,
            tuple(reasons),
        )
    if version.relation == VersionRelation.UPGRADE:
        return CompatibilityAssessment(
            CompatibilityGrade.COMPATIBLE_PREDECESSOR,
            version.relation,
            tuple(reasons),
        )
    return CompatibilityAssessment(
        CompatibilityGrade.COMPATIBLE_FAMILY,
        version.relation,
        tuple(reasons),
    )


__all__ = [
    "ComparisonCompatibilityKey",
    "assess_compatibility",
    "build_compatibility_key",
]
