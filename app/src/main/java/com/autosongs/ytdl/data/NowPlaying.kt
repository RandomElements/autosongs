package com.autosongs.ytdl.data

import android.graphics.Bitmap

/** A track currently playing in a watched app. */
data class NowPlaying(
    val packageName: String,
    val title: String,
    val artist: String,
    val album: String,
    val durationMs: Long,
    val artwork: Bitmap? = null
) {
    /** Stable key used for dedupe across loops. */
    val key: String get() = "$packageName|${title.lowercase().trim()}"

    val searchQuery: String
        get() = if (artist.isBlank()) title else "$artist - $title"

    val displayName: String
        get() = if (artist.isBlank()) title else "$artist - $title"
}
