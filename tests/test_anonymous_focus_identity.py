"""Strict anonymous focus is observed identity, never synthetic visit credit."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from talkback_lib import A11yAdbClient
from talkback_lib.focus_service import FocusService
from tb_runner.phase4b_execution import focus_row
from tb_runner.focus_reconciliation import reconcile_focus
from tb_runner.traversal_reliability import TraversalMetrics, focus_instance, instance_id, observed_focus_instance

def anonymous(bounds='0,0,100,100', **extra):
    return dict(viewIdResourceName=None,text='',contentDescription=None,talkbackLabel='',mergedLabel='',
        className='android.widget.TextView',boundsInScreen=bounds,accessibilityFocused=True,focused=False,**extra)

def test_anonymous_strict_geometry_class_preserves_existing_instance_key():
    node=anonymous()
    row=focus_row(node,'generic')
    item=focus_instance(row)
    assert item and item['label']=='' and item['class_name']==node['className']
    assert instance_id(item)==instance_id(dict(scenario_id='generic',view_id='',bounds=node['boundsInScreen']))
    assert row==focus_row(node,'generic')

@pytest.mark.parametrize('failure',['input_only','unknown_focus','contradiction','missing_class','invalid_bounds',
    'zero_bounds','changed_class','changed_bounds','physical_false','ambiguous','planned_only'])
def test_anonymous_unproven_focus_never_builds_a_visit_identity(failure):
    row=focus_row(anonymous(),'generic')
    if failure=='input_only': row['actual_focus_node'].update(accessibilityFocused=False,focused=True);row['actual_focus_accessibility_focused']=False
    elif failure=='unknown_focus': row['actual_focus_node'].pop('accessibilityFocused');row.pop('actual_focus_accessibility_focused')
    elif failure=='contradiction': row['actual_focus_node']['accessibilityFocused']=False
    elif failure=='missing_class': row['actual_focus_node']['className']='';row['actual_focus_class_name']=''
    elif failure=='invalid_bounds': row['actual_focus_bounds']='bad'
    elif failure=='zero_bounds': row['actual_focus_bounds']='0,0,0,100';row['actual_focus_node']['boundsInScreen']='0,0,0,100'
    elif failure=='changed_class': row['actual_focus_class_name']='android.view.View'
    elif failure=='changed_bounds': row['actual_focus_bounds']='0,100,100,200'
    elif failure=='physical_false': row['physical_visited']=False
    elif failure=='ambiguous': row['focus_reconciliation_confidence']='AMBIGUOUS'
    else: row=dict(row_source='representative',focus_bounds='0,0,100,100',focus_class_name='android.view.View',focus_node={'focused':True})
    assert focus_instance(row) is None
    assert observed_focus_instance(row) is None

def reconcile(node,before,**kwargs):
    return reconcile_focus(row=focus_row(node,'generic'),previous_row=focus_row(before,'generic'),scenario_id='generic',
        inventory=[],expected_candidates=[],physical_visit_confirmed=False,planning_consumed=False,**kwargs)

def test_anonymous_movement_uses_actual_focus_without_ack_or_planner_credit():
    result=reconcile(anonymous('0,100,100,200'),anonymous())
    assert result['focus_transition_status']=='CONFIRMED_MOVED'
    assert result['actual_focus_instance_id'] and result['visit_record_status']=='RECORDED'
    assert not result['planning_consumed']

def test_anonymous_same_focus_has_no_new_visit_despite_successful_ack():
    result=reconcile(anonymous(),anonymous())
    assert result['focus_transition_status']=='CONFIRMED_UNCHANGED'
    assert result['visit_record_status']=='NOT_RECORDED_UNCHANGED'
    assert result['reconciled_visit_instance_id']==''

def test_same_anonymous_geometry_different_class_is_ambiguous_not_new_visit():
    node=anonymous();node['className']='android.webkit.WebView'
    result=reconcile(node,anonymous())
    assert result['focus_transition_status']=='AMBIGUOUS'
    assert result['reconciled_visit_instance_id']==''

def test_labels_appearing_and_path_shift_do_not_reset_anonymous_history():
    first=anonymous();second=deepcopy(first)
    second.update(text='Live reading',stableNodePath='9.3',focused=True)
    assert instance_id(focus_instance(focus_row(first,'generic')))==instance_id(focus_instance(focus_row(second,'generic')))

def test_anonymous_persisted_proof_retains_class_and_round_trips():
    metrics=TraversalMetrics();row=focus_row(anonymous(),'generic')
    metrics.observe_focus(row)
    proof=next(iter(metrics.focus_observations.values()))
    assert proof['actual_focus_class_name']=='android.widget.TextView'
    assert instance_id(focus_instance(proof))==instance_id(focus_instance(row))

@pytest.mark.parametrize('kind',['strict','input_only','missing_class','zero_bounds','partial'])
def test_normal_focus_reader_keeps_complete_strict_anonymous_payload_only(monkeypatch,kind):
    client=A11yAdbClient(start_monitor=False)
    node=anonymous({'l':0,'t':0,'r':100,'b':100},packageName='com.samsung.android.oneconnect')
    if kind=='input_only': node.update(accessibilityFocused=False,focused=True)
    elif kind=='missing_class': node['className']=''
    elif kind=='zero_bounds': node['boundsInScreen']['r']=0
    result={**node,'success':False}
    if kind=='partial': result.update(partial_parse_success=True,partial_payload_trusted=False,partial_fields_from_root_only=True)
    monkeypatch.setattr(client,'_has_recent_helper_ok',lambda **kw:True)
    monkeypatch.setattr(client,'_resolve_serial',lambda dev:'fixture')
    monkeypatch.setattr(client._helper_bridge,'_request_get_focus',lambda **kw:result)
    fallback=dict(text='Other input focus',viewIdResourceName='other',focused=True,accessibilityFocused=False)
    dumps=[]
    monkeypatch.setattr(client,'dump_tree',lambda **kw:dumps.append(True) or [fallback])
    monkeypatch.setattr(client,'_run_get_focus_fallback_dump',lambda **kw:dumps.append(True) or fallback)
    got=FocusService(client).get_focus(mode='normal')
    if kind=='strict':
        assert got['accessibilityFocused'] is True and got['className']==node['className'] and not dumps
    else:
        assert dumps and got==fallback
