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
            packageName = "com.test",
            className = "android.widget.Button",
            viewIdResourceName = "com.test:id/ok",
            text = "확인",
            contentDescription = "확인 버튼",
            clickable = true,
            focusable = true,
            focused = false,
            accessibilityFocused = true,
            selected = false,
            checkable = false,
            checked = false,
            enabled = true,
            boundsInScreen = Rect(1, 2, 3, 4)
        )

        val json = snapshot.toJson()

        assertEquals(1234L, json.getLong("timestamp"))
        assertEquals("com.test", json.getString("packageName"))
        assertEquals("확인", json.getString("text"))
        assertTrue(json.getBoolean("accessibilityFocused"))

        val bounds = json.getJSONObject("boundsInScreen")
        assertEquals(1, bounds.getInt("l"))
        assertEquals(4, bounds.getInt("b"))
    }

    @Test
    fun toJson_supportsNullables() {
        val snapshot = FocusSnapshot(
            timestamp = 1L,
            packageName = null,
            className = null,
            viewIdResourceName = null,
            text = null,
            contentDescription = null,
            clickable = false,
            focusable = false,
            focused = false,
            accessibilityFocused = false,
            selected = false,
            checkable = false,
            checked = false,
            enabled = false,
            boundsInScreen = Rect(0, 0, 0, 0)
        )

        val json = snapshot.toJson()
        assertEquals(JSONObject.NULL, json.get("packageName"))
        assertEquals(JSONObject.NULL, json.get("text"))
    }
}
