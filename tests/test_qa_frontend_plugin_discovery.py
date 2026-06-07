from __future__ import annotations

from fastapi.testclient import TestClient

from qa_frontend.backend import main
from qa_frontend.backend.plugin_discovery import PluginDiscoveryRequest, discover_plugins


def test_plugin_discovery_route_blocks_while_run_is_running(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "running"})
    client = TestClient(main.app)

    response = client.post("/api/plugin-discovery/discover", json={"targets": ["life", "device"]})

    assert response.status_code == 409
    assert "run is in progress" in response.json()["detail"]


def test_plugin_discovery_route_returns_schema(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "idle"})
    monkeypatch.setattr(
        main,
        "discover_plugins",
        lambda request: {
            "ok": True,
            "schema_version": "plugin-discovery-v1",
            "cards": [
                {
                    "id": "device:audio:0",
                    "label": "Audio",
                    "stable_label": "Audio",
                    "type": "device",
                    "confidence": "high",
                    "source": "helper",
                    "bounds": "40,420,1040,760",
                    "resource_id": "com.samsung.android.oneconnect:id/device_card",
                    "known": True,
                    "existing_scenario_id": "device_audio_plugin",
                }
            ],
            "diagnostics": {"warnings": []},
        },
    )
    client = TestClient(main.app)

    response = client.post("/api/plugin-discovery/discover", json={"targets": ["device"], "include_xml": True})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["schema_version"] == "plugin-discovery-v1"
    assert body["cards"][0]["existing_scenario_id"] == "device_audio_plugin"
    assert body["diagnostics"]["warnings"] == []


def test_plugin_discovery_service_reports_helper_and_xml_failures():
    class BrokenClient:
        def dump_tree(self, **_kwargs):
            raise RuntimeError("helper unavailable")

        def _run(self, *_args, **_kwargs):
            raise RuntimeError("adb unavailable")

    result = discover_plugins(
        PluginDiscoveryRequest(targets=["life", "device"], include_xml=True),
        client=BrokenClient(),
    )

    assert result["ok"] is False
    assert result["cards"] == []
    warnings = result["diagnostics"]["warnings"]
    assert any("helper_dump_failed" in warning for warning in warnings)
    assert any("xml_dump_failed" in warning for warning in warnings)
