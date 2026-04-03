from tb_runner.diagnostics import detect_step_mismatch, should_stop


def test_detect_step_mismatch_returns_speech_visible_diverged():
    row = {
        "normalized_visible_label": "wifi",
        "normalized_announcement": "bluetooth",
    }

    mismatch, low = detect_step_mismatch(row)

    assert "speech_visible_diverged" in mismatch
    assert low == []


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
