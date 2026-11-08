import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python") version "17.2.0"
}

android {
    namespace = "com.autosongs.ytdl"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.autosongs"
        minSdk = 26
        targetSdk = 35
        versionCode = 170
        versionName = "1.4.25"

        ndk {
            // The Python runtime ships as a native library, so the APK only
            // needs the ABIs we actually ship. A 32 bit phone is still
            // possible, so all three are kept - an APK without the right
            // ABI cannot be installed at all.
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64")
        }
    }

    // The key is not in the repository, so a clone has none. The root
    // project knows whether this machine has one; read it, so there is
    // one answer and not two that can disagree.
    val hasReleaseKey = rootProject.extra["hasReleaseKey"] as Boolean

    signingConfigs {
        create("release") {
            val props = Properties()
            val file = rootProject.file("keystore.properties")
            if (file.exists()) {
                file.inputStream().use { props.load(it) }
            }
            // The key is deliberately not in the repository, so a
            // clone has none. rootProject.file("") is not a File - it
            // is an error - so the values are only set when there is
            // a key to set them from, and the release build falls
            // back to the debug key when there is not.
            val store = props.getProperty("storeFile", "")
            if (store.isNotBlank() && rootProject.file(store).exists()) {
                storeFile = rootProject.file(store)
                storePassword = props.getProperty("storePassword", "")
                keyAlias = props.getProperty("keyAlias", "")
                keyPassword = props.getProperty("keyPassword", "")
            }
        }
    }

    buildTypes {
        release {
            // The library code nobody calls was being shipped as it was.
            // R8 takes the dex from 9.6 MB to about a third of that.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Signed with AutoSongs' own key, not the debug one. The
            // debug key is the same on every machine that has ever built
            // an Android app, so anybody could sign an "update" to this
            // app with it.
            //
            // A clone has no key, so it uses the debug one. See
            // keystore.properties.example.
            signingConfig = if (hasReleaseKey) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        viewBinding = true
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
            isReturnDefaultValues = true
        }
    }
}

/**
 * The bridge runs INSIDE the app.
 *
 * yt-dlp is a Python program, so an app that wants to download from YouTube
 * needs a Python interpreter. Chaquopy puts one inside the APK and runs it
 * in the app's own process, which means:
 *
 *   - no Termux, no second app, no pasting a command into a terminal
 *   - the bridge keeps listening on 127.0.0.1:8765, so the download code
 *     in the app does not change at all
 *   - the app can replace yt-dlp with a newer version at runtime, so the
 *     "HTTP Error 403: Forbidden" that a stale yt-dlp causes can never
 *     happen again
 */
chaquopy {
    defaultConfig {
        // The runtime has to match the Python that builds the pip packages
        // on this machine, so the versions are kept in step.
        version = "3.11"
        System.getenv("CHAQUOPY_BUILD_PYTHON")?.let { buildPython = listOf(it) }

        pip {
            // yt-dlp is pure Python, so it installs as it is.
            install("yt-dlp==2026.10.26")
        }
    }

    sourceSets {
        getByName("main") {
            // One copy of the bridge, shared with the Termux setup.
            srcDir("../bridge")
            exclude("test_*.py")
            exclude("manual_*.py")
            exclude("*.sh")
            // The bridge keeps a backup of itself when it updates.
            // That is a safety net, not code, and shipping it would put
            // a stale copy of the bridge in the app.
            exclude("*.bak")
        }
    }
}

/**
 * The app carries the bridge as an asset so it can push it to a bridge on
 * another machine. That copy has to be the same file as the one in the
 * Python source set, so it is generated during the build instead of being
 * copied by hand and going stale.
 */
val syncBridgeAsset by tasks.registering(Copy::class) {
    from(rootProject.file("bridge/ytbridge.py"))
    into(layout.buildDirectory.dir("generated/autosongs/assets"))
}

android.sourceSets.getByName("main").assets.srcDir(
    layout.buildDirectory.dir("generated/autosongs/assets")
)

// Everything that reads the generated assets has to wait for them.
tasks.matching { it.name.endsWith("Assets") || it.name.contains("lint", true) }
    .configureEach { dependsOn(syncBridgeAsset) }

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.lifecycle:lifecycle-service:2.8.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.1")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("androidx.test:core:1.6.1")
    testImplementation("androidx.test.ext:junit:1.2.1")
}
