package com.iotpart.sqe.talkbackhelper

import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/** exact-canonical.v1. Deliberately independent of Python and JSONObject.toString(). */
internal object ExactProtocolJson {
    fun canonical(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"
        is Boolean -> if (value) "true" else "false"
        is Byte, is Short, is Int, is Long -> value.toString()
        is String -> quote(value)
        is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { canonical(value.get(it)) }
        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") {
            quote(it) + ":" + canonical(value.get(it))
        }
        else -> error("CANONICAL_TYPE_UNSUPPORTED")
    }

    private fun quote(value: String): String = buildString {
        append('"')
        value.forEachIndexed { index, c ->
            require(!Character.isHighSurrogate(c) || (index + 1 < value.length && Character.isLowSurrogate(value[index + 1])))
            require(!Character.isLowSurrogate(c) || (index > 0 && Character.isHighSurrogate(value[index - 1])))
            append(when (c) {
                '"' -> "\\\""; '\\' -> "\\\\"; '\b' -> "\\b"; '\u000c' -> "\\f"
                '\n' -> "\\n"; '\r' -> "\\r"; '\t' -> "\\t"
                else -> if (c.code < 32 || c.code > 126) "\\u" + c.code.toString(16).padStart(4, '0') else c.toString()
            })
        }
        append('"')
    }

    fun hash(value: Any?): String = sha256(canonical(value))
    fun sha256(text: String): String = MessageDigest.getInstance("SHA-256")
        .digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}
