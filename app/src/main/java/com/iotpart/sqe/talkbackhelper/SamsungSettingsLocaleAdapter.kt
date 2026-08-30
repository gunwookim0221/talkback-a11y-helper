package com.iotpart.sqe.talkbackhelper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

/**
 * A deliberately isolated adapter for the Samsung One UI LocalePicker.
 *
 * This adapter is an environment-provisioning seam.  It does not share or
 * alter the SmartThings traversal policy and it never selects a target by
 * coordinates.
 */
object SamsungSettingsLocaleAdapter {
    const val SETTINGS_PACKAGE = "com.android.settings"
    const val LOCALE_LIST_VIEW_ID = "com.android.settings:id/locale_list_view"
    const val LOCALE_RECYCLER_VIEW_ID = "com.android.settings:id/locale_recycler_view"
    const val LANGUAGE_DESC_VIEW_ID = "com.android.settings:id/language_desc"
    const val LABEL_VIEW_ID = "com.android.settings:id/label"
    const val APPLY_CONTAINER_ID = "com.android.settings:id/apply_btn_layout"
    const val APPLY_BUTTON_ID = "com.android.settings:id/apply_button"
    const val ENGLISH_LOCALE = "en-US"
    const val KOREAN_LOCALE = "ko-KR"

    const val MAX_LOCALE_ROW_ACTIVATIONS = 1
    const val MAX_APPLY_ACTIVATIONS = 1
    const val MAX_TOTAL_MUTATING_UI_ACTIONS = 2

    val LOCALE_PICKER_COMPONENT: String =
        "$SETTINGS_PACKAGE/.Settings" + '\u0024' + "LocalePickerActivity"

    enum class Status {
        ALREADY_ACTIVE,
        HELPER_SERVICE_UNAVAILABLE,
        ROOT_UNAVAILABLE,
        WINDOW_NOT_READY,
        TARGET_READY,
        TARGET_NOT_FOUND,
        TARGET_AMBIGUOUS,
        WRONG_PACKAGE,
        WRONG_SCREEN,
        TARGET_NOT_ACTIONABLE,
        ACTION_PERFORMED,
        CONFIRMATION_REQUIRED,
        UNEXPECTED_DIALOG,
        LOCALE_CHANGE_UNVERIFIED,
        FAILED,
    }

    /** One fresh observation supplied by the owning AccessibilityService. */
    data class RootObservation(
        val serviceAvailable: Boolean,
        val root: NodeSnapshot?,
    )

    data class NodeSnapshot(
        val packageName: String? = null,
        val className: String? = null,
        val text: String? = null,
        val contentDescription: String? = null,
        val resourceId: String? = null,
        val clickable: Boolean = false,
        val focusable: Boolean = false,
        val enabled: Boolean = true,
        val visible: Boolean = true,
        val bounds: String? = null,
        val children: List<NodeSnapshot> = emptyList(),
        val onClick: (() -> Boolean)? = null,
    )

    data class TargetEvidence(
        val rowResourceId: String?,
        val labelResourceId: String?,
        val canonicalLabel: String,
        val nativeLabel: String?,
        val rowClassName: String?,
        val rowClickable: Boolean,
        val rowFocusable: Boolean,
        val rowEnabled: Boolean,
        val rowVisible: Boolean,
        val bounds: String?,
        val listResourceId: String,
    )

    /** Compact, immutable readiness facts shared with the backend contract. */
    data class ReadinessEvidence(
        val serviceAvailable: Boolean,
        val rootAvailable: Boolean,
        val rootPackage: String?,
        val packageMatches: Boolean,
        val localeListPresent: Boolean,
        val localeRecyclerPresent: Boolean,
        val languageDescriptionPresent: Boolean,
        val expectedAncestry: Boolean,
        val targetMatchCount: Int,
        val targetVisible: Boolean? = null,
        val targetEnabled: Boolean? = null,
        val targetClickable: Boolean? = null,
    ) {
        fun toJson(): JSONObject = JSONObject().apply {
            put("serviceAvailable", serviceAvailable)
            put("rootAvailable", rootAvailable)
            put("rootPackage", rootPackage ?: JSONObject.NULL)
            put("packageMatches", packageMatches)
            put("localeListPresent", localeListPresent)
            put("localeRecyclerPresent", localeRecyclerPresent)
            put("languageDescriptionPresent", languageDescriptionPresent)
            put("expectedAncestry", expectedAncestry)
            put("targetMatchCount", targetMatchCount)
            put("targetVisible", targetVisible ?: JSONObject.NULL)
            put("targetEnabled", targetEnabled ?: JSONObject.NULL)
            put("targetClickable", targetClickable ?: JSONObject.NULL)
        }

        internal fun signature(): String = listOf(
            "service=$serviceAvailable",
            "root=$rootAvailable",
            "package=${rootPackage.orEmpty()}",
            "packageMatches=$packageMatches",
            "list=$localeListPresent",
            "recycler=$localeRecyclerPresent",
            "description=$languageDescriptionPresent",
            "ancestry=$expectedAncestry",
            "targetCount=$targetMatchCount",
            "visible=${targetVisible ?: "na"}",
            "enabled=${targetEnabled ?: "na"}",
            "clickable=${targetClickable ?: "na"}",
        ).joinToString(",")
    }

    /** Bounded poll history; it never stores AccessibilityNodeInfo or trees. */
    data class PollEvolutionEvidence(
        val observationCount: Int,
        val firstSignature: String?,
        val lastSignature: String?,
        val distinctFailureSignatures: List<String>,
    ) {
        fun toJson(): JSONObject = JSONObject().apply {
            put("observationCount", observationCount)
            put("firstSignature", firstSignature ?: JSONObject.NULL)
            put("lastSignature", lastSignature ?: JSONObject.NULL)
            put("distinctFailureSignatures", distinctFailureSignatures)
        }
    }

    data class ApplyReadinessEvidence(
        val serviceAvailable: Boolean,
        val rootAvailable: Boolean,
        val rootPackage: String?,
        val packageMatches: Boolean,
        val localeRecyclerPresent: Boolean,
        val languageDescriptionPresent: Boolean,
        val expectedAncestry: Boolean,
        val applyContainerPresent: Boolean,
        val applyMatchCount: Int,
        val applyVisible: Boolean? = null,
        val applyEnabled: Boolean? = null,
        val applyClickable: Boolean? = null,
    ) {
        fun toJson(): JSONObject = JSONObject().apply {
            put("serviceAvailable", serviceAvailable)
            put("rootAvailable", rootAvailable)
            put("rootPackage", rootPackage ?: JSONObject.NULL)
            put("packageMatches", packageMatches)
            put("localeRecyclerPresent", localeRecyclerPresent)
            put("languageDescriptionPresent", languageDescriptionPresent)
            put("expectedAncestry", expectedAncestry)
            put("applyContainerPresent", applyContainerPresent)
            put("applyMatchCount", applyMatchCount)
            put("applyVisible", applyVisible ?: JSONObject.NULL)
            put("applyEnabled", applyEnabled ?: JSONObject.NULL)
            put("applyClickable", applyClickable ?: JSONObject.NULL)
        }

        internal fun signature(): String = listOf(
            "service=$serviceAvailable",
            "root=$rootAvailable",
            "package=${rootPackage.orEmpty()}",
            "packageMatches=$packageMatches",
            "recycler=$localeRecyclerPresent",
            "description=$languageDescriptionPresent",
            "ancestry=$expectedAncestry",
            "container=$applyContainerPresent",
            "applyCount=$applyMatchCount",
            "visible=${applyVisible ?: "na"}",
            "enabled=${applyEnabled ?: "na"}",
            "clickable=${applyClickable ?: "na"}",
        ).joinToString(",")
    }

    data class ApplyEvidence(
        val resourceId: String,
        val className: String?,
        val text: String?,
        val contentDescription: String?,
        val clickable: Boolean,
        val focusable: Boolean,
        val enabled: Boolean,
        val visible: Boolean,
        val bounds: String?,
        val containerResourceId: String,
    ) {
        fun toJson(): JSONObject = JSONObject().apply {
            put("resourceId", resourceId)
            put("className", className ?: JSONObject.NULL)
            put("text", text ?: JSONObject.NULL)
            put("contentDescription", contentDescription ?: JSONObject.NULL)
            put("clickable", clickable)
            put("focusable", focusable)
            put("enabled", enabled)
            put("visible", visible)
            put("bounds", bounds ?: JSONObject.NULL)
            put("containerResourceId", containerResourceId)
        }
    }

    data class Result(
        val status: Status,
        val targetLocale: String?,
        val candidateCount: Int = 0,
        val reason: String? = null,
        val evidence: TargetEvidence? = null,
        val actionPerformed: Boolean = false,
        val readiness: ReadinessEvidence? = null,
        val pollEvolution: PollEvolutionEvidence? = null,
        val applyActionAttempted: Boolean = false,
        val applyActionPerformed: Boolean = false,
        val applyReadiness: ApplyReadinessEvidence? = null,
        val applyEvidence: ApplyEvidence? = null,
        val applyPollEvolution: PollEvolutionEvidence? = null,
        internal val action: (() -> Boolean)? = null,
    ) {
        /** ACTION_PERFORMED is intentionally not final success; ADB must verify the transition. */
        fun toJson(reqId: String): JSONObject = JSONObject().apply {
            put("reqId", reqId)
            put("success", status == Status.ALREADY_ACTIVE)
            put("status", status.name)
            put("targetLocale", targetLocale ?: JSONObject.NULL)
            put("candidateCount", candidateCount)
            put("actionPerformed", actionPerformed)
            put("applyActionAttempted", applyActionAttempted)
            put("applyActionPerformed", applyActionPerformed)
            if (!reason.isNullOrBlank()) put("reason", reason)
            if (readiness != null) put("readiness", readiness.toJson())
            if (pollEvolution != null) put("pollEvolution", pollEvolution.toJson())
            if (applyReadiness != null) put("applyReadiness", applyReadiness.toJson())
            if (applyPollEvolution != null) put("applyPollEvolution", applyPollEvolution.toJson())
            if (applyEvidence != null) put("applyEvidence", applyEvidence.toJson())
            if (evidence != null) {
                put("targetEvidence", JSONObject().apply {
                    put("rowResourceId", evidence.rowResourceId ?: JSONObject.NULL)
                    put("labelResourceId", evidence.labelResourceId ?: JSONObject.NULL)
                    put("canonicalLabel", evidence.canonicalLabel)
                    put("nativeLabel", evidence.nativeLabel ?: JSONObject.NULL)
                    put("rowClassName", evidence.rowClassName ?: JSONObject.NULL)
                    put("rowClickable", evidence.rowClickable)
                    put("rowFocusable", evidence.rowFocusable)
                    put("rowEnabled", evidence.rowEnabled)
                    put("rowVisible", evidence.rowVisible)
                    put("bounds", evidence.bounds ?: JSONObject.NULL)
                    put("listResourceId", evidence.listResourceId)
                })
            }
        }
    }

    private data class LocaleLabel(
        val canonical: String,
        val native: String,
    )

    private val supportedLabels = mapOf(
        ENGLISH_LOCALE to LocaleLabel("English (United States)", "English (United States)"),
        KOREAN_LOCALE to LocaleLabel("Korean (South Korea)", "한국어(대한민국)"),
    )

    private data class HierarchyObservation(
        val readiness: ReadinessEvidence,
        val list: NodeSnapshot?,
        val recycler: NodeSnapshot?,
    )

    private data class ApplyObservation(
        val readiness: ApplyReadinessEvidence,
        val evidence: ApplyEvidence?,
        val action: (() -> Boolean)?,
        val ready: Boolean,
        val reason: String,
    )

    fun inspect(
        root: NodeSnapshot?,
        targetLocale: String?,
        currentLocale: String? = null,
    ): Result {
        val normalizedTarget = normalizeSupportedLocale(targetLocale)
            ?: return failed(targetLocale, "unsupported_locale")

        if (normalizeSupportedLocale(currentLocale) == normalizedTarget) {
            return Result(Status.ALREADY_ACTIVE, normalizedTarget, reason = "target_already_active")
        }

        if (root == null) {
            return Result(
                Status.ROOT_UNAVAILABLE,
                normalizedTarget,
                reason = "active_root_unavailable",
                readiness = ReadinessEvidence(
                    serviceAvailable = true,
                    rootAvailable = false,
                    rootPackage = null,
                    packageMatches = false,
                    localeListPresent = false,
                    localeRecyclerPresent = false,
                    languageDescriptionPresent = false,
                    expectedAncestry = false,
                    targetMatchCount = 0,
                ),
            )
        }
        val hierarchy = observeHierarchy(root)
        if (!hierarchy.readiness.packageMatches) {
            return if (root.packageName.isNullOrBlank()) {
                Result(
                    Status.WINDOW_NOT_READY,
                    normalizedTarget,
                    reason = "active_root_package_unavailable",
                    readiness = hierarchy.readiness,
                )
            } else {
                Result(
                    Status.WRONG_PACKAGE,
                    normalizedTarget,
                    reason = "expected_settings_package",
                    readiness = hierarchy.readiness,
                )
            }
        }

        if (!hierarchy.readiness.localeRecyclerPresent ||
            !hierarchy.readiness.languageDescriptionPresent ||
            !hierarchy.readiness.expectedAncestry
        ) {
            return Result(
                Status.WINDOW_NOT_READY,
                normalizedTarget,
                reason = hierarchyFailureReason(hierarchy.readiness),
                readiness = hierarchy.readiness,
            )
        }
        val recycler = hierarchy.recycler ?: return Result(
            Status.WINDOW_NOT_READY,
            normalizedTarget,
            reason = "locale_recycler_missing",
            readiness = hierarchy.readiness,
        )

        val labels = supportedLabels.getValue(normalizedTarget)
        val candidates = recycler.children.mapNotNull { row ->
            val label = row.find { it.resourceId == LABEL_VIEW_ID }
            if (label == null || !matchesLabel(label, labels)) {
                null
            } else {
                val evidence = TargetEvidence(
                    rowResourceId = row.resourceId,
                    labelResourceId = label.resourceId,
                    canonicalLabel = labels.canonical,
                    nativeLabel = label.text?.trim()?.takeIf { it.isNotEmpty() },
                    rowClassName = row.className,
                    rowClickable = row.clickable,
                    rowFocusable = row.focusable,
                    rowEnabled = row.enabled,
                    rowVisible = row.visible,
                    bounds = row.bounds,
                    listResourceId = LOCALE_RECYCLER_VIEW_ID,
                )
                evidence to row
            }
        }

        val targetReadiness = hierarchy.readiness.copy(
            targetMatchCount = candidates.size,
            targetVisible = candidates.singleOrNull()?.second?.visible,
            targetEnabled = candidates.singleOrNull()?.second?.enabled,
            targetClickable = candidates.singleOrNull()?.second?.clickable,
        )

        if (candidates.isEmpty()) {
            return Result(
                Status.TARGET_NOT_FOUND,
                normalizedTarget,
                reason = "target_missing",
                readiness = targetReadiness,
            )
        }
        if (candidates.size != 1) {
            return Result(
                Status.TARGET_AMBIGUOUS,
                normalizedTarget,
                candidateCount = candidates.size,
                reason = "target_ambiguous",
                readiness = targetReadiness,
            )
        }

        val (evidence, row) = candidates.single()
        if (!row.visible || !row.enabled || !row.clickable) {
            return Result(
                Status.TARGET_NOT_ACTIONABLE,
                normalizedTarget,
                candidateCount = 1,
                reason = when {
                    !row.visible -> "target_not_visible"
                    !row.enabled -> "target_not_enabled"
                    else -> "target_not_clickable"
                },
                evidence = evidence,
                readiness = targetReadiness,
            )
        }
        return Result(
            Status.TARGET_READY,
            normalizedTarget,
            candidateCount = 1,
            reason = "unique_locale_row_ready",
            evidence = evidence,
            readiness = targetReadiness,
            action = row.onClick,
        )
    }

    fun perform(inspected: Result): Result {
        if (inspected.status != Status.TARGET_READY) return inspected

        val click = inspected.action
            ?: return inspected.copy(
                status = Status.TARGET_NOT_ACTIONABLE,
                reason = "locale_row_click_action_unavailable",
                action = null,
            )
        val actionSucceeded = runCatching { click() }.getOrDefault(false)
        if (!actionSucceeded) {
            return inspected.copy(
                status = Status.FAILED,
                reason = "locale_row_action_returned_false",
                action = null,
            )
        }
        return inspected.copy(
            status = Status.ACTION_PERFORMED,
            reason = "locale_row_action_performed_post_verification_required",
            actionPerformed = true,
            action = null,
        )
    }

    fun perform(
        root: NodeSnapshot?,
        targetLocale: String?,
        currentLocale: String? = null,
    ): Result {
        return perform(inspect(root, targetLocale, currentLocale))
    }

    fun perform(
        root: AccessibilityNodeInfo?,
        targetLocale: String?,
        currentLocale: String? = null,
    ): Result {
        if (root == null) {
            return inspect(null, targetLocale, currentLocale)
        }
        return perform(snapshot(root), targetLocale, currentLocale)
    }

    /**
     * Polls fresh service/root observations before allowing the one row action.
     * The provider must reacquire the service and root for every observation.
     */
    internal fun performWithStabilization(
        targetLocale: String?,
        currentLocale: String? = null,
        observationProvider: () -> RootObservation,
        timeoutMillis: Long = ROOT_STABILIZATION_TIMEOUT_MILLIS,
        pollIntervalMillis: Long = ROOT_STABILIZATION_POLL_INTERVAL_MILLIS,
        nowNanos: () -> Long = System::nanoTime,
        waitMillis: (Long) -> Unit = { Thread.sleep(it) },
    ): Result {
        val normalizedTarget = normalizeSupportedLocale(targetLocale)
            ?: return failed(targetLocale, "unsupported_locale")
        if (normalizeSupportedLocale(currentLocale) == normalizedTarget) {
            return Result(Status.ALREADY_ACTIVE, normalizedTarget, reason = "target_already_active")
        }

        val boundedTimeout = timeoutMillis.coerceAtLeast(0L)
        val deadline = nowNanos() + boundedTimeout * NANOS_PER_MILLISECOND
        var lastResult: Result? = null
        var wrongScreenOnly = true
        var observationCount = 0
        var firstSignature: String? = null
        var lastSignature: String? = null
        val distinctFailureSignatures = linkedSetOf<String>()

        while (true) {
            val observation = observationProvider()
            observationCount += 1
            val result = when {
                !observation.serviceAvailable -> Result(
                    Status.HELPER_SERVICE_UNAVAILABLE,
                    normalizedTarget,
                    reason = "service_instance_unavailable",
                    readiness = unavailableReadiness(serviceAvailable = false),
                )

                observation.root == null -> Result(
                    Status.ROOT_UNAVAILABLE,
                    normalizedTarget,
                    reason = "active_root_unavailable",
                    readiness = unavailableReadiness(serviceAvailable = true),
                )

                else -> inspect(observation.root, normalizedTarget, currentLocale)
            }
            val signature = "${result.status.name}|${result.readiness?.signature().orEmpty()}"
            if (firstSignature == null) firstSignature = signature
            lastSignature = signature
            if (result.status != Status.TARGET_READY && result.status != Status.ALREADY_ACTIVE &&
                distinctFailureSignatures.size < MAX_DISTINCT_FAILURE_SIGNATURES
            ) {
                distinctFailureSignatures += signature
            }
            val evolution = PollEvolutionEvidence(
                observationCount = observationCount,
                firstSignature = firstSignature,
                lastSignature = lastSignature,
                distinctFailureSignatures = distinctFailureSignatures.toList(),
            )
            val observedResult = result.copy(pollEvolution = evolution)
            lastResult = observedResult

            when (observedResult.status) {
                Status.TARGET_READY -> {
                    val rowResult = perform(observedResult)
                    if (rowResult.status != Status.ACTION_PERFORMED) return rowResult
                    return performApplyWithStabilization(
                        rowResult = rowResult,
                        observationProvider = observationProvider,
                        timeoutMillis = boundedTimeout,
                        pollIntervalMillis = pollIntervalMillis,
                        nowNanos = nowNanos,
                        waitMillis = waitMillis,
                    )
                }
                Status.ALREADY_ACTIVE -> return observedResult
                Status.WRONG_PACKAGE, Status.WRONG_SCREEN -> Unit
                else -> wrongScreenOnly = false
            }

            val remainingNanos = deadline - nowNanos()
            if (remainingNanos <= 0L) break
            val requestedWait = pollIntervalMillis.coerceAtLeast(1L)
            val remainingMillis = (remainingNanos + NANOS_PER_MILLISECOND - 1L) / NANOS_PER_MILLISECOND
            waitMillis(minOf(requestedWait, remainingMillis))
        }

        val finalResult = lastResult ?: return Result(
            Status.HELPER_SERVICE_UNAVAILABLE,
            normalizedTarget,
            reason = "no_root_observation",
            readiness = unavailableReadiness(serviceAvailable = false),
        )
        if (wrongScreenOnly && finalResult.status == Status.WRONG_PACKAGE) {
            return Result(
                Status.WRONG_SCREEN,
                normalizedTarget,
                reason = "unrelated_package_through_deadline",
                readiness = finalResult.readiness,
                pollEvolution = finalResult.pollEvolution,
            )
        }
        return finalResult.copy(
            reason = "${finalResult.reason ?: finalResult.status.name.lowercase()}_deadline_expired",
            action = null,
        )
    }

    private fun performApplyWithStabilization(
        rowResult: Result,
        observationProvider: () -> RootObservation,
        timeoutMillis: Long,
        pollIntervalMillis: Long,
        nowNanos: () -> Long,
        waitMillis: (Long) -> Unit,
    ): Result {
        val boundedTimeout = timeoutMillis.coerceAtLeast(0L)
        val deadline = nowNanos() + boundedTimeout * NANOS_PER_MILLISECOND
        var lastObservation: ApplyObservation? = null
        var observationCount = 0
        var firstSignature: String? = null
        var lastSignature: String? = null
        val distinctFailureSignatures = linkedSetOf<String>()

        while (true) {
            val observation = inspectApply(observationProvider())
            lastObservation = observation
            observationCount += 1
            val signature = if (observation.ready) {
                "APPLY_READY|${observation.readiness.signature()}"
            } else {
                "${observation.reason}|${observation.readiness.signature()}"
            }
            if (firstSignature == null) firstSignature = signature
            lastSignature = signature
            if (!observation.ready && distinctFailureSignatures.size < MAX_DISTINCT_FAILURE_SIGNATURES) {
                distinctFailureSignatures += signature
            }
            val evolution = PollEvolutionEvidence(
                observationCount = observationCount,
                firstSignature = firstSignature,
                lastSignature = lastSignature,
                distinctFailureSignatures = distinctFailureSignatures.toList(),
            )

            if (observation.ready) {
                val click = observation.action
                    ?: return rowResult.copy(
                        status = Status.FAILED,
                        reason = "apply_button_action_unavailable",
                        applyReadiness = observation.readiness,
                        applyEvidence = observation.evidence,
                        applyPollEvolution = evolution,
                        action = null,
                    )
                val actionSucceeded = runCatching { click() }.getOrDefault(false)
                return rowResult.copy(
                    status = if (actionSucceeded) Status.ACTION_PERFORMED else Status.FAILED,
                    reason = if (actionSucceeded) {
                        "locale_apply_action_performed_post_verification_required"
                    } else {
                        "apply_button_action_returned_false"
                    },
                    applyActionAttempted = true,
                    applyActionPerformed = actionSucceeded,
                    applyReadiness = observation.readiness,
                    applyEvidence = observation.evidence,
                    applyPollEvolution = evolution,
                    action = null,
                )
            }

            val remainingNanos = deadline - nowNanos()
            if (remainingNanos <= 0L) break
            val requestedWait = pollIntervalMillis.coerceAtLeast(1L)
            val remainingMillis = (remainingNanos + NANOS_PER_MILLISECOND - 1L) / NANOS_PER_MILLISECOND
            waitMillis(minOf(requestedWait, remainingMillis))
        }

        val finalObservation = lastObservation ?: return rowResult.copy(
            status = Status.FAILED,
            reason = "apply_confirmation_no_observation",
            action = null,
        )
        return rowResult.copy(
            status = Status.FAILED,
            reason = "${finalObservation.reason}_deadline_expired",
            applyReadiness = finalObservation.readiness,
            applyEvidence = finalObservation.evidence,
            applyPollEvolution = PollEvolutionEvidence(
                observationCount = observationCount,
                firstSignature = firstSignature,
                lastSignature = lastSignature,
                distinctFailureSignatures = distinctFailureSignatures.toList(),
            ),
            action = null,
        )
    }

    private fun inspectApply(observation: RootObservation): ApplyObservation {
        val root = observation.root
        if (!observation.serviceAvailable) {
            return ApplyObservation(
                readiness = unavailableApplyReadiness(serviceAvailable = false, rootAvailable = false),
                evidence = null,
                action = null,
                ready = false,
                reason = "helper_service_unavailable",
            )
        }
        if (root == null) {
            return ApplyObservation(
                readiness = unavailableApplyReadiness(serviceAvailable = true, rootAvailable = false),
                evidence = null,
                action = null,
                ready = false,
                reason = "active_root_unavailable",
            )
        }

        val hierarchy = observeHierarchy(root)
        val candidates = root.paths { it.resourceId == APPLY_BUTTON_ID }
        val candidate = candidates.singleOrNull()
        val applyContainerPresent = candidate?.ancestors?.any { it.resourceId == APPLY_CONTAINER_ID } == true
        val candidateInSettingsContext = candidate?.let { path ->
            isSettingsContextNode(path.node) &&
                path.ancestors.all(::isSettingsContextNode)
        } == true
        val readiness = ApplyReadinessEvidence(
            serviceAvailable = true,
            rootAvailable = true,
            rootPackage = hierarchy.readiness.rootPackage,
            packageMatches = hierarchy.readiness.packageMatches,
            localeRecyclerPresent = hierarchy.readiness.localeRecyclerPresent,
            languageDescriptionPresent = hierarchy.readiness.languageDescriptionPresent,
            expectedAncestry = hierarchy.readiness.expectedAncestry,
            applyContainerPresent = applyContainerPresent,
            applyMatchCount = candidates.size,
            applyVisible = candidate?.node?.visible,
            applyEnabled = candidate?.node?.enabled,
            applyClickable = candidate?.node?.clickable,
        )
        val evidence = candidate?.let { path ->
            ApplyEvidence(
                resourceId = APPLY_BUTTON_ID,
                className = path.node.className,
                text = path.node.text,
                contentDescription = path.node.contentDescription,
                clickable = path.node.clickable,
                focusable = path.node.focusable,
                enabled = path.node.enabled,
                visible = path.node.visible,
                bounds = path.node.bounds,
                containerResourceId = APPLY_CONTAINER_ID,
            )
        }
        val contextReady = hierarchy.readiness.packageMatches &&
            hierarchy.readiness.localeRecyclerPresent &&
            hierarchy.readiness.languageDescriptionPresent &&
            hierarchy.readiness.expectedAncestry &&
            candidateInSettingsContext
        val reason = when {
            !hierarchy.readiness.packageMatches -> "expected_settings_package"
            !hierarchy.readiness.localeRecyclerPresent -> "locale_recycler_missing"
            !hierarchy.readiness.languageDescriptionPresent -> "language_desc_missing"
            !hierarchy.readiness.expectedAncestry -> "expected_ancestry_missing"
            candidates.isEmpty() -> "apply_button_missing"
            candidates.size != 1 -> "apply_button_ambiguous"
            !candidateInSettingsContext -> "apply_button_context_missing"
            candidate?.node?.visible != true -> "apply_button_not_visible"
            candidate?.node?.enabled != true -> "apply_button_not_enabled"
            candidate?.node?.clickable != true -> "apply_button_not_clickable"
            else -> "apply_button_ready"
        }
        return ApplyObservation(
            readiness = readiness,
            evidence = evidence,
            action = candidate?.node?.onClick,
            ready = contextReady && reason == "apply_button_ready",
            reason = reason,
        )
    }

    internal fun normalizeSupportedLocale(value: String?): String? {
        return when (value?.trim()) {
            ENGLISH_LOCALE -> ENGLISH_LOCALE
            KOREAN_LOCALE -> KOREAN_LOCALE
            else -> null
        }
    }

    private fun failed(targetLocale: String?, reason: String): Result = Result(
        status = Status.FAILED,
        targetLocale = normalizeSupportedLocale(targetLocale),
        reason = reason,
    )

    private fun observeHierarchy(root: NodeSnapshot): HierarchyObservation {
        val rootPackage = root.packageName
        val packageMatches = rootPackage == SETTINGS_PACKAGE
        if (!packageMatches) {
            return HierarchyObservation(
                readiness = ReadinessEvidence(
                    serviceAvailable = true,
                    rootAvailable = true,
                    rootPackage = rootPackage,
                    packageMatches = false,
                    localeListPresent = false,
                    localeRecyclerPresent = false,
                    languageDescriptionPresent = false,
                    expectedAncestry = false,
                    targetMatchCount = 0,
                ),
                list = null,
                recycler = null,
            )
        }

        val list = root.find { it.resourceId == LOCALE_LIST_VIEW_ID }
        val recycler = root.find { it.resourceId == LOCALE_RECYCLER_VIEW_ID }
        val languageDescription = root.find { it.resourceId == LANGUAGE_DESC_VIEW_ID }
        val expectedAncestry = isSettingsContextNode(recycler) &&
            isSettingsContextNode(languageDescription)
        return HierarchyObservation(
            readiness = ReadinessEvidence(
                serviceAvailable = true,
                rootAvailable = true,
                rootPackage = rootPackage,
                packageMatches = true,
                localeListPresent = list != null,
                localeRecyclerPresent = recycler != null,
                languageDescriptionPresent = languageDescription != null,
                expectedAncestry = expectedAncestry,
                targetMatchCount = 0,
            ),
            list = list,
            recycler = recycler,
        )
    }

    private fun hierarchyFailureReason(readiness: ReadinessEvidence): String = when {
        !readiness.localeRecyclerPresent -> "locale_recycler_missing"
        !readiness.languageDescriptionPresent -> "language_desc_missing"
        !readiness.expectedAncestry -> "expected_ancestry_missing"
        else -> "locale_picker_hierarchy_not_ready"
    }

    private fun isSettingsContextNode(node: NodeSnapshot?): Boolean {
        return node != null && (node.packageName == null || node.packageName == SETTINGS_PACKAGE)
    }

    private fun unavailableReadiness(serviceAvailable: Boolean): ReadinessEvidence = ReadinessEvidence(
        serviceAvailable = serviceAvailable,
        rootAvailable = false,
        rootPackage = null,
        packageMatches = false,
        localeListPresent = false,
        localeRecyclerPresent = false,
        languageDescriptionPresent = false,
        expectedAncestry = false,
        targetMatchCount = 0,
    )

    private fun unavailableApplyReadiness(
        serviceAvailable: Boolean,
        rootAvailable: Boolean,
    ): ApplyReadinessEvidence = ApplyReadinessEvidence(
        serviceAvailable = serviceAvailable,
        rootAvailable = rootAvailable,
        rootPackage = null,
        packageMatches = false,
        localeRecyclerPresent = false,
        languageDescriptionPresent = false,
        expectedAncestry = false,
        applyContainerPresent = false,
        applyMatchCount = 0,
    )

    private fun matchesLabel(label: NodeSnapshot, expected: LocaleLabel): Boolean {
        return sequenceOf(label.contentDescription, label.text)
            .filterNotNull()
            .map(String::trim)
            .any { it == expected.canonical || it == expected.native }
    }

    private fun NodeSnapshot.find(predicate: (NodeSnapshot) -> Boolean): NodeSnapshot? {
        if (predicate(this)) return this
        for (child in children) {
            child.find(predicate)?.let { return it }
        }
        return null
    }

    private data class NodePath(
        val node: NodeSnapshot,
        val ancestors: List<NodeSnapshot>,
    )

    private fun NodeSnapshot.paths(predicate: (NodeSnapshot) -> Boolean): List<NodePath> {
        val matches = mutableListOf<NodePath>()

        fun visit(node: NodeSnapshot, ancestors: List<NodeSnapshot>) {
            if (predicate(node)) matches += NodePath(node, ancestors)
            node.children.forEach { child -> visit(child, ancestors + node) }
        }

        visit(this, emptyList())
        return matches
    }

    private const val MAX_SNAPSHOT_DEPTH = 12
    private const val MAX_SNAPSHOT_NODES = 512
    private const val ROOT_STABILIZATION_TIMEOUT_MILLIS = 1_500L
    private const val ROOT_STABILIZATION_POLL_INTERVAL_MILLIS = 50L
    private const val NANOS_PER_MILLISECOND = 1_000_000L
    private const val MAX_DISTINCT_FAILURE_SIGNATURES = 8

    internal fun snapshot(root: AccessibilityNodeInfo): NodeSnapshot {
        var count = 0
        fun build(node: AccessibilityNodeInfo, depth: Int): NodeSnapshot {
            count += 1
            val children = if (depth < MAX_SNAPSHOT_DEPTH && count < MAX_SNAPSHOT_NODES) {
                (0 until node.childCount).mapNotNull { index ->
                    runCatching { node.getChild(index) }.getOrNull()?.let { build(it, depth + 1) }
                }
            } else {
                emptyList()
            }
            val rect = Rect()
            node.getBoundsInScreen(rect)
            return NodeSnapshot(
                packageName = node.packageName?.toString(),
                className = node.className?.toString(),
                text = node.text?.toString(),
                contentDescription = node.contentDescription?.toString(),
                resourceId = node.viewIdResourceName,
                clickable = node.isClickable,
                focusable = node.isFocusable,
                enabled = node.isEnabled,
                visible = node.isVisibleToUser,
                bounds = rect.toShortString(),
                children = children,
                onClick = { node.performAction(AccessibilityNodeInfo.ACTION_CLICK) },
            )
        }
        return build(root, 0)
    }
}
