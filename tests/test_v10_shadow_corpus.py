from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa_frontend.backend.v10_shadow_corpus import (
    ShadowCorpusError,
    build_corpus_entry,
    build_family_summary,
    build_readiness_summary,
    update_shadow_corpus,
)
from tools.update_v10_shadow_corpus import main


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _device_run(
    tmp_path: Path,
    *,
    serial: str = "SERIAL-1",
    model: str = "MODEL-1",
    locale: str = "en-US",
    result: str = "MATCH",
    readiness: str = "HOLD",
    family: str = "Door Lock",
    scenario: str = "device_door_lock_plugin",
    label: str = "Front Door",
) -> Path:
    run_dir = tmp_path / f"batch-{serial}" / f"device-{serial}"
    shadow_dir = run_dir / "shadow"
    _write_json(
        run_dir / "summary.json",
        {
            "batch_id": f"batch-{serial}",
            "serial": serial,
            "model": model,
            "device_locale": locale,
            "app_version": "1.2.3",
            "android_version": "16",
        },
    )
    _write_json(run_dir / "runtime_config.json", {"language_mode": locale})
    _write_json(
        shadow_dir / "shadow_inventory.json",
        {
            "run_id": f"batch-{serial}",
            "device_name": model,
            "inventory": {
                "inventory_id": "inventory-1",
                "device_serial": serial,
                "item_count": 1,
                "items": [{"runtime_card_id": "card-1"}],
            },
        },
    )
    _write_json(
        shadow_dir / "shadow_identify.json",
        {
            "inventory_id": "inventory-1",
            "results": [
                {
                    "runtime_card_id": "card-1",
                    "plugin_family_candidate": "GenericLockCapability",
                    "decision": "identified" if result == "MATCH" else "unknown",
                    "confidence": 96,
                }
            ],
        },
    )
    _write_json(
        shadow_dir / "shadow_routing.json",
        {"results": [{"runtime_card_id": "card-1"}]},
    )
    _write_json(
        shadow_dir / "shadow_compare.json",
        {
            "shadow_run_id": f"shadow-{serial}",
            "created_at": "2026-07-02T07:36:33Z",
            "metrics": {
                f"{result.lower()}_count": 1,
                "promotion_eligible_count": 1 if result == "MATCH" else 0,
            },
            "comparisons": [
                {
                    "runtime_card_id": "card-1",
                    "legacy_scenario": scenario,
                    "shadow_candidate": scenario if result == "MATCH" else "",
                    "display_label": f"{label} Locked",
                    "stable_label": label,
                    "comparison_result": result,
                    "comparison_reason": f"test_{result.lower()}",
                    "confidence": 96,
                    "promotion_eligible": result == "MATCH",
                }
            ],
        },
    )
    _write_json(
        shadow_dir / "promotion_readiness.json",
        {
            "overall_status": readiness,
            "families": [
                {
                    "plugin_family": family,
                    "status": readiness,
                    "reason": "test_readiness",
                }
            ],
        },
    )
    (shadow_dir / "shadow_report.md").write_text("report", encoding="utf-8")
    (shadow_dir / "promotion_readiness.md").write_text(
        "readiness",
        encoding="utf-8",
    )
    return run_dir


def test_build_corpus_entry_summarizes_shadow_artifacts(tmp_path):
    run_dir = _device_run(tmp_path)

    entry = build_corpus_entry(run_dir)

    assert entry["inventory_count"] == 1
    assert entry["identify_count"] == 1
    assert entry["identified_count"] == 1
    assert entry["match_count"] == 1
    assert entry["overall_readiness"] == "HOLD"
    assert entry["device_model"] == "MODEL-1"
    assert entry["locale"] == "en-US"
    assert entry["family_results"] == [
        {
            "family": "Door Lock",
            "legacy_scenario": "device_door_lock_plugin",
            "display_label": "Front Door Locked",
            "stable_label": "Front Door",
            "comparison_result": "MATCH",
            "confidence": 96,
            "readiness": "HOLD",
            "reason": "test_match",
            "source_runtime_card_id": "card-1",
        }
    ]
    assert set(entry["source_artifacts"]) >= {
        "shadow_compare.json",
        "shadow_report.md",
    }
    assert not any(
        name.endswith((".xlsx", ".png", ".log"))
        for name in entry["source_artifacts"]
    )


def test_index_append_and_duplicate_entry_upsert(tmp_path):
    run_dir = _device_run(tmp_path)
    corpus_dir = tmp_path / "corpus"

    first = update_shadow_corpus(corpus_dir=corpus_dir, run_dir=run_dir)
    second = update_shadow_corpus(corpus_dir=corpus_dir, run_dir=run_dir)

    assert first["operation"] == "appended"
    assert second["operation"] == "updated"
    assert second["index"]["entry_count"] == 1
    assert len(list((corpus_dir / "entries").glob("*.json"))) == 1


def test_family_summary_preserves_results_and_tracks_diversity(tmp_path):
    first = build_corpus_entry(
        _device_run(
            tmp_path / "one",
            serial="SERIAL-1",
            model="MODEL-1",
            locale="en-US",
            readiness="READY",
        )
    )
    second = build_corpus_entry(
        _device_run(
            tmp_path / "two",
            serial="SERIAL-2",
            model="MODEL-2",
            locale="ko-KR",
            result="UNKNOWN",
            readiness="INSUFFICIENT_DATA",
        )
    )

    summary = build_family_summary([first, second], updated_at="now")
    door_lock = next(
        item for item in summary["families"] if item["family"] == "Door Lock"
    )

    assert door_lock["total_runs"] == 2
    assert door_lock["total_observations"] == 2
    assert door_lock["match_count"] == 1
    assert door_lock["unknown_count"] == 1
    assert door_lock["unique_device_serial_count"] == 2
    assert door_lock["unique_device_model_count"] == 2
    assert door_lock["unique_locale_count"] == 2
    assert door_lock["candidate_for_v11_pilot"] is False


def test_readiness_summary_uses_stored_readiness_without_reclassification(tmp_path):
    ready = build_corpus_entry(
        _device_run(tmp_path / "ready", readiness="READY")
    )
    blocked = build_corpus_entry(
        _device_run(
            tmp_path / "blocked",
            serial="SERIAL-2",
            result="MISMATCH",
            readiness="BLOCKED",
        )
    )

    summary = build_readiness_summary([ready, blocked], updated_at="now")

    assert summary["overall_readiness_distribution"]["READY"] == 1
    assert summary["overall_readiness_distribution"]["BLOCKED"] == 1
    assert summary["v11_pilot_candidate_families"] == []
    assert summary["controlled_routing_enabled"] is False


def test_capability_set_without_scenario_uses_stable_family_alias(tmp_path):
    run_dir = _device_run(
        tmp_path,
        result="UNKNOWN",
        readiness="UNKNOWN_ONLY",
        family="Home Camera",
        scenario="",
    )
    identify_path = run_dir / "shadow" / "shadow_identify.json"
    identify = json.loads(identify_path.read_text(encoding="utf-8"))
    identify["results"][0][
        "plugin_family_candidate"
    ] = "HomeCamera360CapabilitySet"
    _write_json(identify_path, identify)

    entry = build_corpus_entry(run_dir)

    assert entry["family_results"][0]["family"] == "Home Camera"


def test_missing_required_shadow_artifact_fails_before_writing(tmp_path):
    run_dir = _device_run(tmp_path)
    (run_dir / "shadow" / "shadow_routing.json").unlink()
    corpus_dir = tmp_path / "corpus"

    with pytest.raises(
        ShadowCorpusError,
        match="shadow_artifact_missing:shadow_routing.json",
    ):
        update_shadow_corpus(corpus_dir=corpus_dir, run_dir=run_dir)

    assert not corpus_dir.exists()


def test_dry_run_does_not_write_files(tmp_path):
    run_dir = _device_run(tmp_path)
    corpus_dir = tmp_path / "corpus"

    result = update_shadow_corpus(
        corpus_dir=corpus_dir,
        run_dir=run_dir,
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["index"]["entry_count"] == 1
    assert result["files_written"] == []
    assert not corpus_dir.exists()


def test_rebuild_recreates_index_and_summaries_from_entries(tmp_path):
    run_dir = _device_run(tmp_path)
    corpus_dir = tmp_path / "corpus"
    update_shadow_corpus(corpus_dir=corpus_dir, run_dir=run_dir)
    (corpus_dir / "index.json").write_text("{}", encoding="utf-8")
    (corpus_dir / "summaries" / "family_summary.json").write_text(
        "{}",
        encoding="utf-8",
    )

    result = update_shadow_corpus(corpus_dir=corpus_dir, rebuild=True)

    assert result["operation"] == "rebuilt"
    assert result["index"]["entry_count"] == 1
    assert result["family_summary"]["family_count"] == 1
    assert main(["--corpus-dir", str(corpus_dir), "--rebuild"]) == 0


def test_cli_requires_run_dir_unless_rebuilding(tmp_path):
    assert main(["--corpus-dir", str(tmp_path / "corpus")]) == 2
