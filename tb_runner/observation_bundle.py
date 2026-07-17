"""Portable, canonical observation bundles for deterministic comparator replay."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from tb_runner.canonical_json import (
    canonical_json_bytes,
    canonical_sha256,
    normalize_canonical_value,
)
from tb_runner.comparator_schema import ComparatorInput
from tb_runner.observation_adapter import load_observation_set
from tb_runner.observation_schema import (
    OBSERVATION_SET_SCHEMA_VERSION,
    CanonicalObservation,
    ObservationAvailability,
    ObservationSet,
)


OBSERVATION_BUNDLE_SCHEMA_VERSION = "talkback-portable-observation-bundle-v1"
OBSERVATION_BUNDLE_INDEX_SCHEMA_VERSION = (
    "talkback-portable-observation-bundle-index-v1"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ObservationBundleError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _bundle_source(
    observation_set: ObservationSet,
    *,
    baseline_id: str,
) -> dict[str, Any]:
    return normalize_canonical_value(
        {
            "bundle_schema": OBSERVATION_BUNDLE_SCHEMA_VERSION,
            "baseline_id": baseline_id,
            "observation_set_schema": observation_set.observation_set_schema,
            "observation_identity_digest": (
                observation_set.observation_identity_digest
            ),
            "locale": observation_set.locale,
            "app_package": observation_set.app_package,
            "app_version_name": observation_set.app_version_name,
            "app_version_code": observation_set.app_version_code,
            "source_quality": observation_set.source_quality,
            "observations": [
                item.to_dict() for item in observation_set.observations
            ],
            "artifact_provenance": observation_set.artifacts,
        }
    )


def build_observation_bundle(
    observation_set: ObservationSet,
    *,
    baseline_id: str,
) -> dict[str, Any]:
    if observation_set.availability != ObservationAvailability.COMPLETE:
        raise ObservationBundleError("only COMPLETE observation sets can be bundled")
    source = _bundle_source(observation_set, baseline_id=baseline_id)
    digest = canonical_sha256(source)
    return {
        **source,
        "bundle_id": f"observation_bundle_{digest[:24]}",
        "bundle_source_digest": digest,
    }


def _observation(value: Mapping[str, Any]) -> CanonicalObservation:
    payload = dict(value)
    bounds = payload.get("bounds")
    payload["bounds"] = tuple(bounds) if isinstance(bounds, list) else bounds
    payload["dynamic_value_markers"] = tuple(
        payload.get("dynamic_value_markers") or ()
    )
    payload["provenance"] = tuple(payload.get("provenance") or ())
    return CanonicalObservation(**payload)


def load_observation_bundle(
    source: str | Path | Mapping[str, Any],
    *,
    expected_document_digest: str | None = None,
    source_kind: str = "BASELINE",
    source_id: str | None = None,
) -> ObservationSet:
    if isinstance(source, Mapping):
        payload = dict(source)
        raw = canonical_json_bytes(payload)
    else:
        path = Path(source)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObservationBundleError("observation bundle is unreadable") from exc
        if raw != canonical_json_bytes(payload):
            raise ObservationBundleError("observation bundle is not canonical JSON")
    if expected_document_digest:
        expected = str(expected_document_digest).lower()
        if not _SHA256.fullmatch(expected) or _sha256_bytes(raw) != expected:
            raise ObservationBundleError("observation bundle document digest mismatch")
    if payload.get("bundle_schema") != OBSERVATION_BUNDLE_SCHEMA_VERSION:
        raise ObservationBundleError("unsupported observation bundle schema")
    if payload.get("observation_set_schema") != OBSERVATION_SET_SCHEMA_VERSION:
        raise ObservationBundleError("unsupported observation set schema")
    source_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"bundle_id", "bundle_source_digest"}
    }
    digest = canonical_sha256(source_payload)
    if (
        payload.get("bundle_source_digest") != digest
        or payload.get("bundle_id") != f"observation_bundle_{digest[:24]}"
    ):
        raise ObservationBundleError("observation bundle identity mismatch")
    observations = tuple(
        _observation(item)
        for item in payload.get("observations") or ()
        if isinstance(item, Mapping)
    )
    if not observations:
        raise ObservationBundleError("observation bundle is empty")
    return ObservationSet(
        observation_set_schema=OBSERVATION_SET_SCHEMA_VERSION,
        source_kind=source_kind,
        source_id=source_id or str(payload.get("baseline_id") or ""),
        locale=str(payload.get("locale") or ""),
        app_package=str(payload.get("app_package") or ""),
        app_version_name=(
            str(payload["app_version_name"])
            if payload.get("app_version_name") is not None
            else None
        ),
        app_version_code=(
            int(payload["app_version_code"])
            if payload.get("app_version_code") is not None
            else None
        ),
        availability=ObservationAvailability.COMPLETE,
        source_quality="PORTABLE_CANONICAL_BUNDLE",
        observations=observations,
        artifacts=tuple(payload.get("artifact_provenance") or ()),
        observation_identity_digest=str(
            payload.get("observation_identity_digest") or ""
        ),
        diagnostics=(),
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_observation_bundle(
    path: str | Path,
    bundle: Mapping[str, Any],
    *,
    overwrite_identical: bool = True,
) -> str:
    destination = Path(path)
    data = canonical_json_bytes(bundle)
    digest = _sha256_bytes(data)
    if destination.exists():
        current = destination.read_bytes()
        if current == data and overwrite_identical:
            return digest
        raise ObservationBundleError("immutable observation bundle already exists")
    _atomic_write(destination, data)
    return digest


def build_bundle_index(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = sorted(
        (normalize_canonical_value(item) for item in entries),
        key=lambda item: str(item.get("baseline_id") or ""),
    )
    source = {
        "index_schema": OBSERVATION_BUNDLE_INDEX_SCHEMA_VERSION,
        "entries": normalized,
    }
    return {**source, "index_digest": canonical_sha256(source)}


def load_bundle_index(path: str | Path) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationBundleError("observation bundle index is unreadable") from exc
    if raw != canonical_json_bytes(payload):
        raise ObservationBundleError("observation bundle index is not canonical JSON")
    if payload.get("index_schema") != OBSERVATION_BUNDLE_INDEX_SCHEMA_VERSION:
        raise ObservationBundleError("unsupported observation bundle index schema")
    source = {key: value for key, value in payload.items() if key != "index_digest"}
    if payload.get("index_digest") != canonical_sha256(source):
        raise ObservationBundleError("observation bundle index digest mismatch")
    return payload


def find_portable_bundle(
    source: ComparatorInput,
    workspace_root: str | Path,
) -> ObservationSet | None:
    root = Path(workspace_root) / "observation_bundles"
    index_path = root / "index.json"
    if not index_path.is_file():
        return None
    index = load_bundle_index(index_path)
    baseline_id = (
        str(source.provenance.get("source_baseline_id") or "")
        if source.provenance.get("derived_for_self_compare")
        else source.source_id
    )
    match = next(
        (
            item
            for item in index.get("entries") or ()
            if item.get("baseline_id") == baseline_id
        ),
        None,
    )
    if not isinstance(match, Mapping):
        return None
    relative = str(match.get("relative_path") or "")
    path = root / relative
    if path.resolve().parent != root.resolve():
        raise ObservationBundleError("unsafe observation bundle relative path")
    result = load_observation_bundle(
        path,
        expected_document_digest=str(match.get("document_digest") or ""),
        source_kind=source.source_kind.value,
        source_id=source.source_id,
    )
    if result.app_package != str(source.environment.get("app_package") or ""):
        raise ObservationBundleError("observation bundle package mismatch")
    if result.locale != str(source.environment.get("locale") or ""):
        raise ObservationBundleError("observation bundle locale mismatch")
    return replace(
        result,
        app_version_name=(
            str(source.environment.get("app_version_name"))
            if source.environment.get("app_version_name") is not None
            else None
        ),
        app_version_code=(
            int(source.environment["app_version_code"])
            if source.environment.get("app_version_code") is not None
            else None
        ),
    )


def migrate_baseline_observation_bundles(
    baselines: Iterable[ComparatorInput],
    *,
    output_root: str | Path,
    qa_runs_root: str | Path,
    artifact_root: str | Path,
) -> dict[str, Any]:
    root = Path(output_root)
    entries: list[dict[str, Any]] = []
    for baseline in sorted(baselines, key=lambda item: item.source_id):
        observation_set = load_observation_set(
            baseline,
            qa_runs_root=qa_runs_root,
            artifact_root=artifact_root,
        )
        bundle = build_observation_bundle(
            observation_set, baseline_id=baseline.source_id
        )
        filename = f"{baseline.source_id}.observations.json"
        digest = write_observation_bundle(root / filename, bundle)
        entries.append(
            {
                "baseline_id": baseline.source_id,
                "relative_path": filename,
                "document_digest": digest,
                "bundle_id": bundle["bundle_id"],
                "observation_identity_digest": (
                    observation_set.observation_identity_digest
                ),
                "observation_count": len(observation_set.observations),
                "locale": observation_set.locale,
                "app_package": observation_set.app_package,
            }
        )
    index = build_bundle_index(entries)
    index_path = root / "index.json"
    data = canonical_json_bytes(index)
    if index_path.exists() and index_path.read_bytes() != data:
        raise ObservationBundleError("immutable observation bundle index differs")
    if not index_path.exists():
        _atomic_write(index_path, data)
    return index


__all__ = [
    "OBSERVATION_BUNDLE_INDEX_SCHEMA_VERSION",
    "OBSERVATION_BUNDLE_SCHEMA_VERSION",
    "ObservationBundleError",
    "build_bundle_index",
    "build_observation_bundle",
    "find_portable_bundle",
    "load_bundle_index",
    "load_observation_bundle",
    "migrate_baseline_observation_bundles",
    "write_observation_bundle",
]
