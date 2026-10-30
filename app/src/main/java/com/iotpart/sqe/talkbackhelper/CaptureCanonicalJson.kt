package com.iotpart.sqe.talkbackhelper

import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/** Cross-language byte contract for Phase6D root and candidate digests. */
internal object CaptureCanonicalJson {
    const val VERSION = "capture-canonical-json-v1"
    fun canonical(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"
        is Boolean -> if (value) "true" else "false"
        is Byte, is Short, is Int, is Long -> value.toString()
        is String -> quote(value)
        is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { canonical(value.get(it)) }
        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") { quote(it) + ":" + canonical(value.get(it)) }
        else -> error("CAPTURE_CANONICAL_TYPE_UNSUPPORTED")
    }
    private fun quote(value: String): String = buildString {
        append('"')
        value.forEachIndexed { index, char ->
            require(!Character.isHighSurrogate(char) || (index + 1 < value.length && Character.isLowSurrogate(value[index + 1]))) { "CAPTURE_CANONICAL_UNPAIRED_SURROGATE" }
            require(!Character.isLowSurrogate(char) || (index > 0 && Character.isHighSurrogate(value[index - 1]))) { "CAPTURE_CANONICAL_UNPAIRED_SURROGATE" }
            append(when (char) {
                '"' -> "\\\""; '\\' -> "\\\\"; '\b' -> "\\b"; '\u000c' -> "\\f"
                '\n' -> "\\n"; '\r' -> "\\r"; '\t' -> "\\t"
                else -> if (char.code < 0x20 || char.code > 0x7e) "\\u" + char.code.toString(16).padStart(4, '0') else char.toString()
            })
        }
        append('"')
    }
    fun sha256(value: Any?): String = MessageDigest.getInstance("SHA-256")
        .digest(canonical(value).toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}