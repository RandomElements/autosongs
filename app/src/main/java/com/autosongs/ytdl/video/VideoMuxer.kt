package com.autosongs.ytdl.video

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.util.Log
import java.io.File
import java.nio.ByteBuffer

/**
 * Joins a picture and a sound into one video.
 *
 * Android can do this by itself: [MediaMuxer] writes the two tracks into an
 * mp4 without touching the samples - nothing is decoded and nothing is
 * encoded. So a video downloaded inside the app does not need ffmpeg: the
 * bridge hands over the picture and the sound as two files, and the phone
 * joins them here.
 *
 * ffmpeg exists on desktops mostly because desktops have nothing like this.
 */
object VideoMuxer {

    private const val TAG = "VideoMuxer"

    /** How a join ended: it worked, or this is why it did not. */
    data class Outcome(val ok: Boolean, val reason: String = "")

    /** A video sample is at most a few hundred kilobytes, usually far less. */
    private const val SAMPLE_BUFFER = 4 * 1024 * 1024

    /**
     * Joins [video] and [audio] into [output].
     *
     * Nothing is written to [output] unless the join works: the file is
     * only made when the muxer is ready, so a half-joined video never
     * reaches the music library.
     */
    fun mux(video: File, audio: File, output: File): Outcome {
        if (!video.exists() || video.length() == 0L) {
            return Outcome(false, "the picture part is missing")
        }
        if (!audio.exists() || audio.length() == 0L) {
            return Outcome(false, "the sound part is missing")
        }

        val videoExtractor = MediaExtractor()
        val audioExtractor = MediaExtractor()
        var muxer: MediaMuxer? = null
        try {
            videoExtractor.setDataSource(video.absolutePath)
            audioExtractor.setDataSource(audio.absolutePath)

            val videoTrack = findTrack(videoExtractor, "video/")
            if (videoTrack < 0) return Outcome(false, "the picture part has no picture in it")
            val audioTrack = findTrack(audioExtractor, "audio/")
            if (audioTrack < 0) return Outcome(false, "the sound part has no sound in it")

            output.parentFile?.mkdirs()
            output.delete()
            muxer = MediaMuxer(output.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val muxerVideo = muxer.addTrack(videoExtractor.getTrackFormat(videoTrack))
            val muxerAudio = muxer.addTrack(audioExtractor.getTrackFormat(audioTrack))
            muxer.start()

            copyTrack(videoExtractor, videoTrack, muxer, muxerVideo)
            copyTrack(audioExtractor, audioTrack, muxer, muxerAudio)

            muxer.stop()
            muxer.release()
            muxer = null
            return Outcome(true, "")
        } catch (t: Throwable) {
            // A codec the phone cannot put into an mp4 (a VP9 picture on an
            // older Android, for example) lands here. The picture on its own
            // is still worth keeping, so the caller decides what to do.
            Log.w(TAG, "the video could not be joined", t)
            return Outcome(false, t.message ?: t.javaClass.simpleName)
        } finally {
            runCatching { videoExtractor.release() }
            runCatching { audioExtractor.release() }
            runCatching { muxer?.release() }
        }
    }

    /** The first track of a kind ("video/" or "audio/"), or -1. */
    private fun findTrack(extractor: MediaExtractor, mimePrefix: String): Int {
        for (i in 0 until extractor.trackCount) {
            val mime = extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME).orEmpty()
            if (mime.startsWith(mimePrefix)) return i
        }
        return -1
    }

    /**
     * Copies every sample of one track into the file being written.
     *
     * The samples are already encoded, so they are copied as they are. That
     * is the whole point: nothing is decoded, so nothing gets slower and
     * nothing gets worse.
     */
    private fun copyTrack(
        extractor: MediaExtractor,
        trackIndex: Int,
        muxer: MediaMuxer,
        muxerTrack: Int
    ) {
        extractor.selectTrack(trackIndex)
        val buffer: ByteBuffer = ByteBuffer.allocate(SAMPLE_BUFFER)
        val info = MediaCodec.BufferInfo()
        while (true) {
            val size = extractor.readSampleData(buffer, 0)
            if (size < 0) break
            info.offset = 0
            info.size = size
            info.presentationTimeUs = extractor.sampleTime
            // The extractor's flags and the codec's flags are not the same
            // bits, so only the "this is a key frame" one is carried over.
            info.flags = if (extractor.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC != 0) {
                MediaCodec.BUFFER_FLAG_KEY_FRAME
            } else {
                0
            }
            muxer.writeSampleData(muxerTrack, buffer, info)
            extractor.advance()
        }
        extractor.unselectTrack(trackIndex)
    }
}
