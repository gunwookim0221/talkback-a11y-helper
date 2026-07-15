"""Offline BaselineCandidate builder for fresh and historical full-run artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from tb_runner.baseline_candidate import ApprovalEligibility, BaselineCandidate
from tb_runner.baseline_candidate_schema import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    BASELINE_CANDIDATE_SCHEMA_VERSION,
    CANDIDATE_NORMALIZER_VERSION,
    COMPARISON_CONTRACT_VERSION,
    SCENARIO_SET_SCHEMA_VERSION,
    ApprovalState,
)
from tb_runner.baseline_candidate_validator import validate_baseline_candidate
from tb_runner.canonical_json import canonical_json_bytes, canonical_sha256
from tb_runner.environment_fingerprint import (
    ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
    build_environment_fingerprint,
    document_digest_reference,
)
from tb_runner.environment_profile import ENVIRONMENT_PROFILE_SCHEMA_VERSION
from tb_runner.environment_validator import parse_package_metadata
from tb_runner.scenario_config import SCENARIO_CONFIG_VERSION, TAB_CONFIGS


ARTIFACT_SPECS = (
    ("run_summary", "summary.json", True, "core"),
    ("environment_profile", "*.environment_profile.json", True, "core"),
    ("evidence_manifest", "*.evidence_manifest.json", True, "core"),
    ("evidence_reconciliation", "*.evidence_reconciliation.json", True, "core"),
    ("focusable_coverage", "*.focusable_coverage.json", True, "core"),
    ("profiler_archive", "*.profiler.zip", True, "core"),
    ("focusable_inventory", "*.focusable_inventory.json", False, "supporting"),
    ("evidence_ledger", "*.evidence.jsonl", False, "supporting"),
    ("xlsx", "*.xlsx", False, "supporting"),
    ("normal_log", "*.normal.log", False, "supporting"),
    ("runner_log", "runner.log", False, "supporting"),
    ("runtime_config", "runtime_config.json", False, "supporting"),
)


@dataclass(frozen=True)
class CandidateBuildResult:
    candidate: BaselineCandidate
    path: Path | None
    document_digest: str
    reference: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_reference(digest: str, scope: str = "artifact-bytes-v1") -> dict[str, str]:
    return {"algorithm": "SHA-256", "scope": scope, "value": digest}


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def _find_one(root: Path, pattern: str) -> Path | None:
    if "*" not in pattern:
        path = root / pattern
        return path if path.is_file() else None
    matches = sorted(root.glob(pattern))
    return matches[0] if len(matches) == 1 else None


def _status_value(field: Any) -> Any:
    if not isinstance(field, Mapping):
        return None
    status = str(field.get("status") or "").upper()
    return field.get("value") if status in {"AVAILABLE", "BACKFILLED"} else None


def _profile_value(profile: Mapping[str, Any], *path: str) -> Any:
    value: Any = profile
    for part in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return _status_value(value)


def _manifest_value(manifest: Mapping[str, Any], name: str) -> Any:
    return _status_value(manifest.get(name))


def _artifact_schema(path: Path, artifact_type: str) -> str | None:
    if artifact_type == "profiler_archive":
        try:
            with zipfile.ZipFile(path) as archive:
                schemas = {
                    str(json.loads(archive.read(name)).get("schema_version") or "")
                    for name in archive.namelist()
                    if name.endswith(".profiler.json")
                }
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
            return None
        schemas.discard("")
        return schemas.pop() if len(schemas) == 1 else None
    if artifact_type == "run_summary":
        payload = _load_json(path)
        return str(payload.get("schema_version") or "legacy-batch-device-summary-v0")
    if artifact_type == "batch_summary":
        payload = _load_json(path)
        return str(payload.get("schema_version") or "legacy-batch-summary-v0")
    if path.suffix.lower() != ".json" or path.stat().st_size > 4 * 1024 * 1024:
        return None
    payload = _load_json(path)
    schema = payload.get("schema_version") or payload.get("candidate_schema")
    return str(schema) if schema else None


def _artifact_manifest(root: Path, batch_id: str | None) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for artifact_type, pattern, required, tier in ARTIFACT_SPECS:
        path = _find_one(root, pattern)
        if path is None:
            artifacts.append(
                {
                    "artifact_type": artifact_type,
                    "relative_reference": None,
                    "document_digest": None,
                    "schema_version": None,
                    "size": None,
                    "created_at": None,
                    "availability": "MISSING",
                    "required": required,
                    "tier": tier,
                }
            )
            continue
        digest = _sha256_file(path)
        created_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace(
            "+00:00", "Z"
        )
        logical_root = batch_id or "standalone"
        artifacts.append(
            {
                "artifact_type": artifact_type,
                "relative_reference": f"qa-run://{logical_root}/device/{path.name}",
                "document_digest": _digest_reference(digest),
                "schema_version": _artifact_schema(path, artifact_type),
                "size": path.stat().st_size,
                "created_at": created_at,
                "availability": "AVAILABLE",
                "required": required,
                "tier": tier,
            }
        )
    batch_summary = root.parent / "batch_summary.json"
    if batch_summary.is_file():
        digest = _sha256_file(batch_summary)
        artifacts.append(
            {
                "artifact_type": "batch_summary",
                "relative_reference": f"qa-run://{batch_id or 'standalone'}/batch_summary.json",
                "document_digest": _digest_reference(digest),
                "schema_version": _artifact_schema(batch_summary, "batch_summary"),
                "size": batch_summary.stat().st_size,
                "created_at": datetime.fromtimestamp(
                    batch_summary.stat().st_mtime, UTC
                ).isoformat().replace("+00:00", "Z"),
                "availability": "AVAILABLE",
                "required": False,
                "tier": "supporting",
            }
        )
    return {
        "manifest_schema": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "artifacts": artifacts,
    }


def _evidence_parts(root: Path) -> tuple[dict[str, Any], dict[str, Any], Path | None]:
    path = _find_one(root, "*.evidence_manifest.json")
    payload = _load_json(path)
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else payload
    return payload, dict(manifest), path


def _environment_parts(
    root: Path,
    evidence_manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    path = _find_one(root, "*.environment_profile.json")
    profile = _load_json(path)
    if path is not None and profile:
        fingerprint_value = profile.get("environment_fingerprint")
        fingerprint = (
            dict(fingerprint_value)
            if isinstance(fingerprint_value, Mapping)
            else build_environment_fingerprint(profile).to_dict()
        )
        digest = _sha256_file(path)
        reference = {
            "schema_version": profile.get("schema_version"),
            "filename": path.name,
            "sha256": digest,
            "document_digest": document_digest_reference(digest),
            "environment_fingerprint": fingerprint,
            "fingerprint_schema": fingerprint.get("fingerprint_schema"),
            "fingerprint_status": fingerprint.get("status"),
        }
        environment = {
            "target_app_package": _profile_value(profile, "target_app", "package"),
            "target_app_version_name": _profile_value(profile, "target_app", "version_name"),
            "target_app_version_code": _profile_value(profile, "target_app", "version_code"),
            "locale": _profile_value(profile, "locale"),
            "talkback_package": _profile_value(profile, "talkback", "package"),
            "talkback_version_name": _profile_value(profile, "talkback", "version_name"),
        }
        return profile, fingerprint, reference["document_digest"], environment

    target_dump = _manifest_value(evidence_manifest, "target_app_version")
    target_result = parse_package_metadata("com.samsung.android.oneconnect", target_dump)
    target_metadata = target_result.value if target_result.status.value == "AVAILABLE" else None
    target_version = getattr(target_metadata, "version_name", None)
    target_code = getattr(target_metadata, "version_code", None)
    locale = _manifest_value(evidence_manifest, "locale")
    runtime_hash = _manifest_value(evidence_manifest, "runtime_config_hash")
    registry_hash = _manifest_value(evidence_manifest, "scenario_registry_hash")
    flags = evidence_manifest.get("feature_flags")
    if not isinstance(flags, Mapping):
        flags = summary.get("feature_flags") if isinstance(summary.get("feature_flags"), Mapping) else {}
    build_fingerprint = _manifest_value(evidence_manifest, "android_build")
    release_match = re.search(r":([^/]+)/", str(build_fingerprint or ""))
    android_major = None
    if release_match:
        major_match = re.match(r"(\d+)", release_match.group(1))
        android_major = int(major_match.group(1)) if major_match else None
    talkback_package = _legacy_talkback_package(root)
    coverage_payload = _load_json(_find_one(root, "*.focusable_coverage.json"))
    reconciliation_payload = _load_json(_find_one(root, "*.evidence_reconciliation.json"))
    profiler_schema = _artifact_schema(_find_one(root, "*.profiler.zip"), "profiler_archive") if _find_one(root, "*.profiler.zip") else None
    collection_contracts = {
        "evidence": _manifest_value(evidence_manifest, "evidence_schema_version"),
        "coverage": coverage_payload.get("schema_version"),
        "reconciliation": reconciliation_payload.get("schema_version"),
        "profiler": profiler_schema,
    }
    collection_contracts = {
        name: value for name, value in collection_contracts.items() if value
    }
    source = {
        "fingerprint_schema": ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
        "direct": {
            "target_app_package": "com.samsung.android.oneconnect" if target_metadata else None,
            "target_app_release_train": target_version,
            "scenario_registry_hash": registry_hash,
            "runtime_config_hash": runtime_hash,
            "locale": locale,
            "traversal_contract": None,
            "identity_contract": None,
            "comparison_feature_flags": dict(flags),
            "collection_contract_versions": collection_contracts,
        },
        "family": {
            "android_major": android_major,
            "one_ui_major": None,
            "talkback_package": talkback_package,
            "talkback_major": None,
            "form_factor": None,
            "device_family": None,
        },
    }
    missing = sorted(
        name
        for group in (source["direct"], source["family"])
        for name, value in group.items()
        if value is None
    )
    fingerprint = {
        "fingerprint_schema": ENVIRONMENT_FINGERPRINT_SCHEMA_VERSION,
        "status": "INCOMPLETE",
        "hash": None,
        "fingerprint_source": source,
        "missing_fields": missing,
        "invalid_fields": [],
        "backfilled": True,
    }
    environment = {
        "target_app_package": "com.samsung.android.oneconnect" if target_metadata else None,
        "target_app_version_name": target_version,
        "target_app_version_code": target_code,
        "locale": locale,
        "talkback_package": talkback_package,
        "talkback_version_name": None,
    }
    return {}, fingerprint, None, environment


def _legacy_talkback_package(root: Path) -> str | None:
    packages = (
        "com.samsung.android.accessibility.talkback",
        "com.google.android.marvin.talkback",
    )
    for pattern in ("runner.log", "*.normal.log"):
        path = _find_one(root, pattern)
        if path is None:
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    for package in packages:
                        if package in line and "TalkBackService" in line:
                            return package
        except OSError:
            continue
    return None


def _repository_and_runtime(
    profile: Mapping[str, Any],
    evidence_manifest: Mapping[str, Any],
    fingerprint: Mapping[str, Any],
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = fingerprint.get("fingerprint_source")
    direct = source.get("direct") if isinstance(source, Mapping) else {}
    direct = direct if isinstance(direct, Mapping) else {}
    commit = _profile_value(profile, "repository", "commit") or _manifest_value(
        evidence_manifest, "repository_commit_sha"
    )
    dirty = _profile_value(profile, "repository", "dirty")
    if dirty is None:
        dirty = _manifest_value(evidence_manifest, "working_tree_dirty")
    runtime_config_path = root / "runtime_config.json"
    runtime_payload = _load_json(runtime_config_path)
    normalized_hash = canonical_sha256(runtime_payload) if runtime_payload else None
    collection_versions = _profile_value(profile, "runtime", "collection_schema_versions")
    if not isinstance(collection_versions, Mapping):
        collection_versions = direct.get("collection_contract_versions")
    runtime = {
        "scenario_registry_hash": _profile_value(profile, "runtime", "scenario_registry_hash")
        or _manifest_value(evidence_manifest, "scenario_registry_hash"),
        "runtime_config_hash": _profile_value(profile, "runtime", "runtime_config_hash")
        or _manifest_value(evidence_manifest, "runtime_config_hash"),
        "normalized_runtime_config_hash": normalized_hash,
        "traversal_contract": _profile_value(profile, "runtime", "traversal_contract")
        or direct.get("traversal_contract"),
        "identity_contract": _profile_value(profile, "runtime", "identity_contract")
        or direct.get("identity_contract"),
        "feature_flags": _profile_value(profile, "runtime", "feature_flags")
        or direct.get("comparison_feature_flags")
        or {},
        "collection_contract_versions": dict(collection_versions)
        if isinstance(collection_versions, Mapping)
        else {},
    }
    return {"commit": commit, "dirty": dirty}, runtime


def _batch_parts(root: Path) -> tuple[dict[str, Any], Path | None, dict[str, Any]]:
    batch_path = root.parent / "batch_summary.json"
    batch = _load_json(batch_path)
    device_entry: dict[str, Any] = {}
    devices = batch.get("devices")
    if isinstance(devices, list):
        for item in devices:
            if not isinstance(item, dict):
                continue
            output_dir = str(item.get("output_dir") or "").replace("/", "\\")
            if output_dir.endswith(root.name):
                device_entry = item
                break
    return batch, batch_path if batch_path.is_file() else None, device_entry


def _source_run_id(root: Path) -> str:
    candidates = sorted(root.glob("*.evidence_manifest.json"))
    if candidates:
        return candidates[0].name.removesuffix(".evidence_manifest.json")
    candidates = sorted(root.glob("*.normal.log"))
    if candidates:
        return candidates[0].name.removesuffix(".normal.log")
    return root.name


def _scenario_set(
    summary: Mapping[str, Any],
    batch: Mapping[str, Any],
    device_entry: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    observed = device_entry.get("observed_scenario_ids")
    if isinstance(observed, list) and observed:
        selected = [str(item) for item in observed]
    else:
        scenarios = summary.get("scenarios")
        selected = [
            str(item.get("id"))
            for item in scenarios if isinstance(item, dict) and item.get("id")
        ] if isinstance(scenarios, list) else []
    registry_order = [str(item.get("scenario_id")) for item in TAB_CONFIGS if item.get("scenario_id")]
    is_full = (
        str(batch.get("mode") or summary.get("mode") or "").lower() == "full"
        and len(selected) == len(registry_order)
        and set(selected) == set(registry_order)
    )
    return {
        "scenario_set_schema": SCENARIO_SET_SCHEMA_VERSION,
        "scenario_registry_version": SCENARIO_CONFIG_VERSION,
        "scenario_registry_hash": runtime.get("scenario_registry_hash"),
        "selected_scenario_ids": selected,
        "selected_scenario_hash": canonical_sha256(sorted(selected)),
        "selected_scenario_count": len(selected),
        "scenario_order_hash": canonical_sha256(selected),
        "registry_scenario_count": len(registry_order),
        "run_kind": "FULL" if is_full else "TARGETED",
        "is_targeted": not is_full,
    }


def _coverage_summary(root: Path) -> dict[str, Any]:
    path = _find_one(root, "*.focusable_coverage.json")
    payload = _load_json(path)
    records = payload.get("records")
    summaries = payload.get("summary")
    if not isinstance(records, list) or not isinstance(summaries, list):
        return {"available": False}
    cohort_candidates: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict) or item.get("taxonomy") == "IGNORE":
            continue
        source = {
            "scenario_id": item.get("scenario_id"),
            "canonical_id": item.get("canonical_id"),
            "taxonomy": item.get("taxonomy"),
        }
        cohort_candidates.append(
            {
                "scenario_id": source["scenario_id"],
                "taxonomy": source["taxonomy"],
                "signature": canonical_sha256(source),
                "coverage_status": item.get("coverage_status"),
            }
        )
    cohort_candidates.sort(key=lambda item: str(item["signature"]))
    signatures = [str(item["signature"]) for item in cohort_candidates]
    return {
        "available": True,
        "source_schema_version": payload.get("schema_version"),
        "normalizer_version": CANDIDATE_NORMALIZER_VERSION,
        "source_artifact_id": "focusable_coverage",
        "expected_count": sum(int(item.get("expected_count") or 0) for item in summaries if isinstance(item, dict)),
        "covered_count": sum(int(item.get("covered_count") or 0) for item in summaries if isinstance(item, dict)),
        "missed_count": sum(int(item.get("missed_count") or 0) for item in summaries if isinstance(item, dict)),
        "unknown_count": sum(int(item.get("unknown_count") or 0) for item in summaries if isinstance(item, dict)),
        "cohort_hash": canonical_sha256(
            [
                {
                    "scenario_id": item["scenario_id"],
                    "taxonomy": item["taxonomy"],
                    "signature": item["signature"],
                }
                for item in cohort_candidates
            ]
        ),
        "cohort_signatures": signatures,
        "cohort_candidates": cohort_candidates,
        "scenarios": summaries,
    }


def _reconciliation_summary(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _find_one(root, "*.evidence_reconciliation.json")
    payload = _load_json(path)
    if not payload:
        return {"available": False, "status": "MISSING"}, {"available": False}
    ledger = payload.get("ledger") if isinstance(payload.get("ledger"), Mapping) else {}
    orphan = payload.get("orphan_evidence") if isinstance(payload.get("orphan_evidence"), Mapping) else {}
    reconciliation = {
        "available": True,
        "source_schema_version": payload.get("schema_version"),
        "normalizer_version": CANDIDATE_NORMALIZER_VERSION,
        "source_artifact_id": "evidence_reconciliation",
        "status": payload.get("status"),
        "event_count": payload.get("event_count"),
        "anchor_abort_count": int(payload.get("anchor_abort_scenarios") or 0),
        "orphan_count": int(orphan.get("count") or 0),
        "duplicate_event_count": int(ledger.get("duplicate_event_count") or 0),
        "write_failure_count": int(ledger.get("write_failure_count") or 0),
        "checks": payload.get("checks") if isinstance(payload.get("checks"), Mapping) else {},
    }
    identity_value = payload.get("identity_shadow_v2")
    identity = dict(identity_value) if isinstance(identity_value, Mapping) else {}
    identity.update(
        {
            "available": bool(identity),
            "source_schema_version": payload.get("schema_version"),
            "normalizer_version": CANDIDATE_NORMALIZER_VERSION,
            "source_artifact_id": "evidence_reconciliation",
        }
    )
    return reconciliation, identity


def _profiler_summary(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _find_one(root, "*.profiler.zip")
    if path is None:
        return {"available": False}, {"available": False}
    scenarios: list[dict[str, Any]] = []
    results: Counter[str] = Counter()
    try:
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith(".profiler.json"):
                    continue
                payload = json.loads(archive.read(name))
                if not isinstance(payload, dict):
                    continue
                recovery = payload.get("recovery") if isinstance(payload.get("recovery"), list) else []
                results.update(
                    str(item.get("result") or "unknown")
                    for item in recovery if isinstance(item, dict)
                )
                metrics = payload.get("metrics") if isinstance(payload.get("metrics"), Mapping) else {}
                metric_summary = {
                    str(metric): {
                        "count": int(value.get("count") or 0),
                        "duration_ms": float(value.get("duration_ms") or 0.0),
                    }
                    for metric, value in metrics.items() if isinstance(value, Mapping)
                }
                scenarios.append(
                    {
                        "scenario_id": payload.get("scenario"),
                        "runtime_ms": payload.get("runtime_ms"),
                        "metrics": metric_summary,
                        "counters": payload.get("counters") if isinstance(payload.get("counters"), Mapping) else {},
                    }
                )
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
        return {"available": False}, {"available": False}
    profiler = {
        "available": bool(scenarios),
        "source_schema_version": "traversal-profiler-v1",
        "normalizer_version": CANDIDATE_NORMALIZER_VERSION,
        "source_artifact_id": "profiler_archive",
        "metric_duration_semantics": "inclusive",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }
    recovered = int(results.get("recovered") or 0)
    attempts = sum(results.values())
    recovery = {
        "available": bool(scenarios),
        "source_schema_version": "traversal-profiler-v1",
        "normalizer_version": CANDIDATE_NORMALIZER_VERSION,
        "source_artifact_id": "profiler_archive",
        "attempts": attempts,
        "recovered": recovered,
        "failed": attempts - recovered,
        "result_distribution": dict(sorted(results.items())),
    }
    return profiler, recovery


def _run_summary(summary: Mapping[str, Any], scenario_set: Mapping[str, Any]) -> dict[str, Any]:
    completed = int(summary.get("completed_scenarios") or 0)
    reduced_terminal = sum(
        int(summary.get(name) or 0)
        for name in (
            "passed_scenarios",
            "warning_scenarios",
            "failed_scenarios",
            "not_available_scenarios",
        )
    )
    terminal = max(completed, reduced_terminal)
    raw_scenarios = summary.get("scenarios") if isinstance(summary.get("scenarios"), list) else []
    scenarios = [
        {
            key: item.get(key)
            for key in (
                "id",
                "status",
                "steps",
                "stop_reason",
                "traversal_result",
                "availability_status",
                "availability_confidence",
                "availability_reason",
            )
        }
        for item in raw_scenarios
        if isinstance(item, Mapping) and item.get("id")
    ]
    return {
        "source_schema_version": summary.get("schema_version") or "legacy-batch-device-summary-v0",
        "normalizer_version": CANDIDATE_NORMALIZER_VERSION,
        "source_artifact_id": "run_summary",
        "selected_scenarios": scenario_set.get("selected_scenario_count"),
        "executed_scenarios": int(summary.get("executed_scenarios") or 0),
        "terminal_scenarios": terminal,
        "completed_scenarios": completed,
        "failed_scenarios": int(summary.get("failed_scenarios") or 0),
        "process_status": summary.get("process_status") or summary.get("state"),
        "scenario_result_status": summary.get("scenario_result_status"),
        "acceptance_result": "PASS WITH LIMITATIONS"
        if summary.get("scenario_result_status") == "warning"
        else str(summary.get("scenario_result_status") or "UNKNOWN").upper(),
        "scenarios": scenarios,
    }


def _limitations(
    summary: Mapping[str, Any],
    fingerprint: Mapping[str, Any],
    environment_profile: Mapping[str, Any],
    scenario_set: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    limitations: list[dict[str, Any]] = []
    if not environment_profile:
        limitations.append(
            {
                "code": "HISTORICAL_BACKFILL",
                "category": "PROVENANCE",
                "message": "EnvironmentProfile was not captured at run time",
            }
        )
        limitations.append(
            {
                "code": "HISTORICAL_PARITY_UNAVAILABLE",
                "category": "COMPARISON_SCOPE_LIMITATION",
                "message": "Historical environment parity cannot be established",
            }
        )
    if fingerprint.get("status") != "COMPLETE":
        limitations.append(
            {
                "code": "ENVIRONMENT_INCOMPLETE",
                "category": "ENVIRONMENT",
                "message": "Environment fingerprint is not COMPLETE",
            }
        )
    if scenario_set.get("is_targeted") is True:
        limitations.append(
            {
                "code": "TARGETED_RUN",
                "category": "WORKLOAD",
                "message": "Candidate covers a targeted scenario subset",
            }
        )
    issues = summary.get("quality_issues")
    if isinstance(issues, list):
        for item in issues:
            if not isinstance(item, Mapping) or not item.get("mismatch_type"):
                continue
            limitations.append(
                {
                    "code": str(item.get("mismatch_type")),
                    "category": "OBSERVED_RESULT_LIMITATION",
                    "scenario_id": item.get("scenario_id"),
                    "raw_result": item.get("final_result"),
                    "review_status": "UNREVIEWED",
                }
            )
    return tuple(limitations)


def _candidate_reference(candidate_id: str, filename: str, state: str, eligible: bool) -> dict[str, Any]:
    # Deliberately excludes the candidate document digest: source summaries are
    # themselves candidate inputs, so embedding that digest would create a cycle.
    return {
        "candidate_schema": BASELINE_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "filename": filename,
        "approval_state": state,
        "approval_eligible": eligible,
    }


def _environment_reference(
    root: Path,
    summary: Mapping[str, Any],
    profile: Mapping[str, Any],
    fingerprint: Mapping[str, Any],
    document_digest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw = summary.get("environment_profile")
    raw = raw if isinstance(raw, Mapping) else {}
    path = _find_one(root, "*.environment_profile.json")
    reference = {
        "status": "AVAILABLE" if profile and path else "BACKFILLED",
        "schema_version": profile.get("schema_version") if profile else raw.get("schema_version"),
        "filename": path.name if path else raw.get("filename"),
        "sha256": document_digest.get("value") if isinstance(document_digest, Mapping) else None,
        "document_digest": dict(document_digest) if isinstance(document_digest, Mapping) else None,
        "fingerprint_schema": fingerprint.get("fingerprint_schema"),
        "fingerprint_status": fingerprint.get("status"),
    }
    # Never copy path/output_dir fields from legacy references: batch directory
    # names can contain a raw device serial.
    return reference


def _integrate_reference(
    root: Path,
    summary_path: Path,
    batch_path: Path | None,
    evidence_path: Path | None,
    reference: Mapping[str, Any],
) -> None:
    summary = _load_json(summary_path)
    if summary:
        summary["baseline_candidate"] = dict(reference)
        _atomic_write_json(summary_path, summary)
    evidence = _load_json(evidence_path)
    if evidence:
        manifest = evidence.get("manifest")
        if isinstance(manifest, dict):
            manifest["baseline_candidate"] = dict(reference)
        else:
            evidence["baseline_candidate"] = dict(reference)
        _atomic_write_json(evidence_path, evidence)
    batch = _load_json(batch_path)
    devices = batch.get("devices") if isinstance(batch, dict) else None
    if isinstance(devices, list):
        for item in devices:
            if not isinstance(item, dict):
                continue
            output_dir = str(item.get("output_dir") or "").replace("/", "\\")
            if output_dir.endswith(root.name):
                item["baseline_candidate"] = dict(reference)
                break
        _atomic_write_json(batch_path, batch)


def build_baseline_candidate(
    run_root: str | Path,
    *,
    created_at: str | None = None,
    write: bool = True,
    integrate: bool = True,
) -> CandidateBuildResult:
    root = Path(run_root)
    summary_path = root / "summary.json"
    summary = _load_json(summary_path)
    if not summary:
        raise ValueError(f"run summary is unavailable: {summary_path}")
    batch, batch_path, device_entry = _batch_parts(root)
    evidence_payload, evidence_manifest, evidence_path = _evidence_parts(root)
    profile, fingerprint, environment_digest, environment = _environment_parts(
        root, evidence_manifest, summary
    )
    repository, runtime = _repository_and_runtime(
        profile, evidence_manifest, fingerprint, root
    )
    scenario_set = _scenario_set(summary, batch, device_entry, runtime)
    coverage = _coverage_summary(root)
    reconciliation, identity = _reconciliation_summary(root)
    profiler, recovery = _profiler_summary(root)
    run = _run_summary(summary, scenario_set)
    comparison_contract = {
        "contract_version": COMPARISON_CONTRACT_VERSION,
        "normalizer_version": CANDIDATE_NORMALIZER_VERSION,
        "environment": environment,
        "environment_fingerprint": fingerprint,
        "repository": repository,
        "runtime": runtime,
        "scenario_set": scenario_set,
        "run": run,
        "coverage": coverage,
        "identity": identity,
        "recovery": recovery,
        "reconciliation": reconciliation,
        "profiler": profiler,
    }
    limitations = _limitations(summary, fingerprint, profile, scenario_set)
    source_run_id = _source_run_id(root)
    source_batch_id = str(batch.get("batch_id") or "") or None
    evidence_run_id = str(evidence_payload.get("run_id") or "") or None
    candidate_identity_source = {
        "candidate_schema": BASELINE_CANDIDATE_SCHEMA_VERSION,
        "source_run_id": source_run_id,
        "source_batch_id": source_batch_id,
        "evidence_run_id": evidence_run_id,
        "environment_fingerprint": fingerprint,
        "scenario_set": scenario_set,
        "runtime": {
            "scenario_registry_hash": runtime.get("scenario_registry_hash"),
            "runtime_config_hash": runtime.get("runtime_config_hash"),
            "normalized_runtime_config_hash": runtime.get("normalized_runtime_config_hash"),
        },
    }
    candidate_id = "candidate_" + canonical_sha256(candidate_identity_source)[:24]
    filename = f"{candidate_id}.baseline_candidate.json"

    preliminary = {
        "candidate_schema": BASELINE_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "environment_fingerprint": fingerprint,
        "document_digest": environment_digest,
        "limitations": list(limitations),
        "artifact_manifest": _artifact_manifest(root, source_batch_id),
        "comparison_contract": comparison_contract,
    }
    preliminary_report = validate_baseline_candidate(preliminary)
    preliminary_eligible = bool(preliminary_report["approval_eligible"])
    preliminary_state = (
        ApprovalState.CANDIDATE if preliminary_eligible else ApprovalState.NOT_ELIGIBLE
    )
    preliminary_reference = _candidate_reference(
        candidate_id, filename, preliminary_state.value, preliminary_eligible
    )
    if write and integrate:
        _integrate_reference(root, summary_path, batch_path, evidence_path, preliminary_reference)

    artifact_manifest = _artifact_manifest(root, source_batch_id)
    candidate_payload = {
        **preliminary,
        "artifact_manifest": artifact_manifest,
    }
    report = validate_baseline_candidate(candidate_payload)
    eligible = bool(report["approval_eligible"])
    approval_state = ApprovalState.CANDIDATE if eligible else ApprovalState.NOT_ELIGIBLE
    candidate = BaselineCandidate(
        candidate_schema=BASELINE_CANDIDATE_SCHEMA_VERSION,
        candidate_id=candidate_id,
        created_at=created_at or _utc_now(),
        source_run_id=source_run_id,
        source_batch={
            "batch_id": source_batch_id,
            "mode": batch.get("mode") or summary.get("mode"),
        },
        source_batch_id=source_batch_id,
        evidence_run_id=evidence_run_id,
        environment_reference=_environment_reference(
            root,
            summary,
            profile,
            fingerprint,
            environment_digest,
        ),
        environment_fingerprint=dict(fingerprint),
        document_digest=dict(environment_digest) if isinstance(environment_digest, Mapping) else None,
        approval_state=approval_state,
        approval_eligibility=ApprovalEligibility(
            eligible=eligible,
            reasons=tuple(report.get("failure_reasons") or []),
        ),
        limitations=limitations,
        artifact_manifest=artifact_manifest,
        comparison_contract=comparison_contract,
        validation_report=report,
    )
    candidate_digest = candidate.document_sha256()
    path = root / filename if write else None
    if path is not None:
        _atomic_write_json(path, candidate.to_dict())
    reference = _candidate_reference(candidate_id, filename, approval_state.value, eligible)
    reference["document_digest"] = _digest_reference(
        candidate_digest, "canonical-baseline-candidate-v1"
    )
    return CandidateBuildResult(candidate, path, candidate_digest, reference)


__all__ = ["CandidateBuildResult", "build_baseline_candidate"]
