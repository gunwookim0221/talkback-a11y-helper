from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.utils import _safe_regex_search


def test_safe_regex_search_returns_false_for_invalid_pattern():
    assert _safe_regex_search("(?i", "SmartThings Settings") is False


def test_menu_main_anchor_regex_has_single_leading_ignorecase_flag():
    menu_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "menu_main")
    assert menu_cfg["anchor_name"] == "(?i).*smartthings settings.*|.*settings.*"
    assert menu_cfg["anchor"]["text_regex"] == "(?i).*smartthings settings.*|.*settings.*"
    assert menu_cfg["anchor"]["announcement_regex"] == "(?i).*smartthings settings.*|.*settings.*"
