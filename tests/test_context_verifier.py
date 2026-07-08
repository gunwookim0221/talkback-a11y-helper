from tb_runner.context_verifier import verify_context
from tb_runner.scenario_config import TAB_CONFIGS


def _step(**kwargs):
    base = {
        "visible_label": "SmartThings settings",
        "merged_announcement": "Navigate up, SmartThings settings",
        "focus_view_id": "com.test:id/toolbar_title",
        "dump_tree_nodes": [],
    }
    base.update(kwargs)
    return base


def test_verify_context_new_screen_without_context_verify_is_optional():
    result = verify_context(_step(), {"screen_context_mode": "new_screen"})

    assert result["ok"] is True
    assert result.get("skipped") is True


def test_verify_context_screen_text_type():
    result = verify_context(
        _step(),
        {"context_verify": {"type": "screen_text", "text_regex": ".*settings.*"}},
    )

    assert result["ok"] is True


def test_verify_context_screen_text_accepts_korean_settings_alias():
    result = verify_context(
        _step(visible_label="스마트싱스 설정"),
        {"context_verify": {"type": "screen_text", "text_regex": "(?i).*settings.*"}},
    )

    assert result["ok"] is True


def test_verify_context_life_food_accepts_korean_food_identity_cluster():
    food_cfg = next(cfg for cfg in TAB_CONFIGS if cfg.get("scenario_id") == "life_food_plugin")
    result = verify_context(
        _step(
            visible_label="식단 플래너에 추가 저장한 레시피 전자레인지로 간단하게 만드는 누드라자냐 1668 kcal 주요 재료",
            merged_announcement="",
            focus_view_id="com.test:id/food",
        ),
        food_cfg,
    )

    assert result["ok"] is True


def test_verify_context_focused_anchor_accepts_korean_monitor_alias():
    result = verify_context(
        _step(visible_label="모니터링", focus_view_id="com.test:id/plugin_title"),
        {
            "context_verify": {
                "type": "focused_anchor",
                "text_regex": "(?i).*monitor.*",
                "view_id_regex": ".*plugin_title",
            }
        },
    )

    assert result["ok"] is True


def test_verify_context_screen_announcement_type():
    result = verify_context(
        _step(),
        {"context_verify": {"type": "screen_announcement", "announcement_regex": ".*Navigate up.*"}},
    )

    assert result["ok"] is True


def test_verify_context_navigation_aliases_accept_korean_for_english_regex():
    result = verify_context(
        _step(visible_label="상위 메뉴로 이동", merged_announcement="상위 메뉴로 이동"),
        {"context_verify": {"type": "screen_announcement", "announcement_regex": "(?i).*navigate\\s*up.*"}},
    )

    assert result["ok"] is True


def test_verify_context_menu_and_settings_aliases_accept_korean_for_english_regex():
    more_result = verify_context(
        _step(visible_label="더보기", merged_announcement="더보기"),
        {"context_verify": {"type": "screen_text", "text_regex": "(?i).*more\\s*options.*"}},
    )
    settings_result = verify_context(
        _step(visible_label="스마트싱스 설정", merged_announcement="스마트싱스 설정"),
        {"context_verify": {"type": "screen_text", "text_regex": "(?i).*smartthings settings.*"}},
    )

    assert more_result["ok"] is True
    assert settings_result["ok"] is True


def test_verify_context_focused_anchor_type_with_view_id():
    result = verify_context(
        _step(),
        {
            "context_verify": {
                "type": "focused_anchor",
                "text_regex": ".*settings.*",
                "view_id_regex": ".*toolbar_title",
            }
        },
    )

    assert result["ok"] is True


def test_verify_context_selected_bottom_tab_accepts_korean_tab_alias_for_english_regex():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "기기",
                "contentDescription": "선택됨, 기기, 탭 5개 중 2번째 탭, 새 콘텐츠 사용 가능",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_devices",
                "selected": True,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(devices).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is True


def test_verify_context_selected_bottom_tab_accepts_english_selected_after_label():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "Home",
                "contentDescription": "Home, Selected",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_favorites",
                "selected": False,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(home).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is True


def test_verify_context_selected_bottom_tab_accepts_korean_selected_after_label():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "홈",
                "contentDescription": "홈, 선택됨",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_favorites",
                "selected": False,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(home).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is True


def test_verify_context_selected_bottom_tab_accepts_korean_selected_before_label():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "기기",
                "contentDescription": "선택됨, 기기, 탭 1/5",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_devices",
                "selected": False,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(devices).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is True


def test_verify_context_selected_bottom_tab_accepts_node_selected_label_only():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "Home",
                "contentDescription": "Home, Tab 1 of 5",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_favorites",
                "selected": True,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(home).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is True


def test_verify_context_selected_bottom_tab_accepts_selected_resource_id_without_label():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "",
                "contentDescription": "",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/bottom_devices",
                "selected": True,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(devices).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is True


def test_verify_context_selected_bottom_tab_rejects_non_bottom_home_row():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "홈",
                "contentDescription": "홈, 선택됨",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/settings_home_row",
                "selected": True,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(home).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is False


def test_verify_context_selected_bottom_tab_rejects_menu_open_button():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "메뉴 열기",
                "contentDescription": "메뉴 열기",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_open_button",
                "selected": False,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(menu).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is False


def test_verify_context_selected_bottom_tab_prefers_smart_nav_result_on_resource_match():
    step = _step(
        smart_nav_success=True,
        smart_nav_requested_view_id="com.samsung.android.oneconnect:id/menu_devices",
        smart_nav_resolved_view_id="com.samsung.android.oneconnect:id/menu_devices",
        smart_nav_actual_view_id="com.samsung.android.oneconnect:id/menu_devices",
        smart_nav_resolved_label="선택됨, 기기",
        dump_tree_nodes=[
            {
                "text": "",
                "contentDescription": "",
                "viewIdResourceName": "android:id/list",
                "selected": False,
            }
        ],
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(devices|기기).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is True
    assert result["actual_source"] == "smart_nav_result"


def test_verify_context_selected_bottom_tab_ignores_plugin_internal_selected_tab():
    step = _step(
        dump_tree_nodes=[
            {
                "text": "Life",
                "contentDescription": "selected",
                "viewIdResourceName": "com.samsung.android.oneconnect:id/plugin_inner_tab_life",
                "selected": True,
                "boundsInScreen": "0,0,100,100",
            }
        ]
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(life|라이프).*",
        }
    }

    result = verify_context(step, scenario_cfg)

    assert result["ok"] is False


class _DumpGuardClient:
    def dump_tree(self, dev: str = ""):
        raise AssertionError("dump_tree should not be called")


def test_verify_context_selected_bottom_tab_uses_focus_payload_fast_path_without_dump():
    step = _step(
        focus_node={
            "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
            "contentDescription": "Selected, Home, Tab 1 of 5",
            "mergedLabel": "Selected, Home, Tab 1 of 5",
        },
        focus_view_id="com.samsung.android.oneconnect:id/menu_favorites",
        visible_label="Selected, Home, Tab 1 of 5",
        merged_announcement="Selected, Home, Tab 1 of 5",
        dump_tree_nodes=[],
        get_focus_top_level_payload_sufficient=True,
        get_focus_final_payload_source="top_level",
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(home|홈).*",
        },
        "global_nav": {
            "resource_ids": [
                "com.samsung.android.oneconnect:id/menu_favorites",
            ]
        },
    }

    result = verify_context(step, scenario_cfg, client=_DumpGuardClient(), dev="serial")

    assert result["ok"] is True
    assert result["actual_source"] == "focus_payload_fast_path"
    assert result["dump_source"] == "focus_payload"


def test_verify_context_selected_bottom_tab_falls_back_to_dump_when_focus_signal_is_weak():
    class _LazyDumpClient:
        def dump_tree(self, dev: str = ""):
            return [
                {
                    "text": "Home",
                    "contentDescription": "Selected, Home, Tab 1 of 5",
                    "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
                    "selected": True,
                }
            ]

    step = _step(
        focus_node={
            "viewIdResourceName": "com.samsung.android.oneconnect:id/menu_favorites",
            "contentDescription": "Home, Tab 1 of 5",
        },
        focus_view_id="com.samsung.android.oneconnect:id/menu_favorites",
        dump_tree_nodes=[],
        get_focus_top_level_payload_sufficient=False,
        get_focus_final_payload_source="none",
    )
    scenario_cfg = {
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": r"(?i).*(selected|선택됨).*(home|홈).*",
        },
        "global_nav": {
            "resource_ids": [
                "com.samsung.android.oneconnect:id/menu_favorites",
            ]
        },
    }

    result = verify_context(step, scenario_cfg, client=_LazyDumpClient(), dev="serial")

    assert result["ok"] is True
    assert result["dump_source"] == "lazy_dump"
