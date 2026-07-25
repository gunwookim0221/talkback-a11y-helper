import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final


ROLE_ONLY_SPEECH: Final = frozenset({"button", "checkbox", "switch", "radio button", "tab", "image"})
ROLE_BY_CLASS_NAME: Final = {
    "android.widget.button": "Button",
    "android.widget.checkbox": "Checkbox",
    "android.widget.switch": "Switch",
    "android.widget.radiobutton": "Radio button",
}
FOCUS_SNAPSHOT_EVENTS: Final = frozenset({"TARGET_RESOLVED", "POST_ACTION_OBSERVATION", "DELAYED_OBSERVATION", "POST_FOCUS_OBSERVED"})


@dataclass(frozen=True, slots=True)
class SpeechEvidence:
    focus_snapshot: bool
    focus_event: bool
    announcement: bool


@dataclass(frozen=True, slots=True)
class SpeechStatus:
    label: str
    diagnostic: str
    role: str


def _text(value: object) -> str:
    return str(value or "").strip()


def _resource_id(payload: dict[str, object]) -> str:
    for key in ("observation", "focus", "resolvedTarget"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            value = _text(nested.get("resource_id")) or _text(nested.get("viewIdResourceName"))
            if value:
                return value
    return ""


def _load_events(path: Path) -> dict[tuple[str, str], list[dict[str, object]]]:
    if not path.is_file():
        return {}
    events: dict[tuple[str, str], list[dict[str, object]]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        scenario = _text(event.get("scenario_id"))
        step = _text(event.get("step_index"))
        if scenario and step:
            events.setdefault((scenario, step), []).append(event)
    return events


def speech_evidence_index(path: Path) -> dict[tuple[str, str], list[dict[str, object]]]:
    return _load_events(path)


def evidence_for_row(events: list[dict[str, object]], resource_id: str) -> SpeechEvidence:
    normalized_resource = resource_id.strip().lower()
    focus_snapshot = False
    focus_event = False
    announcement = False
    for event in events:
        event_type = _text(event.get("event_type"))
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        matches_resource = _resource_id(payload).strip().lower() == normalized_resource
        if event_type in FOCUS_SNAPSHOT_EVENTS and matches_resource:
            focus_snapshot = True
        if event_type == "ACCESSIBILITY_FOCUS_EVENT" and matches_resource:
            focus_event = True
        if event_type == "ANNOUNCEMENT_OBSERVED" and (matches_resource or focus_event):
            announcement = True
    return SpeechEvidence(focus_snapshot, focus_event, announcement)


def classify_speech_status(*, speech: str, visible_text: str, content_description: str, class_name: str, evidence: SpeechEvidence) -> SpeechStatus:
    normalized_speech = speech.strip().lower()
    if normalized_speech:
        if normalized_speech in ROLE_ONLY_SPEECH:
            return SpeechStatus("Role-only Speech", "role_only_speech", speech)
        return SpeechStatus("Speech Observed", "speech_observed", "")
    metadata_present = bool(visible_text.strip() or content_description.strip())
    inferred_role = ROLE_BY_CLASS_NAME.get(class_name.strip().lower(), "")
    if inferred_role and (evidence.focus_event or evidence.announcement) and not metadata_present:
        return SpeechStatus("Role-only Speech", "role_only_inferred_from_class", inferred_role)
    if evidence.focus_snapshot and not evidence.focus_event and not evidence.announcement and not metadata_present:
        return SpeechStatus("Speech Unobserved", "focus_event_missing; announcement_missing; speech_capture_missing", "")
    if (evidence.focus_event or evidence.announcement) and not metadata_present:
        return SpeechStatus("Speech Missing", "speech_missing_after_observable_focus", "")
    return SpeechStatus("Unknown", "speech_provenance_unavailable", "")


def speech_review_instruction(status: SpeechStatus, speech: str) -> str:
    if status.label == "Speech Observed":
        return f"자동화가 ‘{speech}’ 발화를 관측했습니다. 실제 단말에서도 같은 의미의 발화인지 확인하세요."
    if status.label == "Speech Unobserved":
        return "자동화에서는 실제 TalkBack 발화를 관측하지 못했습니다. 표시된 위치에서 실제 TalkBack 발화를 확인하세요."
    if status.label == "Speech Missing":
        return "자동화에서도 의미 있는 발화가 확인되지 않았습니다. 실제 발화가 없는지 확인하세요."
    if status.label == "Role-only Speech":
        return f"의미 있는 이름 없이 역할만 발화됩니다. 현재 관측값: {status.role or speech}."
    return "이전 Run에는 발화 provenance가 부족합니다. 표시된 위치에서 실제 TalkBack 발화를 확인하세요."
