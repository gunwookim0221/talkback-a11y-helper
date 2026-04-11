from __future__ import annotations

import json
from pathlib import Path

import capture_debug_bundle as cdb


def _write_xml(tmp_path: Path, body: str) -> Path:
    xml_path = tmp_path / "window_dump.xml"
    xml_path.write_text(body, encoding="utf-8")
    return xml_path


def test_resource_ids_reflected_when_helper_only():
    nodes = [
        {
            "text": "Air Care",
            "view_id_resource_name": "com.samsung.android.oneconnect:id/tvHeaderTitle",
            "class_name": "android.widget.TextView",
            "bounds": "[0,300][1080,420]",
        }
    ]

    summary = cdb.summarize_nodes(nodes, xml_path=None)

    assert summary["resource_ids_top_n"] == ["com.samsung.android.oneconnect:id/tvHeaderTitle"]
    assert summary["resource_id_sources"]["com.samsung.android.oneconnect:id/tvHeaderTitle"] == "helper_only"
    assert summary["resource_id_extract_summary"]["helper_count"] >= 1
    assert summary["resource_id_extract_summary"]["xml_count"] == 0


def test_resource_ids_reflected_when_xml_only(tmp_path: Path):
    xml_path = _write_xml(
        tmp_path,
        """
        <hierarchy>
          <node class="android.widget.FrameLayout" resource-id="com.samsung.android.oneconnect:id/frameLayout" text="" bounds="[0,300][1080,880]"/>
        </hierarchy>
        """,
    )

    summary = cdb.summarize_nodes([], xml_path=xml_path)

    assert "com.samsung.android.oneconnect:id/frameLayout" in summary["resource_ids_top_n"]
    assert summary["resource_id_sources"]["com.samsung.android.oneconnect:id/frameLayout"] == "xml_only"


def test_resource_ids_merge_and_dedup(tmp_path: Path):
    nodes = [{"view_id": "com.pkg:id/frameLayout"}]
    xml_path = _write_xml(
        tmp_path,
        """
        <hierarchy>
          <node class="android.widget.FrameLayout" resource-id="com.pkg:id/frameLayout" bounds="[0,300][1080,880]"/>
          <node class="android.widget.TextView" resource-id="com.pkg:id/tvHeaderTitle" text="Home Care" bounds="[0,310][800,420]"/>
        </hierarchy>
        """,
    )

    summary = cdb.summarize_nodes(nodes, xml_path=xml_path)

    assert summary["resource_id_counts"]["com.pkg:id/frameLayout"] >= 2
    assert summary["resource_id_sources"]["com.pkg:id/frameLayout"] == "helper+xml"
    assert "com.pkg:id/tvHeaderTitle" in summary["resource_ids_top_n"]


def test_invalid_resource_ids_filtered(tmp_path: Path):
    nodes = [
        {"view_id": " "},
        {"resourceId": "none"},
        {"resource_id": "null"},
        {"view_id": None},
    ]
    xml_path = _write_xml(
        tmp_path,
        """
        <hierarchy>
          <node resource-id="" class="android.widget.TextView"/>
          <node resource-id="null" class="android.widget.TextView"/>
          <node resource-id="none" class="android.widget.TextView"/>
        </hierarchy>
        """,
    )

    summary = cdb.summarize_nodes(nodes, xml_path=xml_path)

    assert summary["resource_ids_top_n"] == []
    assert summary["resource_id_extract_summary"]["dropped_empty_count"] >= 4


def test_card_like_and_chrome_split(tmp_path: Path):
    nodes = [
        {
            "text": "Air Care",
            "view_id_resource_name": "com.samsung.android.oneconnect:id/containerHeaderLayout",
            "class_name": "android.widget.FrameLayout",
            "bounds": "[0,350][1080,980]",
        }
    ]
    xml_path = _write_xml(
        tmp_path,
        """
        <hierarchy>
          <node text="QR code" class="android.widget.TextView" bounds="[900,20][1060,90]" resource-id="com.pkg:id/topAction"/>
          <node text="Life" class="android.widget.TextView" bounds="[430,1760][620,1860]" resource-id="com.pkg:id/bottomTabLife"/>
        </hierarchy>
        """,
    )

    summary = cdb.summarize_nodes(nodes, xml_path=xml_path)

    assert "com.samsung.android.oneconnect:id/containerHeaderLayout" in summary["resource_ids_card_like_top_n"]
    assert summary["maybe_card_like_nodes_top_n"]
    assert summary["top_bar_present"] is True
    assert summary["bottom_tab_present"] is True
    assert "QR code" in summary["chrome_filtered_labels"]
    assert "Air Care" in summary["content_candidate_labels"]


def test_run_summary_contains_resource_id_unions(tmp_path: Path, monkeypatch):
    output_base = tmp_path / "output"
    monkeypatch.setattr(cdb, "OUTPUT_BASE", output_base)
    monkeypatch.setattr(cdb, "enter_life_tab", lambda dev: {"ok": True})
    monkeypatch.setattr(cdb.client, "scroll_to_top", lambda **kwargs: {"ok": True})

    calls = {"count": 0}

    def fake_save_step_bundle(**kwargs):
        calls["count"] += 1
        step = calls["count"]
        if step == 1:
            meta = {
                "step_index": 1,
                "resource_id_counts": {"com.pkg:id/frameLayout": 2},
                "resource_ids_card_like_top_n": ["com.pkg:id/frameLayout"],
                "resource_id_extract_summary": {"helper_count": 2, "xml_count": 0, "merged_count": 1, "dropped_empty_count": 0},
            }
        else:
            meta = {
                "step_index": 2,
                "resource_id_counts": {"com.pkg:id/tvHeaderTitle": 1},
                "resource_ids_card_like_top_n": ["com.pkg:id/tvHeaderTitle"],
                "resource_id_extract_summary": {"helper_count": 0, "xml_count": 1, "merged_count": 1, "dropped_empty_count": 0},
            }
        return {"meta": meta, "signature": f"sig-{step}"}

    monkeypatch.setattr(cdb, "save_step_bundle", fake_save_step_bundle)

    scroll_calls = {"count": 0}

    def fake_scroll(**kwargs):
        scroll_calls["count"] += 1
        return scroll_calls["count"] == 1

    monkeypatch.setattr(cdb.client, "scroll", fake_scroll)

    run_dir = cdb.run_scroll_capture(serial="ABC123", max_steps=3, save_xml=False, wait_seconds=0.0)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert "com.pkg:id/frameLayout" in summary["resource_ids_union_top_n"]
    assert "com.pkg:id/tvHeaderTitle" in summary["resource_ids_union_top_n"]
    assert summary["steps_with_helper_only_ids"] == [1]
    assert summary["steps_with_xml_only_ids"] == [2]
    assert summary["steps_with_no_resource_ids"] == []
