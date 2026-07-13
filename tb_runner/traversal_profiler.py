"""Opt-in, observation-only runtime profiling for traversal scenarios."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from functools import wraps
from typing import Any, Callable, Iterator, Mapping, TypeVar


TRAVERSAL_PROFILER_ENABLED_ENV = "TB_TRAVERSAL_PROFILER_ENABLED"
PROFILER_SCHEMA_VERSION = "traversal-profiler-v1"
_TRUTHY = {"1", "true", "yes", "on"}
_T = TypeVar("_T")


def traversal_profiler_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return str(source.get(TRAVERSAL_PROFILER_ENABLED_ENV, "") or "").strip().lower() in _TRUTHY


@dataclass
class _Metric:
    duration_ms: float = 0.0
    count: int = 0
    start_ms: float | None = None
    end_ms: float | None = None

    def add(self, duration_ms: float, count: int = 1, *, start_ms: float, end_ms: float) -> None:
        self.duration_ms += max(0.0, float(duration_ms))
        self.count += max(0, int(count))
        self.start_ms = start_ms if self.start_ms is None else min(self.start_ms, start_ms)
        self.end_ms = end_ms if self.end_ms is None else max(self.end_ms, end_ms)


@dataclass
class TraversalRuntimeProfiler:
    scenario: str
    output_path: str | Path
    plugin: str = ""
    enabled: bool = True
    clock_ns: Any = time.perf_counter_ns
    _started_ns: int = field(init=False, default=0)
    _ended_ns: int = field(init=False, default=0)
    _metrics: dict[str, _Metric] = field(init=False, default_factory=dict)
    _recovery: list[dict[str, Any]] = field(init=False, default_factory=list)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.enabled:
            self._started_ns = int(self.clock_ns())

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started = int(self.clock_ns())
        try:
            yield
        finally:
            ended = int(self.clock_ns())
            self.record(
                name,
                (ended - started) / 1_000_000.0,
                started_ns=started,
                ended_ns=ended,
            )

    def record(
        self,
        name: str,
        duration_ms: float,
        *,
        count: int = 1,
        started_ns: int | None = None,
        ended_ns: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        end_ns = int(self.clock_ns()) if ended_ns is None else int(ended_ns)
        start_ns = end_ns - int(max(0.0, float(duration_ms)) * 1_000_000.0) if started_ns is None else int(started_ns)
        start_ms = max(0.0, (start_ns - self._started_ns) / 1_000_000.0)
        end_ms = max(start_ms, (end_ns - self._started_ns) / 1_000_000.0)
        with self._lock:
            self._metrics.setdefault(str(name), _Metric()).add(
                duration_ms,
                count,
                start_ms=start_ms,
                end_ms=end_ms,
            )

    def record_recovery(self, **values: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._recovery.append(dict(values))

    @property
    def artifact_path(self) -> Path:
        output = Path(self.output_path)
        safe_scenario = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.scenario).strip("_") or "scenario"
        return output.with_suffix(".profiler") / f"{safe_scenario}.profiler.json"

    def payload(self) -> dict[str, Any]:
        ended_ns = self._ended_ns or (int(self.clock_ns()) if self.enabled else 0)
        runtime_ms = max(0.0, (ended_ns - self._started_ns) / 1_000_000.0) if self.enabled else 0.0
        with self._lock:
            metrics = {
                name: {
                    "start_ms": round(metric.start_ms or 0.0, 3),
                    "end_ms": round(metric.end_ms or 0.0, 3),
                    "duration_ms": round(metric.duration_ms, 3),
                    "count": metric.count,
                }
                for name, metric in sorted(self._metrics.items())
            }
            recovery = [dict(item) for item in self._recovery]
        return {
            "schema_version": PROFILER_SCHEMA_VERSION,
            "scenario": self.scenario,
            "plugin": self.plugin,
            "runtime_ms": round(runtime_ms, 3),
            "metrics": metrics,
            "recovery": recovery,
        }

    def finalize(self) -> Path | None:
        if not self.enabled:
            return None
        self._ended_ns = int(self.clock_ns())
        target = self.artifact_path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(self.payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        return target


_ACTIVE_PROFILER: ContextVar[TraversalRuntimeProfiler | None] = ContextVar(
    "traversal_runtime_profiler", default=None
)


def active_profiler() -> TraversalRuntimeProfiler | None:
    profiler = _ACTIVE_PROFILER.get()
    return profiler if profiler is not None and profiler.enabled else None


@contextmanager
def profiler_scope(profiler: TraversalRuntimeProfiler | None) -> Iterator[None]:
    token = _ACTIVE_PROFILER.set(profiler)
    try:
        yield
    finally:
        _ACTIVE_PROFILER.reset(token)


@contextmanager
def measure_runtime(name: str) -> Iterator[None]:
    profiler = active_profiler()
    if profiler is None:
        yield
        return
    with profiler.measure(name):
        yield


def profiled(name: str) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    """Measure an existing boundary without changing its arguments or result."""
    def decorate(function: Callable[..., _T]) -> Callable[..., _T]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> _T:
            with measure_runtime(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


__all__ = [
    "PROFILER_SCHEMA_VERSION",
    "TRAVERSAL_PROFILER_ENABLED_ENV",
    "TraversalRuntimeProfiler",
    "active_profiler",
    "measure_runtime",
    "profiler_scope",
    "profiled",
    "traversal_profiler_enabled",
]
