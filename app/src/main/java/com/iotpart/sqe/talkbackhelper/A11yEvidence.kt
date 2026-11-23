package com.iotpart.sqe.talkbackhelper

import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.graphics.Rect
import org.json.JSONObject
import org.json.JSONArray
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import java.util.UUID

internal data class EntryClickSourceIdentity(
    val requestId: String,
    val processEpoch: String,
    val generation: Long,
    val serviceInstanceId: String,
    val captureSequence: Long,
    val rootDigest: String,
    val candidateDigest: String,
    val captureKey: String,
    val connectionEpoch: String,
    val bootEpoch: String,
    val ownerSourceNodeId: String,
    val ownerSourceNodeIdStatus: String,
)

/**
 * Opt-in correlation-only evidence channel.
 *
 * It never participates in navigation, success, history, or reporting decisions.
 * The Python runner only supplies these extras when TB_EVIDENCE_LEDGER_ENABLED is on.
 */
object A11yEvidence {
    private const val TAG = "A11Y_HELPER"
    private const val EVENT_LOG_PREFIX = "EVIDENCE_HELPER_EVENT"
    private const val MAX_EVENT_LOG_CHARS = 3200
    private const val MAX_TRANSPORT_TEXT_CHARS = 256
    private val correlationByReqId = ConcurrentHashMap<String, JSONObject>()
    private val eventsByReqId = ConcurrentHashMap<String, MutableList<JSONObject>>()
    private val eventSequence = AtomicLong(0L)
    private val cleanupHandler = Handler(Looper.getMainLooper())
    private data class EntryClickCapture(
        val reqId: String,
        val transactionId: String,
        val captureId: String,
        val connectionId: String,
        val runId: String,
        val invocationId: String,
        val scenarioId: String,
        val sourceIdentity: EntryClickSourceIdentity,
        val canonicalInvocationUriBound: Boolean,
        val ownerTarget: ExactLiveNodeResolver.ObservationTarget?,
        var navigationRequestId: String? = null,
        var actionTarget: NavigationActionTargetLease? = null,
        var activationOwnerRelation: NavigationActivationOwnerRelation? = null,
        val ownerLeaseId: String,
        val armedElapsedRealtimeMs: Long,
        val leaseDeadlineElapsedRealtimeMs: Long,
        val cursorEventSequence: Long,
        var dispatchUptimeMs: Long? = null,
        var dispatchTargetCurrentnessAccepted: Boolean = false,
        var clickEventId: String? = null,
        var clickEventCapturedElapsedRealtimeMs: Long? = null,
        var postActionObservationEmitted: Boolean = false,
        val clickEvents: MutableList<JSONObject> = mutableListOf(),
    )
    @Volatile private var activeEntryClickCapture: EntryClickCapture? = null

    private val extraKeys = mapOf(
        "run_id" to "evidenceRunId",
        "scenario_tx_id" to "evidenceScenarioTxId",
        "transaction_id" to "evidenceTransactionId",
        "attempt_id" to "evidenceAttemptId",
        "logical_action_id" to "evidenceLogicalActionId"
    )

    fun capture(intent: Intent?, reqId: String) {
        if (intent == null || reqId.isBlank() || reqId == "none") return
        val correlation = JSONObject()
        extraKeys.forEach { (field, extra) ->
            intent.getStringExtra(extra)?.trim()?.takeIf { it.isNotEmpty() }?.let { correlation.put(field, it) }
        }
        if (correlation.length() > 0) {
            correlationByReqId[reqId] = correlation
            eventsByReqId.putIfAbsent(reqId, mutableListOf())
            Log.i(TAG, "[EVIDENCE][helper_start] requestId=$reqId transactionId=${correlation.optString("transaction_id")} enabled=true action=${intent?.action.orEmpty()}")
        }
    }

    fun hasCorrelation(reqId: String): Boolean = correlationByReqId.containsKey(reqId)

    internal fun armEntryClickCapture(reqId: String, transactionId: String, leaseMs: Long, connectionId: String,
        runId: String, invocationId: String, scenarioId: String,
        ownerTarget: ExactLiveNodeResolver.ObservationTarget,
        sourceIdentity: EntryClickSourceIdentity,
        canonicalInvocationUriBound: Boolean = false): JSONObject {
        val safeReqId = reqId.trim()
        val safeTransactionId = transactionId.trim()
        val safeConnectionId = connectionId.trim()
        val sourceNodeIdMatchesTarget = when (sourceIdentity.ownerSourceNodeIdStatus) {
            "FIELD_PRESENT" -> sourceIdentity.ownerSourceNodeId.isNotBlank() &&
                sourceIdentity.ownerSourceNodeId == ownerTarget.sourceNodeId
            "FIELD_ABSENT" -> sourceIdentity.ownerSourceNodeId.isBlank() && ownerTarget.sourceNodeId.isBlank()
            else -> false
        }
        if (safeReqId.isEmpty() || safeReqId == "none" || safeTransactionId.isEmpty() || safeConnectionId.isEmpty() ||
            runId.isBlank() || invocationId.isBlank() || scenarioId.isBlank() ||
            ownerTarget.connectionId != safeConnectionId ||
            sourceIdentity.requestId.isBlank() || sourceIdentity.processEpoch.isBlank() ||
            sourceIdentity.generation <= 0L || sourceIdentity.serviceInstanceId != safeConnectionId ||
            sourceIdentity.captureSequence <= 0L || sourceIdentity.rootDigest.isBlank() ||
            sourceIdentity.candidateDigest.isBlank() || sourceIdentity.captureKey != ownerTarget.sourceSnapshotId ||
            sourceIdentity.connectionEpoch.isBlank() || sourceIdentity.bootEpoch.isBlank() ||
            !sourceNodeIdMatchesTarget ||
            !ownerTarget.stillCurrent(safeConnectionId)) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_CORRELATION_MISSING")
        }
        val now = SystemClock.elapsedRealtime()
        val boundedLease = leaseMs.coerceIn(500L, 2500L)
        val capture = EntryClickCapture(
            reqId = safeReqId,
            transactionId = safeTransactionId,
            captureId = UUID.randomUUID().toString(),
            connectionId = safeConnectionId,
            runId = runId,
            invocationId = invocationId,
            scenarioId = scenarioId,
            sourceIdentity = sourceIdentity,
            canonicalInvocationUriBound = canonicalInvocationUriBound,
            ownerTarget = ownerTarget,
            ownerLeaseId = UUID.randomUUID().toString(),
            armedElapsedRealtimeMs = now,
            leaseDeadlineElapsedRealtimeMs = now + boundedLease,
            cursorEventSequence = eventSequence.get(),
        )
        synchronized(this) {
            if (activeEntryClickCapture != null) {
                return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ALREADY_ACTIVE")
            }
            correlationByReqId[safeReqId] = JSONObject().put("transaction_id", safeTransactionId)
            eventsByReqId[safeReqId] = mutableListOf()
            activeEntryClickCapture = capture
        }
        try {
            val cleanupScheduled = cleanupHandler.postDelayed({
            synchronized(this) {
                if (activeEntryClickCapture === capture) {
                    activeEntryClickCapture = null
                    correlationByReqId.remove(safeReqId)
                    eventsByReqId.remove(safeReqId)
                }
            }
            }, capture.leaseDeadlineElapsedRealtimeMs - now + 250L)
            if (!cleanupScheduled) throw IllegalStateException("entry_capture_cleanup_not_scheduled")
            Log.i(TAG, "[ENTRY_CLICK_CAPTURE][armed] reqId=$safeReqId transactionId=$safeTransactionId cursor=${capture.cursorEventSequence}")
            return entryClickSnapshot(safeReqId).put("ok", true).put("reason", "ARMED")
                .put("runId", capture.runId).put("invocationId", capture.invocationId)
                .put("scenarioId", capture.scenarioId)
                .put("ownerLeaseId", capture.ownerLeaseId).put("ownerWindowId", ownerTarget.windowId)
                .put("ownerPackageName", ownerTarget.packageName)
                .put("ownerPath", JSONArray(ownerTarget.nodePath)).put("ownerDescriptorDigest", ownerTarget.descriptorDigest)
                .put("sourceSnapshotId", ownerTarget.sourceSnapshotId).put("helperSnapshotId", ownerTarget.helperSnapshotId)
                .put("baselineHierarchyDigest", ownerTarget.baselineHierarchyDigest)
                .put("leaseDeadlineElapsedRealtimeMs", capture.leaseDeadlineElapsedRealtimeMs)
        } catch (error: Exception) {
            synchronized(this) {
                if (activeEntryClickCapture === capture) {
                    activeEntryClickCapture = null
                    correlationByReqId.remove(safeReqId)
                    eventsByReqId.remove(safeReqId)
                }
            }
            Log.w(TAG, "[ENTRY_CLICK_CAPTURE][arm_failed] reqId=$safeReqId transactionId=$safeTransactionId " +
                "failureType=${error.javaClass.simpleName.take(80)}")
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ARM_FAILED")
                .put("failureType", error.javaClass.simpleName.take(80))
        }
    }

    private fun sameNavigationActionTarget(
        left: NavigationActionTargetLease,
        right: NavigationActionTargetLease,
    ): Boolean = left.windowId == right.windowId && left.nodePath == right.nodePath &&
        left.descriptorDigest == right.descriptorDigest && left.sourceSnapshotId == right.sourceSnapshotId &&
        left.helperSnapshotId == right.helperSnapshotId &&
        left.baselineHierarchyDigest == right.baselineHierarchyDigest &&
        left.connectionId == right.connectionId && left.packageName == right.packageName &&
        left.className == right.className && left.resourceId == right.resourceId &&
        left.isUniqueInSnapshot == right.isUniqueInSnapshot && left.hasClickAction == right.hasClickAction

    private fun ownerActionIdentity(
        capture: EntryClickCapture,
        actionTarget: NavigationActionTargetLease,
    ): JSONObject {
        val parent = capture.ownerTarget
        return JSONObject()
            .put("ownerActionPath", JSONArray(actionTarget.nodePath))
            .put("ownerActionDescriptorDigest", actionTarget.descriptorDigest)
            .put("ownerActionWindowId", actionTarget.windowId)
            .put("ownerActionConnectionId", actionTarget.connectionId)
            .put("navigationRequestId", capture.navigationRequestId ?: JSONObject.NULL)
            .put("ownerCaptureReqId", capture.reqId)
            .put("ownerLeaseId", capture.ownerLeaseId)
            .put("transactionId", capture.transactionId)
            .put("serviceInstanceId", capture.sourceIdentity.serviceInstanceId)
            .put("ownerAuthorizationPath", parent?.let { JSONArray(it.nodePath) } ?: JSONObject.NULL)
            .put("ownerAuthorizationDescriptorDigest", parent?.descriptorDigest ?: JSONObject.NULL)
            .put("ownerAuthorizationWindowId", parent?.windowId ?: JSONObject.NULL)
            .put("activationOwnerRelation", capture.activationOwnerRelation?.toJson() ?: JSONObject.NULL)
    }

    /** Bind event observation to the exact contract-declared child, retaining parent authorization separately. */
    internal fun bindNavigationActionTarget(
        reqId: String,
        navigationRequestId: String,
        transactionId: String,
        currentConnectionId: String,
        runId: String,
        invocationId: String,
        scenarioId: String,
        captureId: String,
        ownerLeaseId: String,
        sourceIdentity: EntryClickSourceIdentity,
        authorizationTarget: NavigationActionTargetLease,
        actionTarget: NavigationActionTargetLease,
        relation: NavigationActivationOwnerRelation?,
    ): JSONObject = synchronized(this) {
        val capture = activeEntryClickCapture
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_NOT_ARMED")
        if (navigationRequestId.isBlank() || capture.reqId != reqId || capture.transactionId != transactionId ||
            capture.connectionId != currentConnectionId || capture.runId != runId ||
            capture.invocationId != invocationId || capture.scenarioId != scenarioId ||
            capture.captureId != captureId || capture.ownerLeaseId != ownerLeaseId ||
            capture.sourceIdentity != sourceIdentity || !capture.canonicalInvocationUriBound) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ACTION_BINDING_MISMATCH")
        }
        val retainedParent = capture.ownerTarget?.navigationActionLease()
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_PARENT_MISSING")
        if (!sameNavigationActionTarget(retainedParent, authorizationTarget)) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_PARENT_MISMATCH")
        }
        val actionTargetMatches = if (relation == null) {
            sameNavigationActionTarget(actionTarget, authorizationTarget) &&
                actionTarget.isUniqueInSnapshot && actionTarget.hasClickAction &&
                actionTarget.hasAccessibilityFocusAction
        } else relation.isWellFormed() &&
            actionTarget.nodePath == authorizationTarget.nodePath + relation.childIndex &&
            actionTarget.windowId == authorizationTarget.windowId &&
            actionTarget.packageName == authorizationTarget.packageName &&
            actionTarget.connectionId == authorizationTarget.connectionId &&
            actionTarget.sourceSnapshotId == authorizationTarget.sourceSnapshotId &&
            actionTarget.helperSnapshotId == authorizationTarget.helperSnapshotId &&
            actionTarget.baselineHierarchyDigest == authorizationTarget.baselineHierarchyDigest &&
            Regex(relation.childClassPattern).matches(actionTarget.className) &&
            actionTarget.resourceId == relation.childResourceId && actionTarget.isUniqueInSnapshot &&
            actionTarget.hasClickAction
        if (!actionTargetMatches) {
            return JSONObject().put("ok", false).put("reason", if (relation == null)
                "ENTRY_CLICK_CAPTURE_ACTION_TARGET_MISMATCH" else "ENTRY_CLICK_CAPTURE_ACTION_CHILD_MISMATCH")
        }
        val now = SystemClock.elapsedRealtime()
        if (now > capture.leaseDeadlineElapsedRealtimeMs ||
            !retainedParent.stillCurrent(currentConnectionId) || !actionTarget.stillCurrent(currentConnectionId)) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE")
        }
        if (capture.dispatchUptimeMs != null || capture.navigationRequestId != null ||
            capture.actionTarget != null || capture.clickEvents.isNotEmpty()) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ACTION_TARGET_ALREADY_BOUND")
        }
        capture.navigationRequestId = navigationRequestId
        capture.actionTarget = actionTarget
        capture.activationOwnerRelation = relation
        ownerActionIdentity(capture, actionTarget).put("ok", true).put("reason", "ACTION_TARGET_BOUND")
    }

    /** Legacy host tap correlation keeps its post-action mark semantics. */
    fun markEntryClickDispatch(reqId: String, transactionId: String, currentConnectionId: String,
        dispatchElapsedRealtimeMs: Long): JSONObject = synchronized(this) {
        if (dispatchElapsedRealtimeMs < 0L) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_CURSOR_INVALID")
        }
        val capture = activeEntryClickCapture
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_NOT_ARMED")
        if (capture.reqId != reqId) return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_REQUEST_MISMATCH")
        if (capture.transactionId != transactionId) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_TRANSACTION_MISMATCH")
        }
        if (capture.connectionId != currentConnectionId) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_CONNECTION_MISMATCH")
        }
        if (dispatchElapsedRealtimeMs < capture.armedElapsedRealtimeMs ||
            dispatchElapsedRealtimeMs >= capture.leaseDeadlineElapsedRealtimeMs ||
            SystemClock.elapsedRealtime() > capture.leaseDeadlineElapsedRealtimeMs) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_OUTSIDE_LEASE")
        }
        if (capture.dispatchUptimeMs != null) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_ALREADY_MARKED")
        }
        val actionTarget = capture.actionTarget ?: capture.ownerTarget?.navigationActionLease()
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_TARGET_MISSING")
        capture.dispatchUptimeMs = dispatchElapsedRealtimeMs
        val eligible = capture.clickEvents.filter { event ->
            event.optBoolean("owner_exact") && eventElapsedRealtimeMs(event) > dispatchElapsedRealtimeMs
        }
        val exact = eligible.singleOrNull()
        capture.clickEventId = exact?.optString("event_id")?.takeIf { it.isNotBlank() }
        capture.clickEventCapturedElapsedRealtimeMs = exact?.optLong("captured_elapsed_realtime_ms")
        ownerActionIdentity(capture, actionTarget)
            .put("ok", true).put("reason", "DISPATCH_MARKED")
            .put("ownerLeaseId", capture.ownerLeaseId)
            .put("dispatchElapsedRealtimeMs", dispatchElapsedRealtimeMs)
            .put("dispatchTargetCurrentnessAccepted", false)
            .put("clickEventId", capture.clickEventId ?: JSONObject.NULL)
            .put("eligibleExactClickCount", eligible.size)
    }

    /** Strict navigation marks the resolved action owner while both retained targets are current. */
    internal fun markNavigationEntryClickDispatch(
        reqId: String,
        transactionId: String,
        currentConnectionId: String,
        dispatchElapsedRealtimeMs: Long,
        verifiedFocusEvidence: NavigationFocusEvidence? = null,
    ): JSONObject = synchronized(this) {
        if (dispatchElapsedRealtimeMs < 0L) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_CURSOR_INVALID")
        }
        val capture = activeEntryClickCapture
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_NOT_ARMED")
        if (capture.reqId != reqId || capture.transactionId != transactionId ||
            capture.connectionId != currentConnectionId) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_IDENTITY_MISMATCH")
        }
        if (dispatchElapsedRealtimeMs < capture.armedElapsedRealtimeMs ||
            dispatchElapsedRealtimeMs >= capture.leaseDeadlineElapsedRealtimeMs ||
            dispatchElapsedRealtimeMs > SystemClock.elapsedRealtime() ||
            SystemClock.elapsedRealtime() > capture.leaseDeadlineElapsedRealtimeMs) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_OUTSIDE_LEASE")
        }
        if (capture.dispatchUptimeMs != null) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_ALREADY_MARKED")
        }
        if (capture.clickEvents.any { it.optBoolean("owner_exact") }) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_OWNER_EVENT_PRECEDED_DISPATCH")
        }
        val actionTarget = capture.actionTarget ?: capture.ownerTarget?.navigationActionLease()
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_TARGET_MISSING")
        val authorizationTarget = capture.ownerTarget
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_PARENT_MISSING")
        if (capture.activationOwnerRelation != null && capture.actionTarget == null) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ACTION_TARGET_MISSING")
        }
        val focusProof = verifiedFocusEvidence
        val currentnessAccepted = if (focusProof == null) {
            authorizationTarget.stillCurrent(currentConnectionId) &&
                actionTarget.stillCurrent(currentConnectionId)
        } else {
            val relation = capture.activationOwnerRelation
            val focusProofMatches = !capture.navigationRequestId.isNullOrBlank() &&
                focusProof.requestId == capture.navigationRequestId &&
                focusProof.ownerCaptureReqId == capture.reqId &&
                focusProof.ownerLeaseId == capture.ownerLeaseId &&
                focusProof.transactionId == transactionId &&
                focusProof.serviceInstanceId == capture.sourceIdentity.serviceInstanceId &&
                focusProof.connectionId == currentConnectionId &&
                focusProof.windowId == authorizationTarget.windowId &&
                focusProof.windowId == actionTarget.windowId &&
                focusProof.eventType == AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED &&
                focusProof.eventElapsedRealtimeMs in capture.armedElapsedRealtimeMs..dispatchElapsedRealtimeMs &&
                focusProof.eventElapsedRealtimeMs < capture.leaseDeadlineElapsedRealtimeMs &&
                actionTarget.eventSourceMatches(
                    focusProof.source, focusProof.windowId, currentConnectionId)
            if (!focusProofMatches) {
                return JSONObject().put("ok", false).put("reason",
                    "ENTRY_CLICK_CAPTURE_FOCUS_PROOF_MISMATCH")
            }
            val focusRevalidation = if (relation == null) {
                val retainedAuthorization = authorizationTarget.navigationActionLease()
                if (capture.actionTarget == null ||
                    !sameNavigationActionTarget(actionTarget, retainedAuthorization)) {
                    return JSONObject().put("ok", false)
                        .put("reason", "ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE")
                }
                actionTarget.revalidateAfterAccessibilityFocus(currentConnectionId)
            } else {
                if (!relation.isWellFormed()) {
                    return JSONObject().put("ok", false)
                        .put("reason", "ENTRY_CLICK_CAPTURE_FOCUS_PROOF_MISMATCH")
                }
                actionTarget.revalidateAfterDeclaredChildAccessibilityFocus(
                    currentConnectionId, authorizationTarget.navigationActionLease(), relation, focusProof)
            }
            if (!focusRevalidation.accepted) {
                return JSONObject().put("ok", false)
                    .put("reason", "ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE")
                    .put("focus_revalidation", JSONObject(focusRevalidation.diagnostics.toString()))
            }
            true
        }
        if (!currentnessAccepted) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_ACTION_TARGET_STALE")
        }
        capture.dispatchTargetCurrentnessAccepted = true
        capture.dispatchUptimeMs = dispatchElapsedRealtimeMs
        val eligible = capture.clickEvents.filter { event ->
            event.optBoolean("owner_exact") && eventElapsedRealtimeMs(event) > dispatchElapsedRealtimeMs
        }
        capture.clickEventId = eligible.singleOrNull()?.optString("event_id")?.takeIf { it.isNotBlank() }
        capture.clickEventCapturedElapsedRealtimeMs = eligible.singleOrNull()
            ?.optLong("captured_elapsed_realtime_ms")
        ownerActionIdentity(capture, actionTarget)
            .put("ok", true).put("reason", "DISPATCH_MARKED")
            .put("ownerLeaseId", capture.ownerLeaseId)
            .put("dispatchElapsedRealtimeMs", dispatchElapsedRealtimeMs)
            .put("dispatchTargetCurrentnessAccepted", capture.dispatchTargetCurrentnessAccepted)
            .put("focusProofAccepted", focusProof != null)
            .put("focusEventElapsedRealtimeMs", focusProof?.eventElapsedRealtimeMs ?: JSONObject.NULL)
            .put("focusEventWindowId", focusProof?.windowId ?: JSONObject.NULL)
            .put("clickEventId", capture.clickEventId ?: JSONObject.NULL)
            .put("eligibleExactClickCount", eligible.size)
    }

    /** Read back the exact event owned by a previously marked dispatch. */
    fun confirmEntryClickDispatch(
        reqId: String,
        transactionId: String,
        currentConnectionId: String,
        dispatchElapsedRealtimeMs: Long,
    ): JSONObject = synchronized(this) {
        val capture = activeEntryClickCapture
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_NOT_ARMED")
        if (capture.reqId != reqId || capture.transactionId != transactionId ||
            capture.connectionId != currentConnectionId) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_IDENTITY_MISMATCH")
        }
        if (capture.dispatchUptimeMs != dispatchElapsedRealtimeMs) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_MARK_MISMATCH")
        }
        val actionTarget = capture.actionTarget ?: capture.ownerTarget?.navigationActionLease()
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_TARGET_MISSING")
        if (!capture.dispatchTargetCurrentnessAccepted ||
            SystemClock.elapsedRealtime() > capture.leaseDeadlineElapsedRealtimeMs) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_DISPATCH_PROOF_EXPIRED")
        }
        val eligible = capture.clickEvents.filter { event ->
            event.optBoolean("owner_exact") && eventElapsedRealtimeMs(event) > dispatchElapsedRealtimeMs
        }
        val exact = eligible.singleOrNull()
        val eventId = exact?.optString("event_id")?.takeIf { it.isNotBlank() }
        val accepted = exact != null && eventId != null && capture.clickEventId == eventId &&
            exact.optString("event_type") == "TYPE_VIEW_CLICKED" &&
            exact.optInt("window_id", -1) == actionTarget.windowId &&
            eventElapsedRealtimeMs(exact) <= capture.leaseDeadlineElapsedRealtimeMs
        ownerActionIdentity(capture, actionTarget)
            .put("ok", accepted)
            .put("reason", if (accepted) "EXACT_OWNER_CLICK_CONFIRMED" else "EXACT_OWNER_CLICK_UNPROVEN")
            .put("ownerLeaseId", capture.ownerLeaseId)
            .put("dispatchElapsedRealtimeMs", dispatchElapsedRealtimeMs)
            .put("dispatchTargetCurrentnessAccepted", capture.dispatchTargetCurrentnessAccepted)
            .put("eligibleExactClickCount", eligible.size)
            .put("clickEventId", eventId ?: JSONObject.NULL)
            .put("clickEventType", if (exact == null) JSONObject.NULL else AccessibilityEvent.TYPE_VIEW_CLICKED)
            .put("clickEventElapsedRealtimeMs", exact?.let(::eventElapsedRealtimeMs) ?: JSONObject.NULL)
            .put("clickEventWindowId", exact?.optInt("window_id", -1) ?: JSONObject.NULL)
            .put("ownerExact", accepted)
    }

    fun validateEntryClickCapture(reqId: String, transactionId: String, currentConnectionId: String): JSONObject {
        val capture = synchronized(this) {
            activeEntryClickCapture?.takeIf { it.reqId == reqId }
                ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_NOT_ARMED")
        }
        if (capture.transactionId != transactionId) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_TRANSACTION_MISMATCH")
        }
        if (capture.connectionId != currentConnectionId) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_CONNECTION_MISMATCH")
        }
        val target = capture.ownerTarget
            ?: return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_TARGET_MISSING")
        if (SystemClock.elapsedRealtime() > capture.leaseDeadlineElapsedRealtimeMs ||
            !target.stillCurrent(currentConnectionId)) {
            return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_TARGET_STALE")
        }
        synchronized(this) {
            if (activeEntryClickCapture !== capture) {
                return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_REPLACED")
            }
        }
        return entryClickSnapshot(reqId).put("ok", true).put("reason", "TARGET_CURRENT")
            .put("runId", capture.runId).put("invocationId", capture.invocationId)
            .put("scenarioId", capture.scenarioId)
            .put("captureId", capture.captureId).put("connectionId", capture.connectionId)
            .put("ownerLeaseId", capture.ownerLeaseId).put("ownerWindowId", target.windowId)
            .put("ownerPackageName", target.packageName)
            .put("ownerPath", JSONArray(target.nodePath))
            .put("ownerDescriptorDigest", target.descriptorDigest)
            .put("sourceSnapshotId", target.sourceSnapshotId)
            .put("helperSnapshotId", target.helperSnapshotId)
            .put("baselineHierarchyDigest", target.baselineHierarchyDigest)
            .put("leaseDeadlineElapsedRealtimeMs", capture.leaseDeadlineElapsedRealtimeMs)
    }

    /** Returns an action wrapper for the exact node retained by the active observation lease. */
    internal fun navigationTargetLease(
        ownerCaptureReqId: String,
        ownerLeaseId: String,
        transactionId: String,
        connectionId: String,
        runId: String,
        invocationId: String,
        scenarioId: String,
        captureId: String,
        sourceIdentity: EntryClickSourceIdentity,
    ): NavigationActionTargetLease? {
        val capture = synchronized(this) {
            activeEntryClickCapture?.takeIf {
                it.reqId == ownerCaptureReqId && it.ownerLeaseId == ownerLeaseId &&
                    it.transactionId == transactionId && it.connectionId == connectionId &&
                    it.runId == runId && it.invocationId == invocationId && it.captureId == captureId &&
                    it.scenarioId == scenarioId && it.canonicalInvocationUriBound &&
                    it.sourceIdentity == sourceIdentity &&
                    it.dispatchUptimeMs == null && it.actionTarget == null && it.activationOwnerRelation == null &&
                    it.clickEventId == null && it.clickEvents.isEmpty() &&
                    SystemClock.elapsedRealtime() in it.armedElapsedRealtimeMs..it.leaseDeadlineElapsedRealtimeMs
            }
        } ?: return null
        val target = capture.ownerTarget ?: return null
        if (!target.stillCurrent(connectionId)) return null
        synchronized(this) {
            if (activeEntryClickCapture !== capture) return null
        }
        return target.navigationActionLease()
    }

    private fun eventElapsedRealtimeMs(event: JSONObject): Long =
        event.optLong("event_time_elapsed_realtime_ms", -1L)

    internal fun captureEntryClickEvent(
        event: AccessibilityEvent,
        currentConnectionId: String,
        callbackSourceObservation: NavigationCallbackSourceObservation? = null,
    ): String? {
        val capture = activeEntryClickCapture ?: return null
        if (SystemClock.elapsedRealtime() > capture.leaseDeadlineElapsedRealtimeMs) return null
        val receivedElapsed = SystemClock.elapsedRealtime()
        val payload = runCatching {
            val matchingCallbackObservation = if (capture.connectionId == currentConnectionId)
                matchingNavigationCallbackSourceObservation(
                    callbackSourceObservation, event, capture.navigationRequestId ?: "",
                    capture.transactionId, capture.sourceIdentity.serviceInstanceId, currentConnectionId)
            else null
            val source = when {
                callbackSourceObservation == null -> event.source
                else -> matchingCallbackObservation?.source
            }
            val sourceNodeId = if (source != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                runCatching { source.uniqueId }.getOrNull()?.takeIf { it.isNotBlank() }
            } else null
            val eventElapsedRealtime = if (callbackSourceObservation != null &&
                capture.connectionId != currentConnectionId) null else navigationClickElapsedRealtimeMs(
                callbackSourceObservation, event, capture.navigationRequestId ?: "", capture.transactionId,
                capture.sourceIdentity.serviceInstanceId, currentConnectionId,
            ) {
                eventTimeElapsedRealtimeMs(event.eventTime, SystemClock.elapsedRealtime(), SystemClock.uptimeMillis())
            } ?: -1L
            val target = capture.actionTarget ?: capture.ownerTarget?.navigationActionLease()
            val ownerExact = target?.eventSourceMatches(source, event.windowId, currentConnectionId) == true
            val sourceStatus = if (source == null) "FIELD_ABSENT" else "FIELD_PRESENT"
            val sourceData = source?.let { node ->
                val bounds = Rect()
                node.getBoundsInScreen(bounds)
                val hasBounds = bounds.width() > 0 && bounds.height() > 0
                JSONObject().apply {
                    put("resource_id", node.viewIdResourceName ?: JSONObject.NULL)
                    put("class_name", node.className?.toString() ?: JSONObject.NULL)
                    put("text", node.text?.toString() ?: JSONObject.NULL)
                    put("content_description", node.contentDescription?.toString() ?: JSONObject.NULL)
                    put("bounds", if (hasBounds) JSONObject().put("left", bounds.left).put("top", bounds.top)
                        .put("right", bounds.right).put("bottom", bounds.bottom) else JSONObject.NULL)
                    put("window_id", if (node.windowId >= 0) node.windowId else JSONObject.NULL)
                    put("enabled", node.isEnabled)
                    put("clickable", node.isClickable)
                    put("focusable", node.isFocusable)
                    put("resource_id_status", if (node.viewIdResourceName.isNullOrBlank()) "FIELD_ABSENT" else "FIELD_PRESENT")
                    put("class_name_status", if (node.className == null) "FIELD_ABSENT" else "FIELD_PRESENT")
                    put("text_status", if (node.text == null) "FIELD_ABSENT" else "FIELD_PRESENT")
                    put("content_description_status", if (node.contentDescription == null) "FIELD_ABSENT" else "FIELD_PRESENT")
                    put("bounds_status", if (hasBounds) "FIELD_PRESENT" else "FIELD_ABSENT")
                    put("window_id_status", if (node.windowId >= 0) "FIELD_PRESENT" else "FIELD_ABSENT")
                }
            }
            JSONObject().apply {
                put("event_type", "TYPE_VIEW_CLICKED")
                put("event_time_uptime_ms", event.eventTime)
                put("event_time_elapsed_realtime_ms", eventElapsedRealtime ?: JSONObject.NULL)
                put("package", event.packageName?.toString() ?: JSONObject.NULL)
                put("class_name", event.className?.toString() ?: JSONObject.NULL)
                put("text", event.text.joinToString(" ") { it?.toString().orEmpty() }.takeIf { it.isNotBlank() } ?: JSONObject.NULL)
                put("content_description", source?.contentDescription?.toString() ?: JSONObject.NULL)
                put("enabled", event.isEnabled)
                put("window_id", if (event.windowId >= 0) event.windowId else JSONObject.NULL)
                put("source", sourceData ?: JSONObject.NULL)
                put("source_status", sourceStatus)
                put("source_node_id", sourceNodeId ?: JSONObject.NULL)
                put("source_node_id_status", if (sourceNodeId == null) "FIELD_ABSENT" else "FIELD_PRESENT")
                put("source_process_id", JSONObject.NULL)
                put("source_process_id_status", "FIELD_ABSENT")
                put("parser_source", "helper_accessibility_event")
                put("raw_reference", "${capture.reqId}:${event.eventTime}:${event.packageName}")
                put("captured_elapsed_realtime_ms", receivedElapsed)
                put("capture_id", capture.captureId)
                put("connection_id", capture.connectionId)
                put("run_id", capture.runId)
                put("invocation_id", capture.invocationId)
                put("owner_lease_id", capture.ownerLeaseId)
                put("owner_relation", if (ownerExact) "EXACT_RETAINED_NODE_REFERENCE" else "OWNER_UNPROVEN")
                put("owner_exact", ownerExact)
                put("owner_window_id", target?.windowId ?: JSONObject.NULL)
                put("owner_helper_snapshot_id", target?.helperSnapshotId ?: JSONObject.NULL)
                put("owner_descriptor_digest", target?.descriptorDigest ?: JSONObject.NULL)
                put("owner_action_path", target?.let { JSONArray(it.nodePath) } ?: JSONObject.NULL)
                put("owner_authorization_path", capture.ownerTarget?.let { JSONArray(it.nodePath) } ?: JSONObject.NULL)
                put("activation_owner_relation", capture.activationOwnerRelation?.toJson() ?: JSONObject.NULL)
                put("dispatch_uptime_ms", capture.dispatchUptimeMs ?: JSONObject.NULL)
                put("dispatch_target_currentness_accepted", capture.dispatchTargetCurrentnessAccepted)
                put("dispatch_correlation_status", if (capture.dispatchUptimeMs == null) "AWAITING_HOST_MARK" else "HOST_MARKED")
                put("cursor_event_sequence", capture.cursorEventSequence)
            }
        }.getOrElse { error ->
            JSONObject().put("event_type", "TYPE_VIEW_CLICKED")
                .put("event_time_uptime_ms", event.eventTime)
                .put("event_time_elapsed_realtime_ms", JSONObject.NULL)
                .put("package", event.packageName?.toString() ?: JSONObject.NULL)
                .put("source_status", "FIELD_PARSE_FAILED")
                .put("source_parse_error", error.javaClass.simpleName)
                .put("parser_source", "helper_accessibility_event")
                .put("raw_reference", "${capture.reqId}:${event.eventTime}:${event.packageName}")
                .put("captured_elapsed_realtime_ms", receivedElapsed)
                .put("capture_id", capture.captureId)
                .put("connection_id", capture.connectionId)
                .put("run_id", capture.runId)
                .put("invocation_id", capture.invocationId)
                .put("owner_lease_id", capture.ownerLeaseId)
                .put("owner_relation", "OWNER_UNPROVEN")
                .put("owner_exact", false)
                .put("dispatch_uptime_ms", capture.dispatchUptimeMs ?: JSONObject.NULL)
                .put("cursor_event_sequence", capture.cursorEventSequence)
        }
        val eventId = emit("ENTRY_CLICK_OBSERVED", capture.reqId, payload) ?: return null
        synchronized(this) {
            val current = activeEntryClickCapture ?: return null
            if (current.captureId != capture.captureId) return null
            payload.put("event_id", eventId)
            current.clickEvents.add(payload)
            val dispatch = current.dispatchUptimeMs
            if (dispatch != null && payload.optBoolean("owner_exact") &&
                eventElapsedRealtimeMs(payload) > dispatch) {
                val eligible = current.clickEvents.filter { it.optBoolean("owner_exact") &&
                    eventElapsedRealtimeMs(it) > dispatch }
                if (eligible.size == 1) {
                    current.clickEventId = eventId
                    current.clickEventCapturedElapsedRealtimeMs = receivedElapsed
                } else {
                    current.clickEventId = null
                    current.clickEventCapturedElapsedRealtimeMs = null
                }
            }
        }
        return eventId
    }

    fun captureEntryClickPostActionObservation(
        clickEventId: String,
        connectionId: String,
        rootWindowId: Int?,
        focusNodeId: String?,
        focusNodePath: List<Int>?,
        focusWindowId: Int?,
        accessibilityFocused: Boolean,
        currentHierarchy: JSONObject?,
    ): Boolean {
        val capturedElapsed = SystemClock.elapsedRealtime()
        val capture = synchronized(this) {
            activeEntryClickCapture?.takeIf {
                it.connectionId == connectionId && it.clickEventId == clickEventId &&
                    it.dispatchUptimeMs != null && it.clickEventCapturedElapsedRealtimeMs != null &&
                    capturedElapsed > it.clickEventCapturedElapsedRealtimeMs!! &&
                    capturedElapsed <= it.leaseDeadlineElapsedRealtimeMs && !it.postActionObservationEmitted
            }?.also { it.postActionObservationEmitted = true }
        } ?: return false
        val currentCaptureId = UUID.randomUUID().toString()
        val payload = JSONObject().apply {
            put("capture_id", capture.captureId)
            put("connection_id", capture.connectionId)
            put("run_id", capture.runId)
            put("invocation_id", capture.invocationId)
            put("owner_lease_id", capture.ownerLeaseId)
            put("owner_window_id", capture.ownerTarget?.windowId ?: JSONObject.NULL)
            val actionTarget = capture.actionTarget ?: capture.ownerTarget?.navigationActionLease()
            put("owner_helper_snapshot_id", actionTarget?.helperSnapshotId ?: JSONObject.NULL)
            put("owner_descriptor_digest", actionTarget?.descriptorDigest ?: JSONObject.NULL)
            put("owner_action_path", actionTarget?.let { JSONArray(it.nodePath) } ?: JSONObject.NULL)
            put("owner_authorization_path", capture.ownerTarget?.let { JSONArray(it.nodePath) } ?: JSONObject.NULL)
            put("activation_owner_relation", capture.activationOwnerRelation?.toJson() ?: JSONObject.NULL)
            put("source_click_event_id", clickEventId)
            put("dispatch_uptime_ms", capture.dispatchUptimeMs)
            put("source_click_captured_elapsed_realtime_ms", capture.clickEventCapturedElapsedRealtimeMs)
            put("captured_elapsed_realtime_ms", capturedElapsed)
            put("current_capture_id", currentCaptureId)
            put("root_window_id", rootWindowId ?: JSONObject.NULL)
            put("focus_node_id", focusNodeId ?: JSONObject.NULL)
            put("focus_node_path", focusNodePath?.let { JSONArray(it) } ?: JSONObject.NULL)
            put("focus_window_id", focusWindowId ?: JSONObject.NULL)
            put("accessibility_focused", accessibilityFocused)
            put("current_hierarchy", currentHierarchy ?: JSONObject.NULL)
            put("current_hierarchy_status", if (currentHierarchy == null) "FIELD_ABSENT" else "FIELD_PRESENT")
        }
        return emit("ENTRY_CLICK_POST_ACTION_OBSERVED", capture.reqId, payload) != null
    }

    internal fun eventTimeElapsedRealtimeMs(eventTimeUptimeMs: Long, elapsedRealtimeMs: Long,
        uptimeMs: Long): Long? {
        if (eventTimeUptimeMs < 0L || elapsedRealtimeMs < 0L || uptimeMs < 0L || uptimeMs > elapsedRealtimeMs) return null
        return runCatching { Math.addExact(eventTimeUptimeMs, elapsedRealtimeMs - uptimeMs) }.getOrNull()
    }

    fun disarmEntryClickCapture(reqId: String, afterEventSequence: Long? = null): JSONObject {
        synchronized(this) {
            val capture = activeEntryClickCapture
            if (capture != null && capture.reqId != reqId) {
                return JSONObject().put("ok", false).put("reason", "ENTRY_CLICK_CAPTURE_REQUEST_MISMATCH")
            }
            if (capture?.reqId == reqId) activeEntryClickCapture = null
        }
        val snapshot = entryClickSnapshot(reqId, afterEventSequence).put("ok", true).put("reason", "DISARMED")
        synchronized(this) {
            correlationByReqId.remove(reqId)
            eventsByReqId.remove(reqId)
        }
        return snapshot
    }

    fun entryClickSnapshot(reqId: String, afterEventSequence: Long? = null): JSONObject {
        val events = synchronized(eventsByReqId.getOrPut(reqId) { mutableListOf() }) {
            JSONArray().apply {
                eventsByReqId[reqId]?.forEach { item ->
                    val sequence = item.optLong("sequence", -1L)
                    if (afterEventSequence == null || sequence > afterEventSequence) put(JSONObject(item.toString()))
                }
            }
        }
        val capture = activeEntryClickCapture?.takeIf { it.reqId == reqId }
        return JSONObject().apply {
            put("reqId", reqId)
            put("transactionId", correlationByReqId[reqId]?.optString("transaction_id") ?: "")
            put("captureId", capture?.captureId ?: JSONObject.NULL)
            put("connectionId", capture?.connectionId ?: JSONObject.NULL)
            capture?.sourceIdentity?.let { source ->
                put("sourceCaptureRequestId", source.requestId)
                put("sourceProcessEpoch", source.processEpoch)
                put("sourceGeneration", source.generation)
                put("sourceServiceInstanceId", source.serviceInstanceId)
                put("sourceCaptureSequence", source.captureSequence)
                put("sourceRootDigest", source.rootDigest)
                put("sourceCandidateDigest", source.candidateDigest)
                put("sourceCaptureKey", source.captureKey)
                put("sourceConnectionEpoch", source.connectionEpoch)
                put("sourceBootEpoch", source.bootEpoch)
                put("ownerSourceNodeId", source.ownerSourceNodeId)
                put("ownerSourceNodeIdStatus", source.ownerSourceNodeIdStatus)
            }
            put("cursorEventSequence", capture?.cursorEventSequence ?: JSONObject.NULL)
            put("dispatchUptimeMs", capture?.dispatchUptimeMs ?: JSONObject.NULL)
            put("armedElapsedRealtimeMs", capture?.armedElapsedRealtimeMs ?: JSONObject.NULL)
            put("invocationUriBound", capture?.canonicalInvocationUriBound ?: false)
            put("active", capture != null)
            put("evidenceEvents", events)
        }
    }

    fun requestedTarget(intent: Intent?): JSONObject {
        return JSONObject().apply {
            put("action", intent?.action ?: JSONObject.NULL)
            put("direction", intent?.getStringExtra("direction") ?: JSONObject.NULL)
            put("targetName", intent?.getStringExtra("targetName") ?: JSONObject.NULL)
            put("targetType", intent?.getStringExtra("targetType") ?: JSONObject.NULL)
            put("targetId", intent?.getStringExtra("targetId") ?: JSONObject.NULL)
            put("targetText", intent?.getStringExtra("targetText") ?: JSONObject.NULL)
            put("requestedBounds", intent?.getStringExtra("bounds") ?: JSONObject.NULL)
        }
    }

    fun attach(result: JSONObject, reqId: String): JSONObject {
        val correlation = correlationByReqId[reqId] ?: return result
        val events = synchronized(eventsByReqId.getOrPut(reqId) { mutableListOf() }) {
            JSONArray().apply { eventsByReqId[reqId]?.forEach { put(JSONObject(it.toString())) } }
        }
        Log.i(TAG, "[EVIDENCE][helper_response] requestId=$reqId transactionId=${correlation.optString("transaction_id")} SMART_NAV_RESULT_evidenceEvents=${events.length()}")
        return result
            .put("evidenceCorrelation", JSONObject(correlation.toString()))
            .put("evidenceEvents", events)
    }

    fun emit(eventType: String, reqId: String, payload: JSONObject = JSONObject()): String? {
        val correlation = correlationByReqId[reqId] ?: return null
        return runCatching {
            val sequence = eventSequence.incrementAndGet()
            val event = JSONObject().apply {
                put("schemaVersion", "evidence-helper-v1")
                put("eventId", "helper_${reqId}_$sequence")
                put("sequence", sequence)
                put("eventType", eventType)
                put("timestamp", System.currentTimeMillis())
                put("reqId", reqId)
                put("correlation", JSONObject(correlation.toString()))
                put("payload", payload)
            }
            synchronized(eventsByReqId.getOrPut(reqId) { mutableListOf() }) {
                eventsByReqId[reqId]?.add(JSONObject(event.toString()))
            }
            emitTransportEvent(event, correlation)
            event.optString("eventId")
        }.getOrNull()
    }

    /**
     * Primary Helper-to-Runner transport.  Keep each record below logcat's
     * practical line limit; the full event remains available in the in-memory
     * snapshot for backward compatibility.
     */
    private fun emitTransportEvent(event: JSONObject, correlation: JSONObject) {
        val transport = JSONObject().apply {
            put("requestId", event.optString("reqId"))
            put("reqId", event.optString("reqId"))
            put("transactionId", correlation.optString("transaction_id"))
            put("eventId", event.optString("eventId"))
            put("eventType", event.optString("eventType"))
            put("timestamp", event.optLong("timestamp"))
            put("correlation", JSONObject(correlation.toString()))
            put("payload", boundValue(event.opt("payload"), 0))
            put("chunkCount", 1)
        }
        // The bounded payload normally fits.  Preserve required correlation and
        // event identity even if an unexpected value still makes it too large.
        if (transport.toString().length > MAX_EVENT_LOG_CHARS) {
            transport.put("payload", JSONObject().put("transportTruncated", true))
        }
        val serialized = transport.toString()
        Log.i(
            TAG,
            "[EVIDENCE][event_emit] requestId=${transport.optString("requestId")} " +
                "transactionId=${transport.optString("transactionId")} eventId=${transport.optString("eventId")} " +
                "eventType=${transport.optString("eventType")} serializedLength=${serialized.length} chunkCount=1"
        )
        Log.i(TAG, "$EVENT_LOG_PREFIX $serialized")
    }

    private fun boundValue(value: Any?, depth: Int): Any {
        if (depth >= 5) return JSONObject.NULL
        return when (value) {
            is JSONObject -> JSONObject().apply {
                val keys = value.keys()
                var kept = 0
                while (keys.hasNext() && kept < 32) {
                    val key = keys.next()
                    if (key == "children") {
                        put("childrenOmitted", true)
                    } else {
                        put(key, boundValue(value.opt(key), depth + 1))
                    }
                    kept += 1
                }
                if (keys.hasNext()) put("fieldsOmitted", true)
            }
            is JSONArray -> JSONArray().apply {
                val limit = minOf(value.length(), 8)
                for (index in 0 until limit) put(boundValue(value.opt(index), depth + 1))
                if (value.length() > limit) put(JSONObject().put("itemsOmitted", value.length() - limit))
            }
            is String -> if (value.length <= MAX_TRANSPORT_TEXT_CHARS) value else value.take(MAX_TRANSPORT_TEXT_CHARS)
            else -> value ?: JSONObject.NULL
        }
    }

    fun clear(reqId: String) {
        correlationByReqId.remove(reqId)
        eventsByReqId.remove(reqId)
    }

    fun snapshotAndClear(reqId: String): JSONObject {
        val result = JSONObject().apply {
            put("reqId", reqId)
            put("evidenceEvents", synchronized(eventsByReqId[reqId] ?: mutableListOf<JSONObject>()) {
                JSONArray().apply { eventsByReqId[reqId]?.forEach { put(JSONObject(it.toString())) } }
            })
        }
        val eventTypes = (0 until result.getJSONArray("evidenceEvents").length())
            .map { index -> result.getJSONArray("evidenceEvents").optJSONObject(index)?.optString("eventType").orEmpty() }
            .filter { it.isNotBlank() }
        Log.i(TAG, "[EVIDENCE][helper_buffer] lookupKey=$reqId eventCount=${eventTypes.size} eventTypes=$eventTypes")
        // Retain correlation through the final 1000ms delayed observation.  This
        // never changes navigation and lets the primary per-event log transport
        // carry late records even when the legacy snapshot is requested early.
        cleanupHandler.postDelayed({ clear(reqId) }, 1500L)
        return result
    }
}
