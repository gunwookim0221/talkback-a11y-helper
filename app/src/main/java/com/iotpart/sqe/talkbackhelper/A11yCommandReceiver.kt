package com.iotpart.sqe.talkbackhelper

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo

class A11yCommandReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "A11Y_HELPER"
        private const val VERSION = "1.2.8"
        private const val ACTION_GET_FOCUS = "com.iotpart.sqe.talkbackhelper.GET_FOCUS"
        private const val ACTION_FOCUS_RESULT = "com.iotpart.sqe.talkbackhelper.FOCUS_RESULT"
        private const val ACTION_DUMP_TREE = "com.iotpart.sqe.talkbackhelper.DUMP_TREE"
        private const val ACTION_DUMP_HIERARCHY = "com.iotpart.sqe.talkbackhelper.DUMP_HIERARCHY"
        private const val ACTION_FOCUS_TARGET = "com.iotpart.sqe.talkbackhelper.FOCUS_TARGET"
        private const val ACTION_FOCUS_IN_BOUNDS = "com.iotpart.sqe.talkbackhelper.FOCUS_IN_BOUNDS"
        private const val ACTION_TARGET_FOCUS_COMMIT = "com.iotpart.sqe.talkbackhelper.TARGET_FOCUS_COMMIT"
        private const val ACTION_CLICK_TARGET = "com.iotpart.sqe.talkbackhelper.CLICK_TARGET"
        private const val ACTION_TOUCH_BOUNDS_CENTER_TARGET = "com.iotpart.sqe.talkbackhelper.TOUCH_BOUNDS_CENTER_TARGET"
        private const val ACTION_CHECK_TARGET = "com.iotpart.sqe.talkbackhelper.CHECK_TARGET"
        private const val ACTION_NEXT = "com.iotpart.sqe.talkbackhelper.NEXT"
        private const val ACTION_PREV = "com.iotpart.sqe.talkbackhelper.PREV"
        private const val ACTION_SMART_NEXT = "com.iotpart.sqe.talkbackhelper.SMART_NEXT"
        private const val ACTION_CLICK_FOCUSED = "com.iotpart.sqe.talkbackhelper.CLICK_FOCUSED"
        private const val ACTION_SCROLL = "com.iotpart.sqe.talkbackhelper.SCROLL"
        private const val ACTION_SET_TEXT = "com.iotpart.sqe.talkbackhelper.SET_TEXT"
        private const val ACTION_SET_SYSTEM_LANGUAGE = "com.iotpart.sqe.talkbackhelper.SET_SYSTEM_LANGUAGE"
        internal const val HELPER_SERVICE_UNAVAILABLE_STATUS = "HELPER_SERVICE_UNAVAILABLE"
        private const val ACTION_PING = "com.iotpart.sqe.talkbackhelper.PING"
        private const val ACTION_COMMAND = "com.iotpart.sqe.talkbackhelper.ACTION_COMMAND"
        private const val ACTION_EVIDENCE_EVENTS = "com.iotpart.sqe.talkbackhelper.EVIDENCE_EVENTS"
        private const val EXTRA_TARGET_NAME = "targetName"
        private const val EXTRA_TARGET_TYPE = "targetType"
        private const val EXTRA_TARGET_INDEX = "targetIndex"
        private const val EXTRA_CLASS_NAME = "className"
        private const val EXTRA_CLICKABLE = "clickable"
        private const val EXTRA_FOCUSABLE = "focusable"
        private const val EXTRA_TARGET_TEXT = "targetText"
        private const val EXTRA_TARGET_ID = "targetId"
        private const val EXTRA_IS_LONG_CLICK = "isLongClick"
        private const val EXTRA_FORWARD = "forward"
        private const val EXTRA_DIRECTION = "direction"
        private const val EXTRA_PREFER_TREE_SEARCH = "preferTreeSearch"
        private const val EXTRA_INCLUDE_SCROLL_CAPABILITIES = "includeScrollCapabilities"
        private const val EXTRA_INCLUDE_DEVICE_COLLECTION = "includeDeviceCollection"
        private const val EXTRA_DEVICE_LIST_NORMALIZATION = "deviceListNormalization"
        private const val EXTRA_TEXT = "text"
        private const val EXTRA_LOCALE = "locale"
        private const val EXTRA_CURRENT_LOCALE = "currentLocale"
        private const val EXTRA_BOUNDS = "bounds"
        private const val EXTRA_TARGET_LABEL = "targetLabel"
        private const val EXTRA_PREFER_EMPTY_STATE = "preferEmptyState"
        private const val EXTRA_EXCLUDE_TOP_CHROME = "excludeTopChrome"
        private const val EXTRA_EXCLUDE_BOTTOM_NAV = "excludeBottomNav"
        private const val EXTRA_REQ_ID = "reqId"
        private const val EXTRA_COMMAND = "command"
        private const val DEFAULT_REQ_ID = "none"
    }

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        val reqId = parseReqId(intent)
        A11yEvidence.capture(intent, reqId)
        A11yEvidence.emit(
            "ACTION_EXECUTION_STARTED",
            reqId,
            org.json.JSONObject().put("action", action)
        )
        A11yEvidence.emit("TARGET_REQUESTED", reqId, A11yEvidence.requestedTarget(intent))
        if (action == ACTION_SMART_NEXT) {
            logSmartNextDiag(reqId, "receiver_onReceive", "action=$action receiver_version=$VERSION")
        }
        Log.i(
            TAG,
            "[SMART_NEXT][trace_enter] stage='receiver_onReceive' action='$action'"
        )
        when (action) {
            ACTION_GET_FOCUS -> handleGetFocus(context, intent)
            ACTION_DUMP_TREE -> {
                Log.i(TAG, "[DUMP_TREE_ACTION][entry] action='$ACTION_DUMP_TREE'")
                handleDumpTree(intent)
            }
            ACTION_DUMP_HIERARCHY -> handleDumpHierarchy(intent)
            ACTION_FOCUS_TARGET -> handleTargetAction(intent, AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            ACTION_FOCUS_IN_BOUNDS -> handleFocusInBounds(intent)
            ACTION_TARGET_FOCUS_COMMIT -> handleTargetFocusCommit(intent)
            ACTION_CLICK_TARGET -> {
                val actionType = if (intent.getBooleanExtra(EXTRA_IS_LONG_CLICK, false)) {
                    AccessibilityNodeInfo.ACTION_LONG_CLICK
                } else {
                    AccessibilityNodeInfo.ACTION_CLICK
                }
                handleTargetAction(intent, actionType)
            }
            ACTION_CHECK_TARGET -> handleCheckTarget(intent)
            ACTION_TOUCH_BOUNDS_CENTER_TARGET -> handleTargetBoundsCenterTap(intent)
            ACTION_NEXT -> handleMoveFocus(intent, true)
            ACTION_PREV -> handleMoveFocus(intent, false)
            ACTION_SMART_NEXT -> {
                Log.i(TAG, "[SMART_NEXT_ACTION][entry] action='$ACTION_SMART_NEXT'")
                handleSmartNext(context, intent)
            }
            ACTION_CLICK_FOCUSED -> handleClickFocused(intent)
            ACTION_SCROLL -> handleScroll(intent)
            ACTION_SET_TEXT -> handleSetText(intent)
            ACTION_SET_SYSTEM_LANGUAGE -> handleSetSystemLanguage(intent)
            ACTION_PING -> handlePing(intent)
            ACTION_COMMAND -> handleExternalCommand(context, intent)
            ACTION_EVIDENCE_EVENTS -> handleEvidenceEvents(intent)
            else -> Unit
        }
    }

    private fun handleGetFocus(context: Context, intent: Intent) {
        val reqId = parseReqId(intent)
        A11yHelperService.instance?.refreshCurrentFocusSnapshot()
        A11yStateStore.ensureFallbackJson()
        val saveFile = intent.getBooleanExtra("saveFile", false)
        if (saveFile) {
            A11yStateStore.saveToExternalFile(context)
        }

        val jsonObj = runCatching { org.json.JSONObject(A11yStateStore.lastFocusTransportJson) }
            .getOrDefault(org.json.JSONObject())
            .apply { put("reqId", reqId) }
        val json = jsonObj.toString()
        Log.i(TAG, "FOCUS_RESULT $json")

        val reply = Intent(ACTION_FOCUS_RESULT).apply {
            setPackage(context.packageName)
            putExtra("json", json)
            putExtra("updatedAt", A11yStateStore.lastUpdatedAt)
        }
        context.sendBroadcast(reply)
    }

    private fun handleDumpTree(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logDumpTreeFailure(reqId, "Accessibility Service is null or not running")
            return
        }
        executeDumpTreeSafely(
            reqId = reqId,
            dumpTree = {
                service.dumpTree(
                    reqId = reqId,
                    includeScrollCapabilities = intent.getBooleanExtra(EXTRA_INCLUDE_SCROLL_CAPABILITIES, false),
                    includeDeviceCollection = intent.getBooleanExtra(EXTRA_INCLUDE_DEVICE_COLLECTION, false)
                )
            },
            reportFailure = { reason -> logDumpTreeFailure(reqId, reason) }
        )
    }

    private fun handleDumpHierarchy(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logHierarchyFailure(reqId, "SERVICE_UNAVAILABLE", "Accessibility Service is not running")
            Log.i(TAG, "DUMP_HIERARCHY_END $reqId")
            return
        }
        try {
            val payload = service.dumpHierarchy(reqId).toString()
            if (payload.toByteArray(Charsets.UTF_8).size > 750_000) {
                logHierarchyFailure(reqId, "PAYLOAD_TOO_LARGE", "Hierarchy snapshot exceeds the bounded transport size")
                return
            }
            A11yResultTransport.encode(
                "DUMP_HIERARCHY_RESULT",
                reqId,
                payload,
                chunkBytes = A11yResultTransport.HIERARCHY_CHUNK_BYTES,
            )
                .forEach { Log.i(TAG, it) }
        } catch (error: Exception) {
            Log.e(TAG, "[DUMP_HIERARCHY] failed req_id='$reqId'", error)
            logHierarchyFailure(reqId, "SERIALIZATION_ERROR", "${error.javaClass.simpleName}: ${error.message.orEmpty()}")
        } finally {
            Log.i(TAG, "DUMP_HIERARCHY_END $reqId")
        }
    }

    private fun logHierarchyFailure(reqId: String, reason: String, message: String) {
        val payload = org.json.JSONObject()
            .put("reqId", reqId)
            .put("success", false)
            .put("reason", reason)
            .put("message", message)
            .toString()
        Log.w(TAG, "DUMP_HIERARCHY_RESULT $reqId $payload")
    }

    private fun handleSetSystemLanguage(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure(
                "SYSTEM_LANGUAGE_RESULT",
                reqId,
                HELPER_SERVICE_UNAVAILABLE_STATUS,
                status = HELPER_SERVICE_UNAVAILABLE_STATUS,
            )
            return
        }

        val locale = intent.getStringExtra(EXTRA_LOCALE)?.trim().orEmpty()
        val currentLocale = intent.getStringExtra(EXTRA_CURRENT_LOCALE)?.trim()
        service.setSystemLanguage(locale, currentLocale, reqId)
    }

    internal fun executeDumpTreeSafely(
        reqId: String,
        dumpTree: () -> Unit,
        reportFailure: (String) -> Unit,
        logError: (String, Throwable) -> Unit = { message, error -> Log.e(TAG, message, error) }
    ): Boolean {
        return try {
            dumpTree()
            true
        } catch (error: Exception) {
            val reason = "Traversal analysis failed: ${error.javaClass.simpleName}: ${error.message ?: "no message"}"
            logError("[DUMP_TREE] failed req_id='$reqId'", error)
            reportFailure(reason)
            false
        }
    }

    private fun handleTargetAction(intent: Intent, action: Int) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("TARGET_ACTION_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }

        val query = parseQuery(intent, reqId) ?: return
        val actionName = when (action) {
            AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS -> "FOCUS_TARGET"
            AccessibilityNodeInfo.ACTION_CLICK, AccessibilityNodeInfo.ACTION_LONG_CLICK -> "CLICK_TARGET"
            else -> "UNKNOWN"
        }
        val longClick = action == AccessibilityNodeInfo.ACTION_LONG_CLICK
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][recv] reqId=$reqId action=$actionName targetName='${query.targetName}' targetType='${query.targetType}' targetIndex=${query.targetIndex} longClick=$longClick"
        )
        service.performTargetAction(query, action, reqId)
    }

    private fun handleCheckTarget(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("CHECK_TARGET_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }

        val query = parseQuery(intent, reqId) ?: return
        service.checkTarget(query, reqId)
    }

    private fun handleTargetBoundsCenterTap(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("TARGET_ACTION_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }

        val query = parseQuery(intent, reqId) ?: return
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][recv] reqId=$reqId action=TOUCH_BOUNDS_CENTER_TARGET targetName='${query.targetName}' targetType='${query.targetType}' targetIndex=${query.targetIndex}"
        )
        service.performTargetBoundsCenterTap(query, reqId)
    }

    private fun handleEvidenceEvents(intent: Intent) {
        val reqId = parseReqId(intent)
        val result = A11yEvidence.snapshotAndClear(reqId)
        Log.i(TAG, "[EVIDENCE][helper_response] requestId=$reqId EVIDENCE_EVENTS_snapshot=${result.optJSONArray("evidenceEvents")?.length() ?: 0}")
        A11yResultTransport.encode("EVIDENCE_EVENTS_RESULT", reqId, result.toString()).forEach { Log.i(TAG, it) }
    }

    private fun handleFocusInBounds(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("TARGET_ACTION_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }
        val bounds = intent.getStringExtra(EXTRA_BOUNDS)?.trim().orEmpty()
        val preferEmptyState = intent.getBooleanExtra(EXTRA_PREFER_EMPTY_STATE, true)
        val excludeTopChrome = intent.getBooleanExtra(EXTRA_EXCLUDE_TOP_CHROME, true)
        val excludeBottomNav = intent.getBooleanExtra(EXTRA_EXCLUDE_BOTTOM_NAV, true)
        Log.d(
            TAG,
            "[DEBUG][FOCUS_IN_BOUNDS][recv] reqId=$reqId bounds='$bounds' preferEmptyState=$preferEmptyState excludeTopChrome=$excludeTopChrome excludeBottomNav=$excludeBottomNav"
        )
        dispatchFocusCommand(service, "FOCUS_IN_BOUNDS", reqId) {
                service.performFocusInBounds(
                    boundsString = bounds,
                    preferEmptyState = preferEmptyState,
                    excludeTopChrome = excludeTopChrome,
                    excludeBottomNav = excludeBottomNav,
                    reqId = reqId,
                    emitResult = false
                )
        }
    }

    private fun handleTargetFocusCommit(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("TARGET_ACTION_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }
        val descriptor = TargetFocusMatcher.Descriptor(
            bounds = intent.getStringExtra(EXTRA_BOUNDS)?.trim().orEmpty(),
            resourceId = intent.getStringExtra(EXTRA_TARGET_ID)?.trim().orEmpty(),
            label = intent.getStringExtra(EXTRA_TARGET_LABEL)?.trim().orEmpty(),
            className = intent.getStringExtra(EXTRA_CLASS_NAME)?.trim().orEmpty()
        )
        dispatchFocusCommand(service, "TARGET_FOCUS_COMMIT", reqId) {
            service.performTargetFocusCommit(descriptor, reqId, emitResult = false)
        }
    }

    private fun dispatchFocusCommand(service: A11yHelperService, command: String, reqId: String,
                                     work: () -> org.json.JSONObject) {
        val accepted = service.focusCommandDispatcher.submit(reqId, work, onResult = { result ->
            A11yResultTransport.encode("TARGET_ACTION_RESULT", reqId, result.toString()).forEach { Log.i(TAG, it) }
            Log.i(TAG, "[COMMAND_TRANSPORT] command=$command req_id=$reqId stage=result_emitted")
        }, onFailure = { error ->
            Log.e(TAG, "[COMMAND_TRANSPORT] command=$command req_id=$reqId stage=work_failed", error)
            logFailure("TARGET_ACTION_RESULT", reqId, "${command.lowercase()}_exception:${error.javaClass.simpleName}")
        })
        Log.i(TAG, "[COMMAND_TRANSPORT] command=$command req_id=$reqId stage=receiver_ack accepted=$accepted pending_broadcast=false")
    }



    private fun handleMoveFocus(intent: Intent, forward: Boolean) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("NAV_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }

        service.moveFocus(forward, reqId)
    }

    private fun handleExternalCommand(context: Context, intent: Intent) {
        val reqId = parseReqId(intent)
        when (intent.getStringExtra(EXTRA_COMMAND)?.trim()?.lowercase()) {
            "reset" -> {
                A11yNavigator.resetFocusHistory()
                val result = org.json.JSONObject().apply {
                    put("timestamp", System.currentTimeMillis())
                    put("reqId", reqId)
                    put("success", true)
                    put("status", "reset")
                }
                Log.i(TAG, "COMMAND_RESULT $result")
                context.sendBroadcast(Intent("COMMAND_RESULT").apply {
                    setPackage(context.packageName)
                    putExtra("json", result.toString())
                })
            }
            else -> logFailure("COMMAND_RESULT", reqId, "Unsupported command")
        }
    }

    private fun handleSmartNext(context: Context, intent: Intent) {
        val reqId = parseReqId(intent)
        logSmartNextDiag(reqId, "receiver_handleSmartNext", "receiver_version=$VERSION")
        Log.i(
            TAG,
            "[SMART_NEXT][trace_enter] stage='receiver_handleSmartNext' req_id='$reqId'"
        )
        val service = A11yHelperService.instance
        if (service == null) {
            logSmartNextDiag(reqId, "final", "status=failed detail=service_unavailable")
            Log.i(
                TAG,
                "[SMART_NEXT][final] success=false status='failed' detail='service_unavailable' requested_target_view_id='' resolved_focus_view_id=''"
            )
            logFailure("SMART_NAV_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }
        // The accessibility service is already bound and owns this work.
        // Keeping goAsync pending until navigation ends makes am broadcast wait
        // and caused the observed 30s ADB timeouts / ~60s broadcast ANR kills.
        SmartNextPerf.request(reqId, intent.getBooleanExtra("profileSmartNext", false),
            if (intent.getBooleanExtra("profileRelationships", false)) context.filesDir else null)
        val accepted = service.smartNextDispatcher.submit(reqId, onResult = { result ->
            try {
                val status = result.optString("status", "unknown")
                val detail = result.optString("detail", "unknown")
                Log.i(
                    TAG,
                    "[SMART_NEXT][trace_enter] stage='before_final_response' status='$status' detail='$detail'"
                )
                A11yEvidence.emit(
                    "HELPER_ACK_SENT",
                    reqId,
                    org.json.JSONObject().put("status", status).put("detail", detail)
                )
                SmartNextPerf.measure("evidence_attach") { A11yEvidence.attach(result, reqId) }
                // Emit exactly one final payload per reqId, after evidence attachment.
                // A pre-attachment result can race the collector or duplicate chunks.
                val encodedResult = SmartNextPerf.measure("serialize") {
                    A11yResultTransport.encode("SMART_NAV_RESULT", reqId, result.toString())
                }
                SmartNextPerf.mark("T11_result_serialized")
                SmartNextPerf.measure("emit") { encodedResult.forEach { Log.i(TAG, it) } }
                SmartNextPerf.mark("T12_result_emitted")
                val reply = Intent("SMART_NAV_RESULT").apply {
                    setPackage(context.packageName)
                    putExtra("json", result.toString())
                }
                runCatching { context.sendBroadcast(reply) }
                    .onFailure { Log.w(TAG, "[SMART_NEXT] optional reply broadcast failed reqId=$reqId", it) }
                Log.i(
                    TAG,
                    "[SMART_NEXT][trace_enter] stage='after_final_response' status='$status' detail='$detail'"
                )
                logSmartNextDiag(reqId, "receiver_broadcast_sent", "status=$status detail=$detail")
            } catch (t: Throwable) {
                Log.e(TAG, "[SMART_NEXT] result emission failed reqId=$reqId", t)
            }
        }, onFailure = { t ->
                Log.e(TAG, "[SMART_NEXT] async execution failed reqId=$reqId", t)
                logSmartNextDiag(
                    reqId,
                    "exception",
                    "status=failed detail=async_exception exception_class=${t.javaClass.simpleName} exception_message=${t.message.orEmpty()}"
                )
                Log.i(
                    TAG,
                    "[SMART_NEXT][final] success=false status='failed' detail='async_exception:${t.javaClass.simpleName}' requested_target_view_id='' resolved_focus_view_id=''"
                )
                logFailure("SMART_NAV_RESULT", reqId, "Smart next async execution failed: ${t.message}")
                A11yEvidence.emit(
                    "HELPER_ACK_SENT",
                    reqId,
                    org.json.JSONObject().put("status", "failed").put("detail", "async_exception")
                )
        })
        if (!accepted) SmartNextPerf.cancel(reqId)
        logSmartNextDiag(reqId, "receiver_ack", "accepted=$accepted pending_broadcast=false")
    }

    private fun handleClickFocused(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("TARGET_ACTION_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }

        service.clickFocusedNode(reqId)
    }

    private fun parseReqId(intent: Intent): String {
        return intent.getStringExtra(EXTRA_REQ_ID)?.trim().takeUnless { it.isNullOrBlank() } ?: DEFAULT_REQ_ID
    }

    private fun logSmartNextDiag(reqId: String, stage: String, detail: String) {
        Log.i(TAG, "[SMART_NEXT_DIAG] req_id=$reqId stage=$stage $detail")
    }

    private fun parseQuery(intent: Intent, reqId: String): A11yTargetFinder.TargetQuery? {
        val targetName = intent.getStringExtra(EXTRA_TARGET_NAME)?.trim().orEmpty()
        val targetType = intent.getStringExtra(EXTRA_TARGET_TYPE)?.trim().orEmpty().lowercase()
        val targetIndex = intent.getIntExtra(EXTRA_TARGET_INDEX, 0)
        val className = intent.getStringExtra(EXTRA_CLASS_NAME)?.trim().takeUnless { it.isNullOrBlank() }
        val clickable = parseBooleanExtra(intent.getStringExtra(EXTRA_CLICKABLE))
        val focusable = parseBooleanExtra(intent.getStringExtra(EXTRA_FOCUSABLE))
        val targetText = intent.getStringExtra(EXTRA_TARGET_TEXT)?.trim().takeUnless { it.isNullOrBlank() }
        val targetId = intent.getStringExtra(EXTRA_TARGET_ID)?.trim().takeUnless { it.isNullOrBlank() }

        if (targetName.isNotBlank() && targetType !in setOf("t", "b", "r", "a")) {
            logFailure("TARGET_ACTION_RESULT", reqId, "targetType must be one of t,b,r,a")
            return null
        }

        if (targetName.isBlank() && targetType.isNotBlank()) {
            logFailure("TARGET_ACTION_RESULT", reqId, "targetType requires non-empty targetName")
            return null
        }

        if (targetIndex < 0) {
            logFailure("TARGET_ACTION_RESULT", reqId, "targetIndex must be >= 0")
            return null
        }

        if (targetName.isBlank() && className == null && clickable == null && focusable == null && targetText == null && targetId == null) {
            logFailure("TARGET_ACTION_RESULT", reqId, "At least one target condition is required")
            return null
        }

        return A11yTargetFinder.TargetQuery(
            targetName = targetName,
            targetType = targetType,
            targetIndex = targetIndex,
            className = className,
            clickable = clickable,
            focusable = focusable,
            targetText = targetText,
            targetId = targetId
        )
    }

    private fun parseBooleanExtra(value: String?): Boolean? {
        return when (value?.trim()?.lowercase()) {
            "true" -> true
            "false" -> false
            else -> null
        }
    }

    private fun handleScroll(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("SCROLL_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }

        val forward = intent.getBooleanExtra(EXTRA_FORWARD, true)
        val direction = intent.getStringExtra(EXTRA_DIRECTION)?.trim().orEmpty()
        val preferTreeSearch = intent.getBooleanExtra(EXTRA_PREFER_TREE_SEARCH, false)
        val deviceListNormalization = intent.getBooleanExtra(EXTRA_DEVICE_LIST_NORMALIZATION, false)
        service.performScroll(forward, direction, reqId, preferTreeSearch, deviceListNormalization,
            intent.getStringExtra("scrollContainerPath"), intent.getStringExtra("scrollContainerBounds"))
    }

    private fun handleSetText(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("SET_TEXT_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }

        val text = intent.getStringExtra(EXTRA_TEXT)
        if (text == null) {
            logFailure("SET_TEXT_RESULT", reqId, "Missing text extra")
            return
        }

        service.performSetText(text, reqId)
    }

    private fun handlePing(intent: Intent) {
        val reqId = parseReqId(intent)
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("PING_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }

        val payload = org.json.JSONObject()
            .put("reqId", reqId)
            .put("success", true)
            .put("status", "READY")
            .toString()
        Log.i(TAG, "PING_RESULT $payload")
    }

    private fun logFailure(resultTag: String, reqId: String, reason: String, status: String? = null) {
        val payload = org.json.JSONObject()
            .put("reqId", reqId)
            .put("success", false)
            .put("reason", reason)
            .apply {
                if (!status.isNullOrBlank()) put("status", status)
            }
            .toString()
        A11yResultTransport.encode(resultTag, reqId, payload).forEach { Log.w(TAG, it) }
    }

    private fun logDumpTreeFailure(reqId: String, reason: String) {
        val payload = org.json.JSONObject()
            .put("reqId", reqId)
            .put("success", false)
            .put("reason", reason)
            .toString()
        Log.w(TAG, "DUMP_TREE_RESULT $reqId $payload")
    }
}
