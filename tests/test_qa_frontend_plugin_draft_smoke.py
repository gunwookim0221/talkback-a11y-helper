from __future__ import annotations

from fastapi.testclient import TestClient

from qa_frontend.backend import main
from qa_frontend.backend.plugin_draft import (
    PluginDraftSmokeRequest,
    PluginDraftSmokeStatusRequest,
    get_draft_smoke_status,
    start_draft_smoke,
)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def start_run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "state": "running",
            "run_id": "20260607_180000",
            "log_path": "qa_frontend_runs/20260607_180000_smoke.log",
        }


def test_plugin_draft_smoke_route_blocks_while_run_is_running(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "running"})
    client = TestClient(main.app)

    response = client.post("/api/plugin-draft/smoke", json={"scenario_id": "life_preview_plugin", "max_steps": 5, "mode": "smoke"})

    assert response.status_code == 409
    assert "run is in progress" in response.json()["detail"]


def test_plugin_draft_smoke_route_returns_schema(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "idle"})
    monkeypatch.setattr(
        main,
        "start_draft_smoke",
        lambda request, runner: {
            "ok": True,
            "schema_version": "plugin-draft-smoke-v1",
            "smoke_status": "started",
            "run_id": "20260607_180000",
            "scenario_id": "life_preview_plugin",
            "max_steps": 5,
            "summary": {
                "pre_navigation_success": False,
                "plugin_open_verified": False,
                "steps_collected": 0,
                "failure_reason": "",
                "result_status": "UNKNOWN",
            },
            "artifacts": {"log_path": "qa_frontend_runs/20260607_180000_smoke.log", "xlsx_path": ""},
            "diagnostics": {"warnings": []},
        },
    )
    client = TestClient(main.app)

    response = client.post("/api/plugin-draft/smoke", json={"scenario_id": "life_preview_plugin", "max_steps": 5, "mode": "smoke"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["schema_version"] == "plugin-draft-smoke-v1"
    assert body["smoke_status"] == "started"


def test_plugin_draft_smoke_status_route_returns_schema(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "idle"})
    monkeypatch.setattr(
        main,
        "get_draft_smoke_status",
        lambda request, runner: {
            "ok": True,
            "schema_version": "plugin-draft-smoke-status-v1",
            "run_id": "20260607_180000",
            "scenario_id": "life_preview_plugin",
            "smoke_status": "completed",
            "run_status": "finished",
            "summary": {
                "pre_navigation_success": True,
                "plugin_open_verified": True,
                "steps_collected": 1,
                "failure_reason": "",
                "result_status": "PASS",
            },
            "artifacts": {
                "log_path": "qa_frontend_runs/20260607_180000_smoke.log",
                "xlsx_path": "",
                "summary_json_path": "",
                "display_urls": {"log": "/api/runs/recent/20260607_180000/log", "xlsx": ""},
            },
            "diagnostics": {"warnings": [], "errors": []},
        },
    )
    client = TestClient(main.app)

    response = client.get("/api/plugin-draft/smoke/20260607_180000?scenario_id=life_preview_plugin")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "plugin-draft-smoke-status-v1"
    assert body["summary"]["result_status"] == "PASS"


def test_plugin_draft_smoke_service_starts_single_scenario(monkeypatch):
    monkeypatch.setattr("qa_frontend.backend.plugin_draft.scenario_id_exists_for_smoke", lambda scenario_id: True)
    runner = FakeRunner()

    result = start_draft_smoke(
        PluginDraftSmokeRequest(scenario_id="life_preview_plugin", max_steps=5, mode="smoke"),
        runner=runner,
    )

    assert result["ok"] is True
    assert result["smoke_status"] == "started"
    assert result["scenario_id"] == "life_preview_plugin"
    assert runner.calls == [
        {
            "mode": "smoke",
            "scenario_ids": ["life_preview_plugin"],
            "launch_mode": "clean",
            "language_mode": "current",
            "max_steps_overrides": {"life_preview_plugin": 5},
        }
    ]


def test_plugin_draft_smoke_service_blocks_missing_scenario(monkeypatch):
    monkeypatch.setattr("qa_frontend.backend.plugin_draft.scenario_id_exists_for_smoke", lambda scenario_id: False)

    result = start_draft_smoke(
        PluginDraftSmokeRequest(scenario_id="missing_plugin", max_steps=5, mode="smoke"),
        runner=FakeRunner(),
    )

    assert result["ok"] is False
    assert result["smoke_status"] == "blocked"
    assert result["diagnostics"]["warnings"] == ["Scenario id not found: missing_plugin"]


def test_plugin_draft_smoke_status_running(tmp_path):
    log_path = tmp_path / "20260607_180000_smoke.log"
    log_path.write_text("[SCENARIO][pre_nav] success\n", encoding="utf-8")

    class RunningRunner:
        def get_status(self):
            return {"state": "running", "run_id": "20260607_180000", "log_path": str(log_path)}

    result = get_draft_smoke_status(
        PluginDraftSmokeStatusRequest(run_id="20260607_180000", scenario_id="life_preview_plugin"),
        runner=RunningRunner(),
        run_log_dir=tmp_path,
    )

    assert result["ok"] is True
    assert result["smoke_status"] == "running"
    assert result["run_status"] == "running"


def test_plugin_draft_smoke_status_completed_with_artifact_warning(tmp_path):
    log_path = tmp_path / "20260607_180000_smoke.log"
    log_path.write_text(
        "\n".join(
            [
                "[SCENARIO][pre_nav] success",
                "[SCENARIO][entry_contract] success scenario='life_preview_plugin' entry_type='card'",
                "[STEP] END scenario='life_preview_plugin' step=0 visible='Preview'",
                "[MAIN] script end",
            ]
        ),
        encoding="utf-8",
    )

    class IdleRunner:
        def get_status(self):
            return {"state": "idle", "run_id": None}

    result = get_draft_smoke_status(
        PluginDraftSmokeStatusRequest(run_id="20260607_180000", scenario_id="life_preview_plugin"),
        runner=IdleRunner(),
        run_log_dir=tmp_path,
    )

    assert result["ok"] is True
    assert result["smoke_status"] == "completed"
    assert result["summary"]["result_status"] == "PASS"
    assert result["artifacts"]["display_urls"]["log"] == "/api/runs/recent/20260607_180000/log"
    assert "XLSX artifact not found" in result["diagnostics"]["warnings"]


def test_plugin_draft_smoke_status_missing_run_id():
    result = get_draft_smoke_status(
        PluginDraftSmokeStatusRequest(run_id="", scenario_id="life_preview_plugin"),
        runner=FakeRunner(),
    )

    assert result["ok"] is False
    assert result["diagnostics"]["errors"] == ["run_id_missing"]
