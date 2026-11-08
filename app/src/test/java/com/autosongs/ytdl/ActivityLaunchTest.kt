package com.autosongs.ytdl

import android.os.Build
import android.widget.Button
import android.widget.EditText
import android.widget.RadioButton
import android.widget.SeekBar
import android.widget.Spinner
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import com.autosongs.ytdl.data.AppSettings
import com.google.android.material.materialswitch.MaterialSwitch
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * These tests launch the activities for real (Robolectric), so a layout/code
 * mismatch - such as casting a MaterialSwitch to CheckBox - fails the build
 * instead of crashing on the user's phone.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.UPSIDE_DOWN_CAKE])
class ActivityLaunchTest {

    @Test
    fun mainActivity_launches() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertNotNull(activity.findViewById<Button>(R.id.startButton))
                assertNotNull(activity.findViewById<Button>(R.id.stopButton))
                assertNotNull(activity.findViewById<Button>(R.id.settingsButton))
                assertNotNull(activity.findViewById<Button>(R.id.pairRemoteButton))
                assertNotNull(activity.findViewById<Button>(R.id.supportButton))
                assertNotNull(activity.findViewById<Button>(R.id.grantAccessButton))
                assertNotNull(activity.findViewById<Spinner>(R.id.presetSpinner))
                assertNotNull(activity.findViewById<TextView>(R.id.presetDescription))
                assertNotNull(
                    activity.findViewById<MaterialSwitch>(R.id.autoDownloadSwitch)
                )
                assertNotNull(
                    activity.findViewById<MaterialSwitch>(R.id.embedMetadataSwitch)
                )
                assertNotNull(
                    activity.findViewById<MaterialSwitch>(R.id.embedThumbnailSwitch)
                )
            }
        }
    }

    @Test
    fun settingsActivity_launches_and_casts_match_layout() {
        ActivityScenario.launch(SettingsActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val deleteAfter = activity.findViewById<MaterialSwitch>(
                    R.id.deleteAfterSwitch
                )
                assertNotNull("deleteAfterSwitch must be a MaterialSwitch", deleteAfter)

                assertNotNull(activity.findViewById<EditText>(R.id.hostInput))
                assertNotNull(activity.findViewById<EditText>(R.id.portInput))
                assertNotNull(activity.findViewById<EditText>(R.id.tokenInput))
                assertNotNull(activity.findViewById<EditText>(R.id.folderInput))
                assertNotNull(activity.findViewById<EditText>(R.id.blocklistInput))
                assertNotNull(activity.findViewById<EditText>(R.id.packagesInput))
                assertNotNull(activity.findViewById<SeekBar>(R.id.minDurationSeek))
                assertNotNull(activity.findViewById<SeekBar>(R.id.minPlaybackSeek))
                assertNotNull(activity.findViewById<SeekBar>(R.id.dedupeSeek))
                assertNotNull(activity.findViewById<TextView>(R.id.minDurationLabel))
                assertNotNull(activity.findViewById<TextView>(R.id.minPlaybackLabel))
                assertNotNull(activity.findViewById<TextView>(R.id.dedupeLabel))
                assertNotNull(activity.findViewById<Button>(R.id.saveButton))

                // The bridge tools live here now.
                assertNotNull(activity.findViewById<TextView>(R.id.bridgeStatus))
                assertNotNull(activity.findViewById<Button>(R.id.testBridgeButton))
                assertNotNull(activity.findViewById<Button>(R.id.updateBridgeButton))
                assertNotNull(activity.findViewById<Button>(R.id.termuxButton))
                assertNotNull(activity.findViewById<Button>(R.id.pairRemoteSettingsButton))

                // Where the songs are kept: one of two, never both.
                assertNotNull(activity.findViewById<RadioButton>(R.id.saveToPhoneRadio))
                assertNotNull(activity.findViewById<RadioButton>(R.id.saveToBridgeRadio))
            }
        }
    }

    @Test
    fun settings_persist_values() {
        val settings = AppSettings.get(ApplicationProvider.getApplicationContext())
        settings.bridgeHost = "10.0.0.5"
        settings.bridgePort = 9000
        settings.minDurationSec = 123
        settings.dedupeHours = 7

        val reloaded = AppSettings.get(ApplicationProvider.getApplicationContext())
        assertTrue(reloaded.bridgeHost == "10.0.0.5")
        assertTrue(reloaded.bridgePort == 9000)
        assertTrue(reloaded.minDurationSec == 123)
        assertTrue(reloaded.dedupeHours == 7)
    }
}
