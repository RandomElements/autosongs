package com.autosongs.ytdl.bridge

import java.security.MessageDigest

/**
 * The eight-character code the bridge shows on its screen.
 *
 * The user types that one code into the app, and the app works out the
 * rest by itself: where the bridge is, and the key the two share.
 *
 * The letters I, L, O and U are not in the alphabet, because those are the
 * ones people mistype.
 */
object PairCode {

    private const val ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    /**
     * The code as it looks after someone has typed it.
     *
     * The dashes and spaces go. Everything else has to be in the alphabet -
     * a letter that is not in it is reported, not quietly dropped. A code
     * that was read wrong must not become a different code.
     *
     * @throws IllegalArgumentException when the code has a letter that is
     *   not in it. The message is meant to be shown to the user as it is.
     */
    fun normalize(text: String): String {
        val out = StringBuilder()
        for (ch in text.uppercase()) {
            when {
                ch == '-' || ch == ' ' || ch == '\t' -> Unit
                ALPHABET.indexOf(ch) >= 0 -> out.append(ch)
                else -> throw IllegalArgumentException(
                    "That code has a letter that is not in it"
                )
            }
        }
        return out.toString()
    }

    /**
     * A fingerprint of the code.
     *
     * The bridge answers with this instead of the code itself, so hearing
     * the answer on the network does not let anyone else in.
     */
    fun fingerprint(code: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(normalize(code).toByteArray(Charsets.US_ASCII))
        val hex = StringBuilder()
        for (byte in digest) {
            hex.append("%02x".format(byte.toInt() and 0xFF))
        }
        return hex.substring(0, 16)
    }
}
