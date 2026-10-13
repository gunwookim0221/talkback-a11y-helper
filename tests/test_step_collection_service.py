from talkback_lib.step_collection_service import StepCollectionService
from talkback_lib.step_row_builder import populate_get_focus_trace_fields
from talkback_lib.utils import normalize_for_comparison


class _FakeClient:
    @staticmethod
    def normalize_for_comparison(text):
        return normalize_for_comparison(text)


def _service() -> StepCollectionService:
    return StepCollectionService(client=_FakeClient())


def test_focus_trace_preserves_partial_root_only_as_corroborating_evidence():
    step = {}
    root = {
        "className": "android.webkit.WebView",
        "packageName": "com.samsung.android.oneconnect",
        "text": "",
        "boundsInScreen": {"l": 0, "t": 94, "r": 1080, "b": 2496},
        "accessibilityFocused": True,
    }

    populate_get_focus_trace_fields(
        step,
        {
            "partial_root_evidence": root,
            "empty_reason": "untrusted_partial_payload",
            "final_payload_source": "none",
        },
    )

    assert step["get_focus_partial_root_evidence"] == root
    assert step["get_focus_final_payload_source"] == "none"


def test_focus_trace_keeps_raw_accessibility_and_diagnostic_nodes_separate():
    step = {}
    raw = {"viewIdResourceName": "DASC_0172-34", "accessibilityFocused": True,
           "boundsInScreen": "744,94,1026,94"}
    diagnostic = {"text": "Clothing Care", "focused": True, "accessibilityFocused": False}

    populate_get_focus_trace_fields(step, {
        "raw_accessibility_focus_present": True,
        "raw_accessibility_focus_source": "helper_get_focus_response",
        "raw_accessibility_focus_node": raw,
        "raw_accessibility_focus_rejection_reason": "zero_area_bounds;replaced_by_dump_fallback",
        "diagnostic_focus_node": diagnostic,
        "diagnostic_focus_source": "hierarchy_dump_input_focus",
        "diagnostic_focus_reason": "dump_replaced_insufficient_helper_focus_payload",
    })

    assert step["get_focus_raw_accessibility_focus_present"] is True
    assert step["get_focus_raw_accessibility_focus_node"] == raw
    assert step["get_focus_raw_accessibility_focus_rejection_reason"] == "zero_area_bounds;replaced_by_dump_fallback"
    assert step["get_focus_diagnostic_focus_node"] == diagnostic
    assert step["get_focus_diagnostic_focus_source"] == "hierarchy_dump_input_focus"


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
