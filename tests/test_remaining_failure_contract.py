from unittest.mock import Mock
import pytest
from tb_runner import collection_flow as flow, anchor_logic


def test_destination_body_retains_visible_resource_identity():
    client = Mock()
    client.dump_tree.return_value = [
        {'viewIdResourceName': '0_ProfileCard_add_profile_button', 'text': '프로필 추가', 'isVisibleToUser': True},
        {'viewIdResourceName': 'hidden_profile', 'text': 'hidden', 'isVisibleToUser': False},
    ]
    body = flow._collect_post_open_visible_text(client, None)
    assert '0_ProfileCard_add_profile_button' in body
    assert '프로필 추가' in body
    assert 'hidden' not in body
    assert flow._matches_post_open_verify({'verify_tokens': ['profile']}, '', '', '', extra_candidates=[body])
    assert not flow._matches_post_open_verify({'verify_tokens': ['food']}, '', '', '', extra_candidates=[body])
    client.dump_tree.assert_called_once_with(dev=None)


@pytest.mark.parametrize('context, labels, expected_hit', [
    ({'type': 'screen_text', 'text_regex': r'(?i).*smartthings settings.*|.*스마트싱스\s*설정.*'}, '스마트싱스 설정', False),
    ({'type': 'screen_text', 'text_regex': r'(?i).*smartthings settings.*'}, 'SmartThings settings', False),
    ({'type': 'screen_text', 'text_regex': r'(?i).*smartthings settings.*'}, 'SmartThings settings notice', True),
    ({'type': 'screen_text', 'text_regex': r'(?i).*camera.*'}, 'SmartThings settings', True),
    ({'type': 'selected_bottom_tab', 'text_regex': r'.*settings.*'}, 'SmartThings settings', True),
    ({}, 'SmartThings settings', True),
])
def test_shell_boundary_respects_explicit_destination_only(context, labels, expected_hit):
    cfg = {'scenario_id': 'example_plugin', 'group': 'plugin_screen', 'screen_context_mode': 'new_screen', 'context_verify': context}
    hit, _, reason = flow._row_plugin_shell_chrome_boundary({'visible_label': labels}, cfg)
    assert hit is expected_hit
    assert reason == ('shell_chrome_label' if hit else 'expected_destination_label')


def test_destination_context_never_overrides_shell_resource_boundary():
    cfg = {'scenario_id': 'example_plugin', 'group': 'plugin_screen', 'screen_context_mode': 'new_screen', 'context_verify': {'type': 'screen_text', 'text_regex': r'.*settings.*'}}
    hit, _, reason = flow._row_plugin_shell_chrome_boundary({'visible_label': 'SmartThings settings', 'focus_view_id': 'com.samsung.android.oneconnect:id/tab_title'}, cfg)
    assert hit and reason == 'shell_chrome_resource'


def test_anchor_prefers_focusable_match_without_relaxing_score():
    def candidate(score, focusable, top):
        return {'score': score, 'candidate': {'focusable': focusable, 'top': top, 'left': 0}}
    inert = candidate(70, False, 100)
    focusable = candidate(70, True, 300)
    assert anchor_logic.choose_best_anchor_candidate([inert, focusable]) is focusable
    stronger = candidate(100, False, 10)
    assert anchor_logic.choose_best_anchor_candidate([stronger, focusable]) is stronger


@pytest.mark.parametrize('label', ['Dismiss', '닫기'])
def test_root_fallback_excludes_top_dismiss_but_keeps_plugin_and_body_cta(label):
    candidate = {'text': label, 'announcement': label, 'class_name': 'android.view.View', 'top': 6, 'bottom': 150, 'left': 903, 'right': 1047}
    assert anchor_logic._is_fallback_chrome_candidate(candidate, 1080, 2640, exclude_top_dismiss=True)
    assert not anchor_logic._is_fallback_chrome_candidate(candidate, 1080, 2640)
    body = {**candidate, 'top': 1200, 'bottom': 1344}
    assert not anchor_logic._is_fallback_chrome_candidate(body, 1080, 2640, exclude_top_dismiss=True)


def test_root_fallback_selects_content_instead_of_stale_top_dismiss():
    close = {'text': '닫기', 'announcement': '닫기', 'class_name': 'android.view.View', 'top': 6, 'bottom': 150, 'left': 903, 'right': 1047, 'focusable': True, 'clickable': True}
    content = {'text': 'Current location', 'announcement': 'Current location', 'resource_id': 'location', 'top': 200, 'bottom': 350, 'left': 30, 'right': 600, 'focusable': True, 'clickable': True}
    # Use a content title with no chrome alias; the screen includes its full height.
    content.update(text='Living room', announcement='Living room', resource_id='room_title')
    frame = {'text': '', 'class_name': 'android.widget.FrameLayout', 'top': 0, 'bottom': 2640, 'left': 0, 'right': 1080, 'focusable': False, 'clickable': False}
    before, _, _ = anchor_logic._pick_top_content_fallback_candidate([close, content, frame])
    after, _, _ = anchor_logic._pick_top_content_fallback_candidate([close, content, frame], exclude_top_dismiss=True)
    assert before is close
    assert after is content


def _transition_fixture(monkeypatch, *, variant='destination', scenario='example_plugin'):
    from unittest.mock import Mock
    nodes = [
        {'text': '상위 메뉴로 이동', 'className': 'android.widget.Button', 'viewIdResourceName': 'back', 'isVisibleToUser': True},
        {'text': '프로필 추가', 'className': 'android.view.View', 'viewIdResourceName': '0_ProfileCard_add_profile_button', 'isVisibleToUser': True},
    ]
    if variant == 'global_nav':
        nodes.append({'text': '라이프', 'viewIdResourceName': 'com.samsung.android.oneconnect:id/menu_services', 'isVisibleToUser': True})
    elif variant == 'without_up':
        nodes = nodes[1:]
    elif variant == 'wrong_destination':
        nodes[1]['text'] = 'wrong destination'
    elif variant == 'unmatched_body':
        nodes[1].update(text='다른 서비스', viewIdResourceName='other_service')
    client = Mock()
    client.dump_tree.return_value = nodes
    client.get_focus.return_value = {}
    monkeypatch.setattr(flow, '_extract_window_focus_line', lambda *args: 'same-window')
    monkeypatch.setattr(flow.time, 'sleep', lambda *args: None)
    cfg = {'scenario_id': scenario, 'screen_context_mode': 'new_screen', 'entry_type': 'card', 'anchor': {'text_regex': 'Pet Care'}, 'context_verify': {'type': 'screen_text', 'text_regex': 'Pet Care'}, 'verify_tokens': ['profile'], 'negative_verify_tokens': ['wrong destination']}
    return client, cfg


def test_transition_recognizes_loaded_destination_using_same_post_open_contract(monkeypatch):
    client, cfg = _transition_fixture(monkeypatch)
    # The current implementation takes its baseline AFTER dispatching the tap.
    # A destination already loaded at baseline must not depend on another repaint.
    ok, reason = flow._confirm_click_focused_transition(client, None, cfg, transition_fast_path=True, baseline_window_focus='same-window')
    assert ok is True
    assert reason == 'destination_body_verify'


@pytest.mark.parametrize('variant', ['global_nav', 'without_up', 'wrong_destination', 'unmatched_body'])
def test_transition_body_verification_rejects_root_or_unverified_destination(monkeypatch, variant):
    client, cfg = _transition_fixture(monkeypatch, variant=variant)
    ok, _ = flow._confirm_click_focused_transition(client, None, cfg, transition_fast_path=True, baseline_window_focus='same-window')
    assert ok is False


@pytest.mark.parametrize('scenario', ['life_energy_plugin', 'life_air_care_plugin'])
def test_transition_body_verification_preserves_stricter_special_contracts(monkeypatch, scenario):
    client, cfg = _transition_fixture(monkeypatch, scenario=scenario)
    ok, _ = flow._confirm_click_focused_transition(client, None, cfg, transition_fast_path=True, baseline_window_focus='same-window')
    assert ok is False


@pytest.mark.parametrize('variant', ['legacy_resource_id', 'back_alias'])
def test_transition_body_supports_existing_schema_and_navigation_aliases(monkeypatch, variant):
    client, cfg = _transition_fixture(monkeypatch)
    if variant == 'legacy_resource_id':
        node = client.dump_tree.return_value[1]
        node['resourceId'] = node.pop('viewIdResourceName')
    else:
        client.dump_tree.return_value[0]['text'] = 'Back'
    ok, reason = flow._confirm_click_focused_transition(client, None, cfg, transition_fast_path=True, baseline_window_focus='same-window')
    assert ok and reason == 'destination_body_verify'


def test_transition_body_rejects_global_navigation_metadata_without_id(monkeypatch):
    client, cfg = _transition_fixture(monkeypatch)
    client.dump_tree.return_value.append({'isBottomNavigationBar': True, 'text': 'Life', 'isVisibleToUser': True})
    ok, _ = flow._confirm_click_focused_transition(client, None, cfg, transition_fast_path=True, baseline_window_focus='same-window')
    assert ok is False
