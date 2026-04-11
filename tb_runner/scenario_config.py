SCENARIO_CONFIG_VERSION = "2026.04.11-direct-select-verify-v2"

BOTTOM_TAB_GLOBAL_NAV = {
    "labels": ["Home", "Devices", "Life", "Routines", "Menu"],
    "resource_ids": [
        "com.samsung.android.oneconnect:id/menu_favorites",
        "com.samsung.android.oneconnect:id/menu_devices",
        "com.samsung.android.oneconnect:id/menu_services",
        "com.samsung.android.oneconnect:id/menu_automations",
        "com.samsung.android.oneconnect:id/menu_more",
    ],
    "selected_pattern": "(?i).*(selected|선택됨).*",
    "region_hint": "bottom_tabs",
}

# Legacy compatibility: runtime override가 없을 때 global_nav 시나리오는 auto region 힌트를 유지해야 한다.
DEFAULT_GLOBAL_NAV = {
    **BOTTOM_TAB_GLOBAL_NAV,
    "region_hint": "auto",
}


TAB_CONFIGS = [
    # NOTE: scenario 실행 여부(enabled)의 최종 제어는 runtime_config.json(scenarios.<id>.enabled)에서 수행된다.
    # base scenario_config.py의 enabled는 정의용 기본값이며, loader에서 실행 제어값으로 사용하지 않는다.
    {
        "scenario_id": "global_nav_main",
        "scenario_type": "global_nav",
        "tab_name": "(?i).*(home|devices|life|routines|menu).*",
        "tab_type": "a",
        "screen_context_mode": "bottom_tab",
        "stabilization_mode": "tab_context",
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": "(?i).*(selected|선택됨).*(home|devices|life|routines|menu).*",
        },
        "anchor_name": "(?i).*(home|devices|life|routines|menu).*",
        "anchor_type": "a",
        "anchor": {
            "announcement_regex": "(?i).*(selected|선택됨).*(home|devices|life|routines|menu).*",
            "tie_breaker": "bottom_nav_left_to_right",
        },
        "stop_policy": {
            "stop_on_global_nav_exit": True,
        },
        "global_nav": DEFAULT_GLOBAL_NAV,
        "enabled": False,
        "max_steps": 10,
    },
    {
        "scenario_id": "home_main",
        "scenario_type": "content",
        "tab_name": "(?i).*home.*",
        "tab_type": "b",
        "tab": {
            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_favorites",
            "text_regex": "(?i).*home.*",
            "announcement_regex": "(?i).*(selected|선택됨)?.*home.*",
            "tie_breaker": "bottom_nav_left_to_right",
            "allow_resource_id_only": True,
        },
        "screen_context_mode": "bottom_tab",
        "stabilization_mode": "anchor_then_context",
        "anchor_name": "(?i).*location.*qr.*code.*",
        "anchor_type": "b",
        "anchor": {
            "text_regex": "(?i).*location.*qr.*code.*",
            "announcement_regex": "(?i).*qr.*code.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": "(?i).*(selected|선택됨).*home.*",
        },
        "stop_policy": {
            "stop_on_global_nav_entry": True,
        },
        "global_nav": BOTTOM_TAB_GLOBAL_NAV,
        "max_steps": 30,
        "enabled": False,
        "overlay_policy": {
            "allow_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/add_menu_button",
                    "label": "Add",
                },
                {
                    "resource_id": "com.samsung.android.oneconnect:id/more_menu_button",
                    "label": "More options",
                },
            ],
            "block_candidates": [],
        },
    },

    #Life 플러그인 Food
    {
        "scenario_id": "life_food_plugin",
        "scenario_type": "content",
        "tab_name": "(?i).*life.*",
        "tab_type": "b",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [
            {
                "action": "scrolltouch",
                "target": "(?i)(^food$|food\\.|smart\\s*things\\s*cooking|\\bcooking\\b)",
                "type": "a",
            }
        ],
        "anchor_name": "(?i).*navigate\\s*up.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*navigate\\s*up.*",
            "announcement_regex": "(?i).*navigate\\s*up.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "screen_text",
            "text_regex": "(?i).*smart\\s*things\\s*cooking.*|.*ingredients.*|.*모닝빵양배추샌드위치.*",
        },
        "overlay_policy": {
            "allow_candidates": [
                {
                    "label": "More options",
                    "class_name": "android.widget.Button",
                }
            ],
            "block_candidates": [],
        },
        "enabled": False,
        "max_steps": 100,
    },

        # Life 플러그인 Air Care
    {
        "scenario_id": "life_air_care_plugin",
        "scenario_type": "content",
        "entry_type": "card",
        "tab_name": "(?i).*life.*",
        "tab_type": "b",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",

        "pre_navigation": [
            {
                "action": "scrolltouch",
                "target": "(?i)(^smart\\s*air\\s*care$|^air\\s*care$|air\\s*care\\.|\\baircare\\b|에어\\s*케어)",
                "type": "a",
            }
        ],
        "entry_match": {
            "title_patterns": [
                "(?i)(^smart\\s*air\\s*care$|^air\\s*care$|air\\s*care\\.|\\baircare\\b|에어\\s*케어)",
            ],
            "description_patterns": [
                "(?i)(air\\s*quality|air\\s*comfort|outdoor\\s*air\\s*quality|pm\\s*10|pm\\s*2\\.5)",
            ],
            "resource_patterns": [
                "(?i)(preinstalledservicecard|servicecard|air)",
            ],
            "allow_description_match": True,
        },
        "verify_tokens": ["air care", "outdoor air quality", "pm 10", "pm 2.5", "air control"],

        "anchor_name": "(?i).*navigate\\s*up.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*navigate\\s*up.*",
            "announcement_regex": "(?i).*navigate\\s*up.*",
            "tie_breaker": "top_left",
        },

        "context_verify": {
            "type": "screen_text",
            "text_regex": "(?i).*smart\\s*air\\s*care.*|.*air\\s*care.*|.*aircare.*|.*에어\\s*케어.*|.*air\\s*quality.*|.*공기\\s*질.*",
        },
        "overlay_policy": {
            "allow_candidates": [
                {
                    "label": "More options",
                    "class_name": "android.widget.Button",
                }
            ],
            "block_candidates": [],
        },

        "enabled": False,
        "max_steps": 10,
    },
    # Life 플러그인 Home Care
    {
        "scenario_id": "life_home_care_plugin",
        "scenario_type": "content",
        "entry_type": "card",
        "tab_name": "(?i).*life.*",
        "tab_type": "b",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",

        "pre_navigation": [
            {
                "action": "scrolltouch",
                "target": "(?i)(^home\\s*care$|home\\s*care\\.|\\bhomecare\\b|홈\\s*케어)",
                "type": "a",
            }
        ],
        "entry_match": {
            "title_patterns": [
                "(?i)(^home\\s*care$|^smart\\s*home\\s*care$|home\\s*care\\.|\\bhomecare\\b|홈\\s*케어)",
            ],
            "description_patterns": [
                "(?i).*connect\\s*samsung\\s*home\\s*appliances.*smart\\s*care.*latest\\s*ai\\s*technology.*",
                "(?i)(connect\\s*samsung\\s*home\\s*appliances.*smart\\s*care)",
                "(?i)(home\\s*appliances.*smart\\s*care)",
                "(?i)(smart\\s*care.*latest\\s*ai\\s*technology)",
            ],
            "resource_patterns": [],
            "allow_description_match": True,
        },
        "verify_tokens": ["home care", "smart care", "home appliances"],
        "negative_verify_tokens": ["air care", "energy"],
        "special_state_tokens": [
            "smartthings home care",
            "always manage your home appliances optimally",
            "home care constantly monitors devices",
            "ai diagnosis",
            "maintenance",
        ],
        "special_state_cta_tokens": ["start"],
        "special_state_handling": "back_after_read",

        "anchor_name": "(?i).*navigate\\s*up.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*navigate\\s*up.*",
            "announcement_regex": "(?i).*navigate\\s*up.*",
            "tie_breaker": "top_left",
        },

        "context_verify": {
            "type": "screen_text",
            "text_regex": "(?i).*home\\s*care.*|.*homecare.*|.*홈\\s*케어.*",
        },
        "overlay_policy": {
            "allow_candidates": [
                {
                    "label": "More options",
                    "class_name": "android.widget.Button",
                }
            ],
            "block_candidates": [],
        },

        "enabled": False,
        "max_steps": 10,
    },
    
    # Life 플러그인 Energy
    {
        "scenario_id": "life_energy_plugin",
        "scenario_type": "content",
        "entry_type": "card",
        "tab_name": "(?i).*life.*",
        "tab_type": "b",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",

        "pre_navigation": [
            {
                "action": "scrolltouch",
                "target": "(?i)(^energy$|energy\\.|\\bsmart\\s*energy\\b|\\benergy\\b)",
                "type": "a",
            }
        ],
        "entry_match": {
            "title_patterns": [
                "(?i)(^energy$|energy\\.|\\bsmart\\s*energy\\b|\\benergy\\b)",
            ],
            "description_patterns": [
                "(?i)(energy\\s*usage|measuring\\s*energy\\s*usage|add\\s*an\\s*appliance|appliance)",
            ],
            "resource_patterns": [
                "(?i)(preinstalledservicecard|servicecard|energy|card|container|item)",
            ],
            "allow_description_match": True,
        },
        "verify_tokens": ["energy", "smartthings energy", "energy usage", "measuring energy usage", "appliance"],

        "anchor_name": "(?i).*navigate\\s*up.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*navigate\\s*up.*",
            "announcement_regex": "(?i).*navigate\\s*up.*",
            "tie_breaker": "top_left",
        },

        "context_verify": {
            "type": "screen_text",
            "text_regex": "(?i).*energy.*",
        },
        "overlay_policy": {
            "allow_candidates": [
                {
                    "label": "More options",
                    "class_name": "android.widget.Button",
                }
            ],
            "block_candidates": [],
        },

        "enabled": False,
        "max_steps": 10,
    },
        
    {
        "scenario_id": "devices_main",
        "scenario_type": "content",
        "tab_name": "(?i).*devices.*",
        "tab_type": "b",
        "tab": {
            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_devices",
            "text_regex": "(?i).*devices.*",
            "announcement_regex": "(?i).*(selected|선택됨)?.*devices.*",
            "tie_breaker": "bottom_nav_left_to_right",
            "allow_resource_id_only": True,
        },
        "screen_context_mode": "bottom_tab",
        "stabilization_mode": "anchor_then_context",
        "anchor_name": "(?i).*location.*qr.*code.*",
        "anchor_type": "b",
        "anchor": {
            "text_regex": "(?i).*location.*qr.*code.*",
            "announcement_regex": "(?i).*qr.*code.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": "(?i).*(selected|선택됨).*devices.*",
        },
        "stop_policy": {
            "stop_on_global_nav_entry": True,
        },
        "global_nav": BOTTOM_TAB_GLOBAL_NAV,
        "enabled": False,
        "max_steps": 30,
        "overlay_policy": {
            "allow_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/more_menu_button",
                    "label": "More options",
                }
            ],
            "block_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/add_menu_button",
                    "label": "Add",
                }
            ],
        },
    },
    {
        "scenario_id": "life_main",
        "scenario_type": "content",
        "tab_name": "(?i).*life.*",
        "tab_type": "b",
        "tab": {
            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_services",
            "text_regex": "(?i).*life.*",
            "announcement_regex": "(?i).*(selected|선택됨)?.*life.*",
            "tie_breaker": "bottom_nav_left_to_right",
            "allow_resource_id_only": True,
        },
        "screen_context_mode": "bottom_tab",
        "stabilization_mode": "anchor_then_context",
        "anchor_name": "(?i).*location.*qr.*code.*",
        "anchor_type": "b",
        "anchor": {
            "text_regex": "(?i).*location.*qr.*code.*",
            "announcement_regex": "(?i).*qr.*code.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": "(?i).*(selected|선택됨).*life.*",
        },
        "stop_policy": {
            "stop_on_global_nav_entry": True,
        },
        "global_nav": BOTTOM_TAB_GLOBAL_NAV,
        "enabled": False,
        "max_steps": 30,
        "overlay_policy": {
            "allow_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/more_menu_button",
                    "label": "More options",
                }
            ],
            "block_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/add_menu_button",
                    "label": "Add",
                }
            ],
        },
    },
    {
        "scenario_id": "routines_main",
        "scenario_type": "content",
        "tab_name": "(?i).*routines.*",
        "tab_type": "b",
        "tab": {
            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_automations",
            "text_regex": "(?i).*routines.*",
            "announcement_regex": "(?i).*(selected|선택됨)?.*routines.*",
            "tie_breaker": "bottom_nav_left_to_right",
            "allow_resource_id_only": True,
        },
        "screen_context_mode": "bottom_tab",
        "stabilization_mode": "anchor_then_context",
        "anchor_name": "(?i).*location.*qr.*code.*",
        "anchor_type": "b",
        "anchor": {
            "text_regex": "(?i).*location.*qr.*code.*",
            "announcement_regex": "(?i).*qr.*code.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": "(?i).*(selected|선택됨).*routines.*",
        },
        "stop_policy": {
            "stop_on_global_nav_entry": True,
        },
        "global_nav": BOTTOM_TAB_GLOBAL_NAV,
        "enabled": False,
        "max_steps": 30,
        "overlay_policy": {
            "allow_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/more_menu_button",
                    "label": "More options",
                }
            ],
            "block_candidates": [
                {
                    "resource_id": "com.samsung.android.oneconnect:id/add_menu_button",
                    "label": "Add",
                }
            ],
        },
    },
    {
        "scenario_id": "menu_main",
        "scenario_type": "content",
        "tab_name": "(?i).*(menu|more).*",
        "tab_type": "b",
        "tab": {
            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_more",
            "text_regex": "(?i).*(menu|more).*",
            "announcement_regex": "(?i).*(selected|선택됨)?.*(menu|more).*",
            "tie_breaker": "bottom_nav_left_to_right",
            "allow_resource_id_only": True,
        },
        "screen_context_mode": "bottom_tab",
        "stabilization_mode": "anchor_then_context",
        "anchor_name": "(?i).*smartthings settings.*|.*settings.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*smartthings settings.*|.*settings.*",
            "announcement_regex": "(?i).*smartthings settings.*|.*settings.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": "(?i).*(selected|선택됨).*(menu|more).*",
        },
        "stop_policy": {
            "stop_on_global_nav_entry": True,
        },
        "global_nav": BOTTOM_TAB_GLOBAL_NAV,
        "enabled": False,
        "max_steps": 30,
        "overlay_policy": {
            "allow_candidates": [],
            "block_candidates": [],
        },
    },

    {
        "scenario_id": "settings_entry_example",
        "scenario_type": "content",
        "tab_name": "(?i).*menu.*",
        "tab_type": "b",
        "tab": {
            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_more",
            "text_regex": "(?i).*menu.*",
            "announcement_regex": "(?i).*(selected|선택됨)?.*menu.*",
            "tie_breaker": "bottom_nav_left_to_right",
            "allow_resource_id_only": True,
        },
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [
            {
                "action": "select_and_click_focused_or_tap_bounds_center_adb",
                "target": "com.samsung.android.oneconnect:id/setting_button_layout",
                "type": "r",
            }
        ],
        "anchor_name": "(?i).*navigate up.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*navigate up.*",
            "announcement_regex": "(?i).*navigate up.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "screen_text",
            "text_regex": "(?i).*smartthings settings.*|.*settings.*",
        },
        "enabled": False,
        "max_steps": 30,
    },
    {
        "scenario_id": "life_pet_care_example",
        "scenario_type": "content",
        "entry_type": "direct_select",
        "tab_name": "(?i).*life.*",
        "tab_type": "b",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [
            {
                "action": "select",
                "target": "(?i).*pet\\s*care.*|.*펫\\s*케어.*",
                "type": "a",
            }
        ],
        "anchor_name": "(?i).*pet\\s*care.*|.*펫\\s*케어.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*pet\\s*care.*|.*펫\\s*케어.*",
            "announcement_regex": "(?i).*pet\\s*care.*|.*펫\\s*케어.*",
            "tie_breaker": "top_left",
        },
        "verify_tokens": [
            "pet care",
            "smartthings pet care",
            "pet profile",
            "pet routine",
            "반려",
            "펫 케어",
        ],
        "negative_verify_tokens": [
            "qr code",
            "change location",
            "home_button",
            "menu_favorites",
            "menu_devices",
            "menu_services",
            "menu_automations",
            "menu_more",
        ],
        "context_verify": {
            "type": "focused_anchor",
            "text_regex": "(?i).*pet\\s*care.*|.*펫\\s*케어.*",
            "announcement_regex": "(?i).*pet\\s*care.*|.*펫\\s*케어.*",
        },
        "enabled": False,
        "max_steps": 20,
    },


]
