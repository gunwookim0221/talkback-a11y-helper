package com.iotpart.sqe.talkbackhelper

import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.SynchronousQueue
import java.util.concurrent.ThreadFactory
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import org.json.JSONObject

/**
 * Process-scoped owner of the hierarchy transfer workers. A cancelled task may ignore interruption,
 * so its executor is quarantined instead of being treated as available. At most one quarantined
 * executor is retained; if it and the current executor are both still occupied, new work fails
 * closed until one worker actually terminates.
 */
internal class HierarchyTransferExecutorLifecycle(
    private val maxRetiredGenerations: Int = MAX_RETIRED_GENERATIONS,
    private val executorFactory: (Long) -> ThreadPoolExecutor = { generation -> newExecutor(generation) },
) {
    private data class Generation(val id: Long, val executor: ThreadPoolExecutor)
    private data class ActiveOperation(
        val handle: HierarchyPayloadStore.RequestHandle,
        val generation: Generation,
    )

    private var nextGenerationId = 0L
    private var current = newGeneration()
    private val retired = mutableListOf<Generation>()
    private var active: ActiveOperation? = null

    init {
        require(maxRetiredGenerations >= 0)
    }

    @Synchronized
    fun execute(handle: HierarchyPayloadStore.RequestHandle, task: () -> Unit) {
        pruneTerminatedRetired()
        if (active != null) throw RejectedExecutionException("transfer_worker_active")
        val generation = acceptingGeneration()
        val operation = ActiveOperation(handle, generation)
        active = operation
        try {
            generation.executor.execute {
                try {
                    task()
                } finally {
                    workerFinished(operation)
                }
            }
        } catch (error: RejectedExecutionException) {
            if (active === operation) active = null
            throw error
        }
    }

    /** Invalidates only the exact submitted request; repeated or stale cancels are no-ops. */
    @Synchronized
    fun cancel(handle: HierarchyPayloadStore.RequestHandle): Boolean {
        val operation = active ?: return false
        if (operation.handle != handle) return false
        active = null
        operation.generation.executor.shutdownNow()
        return true
    }

    /** Called after the store invalidates its active request during service destruction. */
    @Synchronized
    fun serviceDisconnected() {
        val operation = active ?: return
        active = null
        operation.generation.executor.shutdownNow()
    }

    @Synchronized
    internal fun liveGenerationCountForTest(): Int {
        pruneTerminatedRetired()
        return (if (current.executor.isTerminated) 0 else 1) + retired.count { !it.executor.isTerminated }
    }

    @Synchronized
    internal fun retiredGenerationCountForTest(): Int {
        pruneTerminatedRetired()
        return retired.size
    }

    @Synchronized
    internal fun activeHandleForTest(): HierarchyPayloadStore.RequestHandle? = active?.handle

    private fun acceptingGeneration(): Generation {
        if (!current.executor.isShutdown) return current
        if (!current.executor.isTerminated) {
            pruneTerminatedRetired()
            if (retired.size >= maxRetiredGenerations) {
                throw HierarchyTransferRecoveryLimitException()
            }
            retired += current
        }
        current = newGeneration()
        return current
    }

    private fun workerFinished(operation: ActiveOperation) {
        synchronized(this) {
            if (active === operation) active = null
            pruneTerminatedRetired()
        }
    }

    private fun pruneTerminatedRetired() {
        retired.removeAll { it.executor.isTerminated }
    }

    private fun newGeneration(): Generation {
        val id = ++nextGenerationId
        return Generation(id, executorFactory(id))
    }

    companion object {
        const val MAX_RETIRED_GENERATIONS = 1

        private fun newExecutor(generation: Long) = ThreadPoolExecutor(
            1,
            1,
            0L,
            TimeUnit.MILLISECONDS,
            SynchronousQueue<Runnable>(),
            ThreadFactory { runnable -> Thread(runnable, "hierarchy-payload-transfer-g$generation") },
            ThreadPoolExecutor.AbortPolicy(),
        )
    }
}

internal class HierarchyTransferRecoveryLimitException : RejectedExecutionException("RECOVERY_LIMIT_REACHED")

internal fun submitHierarchyTransfer(
    executor: HierarchyTransferExecutorLifecycle,
    store: HierarchyPayloadStore,
    handle: HierarchyPayloadStore.RequestHandle,
    task: () -> Unit,
): JSONObject? = try {
    executor.execute(handle, task)
    null
} catch (_: HierarchyTransferRecoveryLimitException) {
    store.fail(handle, "RECOVERY_LIMIT_REACHED").also { store.workerFinished(handle) }
} catch (_: RejectedExecutionException) {
    store.fail(handle, "BUSY").also { store.workerFinished(handle) }
}

/** Fence the expired store record before retiring the physical worker. */
internal fun expireHierarchyTransfer(
    executor: HierarchyTransferExecutorLifecycle,
    store: HierarchyPayloadStore,
): HierarchyPayloadStore.RequestHandle? {
    val expired = store.expireActive() ?: return null
    executor.cancel(expired)
    return expired
}
