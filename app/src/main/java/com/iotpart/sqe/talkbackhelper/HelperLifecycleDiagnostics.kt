package com.iotpart.sqe.talkbackhelper

import android.os.Process
import android.util.Log
import org.json.JSONObject

/** Read-only lifecycle observations. Nothing produced here participates in a gate or action. */
internal object HelperLifecycleDiagnostics {
    private const val TAG = "A11Y_HELPER"

    internal fun observation(
        lifecycleEvent: String,
        timestampMs: Long?,
        pid: Int?,
        processEpoch: String?,
        bootEpoch: String?,
        serviceInstanceId: String?,
        connectionEpoch: String?,
        buildId: String?,
        helperInputDigest: String?,
        requestId: String? = null,
        queryNonce: String? = null,
    ): JSONObject {
        val correlationId = requestId ?: queryNonce
        val correlationKind = when {
            requestId != null -> "REQUEST_ID"
            queryNonce != null -> "QUERY_NONCE"
            else -> null
        }
        val observationStatus = if (
            lifecycleEvent.isNotBlank() && timestampMs != null && timestampMs > 0L && pid != null && pid > 0 &&
            listOf(processEpoch, bootEpoch, serviceInstanceId, connectionEpoch, buildId, helperInputDigest)
                .all(::known) &&
            (!isRequestObservation(lifecycleEvent) || !correlationId.isNullOrBlank())
        ) "OBSERVED" else "UNKNOWN"

        return JSONObject()
            .put("timestamp_ms", timestampMs ?: JSONObject.NULL)
            .put("pid", pid ?: JSONObject.NULL)
            .put("process_epoch", processEpoch ?: JSONObject.NULL)
            .put("boot_epoch", bootEpoch ?: JSONObject.NULL)
            .put("service_instance_id", serviceInstanceId ?: JSONObject.NULL)
            .put("connection_epoch", connectionEpoch ?: JSONObject.NULL)
            .put("lifecycle_event", lifecycleEvent.takeIf { it.isNotBlank() } ?: "UNKNOWN")
            .put("build_id", buildId ?: JSONObject.NULL)
            .put("helper_input_digest", helperInputDigest ?: JSONObject.NULL)
            .put("request_id", requestId ?: JSONObject.NULL)
            .put("query_nonce", queryNonce ?: JSONObject.NULL)
            .put("request_correlation_id", correlationId ?: JSONObject.NULL)
            .put("request_correlation_kind", correlationKind ?: JSONObject.NULL)
            .put("observation_status", observationStatus)
    }

    internal fun recordServiceLifecycle(lifecycleEvent: String) {
        safely {
            val status = ExactActionRuntime.status()
            val serviceId = A11yHelperService.serviceInstanceId.takeIf { A11yHelperService.instance != null }
            emit(observation(
                lifecycleEvent = lifecycleEvent,
                timestampMs = System.currentTimeMillis(),
                pid = Process.myPid(),
                processEpoch = HierarchyPayloadRuntime.processEpochForDiagnostics(),
                bootEpoch = stringField(status, "boot_epoch"),
                serviceInstanceId = serviceId,
                connectionEpoch = stringField(status, "connection_epoch"),
                buildId = BuildConfig.HELPER_BUILD_ID,
                helperInputDigest = BuildConfig.HELPER_INPUT_DIGEST,
            ))
        }
    }

    internal fun recordPingResponse(payload: JSONObject) {
        safely {
            emit(pingObservation(
                payload = payload,
                processEpoch = HierarchyPayloadRuntime.processEpochForDiagnostics(),
                timestampMs = System.currentTimeMillis(),
                pid = Process.myPid(),
            ))
        }
    }

    internal fun pingObservation(
        payload: JSONObject,
        processEpoch: String?,
        timestampMs: Long?,
        pid: Int?,
    ): JSONObject {
        val exactState = payload.optJSONObject("exact_action_state")
        val identity = payload.optJSONObject("helper_build_identity")
        return observation(
            lifecycleEvent = "PING_RESPONSE",
            timestampMs = timestampMs,
            pid = pid,
            processEpoch = processEpoch,
            bootEpoch = stringField(exactState, "boot_epoch"),
            serviceInstanceId = stringField(payload, "helper_service_instance_id"),
            connectionEpoch = stringField(exactState, "connection_epoch"),
            buildId = stringField(identity, "build_id"),
            helperInputDigest = stringField(identity, "helper_input_digest"),
            requestId = stringField(payload, "reqId"),
        )
    }

    internal fun recordPingUnavailable(requestId: String) {
        safely {
            emit(observation(
                lifecycleEvent = "PING_SERVICE_UNAVAILABLE",
                timestampMs = System.currentTimeMillis(),
                pid = Process.myPid(),
                processEpoch = HierarchyPayloadRuntime.processEpochForDiagnostics(),
                bootEpoch = null,
                serviceInstanceId = null,
                connectionEpoch = null,
                buildId = BuildConfig.HELPER_BUILD_ID,
                helperInputDigest = BuildConfig.HELPER_INPUT_DIGEST,
                requestId = requestId.takeIf { it.isNotBlank() },
            ))
        }
    }

    internal fun recordCapabilitiesResponse(
        requestId: String?,
        queryNonce: String,
        response: JSONObject,
    ) {
        safely {
            val exactState = if (stringField(response, "service_instance_id") != null &&
                A11yHelperService.instance != null) {
                ExactActionRuntime.status()
            } else null
            emit(capabilitiesObservation(
                requestId = requestId,
                queryNonce = queryNonce,
                response = response,
                exactActionState = exactState,
                timestampMs = System.currentTimeMillis(),
                pid = Process.myPid(),
            ))
        }
    }

    internal fun capabilitiesObservation(
        requestId: String?,
        queryNonce: String?,
        response: JSONObject,
        exactActionState: JSONObject?,
        timestampMs: Long?,
        pid: Int?,
    ): JSONObject {
        val identity = response.optJSONObject("helper_build_identity")
        return observation(
            lifecycleEvent = "CAPABILITIES_RESPONSE",
            timestampMs = timestampMs,
            pid = pid,
            processEpoch = stringField(response, "process_epoch"),
            bootEpoch = stringField(exactActionState, "boot_epoch"),
            serviceInstanceId = stringField(response, "service_instance_id"),
            connectionEpoch = stringField(exactActionState, "connection_epoch"),
            buildId = stringField(identity, "build_id"),
            helperInputDigest = stringField(identity, "input_digest")
                ?: stringField(response, "input_digest"),
            requestId = requestId?.takeIf { it.isNotBlank() },
            queryNonce = queryNonce?.takeIf { it.isNotBlank() },
        )
    }

    private fun isRequestObservation(lifecycleEvent: String): Boolean =
        lifecycleEvent == "PING_RESPONSE" || lifecycleEvent == "PING_SERVICE_UNAVAILABLE" ||
            lifecycleEvent == "CAPABILITIES_RESPONSE"

    private fun known(value: String?): Boolean =
        !value.isNullOrBlank() && !value.equals("UNKNOWN", ignoreCase = true)

    private fun stringField(source: JSONObject?, key: String): String? {
        if (source == null || !source.has(key) || source.isNull(key)) return null
        return source.optString(key).takeIf { it.isNotBlank() && it != "null" }
    }

    private fun emit(payload: JSONObject) {
        Log.i(TAG, "[HELPER_LIFECYCLE_OBSERVATION] $payload")
    }

    private inline fun safely(write: () -> Unit) {
        try {
            write()
        } catch (_: Throwable) {
            // Observability must never affect lifecycle, identity gates, or command handling.
        }
    }
}
