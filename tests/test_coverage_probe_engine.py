import json
from pathlib import Path

from tb_runner import coverage_probe_engine


def _candidate(**overrides):
    base = {
        "label": "100%",
        "normalized_label": "100%",
        "scenario_id": "device_motion_sensor_plugin",
        "tab_name": "Motion Sensor",
        "view_id": "lowBattery",
        "bounds": "747,310,933,382",
        "taxonomy": "REQUIRED",
        "coverage_status": "UNKNOWN",
        "coverage_reason": "related_bounds_only",
        "probe_intent": "VERIFY_RELATED_BOUNDS",
        "probe_priority": 2,
        "probe_eligible": True,
        "probe_method_candidate": "helper_focus_in_bounds",
    }
    base.update(overrides)
    return base


def _plan(candidates):
    return {
        "schema_version": 1,
        "source": "v8_coverage_probe_plan",
        "summary": {"candidate_count": len(candidates)},
        "candidates": candidates,
    }


def _write_inventory(output_path, items):
    path = coverage_probe_engine.focusable_inventory_path(str(output_path))
    path.write_text(
        json.dumps(
            {
                "schema_version": "audit-v7-focusable-inventory-v1",
                "output_path": str(output_path),
                "count": len(items),
                "items": items,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _motion_leaf_candidate(**overrides):
    return _candidate(
        label="Motion detected",
        normalized_label="motion detected",
        view_id="",
        class_name="android.widget.TextView",
        bounds="84,577,924,685",
        **overrides,
    )


def _inventory_item(**overrides):
    base = {
        "scenario_id": "device_motion_sensor_plugin",
        "tab_name": "Motion Sensor",
        "label": "Motion sensor History Motion detected",
        "view_id": "MotionSensorCapabilityCardView",
        "bounds": "30,412,1050,727",
        "source": "helper_snapshot",
        "class_name": "android.view.View",
        "clickable": True,
        "focusable": False,
    }
    base.update(overrides)
    return base


class FakeProbeClient:
    def __init__(self, focus_results=None, scroll_results=None, focus_snapshots=None):
        self.focus_results = list(focus_results or [])
        self.scroll_results = list(scroll_results or [])
        self.focus_snapshots = list(focus_snapshots or [])
        self.focus_in_bounds_calls = []
        self.scroll_calls = []
        self.next_calls = 0
        self.smart_next_calls = 0
        self.last_merged_announcement = ""
        self.last_announcements = []

    def focus_in_bounds(self, **kwargs):
        self.focus_in_bounds_calls.append(kwargs)
        if self.focus_results:
            result = self.focus_results.pop(0)
        else:
            result = {"success": False, "detail": "no_content_candidate_in_bounds", "raw": {"success": False, "reason": "no_content_candidate_in_bounds"}}
        raw = result.get("raw", result) if isinstance(result, dict) else {}
        focused = raw.get("focused") if isinstance(raw.get("focused"), dict) else raw.get("target") if isinstance(raw.get("target"), dict) else {}
        label = str(focused.get("mergedLabel") or focused.get("talkbackLabel") or focused.get("text") or "")
        self.last_merged_announcement = label
        self.last_announcements = [label] if label else []
        return result

    def scroll(self, **kwargs):
        self.scroll_calls.append(kwargs)
        if self.scroll_results:
            return self.scroll_results.pop(0)
        return False

    def get_focus(self, **_kwargs):
        if self.focus_snapshots:
            snapshot = self.focus_snapshots.pop(0)
            speech = str(snapshot.pop("_speech", "") or "") if isinstance(snapshot, dict) else ""
            if speech:
                self.last_merged_announcement = speech
                self.last_announcements = [speech]
            return snapshot
        return {}

    def next(self, **_kwargs):
        self.next_calls += 1
        raise AssertionError("NEXT must not be used by coverage probe engine")

    def smart_next(self, **_kwargs):
        self.smart_next_calls += 1
        raise AssertionError("SMART_NEXT must not be used by coverage probe engine")


def _success_result(label="100%"):
    return {
        "success": True,
        "status": "moved",
        "detail": "content_like_focused_row",
        "raw": {
            "success": True,
            "reason": "content_like_focused_row",
            "focused": {
                "mergedLabel": label,
                "talkbackLabel": label,
                "text": label,
                "viewIdResourceName": "lowBattery",
                "boundsInScreen": {"l": 747, "t": 310, "r": 933, "b": 382},
            },
        },
    }


def _fail_result(reason="no_content_candidate_in_bounds"):
    return {
        "success": False,
        "status": "failed",
        "detail": reason,
        "raw": {"success": False, "reason": reason},
    }


def _focus_snapshot(label="100%", view_id="lowBattery", bounds=None, class_name="android.view.View", speech=""):
    bounds = bounds or {"l": 747, "t": 310, "r": 933, "b": 382}
    return {
        "mergedLabel": label,
        "talkbackLabel": label,
        "text": label,
        "viewIdResourceName": view_id,
        "className": class_name,
        "boundsInScreen": bounds,
        "_speech": speech,
    }


def test_probe_engine_disabled_by_default_does_not_attempt_focus(tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    plan_path = coverage_probe_engine.coverage_probe_plan_path(output_path)
    plan_path.write_text(json.dumps(_plan([_candidate()]), ensure_ascii=False), encoding="utf-8")
    client = FakeProbeClient(focus_results=[_success_result()])

    payload = coverage_probe_engine.maybe_execute_probe_plan_file(
        client,
        "device",
        output_path=output_path,
        env={},
    )

    assert payload is None
    assert client.focus_in_bounds_calls == []
    assert not coverage_probe_engine.coverage_probe_results_path(output_path).exists()


def test_probe_engine_enabled_calls_focus_in_bounds_for_eligible_bounds_candidate(tmp_path):
    client = FakeProbeClient(focus_results=[_success_result()])
    output_path = str(tmp_path / "talkback_compare.xlsx")

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=output_path,
        enabled=True,
    )

    assert payload["summary"]["attempted_count"] == 1
    assert payload["summary"]["original_target_count"] == 1
    assert len(client.focus_in_bounds_calls) == 1
    assert client.focus_in_bounds_calls[0]["bounds"] == "747,310,933,382"


def test_probe_engine_successful_one_shot_captures_evidence_without_scroll(tmp_path):
    client = FakeProbeClient(
        focus_results=[_success_result("100%")],
        focus_snapshots=[{"mergedLabel": "Before"}, {"mergedLabel": "100%", "viewIdResourceName": "lowBattery"}],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
    )
    result = payload["results"][0]

    assert result["probe_success"] is True
    assert result["probe_success_source"] == "HELPER_SUCCESS"
    assert result["helper_success"] is True
    assert result["late_verification_started"] is False
    assert result["attempt_count"] == 1
    assert result["scroll_attempt_count"] == 0
    assert result["captured_speech"] == "100%"
    assert result["captured_visible_text"] == "100%"
    assert result["matched_expected_label"] is True
    assert result["probe_bounds"] == "747,310,933,382"
    assert result["probe_target_strategy"] == "original_bounds"
    assert client.scroll_calls == []


def test_static_related_bounds_leaf_promotes_to_enclosing_actionable_container(tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    _write_inventory(
        output_path,
        [
            _inventory_item(label="SmartThings Plugin", view_id="primary", bounds="0,94,1080,2496", clickable=True),
            _inventory_item(),
            _inventory_item(label="Motion detected", view_id="", class_name="android.widget.TextView", bounds="84,577,924,685", clickable=False, focusable=False),
        ],
    )
    client = FakeProbeClient(focus_results=[_success_result("Motion sensor History Motion detected")])

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_motion_leaf_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=output_path,
        enabled=True,
    )
    result = payload["results"][0]

    assert client.focus_in_bounds_calls[0]["bounds"] == "30,412,1050,727"
    assert result["bounds"] == "84,577,924,685"
    assert result["probe_bounds"] == "30,412,1050,727"
    assert result["probe_target_strategy"] == "promote_to_enclosing_actionable_container"
    assert result["probe_target_source"] == "focusable_inventory"
    assert result["probe_target_view_id"] == "MotionSensorCapabilityCardView"
    assert result["probe_target_class_name"] == "android.view.View"
    assert result["probe_target_clickable"] is True
    assert payload["summary"]["promoted_target_count"] == 1


def test_helper_failure_late_focus_promotes_probe_to_success(tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    _write_inventory(output_path, [_inventory_item()])
    client = FakeProbeClient(
        focus_results=[_fail_result("focus_action_failed")],
        focus_snapshots=[
            _focus_snapshot("Before", view_id="lowBattery"),
            _focus_snapshot(
                "Motion sensor History",
                view_id="MotionSensorCapabilityCardView",
                bounds={"l": 30, "t": 412, "r": 1050, "b": 727},
            ),
        ],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_motion_leaf_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=output_path,
        enabled=True,
        late_verification_timeout_ms=0,
    )
    result = payload["results"][0]

    assert result["probe_success"] is True
    assert result["helper_success"] is False
    assert result["probe_success_source"] == "LATE_FOCUS_VERIFIED"
    assert result["late_verification_started"] is True
    assert result["late_focus_detected"] is True
    assert result["captured_visible_text"] == "Motion sensor History"
    assert result["scroll_attempt_count"] == 0


def test_helper_failure_late_speech_match_promotes_probe_to_success(tmp_path):
    client = FakeProbeClient(
        focus_results=[_fail_result("focus_action_failed")],
        focus_snapshots=[
            _focus_snapshot("Before"),
            _focus_snapshot(
                "Container",
                view_id="lowBattery",
                bounds={"l": 747, "t": 310, "r": 933, "b": 382},
                speech="Battery 100%",
            ),
        ],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
        late_verification_timeout_ms=0,
    )
    result = payload["results"][0]

    assert result["probe_success"] is True
    assert result["probe_success_source"] == "LATE_SPEECH_VERIFIED"
    assert result["late_speech_detected"] is True
    assert result["captured_speech"] == "Battery 100%"


def test_helper_failure_late_visible_text_match_promotes_probe_to_success(tmp_path):
    client = FakeProbeClient(
        focus_results=[_fail_result("focus_action_failed")],
        focus_snapshots=[
            _focus_snapshot("Before"),
            _focus_snapshot(
                "100%",
                view_id="lowBattery",
                bounds={"l": 747, "t": 310, "r": 933, "b": 382},
            ),
        ],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
        late_verification_timeout_ms=0,
    )
    result = payload["results"][0]

    assert result["probe_success"] is True
    assert result["probe_success_source"] == "LATE_FOCUS_VERIFIED"
    assert result["late_visible_text_detected"] is True


def test_helper_failure_without_late_evidence_remains_failed(tmp_path):
    client = FakeProbeClient(
        focus_results=[_fail_result("focus_action_failed")],
        focus_snapshots=[
            _focus_snapshot("Before"),
            _focus_snapshot("Unrelated", view_id="other", bounds={"l": 0, "t": 0, "r": 20, "b": 20}),
        ],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
        max_scrolls=0,
        late_verification_timeout_ms=0,
    )
    result = payload["results"][0]

    assert result["probe_success"] is False
    assert result["probe_success_source"] == "FAILED"
    assert result["late_verification_started"] is True
    assert result["late_focus_detected"] is False


def test_late_verification_timeout_without_evidence_remains_failed(tmp_path):
    client = FakeProbeClient(
        focus_results=[_fail_result("focus_action_failed")],
        focus_snapshots=[_focus_snapshot("Before")],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
        max_scrolls=0,
        late_verification_timeout_ms=1,
        late_verification_poll_ms=1,
    )
    result = payload["results"][0]

    assert result["probe_success"] is False
    assert result["probe_success_source"] == "FAILED"
    assert result["late_verification_elapsed_ms"] >= 1


def test_promotion_chooses_smallest_non_fullscreen_actionable_container(tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    _write_inventory(
        output_path,
        [
            _inventory_item(label="SmartThings Plugin", view_id="primary", bounds="0,94,1080,2496", clickable=True),
            _inventory_item(label="Large panel", view_id="largePanel", bounds="20,350,1060,1000", clickable=True),
            _inventory_item(label="Motion sensor History Motion detected", view_id="MotionSensorCapabilityCardView", bounds="30,412,1050,727", clickable=True),
            _inventory_item(label="Motion detected", view_id="", class_name="android.widget.TextView", bounds="84,577,924,685", clickable=False, focusable=False),
        ],
    )
    client = FakeProbeClient(focus_results=[_success_result("Motion sensor History Motion detected")])

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_motion_leaf_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=output_path,
        enabled=True,
    )

    assert client.focus_in_bounds_calls[0]["bounds"] == "30,412,1050,727"
    assert payload["results"][0]["probe_target_view_id"] == "MotionSensorCapabilityCardView"


def test_promotion_does_not_select_fullscreen_root_when_card_exists(tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    _write_inventory(
        output_path,
        [
            _inventory_item(label="SmartThings Plugin", view_id="primary", bounds="0,94,1080,2496", clickable=True),
            _inventory_item(view_id="MotionSensorCapabilityCardView", bounds="30,412,1050,727", clickable=True),
        ],
    )
    client = FakeProbeClient(focus_results=[_success_result("Motion sensor History Motion detected")])

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_motion_leaf_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=output_path,
        enabled=True,
    )

    assert payload["results"][0]["probe_target_view_id"] == "MotionSensorCapabilityCardView"
    assert payload["results"][0]["probe_bounds"] != "0,94,1080,2496"


def test_promotion_keeps_original_bounds_when_no_suitable_container_exists(tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    _write_inventory(
        output_path,
        [
            _inventory_item(label="SmartThings Plugin", view_id="primary", bounds="0,94,1080,2496", clickable=True),
            _inventory_item(label="Motion detected", view_id="", class_name="android.widget.TextView", bounds="84,577,924,685", clickable=False, focusable=False),
        ],
    )
    client = FakeProbeClient(focus_results=[_success_result("Motion detected")])

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_motion_leaf_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=output_path,
        enabled=True,
    )

    assert client.focus_in_bounds_calls[0]["bounds"] == "84,577,924,685"
    assert payload["results"][0]["probe_target_strategy"] == "original_bounds"
    assert payload["summary"]["original_target_count"] == 1


def test_non_related_bounds_candidate_is_not_promoted(tmp_path):
    output_path = str(tmp_path / "talkback_compare.xlsx")
    _write_inventory(output_path, [_inventory_item()])
    client = FakeProbeClient(focus_results=[_success_result("Motion detected")])

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_motion_leaf_candidate(probe_intent="VERIFY_MISSING_NODE", coverage_status="MISSED", coverage_reason="no_matching_row")]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=output_path,
        enabled=True,
    )

    assert client.focus_in_bounds_calls[0]["bounds"] == "84,577,924,685"
    assert payload["results"][0]["probe_target_strategy"] == "original_bounds"


def test_probe_engine_scrolls_and_retries_after_no_content_candidate(tmp_path):
    client = FakeProbeClient(
        focus_results=[_fail_result("no_content_candidate_in_bounds"), _success_result("100%")],
        scroll_results=[True],
        focus_snapshots=[{"mergedLabel": "Before"}, {"mergedLabel": "100%"}],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
    )
    result = payload["results"][0]

    assert result["probe_success"] is True
    assert result["attempt_count"] == 2
    assert result["scroll_attempt_count"] == 1
    assert len(client.focus_in_bounds_calls) == 2
    assert len(client.scroll_calls) == 1


def test_probe_engine_records_failure_when_scroll_fails(tmp_path):
    client = FakeProbeClient(
        focus_results=[_fail_result("no_content_candidate_in_bounds")],
        scroll_results=[False],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
    )
    result = payload["results"][0]

    assert result["probe_success"] is False
    assert result["attempt_count"] == 1
    assert result["scroll_attempt_count"] == 1
    assert result["failure_reason"] == "no_content_candidate_in_bounds_scroll_failed"


def test_probe_engine_caps_max_retry(tmp_path):
    client = FakeProbeClient(
        focus_results=[
            _fail_result("no_content_candidate_in_bounds"),
            _fail_result("no_content_candidate_in_bounds"),
            _fail_result("no_content_candidate_in_bounds"),
        ],
        scroll_results=[True, True],
    )

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
        max_attempts=3,
        max_scrolls=2,
    )
    result = payload["results"][0]

    assert result["probe_success"] is False
    assert result["attempt_count"] == 3
    assert result["scroll_attempt_count"] == 2
    assert result["failure_reason"] == "no_content_candidate_in_bounds_after_scroll_retry"


def test_probe_engine_skips_view_id_only_candidate(tmp_path):
    client = FakeProbeClient(focus_results=[_success_result()])

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate(bounds="", probe_method_candidate="unresolved_view_id_only")]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
    )
    result = payload["results"][0]

    assert result["attempted"] is False
    assert result["failure_reason"] == "unsupported_probe_method"
    assert client.focus_in_bounds_calls == []


def test_probe_engine_skips_ineligible_candidate(tmp_path):
    client = FakeProbeClient(focus_results=[_success_result()])

    payload = coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate(probe_eligible=False, probe_method_candidate="ineligible_no_target", bounds="")]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
    )
    result = payload["results"][0]

    assert result["attempted"] is False
    assert result["failure_reason"] == "probe_ineligible"
    assert client.focus_in_bounds_calls == []


def test_probe_engine_does_not_use_next_or_smart_next(tmp_path):
    client = FakeProbeClient(focus_results=[_success_result()])

    coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
    )

    assert client.next_calls == 0
    assert client.smart_next_calls == 0


def test_probe_engine_does_not_mutate_rows_or_create_xlsx_rows(tmp_path):
    client = FakeProbeClient(focus_results=[_success_result()])
    rows = [{"scenario_id": "device_motion_sensor_plugin", "final_result": "PASS"}]

    coverage_probe_engine.build_probe_results_payload(
        client,
        "device",
        _plan([_candidate()]),
        probe_plan_path=str(tmp_path / "plan.json"),
        output_path=str(tmp_path / "talkback_compare.xlsx"),
        enabled=True,
    )

    assert rows == [{"scenario_id": "device_motion_sensor_plugin", "final_result": "PASS"}]
    assert not list(Path(tmp_path).glob("*.xlsx"))
