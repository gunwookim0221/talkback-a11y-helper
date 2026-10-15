package com.iotpart.sqe.talkbackhelper

import android.database.sqlite.SQLiteException
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import java.util.UUID
import java.util.concurrent.Executors

internal object ExactActionTestData {
    fun request(store:ExactActionStore):JSONObject {
        val r=JSONObject(ExactActionContractTest().fixture().getJSONObject("request").toString())
        val b=r.getJSONObject("binding");val resolve=r.getJSONObject("resolve_request")
        for(k in listOf("request_id","transaction_id","permit_id","request_nonce")) {
            val value=UUID.randomUUID().toString();b.put(k,value);resolve.put(k,value)
        }
        val connection=store.metadata("connection_epoch")!!;val stop=store.metadata("stop_epoch")!!
        resolve.put("helper_service_instance_id",connection).put("stop_epoch",stop)
        resolve.put("request_digest",ExactActionContract.digestWithoutSelf(resolve))
        b.put("resolve_request_digest",resolve.getString("request_digest"))
            .put("helper_connection_epoch",connection).put("stop_epoch",stop).put("boot_epoch",store.metadata("boot_epoch"))
            .put("issued_at_ms",System.currentTimeMillis()-1).put("expires_at_ms",System.currentTimeMillis()+4000)
        r.put("permit_mac",ExactActionContractTest().session(r).mac(b))
        r.put("request_digest",ExactActionContract.digestWithoutSelf(r))
        return r
    }
}

@RunWith(RobolectricTestRunner::class)
class ExactActionStoreTest {
    private val context get()=RuntimeEnvironment.getApplication()
    @Test fun claimsAndStopSurviveRestartAndReceiptLookupDoesNotReactivate() {
        val name="test-${UUID.randomUUID()}.db"
        var s=ExactActionStore(context,name);val old=s.connect("boot:test")
        val r=ExactActionTestData.request(s);s.register(r);s.approve(r,ExactActionContract.checks.associateWith{true});val id=r.getJSONObject("binding").getString("request_id")
        val receipt=s.claim(r,System.currentTimeMillis());assertTrue(receipt.isNotBlank());s.stop("test");s.close()
        s=ExactActionStore(context,name);assertNotEquals(old,s.connect("boot:test"))
        assertTrue(s.claimed(id));assertNull(s.receipt(id));assertEquals("true",s.metadata("stopped"))
        assertThrows(Exception::class.java){s.register(r)}
        assertThrows(Exception::class.java){s.claim(r,System.currentTimeMillis())}
        assertNull(s.receipt(id));s.close()
    }
    @Test fun failedDurableClaimRollsBackAndNoFakeCallIsPossible() {
        var fail=false
        val s=ExactActionStore(context,"test-${UUID.randomUUID()}.db") { type ->
            if(fail && type=="DISPATCH_STARTED")throw SQLiteException("simulated disk full")
        }
        s.connect("boot:test");val r=ExactActionTestData.request(s);s.register(r);s.approve(r,ExactActionContract.checks.associateWith{true});fail=true
        var calls=0
        assertThrows(Exception::class.java){s.claim(r,System.currentTimeMillis());calls++}
        assertEquals(0,calls);assertFalse(s.claimed(r.getJSONObject("binding").getString("request_id")));s.close()
    }
    @Test fun simultaneousClaimsAllowOnlyOneAndReceiptsAreIntegrityChecked() {
        val s=ExactActionStore(context,"test-${UUID.randomUUID()}.db");s.connect("boot:test")
        val r=ExactActionTestData.request(s);s.register(r);s.approve(r,ExactActionContract.checks.associateWith{true})
        val pool=Executors.newFixedThreadPool(6)
        try {
            val results=(0..8).map { pool.submit<Boolean>{runCatching{s.claim(r,System.currentTimeMillis())}.isSuccess} }
            assertEquals(1,results.count{it.get()})
        } finally {pool.shutdownNow()}
        val id=r.getJSONObject("binding").getString("request_id")
        s.storeReceipt(id,JSONObject().put("test","receipt"));assertEquals("receipt",s.receipt(id)!!.getString("test"))
        s.writableDatabase.execSQL("UPDATE receipts SET hash='corrupt' WHERE request_id=?",arrayOf(id))
        assertThrows(ExactActionRejected::class.java){s.receipt(id)};s.close()
    }
    @Test fun everyIdentifierIsUniqueAndCompetingTransactionsCannotClaim() {
        val s=ExactActionStore(context,"test-${UUID.randomUUID()}.db");s.connect("boot:test")
        val original=ExactActionTestData.request(s);s.register(original)
        for(key in listOf("request_id","request_nonce","permit_id","transaction_id")) {
            val other=ExactActionTestData.request(s)
            other.getJSONObject("binding").put(key,original.getJSONObject("binding").get(key))
            assertThrows(Exception::class.java){s.register(other)}
        }
        s.approve(original,ExactActionContract.checks.associateWith{true});s.claim(original,System.currentTimeMillis())
        val competitor=ExactActionTestData.request(s);s.register(competitor);s.approve(competitor,ExactActionContract.checks.associateWith{true})
        assertThrows(Exception::class.java){s.claim(competitor,System.currentTimeMillis())};s.close()
    }
    @Test fun corruptJournalAndMissingApprovalFailClosed() {
        val s=ExactActionStore(context,"test-${UUID.randomUUID()}.db");s.connect("boot:test")
        val r=ExactActionTestData.request(s);s.register(r)
        assertThrows(Exception::class.java){s.claim(r,System.currentTimeMillis())}
        s.writableDatabase.execSQL("UPDATE journal SET payload='corrupt' WHERE sequence=1")
        assertThrows(Exception::class.java){s.connect("boot:test")};s.close()
    }
    @Test fun receiptAndUnverifiedEffectStopAreAtomicAcrossRestart() {
        val name="test-${UUID.randomUUID()}.db"
        var s=ExactActionStore(context,name);s.connect("boot:test")
        val request=ExactActionTestData.request(s);s.register(request);s.approve(request,ExactActionContract.checks.associateWith{true})
        s.claim(request,System.currentTimeMillis())
        val id=request.getJSONObject("binding").getString("request_id")
        s.storeReceipt(id,JSONObject().put("synthetic_result",true))
        assertTrue(s.stopped());s.close() // No subsequent engine stop() is needed for safety.
        s=ExactActionStore(context,name);s.connect("boot:test")
        assertTrue(s.stopped());assertTrue(s.receipt(id)!!.getBoolean("synthetic_result"))
        s.readableDatabase.rawQuery("SELECT payload FROM journal WHERE request_id=? AND event_type='CONSUMED'",arrayOf(id)).use {
            assertTrue(it.moveToFirst());val event=JSONObject(it.getString(0))
            assertEquals(request.getJSONObject("binding").getString("transaction_id"),event.getString("transaction_id"))
            assertEquals(request.getJSONObject("binding").getString("permit_id"),event.getString("permit_id"))
        }
        s.close()
    }
}
