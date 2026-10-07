import json
import pytest

from tb_runner.target_attempt_ledger import TargetAttemptLedger


@pytest.mark.parametrize("status,state", [
    ("TARGET_MATCHED", "MATCHED"), ("TARGET_NOT_FOUND", "NOT_FOUND"),
    ("AMBIGUOUS_TARGET", "AMBIGUOUS_TARGET"), ("UNAVAILABLE", "UNAVAILABLE"),
    ("talkback_restarted", "INTERRUPTED_TALKBACK_RESTART"),
    ("parse_error", "TRANSPORT_ERROR"), ("NO_RESULT", "NO_RESULT"),
])
def test_attempt_preserved_even_without_normal_workbook_row(tmp_path, status, state):
    ledger = TargetAttemptLedger(tmp_path / "run.xlsx")
    attempt = ledger.begin("life_main", 1, {"label": "가"})
    ledger.finish(attempt, status=status, result={"reqId": "req-1", "status": status})
    document = ledger.reconcile([])
    assert document["attempt_count"] == document["ledger_count"] == 1
    assert document["entries"][0]["state"] == state
    assert document["entries"][0]["req_id"] == "req-1"
    assert document["workbook_omitted_attempt_count"] == 1
    assert json.loads(ledger.path.read_text(encoding="utf-8")) == document


def test_no_result_is_durable_before_result_or_shutdown(tmp_path):
    ledger = TargetAttemptLedger(tmp_path / "run.xlsx")
    attempt = ledger.begin("life_main", 1, {})
    assert attempt == "target_000001"
    assert json.loads(ledger.path.read_text())["state_counts"] == {"NO_RESULT": 1}


def test_duplicate_result_is_explicit_and_does_not_add_entry():
    ledger = TargetAttemptLedger()
    attempt = ledger.begin("life_main", 1, {})
    ledger.finish(attempt, status="TARGET_MATCHED")
    ledger.finish(attempt, status="TARGET_NOT_FOUND")
    document = ledger.reconcile([{"target_focus_attempt_id": attempt}])
    assert document["attempt_count"] == document["ledger_count"] == 1
    assert document["entries"][0]["reason"] == "duplicate_result"
    assert document["entries"][0]["state"] == "TRANSPORT_ERROR"
    assert document["workbook_target_rows"] == 1


def test_restart_overrides_matched_status():
    ledger = TargetAttemptLedger()
    attempt = ledger.begin("life_main", 1, {})
    entry = ledger.finish(attempt, status="TARGET_MATCHED", restart={"talkback_pid": "456"})
    assert entry["state"] == "INTERRUPTED_TALKBACK_RESTART"
