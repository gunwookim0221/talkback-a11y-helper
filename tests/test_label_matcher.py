from tb_runner.label_matcher import canonicalize_label, expand_verify_token_aliases, matches_alias, normalize_label


def test_normalize_label_handles_none_and_collapses_text():
    assert normalize_label(None) == ""
    assert normalize_label("  More   Options,\nButton  ") == "more options"


def test_matches_english_and_korean_exact_aliases():
    assert matches_alias("Home", "bottom_home")
    assert matches_alias("홈", "bottom_home")
    assert matches_alias("Selected", "selected")
    assert matches_alias("선택됨", "selected")


def test_more_options_matches_role_suffix_and_korean():
    assert matches_alias("More options", "more_options")
    assert matches_alias("More options, Button", "more_options")
    assert matches_alias("더보기", "more_options")


def test_bottom_tab_canonicalize_english_and_korean_labels():
    assert canonicalize_label("Selected, Home, Tab 1 of 5", domain="bottom_tab") == "home"
    assert canonicalize_label("Devices, Tab 2 of 5", domain="bottom_tab") == "devices"
    assert canonicalize_label("선택됨, 라이프, 탭 3/5", domain="bottom_tab") == "life"
    assert canonicalize_label("자동화", domain="bottom_tab") == "routines"
    assert canonicalize_label("메뉴", domain="bottom_tab") == "menu"


def test_navigate_up_and_back_are_separate_aliases():
    assert matches_alias("Navigate up", "navigate_up")
    assert matches_alias("위로 이동", "navigate_up")
    assert matches_alias("상위 메뉴로 이동", "navigate_up")
    assert not matches_alias("뒤로", "navigate_up")
    assert matches_alias("Back", "back")
    assert matches_alias("뒤로", "back")
    assert not matches_alias("Navigate up", "back")


def test_contains_and_token_modes():
    assert matches_alias("Selected, Home, Tab 1 of 5", "bottom_home", mode="contains")
    assert matches_alias("Selected, Home, Tab 1 of 5", "bottom_home", mode="token")
    assert matches_alias("기기 추가 버튼", "add_device", mode="token")
    assert not matches_alias("Restart", "start", mode="token")
    assert matches_alias("Tap Start to continue", "start", mode="token")


def test_unknown_key_and_unknown_mode_are_safe():
    assert not matches_alias("Home", "missing_key")
    assert not matches_alias("Home", "bottom_home", mode="regex")
    assert canonicalize_label("Home", domain="unknown") is None


def test_minimal_korean_cta_aliases():
    assert matches_alias("시작", "start")
    assert matches_alias("닫기", "dismiss")
    assert matches_alias("다음에", "next_time")
    assert matches_alias("나중에", "next_time")


def test_token_mode_avoids_broad_substring_false_positives():
    assert not matches_alias("startled", "start", mode="token")
    assert not matches_alias("홈카메라", "bottom_home", mode="token")
    assert not matches_alias("더보기로 이동", "more_options", mode="token")


def test_local_tab_canonicalizer_strips_notification_suffixes_only():
    assert canonicalize_label("Monitor", domain="local_tab") == "monitor"
    assert canonicalize_label("모니터링", domain="local_tab") == "monitor"
    assert canonicalize_label("Save", domain="local_tab") == "save"
    assert canonicalize_label("절약", domain="local_tab") == "save"
    assert canonicalize_label("Activity", domain="local_tab") == "activity"
    assert canonicalize_label("Activity New notification", domain="local_tab") == "activity"
    assert canonicalize_label("Activity New notifications", domain="local_tab") == "activity"
    assert canonicalize_label("활동 새 알림", domain="local_tab") == "activity"
    assert canonicalize_label("활동 알림", domain="local_tab") == "activity"
    assert canonicalize_label("My plants", domain="local_tab") == "my_plants"
    assert canonicalize_label("내 식물", domain="local_tab") == "my_plants"
    assert canonicalize_label("Routines", domain="local_tab") == "routines"
    assert canonicalize_label("자동화", domain="local_tab") == "routines"
    assert canonicalize_label("Monitor", domain="local_tab") == "monitor"


def test_bottom_and_local_tab_domains_keep_separate_meaning():
    assert canonicalize_label("자동화", domain="bottom_tab") == "routines"
    assert canonicalize_label("자동화", domain="local_tab") == "routines"
    assert canonicalize_label("내 식물", domain="bottom_tab") is None


def test_verify_token_aliases_are_plugin_scoped_expansions():
    air_aliases = expand_verify_token_aliases(["outdoor air quality"])
    assert "outdoor air quality" in air_aliases
    assert "실외 공기질" in air_aliases
    assert "실외 공기(미세먼지)" in air_aliases

    settings_aliases = expand_verify_token_aliases(["smartthings settings"])
    assert "smartthings settings" in settings_aliases
    assert "스마트싱스 설정" in settings_aliases
    assert "설정" not in settings_aliases

    energy_aliases = expand_verify_token_aliases(["monitor"])
    assert "monitor" in energy_aliases
    assert "모니터링" in energy_aliases

    plant_aliases = expand_verify_token_aliases(["my plants"])
    assert "my plants" in plant_aliases
    assert "내 식물" in plant_aliases

    home_aliases = expand_verify_token_aliases(["home care", "home appliances"])
    assert "home care" in home_aliases
    assert "홈 케어" in home_aliases
    assert "삼성 가전 기기" in home_aliases

    clothing_aliases = expand_verify_token_aliases(["clothing care", "shoe care"])
    assert "clothing care" in clothing_aliases
    assert "의류 관리" in clothing_aliases
    assert "클로딩 케어" in clothing_aliases
    assert "세탁" not in clothing_aliases
    assert "건조" not in clothing_aliases
    assert "슈드레서" in clothing_aliases

    find_aliases = expand_verify_token_aliases(["smart find", "find"])
    assert "파인드" in find_aliases
    assert "최근 위치 확인" not in find_aliases
    assert "새로고침" not in find_aliases

    video_aliases = expand_verify_token_aliases(["smart video", "video"])
    assert "비디오" in video_aliases
    assert "녹화" not in video_aliases


def test_negative_verify_token_aliases_are_minimal():
    assert "기기 추가" in expand_verify_token_aliases(["add device"])
    assert "다음에" in expand_verify_token_aliases(["not now"])
    assert "나중에" in expand_verify_token_aliases(["next time"])
    assert "닫기" in expand_verify_token_aliases(["dismiss"])
    assert "닫기" not in expand_verify_token_aliases(["air care"])
