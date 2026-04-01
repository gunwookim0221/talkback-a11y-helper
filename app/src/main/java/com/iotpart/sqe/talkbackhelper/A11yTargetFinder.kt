package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo

object A11yTargetFinder {
    private const val TAG = "A11Y_HELPER"
    const val VERSION: String = "1.0.4"

    data class TargetQuery(
        val targetName: String,
        val targetType: String,
        val targetIndex: Int,
        val className: String? = null,
        val clickable: Boolean? = null,
        val focusable: Boolean? = null,
        val targetText: String? = null,
        val targetId: String? = null
    )

    fun findAndPerformAction(
        root: AccessibilityNodeInfo?,
        query: TargetQuery,
        action: Int,
        reqId: String = "none"
    ): TargetActionOutcome {
        Log.d(
            TAG,
            "[DEBUG][TARGET_ACTION][find_start] reqId=$reqId target='${query.targetName}' type='${query.targetType}' index=${query.targetIndex} rootNull=${root == null}"
        )
        if (root == null) {
            Log.d(TAG, "[DEBUG][TARGET_ACTION][final] reqId=$reqId success=false reason='Root node is null'")
            return TargetActionOutcome(false, "Root node is null")
        }

        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)
        var matchCount = 0
        val matchedTargets = mutableListOf<AccessibilityNodeInfo>()

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            val targetNode = resolveMatchedTarget(node, query)
            if (targetNode != null) {
                if (matchCount >= query.targetIndex) {
                    matchedTargets += targetNode
                }
                matchCount += 1
            }

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }

        if (matchedTargets.isEmpty()) {
            Log.d(TAG, "[DEBUG][TARGET_ACTION][matches] reqId=$reqId count=0")
            Log.d(TAG, "[DEBUG][TARGET_ACTION][final] reqId=$reqId success=false reason='Target node not found'")
            return TargetActionOutcome(false, "Target node not found")
        }
        Log.d(TAG, "[DEBUG][TARGET_ACTION][matches] reqId=$reqId count=${matchedTargets.size}")

        val actionName = when (action) {
            AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS -> "ACTION_ACCESSIBILITY_FOCUS"
            AccessibilityNodeInfo.ACTION_CLICK -> "ACTION_CLICK"
            AccessibilityNodeInfo.ACTION_LONG_CLICK -> "ACTION_LONG_CLICK"
            else -> "ACTION_$action"
        }
        var lastAttemptedNode: AccessibilityNodeInfo? = null
        for ((candidateIndex, targetNode) in matchedTargets.withIndex()) {
            lastAttemptedNode = targetNode
            val bounds = Rect().also { targetNode.getBoundsInScreen(it) }.toShortString()
            Log.d(
                TAG,
                "[DEBUG][TARGET_ACTION][attempt] reqId=$reqId candidateIndex=$candidateIndex resourceId='${targetNode.viewIdResourceName.orEmpty()}' class='${targetNode.className?.toString().orEmpty()}' clickable=${targetNode.isClickable} focusable=${targetNode.isFocusable} visible=${targetNode.isVisibleToUser} bounds='$bounds'"
            )
            val success = targetNode.performAction(action)
            Log.d(
                TAG,
                "[DEBUG][TARGET_ACTION][attempt_result] reqId=$reqId candidateIndex=$candidateIndex action=$actionName success=$success"
            )
            if (success) {
                Log.d(
                    TAG,
                    "[DEBUG][TARGET_ACTION][final] reqId=$reqId success=true candidateIndex=$candidateIndex reason='matched_and_action_succeeded'"
                )
                return TargetActionOutcome(
                    success = true,
                    reason = "$actionName success",
                    target = targetNode,
                    attemptedResourceId = targetNode.viewIdResourceName,
                    attemptedClassName = targetNode.className?.toString()
                )
            }
        }

        val failedNode = lastAttemptedNode
        val failedResourceId = failedNode?.viewIdResourceName
        val failedClassName = failedNode?.className?.toString()
        val failedReason = "$actionName failed (resourceId=${failedResourceId ?: "null"}, class=${failedClassName ?: "null"})"
        Log.d(TAG, "[DEBUG][TARGET_ACTION][final] reqId=$reqId success=false reason='$failedReason'")
        return TargetActionOutcome(
            success = false,
            reason = failedReason,
            target = failedNode,
            attemptedResourceId = failedResourceId,
            attemptedClassName = failedClassName
        )
    }

    fun findTarget(root: AccessibilityNodeInfo?, query: TargetQuery): TargetActionOutcome {
        if (root == null) {
            return TargetActionOutcome(false, "Root node is null")
        }

        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)
        var matchCount = 0

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            val targetNode = resolveMatchedTarget(node, query)
            if (targetNode != null) {
                if (matchCount == query.targetIndex) {
                    return TargetActionOutcome(success = true, reason = "Target node found", target = targetNode)
                }
                matchCount += 1
            }

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }

        return TargetActionOutcome(false, "Target node not found")
    }

    fun matchesTarget(
        nodeText: String?,
        nodeContentDescription: String?,
        nodeViewId: String?,
        nodeClassName: String? = null,
        nodeClickable: Boolean? = null,
        nodeFocusable: Boolean? = null,
        query: TargetQuery
    ): Boolean {
        val targetName = query.targetName.trim()
        val targetType = query.targetType.lowercase().trim()
        val baseMatch = if (targetName.isNotBlank()) {
            val regexPattern = buildRegexPattern(targetName)
            val pattern = runCatching { Regex(regexPattern, setOf(RegexOption.IGNORE_CASE)) }.getOrNull()
            val byText = nodeText?.trim()?.let { text ->
                pattern?.containsMatchIn(text) ?: false
            } == true
            val byTalkback = nodeContentDescription?.trim()?.let { text ->
                pattern?.containsMatchIn(text) ?: false
            } == true
            val byResourceId = nodeViewId?.let { viewId ->
                pattern?.matches(viewId) ?: false
            } ?: false
            when (targetType) {
                "t" -> byText
                "b" -> byTalkback
                "r" -> byResourceId
                "a" -> byText || byTalkback || byResourceId
                else -> false
            }
        } else {
            true
        }

        if (!baseMatch) return false

        val targetTextMatch = query.targetText?.let { targetText ->
            nodeText?.contains(targetText, ignoreCase = true) == true || nodeContentDescription?.contains(targetText, ignoreCase = true) == true
        } ?: true
        val targetIdMatch = query.targetId?.let { targetId ->
            isViewIdMatched(nodeViewId, targetId)
        } ?: true
        val classNameMatch = query.className?.let { queryClassName ->
            nodeClassName?.contains(queryClassName, ignoreCase = true) == true
        } ?: true
        val clickableMatch = query.clickable?.let { expected ->
            nodeClickable == expected
        } ?: true
        val focusableMatch = query.focusable?.let { expected ->
            nodeFocusable == expected
        } ?: true

        return targetTextMatch && targetIdMatch && classNameMatch && clickableMatch && focusableMatch
    }

    private fun matchesTarget(node: AccessibilityNodeInfo, query: TargetQuery): Boolean {
        val text = node.text?.toString()
        val description = node.contentDescription?.toString()
        return matchesTarget(
            text,
            description,
            node.viewIdResourceName,
            node.className?.toString(),
            node.isClickable,
            node.isFocusable,
            query
        )
    }

    private fun resolveMatchedTarget(node: AccessibilityNodeInfo, query: TargetQuery): AccessibilityNodeInfo? {
        val queryWithoutClickable = if (query.clickable != null) query.copy(clickable = null) else query
        if (!matchesTarget(node, queryWithoutClickable)) return null

        val candidate = node
        val isCandidateInteractive = candidate.isClickable || candidate.isFocusable
        val effectiveTarget = if (
            candidate.childCount == 1 &&
            candidate.text.isNullOrBlank() &&
            candidate.contentDescription.isNullOrBlank() &&
            !isCandidateInteractive
        ) {
            candidate.getChild(0) ?: candidate
        } else {
            candidate
        }

        val resolvedNode = A11yNavigator.resolveToClickableAncestor(
            node = effectiveTarget,
            parentOf = { current -> current.parent },
            isClickable = { current -> current.isClickable }
        )

        query.clickable?.let { expected ->
            if (resolvedNode.isClickable != expected) return null
        }
        return resolvedNode
    }

    fun calculateBoundsCenter(bounds: Rect?): Pair<Int, Int>? {
        if (bounds == null || bounds.isEmpty) return null
        return bounds.centerX() to bounds.centerY()
    }

    private fun isViewIdMatched(nodeViewId: String?, target: String): Boolean {
        val regexPattern = buildRegexPattern(target)
        return nodeViewId?.let { viewId ->
            runCatching { Regex(regexPattern, setOf(RegexOption.IGNORE_CASE)) }
                .getOrNull()
                ?.matches(viewId)
                ?: false
        } ?: false
    }

    private fun isRegexPattern(target: String): Boolean {
        return target.contains(".*") ||
            target.contains(".+") ||
            target.contains("^") ||
            target.contains("$")
    }

    private fun buildRegexPattern(target: String): String {
        return if (isRegexPattern(target)) {
            target
        } else {
            "^${Regex.escape(target)}$"
        }
    }
}
