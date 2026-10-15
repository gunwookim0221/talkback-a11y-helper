package com.iotpart.sqe.talkbackhelper

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject
import java.util.UUID

/** Private durable safety journal. No public reset, deletion, or action dependency. */
internal class ExactActionStore(context: Context, name: String = "exact-action-v2.db",
    private val beforeWrite: (String)->Unit = {}) : SQLiteOpenHelper(context,name,null,1) {
    val executionLock = Any()
    val busy = java.util.concurrent.atomic.AtomicBoolean(false)
    @Volatile private var localStopped=false
    fun stopped():Boolean = localStopped || metadata("stopped")!="false"
    override fun onConfigure(db: SQLiteDatabase) { db.execSQL("PRAGMA synchronous=FULL"); db.setForeignKeyConstraintsEnabled(true) }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execSQL("CREATE TABLE requests (request_id TEXT PRIMARY KEY, permit_id TEXT NOT NULL UNIQUE, nonce TEXT NOT NULL UNIQUE, transaction_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL, payload TEXT NOT NULL)")
        db.execSQL("CREATE TABLE claims (permit_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, nonce TEXT NOT NULL UNIQUE, transaction_id TEXT NOT NULL UNIQUE, receipt_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL)")
        db.execSQL("CREATE TABLE active_channel (scope TEXT PRIMARY KEY, request_id TEXT NOT NULL)")
        db.execSQL("CREATE TABLE journal (sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, request_id TEXT, event_type TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL)")
        db.execSQL("CREATE TABLE receipts (request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, hash TEXT NOT NULL)")
        for ((key,value) in mapOf("stopped" to "false","stop_epoch" to UUID.randomUUID().toString())) put(db,key,value)
    }
    override fun onUpgrade(db: SQLiteDatabase,oldVersion:Int,newVersion:Int) { error("UNSUPPORTED_ACTION_STORE_VERSION") }

    private fun put(db:SQLiteDatabase,key:String,value:String) { db.execSQL("INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)",arrayOf(key,value)) }
    private fun get(db:SQLiteDatabase,key:String):String? = db.rawQuery("SELECT value FROM metadata WHERE key=?",arrayOf(key)).use { if(it.moveToFirst())it.getString(0) else null }
    fun metadata(key:String):String? = synchronized(executionLock) { get(readableDatabase,key) }

    private fun <T> transaction(block:(SQLiteDatabase)->T):T {
        val db=writableDatabase;db.beginTransaction()
        try { val result=block(db);db.setTransactionSuccessful();return result } finally { db.endTransaction() }
    }

    private fun append(db:SQLiteDatabase,type:String,requestId:String?,payload:JSONObject):String {
        beforeWrite(type)
        val previous=db.rawQuery("SELECT hash FROM journal ORDER BY sequence DESC LIMIT 1",null).use { if(it.moveToFirst())it.getString(0) else "0".repeat(64) }
        val eventId=UUID.randomUUID().toString()
        val sequence=db.rawQuery("SELECT COALESCE(MAX(sequence),0)+1 FROM journal",null).use { it.moveToFirst();it.getLong(0) }
        val binding=if(requestId==null)null else db.rawQuery("SELECT payload FROM requests WHERE request_id=?",arrayOf(requestId)).use {
            if(it.moveToFirst())JSONObject(it.getString(0)).getJSONObject("binding") else null
        }
        val record=JSONObject().put("event_id",eventId).put("event_type",type).put("request_id",requestId ?: JSONObject.NULL)
            .put("producer_sequence",sequence).put("timestamp_ms",System.currentTimeMillis()).put("payload",payload).put("previous_hash",previous)
        for(key in listOf("transaction_id","permit_id","request_nonce","ownership","host_session_id"))record.put(key,binding?.opt(key) ?: JSONObject.NULL)
        record.put("producer_connection_epoch",get(db,"connection_epoch") ?: JSONObject.NULL)
            .put("boot_epoch",get(db,"boot_epoch") ?: "UNKNOWN").put("stop_epoch",get(db,"stop_epoch") ?: JSONObject.NULL)
            .put("ownership_status",if(binding==null)"UNATTRIBUTED" else "REGISTERED_REQUEST")
            .put("failure_code",payload.opt("failure_code") ?: JSONObject.NULL)
        val wire=ExactProtocolJson.canonical(record);val hash=ExactProtocolJson.sha256(wire)
        db.execSQL("INSERT INTO journal(sequence,event_id,request_id,event_type,payload,previous_hash,hash) VALUES (?,?,?,?,?,?,?)",
            arrayOf(sequence,eventId,requestId,type,wire,previous,hash))
        return eventId
    }

    fun record(type:String,requestId:String?,payload:JSONObject):String = synchronized(executionLock) {
        transaction { append(it,type,requestId,payload) }
    }

    fun connect(bootEpoch:String):String = synchronized(executionLock) {
        transaction { db ->
            verifyJournal(db)
            val epoch=UUID.randomUUID().toString()
            put(db,"boot_epoch",bootEpoch);put(db,"connection_epoch",epoch)
            append(db,"HELPER_CONNECTED",null,JSONObject().put("boot_epoch",bootEpoch).put("connection_epoch",epoch))
            val missing=mutableListOf<String>()
            db.rawQuery("SELECT request_id FROM claims WHERE request_id NOT IN (SELECT request_id FROM receipts)",null).use {
                while(it.moveToNext())missing.add(it.getString(0))
            }
            missing.forEach { append(db,"RECOVERY_UNKNOWN_EXECUTION_STATE",it,JSONObject().put("retry_allowed",false)) }
            val hasConsumed=db.rawQuery("SELECT 1 FROM claims LIMIT 1",null).use { it.moveToFirst() }
            if(hasConsumed) {
                localStopped=true
                if(get(db,"stopped")!="true") {
                    put(db,"stopped","true");put(db,"stop_epoch",UUID.randomUUID().toString())
                    append(db,"RECOVERY_STOP_UNVERIFIED_EFFECT",null,JSONObject().put("retry_allowed",false))
                }
            }
            // No execution is resumed, and no active claim is deleted on reconnect.
            epoch
        }
    }

    fun stop(reason:String):String = synchronized(executionLock) {
        localStopped=true // Even a failed persistence operation cannot re-enable this process.
        transaction { db ->
            if(get(db,"stopped")!="true") {
                put(db,"stopped","true");put(db,"stop_epoch",UUID.randomUUID().toString())
                append(db,"HARD_STOP",null,JSONObject().put("reason",reason).put("stop_epoch",get(db,"stop_epoch")))
            }
            get(db,"stop_epoch")!!
        }
    }

    fun register(request:JSONObject) = synchronized(executionLock) {
        transaction { db ->
            verifyJournal(db)
            val b=request.getJSONObject("binding")
            val exists=db.rawQuery("SELECT 1 FROM requests WHERE request_id=? OR permit_id=? OR nonce=? OR transaction_id=?",
                arrayOf(b.getString("request_id"),b.getString("permit_id"),b.getString("request_nonce"),b.getString("transaction_id"))).use{it.moveToFirst()}
            ExactActionContract.requireThat(!exists,"REQUEST_REPLAYED")
            db.execSQL("INSERT INTO requests(request_id,permit_id,nonce,transaction_id,digest,payload) VALUES (?,?,?,?,?,?)",
                arrayOf(b.getString("request_id"),b.getString("permit_id"),b.getString("request_nonce"),b.getString("transaction_id"),
                    request.getString("request_digest"),ExactProtocolJson.canonical(request)))
            append(db,"REQUEST_RECEIVED",b.getString("request_id"),request)
        }
    }

    fun claim(request:JSONObject,nowMs:Long):String = synchronized(executionLock) {
        transaction { db ->
            verifyJournal(db)
            val b=request.getJSONObject("binding");val id=b.getString("request_id")
            fun require(ok:Boolean,code:String)=ExactActionContract.requireThat(ok,code)
            require(!localStopped && get(db,"stopped")=="false","HARD_STOP_ACTIVE")
            for ((field,key) in mapOf("boot_epoch" to "boot_epoch","helper_connection_epoch" to "connection_epoch","stop_epoch" to "stop_epoch")) {
                require(b.getString(field)==get(db,key),field.uppercase()+"_MISMATCH")
            }
            require(nowMs>=b.getLong("issued_at_ms") && nowMs<b.getLong("expires_at_ms"),"PERMIT_EXPIRED")
            val stored=db.rawQuery("SELECT payload FROM requests WHERE request_id=?",arrayOf(id)).use { if(it.moveToFirst())it.getString(0) else null }
            require(stored==ExactProtocolJson.canonical(request),"OWNERSHIP_MISMATCH")
            val approval=db.rawQuery("SELECT payload FROM journal WHERE request_id=? AND event_type='PRE_DISPATCH_APPROVED' ORDER BY sequence DESC LIMIT 1",arrayOf(id)).use {
                if(it.moveToFirst())JSONObject(it.getString(0)).getJSONObject("payload") else null
            }
            require(approval?.optString("request_digest")==request.getString("request_digest"),"PRE_DISPATCH_GATE_REJECTED")
            val used=db.rawQuery("SELECT 1 FROM claims WHERE permit_id=? OR request_id=? OR nonce=? OR transaction_id=?",
                arrayOf(b.getString("permit_id"),id,b.getString("request_nonce"),b.getString("transaction_id"))).use{it.moveToFirst()}
            require(!used,"PERMIT_ALREADY_USED")
            require(!db.rawQuery("SELECT 1 FROM active_channel LIMIT 1",null).use{it.moveToFirst()},"CONCURRENT_ACTION")
            val receipt=UUID.randomUUID().toString()
            db.execSQL("INSERT INTO active_channel(scope,request_id) VALUES ('exact-action',?)",arrayOf(id))
            db.execSQL("INSERT INTO claims(permit_id,request_id,nonce,transaction_id,receipt_id,digest) VALUES (?,?,?,?,?,?)",
                arrayOf(b.getString("permit_id"),id,b.getString("request_nonce"),b.getString("transaction_id"),receipt,request.getString("request_digest")))
            append(db,"DISPATCH_STARTED",id,JSONObject().put("consumption_receipt_id",receipt).put("ownership",b.getJSONObject("ownership")))
            append(db,"CONSUMED",id,JSONObject().put("consumption_receipt_id",receipt))
            receipt
        }
    }

    fun approve(request:JSONObject,facts:Map<String,Any?>) = synchronized(executionLock) {
        ExactActionContract.requireThat(ExactActionContract.failures(facts).isEmpty(),"PRE_DISPATCH_GATE_REJECTED")
        record("PRE_DISPATCH_APPROVED",request.getJSONObject("binding").getString("request_id"),
            JSONObject().put("request_digest",request.getString("request_digest")).put("facts",JSONObject(facts)))
    }

    fun storeReceipt(requestId:String,payload:JSONObject) = synchronized(executionLock) {
        localStopped=true
        transaction { db ->
            val wire=ExactProtocolJson.canonical(payload)
            db.execSQL("INSERT INTO receipts(request_id,payload,hash) VALUES (?,?,?)",arrayOf(requestId,wire,ExactProtocolJson.sha256(wire)))
            append(db,"ACK_PREPARED",requestId,payload)
            // Receipt + stop are one transaction: no crash gap can free an unverified channel.
            if(get(db,"stopped")!="true") {
                put(db,"stopped","true");put(db,"stop_epoch",UUID.randomUUID().toString())
                append(db,"HARD_STOP",requestId,JSONObject().put("reason","C4_EFFECT_UNVERIFIED").put("stop_epoch",get(db,"stop_epoch")))
            }
            // Unique claims are retained forever; the durable stop now blocks any subsequent action.
            db.execSQL("DELETE FROM active_channel WHERE request_id=?",arrayOf(requestId))
        }
    }

    fun receipt(requestId:String):JSONObject? = synchronized(executionLock) {
        verifyJournal(readableDatabase)
        readableDatabase.rawQuery("SELECT payload,hash FROM receipts WHERE request_id=?",arrayOf(requestId)).use {
            if(!it.moveToFirst())return@use null
            val wire=it.getString(0)
            ExactActionContract.requireThat(ExactProtocolJson.sha256(wire)==it.getString(1),"AUDIT_PERSIST_FAILED")
            JSONObject(wire)
        }
    }

    fun claimed(requestId:String):Boolean = synchronized(executionLock) {
        readableDatabase.rawQuery("SELECT 1 FROM claims WHERE request_id=?",arrayOf(requestId)).use { it.moveToFirst() }
    }

    fun sequence():Long = synchronized(executionLock) {
        readableDatabase.rawQuery("SELECT COALESCE(MAX(sequence),0) FROM journal",null).use { it.moveToFirst();it.getLong(0) }
    }

    /** Exact original registered packet only; expiry never authorizes re-execution. */
    fun readback(request:JSONObject):JSONObject = synchronized(executionLock) {
        val id=request.getJSONObject("binding").getString("request_id")
        val registered=readableDatabase.rawQuery("SELECT payload FROM requests WHERE request_id=?",arrayOf(id)).use {
            if(it.moveToFirst())it.getString(0) else null
        }
        ExactActionContract.requireThat(registered==ExactProtocolJson.canonical(request),"OWNERSHIP_MISMATCH")
        val known=receipt(id)
        record("RECEIPT_READBACK",id,JSONObject().put("request_digest",request.getString("request_digest")))
        known ?: JSONObject().apply {
            put("status","UNKNOWN_EXECUTION_STATE");put("permit_consumed",claimed(id))
            put("request_digest",request.getString("request_digest"))
            val b=request.getJSONObject("binding")
            for(k in listOf("request_id","transaction_id","permit_id","request_nonce","ownership","helper_build_id",
                "helper_connection_epoch","boot_epoch","stop_epoch"))put(k,b.get(k))
            put("action_request_resent",false);put("visit_authority",false)
        }
    }

    private fun verifyJournal(db:SQLiteDatabase) {
        var previous="0".repeat(64)
        var sequence=0L
        val consumed=mutableMapOf<String,String>()
        val prepared=mutableMapOf<String,String>()
        val received=mutableMapOf<String,String>()
        db.rawQuery("SELECT payload,previous_hash,hash,sequence,event_id,event_type,request_id FROM journal ORDER BY sequence",null).use { cursor ->
            while(cursor.moveToNext()) {
                ExactActionContract.requireThat(cursor.getString(1)==previous && ExactProtocolJson.sha256(cursor.getString(0))==cursor.getString(2),"AUDIT_PERSIST_FAILED")
                val record=JSONObject(cursor.getString(0));sequence++
                ExactActionContract.requireThat(record.getLong("producer_sequence")==sequence && cursor.getLong(3)==sequence &&
                    record.getString("event_id")==cursor.getString(4) && record.getString("event_type")==cursor.getString(5),"AUDIT_PERSIST_FAILED")
                val id=cursor.getString(6)
                if(id!=null)ExactActionContract.requireThat(record.getString("request_id")==id,"AUDIT_PERSIST_FAILED")
                val payload=record.getJSONObject("payload")
                when(record.getString("event_type")) {
                    "CONSUMED"->consumed[id]=payload.getString("consumption_receipt_id")
                    "ACK_PREPARED"->prepared[id]=ExactProtocolJson.canonical(payload)
                    "REQUEST_RECEIVED"->received[id]=ExactProtocolJson.canonical(payload)
                    "HARD_STOP"->ExactActionContract.requireThat(get(db,"stopped")=="true" && get(db,"stop_epoch")==payload.getString("stop_epoch"),"AUDIT_PERSIST_FAILED")
                }
                previous=cursor.getString(2)
            }
        }
        db.rawQuery("SELECT payload,hash,request_id FROM receipts",null).use { cursor ->
            while(cursor.moveToNext())ExactActionContract.requireThat(ExactProtocolJson.sha256(cursor.getString(0))==cursor.getString(1) && prepared[cursor.getString(2)]==cursor.getString(0),"AUDIT_PERSIST_FAILED")
        }
        db.rawQuery("SELECT request_id,receipt_id FROM claims",null).use { cursor ->
            while(cursor.moveToNext())ExactActionContract.requireThat(consumed[cursor.getString(0)]==cursor.getString(1),"AUDIT_PERSIST_FAILED")
        }
        db.rawQuery("SELECT request_id,payload FROM requests",null).use { cursor ->
            while(cursor.moveToNext())ExactActionContract.requireThat(received[cursor.getString(0)]==cursor.getString(1),"AUDIT_PERSIST_FAILED")
        }
    }
}
