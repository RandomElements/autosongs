package com.autosongs.ytdl.bridge

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Asks AutoSongs where a bridge is, when it is not on this network.
 *
 * The bridge shows eight characters and keeps saying, to AutoSongs' own
 * service, where those characters are and what key goes with them. The
 * phone sends the characters and is told the address - so a bridge behind
 * a router, on a phone network or on the other side of the world is
 * reachable without forwarding a port or knowing an address.
 *
 * Nothing is kept here: the service only answers while the bridge is
 * running, and it answers with the same key the bridge would have given
 * over the network.
 */
object OnlinePairing {

    private const val TAG = "OnlinePairing"

    /** Where the pairing service is. One address, and it is AutoSongs' own. */
    val SERVICES = listOf("https://autosongs.org/api/paird/pair")

    /** What the service said: where the bridge is, and the key to it. */
    data class Answer(
        val host: String,
        val port: Int,
        val token: String,
        val scheme: String,
        val path: String
    )

    /**
     * Looks up eight characters.
     *
     * @return the bridge, or null when the service does not know the code -
     *   which is what a bridge that is not running, an expired code, or no
     *   internet at all looks like. Callers fall back to the network.
     */
    suspend fun resolve(code: String): Answer? = withContext(Dispatchers.IO) {
        val wanted = runCatching { PairCode.normalize(code) }.getOrNull() ?: return@withContext null
        if (wanted.length != 8) return@withContext null

        for (service in SERVICES) {
            val answer = try {
                ask(service, wanted)
            } catch (t: Throwable) {
                Log.i(TAG, "the pairing service did not answer: ${t.message}")
                continue
            }
            if (answer != null) {
                Log.i(TAG, "the pairing service knows ${wanted}: ${answer.scheme}://${answer.host}")
                return@withContext answer
            }
        }
        null
    }

    private fun ask(service: String, code: String): Answer? {
        val connection = (URL(service).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 8000
            readTimeout = 8000
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
        }
        try {
            val body = JSONObject().put("code", code).toString()
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (status == 404) return null          // no bridge is running with that code
            if (status != HttpURLConnection.HTTP_OK) {
                Log.i(TAG, "the service answered $status: $text")
                return null
            }
            val json = JSONObject(text)
            val url = json.optString("url")
            val token = json.optString("key")
            if (url.isBlank() || token.isBlank()) return null
            return fromUrl(url, token)
        } finally {
            connection.disconnect()
        }
    }

    /** Splits the address the service gave into the parts the app stores. */
    internal fun fromUrl(url: String, token: String): Answer? = try {
        val parsed = URL(url)
        val scheme = parsed.protocol.lowercase()
        val port = if (parsed.port > 0) parsed.port else if (scheme == "https") 443 else 80
        Answer(
            host = parsed.host,
            port = port,
            token = token,
            scheme = scheme,
            path = parsed.path.orEmpty().trimEnd('/')
        )
    } catch (t: Throwable) {
        Log.w(TAG, "the service gave an address that cannot be used: $url", t)
        null
    }
}
