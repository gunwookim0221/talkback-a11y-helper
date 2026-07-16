import time
from unittest.mock import Mock

import pytest

from tb_runner import anchor_logic


class FakeAnchorClient:
    def __init__(self):
        self.dump_tree = Mock(return_value=[])
        self.select = Mock(return_value=False)
        self.collect_focus_step = Mock(return_value={})


def _tab_cfg():
    return {
        "scenario_id": "s1",
        "anchor_name": "anchor_text",
        "anchor_type": "a",
        "anchor": {"resource_id_regex": "anchor_id", "text_regex": "anchor_text"},
    }


def _node(view_id="anchor_id", text="anchor_text", bounds="[0,0][10,10]"):
    return {"viewIdResourceName": view_id, "text": text, "boundsInScreen": bounds, "className": "TextView"}


def _focusable_node(
    view_id: str,
    text: str,
    bounds: str,
    *,
    focusable: bool = True,
    clickable: bool = True,
    visible_to_user: bool = True,
):
    return {
        "viewIdResourceName": view_id,
        "text": text,
        "boundsInScreen": bounds,
        "className": "TextView",
        "focusable": focusable,
        "clickable": clickable,
        "visibleToUser": visible_to_user,
    }


def _verify_step(view_id="anchor_id", label="anchor_text", bounds="0,0,10,10"):
    return {"focus_view_id": view_id, "visible_label": label, "merged_announcement": label, "focus_bounds": bounds}


def _empty_webview_snapshot(label="Home Care", *, resource_id=""):
    return [
        {
            "packageName": "com.samsung.android.oneconnect",
            "className": "android.webkit.WebView",
            "text": "",
            "contentDescription": None,
            "viewIdResourceName": None,
            "accessibilityFocused": True,
            "visibleToUser": True,
            "boundsInScreen": "[0,94][1080,2496]",
            "children": [
                {
                    "className": "android.view.View",
                    "text": label,
                    "viewIdResourceName": resource_id or None,
                    "visibleToUser": True,
                    "boundsInScreen": "[40,220][1040,380]",
                }
            ],
        }
    ]


def _landing_cfg(label_pattern="(?i).*home\\s*care.*", *, resource_pattern=""):
    now = time.monotonic_ns()
    return {
        "scenario_id": "life_fixture_plugin",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "entry_match": {
            "title_patterns": [label_pattern] if label_pattern else [],
            "resource_patterns": [resource_pattern] if resource_pattern else [],
        },
        "entry_transition_evidence": {
            "correlation_id": f"life_fixture_plugin:{now}",
            "scenario_id": "life_fixture_plugin",
            "transition_confirmed": True,
            "transition_signal": "package_or_surface_changed",
            "observed_monotonic_ns": now,
            "pre_entry_surface_signature": anchor_logic.build_landing_surface_signature(
                [{"className": "android.widget.FrameLayout", "text": "Life card list", "boundsInScreen": "[0,0][1080,2496]"}]
            ),
        },
    }


def _evaluate_landing(cfg, first, second=None, verify_rows=None, *, now_ns=None):
    return anchor_logic.evaluate_post_entry_landing_evidence(
        tab_cfg=cfg,
        phase="scenario_start",
        first_nodes=first,
        second_nodes=second if second is not None else first,
        verify_rows=verify_rows or [],
        now_monotonic_ns=now_ns,
    )


@pytest.mark.parametrize(
    ("label", "pattern"),
    [
        ("Home Care", "(?i).*home\\s*care.*"),
        ("홈 케어", "(?i).*홈\\s*케어.*"),
        ("Clothing Care", "(?i).*clothing\\s*care.*"),
        ("클로딩 케어", "(?i).*클로딩\\s*케어.*"),
    ],
)
def test_correlated_empty_webview_with_stable_configured_child_is_accepted(label, pattern):
    cfg = _landing_cfg(pattern)
    snapshot = _empty_webview_snapshot(label)

    result = _evaluate_landing(cfg, snapshot)

    assert result.accepted is True
    assert result.reason == "correlated_empty_webview_landing"
    assert result.identity_source == "configured_child"


def test_correlated_empty_webview_with_exact_resource_and_stable_observation_is_accepted():
    cfg = _landing_cfg("", resource_pattern=r"^plugin_landing_title$")
    snapshot = _empty_webview_snapshot("", resource_id="plugin_landing_title")

    result = _evaluate_landing(cfg, snapshot)

    assert result.accepted is True
    assert result.identity_source == "exact_resource"


def test_root_only_focus_evidence_combines_with_stable_dump_tree_identity():
    cfg = _landing_cfg()
    tree = [
        {
            "className": "android.widget.TextView",
            "text": "Home Care",
            "contentDescription": "Home Care",
            "boundsInScreen": {"l": 168, "t": 196, "r": 486, "b": 280},
        }
    ]
    root = {
        "packageName": "com.samsung.android.oneconnect",
        "className": "android.webkit.WebView",
        "text": "",
        "boundsInScreen": {"l": 0, "t": 94, "r": 1080, "b": 2496},
        "accessibilityFocused": True,
        "visibleToUser": True,
    }
    verify_rows = [
        {"get_focus_partial_root_evidence": dict(root)},
        {"get_focus_partial_root_evidence": dict(root)},
    ]

    result = _evaluate_landing(cfg, tree, verify_rows=verify_rows)

    assert result.accepted is True
    assert result.root_class == "android.webkit.WebView"
    assert result.root_bounds == "0,94,1080,2496"
    assert result.identity_value == "Home Care Home Care"


def test_empty_webview_class_alone_is_rejected():
    cfg = _landing_cfg()
    snapshot = _empty_webview_snapshot("")

    result = _evaluate_landing(cfg, snapshot)

    assert result.accepted is False
    assert result.reason == "configured_landing_identity_absent"


def test_empty_webview_with_tap_but_without_confirmed_transition_is_rejected():
    cfg = _landing_cfg()
    cfg["entry_transition_evidence"]["transition_confirmed"] = False

    result = _evaluate_landing(cfg, _empty_webview_snapshot("Home Care"))

    assert result.accepted is False
    assert result.reason == "transition_not_confirmed"


def test_stale_fallback_tree_is_rejected():
    cfg = _landing_cfg()
    observed = int(cfg["entry_transition_evidence"]["observed_monotonic_ns"])

    result = _evaluate_landing(
        cfg,
        _empty_webview_snapshot("Home Care"),
        now_ns=observed + int((anchor_logic._POST_ENTRY_CORRELATION_MAX_AGE_SECONDS + 1) * 1_000_000_000),
    )

    assert result.accepted is False
    assert result.reason == "stale_transition_evidence"


def test_transaction_correlation_mismatch_is_rejected():
    cfg = _landing_cfg()
    cfg["entry_transition_evidence"]["scenario_id"] = "different_scenario"

    result = _evaluate_landing(cfg, _empty_webview_snapshot("Home Care"))

    assert result.accepted is False
    assert result.reason == "transaction_correlation_mismatch"


def test_delayed_focus_that_changes_to_non_webview_is_rejected():
    cfg = _landing_cfg()
    verify_rows = [
        {"focus_node": {"className": "android.webkit.WebView"}, "focus_bounds": "[0,94][1080,2496]"},
        {"focus_node": {"className": "android.widget.Button"}, "focus_bounds": "[0,0][100,100]", "visible_label": "Home"},
    ]

    result = _evaluate_landing(cfg, _empty_webview_snapshot("Home Care"), verify_rows=verify_rows)

    assert result.accepted is False
    assert result.reason == "delayed_focus_changed"


def test_delayed_empty_webview_root_bounds_change_is_rejected():
    cfg = _landing_cfg()
    first = _empty_webview_snapshot("Home Care")
    second = _empty_webview_snapshot("Home Care")
    second[0]["boundsInScreen"] = "[0,94][1080,2200]"

    result = _evaluate_landing(cfg, first, second)

    assert result.accepted is False
    assert result.reason == "delayed_webview_changed"


def test_pre_and_post_same_surface_without_anchor_is_rejected():
    cfg = _landing_cfg()
    snapshot = _empty_webview_snapshot("Home Care")
    cfg["entry_transition_evidence"]["pre_entry_surface_signature"] = anchor_logic.build_landing_surface_signature(snapshot)

    result = _evaluate_landing(cfg, snapshot)

    assert result.accepted is False
    assert result.reason == "pre_post_surface_identity_unchanged"


def test_stabilize_anchor_selects_best_candidate_resource_id(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert result["selected"] is True
    assert client.dump_tree.call_count == 1
    assert client.select.call_count == 1
    assert client.collect_focus_step.call_count == 2


def test_stabilize_anchor_fallback_select_when_best_select_fails(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.side_effect = [False, True]
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert client.select.call_count == 2


def test_stabilize_anchor_ok_when_verify_match_and_context_ok(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step()
    verify_context = Mock(return_value={"ok": True})
    monkeypatch.setattr(anchor_logic, "verify_context", verify_context)

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert verify_context.call_count == 2


def test_stabilize_anchor_fails_when_match_but_context_fail(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": False})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is False


def test_stabilize_anchor_retries_and_fails_when_verify_match_fails(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step(view_id="different", label="different")
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=2)

    assert result["ok"] is False
    assert client.dump_tree.call_count == 2


def test_stabilize_anchor_verified_without_select_reason(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = []
    client.select.return_value = False
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert result["selected"] is False
    assert result["reason"] == "verified_without_select"


def test_stabilize_anchor_fails_when_not_double_verified(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = []
    client.select.return_value = False
    client.collect_focus_step.side_effect = [_verify_step(), _verify_step(view_id="different", label="different")]
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})

    result = anchor_logic.stabilize_anchor(client, "SERIAL", _tab_cfg(), phase="scenario_start", max_retries=1)

    assert result["ok"] is False
    assert result["reason"] == "low_confidence_anchor_start"


def test_stabilize_anchor_anchor_only_ignores_context_failure(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step()
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": False})
    tab_cfg = {**_tab_cfg(), "stabilization_mode": "anchor_only"}

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert result["context"]["type"] == "skipped"


def test_stabilize_anchor_tab_context_ignores_anchor_mismatch(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [_node()]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step(view_id="different", label="different")
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {**_tab_cfg(), "stabilization_mode": "tab_context"}

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True


def test_stabilize_anchor_uses_content_fallback_when_anchor_missing(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node("toolbar_back", "Back", "[0,0][120,120]"),
        _focusable_node("content_top_left", "Start", "[40,260][220,340]"),
    ]
    client.select.return_value = True
    captured_cfg = {}

    def _fake_stabilize_anchor_focus(**kwargs):
        captured_cfg.update(kwargs.get("anchor_cfg", {}))
        return {
            "stable": True,
            "reason": "double_verified",
            "verify_rows": [_verify_step(view_id="content_top_left", label="Start"), _verify_step(view_id="content_top_left", label="Start")],
            "verify_matches": [{"matched": True, "score": 100}, {"matched": True, "score": 100}],
            "verify1_matched": True,
            "verify2_matched": True,
        }

    monkeypatch.setattr(anchor_logic, "stabilize_anchor_focus", _fake_stabilize_anchor_focus)
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {"scenario_id": "s1", "anchor_name": "", "anchor_type": "a", "anchor": {}}

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert client.select.call_args.kwargs["type_"] == "r"
    assert "content_top_left" in client.select.call_args.kwargs["name"]
    assert "content_top_left" in captured_cfg.get("resource_id_regex", "")


def test_stabilize_anchor_fallback_prefers_top_center_then_right(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node("top_toolbar", "Search", "[10,0][300,120]"),
        _focusable_node("top_center_item", "Center", "[430,260][650,340]"),
        _focusable_node("top_right_item", "Right", "[820,260][1040,340]"),
    ]
    client.select.return_value = True
    monkeypatch.setattr(
        anchor_logic,
        "stabilize_anchor_focus",
        lambda **kwargs: {
            "stable": True,
            "reason": "double_verified",
            "verify_rows": [_verify_step(view_id="top_center_item", label="Center"), _verify_step(view_id="top_center_item", label="Center")],
            "verify_matches": [{"matched": True, "score": 100}, {"matched": True, "score": 100}],
            "verify1_matched": True,
            "verify2_matched": True,
        },
    )
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {
        **_tab_cfg(),
        "anchor": {"resource_id_regex": "not_found", "text_regex": "not_found"},
    }

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert "top_center_item" in client.select.call_args.kwargs["name"]


def test_stabilize_anchor_fallback_rejects_boilerplate_like_top_candidate(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node(
            "privacy_notice",
            "I agree to the Privacy Policy and Terms of Use",
            "[20,260][1040,360]",
        )
    ]
    client.select.return_value = False
    client.collect_focus_step.return_value = _verify_step(view_id="different", label="different")
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {
        "scenario_id": "life_food_plugin",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "select", "target": ".*food.*", "type": "a"}],
        "anchor_name": "(?i).*navigate\\s*up.*",
        "anchor_type": "a",
        "anchor": {
            "resource_id_regex": "missing",
            "text_regex": "(?i).*navigate\\s*up.*",
        },
    }

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is False
    assert result["fallback_candidate_rejected_reason"] == "boilerplate_like"


def test_stabilize_anchor_fallback_rejects_home_button_chrome_candidate(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node("com.samsung.android.oneconnect:id/home_button", "Home", "[20,260][220,340]"),
    ]
    client.select.return_value = False
    client.collect_focus_step.return_value = _verify_step(view_id="different", label="different")
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {
        "scenario_id": "life_pet_care_plugin",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "select", "target": ".*pet.*", "type": "a"}],
        "anchor_name": "(?i).*pet\\s*care.*",
        "anchor_type": "a",
        "anchor": {},
    }

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is False
    assert result["fallback_candidate_rejected_reason"] == "no_readable_top_candidate"


def test_stabilize_anchor_accepts_home_care_landing_section_title(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node("com.example:id/plugin_title", "Home Care", "[40,140][600,220]"),
        _focusable_node("com.example:id/suggestions", "Suggestions", "[40,320][600,390]"),
        _focusable_node("com.example:id/device_list", "My device list", "[40,760][600,830]"),
    ]
    client.select.return_value = True
    client.collect_focus_step.return_value = _verify_step(
        view_id="com.example:id/suggestions",
        label="Suggestions",
        bounds="40,320,600,390",
    )
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {
        "scenario_id": "life_home_care_plugin",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "xml_scroll_search_tap", "target": ".*home.*", "type": "a"}],
        "anchor_name": "(?i).*(navigate\\s*up|suggestions|my\\s*device\\s*list|care\\s*options|software\\s*update).*",
        "anchor_type": "a",
        "anchor": {
            "text_regex": "(?i).*(navigate\\s*up|suggestions|my\\s*device\\s*list|care\\s*options|software\\s*update).*",
            "announcement_regex": "(?i).*(navigate\\s*up|suggestions|my\\s*device\\s*list|care\\s*options|software\\s*update).*",
        },
    }

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["ok"] is True
    assert result["reason"] == "selected_and_verified"
    assert "suggestions" in client.select.call_args.kwargs["name"]


def test_stabilize_anchor_direct_select_fallback_prefers_verify_token_candidate(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node("top_left_generic", "Welcome", "[20,260][960,520]"),
        _focusable_node("pet_plugin_entry", "Pet Care", "[740,260][1030,340]"),
    ]
    client.select.return_value = True
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "direct_select",
        "verify_tokens": ["pet care"],
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "select", "target": ".*pet.*", "type": "a"}],
        "anchor_name": "(?i).*pet\\s*care.*",
        "anchor_type": "a",
        "anchor": {},
    }

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["fallback_candidate_label"] == "Pet Care"
    assert "pet_plugin_entry" in client.select.call_args.kwargs["name"]


def test_stabilize_anchor_direct_select_fallback_demotes_generic_activity_top_candidate(monkeypatch):
    client = FakeAnchorClient()
    client.dump_tree.return_value = [
        _focusable_node("family_me_card", "안 창준 (Me) No activity", "[20,260][1060,700]"),
        _focusable_node("pet_plugin_entry", "Companion service", "[700,260][1030,340]"),
    ]
    client.select.return_value = True
    monkeypatch.setattr(anchor_logic, "verify_context", lambda *a, **k: {"ok": True})
    tab_cfg = {
        "scenario_id": "life_pet_care_plugin",
        "entry_type": "direct_select",
        "screen_context_mode": "new_screen",
        "stabilization_mode": "anchor_only",
        "pre_navigation": [{"action": "select", "target": ".*pet.*", "type": "a"}],
        "anchor_name": "(?i).*pet\\s*care.*",
        "anchor_type": "a",
        "anchor": {},
    }

    result = anchor_logic.stabilize_anchor(client, "SERIAL", tab_cfg, phase="scenario_start", max_retries=1)

    assert result["fallback_candidate_resource_id"] == "pet_plugin_entry"
