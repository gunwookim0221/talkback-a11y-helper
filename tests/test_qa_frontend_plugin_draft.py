from __future__ import annotations

from fastapi.testclient import TestClient

from qa_frontend.backend import main
from qa_frontend.backend.plugin_draft import (
    PluginDraftApplyRequest,
    PluginDraftRequest,
    PluginDraftReviewRequest,
    apply_draft,
    generate_draft,
    review_draft,
)


def test_plugin_draft_route_blocks_while_run_is_running(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "running"})
    client = TestClient(main.app)

    response = client.post(
        "/api/plugin-draft/generate",
        json={
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "bounds": "40,420,1040,760",
            },
            "probe": {
                "ok": True,
                "schema_version": "plugin-probe-v1",
                "probe_status": "opened_partial_observed",
                "summary": {"plugin_open_verified_candidate": True, "suggested_entry_method": "xml_scroll_search_tap", "suggested_scenario_type": "content"},
                "seed": {"verify_tokens": ["Home Care"], "headers": [], "local_tabs": [], "representative_cards": [], "overlay_hints": [], "context_verify_text_candidates": [], "entry_candidate": {"action": "xml_scroll_search_tap", "target_seed": "Home Care"}},
                "diagnostics": {"warnings": [], "failure_reason": ""},
            },
        },
    )

    assert response.status_code == 409
    assert "run is in progress" in response.json()["detail"]


def test_plugin_draft_route_returns_schema(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "idle"})
    monkeypatch.setattr(
        main,
        "generate_draft",
        lambda request: {
            "ok": True,
            "schema_version": "plugin-draft-v1",
            "draft_status": "generated",
            "draft": {
                "scenario": {"id": "life_home_care_plugin"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {
                    "source_card": {},
                    "probe_status": "opened_partial_observed",
                    "plugin_open_verified_candidate": True,
                    "headers": [],
                    "local_tabs": [],
                    "representative_cards": [],
                    "overlay_hints": [],
                    "context_verify_text_candidates": [],
                    "manual_review_required": False,
                },
            },
            "diagnostics": {"warnings": [], "notes": ["Draft only. No files were modified."], "failure_reason": ""},
        },
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/plugin-draft/generate",
        json={
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "bounds": "40,420,1040,760",
            },
            "probe": {
                "ok": True,
                "schema_version": "plugin-probe-v1",
                "probe_status": "opened_partial_observed",
                "summary": {"plugin_open_verified_candidate": True, "suggested_entry_method": "xml_scroll_search_tap", "suggested_scenario_type": "content"},
                "seed": {"verify_tokens": ["Home Care"], "headers": [], "local_tabs": [], "representative_cards": [], "overlay_hints": [], "context_verify_text_candidates": [], "entry_candidate": {"action": "xml_scroll_search_tap", "target_seed": "Home Care"}},
                "diagnostics": {"warnings": [], "failure_reason": ""},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["schema_version"] == "plugin-draft-v1"
    assert body["draft"]["scenario"]["id"] == "life_home_care_plugin"


def test_plugin_draft_review_route_returns_schema(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "idle"})
    monkeypatch.setattr(
        main,
        "review_draft",
        lambda request: {
            "ok": True,
            "schema_version": "plugin-draft-review-v1",
            "review_status": "ready",
            "checks": {
                "scenario_id_exists": False,
                "runtime_config_exists": False,
                "manual_review_required": False,
                "can_apply": True,
            },
            "preview": {
                "scenario_config_insertion_hint": "append_to_scenarios",
                "runtime_config_patch": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "diff_preview": "scenario_config.py:\n+ {...}",
            },
            "diagnostics": {"warnings": [], "errors": []},
        },
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/plugin-draft/review",
        json={
            "draft": {
                "scenario": {"id": "life_home_care_plugin"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False},
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["schema_version"] == "plugin-draft-review-v1"
    assert body["checks"]["can_apply"] is True


def test_plugin_draft_apply_route_returns_schema(monkeypatch):
    monkeypatch.setattr(main.runner, "get_status", lambda: {"state": "idle"})
    monkeypatch.setattr(
        main,
        "apply_draft",
        lambda request: {
            "ok": True,
            "schema_version": "plugin-draft-apply-v1",
            "apply_status": "applied",
            "changed_files": ["tb_runner/scenario_config.py", "config/runtime_config.json"],
            "backup": {"created": True, "paths": ["output/plugin_draft_backups/x/scenario_config.py.bak"]},
            "applied": {"scenario_id": "life_home_care_plugin", "runtime_config_key": "life_home_care_plugin"},
            "diagnostics": {"warnings": [], "errors": []},
        },
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/plugin-draft/apply",
        json={
            "draft": {
                "scenario": {"id": "life_home_care_plugin"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False},
            },
            "review": {
                "schema_version": "plugin-draft-review-v1",
                "checks": {"can_apply": True, "scenario_id_exists": False, "manual_review_required": False},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["schema_version"] == "plugin-draft-apply-v1"
    assert body["apply_status"] == "applied"


def test_plugin_draft_service_rejects_invalid_request():
    result = generate_draft(
        PluginDraftRequest(
            card={
                "id": "",
                "label": "",
                "stable_label": "",
                "type": "",
                "source": "",
                "bounds": "",
                "resource_id": "",
                "existing_scenario_id": "",
            },
            probe={
                "ok": False,
                "schema_version": "",
                "probe_status": "",
                "summary": {
                    "plugin_open_verified_candidate": False,
                    "suggested_entry_method": "",
                    "suggested_scenario_type": "content",
                },
                "seed": {
                    "verify_tokens": [],
                    "headers": [],
                    "local_tabs": [],
                    "representative_cards": [],
                    "overlay_hints": [],
                    "context_verify_text_candidates": [],
                    "entry_candidate": {"action": "", "target_seed": ""},
                },
                "diagnostics": {"warnings": [], "failure_reason": ""},
            },
        )
    )

    assert result["ok"] is False
    assert result["diagnostics"]["failure_reason"] == "invalid_request"


def test_plugin_draft_review_service_rejects_invalid_request():
    result = review_draft(
        PluginDraftReviewRequest(
            draft={
                "scenario": {
                    "id": "",
                    "tab": "",
                    "verify_tokens": [],
                    "target_stable_labels": [],
                    "pre_navigation": "",
                    "entry_contract": "",
                    "anchor_mode": "",
                },
                "runtime_config": {},
                "metadata": {
                    "manual_review_required": False,
                    "source_card": {},
                    "probe_status": "",
                    "plugin_open_verified_candidate": False,
                    "headers": [],
                    "local_tabs": [],
                    "representative_cards": [],
                    "overlay_hints": [],
                    "context_verify_text_candidates": [],
                },
            }
        )
    )

    assert result["ok"] is False
    assert result["diagnostics"]["errors"] == ["invalid_request"]


def test_plugin_draft_apply_service_rejects_invalid_request():
    result = apply_draft(
        PluginDraftApplyRequest(
            draft={
                "scenario": {
                    "id": "",
                    "tab": "",
                    "verify_tokens": [],
                    "target_stable_labels": [],
                    "pre_navigation": "",
                    "entry_contract": "",
                    "anchor_mode": "",
                },
                "runtime_config": {},
                "metadata": {
                    "manual_review_required": False,
                    "source_card": {},
                    "probe_status": "",
                    "plugin_open_verified_candidate": False,
                    "headers": [],
                    "local_tabs": [],
                    "representative_cards": [],
                    "overlay_hints": [],
                    "context_verify_text_candidates": [],
                },
            },
            review={
                "schema_version": "plugin-draft-review-v1",
                "checks": {
                    "can_apply": False,
                    "scenario_id_exists": False,
                    "runtime_config_exists": False,
                    "manual_review_required": False,
                },
            },
        )
    )

    assert result["ok"] is False
    assert result["apply_status"] == "blocked"
