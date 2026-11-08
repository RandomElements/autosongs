package com.autosongs.ytdl.audio

import android.util.Log

/**
 * The MP3 encoder that lives inside the app.
 *
 * Android can decode MP3 but cannot produce one: MediaCodec has an MP3
 * decoder and no MP3 encoder, so with the platform alone there is no way
 * to re-encode anything to MP3. So the app carries LAME - a small LGPL
 * library, about 400 KB per device type - and calls it through a thin
 * JNI layer. The whole thing is about 1.5 MB for the three device types
 * the app supports, against the 30 MB that bundling all of ffmpeg would
 * cost.
 *
 * Nothing here talks to the network. The sound is decoded on the phone and
 * encoded on the phone.
 *
 * **This is an object on purpose.** The system finds a native method by
 * name: `Java_<the class that declares it>_<the method>`. A companion
 * object would declare the methods in `LameEncoder$Companion`, and the
 * library - which exports the plain name - would never be called. The
 * app would then simply stop making mp3s, with nothing to say why.
 * `LameEncoderBindingTest` keeps an eye on this.
 */
object LameEncoder {

    private const val TAG = "LameEncoder"

    /** The open encoder, if there is one. */
    private var handle = 0L

    private var tried = false
    private var ok = false
    private var why = ""

    /** True when this phone can make MP3s. */
    fun available(): Boolean {
        if (!tried) {
            tried = true
            ok = try {
                System.loadLibrary("mp3lame")
                true
            } catch (t: Throwable) {
                // A phone without the library for its own device type
                // still works for everything else - but the reason is
                // worth keeping, because otherwise the app can only say
                // "the encoder did not work" and nobody learns anything.
                why = "${t.javaClass.simpleName}: ${t.message ?: "no detail"}"
                Log.w(TAG, "the mp3 encoder did not load: $why")
                false
            }
        }
        return ok
    }

    /** Why the encoder could not be loaded, if it could not be. */
    fun loadError(): String = why

    /**
     * Opens an encoder.
     *
     * Returns null when this phone cannot make MP3s, when the sample
     * rate is one LAME does not know, or when the file has more than
     * two channels - music does not, but a surround mix would.
     */
    fun open(
        sampleRate: Int,
        channels: Int,
        bitrate: Int = 192,
        title: String? = null,
        artist: String? = null,
        album: String? = null,
        artwork: ByteArray? = null
    ): LameEncoder? {
        if (!available()) return null
        if (sampleRate < 8000 || sampleRate > 48000) return null
        if (channels < 1 || channels > 2) return null
        close()
        val opened = nativeOpen(
            sampleRate, channels, bitrate, title, artist, album, artwork
        )
        if (opened == 0L) return null
        handle = opened
        return this
    }

    external fun nativeOpen(
        sampleRate: Int,
        channels: Int,
        bitrate: Int,
        title: String?,
        artist: String?,
        album: String?,
        artwork: ByteArray?
    ): Long

    external fun nativeEncode(
        handle: Long,
        pcm: ShortArray,
        samples: Int
    ): ByteArray

    external fun nativeFlush(handle: Long): ByteArray

    external fun nativeId3Tag(handle: Long): ByteArray

    external fun nativeClose(handle: Long)

    /** Encodes one buffer of samples and returns the MP3 bytes. */
    fun encode(pcm: ShortArray, samples: Int): ByteArray =
        if (handle == 0L) ByteArray(0) else nativeEncode(handle, pcm, samples)

    /** The ID3 tag that goes at the front of the file. */
    fun tag(): ByteArray = if (handle == 0L) ByteArray(0) else nativeId3Tag(handle)

    /** Finishes the file and returns the last bytes. */
    fun finish(): ByteArray = if (handle == 0L) ByteArray(0) else nativeFlush(handle)

    /** Closes the encoder. Safe to call more than once. */
    fun close() {
        if (handle != 0L) {
            nativeClose(handle)
            handle = 0L
        }
    }
}
