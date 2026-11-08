package com.autosongs.bridge

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Checks on the bridge app that do not need an Android device.
 *
 * The bridge app is a second half of AutoSongs: the same bridge, but on
 * its own, so a phone can reach it over the network. The two halves
 * must not drift apart - a bridge app with a different version number,
 * or a manifest that has quietly lost a permission, would be found out
 * by a user rather than by a build.
 */
class BridgeAppTest {

    /** The repository root, found by walking up from the module. */
    private fun root(): File {
        var dir = File(".").absoluteFile
        while (dir.parentFile != null) {
            if (File(dir, "settings.gradle.kts").exists()) return dir
            dir = dir.parentFile
        }
        throw IllegalStateException("could not find the repository root")
    }

    private fun appBuildFile() = File(root(), "app/build.gradle.kts")
    private fun bridgeBuildFile() = File(root(), "bridgeapp/build.gradle.kts")
    private fun manifest() = File(root(), "bridgeapp/src/main/AndroidManifest.xml")

    @Test
    fun `the bridge app takes its version from the app, so the two cannot drift`() {
        val appText = appBuildFile().readText()
        val bridgeText = bridgeBuildFile().readText()

        val appName = Regex("versionName = \"([^\"]+)\"").find(appText)!!.groupValues[1]
        val appCode = Regex("versionCode = (\\d+)").find(appText)!!.groupValues[1]

        // The bridge app must read the number, not write it out again.
        assertTrue(
            "the bridge app should read the app's version, not keep its own copy",
            bridgeText.contains("appVersionName()") &&
                bridgeText.contains("appVersionCode()")
        )
        assertTrue(
            "the bridge app should be signed with the app's own key",
            bridgeText.contains("keystore.properties")
        )
        assertEquals("com.autosongs.bridge", Regex("applicationId = \"([^\"]+)\"").find(bridgeText)!!.groupValues[1])

        // and the numbers must be sane: the app's version is the truth
        assertTrue("the app's version code should be a number", appCode.toIntOrNull() != null)
        assertTrue("the app should have a version name", appName.isNotEmpty())
    }

    @Test
    fun `the manifest declares the foreground service the bridge runs in`() {
        val text = manifest().readText()

        assertTrue("the bridge needs the internet", text.contains("android.permission.INTERNET"))
        assertTrue(
            "the bridge needs to keep running in the foreground",
            text.contains("android.permission.FOREGROUND_SERVICE")
        )
        assertTrue(
            "the bridge needs the specialUse foreground service type",
            text.contains("android.permission.FOREGROUND_SERVICE_SPECIAL_USE")
        )
        assertTrue(
            "the service must say what it is for, or the phone will not hold it",
            text.contains("PROPERTY_SPECIAL_USE_FGS_SUBTYPE")
        )
        assertTrue("the bridge is a service", text.contains(".BridgeService"))
        assertTrue("the bridge app has a screen", text.contains(".MainActivity"))
    }

    @Test
    fun `the bridge app and the app share one bridge, not two`() {
        val wrapper = File(root(), "bridgeapp/src/main/python/autosongs_bridge.py").readText()
        val bridge = File(root(), "bridge/ytbridge.py").readText()

        // The wrapper is a thin cover over the one bridge.
        assertTrue(
            "the wrapper should import the shared bridge, not copy it",
            wrapper.contains("import ytbridge")
        )
        assertTrue(
            "the wrapper should not carry its own copy of the bridge",
            !wrapper.contains("def make_server(") &&
                !wrapper.contains("def make_pair_code(")
        )
        assertTrue(
            "the shared bridge is what makes the pairing code",
            bridge.contains("def make_pair_code(")
        )

        // and the module compiles that one file, exactly as the app does
        val buildFile = bridgeBuildFile().readText()
        assertTrue(
            "the bridge app should compile the shared bridge source",
            buildFile.contains("srcDir(\"../bridge\")")
        )
    }

    @Test
    fun `the bridge app can find its own icon`() {
        // The manifest asks for an icon; a missing one stops the app
        // from linking, and the build error says nothing about the icon.
        val text = manifest().readText()
        assertTrue("the manifest names an icon", text.contains("@mipmap/ic_launcher"))
        for (name in listOf("mipmap-anydpi-v26", "mipmap-anydpi-v33")) {
            assertTrue(
                "the $name icon is missing",
                File(root(), "bridgeapp/src/main/res/$name/ic_launcher.xml").exists()
            )
        }
        assertTrue(
            "the icon's foreground is missing",
            File(root(), "bridgeapp/src/main/res/drawable/ic_launcher_foreground.xml").exists()
        )
        assertTrue(
            "the icon's background is missing",
            File(root(), "bridgeapp/src/main/res/drawable/ic_launcher_background.xml").exists()
        )
    }
}
