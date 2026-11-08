package com.autosongs.ytdl

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The mp3 encoder has to be wired up correctly, and there is no way to
 * find out on a phone until a track is saved as something else.
 *
 * The native methods are found by name: the system looks for
 * `Java_<class>_<method>`, and the class is the one that *declares* them.
 * A companion object changes that name - the methods would live in
 * `LameEncoder$Companion` and the library, which exports the plain name,
 * would never be called. Nothing would say so: the app would simply stop
 * making mp3s.
 *
 * So the names are checked here, before anything is published.
 */
class LameEncoderBindingTest {

    private val library = File("src/main/jniLibs/arm64-v8a/libmp3lame.so")
    private val source = File("src/main/java/com/autosongs/ytdl/audio/LameEncoder.kt")

    private val methods = listOf(
        "nativeOpen", "nativeEncode", "nativeFlush", "nativeId3Tag", "nativeClose"
    )

    @Test
    fun theLibraryIsThere() {
        assertTrue("the encoder library is missing: $library", library.exists())
        assertTrue("the encoder library is empty", library.length() > 1000)
    }

    @Test
    fun theLibraryExportsEveryNameTheAppCalls() {
        val text = String(library.readBytes(), Charsets.ISO_8859_1)
        for (method in methods) {
            val symbol = "Java_com_autosongs_ytdl_audio_LameEncoder_$method"
            assertTrue("the library does not export $symbol", text.contains(symbol))
        }
    }

    @Test
    fun theLibraryDoesNotExportTheCompanionName() {
        val text = String(library.readBytes(), Charsets.ISO_8859_1)
        assertFalse(
            "the library exports a companion-object name, which the app " +
                "would never call",
            text.contains("LameEncoder_Companion")
        )
    }

    @Test
    fun theEncoderIsASingleton() {
        assertTrue("the encoder should be an object, so the native methods " +
            "are declared in LameEncoder itself",
            source.readText().contains("object LameEncoder"))
    }

    @Test
    fun theNativeMethodsAreNotInACompanionObject() {
        assertTrue("the encoder source is missing", source.exists())
        val text = source.readText()
        assertFalse(
            "the native methods are in a companion object, so the system " +
                "would look for a name the library does not export",
            text.contains("companion object")
        )
    }
}
