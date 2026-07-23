from __future__ import annotations

import json

import pytest

from qa_frontend.backend import batch_runner
from qa_frontend.backend.comparator_ui import ComparatorUiService
from tb_runner.baseline_candidate_builder import build_baseline_candidate
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


def test_finished_full_run_creates_candidate_and_comparator_lists_it(tmp_path, monkeypatch):
    run_root = _create_run(tmp_path)
    _set_no_target_candidate_count(run_root, 0)
    monkeypatch.setattr(batch_runner, "ROOT_DIR", tmp_path)
    manager, devices = _manager_for(run_root)

    manager._auto_generate_full_candidates(devices)

    paths = _candidate_paths(run_root)
    assert len(paths) == 1
    candidates = ComparatorUiService(root_dir=tmp_path, run_log_dir=tmp_path).candidates()
    assert [item["candidate_id"] for item in candidates] == [paths[0].stem.removesuffix(".baseline_candidate")]


@pytest.mark.parametrize(
    ("mode", "state", "device_state", "return_code", "targeted", "no_target", "remove_artifact"),
    [
        ("smoke", "finished", "passed", 0, False, 0, False),
        ("full", "finished", "passed", 0, True, 0, False),
        ("full", "finished", "failed", 1, False, 0, False),
        ("full", "stopped", "passed", 0, False, 0, False),
        ("full", "finished", "passed", 0, False, 1, False),
        ("full", "finished", "passed", 0, False, 0, True),
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

    assert existing.read_bytes() == original


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
