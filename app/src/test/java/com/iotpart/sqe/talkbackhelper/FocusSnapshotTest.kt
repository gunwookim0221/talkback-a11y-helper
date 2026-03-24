package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.json.JSONObject
import org.junit.Test

class FocusSnapshotTest {

    @Test
    fun toJson_containsExpectedFields() {
        val snapshot = FocusSnapshot(
            timestamp = 1234L,
            schemaVersion = "1.1.0",
            packageName = "com.test",
            className = "android.widget.Button",
            viewIdResourceName = "com.test:id/ok",
            text = "확인",
            contentDescription = "확인 버튼",
            mergedLabel = "확인",
            talkbackLabel = "확인",
            clickable = true,
            focusable = true,
            focused = false,
            accessibilityFocused = true,
            visibleToUser = true,
            selected = false,
            checkable = false,
            checked = false,
            enabled = true,
            boundsInScreen = Rect(1, 2, 3, 4),
            children = emptyList()
        )

        val json = snapshot.toJson()

        assertEquals(1234L, json.getLong("timestamp"))
        assertEquals("1.1.0", json.getString("schemaVersion"))
        assertEquals("com.test", json.getString("packageName"))
        assertEquals("확인", json.getString("text"))
        assertTrue(json.getBoolean("accessibilityFocused"))
        assertEquals("확인", json.getString("mergedLabel"))
        assertEquals("확인", json.getString("talkbackLabel"))
        assertTrue(json.getBoolean("visibleToUser"))

        val bounds = json.getJSONObject("boundsInScreen")
        assertEquals(1, bounds.getInt("l"))
        assertEquals(4, bounds.getInt("b"))
    }

    @Test
    fun toJson_supportsNullables() {
        val snapshot = FocusSnapshot(
            timestamp = 1L,
            schemaVersion = "1.1.0",
            packageName = null,
            className = null,
            viewIdResourceName = null,
            text = null,
            contentDescription = null,
            mergedLabel = "",
            talkbackLabel = "",
            clickable = false,
            focusable = false,
            focused = false,
            accessibilityFocused = false,
            visibleToUser = false,
            selected = false,
            checkable = false,
            checked = false,
            enabled = false,
            boundsInScreen = Rect(0, 0, 0, 0),
            children = emptyList()
        )

        val json = snapshot.toJson()
        assertEquals(JSONObject.NULL, json.get("packageName"))
        assertEquals(JSONObject.NULL, json.get("text"))
    }
}
