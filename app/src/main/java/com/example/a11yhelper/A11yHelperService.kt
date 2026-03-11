package com.example.a11yhelper

import android.accessibilityservice.AccessibilityService
import android.os.Bundle
import android.util.Log
import android.view.View
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

class A11yHelperService : AccessibilityService() {
    companion object {
        @Volatile
        var instance: A11yHelperService? = null
            private set

        private const val TAG = "A11Y_HELPER"
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "Service connected")
    }

    override fun onInterrupt() {
        Log.w(TAG, "Service interrupted")
    }

    override fun onDestroy() {
        super.onDestroy()
        if (instance === this) {
            instance = null
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        val type = event.eventType
        if (type == AccessibilityEvent.TYPE_ANNOUNCEMENT) {
            val announcement = event.text.joinToString(separator = "") { it?.toString() ?: "" }
            Log.i(TAG, "A11Y_ANNOUNCEMENT: $announcement")
        }

        if (type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            Log.i(TAG, "SCREEN_CHANGED")
        }

        if (type != AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED &&
            type != AccessibilityEvent.TYPE_VIEW_FOCUSED &&
            type != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            type != AccessibilityEvent.TYPE_ANNOUNCEMENT
        ) {
            return
        }

        val node = resolveFocusNode(event)
        if (node == null) {
            Log.d(TAG, "Focus node not found for eventType=$type")
            return
        }

        runCatching {
            A11yStateStore.update(FocusSnapshot.fromNode(node))
        }.onFailure {
            Log.e(TAG, "Failed to capture focus snapshot", it)
        }
    }

    private fun resolveFocusNode(event: AccessibilityEvent): AccessibilityNodeInfo? {
        val source = event.source
        if (source != null && (source.isAccessibilityFocused || source.isFocused)) {
            return source
        }

        rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)?.let { return it }
        rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.let { return it }
        return source
    }

    fun dumpTree() {
        val dumpArray = A11yNavigator.dumpTreeFlat(rootInActiveWindow)
        val dumpString = dumpArray.toString()
        val chunkSize = 3000

        if (dumpString.length <= chunkSize) {
            Log.i(TAG, "DUMP_TREE_RESULT $dumpString")
            return
        }

        var startIndex = 0
        while (startIndex < dumpString.length) {
            val endIndex = minOf(startIndex + chunkSize, dumpString.length)
            Log.i(TAG, "DUMP_TREE_PART ${dumpString.substring(startIndex, endIndex)}")
            startIndex = endIndex
        }
        Log.i(TAG, "DUMP_TREE_END")
    }

    fun performTargetAction(query: A11yNavigator.TargetQuery, action: Int): JSONObject {
        val outcome = A11yNavigator.findAndPerformAction(rootInActiveWindow, query, action)
        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("success", outcome.success)
            put("reason", outcome.reason)
            put("action", if (action == AccessibilityNodeInfo.ACTION_CLICK) "CLICK" else "FOCUS")
            put("targetText", query.targetText ?: JSONObject.NULL)
            put("targetViewId", query.targetViewId ?: JSONObject.NULL)
            put("targetClassName", query.targetClassName ?: JSONObject.NULL)
            if (outcome.target != null) {
                put("target", FocusSnapshot.fromNode(outcome.target).toJson())
            }
        }

        Log.i(TAG, "TARGET_ACTION_RESULT $resultJson")
        if (outcome.success && outcome.target != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(outcome.target))
        }
        return resultJson
    }
    fun moveFocus(forward: Boolean): JSONObject {
        val currentNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val targetNode = currentNode?.focusSearch(if (forward) View.FOCUS_FORWARD else View.FOCUS_BACKWARD)
        val success = targetNode?.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS) == true

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("success", success)
            put("direction", if (forward) "NEXT" else "PREV")
        }

        Log.i(TAG, "NAV_RESULT $resultJson")
        if (success && targetNode != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(targetNode))
        }
        return resultJson
    }

    fun clickFocusedNode(): JSONObject {
        val focusedNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val success = focusedNode?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("success", success)
            put("action", "CLICK_FOCUSED")
        }

        Log.i(TAG, "TARGET_ACTION_RESULT $resultJson")
        if (success && focusedNode != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(focusedNode))
        }
        return resultJson
    }

    fun performScroll(forward: Boolean): JSONObject {
        val focusedNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        var scrollNode = focusedNode

        while (scrollNode != null && !scrollNode.isScrollable) {
            scrollNode = scrollNode.parent
        }

        val action = if (forward) {
            AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
        } else {
            AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        }
        val success = scrollNode?.performAction(action) == true

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("success", success)
            put("action", if (forward) "SCROLL_FORWARD" else "SCROLL_BACKWARD")
            put("hasFocusedNode", focusedNode != null)
            put("scrollableNodeFound", scrollNode != null)
        }

        Log.i(TAG, "SCROLL_RESULT $resultJson")
        return resultJson
    }

    fun performSetText(text: String): JSONObject {
        val focusedNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        val success = focusedNode?.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args) == true

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("success", success)
            put("action", "SET_TEXT")
            put("text", text)
            put("hasFocusedNode", focusedNode != null)
        }

        Log.i(TAG, "SET_TEXT_RESULT $resultJson")
        return resultJson
    }

}
