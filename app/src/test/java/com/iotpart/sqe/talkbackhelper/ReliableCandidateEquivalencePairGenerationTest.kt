package com.iotpart.sqe.talkbackhelper

import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ReliableCandidateEquivalencePairGenerationTest {
    @Test
    fun generatesApi34PairsFromSharedFixedInputs() {
        writePairsForApi(34, expectedCount = 19, outputEnvironmentName = "TB_CANDIDATE_C4_API34_OUTPUT")
    }

    @Test
    @Config(sdk = [27])
    fun generatesApi27PairWithUnsupportedScreenReaderFocusableMetadata() {
        writePairsForApi(27, expectedCount = 1, outputEnvironmentName = "TB_CANDIDATE_C4_API27_OUTPUT")
    }

    private fun writePairsForApi(apiLevel: Int, expectedCount: Int, outputEnvironmentName: String) {
        assertEquals(apiLevel, Build.VERSION.SDK_INT)
        val selectedFixtures = CandidateEquivalenceFixtureSupport.fixtures()
            .filter { it.getInt("platform_api_level") == apiLevel }
        assertEquals(expectedCount, selectedFixtures.size)

        val pairs = JSONArray()
        selectedFixtures.forEach { fixture ->
            val fixtureId = fixture.getString("fixture_id")
            val requestId = "c4-offline-$fixtureId"
            val root = CandidateEquivalenceFixtureSupport.root(fixture)

            // Both paths consume this exact AccessibilityNodeInfo root instance.
            val legacy = A11yNavigator.dumpTreeFlat(root)
            val reliable = CandidateEquivalenceFixtureSupport.reliablePayload(root, requestId)
            val projection = reliable.getJSONObject("traversalCandidates")

            if (apiLevel < Build.VERSION_CODES.P) {
                val rawRoot = reliable.getJSONArray("windows").getJSONObject(0).getJSONObject("root")
                val firstChild = rawRoot.getJSONArray("children").getJSONObject(0)
                assertTrue(firstChild.has("screenReaderFocusable"))
                assertTrue(firstChild.isNull("screenReaderFocusable"))
            }
            assertTrue(ReliableHierarchyCandidateContract.hasValidRootBinding(reliable))
            assertEquals(legacy.getJSONArray("nodes").toString(), projection.getJSONArray("candidates").toString())
            assertEquals(legacy.getBoolean("canScrollDown"), projection.getBoolean("canScrollDown"))

            pairs.put(JSONObject()
                .put("fixture_id", fixtureId)
                .put("input_sha256", CandidateEquivalenceFixtureSupport.inputDigest(fixture))
                .put("legacy_generator_version", A11yNavigator.NAVIGATOR_ALGORITHM_VERSION)
                .put("analyzer_version", A11yTraversalAnalyzer.VERSION)
                .put("raw_schema_version", reliable.getString("schemaVersion"))
                .put("candidate_schema_version", projection.getString("schema_version"))
                .put("candidate_contract_version", projection.getString("candidate_contract_version"))
                .put("legacy_candidate_count", legacy.getJSONArray("nodes").length())
                .put("v2_candidate_count", projection.getJSONArray("candidates").length())
                .put("root_binding_valid", ReliableHierarchyCandidateContract.hasValidRootBinding(reliable))
                .put("legacy_output", legacy)
                .put("v2_payload", reliable))
        }

        val generated = JSONObject()
            .put("fixture_schema", "talkback-candidate-equivalence-pairs.v1")
            .put("platform_api_level", apiLevel)
            .put("pairs", pairs)
        val committedArtifact = javaClass.getResourceAsStream(
            "/candidate_equivalence/pairs_api$apiLevel.json"
        )?.bufferedReader(Charsets.UTF_8)?.use { JSONObject(it.readText()) }
        if (committedArtifact != null) {
            assertEquals(
                "C4_PAIR_ARTIFACT_DRIFT_API_$apiLevel",
                committedArtifact.toString(),
                generated.toString()
            )
        }

        System.getenv(outputEnvironmentName)?.takeIf(String::isNotBlank)?.let { outputPath ->
            val output = File(outputPath).absoluteFile
            output.parentFile?.mkdirs()
            output.writeText(generated.toString(2) + "\n", Charsets.UTF_8)
        }
    }
}
