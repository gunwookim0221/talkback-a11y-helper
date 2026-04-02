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
        private const val VERSION = "1.4.0"
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
        ANCESTOR("ancestor"),
        ROOT_RETARGET("root_retarget"),
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
            childCountOf = { it.childCount },
            childAt = { node, index -> node.getChild(index) },
            parentOf = { it.parent },
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

    internal fun <T> executeClickFromFocusedNode(
        focusedNode: T?,
        rootNode: T?,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        parentOf: (T) -> T?,
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

        val focusedBounds = boundsOf(focusedNode)
        val focusedResourceId = resourceIdOf(focusedNode).orEmpty()
        val focusedClassName = classNameOf(focusedNode).orEmpty()

        if (isNodeClickableCandidate(focusedNode, isClickable, isVisible, isEnabled, boundsOf) && performClick(focusedNode)) {
            return ClickExecutionResult(
                success = true,
                reason = "Focused node clicked",
                path = ClickPath.DIRECT,
                clickedNode = focusedNode,
                attemptedNode = focusedNode
            )
        }

        val descendant = findFirstClickableDescendant(
            root = focusedNode,
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
            focusedNode = focusedNode,
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
        val focusedSubtreeChildCount = childCountOf(focusedNode)
        val focusedSubtreeEmpty = focusedSubtreeChildCount == 0
        val shouldTryMirrorResolve = focusedSubtreeEmpty && descendantHint == null
        log?.invoke(
            "click_focused_subtree_state empty=$focusedSubtreeEmpty mirrorResolvePlanned=$shouldTryMirrorResolve focusedChildCount=$focusedSubtreeChildCount"
        )

        var resolvedMirrorNode: T? = null
        if (shouldTryMirrorResolve) {
            val mirrorResolve = resolveMirrorNodeFromRoot(
                focusedNode = focusedNode,
                rootNode = rootNode,
                childCountOf = childCountOf,
                childAt = childAt,
                isVisible = isVisible,
                boundsOf = boundsOf,
                resourceIdOf = resourceIdOf,
                classNameOf = classNameOf,
                contentDescOf = contentDescOf,
                textOf = textOf
            )
            resolvedMirrorNode = mirrorResolve.node
            log?.invoke(
                "click_focused_mirror_resolve attempted=true candidates=${mirrorResolve.candidateCount} reason='${mirrorResolve.reason}' score=${mirrorResolve.score}"
            )
            if (resolvedMirrorNode != null) {
                val mirrorBounds = boundsOf(resolvedMirrorNode)
                log?.invoke(
                    "click_focused_mirror_pick resourceId='${resourceIdOf(resolvedMirrorNode).orEmpty()}' class='${classNameOf(resolvedMirrorNode).orEmpty()}' bounds='${mirrorBounds.toShortString()}'"
                )
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
            }
        } else {
            log?.invoke("click_focused_mirror_resolve attempted=false")
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
            node = focusedNode,
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
            focusedNode = focusedNode,
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

        return ClickExecutionResult(
            success = false,
            reason = "No clickable node found from focused node subtree or root tree",
            path = ClickPath.NONE,
            clickedNode = null,
            attemptedNode = rootRetarget.node ?: ancestor ?: descendant ?: focusedNode,
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
        val reason: String,
        val score: Int
    )

    private fun <T> resolveMirrorNodeFromRoot(
        focusedNode: T,
        rootNode: T?,
        childCountOf: (T) -> Int,
        childAt: (T, Int) -> T?,
        isVisible: (T) -> Boolean,
        boundsOf: (T) -> Rect,
        resourceIdOf: (T) -> String?,
        classNameOf: (T) -> String?,
        contentDescOf: (T) -> String?,
        textOf: (T) -> String?
    ): MirrorResolveResult<T> {
        if (rootNode == null) return MirrorResolveResult(null, 0, "no_root", Int.MIN_VALUE)
        val focusedBounds = boundsOf(focusedNode)
        if (focusedBounds.isEmpty) return MirrorResolveResult(null, 0, "invalid_focused_bounds", Int.MIN_VALUE)
        val focusedResourceId = resourceIdOf(focusedNode).orEmpty()
        val focusedClassName = classNameOf(focusedNode).orEmpty()
        val focusedContentDesc = contentDescOf(focusedNode).orEmpty()
        val focusedText = textOf(focusedNode).orEmpty()
        val focusedCenterX = focusedBounds.centerX()
        val focusedCenterY = focusedBounds.centerY()
        val focusedArea = maxOf(1, focusedBounds.width() * focusedBounds.height())

        data class ScoredMirror<T>(
            val node: T,
            val score: Int,
            val distance: Long,
            val reason: String
        )

        val queue = ArrayDeque<T>()
        queue += rootNode
        var candidates = 0
        var best: ScoredMirror<T>? = null

        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            for (index in 0 until childCountOf(node)) {
                childAt(node, index)?.let(queue::add)
            }
            if (node == focusedNode) continue
            if (!isVisible(node)) continue

            val bounds = boundsOf(node)
            if (bounds.isEmpty) continue

            val overlap = Rect.intersects(focusedBounds, bounds)
            val contains = focusedBounds.contains(bounds) || bounds.contains(focusedBounds)
            val centerInBounds = bounds.contains(focusedCenterX, focusedCenterY) ||
                focusedBounds.contains(bounds.centerX(), bounds.centerY())
            val nodeArea = maxOf(1, bounds.width() * bounds.height())

            var score = 0
            val reasonTokens = mutableListOf<String>()
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
            val nodeClassName = classNameOf(node).orEmpty()
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
                score += minOf(90, childCount * 20)
                reasonTokens += "has_children"
            }
            if (nodeArea > focusedArea * 8) {
                score -= 220
            }

            val dx = (focusedCenterX - bounds.centerX()).toLong()
            val dy = (focusedCenterY - bounds.centerY()).toLong()
            val distance = (dx * dx) + (dy * dy)
            score -= minOf(300, (distance / 4500L).toInt())
            if (score < 220) continue

            candidates += 1
            val scoredMirror = ScoredMirror(
                node = node,
                score = score,
                distance = distance,
                reason = reasonTokens.joinToString(separator = "+").ifBlank { "score_only" }
            )
            if (best == null ||
                scoredMirror.score > best!!.score ||
                (scoredMirror.score == best!!.score && scoredMirror.distance < best!!.distance)
            ) {
                best = scoredMirror
            }
        }

        return MirrorResolveResult(
            node = best?.node,
            candidateCount = candidates,
            reason = best?.reason ?: "no_candidate",
            score = best?.score ?: Int.MIN_VALUE
        )
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
