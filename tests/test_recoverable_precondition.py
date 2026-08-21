from tb_runner import collection_flow
from tb_runner.scenario_config import TAB_CONFIGS


class RecoveryClient:
    def __init__(self, dumps=None, *, click_result=True):
        self.dumps = list(dumps or [])
        self.click_result = click_result
        self.select_calls = []
        self.click_focused_calls = []
        self.dump_tree_calls = []

    def select(self, **kwargs):
        self.select_calls.append(kwargs)
        return True

    def click_focused(self, **kwargs):
        self.click_focused_calls.append(kwargs)
        return self.click_result

    def dump_tree(self, **kwargs):
        self.dump_tree_calls.append(kwargs)
        return self.dumps.pop(0) if self.dumps else []


def _cfg() -> dict:
    return {
        "scenario_id": "life_air_care_plugin",
        "recoverable_precondition": {
            "target_resource_ids": [
                "com.samsung.android.oneconnect:id/service_card",
                "com.samsung.android.oneconnect:id/containerNameLayout",
                "com.samsung.android.oneconnect:id/frameLayout",
            ],
            "error_resource_ids": [
                "com.samsung.android.oneconnect:id/errorMessage",
            ],
            "action_resource_ids": [
                "com.samsung.android.oneconnect:id/btTextButton",
            ],
        },
    }


def _target(*, error: bool, label: str, actionable: bool = True) -> dict:
    children = []
    if error:
        children.extend(
            [
                {
                    "text": "localized connection problem",
                    "viewIdResourceName": (
                        "com.samsung.android.oneconnect:id/errorMessage"
                    ),
                    "visibleToUser": True,
                    "children": [],
                },
                {
                    "text": "localized refresh",
                    "viewIdResourceName": (
                        "com.samsung.android.oneconnect:id/btTextButton"
                    ),
                    "clickable": actionable,
                    "enabled": actionable,
                    "effectiveClickable": actionable,
                    "visibleToUser": True,
                    "children": [],
                },
            ]
        )
    else:
        children.append(
            {
                "text": "localized normal value",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/airValue",
                "visibleToUser": True,
                "children": [],
            }
        )
    return {
        "text": label,
        "viewIdResourceName": "com.samsung.android.oneconnect:id/service_card",
        "visibleToUser": True,
        "children": children,
    }


def _run(client: RecoveryClient, target: dict, *, cfg: dict | None = None) -> dict:
    return collection_flow._run_recoverable_precondition_gate(
        client=client,
        dev="SERIAL",
        tab_cfg=cfg or _cfg(),
        target_node=target,
        initial_nodes=[target],
        wait_seconds=0.2,
    )


def test_normal_ko_kr_needs_no_recovery(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = RecoveryClient()
    result = _run(client, _target(error=False, label="에어 케어"))

    assert result["outcome"] == "NO_RECOVERY_NEEDED"
    assert result["attempted"] is False
    assert result["attempt_count"] == 0
    assert client.select_calls == []
    assert client.click_focused_calls == []


def test_normal_en_us_needs_no_recovery(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    result = _run(
        RecoveryClient(),
        _target(error=False, label="Air Care"),
    )

    assert result["outcome"] == "NO_RECOVERY_NEEDED"
    assert result["attempt_count"] == 0


def test_ko_kr_error_recovers_once_and_is_stable(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = RecoveryClient(
        [
            [_target(error=False, label="에어 케어")],
            [_target(error=False, label="에어 케어")],
        ]
    )
    result = _run(client, _target(error=True, label="에어 케어"))

    assert result["outcome"] == "RECOVERED_STABLE"
    assert result["detected"] is True
    assert result["attempted"] is True
    assert result["attempt_count"] == 1
    assert result["error_resource_ids"] == [
        "com.samsung.android.oneconnect:id/errorMessage"
    ]
    assert result["action_resource_id"] == (
        "com.samsung.android.oneconnect:id/btTextButton"
    )
    assert len(client.select_calls) == 1
    assert client.select_calls[0]["name"] == (
        "com.samsung.android.oneconnect:id/btTextButton"
    )
    assert len(client.click_focused_calls) == 1


def test_en_us_error_uses_same_structural_contract(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = RecoveryClient(
        [
            [_target(error=False, label="Air Care")],
            [_target(error=False, label="Air Care")],
        ]
    )
    result = _run(client, _target(error=True, label="Air Care"))

    assert result["outcome"] == "RECOVERED_STABLE"
    assert result["action_resource_id"] == (
        "com.samsung.android.oneconnect:id/btTextButton"
    )


def test_arbitrary_localized_text_still_detects_structurally(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = RecoveryClient(
        [
            [_target(error=False, label="Target A")],
            [_target(error=False, label="Target A")],
        ]
    )
    result = _run(client, _target(error=True, label="Target A"))

    assert result["outcome"] == "RECOVERED_STABLE"
    assert result["detection_basis"] == "target_associated_resource_ids"


def test_error_descendants_inside_selected_target_subtree_are_recoverable(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    selected_target = _target(error=True, label="Air Care")
    error_parent = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/card_root",
        "visibleToUser": True,
        "children": [
            selected_target,
        ],
    }
    normal_parent = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/card_root",
        "visibleToUser": True,
        "children": [
            _target(error=False, label="Air Care"),
        ],
    }
    client = RecoveryClient([[normal_parent], [normal_parent]])
    result = collection_flow._run_recoverable_precondition_gate(
        client=client,
        dev="SERIAL",
        tab_cfg=_cfg(),
        target_node=selected_target,
        initial_nodes=[error_parent],
        wait_seconds=0.2,
    )

    assert result["outcome"] == "RECOVERED_STABLE"
    assert len(client.select_calls) == 1
    assert len(client.click_focused_calls) == 1


def test_sibling_subtree_error_and_refresh_do_not_trigger_recovery(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    target = _target(error=False, label="Air Care")
    target["boundsInScreen"] = "0,0,500,500"
    sibling = _target(error=True, label="Other card")
    sibling["boundsInScreen"] = "500,0,1000,500"
    shared_container = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/sharedContainer",
        "visibleToUser": True,
        "children": [target, sibling],
    }
    client = RecoveryClient()

    result = collection_flow._run_recoverable_precondition_gate(
        client=client,
        dev="SERIAL",
        tab_cfg=_cfg(),
        target_node=target,
        initial_nodes=[shared_container],
        wait_seconds=0.2,
    )

    assert result["outcome"] == "NO_RECOVERY_NEEDED"
    assert client.select_calls == []
    assert client.click_focused_calls == []


def test_duplicate_refresh_ids_select_the_target_subtree_control(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    sibling = _target(error=True, label="Other card")
    target = _target(error=True, label="Air Care")
    shared_container = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/sharedContainer",
        "visibleToUser": True,
        "children": [sibling, target],
    }
    normal_target = _target(error=False, label="Air Care")
    client = RecoveryClient([[normal_target], [normal_target]])

    result = collection_flow._run_recoverable_precondition_gate(
        client=client,
        dev="SERIAL",
        tab_cfg=_cfg(),
        target_node=target,
        initial_nodes=[shared_container],
        wait_seconds=0.2,
    )

    assert result["outcome"] == "RECOVERED_STABLE"
    assert len(client.select_calls) == 1
    assert client.select_calls[0]["index_"] == 1


def test_moved_target_does_not_fall_back_to_duplicate_sibling_resource_id(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    error_target = _target(error=True, label="Air Care")
    error_target["boundsInScreen"] = "0,100,400,300"
    sibling = _target(error=False, label="Other card")
    sibling["boundsInScreen"] = "700,0,1000,400"
    moved_target = _target(error=False, label="Air Care normal")
    moved_target["viewIdResourceName"] = (
        "com.samsung.android.oneconnect:id/frameLayout"
    )
    moved_target["boundsInScreen"] = "0,0,500,500"
    post_root = {
        "viewIdResourceName": "com.samsung.android.oneconnect:id/sharedContainer",
        "visibleToUser": True,
        "children": [sibling, moved_target],
    }
    client = RecoveryClient([[post_root], [post_root]])

    result = _run(client, error_target)

    assert result["outcome"] == "RECOVERED_STABLE"
    recovered_target = client.last_recoverable_precondition_target
    assert recovered_target["text"] == "Air Care normal"
    assert len(client.select_calls) == 1


def test_error_remaining_is_recovery_failed(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    error_target = _target(error=True, label="Air Care")
    client = RecoveryClient([[error_target], [error_target]])
    result = _run(client, error_target)

    assert result["outcome"] == "RECOVERY_FAILED"
    assert result["attempt_count"] == 1
    assert result["reason"] == "error_state_remains"
    assert len(client.click_focused_calls) == 1


def test_error_clears_during_bounded_stability_wait(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    error_target = _target(error=True, label="Air Care")
    client = RecoveryClient(
        [
            [_target(error=True, label="Air Care")],
            [_target(error=False, label="Air Care")],
        ]
    )
    result = _run(client, error_target)

    assert result["outcome"] == "RECOVERY_FAILED"
    assert result["reason"] == "normal_state_not_stable"
    assert result["attempt_count"] == 1
    assert len(client.select_calls) == 1


def test_target_can_be_temporarily_absent_during_refresh(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    error_target = _target(error=True, label="Air Care")
    normal_target = _target(error=False, label="Air Care")
    error_target["boundsInScreen"] = "30,2054,1050,2144"
    normal_target["boundsInScreen"] = "30,2054,1050,2558"
    normal_target["viewIdResourceName"] = (
        "com.samsung.android.oneconnect:id/frameLayout"
    )
    client = RecoveryClient([[], [normal_target]])

    result = _run(client, error_target)

    assert result["outcome"] == "RECOVERY_FAILED"
    assert result["reason"] == "normal_state_not_stable"
    assert result["attempt_count"] == 1
    assert len(client.select_calls) == 1


def test_normal_then_error_is_recovered_then_regressed(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = RecoveryClient(
        [
            [_target(error=False, label="Air Care")],
            [_target(error=True, label="Air Care")],
        ]
    )
    result = _run(client, _target(error=True, label="Air Care"))

    assert result["outcome"] == "RECOVERED_THEN_REGRESSED"
    assert result["reason"] == "error_state_returned_during_stability"
    assert result["attempt_count"] == 1


def test_missing_refresh_control_fails_without_action(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    target = _target(error=True, label="Air Care")
    target["children"] = [target["children"][0]]
    client = RecoveryClient()
    result = _run(client, target)

    assert result["outcome"] == "RECOVERY_FAILED"
    assert result["reason"] == "recovery_control_missing"
    assert result["attempt_count"] == 0
    assert client.select_calls == []


def test_non_actionable_refresh_control_fails_without_action(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = RecoveryClient()
    result = _run(client, _target(error=True, label="Air Care", actionable=False))

    assert result["outcome"] == "RECOVERY_FAILED"
    assert result["reason"] == "recovery_control_not_actionable"
    assert result["attempt_count"] == 0
    assert client.click_focused_calls == []


def test_unrelated_refresh_outside_target_does_not_trigger(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    target = _target(error=False, label="Air Care")
    unrelated = {
        "text": "Refresh",
        "viewIdResourceName": (
            "com.samsung.android.oneconnect:id/btTextButton"
        ),
        "clickable": True,
        "enabled": True,
        "visibleToUser": True,
        "children": [],
    }
    client = RecoveryClient()
    result = collection_flow._run_recoverable_precondition_gate(
        client=client,
        dev="SERIAL",
        tab_cfg=_cfg(),
        target_node=target,
        initial_nodes=[target, unrelated],
        wait_seconds=0.2,
    )

    assert result["outcome"] == "NO_RECOVERY_NEEDED"
    assert client.select_calls == []


def test_unrelated_korean_refresh_does_not_trigger(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    target = _target(error=False, label="Target")
    unrelated = {
        "text": "새로고침",
        "viewIdResourceName": (
            "com.samsung.android.oneconnect:id/btTextButton"
        ),
        "clickable": True,
        "enabled": True,
        "visibleToUser": True,
        "children": [],
    }
    client = RecoveryClient()
    result = collection_flow._run_recoverable_precondition_gate(
        client=client,
        dev="SERIAL",
        tab_cfg=_cfg(),
        target_node=target,
        initial_nodes=[target, unrelated],
        wait_seconds=0.2,
    )

    assert result["outcome"] == "NO_RECOVERY_NEEDED"
    assert client.click_focused_calls == []


def test_dispatch_failure_is_controlled(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = RecoveryClient(click_result=False)
    result = _run(client, _target(error=True, label="Air Care"))

    assert result["outcome"] == "RECOVERY_FAILED"
    assert result["reason"] == "recovery_action_failed"
    assert result["attempt_count"] == 1


def test_accessibility_verdict_is_not_mutated(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    client = RecoveryClient(
        [
            [_target(error=False, label="Air Care")],
            [_target(error=False, label="Air Care")],
        ]
    )
    result = _run(client, _target(error=True, label="Air Care"))

    assert result["outcome"] == "RECOVERED_STABLE"
    assert "accessibility_verdict" not in result
    assert "expected_speech" not in result


def test_attempt_count_never_exceeds_one(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    error_target = _target(error=True, label="Air Care")
    client = RecoveryClient([[error_target], [error_target]])
    result = _run(client, error_target)

    assert result["attempt_count"] <= 1
    assert len(client.select_calls) <= 1
    assert len(client.click_focused_calls) <= 1


def test_repeated_gate_call_does_not_dispatch_a_second_recovery(monkeypatch):
    monkeypatch.setattr(collection_flow.time, "sleep", lambda *_: None)
    error_target = _target(error=True, label="Air Care")
    client = RecoveryClient(
        [
            [_target(error=False, label="Air Care")],
            [_target(error=False, label="Air Care")],
        ]
    )

    first = _run(client, error_target)
    second = _run(client, error_target)

    assert first["outcome"] == "RECOVERED_STABLE"
    assert second["outcome"] == "RECOVERED_THEN_REGRESSED"
    assert second["attempt_count"] == 1
    assert len(client.select_calls) == 1
    assert len(client.click_focused_calls) == 1


def test_air_care_production_rule_is_structural_and_locale_independent():
    air_cfg = next(
        cfg for cfg in TAB_CONFIGS if cfg["scenario_id"] == "life_air_care_plugin"
    )
    rule = air_cfg["recoverable_precondition"]

    assert "com.samsung.android.oneconnect:id/service_card" in rule[
        "target_resource_ids"
    ]
    assert "com.samsung.android.oneconnect:id/containerNameLayout" in rule[
        "target_resource_ids"
    ]
    assert "com.samsung.android.oneconnect:id/frameLayout" in rule[
        "target_resource_ids"
    ]
    assert rule["error_resource_ids"] == [
        "com.samsung.android.oneconnect:id/errorMessage"
    ]
    assert rule["action_resource_ids"] == [
        "com.samsung.android.oneconnect:id/btTextButton"
    ]
    assert not any(
        localized in rule
        for localized in ("에어 케어", "Air Care", "새로고침", "Refresh")
    )


def test_xml_entry_blocks_normal_entry_when_recovery_cannot_complete(monkeypatch):
    class XmlClient:
        def __init__(self):
            self.tap_calls = []

        def scroll(self, **_kwargs):
            return True

        def tap_xy_adb(self, **kwargs):
            self.tap_calls.append(kwargs)
            return True

    target = _target(error=True, label="Air Care")
    target["boundsInScreen"] = "0,300,1080,900"
    monkeypatch.setattr(
        collection_flow,
        "_load_scrolltouch_xml_nodes",
        lambda **_kwargs: ([target], "ok"),
    )
    monkeypatch.setattr(
        collection_flow,
        "_run_recoverable_precondition_gate",
        lambda **_kwargs: {
            "outcome": "RECOVERY_FAILED",
            "reason": "error_state_remains",
        },
    )
    monkeypatch.setattr(collection_flow, "log", lambda *_args, **_kwargs: None)

    client = XmlClient()
    ok, reason = collection_flow._run_xml_scroll_search_tap(
        client=client,
        dev="SERIAL",
        tab_cfg=_cfg(),
        target=r"(?i)\bair\s*care\b",
        type_="card",
        max_scroll_search_steps=1,
        step_wait_seconds=0.2,
        transition_fast_path=False,
    )

    assert ok is False
    assert "recoverable_precondition:error_state_remains" in reason
    assert client.tap_calls == []


def test_pre_navigation_does_not_bypass_failed_recovery_with_legacy_fallback(monkeypatch):
    class PreNavigationClient:
        def __init__(self):
            self.scroll_touch_calls = []
            self.last_recoverable_precondition = {
                "outcome": "RECOVERY_FAILED",
                "reason": "normal_state_not_stable",
            }

        def scrollTouch(self, **kwargs):
            self.scroll_touch_calls.append(kwargs)
            return True

    monkeypatch.setattr(
        collection_flow,
        "_run_xml_scroll_search_tap",
        lambda *_args, **_kwargs: (False, "recoverable_precondition:normal_state_not_stable"),
    )
    client = PreNavigationClient()
    cfg = _cfg()
    cfg["pre_navigation"] = [
        {
            "action": "xml_scroll_search_tap",
            "target": "(?i)air care",
            "type": "a",
        }
    ]

    ok = collection_flow._run_pre_navigation_steps(
        client=client,
        dev="SERIAL",
        tab_cfg=cfg,
        transition_fast_path=False,
    )

    assert ok is False
    assert client.scroll_touch_calls == []
