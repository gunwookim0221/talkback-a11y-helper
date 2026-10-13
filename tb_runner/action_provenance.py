"""Read-only step ownership over the existing append-only production journal.

No dispatch, focus reconciliation, visit commit or traversal policy lives here.
Final rows link to immutable primary and recovery facts, never replace them.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from tb_runner.phase4b_execution import focus_row
from tb_runner.traversal_reliability import focus_instance, instance_id

SCHEMA = "step-action-provenance-v2"
EVENT_TYPES = {"ACTION_SENT", "HELPER_ACK_RECEIVED", "POST_FOCUS_OBSERVED",
               "FOCUS_RECONCILIATION", "PRODUCTION_TRAVERSAL_GATE_DECIDED",
               "RECOVERY_CANDIDATE_RESULT", "TRANSACTION_CLOSED"}
GATES = ("AUDIT_CHAIN_INCOMPLETE_COUNT", "ORPHAN_PRIMARY_ACTION_COUNT",
         "ORPHAN_RECOVERY_ACTION_COUNT", "MISMATCHED_REQUEST_OWNERSHIP_COUNT",
         "CROSS_STEP_EVIDENCE_LEAK_COUNT", "CROSS_SCENARIO_EVIDENCE_LEAK_COUNT")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def focused_identity(node, scenario):
    if not isinstance(node, dict):
        return ""
    actual = focus_instance(focus_row(node, scenario))
    return instance_id(actual) if actual else ""


def observation_node(event):
    value = (event.get("payload") or {}).get("observation") or {}
    return dict(viewIdResourceName=value.get("resource_id"), className=value.get("class_name"),
                text=value.get("text"), contentDescription=value.get("content_description"),
                talkbackLabel=value.get("talkback_label"), boundsInScreen=value.get("bounds"),
                accessibilityFocused=value.get("accessibility_focused"), focusable=value.get("focusable"))


def production_focus_identity(node, scenario, observed_resource_id):
    """Preserve the production row's resource fallback; require raw actual focus."""
    if not isinstance(node, dict) or node.get('accessibilityFocused') is not True:
        return ''
    row = focus_row(node, scenario)
    row['actual_focus_resource_id'] = node.get('viewIdResourceName') or node.get('resourceId') or observed_resource_id or ''
    actual = focus_instance(row)
    return instance_id(actual) if actual else ''


def _request_domain(command_type):
    command = str(command_type or "").rsplit(".", 1)[-1].upper()
    if command == "GET_FOCUS":
        return "FOCUS_OBSERVATION"
    if command in {"EVIDENCE_EVENTS", "PING", "DUMP_TREE", "DUMP_HIERARCHY"}:
        return "READ_ONLY_HELPER"
    if command:
        return "ACTION_DISPATCH"
    return "UNKNOWN"


def build_action_chain(audit, row, events):
    """Snapshot existing evidence; no runtime state or row outcome is mutated."""
    scenario, step = audit["scenario"], audit["step"]
    events = [deepcopy(e.to_dict() if hasattr(e, "to_dict") else e) for e in events
              if (e.event_type if hasattr(e, "event_type") else e.get("event_type")) in EVENT_TYPES]
    owners = {(e.get("run_id"), e.get("scenario_tx_id")) for e in events if e.get("scenario_id") == scenario}
    owner = next(iter(owners)) if len(owners) == 1 else ("", "")
    action_id = json.dumps([SCHEMA, *owner, scenario, step], separators=(",", ":"))
    transactions = {}
    for event in events:
        tx = event.get("transaction_id") or ""
        if tx:
            transactions.setdefault(tx, []).append(event)
    actions = []
    for tx, group in transactions.items():
        sent = [e for e in group if e["event_type"] == "ACTION_SENT"]
        if not sent:
            continue
        is_recovery = any(":recovery:" in str(e["step_index"]) for e in sent)
        request_ids = [e["payload"].get("request_id") for e in sent]
        request_domains = {}
        request_types = {}
        for event in sent:
            request_id = event["payload"].get("request_id")
            if not request_id:
                continue
            command_type = event["payload"].get("command_type")
            request_types.setdefault(request_id, set()).add(str(command_type or ""))
            request_domains.setdefault(request_id, set()).add(_request_domain(command_type))
        actions.append(dict(action_id=action_id+":"+tx, role="RECOVERY_ACTION" if is_recovery else "PRIMARY_ACTION",
                            transaction_id=tx, request_ids=request_ids,
                            request_domains={req: sorted(values) for req, values in request_domains.items()},
                            request_types={req: sorted(values) for req, values in request_types.items()},
                            event_ids=[e["event_id"] for e in group]))
    # SCROLL has a separate native exact-request transport observer, not a focus transaction.
    if audit.get("actual_execution_mode") == "CONTROLLED_SCROLL" and audit.get("planner_executed"):
        actions.insert(0, dict(action_id=action_id+":scroll", role="PRIMARY_ACTION",
                              request_ids=[audit.get("helper_request_id")], transaction_id="",
                               request_domains={audit.get("helper_request_id"): ["ACTION_DISPATCH"]},
                               request_types={audit.get("helper_request_id"): [audit.get("scroll_action") or audit.get("planner_action") or "SCROLL_FORWARD"]},
                               action_type=audit.get("scroll_action") or audit.get("planner_action") or "SCROLL_FORWARD",
                              helper_result=deepcopy(audit.get("helper_ack_result")),
                              correlated=audit.get("helper_result_correlated"),
                              source=audit.get("helper_request_source"), event_ids=[]))
    reconciliation = [e for e in events if e["event_type"] == "FOCUS_RECONCILIATION"
                      and str(e["step_index"]) == str(step)]
    recoveries = [e for e in events if e["event_type"] == "RECOVERY_CANDIDATE_RESULT"]
    final_node = deepcopy(row.get("actual_focus_node"))
    final_identity = production_focus_identity(final_node, scenario, row.get('actual_focus_resource_id'))
    final_reconciliation = row.get("focus_reconciliation_evidence") or {}
    if isinstance(final_reconciliation, str):
        final_reconciliation = json.loads(final_reconciliation)
    # Final outcome belongs to a successfully recovered production actor when one exists.
    strong = [e for e in recoveries if e["payload"].get("strong_recovery") is True]
    final = dict(actual_focus=final_node, actual_focus_instance_id=final_identity,
                 production_observed_resource_id=row.get('actual_focus_resource_id'),
                 verification_request_id=row.get("get_focus_req_id") or (final_node or {}).get("reqId"),
                 reconciliation=deepcopy(final_reconciliation),
                 status=row.get("status"), move_result=row.get("move_result"),
                 visit_record_status=row.get("visit_record_status"),
                 focus_transition_status=row.get("focus_transition_status"),
                 actor="RECOVERY_ACTION" if strong else "PRIMARY_ACTION",
                 actor_transaction_id=strong[-1]["transaction_id"] if strong else "",
                 actor_result_event_id=strong[-1]["event_id"] if strong else (reconciliation[-1]["event_id"] if reconciliation else ""))
    primary_request_id = audit.get("helper_request_id")
    primary_action = next((action for action in actions if primary_request_id in action.get("request_ids", [])), None)
    primary_domains = (primary_action or {}).get("request_domains", {}).get(primary_request_id, [])
    primary_domain = primary_domains[0] if len(primary_domains) == 1 else (
        "UNKNOWN" if primary_request_id else "NONE")
    observation_owner = deepcopy(audit.get("fallback_observation_ownership"))
    production_observation_request_id = (audit.get("primary_production_outcome") or {}).get("get_focus_req_id")
    if not production_observation_request_id:
        production_observation_request_id = row.get("get_focus_req_id") or (final_node or {}).get("reqId")
    lineage = None
    if observation_owner is not None:
        primary_result = audit.get("helper_ack_result") or {}
        source_ack_request_id = primary_result.get("reqId") or ""
        if primary_domain == "FOCUS_OBSERVATION":
            source_acknowledged = bool(
                source_ack_request_id == primary_request_id
                and observation_owner.get("status") == "PROVEN"
                and primary_request_id in set(observation_owner.get("acknowledged_request_ids") or [])
            )
        else:
            source_acknowledged = bool(
                source_ack_request_id == primary_request_id
                and audit.get("helper_result_correlated") is True
            )
        lineage = dict(
            source_action_id=primary_action.get("action_id") if primary_action else "",
            source_action_request_id=primary_request_id or "",
            source_request_domain=primary_domain,
            source_ack_request_id=source_ack_request_id,
            source_action_acknowledged=source_acknowledged,
            observation_transaction_id=observation_owner.get("transaction_id") or "",
            observation_request_ids=list(observation_owner.get("request_ids") or []),
            production_observation_request_id=production_observation_request_id or "",
            observation_type=observation_owner.get("observation_type") or "UNKNOWN",
        )
    chain = dict(schema=SCHEMA, step_action_id=action_id,
                owner=dict(run_id=owner[0], scenario_tx_id=owner[1], scenario=scenario, step=step),
                planner=dict(action=audit.get("planner_action"), target=deepcopy(audit.get("planner_target")),
                             gate=deepcopy(audit.get("execution_gate_result")),
                             execution_mode=audit.get("actual_execution_mode"),
                             production_fallback_used=audit.get("fallback_used")),
                primary_request_id=audit.get("helper_request_id"),
                 primary_request_domain=primary_domain,
                primary_helper_result=deepcopy(audit.get("helper_ack_result")),
                original_focus_before=deepcopy(audit.get("actual_focus_before")),
                original_focus_after=deepcopy(audit.get("immediate_actual_focus")),
                primary_reconciliation_event_ids=[e["event_id"] for e in reconciliation],
                primary_production_outcome=deepcopy(audit.get("primary_production_outcome")),
                actions=actions, recovery_result_event_ids=[e["event_id"] for e in recoveries],
                verification_actions=[dict(role="VERIFICATION_ACTION", request_id=final["verification_request_id"],
                                           source="final_production_get_focus", actual_focus=deepcopy(final_node)),
                                      dict(role="VERIFICATION_ACTION", source="primary_production_get_focus",
                                           request_id=(audit.get("primary_production_outcome") or {}).get("get_focus_req_id"),
                                           actual_focus=(audit.get("primary_production_outcome") or {}).get("actual_focus_node"))],
                events=events, final_outcome=final,
                audit_visit_authority=False,
                destination_recovery_ownership=deepcopy(audit.get("dynamic_context")),
                 fallback_observation_ownership=observation_owner,
                 action_to_observation_lineage=lineage)
    if audit.get("action_safety") is not None:
        chain["action_safety"] = dict(step_action_id=action_id, owner=deepcopy(chain["owner"]),
                                    evidence=deepcopy(audit["action_safety"]))
    return chain


def action_chain_failures(chain, audit=None):
    """Verify native request ownership and final actor; never infer visits."""
    reasons = []
    if not isinstance(chain, dict) or chain.get("schema") != SCHEMA:
        return ["AUDIT_CHAIN_MISSING"]
    owner = chain.get("owner") or {}
    scenario, step = owner.get("scenario"), owner.get("step")
    if not owner.get("run_id") or not owner.get("scenario_tx_id") or not scenario or not isinstance(step, int):
        reasons.append("ORPHAN_PRIMARY_ACTION")
    expected_id = json.dumps([SCHEMA, owner.get("run_id"), owner.get("scenario_tx_id"), scenario, step], separators=(",", ":"))
    if chain.get("step_action_id") != expected_id:
        reasons.append("STEP_ACTION_ID_MISMATCH")
    if audit and (audit.get("scenario") != scenario or audit.get("step") != step):
        reasons.append("CROSS_STEP_OR_SCENARIO_EVIDENCE_LEAK")
    if audit and chain.get("destination_recovery_ownership") != audit.get("dynamic_context"):
        reasons.append("DESTINATION_OWNERSHIP_PROVENANCE_MISMATCH")
    safety = chain.get("action_safety")
    if safety is None and audit and audit.get("action_safety") is not None:
        reasons.append("SAFETY_PROVENANCE_MISSING")
    if safety is not None:
        evidence = safety.get("evidence") or {}
        if safety.get("owner") != owner or safety.get("step_action_id") != expected_id or (
                evidence.get("scenario"), evidence.get("step")) != (scenario, step):
            reasons.append("SAFETY_EVIDENCE_OWNERSHIP_MISMATCH")
        if audit and evidence != audit.get("action_safety"):
            reasons.append("SAFETY_PROVENANCE_MISMATCH")
        if evidence.get("mode") == "enforce" and (evidence.get("final_outcome") or {}).get("planner_executed"):
            from tb_runner.safe_action_policy import evaluate_policy
            selected = evidence.get("selected") or {}
            eligible = evaluate_policy(selected.get("classification") or {}, selected.get("conditions") or {}).eligible
            if selected.get("policy", {}).get("eligible") is not True or not eligible:
                reasons.append("SAFETY_BLOCKED_ACTION_EXECUTED")
    events = chain.get("events") or []
    for event in events:
        if (event.get("scenario_id") != scenario or event.get("run_id") != owner.get("run_id")
                or event.get("scenario_tx_id") != owner.get("scenario_tx_id")):
            reasons.append("CROSS_SCENARIO_EVIDENCE_LEAK")
        if not re.fullmatch(re.escape(str(step))+r"(?::recovery:\d+)?", str(event.get("step_index"))):
            reasons.append("CROSS_STEP_EVIDENCE_LEAK")
    by_id = {e.get("event_id"): e for e in events}
    if len(by_id) != len(events) or None in by_id:
        reasons.append("EVIDENCE_EVENT_ID_COLLISION")
    actions = chain.get("actions") or []
    if not actions:
        reasons.append("ORPHAN_PRIMARY_ACTION")
    request_owner = {}
    for action in actions:
        tx = action.get("transaction_id")
        role = action.get("role")
        if not action.get("action_id", "").startswith(expected_id+":"):
            reasons.append("ACTION_OWNER_MISMATCH")
        refs = [by_id.get(ref) for ref in action.get("event_ids", [])]
        if any(e is None or e.get("transaction_id") != tx for e in refs):
            reasons.append("MISMATCHED_REQUEST_OWNERSHIP")
            continue
        if any((":recovery:" in str(e.get('step_index'))) != (role == 'RECOVERY_ACTION') for e in refs):
            reasons.append('MISMATCHED_REQUEST_OWNERSHIP')
        if role == 'RECOVERY_ACTION' and not any(e['event_type'] == 'RECOVERY_CANDIDATE_RESULT' for e in refs):
            reasons.append('ORPHAN_RECOVERY_ACTION')
        for req in action.get("request_ids", []):
            if not req or req in request_owner and request_owner[req] != action['action_id']:
                reasons.append("MISMATCHED_REQUEST_OWNERSHIP")
            request_owner[req] = action['action_id']
            domains = action.get("request_domains") or {}
            if domains and req not in domains:
                reasons.append("MISMATCHED_REQUEST_OWNERSHIP")
            if len(domains.get(req, [])) != 1:
                reasons.append("MISMATCHED_REQUEST_OWNERSHIP")
            request_types = action.get("request_types") or {}
            recorded_types = set(request_types.get(req, []))
            if not tx:
                result = action.get("helper_result") or {}
                if not (domains.get(req) == ["ACTION_DISPATCH"]
                        and len(recorded_types) == 1
                        and _request_domain(next(iter(recorded_types), "")) == "ACTION_DISPATCH"
                        and action.get("source") == "SCROLL_RESULT_EXPLICIT_TRANSPORT_ARGUMENT"
                        and action.get("correlated") is True and result.get("reqId") == req):
                    reasons.append("MISMATCHED_REQUEST_OWNERSHIP")
                continue
            sent = [e for e in refs if e['event_type'] == 'ACTION_SENT' and e['payload'].get('request_id') == req]
            acks = [e for e in refs if e['event_type'] == 'HELPER_ACK_RECEIVED' and e['payload'].get('request_id') == req]
            if not sent or not acks:
                reasons.append("ORPHAN_RECOVERY_ACTION" if role == "RECOVERY_ACTION" else "ORPHAN_PRIMARY_ACTION")
            for ack in acks:
                sent_commands = {str(event["payload"].get("command_type") or "").rsplit(".", 1)[-1].upper()
                                 for event in sent}
                expected_domain = "FOCUS_OBSERVATION" if sent_commands == {"GET_FOCUS"} else (
                    "READ_ONLY_HELPER" if sent_commands and sent_commands.issubset(
                        {"EVIDENCE_EVENTS", "PING", "DUMP_TREE", "DUMP_HIERARCHY"})
                    else "ACTION_DISPATCH")
                normalized_recorded_types = {
                    str(command).rsplit(".", 1)[-1].upper() for command in recorded_types
                }
                if (expected_domain not in domains.get(req, [])
                        or normalized_recorded_types != sent_commands
                        or {_request_domain(command) for command in sent_commands} != {expected_domain}):
                    reasons.append("MISMATCHED_REQUEST_OWNERSHIP")
                result = ack['payload'].get('helper_result') or {}
                correlation = result.get('evidenceCorrelation') or {}
                if result.get('reqId') not in {None, '', req} or correlation and any(
                        correlation.get(k) != v for k,v in dict(run_id=owner['run_id'], scenario_tx_id=owner['scenario_tx_id'], transaction_id=tx).items()):
                    reasons.append("MISMATCHED_REQUEST_OWNERSHIP")
    for event in events:
        if event['event_type'] == 'ACTION_SENT' and event['payload'].get('request_id') not in request_owner:
            reasons.append("ORPHAN_PRIMARY_ACTION")
    observation_owner = chain.get('fallback_observation_ownership')
    if observation_owner is not None:
        owned_tx = observation_owner.get('transaction_id')
        request_ids = observation_owner.get('request_ids') or []
        acknowledged_ids = observation_owner.get('acknowledged_request_ids') or []
        observation_action = next((a for a in actions if a.get('transaction_id') == owned_tx), None)
        observation_events = [e for e in events if e.get('transaction_id') == owned_tx]
        sent_ids = {e['payload'].get('request_id') for e in observation_events if e['event_type'] == 'ACTION_SENT'}
        ack_ids = {e['payload'].get('request_id') for e in observation_events if e['event_type'] == 'HELPER_ACK_RECEIVED'}
        production_request_id = (chain.get("primary_production_outcome") or {}).get("get_focus_req_id")
        if not production_request_id and audit:
            production_request_id = (audit.get("primary_production_outcome") or {}).get("get_focus_req_id")
        if not production_request_id and audit:
            production_request_id = (audit.get("production_row") or {}).get("get_focus_req_id")
        if not production_request_id:
            production_request_id = (chain.get("final_outcome") or {}).get("verification_request_id")
        owner_domains = observation_owner.get("request_domains") or {}
        lineage = chain.get("action_to_observation_lineage") or {}
        source_request = lineage.get("source_action_request_id")
        source_action = next((action for action in actions if action.get("action_id") == lineage.get("source_action_id")), None)
        source_domain = lineage.get("source_request_domain")
        lineage_valid = (
            lineage.get("observation_transaction_id") == owned_tx
            and set(lineage.get("observation_request_ids") or []) == set(request_ids)
            and lineage.get("production_observation_request_id") == production_request_id
            and observation_owner.get("production_request_id") == production_request_id
            and production_request_id in set(request_ids)
            and production_request_id in set(acknowledged_ids)
            and observation_owner.get("request_domain") == "FOCUS_OBSERVATION"
            and observation_owner.get("read_only") is True
            and observation_owner.get("observation_type") in {
                "POST_ACTION", "FALLBACK", "RECOVERY", "READ_ONLY"
            }
        )
        if source_request:
            source_domains = (source_action or {}).get("request_domains", {}).get(source_request, [])
            lineage_valid = lineage_valid and bool(source_action) and source_domain in source_domains
            lineage_valid = lineage_valid and (
                lineage.get("source_action_acknowledged") is True
                and lineage.get("source_ack_request_id") == source_request
            )
            if source_domain == "ACTION_DISPATCH":
                lineage_valid = lineage_valid and source_request not in set(request_ids)
            elif source_domain == "FOCUS_OBSERVATION":
                lineage_valid = lineage_valid and source_request in set(request_ids)
            else:
                lineage_valid = False
        elif source_domain not in {None, "", "NONE"}:
            lineage_valid = False
        if (observation_owner.get('status') != 'PROVEN'
                or audit and audit.get('fallback_observation_ownership') != observation_owner
                or observation_owner.get('step') != step
                or not owned_tx or not request_ids
                or not observation_action
                or not set(request_ids).issubset(set(observation_action.get('request_ids') or []))
                or not set(request_ids).issubset(sent_ids)
                or not set(request_ids).issubset(ack_ids)
                or not set(request_ids).issubset(set(acknowledged_ids))
                or any(owner_domains.get(req) != "FOCUS_OBSERVATION" for req in request_ids)
                or not lineage_valid):
            reasons.append('FALLBACK_OBSERVATION_OWNERSHIP_UNPROVEN')
    primary_domain = chain.get("primary_request_domain")
    if audit and audit.get("planner_executed") is True:
        gate = audit.get("execution_gate_result") or {}
        if audit.get("planner_authorized") is not True or gate.get("allowed") is not True:
            reasons.append("UNAUTHORIZED_PRIMARY_ACTION")
    if chain.get("primary_request_id"):
        primary_action_id = request_owner.get(chain["primary_request_id"])
        primary_action = next((action for action in actions if action.get("action_id") == primary_action_id), None)
        if not primary_action or primary_domain not in (primary_action.get("request_domains") or {}).get(
                chain["primary_request_id"], []):
            reasons.append("MISMATCHED_REQUEST_OWNERSHIP")
    if chain.get('primary_request_id') and chain['primary_request_id'] not in request_owner:
        reasons.append('MISMATCHED_REQUEST_OWNERSHIP')
    primary_result = chain.get('primary_helper_result') or {}
    if chain.get('primary_request_id') and primary_result.get('reqId') != chain['primary_request_id']:
        reasons.append('MISMATCHED_REQUEST_OWNERSHIP')
    for ref in chain.get('primary_reconciliation_event_ids', []):
        event = by_id.get(ref) or {}
        if event.get('event_type') != 'FOCUS_RECONCILIATION' or str(event.get('step_index')) != str(step):
            reasons.append('PRIMARY_RECONCILIATION_MISSING')
    for ref in chain.get('recovery_result_event_ids', []):
        event = by_id.get(ref) or {}
        if event.get('event_type') != 'RECOVERY_CANDIDATE_RESULT' or not any(
                a['role'] == 'RECOVERY_ACTION' and a['transaction_id'] == event.get('transaction_id') for a in actions):
            reasons.append('ORPHAN_RECOVERY_ACTION')
    final = chain.get('final_outcome') or {}
    actual = production_focus_identity(final.get('actual_focus'), scenario, final.get('production_observed_resource_id'))
    if actual != final.get('actual_focus_instance_id'):
        reasons.append('FINAL_FOCUS_IDENTITY_MISMATCH')
    result = by_id.get(final.get('actor_result_event_id')) or {}
    if final.get('actor') == 'RECOVERY_ACTION':
        tx = final.get('actor_transaction_id')
        post = [e for e in events if e['event_type'] == 'POST_FOCUS_OBSERVED' and e.get('transaction_id') == tx and e.get('producer') == 'runner']
        gates = [e for e in events if e['event_type'] == 'PRODUCTION_TRAVERSAL_GATE_DECIDED' and e.get('transaction_id') == tx]
        gate = gates[-1]['payload'] if gates else {}
        p, v = gate.get('progress') or {}, gate.get('visit') or {}
        if (not actual or result.get('event_type') != 'RECOVERY_CANDIDATE_RESULT'
                or result.get('transaction_id') != tx or result.get('payload', {}).get('strong_recovery') is not True
                or not post or focused_identity(observation_node(post[-1]), scenario) != actual
                or observation_node(post[-1]).get('className') != final.get('actual_focus', {}).get('className')
                or not (p.get('gate_applied') is True and p.get('physical_progress') is True
                        and p.get('verdict') == 'MOVE_CONFIRMED' and v.get('visited') is True
                        and p.get('transaction_id') == v.get('transaction_id') == tx)
                or not any(a['role'] == 'RECOVERY_ACTION' and a['transaction_id'] == tx for a in actions)):
            reasons.append('FINAL_RECOVERY_OUTCOME_NOT_PROVEN')
    else:
        if result.get('event_type') != 'FOCUS_RECONCILIATION':
            reasons.append('PRIMARY_RECONCILIATION_MISSING')
        elif result['payload'].get('actual_focus_instance_id', '') != actual:
            reasons.append('FINAL_PRIMARY_RECONCILIATION_MISMATCH')
    if not chain.get('primary_reconciliation_event_ids'):
        reasons.append('PRIMARY_RECONCILIATION_MISSING')
    if chain.get('audit_visit_authority') is not False:
        reasons.append('AUDIT_VISIT_AUTHORITY')
    return sorted(set(reasons))


def chain_gates(chain, audit=None):
    failures = action_chain_failures(chain, audit)
    return {name: int(bool(failures)) if name == GATES[0] else int(any(
        name.removesuffix('_COUNT') in reason for reason in failures)) for name in GATES}


def final_actor_proven(audit):
    chain = audit.get('action_audit_chain')
    if action_chain_failures(chain, audit):
        return False
    ref = (audit.get('production_row') or {}).get('step_action_provenance') or {}
    final = chain['final_outcome']
    return bool(ref.get('step_action_id') == chain['step_action_id'] and ref.get('sha256') == digest(chain)
                and focused_identity(audit.get('actual_focus_after'), audit['scenario']) == final['actual_focus_instance_id'])
