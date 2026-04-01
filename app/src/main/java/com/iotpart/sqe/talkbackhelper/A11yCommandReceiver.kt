package com.iotpart.sqe.talkbackhelper

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class A11yCommandReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "A11Y_HELPER"
        private const val VERSION = "1.2.2"
        private const val ACTION_GET_FOCUS = "com.iotpart.sqe.talkbackhelper.GET_FOCUS"
        private const val ACTION_FOCUS_RESULT = "com.iotpart.sqe.talkbackhelper.FOCUS_RESULT"
        private const val ACTION_DUMP_TREE = "com.iotpart.sqe.talkbackhelper.DUMP_TREE"
        private const val ACTION_FOCUS_TARGET = "com.iotpart.sqe.talkbackhelper.FOCUS_TARGET"
        private const val ACTION_CLICK_TARGET = "com.iotpart.sqe.talkbackhelper.CLICK_TARGET"
        private const val ACTION_TOUCH_BOUNDS_CENTER_TARGET = "com.iotpart.sqe.talkbackhelper.TOUCH_BOUNDS_CENTER_TARGET"
        private const val ACTION_CHECK_TARGET = "com.iotpart.sqe.talkbackhelper.CHECK_TARGET"
        private const val ACTION_NEXT = "com.iotpart.sqe.talkbackhelper.NEXT"
        private const val ACTION_PREV = "com.iotpart.sqe.talkbackhelper.PREV"
        private const val ACTION_SMART_NEXT = "com.iotpart.sqe.talkbackhelper.SMART_NEXT"
        private const val ACTION_CLICK_FOCUSED = "com.iotpart.sqe.talkbackhelper.CLICK_FOCUSED"
        private const val ACTION_SCROLL = "com.iotpart.sqe.talkbackhelper.SCROLL"
        private const val ACTION_SET_TEXT = "com.iotpart.sqe.talkbackhelper.SET_TEXT"
        private const val ACTION_PING = "com.iotpart.sqe.talkbackhelper.PING"
        private const val ACTION_COMMAND = "com.iotpart.sqe.talkbackhelper.ACTION_COMMAND"
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
        private const val EXTRA_TEXT = "text"
        private const val EXTRA_REQ_ID = "reqId"
        private const val EXTRA_COMMAND = "command"
        private const val DEFAULT_REQ_ID = "none"
        private val smartNextExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    }

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        when (action) {
            ACTION_GET_FOCUS -> handleGetFocus(context, intent)
            ACTION_DUMP_TREE -> handleDumpTree(intent)
            ACTION_FOCUS_TARGET -> handleTargetAction(intent, AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
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
            ACTION_SMART_NEXT -> handleSmartNext(context, intent)
            ACTION_CLICK_FOCUSED -> handleClickFocused(intent)
            ACTION_SCROLL -> handleScroll(intent)
            ACTION_SET_TEXT -> handleSetText(intent)
            ACTION_PING -> handlePing(intent)
            ACTION_COMMAND -> handleExternalCommand(context, intent)
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

        val jsonObj = runCatching { org.json.JSONObject(A11yStateStore.lastFocusJson) }
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
            logFailure("DUMP_TREE_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }
        service.dumpTree(reqId)
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
        val service = A11yHelperService.instance
        if (service == null) {
            logFailure("SMART_NAV_RESULT", reqId, "Accessibility Service is null or not running")
            return
        }
        val pendingResult = goAsync()
        smartNextExecutor.execute {
            try {
                Log.i(TAG, "[SMART_NEXT] async execution start reqId=$reqId receiverVersion=$VERSION")
                val result = service.moveFocusSmart(reqId)
                val reply = Intent("SMART_NAV_RESULT").apply {
                    setPackage(context.packageName)
                    putExtra("json", result.toString())
                }
                context.sendBroadcast(reply)
            } catch (t: Throwable) {
                Log.e(TAG, "[SMART_NEXT] async execution failed reqId=$reqId", t)
                logFailure("SMART_NAV_RESULT", reqId, "Smart next async execution failed: ${t.message}")
            } finally {
                pendingResult.finish()
            }
        }
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
        service.performScroll(forward, direction, reqId)
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

    private fun logFailure(resultTag: String, reqId: String, reason: String) {
        val payload = org.json.JSONObject()
            .put("reqId", reqId)
            .put("success", false)
            .put("reason", reason)
            .toString()
        Log.w(TAG, "$resultTag $payload")
    }
}
