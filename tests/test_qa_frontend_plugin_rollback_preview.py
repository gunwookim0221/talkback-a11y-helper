from __future__ import annotations

from fastapi.testclient import TestClient

from qa_frontend.backend import main


def test_plugin_onboarding_rollback_preview_route_returns_schema(monkeypatch):
    monkeypatch.setattr(
        main,
        "preview_session_rollback",
        lambda session_id: {
            "ok": True,
            "schema_version": "plugin-rollback-preview-v1",
            "rollback_status": "preview_ready",
            "can_rollback": True,
            "target_files": ["tb_runner/scenario_config.py", "config/runtime_config.json"],
            "backup": {"found": True, "paths": ["output/plugin_draft_backups/x/scenario_config.py.bak"]},
            "preview": {
                "scenario_entry_will_be_removed": True,
                "runtime_config_entry_will_be_removed": True,
                "diff_preview": "scenario_config.py:\n...",
            },
            "diagnostics": {"warnings": [], "errors": []},
        },
    )
    client = TestClient(main.app)

    response = client.post("/api/plugin-onboarding/session/onboarding_1/rollback/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "plugin-rollback-preview-v1"
    assert body["can_rollback"] is True


def test_plugin_onboarding_rollback_preview_route_missing_session(monkeypatch):
    def raise_missing(session_id):
        raise FileNotFoundError("session_not_found")

    monkeypatch.setattr(main, "preview_session_rollback", raise_missing)
    client = TestClient(main.app)

    response = client.post("/api/plugin-onboarding/session/missing/rollback/preview")

    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"


def test_plugin_onboarding_rollback_execute_route_returns_schema(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "idle"})
    monkeypatch.setattr(
        main,
        "execute_session_rollback",
        lambda session_id, request: {
            "ok": True,
            "schema_version": "plugin-rollback-execute-v1",
            "rollback_status": "rolled_back",
            "session_id": session_id,
            "restored_files": ["tb_runner/scenario_config.py", "config/runtime_config.json"],
            "backup": {"paths": ["output/plugin_draft_backups/x/scenario_config.py.bak"]},
            "pre_rollback_backup": ["output/plugin_rollback_execute_backups/x/scenario_config.py.before_rollback"],
            "diagnostics": {"warnings": [], "errors": []},
        },
    )
    client = TestClient(main.app)

    response = client.post("/api/plugin-onboarding/session/onboarding_1/rollback", json={"confirm": True})

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "plugin-rollback-execute-v1"
    assert body["rollback_status"] == "rolled_back"


def test_plugin_onboarding_rollback_execute_route_blocks_while_running(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "running"})
    client = TestClient(main.app)

    response = client.post("/api/plugin-onboarding/session/onboarding_1/rollback", json={"confirm": True})

    assert response.status_code == 409
    assert response.json()["detail"] == "Rollback is blocked while a run is in progress"
