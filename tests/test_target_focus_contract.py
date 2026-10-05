from types import SimpleNamespace

from tb_runner.content_terminal import ContentTerminal
from tb_runner.focus_realign_logic import _maybe_realign_focus_to_representative_impl, _target_focus_matches
from tb_runner.traversal_reliability import TraversalMetrics


def node(rid="id/a", label="A", bounds="0,0,100,100", focused=True):
    return {
        "viewIdResourceName": rid,
        "text": label,
        "talkbackLabel": label,
        "boundsInScreen": bounds,
        "className": "android.widget.Button",
        "accessibilityFocused": focused,
        "focused": False,
    }


class Client:
    def __init__(self, actual, status="TARGET_MATCHED", success=True):
        self.actual = actual
        self.status = status
        self.success = success
        self.calls = []

    def target_focus_commit(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": self.success, "status": self.status}

    def get_focus(self, **_kwargs):
        return self.actual


def commit(client, target):
    row = {"focus_view_id": "id/sibling", "visible_label": "Sibling", "focus_bounds": "0,120,100,220"}
    return row, _maybe_realign_focus_to_representative_impl(
        client=client, dev="SERIAL", row=row, selected_node=target,
        selected_rid=target["viewIdResourceName"], selected_label=target["text"],
        selected_bounds=target["boundsInScreen"], scenario_id="home", step_idx=1,
        mismatch_logged=True, force_reason="anchor_mismatch", scenario_perf=None,
        focus_matches_fn=lambda **_kwargs: False,
        extract_label_fn=lambda value: value.get("text", ""),
        label_blob_fn=lambda value: value.get("talkbackLabel", ""),
        truncate_fn=lambda value, *_args: value, log_fn=lambda _message: None,
    )


def test_exact_target_commit_matches_and_sends_full_descriptor():
    target = node()
    client = Client(target)
    row, (ok, reason, actual) = commit(client, target)
    assert ok and reason == "TARGET_MATCHED" and actual == target
    assert client.calls[0]["target"] == {
        "bounds": "0,0,100,100", "resource_id": "id/a", "label": "A",
        "class_name": "android.widget.Button",
    }
    assert row["target_focus_status"] == "TARGET_MATCHED"


def test_same_resource_id_different_bounds_is_not_a_match():
    assert not _target_focus_matches(
        focus_node=node(bounds="0,120,100,220"), target_rid="id/a", target_label="A",
        target_bounds="0,0,100,100", target_class="android.widget.Button",
    )


def test_sibling_focus_never_verifies_selected_target():
    target = node()
    row, (ok, reason, actual) = commit(Client(node("id/b", "B", "0,120,100,220"), "FOCUS_MOVED_TO_OTHER_NODE", False), target)
    assert not ok and reason == "FOCUS_MOVED_TO_OTHER_NODE" and actual["viewIdResourceName"] == "id/b"
    assert row["target_focus_status"] == "FOCUS_MOVED_TO_OTHER_NODE"


def test_ack_failure_but_actual_target_focus_wins():
    target = node()
    row, (ok, reason, _actual) = commit(Client(target, "FOCUS_ACTION_REJECTED", False), target)
    assert ok and reason == "TARGET_MATCHED"
    assert row["target_focus_status"] == "TARGET_MATCHED"


def test_ack_success_without_actual_focus_move_has_no_match():
    target = node()
    row, (ok, reason, _actual) = commit(Client(node("id/sibling", "Sibling", "0,120,100,220"), "FOCUS_UNCHANGED", True), target)
    assert not ok and reason == "FOCUS_UNCHANGED"
    assert row["target_focus_status"] == "FOCUS_UNCHANGED"


def test_no_progress_waits_for_unattempted_target_then_terminates_after_attempt():
    candidate = {
        "viewIdResourceName": "id/a", "text": "A", "className": "android.widget.Button",
        "boundsInScreen": "0,0,100,100", "visibleToUser": True, "focusable": True, "clickable": True,
    }
    observation = {
        "nodes": [candidate],
        "capability": {"can_scroll_forward": False, "vertical_can_scroll_forward": False, "contradictory": False},
        "viewport": {"valid": True, "stable_signature": "v"},
    }
    terminal = ContentTerminal("home")
    attempt = {"resource_id": "id/a", "bounds": "0,0,100,100", "label": "A",
               "class_name": "android.widget.Button", "status": "TARGET_NOT_FOUND"}
    terminal.observe(observation, 0, target_attempt=attempt)
    for step in range(1, 5):
        terminal.observe(observation, step)
    assert terminal.latest["unattempted_active_unseen"] == 0
    assert terminal.decision() == "content_no_progress"


def test_no_progress_waits_only_for_unattempted_candidates_in_current_valid_planner_pool():
    first = node("id/a", "A", "0,0,100,100", focused=False)
    second = node("id/b", "B", "0,120,100,220", focused=False)
    observation = {
        "nodes": [first, second],
        "capability": {"can_scroll_forward": False, "vertical_can_scroll_forward": False, "contradictory": False},
        "viewport": {"valid": True, "stable_signature": "v"},
    }
    terminal = ContentTerminal("home")
    terminal.observe(
        observation,
        0,
        target_attempt={
            "resource_id": "id/a",
            "bounds": "0,0,100,100",
            "label": "A",
            "class_name": "android.widget.Button",
            "status": "FOCUS_MOVED_TO_OTHER_NODE",
        },
    )
    terminal.planner_candidate_ids = set(terminal.latest["unseen_candidate_ids"])

    for step in range(1, 5):
        terminal.observe(observation, step)
    assert terminal.latest["unattempted_active_unseen"] == 1
    assert terminal.decision() == ""
    assert terminal.visited == set()

    terminal.planner_candidate_ids = set()
    terminal.observe(observation, 5)
    assert terminal.latest["unattempted_active_unseen"] == 0
    assert terminal.latest["active_unseen"] == 2
    assert terminal.decision() == "content_no_progress"


def test_valid_unattempted_planner_targets_delay_no_progress_before_first_target_attempt():
    candidates = [
        node("id/a", "A", "0,0,100,100", focused=False),
        node("id/b", "B", "0,120,100,220", focused=False),
    ]
    observation = {
        "nodes": candidates,
        "capability": {"can_scroll_forward": False, "vertical_can_scroll_forward": False, "contradictory": False},
        "viewport": {"valid": True, "stable_signature": "v"},
    }
    terminal = ContentTerminal("home")
    terminal.observe(observation, 0)
    terminal.planner_candidate_ids = set(terminal.latest["unseen_candidate_ids"])

    for step in range(1, 5):
        terminal.observe(observation, step)

    assert terminal.latest["target_attempt_contract_active"] is False
    assert terminal.latest["unattempted_active_unseen"] == 2
    assert terminal.decision() == ""


def test_verified_anchor_is_credited_exactly_once():
    metrics = TraversalMetrics()
    anchor = {
        "scenario_id": "home", "step_index": 0, "status": "ANCHOR", "physical_visited": True,
        "focus_view_id": "id/map", "focus_bounds": "0,0,100,100", "visible_label": "Map",
        "actual_focus_resource_id": "id/map", "actual_focus_bounds": "0,0,100,100",
        "actual_focus_visible": "Map", "actual_focus_accessibility_focused": True,
        "actual_focus_node": node("id/map", "Map"),
    }
    metrics.observe_focus(anchor)
    metrics.observe_focus(anchor)
    assert len(metrics.visited) == 1
    assert len(metrics.focus_observations) == 1
