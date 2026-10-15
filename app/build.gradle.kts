import java.nio.file.Files
import java.security.MessageDigest
import java.time.Instant
import java.time.format.DateTimeFormatter

plugins {
    id("com.android.application") 
    id("org.jetbrains.kotlin.android") 
}

data class HelperBuildIdentityValues(
    val buildId: String,
    val gitCommit: String,
    val inputDigest: String,
    val sourceState: String,
    val variant: String,
    val timestamp: String
)

fun sha256Text(value: String): String = MessageDigest.getInstance("SHA-256")
    .digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

fun sha256Bytes(value: ByteArray): String = MessageDigest.getInstance("SHA-256")
    .digest(value).joinToString("") { "%02x".format(it) }

fun runGit(vararg arguments: String): String? = runCatching {
    val process = ProcessBuilder(listOf("git", "-C", rootProject.projectDir.absolutePath) + arguments)
        .redirectErrorStream(true).start()
    val output = process.inputStream.bufferedReader().readText().trim()
    if (process.waitFor() == 0) output else null
}.getOrNull()

fun helperBuildIdentity(variant: String): HelperBuildIdentityValues {
    val repo = rootProject.projectDir.toPath()
    val relativeInputs = listOf(
        "app/src/main", "app/build.gradle.kts", "build.gradle.kts", "settings.gradle.kts",
        "gradle.properties", "gradle/wrapper/gradle-wrapper.properties", "gradle/libs.versions.toml",
        "gradlew", "gradlew.bat"
    )
    val files = relativeInputs.flatMap { relative ->
        val path = repo.resolve(relative)
        when {
            Files.isRegularFile(path) -> listOf(path)
            Files.isDirectory(path) -> Files.walk(path).use { stream ->
                stream.filter { Files.isRegularFile(it) }.toList()
            }
            else -> emptyList()
        }
    }.distinct().sortedBy { repo.relativize(it).toString().replace('\\', '/') }
    val inputLines = files.joinToString("\n") { path ->
        val relative = repo.relativize(path).toString().replace('\\', '/')
        "$relative=${sha256Bytes(Files.readAllBytes(path))}"
    }
    val inputDigest = sha256Text(inputLines)
    val commit = runGit("rev-parse", "HEAD")
    val status = runGit("status", "--porcelain", "--untracked-files=all", "--", *relativeInputs.toTypedArray())
    val sourceState = when {
        commit == null || status == null -> "UNKNOWN"
        status.isBlank() -> "CLEAN"
        else -> "DIRTY"
    }
    val timestamp = System.getenv("SOURCE_DATE_EPOCH")?.toLongOrNull()?.let {
        DateTimeFormatter.ISO_INSTANT.format(Instant.ofEpochSecond(it))
    } ?: runGit("show", "-s", "--format=%ct", "HEAD")?.toLongOrNull()?.let {
        DateTimeFormatter.ISO_INSTANT.format(Instant.ofEpochSecond(it))
    }.orEmpty()
    val buildId = if (commit == null || sourceState == "UNKNOWN") "UNKNOWN" else sha256Text(
        listOf("schema=helper-build-manifest.v1", "git_commit=$commit", "input_digest=$inputDigest",
            "source_state=$sourceState", "build_variant=$variant", "version_name=1.0", "version_code=1",
            "gradle_version=${gradle.gradleVersion}")
            .joinToString("\n")
    )
    return HelperBuildIdentityValues(buildId, commit ?: "UNKNOWN", inputDigest, sourceState, variant, timestamp)
}

fun buildConfigString(value: String): String = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

val debugHelperIdentity = helperBuildIdentity("debug")
val releaseHelperIdentity = helperBuildIdentity("release")

fun helperBuildConfigFields(identity: HelperBuildIdentityValues): Map<String, String> = mapOf(
    "HELPER_PROTOCOL_VERSION" to buildConfigString("talkback.exact-navigation.v1"),
    "HELPER_BUILD_ID" to buildConfigString(identity.buildId),
    "HELPER_GIT_COMMIT" to buildConfigString(identity.gitCommit),
    "HELPER_INPUT_DIGEST" to buildConfigString(identity.inputDigest),
    "HELPER_SOURCE_STATE" to buildConfigString(identity.sourceState),
    "HELPER_BUILD_VARIANT" to buildConfigString(identity.variant),
    "HELPER_BUILD_TIMESTAMP" to buildConfigString(identity.timestamp),
)

android {
    namespace = "com.iotpart.sqe.talkbackhelper"
    compileSdk = 34
    buildFeatures { buildConfig = true }

    defaultConfig {
        applicationId = "com.iotpart.sqe.talkbackhelper"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        getByName("debug") {
            helperBuildConfigFields(debugHelperIdentity).forEach { (name, value) -> buildConfigField("String", name, value) }
        }
        release {
            helperBuildConfigFields(releaseHelperIdentity).forEach { (name, value) -> buildConfigField("String", name, value) }
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }
    kotlinOptions {
        jvmTarget = "21"
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.17")
}
