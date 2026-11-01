package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.ArrayDeque
import java.util.concurrent.Executor

class CoalescingAccessibilityEventProcessorTest {
    private data class Result(val value: String)

    private class ManualExecutor : Executor {
        private val tasks = ArrayDeque<Runnable>()
        override fun execute(command: Runnable) {
            tasks.addLast(command)
        }
        fun runNext() {
            tasks.removeFirst().run()
        }
        fun runAll() {
            while (tasks.isNotEmpty()) runNext()
        }
        fun size(): Int = tasks.size
    }

    private val context = AccessibilityEventWorkContext(
        serviceInstanceId = "service-a",
        activeTurnId = 4L,
        activeRequestId = "req-a",
        finalCommitTurnId = 3L
    )

    @Test
    fun submitReturnsBeforeWorkerRunsAndOnlyNewestPendingEventIsProcessed() {
        val worker = ManualExecutor()
        val main = ManualExecutor()
        val processed = mutableListOf<String>()
        val committed = mutableListOf<String>()
        val disposed = mutableListOf<String>()
        val processor = CoalescingAccessibilityEventProcessor<String, Result>(
            worker = worker,
            main = main,
            isContextCurrent = { true },
            process = { input, _ -> processed += input; Result(input) },
            commit = { result, _ -> committed += result.value },
            disposeInput = disposed::add
        )

        assertTrue(processor.submit("first", context))
        assertTrue(processor.submit("latest", context))
        assertEquals(listOf("first"), disposed)
        assertEquals(1, worker.size())
        assertTrue(processed.isEmpty())

        worker.runNext()
        assertEquals(listOf("latest"), processed)
        assertEquals(1, main.size())
        main.runAll()
        assertEquals(listOf("latest"), committed)
        assertEquals(listOf("first", "latest"), disposed)
    }

    @Test
    fun aNewerEventInvalidatesAnInFlightResultAndOnlyLatestCanCommit() {
        val worker = ManualExecutor()
        val main = ManualExecutor()
        val committed = mutableListOf<String>()
        lateinit var processor: CoalescingAccessibilityEventProcessor<String, Result>
        processor = CoalescingAccessibilityEventProcessor(
            worker = worker,
            main = main,
            isContextCurrent = { true },
            process = { input, _ ->
                if (input == "old") processor.submit("new", context)
                Result(input)
            },
            commit = { result, _ -> committed += result.value },
            disposeInput = {}
        )

        processor.submit("old", context)
        worker.runNext()
        assertEquals(1, main.size())
        main.runAll()
        assertEquals(listOf("new"), committed)
    }

    @Test
    fun connectionInvalidationRejectsAlreadyPostedMainCommit() {
        val worker = ManualExecutor()
        val main = ManualExecutor()
        val committed = mutableListOf<String>()
        val processor = CoalescingAccessibilityEventProcessor<String, Result>(
            worker = worker,
            main = main,
            isContextCurrent = { true },
            process = { input, _ -> Result(input) },
            commit = { result, _ -> committed += result.value },
            disposeInput = {}
        )

        processor.submit("captured-before-disconnect", context)
        worker.runNext()
        processor.invalidateConnection()
        main.runAll()

        assertTrue(committed.isEmpty())
    }

    @Test
    fun staleServiceTurnOrRequestContextCannotCommit() {
        val worker = ManualExecutor()
        val main = ManualExecutor()
        var current = context
        val processed = mutableListOf<String>()
        val committed = mutableListOf<String>()
        val processor = CoalescingAccessibilityEventProcessor<String, Result>(
            worker = worker,
            main = main,
            isContextCurrent = { it == current },
            process = { input, _ -> processed += input; Result(input) },
            commit = { result, _ -> committed += result.value },
            disposeInput = {}
        )

        processor.submit("old-context", context)
        current = context.copy(serviceInstanceId = "service-b", activeTurnId = 5L, activeRequestId = "req-b")
        worker.runNext()
        main.runAll()

        assertTrue(processed.isEmpty())
        assertTrue(committed.isEmpty())
    }

    @Test
    fun missingResultAndProcessingFailureNeverCommit() {
        val worker = ManualExecutor()
        val main = ManualExecutor()
        var failures = 0
        val committed = mutableListOf<String>()
        val processor = CoalescingAccessibilityEventProcessor<String, Result>(
            worker = worker,
            main = main,
            isContextCurrent = { true },
            process = { input, _ ->
                when (input) {
                    "missing" -> null
                    else -> throw IllegalStateException("capture failed")
                }
            },
            commit = { result, _ -> committed += result.value },
            disposeInput = {},
            onFailure = { failures++ }
        )

        processor.submit("missing", context)
        worker.runNext()
        processor.submit("failure", context)
        worker.runNext()
        main.runAll()

        assertEquals(1, failures)
        assertTrue(committed.isEmpty())
    }

    @Test
    fun closeDisposesPendingEventAndPreventsFurtherWork() {
        val worker = ManualExecutor()
        val main = ManualExecutor()
        val processed = mutableListOf<String>()
        val disposed = mutableListOf<String>()
        val processor = CoalescingAccessibilityEventProcessor<String, Result>(
            worker = worker,
            main = main,
            isContextCurrent = { true },
            process = { input, _ -> processed += input; Result(input) },
            commit = { _, _ -> error("closed work must not commit") },
            disposeInput = disposed::add
        )

        processor.submit("pending", context)
        processor.close()
        assertFalse(processor.submit("after-close", context))
        worker.runAll()
        main.runAll()

        assertTrue(processed.isEmpty())
        assertEquals(listOf("pending", "after-close"), disposed)
    }
}
