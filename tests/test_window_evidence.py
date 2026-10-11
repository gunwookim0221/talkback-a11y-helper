from tools.state_fingerprint_diagnostic import summarize_window_evidence


def test_summarize_focused_base_application_window_without_retaining_full_dump():
    dump = """Window #0 Window{aaa u0 com.example/com.example.MainActivity}:\n    mAttrs={(0,0)(fillxfill) ty=BASE_APPLICATION}\n    mFrame=[0,0][1080,2400]\nWindow #1 Window{bbb u0 com.android.systemui/StatusBar}:\n    mAttrs={(0,0)(fillx24) ty=STATUS_BAR}\n    mFrame=[0,0][1080,24]\nmCurrentFocus=Window{aaa u0 com.example/com.example.MainActivity}\nmFocusedApp=ActivityRecord{abc u0 com.example/.MainActivity}\n"""

    result = summarize_window_evidence(dump)

    assert result["window_count"] == 2
    assert result["window_types"] == ["BASE_APPLICATION", "STATUS_BAR"]
    assert result["focused_window_component"] == "com.example.MainActivity"
    assert result["focused_window_type"] == "BASE_APPLICATION"
    assert result["focused_window_is_dialog"] is False
    assert "mAttrs" not in str(result)


def test_summarize_focused_attached_dialog_window_as_explicit_modal_signal():
    dump = """Window #0 Window{aaa u0 com.example/com.example.MainActivity}:\n    mAttrs={(0,0)(fillxfill) ty=BASE_APPLICATION}\nWindow #1 Window{bbb u0 com.example/com.example.AlertDialog}:\n    mAttrs={(100,100)(fillxfill) ty=APPLICATION_ATTACHED_DIALOG}\nmCurrentFocus=Window{bbb u0 com.example/com.example.AlertDialog}\n"""

    result = summarize_window_evidence(dump)

    assert result["window_count"] == 2
    assert result["focused_window_type"] == "APPLICATION_ATTACHED_DIALOG"
    assert result["focused_window_is_dialog"] is True


def test_summarize_prefers_concrete_focus_over_cover_display_null_focus():
    dump = """Display #1 cover:
mCurrentFocus=null
Display #0 main:
Window #0 Window{abc u0 com.example/com.example.CameraActivity}:
    mAttrs={(0,0)(fillxfill) ty=BASE_APPLICATION}
    mFrame=[0,0][1080,2400]
mCurrentFocus=Window{abc u0 com.example/com.example.CameraActivity}
"""

    result = summarize_window_evidence(dump)

    assert result["current_focus_line"].endswith("com.example/com.example.CameraActivity}")
    assert result["focused_window_component"] == "com.example.CameraActivity"
    assert result["focused_window_type"] == "BASE_APPLICATION"
