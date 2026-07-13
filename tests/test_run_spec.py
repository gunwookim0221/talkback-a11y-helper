from __future__ import annotations

import os
from pathlib import Path

from qa_frontend.backend.runtime_setup import prepare_runtime
from tb_runner.run_selection import apply_run_selection
from tb_runner.run_spec import RunContext, RunSpec, resolve_identity_feature_flags


def test_run_spec_builds_shared_cli_command_and_environment():
    spec = RunSpec(
        serial="SERIAL-1",
        mode="smoke",
        language_mode="ko-KR",
        launch_mode="clean",
        scenario_ids=("global_nav_main", "device_tv_plugin"),
        output_dir="runs/device",
        runtime_config_path="runs/device/runtime_config.json",
    )

    assert spec.build_script_command(Path("script_test.py")) == [
        os.sys.executable,
        "script_test.py",
        "--serial",
        "SERIAL-1",
        "--output-dir",
        "runs/device",
        "--mode",
        "smoke",
        "--language-mode",
        "ko-KR",
        "--launch-mode",
        "clean",
        "--scenario",
        "global_nav_main",
        "--scenario",
        "device_tv_plugin",
    ]
    env = spec.build_subprocess_env({"KEEP": "1"})
    assert env["ANDROID_SERIAL"] == "SERIAL-1"
    assert env["TB_OUTPUT_DIR"] == "runs/device"
    assert env["TB_RUNTIME_CONFIG_PATH"] == "runs/device/runtime_config.json"
    assert "TB_V8_COVERAGE_PROBE" not in env
    assert RunContext(spec).serial == "SERIAL-1"

def test_run_spec_builds_subprocess_env_with_coverage_probe():
    spec = RunSpec(enable_coverage_probe=True)
    env = spec.build_subprocess_env()
    assert env["TB_V8_COVERAGE_PROBE"] == "1"

    spec_disabled = RunSpec(enable_coverage_probe=False)
    env_disabled = spec_disabled.build_subprocess_env()
    assert "TB_V8_COVERAGE_PROBE" not in env_disabled


def test_run_spec_identity_v2_is_default_and_legacy_compatibility_is_explicit():
    base = {
        "TB_EVIDENCE_LEDGER_ENABLED": "1",
        "TB_EVIDENCE_IDENTITY_SHADOW_ENABLED": "1",
        "TB_TRAVERSAL_IDENTITY_V2_ENABLED": "1",
    }
    default = RunSpec().build_subprocess_env(base)
    assert default["TB_EVIDENCE_LEDGER_ENABLED"] == "1"
    assert default["TB_EVIDENCE_IDENTITY_SHADOW_ENABLED"] == "1"
    assert default["TB_TRAVERSAL_IDENTITY_V2_ENABLED"] == "1"
    ledger = RunSpec(evidence_ledger=True, traversal_identity_v2=False).build_subprocess_env({})
    assert ledger["TB_EVIDENCE_LEDGER_ENABLED"] == "1"
    assert "TB_EVIDENCE_IDENTITY_SHADOW_ENABLED" not in ledger
    assert ledger["TB_TRAVERSAL_IDENTITY_V2_ENABLED"] == "0"
    identity = RunSpec(identity_shadow_v2=True, traversal_identity_v2=False).build_subprocess_env({})
    assert identity["TB_EVIDENCE_LEDGER_ENABLED"] == "1"
    assert identity["TB_EVIDENCE_IDENTITY_SHADOW_ENABLED"] == "1"
    traversal = RunSpec(traversal_identity_v2=True).build_subprocess_env({})
    assert traversal["TB_EVIDENCE_LEDGER_ENABLED"] == "1"
    assert traversal["TB_EVIDENCE_IDENTITY_SHADOW_ENABLED"] == "1"
    assert traversal["TB_TRAVERSAL_IDENTITY_V2_ENABLED"] == "1"
    legacy = RunSpec(traversal_identity_v2=False).build_subprocess_env(traversal)
    assert legacy["TB_TRAVERSAL_IDENTITY_V2_ENABLED"] == "0"


def test_run_spec_profiler_is_default_off_and_run_scoped():
    inherited = {"TB_TRAVERSAL_PROFILER_ENABLED": "1"}
    assert "TB_TRAVERSAL_PROFILER_ENABLED" not in RunSpec().build_subprocess_env(inherited)
    enabled = RunSpec(traversal_profiler=True).build_subprocess_env({})
    assert enabled["TB_TRAVERSAL_PROFILER_ENABLED"] == "1"
    assert "TB_TRAVERSAL_PROFILER_ENABLED" not in RunSpec().build_subprocess_env(enabled)
    assert resolve_identity_feature_flags(traversal_identity_v2=True) == {
        "evidence_ledger": True,
        "identity_shadow_v2": True,
        "traversal_identity_v2": True,
        "runtime_profiler": False,
    }


def test_prepare_runtime_scopes_android_serial(monkeypatch):
    monkeypatch.setenv("ANDROID_SERIAL", "PREVIOUS")
    seen = []

    def language_fn(mode):
        seen.append(("language", mode, os.environ.get("ANDROID_SERIAL")))
        return {"ok": True}

    def preflight_fn(mode):
        seen.append(("preflight", mode, os.environ.get("ANDROID_SERIAL")))
        return {"ok": True}

    prepare_runtime(
        RunSpec(serial="TARGET", language_mode="en-US", launch_mode="warm"),
        language_fn=language_fn,
        preflight_fn=preflight_fn,
    )

    assert seen == [("language", "en-US", "TARGET"), ("preflight", "warm", "TARGET")]
    assert os.environ["ANDROID_SERIAL"] == "PREVIOUS"


def test_run_selection_applies_cli_scenarios_and_shared_smoke_policy():
    configs = [
        {"scenario_id": "global_nav_main", "enabled": True, "max_steps": 20},
        {"scenario_id": "device_tv_plugin", "enabled": True, "max_steps": 30},
        {"scenario_id": "home_main", "enabled": True, "max_steps": 40},
    ]

    selected = apply_run_selection(configs, ["global_nav_main", "device_tv_plugin"], mode="smoke")

    assert [(cfg["scenario_id"], cfg["enabled"], cfg["max_steps"]) for cfg in selected] == [
        ("global_nav_main", True, 6),
        ("device_tv_plugin", True, 8),
        ("home_main", False, 40),
    ]
