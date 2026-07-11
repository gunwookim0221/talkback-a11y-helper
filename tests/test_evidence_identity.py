from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from talkback_lib import A11yAdbClient
from tb_runner.evidence import EvidenceEvent, EvidenceRuntime, reduce_shadow_events
from tb_runner.evidence_identity import (
    ComparatorPolicy,
    FieldComparison,
    IdentityAssertion,
    TargetRelation,
    TemporalRelation,
    compare_physical,
    compare_semantic,
    evaluate_hierarchy,
    evaluate_stability,
    evaluate_target_relation,
    identity_shadow_enabled,
    normalize_observation,
    reduce_shadow_v2,
    replay_shadow_v2,
)


def _raw_node(
    resource_id: str | None,
    left: int,
    *,
    label: str = "node",
    window_id: int | None = 7,
    class_name: str = "android.widget.TextView",
    node_path: str | None = None,
    parent_path: str | None = None,
    accessibility_node_id: str | None = None,
) -> dict:
    node = {
        "packageName": "pkg",
        "className": class_name,
        "viewIdResourceName": resource_id,
        "boundsInScreen": {"l": left, "t": 0, "r": left + 10, "b": 10},
        "text": label,
        "talkbackLabel": label,
        "focusable": True,
        "accessibilityFocused": True,
    }
    if window_id is not None:
        node["windowId"] = window_id
    if node_path is not None:
        node["nodePath"] = node_path
    if parent_path is not None:
        node["parentPath"] = parent_path
    if accessibility_node_id is not None:
        node["accessibilityNodeId"] = accessibility_node_id
    return node


def _canonical(node: dict, *, source: str = "test", event_id: str = "evt"):
    return normalize_observation(
        node,
        source_type=source,
        envelope={
            "event_id": event_id,
            "run_id": "run",
            "scenario_tx_id": "stx",
            "transaction_id": "tx",
            "producer": "helper",
            "surface_id": "surface",
            "surface_revision": 0,
        },
    )


def _event(event_id: str, event_type: str, payload: dict | None = None, *, transaction_id: str = "tx") -> dict:
    return {
        "schema_version": "evidence-event-v1",
        "event_id": event_id,
        "event_type": event_type,
        "run_id": "run",
        "scenario_tx_id": "stx",
        "transaction_id": transaction_id,
        "logical_action_id": "act",
        "attempt_id": "att",
        "parent_transaction_id": None,
        "causation_event_id": None,
        "producer": "helper" if event_type not in {"PRE_FOCUS_OBSERVED", "POST_FOCUS_OBSERVED", "HELPER_ACK_RECEIVED"} else "runner",
        "producer_instance_id": "test",
        "producer_sequence": 1,
        "wall_time_utc": "2026-01-01T00:00:00.000Z",
        "monotonic_time_ns": 1,
        "runner_received_wall_time_utc": None,
        "scenario_id": "scenario",
        "plugin_family": "plugin",
        "step_index": 1,
        "phase": "main_loop",
        "surface_id": "surface",
        "surface_revision": 0,
        "payload": payload or {},
        "provenance": {},
    }


def test_normalize_observation_accepts_camel_and_snake_aliases_once() -> None:
    camel = _canonical(_raw_node("pkg:id/title", 10, label=" Hello "), event_id="camel")
    snake = _canonical(
        {
            "package": "pkg",
            "window_id": 7,
            "class_name": "android.widget.TextView",
            "resource_id": "pkg:id/title",
            "bounds": {"left": 10, "top": 0, "right": 20, "bottom": 10},
            "normalized_text": "hello",
            "normalized_talkback_label": "hello",
        },
        event_id="snake",
    )
    assert camel.package_name == snake.package_name == "pkg"
    assert camel.window_id == snake.window_id == "7"
    assert camel.class_name == snake.class_name == "android.widget.TextView"
    assert camel.resource_id_short == snake.resource_id_short == "title"
    assert camel.bounds_normalized == snake.bounds_normalized == (10, 0, 20, 10)
    assert camel.semantic_label == snake.semantic_label == "hello"


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (None, 7, FieldComparison.LEFT_MISSING),
        (7, None, FieldComparison.RIGHT_MISSING),
        (None, None, FieldComparison.BOTH_MISSING),
    ],
)
def test_missing_field_is_unavailable_not_different(left, right, expected) -> None:
    left_node = _canonical(_raw_node("title", 0, window_id=left), event_id="left")
    right_node = _canonical(_raw_node("title", 0, window_id=right), event_id="right")
    result = compare_physical(left_node, right_node)
    assert result.field_comparisons["window_id"] == expected
    assert result.relation != TargetRelation.DIFFERENT_PHYSICAL_NODE


def test_missing_window_still_allows_strong_physical_link_from_structural_evidence() -> None:
    resolved = _canonical(_raw_node(None, 10, label="Safe", window_id=None), event_id="resolved")
    post = _canonical(_raw_node(None, 10, label="Safe", window_id=1685), event_id="post")
    result = compare_physical(resolved, post)
    assert result.field_comparisons["window_id"] == FieldComparison.LEFT_MISSING
    assert result.relation == TargetRelation.STRONG_PHYSICAL_LINK


def test_known_different_window_is_a_physical_contradiction() -> None:
    left = _canonical(_raw_node("title", 0, window_id=1), event_id="left")
    right = _canonical(_raw_node("title", 0, window_id=2), event_id="right")
    assert compare_physical(left, right).relation == TargetRelation.DIFFERENT_PHYSICAL_NODE


def test_accessibility_node_id_can_confirm_exact_physical_node() -> None:
    left = _canonical(_raw_node("title", 0, accessibility_node_id="node-1"), event_id="left")
    right = _canonical(_raw_node("title", 0, accessibility_node_id="node-1"), event_id="right")
    assert compare_physical(left, right).relation == TargetRelation.EXACT_PHYSICAL_NODE


def test_semantic_relations_do_not_turn_same_label_into_physical_equality() -> None:
    left = _canonical(_raw_node(None, 0, label="Repeated"), event_id="left")
    right = _canonical(_raw_node(None, 100, label="Repeated"), event_id="right")
    semantic = compare_semantic(left, right)
    assert semantic.relation == TargetRelation.SAME_LABEL_DIFFERENT_LOCATION
    assert compare_physical(left, right).relation != TargetRelation.EXACT_PHYSICAL_NODE


def test_same_resource_different_location_is_preserved_as_instance_relation() -> None:
    left = _canonical(_raw_node("row", 0, label="A"), event_id="left")
    right = _canonical(_raw_node("row", 100, label="B"), event_id="right")
    assert compare_semantic(left, right).relation == TargetRelation.SAME_RESOURCE_DIFFERENT_INSTANCE


def test_announcement_equivalence_never_grants_direct_visit_credit() -> None:
    target = _canonical(_raw_node(None, 0, label="Title Description"), event_id="target")
    landing = _canonical(_raw_node(None, 100, label="Container"), event_id="landing")
    result = compare_semantic(target, landing, {"announcement": "Title Description button"})
    assert result.relation == TargetRelation.ANNOUNCEMENT_EQUIVALENT
    assert result.allows_direct_visit_credit is False


def test_hierarchy_detects_direction_without_bounds_inference() -> None:
    target = _canonical(_raw_node("child", 10, node_path="root/card/child", parent_path="root/card"), event_id="target")
    landing = _canonical(_raw_node("card", 0, node_path="root/card"), event_id="landing")
    parent = evaluate_hierarchy(target, landing)
    child = evaluate_hierarchy(landing, target)
    assert parent.relation == TargetRelation.TARGET_ANCESTOR
    assert parent.container_relation == TargetRelation.CONTAINER_PARENT
    assert child.relation == TargetRelation.TARGET_DESCENDANT
    assert child.container_relation == TargetRelation.CONTAINER_CHILD


def test_explicit_alias_assertion_is_scoped_and_non_crediting() -> None:
    target = _canonical(_raw_node("child", 10), event_id="target")
    landing = _canonical(_raw_node("container", 0), event_id="landing")
    assertion = IdentityAssertion(
        assertion_id="assertion",
        source_observation_id=target.canonical_observation_id,
        target_observation_id=landing.canonical_observation_id,
        relation=TargetRelation.ALIAS_EQUIVALENT,
        confidence="CONFIRMED",
    )
    result = evaluate_hierarchy(target, landing, [assertion])
    assert result.relation == TargetRelation.ALIAS_EQUIVALENT
    assert result.assertion_ids == ("assertion",)
    assert result.allows_direct_visit_credit is False


def test_stability_detects_stable_delayed_series_when_immediate_is_missing() -> None:
    pre = _canonical(_raw_node("before", 0), event_id="pre")
    resolved = _canonical(_raw_node("target", 20, window_id=None), event_id="resolved")
    delayed = [_canonical(_raw_node("target", 20), event_id=f"d{offset}") for offset in (100, 300, 1000)]
    result = evaluate_stability(pre, None, delayed, resolved=resolved)
    assert result.relation == TemporalRelation.STABLE_LANDING
    assert "immediate" in result.missing_samples


def test_stability_detects_snap_back() -> None:
    pre = _canonical(_raw_node("before", 0, label="before"), event_id="pre")
    immediate = _canonical(_raw_node("target", 20, label="target"), event_id="post")
    delayed = [_canonical(_raw_node("before", 0, label="before"), event_id="late")]
    assert evaluate_stability(pre, immediate, delayed).relation == TemporalRelation.SNAP_BACK


def test_target_relation_prefers_strong_physical_link_over_missing_window() -> None:
    resolved = _canonical(_raw_node(None, 20, label="target", window_id=None), event_id="resolved")
    landing = _canonical(_raw_node(None, 20, label="target", window_id=7), event_id="landing")
    result = evaluate_target_relation(None, resolved, landing)
    assert result.aggregate_relation == TargetRelation.STRONG_PHYSICAL_LINK
    assert result.allows_move_confirmation is True


def test_shadow_v2_does_not_classify_missing_window_as_other_node() -> None:
    before = _raw_node("before", 0, label="before", window_id=None)
    resolved = _raw_node(None, 20, label="target", window_id=None)
    post = _raw_node(None, 20, label="target", window_id=7)
    events = [
        _event("pre", "PRE_FOCUS_OBSERVED", {"observation": before}),
        _event("api", "ACTION_API_RESULT", {"success": True}),
        _event("resolved", "TARGET_RESOLVED", {"resolvedTarget": resolved}),
        _event("post", "POST_ACTION_OBSERVATION", {"observation": post}),
        _event("d100", "DELAYED_OBSERVATION", {"observation": post, "offsetMs": 100}),
        _event("d300", "DELAYED_OBSERVATION", {"observation": post, "offsetMs": 300}),
        _event("d1000", "DELAYED_OBSERVATION", {"observation": post, "offsetMs": 1000}),
        _event("ack", "HELPER_ACK_RECEIVED"),
    ]
    legacy_events = [EvidenceEvent(**event) for event in events]
    assert reduce_shadow_events(legacy_events)["verdict"] == "MOVE_TO_OTHER_NODE"
    result = reduce_shadow_v2(events)
    assert result["target_relation"] == "STRONG_PHYSICAL_LINK"
    assert result["verdict"] == "MOVE_CONFIRMED"


def test_replay_groups_transactions_without_mutating_events() -> None:
    events = [
        _event("pre1", "PRE_FOCUS_OBSERVED", {"observation": _raw_node("a", 0)}, transaction_id="tx1"),
        _event("post1", "POST_ACTION_OBSERVATION", {"observation": _raw_node("a", 0)}, transaction_id="tx1"),
        _event("pre2", "PRE_FOCUS_OBSERVED", {"observation": _raw_node("b", 20)}, transaction_id="tx2"),
        _event("post2", "POST_ACTION_OBSERVATION", {"observation": _raw_node("b", 20)}, transaction_id="tx2"),
    ]
    original = json.dumps(events, sort_keys=True)
    assert set(replay_shadow_v2(events)) == {"tx1", "tx2"}
    assert json.dumps(events, sort_keys=True) == original


def test_identity_shadow_flag_defaults_off_and_accepts_true(monkeypatch) -> None:
    monkeypatch.delenv("TB_EVIDENCE_IDENTITY_SHADOW_ENABLED", raising=False)
    assert identity_shadow_enabled() is False
    monkeypatch.setenv("TB_EVIDENCE_IDENTITY_SHADOW_ENABLED", "1")
    assert identity_shadow_enabled() is True


def test_runtime_feature_off_does_not_call_v2_reducer(tmp_path: Path, monkeypatch) -> None:
    runtime = EvidenceRuntime(output_path=tmp_path / "off.xlsx", identity_shadow=False)
    runtime.start_scenario("scenario")
    transaction = runtime.begin_transaction("SMART_NEXT", phase="main_loop")
    monkeypatch.setattr("tb_runner.evidence.reduce_shadow_v2", lambda _events: (_ for _ in ()).throw(AssertionError("called")))
    assert runtime.reduce_identity_shadow(transaction["transaction_id"]) is None


def test_evidence_off_suppresses_identity_shadow_and_all_artifacts(tmp_path: Path) -> None:
    runtime = EvidenceRuntime(
        output_path=tmp_path / "disabled.xlsx",
        enabled=False,
        identity_shadow=True,
    )
    assert runtime.identity_shadow_enabled is False
    assert runtime.reduce_identity_shadow("tx") is None
    assert runtime.finalize() == {}
    assert not list(tmp_path.glob("*.evidence.*"))


@pytest.mark.parametrize(("identity_shadow", "expect_v2"), [(False, False), (True, True)])
def test_runtime_emits_legacy_and_optional_v2_side_by_side(
    tmp_path: Path,
    monkeypatch,
    identity_shadow: bool,
    expect_v2: bool,
) -> None:
    runtime = EvidenceRuntime(output_path=tmp_path / f"runtime_{identity_shadow}.xlsx", identity_shadow=identity_shadow)
    runtime.start_scenario("scenario")
    client = A11yAdbClient(start_monitor=False)
    client.set_evidence_runtime(runtime)
    before = _raw_node("before", 0, label="before", window_id=None)
    target = _raw_node("target", 20, label="target", window_id=7)
    client._evidence_last_focus_node = before
    client._evidence_set_step(1)
    transaction = client._evidence_begin_step_action("SMART_NEXT")
    assert transaction is not None
    runtime.emit("ACTION_API_RESULT", producer="helper", phase="helper", transaction=transaction, payload={"success": True})
    runtime.emit("TARGET_RESOLVED", producer="helper", phase="helper", transaction=transaction, payload={"resolvedTarget": target})
    runtime.emit("POST_ACTION_OBSERVATION", producer="helper", phase="helper", transaction=transaction, payload={"observation": target})
    client._evidence_helper_ack({}, req_id="req")
    monkeypatch.setattr(client, "_evidence_fetch_helper_events", lambda *_args, **_kwargs: None)
    client._evidence_complete_step_action({"step_index": 1, "merged_announcement": "target"}, target)
    event_types = [json.loads(line)["event_type"] for line in runtime.ledger.path.read_text(encoding="utf-8").splitlines()]
    assert "SHADOW_ACTION_REDUCED" in event_types
    assert ("SHADOW_ACTION_REDUCED_V2" in event_types) is expect_v2


def _frozen_ledger_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    return {
        "Motion": root / "qa_frontend_runs/batch_20260711_212123/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260711_212134.evidence.jsonl",
        "Safe": root / "qa_frontend_runs/batch_20260711_212734/device_SM-F741N_R3CX40QFDBP/talkback_compare_20260711_212745.evidence.jsonl",
    }


@pytest.mark.parametrize(("scenario", "expected_transactions"), [("Motion", 16), ("Safe", 20)])
def test_frozen_motion_safe_replay_removes_window_missing_false_other_node(
    scenario: str,
    expected_transactions: int,
) -> None:
    path = _frozen_ledger_paths()[scenario]
    if not path.exists():
        pytest.skip(f"local frozen ledger unavailable: {path}")
    raw_events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in raw_events:
        if event.get("transaction_id"):
            grouped[event["transaction_id"]].append(event)
    assert len(grouped) == expected_transactions

    legacy = Counter()
    for events in grouped.values():
        legacy[reduce_shadow_events([EvidenceEvent(**event) for event in events])["verdict"]] += 1
    assert legacy == {"MOVE_TO_OTHER_NODE": expected_transactions}

    replay = replay_shadow_v2(raw_events)
    verdicts = Counter(result["verdict"] for result in replay.values())
    relations = Counter(result["target_relation"] for result in replay.values())
    assert verdicts["MOVE_TO_OTHER_NODE"] == 0
    assert relations["STRONG_PHYSICAL_LINK"] == expected_transactions
    if scenario == "Motion":
        assert verdicts == {"MOVE_CONFIRMED": 11, "STATIC_FOCUS": 3, "INDETERMINATE": 2}
    else:
        assert verdicts == {"MOVE_CONFIRMED": 11, "STATIC_FOCUS": 6, "INDETERMINATE": 3}


def test_comparator_policy_never_grants_visit_credit_by_default() -> None:
    assert ComparatorPolicy().allows_direct_visit_credit is False
