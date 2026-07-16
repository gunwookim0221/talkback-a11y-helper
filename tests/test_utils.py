import os

from tb_runner.runtime_config import load_runtime_bundle
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.utils import _safe_regex_search, configure_process_temp_dir


def test_safe_regex_search_returns_false_for_invalid_pattern():
    assert _safe_regex_search("(?i", "SmartThings Settings") is False


def test_menu_main_anchor_regex_has_single_leading_ignorecase_flag():
    menu_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "menu_main")
    for regex in (
        menu_cfg["anchor_name"],
        menu_cfg["anchor"]["text_regex"],
        menu_cfg["anchor"]["announcement_regex"],
    ):
        assert regex.startswith("(?i)")
        assert regex.count("(?i)") == 1
        assert _safe_regex_search(regex, "SmartThings settings")
        assert _safe_regex_search(regex, "Settings")
        assert _safe_regex_search(regex, "스마트싱스 설정")


def test_life_pet_care_plugin_uses_card_entry_spec():
    pet_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "life_pet_care_plugin")

    assert pet_cfg["entry_type"] == "card"
    assert pet_cfg["pre_navigation"][0]["action"] == "xml_scroll_search_tap"
    assert pet_cfg["entry_match"]["allow_description_match"] is True
    assert "(?i).*take care of your pet.*" in pet_cfg["entry_match"]["description_patterns"]
    assert "산책 시작" in pet_cfg["verify_tokens"]


def test_life_food_plugin_uses_xml_card_entry_spec():
    food_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "life_food_plugin")

    assert food_cfg["entry_type"] == "card"
    assert food_cfg["pre_navigation"][0]["action"] == "xml_scroll_search_tap"
    assert food_cfg["entry_match"]["allow_description_match"] is True
    assert food_cfg["verify_tokens"] == ["smartthings cooking", "ingredients"]
    assert "(?i)(smart\\s*things\\s*cooking|\\bcooking\\b|\\bmeal\\b|\\brecipe\\b|barcode\\s*scan|kitchen\\s*appliance)" in food_cfg[
        "entry_match"
    ]["description_patterns"]
    assert "(?i)(^food$|food\\.|smart\\s*things\\s*cooking|\\bcooking\\b|^푸드$)" in food_cfg["entry_match"]["title_patterns"]


def test_runtime_config_does_not_downgrade_life_food_xml_entry():
    bundle = load_runtime_bundle(TAB_CONFIGS, config_path="config/runtime_config.json")
    food_cfg = next(cfg for cfg in bundle["tab_configs"] if cfg.get("scenario_id") == "life_food_plugin")

    assert food_cfg["entry_type"] == "card"
    assert food_cfg["pre_navigation"][0]["action"] == "xml_scroll_search_tap"
    assert food_cfg["pre_navigation"][0]["target"] == "(?i)(^food$|food\\.|smart\\s*things\\s*cooking|\\bcooking\\b|^푸드$)"
    assert food_cfg["entry_match"]["allow_description_match"] is True
    assert "pre_navigation_ref" not in food_cfg


def test_life_home_care_plugin_uses_landing_section_anchor_tokens():
    home_care_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "life_home_care_plugin")

    assert "suggestions" in home_care_cfg["verify_tokens"]
    assert "my device list" in home_care_cfg["verify_tokens"]
    assert "care options" in home_care_cfg["verify_tokens"]
    assert "software update" in home_care_cfg["verify_tokens"]
    assert "suggestions" in home_care_cfg["anchor"]["text_regex"].lower()
    assert "my\\s*device\\s*list" in home_care_cfg["anchor"]["announcement_regex"].lower()


def test_device_plugins_use_device_pre_navigation():
    expected_targets = {
        "device_smoke_sensor_plugin": ["연기", "Smoke sensor"],
        "device_water_leak_sensor_plugin": ["누수", "Water leak sensor"],
        "device_motion_sensor_plugin": ["모션센서", "Motion sensor"],
        "device_door_lock_plugin": ["Door Lock"],
        "device_air_purifier_plugin": ["공기청정기", "Air purifier"],
        "device_tv_plugin": ["TV"],
        "device_washer_plugin": ["세탁기", "Washer"],
        "device_humidity_sensor_plugin": ["습도센서", "Humidity sensor"],
        "device_temperature_humidity_sensor_plugin": ["온습도 센서", "Temperature & humidity sensor"],
        "device_camera_plugin": ["Camera"],
        "device_home_camera_plugin": ["홈카메라 360"],
        "device_audio_plugin": ["Audio", "오디오"],
    }

    for scenario_id, target_stable_labels in expected_targets.items():
        cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == scenario_id)

        assert cfg["tab"]["resource_id_regex"] == "com\\.samsung\\.android\\.oneconnect:id/menu_devices"
        assert cfg["pre_navigation"][0]["action"] == "enter_device_card_plugin"
        assert cfg["pre_navigation"][0]["target_stable_labels"] == target_stable_labels
        assert cfg["enabled"] is False


def test_configure_process_temp_dir_sets_tmp_and_temp(tmp_path):
    applied, path_text = configure_process_temp_dir(str(tmp_path / ".tmp"))

    assert os.environ["TMP"] == path_text
    assert os.environ["TEMP"] == path_text
    assert applied is True
