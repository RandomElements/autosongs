package com.autosongs.ytdl.embedded

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.ZipInputStream

/**
 * Keeps yt-dlp up to date.
 *
 * YouTube breaks yt-dlp every few months. An old yt-dlp cannot download
 * anything at all, and the symptom is "HTTP Error 403: Forbidden", which
 * looks like a network problem rather than a version problem - so it cost
 * us a lot of guessing before it was understood.
 *
 * The app therefore looks up the newest yt-dlp and puts it in front of the
 * one that came with the APK. The newer one is a single pure-Python file
 * tree, so it is a small download and it needs nothing else.
 */
object YtDlpUpdater {

    private const val TAG = "YtDlpUpdater"
    private const val PYPI = "https://pypi.org/pypi/yt-dlp"

    /** The newest yt-dlp there is, or null if PyPI cannot be reached. */
    suspend fun latestVersion(): String? = withContext(Dispatchers.IO) {
        try {
            val body = URL("$PYPI/json").readText()
            val info = JSONObject(body).optJSONObject("info") ?: return@withContext null
            info.optString("version").takeIf { it.isNotBlank() }
        } catch (t: Throwable) {
            Log.w(TAG, "the newest yt-dlp could not be looked up", t)
            null
        }
    }

    /**
     * Brings yt-dlp up to date if it is behind.
     *
     * Returns the version that is now in use, or null when nothing changed
     * or the download failed. A failure here is never fatal: the bundled
     * yt-dlp still works, it is just older.
     */
    suspend fun update(context: Context): String? = withContext(Dispatchers.IO) {
        try {
            val newest = latestVersion() ?: return@withContext null
            val current = EmbeddedBridge.ytDlpVersion()
            if (!isOlder(current, newest)) return@withContext null

            val root = File(context.filesDir, "ytdlp")
            if (!root.exists()) root.mkdirs()
            val wheel = File(root, "yt_dlp-$newest.whl")
            if (!wheel.exists() || wheel.length() < 100_000L) {
                val url = wheelUrl(newest) ?: return@withContext null
                download(url, wheel)
            }
            val site = File(root, "site")
            if (site.exists()) site.deleteRecursively()
            unpack(wheel, site)
            if (!EmbeddedBridge.useYtDlpAt(site)) return@withContext null
            Log.i(TAG, "yt-dlp is now $newest")
            newest
        } catch (t: Throwable) {
            Log.w(TAG, "yt-dlp could not be updated", t)
            null
        }
    }

    /**
     * True when "current" is older than "newest".
     *
     * The versions are dates - 2026.06.09 and 2026.10.26 - so they are
     * compared as numbers. As text, October would come before August and
     * the comparison would be wrong.
     */
    fun isOlder(current: String, newest: String): Boolean {
        val a = numbers(current)
        val b = numbers(newest)
        if (a == null || b == null) return false
        return compare(a, b) < 0
    }

    /** Compares two versions as numbers, not as text. */
    private fun compare(a: Triple<Int, Int, Int>, b: Triple<Int, Int, Int>): Int {
        val year = a.first.compareTo(b.first)
        if (year != 0) return year
        val month = a.second.compareTo(b.second)
        if (month != 0) return month
        return a.third.compareTo(b.third)
    }

    private fun numbers(version: String): Triple<Int, Int, Int>? {
        val found = Regex("\\d+").findAll(version).take(3).map { it.value.toIntOrNull() ?: 0 }
            .toList()
        if (found.size < 3) return null
        return Triple(found[0], found[1], found[2])
    }

    private fun wheelUrl(version: String): String? = try {
        val body = URL("$PYPI/$version/json").readText()
        val urls: JSONArray = JSONObject(body).optJSONArray("urls") ?: return null
        var found: String? = null
        for (i in 0 until urls.length()) {
            val entry = urls.getJSONObject(i)
            if (entry.optString("packagetype") == "bdist_wheel") {
                found = entry.optString("url")
                break
            }
        }
        found
    } catch (t: Throwable) {
        Log.w(TAG, "the download address for yt-dlp could not be found", t)
        null
    }

    private fun download(url: String, into: File) {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 20000
        connection.readTimeout = 120000
        connection.instanceFollowRedirects = true
        try {
            connection.inputStream.use { input ->
                into.outputStream().use { output -> input.copyTo(output) }
            }
        } finally {
            connection.disconnect()
        }
    }

    /** A wheel is a zip file. */
    private fun unpack(wheel: File, into: File) {
        if (!into.exists()) into.mkdirs()
        val root = into.canonicalFile
        ZipInputStream(wheel.inputStream().buffered()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                val target = File(into, entry.name)
                // Never write outside the folder, whatever the file says.
                if (!target.canonicalFile.path.startsWith(root.path)) {
                    zip.closeEntry()
                    continue
                }
                if (entry.isDirectory) {
                    target.mkdirs()
                } else {
                    target.parentFile?.mkdirs()
                    target.outputStream().use { output -> zip.copyTo(output) }
                }
                zip.closeEntry()
            }
        }
    }
}
