from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from talkback_lib import A11yAdbClient
from tb_runner.evidence import (
    EvidenceEvent,
    EvidenceRuntime,
    build_reconciliation_report,
    reduce_shadow_events,
)
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


def _shadow_case(
    *,
    pre: dict,
    resolved: dict,
    post: dict,
    delayed: list[dict] | None = None,
    success: bool = True,
    reason: str = "moved",
) -> list[dict]:
    samples = delayed if delayed is not None else [post, post, post]
    events = [
        _event("pre", "PRE_FOCUS_OBSERVED", {"observation": pre}),
        _event("api", "ACTION_API_RESULT", {"success": success, "reason": reason}),
        _event("resolved", "TARGET_RESOLVED", {"resolvedTarget": resolved}),
        _event("post", "POST_ACTION_OBSERVATION", {"observation": post}),
    ]
    events.extend(
        _event(f"d{index}", "DELAYED_OBSERVATION", {"observation": sample, "offsetMs": offset})
        for index, (offset, sample) in enumerate(zip((100, 300, 1000), samples, strict=False))
    )
    events.append(_event("ack", "HELPER_ACK_RECEIVED"))
    return events


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


def test_resolved_target_without_immediate_focus_cannot_prove_snap_back() -> None:
    pre = _canonical(_raw_node("before", 0, label="before"), event_id="pre")
    resolved = _canonical(_raw_node("target", 20, label="target"), event_id="resolved")
    delayed = [_canonical(_raw_node("before", 0, label="before"), event_id="late")]
    assert evaluate_stability(pre, None, delayed, resolved=resolved).relation != TemporalRelation.SNAP_BACK


def test_target_relation_prefers_strong_physical_link_over_missing_window() -> None:
    resolved = _canonical(_raw_node(None, 20, label="target", window_id=None), event_id="resolved")
    landing = _canonical(_raw_node(None, 20, label="target", window_id=7), event_id="landing")
    result = evaluate_target_relation(None, resolved, landing)
    assert result.aggregate_relation == TargetRelation.STRONG_PHYSICAL_LINK
    assert result.allows_move_confirmation is True


def test_physical_scope_conflict_is_not_masked_by_semantic_similarity() -> None:
    target = _canonical(_raw_node("same", 20, label="same"), event_id="target")
    other_package = _raw_node("same", 20, label="same")
    other_package["packageName"] = "other.pkg"
    landing = _canonical(other_package, event_id="landing")
    result = evaluate_target_relation(None, target, landing)
    assert result.semantic_relation == TargetRelation.SAME_SEMANTIC_OBJECT
    assert result.aggregate_relation == TargetRelation.DIFFERENT_PHYSICAL_NODE
    assert result.allows_move_confirmation is False


def test_repeated_resource_diagnostic_does_not_mask_other_physical_node() -> None:
    target = _canonical(_raw_node("same", 0, label="first"), event_id="target")
    landing = _canonical(_raw_node("same", 20, label="second"), event_id="landing")
    result = evaluate_target_relation(None, target, landing)
    assert result.semantic_relation == TargetRelation.SAME_RESOURCE_DIFFERENT_INSTANCE
    assert result.aggregate_relation == TargetRelation.DIFFERENT_PHYSICAL_NODE


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
    assert result["confidence"] == "HIGH_CONFIDENCE"
    assert result["evidence_complete"] is True
    assert result["normalization_version"] == "canonical-observation-v1"


def test_reached_end_with_stable_unchanged_focus_is_static() -> None:
    node = _raw_node("end", 20, label="end")
    result = reduce_shadow_v2(
        _shadow_case(pre=node, resolved=node, post=node, success=False, reason="reached_end")
    )
    assert result["action_api"] == "REJECTED"
    assert result["verdict"] == "STATIC_FOCUS"
    assert result["verdict_reason"] == "REACHED_END_STABLE_UNCHANGED"
    assert result["confidence"] == "HIGH_CONFIDENCE"


def test_arbitrary_rejection_with_unchanged_focus_remains_indeterminate() -> None:
    node = _raw_node("node", 20, label="node")
    result = reduce_shadow_v2(
        _shadow_case(pre=node, resolved=node, post=node, success=False, reason="unsupported")
    )
    assert result["verdict"] == "INDETERMINATE"
    assert result["verdict_reason"] == "ACTION_NOT_ACCEPTED"


def test_v2_completeness_requires_delayed_stability_evidence() -> None:
    node = _raw_node("node", 20, label="node")
    events = _shadow_case(pre=node, resolved=node, post=node)
    events = [event for event in events if event["event_type"] != "DELAYED_OBSERVATION"]
    result = reduce_shadow_v2(events)
    assert result["evidence_complete"] is False
    assert result["evidence_completeness"] == "PARTIAL"
    assert result["verdict"] == "INDETERMINATE"
    assert result["verdict_reason"] == "EVIDENCE_INCOMPLETE"


def test_static_focus_requires_zero_physical_contradictions() -> None:
    before = _raw_node("before", 20, label="same")
    after = _raw_node("after", 20, label="same")
    result = reduce_shadow_v2(_shadow_case(pre=before, resolved=after, post=after))
    assert result["physical_focus_delta"] == "INDETERMINATE"
    assert "resource_id" in result["contradicting_fields"]
    assert result["verdict"] == "INDETERMINATE"


def test_delayed_series_with_single_strong_contradiction_is_not_stable() -> None:
    before = _raw_node("before", 20, label="same")
    replaced = _raw_node("after", 20, label="same")
    result = reduce_shadow_v2(
        _shadow_case(
            pre=before,
            resolved=before,
            post=before,
            delayed=[replaced, replaced, replaced],
        )
    )
    assert result["stability"] == "UNSTABLE"
    assert result["verdict"] == "INDETERMINATE"


def test_dynamic_label_on_same_accessibility_node_remains_static_physical_focus() -> None:
    before = _raw_node(
        "status",
        20,
        label="off",
        accessibility_node_id="node-42",
    )
    after = _raw_node(
        "status",
        20,
        label="on",
        accessibility_node_id="node-42",
    )
    result = reduce_shadow_v2(_shadow_case(pre=before, resolved=after, post=after))
    assert result["physical_focus_delta"] == "UNCHANGED"
    assert "semantic_label" in result["contradicting_fields"]
    assert result["verdict"] == "STATIC_FOCUS"


def test_unstable_landing_cannot_be_move_confirmed() -> None:
    before = _raw_node("before", 0, label="before")
    target = _raw_node("target", 20, label="target")
    drift = _raw_node("drift", 40, label="drift")
    result = reduce_shadow_v2(
        _shadow_case(pre=before, resolved=target, post=target, delayed=[target, drift, drift])
    )
    assert result["stability"] == "UNSTABLE"
    assert result["verdict"] == "INDETERMINATE"
    assert result["verdict_reason"] == "LANDING_NOT_STABLE"


def test_delayed_commit_is_not_misclassified_as_static_focus() -> None:
    before = _raw_node("before", 0, label="before")
    target = _raw_node("target", 20, label="target")
    result = reduce_shadow_v2(
        _shadow_case(pre=before, resolved=target, post=before, delayed=[target, target, target])
    )
    assert result["stability"] == "DELAYED_COMMIT"
    assert result["verdict"] == "INDETERMINATE"
    assert result["verdict_reason"] == "DELAYED_COMMIT_UNCONFIRMED"


def test_single_delayed_sample_cannot_complete_stable_landing() -> None:
    before = _raw_node("before", 0, label="before")
    target = _raw_node("target", 20, label="target")
    result = reduce_shadow_v2(
        _shadow_case(pre=before, resolved=target, post=target, delayed=[target])
    )
    assert result["stability"] == "INSUFFICIENT_EVIDENCE"
    assert result["evidence_complete"] is False
    assert result["verdict"] == "INDETERMINATE"
    assert "delayed_300ms" in result["missing_fields"]
    assert "delayed_1000ms" in result["missing_fields"]


def test_stable_other_node_is_reported_only_with_positive_contradiction() -> None:
    before = _raw_node("before", 0, label="before")
    target = _raw_node("target", 20, label="target")
    other = _raw_node("other", 40, label="other", class_name="android.widget.Button")
    result = reduce_shadow_v2(_shadow_case(pre=before, resolved=target, post=other))
    assert result["target_relation"] == "DIFFERENT_PHYSICAL_NODE"
    assert result["verdict"] == "MOVE_TO_OTHER_NODE"
    assert result["verdict_reason"] == "ACCEPTED_STABLE_OTHER_NODE"


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


def test_reconciliation_adds_non_blocking_identity_shadow_metrics() -> None:
    events = [
        EvidenceEvent(**_event("legacy", "SHADOW_ACTION_REDUCED", {"verdict": "MOVE_TO_OTHER_NODE"})),
        EvidenceEvent(
            **_event(
                "v2",
                "SHADOW_ACTION_REDUCED_V2",
                {
                    "verdict": "MOVE_CONFIRMED",
                    "confidence": "HIGH_CONFIDENCE",
                    "evidence_complete": True,
                },
            )
        ),
    ]
    report = build_reconciliation_report(events)
    assert report["status"] == "PASS"
    assert report["identity_shadow_v2"] == {
        "available": True,
        "transaction_count": 1,
        "legacy_transaction_count": 1,
        "legacy_transactions_without_v2": 0,
        "verdicts": {"MOVE_CONFIRMED": 1},
        "confidence": {"HIGH_CONFIDENCE": 1},
        "completeness": {"COMPLETE": 1, "PARTIAL": 0},
    }


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
        assert verdicts == {"MOVE_CONFIRMED": 11, "STATIC_FOCUS": 5}
    else:
        assert verdicts == {"MOVE_CONFIRMED": 11, "STATIC_FOCUS": 9}


def test_comparator_policy_never_grants_visit_credit_by_default() -> None:
    assert ComparatorPolicy().allows_direct_visit_credit is False
