import time
from pathlib import Path
from typing import TextIO

from tb_runner.constants import LOG_LEVEL, LOG_LEVEL_ORDER

_normal_log_file: TextIO | None = None
_debug_log_file: TextIO | None = None


def now_str() -> str:
    return time.strftime("%H:%M:%S")


def _should_log(level: str = "NORMAL") -> bool:
    current = LOG_LEVEL if LOG_LEVEL in LOG_LEVEL_ORDER else "NORMAL"
    return LOG_LEVEL_ORDER.get(current, 1) >= LOG_LEVEL_ORDER.get(level, 1)


def _safe_close(file_obj: TextIO | None) -> None:
    if file_obj is None:
        return
    try:
        file_obj.flush()
        file_obj.close()
    except Exception:
        pass


def configure_log_files(output_path: str) -> None:
    global _normal_log_file, _debug_log_file
    close_log_files()

    if not output_path:
        return

    try:
        base_path = Path(output_path)
        base_prefix = base_path.with_suffix("")
        base_prefix.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    current = LOG_LEVEL if LOG_LEVEL in LOG_LEVEL_ORDER else "NORMAL"
    try:
        _normal_log_file = open(f"{base_prefix}.normal.log", "a", encoding="utf-8")
    except Exception:
        _normal_log_file = None
    if current == "DEBUG":
        try:
            _debug_log_file = open(f"{base_prefix}.debug.log", "a", encoding="utf-8")
        except Exception:
            _debug_log_file = None


def close_log_files() -> None:
    global _normal_log_file, _debug_log_file
    _safe_close(_normal_log_file)
    _safe_close(_debug_log_file)
    _normal_log_file = None
    _debug_log_file = None


def log(msg: str, level: str = "NORMAL") -> None:
    global _normal_log_file, _debug_log_file
    if _should_log(level):
        line = f"[{now_str()}] {msg}"
        print(line)
        if _normal_log_file is not None and LOG_LEVEL_ORDER.get(level, 1) <= LOG_LEVEL_ORDER["NORMAL"]:
            try:
                _normal_log_file.write(f"{line}\n")
                _normal_log_file.flush()
            except Exception:
                _safe_close(_normal_log_file)
                _normal_log_file = None
        if _debug_log_file is not None:
            try:
                _debug_log_file.write(f"{line}\n")
                _debug_log_file.flush()
            except Exception:
                _safe_close(_debug_log_file)
                _debug_log_file = None
