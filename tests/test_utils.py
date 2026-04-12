import os

from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.utils import _safe_regex_search, configure_process_temp_dir


def test_safe_regex_search_returns_false_for_invalid_pattern():
    assert _safe_regex_search("(?i", "SmartThings Settings") is False


def test_menu_main_anchor_regex_has_single_leading_ignorecase_flag():
    menu_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "menu_main")
    assert menu_cfg["anchor_name"] == "(?i).*smartthings settings.*|.*settings.*"
    assert menu_cfg["anchor"]["text_regex"] == "(?i).*smartthings settings.*|.*settings.*"
    assert menu_cfg["anchor"]["announcement_regex"] == "(?i).*smartthings settings.*|.*settings.*"


def test_life_pet_care_plugin_uses_card_entry_spec():
    pet_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "life_pet_care_plugin")

    assert pet_cfg["entry_type"] == "card"
    assert pet_cfg["pre_navigation"][0]["action"] == "scrolltouch"
    assert pet_cfg["entry_match"]["allow_description_match"] is True
    assert "(?i).*take care of your pet.*" in pet_cfg["entry_match"]["description_patterns"]


def test_life_food_plugin_uses_card_entry_spec():
    food_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "life_food_plugin")

    assert food_cfg["entry_type"] == "card"
    assert food_cfg["pre_navigation"][0]["action"] == "scrolltouch"
    assert food_cfg["entry_match"]["allow_description_match"] is True
    assert food_cfg["entry_match"]["allow_title_hidden_card_inference"] is True
    assert "(?i)(^food$|food\\.|smart\\s*things\\s*cooking|\\bcooking\\b)" in food_cfg["entry_match"]["title_patterns"]


def test_configure_process_temp_dir_sets_tmp_and_temp(tmp_path):
    applied, path_text = configure_process_temp_dir(str(tmp_path / ".tmp"))

    assert os.environ["TMP"] == path_text
    assert os.environ["TEMP"] == path_text
    assert applied is True
