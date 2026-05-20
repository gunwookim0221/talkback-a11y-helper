from pathlib import Path

import pytest

from qa_frontend.backend import outputs


def test_safe_output_path_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(outputs, "OUTPUT_DIR", tmp_path)

    with pytest.raises(ValueError):
        outputs.safe_output_path("../runtime_config.json")


def test_safe_output_path_accepts_allowed_file(tmp_path, monkeypatch):
    monkeypatch.setattr(outputs, "OUTPUT_DIR", tmp_path)
    report = tmp_path / "report.log"
    report.write_text("ok", encoding="utf-8")

    assert outputs.safe_output_path("report.log") == report.resolve()


def test_safe_output_path_rejects_unsupported_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(outputs, "OUTPUT_DIR", tmp_path)
    path = tmp_path / "report.txt"
    path.write_text("no", encoding="utf-8")

    with pytest.raises(ValueError):
        outputs.safe_output_path(path.name)
