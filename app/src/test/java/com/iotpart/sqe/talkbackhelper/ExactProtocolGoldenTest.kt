package com.iotpart.sqe.talkbackhelper

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

@RunWith(RobolectricTestRunner::class)
class ExactProtocolGoldenTest {
    @Test fun malformedRequestsExportRegisteredErrorDetails() {
        var root=File(".").canonicalFile
        while(!File(root,"settings.gradle.kts").exists())root=root.parentFile ?: error("root")
        val output=JSONArray()
        for(raw in listOf("{","{\"request_id\":\"one\",\"request_id\":\"two\"}")) {
            val ack=ExactNodeResolver.resolve(raw,JSONObject(),helperServiceInstanceId="helper:golden")
            assertEquals("REQUEST_INVALID",ack.getString("failure_code"))
            assertTrue(ack.has("validation_detail"));output.put(ExactProtocolJson.canonical(ack))
        }
        output.put(ExactProtocolJson.canonical(ExactNodeResolver.invalidRequestAck("golden:error","HELPER_REACQUIRE_FAILED")
            .put("failure_detail","synthetic_exception")))
        File(root,"app/build/reports/exact-protocol/error-acks.json").apply {parentFile.mkdirs();writeText(output.toString(2))}
    }
    @Test fun pythonWireBytesAreAcceptedAndKotlinAcksAreExported() {
        var root = File(".").canonicalFile
        while (!File(root, "settings.gradle.kts").exists()) root = root.parentFile ?: error("repo root")
        val fixture = JSONObject(File(root, "tests/fixtures/exact_protocol/golden.json").readText())
        val values = fixture.getJSONArray("values")
        for (i in 0 until values.length()) {
            val v = values.getJSONObject(i)
            assertEquals(v.getString("canonical"), ExactProtocolJson.canonical(v.get("value")))
            assertEquals(v.getString("digest"), ExactProtocolJson.hash(v.get("value")))
        }
        val output = JSONArray()
        val cases = fixture.getJSONArray("cases")
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val request = JSONObject(case.getString("wire"))
            assertEquals(case.getString("wire"), ExactProtocolJson.canonical(request))
            val body = JSONObject(request.toString()).apply { remove("request_digest") }
            assertEquals(case.getString("digest"), ExactProtocolJson.hash(body))
            val ack = ExactNodeResolver.resolve(case.getString("wire"), case.getJSONObject("hierarchy"),
                helperServiceInstanceId = "helper:golden")
            assertEquals(case.getBoolean("expected_resolved"), ack.getBoolean("resolved"))
            output.put(JSONObject().put("name",case.getString("name"))
                .put("canonical",ExactProtocolJson.canonical(request)).put("digest",ExactProtocolJson.hash(body))
                .put("ack_wire",ExactProtocolJson.canonical(ack)))
        }
        File(root,"app/build/reports/exact-protocol/acks.json").apply { parentFile.mkdirs();writeText(output.toString(2)) }
    }
}
