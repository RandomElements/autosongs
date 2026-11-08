package com.autosongs.ytdl

import com.autosongs.ytdl.bridge.BridgeHealth
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The message the user sees when the bridge reports an yt-dlp that is too
 * old for YouTube.
 *
 * This is the most common cause of a failed download and the one that looks
 * least like a version problem, so the app has to name it.
 */
class YtDlpVersionMessageTest {

    private val health = """
        {"ok": true, "yt_dlp": "2026.06.09", "yt_dlp_outdated": true,
         "yt_dlp_min": "2026.08.19", "cookies": false, "ffmpeg": true}
    """.trimIndent()

    @Test
    fun anOldYtDlpIsExplained() {
        val msg = BridgeHealth.outdatedYtDlpMessage(health)
        assertNotNull("the app must explain an outdated yt-dlp", msg)
        assertTrue(msg!!.contains("2026.06.09"))
        assertTrue(msg.contains("2026.08.19"))
        assertTrue("the message must name the symptom: $msg", msg.contains("403"))
    }

    @Test
    fun aCurrentYtDlpIsNotMentioned() {
        val good = """
            {"ok": true, "yt_dlp": "2026.10.26", "yt_dlp_outdated": false,
             "yt_dlp_min": "2026.08.19"}
        """.trimIndent()
        assertNull(BridgeHealth.outdatedYtDlpMessage(good))
    }

    @Test
    fun aMissingHealthAnswerIsNotMentioned() {
        assertNull(BridgeHealth.outdatedYtDlpMessage(null))
        assertNull(BridgeHealth.outdatedYtDlpMessage(""))
    }

    @Test
    fun anOlderBridgeWithoutTheFieldIsNotMentioned() {
        // A bridge that does not know about the field must not crash the app.
        val old = """{"ok": true, "yt_dlp": "2026.06.09"}"""
        assertNull(BridgeHealth.outdatedYtDlpMessage(old))
    }

    @Test
    fun theMessageSaysWhatToDo() {
        val msg = BridgeHealth.outdatedYtDlpMessage(health)!!
        assertTrue("the message must tell the user to run the setup: $msg",
            msg.contains("Termux"))
    }
}
