package com.iotpart.sqe.talkbackhelper

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

@RunWith(RobolectricTestRunner::class)
class ExactActionContractTest {
    internal fun fixture(): JSONObject {
        var root = File(".").canonicalFile
        while (!File(root,"settings.gradle.kts").exists()) root = root.parentFile ?: error("root")
        return JSONObject(File(root,"tests/fixtures/exact_protocol/action.json").readText())
    }
    internal fun session(request: JSONObject,identityStatus:String="MATCH"): ExactActionSession {
        val b = request.getJSONObject("binding")
        return ExactActionSession(ByteArray(32) { it.toByte() }, b.getString("host_session_id"),b.getString("expected_package"),
            b.getString("app_version"),b.getString("helper_build_id"),b.getString("boot_epoch"),
            b.getString("helper_connection_epoch"),b.getString("stop_epoch"),setOf(b.getString("authorized_intent_digest")),
            setOf(b.getString("target_identity_digest")),setOf(b.getString("transaction_id")),identityStatus)
    }
    @Test fun pythonAuthenticatedPermitVerifiesInKotlinAndTamperingFails() {
        val f = fixture(); val r = f.getJSONObject("request"); val session = session(r)
        session.verify(r,f.getLong("now_ms"))
        for(status in listOf("UNKNOWN","MISMATCH"))assertThrows(ExactActionRejected::class.java){
            session(r,status).verify(r,f.getLong("now_ms"))
        }
        val changed = JSONObject(r.toString()).apply { put("permit_mac","0".repeat(64)) }
        changed.put("request_digest",ExactActionContract.digestWithoutSelf(changed))
        assertThrows(ExactActionRejected::class.java) { session.verify(changed,f.getLong("now_ms")) }
        assertThrows(ExactActionRejected::class.java) { session.verify(r,f.getLong("now_ms")+3000) }
        r.getJSONObject("binding").put("stop_epoch","stale")
        assertThrows(ExactActionRejected::class.java) { session.verify(r,f.getLong("now_ms")) }
    }
    @Test fun gateRejectsEveryMissingUnknownOrFalseCondition() {
        val facts = ExactActionContract.checks.associateWith { true as Any? }.toMutableMap()
        assertTrue(ExactActionContract.failures(facts).isEmpty())
        ExactActionContract.checks.forEach { key ->
            listOf(null,false,1,"true").forEach { value ->
                facts[key] = value; assertTrue(ExactActionContract.failures(facts).contains(key))
            }
            facts[key] = true
        }
    }
    @Test fun transitionsAndEpochStopAreMonotonic() {
        assertFalse(ExactActionState.CONSUMED.permits(ExactActionState.ISSUED))
        assertTrue(ExactActionState.DISPATCH_STARTED.permits(ExactActionState.CONSUMED))
        assertTrue(ExactActionState.CONSUMED.permits(ExactActionState.UNKNOWN_EXECUTION_STATE))
        assertFalse(ExactActionState.ACKED.permits(ExactActionState.DISPATCH_STARTED))
        val latch=ExactActionStopLatch();val old=latch.connectionEpoch;latch.reconnect()
        assertNotEquals(old,latch.connectionEpoch)
        val epoch=latch.stopEpoch;latch.stop();assertTrue(latch.stopped);assertNotEquals(epoch,latch.stopEpoch)
        val stoppedEpoch=latch.stopEpoch;latch.stop();assertEquals(stoppedEpoch,latch.stopEpoch)
    }
    @Test fun monotonicSessionExpiryRejectsEvenWithAnOldWallClockValue() {
        val f=fixture();val r=f.getJSONObject("request");val trusted=session(r)
        org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(6))
        assertThrows(ExactActionRejected::class.java){trusted.verify(r,f.getLong("now_ms"))}
    }
}
