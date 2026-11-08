#!/usr/bin/env python3
"""Checks that every list of addresses names the one release address.

AutoSongs is published at exactly one address: https://autosongs.example

Eleven places have to know about it: the app's update feed, the addresses
the installer asks, the app's project page, the bridge's own update list,
the two Termux scripts, the two bridge launchers, the two desktop GUIs and
the site's release feed.

Forget one and the app quietly stops finding new releases. It keeps
asking an address that died weeks ago, every try costs a timeout, and the
newest build is never seen. That happened once already: the app could not
see anything after 1.4.1, and every release since then had to be handed
over by hand.

So the check is part of the build now. If an address is missing from any
of the lists, the build stops and says which list.

It also refuses to let a retired address back in. The throwaway host names
and the retired platform mirrors are gone for good: a release published to
one of them would be published to a host that is going away, and the app
would keep asking it for years.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)
HOSTS_FILE = os.path.join(HERE, "release-hosts.txt")

# The only address a release may be published to.
SITE_URL = "https://autosongs.example"

FILES = [
    ("the app's update feed",
     os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/AppUpdate.kt")),
    ("the addresses the installer asks",
     os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/bridge/BridgeVersion.kt")),
    ("the app's project page",
     os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/Support.kt")),
    ("the bridge's own update list",
     os.path.join(APP, "bridge/ytbridge.py")),
    ("the setup script", os.path.join(APP, "bridge/setup-termux.sh")),
    ("the installer", os.path.join(APP, "bridge/install-termux.sh")),
    ("the shell bridge launcher", os.path.join(APP, "bridge/autosongs-bridge.sh")),
    ("the Windows bridge launcher", os.path.join(APP, "bridge/autosongs-bridge.cmd")),
    ("the desktop tray app",
     os.path.join(APP, "windows_Linux_Bridge/gui/autosongs_bridge_app.py")),
    ("the desktop GUI",
     os.path.join(APP, "windows_Linux_Bridge/gui/autosongs_bridge_gui.py")),
    ("the site's release feed", os.path.join(APP, "website/version.json")),
]

# The hosting that is retired. Nothing may point at it any more. The names
# are kept in pieces so this file does not carry a usable address itself.
BANNED_HOSTS = (
    "space." + "mcode" + ".io",
    "space." + "minimax" + ".io",
    "sslip" + ".io",
    "203.0.113.10",
)

# A release address is one on the project's own domain. Anything else a
# file happens to link to - the donation page, the video site, a source
# archive - is not a release address and is not this script's business.
RELEASE_SUFFIXES = (".autosongs.example",)

# Every https URL a file contains, host part only.
URL = re.compile(r"https://([A-Za-z0-9.\-]+(?::\d+)?)")


def host_of(url_match):
    host = url_match.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_release_host(host):
    return host == "autosongs.example" or host.endswith(RELEASE_SUFFIXES)


def addresses(path):
    """The release addresses in one file, in the order they appear."""
    s = open(path, encoding="utf-8").read()
    out = []
    for m in URL.findall(s):
        host = host_of(m)
        if not is_release_host(host):
            continue
        address = "https://" + m
        if address not in out:
            out.append(address)
    return out


def banned_in(path):
    """The retired hosting named in one file."""
    s = open(path, encoding="utf-8").read().lower()
    return [bad for bad in BANNED_HOSTS if bad in s]


def wanted_hosts():
    """The one list that is the truth."""
    if not os.path.exists(HOSTS_FILE):
        return None
    out = []
    for line in open(HOSTS_FILE, encoding="utf-8").read().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.rstrip("/"))
    return out


def main():
    wanted = wanted_hosts()
    if wanted is None or not wanted:
        print("FAIL  no address to check - release-hosts.txt does not name one")
        return 1
    if wanted != [SITE_URL]:
        print("FAIL  release-hosts.txt must name exactly %s" % SITE_URL)
        return 1

    problems = []

    # the retired hosting must not be in the truth list either
    for host in wanted:
        for bad in BANNED_HOSTS:
            if bad in host:
                problems.append("release-hosts.txt names a retired address (%s)" % bad)

    lists = {}
    for label, path in FILES:
        if not os.path.exists(path):
            problems.append("%s is missing (%s)" % (label, path))
            continue
        lists[label] = addresses(path)
        for bad in banned_in(path):
            problems.append("%s still names a retired address" % label)

    reference = set(wanted)
    for label, hosts in lists.items():
        got = set(hosts)
        if got != reference:
            problems.append(
                "%s has a different list (missing: %s, extra: %s)"
                % (label,
                   ", ".join(sorted(reference - got)) or "none",
                   ", ".join(sorted(got - reference)) or "none"))

    if problems:
        for p in problems:
            print("FAIL  " + p)
        print("\nRun tools/sync-release-hosts.py, then build again.")
        return 1

    print("OK  every list names %s" % SITE_URL)
    print("OK  %d lists agree, and no retired address is named" % len(lists))
    return 0


if __name__ == "__main__":
    sys.exit(main())
