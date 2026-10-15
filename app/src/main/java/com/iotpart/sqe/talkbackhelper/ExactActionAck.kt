package com.iotpart.sqe.talkbackhelper

import org.json.JSONArray
import org.json.JSONObject

internal object ExactActionAck {
    fun create(request:JSONObject, failure:String?, consumed:Boolean=false, consumptionReceipt:String?=null,
        resolved:JSONObject?=null, called:Boolean?=false, returned:Boolean?=null,
        state:ExactActionState=ExactActionState.FAILED_NOT_EXECUTED,
        started:String?=null,finished:String?=null,uptime:Long?=null,
        auditReceipt:String,sequence:Long,exception:String?=null):JSONObject {
        val b=request.getJSONObject("binding");val resolve=request.getJSONObject("resolve_request")
        val target=resolved?.optJSONObject("resolved_target_identity")
        return JSONObject().apply {
            put("protocol_version",ExactActionContract.VERSION);put("ack_schema_version",ExactActionContract.ACK_VERSION)
            for(k in listOf("request_id","transaction_id","permit_id","request_nonce","ownership","authorized_intent_digest",
                "helper_build_id","helper_connection_epoch","boot_epoch","stop_epoch"))put(k,b.get(k))
            put("request_digest",request.getString("request_digest"))
            for(k in listOf("authorized_snapshot_id","reacquire_snapshot_id"))put(k,resolve.get(k))
            put("helper_validation_snapshot_id",resolved?.opt("helper_validation_snapshot_id") ?: JSONObject.NULL)
            put("resolved_target_identity",target ?: JSONObject.NULL)
            put("resolved_source_node_id",resolved?.opt("resolved_source_node_id") ?: JSONObject.NULL)
            put("source_id_provenance",resolved?.opt("resolved_source_node_id_provenance") ?: "NOT_SUPPORTED_BY_SOURCE")
            put("resolved_action_set",resolved?.opt("resolved_action_set") ?: JSONObject.NULL)
            put("candidate_count",resolved?.optInt("candidate_count",0) ?: 0)
            put("pre_dispatch_gate_verdict",if(consumed)"APPROVED" else "REJECTED")
            put("gate_evidence_refs",JSONArray().put(auditReceipt))
            put("permit_consumed",consumed);put("consumption_receipt_id",consumptionReceipt ?: JSONObject.NULL)
            put("dispatch_started_at",started ?: JSONObject.NULL);put("dispatch_finished_at",finished ?: JSONObject.NULL)
            put("dispatch_uptime_ms",uptime ?: JSONObject.NULL);put("producer_sequence",sequence)
            put("perform_action_called",called ?: JSONObject.NULL);put("perform_action_type",if(called==true)16 else JSONObject.NULL)
            put("perform_action_call_count",if(called==null)JSONObject.NULL else if(called)1 else 0)
            put("perform_action_return",returned ?: JSONObject.NULL);put("exception_detail",exception ?: JSONObject.NULL)
            put("framework_event_correlation_window",JSONObject.NULL);put("post_action_probe_id",JSONObject.NULL)
            put("failure_code",failure ?: JSONObject.NULL);put("failure_detail",JSONObject.NULL)
            put("audit_receipt_id",auditReceipt);put("execution_state",state.name)
            put("visit_authority",false);put("action_effect_confirmed",false);put("expected_navigation_confirmed",false)
        }
    }
}
