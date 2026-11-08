package com.autosongs.bridge

import android.content.Context
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The bridge, running inside this app.
 *
 * It is the same Python program the AutoSongs app carries inside itself -
 * one source file, compiled into both. Here it listens on the network
 * rather than on the phone's own loopback, so another phone can reach it.
 */
object BridgeRunner {

    private const val TAG = "BridgeRunner"

    private val running = AtomicBoolean(false)

    /** The eight characters a phone types to pair with this bridge. */
    @Volatile
    var code: String = ""
        private set

    /** Where the bridge can be reached. */
    @Volatile
    var address: String = ""
        private set

    /** Why the bridge would not start, when it would not. */
    @Volatile
    var lastError: String = ""
        private set

    /** Where the bridge keeps the files it is working on. */
    fun workdir(context: Context): File =
        File(context.filesDir, "autosongs").apply { mkdirs() }

    /**
     * Where the finished songs are put.
     *
     * They are put here first and then copied into the phone's own music
     * library, because an app cannot write straight into a public folder
     * on modern Android.
     */
    fun library(context: Context): File =
        File(context.filesDir, "library").apply { mkdirs() }

    fun isRunning(): Boolean = running.get()

    /**
     * Starts the bridge.
     *
     * If the port is taken - another bridge on the same network, or an
     * old one that was never closed - it steps aside to the next port
     * rather than refusing to start.
     */
    fun start(context: Context, port: Int = 8765): Boolean {
        if (running.get()) return true
        lastError = ""
        return try {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(context.applicationContext))
            }
            val module = Python.getInstance().getModule("autosongs_bridge")
            val dir = workdir(context).absolutePath
            val lib = library(context).absolutePath
            var failure: Throwable? = null
            for (candidate in port until port + 10) {
                try {
                    val shown = module.callAttr("start", candidate, dir, lib)
                        .toString()
                    code = shown
                    address = module.callAttr("address").toString()
                    running.set(true)
                    Log.i(TAG, "the bridge is running on port $candidate, code $shown")
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
            val module = Python.getInstance().getModule("autosongs_bridge")
            module.callAttr("stop")
        } catch (t: Throwable) {
            Log.w(TAG, "the bridge did not stop cleanly", t)
        }
        code = ""
    }

    /** The version of the bridge inside this app. */
    fun version(): String = try {
        Python.getInstance().getModule("autosongs_bridge")["version"].toString()
    } catch (t: Throwable) {
        ""
    }

    /** The version of yt-dlp the bridge is using. */
    fun ytDlpVersion(): String = try {
        Python.getInstance().getModule("autosongs_bridge")["yt_dlp_version"].toString()
    } catch (t: Throwable) {
        ""
    }
}
