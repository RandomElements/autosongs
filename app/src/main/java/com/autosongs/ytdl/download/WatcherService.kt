package com.autosongs.ytdl.download

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.autosongs.ytdl.MainActivity
import com.autosongs.ytdl.R
import com.autosongs.ytdl.audio.Mp3Converter
import com.autosongs.ytdl.bridge.BridgeClient
import com.autosongs.ytdl.bridge.CookieStore
import com.autosongs.ytdl.embedded.EmbeddedBridge
import com.autosongs.ytdl.bridge.BridgeVersion
import com.autosongs.ytdl.bridge.JobStatus
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.data.DedupeStore
import com.autosongs.ytdl.data.FormatPreset
import com.autosongs.ytdl.data.NowPlaying
import com.autosongs.ytdl.data.watchedApps
import com.autosongs.ytdl.media.MediaSessionProbe
import com.autosongs.ytdl.media.MediaSniffer
import com.autosongs.ytdl.media.TrackBus
import com.autosongs.ytdl.video.VideoMuxer
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.File
import java.util.Locale

/**
 * Foreground service that watches what is playing and downloads each track.
 */
class WatcherService : LifecycleService() {

    private lateinit var settings: AppSettings
    private lateinit var dedupe: DedupeStore

    private var currentTrack: NowPlaying? = null
    private var currentPlaying = false
    private var currentPosition = 0L
    private var lastActionAt = 0L
    private var downloadJob: Job? = null
    private var watchJob: Job? = null
    private val queued = LinkedHashSet<String>()

    override fun onCreate() {
        super.onCreate()
        settings = AppSettings.get(this)
        dedupe = DedupeStore(this)
        createChannel()
        isRunning = true
        // The service can run without the activity ever being opened, so the
        // bridge inside the app is started here as well.
        if (settings.isEmbedded) {
            EmbeddedBridge.start(this)
        }
        TrackBus.listener = { track, playing, position -> onTrack(track, playing, position) }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        startForeground(NOTIF_ID, buildNotification("AutoSongs", "Waiting for a track…"), foregroundType())
        startWatching()
        return START_STICKY
    }

    override fun onDestroy() {
        isRunning = false
        TrackBus.listener = null
        watchJob?.cancel()
        downloadJob?.cancel()
        super.onDestroy()
    }

    // ---- detection ---------------------------------------------------------

    /**
     * Polls the active media sessions directly.
     *
     * This deliberately does not depend on the notification-listener service:
     * reading sessions with a `null` component only needs the
     * MEDIA_CONTENT_CONTROL permission, which Android grants at install time.
     * If the user never grants notification access - or the system never binds
     * the listener - detection still works.
     */
    private fun startWatching() {
        watchJob?.cancel()
        watchJob = lifecycleScope.launch {
            while (isActive) {
                val result = MediaSessionProbe.scan(
                    this@WatcherService, watchedApps(settings))
                TrackBus.setLastProbe(System.currentTimeMillis())

                val best = result.best
                if (best != null) {
                    onTrack(best.track, best.playing, best.position)
                }
                delay(WATCH_POLL_INTERVAL_MS)
            }
        }
    }

    // ---- track handling ----------------------------------------------------

    private fun onTrack(track: NowPlaying, playing: Boolean, position: Long) {
        val changed = currentTrack?.key != track.key
        currentTrack = track
        currentPlaying = playing
        currentPosition = position

        if (changed) {
            notify(track, "Detected")
        }

        if (!playing || !settings.autoDownload) return

        // Require the track to have been playing for a while, so we skip ads,
        // previews and tracks the user skips immediately.
        val playedFor = position
        if (playedFor in 1 until settings.minPlaybackMs) return

        if (track.durationMs in 1 until settings.minDurationSec * 1000L) return

        if (isBlocked(track.artist)) return
        if (!dedupe.shouldDownload(track.key, settings.dedupeHours)) return
        if (!queued.add(track.key)) return

        downloadJob?.cancel()
        downloadJob = lifecycleScope.launch {
            // Avoid hammering the bridge when the track changes rapidly.
            val since = System.currentTimeMillis() - lastActionAt
            if (since < 5_000) delay(5_000 - since)
            lastActionAt = System.currentTimeMillis()
            download(track)
        }
    }

    private fun isBlocked(artist: String): Boolean {
        if (artist.isBlank()) return false
        val blocks = settings.artistBlocklist.split(",").map { it.trim().lowercase() }
            .filter { it.isNotEmpty() }
        val a = artist.lowercase()
        return blocks.any { a.contains(it) }
    }

    // ---- downloading -------------------------------------------------------

    private suspend fun download(track: NowPlaying, retriedWithCookies: Boolean = false) {
        val client = BridgeClient(
            settings.bridgeAddress.first,
            settings.bridgeAddress.second,
            settings.bridgeAuthToken,
            settings.bridgeScheme,
            settings.bridgePath
        )

        // An old bridge turns a failed download into a bogus song (it used to
        // hand over its own source code). Refuse to work with it and say how
        // to fix it instead.
        val bridgeVersion = client.bridgeVersion().getOrNull()
        if (BridgeVersion.isTooOld(bridgeVersion)) {
            // The bridge inside the app is part of the app: there is
            // nothing to install and nothing to paste. Telling somebody who
            // never installed Termux to paste a command into it is
            // nonsense, and it sent the user looking for the wrong problem.
            val reason = if (settings.isEmbedded) {
                "The bridge inside the app is not answering. " +
                    "The app may need updating."
            } else {
                "The bridge on the phone is too old " +
                    "(${bridgeVersion ?: "unknown"}). ${BridgeVersion.installHint()}"
            }
            Log.e(TAG, reason)
            fail(track, reason)
            queued.remove(track.key)
            return
        }

        notify(track, "Searching…")
        TrackBus.setLastStatus("Searching…")
        val started = client.startJob(
            query = track.searchQuery,
            title = track.title,
            artist = track.artist,
            presetId = bridgePreset(),
            videoQuality = settings.preset.quality.takeIf { it > 0 } ?: settings.videoQuality,
            embedMetadata = settings.embedMetadata,
            embedThumbnail = settings.embedThumbnail,
            expectedDurationSec = track.durationMs / 1000
        )
        val jobId = started.getOrElse { error ->
            Log.e(TAG, "bridge unreachable: ${error.message}")
            notify(track, "Bridge unreachable")
            queued.remove(track.key)
            return
        }

        var status: JobStatus? = null
        var failures = 0
        for (attempt in 0 until MAX_POLLS) {
            delay(POLL_INTERVAL_MS)

            val polled = client.jobStatus(jobId)
            if (polled.isFailure) {
                failures++
                if (failures >= MAX_POLL_FAILURES) {
                    Log.e(TAG, "bridge unreachable while polling job $jobId")
                    break
                }
                continue
            }
            failures = 0

            val current = polled.getOrThrow()
            status = current
            // Stop as soon as the job is finished - `return@repeat` used to
            // continue the loop for the full hour of MAX_POLLS.
            if (current.isDone || current.isError) break

            val label = when {
                current.status.equals("searching", true) -> "Searching..."
                current.title.isNotBlank() -> "${current.title} (${current.percent}%)"
                else -> "Downloading ${current.percent}%"
            }
            notify(track, label)
        }

        val final = status
        if (final == null || final.isError) {
            // YouTube asked for a sign-in instead of the video. The cure is
            // a cookie jar, and the app may already have one: it is handed
            // over and the whole download is tried again - the refusal can
            // land in the search as well as in the download, so starting
            // again from the search is the only way to be sure.
            //
            // This happens at most once per track. A jar that does not
            // get past the refusal would fail the same way for ever.
            if (final != null && final.needsCookies &&
                !retriedWithCookies &&
                CookieStore.hasJar(this)
            ) {
                val sent = CookieStore.sendToBridge(this, client)
                if (sent.isSuccess) {
                    Log.i(TAG, "YouTube asked for a sign-in - trying again with the cookies")
                    notify(track, getString(R.string.cookies_retrying))
                    TrackBus.setLastStatus(getString(R.string.cookies_retrying))
                    queued.remove(track.key)
                    // The one retry. A jar that does not get past the
                    // refusal would fail the same way for ever.
                    download(track, retriedWithCookies = true)
                    return
                }
                Log.w(TAG, "the cookie jar could not be sent: " +
                    (sent.exceptionOrNull()?.message ?: "unknown"))
            }
            val reason = if (final != null && final.needsCookies) {
                getString(R.string.cookies_needed)
            } else {
                final?.error?.takeIf { it.isNotBlank() } ?: "download failed"
            }
            fail(track, reason)
            queued.remove(track.key)
            return
        }
        val safeName = track.displayName.replace(Regex("[^\\p{L}\\p{N} ._\\-]"), "_").trim()
            .ifBlank { "track" }
        if (!final.hasFile) {
            fail(track, "No file produced")
            queued.remove(track.key)
            return
        }

        // The song was to be kept on the bridge, not on this phone. The
        // bridge has already put it in its library folder, so there is
        // nothing to fetch and nothing to save here.
        if (settings.saveLocation == AppSettings.SAVE_BRIDGE && !settings.isEmbedded) {
            val where = final.savedAt.ifBlank { "the bridge's library folder" }
            Log.i(TAG, "kept on the bridge: $where")
            notify(track, "Saved on the bridge")
            TrackBus.setLastStatus("Saved on the bridge")
            queued.remove(track.key)
            return
        }

        // A video downloaded inside the app arrives in two pieces: the
        // picture and the sound. Joining them needs no ffmpeg - MediaMuxer
        // is part of Android - so the phone does it itself.
        if (final.parts) {
            val picture = File(cacheDir, "dl_${jobId}_picture.part")
            val sound = File(cacheDir, "dl_${jobId}_sound.part")
            notify(track, "Joining the picture and the sound\u2026")
            val gotPicture = client.downloadFilePart(jobId, "video", picture)
            val gotSound = client.downloadFilePart(jobId, "audio", sound)
            if (gotPicture.isFailure || gotSound.isFailure) {
                val why = (gotPicture.exceptionOrNull() ?: gotSound.exceptionOrNull())
                    ?.message.orEmpty()
                fail(track, "The bridge lost the video - try again" +
                    if (why.isNotBlank()) ": $why" else "")
                queued.remove(track.key)
                return
            }
            if (!MediaSniffer.looksLikeMedia(picture)) {
                fail(track, "The bridge returned something that is not a video")
                queued.remove(track.key)
                return
            }
            val joined = File(cacheDir, "dl_${jobId}_joined.mp4")
            val outcome = VideoMuxer.mux(picture, sound, joined)
            if (!outcome.ok) {
                Log.w(TAG, "the video could not be joined: ${outcome.reason}")
                if (outcome.reason.contains("no picture")) {
                    // This match has no picture in it - only the sound. The
                    // sound carries the album cover, so saving it as a video
                    // would show the cover as a still picture with the song
                    // playing. Save it as what it is, and say so.
                    val ext = final.audioExt.ifBlank { ".m4a" }
                    notify(track, "This one has no picture - saving the sound only")
                    saveToMediaLibrary(sound, track, "$safeName$ext", ext.removePrefix("."))
                    queued.remove(track.key)
                    notify(track, "Saved \u2713", done = true)
                    TrackBus.setLastStatus("Saved: $safeName$ext (sound only)")
                    return
                }
                // The picture on its own is still worth keeping - and the
                // user should know that there is no sound on it.
                notify(track, "Saved the video without the sound")
                saveToMediaLibrary(picture, track, "$safeName.mp4", "mp4")
                queued.remove(track.key)
                notify(track, "Saved \u2713", done = true)
                TrackBus.setLastStatus("Saved: $safeName.mp4")
                return
            }
            saveToMediaLibrary(joined, track, "$safeName.mp4", "mp4")
            queued.remove(track.key)
            notify(track, "Saved \u2713", done = true)
            TrackBus.setLastStatus("Saved: $safeName.mp4")
            return
        }

        notify(track, "Saving…")
        val tmp = File(cacheDir, "dl_$jobId.download")

        var downloaded = client.downloadFile(jobId, tmp)
        if (downloaded.isFailure && isMissingFile(downloaded)) {
            // The bridge keeps its job list in memory. If it restarted while
            // the download was running, the file is on disk but the job is
            // gone - so ask for it by the name the bridge itself used.
            Log.w(TAG, "job $jobId not on the bridge any more, trying the rescue path")
            val bridgeName = if (final.artist.isNotBlank()) {
                "${final.artist} - ${final.title}"
            } else {
                final.title
            }
            downloaded = client.downloadByName(bridgeName, tmp)
        }
        if (downloaded.isFailure) {
            val message = downloaded.exceptionOrNull()?.message.orEmpty()
            fail(track, if (isMissingFile(downloaded)) {
                "The bridge lost the file (it probably restarted) - try again"
            } else {
                "Transfer failed: $message"
            })
            queued.remove(track.key)
            return
        }
        val serverExtension = downloaded.getOrNull()?.extension.orEmpty()

        // Guard against the bridge handing over something that is not media
        // at all. A real bug shipped a Python script as "Artist - Title.py.mp3",
        // because the bridge fell back to "any recent file" and found itself.
        if (!MediaSniffer.looksLikeMedia(tmp)) {
            fail(track, "The bridge returned ${tmp.length()} bytes that are not " +
                "audio or video - nothing was saved")
            queued.remove(track.key)
            return
        }

        // Use the real container extension reported by the bridge (m4a/opus/
        // mp3/webm/mp4) rather than guessing from the preset.
        var ext = serverExtension.ifBlank {
            if (settings.preset.isVideo) "mp4" else "m4a"
        }
        var fileToSave = tmp

        // The app can make MP3s itself now. The bridge hands over the sound
        // it downloaded - an m4a, when it has no ffmpeg to re-encode with -
        // and the phone turns it into an mp3. A bridge that already did the
        // job, such as the one in Termux, is left alone.
        var mp3Problem: String? = null
        if (settings.preset == FormatPreset.AUDIO_MP3 && !ext.equals("mp3", true)) {
            notify(track, "Converting to mp3…")
            val mp3 = File(cacheDir, "dl_$jobId.mp3")
            // The decoder likes a file that says what it is, so the
            // download is copied under its real name first.
            val source = File(cacheDir, "dl_$jobId.$ext")
            try {
                tmp.copyTo(source, overwrite = true)
            } catch (_: Throwable) {
                // If the copy fails the original is used anyway.
            }
            // The cover goes inside the mp3. The session's own art is
            // the first choice; when it has none, the bridge knows where
            // the picture is and the phone goes and gets it.
            val artwork = Mp3Converter.artworkBytes(track.artwork)
                ?: Mp3Converter.artworkFromUrl(final.thumbnail)
            val result = Mp3Converter.convert(
                source, mp3, track.title, track.artist, track.album,
                artwork, 192
            )
            if (result.ok) {
                fileToSave = mp3
                ext = "mp3"
            } else {
                Log.w(TAG, "the mp3 conversion did not work: ${result.reason}")
                // "It did not work" on its own tells nobody anything, so
                // the reason is kept and shown in the app's own status
                // line - that is where a person can read it and pass it on.
                mp3Problem = result.reason
            }
        }

        val savedAs = "$safeName.$ext"
        saveToMediaLibrary(fileToSave, track, savedAs, ext)
        queued.remove(track.key)
        val problem = mp3Problem
        if (problem == null) {
            notify(track, "Saved ✓", done = true)
            TrackBus.setLastStatus("Saved: $savedAs")
        } else {
            notify(track, "Saved as ${ext.uppercase()} - mp3 did not work", done = true)
            TrackBus.setLastStatus("Saved: $savedAs - mp3 did not work: $problem")
        }
    }

    /**
     * What to ask the bridge for.
     *
     * For mp3 the bridge is asked for the sound as it is, and the phone
     * makes the mp3 itself. That way mp3 works with every bridge: one
     * with ffmpeg, one without, and the one inside the app.
     *
     * Asking a bridge without ffmpeg to re-encode only ever produces an
     * error - "the mp3 conversion failed, ffmpeg is required" - and the
     * user is left with nothing.
     */
    private fun bridgePreset(): String =
        if (settings.preset == FormatPreset.AUDIO_MP3) {
            FormatPreset.AUDIO_ORIGINAL.id
        } else {
            settings.preset.id
        }

    /** True when the bridge answered "no such file" (404). */
    private fun isMissingFile(result: Result<*>): Boolean =
        result.exceptionOrNull()?.message?.contains("404") == true

    /** Writes the file into the shared library so every player sees it. */
    private fun saveToMediaLibrary(file: File, track: NowPlaying, displayName: String, ext: String) {
        try {
            val resolver = contentResolver
            val isVideo = settings.preset.isVideo
            val collection = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                if (isVideo) {
                    MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                } else {
                    MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                }
            } else if (isVideo) {
                MediaStore.Video.Media.EXTERNAL_CONTENT_URI
            } else {
                MediaStore.Audio.Media.EXTERNAL_CONTENT_URI
            }

            val values = android.content.ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
                put(MediaStore.MediaColumns.MIME_TYPE, mimeFor(ext))
                if (isVideo) {
                    put(MediaStore.Video.Media.ALBUM, track.album)
                    put(MediaStore.Video.Media.ARTIST, track.artist)
                    put(MediaStore.Video.Media.DESCRIPTION, track.title)
                } else {
                    put(MediaStore.Audio.Media.TITLE, track.title)
                    put(MediaStore.Audio.Media.ARTIST, track.artist)
                    put(MediaStore.Audio.Media.ALBUM, track.album)
                    put(MediaStore.Audio.Media.IS_MUSIC, 1)
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    // A video must live under Movies/ - a Music/ path on a
                    // video entry makes MediaStore hide the file.
                    val dir = if (isVideo) {
                        Environment.DIRECTORY_MOVIES
                    } else {
                        Environment.DIRECTORY_MUSIC
                    }
                    put(
                        MediaStore.MediaColumns.RELATIVE_PATH,
                        "$dir/${settings.folderName}"
                    )
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }
            }

            val uri = resolver.insert(collection, values)
            if (uri == null) {
                Log.e(TAG, "MediaStore insert failed")
                return
            }

            resolver.openOutputStream(uri)?.use { out ->
                file.inputStream().use { it.copyTo(out) }
            } ?: run {
                resolver.delete(uri, null, null)
                return
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                resolver.update(
                    uri,
                    android.content.ContentValues().apply {
                        put(MediaStore.MediaColumns.IS_PENDING, 0)
                    },
                    null, null
                )
            }

            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                // On Android 9 and older the insert above has no path to
                // write to, so the scanner has to pick the file up. On
                // Android 10+ the MediaStore insert already indexed it -
                // scanning as well creates a duplicate entry for the same
                // bytes, and the library then shows the track twice.
                MediaScannerConnection.scanFile(this, arrayOf(file.absolutePath), null, null)
            }
            if (settings.deleteAfterTransfer) file.delete()
            Log.i(TAG, "saved: ${track.displayName} -> $displayName")
        } catch (t: Throwable) {
            Log.e(TAG, "save failed", t)
        }
    }

    private fun mimeFor(ext: String): String = when (ext.lowercase(Locale.US)) {
        "mp3" -> "audio/mpeg"
        "opus" -> "audio/ogg"
        "webm" -> "audio/webm"
        "mp4", "m4v" -> "video/mp4"
        "ogg" -> "audio/ogg"
        else -> "audio/mpeg"
    }

    // ---- notifications -----------------------------------------------------

    /**
     * The watcher runs as a specialUse foreground service: Android 14+ only
     * grants the mediaPlayback type to apps that own an active MediaSession,
     * and here the *other* app owns the session.
     */
    private fun foregroundType(): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "AutoSongs activity",
            NotificationManager.IMPORTANCE_LOW
        ).apply { description = "Shows what AutoSongs is downloading" }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun notify(track: NowPlaying, message: String, done: Boolean = false) {
        val title = "${track.title}${if (track.artist.isNotBlank()) " — ${track.artist}" else ""}"
        val notification = buildNotification(title, message, done)
        getSystemService(NotificationManager::class.java).notify(NOTIF_ID, notification)
        TrackBus.setLastStatus(message)
    }

    /** Records a failure so the UI can show the reason, not just a code. */
    private fun fail(track: NowPlaying, reason: String) {
        Log.e(TAG, reason)
        notify(track, reason)
        TrackBus.setLastStatus(reason, reason)
    }

    private fun buildNotification(title: String, text: String = "", done: Boolean = false): Notification {
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_stat_autosongs)
            .setOngoing(!done)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    companion object {
        private const val TAG = "WatcherService"

        /** Lets the UI show whether the watcher is alive. */
        @Volatile
        var isRunning: Boolean = false
            private set
        private const val CHANNEL_ID = "autosongs_activity"
        private const val NOTIF_ID = 4711
        private const val POLL_INTERVAL_MS = 1500L
        private const val WATCH_POLL_INTERVAL_MS = 1000L
        private const val MAX_POLLS = 2400
        private const val MAX_POLL_FAILURES = 5

        fun start(context: Context) {
            val intent = Intent(context, WatcherService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, WatcherService::class.java))
        }
    }
}
