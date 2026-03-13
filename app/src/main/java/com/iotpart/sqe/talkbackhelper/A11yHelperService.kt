package com.iotpart.sqe.talkbackhelper

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
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
        if (
            type == AccessibilityEvent.TYPE_ANNOUNCEMENT ||
            type == AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED ||
            type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
        ) {
            val announcement = extractAnnouncementText(event)
            if (announcement.isNotBlank()) {
                Log.i(TAG, "A11Y_ANNOUNCEMENT: $announcement")
            }
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

    private fun extractAnnouncementText(event: AccessibilityEvent): String {
        val eventText = event.text
            .mapNotNull { it?.toString()?.trim() }
            .filter { it.isNotEmpty() }
            .joinToString(separator = " ")

        if (eventText.isNotBlank()) {
            return eventText
        }

        val sourceNode = event.source ?: return ""
        val sourceText = listOf(
            sourceNode.text?.toString()?.trim().orEmpty(),
            sourceNode.contentDescription?.toString()?.trim().orEmpty(),
        )
            .filter { it.isNotEmpty() }
            .joinToString(separator = " ")

        return sourceText
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

    fun dumpTree(reqId: String = "none") {
        val dumpArray = A11yNavigator.dumpTreeFlat(rootInActiveWindow)
        val dumpString = dumpArray.toString()
        val chunkSize = 3000

        if (dumpString.length <= chunkSize) {
            Log.i(TAG, "DUMP_TREE_RESULT $reqId $dumpString")
            return
        }

        var startIndex = 0
        while (startIndex < dumpString.length) {
            val endIndex = minOf(startIndex + chunkSize, dumpString.length)
            Log.i(TAG, "DUMP_TREE_PART $reqId ${dumpString.substring(startIndex, endIndex)}")
            startIndex = endIndex
        }
        Log.i(TAG, "DUMP_TREE_END $reqId")
    }

    fun performTargetAction(query: A11yNavigator.TargetQuery, action: Int, reqId: String = "none"): JSONObject {
        val outcome = A11yNavigator.findAndPerformAction(rootInActiveWindow, query, action)
        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", outcome.success)
            put("reason", outcome.reason)
            put(
                "action", when (action) {
                    AccessibilityNodeInfo.ACTION_CLICK -> "CLICK"
                    AccessibilityNodeInfo.ACTION_LONG_CLICK -> "LONG_CLICK"
                    else -> "FOCUS"
                }
            )
            put("targetName", query.targetName)
            put("targetType", query.targetType)
            put("targetIndex", query.targetIndex)
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

    fun checkTarget(query: A11yNavigator.TargetQuery, reqId: String = "none"): JSONObject {
        val outcome = A11yNavigator.findTarget(rootInActiveWindow, query)
        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", outcome.success)
            put("reason", outcome.reason)
            put("action", "CHECK_TARGET")
            put("targetName", query.targetName)
            put("targetType", query.targetType)
            put("targetIndex", query.targetIndex)
        }

        Log.i(TAG, "CHECK_TARGET_RESULT $resultJson")
        return resultJson
    }

    fun moveFocus(forward: Boolean, reqId: String = "none"): JSONObject {
        val currentNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val targetNode = currentNode?.focusSearch(if (forward) View.FOCUS_FORWARD else View.FOCUS_BACKWARD)
        val success = targetNode?.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS) == true

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", success)
            put("direction", if (forward) "NEXT" else "PREV")
        }

        Log.i(TAG, "NAV_RESULT $resultJson")
        if (success && targetNode != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(targetNode))
        }
        return resultJson
    }

    fun clickFocusedNode(reqId: String = "none"): JSONObject {
        val focusedNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val success = focusedNode?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", success)
            put("action", "CLICK_FOCUSED")
        }

        Log.i(TAG, "TARGET_ACTION_RESULT $resultJson")
        if (success && focusedNode != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(focusedNode))
        }
        return resultJson
    }

    private fun findLargestScrollableNode(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null

        var bestNode: AccessibilityNodeInfo? = null
        var bestArea = -1L
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            if (node.isScrollable) {
                val bounds = Rect()
                node.getBoundsInScreen(bounds)
                val area = bounds.width().toLong() * bounds.height().toLong()
                if (area > bestArea) {
                    bestArea = area
                    bestNode = node
                }
            }

            for (index in 0 until node.childCount) {
                node.getChild(index)?.let { queue.add(it) }
            }
        }

        return bestNode
    }

    private fun findFirstScrollableNode(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null

        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            if (node.isScrollable) {
                return node
            }

            for (index in 0 until node.childCount) {
                node.getChild(index)?.let { queue.add(it) }
            }
        }

        return null
    }

    private fun normalizeScrollDirection(direction: String, forward: Boolean): String {
        return when (direction.trim().lowercase()) {
            "d", "down" -> "down"
            "u", "up" -> "up"
            "r", "right" -> "right"
            "l", "left" -> "left"
            else -> if (forward) "down" else "up"
        }
    }

    fun performScroll(forward: Boolean, direction: String, reqId: String = "none"): JSONObject {
        val focusedNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        var scrollNode = focusedNode

        while (scrollNode != null && !scrollNode.isScrollable) {
            scrollNode = scrollNode.parent
        }

        var fallbackUsed = false
        if (scrollNode == null) {
            fallbackUsed = true
            scrollNode = findFirstScrollableNode(rootInActiveWindow)
        }

        val fallbackToLargestUsed = scrollNode == null
        if (scrollNode == null) {
            scrollNode = findLargestScrollableNode(rootInActiveWindow)
        }

        val normalizedDirection = normalizeScrollDirection(direction, forward)
        val isForwardDirection = normalizedDirection == "down" || normalizedDirection == "right"
        val action = if (isForwardDirection) {
            AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
        } else {
            AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        }
        val success = scrollNode?.performAction(action) == true

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", success)
            put("action", if (isForwardDirection) "SCROLL_FORWARD" else "SCROLL_BACKWARD")
            put("direction", normalizedDirection)
            put("hasFocusedNode", focusedNode != null)
            put("scrollableNodeFound", scrollNode != null)
            put("fallbackToTreeSearchScrollable", fallbackUsed)
            put("fallbackToLargestScrollable", fallbackToLargestUsed)
        }

        Log.i(TAG, "SCROLL_RESULT $resultJson")
        return resultJson
    }

    fun performSetText(text: String, reqId: String = "none"): JSONObject {
        val focusedNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        val success = focusedNode?.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args) == true

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", success)
            put("action", "SET_TEXT")
            put("text", text)
            put("hasFocusedNode", focusedNode != null)
        }

        Log.i(TAG, "SET_TEXT_RESULT $resultJson")
        return resultJson
    }

}
