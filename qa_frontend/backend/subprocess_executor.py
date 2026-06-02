from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from tb_runner.run_spec import RunSpec


@dataclass
class RunExecution:
    process: subprocess.Popen[str]
    tee_thread: threading.Thread
    log_file: TextIO
    log_path: Path


def start_execution(
    *,
    spec: RunSpec,
    script_path: Path,
    cwd: Path,
    log_file: TextIO,
    log_path: Path,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> RunExecution:
    process = popen_factory(
        spec.build_script_command(script_path),
        cwd=cwd,
        env=spec.build_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    tee_thread = threading.Thread(target=_tee_output, args=(process, log_file), daemon=True)
    tee_thread.start()
    return RunExecution(process=process, tee_thread=tee_thread, log_file=log_file, log_path=log_path)


def wait_for_execution(execution: RunExecution, *, join_timeout: float = 5.0) -> int:
    returncode = execution.process.wait()
    execution.tee_thread.join(timeout=join_timeout)
    if execution.tee_thread.is_alive():
        execution.log_file.write("\n[RUNNER WARNING] tee_thread join timeout\n")
    execution.log_file.flush()
    return returncode


def close_execution_log(execution: RunExecution) -> None:
    try:
        execution.log_file.flush()
    finally:
        execution.log_file.close()


def _tee_output(process: subprocess.Popen[str], log_file: TextIO) -> None:
    try:
        if process.stdout:
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
    except Exception as exc:
        log_file.write(f"\n[TEE ERROR] {exc}\n")
        log_file.flush()

