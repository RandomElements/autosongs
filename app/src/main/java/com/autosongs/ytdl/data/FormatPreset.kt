package com.autosongs.ytdl.data

/**
 * Download format presets. The `id` is sent to the yt-dlp bridge, which maps it
 * onto real yt-dlp format selectors + post-processing options.
 */
enum class FormatPreset(
    val id: String,
    val label: String,
    val description: String,
    val isVideo: Boolean
) {
    AUDIO_M4A(
        "audio_m4a",
        "Audio · M4A 256 kbps",
        "Best quality audio re-encoded to M4A. Plays in any Android music app.",
        false
    ),
    AUDIO_OPUS(
        "audio_opus",
        "Audio · Opus 160 kbps",
        "Smaller files, great quality. AAC fallback if Opus is unavailable.",
        false
    ),
    AUDIO_MP3(
        "audio_mp3",
        "Audio · MP3 192 kbps",
        "Maximum compatibility. Made on the phone, in the app itself.",
        false
    ),
    AUDIO_ORIGINAL(
        "audio_original",
        "Audio · Original quality",
        "Keeps the source codec untouched (no re-encode, fastest).",
        false
    ),
    VIDEO_1080(
        "video_1080",
        "Video · 1080p",
        "Music video at up to 1080p, muxed with the best audio track.",
        true
    ),
    VIDEO_720(
        "video_720",
        "Video · 720p",
        "Music video at up to 720p. Smaller files.",
        true
    ),
    VIDEO_2160(
        "video_2160",
        "Video · 4K",
        "Music video at up to 2160p. Large files.",
        true
    );

    companion object {
        fun fromId(id: String?): FormatPreset = values().firstOrNull { it.id == id } ?: AUDIO_M4A
    }

    /**
     * Video height this preset asks for, 0 for audio presets. The bridge
     * derives the real quality from the preset id, so the label in the app
     * and the file you actually get always agree.
     */
    val quality: Int
        get() = if (isVideo) id.removePrefix("video_").toIntOrNull() ?: 0 else 0
}
