package com.autosongs.ytdl.media

import android.content.ComponentName
import android.content.Context
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.util.Log
import com.autosongs.ytdl.data.NowPlaying

/**
 * Reads the media sessions that are currently active on the device.
 *
 * Two ways to do that exist, and this class uses both:
 *
 *  1. [MediaSessionManager.getActiveSessions] with a `null` component. That
 *     needs the `MEDIA_CONTENT_CONTROL` permission, which is granted at
 *     install time, so detection works **without** the user granting
 *     notification access. This is the primary path.
 *  2. The same call with our own notification-listener component. That needs
 *     notification access and only works while the system has actually bound
 *     our listener service. It is the fallback, and the only path that can
 *     deliver notification artwork.
 *
 * Relying on path 2 alone is fragile: if the system does not bind the
 * listener (a toggle in the notification-access list that did not take, a
 * service the system refused, an OEM quirk) the app silently sees nothing.
 */
object MediaSessionProbe {

    data class Sample(
        val track: NowPlaying,
        val playing: Boolean,
        val position: Long
    )

    /** Result of a scan: whether we may read sessions, and what is playing. */
    data class Result(
        val accessible: Boolean,
        val sessions: Int,
        val samples: List<Sample>
    ) {
        /** The track the user is most likely listening to. */
        val best: Sample? get() = samples.firstOrNull { it.playing } ?: samples.firstOrNull()
    }

    /** True when the direct (no notification access) path is usable. */
    @Volatile
    var directAccessWorks: Boolean = false
        private set

    /** Reads every active session, or null when we are not allowed to. */
    fun controllers(context: Context): List<MediaController>? {
        val manager = context.getSystemService(MediaSessionManager::class.java)
            ?: return null

        try {
            val all = manager.getActiveSessions(null)
            directAccessWorks = true
            return all
        } catch (t: SecurityException) {
            Log.i(TAG, "direct media session read denied; using listener component")
        } catch (t: Throwable) {
            Log.w(TAG, "direct media session read failed", t)
        }

        return try {
            manager.getActiveSessions(
                ComponentName(context, MediaSessionListenerService::class.java)
            )
        } catch (t: SecurityException) {
            Log.w(TAG, "listener component read denied", t)
            null
        } catch (t: Throwable) {
            Log.w(TAG, "listener component read failed", t)
            null
        }
    }

    /**
     * Returns the tracks of the watched apps that are currently playing.
     * The track with the highest playback position wins, because that is
     * normally the one the user is actually listening to.
     */
    /**
     * Scans the device for the watched apps that are currently playing.
     *
     * [Result.accessible] tells the two failure modes apart: "we may not read
     * sessions at all" versus "we can read them, nothing is playing".
     */
    fun scan(context: Context, watched: Set<String>): Result {
        val list = controllers(context)
            ?: return Result(accessible = false, sessions = 0, samples = emptyList())

        val out = mutableListOf<Sample>()
        for (controller in list) {
            if (watched.isNotEmpty() && controller.packageName !in watched) continue
            val sample = toSample(controller) ?: continue
            out.add(sample)
        }
        out.sortByDescending { it.position }
        return Result(accessible = true, sessions = list.size, samples = out)
    }

    /** Convenience wrapper for callers that only need the tracks. */
    fun probe(context: Context, watched: Set<String>): List<Sample> =
        scan(context, watched).samples

    fun toSample(controller: MediaController): Sample? {
        val metadata = controller.metadata ?: return null
        val title = metadata.getString(MediaMetadata.METADATA_KEY_TITLE)
            ?.takeIf { it.isNotBlank() } ?: return null
        val artist = metadata.getString(MediaMetadata.METADATA_KEY_ARTIST).orEmpty()
        val album = metadata.getString(MediaMetadata.METADATA_KEY_ALBUM).orEmpty()
        val duration = metadata.getLong(MediaMetadata.METADATA_KEY_DURATION)
        val artwork = metadata.getBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART)

        val state = controller.playbackState
        val playing = state?.state == PlaybackState.STATE_PLAYING
        val position = state?.position ?: 0L

        return Sample(
            NowPlaying(controller.packageName, title, artist, album, duration, artwork),
            playing,
            position
        )
    }

    private const val TAG = "MediaSessionProbe"
}
