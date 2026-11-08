package com.autosongs.ytdl.bridge

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.URL
import java.net.URLEncoder

/**
 * Finds a bridge on the same network, without being told where it is.
 *
 * The bridge shows an eight-character code. The user types it into the
 * app, and the app calls out to the network. Every bridge answers with a
 * fingerprint of the code it is showing - never the code itself - and the
 * phone picks the one that matches. Then it asks that bridge for the key.
 *
 * If nothing answers the call - some routers do not pass broadcasts on -
 * the phone walks the addresses around it and asks each one in turn.
 */
object BridgeDiscovery {

    private const val TAG = "BridgeDiscovery"
    private const val PROBE = "autosongs-pair-v1"
    const val DEFAULT_PORT = 8765

    /** A bridge that was found, before the key was asked for. */
    data class Found(val host: String, val port: Int, val fingerprint: String)

    /**
     * Looks for a bridge that is showing this code.
     *
     * @param port the port the bridge listens on. The default is the one
     *   it uses out of the box.
     */
    suspend fun find(code: String, port: Int = DEFAULT_PORT): Found? {
        val wanted = runCatching { PairCode.fingerprint(code) }.getOrNull() ?: return null
        val byBroadcast = broadcast(wanted, port)
        if (byBroadcast != null) return byBroadcast
        Log.i(TAG, "no bridge answered the call out, looking around instead")
        return scan(wanted, port)
    }

    /**
     * Asks the bridge for the key, showing the code as the proof.
     *
     * The answer is the string the app sends as its token from then on.
     */
    suspend fun claim(host: String, port: Int, code: String): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                val url = URL("http://$host:$port/pair/claim?code=" +
                    URLEncoder.encode(code, "UTF-8"))
                val connection = url.openConnection() as HttpURLConnection
                connection.connectTimeout = 8000
                connection.readTimeout = 8000
                try {
                    val body = connection.inputStream.bufferedReader().use { it.readText() }
                    val token = JSONObject(body).optString("token")
                    if (token.isBlank()) {
                        throw IllegalArgumentException("The bridge did not give a key")
                    }
                    token
                } finally {
                    connection.disconnect()
                }
            }
        }

    // ---- calling out --------------------------------------------------------

    /** Calls out to the network and waits for the bridges to answer. */
    private suspend fun broadcast(wanted: String, port: Int): Found? =
        withContext(Dispatchers.IO) {
            val socket = DatagramSocket()
            try {
                socket.broadcast = true
                socket.soTimeout = 2500
                for (target in broadcastAddresses()) {
                    try {
                        socket.send(
                            DatagramPacket(PROBE.toByteArray(), PROBE.length, target, port)
                        )
                    } catch (t: Throwable) {
                        Log.w(TAG, "the call out did not reach $target", t)
                    }
                }
                val until = System.currentTimeMillis() + 3000
                val buffer = ByteArray(2048)
                while (System.currentTimeMillis() < until) {
                    val packet = DatagramPacket(buffer, buffer.size)
                    val answer = try {
                        socket.receive(packet)
                        parse(packet.data.copyOf(packet.length))
                    } catch (t: Throwable) {
                        null
                    } ?: continue
                    if (answer.fingerprint == wanted) return@withContext answer
                }
                null
            } finally {
                socket.close()
            }
        }

    private fun parse(data: ByteArray): Found? = try {
        val json = JSONObject(String(data, Charsets.UTF_8))
        Found(
            host = json.optString("host"),
            port = json.optInt("port", DEFAULT_PORT),
            fingerprint = json.optString("h")
        )
    } catch (t: Throwable) {
        null
    }

    /** Where a call should go: everyone, and the network the phone is on. */
    private fun broadcastAddresses(): List<InetAddress> {
        val out = mutableListOf<InetAddress>()
        try {
            out.add(InetAddress.getByName("255.255.255.255"))
        } catch (_: Throwable) {
        }
        for (address in localAddresses()) {
            val bytes = address.address
            if (bytes.size != 4) continue
            bytes[3] = (bytes[3].toInt() or 0xFF).toByte()
            try {
                out.add(InetAddress.getByAddress(bytes))
            } catch (_: Throwable) {
            }
        }
        return out
    }

    // ---- looking around -----------------------------------------------------

    /** Walks the addresses next to the phone and asks each one. */
    private suspend fun scan(wanted: String, port: Int): Found? = coroutineScope {
        val targets = neighbours()
        if (targets.isEmpty()) return@coroutineScope null
        // A few at a time, so the phone is not busy opening two hundred
        // sockets at once.
        for (chunk in targets.chunked(32)) {
            val answers = chunk.map { target ->
                async(Dispatchers.IO) { ask(target, port, wanted) }
            }.awaitAll()
            val hit = answers.firstOrNull { it != null }
            if (hit != null) return@coroutineScope hit
        }
        null
    }

    /** The addresses around the phone, assuming an ordinary home network. */
    private fun neighbours(): List<InetAddress> {
        val out = mutableListOf<InetAddress>()
        for (address in localAddresses()) {
            val bytes = address.address
            if (bytes.size != 4) continue
            for (last in 1..254) {
                val copy = bytes.copyOf()
                copy[3] = last.toByte()
                try {
                    out.add(InetAddress.getByAddress(copy))
                } catch (_: Throwable) {
                }
            }
        }
        return out
    }

    /** Asks one address whether it is the bridge we are looking for. */
    private fun ask(host: InetAddress, port: Int, wanted: String): Found? {
        val connection = try {
            URL("http://${host.hostAddress}:$port/pair/info")
                .openConnection() as HttpURLConnection
        } catch (_: Throwable) {
            return null
        }
        return try {
            connection.connectTimeout = 1200
            connection.readTimeout = 1500
            val body: String = connection.inputStream
                .bufferedReader().use(BufferedReader::readText)
            val json = JSONObject(body)
            val answer = Found(
                host = json.optString("host").ifBlank { host.hostAddress },
                port = json.optInt("port", port),
                fingerprint = json.optString("h")
            )
            if (answer.fingerprint == wanted) answer else null
        } catch (_: Throwable) {
            null
        } finally {
            connection.disconnect()
        }
    }

    /** The addresses of this phone. */
    private fun localAddresses(): List<InetAddress> {
        val out = mutableListOf<InetAddress>()
        try {
            for (network in NetworkInterface.getNetworkInterfaces()) {
                for (info in network.inetAddresses) {
                    if (info is Inet4Address && !info.isLoopbackAddress) out.add(info)
                }
            }
        } catch (t: Throwable) {
            Log.w(TAG, "the phone's own addresses could not be found", t)
        }
        return out
    }
}
