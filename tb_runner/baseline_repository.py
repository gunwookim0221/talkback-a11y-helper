"""Manual, immutable and auditable baseline repository for Phase 10.2."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from tb_runner.baseline_artifact_store import ContentAddressedArtifactStore, sha256_file
from tb_runner.baseline_repository_schema import (
    APPROVED_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    APP_INDEX_SCHEMA_VERSION,
    BASELINE_KEY_SCHEMA_VERSION,
    BASELINE_SCHEMA_VERSION,
    CATALOG_SCHEMA_VERSION,
    LIFECYCLE_EVENT_SCHEMA_VERSION,
    REPOSITORY_VERSION,
    AcceptanceResult,
    LifecycleEventType,
)
from tb_runner.baseline_repository_validator import (
    OfflineValidationResult,
    offline_revalidate_candidate,
    validate_reviewed_limitations,
)
from tb_runner.canonical_json import canonical_json, canonical_json_bytes, canonical_sha256


class BaselineRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArtifactPinPolicy:
    pin_required: bool = True
    optional_artifact_types: tuple[str, ...] = ()
    retention_class: str = "BASELINE_AUDIT"


@dataclass(frozen=True)
class ApprovalRequest:
    candidate_path: Path
    candidate_digest: str
    reviewer: Mapping[str, str]
    reason: str
    acceptance_result: str
    structured_limitations: tuple[dict[str, Any], ...] = ()
    known_limitation_snapshot: tuple[dict[str, Any], ...] = ()
    limitations_explicitly_accepted: bool = False
    supersedes: str | None = None
    artifact_pin_policy: ArtifactPinPolicy = field(default_factory=ArtifactPinPolicy)


@dataclass(frozen=True)
class ApprovalResult:
    baseline_id: str
    baseline_key_digest: str
    package_path: Path
    core_checksums: dict[str, str]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryVerification:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    package_count: int
    event_count: int


MEDIA_TYPES = {
    "profiler_archive": "application/zip",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "evidence_ledger": "application/x-ndjson",
    "normal_log": "text/plain",
    "runner_log": "text/plain",
}
SENSITIVE_ARTIFACT_TYPES = frozenset(
    {"evidence_ledger", "xlsx", "normal_log", "runner_log", "focusable_inventory"}
)
REJECTION_CATEGORIES = frozenset(
    {
        "REGRESSION",
        "INCOMPLETE_ENVIRONMENT",
        "INVALID_ARTIFACT",
        "INVALID_COHORT",
        "KNOWN_ISSUE_UNREVIEWED",
        "MANUAL_REJECTION",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.write_bytes(canonical_json_bytes(payload))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _actor(actor: Mapping[str, str]) -> dict[str, str]:
    identity = str(actor.get("identity") or "").strip()
    authentication_source = str(actor.get("authentication_source") or "").strip()
    if not identity or not authentication_source:
        raise BaselineRepositoryError("actor identity and authentication_source are required")
    return {"identity": identity, "authentication_source": authentication_source}


def _reason(reason: str) -> str:
    value = str(reason or "").strip()
    if not value:
        raise BaselineRepositoryError("an explicit reason is required")
    return value


def _app_key(candidate: Mapping[str, Any]) -> str:
    comparison = candidate.get("comparison_contract")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    environment = comparison.get("environment")
    environment = environment if isinstance(environment, Mapping) else {}
    package = str(environment.get("target_app_package") or "").strip().lower()
    if not package:
        raise BaselineRepositoryError("target app package is unavailable")
    safe = re.sub(r"[^a-z0-9._-]+", "-", package).strip(".-")
    if not safe:
        raise BaselineRepositoryError("target app package cannot form an app key")
    return safe


def _baseline_key(candidate: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    fingerprint = candidate.get("environment_fingerprint")
    fingerprint = fingerprint if isinstance(fingerprint, Mapping) else {}
    source = fingerprint.get("fingerprint_source")
    source = source if isinstance(source, Mapping) else {}
    comparison = candidate.get("comparison_contract")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    scenario_set = comparison.get("scenario_set")
    scenario_set = scenario_set if isinstance(scenario_set, Mapping) else {}
    key_source = {
        "key_schema": BASELINE_KEY_SCHEMA_VERSION,
        "direct": {
            **dict(source.get("direct") or {}),
            "selected_scenario_hash": scenario_set.get("selected_scenario_hash"),
            "scenario_order_hash": scenario_set.get("scenario_order_hash"),
            "selected_scenario_count": scenario_set.get("selected_scenario_count"),
        },
        "family": dict(source.get("family") or {}),
    }
    return key_source, canonical_sha256(key_source)


def _event_hash_source(event: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key not in {"event_id", "event_hash"}}


def _catalog_checksum(payload: Mapping[str, Any]) -> str:
    source = {key: value for key, value in payload.items() if key != "catalog_checksum"}
    return canonical_sha256(source)


def _contains_private_path_or_serial(payload: Any) -> str | None:
    def visit(value: Any, key: str = "") -> str | None:
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                lowered = str(child_key).lower()
                if lowered in {"serial", "device_serial", "raw_serial"} and child is not None:
                    if not isinstance(child, Mapping) and child != "":
                        return f"raw serial field: {child_key}"
                    if isinstance(child, Mapping) and child.get("value") not in {None, ""}:
                        return f"raw serial field: {child_key}"
                found = visit(child, lowered)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child, key)
                if found:
                    return found
        elif isinstance(value, str):
            if (
                re.match(r"^[A-Za-z]:[\\/]", value)
                or value.startswith("/")
                or value.startswith("\\\\")
            ):
                return f"absolute path in {key or 'value'}"
        return None

    return visit(payload)


class BaselineRepository:
    def __init__(
        self,
        root: str | Path,
        *,
        artifact_root: str | Path | None = None,
        clock: Callable[[], str] | None = None,
        lock_timeout: float = 10.0,
    ) -> None:
        self.root = Path(root)
        self.artifact_root = Path(artifact_root) if artifact_root else self.root.parent / ".baseline-artifacts"
        self._clock = clock or _utc_now
        self._lock_timeout = lock_timeout
        self.artifacts = ContentAddressedArtifactStore(self.artifact_root, clock=self._clock)

    @property
    def lifecycle_path(self) -> Path:
        return self.root / "lifecycle.jsonl"

    @property
    def catalog_path(self) -> Path:
        return self.root / "catalog.json"

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / ".repository.lock"
        deadline = time.monotonic() + self._lock_timeout
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
                os.fsync(descriptor)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise BaselineRepositoryError("repository is locked by another operation")
                time.sleep(0.05)
        try:
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            path.unlink(missing_ok=True)

    def _events(self, *, verify: bool = True) -> list[dict[str, Any]]:
        if not self.lifecycle_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        previous: str | None = None
        for line_number, line in enumerate(self.lifecycle_path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BaselineRepositoryError(f"invalid lifecycle JSON at line {line_number}") from exc
            if not isinstance(value, dict):
                raise BaselineRepositoryError(f"invalid lifecycle event at line {line_number}")
            if verify:
                expected = canonical_sha256(_event_hash_source(value))
                if value.get("event_hash") != expected or value.get("event_id") != f"event_{expected[:24]}":
                    raise BaselineRepositoryError(f"lifecycle event hash mismatch at line {line_number}")
                if value.get("previous_event_hash") != previous:
                    raise BaselineRepositoryError(f"lifecycle chain mismatch at line {line_number}")
            previous = value.get("event_hash")
            events.append(value)
        return events

    def _append_event(self, event_type: str, **payload: Any) -> dict[str, Any]:
        events = self._events()
        source = {
            "event_schema": LIFECYCLE_EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            **payload,
            "created_at": payload.get("created_at") or self._clock(),
            "previous_event_hash": events[-1]["event_hash"] if events else None,
        }
        digest = canonical_sha256(source)
        event = {**source, "event_id": f"event_{digest[:24]}", "event_hash": digest}
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lifecycle_path.open("ab") as handle:
            handle.write((canonical_json(event) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        return event

    @staticmethod
    def _reduce_states(events: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
        states: dict[str, str] = {}
        superseded_by: dict[str, str] = {}
        for event in events:
            event_type = event.get("event_type")
            baseline_id = event.get("baseline_id")
            candidate_id = event.get("candidate_id")
            if event_type == "APPROVED" and baseline_id:
                states[str(baseline_id)] = "APPROVED"
                old = event.get("supersedes")
                if old:
                    states[str(old)] = "SUPERSEDED"
                    superseded_by[str(old)] = str(baseline_id)
            elif event_type == "SUPERSEDED" and baseline_id:
                states[str(baseline_id)] = "SUPERSEDED"
                if event.get("superseded_by"):
                    superseded_by[str(baseline_id)] = str(event["superseded_by"])
            elif event_type == "REJECTED" and candidate_id:
                states[str(candidate_id)] = "REJECTED"
            elif event_type == "ARCHIVED":
                target = baseline_id or candidate_id
                if target:
                    states[str(target)] = "ARCHIVED"
        return states, superseded_by

    def _packages(self) -> dict[str, tuple[Path, dict[str, Any]]]:
        packages: dict[str, tuple[Path, dict[str, Any]]] = {}
        if not self.root.is_dir():
            return packages
        for path in sorted(self.root.glob("*/baseline_*_r*/baseline.json")):
            payload = _load_json(path)
            baseline_id = str(payload.get("baseline_id") or "")
            if baseline_id:
                packages[baseline_id] = (path.parent, payload)
        return packages

    def _snapshot(self) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str], dict[str, tuple[Path, dict[str, Any]]]]:
        events = self._events()
        states, superseded_by = self._reduce_states(events)
        return events, states, superseded_by, self._packages()

    def _next_revision(self, key_digest: str, packages: Mapping[str, tuple[Path, dict[str, Any]]]) -> int:
        revisions = [
            int(payload.get("baseline_revision") or 0)
            for _, payload in packages.values()
            if payload.get("baseline_key_digest") == key_digest
        ]
        return max(revisions, default=0) + 1

    def _validation_failure(self, candidate_id: str | None, actor: Mapping[str, str], reason: str, failures: Any) -> None:
        self._append_event(
            LifecycleEventType.VALIDATION_FAILED.value,
            candidate_id=candidate_id,
            actor=dict(actor),
            reason=reason,
            failures=list(failures),
        )

    def approve(self, request: ApprovalRequest) -> ApprovalResult:
        actor = _actor(request.reviewer)
        reason = _reason(request.reason)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(request.candidate_digest or "")):
            raise BaselineRepositoryError("the reviewed Candidate SHA-256 digest is required")
        if not request.artifact_pin_policy.pin_required:
            raise BaselineRepositoryError("required artifact pinning cannot be disabled")
        acceptance = str(request.acceptance_result)
        if acceptance not in {item.value for item in AcceptanceResult}:
            raise BaselineRepositoryError("acceptance result must be PASS or PASS WITH LIMITATIONS")

        initial = offline_revalidate_candidate(
            request.candidate_path,
            expected_candidate_digest=request.candidate_digest,
        )
        limitation_failures = validate_reviewed_limitations(
            initial.candidate.get("limitations"),
            list(request.structured_limitations),
            acceptance_result=acceptance,
            explicitly_accepted=request.limitations_explicitly_accepted,
        )
        known_snapshot_failures = validate_reviewed_limitations(
            initial.candidate.get("limitations"),
            list(request.known_limitation_snapshot),
            acceptance_result=acceptance,
            explicitly_accepted=request.limitations_explicitly_accepted,
        )
        with self._lock():
            validation = offline_revalidate_candidate(
                request.candidate_path,
                expected_candidate_digest=request.candidate_digest,
            )
            failures = list(validation.failures) + list(limitation_failures) + [
                f"known_snapshot:{item}" for item in known_snapshot_failures
            ]
            candidate_id = str(validation.candidate.get("candidate_id") or "") or None
            if not validation.valid or failures:
                self._validation_failure(candidate_id, actor, reason, failures)
                self.rebuild_indexes(_already_locked=True)
                raise BaselineRepositoryError("candidate approval validation failed: " + ", ".join(failures))

            events, states, _, packages = self._snapshot()
            if any(
                event.get("event_type") == "APPROVED" and event.get("candidate_id") == candidate_id
                for event in events
            ):
                raise BaselineRepositoryError("the same Candidate is already approved in this repository")
            if any(
                payload.get("source_candidate_id") == candidate_id
                for _, payload in packages.values()
            ):
                raise BaselineRepositoryError(
                    "a package for this Candidate already exists and requires repository repair"
                )
            key_source, key_digest = _baseline_key(validation.candidate)
            active = [
                baseline_id
                for baseline_id, (_, payload) in packages.items()
                if states.get(baseline_id) == "APPROVED" and payload.get("baseline_key_digest") == key_digest
            ]
            if len(active) > 1:
                raise BaselineRepositoryError("repository already has multiple active baselines for one key")
            if active and request.supersedes != active[0]:
                raise BaselineRepositoryError("the active baseline must be explicitly superseded")
            if request.supersedes:
                old = packages.get(request.supersedes)
                if old is None or states.get(request.supersedes) != "APPROVED":
                    raise BaselineRepositoryError("superseded baseline is not active APPROVED")
                if old[1].get("baseline_key_digest") != key_digest:
                    raise BaselineRepositoryError("incompatible BaselineKey cannot be superseded")

            app_key = _app_key(validation.candidate)
            revision = self._next_revision(key_digest, packages)
            baseline_id = f"baseline_{key_digest[:16]}_r{revision:04d}"
            destination = self.root / app_key / baseline_id
            if destination.exists():
                raise BaselineRepositoryError("approved package destination already exists")

            try:
                artifact_manifest, pin_events, pin_warnings = self._materialize_artifact_manifest(
                    validation, request.artifact_pin_policy
                )
            except BaselineRepositoryError as exc:
                self._validation_failure(candidate_id, actor, reason, ["artifact_pinning", str(exc)])
                self.rebuild_indexes(_already_locked=True)
                raise
            approved_at = self._clock()
            baseline = self._baseline_document(
                validation,
                request,
                actor,
                reason,
                acceptance,
                baseline_id,
                revision,
                key_source,
                key_digest,
                approved_at,
            )
            environment = copy.deepcopy(validation.environment_profile)
            privacy_error = _contains_private_path_or_serial(
                {"baseline": baseline, "environment": environment, "artifacts": artifact_manifest}
            )
            if privacy_error:
                self._validation_failure(candidate_id, actor, reason, [privacy_error])
                raise BaselineRepositoryError(f"shared package privacy validation failed: {privacy_error}")

            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.parent / f".{baseline_id}.tmp-{uuid.uuid4().hex}"
            temporary.mkdir()
            try:
                files = {
                    "baseline.json": baseline,
                    "environment_profile.json": environment,
                    "artifact_manifest.json": artifact_manifest,
                }
                for filename, payload in files.items():
                    (temporary / filename).write_bytes(canonical_json_bytes(payload))
                core_checksums = {name: sha256_file(temporary / name) for name in files}
                for filename, payload in files.items():
                    if (temporary / filename).read_bytes() != canonical_json_bytes(payload):
                        raise BaselineRepositoryError(f"core package verification failed: {filename}")
                os.replace(temporary, destination)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise

            self._append_event(
                LifecycleEventType.CANDIDATE_VALIDATED.value,
                candidate_id=candidate_id,
                actor=actor,
                reason=reason,
                candidate_digest=validation.candidate_digest,
            )
            for pin_event in pin_events:
                self._append_event(
                    LifecycleEventType.ARTIFACT_PINNED.value,
                    candidate_id=candidate_id,
                    baseline_id=baseline_id,
                    actor=actor,
                    reason=reason,
                    **pin_event,
                )
            self._append_event(
                LifecycleEventType.APPROVED.value,
                baseline_id=baseline_id,
                candidate_id=candidate_id,
                actor=actor,
                reason=reason,
                acceptance_result=acceptance,
                app_key=app_key,
                baseline_key_digest=key_digest,
                baseline_revision=revision,
                supersedes=request.supersedes,
                core_checksums=core_checksums,
            )
            if request.supersedes:
                self._append_event(
                    LifecycleEventType.SUPERSEDED.value,
                    baseline_id=request.supersedes,
                    candidate_id=candidate_id,
                    actor=actor,
                    reason=reason,
                    superseded_by=baseline_id,
                )
            self.rebuild_indexes(_already_locked=True)
            return ApprovalResult(baseline_id, key_digest, destination, core_checksums, tuple(pin_warnings))

    def _baseline_document(
        self,
        validation: OfflineValidationResult,
        request: ApprovalRequest,
        actor: Mapping[str, str],
        reason: str,
        acceptance: str,
        baseline_id: str,
        revision: int,
        key_source: Mapping[str, Any],
        key_digest: str,
        approved_at: str,
    ) -> dict[str, Any]:
        candidate = validation.candidate
        comparison = candidate["comparison_contract"]
        repository = comparison.get("repository") or {}
        return {
            "schema_version": BASELINE_SCHEMA_VERSION,
            "baseline_id": baseline_id,
            "baseline_revision": revision,
            "source_candidate_id": candidate.get("candidate_id"),
            "source_candidate_digest": {
                "algorithm": "SHA-256",
                "scope": "canonical-baseline-candidate-v1",
                "value": validation.candidate_digest,
            },
            "source_run_id": candidate.get("source_run_id"),
            "source_batch_id": candidate.get("source_batch_id"),
            "evidence_run_id": candidate.get("evidence_run_id"),
            "baseline_key": copy.deepcopy(key_source),
            "baseline_key_digest": key_digest,
            "environment_fingerprint": copy.deepcopy(candidate.get("environment_fingerprint")),
            "lifecycle": {"state": "APPROVED", "supersedes": request.supersedes},
            "acceptance_result": acceptance,
            "approval": {
                "reviewer": dict(actor),
                "reason": reason,
                "limitations_explicitly_accepted": request.limitations_explicitly_accepted,
            },
            "structured_limitations": copy.deepcopy(list(request.structured_limitations)),
            "candidate_limitations": copy.deepcopy(candidate.get("limitations") or []),
            "scenario_set_contract": copy.deepcopy(comparison.get("scenario_set")),
            "comparison_contract": {
                "contract_version": comparison.get("contract_version"),
                "normalizer_version": comparison.get("normalizer_version"),
            },
            "summaries": {
                name: copy.deepcopy(comparison.get(name))
                for name in ("run", "coverage", "identity", "recovery", "reconciliation", "profiler")
            },
            "known_limitation_snapshot": copy.deepcopy(list(request.known_limitation_snapshot)),
            "core_schema_map": {
                "baseline": BASELINE_SCHEMA_VERSION,
                "environment_profile": validation.environment_profile.get("schema_version"),
                "artifact_manifest": APPROVED_ARTIFACT_MANIFEST_SCHEMA_VERSION,
                "comparison_contract": comparison.get("contract_version"),
            },
            "source_repository": {"commit": repository.get("commit"), "dirty": repository.get("dirty")},
            "created_at": candidate.get("created_at"),
            "approved_at": approved_at,
        }

    def _materialize_artifact_manifest(
        self, validation: OfflineValidationResult, policy: ArtifactPinPolicy
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        source_manifest = validation.candidate.get("artifact_manifest") or {}
        entries: list[dict[str, Any]] = []
        pin_events: list[dict[str, Any]] = []
        warnings: list[str] = []
        for source in source_manifest.get("artifacts") or []:
            if not isinstance(source, Mapping):
                continue
            artifact_type = str(source.get("artifact_type") or "unknown")
            digest_ref = source.get("document_digest")
            digest = str(digest_ref.get("value") or "") if isinstance(digest_ref, Mapping) else ""
            required = source.get("required") is True
            should_pin = required or artifact_type in policy.optional_artifact_types
            pinned_reference = None
            availability = str(source.get("availability") or "MISSING")
            if should_pin:
                artifact_path = validation.artifact_paths.get(artifact_type)
                try:
                    if artifact_path is None:
                        raise FileNotFoundError(artifact_type)
                    pinned = self.artifacts.pin(
                        artifact_path,
                        digest,
                        media_type=MEDIA_TYPES.get(artifact_type, "application/json"),
                        schema_version=source.get("schema_version"),
                        contains_sensitive_data=artifact_type in SENSITIVE_ARTIFACT_TYPES,
                        retention_class=policy.retention_class,
                    )
                    pinned_reference = pinned.reference
                    pin_events.append(
                        {
                            "artifact_type": artifact_type,
                            "artifact_digest": digest,
                            "pinned_reference": pinned.reference,
                            "deduplicated": pinned.deduplicated,
                        }
                    )
                except (OSError, ValueError) as exc:
                    if required:
                        raise BaselineRepositoryError(f"required artifact pin failed: {artifact_type}: {exc}") from exc
                    warnings.append(f"optional_artifact_pin_failed:{artifact_type}")
            entries.append(
                {
                    "artifact_type": artifact_type,
                    "logical_reference": source.get("relative_reference"),
                    "content_digest": copy.deepcopy(digest_ref),
                    "media_type": MEDIA_TYPES.get(artifact_type, "application/json"),
                    "size": source.get("size"),
                    "schema_version": source.get("schema_version"),
                    "required": required,
                    "tier": source.get("tier"),
                    "availability": availability,
                    "pinned_reference": pinned_reference,
                    "contains_sensitive_data": artifact_type in SENSITIVE_ARTIFACT_TYPES,
                    "retention_class": policy.retention_class if should_pin else "SOURCE_RETENTION",
                }
            )
        return {
            "manifest_schema": APPROVED_ARTIFACT_MANIFEST_SCHEMA_VERSION,
            "source_manifest_schema": source_manifest.get("manifest_schema"),
            "artifacts": entries,
        }, pin_events, warnings

    def reject(
        self,
        candidate_path: str | Path,
        *,
        reviewer: Mapping[str, str],
        reason: str,
        category: str,
        candidate_digest: str | None = None,
    ) -> dict[str, Any]:
        actor = _actor(reviewer)
        reason = _reason(reason)
        category = str(category or "").strip()
        if category not in REJECTION_CATEGORIES:
            raise BaselineRepositoryError("unsupported rejection category")
        path = Path(candidate_path)
        candidate = _load_json(path)
        if not candidate or path.read_bytes() != canonical_json_bytes(candidate):
            raise BaselineRepositoryError("candidate is unavailable or non-canonical")
        actual_digest = sha256_file(path)
        if candidate_digest and actual_digest != candidate_digest.lower():
            raise BaselineRepositoryError("candidate checksum mismatch")
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            raise BaselineRepositoryError("candidate ID is unavailable")
        with self._lock():
            _, states, _, _ = self._snapshot()
            if states.get(candidate_id) in {"REJECTED", "ARCHIVED"}:
                raise BaselineRepositoryError("candidate already has a terminal repository state")
            event = self._append_event(
                LifecycleEventType.REJECTED.value,
                candidate_id=candidate_id,
                actor=actor,
                reason=reason,
                category=category,
                candidate_digest=actual_digest,
            )
            self.rebuild_indexes(_already_locked=True)
            return event

    def supersede(
        self,
        baseline_id: str,
        *,
        superseded_by: str,
        actor: Mapping[str, str],
        reason: str,
    ) -> dict[str, Any]:
        actor_value = _actor(actor)
        reason_value = _reason(reason)
        with self._lock():
            _, states, _, packages = self._snapshot()
            old = packages.get(baseline_id)
            new = packages.get(superseded_by)
            if not old or not new:
                raise BaselineRepositoryError("both baseline packages must exist")
            if states.get(baseline_id) != "APPROVED" or states.get(superseded_by) != "APPROVED":
                raise BaselineRepositoryError("both baselines must be APPROVED before manual supersede")
            if old[1].get("baseline_key_digest") != new[1].get("baseline_key_digest"):
                raise BaselineRepositoryError("incompatible BaselineKey cannot be superseded")
            event = self._append_event(
                LifecycleEventType.SUPERSEDED.value,
                baseline_id=baseline_id,
                actor=actor_value,
                reason=reason_value,
                superseded_by=superseded_by,
            )
            self.rebuild_indexes(_already_locked=True)
            return event

    def archive(
        self,
        identifier: str,
        *,
        actor: Mapping[str, str],
        reason: str,
    ) -> dict[str, Any]:
        actor_value = _actor(actor)
        reason_value = _reason(reason)
        with self._lock():
            _, states, _, packages = self._snapshot()
            state = states.get(identifier)
            if state not in {"APPROVED", "REJECTED", "SUPERSEDED"}:
                raise BaselineRepositoryError("only APPROVED, REJECTED or SUPERSEDED records can be archived")
            event = self._append_event(
                LifecycleEventType.ARCHIVED.value,
                baseline_id=identifier if identifier in packages else None,
                candidate_id=identifier if identifier not in packages else None,
                actor=actor_value,
                reason=reason_value,
                previous_state=state,
            )
            self.rebuild_indexes(_already_locked=True)
            return event

    def rebuild_indexes(self, *, _already_locked: bool = False) -> dict[str, Any]:
        if not _already_locked:
            with self._lock():
                return self.rebuild_indexes(_already_locked=True)
        events, states, superseded_by, packages = self._snapshot()
        summaries: list[dict[str, Any]] = []
        active: dict[str, str] = {}
        by_app: dict[str, list[dict[str, Any]]] = {}
        for baseline_id, (package_path, payload) in sorted(packages.items()):
            state = states.get(baseline_id, "ORPHANED")
            key_digest = str(payload.get("baseline_key_digest") or "")
            app_key = package_path.parent.name
            summary = {
                "baseline_id": baseline_id,
                "app_key": app_key,
                "baseline_key_digest": key_digest,
                "environment_fingerprint": copy.deepcopy(payload.get("environment_fingerprint")),
                "revision": payload.get("baseline_revision"),
                "state": state,
                "source_candidate_id": payload.get("source_candidate_id"),
                "approval": copy.deepcopy(payload.get("approval")),
                "approved_at": payload.get("approved_at"),
                "supersedes": (payload.get("lifecycle") or {}).get("supersedes"),
                "superseded_by": superseded_by.get(baseline_id),
            }
            summaries.append(summary)
            by_app.setdefault(app_key, []).append(summary)
            if state == "APPROVED":
                if key_digest in active:
                    raise BaselineRepositoryError("multiple active baselines share one BaselineKey")
                active[key_digest] = baseline_id
        tail = events[-1] if events else {}
        catalog: dict[str, Any] = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "repository_version": REPOSITORY_VERSION,
            "baseline_summaries": summaries,
            "active_baselines": active,
            "lifecycle_tail": {
                "event_id": tail.get("event_id"),
                "event_hash": tail.get("event_hash"),
                "event_count": len(events),
            },
            "updated_at": self._clock(),
        }
        catalog["catalog_checksum"] = {
            "algorithm": "SHA-256",
            "scope": "canonical-catalog-without-checksum-v1",
            "value": _catalog_checksum(catalog),
        }
        _atomic_write_json(self.catalog_path, catalog)
        for app_key, app_summaries in by_app.items():
            app_active = {
                item["baseline_key_digest"]: item["baseline_id"]
                for item in app_summaries
                if item["state"] == "APPROVED"
            }
            index = {
                "schema_version": APP_INDEX_SCHEMA_VERSION,
                "repository_version": REPOSITORY_VERSION,
                "app_key": app_key,
                "active_baselines": app_active,
                "approved_revisions": [item for item in app_summaries if item["state"] == "APPROVED"],
                "superseded_revisions": [item for item in app_summaries if item["state"] == "SUPERSEDED"],
                "archived_revisions": [item for item in app_summaries if item["state"] == "ARCHIVED"],
                "updated_at": catalog["updated_at"],
            }
            _atomic_write_json(self.root / app_key / "index.json", index)
        return catalog

    def list_baselines(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        catalog = _load_json(self.catalog_path)
        if not catalog:
            catalog = self.rebuild_indexes()
        summaries = list(catalog.get("baseline_summaries") or [])
        return summaries if include_inactive else [item for item in summaries if item.get("state") == "APPROVED"]

    def inspect_baseline(self, baseline_id: str) -> dict[str, Any]:
        _, states, superseded_by, packages = self._snapshot()
        value = packages.get(baseline_id)
        if value is None:
            raise BaselineRepositoryError("baseline does not exist")
        return {
            "baseline": copy.deepcopy(value[1]),
            "repository_state": states.get(baseline_id, "ORPHANED"),
            "superseded_by": superseded_by.get(baseline_id),
            "package_path": value[0].relative_to(self.root).as_posix(),
        }

    def verify(self) -> RepositoryVerification:
        errors: list[str] = []
        warnings: list[str] = []
        try:
            events = self._events()
        except BaselineRepositoryError as exc:
            return RepositoryVerification(False, (str(exc),), (), len(self._packages()), 0)
        states, superseded_by = self._reduce_states(events)
        packages = self._packages()
        catalog = _load_json(self.catalog_path)
        if not catalog:
            errors.append("catalog_missing_or_invalid")
        else:
            digest = ((catalog.get("catalog_checksum") or {}).get("value"))
            if digest != _catalog_checksum(catalog):
                errors.append("catalog_checksum_mismatch")
            tail = catalog.get("lifecycle_tail") or {}
            actual_tail = events[-1].get("event_hash") if events else None
            if tail.get("event_hash") != actual_tail or int(tail.get("event_count") or 0) != len(events):
                errors.append("catalog_lifecycle_tail_mismatch")

        approved_events = {
            str(event.get("baseline_id")): event
            for event in events
            if event.get("event_type") == "APPROVED" and event.get("baseline_id")
        }
        for baseline_id, event in approved_events.items():
            package = packages.get(baseline_id)
            if package is None:
                errors.append(f"package_missing:{baseline_id}")
                continue
            checksums = event.get("core_checksums") or {}
            for filename in ("baseline.json", "environment_profile.json", "artifact_manifest.json"):
                path = package[0] / filename
                if not path.is_file():
                    errors.append(f"core_file_missing:{baseline_id}:{filename}")
                elif sha256_file(path) != checksums.get(filename):
                    errors.append(f"core_checksum_mismatch:{baseline_id}:{filename}")
            manifest = _load_json(package[0] / "artifact_manifest.json")
            for item in manifest.get("artifacts") or []:
                if not isinstance(item, Mapping) or item.get("required") is not True:
                    continue
                artifact_type = str(item.get("artifact_type") or "unknown")
                digest_ref = item.get("content_digest")
                digest = str(digest_ref.get("value") or "") if isinstance(digest_ref, Mapping) else ""
                expected_reference = f"artifact://sha256/{digest}"
                if item.get("pinned_reference") != expected_reference:
                    errors.append(f"required_artifact_not_pinned:{baseline_id}:{artifact_type}")
                    continue
                try:
                    payload_path = self.artifacts.location(digest) / "payload"
                except ValueError:
                    errors.append(f"pinned_artifact_digest_invalid:{baseline_id}:{artifact_type}")
                    continue
                if not payload_path.is_file():
                    errors.append(f"pinned_artifact_missing:{baseline_id}:{artifact_type}")
                elif sha256_file(payload_path) != digest:
                    errors.append(f"pinned_artifact_checksum_mismatch:{baseline_id}:{artifact_type}")
        for baseline_id in packages:
            if baseline_id not in approved_events:
                errors.append(f"orphan_package:{baseline_id}")
        for temporary in self.root.glob("*/.baseline_*.tmp-*") if self.root.is_dir() else ():
            if temporary.is_dir():
                errors.append(f"incomplete_staged_package:{temporary.name}")

        active: dict[str, str] = {}
        for baseline_id, (_, payload) in packages.items():
            if states.get(baseline_id) != "APPROVED":
                continue
            key = str(payload.get("baseline_key_digest") or "")
            if key in active:
                errors.append(f"multiple_active_baselines:{key}")
            active[key] = baseline_id

        for start in superseded_by:
            visited: set[str] = set()
            node = start
            while node in superseded_by:
                if node in visited:
                    errors.append(f"lifecycle_relation_cycle:{start}")
                    break
                visited.add(node)
                node = superseded_by[node]
        return RepositoryVerification(not errors, tuple(sorted(set(errors))), tuple(warnings), len(packages), len(events))


__all__ = [
    "ApprovalRequest",
    "ApprovalResult",
    "ArtifactPinPolicy",
    "BaselineRepository",
    "BaselineRepositoryError",
    "RepositoryVerification",
]
