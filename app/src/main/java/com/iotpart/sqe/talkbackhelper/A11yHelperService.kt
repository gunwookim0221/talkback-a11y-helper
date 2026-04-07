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
        private const val VERSION = "1.5.2"
        private const val GESTURE_TAP_DURATION_MS = 90L
        // 일부 단말에서 접근성 제스처 callback(onCompleted/onCancelled) 전달이 2초 내외로 지연될 수 있어
        // 기존 1500ms 대신 callback 분기 구분이 가능한 현실적인 여유 시간을 사용한다.
        private const val GESTURE_DISPATCH_TIMEOUT_MS = 2800L
        private const val GESTURE_STABILIZATION_DELAY_MS = 100L
        private const val CLICK_DESCENDANT_MAX_DEPTH = 4
    }

    internal enum class ClickPath(val value: String) {
        DIRECT("direct"),
        DESCENDANT("descendant"),
        MIRROR_DESCENDANT("mirror_descendant"),
        WRAPPER_RECOVERY("wrapper_recovery"),
        ANCESTOR("ancestor"),
        ROOT_RETARGET("root_retarget"),
        SEMANTIC_MIRROR("semantic_mirror"),
        NONE("none")
    }

    internal data class ClickExecutionResult<T>(
        val success: Boolean,
        val reason: String,
        val path: ClickPath,
        val clickedNode: T?,
        val attemptedNode: T?,
        val mirrorNode: T? = null
    )

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
        val resolvedFocusNode = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        val resolvedFocusLabel = (
            resolvedFocusNode?.text?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: resolvedFocusNode?.contentDescription?.toString()?.trim().takeUnless { it.isNullOrEmpty() }
                ?: ""
            ).replace("\n", " ").take(96)
        Log.i(
            TAG,
            "[SMART_NEXT][final] success=${outcome.success} status='$normalizedStatus' detail='$detail' resolved_focus_view_id='${resolvedFocusNode?.viewIdResourceName.orEmpty()}' resolved_focus_label='$resolvedFocusLabel' requested_target_view_id='${outcome.target?.viewIdResourceName.orEmpty()}'"
        )

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
        val rootNode = rootInActiveWindow
        val focusedSnapshot = FocusSnapshot.fromNodeOrNull(focusedNode)
        val focusedBounds = focusedNode?.let { Rect().also { rect -> it.getBoundsInScreen(rect) } }
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][click_focused_focus_snapshot] reqId=$reqId resourceId='${focusedNode?.viewIdResourceName.orEmpty()}' class='${focusedNode?.className?.toString().orEmpty()}' text='${focusedNode?.text?.toString().orEmpty()}' contentDesc='${focusedNode?.contentDescription?.toString().orEmpty()}' bounds='${focusedBounds?.toShortString().orEmpty()}'"
        )
        val outcome = executeClickFromFocusedNode(
            focusedNode = focusedNode,
            rootNode = rootNode,
            reResolveFocusedNodeFromRoot = { snapshotFocusedNode, currentRootNode, log ->
                resolveRawFocusedNodeFromRoot(snapshotFocusedNode, currentRootNode, log)
            },
            childCountOf = { it.childCount },
            childAt = { node, index -> node.getChild(index) },
            parentOf = { it.parent },
            isAccessibilityFocused = { it.isAccessibilityFocused },
            isFocusable = { it.isFocusable },
            isClickable = { it.isClickable },
            isVisible = { it.isVisibleToUser },
            isEnabled = { it.isEnabled },
            boundsOf = { node -> Rect().also { node.getBoundsInScreen(it) } },
            resourceIdOf = { it.viewIdResourceName },
            classNameOf = { it.className?.toString() },
            contentDescOf = { it.contentDescription?.toString() },
            textOf = { it.text?.toString() },
            performClick = { it.performAction(AccessibilityNodeInfo.ACTION_CLICK) },
            log = { message ->
                Log.d(TAG, "[DEBUG][TARGET_ACTION][$message] reqId=$reqId")
            }
        )
        val attemptedNode = outcome.attemptedNode ?: focusedNode
        val clickedNode = outcome.clickedNode
        val mirrorNode = outcome.mirrorNode

        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][click_focused_final] reqId=$reqId success=${outcome.success} path=${outcome.path.value} reason='${outcome.reason}' attemptedResourceId='${attemptedNode?.viewIdResourceName.orEmpty()}' attemptedClassName='${attemptedNode?.className?.toString().orEmpty()}'"
        )

        val resultJson = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("reqId", reqId)
            put("success", outcome.success)
            put("action", "CLICK_FOCUSED")
            put("reason", outcome.reason)
            put("path", outcome.path.value)
            put("attemptedResourceId", attemptedNode?.viewIdResourceName ?: JSONObject.NULL)
            put("attemptedClassName", attemptedNode?.className?.toString() ?: JSONObject.NULL)
            if (mirrorNode != null) {
                val mirrorBounds = Rect().also { mirrorNode.getBoundsInScreen(it) }
                put("mirrorResourceId", mirrorNode.viewIdResourceName ?: JSONObject.NULL)
                put("mirrorClassName", mirrorNode.className?.toString() ?: JSONObject.NULL)
                put("mirrorBounds", mirrorBounds.toShortString())
            }
            if (focusedSnapshot != null) {
                put("focused", focusedSnapshot.toJson())
            }
            if (clickedNode != null) {
                put("target", FocusSnapshot.fromNode(clickedNode).toJson())
            }
            if (outcome.path == ClickPath.ROOT_RETARGET && clickedNode != null) {
                val retargetedBounds = Rect().also { clickedNode.getBoundsInScreen(it) }
                put("retargetedResourceId", clickedNode.viewIdResourceName ?: JSONObject.NULL)
                put("retargetedClassName", clickedNode.className?.toString() ?: JSONObject.NULL)
                put("retargetedBounds", retargetedBounds.toShortString())
            }
        }

        Log.i(TAG, "TARGET_ACTION_RESULT $resultJson")
        if (outcome.success && clickedNode != null) {
            A11yStateStore.update(FocusSnapshot.fromNode(clickedNode))
        }
        return resultJson
    }

    private fun resolveRawFocusedNodeFromRoot(
        focusedNode: AccessibilityNodeInfo?,
        rootNode: AccessibilityNodeInfo?,
        log: ((String) -> Unit)? = null
    ): AccessibilityNodeInfo? {
        if (focusedNode == null || rootNode == null) {
            log?.invoke(
                "[click_focused_raw_focus_resolve] resolved=false resourceId='${focusedNode?.viewIdResourceName.orEmpty()}' className='${focusedNode?.className?.toString().orEmpty()}' bounds='' reason='missing_focused_or_root'"
            )
            return null
        }
        val focusedBounds = Rect().also { focusedNode.getBoundsInScreen(it) }
        val focusedResourceId = focusedNode.viewIdResourceName.orEmpty()
        val focusedClassName = focusedNode.className?.toString().orEmpty()
        val focusedPackage = focusedNode.packageName?.toString().orEmpty()
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue += rootNode
        var bestNode: AccessibilityNodeInfo? = null
        var bestScore = Int.MIN_VALUE
        var bestReason = "not_found"

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            for (index in 0 until node.childCount) {
                node.getChild(index)?.let(queue::add)
            }
            val nodeBounds = Rect().also { node.getBoundsInScreen(it) }
            if (nodeBounds.isEmpty) continue
            val nodeResourceId = node.viewIdResourceName.orEmpty()
            val nodeClassName = node.className?.toString().orEmpty()
            val nodePackage = node.packageName?.toString().orEmpty()
            var score = 0
            val reasonTokens = mutableListOf<String>()
            if (node === focusedNode) {
                score += 1400
                reasonTokens += "same_instance"
            }
            if (focusedResourceId.isNotEmpty() && focusedResourceId == nodeResourceId) {
                score += 520
                reasonTokens += "same_resource"
            }
            if (focusedClassName.isNotEmpty() && focusedClassName == nodeClassName) {
                score += 260
                reasonTokens += "same_class"
            }
            if (focusedPackage.isNotEmpty() && focusedPackage == nodePackage) {
                score += 90
                reasonTokens += "same_package"
            }
            if (focusedBounds == nodeBounds) {
                score += 520
                reasonTokens += "same_bounds"
            }
            if (Rect.intersects(focusedBounds, nodeBounds)) {
                score += 180
                reasonTokens += "bounds_intersect"
            }
            val delta = kotlin.math.abs(focusedBounds.centerX() - nodeBounds.centerX()) +
                kotlin.math.abs(focusedBounds.centerY() - nodeBounds.centerY())
            if (delta <= 24) {
                score += 220
                reasonTokens += "center_near"
            } else if (delta <= 96) {
                score += 80
                reasonTokens += "center_close"
            }
            if (node.isAccessibilityFocused) {
                score += 180
                reasonTokens += "a11y_focused"
            }
            if (node.isFocused) {
                score += 120
                reasonTokens += "input_focused"
            }
            if (score > bestScore) {
                bestScore = score
                bestNode = node
                bestReason = if (reasonTokens.isEmpty()) "weak_match" else reasonTokens.joinToString("+")
            }
        }

        val resolved = bestNode != null && bestScore >= 420
        val resolvedBounds = if (resolved) Rect().also { bestNode?.getBoundsInScreen(it) } else null
        log?.invoke(
            "[click_focused_raw_focus_resolve] resolved=$resolved resourceId='${bestNode?.viewIdResourceName.orEmpty()}' className='${bestNode?.className?.toString().orEmpty()}' bounds='${resolvedBounds?.toShortString().orEmpty()}' reason='${if (resolved) bestReason else "score_too_low:$bestScore"}'"
        )
        return if (resolved) bestNode else null
    }

    internal fun <T> executeClickFromFocusedNode(
        focusedNode: T?,
        rootNode: T?,
        reResolveFocusedNodeFromRoot: ((focusedNode: T, rootNode: T?, log: ((String) -> Unit)?) -> T?)? = null,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        parentOf: (T) -> T?,
        isAccessibilityFocused: (T) -> Boolean = { false },
        isFocusable: (T) -> Boolean = { false },
        isClickable: (T) -> Boolean,
        isVisible: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        boundsOf: (T) -> Rect,
        resourceIdOf: (T) -> String?,
        classNameOf: (T) -> String?,
        contentDescOf: (T) -> String?,
        textOf: (T) -> String?,
        performClick: (T) -> Boolean,
        log: ((String) -> Unit)? = null
    ): ClickExecutionResult<T> {
        if (focusedNode == null) {
            return ClickExecutionResult(
                success = false,
                reason = "Focused node not found",
                path = ClickPath.NONE,
                clickedNode = null,
                attemptedNode = null
            )
        }

        val rawResolvedFocusedNode = if (!isClickable(focusedNode) && reResolveFocusedNodeFromRoot != null) {
            reResolveFocusedNodeFromRoot(focusedNode, rootNode, log)
        } else {
            null
        }
        val effectiveFocusedNode = rawResolvedFocusedNode ?: focusedNode
        val focusedBounds = boundsOf(effectiveFocusedNode)
        val focusedResourceId = resourceIdOf(effectiveFocusedNode).orEmpty()
        val focusedClassName = classNameOf(effectiveFocusedNode).orEmpty()

        if (isNodeClickableCandidate(effectiveFocusedNode, isClickable, isVisible, isEnabled, boundsOf) && performClick(effectiveFocusedNode)) {
            return ClickExecutionResult(
                success = true,
                reason = "Focused node clicked",
                path = ClickPath.DIRECT,
                clickedNode = effectiveFocusedNode,
                attemptedNode = effectiveFocusedNode
            )
        }

        val descendant = findFirstClickableDescendant(
            root = effectiveFocusedNode,
            maxDepth = CLICK_DESCENDANT_MAX_DEPTH,
            childCountOf = childCountOf,
            childAt = childAt,
            isClickable = isClickable,
            isVisible = isVisible,
            isEnabled = isEnabled,
            boundsOf = boundsOf
        )
        if (descendant != null && performClick(descendant)) {
            return ClickExecutionResult(
                success = true,
                reason = "Clickable descendant clicked",
                path = ClickPath.DESCENDANT,
                clickedNode = descendant,
                attemptedNode = descendant
            )
        }

        val descendantHint = buildDescendantHint(
            focusedNode = effectiveFocusedNode,
            childCountOf = childCountOf,
            childAt = childAt,
            isVisible = isVisible,
            isClickable = isClickable,
            isEnabled = isEnabled,
            resourceIdOf = resourceIdOf,
            classNameOf = classNameOf,
            contentDescOf = contentDescOf,
            textOf = textOf,
            boundsOf = boundsOf
        )
        log?.invoke(
            "click_focused_descendant_hint hasClickableDescendant=${descendantHint != null} actionableDescendantResourceId='${descendantHint?.resourceId.orEmpty()}' actionableDescendantClassName='${descendantHint?.className.orEmpty()}' actionableDescendantContentDescription='${descendantHint?.contentDescription.orEmpty()}'"
        )
        val focusedSubtreeChildCount = childCountOf(effectiveFocusedNode)
        val focusedSubtreeEmpty = focusedSubtreeChildCount == 0
        val shouldTryMirrorResolve = !isClickable(effectiveFocusedNode)
        val focusedAccessibleFocused = isAccessibilityFocused(effectiveFocusedNode)
        val focusedFocusable = isFocusable(effectiveFocusedNode)
        log?.invoke(
            "click_focused_subtree_state empty=$focusedSubtreeEmpty mirrorResolvePlanned=$shouldTryMirrorResolve focusedClickable=${isClickable(effectiveFocusedNode)} focusedChildCount=$focusedSubtreeChildCount"
        )

        val rootBounds = boundsOf(rootNode ?: effectiveFocusedNode)
        val rootArea = maxOf(1, rootBounds.width() * rootBounds.height())
        val focusedArea = maxOf(1, focusedBounds.width() * focusedBounds.height())
        val rootHeight = maxOf(1, rootBounds.height())
        val focusedCenterX = focusedBounds.centerX()
        val focusedCenterY = focusedBounds.centerY()
        val focusedTopRegion = focusedCenterY <= rootBounds.top + (rootHeight / 3)
        val focusedSmallTopTarget = focusedTopRegion && focusedArea <= (rootArea / 28)
        val topRegionBottom = minOf(
            rootBounds.bottom,
            maxOf(rootBounds.top + (rootHeight / 6), focusedBounds.bottom + maxOf(180, focusedBounds.height() * 2))
        )

        var resolvedMirrorNode: T? = null
        if (shouldTryMirrorResolve) {
            val mirrorResolve = resolveMirrorNodeFromRoot(
                focusedNode = effectiveFocusedNode,
                rootNode = rootNode,
                childCountOf = childCountOf,
                childAt = childAt,
                isClickable = isClickable,
                isVisible = isVisible,
                isEnabled = isEnabled,
                boundsOf = boundsOf,
                resourceIdOf = resourceIdOf,
                classNameOf = classNameOf,
                contentDescOf = contentDescOf,
                textOf = textOf,
                log = log
            )
            resolvedMirrorNode = mirrorResolve.node
            log?.invoke(
                "click_focused_mirror_candidates local=${mirrorResolve.localCandidateCount} global=${mirrorResolve.globalCandidateCount} giantFiltered=${mirrorResolve.giantFilteredCount} total=${mirrorResolve.candidateCount} rejectSummary='${mirrorResolve.rejectSummary}'"
            )
            log?.invoke(
                "click_focused_mirror_resolve attempted=true candidates=${mirrorResolve.candidateCount} reason='${mirrorResolve.reason}' score=${mirrorResolve.score}"
            )
            if (resolvedMirrorNode != null) {
                val mirrorBounds = boundsOf(resolvedMirrorNode)
                log?.invoke(
                    "click_focused_mirror_pick resourceId='${resourceIdOf(resolvedMirrorNode).orEmpty()}' class='${classNameOf(resolvedMirrorNode).orEmpty()}' bounds='${mirrorBounds.toShortString()}' reason='${mirrorResolve.reason}' score=${mirrorResolve.score}"
                )
                if (isNodeClickableCandidate(resolvedMirrorNode, isClickable, isVisible, isEnabled, boundsOf) && performClick(resolvedMirrorNode)) {
                    return ClickExecutionResult(
                        success = true,
                        reason = "Mirror clickable node clicked",
                        path = ClickPath.MIRROR_DESCENDANT,
                        clickedNode = resolvedMirrorNode,
                        attemptedNode = resolvedMirrorNode,
                        mirrorNode = resolvedMirrorNode
                    )
                }
                val mirrorDescendantHint = buildDescendantHint(
                    focusedNode = resolvedMirrorNode,
                    childCountOf = childCountOf,
                    childAt = childAt,
                    isVisible = isVisible,
                    isClickable = isClickable,
                    isEnabled = isEnabled,
                    resourceIdOf = resourceIdOf,
                    classNameOf = classNameOf,
                    contentDescOf = contentDescOf,
                    textOf = textOf,
                    boundsOf = boundsOf
                )
                log?.invoke(
                    "click_focused_mirror_descendant_hint hasClickableDescendant=${mirrorDescendantHint != null} actionableDescendantResourceId='${mirrorDescendantHint?.resourceId.orEmpty()}' actionableDescendantClassName='${mirrorDescendantHint?.className.orEmpty()}' actionableDescendantContentDescription='${mirrorDescendantHint?.contentDescription.orEmpty()}'"
                )

                val mirrorDescendant = findFirstClickableDescendant(
                    root = resolvedMirrorNode,
                    maxDepth = CLICK_DESCENDANT_MAX_DEPTH,
                    childCountOf = childCountOf,
                    childAt = childAt,
                    isClickable = isClickable,
                    isVisible = isVisible,
                    isEnabled = isEnabled,
                    boundsOf = boundsOf
                )
                if (mirrorDescendant != null && performClick(mirrorDescendant)) {
                    return ClickExecutionResult(
                        success = true,
                        reason = "Mirror clickable descendant clicked",
                        path = ClickPath.MIRROR_DESCENDANT,
                        clickedNode = mirrorDescendant,
                        attemptedNode = mirrorDescendant,
                        mirrorNode = resolvedMirrorNode
                    )
                }

                val mirrorDescendantRetarget = findMatchingClickableFromRootByDescendantHint(
                    rootNode = rootNode,
                    focusedBounds = mirrorBounds,
                    hint = mirrorDescendantHint,
                    childCountOf = childCountOf,
                    childAt = childAt,
                    isClickable = isClickable,
                    isVisible = isVisible,
                    isEnabled = isEnabled,
                    boundsOf = boundsOf,
                    resourceIdOf = resourceIdOf,
                    classNameOf = classNameOf,
                    contentDescOf = contentDescOf,
                    textOf = textOf
                )
                if (mirrorDescendantRetarget != null && performClick(mirrorDescendantRetarget)) {
                    return ClickExecutionResult(
                        success = true,
                        reason = "Mirror descendant metadata retarget clicked",
                        path = ClickPath.MIRROR_DESCENDANT,
                        clickedNode = mirrorDescendantRetarget,
                        attemptedNode = mirrorDescendantRetarget,
                        mirrorNode = resolvedMirrorNode
                    )
                }
            } else if (mirrorResolve.giantFilteredCount > 0) {
                log?.invoke(
                    "click_focused_mirror_reject reason='${mirrorResolve.reason}' rejectSummary='${mirrorResolve.rejectSummary}'"
                )
            }
        } else {
            log?.invoke("click_focused_mirror_resolve attempted=false")
        }

        val shouldTryWrapperRecovery =
            focusedAccessibleFocused &&
                focusedFocusable &&
                !isClickable(effectiveFocusedNode) &&
                focusedSubtreeEmpty &&
                focusedSmallTopTarget &&
                rootNode != null
        if (shouldTryWrapperRecovery) {
            log?.invoke(
                "[click_focused_wrapper_recovery_start] focusedResourceId='$focusedResourceId' focusedClass='$focusedClassName' focusedBounds='${focusedBounds.toShortString()}' topRegionBottom=$topRegionBottom"
            )
            data class WrapperCandidate<T>(
                val node: T,
                val bounds: Rect,
                val reason: String,
                val priority: Int,
                val score: Int,
                val distance: Long
            )
            val candidatePicks = mutableListOf<WrapperCandidate<T>>()
            val queue = ArrayDeque<T>()
            rootNode?.let(queue::add)
            while (queue.isNotEmpty()) {
                val node = queue.removeFirst()
                val childCount = childCountOf(node)
                for (index in 0 until childCount) {
                    childAt(node, index)?.let(queue::add)
                }
                if (node == effectiveFocusedNode) continue
                val nodeResourceId = resourceIdOf(node).orEmpty()
                val nodeClassName = classNameOf(node).orEmpty()
                val bounds = boundsOf(node)
                if (bounds.isEmpty) {
                    log?.invoke("[click_focused_wrapper_recovery_reject] reason='invalid_bounds' resourceId='$nodeResourceId' class='$nodeClassName'")
                    continue
                }
                val clickableNode = isClickable(node)
                val enabledNode = isEnabled(node)
                val visibleNode = isVisible(node)
                if (!clickableNode || !enabledNode || !visibleNode) {
                    log?.invoke(
                        "[click_focused_wrapper_recovery_reject] reason='state_mismatch' resourceId='$nodeResourceId' class='$nodeClassName' clickable=$clickableNode enabled=$enabledNode visible=$visibleNode bounds='${bounds.toShortString()}'"
                    )
                    continue
                }
                val candidateCenterX = bounds.centerX()
                val candidateCenterY = bounds.centerY()
                val inTopBand = bounds.top <= topRegionBottom && candidateCenterY <= topRegionBottom
                if (!inTopBand) {
                    log?.invoke(
                        "[click_focused_wrapper_recovery_reject] reason='top_band_mismatch' resourceId='$nodeResourceId' class='$nodeClassName' bounds='${bounds.toShortString()}'"
                    )
                    continue
                }
                val nodeArea = maxOf(1, bounds.width() * bounds.height())
                val areaRatio = nodeArea.toDouble() / focusedArea.toDouble()
                val rootContainmentRatio = nodeArea.toDouble() / rootArea.toDouble()
                val classLower = nodeClassName.lowercase()
                val giantContainer = areaRatio >= 28.0 ||
                    (rootContainmentRatio >= 0.62 &&
                        bounds.width() >= (rootBounds.width() * 0.88).toInt() &&
                        bounds.height() >= (rootBounds.height() * 0.58).toInt()) ||
                    ((classLower.endsWith("scrollview") ||
                        classLower.endsWith("recyclerview") ||
                        classLower.endsWith("listview") ||
                        classLower.endsWith("nestedscrollview")) && rootContainmentRatio >= 0.62)
                if (giantContainer) {
                    log?.invoke(
                        "[click_focused_wrapper_recovery_reject] reason='giant_container' resourceId='$nodeResourceId' class='$nodeClassName' bounds='${bounds.toShortString()}'"
                    )
                    continue
                }
                val insideFocused = focusedBounds.contains(bounds)
                val overlapRect = Rect(bounds)
                val overlapExists = overlapRect.intersect(focusedBounds)
                val overlapArea = if (overlapExists) overlapRect.width() * overlapRect.height() else 0
                val overlapRatio = if (overlapExists) overlapArea.toDouble() / minOf(nodeArea, focusedArea).toDouble() else 0.0
                val dx = (focusedCenterX - candidateCenterX).toLong()
                val dy = (focusedCenterY - candidateCenterY).toLong()
                val distance = (dx * dx) + (dy * dy)
                val nearCenter = distance <= (maxOf(72, focusedBounds.width()) * maxOf(72, focusedBounds.width())).toLong()
                val priority = when {
                    insideFocused -> 3
                    overlapRatio >= 0.35 -> 2
                    nearCenter -> 1
                    else -> 0
                }
                if (priority == 0) {
                    log?.invoke(
                        "[click_focused_wrapper_recovery_reject] reason='weak_geometry' resourceId='$nodeResourceId' class='$nodeClassName' bounds='${bounds.toShortString()}' overlapRatio=$overlapRatio distance=$distance"
                    )
                    continue
                }
                val score = (priority * 1000) - minOf(900, distance.toInt() / 12) - minOf(240, (areaRatio * 16.0).toInt())
                val reason = when (priority) {
                    3 -> "inside_focused_bounds"
                    2 -> "strong_overlap"
                    else -> "near_center"
                }
                log?.invoke(
                    "[click_focused_wrapper_recovery_candidate] resourceId='$nodeResourceId' class='$nodeClassName' bounds='${bounds.toShortString()}' reason='$reason' priority=$priority overlapRatio=$overlapRatio distance=$distance score=$score"
                )
                candidatePicks += WrapperCandidate(
                    node = node,
                    bounds = bounds,
                    reason = reason,
                    priority = priority,
                    score = score,
                    distance = distance
                )
            }

            val wrapperPick = candidatePicks.maxWithOrNull(
                compareBy<WrapperCandidate<T>> { it.priority }
                    .thenBy { it.score }
                    .thenByDescending { it.distance }
            )
            if (wrapperPick != null) {
                log?.invoke(
                    "[click_focused_wrapper_recovery_pick] resourceId='${resourceIdOf(wrapperPick.node).orEmpty()}' class='${classNameOf(wrapperPick.node).orEmpty()}' bounds='${wrapperPick.bounds.toShortString()}' reason='${wrapperPick.reason}' priority=${wrapperPick.priority} score=${wrapperPick.score}"
                )
                if (performClick(wrapperPick.node)) {
                    return ClickExecutionResult(
                        success = true,
                        reason = "Wrapper recovery clickable node clicked",
                        path = ClickPath.WRAPPER_RECOVERY,
                        clickedNode = wrapperPick.node,
                        attemptedNode = wrapperPick.node,
                        mirrorNode = resolvedMirrorNode
                    )
                }
                log?.invoke(
                    "[click_focused_wrapper_recovery_reject] reason='perform_click_failed' resourceId='${resourceIdOf(wrapperPick.node).orEmpty()}' class='${classNameOf(wrapperPick.node).orEmpty()}' bounds='${wrapperPick.bounds.toShortString()}'"
                )
            }
        }

        val descendantRetarget = findMatchingClickableFromRootByDescendantHint(
            rootNode = rootNode,
            focusedBounds = focusedBounds,
            hint = descendantHint,
            childCountOf = childCountOf,
            childAt = childAt,
            isClickable = isClickable,
            isVisible = isVisible,
            isEnabled = isEnabled,
            boundsOf = boundsOf,
            resourceIdOf = resourceIdOf,
            classNameOf = classNameOf,
            contentDescOf = contentDescOf,
            textOf = textOf
        )
        if (descendantRetarget != null && performClick(descendantRetarget)) {
            return ClickExecutionResult(
                success = true,
                reason = "Clickable descendant metadata retarget clicked",
                path = ClickPath.DESCENDANT,
                clickedNode = descendantRetarget,
                attemptedNode = descendantRetarget,
                mirrorNode = resolvedMirrorNode
            )
        }

        val ancestor = findFirstClickableAncestor(
            node = effectiveFocusedNode,
            parentOf = parentOf,
            isClickable = isClickable,
            isVisible = isVisible,
            isEnabled = isEnabled,
            boundsOf = boundsOf
        )
        if (ancestor != null && performClick(ancestor)) {
            return ClickExecutionResult(
                success = true,
                reason = "Clickable ancestor clicked",
                path = ClickPath.ANCESTOR,
                clickedNode = ancestor,
                attemptedNode = ancestor,
                mirrorNode = resolvedMirrorNode
            )
        }

        val rootRetarget = findBestClickableFromRoot(
            focusedNode = effectiveFocusedNode,
            rootNode = rootNode,
            childCountOf = childCountOf,
            childAt = childAt,
            isClickable = isClickable,
            isVisible = isVisible,
            isEnabled = isEnabled,
            boundsOf = boundsOf,
            resourceIdOf = resourceIdOf,
            classNameOf = classNameOf,
            contentDescOf = contentDescOf,
            textOf = textOf
        )
        log?.invoke(
            "click_focused_root_retarget candidates=${rootRetarget.candidateCount} focusedResourceId='$focusedResourceId' focusedClass='$focusedClassName' focusedBounds='${focusedBounds.toShortString()}'"
        )
        log?.invoke(
            "click_focused_root_candidates inside=${rootRetarget.insideCount} overlap=${rootRetarget.overlapCount} local=${rootRetarget.localBandCount} global=${rootRetarget.globalCount} focusedBounds='${focusedBounds.toShortString()}'"
        )
        if (rootRetarget.node != null) {
            val candidateBounds = boundsOf(rootRetarget.node)
            log?.invoke(
                "click_focused_root_pick resourceId='${resourceIdOf(rootRetarget.node).orEmpty()}' class='${classNameOf(rootRetarget.node).orEmpty()}' bounds='${candidateBounds.toShortString()}' reason='${rootRetarget.selectedReason}' score=${rootRetarget.selectedScore}"
            )
            if (performClick(rootRetarget.node)) {
                return ClickExecutionResult(
                    success = true,
                    reason = "Retargeted clickable node clicked from root tree",
                    path = ClickPath.ROOT_RETARGET,
                    clickedNode = rootRetarget.node,
                    attemptedNode = rootRetarget.node,
                    mirrorNode = resolvedMirrorNode
                )
            }
        }

        val semanticMirror = resolveSemanticMirrorFromRoot(
            focusedNode = effectiveFocusedNode,
            rootNode = rootNode,
            childCountOf = childCountOf,
            childAt = childAt,
            isClickable = isClickable,
            isVisible = isVisible,
            isEnabled = isEnabled,
            boundsOf = boundsOf,
            resourceIdOf = resourceIdOf,
            classNameOf = classNameOf,
            contentDescOf = contentDescOf,
            textOf = textOf,
            log = log
        )
        if (semanticMirror.node != null && performClick(semanticMirror.node)) {
            return ClickExecutionResult(
                success = true,
                reason = "Semantic mirror clickable node clicked",
                path = ClickPath.SEMANTIC_MIRROR,
                clickedNode = semanticMirror.node,
                attemptedNode = semanticMirror.node,
                mirrorNode = resolvedMirrorNode
            )
        }

        return ClickExecutionResult(
            success = false,
            reason = "No clickable node found from focused node subtree or root tree",
            path = ClickPath.NONE,
            clickedNode = null,
            attemptedNode = rootRetarget.node ?: ancestor ?: descendant ?: effectiveFocusedNode,
            mirrorNode = resolvedMirrorNode
        )
    }

    private data class RootRetargetPick<T>(
        val node: T?,
        val candidateCount: Int,
        val insideCount: Int,
        val overlapCount: Int,
        val localBandCount: Int,
        val globalCount: Int,
        val selectedReason: String,
        val selectedScore: Int
    )

    private data class DescendantHint(
        val resourceId: String?,
        val className: String?,
        val contentDescription: String?,
        val text: String?
    )

    private data class MirrorResolveResult<T>(
        val node: T?,
        val candidateCount: Int,
        val localCandidateCount: Int,
        val globalCandidateCount: Int,
        val giantFilteredCount: Int,
        val reason: String,
        val score: Int,
        val rejectSummary: String
    )

    private data class SemanticMirrorResult<T>(
        val node: T?,
        val score: Int,
        val candidates: Int,
        val reason: String
    )

    private fun semanticTokens(vararg rawValues: String?): Set<String> {
        val rawTokens = rawValues.flatMap { raw ->
            raw
                .orEmpty()
                .lowercase()
                .replace(Regex("[^a-z0-9]+"), "_")
                .split("_")
                .filter { it.isNotBlank() }
        }
        if (rawTokens.isEmpty()) return emptySet()
        val normalized = mutableSetOf<String>()
        for (token in rawTokens) {
            val normalizedToken = when {
                token.endsWith("ies") && token.length > 4 -> token.dropLast(3) + "y"
                token.endsWith("s") && token.length > 4 -> token.dropLast(1)
                else -> token
            }
            if (normalizedToken.isBlank()) continue
            normalized += normalizedToken
            when (normalizedToken) {
                "btn" -> normalized += "button"
                "img" -> normalized += "image"
                "icon" -> normalized += "image"
            }
        }
        return normalized
    }

    private fun wrapperCoreTokens(tokens: Set<String>): Set<String> {
        val wrapperLikeTokens = setOf("layout", "container", "wrapper", "view", "group", "frame", "relative")
        return tokens.filterTo(mutableSetOf()) { it !in wrapperLikeTokens }
    }

    private fun <T> resolveMirrorNodeFromRoot(
        focusedNode: T,
        rootNode: T?,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        isClickable: (T) -> Boolean,
        isVisible: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        boundsOf: (T) -> Rect,
        resourceIdOf: (T) -> String?,
        classNameOf: (T) -> String?,
        contentDescOf: (T) -> String?,
        textOf: (T) -> String?,
        log: ((String) -> Unit)? = null
    ): MirrorResolveResult<T> {
        val focusedBounds = boundsOf(focusedNode)
        if (focusedBounds.isEmpty) return MirrorResolveResult(null, 0, 0, 0, 0, "invalid_focused_bounds", Int.MIN_VALUE, "invalid_focused_bounds")
        val focusedResourceId = resourceIdOf(focusedNode).orEmpty()
        val focusedClassName = classNameOf(focusedNode).orEmpty()
        val focusedContentDesc = contentDescOf(focusedNode).orEmpty()
        val focusedText = textOf(focusedNode).orEmpty()
        val focusedCenterX = focusedBounds.centerX()
        val focusedCenterY = focusedBounds.centerY()
        val focusedArea = maxOf(1, focusedBounds.width() * focusedBounds.height())
        val rootBounds = boundsOf(rootNode ?: focusedNode)
        val rootArea = maxOf(1, rootBounds.width() * rootBounds.height())
        val rootHeight = maxOf(1, rootBounds.height())
        val rootWidth = maxOf(1, rootBounds.width())
        val localMaxDx = minOf(maxOf(120, focusedBounds.width() * 3), maxOf(220, rootWidth / 2))
        val localMaxDyBase = minOf(maxOf(120, focusedBounds.height() * 3), maxOf(220, rootHeight / 2))
        val focusedTopRegion = focusedCenterY <= rootBounds.top + (rootHeight / 3)
        val focusedSmallTopTarget = focusedTopRegion && focusedArea <= (rootArea / 28)
        val localMaxDy = if (focusedSmallTopTarget) {
            minOf(localMaxDyBase, maxOf(140, focusedBounds.height() * 2))
        } else {
            localMaxDyBase
        }
        val localMarginX = localMaxDx
        val localMarginY = localMaxDy
        val localBandRect = Rect(
            focusedBounds.left - localMarginX,
            focusedBounds.top - localMarginY,
            focusedBounds.right + localMarginX,
            focusedBounds.bottom + localMarginY
        )
        val topRegionBottom = minOf(
            rootBounds.bottom,
            maxOf(rootBounds.top + (rootHeight / 6), focusedBounds.bottom + maxOf(180, focusedBounds.height() * 2))
        )
        if (focusedTopRegion) {
            localBandRect.top = rootBounds.top
            localBandRect.bottom = minOf(localBandRect.bottom, topRegionBottom)
        }
        log?.invoke(
            "click_focused_mirror_locality focusedCenter='$focusedCenterX,$focusedCenterY' maxDx=$localMaxDx maxDy=$localMaxDy topRegion=$focusedTopRegion smallTopTarget=$focusedSmallTopTarget localBand='${localBandRect.toShortString()}' topRegionBottom=$topRegionBottom"
        )

        data class ScoredMirror<T>(
            val node: T,
            val score: Int,
            val distance: Long,
            val localBand: Boolean,
            val reason: String
        )

        data class MirrorCandidate<T>(
            val node: T,
            val bounds: Rect,
            val nodeClassName: String,
            val clickable: Boolean,
            val candidateCenterX: Int,
            val candidateCenterY: Int,
            val dxAbs: Int,
            val dyAbs: Int,
            val areaRatio: Double,
            val overlap: Boolean,
            val contains: Boolean,
            val centerInBounds: Boolean,
            val isLeaf: Boolean,
            val nonClickableLeaf: Boolean,
            val looksLikeHeavyContainer: Boolean,
            val almostFullScreenContainer: Boolean
        )

        val queue = ArrayDeque<T>()
        val allCandidates = mutableListOf<MirrorCandidate<T>>()
        val seenCandidateKeys = mutableSetOf<String>()
        val localCandidates = mutableListOf<ScoredMirror<T>>()
        var giantFilteredCount = 0
        var giantClassFilteredCount = 0
        var giantAreaFilteredCount = 0

        fun enqueueChildren(
            source: T,
            targetQueue: ArrayDeque<T>,
            expansionTag: String? = null
        ) {
            val parentResourceId = resourceIdOf(source).orEmpty()
            val parentClassName = classNameOf(source).orEmpty()
            val childCount = childCountOf(source)
            if (expansionTag != null) {
                log?.invoke(
                    "[$expansionTag] parentResourceId='${parentResourceId}' class='${parentClassName}' childCount=$childCount"
                )
            }
            for (index in 0 until childCount) {
                val firstChild = childAt(source, index)
                val resolvedChild = firstChild ?: childAt(source, index)
                val childResourceId = resolvedChild?.let { resourceIdOf(it).orEmpty() }.orEmpty()
                val childClassName = resolvedChild?.let { classNameOf(it).orEmpty() }.orEmpty()
                val enqueued = resolvedChild != null
                resolvedChild?.let(targetQueue::add)
                if (expansionTag != null) {
                    log?.invoke(
                        "[click_focused_local_raw_child] parentResourceId='${parentResourceId}' index=$index childResourceId='${childResourceId}' childClass='${childClassName}' childNull=${resolvedChild == null} enqueued=$enqueued"
                    )
                }
            }
        }

        fun shouldCollectFocusedDescendantCandidate(
            candidate: T,
            bounds: Rect,
            nodeClassName: String
        ): Boolean {
            if (!isClickable(candidate)) return false
            val classLower = nodeClassName.lowercase()
            val classEligible = classLower.endsWith("imagebutton") ||
                classLower.endsWith("button") ||
                classLower.endsWith("viewgroup")
            if (!classEligible) return false
            val nearMarginX = maxOf(96, focusedBounds.width())
            val nearMarginY = maxOf(96, focusedBounds.height())
            val expandedFocusedBounds = Rect(
                focusedBounds.left - nearMarginX,
                focusedBounds.top - nearMarginY,
                focusedBounds.right + nearMarginX,
                focusedBounds.bottom + nearMarginY
            )
            return focusedBounds.contains(bounds) ||
                bounds.contains(focusedBounds) ||
                Rect.intersects(focusedBounds, bounds) ||
                Rect.intersects(expandedFocusedBounds, bounds)
        }

        fun collectCandidate(
            node: T,
            logPrefix: String = "click_focused_candidate_seen",
            source: String = "root_tree"
        ) {
            if (node == focusedNode) return
            if (!isVisible(node)) return
            val bounds = boundsOf(node)
            if (bounds.isEmpty) return

            val nodeClassName = classNameOf(node).orEmpty()
            val clickableNode = isClickable(node)
            val candidateKey = "${resourceIdOf(node).orEmpty()}|$nodeClassName|${bounds.toShortString()}|$clickableNode"
            if (!seenCandidateKeys.add(candidateKey)) return

            val candidateCenterX = bounds.centerX()
            val candidateCenterY = bounds.centerY()
            val dxAbs = kotlin.math.abs(focusedCenterX - candidateCenterX)
            val dyAbs = kotlin.math.abs(focusedCenterY - candidateCenterY)
            val overlap = Rect.intersects(focusedBounds, bounds)
            val contains = focusedBounds.contains(bounds) || bounds.contains(focusedBounds)
            val centerInBounds = bounds.contains(focusedCenterX, focusedCenterY) ||
                focusedBounds.contains(candidateCenterX, candidateCenterY)
            val nodeArea = maxOf(1, bounds.width() * bounds.height())
            val areaRatio = nodeArea.toDouble() / focusedArea.toDouble()
            val classLower = nodeClassName.lowercase()
            val looksLikeHeavyContainer = classLower.endsWith("scrollview") ||
                classLower.endsWith("recyclerview") ||
                classLower.endsWith("listview") ||
                classLower.endsWith("nestedscrollview")
            val rootContainmentRatio = if (rootArea > 0) nodeArea.toDouble() / rootArea.toDouble() else 0.0
            val almostFullScreenContainer = rootContainmentRatio >= 0.62 &&
                bounds.width() >= (rootBounds.width() * 0.88).toInt() &&
                bounds.height() >= (rootBounds.height() * 0.58).toInt()
            val isLeaf = childCountOf(node) == 0
            val simpleLeaf = classLower.endsWith("textview") || classLower.endsWith("imageview")
            val nonClickableLeaf = isLeaf && simpleLeaf && !clickableNode

            log?.invoke(
                "[$logPrefix] resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}' source='$source'"
            )
            if (source == "raw_descendant") {
                log?.invoke(
                    "[click_focused_candidate_pass_stage] stage='raw_descendant_collected' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
                )
            }
            if (source == "local_raw_search") {
                log?.invoke(
                    "[click_focused_candidate_pass_stage] stage='local_raw_collected' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
                )
            }
            log?.invoke(
                "[click_focused_candidate_pass_stage] stage='collected' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
            )

            allCandidates += MirrorCandidate(
                node = node,
                bounds = bounds,
                nodeClassName = nodeClassName,
                clickable = clickableNode,
                candidateCenterX = candidateCenterX,
                candidateCenterY = candidateCenterY,
                dxAbs = dxAbs,
                dyAbs = dyAbs,
                areaRatio = areaRatio,
                overlap = overlap,
                contains = contains,
                centerInBounds = centerInBounds,
                isLeaf = isLeaf,
                nonClickableLeaf = nonClickableLeaf,
                looksLikeHeavyContainer = looksLikeHeavyContainer,
                almostFullScreenContainer = almostFullScreenContainer
            )
        }

        var rawDescendantCollectedCount = 0
        if (!isClickable(focusedNode)) {
            log?.invoke(
                "[click_focused_descendant_scan_start] nodeResourceId='${focusedResourceId}' childCount=${childCountOf(focusedNode)} source='resolved_raw_focus'"
            )
            val focusedQueue = ArrayDeque<T>()
            enqueueChildren(focusedNode, focusedQueue)
            while (focusedQueue.isNotEmpty()) {
                val node = focusedQueue.removeFirst()
                enqueueChildren(node, focusedQueue)
                val bounds = boundsOf(node)
                val nodeClassName = classNameOf(node).orEmpty()
                if (bounds.isEmpty) continue
                if (!shouldCollectFocusedDescendantCandidate(node, bounds, nodeClassName)) continue
                collectCandidate(node, logPrefix = "click_focused_descendant_candidate_seen", source = "raw_descendant")
                rawDescendantCollectedCount += 1
            }
        }

        if (!isClickable(focusedNode) && rawDescendantCollectedCount == 0 && rootNode != null) {
            val localSearchBounds = Rect(localBandRect)
            val focusedCenter = "${focusedCenterX},${focusedCenterY}"
            log?.invoke(
                "[click_focused_local_raw_search_start] focusedBounds='${focusedBounds.toShortString()}' focusedCenter='$focusedCenter' topRegion=$focusedTopRegion localSearchBounds='${localSearchBounds.toShortString()}'"
            )
            val localQueue = ArrayDeque<T>()
            localQueue += rootNode
            var seenSettingWrapper = false
            var seenSettingsImage = false
            var seenSettingsBadge = false
            val nearFocusedBounds = Rect(
                focusedBounds.left - maxOf(120, focusedBounds.width() * 2),
                focusedBounds.top - maxOf(120, focusedBounds.height() * 2),
                focusedBounds.right + maxOf(120, focusedBounds.width() * 2),
                focusedBounds.bottom + maxOf(120, focusedBounds.height() * 2)
            )
            while (localQueue.isNotEmpty()) {
                val node = localQueue.removeFirst()
                enqueueChildren(node, localQueue, expansionTag = "click_focused_local_raw_expand")
                if (node == focusedNode) continue
                val bounds = boundsOf(node)
                val clickableNode = isClickable(node)
                val visibleNode = isVisible(node)
                val enabledNode = isEnabled(node)
                val nodeClassName = classNameOf(node).orEmpty()
                val nodeResourceId = resourceIdOf(node).orEmpty()
                if (nodeResourceId.endsWith(":id/setting_button_layout")) {
                    seenSettingWrapper = true
                }
                if (nodeResourceId.endsWith(":id/settings_image")) {
                    seenSettingsImage = true
                }
                if (nodeResourceId.endsWith(":id/settings_new_badge")) {
                    seenSettingsBadge = true
                }
                if (bounds.isEmpty) {
                    log?.invoke(
                        "[click_focused_local_raw_candidate_skip] reason='invalid_bounds' resourceId='${nodeResourceId}' class='${nodeClassName}' source='local_raw_search'"
                    )
                    continue
                }
                val candidateCenterX = bounds.centerX()
                val candidateCenterY = bounds.centerY()
                val dxAbs = kotlin.math.abs(focusedCenterX - candidateCenterX)
                val dyAbs = kotlin.math.abs(focusedCenterY - candidateCenterY)
                val insideFocused = focusedBounds.contains(bounds) || focusedBounds.contains(candidateCenterX, candidateCenterY)
                val overlapFocused = Rect.intersects(focusedBounds, bounds)
                val nearCenter = dxAbs <= maxOf(72, focusedBounds.width()) && dyAbs <= maxOf(72, focusedBounds.height())
                val wrapperContainment = bounds.contains(focusedBounds) || focusedBounds.contains(bounds)
                val nearFocused = Rect.intersects(nearFocusedBounds, bounds)
                val inLocalBand = Rect.intersects(localSearchBounds, bounds) || localSearchBounds.contains(candidateCenterX, candidateCenterY)
                val inTopRegionBand = bounds.top <= topRegionBottom && candidateCenterY <= topRegionBottom
                log?.invoke(
                    "[click_focused_local_raw_scan_node] resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode enabled=$enabledNode visible=$visibleNode bounds='${bounds.toShortString()}' center='${candidateCenterX},${candidateCenterY}' dx=$dxAbs dy=$dyAbs inLocalBounds=$inLocalBand topRegionBand=$inTopRegionBand source='local_raw_search'"
                )
                if (!clickableNode) {
                    log?.invoke(
                        "[click_focused_local_raw_candidate_skip] reason='not_clickable' resourceId='${nodeResourceId}' class='${nodeClassName}' bounds='${bounds.toShortString()}' source='local_raw_search'"
                    )
                    continue
                }
                if (!visibleNode) {
                    log?.invoke(
                        "[click_focused_local_raw_candidate_skip] reason='not_visible' resourceId='${nodeResourceId}' class='${nodeClassName}' bounds='${bounds.toShortString()}' source='local_raw_search'"
                    )
                    continue
                }
                if (!enabledNode) {
                    log?.invoke(
                        "[click_focused_local_raw_candidate_skip] reason='not_enabled' resourceId='${nodeResourceId}' class='${nodeClassName}' bounds='${bounds.toShortString()}' source='local_raw_search'"
                    )
                    continue
                }
                if (focusedTopRegion && !inTopRegionBand && !insideFocused && !overlapFocused) {
                    log?.invoke(
                        "[click_focused_local_raw_candidate_skip] reason='top_region_mismatch' resourceId='${nodeResourceId}' class='${nodeClassName}' bounds='${bounds.toShortString()}' source='local_raw_search'"
                    )
                    continue
                }
                val nodeArea = maxOf(1, bounds.width() * bounds.height())
                if (nodeArea > focusedArea * 8) {
                    log?.invoke(
                        "[click_focused_local_raw_candidate_skip] reason='oversized_local' resourceId='${nodeResourceId}' class='${nodeClassName}' bounds='${bounds.toShortString()}' source='local_raw_search'"
                    )
                    continue
                }
                val nodeClassNameLower = nodeClassName.lowercase()
                val preferredClass = nodeClassNameLower.endsWith("imagebutton") ||
                    nodeClassNameLower.endsWith("button") ||
                    nodeClassNameLower.endsWith("imageview") ||
                    nodeClassNameLower.endsWith("viewgroup")
                val localGeometryMatch = insideFocused || overlapFocused || nearCenter || wrapperContainment || nearFocused || inLocalBand
                val classGatePass = if (preferredClass) {
                    localGeometryMatch
                } else {
                    insideFocused || overlapFocused || nearCenter
                }
                if (!classGatePass) {
                    log?.invoke(
                        "[click_focused_local_raw_candidate_skip] reason='class_gate_miss' resourceId='${nodeResourceId}' class='${nodeClassName}' bounds='${bounds.toShortString()}' source='local_raw_search'"
                    )
                    continue
                }
                collectCandidate(
                    node = node,
                    logPrefix = "click_focused_local_raw_candidate_seen",
                    source = "local_raw_search"
                )
            }
            log?.invoke(
                "[click_focused_local_raw_toolbar_summary] seenSettingWrapper=$seenSettingWrapper seenSettingsImage=$seenSettingsImage seenSettingsBadge=$seenSettingsBadge"
            )
        }

        if (rootNode != null) {
            queue += rootNode
        }
        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            enqueueChildren(node, queue)
            collectCandidate(node)
        }

        for (candidate in allCandidates) {
            val node = candidate.node
            val bounds = candidate.bounds
            val nodeClassName = candidate.nodeClassName
            val candidateCenterX = candidate.candidateCenterX
            val candidateCenterY = candidate.candidateCenterY
            val dxAbs = candidate.dxAbs
            val dyAbs = candidate.dyAbs
            val areaRatio = candidate.areaRatio
            val overlap = candidate.overlap
            val contains = candidate.contains
            val centerInBounds = candidate.centerInBounds
            val clickableNode = candidate.clickable
            val looksLikeHeavyContainer = candidate.looksLikeHeavyContainer
            val almostFullScreenContainer = candidate.almostFullScreenContainer
            val nonClickableLeaf = candidate.nonClickableLeaf

            if (looksLikeHeavyContainer && almostFullScreenContainer) {
                giantFilteredCount += 1
                giantClassFilteredCount += 1
                log?.invoke(
                    "[click_focused_candidate_reject] reason='giant_container' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
                )
                continue
            }
            if (areaRatio >= 28.0 || (almostFullScreenContainer && areaRatio >= 10.0)) {
                giantFilteredCount += 1
                giantAreaFilteredCount += 1
                log?.invoke(
                    "[click_focused_candidate_reject] reason='giant_container' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
                )
                continue
            }
            log?.invoke(
                "[click_focused_candidate_pass_stage] stage='giant_pass' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
            )

            val localBand = Rect.intersects(localBandRect, bounds) ||
                localBandRect.contains(candidateCenterX, candidateCenterY)
            val candidateInTopRegion = bounds.top <= topRegionBottom && candidateCenterY <= topRegionBottom
            if (focusedSmallTopTarget && !candidateInTopRegion) {
                log?.invoke(
                    "[click_focused_candidate_reject] reason='top_region_mismatch' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
                )
                continue
            }
            if (!focusedSmallTopTarget && !localBand) {
                log?.invoke(
                    "[click_focused_candidate_reject] reason='top_region_mismatch' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
                )
                continue
            }
            log?.invoke(
                "[click_focused_candidate_pass_stage] stage='top_region_pass' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
            )

            val relaxedDx = localMaxDx + maxOf(80, focusedBounds.width() * 2)
            val relaxedDy = localMaxDy + maxOf(120, focusedBounds.height() * 2)
            val localityPass = if (clickableNode) {
                if (focusedSmallTopTarget && candidateInTopRegion) {
                    (dxAbs <= relaxedDx && dyAbs <= localMaxDy) ||
                        (dxAbs <= localMaxDx && dyAbs <= relaxedDy) ||
                        (dxAbs <= localMaxDx && dyAbs <= localMaxDy)
                } else {
                    dxAbs <= localMaxDx && dyAbs <= localMaxDy
                }
            } else {
                dxAbs <= localMaxDx && dyAbs <= localMaxDy
            }
            if (!localityPass) {
                val rejectReason = when {
                    dxAbs > localMaxDx && dyAbs > localMaxDy -> "dx_exceeded"
                    dxAbs > localMaxDx -> "dx_exceeded"
                    else -> "dy_exceeded"
                }
                log?.invoke(
                    "[click_focused_candidate_reject] reason='${rejectReason}' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
                )
                continue
            }

            val strictLeafDx = maxOf(72, focusedBounds.width())
            val strictLeafDy = maxOf(72, focusedBounds.height())
            if (nonClickableLeaf && (dxAbs > strictLeafDx || dyAbs > strictLeafDy)) {
                log?.invoke(
                    "[click_focused_candidate_reject] reason='far_leaf' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
                )
                continue
            }
            log?.invoke(
                "[click_focused_candidate_pass_stage] stage='locality_pass' resourceId='${resourceIdOf(node).orEmpty()}' class='${nodeClassName}' clickable=$clickableNode bounds='${bounds.toShortString()}'"
            )

            var score = 0
            val reasonTokens = mutableListOf<String>()
            if (localBand || (focusedSmallTopTarget && candidateInTopRegion)) {
                score += 540
                reasonTokens += "local_band"
            } else {
                score -= 260
            }
            score += when {
                areaRatio <= 2.2 -> 300
                areaRatio <= 4.0 -> 170
                areaRatio <= 8.0 -> 20
                else -> -200
            }
            if (areaRatio > 12.0) score -= minOf(520, (areaRatio * 18.0).toInt())
            val nodeResourceId = resourceIdOf(node).orEmpty()
            if (focusedResourceId.isNotEmpty() && focusedResourceId == nodeResourceId) {
                score += 500
                reasonTokens += "same_resource"
            }
            if (contains) {
                score += 320
                reasonTokens += "contains"
            }
            if (overlap) {
                score += 240
                reasonTokens += "overlap"
            }
            if (centerInBounds) {
                score += 200
                reasonTokens += "center_match"
            }
            if (focusedClassName.isNotEmpty() && focusedClassName == nodeClassName) {
                score += 120
                reasonTokens += "same_class"
            }
            val nodeContentDesc = contentDescOf(node).orEmpty()
            if (focusedContentDesc.isNotEmpty() && focusedContentDesc == nodeContentDesc) {
                score += 90
                reasonTokens += "same_content_desc"
            }
            val nodeText = textOf(node).orEmpty()
            if (focusedText.isNotEmpty() && focusedText == nodeText) {
                score += 90
                reasonTokens += "same_text"
            }
            val childCount = childCountOf(node)
            if (childCount > 0) {
                score += minOf(40, childCount * 4)
                reasonTokens += "has_children"
            }
            if (focusedSmallTopTarget && candidateInTopRegion) {
                score += 120
                reasonTokens += "same_top_region"
            }
            if (nonClickableLeaf) {
                score -= 260
                reasonTokens += "leaf_penalty"
            }
            if (looksLikeHeavyContainer) score -= 420
            if (clickableNode) {
                score += 120
                reasonTokens += "clickable"
            }

            val dx = (focusedCenterX - candidateCenterX).toLong()
            val dy = (focusedCenterY - candidateCenterY).toLong()
            val distance = (dx * dx) + (dy * dy)
            score -= minOf(320, (distance / 5000L).toInt())
            if (score < 240) continue

            val scoredMirror = ScoredMirror(
                node = node,
                score = score,
                distance = distance,
                localBand = localBand,
                reason = reasonTokens.joinToString(separator = "+").ifBlank { "score_only" }
            )
            localCandidates += scoredMirror
        }

        val preferredPool = localCandidates
        val best = preferredPool.maxWithOrNull { a, b ->
            when {
                a.score != b.score -> a.score - b.score
                a.distance < b.distance -> 1
                a.distance > b.distance -> -1
                else -> 0
            }
        }
        val totalCandidates = localCandidates.size
        val rejectSummary = "giant_class=$giantClassFilteredCount giant_area=$giantAreaFilteredCount"
        val reason = when {
            best == null && giantFilteredCount > 0 && totalCandidates == 0 -> "giant_only_rejected"
            best == null -> "no_candidate"
            else -> "local_${best.reason}"
        }

        return MirrorResolveResult(
            node = best?.node,
            candidateCount = totalCandidates,
            localCandidateCount = localCandidates.size,
            globalCandidateCount = 0,
            giantFilteredCount = giantFilteredCount,
            reason = reason,
            score = best?.score ?: Int.MIN_VALUE,
            rejectSummary = rejectSummary
        )
    }

    private fun <T> resolveSemanticMirrorFromRoot(
        focusedNode: T,
        rootNode: T?,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        isClickable: (T) -> Boolean,
        isVisible: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        boundsOf: (T) -> Rect,
        resourceIdOf: (T) -> String?,
        classNameOf: (T) -> String?,
        contentDescOf: (T) -> String?,
        textOf: (T) -> String?,
        log: ((String) -> Unit)? = null
    ): SemanticMirrorResult<T> {
        if (rootNode == null) {
            log?.invoke("[click_focused_semantic_resolve] attempted=false candidates=0 selected='' score=${Int.MIN_VALUE} reason='root_null'")
            return SemanticMirrorResult(node = null, score = Int.MIN_VALUE, candidates = 0, reason = "root_null")
        }
        val focusedBounds = boundsOf(focusedNode)
        if (focusedBounds.isEmpty) {
            log?.invoke("[click_focused_semantic_resolve] attempted=false candidates=0 selected='' score=${Int.MIN_VALUE} reason='invalid_focused_bounds'")
            return SemanticMirrorResult(node = null, score = Int.MIN_VALUE, candidates = 0, reason = "invalid_focused_bounds")
        }
        val rootBounds = boundsOf(rootNode)
        val rootArea = maxOf(1, rootBounds.width() * rootBounds.height())
        val focusedArea = maxOf(1, focusedBounds.width() * focusedBounds.height())
        val focusedCenterX = focusedBounds.centerX()
        val focusedCenterY = focusedBounds.centerY()
        val rootHeight = maxOf(1, rootBounds.height())
        val rootWidth = maxOf(1, rootBounds.width())
        val focusedResourceId = resourceIdOf(focusedNode).orEmpty()
        val focusedClassName = classNameOf(focusedNode).orEmpty()
        val focusedTokens = semanticTokens(focusedResourceId, focusedClassName, contentDescOf(focusedNode), textOf(focusedNode))
        val focusedCoreTokens = wrapperCoreTokens(focusedTokens)
        val focusedTopRegion = focusedCenterY <= rootBounds.top + (rootHeight / 3)
        val focusedSmallTarget = focusedTopRegion && focusedArea <= (rootArea / 28)
        val topRegionBottom = minOf(
            rootBounds.bottom,
            maxOf(rootBounds.top + (rootHeight / 6), focusedBounds.bottom + maxOf(180, focusedBounds.height() * 2))
        )
        val focusedRightRegion = focusedCenterX >= rootBounds.left + ((rootWidth * 2) / 3)

        log?.invoke(
            "[click_focused_semantic_search_start] focusedResourceId='$focusedResourceId' focusedClass='$focusedClassName' focusedBounds='${focusedBounds.toShortString()}' normalizedTokens='${focusedCoreTokens.sorted().joinToString(",")}' topRegion=$focusedTopRegion smallTarget=$focusedSmallTarget"
        )

        data class SemanticCandidate<T>(
            val node: T,
            val score: Int,
            val resourceId: String,
            val className: String,
            val bounds: Rect
        )

        var candidates = 0
        var best: SemanticCandidate<T>? = null
        val queue = ArrayDeque<T>()
        queue += rootNode
        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            val childCount = childCountOf(node)
            for (index in 0 until childCount) {
                childAt(node, index)?.let(queue::add)
            }
            if (node == focusedNode) continue

            val clickable = isClickable(node)
            val visible = isVisible(node)
            val enabled = isEnabled(node)
            if (!clickable || !visible || !enabled) continue

            val bounds = boundsOf(node)
            if (bounds.isEmpty) continue
            val resourceId = resourceIdOf(node).orEmpty()
            val className = classNameOf(node).orEmpty()
            val classLower = className.lowercase()
            val nodeArea = maxOf(1, bounds.width() * bounds.height())
            val areaRatio = nodeArea.toDouble() / focusedArea.toDouble()
            val rootRatio = nodeArea.toDouble() / rootArea.toDouble()
            val candidateCenterX = bounds.centerX()
            val candidateCenterY = bounds.centerY()
            val inTopRegion = bounds.top <= topRegionBottom && candidateCenterY <= topRegionBottom
            val inRightRegion = candidateCenterX >= rootBounds.left + ((rootWidth * 2) / 3)
            val centerDistance = kotlin.math.abs(focusedCenterX - candidateCenterX) + kotlin.math.abs(focusedCenterY - candidateCenterY)
            val overlap = Rect.intersects(focusedBounds, bounds)
            val contains = focusedBounds.contains(bounds) || bounds.contains(focusedBounds)

            val giantContainer = areaRatio >= 28.0 ||
                (rootRatio >= 0.62 &&
                    bounds.width() >= (rootBounds.width() * 0.88).toInt() &&
                    bounds.height() >= (rootBounds.height() * 0.58).toInt()) ||
                ((classLower.endsWith("scrollview") ||
                    classLower.endsWith("recyclerview") ||
                    classLower.endsWith("listview") ||
                    classLower.endsWith("nestedscrollview")) && rootRatio >= 0.62)
            if (giantContainer) {
                log?.invoke(
                    "[click_focused_semantic_candidate_reject] reason='giant_container' resourceId='$resourceId' class='$className' bounds='${bounds.toShortString()}'"
                )
                continue
            }
            if (areaRatio > 12.0 && !contains) {
                log?.invoke(
                    "[click_focused_semantic_candidate_reject] reason='oversized' resourceId='$resourceId' class='$className' bounds='${bounds.toShortString()}'"
                )
                continue
            }

            val candidateTokens = semanticTokens(resourceId, className, contentDescOf(node), textOf(node))
            val candidateCoreTokens = wrapperCoreTokens(candidateTokens)
            val tokenOverlap = focusedCoreTokens.intersect(candidateCoreTokens).size
            var tokenScore = tokenOverlap * 120
            if (focusedCoreTokens.isNotEmpty() && focusedCoreTokens.any { token ->
                    candidateCoreTokens.any { candidateToken ->
                        candidateToken.startsWith(token) || token.startsWith(candidateToken)
                    }
                }
            ) {
                tokenScore += 80
            }
            if (focusedResourceId.isNotBlank() && resourceId.isNotBlank()) {
                val focusedPackage = focusedResourceId.substringBefore("/").ifBlank { focusedResourceId.substringBefore(":id/") }
                val candidatePackage = resourceId.substringBefore("/").ifBlank { resourceId.substringBefore(":id/") }
                if (focusedPackage.isNotBlank() && focusedPackage == candidatePackage) tokenScore += 40
            }

            var classScore = 0
            if (classLower.endsWith("imagebutton") || classLower.endsWith("button")) classScore += 90
            if (classLower.endsWith("imageview")) classScore += 50
            if (classLower.endsWith("framelayout") || classLower.endsWith("relativelayout")) classScore += 20
            if (focusedClassName.isNotBlank() && focusedClassName == className) classScore += 40

            var spatialScore = 0
            if (overlap) spatialScore += 180
            if (contains) spatialScore += 220
            spatialScore += when {
                centerDistance <= 40 -> 200
                centerDistance <= 120 -> 140
                centerDistance <= 260 -> 80
                centerDistance <= 420 -> 20
                else -> -120
            }
            if (focusedSmallTarget && inTopRegion) spatialScore += 90
            if (focusedSmallTarget && focusedRightRegion && inRightRegion) spatialScore += 70

            val semanticScore = tokenScore + classScore
            val totalScore = semanticScore + spatialScore
            candidates += 1

            log?.invoke(
                "[click_focused_semantic_candidate_seen] resourceId='$resourceId' class='$className' clickable=$clickable bounds='${bounds.toShortString()}' tokenScore=$tokenScore spatialScore=$spatialScore semanticScore=$semanticScore totalScore=$totalScore"
            )

            val rejectReason = when {
                focusedSmallTarget && !inTopRegion && !overlap && !contains -> "top_region_mismatch"
                spatialScore < 40 -> "spatially_unrelated"
                tokenScore <= 0 && semanticScore < 90 -> "token_miss"
                totalScore < 280 -> "semantic_score_low"
                else -> null
            }
            if (rejectReason != null) {
                log?.invoke(
                    "[click_focused_semantic_candidate_reject] reason='$rejectReason' resourceId='$resourceId' class='$className' bounds='${bounds.toShortString()}'"
                )
                continue
            }
            if (best == null || totalScore > best.score) {
                best = SemanticCandidate(node = node, score = totalScore, resourceId = resourceId, className = className, bounds = bounds)
            }
        }

        if (best == null) {
            log?.invoke("[click_focused_semantic_resolve] attempted=true candidates=$candidates selected='' score=${Int.MIN_VALUE} reason='no_semantic_match'")
            return SemanticMirrorResult(node = null, score = Int.MIN_VALUE, candidates = candidates, reason = "no_semantic_match")
        }
        val bestCandidate = best ?: return SemanticMirrorResult(
            node = null,
            score = Int.MIN_VALUE,
            candidates = candidates,
            reason = "no_semantic_match"
        )

        log?.invoke(
            "[click_focused_semantic_resolve] attempted=true candidates=$candidates selected='${bestCandidate.resourceId}/${bestCandidate.className}/${bestCandidate.bounds.toShortString()}' score=${bestCandidate.score} reason='semantic_match'"
        )
        return SemanticMirrorResult(node = bestCandidate.node, score = bestCandidate.score, candidates = candidates, reason = "semantic_match")
    }

    private fun <T> findBestClickableFromRoot(
        focusedNode: T,
        rootNode: T?,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        isClickable: (T) -> Boolean,
        isVisible: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        boundsOf: (T) -> Rect,
        resourceIdOf: (T) -> String?,
        classNameOf: (T) -> String?,
        contentDescOf: (T) -> String?,
        textOf: (T) -> String?
    ): RootRetargetPick<T> {
        if (rootNode == null) {
            return RootRetargetPick(null, 0, 0, 0, 0, 0, "none", Int.MIN_VALUE)
        }
        val focusedBounds = boundsOf(focusedNode)
        if (focusedBounds.isEmpty) {
            return RootRetargetPick(null, 0, 0, 0, 0, 0, "none", Int.MIN_VALUE)
        }
        val focusedCenter = A11yTargetFinder.calculateBoundsCenter(focusedBounds)
        val focusedArea = maxOf(1, focusedBounds.width() * focusedBounds.height())
        val focusedResourceId = resourceIdOf(focusedNode)
        val focusedClassName = classNameOf(focusedNode)
        val focusedContentDesc = contentDescOf(focusedNode)
        val focusedText = textOf(focusedNode)
        val bandMargin = maxOf(focusedBounds.height() * 2, 80)
        val localBandTop = focusedBounds.top - bandMargin
        val localBandBottom = focusedBounds.bottom + bandMargin
        val rootBounds = boundsOf(rootNode)
        val rootHeight = maxOf(1, rootBounds.height())
        val rootArea = maxOf(1, rootBounds.width() * rootBounds.height())
        val focusedTopLocalTarget = focusedBounds.centerY() <= rootBounds.top + (rootHeight / 4) &&
            focusedArea <= (rootArea / 30)

        data class ScoredCandidate<T>(
            val node: T,
            val inside: Boolean,
            val overlap: Boolean,
            val localBand: Boolean,
            val distance: Long,
            val score: Int
        )

        val queue = ArrayDeque<T>()
        queue += rootNode
        val allCandidates = mutableListOf<ScoredCandidate<T>>()

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            for (index in 0 until childCountOf(node)) {
                val child = childAt(node, index) ?: continue
                queue += child
            }
            if (node == focusedNode) continue
            if (!isNodeClickableCandidate(node, isClickable, isVisible, isEnabled, boundsOf)) continue

            val candidateBounds = boundsOf(node)
            val candidateCenterX = candidateBounds.centerX()
            val candidateCenterY = candidateBounds.centerY()
            val inside = focusedBounds.contains(candidateBounds) || focusedBounds.contains(candidateCenterX, candidateCenterY)
            val overlapArea = if (Rect.intersects(focusedBounds, candidateBounds)) {
                val left = maxOf(focusedBounds.left, candidateBounds.left)
                val top = maxOf(focusedBounds.top, candidateBounds.top)
                val right = minOf(focusedBounds.right, candidateBounds.right)
                val bottom = minOf(focusedBounds.bottom, candidateBounds.bottom)
                maxOf(0, right - left) * maxOf(0, bottom - top)
            } else {
                0
            }
            val candidateArea = maxOf(1, candidateBounds.width() * candidateBounds.height())
            val overlapByFocused = overlapArea.toDouble() / focusedArea.toDouble()
            val overlapByCandidate = overlapArea.toDouble() / candidateArea.toDouble()
            val overlap = overlapArea > 0 && (overlapByFocused >= 0.2 || overlapByCandidate >= 0.1)
            val localBand = candidateCenterY in localBandTop..localBandBottom ||
                (candidateBounds.bottom >= localBandTop && candidateBounds.top <= localBandBottom)
            val distance = focusedCenter?.let { (fx, fy) ->
                val dx = (fx - candidateCenterX).toLong()
                val dy = (fy - candidateCenterY).toLong()
                (dx * dx) + (dy * dy)
            } ?: Long.MAX_VALUE

            var score = 0
            if (inside) score += 2200
            if (overlap) score += 1500
            if (localBand) score += 350
            if (overlapArea > 0) score += minOf(overlapArea / 80, 350)
            if (!focusedResourceId.isNullOrBlank() && focusedResourceId == resourceIdOf(node)) score += 200
            if (!focusedClassName.isNullOrBlank() && focusedClassName == classNameOf(node)) score += 80
            if (!focusedContentDesc.isNullOrBlank() && focusedContentDesc == contentDescOf(node)) score += 80
            if (!focusedText.isNullOrBlank() && focusedText == textOf(node)) score += 80
            if (candidateArea > focusedArea * 4) {
                val areaRatio = candidateArea.toDouble() / focusedArea.toDouble()
                score -= minOf(900, (areaRatio * 70.0).toInt())
            }
            if (candidateBounds.top > focusedBounds.bottom + bandMargin) score -= 700
            if (!localBand) score -= 250
            score -= minOf(700, (distance / 4000L).toInt())

            allCandidates += ScoredCandidate(
                node = node,
                inside = inside,
                overlap = overlap,
                localBand = localBand,
                distance = distance,
                score = score
            )
        }

        val insideCandidates = allCandidates.filter { it.inside }
        val overlapCandidates = allCandidates.filter { !it.inside && it.overlap }
        val localBandCandidates = allCandidates.filter { !it.inside && !it.overlap && it.localBand }
        val strictLocalBandCandidates = localBandCandidates.filter {
            isSafeLocalBandFallbackCandidate(
                focusedBounds = focusedBounds,
                focusedArea = focusedArea,
                candidateBounds = boundsOf(it.node)
            )
        }
        val (pool, reason) = when {
            insideCandidates.isNotEmpty() -> insideCandidates to "inside_bounds"
            overlapCandidates.isNotEmpty() -> overlapCandidates to "overlap_bounds"
            strictLocalBandCandidates.isNotEmpty() && !focusedTopLocalTarget -> strictLocalBandCandidates to "local_band"
            focusedTopLocalTarget -> emptyList<ScoredCandidate<T>>() to "none"
            else -> allCandidates to "global_fallback"
        }
        val picked = pool.maxWithOrNull { a, b ->
            when {
                a.score != b.score -> a.score - b.score
                a.distance < b.distance -> 1
                a.distance > b.distance -> -1
                else -> 0
            }
        }

        return RootRetargetPick(
            node = picked?.node,
            candidateCount = allCandidates.size,
            insideCount = insideCandidates.size,
            overlapCount = overlapCandidates.size,
            localBandCount = strictLocalBandCandidates.size,
            globalCount = allCandidates.size,
            selectedReason = reason,
            selectedScore = picked?.score ?: Int.MIN_VALUE
        )
    }

    private fun isSafeLocalBandFallbackCandidate(
        focusedBounds: Rect,
        focusedArea: Int,
        candidateBounds: Rect
    ): Boolean {
        val dx = kotlin.math.abs(focusedBounds.centerX() - candidateBounds.centerX())
        val dy = kotlin.math.abs(focusedBounds.centerY() - candidateBounds.centerY())
        val maxDx = maxOf(180, focusedBounds.width() * 2)
        val maxDy = maxOf(180, focusedBounds.height() * 2)
        if (dx > maxDx || dy > maxDy) return false
        val candidateArea = maxOf(1, candidateBounds.width() * candidateBounds.height())
        if (candidateArea > focusedArea * 6) return false
        return true
    }

    private fun <T> buildDescendantHint(
        focusedNode: T,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        isVisible: (T) -> Boolean,
        isClickable: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        resourceIdOf: (T) -> String?,
        classNameOf: (T) -> String?,
        contentDescOf: (T) -> String?,
        textOf: (T) -> String?,
        boundsOf: (T) -> Rect
    ): DescendantHint? {
        val metadata = A11yTraversalAnalyzer.collectActionableDescendantMetadata(
            container = focusedNode,
            childCountOf = childCountOf,
            childAt = childAt,
            isVisible = isVisible,
            isClickable = isClickable,
            isFocusable = { false },
            isEnabled = isEnabled,
            resourceIdOf = resourceIdOf,
            classNameOf = classNameOf,
            contentDescriptionOf = contentDescOf,
            textOf = textOf,
            boundsOf = boundsOf
        )
        if (!metadata.hasClickableDescendant) return null
        return DescendantHint(
            resourceId = metadata.actionableDescendantResourceId,
            className = metadata.actionableDescendantClassName,
            contentDescription = metadata.actionableDescendantContentDescription,
            text = textOf(focusedNode)
        )
    }

    private fun <T> findMatchingClickableFromRootByDescendantHint(
        rootNode: T?,
        focusedBounds: Rect,
        hint: DescendantHint?,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        isClickable: (T) -> Boolean,
        isVisible: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        boundsOf: (T) -> Rect,
        resourceIdOf: (T) -> String?,
        classNameOf: (T) -> String?,
        contentDescOf: (T) -> String?,
        textOf: (T) -> String?
    ): T? {
        if (rootNode == null || hint == null) return null
        data class Ranked<T>(val node: T, val score: Int, val distance: Long)
        val queue = ArrayDeque<T>()
        queue += rootNode
        var best: Ranked<T>? = null
        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            for (index in 0 until childCountOf(node)) {
                childAt(node, index)?.let(queue::add)
            }
            if (!isNodeClickableCandidate(node, isClickable, isVisible, isEnabled, boundsOf)) continue
            var score = 0
            if (!hint.resourceId.isNullOrBlank() && hint.resourceId == resourceIdOf(node)) score += 240
            if (!hint.className.isNullOrBlank() && hint.className == classNameOf(node)) score += 120
            if (!hint.contentDescription.isNullOrBlank() && hint.contentDescription == contentDescOf(node)) score += 120
            if (!hint.text.isNullOrBlank() && hint.text == textOf(node)) score += 60
            if (score < 120) continue
            val bounds = boundsOf(node)
            val dx = (focusedBounds.centerX() - bounds.centerX()).toLong()
            val dy = (focusedBounds.centerY() - bounds.centerY()).toLong()
            val distance = (dx * dx) + (dy * dy)
            val ranked = Ranked(node, score, distance)
            if (best == null ||
                ranked.score > best!!.score ||
                (ranked.score == best!!.score && ranked.distance < best!!.distance)
            ) {
                best = ranked
            }
        }
        return best?.node
    }

    internal fun <T> findFirstClickableDescendant(
        root: T,
        maxDepth: Int,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        isClickable: (T) -> Boolean,
        isVisible: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        boundsOf: (T) -> Rect
    ): T? {
        val queue = ArrayDeque<Pair<T, Int>>()
        queue += root to 0
        while (queue.isNotEmpty()) {
            val (current, depth) = queue.removeFirst()
            if (depth > 0 && isNodeClickableCandidate(current, isClickable, isVisible, isEnabled, boundsOf)) {
                return current
            }
            if (depth >= maxDepth) continue
            for (index in 0 until childCountOf(current)) {
                val child = childAt(current, index) ?: continue
                queue += child to (depth + 1)
            }
        }
        return null
    }

    internal fun <T> findFirstClickableAncestor(
        node: T,
        parentOf: (T) -> T?,
        isClickable: (T) -> Boolean,
        isVisible: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        boundsOf: (T) -> Rect
    ): T? {
        var parent = parentOf(node)
        while (parent != null) {
            if (isNodeClickableCandidate(parent, isClickable, isVisible, isEnabled, boundsOf)) {
                return parent
            }
            parent = parentOf(parent)
        }
        return null
    }

    private fun <T> isNodeClickableCandidate(
        node: T,
        isClickable: (T) -> Boolean,
        isVisible: (T) -> Boolean,
        isEnabled: (T) -> Boolean,
        boundsOf: (T) -> Rect
    ): Boolean {
        if (!isClickable(node) || !isVisible(node) || !isEnabled(node)) return false
        val bounds = boundsOf(node)
        return !bounds.isEmpty
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
