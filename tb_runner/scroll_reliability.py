"""Capability and verified viewport transitions, reusing Phase 0A instance-v1."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from tb_runner.traversal_reliability import instance_id, normalized_bounds
from tb_runner.utils import parse_bounds_str
from tb_runner.logging_utils import log


def classify_container(class_name):
    value=str(class_name or "").lower()
    if "horizontal" in value:
        return "HORIZONTAL_TAB_SCROLL"
    if "pager" in value:
        return "PAGER"
    if any(token in value for token in ("recyclerview","gridview","listview","scrollview")):
        return "VERTICAL_CONTENT_SCROLL"
    return "UNKNOWN_SCROLL_CONTAINER"


def flat_nodes(nodes):
    for node in nodes if isinstance(nodes,list) else []:
        if not isinstance(node,dict):
            continue
        yield node
        yield from flat_nodes(node.get("children",[]))


def scroll_axis(node):
    """Directional actions outrank a class guess; forward alone has no axis."""
    cls=str(node.get("className",node.get("class", "")) or "").lower()
    ids={a.get("id") if isinstance(a,dict) else a for a in node.get("actions",[])}
    vertical=bool(ids & {16908344,16908346}) or node.get("scroll_up_supported") is True or node.get("scroll_down_supported") is True
    horizontal=bool(ids & {16908345,16908347}) or node.get("scroll_left_supported") is True or node.get("scroll_right_supported") is True
    if "pager" in cls: return "PAGER", "class"
    if vertical and horizontal: return "BIDIRECTIONAL", "directional_actions"
    if horizontal: return "HORIZONTAL", "directional_actions"
    if vertical: return "VERTICAL", "directional_actions"
    kind=classify_container(cls)
    if kind=="HORIZONTAL_TAB_SCROLL": return "HORIZONTAL", "class"
    if kind=="VERTICAL_CONTENT_SCROLL": return "VERTICAL", "class"
    return "UNKNOWN", "insufficient_axis_evidence"


def capability(nodes, metadata=None, containers=None, raw_xml=""):
    metadata=metadata or {}
    candidates=[]
    source="helper_metadata" if isinstance(metadata.get("canScrollDown"),bool) else "unknown"
    if containers:
        source="helper_metadata"
        candidates=list(containers)
    elif source == "unknown":
        candidates=[n for n in flat_nodes(nodes) if n.get("scrollable") or n.get("isScrollable") or any(k in n for k in ("canScrollForward","scroll_forward_supported"))
                    or classify_container(n.get("className",n.get("class"))) != "UNKNOWN_SCROLL_CONTAINER"]
        if candidates:
            source="flattened_node"
        elif raw_xml:
            try:
                candidates=[dict(className=n.get("class"),boundsInScreen=n.get("bounds"),viewIdResourceName=n.get("resource-id"),isScrollable=True)
                            for n in ET.fromstring(raw_xml).iter("node") if n.get("scrollable")=="true"]
                if candidates:
                    source="raw_xml_fallback"
            except ET.ParseError:
                pass
    classified=[]
    for raw in candidates:
        if raw.get("isVisibleToUser",raw.get("visibleToUser",True)) is False or raw.get("isEnabled",True) is False:
            continue
        item=deepcopy(raw)
        item["kind"]=classify_container(item.get("className",item.get("class")))
        item["axis"],item["axis_source"]=scroll_axis(item)
        item["axis_confidence"]="unknown" if item["axis"]=="UNKNOWN" else "explicit_actions" if item["axis_source"]=="directional_actions" else "class"
        item["instance_id"]=instance_id(dict(view_id=item.get("viewIdResourceName",item.get("resourceId","")),bounds=item.get("boundsInScreen",item.get("bounds",""))))
        classified.append(item)
    vertical=[n for n in classified if n["axis"] in {"VERTICAL","BIDIRECTIONAL"} and n.get("isScrollable",n.get("scrollable",True)) is not False]
    def vertical_forward(n):
        ids={a.get("id") if isinstance(a,dict) else a for a in n.get("actions",[])}
        down=n.get("scroll_down_supported") is True or 16908346 in ids
        if n["axis"]=="BIDIRECTIONAL":
            return down
        return down or n.get("scroll_forward_supported",n.get("canScrollForward")) is True or 4096 in ids
    supported=[n for n in vertical if vertical_forward(n)]
    def vertical_end_known(n):
        return not vertical_forward(n) and (n["axis"]=="BIDIRECTIONAL" or
            n.get("scroll_forward_supported",n.get("canScrollForward")) is False)
    known_vertical_end=bool(vertical) and all(vertical_end_known(n) for n in vertical)
    explicit=metadata.get("canScrollDown")
    explicit=explicit if isinstance(explicit,bool) else None
    unknown=[n for n in classified if n["axis"]=="UNKNOWN" and n.get("isScrollable",n.get("scrollable",False))
             and n.get("scroll_forward_supported",n.get("canScrollForward")) is not False]
    nonvertical_forward=any(n["axis"] in {"HORIZONTAL","PAGER","BIDIRECTIONAL"}
                           and (n.get("scroll_forward_supported",n.get("canScrollForward")) is True
                                or n.get("scroll_right_supported") is True
                                or any((a.get("id") if isinstance(a,dict) else a)==16908347 for a in n.get("actions",[]))) for n in classified)
    # An old producer's mixed-axis boolean is diagnosable, not authoritative.
    filtered_legacy=bool(containers and explicit is True and nonvertical_forward and not supported and not unknown)
    contradiction=(explicit is False and bool(supported)) or bool(
        containers and explicit is True and vertical and not supported and not filtered_legacy
        and known_vertical_end)
    value=None if contradiction else explicit
    if value is None and not contradiction and supported:
        value=True
    elif value is None and not contradiction and known_vertical_end:
        value=False
    if filtered_legacy:
        value=False
    if containers and not vertical and not unknown and classified:
        value=False; contradiction=False
    if unknown and not supported:
        value=None
    def area(n):
        b=parse_bounds_str(normalized_bounds(n.get("boundsInScreen",n.get("bounds"))))
        return (b[2]-b[0])*(b[3]-b[1]) if b else 0
    targets=supported or vertical
    target=max(targets,key=area) if targets else None
    return dict(status="SCROLL_CAPABLE" if value is True else "SCROLL_NOT_CAPABLE" if value is False else "SCROLL_CAPABILITY_UNKNOWN",
                source=source,can_scroll_forward=value,container=target,containers=classified,
                confidence="explicit_action" if supported else "explicit_metadata" if explicit is not None else "structural_only",
                contradictory=contradiction,vertical_can_scroll_forward=value,axis_contract="axis-v1",
                axis="VERTICAL" if vertical else "UNKNOWN" if unknown else "HORIZONTAL" if classified else "UNKNOWN",
                axis_source="container_actions_and_class" if classified else "legacy_metadata_unverified_axis",
                unknown_axis_containers=len(unknown),legacy_axis_filtered=filtered_legacy,
                horizontal_can_scroll_forward=nonvertical_forward)


def viewport(nodes, scenario_id, container=None):
    ids=set(); stable=set()
    container_bounds=normalized_bounds((container or {}).get("boundsInScreen",(container or {}).get("bounds")))
    cb=parse_bounds_str(container_bounds)
    for n in flat_nodes(nodes):
        if n.get("isVisibleToUser",n.get("visibleToUser",True)) is False:
            continue
        bounds=normalized_bounds(n.get("boundsInScreen",n.get("bounds")))
        b=parse_bounds_str(bounds)
        if not b or n.get("isTopAppBar") or n.get("isBottomNavigationBar"):
            continue
        if cb and (b[2]<=cb[0] or b[0]>=cb[2] or b[3]<=cb[1] or b[1]>=cb[3]):
            continue
        rid=n.get("viewIdResourceName",n.get("resourceId","")) or ""
        item=dict(scenario_id=scenario_id,view_id=rid,bounds=bounds,label=n.get("text") or n.get("contentDescription") or n.get("talkbackLabel") or "")
        ids.add(instance_id(item))
        # Same identity function, coarser geometry only for change confidence.
        quantized=",".join(str(round(v/16)*16) for v in b)
        stable.add(instance_id(dict(item,bounds=quantized)))
    digest=lambda keys: hashlib.sha256(json.dumps(sorted(keys),ensure_ascii=False).encode()).hexdigest()
    return dict(signature=digest(ids),stable_signature=digest(stable),instances=sorted(ids),count=len(ids),valid=bool(ids))


def transition(before,after,action_success,after_capability):
    b,a=set(before["instances"]),set(after["instances"])
    valid=bool(before["valid"] and after["valid"])
    changed=valid and before["stable_signature"] != after["stable_signature"]
    moved=bool(action_success and changed)
    end=bool(valid and action_success and not changed and not (a-b) and after_capability["can_scroll_forward"] is False and not after_capability["contradictory"])
    reason="scroll_error" if not action_success else "" if moved or end else "scroll_unverified"
    return dict(status="SCROLL_FAILED" if not action_success else "SCROLL_MOVED" if moved else "SCROLL_NO_CHANGE",
                action_state="SCROLL_ATTEMPTED",action_success=bool(action_success),viewport_changed=bool(changed),viewport_end=end,
                before=before,after=after,persisted=sorted(a&b),new=sorted(a-b),disappeared=sorted(b-a),
                persisted_count=len(a&b),new_count=len(a-b),disappeared_count=len(b-a),termination_reason=reason)


def _dump_with_capability_context(client,dev):
    snapshot_fn=getattr(client,"get_traversal_candidate_snapshot",None)
    if callable(snapshot_fn):
        snapshot=snapshot_fn(dev=dev)
        nodes=snapshot.candidates
        raw_scroll_tree=[]
        raw=snapshot.raw_hierarchy
        try:
            from talkback_lib.hierarchy_snapshot import legacy_scroll_nodes
            raw_scroll_tree=legacy_scroll_nodes(raw)
        except Exception as exc:
            raise RuntimeError("reliable_scroll_snapshot_invalid") from exc
        tokens=("scroll","recycler","gridview","listview","viewpager","pager")
        containers=[
            node for node in flat_nodes(raw_scroll_tree)
            if node.get("scrollable") is True
            or any(token in str(node.get(key) or "").lower()
                   for key in ("className","viewIdResourceName") for token in tokens)
        ]
        metadata_containers=deepcopy(getattr(client,"last_scroll_capabilities",[]) or [])
        return nodes,metadata_containers or containers
    fn=client.dump_tree
    try:
        return fn(dev=dev,include_scroll_capabilities=True),None
    except TypeError as exc:
        if "include_scroll_capabilities" not in str(exc):
            raise
        return fn(dev=dev),None  # Compatibility for older transports/test adapters.


def dump_with_capabilities(client,dev):
    return _dump_with_capability_context(client,dev)[0]


def capture(client,dev,scenario_id,nodes=None,step_index=0,evidence="helper_capture"):
    containers=None
    if nodes is None:
        nodes,containers=_dump_with_capability_context(client,dev)
    meta=deepcopy(getattr(client,"last_dump_metadata",{}) or {})
    caps=deepcopy(getattr(client,"last_scroll_capabilities",[]) or [])
    c=capability(nodes,meta,containers=containers or caps or None)
    if c["source"] == "unknown" and callable(getattr(client,"dump_hierarchy",None)):
        try:
            from talkback_lib.hierarchy_snapshot import service_hierarchy_to_xml

            xml=service_hierarchy_to_xml(client.dump_hierarchy(dev=dev))
            c=capability(nodes,meta,caps,raw_xml=xml)
            if c["source"] == "raw_xml_fallback":
                c["source"] = "service_hierarchy_fallback"
        except Exception:
            c["acquisition_error"] = "service_hierarchy_unavailable"
    observation = dict(nodes=nodes,capability=c,viewport=viewport(nodes,scenario_id,c["container"]),
                       step_index=step_index,evidence=evidence)
    history = getattr(client, "_completeness_observations", None)
    if history is None:
        history = {}; client._completeness_observations = history
    history.setdefault(scenario_id, []).append(deepcopy(observation))
    return observation


def emit(client,event,payload):
    runtime=getattr(client,"evidence_runtime",None)
    if getattr(runtime,"is_enabled",False):
        try:
            runtime.emit(event,producer="runner",phase="scroll",payload=payload)
        except Exception as exc:
            log(f"[SCROLL][evidence_failed] error='{type(exc).__name__}'")


def _verified_scroll_target(before, resolved_owner=None):
    """Return an exact current scroll target or a fail-closed reason."""
    capability = before.get("capability") if isinstance(before, dict) else None
    capability = capability if isinstance(capability, dict) else {}
    if (capability.get("vertical_can_scroll_forward", capability.get("can_scroll_forward")) is not True
            or capability.get("contradictory") is True):
        return None, "scroll_opportunity_unverified"

    if resolved_owner is not None:
        if (not isinstance(resolved_owner, dict) or resolved_owner.get("status") != "RESOLVED"
                or not str(resolved_owner.get("identity") or "").strip()):
            return None, "scroll_owner_unresolved"
        candidate = resolved_owner
    else:
        candidate = capability.get("container")
        if not isinstance(candidate, dict):
            return None, "scroll_owner_unresolved"

    axis = str(candidate.get("axis") or "").strip().upper()
    path = str(candidate.get("path") or "").strip()
    bounds = normalized_bounds(candidate.get("boundsInScreen", candidate.get("bounds")))
    state = candidate.get("state") if isinstance(candidate.get("state"), dict) else candidate
    if axis not in {"VERTICAL", "BIDIRECTIONAL"} or not path or not bounds:
        return None, "scroll_owner_unresolved"
    if (state.get("scrollable", state.get("isScrollable", True)) is False
            or state.get("visible", state.get("visibleToUser", True)) is False
            or state.get("enabled", state.get("isEnabled", True)) is False):
        return None, "scroll_owner_unresolved"
    return {"path": path, "bounds": bounds, "axis": axis}, ""


def _blocked_scroll_transition(before, scenario_id, reason):
    capability = before.get("capability") if isinstance(before.get("capability"), dict) else {}
    view = before.get("viewport") if isinstance(before.get("viewport"), dict) else viewport(
        before.get("nodes", []), scenario_id)
    result = transition(view, view, False, capability)
    result.update(
        status="SCROLL_BLOCKED",
        action_state="SCROLL_NOT_DISPATCHED",
        action_success=False,
        action_attempted=False,
        action_target={"mode": "UNRESOLVED_CONTAINER", "container_path": None, "container_bounds": None},
        action_result={"success": False, "status": "blocked", "reason": reason,
                       "actionSupported": False, "actionAttempted": False},
        action_request_id=None,
        action_result_request_id=None,
        action_result_correlated=False,
        termination_reason=reason,
    )
    return result


def verified_scroll(client,dev,scenario_id,step_idx,before=None,output_base_dir="",resolved_owner=None):
    before=before or capture(client,dev,scenario_id,step_index=step_idx,evidence="verified_scroll_before")
    # Clear any prior receipt before calling a client wrapper. Production
    # A11yAdbClient also clears these fields at its public dispatch boundary.
    for name, value in (("last_scroll_request_id", ""), ("last_scroll_result", {})):
        if hasattr(client, name):
            try:
                setattr(client, name, value)
            except (AttributeError, TypeError):
                pass
    target, target_error = _verified_scroll_target(before, resolved_owner)
    if target is None:
        blocked = _blocked_scroll_transition(before, scenario_id, target_error)
        log(f"[SCROLL][blocked] scenario='{scenario_id}' step={step_idx} reason='{target_error}' action_dispatched=false")
        return blocked, before

    try:
        parameters = inspect.signature(client.scroll).parameters
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
        accepts_target = accepts_kwargs or {"container_path", "container_bounds"} <= set(parameters)
    except (TypeError, ValueError, AttributeError):
        accepts_target = False
    if not accepts_target:
        reason = "targeted_scroll_dispatch_unsupported"
        blocked = _blocked_scroll_transition(before, scenario_id, reason)
        log(f"[SCROLL][blocked] scenario='{scenario_id}' step={step_idx} reason='{reason}' action_dispatched=false")
        return blocked, before

    action_target = {
        "mode": "EXPLICIT_CONTAINER",
        "container_path": target["path"],
        "container_bounds": target["bounds"],
    }
    emit(client,"SCROLL_ATTEMPTED",dict(scenario_id=scenario_id,step_index=step_idx,
        capability=before.get("capability", {}),viewport=before.get("viewport", {}),action_target=action_target))
    try:
        ok=client.scroll(dev=dev,direction="down",container_path=target["path"],container_bounds=target["bounds"])
        action=deepcopy(getattr(client,"last_scroll_result",{}) or {})
    except Exception as exc:
        ok=False; action=dict(error=type(exc).__name__)
    action_request_id = str(getattr(client, "last_scroll_request_id", "") or "").strip()
    action_result_request_id = str(action.get("reqId") or action.get("requestId")
                                   or action.get("request_id") or "").strip()
    time.sleep(0.25)
    try:
        after=capture(client,dev,scenario_id)
        history = getattr(client, "_completeness_observations", {}).get(scenario_id, [])
        if history:
            history[-1]["step_index"] = step_idx
            history[-1]["evidence"] = "verified_scroll_after"
    except Exception as exc:
        after=dict(nodes=[],capability=capability([],{}),viewport=viewport([],scenario_id))
        action["after_dump_error"]=type(exc).__name__
    targeted_result_correlated = bool(
        action_request_id and action_result_request_id == action_request_id
        and action.get("action") == "SCROLL_FORWARD"
        and action.get("direction") == "down"
        and action.get("actionAttempted") is True
        and action.get("explicitTarget") is True
        and str(action.get("scrollContainerPath") or "").strip() == target["path"]
        and action.get("success") is bool(ok)
    )
    owner_result_unverified = bool(
        (ok or action.get("actionAttempted") is True) and not targeted_result_correlated
    )
    result=transition(before["viewport"],after["viewport"],
                      bool(ok) and not owner_result_unverified,after["capability"])
    if owner_result_unverified:
        result.update(
            status="SCROLL_UNVERIFIED",
            action_state="SCROLL_ATTEMPTED_UNVERIFIED_OWNER",
            # Keep the helper's raw response in action_result, but do not let
            # an unbound fallback count as an accepted scroll operation.
            action_success=False,
            observed_action_success=bool(ok),
            target_dispatch_verified=False,
            termination_reason="scroll_owner_unverified",
        )
        blocker = {
            "category": "AUTHORITY",
            "reason": "SCROLL_RESULT_DID_NOT_CONFIRM_EXPLICIT_CURRENT_OWNER",
            "scenario_id": scenario_id,
            "step_index": step_idx,
            "action_request_id": action_request_id or None,
            "result_request_id": action_result_request_id or None,
            "requested_container_path": target["path"],
            "reported_container_path": action.get("scrollContainerPath"),
            "explicit_target": action.get("explicitTarget"),
            "action_attempted": action.get("actionAttempted"),
            "viewport_changed": result.get("viewport_changed"),
        }
        log("PHASE6F_ACCEPTANCE_BLOCKER " + json.dumps(blocker, ensure_ascii=False, sort_keys=True))
    else:
        result["target_dispatch_verified"] = targeted_result_correlated
    result.update(scenario_id=scenario_id,step_index=step_idx,
                  capability_before=before["capability"],capability_after=after["capability"],
                  action_type="SCROLL_FORWARD", direction="down",
                  action_request_id=action_request_id or None,
                  action_result_request_id=action_result_request_id or None,
                  action_result_correlated=bool(action_request_id and action_result_request_id
                                                and action_request_id == action_result_request_id),
                  action_target=action_target, action_result=action)
    result["after_dump_path"]=""
    if output_base_dir:
        folder=Path(output_base_dir)/scenario_id/"scroll_dumps"
        folder.mkdir(parents=True,exist_ok=True)
        attempt=len(list(folder.glob("*_after_scroll.json")))+1
        stem=f"step_{step_idx:03d}_attempt_{attempt:03d}"
        for phase,data in (("before_scroll",before),("after_scroll",after)):
            path=folder/f"{stem}_{phase}.json"
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
            result[phase+"_dump_path"]=str(path)
        result["after_dump_path"]=result["after_scroll_dump_path"]
        try:
            from tb_runner.audit_snapshot import write_helper_snapshot_xml
            write_helper_snapshot_xml(after["nodes"], folder/f"{stem}_after_scroll.xml")
            result["after_xml_source"] = "a11y_helper"
        except Exception as exc:
            result["after_xml_error"]=type(exc).__name__
    records=getattr(client,"_scroll_transitions",None)
    if records is None:
        records=[]; client._scroll_transitions=records
    seen = set(before["viewport"]["instances"])
    for previous in records:
        if previous.get("scenario_id") == scenario_id:
            seen.update(previous["before"]["instances"])
            seen.update(previous["after"]["instances"])
    result["newly_observed"] = sorted(set(result["new"]) - seen)
    result["newly_observed_count"] = len(result["newly_observed"])
    result["reappeared"] = sorted(set(result["new"]) & seen)
    records.append(result)
    log(f"[SCROLL_TRANSITION] scenario='{scenario_id}' source={before['capability'].get('source', 'unknown')} status={result['status']} "
        f"before_instances={before['viewport']['count']} after_instances={after['viewport']['count']} "
        f"persisted={result['persisted_count']} new={result['new_count']} disappeared={result['disappeared_count']} viewport_changed={str(result['viewport_changed']).lower()}")
    emit(client,"SCROLL_TRANSITION",result)
    return result,after
