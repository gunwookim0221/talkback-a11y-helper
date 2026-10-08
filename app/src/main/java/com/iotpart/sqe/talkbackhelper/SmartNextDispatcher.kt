package com.iotpart.sqe.talkbackhelper

import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException

/** Work belongs to the bound accessibility service, never a pending broadcast. */
internal class SmartNextDispatcher(
    private val executor: ExecutorService = Executors.newSingleThreadExecutor(),
    private val work: (String) -> JSONObject
) {
    private val accepted = LinkedHashSet<String>()
    private var closed = false

    fun submit(reqId: String, onResult: (JSONObject) -> Unit, onFailure: (Throwable) -> Unit): Boolean {
        synchronized(this) {
            if (reqId in accepted) return false
            if (closed) {
                onFailure(RejectedExecutionException("SMART_NEXT service scope closed"))
                return false
            }
            accepted.add(reqId)
            if (accepted.size > 1024) accepted.remove(accepted.first())
        }
        try {
            executor.execute {
                // Emission is a single callback; an emission exception must not
                // trigger a second navigation result for the same request.
                val result = runCatching { work(reqId) }
                result.fold(onSuccess = onResult, onFailure = onFailure)
            }
        } catch (error: RejectedExecutionException) {
            onFailure(error)
            return false
        }
        return true
    }

    fun close() {
        synchronized(this) { closed = true }
        // Accepted work drains once; closing cannot enqueue new navigation.
        executor.shutdown()
    }
}
