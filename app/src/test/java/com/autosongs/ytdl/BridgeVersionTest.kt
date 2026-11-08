package com.autosongs.ytdl

import com.autosongs.ytdl.bridge.BridgeVersion
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BridgeVersionTest {

    @Test
    fun oldBridgesAreRejected() {
        // These are the versions that handed over their own source code.
        assertTrue(BridgeVersion.isTooOld("1.3.0"))
        assertTrue(BridgeVersion.isTooOld("1.3.1"))
        assertTrue(BridgeVersion.isTooOld("1.3.2"))
        assertTrue(BridgeVersion.isTooOld("1.3.4"))
        assertTrue(BridgeVersion.isTooOld("1.3.8"))
    }

    @Test
    fun currentBridgeIsAccepted() {
        assertFalse(BridgeVersion.isTooOld("1.3.9"))
        assertFalse(BridgeVersion.isTooOld("1.3.16"))
        assertFalse(BridgeVersion.isTooOld("1.4.0"))
        assertFalse(BridgeVersion.isTooOld("2.0.0"))
    }

    @Test
    fun missingVersionIsRejected() {
        assertTrue(BridgeVersion.isTooOld(null))
        assertTrue(BridgeVersion.isTooOld(""))
        assertTrue(BridgeVersion.isTooOld("   "))
    }

    @Test
    fun selfUpdateNeedsARecentBridge() {
        // Before 1.3.11 the bridge had no way of being given new code.
        assertFalse(BridgeVersion.canSelfUpdate("1.3.4"))
        assertFalse(BridgeVersion.canSelfUpdate("1.3.10"))
        assertTrue(BridgeVersion.canSelfUpdate("1.3.11"))
        assertTrue(BridgeVersion.canSelfUpdate("1.3.16"))
        assertFalse(BridgeVersion.canSelfUpdate(null))
    }

    @Test
    fun versionsCompareNumerically() {
        assertTrue(BridgeVersion.compare("1.3.10", "1.3.9") > 0)
        assertTrue(BridgeVersion.compare("1.3.8", "1.3.8") == 0)
        assertTrue(BridgeVersion.compare("1.3.7", "1.3.8") < 0)
        assertTrue(BridgeVersion.compare("1.3", "1.3.0") == 0)
    }
}
