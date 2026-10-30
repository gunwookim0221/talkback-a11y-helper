package com.iotpart.sqe.talkbackhelper

import android.net.Uri
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Robolectric
import org.robolectric.RuntimeEnvironment
import org.robolectric.shadows.ShadowLooper
import java.io.File
import java.io.IOException
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicLong

@RunWith(RobolectricTestRunner::class)
class HierarchyTransferExecutorLifecycleTest {
    @get:Rule val temporaryFolder = TemporaryFolder()

    private val buildId = "a".repeat(64)
    private val gitCommit = "b".repeat(40)
    private val clientNonce = "c".repeat(32)
    private val helperIdentity = JSONObject()
        .put("build_id", buildId)
        .put("git_commit", gitCommit)
        .put("input_digest", "d".repeat(64))
        .put("source_state", "CLEAN")
        .put("build_variant", "debug")

    private data class Fixture(
        val directory: File,
        val store: HierarchyPayloadStore,
        val serviceId: String,
    )

    private data class Worker(
        val completed: CountDownLatch,
        val result: AtomicReference<JSONObject?>,
    )

    private fun fixture(
        serviceId: String = "service-instance-test",
        beforeAtomicFileFinishWrite: (File) -> Unit = {},
        clock: () -> Long = { 100L },
    ): Fixture {
        val directory = temporaryFolder.newFolder()
        val store = HierarchyPayloadStore(
            directory = directory,
            processEpoch = UUID.randomUUID().toString(),
            elapsedRealtimeMs = clock,
            helperIdentity = helperIdentity,
            beforeAtomicFileFinishWrite = beforeAtomicFileFinishWrite,
        )
        store.serviceConnected(serviceId)
        return Fixture(directory, store, serviceId)
    }

    private fun begin(
        fixture: Fixture,
        requestId: String = UUID.randomUUID().toString().replace("-", ""),
        nonce: String = clientNonce,
        serviceId: String = fixture.serviceId,
    ): HierarchyPayloadStore.RequestHandle {
        val accepted = fixture.store.begin(
            requestId = requestId,
            clientNonce = nonce,
            queryNonce = UUID.randomUUID().toString().replace("-", ""),
            expectedBuildId = buildId,
            expectedGitCommit = gitCommit,
            expectedServiceInstanceId = serviceId,
        )
        assertEquals("ACCEPTED", accepted.getString("status"))
        return HierarchyPayloadStore.RequestHandle(requestId, nonce, accepted.getLong("generation"))
    }

    private fun submit(
        fixture: Fixture,
        executor: HierarchyTransferExecutorLifecycle,
        handle: HierarchyPayloadStore.RequestHandle,
        beforePublish: () -> Unit = {},
    ): Worker {
        val completed = CountDownLatch(1)
        val result = AtomicReference<JSONObject?>()
        val rejection = submitHierarchyTransfer(executor, fixture.store, handle) {
            try {
                if (!fixture.store.markCollecting(handle)) return@submitHierarchyTransfer
                fixture.store.reserveCaptureSequence(handle)
                    ?: throw IllegalStateException("CAPTURE_SEQUENCE_UNAVAILABLE")
                beforePublish()
                result.set(fixture.store.publish(handle, byteArrayOf(1, 2, 3, 4)))
            } catch (error: Throwable) {
                result.set(fixture.store.fail(
                    handle,
                    if (error.message == "PAYLOAD_TOO_LARGE") "PAYLOAD_TOO_LARGE" else "COLLECTION_FAILED",
                ))
            } finally {
                fixture.store.workerFinished(handle)
                completed.countDown()
            }
        }
        assertNull("unexpected submission rejection: ${rejection?.optString("error_code")}", rejection)
        return Worker(completed, result)
    }

    private fun cancel(
        fixture: Fixture,
        executor: HierarchyTransferExecutorLifecycle,
        handle: HierarchyPayloadStore.RequestHandle,
    ): JSONObject {
        val cancellation = fixture.store.cancelWithLifecycle(
            handle.requestId,
            handle.clientNonce,
            UUID.randomUUID().toString().replace("-", ""), fixture.store.processEpoch, handle.generation,
        )
        assertEquals("CANCELLED", cancellation.response.getString("status"))
        assertEquals("HOST_CANCELLED", cancellation.response.getString("error_code"))
        cancellation.activeHandle?.let { assertTrue(executor.cancel(it)) }
        return cancellation.response
    }

    private fun awaitWorker(worker: Worker) {
        assertTrue("worker did not finish", worker.completed.await(5, TimeUnit.SECONDS))
    }

    private fun awaitUninterruptibly(latch: CountDownLatch) {
        var interrupted = false
        while (true) {
            try {
                latch.await()
                break
            } catch (_: InterruptedException) {
                interrupted = true
            }
        }
        if (interrupted) Thread.currentThread().interrupt()
    }

    private fun assertEventually(timeoutMs: Long = 2_000L, condition: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs)
        while (!condition() && System.nanoTime() < deadline) Thread.sleep(5L)
        assertTrue("condition did not become true before timeout", condition())
    }

    @Test
    fun cancelledCollectingWorkerIsFencedAndReplacementUsesNewGeneration() {
        val fixture = fixture()
        val executor = HierarchyTransferExecutorLifecycle()
        val requestId = UUID.randomUUID().toString().replace("-", "")
        val oldHandle = begin(fixture, requestId = requestId)
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val oldWorker = submit(fixture, executor, oldHandle) {
            started.countDown()
            awaitUninterruptibly(release)
        }

        try {
            assertTrue("blocked collection did not start", started.await(2, TimeUnit.SECONDS))
            assertEquals("COLLECTING", fixture.store.status(
                requestId, oldHandle.clientNonce, "1".repeat(32),
            ).getString("status"))

            val cancellation = fixture.store.cancelWithLifecycle(
                requestId, oldHandle.clientNonce, "2".repeat(32), fixture.store.processEpoch, oldHandle.generation,
            )
            assertEquals("HOST_CANCELLED", cancellation.response.getString("error_code"))
            assertEquals(oldHandle, cancellation.activeHandle)
            assertTrue(executor.cancel(oldHandle))
            assertFalse("repeated cancel must not retire another generation", executor.cancel(oldHandle))

            val repeated = fixture.store.cancelWithLifecycle(requestId, oldHandle.clientNonce, "3".repeat(32), fixture.store.processEpoch, oldHandle.generation)
            assertEquals("REQUEST_NOT_FOUND", repeated.response.getString("error_code"))
            assertNull(repeated.activeHandle)

            val replacement = begin(fixture, requestId = requestId)
            assertTrue("request generation was reused", replacement.generation > oldHandle.generation)
            val newWorker = submit(fixture, executor, replacement)
            awaitWorker(newWorker)
            assertEquals("READY", newWorker.result.get()!!.getString("status"))
            assertEquals("READY", fixture.store.status(
                requestId, replacement.clientNonce, "4".repeat(32),
            ).getString("status"))
            assertEquals("one retired blocked worker plus one current worker", 2, executor.liveGenerationCountForTest())
            assertFalse("shutdownNow was incorrectly treated as worker termination", oldWorker.completed.await(100, TimeUnit.MILLISECONDS))

            release.countDown()
            awaitWorker(oldWorker)
            assertEquals("REQUEST_CANCELLED_OR_STALE", oldWorker.result.get()!!.getString("error_code"))
            assertEquals("READY", fixture.store.status(
                requestId, replacement.clientNonce, "5".repeat(32),
            ).getString("status"))
            assertEventually { executor.liveGenerationCountForTest() == 1 }
        } finally {
            release.countDown()
            oldWorker.completed.await(5, TimeUnit.SECONDS)
        }
    }

    @Test
    fun cancelledWritingWorkerKeepsNewFileLeaseUntilLatePublicationIsRejected() {
        val writingStarted = CountDownLatch(1)
        val release = CountDownLatch(1)
        val firstWrite = AtomicBoolean(true)
        val fixture = fixture(beforeAtomicFileFinishWrite = { readyFile ->
            if (firstWrite.compareAndSet(true, false)) {
                writingStarted.countDown()
                awaitUninterruptibly(release)
            }
        })
        val executor = HierarchyTransferExecutorLifecycle()
        val requestId = UUID.randomUUID().toString().replace("-", "")
        val oldHandle = begin(fixture, requestId = requestId)
        val oldWorker = submit(fixture, executor, oldHandle)

        try {
            assertTrue("AtomicFile writer did not reach the held commit point", writingStarted.await(2, TimeUnit.SECONDS))
            assertEquals("WRITING", fixture.store.status(
                requestId, oldHandle.clientNonce, "6".repeat(32),
            ).getString("status"))
            val oldNewFile = fixture.directory.listFiles()!!.single { it.name.endsWith(".new") }
            assertTrue(oldNewFile.exists())

            val cancellation = fixture.store.cancelWithLifecycle(requestId, oldHandle.clientNonce, "7".repeat(32), fixture.store.processEpoch, oldHandle.generation)
            assertEquals("HOST_CANCELLED", cancellation.response.getString("error_code"))
            assertTrue(executor.cancel(cancellation.activeHandle!!))
            val replacement = begin(fixture, requestId = requestId)
            assertTrue("prune removed a physically active .new file", oldNewFile.exists())

            val newWorker = submit(fixture, executor, replacement)
            awaitWorker(newWorker)
            assertEquals("READY", newWorker.result.get()!!.getString("status"))
            assertTrue("replacement work pruned the cancelled writer's .new file", oldNewFile.exists())

            release.countDown()
            awaitWorker(oldWorker)
            assertEquals("REQUEST_CANCELLED_OR_STALE", oldWorker.result.get()!!.getString("error_code"))
            assertFalse("stale writer left an artifact", oldNewFile.exists())
            val readyUri = Uri.parse(newWorker.result.get()!!.getString("payload_uri"))
            assertNotNull("stale writer removed the current payload", fixture.store.resolveReadyFile(readyUri))
            assertEquals("READY", fixture.store.status(
                requestId, replacement.clientNonce, "8".repeat(32),
            ).getString("status"))
        } finally {
            release.countDown()
            oldWorker.completed.await(5, TimeUnit.SECONDS)
        }
    }

    @Test
    fun repeatedPoisonWorkersHitHardCapAndReportRecoveryLimit() {
        val fixture = fixture()
        val executor = HierarchyTransferExecutorLifecycle()
        val releaseFirst = CountDownLatch(1)
        val releaseSecond = CountDownLatch(1)
        val firstStarted = CountDownLatch(1)
        val secondStarted = CountDownLatch(1)
        val firstHandle = begin(fixture)
        val firstWorker = submit(fixture, executor, firstHandle) {
            firstStarted.countDown()
            awaitUninterruptibly(releaseFirst)
        }

        try {
            assertTrue(firstStarted.await(2, TimeUnit.SECONDS))
            cancel(fixture, executor, firstHandle)

            val secondHandle = begin(fixture)
            val secondWorker = submit(fixture, executor, secondHandle) {
                secondStarted.countDown()
                awaitUninterruptibly(releaseSecond)
            }
            try {
                assertTrue(secondStarted.await(2, TimeUnit.SECONDS))
                cancel(fixture, executor, secondHandle)

                val rejectedHandle = begin(fixture)
                val rejection = submitHierarchyTransfer(executor, fixture.store, rejectedHandle) {
                    throw AssertionError("recovery cap unexpectedly ran another worker")
                }
                assertNotNull(rejection)
                assertEquals("FAILED", rejection!!.getString("status"))
                assertEquals("RECOVERY_LIMIT_REACHED", rejection.getString("error_code"))
                assertEquals("RECOVERY_LIMIT_REACHED", fixture.store.status(
                    rejectedHandle.requestId, rejectedHandle.clientNonce, "9".repeat(32),
                ).getString("error_code"))
                assertEquals(2, executor.liveGenerationCountForTest())
                assertEquals(1, executor.retiredGenerationCountForTest())

                releaseFirst.countDown()
                releaseSecond.countDown()
                awaitWorker(firstWorker)
                awaitWorker(secondWorker)
                assertEquals("REQUEST_CANCELLED_OR_STALE", firstWorker.result.get()!!.getString("error_code"))
                assertEquals("REQUEST_CANCELLED_OR_STALE", secondWorker.result.get()!!.getString("error_code"))
                assertEventually { executor.liveGenerationCountForTest() == 0 }

                val recoveredHandle = begin(fixture)
                val recoveredWorker = submit(fixture, executor, recoveredHandle)
                awaitWorker(recoveredWorker)
                assertEquals("READY", recoveredWorker.result.get()!!.getString("status"))
                assertEquals(1, executor.liveGenerationCountForTest())
            } finally {
                releaseSecond.countDown()
                secondWorker.completed.await(5, TimeUnit.SECONDS)
            }
        } finally {
            releaseFirst.countDown()
            firstWorker.completed.await(5, TimeUnit.SECONDS)
        }
    }

    @Test
    fun completedWriteFailureAndCancelKeepErrorProvenanceWithoutRotatingWorker() {
        val fixture = fixture(beforeAtomicFileFinishWrite = { throw IOException("injected writer timeout") })
        val executor = HierarchyTransferExecutorLifecycle()
        val failedHandle = begin(fixture)
        val failedWorker = submit(fixture, executor, failedHandle)
        awaitWorker(failedWorker)
        assertEquals("FAILED", failedWorker.result.get()!!.getString("status"))
        assertEquals("WRITE_FAILED", failedWorker.result.get()!!.getString("error_code"))

        assertEventually { executor.activeHandleForTest() == null }
        val cancellation = fixture.store.cancelWithLifecycle(
            failedHandle.requestId, failedHandle.clientNonce, "a".repeat(32), fixture.store.processEpoch, failedHandle.generation,
        )
        assertEquals("CANCELLED", cancellation.response.getString("status"))
        assertEquals("HOST_CANCELLED", cancellation.response.getString("error_code"))
        assertNull("completed cancel must not cancel a worker", cancellation.activeHandle)
        assertFalse(executor.cancel(failedHandle))
        assertEquals("completed cancel rotated the executor", 1, executor.liveGenerationCountForTest())
    }

    @Test
    fun serviceDestroyAndRecreateQuarantinesOldWriterAndFencesReusedRequestIdentity() {
        val writingStarted = CountDownLatch(1)
        val release = CountDownLatch(1)
        val firstWrite = AtomicBoolean(true)
        val oldServiceId = "service-instance-old"
        val newServiceId = "service-instance-new"
        val fixture = fixture(oldServiceId, beforeAtomicFileFinishWrite = { readyFile ->
            if (firstWrite.compareAndSet(true, false)) {
                writingStarted.countDown()
                awaitUninterruptibly(release)
            }
        })
        val executor = HierarchyTransferExecutorLifecycle()
        val requestId = UUID.randomUUID().toString().replace("-", "")
        val oldHandle = begin(fixture, requestId = requestId)
        val oldWorker = submit(fixture, executor, oldHandle)

        try {
            assertTrue(writingStarted.await(2, TimeUnit.SECONDS))
            val activeNew = fixture.directory.listFiles()!!.single { it.name.endsWith(".new") }

            // This is the same store/executor sequence used by runtime serviceDisconnected/serviceConnected.
            fixture.store.serviceDisconnected(oldServiceId)
            executor.serviceDisconnected()
            assertTrue("destroy removed a still-open AtomicFile .new", activeNew.exists())
            fixture.store.serviceConnected(newServiceId)

            val replacement = begin(fixture, requestId = requestId, serviceId = newServiceId)
            assertTrue("service reconnect reused a stale request generation", replacement.generation > oldHandle.generation)
            val newWorker = submit(fixture, executor, replacement)
            awaitWorker(newWorker)
            assertEquals("READY", newWorker.result.get()!!.getString("status"))
            assertEquals(newServiceId, newWorker.result.get()!!.getString("service_instance_id"))
            assertTrue(activeNew.exists())

            release.countDown()
            awaitWorker(oldWorker)
            assertEquals("REQUEST_CANCELLED_OR_STALE", oldWorker.result.get()!!.getString("error_code"))
            assertFalse(activeNew.exists())
            assertEquals("READY", fixture.store.status(
                requestId, replacement.clientNonce, "b".repeat(32),
            ).getString("status"))
        } finally {
            release.countDown()
            oldWorker.completed.await(5, TimeUnit.SECONDS)
        }
    }
    @Test
    fun expiredBlockedWriterIsFencedWithoutHostCancelAndTimeoutIsPreserved() {
        val now = AtomicLong(100L)
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val first = AtomicBoolean(true)
        val fixture = fixture(beforeAtomicFileFinishWrite = {
            if (first.compareAndSet(true, false)) {
                started.countDown()
                awaitUninterruptibly(release)
            }
        }, clock = { now.get() })
        val executor = HierarchyTransferExecutorLifecycle()
        val old = begin(fixture)
        val oldWorker = submit(fixture, executor, old)
        try {
            assertTrue(started.await(2, TimeUnit.SECONDS))
            now.addAndGet(HierarchyPayloadStore.RETENTION_MS)
            assertNull("lease expires strictly after the existing bound", expireHierarchyTransfer(executor, fixture.store))
            now.incrementAndGet()
            val expired = expireHierarchyTransfer(executor, fixture.store)
            assertEquals(old, expired)
            val status = fixture.store.status(old.requestId, old.clientNonce, "1".repeat(32))
            assertEquals("FAILED", status.getString("status"))
            assertEquals("WORKER_TIMEOUT", status.getString("error_code"))
            assertFalse(status.optBoolean("payload_complete"))
            val next = begin(fixture)
            val nextWorker = submit(fixture, executor, next)
            awaitWorker(nextWorker)
            assertEquals("READY", nextWorker.result.get()!!.getString("status"))
            release.countDown()
            awaitWorker(oldWorker)
            assertEquals("REQUEST_CANCELLED_OR_STALE", oldWorker.result.get()!!.getString("error_code"))
            assertEquals("READY", fixture.store.status(next.requestId, next.clientNonce, "2".repeat(32)).getString("status"))
        } finally {
            release.countDown()
            oldWorker.completed.await(5, TimeUnit.SECONDS)
        }
    }

    @Test
    fun writerCannotPublishAfterLeaseEvenBeforeNextControlRequest() {
        val now = AtomicLong(100L)
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val fixture = fixture(beforeAtomicFileFinishWrite = {
            started.countDown()
            awaitUninterruptibly(release)
        }, clock = { now.get() })
        val executor = HierarchyTransferExecutorLifecycle()
        val handle = begin(fixture)
        val worker = submit(fixture, executor, handle)
        try {
            assertTrue(started.await(2, TimeUnit.SECONDS))
            now.addAndGet(HierarchyPayloadStore.RETENTION_MS + 1)
            release.countDown()
            awaitWorker(worker)
            assertEquals("FAILED", worker.result.get()!!.getString("status"))
            assertEquals("WORKER_TIMEOUT", worker.result.get()!!.getString("error_code"))
            assertFalse(worker.result.get()!!.optBoolean("payload_complete"))
        } finally {
            release.countDown()
            worker.completed.await(5, TimeUnit.SECONDS)
        }
    }

    @Test
    fun ordinaryPruningDoesNotLoseExpiredCollectingWorkerBeforeFence() {
        val now = AtomicLong(100L)
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val fixture = fixture(clock = { now.get() })
        val executor = HierarchyTransferExecutorLifecycle()
        val old = begin(fixture)
        val worker = submit(fixture, executor, old) {
            started.countDown()
            awaitUninterruptibly(release)
        }
        try {
            assertTrue(started.await(2, TimeUnit.SECONDS))
            now.addAndGet(HierarchyPayloadStore.RETENTION_MS + 1)
            // The raw store path prunes, but may not silently discard an active worker.
            assertEquals("COLLECTING", fixture.store.status(old.requestId, old.clientNonce, "c".repeat(32)).getString("status"))
            assertEquals(old, expireHierarchyTransfer(executor, fixture.store))
            assertEquals("WORKER_TIMEOUT", fixture.store.status(old.requestId, old.clientNonce, "d".repeat(32)).getString("error_code"))
            val next = begin(fixture)
            val nextWorker = submit(fixture, executor, next)
            awaitWorker(nextWorker)
            assertEquals("READY", nextWorker.result.get()!!.getString("status"))
        } finally {
            release.countDown()
            worker.completed.await(5, TimeUnit.SECONDS)
        }
    }

    @Test
    fun actualServiceDestructionAndRecreationRetiresBlockedWorker() {
        val first = Robolectric.buildService(A11yHelperService::class.java).create()
        val firstService = first.get()
        val connect = A11yHelperService::class.java.getDeclaredMethod("onServiceConnected").apply { isAccessible = true }
        connect.invoke(firstService)
        val runtime = HierarchyPayloadRuntime
        val storeField = runtime.javaClass.getDeclaredField("store").apply { isAccessible = true }
        val executorField = runtime.javaClass.getDeclaredField("transferExecutor").apply { isAccessible = true }
        val store = storeField.get(runtime) as HierarchyPayloadStore
        val executor = executorField.get(runtime) as HierarchyTransferExecutorLifecycle
        val identityField = store.javaClass.getDeclaredField("helperIdentity").apply { isAccessible = true }
        val identity = identityField.get(store) as JSONObject
        // Test-only fake identity lets the real store run against a deliberately uncommitted test tree.
        identity.put("build_id", buildId).put("git_commit", gitCommit).put("source_state", "CLEAN")
        val directoryField = store.javaClass.getDeclaredField("directory").apply { isAccessible = true }
        val directory = directoryField.get(store) as File
        val oldServiceId = A11yHelperService.serviceInstanceId
        val fixture = Fixture(directory, store, oldServiceId)
        val old = begin(fixture)
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val worker = submit(fixture, executor, old) {
            started.countDown()
            awaitUninterruptibly(release)
        }
        var second: org.robolectric.android.controller.ServiceController<A11yHelperService>? = null
        try {
            assertTrue(started.await(2, TimeUnit.SECONDS))
            first.destroy()
            assertNull(executor.activeHandleForTest())
            second = Robolectric.buildService(A11yHelperService::class.java).create()
            connect.invoke(second.get())
            assertTrue("runtime must retain process store across services", store === storeField.get(runtime))
            val nextServiceId = A11yHelperService.serviceInstanceId
            assertTrue(nextServiceId != oldServiceId)
            val next = begin(fixture, requestId = old.requestId, serviceId = nextServiceId)
            assertTrue(next.generation > old.generation)
            val replacement = submit(fixture, executor, next)
            awaitWorker(replacement)
            assertEquals("READY", replacement.result.get()!!.getString("status"))
            release.countDown()
            awaitWorker(worker)
            assertEquals("REQUEST_CANCELLED_OR_STALE", worker.result.get()!!.getString("error_code"))
            assertEquals("READY", store.status(next.requestId, next.clientNonce, "e".repeat(32)).getString("status"))
        } finally {
            release.countDown()
            worker.completed.await(5, TimeUnit.SECONDS)
            second?.destroy()
        }
    }

    @Test
    fun staleAndLegacyCleanupCannotMutateReusedIdentityWithSamePayloadHash() {
        val fixture = fixture()
        val executor = HierarchyTransferExecutorLifecycle()
        val old = begin(fixture)
        val oldWorker = submit(fixture, executor, old)
        awaitWorker(oldWorker)
        val oldHash = oldWorker.result.get()!!.getString("payload_sha256")
        assertEventually { executor.activeHandleForTest() == null }
        assertEquals("CANCELLED", fixture.store.cancel(old.requestId, old.clientNonce, "1".repeat(32),
            fixture.store.processEpoch, old.generation).getString("status"))
        val next = begin(fixture, requestId = old.requestId)
        val nextWorker = submit(fixture, executor, next)
        awaitWorker(nextWorker)
        val nextResult = nextWorker.result.get()!!
        assertEquals(oldHash, nextResult.getString("payload_sha256"))
        val uri = Uri.parse(nextResult.getString("payload_uri"))
        assertEquals("REQUEST_IDENTITY_MISMATCH", fixture.store.cancel(old.requestId, old.clientNonce,
            "2".repeat(32), fixture.store.processEpoch, old.generation).getString("error_code"))
        assertEquals("ACK_IDENTITY_MISMATCH", fixture.store.acknowledge(old.requestId, old.clientNonce,
            "3".repeat(32), oldHash, fixture.store.processEpoch, old.generation).getString("error_code"))
        assertEquals("REQUEST_IDENTITY_MISMATCH", fixture.store.cancel(old.requestId, old.clientNonce,
            "4".repeat(32)).getString("error_code"))
        assertEquals("ACK_IDENTITY_MISMATCH", fixture.store.acknowledge(old.requestId, old.clientNonce,
            "5".repeat(32), oldHash).getString("error_code"))
        assertNotNull(fixture.store.resolveReadyFile(uri))
        assertEquals("READY", fixture.store.status(next.requestId, next.clientNonce, "6".repeat(32)).getString("status"))
        assertEquals("ACKED", fixture.store.acknowledge(next.requestId, next.clientNonce, "7".repeat(32),
            oldHash, fixture.store.processEpoch, next.generation).getString("status"))
        assertNull(fixture.store.resolveReadyFile(uri))
    }

    @Test
    fun priorProcessEpochCannotMutateReplacementEvenWhenGenerationAndPayloadMatch() {
        val oldFixture = fixture()
        val newFixture = fixture()
        val oldExecutor = HierarchyTransferExecutorLifecycle()
        val newExecutor = HierarchyTransferExecutorLifecycle()
        val old = begin(oldFixture)
        val oldWorker = submit(oldFixture, oldExecutor, old)
        awaitWorker(oldWorker)
        val next = begin(newFixture, requestId = old.requestId)
        val nextWorker = submit(newFixture, newExecutor, next)
        awaitWorker(nextWorker)
        val hash = oldWorker.result.get()!!.getString("payload_sha256")
        assertEquals(old.generation, next.generation)
        assertEquals(hash, nextWorker.result.get()!!.getString("payload_sha256"))
        val uri = Uri.parse(nextWorker.result.get()!!.getString("payload_uri"))
        assertEquals("REQUEST_IDENTITY_MISMATCH", newFixture.store.cancel(next.requestId, next.clientNonce,
            "8".repeat(32), oldFixture.store.processEpoch, old.generation).getString("error_code"))
        assertEquals("ACK_IDENTITY_MISMATCH", newFixture.store.acknowledge(next.requestId, next.clientNonce,
            "9".repeat(32), hash, oldFixture.store.processEpoch, old.generation).getString("error_code"))
        assertNotNull(newFixture.store.resolveReadyFile(uri))
        assertEquals("CANCELLED", newFixture.store.cancel(next.requestId, next.clientNonce,
            "a".repeat(32), newFixture.store.processEpoch, next.generation).getString("status"))
    }

    @Test
    fun orderedControlBroadcastsFenceOldGenerationBeforeMutation() {
        val fixture = fixture()
        val executor = HierarchyTransferExecutorLifecycle()
        val old = begin(fixture)
        val oldWorker = submit(fixture, executor, old)
        awaitWorker(oldWorker)
        val hash = oldWorker.result.get()!!.getString("payload_sha256")
        assertEventually { executor.activeHandleForTest() == null }
        assertEquals("CANCELLED", fixture.store.cancel(old.requestId, old.clientNonce, "1".repeat(32),
            fixture.store.processEpoch, old.generation).getString("status"))
        val next = begin(fixture, requestId = old.requestId)
        val replacement = submit(fixture, executor, next)
        awaitWorker(replacement)
        val uri = Uri.parse(replacement.result.get()!!.getString("payload_uri"))
        assertEquals(hash, replacement.result.get()!!.getString("payload_sha256"))
        val runtime = HierarchyPayloadRuntime
        val storeField = runtime.javaClass.getDeclaredField("store").apply { isAccessible = true }
        val previous = storeField.get(runtime)
        storeField.set(runtime, fixture.store)
        val context = RuntimeEnvironment.getApplication()
        val receiver = A11yCommandReceiver()
        val filter = IntentFilter().apply {
            addAction(HierarchyPayloadActions.CANCEL)
            addAction(HierarchyPayloadActions.ACK)
        }
        context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
        fun control(action: String, generation: Long?, epoch: String?): JSONObject {
            var encoded: String? = null
            val done = object : BroadcastReceiver() {
                override fun onReceive(context: Context, intent: Intent) { encoded = resultData }
            }
            val intent = Intent(action).putExtra("requestId", next.requestId)
                .putExtra("clientNonce", next.clientNonce).putExtra("queryNonce", "b".repeat(32))
                .putExtra("payloadSha256", hash)
            if (generation != null) intent.putExtra("expectedGeneration", generation.toString())
            if (epoch != null) intent.putExtra("expectedProcessEpoch", epoch)
            context.sendOrderedBroadcast(intent, null, done, null, 0, null, null)
            ShadowLooper.idleMainLooper()
            return HierarchyControlCodec.decode(requireNotNull(encoded))
        }
        try {
            assertEquals("REQUEST_IDENTITY_MISMATCH", control(HierarchyPayloadActions.CANCEL,
                old.generation, fixture.store.processEpoch).getString("error_code"))
            assertEquals("ACK_IDENTITY_MISMATCH", control(HierarchyPayloadActions.ACK,
                old.generation, fixture.store.processEpoch).getString("error_code"))
            assertEquals("REQUEST_IDENTITY_MISMATCH", control(HierarchyPayloadActions.CANCEL,
                null, null).getString("error_code"))
            assertEquals("ACK_IDENTITY_MISMATCH", control(HierarchyPayloadActions.ACK,
                null, null).getString("error_code"))
            assertNotNull(fixture.store.resolveReadyFile(uri))
            assertEquals("ACKED", control(HierarchyPayloadActions.ACK,
                next.generation, fixture.store.processEpoch).getString("status"))
            assertNull(fixture.store.resolveReadyFile(uri))
        } finally {
            context.unregisterReceiver(receiver)
            storeField.set(runtime, previous)
        }
    }

    @Test
    fun delayedCancelCannotRetireReplacementWorkerWhileItIsCollecting() {
        val fixture = fixture()
        val executor = HierarchyTransferExecutorLifecycle()
        val firstStarted = CountDownLatch(1)
        val secondStarted = CountDownLatch(1)
        val releaseFirst = CountDownLatch(1)
        val releaseSecond = CountDownLatch(1)
        val old = begin(fixture)
        val first = submit(fixture, executor, old) {
            firstStarted.countDown()
            awaitUninterruptibly(releaseFirst)
        }
        try {
            assertTrue(firstStarted.await(2, TimeUnit.SECONDS))
            cancel(fixture, executor, old)
            val next = begin(fixture, requestId = old.requestId)
            val second = submit(fixture, executor, next) {
                secondStarted.countDown()
                awaitUninterruptibly(releaseSecond)
            }
            try {
                assertTrue(secondStarted.await(2, TimeUnit.SECONDS))
                val stale = fixture.store.cancelWithLifecycle(old.requestId, old.clientNonce,
                    "f".repeat(32), fixture.store.processEpoch, old.generation)
                assertEquals("REQUEST_IDENTITY_MISMATCH", stale.response.getString("error_code"))
                assertNull(stale.activeHandle)
                assertEquals(next, executor.activeHandleForTest())
                assertEquals("COLLECTING", fixture.store.status(next.requestId, next.clientNonce,
                    "e".repeat(32)).getString("status"))
                releaseSecond.countDown()
                awaitWorker(second)
                assertEquals("READY", second.result.get()!!.getString("status"))
            } finally {
                releaseSecond.countDown()
                second.completed.await(5, TimeUnit.SECONDS)
            }
        } finally {
            releaseFirst.countDown()
            first.completed.await(5, TimeUnit.SECONDS)
        }
    }

}
