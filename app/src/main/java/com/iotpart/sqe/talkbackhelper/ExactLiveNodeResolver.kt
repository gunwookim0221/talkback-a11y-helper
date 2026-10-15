package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.os.Build
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

internal data class ExactApplicationWindow(val id:Int,val type:Int,val active:Boolean,val root:AccessibilityNodeInfo?)

/** Keeps the exact reference that supplied the validated descriptor. No legacy target finder. */
internal class ExactLiveNodeResolver(private val windows:()->List<ExactApplicationWindow>) {
    inner class Target internal constructor(val node:AccessibilityNodeInfo,val ack:JSONObject,
        val independentDescendants:Int,val independentSiblings:Int,
        private val request:JSONObject,private val connection:String,private val capturedAt:Long) {
        fun revalidate():JSONObject {
            ExactActionContract.requireThat(SystemClock.elapsedRealtime()-capturedAt in 0..1000,"SNAPSHOT_STALE")
            ExactActionContract.requireThat(node.refresh(),"TARGET_STALE")
            val fresh=capture(request,connection)
            ExactActionContract.requireThat(node.windowId==request.getJSONObject("expected_window").getInt("id") &&
                node.packageName?.toString()==request.getString("expected_package"),"WINDOW_MISMATCH")
            ExactActionContract.requireThat(node.isEnabled,"TARGET_DISABLED")
            ExactActionContract.requireThat(node.isVisibleToUser,"TARGET_NOT_VISIBLE")
            ExactActionContract.requireThat(node.actionList.any{it.id==16},"ACTION_NOT_AVAILABLE")
            ExactActionContract.requireThat(fresh.independentDescendants==0 && fresh.independentSiblings==0,"ISOLATION_UNPROVEN")
            // Compare the retained reference itself, not merely a newly looked-up replacement.
            ExactActionContract.requireThat(ExactProtocolJson.canonical(serialize(node,0,intArrayOf(0),null,"",null)) ==
                ExactProtocolJson.canonical(serialize(fresh.node,0,intArrayOf(0),null,"",null)),"TARGET_IDENTITY_MISMATCH")
            return fresh.ack
        }
        fun click():Boolean = node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    fun capture(request:JSONObject,connection:String):Target {
        val captureStarted=SystemClock.elapsedRealtime()
        val expected=request.getJSONObject("expected_window")
        ExactActionContract.requireThat(expected.opt("type")==1,"WINDOW_MISMATCH")
        val matching=windows().filter { it.id==expected.getInt("id") && it.type==1 && it.active }
        ExactActionContract.requireThat(matching.size==1,"WINDOW_MISMATCH")
        val window=matching.single();val root=window.root ?: throw ExactActionRejected("HELPER_REACQUIRE_FAILED")
        val handles=mutableMapOf<String,AccessibilityNodeInfo>();val rawNodes=mutableMapOf<String,JSONObject>()
        val hierarchy=JSONObject().put("snapshotId",UUID.randomUUID().toString()).put("success",true)
            .put("windows",JSONArray().put(JSONObject().put("id",window.id).put("type",window.type)
                .put("root",serialize(root,0,intArrayOf(0),handles,"",rawNodes))))
        val ack=ExactNodeResolver.resolveForAction(request.toString(),hierarchy,connection)
        ExactActionContract.requireThat(ack.optBoolean("resolved"),ack.optString("failure_code","TARGET_NOT_FOUND"))
        val indices=ack.getJSONObject("resolved_target_identity").getJSONObject("hierarchy_path").getJSONArray("child_indices")
        val key=(0 until indices.length()).joinToString("."){indices.getInt(it).toString()}
        val node=handles[key] ?: throw ExactActionRejected("TARGET_NOT_FOUND")
        ExactActionContract.requireThat(node.windowId==window.id,"WINDOW_MISMATCH")
        val raw=rawNodes.getValue(key)
        val descendantCount=children(raw).sumOf(::actionableCount)
        val parent=if(key.contains('.'))key.substringBeforeLast('.') else ""
        val siblings=if(key.isBlank())0 else children(rawNodes.getValue(parent)).filter { it !== raw }.sumOf(::actionableCount)
        ExactActionContract.requireThat(SystemClock.elapsedRealtime()-captureStarted in 0..1000,"SNAPSHOT_STALE")
        return Target(node,ack,descendantCount,siblings,request,connection,captureStarted)
    }

    private fun children(node:JSONObject):List<JSONObject> = node.getJSONArray("children").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
    private fun actionableCount(node:JSONObject):Int {
        val actions=node.getJSONArray("actions")
        val self=node.optBoolean("clickable") || (0 until actions.length()).any { actions.getJSONObject(it).getInt("id")==16 }
        return (if(self)1 else 0)+children(node).sumOf(::actionableCount)
    }

    private fun serialize(node:AccessibilityNodeInfo,depth:Int,count:IntArray,handles:MutableMap<String,AccessibilityNodeInfo>?,
        path:String,rawNodes:MutableMap<String,JSONObject>?):JSONObject {
        ExactActionContract.requireThat(depth<=80 && ++count[0]<=5000,"METADATA_INCOMPLETE")
        val bounds=Rect().also(node::getBoundsInScreen)
        val result=JSONObject().put("packageName",node.packageName?.toString() ?: JSONObject.NULL)
            .put("viewIdResourceName",node.viewIdResourceName ?: JSONObject.NULL).put("className",node.className?.toString() ?: JSONObject.NULL)
            .put("text",node.text?.toString() ?: JSONObject.NULL).put("contentDescription",node.contentDescription?.toString() ?: JSONObject.NULL)
            .put("boundsInScreen",A11yNavigator.rectToJson(bounds)).put("clickable",node.isClickable)
            .put("focusable",node.isFocusable).put("enabled",node.isEnabled).put("visibleToUser",node.isVisibleToUser)
            .put("actions",JSONArray().apply { node.actionList.forEach {
                put(JSONObject().put("id",it.id).put("name",A11yNavigator.hierarchyActionName(it.id)).put("label",it.label?.toString() ?: JSONObject.NULL))
            } })
        handles?.put(path,node);rawNodes?.put(path,result)
        if(Build.VERSION.SDK_INT>=33)result.put("sourceNodeId",node.uniqueId ?: JSONObject.NULL)
        result.put("children",JSONArray().apply {
            for(i in 0 until node.childCount) {
                val child=node.getChild(i) ?: throw ExactActionRejected("METADATA_INCOMPLETE")
                put(serialize(child,depth+1,count,handles,if(path.isBlank())"$i" else "$path.$i",rawNodes))
            }
        })
        return result
    }
}
