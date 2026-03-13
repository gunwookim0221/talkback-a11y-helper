package com.iotpart.sqe.talkbackhelper

import android.content.Context
import android.util.Log
import org.json.JSONObject
import java.io.File

object A11yStateStore {
    private const val TAG = "A11Y_HELPER"

    @Volatile
    var lastFocusJson: String = "{}"
        private set

    @Volatile
    var lastUpdatedAt: Long = 0L
        private set

    fun update(snapshot: FocusSnapshot) {
        lastFocusJson = snapshot.toJson().toString()
        lastUpdatedAt = snapshot.timestamp
        Log.i(TAG, "FOCUS_UPDATE $lastFocusJson")
    }

    fun ensureFallbackJson() {
        if (lastFocusJson == "{}") {
            val json = JSONObject().apply {
                put("timestamp", System.currentTimeMillis())
                put("note", "No focus event captured yet")
            }.toString()
            lastFocusJson = json
        }
    }

    fun saveToExternalFile(context: Context): Result<String> {
        return runCatching {
            val base = context.getExternalFilesDir(null)
                ?: throw IllegalStateException("External files directory is not available")
            val target = File(base, "a11y_focus.json")
            target.writeText(lastFocusJson)
            target.absolutePath
        }.onFailure {
            Log.w(TAG, "Failed to save a11y_focus.json in app external files directory", it)
        }
    }
}
