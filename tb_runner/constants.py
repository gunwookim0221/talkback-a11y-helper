import os


DEV_SERIAL = "R3CX40QFDBP"
SCRIPT_VERSION = "1.7.97"
_raw_log_level = os.getenv("LOG_LEVEL", os.getenv("TB_LOG_LEVEL", "INFO")).upper()
LOG_LEVEL = "NORMAL" if _raw_log_level == "INFO" else _raw_log_level
LOG_LEVEL_ORDER = {"QUIET": 0, "INFO": 1, "NORMAL": 1, "DEBUG": 2}

OVERLAY_ENTRY_CANDIDATES = [
    {
        "resource_id": "com.samsung.android.oneconnect:id/add_menu_button",
        "label": "Add",
    },
    {
        "resource_id": "com.samsung.android.oneconnect:id/more_menu_button",
        "label": "More options",
    },
]
# Backward compatibility: legacy name kept as alias.
OVERLAY_ENTRY_ALLOWLIST = OVERLAY_ENTRY_CANDIDATES

OVERLAY_MAX_STEPS = 10
MAIN_STEP_WAIT_SECONDS = 1.2
MAIN_ANNOUNCEMENT_WAIT_SECONDS = 1.2
OVERLAY_STEP_WAIT_SECONDS = 0.8
OVERLAY_ANNOUNCEMENT_WAIT_SECONDS = 0.8
BACK_RECOVERY_WAIT_SECONDS = 0.8
CHECKPOINT_SAVE_EVERY_STEPS = 3
OVERLAY_REALIGN_MAX_STEPS = 8

ENABLE_IMAGE_CROP = True
ENABLE_IMAGE_INSERT_TO_EXCEL = True
IMAGE_DIR = "output/crops"
