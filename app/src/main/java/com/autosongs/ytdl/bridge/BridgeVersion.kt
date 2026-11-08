package com.autosongs.ytdl.bridge

/**
 * The bridge on the phone has to be new enough.
 *
 * An old bridge (1.3.2 and older) had a fallback that handed over "any
 * recently written file" when a download produced nothing. YouTube started
 * refusing downloads with "HTTP Error 403", so that fallback fired on every
 * track and saved the bridge's own source code as "Artist - Title.py.mp3".
 *
 * Rather than let the app quietly do that again, the app refuses to
 * download and says what to do about it.
 */
object BridgeVersion {

    /**
     * The oldest bridge this app can work with.
     *
     * 1.3.9 is where a 403 started making the bridge try the next player
     * client instead of giving up after one attempt. Older than that and
     * every download fails.
     */
    const val MINIMUM = "1.3.9"

    /**
     * Where the installer lives. This host always serves the newest bridge:
     * the installer and the setup script both point back at it.
     */
    const val INSTALLER_URL = "https://autosongs.example/install-termux.sh"

    /**
     * Every address a release has been published to, newest first.
     *
     * The installer asks all of them which one carries the newest bridge.
     * That list used to live inside the installer itself, which is a
     * chicken-and-egg problem: the newest address is never in the copy of
     * the file that is served from that same address, so the installer
     * kept finding an older release and running its older setup script.
     *
     * So the app hands the list over instead. The app is rebuilt with
     * every release, so it always knows the newest addresses - the
     * installer never has to guess.
     */
    val HOSTS = listOf(
        "https://autosongs.example"
    )

    /**
     * Where published copies of the bridge live. The app looks at all of
     * them and pushes the newest one it finds to the phone, so a fix
     * reaches the phone without another installation.
     */
    val BRIDGE_URLS: List<String> = HOSTS.map { "$it/ytbridge.py" }

    /**
     * The one line to paste into Termux. It installs and starts the bridge.
     *
     * The host list goes with it. The installer would otherwise look for
     * the newest release among the addresses it knows, and the newest
     * address is never among them - it was published after the file was
     * written.
     */
    val INSTALL_COMMAND: String =
        "YTBRIDGE_HOSTS=\"" + HOSTS.joinToString(" ") + "\" " +
            "bash -c \"\$(curl -fsSL $INSTALLER_URL)\""

    /** The same, but ready to be copied into a message. */
    fun installHint(): String =
        "Paste this into Termux and press enter:\n\n$INSTALL_COMMAND"

    /**
     * The oldest bridge that can update itself.
     *
     * Before this the bridge had no way of being given new code, so the app
     * has to ask the user to run the installer in Termux instead.
     */
    const val MINIMUM_SELF_UPDATE = "1.3.11"

    /** True when the bridge can replace itself with a newer one. */
    fun canSelfUpdate(version: String?): Boolean {
        if (version.isNullOrBlank()) return false
        return compare(version, MINIMUM_SELF_UPDATE) >= 0
    }

    /** True when [version] is older than [MINIMUM] (or unreadable). */
    fun isTooOld(version: String?): Boolean {
        if (version.isNullOrBlank()) return true
        return compare(version, MINIMUM) < 0
    }

    /** Compares dotted version numbers, e.g. "1.3.10" > "1.3.9". */
    fun compare(a: String, b: String): Int {
        val left = a.trim().split('.')
        val right = b.trim().split('.')
        val n = maxOf(left.size, right.size)
        for (i in 0 until n) {
            val l = left.getOrNull(i)?.trim()?.toIntOrNull() ?: 0
            val r = right.getOrNull(i)?.trim()?.toIntOrNull() ?: 0
            if (l != r) return l.compareTo(r)
        }
        return 0
    }
}
