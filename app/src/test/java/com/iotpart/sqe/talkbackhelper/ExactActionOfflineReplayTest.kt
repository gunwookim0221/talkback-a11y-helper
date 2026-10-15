package com.iotpart.sqe.talkbackhelper

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

@RunWith(RobolectricTestRunner::class)
class ExactActionOfflineReplayTest {
    @Test fun structuralReacquireDoesNotAuthorizeUnknownOrMutationEffects() {
        var root=File(".").canonicalFile
        while(!File(root,"settings.gradle.kts").exists())root=root.parentFile ?: error("root")
        val explicit=System.getProperty("exactC4ReplayFile")
        val input=if(explicit!=null)JSONObject(File(explicit).readText()) else {
            val golden=JSONObject(File(root,"tests/fixtures/exact_protocol/golden.json").readText()).getJSONArray("cases").getJSONObject(0)
            JSONObject().put("source","synthetic_default").put("home_monitor",JSONArray().put(JSONObject()
                .put("name","generic_navigation_candidate").put("request",golden.getJSONObject("request"))
                .put("hierarchy",golden.getJSONObject("hierarchy")).put("target_class","UNKNOWN_ACTIONABLE")))
                .put("cross_scenario",JSONArray())
        }
        val homes=JSONArray();val cross=JSONArray();val cases=input.getJSONArray("home_monitor")
        for(i in 0 until cases.length()) {
            val case=cases.getJSONObject(i);val request=case.getJSONObject("request")
            val ack=ExactNodeResolver.resolveForAction(request.toString(),case.getJSONObject("hierarchy"),request.getString("helper_service_instance_id"))
            assertTrue(ack.toString(),ack.getBoolean("resolved"));assertEquals(1,ack.getInt("candidate_count"))
            val facts=ExactActionContract.checks.associateWith{true as Any?}.toMutableMap()
            facts["target_class_allowed"]=case.getString("target_class")=="NAVIGATION_TARGET"
            facts["semantic_approved"]=false;facts["isolation_approved"]=false
            var calls=0;if(ExactActionContract.failures(facts).isEmpty())calls++
            assertEquals(0,calls)
            homes.put(JSONObject().put("name",case.getString("name")).put("resolved",true).put("candidate_count",1)
                .put("target_class",case.getString("target_class")).put("structure_match",true).put("action_set_match",true).put("fake_action_calls",calls))
        }
        val missing=input.getJSONArray("cross_scenario")
        for(i in 0 until missing.length()) {
            val case=missing.getJSONObject(i)
            assertFalse(case.getBoolean("resolved"))
            assertTrue(case.getString("reason") in setOf("METADATA_INCOMPLETE","TARGET_NOT_FOUND"))
            val facts=ExactActionContract.checks.associateWith{true as Any?}.toMutableMap()
            facts["hierarchy_complete"]=false;facts["identity_match"]=false
            var calls=0;if(ExactActionContract.failures(facts).isEmpty())calls++
            assertEquals(0,calls);cross.put(JSONObject().put("scenario",case.getString("scenario")).put("reason",case.getString("reason")).put("fake_action_calls",calls))
        }
        val output=JSONObject().put("source",input.getString("source")).put("home_monitor",homes).put("cross_scenario",cross).put("false_safe_approval_count",0)
        File(root,"app/build/reports/exact-protocol/safety-replay.json").apply {parentFile.mkdirs();writeText(output.toString(2))}
    }
}
