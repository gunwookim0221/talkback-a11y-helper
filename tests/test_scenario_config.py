from tb_runner.scenario_config import TAB_CONFIGS


def test_home_safe_plugin_is_home_optional_card_scenario():
    cfg = next(item for item in TAB_CONFIGS if item.get("scenario_id") == "home_safe_plugin")

    assert cfg["tab_name"] == "(?i).*home.*"
    assert cfg["entry_type"] == "card"
    assert cfg["pre_navigation"][0]["action"] == "enter_safe_favorite_card"
    assert cfg["optional_availability"] is True
    assert cfg["plugin_more_options_enabled"] is True

