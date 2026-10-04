"""Read observed TalkBack focus utterances, never predict speech from node text."""

import re


_TAG = re.compile(r'(?:[VDIWEF]/talkback(?:: (?:Mappers|SpeechControllerImpl))?\s*\(\s*(\d+)\)\s*:|\s(\d+)\s+\d+\s+[VDIWEF]\s+talkback\s*:)', re.I)
_FOCUS = re.compile(r'EventType: TYPE_VIEW_ACCESSIBILITY_FOCUSED; EventTime: (\d+); PackageName: ([^;]+);.*?ClassName: ([^;]+);')
_SPEECH = re.compile(r'Speaking fragment text="(.*)", utteranceId=([^,]+),.*?event=type:EVENT_TYPE_ACCESSIBILITY subtype:TYPE_VIEW_ACCESSIBILITY_FOCUSED\s+displayId:\d+\s+time:(\d+)')


def native_focus_speech(logs: str) -> list[dict]:
    """Require the same PID/event time as the latest native accessibility focus.

    Hints, predicted feedback, old focus speech and system/reader chrome are not
    destination speech. Missing native logs remain missing evidence.
    """
    lines = logs.splitlines()
    latest = None
    for line in lines:
        tag = _TAG.search(line)
        focus = _FOCUS.search(line) if tag else None
        if focus:
            latest = (tag.group(1) or tag.group(2), *focus.groups())
    if latest is None:
        return []
    pid, event_time, package, class_name = latest
    if package in {'com.android.systemui', 'com.google.android.marvin.talkback',
                   'com.samsung.android.accessibility.talkback', 'com.iotpart.sqe.talkbackhelper'}:
        return []
    result = []
    for index, line in enumerate(lines, 1):
        tag = _TAG.search(line)
        speech = _SPEECH.search(line) if tag and 'SpeechControllerImpl' in line else None
        if not speech or (tag.group(1) or tag.group(2)) != pid or speech.group(3) != event_time:
            continue
        text = speech.group(1).strip()
        if text:
            result.append({'text': text, 'source': 'native_talkback_speaking_fragment',
                           'event_time': event_time, 'package': package, 'class_name': class_name,
                           'utterance_id': speech.group(2), 'line_index': index, 'log_line': line})
    return result
