from talkback_lib import announcement, focus_reader


def test_focus_reader_import_sanity() -> None:
    assert hasattr(focus_reader, "get_focus")


def test_announcement_import_sanity() -> None:
    assert hasattr(announcement, "get_announcements")
