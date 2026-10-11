from types import SimpleNamespace

import pytest

from tools import phase4a_shadow_monitor as monitor


@pytest.mark.parametrize("selected", [None, {}])
def test_missing_selected_tab_fails_precondition_without_crashing(monkeypatch, tmp_path, selected):
    baseline=dict(talkback_pid="1", helper_pid="2", locale="en-US")
    raw=dict(nodes=[],selected_tab=selected,package_name="com.android.systemui",
             activity_name="Keyguard",overlay=dict(observed=False))
    monkeypatch.setattr(monitor,"OUT",tmp_path)
    monkeypatch.setattr(monitor,"device_state",lambda:dict(baseline))
    monkeypatch.setattr(monitor,"clean_start_smartthings",lambda **kw:(False,[],{}))
    monkeypatch.setattr(monitor,"A11yAdbClient",lambda **kw:object())
    monkeypatch.setattr(monitor,"capture_observation",lambda *a,**kw:raw)
    result=monitor.validate_precondition("device_tv_plugin",SimpleNamespace(),baseline)
    assert result["start_state_valid"] is False
    assert result["smartthings_foreground"] is False
    assert result["selected_tab_verified"] is False
    assert (tmp_path/'preconditions/device_tv_plugin.json').exists()
