from __future__ import annotations

import json
from typing import Any

from .paths import RUNTIME_CONFIG_PATH


def read_runtime_config() -> dict[str, Any]:
    with RUNTIME_CONFIG_PATH.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise ValueError("runtime_config root must be an object")
    return data


def list_scenarios() -> list[dict[str, Any]]:
    config = read_runtime_config()
    scenarios = config.get("scenarios", {})
    if not isinstance(scenarios, dict):
        return []

    result: list[dict[str, Any]] = []
    for scenario_id, raw in scenarios.items():
        cfg = raw if isinstance(raw, dict) else {}
        result.append(
            {
                "id": str(scenario_id),
                "enabled": bool(cfg.get("enabled", False)),
                "max_steps": cfg.get("max_steps"),
            }
        )
    return result
