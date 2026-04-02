package com.iotpart.sqe.talkbackhelper

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityManager
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class A11yHelperService : AccessibilityService() {
    companion object {
        @Volatile
        var instance: A11yHelperService? = null
            private set

        private const val TAG = "A11Y_HELPER"
        private const val VERSION = "1.0.4"
        private const val GESTURE_TAP_DURATION_MS = 90L
        // 일부 단말에서 접근성 제스처 callback(onCompleted/onCancelled) 전달이 2초 내외로 지연될 수 있어
        // 기존 1500ms 대신 callback 분기 구분이 가능한 현실적인 여유 시간을 사용한다.
        private const val GESTURE_DISPATCH_TIMEOUT_MS = 2800L
        private const val GESTURE_STABILIZATION_DELAY_MS = 100L
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

    internal fun sendAccessibilityEvent(eventType: Int) {
        val manager = getSystemService(ACCESSIBILITY_SERVICE) as? AccessibilityManager
        if (manager == null || !manager.isEnabled) {
            Log.w(TAG, "AccessibilityManager unavailable; skipped eventType=$eventType")
            return
        }

        val event = AccessibilityEvent.obtain(eventType).apply {
            packageName = this@A11yHelperService.packageName
            className = this@A11yHelperService.javaClass.name
            isEnabled = true
        }
        manager.sendAccessibilityEvent(event)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        val type = event.eventType
        if (type != AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED &&
            type != AccessibilityEvent.TYPE_VIEW_FOCUSED &&
            type != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            type != AccessibilityEvent.TYPE_ANNOUNCEMENT
        ) {
            return
        }
        if (A11yHistoryManager.shouldSuppressPreCommitTransientSystemUiEvent(type, event.packageName?.toString(), rootInActiveWindow)) {
            return
        }

        val node = resolveFocusNode(event)
        if (node == null) {
            Log.d(TAG, "Focus node not found for eventType=$type")
            return
        }
        if (A11yHistoryManager.shouldIgnorePostCommitResurfacedHeader(rootInActiveWindow, node, type)) {
            return
        }
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

    private fun resolveCurrentFocusNode(): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        return root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
            ?: root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: root
    }

    fun refreshCurrentFocusSnapshot(): FocusSnapshot? {
        val snapshot = FocusSnapshot.fromNodeOrNull(resolveCurrentFocusNode()) ?: return null
        A11yStateStore.update(snapshot)
        return snapshot
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

    fun performTargetAction(query: A11yTargetFinder.TargetQuery, action: Int, reqId: String = "none"): JSONObject {
        val actionLabel = when (action) {
            AccessibilityNodeInfo.ACTION_CLICK -> "ACTION_CLICK"
            AccessibilityNodeInfo.ACTION_LONG_CLICK -> "ACTION_LONG_CLICK"
            AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS -> "ACTION_ACCESSIBILITY_FOCUS"
            else -> "ACTION_$action"
        }
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][service_start] reqId=$reqId accessibilityAction=$actionLabel target='${query.targetName}' type='${query.targetType}'"
        )
        val outcome = A11yTargetFinder.findAndPerformAction(rootInActiveWindow, query, action, reqId)
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
            if (!outcome.attemptedResourceId.isNullOrBlank()) {
                put("attemptedResourceId", outcome.attemptedResourceId)
            }
            if (!outcome.attemptedClassName.isNullOrBlank()) {
                put("attemptedClassName", outcome.attemptedClassName)
            }
            if (outcome.target != null) {
                put("target", FocusSnapshot.fromNode(outcome.target).toJson())
            }
        }

        val safeReason = outcome.reason.ifBlank { "" }
        val safeResourceId = outcome.attemptedResourceId ?: ""
        val safeClassName = outcome.attemptedClassName ?: ""
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][service_end] reqId=$reqId success=${outcome.success} reason='$safeReason' attemptedResourceId='$safeResourceId' attemptedClassName='$safeClassName'"
        )
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][broadcast_result] reqId=$reqId success=${outcome.success} reason='$safeReason' attemptedResourceId='$safeResourceId' attemptedClassName='$safeClassName'"
        )
        Log.i(TAG, "TARGET_ACTION_RESULT $resultJson")
        if (outcome.success && outcome.target != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(outcome.target))
        }
        return resultJson
    }

    fun checkTarget(query: A11yTargetFinder.TargetQuery, reqId: String = "none"): JSONObject {
        val outcome = A11yTargetFinder.findTarget(rootInActiveWindow, query)
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

    fun performTargetBoundsCenterTap(query: A11yTargetFinder.TargetQuery, reqId: String = "none"): JSONObject {
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][service_start] reqId=$reqId accessibilityAction=TOUCH_BOUNDS_CENTER target='${query.targetName}' type='${query.targetType}' serviceVersion=$VERSION"
        )
        val targetOutcome = A11yTargetFinder.findTarget(rootInActiveWindow, query)
        val targetNode = targetOutcome.target
        val actionOutcome = when {
            !targetOutcome.success || targetNode == null -> TargetActionOutcome(
                success = false,
                reason = targetOutcome.reason.ifBlank { "Target node not found" }
            )
            else -> {
                val bounds = Rect().also { targetNode.getBoundsInScreen(it) }
                val center = A11yTargetFinder.calculateBoundsCenter(bounds)
                if (center == null) {
                    TargetActionOutcome(
                        success = false,
                        reason = "Bounds unavailable",
                        target = targetNode,
                        attemptedResourceId = targetNode.viewIdResourceName,
                        attemptedClassName = targetNode.className?.toString()
                    )
                } else {
                    val (x, y) = center
                    val gestureOutcome = runCatching { dispatchCenterTap(x, y, reqId) }
                        .getOrElse { TargetActionOutcome(success = false, reason = "Gesture dispatch failed") }
                    if (!gestureOutcome.success) {
                        TargetActionOutcome(
                            success = false,
                            reason = gestureOutcome.reason,
                            target = targetNode,
                            attemptedResourceId = targetNode.viewIdResourceName,
                            attemptedClassName = targetNode.className?.toString()
                        )
                    } else {
                        TargetActionOutcome(
                            success = true,
                            reason = "Center tap success",
                            target = targetNode,
                            attemptedResourceId = targetNode.viewIdResourceName,
                            attemptedClassName = targetNode.className?.toString()
                        )
                    }
                }
            }
        }

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", actionOutcome.success)
            put("reason", actionOutcome.reason)
            put("action", "TOUCH_BOUNDS_CENTER")
            put("targetName", query.targetName)
            put("targetType", query.targetType)
            put("targetIndex", query.targetIndex)
            if (!actionOutcome.attemptedResourceId.isNullOrBlank()) {
                put("attemptedResourceId", actionOutcome.attemptedResourceId)
            }
            if (!actionOutcome.attemptedClassName.isNullOrBlank()) {
                put("attemptedClassName", actionOutcome.attemptedClassName)
            }
            if (actionOutcome.target != null) {
                put("target", FocusSnapshot.fromNode(actionOutcome.target).toJson())
            }
        }
        Log.i(TAG, "TARGET_ACTION_RESULT $resultJson")
        return resultJson
    }

    private fun dispatchCenterTap(x: Int, y: Int, reqId: String): TargetActionOutcome {
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][gesture_dispatch] reqId=$reqId x=$x y=$y delayMs=$GESTURE_STABILIZATION_DELAY_MS durationMs=$GESTURE_TAP_DURATION_MS"
        )
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, GESTURE_STABILIZATION_DELAY_MS, GESTURE_TAP_DURATION_MS))
            .build()
        val latch = CountDownLatch(1)
        val callbackReason = AtomicReference("Gesture dispatch timeout")
        val callbackThread = HandlerThread("gesture-callback-$reqId").apply { start() }
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][gesture_dispatch] reqId=$reqId awaitThread=${Thread.currentThread().name} callbackThread=${callbackThread.name}"
        )
        val dispatched = dispatchGesture(
            gesture,
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) {
                    Log.d(TAG, "[DEBUG][TARGET_ACTION][gesture_callback] reqId=$reqId state=completed")
                    callbackReason.set("Gesture completed")
                    latch.countDown()
                }

                override fun onCancelled(gestureDescription: GestureDescription?) {
                    Log.d(TAG, "[DEBUG][TARGET_ACTION][gesture_callback] reqId=$reqId state=cancelled")
                    callbackReason.set("Gesture cancelled")
                    latch.countDown()
                }
            },
            Handler(callbackThread.looper)
        )
        Log.d(TAG, "[DEBUG][TARGET_ACTION][gesture_dispatch_result] reqId=$reqId dispatched=$dispatched")
        val outcome = try {
            if (!dispatched) {
                TargetActionOutcome(success = false, reason = "Gesture dispatch returned false")
            } else {
                val callbackReceived = latch.await(GESTURE_DISPATCH_TIMEOUT_MS, TimeUnit.MILLISECONDS)
                if (!callbackReceived) {
                    Log.d(TAG, "[DEBUG][TARGET_ACTION][gesture_timeout] reqId=$reqId timeoutMs=$GESTURE_DISPATCH_TIMEOUT_MS")
                    TargetActionOutcome(success = false, reason = "Gesture dispatch timeout")
                } else {
                    val reason = callbackReason.get()
                    TargetActionOutcome(
                        success = reason == "Gesture completed",
                        reason = reason
                    )
                }
            }
        } finally {
            callbackThread.quitSafely()
        }

        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][gesture_final] reqId=$reqId success=${outcome.success} reason='${outcome.reason}'"
        )
        return outcome
    }


    private fun normalizeSmartNavStatus(success: Boolean, detail: String): String {
        if (!success) return "failed"
        return when (detail) {
            "scrolled" -> "scrolled"
            "looped" -> "looped"
            else -> "moved"
        }
    }

    private fun buildSmartNavFlags(detail: String): List<String> {
        return buildList {
            when (detail) {
                "moved_to_bottom_bar", "moved_to_bottom_bar_direct" -> add("bottom_bar")
            }
            if (detail == "moved_to_bottom_bar_direct") add("direct")
            if (detail == "moved_aligned") add("aligned")
            if (detail == "end_of_sequence") add("terminal")
            if (detail.startsWith("failed")) add("focus_failed")
        }
    }

    fun moveFocusSmart(reqId: String = "none"): JSONObject {
        val currentNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val outcome = A11yNavigator.performSmartNext(rootInActiveWindow, currentNode)

        val detail = outcome.reason
        val normalizedStatus = normalizeSmartNavStatus(outcome.success, detail)
        val flags = buildSmartNavFlags(detail)

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", outcome.success)
            put("status", normalizedStatus)
            put("detail", detail)
            put("flags", org.json.JSONArray(flags))
        }

        Log.i(TAG, "SMART_NAV_RESULT $resultJson")
        if (outcome.success && outcome.target != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(outcome.target))
        }
        return resultJson
    }

    fun moveFocus(forward: Boolean, reqId: String = "none"): JSONObject {
        val currentNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val targetNode = A11yNavigator.findSwipeTarget(rootInActiveWindow, currentNode, forward)
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
        var success = false
        var reason = "No clickable node found from focused node (direct/child/ancestor)"
        var clickedNode: AccessibilityNodeInfo? = null

        if (focusedNode == null) {
            reason = "Focused node is null"
        } else {
            Log.d(
                TAG,
                "[DEBUG][TARGET_ACTION][click_focused_direct] reqId=$reqId clickable=${focusedNode.isClickable} resourceId='${focusedNode.viewIdResourceName.orEmpty()}' class='${focusedNode.className?.toString().orEmpty()}'"
            )
            if (focusedNode.isClickable) {
                success = focusedNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                if (success) {
                    clickedNode = focusedNode
                    reason = "direct_click_success"
                }
            }

            if (!success) {
                val queue = ArrayDeque<Pair<AccessibilityNodeInfo, Int>>()
                queue.add(focusedNode to 0)
                var clickableChild: AccessibilityNodeInfo? = null
                while (queue.isNotEmpty()) {
                    val (node, depth) = queue.removeFirst()
                    if (depth >= 2) continue
                    for (i in 0 until node.childCount) {
                        val child = node.getChild(i) ?: continue
                        if (child.isClickable) {
                            clickableChild = child
                            break
                        }
                        queue.add(child to (depth + 1))
                    }
                    if (clickableChild != null) break
                }

                if (clickableChild != null) {
                    Log.d(
                        TAG,
                        "[DEBUG][TARGET_ACTION][click_focused_child] reqId=$reqId resourceId='${clickableChild.viewIdResourceName.orEmpty()}' class='${clickableChild.className?.toString().orEmpty()}'"
                    )
                    success = clickableChild.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    if (success) {
                        clickedNode = clickableChild
                        reason = "child_click_success"
                    }
                }
            }

            if (!success) {
                var parent = focusedNode.parent
                while (parent != null) {
                    Log.d(
                        TAG,
                        "[DEBUG][TARGET_ACTION][click_focused_ancestor] reqId=$reqId clickable=${parent.isClickable} resourceId='${parent.viewIdResourceName.orEmpty()}' class='${parent.className?.toString().orEmpty()}'"
                    )
                    if (parent.isClickable) {
                        success = parent.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                        if (success) {
                            clickedNode = parent
                            reason = "ancestor_click_success"
                            break
                        }
                    }
                    parent = parent.parent
                }
            }
        }

        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][click_focused_final] reqId=$reqId success=$success reason='$reason'"
        )

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", success)
            put("action", "CLICK_FOCUSED")
            put("reason", reason)
        }

        Log.i(TAG, "TARGET_ACTION_RESULT $resultJson")
        if (success && clickedNode != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(clickedNode))
        }
        return resultJson
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
            scrollNode = A11yNodeUtils.findBestScrollableContainer(rootInActiveWindow)
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
