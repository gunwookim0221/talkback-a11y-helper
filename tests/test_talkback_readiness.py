import pytest
from unittest.mock import MagicMock
from talkback_lib import A11yAdbClient

def test_is_talkback_enabled_helper_only():
    client = A11yAdbClient("test_dev")
    client._run = MagicMock(side_effect=lambda args, **kwargs: 
        "1" if "accessibility_enabled" in args else 
        "com.iotpart.sqe.talkbackhelper/com.iotpart.sqe.talkbackhelper.A11yHelperService"
    )
    assert not client.is_talkback_enabled()

def test_is_talkback_enabled_google_talkback():
    client = A11yAdbClient("test_dev")
    client._run = MagicMock(side_effect=lambda args, **kwargs: 
        "1" if "accessibility_enabled" in args else 
        "com.google.android.marvin.talkback/com.google.android.marvin.talkback.TalkBackService"
    )
    assert client.is_talkback_enabled()

def test_is_talkback_enabled_samsung_talkback():
    client = A11yAdbClient("test_dev")
    client._run = MagicMock(side_effect=lambda args, **kwargs: 
        "1" if "accessibility_enabled" in args else 
        "com.samsung.android.accessibility.talkback/com.samsung.android.marvin.talkback.TalkBackService"
    )
    assert client.is_talkback_enabled()

def test_is_talkback_enabled_helper_and_talkback():
    client = A11yAdbClient("test_dev")
    client._run = MagicMock(side_effect=lambda args, **kwargs: 
        "1" if "accessibility_enabled" in args else 
        "com.samsung.android.accessibility.talkback/com.samsung.android.marvin.talkback.TalkBackService:com.iotpart.sqe.talkbackhelper/com.iotpart.sqe.talkbackhelper.A11yHelperService"
    )
    assert client.is_talkback_enabled()

def test_check_talkback_ready_disabled_when_helper_only():
    client = A11yAdbClient("test_dev")
    client.is_talkback_enabled = MagicMock(return_value=False)
    client.check_helper_status = MagicMock(return_value=True)
    
    result = client.check_talkback_ready()
    assert result == {"status": "disabled", "reason": "talkback_off"}
    client.is_talkback_enabled.assert_called_once()
    client.check_helper_status.assert_not_called()
