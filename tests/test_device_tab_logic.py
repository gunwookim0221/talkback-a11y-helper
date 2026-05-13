from tb_runner import device_tab_logic


def _node(
    label,
    rid,
    bounds,
    *,
    class_name="android.view.ViewGroup",
    clickable=True,
    focusable=True,
    effective_clickable=True,
    selected=False,
    visible=True,
    has_clickable_descendant=False,
    actionable_descendant_resource_id=None,
):
    return {
        "text": label,
        "contentDescription": label,
        "mergedLabel": label,
        "talkbackLabel": label,
        "className": class_name,
        "viewIdResourceName": rid,
        "boundsInScreen": bounds,
        "clickable": clickable,
        "focusable": focusable,
        "effectiveClickable": effective_clickable,
        "selected": selected,
        "isVisibleToUser": visible,
        "hasClickableDescendant": has_clickable_descendant,
        "actionableDescendantResourceId": actionable_descendant_resource_id,
    }


def _device_card(label, left, top, *, rid="com.samsung.android.oneconnect:id/device_card", **kwargs):
    return _node(
        label,
        rid,
        {"l": left, "t": top, "r": left + 477, "b": top + 345},
        **kwargs,
    )


def test_collect_visible_device_cards_collects_viewgroup_cards_only():
    nodes = [
        _device_card("연기 감지 안 됨", 42, 628),
        _node(
            "연기",
            "com.samsung.android.oneconnect:id/device_name",
            {"l": 80, "t": 690, "r": 220, "b": 760},
            class_name="android.widget.TextView",
            clickable=False,
            focusable=False,
            effective_clickable=False,
        ),
        _node(
            "켜기",
            "com.samsung.android.oneconnect:id/image_button",
            {"l": 410, "t": 710, "r": 500, "b": 800},
            class_name="android.widget.ImageButton",
            clickable=True,
            focusable=True,
        ),
    ]

    cards = device_tab_logic.collect_visible_device_cards(nodes)

    assert len(cards) == 1
    assert cards[0]["rid"] == "com.samsung.android.oneconnect:id/device_card"
    assert cards[0]["stable_label"] == "연기"


def test_collect_visible_device_cards_accepts_home_camera_card_resource_id():
    nodes = [
        _device_card(
            "홈카메라 360 오프라인",
            42,
            1015,
            rid="com.samsung.android.oneconnect:id/device_card_camera",
        )
    ]

    cards = device_tab_logic.collect_visible_device_cards(nodes)

    assert len(cards) == 1
    assert cards[0]["rid"] == "com.samsung.android.oneconnect:id/device_card_camera"
    assert cards[0]["stable_label"] == "홈카메라 360"


def test_promote_device_card_target_uses_ancestor_card_not_action_button():
    card = _device_card(
        "TV 꺼짐",
        561,
        1866,
        has_clickable_descendant=True,
        actionable_descendant_resource_id="com.samsung.android.oneconnect:id/image_button",
    )
    action_button = _node(
        "켜기",
        "com.samsung.android.oneconnect:id/image_button",
        {"l": 900, "t": 1960, "r": 1010, "b": 2070},
        class_name="android.widget.ImageButton",
        clickable=True,
        focusable=True,
    )
    nodes = [card, action_button]

    promoted = device_tab_logic.promote_device_card_target(action_button, nodes)

    assert promoted is not None
    assert promoted["rid"] == "com.samsung.android.oneconnect:id/device_card"
    assert promoted["stable_label"] == "TV"
    assert promoted["promoted_from"]["rid"] == "com.samsung.android.oneconnect:id/image_button"


def test_promote_door_lock_action_descendant_uses_ancestor_card():
    card = _device_card(
        "Door Lock 잠김",
        561,
        1015,
        has_clickable_descendant=True,
        actionable_descendant_resource_id="com.samsung.android.oneconnect:id/image_button",
    )
    action_button = _node(
        "잠금해제",
        "com.samsung.android.oneconnect:id/image_button",
        {"l": 900, "t": 1100, "r": 1010, "b": 1210},
        class_name="android.widget.ImageButton",
        clickable=True,
        focusable=True,
    )

    promoted = device_tab_logic.promote_device_card_target(action_button, [card, action_button])

    assert promoted is not None
    assert promoted["rid"] == "com.samsung.android.oneconnect:id/device_card"
    assert promoted["stable_label"] == "Door Lock"


def test_observed_state_suffix_is_removed_from_stable_target_label():
    cards = device_tab_logic.collect_visible_device_cards(
        [
            _device_card("세탁기 꺼짐", 42, 1479),
            _device_card("Audio 일시중지", 42, 1911),
        ]
    )

    assert [card["stable_label"] for card in cards] == ["세탁기", "Audio"]
    assert all("꺼짐" not in card["stable_label"] for card in cards)
    assert all("일시중지" not in card["stable_label"] for card in cards)


def test_second_wave_observed_state_suffixes_are_removed_from_stable_labels():
    cards = device_tab_logic.collect_visible_device_cards(
        [
            _device_card("모션센서 움직임 감지됨", 42, 1015),
            _device_card("Door Lock 잠김", 561, 1015),
            _device_card("공기청정기 켜짐", 42, 1479),
        ]
    )

    assert [card["stable_label"] for card in cards] == ["모션센서", "Door Lock", "공기청정기"]
    assert all(card["target_label_allowed"] is True for card in cards)
    assert all(not device_tab_logic.label_contains_state_text(card["stable_label"]) for card in cards)


def test_short_english_state_tokens_do_not_match_inside_words():
    card = device_tab_logic.collect_visible_device_cards(
        [_device_card("Motion sensor detected", 42, 1789)]
    )[0]

    assert card["stable_label"] == "Motion sensor"
    assert card["target_label_allowed"] is True


def test_detect_selected_device_location_accepts_all_devices_filter():
    nodes = [
        _node(
            "모든 기기 모든 기기",
            "",
            {"l": 171, "t": 319, "r": 410, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=False,
            focusable=True,
            effective_clickable=False,
        ),
        _node(
            "지정된 방 없음 지정된 방 없음",
            "",
            {"l": 560, "t": 319, "r": 888, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=True,
            focusable=True,
        ),
    ]

    result = device_tab_logic.detect_selected_device_location(nodes)

    assert result["selected"] is True
    assert result["candidate"]["label"] == "모든 기기 모든 기기"


def test_find_all_devices_location_candidate_supports_english_label():
    nodes = [
        _node(
            "All devices All devices",
            "",
            "171,319,410,469",
            class_name="android.widget.LinearLayout",
            clickable=False,
            focusable=True,
            effective_clickable=False,
        )
    ]

    candidate = device_tab_logic.find_all_devices_location_candidate(nodes)

    assert candidate is not None
    assert candidate["label"] == "All devices All devices"


def test_find_collapsed_room_sections_marks_only_explicit_collapsed_as_actionable():
    nodes = [
        _node(
            "펼쳐짐 거실 거실",
            "com.samsung.android.oneconnect:id/subheader_card",
            {"l": 42, "t": 520, "r": 1038, "b": 628},
            clickable=True,
            focusable=True,
        ),
        _node(
            "접힘 지정된 방 없음 지정된 방 없음",
            "com.samsung.android.oneconnect:id/subheader_card",
            {"l": 42, "t": 2182, "r": 1038, "b": 2290},
            clickable=True,
            focusable=True,
        ),
        _node(
            "주방",
            "com.samsung.android.oneconnect:id/subheader_card",
            {"l": 42, "t": 2290, "r": 1038, "b": 2398},
            clickable=True,
            focusable=True,
        ),
    ]

    candidates = device_tab_logic.find_collapsed_room_sections(nodes)

    assert [candidate["label"] for candidate in candidates] == [
        "접힘 지정된 방 없음 지정된 방 없음",
        "주방",
    ]
    assert candidates[0]["collapsed"] is True
    assert candidates[0]["actionable"] is True
    assert candidates[1]["collapsed"] is False
    assert candidates[1]["confidence"] == "low"
    assert candidates[1]["actionable"] is False


def test_find_device_card_by_stable_label_matches_observed_device_labels():
    nodes = [
        _device_card("연기 감지 안 됨", 42, 628),
        _device_card("누수 물기 없음", 561, 628),
        _device_card("모션센서 움직임 감지됨", 42, 1015),
        _device_card("Door Lock 잠김", 561, 1015),
        _device_card("공기청정기 켜짐", 42, 1479),
    ]

    smoke = device_tab_logic.find_device_card_by_stable_label(nodes, ["연기", "Smoke sensor"])
    leak = device_tab_logic.find_device_card_by_stable_label(nodes, ["누수", "Water leak sensor"])
    motion = device_tab_logic.find_device_card_by_stable_label(nodes, ["모션센서", "Motion sensor"])
    door_lock = device_tab_logic.find_device_card_by_stable_label(nodes, ["Door Lock"])
    air_purifier = device_tab_logic.find_device_card_by_stable_label(nodes, ["공기청정기", "Air purifier"])

    assert smoke is not None
    assert smoke["stable_label"] == "연기"
    assert leak is not None
    assert leak["stable_label"] == "누수"
    assert motion is not None
    assert motion["stable_label"] == "모션센서"
    assert door_lock is not None
    assert door_lock["stable_label"] == "Door Lock"
    assert air_purifier is not None
    assert air_purifier["stable_label"] == "공기청정기"


def test_find_device_card_by_stable_label_returns_none_for_missing_target():
    nodes = [_device_card("연기 감지 안 됨", 42, 628)]

    assert device_tab_logic.find_device_card_by_stable_label(nodes, ["누수"]) is None


def test_select_all_devices_candidate_for_action_returns_candidate_when_not_selected():
    nodes = [
        _node(
            "All devices All devices",
            "",
            "171,319,410,469",
            class_name="android.widget.LinearLayout",
            clickable=True,
            focusable=False,
            effective_clickable=True,
            selected=False,
        )
    ]

    candidate = device_tab_logic.select_all_devices_candidate_for_action(nodes)

    assert candidate is not None
    assert candidate["label"] == "All devices All devices"


def test_collect_high_confidence_collapsed_room_sections_filters_low_confidence_sections():
    nodes = [
        _node(
            "접힘 거실 거실",
            "com.samsung.android.oneconnect:id/subheader_card",
            {"l": 42, "t": 520, "r": 1038, "b": 628},
            clickable=True,
            focusable=True,
        ),
        _node(
            "주방",
            "com.samsung.android.oneconnect:id/subheader_card",
            {"l": 42, "t": 2182, "r": 1038, "b": 2290},
            clickable=True,
            focusable=True,
        ),
    ]

    candidates = device_tab_logic.collect_high_confidence_collapsed_room_sections(nodes)

    assert [candidate["label"] for candidate in candidates] == ["접힘 거실 거실"]
