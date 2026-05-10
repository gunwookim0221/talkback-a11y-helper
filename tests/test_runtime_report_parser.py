from pathlib import Path
import shutil
import uuid

import pytest

from tools import runtime_report_parser as parser


@pytest.fixture
def tmp_path():
    base = Path.cwd() / ".test_tmp" / f"runtime_report_parser_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=False)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _write_log(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _baseline_log(
    *,
    stop_reason: str = "safety_limit",
    labels: str = "Medication\nHospital\nEvent\n",
    fatal_line: str = "",
    total_steps: int = 39,
    filtered_rows: int = 37,
    raw_rows: int = 39,
) -> str:
    return f"""
[STOP][summary] reason={stop_reason}
[PERF][scenario_summary] total_steps={total_steps}
[SAVE] filtered rows={filtered_rows} raw rows={raw_rows}
{labels}
[STEP][local_tab_force_navigation_set]
[STEP][local_tab_force_navigation_set]
[STEP][local_tab_force_navigation_set]
[STEP][local_tab_commit]
{fatal_line}
"""


def test_runtime_report_parser_baseline_pass(tmp_path):
    path = _write_log(tmp_path, "baseline.log", _baseline_log(labels="가족 구성원 추가\n프로필 보기\n지금 활동 중\n"))

    summary = parser.parse_log(path)

    assert summary.fatal is False
    assert summary.stop_reason == "safety_limit"
    assert summary.total_steps == 39
    assert summary.raw_rows == 39
    assert summary.filtered_rows == 37
    assert summary.ready_matched_groups == ("add_family_member", "profile", "active_now")
    assert summary.local_tab_force_navigation_set >= 1
    assert summary.local_tab_commit == 1
    assert summary.baseline_pass is True
    assert summary.baseline_reason == "ok"


def test_runtime_report_parser_fails_when_required_labels_missing(tmp_path):
    path = _write_log(
        tmp_path,
        "missing_labels.log",
        _baseline_log(labels="Event\n"),
    )

    summary = parser.parse_log(path)

    assert summary.reached_medication is False
    assert summary.reached_hospital is False
    assert summary.baseline_pass is False
    assert "missing_" in summary.baseline_reason


def test_runtime_report_parser_detects_fatal_signals(tmp_path):
    fatal_lines = [
        "Traceback (most recent call last):",
        "[ERROR] failed to collect focus",
        "adb command timed out after 30s",
    ]
    for index, fatal_line in enumerate(fatal_lines):
        path = _write_log(
            tmp_path,
            f"fatal_{index}.log",
            _baseline_log(fatal_line=fatal_line),
        )

        summary = parser.parse_log(path)

        assert summary.fatal is True
        assert summary.baseline_pass is False
        assert summary.baseline_reason == "fatal_detected"


def test_runtime_report_parser_fails_on_wrong_stop_reason(tmp_path):
    path = _write_log(
        tmp_path,
        "wrong_stop.log",
        _baseline_log(stop_reason="repeat_no_progress", labels="Event\n"),
    )

    summary = parser.parse_log(path)

    assert summary.stop_reason == "repeat_no_progress"
    assert summary.baseline_pass is False
    assert summary.baseline_reason == "wrong_stop_reason"


def test_runtime_report_parser_extracts_counts(tmp_path):
    path = _write_log(
        tmp_path,
        "counts.log",
        _baseline_log(total_steps=43, filtered_rows=40, raw_rows=42),
    )

    summary = parser.parse_log(path)

    assert summary.total_steps == 43
    assert summary.raw_rows == 42
    assert summary.filtered_rows == 40


def test_runtime_report_parser_aggregates_multiple_logs(tmp_path, capsys):
    passing = parser.parse_log(
        _write_log(tmp_path, "pass.log", _baseline_log(labels="가족 구성원 추가\n프로필 보기\n"))
    )
    failing = parser.parse_log(
        _write_log(
            tmp_path,
            "fail.log",
            _baseline_log(labels="Event\n"),
        )
    )

    parser.print_aggregate([passing, failing])

    output = capsys.readouterr().out
    assert "[BASELINE][aggregate]" in output
    assert "runs=2" in output
    assert "passed=1" in output
    assert "failed=1" in output
    assert "fail.log" in output


def test_runtime_report_parser_default_uses_family_care_labels(tmp_path):
    path = _write_log(
        tmp_path,
        "default_family_missing.log",
        _baseline_log(labels="Event\n"),
    )

    summary = parser.parse_log(path)

    assert summary.scenario == "life_family_care_plugin"
    assert summary.ready_expected_labels == ("add_family_member", "profile", "active_now", "me")
    assert summary.reached_labels["profile"] is False
    assert summary.baseline_pass is False
    assert summary.baseline_status == "baseline_fail"
    assert summary.detected_state == "unknown"
    assert summary.baseline_reason == "missing_add_family_member"


def test_runtime_report_parser_scenario_family_care_labels(tmp_path):
    path = _write_log(tmp_path, "family.log", _baseline_log(labels="가족 구성원 추가\n프로필 보기\n"))

    summary = parser.parse_log(path, scenario="life_family_care_plugin")

    assert summary.scenario == "life_family_care_plugin"
    assert summary.ready_matched_groups == ("add_family_member", "profile")
    assert summary.baseline_pass is True
    assert summary.baseline_reason == "ok"


def test_runtime_report_parser_custom_empty_expected_labels_override_scenario(tmp_path):
    path = _write_log(
        tmp_path,
        "air.log",
        _baseline_log(labels=""),
    )

    summary = parser.parse_log(path, scenario="life_air_care_plugin", expected_labels=[])

    assert summary.scenario == "life_air_care_plugin"
    assert summary.expected_labels == ()
    assert summary.reached_labels == {}
    assert summary.baseline_pass is True
    assert summary.baseline_status == "baseline_pass"
    assert summary.baseline_reason == "ok_no_expected_labels"


def test_runtime_report_parser_custom_expected_labels_override_scenario(tmp_path):
    path = _write_log(
        tmp_path,
        "custom.log",
        _baseline_log(labels="Medication\n"),
    )

    summary = parser.parse_log(
        path,
        scenario="life_air_care_plugin",
        expected_labels=["Medication", "Hospital"],
    )

    assert summary.scenario == "life_air_care_plugin"
    assert summary.expected_labels == ("Medication", "Hospital")
    assert summary.reached_labels["Medication"] is True
    assert summary.reached_labels["Hospital"] is False
    assert summary.baseline_pass is False
    assert summary.baseline_reason == "missing_hospital"


def test_runtime_report_parser_output_includes_expected_labels(tmp_path, capsys):
    path = _write_log(tmp_path, "family_output.log", _baseline_log(labels="가족 구성원 추가\n프로필 보기\n"))
    summary = parser.parse_log(path, scenario="life_family_care_plugin")

    parser.print_summary(summary, include_path=False)

    output = capsys.readouterr().out
    assert "scenario=life_family_care_plugin" in output
    assert "expected_labels=add_family_member,profile,active_now,me" in output
    assert "baseline_status=baseline_pass" in output
    assert "detected_state=ready" in output
    assert "ready_expected_count=4" in output
    assert "ready_matched_count=2" in output
    assert "ready_matched_labels=add_family_member,profile" in output
    assert "initial_expected_count=0" in output
    assert "initial_matched_count=0" in output
    assert "reached_add_family_member=True" in output
    assert "reached_profile=True" in output


def test_runtime_report_parser_legacy_list_structure_ready_threshold(tmp_path, monkeypatch):
    monkeypatch.setitem(
        parser.SCENARIO_EXPECTED_LABELS,
        "life_family_care_plugin",
        ["Medication", "Hospital", "Event"],
    )
    path = _write_log(
        tmp_path,
        "legacy_ready.log",
        _baseline_log(labels="Medication\nHospital\n"),
    )

    summary = parser.parse_log(path, scenario="life_family_care_plugin")

    assert summary.ready_matched_labels == ("Medication", "Hospital")
    assert summary.baseline_status == "baseline_pass"
    assert summary.detected_state == "ready"
    assert summary.baseline_pass is True


def test_runtime_report_parser_structured_ready_threshold(tmp_path, monkeypatch):
    monkeypatch.setitem(
        parser.SCENARIO_EXPECTED_LABELS,
        "life_air_care_plugin",
        {
            "ready": ["Air quality", "Outdoor air quality", "Indoor air quality"],
            "initial": ["Get started", "Start"],
        },
    )
    path = _write_log(
        tmp_path,
        "structured_ready.log",
        _baseline_log(labels="Air quality\nOutdoor air quality\n"),
    )

    summary = parser.parse_log(path, scenario="life_air_care_plugin")

    assert summary.ready_matched_labels == ("Air quality", "Outdoor air quality")
    assert summary.initial_matched_labels == ()
    assert summary.baseline_status == "baseline_pass"
    assert summary.detected_state == "ready"


def test_runtime_report_parser_structured_initial_state(tmp_path, monkeypatch):
    monkeypatch.setitem(
        parser.SCENARIO_EXPECTED_LABELS,
        "life_air_care_plugin",
        {
            "ready": ["Air quality", "Outdoor air quality"],
            "initial": ["Set geolocation to monitor outdoor air quality", "Dismiss"],
        },
    )
    path = _write_log(
        tmp_path,
        "initial.log",
        _baseline_log(labels="Set geolocation to monitor outdoor air quality\n"),
    )

    summary = parser.parse_log(path, scenario="life_air_care_plugin")

    assert summary.ready_matched_labels == ()
    assert summary.initial_matched_labels == ("Set geolocation to monitor outdoor air quality",)
    assert summary.baseline_status == "initial_state"
    assert summary.detected_state == "initial"
    assert summary.baseline_pass is True
    assert summary.baseline_reason == "initial_state_detected"


def test_runtime_report_parser_ready_wins_over_initial(tmp_path, monkeypatch):
    monkeypatch.setitem(
        parser.SCENARIO_EXPECTED_LABELS,
        "life_air_care_plugin",
        {
            "ready": ["Air quality", "Outdoor air quality"],
            "initial": ["Get started"],
        },
    )
    path = _write_log(
        tmp_path,
        "ready_and_initial.log",
        _baseline_log(labels="Air quality\nOutdoor air quality\nGet started\n"),
    )

    summary = parser.parse_log(path, scenario="life_air_care_plugin")

    assert summary.ready_matched_labels == ("Air quality", "Outdoor air quality")
    assert summary.initial_matched_labels == ("Get started",)
    assert summary.baseline_status == "baseline_pass"
    assert summary.detected_state == "ready"


def test_runtime_report_parser_fatal_overrides_ready_and_initial(tmp_path, monkeypatch):
    monkeypatch.setitem(
        parser.SCENARIO_EXPECTED_LABELS,
        "life_air_care_plugin",
        {
            "ready": ["Air quality", "Outdoor air quality"],
            "initial": ["Get started"],
        },
    )
    path = _write_log(
        tmp_path,
        "fatal_ready.log",
        _baseline_log(
            labels="Air quality\nOutdoor air quality\nGet started\n",
            fatal_line="Traceback (most recent call last):",
        ),
    )

    summary = parser.parse_log(path, scenario="life_air_care_plugin")

    assert summary.fatal is True
    assert summary.baseline_status == "baseline_fail"
    assert summary.detected_state == "unknown"
    assert summary.baseline_pass is False
    assert summary.baseline_reason == "fatal_detected"


def test_runtime_report_parser_suggests_top_labels():
    text = """
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Hospital' speech='Hospital'
[STEP] END visible='Event' speech='Event'
visible_label='Event'
"""

    candidates = parser.extract_label_candidates(text)
    suggestions = parser.suggest_expected_labels(text)

    assert candidates["Medication"] == 4
    assert candidates["Hospital"] == 2
    assert candidates["Event"] == 3
    assert suggestions[:3] == ["Medication", "Event", "Hospital"]


def test_runtime_report_parser_suggest_labels_filters_noise():
    text = """
[STEP] END visible='Home' speech='Life'
[STEP] END visible='Map' speech='Current location'
[STEP] END visible='Navigate' speech='Back'
[STEP] END visible='Medication' speech='Medication'
merged_announcement='123 Main Street'
visible_label='9:51 am'
speech='0 steps / 6000 %'
"""

    candidates = parser.extract_label_candidates(text)

    assert "Medication" in candidates
    assert "Home" not in candidates
    assert "Life" not in candidates
    assert "Map" not in candidates
    assert "Current location" not in candidates
    assert "Navigate" not in candidates
    assert "123 Main Street" not in candidates
    assert "9:51 am" not in candidates
    assert "0 steps / 6000 %" not in candidates


def test_runtime_report_parser_suggest_label_limit():
    text = """
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Hospital' speech='Hospital'
[STEP] END visible='Event' speech='Event'
"""

    suggestions = parser.suggest_expected_labels(text, limit=2)

    assert len(suggestions) == 2


def test_runtime_report_parser_suggest_labels_outputs_python_snippet(capsys):
    candidates = parser.extract_label_candidates(
        """
[STEP] END visible='Medication' speech='Medication'
[STEP] END visible='Hospital' speech='Hospital'
"""
    )

    parser.print_label_suggestions(
        candidates,
        scenario="life_family_care_plugin",
        limit=2,
    )

    output = capsys.readouterr().out
    assert "[LABEL_SUGGESTION][python]" in output
    assert '"life_family_care_plugin": [' in output
    assert "'Medication'" in output
    assert "'Hospital'" in output


def test_runtime_report_parser_suggest_labels_does_not_change_baseline_pass(tmp_path):
    path = _write_log(
        tmp_path,
        "baseline.log",
        _baseline_log(
            labels="""
[STEP] END visible='가족 구성원 추가' speech='가족 구성원 추가'
[STEP] END visible='프로필 보기' speech='프로필 보기'
[STEP] END visible='지금 활동 중' speech='지금 활동 중'
"""
        ),
    )

    before = parser.parse_log(path)
    candidates = parser.extract_label_candidates(path.read_text(encoding="utf-8"))
    parser.suggest_expected_labels(path.read_text(encoding="utf-8"))
    after = parser.parse_log(path)

    assert candidates
    assert before.baseline_pass is True
    assert after.baseline_pass is before.baseline_pass
    assert after.baseline_reason == before.baseline_reason


def test_runtime_report_parser_semantic_alias_group_matches_korean_energy(tmp_path):
    path = _write_log(
        tmp_path,
        "energy_ko.log",
        _baseline_log(labels="에너지\n기기 에너지 사용량\n모니터링\n절약\n"),
    )

    summary = parser.parse_log(path, scenario="life_energy_plugin")

    assert summary.baseline_pass is True
    assert "energy_title" in summary.ready_matched_groups
    assert "device_energy_usage" in summary.ready_matched_groups
    assert "monitor" in summary.ready_matched_groups
    assert "save" in summary.ready_matched_groups
    assert "device_energy_usage:기기 에너지 사용량" in summary.ready_match_details


def test_runtime_report_parser_semantic_alias_group_matches_korean_plant(tmp_path):
    path = _write_log(
        tmp_path,
        "plant_ko.log",
        _baseline_log(labels="내 식물\n자동화\n한 장소에서 많은 식물을 키우고 있나요?\n"),
    )

    summary = parser.parse_log(path, scenario="life_plant_care_plugin")

    assert summary.baseline_pass is True
    assert "my_plants" in summary.ready_matched_groups
    assert "routines" in summary.ready_matched_groups
    assert "many_plants" in summary.ready_matched_groups


def test_runtime_report_parser_semantic_alias_group_matches_korean_air(tmp_path):
    path = _write_log(
        tmp_path,
        "air_ko.log",
        _baseline_log(labels="실외 공기(미세먼지)\n실외 공기질 모니터링을 위해 위치를 설정하세요\n"),
    )

    summary = parser.parse_log(path, scenario="life_air_care_plugin")

    assert summary.baseline_pass is True
    assert summary.ready_matched_groups == ("outdoor_air_quality", "set_geolocation")


def test_runtime_report_parser_settings_requires_scoped_alias_not_generic_setting(tmp_path):
    generic_path = _write_log(tmp_path, "settings_generic.log", _baseline_log(labels="설정\n"))
    scoped_path = _write_log(tmp_path, "settings_scoped.log", _baseline_log(labels="스마트싱스 설정\n앱 업데이트\n"))

    generic_summary = parser.parse_log(generic_path, scenario="settings_entry_example")
    scoped_summary = parser.parse_log(scoped_path, scenario="settings_entry_example")

    assert generic_summary.baseline_pass is False
    assert scoped_summary.baseline_pass is True
    assert "smartthings_settings" in scoped_summary.ready_matched_groups


def test_runtime_report_parser_settings_accepts_update_app_alias_without_generic_update(tmp_path):
    generic_path = _write_log(tmp_path, "settings_update_generic.log", _baseline_log(labels="Update\n"))
    scoped_path = _write_log(
        tmp_path,
        "settings_update_app.log",
        _baseline_log(labels="SmartThings settings\nUpdate app\n"),
    )

    generic_summary = parser.parse_log(generic_path, scenario="settings_entry_example")
    scoped_summary = parser.parse_log(scoped_path, scenario="settings_entry_example")

    assert generic_summary.baseline_pass is False
    assert scoped_summary.baseline_pass is True
    assert "app_update" in scoped_summary.ready_matched_groups


def test_runtime_report_parser_reads_utf8_korean_with_replacement_errors(tmp_path):
    path = tmp_path / "utf8.log"
    path.write_bytes(_baseline_log(labels="실외 공기질\n").encode("utf-8") + b"\xff")

    summary = parser.parse_log(path, scenario="life_air_care_plugin")

    assert summary.fatal is False
    assert "outdoor_air_quality" in summary.ready_matched_groups


def test_runtime_report_parser_suggest_labels_preserves_korean(capsys):
    candidates = parser.extract_label_candidates(
        """
[STEP] END visible='기기 에너지 사용량' speech='기기 에너지 사용량'
[STEP] END visible='내 식물' speech='내 식물'
"""
    )

    parser.print_label_suggestions(candidates, scenario="life_energy_plugin", limit=2)

    output = capsys.readouterr().out
    assert "기기 에너지 사용량" in output
    assert "내 식물" in output


def test_runtime_report_parser_semantic_alias_group_matches_korean_pet(tmp_path):
    path = _write_log(
        tmp_path,
        "pet_ko.log",
        _baseline_log(labels="프로필 추가\n반려동물 정보를 입력하세요\n반려동물 위치 확인\n활동\n케어\n"),
    )

    summary = parser.parse_log(path, scenario="life_pet_care_plugin")

    assert summary.baseline_pass is True
    assert "add_profile" in summary.ready_matched_groups
    assert "enter_pet_info" in summary.ready_matched_groups
    assert "pet_location" in summary.ready_matched_groups


def test_runtime_report_parser_semantic_alias_group_matches_korean_family(tmp_path):
    path = _write_log(
        tmp_path,
        "family_ko.log",
        _baseline_log(labels="가족 구성원 추가\n프로필 보기\n지금 활동 중\n나\n"),
    )

    summary = parser.parse_log(path, scenario="life_family_care_plugin")

    assert summary.baseline_pass is True
    assert "add_family_member" in summary.ready_matched_groups
    assert "profile" in summary.ready_matched_groups
    assert "active_now" in summary.ready_matched_groups


def test_runtime_report_parser_semantic_alias_group_matches_korean_home_care(tmp_path):
    path = _write_log(
        tmp_path,
        "home_care_ko.log",
        _baseline_log(labels="홈 케어\n삼성 가전 기기\n똑똑한 관리\n"),
    )

    summary = parser.parse_log(path, scenario="life_home_care_plugin")

    assert summary.baseline_pass is True
    assert "home_care" in summary.ready_matched_groups
    assert "samsung_appliances" in summary.ready_matched_groups
    assert "smart_management" in summary.ready_matched_groups


def test_runtime_report_parser_semantic_alias_group_matches_korean_clothing_care(tmp_path):
    path = _write_log(
        tmp_path,
        "clothing_care_ko.log",
        _baseline_log(labels="클로딩 케어\n에어드레서\n슈드레서\n"),
    )

    summary = parser.parse_log(path, scenario="life_clothing_care_plugin")

    assert summary.baseline_pass is True
    assert "clothing_care" in summary.ready_matched_groups
    assert "airdresser" in summary.ready_matched_groups
    assert "shoedresser" in summary.ready_matched_groups


def test_runtime_report_parser_generic_single_korean_labels_do_not_pass(tmp_path):
    family_path = _write_log(tmp_path, "family_generic.log", _baseline_log(labels="나\n"))
    clothing_path = _write_log(tmp_path, "clothing_generic.log", _baseline_log(labels="세탁\n"))

    family_summary = parser.parse_log(family_path, scenario="life_family_care_plugin")
    clothing_summary = parser.parse_log(clothing_path, scenario="life_clothing_care_plugin")

    assert family_summary.baseline_pass is False
    assert clothing_summary.baseline_pass is False


def test_runtime_report_parser_semantic_alias_group_matches_korean_find_and_video(tmp_path):
    find_path = _write_log(tmp_path, "find_ko.log", _baseline_log(labels="파인드\n"))
    video_path = _write_log(tmp_path, "video_ko.log", _baseline_log(labels="비디오\n"))

    find_summary = parser.parse_log(find_path, scenario="life_find_plugin")
    video_summary = parser.parse_log(video_path, scenario="life_video_plugin")

    assert find_summary.baseline_pass is True
    assert "find_title" in find_summary.ready_matched_groups
    assert video_summary.baseline_pass is True
    assert "video_title" in video_summary.ready_matched_groups


def test_runtime_report_parser_find_and_video_avoid_dynamic_korean_aliases(tmp_path):
    find_path = _write_log(tmp_path, "find_dynamic.log", _baseline_log(labels="새로고침\n최근 위치 확인: 4분 전\n"))
    video_path = _write_log(tmp_path, "video_dynamic.log", _baseline_log(labels="오늘은 녹화된 클립이 없습니다\n"))

    find_summary = parser.parse_log(find_path, scenario="life_find_plugin")
    video_summary = parser.parse_log(video_path, scenario="life_video_plugin")

    assert find_summary.baseline_pass is False
    assert video_summary.baseline_pass is False


def test_runtime_report_parser_semantic_alias_group_matches_korean_food(tmp_path):
    path = _write_log(tmp_path, "food_ko.log", _baseline_log(labels="푸드\nSmart Things Cooking\n"))

    summary = parser.parse_log(path, scenario="life_food_plugin")

    assert summary.baseline_pass is True
    assert "food_title" in summary.ready_matched_groups


def test_runtime_report_parser_food_and_energy_avoid_dynamic_korean_aliases(tmp_path):
    food_path = _write_log(tmp_path, "food_dynamic.log", _baseline_log(labels="추천 레시피\n오늘의 메뉴\n"))
    energy_path = _write_log(tmp_path, "energy_dynamic.log", _baseline_log(labels="현재 사용량 0 Wh\n"))

    food_summary = parser.parse_log(food_path, scenario="life_food_plugin")
    energy_summary = parser.parse_log(energy_path, scenario="life_energy_plugin")

    assert food_summary.baseline_pass is False
    assert energy_summary.baseline_pass is False


def test_runtime_report_parser_semantic_alias_group_matches_korean_home_monitor(tmp_path):
    path = _write_log(tmp_path, "home_monitor_ko.log", _baseline_log(labels="홈 모니터\n보안\n연기\n누수\n"))

    summary = parser.parse_log(path, scenario="life_home_monitor_plugin")

    assert summary.baseline_pass is True
    assert "home_monitor_title" in summary.ready_matched_groups
    assert "security" in summary.ready_matched_groups
    assert "smoke" in summary.ready_matched_groups
    assert "water_leak" in summary.ready_matched_groups


def test_runtime_report_parser_semantic_alias_group_matches_korean_music_sync_repeat_stop(tmp_path):
    path = _write_log(
        tmp_path,
        "music_sync_ko.log",
        _baseline_log(
            stop_reason="repeat_no_progress",
            labels="조명을 음악에 어울리도록 동기화하세요\n",
        ),
    )

    summary = parser.parse_log(path, scenario="life_music_sync_plugin")

    assert summary.baseline_pass is True
    assert summary.baseline_reason == "ok"
    assert summary.stop_reason == "repeat_no_progress"
    assert summary.ready_matched_groups == ("music_sync_title",)


def test_runtime_report_parser_home_monitor_and_music_sync_avoid_generic_korean_aliases(tmp_path):
    home_monitor_path = _write_log(tmp_path, "home_monitor_generic.log", _baseline_log(labels="보안\n"))
    music_sync_path = _write_log(tmp_path, "music_sync_generic.log", _baseline_log(labels="음악\n"))

    home_monitor_summary = parser.parse_log(home_monitor_path, scenario="life_home_monitor_plugin")
    music_sync_summary = parser.parse_log(music_sync_path, scenario="life_music_sync_plugin")

    assert home_monitor_summary.baseline_pass is False
    assert music_sync_summary.baseline_pass is False


def test_runtime_report_parser_english_home_and_clothing_regression(tmp_path):
    home_path = _write_log(tmp_path, "home_en.log", _baseline_log(labels="Home Care\nDevice care\nUsage guide\n"))
    clothing_path = _write_log(
        tmp_path,
        "clothing_en.log",
        _baseline_log(labels="Clothing Care\nIt's time to care for your blanket\nTry Bedding cycle\n"),
    )

    home_summary = parser.parse_log(home_path, scenario="life_home_care_plugin")
    clothing_summary = parser.parse_log(clothing_path, scenario="life_clothing_care_plugin")

    assert home_summary.baseline_pass is True
    assert clothing_summary.baseline_pass is True
