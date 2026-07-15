"""Local content-addressed artifact pinning for approved baselines."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tb_runner.baseline_repository_schema import ARTIFACT_METADATA_SCHEMA_VERSION
from tb_runner.canonical_json import canonical_json_bytes


@dataclass(frozen=True)
class PinnedArtifact:
    digest: str
    reference: str
    size: int
    payload_path: Path
    deduplicated: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ContentAddressedArtifactStore:
    def __init__(self, root: str | Path, *, clock: Callable[[], str] | None = None) -> None:
        self.root = Path(root)
        self._clock = clock or (lambda: "")

    def location(self, digest: str) -> Path:
        digest = str(digest).lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("artifact digest must be a 64-character lowercase SHA-256")
        return self.root / "sha256" / digest[:2] / digest

    def pin(
        self,
        source: str | Path,
        expected_digest: str,
        *,
        media_type: str,
        schema_version: str | None,
        contains_sensitive_data: bool,
        retention_class: str,
    ) -> PinnedArtifact:
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(f"artifact is unavailable: {source_path.name}")
        expected_digest = str(expected_digest).lower()
        if sha256_file(source_path) != expected_digest:
            raise ValueError(f"artifact checksum mismatch: {source_path.name}")

        destination = self.location(expected_digest)
        payload = destination / "payload"
        if payload.is_file():
            if sha256_file(payload) != expected_digest:
                raise ValueError(f"pinned artifact is corrupt: {expected_digest}")
            return PinnedArtifact(
                expected_digest,
                f"artifact://sha256/{expected_digest}",
                payload.stat().st_size,
                payload,
                True,
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{expected_digest}.tmp-{uuid.uuid4().hex}"
        temporary.mkdir()
        try:
            temporary_payload = temporary / "payload"
            shutil.copyfile(source_path, temporary_payload)
            if sha256_file(temporary_payload) != expected_digest:
                raise ValueError(f"artifact changed while pinning: {source_path.name}")
            metadata: dict[str, Any] = {
                "schema_version": ARTIFACT_METADATA_SCHEMA_VERSION,
                "digest": {"algorithm": "SHA-256", "value": expected_digest},
                "size": temporary_payload.stat().st_size,
                "media_type": media_type,
                "source_schema_version": schema_version,
                "contains_sensitive_data": bool(contains_sensitive_data),
                "retention_class": retention_class,
                "pinned_at": self._clock(),
            }
            (temporary / "metadata.json").write_bytes(canonical_json_bytes(metadata))
            try:
                os.replace(temporary, destination)
            except OSError:
                if payload.is_file() and sha256_file(payload) == expected_digest:
                    shutil.rmtree(temporary, ignore_errors=True)
                else:
                    raise
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return PinnedArtifact(
            expected_digest,
            f"artifact://sha256/{expected_digest}",
            payload.stat().st_size,
            payload,
            False,
        )


__all__ = ["ContentAddressedArtifactStore", "PinnedArtifact", "sha256_file"]
