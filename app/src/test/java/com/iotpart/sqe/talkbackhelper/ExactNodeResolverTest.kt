package com.iotpart.sqe.talkbackhelper

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
class ExactNodeResolverTest {
    private fun actionSet(id: Int = 16): JSONArray = JSONArray().put(
        JSONObject().put("id", id).put("name", if (id == 16) "ACTION_CLICK" else "ACTION_ACCESSIBILITY_FOCUS")
            .put("label", JSONObject.NULL)
    )

    private fun node(
        resourceId: String,
        className: String,
        text: Any = "Open",
        bounds: List<Int> = listOf(10, 20, 110, 70),
        children: JSONArray = JSONArray(),
        actions: JSONArray = actionSet(),
        sourceNodeId: Any = JSONObject.NULL,
        clickable: Boolean = true,
        focusable: Boolean = true,
    ) = JSONObject()
        .put("packageName", "com.example.smartthings")
        .put("viewIdResourceName", resourceId)
        .put("className", className)
        .put("text", text)
        .put("contentDescription", JSONObject.NULL)
        .put("sourceNodeId", sourceNodeId)
        .put("boundsInScreen", JSONObject().put("left", bounds[0]).put("top", bounds[1]).put("right", bounds[2]).put("bottom", bounds[3]))
        .put("clickable", clickable)
        .put("focusable", focusable)
        .put("enabled", true)
        .put("visibleToUser", true)
        .put("actions", actions)
        .put("children", children)

    private fun hierarchy(
        snapshotId: String = "C-${UUID.randomUUID()}",
        target: JSONObject = node("com.example.smartthings:id/control", "android.widget.Button"),
        rootClass: String = "android.widget.FrameLayout",
        siblings: JSONArray = JSONArray(),
        windowId: Int = 7,
    ): JSONObject {
        val children = JSONArray().put(target)
        for (index in 0 until siblings.length()) children.put(siblings.getJSONObject(index))
        val root = node("com.example.smartthings:id/root", rootClass, JSONObject.NULL,
            listOf(0, 0, 400, 800), children, JSONArray(), clickable = false, focusable = false)
        return JSONObject().put("success", true).put("snapshotId", snapshotId)
            .put("windows", JSONArray().put(JSONObject().put("order", 0).put("id", windowId).put("type", 1).put("root", root)))
    }

    private fun signature(node: JSONObject, childIndex: Int, includeChildren: Boolean = false): JSONObject {
        val result = JSONObject()
            .put("resource_id", nullable(node.opt("viewIdResourceName")))
            .put("class_name", nullable(node.opt("className")))
            .put("package", nullable(node.opt("packageName")))
            .put("text", nullable(node.opt("text")))
            .put("content_description", nullable(node.opt("contentDescription")))
            .put("clickable", nullable(node.opt("clickable")))
            .put("focusable", nullable(node.opt("focusable")))
            .put("enabled", nullable(node.opt("enabled")))
            .put("visible", nullable(node.opt("visibleToUser")))
            .put("child_index", childIndex)
            .put("actions", normalizeActions(node.optJSONArray("actions") ?: JSONArray()))
        if (includeChildren) result.put("children", childSignature(node))
        return result
    }

    private fun normalizeActions(actions: JSONArray): JSONArray = JSONArray().apply {
        for (i in 0 until actions.length()) {
            val action = actions.getJSONObject(i)
            put(JSONObject().put("id", action.getInt("id")).put("name", nullable(action.opt("name")))
                .put("label", nullable(action.opt("label"))))
        }
    }

    private fun childSignature(node: JSONObject): JSONArray {
        val children = node.optJSONArray("children") ?: JSONArray()
        return JSONArray().apply {
            for (i in 0 until children.length()) put(signature(children.getJSONObject(i), i, includeChildren = true))
        }
    }

    private fun descriptor(target: JSONObject, root: JSONObject, snapshot: String = "B"): JSONObject {
        return JSONObject()
            .put("package", target.optString("packageName"))
            .put("window_id", 7)
            .put("resource_id", target.optString("viewIdResourceName"))
            .put("class_name", target.optString("className"))
            .put("text", nullable(target.opt("text")))
            .put("content_description", nullable(target.opt("contentDescription")))
            .put("bounds", target.optJSONObject("boundsInScreen"))
            .put("source_node_id", nullable(target.opt("sourceNodeId")))
            .put("source_node_id_provenance", if (target.isNull("sourceNodeId")) "ABSENT_IN_SOURCE" else "PRESENT")
            .put("node_local_id", "$snapshot:0:0")
            .put("hierarchy_path", JSONObject().put("window_order", 0).put("child_indices", JSONArray().put(0)))
            .put("parent_identity", signature(root, 0))
            .put("lineage_signature", JSONArray().put(signature(root, 0)))
            .put("child_structure_signature", childSignature(target))
            .put("actions", normalizeActions(target.optJSONArray("actions") ?: JSONArray()))
            .put("semantic_role", JSONObject.NULL)
            .put("snapshot_id", snapshot)
            .put("field_provenance", JSONObject().apply {
                val states = mapOf("package" to "PRESENT", "resource_id" to "PRESENT", "class_name" to "PRESENT",
                    "text" to "PRESENT", "content_description" to "ABSENT_IN_SOURCE", "bounds" to "PRESENT",
                    "actions" to "PRESENT", "source_node_id" to if (target.isNull("sourceNodeId")) "ABSENT_IN_SOURCE" else "PRESENT",
                    "semantic_role" to "NOT_SUPPORTED_BY_SOURCE")
                states.forEach { (field, status) ->
                    put(field, JSONObject().put("status", status).put("source_field", field).put("derivation", "source_value"))
                }
            })
    }

    private fun request(target: JSONObject, hardStop: Boolean = false, command: String = "RESOLVE_EXACT_NODE"): JSONObject {
        val targetHierarchy = hierarchy(snapshotId = "B", target = target)
        val root = targetHierarchy.getJSONArray("windows").getJSONObject(0).getJSONObject("root")
        val identity = descriptor(target, root)
        val nonce = UUID.randomUUID().toString()
        val result = JSONObject()
            .put("protocol_version", ExactNodeResolver.PROTOCOL_VERSION)
            .put("command", command)
            .put("request_id", "request-${UUID.randomUUID()}")
            .put("transaction_id", "transaction-${UUID.randomUUID()}")
            .put("permit_id", "permit-${UUID.randomUUID()}")
            .put("request_nonce", nonce)
            .put("ownership", JSONObject().put("run_id", "run:test").put("scenario_id", "scenario:test")
                .put("scenario_transaction_id", "scenario-tx:test").put("step_action_id", "step:test").put("parent_action_id", JSONObject.NULL))
            .put("action_type", ExactNodeResolver.ACTION_TYPE)
            .put("expected_package", "com.example.smartthings")
            .put("expected_window", JSONObject().put("id", 7).put("type", 1))
            .put("authorized_snapshot_id", "A")
            .put("reacquire_snapshot_id", "B")
            .put("target_identity_schema", "talkback.exact-node-descriptor.v1")
            .put("target_identity", identity)
            .put("target_action_set", identity.getJSONArray("actions"))
            .put("target_lineage_signature", identity.getJSONArray("lineage_signature"))
            .put("target_child_structure_signature", identity.getJSONArray("child_structure_signature"))
            .put("created_at", Instant.now().minusSeconds(1).toString())
            .put("expires_at", Instant.now().plusSeconds(30).toString())
            .put("permit_created_at", Instant.now().minusSeconds(1).toString())
            .put("permit_expires_at", Instant.now().plusSeconds(31).toString())
            .put("hard_stop_active", hardStop)
            .put("source_request_id", "capture:B")
            .put("helper_service_instance_id", "helper:epoch:test")
            .put("host_session_id", "host:session:test")
            .put("stop_epoch", "stop:0")
            .put("evidence_refs", JSONArray())
        result.put("request_digest", digest(result))
        return result
    }

    private fun digest(request: JSONObject): String {
        val without = JSONObject()
        request.keys().asSequence().filter { it != "request_digest" }.forEach { without.put(it, request.opt(it)) }
        return MessageDigest.getInstance("SHA-256").digest(canonical(without).toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }

    private fun canonical(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"
        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(prefix = "{", postfix = "}") { key ->
            JSONObject.quote(key) + ":" + canonical(value.opt(key))
        }
        is JSONArray -> (0 until value.length()).joinToString(prefix = "[", postfix = "]") { canonical(value.opt(it)) }
        is String -> JSONObject.quote(value)
        is Number, is Boolean -> value.toString()
        else -> JSONObject.quote(value.toString())
    }

    private fun nullable(value: Any?): Any = if (value == null || value === JSONObject.NULL) JSONObject.NULL else value

    private fun resolve(req: JSONObject, fresh: JSONObject = hierarchy()) =
        ExactNodeResolver.resolve(req.toString(), fresh)

    @Test
    fun exactUniqueTargetResolvesWithNoActionReceipt() {
        val target = node("com.example.smartthings:id/control", "android.widget.Button")
        val req = request(target)
        val ack = resolve(req, hierarchy(target = target))
        assertTrue(ack.getBoolean("resolved"))
        assertEquals(1, ack.getInt("candidate_count"))
        assertFalse(ack.getBoolean("perform_action_called"))
        assertEquals(0, ack.getInt("perform_action_call_count"))
        assertTrue(ack.isNull("perform_action_return"))
        assertFalse(ack.getBoolean("visit_authority"))
        assertNotNull(ack.getString("helper_validation_snapshot_id"))
        val freshIdentity = ack.getJSONObject("resolved_target_identity")
        assertEquals(ack.getString("helper_validation_snapshot_id"), freshIdentity.getString("snapshot_id"))
        assertEquals("PRESENT", freshIdentity.getJSONObject("field_provenance").getJSONObject("bounds").getString("status"))
        assertEquals(100, freshIdentity.getJSONObject("bounds").getInt("right") - freshIdentity.getJSONObject("bounds").getInt("left"))
        assertEquals(canonical(ack.get("resolved_lineage_summary")), canonical(freshIdentity.get("lineage_signature")))
        assertEquals(canonical(ack.get("resolved_child_structure_summary")), canonical(freshIdentity.get("child_structure_signature")))
    }

    @Test
    fun boundsMayMoveWhenStrongIdentityAndStructureRemainStable() {
        val target = node("com.example.smartthings:id/control", "android.widget.Button")
        val req = request(target)
        val moved = node("com.example.smartthings:id/control", "android.widget.Button", bounds = listOf(80, 100, 180, 150))
        val ack = resolve(req, hierarchy(target = moved))
        assertTrue(ack.getBoolean("resolved"))
        assertEquals(moved.getJSONObject("boundsInScreen").toString(), ack.getJSONObject("resolved_target_identity").getJSONObject("bounds").toString())
    }

    @Test
    fun duplicateResourceIdFailsClosedWithoutLineageWinner() {
        val target = node("com.example.smartthings:id/control", "android.widget.Button")
        val req = request(target)
        val duplicate = node("com.example.smartthings:id/control", "android.widget.Button")
        val ack = resolve(req, hierarchy(target = target, siblings = JSONArray().put(duplicate)))
        assertFalse(ack.getBoolean("resolved"))
        assertEquals("TARGET_MULTI_MATCH", ack.getString("failure_code"))
        assertEquals(2, ack.getInt("candidate_count"))
    }

    @Test
    fun lineageChildAndActionSetMismatchReject() {
        val target = node("com.example.smartthings:id/control", "android.widget.Button")
        assertEquals("TARGET_LINEAGE_MISMATCH", resolve(request(target), hierarchy(target = target, rootClass = "android.widget.LinearLayout")).getString("failure_code"))
        val changedChild = node("com.example.smartthings:id/control", "android.widget.Button", children = JSONArray().put(
            node("com.example.smartthings:id/new_child", "android.widget.ImageButton")
        ))
        assertEquals("TARGET_CHILD_STRUCTURE_CHANGED", resolve(request(target), hierarchy(target = changedChild)).getString("failure_code"))
        val changedAction = node("com.example.smartthings:id/control", "android.widget.Button", actions = actionSet(64))
        assertEquals("ACTION_SET_CHANGED", resolve(request(target), hierarchy(target = changedAction)).getString("failure_code"))
    }

    @Test
    fun zeroMatchPackageWindowAndStaleCaptureReject() {
        val target = node("com.example.smartthings:id/control", "android.widget.Button")
        assertEquals("TARGET_NOT_FOUND", resolve(request(target), hierarchy(target = node("other:id/no", "android.widget.Button"))).getString("failure_code"))
        assertEquals("WINDOW_MISMATCH", resolve(request(target), hierarchy(target = target, windowId = 8)).getString("failure_code"))
        assertEquals("SNAPSHOT_STALE", resolve(request(target), hierarchy(snapshotId = "B", target = target)).getString("failure_code"))
        val wrongPackage = hierarchy(target = target)
        wrongPackage.getJSONArray("windows").getJSONObject(0).getJSONObject("root").getJSONArray("children")
            .getJSONObject(0).put("packageName", "other.app")
        assertEquals("PACKAGE_MISMATCH", resolve(request(target), wrongPackage).getString("failure_code"))
    }

    @Test
    fun hardStopUnsupportedCommandAndReplayReject() {
        val target = node("com.example.smartthings:id/control", "android.widget.Button")
        assertEquals("HARD_STOP_ACTIVE", resolve(request(target, hardStop = true), hierarchy(target = target)).getString("failure_code"))
        assertEquals("ACTION_EXECUTION_DISABLED", resolve(request(target, command = "CLICK_TARGET"), hierarchy(target = target)).getString("failure_code"))
        val req = request(target)
        val duplicateJson = req.toString().dropLast(1) + ",\"request_id\":\"shadow-request\"}"
        assertEquals("REQUEST_INVALID", ExactNodeResolver.resolve(duplicateJson, hierarchy(target = target)).getString("failure_code"))
        assertTrue(resolve(req, hierarchy(target = target)).getBoolean("resolved"))
        assertEquals("REQUEST_REPLAYED", resolve(req, hierarchy(target = target)).getString("failure_code"))
        val transactionReuse = request(target).put("transaction_id", req.getString("transaction_id"))
        transactionReuse.put("request_digest", digest(transactionReuse))
        assertEquals("TRANSACTION_MISMATCH", resolve(transactionReuse, hierarchy(target = target)).getString("failure_code"))
    }

    @Test
    fun sourceNodeIdIsOptionalButChangedPresentValueIsNotAccepted() {
        val requestTarget = node("com.example.smartthings:id/control", "android.widget.Button", sourceNodeId = JSONObject.NULL)
        val req = request(requestTarget)
        val freshTarget = node("com.example.smartthings:id/control", "android.widget.Button", sourceNodeId = "uid-C")
        assertTrue(resolve(req, hierarchy(target = freshTarget)).getBoolean("resolved"))

        val presentTarget = node("com.example.smartthings:id/control", "android.widget.Button", sourceNodeId = "uid-B")
        val presentReq = request(presentTarget)
        val changedTarget = node("com.example.smartthings:id/control", "android.widget.Button", sourceNodeId = "uid-C")
        assertEquals("SOURCE_NODE_ID_MISMATCH", resolve(presentReq, hierarchy(target = changedTarget)).getString("failure_code"))
    }

    @Test
    fun helperServiceRestartInvalidatesARequestBoundToThePriorInstance() {
        val target = node("com.example.smartthings:id/control", "android.widget.Button")
        val req = request(target)
        val ack = ExactNodeResolver.resolve(
            req.toString(),
            hierarchy(target = target),
            helperServiceInstanceId = "helper:epoch:restarted",
        )
        assertFalse(ack.getBoolean("resolved"))
        assertEquals("HELPER_SERVICE_INSTANCE_MISMATCH", ack.getString("failure_code"))
        assertEquals("helper:epoch:restarted", ack.getString("helper_service_instance_id"))
    }

    @Test
    fun requestDigestExpiryAndStaticDispatchGuard() {
        val target = node("com.example.smartthings:id/control", "android.widget.Button")
        val malformed = request(target).put("free_form_selector", "first")
        malformed.put("request_digest", digest(malformed))
        assertEquals("REQUEST_INVALID", resolve(malformed, hierarchy(target = target)).getString("failure_code"))
        var root = File(".").canonicalFile
        while (!File(root, "app/src/main/java/com/iotpart/sqe/talkbackhelper/ExactNodeResolver.kt").exists() && root.parentFile != null) {
            root = root.parentFile!!
        }
        val resolverSource = File(root, "app/src/main/java/com/iotpart/sqe/talkbackhelper/ExactNodeResolver.kt").readText()
        val receiverSource = File(root, "app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yCommandReceiver.kt").readText()
        val manifestSource = File(root, "app/src/main/AndroidManifest.xml").readText()
        assertFalse(resolverSource.contains(".performAction("))
        assertFalse(resolverSource.contains("A11yTargetFinder"))
        val handlerStart = receiverSource.indexOf("private fun handleResolveExactNode")
        assertTrue(handlerStart >= 0)
        val handlerEnd = receiverSource.indexOf("\n    private fun ", handlerStart + 10).let { if (it < 0) receiverSource.length else it }
        val handler = receiverSource.substring(handlerStart, handlerEnd)
        assertFalse(handler.contains(".performAction("))
        assertFalse(handler.contains("A11yTargetFinder"))
        assertTrue(manifestSource.contains("com.iotpart.sqe.talkbackhelper.RESOLVE_EXACT_NODE"))
    }
}
