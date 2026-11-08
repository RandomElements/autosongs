package com.autosongs.ytdl.media

import java.io.File

/**
 * Checks that what came back from the bridge is actually media.
 *
 * This exists because of a real bug: an older bridge fell back to "any
 * recently written file" when a download produced nothing, and the file it
 * found was the bridge script itself (`ytbridge.py`). The app happily saved
 * it as "Artist - Title.py.mp3" - a Python script with a song's name.
 *
 * A file name is not enough of a check, because the name comes from the same
 * untrusted source. The magic bytes are.
 */
object MediaSniffer {

    /** Reads the head of [file] and decides whether it is media. */
    fun looksLikeMedia(file: File): Boolean {
        val head = ByteArray(16)
        val read = try {
            file.inputStream().use { it.read(head) }
        } catch (t: Throwable) {
            return false
        }
        if (read < 4) return false
        return looksLikeMedia(head.copyOf(read))
    }

    /** True when [head] starts with a known media container signature. */
    fun looksLikeMedia(head: ByteArray): Boolean {
        if (head.size < 4) return false

        fun ascii(offset: Int, len: Int): String =
            String(head, offset, len, Charsets.US_ASCII)

        // ISO base media: mp4, m4a, mov, 3gp - "ftyp" at offset 4.
        if (head.size >= 8 && ascii(4, 4) == "ftyp") return true

        // Matroska / WebM - EBML magic.
        if (head[0] == 0x1A.toByte() && head[1] == 0x45.toByte() &&
            head[2] == 0xDF.toByte() && head[3] == 0xA3.toByte()
        ) return true

        // Ogg container: opus, ogg, vorbis.
        if (ascii(0, 4) == "OggS") return true

        // MP3 with an ID3v2 tag.
        if (ascii(0, 3) == "ID3") return true

        // Raw MP3 frame sync (11 set bits).
        if (head[0] == 0xFF.toByte() && (head[1].toInt() and 0xE0) == 0xE0) return true

        // RIFF container: wav, avi.
        if (ascii(0, 4) == "RIFF") return true

        // FLAC.
        if (ascii(0, 4) == "fLaC") return true

        return false
    }
}
