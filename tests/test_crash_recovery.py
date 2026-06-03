from __future__ import annotations

import json
from types import SimpleNamespace

import script_test
from tb_runner import crash_recovery
from tb_runner.accessibility_preflight import AccessibilityPreflightResult, AccessibilitySettings


def test_extract_crash_terminal_signal_from_app_terminated_row():
    signal = crash_recovery.extract_crash_terminal_signal(
        [
            {"stop_reason": "repeat_no_progress", "scenario_id": "home_main"},
            {
                "stop_reason": "app_terminated",
                "scenario_id": "global_nav_main",
                "crash_event_id": "CRASH-0001",
                "crash_type": "APP_TERMINATED",
                "artifact_dir": "out/crashes/CRASH-0001",
            },
        ]
    )

    assert signal is not None
    assert signal.is_crash_like is True
    assert signal.scenario_id == "global_nav_main"
    assert signal.stop_reason == "app_terminated"
    assert signal.crash_type == "APP_TERMINATED"
    assert signal.crash_event_id == "CRASH-0001"
    assert signal.recovery_state == "CRASH_DETECTED"


def test_extract_crash_terminal_signal_ignores_non_crash_rows():
    assert crash_recovery.extract_crash_terminal_signal(
        [
            {"stop_reason": "", "status": "PASS"},
            {"stop_reason": "repeat_no_progress", "status": "WARN"},
            {"stop_reason": "tab_or_anchor_failed", "status": "FAIL"},
        ]
    ) is None
    assert crash_recovery.has_crash_terminal_signal({"stop_reason": "terminal_reached"}) is False


def test_build_recovery_decision_logs_only_and_renders_logs():
    signal = crash_recovery.CrashTerminalSignal(
        is_crash_like=True,
        scenario_id="life_home_monitor_plugin",
        stop_reason="possible_crash",
        crash_type="POSSIBLE_CRASH",
        crash_event_id="CRASH-0002",
        artifact_dir="out/crashes/CRASH-0002",
    )

    decision = crash_recovery.build_recovery_decision(signal, attempt=0)
    lines = crash_recovery.render_recovery_log_lines(decision)

    assert decision.decision == "logs_only"
    assert decision.retry_count == 0
    assert decision.result == "not_implemented"
    assert decision.scenario_final_status == "CRASH_CAPTURED"
    assert decision.next_action == "continue_without_retry"
    assert lines == [
        "[CRASH_RECOVERY] state='CRASH_DETECTED' scenario='life_home_monitor_plugin' crash_event_id='CRASH-0002' crash_type='POSSIBLE_CRASH' attempt=0",
        "[CRASH_RECOVERY] state='ARTIFACT_CAPTURED' scenario='life_home_monitor_plugin' crash_event_id='CRASH-0002'",
        "[CRASH_RECOVERY] state='RECOVERY_NOT_IMPLEMENTED' scenario='life_home_monitor_plugin' decision='logs_only'",
        "[CRASH_RECOVERY] state='CONTINUE_WITHOUT_RETRY' scenario='life_home_monitor_plugin'",
    ]


def test_should_process_crash_recovery_deduplicates_event_ids():
    signal = crash_recovery.CrashTerminalSignal(
        is_crash_like=True,
        scenario_id="global_nav_main",
        stop_reason="app_terminated",
        crash_type="APP_TERMINATED",
        crash_event_id="CRASH-0001",
    )
    processed = set()

    assert crash_recovery.should_process_crash_recovery(signal, processed) is True
    assert crash_recovery.should_process_crash_recovery(signal, processed) is False
    assert processed == {"CRASH-0001"}


def test_update_crash_context_recovery_adds_logs_only_payload(tmp_path):
    artifact_dir = tmp_path / "crashes" / "CRASH-0001"
    artifact_dir.mkdir(parents=True)
    context_path = artifact_dir / "crash_context.json"
    context_path.write_text(
        json.dumps({"recovery": {"decision": "capture_only", "retry_count": 0}}, indent=2),
        encoding="utf-8",
    )
    signal = crash_recovery.CrashTerminalSignal(
        is_crash_like=True,
        scenario_id="global_nav_main",
        stop_reason="app_terminated",
        crash_type="APP_TERMINATED",
        crash_event_id="CRASH-0001",
        artifact_dir=str(artifact_dir),
    )
    decision = crash_recovery.build_recovery_decision(signal)

    assert crash_recovery.update_crash_context_recovery(signal, decision) is True

    payload = json.loads(context_path.read_text(encoding="utf-8"))
    assert payload["recovery"] == {
        "decision": "logs_only",
        "retry_count": 0,
        "result": "not_implemented",
        "scenario_final_status": "CRASH_CAPTURED",
        "next_action": "continue_without_retry",
    }


class _RecoveryClient:
    def __init__(self, *, ping_ok=True, talkback_status="enabled"):
        self.ping_ok = ping_ok
        self.talkback_status = talkback_status
        self.calls = []

    def ping(self, dev=None, wait_=3.0):
        self.calls.append(("ping", dev, wait_))
        return self.ping_ok

    def check_talkback_ready(self, dev=None):
        self.calls.append(("talkback", dev))
        return {"status": self.talkback_status, "reason": "ok"}


def _step(status, **details):
    return {"status": status, "message": status.lower(), **details}


def _accessibility_result(ok=True, reason="ok"):
    settings = AccessibilitySettings("helper", "1")
    return AccessibilityPreflightResult(ok, reason, settings, settings, False, ok)


def test_recovery_preflight_success(monkeypatch):
    monkeypatch.setattr(crash_recovery, "wake_screen", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(crash_recovery, "unlock_swipe", lambda **_kwargs: _step("WARN"))
    monkeypatch.setattr(
        crash_recovery,
        "ensure_smartthings_foreground",
        lambda **_kwargs: _step("PASS", package="com.samsung.android.oneconnect"),
    )
    monkeypatch.setattr(
        crash_recovery,
        "recover_external_popup_contamination",
        lambda **_kwargs: _step("PASS", recovered=True),
    )
    monkeypatch.setattr(
        crash_recovery,
        "ensure_accessibility_service_enabled",
        lambda **_kwargs: _accessibility_result(True),
    )
    client = _RecoveryClient()

    result = crash_recovery.run_recovery_preflight(
        client=client,
        serial="SERIAL",
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is True
    assert result.reason == "ok"
    assert result.relaunch_result == "success"
    assert result.preflight_result == "passed"
    assert result.helper_status == "ok"
    assert result.talkback_status == "ok"
    assert result.foreground_status == "ok"
    assert client.calls == [("ping", "SERIAL", 3.0), ("talkback", "SERIAL")]


def test_recovery_preflight_passes_when_final_sanity_is_ok_after_initial_foreground_failure(monkeypatch):
    foreground_results = iter(
        [
            _step("FAIL", package="com.sec.android.app.launcher"),
            _step("PASS", package="com.samsung.android.oneconnect"),
        ]
    )
    monkeypatch.setattr(crash_recovery, "wake_screen", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(crash_recovery, "unlock_swipe", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(crash_recovery, "ensure_smartthings_foreground", lambda **_kwargs: next(foreground_results))
    monkeypatch.setattr(
        crash_recovery,
        "recover_external_popup_contamination",
        lambda **_kwargs: _step("PASS", recovered=True),
    )
    monkeypatch.setattr(
        crash_recovery,
        "ensure_accessibility_service_enabled",
        lambda **_kwargs: _accessibility_result(True),
    )

    result = crash_recovery.run_recovery_preflight(
        client=_RecoveryClient(),
        serial="SERIAL",
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is True
    assert result.reason == "ok"
    assert result.relaunch_result == "success"
    assert result.preflight_result == "passed"
    assert result.helper_status == "ok"
    assert result.talkback_status == "ok"
    assert result.foreground_status == "ok"
    assert result.foreground_package == "com.samsung.android.oneconnect"


def test_recovery_preflight_foreground_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(crash_recovery, "wake_screen", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(crash_recovery, "unlock_swipe", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(
        crash_recovery,
        "ensure_smartthings_foreground",
        lambda **_kwargs: _step("FAIL", package="com.example.other"),
    )
    monkeypatch.setattr(
        crash_recovery,
        "recover_external_popup_contamination",
        lambda **_kwargs: _step("PASS", recovered=True),
    )
    monkeypatch.setattr(
        crash_recovery,
        "ensure_accessibility_service_enabled",
        lambda **_kwargs: _accessibility_result(True),
    )

    result = crash_recovery.run_recovery_preflight(
        client=_RecoveryClient(),
        serial="SERIAL",
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "foreground_not_confirmed"
    assert result.relaunch_result == "failed"
    assert result.preflight_result == "failed"
    assert result.helper_status == "ok"
    assert result.talkback_status == "ok"
    assert result.foreground_status == "fail"


def test_recovery_preflight_helper_failure_reason(monkeypatch):
    monkeypatch.setattr(crash_recovery, "wake_screen", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(crash_recovery, "unlock_swipe", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(
        crash_recovery,
        "ensure_smartthings_foreground",
        lambda **_kwargs: _step("PASS", package="com.samsung.android.oneconnect"),
    )
    monkeypatch.setattr(
        crash_recovery,
        "recover_external_popup_contamination",
        lambda **_kwargs: _step("PASS", recovered=True),
    )
    monkeypatch.setattr(
        crash_recovery,
        "ensure_accessibility_service_enabled",
        lambda **_kwargs: _accessibility_result(False, reason="helper_ready_timeout"),
    )

    result = crash_recovery.run_recovery_preflight(
        client=_RecoveryClient(),
        serial="SERIAL",
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "helper_not_ready"
    assert result.preflight_result == "failed"
    assert result.helper_status == "fail"
    assert result.talkback_status == "ok"
    assert result.foreground_status == "ok"


def test_recovery_preflight_talkback_failure_reason(monkeypatch):
    monkeypatch.setattr(crash_recovery, "wake_screen", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(crash_recovery, "unlock_swipe", lambda **_kwargs: _step("PASS"))
    monkeypatch.setattr(
        crash_recovery,
        "ensure_smartthings_foreground",
        lambda **_kwargs: _step("PASS", package="com.samsung.android.oneconnect"),
    )
    monkeypatch.setattr(
        crash_recovery,
        "recover_external_popup_contamination",
        lambda **_kwargs: _step("PASS", recovered=True),
    )
    monkeypatch.setattr(
        crash_recovery,
        "ensure_accessibility_service_enabled",
        lambda **_kwargs: _accessibility_result(True),
    )

    result = crash_recovery.run_recovery_preflight(
        client=_RecoveryClient(talkback_status="enabled_but_not_ready"),
        serial="SERIAL",
        sleep_fn=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.reason == "talkback_not_ready"
    assert result.preflight_result == "failed"
    assert result.helper_status == "ok"
    assert result.talkback_status == "fail"
    assert result.foreground_status == "ok"


def test_relaunch_recovery_decision_updates_context(tmp_path):
    artifact_dir = tmp_path / "crashes" / "CRASH-0003"
    artifact_dir.mkdir(parents=True)
    context_path = artifact_dir / "crash_context.json"
    context_path.write_text(
        json.dumps({"recovery": {"decision": "capture_only", "retry_count": 0}}, indent=2),
        encoding="utf-8",
    )
    signal = crash_recovery.CrashTerminalSignal(
        is_crash_like=True,
        scenario_id="global_nav_main",
        stop_reason="app_terminated",
        crash_type="APP_TERMINATED",
        crash_event_id="CRASH-0003",
        artifact_dir=str(artifact_dir),
    )
    preflight = crash_recovery.RecoveryPreflightResult(
        ok=True,
        reason="ok",
        relaunch_result="success",
        preflight_result="passed",
        helper_status="ok",
        talkback_status="ok",
        foreground_status="ok",
        foreground_package="com.samsung.android.oneconnect",
        wake_screen={},
        unlock_swipe={},
        app_foreground={},
        popup_recovery={},
        helper={},
        talkback={},
        final_foreground={},
    )
    decision = crash_recovery.build_relaunch_recovery_decision(signal, preflight)

    assert crash_recovery.update_crash_context_recovery(signal, decision) is True

    payload = json.loads(context_path.read_text(encoding="utf-8"))
    assert payload["recovery"] == {
        "decision": "relaunch_only",
        "retry_count": 0,
        "result": "recovery_preflight_passed",
        "scenario_final_status": "CRASH_CAPTURED",
        "next_action": "continue_without_retry",
        "relaunch_result": "success",
        "preflight_result": "passed",
    }
    assert crash_recovery.render_recovery_log_lines(decision) == [
        "[CRASH_RECOVERY] state='CRASH_DETECTED' scenario='global_nav_main' crash_event_id='CRASH-0003' crash_type='APP_TERMINATED' attempt=0",
        "[CRASH_RECOVERY] state='ARTIFACT_CAPTURED' scenario='global_nav_main' crash_event_id='CRASH-0003'",
        "[CRASH_RECOVERY] state='RELAUNCHING' scenario='global_nav_main' crash_event_id='CRASH-0003'",
        "[CRASH_RECOVERY] relaunch_result='success' foreground='com.samsung.android.oneconnect'",
        "[CRASH_RECOVERY] state='RECOVERY_PREFLIGHT' scenario='global_nav_main'",
        "[CRASH_RECOVERY] preflight_result='passed' helper='ok' talkback='ok' foreground='ok'",
        "[CRASH_RECOVERY] state='CONTINUE_WITHOUT_RETRY' scenario='global_nav_main'",
    ]


def _signal(
    *,
    crash_type="APP_TERMINATED",
    event_id="CRASH-0001",
    attempt=0,
    artifact_dir="",
):
    return crash_recovery.CrashTerminalSignal(
        is_crash_like=True,
        scenario_id="global_nav_main",
        stop_reason={
            "CONFIRMED_CRASH": "confirmed_crash",
            "POSSIBLE_CRASH": "possible_crash",
            "APP_TERMINATED": "app_terminated",
        }.get(crash_type, "possible_crash"),
        crash_type=crash_type,
        crash_event_id=event_id,
        attempt=attempt,
        artifact_dir=artifact_dir,
    )


def test_crash_run_stats_app_terminated_recovered_is_not_counted_for_abort():
    stats = crash_recovery.CrashRunStats()
    signal = _signal(crash_type="APP_TERMINATED")
    decision = crash_recovery.build_retry_outcome_decision(signal, recovered=True)

    crash_recovery.update_crash_run_stats(stats, signal=signal, decision=decision)
    policy = crash_recovery.should_abort_for_crash_policy(stats, threshold=5, decision=decision)

    assert stats.app_terminated_count == 1
    assert stats.crash_recovered_count == 1
    assert stats.counted_crash_count == 0
    assert policy["decision"] == "continue"


def test_crash_run_stats_confirmed_repeated_is_counted():
    stats = crash_recovery.CrashRunStats()
    first = _signal(crash_type="CONFIRMED_CRASH", event_id="CRASH-0001", attempt=0)
    retry = _signal(crash_type="CONFIRMED_CRASH", event_id="CRASH-0002", attempt=1)
    decision = crash_recovery.build_retry_outcome_decision(retry, recovered=False)

    crash_recovery.update_crash_run_stats(stats, signal=first, decision=decision, retry_signal=retry)

    assert stats.confirmed_crash_count == 2
    assert stats.crash_repeated_count == 1
    assert stats.counted_crash_count == 2


def test_crash_run_stats_possible_retry_consumed_is_counted():
    stats = crash_recovery.CrashRunStats()
    signal = _signal(crash_type="POSSIBLE_CRASH")
    decision = crash_recovery.build_retry_outcome_decision(signal, recovered=True)

    crash_recovery.update_crash_run_stats(stats, signal=signal, decision=decision)

    assert stats.possible_crash_count == 1
    assert stats.counted_crash_count == 1


def test_crash_policy_threshold_reached_aborts():
    stats = crash_recovery.CrashRunStats(counted_crash_count=5)

    policy = crash_recovery.should_abort_for_crash_policy(stats, threshold=5)

    assert policy == {
        "decision": "abort",
        "reason": "crash_threshold_exceeded",
        "counted_crash_count": 5,
        "threshold": 5,
    }


def test_crash_abort_threshold_env_override(monkeypatch):
    monkeypatch.setenv("TB_CRASH_ABORT_THRESHOLD", "2")

    assert crash_recovery.resolve_crash_abort_threshold() == 2


def test_update_crash_context_batch_policy(tmp_path):
    artifact_dir = tmp_path / "crashes" / "CRASH-0001"
    artifact_dir.mkdir(parents=True)
    context_path = artifact_dir / "crash_context.json"
    context_path.write_text(json.dumps({"recovery": {}}), encoding="utf-8")
    signal = _signal(artifact_dir=str(artifact_dir))
    policy = {
        "decision": "abort",
        "reason": "crash_threshold_exceeded",
        "counted_crash_count": 5,
        "threshold": 5,
    }

    assert crash_recovery.update_crash_context_batch_policy(signal, policy) is True

    payload = json.loads(context_path.read_text(encoding="utf-8"))
    assert payload["batch_policy"] == {
        "counted_crash_count": 5,
        "threshold": 5,
        "decision": "abort",
        "reason": "crash_threshold_exceeded",
    }


def _patch_script_main_basics(monkeypatch, tmp_path, logs, tab_configs=None):
    monkeypatch.setattr(script_test.args, "serial", "SERIAL")
    monkeypatch.setattr(script_test.args, "output_dir", str(tmp_path))
    monkeypatch.setattr(script_test.args, "mode", "smoke")
    monkeypatch.setattr(script_test.args, "language_mode", "current")
    monkeypatch.setattr(script_test.args, "launch_mode", "warm")
    monkeypatch.setattr(script_test.args, "scenario", [])
    monkeypatch.setattr(script_test, "log", logs.append)
    monkeypatch.setattr(script_test, "configure_log_files", lambda _output_path: None)
    monkeypatch.setattr(script_test, "close_log_files", lambda: None)
    monkeypatch.setattr(script_test, "configure_process_temp_dir", lambda _path: (True, str(tmp_path / ".tmp")))
    monkeypatch.setattr(script_test, "generate_output_path", lambda: str(tmp_path / "run.xlsx"))
    monkeypatch.setattr(script_test, "save_excel_with_perf", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        script_test,
        "run_preflight",
        lambda **_kwargs: SimpleNamespace(ok=True, talkback_status="enabled", talkback_reason="", reason="ok"),
    )
    monkeypatch.setattr(
        script_test,
        "load_runtime_bundle",
        lambda _configs: {
            "tab_configs": tab_configs
            or [{"enabled": True, "scenario_id": "global_nav_main", "tab_name": "Home"}],
            "checkpoint_save_every": 1,
        },
    )
    monkeypatch.setattr(script_test, "apply_run_selection", lambda configs, *_args, **_kwargs: configs)
    monkeypatch.setattr(script_test, "recover_to_start_state", lambda *_args, **_kwargs: True)


def test_script_test_retry_success_marks_crash_recovered(monkeypatch, tmp_path):
    logs = []
    fake_client = _RecoveryClient()
    collect_calls = []
    recovery_calls = []
    artifact_dir = tmp_path / "run" / "crashes" / "CRASH-0001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "crash_context.json").write_text(json.dumps({"recovery": {}}), encoding="utf-8")
    _patch_script_main_basics(monkeypatch, tmp_path, logs)
    monkeypatch.setattr(script_test, "A11yAdbClient", lambda dev_serial=None: fake_client)

    def collect_tab_rows(client, *_args, **_kwargs):
        attempt = int(_args[1].get("_crash_attempt", 0))
        collect_calls.append(attempt)
        if attempt == 0:
            client.last_crash_terminal_signal = {
                "is_crash_like": True,
                "scenario_id": "global_nav_main",
                "stop_reason": "app_terminated",
                "crash_type": "APP_TERMINATED",
                "crash_event_id": "CRASH-0001",
                "artifact_dir": str(artifact_dir),
                "attempt": 0,
            }
            return [{"status": "END", "stop_reason": "app_terminated", "crash_event_id": "CRASH-0001"}]
        client.last_crash_terminal_signal = {}
        return [{"status": "END", "stop_reason": "repeat_no_progress"}]

    def run_recovery_preflight(**kwargs):
        recovery_calls.append(kwargs)
        return crash_recovery.RecoveryPreflightResult(
            ok=True,
            reason="ok",
            relaunch_result="success",
            preflight_result="passed",
            helper_status="ok",
            talkback_status="ok",
            foreground_status="ok",
            foreground_package="com.samsung.android.oneconnect",
            wake_screen={},
            unlock_swipe={},
            app_foreground={},
            popup_recovery={},
            helper={},
            talkback={},
            final_foreground={},
        )

    monkeypatch.setattr(script_test, "collect_tab_rows", collect_tab_rows)
    monkeypatch.setattr(script_test, "run_recovery_preflight", run_recovery_preflight)

    assert script_test.main() == 0

    assert collect_calls == [0, 1]
    assert len(recovery_calls) == 1
    assert recovery_calls[0]["client"] is fake_client
    detected_index = next(index for index, line in enumerate(logs) if "[CRASH_RECOVERY] state='CRASH_DETECTED'" in line)
    artifact_index = next(index for index, line in enumerate(logs) if "[CRASH_RECOVERY] state='ARTIFACT_CAPTURED'" in line)
    relaunch_index = next(index for index, line in enumerate(logs) if "[CRASH_RECOVERY] state='RELAUNCHING'" in line)
    assert detected_index < artifact_index < relaunch_index
    assert any("[CRASH_RECOVERY] state='RETRYING_SCENARIO' scenario='global_nav_main' crash_event_id='CRASH-0001' attempt=1" in line for line in logs)
    assert any("[CRASH_RECOVERY] state='CRASH_RECOVERED' scenario='global_nav_main' attempt=1" in line for line in logs)
    assert not any("[CRASH_RECOVERY] state='CONTINUE_WITHOUT_RETRY'" in line for line in logs)
    payload = json.loads((artifact_dir / "crash_context.json").read_text(encoding="utf-8"))
    assert payload["recovery"]["decision"] == "retry_once"
    assert payload["recovery"]["retry_count"] == 1
    assert payload["recovery"]["result"] == "crash_recovered"
    assert payload["recovery"]["scenario_final_status"] == "CRASH_RECOVERED"


def test_script_test_retry_crash_marks_crash_repeated_and_skips(monkeypatch, tmp_path):
    logs = []
    fake_client = _RecoveryClient()
    collect_calls = []
    artifact_1 = tmp_path / "run" / "crashes" / "CRASH-0001"
    artifact_2 = tmp_path / "run" / "crashes" / "CRASH-0002"
    artifact_1.mkdir(parents=True)
    artifact_2.mkdir(parents=True)
    (artifact_1 / "crash_context.json").write_text(json.dumps({"recovery": {}}), encoding="utf-8")
    (artifact_2 / "crash_context.json").write_text(json.dumps({"recovery": {}}), encoding="utf-8")
    _patch_script_main_basics(monkeypatch, tmp_path, logs)
    monkeypatch.setattr(script_test, "A11yAdbClient", lambda dev_serial=None: fake_client)

    def collect_tab_rows(client, *_args, **_kwargs):
        attempt = int(_args[1].get("_crash_attempt", 0))
        collect_calls.append(attempt)
        event_id = "CRASH-0001" if attempt == 0 else "CRASH-0002"
        artifact_dir = artifact_1 if attempt == 0 else artifact_2
        client.last_crash_terminal_signal = {
            "is_crash_like": True,
            "scenario_id": "global_nav_main",
            "stop_reason": "app_terminated",
            "crash_type": "APP_TERMINATED",
            "crash_event_id": event_id,
            "artifact_dir": str(artifact_dir),
            "attempt": attempt,
        }
        return [{"status": "END", "stop_reason": "app_terminated", "crash_event_id": event_id}]

    monkeypatch.setattr(script_test, "collect_tab_rows", collect_tab_rows)
    monkeypatch.setattr(
        script_test,
        "run_recovery_preflight",
        lambda **_kwargs: crash_recovery.RecoveryPreflightResult(
            ok=True,
            reason="ok",
            relaunch_result="success",
            preflight_result="passed",
            helper_status="ok",
            talkback_status="ok",
            foreground_status="ok",
            foreground_package="com.samsung.android.oneconnect",
            wake_screen={},
            unlock_swipe={},
            app_foreground={},
            popup_recovery={},
            helper={},
            talkback={},
            final_foreground={},
        ),
    )

    assert script_test.main() == 0

    assert collect_calls == [0, 1]
    assert any("[CRASH_RECOVERY] state='CRASH_REPEATED' scenario='global_nav_main' attempt=1" in line for line in logs)
    assert any("[CRASH_RECOVERY] scenario_skip scenario='global_nav_main' reason='crash_repeated'" in line for line in logs)
    payload_1 = json.loads((artifact_1 / "crash_context.json").read_text(encoding="utf-8"))
    payload_2 = json.loads((artifact_2 / "crash_context.json").read_text(encoding="utf-8"))
    assert payload_1["recovery"]["result"] == "crash_repeated"
    assert payload_2["recovery"]["scenario_final_status"] == "CRASH_REPEATED"


def test_script_test_recovery_preflight_failure_does_not_retry(monkeypatch, tmp_path):
    logs = []
    fake_client = _RecoveryClient()
    collect_calls = []
    artifact_dir = tmp_path / "run" / "crashes" / "CRASH-0001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "crash_context.json").write_text(json.dumps({"recovery": {}}), encoding="utf-8")
    _patch_script_main_basics(monkeypatch, tmp_path, logs)
    monkeypatch.setattr(script_test, "A11yAdbClient", lambda dev_serial=None: fake_client)

    def collect_tab_rows(client, *_args, **_kwargs):
        attempt = int(_args[1].get("_crash_attempt", 0))
        collect_calls.append(attempt)
        client.last_crash_terminal_signal = {
            "is_crash_like": True,
            "scenario_id": "global_nav_main",
            "stop_reason": "app_terminated",
            "crash_type": "APP_TERMINATED",
            "crash_event_id": "CRASH-0001",
            "artifact_dir": str(artifact_dir),
            "attempt": attempt,
        }
        return [{"status": "END", "stop_reason": "app_terminated", "crash_event_id": "CRASH-0001"}]

    monkeypatch.setattr(script_test, "collect_tab_rows", collect_tab_rows)
    monkeypatch.setattr(
        script_test,
        "run_recovery_preflight",
        lambda **_kwargs: crash_recovery.RecoveryPreflightResult(
            ok=False,
            reason="foreground_not_confirmed",
            relaunch_result="failed",
            preflight_result="failed",
            helper_status="ok",
            talkback_status="ok",
            foreground_status="fail",
            foreground_package="com.example.other",
            wake_screen={},
            unlock_swipe={},
            app_foreground={},
            popup_recovery={},
            helper={},
            talkback={},
            final_foreground={},
        ),
    )

    assert script_test.main() == 0

    assert collect_calls == [0]
    assert not any("state='RETRYING_SCENARIO'" in line for line in logs)
    assert any("[CRASH_RECOVERY] state='CONTINUE_WITHOUT_RETRY' scenario='global_nav_main'" in line for line in logs)
    payload = json.loads((artifact_dir / "crash_context.json").read_text(encoding="utf-8"))
    assert payload["recovery"]["decision"] == "relaunch_only"
    assert payload["recovery"]["result"] == "recovery_preflight_failed"


def test_script_test_retry_never_enters_attempt_two(monkeypatch, tmp_path):
    logs = []
    fake_client = _RecoveryClient()
    collect_calls = []
    artifact_1 = tmp_path / "run" / "crashes" / "CRASH-0001"
    artifact_2 = tmp_path / "run" / "crashes" / "CRASH-0002"
    artifact_1.mkdir(parents=True)
    artifact_2.mkdir(parents=True)
    (artifact_1 / "crash_context.json").write_text(json.dumps({"recovery": {}}), encoding="utf-8")
    (artifact_2 / "crash_context.json").write_text(json.dumps({"recovery": {}}), encoding="utf-8")
    _patch_script_main_basics(monkeypatch, tmp_path, logs)
    monkeypatch.setattr(script_test, "A11yAdbClient", lambda dev_serial=None: fake_client)

    def collect_tab_rows(client, *_args, **_kwargs):
        attempt = int(_args[1].get("_crash_attempt", 0))
        assert attempt <= 1
        collect_calls.append(attempt)
        artifact_dir = artifact_1 if attempt == 0 else artifact_2
        client.last_crash_terminal_signal = {
            "is_crash_like": True,
            "scenario_id": "global_nav_main",
            "stop_reason": "app_terminated",
            "crash_type": "APP_TERMINATED",
            "crash_event_id": f"CRASH-000{attempt + 1}",
            "artifact_dir": str(artifact_dir),
            "attempt": attempt,
        }
        return [{"status": "END", "stop_reason": "app_terminated"}]

    monkeypatch.setattr(script_test, "collect_tab_rows", collect_tab_rows)
    monkeypatch.setattr(
        script_test,
        "run_recovery_preflight",
        lambda **_kwargs: crash_recovery.RecoveryPreflightResult(
            ok=True,
            reason="ok",
            relaunch_result="success",
            preflight_result="passed",
            helper_status="ok",
            talkback_status="ok",
            foreground_status="ok",
            foreground_package="com.samsung.android.oneconnect",
            wake_screen={},
            unlock_swipe={},
            app_foreground={},
            popup_recovery={},
            helper={},
            talkback={},
            final_foreground={},
        ),
    )

    assert script_test.main() == 0

    assert collect_calls == [0, 1]
    assert not any("attempt=2" in line for line in logs)


def test_script_test_threshold_abort_breaks_remaining_scenarios_and_final_saves(monkeypatch, tmp_path):
    logs = []
    fake_client = _RecoveryClient()
    collect_calls = []
    save_calls = []
    artifact_dir = tmp_path / "run" / "crashes" / "CRASH-0001"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "crash_context.json").write_text(json.dumps({"recovery": {}}), encoding="utf-8")
    _patch_script_main_basics(
        monkeypatch,
        tmp_path,
        logs,
        tab_configs=[
            {"enabled": True, "scenario_id": "global_nav_main", "tab_name": "Home"},
            {"enabled": True, "scenario_id": "life_home_monitor_plugin", "tab_name": "Life"},
        ],
    )
    monkeypatch.setenv("TB_CRASH_ABORT_THRESHOLD", "1")
    monkeypatch.setattr(script_test, "A11yAdbClient", lambda dev_serial=None: fake_client)
    monkeypatch.setattr(script_test, "save_excel_with_perf", lambda *args, **kwargs: save_calls.append((args, kwargs)))

    def collect_tab_rows(client, *_args, **_kwargs):
        tab_cfg = _args[1]
        attempt = int(tab_cfg.get("_crash_attempt", 0))
        collect_calls.append((tab_cfg["scenario_id"], attempt))
        if attempt == 0:
            client.last_crash_terminal_signal = {
                "is_crash_like": True,
                "scenario_id": "global_nav_main",
                "stop_reason": "confirmed_crash",
                "crash_type": "CONFIRMED_CRASH",
                "crash_event_id": "CRASH-0001",
                "artifact_dir": str(artifact_dir),
                "attempt": 0,
            }
            return [{"status": "END", "stop_reason": "confirmed_crash", "crash_event_id": "CRASH-0001"}]
        client.last_crash_terminal_signal = {}
        return [{"status": "END", "stop_reason": "repeat_no_progress"}]

    monkeypatch.setattr(script_test, "collect_tab_rows", collect_tab_rows)
    monkeypatch.setattr(
        script_test,
        "run_recovery_preflight",
        lambda **_kwargs: crash_recovery.RecoveryPreflightResult(
            ok=True,
            reason="ok",
            relaunch_result="success",
            preflight_result="passed",
            helper_status="ok",
            talkback_status="ok",
            foreground_status="ok",
            foreground_package="com.samsung.android.oneconnect",
            wake_screen={},
            unlock_swipe={},
            app_foreground={},
            popup_recovery={},
            helper={},
            talkback={},
            final_foreground={},
        ),
    )

    assert script_test.main() == 0

    assert collect_calls == [("global_nav_main", 0), ("global_nav_main", 1)]
    assert save_calls
    assert any("[CRASH_POLICY] decision='abort' reason='crash_threshold_exceeded' counted=1 threshold=1" in line for line in logs)
    payload = json.loads((artifact_dir / "crash_context.json").read_text(encoding="utf-8"))
    assert payload["batch_policy"] == {
        "counted_crash_count": 1,
        "threshold": 1,
        "decision": "abort",
        "reason": "crash_threshold_exceeded",
    }


def test_script_test_no_crash_path_does_not_run_recovery_preflight(monkeypatch, tmp_path):
    logs = []
    fake_client = _RecoveryClient()
    collect_calls = []
    _patch_script_main_basics(monkeypatch, tmp_path, logs)
    monkeypatch.setattr(script_test, "A11yAdbClient", lambda dev_serial=None: fake_client)

    def collect_tab_rows(client, *_args, **_kwargs):
        collect_calls.append(client)
        client.last_crash_terminal_signal = {}
        return [{"status": "END", "stop_reason": "repeat_no_progress"}]

    monkeypatch.setattr(script_test, "collect_tab_rows", collect_tab_rows)
    monkeypatch.setattr(
        script_test,
        "run_recovery_preflight",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("recovery preflight must not run")),
    )

    assert script_test.main() == 0

    assert collect_calls == [fake_client]
    assert not any("[CRASH_RECOVERY] state='RELAUNCHING'" in line for line in logs)
