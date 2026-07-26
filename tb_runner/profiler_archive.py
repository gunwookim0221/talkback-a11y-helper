from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tb_runner.canonical_json import canonical_json_bytes
from tb_runner.traversal_profiler import PROFILER_SCHEMA_VERSION


PROFILER_ARCHIVE_SCHEMA_VERSION = "traversal-profiler-archive-v1"
PROFILER_ARCHIVE_MANIFEST = "manifest.json"
PROFILER_ARCHIVE_SUFFIX = ".profiler.zip"
PROFILER_DIRECTORY_SUFFIX = ".profiler"
PROFILER_ENTRY_SUFFIX = ".profiler.json"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class ProfilerArchive:
    profiles: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _profile_payload(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"profiler payload is not an object: {path}")
    if payload.get("schema_version") != PROFILER_SCHEMA_VERSION:
        raise ValueError(f"unsupported profiler schema: {path}")
    return payload, canonical_json_bytes(payload)


def create_profiler_archive(
    profiler_directory: str | Path,
    archive_path: str | Path | None = None,
) -> Path:
    source = Path(profiler_directory)
    profiles: list[tuple[str, dict[str, Any], bytes]] = []
    for path in sorted(source.glob(f"*{PROFILER_ENTRY_SUFFIX}"), key=lambda item: item.name):
        payload, encoded = _profile_payload(path)
        profiles.append((f"profiler/{path.name}", payload, encoded))
    if not profiles:
        raise ValueError(f"profiler directory has no profiler JSON: {source}")

    target = (
        Path(archive_path)
        if archive_path is not None
        else source.with_suffix(PROFILER_ARCHIVE_SUFFIX)
    )
    manifest = {
        "schema_version": PROFILER_ARCHIVE_SCHEMA_VERSION,
        "profiler_schema_version": PROFILER_SCHEMA_VERSION,
        "entry_count": len(profiles),
        "entries": [
            {
                "path": name,
                "scenario": str(payload.get("scenario") or ""),
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "size": len(encoded),
            }
            for name, payload, encoded in profiles
        ],
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.writestr(
                _zip_info(PROFILER_ARCHIVE_MANIFEST),
                canonical_json_bytes(manifest),
            )
            for name, _payload, encoded in profiles:
                archive.writestr(_zip_info(name), encoded)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def create_profiler_archives(run_root: str | Path) -> tuple[Path, ...]:
    root = Path(run_root)
    directories = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir() and path.name.endswith(PROFILER_DIRECTORY_SUFFIX)
        ),
        key=lambda path: path.name,
    ) if root.is_dir() else []
    return tuple(create_profiler_archive(path) for path in directories)


def read_profiler_archive(path: str | Path) -> ProfilerArchive:
    profiles: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    encoded_entries: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if PROFILER_ARCHIVE_MANIFEST in names:
            value = json.loads(archive.read(PROFILER_ARCHIVE_MANIFEST))
            if not isinstance(value, dict):
                raise ValueError("profiler archive manifest is not an object")
            if value.get("schema_version") != PROFILER_ARCHIVE_SCHEMA_VERSION:
                raise ValueError("unsupported profiler archive schema")
            manifest = value
        for name in sorted(names):
            if not name.endswith(PROFILER_ENTRY_SUFFIX):
                continue
            encoded = archive.read(name)
            value = json.loads(encoded)
            if not isinstance(value, Mapping):
                raise ValueError(f"profiler archive entry is not an object: {name}")
            payload = dict(value)
            if payload.get("schema_version") != PROFILER_SCHEMA_VERSION:
                raise ValueError(f"unsupported profiler entry schema: {name}")
            profiles.append(payload)
            encoded_entries.append((name, encoded))
    if not profiles:
        raise ValueError("profiler archive has no profiler entries")
    if manifest and int(manifest.get("entry_count") or -1) != len(profiles):
        raise ValueError("profiler archive manifest entry count mismatch")
    if manifest:
        manifest_entries = manifest.get("entries")
        if not isinstance(manifest_entries, list):
            raise ValueError("profiler archive manifest entries are missing")
        expected_entries = {
            str(item.get("path") or ""): item
            for item in manifest_entries
            if isinstance(item, Mapping)
        }
        if set(expected_entries) != {name for name, _encoded in encoded_entries}:
            raise ValueError("profiler archive manifest paths mismatch")
        for name, encoded in encoded_entries:
            expected = expected_entries[name]
            if int(expected.get("size") or -1) != len(encoded):
                raise ValueError(f"profiler archive entry size mismatch: {name}")
            if expected.get("sha256") != hashlib.sha256(encoded).hexdigest():
                raise ValueError(f"profiler archive entry digest mismatch: {name}")
    return ProfilerArchive(tuple(profiles), manifest)


__all__ = [
    "PROFILER_ARCHIVE_MANIFEST",
    "PROFILER_ARCHIVE_SCHEMA_VERSION",
    "PROFILER_ARCHIVE_SUFFIX",
    "PROFILER_ENTRY_SUFFIX",
    "ProfilerArchive",
    "create_profiler_archive",
    "create_profiler_archives",
    "read_profiler_archive",
]
