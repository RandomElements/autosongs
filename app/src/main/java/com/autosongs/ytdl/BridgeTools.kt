package com.autosongs.ytdl

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import com.autosongs.ytdl.bridge.BridgeClient
import com.autosongs.ytdl.bridge.BridgeHealth
import com.autosongs.ytdl.bridge.BridgeVersion
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.embedded.EmbeddedBridge
import com.autosongs.ytdl.embedded.YtDlpUpdater
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * The parts of the bridge that both screens need.
 *
 * The tools used to sit on the home screen, where they took up more room
 * than the things people actually use. They are in Settings now, and both
 * screens call in here, so there is one copy of this rather than two that
 * drift apart.
 */
object BridgeTools {

    private const val TAG = "BridgeTools"

    // ---- checking ------------------------------------------------------------

    /**
     * Checks the bridge as soon as a screen opens.
     *
     * The install hint used to appear only after the user tapped a button.
     * An old bridge is the single most common reason a download fails, so
     * the app has to say so by itself - otherwise the user has to guess
     * that a button is what they need.
     */
    fun check(activity: Activity, settings: AppSettings, status: TextView) {
        lifecycleScope(activity).launch {
            val client = client(settings)
            val embedded = settings.bridgeMode == AppSettings.BRIDGE_EMBEDDED
            // The bridge inside the app needs a moment to start: Python has
            // to load first. A couple of tries save the user a worry.
            var version: String? = null
            var health: Result<String>? = null
            val tries = if (embedded) 6 else 1
            for (attempt in 0 until tries) {
                version = client.bridgeVersion().getOrNull()
                health = client.health(ytDlpFallback(settings))
                if (version != null) break
                delay(1000)
            }
            status.text = health!!.fold(
                onSuccess = { "Bridge OK — $it (${whereTheBridgeIs(settings)})" },
                onFailure = { "Bridge unreachable: ${it.message}" }
            )
            BridgeHealth.outdatedYtDlpMessage(health.getOrNull())?.let {
                status.text = status.text.toString() + "\n\n" + it
            }
            if (embedded) {
                // The bridge is part of the app. There is nothing to
                // install, so an install line would only confuse.
                if (version == null) {
                    val reason = EmbeddedBridge.lastError()
                    status.text = status.text.toString() +
                        "\n\nThe bridge inside the app is not answering yet." +
                        " It usually needs a moment after the app opens." +
                        (if (reason.isBlank()) "" else "\n\nThe bridge said: $reason")
                }
            } else if (version == null || BridgeVersion.isTooOld(version)) {
                status.text = status.text.toString() + "\n\n" +
                    BridgeVersion.installHint()
            }
        }
    }

    /** Checks the bridge because the user asked. */
    fun test(activity: Activity, settings: AppSettings, status: TextView) {
        status.text = "Testing ${settings.bridgeAddress.first}:${settings.bridgeAddress.second}…"
        lifecycleScope(activity).launch {
            val client = client(settings)
            val version = client.bridgeVersion().getOrNull()
            val result = client.health(ytDlpFallback(settings))
            status.text = result.fold(
                onSuccess = { "Bridge OK — $it (${whereTheBridgeIs(settings)})" },
                onFailure = { "Bridge unreachable: ${it.message}" }
            )
            BridgeHealth.outdatedYtDlpMessage(result.getOrNull())?.let {
                status.text = status.text.toString() + "\n\n" + it
            }
            if (settings.isEmbedded) {
                // The bridge is part of the app. There is nothing to
                // install, so an install line would only confuse.
                if (version == null) {
                    status.text = status.text.toString() +
                        "\n\nThe bridge inside the app is not answering." +
                        " It usually needs a moment after the app opens."
                }
            } else if (version == null) {
                val why = if (bridgeIsOnThisPhone(settings)) {
                    "The bridge on the phone has stopped. Android kills apps " +
                        "that sit in the background, and Termux is one of them. " +
                        "Give Termux a battery exemption with the button below, " +
                        "then start the bridge in Termux again."
                } else {
                    "The bridge did not answer. Check that it is running, and " +
                        "that the address and the port are right."
                }
                status.text = status.text.toString() + "\n\n" + why
            } else if (BridgeVersion.isTooOld(version)) {
                status.text = status.text.toString() + "\n\n" +
                    BridgeVersion.installHint()
            }
        }
    }

    /**
     * The yt-dlp version, for when the bridge cannot say.
     *
     * The bridge inside the app sometimes cannot tell which yt-dlp it is
     * using - the number lives in the Python library. The app knows it,
     * because the app is the one that put the library there.
     */
    private fun ytDlpFallback(settings: AppSettings): String? {
        if (!settings.isEmbedded) return null
        return EmbeddedBridge.ytDlpVersion().ifBlank { null }
    }

    // ---- updating ------------------------------------------------------------

    /**
     * Brings the bridge up to date.
     *
     * The newest published bridge is fetched here and pushed to the bridge
     * on the phone, which installs it and restarts by itself. If the bridge
     * cannot be reached at all, the files are written to the phone and the
     * one line to paste into Termux is shown.
     */
    fun update(activity: Activity, settings: AppSettings, status: TextView) {
        if (settings.isEmbedded) {
            // The bridge is part of the app, so there is nothing to push to
            // it. What can go stale is yt-dlp, and that is the part that
            // actually breaks.
            status.text = "Looking for a newer yt-dlp…"
            lifecycleScope(activity).launch {
                val newest = YtDlpUpdater.update(activity)
                status.text = if (newest != null) {
                    "yt-dlp is now $newest"
                } else {
                    "yt-dlp is already up to date, or PyPI could not be reached"
                }
            }
            return
        }

        status.text = "Looking for a newer bridge…"
        lifecycleScope(activity).launch {
            val newest = bundledBridge(activity) ?: fetchNewestBridge()
            if (newest == null) {
                status.text = "Could not download a newer bridge - is this phone online?"
                return@launch
            }
            val client = client(settings)

            // A bridge older than 1.3.11 has no way of being given new code.
            // Say so plainly and hand over the one line that fixes it.
            val running = client.bridgeVersion().getOrNull()
            if (!BridgeVersion.canSelfUpdate(running)) {
                status.text = "The bridge on the phone is ${running ?: "not answering"} " +
                    "and is too old to update itself.\n\n" + BridgeVersion.installHint()
                return@launch
            }

            status.text = "Pushing bridge ${newest.first} to the phone…"
            val answer = client.updateBridge(newest.second)
            if (answer.isSuccess) {
                status.text = answer.getOrNull() ?: "The bridge was updated."
                return@launch
            }
            // The bridge could not be reached. Put the files on the phone
            // and let the user start them with one line in Termux.
            val saved = writeBridgeToPhone(activity, newest.second)
            status.text = if (saved != null) {
                "The bridge on the phone is not answering.\n\n" +
                    "Paste this into Termux:\n\nbash $saved/setup.sh"
            } else {
                "The bridge on the phone is not answering.\n\n" +
                    BridgeVersion.installHint()
            }
        }
    }

    /**
     * The bridge that ships inside this app.
     *
     * The APK carries the bridge as an asset, so the app and the bridge can
     * never be different versions: whatever the app was built with is what
     * it pushes to the phone.
     */
    private suspend fun bundledBridge(activity: Activity): Pair<String, String>? {
        return try {
            val text = withContext(Dispatchers.IO) {
                activity.assets.open("ytbridge.py").use {
                    it.readBytes().toString(Charsets.UTF_8)
                }
            }
            val m = Regex("^BRIDGE_VERSION = \"([^\"]+)\"", RegexOption.MULTILINE)
                .find(text) ?: return null
            m.groupValues[1] to text
        } catch (_: Exception) {
            null
        }
    }

    /** The newest bridge that any of the published copies has. */
    private suspend fun fetchNewestBridge(): Pair<String, String>? {
        var best: Pair<String, String>? = null
        for (url in BridgeVersion.BRIDGE_URLS) {
            try {
                val request = okhttp3.Request.Builder().url(url).get().build()
                val client = okhttp3.OkHttpClient.Builder()
                    .callTimeout(30, java.util.concurrent.TimeUnit.SECONDS).build()
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) return@use
                    val text = response.body?.string().orEmpty()
                    val m = Regex("^BRIDGE_VERSION = \"([^\"]+)\"", RegexOption.MULTILINE)
                        .find(text) ?: return@use
                    val version = m.groupValues[1]
                    if (best == null || compareVersions(version, best!!.first) > 0) {
                        best = version to text
                    }
                }
            } catch (_: Exception) {
                // try the next one
            }
        }
        return best
    }

    /** Compares dotted version numbers. */
    private fun compareVersions(a: String, b: String): Int {
        val left = a.split(".")
        val right = b.split(".")
        for (i in 0 until maxOf(left.size, right.size)) {
            val l = left.getOrNull(i)?.toIntOrNull() ?: 0
            val r = right.getOrNull(i)?.toIntOrNull() ?: 0
            if (l != r) return l.compareTo(r)
        }
        return 0
    }

    /**
     * Puts the bridge and a setup script on the phone and returns the
     * folder they are in.
     *
     * It has to land somewhere Termux can open and the user can name in one
     * line. The app's own folder (/Android/data/...) cannot be read by
     * another app on modern Android, and a path Termux cannot open is
     * worse than no fallback at all.
     */
    private fun writeBridgeToPhone(activity: Activity, code: String): String? {
        return try {
            val setup = "#!/data/data/com.termux/files/usr/bin/bash\n" +
                "set -e\n" +
                "mkdir -p \"\$HOME/autosongs/bin\" \"\$HOME/autosongs/downloads\"\n" +
                "cp \"\$HERE/ytbridge.py\" \"\$HOME/autosongs/bin/ytbridge.py\"\n" +
                "chmod +x \"\$HOME/autosongs/bin/ytbridge.py\"\n" +
                "pkg install -y python ffmpeg curl >/dev/null 2>&1 || true\n" +
                "python -m pip install -U -q yt-dlp --break-system-packages || true\n" +
                "for proc in /proc/[0-9]*; do " +
                "if grep -qa ytbridge.py \"\$proc/cmdline\" 2>/dev/null; then " +
                "kill \"\${proc#/proc/}\" 2>/dev/null || true; fi; done\n" +
                "sleep 1\n" +
                "nohup python \"\$HOME/autosongs/bin/ytbridge.py\" --port \"\${YTBRIDGE_PORT:-8765}\" " +
                "--workdir \"\$HOME/autosongs/downloads\" > \"\$HOME/autosongs/bridge.log\" 2>&1 &\n" +
                "echo \"bridge started\"\n"

            if (!writeToDownloads(activity, "ytbridge.py", code.toByteArray())) return null
            if (!writeToDownloads(activity, "setup.sh", setup.toByteArray())) return null
            downloadFolder()
        } catch (_: Exception) {
            null
        }
    }

    /** The public Downloads folder, as Termux sees it. */
    private fun downloadFolder(): String? = try {
        File(Environment.getExternalStoragePublicDirectory(
            Environment.DIRECTORY_DOWNLOADS), "autosongs").absolutePath
    } catch (_: Exception) {
        null
    }

    /**
     * Writes a file into the public Downloads folder through MediaStore.
     *
     * Writing to public storage with a plain File fails on Android 10 and
     * later because of scoped storage. MediaStore is the way that still
     * works, and the file ends up readable by Termux.
     */
    private fun writeToDownloads(activity: Activity, name: String, bytes: ByteArray): Boolean {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val values = android.content.ContentValues().apply {
                    put(android.provider.MediaStore.Downloads.DISPLAY_NAME, name)
                    put(android.provider.MediaStore.Downloads.MIME_TYPE, "text/plain")
                    put(android.provider.MediaStore.Downloads.RELATIVE_PATH,
                        Environment.DIRECTORY_DOWNLOADS + "/autosongs")
                    put(android.provider.MediaStore.Downloads.IS_PENDING, 1)
                }
                val uri = activity.contentResolver.insert(
                    android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                if (uri == null) return false
                activity.contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                values.clear()
                values.put(android.provider.MediaStore.Downloads.IS_PENDING, 0)
                activity.contentResolver.update(uri, values, null, null)
                true
            } else {
                val dir = File(Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_DOWNLOADS), "autosongs")
                if (!dir.exists()) dir.mkdirs()
                File(dir, name).writeBytes(bytes)
                true
            }
        } catch (_: Exception) {
            false
        }
    }

    // ---- where the bridge is -------------------------------------------------

    /**
     * Where the bridge is, in words.
     *
     * The same address - 127.0.0.1:8765 - means two very different things:
     * the bridge inside this app, or a Python program the user runs in
     * Termux. The user has to know which one is answering, because the fix
     * for each one is different.
     */
    fun whereTheBridgeIs(settings: AppSettings): String = when {
        settings.isEmbedded -> "inside the app"
        bridgeIsOnThisPhone(settings) -> "on the phone"
        else -> "at ${settings.bridgeHost}"
    }

    /** True when the bridge is the one running on this phone, in Termux. */
    fun bridgeIsOnThisPhone(settings: AppSettings): Boolean {
        if (settings.isEmbedded) return false
        val host = settings.bridgeHost.trim()
        return host == "127.0.0.1" || host == "localhost" || host == "::1"
    }

    // ---- Termux --------------------------------------------------------------

    /**
     * The phone's own bridge lives in Termux, and Android kills apps that
     * sit in the background. The bridge then dies, and the app sees a
     * connection that opens and closes with nothing on it. The cure is a
     * battery exemption for Termux, and the only place to give one is
     * Termux's own page in the settings.
     */
    fun updateTermuxButton(activity: Activity, settings: AppSettings, button: Button?) {
        if (button == null) return
        if (!bridgeIsOnThisPhone(settings)) {
            button.visibility = View.GONE
            return
        }
        button.visibility = View.VISIBLE
        button.text = if (termuxIsExempt(activity)) "Termux: battery exemption given"
        else "Fix the phone bridge (Termux)"
    }

    private fun termuxIsExempt(activity: Activity): Boolean = try {
        val pm = activity.getSystemService(android.os.PowerManager::class.java)
        pm?.isIgnoringBatteryOptimizations("com.termux") == true
    } catch (_: Throwable) {
        false
    }

    fun openTermuxSettings(activity: Activity) {
        val installed = try {
            activity.packageManager.getPackageInfo("com.termux", 0)
            true
        } catch (_: Throwable) {
            false
        }
        if (!installed) {
            Toast.makeText(activity, "Termux is not installed on this phone",
                Toast.LENGTH_SHORT).show()
            return
        }
        try {
            activity.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", "com.termux", null)))
        } catch (_: Throwable) {
            Toast.makeText(activity, "Could not open Termux's settings",
                Toast.LENGTH_SHORT).show()
        }
    }

    // ---- helpers -------------------------------------------------------------

    private fun client(settings: AppSettings) = BridgeClient(
        settings.bridgeAddress.first,
        settings.bridgeAddress.second,
        settings.bridgeAuthToken,
        settings.bridgeScheme,
        settings.bridgePath
    )

    private fun lifecycleScope(activity: Activity) =
        (activity as? androidx.lifecycle.LifecycleOwner)?.lifecycleScope
            ?: error("this screen is not a lifecycle owner")
}
