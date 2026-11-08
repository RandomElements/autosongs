package com.autosongs.ytdl

import com.autosongs.ytdl.embedded.YtDlpUpdater
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The comparison that decides whether yt-dlp is out of date.
 *
 * The versions are dates, so they have to be compared as numbers. As text,
 * "2026.10.26" comes before "2026.08.19" and the app would think a new
 * yt-dlp was an old one - which is exactly the bug that let a four-month
 * old yt-dlp stay on the phone and fail every download with a 403.
 */
class YtDlpVersionTest {

    @Test
    fun anOlderVersionIsRecognised() {
        assertTrue(YtDlpUpdater.isOlder("2026.06.09", "2026.10.26"))
    }

    @Test
    fun theSameVersionIsNotOlder() {
        assertFalse(YtDlpUpdater.isOlder("2026.10.26", "2026.10.26"))
    }

    @Test
    fun aNewerVersionIsNotOlder() {
        assertFalse(YtDlpUpdater.isOlder("2026.10.26", "2026.06.09"))
    }

    @Test
    fun octoberIsNewerThanAugust() {
        // The trap: as text, "2026.10.26" < "2026.08.19".
        assertTrue(YtDlpUpdater.isOlder("2026.08.19", "2026.10.26"))
        assertFalse(YtDlpUpdater.isOlder("2026.10.26", "2026.08.19"))
    }

    @Test
    fun theYearIsComparedToo() {
        assertTrue(YtDlpUpdater.isOlder("2025.12.31", "2026.01.01"))
        assertFalse(YtDlpUpdater.isOlder("2026.01.01", "2025.12.31"))
    }

    @Test
    fun anOddVersionIsIgnored() {
        // An unknown version must not make the app think it is out of date
        // and download something for nothing.
        assertFalse(YtDlpUpdater.isOlder("", "2026.10.26"))
        assertFalse(YtDlpUpdater.isOlder("unknown", "2026.10.26"))
        assertFalse(YtDlpUpdater.isOlder("2026.10", "2026.10.26"))
        assertFalse(YtDlpUpdater.isOlder("nightly", "2026.10.26"))
    }

    @Test
    fun theVersionThePhoneHadIsOlderThanTheNewest() {
        // The real case: the phone was running this, and every download
        // failed with a 403.
        assertTrue(YtDlpUpdater.isOlder("2026.06.09", "2026.08.19"))
    }
}
