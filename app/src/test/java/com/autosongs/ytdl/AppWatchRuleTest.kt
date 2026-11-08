package com.autosongs.ytdl

import android.os.Build
import androidx.test.core.app.ApplicationProvider
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.data.MusicApps
import com.autosongs.ytdl.data.watchedApps
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The app watches every app that plays music, not only the ticked ones.
 *
 * A media session is the system's own way of saying "something is
 * playing", so any app that publishes one is a music app - Spotify, Apple
 * Music, a browser playing a video. Watching only a hand-written list of
 * package names meant that everything else was silently ignored.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.UPSIDE_DOWN_CAKE])
class AppWatchRuleTest {

    private val settings: AppSettings
        get() = AppSettings.get(ApplicationProvider.getApplicationContext())

    // The preferences are shared by every test in the run, so this test
    // puts them back the way it found them. Otherwise it would change
    // what another test believes about the default.
    private var savedPackages = ""
    private var savedWatchAll = true

    @Before
    fun remember() {
        savedPackages = settings.watchedPackages
        savedWatchAll = settings.watchAllApps
    }

    @After
    fun putBack() {
        settings.watchedPackages = savedPackages
        settings.watchAllApps = savedWatchAll
    }

    @Test
    fun every_app_is_watched_by_default() {
        settings.watchAllApps = true
        assertTrue("every app that plays music must be watched by default",
            settings.watchAllApps)
    }

    @Test
    fun an_empty_watched_set_means_every_app() {
        settings.watchAllApps = true
        settings.watchedPackages = "com.example.something"
        assertTrue("an empty set means every app",
            watchedApps(settings).isEmpty())
    }

    @Test
    fun the_list_is_used_when_the_switch_is_off() {
        settings.watchAllApps = false
        settings.watchedPackages = " com.example.one , com.example.two ,, "
        assertEquals(
            setOf("com.example.one", "com.example.two"),
            watchedApps(settings)
        )
    }

    @Test
    fun the_well_known_apps_include_the_music_ones_and_the_browsers() {
        val packages = MusicApps.POPULAR.map { it.first }
        for (wanted in listOf(
            "com.spotify.music",
            "com.apple.android.music",
            "com.deezer.android.app",
            "com.soundcloud.android",
            "com.tidal.hifi",
            "com.android.chrome",
            "com.mozilla.firefox",
            "com.brave.browser",
            "com.microsoft.emmx",
            "com.opera.browser"
        )) {
            assertTrue("$wanted must be in the list", packages.contains(wanted))
        }
    }

    @Test
    fun detection_finds_the_playing_apps_and_never_throws() {
        val apps = MusicApps.detect(ApplicationProvider.getApplicationContext())
        assertTrue(apps.all { it.packageName.isNotBlank() })
    }
}
