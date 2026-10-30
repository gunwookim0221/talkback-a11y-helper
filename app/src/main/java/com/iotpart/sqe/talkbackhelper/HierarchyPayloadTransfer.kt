package com.iotpart.sqe.talkbackhelper

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.ParcelFileDescriptor
import android.os.Process
import android.os.SystemClock
import android.util.AtomicFile
import android.util.Base64
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.IOException
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.UUID
import java.nio.file.Files
import java.util.concurrent.RejectedExecutionException

internal object HierarchyPayloadActions {
    const val CAPABILITIES = "com.iotpart.sqe.talkbackhelper.HIERARCHY_TRANSFER_CAPABILITIES"
    const val START = "com.iotpart.sqe.talkbackhelper.HIERARCHY_TRANSFER_START"
    const val STATUS = "com.iotpart.sqe.talkbackhelper.HIERARCHY_TRANSFER_STATUS"
    const val ACK = "com.iotpart.sqe.talkbackhelper.HIERARCHY_TRANSFER_ACK"
    const val CANCEL = "com.iotpart.sqe.talkbackhelper.HIERARCHY_TRANSFER_CANCEL"
    const val CONTROL_SCHEMA = "hierarchy-transfer-control.v1"
    const val LEGACY_DIAGNOSTIC_SCHEMA = "service-hierarchy-v1"
    const val PAYLOAD_SCHEMA = "service-hierarchy-v2"
    const val CAPTURE_ENVELOPE_SCHEMA = "phase6d-capture-envelope-v1"
    const val CAPTURE_CANONICALIZATION = "capture-canonical-json-v1"
    const val MIME_TYPE = "application/vnd.talkback.hierarchy"
    const val CONTROL_PREFIX = "HPT1:"
    const val RESULT_OK = 1
    const val RESULT_REJECTED = 2
    const val EXTRA_REQUEST_ID = "requestId"
    const val EXTRA_CLIENT_NONCE = "clientNonce"
    const val EXTRA_QUERY_NONCE = "queryNonce"
    const val EXTRA_EXPECTED_BUILD_ID = "expectedBuildId"
    const val EXTRA_EXPECTED_GIT_COMMIT = "expectedGitCommit"
    const val EXTRA_EXPECTED_SERVICE_INSTANCE_ID = "expectedServiceInstanceId"
    const val EXTRA_PAYLOAD_SHA256 = "payloadSha256"
    const val EXTRA_EXPECTED_PROCESS_EPOCH = "expectedProcessEpoch"
    const val EXTRA_EXPECTED_GENERATION = "expectedGeneration"

    val ALL = setOf(CAPABILITIES, START, STATUS, ACK, CANCEL)
}

internal object HierarchyPayloadEnvelope {
    private val MAGIC = "TBHIER01".toByteArray(StandardCharsets.US_ASCII)
    private val TRAILER = "TBHEND01".toByteArray(StandardCharsets.US_ASCII)
    const val MAX_PAYLOAD_BYTES = 750_000
    const val MAX_HEADER_BYTES = 8_192
    const val MAX_ARTIFACT_BYTES = 758_220

    data class Decoded(val header: JSONObject, val payload: ByteArray)

    /** Serializer-compatible size preflight before JSONObject creates its serialized copy. */
    fun estimatedJsonUtf8Bytes(value: Any?, limit: Int = MAX_PAYLOAD_BYTES): Long {
        fun add(left: Long, right: Long): Long =
            if (right > limit || left > limit.toLong() - right) limit.toLong() + 1 else left + right
        fun stringBytes(text: String): Long {
            if (text.length > limit) return limit.toLong() + 1
            var size = 2L
            var index = 0
            while (index < text.length) {
                val char = text[index]
                val cost = when {
                    char == '"' || char == '\\' -> 2L
                    char == '\b' || char == '\u000c' || char == '\n' || char == '\r' || char == '\t' -> 2L
                    char.code < 0x20 -> 6L
                    char.code in 0x7F..0x9F || char.code in 0x2000..0x20FF -> 6L
                    char.code in 0xD800..0xDBFF && index + 1 < text.length && text[index + 1].code in 0xDC00..0xDFFF -> 4L
                    char.code in 0xD800..0xDFFF -> 1L
                    char.code < 0x80 -> 1L
                    char.code < 0x800 -> 2L
                    else -> 3L
                }
                size = add(size, cost)
                if (size > limit) return size
                if (char.code in 0xD800..0xDBFF && index + 1 < text.length && text[index + 1].code in 0xDC00..0xDFFF) index++
                index++
            }
            return size
        }
        fun estimate(item: Any?, depth: Int): Long {
            if (depth > 128) return limit.toLong() + 1
            return when (item) {
                null, JSONObject.NULL -> 4L
                is String -> stringBytes(item)
                is JSONObject -> {
                    var size = 2L
                    val keys = item.keys()
                    var first = true
                    while (keys.hasNext()) {
                        val key = keys.next()
                        if (!first) size = add(size, 1)
                        first = false
                        size = add(size, stringBytes(key))
                        size = add(size, 1)
                        size = add(size, estimate(item.opt(key), depth + 1))
                        if (size > limit) return size
                    }
                    size
                }
                is JSONArray -> {
                    var size = 2L
                    for (index in 0 until item.length()) {
                        if (index > 0) size = add(size, 1)
                        size = add(size, estimate(item.opt(index), depth + 1))
                        if (size > limit) return size
                    }
                    size
                }
                is Number, is Boolean -> item.toString().length.toLong()
                else -> stringBytes(item.toString())
            }
        }
        return estimate(value, 0)
    }

    fun encode(header: JSONObject, payload: ByteArray): ByteArray {
        require(payload.size <= MAX_PAYLOAD_BYTES) { "PAYLOAD_TOO_LARGE" }
        val headerBytes = header.toString().toByteArray(StandardCharsets.UTF_8)
        require(headerBytes.size <= MAX_HEADER_BYTES) { "HEADER_TOO_LARGE" }
        val total = MAGIC.size + 4 + 8 + headerBytes.size + payload.size + TRAILER.size
        require(total <= MAX_ARTIFACT_BYTES)
        return ByteArrayOutputStream(total).use { buffer ->
            DataOutputStream(buffer).use { out ->
                out.write(MAGIC)
                out.writeInt(headerBytes.size)
                out.writeLong(payload.size.toLong())
                out.write(headerBytes)
                out.write(payload)
                out.write(TRAILER)
            }
            buffer.toByteArray()
        }
    }

    fun decode(bytes: ByteArray): Decoded {
        require(bytes.size in (MAGIC.size + 12 + TRAILER.size)..MAX_ARTIFACT_BYTES) { "ARTIFACT_SIZE_INVALID" }
        DataInputStream(ByteArrayInputStream(bytes)).use { input ->
            val magic = ByteArray(MAGIC.size).also(input::readFully)
            require(magic.contentEquals(MAGIC)) { "MAGIC_INVALID" }
            val headerSize = input.readInt()
            val payloadSize = input.readLong()
            require(headerSize in 1..MAX_HEADER_BYTES && payloadSize in 0..MAX_PAYLOAD_BYTES.toLong()) {
                "LENGTH_INVALID"
            }
            val expectedSize = MAGIC.size.toLong() + 12 + headerSize + payloadSize + TRAILER.size
            require(expectedSize == bytes.size.toLong()) { "LENGTH_MISMATCH" }
            val headerBytes = ByteArray(headerSize).also(input::readFully)
            val payload = ByteArray(payloadSize.toInt()).also(input::readFully)
            val trailer = ByteArray(TRAILER.size).also(input::readFully)
            require(trailer.contentEquals(TRAILER) && input.read() == -1) { "TRAILER_INVALID" }
            val header = JSONObject(headerBytes.toString(StandardCharsets.UTF_8))
            require(header.getInt("payload_bytes") == payload.size) { "HEADER_LENGTH_MISMATCH" }
            require(header.getString("payload_sha256") == sha256(payload)) { "PAYLOAD_HASH_MISMATCH" }
            return Decoded(header, payload)
        }
    }

    fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it.toInt() and 0xff) }
}

/** Process/service scoped, request addressed immutable hierarchy files. */
internal class HierarchyPayloadStore(
    private val directory: File,
    val processEpoch: String = UUID.randomUUID().toString(),
    private val elapsedRealtimeMs: () -> Long = { SystemClock.elapsedRealtime() },
    private val helperIdentity: JSONObject = currentBuildIdentity(),
    private val beforeAtomicFileFinishWrite: (File) -> Unit = {},
) {
    data class RequestHandle internal constructor(val requestId: String, val clientNonce: String, val generation: Long)
    data class Cancellation internal constructor(val response: JSONObject, val activeHandle: RequestHandle?)

    private data class Record(
        val handle: RequestHandle,
        var queryNonce: String,
        val serviceInstanceId: String,
        val helperIdentity: JSONObject,
        val createdElapsedNs: Long,
        val startedAtMs: Long,
        var retentionStartedAtMs: Long = startedAtMs,
        val token: String,
        var state: String,
        var errorCode: String? = null,
        var payloadBytes: Int? = null,
        var payloadSha256: String? = null,
        var artifactBytes: Int? = null,
        var artifactSha256: String? = null,
        var payloadUri: String? = null,
        var file: File? = null,
        var reservedBytes: Int = HierarchyPayloadEnvelope.MAX_ARTIFACT_BYTES,
        var captureSequence: Long? = null,
    )

    private val records = LinkedHashMap<String, Record>()
    private var currentServiceInstanceId: String? = null
    private var generation = 0L
    private var captureSequence = 0L
    private var activeCollector: RequestHandle? = null
    private val activeWriteFiles = mutableSetOf<File>()

    @Synchronized
    fun serviceConnected(serviceInstanceId: String) {
        invalidateAll("SERVICE_INSTANCE_CHANGED")
        currentServiceInstanceId = serviceInstanceId
        captureSequence = 0L
        directory.mkdirs()
    }

    @Synchronized
    fun begin(
        requestId: String,
        clientNonce: String,
        queryNonce: String,
        expectedBuildId: String,
        expectedGitCommit: String,
        expectedServiceInstanceId: String,
    ): JSONObject {
        pruneExpired()
        val serviceId = currentServiceInstanceId
            ?: return errorResponse(requestId, clientNonce, queryNonce, "SERVICE_UNAVAILABLE")
        if (!requestId.matches(Regex("[0-9a-f]{32}")) || !clientNonce.matches(Regex("[0-9a-f]{32}")) ||
            !queryNonce.matches(Regex("[0-9a-f]{32}"))) {
            return errorResponse(requestId, clientNonce, queryNonce, "IDENTIFIER_INVALID")
        }
        if (records.containsKey(requestId)) return errorResponse(requestId, clientNonce, queryNonce, "DUPLICATE_REQUEST")
        if (serviceId != expectedServiceInstanceId || helperIdentity.optString("build_id") != expectedBuildId ||
            helperIdentity.optString("git_commit") != expectedGitCommit || helperIdentity.optString("source_state") != "CLEAN") {
            return errorResponse(requestId, clientNonce, queryNonce, "IDENTITY_MISMATCH")
        }
        if (activeCollector != null) return errorResponse(requestId, clientNonce, queryNonce, "BUSY")
        if (records.size >= MAX_RECORDS || reservedBytes() + HierarchyPayloadEnvelope.MAX_ARTIFACT_BYTES > MAX_TOTAL_BYTES) {
            return errorResponse(requestId, clientNonce, queryNonce, "QUOTA_EXCEEDED")
        }
        val handle = RequestHandle(requestId, clientNonce, ++generation)
        val token = UUID.randomUUID().toString().replace("-", "")
        val identity = JSONObject(helperIdentity.toString())
        val record = Record(
            handle = handle,
            queryNonce = queryNonce,
            serviceInstanceId = serviceId,
            helperIdentity = identity,
            createdElapsedNs = SystemClock.elapsedRealtimeNanos(),
            startedAtMs = elapsedRealtimeMs(),
            token = token,
            state = "ACCEPTED",
        )
        records[requestId] = record
        activeCollector = handle
        return response(record, completed = false)
    }

    @Synchronized
    fun capabilities(queryNonce: String): JSONObject {
        if (!queryNonce.matches(Regex("[0-9a-f]{32}"))) return errorResponse("", "", queryNonce, "QUERY_NONCE_INVALID")
        val serviceId = currentServiceInstanceId
            ?: return errorResponse("", "", queryNonce, "SERVICE_UNAVAILABLE")
        return JSONObject()
            .put("schema", HierarchyPayloadActions.CONTROL_SCHEMA)
            .put("protocol_version", "hierarchy-payload.v1")
            .put("request_id", JSONObject.NULL)
            .put("query_nonce", queryNonce)
            .put("process_epoch", processEpoch)
            .put("service_instance_id", serviceId)
            .put("generation", generation)
            .put("helper_build_identity", JSONObject(helperIdentity.toString()))
            .put("payload_schema_version", HierarchyPayloadActions.PAYLOAD_SCHEMA)
            .put("supported_payload_schema_versions", JSONArray().put(HierarchyPayloadActions.PAYLOAD_SCHEMA))
            .put("capture_envelope_schema_version", HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA)
            .put("supported_capture_envelope_schema_versions", JSONArray().put(HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA))
            .put("capture_canonicalization_version", HierarchyPayloadActions.CAPTURE_CANONICALIZATION)
            .put("supported_capture_canonicalization_versions", JSONArray().put(HierarchyPayloadActions.CAPTURE_CANONICALIZATION))
            .put("capture_root_id_version", ReliableHierarchyCandidateContract.ROOT_CAPTURE_ID_VERSION)
            .put("supported_capture_root_id_versions", JSONArray().put(ReliableHierarchyCandidateContract.ROOT_CAPTURE_ID_VERSION))
            .put("candidate_schema_version", ReliableHierarchyCandidateContract.SCHEMA_VERSION)
            .put("supported_candidate_schema_versions", JSONArray().put(ReliableHierarchyCandidateContract.SCHEMA_VERSION))
            .put("candidate_contract_version", ReliableHierarchyCandidateContract.CONTRACT_VERSION)
            .put("diagnostic_schema_version", HierarchyPayloadActions.LEGACY_DIAGNOSTIC_SCHEMA)
            .put("diagnostic_payload_schema_versions", JSONArray().put(HierarchyPayloadActions.LEGACY_DIAGNOSTIC_SCHEMA))
            .put("max_payload_bytes", HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES)
            .put("max_artifact_bytes", HierarchyPayloadEnvelope.MAX_ARTIFACT_BYTES)
            .put("status", "OK")
            .put("completed", true)
            .put("payload_complete", true)
            .put("capabilities", JSONArray()
                .put("ordered_control")
                .put("atomic_file")
                .put("content_provider_pfd")
                .put("service_hierarchy_v2")
                .put(ReliableHierarchyCandidateContract.SCHEMA_VERSION)
                .put(HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA)
                .put(HierarchyPayloadActions.CAPTURE_CANONICALIZATION)
                .put(ReliableHierarchyCandidateContract.ROOT_CAPTURE_ID_VERSION))
    }

    @Synchronized
    fun markCollecting(handle: RequestHandle): Boolean {
        val record = records[handle.requestId] ?: return false
        if (!same(record, handle) || record.state != "ACCEPTED" || currentServiceInstanceId != record.serviceInstanceId) return false
        record.state = "COLLECTING"
        return true
    }

    @Synchronized
    fun reserveCaptureSequence(handle: RequestHandle): Long? {
        val record = records[handle.requestId] ?: return null
        if (!same(record, handle) || record.state != "COLLECTING" ||
            currentServiceInstanceId != record.serviceInstanceId || record.captureSequence != null) return null
        captureSequence += 1
        if (captureSequence <= 0) return null
        record.captureSequence = captureSequence
        return captureSequence
    }

    fun publish(handle: RequestHandle, payload: ByteArray): JSONObject {
        val record = synchronized(this) {
            val found = records[handle.requestId]
            if (found == null || !same(found, handle) || found.state != "COLLECTING" ||
                currentServiceInstanceId != found.serviceInstanceId) return@synchronized null
            if (elapsedRealtimeMs() - found.startedAtMs > RETENTION_MS) {
                found.state = "FAILED"
                found.errorCode = "WORKER_TIMEOUT"
                found.retentionStartedAtMs = elapsedRealtimeMs()
                found.reservedBytes = 0
                return response(found, completed = true)
            }
            if (found.captureSequence == null) {
                found.state = "FAILED"
                found.errorCode = "CAPTURE_SEQUENCE_MISSING"
                found.reservedBytes = 0
                if (activeCollector == handle) activeCollector = null
                return response(found, completed = true)
            }
            if (payload.size > HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES) {
                found.state = "FAILED"
                found.errorCode = "PAYLOAD_TOO_LARGE"
                found.reservedBytes = 0
                if (activeCollector == handle) activeCollector = null
                return response(found, completed = true)
            }
            found.state = "WRITING"
            found.payloadBytes = payload.size
            found.payloadSha256 = HierarchyPayloadEnvelope.sha256(payload)
            activeWriteFiles += readyFile(found)
            found
        } ?: return errorResponse(handle.requestId, handle.clientNonce, "", "REQUEST_CANCELLED_OR_STALE")

        val readyFile = readyFile(record)
        val atomicFile = AtomicFile(readyFile)
        try {
            if (!directory.exists() && !directory.mkdirs()) throw IOException("DIRECTORY_CREATE_FAILED")
            val header = JSONObject()
                .put("protocol_version", "hierarchy-payload.v1")
                .put("request_id", record.handle.requestId)
                .put("client_nonce", record.handle.clientNonce)
                .put("process_epoch", processEpoch)
                .put("generation", record.handle.generation)
                .put("service_instance_id", record.serviceInstanceId)
                .put("helper_build_identity", record.helperIdentity)
                .put("payload_schema_version", HierarchyPayloadActions.PAYLOAD_SCHEMA)
                .put("candidate_schema_version", ReliableHierarchyCandidateContract.SCHEMA_VERSION)
                .put("candidate_contract_version", ReliableHierarchyCandidateContract.CONTRACT_VERSION)
                .put("capture_sequence", record.captureSequence ?: throw IOException("CAPTURE_SEQUENCE_MISSING"))
                .put("capture_envelope_schema_version", HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA)
                .put("capture_canonicalization_version", HierarchyPayloadActions.CAPTURE_CANONICALIZATION)
                .put("capture_root_id_version", ReliableHierarchyCandidateContract.ROOT_CAPTURE_ID_VERSION)
                .put("payload_bytes", payload.size)
                .put("payload_sha256", record.payloadSha256)
                .put("created_elapsed_realtime_ns", record.createdElapsedNs)
                .put("completed_elapsed_realtime_ns", SystemClock.elapsedRealtimeNanos())
            val envelope = HierarchyPayloadEnvelope.encode(header, payload)
            val stream = atomicFile.startWrite()
            try {
                stream.write(envelope)
                stream.flush()
                beforeAtomicFileFinishWrite(readyFile)
                atomicFile.finishWrite(stream)
            } catch (error: Throwable) {
                atomicFile.failWrite(stream)
                throw error
            }
            val digest = digestFile(atomicFile.openRead())
            val result = synchronized(this) {
                val current = records[handle.requestId]
                if (current === record && same(record, handle) && record.state == "WRITING" &&
                    currentServiceInstanceId == record.serviceInstanceId &&
                    elapsedRealtimeMs() - record.startedAtMs > RETENTION_MS) {
                    record.state = "FAILED"
                    record.errorCode = "WORKER_TIMEOUT"
                    record.retentionStartedAtMs = elapsedRealtimeMs()
                    record.reservedBytes = 0
                    atomicFile.delete()
                    response(record, completed = true)
                } else if (current !== record || !same(record, handle) || record.state != "WRITING" ||
                    currentServiceInstanceId != record.serviceInstanceId) {
                    atomicFile.delete()
                    if (current === record && record.state != "FAILED") {
                        record.state = "CANCELLED"
                        record.errorCode = "REQUEST_CANCELLED_OR_STALE"
                        record.reservedBytes = 0
                    }
                    errorResponse(handle.requestId, handle.clientNonce, "", "REQUEST_CANCELLED_OR_STALE")
                } else {
                    record.file = readyFile
                    record.artifactBytes = readyFile.length().toInt()
                    record.artifactSha256 = digest
                    record.payloadUri = contentUri(record)
                    record.state = "READY"
                    record.reservedBytes = 0
                    response(record, completed = true)
                }
            }
            return result
        } catch (_: Throwable) {
            runCatching { atomicFile.delete() }
            synchronized(this) {
                if (records[handle.requestId] === record && record.state == "WRITING") {
                    record.state = "FAILED"
                    record.errorCode = "WRITE_FAILED"
                    record.reservedBytes = 0
                }
            }
            return synchronized(this) { response(record, completed = true) }
        } finally {
            synchronized(this) { activeWriteFiles.remove(readyFile) }
        }
    }

    @Synchronized
    fun fail(handle: RequestHandle, code: String): JSONObject {
        val record = records[handle.requestId]
            ?: return errorResponse(handle.requestId, handle.clientNonce, "", "REQUEST_NOT_FOUND")
        if (!same(record, handle)) return errorResponse(handle.requestId, handle.clientNonce, "", "REQUEST_IDENTITY_MISMATCH")
        if (record.state !in TERMINAL_STATES) {
            record.state = "FAILED"
            record.errorCode = safeError(code)
            record.reservedBytes = 0
        }
        return response(record, completed = true)
    }

    @Synchronized
    fun status(requestId: String, clientNonce: String, queryNonce: String): JSONObject {
        pruneExpired()
        if (!queryNonce.matches(Regex("[0-9a-f]{32}"))) return errorResponse(requestId, clientNonce, queryNonce, "QUERY_NONCE_INVALID")
        val record = records[requestId]
            ?: return errorResponse(requestId, clientNonce, queryNonce, "REQUEST_NOT_FOUND")
        if (record.handle.clientNonce != clientNonce || record.serviceInstanceId != currentServiceInstanceId) {
            return errorResponse(requestId, clientNonce, queryNonce, "REQUEST_IDENTITY_MISMATCH")
        }
        record.queryNonce = queryNonce
        return response(record, completed = record.state in TERMINAL_STATES)
    }

    fun cancel(requestId: String, clientNonce: String, queryNonce: String,
               expectedProcessEpoch: String = "", expectedGeneration: Long? = null): JSONObject =
        cancelWithLifecycle(requestId, clientNonce, queryNonce, expectedProcessEpoch, expectedGeneration).response

    @Synchronized
    fun cancelWithLifecycle(requestId: String, clientNonce: String, queryNonce: String,
                            expectedProcessEpoch: String = "", expectedGeneration: Long? = null): Cancellation {
        val record = records[requestId]
            ?: return Cancellation(errorResponse(requestId, clientNonce, queryNonce, "REQUEST_NOT_FOUND"), null)
        if (record.handle.clientNonce != clientNonce || !queryNonce.matches(Regex("[0-9a-f]{32}")) ||
            expectedProcessEpoch != processEpoch || expectedGeneration != record.handle.generation ||
            record.serviceInstanceId != currentServiceInstanceId) {
            return Cancellation(errorResponse(requestId, clientNonce, queryNonce, "REQUEST_IDENTITY_MISMATCH"), null)
        }
        val activeHandle = record.handle.takeIf { record.state !in TERMINAL_STATES }
        record.queryNonce = queryNonce
        record.state = "CANCELLED"
        record.errorCode = "HOST_CANCELLED"
        record.reservedBytes = 0
        record.file?.let { AtomicFile(it).delete() }
        record.file = null
        records.remove(requestId)
        if (activeCollector?.let { same(record, it) } == true) activeCollector = null
        return Cancellation(response(record, completed = true), activeHandle)
    }

    @Synchronized
    fun acknowledge(requestId: String, clientNonce: String, queryNonce: String, payloadSha256: String,
                    expectedProcessEpoch: String = "", expectedGeneration: Long? = null): JSONObject {
        val record = records[requestId]
            ?: return errorResponse(requestId, clientNonce, queryNonce, "REQUEST_NOT_FOUND")
        if (record.handle.clientNonce != clientNonce || !queryNonce.matches(Regex("[0-9a-f]{32}")) ||
            expectedProcessEpoch != processEpoch || expectedGeneration != record.handle.generation ||
            record.serviceInstanceId != currentServiceInstanceId ||
            record.state != "READY" || record.payloadSha256 != payloadSha256) {
            return errorResponse(requestId, clientNonce, queryNonce, "ACK_IDENTITY_MISMATCH")
        }
        record.queryNonce = queryNonce
        AtomicFile(record.file ?: return errorResponse(requestId, clientNonce, queryNonce, "READY_FILE_MISSING")).delete()
        records.remove(requestId)
        return JSONObject()
            .put("schema", HierarchyPayloadActions.CONTROL_SCHEMA)
            .put("protocol_version", "hierarchy-payload.v1")
            .put("request_id", requestId)
            .put("client_nonce", record.handle.clientNonce)
            .put("query_nonce", queryNonce)
            .put("process_epoch", processEpoch)
            .put("service_instance_id", record.serviceInstanceId)
            .put("generation", record.handle.generation)
            .put("capture_sequence", record.captureSequence ?: JSONObject.NULL)
            .put("capture_envelope_schema_version", HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA)
            .put("capture_canonicalization_version", HierarchyPayloadActions.CAPTURE_CANONICALIZATION)
            .put("capture_root_id_version", ReliableHierarchyCandidateContract.ROOT_CAPTURE_ID_VERSION)
            .put("helper_build_identity", record.helperIdentity)
            .put("status", "ACKED")
            .put("completed", true)
            .put("payload_complete", true)
    }

    @Synchronized
    fun resolveReadyFile(uri: Uri): File? {
        pruneExpired()
        if (uri.scheme != "content" || uri.authority != PROVIDER_AUTHORITY || uri.query != null || uri.fragment != null) return null
        val segments = uri.pathSegments
        if (segments.size != 5 || segments[0] != "v1" || segments[1] != processEpoch) return null
        val requestId = segments[2]
        val generationValue = segments[3].toLongOrNull() ?: return null
        val token = segments[4]
        val record = records[requestId] ?: return null
        val file = record.file ?: return null
        if (record.state != "READY" || record.handle.generation != generationValue || record.token != token ||
            file.name.endsWith(".tmp") || !file.name.endsWith(".ready")) return null
        val canonicalDirectory = directory.canonicalFile
        val canonicalFile = file.canonicalFile
        if (canonicalFile.parentFile != canonicalDirectory || !canonicalFile.isFile || Files.isSymbolicLink(file.toPath())) return null
        return file
    }

    /** Reap a timed-out operation without pretending the underlying worker stopped. */
    @Synchronized
    fun expireActive(): RequestHandle? {
        val handle = activeCollector ?: return null
        val record = records[handle.requestId] ?: return null
        if (!same(record, handle) || record.state in TERMINAL_STATES ||
            elapsedRealtimeMs() - record.startedAtMs <= RETENTION_MS) return null
        record.state = "FAILED"
        record.errorCode = "WORKER_TIMEOUT"
        record.reservedBytes = 0
        record.retentionStartedAtMs = elapsedRealtimeMs()
        activeCollector = null
        return handle
    }

    @Synchronized
    fun workerFinished(handle: RequestHandle) {
        if (activeCollector == handle) activeCollector = null
    }

    @Synchronized
    fun serviceDisconnected(serviceInstanceId: String) {
        if (currentServiceInstanceId != serviceInstanceId) return
        invalidateAll("SERVICE_INSTANCE_CHANGED")
        currentServiceInstanceId = null
    }

    @Synchronized
    fun close() {
        invalidateAll("PROCESS_EPOCH_CHANGED")
        currentServiceInstanceId = null
    }

    private fun response(record: Record, completed: Boolean): JSONObject = JSONObject()
        .put("schema", HierarchyPayloadActions.CONTROL_SCHEMA)
        .put("protocol_version", "hierarchy-payload.v1")
        .put("request_id", record.handle.requestId)
        .put("client_nonce", record.handle.clientNonce)
        .put("query_nonce", record.queryNonce)
        .put("process_epoch", processEpoch)
        .put("generation", record.handle.generation)
        .put("service_instance_id", record.serviceInstanceId)
        .put("helper_build_identity", record.helperIdentity)
        .put("payload_schema_version", HierarchyPayloadActions.PAYLOAD_SCHEMA)
        .put("candidate_schema_version", ReliableHierarchyCandidateContract.SCHEMA_VERSION)
        .put("candidate_contract_version", ReliableHierarchyCandidateContract.CONTRACT_VERSION)
        .put("capture_sequence", record.captureSequence ?: JSONObject.NULL)
        .put("capture_envelope_schema_version", HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA)
        .put("capture_canonicalization_version", HierarchyPayloadActions.CAPTURE_CANONICALIZATION)
        .put("capture_root_id_version", ReliableHierarchyCandidateContract.ROOT_CAPTURE_ID_VERSION)
        .put("status", record.state)
        .put("completed", completed)
        .put("payload_complete", record.state == "READY")
        .put("payload_uri", record.payloadUri ?: JSONObject.NULL)
        .put("payload_bytes", record.payloadBytes ?: JSONObject.NULL)
        .put("payload_sha256", record.payloadSha256 ?: JSONObject.NULL)
        .put("artifact_bytes", record.artifactBytes ?: JSONObject.NULL)
        .put("artifact_sha256", record.artifactSha256 ?: JSONObject.NULL)
        .put("created_elapsed_realtime_ns", record.createdElapsedNs)
        .put("completed_elapsed_realtime_ns", if (completed) SystemClock.elapsedRealtimeNanos() else JSONObject.NULL)
        .put("error_code", record.errorCode ?: JSONObject.NULL)

    private fun errorResponse(requestId: String, clientNonce: String, queryNonce: String, code: String) = JSONObject()
        .put("schema", HierarchyPayloadActions.CONTROL_SCHEMA)
        .put("protocol_version", "hierarchy-payload.v1")
        .put("request_id", requestId.takeIf { it.isNotBlank() }?.take(64) ?: JSONObject.NULL)
        .put("client_nonce", clientNonce.takeIf { it.isNotBlank() }?.take(64) ?: JSONObject.NULL)
        .put("query_nonce", queryNonce.takeIf { it.isNotBlank() }?.take(64) ?: JSONObject.NULL)
        .put("process_epoch", processEpoch)
        .put("service_instance_id", currentServiceInstanceId ?: JSONObject.NULL)
        .put("generation", JSONObject.NULL)
        .put("helper_build_identity", currentIdentity())
        .put("payload_schema_version", HierarchyPayloadActions.PAYLOAD_SCHEMA)
        .put("candidate_schema_version", ReliableHierarchyCandidateContract.SCHEMA_VERSION)
        .put("candidate_contract_version", ReliableHierarchyCandidateContract.CONTRACT_VERSION)
        .put("capture_envelope_schema_version", HierarchyPayloadActions.CAPTURE_ENVELOPE_SCHEMA)
        .put("capture_canonicalization_version", HierarchyPayloadActions.CAPTURE_CANONICALIZATION)
        .put("status", "FAILED")
        .put("completed", true)
        .put("payload_complete", false)
        .put("error_code", safeError(code))

    private fun currentIdentity() = JSONObject(helperIdentity.toString())

    private fun contentUri(record: Record) = Uri.Builder()
        .scheme("content")
        .authority(PROVIDER_AUTHORITY)
        .appendPath("v1")
        .appendPath(processEpoch)
        .appendPath(record.handle.requestId)
        .appendPath(record.handle.generation.toString())
        .appendPath(record.token)
        .build()
        .toString()

    private fun readyFile(record: Record): File = File(
        directory,
        "hierarchy_${record.handle.requestId}_${record.handle.generation}_${record.token}.ready",
    )

    private fun same(record: Record, handle: RequestHandle) =
        record.handle.requestId == handle.requestId && record.handle.clientNonce == handle.clientNonce &&
            record.handle.generation == handle.generation

    private fun reservedBytes() = records.values.sumOf { it.reservedBytes.toLong() }.coerceAtMost(Int.MAX_VALUE.toLong()).toInt()

    private fun pruneExpired() {
        val now = elapsedRealtimeMs()
        val expired = records.values.filter {
            it.handle != activeCollector && it.state != "WRITING" && now - it.retentionStartedAtMs > RETENTION_MS
        }
        expired.forEach { record ->
            record.file?.let { AtomicFile(it).delete() }
            records.remove(record.handle.requestId)
            if (activeCollector == record.handle) activeCollector = null
        }
        directory.listFiles()?.filter { it.name.startsWith("hierarchy_") &&
            (it.name.endsWith(".new") || it.name.endsWith(".bak") || it.name.endsWith(".ready")) &&
            records.values.none { record -> record.file == it || isActiveWriteFile(record, it) } &&
            activeWriteFiles.none { readyPath -> isActiveWriteArtifact(readyPath, it) } }?.forEach { it.delete() }
    }

    private fun isActiveWriteFile(record: Record, file: File): Boolean {
        if (record.state != "WRITING") return false
        return isActiveWriteArtifact(readyFile(record), file)
    }

    private fun isActiveWriteArtifact(readyFile: File, file: File): Boolean =
        file.name == readyFile.name || file.name == "${readyFile.name}.new" || file.name == "${readyFile.name}.bak"

    private fun invalidateAll(reason: String) {
        records.values.forEach { record -> record.file?.let { AtomicFile(it).delete() } }
        records.clear()
        activeCollector = null
        directory.listFiles()?.filter { it.name.startsWith("hierarchy_") &&
            activeWriteFiles.none { readyPath -> isActiveWriteArtifact(readyPath, it) } }?.forEach { it.delete() }
    }

    private fun digestFile(input: FileInputStream): String = input.use { stream ->
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(16 * 1024)
        while (true) {
            val read = stream.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
        digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    private fun safeError(value: String) = value.takeIf { it.matches(Regex("[A-Z0-9_]{1,64}")) } ?: "TRANSFER_FAILED"

    companion object {
        const val PROVIDER_AUTHORITY = "com.iotpart.sqe.talkbackhelper.hierarchy"
        const val MAX_TOTAL_BYTES = 2 * 1024 * 1024
        const val MAX_RECORDS = 2
        const val RETENTION_MS = 120_000L
        private val TERMINAL_STATES = setOf("READY", "FAILED", "CANCELLED")

        private fun currentBuildIdentity() = JSONObject()
            .put("build_id", BuildIdentity.buildId)
            .put("git_commit", BuildIdentity.gitCommit)
            .put("input_digest", BuildIdentity.inputDigest)
            .put("source_state", BuildIdentity.sourceState)
            .put("build_variant", BuildConfig.HELPER_BUILD_VARIANT)
    }
}

internal object HierarchyPayloadRuntime {
    private val processEpoch = UUID.randomUUID().toString()
    private val transferExecutor = HierarchyTransferExecutorLifecycle()
    @Volatile private var store: HierarchyPayloadStore? = null
    private var activeServiceInstanceId: String? = null

    @Synchronized
    fun serviceConnected(context: Context, serviceInstanceId: String) {
        val transferRoot = File(context.noBackupFilesDir, "hierarchy-transfer")
        if (!transferRoot.exists() && !transferRoot.mkdirs()) throw IOException("TRANSFER_ROOT_CREATE_FAILED")
        cleanupStaleProcessDirectories(transferRoot, processEpoch)
        val directory = File(transferRoot, processEpoch)
        val existingStore = store
        if (existingStore == null) {
            store = HierarchyPayloadStore(directory, processEpoch).also { it.serviceConnected(serviceInstanceId) }
        } else {
            existingStore.serviceConnected(serviceInstanceId)
            transferExecutor.serviceDisconnected()
        }
        activeServiceInstanceId = serviceInstanceId
    }

    internal fun cleanupStaleProcessDirectories(transferRoot: File, activeEpoch: String) {
        val canonicalRoot = transferRoot.canonicalFile
        transferRoot.listFiles()?.forEach { candidate ->
            val epochName = candidate.name
            if (epochName == activeEpoch || !UUID_REGEX.matches(epochName) || !candidate.isDirectory ||
                Files.isSymbolicLink(candidate.toPath()) || candidate.canonicalFile.parentFile != canonicalRoot) return@forEach
            candidate.deleteRecursively()
        }
    }

    @Synchronized
    fun serviceDisconnected(serviceInstanceId: String) {
        if (activeServiceInstanceId != serviceInstanceId) return
        store?.serviceDisconnected(serviceInstanceId)
        transferExecutor.serviceDisconnected()
        activeServiceInstanceId = null
    }

    fun capabilities(queryNonce: String): JSONObject = store?.capabilities(queryNonce)
        ?: errorResponse("", "", queryNonce, "SERVICE_UNAVAILABLE")

    @Synchronized
    fun begin(
        requestId: String,
        clientNonce: String,
        queryNonce: String,
        expectedBuildId: String,
        expectedGitCommit: String,
        expectedServiceInstanceId: String,
        service: A11yHelperService,
    ): JSONObject {
        val activeStore = store ?: return errorResponse(requestId, clientNonce, queryNonce, "SERVICE_UNAVAILABLE")
        reapExpired(activeStore)
        val accepted = activeStore.begin(
            requestId, clientNonce, queryNonce, expectedBuildId, expectedGitCommit, expectedServiceInstanceId,
        )
        if (accepted.optString("status") != "ACCEPTED") return accepted
        val handle = HierarchyPayloadStore.RequestHandle(
            requestId,
            clientNonce,
            accepted.optLong("generation", -1L),
        )
        val submissionFailure = submitHierarchyTransfer(transferExecutor, activeStore, handle) {
                try {
                    if (!activeStore.markCollecting(handle)) return@submitHierarchyTransfer
                    val producerSequence = activeStore.reserveCaptureSequence(handle)
                        ?: throw IllegalStateException("CAPTURE_SEQUENCE_UNAVAILABLE")
                    if (A11yHelperService.instance !== service || A11yHelperService.serviceInstanceId != expectedServiceInstanceId) {
                        activeStore.fail(handle, "SERVICE_INSTANCE_CHANGED")
                        return@submitHierarchyTransfer
                    }
                    val capture = service.dumpReliableHierarchy(requestId, activeStore.processEpoch, handle.generation, expectedServiceInstanceId, producerSequence)
                    val payloadObject = capture.payload
                    if (!payloadObject.optBoolean("success", false)) {
                        activeStore.fail(handle, payloadObject.optString("reason", "HIERARCHY_ACQUISITION_FAILED"))
                        return@submitHierarchyTransfer
                    }
                    if (!ReliableHierarchyCandidateContract.hasValidRootBinding(payloadObject)) {
                        activeStore.fail(handle, "TRAVERSAL_CANDIDATE_ROOT_BINDING_FAILED")
                        return@submitHierarchyTransfer
                    }
                    if (HierarchyPayloadEnvelope.estimatedJsonUtf8Bytes(payloadObject) > HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES) {
                        activeStore.fail(handle, "PAYLOAD_TOO_LARGE")
                        return@submitHierarchyTransfer
                    }
                    val totalSerializationStarted = System.nanoTime()
                    val bytes = payloadObject.toString().toByteArray(StandardCharsets.UTF_8)
                    val totalSerializationElapsedNanos = System.nanoTime() - totalSerializationStarted
                    if (bytes.size > HierarchyPayloadEnvelope.MAX_PAYLOAD_BYTES) {
                        activeStore.fail(handle, "PAYLOAD_TOO_LARGE")
                        return@submitHierarchyTransfer
                    }
                    Log.i(
                        "A11Y_HELPER",
                        "[HIERARCHY_CANDIDATE_METRICS] requestId=$requestId " +
                            "rawHierarchyBytesEstimate=${capture.rawHierarchyBytesEstimate} " +
                            "candidateProjectionBytesEstimate=${capture.candidateProjectionBytesEstimate} " +
                            "totalPayloadBytesEstimate=${capture.totalPayloadBytesEstimate} " +
                            "totalSerializedPayloadBytes=${bytes.size} rawNodeCount=${capture.rawNodeCount} " +
                            "candidateCount=${capture.candidateCount} " +
                            "rawSerializationElapsedMs=${capture.rawSerializationElapsedNanos / 1_000_000.0} " +
                            "candidateGenerationElapsedMs=${capture.candidateGenerationElapsedNanos / 1_000_000.0} " +
                            "candidateSerializationElapsedMs=${capture.candidateSerializationElapsedNanos / 1_000_000.0} " +
                            "totalSerializationElapsedMs=${totalSerializationElapsedNanos / 1_000_000.0}"
                    )
                    activeStore.publish(handle, bytes)
                } catch (error: Throwable) {
                    activeStore.fail(handle, if (error.message == "PAYLOAD_TOO_LARGE") "PAYLOAD_TOO_LARGE" else "COLLECTION_FAILED")
                } finally {
                    activeStore.workerFinished(handle)
                }
            }
        return submissionFailure ?: accepted
    }

    @Synchronized
    fun status(requestId: String, clientNonce: String, queryNonce: String): JSONObject {
        val activeStore = store ?: return errorResponse(requestId, clientNonce, queryNonce, "SERVICE_UNAVAILABLE")
        reapExpired(activeStore)
        return activeStore.status(requestId, clientNonce, queryNonce)
    }

    private fun reapExpired(activeStore: HierarchyPayloadStore) {
        expireHierarchyTransfer(transferExecutor, activeStore)
    }

    @Synchronized
    fun cancel(requestId: String, clientNonce: String, queryNonce: String,
               expectedProcessEpoch: String = "", expectedGeneration: Long? = null): JSONObject {
        val activeStore = store ?: return errorResponse(requestId, clientNonce, queryNonce, "SERVICE_UNAVAILABLE")
        val cancellation = activeStore.cancelWithLifecycle(requestId, clientNonce, queryNonce, expectedProcessEpoch, expectedGeneration)
        cancellation.activeHandle?.let(transferExecutor::cancel)
        return cancellation.response
    }

    fun acknowledge(requestId: String, clientNonce: String, queryNonce: String, payloadSha256: String,
                    expectedProcessEpoch: String = "", expectedGeneration: Long? = null) =
        store?.acknowledge(requestId, clientNonce, queryNonce, payloadSha256, expectedProcessEpoch, expectedGeneration)
            ?: errorResponse(requestId, clientNonce, queryNonce, "SERVICE_UNAVAILABLE")

    fun unavailable(requestId: String, clientNonce: String, queryNonce: String) =
        errorResponse(requestId, clientNonce, queryNonce, "SERVICE_UNAVAILABLE")

    fun resolve(uri: Uri) = store?.resolveReadyFile(uri)

    private fun errorResponse(requestId: String, clientNonce: String, queryNonce: String, code: String) = JSONObject()
        .put("schema", HierarchyPayloadActions.CONTROL_SCHEMA)
        .put("protocol_version", "hierarchy-payload.v1")
        .put("request_id", requestId.takeIf { it.isNotBlank() }?.take(64) ?: JSONObject.NULL)
        .put("client_nonce", clientNonce.takeIf { it.isNotBlank() }?.take(64) ?: JSONObject.NULL)
        .put("query_nonce", queryNonce.takeIf { it.isNotBlank() }?.take(64) ?: JSONObject.NULL)
        .put("process_epoch", processEpoch)
        .put("service_instance_id", activeServiceInstanceId ?: JSONObject.NULL)
        .put("generation", JSONObject.NULL)
        .put("helper_build_identity", JSONObject()
            .put("build_id", BuildIdentity.buildId)
            .put("git_commit", BuildIdentity.gitCommit)
            .put("input_digest", BuildIdentity.inputDigest)
            .put("source_state", BuildIdentity.sourceState)
            .put("build_variant", BuildConfig.HELPER_BUILD_VARIANT))
        .put("payload_schema_version", HierarchyPayloadActions.PAYLOAD_SCHEMA)
        .put("candidate_schema_version", ReliableHierarchyCandidateContract.SCHEMA_VERSION)
        .put("candidate_contract_version", ReliableHierarchyCandidateContract.CONTRACT_VERSION)
        .put("status", "FAILED")
        .put("completed", true)
        .put("payload_complete", false)
        .put("error_code", code)

    private val UUID_REGEX = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
}

/** Provides only an exact, live READY artifact to the shell transport client. */
class HierarchyPayloadProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        if (mode != "r") throw SecurityException("READ_ONLY")
        val uid = Binder.getCallingUid()
        if (uid != Process.myUid() && (uid != SHELL_UID ||
                context?.checkCallingPermission(android.Manifest.permission.DUMP) != PackageManager.PERMISSION_GRANTED)) {
            throw SecurityException("CALLER_NOT_ALLOWED")
        }
        val file = HierarchyPayloadRuntime.resolve(uri)
            ?: throw java.io.FileNotFoundException("READY_HIERARCHY_NOT_FOUND")
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    }

    override fun getType(uri: Uri): String = HierarchyPayloadActions.MIME_TYPE

    override fun query(
        uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?,
    ): Cursor? = throw SecurityException("DIRECTORY_QUERIES_DISABLED")

    override fun insert(uri: Uri, values: ContentValues?): Uri? = throw SecurityException("READ_ONLY")
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = throw SecurityException("READ_ONLY")
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int =
        throw SecurityException("READ_ONLY")

    companion object { private const val SHELL_UID = 2000 }
}

internal object HierarchyControlCodec {
    fun encode(response: JSONObject): String? {
        val bytes = response.toString().toByteArray(StandardCharsets.UTF_8)
        if (bytes.size > MAX_CONTROL_JSON_BYTES) return null
        return HierarchyPayloadActions.CONTROL_PREFIX + Base64.encodeToString(
            bytes,
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING,
        )
    }

    fun decode(encoded: String): JSONObject {
        require(encoded.startsWith(HierarchyPayloadActions.CONTROL_PREFIX)) { "CONTROL_PREFIX_INVALID" }
        val body = encoded.removePrefix(HierarchyPayloadActions.CONTROL_PREFIX)
        require(body.length <= MAX_CONTROL_BASE64_CHARS) { "CONTROL_TOO_LARGE" }
        val bytes = Base64.decode(body, Base64.URL_SAFE or Base64.NO_WRAP)
        require(bytes.size <= MAX_CONTROL_JSON_BYTES) { "CONTROL_TOO_LARGE" }
        return JSONObject(bytes.toString(StandardCharsets.UTF_8))
    }

    const val MAX_CONTROL_JSON_BYTES = 8 * 1024
    private const val MAX_CONTROL_BASE64_CHARS = 12 * 1024
}
