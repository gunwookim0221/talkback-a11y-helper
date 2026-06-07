from __future__ import annotations

import pytest

from tb_runner.plugin_onboarding_session import (
    create_onboarding_session,
    get_onboarding_session,
    list_onboarding_sessions,
    restore_onboarding_session,
    save_onboarding_step,
)


def test_create_onboarding_session(tmp_path):
    result = create_onboarding_session(
        {"label": "Home Care", "stable_label": "Home Care", "type": "life"},
        tmp_path,
    )

    assert result["ok"] is True
    assert result["schema_version"] == "plugin-onboarding-session-v1"
    assert result["session_id"].startswith("onboarding_")
    assert (tmp_path / f"{result['session_id']}.json").is_file()


def test_save_step_updates_status_and_scenario_id(tmp_path):
    created = create_onboarding_session(
        {"label": "Home Care", "stable_label": "Home Care", "type": "life"},
        tmp_path,
    )

    result = save_onboarding_step(
        created["session_id"],
        "apply",
        "applied",
        {"applied": {"scenario_id": "life_home_care_plugin"}},
        tmp_path,
    )

    session = result["session"]
    assert session["status"] == "applied"
    assert session["plugin"]["scenario_id"] == "life_home_care_plugin"
    assert session["steps"]["apply"]["status"] == "applied"


def test_get_and_list_sessions_sorted_by_updated_at(tmp_path):
    first = create_onboarding_session({"label": "A", "stable_label": "A", "type": "life"}, tmp_path)
    second = create_onboarding_session({"label": "B", "stable_label": "B", "type": "device"}, tmp_path)
    save_onboarding_step(first["session_id"], "probe", "completed", {}, tmp_path)

    fetched = get_onboarding_session(first["session_id"], tmp_path)
    listed = list_onboarding_sessions(tmp_path)

    assert fetched["session"]["session_id"] == first["session_id"]
    assert [item["session_id"] for item in listed["sessions"]] == [first["session_id"], second["session_id"]]


@pytest.mark.parametrize(
    ("result_status", "expected_status", "feedback_key", "feedback_value"),
    [
        ("PASS", "smoke_passed", "suggestions", "Ready for manual validation"),
        ("WARN", "smoke_warn", "warnings", "needs review"),
        ("FAIL", "smoke_failed", "errors", "tap_failed"),
    ],
)
def test_smoke_feedback_is_stored(tmp_path, result_status, expected_status, feedback_key, feedback_value):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path)
    payload = {
        "summary": {
            "result_status": result_status,
            "failure_reason": "tap_failed" if result_status == "FAIL" else "",
        },
        "diagnostics": {
            "warnings": ["needs review"] if result_status == "WARN" else [],
            "errors": [],
        },
    }

    result = save_onboarding_step(created["session_id"], "smoke", "completed", payload, tmp_path)

    assert result["session"]["status"] == expected_status
    assert feedback_value in result["session"]["feedback"][feedback_key]


def test_invalid_step_rejected(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path)

    with pytest.raises(ValueError, match="invalid_step"):
        save_onboarding_step(created["session_id"], "rollback", "completed", {}, tmp_path)


def test_restore_complete_session(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path)
    card = {"label": "TV", "stable_label": "TV", "type": "device"}
    save_onboarding_step(created["session_id"], "discovery", "completed", {"card": card}, tmp_path)
    save_onboarding_step(created["session_id"], "probe", "completed", {"schema_version": "plugin-probe-v1"}, tmp_path)
    save_onboarding_step(created["session_id"], "draft", "completed", {"schema_version": "plugin-draft-v1"}, tmp_path)
    save_onboarding_step(created["session_id"], "review", "ready", {"schema_version": "plugin-draft-review-v1", "review_status": "ready"}, tmp_path)
    save_onboarding_step(created["session_id"], "apply", "applied", {"schema_version": "plugin-draft-apply-v1"}, tmp_path)
    save_onboarding_step(
        created["session_id"],
        "smoke",
        "completed",
        {"schema_version": "plugin-draft-smoke-status-v1", "summary": {"result_status": "PASS", "failure_reason": ""}},
        tmp_path,
    )

    restored = restore_onboarding_session(created["session_id"], tmp_path)

    assert restored["schema_version"] == "plugin-onboarding-restore-v1"
    assert restored["restored_state"]["selected_card"] == card
    assert restored["restored_state"]["probe_result"]["schema_version"] == "plugin-probe-v1"
    assert restored["restored_state"]["smoke_status_result"]["summary"]["result_status"] == "PASS"
    assert restored["recommendation"]["next_action"] == "ready_for_manual_validation"


def test_restore_partial_session_uses_first_discovery_card(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path)
    save_onboarding_step(
        created["session_id"],
        "discovery",
        "completed",
        {"cards": [{"label": "TV", "stable_label": "TV", "type": "device"}]},
        tmp_path,
    )

    restored = restore_onboarding_session(created["session_id"], tmp_path)

    assert restored["restored_state"]["selected_card"]["stable_label"] == "TV"
    assert restored["recommendation"]["next_action"] == "incomplete"


def test_recommend_ready_with_warning(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path)
    save_onboarding_step(
        created["session_id"],
        "smoke",
        "completed",
        {"summary": {"result_status": "WARN", "failure_reason": "repeat_no_progress"}},
        tmp_path,
    )

    restored = restore_onboarding_session(created["session_id"], tmp_path)

    assert restored["recommendation"]["next_action"] == "ready_with_warning"
    assert restored["recommendation"]["allowed_actions"] == ["manual_validation", "review_logs"]


def test_recommend_needs_probe_revision(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path)
    save_onboarding_step(
        created["session_id"],
        "smoke",
        "completed",
        {"summary": {"result_status": "FAIL", "failure_reason": "tap_failed"}},
        tmp_path,
    )

    restored = restore_onboarding_session(created["session_id"], tmp_path)

    assert restored["recommendation"]["next_action"] == "needs_probe_revision"
    assert "retry_probe" in restored["recommendation"]["allowed_actions"]


def test_recommend_apply_rollback_candidate(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path)
    save_onboarding_step(
        created["session_id"],
        "apply",
        "applied",
        {"backup": {"created": True, "paths": ["output/plugin_draft_backups/x/scenario_config.py.bak"]}},
        tmp_path,
    )
    save_onboarding_step(
        created["session_id"],
        "smoke",
        "completed",
        {"summary": {"result_status": "FAIL", "failure_reason": "tap_failed"}},
        tmp_path,
    )

    restored = restore_onboarding_session(created["session_id"], tmp_path)

    assert restored["recommendation"]["next_action"] == "apply_rollback_candidate"
    assert "rollback_from_backup" in restored["recommendation"]["allowed_actions"]


def test_recommend_review_blocked(tmp_path):
    created = create_onboarding_session({"label": "TV", "stable_label": "TV", "type": "device"}, tmp_path)
    save_onboarding_step(
        created["session_id"],
        "review",
        "blocked",
        {
            "review_status": "blocked",
            "checks": {"manual_review_required": True, "scenario_id_exists": True},
            "diagnostics": {"warnings": ["Candidate id requires manual rename before apply"]},
        },
        tmp_path,
    )

    restored = restore_onboarding_session(created["session_id"], tmp_path)

    assert restored["recommendation"]["next_action"] == "review_blocked"
    assert "apply_draft" in restored["recommendation"]["blocked_actions"]
