import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python") version "17.2.0"
}

/**
 * The app's version number, so the two are never out of step.
 *
 * It is read from the app's own file rather than written out twice - a
 * version number that can drift apart is a version number that will.
 */
fun appVersionName(): String {
    val text = rootProject.file("app/build.gradle.kts").readText()
    return Regex("versionName = \"([^\"]+)\"").find(text)?.groupValues?.get(1) ?: "0"
}

/** The app's version code, for the same reason. */
fun appVersionCode(): Int {
    val text = rootProject.file("app/build.gradle.kts").readText()
    return Regex("versionCode = (\\d+)").find(text)?.groupValues?.get(1)?.toIntOrNull() ?: 1
}

/**
 * The bridge, as an app of its own.
 *
 * This is the same Python program the AutoSongs app carries inside it, but
 * on its own, listening on the network so a phone can reach it. It is for
 * people who want the songs to land on the phone that runs the bridge -
 * an old tablet, a phone in a drawer - and not on the one they use.
 *
 * The two share one bridge source file. There is no second implementation
 * to keep in step: this module compiles ../bridge/ytbridge.py, exactly as
 * the app does.
 */
android {
    namespace = "com.autosongs.bridge"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.autosongs.bridge"
        minSdk = 26
        targetSdk = 35

        // The version is the same as the app's, so a person never has to
        // wonder which half is behind.
        versionCode = appVersionCode()
        versionName = appVersionName()

        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64")
        }
    }

    // Read from the root project, where it is worked out once.
    val hasReleaseKey = rootProject.extra["hasReleaseKey"] as Boolean

    signingConfigs {
        create("release") {
            // The same key as the app. A keystore can sign as many
            // packages as it likes, and one backup is one thing to keep
            // safe rather than two.
            val props = Properties()
            val file = rootProject.file("keystore.properties")
            if (file.exists()) {
                file.inputStream().use { props.load(it) }
            }
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
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            // The key is not in the repository, so a clone has none and
            // the debug key is used. See keystore.properties.example.
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
 * The same Python the app runs, for the same reason: yt-dlp is a Python
 * program, and an app that downloads from YouTube needs an interpreter.
 * Chaquopy puts one inside the APK.
 */
chaquopy {
    defaultConfig {
        version = "3.11"
        System.getenv("CHAQUOPY_BUILD_PYTHON")?.let { buildPython = listOf(it) }

        pip {
            install("yt-dlp==2026.10.26")
        }
    }

    sourceSets {
        getByName("main") {
            // One copy of the bridge, shared with the app and with the
            // Termux setup.
            srcDir("../bridge")
            exclude("test_*.py")
            exclude("manual_*.py")
            exclude("*.sh")
            // The bridge keeps a backup of itself when it updates.
            // That is a safety net, not code, and shipping it would put
            // a stale copy of the bridge in the app.
            exclude("*.bak")
            exclude("*.cmd")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-service:2.8.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("androidx.test:core:1.6.1")
    testImplementation("androidx.test.ext:junit:1.2.1")
}
