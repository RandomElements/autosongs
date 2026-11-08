package com.autosongs.ytdl.bridge

/**
 * Reads the bridge's health answer and turns it into something a person can
 * act on.
 *
 * The important case is an yt-dlp that is too old for YouTube. Every
 * download then fails with "HTTP Error 403: Forbidden", which looks like a
 * network fault rather than a version problem, so the user never suspects
 * the version and never updates it.
 */
object BridgeHealth {

    /**
     * Returns a sentence explaining that yt-dlp is too old, or null when
     * there is nothing to say.
     */
    fun outdatedYtDlpMessage(health: String?): String? {
        if (health.isNullOrBlank()) return null
        if (!health.contains("\"yt_dlp_outdated\": true")) return null
        val min = value(health, "yt_dlp_min") ?: DEFAULT_MIN
        val version = value(health, "yt_dlp") ?: "unknown"
        return "yt-dlp $version is too old for YouTube (needs $min or newer).\n" +
            "Every download will fail with \"HTTP Error 403: Forbidden\" until it is updated.\n" +
            "Run the setup script in Termux - it updates yt-dlp and restarts the bridge."
    }

    private const val DEFAULT_MIN = "2026.08.19"

    /** Reads "name": "value" out of the health answer. */
    private fun value(health: String, name: String): String? {
        val match = Regex("\"" + name + "\"\\s*:\\s*\"([^\"]+)\"").find(health)
        return match?.groupValues?.getOrNull(1)
    }
}
