package com.autosongs.ytdl

import com.autosongs.ytdl.bridge.PairCode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The eight-character code the bridge shows.
 *
 * The bridge has its own copy of this in Python. If the two ever disagree
 * about how a code is read, the phone cannot pair with anything - so the
 * same code is checked here against the same number the bridge produces.
 */
class PairCodeTest {

    @Test
    fun aCodeIsEightCharacters() {
        assertEquals(8, PairCode.normalize("72D2BXEH").length)
    }

    @Test
    fun aCodeIsReadTheSameEitherWay() {
        val code = "72D2BXEH"
        assertEquals(code, PairCode.normalize(code))
        assertEquals(code, PairCode.normalize(code.lowercase()))
        assertEquals(code, PairCode.normalize(" 72d2bxeh "))
        assertEquals(code, PairCode.normalize("72D2-BXEH"))
    }

    @Test
    fun aLetterThatIsNotInTheAlphabetIsReported() {
        // I, L, O and U are not in the alphabet, because people mistype
        // them. A code that was read wrong must not turn into a different
        // code.
        for (letter in listOf("I", "L", "O", "U")) {
            var failed = false
            try {
                PairCode.normalize("ABCDEFG$letter")
            } catch (e: IllegalArgumentException) {
                failed = true
            }
            assertTrue("the letter $letter must be reported", failed)
        }
    }

    @Test
    fun theFingerprintIsTheSameOneTheBridgeGives() {
        // The bridge answers with this, so a phone can check a code
        // without the code ever going out over the network.
        assertEquals("5b5bc7dd51a02837", PairCode.fingerprint("72D2BXEH"))
    }

    @Test
    fun theFingerprintIsSixteenHexCharacters() {
        val print = PairCode.fingerprint("72D2BXEH")
        assertEquals(16, print.length)
        assertTrue(print.all { it in "0123456789abcdef" })
    }
}
