package com.example.a11yhelper

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
        val targetIndex: Int
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
            if (matchesTarget(node, query)) {
                if (matchCount != query.targetIndex) {
                    matchCount += 1
                } else {
                    val success = node.performAction(action)
                    val actionName = when (action) {
                        AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS -> "ACTION_ACCESSIBILITY_FOCUS"
                        AccessibilityNodeInfo.ACTION_CLICK -> "ACTION_CLICK"
                        AccessibilityNodeInfo.ACTION_LONG_CLICK -> "ACTION_LONG_CLICK"
                        else -> "ACTION_$action"
                    }
                    return TargetActionOutcome(
                        success = success,
                        reason = if (success) "$actionName success" else "$actionName failed",
                        target = node
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
            if (matchesTarget(node, query)) {
                if (matchCount == query.targetIndex) {
                    return TargetActionOutcome(success = true, reason = "Target node found", target = node)
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
        query: TargetQuery
    ): Boolean {
        val targetName = query.targetName.trim()
        val targetType = query.targetType.lowercase().trim()
        val byText = nodeText?.trim()?.contains(targetName) == true
        val byTalkback = nodeContentDescription?.trim()?.contains(targetName) == true
        val regexSpecialChars = Regex("[\\\\.^$|?*+()\\[\\]{}]")
        val regexPattern = if (regexSpecialChars.containsMatchIn(targetName)) {
            targetName
        } else {
            "^${Regex.escape(targetName)}$"
        }
        val byResourceId = nodeViewId?.let { viewId ->
            runCatching { Regex(regexPattern) }
                .getOrNull()
                ?.matches(viewId)
                ?: false
        } ?: false

        return when (targetType) {
            "t" -> byText
            "b" -> byTalkback
            "r" -> byResourceId
            "a" -> byText || byTalkback || byResourceId
            else -> false
        }
    }

    private fun matchesTarget(node: AccessibilityNodeInfo, query: TargetQuery): Boolean {
        val text = node.text?.toString()
        val description = node.contentDescription?.toString()
        return matchesTarget(text, description, node.viewIdResourceName, query)
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
