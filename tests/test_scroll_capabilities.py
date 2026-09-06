import json

from talkback_lib import A11yAdbClient
from talkback_lib.constants import ACTION_DUMP_TREE


def test_dump_tree_scroll_capabilities_is_opt_in_and_preserves_existing_nodes(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    broadcast = {}
    monkeypatch.setattr(client, "check_helper_status", lambda dev=None: True)
    monkeypatch.setattr(client, "clear_logcat", lambda dev=None: "")

    def fake_broadcast(dev, action, extras):
        broadcast.update(action=action, extras=extras)
        return ""

    monkeypatch.setattr(client, "_broadcast", fake_broadcast)
    monkeypatch.setattr(
        client._logcat_reader,
        "dump_raw_filtered",
        lambda dev=None: (
            f'DUMP_TREE_RESULT {broadcast["extras"][2]} '
            + json.dumps(
                {
                    "algorithmVersion": "test",
                    "canScrollDown": True,
                    "nodes": [{"text": "Existing node"}],
                    "scrollCapabilities": [
                        {
                            "path": "0.1",
                            "className": "android.widget.GridView",
                            "scroll_backward_supported": True,
                        }
                    ],
                }
            )
        ),
    )

    nodes = client.dump_tree(dev="SERIAL", wait_seconds=0.1, include_scroll_capabilities=True)

    assert broadcast["action"] == ACTION_DUMP_TREE
    assert broadcast["extras"][0:2] == ["--es", "reqId"]
    assert broadcast["extras"][3:] == ["--ez", "includeScrollCapabilities", "true"]
    assert nodes == [{"text": "Existing node"}]
    assert client.last_scroll_capabilities[0]["className"] == "android.widget.GridView"


def test_dump_scroll_capabilities_returns_copy_of_optional_field(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    expected = [{"path": "0", "actions": []}]
    monkeypatch.setattr(
        client,
        "dump_tree",
        lambda **kwargs: setattr(client, "last_scroll_capabilities", expected) or [],
    )

    result = client.dump_scroll_capabilities(dev="SERIAL")

    assert result == expected
    assert result is not expected


def test_device_collection_bridge_is_explicit_and_separate_from_diagnostics(monkeypatch):
    client = A11yAdbClient(start_monitor=False)
    broadcast = {}
    monkeypatch.setattr(client, "check_helper_status", lambda dev=None: True)
    monkeypatch.setattr(client, "clear_logcat", lambda dev=None: "")
    monkeypatch.setattr(
        client,
        "_broadcast",
        lambda dev, action, extras: broadcast.update(action=action, extras=extras) or "",
    )
    monkeypatch.setattr(
        client._logcat_reader,
        "dump_raw_filtered",
        lambda dev=None: (
            f'DUMP_TREE_RESULT {broadcast["extras"][2]} '
            + json.dumps(
                {
                    "algorithmVersion": "test",
                    "canScrollDown": True,
                    "nodes": [{"text": "Existing node"}],
                    "deviceCollection": {
                        "verified": True,
                        "boundsInScreen": {"l": 0, "t": 0, "r": 100, "b": 100},
                        "cardBounds": [],
                    },
                }
            )
        ),
    )

    nodes = client.dump_tree(dev="SERIAL", wait_seconds=0.1, include_device_collection=True)

    assert nodes == [{"text": "Existing node"}]
    assert broadcast["extras"][3:] == ["--ez", "includeDeviceCollection", "true"]
    assert client.last_device_collection["verified"] is True
    assert client.last_scroll_capabilities == []
