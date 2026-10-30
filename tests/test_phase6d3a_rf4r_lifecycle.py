"""RF4R real-wrapper lifecycle semantics; external device IO is simulated."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from talkback_lib import A11yAdbClient
from tb_runner import collection_flow as flow
from tb_runner.active_redirect import active_revalidation_document
from tb_runner.phase5b_navigation import SafeNavigationSession
from tb_runner.canonical_json import canonical_sha256
from test_phase6d3a_rf4_active import active_fixture, run
from test_window_lifecycle import _snapshot


def test_benign_lifecycle_cannot_override_component_unknown_or_dispatch(monkeypatch):
    f = active_fixture(monkeypatch)
    before = f.lifecycle.event_count
    assert f.client.target_focus_commit.__func__ is A11yAdbClient.target_focus_commit
    row = run(f)
    audit = row["phase6d3a_redirect"]
    readiness = audit["common_readiness"]
    assert readiness["readiness_status"] == "UNKNOWN"
    assert "PLUGIN_CONTEXT_UNKNOWN" in readiness["reason_codes"]
    assert audit["ready"] is False
    assert audit["dispatch_count"] == 0
    assert f.native == []
    assert f.controller.budget.redirects_used == f.client._phase6d3a_controlled_budget.actions == 0
    assert f.lifecycle.event_count >= before
    assert f.lifecycle.process_continuity_revision == 0
    assert audit["fallback_count"] <= 1
    assert len(f.collected) <= 1


@pytest.mark.parametrize("case", ["pid_change", "restart_reconnect", "process_gap", "blocked",
    "missing_sample", "missing_recorder", "recovered_gap_same_pid", "recorder_replaced"])
def test_real_wrapper_lifecycle_instability_zero_dispatch(monkeypatch, case):
    f = active_fixture(monkeypatch)
    before = f.lifecycle.event_count
    process_before = deepcopy(f.lifecycle.last_process_observation)
    original = SafeNavigationSession.authorize_focus_target
    @contextmanager
    def authorization(session, **kw):
        with original(session, **kw) as permit:
            if case == "pid_change":
                f.lifecycle_output = lambda: _snapshot("54321")
            elif case in {"restart_reconnect", "recovered_gap_same_pid"}:
                f.lifecycle_output = lambda: _snapshot("")
                f.lifecycle.capture("offline-gap", "PING")
                pid = "54321" if case == "restart_reconnect" else "12345"
                f.lifecycle_output = lambda: _snapshot(pid)
            elif case in {"process_gap", "blocked"}:
                f.lifecycle_output = lambda: _snapshot("")
            elif case == "missing_sample":
                f.lifecycle_output = lambda: ""
            elif case == "missing_recorder":
                f.client._window_lifecycle_recorder = None
            elif case == "recorder_replaced":
                from talkback_lib.window_lifecycle import WindowLifecycleRecorder
                replacement = WindowLifecycleRecorder(f.client,
                    "offline", f.scenario_id, None)
                replacement.previous_pid = "12345"
                replacement.step = 7
                replacement.capture("fixture", "PING")
                f.client._window_lifecycle_recorder = replacement
            yield permit
    monkeypatch.setattr(SafeNavigationSession, "authorize_focus_target", authorization)
    row = run(f)
    assert len(f.native) == 0, row["phase6d3a_redirect"]
    assert f.controller.budget.redirects_used == f.client._phase6d3a_controlled_budget.actions == 0
    assert f.controller.budget.consecutive_failures == 0
    assert row["phase6d3a_redirect"]["fallback_count"] <= 1
    if case in {"missing_sample", "recovered_gap_same_pid"}:
        # Component-UNKNOWN closes before lifecycle-dependent authorization, so
        # no synthetic post-decision lifecycle sample is manufactured.
        assert row["phase6d3a_redirect"]["common_readiness"]["readiness_status"] == "UNKNOWN"
        assert f.lifecycle.event_count == before
        assert f.lifecycle.last_process_observation == process_before
    if case == "missing_sample":
        assert process_before["pid"] == "12345"


def test_only_diagnostic_lifecycle_metadata_is_excluded(monkeypatch):
    f = active_fixture(monkeypatch)
    token = flow._phase6d3a_capture_lifecycle_token(f.client)
    sample = deepcopy(f.lifecycle.last_process_observation)
    revision = f.lifecycle.process_continuity_revision
    diagnostic = run(f)["phase6d3a_redirect"]["common_readiness"]
    baseline, version = active_revalidation_document(diagnostic, token, sample, revision)
    changed = deepcopy(diagnostic)
    evidence = changed["conditions"]["lifecycle_evidence"]
    evidence["event_count"] += 1
    evidence["recorder_step"] += 1
    evidence["reason"] = "another diagnostic explanation"
    evidence["merge_reason"] = "another stable merge explanation"
    for name in ["lifecycle_pre_decision", "lifecycle_post_collector"]:
        evidence[name]["reason"] = "fresh diagnostic explanation"
    evidence["lifecycle_post_collector"]["event_count"] += 1
    evidence["lifecycle_post_collector"]["recorder_step"] += 1
    advanced_token = (*token[:3], token[3]+1, token[4]+1, *token[5:])
    current, advanced = active_revalidation_document(changed, advanced_token,
        {**sample, "event_count": sample["event_count"]+1}, revision)
    assert canonical_sha256(baseline) == canonical_sha256(current)
    assert advanced[0] > version[0] and advanced[1] > version[1]
    # Full diagnostic documents are retained in the audit; execution equality
    # preserves exact non-lifecycle provenance and actual process identity.
    _, _ = active_revalidation_document(diagnostic, token, sample, revision)
    pid_token = (*token[:6], "other-pid", *token[7:])
    different_pid, _ = active_revalidation_document(diagnostic, pid_token, {**sample,"pid":"other-pid"}, revision)
    assert canonical_sha256(different_pid) != canonical_sha256(baseline)
    different_generation, _ = active_revalidation_document(diagnostic, token, sample, revision+1)
    assert canonical_sha256(different_generation) != canonical_sha256(baseline)


@pytest.mark.parametrize("field,value", [("pid",None),("enabled",None),("enabled",False),
    ("process_event","missing_or_unavailable"),("restart_detected",True),("snapshot_error",True),
    ("schema","unknown-version"),("event_count",-1)])
def test_missing_or_unstable_process_sample_never_becomes_identity(monkeypatch, field, value):
    f = active_fixture(monkeypatch)
    token = flow._phase6d3a_capture_lifecycle_token(f.client)
    sample = deepcopy(f.lifecycle.last_process_observation)
    diagnostic = run(f)["phase6d3a_redirect"]["common_readiness"]
    sample[field] = value
    with pytest.raises(ValueError):
        active_revalidation_document(diagnostic, token, sample, 0)


@pytest.mark.parametrize("constant", ["LIFECYCLE_SNAPSHOT_COMMAND", "LIFECYCLE_PROCESS_PROBE_COMMAND"])
def test_only_exact_lifecycle_diagnostic_scripts_pass_phase5(monkeypatch, constant):
    from talkback_lib import window_lifecycle as lifecycle
    from talkback_lib.native_dispatch_evidence import classify_dispatch
    command = ["shell", getattr(lifecycle, constant)]
    session = SafeNavigationSession("device_tv_plugin", lambda *a: None)
    assert lifecycle.is_lifecycle_readonly_command(command)
    assert session.command_allowed(command)
    assert session.permit is None
    assert classify_dispatch(command) is None
    for mutated in [
        ["shell", command[1]+"; input keyevent 4"],
        ["shell", command[1]+" && am start example"],
        ["shell", command[1]+" | sh"],
        ["shell", "input keyevent 4; "+command[1]],
        [*command, "extra"],
    ]:
        assert not lifecycle.is_lifecycle_readonly_command(mutated)
        assert not session.command_allowed(mutated)


def test_recorder_preserves_observed_gap_after_same_pid_recovers(monkeypatch):
    f = active_fixture(monkeypatch)
    revision = f.lifecycle.process_continuity_revision
    f.lifecycle_output = lambda: _snapshot("")
    f.lifecycle.capture("offline-gap", "PING")
    assert f.lifecycle.saw_enabled_process_gap
    assert f.lifecycle.process_continuity_revision > revision
    f.lifecycle_output = lambda: _snapshot("12345")
    f.lifecycle.capture("offline-recovered", "PING")
    assert not f.lifecycle.saw_enabled_process_gap
    assert f.lifecycle.last_process_observation["process_event"] == "running"
    assert f.lifecycle.process_continuity_revision > revision


def test_process_probe_at_capture_limit_updates_actual_process_evidence(monkeypatch):
    from talkback_lib.window_lifecycle import MAX_EVENTS
    f = active_fixture(monkeypatch)
    f.lifecycle.event_count = MAX_EVENTS
    f.lifecycle.capture("offline-at-limit", "PING")
    assert f.lifecycle.event_count == MAX_EVENTS
    assert f.lifecycle.last_process_observation["event_count"] == MAX_EVENTS
    assert f.lifecycle.last_process_observation["pid"] == "12345"
    f.lifecycle_output = lambda: _snapshot("")
    f.lifecycle.capture("offline-gap-at-limit", "PING")
    assert f.lifecycle.saw_enabled_process_gap
    assert f.lifecycle.last_process_observation["pid"] is None
    assert f.lifecycle.process_continuity_revision > 0
