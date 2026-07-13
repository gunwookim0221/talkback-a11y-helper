from unittest.mock import patch

from test_talkback_lib import CollectFocusStepClient


def _helper_events(transaction_id: str) -> list[dict]:
    correlation = {"transaction_id": transaction_id}
    observation = {
        "text": "Hello",
        "className": "android.widget.TextView",
        "packageName": "com.example.custom",
        "boundsInScreen": {"l": 1, "t": 2, "r": 3, "b": 4},
        "accessibilityFocused": True,
    }
    events = [
        {
            "eventType": "ACTION_API_RESULT",
            "correlation": correlation,
            "payload": {"success": True},
        },
        {
            "eventType": "FOCUS_COMMIT_CLAIMED",
            "correlation": correlation,
            "payload": {"claim": "navigator_outcome_success"},
        },
        {
            "eventType": "POST_ACTION_OBSERVATION",
            "correlation": correlation,
            "payload": {"observation": observation},
        },
    ]
    for offset_ms in (100, 300, 1000):
        events.append(
            {
                "eventType": "DELAYED_OBSERVATION",
                "correlation": correlation,
                "payload": {"offsetMs": offset_ms, "observation": dict(observation)},
            }
        )
    return events


def _run_collection(*, complete_evidence: bool) -> tuple[dict, float, int]:
    client = CollectFocusStepClient()
    client.partial_payload = []
    client._evidence_active_transaction = {"transaction_id": "tx-current", "phase": "main_loop"}
    client._evidence_active_request_id = "req-current"
    client.last_smart_nav_result = {
        "success": True,
        "status": "moved",
        "reqId": "req-current",
        "evidenceEvents": _helper_events("tx-current") if complete_evidence else [],
    }
    clock = {"value": 0.0}

    def fake_monotonic() -> float:
        return clock["value"]

    def poll(dev=None, wait_seconds: float = 2.0, only_new: bool = True):
        del dev, only_new
        clock["value"] += wait_seconds
        client.partial_calls.append(("SERIAL", wait_seconds, True))
        return []

    with patch.object(client, "get_partial_announcements", side_effect=poll), patch(
        "talkback_lib.step_collection_service.time.monotonic", side_effect=fake_monotonic
    ):
        row = client.collect_focus_step(
            dev="SERIAL",
            move=True,
            wait_seconds=0.2,
            announcement_wait_seconds=1.5,
            announcement_idle_wait_seconds=0.5,
            announcement_max_extra_wait_seconds=1.5,
        )
    return row, clock["value"], len(client.partial_calls)


def test_complete_correlated_helper_evidence_uses_adaptive_fast_path() -> None:
    row, elapsed, polls = _run_collection(complete_evidence=True)
    assert row["partial_announcements"] == []
    assert row["visible_label"] == "Hello"
    assert elapsed < 1.5
    assert polls < 10


def test_incomplete_evidence_preserves_conservative_deadline_and_row() -> None:
    fast_row, fast_elapsed, _ = _run_collection(complete_evidence=True)
    fallback_row, fallback_elapsed, _ = _run_collection(complete_evidence=False)
    assert fallback_elapsed >= 3.0
    assert fast_elapsed < fallback_elapsed
    for key in (
        "partial_announcements",
        "merged_announcement",
        "visible_label",
        "focus_text",
        "focus_view_id",
        "focus_bounds",
        "move_result",
    ):
        assert fast_row[key] == fallback_row[key]


def test_transient_delayed_focus_preserves_conservative_deadline() -> None:
    client = CollectFocusStepClient()
    client._evidence_active_transaction = {"transaction_id": "tx-current", "phase": "main_loop"}
    client._evidence_active_request_id = "req-current"
    events = _helper_events("tx-current")
    events[-1]["payload"]["observation"]["boundsInScreen"] = {"l": 9, "t": 9, "r": 19, "b": 19}
    client.last_smart_nav_result = {
        "success": True,
        "reqId": "req-current",
        "evidenceEvents": events,
    }
    assert client._step_collection_service._correlated_action_focus_observation(move=True) is None
