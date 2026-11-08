package com.autosongs.ytdl.bridge

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Client for the yt-dlp bridge — a tiny HTTP service that wraps the real
 * `yt-dlp` binary (running in Termux on the same phone, or on a LAN machine).
 *
 * API:
 *   GET  /health                -> {"ok":true,"yt_dlp":"2025.01.01"}
 *   POST /search  {query,...}   -> {"id":"...","title":"...","url":"..."}
 *   GET  /job/{id}              -> {"status":"downloading|done|error","percent":42,"file":"...","title":"..."}
 *   GET  /file/{id}             -> raw media bytes
 *   GET  /cookies               -> {"cookies":true,"source":"..."}
 *   POST /cookies               -> hands the bridge a cookie jar
 */
class BridgeClient(
    private val host: String,
    private val port: Int,
    private val token: String,
    /**
     * "http" or "https".
     *
     * A bridge that is reached over a tunnel is https. Talking to it in
     * plain http would not arrive, and talking to a bridge on the local
     * network in https would not either - so this follows whatever the
     * bridge itself says.
     */
    private val scheme: String = "http",
    /**
     * A prefix under the address, for a tunnel that forwards under a
     * path rather than at the root.
     */
    private val path: String = ""
) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    /**
     * Where the bridge is.
     *
     * The port is left out when it is the one the scheme already means,
     * so an address reads the way a person would write it.
     */
    private val baseUrl: String
        get() {
            val defaultPort = if (scheme == "https") 443 else 80
            val portPart = if (port == defaultPort) "" else ":$port"
            val pathPart = if (path.isEmpty()) "" else "/${path.trim('/')}"
            return "$scheme://$host$portPart$pathPart"
        }

    /**
     * Runs a request and turns the outcome into a [Result].
     *
     * [CancellationException] is rethrown on purpose: [runCatching] would
     * swallow it, so a cancelled download would keep running to the end and
     * the socket would only close long after the app moved on.
     */
    private suspend fun <T> api(block: suspend () -> T): Result<T> =
        withContext(Dispatchers.IO) {
            try {
                Result.success(block())
            } catch (ce: CancellationException) {
                throw ce
            } catch (t: Throwable) {
                Result.failure(t)
            }
        }

    /** Executes the call and suspends until it completes, cancellably. */
    private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
        enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (!cont.isCancelled) cont.resumeWithException(e)
            }

            override fun onResponse(call: Call, response: Response) {
                cont.resume(response)
            }
        })
        cont.invokeOnCancellation {
            try {
                cancel()
            } catch (_: Throwable) {
                // nothing useful to do
            }
        }
    }

    private fun authed(builder: Request.Builder): Request.Builder {
        if (token.isNotEmpty()) builder.header("X-Auth-Token", token)
        return builder
    }

    /**
     * The bridge's own words about itself.
     *
     * @param ytDlpFallback the version to use when the bridge cannot say.
     *   The bridge inside the app cannot always tell which yt-dlp it is
     *   using - the number lives in the Python library, and the library
     *   does not always hand it over. The app knows, because the app is
     *   the one that put the library there.
     */
    suspend fun health(ytDlpFallback: String? = null): Result<String> = api {
            val request = authed(Request.Builder().url("$baseUrl/health")).get().build()
            client.newCall(request).await().use { response ->
                if (!response.isSuccessful) error(httpError(response))
                val body = response.body?.string().orEmpty()
                val json = JSONObject(body)
                val said = json.optString("yt_dlp", "").trim()
                val ytdlp = said.takeIf { it.isNotEmpty() && it != "unknown" }
                    ?: ytDlpFallback?.takeIf { it.isNotEmpty() }
                    ?: "unknown"
                val version = json.optString("version", "old")
                // Inside the app there is no ffmpeg and none is needed -
                // the phone does the encoding and the joining itself. So
                // it says that, instead of saying something is missing.
                val encoding = when {
                    json.optBoolean("ffmpeg", false) -> "ffmpeg ok"
                    !json.optBoolean("ffmpeg_needed", true) ->
                        "the phone does the encoding"
                    else -> "ffmpeg missing"
                }
                "yt-dlp $ytdlp · bridge $version · $encoding"
            }
    }

    /**
     * The reason a request failed, with the bridge's own words.
     *
     * "HTTP 500" on its own tells nobody anything. The bridge explains
     * itself in the body when something goes wrong, and that explanation
     * is the only clue there is.
     */
    private fun httpError(response: Response): String {
        val detail = try {
            response.body?.string().orEmpty().trim().take(300)
        } catch (_: Throwable) {
            ""
        }
        return if (detail.isEmpty()) "HTTP ${response.code}"
        else "HTTP ${response.code} — $detail"
    }

    /** The bridge's own version, e.g. "1.3.8". */
    suspend fun bridgeVersion(): Result<String> = api {
            val request = authed(Request.Builder().url("$baseUrl/health")).get().build()
            client.newCall(request).await().use { response ->
                if (!response.isSuccessful) error(httpError(response))
                val body = response.body?.string().orEmpty()
                JSONObject(body).optString("version", "old")
        }
    }

    /** Ask the bridge to start a download. Returns the job id. */
    suspend fun startJob(
        query: String,
        title: String,
        artist: String,
        presetId: String,
        videoQuality: Int,
        embedMetadata: Boolean,
        embedThumbnail: Boolean,
        expectedDurationSec: Long,
        save: String = "local"
    ): Result<String> = api {
            val payload = JSONObject()
                .put("query", query)
                .put("title", title)
                .put("artist", artist)
                .put("preset", presetId)
                .put("video_quality", videoQuality)
                .put("embed_metadata", embedMetadata)
                .put("embed_thumbnail", embedThumbnail)
                .put("expected_duration", expectedDurationSec)
                .put("save", save)
            val body = payload.toString().toRequestBody("application/json".toMediaType())
            val request = authed(Request.Builder().url("$baseUrl/search")).post(body).build()
            client.newCall(request).await().use { response ->
                if (!response.isSuccessful) error("HTTP ${response.code}")
                val json = JSONObject(response.body?.string().orEmpty())
                json.optString("id").takeIf { it.isNotEmpty() } ?: error("no job id returned")
            }
    }

    /**
     * Asks the bridge to fetch a newer version of itself and restart.
     *
     * The bridge keeps a copy of itself up to date, so a fix does not need
     * the phone to install anything again.
     */
    suspend fun updateBridge(code: String? = null): Result<String> = api {
            val payload = JSONObject()
            if (!code.isNullOrBlank()) payload.put("code", code)
            val body = payload.toString().toRequestBody("application/json".toMediaType())
            val request = authed(Request.Builder().url("$baseUrl/update")).post(body).build()
            client.newCall(request).await().use { response ->
                if (!response.isSuccessful) error("HTTP ${response.code}")
                val json = JSONObject(response.body?.string().orEmpty())
                when (json.optString("state", "unknown")) {
                    "updating" -> "updating to ${json.optString("remote")}, the bridge restarts in a moment"
                    "current" -> "the bridge is up to date (${json.optString("remote")})"
                    "error" -> "the update failed: ${json.optString("error")}"
                    else -> "the bridge answered: ${json.optString("state")}"
                }
            }
    }

    /**
     * Hands the bridge a cookie jar.
     *
     * YouTube sometimes answers with "Sign in to confirm you're not a bot"
     * instead of the video. A cookie jar - the file a signed-in browser can
     * export - is what gets past it, and the bridge uses it from then on.
     *
     * The jar's contents cross the network to the bridge. For the bridge
     * inside the app that is 127.0.0.1 and harmless; for a bridge on
     * another machine it is the same link the downloads themselves use.
     */
    suspend fun pushCookies(text: String): Result<String> = api {
        val payload = JSONObject().put("cookies", text)
        val body = payload.toString().toRequestBody("application/json".toMediaType())
        val request = authed(Request.Builder().url("$baseUrl/cookies")).post(body).build()
        client.newCall(request).await().use { response ->
            if (!response.isSuccessful) error(httpError(response))
            val json = JSONObject(response.body?.string().orEmpty())
            json.optString("source").ifBlank { "the file you chose" }
        }
    }

    /** Takes the cookie jar away again. */
    suspend fun clearCookies(): Result<String> = api {
        val payload = JSONObject().put("clear", true)
        val body = payload.toString().toRequestBody("application/json".toMediaType())
        val request = authed(Request.Builder().url("$baseUrl/cookies")).post(body).build()
        client.newCall(request).await().use { response ->
            if (!response.isSuccessful) error(httpError(response))
            val json = JSONObject(response.body?.string().orEmpty())
            json.optString("source")
        }
    }

    /**
     * What the bridge knows about cookies.
     *
     * The bridge looks for a jar on its own, so the app asks rather than
     * guesses - the answer says where the jar came from.
     */
    suspend fun cookieStatus(): Result<CookieStatus> = api {
        val request = authed(Request.Builder().url("$baseUrl/cookies")).get().build()
        client.newCall(request).await().use { response ->
            if (!response.isSuccessful) error(httpError(response))
            val json = JSONObject(response.body?.string().orEmpty())
            CookieStatus(
                available = json.optBoolean("cookies", false),
                source = json.optString("source", "")
            )
        }
    }

    suspend fun jobStatus(id: String): Result<JobStatus> = api {
            val request = authed(Request.Builder().url("$baseUrl/job/$id")).get().build()
            client.newCall(request).await().use { response ->
                if (!response.isSuccessful) error("HTTP ${response.code}")
                val json = JSONObject(response.body?.string().orEmpty())
                JobStatus(
                    id = id,
                    status = json.optString("status", "unknown"),
                    percent = json.optInt("percent", 0),
                    title = json.optString("title"),
                    artist = json.optString("artist"),
                    error = json.optString("error"),
                    hasFile = json.optBoolean("has_file", false),
                    parts = json.optBoolean("parts", false),
                    audioExt = json.optString("audio_ext", ""),
                    thumbnail = json.optString("thumbnail", ""),
                    savedAt = json.optString("saved_at", ""),
                    note = json.optString("note"),
                    needsCookies = json.optBoolean("needs_cookies", false)
                )
            }
    }

    /** Downloads the finished file to [target]; returns the file and its server-side name. */
    suspend fun downloadFile(id: String, target: File): Result<DownloadedFile> =
        fetch(Request.Builder().url("$baseUrl/file/$id"), target)

    /**
     * Downloads one piece of a finished job: the picture or the sound.
     *
     * A video that was downloaded inside the app arrives in two pieces,
     * because joining them needs ffmpeg and an app cannot run one. The
     * phone joins them itself, with MediaMuxer.
     */
    suspend fun downloadFilePart(
        id: String,
        part: String,
        target: File
    ): Result<DownloadedFile> =
        fetch(Request.Builder().url("$baseUrl/file/$id?part=$part"), target)

    /**
     * Asks the bridge for a finished download by name.
     *
     * The bridge keeps its job list in memory, so a restart (running the
     * setup script again, for example) throws it away while the finished
     * file stays on disk. Without this the app reports "HTTP 404" for a
     * download that actually worked.
     */
    suspend fun downloadByName(name: String, target: File): Result<DownloadedFile> {
        val encoded = URLEncoder.encode(name, "UTF-8")
        return fetch(Request.Builder().url("$baseUrl/find?name=$encoded"), target)
    }

    private suspend fun fetch(builder: Request.Builder, target: File): Result<DownloadedFile> = api {
            client.newCall(authed(builder).get().build()).await().use { response ->
                if (!response.isSuccessful) error("HTTP ${response.code}")
                target.parentFile?.mkdirs()
                response.body?.byteStream()?.use { input ->
                    target.outputStream().use { output -> input.copyTo(output) }
                } ?: error("empty body")

                val disposition = response.header("Content-Disposition").orEmpty()
                val serverName = Regex("filename=\"([^\"]+)\"").find(disposition)?.groupValues?.get(1)
                    ?: response.header("X-File-Name").orEmpty()
                DownloadedFile(target, serverName)
            }
    }
}

/**
 * What the bridge knows about the cookie jar it is using.
 *
 * @param available whether there is a jar at all.
 * @param source where it came from, in the bridge's own words.
 */
data class CookieStatus(
    val available: Boolean,
    val source: String
)

data class DownloadedFile(
    val file: File,
    val serverName: String
) {
    val extension: String
        get() = serverName.substringAfterLast('.', "").lowercase()
}

data class JobStatus(
    val id: String,
    val status: String,
    val percent: Int,
    val title: String,
    val artist: String,
    val error: String,
    val hasFile: Boolean,
    /** True when the job produced a picture and a sound instead of one file. */
    val parts: Boolean = false,
    /** Where the bridge put the song, when it was to be kept there. */
    val savedAt: String = "",
    /** The extension of the sound the bridge handed over, e.g. ".m4a". */
    val audioExt: String = "",
    /** Where the cover picture is, when the bridge found one. */
    val thumbnail: String = "",
    /** Something the bridge wants to say about what it did. */
    val note: String = "",
    /**
     * True when the job was refused because YouTube wanted a sign-in.
     *
     * This is the cue to offer the user their cookie jar and try again -
     * the jar is what gets past that refusal.
     */
    val needsCookies: Boolean = false
) {
    /** Human readable state, safe to show in a notification. */
    val displayState: String
        get() = when {
            status.equals("done", true) -> "done"
            status.equals("error", true) -> error.ifBlank { "failed" }
            status.equals("searching", true) -> "searching"
            else -> status
        }

    val isDone get() = status.equals("done", true)
    val isError get() = status.equals("error", true)
}
