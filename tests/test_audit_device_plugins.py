import pytest
from pathlib import Path
import json
from unittest.mock import patch
import tempfile
import sys
import os
from tools.audit_device_plugins import parse_run_results, evaluate_scenario, parse_summary_json, main
from tools.audit_xml_candidates import extract_xml_candidates
from tools.audit_xml_coverage import calculate_xml_coverage, normalize_coverage_label
from tools.audit_xml_filters import classify_xml_candidate

@pytest.fixture
def mock_log_3_tabs():
    return """
[INVENTORY] found=true
[STEP] kind='local_tab' source='...' label='Controls'
[STEP] kind='local_tab' source='...' label='Routines'
[STEP] kind='local_tab' source='...' label='History'
[STEP][local_tab_transition_success] target='Controls'
[STEP][local_tab_transition_success] target='Routines'
[STEP][local_tab_transition_success] target='History'
[STEP][enter_device_card_success] target='Motion Sensor'
"""

@pytest.fixture
def mock_log_2_tabs_missed_1():
    return """
[INVENTORY] found=true
[STEP] kind='local_tab' source='...' label='Controls'
[STEP] kind='local_tab' source='...' label='History'
[STEP][local_tab_transition_success] target='Controls'
[STEP][enter_device_card_success] target='Motion Sensor'
"""

@pytest.fixture
def mock_log_1_tab():
    return """
[INVENTORY] found=true
[STEP] kind='local_tab' source='...' label='Controls'
[STEP][local_tab_transition_success] target='Controls'
[STEP][enter_device_card_success] target='TV'
"""

@pytest.fixture
def mock_log_status_excluded():
    return """
[INVENTORY] found=true
[STEP] kind='local_tab' source='...' label='Controls'
[STEP][local_tab_transition_success] target='Controls'
[STEP][enter_device_card_success] target='Motion Sensor'
[STEP][viewport_exhausted_eval] status_excluded='No motion' chrome_excluded='none'
"""

@pytest.fixture
def mock_log_routines_boundary():
    return """
[INVENTORY] found=true
[STEP] kind='local_tab' source='...' label='Controls'
[STEP][local_tab_transition_success] target='Controls'
[STEP][enter_device_card_success] target='Motion Sensor'
[PLUGIN_BOUNDARY][global_nav_reached] label='Routines | Routines'
"""
def test_audit_3_tabs_pass(mock_log_3_tabs):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.normal.log"
        log_file.write_text(mock_log_3_tabs)
        
        log_data = parse_run_results(log_file, Path("nonexistent"))
        # Mocking the tab_stats since we don't have xlsx
        for t in ["Controls", "Routines", "History"]:
            log_data["tab_stats"][t] = {"viewport_exhausted": True, "unique_visible_labels": 1, "visible_labels_set": {"dummy"}}
            
        assert len(log_data["detected_tabs"]) == 3
        assert len(log_data["visited_tabs"]) == 3
        
        summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "none"}]}
        report = evaluate_scenario("test_plugin", summary, log_data)
        
        assert report["verdict"] == "PASS"

def test_audit_2_tabs_missed_1(mock_log_2_tabs_missed_1):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.normal.log"
        log_file.write_text(mock_log_2_tabs_missed_1)
        
        log_data = parse_run_results(log_file, Path("nonexistent"))
        log_data["tab_stats"]["Controls"] = {"viewport_exhausted": True, "unique_visible_labels": 1, "visible_labels_set": {"dummy"}}

        assert len(log_data["detected_tabs"]) == 2
        assert len(log_data["visited_tabs"]) == 1
        
        summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "none"}]}
        report = evaluate_scenario("test_plugin", summary, log_data)
        
        assert report["verdict"] == "REVIEW"
        assert "Missed tabs: History" in report["reason"]

def test_audit_1_tab_pass(mock_log_1_tab):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.normal.log"
        log_file.write_text(mock_log_1_tab)
        
        log_data = parse_run_results(log_file, Path("nonexistent"))
        log_data["tab_stats"]["Controls"] = {"viewport_exhausted": True, "unique_visible_labels": 1, "visible_labels_set": {"dummy"}}

        assert len(log_data["detected_tabs"]) == 1
        assert len(log_data["visited_tabs"]) == 1
        
        summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "none"}]}
        report = evaluate_scenario("test_plugin", summary, log_data)
        
        assert report["verdict"] == "PASS"

def test_audit_status_excluded_review(mock_log_status_excluded):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.normal.log"
        log_file.write_text(mock_log_status_excluded)
        
        log_data = parse_run_results(log_file, Path("nonexistent"))
        log_data["tab_stats"]["Controls"] = {"viewport_exhausted": True, "unique_visible_labels": 1, "visible_labels_set": {"dummy"}}

        assert "No motion" in log_data["value_exclusion_warnings"]
        
        summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "none"}]}
        report = evaluate_scenario("test_plugin", summary, log_data)
        
        assert report["verdict"] == "REVIEW"
        assert "Sensor values excluded" in report["reason"]

def test_audit_routines_boundary_review(mock_log_routines_boundary):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.normal.log"
        log_file.write_text(mock_log_routines_boundary)
        
        log_data = parse_run_results(log_file, Path("nonexistent"))
        log_data["tab_stats"]["Controls"] = {"viewport_exhausted": True, "unique_visible_labels": 1, "visible_labels_set": {"dummy"}}

        
        summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "plugin_boundary_global_nav"}]}
        report = evaluate_scenario("test_plugin", summary, log_data)
        
        assert report["verdict"] == "REVIEW"
        assert "global_nav_reached routines" in report["reason"]

def test_target_exists_but_not_available():
    log_data = {
        "detected_tabs": [], "visited_tabs": [], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": []
    }
    summary = {"scenarios": [{"id": "test_plugin", "availability_status": "not_available"}]}
    
    report = evaluate_scenario("test_plugin", summary, log_data)
    assert report["verdict"] == "FAIL"
    assert "Target entered but exited with not_available" in report["reason"]

def test_target_not_exists_and_not_available():
    log_data = {
        "detected_tabs": [], "visited_tabs": [], "preflight_fail": False, "crash": False,
        "target_entered": None, "inventory_found": False,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": []
    }
    summary = {"scenarios": [{"id": "test_plugin", "availability_status": "not_available"}]}
    
    report = evaluate_scenario("test_plugin", summary, log_data)
    assert report["verdict"] == "PASS_NOT_AVAILABLE"

def test_preflight_fail():
    log_data = {
        "detected_tabs": [], "visited_tabs": [], "preflight_fail": True, "crash": False,
        "target_entered": None, "inventory_found": False,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": []
    }
    summary = {"scenarios": [{"id": "test_plugin"}]}
    
    report = evaluate_scenario("test_plugin", summary, log_data)
    assert report["verdict"] == "ENVIRONMENT_ERROR"
    assert "Preflight failed" in report["reason"]

@patch("subprocess.run")
def test_main_cli(mock_run):
    import sys
    with tempfile.TemporaryDirectory() as tmpdir:
        test_args = ["audit_device_plugins.py", "--scenarios", "test_plugin", "--output-dir", tmpdir, "--dry-run"]
        with patch.object(sys, 'argv', test_args):
            main()
        
        # Verify reports were created
        assert (Path(tmpdir) / "audit_report.json").exists()
        assert (Path(tmpdir) / "audit_report.csv").exists()
        assert (Path(tmpdir) / "audit_report.md").exists()
        
        report_json = json.loads((Path(tmpdir) / "audit_report.json").read_text(encoding="utf-8"))
        assert len(report_json) == 1
        assert report_json[0]["scenario_id"] == "test_plugin"
        assert report_json[0]["verdict"] == "FAIL"  # Because no logs were found


def test_parse_active_tabs():
    log_content = '''[21:38:49] [STEP][local_tab_active] tabs='Controls|Routines|History' active='Controls' reason='current_row_member_match'
[21:38:57] [LIFECYCLE] step=2 kind='local_tab' source='bottom_strip_candidate' confidence='high' label='Controls'
[21:39:11] [STEP][local_tab_transition_success] target='Routines'
'''
    import tempfile
    from pathlib import Path
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
        f.write(log_content)
        temp_name = f.name
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from tools.audit_device_plugins import parse_run_results
        log_data = parse_run_results(Path(temp_name), Path("nonexistent"))
        assert "Controls" in log_data["visited_tabs"], "Active tab should be added to visited_tabs"
        assert "Routines" in log_data["visited_tabs"]
        assert "Controls" in log_data["detected_tabs"]
    finally:
        os.remove(temp_name)

def test_lifecycle_local_tab_content_label_not_detected_as_tab(tmp_path):
    log_file = tmp_path / "test.normal.log"
    log_file.write_text(
        """[STEP][local_tab_active] tabs='Controls|Routines|History' active='Controls' reason='current_row_member_match'
[LIFECYCLE] step=5 kind='local_tab' source='bottom_strip_candidate' confidence='high' label='SmartThings Plugin'
[STEP][local_tab_transition_success] target='Routines'
""",
        encoding="utf-8",
    )

    log_data = parse_run_results(log_file, Path("nonexistent"))

    assert log_data["detected_tabs"] == ["Controls", "Routines", "History"]
    assert "SmartThings Plugin" not in log_data["detected_tabs"]

def test_tab_visited_not_exhausted():
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {"Controls": {"viewport_exhausted": False, "representative_exhausted": False, "unique_visible_labels": 2}}
    }
    summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none"}]}
    report = evaluate_scenario("test_plugin", summary, log_data)
    assert report["verdict"] == "REVIEW"
    assert "Controls not exhausted" in report["reason"]

def test_all_tabs_visited_but_controls_missing_labels():
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {"Controls": {"viewport_exhausted": True, "representative_exhausted": False, "unique_visible_labels": 0}}
    }
    summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none"}]}
    report = evaluate_scenario("test_plugin", summary, log_data)
    assert report["verdict"] == "REVIEW"
    assert "Controls has no visible labels" in report["reason"]

def test_repeat_no_progress_before_all_tabs_exhausted():
    log_data = {
        "detected_tabs": ["Controls", "Routines"], "visited_tabs": ["Controls", "Routines"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": ["repeat_no_progress"],
        "tab_stats": {
            "Controls": {"viewport_exhausted": True, "unique_visible_labels": 1},
            "Routines": {"viewport_exhausted": False, "unique_visible_labels": 1}
        }
    }
    summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "repeat_no_progress"}]}
    report = evaluate_scenario("test_plugin", summary, log_data)
    assert report["verdict"] == "REVIEW"
    assert "repeat_no_progress" in report["reason"]
    assert "not exhausted" in report["reason"]

def test_motion_sensor_missing_battery():
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {
            "Controls": {"viewport_exhausted": True, "unique_visible_labels": 2, "visible_labels_set": {"Motion sensor", "Vibration sensor"}}
        }
    }
    summary = {"scenarios": [{"id": "device_motion_sensor_plugin", "availability_status": "none"}]}
    report = evaluate_scenario("device_motion_sensor_plugin", summary, log_data)
    assert report["verdict"] == "REVIEW"
    assert "missing required content" in report["reason"]
    assert "Battery" in report["missing_required_content"]

def test_motion_sensor_content_complete():
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {
            "Controls": {"viewport_exhausted": True, "unique_visible_labels": 5, "visible_labels_set": {"Motion sensor", "Vibration sensor", "25 °C", "95%"}}
        }
    }
    summary = {"scenarios": [{"id": "device_motion_sensor_plugin", "availability_status": "none"}]}
    report = evaluate_scenario("device_motion_sensor_plugin", summary, log_data)
    assert report["verdict"] == "PASS"

def test_xml_parser_extracts_candidate_fields(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    (xml_dir / "000_step_001_entry.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node text="Motion sensor" content-desc="Motion status" resource-id="com.samsung.android.oneconnect:id/status" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[1,2][3,4]" />
</hierarchy>
""",
        encoding="utf-8",
    )

    summary = extract_xml_candidates(xml_dir)

    assert summary["xml_dump_count"] == 1
    assert summary["xml_candidate_count"] == 1
    candidate = summary["xml_candidates"][0]
    assert candidate["text"] == "Motion sensor"
    assert candidate["content_desc"] == "Motion status"
    assert candidate["resource_id"] == "com.samsung.android.oneconnect:id/status"
    assert candidate["class"] == "android.widget.TextView"
    assert candidate["bounds"] == "[1,2][3,4]"
    assert candidate["focusable"] == ""
    assert candidate["clickable"] == ""

def test_xml_parser_deduplicates_duplicate_nodes(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    duplicate = '<node text="Battery" content-desc="" resource-id="battery" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[10,20][30,40]" />'
    (xml_dir / "000_step_001_entry.xml").write_text(f"<hierarchy>{duplicate}{duplicate}</hierarchy>", encoding="utf-8")

    summary = extract_xml_candidates(xml_dir)

    assert summary["xml_dump_count"] == 1
    assert summary["xml_candidate_count"] == 1
    assert summary["xml_unique_label_count"] == 1
    assert summary["merged_candidate_count"] == 1

def test_xml_candidate_merge_collapses_label_across_dumps_and_tracks_tabs(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    (xml_dir / "000_step_001_entry.xml").write_text(
        """<hierarchy>
  <node text="Battery" resource-id="battery_a" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[1,2][3,4]" />
</hierarchy>""",
        encoding="utf-8",
    )
    (xml_dir / "001_step_004_local_tab_transition_Controls.xml").write_text(
        """<hierarchy>
  <node text="Battery" resource-id="battery_b" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[5,6][7,8]" />
</hierarchy>""",
        encoding="utf-8",
    )
    (xml_dir / "002_step_007_local_tab_transition_Routines.xml").write_text(
        """<hierarchy>
  <node text="Battery" resource-id="battery_c" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[9,10][11,12]" />
</hierarchy>""",
        encoding="utf-8",
    )

    summary = extract_xml_candidates(xml_dir)
    battery = next(candidate for candidate in summary["merged_candidates"] if candidate["label"] == "Battery")

    assert summary["xml_candidate_count"] == 3
    assert summary["merged_candidate_count"] == 1
    assert battery["tabs"] == ["Controls", "Routines", "entry"]
    assert battery["xml_dump_count"] == 3
    assert "Controls" in summary["candidate_tab_distribution"]
    assert "Battery" in summary["candidate_source_summary"]

def test_xml_candidate_classification_keeps_merged_count_without_filtering(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    (xml_dir / "000_step_001_entry.xml").write_text(
        """<hierarchy>
  <node text="Motion sensor" resource-id="motion" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[1,2][3,4]" />
  <node text="Navigate up" resource-id="back" class="android.widget.Button" package="com.samsung.android.oneconnect" bounds="[5,6][7,8]" />
  <node text="SmartThings Plugin" resource-id="plugin_title" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[9,10][11,12]" />
</hierarchy>""",
        encoding="utf-8",
    )

    summary = extract_xml_candidates(xml_dir)
    by_label = {candidate["label"]: candidate for candidate in summary["merged_candidates"]}

    assert summary["merged_candidate_count"] == 3
    assert by_label["Motion sensor"]["classification"] == "KEEP"
    assert by_label["Navigate up"]["classification"] == "EXCLUDE"
    assert by_label["SmartThings Plugin"]["classification"] == "REVIEW"
    assert summary["candidate_classification_summary"] == {"KEEP": 1, "REVIEW": 1, "EXCLUDE": 1}
    assert "Motion sensor" in summary["keep_candidates_sample"]
    assert "SmartThings Plugin" in summary["review_candidates_sample"]
    assert "Navigate up" in summary["exclude_candidates_sample"]

def test_xml_candidate_policy_diagnostics_do_not_change_classification(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    (xml_dir / "000_step_001_local_tab_transition_History.xml").write_text(
        """<hierarchy>
  <node text="No history" resource-id="" class="android.widget.TextView" package="com.samsung.android.oneconnect" focusable="false" clickable="false" bounds="[1,2][3,4]" />
  <node text="Add routine" resource-id="ADDROUTINE" class="android.widget.Button" package="com.samsung.android.oneconnect" focusable="true" clickable="true" bounds="[5,6][7,8]" />
  <node text="Motion detected" resource-id="" class="android.widget.TextView" package="com.samsung.android.oneconnect" focusable="false" clickable="false" bounds="[9,10][11,12]" />
  <node text="Navigate up" resource-id="back" class="android.widget.Button" package="com.samsung.android.oneconnect" bounds="[13,14][15,16]" />
</hierarchy>""",
        encoding="utf-8",
    )

    summary = extract_xml_candidates(xml_dir)
    by_label = {candidate["label"]: candidate for candidate in summary["merged_candidates"]}

    assert summary["candidate_classification_summary"] == {"KEEP": 3, "REVIEW": 0, "EXCLUDE": 1}
    assert by_label["No history"]["classification"] == "KEEP"
    assert by_label["No history"]["candidate_type"] == "EMPTY_STATE"
    assert by_label["No history"]["policy_recommendation"] == "REVIEW"
    assert by_label["Add routine"]["classification"] == "KEEP"
    assert by_label["Add routine"]["candidate_type"] == "ACTIONABLE"
    assert by_label["Add routine"]["policy_recommendation"] == "REVIEW"
    assert by_label["Motion detected"]["classification"] == "KEEP"
    assert by_label["Motion detected"]["candidate_type"] == "STATUS"
    assert by_label["Motion detected"]["policy_recommendation"] == "KEEP"
    assert by_label["Navigate up"]["classification"] == "EXCLUDE"
    assert by_label["Navigate up"]["candidate_type"] == "CHROME"
    assert summary["candidate_policy_recommendation_summary"] == {"KEEP": 1, "REVIEW": 2, "EXCLUDE": 1}
    assert summary["hypothetical_denominator_count"] == 1
    assert summary["hypothetical_denominator_delta"] == 2

def test_life_candidate_subtype_diagnostics_do_not_change_classification(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    (xml_dir / "000_step_001_entry.xml").write_text(
        """<hierarchy>
  <node text="Add family member" resource-id="com.samsung.android.plugin.care:id/menu_main_invite_member" class="android.widget.Button" package="com.samsung.android.oneconnect" focusable="true" clickable="true" bounds="[1,2][3,4]" />
  <node text="ActivityButton" resource-id="" class="android.widget.LinearLayout" package="com.samsung.android.oneconnect" focusable="true" clickable="false" bounds="[5,6][7,8]" />
  <node text="Device care" resource-id="DASH_0102-5" class="android.view.View" package="com.samsung.android.oneconnect" focusable="true" clickable="false" bounds="[9,10][11,12]" />
  <node text="Air purifier,Self-diagnosis if fine dust count does not decrease" resource-id="" class="android.view.View" package="com.samsung.android.oneconnect" focusable="true" clickable="false" bounds="[13,14][15,16]" />
  <node text="Home Care" resource-id="" class="android.widget.TextView" package="com.samsung.android.oneconnect" focusable="true" clickable="false" bounds="[17,18][19,20]" />
  <node text="Usage guide" resource-id="DASH_0106-17" class="android.view.View" package="com.samsung.android.oneconnect" focusable="true" clickable="false" bounds="[21,22][23,24]" />
  <node text="Samsung Care+" resource-id="DASH_0109-13" class="android.view.View" package="com.samsung.android.oneconnect" focusable="true" clickable="true" bounds="[25,26][27,28]" />
  <node text="35" resource-id="" class="android.widget.TextView" package="com.samsung.android.oneconnect" focusable="false" clickable="false" bounds="[29,30][31,32]" />
  <node text="Active now" resource-id="profile_status_text" class="android.widget.TextView" package="com.samsung.android.oneconnect" focusable="false" clickable="false" bounds="[33,34][35,36]" />
  <node text="," resource-id="DASH_0108-11" class="android.view.View" package="com.samsung.android.oneconnect" focusable="true" clickable="true" bounds="[37,38][39,40]" />
</hierarchy>""",
        encoding="utf-8",
    )

    summary = extract_xml_candidates(xml_dir)
    by_label = {candidate["label"]: candidate for candidate in summary["merged_candidates"]}

    assert all(candidate["classification"] == "REVIEW" for candidate in summary["merged_candidates"])
    assert by_label["Add family member"]["candidate_subtype"] == "CTA"
    assert by_label["ActivityButton"]["candidate_subtype"] == "NAV_TILE"
    assert by_label["Device care"]["candidate_subtype"] == "SERVICE_TILE"
    assert by_label["Air purifier,Self-diagnosis if fine dust count does not decrease"]["candidate_subtype"] == "CONTENT_CARD"
    assert by_label["Home Care"]["candidate_subtype"] == "SCREEN_TITLE"
    assert by_label["Usage guide"]["candidate_subtype"] == "ONBOARDING"
    assert by_label["Samsung Care+"]["candidate_subtype"] == "PROMOTION_OR_SERVICE_CARD"
    assert by_label["35"]["candidate_subtype"] == "STATUS_METRIC"
    assert by_label["Active now"]["candidate_subtype"] == "STATUS_LABEL"
    assert by_label[","]["candidate_subtype"] == "LOW_VALUE_LABEL"
    assert summary["candidate_subtype_summary"]["CTA"] == 1
    assert "Add family member" in summary["cta_candidates_sample"]
    assert "Device care" in summary["service_tile_candidates_sample"]
    assert "CTA: 1" in summary["life_taxonomy_summary"]

def test_xml_candidate_classifier_rules():
    assert classify_xml_candidate({"label": "More options", "resource_ids": [], "classes": []})["classification"] == "EXCLUDE"
    assert classify_xml_candidate({"label": "Battery", "resource_ids": [], "classes": []})["classification"] == "KEEP"
    assert classify_xml_candidate({"label": "Example: every day, 6:00 PM - 10:00 PM", "resource_ids": [], "classes": []})["classification"] == "REVIEW"

def test_xml_coverage_uses_keep_candidates_only():
    merged_candidates = [
        {"label": "Motion sensor", "classification": "KEEP", "tabs": ["Controls"]},
        {"label": "Battery", "classification": "KEEP", "tabs": ["Controls"]},
        {"label": "No history", "classification": "KEEP", "policy_recommendation": "REVIEW", "tabs": ["Controls"]},
        {"label": "SmartThings Plugin", "classification": "REVIEW", "policy_recommendation": "KEEP", "tabs": ["Controls"]},
        {"label": "Navigate up", "classification": "EXCLUDE", "tabs": ["Controls"]},
    ]
    tab_stats = {
        "Controls": {
            "visible_labels_set": {"Motion sensor", "SmartThings Plugin", "Navigate up", "Unrelated label"}
        }
    }

    coverage = calculate_xml_coverage(merged_candidates, tab_stats)

    assert coverage["coverage_denominator_count"] == 3
    assert coverage["coverage_matched_count"] == 1
    assert coverage["coverage_missing_count"] == 2
    assert coverage["coverage_percent"] == 33.3
    assert coverage["coverage_matched_labels_sample"] == "Motion sensor"
    assert coverage["coverage_missing_labels_sample"] == "Battery, No history"
    assert "Battery: xml_only" in coverage["coverage_missing_reason_sample"]
    assert "No history: xml_only" in coverage["coverage_missing_reason_sample"]
    assert "SmartThings Plugin" in coverage["coverage_extra_traversal_labels_sample"]
    assert coverage["coverage_policy"] == "denominator=KEEP_ONLY; matching=normalized_exact; verdict=diagnostic_only"
    assert coverage["coverage_by_tab"]["Controls"]["denominator"] == 3
    assert coverage["coverage_by_tab"]["Controls"]["matched"] == 1

def test_xml_coverage_normalizes_case_and_whitespace_without_fuzzy_matching():
    merged_candidates = [
        {"label": "Motion sensor", "classification": "KEEP", "tabs": ["Controls"]},
        {"label": "Battery", "classification": "KEEP", "tabs": ["Controls"]},
    ]
    tab_stats = {"Controls": {"visible_labels_set": {"  motion   SENSOR  ", "Battery level"}}}

    coverage = calculate_xml_coverage(merged_candidates, tab_stats)

    assert normalize_coverage_label("  motion   SENSOR  ") == "motion sensor"
    assert coverage["coverage_matched_count"] == 1
    assert coverage["coverage_missing_labels_sample"] == "Battery"

def test_xml_coverage_missing_reason_diagnostics():
    merged_candidates = [
        {
            "label": "Motion detected",
            "classification": "KEEP",
            "tabs": ["Controls"],
            "classes": ["android.widget.TextView"],
            "resource_ids": [],
            "focusable_values": ["false"],
            "clickable_values": ["false"],
        },
        {
            "label": "Add routine",
            "classification": "KEEP",
            "tabs": ["Routines"],
            "classes": ["android.widget.Button"],
            "resource_ids": ["ADDROUTINE"],
            "focusable_values": ["true"],
            "clickable_values": ["true"],
        },
        {
            "label": "No history",
            "classification": "KEEP",
            "tabs": ["History"],
            "classes": ["android.widget.TextView"],
            "resource_ids": [],
            "focusable_values": ["false"],
            "clickable_values": ["false"],
        },
    ]
    tab_stats = {
        "Controls": {"visible_labels_set": {"Motion sensor History Motion detected"}},
        "Routines": {"visible_labels_set": {"History"}},
        "History": {"visible_labels_set": {"History"}},
    }

    coverage = calculate_xml_coverage(merged_candidates, tab_stats)

    assert "Motion detected: matching_mismatch_contained_in_traversal:Motion sensor History Motion detected" in coverage["coverage_missing_reason_sample"]
    assert "Add routine: xml_only_actionable_candidate" in coverage["coverage_missing_reason_sample"]
    assert "No history: xml_only_static_text_or_status" in coverage["coverage_missing_reason_sample"]

def test_missing_xml_dumps_directory_does_not_fail_audit(tmp_path):
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {"Controls": {"viewport_exhausted": True, "representative_exhausted": False, "unique_visible_labels": 2, "visible_labels_set": {"Motion sensor", "95%"}}},
    }
    summary = {"scenarios": [{"id": "device_motion_sensor_plugin", "availability_status": "none"}]}

    report = evaluate_scenario("device_motion_sensor_plugin", summary, log_data, tmp_path / "missing" / "xml_dumps")

    assert report["verdict"] == "PASS"
    assert report["xml_diagnostic_status"] == "xml_missing"
    assert report["coverage_diagnostic_status"] == "xml_missing"
    assert report["xml_dump_count"] == 0
    assert report["xml_candidate_count"] == 0

def test_invalid_xml_file_does_not_fail_audit(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    (xml_dir / "000_step_001_entry.xml").write_text("<hierarchy><node", encoding="utf-8")
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {"Controls": {"viewport_exhausted": True, "representative_exhausted": False, "unique_visible_labels": 2, "visible_labels_set": {"Motion sensor", "95%"}}},
    }
    summary = {"scenarios": [{"id": "device_motion_sensor_plugin", "availability_status": "none"}]}

    report = evaluate_scenario("device_motion_sensor_plugin", summary, log_data, xml_dir)

    assert report["verdict"] == "PASS"
    assert report["xml_diagnostic_status"] == "xml_present_parsed"
    assert report["coverage_diagnostic_status"] == "ready_empty_denominator"
    assert report["xml_dump_count"] == 1
    assert report["xml_candidate_count"] == 0

def test_empty_xml_directory_reports_present_empty_status(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {"Controls": {"viewport_exhausted": True, "representative_exhausted": False, "unique_visible_labels": 2, "visible_labels_set": {"Motion sensor", "95%"}}},
    }
    summary = {"scenarios": [{"id": "device_motion_sensor_plugin", "availability_status": "none"}]}

    report = evaluate_scenario("device_motion_sensor_plugin", summary, log_data, xml_dir)

    assert report["xml_diagnostic_status"] == "xml_present_empty"
    assert report["coverage_diagnostic_status"] == "xml_present_empty"
    assert report["xml_dump_count"] == 0
    assert report["merged_candidate_count"] == 0

def test_xml_diagnostic_fields_exist_in_report(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    (xml_dir / "000_step_001_entry.xml").write_text(
        """<hierarchy>
  <node text="Motion sensor" resource-id="motion" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[1,2][3,4]" />
  <node text="Battery" resource-id="battery" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[5,6][7,8]" />
</hierarchy>""",
        encoding="utf-8",
    )
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {"Controls": {"viewport_exhausted": True, "representative_exhausted": False, "unique_visible_labels": 2, "visible_labels_set": {"Motion sensor", "95%"}}},
    }
    summary = {"scenarios": [{"id": "device_motion_sensor_plugin", "availability_status": "none"}]}

    report = evaluate_scenario("device_motion_sensor_plugin", summary, log_data, xml_dir)

    for key in (
        "xml_dump_count",
        "xml_diagnostic_status",
        "xml_candidate_count",
        "xml_unique_label_count",
        "xml_unique_labels_sample",
        "xml_labels_not_seen_in_traversal_sample",
        "traversal_labels_not_in_xml_sample",
        "merged_candidate_count",
        "candidate_tab_distribution",
        "candidate_source_summary",
        "candidate_exclusion_todo",
        "candidate_classification_summary",
        "keep_candidates_sample",
        "review_candidates_sample",
        "exclude_candidates_sample",
        "candidate_classification_examples",
        "candidate_type_summary",
        "candidate_subtype_summary",
        "candidate_subtype_examples",
        "life_taxonomy_summary",
        "cta_candidates_sample",
        "nav_tile_candidates_sample",
        "service_tile_candidates_sample",
        "content_card_candidates_sample",
        "screen_title_candidates_sample",
        "onboarding_candidates_sample",
        "promotion_or_service_card_candidates_sample",
        "status_metric_candidates_sample",
        "status_label_candidates_sample",
        "instructional_status_candidates_sample",
        "low_value_label_candidates_sample",
        "actionable_candidates_sample",
        "status_candidates_sample",
        "empty_state_candidates_sample",
        "instructional_candidates_sample",
        "chrome_candidates_sample",
        "unknown_candidates_sample",
        "candidate_policy_recommendations",
        "candidate_policy_recommendation_summary",
        "candidate_policy_examples",
        "hypothetical_denominator_count",
        "hypothetical_denominator_delta",
        "coverage_diagnostic_status",
        "merged_candidates_sample",
        "coverage_denominator_count",
        "coverage_matched_count",
        "coverage_missing_count",
        "coverage_percent",
        "coverage_matched_labels_sample",
        "coverage_missing_labels_sample",
        "coverage_missing_reason_sample",
        "coverage_extra_traversal_labels_sample",
        "coverage_policy",
        "coverage_by_tab",
    ):
        assert key in report
    assert report["xml_dump_count"] == 1
    assert report["xml_diagnostic_status"] == "xml_present_parsed"
    assert report["coverage_diagnostic_status"] == "ready"
    assert report["merged_candidate_count"] == 2
    assert "Battery" in report["xml_labels_not_seen_in_traversal_sample"]
    assert "95%" in report["traversal_labels_not_in_xml_sample"]

def test_xml_diagnostics_do_not_change_v3_verdict(tmp_path):
    xml_dir = tmp_path / "xml_dumps"
    xml_dir.mkdir()
    (xml_dir / "000_step_001_entry.xml").write_text(
        """<hierarchy>
  <node text="Never visited label" resource-id="extra" class="android.widget.TextView" package="com.samsung.android.oneconnect" bounds="[1,2][3,4]" />
</hierarchy>""",
        encoding="utf-8",
    )
    log_data = {
        "detected_tabs": ["Controls"], "visited_tabs": ["Controls"], "preflight_fail": False, "crash": False,
        "target_entered": "Motion Sensor", "inventory_found": True,
        "value_exclusion_warnings": [], "boundary_warnings": [], "repeat_warnings": [],
        "tab_stats": {"Controls": {"viewport_exhausted": True, "representative_exhausted": False, "unique_visible_labels": 2, "visible_labels_set": {"Motion sensor", "95%"}}},
    }
    summary = {"scenarios": [{"id": "device_motion_sensor_plugin", "availability_status": "none"}]}

    without_xml = evaluate_scenario("device_motion_sensor_plugin", summary, log_data)
    with_xml = evaluate_scenario("device_motion_sensor_plugin", summary, log_data, xml_dir)

    assert without_xml["verdict"] == "PASS"
    assert with_xml["verdict"] == without_xml["verdict"]
    assert with_xml["xml_labels_not_seen_in_traversal_sample"] == "Never visited label"
    assert with_xml["coverage_policy"].endswith("verdict=diagnostic_only")
