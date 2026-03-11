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
        val targetText: String?,
        val targetViewId: String?,
        val targetClassName: String?
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

        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            if (matchesTarget(node, query)) {
                val success = node.performAction(action)
                val actionName = when (action) {
                    AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS -> "ACTION_ACCESSIBILITY_FOCUS"
                    AccessibilityNodeInfo.ACTION_CLICK -> "ACTION_CLICK"
                    else -> "ACTION_$action"
                }
                return TargetActionOutcome(
                    success = success,
                    reason = if (success) "$actionName success" else "$actionName failed",
                    target = node
                )
            }

            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }

        return TargetActionOutcome(false, "Target node not found")
    }

    fun matchesTarget(
        nodeText: String?,
        nodeViewId: String?,
        nodeClassName: String?,
        query: TargetQuery
    ): Boolean {
        val normalizedTargetText = query.targetText?.trim()?.takeIf { it.isNotEmpty() }
        if (normalizedTargetText != null) {
            val normalizedNodeText = nodeText?.trim() ?: return false
            if (!normalizedNodeText.contains(normalizedTargetText)) {
                return false
            }
        }
        if (!query.targetViewId.isNullOrBlank() && query.targetViewId != nodeViewId) {
            return false
        }
        if (!query.targetClassName.isNullOrBlank() && query.targetClassName != nodeClassName) {
            return false
        }

        return true
    }

    private fun matchesTarget(node: AccessibilityNodeInfo, query: TargetQuery): Boolean {
        val text = node.text?.toString()
        val description = node.contentDescription?.toString()
        val className = node.className?.toString()
        val byText = matchesTarget(text, node.viewIdResourceName, className, query)
        val byDescription = matchesTarget(description, node.viewIdResourceName, className, query)
        return byText || byDescription
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
