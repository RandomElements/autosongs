package com.autosongs.ytdl

import com.autosongs.ytdl.bridge.CookieStore
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The cookie jar the user picks has to be recognised as a jar.
 *
 * A file that is not one would make every download fail in a way that is
 * much harder to explain than "that is not a cookies.txt file" - so the
 * check happens when the jar is picked, not when it is used.
 */
class CookieStoreTest {

    @Test
    fun aRealJarIsRecognised() {
        assertTrue(CookieStore.looksLikeAJar(
            "# Netscape HTTP Cookie File\n" +
                ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n"))
    }

    @Test
    fun aJarWithOnlyHttpOnlyLinesIsRecognised() {
        // Some browsers export a jar whose first line is a cookie rather
        // than the header comment.
        assertTrue(CookieStore.looksLikeAJar(
            "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n"))
    }

    @Test
    fun somethingElseIsNotAJar() {
        assertFalse(CookieStore.looksLikeAJar("hello"))
        assertFalse(CookieStore.looksLikeAJar(""))
        assertFalse(CookieStore.looksLikeAJar("<html><body>not a jar</body></html>"))
    }

    @Test
    fun aJarIsRecognisedAmongOtherLines() {
        // The header is not always the first line.
        assertTrue(CookieStore.looksLikeAJar(
            "some note somebody wrote\n" +
                "# Netscape HTTP Cookie File\n" +
                ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n"))
    }
}
