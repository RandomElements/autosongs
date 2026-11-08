package com.autosongs.ytdl.media

import android.app.Notification
import android.content.ComponentName
import android.graphics.Bitmap
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.Handler
import android.os.Looper
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.data.NowPlaying
import com.autosongs.ytdl.data.watchedApps

/**
 * Detects what is playing in YouTube Music (ReVanced) — and any other app the
 * user allows.
 *
 * Two signals are combined:
 *  1. Media controllers (read from [MediaSessionManager]) → exact
 *     title/artist/album plus playback state and position.
 *  2. Media notifications → artwork and a fallback when a player does not
 *     publish a usable media session.
 */
class MediaSessionListenerService : NotificationListenerService() {

    private val handler = Handler(Looper.getMainLooper())
    private var sessionManager: MediaSessionManager? = null
    private val notificationArtwork = mutableMapOf<String, Bitmap>()

    private val selfComponent: ComponentName
        get() = ComponentName(this, MediaSessionListenerService::class.java)

    private val poller = object : Runnable {
        override fun run() {
            publishFromSessions()
            handler.postDelayed(this, POLL_INTERVAL_MS)
        }
    }

    override fun onCreate() {
        super.onCreate()
        sessionManager = getSystemService(MediaSessionManager::class.java)
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        TrackBus.setListenerConnected(true)
        handler.removeCallbacks(poller)
        handler.post(poller)
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        TrackBus.setListenerConnected(false)
        handler.removeCallbacks(poller)
    }

    override fun onDestroy() {
        handler.removeCallbacks(poller)
        super.onDestroy()
    }

    // ---- notifications -----------------------------------------------------

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val n = sbn?.notification ?: return
        if (!n.isMediaStyle()) return
        val pkg = sbn.packageName
        val extras = n.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val artist = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
        val album = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString().orEmpty()

        n.largeIcon?.let { notificationArtwork[pkg] = it }

        // Fallback only: media sessions carry better metadata and playback
        // state, so they win when available.
        if (title.isNotBlank() && !hasSessionFor(pkg)) {
            publish(NowPlaying(pkg, title, artist, album, 0L, notificationArtwork[pkg]), true, 0L)
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        notificationArtwork.remove(sbn?.packageName ?: return)
    }

    // ---- sessions ----------------------------------------------------------

    /** The apps to watch - the same rule the watcher uses. */
    private fun watchedPackages(): Set<String> = watchedApps(AppSettings.get(this))

    private fun activeControllers(): List<MediaController> {
        val manager = sessionManager ?: return emptyList()
        return runCatching { manager.getActiveSessions(selfComponent) }
            .onFailure { Log.w(TAG, "cannot read sessions", it) }
            .getOrNull()
            .orEmpty()
    }

    private fun hasSessionFor(pkg: String): Boolean =
        activeControllers().any { it.packageName == pkg }

    private fun publishFromSessions() {
        val watched = watchedPackages()
        val all = activeControllers()
        TrackBus.setSeenPackages(all.map { it.packageName }.toSet())
        TrackBus.setLastProbe(System.currentTimeMillis())

        for (controller in all) {
            val pkg = controller.packageName
            // An empty list means every app: a media session is the
            // system's own way of saying "something is playing".
            if (watched.isNotEmpty() && pkg !in watched) continue

            val metadata = controller.metadata ?: continue
            val title = metadata.getString(MediaMetadata.METADATA_KEY_TITLE)
                ?.takeIf { it.isNotBlank() } ?: continue
            val artist = metadata.getString(MediaMetadata.METADATA_KEY_ARTIST).orEmpty()
            val album = metadata.getString(MediaMetadata.METADATA_KEY_ALBUM).orEmpty()
            val duration = metadata.getLong(MediaMetadata.METADATA_KEY_DURATION)
            val artwork = metadata.getBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART)
                ?: notificationArtwork[pkg]

            val state = controller.playbackState
            val playing = state?.state == PlaybackState.STATE_PLAYING
            val position = state?.position ?: 0L

            publish(NowPlaying(pkg, title, artist, album, duration, artwork), playing, position)
        }
    }

    private fun publish(track: NowPlaying, playing: Boolean, position: Long) {
        TrackBus.dispatch(track, playing, position)
    }

    companion object {
        private const val TAG = "MediaSessionListener"
        private const val POLL_INTERVAL_MS = 1_000L

        /** Notification.EXTRA_MEDIA_STYLE is not public API, so use its raw key. */
        private const val KEY_MEDIA_STYLE = "android.mediaStyle"

        private fun Notification.isMediaStyle(): Boolean =
            extras?.containsKey(KEY_MEDIA_STYLE) == true
    }
}
