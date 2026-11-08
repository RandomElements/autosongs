package com.autosongs.ytdl.audio

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.SystemClock
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteOrder

/**
 * Turns an audio file into an MP3, on the phone.
 *
 * The sound is decoded with MediaCodec - the decoder every phone already
 * has and does in hardware - and encoded with LAME. Nothing is uploaded
 * anywhere, and nothing is asked of the user: this is what the app does
 * with a track it has already fetched.
 *
 * YouTube hands over AAC in an MP4 wrapper, and Android plays that
 * natively, so converting is only worth doing when somebody asks for
 * MP3 - an old car stereo, an old player, a file manager that shows
 * "unknown format".
 */
object Mp3Converter {

    private const val TAG = "Mp3Converter"

    /** How long to wait for the decoder before giving up on a buffer. */
    private const val TIMEOUT_US = 10_000L

    /** How long the whole decode may take before it is called off. */
    private const val DEADLINE_MS = 180_000L

    /** What happened. */
    data class Result(
        val ok: Boolean,
        val reason: String = "",
        val bytes: Long = 0L
    )

    /**
     * The cover picture for the mp3's tag, as JPEG bytes.
     *
     * It is shrunk first: a full size cover would add a hundred kilobytes
     * to every single track, and nobody looks at a cover that big.
     */
    fun artworkBytes(bitmap: android.graphics.Bitmap?): ByteArray? {
        if (bitmap == null) return null
        return try {
            val size = 256
            val scaled = if (bitmap.width > size || bitmap.height > size) {
                val scale = size.toFloat() / maxOf(bitmap.width, bitmap.height)
                android.graphics.Bitmap.createScaledBitmap(
                    bitmap,
                    (bitmap.width * scale).toInt().coerceAtLeast(1),
                    (bitmap.height * scale).toInt().coerceAtLeast(1),
                    true
                )
            } else {
                bitmap
            }
            java.io.ByteArrayOutputStream().use { out ->
                scaled.compress(android.graphics.Bitmap.CompressFormat.JPEG, 88, out)
                out.toByteArray()
            }
        } catch (_: Throwable) {
            // A cover is a nice thing to have, not a reason to fail.
            null
        }
    }

    /**
     * Fetches a cover picture from the internet.
     *
     * The media session usually has the album art, and that is the first
     * choice. When it does not - a session is free to keep its art to
     * itself - the bridge knows the address of the picture, and the
     * phone can go and get it. A cover is a small picture, so this is
     * quick, and it is never worth failing a download over.
     */
    fun artworkFromUrl(url: String): ByteArray? {
        if (url.isBlank()) return null
        return try {
            val connection = (java.net.URL(url).openConnection()
                    as java.net.HttpURLConnection).apply {
                connectTimeout = 8000
                readTimeout = 8000
                instanceFollowRedirects = true
                requestMethod = "GET"
            }
            try {
                if (connection.responseCode !in 200..299) return null
                val bytes = connection.inputStream.use { it.readBytes() }
                if (bytes.isEmpty()) null else bytes
            } finally {
                connection.disconnect()
            }
        } catch (_: Throwable) {
            null
        }
    }

    /**
     * Tries the encoder with a tone the app makes itself.
     *
     * It needs no file and no network, so it answers exactly one question:
     * does the encoder inside the app work on this phone. The settings
     * screen has a button for it, because a phone that cannot encode is
     * worth finding out about before a track is saved as something else.
     */
    fun testEncoder(): String {
        if (!LameEncoder.available()) {
            return "The encoder did not load: ${LameEncoder.loadError()}"
        }
        val rate = 44100
        val frames = rate // one second
        val samples = ShortArray(frames * 2)
        for (i in 0 until frames) {
            val value = (Math.sin(2.0 * Math.PI * 440.0 * i / rate) * 12000.0).toInt().toShort()
            samples[i * 2] = value
            samples[i * 2 + 1] = value
        }
        return try {
            val encoder = LameEncoder.open(rate, 2, 128, "Test", "AutoSongs", "Test")
                ?: return "The encoder refused to start"
            var bytes = encoder.tag().size
            bytes += encoder.encode(samples, samples.size).size
            bytes += encoder.finish().size
            encoder.close()
            if (bytes < 1024) {
                "The encoder produced only $bytes bytes - something is wrong with it"
            } else {
                "The encoder works: $bytes bytes of mp3 from one second of sound"
            }
        } catch (t: Throwable) {
            "The encoder failed: ${t.javaClass.simpleName}: ${t.message}"
        }
    }

    /**
     * Converts an audio file to MP3.
     *
     * The output file is only written when the whole thing worked, so a
     * half-finished mp3 never reaches the music library.
     */
    fun convert(
        input: File,
        output: File,
        title: String,
        artist: String,
        album: String,
        artwork: ByteArray? = null,
        bitrate: Int = 192
    ): Result {
        if (!LameEncoder.available()) {
            return Result(false, "the encoder did not load: ${LameEncoder.loadError()}")
        }
        if (!input.exists() || input.length() == 0L) {
            return Result(false, "the downloaded file is empty")
        }

        val extractor = MediaExtractor()
        var track = -1
        var mime = ""
        try {
            extractor.setDataSource(input.absolutePath)
            for (i in 0 until extractor.trackCount) {
                val format = extractor.getTrackFormat(i)
                val type = format.getString(MediaFormat.KEY_MIME) ?: continue
                if (type.startsWith("audio/")) {
                    track = i
                    mime = type
                    break
                }
            }
        } catch (t: Throwable) {
            return Result(false, "the file could not be opened: ${t.message}")
        }
        if (track < 0) {
            return Result(false, "there is no sound in that file")
        }

        var decoder: MediaCodec? = null
        var encoder: LameEncoder? = null
        var written = 0L
        try {
            extractor.selectTrack(track)
            decoder = MediaCodec.createDecoderByType(mime)
            decoder.configure(extractor.getTrackFormat(track), null, null, 0)
            decoder.start()

            val bufferInfo = MediaCodec.BufferInfo()
            var inputDone = false
            var outputDone = false
            var scratch = ShortArray(0)
            val started = SystemClock.elapsedRealtime()

            FileOutputStream(output).use { out ->
                while (!outputDone) {
                    if (SystemClock.elapsedRealtime() - started > DEADLINE_MS) {
                        return Result(false, "the decoder took too long and was stopped")
                    }

                    if (!inputDone) {
                        val inIndex = decoder.dequeueInputBuffer(TIMEOUT_US)
                        if (inIndex >= 0) {
                            val inBuffer = decoder.getInputBuffer(inIndex)
                            if (inBuffer != null) {
                                val size = extractor.readSampleData(inBuffer, 0)
                                if (size < 0) {
                                    decoder.queueInputBuffer(
                                        inIndex, 0, 0, 0,
                                        MediaCodec.BUFFER_FLAG_END_OF_STREAM
                                    )
                                    inputDone = true
                                } else {
                                    decoder.queueInputBuffer(
                                        inIndex, 0, size, extractor.sampleTime, 0
                                    )
                                    extractor.advance()
                                }
                            }
                        }
                    }

                    val outIndex = decoder.dequeueOutputBuffer(bufferInfo, TIMEOUT_US)
                    when {
                        outIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                            val format = decoder.outputFormat
                            val sampleRate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                            val channels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                            encoder = LameEncoder.open(
                                sampleRate, channels, bitrate,
                                title, artist, album, artwork
                            )
                            if (encoder == null) {
                                return Result(
                                    false,
                                    "the encoder could not start for ${sampleRate}Hz " +
                                        "${channels}ch sound"
                                )
                            }
                            out.write(encoder!!.tag())
                        }

                        outIndex >= 0 -> {
                            val outBuffer = decoder.getOutputBuffer(outIndex)
                            if (outBuffer != null && bufferInfo.size > 0 && encoder != null) {
                                outBuffer.position(bufferInfo.offset)
                                outBuffer.limit(bufferInfo.offset + bufferInfo.size)
                                // The sound in a MediaCodec buffer is in the
                                // phone's own byte order, which is little
                                // endian. The default order of a buffer is
                                // big endian, so without this the music would
                                // be noise.
                                val shorts = outBuffer.duplicate()
                                    .order(ByteOrder.LITTLE_ENDIAN)
                                    .asShortBuffer()
                                val count = shorts.remaining()
                                if (count > 0) {
                                    if (scratch.size < count) scratch = ShortArray(count)
                                    shorts.get(scratch, 0, count)
                                    // The values in the buffer are handed
                                    // over as they are. The encoder counts
                                    // the frames itself - it is the only
                                    // place that knows what LAME wants, and
                                    // getting it wrong there makes every
                                    // track twice as long and full of noise.
                                    val bytes = encoder!!.encode(scratch, count)
                                    if (bytes.isNotEmpty()) {
                                        out.write(bytes)
                                        written += bytes.size
                                    }
                                }
                            }
                            decoder.releaseOutputBuffer(outIndex, false)
                            if (bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                                outputDone = true
                            }
                        }
                    }
                }

                val tail = encoder?.finish() ?: ByteArray(0)
                if (tail.isNotEmpty()) {
                    out.write(tail)
                    written += tail.size
                }
            }

            encoder?.close()
            if (written < 1024L) {
                output.delete()
                return Result(false, "the encoder produced nothing")
            }
            return Result(true, bytes = written)
        } catch (t: Throwable) {
            Log.w(TAG, "the conversion failed", t)
            output.delete()
            return Result(false, "the conversion failed: ${t.message ?: t.javaClass.simpleName}")
        } finally {
            try {
                decoder?.stop()
            } catch (_: Throwable) {
            }
            try {
                decoder?.release()
            } catch (_: Throwable) {
            }
            try {
                extractor.release()
            } catch (_: Throwable) {
            }
            try {
                encoder?.close()
            } catch (_: Throwable) {
            }
        }
    }
}
