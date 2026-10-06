from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


SCHEMA_VERSION = "repository-provenance-v1"
GitReader = Callable[[tuple[str, ...]], str | None]


def _git_reader(repo_root: Path) -> GitReader:
    def read(args: tuple[str, ...]) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout

    return read


def _status_records(raw_status: str | None) -> list[dict[str, str]] | None:
    if raw_status is None:
        return None
    records: list[dict[str, str]] = []
    for line in raw_status.splitlines():
        if len(line) < 3:
            continue
        status = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        records.append({"status": status, "path": path})
    return records


def collect_repository_provenance(
    repo_root: Path,
    *,
    git_reader: GitReader | None = None,
    captured_at: str | None = None,
) -> dict[str, object]:
    reader = git_reader or _git_reader(Path(repo_root))
    raw_status = reader(("status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"))
    parsed_status_records = _status_records(raw_status)
    status_records = parsed_status_records or []
    staged = [item["path"] for item in status_records if item["status"][0] not in {" ", "?", "!"}]
    tracked_modified = [
        item["path"]
        for item in status_records
        if item["status"] not in {"??", "!!"} and item["status"][1] not in {" ", "?", "!"}
    ]
    untracked = [item["path"] for item in status_records if item["status"] == "??"]
    ignored = [item["path"] for item in status_records if item["status"] == "!!"]
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repository_root": str(Path(repo_root).resolve()),
        "branch": (reader(("branch", "--show-current")) or "").strip() or None,
        "head": (reader(("rev-parse", "HEAD")) or "").strip() or None,
        "origin_main": (reader(("rev-parse", "origin/main")) or "").strip() or None,
        "git_status_short": [f"{item['status']} {item['path']}" for item in status_records],
        "staged_paths": staged,
        "tracked_modified_paths": tracked_modified,
        "untracked_paths": untracked,
        "ignored_paths": ignored,
        "status_available": raw_status is not None,
        "dirty": (
            bool([item for item in status_records if item["status"] != "!!"])
            if parsed_status_records is not None
            else None
        ),
        "path_count": len(status_records),
    }


def capture_repository_provenance(
    repo_root: Path,
    output_dir: Path,
    *,
    git_reader: GitReader | None = None,
    captured_at: str | None = None,
) -> tuple[dict[str, object], Path]:
    provenance = collect_repository_provenance(
        repo_root, git_reader=git_reader, captured_at=captured_at
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "repository_provenance.json"
    temporary_path = artifact_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(artifact_path)
    return provenance, artifact_path


__all__ = [
    "SCHEMA_VERSION",
    "capture_repository_provenance",
    "collect_repository_provenance",
]
