package com.autosongs.ytdl.embedded

import android.content.Context
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.autosongs.ytdl.data.AppSettings
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The bridge, running inside the app.
 *
 * yt-dlp is a Python program, so an app that downloads from YouTube needs a
 * Python interpreter. Chaquopy puts one inside the APK, which means the
 * whole thing is one app: no Termux, no second install, no pasting a
 * command into a terminal.
 *
 * The bridge still listens on 127.0.0.1:8765 and still speaks the same
 * HTTP, so the download code in the app does not change at all.
 */
object EmbeddedBridge {

    private const val TAG = "EmbeddedBridge"

    private val running = AtomicBoolean(false)

    /** Where the bridge keeps its files. */
    fun workdir(context: Context): File =
        File(context.filesDir, "autosongs").apply { mkdirs() }

    /** Why the bridge would not start, when it would not. */
    @Volatile
    private var lastError: String = ""

    /** The reason the bridge gave for not starting, if it gave one. */
    fun lastError(): String = lastError

    /**
     * Starts the bridge inside the app.
     *
     * Returns true when it is running. It is safe to call this more than
     * once - the second call does nothing.
     *
     * Something else may already hold the port - an old Termux bridge, most
     * often. The bridge inside the app steps aside to the next port rather
     * than refusing to start, and writes down which port it took so the
     * app and the service both dial the right one.
     */
    fun start(context: Context, port: Int = 8765): Boolean {
        if (running.get()) return true
        lastError = ""
        return try {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(context.applicationContext))
            }
            val module = Python.getInstance().getModule("autosongs_embedded")
            val dir = workdir(context).absolutePath
            var failure: Throwable? = null
            for (candidate in port until port + 10) {
                try {
                    module.callAttr("start", candidate, dir, true)
                    AppSettings.get(context).embeddedPort = candidate
                    running.set(true)
                    Log.i(TAG, "the bridge is running inside the app on port $candidate")
                    return true
                } catch (t: Throwable) {
                    failure = t
                    Log.w(TAG, "port $candidate is taken, trying the next one")
                }
            }
            lastError = failure?.message ?: "unknown"
            Log.e(TAG, "the bridge could not be started", failure)
            running.set(false)
            false
        } catch (t: Throwable) {
            lastError = t.message ?: "unknown"
            Log.e(TAG, "the bridge could not be started", t)
            running.set(false)
            false
        }
    }

    /** Stops the bridge. It starts again on the next call to start(). */
    fun stop() {
        if (!running.getAndSet(false)) return
        try {
            val module = Python.getInstance().getModule("autosongs_embedded")
            module.callAttr("stop")
        } catch (t: Throwable) {
            Log.w(TAG, "the bridge did not stop cleanly", t)
        }
    }

    /** The version of the bridge inside the app. */
    fun version(): String = try {
        val module = Python.getInstance().getModule("autosongs_embedded")
        module["version"].toString()
    } catch (t: Throwable) {
        ""
    }

    /**
     * The version of yt-dlp the bridge is using.
     *
     * The app can put a newer yt-dlp in front of the one that came with
     * the APK, so this can be newer than the version in the build.
     */
    fun ytDlpVersion(): String = try {
        val module = Python.getInstance().getModule("autosongs_embedded")
        module["yt_dlp_version"].toString()
    } catch (t: Throwable) {
        ""
    }

    /**
     * Points the bridge at a newer yt-dlp that was downloaded earlier.
     *
     * The newest yt-dlp is the one that works with YouTube. A year-old
     * version cannot download anything, and that shows up as a 403. So the
     * app keeps this up to date by itself.
     */
    fun useYtDlpAt(directory: File): Boolean = try {
        val module = Python.getInstance().getModule("autosongs_embedded")
        module.callAttr("use_ytdlp", directory.absolutePath)
        true
    } catch (t: Throwable) {
        Log.w(TAG, "the newer yt-dlp could not be used", t)
        false
    }
}
