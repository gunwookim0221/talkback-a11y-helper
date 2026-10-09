"""Global destinations are verified state observations, not body focus visits."""
import json
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET

from tb_runner.bottom_nav import annotate_bottom_nav_candidates
from tb_runner.label_matcher import canonicalize_label
from tb_runner.logging_utils import log
from tb_runner.scroll_reliability import dump_with_capabilities, viewport
from tb_runner.traversal_reliability import instance_id, normalized_bounds
from tb_runner.utils import parse_bounds_str


def expected_destinations(config):
    labels = config.get("global_nav", {}).get("labels", [])
    return list(dict.fromkeys(canonicalize_label(label, domain="bottom_tab") or str(label).casefold()
                              for label in labels if str(label).strip()))


def xml_nodes(raw):
    start = raw.find("<hierarchy")
    root = ET.fromstring(raw[start:])
    result = []

    def walk(element, path, ancestors):
        for index, child in enumerate(element):
            child_path = f"{path}.{index}"
            a = child.attrib
            node = dict(text=a.get("text", ""), contentDescription=a.get("content-desc", ""),
                        viewIdResourceName=a.get("resource-id", ""), className=a.get("class", ""),
                        boundsInScreen=a.get("bounds", ""), selected=a.get("selected") == "true",
                        clickable=a.get("clickable") == "true", focusable=a.get("focusable") == "true",
                        enabled=a.get("enabled", "true") == "true", visibleToUser=a.get("visible-to-user", "true") == "true",
                        role=a.get("role", ""), stable_node_path=child_path, ancestors=ancestors)
            result.append(node)
            walk(child, child_path, ancestors + [dict(path=child_path, resource_id=node["viewIdResourceName"],
                                                     class_name=node["className"], role=node["role"])])
    walk(root, "0", [])
    return result


def discover(nodes, config):
    expected = expected_destinations(config)
    annotated = annotate_bottom_nav_candidates(nodes, expected_count=len(expected))
    fallback_names = {canonicalize_label(n.get("contentDescription") or n.get("text"), domain="bottom_tab")
                      for n in annotated if n.get("_bottom_nav_candidate")}
    fallback_valid = set(expected) <= fallback_names and any(n.get("selected") for n in annotated if n.get("_bottom_nav_candidate"))
    items = []
    known_ids = config.get("global_nav", {}).get("resource_ids", [])
    for n in annotated:
        if n.get("visibleToUser", n.get("isVisibleToUser", True)) is False or n.get("enabled", True) is False:
            continue
        label = n.get("contentDescription") or n.get("text") or ""
        logical = canonicalize_label(label, domain="bottom_tab")
        rid = n.get("viewIdResourceName", "")
        if not logical and rid in known_ids:
            index = known_ids.index(rid)
            logical = expected[index] if index < len(expected) else None
        if logical not in expected:
            continue
        ancestry = n.get("ancestors", [])
        container = next((a for a in reversed(ancestry) if re.search(
            r"bottom[_-]?nav|navigation[_-]?bar|bottomnavigation|navigationbar",
            a.get("resource_id", "") + " " + a.get("class_name", ""), re.I) or a.get("role") in {"tablist", "navigation"}), None)
        role = str(n.get("role", "")).casefold()
        semantic = role == "tab" or bool(n.get("isBottomNavigationBar"))
        structural = bool(container and n.get("focusable"))
        legacy = rid in known_ids
        fallback = fallback_valid and n.get("_bottom_nav_candidate")
        if not (semantic or structural or legacy or fallback):
            continue
        bounds = normalized_bounds(n.get("boundsInScreen"))
        item = dict(logical_name=logical, role="tab" if semantic else "navigation_destination",
                    selected=n.get("selected") is True, actionable=bool(n.get("clickable") or n.get("focusable")),
                    bounds=bounds, semantic_label=label, view_id=rid,
                    stable_node_path=n.get("stable_node_path", ""), container_id=(container or {}).get("path", ""),
                    evidence_source="role" if semantic else "container_ancestry" if structural else "configured_resource_id" if legacy else "semantic_bottom_row")
        item["instance_id"] = instance_id(dict(item, scenario_id=config.get("scenario_id", "global_nav_main"), label=label))
        items.append(item)
    if any(i["container_id"] for i in items):
        items = [i for i in items if i["container_id"] or i["view_id"] in known_ids]
    return sorted({i["instance_id"]: i for i in items}.values(), key=lambda i: (parse_bounds_str(i["bounds"]) or (0, 0, 0, 0))[0])


def current(items):
    selected = [i for i in items if i["selected"]]
    return selected[0] if len(selected) == 1 else None


def next_unseen(items, verified, attempts):
    return next((i for i in items if i["logical_name"] not in verified and attempts.get(i["logical_name"], 0) < 2
                 and i["actionable"] and i["bounds"]), None)


def verify_transition(before, after, target, action_success, markers=()):
    if isinstance(markers, str):
        markers = [markers]
    selected_before = [i["logical_name"] for i in before["items"] if i["selected"]]
    selected_after = [i["logical_name"] for i in after["items"] if i["selected"]]
    changed = set(selected_before) != set(selected_after)
    selected_confirmed = selected_after == [target["logical_name"]]
    marker_verified = any(pattern and re.search(pattern, json.dumps(after["nodes"], ensure_ascii=False), re.I)
                          and not re.search(pattern, json.dumps(before["nodes"], ensure_ascii=False), re.I) for pattern in markers)
    fingerprint_changed = bool(before["viewport"]["valid"] and after["viewport"]["valid"]
                               and before["viewport"]["stable_signature"] != after["viewport"]["stable_signature"])
    # A generic changing body is supplementary evidence, never an oracle for the target.
    verified = bool(action_success and after["items"] and ((selected_confirmed and changed) or
                    (marker_verified and (not selected_after or selected_confirmed))))
    return dict(selected_before=selected_before, selected_after=selected_after, selected_state_changed=changed,
                selected_confirmed=selected_confirmed, screen_fingerprint_changed=fingerprint_changed,
                destination_marker_changed=bool(marker_verified), destination_verified=verified,
                result="VERIFIED" if verified else "ACTIVATED_NOT_VERIFIED" if action_success else "ACTIVATION_FAILED")


def capture(client, dev, config, folder, index):
    nodes = dump_with_capabilities(client, dev)
    from talkback_lib.hierarchy_snapshot import flatten_service_hierarchy

    hierarchy = client.dump_hierarchy(dev=dev)
    candidates = flatten_service_hierarchy(hierarchy)
    observation = dict(nodes=nodes, items=discover(candidates, config), viewport=viewport(nodes, config.get("scenario_id", "")),
                       source="accessibility_service_hierarchy", service_hierarchy=hierarchy)
    if folder:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"snapshot_{index:03d}.json"
        path.write_text(json.dumps(observation, ensure_ascii=False, indent=2), encoding="utf-8")
        observation["snapshot_path"] = str(path)
        path.with_suffix(".hierarchy.json").write_text(
            json.dumps(hierarchy, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return observation


def emit(client, event, payload):
    runtime = getattr(client, "evidence_runtime", None)
    if getattr(runtime, "is_enabled", False):
        runtime.emit(event, producer="runner", phase="global_navigation", payload=payload)


def collect(client, dev, config, all_rows, output_path, output_base_dir, scenario_perf=None):
    scenario = config.get("scenario_id", "global_nav_main")
    runtime = getattr(client, "evidence_runtime", None)
    if getattr(runtime, "is_enabled", False):
        runtime.start_scenario(scenario, plugin_family="global_nav")
    expected = expected_destinations(config)
    folder = Path(output_base_dir) / scenario / "global_nav_dumps" if output_base_dir else None
    rows, transitions, verified, attempts, discovered = [], [], set(), {}, {}
    activation_failures = verification_failures = 0
    cap = min(max(1, int(config.get("max_steps", 10))), max(1, len(expected) * 2))
    reason = "global_nav_incomplete"
    error = ""

    def record(item, evidence, state, attempted):
        row = dict(scenario_id=scenario, scenario_type="global_nav", tab_name=config.get("tab_name", ""),
                   step_index=len(rows), row_source="global_navigation_state", physical_visited=False,
                   nav_logical_name=item["logical_name"], nav_instance_id=item["instance_id"], nav_item=item,
                   nav_state=state, nav_activation_attempted=attempted, nav_selected_confirmed=evidence.get("selected_confirmed", False),
                   nav_destination_verified=evidence["destination_verified"], nav_transition=evidence,
                   visible_label=item["semantic_label"], merged_announcement="", status="GLOBAL_NAV_" + state,
                   traversal_result="GLOBAL_NAV_" + state, final_result="PASS" if evidence["destination_verified"] else "FAIL")
        rows.append(row)
        all_rows.append(row)

    try:
        before = capture(client, dev, config, folder, 0)
        discovered.update({i["instance_id"]: i for i in before["items"]})
        selected = current(before["items"])
        if selected:
            verified.add(selected["logical_name"])
            evidence = dict(destination_verified=True, selected_confirmed=True, selected_before=[selected["logical_name"]],
                            selected_after=[selected["logical_name"]], selected_state_changed=False, result="CURRENT_VERIFIED",
                            snapshot_path=before.get("snapshot_path", ""), activation_attempted=False)
            record(selected, evidence, "CURRENT", False)
            emit(client, "GLOBAL_NAV_CURRENT", dict(scenario_id=scenario, item=selected, **evidence))
        while set(expected) - verified:
            if sum(attempts.values()) >= cap:
                reason = "global_nav_safety_limit"
                break
            target = next_unseen(before["items"], verified, attempts)
            if not target:
                break
            logical = target["logical_name"]
            attempts[logical] = attempts.get(logical, 0) + 1
            action_error = ""
            try:
                l, t, r, b = parse_bounds_str(target["bounds"])
                activated = bool(client.touch_point(dev=dev, x=(l+r)//2, y=(t+b)//2))
            except Exception as exc:
                activated = False
                action_error = str(exc)
            time.sleep(float(config.get("global_nav_stabilization_seconds", .5)))
            try:
                after = capture(client, dev, config, folder, sum(attempts.values()))
            except Exception as exc:
                error = str(exc)
                after = dict(nodes=[], items=[], viewport=viewport([], scenario), snapshot_error=error)
            discovered.update({i["instance_id"]: i for i in after["items"]})
            evidence = verify_transition(before, after, target, activated, config.get("global_nav_destination_markers", {}).get(logical, []))
            focus_confirmed = False
            focus_error = ""
            if callable(getattr(client, "get_focus", None)):
                try:
                    focus = client.get_focus(dev=dev) or {}
                    node = focus.get("node", focus)
                    focus_confirmed = bool(isinstance(node, dict) and (node.get("accessibilityFocused") or node.get("focused"))
                                           and normalized_bounds(node.get("boundsInScreen")) == target["bounds"])
                except Exception as exc:
                    focus_error = str(exc)
            if not activated and focus_confirmed:
                evidence["result"] = "FOCUSED_NOT_ACTIVATED"
            evidence.update(scenario_id=scenario, logical_name=logical, instance_id=target["instance_id"],
                            focus_confirmed=focus_confirmed, activation_action_success=activated,
                            activation_confirmed=evidence["destination_verified"], activation_attempted=True,
                            before_snapshot=before.get("snapshot_path", ""), after_snapshot=after.get("snapshot_path", ""),
                            action_error=action_error, focus_observation_error=focus_error,
                            after_snapshot_error=after.get("snapshot_error", ""))
            if evidence["destination_verified"]:
                verified.add(logical)
            elif activated:
                verification_failures += 1
            else:
                activation_failures += 1
            transitions.append(evidence)
            record(target, evidence, evidence["result"], True)
            emit(client, "GLOBAL_NAV_TRANSITION", evidence)
            log(f"[GLOBAL_NAV_TRANSITION] from={evidence['selected_before']} to={logical} focus_confirmed={focus_confirmed} "
                f"activation_confirmed={evidence['activation_confirmed']} selected_state_changed={evidence['selected_state_changed']} "
                f"destination_verified={evidence['destination_verified']} result={evidence['result']}")
            before = after
        if expected and set(expected) <= verified:
            reason = "global_nav_verified"
    except Exception as exc:
        error = str(exc)
    status = "COMPLETED" if reason == "global_nav_verified" else "INCOMPLETE_SAFETY_LIMIT" if reason == "global_nav_safety_limit" else "INCOMPLETE_GLOBAL_NAV"
    summary = dict(scenario_id=scenario, scenario_type="global_nav", candidate_policy="GLOBAL_NAV_ONLY",
                   nav_items_discovered=len({i["logical_name"] for i in discovered.values()}), nav_instances_discovered=len(discovered),
                   nav_items_expected=len(expected), nav_items_verified=len(verified), nav_activation_attempts=sum(attempts.values()),
                   nav_recorded_rows=len(rows) or 1,
                   nav_activation_failures=activation_failures, destination_verification_failures=verification_failures,
                   nav_verified_destinations=sorted(verified), nav_missing_destinations=sorted(set(expected)-verified),
                   nav_attempt_safety_cap=cap, stop_reason=reason, termination_status=status, error=error)
    if not rows:
        row = dict(scenario_id=scenario, scenario_type="global_nav", step_index=0, row_source="global_navigation_state", physical_visited=False,
                   status="GLOBAL_NAV_FAILED", final_result="FAIL", visible_label="", merged_announcement="")
        rows.append(row)
        all_rows.append(row)
    for row in rows:
        row.update(summary)
    client.last_main_traversal_summary = summary
    if scenario_perf:
        scenario_perf.finalize()
    emit(client, "GLOBAL_NAV_SUMMARY", summary)
    emit(client, "SCENARIO_TERMINAL", summary)
    log(f"[GLOBAL_NAV_SUMMARY] expected={len(expected)} verified={len(verified)} failed={len(set(expected)-verified)} termination={status}")
    if output_path:
        path = Path(output_path).with_suffix(".global_nav.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(schema_version="phase0c-global-nav-v1", summary=summary,
                                        items=list(discovered.values()), transitions=transitions, rows=rows), ensure_ascii=False, indent=2), encoding="utf-8")
    return rows
