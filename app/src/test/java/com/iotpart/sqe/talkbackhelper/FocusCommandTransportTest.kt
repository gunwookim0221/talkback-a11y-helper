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
class FocusCommandTransportTest {
    private class QueueExecutor : AbstractExecutorService() {
        val tasks = mutableListOf<Runnable>()
        var closed = false
        override fun execute(task: Runnable) { tasks.add(task) }
        override fun shutdown() { closed = true }
        override fun shutdownNow(): MutableList<Runnable> { closed = true; return tasks }
        override fun isShutdown() = closed
        override fun isTerminated() = closed && tasks.isEmpty()
        override fun awaitTermination(timeout: Long, unit: TimeUnit) = isTerminated
        fun next() { tasks.removeAt(0).run() }
    }

    private fun receiverContract(command: String) {
        ShadowLog.clear()
        val controller = Robolectric.buildService(A11yHelperService::class.java).create()
        val service = controller.get()
        A11yHelperService::class.java.getDeclaredMethod("onServiceConnected").apply { isAccessible = true }.invoke(service)
        val queue = QueueExecutor()
        service.focusCommandDispatcher.close()
        service.focusCommandDispatcher = AccessibilityCommandDispatcher(queue)
        val context = RuntimeEnvironment.getApplication()
        val action = "com.iotpart.sqe.talkbackhelper.$command"
        val receiver = A11yCommandReceiver()
        context.registerReceiver(receiver, IntentFilter(action), Context.RECEIVER_EXPORTED)
        var ack = false
        val done = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) { ack = true }
        }
        try {
            val intent = Intent(action).putExtra("reqId", "slow-$command").putExtra("bounds", "[0,0][100,100]")
            context.sendOrderedBroadcast(intent, null, done, null, 0, null, null)
            ShadowLooper.idleMainLooper()
            assertTrue("Command ACK must precede arbitrarily delayed service work", ack)
            assertEquals(1, queue.tasks.size)
            assertFalse(ShadowLog.getLogsForTag("A11Y_HELPER").any { it.msg.startsWith("TARGET_ACTION_RESULT ") })
            // A held queue is a mock of 30+ seconds of work; no real sleep.
            receiver.onReceive(context, intent) // Same request never queues another action.
            assertEquals(1, queue.tasks.size)
            queue.next()
            val results = ShadowLog.getLogsForTag("A11Y_HELPER").filter { it.msg.startsWith("TARGET_ACTION_RESULT ") }
            assertEquals(1, results.size)
            val result = JSONObject(results.single().msg.removePrefix("TARGET_ACTION_RESULT "))
            assertEquals("slow-$command", result.getString("reqId"))
            assertFalse(result.getBoolean("success")) // Root unavailable in this mock service.
            assertEquals(command, result.getString("action"))
        } finally {
            context.unregisterReceiver(receiver)
            controller.destroy()
        }
    }

    @Test fun focusBroadcastCompletesBeforeFocusWorkAndKeepsOneCorrelatedResult() {
        receiverContract("FOCUS_IN_BOUNDS")
    }
    @Test fun targetCommitBroadcastCompletesBeforeWorkWithoutChangingResultContract() {
        receiverContract("TARGET_FOCUS_COMMIT")
    }
    @Test fun sequenceAndDuplicateSuppressionSharedAcrossFocusCommands() {
        val queue = QueueExecutor()
        val dispatcher = AccessibilityCommandDispatcher(queue)
        val events = mutableListOf<String>()
        for (reqId in listOf("bounds", "target", "bounds")) {
            dispatcher.submit(reqId, { events.add("work:$reqId"); JSONObject().put("reqId", reqId) },
                { events.add("result:${it.getString("reqId")}") }, { fail(it.message) })
        }
        assertEquals(2, queue.tasks.size)
        queue.next(); queue.next()
        assertEquals(listOf("work:bounds", "result:bounds", "work:target", "result:target"), events)
    }
    @Test fun workExceptionProducesOneFailure() {
        val queue = QueueExecutor()
        val dispatcher = AccessibilityCommandDispatcher(queue)
        var failures = 0
        dispatcher.submit("failure", { throw IllegalStateException("work failed") }, { fail("Unexpected result") }, { failures++ })
        queue.next()
        assertEquals(1, failures)
        assertFalse(dispatcher.submit("failure", { JSONObject() }, {}, { failures++ }))
        assertEquals(1, failures)
    }
    @Test fun emissionExceptionCannotEmitSecondResult() {
        val queue = QueueExecutor()
        val dispatcher = AccessibilityCommandDispatcher(queue)
        var failures = 0
        dispatcher.submit("emit", { JSONObject() }, { throw IllegalStateException("emission failed") }, { failures++ })
        try { queue.next(); fail("Expected callback exception") } catch (_: IllegalStateException) { }
        assertEquals(0, failures)
        assertFalse(dispatcher.submit("emit", { JSONObject() }, {}, { failures++ }))
    }
    @Test fun closeDrainsAcceptedWorkAndRejectsNewRequestOnce() {
        val queue = QueueExecutor()
        val dispatcher = AccessibilityCommandDispatcher(queue)
        var emitted = 0
        var failed = 0
        dispatcher.submit("accepted", { JSONObject() }, { emitted++ }, { failed++ })
        dispatcher.close()
        assertFalse(dispatcher.submit("closed", { JSONObject() }, {}, { failed++ }))
        assertFalse(dispatcher.submit("closed", { JSONObject() }, {}, { failed++ }))
        queue.next()
        assertEquals(1, emitted)
        assertEquals(1, failed)
    }
    @Test(timeout = 3000) fun longWorkerDoesNotBlockSubmissionOrStartSecondCommandEarly() {
        val dispatcher = AccessibilityCommandDispatcher()
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val second = CountDownLatch(1)
        try {
            dispatcher.submit("slow", { entered.countDown(); release.await(); JSONObject() }, {}, { fail(it.message) })
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            dispatcher.submit("next", { second.countDown(); JSONObject() }, {}, { fail(it.message) })
            assertEquals(1L, second.count)
            release.countDown()
            assertTrue(second.await(1, TimeUnit.SECONDS))
        } finally {
            release.countDown()
            dispatcher.close()
        }
    }
}
