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


def dump_with_capabilities(client,dev):
    fn=client.dump_tree
    try:
        return fn(dev=dev,include_scroll_capabilities=True)
    except TypeError as exc:
        if "include_scroll_capabilities" not in str(exc):
            raise
        return fn(dev=dev)  # Compatibility for older transports/test adapters.


def capture(client,dev,scenario_id,nodes=None,step_index=0,evidence="helper_capture"):
    if nodes is None:
        nodes=dump_with_capabilities(client,dev)
    meta=deepcopy(getattr(client,"last_dump_metadata",{}) or {})
    caps=deepcopy(getattr(client,"last_scroll_capabilities",[]) or [])
    c=capability(nodes,meta,caps)
    if c["source"] == "unknown" and callable(getattr(client,"_run",None)):
        try:
            client._run(["shell","uiautomator","dump","/sdcard/phase0b_capability.xml"],dev=dev)
            xml=client._run(["shell","cat","/sdcard/phase0b_capability.xml"],dev=dev)
            c=capability(nodes,meta,caps,raw_xml=xml)
        except Exception:
            pass
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


def verified_scroll(client,dev,scenario_id,step_idx,before=None,output_base_dir=""):
    before=before or capture(client,dev,scenario_id,step_index=step_idx,evidence="verified_scroll_before")
    target=before["capability"]["container"]
    emit(client,"SCROLL_ATTEMPTED",dict(scenario_id=scenario_id,step_index=step_idx,capability=before["capability"],viewport=before["viewport"]))
    try:
        parameters = inspect.signature(client.scroll).parameters
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
        kwargs = dict(dev=dev, direction="down")
        if target and target.get("path"):
            kwargs.update(container_path=target["path"],container_bounds=normalized_bounds(target.get("boundsInScreen")))
        else:
            kwargs["accessibility_fallback"] = True
        kwargs = {k:v for k,v in kwargs.items() if accepts_kwargs or k in parameters}
        ok=client.scroll(**kwargs)
        action=deepcopy(getattr(client,"last_scroll_result",{}) or {})
    except Exception as exc:
        ok=False; action=dict(error=type(exc).__name__)
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
    result=transition(before["viewport"],after["viewport"],ok,after["capability"])
    result.update(scenario_id=scenario_id,step_index=step_idx,capability_before=before["capability"],capability_after=after["capability"],action_result=action)
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
        if callable(getattr(client,"_run",None)):
            try:
                client._run(["shell","uiautomator","dump","/sdcard/phase0b_after_scroll.xml"],dev=dev)
                xml=client._run(["shell","cat","/sdcard/phase0b_after_scroll.xml"],dev=dev)
                (folder/f"{stem}_after_scroll.xml").write_text(xml,encoding="utf-8")
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
    log(f"[SCROLL_TRANSITION] scenario='{scenario_id}' source={before['capability']['source']} status={result['status']} "
        f"before_instances={before['viewport']['count']} after_instances={after['viewport']['count']} "
        f"persisted={result['persisted_count']} new={result['new_count']} disappeared={result['disappeared_count']} viewport_changed={str(result['viewport_changed']).lower()}")
    emit(client,"SCROLL_TRANSITION",result)
    return result,after
