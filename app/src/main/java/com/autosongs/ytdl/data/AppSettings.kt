package com.autosongs.ytdl.data

import android.content.Context
import android.content.SharedPreferences

/**
 * All user-tunable options. Backed by SharedPreferences so the watcher service
 * and the UI always read the same source of truth.
 */
class AppSettings private constructor(private val prefs: SharedPreferences) {

    // ---- Bridge connection -------------------------------------------------
    /**
     * Where the bridge lives.
     *
     * "embedded" is the copy inside the app - one app, nothing else to
     * install. "remote" is a bridge on another machine (or in Termux).
     */
    var bridgeMode: String
        get() = prefs.getString(KEY_MODE, BRIDGE_EMBEDDED)!!
        set(v) = prefs.edit().putString(KEY_MODE, v).apply()

    /** True when the bridge inside the app is the one being used. */
    val isEmbedded: Boolean
        get() = bridgeMode == BRIDGE_EMBEDDED

    /** The address of a remote bridge. It is kept even in embedded mode. */
    var bridgeHost: String
        get() = prefs.getString(
            KEY_SAVED_HOST,
            // An older version of the app stored the address under this
            // name. It is still read once, so a remote setup is not lost.
            prefs.getString(KEY_HOST, "127.0.0.1")
        )!!.trim()
        set(v) = prefs.edit().putString(KEY_SAVED_HOST, v.trim()).apply()

    var bridgePort: Int
        get() = if (prefs.contains(KEY_SAVED_PORT)) prefs.getInt(KEY_SAVED_PORT, 8765)
        else prefs.getInt(KEY_PORT, 8765)
        set(v) = prefs.edit().putInt(KEY_SAVED_PORT, v).apply()

    var bridgeToken: String
        get() = prefs.getString(KEY_TOKEN, "")!!.trim()
        set(v) = prefs.edit().putString(KEY_TOKEN, v.trim()).apply()

    /**
     * How the phone reaches the bridge: "http" or "https".
     *
     * A bridge on the same network is plain http. A bridge reached over
     * a tunnel is https - the tunnel gives out an https address, and
     * connecting to it over plain http would not arrive.
     */
    var bridgeScheme: String
        get() = prefs.getString(KEY_SCHEME, "http")!!.trim().ifEmpty { "http" }
        set(v) = prefs.edit().putString(KEY_SCHEME, v.trim().ifEmpty { "http" }).apply()

    /**
     * A prefix under the address, for a tunnel that forwards under a
     * path rather than at the root. Empty for the usual case.
     */
    var bridgePath: String
        get() = prefs.getString(KEY_PATH, "")!!.trim()
        set(v) = prefs.edit().putString(KEY_PATH, v.trim().trimEnd('/')).apply()

    /**
     * The port the bridge inside the app is listening on.
     *
     * It is not always 8765: when something else already has that port - an
     * old Termux bridge, most often - the bridge inside the app takes the
     * next one and writes down which.
     */
    var embeddedPort: Int
        get() = prefs.getInt(KEY_EMBEDDED_PORT, EMBEDDED_PORT)
        set(v) = prefs.edit().putInt(KEY_EMBEDDED_PORT, v).apply()

    /**
     * The address the app actually dials.
     *
     * When the bridge is inside the app it listens on the port it found.
     * When it is somewhere else, it is the address that was entered.
     */
    val bridgeAddress: Pair<String, Int>
        get() = if (isEmbedded) EMBEDDED_HOST to embeddedPort
        else bridgeHost to bridgePort

    /** The token the app sends. The bridge inside the app has none. */
    val bridgeAuthToken: String
        get() = if (isEmbedded) "" else bridgeToken

    // ---- What to download --------------------------------------------------
    var preset: FormatPreset
        get() = FormatPreset.fromId(prefs.getString(KEY_PRESET, FormatPreset.AUDIO_M4A.id)!!)
        set(v) = prefs.edit().putString(KEY_PRESET, v.id).apply()

    var videoQuality: Int
        get() = prefs.getInt(KEY_VIDEO_QUALITY, 1080)
        set(v) = prefs.edit().putInt(KEY_VIDEO_QUALITY, v).apply()

    var embedMetadata: Boolean
        get() = prefs.getBoolean(KEY_EMBED_META, true)
        set(v) = prefs.edit().putBoolean(KEY_EMBED_META, v).apply()

    var embedThumbnail: Boolean
        get() = prefs.getBoolean(KEY_EMBED_THUMB, true)
        set(v) = prefs.edit().putBoolean(KEY_EMBED_THUMB, v).apply()

    // ---- Trigger rules -----------------------------------------------------
    var autoDownload: Boolean
        get() = prefs.getBoolean(KEY_AUTO, true)
        set(v) = prefs.edit().putBoolean(KEY_AUTO, v).apply()

    /** Only trigger once the track has been playing for at least this long (ms). */
    var minPlaybackMs: Long
        get() = prefs.getLong(KEY_MIN_PLAY, 20_000L)
        set(v) = prefs.edit().putLong(KEY_MIN_PLAY, v).apply()

    /** Ignore anything shorter than this (ads, intros, previews). */
    var minDurationSec: Int
        get() = prefs.getInt(KEY_MIN_DUR, 60)
        set(v) = prefs.edit().putInt(KEY_MIN_DUR, v).apply()

    /** A track with the same key is not downloaded again within this window (hours). */
    var dedupeHours: Int
        get() = prefs.getInt(KEY_DEDUPE_H, 72)
        set(v) = prefs.edit().putInt(KEY_DEDUPE_H, v).apply()

    /** Comma separated artist names that must never be downloaded. */
    var artistBlocklist: String
        get() = prefs.getString(KEY_BLOCK, "")!!
        set(v) = prefs.edit().putString(KEY_BLOCK, v).apply()

    /** Comma separated package names to watch. Empty = YouTube Music only. */
    var watchedPackages: String
        get() = prefs.getString(KEY_PACKAGES, DEFAULT_PACKAGES)!!
        set(v) = prefs.edit().putString(KEY_PACKAGES, v).apply()

    /**
     * Watch every app that plays music, not only the ticked ones.
     *
     * A media session is the system's own way of saying "something is
     * playing", and any app that publishes one - Spotify, Apple Music, a
     * browser playing a video - is a music app as far as this one is
     * concerned. The ticked list stays for the times when somebody wants
     * only one or two.
     */
    var watchAllApps: Boolean
        get() = prefs.getBoolean(KEY_WATCH_ALL_APPS, true)
        set(v) = prefs.edit().putBoolean(KEY_WATCH_ALL_APPS, v).apply()

    /**
     * True once the introduction has been shown.
     *
     * The introduction is three lines and two taps, and it is the answer to
     * most of the "it does not work" messages, so it is worth showing once.
     * After that the app gets out of the way.
     */
    var seenIntro: Boolean
        get() = prefs.getBoolean(KEY_SEEN_INTRO, false)
        set(v) = prefs.edit().putBoolean(KEY_SEEN_INTRO, v).apply()

    /**
     * Where a saved song is to end up: on this phone, or on the bridge.
     *
     * A bridge on another machine can keep the song in its own library
     * folder - on a NAS, on a home server, wherever the bridge lives. Then
     * the phone does not store it at all.
     */
    var saveLocation: String
        get() = prefs.getString(KEY_SAVE_LOCATION, SAVE_LOCAL)!!
        set(v) = prefs.edit().putString(KEY_SAVE_LOCATION, v).apply()

    // ---- YouTube sign-in (cookies) ---------------------------------------
    /**
     * The name of the cookie jar the user chose, or empty when there is
     * none.
     *
     * Only the name is kept, never the contents: the jar itself lives in
     * the app's own storage, and its contents are a signed-in session that
     * has no business in a settings file.
     */
    var cookiesFileName: String
        get() = prefs.getString(KEY_COOKIES_NAME, "")!!.trim()
        set(v) = prefs.edit().putString(KEY_COOKIES_NAME, v.trim()).apply()

    // ---- Updates -----------------------------------------------------------
    /**
     * An address of the user's own for the release feed.
     *
     * The hosting gives a new address for every release, so the addresses
     * built into the app are always behind by one release. An address that
     * does not change - a file in a git repository, for instance - can be
     * put here, and the app then hears about a release on the day it comes
     * out, without the app having to be rebuilt.
     */
    var customFeedUrl: String
        get() = prefs.getString(KEY_FEED, "")!!.trim()
        set(v) = prefs.edit().putString(KEY_FEED, v.trim()).apply()

    /** When the app last looked for a newer build (milliseconds). */
    var lastUpdateCheck: Long
        get() = prefs.getLong(KEY_LAST_CHECK, 0L)
        set(v) = prefs.edit().putLong(KEY_LAST_CHECK, v).apply()

    // ---- Storage -----------------------------------------------------------
    var folderName: String
        get() = prefs.getString(KEY_FOLDER, "AutoSongs")!!.trim().ifEmpty { "AutoSongs" }
        set(v) = prefs.edit().putString(KEY_FOLDER, v.trim().ifEmpty { "AutoSongs" }).apply()

    var deleteAfterTransfer: Boolean
        get() = prefs.getBoolean(KEY_DELETE_AFTER, true)
        set(v) = prefs.edit().putBoolean(KEY_DELETE_AFTER, v).apply()

    // ---- Media session matching -------------------------------------------
    /** Require the playing track's artist to match this (empty = accept anything). */
    var requireArtistMatch: Boolean
        get() = prefs.getBoolean(KEY_REQUIRE_ARTIST, false)
        set(v) = prefs.edit().putBoolean(KEY_REQUIRE_ARTIST, v).apply()

    companion object {
        const val DEFAULT_PACKAGES =
            "com.google.android.apps.youtube.music,app.revanced.android.youtube.music"

        /** The bridge runs inside the app. */
        /** The song is saved on this phone. */
        const val SAVE_LOCAL = "local"

        /** The song is saved on the bridge, in its own library folder. */
        const val SAVE_BRIDGE = "bridge"

        const val BRIDGE_EMBEDDED = "embedded"

        /** The bridge runs somewhere else. */
        const val BRIDGE_REMOTE = "remote"

        /** The bridge inside the app always listens here. */
        const val EMBEDDED_HOST = "127.0.0.1"
        const val EMBEDDED_PORT = 8765

        private const val FILE = "autosongs_settings"
        private const val KEY_MODE = "bridge_mode"
        private const val KEY_SAVED_HOST = "bridge_saved_host"
        private const val KEY_SAVED_PORT = "bridge_saved_port"
        private const val KEY_HOST = "bridge_host"
        private const val KEY_PORT = "bridge_port"
        private const val KEY_TOKEN = "bridge_token"
        private const val KEY_SCHEME = "bridge_scheme"
        private const val KEY_PATH = "bridge_path"
        private const val KEY_PRESET = "preset"
        private const val KEY_VIDEO_QUALITY = "video_quality"
        private const val KEY_EMBED_META = "embed_metadata"
        private const val KEY_EMBED_THUMB = "embed_thumbnail"
        private const val KEY_AUTO = "auto_download"
        private const val KEY_MIN_PLAY = "min_playback_ms"
        private const val KEY_MIN_DUR = "min_duration_sec"
        private const val KEY_DEDUPE_H = "dedupe_hours"
        private const val KEY_BLOCK = "artist_blocklist"
        private const val KEY_PACKAGES = "watched_packages"
        private const val KEY_WATCH_ALL_APPS = "watch_all_apps"
        private const val KEY_FOLDER = "folder_name"
        private const val KEY_DELETE_AFTER = "delete_after_transfer"
        private const val KEY_REQUIRE_ARTIST = "require_artist_match"
        private const val KEY_FEED = "custom_feed_url"
        private const val KEY_LAST_CHECK = "last_update_check"
        private const val KEY_EMBEDDED_PORT = "embedded_port"
    private const val KEY_SEEN_INTRO = "seen_intro"
    private const val KEY_SAVE_LOCATION = "save_location"
        private const val KEY_COOKIES_NAME = "cookies_file_name"

        @Volatile
        private var instance: AppSettings? = null

        fun get(context: Context): AppSettings =
            instance ?: synchronized(this) {
                instance ?: AppSettings(
                    context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)
                ).also { instance = it }
            }
    }
}

/**
 * The apps to watch.
 *
 * An empty set means every app that publishes a media session, which is
 * what most people want: Spotify, Apple Music, a browser playing a
 * video - they all report a title and an artist, so there is no reason
 * to make a list of them. The list is for the times when somebody wants
 * only one or two.
 */
fun watchedApps(settings: AppSettings): Set<String> {
    if (settings.watchAllApps) return emptySet()
    return settings.watchedPackages
        .split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
}
