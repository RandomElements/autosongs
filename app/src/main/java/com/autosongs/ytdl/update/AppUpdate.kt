package com.autosongs.ytdl.update

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * One release, as the feed describes it.
 */
data class Release(
    val versionName: String,
    val versionCode: Int,
    val notes: String,
    val apkUrl: String,
    val sha256: String,
    val published: String,
    val hosts: List<String>
)

/**
 * The release feed.
 *
 * Every release publishes a version.json next to the APK. The app asks
 * every address it knows, takes the newest answer it gets, and compares it
 * with the build that is running.
 *
 * There is one address, and it does not change: the user's own server.
 *
 * The list used to grow with every release, because the hosting handed out
 * a new address each time something was published and the old ones died
 * one by one. The app then spent a timeout on every dead address before
 * it got to the live one, and a phone that had been away for a while
 * never saw the newest release at all.
 *
 * A feed can still name other addresses, and that is worth keeping: an
 * address that never changes (a file in a git repository, for instance)
 * can be put in the settings and the app hears about a release on the day
 * it comes out, without anyone having to rebuild the app.
 */
object AppUpdate {

    /**
     * Where the feed has been published, newest first.
     */
    val FEED_URLS: List<String> = listOf(
        "https://autosongs.example/version.json"
    )

    /**
     * Reads one answer from the feed.
     *
     * An answer that says something unexpected is ignored rather than
     * trusted. The app downloads what this file says, so it may not be
     * talked into downloading something because a broken or hostile file
     * said so. Only https is accepted: a plain http address would let
     * anyone on the network swap the file that gets fetched.
     *
     * [feedUrl] is the address the answer came from. It is used to work out
     * where the APK is when the answer does not say, so the same feed
     * works wherever it is published.
     */
    fun parse(json: String, feedUrl: String? = null): Release? {
        return try {
            val obj = JSONObject(json)
            val code = obj.optInt("versionCode", 0)
            if (code <= 0) return null
            val versionName = obj.optString("versionName", "")
            val given = obj.optString("apkUrl", "").trim()
            val url = when {
                given.startsWith("https://") -> given
                given.isEmpty() && feedUrl != null && feedUrl.startsWith("https://") &&
                    versionName.isNotEmpty() ->
                    feedUrl.substringBeforeLast('/') + "/AutoSongs-" + versionName + ".apk"
                else -> return null
            }
            val hosts = ArrayList<String>()
            val array = obj.optJSONArray("hosts")
            if (array != null) {
                for (i in 0 until array.length()) {
                    val host = array.optString(i, "").trim()
                    if (host.startsWith("https://")) hosts.add(host)
                }
            }
            Release(
                versionName = versionName,
                versionCode = code,
                notes = obj.optString("notes", ""),
                apkUrl = url,
                sha256 = obj.optString("sha256", ""),
                published = obj.optString("published", ""),
                hosts = hosts
            )
        } catch (_: Exception) {
            null
        }
    }

    /** True when the release is newer than the build that is running. */
    fun isNewer(release: Release, currentVersionCode: Int): Boolean =
        release.versionCode > currentVersionCode

    /**
     * The newest release any of the addresses knows about.
     *
     * Addresses named by a feed are followed as well, so an address that
     * was published later can still be found through an older feed.
     */
    suspend fun fetchNewest(extraUrls: List<String> = emptyList()): Release? =
        withContext(Dispatchers.IO) {
            var best: Release? = null
            val seen = LinkedHashSet<String>()
            val queue = java.util.ArrayDeque<String>()
            (extraUrls + FEED_URLS)
                .map { it.trim() }
                .filter { it.isNotEmpty() }
                .forEach { queue.add(it) }

            while (queue.isNotEmpty() && seen.size < 40) {
                val url = queue.removeFirst()
                if (!seen.add(url)) continue
                val release = fetch(url) ?: continue
                if (best == null || release.versionCode > best!!.versionCode) {
                    best = release
                }
                for (host in release.hosts) {
                    val feed = host.trimEnd('/') + "/version.json"
                    if (!seen.contains(feed)) queue.add(feed)
                }
            }
            best
        }

    private fun fetch(url: String): Release? = try {
        val request = Request.Builder().url(url).get().build()
        val client = OkHttpClient.Builder()
            .callTimeout(15, TimeUnit.SECONDS)
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) null
            else parse(response.body?.string().orEmpty(), url)
        }
    } catch (_: Exception) {
        null
    }
}
