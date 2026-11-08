package com.autosongs.ytdl

import android.content.Context
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import com.autosongs.ytdl.data.AppSettings
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Where the bridge lives.
 *
 * The default is the copy inside the app: that is the whole point of the
 * embedded bridge - one app, nothing else to install.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.UPSIDE_DOWN_CAKE])
class BridgeModeTest {

    private fun settings(): AppSettings =
        AppSettings.get(ApplicationProvider.getApplicationContext<Context>())

    @Test
    fun theBridgeIsInsideTheAppByDefault() {
        val s = settings()
        s.bridgeMode = AppSettings.BRIDGE_EMBEDDED
        assertEquals(AppSettings.BRIDGE_EMBEDDED, s.bridgeMode)
        assertTrue(s.isEmbedded)
    }

    @Test
    fun theAppTalksToItsOwnBridge() {
        val s = settings()
        s.bridgeMode = AppSettings.BRIDGE_EMBEDDED
        assertEquals("127.0.0.1", s.bridgeAddress.first)
        assertEquals(8765, s.bridgeAddress.second)
    }

    @Test
    fun anotherMachineIsUsedWhenItIsChosen() {
        val s = settings()
        s.bridgeMode = AppSettings.BRIDGE_REMOTE
        s.bridgeHost = "192.168.1.10"
        s.bridgePort = 9000
        assertEquals("192.168.1.10", s.bridgeAddress.first)
        assertEquals(9000, s.bridgeAddress.second)
    }

    @Test
    fun theSavedAddressSurvivesTheSwitch() {
        // Switching the bridge over and back must not lose the address.
        val s = settings()
        s.bridgeMode = AppSettings.BRIDGE_REMOTE
        s.bridgeHost = "192.168.1.10"
        s.bridgePort = 9000
        s.bridgeMode = AppSettings.BRIDGE_EMBEDDED
        assertEquals("127.0.0.1", s.bridgeAddress.first)
        assertEquals(8765, s.bridgeAddress.second)
        s.bridgeMode = AppSettings.BRIDGE_REMOTE
        assertEquals("192.168.1.10", s.bridgeAddress.first)
        assertEquals(9000, s.bridgeAddress.second)
    }

    @Test
    fun theEmbeddedBridgeNeedsNoToken() {
        val s = settings()
        s.bridgeMode = AppSettings.BRIDGE_EMBEDDED
        s.bridgeToken = "secret"
        assertEquals("", s.bridgeAuthToken)
        s.bridgeMode = AppSettings.BRIDGE_REMOTE
        assertEquals("secret", s.bridgeAuthToken)
    }
}
