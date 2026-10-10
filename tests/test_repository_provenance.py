from __future__ import annotations

import json

from qa_frontend.backend.repository_provenance import (
    capture_repository_provenance,
    collect_repository_provenance,
)


def test_repository_provenance_records_git_state_and_path_classes(tmp_path):
    values = {
        ("branch", "--show-current"): "fix/test\n",
        ("rev-parse", "HEAD"): "abc123\n",
        ("rev-parse", "origin/main"): "def456\n",
        (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
        ): "M  staged.py\n M modified.py\n?? new.py\n!! cache.bin\n",
    }

    result = collect_repository_provenance(
        tmp_path,
        git_reader=lambda args: values.get(args),
        captured_at="2026-10-07T00:00:00+00:00",
    )

    assert result["branch"] == "fix/test"
    assert result["head"] == "abc123"
    assert result["origin_main"] == "def456"
    assert result["staged_paths"] == ["staged.py"]
    assert result["tracked_modified_paths"] == ["modified.py"]
    assert result["untracked_paths"] == ["new.py"]
    assert result["ignored_paths"] == ["cache.bin"]
    assert result["dirty"] is True
    assert result["status_available"] is True


def test_provenance_artifact_is_written_and_json_readable(tmp_path):
    values = {
        ("branch", "--show-current"): "main\n",
        ("rev-parse", "HEAD"): "abc123\n",
        ("rev-parse", "origin/main"): "abc123\n",
        (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
        ): "",
    }

    result, path = capture_repository_provenance(
        tmp_path / "repo",
        tmp_path / "run",
        git_reader=lambda args: values.get(args),
    )

    assert path.name == "repository_provenance.json"
    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert result["dirty"] is False
    assert result["path_count"] == 0
