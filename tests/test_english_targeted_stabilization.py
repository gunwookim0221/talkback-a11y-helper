import copy
import json
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from tb_runner import anchor_logic, collection_flow
from tb_runner.runtime_config import load_runtime_bundle
from tb_runner.scenario_config import TAB_CONFIGS


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/english_targeted_stabilization/device_roots.json').read_text(encoding='utf-8'))
SEARCH_ID = 'com.samsung.android.oneconnect:id/search_icon'


def devices_config():
    bundle = load_runtime_bundle(copy.deepcopy(TAB_CONFIGS), config_path=ROOT / 'config/runtime_config.json')
    return next(c for c in bundle['tab_configs'] if c['scenario_id'] == 'devices_main')


def anchor_client(nodes):
    search = next(n for n in nodes if n.get('viewIdResourceName') == SEARCH_ID)
    label = search.get('contentDescription') or search.get('text')
    client = Mock()
    client.dump_tree.return_value = copy.deepcopy(nodes)
    client.select.return_value = True
    client.get_focus.return_value = copy.deepcopy(search)
    client.collect_focus_step.return_value = {
        'focus_view_id': SEARCH_ID, 'visible_label': label,
        'merged_announcement': label, 'focus_bounds': '48,286,168,436',
        'actual_focus_accessibility_focused': True,
    }
    return client


@pytest.mark.parametrize('locale', ['ko-KR', 'en-US'])
def test_devices_anchor_preserves_observed_focus_and_double_verification(locale, monkeypatch):
    monkeypatch.setattr(anchor_logic.time, 'sleep', lambda _: None)
    cfg = devices_config()
    legacy = copy.deepcopy(cfg)
    legacy.update(copy.deepcopy(FIXTURE['legacy_devices_anchor']))
    nodes = FIXTURE[locale]['nodes']
    old_client, new_client = anchor_client(nodes), anchor_client(nodes)
    old = anchor_logic.stabilize_anchor(old_client, 'SERIAL', legacy, phase='scenario_start', max_retries=1)
    new = anchor_logic.stabilize_anchor(new_client, 'SERIAL', cfg, phase='scenario_start', max_retries=1)

    assert old['ok'] is True and new['ok'] is True
    assert old['context']['ok'] is True and new['context']['ok'] is True
    assert old_client.select.call_args == new_client.select.call_args
    assert new_client.select.call_args.kwargs['type_'] == 'r'
    assert 'search_icon' in new_client.select.call_args.kwargs['name']
    assert old_client.collect_focus_step.call_count == new_client.collect_focus_step.call_count == 2
    assert cfg['max_steps'] == legacy['max_steps'] == 100
    assert cfg['stabilization_mode'] == legacy['stabilization_mode'] == 'anchor_then_context'


@pytest.mark.parametrize('locale', ['ko-KR', 'en-US'])
def test_devices_anchor_cannot_verify_home_even_with_same_search_resource(locale, monkeypatch):
    monkeypatch.setattr(anchor_logic.time, 'sleep', lambda _: None)
    nodes = copy.deepcopy(FIXTURE[locale]['nodes'])
    home = '홈' if locale == 'ko-KR' else 'Home'
    for node in nodes:
        if node.get('viewIdResourceName') != SEARCH_ID:
            node['selected'] = node.get('text') == f'{home} {home}'
    client = anchor_client(nodes)
    result = anchor_logic.stabilize_anchor(client, 'SERIAL', devices_config(), phase='scenario_start', max_retries=1)
    assert result['ok'] is False
    client.select.assert_not_called()


def test_devices_runtime_config_has_no_home_anchor_dependency():
    raw = json.loads((ROOT / 'config/runtime_config.json').read_text(encoding='utf-8'))
    cfg = devices_config()
    assert 'anchor_ref' not in raw['scenarios']['devices_main']
    assert cfg['anchor']['resource_id_regex'] == cfg['anchor_name']
    assert cfg['anchor']['allow_resource_id_only'] is True
    assert 'location' not in json.dumps(cfg['anchor']).lower()
    assert 'qr' not in json.dumps(cfg['anchor']).lower()
    assert 'home_tab_anchor' in raw['shared_anchors']


@pytest.mark.parametrize('cta', ['쇼핑리스트로 보내기', 'Send to Shopping list', 'SEND TO SHOPPING LIST'])
@pytest.mark.parametrize('channel', ['text', 'contentDescription', 'visible_body'])
def test_food_cta_verifies_both_locales_and_semantic_channels(cta, channel):
    cfg = next(c for c in TAB_CONFIGS if c['scenario_id'] == 'life_food_plugin')
    assert '쇼핑리스트로 보내기' in cfg['verify_tokens']
    if channel == 'visible_body':
        fields = ('back', 'Navigate up', 'Navigate up')
        extra = [cta]
    else:
        fields = collection_flow._extract_post_open_focus_fields({channel: cta})
        extra = []
    assert collection_flow._matches_post_open_verify(cfg, *fields, extra_candidates=extra)


@pytest.mark.parametrize('copy_text', ['Food', 'Cooking', 'Recipes for you', '꼬치어묵', '찹스테이크 마이셰프'])
def test_food_does_not_verify_unconfirmed_card_or_recipe_copy(copy_text):
    cfg = next(c for c in TAB_CONFIGS if c['scenario_id'] == 'life_food_plugin')
    assert not collection_flow._matches_post_open_verify(
        cfg, 'back', 'Navigate up', 'Navigate up', extra_candidates=[copy_text],
    )


@pytest.mark.parametrize('label', ['Location QR code', 'More options', 'Add'])
def test_shared_false_success_guard_remains_strict(label):
    assert collection_flow._is_negative_post_open_focus_signal('', label, label)


def run_find_map(monkeypatch, description, *, rid='com.samsung.android.oneconnect:id/map_area', actionable=True, scenario='life_find_plugin'):
    cfg = next(c for c in TAB_CONFIGS if c['scenario_id'] == scenario)
    target = {
        'text': '', 'contentDescription': description, 'viewIdResourceName': rid,
        'className': 'android.widget.FrameLayout', 'boundsInScreen': '30,1100,1050,1454',
        'clickable': actionable, 'effectiveClickable': actionable, 'focusable': True,
        'visibleToUser': True, 'children': [],
    }
    root = {'className': 'android.widget.GridView', 'viewIdResourceName': 'com.samsung.android.oneconnect:id/recycler_view',
            'boundsInScreen': '0,0,1080,2640', 'focusable': True, 'children': [target]}
    taps = []
    client = SimpleNamespace(tap_xy_adb=lambda **kw: taps.append((kw['x'], kw['y'])) or True)
    monkeypatch.setattr(collection_flow, '_load_scrolltouch_xml_nodes', lambda **kw: ([root], 'ok'))
    monkeypatch.setattr(collection_flow, '_confirm_click_focused_transition', lambda **kw: (True, 'plugin_open_verified'))
    monkeypatch.setattr(collection_flow.time, 'sleep', lambda *_: None)
    result = collection_flow._run_xml_scroll_search_tap(
        client, 'SERIAL', tab_cfg=cfg, target=cfg['pre_navigation'][0]['target'],
        type_='a', max_scroll_search_steps=0, step_wait_seconds=.2, transition_fast_path=False,
    )
    return result, taps


@pytest.mark.parametrize('description', [
    'Find, kor003의 Z Fold8, Last updated: 50 minutes ago',
    '파인드, kor003의 Z Fold8, 최근 위치 확인: 3시간 전',
])
def test_find_map_description_preserves_bilingual_actionable_target(monkeypatch, description):
    result, taps = run_find_map(monkeypatch, description)
    assert result == (True, 'xml_entry_success')
    assert taps == [(540, 1277)]


@pytest.mark.parametrize('description', ['Find, Loading…', '파인드, 로딩 중'])
def test_find_loading_card_owns_action_and_requires_verified_transition(monkeypatch, description):
    result, taps = run_find_map(monkeypatch, description, rid='com.samsung.android.oneconnect:id/fme_view')
    assert result == (True, 'xml_entry_success')
    assert taps == [(540, 1277)]
    monkeypatch.setattr(collection_flow, '_confirm_click_focused_transition', lambda **kw: (False, 'same_screen'))
    cfg = next(c for c in TAB_CONFIGS if c['scenario_id'] == 'life_find_plugin')
    client = SimpleNamespace(tap_xy_adb=lambda **kw: True)
    rejected = collection_flow._run_xml_scroll_search_tap(
        client, 'SERIAL', tab_cfg=cfg, target=cfg['pre_navigation'][0]['target'],
        type_='a', max_scroll_search_steps=0, step_wait_seconds=.2, transition_fast_path=False,
    )
    assert rejected[0] is False


@pytest.mark.parametrize('description,rid,actionable,scenario', [
    ('Find, my device', 'com.samsung.android.oneconnect:id/other_card', True, 'life_find_plugin'),
    ('Find, my device', 'com.samsung.android.oneconnect:id/map_area', False, 'life_find_plugin'),
    ('Find out more about air control', 'com.samsung.android.oneconnect:id/map_area', True, 'life_find_plugin'),
    ('Use Find to locate devices', 'com.samsung.android.oneconnect:id/map_area', True, 'life_find_plugin'),
    ('Find, my device, Family Care', 'com.samsung.android.oneconnect:id/map_area', True, 'life_find_plugin'),
    ('Find, my device', 'com.samsung.android.oneconnect:id/map_area', True, 'life_pet_care_plugin'),
])
def test_find_weak_copy_or_wrong_resource_cannot_qualify(monkeypatch, description, rid, actionable, scenario):
    result, taps = run_find_map(monkeypatch, description, rid=rid, actionable=actionable, scenario=scenario)
    assert result[0] is False
    assert taps == []
