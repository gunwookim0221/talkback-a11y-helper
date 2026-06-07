from __future__ import annotations

from tb_runner.plugin_onboarding_session import (
    create_onboarding_session,
    preview_onboarding_rollback,
    save_onboarding_step,
)


def _write_project_files(project_root, scenario_id="life_home_care_plugin"):
    scenario_path = project_root / "tb_runner" / "scenario_config.py"
    runtime_path = project_root / "config" / "runtime_config.json"
    backup_root = project_root / "output" / "plugin_draft_backups" / "20260607_173000"
    scenario_backup = backup_root / "scenario_config.py.bak"
    runtime_backup = backup_root / "runtime_config.json.bak"
    scenario_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(f'TAB_CONFIGS = [{{"scenario_id": "{scenario_id}"}}]\n', encoding="utf-8")
    runtime_path.write_text(f'{{"scenarios": {{"{scenario_id}": {{"enabled": false}}}}}}\n', encoding="utf-8")
    scenario_backup.write_text("TAB_CONFIGS = []\n", encoding="utf-8")
    runtime_backup.write_text('{"scenarios": {}}\n', encoding="utf-8")
    return scenario_backup, runtime_backup


def _session_with_apply(tmp_path, project_root, scenario_id="life_home_care_plugin"):
    created = create_onboarding_session({"label": "Home Care", "stable_label": "Home Care", "type": "life"}, tmp_path)
    scenario_backup, runtime_backup = _write_project_files(project_root, scenario_id)
    save_onboarding_step(
        created["session_id"],
        "apply",
        "applied",
        {
            "apply_status": "applied",
            "backup": {"created": True, "paths": [str(scenario_backup), str(runtime_backup)]},
            "applied": {"scenario_id": scenario_id, "runtime_config_key": scenario_id},
        },
        tmp_path,
    )
    return created


def test_rollback_preview_ready(tmp_path):
    project_root = tmp_path / "project"
    created = _session_with_apply(tmp_path / "sessions", project_root)

    result = preview_onboarding_rollback(created["session_id"], tmp_path / "sessions", project_root)

    assert result["schema_version"] == "plugin-rollback-preview-v1"
    assert result["rollback_status"] == "preview_ready"
    assert result["can_rollback"] is True
    assert result["backup"]["found"] is True
    assert result["preview"]["scenario_entry_will_be_removed"] is True
    assert result["preview"]["runtime_config_entry_will_be_removed"] is True


def test_rollback_preview_blocks_backup_missing(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path / "sessions")
    project_root = tmp_path / "project"
    _write_project_files(project_root, "device_tv_plugin")
    save_onboarding_step(
        created["session_id"],
        "apply",
        "applied",
        {
            "backup": {"created": True, "paths": []},
            "applied": {"scenario_id": "device_tv_plugin", "runtime_config_key": "device_tv_plugin"},
        },
        tmp_path / "sessions",
    )

    result = preview_onboarding_rollback(created["session_id"], tmp_path / "sessions", project_root)

    assert result["can_rollback"] is False
    assert "backup missing" in result["diagnostics"]["errors"]


def test_rollback_preview_blocks_apply_payload_missing(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path / "sessions")

    result = preview_onboarding_rollback(created["session_id"], tmp_path / "sessions", tmp_path / "project")

    assert result["can_rollback"] is False
    assert "apply payload missing" in result["diagnostics"]["errors"]


def test_rollback_preview_blocks_missing_scenario_and_runtime_key(tmp_path):
    project_root = tmp_path / "project"
    scenario_backup, runtime_backup = _write_project_files(project_root, "device_tv_plugin")
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path / "sessions")
    save_onboarding_step(
        created["session_id"],
        "apply",
        "applied",
        {"backup": {"created": True, "paths": [str(scenario_backup), str(runtime_backup)]}},
        tmp_path / "sessions",
    )

    result = preview_onboarding_rollback(created["session_id"], tmp_path / "sessions", project_root)

    assert result["can_rollback"] is False
    assert "scenario id missing" in result["diagnostics"]["errors"]
    assert "runtime key missing" in result["diagnostics"]["errors"]


def test_rollback_preview_generates_diff(tmp_path):
    project_root = tmp_path / "project"
    created = _session_with_apply(tmp_path / "sessions", project_root)

    result = preview_onboarding_rollback(created["session_id"], tmp_path / "sessions", project_root)

    diff_preview = result["preview"]["diff_preview"]
    assert "scenario_config.py:" in diff_preview
    assert "runtime_config.json:" in diff_preview
    assert "--- current/scenario_config.py" in diff_preview
