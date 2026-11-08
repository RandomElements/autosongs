package com.autosongs.ytdl.bridge

import android.content.Context
import android.net.Uri
import android.util.Log
import com.autosongs.ytdl.data.AppSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * The cookie jar the app keeps, and the bridge's copy of it.
 *
 * YouTube sometimes answers with "Sign in to confirm you're not a bot"
 * instead of the video. The cure is a cookie jar: the file a signed-in
 * browser can export. yt-dlp then looks like that browser, and the
 * refusal does not happen.
 *
 * The jar is copied into the app's own storage rather than kept as a
 * content URI. A URI can stop resolving - the user moves the file, the
 * picker permission expires - and the bridge inside the app can read the
 * app's own files directly, so a copy is both more reliable and simpler.
 *
 * The jar's contents are sent to the bridge over HTTP. For the bridge
 * inside the app that is 127.0.0.1 and harmless. For a bridge on another
 * machine it travels over the same link the downloads themselves use, and
 * the user is the one who chose to pair with that bridge.
 */
object CookieStore {

    private const val TAG = "CookieStore"

    /** The file the chosen jar is copied into. */
    private fun jarFile(context: Context): File =
        File(File(context.filesDir, "autosongs"), "cookies.txt")

    /**
     * Copies a jar the user picked into the app's storage.
     *
     * Returns the file, or null when the file could not be read - a jar
     * the app cannot read is no use to it.
     */
    suspend fun importJar(context: Context, source: Uri): File? =
        withContext(Dispatchers.IO) {
            try {
                val text = context.contentResolver.openInputStream(source)
                    ?.use { it.readBytes().toString(Charsets.UTF_8) }
                    ?: return@withContext null
                if (!looksLikeAJar(text)) {
                    Log.w(TAG, "the file that was chosen is not a cookie jar")
                    return@withContext null
                }
                val file = jarFile(context)
                file.parentFile?.mkdirs()
                file.writeText(text)
                // The jar holds a signed-in session. Nobody else on the
                // phone has any business reading it.
                try {
                    file.setReadable(false, false)
                    file.setReadable(true, true)
                } catch (_: Exception) {
                    // Not every filesystem lets the owner change this.
                }
                AppSettings.get(context).cookiesFileName = source.lastPathSegment
                    ?.substringAfterLast('/')
                    ?: "cookies.txt"
                Log.i(TAG, "a cookie jar was chosen and is now in the app's storage")
                file
            } catch (t: Throwable) {
                Log.w(TAG, "the cookie jar could not be read", t)
                null
            }
        }

    /**
     * True when the text looks like a cookie jar.
     *
     * A cookie jar starts with a comment line saying what it is. A file
     * that is not one would make every download fail in a way that is
     * much harder to explain than "that is not a cookies.txt file".
     */
    fun looksLikeAJar(text: String): Boolean =
        text.contains("Netscape HTTP Cookie File") ||
            text.lines().any { it.trimStart().startsWith("#HttpOnly_") }

    /** The jar's contents, or null when there is none. */
    suspend fun jarText(context: Context): String? = withContext(Dispatchers.IO) {
        val file = jarFile(context)
        if (!file.isFile) null else try {
            file.readText()
        } catch (_: Throwable) {
            null
        }
    }

    /** Whether the app has a jar of its own. */
    fun hasJar(context: Context): Boolean = jarFile(context).isFile

    /** Forgets the jar. The file goes with it. */
    suspend fun forget(context: Context) = withContext(Dispatchers.IO) {
        try {
            jarFile(context).delete()
        } catch (_: Throwable) {
            // Nothing to do - the jar is gone either way.
        }
        AppSettings.get(context).cookiesFileName = ""
    }

    /**
     * Hands the jar to the bridge and returns what the bridge says.
     *
     * The bridge writes the jar into its work folder and uses it from then
     * on, so it is found again after a restart without being sent twice.
     */
    suspend fun sendToBridge(
        context: Context,
        client: BridgeClient
    ): Result<String> {
        val text = jarText(context)
            ?: return Result.failure(IllegalStateException("there is no cookie jar"))
        return client.pushCookies(text)
    }
}
