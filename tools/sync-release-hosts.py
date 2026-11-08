#!/usr/bin/env python3
"""Puts the release address from one file into every place that needs it.

`release-hosts.txt` is the one list: the address every release is
published to. The app's update feed, the addresses the installer asks for,
the app's project page, the bridge's own update list, the two Termux
scripts, the two bridge launchers, the two desktop GUIs and the site's
release feed all have to name it - miss one and the app quietly stops
finding new releases.

This rewrites all of them from that one file. `check-release-hosts.py`
then makes sure none was missed, and `check-host-lists.py` makes sure the
lists agree with each other.

Every place a release address can hide is handled here. The four that
were missed before are handled too:

  - Support.kt's PROJECT_URL, the page the app's About screen opens
  - autosongs-bridge.sh's HOSTS, the shell bridge's own fetch list
  - autosongs-bridge.cmd's for %%H in (...) list, the Windows one
  - the two desktop GUIs' HOSTS lists

A substitution that matches nothing is an error, not a quiet success.
That is not fussiness: a pattern that stopped matching left the old
address in the file while the script still said "ok", and that is how
the retired addresses stayed in here for so long.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)

HOSTS_FILE = os.path.join(HERE, "release-hosts.txt")
SITE_URL = "https://autosongs.example"

# The hosting is retired for good. The names are kept in pieces so this
# file does not carry a usable address itself.
BANNED = (
    "space." + "mcode" + ".io",
    "space." + "minimax" + ".io",
    "sslip" + ".io",
    "203.0.113.10",
)


def host_list():
    out = []
    for line in open(HOSTS_FILE, encoding="utf-8").read().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.rstrip("/"))
    return out


def write(path, text):
    open(path, "w", encoding="utf-8", newline="").write(text)
    print("ok:", os.path.relpath(path, ROOT))


def sub(text, pattern, repl, what, count=1):
    """Regex replace that refuses to pass silently when it matches nothing."""
    new, n = re.subn(pattern, repl, text, count=count, flags=re.S)
    if n != count:
        raise SystemExit("could not find %s - nothing was changed" % what)
    return new


def kotlin_list(hosts, suffix=""):
    return "\n".join('        "%s%s",' % (h, suffix) for h in hosts).rstrip(",")


def main():
    hosts = host_list()
    if not hosts:
        print("the host list is empty")
        return 1
    if hosts != [SITE_URL]:
        print("the release address list must name exactly %s" % SITE_URL)
        return 1

    for host in hosts:
        for bad in BANNED:
            if bad in host:
                print("%s is a retired address" % host)
                print("take it out of %s" % HOSTS_FILE)
                return 1

    # the app's update feed
    p = os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/AppUpdate.kt")
    s = open(p, encoding="utf-8").read()
    s = sub(s, r"(    val FEED_URLS: List<String> = listOf\(\n).*?(\n    \))",
            lambda m: m.group(1) + kotlin_list(hosts, "/version.json") + m.group(2),
            "the app's update feed")
    write(p, s)

    # the addresses the installer and the bridge ask for
    p = os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/bridge/BridgeVersion.kt")
    s = open(p, encoding="utf-8").read()
    s = sub(s, r"(    val HOSTS = listOf\(\n).*?(\n    \))",
            lambda m: m.group(1) + kotlin_list(hosts) + m.group(2),
            "the bridge's addresses")
    s = sub(s, r'const val INSTALLER_URL = "https://[^"]+/install-termux.sh"',
            lambda m: 'const val INSTALLER_URL = "%s/install-termux.sh"' % hosts[0],
            "the installer's address")
    write(p, s)

    # the page the app's About screen opens
    p = os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/Support.kt")
    s = open(p, encoding="utf-8").read()
    s = sub(s, r'(const val PROJECT_URL = ")https://[^"]+(")',
            lambda m: m.group(1) + SITE_URL + m.group(2),
            "the app's project page")
    write(p, s)

    # the bridge's own update list
    p = os.path.join(APP, "bridge/ytbridge.py")
    s = open(p, encoding="utf-8").read()
    s = sub(s, r"(_UPDATE_URLS_DEFAULT = \[\n).*?(\n\])",
            lambda m: m.group(1) + '    "%s/ytbridge.py",' % SITE_URL + m.group(2),
            "the bridge's update list")
    write(p, s)

    # the two Termux scripts
    for name in ("setup-termux.sh", "install-termux.sh"):
        p = os.path.join(APP, "bridge/" + name)
        s = open(p, encoding="utf-8").read()
        s = sub(s, r'BRIDGE_HOSTS="\$\{YTBRIDGE_HOSTS:-[^}]*\}"',
                lambda m: 'BRIDGE_HOSTS="${YTBRIDGE_HOSTS:-%s}"' % " ".join(hosts),
                "%s's address list" % name)
        write(p, s)

    # the shell bridge's own fetch list
    p = os.path.join(APP, "bridge/autosongs-bridge.sh")
    s = open(p, encoding="utf-8").read()
    s = sub(s, r'(HOSTS=").*?(")',
            lambda m: m.group(1) + "\n".join(hosts) + m.group(2),
            "the shell bridge's fetch list")
    write(p, s)

    # the Windows bridge's own fetch list
    p = os.path.join(APP, "bridge/autosongs-bridge.cmd")
    s = open(p, encoding="utf-8", newline="").read()
    s = sub(s, r"(for %%H in \(\n).*?(\n\) do \()",
            lambda m: m.group(1) + "\n".join("    " + h for h in hosts) + m.group(2),
            "the Windows bridge's fetch list")
    write(p, s)

    # the two desktop GUIs
    for name in ("autosongs_bridge_app.py", "autosongs_bridge_gui.py"):
        p = os.path.join(APP, "windows_Linux_Bridge/gui/" + name)
        s = open(p, encoding="utf-8").read()
        s = sub(s, r"(HOSTS = \[\n).*?(\n\])",
                lambda m: m.group(1) + "\n".join('    "%s",' % h for h in hosts) + m.group(2),
                "%s's fetch list" % name)
        write(p, s)

    print("%d address in every place" % len(hosts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
