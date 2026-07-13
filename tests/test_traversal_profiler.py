from __future__ import annotations

import json
import threading
from pathlib import Path

from tb_runner.traversal_profiler import (
    TraversalRuntimeProfiler,
    active_profiler,
    measure_runtime,
    profiler_scope,
    traversal_profiler_enabled,
)
from tb_runner import collection_flow


class _Clock:
    def __init__(self, *values: int) -> None:
        self._values = iter(values)

    def __call__(self) -> int:
        return next(self._values)


def test_profiler_default_off_and_no_artifact(tmp_path: Path) -> None:
    assert traversal_profiler_enabled({}) is False
    profiler = TraversalRuntimeProfiler("safe", tmp_path / "run.xlsx", enabled=False)
    with profiler.measure("traversal_loop"):
        pass
    assert profiler.finalize() is None
    assert not (tmp_path / "run.profiler").exists()


def test_profiler_writes_non_negative_duration_and_counts(tmp_path: Path) -> None:
    clock = _Clock(1_000_000, 2_000_000, 5_500_000, 8_000_000, 9_000_000)
    profiler = TraversalRuntimeProfiler("safe plugin", tmp_path / "run.xlsx", clock_ns=clock)
    with profiler_scope(profiler):
        assert active_profiler() is profiler
        with measure_runtime("candidate_discovery"):
            pass
        profiler.record("candidate_discovery", 2.5)
    artifact = profiler.finalize()
    assert artifact == tmp_path / "run.profiler" / "safe_plugin.profiler.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["runtime_ms"] >= 0
    assert payload["metrics"]["candidate_discovery"]["duration_ms"] >= 0
    assert payload["metrics"]["candidate_discovery"]["count"] == 2
    assert payload["metrics"]["candidate_discovery"]["end_ms"] >= payload["metrics"]["candidate_discovery"]["start_ms"]
    assert active_profiler() is None


def test_recovery_summary_is_append_only_and_thread_safe(tmp_path: Path) -> None:
    profiler = TraversalRuntimeProfiler("motion", tmp_path / "run.xlsx")

    def record(index: int) -> None:
        profiler.record("recovery_executor", float(index))
        profiler.record_recovery(attempt=index, result="recovered")

    threads = [threading.Thread(target=record, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    payload = profiler.payload()
    assert payload["metrics"]["recovery_executor"]["count"] == 8
    assert len(payload["recovery"]) == 8


def test_profiler_counters_are_additive_and_backward_compatible(tmp_path: Path) -> None:
    profiler = TraversalRuntimeProfiler("safe", tmp_path / "run.xlsx")
    profiler.increment_counter("verification_poll_attempts")
    profiler.increment_counter("verification_poll_attempts", 2)
    profiler.increment_counter("verification_fast_path_hits")
    payload = profiler.payload()
    assert payload["counters"]["verification_poll_attempts"] == 3
    assert payload["counters"]["verification_fast_path_hits"] == 1
    assert "metrics" in payload and "recovery" in payload


def test_feature_flag_truthy_values() -> None:
    for value in ("1", "true", "YES", "on"):
        assert traversal_profiler_enabled({"TB_TRAVERSAL_PROFILER_ENABLED": value}) is True
    assert traversal_profiler_enabled({"TB_TRAVERSAL_PROFILER_ENABLED": "0"}) is False


def test_collection_wrapper_preserves_result_off_and_writes_artifact_on(tmp_path, monkeypatch) -> None:
    expected = [{"step_index": 1}]
    monkeypatch.setattr(collection_flow, "_collect_tab_rows_impl", lambda *args, **kwargs: expected)
    args = (object(), "device", {"scenario_id": "safe", "scenario_type": "plugin"}, [])
    output = tmp_path / "run.xlsx"

    monkeypatch.delenv("TB_TRAVERSAL_PROFILER_ENABLED", raising=False)
    assert collection_flow.collect_tab_rows(*args, str(output), str(tmp_path / "run")) is expected
    assert not output.with_suffix(".profiler").exists()

    monkeypatch.setenv("TB_TRAVERSAL_PROFILER_ENABLED", "1")
    assert collection_flow.collect_tab_rows(*args, str(output), str(tmp_path / "run")) is expected
    artifact = output.with_suffix(".profiler") / "safe.profiler.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["metrics"]["scenario"]["count"] == 1
