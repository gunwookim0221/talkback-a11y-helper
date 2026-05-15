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
    checked=False,
    accessibility_focused=False,
    focused=False,
    state_description=None,
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
        "checked": checked,
        "accessibilityFocused": accessibility_focused,
        "focused": focused,
        "stateDescription": state_description,
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


def test_promote_generic_media_action_descendant_uses_ancestor_card():
    card = _device_card(
        "Media device 일시중지",
        42,
        1911,
        has_clickable_descendant=True,
        actionable_descendant_resource_id="com.samsung.android.oneconnect:id/image_button",
    )
    action_button = _node(
        "재생",
        "com.samsung.android.oneconnect:id/image_button",
        {"l": 385, "t": 1990, "r": 500, "b": 2105},
        class_name="android.widget.ImageButton",
        clickable=True,
        focusable=True,
    )

    promoted = device_tab_logic.promote_device_card_target(action_button, [card, action_button])

    assert promoted is not None
    assert promoted["rid"] == "com.samsung.android.oneconnect:id/device_card"
    assert promoted["stable_label"] == "Media device"


def test_promote_washer_action_descendant_uses_ancestor_card():
    card = _device_card(
        "세탁기 꺼짐",
        42,
        1479,
        has_clickable_descendant=True,
        actionable_descendant_resource_id="com.samsung.android.oneconnect:id/image_button",
    )
    action_button = _node(
        "전원",
        "com.samsung.android.oneconnect:id/image_button",
        {"l": 385, "t": 1550, "r": 500, "b": 1665},
        class_name="android.widget.ImageButton",
        clickable=True,
        focusable=True,
    )

    promoted = device_tab_logic.promote_device_card_target(action_button, [card, action_button])

    assert promoted is not None
    assert promoted["rid"] == "com.samsung.android.oneconnect:id/device_card"
    assert promoted["stable_label"] == "세탁기"


def test_observed_state_suffix_is_removed_from_stable_target_label():
    cards = device_tab_logic.collect_visible_device_cards(
        [
            _device_card("세탁기 꺼짐", 42, 1479),
        ]
    )

    assert [card["stable_label"] for card in cards] == ["세탁기"]
    assert all("꺼짐" not in card["stable_label"] for card in cards)


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


def test_third_wave_observed_state_suffixes_are_removed_from_stable_labels():
    cards = device_tab_logic.collect_visible_device_cards(
        [
            _device_card("TV 꺼짐", 42, 1866),
            _device_card("세탁기 꺼짐", 42, 1479),
        ]
    )

    assert [card["stable_label"] for card in cards] == ["세탁기", "TV"]
    assert all(card["target_label_allowed"] is True for card in cards)
    assert all(not device_tab_logic.label_contains_state_text(card["stable_label"]) for card in cards)


def test_fourth_wave_humidity_state_suffixes_are_removed_from_stable_labels():
    cards = device_tab_logic.collect_visible_device_cards(
        [
            _device_card("습도센서 진동 감지됨", 42, 1681),
            _device_card("온습도 센서 진동 감지됨", 42, 2068),
        ]
    )

    assert [card["stable_label"] for card in cards] == ["습도센서", "온습도 센서"]
    assert all(card["target_label_allowed"] is True for card in cards)
    assert all(not device_tab_logic.label_contains_state_text(card["stable_label"]) for card in cards)


def test_english_state_suffixes_are_removed_from_stable_labels():
    cards = device_tab_logic.collect_visible_device_cards(
        [
            _device_card("연기 Clear", 42, 628),
            _device_card("누수 Dry", 561, 628),
            _device_card("Audio Pause", 42, 1911),
            _device_card("Audio Paused", 42, 1911),
            _device_card("온습도 센서 Vibration detected", 42, 2068),
            _device_card("습도센서 Vibration detected", 42, 1681),
            _device_card("Camera Connected", 42, 742),
            _device_card("Door Lock Locked", 561, 1015),
            _device_card("TV Off", 42, 1866),
            _device_card("세탁기 Off", 42, 1479),
            _device_card("공기청정기 On", 42, 1479),
            _device_card("Security System Armed (away)", 42, 1015),
        ]
    )

    assert [card["stable_label"] for card in cards] == [
        "연기",
        "누수",
        "Camera",
        "Security System",
        "Door Lock",
        "공기청정기",
        "세탁기",
        "습도센서",
        "TV",
        "Audio",
        "Audio",
        "온습도 센서",
    ]
    assert all(card["target_label_allowed"] is True for card in cards)
    assert all(not device_tab_logic.label_contains_state_text(card["stable_label"]) for card in cards)


def test_short_english_state_tokens_do_not_match_inside_words():
    card = device_tab_logic.collect_visible_device_cards(
        [_device_card("Motion sensor detected", 42, 1789)]
    )[0]

    assert card["stable_label"] == "Motion sensor"
    assert card["target_label_allowed"] is True


def test_english_state_suffixes_do_not_remove_device_base_words():
    cards = device_tab_logic.collect_visible_device_cards(
        [
            _device_card("Smoke sensor Clear", 42, 628),
            _device_card("Water leak sensor Dry", 561, 628),
            _device_card("Motion sensor", 42, 1789),
            _device_card("Smoke sensor", 42, 628),
            _device_card("Water leak sensor", 561, 628),
        ]
    )

    assert [card["stable_label"] for card in cards] == [
        "Smoke sensor",
        "Smoke sensor",
        "Water leak sensor",
        "Water leak sensor",
        "Motion sensor",
    ]
    assert all(card["target_label_allowed"] is True for card in cards)


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
    assert result["selected_label"] == "모든 기기"


def test_detect_selected_device_location_accepts_english_all_devices_filter():
    nodes = [
        _node(
            "All devices All devices",
            "",
            {"l": 171, "t": 319, "r": 410, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=False,
            focusable=True,
            effective_clickable=False,
        )
    ]

    result = device_tab_logic.detect_selected_device_location(nodes)

    assert result["selected"] is True
    assert result["selected_label"] == "All devices"


def test_detect_selected_device_location_does_not_treat_room_filter_as_all_devices():
    nodes = [
        _node(
            "모든 기기 모든 기기",
            "",
            {"l": 171, "t": 319, "r": 410, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=True,
            focusable=False,
            effective_clickable=True,
        ),
        _node(
            "지정된 방 없음 지정된 방 없음",
            "",
            {"l": 560, "t": 319, "r": 888, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=False,
            focusable=True,
            effective_clickable=False,
        ),
    ]

    result = device_tab_logic.detect_selected_device_location(nodes)
    candidate = device_tab_logic.select_all_devices_candidate_for_action(nodes)

    assert result["selected"] is False
    assert result["selected_label"] == "지정된 방 없음"
    assert candidate is not None
    assert candidate["stable_label"] == "모든 기기"


def test_detect_selected_device_location_does_not_treat_visible_clickable_all_devices_as_selected():
    nodes = [
        _node(
            "모든 기기 모든 기기",
            "",
            {"l": 171, "t": 319, "r": 410, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=True,
            focusable=True,
            effective_clickable=True,
            accessibility_focused=False,
        ),
        _node(
            "지정된 방 없음 지정된 방 없음",
            "",
            {"l": 560, "t": 319, "r": 888, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=False,
            focusable=True,
            effective_clickable=False,
            accessibility_focused=True,
        ),
    ]

    result = device_tab_logic.detect_selected_device_location(nodes)
    candidate = device_tab_logic.find_all_devices_location_candidate(nodes)

    assert result["selected"] is False
    assert result["selected_label"] == "지정된 방 없음"
    assert result["reason"] == "all_devices_candidate_not_selected"
    assert result["selected_location"]["selection_reason"] == "non_clickable_selected_chip"
    assert candidate is not None
    assert candidate["clickable"] is True


def test_detect_selected_device_location_uses_non_clickable_all_devices_as_selected():
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
    assert result["selected_label"] == "모든 기기"
    assert result["reason"] == "non_clickable_selected_chip"


def test_accessibility_focus_alone_does_not_select_location_chip():
    nodes = [
        _node(
            "모든 기기 모든 기기",
            "",
            {"l": 171, "t": 319, "r": 410, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=True,
            focusable=True,
            effective_clickable=True,
            accessibility_focused=True,
        ),
        _node(
            "지정된 방 없음 지정된 방 없음",
            "",
            {"l": 560, "t": 319, "r": 888, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=True,
            focusable=True,
            effective_clickable=True,
        ),
    ]

    result = device_tab_logic.detect_selected_device_location(nodes)

    assert result["selected"] is False
    assert result["selected_location"] is None


def test_detect_selected_device_location_accepts_state_description_selected():
    nodes = [
        _node(
            "All devices All devices",
            "",
            {"l": 171, "t": 319, "r": 410, "b": 469},
            class_name="android.widget.LinearLayout",
            clickable=True,
            focusable=True,
            effective_clickable=True,
            state_description="Selected",
        )
    ]

    result = device_tab_logic.detect_selected_device_location(nodes)

    assert result["selected"] is True
    assert result["selected_label"] == "All devices"
    assert result["reason"] == "state_description_selected"


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
        _device_card("TV 꺼짐", 42, 1866),
        _device_card("세탁기 꺼짐", 42, 1479),
        _device_card("습도센서 진동 감지됨", 42, 1681),
        _device_card("온습도 센서 진동 감지됨", 42, 2068),
    ]

    smoke = device_tab_logic.find_device_card_by_stable_label(nodes, ["연기", "Smoke sensor"])
    leak = device_tab_logic.find_device_card_by_stable_label(nodes, ["누수", "Water leak sensor"])
    motion = device_tab_logic.find_device_card_by_stable_label(nodes, ["모션센서", "Motion sensor"])
    door_lock = device_tab_logic.find_device_card_by_stable_label(nodes, ["Door Lock"])
    air_purifier = device_tab_logic.find_device_card_by_stable_label(nodes, ["공기청정기", "Air purifier"])
    tv = device_tab_logic.find_device_card_by_stable_label(nodes, ["TV"])
    washer = device_tab_logic.find_device_card_by_stable_label(nodes, ["세탁기", "Washer"])
    humidity = device_tab_logic.find_device_card_by_stable_label(nodes, ["습도센서", "Humidity sensor"])
    temp_humidity = device_tab_logic.find_device_card_by_stable_label(
        nodes,
        ["온습도 센서", "Temperature humidity sensor"],
    )

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
    assert tv is not None
    assert tv["stable_label"] == "TV"
    assert washer is not None
    assert washer["stable_label"] == "세탁기"
    assert humidity is not None
    assert humidity["stable_label"] == "습도센서"
    assert temp_humidity is not None
    assert temp_humidity["stable_label"] == "온습도 센서"


def test_find_device_card_by_stable_label_matches_english_observed_state_suffix_labels():
    nodes = [
        _device_card("연기 Clear", 42, 628),
        _device_card("누수 Dry", 561, 628),
        _device_card("Audio Pause", 42, 1911),
        _device_card("온습도 센서 Vibration detected", 42, 2068),
        _device_card("Camera Connected", 42, 742),
        _device_card("Door Lock Locked", 561, 1015),
        _device_card("TV Off", 42, 1866),
        _device_card("세탁기 Off", 42, 1479),
        _device_card("공기청정기 On", 42, 1479),
        _device_card("Security System Armed (away)", 42, 1015),
    ]

    smoke = device_tab_logic.find_device_card_by_stable_label(nodes, ["연기", "Smoke sensor"])
    leak = device_tab_logic.find_device_card_by_stable_label(nodes, ["누수", "Water leak sensor"])
    audio = device_tab_logic.find_device_card_by_stable_label(nodes, ["Audio", "오디오"])
    temp_humidity = device_tab_logic.find_device_card_by_stable_label(nodes, ["온습도 센서", "Temperature humidity sensor"])
    camera = device_tab_logic.find_device_card_by_stable_label(nodes, ["Camera"])
    door_lock = device_tab_logic.find_device_card_by_stable_label(nodes, ["Door Lock"])
    tv = device_tab_logic.find_device_card_by_stable_label(nodes, ["TV"])
    washer = device_tab_logic.find_device_card_by_stable_label(nodes, ["세탁기", "Washer"])
    air_purifier = device_tab_logic.find_device_card_by_stable_label(nodes, ["공기청정기", "Air purifier"])

    assert smoke is not None
    assert smoke["stable_label"] == "연기"
    assert leak is not None
    assert leak["stable_label"] == "누수"
    assert audio is not None
    assert audio["stable_label"] == "Audio"
    assert temp_humidity is not None
    assert temp_humidity["stable_label"] == "온습도 센서"
    assert camera is not None
    assert camera["stable_label"] == "Camera"
    assert door_lock is not None
    assert door_lock["stable_label"] == "Door Lock"
    assert tv is not None
    assert tv["stable_label"] == "TV"
    assert washer is not None
    assert washer["stable_label"] == "세탁기"
    assert air_purifier is not None
    assert air_purifier["stable_label"] == "공기청정기"


def test_label_contains_state_text_detects_clear_and_dry_suffixes():
    assert device_tab_logic.label_contains_state_text("Clear") is True
    assert device_tab_logic.label_contains_state_text("Dry") is True
    assert device_tab_logic.label_contains_state_text("연기 Clear") is True
    assert device_tab_logic.label_contains_state_text("누수 Dry") is True


def test_humidity_matching_uses_exact_normalized_label_not_substring():
    nodes = [
        _device_card("습도센서 진동 감지됨", 42, 1681),
        _device_card("온습도 센서 진동 감지됨", 42, 2068),
    ]

    humidity = device_tab_logic.find_device_card_by_stable_label(nodes, ["습도센서"])
    temp_humidity = device_tab_logic.find_device_card_by_stable_label(nodes, ["온습도 센서"])
    compact_temp_humidity = device_tab_logic.find_device_card_by_stable_label(nodes, ["온습도센서"])

    assert humidity is not None
    assert humidity["stable_label"] == "습도센서"
    assert temp_humidity is not None
    assert temp_humidity["stable_label"] == "온습도 센서"
    assert compact_temp_humidity is None


def test_find_device_card_by_stable_label_returns_none_for_missing_target():
    nodes = [_device_card("연기 감지 안 됨", 42, 628)]

    assert device_tab_logic.find_device_card_by_stable_label(nodes, ["누수"]) is None


def test_compute_safe_device_card_tap_point_returns_center_when_no_avoid_hit():
    result = device_tab_logic.compute_safe_device_card_tap_point(
        (42, 628, 519, 973),
        [(216, 2112, 864, 2268)],
    )

    assert result is not None
    assert result["point"] == (280, 800)
    assert result["strategy"] == "center"


def test_compute_safe_device_card_tap_point_avoids_assign_room_cta_overlap():
    result = device_tab_logic.compute_safe_device_card_tap_point(
        (42, 2068, 519, 2316),
        [(216, 2112, 864, 2268)],
    )

    assert result is not None
    x, y = result["point"]
    assert 42 < x < 519
    assert 2068 < y < 2316
    assert not (216 <= x <= 864 and 2112 <= y <= 2268)
    assert result["strategy"] != "center"


def test_compute_safe_device_card_tap_point_returns_none_when_card_is_covered():
    result = device_tab_logic.compute_safe_device_card_tap_point(
        (42, 2068, 519, 2316),
        [(0, 2000, 1080, 2400)],
    )

    assert result is None


def test_collect_device_card_tap_avoid_bounds_detects_assign_room_cta_only():
    nodes = [
        _node(
            "방 지정하기",
            "com.samsung.android.oneconnect:id/move_devices_button",
            {"l": 216, "t": 2112, "r": 864, "b": 2268},
            class_name="android.widget.TextView",
        ),
        _node(
            "방 지정하기",
            "com.samsung.android.oneconnect:id/plain_text",
            {"l": 216, "t": 100, "r": 864, "b": 200},
            class_name="android.widget.TextView",
        ),
        _device_card("온습도 센서 진동 감지됨", 42, 2068),
    ]

    candidates = device_tab_logic.collect_device_card_tap_avoid_bounds(nodes)

    assert len(candidates) == 2
    assert candidates[0]["role"] == "device_card_tap_avoid"
    assert {candidate["avoid_reason"] for candidate in candidates} == {"move_devices_button", "assign_room_cta"}


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
