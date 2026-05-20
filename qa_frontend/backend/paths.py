from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
RUNTIME_CONFIG_PATH = CONFIG_DIR / "runtime_config.json"
OUTPUT_DIR = ROOT_DIR / "output"
RUN_LOG_DIR = ROOT_DIR / "qa_frontend_runs"
SCRIPT_PATH = ROOT_DIR / "script_test.py"
