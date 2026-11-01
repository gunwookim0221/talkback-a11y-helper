package com.iotpart.sqe.talkbackhelper

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class HelperLifecycleDiagnosticsTest {
    private fun snapshot(
        event: String,
        service: String? = "connection-a",
        connection: String? = "connection-a",
        process: String? = "process-a",
        boot: String? = "boot:12",
        requestId: String? = null,
        queryNonce: String? = null,
    ) = HelperLifecycleDiagnostics.observation(
        lifecycleEvent = event,
        timestampMs = 1_800_000_000_000L,
        pid = 4321,
        processEpoch = process,
        bootEpoch = boot,
        serviceInstanceId = service,
        connectionEpoch = connection,
        buildId = "build-a",
        helperInputDigest = "a".repeat(64),
        requestId = requestId,
        queryNonce = queryNonce,
    )

    @Test
    fun connectionCanChangeWhileProcessAndBootEpochsStayStable() {
        val before = snapshot("ON_SERVICE_CONNECTED", service = "connection-a", connection = "connection-a")
        val after = snapshot("ON_SERVICE_CONNECTED", service = "connection-b", connection = "connection-b")

        assertEquals(before.getString("process_epoch"), after.getString("process_epoch"))
        assertEquals(before.getString("boot_epoch"), after.getString("boot_epoch"))
        assertNotEquals(before.getString("service_instance_id"), after.getString("service_instance_id"))
        assertNotEquals(before.getString("connection_epoch"), after.getString("connection_epoch"))
        assertEquals("OBSERVED", after.getString("observation_status"))
    }

    @Test
    fun pingAndCapabilitiesSnapshotsKeepTheirOwnCorrelationValues() {
        val pingPayload = JSONObject()
            .put("reqId", "ping-req-19")
            .put("helper_service_instance_id", "connection-ping")
            .put("exact_action_state", JSONObject().put("connection_epoch", "connection-ping")
                .put("boot_epoch", "boot:12"))
            .put("helper_build_identity", JSONObject().put("build_id", "build-ping")
                .put("helper_input_digest", "b".repeat(64)))
        val capabilitiesPayload = JSONObject()
            .put("process_epoch", "process-cap")
            .put("service_instance_id", "connection-cap")
            .put("input_digest", "c".repeat(64))
            .put("helper_build_identity", JSONObject().put("build_id", "build-cap")
                .put("input_digest", "c".repeat(64)))
        val ping = HelperLifecycleDiagnostics.pingObservation(
            pingPayload, "process-ping", 1_800_000_000_000L, 4321,
        )
        val capabilities = HelperLifecycleDiagnostics.capabilitiesObservation(
            requestId = null,
            queryNonce = "cap-nonce-31",
            response = capabilitiesPayload,
            exactActionState = JSONObject().put("connection_epoch", "connection-cap")
                .put("boot_epoch", "boot:12"),
            timestampMs = 1_800_000_000_001L,
            pid = 4321,
        )

        assertEquals("ping-req-19", ping.getString("request_id"))
        assertEquals("ping-req-19", ping.getString("request_correlation_id"))
        assertEquals("REQUEST_ID", ping.getString("request_correlation_kind"))
        assertEquals("connection-ping", ping.getString("service_instance_id"))
        assertEquals("connection-ping", ping.getString("connection_epoch"))
        assertEquals("process-ping", ping.getString("process_epoch"))
        assertEquals("build-ping", ping.getString("build_id"))
        assertEquals("b".repeat(64), ping.getString("helper_input_digest"))
        assertEquals("cap-nonce-31", capabilities.getString("query_nonce"))
        assertEquals("cap-nonce-31", capabilities.getString("request_correlation_id"))
        assertEquals("QUERY_NONCE", capabilities.getString("request_correlation_kind"))
        assertEquals("connection-cap", capabilities.getString("service_instance_id"))
        assertEquals("connection-cap", capabilities.getString("connection_epoch"))
        assertEquals("process-cap", capabilities.getString("process_epoch"))
        assertEquals("build-cap", capabilities.getString("build_id"))
        assertEquals("c".repeat(64), capabilities.getString("helper_input_digest"))
        assertFalse(pingPayload.has("lifecycle_event"))
        assertFalse(capabilitiesPayload.has("lifecycle_event"))
        assertFalse(ping.has("success"))
        assertFalse(capabilities.has("authorized"))
    }

    @Test
    fun changedServiceIdentityIsPreservedAsObservationOnly() {
        val oldService = snapshot("ON_SERVICE_CONNECTED", service = "connection-old", connection = "connection-old")
        val pingPayload = JSONObject()
            .put("reqId", "ping-new")
            .put("helper_service_instance_id", "connection-new")
            .put("exact_action_state", JSONObject().put("connection_epoch", "connection-new")
                .put("boot_epoch", "boot:12"))
            .put("helper_build_identity", JSONObject().put("build_id", "build-a")
                .put("helper_input_digest", "a".repeat(64)))
        val newService = HelperLifecycleDiagnostics.pingObservation(
            pingPayload, "process-a", 1_800_000_000_001L, 4321,
        )

        assertEquals("connection-old", oldService.getString("service_instance_id"))
        assertEquals("connection-new", newService.getString("service_instance_id"))
        assertEquals("connection-old", oldService.getString("connection_epoch"))
        assertEquals("connection-new", newService.getString("connection_epoch"))
        assertFalse(newService.has("authority"))
        assertFalse(newService.has("authorized"))
    }

    @Test
    fun missingIdentityEvidenceIsUnknownAndRepresentedAsNull() {
        val missing = HelperLifecycleDiagnostics.capabilitiesObservation(
            requestId = null,
            queryNonce = "cap-nonce-missing",
            response = JSONObject().put("process_epoch", "process-a"),
            exactActionState = null,
            timestampMs = 1_800_000_000_002L,
            pid = 4321,
        )

        assertEquals("UNKNOWN", missing.getString("observation_status"))
        assertTrue(missing.isNull("service_instance_id"))
        assertTrue(missing.isNull("connection_epoch"))
        assertTrue(missing.isNull("boot_epoch"))

        val pingUnavailable = HelperLifecycleDiagnostics.observation(
            lifecycleEvent = "PING_SERVICE_UNAVAILABLE",
            timestampMs = 1_800_000_000_003L,
            pid = 4321,
            processEpoch = "process-a",
            bootEpoch = null,
            serviceInstanceId = null,
            connectionEpoch = null,
            buildId = "build-a",
            helperInputDigest = "a".repeat(64),
            requestId = "ping-unavailable",
        )
        assertEquals("UNKNOWN", pingUnavailable.getString("observation_status"))
        assertEquals("ping-unavailable", pingUnavailable.getString("request_id"))
    }
}
