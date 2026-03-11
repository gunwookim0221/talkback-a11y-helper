package com.example.a11yhelper

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo

class A11yCommandReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "A11Y_HELPER"
        private const val ACTION_GET_FOCUS = "com.example.a11yhelper.GET_FOCUS"
        private const val ACTION_FOCUS_RESULT = "com.example.a11yhelper.FOCUS_RESULT"
        private const val ACTION_DUMP_TREE = "com.example.a11yhelper.DUMP_TREE"
        private const val ACTION_FOCUS_TARGET = "com.example.a11yhelper.FOCUS_TARGET"
        private const val ACTION_CLICK_TARGET = "com.example.a11yhelper.CLICK_TARGET"
        private const val EXTRA_TARGET_TEXT = "targetText"
        private const val EXTRA_TARGET_VIEW_ID = "targetViewId"
        private const val EXTRA_TARGET_CLASS_NAME = "targetClassName"
    }

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        when (action) {
            ACTION_GET_FOCUS -> handleGetFocus(context, intent)
            ACTION_DUMP_TREE -> handleDumpTree()
            ACTION_FOCUS_TARGET -> handleTargetAction(intent, AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS)
            ACTION_CLICK_TARGET -> handleTargetAction(intent, AccessibilityNodeInfo.ACTION_CLICK)
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

    private fun handleDumpTree() {
        val service = A11yHelperService.instance
        if (service == null) {
            Log.w(TAG, "DUMP_TREE_RESULT [] // Service not connected")
            return
        }
        service.dumpTree()
    }

    private fun handleTargetAction(intent: Intent, action: Int) {
        val service = A11yHelperService.instance
        if (service == null) {
            Log.w(TAG, "TARGET_ACTION_RESULT {\"success\":false,\"reason\":\"Service not connected\"}")
            return
        }

        val query = A11yNavigator.TargetQuery(
            targetText = intent.getStringExtra(EXTRA_TARGET_TEXT),
            targetViewId = intent.getStringExtra(EXTRA_TARGET_VIEW_ID),
            targetClassName = intent.getStringExtra(EXTRA_TARGET_CLASS_NAME)
        )

        if (query.targetText.isNullOrBlank() &&
            query.targetViewId.isNullOrBlank() &&
            query.targetClassName.isNullOrBlank()
        ) {
            Log.w(
                TAG,
                "TARGET_ACTION_RESULT {\"success\":false,\"reason\":\"At least one of targetText, targetViewId, targetClassName is required\"}"
            )
            return
        }

        service.performTargetAction(query, action)
    }
}
