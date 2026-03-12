package com.example.a11yhelper

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo

class A11yCommandReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "A11Y_HELPER"
        private const val ACTION_GET_FOCUS = "com.example.a11yhelper.GET_FOCUS"
        private const val ACTION_FOCUS_RESULT = "com.example.a11yhelper.FOCUS_RESULT"
        private const val ACTION_DUMP_TREE = "com.example.a11yhelper.DUMP_TREE"
        private const val ACTION_FOCUS_TARGET = "com.example.a11yhelper.FOCUS_TARGET"
        private const val ACTION_CLICK_TARGET = "com.example.a11yhelper.CLICK_TARGET"
        private const val ACTION_CHECK_TARGET = "com.example.a11yhelper.CHECK_TARGET"
        private const val ACTION_NEXT = "com.example.a11yhelper.NEXT"
        private const val ACTION_PREV = "com.example.a11yhelper.PREV"
        private const val ACTION_CLICK_FOCUSED = "com.example.a11yhelper.CLICK_FOCUSED"
        private const val ACTION_SCROLL = "com.example.a11yhelper.SCROLL"
        private const val ACTION_SET_TEXT = "com.example.a11yhelper.SET_TEXT"
        private const val EXTRA_TARGET_NAME = "targetName"
        private const val EXTRA_TARGET_TYPE = "targetType"
        private const val EXTRA_TARGET_INDEX = "targetIndex"
        private const val EXTRA_IS_LONG_CLICK = "isLongClick"
        private const val EXTRA_FORWARD = "forward"
        private const val EXTRA_TEXT = "text"
    }

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        when (action) {
            ACTION_GET_FOCUS -> handleGetFocus(context, intent)
            ACTION_DUMP_TREE -> handleDumpTree()
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
            ACTION_NEXT -> A11yHelperService.instance?.moveFocus(true)
            ACTION_PREV -> A11yHelperService.instance?.moveFocus(false)
            ACTION_CLICK_FOCUSED -> A11yHelperService.instance?.clickFocusedNode()
            ACTION_SCROLL -> handleScroll(intent)
            ACTION_SET_TEXT -> handleSetText(intent)
            else -> Unit
        }
    }

    private fun handleGetFocus(context: Context, intent: Intent) {
        A11yStateStore.ensureFallbackJson()
        val saveFile = intent.getBooleanExtra("saveFile", false)
        if (saveFile) {
            A11yStateStore.saveToExternalFile(context)
        }

        val json = A11yStateStore.lastFocusJson
        Log.i(TAG, "FOCUS_RESULT $json")

        val reply = Intent(ACTION_FOCUS_RESULT).apply {
            setPackage(context.packageName)
            putExtra("json", json)
            putExtra("updatedAt", A11yStateStore.lastUpdatedAt)
        }
        context.sendBroadcast(reply)
    }

    private fun handleDumpTree() {
        val service = A11yHelperService.instance
        if (service == null) {
            Log.w(TAG, "DUMP_TREE_RESULT [] // Service not connected")
            return
        }
        service.dumpTree()
    }

    private fun handleTargetAction(intent: Intent, action: Int) {
        val service = A11yHelperService.instance
        if (service == null) {
            Log.w(TAG, "TARGET_ACTION_RESULT {\"success\":false,\"reason\":\"Service not connected\"}")
            return
        }

        val query = parseQuery(intent) ?: return
        service.performTargetAction(query, action)
    }

    private fun handleCheckTarget(intent: Intent) {
        val service = A11yHelperService.instance
        if (service == null) {
            Log.w(TAG, "CHECK_TARGET_RESULT {\"success\":false,\"reason\":\"Service not connected\"}")
            return
        }

        val query = parseQuery(intent) ?: return
        service.checkTarget(query)
    }

    private fun parseQuery(intent: Intent): A11yNavigator.TargetQuery? {
        val targetName = intent.getStringExtra(EXTRA_TARGET_NAME)?.trim().orEmpty()
        val targetType = intent.getStringExtra(EXTRA_TARGET_TYPE)?.trim().orEmpty().lowercase()
        val targetIndex = intent.getIntExtra(EXTRA_TARGET_INDEX, 0)

        if (targetName.isBlank()) {
            Log.w(TAG, "TARGET_ACTION_RESULT {\"success\":false,\"reason\":\"targetName is required\"}")
            return null
        }

        if (targetType !in setOf("t", "b", "r", "a")) {
            Log.w(TAG, "TARGET_ACTION_RESULT {\"success\":false,\"reason\":\"targetType must be one of t,b,r,a\"}")
            return null
        }

        if (targetIndex < 0) {
            Log.w(TAG, "TARGET_ACTION_RESULT {\"success\":false,\"reason\":\"targetIndex must be >= 0\"}")
            return null
        }

        return A11yNavigator.TargetQuery(targetName = targetName, targetType = targetType, targetIndex = targetIndex)
    }

    private fun handleScroll(intent: Intent) {
        val service = A11yHelperService.instance
        if (service == null) {
            Log.w(TAG, "SCROLL_RESULT {\"success\":false,\"reason\":\"Service not connected\"}")
            return
        }

        val forward = intent.getBooleanExtra(EXTRA_FORWARD, true)
        service.performScroll(forward)
    }

    private fun handleSetText(intent: Intent) {
        val service = A11yHelperService.instance
        if (service == null) {
            Log.w(TAG, "SET_TEXT_RESULT {\"success\":false,\"reason\":\"Service not connected\"}")
            return
        }

        val text = intent.getStringExtra(EXTRA_TEXT)
        if (text == null) {
            Log.w(TAG, "SET_TEXT_RESULT {\"success\":false,\"reason\":\"Missing text extra\"}")
            return
        }

        service.performSetText(text)
    }
}
