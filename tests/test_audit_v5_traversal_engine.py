from pathlib import Path

from tools import audit_v5_traversal_engine as audit


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _xml(label: str, rid: str = "") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<hierarchy>
  <node package="com.samsung.android.oneconnect"
        text="{label}"
        content-desc=""
        resource-id="{rid}"
        class="android.widget.TextView"
        bounds="[10,20][200,80]"
        focusable="true"
        clickable="true" />
</hierarchy>
"""


def test_build_report_reconstructs_visit_and_activation_fail(tmp_path):
    scenario_dir = tmp_path / "life_family_care_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "life_family_care_plugin" / "xml_dumps"
    _write_text(xml_dir / "000_step_001_entry.xml", _xml("EventsButton", "eventsbutton"))
    _write_text(xml_dir / "001_step_002_viewport_exhausted.xml", _xml("Profile", "profile"))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "\n".join(
            [
                "[10:00:00] [STEP][candidate_priority] selected='EventsButton' reason='representative_content_preferred'",
                "[10:00:01] [STEP][local_tab_target_activate] target='EventsButton' method='tap_bounds'",
                "[10:00:02] [STEP][local_tab_target_activate_fail] target='EventsButton' reason='no_match_after_all_methods'",
                "[10:00:03] [STEP] END step=2 visible='Profile' speech='Profile'",
            ]
        ),
    )

    report = audit.build_report(scenario_dir)

    assert report["metrics"]["discovered_count"] == 2
    assert report["metrics"]["visited_count"] == 1
    assert report["metrics"]["missed_count"] == 1
    assert report["metrics"]["activation_attempt_count"] == 1
    assert report["metrics"]["activation_success_count"] == 0
    assert report["root_cause_summary"]["ACTIVATION_FAIL"] == 1

    missed = [ledger for ledger in report["candidate_ledgers"] if ledger["missed"]]
    assert missed[0]["stable_label"] == "EventsButton"
    assert missed[0]["root_cause"] == "ACTIVATION_FAIL"


def test_markdown_summary_contains_top_missed_candidates(tmp_path):
    scenario_dir = tmp_path / "life_home_care_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "life_home_care_plugin" / "xml_dumps"
    _write_text(xml_dir / "000_step_001_entry.xml", _xml("Usage guide", "usage"))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "[10:00:00] [STEP][section_header_deferred] candidates='Usage guide' reason='content_candidates_present'",
    )

    report = audit.build_report(scenario_dir)
    markdown = audit.render_markdown(report)

    assert "## Top Missed Candidates" in markdown
    assert "`Usage guide`" in markdown
    assert "root_cause=CANDIDATE_DISCARDED" in markdown


def test_local_tab_recover_compound_candidates_and_active_visit(tmp_path):
    scenario_dir = tmp_path / "life_family_care_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "life_family_care_plugin" / "xml_dumps"
    _write_text(xml_dir / "000_step_001_entry.xml", _xml("LocationButton"))
    _write_text(xml_dir / "001_step_002_entry.xml", _xml("EventsButton"))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "[10:00:00] [STEP][local_tab_recover] reason='state_missing_but_dump_strip_seen' "
        "candidates='LocationButton Location|EventsButton Events' active='LocationButton Location'",
    )

    report = audit.build_report(scenario_dir)
    by_label = {ledger["stable_label"]: ledger for ledger in report["candidate_ledgers"]}

    assert by_label["LocationButton"]["visited"] is True
    assert by_label["LocationButton"]["missed"] is False
    assert by_label["EventsButton"]["missed"] is True
    assert by_label["EventsButton"]["root_cause"] == "BOTTOM_STRIP_MISS"


def test_chrome_penalty_becomes_policy_deprioritized(tmp_path):
    scenario_dir = tmp_path / "life_family_care_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "life_family_care_plugin" / "xml_dumps"
    _write_text(xml_dir / "000_step_001_entry.xml", _xml("Add family member", "invite_member"))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "[10:00:00] [STEP][chrome_penalty] deprioritized='Navigate up|Family Care|Add family member|More options' "
        "reason='top_chrome_during_content_phase'",
    )

    report = audit.build_report(scenario_dir)
    missed = [ledger for ledger in report["candidate_ledgers"] if ledger["missed"]]

    assert missed[0]["stable_label"] == "Add family member"
    assert missed[0]["root_cause"] == "POLICY_DEPRIORITIZED"


def test_compound_metric_row_marks_leaf_candidates_visited(tmp_path):
    scenario_dir = tmp_path / "life_family_care_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "life_family_care_plugin" / "xml_dumps"
    for index, label in enumerate(["Today", "Avg (week)", "6000", "12", "3", "32"]):
        _write_text(xml_dir / f"{index:03d}_step_001_entry.xml", _xml(label))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "\n".join(
            [
                "[10:00:00] [STEP] END step=1 visible='Today 4 h 32 m Avg (week) 3 12 03:12' "
                "speech='Today 4 h 32 m Avg (week) 3 12 03:12'",
                "[10:00:01] [STEP] END step=2 visible='0 steps / 6000 %' speech='0 steps / 6000 %'",
            ]
        ),
    )

    report = audit.build_report(scenario_dir)
    by_label = {ledger["stable_label"]: ledger for ledger in report["candidate_ledgers"]}

    for label in ["Today", "Avg (week)", "6000", "12", "3", "32"]:
        assert by_label[label]["visited"] is True
        assert by_label[label]["missed"] is False


def test_numeric_leaf_does_not_match_non_metric_row(tmp_path):
    scenario_dir = tmp_path / "life_family_care_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "life_family_care_plugin" / "xml_dumps"
    _write_text(xml_dir / "000_step_001_entry.xml", _xml("12"))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "[10:00:00] [STEP] END step=1 visible='Room 12' speech='Room 12'",
    )

    report = audit.build_report(scenario_dir)
    ledger = next(ledger for ledger in report["candidate_ledgers"] if ledger["stable_label"] == "12")

    assert ledger["visited"] is False
    assert ledger["missed"] is True
    assert ledger["root_cause"] == "UNKNOWN"


def test_focus_realign_record_marks_composite_leaf_candidates_visited(tmp_path):
    scenario_dir = tmp_path / "device_door_lock_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "device_door_lock_plugin" / "xml_dumps"
    _write_text(xml_dir / "000_step_001_entry.xml", _xml("Locked"))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "[10:00:00] [STEP][focus_realign_record] target='Lock state Locked switch' "
        "signature='lockcapabilitycardview||bounds||lock state locked switch' phase='Controls'",
    )

    report = audit.build_report(scenario_dir)
    ledger = next(ledger for ledger in report["candidate_ledgers"] if ledger["stable_label"] == "Locked")

    assert ledger["visited"] is True
    assert ledger["missed"] is False
    assert ledger["root_cause"] is None


def test_chrome_excluded_candidates_become_discarded(tmp_path):
    scenario_dir = tmp_path / "device_motion_sensor_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "device_motion_sensor_plugin" / "xml_dumps"
    _write_text(xml_dir / "000_step_001_entry.xml", _xml("Add routine"))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "[10:00:00] [STEP][viewport_exhausted_eval] all_candidates='none' selection_candidates='none' "
        "representative_candidates='none' chrome_excluded='Navigate up|Plugin title|Add routine|More options' "
        "result=true reason='no_representative_candidates'",
    )

    report = audit.build_report(scenario_dir)
    ledger = next(ledger for ledger in report["candidate_ledgers"] if ledger["stable_label"] == "Add routine")

    assert ledger["visited"] is False
    assert ledger["missed"] is True
    assert ledger["root_cause"] == "CANDIDATE_DISCARDED"


def test_local_tab_content_traversal_fail_demotes_commit_visit(tmp_path):
    scenario_dir = tmp_path / "device_motion_sensor_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "device_motion_sensor_plugin" / "xml_dumps"
    _write_text(xml_dir / "000_step_001_entry.xml", _xml("Controls", "control"))
    _write_text(xml_dir / "001_step_002_entry.xml", _xml("Routines", "routine"))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "\n".join(
            [
                "[10:00:00] [STEP][local_tab_target_activate] target='Controls' method='tap_bounds_center'",
                "[10:00:01] [STEP][local_tab_target_activate_success] target='Controls' matched_by='bounds'",
                "[10:00:02] [STEP][local_tab_commit] active='Controls' reason='target_activation_success'",
                "[10:00:03] [STEP][local_tab_target_activate] target='Routines' method='tap_bounds_center'",
                "[10:00:04] [STEP][local_tab_target_activate_success] target='Routines' matched_by='rid'",
                "[10:00:05] [STEP][local_tab_commit] active='Routines' reason='target_activation_success'",
                "[10:00:06] [STEP][local_tab_content_traversal_fail] active='Routines' "
                "reason='content_not_entered_after_tab_activation' visible='History' "
                "focus_confidence='high' content_entered=false content_candidate_visited=false",
            ]
        ),
    )

    report = audit.build_report(scenario_dir)
    by_label = {ledger["stable_label"]: ledger for ledger in report["candidate_ledgers"]}

    assert by_label["Controls"]["visited"] is True
    assert by_label["Controls"]["missed"] is False
    assert by_label["Routines"]["selected"] is True
    assert by_label["Routines"]["activation_attempted"] is True
    assert by_label["Routines"]["activation_succeeded"] is True
    assert by_label["Routines"]["local_tab_transition_succeeded"] is True
    assert by_label["Routines"]["visited"] is False
    assert by_label["Routines"]["missed"] is True
    assert by_label["Routines"]["root_cause"] == "LOCAL_TAB_MISS"
    assert report["root_cause_summary"]["LOCAL_TAB_MISS"] == 1

    fail_events = [
        event
        for event in report["event_samples"]
        if event["event_type"] == "LOCAL_TAB_CONTENT_TRAVERSAL_FAIL"
    ]
    assert len(fail_events) == 1
    assert fail_events[0]["stable_label"] == "Routines"
    assert fail_events[0]["visible_label"] == "History"
    assert fail_events[0]["reason"] == "content_not_entered_after_tab_activation"
    assert fail_events[0]["evidence"]["focus_confidence"] == "high"
    assert fail_events[0]["evidence"]["content_entered"] == "false"
    assert fail_events[0]["evidence"]["content_candidate_visited"] == "false"


def test_local_tab_content_traversal_fail_only_affects_matching_tab(tmp_path):
    scenario_dir = tmp_path / "device_motion_sensor_plugin"
    xml_dir = scenario_dir / "talkback_compare_1" / "device_motion_sensor_plugin" / "xml_dumps"
    for label, rid in [("Controls", "control"), ("Routines", "routine"), ("History", "history")]:
        _write_text(xml_dir / f"{rid}.xml", _xml(label, rid))
    _write_text(
        scenario_dir / "talkback_compare_1.normal.log",
        "\n".join(
            [
                "[10:00:00] [STEP][local_tab_commit] active='Controls' reason='target_activation_success'",
                "[10:00:01] [STEP][local_tab_commit] active='Routines' reason='target_activation_success'",
                "[10:00:02] [STEP][local_tab_content_traversal_fail] active='Routines' "
                "reason='content_not_entered_after_tab_activation' visible='History'",
                "[10:00:03] [STEP][local_tab_commit] active='History' reason='target_activation_success'",
                "[10:00:04] [STEP][local_tab_content_traversal_fail] active='History' "
                "reason='content_not_entered_after_tab_activation' visible='History'",
            ]
        ),
    )

    report = audit.build_report(scenario_dir)
    by_label = {ledger["stable_label"]: ledger for ledger in report["candidate_ledgers"]}

    assert by_label["Controls"]["visited"] is True
    assert by_label["Controls"]["missed"] is False
    assert by_label["Routines"]["visited"] is False
    assert by_label["Routines"]["root_cause"] == "LOCAL_TAB_MISS"
    assert by_label["History"]["visited"] is False
    assert by_label["History"]["root_cause"] == "LOCAL_TAB_MISS"
    assert report["root_cause_summary"]["LOCAL_TAB_MISS"] == 2
