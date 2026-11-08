package com.autosongs.ytdl.data

import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager

/**
 * Finds the YouTube Music variants installed on the device.
 *
 * This matters because the package name is not stable across the ecosystem:
 *   - official YouTube Music      -> com.google.android.apps.youtube.music
 *   - ReVanced Extended (re-signed, so it must rename itself)
 *                                -> app.revanced.android.youtube.music
 *   - other forks                 -> com.mods.openmusic, app.venom, ...
 *
 * Hard-coding one name means the app silently watches nothing, so we discover
 * the installed ones instead.
 */
object MusicApps {

    /** Package names that are always watched. */
    val ALWAYS = listOf(
        "com.google.android.apps.youtube.music",
        "app.revanced.android.youtube.music"
    )

    private val LOOKING_LIKE = listOf(
        "youtube.music",
        "youtubemusic",
        "openmusic",
        "venom",
        "music.youtube",
        "tubemusic"
    )

    /**
     * The apps people listen music in, and the browsers that play it.
     *
     * This is not a whitelist - the app watches whatever publishes a
     * media session, so an app that is not on this list works as well.
     * The list is here so the settings screen can show something a
     * person can read instead of a list of every package on the phone.
     */
    val POPULAR: List<Pair<String, String>> = listOf(
        // music
        "com.spotify.music" to "Spotify",
        "com.apple.android.music" to "Apple Music",
        "com.google.android.apps.youtube.music" to "YouTube Music",
        "app.revanced.android.youtube.music" to "YouTube Music (ReVanced)",
        "com.google.android.youtube" to "YouTube",
        "com.deezer.android.app" to "Deezer",
        "com.tidal.hifi" to "Tidal",
        "com.soundcloud.android" to "SoundCloud",
        "com.pandora.android" to "Pandora",
        "com.amazon.mp3" to "Amazon Music",
        "com.qobuz.music" to "Qobuz",
        "com.musixmatch.music" to "Musixmatch",
        "com.mixcloud.player" to "Mixcloud",
        "com.google.android.music" to "Google Play Music",
        "com.htc.music" to "HTC Music",
        "com.samsung.android.app.music" to "Samsung Music",
        "com.sec.android.app.smusic" to "Samsung Music",
        "com.oneplus.music" to "OnePlus Music",
        "com.miui.player" to "Mi Music",
        "com.opera.music" to "Opera Music",
        "com.maxmpz.audioplayer" to "Poweramp",
        "com.neutroncode.mp" to "Neutron",
        "org.videolan.vlc" to "VLC",
        "com.mxtech.videoplayer.ad" to "VLC",
        // browsers - they play YouTube, Spotify and everything else
        "com.android.chrome" to "Chrome",
        "com.chrome.beta" to "Chrome Beta",
        "com.chrome.dev" to "Chrome Dev",
        "com.mozilla.firefox" to "Firefox",
        "org.mozilla.fenix" to "Firefox Nightly",
        "com.microsoft.emmx" to "Edge",
        "com.microsoft.msedge" to "Edge",
        "com.brave.browser" to "Brave",
        "com.opera.browser" to "Opera",
        "com.opera.mini.native" to "Opera Mini",
        "com.vivaldi.browser" to "Vivaldi",
        "com.duckduckgo.mobile.android" to "DuckDuckGo",
        "com.sec.android.app.sbrowser" to "Samsung Internet",
        "org.torproject.torbrowser" to "Tor Browser",
        "com.UCMobile.intl" to "UC Browser",
        "com.UCMobile.browser" to "UC Browser",
        "com.kiwibrowser.browser" to "Kiwi Browser",
        "com.yandex.browser" to "Yandex Browser",
        "com.yandex.browser.lite" to "Yandex Browser",
        "com.mmbox.xbrowser" to "X Browser",
        "com.oupeng.cm.browser" to "CM Browser"
    ).filter { it.second.isNotBlank() }

    /**
     * The apps that are playing something right now.
     *
     * These are the ones that matter: whatever is on the phone at this
     * moment is what the user is listening to.
     */
    fun liveApps(context: Context): List<String> =
        runCatching {
            com.autosongs.ytdl.media.MediaSessionProbe
                .controllers(context)
                ?.map { it.packageName }
                ?.filter { it.isNotBlank() }
                ?.distinct()
                ?: emptyList()
        }.getOrDefault(emptyList())

    /**
     * Every app worth offering: the well known music apps and browsers
     * that are installed, the apps that are playing something right now,
     * and the YouTube Music clients - whose package names are not stable.
     */
    fun detect(context: Context): List<DetectedApp> {
        val pm = context.packageManager
        val result = linkedMapOf<String, DetectedApp>()

        fun add(pkg: String, name: String, known: Boolean) {
            if (pkg.isBlank() || result.containsKey(pkg)) return
            result[pkg] = DetectedApp(pkg, name, known)
        }

        try {
            val packages = pm.getInstalledApplications(PackageManager.GET_META_DATA)
            val installed = packages.associateBy { it.packageName }
            for ((pkg, name) in POPULAR) {
                val app = installed[pkg] ?: continue
                add(pkg, label(pm, app), true)
            }
            for (app in packages) {
                val pkg = app.packageName
                if (pkg.contains("android", ignoreCase = true) &&
                    pkg.startsWith("com.android", ignoreCase = true)
                ) {
                    continue
                }
                if (ALWAYS.any { it.equals(pkg, ignoreCase = true) }) {
                    add(pkg, label(pm, app), true)
                    continue
                }
                val low = pkg.lowercase()
                if (LOOKING_LIKE.any { low.contains(it) }) {
                    add(pkg, label(pm, app), false)
                }
            }
        } catch (t: Throwable) {
            // the list is a convenience; the app does not depend on it
        }

        // Whatever is playing right now, whatever it is.
        for (pkg in liveApps(context)) {
            val app = runCatching {
                pm.getApplicationInfo(pkg, 0)
            }.getOrNull()
            add(pkg, if (app != null) label(pm, app) else pkg, false)
        }

        return result.values.sortedBy { it.packageName }
    }

    private fun label(pm: PackageManager, app: ApplicationInfo): String =
        runCatching { pm.getApplicationLabel(app).toString() }
            .getOrDefault(app.packageName)

    data class DetectedApp(
        val packageName: String,
        val label: String,
        val isKnown: Boolean
    )
}
