package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

object FocusLabelBuilder {
    data class LabelNode(
        val text: String? = null,
        val contentDescription: String? = null,
        val children: List<LabelNode> = emptyList()
    )

    fun buildMergedLabel(root: LabelNode?): String {
        if (root == null) return ""
        val labels = linkedSetOf<String>()
        addCandidate(labels, root.text)
        addCandidate(labels, root.contentDescription)

        if (labels.isEmpty()) {
            collectChildLabels(root.children, labels)
        }
        return labels.joinToString(separator = " ")
    }

    private fun collectChildLabels(children: List<LabelNode>, labels: LinkedHashSet<String>) {
        children.forEach { child ->
            addCandidate(labels, child.text)
            addCandidate(labels, child.contentDescription)
            collectChildLabels(child.children, labels)
        }
    }

    private fun addCandidate(labels: LinkedHashSet<String>, value: String?) {
        value?.trim()?.takeIf { it.isNotEmpty() }?.let(labels::add)
    }
}

data class FocusChildNode(
    val text: String?,
    val contentDescription: String?,
    val className: String?,
    val viewIdResourceName: String?,
    val clickable: Boolean,
    val focusable: Boolean,
    val accessibilityFocused: Boolean,
    val visibleToUser: Boolean,
    val boundsInScreen: Rect,
    val children: List<FocusChildNode>
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("text", text ?: JSONObject.NULL)
            put("contentDescription", contentDescription ?: JSONObject.NULL)
            put("className", className ?: JSONObject.NULL)
            put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
            put("clickable", clickable)
            put("focusable", focusable)
            put("accessibilityFocused", accessibilityFocused)
            put("visibleToUser", visibleToUser)
            put(
                "boundsInScreen", JSONObject().apply {
                    put("l", boundsInScreen.left)
                    put("t", boundsInScreen.top)
                    put("r", boundsInScreen.right)
                    put("b", boundsInScreen.bottom)
                }
            )
            put(
                "children", JSONArray().apply {
                    children.forEach { put(it.toJson()) }
                }
            )
        }
    }

    companion object {
        private const val MAX_CHILDREN_PER_NODE = 12

        fun fromNode(
            node: AccessibilityNodeInfo,
            maxDepth: Int,
            currentDepth: Int = 1
        ): FocusChildNode {
            val rect = Rect()
            node.getBoundsInScreen(rect)
            val childSnapshots = if (currentDepth >= maxDepth) {
                emptyList()
            } else {
                val limit = minOf(node.childCount, MAX_CHILDREN_PER_NODE)
                (0 until limit).mapNotNull { index ->
                    node.getChild(index)?.let { child ->
                        fromNode(child, maxDepth = maxDepth, currentDepth = currentDepth + 1)
                    }
                }
            }

            return FocusChildNode(
                text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString(),
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                clickable = node.isClickable,
                focusable = node.isFocusable,
                accessibilityFocused = node.isAccessibilityFocused,
                visibleToUser = node.isVisibleToUser,
                boundsInScreen = rect,
                children = childSnapshots
            )
        }
    }
}

data class A11yNodeInfo(
    val text: String?,
    val contentDescription: String?,
    val className: String?,
    val viewIdResourceName: String?,
    val boundsInScreen: Rect,
    val clickable: Boolean,
    val focusable: Boolean,
    val isVisibleToUser: Boolean,
    val focused: Boolean,
    val accessibilityFocused: Boolean,
    val isTopAppBar: Boolean,
    val isBottomNavigationBar: Boolean
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("text", text ?: JSONObject.NULL)
            put("contentDescription", contentDescription ?: JSONObject.NULL)
            put("className", className ?: JSONObject.NULL)
            put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
            put(
                "boundsInScreen", JSONObject().apply {
                    put("l", boundsInScreen.left)
                    put("t", boundsInScreen.top)
                    put("r", boundsInScreen.right)
                    put("b", boundsInScreen.bottom)
                }
            )
            put("clickable", clickable)
            put("focusable", focusable)
            put("isVisibleToUser", isVisibleToUser)
            put("focused", focused)
            put("accessibilityFocused", accessibilityFocused)
            put("isTopAppBar", isTopAppBar)
            put("isBottomNavigationBar", isBottomNavigationBar)
        }
    }
}

data class A11yDumpResponse(
    val algorithmVersion: String,
    val canScrollDown: Boolean,
    val nodes: List<A11yNodeInfo>
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("algorithmVersion", algorithmVersion)
            put("canScrollDown", canScrollDown)
            put(
                "nodes", JSONArray().apply {
                    nodes.forEach { put(it.toJson()) }
                }
            )
        }
    }
}

data class FocusSnapshot(
    val timestamp: Long,
    val schemaVersion: String,
    val packageName: String?,
    val className: String?,
    val viewIdResourceName: String?,
    val text: String?,
    val contentDescription: String?,
    val mergedLabel: String,
    val talkbackLabel: String,
    val clickable: Boolean,
    val focusable: Boolean,
    val focused: Boolean,
    val accessibilityFocused: Boolean,
    val visibleToUser: Boolean,
    val selected: Boolean,
    val checkable: Boolean,
    val checked: Boolean,
    val enabled: Boolean,
    val boundsInScreen: Rect,
    val children: List<FocusChildNode>
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("timestamp", timestamp)
            put("schemaVersion", schemaVersion)
            put("packageName", packageName ?: JSONObject.NULL)
            put("className", className ?: JSONObject.NULL)
            put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
            put("text", text ?: JSONObject.NULL)
            put("contentDescription", contentDescription ?: JSONObject.NULL)
            put("mergedLabel", mergedLabel)
            put("talkbackLabel", talkbackLabel)
            put("clickable", clickable)
            put("focusable", focusable)
            put("focused", focused)
            put("accessibilityFocused", accessibilityFocused)
            put("visibleToUser", visibleToUser)
            put("isVisibleToUser", visibleToUser)
            put("selected", selected)
            put("checkable", checkable)
            put("checked", checked)
            put("enabled", enabled)
            put(
                "boundsInScreen", JSONObject().apply {
                    put("l", boundsInScreen.left)
                    put("t", boundsInScreen.top)
                    put("r", boundsInScreen.right)
                    put("b", boundsInScreen.bottom)
                }
            )
            put(
                "children", JSONArray().apply {
                    children.forEach { put(it.toJson()) }
                }
            )
        }
    }

    companion object {
        const val GET_FOCUS_SCHEMA_VERSION: String = "1.1.0"
        private const val FOCUS_CHILD_MAX_DEPTH = 3

        fun fromNodeOrNull(node: AccessibilityNodeInfo?): FocusSnapshot? {
            return node?.let { fromNode(it) }
        }

        fun fromNode(node: AccessibilityNodeInfo): FocusSnapshot {
            val rootChildSnapshot = FocusChildNode.fromNode(node, maxDepth = FOCUS_CHILD_MAX_DEPTH)
            val mergedLabel = FocusLabelBuilder.buildMergedLabel(rootChildSnapshot.toLabelNode())
            return FocusSnapshot(
                timestamp = System.currentTimeMillis(),
                schemaVersion = GET_FOCUS_SCHEMA_VERSION,
                packageName = node.packageName?.toString(),
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString(),
                mergedLabel = mergedLabel,
                talkbackLabel = mergedLabel,
                clickable = node.isClickable,
                focusable = node.isFocusable,
                focused = node.isFocused,
                accessibilityFocused = node.isAccessibilityFocused,
                visibleToUser = node.isVisibleToUser,
                selected = node.isSelected,
                checkable = node.isCheckable,
                checked = node.isChecked,
                enabled = node.isEnabled,
                boundsInScreen = rootChildSnapshot.boundsInScreen,
                children = rootChildSnapshot.children
            )
        }

        private fun FocusChildNode.toLabelNode(): FocusLabelBuilder.LabelNode {
            return FocusLabelBuilder.LabelNode(
                text = text,
                contentDescription = contentDescription,
                children = children.map { it.toLabelNode() }
            )
        }
    }
}
