package com.iotpart.sqe.talkbackhelper

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLog
import org.robolectric.shadows.ShadowLooper
import java.util.concurrent.AbstractExecutorService
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SmartNextDispatcherTest {
    private class QueueExecutor : AbstractExecutorService() {
        val tasks = mutableListOf<Runnable>()
        var stopped = false
        override fun execute(task: Runnable) { tasks.add(task) }
        override fun shutdown() { stopped = true }
        override fun shutdownNow(): MutableList<Runnable> { stopped = true; return tasks }
        override fun isShutdown() = stopped
        override fun isTerminated() = stopped && tasks.isEmpty()
        override fun awaitTermination(timeout: Long, unit: TimeUnit) = isTerminated
        fun runNext() { tasks.removeAt(0).run() }
    }

    @Test fun preservesRequestAndEmitsOneResultDespiteDuplicateRequest() {
        val queue = QueueExecutor()
        val executed = mutableListOf<String>()
        val emitted = mutableListOf<String>()
        val dispatcher = SmartNextDispatcher(queue) { reqId ->
            executed.add(reqId)
            JSONObject().put("reqId", reqId).put("success", true)
        }
        val onResult: (JSONObject) -> Unit = { emitted.add(it.getString("reqId")) }
        assertTrue(dispatcher.submit("one", onResult) { fail(it.message) })
        assertFalse(dispatcher.submit("one", onResult) { fail(it.message) })
        assertTrue(executed.isEmpty())
        queue.runNext()
        assertEquals(listOf("one"), executed)
        assertEquals(listOf("one"), emitted)
        assertFalse(dispatcher.submit("one", onResult) { fail(it.message) })
    }

    @Test fun serialRequestsKeepSubmissionOrderAndResultCorrelation() {
        val queue = QueueExecutor()
        val executed = mutableListOf<String>()
        val emitted = mutableListOf<String>()
        val dispatcher = SmartNextDispatcher(queue) { reqId ->
            executed.add(reqId)
            JSONObject().put("reqId", reqId).put("success", true)
        }

        assertTrue(dispatcher.submit("first", { emitted.add(it.getString("reqId")) }) { fail(it.message) })
        assertTrue(dispatcher.submit("second", { emitted.add(it.getString("reqId")) }) { fail(it.message) })
        assertEquals(2, queue.tasks.size)

        queue.runNext()
        assertEquals(listOf("first"), executed)
        assertEquals(listOf("first"), emitted)
        queue.runNext()
        assertEquals(listOf("first", "second"), executed)
        assertEquals(listOf("first", "second"), emitted)
        dispatcher.close()
        assertTrue(queue.tasks.isEmpty())
    }

    @Test fun workFailureReportsExactlyOnceAndClosedServiceRejectsNewWork() {
        val queue = QueueExecutor()
        var failures = 0
        val dispatcher = SmartNextDispatcher(queue) { throw IllegalStateException("work failed") }
        dispatcher.submit("failure", { fail("Unexpected success") }) { failures++ }
        queue.runNext()
        assertEquals(1, failures)
        dispatcher.close()
        assertFalse(dispatcher.submit("closed", { fail("Unexpected success") }) { failures++ })
        assertEquals(2, failures)
        assertTrue(queue.tasks.isEmpty())
    }

    @Test(timeout = 3000) fun longWorkDoesNotBlockSubmission() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val result = CountDownLatch(1)
        val dispatcher = SmartNextDispatcher { reqId ->
            entered.countDown()
            release.await()
            JSONObject().put("reqId", reqId)
        }
        try {
            assertTrue(dispatcher.submit("slow", { result.countDown() }) { fail(it.message) })
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            assertEquals(1L, result.count)
            release.countDown()
            assertTrue(result.await(1, TimeUnit.SECONDS))
        } finally {
            release.countDown()
            dispatcher.close()
        }
    }

    @Test fun orderedBroadcastFinishesBeforeServiceWorkAndFailureStillEmitsCorrelatedResult() {
        val controller = Robolectric.buildService(A11yHelperService::class.java).create()
        val service = controller.get()
        A11yHelperService::class.java.getDeclaredMethod("onServiceConnected").apply { isAccessible = true }.invoke(service)
        val queue = QueueExecutor()
        service.smartNextDispatcher.close()
        service.smartNextDispatcher = SmartNextDispatcher(queue) { throw IllegalStateException("slow work failed") }
        val context = RuntimeEnvironment.getApplication()
        val receiver = A11yCommandReceiver()
        val action = "com.iotpart.sqe.talkbackhelper.SMART_NEXT"
        context.registerReceiver(receiver, IntentFilter(action), Context.RECEIVER_EXPORTED)
        var ack = false
        val completion = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) { ack = true }
        }
        try {
            context.sendOrderedBroadcast(Intent(action).putExtra("reqId", "receiver-one"), null, completion, null, 0, null, null)
            ShadowLooper.idleMainLooper()
            assertTrue("Ordered broadcast ACK must not wait for navigation", ack)
            assertEquals(1, queue.tasks.size)
            assertFalse(ShadowLog.getLogsForTag("A11Y_HELPER").any { it.msg.startsWith("SMART_NAV_RESULT ") })
            queue.runNext()
            val results = ShadowLog.getLogsForTag("A11Y_HELPER").filter { it.msg.startsWith("SMART_NAV_RESULT ") }
            assertEquals(1, results.size)
            val payload = JSONObject(results.single().msg.removePrefix("SMART_NAV_RESULT "))
            assertEquals("receiver-one", payload.getString("reqId"))
            assertFalse(payload.getBoolean("success"))
        } finally {
            context.unregisterReceiver(receiver)
            controller.destroy()
        }
    }
}
