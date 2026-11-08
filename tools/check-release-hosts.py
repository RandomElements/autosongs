#!/usr/bin/env python3
"""Keeps the release addresses in one place, and checks they are everywhere.

AutoSongs is published at exactly one address: https://autosongs.example

Every place that has to name it needs the same list:

  - the app's update feed      (AppUpdate.kt)
  - the bridge's own addresses (BridgeVersion.kt)
  - the app's project page     (Support.kt)
  - the bridge's update list   (ytbridge.py)
  - the two Termux scripts     (setup-termux.sh, install-termux.sh)
  - the two bridge launchers   (autosongs-bridge.sh, autosongs-bridge.cmd)
  - the desktop GUIs           (autosongs_bridge_app.py, autosongs_bridge_gui.py)
  - the site's release feed    (website/version.json)

Missing one is how the app ended up unable to find anything newer than
1.4.1: the list still named three addresses that had died, and the check
took a minute before it gave up.

So the addresses live in one file, and this script makes sure every place
that needs them has them.

It also refuses to let a retired address back in. The throwaway host names
and the retired platform mirrors are gone for good: a release published to
one of them would be published to a host that is going away, and the app
would keep asking it for years. Any appearance of one of those names - in
the list of addresses or in any file that holds a list - fails the check.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)

HOSTS_FILE = os.path.join(HERE, "release-hosts.txt")

# The only address a release may be published to.
SITE_URL = "https://autosongs.example"

# The hosting that is retired. Nothing may point at it any more. The names
# are kept in pieces so this file does not carry a usable address itself.
BANNED_HOSTS = (
    "space." + "mcode" + ".io",
    "space." + "minimax" + ".io",
    "sslip" + ".io",
    "203.0.113.10",
)

PLACES = [
    ("the app's update feed",
     os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/AppUpdate.kt")),
    ("the bridge's addresses",
     os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/bridge/BridgeVersion.kt")),
    ("the app's project page",
     os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/Support.kt")),
    ("the bridge's update list",
     os.path.join(APP, "bridge/ytbridge.py")),
    ("the setup script",
     os.path.join(APP, "bridge/setup-termux.sh")),
    ("the installer",
     os.path.join(APP, "bridge/install-termux.sh")),
    ("the shell bridge launcher",
     os.path.join(APP, "bridge/autosongs-bridge.sh")),
    ("the Windows bridge launcher",
     os.path.join(APP, "bridge/autosongs-bridge.cmd")),
    ("the desktop tray app",
     os.path.join(APP, "windows_Linux_Bridge/gui/autosongs_bridge_app.py")),
    ("the desktop GUI",
     os.path.join(APP, "windows_Linux_Bridge/gui/autosongs_bridge_gui.py")),
    ("the site's release feed",
     os.path.join(APP, "website/version.json")),
]


def main():
    if not os.path.exists(HOSTS_FILE):
        print("no host list at %s" % HOSTS_FILE)
        return 1
    hosts = [h.strip() for h in open(HOSTS_FILE, encoding="utf-8").read().splitlines()]
    hosts = [h for h in hosts if h and not h.startswith("#")]
    if not hosts:
        print("the host list is empty")
        return 1
    if hosts != [SITE_URL]:
        print("the release address list must name exactly %s" % SITE_URL)
        for host in hosts:
            print("  -", host)
        return 1

    problems = []

    # 1. the retired hosting must not be in the list of addresses
    for host in hosts:
        for bad in BANNED_HOSTS:
            if bad in host:
                problems.append("%s is a retired address" % host)

    # 2. and it must not be hiding in any file that holds a list
    for label, path in PLACES:
        if not os.path.exists(path):
            problems.append("%s: %s is missing" % (label, path))
            continue
        text = open(path, encoding="utf-8").read()
        if SITE_URL not in text:
            problems.append("%s does not mention %s" % (label, SITE_URL))
        for bad in BANNED_HOSTS:
            if bad in text:
                problems.append("%s still names a retired address" % label)

    if problems:
        print("the release addresses are not right:")
        for problem in problems:
            print("  -", problem)
        print("\nRun tools/sync-release-hosts.py after editing %s,\n"
              "and take the retired hosting out of every list." % HOSTS_FILE)
        return 1

    print("all %d places name the one release address" % len(PLACES))
    print("  ", SITE_URL)
    print("no retired address is named anywhere")
    return 0


if __name__ == "__main__":
    sys.exit(main())
