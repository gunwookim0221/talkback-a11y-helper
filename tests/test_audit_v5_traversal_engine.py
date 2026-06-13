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
