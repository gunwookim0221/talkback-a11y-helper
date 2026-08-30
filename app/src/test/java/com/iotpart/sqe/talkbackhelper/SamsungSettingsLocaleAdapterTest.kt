package com.iotpart.sqe.talkbackhelper

import com.iotpart.sqe.talkbackhelper.SamsungSettingsLocaleAdapter.NodeSnapshot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SamsungSettingsLocaleAdapterTest {

    @Test
    fun inspect_accepts_uniqueEnglishCanonicalLabel() {
        val result = SamsungSettingsLocaleAdapter.inspect(localePicker(row("en-US")), "en-US", "ko-KR")

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_READY, result.status)
        assertEquals(1, result.candidateCount)
        assertEquals("English (United States)", result.evidence?.canonicalLabel)
        assertEquals(1, result.readiness?.targetMatchCount)
        assertTrue(result.readiness?.packageMatches == true)
    }

    @Test
    fun inspect_acceptsUniqueKoreanCanonicalContentDescriptionAndNativeText() {
        val result = SamsungSettingsLocaleAdapter.inspect(localePicker(row("ko-KR")), "ko-KR", "en-US")

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_READY, result.status)
        assertEquals(1, result.candidateCount)
        assertEquals("Korean (South Korea)", result.evidence?.canonicalLabel)
        assertEquals("한국어(대한민국)", result.evidence?.nativeLabel)
        assertEquals(true, result.readiness?.targetClickable)
    }

    @Test
    fun inspect_rejectsMissingTarget() {
        val result = SamsungSettingsLocaleAdapter.inspect(localePicker(row("en-US")), "ko-KR", "en-US")

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_NOT_FOUND, result.status)
        assertEquals(0, result.candidateCount)
    }

    @Test
    fun inspect_rejectsDuplicateTargetRows() {
        val result = SamsungSettingsLocaleAdapter.inspect(
            localePicker(row("ko-KR"), row("ko-KR")),
            "ko-KR",
            "en-US",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_AMBIGUOUS, result.status)
        assertEquals(2, result.candidateCount)
    }

    @Test
    fun inspect_rejectsWrongPackage() {
        val result = SamsungSettingsLocaleAdapter.inspect(
            localePicker(row("ko-KR")).copy(packageName = "com.samsung.android.oneconnect"),
            "ko-KR",
            "en-US",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.WRONG_PACKAGE, result.status)
    }

    @Test
    fun inspect_rejectsUnexpectedHierarchy() {
        val result = SamsungSettingsLocaleAdapter.inspect(
            NodeSnapshot(packageName = SamsungSettingsLocaleAdapter.SETTINGS_PACKAGE),
            "ko-KR",
            "en-US",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.WINDOW_NOT_READY, result.status)
        assertEquals("locale_recycler_missing", result.reason)
        assertEquals(false, result.readiness?.localeListPresent)
        assertEquals(false, result.readiness?.localeRecyclerPresent)
        assertEquals(false, result.readiness?.languageDescriptionPresent)
        assertEquals(false, result.readiness?.expectedAncestry)
    }

    @Test
    fun inspect_reportsEachMissingHierarchyPredicate() {
        val cases = listOf(
            localePicker(row("ko-KR"), includeList = false, includeRecycler = false) to
                "locale_recycler_missing",
            localePicker(row("ko-KR"), includeList = false, includeDescription = false) to
                "language_desc_missing",
            localePicker(
                row("ko-KR"),
                includeList = false,
                recyclerPackage = "com.samsung.android.oneconnect",
            ) to "expected_ancestry_missing",
        )

        cases.forEach { (root, expectedReason) ->
            val result = SamsungSettingsLocaleAdapter.inspect(root, "ko-KR", "en-US")

            assertEquals(SamsungSettingsLocaleAdapter.Status.WINDOW_NOT_READY, result.status)
            assertEquals(expectedReason, result.reason)
            assertEquals(true, result.readiness?.rootAvailable)
            assertEquals(true, result.readiness?.packageMatches)
        }
    }

    @Test
    fun inspect_acceptsUniqueTargetWhenLocaleListIsAbsent() {
        val result = SamsungSettingsLocaleAdapter.inspect(
            localePicker(row("ko-KR"), includeList = false),
            "ko-KR",
            "en-US",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_READY, result.status)
        assertEquals(1, result.candidateCount)
        assertEquals(1, result.readiness?.targetMatchCount)
        assertEquals(false, result.readiness?.localeListPresent)
        assertEquals(true, result.readiness?.localeRecyclerPresent)
        assertEquals(true, result.readiness?.expectedAncestry)
    }

    @Test
    fun inspect_acceptsEnglishTargetWhenLocaleListIsAbsent() {
        val result = SamsungSettingsLocaleAdapter.inspect(
            localePicker(row("en-US"), includeList = false),
            "en-US",
            "ko-KR",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_READY, result.status)
        assertEquals(1, result.readiness?.targetMatchCount)
        assertEquals(false, result.readiness?.localeListPresent)
    }

    @Test
    fun inspect_preservesDuplicateTargetAmbiguityWhenLocaleListIsAbsent() {
        val result = SamsungSettingsLocaleAdapter.inspect(
            localePicker(row("ko-KR"), row("ko-KR"), includeList = false),
            "ko-KR",
            "en-US",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_AMBIGUOUS, result.status)
        assertEquals(2, result.readiness?.targetMatchCount)
    }

    @Test
    fun inspect_acceptsCanonicalKoreanContentDescriptionWithoutNativeText() {
        val originalRow = row("ko-KR")
        val labelWithoutNativeText = originalRow.children.single().copy(text = null)
        val result = SamsungSettingsLocaleAdapter.inspect(
            localePicker(originalRow.copy(children = listOf(labelWithoutNativeText))),
            "ko-KR",
            "en-US",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_READY, result.status)
        assertEquals(1, result.readiness?.targetMatchCount)
    }

    @Test
    fun stabilization_reportsServiceUnavailableAfterDeadline() {
        val result = stabilize(
            listOf(SamsungSettingsLocaleAdapter.RootObservation(serviceAvailable = false, root = null)),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.HELPER_SERVICE_UNAVAILABLE, result.status)
        assertEquals(false, result.readiness?.serviceAvailable)
        assertEquals(5, result.pollEvolution?.observationCount)
    }

    @Test
    fun stabilization_continuesWhenServiceBecomesAvailable() {
        var clicks = 0
        val result = stabilize(
            listOf(
                SamsungSettingsLocaleAdapter.RootObservation(serviceAvailable = false, root = null),
                SamsungSettingsLocaleAdapter.RootObservation(
                    serviceAvailable = true,
                    root = localePicker(row("ko-KR", onClick = { clicks += 1; true })),
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(1, clicks)
        assertEquals(2, result.pollEvolution?.observationCount)
        assertEquals(1, result.pollEvolution?.distinctFailureSignatures?.size)
    }

    @Test
    fun stabilization_reportsRootUnavailableAfterDeadline() {
        val result = stabilize(
            listOf(SamsungSettingsLocaleAdapter.RootObservation(serviceAvailable = true, root = null)),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ROOT_UNAVAILABLE, result.status)
        assertEquals(true, result.readiness?.serviceAvailable)
        assertEquals(false, result.readiness?.rootAvailable)
    }

    @Test
    fun stabilization_waitsForRootThenActivatesOnce() {
        var clicks = 0
        val result = stabilize(
            listOf(
                SamsungSettingsLocaleAdapter.RootObservation(serviceAvailable = true, root = null),
                SamsungSettingsLocaleAdapter.RootObservation(
                    serviceAvailable = true,
                    root = localePicker(row("ko-KR", onClick = { clicks += 1; true })),
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(1, clicks)
        assertEquals(2, result.pollEvolution?.observationCount)
    }

    @Test
    fun stabilization_activatesOnceWhenLocaleListRemainsAbsent() {
        var clicks = 0
        val result = stabilize(
            listOf(
                SamsungSettingsLocaleAdapter.RootObservation(
                    serviceAvailable = true,
                    root = localePicker(
                        row("ko-KR", onClick = { clicks += 1; true }),
                        includeList = false,
                    ),
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(1, clicks)
        assertEquals(false, result.readiness?.localeListPresent)
        assertEquals(1, result.readiness?.targetMatchCount)
        assertEquals(1, result.pollEvolution?.observationCount)
    }

    @Test
    fun stabilization_waitsForIncompleteWindowThenActivates() {
        var clicks = 0
        val incomplete = NodeSnapshot(packageName = SamsungSettingsLocaleAdapter.SETTINGS_PACKAGE)
        val result = stabilize(
            listOf(
                SamsungSettingsLocaleAdapter.RootObservation(serviceAvailable = true, root = incomplete),
                SamsungSettingsLocaleAdapter.RootObservation(
                    serviceAvailable = true,
                    root = localePicker(row("ko-KR", onClick = { clicks += 1; true })),
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(1, clicks)
        assertEquals(2, result.pollEvolution?.observationCount)
        assertEquals(1, result.pollEvolution?.distinctFailureSignatures?.size)
    }

    @Test
    fun stabilization_reportsWindowNotReadyWhenMarkersNeverAppear() {
        val incomplete = NodeSnapshot(packageName = SamsungSettingsLocaleAdapter.SETTINGS_PACKAGE)
        val result = stabilize(
            listOf(SamsungSettingsLocaleAdapter.RootObservation(serviceAvailable = true, root = incomplete)),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.WINDOW_NOT_READY, result.status)
        assertEquals("locale_recycler_missing_deadline_expired", result.reason)
        assertEquals(5, result.pollEvolution?.observationCount)
        assertEquals(1, result.pollEvolution?.distinctFailureSignatures?.size)
        assertEquals(
            result.pollEvolution?.firstSignature,
            result.pollEvolution?.lastSignature,
        )
    }

    @Test
    fun stabilization_reportsWrongScreenForStableUnrelatedPackage() {
        val result = stabilize(
            listOf(
                SamsungSettingsLocaleAdapter.RootObservation(
                    serviceAvailable = true,
                    root = NodeSnapshot(packageName = "com.samsung.android.oneconnect"),
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.WRONG_SCREEN, result.status)
        assertEquals(false, result.readiness?.packageMatches)
    }

    @Test
    fun stabilization_usesFreshRootWhenRootChangesBetweenPolls() {
        var staleClicks = 0
        var currentClicks = 0
        val staleRoot = NodeSnapshot(
            packageName = "com.samsung.android.oneconnect",
            onClick = { staleClicks += 1; true },
        )
        val currentRoot = localePicker(row("ko-KR", onClick = { currentClicks += 1; true }))
        val result = stabilize(
            listOf(
                SamsungSettingsLocaleAdapter.RootObservation(serviceAvailable = true, root = staleRoot),
                SamsungSettingsLocaleAdapter.RootObservation(serviceAvailable = true, root = currentRoot),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(0, staleClicks)
        assertEquals(1, currentClicks)
        assertEquals(2, result.pollEvolution?.observationCount)
    }

    @Test
    fun stabilization_timeoutPerformsZeroActivations() {
        var clicks = 0
        val result = stabilize(
            listOf(
                SamsungSettingsLocaleAdapter.RootObservation(
                    serviceAvailable = true,
                    root = localePicker(row("ko-KR", clickable = false, onClick = { clicks += 1; true })),
                ),
            ),
            timeoutMillis = 0L,
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_NOT_ACTIONABLE, result.status)
        assertEquals(0, clicks)
        assertEquals(false, result.readiness?.targetClickable)
    }

    @Test
    fun inspect_rejectsDisabledOrNonClickableTarget() {
        val disabled = SamsungSettingsLocaleAdapter.inspect(
            localePicker(row("ko-KR", enabled = false)),
            "ko-KR",
            "en-US",
        )
        val nonClickable = SamsungSettingsLocaleAdapter.inspect(
            localePicker(row("ko-KR", clickable = false)),
            "ko-KR",
            "en-US",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_NOT_ACTIONABLE, disabled.status)
        assertEquals(SamsungSettingsLocaleAdapter.Status.TARGET_NOT_ACTIONABLE, nonClickable.status)
        assertEquals(false, disabled.readiness?.targetEnabled)
        assertEquals(false, nonClickable.readiness?.targetClickable)
    }

    @Test
    fun stabilization_activatesRowThenFreshApplyExactlyOnce() {
        var rowClicks = 0
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR", onClick = { rowClicks += 1; true }),
                    onApply = { applyClicks += 1; true },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals("locale_apply_action_performed_post_verification_required", result.reason)
        assertTrue(result.actionPerformed)
        assertTrue(result.applyActionAttempted)
        assertTrue(result.applyActionPerformed)
        assertEquals(1, rowClicks)
        assertEquals(1, applyClicks)
        assertEquals(1, result.applyPollEvolution?.observationCount)
    }

    @Test
    fun stabilization_identifiesApplyByResourceIdWithoutEnglishText() {
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR"),
                    applyText = null,
                    applyContentDescription = null,
                    onApply = { applyClicks += 1; true },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(1, applyClicks)
        assertEquals(SamsungSettingsLocaleAdapter.APPLY_BUTTON_ID, result.applyEvidence?.resourceId)
    }

    @Test
    fun stabilization_identifiesLocalizedApplyByResourceId() {
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR"),
                    applyText = "적용",
                    applyContentDescription = "적용",
                    onApply = { applyClicks += 1; true },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(1, applyClicks)
        assertEquals("적용", result.applyEvidence?.text)
    }

    @Test
    fun stabilization_acceptsApplyWhenLayoutContainerIsAbsentFromHelperTree() {
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR"),
                    includeApplyContainer = false,
                    onApply = { applyClicks += 1; true },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals("locale_apply_action_performed_post_verification_required", result.reason)
        assertEquals(1, applyClicks)
        assertEquals(1, result.applyReadiness?.applyMatchCount)
        assertEquals(false, result.applyReadiness?.applyContainerPresent)
    }

    @Test
    fun stabilization_rejectsApplyWithoutStableResourceId() {
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR"),
                    applyResourceId = "com.android.settings:id/other_button",
                    onApply = { applyClicks += 1; true },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, result.status)
        assertEquals("apply_button_missing_deadline_expired", result.reason)
        assertEquals(0, applyClicks)
        assertEquals(0, result.applyReadiness?.applyMatchCount)
    }

    @Test
    fun stabilization_rejectsDuplicateApplyCandidatesWithoutAction() {
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR"),
                    applyCount = 2,
                    onApply = { applyClicks += 1; true },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, result.status)
        assertEquals("apply_button_ambiguous_deadline_expired", result.reason)
        assertEquals(0, applyClicks)
        assertEquals(2, result.applyReadiness?.applyMatchCount)
    }

    @Test
    fun stabilization_rejectsApplyThatIsNotActionable() {
        val cases = listOf(
            localePicker(row("ko-KR"), applyVisible = false) to "apply_button_not_visible_deadline_expired",
            localePicker(row("ko-KR"), applyEnabled = false) to "apply_button_not_enabled_deadline_expired",
            localePicker(row("ko-KR"), applyClickable = false) to "apply_button_not_clickable_deadline_expired",
        )

        cases.forEach { (root, expectedReason) ->
            var applyClicks = 0
            val result = stabilize(
                listOf(root.copy(children = root.children.map { container ->
                    container.copy(children = container.children.map { button ->
                        button.copy(onClick = { applyClicks += 1; true })
                    })
                })),
            )

            assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, result.status)
            assertEquals(expectedReason, result.reason)
            assertEquals(0, applyClicks)
        }
    }

    @Test
    fun stabilization_rejectsWrongPackageAndNonLocaleContextWithoutApplyAction() {
        var applyClicks = 0
        val wrongPackage = localePicker(row("ko-KR"), includeApply = false)
            .copy(packageName = "com.samsung.android.oneconnect")
        val wrongPackageResult = stabilize(
            listOf(
                localePicker(row("ko-KR"), includeApply = false),
                wrongPackage,
            ),
        )
        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, wrongPackageResult.status)
        assertEquals("expected_settings_package_deadline_expired", wrongPackageResult.reason)
        assertEquals(0, applyClicks)

        val nonLocaleContextResult = stabilize(
            listOf(
                localePicker(row("ko-KR"), includeApply = false),
                localePicker(row("ko-KR"), includeRecycler = false, onApply = { applyClicks += 1; true }),
            ),
        )
        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, nonLocaleContextResult.status)
        assertEquals("locale_recycler_missing_deadline_expired", nonLocaleContextResult.reason)
        assertEquals(0, applyClicks)
    }

    @Test
    fun stabilization_doesNotInspectApplyWhenRowActionFails() {
        var rowClicks = 0
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR", onClick = { rowClicks += 1; false }),
                    onApply = { applyClicks += 1; true },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, result.status)
        assertEquals("locale_row_action_returned_false", result.reason)
        assertEquals(1, rowClicks)
        assertEquals(0, applyClicks)
        assertFalse(result.applyActionAttempted)
    }

    @Test
    fun stabilization_waitsForApplyOnFreshRootAfterRowAction() {
        var rowClicks = 0
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR", onClick = { rowClicks += 1; true }),
                    includeApply = false,
                ),
                localePicker(
                    row("ko-KR"),
                    onApply = { applyClicks += 1; true },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(1, rowClicks)
        assertEquals(1, applyClicks)
        assertEquals(1, result.applyPollEvolution?.observationCount)
    }

    @Test
    fun stabilization_timesOutWithoutApplyAndNeverRetriesRow() {
        var rowClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR", onClick = { rowClicks += 1; true }),
                    includeApply = false,
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, result.status)
        assertEquals("apply_button_missing_deadline_expired", result.reason)
        assertEquals(1, rowClicks)
        assertFalse(result.applyActionAttempted)
        assertTrue((result.applyPollEvolution?.observationCount ?: 0) > 0)
    }

    @Test
    fun stabilization_doesNotRetryFailedApplyAction() {
        var applyClicks = 0
        val result = stabilize(
            listOf(
                localePicker(
                    row("ko-KR"),
                    onApply = { applyClicks += 1; false },
                ),
            ),
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, result.status)
        assertEquals("apply_button_action_returned_false", result.reason)
        assertEquals(1, applyClicks)
        assertTrue(result.applyActionAttempted)
        assertFalse(result.applyActionPerformed)
    }

    @Test
    fun stabilization_doesNotDuplicateApplyAfterConfigurationRootChange() {
        var observations = 0
        var applyClicks = 0
        var nowNanos = 0L
        val roots = listOf(
            localePicker(row("ko-KR"), includeApply = false),
            localePicker(row("ko-KR"), onApply = { applyClicks += 1; true }),
            localePicker(row("ko-KR"), onApply = { applyClicks += 1; true }),
        )
        val result = SamsungSettingsLocaleAdapter.performWithStabilization(
            targetLocale = "ko-KR",
            currentLocale = "en-US",
            observationProvider = { roots[minOf(observations++, roots.lastIndex)].let { SamsungSettingsLocaleAdapter.RootObservation(true, it) } },
            timeoutMillis = 40L,
            pollIntervalMillis = 10L,
            nowNanos = { nowNanos },
            waitMillis = { millis -> nowNanos += millis * 1_000_000L },
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertEquals(2, observations)
        assertEquals(1, applyClicks)
    }

    @Test
    fun stabilization_usesSameApplySemanticsForEnglishAndKoreanTargets() {
        var englishApplyClicks = 0
        val englishResult = stabilize(
            listOf(
                localePicker(
                    row("en-US"),
                    onApply = { englishApplyClicks += 1; true },
                ),
            ),
            targetLocale = "en-US",
            currentLocale = "ko-KR",
        )
        var koreanApplyClicks = 0
        val koreanResult = stabilize(
            listOf(
                localePicker(
                    row("ko-KR"),
                    onApply = { koreanApplyClicks += 1; true },
                ),
            ),
            targetLocale = "ko-KR",
            currentLocale = "en-US",
        )

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, englishResult.status)
        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, koreanResult.status)
        assertEquals(1, englishApplyClicks)
        assertEquals(1, koreanApplyClicks)
        assertEquals(englishResult.applyEvidence?.resourceId, koreanResult.applyEvidence?.resourceId)
    }

    @Test
    fun inspect_returnsAlreadyActiveWithoutRequiringOrPerformingAction() {
        val result = SamsungSettingsLocaleAdapter.perform(localePicker(row("ko-KR")), "ko-KR", "ko-KR")

        assertEquals(SamsungSettingsLocaleAdapter.Status.ALREADY_ACTIVE, result.status)
        assertFalse(result.actionPerformed)
    }

    @Test
    fun inspect_rejectsUnsupportedLocale() {
        val result = SamsungSettingsLocaleAdapter.inspect(localePicker(row("ko-KR")), "ja-JP", "en-US")

        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, result.status)
        assertEquals("unsupported_locale", result.reason)
    }

    @Test
    fun performActivatesOnlyTheUniqueSemanticRow() {
        var clicks = 0
        val root = localePicker(row("ko-KR", onClick = { clicks += 1; true }))

        val result = SamsungSettingsLocaleAdapter.perform(root, "ko-KR", "en-US")

        assertEquals(SamsungSettingsLocaleAdapter.Status.ACTION_PERFORMED, result.status)
        assertTrue(result.actionPerformed)
        assertEquals(1, clicks)
    }

    @Test
    fun performReportsFailedActionWithoutRetryingOrClaimingSuccess() {
        var clicks = 0
        val root = localePicker(row("ko-KR", onClick = { clicks += 1; false }))

        val result = SamsungSettingsLocaleAdapter.perform(root, "ko-KR", "en-US")

        assertEquals(SamsungSettingsLocaleAdapter.Status.FAILED, result.status)
        assertFalse(result.actionPerformed)
        assertEquals(1, clicks)
    }

    @Test
    fun resultIncludesCompactReadinessAndPollEvolution() {
        val result = stabilize(
            listOf(
                SamsungSettingsLocaleAdapter.RootObservation(
                    serviceAvailable = true,
                    root = localePicker(row("ko-KR"), includeRecycler = false),
                ),
            ),
        )

        assertEquals(false, result.readiness?.localeRecyclerPresent)
        assertEquals("com.android.settings", result.readiness?.rootPackage)
        assertTrue((result.pollEvolution?.observationCount ?: 0) > 1)
        assertTrue((result.pollEvolution?.distinctFailureSignatures?.size ?: 0) <= 8)
    }

    private fun localePicker(
        vararg rows: NodeSnapshot,
        includeList: Boolean = true,
        includeRecycler: Boolean = true,
        includeDescription: Boolean = true,
        recyclerInsideList: Boolean = true,
        recyclerPackage: String? = null,
        includeApply: Boolean = true,
        applyCount: Int = 1,
        applyResourceId: String? = SamsungSettingsLocaleAdapter.APPLY_BUTTON_ID,
        includeApplyContainer: Boolean = true,
        applyText: String? = "Apply",
        applyContentDescription: String? = null,
        applyClickable: Boolean = true,
        applyEnabled: Boolean = true,
        applyVisible: Boolean = true,
        onApply: (() -> Boolean)? = { true },
    ): NodeSnapshot {
        val recycler = NodeSnapshot(
            packageName = recyclerPackage,
            resourceId = SamsungSettingsLocaleAdapter.LOCALE_RECYCLER_VIEW_ID,
            className = "androidx.recyclerview.widget.RecyclerView",
            children = rows.toList(),
        )
        val applyContainers = (0 until applyCount.coerceAtLeast(0)).map {
            NodeSnapshot(
                resourceId = SamsungSettingsLocaleAdapter.APPLY_CONTAINER_ID,
                children = listOf(
                    NodeSnapshot(
                        resourceId = applyResourceId,
                        className = "android.widget.Button",
                        text = applyText,
                        contentDescription = applyContentDescription,
                        clickable = applyClickable,
                        focusable = true,
                        enabled = applyEnabled,
                        visible = applyVisible,
                        onClick = onApply,
                    ),
                ),
            )
        }
        val applyNodes = if (includeApplyContainer) {
            applyContainers
        } else {
            applyContainers.map { container -> container.children.single() }
        }
        val list = NodeSnapshot(
            resourceId = SamsungSettingsLocaleAdapter.LOCALE_LIST_VIEW_ID,
            children = buildList {
                if (includeRecycler && recyclerInsideList) add(recycler)
                if (includeApply) addAll(applyNodes)
            },
        )
        val children = buildList {
            if (includeList) add(list)
            if (includeRecycler && (!includeList || !recyclerInsideList)) add(recycler)
            if (includeDescription) {
                add(NodeSnapshot(resourceId = SamsungSettingsLocaleAdapter.LANGUAGE_DESC_VIEW_ID))
            }
            if (includeApply && !includeList) addAll(applyNodes)
        }
        return NodeSnapshot(
            packageName = SamsungSettingsLocaleAdapter.SETTINGS_PACKAGE,
            className = "android.widget.LinearLayout",
            children = children,
        )
    }

    private fun row(
        locale: String,
        clickable: Boolean = true,
        enabled: Boolean = true,
        visible: Boolean = true,
        onClick: (() -> Boolean)? = { true },
    ): NodeSnapshot {
        val (text, description) = when (locale) {
            "en-US" -> "English (United States)" to "English (United States)"
            "ko-KR" -> "한국어(대한민국)" to "Korean (South Korea)"
            else -> locale to locale
        }
        return NodeSnapshot(
            className = "android.widget.LinearLayout",
            clickable = clickable,
            focusable = true,
            enabled = enabled,
            visible = visible,
            bounds = "[30,656][1050,824]",
            children = listOf(
                NodeSnapshot(
                    resourceId = SamsungSettingsLocaleAdapter.LABEL_VIEW_ID,
                    className = "android.widget.TextView",
                    text = text,
                    contentDescription = description,
                    enabled = enabled,
                    visible = visible,
                ),
            ),
            onClick = onClick,
        )
    }

    private fun stabilize(
        observations: List<Any>,
        timeoutMillis: Long = 40L,
        targetLocale: String = "ko-KR",
        currentLocale: String = "en-US",
    ): SamsungSettingsLocaleAdapter.Result {
        var index = 0
        var nowNanos = 0L
        return SamsungSettingsLocaleAdapter.performWithStabilization(
            targetLocale = targetLocale,
            currentLocale = currentLocale,
            observationProvider = {
                when (val observation = observations[minOf(index++, observations.lastIndex)]) {
                    is SamsungSettingsLocaleAdapter.RootObservation -> observation
                    is NodeSnapshot -> SamsungSettingsLocaleAdapter.RootObservation(
                        serviceAvailable = true,
                        root = observation,
                    )
                    else -> error("unsupported test observation")
                }
            },
            timeoutMillis = timeoutMillis,
            pollIntervalMillis = 10L,
            nowNanos = { nowNanos },
            waitMillis = { millis -> nowNanos += millis * 1_000_000L },
        )
    }
}
