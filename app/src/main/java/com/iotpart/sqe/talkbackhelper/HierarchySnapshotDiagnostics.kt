package com.iotpart.sqe.talkbackhelper

import android.content.Intent
import android.os.Process
import android.os.SystemClock
import android.util.Log
import org.json.JSONObject

/** Observational-only trace for the reliable HIERARCHY_SNAPSHOT transport. */
internal data class HierarchySnapshotTraceContext(
    val requestId: String,
    val runId: String,
    val scenarioId: String,
    val step: String,
    val deviceSerial: String,
    val startedElapsedNanos: Long,
    val pid: Int,
    val processEpoch: String,
    val bootEpoch: String,
    val serviceInstanceId: String,
    val connectionEpoch: String,
    val buildId: String,
    val helperInputDigest: String,
)

internal class HierarchySnapshotTrace(
    private val context: HierarchySnapshotTraceContext,
    private val sink: (String) -> Unit = { line -> Log.i("A11Y_HELPER", "[HIERARCHY_SNAPSHOT_STAGE] $line") },
    private val monotonicClock: () -> Long = { SystemClock.elapsedRealtimeNanos() },
    private val failureSink: (Throwable) -> Unit = {},
) {
    fun mark(stage: String, fields: Map<String, Any?> = emptyMap()) {
        try {
            val now = monotonicClock()
            val record = JSONObject()
                .put("timestamp_ms", System.currentTimeMillis())
                .put("monotonic_ns", now)
                .put("elapsed_ms", ((now - context.startedElapsedNanos).coerceAtLeast(0L)) / 1_000_000.0)
                .put("stage", stage.take(64))
                .put("request_id", context.requestId.takeIf { it.isNotBlank() } ?: JSONObject.NULL)
                .put("run_id", context.runId)
                .put("scenario_id", context.scenarioId)
                .put("step", context.step)
                .put("device_serial", context.deviceSerial)
                .put("pid", context.pid.takeIf { it > 0 } ?: JSONObject.NULL)
                .put("process_epoch", context.processEpoch)
                .put("boot_epoch", context.bootEpoch)
                .put("service_instance_id", context.serviceInstanceId)
                .put("connection_epoch", context.connectionEpoch)
                .put("build_id", context.buildId)
                .put("helper_input_digest", context.helperInputDigest)
            fields.forEach { (key, value) ->
                if (key.matches(Regex("[a-zA-Z0-9_]{1,48}"))) {
                    record.put(key, value ?: JSONObject.NULL)
                }
            }
            sink(record.toString())
        } catch (error: Throwable) {
            // Diagnostics are deliberately unable to change transport results or authority.
            runCatching { failureSink(error) }
        }
    }

    fun <T> around(stage: String, action: () -> T): T {
        mark("${stage}_START")
        return try {
            action().also { mark("${stage}_COMPLETE") }
        } catch (error: Throwable) {
            mark("ERROR_STAGE", mapOf("failed_stage" to stage, "error_type" to error.javaClass.simpleName))
            throw error
        }
    }
}

internal object HierarchySnapshotDiagnostics {
    fun fromIntent(intent: Intent, requestId: String): HierarchySnapshotTrace = create(
        requestId = requestId,
        runId = intent.getStringExtra(EXTRA_RUN_ID).orUnknown(),
        scenarioId = intent.getStringExtra(EXTRA_SCENARIO_ID).orUnknown(),
        step = intent.getStringExtra(EXTRA_STEP).orUnknown(),
        deviceSerial = intent.getStringExtra(EXTRA_DEVICE_SERIAL).orUnknown(),
        readCurrentConnectionState = intent.action == HierarchyPayloadActions.START ||
            intent.action == HierarchyPayloadActions.CAPABILITIES,
    )

    fun create(
        requestId: String,
        runId: String = UNKNOWN,
        scenarioId: String = UNKNOWN,
        step: String = UNKNOWN,
        deviceSerial: String = UNKNOWN,
        readCurrentConnectionState: Boolean = true,
    ): HierarchySnapshotTrace {
        val exactState = if (readCurrentConnectionState) runCatching { ExactActionRuntime.status() }.getOrNull() else null
        val serviceId = A11yHelperService.serviceInstanceId.takeIf { A11yHelperService.instance != null }
        val context = HierarchySnapshotTraceContext(
            requestId = requestId,
            runId = runId.orUnknown(),
            scenarioId = scenarioId.orUnknown(),
            step = step.orUnknown(),
            deviceSerial = deviceSerial.orUnknown(),
            startedElapsedNanos = SystemClock.elapsedRealtimeNanos(),
            pid = Process.myPid(),
            processEpoch = runCatching { HierarchyPayloadRuntime.processEpochForDiagnostics() }.getOrNull().orUnknown(),
            bootEpoch = exactState?.optString("boot_epoch").orUnknown(),
            serviceInstanceId = serviceId.orUnknown(),
            connectionEpoch = exactState?.optString("connection_epoch").orUnknown(),
            buildId = BuildIdentity.buildId,
            helperInputDigest = BuildIdentity.inputDigest,
        )
        return HierarchySnapshotTrace(context)
    }

    const val EXTRA_RUN_ID = "hierarchyDiagnosticRunId"
    const val EXTRA_SCENARIO_ID = "hierarchyDiagnosticScenarioId"
    const val EXTRA_STEP = "hierarchyDiagnosticStep"
    const val EXTRA_DEVICE_SERIAL = "hierarchyDiagnosticDeviceSerial"
    const val UNKNOWN = "UNKNOWN"

    private fun String?.orUnknown(): String = this?.takeIf { it.isNotBlank() && it != "null" } ?: UNKNOWN
}
