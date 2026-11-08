package com.autosongs.ytdl

import com.autosongs.ytdl.bridge.PairingCode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * The code the bridge shows, and the phone reads.
 *
 * These strings were made by the bridge itself, so if the two halves ever
 * stop agreeing the test says so. A phone paired with a garbled code looks
 * exactly like a bridge that is not answering, and the user has no way to
 * tell the difference.
 */
class PairingCodeTest {

    @Test
    fun anAddressAndAKeyComeOutOfTheCode() {
        val pairing = PairingCode.parse("042C1-A0168-H3V8D-JRFAE-BXP4")
        assertEquals("192.168.1.50", pairing.host)
        assertEquals(8765, pairing.port)
        assertEquals("TESTSECRET", pairing.token)
    }

    @Test
    fun aNameWorksToo() {
        val pairing = PairingCode.parse(
            "0430J-VK1EC-Q6RVV-3C5P2-6A002-4H36H-2NCSV-V4"
        )
        assertEquals("nas.local", pairing.host)
        assertEquals(9000, pairing.port)
        assertEquals("0011223344556677", pairing.token)
    }

    @Test
    fun spacesAndMissingDashesAreForgiven() {
        val pairing = PairingCode.parse("042C1A0168H3V8DJRFAEBXP4")
        assertEquals("192.168.1.50", pairing.host)
        assertEquals(8765, pairing.port)
    }

    @Test
    fun aWrongLetterIsCaught() {
        val code = "042C1-A0168-H3V8D-JRFAE-BXP4".toCharArray()
        code[3] = if (code[3] == 'X') 'Y' else 'X'
        try {
            PairingCode.parse(String(code))
            fail("a code with a letter wrong must not be accepted")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message.orEmpty().contains("letter"))
        }
    }

    @Test
    fun rubbishIsNotACode() {
        for (rubbish in listOf("", "hello", "1234", "A-B-C")) {
            try {
                PairingCode.parse(rubbish)
                fail("\"$rubbish\" must not be accepted as a code")
            } catch (_: IllegalArgumentException) {
                // good
            }
        }
    }

    @Test
    fun theLettersPeopleMistypeAreNotInTheCode() {
        val code = PairingCode.parse("042C1-A0168-H3V8D-JRFAE-BXP4")
        assertTrue(code.token.none { it == 'I' || it == 'L' || it == 'O' || it == 'U' })
    }
}
