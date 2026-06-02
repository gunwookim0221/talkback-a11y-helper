from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Callable, Iterator

from tb_runner.run_spec import RunSpec

from .device_locale import apply_language_mode
from .preflight import run_surface_preflight


def prepare_runtime(
    spec: RunSpec,
    *,
    language_fn: Callable[[str], dict[str, object]] = apply_language_mode,
    preflight_fn: Callable[[str], dict[str, object]] = run_surface_preflight,
) -> tuple[dict[str, object], dict[str, object] | None]:
    with _android_serial(spec.serial):
        language_status = language_fn(spec.language_mode)
        if not language_status.get("ok"):
            return language_status, None
        return language_status, preflight_fn(spec.launch_mode)


@contextmanager
def _android_serial(serial: str | None) -> Iterator[None]:
    previous = os.environ.get("ANDROID_SERIAL")
    try:
        if serial:
            os.environ["ANDROID_SERIAL"] = serial
        elif "ANDROID_SERIAL" in os.environ:
            del os.environ["ANDROID_SERIAL"]
        yield
    finally:
        if previous is None:
            os.environ.pop("ANDROID_SERIAL", None)
        else:
            os.environ["ANDROID_SERIAL"] = previous
