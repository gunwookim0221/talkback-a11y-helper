from talkback_lib import A11yAdbClient
import pytest


def focus_log(event_time=123, package='com.example.app'):
    return (f'10-04 19:00:00.000 V/talkback( 42): Mappers: mapToFeedback() '
            f'event=EventType: TYPE_VIEW_ACCESSIBILITY_FOCUSED; EventTime: {event_time}; '
            f'PackageName: {package}; [ ClassName: android.widget.SeekBar; Text: [] ]')


def speech_log(text='10, 슬라이더', event_time=123, subtype='TYPE_VIEW_ACCESSIBILITY_FOCUSED'):
    return (f'10-04 19:00:00.100 V/talkback( 42): SpeechControllerImpl: '
            f'Speaking fragment text="{text}", utteranceId=talkback_14, TtsSpan=null, '
            f'locale=null, event=type:EVENT_TYPE_ACCESSIBILITY subtype:{subtype} '
            f'displayId:0 time:{event_time}')


def capture(monkeypatch, logs):
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client, 'check_talkback_status', lambda dev=None: True)
    monkeypatch.setattr(client, '_run', lambda args, dev=None: logs)
    return client, client.get_partial_announcements(wait_seconds=0)


@pytest.mark.parametrize('text', ['10, 슬라이더', '25, 슬라이더', '사용할 수 없음, 페이저 내부', 'a "quoted", control'])
def test_native_focus_speech_preserved_when_node_announcement_empty(monkeypatch, text):
    _, result = capture(monkeypatch, focus_log() + '\n' + speech_log(text))
    assert result == [text]


@pytest.mark.parametrize('logs', [
    focus_log() + '\n' + speech_log(''),
    speech_log(),  # No focus event context.
    focus_log() + '\n' + speech_log(subtype='EVENT_SPEAK_HINT'),
    focus_log(124) + '\n' + speech_log(event_time=123),
    (focus_log() + '\n' + speech_log()).replace('V/talkback', 'I/A11Y_HELPER'),
    focus_log(package='com.android.systemui') + '\n' + speech_log(),
    focus_log(package='com.samsung.android.accessibility.talkback') + '\n' + speech_log(),
    focus_log() + '\n' + '10-04 19:00:00.100 V/talkback( 42): speech prediction: 10, 슬라이더',
    focus_log() + '\n' + speech_log().replace('( 42)', '( 43)'),
])
def test_unobserved_or_unrelated_native_speech_remains_empty(monkeypatch, logs):
    _, result = capture(monkeypatch, logs)
    assert result == []


def test_existing_helper_announcement_has_precedence(monkeypatch):
    _, result = capture(monkeypatch, focus_log() + '\n' + speech_log() +
                        '\n10-04 19:00:00.110 I/A11Y_HELPER: A11Y_ANNOUNCEMENT: 기존 발화')
    assert result == ['기존 발화']


def test_native_speech_is_not_reused_by_next_poll(monkeypatch):
    client, result = capture(monkeypatch, focus_log() + '\n' + speech_log())
    assert result == ['10, 슬라이더']
    assert client.get_partial_announcements(wait_seconds=0) == []


def test_native_duplicate_fragment_deduplicated(monkeypatch):
    _, result = capture(monkeypatch, focus_log() + '\n' + speech_log() + '\n' + speech_log())
    assert result == ['10, 슬라이더']


def test_new_focus_during_poll_does_not_keep_old_native_utterance(monkeypatch):
    import talkback_lib
    clock = [0.0]
    monkeypatch.setattr(talkback_lib.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(talkback_lib.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    client = A11yAdbClient(start_monitor=False)
    monkeypatch.setattr(client, 'check_talkback_status', lambda dev=None: True)
    old = focus_log() + '\n' + speech_log()
    logs = iter([old, old + '\n' + focus_log(124)])
    from talkback_lib.constants import NATIVE_SPEECH_LOGCAT_ARGS
    monkeypatch.setattr(client, '_run', lambda args, dev=None: next(logs) if args == NATIVE_SPEECH_LOGCAT_ARGS else '')
    assert client.get_partial_announcements(wait_seconds=0.1) == []


def test_samsung_component_tags_with_colon_are_supported(monkeypatch):
    logs = (focus_log().replace('V/talkback( 42): Mappers:', 'V/talkback: Mappers( 42):') + '\n' +
            speech_log().replace('V/talkback( 42): SpeechControllerImpl:', 'V/talkback: SpeechControllerImpl( 42):'))
    client, result = capture(monkeypatch, logs)
    assert result == ['10, 슬라이더']
    assert client.last_native_speech_evidence[0]['source'] == 'native_talkback_speaking_fragment'
