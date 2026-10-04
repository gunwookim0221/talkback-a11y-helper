"""Fix 2: strict primary visits and scenario execution/comparison precedence."""
from collections import deque
from types import SimpleNamespace
import pytest
from tb_runner import collection_flow as flow
from tb_runner.completeness import reconcile as completeness
from tb_runner.focus_reconciliation import reconcile_focus, apply_reconciliation_to_row
from tb_runner.traversal_reliability import TraversalMetrics, focus_instance
from qa_frontend.backend.runtime_dashboard import parse_runtime_log, scenario_contract_status
from qa_frontend.backend.run_summary import build_run_summary

RID = 'com.samsung.android.plugin.camera:id/toolbar_more_menu'
BOUNDS = '912,142,1032,262'

def camera(a11y=False, **extra):
    return dict(scenario_id='device_camera_plugin', step_index=1, row_source='representative',
                focus_view_id=RID, focus_bounds=BOUNDS, visible_label='More options',
                actual_focus_resource_id=RID, actual_focus_bounds=BOUNDS,
                actual_focus_visible='More options', actual_focus_accessibility_focused=a11y,
                actual_focus_input_focused=True, move_result='moved', **extra)

def state():
    return SimpleNamespace(recent_representative_signatures=deque(),
                           consumed_representative_signatures=set(), reliability_metrics=TraversalMetrics())

def test_exact_camera_input_only_then_actual_focus_credits_only_later():
    st = state()
    r = camera()
    candidate = dict(scenario_id=r['scenario_id'], rid=RID, bounds=BOUNDS, label='More options')
    result = reconcile_focus(row=r, previous_row=None, scenario_id=r['scenario_id'],
        inventory=[candidate], expected_candidates=[candidate], physical_visit_confirmed=True,
        planning_consumed=True)
    assert result['mapping_confidence'] == 'EXACT'
    assert result['physical_visit_confirmed'] is False
    apply_reconciliation_to_row(r, result)
    flow._record_recent_representative_signature(st, r)
    assert r['physical_visited'] is False
    assert len(st.reliability_metrics.visited) == 0
    assert completeness(r['scenario_id'], [], [r])['summary']['completeness_actual_visited'] == 0
    later = camera(True)
    flow._record_recent_representative_signature(st, later)
    assert later['physical_visited'] is True
    assert len(st.reliability_metrics.visited) == 1
    assert completeness(r['scenario_id'], [], [r, later])['summary']['completeness_actual_visited'] == 1

@pytest.mark.parametrize('r', [camera(), camera(False, selected=True),
    dict(scenario_id='device_camera_plugin', focus_view_id=RID, focus_bounds=BOUNDS, visible_label='More'),
    camera(True, focus_transition_status='AMBIGUOUS'),
    camera(True, focus_reconciliation_confidence='AMBIGUOUS'), camera(True, physical_visited=False),
    dict(camera(), actual_focus_input_focused=False),
    dict(camera(True), actual_focus_node={'accessibilityFocused': False})])
def test_non_strict_or_unreconciled_focus_never_credits(r):
    m = TraversalMetrics();m.observe_focus(r)
    assert focus_instance(r) is None
    assert m.visited == set()

@pytest.mark.parametrize('execution,comparison,expected', [
 ('COMPLETED','PASS','passed'), ('COMPLETED','FAIL','failed'),
 ('INCOMPLETE_ERROR','N/A','failed'), ('INCOMPLETE_NO_PROGRESS','PASS','warning'),
 ('INCOMPLETE_SAFETY_LIMIT','PASS','warning'), ('INCOMPLETE_SCROLL_UNVERIFIED','PASS','warning'),
 ('COMPLETED','WARN','warning'), ('NOT_AVAILABLE','N/A','not_available')])
def test_summary_matrix(execution, comparison, expected):
    assert scenario_contract_status('home_main', {'termination_status': execution}, comparison) == expected

@pytest.mark.parametrize('sid', ['home_main', 'settings_entry_example'])
def test_exact_error_false_pass_persisted_and_live(tmp_path, sid):
    log = tmp_path/'fixture.log'
    log.write_text(f"[PERF][scenario_contract_summary] scenario={sid} total_steps=1 termination_status=INCOMPLETE_ERROR termination_reason=tab_or_anchor_failed\n[PERF][scenario_summary] scenario={sid} total_steps=1", encoding='utf-8')
    summary = build_run_summary(status={'state':'finished'}, log_path=log, scenario_ids=[sid])
    assert summary['scenarios'][0]['status'] == 'failed'
    assert summary['scenarios'][0]['execution_status'] == 'INCOMPLETE_ERROR'
    assert summary['scenario_result_status'] == 'failed'
    assert summary['failed_scenarios'] == 1
    assert parse_runtime_log(log.read_text(), scenario_ids=[sid])['failed_scenarios'] == 1

def test_global_nav_primary_5_of_5_overrides_internal_fail_and_has_zero_content_steps():
    log = "[TAB][select] stabilization failed scenario=global_nav_main\n[PERF][scenario_contract_summary] scenario=global_nav_main total_steps=0 termination_status=COMPLETED nav_items_expected=5 nav_items_verified=5"
    parsed = parse_runtime_log(log, scenario_ids=['global_nav_main'], validation_failed_scenarios={'global_nav_main'})
    assert parsed['scenario_progress'][0]['status'] == 'passed'
    assert parsed['passed_scenarios'] == parsed['executed_scenarios'] == 1
    assert parsed['failed_scenarios'] == 0

@pytest.mark.parametrize('ack', ['moved','failed'])
def test_failed_ack_actual_transition_still_visits_and_unchanged_does_not(ack):
    st = state(); previous = dict(camera(True), actual_focus_bounds='0,0,100,100')
    r = dict(camera(True), move_result=ack)
    result = reconcile_focus(row=r, previous_row=previous, scenario_id=r['scenario_id'], inventory=[],
        expected_candidates=[], physical_visit_confirmed=False, planning_consumed=True)
    apply_reconciliation_to_row(r, result)
    flow._record_recent_representative_signature(st, r)
    assert len(st.reliability_metrics.visited) == 1
    same = dict(r)
    result = reconcile_focus(row=same, previous_row=r, scenario_id=r['scenario_id'], inventory=[],
        expected_candidates=[], physical_visit_confirmed=True, planning_consumed=True)
    apply_reconciliation_to_row(same, result)
    flow._record_recent_representative_signature(st, same)
    assert same['physical_visited'] is False
    assert len(st.reliability_metrics.visited) == 1

def test_primary_matrix_counts_are_conserved_in_batch_live_summary():
    from qa_frontend.backend.batch_runner import _parse_live_log
    specs = [('home_main','INCOMPLETE_ERROR'), ('devices_main','INCOMPLETE_SAFETY_LIMIT'),
             ('menu_main','COMPLETED')]
    log = '\n'.join(f'[PERF][scenario_contract_summary] scenario={sid} total_steps=1 termination_status={status}' for sid,status in specs)
    live = _parse_live_log(log, scenario_ids=[sid for sid,_ in specs])
    assert live['progress']['failed_scenarios'] == 1
    assert live['progress']['warning_scenarios'] == 1
    assert live['progress']['passed_scenarios'] == 1
    assert live['progress']['executed_scenarios'] == live['progress']['completed_scenarios'] == 3


def test_absolute_saved_excel_path_and_only_result_sheet_comparison(tmp_path, monkeypatch):
    import openpyxl
    from qa_frontend.backend import runtime_dashboard as dashboard
    monkeypatch.setattr(dashboard, 'OUTPUT_DIR', tmp_path)
    folder = tmp_path/'nested folder';folder.mkdir()
    wb = openpyxl.Workbook();raw = wb.active;raw.title='raw'
    raw.append(['scenario_id','final_result','failure_reason','mismatch_type'])
    raw.append(['menu_main','FAIL','raw_placeholder','EMPTY_VISIBLE'])
    result = wb.create_sheet('result');result.append(['scenario_id','final_result','failure_reason','mismatch_type'])
    result.append(['devices_main','FAIL','label','LABEL_MISMATCH'])
    wb.save(folder/'test.xlsx');wb.close()
    log = ('[PERF][scenario_contract_summary] scenario=menu_main termination_status=COMPLETED\n'
           '[PERF][scenario_contract_summary] scenario=devices_main termination_status=COMPLETED\n'
           r'[SAVE] saved excel: D:\Python test\talkback-a11y-helper\output/nested folder/test.xlsx rows=2')
    parsed = parse_runtime_log(log, scenario_ids=['menu_main','devices_main'])
    states = {s['id']:s for s in parsed['scenario_progress']}
    assert states['menu_main']['status'] == 'passed'
    assert states['devices_main']['status'] == 'failed'
    assert states['devices_main']['comparison_status'] == 'FAIL'

def test_actual_node_focus_proof_is_shared_by_primary_and_completeness():
    r = camera()
    r['actual_focus_accessibility_focused'] = None
    r['actual_focus_node'] = {'accessibilityFocused': True}
    r['focus_node'] = {'accessibilityFocused': False, 'focused': False}
    m = TraversalMetrics();m.observe_focus(r)
    assert len(m.visited) == 1
    assert list(m.focus_observations.values())[0]['actual_focus_accessibility_focused'] is True
    assert completeness(r['scenario_id'], [], [r], focus_observations=list(m.focus_observations.values()))['summary']['completeness_actual_visited'] == 1

def test_primary_error_overriding_availability_terminal_is_counted_once():
    log = "\n".join([
        "[SCENARIO][pre_nav] step=1 action=enter_device_card_plugin target='TV'",
        "[DEVICE_ENTRY][inventory] labels='Galaxy Home Mini N7LM Melon'",
        "[DEVICE_ENTRY][expand] running reason='target_not_visible'",
        "[DEVICE][scroll] inventory_signature_changed=false",
        "[SCENARIO][pre_nav] failed reason='action_failed' step=1",
        "[PERF][scenario_summary] scenario=device_tv_plugin total_steps=1 save_excel_count=0",
        "[PERF][scenario_contract_summary] scenario=device_tv_plugin termination_status=INCOMPLETE_ERROR"])
    parsed = parse_runtime_log(log, scenario_ids=['device_tv_plugin'])
    assert parsed['scenario_progress'][0]['status'] == 'failed'
    assert parsed['executed_scenarios'] == parsed['terminal_scenarios'] == 1
    assert parsed['availability_terminal_scenarios'] == parsed['not_available_scenarios'] == 0


def test_primary_not_available_is_a_terminal_execution():
    parsed = parse_runtime_log('[PERF][scenario_contract_summary] scenario=device_tv_plugin termination_status=NOT_AVAILABLE',scenario_ids=['device_tv_plugin'])
    assert parsed['not_available_scenarios'] == parsed['availability_terminal_scenarios'] == 1
    assert parsed['executed_scenarios'] == parsed['terminal_scenarios'] == 1
