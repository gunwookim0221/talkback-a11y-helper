from tb_runner.diagnostics import classify_step_result, detect_step_mismatch, should_stop


def test_detect_step_mismatch_returns_speech_visible_diverged():
    row = {
        "normalized_visible_label": "wifi",
        "normalized_announcement": "bluetooth",
    }

    mismatch, low = detect_step_mismatch(row)

    assert "speech_visible_diverged" in mismatch
    assert low == []


def test_detect_step_mismatch_skips_speech_mismatch_when_smart_nav_is_primary_verdict():
    row = {
        "normalized_visible_label": "devices",
        "normalized_announcement": "grid view",
        "post_move_verdict_source": "smart_nav_result_resource_match",
    }

    mismatch, _ = detect_step_mismatch(row)

    assert "speech_visible_diverged" not in mismatch


def test_detect_step_mismatch_returns_speech_bounds_diverged():
    previous = {
        "normalized_announcement": "same speech",
        "focus_bounds": "0,0,10,10",
    }
    row = {
        "normalized_visible_label": "same speech",
        "normalized_announcement": "same speech",
        "focus_bounds": "300,300,320,320",
    }

    mismatch, _ = detect_step_mismatch(row, previous_step=previous)

    assert "speech_bounds_diverged" in mismatch


def test_detect_step_mismatch_skips_low_confidence_under_strong_top_level_policy():
    row = {
        "focus_payload_source": "top_level",
        "get_focus_response_success": False,
        "get_focus_success_false_top_level_dump_skipped": True,
        "get_focus_dump_skip_reason": "strong_top_level_payload",
        "crop_focus_confidence_low": True,
        "get_focus_fallback_found": False,
        "get_focus_success_false_top_level_dump_found": False,
    }

    _, low = detect_step_mismatch(row)

    assert "crop_low_confidence" not in low
    assert "top_level_without_fallback_dump" not in low
    assert "get_focus_top_level_success_false" not in low


def test_detect_step_mismatch_returns_overlay_bounds_only_focus_low_confidence():
    row = {
        "context_type": "overlay",
        "focus_view_id": "",
        "focus_bounds": "1,1,2,2",
    }

    _, low = detect_step_mismatch(row)

    assert "overlay_bounds_only_focus" in low


def test_detect_step_mismatch_returns_bounds_dependent_focus_low_confidence():
    row = {
        "focus_view_id": "",
        "focus_bounds": "1,1,2,2",
    }

    _, low = detect_step_mismatch(row)

    assert "bounds_dependent_focus" in low


def test_detect_step_mismatch_relaxes_low_confidence_when_top_level_payload_sufficient():
    row = {
        "focus_payload_source": "top_level",
        "get_focus_response_success": False,
        "get_focus_top_level_success_false": True,
        "get_focus_top_level_payload_sufficient": True,
        "focus_node": {"className": "android.widget.Button"},
        "normalized_visible_label": "map view",
        "focus_view_id": "",
        "focus_bounds": "10,10,100,100",
        "get_focus_fallback_found": False,
        "get_focus_success_false_top_level_dump_found": False,
    }

    _, low = detect_step_mismatch(row)

    assert "get_focus_top_level_success_false" not in low
    assert "top_level_without_fallback_dump" not in low
    assert "bounds_dependent_focus" not in low


def test_should_stop_when_smart_nav_terminal():
    stop, fail_count, same_count, reason, _, details = should_stop(
        row={"last_smart_nav_terminal": True, "visible_label": "a", "merged_announcement": "a"},
        prev_fingerprint=("", "", ""),
        fail_count=0,
        same_count=0,
        previous_row=None,
    )

    assert stop is True
    assert fail_count == 0
    assert same_count == 0
    assert reason == "smart_nav_terminal"
    assert details["terminal"] is True


def test_should_stop_when_repeat_and_no_progress():
    previous = {
        "normalized_visible_label": "label",
        "normalized_announcement": "label",
        "focus_view_id": "id",
        "focus_bounds": "0,0,1,1",
    }
    row = {
        "move_result": "failed",
        "last_smart_nav_result": "failed",
        "visible_label": "a",
        "merged_announcement": "a",
        "normalized_visible_label": "label",
        "normalized_announcement": "label",
        "focus_view_id": "id",
        "focus_bounds": "0,0,1,1",
    }

    stop, fail_count, same_count, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("label", "id", "0,0,1,1"),
        fail_count=1,
        same_count=1,
        previous_row=previous,
    )

    assert stop is True
    assert fail_count == 2
    assert same_count == 2
    assert reason == "repeat_no_progress"
    assert details["no_progress"] is True


def test_should_stop_does_not_treat_successful_move_dict_as_move_failed():
    row = {
        "move_result": {"success": True, "status": "moved", "detail": "moved"},
        "last_smart_nav_result": "moved",
        "smart_nav_success": True,
        "normalized_visible_label": "devices",
        "normalized_announcement": "devices",
        "focus_view_id": "com.samsung.android.oneconnect:id/menu_devices",
        "focus_bounds": "0,0,1,1",
    }

    stop, fail_count, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("", "", ""),
        fail_count=0,
        same_count=0,
        previous_row=None,
        scenario_type="global_nav",
        stop_policy={"stop_on_repeat_no_progress": True},
    )

    assert stop is False
    assert fail_count == 0
    assert reason == ""
    assert details["reason"] == ""


def test_should_stop_empty_only_is_not_immediate_stop():
    stop, _, _, reason, _, details = should_stop(
        row={"move_result": "moved", "visible_label": "", "merged_announcement": ""},
        prev_fingerprint=("", "", ""),
        fail_count=0,
        same_count=0,
        previous_row=None,
    )

    assert stop is False
    assert reason == ""
    assert details["reason"] == ""


def test_should_stop_repeat_semantic_stall_when_moved_but_same_semantic_target_repeats():
    previous = {
        "normalized_visible_label": "update app",
        "normalized_announcement": "update app",
        "focus_view_id": "com.samsung.android.oneconnect:id/update_app_title",
        "focus_bounds": "507,441",
    }
    row = {
        "move_result": "moved",
        "last_smart_nav_result": "moved",
        "visible_label": "Update app",
        "merged_announcement": "Update app",
        "normalized_visible_label": "update app",
        "normalized_announcement": "update app",
        "focus_view_id": "com.samsung.android.oneconnect:id/update_app_title",
        "focus_bounds": "507,441",
        "is_recent_duplicate_step": True,
        "is_recent_semantic_duplicate_step": True,
        "recent_semantic_unique_count": 1,
    }

    stop, fail_count, same_count, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=(
            "update app",
            "com.samsung.android.oneconnect:id/update_app_title",
            "507,441",
        ),
        fail_count=0,
        same_count=7,
        previous_row=previous,
    )

    assert stop is True
    assert fail_count == 0
    assert same_count == 8
    assert reason == "repeat_semantic_stall"
    assert details["repeat_stop_hit"] is True


def test_classify_step_result_marks_scrolled_with_payload_as_pass():
    row = {
        "move_result": "scrolled",
        "visible_label": "Labs",
        "merged_announcement": "Labs",
        "focus_view_id": "id/labs",
        "focus_bounds": "[0,0][100,100]",
    }

    summary = classify_step_result(
        row,
        mismatch_reasons=[],
        no_progress=False,
        stop_reason="",
        terminal_signal=False,
    )

    assert summary["traversal_result"] == "PASS_SCROLLED"
    assert summary["final_result"] == "PASS"
    assert summary["failure_reason"] == ""


def test_should_stop_content_global_nav_entry():
    previous = {
        "visible_label": "Device card",
        "normalized_visible_label": "device card",
        "merged_announcement": "device card",
        "focus_view_id": "id/device_card",
    }
    row = {
        "visible_label": "Devices",
        "normalized_visible_label": "devices",
        "merged_announcement": "selected devices",
        "focus_view_id": "com.samsung.android.oneconnect:id/menu_devices",
        "selected": True,
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("device card", "id/device_card", "0,0,10,10"),
        fail_count=0,
        same_count=0,
        previous_row=previous,
        scenario_type="content",
        stop_policy={"stop_on_global_nav_entry": True},
        scenario_cfg={
            "global_nav": {
                "labels": ["Home", "Devices", "Life", "Routines", "Menu"],
                "resource_ids": ["com.samsung.android.oneconnect:id/menu_devices"],
                "selected_pattern": "(?i).*selected.*",
                "region_hint": "auto",
            }
        },
    )

    assert stop is True
    assert reason == "global_nav_entry"
    assert details["is_global_nav"] is True


def test_should_stop_global_nav_exit():
    previous = {
        "visible_label": "Devices",
        "normalized_visible_label": "devices",
        "merged_announcement": "selected devices",
        "focus_view_id": "com.samsung.android.oneconnect:id/menu_devices",
        "selected": True,
    }
    row = {
        "visible_label": "Air conditioner",
        "normalized_visible_label": "air conditioner",
        "merged_announcement": "air conditioner",
        "focus_view_id": "id/device_card",
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("devices", "com.samsung.android.oneconnect:id/menu_devices", "0,0,10,10"),
        fail_count=0,
        same_count=0,
        previous_row=previous,
        scenario_type="global_nav",
        stop_policy={"stop_on_global_nav_exit": True},
        scenario_cfg={
            "global_nav": {
                "labels": ["Home", "Devices", "Life", "Routines", "Menu"],
                "resource_ids": ["com.samsung.android.oneconnect:id/menu_devices"],
                "selected_pattern": "(?i).*selected.*",
                "region_hint": "auto",
            }
        },
    )

    assert stop is True
    assert reason == "global_nav_exit"
    assert details["is_global_nav"] is False


def test_should_stop_global_nav_end_when_failed_repeat_no_progress():
    previous = {
        "visible_label": "Menu",
        "normalized_visible_label": "menu",
        "normalized_announcement": "menu selected",
        "focus_view_id": "com.samsung.android.oneconnect:id/menu_more",
        "focus_bounds": "0,0,10,10",
        "selected": True,
    }
    row = {
        "move_result": "failed",
        "last_smart_nav_result": "failed",
        "visible_label": "Menu",
        "normalized_visible_label": "menu",
        "normalized_announcement": "menu selected",
        "merged_announcement": "menu selected",
        "focus_view_id": "com.samsung.android.oneconnect:id/menu_more",
        "focus_bounds": "0,0,10,10",
        "selected": True,
    }

    stop, fail_count, same_count, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("menu", "com.samsung.android.oneconnect:id/menu_more", "0,0,10,10"),
        fail_count=1,
        same_count=1,
        previous_row=previous,
        scenario_type="global_nav",
        stop_policy={"stop_on_repeat_no_progress": True},
        scenario_cfg={
            "global_nav": {
                "labels": ["Home", "Devices", "Life", "Routines", "Menu"],
                "resource_ids": ["com.samsung.android.oneconnect:id/menu_more"],
                "selected_pattern": "(?i).*selected.*",
                "region_hint": "auto",
            }
        },
    )

    assert stop is True
    assert fail_count == 2
    assert same_count == 2
    assert reason == "global_nav_end"
    assert details["no_progress"] is True
    assert details["recent_repeat"] is True


def test_should_not_stop_realign_semantic_repeat_during_grace_window():
    previous = {
        "normalized_visible_label": "more options",
        "normalized_announcement": "more options",
        "focus_view_id": "id/more",
        "focus_bounds": "0,0,1,1",
    }
    row = {
        "move_result": "failed",
        "last_smart_nav_result": "failed",
        "visible_label": "More options",
        "merged_announcement": "More options",
        "normalized_visible_label": "more options",
        "normalized_announcement": "more options",
        "focus_view_id": "id/more",
        "focus_bounds": "0,0,2,2",
        "overlay_recovery_status": "after_realign",
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("more options", "id/more", "0,0,1,1"),
        fail_count=1,
        same_count=1,
        previous_row=previous,
        scenario_type="content",
        stop_policy={"stop_on_repeat_no_progress": True},
    )

    assert stop is False
    assert reason == ""
    assert details["after_realign"] is True
    assert details["overlay_realign_grace_active"] is True
    assert details["realign_grace_suppressed"] is False


def test_should_not_stop_only_because_after_realign_marker():
    previous = {
        "normalized_visible_label": "our home",
        "normalized_announcement": "our home",
        "focus_view_id": "id/home",
        "focus_bounds": "0,0,1,1",
    }
    row = {
        "move_result": "moved",
        "last_smart_nav_result": "moved",
        "visible_label": "Add",
        "merged_announcement": "Add",
        "normalized_visible_label": "add",
        "normalized_announcement": "add",
        "focus_view_id": "id/add",
        "focus_bounds": "0,0,2,2",
        "overlay_recovery_status": "after_realign",
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("our home", "id/home", "0,0,1,1"),
        fail_count=0,
        same_count=0,
        previous_row=previous,
        scenario_type="content",
    )

    assert stop is False
    assert reason == ""
    assert details["after_realign"] is True


def test_should_stop_bounded_two_card_loop_from_recent_semantic_duplicate():
    previous = {
        "normalized_visible_label": "is your family sensitive to air quality",
        "normalized_announcement": "is your family sensitive to air quality",
        "focus_view_id": "id/card_prompt",
        "focus_bounds": "0,1000,1080,1200",
    }
    row = {
        "move_result": "moved",
        "last_smart_nav_result": "moved",
        "visible_label": "Set the perfect temperature and humidity",
        "merged_announcement": "Set the perfect temperature and humidity",
        "normalized_visible_label": "set the perfect temperature and humidity",
        "normalized_announcement": "set the perfect temperature and humidity",
        "focus_view_id": "id/card_prompt",
        "focus_bounds": "0,1200,1080,1400",
        "is_recent_semantic_duplicate_step": True,
        "recent_semantic_duplicate_distance": 2,
        "recent_semantic_unique_count": 2,
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("is your family sensitive to air quality", "id/card_prompt", "0,1000,1080,1200"),
        fail_count=0,
        same_count=0,
        previous_row=previous,
        scenario_type="content",
        stop_policy={"stop_on_repeat_no_progress": True},
    )

    assert stop is True
    assert reason == "bounded_two_card_loop"
    assert details["recent_repeat"] is True
    assert details["bounded_two_card_loop"] is True
    assert details["no_progress"] is True


def test_should_not_stop_when_semantic_duplicate_window_is_wide():
    previous = {
        "normalized_visible_label": "card a",
        "normalized_announcement": "card a",
        "focus_view_id": "id/card_a",
        "focus_bounds": "0,100,100,200",
    }
    row = {
        "move_result": "moved",
        "last_smart_nav_result": "moved",
        "visible_label": "Card D",
        "merged_announcement": "Card D",
        "normalized_visible_label": "card d",
        "normalized_announcement": "card d",
        "focus_view_id": "id/card_d",
        "focus_bounds": "0,400,100,500",
        "is_recent_semantic_duplicate_step": True,
        "recent_semantic_duplicate_distance": 2,
        "recent_semantic_unique_count": 4,
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("card a", "id/card_a", "0,100,100,200"),
        fail_count=0,
        same_count=0,
        previous_row=previous,
        scenario_type="content",
        stop_policy={"stop_on_repeat_no_progress": True},
    )

    assert stop is False
    assert reason == ""
    assert details["bounded_two_card_loop"] is False


def test_should_block_repeat_stop_before_min_step_gate():
    previous = {
        "normalized_visible_label": "menu",
        "normalized_announcement": "menu",
        "focus_view_id": "id/menu",
        "focus_bounds": "0,0,10,10",
    }
    row = {
        "step_index": 1,
        "move_result": "failed",
        "last_smart_nav_result": "failed",
        "visible_label": "Menu",
        "merged_announcement": "Menu",
        "normalized_visible_label": "menu",
        "normalized_announcement": "menu",
        "focus_view_id": "id/menu",
        "focus_bounds": "0,0,10,10",
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("menu", "id/menu", "0,0,10,10"),
        fail_count=1,
        same_count=1,
        previous_row=previous,
        scenario_type="content",
    )

    assert stop is False
    assert reason == ""
    assert details["min_step_gate_blocked"] is True
    assert details["hard_no_progress"] is True


def test_should_allow_strict_hard_no_progress_even_after_realign_grace():
    previous = {
        "normalized_visible_label": "add",
        "normalized_announcement": "add",
        "focus_view_id": "id/add",
        "focus_bounds": "0,0,1,1",
    }
    row = {
        "step_index": 4,
        "move_result": "failed",
        "last_smart_nav_result": "failed",
        "visible_label": "Add",
        "merged_announcement": "Add",
        "normalized_visible_label": "add",
        "normalized_announcement": "add",
        "focus_view_id": "id/add",
        "focus_bounds": "0,0,1,1",
        "overlay_recovery_status": "after_realign",
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("add", "id/add", "0,0,1,1"),
        fail_count=1,
        same_count=1,
        previous_row=previous,
        scenario_type="content",
    )

    assert stop is True
    assert reason == "repeat_no_progress"
    assert details["strict_duplicate"] is True
    assert details["hard_no_progress"] is True


def test_should_include_stop_explain_snapshot_without_changing_decision():
    previous = {
        "normalized_visible_label": "add",
        "normalized_announcement": "add",
        "focus_view_id": "id/add",
        "focus_bounds": "0,0,1,1",
    }
    row = {
        "step_index": 4,
        "move_result": "failed",
        "last_smart_nav_result": "failed",
        "visible_label": "Add",
        "merged_announcement": "Add",
        "normalized_visible_label": "add",
        "normalized_announcement": "add",
        "focus_view_id": "id/add",
        "focus_bounds": "0,0,1,1",
        "overlay_recovery_status": "after_realign",
    }

    stop, _, _, reason, _, details = should_stop(
        row=row,
        prev_fingerprint=("add", "id/add", "0,0,1,1"),
        fail_count=1,
        same_count=1,
        previous_row=previous,
        scenario_type="content",
    )

    assert stop is True
    assert reason == "repeat_no_progress"
    assert details["stop_explain_version"] == "pr7_explain_v1"
    explain = details["stop_explain"]
    assert explain["repeat"]["repeat_class"] == details["repeat_class"]
    assert explain["no_progress"]["no_progress_class"] == "hard_no_progress"
    assert explain["overlay_context"]["realign_grace_suppressed"] is False
    assert explain["gates"]["min_step_gate_blocked"] is False
