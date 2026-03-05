package com.example.a11yhelper

import android.view.accessibility.AccessibilityNodeInfo

object A11yNavigator {
    data class NavOutcome(
        val success: Boolean,
        val reason: String,
        val fromIndex: Int,
        val targetIndex: Int,
        val targetNode: AccessibilityNodeInfo?
    )

    fun collectNavigableNodes(root: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> {
        if (root == null) return emptyList()
        val out = mutableListOf<AccessibilityNodeInfo>()
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)
        while (stack.isNotEmpty()) {
            val node = stack.removeLast()
            if (isNodeCandidate(node)) {
                out.add(node)
            }
            for (i in node.childCount - 1 downTo 0) {
                node.getChild(i)?.let { stack.add(it) }
            }
        }
        return out
    }

    fun navigate(root: AccessibilityNodeInfo?, direction: Int): NavOutcome {
        val nodes = collectNavigableNodes(root)
        if (nodes.isEmpty()) {
            return NavOutcome(false, "No navigable nodes", -1, -1, null)
        }
        val currentIdx = nodes.indexOfFirst { it.isAccessibilityFocused || it.isFocused }
        val anchor = if (currentIdx >= 0) currentIdx else if (direction > 0) -1 else nodes.size
        val targetIdx = anchor + direction

        if (targetIdx !in nodes.indices) {
            return NavOutcome(
                success = false,
                reason = "Reached boundary (nodes=${nodes.size}, current=$currentIdx, direction=$direction)",
                fromIndex = currentIdx,
                targetIndex = targetIdx,
                targetNode = null
            )
        }

        val target = nodes[targetIdx]
        val actionOk = target.performAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
        val reason = if (actionOk) "ACTION_ACCESSIBILITY_FOCUS success" else "ACTION_ACCESSIBILITY_FOCUS failed"

        return NavOutcome(
            success = actionOk,
            reason = reason,
            fromIndex = currentIdx,
            targetIndex = targetIdx,
            targetNode = target
        )
    }

    private fun isNodeCandidate(node: AccessibilityNodeInfo): Boolean {
        return node.isVisibleToUser && (node.isFocusable || node.isClickable || !node.text.isNullOrBlank() || !node.contentDescription.isNullOrBlank())
    }
}
