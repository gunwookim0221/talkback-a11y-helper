from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tb_runner.profiler_archive import (
    PROFILER_ARCHIVE_MANIFEST,
    PROFILER_ARCHIVE_SCHEMA_VERSION,
    create_profiler_archives,
    read_profiler_archive,
)
from tb_runner.traversal_profiler import PROFILER_SCHEMA_VERSION


def _write_profile(directory: Path, scenario: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{scenario}.profiler.json").write_text(
        json.dumps(
            {
                "schema_version": PROFILER_SCHEMA_VERSION,
                "scenario": scenario,
                "runtime_ms": 1.0,
                "metrics": {},
                "recovery": [],
                "counters": {},
            }
        ),
        encoding="utf-8",
    )


def test_profiler_archive_is_deterministic_and_keeps_json(tmp_path: Path) -> None:
    profile_dir = tmp_path / "talkback_compare.profiler"
    _write_profile(profile_dir, "scenario_b")
    _write_profile(profile_dir, "scenario_a")

    first = create_profiler_archives(tmp_path)
    first_bytes = first[0].read_bytes()
    second = create_profiler_archives(tmp_path)

    assert first == second
    assert second[0].read_bytes() == first_bytes
    assert sorted(path.name for path in profile_dir.glob("*.profiler.json")) == [
        "scenario_a.profiler.json",
        "scenario_b.profiler.json",
    ]
    with zipfile.ZipFile(first[0]) as archive:
        assert archive.namelist() == [
            PROFILER_ARCHIVE_MANIFEST,
            "profiler/scenario_a.profiler.json",
            "profiler/scenario_b.profiler.json",
        ]
        manifest = json.loads(archive.read(PROFILER_ARCHIVE_MANIFEST))
    assert manifest["schema_version"] == PROFILER_ARCHIVE_SCHEMA_VERSION
    assert [entry["scenario"] for entry in manifest["entries"]] == [
        "scenario_a",
        "scenario_b",
    ]


def test_profiler_archive_reader_accepts_new_and_legacy_contracts(tmp_path: Path) -> None:
    profile_dir = tmp_path / "talkback_compare.profiler"
    _write_profile(profile_dir, "new_scenario")
    archive_path = create_profiler_archives(tmp_path)[0]

    new_archive = read_profiler_archive(archive_path)
    assert [item["scenario"] for item in new_archive.profiles] == ["new_scenario"]
    assert new_archive.manifest["schema_version"] == PROFILER_ARCHIVE_SCHEMA_VERSION

    legacy_path = tmp_path / "legacy.profiler.zip"
    with zipfile.ZipFile(legacy_path, "w") as archive:
        archive.writestr(
            "profiler/legacy.profiler.json",
            json.dumps(
                {
                    "schema_version": PROFILER_SCHEMA_VERSION,
                    "scenario": "legacy",
                    "metrics": {},
                    "recovery": [],
                    "counters": {},
                }
            ),
        )
    legacy_archive = read_profiler_archive(legacy_path)
    assert [item["scenario"] for item in legacy_archive.profiles] == ["legacy"]
    assert legacy_archive.manifest == {}
