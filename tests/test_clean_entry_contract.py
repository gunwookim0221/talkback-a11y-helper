from copy import deepcopy
from unittest.mock import Mock

import pytest

from tb_runner import anchor_logic, context_verifier, tab_logic
from tb_runner.scenario_config import TAB_CONFIGS


def config(sid='home_main'):
    return deepcopy(next(c for c in TAB_CONFIGS if c['scenario_id'] == sid))


def tree(selected='home', content=True):
    labels = ['Home', 'Devices', 'Life', 'Routines', 'Menu']
    ids = ['favorites', 'devices', 'services', 'automations', 'more']
    nodes = [dict(text=label, contentDescription=label,
                  viewIdResourceName='com.samsung.android.oneconnect:id/menu_' + rid,
                  boundsInScreen=f'[{i * 180},900][{i * 180 + 150},1000]',
                  className='android.widget.LinearLayout', visibleToUser=True,
                  focusable=True, clickable=True, selected=label.lower() == selected)
             for i, (label, rid) in enumerate(zip(labels, ids))]
    if content:
        nodes.append(dict(text='Body card', viewIdResourceName='app:id/card',
                          boundsInScreen='[40,300][300,500]', className='android.widget.Button',
                          visibleToUser=True, focusable=True, clickable=True))
    return nodes


@pytest.fixture(autouse=True)
def no_device_or_sleep(monkeypatch):
    monkeypatch.setattr(anchor_logic.time, 'sleep', lambda _: None)
    monkeypatch.setattr(context_verifier, '_read_window_xml_selected_bottom_tab', lambda *a: '')
    monkeypatch.setattr(tab_logic, '_read_window_xml_nodes', lambda *a: [])


def readiness(snapshots, **kwargs):
    client = Mock(spec=['dump_tree'])
    client.dump_tree.side_effect = snapshots
    return anchor_logic.wait_for_root_entry_ready(client, None, config(), **kwargs), client


def test_clean_delayed_nav_retries_before_anchor():
    result, client = readiness([[], tree()])
    assert result['ok'] and len(result['observations']) == 2
    assert result['observations'][0]['nav_candidates'] == 0
    assert client.dump_tree.call_count == 2


def test_clean_delayed_content_retries():
    result, _ = readiness([tree(content=False), tree()])
    assert result['ok'] and len(result['observations']) == 2
    assert not result['observations'][0]['content_anchor_ready']


def test_helper_ready_before_content_does_not_abort_anchor(monkeypatch):
    client = Mock(spec=['dump_tree', 'select', 'collect_focus_step'])
    client.dump_tree.side_effect = [tree(content=False), tree()]
    result = anchor_logic.wait_for_root_entry_ready(client, None, config())
    assert result['ok']
    client.select.assert_not_called()
    assert len(result['observations']) == 2


def test_readiness_timeout_keeps_truthful_entry_failure(monkeypatch):
    client = Mock(spec=['dump_tree', 'select'])
    client.dump_tree.return_value = tree(content=False)
    result = anchor_logic.stabilize_anchor(client, None, config(), 'scenario_start')
    assert result['ok'] is False
    assert result['reason'] == 'root_entry_readiness_timeout'
    assert len(result['readiness']['observations']) == 3
    client.select.assert_not_called()


def tab_client(nodes):
    client = Mock(spec=['dump_tree', 'touch_point', 'select', 'touch', 'touch_bounds_center', 'collect_focus_step'])
    client.dump_tree.return_value = nodes
    client.collect_focus_step.return_value = {'dump_tree_nodes': nodes}
    client.touch_point.return_value = True
    return client


def test_current_selected_tab_does_not_destructively_navigate():
    client = tab_client(tree())
    result = tab_logic.stabilize_tab_selection(client, None, config())
    assert result['ok']
    assert result['focus_align']['attempted'] is False
    client.touch_point.assert_not_called()
    client.touch.assert_not_called()
    client.select.assert_not_called()


def test_selected_state_late_update_is_bounded():
    result, _ = readiness([tree(selected='menu'), tree()])
    assert result['ok'] and len(result['observations']) == 2
    assert not result['observations'][0]['selected_confirmed']


def test_selected_tab_without_content_does_not_immediately_select_anchor():
    result, _ = readiness([tree(content=False), tree(content=False), tree()])
    assert result['ok'] and len(result['observations']) == 3


@pytest.mark.parametrize('previous', ['menu', 'devices', 'routines', 'life'])
def test_previous_active_tab_transitions_then_verifies(previous):
    client = tab_client(tree(selected=previous))
    client.collect_focus_step.return_value = {'dump_tree_nodes': tree()}
    result = tab_logic.stabilize_tab_selection(client, None, config())
    assert result['ok'] and result['context']['ok']
    client.touch_point.assert_called_once_with(dev=None, x=75, y=950)


def focus_row(a11y, input_focus=False):
    return dict(visible_label='Body card', merged_announcement='Body card',
                focus_view_id='app:id/card', focus_bounds='[40,300][300,500]',
                actual_focus_accessibility_focused=a11y, actual_focus_input_focused=input_focus,
                focus_node={'accessibilityFocused': a11y, 'focused': input_focus})


def test_no_accessibility_focus_first_retries_setup_bounded():
    client = Mock(spec=['dump_tree', 'select', 'collect_focus_step'])
    client.dump_tree.return_value = tree()
    client.select.return_value = True
    client.collect_focus_step.side_effect = [focus_row(False), focus_row(False), focus_row(True), focus_row(True)]
    result = anchor_logic.stabilize_anchor(client, None, config(), 'scenario_start')
    assert result['ok'] and result['attempt'] == 2
    assert client.collect_focus_step.call_count == 4


def test_input_focus_only_never_counts_as_root_setup_success():
    client = Mock(spec=['dump_tree', 'select', 'collect_focus_step'])
    client.dump_tree.return_value = tree()
    client.select.return_value = True
    client.collect_focus_step.return_value = focus_row(False, input_focus=True)
    result = anchor_logic.stabilize_anchor(client, None, config(), 'scenario_start')
    assert result['ok'] is False
    assert client.collect_focus_step.call_count == 4


def test_global_nav_ends_menu_then_home_default_device_entry():
    client = tab_client(tree(selected='menu'))
    client.collect_focus_step.return_value = {'dump_tree_nodes': tree()}
    result = tab_logic.stabilize_tab_selection(client, None, config())
    assert result['ok']
    client.dump_tree.return_value = tree()
    ready = anchor_logic.wait_for_root_entry_ready(client, None, config())
    assert ready['ok']
    assert ready['observations'][0]['selected_confirmed']


def test_default_device_empty_step_cache_refreshes_full_tree():
    client = Mock(spec=['dump_tree'])
    client.dump_tree.return_value = tree()
    result = context_verifier.verify_context({'dump_tree_nodes': []}, config(), client=client, dev=None)
    assert result['ok'] and result['dump_source'] == 'lazy_dump'
    client.dump_tree.assert_called_once_with(dev=None)


def test_partial_nonempty_focus_cache_refreshes_full_tree():
    client = Mock(spec=['dump_tree'])
    client.dump_tree.return_value = tree()
    result = context_verifier.verify_context({'dump_tree_nodes': [{'text': 'Whole screen fallback'}]}, config(), client=client, dev=None)
    assert result['ok'] and result['dump_source'] == 'refreshed_incomplete_step_cache'


def test_xml_selected_state_works_without_explicit_serial(monkeypatch):
    monkeypatch.undo()
    xml = '<hierarchy><node selected="true" content-desc="Home" /></hierarchy>'
    client = Mock(spec=['_run'])
    client._run.side_effect = ['', xml, '']
    assert context_verifier._read_window_xml_selected_bottom_tab(client, None, 'home') == 'Home'
    assert all(call.kwargs['dev'] is None for call in client._run.call_args_list)


def test_tab_xml_fallback_works_without_explicit_serial(monkeypatch):
    monkeypatch.undo()
    xml = '<hierarchy><node selected="true" content-desc="Home" bounds="[0,900][150,1000]" /></hierarchy>'
    client = Mock(spec=['_run'])
    client._run.side_effect = ['', xml, '']
    nodes = tab_logic._read_window_xml_nodes(client, None)
    assert nodes[0]['selected'] is True
    assert all(call.kwargs['dev'] is None for call in client._run.call_args_list)
