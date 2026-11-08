package com.autosongs.ytdl

import com.autosongs.ytdl.video.VideoMuxer
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The video joiner.
 *
 * Joining really needs Android's own MediaMuxer, which cannot run in a
 * unit test. What can be checked here is the part that must never go
 * wrong: a missing piece has to be reported, not written out as a broken
 * file.
 */
class VideoMuxerTest {

    @Test
    fun aMissingPictureIsReported() {
        val out = File.createTempFile("autosongs", ".mp4")
        out.delete()
        val outcome = VideoMuxer.mux(
            File("/does/not/exist.mp4"),
            File("/does/not/exist.m4a"),
            out
        )
        assertFalse(outcome.ok)
        assertTrue(outcome.reason.isNotBlank())
    }

    @Test
    fun anEmptySoundIsReported() {
        val out = File.createTempFile("autosongs", ".mp4")
        out.delete()
        val picture = File.createTempFile("autosongs-picture", ".mp4")
        val sound = File.createTempFile("autosongs-sound", ".m4a")
        sound.writeBytes(ByteArray(0))
        val outcome = VideoMuxer.mux(picture, sound, out)
        assertFalse(outcome.ok)
        picture.delete()
        sound.delete()
    }
}
