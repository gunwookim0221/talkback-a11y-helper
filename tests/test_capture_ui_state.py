from unittest.mock import Mock

import capture_ui_state


def test_capture_full_screenshot_delegates_to_client_snapshot():
    client = Mock()

    capture_ui_state.capture_full_screenshot(client, "SERIAL", "screen.png")

    client._take_snapshot.assert_called_once_with("SERIAL", "screen.png")


def test_capture_full_screenshot_propagates_snapshot_failure():
    client = Mock()
    client._take_snapshot.side_effect = RuntimeError("snapshot failed")

    try:
        capture_ui_state.capture_full_screenshot(client, "SERIAL", "screen.png")
        assert False, "snapshot failure should propagate"
    except RuntimeError as exc:
        assert str(exc) == "snapshot failed"
