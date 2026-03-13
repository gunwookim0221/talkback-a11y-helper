package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

object A11yNavigator {
    data class TargetActionOutcome(
        val success: Boolean,
        val reason: String,
        val target: AccessibilityNodeInfo? = null
    )

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

    fun dumpTreeFlat(root: AccessibilityNodeInfo?): JSONArray {
        if (root == null) return JSONArray()

        val result = JSONArray()
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            result.put(nodeToJson(node))

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }
        return result
    }

    fun findAndPerformAction(
        root: AccessibilityNodeInfo?,
        query: TargetQuery,
        action: Int
    ): TargetActionOutcome {
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
                if (matchCount != query.targetIndex) {
                    matchCount += 1
                } else {
                    val success = targetNode.performAction(action)
                    val actionName = when (action) {
                        AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS -> "ACTION_ACCESSIBILITY_FOCUS"
                        AccessibilityNodeInfo.ACTION_CLICK -> "ACTION_CLICK"
                        AccessibilityNodeInfo.ACTION_LONG_CLICK -> "ACTION_LONG_CLICK"
                        else -> "ACTION_$action"
                    }
                    return TargetActionOutcome(
                        success = success,
                        reason = if (success) "$actionName success" else "$actionName failed",
                        target = targetNode
                    )
                }
            }

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }

        return TargetActionOutcome(false, "Target node not found")
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
            val pattern = runCatching { Regex(regexPattern) }.getOrNull()
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
            nodeText?.contains(targetText) == true || nodeContentDescription?.contains(targetText) == true
        } ?: true
        val targetIdMatch = query.targetId?.let { targetId ->
            isViewIdMatched(nodeViewId, targetId)
        } ?: true
        val classNameMatch = query.className?.let { queryClassName ->
            nodeClassName?.contains(queryClassName) == true
        } ?: true
        val clickableMatch = query.clickable?.let { expected ->
            nodeClickable == expected
        } ?: true
        val focusableMatch = query.focusable?.let { expected ->
            nodeFocusable == expected
        } ?: true

        return targetTextMatch && targetIdMatch && classNameMatch && clickableMatch && focusableMatch
    }

    fun findSwipeTarget(
        root: AccessibilityNodeInfo?,
        currentNode: AccessibilityNodeInfo?,
        forward: Boolean
    ): AccessibilityNodeInfo? {
        if (root == null) return null
        val traversalList = buildFocusableTraversalList(root)
        if (traversalList.isEmpty()) return null

        val resolvedCurrent = currentNode?.let {
            resolveToClickableAncestor(
                node = it,
                parentOf = { node -> node.parent },
                isClickable = { node -> node.isClickable }
            )
        }

        val currentIndex = resolvedCurrent?.let { resolved ->
            traversalList.indexOfFirst { it == resolved }
        } ?: -1

        val targetIndex = if (forward) {
            currentIndex + 1
        } else {
            if (currentIndex == -1) traversalList.lastIndex else currentIndex - 1
        }

        if (targetIndex !in traversalList.indices) return null
        return traversalList[targetIndex]
    }

    internal fun <T> resolveToClickableAncestor(
        node: T,
        parentOf: (T) -> T?,
        isClickable: (T) -> Boolean
    ): T {
        if (isClickable(node)) return node

        var current = parentOf(node)
        while (current != null) {
            if (isClickable(current)) return current
            current = parentOf(current)
        }
        return node
    }

    internal fun <T> buildGroupedTraversalList(
        nodesInOrder: List<T>,
        parentOf: (T) -> T?,
        isClickable: (T) -> Boolean,
        isFocusable: (T) -> Boolean,
        isVisible: (T) -> Boolean
    ): List<T> {
        val results = mutableListOf<T>()

        for (node in nodesInOrder) {
            if (!isVisible(node)) continue
            if (hasClickableAncestor(node, parentOf, isClickable)) continue
            if (!isClickable(node) && !isFocusable(node)) continue
            results += node
        }
        return results
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

        val resolvedNode = resolveToClickableAncestor(
            node = node,
            parentOf = { current -> current.parent },
            isClickable = { current -> current.isClickable }
        )

        query.clickable?.let { expected ->
            if (resolvedNode.isClickable != expected) return null
        }
        return resolvedNode
    }


    private fun <T> hasClickableAncestor(
        node: T,
        parentOf: (T) -> T?,
        isClickable: (T) -> Boolean
    ): Boolean {
        var parent = parentOf(node)
        while (parent != null) {
            if (isClickable(parent)) return true
            parent = parentOf(parent)
        }
        return false
    }

    private fun buildFocusableTraversalList(root: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        val nodesInOrder = mutableListOf<AccessibilityNodeInfo>()
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            nodesInOrder += node

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }

        return buildGroupedTraversalList(
            nodesInOrder = nodesInOrder,
            parentOf = { node -> node.parent },
            isClickable = { node -> node.isClickable },
            isFocusable = { node -> node.isFocusable },
            isVisible = { node -> node.isVisibleToUser }
        )
    }

    private fun isViewIdMatched(nodeViewId: String?, target: String): Boolean {
        val regexPattern = buildRegexPattern(target)
        return nodeViewId?.let { viewId ->
            runCatching { Regex(regexPattern) }
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

    private fun nodeToJson(node: AccessibilityNodeInfo): JSONObject {
        val rect = Rect()
        node.getBoundsInScreen(rect)

        return JSONObject().apply {
            put("text", node.text?.toString() ?: JSONObject.NULL)
            put("contentDescription", node.contentDescription?.toString() ?: JSONObject.NULL)
            put("className", node.className?.toString() ?: JSONObject.NULL)
            put("viewIdResourceName", node.viewIdResourceName ?: JSONObject.NULL)
            put(
                "boundsInScreen", JSONObject().apply {
                    put("l", rect.left)
                    put("t", rect.top)
                    put("r", rect.right)
                    put("b", rect.bottom)
                }
            )
            put("clickable", node.isClickable)
            put("focusable", node.isFocusable)
            put("isVisibleToUser", node.isVisibleToUser)
        }
    }
}
