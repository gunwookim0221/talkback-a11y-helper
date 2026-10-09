package com.iotpart.sqe.talkbackhelper

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Base64

/** Keeps helper result log records below Android logcat's per-line limit. */
internal object A11yResultTransport {
    private const val LEGACY_LINE_MAX_BYTES = 2700
    private const val CHUNK_BYTES = 1500
    // Hierarchy snapshots are comparatively large; fewer bounded writes reduce
    // logcat loss risk while keeping each encoded record below Android's limit.
    const val HIERARCHY_CHUNK_BYTES = 2600

    fun encode(
        prefix: String,
        reqId: String,
        serialized: String,
        chunkBytes: Int = CHUNK_BYTES,
    ): List<String> {
        val bytes = serialized.toByteArray(StandardCharsets.UTF_8)
        if (bytes.size <= LEGACY_LINE_MAX_BYTES) return listOf("$prefix $serialized")

        val digest = sha256(bytes)
        require(chunkBytes in 1..HIERARCHY_CHUNK_BYTES) { "Invalid result chunk size: $chunkBytes" }
        val chunks = bytes.asList().chunked(chunkBytes).map { part ->
            ByteArray(part.size) { index -> part[index] }
        }
        val count = chunks.size
        return chunks.mapIndexed { index, chunk ->
            val payload = Base64.getEncoder().encodeToString(chunk)
            "${prefix}_CHUNK reqId=$reqId index=$index count=$count sha256=$digest payload=$payload"
        }
    }

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes)
        .joinToString(separator = "") { byte -> "%02x".format(byte.toInt() and 0xff) }
}
