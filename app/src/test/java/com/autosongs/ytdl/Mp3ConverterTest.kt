package com.autosongs.ytdl

import com.autosongs.ytdl.audio.Mp3Converter
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The mp3 encoder on the phone.
 *
 * The encoder itself is native code, so it cannot run in a unit test. What
 * can be checked here is that the app behaves when it is not there, and
 * that nothing throws at the user.
 */
class Mp3ConverterTest {

    @Test
    fun aMissingFileIsReportedRatherThanCrashing() {
        val result = Mp3Converter.convert(
            File("/does/not/exist.m4a"),
            File("/tmp/autosongs-test-out.mp3"),
            "Title", "Artist", "Album"
        )
        assertFalse(result.ok)
        assertTrue(result.reason.isNotBlank())
    }

    @Test
    fun thereIsNoCoverWithoutAPicture() {
        assertNull(Mp3Converter.artworkBytes(null))
    }
}
