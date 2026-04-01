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
    assert "get_focus_top_level_success_false" in low


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


def test_should_stop_when_move_failed_twice():
    prev_fp = ("", "", "")
    stop, fail_count, same_count, reason, _ = should_stop(
        row={"move_result": "failed", "visible_label": "a", "merged_announcement": "a"},
        prev_fingerprint=prev_fp,
        fail_count=1,
        same_count=0,
    )

    assert stop is True
    assert fail_count == 2
    assert same_count == 0
    assert reason == "move_failed_twice"


def test_should_stop_when_same_fingerprint_repeated():
    row = {
        "move_result": "moved",
        "visible_label": "a",
        "merged_announcement": "a",
        "normalized_visible_label": "label",
        "focus_view_id": "id",
        "focus_bounds": "0,0,1,1",
    }
    fp = ("label", "id", "0,0,1,1")

    stop, fail_count, same_count, reason, _ = should_stop(
        row=row,
        prev_fingerprint=fp,
        fail_count=0,
        same_count=2,
    )

    assert stop is True
    assert fail_count == 0
    assert same_count == 3
    assert reason == "same_fingerprint_repeated"


def test_should_stop_when_visible_and_speech_are_empty():
    stop, _, _, reason, _ = should_stop(
        row={"move_result": "moved", "visible_label": "", "merged_announcement": ""},
        prev_fingerprint=("", "", ""),
        fail_count=0,
        same_count=0,
    )

    assert stop is True
    assert reason == "empty_visible_and_speech"
