package com.iotpart.sqe.talkbackhelper

import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException

/** Bound-service work is independent of the lifetime of the command broadcast. */
internal class AccessibilityCommandDispatcher(
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
) {
    private val active = mutableSetOf<String>()
    private val completed = LinkedHashSet<String>()
    private var closed = false

    fun submit(reqId: String, work: () -> JSONObject,
               onResult: (JSONObject) -> Unit, onFailure: (Throwable) -> Unit): Boolean {
        synchronized(this) {
            if (reqId in active || reqId in completed) return false
            active.add(reqId)
            if (closed) {
                complete(reqId)
                onFailure(RejectedExecutionException("Accessibility command service scope closed"))
                return false
            }
            try {
                // Enqueue under the lock: accepted commands retain submission order.
                executor.execute {
                    val result = runCatching(work)
                    try {
                        // Callback exceptions cannot generate a second terminal result.
                        result.fold(onSuccess = onResult, onFailure = onFailure)
                    } finally {
                        synchronized(this) { complete(reqId) }
                    }
                }
            } catch (error: RejectedExecutionException) {
                complete(reqId)
                onFailure(error)
                return false
            }
        }
        return true
    }

    private fun complete(reqId: String) {
        active.remove(reqId)
        completed.add(reqId)
        if (completed.size > 1024) completed.remove(completed.first())
    }

    fun close() {
        synchronized(this) {
            closed = true
            executor.shutdown() // Drain accepted work, reject new commands.
        }
    }
}
