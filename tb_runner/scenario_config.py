TAB_CONFIGS = [
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
        "global_nav": {
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
        },
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
                "action": "touch",
                "target": "(?i).*food.*|.*cooking.*|.*smart\\s*things\\s*cooking.*",
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
        "enabled": True,
        "max_steps": 20,
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
        "global_nav": {
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
        },
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
        "global_nav": {
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
        },
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
        "global_nav": {
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
        },
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
        "anchor_name": "(?i).*smartthings settings.*|(?i).*settings.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*smartthings settings.*|(?i).*settings.*",
            "announcement_regex": "(?i).*smartthings settings.*|(?i).*settings.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": "(?i).*(selected|선택됨).*(menu|more).*",
        },
        "stop_policy": {
            "stop_on_global_nav_entry": True,
        },
        "global_nav": {
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
        },
        "enabled": False,
        "max_steps": 30,
        "overlay_policy": {
            "allow_candidates": [],
            "block_candidates": [],
        },
    },
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
        "global_nav": {
            "labels": ["Home", "Devices", "Life", "Routines", "Menu"],
            "resource_ids": [
                "com.samsung.android.oneconnect:id/menu_favorites",
                "com.samsung.android.oneconnect:id/menu_devices",
                "com.samsung.android.oneconnect:id/menu_services",
                "com.samsung.android.oneconnect:id/menu_automations",
                "com.samsung.android.oneconnect:id/menu_more",
            ],
            "selected_pattern": "(?i).*(selected|선택됨).*",
            "region_hint": "auto",
        },
        "enabled": False,
        "max_steps": 10,
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
        "context_verify": {
            "type": "focused_anchor",
            "text_regex": "(?i).*pet\\s*care.*|.*펫\\s*케어.*",
            "announcement_regex": "(?i).*pet\\s*care.*|.*펫\\s*케어.*",
        },
        "enabled": False,
        "max_steps": 20,
    },
    {
        "scenario_id": "life_plugin_example",
        "scenario_type": "content",
        "tab_name": "(?i).*life.*",
        "tab_type": "b",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "anchor_name": "(?i).*smartthings.*energy.*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*smartthings.*energy.*",
            "announcement_regex": "(?i).*smartthings.*energy.*",
            "tie_breaker": "top_left",
        },
        "context_verify": {
            "type": "screen_text",
            "text_regex": "(?i).*smartthings.*energy.*",
        },
        "enabled": False,
        "max_steps": 5,
    },
    {
        "scenario_id": "resource_id_only_example",
        "scenario_type": "content",
        "tab_name": "(?i).*home.*",
        "tab_type": "b",
        "screen_context_mode": "bottom_tab",
        "stabilization_mode": "anchor_then_context",
        "anchor_name": "com.samsung.android.oneconnect:id/add_menu_button",
        "anchor_type": "r",
        "anchor": {
            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/add_menu_button",
            "tie_breaker": "top_left",
            "allow_resource_id_only": True,
        },
        "context_verify": {
            "type": "selected_bottom_tab",
            "announcement_regex": "(?i).*(selected|선택됨).*home.*",
        },
        "stop_policy": {
            "stop_on_global_nav_entry": True,
        },
        "global_nav": {
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
        },
        "enabled": False,
        "max_steps": 10,
    },
]
