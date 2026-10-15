package com.iotpart.sqe.talkbackhelper

import org.json.JSONObject
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import java.util.UUID
import android.os.SystemClock

internal class ExactActionRejected(val code: String) : IllegalArgumentException(code)

internal enum class ExactActionState {
    ISSUED, VALIDATED, RESOLVED, PRE_DISPATCH_APPROVED, DISPATCH_STARTED, CONSUMED, ACKED,
    FAILED_NOT_EXECUTED, FAILED_CONSUMED, UNKNOWN_EXECUTION_STATE;

    fun permits(next: ExactActionState): Boolean = next in when (this) {
        ISSUED -> setOf(VALIDATED, FAILED_NOT_EXECUTED)
        VALIDATED -> setOf(RESOLVED, FAILED_NOT_EXECUTED)
        RESOLVED -> setOf(PRE_DISPATCH_APPROVED, FAILED_NOT_EXECUTED)
        PRE_DISPATCH_APPROVED -> setOf(DISPATCH_STARTED, FAILED_NOT_EXECUTED)
        DISPATCH_STARTED -> setOf(CONSUMED, UNKNOWN_EXECUTION_STATE)
        CONSUMED -> setOf(ACKED, FAILED_CONSUMED, UNKNOWN_EXECUTION_STATE)
        else -> emptySet()
    }
}

internal enum class ExactTargetClass {
    NAVIGATION_TARGET, STATE_MUTATION_CONTROL, UNKNOWN_ACTIONABLE, CONTAINER_WRAPPER, MIXED_ACTION_CONTAINER
}

internal class ExactActionTransaction {
    var state=ExactActionState.ISSUED; private set
    var consumed=false; private set
    fun move(next:ExactActionState) {
        ExactActionContract.requireThat(state.permits(next),"ILLEGAL_STATE_TRANSITION")
        if(next==ExactActionState.DISPATCH_STARTED || next==ExactActionState.CONSUMED)consumed=true
        state=next
    }
}

internal object ExactActionContract {
    const val VERSION = "talkback.exact-action.v2"
    const val ACK_VERSION = "2"
    const val MODE = "C4_DIAGNOSTIC_ACCEPTANCE_V1"
    val checks = ("build_gate runtime_gate helper_identity_match protocol_supported ownership_valid " +
        "permit_authenticated request_digest_valid transaction_valid request_unique nonce_unique permit_unused " +
        "unexpired host_session_match boot_epoch_match connection_epoch_match stop_epoch_match host_stop_inactive " +
        "helper_stop_inactive exclusive_channel package_match window_match hierarchy_complete single_candidate " +
        "identity_match lineage_match children_match action_set_match click_present enabled visible node_valid " +
        "target_class_allowed semantic_approved isolation_approved observation_ready destination_ready " +
        "forbidden_detector_ready audit_persisted durable_claim_available").split(" ")

    val bindingFields = ("request_id transaction_id permit_id request_nonce ownership expected_package app_version " +
        "helper_build_id host_session_id boot_epoch helper_connection_epoch stop_epoch target_identity_digest " +
        "authorized_intent_digest semantic_intent allowed_action max_call_count issued_at_ms expires_at_ms " +
        "resolve_request_digest").split(" ").toSet()
    val intentFields = ("kind target_class semantic_approved isolation_approved destination_contract_id " +
        "destination_contract_digest evidence_refs").split(" ").toSet()

    fun failures(facts: Map<String, Any?>): List<String> = checks.filter { facts[it] != true }
    fun classify(mutation: Boolean, independentActions: Int, wrapper: Boolean, navigation: Boolean): ExactTargetClass = when {
        mutation -> ExactTargetClass.STATE_MUTATION_CONTROL
        independentActions > 0 -> ExactTargetClass.MIXED_ACTION_CONTAINER
        wrapper -> ExactTargetClass.CONTAINER_WRAPPER
        navigation -> ExactTargetClass.NAVIGATION_TARGET
        else -> ExactTargetClass.UNKNOWN_ACTIONABLE
    }
    fun requireThat(ok: Boolean, code: String) { if (!ok) throw ExactActionRejected(code) }
    fun digestWithoutSelf(request: JSONObject): String = ExactProtocolJson.hash(JSONObject(request.toString()).apply { remove("request_digest") })
}

/** A trusted local issuer supplies this session. No RPC accepts keys or registers sessions. */
internal class ExactActionSession(
    secret: ByteArray, val sessionId: String, val packageName: String, val appVersion: String,
    val buildId: String, val bootEpoch: String, val connectionEpoch: String, val stopEpoch: String,
    allowedIntentDigests: Set<String>,
    allowedTargetDigests: Set<String>, allowedTransactionIds: Set<String>,
    val identityStatus:String="UNKNOWN",
) {
    private val secret = secret.copyOf()
    private val allowedIntents = allowedIntentDigests.toSet()
    private val allowedTargets = allowedTargetDigests.toSet()
    private val allowedTransactions = allowedTransactionIds.toSet()
    private val createdElapsed=SystemClock.elapsedRealtime()
    init { require(secret.size >= 32 && allowedTargets.size==1 && allowedTransactions.size==1) }

    fun mac(binding: JSONObject): String = Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(secret, "HmacSHA256"))
        doFinal(ExactProtocolJson.canonical(binding).toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }

    fun verify(request: JSONObject, nowMs: Long): JSONObject {
        fun check(ok: Boolean, code: String) = ExactActionContract.requireThat(ok, code)
        check(identityStatus=="MATCH","BUILD_IDENTITY_UNKNOWN")
        check(SystemClock.elapsedRealtime()-createdElapsed in 0..5000,"PERMIT_EXPIRED")
        check(request.keys().asSequence().toSet() == setOf("protocol_version","command","resolve_request","binding","permit_mac","request_digest"), "REQUEST_INVALID")
        check(request.optString("protocol_version") == ExactActionContract.VERSION && request.optString("command") == "EXACT_ACTION", "PROTOCOL_VERSION_UNSUPPORTED")
        check(ExactActionContract.digestWithoutSelf(request) == request.optString("request_digest"), "REQUEST_DIGEST_MISMATCH")
        val resolve = request.getJSONObject("resolve_request")
        val invalid = ExactNodeResolver.validateOnly(resolve, false, connectionEpoch)
        check(invalid == null, invalid ?: "REQUEST_INVALID")
        val b = request.getJSONObject("binding")
        check(b.keys().asSequence().toSet() == ExactActionContract.bindingFields, "PERMIT_INVALID")
        for (key in listOf("request_id","transaction_id","permit_id","request_nonce","ownership","expected_package","host_session_id","stop_epoch")) {
            check(ExactProtocolJson.canonical(b.get(key)) == ExactProtocolJson.canonical(resolve.get(key)), "OWNERSHIP_MISMATCH")
        }
        check(b.opt("allowed_action") == 16 && b.opt("max_call_count") == 1, "ACTION_NOT_AVAILABLE")
        check((b.opt("issued_at_ms") is Long || b.opt("issued_at_ms") is Int) &&
            (b.opt("expires_at_ms") is Long || b.opt("expires_at_ms") is Int), "PERMIT_INVALID")
        val issued = b.getLong("issued_at_ms"); val expires = b.getLong("expires_at_ms")
        val lifetime=runCatching{Math.subtractExact(expires,issued)}.getOrElse{throw ExactActionRejected("PERMIT_INVALID")}
        check(lifetime in 1..5000 && nowMs >= issued && nowMs < expires, "PERMIT_EXPIRED")
        val intent = b.getJSONObject("semantic_intent")
        check(intent.keys().asSequence().toSet() == ExactActionContract.intentFields, "ACTION_SEMANTICS_UNPROVEN")
        check(intent.optString("kind") == "NAVIGATION" && runCatching { ExactTargetClass.valueOf(intent.getString("target_class")) }.isSuccess &&
            intent.opt("semantic_approved") is Boolean && intent.opt("isolation_approved") is Boolean &&
            intent.opt("destination_contract_id") is String && intent.optString("destination_contract_id").isNotBlank() &&
            intent.optString("destination_contract_digest").matches(Regex("[0-9a-f]{64}")), "ACTION_SEMANTICS_UNPROVEN")
        val refs = intent.optJSONArray("evidence_refs")
        check(refs != null && refs.length() > 0 && (0 until refs.length()).all { refs.opt(it) is String && refs.getString(it).isNotBlank() }, "ACTION_SEMANTICS_UNPROVEN")
        check(b.optString("target_identity_digest") == ExactProtocolJson.hash(resolve.getJSONObject("target_identity")) &&
            b.optString("authorized_intent_digest") == ExactProtocolJson.hash(intent) &&
            b.optString("resolve_request_digest") == resolve.optString("request_digest"), "REQUEST_DIGEST_MISMATCH")
        val providedMac = request.optString("permit_mac")
        check(providedMac.matches(Regex("[0-9a-f]{64}")) && MessageDigest.isEqual(mac(b).toByteArray(),providedMac.toByteArray()), "PERMIT_AUTHENTICATION_FAILED")
        val expected = mapOf("host_session_id" to sessionId, "expected_package" to packageName, "app_version" to appVersion,
            "helper_build_id" to buildId, "boot_epoch" to bootEpoch, "helper_connection_epoch" to connectionEpoch, "stop_epoch" to stopEpoch)
        check(buildId.matches(Regex("[0-9a-f]{64}")),"BUILD_IDENTITY_UNKNOWN")
        expected.forEach { (key,value) -> check(value.isNotBlank() && value!="UNKNOWN" && b.opt(key) is String && b.optString(key) == value, key.uppercase(java.util.Locale.ROOT) + "_MISMATCH") }
        check(b.optString("authorized_intent_digest") in allowedIntents, "ACTION_SEMANTICS_UNPROVEN")
        check(b.optString("target_identity_digest") in allowedTargets && b.optString("transaction_id") in allowedTransactions,"PERMIT_SCOPE_MISMATCH")
        return resolve
    }
}

/** Pure model; runtime persistence is supplied by ExactActionStore. No diagnostic reset. */
internal class ExactActionStopLatch {
    var stopEpoch: String = UUID.randomUUID().toString(); private set
    var connectionEpoch: String = UUID.randomUUID().toString(); private set
    var stopped: Boolean = false; private set
    @Synchronized fun stop() { if (!stopped) { stopped = true; stopEpoch = UUID.randomUUID().toString() } }
    @Synchronized fun reconnect() { connectionEpoch = UUID.randomUUID().toString() }
}
