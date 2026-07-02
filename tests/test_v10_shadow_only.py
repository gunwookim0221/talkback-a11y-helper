from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa_frontend.backend.shadow_only import (
    inspect_shadow_only_run,
    run_shadow_only,
)
from tools.run_v10_shadow_only import main


def _device_run(tmp_path: Path, *, shadow_enabled: bool = False) -> Path:
    run_dir = tmp_path / "batch_001" / "device_SERIAL"
    run_dir.mkdir(parents=True)
    (run_dir / "runtime_config.json").write_text(
        json.dumps(
            {
                "v10": {
                    "feature_flags": {
                        "inventory_enabled": shadow_enabled,
                        "quick_identify_enabled": shadow_enabled,
                        "policy_mapping_enabled": shadow_enabled,
                        "shadow_validation_enabled": shadow_enabled,
                    }
                },
                "scenarios": {
                    "device_motion_sensor_plugin": {"enabled": True},
                    "device_tv_plugin": {"enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "batch_id": "batch_001",
                "serial": "SERIAL",
                "model": "Device",
                "return_code": 0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "runner.log").write_text("legacy\n", encoding="utf-8")
    (run_dir / "talkback_compare.normal.log").write_text("normal\n", encoding="utf-8")
    (run_dir / "talkback_compare.xlsx").write_bytes(b"legacy-xlsx")
    return run_dir


def test_valid_run_dir_dry_run_reads_metadata_without_output(tmp_path):
    run_dir = _device_run(tmp_path)

    result = run_shadow_only(run_dir, dry_run=True)

    assert result["status"] == "validated"
    assert result["scenario_ids"] == ["device_motion_sensor_plugin"]
    assert result["serial"] == "SERIAL"
    assert result["run_id"] == "batch_001"
    assert not (run_dir / "shadow").exists()


def test_invalid_run_dir_fails(tmp_path):
    with pytest.raises(ValueError, match="run_dir_invalid"):
        inspect_shadow_only_run(tmp_path / "missing")
    assert main(["--run-dir", str(tmp_path / "missing"), "--dry-run"]) == 2


def test_run_dir_requires_legacy_result_artifact(tmp_path):
    run_dir = _device_run(tmp_path)
    (run_dir / "runner.log").unlink()
    (run_dir / "talkback_compare.normal.log").unlink()
    (run_dir / "talkback_compare.xlsx").unlink()

    with pytest.raises(ValueError, match="legacy_artifacts_missing"):
        inspect_shadow_only_run(run_dir)


def test_existing_shadow_requires_overwrite_and_replaces_known_artifacts(tmp_path):
    run_dir = _device_run(tmp_path)
    shadow_dir = run_dir / "shadow"
    shadow_dir.mkdir()
    stale = shadow_dir / "shadow_error.json"
    stale.write_text("stale", encoding="utf-8")

    with pytest.raises(ValueError, match="shadow_output_exists"):
        run_shadow_only(run_dir, pipeline_runner=lambda **kwargs: {"status": "completed"})

    def pipeline_runner(**kwargs):
        assert kwargs["artifact_dir"] == shadow_dir
        assert not stale.exists()
        (shadow_dir / "shadow_report.md").write_text("new", encoding="utf-8")
        return {"status": "completed"}

    result = run_shadow_only(
        run_dir,
        overwrite_shadow=True,
        pipeline_runner=pipeline_runner,
    )
    assert result["status"] == "completed"
    assert (shadow_dir / "shadow_report.md").read_text(encoding="utf-8") == "new"


def test_output_suffix_uses_separate_shadow_directory(tmp_path):
    run_dir = _device_run(tmp_path)
    captured: dict[str, object] = {}

    def pipeline_runner(**kwargs):
        captured.update(kwargs)
        return {"status": "completed"}

    result = run_shadow_only(
        run_dir,
        output_suffix="duplicate_fix",
        pipeline_runner=pipeline_runner,
    )

    assert Path(result["artifact_dir"]) == run_dir / "shadow_duplicate_fix"
    assert captured["artifact_dir"] == run_dir / "shadow_duplicate_fix"
    assert not (run_dir / "shadow").exists()


def test_pipeline_exception_writes_failure_artifacts(tmp_path):
    run_dir = _device_run(tmp_path)

    result = run_shadow_only(
        run_dir,
        pipeline_runner=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("probe_failed")),
    )

    shadow_dir = run_dir / "shadow"
    assert result["status"] == "warning"
    assert result["legacy_result_preserved"] is True
    error = json.loads((shadow_dir / "shadow_error.json").read_text(encoding="utf-8"))
    assert error["stage"] == "shadow_only_execution"
    assert error["error"] == "probe_failed"
    assert "Legacy result preserved: true" in (
        shadow_dir / "shadow_report.md"
    ).read_text(encoding="utf-8")


def test_shadow_only_forces_temp_flags_and_preserves_legacy_artifacts(tmp_path):
    run_dir = _device_run(tmp_path, shadow_enabled=False)
    protected = [
        run_dir / "runtime_config.json",
        run_dir / "summary.json",
        run_dir / "runner.log",
        run_dir / "talkback_compare.normal.log",
        run_dir / "talkback_compare.xlsx",
    ]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected}

    def pipeline_runner(**kwargs):
        forced = json.loads(
            Path(kwargs["runtime_config_path"]).read_text(encoding="utf-8")
        )
        assert all(forced["v10"]["feature_flags"].values())
        assert Path(kwargs["runtime_config_path"]) != run_dir / "runtime_config.json"
        return {"status": "completed"}

    result = run_shadow_only(run_dir, pipeline_runner=pipeline_runner)

    assert result["status"] == "completed"
    for path in protected:
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before[path]
