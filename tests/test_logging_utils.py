import importlib

import tb_runner.constants as constants
import tb_runner.logging_utils as logging_utils


def _reload_logging_utils(monkeypatch, level: str | None):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("TB_LOG_LEVEL", raising=False)
    if level is not None:
        monkeypatch.setenv("LOG_LEVEL", level)
    importlib.reload(constants)
    importlib.reload(logging_utils)
    return logging_utils


def test_normal_level_writes_only_normal_file(tmp_path, monkeypatch, capsys):
    module = _reload_logging_utils(monkeypatch, "INFO")
    output_path = tmp_path / "talkback_compare_20260405_101010.xlsx"

    module.configure_log_files(str(output_path))
    module.log("normal line")
    module.log("debug line", level="DEBUG")
    module.close_log_files()

    captured = capsys.readouterr()
    assert "normal line" in captured.out
    assert "debug line" not in captured.out

    normal_path = tmp_path / "talkback_compare_20260405_101010.normal.log"
    debug_path = tmp_path / "talkback_compare_20260405_101010.debug.log"
    assert normal_path.exists()
    assert "normal line" in normal_path.read_text(encoding="utf-8")
    assert "debug line" not in normal_path.read_text(encoding="utf-8")
    assert not debug_path.exists()


def test_default_level_without_env_matches_info(tmp_path, monkeypatch, capsys):
    module = _reload_logging_utils(monkeypatch, None)
    output_path = tmp_path / "talkback_compare_20260405_121212.xlsx"

    module.configure_log_files(str(output_path))
    module.log("normal line")
    module.log("debug line", level="DEBUG")
    module.close_log_files()

    captured = capsys.readouterr()
    assert "normal line" in captured.out
    assert "debug line" not in captured.out


def test_debug_level_writes_normal_and_debug_files(tmp_path, monkeypatch, capsys):
    module = _reload_logging_utils(monkeypatch, "DEBUG")
    output_path = tmp_path / "talkback_compare_20260405_111111.xlsx"

    module.configure_log_files(str(output_path))
    module.log("normal line")
    module.log("debug line", level="DEBUG")
    module.close_log_files()

    captured = capsys.readouterr()
    assert "normal line" in captured.out
    assert "debug line" in captured.out

    normal_path = tmp_path / "talkback_compare_20260405_111111.normal.log"
    debug_path = tmp_path / "talkback_compare_20260405_111111.debug.log"
    normal_text = normal_path.read_text(encoding="utf-8")
    debug_text = debug_path.read_text(encoding="utf-8")

    assert "normal line" in normal_text
    assert "debug line" not in normal_text
    assert "normal line" in debug_text
    assert "debug line" in debug_text


def test_get_recent_logs_returns_latest_lines(monkeypatch):
    module = _reload_logging_utils(monkeypatch, "DEBUG")
    for idx in range(5):
        module.log(f"line-{idx}")

    recent = module.get_recent_logs(limit=3)

    assert len(recent) == 3
    assert "line-2" in recent[0]
    assert "line-4" in recent[-1]
