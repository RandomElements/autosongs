package com.autosongs.ytdl

import android.os.Build
import androidx.test.core.app.ApplicationProvider
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.data.MusicApps
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Guards the "app does not pick up songs" class of failure: the package name of
 * the YouTube Music client is not stable, so both known variants must be
 * watched by default and detection must never crash.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.UPSIDE_DOWN_CAKE])
class MusicAppDetectionTest {

    @Test
    fun default_packages_include_revanced_variants() {
        val settings = AppSettings.get(ApplicationProvider.getApplicationContext())
        val packages = settings.watchedPackages.split(",").map { it.trim() }

        assertTrue("official YouTube Music must be watched",
            packages.contains("com.google.android.apps.youtube.music"))
        assertTrue("ReVanced Extended renames itself and must be watched",
            packages.contains("app.revanced.android.youtube.music"))
    }

    @Test
    fun detect_never_throws_and_returns_a_list() {
        val apps = MusicApps.detect(ApplicationProvider.getApplicationContext())
        assertNotNull(apps)
        // on a clean Robolectric device there may be nothing, but the call
        // must not throw
        assertTrue(apps.all { it.packageName.isNotBlank() })
    }

    @Test
    fun always_list_contains_both_variants() {
        assertTrue(MusicApps.ALWAYS.contains("com.google.android.apps.youtube.music"))
        assertTrue(MusicApps.ALWAYS.contains("app.revanced.android.youtube.music"))
    }
}
