from __future__ import annotations

import json

from qa_frontend.backend.promotion_readiness import (
    evaluate_promotion_readiness,
    render_promotion_readiness_markdown,
    write_promotion_readiness_artifacts,
)


def _comparison(
    result: str,
    *,
    card_id: str,
    scenario: str = "device_door_lock_plugin",
    confidence: int = 95,
    promotion_eligible: bool | None = None,
) -> dict[str, object]:
    return {
        "runtime_card_id": card_id,
        "legacy_scenario": scenario,
        "shadow_candidate": scenario if result == "MATCH" else "",
        "comparison_result": result,
        "confidence": confidence,
        "promotion_eligible": result == "MATCH"
        if promotion_eligible is None
        else promotion_eligible,
    }


def test_ready_family_requires_sufficient_high_confidence_matches():
    readiness = evaluate_promotion_readiness(
        [
            _comparison("MATCH", card_id="door-1"),
            _comparison("MATCH", card_id="door-2"),
        ],
        legacy_preserved=True,
    )

    family = readiness["families"][0]
    assert readiness["overall_status"] == "READY"
    assert readiness["status_counts"]["READY"] == 1
    assert family["plugin_family"] == "Door Lock"
    assert family["status"] == "READY"
    assert family["ready_candidate"] is True


def test_single_match_is_candidate_but_held_for_sample_size():
    readiness = evaluate_promotion_readiness(
        [_comparison("MATCH", card_id="tv-1", scenario="device_tv_plugin")],
        legacy_preserved=True,
    )

    family = readiness["families"][0]
    assert family["status"] == "HOLD"
    assert family["reason"] == "insufficient_independent_observations"
    assert family["ready_candidate"] is True


def test_known_unknown_only_family_is_insufficient_data():
    readiness = evaluate_promotion_readiness(
        [_comparison("UNKNOWN", card_id="audio-1", scenario="device_audio_plugin")],
        legacy_preserved=True,
    )

    assert readiness["families"][0]["plugin_family"] == "Audio"
    assert readiness["families"][0]["status"] == "INSUFFICIENT_DATA"


def test_unresolved_unknown_family_is_unknown_only():
    readiness = evaluate_promotion_readiness(
        [_comparison("UNKNOWN", card_id="unknown-1", scenario="")],
        identify_results=[
            {
                "runtime_card_id": "unknown-1",
                "plugin_family_candidate": "unknown",
            }
        ],
        legacy_preserved=True,
    )

    assert readiness["families"][0]["status"] == "UNKNOWN_ONLY"
    assert readiness["overall_status"] == "UNKNOWN_ONLY"


def test_mismatch_blocks_family():
    readiness = evaluate_promotion_readiness(
        [_comparison("MISMATCH", card_id="door-1")],
        legacy_preserved=True,
    )

    assert readiness["families"][0]["status"] == "BLOCKED"
    assert readiness["overall_status"] == "BLOCKED"


def test_failure_blocks_family():
    readiness = evaluate_promotion_readiness(
        [_comparison("FAILED", card_id="washer-1", scenario="device_washer_plugin")],
        legacy_preserved=True,
    )

    assert readiness["families"][0]["status"] == "BLOCKED"
    assert readiness["families"][0]["reason"] == "shadow_failure_observed"


def test_legacy_not_preserved_blocks_every_family():
    readiness = evaluate_promotion_readiness(
        [
            _comparison("MATCH", card_id="door-1"),
            _comparison("MATCH", card_id="door-2"),
        ],
        legacy_preserved=False,
    )

    assert readiness["overall_status"] == "BLOCKED"
    assert readiness["families"][0]["reason"] == "legacy_result_not_preserved"


def test_readiness_artifacts_are_json_and_markdown(tmp_path):
    readiness = evaluate_promotion_readiness(
        [_comparison("UNKNOWN", card_id="camera-1", scenario="device_camera_plugin")],
        legacy_preserved=True,
        created_at="2026-07-02T00:00:00Z",
    )

    json_path, markdown_path = write_promotion_readiness_artifacts(
        readiness,
        shadow_dir=tmp_path,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["controlled_routing_enabled"] is False
    assert "# V10 Promotion Readiness" in markdown
    assert "Camera" in render_promotion_readiness_markdown(readiness)
    assert "Controlled routing remains disabled" in markdown


def test_markdown_marks_held_ready_candidate():
    readiness = evaluate_promotion_readiness(
        [_comparison("MATCH", card_id="motion-1", scenario="device_motion_sensor_plugin")],
        legacy_preserved=True,
    )

    assert "READY CANDIDATE" in render_promotion_readiness_markdown(readiness)
