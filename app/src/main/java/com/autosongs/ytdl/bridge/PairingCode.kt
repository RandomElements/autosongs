package com.autosongs.ytdl.bridge

import java.io.ByteArrayOutputStream

/**
 * The code the bridge shows, and the user types in here.
 *
 * The bridge prints one code. It carries where the bridge is and the key
 * the two share, so the user types one thing instead of a host, a port and
 * a token - and cannot get one of them wrong.
 *
 * The letters I, L, O and U are not in the alphabet, because those are the
 * ones people mistype.
 *
 * The code is:
 *
 *     the version, the kind, the address, the port, the key, a checksum
 *
 * all in base32, in groups of five.
 */
object PairingCode {

    private const val ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    /**
     * What the code says: where the bridge is, and the key to it.
     *
     * @param scheme "http" for a bridge on the same network, "https" for
     *   one that is reached over a tunnel. A tunnel gives out an https
     *   address, and the phone has to use the same one the tunnel does -
     *   connecting to it over plain http would not reach it at all.
     * @param path a prefix under the address, for a tunnel that forwards
     *   under a path rather than at the root.
     */
    data class Pairing(
        val host: String,
        val port: Int,
        val token: String,
        val scheme: String = "http",
        val path: String = ""
    )

    /**
     * Reads a code the bridge showed.
     *
     * @throws IllegalArgumentException when the code is not one of ours,
     *   or has been typed wrong. The message is meant to be shown to the
     *   user as it is.
     */
    fun parse(text: String): Pairing {
        val body = decode(text)
        if (body.size < 15) {
            throw IllegalArgumentException("That code is too short")
        }
        var sum = 0
        for (i in 0 until body.size - 1) sum += body[i]
        if ((sum and 0xFF) != (body.last().toInt() and 0xFF)) {
            throw IllegalArgumentException(
                "That code has a letter wrong, or a dash missing"
            )
        }
        if ((body[0].toInt() and 0xFF) != 1) {
            throw IllegalArgumentException(
                "That code is from a newer version of AutoSongs"
            )
        }

        val kind = body[1].toInt() and 0xFF
        var index = 2
        var scheme = "http"
        var path = ""
        val host: String
        if (kind == 4) {
            host = (2..5).joinToString(".") { (body[it].toInt() and 0xFF).toString() }
            index = 6
        } else if (kind == 6) {
            val length = body[2].toInt() and 0xFF
            host = String(body, 3, length, Charsets.UTF_8)
            index = 3 + length
        } else if (kind == 7) {
            // A bridge that is reached over the internet. The code
            // carries the whole address - the scheme, the host and any
            // path - because there is no network for the phone to ask.
            scheme = if ((body[2].toInt() and 0xFF) == 1) "https" else "http"
            val length = body[3].toInt() and 0xFF
            host = String(body, 4, length, Charsets.UTF_8)
            index = 4 + length
            val port = ((body[index].toInt() and 0xFF) shl 8) or
                (body[index + 1].toInt() and 0xFF)
            index += 2
            val pathLength = body[index].toInt() and 0xFF
            path = String(body, index + 1, pathLength, Charsets.UTF_8)
            index += 1 + pathLength
            val secret = body.copyOfRange(index, body.size - 1)
            val token = secret.joinToString("") { "%02X".format(it) }
            return Pairing(host, port, token, scheme, path)
        } else {
            throw IllegalArgumentException("That code is not one of ours")
        }

        val port = ((body[index].toInt() and 0xFF) shl 8) or
            (body[index + 1].toInt() and 0xFF)
        val secret = body.copyOfRange(index + 2, body.size - 1)
        val token = secret.joinToString("") { "%02X".format(it) }
        return Pairing(host, port, token, scheme, path)
    }

    private fun decode(text: String): ByteArray {
        val out = ByteArrayOutputStream()
        var value = 0
        var bits = 0
        for (ch in text.trim().uppercase()) {
            if (ch == '-' || ch == ' ' || ch == '\t') continue
            val index = ALPHABET.indexOf(ch)
            if (index < 0) {
                throw IllegalArgumentException(
                    "That code has a letter that is not in it"
                )
            }
            value = (value shl 5) or index
            bits += 5
            if (bits >= 8) {
                bits -= 8
                out.write((value shr bits) and 0xFF)
                // Throw the bits away once they have been used, so what is
                // left is always the group still to come.
                value = value and ((1 shl bits) - 1)
            }
        }
        return out.toByteArray()
    }
}
