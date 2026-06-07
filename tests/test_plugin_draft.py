from __future__ import annotations

import json

import tb_runner.plugin_draft as plugin_draft
from tb_runner.plugin_draft import apply_plugin_draft, generate_plugin_draft, review_plugin_draft


def test_life_draft_generation_returns_verify_tokens():
    result = generate_plugin_draft(
        {
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "source": "xml",
                "bounds": "40,420,1040,760",
                "resource_id": "com.pkg:id/card",
                "existing_scenario_id": "",
            },
            "probe": {
                "ok": True,
                "schema_version": "plugin-probe-v1",
                "probe_status": "opened_partial_observed",
                "summary": {
                    "plugin_open_verified_candidate": True,
                    "suggested_entry_method": "xml_scroll_search_tap",
                    "suggested_scenario_type": "content",
                },
                "seed": {
                    "verify_tokens": ["Home Care"],
                    "headers": ["Home Care"],
                    "local_tabs": ["Monitor", "Activity"],
                    "representative_cards": ["Suggestions", "My device list"],
                    "overlay_hints": [],
                    "context_verify_text_candidates": ["(?i).*home\\s*care.*"],
                    "entry_candidate": {"action": "xml_scroll_search_tap", "target_seed": "Home Care"},
                },
                "diagnostics": {
                    "warnings": [],
                    "failure_reason": "",
                },
            },
            "options": {
                "include_disabled_runtime_config": True,
            },
        }
    )

    assert result["ok"] is True
    assert result["schema_version"] == "plugin-draft-v1"
    assert result["draft"]["scenario"]["id"] == "life_home_care_plugin"
    assert result["draft"]["scenario"]["verify_tokens"] == ["Home Care"]
    assert result["draft"]["scenario"]["pre_navigation"] == "xml_scroll_search_tap"
    assert result["draft"]["runtime_config"]["life_home_care_plugin"]["enabled"] is False


def test_device_draft_generation_returns_target_stable_labels():
    result = generate_plugin_draft(
        {
            "card": {
                "id": "device:audio:0",
                "label": "Audio",
                "stable_label": "Audio",
                "type": "device",
                "source": "helper",
                "bounds": "40,420,1040,760",
                "resource_id": "com.samsung.android.oneconnect:id/device_card",
                "existing_scenario_id": "",
            },
            "probe": {
                "ok": True,
                "schema_version": "plugin-probe-v1",
                "probe_status": "opened_partial_observed",
                "summary": {
                    "plugin_open_verified_candidate": True,
                    "suggested_entry_method": "enter_device_card_plugin",
                    "suggested_scenario_type": "content",
                },
                "seed": {
                    "verify_tokens": ["Audio", "Now playing"],
                    "headers": ["Audio"],
                    "local_tabs": [],
                    "representative_cards": [],
                    "overlay_hints": [],
                    "context_verify_text_candidates": ["(?i).*audio.*"],
                    "entry_candidate": {"action": "enter_device_card_plugin", "target_seed": "Audio"},
                },
                "diagnostics": {
                    "warnings": [],
                    "failure_reason": "",
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["draft"]["scenario"]["id"] == "device_audio_plugin"
    assert result["draft"]["scenario"]["target_stable_labels"] == ["Audio"]
    assert result["draft"]["scenario"]["pre_navigation"] == "enter_device_card_plugin"


def test_non_ascii_label_falls_back_to_candidate_id_with_warning():
    result = generate_plugin_draft(
        {
            "card": {
                "id": "device:yeongi:0",
                "label": "연기",
                "stable_label": "연기",
                "type": "device",
                "source": "helper",
                "bounds": "40,420,1040,760",
                "resource_id": "com.samsung.android.oneconnect:id/device_card",
                "existing_scenario_id": "",
            },
            "probe": {
                "ok": True,
                "schema_version": "plugin-probe-v1",
                "probe_status": "opened_partial_observed",
                "summary": {
                    "plugin_open_verified_candidate": True,
                    "suggested_entry_method": "enter_device_card_plugin",
                    "suggested_scenario_type": "content",
                },
                "seed": {
                    "verify_tokens": ["연기"],
                    "headers": ["연기"],
                    "local_tabs": [],
                    "representative_cards": [],
                    "overlay_hints": [],
                    "context_verify_text_candidates": [],
                    "entry_candidate": {"action": "enter_device_card_plugin", "target_seed": "연기"},
                },
                "diagnostics": {"warnings": [], "failure_reason": ""},
            },
        }
    )

    assert result["draft"]["scenario"]["id"] == "device_plugin_candidate_001"
    assert any("Non-ASCII stable_label requires manual scenario id review" in warning for warning in result["diagnostics"]["warnings"])
    assert result["draft"]["metadata"]["manual_review_required"] is True


def test_manual_review_required_when_probe_is_not_verified():
    result = generate_plugin_draft(
        {
            "card": {
                "id": "life:home_care:0",
                "label": "Home Care",
                "stable_label": "Home Care",
                "type": "life",
                "source": "xml",
                "bounds": "40,420,1040,760",
                "resource_id": "com.pkg:id/card",
                "existing_scenario_id": "",
            },
            "probe": {
                "ok": False,
                "schema_version": "plugin-probe-v1",
                "probe_status": "collector_partial_only",
                "summary": {
                    "plugin_open_verified_candidate": False,
                    "suggested_entry_method": "xml_scroll_search_tap",
                    "suggested_scenario_type": "content",
                },
                "seed": {
                    "verify_tokens": [],
                    "headers": [],
                    "local_tabs": [],
                    "representative_cards": [],
                    "overlay_hints": ["More options"],
                    "context_verify_text_candidates": [],
                    "entry_candidate": {"action": "xml_scroll_search_tap", "target_seed": "Home Care"},
                },
                "diagnostics": {"warnings": [], "failure_reason": "collector_partial_only"},
            },
        }
    )

    assert result["ok"] is True
    assert result["draft"]["metadata"]["manual_review_required"] is True


def test_review_ready_for_new_scenario(monkeypatch):
    monkeypatch.setattr(plugin_draft, "TAB_CONFIGS", [{"scenario_id": "life_food_plugin"}])
    monkeypatch.setattr(plugin_draft, "_load_runtime_scenarios", lambda config_path=None: {})

    result = review_plugin_draft(
        {
            "draft": {
                "scenario": {
                    "id": "life_preview_plugin",
                    "tab": "life",
                    "verify_tokens": ["Preview"],
                    "pre_navigation": "xml_scroll_search_tap",
                    "entry_contract": "plugin_screen",
                    "anchor_mode": "anchor_only",
                },
                "runtime_config": {
                    "life_preview_plugin": {
                        "enabled": False,
                        "max_steps": 5,
                    }
                },
                "metadata": {
                    "manual_review_required": False,
                },
            },
            "options": {
                "include_diff_preview": True,
                "check_existing": True,
            },
        }
    )

    assert result["ok"] is True
    assert result["review_status"] == "ready"
    assert result["checks"]["can_apply"] is True
    assert "scenario_config.py:" in result["preview"]["diff_preview"]


def test_review_blocks_duplicate_scenario_id(monkeypatch):
    monkeypatch.setattr(plugin_draft, "TAB_CONFIGS", [{"scenario_id": "life_home_care_plugin"}])
    monkeypatch.setattr(plugin_draft, "_load_runtime_scenarios", lambda config_path=None: {})

    result = review_plugin_draft(
        {
            "draft": {
                "scenario": {"id": "life_home_care_plugin"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False},
            }
        }
    )

    assert result["checks"]["scenario_id_exists"] is True
    assert result["checks"]["can_apply"] is False
    assert any("Scenario id already exists" in warning for warning in result["diagnostics"]["warnings"])


def test_review_warns_on_runtime_config_duplicate(monkeypatch):
    monkeypatch.setattr(plugin_draft, "TAB_CONFIGS", [{"scenario_id": "life_food_plugin"}])
    monkeypatch.setattr(plugin_draft, "_load_runtime_scenarios", lambda config_path=None: {"life_home_care_plugin": {"enabled": False}})

    result = review_plugin_draft(
        {
            "draft": {
                "scenario": {"id": "life_home_care_plugin"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False},
            }
        }
    )

    assert result["checks"]["runtime_config_exists"] is True
    assert result["checks"]["can_apply"] is True
    assert any("Runtime config key already exists" in warning for warning in result["diagnostics"]["warnings"])


def test_review_blocks_manual_review_required():
    result = review_plugin_draft(
        {
            "draft": {
                "scenario": {"id": "life_home_care_plugin"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": True},
            }
        }
    )

    assert result["checks"]["manual_review_required"] is True
    assert result["checks"]["can_apply"] is False


def test_review_blocks_candidate_id(monkeypatch):
    monkeypatch.setattr(plugin_draft, "TAB_CONFIGS", [])
    monkeypatch.setattr(plugin_draft, "_load_runtime_scenarios", lambda config_path=None: {})

    result = review_plugin_draft(
        {
            "draft": {
                "scenario": {"id": "device_plugin_candidate_001"},
                "runtime_config": {"device_plugin_candidate_001": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False},
            }
        }
    )

    assert result["checks"]["can_apply"] is False
    assert any("Candidate id requires manual rename before apply" in warning for warning in result["diagnostics"]["warnings"])


def test_apply_blocked_when_review_missing():
    result = apply_plugin_draft(
        {
            "draft": {
                "scenario": {"id": "life_home_care_plugin"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False},
            }
        }
    )

    assert result["ok"] is False
    assert result["apply_status"] == "blocked"


def test_apply_blocked_when_can_apply_false():
    result = apply_plugin_draft(
        {
            "draft": {
                "scenario": {"id": "life_home_care_plugin"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False},
            },
            "review": {
                "schema_version": "plugin-draft-review-v1",
                "checks": {"can_apply": False},
            },
        }
    )

    assert result["ok"] is False
    assert result["diagnostics"]["errors"] == ["Review did not allow apply"]


def test_apply_blocked_when_scenario_id_duplicate_at_apply_time(tmp_path):
    scenario_config_path = tmp_path / "scenario_config.py"
    runtime_config_path = tmp_path / "runtime_config.json"
    scenario_config_path.write_text('TAB_CONFIGS = [\n    {"scenario_id": "life_home_care_plugin"}\n]\n', encoding="utf-8")
    runtime_config_path.write_text('{"scenarios": {}}', encoding="utf-8")

    result = apply_plugin_draft(
        {
            "draft": {
                "scenario": {"id": "life_home_care_plugin", "tab": "life", "verify_tokens": ["Home Care"], "pre_navigation": "xml_scroll_search_tap"},
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False, "source_card": {"stable_label": "Home Care"}},
            },
            "review": {
                "schema_version": "plugin-draft-review-v1",
                "checks": {"can_apply": True},
            },
        },
        scenario_config_path=scenario_config_path,
        runtime_config_path=runtime_config_path,
        backup_root=tmp_path / "backups",
    )

    assert result["ok"] is False
    assert "Scenario id already exists at apply time" in result["diagnostics"]["errors"][0]


def test_apply_writes_runtime_config_and_creates_backup(tmp_path):
    scenario_config_path = tmp_path / "scenario_config.py"
    runtime_config_path = tmp_path / "runtime_config.json"
    backup_root = tmp_path / "backups"
    scenario_config_path.write_text('TAB_CONFIGS = [\n    {"scenario_id": "life_food_plugin"}\n]\n', encoding="utf-8")
    runtime_config_path.write_text('{"scenarios": {"life_food_plugin": {"enabled": false, "max_steps": 5}}}\n', encoding="utf-8")

    result = apply_plugin_draft(
        {
            "draft": {
                "scenario": {
                    "id": "life_home_care_plugin",
                    "tab": "life",
                    "verify_tokens": ["Home Care"],
                    "pre_navigation": "xml_scroll_search_tap",
                    "entry_contract": "plugin_screen",
                    "anchor_mode": "anchor_only",
                },
                "runtime_config": {"life_home_care_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {
                    "manual_review_required": False,
                    "source_card": {"stable_label": "Home Care", "label": "Home Care"},
                    "context_verify_text_candidates": ["(?i).*home\\s*care.*"],
                },
            },
            "review": {
                "schema_version": "plugin-draft-review-v1",
                "checks": {"can_apply": True, "scenario_id_exists": False, "manual_review_required": False},
            },
            "options": {
                "create_backup": True,
            },
        },
        scenario_config_path=scenario_config_path,
        runtime_config_path=runtime_config_path,
        backup_root=backup_root,
    )

    assert result["ok"] is True
    assert result["apply_status"] == "applied"
    updated_runtime = json.loads(runtime_config_path.read_text(encoding="utf-8"))
    assert "life_home_care_plugin" in updated_runtime["scenarios"]
    updated_scenario_config = scenario_config_path.read_text(encoding="utf-8")
    assert '"scenario_id": "life_home_care_plugin"' in updated_scenario_config
    assert result["backup"]["created"] is True
    assert len(result["backup"]["paths"]) == 2


def test_apply_response_schema_with_temp_files(tmp_path):
    scenario_config_path = tmp_path / "scenario_config.py"
    runtime_config_path = tmp_path / "runtime_config.json"
    scenario_config_path.write_text('TAB_CONFIGS = [\n    {"scenario_id": "life_food_plugin"}\n]\n', encoding="utf-8")
    runtime_config_path.write_text('{"scenarios": {}}\n', encoding="utf-8")

    result = apply_plugin_draft(
        {
            "draft": {
                "scenario": {"id": "device_audio_plugin", "tab": "devices", "target_stable_labels": ["Audio"], "pre_navigation": "enter_device_card_plugin"},
                "runtime_config": {"device_audio_plugin": {"enabled": False, "max_steps": 5}},
                "metadata": {"manual_review_required": False, "source_card": {"stable_label": "Audio", "label": "Audio"}},
            },
            "review": {"schema_version": "plugin-draft-review-v1", "checks": {"can_apply": True}},
        },
        scenario_config_path=scenario_config_path,
        runtime_config_path=runtime_config_path,
        backup_root=tmp_path / "backups",
    )

    assert result["schema_version"] == "plugin-draft-apply-v1"
    assert result["applied"]["scenario_id"] == "device_audio_plugin"
