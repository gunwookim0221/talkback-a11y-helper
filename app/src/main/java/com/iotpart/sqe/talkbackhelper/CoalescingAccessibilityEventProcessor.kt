package com.iotpart.sqe.talkbackhelper

import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

internal data class AccessibilityEventWorkContext(
    val serviceInstanceId: String,
    val activeTurnId: Long,
    val activeRequestId: String,
    val finalCommitTurnId: Long
)

internal data class AccessibilityEventWorkTicket(
    val sequence: Long,
    val connectionGeneration: Long,
    val context: AccessibilityEventWorkContext
)

/**
 * Runs accessibility-node inspection away from the service callback looper.
 * Pending work is latest-only; a newer event or lifecycle boundary makes every
 * older in-flight result ineligible for the main-thread commit.
 */
internal class CoalescingAccessibilityEventProcessor<I : Any, O : Any>(
    private val worker: Executor,
    private val main: Executor,
    private val isContextCurrent: (AccessibilityEventWorkContext) -> Boolean,
    private val process: (I, AccessibilityEventWorkTicket) -> O?,
    private val commit: (O, AccessibilityEventWorkTicket) -> Unit,
    private val disposeInput: (I) -> Unit,
    private val onFailure: (Exception) -> Unit = {}
) {
    private data class Work<I>(val ticket: AccessibilityEventWorkTicket, val input: I)

    private val pending = AtomicReference<Work<I>?>(null)
    private val sequence = AtomicLong(0L)
    private val connectionGeneration = AtomicLong(0L)
    private val drainScheduled = AtomicBoolean(false)
    private val closed = AtomicBoolean(false)

    fun submit(input: I, context: AccessibilityEventWorkContext): Boolean {
        if (closed.get()) {
            disposeSafely(input)
            return false
        }

        val ticket = AccessibilityEventWorkTicket(
            sequence = sequence.incrementAndGet(),
            connectionGeneration = connectionGeneration.get(),
            context = context
        )
        pending.getAndSet(Work(ticket, input))?.let { disposeSafely(it.input) }
        scheduleDrain()
        return !closed.get()
    }

    /** Invalidates pending/in-flight work when any later accessibility event arrives. */
    fun invalidatePending() {
        sequence.incrementAndGet()
        pending.getAndSet(null)?.let { disposeSafely(it.input) }
    }

    /** Invalidates work across service connection, interruption, or destruction. */
    fun invalidateConnection() {
        connectionGeneration.incrementAndGet()
        invalidatePending()
    }

    fun close() {
        if (!closed.compareAndSet(false, true)) return
        connectionGeneration.incrementAndGet()
        sequence.incrementAndGet()
        pending.getAndSet(null)?.let { disposeSafely(it.input) }
    }

    private fun isCurrent(ticket: AccessibilityEventWorkTicket): Boolean {
        if (closed.get() || ticket.sequence != sequence.get() ||
            ticket.connectionGeneration != connectionGeneration.get()) return false
        return try {
            isContextCurrent(ticket.context)
        } catch (_: Exception) {
            false
        }
    }

    private fun scheduleDrain() {
        if (!drainScheduled.compareAndSet(false, true)) return
        try {
            worker.execute(::drain)
        } catch (failure: Exception) {
            drainScheduled.set(false)
            pending.getAndSet(null)?.let { disposeSafely(it.input) }
            reportFailure(failure)
        }
    }

    private fun drain() {
        try {
            while (!closed.get()) {
                val work = pending.getAndSet(null) ?: break
                try {
                    if (!isCurrent(work.ticket)) continue
                    val result = process(work.input, work.ticket) ?: continue
                    if (!isCurrent(work.ticket)) continue
                    main.execute {
                        if (isCurrent(work.ticket)) {
                            try {
                                commit(result, work.ticket)
                            } catch (failure: Exception) {
                                reportFailure(failure)
                            }
                        }
                    }
                } catch (failure: Exception) {
                    reportFailure(failure)
                } finally {
                    disposeSafely(work.input)
                }
            }
        } finally {
            drainScheduled.set(false)
            if (pending.get() != null && !closed.get()) scheduleDrain()
        }
    }

    private fun disposeSafely(input: I) {
        try {
            disposeInput(input)
        } catch (failure: Exception) {
            reportFailure(failure)
        }
    }

    private fun reportFailure(failure: Exception) {
        try {
            onFailure(failure)
        } catch (_: Exception) {
            // Diagnostics cannot affect event authority or worker availability.
        }
    }
}
