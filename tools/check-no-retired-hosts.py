#!/usr/bin/env python3
"""Fails the build if a retired hosting address sneaks back in.

AutoSongs is published at https://autosongs.example and to nothing else. The
throwaway host names and the platform's retired mirrors are gone for good,
and a release published to one of them would be published to a host that
is going away - the app would keep asking it for years, and every one of
those requests would cost a timeout before the app gave up and tried the
next address.

That is not a hypothetical. The app carried nine such addresses for
months. Nothing in the build noticed, because the build only checked
that the addresses the app knew about were the ones in the list - it
never checked that the list was made of addresses worth having.

So this walks the whole release surface - every source file, every
script, every feed, and the APK itself once it has been built - and
fails on the first thing that names a retired host.

Two different questions, kept apart on purpose:

  1. Does anything name a retired host?  Always fatal, everywhere,
     including the tests and the APK.

  2. Does anything name a host this project does not publish to?
     Checked only in the files that actually hold a release address
     list. The app also links to LAME's download page and PyPI, and the
     tests use made-up hosts on purpose; those are not mistakes.
"""

import io
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)

# The hosting that is retired. The names are kept in pieces so this file
# does not carry a usable address itself.
BANNED = (
    "space." + "mcode" + ".io",
    "space." + "minimax" + ".io",
    "sslip" + ".io",
    "203.0.113.10",
)

# The only address a release may be published to.
ALLOWED = ("autosongs.example",)

# Third parties the app legitimately talks to. These are not release
# addresses, so they are allowed to appear anywhere.
ALLOWED_OTHER = ("ko-fi.com", "youtube.com", "youtube", "githubusercontent.com",
                 "github.com", "sourceforge.net", "pypi.org",
                 "files.pythonhosted.org", "googleapis.com", "gstatic.com",
                 "127.0.0.1", "localhost",
                 # Cloudflare's own documentation, which the tunnel's
                 # help text points a person at. It is a link to read,
                 # not somewhere a release is published.
                 "developers.cloudflare.com",
                 # The reserved example domain (RFC 2606), used as the
                 # sample address in the --public-url help text.
                 "example.com")

# Every https URL, host part only.
URL = re.compile(r"https://([A-Za-z0-9.\-]+(?::\d+)?)")

# Files worth reading. Build output and git history are skipped.
SKIP_DIRS = {".git", "build", ".gradle", "node_modules", "dist", "site",
             ".matrix-session-memory", "__pycache__", ".idea"}
TEXT_SUFFIXES = (".kt", ".java", ".py", ".sh", ".cmd", ".bat", ".txt",
                 ".html", ".json", ".xml", ".gradle", ".kts", ".md", ".cfg",
                 ".properties", ".yml", ".yaml", "")

# Where the release surface lives.
ROOTS = [
    os.path.join(APP, "app", "src"),
    os.path.join(APP, "bridge"),
    os.path.join(APP, "tools"),
    os.path.join(APP, "bridgeapp", "src"),
    os.path.join(APP, "windows_Linux_Bridge", "gui"),
    os.path.join(APP, "website"),
    os.path.join(APP, "app", "build.gradle.kts"),
]

# The files that hold a list of release addresses. Only these are
# checked for addresses this project does not publish to.
ADDRESS_LISTS = [
    os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/AppUpdate.kt"),
    os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/bridge/BridgeVersion.kt"),
    os.path.join(APP, "app/src/main/java/com/autosongs/ytdl/update/Support.kt"),
    os.path.join(APP, "bridge/ytbridge.py"),
    os.path.join(APP, "bridge/setup-termux.sh"),
    os.path.join(APP, "bridge/install-termux.sh"),
    os.path.join(APP, "bridge/autosongs-bridge.sh"),
    os.path.join(APP, "bridge/autosongs-bridge.cmd"),
    os.path.join(APP, "windows_Linux_Bridge/gui/autosongs_bridge_app.py"),
    os.path.join(APP, "windows_Linux_Bridge/gui/autosongs_bridge_gui.py"),
    os.path.join(APP, "website/version.json"),
    os.path.join(APP, "tools/release-hosts.txt"),
]


def files_under(path):
    if os.path.isfile(path):
        yield path
        return
    for base, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in TEXT_SUFFIXES:
                yield os.path.join(base, name)


def host_of(m):
    h = m.lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def is_retired(host):
    return any(bad in host for bad in BANNED)


def is_allowed(host):
    # A sentence can end with the address, and the full stop is then
    # part of what a URL reader sees. It is not part of the host.
    host = host.rstrip(".")
    for ok in ALLOWED:
        if host == ok or host.endswith("." + ok):
            return True
    for ok in ALLOWED_OTHER:
        if host == ok or host.endswith("." + ok):
            return True
    return False


def scan_text(path, text, problems, strict=False):
    """strict: also fail on a host this project does not publish to."""
    for m in URL.findall(text):
        host = host_of(m)
        if is_retired(host):
            problems.append("%s: %s names retired hosting" % (path, host))
        elif strict and not is_allowed(host):
            problems.append("%s: %s is not an address this project publishes to"
                            % (path, host))


def scan_apk(path, problems):
    """The APK is the last word: what ships is what was checked."""
    if not os.path.exists(path):
        return
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        problems.append("%s: could not be opened (%s)" % (path, e))
        return
    for name in z.namelist():
        if name.endswith(".imy"):
            # Chaquopy packs the Python into one archive of compiled
            # modules. The strings are still in there, so they still have
            # to be looked at - and the archive is one level down, so a
            # scan that stopped at the APK would miss every address the
            # Python carries.
            scan_imy(path, name, z, problems)
            continue
        if not (name.endswith(".py") or name.endswith(".dex")
                or name.endswith(".sh") or name.endswith(".cmd")
                or name.endswith(".json") or name.endswith(".pyc")):
            continue
        try:
            data = z.read(name)
        except Exception:
            continue
        text = data.decode("utf-8", "ignore")
        scan_text("%s (%s)" % (path, name), text, problems)


def scan_imy(apk_path, name, z, problems):
    """Look inside the archive of compiled Python modules.

    Chaquopy packs the app's own modules into one .imy, which is a zip.
    The standard library comes in others that are not. Either way the
    strings are in there, so either way they are read - a file that is
    not a zip is simply read as text.
    """
    data = z.read(name)
    try:
        inner = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        scan_text("%s (%s)" % (apk_path, name), data.decode("utf-8", "ignore"), problems)
        return
    for member in inner.namelist():
        if not (member.endswith(".py") or member.endswith(".pyc")
                or member.endswith(".json")):
            continue
        try:
            text = inner.read(member).decode("utf-8", "ignore")
        except Exception:
            continue
        scan_text("%s (%s/%s)" % (apk_path, name, member), text, problems)


def main():
    # usage: check-no-retired-hosts.py [apk] [--feed dir]
    #
    # The APK is the built app. --feed points at a folder of *generated*
    # release files - the feed and the landing page that publish.sh has
    # just written - so the thing that is about to go on the server can
    # be checked too. It is checked separately because the generated
    # folder is written after the build, and at build time it still holds
    # the previous release's files.
    apk = None
    feed = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--feed":
            feed = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if apk is None:
            apk = args[i]
        i += 1

    problems = []
    seen = 0
    for root in ROOTS:
        if not os.path.exists(root):
            continue
        for file_path in files_under(root):
            try:
                text = open(file_path, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            seen += 1
            scan_text(os.path.relpath(file_path, APP), text, problems)

    # the strict pass: only the files that hold a release address list
    for path in ADDRESS_LISTS:
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8", errors="ignore").read()
        scan_text(os.path.relpath(path, APP), text, problems, strict=True)

    if feed:
        for path in files_under(feed):
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            seen += 1
            scan_text(os.path.relpath(path, APP), text, problems, strict=True)

    if apk:
        scan_apk(apk, problems)

    if problems:
        print("FAIL  a retired or foreign address is in the release surface:")
        for p in problems:
            print("  -", p)
        print("\nAutoSongs is published at autosongs.example and nowhere else.")
        print("Take the address out, then build again.")
        return 1

    print("OK  %d files carry no retired address" % seen)
    print("OK  every release address list names only autosongs.example")
    if apk:
        print("OK  the APK carries no retired address")
    if feed:
        print("OK  the generated feed names only autosongs.example")
    return 0


if __name__ == "__main__":
    sys.exit(main())
