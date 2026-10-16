"""Phase 5 final closure metadata and safety-limit accounting regressions."""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLOSURE_PATH = PROJECT_ROOT / "docs/design/talkback-phase5-final-closure-20261017.json"


def load_closure():
    return json.loads(CLOSURE_PATH.read_text(encoding="utf-8"))


def test_final_ledger_has_canonical_32_ids_and_expected_aggregation():
    closure = load_closure()
    ledger = closure["scenarios"]
    ids = [row["scenario_id"] for row in ledger]

    assert len(ledger) == 32
    assert ids == list(range(1, 33))
    assert len(set(ids)) == 32
    assert closure["accounting"] == {
        "total_scenarios": 32,
        "accepted_scenario_count": 30,
        "safety_limit_scenario_count": 2,
        "fail_scenario_count": 0,
        "other_status_count": 0,
        "counts_as_pass_true_count": 30,
        "counts_as_fail_true_count": 0,
        "counts_as_safety_limit_true_count": 2,
        "raw_prior_terminal_status_counts_for_scenarios_1_to_30": {
            "COMPLETED": 8,
            "INCOMPLETE_NO_PROGRESS": 4,
            "INCOMPLETE_SAFETY_LIMIT": 17,
            "NO_DEDICATED_TERMINAL_STATUS": 1,
        },
        "aggregation_correct": True,
        "claim_32_of_32_pass": False,
    }


def test_scenario31_is_a_nonpass_nonfail_manual_safety_limit():
    closure = load_closure()
    row = closure["scenarios"][30]

    assert row["scenario_name"] == "life_home_monitor_plugin"
    assert row["status"] == "INCOMPLETE_SAFETY_LIMIT"
    assert row["limitation_class"] == "MANUAL_SAFETY_LIMITATION"
    assert row["blocker_stage"] == "AUTOMATED_ENTRY_SAFETY_APPROVAL"
    assert row["counts_as_pass"] is False
    assert row["counts_as_fail"] is False
    assert row["counts_as_safety_limit"] is True
    assert row["historical_attempt_status"] == "REJECTED"
    assert row["historical_attempt_preserved"] is True
    assert "TalkBack 포커스/발화 검증 자체가 원인은 아니다" in row["reason"]
    assert row["future_reopen_conditions"]


def test_scenario32_safety_limit_keeps_retry01_as_historical_error():
    closure = load_closure()
    row = closure["scenarios"][31]
    retry = row["retry01_historical_result"]

    assert row["scenario_name"] == "life_music_sync_plugin"
    assert row["status"] == "INCOMPLETE_SAFETY_LIMIT"
    assert row["limitation_class"] == "MANUAL_SAFETY_LIMITATION"
    assert row["blocker_stage"] == "EXACT_ACTION_SEMANTIC_AND_APPLICATION_ISOLATION"
    assert row["counts_as_pass"] is False
    assert row["counts_as_fail"] is False
    assert row["counts_as_safety_limit"] is True
    assert retry["result"] == "INCOMPLETE_ERROR"
    assert retry["terminal_reason"] == "tab_or_anchor_failed"
    assert retry["retry_index"] == 1
    assert retry["total_attempts_including_original"] == 2
    assert retry["first_attempt_preserved"] is True
    assert retry["additional_retry_performed"] is False
    assert retry["dispatch_cursor_status"] == "DEVICE_UPTIME_CURSOR_MISSING"
    assert retry["event_correlation"] == "REJECTED"
    assert retry["attempted_steps"] == 0
    assert retry["visits"] == 0
    assert row["future_reopen_conditions"]


def test_accepted_prefix_retains_per_scenario_terminal_variants_and_provenance():
    closure = load_closure()
    prefix = closure["scenarios"][:30]

    assert all(row["status"] == "ACCEPTED_PRESERVED" for row in prefix)
    assert all(row["counts_as_pass"] is True for row in prefix)
    assert all(row["counts_as_fail"] is False for row in prefix)
    assert all(row["counts_as_safety_limit"] is False for row in prefix)
    assert all(row["preserved_source_line"] == i for i, row in enumerate(prefix, 1))
    assert all(len(row["preserved_source_record_sha256"]) == 64 for row in prefix)
    assert closure["source"]["preserved_prefix"]["sha256"] == (
        "801e94050b4b263d2c53b1dd687d7a963d892dac781e966c90ebf96b2a326985"
    )
    assert closure["source"]["preserved_prefix"]["scenarios_1_to_30_records_unchanged"] is True


def test_phase_verdicts_are_not_final_before_gates_and_finalize_with_limitations():
    closure = load_closure()
    assert closure["record_state"] in {"VALIDATION_PENDING", "FINALIZED"}

    if closure["record_state"] == "VALIDATION_PENDING":
        assert closure["phase5c"]["verdict"] is None
        assert closure["phase5c"]["closure_conditions_met"] is False
        assert closure["phase5"]["verdict"] is None
        assert closure["phase5"]["closure_conditions_met"] is False
        assert closure["phase6"]["safe_to_start_review"] is False
    else:
        assert closure["phase5c"]["verdict"] == "PASS_WITH_LIMITATIONS"
        assert closure["phase5c"]["closure_conditions_met"] is True
        assert closure["phase5"]["verdict"] == "PASS_WITH_LIMITATIONS"
        assert closure["phase5"]["closure_conditions_met"] is True
        assert closure["phase6"]["safe_to_start_review"] is True
        gates = closure["regression_gates"]
        assert gates["scenario31_metadata"] == "PASS"
        assert gates["scenario32_metadata_and_retry_history"] == "PASS"
        assert gates["aggregation_and_accepted_prefix_integrity"] == "PASS"
        assert gates["phase5_focused_and_c4_c5_c6_safety_regression"].startswith("PASS")
        assert gates["full_python_suite"].startswith("PASS")
        assert gates["android_unit_tests"].startswith("PASS")
        assert gates["android_build"].startswith("PASS")

    assert closure["phase5"]["production_visit_authority_unchanged"] is True
    assert closure["phase5"]["exact_action_build_gate_default"] == "OFF"
    assert closure["phase5"]["runtime_action_gate_default"] == "OFF"
    assert closure["clock_architecture"]["implemented"] is False
    assert closure["clock_architecture"]["required_before_phase5_closure"] is False
    assert closure["phase6"]["started"] is False
    assert closure["phase6"]["ready_for_implementation"] is False
    assert closure["regression_gates"]["false_safe_approval_count"] == 0
