package com.autosongs.ytdl

import android.os.Build
import com.autosongs.ytdl.update.AppUpdate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The release feed.
 *
 * The feed is a file on the internet that says which build is the newest.
 * Two things have to be right: a newer build has to be recognised as
 * newer, and a feed that says something odd has to be ignored rather than
 * followed. The app downloads what this file says, so the second one
 * matters more than the first.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.UPSIDE_DOWN_CAKE])
class AppUpdateTest {

    private val feed = """
        {
          "versionName": "1.4.1",
          "versionCode": 146,
          "notes": "The app can now tell you when there is a newer build.",
          "apkUrl": "https://example.com/AutoSongs-1.4.1.apk",
          "sha256": "abc123",
          "published": "2026-10-30T21:00:00Z",
          "hosts": ["https://example.com", "https://backup.example.com"]
        }
    """.trimIndent()

    @Test
    fun aFeedIsRead() {
        val release = AppUpdate.parse(feed)
        assertNotNull(release)
        assertEquals("1.4.1", release!!.versionName)
        assertEquals(146, release.versionCode)
        assertEquals("https://example.com/AutoSongs-1.4.1.apk", release.apkUrl)
        assertEquals("abc123", release.sha256)
        assertEquals(2, release.hosts.size)
    }

    @Test
    fun aNewerBuildIsRecognised() {
        val release = AppUpdate.parse(feed)!!
        assertTrue(AppUpdate.isNewer(release, 145))
        assertFalse(AppUpdate.isNewer(release, 146))
        assertFalse(AppUpdate.isNewer(release, 147))
    }

    @Test
    fun nonsenseIsIgnored() {
        // A feed that is not a feed must not be followed.
        assertNull(AppUpdate.parse(""))
        assertNull(AppUpdate.parse("not json at all"))
        assertNull(AppUpdate.parse("{}"))
        assertNull(AppUpdate.parse("[]"))
    }

    @Test
    fun aFeedWithoutABuildNumberIsIgnored() {
        assertNull(AppUpdate.parse("""{"apkUrl":"https://example.com/a.apk"}"""))
        assertNull(AppUpdate.parse("""{"versionCode":0,"apkUrl":"https://example.com/a.apk"}"""))
    }

    @Test
    fun aFeedWithAnUnsafeAddressIsIgnored() {
        // Only https is accepted. A plain http address would let anyone on
        // the network swap the file that gets downloaded.
        assertNull(AppUpdate.parse("""{"versionCode":146,"apkUrl":"http://example.com/a.apk"}"""))
        assertNull(AppUpdate.parse("""{"versionCode":146,"apkUrl":"file:///sdcard/a.apk"}"""))
    }

    @Test
    fun theDownloadIsFoundNextToTheFeed() {
        // The hosting gives a new address for every release, so the feed
        // does not say where the download is. The app works it out from
        // the address the feed itself came from, which keeps the feed
        // right wherever it is published.
        val release = AppUpdate.parse(
            """{"versionName":"1.4.1","versionCode":146}""",
            "https://example.com/version.json"
        )!!
        assertEquals("https://example.com/AutoSongs-1.4.1.apk", release.apkUrl)
    }

    @Test
    fun aFeedWithoutAnAddressOrAPlaceToLookIsIgnored() {
        assertNull(AppUpdate.parse("""{"versionName":"1.4.1","versionCode":146}"""))
    }

    @Test
    fun hostsThatAreNotAddressesAreDropped() {
        val release = AppUpdate.parse(
            """{"versionCode":146,"apkUrl":"https://example.com/a.apk",
                "hosts":["https://ok.example.com","http://insecure.example.com",""]}"""
        )!!
        assertEquals(1, release.hosts.size)
        assertEquals("https://ok.example.com", release.hosts[0])
    }
}
