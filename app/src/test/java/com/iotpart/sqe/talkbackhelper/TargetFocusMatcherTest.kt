package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TargetFocusMatcherTest {
    private val first = TargetFocusMatcher.Candidate("[0,100][100,200]", "id/action", "Help", "android.widget.Button")
    private val second = TargetFocusMatcher.Candidate("[0,220][100,320]", "id/action", "Power off", "android.widget.Button")

    @Test fun exactTargetWinsOverSibling() {
        val result = TargetFocusMatcher.resolve(
            TargetFocusMatcher.Descriptor(second.bounds, second.resourceId, second.label, second.className),
            listOf(first, second)
        )
        assertEquals(TargetFocusMatcher.Resolution.MATCHED, result.resolution)
        assertEquals(1, result.index)
    }

    @Test fun sameResourceIdDifferentBoundsRemainDistinct() {
        val result = TargetFocusMatcher.resolve(
            TargetFocusMatcher.Descriptor(second.bounds, second.resourceId, "", second.className),
            listOf(first, second)
        )
        assertEquals(1, result.index)
    }

    @Test fun missingTargetIsNotFound() {
        assertEquals(TargetFocusMatcher.Resolution.NOT_FOUND,
            TargetFocusMatcher.resolve(TargetFocusMatcher.Descriptor("[9,9][10,10]", "id/action"), listOf(first)).resolution)
    }

    @Test fun resourceOnlyDescriptorIsRejected() {
        assertEquals(TargetFocusMatcher.Resolution.INVALID,
            TargetFocusMatcher.resolve(TargetFocusMatcher.Descriptor("", "id/action"), listOf(first)).resolution)
    }

    @Test fun duplicateStrongIdentityIsAmbiguous() {
        val descriptor = TargetFocusMatcher.Descriptor(first.bounds, first.resourceId, first.label, first.className)
        assertEquals(TargetFocusMatcher.Resolution.AMBIGUOUS,
            TargetFocusMatcher.resolve(descriptor, listOf(first, first.copy())).resolution)
    }

    @Test fun siblingDoesNotMatchSelectedTarget() {
        val descriptor = TargetFocusMatcher.Descriptor(first.bounds, first.resourceId, first.label, first.className)
        assertTrue(!TargetFocusMatcher.sameIdentity(descriptor, second))
    }

    @Test fun focusableOptInFiltersPresentationWrapperButDefaultStillRejectsAmbiguity() {
        val wrapper = TargetFocusMatcher.Candidate("[0,0][1080,2640]", className="android.webkit.WebView", enabled=true)
        val canonical = wrapper.copy(focusable=true)
        val descriptor = TargetFocusMatcher.Descriptor(wrapper.bounds, className=wrapper.className)
        assertEquals(TargetFocusMatcher.Resolution.AMBIGUOUS, TargetFocusMatcher.resolve(descriptor, listOf(wrapper,canonical)).resolution)
        assertEquals(1, TargetFocusMatcher.resolve(descriptor.copy(requireFocusable=true), listOf(wrapper,canonical)).index)
    }

    @Test fun twoRealFocusableTargetsRemainAmbiguous() {
        val target = first.copy(focusable=true, enabled=true)
        val descriptor = TargetFocusMatcher.Descriptor(target.bounds, target.resourceId, target.label, target.className, requireFocusable=true)
        assertEquals(TargetFocusMatcher.Resolution.AMBIGUOUS, TargetFocusMatcher.resolve(descriptor,listOf(target,target.copy())).resolution)
    }

    @Test fun disabledOrUnknownFocusableTargetCannotExecuteWithOptIn() {
        val descriptor = TargetFocusMatcher.Descriptor(first.bounds, first.resourceId, className=first.className, requireFocusable=true)
        for (candidate in listOf(first,first.copy(focusable=true),first.copy(enabled=true))) {
            assertEquals(TargetFocusMatcher.Resolution.NOT_FOUND, TargetFocusMatcher.resolve(descriptor,listOf(candidate)).resolution)
        }
        assertEquals(TargetFocusMatcher.Resolution.MATCHED, TargetFocusMatcher.resolve(descriptor,listOf(first.copy(focusable=true,enabled=true))).resolution)
    }
}
