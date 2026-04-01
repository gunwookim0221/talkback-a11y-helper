import time

from tb_runner.constants import LOG_LEVEL, LOG_LEVEL_ORDER


def now_str() -> str:
    return time.strftime("%H:%M:%S")


def _should_log(level: str = "NORMAL") -> bool:
    current = LOG_LEVEL if LOG_LEVEL in LOG_LEVEL_ORDER else "NORMAL"
    return LOG_LEVEL_ORDER.get(current, 1) >= LOG_LEVEL_ORDER.get(level, 1)


def log(msg: str, level: str = "NORMAL") -> None:
    if _should_log(level):
        print(f"[{now_str()}] {msg}")
