import pytest
from tb_runner.local_tab_logic import _is_passive_status_text, _is_chrome_like_candidate
from tb_runner.collection_flow import _row_global_bottom_nav_boundary

def test_motion_sensor_passive_status_bypass():
    scenario_id = "device_motion_sensor_plugin"
    
    # Normally passive status
    assert _is_passive_status_text("No motion") is True
    
    # Bypassed for sensor plugin
    assert _is_passive_status_text("No motion", scenario_id=scenario_id) is False
    assert _is_passive_status_text("Motion detected", scenario_id=scenario_id) is False
    assert _is_passive_status_text("No vibration", scenario_id=scenario_id) is False
    assert _is_passive_status_text("Vibration detected", scenario_id=scenario_id) is False
    
    # Temperature bypass
    assert _is_passive_status_text("24.5 °C", scenario_id=scenario_id) is False
    assert _is_passive_status_text("8,555.5 °", scenario_id=scenario_id) is False
    
    # Battery bypass
    assert _is_passive_status_text("100%", scenario_id=scenario_id) is False

def test_motion_sensor_chrome_exclusion_bypass():
    scenario_id = "device_motion_sensor_plugin"
    
    # 100% at the top right usually classified as chrome
    assert _is_chrome_like_candidate(
        label="100%",
        resource_id="battery",
        class_name="textview",
        actionable=False,
        button_like=False,
        card_like=False,
        center_y=150,
        top_header_band=220,
        width_ratio=0.1
    ) is True
    
    assert _is_chrome_like_candidate(
        label="100%",
        resource_id="battery",
        class_name="textview",
        actionable=False,
        button_like=False,
        card_like=False,
        center_y=150,
        top_header_band=220,
        width_ratio=0.1,
        scenario_id=scenario_id
    ) is False
    
    assert _is_chrome_like_candidate(
        label="Motion sensor",
        resource_id="title",
        class_name="textview",
        actionable=False,
        button_like=False,
        card_like=False,
        center_y=150,
        top_header_band=220,
        width_ratio=0.3,
        scenario_id=scenario_id
    ) is False

def test_global_nav_boundary_routines_local_tab():
    tab_cfg = {"scenario_id": "device_motion_sensor_plugin"}
    
    # Local tab "Routines" (not in bottom region)
    row_local = {
        "focus_view_id": "routine",
        "visible_label": "Routines tab 2 of 3",
        "focus_bounds": "100, 1200, 400, 1300",
        "screen_height": 2400
    }
    
    # 1300 / 2400 = 0.54 (< 0.72), so it's not bottom region.
    hit, label, reason = _row_global_bottom_nav_boundary(row_local, tab_cfg)
    assert hit is False
    assert "routines_not_in_bottom_region" in reason or "label_requires_tab_context" in reason
    
    # Global nav "Routines" (in bottom region)
    row_global = {
        "focus_view_id": "routine",
        "visible_label": "Routines",
        "focus_bounds": "100, 2100, 400, 2200",
        "screen_height": 2400
    }
    
    # 2200 / 2400 = 0.91 (>= 0.72), so it's bottom region.
    hit2, label2, reason2 = _row_global_bottom_nav_boundary(row_global, tab_cfg)
    assert hit2 is True
    assert reason2 == "label:routines"
