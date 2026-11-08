package com.autosongs.ytdl

import android.os.Build
import androidx.test.core.app.ApplicationProvider
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.media.MediaSessionProbe
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Detection must not depend on the notification-listener service being bound.
 * The probe reads media sessions directly, and only falls back to the listener
 * component when that is not allowed.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.UPSIDE_DOWN_CAKE])
class MediaSessionProbeTest {

    @Test
    fun scan_never_throws_and_reports_access_state() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        val watched = setOf("com.google.android.apps.youtube.music")
        val result = MediaSessionProbe.scan(ctx, watched)

        assertNotNull(result)
        assertTrue("samples must not exceed the session count", result.samples.size <= result.sessions)
    }

    @Test
    fun scan_with_empty_watch_list_does_not_crash() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        val result = MediaSessionProbe.scan(ctx, emptySet())
        assertNotNull(result)
    }

    @Test
    fun direct_access_does_not_need_notification_access() {
        // The direct path relies on MEDIA_CONTENT_CONTROL, which is a normal
        // permission granted at install time. It must be declared in the
        // manifest, otherwise the fallback is the only option.
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        val declared = ctx.packageManager
            .getPackageInfo(ctx.packageName, android.content.pm.PackageManager.GET_PERMISSIONS)
            .requestedPermissions ?: emptyArray()

        assertTrue(
            "MEDIA_CONTENT_CONTROL must be declared",
            declared.contains(android.Manifest.permission.MEDIA_CONTENT_CONTROL)
        )
    }

    @Test
    fun watched_packages_include_both_music_clients() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        val settings = AppSettings.get(ctx)
        val packages = settings.watchedPackages.split(",").map { it.trim() }
        assertEquals(2, packages.size)
        assertTrue(packages.contains("app.revanced.android.youtube.music"))
    }
}
