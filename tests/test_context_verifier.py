from tb_runner.context_verifier import verify_context


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


def test_verify_context_screen_announcement_type():
    result = verify_context(
        _step(),
        {"context_verify": {"type": "screen_announcement", "announcement_regex": ".*Navigate up.*"}},
    )

    assert result["ok"] is True


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
