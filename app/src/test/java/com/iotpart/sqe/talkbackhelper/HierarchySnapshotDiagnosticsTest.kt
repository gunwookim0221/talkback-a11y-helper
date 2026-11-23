package com.iotpart.sqe.talkbackhelper

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class HierarchySnapshotDiagnosticsTest {
    private fun context() = HierarchySnapshotTraceContext(
        requestId = "request-1",
        runId = "run-2",
        scenarioId = "scenario-3",
        step = "4",
        deviceSerial = "serial-5",
        startedElapsedNanos = 100L,
        pid = 6,
        processEpoch = "process-7",
        bootEpoch = "boot-8",
        serviceInstanceId = "service-9",
        connectionEpoch = "connection-10",
        buildId = "build-11",
        helperInputDigest = "input-12",
    )

    @Test
    fun stageMarkersKeepRequestAndIdentityCorrelation() {
        val lines = mutableListOf<String>()
        val failures = mutableListOf<Throwable>()
        HierarchySnapshotTrace(context(), lines::add, { 200L }, failures::add).mark("SNAPSHOT_COMPLETE", mapOf("node_count" to 23))
        assertTrue(failures.map { it.toString() }.toString(), failures.isEmpty())

        val record = JSONObject(lines.single())
        assertEquals("SNAPSHOT_COMPLETE", record.getString("stage"))
        assertEquals("request-1", record.getString("request_id"))
        assertEquals("run-2", record.getString("run_id"))
        assertEquals("scenario-3", record.getString("scenario_id"))
        assertEquals("4", record.getString("step"))
        assertEquals("serial-5", record.getString("device_serial"))
        assertEquals("process-7", record.getString("process_epoch"))
        assertEquals("boot-8", record.getString("boot_epoch"))
        assertEquals("service-9", record.getString("service_instance_id"))
        assertEquals("connection-10", record.getString("connection_epoch"))
        assertEquals("build-11", record.getString("build_id"))
        assertEquals("input-12", record.getString("helper_input_digest"))
        assertTrue(record.getLong("monotonic_ns") >= 100L)
        assertTrue(record.getDouble("elapsed_ms") >= 0.0)
        assertEquals(23, record.getInt("node_count"))
        assertFalse(record.has("visit_credit"))
        assertFalse(record.has("authority"))
    }

    @Test
    fun diagnosticsFailureDoesNotChangeReturnOrOperationFailure() {
        val trace = HierarchySnapshotTrace(
            context(),
            sink = { error("logger unavailable") },
            monotonicClock = { 200L },
        )
        assertEquals(17, trace.around("PAYLOAD_READ") { 17 })

        val expected = IllegalStateException("payload unavailable")
        val actual = runCatching {
            trace.around("ROOT_ACQUISITION") { throw expected }
        }.exceptionOrNull()
        assertNotNull(actual)
        assertSame(expected, actual)
    }

    @Test
    fun failureDetailsSurviveLoggerFailureWithoutChangingFailureOutcome() {
        val trace = HierarchySnapshotTrace(
            context(),
            sink = { error("logger unavailable") },
            monotonicClock = { 200L },
        )
        trace.mark("ERROR_STAGE", mapOf("failed_stage" to "ROOT_ACQUISITION", "error_type" to "IllegalStateException"))

        assertEquals("ROOT_ACQUISITION" to "IllegalStateException", trace.failureDetails())
    }

    @Test
    fun queueStateTraceIsObservationalAndQueueReadFailureStaysUnavailable() {
        val lines = mutableListOf<String>()
        val trace = HierarchySnapshotTrace(context(), lines::add, { 200L })
        HierarchySnapshotDiagnostics.recordQueueState(
            trace,
            eventQueueSnapshot = { throw IllegalStateException("queue read failed") },
            helperQueueSnapshot = { mapOf("helper_pending_queue_depth" to 0, "helper_active_operation_count" to 0) },
        )
        val operationResult = trace.around("SNAPSHOT_READ") { "READY" }

        assertEquals("READY", operationResult)
        val record = JSONObject(lines.first())
        assertEquals("WORK_QUEUE_STATE", record.getString("stage"))
        assertEquals("UNAVAILABLE", record.getString("event_worker_queue_status"))
        assertEquals(0, record.getInt("helper_pending_queue_depth"))
        assertEquals(0, record.getInt("helper_active_operation_count"))
        assertFalse(record.has("authority"))
        assertFalse(record.has("visit_credit"))
    }

    @Test
    fun unavailableIdentityAndScenarioContextStayExplicitlyUnknown() {
        val lines = mutableListOf<String>()
        val failures = mutableListOf<Throwable>()
        val unknown = context().copy(
            runId = "UNKNOWN",
            scenarioId = "UNKNOWN",
            step = "UNKNOWN",
            deviceSerial = "UNKNOWN",
            bootEpoch = "UNKNOWN",
            connectionEpoch = "UNKNOWN",
        )
        HierarchySnapshotTrace(unknown, lines::add, { 200L }, failures::add).mark("DEVICE_RECEIVE")
        assertTrue(failures.map { it.toString() }.toString(), failures.isEmpty())

        val record = JSONObject(lines.single())
        assertEquals("UNKNOWN", record.getString("run_id"))
        assertEquals("UNKNOWN", record.getString("scenario_id"))
        assertEquals("UNKNOWN", record.getString("step"))
        assertEquals("UNKNOWN", record.getString("device_serial"))
        assertEquals("UNKNOWN", record.getString("boot_epoch"))
        assertEquals("UNKNOWN", record.getString("connection_epoch"))
    }
}
