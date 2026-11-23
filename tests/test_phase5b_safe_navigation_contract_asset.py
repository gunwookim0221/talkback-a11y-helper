import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_helper_policy_matches_reviewed_source_and_stays_default_off():
    source = ROOT / "config" / "safe_navigation_contracts.json"
    packaged = ROOT / "app" / "src" / "main" / "res" / "raw" / "safe_navigation_contracts.json"

    assert packaged.read_bytes() == source.read_bytes()
    policy = json.loads(packaged.read_text(encoding="utf-8"))
    assert policy["schema"] == "safe-navigation-contracts-v1"
    assert policy["default_enabled"] is False
    contracts = {contract["id"]: contract for contract in policy["contracts"]}
    assert set(contracts) == {
        "application_overflow_menu", "life_service_card_read_only_navigation",
        "life_plugin_navigate_up_to_landing",
    }
    old_contract = contracts["application_overflow_menu"]
    assert old_contract.get("enabled", False) is False
    assert old_contract["resource_id"] == "com.samsung.android.oneconnect:id/more_menu_button_container"
    assert "destination_pattern" not in old_contract
    assert "required_anchor_pattern" not in old_contract

    route = contracts["life_service_card_read_only_navigation"]
    assert route["enabled"] is True
    assert route["effect"] == "read_only_navigation"
    assert route["scenario_ids"] == ["life_air_care_plugin"]
    assert route["resource_id"] == ""
    assert route["target_class_pattern"] == r"^android\.widget\.RelativeLayout$"
    assert route["return_transport"] == "BACK"
    assert route["expected_descendant_count"] == 7
    assert set(route["excluded_descendant_resource_ids"]) == {
        "com.samsung.android.oneconnect:id/frameLayout",
        "com.samsung.android.oneconnect:id/include",
    }
    assert set(route["required_non_actionable_descendant_label_patterns"]) == {"^(?:보통|나쁨)$", "^야외$"}
    assert "(?=.*(?:보통|나쁨))" in route["target_subtree_pattern"]
    assert "좋음" not in route["target_subtree_pattern"]
    assert route["destination_pattern"] and route["required_anchor_pattern"]
    assert len(route["evidence_refs"]) >= 3

    recovery = contracts["life_plugin_navigate_up_to_landing"]
    assert recovery["enabled"] is True
    assert recovery["effect"] == "read_only_navigation"
    assert recovery["scenario_ids"] == ["life_air_care_plugin"]
    assert recovery["resource_id"] == "back"
    assert recovery["target_class_pattern"] == r"^android\.widget\.Button$"
    assert recovery["expected_descendant_count"] == 0
    assert recovery["excluded_descendant_resource_ids"] == []
    assert recovery["required_non_actionable_descendant_label_patterns"] == []
    assert recovery["destination_pattern"] and recovery["required_anchor_pattern"]
    assert recovery["required_anchor_structure"] == {
        "relation": "direct_parent",
        "node_class_pattern": r"^android\.widget\.LinearLayout$",
        "parent_class_pattern": r"^android\.widget\.HorizontalScrollView$",
        "parent_resource_id_pattern": r"^com\.samsung\.android\.oneconnect:id/bottom_navigation$",
    }
