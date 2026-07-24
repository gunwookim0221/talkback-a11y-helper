from __future__ import annotations

import json

import pytest

from qa_frontend.backend import batch_runner
from qa_frontend.backend.comparator_ui import ComparatorUiService
from tb_runner.baseline_candidate_builder import CandidateBuildResult, build_baseline_candidate
from tests.test_baseline_candidate_builder import _create_run


def _manager_for(run_root, *, mode="full", state="finished", device_state="passed", return_code=0):
    manager = batch_runner.BatchRunManager()
    manager._mode = mode
    manager._state = state
    return manager, [
        {
            "state": device_state,
            "return_code": return_code,
            "output_dir": str(run_root.relative_to(run_root.parents[1])),
        }
    ]


def _set_no_target_candidate_count(run_root, count):
    summary_path = run_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["no_target_candidate_scenarios"] = count
    summary_path.write_text(json.dumps(summary), encoding="utf-8")


def _candidate_paths(run_root):
    return list(run_root.glob("candidate_*.baseline_candidate.json"))


def _diagnostic_events(run_root):
    payload = json.loads((run_root / "candidate_generation.json").read_text(encoding="utf-8"))
    return payload["events"]


def test_finished_full_run_creates_candidate_and_comparator_lists_it(tmp_path, monkeypatch):
    run_root = _create_run(tmp_path)
    _set_no_target_candidate_count(run_root, 0)
    real_build = build_baseline_candidate
    write_calls = []

    def track_write(run_root, *, write=True, integrate=True):
        if write:
            write_calls.append(run_root)
        return real_build(run_root, write=write, integrate=integrate)

    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(batch_runner, "build_baseline_candidate", track_write)
    manager, devices = _manager_for(run_root)

    manager._auto_generate_full_candidates(devices)

    paths = _candidate_paths(run_root)
    assert len(paths) == 1
    assert write_calls == [run_root]
    events = _diagnostic_events(run_root)
    assert [event["event"] for event in events] == [
        "AUTO_CANDIDATE_STARTED",
        "AUTO_CANDIDATE_PREVIEW_SUCCEEDED",
        "AUTO_CANDIDATE_WRITE_STARTED",
        "AUTO_CANDIDATE_WRITE_SUCCEEDED",
    ]
    assert events[-1]["candidate_id"] == paths[0].stem.removesuffix(".baseline_candidate")
    assert events[-1]["candidate_digest"]
    assert events[-1]["output_path"] == str(paths[0])
    candidates = ComparatorUiService(root_dir=tmp_path, run_log_dir=tmp_path).candidates()
    assert [item["candidate_id"] for item in candidates] == [paths[0].stem.removesuffix(".baseline_candidate")]


@pytest.mark.parametrize(
    ("mode", "state", "device_state", "return_code", "targeted", "no_target", "remove_artifact", "reason"),
    [
        ("smoke", "finished", "passed", 0, False, 0, False, "batch_mode_not_full"),
        ("full", "finished", "passed", 0, True, 0, False, "scenario_set_not_full"),
        ("full", "finished", "failed", 1, False, 0, False, "device_not_passed"),
        ("full", "stopped", "passed", 0, False, 0, False, "batch_not_finished"),
        ("full", "finished", "passed", 0, False, 1, False, "no_target_candidate_scenarios"),
        ("full", "finished", "passed", 0, False, 0, True, "required_artifacts_failed"),
    ],
    ids=["smoke", "targeted", "crash", "stopped", "no-target", "missing-artifact"],
)
def test_non_qualifying_runs_do_not_create_candidates(
    tmp_path,
    monkeypatch,
    mode,
    state,
    device_state,
    return_code,
    targeted,
    no_target,
    remove_artifact,
    reason,
):
    run_root = _create_run(tmp_path, targeted=targeted)
    _set_no_target_candidate_count(run_root, no_target)
    if remove_artifact:
        (run_root / "talkback_compare.focusable_coverage.json").unlink()
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    manager, devices = _manager_for(
        run_root,
        mode=mode,
        state=state,
        device_state=device_state,
        return_code=return_code,
    )

    manager._auto_generate_full_candidates(devices)

    assert _candidate_paths(run_root) == []
    assert _diagnostic_events(run_root)[-1]["event"] == "AUTO_CANDIDATE_SKIPPED"
    assert _diagnostic_events(run_root)[-1]["skip_reason"] == reason


def test_non_zero_return_code_records_a_distinct_skip_reason(tmp_path, monkeypatch):
    run_root = _create_run(tmp_path)
    _set_no_target_candidate_count(run_root, 0)
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    manager, devices = _manager_for(run_root, return_code=1)

    manager._auto_generate_full_candidates(devices)

    assert _diagnostic_events(run_root)[-1]["skip_reason"] == "return_code_not_zero"


def test_terminal_count_shortfall_records_a_distinct_skip_reason(tmp_path, monkeypatch):
    run_root = _create_run(tmp_path)
    _set_no_target_candidate_count(run_root, 0)
    summary_path = run_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update({"completed_scenarios": 31, "executed_scenarios": 31, "passed_scenarios": 31})
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    manager, devices = _manager_for(run_root)

    manager._auto_generate_full_candidates(devices)

    assert _diagnostic_events(run_root)[-1]["skip_reason"] == "scenario_terminal_not_complete"


def test_not_eligible_full_candidate_is_created_and_listed(tmp_path, monkeypatch):
    run_root = _create_run(tmp_path, complete_environment=False)
    _set_no_target_candidate_count(run_root, 0)
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    manager, devices = _manager_for(run_root)

    manager._auto_generate_full_candidates(devices)

    paths = _candidate_paths(run_root)
    assert len(paths) == 1
    candidates = ComparatorUiService(root_dir=tmp_path, run_log_dir=tmp_path).candidates()
    assert candidates[0]["source_status"] == "NOT_ELIGIBLE"


def test_existing_candidate_is_not_overwritten(tmp_path, monkeypatch):
    run_root = _create_run(tmp_path)
    _set_no_target_candidate_count(run_root, 0)
    existing = build_baseline_candidate(run_root, write=True, integrate=False).path
    assert existing is not None
    original = existing.read_bytes()
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    manager, devices = _manager_for(run_root)

    manager._auto_generate_full_candidates(devices)
    manager._auto_generate_full_candidates(devices)

    assert existing.read_bytes() == original
    assert [event["event"] for event in _diagnostic_events(run_root)][-2:] == [
        "AUTO_CANDIDATE_PREVIEW_SUCCEEDED",
        "AUTO_CANDIDATE_ALREADY_EXISTS",
    ]


def test_write_failure_is_persisted_without_changing_finished_batch(tmp_path, monkeypatch):
    run_root = _create_run(tmp_path)
    _set_no_target_candidate_count(run_root, 0)
    real_build = build_baseline_candidate

    def raise_on_write(run_root, *, write=True, integrate=True):
        if write:
            raise OSError("candidate destination is unavailable")
        return real_build(run_root, write=write, integrate=integrate)

    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(batch_runner, "build_baseline_candidate", raise_on_write)
    manager, devices = _manager_for(run_root)

    manager._auto_generate_full_candidates(devices)

    assert manager._state == "finished"
    event = _diagnostic_events(run_root)[-1]
    assert event["event"] == "AUTO_CANDIDATE_WRITE_FAILED"
    assert event["exception_type"] == "OSError"
    assert "destination is unavailable" in event["exception_message"]


def test_missing_written_file_is_persisted_as_write_failure(tmp_path, monkeypatch):
    run_root = _create_run(tmp_path)
    _set_no_target_candidate_count(run_root, 0)
    real_build = build_baseline_candidate

    def omit_write_path(run_root, *, write=True, integrate=True):
        result = real_build(run_root, write=False, integrate=integrate)
        if not write:
            return result
        return CandidateBuildResult(
            candidate=result.candidate,
            path=None,
            document_digest=result.document_digest,
            reference=result.reference,
        )

    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(batch_runner, "build_baseline_candidate", omit_write_path)
    manager, devices = _manager_for(run_root)

    manager._auto_generate_full_candidates(devices)

    event = _diagnostic_events(run_root)[-1]
    assert event["event"] == "AUTO_CANDIDATE_WRITE_FAILED"
    assert event["skip_reason"] == "candidate_file_missing_after_write"
    assert _candidate_paths(run_root) == []


def test_run_loop_invokes_auto_generation_only_after_batch_is_finished(monkeypatch):
    manager = batch_runner.BatchRunManager()
    manager._mode = "full"
    manager._state = "running"
    manager._devices = [{"state": "passed", "return_code": 0, "output_dir": "batch/device"}]
    manager._current_device_idx = 1
    observed = []
    monkeypatch.setattr(manager, "_auto_generate_full_candidates", lambda devices: observed.extend(devices))

    manager._run_loop()

    assert manager._state == "finished"
    assert observed == [{"state": "passed", "return_code": 0, "output_dir": "batch/device"}]
