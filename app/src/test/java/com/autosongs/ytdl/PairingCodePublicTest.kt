
package com.autosongs.ytdl

import com.autosongs.ytdl.bridge.PairingCode
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The code the bridge shows and the phone reads must mean the same thing.
 *
 * The cases here were produced by the bridge itself - the Python side
 * wrote them and this file checks the phone reads them back the same. A
 * mismatch means the phone cannot pair at all, and the user sees nothing
 * but a code that does not work.
 *
 * The first two are a bridge on the same network. The rest are a bridge
 * reached over the internet, where the phone cannot look the address up
 * and has to be told it.
 */
class PairingCodePublicTest {

    private fun assertParses(
        code: String,
        host: String,
        port: Int,
        scheme: String,
        path: String
    ) {
        val pairing = PairingCode.parse(code)
        assertEquals("the host of " + code, host, pairing.host)
        assertEquals("the port of " + code, port, pairing.port)
        assertEquals("the scheme of " + code, scheme, pairing.scheme)
        assertEquals("the path of " + code, path, pairing.path)
        assertEquals("the key of " + code, "A1B2C3D4E5F6", pairing.token)
    }

    @Test
    fun theCodesTheBridgeShowsAreReadBackTheSame() {
        assertParses("042C1-A0168-H3V8D-JRFAE-BXP4", "192.168.1.50", 8765, "http", "")
        assertParses("0430J-VK1EC-Q6RVV-3C5P2-4FD1P-B1X9S-FPNW", "nas.local", 8765, "http", "")
        assertParses("043G2-CKGCN-Q62V3-MF4PP-CSB4C-NS62X-39DXQ-2TXBJ-CXJPW-X1DEN-Q7EWK-1E0Q7-8WKSC-DP6YX-B4CSP-62WK5-5SHPY-V81QC-0A3CP-3TKJZ-DBG", "penalty-federation-urgent-unwrap.trycloudflare.com", 443, "https", "")
        assertParses("043G2-4K2E9-MP8SV-55SJQ-GRBDE-1P6AB-K3DXP-G3ER0-M6SC7-N75YT-80", "bridge.example.com", 443, "https", "")
        assertParses("043G0-4K2E9-MP8SV-55SJQ-GRBDE-1P6AB-K3DXP-HZ400-M6SC7-N75YT-10", "bridge.example.com", 8080, "http", "")
        assertParses("043G2-2V5F1-GPTW3-CCMQ6-6VVD0-6XGRB-V1ENT-6YBV2-E9MP8-SV5M6-SC7N7-5YSZ0", "example.com", 443, "https", "/auto/bridge")
    }
}
