package com.autosongs.ytdl

import com.autosongs.ytdl.bridge.BridgeVersion
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The message the user sees when the bridge on the phone is too old.
 *
 * It has to contain the exact line to paste into Termux, because that is the
 * only way to fix an old bridge - it cannot be pushed to it.
 */
class InstallHintTest {

    @Test
    fun theHintHasAOneLineCommand() {
        val hint = BridgeVersion.installHint()
        assertTrue("the hint must mention Termux:\n$hint",
            hint.contains("Termux"))
        assertTrue("the hint must contain a command:\n$hint",
            hint.contains("curl -fsSL"))
        assertTrue("the hint must be a single line to paste:\n$hint",
            hint.contains("bash -c"))
    }

    @Test
    fun theHintPointsAtTheInstaller() {
        assertTrue(BridgeVersion.installHint().contains(BridgeVersion.INSTALLER_URL))
    }

    @Test
    fun theInstallerAddressIsReachable() {
        // A wrong address means the paste fails and the user is stuck.
        assertTrue("the installer address must be https",
            BridgeVersion.INSTALLER_URL.startsWith("https://"))
        assertTrue("the installer address must end in the script",
            BridgeVersion.INSTALLER_URL.endsWith("/install-termux.sh"))
    }

    @Test
    fun theBridgeListStartsWithTheNewestHost() {
        // The app pushes the newest bridge it can find, so the newest host
        // has to be in the list.
        assertTrue(BridgeVersion.BRIDGE_URLS.isNotEmpty())
        assertTrue(BridgeVersion.BRIDGE_URLS.all { it.startsWith("https://") })
        assertTrue(BridgeVersion.BRIDGE_URLS.all { it.endsWith("/ytbridge.py") })
    }
}
