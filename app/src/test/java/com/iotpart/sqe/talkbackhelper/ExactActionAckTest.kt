package com.iotpart.sqe.talkbackhelper

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import java.io.File
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
class ExactActionAckTest {
    @Test fun kotlinActionAckSchemaExportsWithoutCallingAnyAction() {
        var root=File(".").canonicalFile
        while(!File(root,"settings.gradle.kts").exists())root=root.parentFile ?: error("root")
        val request=ExactActionContractTest().fixture().getJSONObject("request")
        val output=JSONArray()
        val rejected=ExactActionAck.create(request,"ACTION_GATE_DISABLED",auditReceipt="audit:synthetic",sequence=1)
        val unknown=ExactActionAck.create(request,"UNKNOWN_EXECUTION_STATE",consumed=true,consumptionReceipt="claim:synthetic",
            called=null,state=ExactActionState.UNKNOWN_EXECUTION_STATE,auditReceipt="audit:synthetic",sequence=2)
        for(ack in listOf(rejected,unknown)) {
            assertFalse(ack.getBoolean("visit_authority"));assertFalse(ack.getBoolean("action_effect_confirmed"))
            output.put(JSONObject().put("request",request).put("ack",ack))
        }
        File(root,"app/build/reports/exact-protocol/action-acks.json").apply { parentFile.mkdirs();writeText(output.toString(2)) }
    }
    @Test fun receiptReadbackNeverClaimsRetriesOrClearsStop() {
        val s=ExactActionStore(RuntimeEnvironment.getApplication(),"test-${UUID.randomUUID()}.db")
        s.connect("boot:test");val request=ExactActionTestData.request(s)
        s.register(request);s.approve(request,ExactActionContract.checks.associateWith{true});s.claim(request,System.currentTimeMillis());s.stop("test")
        val result=s.readback(request)
        assertEquals("UNKNOWN_EXECUTION_STATE",result.getString("status"))
        assertTrue(result.getBoolean("permit_consumed"));assertFalse(result.getBoolean("action_request_resent"))
        assertEquals("true",s.metadata("stopped"))
        var root=File(".").canonicalFile
        while(!File(root,"settings.gradle.kts").exists())root=root.parentFile ?: error("root")
        File(root,"app/build/reports/exact-protocol/unknown-receipt.json").apply {
            parentFile.mkdirs();writeText(JSONObject().put("request",request).put("response",
                JSONObject().put("reqId","readback:synthetic").put("receipt",result)).toString(2))
        }
        val wrong=JSONObject(request.toString()).apply { put("request_digest","wrong") }
        assertThrows(ExactActionRejected::class.java){s.readback(wrong)};s.close()
    }
}
