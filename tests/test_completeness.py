import pytest
# These are real export checks. Load their dependencies before older scenario
# tests register optional-dependency stubs with sys.modules.setdefault().
import pandas
import openpyxl
from tb_runner.completeness import reconcile, candidate, eligibility
from tb_runner.traversal_reliability import instance_id


def node(bounds="0,0,100,100", **kwargs):
    return dict(view_id="id/title", bounds=bounds, label="Title", focusable=True, **kwargs)


def row(**kwargs):
    return dict(scenario_id="s", actual_focus_resource_id="id/title", actual_focus_bounds="0,0,100,100",
                actual_focus_visible="Title", actual_focus_accessibility_focused=True, **kwargs)


def run(nodes=None, rows=None, **kwargs):
    return reconcile("s", nodes or [], rows or [], **kwargs)


def test_actual_focus_and_duplicate_partition():
    result = run([node()], [row(), row()])
    assert result["summary"]["completeness_actual_visited"] == 1
    assert result["summary"]["completeness_missed"] == 0
    assert result["summary"]["completeness_rate"] == 100
    assert result["summary"]["completeness_population_complete"] is False


@pytest.mark.parametrize("changes", [dict(physical_visited=False),
    dict(actual_focus_accessibility_focused=False), dict(actual_focus_accessibility_focused=None),
    dict(actual_focus_accessibility_focused=False, actual_focus_input_focused=True),
    dict(actual_focus_bounds=""), dict(row_source="representative_fallback", physical_visited=False)])
def test_uncertain_or_false_focus_not_visited(changes):
    r = row(); r.update(changes)
    assert run([node()], [r])["summary"]["completeness_actual_visited"] == 0


def test_sibling_instance_separation():
    result = run([node(), node("0,100,100,200")], [row()])
    assert result["summary"]["completeness_expected"] == 2
    assert result["summary"]["completeness_missed"] == 1
    assert result["summary"]["identity_relocation_groups"] == 1


def test_semantic_not_actual():
    key = instance_id(dict(node(), scenario_id="s"))
    result = run([node()], coverage_records=[dict(canonical_id=key, visit_status="SEMANTICALLY_COVERED")])
    assert result["summary"]["completeness_semantic_covered"] == 1
    assert result["summary"]["completeness_actual_visited"] == 0


def test_actual_overrides_semantic():
    key = instance_id(dict(node(), scenario_id="s"))
    result = run([node()], [row()], coverage_records=[dict(canonical_id=key, visit_status="SEMANTICALLY_COVERED")])
    assert result["summary"]["completeness_semantic_covered"] == 0


def test_unknown_not_hidden_by_zero_missed():
    n = node(); n["focusable"] = False
    s = run([n])["summary"]
    assert s["completeness_unknown"] == 1 and s["completeness_missed"] == 0
    assert s["completeness_rate"] is None


@pytest.mark.parametrize("changes", [dict(visible=False), dict(bounds=""), dict(bounds="0,0,0,0"),
    dict(label=""), dict(merged=True), dict(structural=True)])
def test_out_of_scope(changes):
    n = candidate(node(), "s"); n.update(changes)
    assert eligibility(n)[0] == "OUT_OF_SCOPE"


def test_viewport_union_and_deltas():
    first, second = node(), node("0,100,100,200")
    result = run(observations=[dict(nodes=[first]), dict(nodes=[first, second]), dict(nodes=[second])])
    assert result["summary"]["completeness_expected"] == 2
    a, b, c = result["viewports"]
    assert a["new_expected_count"] == 1
    assert b["new_expected_count"] == b["persisted_count"] == 1
    assert c["new_expected_count"] == 0 and c["disappeared_count"] == 1


def test_reappearing_instance_not_new():
    result = run(observations=[dict(nodes=[node()]), dict(nodes=[]), dict(nodes=[node()])])
    assert result["viewports"][-1]["new_expected_count"] == 0


def test_helper_schema_and_visible_filter():
    result = run(observations=[dict(nodes=[dict(viewIdResourceName="rid", boundsInScreen="[0,0][10,10]",
        text="hello", focusable=True, isVisibleToUser=False)])])
    assert result["summary"]["completeness_expected"] == 0


def test_actual_focus_adds_missing_inventory():
    assert run(rows=[row()])["summary"]["completeness_expected"] == 1


def test_pre_persist_focus_proof_survives_suppression_and_mutation():
    from tb_runner.traversal_reliability import TraversalMetrics
    metrics = TraversalMetrics()
    r = row(); metrics.observe_focus(r)
    r["actual_focus_accessibility_focused"] = False
    r["physical_visited"] = False
    result = run([node()], [r], focus_observations=list(metrics.focus_observations.values()))
    assert result["summary"]["completeness_actual_visited"] == 1
    assert result["focus_observations"][0]["actual_focus_accessibility_focused"] is True


def test_unknown_pre_persist_focus_is_not_actual_talkback_visit():
    from tb_runner.traversal_reliability import TraversalMetrics
    metrics = TraversalMetrics()
    r = row(); r["actual_focus_accessibility_focused"] = None
    metrics.observe_focus(r)
    result = run([node()], focus_observations=list(metrics.focus_observations.values()))
    assert len(metrics.visited) == 0
    assert result["summary"]["completeness_actual_visited"] == 0


@pytest.mark.parametrize("termination", ["COMPLETED", "INCOMPLETE_SAFETY_LIMIT", "INCOMPLETE_NO_PROGRESS", "INCOMPLETE_ERROR"])
def test_termination_does_not_claim_population_complete(termination):
    s = run([node()], termination=termination)["summary"]
    assert s["termination_status"] == termination and s["completeness_population_complete"] is False


def test_partition_accounting():
    unknown = node("0,200,100,300"); unknown["focusable"] = False
    s = run([node(), node("0,100,100,200"), unknown], [row()])["summary"]
    assert s["completeness_expected"] == sum(s[k] for k in (
        "completeness_actual_visited", "completeness_semantic_covered", "completeness_missed", "completeness_unknown"))


def test_empty_entry_is_unobserved_not_complete():
    s = run(termination="INCOMPLETE_ERROR")["summary"]
    assert s["completeness_observation_status"] == "UNOBSERVED"
    assert s["completeness_rate"] is None and s["completeness_population_complete"] is False


def test_successful_sample_is_still_only_observed_partial():
    s = run([node()], [row()])["summary"]
    assert s["completeness_observation_status"] == "OBSERVED_PARTIAL"


def test_label_change_preserves_identity():
    n = node(); n["label"] = "Changed"
    assert run([node(), n])["summary"]["completeness_expected"] == 1


def test_merged_child_not_expected():
    n = node(); n["mergedIntoAncestor"] = True
    assert run([n])["summary"]["completeness_out_of_scope"] == 1


def test_nested_nodes_preserved():
    n = node(); n["children"] = [node("0,100,100,200")]
    assert run(observations=[dict(nodes=[n])])["summary"]["completeness_expected"] == 2


def test_public_collector_serialization(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from tb_runner import collection_flow
    events = []
    runtime = SimpleNamespace(is_enabled=True, emit=lambda event, **kw: events.append((event, kw["payload"])))
    client = SimpleNamespace(evidence_runtime=runtime)
    def inner(client, dev, cfg, all_rows, *args, **kwargs):
        r = row(); r["stop_reason"] = "safety_limit"
        all_rows.append(r)
        client.last_main_traversal_summary = dict(stop_reason="safety_limit")
        client._completeness_observations = {"s": [dict(nodes=[node(), node("0,100,100,200")])]}
        client._active_traversal_metrics.observe_focus(r)
        return [r]
    monkeypatch.setattr(collection_flow, "_collect_tab_rows_inner", inner)
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *a, **kw: None)
    monkeypatch.setattr(collection_flow, "_save_focusable_coverage", lambda *a: None)
    output = str(tmp_path / "run.xlsx")
    collection_flow._collect_tab_rows_impl(client, "serial", dict(scenario_id="s"), [], output, str(tmp_path))
    payload = json.loads((tmp_path / "run.traversal_summary.completeness.json").read_text(encoding="utf-8"))
    summary = client.last_main_traversal_summary
    assert summary["completeness_actual_visited"] == summary["unique_visited_instances"] == 1
    assert summary["completeness_missed"] == 1
    assert summary["termination_status"] == "INCOMPLETE_SAFETY_LIMIT"
    evidence = next(p for e,p in events if e == "COMPLETENESS_RECONCILIATION")
    assert evidence == payload["scenarios"][0]


def test_public_collector_preserves_focus_before_row_rewrite(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from tb_runner import collection_flow
    client = SimpleNamespace()
    def inner(client, dev, cfg, all_rows, *args, **kwargs):
        actual = row()
        actual["stop_reason"] = "safety_limit"
        client._active_traversal_metrics.observe_focus(actual)
        actual.update(physical_visited=False, row_source="representative_fallback")
        all_rows.append(actual)
        client.last_main_traversal_summary = dict(stop_reason="safety_limit")
        return [actual]
    monkeypatch.setattr(collection_flow, "_collect_tab_rows_inner", inner)
    monkeypatch.setattr(collection_flow, "save_excel_with_perf", lambda *a, **kw: None)
    output = str(tmp_path / "run.xlsx")
    collection_flow._collect_tab_rows_impl(client, "serial", dict(scenario_id="s"), [], output, str(tmp_path))
    full = json.loads((tmp_path / "run.traversal_summary.completeness.json").read_text(encoding="utf-8"))["scenarios"][0]
    coverage = json.loads((tmp_path / "run.focusable_coverage.json").read_text(encoding="utf-8"))
    assert full["summary"]["completeness_actual_visited"] == 1
    assert client.last_main_traversal_summary["unique_visited_instances"] == 1
    assert full["focus_observations"][0]["actual_focus_accessibility_focused"] is True
    assert coverage["completeness_reconciliation"] == [full]
    assert coverage["traversal_summary"] == [client._traversal_summaries["s"]]


def test_capture_preserves_history(monkeypatch):
    from types import SimpleNamespace
    from tb_runner.scroll_reliability import capture
    client = SimpleNamespace(dump_tree=lambda **kw: [node()], last_dump_metadata={"canScrollDown": False})
    capture(client, "serial", "s")
    capture(client, "serial", "s")
    assert len(client._completeness_observations["s"]) == 2


def test_fresh_capture_keeps_scroll_step_for_viewport_order():
    from types import SimpleNamespace
    from tb_runner.scroll_reliability import capture
    client = SimpleNamespace(last_dump_metadata={"canScrollDown": False})
    before = capture(client, "serial", "s", nodes=[node()], step_index=12, evidence="local_scroll_evaluation")
    assert before["step_index"] == 12
    assert client._completeness_observations["s"][0]["step_index"] == 12
    assert client._completeness_observations["s"][0]["evidence"] == "local_scroll_evaluation"


def test_excel_null_flag_uses_original_focus_node():
    r = row(); r["actual_focus_accessibility_focused"] = None
    r["focus_node"] = '{"accessibilityFocused":true}'
    assert run([node()], [r])["summary"]["completeness_actual_visited"] == 1


def test_repeated_capture_is_one_viewport():
    result = run(observations=[dict(nodes=[node()]), dict(nodes=[node()])])
    assert result["summary"]["completeness_viewports"] == 1
    assert result["viewports"][0]["repeated_observations"] == 1


def test_stable_geometry_keeps_stronger_eligibility_evidence():
    uncertain = node(); uncertain["focusable"] = False
    result = run(observations=[dict(nodes=[uncertain]), dict(nodes=[node()])])
    assert result["summary"]["completeness_viewports"] == 1
    assert result["summary"]["completeness_unknown"] == 0
    assert result["summary"]["completeness_expected_confirmed"] == 1
    assert result["summary"]["completeness_missed"] == 1


def test_implicit_scroll_row_dump_in_population():
    r = row(); r["dump_tree_nodes"] = [node("0,100,100,200")]; r["step_index"] = 1
    result = run(rows=[r], observations=[dict(nodes=[node()])])
    assert result["summary"]["completeness_expected"] == 2
    assert len(result["viewports"]) == 2


def test_coverage_keeps_additive_reconciliation(tmp_path):
    import json
    from types import SimpleNamespace
    from tb_runner.collection_flow import _save_focusable_coverage
    report = run([node()], [row()])
    client = SimpleNamespace(_completeness_scenarios={"s": report})
    output = str(tmp_path / "run.xlsx")
    _save_focusable_coverage(client, output, [])
    coverage = json.loads((tmp_path / "run.focusable_coverage.json").read_text(encoding="utf-8"))
    assert coverage["completeness_reconciliation"] == [report]


def test_excel_completeness_sheet(tmp_path):
    import openpyxl
    from tb_runner.excel_report import save_excel
    r = row(); r.update(run([node()], [r])["summary"])
    r.update(termination_status="INCOMPLETE_SAFETY_LIMIT", visible_label="Title", merged_announcement="Title")
    output = tmp_path / "run.xlsx"
    save_excel([r], str(output), with_images=False)
    workbook = openpyxl.load_workbook(output, read_only=True)
    records = list(workbook["completeness"].values)
    assert records[1][records[0].index("completeness_actual_visited")] == 1
    assert "completeness_expected" in next(workbook["traversal"].values)
    workbook.close()
