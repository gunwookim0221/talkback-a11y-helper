from tools import clean_start_smartthings as clean_start


def test_is_smartthings_foreground_rejects_play_store_overlay():
    focus = (
        "mCurrentFocus=Window{abc com.android.vending/com.google.android.finsky.inappreviewdialog.InAppReviewActivity}\n"
        "mFocusedApp=ActivityRecord{def com.android.vending/.InAppReviewActivity}"
    )

    assert clean_start.is_smartthings_foreground(focus) is False


def test_is_smartthings_foreground_accepts_smartthings_activity():
    focus = (
        "mCurrentFocus=Window{abc com.samsung.android.oneconnect/"
        "com.samsung.android.oneconnect.ui.SCMainActivity}\n"
        "mFocusedApp=ActivityRecord{def com.samsung.android.oneconnect/.ui.SCMainActivity}"
    )

    assert clean_start.is_smartthings_foreground(focus) is True


def test_clean_start_retries_after_play_store_focus(monkeypatch):
    commands = []
    focus_values = [
        "mCurrentFocus=Window{abc com.android.vending/.InAppReviewActivity}",
        "mCurrentFocus=Window{def com.samsung.android.oneconnect/.ui.SCMainActivity}",
    ]

    def fake_run_adb(serial, *args, timeout=15.0):
        commands.append(args)
        return clean_start.CommandResult(tuple(args), 0, "", "")

    def fake_current_focus(serial=None):
        return focus_values.pop(0)

    monkeypatch.setattr(clean_start, "run_adb", fake_run_adb)
    monkeypatch.setattr(clean_start, "current_focus", fake_current_focus)
    monkeypatch.setattr(clean_start.time, "sleep", lambda _seconds: None)

    ok, _results, focus = clean_start.clean_start_smartthings(wait_seconds=0.0, max_attempts=2)

    assert ok is True
    assert "com.samsung.android.oneconnect" in focus
    assert ("shell", "am", "force-stop", clean_start.PLAY_STORE_PACKAGE) in commands
    assert commands.count(("shell", "am", "start", "-n", clean_start.SMARTTHINGS_ACTIVITY)) == 2
