from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from talkback_lib import (
    A11yAdbClient,
    DEFAULT_HIERARCHY_TRANSPORT_MODE,
    HIERARCHY_PAYLOAD_SCHEMA,
    MAX_HIERARCHY_PAYLOAD_BYTES,
)
from tb_runner.entry_mode import PrepositionedSafetyStop, PrepositionedSession


HELPER_ACTION_PREFIX = "com.iotpart.sqe.talkbackhelper."
HELPER_PACKAGE = "com.iotpart.sqe.talkbackhelper"


def _broadcast(action: str, *extras: str) -> list[str]:
    return ["shell", "am", "broadcast", "-a", HELPER_ACTION_PREFIX + action,
            "-p", HELPER_PACKAGE, *extras]


def _session(tmp_path):
    client = SimpleNamespace(
        _adb_device=SimpleNamespace(command_guard=None),
        evidence_runtime=None,
        _evidence_active_transaction=None,
        _evidence_active_request_id="",
    )
    session = PrepositionedSession(
        client,
        {"scenario_id": "life_home_monitor_plugin"},
        tmp_path / "prepositioned.jsonl",
        log_fn=lambda *_args, **_kwargs: None,
    )
    session.bind()
    return client, session


def _audit(session):
    return [json.loads(line) for line in session.audit_path.read_text(encoding="utf-8").splitlines()]


def test_reliable_default_capability_query_is_read_only_control(tmp_path):
    assert DEFAULT_HIERARCHY_TRANSPORT_MODE == "RELIABLE_FILE_PFD"
    _, session = _session(tmp_path)

    session.guard_command(_broadcast("HIERARCHY_TRANSFER_CAPABILITIES", "--es", "queryNonce", "a" * 32))

    event = _audit(session)[-1]
    assert event["event"] == "COMMAND_ALLOWED"
    assert event["kind"] == "READ_ONLY_CONTROL"
    assert event["phase"] == "READ_ONLY"
    assert event["command"][4] == HELPER_ACTION_PREFIX + "HIERARCHY_TRANSFER_CAPABILITIES"
    assert not any(row["event"] in {"SAFETY_STOP", "INTERNAL_TRAVERSAL_TERMINAL"}
                   for row in _audit(session))


def test_default_reliable_dump_passes_capability_gate_then_stops_at_unlisted_start(tmp_path, monkeypatch):
    assert DEFAULT_HIERARCHY_TRANSPORT_MODE == "RELIABLE_FILE_PFD"
    client = A11yAdbClient(dev_serial="SERIAL", start_monitor=False)
    session = PrepositionedSession(
        client,
        {"scenario_id": "life_home_monitor_plugin"},
        tmp_path / "prepositioned.jsonl",
        log_fn=lambda *_args, **_kwargs: None,
    )
    session.bind()
    helper_identity = {
        "build_id": "a" * 64,
        "git_commit": "b" * 40,
        "source_state": "CLEAN",
        "input_digest": "c" * 64,
        "build_variant": "debug",
    }
    expected_identity = {
        "status": "MATCH",
        "helper_build_id": helper_identity["build_id"],
        "helper_git_commit": helper_identity["git_commit"],
        "helper_service_instance_id": "service-instance-1",
        "helper_input_digest": helper_identity["input_digest"],
        "build_variant": "debug",
    }
    actions = []

    def control(_dev, action, extras, *, request_id, remaining_seconds):
        actions.append(action)
        session.guard_command(_broadcast(f"HIERARCHY_TRANSFER_{action}", *extras))
        if action != "CAPABILITIES":
            pytest.fail(f"unexpected control response after guard: {action}")
        nonce = extras[extras.index("queryNonce") + 1]
        return {
            "schema": "hierarchy-transfer-control.v1",
            "protocol_version": "hierarchy-payload.v1",
            "request_id": None,
            "query_nonce": nonce,
            "process_epoch": "process-epoch-1",
            "service_instance_id": "service-instance-1",
            "generation": 0,
            "helper_build_identity": helper_identity,
            "payload_schema_version": HIERARCHY_PAYLOAD_SCHEMA,
            "max_payload_bytes": MAX_HIERARCHY_PAYLOAD_BYTES,
            "status": "OK",
            "completed": True,
            "payload_complete": True,
            "capabilities": ["content_provider_pfd"],
        }

    monkeypatch.setattr(client, "_hierarchy_transfer_control", control)

    with pytest.raises(PrepositionedSafetyStop):
        client.dump_hierarchy(dev="SERIAL", expected_helper_build_identity=expected_identity)

    assert actions == ["CAPABILITIES", "START"]
    rows = _audit(session)
    capability = next(row for row in rows if row.get("kind") == "READ_ONLY_CONTROL")
    assert capability["phase"] == "READ_ONLY"
    blocked = next(row for row in rows if row["event"] == "COMMAND_BLOCKED")
    assert blocked["command"][4] == HELPER_ACTION_PREFIX + "HIERARCHY_TRANSFER_START"
    terminal = next(row for row in rows if row["event"] == "INTERNAL_TRAVERSAL_TERMINAL")
    assert terminal["safety_classification"] == "UNALLOWLISTED_HIERARCHY_CONTROL"
    assert terminal["blocked_operation_dispatched"] is False


def test_capability_query_remains_read_only_during_prepositioned_traversal(tmp_path):
    _, session = _session(tmp_path)
    session.destination = {"verdict": "PASS"}
    session.begin_traversal()

    session.guard_command(_broadcast("HIERARCHY_TRANSFER_CAPABILITIES", "--es", "queryNonce", "b" * 32))

    event = _audit(session)[-1]
    assert event["event"] == "COMMAND_ALLOWED"
    assert event["kind"] == "READ_ONLY_CONTROL"
    assert event["phase"] == "TRAVERSAL"


def test_unknown_broadcast_still_fails_closed_with_terminal_audit(tmp_path):
    command = _broadcast("UNRECOGNIZED_DIAGNOSTIC", "--es", "queryNonce", "c" * 32)
    _, session = _session(tmp_path)

    with pytest.raises(PrepositionedSafetyStop, match="non_navigation_contract_violation"):
        session.guard_command(command)

    rows = _audit(session)
    blocked = next(row for row in rows if row["event"] == "COMMAND_BLOCKED")
    stopped = next(row for row in rows if row["event"] == "SAFETY_STOP")
    terminal = next(row for row in rows if row["event"] == "INTERNAL_TRAVERSAL_TERMINAL")
    assert blocked["safety_classification"] == "UNKNOWN_BROADCAST"
    assert blocked["action_dispatched"] is False
    assert rows.index(blocked) < rows.index(stopped) < rows.index(terminal)
    assert terminal["terminal_reason"] == "non_navigation_contract_violation"
    assert terminal["blocked_operation"] == command
    assert terminal["safety_classification"] == "UNKNOWN_BROADCAST"
    assert terminal["stage"] == "READ_ONLY"
    assert terminal["no_action_dispatched"] is True
    assert terminal["blocked_operation_dispatched"] is False
    assert terminal["request_context"] == {"queryNonce": "c" * 32}
    assert terminal["traversal_started"] is False
    assert terminal["row_count"] is None
    assert sum(row["event"] == "INTERNAL_TRAVERSAL_TERMINAL" for row in rows) == 1


@pytest.mark.parametrize(
    "command",
    [
        _broadcast("CLICK_TARGET"),
        _broadcast("CLICK_FOCUSED"),
        _broadcast("ACTION_COMMAND", "--es", "command", "activate"),
        _broadcast("HIERARCHY_TRANSFER_START"),
        _broadcast("NOT_A_HELPER_ACTION"),
        ["shell", "input", "tap", "400", "400"],
    ],
)
def test_capability_permission_does_not_allow_mutation_or_other_broadcasts(tmp_path, command):
    _, session = _session(tmp_path)
    session.guard_command(_broadcast("HIERARCHY_TRANSFER_CAPABILITIES", "--es", "queryNonce", "d" * 32))

    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(command)

    rows = _audit(session)
    assert rows[-2]["event"] == "SAFETY_STOP"
    assert rows[-1]["event"] == "INTERNAL_TRAVERSAL_TERMINAL"
    assert rows[-1]["blocked_operation_dispatched"] is False


def test_home_monitor_security_control_activation_remains_blocked(tmp_path):
    _, session = _session(tmp_path)
    command = _broadcast(
        "CLICK_TARGET", "--es", "targetId",
        "com.samsung.android.oneconnect:id/shmBannerAwayButton",
    )

    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(command)

    terminal = _audit(session)[-1]
    assert terminal["safety_classification"] == "MUTATING_ACTION"
    assert terminal["blocked_operation_dispatched"] is False


def test_legacy_hierarchy_read_stays_allowed_without_adding_activation_permission(tmp_path):
    _, session = _session(tmp_path)

    session.guard_command(_broadcast("DUMP_HIERARCHY", "--es", "reqId", "legacy-read"))
    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(_broadcast("CLICK_TARGET"))

    rows = _audit(session)
    assert next(row for row in rows if row.get("kind") == "read_only")["phase"] == "READ_ONLY"
    assert rows[-1]["event"] == "INTERNAL_TRAVERSAL_TERMINAL"


def test_safety_stop_terminal_audit_is_idempotent_when_finalized_later(tmp_path):
    _, session = _session(tmp_path)
    with pytest.raises(PrepositionedSafetyStop):
        session.guard_command(_broadcast("CLICK_TARGET", "--es", "reqId", "blocked-click-1"))

    session.finalize_stop(row_count=0)
    rows = _audit(session)
    terminals = [row for row in rows if row["event"] == "INTERNAL_TRAVERSAL_TERMINAL"]
    assert len(terminals) == 1
    assert terminals[0]["terminal_reason"] == "non_navigation_contract_violation"
    assert terminals[0]["blocked_operation_dispatched"] is False
