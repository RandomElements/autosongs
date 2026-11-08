package com.autosongs.ytdl

import com.autosongs.ytdl.data.FormatPreset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The preset label used to be a lie: the app sent a separate `videoQuality`
 * setting, so "Video · 720p" downloaded 1080p. The preset id now carries the
 * quality and the bridge derives it from there.
 */
class FormatPresetTest {

    @Test
    fun video_presets_carry_their_own_quality() {
        assertEquals(1080, FormatPreset.VIDEO_1080.quality)
        assertEquals(720, FormatPreset.VIDEO_720.quality)
        assertEquals(2160, FormatPreset.VIDEO_2160.quality)
    }

    @Test
    fun audio_presets_have_no_video_quality() {
        assertEquals(0, FormatPreset.AUDIO_M4A.quality)
        assertEquals(0, FormatPreset.AUDIO_OPUS.quality)
        assertEquals(0, FormatPreset.AUDIO_MP3.quality)
        assertEquals(0, FormatPreset.AUDIO_ORIGINAL.quality)
    }

    @Test
    fun the_id_matches_the_quality_the_bridge_parses() {
        // The bridge reads the height out of the preset id, e.g. "video_720".
        for (preset in FormatPreset.values()) {
            if (!preset.isVideo) continue
            assertTrue(
                "preset id must carry the height: ${preset.id}",
                Regex("""video_\d{3,4}""").matches(preset.id)
            )
            assertEquals(
                "id and quality must agree for ${preset.id}",
                preset.id.removePrefix("video_").toInt(),
                preset.quality
            )
        }
    }

    @Test
    fun fromId_falls_back_to_a_known_preset() {
        assertEquals(FormatPreset.AUDIO_M4A, FormatPreset.fromId(null))
        assertEquals(FormatPreset.AUDIO_M4A, FormatPreset.fromId("nonsense"))
        assertEquals(FormatPreset.VIDEO_720, FormatPreset.fromId("video_720"))
    }
}
