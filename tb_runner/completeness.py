"""Observed positional population reconciliation; not a whole-screen oracle.

The five primary buckets partition observed in-scope instances. UNKNOWN retains
uncertain eligibility. Semantic coverage never proves an actual focus visit.
"""
from collections import defaultdict
from tb_runner.traversal_reliability import focus_instance, instance_id, normalized_bounds
from tb_runner.utils import parse_bounds_str


def candidate(node, scenario_id):
    return dict(scenario_id=scenario_id,
                view_id=node.get("view_id", node.get("viewIdResourceName", node.get("resourceId", ""))),
                bounds=normalized_bounds(node.get("bounds", node.get("boundsInScreen", ""))),
                label=node.get("label") or node.get("text") or node.get("contentDescription") or node.get("talkbackLabel") or "",
                class_name=node.get("class_name", node.get("className", "")),
                stable_node_path=node.get("stable_node_path", node.get("path", "")),
                focusable=node.get("focusable"), clickable=node.get("clickable", node.get("effectiveClickable")),
                visible=node.get("isVisibleToUser", node.get("visibleToUser", node.get("visible", True))),
                enabled=node.get("enabled"), merged=node.get("mergedIntoAncestor", False),
                structural=node.get("isStructuralContainer", False),
                ancestor_id=node.get("ancestor_id", node.get("parentPath", "")),
                stable_logical_id=node.get("stableLogicalId"),
                role=node.get("role", ""), source=node.get("source", "helper_snapshot"))


def eligibility(item):
    b = parse_bounds_str(item["bounds"])
    if item["visible"] is False or not b or b[2] <= b[0] or b[3] <= b[1]:
        return "OUT_OF_SCOPE", "invisible_or_invalid_bounds"
    if item["merged"] or item["structural"]:
        return "OUT_OF_SCOPE", "merged_or_structural_container"
    if not item["label"] and not item["role"]:
        return "OUT_OF_SCOPE", "no_label_or_role"
    if item["focusable"] is True or item["clickable"] is True:
        return "EXPECTED", "focusable_or_actionable"
    return "UNKNOWN", "readable_eligibility_not_proven"


def confirmed_focus(row):
    observed = focus_instance(row)
    if observed is None:
        return None
    node = row.get("focus_node", {})
    if isinstance(node, str):
        import json
        try:
            node = json.loads(node)
        except (ValueError, TypeError):
            node = {}
    node = node if isinstance(node, dict) else {}
    a11y = row.get("actual_focus_accessibility_focused")
    if a11y is None and row.get("row_source") not in {"representative", "representative_fallback"}:
        a11y = node.get("accessibilityFocused")
    # Input focus alone is not a TalkBack accessibility-focus oracle.
    return observed if a11y is True else None


def reconcile(scenario_id, inventory, rows, observations=(), coverage_records=(), termination="", focus_observations=(), stale_aliases=None):
    records = {}
    history = []
    seen = set()
    previous = set()

    def observe(node, viewport_id=None):
        item = candidate(node, scenario_id)
        key = instance_id(item)
        state, reason = eligibility(item)
        prior = records.get(key)
        priority = {"OUT_OF_SCOPE": 0, "UNKNOWN": 1, "EXPECTED": 2}
        if prior is None:
            records[key] = dict(item, instance_id=key, eligibility=state, eligibility_reason=reason,
                                viewport_ids=[], sources=[])
        elif priority[state] > priority[prior["eligibility"]]:
            prior.update(item, eligibility=state, eligibility_reason=reason)
        record = records[key]
        if viewport_id is not None and viewport_id not in record["viewport_ids"]:
            record["viewport_ids"].append(viewport_id)
        if item["source"] not in record["sources"]:
            record["sources"].append(item["source"])
        return key, state

    from tb_runner.scroll_reliability import flat_nodes
    frames = [dict(o, evidence=o.get("evidence", "helper_capture")) for o in observations]
    for row in rows:
        nodes = row.get("dump_tree_nodes")
        if isinstance(nodes, list) and nodes:
            frames.append(dict(nodes=nodes, step_index=row.get("step_index", 0), evidence="persisted_row_dump"))
    frames.sort(key=lambda frame: int(frame.get("step_index", 0) or 0))
    last_visible = None
    for observation in frames:
        eligible_keys = {instance_id(candidate(n, scenario_id)) for n in flat_nodes(observation.get("nodes", []))
                         if eligibility(candidate(n, scenario_id))[0] != "OUT_OF_SCOPE"}
        if last_visible == eligible_keys and history:
            # Geometry can be stable while candidate eligibility becomes
            # stronger. Keep that evidence without creating a new viewport.
            for node in flat_nodes(observation.get("nodes", [])):
                observe(node, history[-1]["viewport_id"])
            history[-1]["repeated_observations"] += 1
            continue
        last_visible = eligible_keys
        visible = set()
        viewport_id = f"viewport_{len(history)}"
        for node in flat_nodes(observation.get("nodes", [])):
            key, state = observe(node, viewport_id)
            if state != "OUT_OF_SCOPE":
                visible.add(key)
        history.append(dict(viewport_id=viewport_id, evidence=observation.get("evidence", "helper_capture"),
                            step_index=observation.get("step_index", 0), repeated_observations=0,
                            signature=observation.get("viewport", {}).get("signature"),
                            visible_expected=sorted(visible), new_expected=sorted(visible-seen),
                            persisted=sorted(visible & previous), disappeared=sorted(previous-visible)))
        seen.update(visible)
        previous = visible
    for item in inventory:
        observe(item)
    visited = set()
    uncertain_focus = set()
    for row in [*rows, *focus_observations]:
        observed = confirmed_focus(row)
        if observed:
            key, _ = observe(dict(observed, focusable=True, source="actual_accessibility_focus"))
            visited.add(key)
        else:
            weaker = focus_instance(row)
            if weaker:
                uncertain_focus.add(instance_id(weaker))
    semantic = {r.get("canonical_id", r.get("instance_id", "")) for r in coverage_records
                if r.get("visit_status") == "SEMANTICALLY_COVERED"}
    buckets = defaultdict(list)
    logical_positions = defaultdict(set)
    stale_aliases=stale_aliases or {}
    for key, record in records.items():
        state = record["eligibility"]
        bucket = "OUT_OF_SCOPE_INSTANCES" if state == "OUT_OF_SCOPE" else (
            "ACTUAL_VISITED_INSTANCES" if key in visited else
            "STALE_INSTANCES" if key in stale_aliases else
            "UNKNOWN_INSTANCES" if state == "UNKNOWN" else
            "SEMANTICALLY_COVERED_INSTANCES" if key in semantic else "MISSED_INSTANCES")
        record["population_status"] = bucket
        record["identity_confidence"] = "POSITIONAL_ONLY"
        record["focus_evidence_uncertain"] = key in uncertain_focus
        record["stale_alias"] = key in stale_aliases
        record["replacement_instance"] = stale_aliases.get(key)
        buckets[bucket].append(key)
        if record["view_id"] and record["label"]:
            logical_positions[(record["view_id"], record["label"])].add(record["bounds"])
    for viewport in history:
        viewport["visited"] = sorted(set(viewport["visible_expected"]) & visited)
        viewport["visited_contract"] = "run-wide actual focus intersection; not a timestamp-local focus count"
        for field in ("visible_expected", "new_expected", "persisted", "disappeared", "visited"):
            viewport[field+"_count"] = len(viewport[field])
    actual = len(buckets["ACTUAL_VISITED_INSTANCES"])
    semantic_count = len(buckets["SEMANTICALLY_COVERED_INSTANCES"])
    missed = len(buckets["MISSED_INSTANCES"])
    unknown = len(buckets["UNKNOWN_INSTANCES"])
    confirmed = actual + semantic_count + missed
    summary = dict(completeness_expected=confirmed+unknown, completeness_expected_confirmed=confirmed,
                   completeness_actual_visited=actual, completeness_semantic_covered=semantic_count,
                   completeness_missed=missed, completeness_unknown=unknown,
                   completeness_stale=len(buckets["STALE_INSTANCES"]),
                   completeness_observed_total=confirmed+unknown+len(buckets["STALE_INSTANCES"]),
                   completeness_out_of_scope=len(buckets["OUT_OF_SCOPE_INSTANCES"]),
                   completeness_viewports=len(history),
                   completeness_rate=round(actual/confirmed*100, 2) if confirmed else None,
                   completeness_denominator="actual_accessibility_focus / observed_expected_confirmed; UNKNOWN separate",
                   completeness_population_complete=False,
                   completeness_observation_status="OBSERVED_PARTIAL" if frames or records else "UNOBSERVED",
                   identity_confidence="POSITIONAL_ONLY",
                   identity_relocation_groups=sum(len(bounds)>1 for bounds in logical_positions.values()),
                   completeness_contract="phase0d-observed-positional-v1", termination_status=termination)
    return dict(schema_version="phase0d-completeness-v1", scenario_id=scenario_id,
                focus_observations=list(focus_observations),
                summary=summary, records=list(records.values()), viewports=history,
                populations={name: sorted(buckets[name]) for name in (
                    "ACTUAL_VISITED_INSTANCES", "SEMANTICALLY_COVERED_INSTANCES", "MISSED_INSTANCES",
                    "UNKNOWN_INSTANCES", "OUT_OF_SCOPE_INSTANCES", "STALE_INSTANCES")},
                expected_instances=sorted(k for k,r in records.items() if r["eligibility"] != "OUT_OF_SCOPE" and r["population_status"]!="STALE_INSTANCES"))
