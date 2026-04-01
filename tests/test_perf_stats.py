from tb_runner.perf_stats import RunPerfStats, ScenarioPerfStats


def test_avg_step_total_uses_only_positive_timing_samples():
    stats = ScenarioPerfStats(scenario_id="s1", tab_name="홈")

    stats.record_row(
        {
            "context_type": "main",
            "get_focus_elapsed_sec": 2.0,
            "step_total_elapsed_sec": 8.5,
        }
    )
    stats.record_row(
        {
            "context_type": "overlay",
            "get_focus_elapsed_sec": 1.0,
            # overlay row without total timing fields should not dilute avg_step_total
        }
    )

    summary = stats.summary_dict()

    assert summary["total_steps"] == 2
    assert summary["step_total_sample_count"] == 1
    assert summary["avg_step_total"] == 8.5


def test_success_false_top_level_dump_attempt_and_found_are_counted_separately():
    stats = ScenarioPerfStats(scenario_id="s1", tab_name="홈")

    stats.record_row(
        {
            "context_type": "main",
            "get_focus_fallback_used": False,
            "get_focus_success_false_top_level_dump_attempted": True,
            "get_focus_success_false_top_level_dump_found": True,
        }
    )
    stats.record_row(
        {
            "context_type": "main",
            "get_focus_fallback_used": True,
            "get_focus_success_false_top_level_dump_attempted": False,
            "get_focus_success_false_top_level_dump_found": False,
        }
    )

    summary = stats.summary_dict()

    assert summary["fallback_dump_count"] == 1
    assert summary["success_false_top_level_dump_attempt_count"] == 1
    assert summary["success_false_top_level_dump_found_count"] == 1


def test_avg_get_focus_main_and_overlay_are_reported_separately():
    stats = ScenarioPerfStats(scenario_id="s1", tab_name="홈")

    stats.record_row({"context_type": "main", "get_focus_elapsed_sec": 2.0, "step_total_elapsed_sec": 7.0})
    stats.record_row({"context_type": "main", "get_focus_elapsed_sec": 4.0, "step_total_elapsed_sec": 9.0})
    stats.record_row({"context_type": "overlay", "get_focus_elapsed_sec": 1.0})

    summary = stats.summary_dict()

    assert summary["avg_get_focus"] == round((2.0 + 4.0 + 1.0) / 3.0, 3)
    assert summary["avg_get_focus_main"] == 3.0
    assert summary["avg_get_focus_overlay"] == 1.0


def test_run_summary_aggregates_success_false_top_level_counts():
    run_stats = RunPerfStats()
    scenario = run_stats.start_scenario("s1", "홈")

    scenario.record_row(
        {
            "context_type": "main",
            "get_focus_success_false_top_level_dump_attempted": True,
            "get_focus_success_false_top_level_dump_found": True,
        }
    )

    summary = run_stats.summary_dict()

    assert summary["success_false_top_level_dump_attempt_count"] == 1
    assert summary["success_false_top_level_dump_found_count"] == 1
