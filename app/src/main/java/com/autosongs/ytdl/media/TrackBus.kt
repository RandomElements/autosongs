package com.autosongs.ytdl.media

import com.autosongs.ytdl.data.NowPlaying

/**
 * Tiny in-process bus. The notification listener service and the watcher
 * service live in the same process, so no IPC is needed.
 *
 * It also keeps the last observed track so the UI can show the user exactly
 * what the app can currently see - the fastest way to diagnose "it is not
 * picking up songs".
 */
object TrackBus {

    @Volatile
    var listener: ((NowPlaying, Boolean, Long) -> Unit)? = null

    @Volatile
    var lastTrack: NowPlaying? = null
        private set

    @Volatile
    var lastSeenAt: Long = 0L
        private set

    /** Packages that currently expose a media session. */
    @Volatile
    private var seen: Set<String> = emptySet()

    val seenPackages: Set<String> get() = seen

    fun setSeenPackages(value: Set<String>) {
        seen = value
    }

    /** True once the notification listener has been connected by the system. */
    @Volatile
    var listenerConnected: Boolean = false
        private set

    /** Timestamp of the last successful media-session read. */
    @Volatile
    var lastProbeAt: Long = 0L
        private set

    fun setLastProbe(value: Long) {
        lastProbeAt = value
    }

    /** Last thing the downloader did, and why it stopped. */
    @Volatile
    var lastStatus: String = ""
        private set

    @Volatile
    var lastError: String = ""
        private set

    fun setLastStatus(status: String, error: String = "") {
        lastStatus = status
        lastError = error
    }

    fun setListenerConnected(value: Boolean) {
        listenerConnected = value
    }

    fun dispatch(track: NowPlaying, playing: Boolean, position: Long) {
        lastTrack = track
        lastSeenAt = System.currentTimeMillis()
        seen = seen + track.packageName
        listener?.invoke(track, playing, position)
    }
}
