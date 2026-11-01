package com.iotpart.sqe.talkbackhelper

import android.view.accessibility.AccessibilityEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class A11yHelperServiceFocusEventTest {
    @Test
    fun callbackReturnsPromptlyWhileFreshRootIsReadOffMainAndNullRootDoesNotUpdateFocusOrVisits() {
        val controller = Robolectric.buildService(A11yHelperService::class.java).create()
        val service = controller.get()
        val rootReadStarted = CountDownLatch(1)
        val allowRootReadToFinish = CountDownLatch(1)
        val rootReadFinished = CountDownLatch(1)
        val rootReadThread = AtomicReference<Thread>()
        val originalFocusTimestamp = A11yStateStore.lastUpdatedAt
        val originalVisited = A11yHistoryManager.snapshotVisitedHistorySignatures()
        service.focusEventRootProviderForTesting = {
            rootReadThread.set(Thread.currentThread())
            rootReadStarted.countDown()
            try {
                allowRootReadToFinish.await(3, TimeUnit.SECONDS)
            } finally {
                rootReadFinished.countDown()
            }
            null
        }

        try {
            A11yHelperService::class.java.getDeclaredMethod("onServiceConnected")
                .apply { isAccessible = true }
                .invoke(service)
            val event = AccessibilityEvent.obtain(AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED).apply {
                packageName = "com.example.focus-test"
            }
            val callbackStarted = System.nanoTime()
            service.onAccessibilityEvent(event)
            val callbackElapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - callbackStarted)

            assertTrue("callback elapsed ${callbackElapsedMs}ms", callbackElapsedMs < 500L)
            assertTrue(rootReadStarted.await(2, TimeUnit.SECONDS))
            assertNotEquals(Thread.currentThread(), rootReadThread.get())

            allowRootReadToFinish.countDown()
            assertTrue(rootReadFinished.await(2, TimeUnit.SECONDS))
            Thread.sleep(50)
            assertEquals(originalFocusTimestamp, A11yStateStore.lastUpdatedAt)
            assertEquals(originalVisited, A11yHistoryManager.snapshotVisitedHistorySignatures())
        } finally {
            allowRootReadToFinish.countDown()
            controller.destroy()
        }
    }
}
