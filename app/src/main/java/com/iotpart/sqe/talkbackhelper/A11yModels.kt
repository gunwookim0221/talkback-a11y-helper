package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

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
    val isSystemNavigationBar: Boolean
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
            put("isSystemNavigationBar", isSystemNavigationBar)
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
    val packageName: String?,
    val className: String?,
    val viewIdResourceName: String?,
    val text: String?,
    val contentDescription: String?,
    val clickable: Boolean,
    val focusable: Boolean,
    val focused: Boolean,
    val accessibilityFocused: Boolean,
    val selected: Boolean,
    val checkable: Boolean,
    val checked: Boolean,
    val enabled: Boolean,
    val boundsInScreen: Rect
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("timestamp", timestamp)
            put("packageName", packageName ?: JSONObject.NULL)
            put("className", className ?: JSONObject.NULL)
            put("viewIdResourceName", viewIdResourceName ?: JSONObject.NULL)
            put("text", text ?: JSONObject.NULL)
            put("contentDescription", contentDescription ?: JSONObject.NULL)
            put("clickable", clickable)
            put("focusable", focusable)
            put("focused", focused)
            put("accessibilityFocused", accessibilityFocused)
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
        }
    }

    companion object {
        fun fromNode(node: AccessibilityNodeInfo): FocusSnapshot {
            val rect = Rect()
            node.getBoundsInScreen(rect)
            return FocusSnapshot(
                timestamp = System.currentTimeMillis(),
                packageName = node.packageName?.toString(),
                className = node.className?.toString(),
                viewIdResourceName = node.viewIdResourceName,
                text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString(),
                clickable = node.isClickable,
                focusable = node.isFocusable,
                focused = node.isFocused,
                accessibilityFocused = node.isAccessibilityFocused,
                selected = node.isSelected,
                checkable = node.isCheckable,
                checked = node.isChecked,
                enabled = node.isEnabled,
                boundsInScreen = rect
            )
        }
    }
}
