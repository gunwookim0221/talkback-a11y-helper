package com.iotpart.sqe.talkbackhelper

import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong

/** Fixed-capacity request ledger. It stores frame metadata and digests, never frame bodies. */
internal class HierarchyPublicationLedger(
    private val nowNanos: () -> Long = { SystemClock.elapsedRealtimeNanos() },
    val processEpoch: String = UUID.randomUUID().toString(),
) {
    enum class FrameType(val wireName: String, val code: Int) {
        CHUNK("CHUNK", 1), LEGACY_RESULT("LEGACY_RESULT", 2), FAILURE_RESULT("FAILURE_RESULT", 3), END("END", 4);
        companion object { fun fromCode(code: Int) = entries.firstOrNull { it.code == code } }
    }

    enum class ReturnClass(val wireName: String, val code: Int) {
        POSITIVE("POSITIVE", 1), ZERO("ZERO", 2), NEGATIVE("NEGATIVE", 3), THREW("THREW", 4), OUTCOME_UNKNOWN("OUTCOME_UNKNOWN", 5);
        companion object { fun fromCode(code: Int) = entries.firstOrNull { it.code == code } ?: OUTCOME_UNKNOWN }
    }

    data class Admission(val handle: RequestHandle?, val reason: String?)
    data class RequestHandle internal constructor(val slot: Int, val generation: Long)
    data class FrameHandle internal constructor(val request: RequestHandle, val descriptorIndex: Int)
    data class AttemptHandle internal constructor(val request: RequestHandle, val attemptIndex: Int)
    data class FrameSpec(
        val type: FrameType,
        val sequence: Int,
        val chunkIndex: Int? = null,
        val chunkCount: Int? = null,
        val responsePayloadBytes: Int? = null,
        val chunkPayloadBytes: Int? = null,
        val responseSha256: ByteArray? = null,
        val priority: Int,
        val overload: String,
    )

    private data class Lookup(val slot: Int? = null, val error: JSONObject? = null)
    private val storage = ByteBuffer.allocate(STORAGE_BYTES).order(ByteOrder.BIG_ENDIAN)
    private val publicationSequence = AtomicLong(0L)
    private var nextGeneration = 1L
    private var currentServiceInstanceId: String? = null
    private var lastServiceInstanceId: String? = null

    @Synchronized
    fun serviceConnected(serviceInstanceId: String) {
        if (currentServiceInstanceId != null && currentServiceInstanceId != serviceInstanceId) clearRequests()
        currentServiceInstanceId = serviceInstanceId.take(MAX_SERVICE_ID_BYTES)
        lastServiceInstanceId = currentServiceInstanceId
    }

    @Synchronized
    fun serviceEnded(serviceInstanceId: String) {
        if (currentServiceInstanceId == serviceInstanceId) {
            lastServiceInstanceId = serviceInstanceId
            currentServiceInstanceId = null
            clearRequests()
        }
    }

    @Synchronized
    fun beginRequest(
        requestId: String,
        serviceInstanceId: String?,
        buildId: String,
        gitCommit: String,
        inputDigest: String,
        sourceState: String,
        sdk: Int,
        release: String,
    ): Admission {
        if (requestId.isBlank() || requestId.toByteArray(StandardCharsets.UTF_8).size > MAX_REQUEST_ID_BYTES) {
            return Admission(null, "REQUEST_ID_OUT_OF_BOUNDS")
        }
        val now = nowNanos()
        expireCompleted(now)
        val duplicateSlot = (0 until MAX_REQUESTS).firstOrNull {
            isOccupied(it) && readString(it, H_REQUEST_ID) == requestId &&
                readNullableString(it, H_SERVICE_INSTANCE_ID) == serviceInstanceId
        }
        if (duplicateSlot != null) {
            val duplicateBase = slotBase(duplicateSlot)
            putByte(duplicateBase + H_AMBIGUOUS, 1)
            putByte(duplicateBase + H_EVIDENCE_COMPLETE, 0)
            if (getByte(duplicateBase + H_FINALIZED).toInt() == 1) {
                calculateReportDigest(duplicateSlot).copyInto(storage.array(), duplicateBase + H_REPORT_DIGEST)
            }
            return Admission(null, "AMBIGUOUS_REQUEST_ID")
        }

        var slot = (0 until MAX_REQUESTS).firstOrNull { !isOccupied(it) } ?: -1
        if (slot < 0) {
            slot = (0 until MAX_REQUESTS)
                .filter { getByte(slotBase(it) + H_FINALIZED).toInt() == 1 }
                .minByOrNull { getLong(slotBase(it) + H_CREATED_NS) } ?: -1
        }
        if (slot < 0) return Admission(null, "LEDGER_CAPACITY_UNAVAILABLE")
        clearSlot(slot)
        val generation = nextGeneration++
        val base = slotBase(slot)
        putByte(base + H_OCCUPIED, 1)
        putByte(base + H_EVIDENCE_COMPLETE, 1)
        putLong(base + H_GENERATION, generation)
        putLong(base + H_CREATED_NS, now)
        putInt(base + H_SDK, sdk)
        putInt(base + H_DESCRIPTOR_COUNT, 0)
        putInt(base + H_ATTEMPT_COUNT, 0)
        if (!writeString(slot, H_REQUEST_ID, MAX_REQUEST_ID_BYTES, requestId) ||
            !writeNullableString(slot, H_SERVICE_INSTANCE_ID, MAX_SERVICE_ID_BYTES, serviceInstanceId) ||
            !writeString(slot, H_BUILD_ID, MAX_HEADER_VALUE_BYTES, buildId) ||
            !writeString(slot, H_GIT_COMMIT, MAX_HEADER_VALUE_BYTES, gitCommit) ||
            !writeString(slot, H_INPUT_DIGEST, MAX_HEADER_VALUE_BYTES, inputDigest) ||
            !writeString(slot, H_SOURCE_STATE, MAX_SOURCE_STATE_BYTES, sourceState) ||
            !writeString(slot, H_RELEASE, MAX_RELEASE_BYTES, release) ||
            !writeString(slot, H_PROCESS_EPOCH, MAX_PROCESS_EPOCH_BYTES, processEpoch)
        ) {
            putByte(base + H_LEDGER_FAULT, 1)
            putByte(base + H_EVIDENCE_COMPLETE, 0)
        }
        return Admission(RequestHandle(slot, generation), null)
    }

    @Synchronized
    fun recordConstructed(handle: RequestHandle, spec: FrameSpec, message: String): FrameHandle? {
        val slot = validatedSlot(handle) ?: return null
        val base = slotBase(slot)
        if (getByte(base + H_FINALIZED).toInt() == 1) return fault(slot)
        val count = getInt(base + H_DESCRIPTOR_COUNT)
        if (count >= MAX_RECORDS_PER_REQUEST || spec.sequence != count) {
            putByte(base + H_OVERFLOW, 1)
            putByte(base + H_EVIDENCE_COMPLETE, 0)
            return null
        }
        if (message.length > MAX_FRAME_MESSAGE_CHARS) {
            putByte(base + H_LEDGER_FAULT, 1)
            putByte(base + H_EVIDENCE_COMPLETE, 0)
            return null
        }
        val messageBytes = message.toByteArray(StandardCharsets.UTF_8)
        if (messageBytes.size > MAX_FRAME_MESSAGE_BYTES) {
            putByte(base + H_LEDGER_FAULT, 1)
            putByte(base + H_EVIDENCE_COMPLETE, 0)
            return null
        }
        val row = descriptorBase(slot, count)
        putInt(row + D_SEQUENCE, spec.sequence)
        putByte(row + D_TYPE, spec.type.code)
        putByte(row + D_CONSTRUCTED, 1)
        putInt(row + D_CHUNK_INDEX, spec.chunkIndex ?: NULL_INT)
        putInt(row + D_CHUNK_COUNT, spec.chunkCount ?: NULL_INT)
        putInt(row + D_RESPONSE_BYTES, spec.responsePayloadBytes ?: NULL_INT)
        putInt(row + D_CHUNK_BYTES, spec.chunkPayloadBytes ?: NULL_INT)
        putInt(row + D_MESSAGE_BYTES, messageBytes.size)
        putInt(row + D_PRIORITY, spec.priority)
        putByte(row + D_OVERLOAD, if (spec.priority == 5) OVERLOAD_WARN else OVERLOAD_INFO)
        putLong(row + D_CONSTRUCTED_NS, nowNanos())
        sha256(messageBytes).copyInto(storage.array(), row + D_FRAME_SHA256)
        val responseDigest = spec.responseSha256
        if (responseDigest != null && responseDigest.size == SHA256_BYTES) {
            putByte(row + D_HAS_RESPONSE_SHA256, 1)
            responseDigest.copyInto(storage.array(), row + D_RESPONSE_SHA256)
        }
        putInt(base + H_DESCRIPTOR_COUNT, count + 1)
        return FrameHandle(handle, count)
    }

    @Synchronized
    fun markAttemptStarted(frame: FrameHandle): AttemptHandle? {
        val slot = validatedSlot(frame.request) ?: return null
        val base = slotBase(slot)
        val descriptorCount = getInt(base + H_DESCRIPTOR_COUNT)
        if (frame.descriptorIndex !in 0 until descriptorCount || getByte(base + H_FINALIZED).toInt() == 1) {
            return fault(slot)
        }
        val count = getInt(base + H_ATTEMPT_COUNT)
        if (count >= MAX_RECORDS_PER_REQUEST) {
            putByte(base + H_OVERFLOW, 1)
            putByte(base + H_EVIDENCE_COMPLETE, 0)
            return null
        }
        var ordinal = 1
        for (index in 0 until count) {
            if (getInt(attemptBase(slot, index) + A_DESCRIPTOR_INDEX) == frame.descriptorIndex) ordinal++
        }
        val row = attemptBase(slot, count)
        putInt(row + A_DESCRIPTOR_INDEX, frame.descriptorIndex)
        putInt(row + A_ORDINAL, ordinal)
        putLong(row + A_PUBLICATION_SEQUENCE, publicationSequence.incrementAndGet())
        putLong(row + A_STARTED_NS, nowNanos())
        putLong(row + A_FINISHED_NS, NULL_LONG)
        putInt(row + A_RETURN_VALUE, NULL_INT)
        putByte(row + A_ACCEPTED, NULL_BYTE)
        putByte(row + A_RETURN_CLASS, ReturnClass.OUTCOME_UNKNOWN.code)
        putByte(row + A_EXCEPTION_CODE, EXCEPTION_NONE)
        putByte(row + A_ATTEMPTED, 1)
        putInt(base + H_ATTEMPT_COUNT, count + 1)
        return AttemptHandle(frame.request, count)
    }

    fun emit(frame: FrameHandle?, logger: () -> Int): Int {
        if (frame == null) return logger()
        val attempt = try {
            markAttemptStarted(frame)
        } catch (_: Throwable) {
            markFaultSafely(frame.request)
            null
        }
        if (attempt == null) markFaultSafely(frame.request)
        return try {
            val result = logger()
            if (attempt != null) {
                try { recordReturned(attempt, result) } catch (_: Throwable) { markFaultSafely(frame.request) }
            }
            result
        } catch (error: Throwable) {
            if (attempt != null) {
                try { recordThrew(attempt, error) } catch (_: Throwable) { markFaultSafely(frame.request) }
            }
            throw error
        }
    }

    @Synchronized
    fun recordReturned(handle: AttemptHandle, value: Int) {
        val slot = validatedSlot(handle.request) ?: return
        val base = slotBase(slot)
        val count = getInt(base + H_ATTEMPT_COUNT)
        if (handle.attemptIndex !in 0 until count) return faultUnit(slot)
        val row = attemptBase(slot, handle.attemptIndex)
        if (getByte(row + A_ATTEMPTED).toInt() != 1) return faultUnit(slot)
        putInt(row + A_RETURN_VALUE, value)
        putByte(row + A_ACCEPTED, if (value > 0) 1 else 0)
        putByte(row + A_RETURN_CLASS, when { value > 0 -> ReturnClass.POSITIVE.code; value == 0 -> ReturnClass.ZERO.code; else -> ReturnClass.NEGATIVE.code })
        putLong(row + A_FINISHED_NS, nowNanos())
    }

    @Synchronized
    fun recordThrew(handle: AttemptHandle, error: Throwable) {
        val slot = validatedSlot(handle.request) ?: return
        val base = slotBase(slot)
        val count = getInt(base + H_ATTEMPT_COUNT)
        if (handle.attemptIndex !in 0 until count) return faultUnit(slot)
        val row = attemptBase(slot, handle.attemptIndex)
        putByte(row + A_ACCEPTED, NULL_BYTE)
        putByte(row + A_RETURN_CLASS, ReturnClass.THREW.code)
        putByte(row + A_EXCEPTION_CODE, exceptionCode(error).toInt())
        putLong(row + A_FINISHED_NS, nowNanos())
    }

    @Synchronized
    fun markPlanComplete(handle: RequestHandle) {
        val slot = validatedSlot(handle) ?: return
        putByte(slotBase(slot) + H_PLAN_COMPLETE, 1)
    }

    @Synchronized
    fun finishRequest(handle: RequestHandle) {
        val slot = validatedSlot(handle) ?: return
        val base = slotBase(slot)
        if (getByte(base + H_FINALIZED).toInt() == 1) return
        putLong(base + H_COMPLETED_NS, nowNanos())
        putByte(base + H_FINALIZED, 1)
        val complete = getByte(base + H_PLAN_COMPLETE).toInt() == 1 &&
            getByte(base + H_LEDGER_FAULT).toInt() == 0 && getByte(base + H_OVERFLOW).toInt() == 0
        putByte(base + H_EVIDENCE_COMPLETE, if (complete) 1 else 0)
        calculateReportDigest(slot).copyInto(storage.array(), base + H_REPORT_DIGEST)
    }

    @Synchronized
    fun markFault(handle: RequestHandle?) {
        if (handle == null) return
        val slot = validatedSlot(handle) ?: return
        putByte(slotBase(slot) + H_LEDGER_FAULT, 1)
        putByte(slotBase(slot) + H_EVIDENCE_COMPLETE, 0)
    }

    fun markFaultSafely(handle: RequestHandle) {
        try { markFault(handle) } catch (_: Throwable) { }
    }

    @Synchronized
    fun capabilities(nonce: String): JSONObject {
        if (!validToken(nonce, 64)) return error("QUERY_NONCE_INVALID", "", nonce)
        return JSONObject()
            .put("schema", REPORT_SCHEMA)
            .put("status", "OK")
            .put("query_nonce", nonce)
            .put("process_epoch", processEpoch)
            .put("service_instance_id", currentServiceInstanceId ?: JSONObject.NULL)
            .put("last_service_instance_id", lastServiceInstanceId ?: JSONObject.NULL)
            .put("build_id", BuildIdentity.buildId)
            .put("git_commit", BuildIdentity.gitCommit)
            .put("input_digest", BuildIdentity.inputDigest)
            .put("source_state", BuildIdentity.sourceState)
            .put("sdk", android.os.Build.VERSION.SDK_INT)
            .put("release", android.os.Build.VERSION.RELEASE.orEmpty())
            .put("max_requests", MAX_REQUESTS)
            .put("retention_ms", RETENTION_NANOS / NANOS_PER_MILLI)
            .put("max_descriptors_per_request", MAX_RECORDS_PER_REQUEST)
            .put("max_attempts_per_request", MAX_RECORDS_PER_REQUEST)
            .put("max_records_per_page", MAX_RECORDS_PER_PAGE)
            .put("result_data_limit_bytes", RESULT_DATA_LIMIT_BYTES)
            .put("json_limit_bytes", JSON_LIMIT_BYTES)
            .put("ledger_storage_bytes", STORAGE_BYTES)
    }

    @Synchronized
    fun summary(requestId: String, nonce: String, expectedProcessEpoch: String, expectedServiceInstanceId: String?): JSONObject {
        val lookup = findValidated(requestId, nonce, expectedProcessEpoch, expectedServiceInstanceId)
        val slot = lookup.slot ?: return lookup.error ?: error("NOT_RETAINED_OR_NOT_REGISTERED", requestId, nonce)
        val base = slotBase(slot)
        if (getByte(base + H_FINALIZED).toInt() != 1) return error("IN_PROGRESS", requestId, nonce)
        return summaryJson(slot, nonce)
    }

    @Synchronized
    fun page(
        requestId: String,
        nonce: String,
        expectedProcessEpoch: String,
        expectedServiceInstanceId: String?,
        expectedGeneration: Long,
        expectedRevision: Int,
        expectedReportDigest: String,
        pageKind: String,
        pageIndex: Int,
    ): JSONObject {
        val lookup = findValidated(requestId, nonce, expectedProcessEpoch, expectedServiceInstanceId)
        val slot = lookup.slot ?: return lookup.error ?: error("NOT_RETAINED_OR_NOT_REGISTERED", requestId, nonce)
        val base = slotBase(slot)
        if (getByte(base + H_FINALIZED).toInt() != 1) return error("IN_PROGRESS", requestId, nonce)
        if (getLong(base + H_GENERATION) != expectedGeneration ||
            expectedRevision != REPORT_REVISION || reportDigest(slot) != expectedReportDigest
        ) return error("REPORT_REVISION_MISMATCH", requestId, nonce)
        val isPlan = pageKind == "PLAN"
        if (!isPlan && pageKind != "ATTEMPTS") return error("PAGE_KIND_INVALID", requestId, nonce)
        val count = getInt(base + if (isPlan) H_DESCRIPTOR_COUNT else H_ATTEMPT_COUNT)
        val pages = pageCount(count)
        if (pageIndex !in 0 until pages) return error("PAGE_INDEX_INVALID", requestId, nonce)
        val start = pageIndex * MAX_RECORDS_PER_PAGE
        val end = minOf(count, start + MAX_RECORDS_PER_PAGE)
        val records = JSONArray()
        for (index in start until end) {
            val row = if (isPlan) descriptorJson(slot, index) else attemptJson(slot, index)
            if (row.toString().toByteArray(StandardCharsets.UTF_8).size > MAX_ROW_JSON_BYTES) {
                return error("ROW_SIZE_LIMIT", requestId, nonce)
            }
            records.put(row)
        }
        return JSONObject()
            .put("status", "OK")
            .put("schema", REPORT_SCHEMA)
            .put("request_id", readString(slot, H_REQUEST_ID))
            .put("query_nonce", nonce)
            .put("process_epoch", processEpoch)
            .put("service_instance_id", readNullableString(slot, H_SERVICE_INSTANCE_ID) ?: JSONObject.NULL)
            .put("capture_generation", getLong(base + H_GENERATION))
            .put("report_revision", REPORT_REVISION)
            .put("report_digest", reportDigest(slot))
            .put("page_kind", pageKind)
            .put("page_index", pageIndex)
            .put("page_count", pages)
            .put("records", records)
    }

    @Synchronized
    fun queryError(reason: String, requestId: String, nonce: String): JSONObject = error(reason, requestId, nonce)

    @Synchronized
    fun storageBytesForTest(): Int = storage.capacity()

    private fun findValidated(requestId: String, nonce: String, expectedProcess: String, expectedService: String?): Lookup {
        if (!validToken(nonce, 64)) return Lookup(error = error("QUERY_NONCE_INVALID", requestId, nonce))
        if (expectedProcess != processEpoch || expectedService != currentServiceInstanceId) {
            return Lookup(error = error("PUBLICATION_EVIDENCE_UNAVAILABLE_AFTER_RESTART", requestId, nonce))
        }
        val matches = (0 until MAX_REQUESTS).filter {
            isOccupied(it) && readString(it, H_REQUEST_ID) == requestId &&
                readNullableString(it, H_SERVICE_INSTANCE_ID) == expectedService
        }
        if (matches.size > 1 || (matches.singleOrNull()?.let { getByte(slotBase(it) + H_AMBIGUOUS).toInt() == 1 } == true)) {
            return Lookup(error = error("AMBIGUOUS_REQUEST_ID", requestId, nonce))
        }
        val slot = matches.singleOrNull() ?: return Lookup(error = error("NOT_RETAINED_OR_NOT_REGISTERED", requestId, nonce))
        if (nowNanos() - getLong(slotBase(slot) + H_CREATED_NS) > RETENTION_NANOS) {
            return Lookup(error = error("EXPIRED", requestId, nonce))
        }
        return Lookup(slot)
    }

    private fun summaryJson(slot: Int, nonce: String): JSONObject {
        val base = slotBase(slot)
        val descriptorCount = getInt(base + H_DESCRIPTOR_COUNT)
        val attemptCount = getInt(base + H_ATTEMPT_COUNT)
        val chunks = JSONArray()
        var expectedChunks = 0
        var responseDigest: String? = null
        for (index in 0 until descriptorCount) {
            val row = descriptorBase(slot, index)
            if (getByte(row + D_TYPE).toInt() == FrameType.CHUNK.code) {
                val chunkIndex = getInt(row + D_CHUNK_INDEX)
                if (chunkIndex != NULL_INT) chunks.put(chunkIndex)
                if (expectedChunks == 0) expectedChunks = nullableInt(getInt(row + D_CHUNK_COUNT)) ?: 0
                if (responseDigest == null && getByte(row + D_HAS_RESPONSE_SHA256).toInt() == 1) {
                    responseDigest = hex(storage.array().copyOfRange(row + D_RESPONSE_SHA256, row + D_RESPONSE_SHA256 + SHA256_BYTES))
                }
            }
        }
        val attemptedSequences = JSONArray()
        var positiveCount = 0
        var zeroCount = 0
        var negativeCount = 0
        var thrownCount = 0
        var unknownCount = 0
        val attemptedPlanIndices = BooleanArray(MAX_RECORDS_PER_REQUEST)
        for (index in 0 until attemptCount) {
            val attempt = attemptBase(slot, index)
            val descriptorIndex = getInt(attempt + A_DESCRIPTOR_INDEX)
            if (descriptorIndex in 0 until descriptorCount && !attemptedPlanIndices[descriptorIndex]) {
                attemptedPlanIndices[descriptorIndex] = true
                attemptedSequences.put(getInt(descriptorBase(slot, descriptorIndex) + D_SEQUENCE))
            }
            when (ReturnClass.fromCode(getByte(attempt + A_RETURN_CLASS).toInt())) {
                ReturnClass.POSITIVE -> positiveCount++
                ReturnClass.ZERO -> zeroCount++
                ReturnClass.NEGATIVE -> negativeCount++
                ReturnClass.THREW -> thrownCount++
                ReturnClass.OUTCOME_UNKNOWN -> unknownCount++
            }
        }
        return JSONObject()
            .put("status", "OK")
            .put("schema", REPORT_SCHEMA)
            .put("request_id", readString(slot, H_REQUEST_ID))
            .put("query_nonce", nonce)
            .put("process_epoch", readString(slot, H_PROCESS_EPOCH))
            .put("service_instance_id", readNullableString(slot, H_SERVICE_INSTANCE_ID) ?: JSONObject.NULL)
            .put("capture_generation", getLong(base + H_GENERATION))
            .put("created_elapsed_ns", getLong(base + H_CREATED_NS))
            .put("completed_elapsed_ns", nullableLong(getLong(base + H_COMPLETED_NS)) ?: JSONObject.NULL)
            .put("build_id", readString(slot, H_BUILD_ID))
            .put("git_commit", readString(slot, H_GIT_COMMIT))
            .put("input_digest", readString(slot, H_INPUT_DIGEST))
            .put("source_state", readString(slot, H_SOURCE_STATE))
            .put("sdk", getInt(base + H_SDK))
            .put("release", readString(slot, H_RELEASE))
            .put("tag", "A11Y_HELPER")
            .put("expected_chunk_count", expectedChunks)
            .put("response_sha256", responseDigest ?: JSONObject.NULL)
            .put("descriptor_count", descriptorCount)
            .put("attempt_count", attemptCount)
            .put("api_positive_count", positiveCount)
            .put("api_zero_count", zeroCount)
            .put("api_negative_count", negativeCount)
            .put("api_threw_count", thrownCount)
            .put("api_outcome_unknown_count", unknownCount)
            .put("chunk_indices_constructed", chunks)
            .put("frame_sequences_attempted", attemptedSequences)
            .put("plan_complete", getByte(base + H_PLAN_COMPLETE).toInt() == 1)
            .put("finalized", getByte(base + H_FINALIZED).toInt() == 1)
            .put("evidence_complete", getByte(base + H_EVIDENCE_COMPLETE).toInt() == 1)
            .put("ledger_fault", getByte(base + H_LEDGER_FAULT).toInt() == 1)
            .put("overflow", getByte(base + H_OVERFLOW).toInt() == 1)
            .put("ambiguous_request_id", getByte(base + H_AMBIGUOUS).toInt() == 1)
            .put("sha_frame_applicable", false)
            .put("report_revision", REPORT_REVISION)
            .put("report_digest", reportDigest(slot))
            .put("plan_page_count", pageCount(descriptorCount))
            .put("attempt_page_count", pageCount(attemptCount))
            .put("retention_ms", RETENTION_NANOS / NANOS_PER_MILLI)
    }

    private fun descriptorJson(slot: Int, index: Int): JSONObject {
        val row = descriptorBase(slot, index)
        val sequence = getInt(row + D_SEQUENCE)
        val frameType = FrameType.fromCode(getByte(row + D_TYPE).toInt()) ?: FrameType.FAILURE_RESULT
        return JSONObject()
            .put("s", sequence)
            .put("t", frameType.wireName)
            .put("b", getByte(row + D_CONSTRUCTED).toInt() == 1)
            .put("at", hasAttempt(slot, index))
            .put("i", nullableInt(getInt(row + D_CHUNK_INDEX)) ?: JSONObject.NULL)
            .put("c", nullableInt(getInt(row + D_CHUNK_COUNT)) ?: JSONObject.NULL)
            .put("rb", nullableInt(getInt(row + D_RESPONSE_BYTES)) ?: JSONObject.NULL)
            .put("cb", nullableInt(getInt(row + D_CHUNK_BYTES)) ?: JSONObject.NULL)
            .put("mb", getInt(row + D_MESSAGE_BYTES))
            .put("d", hex(storage.array().copyOfRange(row + D_FRAME_SHA256, row + D_FRAME_SHA256 + SHA256_BYTES)))
            .put("p", getInt(row + D_PRIORITY))
            .put("o", if (getByte(row + D_OVERLOAD).toInt() == OVERLOAD_WARN) "W2" else "I2")
            .put("ct", getLong(row + D_CONSTRUCTED_NS))
    }

    private fun attemptJson(slot: Int, index: Int): JSONObject {
        val row = attemptBase(slot, index)
        val descriptorIndex = getInt(row + A_DESCRIPTOR_INDEX)
        val sequence = if (descriptorIndex in 0 until getInt(slotBase(slot) + H_DESCRIPTOR_COUNT)) {
            getInt(descriptorBase(slot, descriptorIndex) + D_SEQUENCE)
        } else NULL_INT
        val returnValue = getInt(row + A_RETURN_VALUE)
        val accepted = getByte(row + A_ACCEPTED).toInt()
        val exception = getByte(row + A_EXCEPTION_CODE).toInt()
        return JSONObject()
            .put("s", nullableInt(sequence) ?: JSONObject.NULL)
            .put("p", getLong(row + A_PUBLICATION_SEQUENCE))
            .put("a", getInt(row + A_ORDINAL))
            .put("at", getByte(row + A_ATTEMPTED).toInt() == 1)
            .put("st", getLong(row + A_STARTED_NS))
            .put("ft", nullableLong(getLong(row + A_FINISHED_NS)) ?: JSONObject.NULL)
            .put("rv", nullableInt(returnValue) ?: JSONObject.NULL)
            .put("ok", when (accepted) { 1 -> true; 0 -> false; else -> JSONObject.NULL })
            .put("rc", ReturnClass.fromCode(getByte(row + A_RETURN_CLASS).toInt()).wireName)
            .put("ec", exceptionName(exception) ?: JSONObject.NULL)
    }

    private fun hasAttempt(slot: Int, descriptorIndex: Int): Boolean {
        for (index in 0 until getInt(slotBase(slot) + H_ATTEMPT_COUNT)) {
            if (getInt(attemptBase(slot, index) + A_DESCRIPTOR_INDEX) == descriptorIndex) return true
        }
        return false
    }

    private fun calculateReportDigest(slot: Int): ByteArray {
        val base = slotBase(slot)
        val digest = MessageDigest.getInstance("SHA-256")
        val requestLength = getInt(base + H_REQUEST_ID).coerceIn(0, MAX_REQUEST_ID_BYTES)
        digest.update(storage.array(), base + H_REQUEST_ID + STRING_LENGTH_BYTES, requestLength)
        digest.update(ByteBuffer.allocate(8).putLong(getLong(base + H_GENERATION)).array())
        digest.update(ByteBuffer.allocate(4).putInt(getInt(base + H_DESCRIPTOR_COUNT)).array())
        digest.update(ByteBuffer.allocate(4).putInt(getInt(base + H_ATTEMPT_COUNT)).array())
        digest.update(getByte(base + H_EVIDENCE_COMPLETE))
        digest.update(getByte(base + H_LEDGER_FAULT))
        digest.update(getByte(base + H_OVERFLOW))
        digest.update(getByte(base + H_AMBIGUOUS))
        digest.update(readString(slot, H_PROCESS_EPOCH).toByteArray(StandardCharsets.UTF_8))
        digest.update((readNullableString(slot, H_SERVICE_INSTANCE_ID) ?: "").toByteArray(StandardCharsets.UTF_8))
        for (index in 0 until getInt(base + H_DESCRIPTOR_COUNT)) {
            digest.update(storage.array(), descriptorBase(slot, index), PLAN_RECORD_BYTES)
        }
        for (index in 0 until getInt(base + H_ATTEMPT_COUNT)) {
            digest.update(storage.array(), attemptBase(slot, index), ATTEMPT_RECORD_BYTES)
        }
        return digest.digest()
    }

    private fun reportDigest(slot: Int): String {
        val base = slotBase(slot)
        return hex(storage.array().copyOfRange(base + H_REPORT_DIGEST, base + H_REPORT_DIGEST + SHA256_BYTES))
    }

    private fun validatedSlot(handle: RequestHandle): Int? {
        if (handle.slot !in 0 until MAX_REQUESTS || !isOccupied(handle.slot)) return null
        val base = slotBase(handle.slot)
        return handle.slot.takeIf { getLong(base + H_GENERATION) == handle.generation }
    }

    private fun fault(slot: Int): Nothing? {
        putByte(slotBase(slot) + H_LEDGER_FAULT, 1)
        putByte(slotBase(slot) + H_EVIDENCE_COMPLETE, 0)
        return null
    }

    private fun faultUnit(slot: Int) { fault(slot) }

    private fun exceptionCode(error: Throwable): Byte = when (error) {
        is SecurityException -> EXCEPTION_SECURITY.toByte()
        is IllegalArgumentException -> EXCEPTION_ARGUMENT.toByte()
        is IllegalStateException -> EXCEPTION_STATE.toByte()
        is OutOfMemoryError -> EXCEPTION_MEMORY.toByte()
        is InterruptedException -> EXCEPTION_INTERRUPTED.toByte()
        else -> EXCEPTION_OTHER.toByte()
    }

    private fun exceptionName(code: Int): String? = when (code) {
        EXCEPTION_SECURITY -> "SECURITY_EXCEPTION"
        EXCEPTION_ARGUMENT -> "ILLEGAL_ARGUMENT"
        EXCEPTION_STATE -> "ILLEGAL_STATE"
        EXCEPTION_MEMORY -> "OUT_OF_MEMORY"
        EXCEPTION_INTERRUPTED -> "INTERRUPTED"
        EXCEPTION_OTHER -> "OTHER"
        else -> null
    }

    private fun error(reason: String, requestId: String, nonce: String): JSONObject = JSONObject()
        .put("status", reason)
        .put("schema", REPORT_SCHEMA)
        .put("request_id", requestId.take(MAX_REQUEST_ID_BYTES))
        .put("query_nonce", nonce.take(64))
        .put("process_epoch", processEpoch)

    private fun expireCompleted(now: Long) {
        for (slot in 0 until MAX_REQUESTS) {
            val base = slotBase(slot)
            if (isOccupied(slot) && getByte(base + H_FINALIZED).toInt() == 1 &&
                now - getLong(base + H_CREATED_NS) > RETENTION_NANOS
            ) clearSlot(slot)
        }
    }

    private fun clearRequests() { for (slot in 0 until MAX_REQUESTS) clearSlot(slot) }

    private fun clearSlot(slot: Int) {
        val start = slotBase(slot)
        val end = start + REQUEST_SLOT_BYTES
        for (index in start until end) storage.put(index, 0.toByte())
    }

    private fun isOccupied(slot: Int): Boolean = getByte(slotBase(slot) + H_OCCUPIED).toInt() == 1
    private fun slotBase(slot: Int): Int = slot * REQUEST_SLOT_BYTES
    private fun descriptorBase(slot: Int, index: Int): Int =
        slotBase(slot) + HEADER_BYTES + index * PLAN_RECORD_BYTES
    private fun attemptBase(slot: Int, index: Int): Int = slotBase(slot) + HEADER_BYTES +
        MAX_RECORDS_PER_REQUEST * PLAN_RECORD_BYTES + index * ATTEMPT_RECORD_BYTES

    private fun putByte(offset: Int, value: Int) { storage.put(offset, value.toByte()) }
    private fun getByte(offset: Int): Byte = storage.get(offset)
    private fun putInt(offset: Int, value: Int) { storage.putInt(offset, value) }
    private fun getInt(offset: Int): Int = storage.getInt(offset)
    private fun putLong(offset: Int, value: Long) { storage.putLong(offset, value) }
    private fun getLong(offset: Int): Long = storage.getLong(offset)

    private fun writeString(slot: Int, fieldOffset: Int, maxBytes: Int, value: String): Boolean {
        val bytes = value.toByteArray(StandardCharsets.UTF_8)
        if (bytes.size > maxBytes) return false
        val offset = slotBase(slot) + fieldOffset
        putInt(offset, bytes.size)
        bytes.copyInto(storage.array(), offset + STRING_LENGTH_BYTES)
        return true
    }

    private fun writeNullableString(slot: Int, fieldOffset: Int, maxBytes: Int, value: String?): Boolean =
        if (value == null) { putInt(slotBase(slot) + fieldOffset, NULL_INT); true }
        else writeString(slot, fieldOffset, maxBytes, value)

    private fun readString(slot: Int, fieldOffset: Int): String = readStringOrNull(slot, fieldOffset).orEmpty()
    private fun readNullableString(slot: Int, fieldOffset: Int): String? = readStringOrNull(slot, fieldOffset)

    private fun readStringOrNull(slot: Int, fieldOffset: Int): String? {
        val offset = slotBase(slot) + fieldOffset
        val length = getInt(offset)
        if (length == NULL_INT) return null
        val max = stringCapacity(fieldOffset)
        if (length !in 0..max) return null
        return String(storage.array(), offset + STRING_LENGTH_BYTES, length, StandardCharsets.UTF_8)
    }

    private fun stringCapacity(fieldOffset: Int): Int = when (fieldOffset) {
        H_REQUEST_ID -> MAX_REQUEST_ID_BYTES
        H_SERVICE_INSTANCE_ID -> MAX_SERVICE_ID_BYTES
        H_BUILD_ID, H_GIT_COMMIT, H_INPUT_DIGEST -> MAX_HEADER_VALUE_BYTES
        H_SOURCE_STATE -> MAX_SOURCE_STATE_BYTES
        H_RELEASE -> MAX_RELEASE_BYTES
        H_PROCESS_EPOCH -> MAX_PROCESS_EPOCH_BYTES
        else -> 0
    }

    private fun nullableInt(value: Int): Int? = value.takeUnless { it == NULL_INT }
    private fun nullableLong(value: Long): Long? = value.takeUnless { it == NULL_LONG }
    private fun pageCount(count: Int): Int = if (count <= 0) 0 else (count + MAX_RECORDS_PER_PAGE - 1) / MAX_RECORDS_PER_PAGE
    private fun validToken(value: String, maxBytes: Int): Boolean =
        value.isNotBlank() && value.toByteArray(StandardCharsets.UTF_8).size <= maxBytes &&
            value.all { it in 'a'..'z' || it in 'A'..'Z' || it in '0'..'9' || it == '-' || it == '_' }
    private fun sha256(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(bytes)
    private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it.toInt() and 0xff) }

    companion object {
        const val MAX_REQUESTS = 4
        const val MAX_RECORDS_PER_REQUEST = 292
        const val MAX_RECORDS_PER_PAGE = 32
        const val MAX_REQUEST_ID_BYTES = 128
        const val RESULT_DATA_LIMIT_BYTES = 16 * 1024
        const val JSON_LIMIT_BYTES = 11 * 1024
        const val MAX_ROW_JSON_BYTES = 256
        const val REPORT_SCHEMA = "hierarchy-publication-report.v1"
        const val REPORT_REVISION = 1
        const val RESULT_SUCCESS = 0x4850
        const val RESULT_ERROR = 0x4851
        const val RESULT_PREFIX = "HPUB1."
        const val STORAGE_BYTES = 240_640

        private const val MAX_SERVICE_ID_BYTES = 64
        private const val MAX_HEADER_VALUE_BYTES = 128
        private const val MAX_SOURCE_STATE_BYTES = 16
        private const val MAX_RELEASE_BYTES = 32
        private const val MAX_PROCESS_EPOCH_BYTES = 64
        private const val MAX_FRAME_MESSAGE_CHARS = 4096
        private const val MAX_FRAME_MESSAGE_BYTES = 12 * 1024
        private const val SHA256_BYTES = 32
        private const val STRING_LENGTH_BYTES = 4
        private const val HEADER_BYTES = 4096
        private const val PLAN_RECORD_BYTES = 128
        private const val ATTEMPT_RECORD_BYTES = 64
        private const val REQUEST_SLOT_BYTES = HEADER_BYTES + MAX_RECORDS_PER_REQUEST * PLAN_RECORD_BYTES +
            MAX_RECORDS_PER_REQUEST * ATTEMPT_RECORD_BYTES
        private const val NANOS_PER_MILLI = 1_000_000L
        private const val RETENTION_NANOS = 10L * 60L * 1_000_000_000L
        private const val NULL_INT = Int.MIN_VALUE
        private const val NULL_LONG = -1L
        private const val NULL_BYTE = -1
        private const val OVERLOAD_INFO = 1
        private const val OVERLOAD_WARN = 2
        private const val EXCEPTION_NONE = 0
        private const val EXCEPTION_SECURITY = 1
        private const val EXCEPTION_ARGUMENT = 2
        private const val EXCEPTION_STATE = 3
        private const val EXCEPTION_MEMORY = 4
        private const val EXCEPTION_INTERRUPTED = 5
        private const val EXCEPTION_OTHER = 6

        private const val H_OCCUPIED = 0
        private const val H_FINALIZED = 1
        private const val H_EVIDENCE_COMPLETE = 2
        private const val H_LEDGER_FAULT = 3
        private const val H_OVERFLOW = 4
        private const val H_PLAN_COMPLETE = 5
        private const val H_AMBIGUOUS = 6
        private const val H_GENERATION = 8
        private const val H_CREATED_NS = 16
        private const val H_COMPLETED_NS = 24
        private const val H_SDK = 32
        private const val H_DESCRIPTOR_COUNT = 36
        private const val H_ATTEMPT_COUNT = 40
        private const val H_REPORT_DIGEST = 48
        private const val H_REQUEST_ID = 80
        private const val H_SERVICE_INSTANCE_ID = 212
        private const val H_BUILD_ID = 280
        private const val H_GIT_COMMIT = 412
        private const val H_INPUT_DIGEST = 544
        private const val H_SOURCE_STATE = 676
        private const val H_RELEASE = 696
        private const val H_PROCESS_EPOCH = 732

        private const val D_SEQUENCE = 0
        private const val D_TYPE = 4
        private const val D_CONSTRUCTED = 5
        private const val D_HAS_RESPONSE_SHA256 = 6
        private const val D_CHUNK_INDEX = 8
        private const val D_CHUNK_COUNT = 12
        private const val D_RESPONSE_BYTES = 16
        private const val D_CHUNK_BYTES = 20
        private const val D_MESSAGE_BYTES = 24
        private const val D_PRIORITY = 28
        private const val D_OVERLOAD = 32
        private const val D_CONSTRUCTED_NS = 40
        private const val D_FRAME_SHA256 = 48
        private const val D_RESPONSE_SHA256 = 80

        private const val A_DESCRIPTOR_INDEX = 0
        private const val A_ORDINAL = 4
        private const val A_PUBLICATION_SEQUENCE = 8
        private const val A_STARTED_NS = 16
        private const val A_FINISHED_NS = 24
        private const val A_RETURN_VALUE = 32
        private const val A_ACCEPTED = 36
        private const val A_RETURN_CLASS = 37
        private const val A_EXCEPTION_CODE = 38
        private const val A_ATTEMPTED = 39
    }
}

internal object BuildIdentity {
    val buildId: String get() = BuildConfig.HELPER_BUILD_ID
    val gitCommit: String get() = BuildConfig.HELPER_GIT_COMMIT
    val inputDigest: String get() = BuildConfig.HELPER_INPUT_DIGEST
    val sourceState: String get() = BuildConfig.HELPER_SOURCE_STATE
}

internal object HierarchyPublicationReportCodec {
    fun encode(json: JSONObject): String? {
        val bytes = json.toString().toByteArray(StandardCharsets.UTF_8)
        if (bytes.size > HierarchyPublicationLedger.JSON_LIMIT_BYTES) return null
        val body = android.util.Base64.encodeToString(
            bytes,
            android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING,
        )
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {
            "%02x".format(it.toInt() and 0xff)
        }
        val result = HierarchyPublicationLedger.RESULT_PREFIX + body + "." + digest
        return result.takeIf { it.toByteArray(StandardCharsets.UTF_8).size <= HierarchyPublicationLedger.RESULT_DATA_LIMIT_BYTES }
    }
}
