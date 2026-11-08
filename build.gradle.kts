import java.util.Properties

plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}

/**
 * Whether this machine has the release signing key.
 *
 * The key is deliberately not in the repository: anybody holding it could
 * sign an "update" to the app and have a phone install it. A clone has
 * none, and a release build without one falls back to the debug key
 * rather than failing outright - a build that cannot run at all is a
 * poor first impression.
 *
 * Both modules read this from here, so there is one answer and not two
 * that can disagree.
 */
val keystoreFile = rootProject.file("keystore.properties")
val releaseStore = if (keystoreFile.exists()) {
    val props = Properties()
    keystoreFile.inputStream().use { props.load(it) }
    props.getProperty("storeFile", "")
} else {
    ""
}
extra["hasReleaseKey"] =
    releaseStore.isNotBlank() && rootProject.file(releaseStore).exists()
