package com.iotpart.sqe.talkbackhelper

import android.accessibilityservice.AccessibilityServiceInfo
import android.view.accessibility.AccessibilityEvent
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
class ExactPostActionTest {
    private fun root():File {var p=File(".").canonicalFile;while(!File(p,"settings.gradle.kts").exists())p=p.parentFile;return p}
    private fun shared()=JSONObject(File(root(),"tests/fixtures/exact_protocol/post_action.json").readText())
    private class Rig(val store:ExactActionStore,val request:JSONObject,val collector:ExactPostActionCollector,var time:Long=90)
    private fun rig(fail:(String)->Unit={}):Rig {
        val s=ExactActionStore(RuntimeEnvironment.getApplication(),"test-${UUID.randomUUID()}.db",fail);s.connect("boot:test")
        val r=ExactActionTestData.request(s)
        val contract=shared().getJSONArray("helper_export").getJSONObject(1).getJSONObject("record").getJSONObject("payload").getJSONObject("destination_contract")
        val b=r.getJSONObject("binding");val intent=b.getJSONObject("semantic_intent")
        intent.put("destination_contract_digest",ExactProtocolJson.hash(contract))
        b.put("authorized_intent_digest",ExactProtocolJson.hash(intent))
        r.put("permit_mac",ExactActionContractTest().session(r).mac(b));r.put("request_digest",ExactActionContract.digestWithoutSelf(r))
        lateinit var result:Rig
        val c=ExactPostActionCollector(s,{result.time},{123456L});result=Rig(s,r,c)
        s.register(r);c.arm(r,"probe:synthetic",contract,JSONObject().put("security:status","unchanged"))
        return result
    }
    private fun raw(time:Long=110)=JSONObject().put("event_type",1).put("event_uptime_ms",time).put("package","com.example.smartthings")
        .put("window_id",7).put("source_identity",JSONObject.NULL).put("text",JSONArray().put("Open"))

    @Test fun cursorArmedDurablyBeforeConsumptionAndRawPreservedBeforeDerived() {
        val r=rig();val s=r.store;val request=r.request
        s.approve(request,ExactActionContract.checks.associateWith{true});val receipt=s.claim(request,System.currentTimeMillis())
        assertTrue(receipt.isNotBlank());r.time=120
        val raw=raw();assertTrue(r.collector.accept(raw));raw.put("text","MUTATED")
        val rows=s.exportJournal();val types=(0 until rows.length()).map{rows.getJSONObject(it).getJSONObject("record").getString("event_type")}
        assertTrue(types.indexOf("C5_CURSOR_ARMED")<types.indexOf("DISPATCH_STARTED"))
        assertTrue(types.indexOf("C5_RAW_EVENT")<types.indexOf("C5_NORMALIZED_EVENT"))
        val saved=(0 until rows.length()).map{rows.getJSONObject(it).getJSONObject("record")}.single{it.getString("event_type")=="C5_RAW_EVENT"}.getJSONObject("payload")
        assertEquals("Open",saved.getJSONArray("text").getString(0))
        assertEquals(request.getJSONObject("binding").getString("request_id"),saved.getString("request_id"))
        assertFalse(r.collector.status().getBoolean("post_action_verifier_ready"));s.close()
    }
    @Test fun finiteWindowDoesNotExtendAndLateEventsCannotReopen() {
        val r=rig();assertEquals(6090L,r.collector.closeDeadline())
        assertThrows(IllegalArgumentException::class.java){r.collector.close(6089)}
        r.time=5090;assertTrue(r.collector.accept(raw(5090)))
        r.time=5091;assertFalse(r.collector.active()) // Grace admits old delivery, never a new dispatch.
        r.time=6090;assertTrue(r.collector.close());assertFalse(r.collector.active())
        r.time=6100;assertFalse(r.collector.accept(raw(5090)))
        assertFalse(r.collector.close());assertEquals(6090L,r.collector.closeDeadline())
        val rows=r.store.exportJournal();val records=(0 until rows.length()).map{rows.getJSONObject(it).getJSONObject("record")}
        assertEquals(1,records.count{it.getString("event_type")=="C5_COLLECTION_CLOSED"})
        assertEquals(2,records.count{it.getString("event_type")=="C5_RAW_EVENT"})
        assertTrue(records.last{it.getString("event_type")=="C5_RAW_EVENT"}.getJSONObject("payload").getBoolean("late_evidence"));r.store.close()
    }
    @Test fun auditFailurePoisonsObserverAndStopsFutureAction() {
        var fail=false
        val r=rig{if(fail && it=="C5_RAW_EVENT")error("DISK_FULL")};fail=true;r.time=120
        assertThrows(IllegalStateException::class.java){r.collector.accept(raw())}
        assertFalse(r.collector.active());assertTrue(r.store.stopped());r.store.close()
    }
    @Test fun restartCannotResumeAndOldEpochCannotArm() {
        val r=rig();r.collector.interrupt("SERVICE_RESTARTED");assertFalse(r.collector.active())
        r.store.connect("boot:test")
        val c=ExactPostActionCollector(r.store,{100L})
        val contract=shared().getJSONArray("helper_export").getJSONObject(1).getJSONObject("record").getJSONObject("payload").getJSONObject("destination_contract")
        assertThrows(IllegalArgumentException::class.java){c.arm(r.request,"new",contract,JSONObject())}
        assertFalse(c.active());r.store.close()
    }
    @Test fun normalizationDoesNotFabricateSourceAndRetainsRawDuplicates() {
        val a=ExactPostActionContract.normalize(raw());val b=ExactPostActionContract.normalize(raw())
        assertTrue(a.isNull("source_identity"));assertEquals(a.toString(),b.toString())
        assertEquals(1,a.getInt("event_type"));assertEquals("Open",a.getJSONArray("text").getString(0))
    }
    @Test fun identicalPlatformCallbacksRemainSeparateDurableRawEvidence() {
        val r=rig();r.time=120
        val event=raw(110)
        assertTrue(r.collector.accept(event));assertTrue(r.collector.accept(event))
        r.time=6090;assertTrue(r.collector.close())
        val rows=r.store.exportJournal()
        val rawRows=(0 until rows.length()).map{rows.getJSONObject(it).getJSONObject("record")}
            .filter{it.getString("event_type")=="C5_RAW_EVENT"}
        val normalized=(0 until rows.length()).map{rows.getJSONObject(it).getJSONObject("record")}
            .filter{it.getString("event_type")=="C5_NORMALIZED_EVENT"}
        assertEquals(2,rawRows.size);assertEquals(2,normalized.size)
        assertNotEquals(rawRows[0].getInt("producer_sequence"),rawRows[1].getInt("producer_sequence"))
        assertEquals(normalized[0].getJSONObject("payload").getString("fingerprint"),
            normalized[1].getJSONObject("payload").getString("fingerprint"))
        assertTrue((0 until rows.length()).map{rows.getJSONObject(it).getJSONObject("record")}
            .none{it.getString("event_type")=="DISPATCH_STARTED"})
        assertFalse(r.collector.status().getBoolean("visit_authority"));r.store.close()
    }
    @Test fun configuredEventsCoverMinimalRequiredTypes() {
        val context=RuntimeEnvironment.getApplication()
        val info=AccessibilityServiceInfo()
        // Read the actual bundled XML, not a duplicated test constant.
        val parser=context.resources.getXml(R.xml.a11y_service_config)
        while(parser.eventType!=org.xmlpull.v1.XmlPullParser.START_TAG)parser.next()
        val attrs=android.util.Xml.asAttributeSet(parser)
        val typed=context.obtainStyledAttributes(attrs,intArrayOf(android.R.attr.accessibilityEventTypes))
        val configured=typed.getInt(0,0);typed.recycle();parser.close()
        assertTrue(ExactPostActionContract.eventTypes.all{configured and it != 0})
        info.eventTypes=configured
        val facts=listOf("service_connected","listener_active","producer_sequence_available","cursor_registered",
            "persistent_audit_writable","no_competing_transaction","connection_epoch_current","destination_contract_approved","forbidden_contract_observable").associateWith{true}
        assertTrue(ExactPostActionContract.ready(facts,ExactPostActionContract.eventTypes))
        for(k in facts.keys)assertFalse(ExactPostActionContract.ready(facts+(k to false),ExactPostActionContract.eventTypes))
        assertFalse(ExactPostActionContract.ready(facts,ExactPostActionContract.eventTypes-2048))
    }
    private fun hierarchy():JSONObject {
        val child=JSONObject().put("viewIdResourceName","security:status").put("className","android.widget.TextView")
            .put("text","unchanged").put("visibleToUser",true).put("enabled",true).put("children",JSONArray())
        val root=JSONObject().put("packageName","com.example.smartthings").put("viewIdResourceName","root")
            .put("className","android.widget.FrameLayout").put("children",JSONArray().put(child))
        return JSONObject().put("windows",JSONArray().put(JSONObject().put("id",7).put("type",1).put("active",true).put("root",root)))
    }
    @Test fun structuralReadOnlyProbeRetainsRawAndRequiresUniqueSecuritySelector() {
        val h=hierarchy();val p=ExactStructuralProbe.build(h,listOf("security:status","missing"))
        assertTrue(p.getBoolean("read_succeeded"));assertEquals("com.example.smartthings",p.getString("package"))
        assertFalse(p.getJSONObject("security_state").isNull("security:status"));assertTrue(p.getJSONObject("security_state").isNull("missing"))
        assertEquals(2,p.getJSONArray("structures").length());assertTrue(p.has("raw_hierarchy"))
        val children=h.getJSONArray("windows").getJSONObject(0).getJSONObject("root").getJSONArray("children");children.put(children.getJSONObject(0))
        assertTrue(ExactStructuralProbe.build(h,listOf("security:status")).getJSONObject("security_state").isNull("security:status"))
        val r=rig();r.time=200;val first=r.collector.probe(hierarchy(),"example.Destination","destination","NONE",listOf("security:status"))
        assertEquals(1L,first.getLong("observation_sequence"));assertEquals("probe:synthetic",first.getString("post_action_probe_id"))
        assertThrows(IllegalArgumentException::class.java){r.collector.probe(hierarchy(),null,null,null,emptyList())}
        r.time=400;r.collector.probe(hierarchy(),"example.Destination","destination","NONE",listOf("security:status"));r.store.close()
    }
    @Test fun sharedPythonFixtureCanonicalizationAndJournalInteroperability() {
        val fixture=shared();val exported=fixture.getJSONArray("helper_export")
        var previous="0".repeat(64)
        for(i in 0 until exported.length()) {
            val row=exported.getJSONObject(i);val record=row.getJSONObject("record")
            assertEquals(previous,record.getString("previous_hash"));assertEquals(i+1,record.getInt("producer_sequence"))
            assertEquals(row.getString("hash"),ExactProtocolJson.hash(record));previous=row.getString("hash")
        }
        // Actual SQLite writer + exporter output, consumed by Python verification after JVM tests.
        val r=rig();r.time=120;r.collector.accept(raw());r.time=6090;r.collector.close()
        File(root(),"app/build/reports/exact-protocol/post-action-export.json").apply {
            parentFile.mkdirs();writeText(JSONObject().put("evidence_type","SYNTHETIC_NO_DISPATCH")
                .put("request",r.request).put("helper_export",r.store.exportJournal()).toString(2))
        };r.store.close()
    }
}
