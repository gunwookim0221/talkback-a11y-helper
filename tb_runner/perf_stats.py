from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any



def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class ScenarioPerfStats:
    scenario_id: str
    tab_name: str
    started_at: float = field(default_factory=time.perf_counter)
    total_runtime_sec: float = 0.0
    total_steps: int = 0
    main_step_count: int = 0
    overlay_step_count: int = 0
    overlay_count: int = 0
    save_excel_count: int = 0
    fallback_dump_count: int = 0
    strong_skip_count: int = 0
    step_dump_used_count: int = 0
    realign_attempt_count: int = 0
    realign_success_count: int = 0

    _sum_get_focus_sec: float = 0.0
    _sum_move_sec: float = 0.0
    _sum_crop_sec: float = 0.0
    _sum_step_total_sec: float = 0.0

    def record_row(self, row: dict[str, Any]) -> None:
        self.total_steps += 1
        context_type = str(row.get("context_type", "") or "").strip().lower()
        if context_type == "overlay":
            self.overlay_step_count += 1
        else:
            self.main_step_count += 1

        self._sum_get_focus_sec += _safe_float(row.get("get_focus_elapsed_sec", 0.0))
        self._sum_move_sec += _safe_float(row.get("move_elapsed_sec", 0.0))
        self._sum_crop_sec += _safe_float(row.get("crop_elapsed_sec", 0.0))
        self._sum_step_total_sec += _safe_float(row.get("step_total_elapsed_sec", row.get("step_elapsed_sec", 0.0)))

        if bool(row.get("get_focus_fallback_used", False)):
            self.fallback_dump_count += 1
        if bool(row.get("get_focus_success_false_top_level_dump_skipped", False)):
            self.strong_skip_count += 1
        if bool(row.get("step_dump_tree_used", False)):
            self.step_dump_used_count += 1

    def finalize(self) -> None:
        self.total_runtime_sec = max(0.0, time.perf_counter() - self.started_at)

    def summary_dict(self) -> dict[str, Any]:
        total_steps = max(self.total_steps, 1)
        realign_attempt_count = max(self.realign_attempt_count, 1)
        return {
            "scenario": self.scenario_id,
            "tab": self.tab_name,
            "total_runtime": round(self.total_runtime_sec, 1),
            "total_steps": self.total_steps,
            "main_step_count": self.main_step_count,
            "overlay_step_count": self.overlay_step_count,
            "overlay_count": self.overlay_count,
            "avg_get_focus": round(self._sum_get_focus_sec / total_steps, 3),
            "avg_move": round(self._sum_move_sec / total_steps, 3),
            "avg_crop": round(self._sum_crop_sec / total_steps, 3),
            "avg_step_total": round(self._sum_step_total_sec / total_steps, 3),
            "fallback_dump_count": self.fallback_dump_count,
            "fallback_dump_rate": round((self.fallback_dump_count / total_steps) * 100.0, 1),
            "get_focus_strong_skip_count": self.strong_skip_count,
            "get_focus_strong_skip_rate": round((self.strong_skip_count / total_steps) * 100.0, 1),
            "step_dump_used_count": self.step_dump_used_count,
            "save_excel_count": self.save_excel_count,
            "realign_attempt_count": self.realign_attempt_count,
            "realign_success_count": self.realign_success_count,
            "realign_success_rate": round((self.realign_success_count / realign_attempt_count) * 100.0, 1),
        }


@dataclass
class RunPerfStats:
    started_at: float = field(default_factory=time.perf_counter)
    scenarios: list[ScenarioPerfStats] = field(default_factory=list)
    extra_save_excel_count: int = 0

    def start_scenario(self, scenario_id: str, tab_name: str) -> ScenarioPerfStats:
        scenario = ScenarioPerfStats(scenario_id=scenario_id, tab_name=tab_name)
        self.scenarios.append(scenario)
        return scenario

    def summary_dict(self) -> dict[str, Any]:
        total_runtime_sec = max(0.0, time.perf_counter() - self.started_at)
        total_steps = sum(s.total_steps for s in self.scenarios)
        sum_get_focus = sum(s._sum_get_focus_sec for s in self.scenarios)
        sum_move = sum(s._sum_move_sec for s in self.scenarios)
        total_overlay_count = sum(s.overlay_count for s in self.scenarios)
        fallback_dump_count = sum(s.fallback_dump_count for s in self.scenarios)
        strong_skip_count = sum(s.strong_skip_count for s in self.scenarios)
        realign_attempt_count = sum(s.realign_attempt_count for s in self.scenarios)
        realign_success_count = sum(s.realign_success_count for s in self.scenarios)
        save_excel_count = sum(s.save_excel_count for s in self.scenarios) + self.extra_save_excel_count

        denominator_steps = max(total_steps, 1)
        denominator_realign = max(realign_attempt_count, 1)
        return {
            "total_runtime": round(total_runtime_sec, 1),
            "total_scenarios": len(self.scenarios),
            "total_steps": total_steps,
            "total_overlay_count": total_overlay_count,
            "avg_get_focus": round(sum_get_focus / denominator_steps, 3),
            "avg_move": round(sum_move / denominator_steps, 3),
            "fallback_dump_count": fallback_dump_count,
            "fallback_dump_rate": round((fallback_dump_count / denominator_steps) * 100.0, 1),
            "get_focus_strong_skip_rate": round((strong_skip_count / denominator_steps) * 100.0, 1),
            "realign_success_rate": round((realign_success_count / denominator_realign) * 100.0, 1),
            "save_excel_count": save_excel_count,
        }

    def record_save_excel(self) -> None:
        self.extra_save_excel_count += 1


def format_perf_summary(prefix: str, summary: dict[str, Any]) -> str:
    ordered_items = [f"{key}={value}" for key, value in summary.items()]
    return f"[PERF][{prefix}] " + " ".join(ordered_items)


def save_excel_with_perf(
    save_excel_func,
    rows: list[dict[str, Any]],
    output_path: str,
    with_images: bool,
    scenario_perf: ScenarioPerfStats | None = None,
) -> None:
    if scenario_perf is not None:
        scenario_perf.save_excel_count += 1
    save_excel_func(rows, output_path, with_images=with_images)
