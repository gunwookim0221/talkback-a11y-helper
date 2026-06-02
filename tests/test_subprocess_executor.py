from __future__ import annotations

from io import StringIO
from pathlib import Path

from qa_frontend.backend.subprocess_executor import start_execution, wait_for_execution
from tb_runner.run_spec import RunSpec


class _Stdout:
    def __iter__(self):
        return iter(["line one\n", "line two\n"])


class _Process:
    stdout = _Stdout()

    def wait(self):
        return 7


def test_executor_waits_joins_and_flushes_before_return(tmp_path):
    captured = {}

    def popen_factory(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return _Process()

    log_file = StringIO()
    execution = start_execution(
        spec=RunSpec(serial="SERIAL", output_dir=str(tmp_path)),
        script_path=Path("script_test.py"),
        cwd=tmp_path,
        log_file=log_file,
        log_path=tmp_path / "runner.log",
        popen_factory=popen_factory,
    )

    assert wait_for_execution(execution) == 7
    assert execution.tee_thread.is_alive() is False
    assert log_file.getvalue() == "line one\nline two\n"
    assert "--serial" in captured["command"]
    assert captured["env"]["ANDROID_SERIAL"] == "SERIAL"

