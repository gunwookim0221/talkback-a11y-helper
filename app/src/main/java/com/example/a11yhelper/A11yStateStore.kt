package com.example.a11yhelper

import android.content.Context
import android.os.Environment
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
            val base = Environment.getExternalStorageDirectory()
            val target = File(base, "a11y_focus.json")
            target.writeText(lastFocusJson)
            target.absolutePath
        }.onFailure {
            Log.w(TAG, "Failed to save /sdcard/a11y_focus.json", it)
        }
    }
}
