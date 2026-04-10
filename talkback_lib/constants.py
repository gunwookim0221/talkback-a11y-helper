"""talkback_lib 상수 정의 (1단계 기초 분리)."""

from __future__ import annotations

import os
import re

ACTION_DUMP_TREE = "com.iotpart.sqe.talkbackhelper.DUMP_TREE"
ACTION_GET_FOCUS = "com.iotpart.sqe.talkbackhelper.GET_FOCUS"
ACTION_FOCUS_TARGET = "com.iotpart.sqe.talkbackhelper.FOCUS_TARGET"
ACTION_CLICK_TARGET = "com.iotpart.sqe.talkbackhelper.CLICK_TARGET"
ACTION_TOUCH_BOUNDS_CENTER_TARGET = "com.iotpart.sqe.talkbackhelper.TOUCH_BOUNDS_CENTER_TARGET"
ACTION_CHECK_TARGET = "com.iotpart.sqe.talkbackhelper.CHECK_TARGET"
ACTION_NEXT = "com.iotpart.sqe.talkbackhelper.NEXT"
ACTION_PREV = "com.iotpart.sqe.talkbackhelper.PREV"
ACTION_SMART_NEXT = "com.iotpart.sqe.talkbackhelper.SMART_NEXT"
ACTION_CLICK_FOCUSED = "com.iotpart.sqe.talkbackhelper.CLICK_FOCUSED"
ACTION_SCROLL = "com.iotpart.sqe.talkbackhelper.SCROLL"
ACTION_SET_TEXT = "com.iotpart.sqe.talkbackhelper.SET_TEXT"
ACTION_PING = "com.iotpart.sqe.talkbackhelper.PING"
ACTION_COMMAND = "com.iotpart.sqe.talkbackhelper.ACTION_COMMAND"

LOG_TAG = "A11Y_HELPER"
LOGCAT_FILTER_SPECS = ["A11Y_HELPER:V", "A11Y_ANNOUNCEMENT:V", "*:S"]
LOGCAT_TIME_PATTERN = re.compile(r"^(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})")

RED_TEXT = "\033[91m"
RESET_TEXT = "\033[0m"

CLIENT_ALGORITHM_VERSION = "1.7.69"

DEFAULT_PACKAGE_NAME = "com.iotpart.sqe.talkbackhelper"
DEFAULT_ADB_PATH = "adb"
DEFAULT_TIMEOUT_SECONDS = 30.0

STATUS_MOVED = "moved"
STATUS_FAILED = "failed"
STATUS_SCROLLED = "scrolled"
STATUS_LOOPED = "looped"

LOG_LEVEL = os.getenv("TB_LOG_LEVEL", "NORMAL").upper()
LOG_LEVEL_ORDER = {"QUIET": 0, "NORMAL": 1, "DEBUG": 2}
