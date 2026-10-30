package com.iotpart.sqe.talkbackhelper

import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class CaptureRootIdGoldenTest {
    @Test
    fun captureLocalRootIdentityMatchesPythonGoldenVector() {
        assertEquals(
            "fde8456b615adfa22d816cd1bcf7f8762265d96d3e39a2be2ee402070db50c71",
            ReliableHierarchyCandidateContract.rootCaptureId(
                requestId = "request-1",
                processEpoch = "epoch-1",
                generation = 3L,
                serviceInstanceId = "service-1",
                captureSequence = 2L,
                rootRef = "windows[1].root",
                rootDigest = "a".repeat(64),
            ),
        )
    }
}
