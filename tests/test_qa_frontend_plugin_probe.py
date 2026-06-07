from __future__ import annotations

from fastapi.testclient import TestClient

from qa_frontend.backend import main
from qa_frontend.backend.plugin_probe import PluginProbeRequest, probe_plugin


def test_plugin_probe_route_blocks_while_run_is_running(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "running"})
    client = TestClient(main.app)

    response = client.post(
        "/api/plugin-probe/start",
        json={
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "bounds": "40,420,1040,760",
            }
        },
    )

    assert response.status_code == 409
    assert "run is in progress" in response.json()["detail"]


def test_plugin_probe_route_returns_schema(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "idle"})
    monkeypatch.setattr(
        main,
        "probe_plugin",
        lambda request: {
            "ok": True,
            "schema_version": "plugin-probe-v1",
            "probe_status": "opened_partial_observed",
            "entry": {"attempted": True, "method": "life_bounds_tap", "open_confirmed": True, "reason": "transition_or_anchor_seen"},
            "summary": {"plugin_open_verified_candidate": True, "suggested_entry_method": "xml_scroll_search_tap", "suggested_scenario_type": "content"},
            "seed": {
                "verify_tokens": ["Home Care"],
                "negative_verify_tokens": [],
                "headers": ["Home Care"],
                "local_tabs": [],
                "representative_cards": [],
                "overlay_hints": [],
                "context_verify_text_candidates": ["(?i).*home\\s*care.*"],
                "entry_candidate": {"action": "xml_scroll_search_tap", "target_seed": "Home Care"},
            },
            "artifacts": {"helper_nodes_captured": True, "xml_captured": True, "focus_steps": 3},
            "diagnostics": {"warnings": [], "failure_reason": ""},
        },
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/plugin-probe/start",
        json={
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "bounds": "40,420,1040,760",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["schema_version"] == "plugin-probe-v1"
    assert body["entry"]["method"] == "life_bounds_tap"


def test_plugin_probe_service_preserves_invalid_request_failure():
    result = probe_plugin(
        PluginProbeRequest(
            card={
                "id": "x",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "source": "xml",
                "bounds": "",
                "resource_id": "",
                "existing_scenario_id": "",
            }
        ),
        client=object(),
    )

    assert result["ok"] is False
    assert result["diagnostics"]["failure_reason"] == "invalid_request"
