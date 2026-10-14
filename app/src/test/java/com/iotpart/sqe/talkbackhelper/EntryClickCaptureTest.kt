package com.iotpart.sqe.talkbackhelper

import android.os.SystemClock
import android.view.accessibility.AccessibilityEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class EntryClickCaptureTest {

    @Test
    fun clickEventIsRetainedOnlyUnderArmedTransactionAndAbsentSourceIsExplicit() {
        val reqId = "click-${UUID.randomUUID()}"
        val transactionId = "transaction-${UUID.randomUUID()}"
        val armed = A11yEvidence.armEntryClickCapture(reqId, transactionId, 2000L)
        assertTrue(armed.optBoolean("ok"))
        assertEquals(transactionId, armed.optString("transactionId"))

        val event = AccessibilityEvent.obtain(AccessibilityEvent.TYPE_VIEW_CLICKED)
        event.eventTime = SystemClock.uptimeMillis()
        event.packageName = "com.samsung.android.oneconnect"
        event.className = "android.view.ViewGroup"
        event.text.add("Home Monitor")

        assertTrue(A11yEvidence.captureEntryClickEvent(event))
        val snapshot = A11yEvidence.entryClickSnapshot(reqId)
        val records = snapshot.optJSONArray("evidenceEvents")
        assertEquals(transactionId, snapshot.optString("transactionId"))
        assertEquals(1, records?.length())
        val payload = records?.optJSONObject(0)?.optJSONObject("payload")
        assertEquals("TYPE_VIEW_CLICKED", payload?.optString("event_type"))
        assertEquals("com.samsung.android.oneconnect", payload?.optString("package"))
        assertEquals("android.view.ViewGroup", payload?.optString("class_name"))
        assertEquals("Home Monitor", payload?.optString("text"))
        assertEquals("FIELD_ABSENT", payload?.optString("source_status"))
        assertEquals("FIELD_ABSENT", payload?.optString("source_node_id_status"))

        val ended = A11yEvidence.disarmEntryClickCapture(reqId)
        assertTrue(ended.optBoolean("ok"))
        assertEquals(transactionId, ended.optString("transactionId"))
        assertEquals(1, ended.optJSONArray("evidenceEvents")?.length())
        assertFalse(ended.optBoolean("active"))
        event.recycle()
    }
}
