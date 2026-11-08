# -*- coding: utf-8 -*-
"""Puts the newest release addresses into every place that needs them.

The addresses live in tools/release-hosts.txt. This copies them into
the app's update feed, the bridge's own address list, the bridge's
update list, the two Termux scripts and the release feed - so that a
release is never published to an address nobody knows about.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)
HOSTS_FILE = os.path.join(HERE, "release-hosts.txt")

HOSTS = [h.strip() for h in open(HOSTS_FILE, encoding="utf-8").read().splitlines()]
HOSTS = [h for h in HOSTS if h and not h.startswith("#")]
if not HOSTS:
    print("no hosts in %s" % HOSTS_FILE)
    sys.exit(1)

# the app's update feed: the address of version.json on each host
p = os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/AppUpdate.kt")
s = open(p, encoding="utf-8").read()
new = "\n".join('        "%s/version.json",' % h for h in HOSTS)
s = re.sub(r'(val FEED_URLS: List<String> = listOf\(\n)(.*?)(\n    \))',
           lambda m: m.group(1) + new + m.group(3), s, count=1, flags=re.S)
open(p, "w", encoding="utf-8").write(s)
print("the app's update feed now names %d addresses" % len(HOSTS))

# the bridge's own addresses, and where the installer is fetched from
p = os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/bridge/BridgeVersion.kt")
s = open(p, encoding="utf-8").read()
new = "\n".join('        "%s",' % h for h in HOSTS)
s = re.sub(r'(val HOSTS = listOf\(\n)(.*?)(\n    \))',
           lambda m: m.group(1) + new + m.group(3), s, count=1, flags=re.S)
s = re.sub(r'const val INSTALLER_URL = "[^"]*"',
           'const val INSTALLER_URL = "%s/install-termux.sh"' % HOSTS[0], s, count=1)
open(p, "w", encoding="utf-8").write(s)
print("the bridge now knows %d addresses" % len(HOSTS))

# the bridge's own update list
p = os.path.join(APP, "bridge/ytbridge.py")
s = open(p, encoding="utf-8").read()
new = "\n".join('    "%s/ytbridge.py",' % h for h in HOSTS)
s = re.sub(r'(_UPDATE_URLS_DEFAULT = \[\n)(.*?)(\n\])',
           lambda m: m.group(1) + new + m.group(3), s, count=1, flags=re.S)
open(p, "w", encoding="utf-8").write(s)
print("the bridge's update list now names %d addresses" % len(HOSTS))

# the two Termux scripts
for name in ("setup-termux.sh", "install-termux.sh"):
    p = os.path.join(APP, "bridge", name)
    s = open(p, encoding="utf-8").read()
    s = re.sub(r'(BRIDGE_HOSTS="\$\{YTBRIDGE_HOSTS:-)([^"]*)(")',
               lambda m: m.group(1) + " ".join(HOSTS) + "}" + m.group(3),
               s, count=1)
    open(p, "w", encoding="utf-8").write(s)
    print("%s now names %d addresses" % (name, len(HOSTS)))

# the release feed names every address too, so the app can follow them
p = os.path.join(ROOT, "publish.sh")
s = open(p, encoding="utf-8").read()
s = re.sub(r'(HOSTS=")([^"]*)(")',
           lambda m: m.group(1) + "\n".join(HOSTS) + m.group(3), s, count=1)
open(p, "w", encoding="utf-8").write(s)
print("the release feed names %d addresses" % len(HOSTS))
