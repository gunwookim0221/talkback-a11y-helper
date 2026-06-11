import pytest
from pathlib import Path
import json
from unittest.mock import patch, mock_open
from tools.audit_device_plugins import parse_run_results, evaluate_scenario, parse_summary_json, main

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

import tempfile

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
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from tools.audit_device_plugins import parse_run_results
        log_data = parse_run_results(Path(temp_name), Path("nonexistent"))
        assert "Controls" in log_data["visited_tabs"], "Active tab should be added to visited_tabs"
        assert "Routines" in log_data["visited_tabs"]
        assert "Controls" in log_data["detected_tabs"]
    finally:
        import os
        os.remove(temp_name)

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
