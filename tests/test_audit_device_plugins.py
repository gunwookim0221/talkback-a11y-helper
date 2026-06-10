import pytest
from pathlib import Path
import json
from unittest.mock import patch, mock_open
from tools.audit_device_plugins import parse_normal_log, evaluate_scenario, parse_summary_json, main

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
        
        log_data = parse_normal_log(log_file)
        assert len(log_data["detected_tabs"]) == 3
        assert len(log_data["visited_tabs"]) == 3
        
        summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "none"}]}
        report = evaluate_scenario("test_plugin", summary, log_data)
        
        assert report["verdict"] == "PASS"

def test_audit_2_tabs_missed_1(mock_log_2_tabs_missed_1):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.normal.log"
        log_file.write_text(mock_log_2_tabs_missed_1)
        
        log_data = parse_normal_log(log_file)
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
        
        log_data = parse_normal_log(log_file)
        assert len(log_data["detected_tabs"]) == 1
        assert len(log_data["visited_tabs"]) == 1
        
        summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "none"}]}
        report = evaluate_scenario("test_plugin", summary, log_data)
        
        assert report["verdict"] == "PASS"

def test_audit_status_excluded_review(mock_log_status_excluded):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.normal.log"
        log_file.write_text(mock_log_status_excluded)
        
        log_data = parse_normal_log(log_file)
        assert "No motion" in log_data["value_exclusion_warnings"]
        
        summary = {"scenarios": [{"id": "test_plugin", "availability_status": "none", "stop_reason": "none"}]}
        report = evaluate_scenario("test_plugin", summary, log_data)
        
        assert report["verdict"] == "REVIEW"
        assert "Sensor values excluded" in report["reason"]

def test_audit_routines_boundary_review(mock_log_routines_boundary):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.normal.log"
        log_file.write_text(mock_log_routines_boundary)
        
        log_data = parse_normal_log(log_file)
        
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
    assert "Target found but exited with not_available" in report["reason"]

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
    assert report["verdict"] == "FAIL"
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
