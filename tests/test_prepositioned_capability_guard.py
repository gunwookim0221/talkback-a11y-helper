from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from talkback_lib import (
    DEFAULT_HIERARCHY_TRANSPORT_MODE,
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
    assert event["kind"] == "READ_ONLY_QUERY"
    assert event["phase"] == "READ_ONLY"
    assert event["command"][4] == HELPER_ACTION_PREFIX + "HIERARCHY_TRANSFER_CAPABILITIES"
    assert not any(row["event"] in {"SAFETY_STOP", "INTERNAL_TRAVERSAL_TERMINAL"}
                   for row in _audit(session))


@pytest.mark.parametrize(
    ("action", "expected_kind"),
    [
        ("HIERARCHY_TRANSFER_CAPABILITIES", "READ_ONLY_QUERY"),
        ("HIERARCHY_TRANSFER_START", "READ_ONLY_OBSERVATION_CONTROL"),
        ("HIERARCHY_TRANSFER_STATUS", "READ_ONLY_OBSERVATION_CONTROL"),
        ("HIERARCHY_TRANSFER_ACK", "TRANSPORT_CLEANUP_CONTROL"),
        ("HIERARCHY_TRANSFER_CANCEL", "TRANSPORT_CLEANUP_CONTROL"),
    ],
)
def test_exact_reliable_control_actions_have_approved_classification(tmp_path, action, expected_kind):
    assert DEFAULT_HIERARCHY_TRANSPORT_MODE == "RELIABLE_FILE_PFD"
    _, session = _session(tmp_path)

    session.guard_command(_broadcast(action, "--es", "queryNonce", "a" * 32))

    event = _audit(session)[-1]
    assert event["event"] == "COMMAND_ALLOWED"
    assert event["kind"] == expected_kind
    assert event["phase"] == "READ_ONLY"


def test_capability_query_remains_read_only_during_prepositioned_traversal(tmp_path):
    _, session = _session(tmp_path)
    session.destination = {"verdict": "PASS"}
    session.begin_traversal()

    session.guard_command(_broadcast("HIERARCHY_TRANSFER_CAPABILITIES", "--es", "queryNonce", "b" * 32))

    event = _audit(session)[-1]
    assert event["event"] == "COMMAND_ALLOWED"
    assert event["kind"] == "READ_ONLY_QUERY"
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
        _broadcast("HIERARCHY_TRANSFER_UNRECOGNIZED"),
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
