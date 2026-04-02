TAB_CONFIGS = [

    {

        "scenario_id": "home_main",

        "tab_name": "(?i).*home.*",

        "tab_type": "b",

        "tab": {

            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_favorites",

            "text_regex": "(?i).*home.*",

            "announcement_regex": "(?i).*(selected|선택됨)?.*home.*",

            "tie_breaker": "bottom_nav_left_to_right",

            "allow_resource_id_only": True,

        },

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

        "max_steps": 5,

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

    {

        "scenario_id": "devices_main",

        "tab_name": "(?i).*devices.*",

        "tab_type": "b",

        "tab": {

            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_devices",

            "text_regex": "(?i).*devices.*",

            "announcement_regex": "(?i).*(selected|선택됨)?.*devices.*",

            "tie_breaker": "bottom_nav_left_to_right",

            "allow_resource_id_only": True,

        },

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

        "enabled": False,

        "max_steps": 5,

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

        "tab_name": "(?i).*life.*",

        "tab_type": "b",

        "tab": {

            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_services",

            "text_regex": "(?i).*life.*",

            "announcement_regex": "(?i).*(selected|선택됨)?.*life.*",

            "tie_breaker": "bottom_nav_left_to_right",

            "allow_resource_id_only": True,

        },

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

        "enabled": False,

        "max_steps": 5,

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

        "tab_name": "(?i).*routines.*",

        "tab_type": "b",

        "tab": {

            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_automations",

            "text_regex": "(?i).*routines.*",

            "announcement_regex": "(?i).*(selected|선택됨)?.*routines.*",

            "tie_breaker": "bottom_nav_left_to_right",

            "allow_resource_id_only": True,

        },

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

        "enabled": False,

        "max_steps": 5,

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

        "scenario_id": "settings_entry_example",

        "tab_name": "(?i).*menu.*",

        "tab_type": "b",

        "tab": {

            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_more",

            "text_regex": "(?i).*menu.*",

            "announcement_regex": "(?i).*(selected|선택됨)?.*menu.*",

            "tie_breaker": "bottom_nav_left_to_right",

            "allow_resource_id_only": True,

        },

        "pre_navigation": [

            {

                "action": "tap_bounds_center_adb",

                "target": "com.samsung.android.oneconnect:id/setting_button_layout",

                "type": "r",

            }

        ],

        "anchor_name": "(?i).*navigate up.*",

        "anchor_type": "a",

        "anchor": {

            "announcement_regex": "(?i).*navigate up.*",

            "tie_breaker": "top_left",

        },

        "context_verify": {

            "type": "selected_bottom_tab",

            "announcement_regex": "(?i).*(selected|선택됨).*menu.*",

        },

        "enabled": True,

        "max_steps": 20,

    }



    ,


    {

        "scenario_id": "life_pet_care_example",

        "tab_name": "(?i).*life.*",

        "tab_type": "b",

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

            "tie_breaker": "top_left",

        },

        "enabled": False,

        "max_steps": 20,

    },

    {

        "scenario_id": "life_plugin_example",

        "tab_name": "(?i).*life.*",

        "tab_type": "b",

        "anchor_name": "(?i).*location.*qr.*code.*",

        "anchor_type": "b",

        "anchor": {

            "text_regex": "(?i).*location.*qr.*code.*",

            "announcement_regex": "(?i).*qr.*code.*",

            "tie_breaker": "top_left",

        },

        "context_verify": {

            "type": "plugin",

            "text_regex": "(?i).*smartthings.*energy.*",

        },

        "enabled": False,

        "max_steps": 5,

    },

    {

        "scenario_id": "resource_id_only_example",

        "tab_name": "(?i).*home.*",

        "tab_type": "b",

        "anchor_name": "com.samsung.android.oneconnect:id/add_menu_button",

        "anchor_type": "r",

        "anchor": {

            "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/add_menu_button",

            "tie_breaker": "top_left",

            "allow_resource_id_only": True,

        },

        "enabled": False,

        "max_steps": 10,

    },

]


