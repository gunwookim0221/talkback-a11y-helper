package com.example.a11yhelper

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class A11yCommandReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "A11Y_HELPER"
        private const val ACTION_GET_FOCUS = "com.example.a11yhelper.GET_FOCUS"
        private const val ACTION_FOCUS_RESULT = "com.example.a11yhelper.FOCUS_RESULT"
        private const val ACTION_NEXT = "com.example.a11yhelper.NEXT"
        private const val ACTION_PREV = "com.example.a11yhelper.PREV"
    }

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        when (action) {
            ACTION_GET_FOCUS -> handleGetFocus(context, intent)
            ACTION_NEXT -> handleNavigate(+1)
            ACTION_PREV -> handleNavigate(-1)
            else -> Unit
        }
    }

    private fun handleGetFocus(context: Context, intent: Intent) {
        A11yStateStore.ensureFallbackJson()
        val saveFile = intent.getBooleanExtra("saveFile", false)
        if (saveFile) {
            A11yStateStore.saveToExternalFile(context)
        }

        val json = A11yStateStore.lastFocusJson
        Log.i(TAG, "FOCUS_RESULT $json")

        val reply = Intent(ACTION_FOCUS_RESULT).apply {
            setPackage(context.packageName)
            putExtra("json", json)
            putExtra("updatedAt", A11yStateStore.lastUpdatedAt)
        }
        context.sendBroadcast(reply)
    }

    private fun handleNavigate(direction: Int) {
        val service = A11yHelperService.instance
        if (service == null) {
            Log.w(TAG, "NAV_RESULT {\"success\":false,\"reason\":\"Service not connected\"}")
            return
        }
        service.handleNavigation(direction)
    }
}
