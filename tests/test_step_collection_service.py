from talkback_lib.step_collection_service import StepCollectionService
from talkback_lib.utils import normalize_for_comparison


class _FakeClient:
    @staticmethod
    def normalize_for_comparison(text):
        return normalize_for_comparison(text)


def _service() -> StepCollectionService:
    return StepCollectionService(client=_FakeClient())


def test_trim_context_to_focus_anchor_trims_merged_context():
    service = _service()

    trimmed, applied, reason = service._trim_context_to_focus_anchor(
        "Edge panels Settings",
        ["Settings"],
        icon_only_focus=True,
    )

    assert applied is True
    assert trimmed == "Settings"
    assert reason == "focus_anchor_context_trim"


def test_trim_context_to_focus_anchor_keeps_short_suffix_when_not_icon_only():
    service = _service()

    trimmed, applied, reason = service._trim_context_to_focus_anchor(
        "Wi-Fi on",
        ["Wi-Fi"],
        icon_only_focus=False,
    )

    assert applied is False
    assert trimmed == "Wi-Fi on"
    assert reason == "context_tokens_too_short"


def test_focus_affinity_score_prefers_exact_or_embedded_focus_label():
    service = _service()

    assert service._focus_affinity_score("Settings", ["Settings"]) == 4
    assert service._focus_affinity_score("Edge panels Settings", ["Settings"]) >= 2


def test_snapshot_actual_focus_fields_preserves_focus_metadata():
    step = {
        "visible_label": "누수",
        "merged_announcement": "누수, 우리 집 - 거실",
        "focus_view_id": "WaterSensorCapabilityCardView_header_title",
        "focus_bounds": "84,460,822,529",
        "focus_payload_source": "top_level",
    }

    StepCollectionService._snapshot_actual_focus_fields(step)

    assert step["actual_focus_visible"] == "누수"
    assert step["actual_focus_speech"] == "누수, 우리 집 - 거실"
    assert step["actual_focus_resource_id"] == "WaterSensorCapabilityCardView_header_title"
    assert step["actual_focus_bounds"] == "84,460,822,529"
    assert step["actual_focus_payload_source"] == "top_level"
    assert step["row_source"] == "actual_focus"
    assert step["crop_source"] == "actual_focus"
