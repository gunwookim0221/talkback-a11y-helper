from __future__ import annotations

from fastapi.testclient import TestClient

from qa_frontend.backend import main
from qa_frontend.backend.plugin_onboarding_session import (
    PluginOnboardingSessionCreateRequest,
    PluginOnboardingSessionStepRequest,
    create_session,
    get_session,
    list_sessions,
    save_session_step,
)


def test_plugin_onboarding_create_route_returns_schema(monkeypatch):
    monkeypatch.setattr(
        main,
        "create_session",
        lambda request: {
            "ok": True,
            "schema_version": "plugin-onboarding-session-v1",
            "session_id": "onboarding_20260607_183000_home_care",
        },
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/plugin-onboarding/session",
        json={"card": {"label": "Home Care", "stable_label": "Home Care", "type": "life"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "plugin-onboarding-session-v1"
    assert body["session_id"] == "onboarding_20260607_183000_home_care"


def test_plugin_onboarding_step_route_returns_schema(monkeypatch):
    monkeypatch.setattr(
        main,
        "save_session_step",
        lambda session_id, request: {
            "ok": True,
            "schema_version": "plugin-onboarding-session-v1",
            "session": {
                "session_id": session_id,
                "status": "probed",
                "plugin": {"label": "Home Care", "stable_label": "Home Care", "type": "life", "scenario_id": ""},
                "steps": {"probe": {"status": "completed", "payload": {}}},
                "feedback": {"warnings": [], "errors": [], "suggestions": []},
                "created_at": "2026-06-07T18:30:00+09:00",
                "updated_at": "2026-06-07T18:31:00+09:00",
                "schema_version": "plugin-onboarding-session-v1",
            },
        },
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/plugin-onboarding/session/onboarding_1/step",
        json={"step": "probe", "status": "completed", "payload": {}},
    )

    assert response.status_code == 200
    assert response.json()["session"]["status"] == "probed"


def test_plugin_onboarding_get_and_list_routes(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_session",
        lambda session_id: {
            "ok": True,
            "schema_version": "plugin-onboarding-session-v1",
            "session": {"session_id": session_id, "status": "created"},
        },
    )
    monkeypatch.setattr(
        main,
        "list_sessions",
        lambda limit=20: {
            "ok": True,
            "schema_version": "plugin-onboarding-session-v1",
            "sessions": [{"session_id": "onboarding_1", "status": "created"}],
        },
    )
    client = TestClient(main.app)

    get_response = client.get("/api/plugin-onboarding/session/onboarding_1")
    list_response = client.get("/api/plugin-onboarding/sessions")

    assert get_response.status_code == 200
    assert get_response.json()["session"]["session_id"] == "onboarding_1"
    assert list_response.status_code == 200
    assert list_response.json()["sessions"][0]["session_id"] == "onboarding_1"


def test_plugin_onboarding_restore_route_returns_schema(monkeypatch):
    monkeypatch.setattr(
        main,
        "restore_session",
        lambda session_id: {
            "ok": True,
            "schema_version": "plugin-onboarding-restore-v1",
            "session": {"session_id": session_id, "status": "smoke_passed"},
            "restored_state": {
                "selected_card": {"label": "TV", "stable_label": "TV", "type": "device"},
                "probe_result": {},
                "draft_result": {},
                "review_result": {},
                "apply_result": {},
                "smoke_start_result": {},
                "smoke_status_result": {"summary": {"result_status": "PASS"}},
            },
            "recommendation": {
                "next_action": "ready_for_manual_validation",
                "severity": "success",
                "reasons": ["Smoke result PASS"],
                "allowed_actions": ["manual_validation", "commit_changes"],
                "blocked_actions": [],
            },
        },
    )
    client = TestClient(main.app)

    response = client.get("/api/plugin-onboarding/session/onboarding_1/restore")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "plugin-onboarding-restore-v1"
    assert body["recommendation"]["next_action"] == "ready_for_manual_validation"


def test_plugin_onboarding_service_create_and_update(monkeypatch, tmp_path):
    monkeypatch.setattr("qa_frontend.backend.plugin_onboarding_session.SESSION_ROOT", tmp_path)
    created = create_session(
        PluginOnboardingSessionCreateRequest(
            card={"label": "TV", "stable_label": "TV", "type": "device"},
        )
    )

    updated = save_session_step(
        created["session_id"],
        PluginOnboardingSessionStepRequest(
            step="smoke",
            status="completed",
            payload={"summary": {"result_status": "PASS", "failure_reason": ""}, "diagnostics": {"warnings": [], "errors": []}},
        ),
    )

    assert updated["session"]["status"] == "smoke_passed"
    assert "Ready for manual validation" in updated["session"]["feedback"]["suggestions"]
    assert get_session(created["session_id"])["session"]["session_id"] == created["session_id"]
    assert list_sessions()["sessions"][0]["session_id"] == created["session_id"]


def test_plugin_onboarding_invalid_step_route_rejects(monkeypatch, tmp_path):
    monkeypatch.setattr("qa_frontend.backend.plugin_onboarding_session.SESSION_ROOT", tmp_path)
    created = create_session(
        PluginOnboardingSessionCreateRequest(
            card={"label": "TV", "stable_label": "TV", "type": "device"},
        )
    )
    client = TestClient(main.app)

    response = client.post(
        f"/api/plugin-onboarding/session/{created['session_id']}/step",
        json={"step": "rollback", "status": "completed", "payload": {}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_step"
