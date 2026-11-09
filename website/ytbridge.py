#!/usr/bin/env python3
"""
yt-dlp bridge for AutoSongs.

A small HTTP service that wraps the real `yt-dlp` binary so the Android app can
trigger downloads. Designed to run inside Termux on the same phone:

    pkg install python ffmpeg
    pip install yt-dlp
    python3 ytbridge.py --port 8765

or on any LAN machine / VPS.

How a download works
--------------------
1. The app sends the detected track (title, artist, duration).
2. The bridge runs `yt-dlp --flat-playlist --dump-json "ytsearchN:<query>"` to
   get candidate videos.  (The `ytsearch:` prefix matters - yt-dlp treats a
   bare positional argument as a URL, not as a search.)
3. Candidates are scored against the requested title/artist/duration and the
   best one is chosen.
4. That single video id is downloaded with the requested format preset.

Endpoints
---------
GET  /health                -> {"ok":true,"yt_dlp":"<version>"}
POST /search                -> {"id":"<job id>"}            (starts a download)
GET  /job/<id>              -> {"status","percent","title","artist","has_file","error"}
GET  /file/<id>             -> raw media bytes
GET  /cookies               -> {"cookies":<bool>,"source":"<where it came from>"}
POST /cookies               -> {"cookies":"<the file text>"} hands the bridge a
                               cookie jar, {"clear":true} takes it away again
"""

import argparse
import difflib
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import shutil
import uuid
import secrets
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BRIDGE_VERSION = "1.4.4"

# Where the newest bridge is published. The bridge checks these on its own
# and replaces itself, so a fix does not need the phone to install anything.
# The AutoSongs site is the one home of the current core; more sources can be
# listed through YTBRIDGE_UPDATE_URLS (comma separated) if copies appear
# again. The bridge takes the newest version any source has, and never
# replaces itself with anything older than what is running here.
_UPDATE_URLS_DEFAULT = [
    "https://autosongs.org/ytbridge.py"
]
UPDATE_URLS = [u.strip() for u in
               os.environ.get("YTBRIDGE_UPDATE_URLS", "").split(",") if u.strip()] \
    or list(_UPDATE_URLS_DEFAULT)

TOKEN = ""
WORKDIR = ""
LIBRARY_DIR = ""
PO_TOKEN = ""
CLIENTS_OVERRIDE = ""
JOBS = {}
JOBS_LOCK = threading.Lock()

# The address the bridge is reachable at from outside the network.
#
# A bridge on a home network is found by the phone asking the network
# who is there. A bridge that is reachable over the internet cannot be
# found that way - there is no network to ask - so the address has to be
# written down instead, and this is it.
PUBLIC_URL = ""

# When the bridge is reachable from outside, every request has to carry
# the key, including the two that answer a phone that is trying to pair.
#
# Those two are open on a home network on purpose: the phone has the
# eight-character code but not the key yet, and the code is what proves
# it. Over the internet that is not good enough - the code is short
# enough to be guessed by someone who is trying - so the key is required
# there too, and the phone is given the key in the pairing code.
REQUIRE_TOKEN = False

# The tunnel process, when there is one. It is stopped with the bridge.
TUNNEL_PROC = None

# how many search candidates to pull
SEARCH_DEPTH = 8

# The bridge normally starts the yt-dlp program as a child process. Inside
# the app there is no such program - yt-dlp is a Python library there - so
# the bridge calls yt-dlp as a library instead. make_server(embedded=True)
# turns this on.
EMBEDDED = False

# The short code the bridge shows, and the words a phone calls out with
# when it is looking for a bridge it does not know the address of.
PAIR_CODE = ""
PAIR_PROBE = b"autosongs-pair-v1"

# The folder that holds the yt_dlp package. The app can download a newer
# yt-dlp than the one that came with the APK and point the bridge at it, so
# a yt-dlp that YouTube has broken can always be replaced.
YTDL_PATH = ""


# --------------------------------------------------------------------------- #
# cookies
# --------------------------------------------------------------------------- #
# YouTube answers some requests with "Sign in to confirm you're not a bot"
# instead of the video. The cure is a cookie jar - the file a signed-in
# browser can export, which makes yt-dlp look like that browser.
#
# The bridge looks for a jar itself rather than demanding one, because the
# person who hits the bot check is the person who has to fix it, and they
# should not have to learn a command line to do it.
#
# Where the jar can be, in the order it is looked for. The first one that
# exists wins.
def cookie_search_paths():
    """The places a cookie jar is looked for, in the order they are tried."""
    here = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~")
    paths = [
        ("next to the bridge", os.path.join(here, "cookies.txt")),
    ]
    if WORKDIR:
        paths.append(("in the work folder", os.path.join(WORKDIR, "cookies.txt")))
    paths += [
        ("in ~/.autosongs", os.path.join(home, ".autosongs", "cookies.txt")),
        ("in ~/autosongs", os.path.join(home, "autosongs", "cookies.txt")),
        ("in ~/.config/yt-dlp", os.path.join(home, ".config", "yt-dlp", "cookies.txt")),
    ]
    return paths


def find_cookie_source(explicit=""):
    """Works out where the cookie jar is, and says so.

    An explicit path (the --cookies argument, the environment variable, or
    a jar the app pushed over HTTP) always wins: the person who named it
    meant it.

    Returns a (path, source) pair. The path is empty when there is no jar
    at all, and the source then says why there is none.
    """
    if explicit:
        path = os.path.expanduser(explicit)
        if os.path.isfile(path):
            return path, "the file you chose"
        return "", "the file you chose is not there"

    for where, path in cookie_search_paths():
        try:
            if os.path.isfile(path):
                return path, where
        except OSError:
            continue
    return "", "none"


class CookieSource:
    """The cookie jar, in both of the shapes yt-dlp wants it.

    The command line takes a path; the library takes an option. One object
    that knows both shapes is what stops an option being added to one path
    and forgotten in the other - and the app uses the library path while
    every other bridge uses the command line.
    """

    def __init__(self, path="", source=""):
        self.path = path or ""
        self.source = source or ""

    @property
    def active(self):
        """True when there is a jar to hand to yt-dlp."""
        return bool(self.path)

    def cli_args(self):
        """The option for the command line path."""
        return ["--cookies", self.path] if self.path else []

    def api_opts(self):
        """The option for the library path."""
        return {"cookiefile": self.path} if self.path else {}

    def __repr__(self):
        return "CookieSource(%r, %r)" % (self.path, self.source)


# The jar in use. It is a module global because the app can replace it
# while the bridge is running - it pushes a jar over HTTP when the user
# confirms - and every download after that has to use the new one.
COOKIES = CookieSource()


# The words YouTube uses when it wants a sign-in instead of the video.
# The check has been spelled several ways over the years, and a new one
# appears every so often, so several are recognised.
BOT_CHECK_PHRASES = (
    "sign in to confirm",
    "not a bot",
    "confirm you are not a bot",
    "confirm you're not a bot",
    "login required",
    "please log in",
    "please sign in",
    "please sign-in",
)


def is_bot_check(text):
    """True when a message from YouTube is the sign-in demand.

    One place decides this, so the search and the download cannot disagree
    about what a bot check looks like.
    """
    low = (text or "").lower()
    return any(phrase in low for phrase in BOT_CHECK_PHRASES)


def set_cookie_jar(text):
    """Saves a cookie jar the app sent, and puts it to use.

    The jar is written into the work folder, so it is found again by the
    usual search - which means it survives a restart of the bridge without
    the app having to send it a second time.
    """
    global COOKIES
    if not text:
        # Taking the jar away again. The jar the app sent sits in the work
        # folder, and the ordinary search would find it there again - so
        # the file has to go as well, or "clear" would not clear anything.
        folder = WORKDIR or os.path.dirname(os.path.abspath(__file__))
        sent = os.path.join(folder, "cookies.txt")
        if COOKIES.path and os.path.abspath(COOKIES.path) == os.path.abspath(sent):
            try:
                os.remove(sent)
            except OSError:
                pass
        path, source = find_cookie_source("")
        COOKIES = CookieSource(path, source)
        return COOKIES

    folder = WORKDIR or os.path.dirname(os.path.abspath(__file__))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "cookies.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    # The jar belongs to the person who sent it, so nobody else can read it.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    COOKIES = CookieSource(path, "the file the app sent")
    print("[bridge] cookies: a jar was sent over HTTP and is now in use",
          flush=True)
    return COOKIES


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def version_tuple(v):
    """Turn "1.3.11" into (1, 3, 11) so versions can be compared."""
    out = []
    for part in str(v).split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


UPDATE_STATE = {"state": "unknown", "remote": BRIDGE_VERSION}


def fetch_remote_bridge():
    """Download the newest published bridge. Returns (version, source).

    Every source is asked, and the newest version wins - an older copy of
    the bridge sitting on an older host must not hide a newer one.
    """
    import urllib.request
    best = (None, None)
    errors = []
    for url in UPDATE_URLS:
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                text = resp.read().decode("utf-8", "replace")
            m = re.search(r'^BRIDGE_VERSION = "([^"]+)"', text, re.M)
            if not m:
                errors.append("%s: no version" % url)
                continue
            if best[0] is None or version_tuple(m.group(1)) > version_tuple(best[0]):
                best = (m.group(1), text)
        except Exception as exc:
            errors.append("%s: %s" % (url, exc))
    if best[0] is None:
        raise RuntimeError("; ".join(errors) or "no source answered")
    return best


def self_update(force=False, code=None):
    """Replace the running bridge with the newest one and restart.

    The old file is kept as a backup, the new one has to compile before it
    is put in place, and the restart keeps the same arguments.

    [code] is the new source. Without it the newest published bridge is
    fetched - the app can also push a copy it found itself.
    """
    global UPDATE_STATE
    if code:
        m = re.search(r'^BRIDGE_VERSION = "([^"]+)"', code, re.M)
        if not m:
            UPDATE_STATE = {"state": "error",
                            "error": "the pushed code has no version"}
            return UPDATE_STATE
        remote, text = m.group(1), code
    else:
        try:
            remote, text = fetch_remote_bridge()
        except Exception as exc:
            UPDATE_STATE = {"state": "error", "error": str(exc)}
            return UPDATE_STATE

    if not force and version_tuple(remote) <= version_tuple(BRIDGE_VERSION):
        UPDATE_STATE = {"state": "current", "remote": remote}
        return UPDATE_STATE

    try:
        compile(text, "ytbridge.py", "exec")
    except SyntaxError as exc:
        UPDATE_STATE = {"state": "error", "remote": remote,
                        "error": "the downloaded bridge does not compile: %s" % exc}
        return UPDATE_STATE

    target = os.path.abspath(sys.argv[0])
    try:
        if os.path.exists(target):
            shutil.copy2(target, target + ".bak")
        with open(target + ".new", "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(target + ".new", target)
    except Exception as exc:
        UPDATE_STATE = {"state": "error", "remote": remote,
                        "error": "could not write the new bridge: %s" % exc}
        return UPDATE_STATE

    UPDATE_STATE = {"state": "updating", "remote": remote,
                    "from": BRIDGE_VERSION}
    print("[bridge] updating %s -> %s, restarting" % (BRIDGE_VERSION, remote),
          flush=True)
    time.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def update_watcher():
    """Check for a newer bridge every 30 minutes."""
    while True:
        try:
            self_update()
        except Exception:
            pass
        time.sleep(1800)


def yt_dlp_bin():
    """Locate the yt-dlp executable (Termux may install it under ~/.local/bin)."""
    found = shutil.which("yt-dlp")
    if found:
        return [found]
    local = os.path.expanduser("~/.local/bin/yt-dlp")
    if os.path.exists(local):
        return [local]
    return ["yt-dlp"]


# --------------------------------------------------------------------------- #
# yt-dlp as a library - this is how the app inside the phone uses it
# --------------------------------------------------------------------------- #
def yt_dlp_module():
    """Imports yt-dlp as a library. Returns None when it is not there."""
    global YTDL_PATH
    if YTDL_PATH:
        # A newer yt-dlp that the app downloaded. Its folder goes in front of
        # everything else, so it wins over the one that came with the APK.
        parent = os.path.dirname(YTDL_PATH)
        if parent and parent not in sys.path:
            sys.path.insert(0, parent)
    try:
        import yt_dlp
    except ImportError:
        return None
    return yt_dlp


def _api_extractor_args(clients):
    """Turns "youtube:player_client=android" into yt-dlp's extractor_args."""
    if not clients:
        return {}
    name, _, rest = clients.partition("=")
    option, _, value = rest.partition("=")
    key = name.split(":")[-1]
    if not option or not value:
        return {}
    return {key: {option: [value]}}


# YouTube regularly breaks yt-dlp. When that happens, every download fails
# with "HTTP Error 403: Forbidden" until yt-dlp is updated. Release
# 2026.08.19 was exactly such a fix, and the phone in question was still
# running 2026.06.09 - four months old, and the reason its downloads all
# failed. Anything older than this cannot be trusted with YouTube.
MIN_YTDLP = "2026.08.19"


# Running "yt-dlp --version" takes a moment on a phone, and /health is
# polled often, so the answer is cached for a short while.
_YTDLP_CACHE = {"version": "", "at": 0.0}


def yt_dlp_version(max_age=60.0):
    """The version of yt-dlp that is actually installed, or ""."""
    if EMBEDDED:
        # Inside the app yt-dlp is a library, so the version comes from the
        # library itself.
        #
        # The attribute is __version__. "yt_dlp.version" is the *module*
        # yt-dlp keeps the number in, and handing a module to /health made
        # the bridge die before it could answer: writing the answer down
        # failed, the connection closed with nothing on it, and the app saw
        # a bridge that had gone quiet.
        mod = yt_dlp_module()
        ver = getattr(mod, "__version__", "") if mod else ""
        if not ver and mod is not None:
            # Some builds keep the number in the submodule instead.
            ver = getattr(getattr(mod, "version", None), "__version__", "") or ""
        if not ver and mod is not None:
            # And some keep it in a file.
            ver = version_from_package(mod)
        return str(ver or "")
    now = time.time()
    if _YTDLP_CACHE["version"] and now - _YTDLP_CACHE["at"] < max_age:
        return _YTDLP_CACHE["version"]
    try:
        out = subprocess.run(yt_dlp_bin() + ["--version"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, timeout=30)
        ver = (out.stdout or "").strip()
    except Exception:  # noqa: BLE001
        ver = ""
    if ver:
        _YTDLP_CACHE["version"] = ver
        _YTDLP_CACHE["at"] = now
    return ver


def yt_dlp_is_outdated():
    """True when the installed yt-dlp is older than MIN_YTDLP."""
    ver = yt_dlp_version()
    if not ver:
        return False
    # yt-dlp versions are dates: "2026.06.09". Compare them as numbers so
    # "2026.10.26" beats "2026.08.19" instead of comparing alphabetically.
    nums = re.findall(r"\d+", ver)
    if len(nums) < 3:
        return False
    try:
        current = tuple(int(n) for n in nums[:3])
    except ValueError:
        return False
    need = tuple(int(n) for n in re.findall(r"\d+", MIN_YTDLP)[:3])
    return current < need


def upgrade_yt_dlp():
    """Try to update yt-dlp in place. Returns the version afterwards."""
    if EMBEDDED:
        # Inside the app there is no pip and no writable site-packages. The
        # app updates yt-dlp itself - it downloads a newer one and puts it
        # in front of the one that came with the APK.
        print("[bridge] yt-dlp is updated by the app, not by the bridge",
              flush=True)
        return yt_dlp_version()
    print("[bridge] yt-dlp is older than %s - updating it now" % MIN_YTDLP,
          flush=True)
    commands = [
        ["python", "-m", "pip", "install", "-U", "-q", "yt-dlp",
         "--break-system-packages"],
        ["python", "-m", "pip", "install", "-U", "-q", "yt-dlp"],
        ["pip", "install", "-U", "-q", "yt-dlp", "--break-system-packages"],
        ["pip", "install", "-U", "-q", "yt-dlp"],
    ]
    for cmd in commands:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=300)
        except Exception:  # noqa: BLE001
            continue
        _YTDLP_CACHE["version"] = ""
        if not yt_dlp_is_outdated():
            print("[bridge] yt-dlp is now %s" % (yt_dlp_version() or "unknown"),
                  flush=True)
            return yt_dlp_version()
    print("[bridge] could not update yt-dlp - it is still %s"
          % (yt_dlp_version() or "unknown"), flush=True)
    return yt_dlp_version()


def normalize(text):
    """Lowercase and strip everything that is not a letter or digit."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


# Words that mark a video as a different recording than the one requested.
DISQUALIFIERS = (
    "cover", "live", "remix", "karaoke", "instrumental", "acoustic",
    "sped up", "slowed", "nightcore", "parody", "mashup", "reverb",
    "reprise", "demo", "snippet", "preview", "ringtone",
)

# Suffixes that carry no information and should not count as extra words.
NOISE_SUFFIXES = (
    "official video", "official music video", "official lyric video",
    "official audio", "official visualizer", "official hd", "official mv",
    "official version", "lyric video", "lyrics video", "music video",
    "visualizer", "audio only", "hd", "hq", "mv", "m v", "4k",
)


def strip_noise(title):
    """Remove filler suffixes such as '(Official Video)' from a title."""
    out = (title or "").lower()
    for suffix in NOISE_SUFFIXES:
        out = re.sub(re.escape(suffix), " ", out)
    # drop leftover punctuation left behind by the removal
    out = re.sub(r"[()\[\]{}]+", " ", out)
    return " ".join(out.split())


def disqualifier_penalty(title):
    """How strongly a title looks like a different recording than requested."""
    low = (title or "").lower()
    hits = 0
    for word in DISQUALIFIERS:
        if word in low:
            hits += 1
    if hits == 0:
        return 0.0
    return min(0.75, 0.30 + 0.25 * (hits - 1))


def similarity(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()



def search_candidates_with_video(query, found):
    """Asks for the official video as well, and puts it first.

    The search for a song hands over the official audio first - its title
    fits the song better - and that one has no picture at all. The
    official video is often not in the list at all, so it is asked for by
    name. Both lists are then sorted by score, and because the sort keeps
    the order of equal scores, the video is tried before the audio.
    """
    extra = []
    try:
        extra = search_candidates("%s official video" % query)
    except Exception as exc:  # noqa: BLE001
        print("[bridge] the search for the official video failed: %s" % exc,
              flush=True)
        return found
    seen = set(c.get("id") for c in found if c.get("id"))
    fresh = []
    for cand in extra:
        cid = cand.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            fresh.append(cand)
    return fresh + found


def score_candidate(cand, want_title, want_artist, want_duration):
    """Higher is better. Combines title match, artist match and duration match."""
    raw_title = cand.get("title") or ""
    cand_artist = normalize(cand.get("artist") or cand.get("uploader") or "")

    want_title_norm = normalize(want_title)
    cand_core = normalize(strip_noise(raw_title))

    title_score = similarity(cand_core, want_title_norm)

    # extra words in the candidate title usually mean a remix/cover variant
    extra = len(cand_core.split()) - len(want_title_norm.split())
    if extra > 0:
        title_score *= max(0.0, 1.0 - 0.18 * extra)

    artist_score = 0.0
    if want_artist:
        want_artist_norm = normalize(want_artist)
        artist_score = similarity(cand_artist, want_artist_norm)
        # the artist is often part of the title ("Artist - Title")
        artist_score = max(artist_score, similarity(normalize(raw_title), want_artist_norm))
        # a completely different artist is a strong signal against the match
        if artist_score < 0.45:
            artist_score -= 0.25

    duration_score = 0.0
    dur = cand.get("duration")
    if want_duration and dur:
        diff = abs(float(dur) - float(want_duration))
        if diff <= 10:
            duration_score = 1.0
        else:
            duration_score = max(0.0, 1.0 - (diff - 10) / 90.0)

    total = 0.45 * title_score + 0.30 * artist_score + 0.25 * duration_score
    total -= disqualifier_penalty(raw_title)
    return total


# Last logged state per job, so the terminal only shows changes.
JOB_LOGGED = {}



MEDIA_EXTS = {".mp4", ".m4v", ".m4a", ".webm", ".mkv", ".mov", ".mp3",
              ".opus", ".ogg", ".flv", ".avi"}

# What the user asked for, and what has to come out. When an audio
# conversion fails (no ffmpeg, a missing encoder) yt-dlp leaves the source
# file behind and never prints the after_move path - so the bridge would
# hand over a webm and call it an mp3.
EXPECTED_EXTS = {
    "audio_m4a": {".m4a"},
    "audio_mp3": {".mp3"},
    "audio_opus": {".opus", ".ogg"},
}


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #
# The bridge shows a code, the app is given that code once, and from then on
# the two know each other. The code carries the address and the key, so the
# user types one thing instead of three.
#
# The alphabet leaves out I, L, O and U: those are the letters people mistype.
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def b32encode(data):
    value = 0
    bits = 0
    out = []
    for byte in data:
        value = (value << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(CROCKFORD[(value >> bits) & 31])
            # Throw the bits away as soon as they have been used. What is
            # left is then always the group that is still to come.
            value &= (1 << bits) - 1
    if bits:
        out.append(CROCKFORD[(value << (5 - bits)) & 31])
    return "".join(out)


def b32decode(text):
    value = 0
    bits = 0
    out = bytearray()
    for ch in text.strip().upper():
        if ch in "- \t":
            continue
        index = CROCKFORD.find(ch)
        if index < 0:
            raise ValueError("that code has a letter that is not in it")
        value = (value << 5) | index
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((value >> bits) & 0xFF)
            value &= (1 << bits) - 1
    return bytes(out)


def split_public_url(url):
    """The scheme, the host and the path of a public address.

    The path is usually empty - a tunnel that forwards a whole host puts
    the bridge at the root - but a tunnel that forwards under a path
    needs it, and the phone has to be told.
    """
    text = str(url or "").strip()
    if "://" in text:
        scheme, rest = text.split("://", 1)
    else:
        scheme, rest = "https", text
    scheme = scheme.lower()
    if "/" in rest:
        host, path = rest.split("/", 1)
        path = "/" + path
    else:
        host, path = rest, ""
    host = host.strip().rstrip("/")
    # The port is not part of the host. It is kept in the host here and
    # read back out of it by public_port, because that is the only place
    # that knows how to tell a port from a colon in something else.
    return scheme, host, path


def public_port(scheme, host, fallback):
    """The port the phone should use to reach a public address.

    The bridge's own port is a number on this machine that means
    nothing outside it. What the phone needs is the port the address
    names - 443 for https - and that is what goes in the pairing code.
    """
    if ":" in host and not host.endswith("]"):
        try:
            return int(host.rsplit(":", 1)[1])
        except ValueError:
            pass
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return fallback


def find_cloudflared():
    """Where cloudflared is, if it is anywhere at all.

    Next to the bridge first, then in the bridge's own folder, then
    wherever it happens to be on the path. A copy next to the launcher
    is the one a user is most likely to have.
    """
    names = ["cloudflared.exe", "cloudflared"] if os.name == "nt" else ["cloudflared"]
    folders = [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.expanduser("~"), ".autosongs"),
    ]
    for folder in folders:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return shutil.which("cloudflared")


TUNNEL_URL = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def start_quick_tunnel(port):
    """Opens a hole to the internet and returns the address of it.

    The bridge itself stays on this machine and listens only where it
    always did. What reaches the internet is cloudflared, which makes an
    outgoing connection of its own and hands the phone an https address
    - so nothing on the home network has to be opened up, and no router
    has to be touched.

    The address it hands out is a quick tunnel: it works without an
    account and it changes every time the bridge starts. That is enough
    for a phone on the other side of the country, and the pairing code
    carries the new address with it.
    """
    exe = find_cloudflared()
    if not exe:
        raise RuntimeError(
            "cloudflared was not found. Put cloudflared.exe next to the "
            "bridge, or in %s, and start it again.\n"
            "It is a free download from Cloudflare: "
            "https://developers.cloudflare.com/cloudflare-one/connections/connect-apps"
            % os.path.join(os.path.expanduser("~"), ".autosongs")
        )
    cmd = [exe, "tunnel", "--url", "http://127.0.0.1:%d" % int(port),
           "--no-autoupdate"]
    print("[bridge] opening a tunnel with %s" % exe, flush=True)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    url = ""
    # What cloudflared said, kept so a failure can be explained.
    said = []

    def watch():
        nonlocal url
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line.strip():
                    print("[tunnel] " + line, flush=True)
                    said.append(line)
                if not url:
                    found = TUNNEL_URL.search(line)
                    if found:
                        url = found.group(0)
                        print("[bridge] the bridge is now reachable at %s" % url,
                              flush=True)
        except Exception:  # noqa: BLE001 - the pipe closing is normal
            pass

    threading.Thread(target=watch, daemon=True).start()

    # Wait for the address, but not for ever: a tunnel that never
    # appears is a failure the user has to be told about.
    for _ in range(120):
        if url:
            return proc, url
        if proc.poll() is not None:
            raise RuntimeError(_tunnel_failure(said))
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("the tunnel did not come up within a minute")


def _tunnel_failure(said):
    """What went wrong, in words a person can act on.

    Cloudflare limits how many quick tunnels one network may make in a
    short time, and a person who restarts the bridge a few times will
    hit it. The bare message "the tunnel stopped before it was ready"
    gives them nothing to do; this says what happened and what to do
    about it.
    """
    text = "\n".join(said)
    if "429" in text or "rate limit" in text.lower() or "too many" in text.lower():
        return ("Cloudflare is refusing more tunnels from this network at the "
                "moment - too many have been made in a short time. Wait a "
                "minute and start the bridge again.")
    if "no account" in text.lower() or "login" in text.lower() or "auth" in text.lower():
        return ("cloudflared needs to be signed in to make a tunnel. Run "
                "\"cloudflared tunnel login\" and start the bridge again.")
    if "not found" in text.lower() or "cannot find" in text.lower():
        return ("cloudflared was not found. Put cloudflared.exe beside the "
                "bridge, or in %s, and start it again."
                % os.path.join(os.path.expanduser("~"), ".autosongs"))
    return "the tunnel stopped before it was ready"


# ---- the fixed address, and the eight characters ---------------------------
#
# A quick tunnel is a new address every start, so a code that carries the
# address dies with it. With an account-backed tunnel the address is fixed:
# cloudflared keeps a named tunnel of its own, the server points a name at it
# once, and a restart lands on the same name.
#
# That name is then all the bridge has to remember, and the eight characters
# the user types are enough to find it - the phone asks the server which
# bridge owns those characters, and is given the address and the key while
# this bridge is running.
SERVER_API = os.environ.get("YTBRIDGE_PAIR_URL", "https://autosongs.org/api/paird")
TUNNEL_CONF = os.path.join(os.path.expanduser("~"), ".autosongs", "tunnel.json")
REGISTERED = threading.Event()          # set while the code is advertised
PAIR_SESSION = {}


def read_tunnel_conf():
    """The address this install already owns, if it has one."""
    try:
        with open(TUNNEL_CONF, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def write_tunnel_conf(data):
    try:
        os.makedirs(os.path.dirname(TUNNEL_CONF), exist_ok=True)
        with open(TUNNEL_CONF, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        try:
            os.chmod(TUNNEL_CONF, 0o600)
        except OSError:
            pass
    except OSError as exc:
        print("[bridge] could not save the tunnel: %s" % exc, flush=True)


def forget_tunnel():
    """Forgets the fixed address, so the next start asks for a new one."""
    try:
        os.remove(TUNNEL_CONF)
        return True
    except OSError:
        return False


def _post_json(url, payload, timeout=20):
    """POST to the pairing service. Returns (status, body-as-dict)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "autosongs-bridge/%s" % BRIDGE_VERSION},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw or "{}")
        except ValueError:
            return exc.code, {"error": raw[:200]}
    except Exception as exc:  # noqa: BLE001 - the network is allowed to be down
        return 0, {"error": str(exc)}


def ask_for_tunnel(port):
    """Makes a fixed address for this install, once.

    The token that makes the tunnel is kept on this machine afterwards, so a
    restart reuses the address instead of asking for a new one.
    """
    conf = read_tunnel_conf()
    if conf.get("token") and conf.get("hostname"):
        return conf
    status, body = _post_json(SERVER_API + "/tunnel/new",
                              {"port": int(port)}, timeout=30)
    if status != 200 or not body.get("token"):
        print("[bridge] no fixed address: %s"
              % body.get("error", "the pairing service did not answer"), flush=True)
        return {}
    conf = {
        "hostname": body["hostname"],
        "token": body["token"],
        "rotateKey": body.get("rotateKey", ""),
        "port": int(port),
    }
    write_tunnel_conf(conf)
    print("[bridge] this install now has a fixed address: %s"
          % conf["hostname"], flush=True)
    return conf


def start_named_tunnel(port, conf):
    """Runs the named tunnel and returns its address.

    The address does not come from cloudflared this time - it is the one this
    install already owns - so cloudflared only has to be up. It is judged up
    when it says it registered a connection, or when it is still running
    after twenty seconds, because a working tunnel that has been quiet for a
    moment must not be thrown away.
    """
    exe = find_cloudflared()
    if not exe:
        raise RuntimeError(
            "cloudflared was not found. Put cloudflared.exe beside the "
            "bridge, or in %s, and start it again."
            % os.path.join(os.path.expanduser("~"), ".autosongs"))
    cmd = [exe, "tunnel", "--no-autoupdate", "run", "--token", conf["token"]]
    print("[bridge] using the fixed address %s" % conf["hostname"], flush=True)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    ready = threading.Event()
    said = []

    def watch():
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line.strip():
                    print("[tunnel] " + line, flush=True)
                    said.append(line)
                low = line.lower()
                if "registered tunnel connection" in low or "connection registered" in low:
                    ready.set()
        except Exception:  # noqa: BLE001 - the pipe closing is normal
            pass

    threading.Thread(target=watch, daemon=True).start()

    for _ in range(40):
        if ready.is_set():
            return proc, conf["hostname"]
        if proc.poll() is not None:
            raise RuntimeError(_tunnel_failure(said))
        time.sleep(0.5)

    if proc.poll() is None:
        return proc, conf["hostname"]
    raise RuntimeError(_tunnel_failure(said))


def start_tunnel(port, fixed=True):
    """Opens a hole to the internet and returns the address of it.

    With a fixed address the same eight characters keep working after a
    restart. Without one - no account on the server, or the service is
    unreachable - it falls back to a quick tunnel, which works straight away
    and hands out a new address every time.
    """
    if fixed:
        conf = ask_for_tunnel(port)
        if conf:
            try:
                return start_named_tunnel(port, conf)
            except RuntimeError as exc:
                print("[bridge] %s" % exc, flush=True)
                print("[bridge] falling back to a quick tunnel", flush=True)
    return start_quick_tunnel(port)


def register_pair_code(code, public_url, key):
    """Tells the pairing service where this bridge is, and keeps saying so.

    The phone only knows eight characters. The service turns them into an
    address, and it only answers while this thread is beating - so a bridge
    that is closed, crashed or killed stops being reachable instead of
    pointing at nothing.
    """
    if not code or not public_url:
        return
    claim = secrets.token_hex(16)
    PAIR_SESSION.update({"code": code, "claim": claim, "url": public_url,
                         "stop": threading.Event()})

    def run():
        delay = 300
        while not PAIR_SESSION["stop"].is_set():
            status, body = _post_json(SERVER_API + "/bridge/register",
                                      {"code": code, "url": public_url,
                                       "key": key, "claim": claim})
            if status == 200:
                delay = max(60, int(body.get("ttlSeconds", 900)) // 3)
                print("[bridge] the code %s works from any network while the "
                      "bridge runs" % code, flush=True)
                REGISTERED.set()
                break
            print("[bridge] could not advertise the code: %s"
                  % body.get("error", status), flush=True)
            PAIR_SESSION["stop"].wait(30)
            if PAIR_SESSION["stop"].is_set():
                return

        while not PAIR_SESSION["stop"].wait(delay):
            status, body = _post_json(SERVER_API + "/bridge/beat",
                                      {"code": code, "claim": claim})
            if status == 200:
                continue
            if status == 404:
                REGISTERED.clear()
                status, body = _post_json(SERVER_API + "/bridge/register",
                                          {"code": code, "url": public_url,
                                           "key": key, "claim": claim})
                if status == 200:
                    REGISTERED.set()
                    continue
            # Not fatal: the bridge still works for anybody holding the long
            # code, and the code is advertised again on the next beat that
            # gets through.
            print("[bridge] the pairing service did not answer: %s"
                  % body.get("error", status), flush=True)

    threading.Thread(target=run, daemon=True).start()


def stop_pairing():
    """Withdraws the code, so it stops pointing at a bridge that is closing."""
    code = PAIR_SESSION.get("code")
    if not code:
        return
    PAIR_SESSION["stop"].set()
    _post_json(SERVER_API + "/bridge/drop",
               {"code": code, "claim": PAIR_SESSION.get("claim", "")}, timeout=5)



def is_ipv4(host):
    parts = str(host).split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or not 0 <= int(part) <= 255:
            return False
    return True


def pairing_code(host, port, secret_hex, public_url=""):
    """The code the user copies into the app.

    With a public address the code carries the whole address - the
    scheme, the host and any path under it - because a bridge that is
    reached over the internet is not found by asking the network, so the
    phone has to be told where it is.
    """
    body = bytearray()
    body.append(1)                                    # the version of the format
    if public_url:
        scheme, url_host, url_path = split_public_url(public_url)
        body.append(7)                                # an address, not just a host
        body.append(1 if scheme == "https" else 0)
        # The port is a field of its own in the code, so it is taken off
        # the host here.
        name = url_host.split(":")[0].encode("utf-8")[:200]
        body.append(len(name))
        body += name
        # The port in the code is the one the address names - 443 for
        # https - not the bridge's own port, which is a number on this
        # machine and means nothing outside it.
        body += int(public_port(scheme, url_host, port)).to_bytes(2, "big")
        path = url_path.encode("utf-8")[:200]
        body.append(len(path))
        body += path
    elif is_ipv4(host):
        body.append(4)
        body += bytes(int(part) for part in str(host).split("."))
        body += int(port).to_bytes(2, "big")
    else:
        name = str(host).encode("utf-8")[:200]
        body.append(6)
        body.append(len(name))
        body += name
        body += int(port).to_bytes(2, "big")
    body += bytes.fromhex(secret_hex)
    body.append(sum(body) & 0xFF)                    # a checksum, so a typo shows up
    text = b32encode(bytes(body))
    return "-".join(text[i:i + 5] for i in range(0, len(text), 5))


def read_pairing_code(text):
    """What the app does with the code.

    Returns (host, port, secret, scheme, path). The scheme and the path
    are what a bridge reached over the internet needs: it is not on the
    same network, so the phone cannot look it up and has to be told
    exactly where it is.
    """
    body = b32decode(text)
    if len(body) < 15:
        raise ValueError("that code is too short")
    if body[-1] != (sum(body[:-1]) & 0xFF):
        raise ValueError("that code has a letter wrong, or a dash missing")
    if body[0] != 1:
        raise ValueError("that code is from a newer version of AutoSongs")
    kind = body[1]
    scheme = "http"
    path = ""
    if kind == 4:
        host = ".".join(str(b) for b in body[2:6])
        rest = body[6:]
    elif kind == 6:
        length = body[2]
        host = body[3:3 + length].decode("utf-8", "replace")
        rest = body[3 + length:]
    elif kind == 7:
        # An address rather than a host: the scheme, the host, the port
        # and any path under it, in that order.
        scheme = "https" if body[2] else "http"
        length = body[3]
        host = body[4:4 + length].decode("utf-8", "replace")
        rest = body[4 + length:]
        port = int.from_bytes(rest[0:2], "big")
        path_length = rest[2]
        path = rest[3:3 + path_length].decode("utf-8", "replace")
        secret = rest[3 + path_length:-1]
        return host, port, secret.hex().upper(), scheme, path
    else:
        raise ValueError("that code is not one of ours")
    port = int.from_bytes(rest[0:2], "big")
    secret = rest[2:-1]
    return host, port, secret.hex().upper(), scheme, path


def make_pair_code():
    """Eight characters, from the alphabet people can read out loud."""
    value = int.from_bytes(os.urandom(5), "big")
    return "".join(CROCKFORD[(value >> (5 * (7 - i))) & 31] for i in range(8))


def normalize_pair_code(text):
    """The code as it looks after someone has typed it.

    The dashes and spaces go. Everything else has to be in the alphabet,
    so a letter that is not in it is reported rather than quietly thrown
    away - a code that is read wrong must not become a different code.
    """
    out = []
    for ch in str(text).upper():
        if ch in "- \t":
            continue
        if ch not in CROCKFORD:
            raise ValueError("that code has a letter that is not in it")
        out.append(ch)
    return "".join(out)


def pair_code_hash(code):
    """A fingerprint of the code.

    The bridge never says the code out loud on the network. It says this
    instead, and the phone compares it against the code the user typed.
    So hearing the answer does not let anyone else in.
    """
    return hashlib.sha256(
        normalize_pair_code(code).encode("ascii")).hexdigest()[:16]


def start_pair_responder(port):
    """Answers the phones that are looking for this bridge.

    A phone cannot ask for a bridge it has no address for. So it calls
    out to the whole network, and every bridge answers with a
    fingerprint of the code it is showing. The phone matches that with
    the code the user typed, and only then says anything to the bridge.
    """
    def serve():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", int(port)))
        except OSError:
            return
        while True:
            try:
                data, addr = sock.recvfrom(2048)
            except OSError:
                break
            if data.strip() != PAIR_PROBE or not PAIR_CODE:
                continue
            reply = json.dumps({
                "h": pair_code_hash(PAIR_CODE),
                "host": lan_address(),
                "port": int(port),
                "version": BRIDGE_VERSION,
            }).encode("utf-8")
            try:
                sock.sendto(reply, addr)
            except OSError:
                pass
    threading.Thread(target=serve, daemon=True).start()


def version_from_package(mod):
    """The version number out of the yt_dlp package, if it is in there.

    Some builds keep the number in the package's own file rather than on
    the module. A version number is not worth failing over.
    """
    try:
        folder = os.path.dirname(os.path.abspath(mod.__file__))
        with open(os.path.join(folder, "version.py"), "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except Exception:  # noqa: BLE001
        pass
    return ""


def secret_path():
    return os.path.join(os.path.expanduser("~"), ".autosongs", "secret")


def load_or_make_secret():
    """The key the app and the bridge share.

    It is made once and kept, so a phone stays paired after the bridge is
    restarted. It is the same string the app sends as its auth token.
    """
    path = secret_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
        if len(text) >= 16:
            return text[:16].upper()
    except OSError:
        pass
    secret = os.urandom(8).hex().upper()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(secret)
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret


def lan_address():
    """The address a phone on the same network can reach this bridge at."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect(("8.8.8.8", 53))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def default_workdir():
    """Where downloads are kept.

    In Termux that is the app's own folder. Everywhere else it is a folder
    in the user's home, because a bridge that runs on a desktop should not
    be writing into somebody else's app.
    """
    if os.path.isdir("/data/data/com.termux"):
        return "/data/data/com.termux/files/home/autosongs/downloads"
    return os.path.join(os.path.expanduser("~"), ".autosongs", "downloads")


def print_pairing_banner(host, port, secret, public_url=""):
    """Shows the code the phone needs.

    With a public address the phone cannot find the bridge by asking the
    network - it is not on the same network - so the long code is the
    way in, and it carries the address and the key with it.
    """
    code = pairing_code(host, port, secret, public_url=public_url)
    line = "  " + "-" * 58
    print("", flush=True)
    print("  AutoSongs bridge %s" % BRIDGE_VERSION, flush=True)
    print(line, flush=True)
    print("", flush=True)
    if public_url:
        print("  This bridge is reachable from anywhere:", flush=True)
        print("", flush=True)
        print("      %s" % public_url, flush=True)
        print("", flush=True)
        print("  On the phone:  AutoSongs - Pair remote bridge - type these", flush=True)
        print("  eight characters. They work from any network, and they keep", flush=True)
        print("  working after the bridge restarts:", flush=True)
        print("", flush=True)
        print("      %s" % (PAIR_CODE or "--------"), flush=True)
        print("", flush=True)
        print("  If the phone cannot reach the pairing service, paste this", flush=True)
        print("  long code instead - it carries the address and the key:", flush=True)
        print("", flush=True)
        print("      %s" % code, flush=True)
    else:
        print("  On the phone:  AutoSongs - Pair remote bridge - type this code:", flush=True)
        print("", flush=True)
        print("      %s" % (PAIR_CODE or "--------"), flush=True)
        print("", flush=True)
        print("  The phone finds this bridge by itself and sets up the address.", flush=True)
        print("", flush=True)
        print("  If the phone cannot find it, paste this long code in Settings:", flush=True)
        print("", flush=True)
        print("      %s" % code, flush=True)
    print("", flush=True)
    print("  Address: %s:%d" % (host, port), flush=True)
    print("", flush=True)
    print(line, flush=True)
    print("", flush=True)



def has_ffmpeg():
    """ffmpeg is required by every --extract-audio preset."""
    if EMBEDDED:
        # An app cannot start programs, so there is no ffmpeg inside it.
        return False
    return shutil.which("ffmpeg") is not None


def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "")
    return name.strip() or "download"


def find_finished_file(name, max_age=3600, part=""):
    """Finds a finished download in the workdir by its name.

    The job records live in memory and are lost whenever the bridge
    restarts. The files themselves stay on disk, so the app can still get
    its download when the bridge was restarted mid-transfer.

    The name must match: returning "the newest media file" instead would
    happily hand over a completely different song.
    """
    stem = sanitize(name)
    if not stem:
        return None
    now = time.time()
    best = None
    best_age = None
    for root, _dirs, names in os.walk(WORKDIR):
        for n in names:
            if os.path.splitext(n)[1].lower() not in MEDIA_EXTS:
                continue
            if not n.startswith(stem):
                continue
            if part == "video" and ".video" not in n.lower():
                continue
            if part == "audio" and ".audio" not in n.lower():
                continue
            path = os.path.join(root, n)
            try:
                age = now - os.path.getmtime(path)
            except OSError:
                continue
            if age > max_age:
                continue
            if best_age is None or age < best_age:
                best_age = age
                best = path
    return best


# A last-resort format. The high quality formats need a proof of origin
# token, which YouTube does not always hand out - the low quality ones
# usually work without one.
# How many matches to try before giving up on finding a picture.
VIDEO_TRIES = 6

FALLBACK_AUDIO_FMT = "worstaudio[ext=m4a]/worstaudio/best"
FALLBACK_VIDEO_FMT = "worstvideo[ext=mp4]+worstaudio[ext=m4a]/worst[ext=mp4]/worst"


def build_download_args(preset, video_quality, embed_metadata, embed_thumbnail,
                        format_override=None):
    """Translate a preset id into real yt-dlp download arguments."""
    args = _build_download_args(preset, video_quality, embed_metadata,
                                embed_thumbnail)
    if format_override:
        # Replace the format the preset asked for - used for the last-resort
        # attempt with a quality that does not need a proof of origin token.
        if "-f" in args:
            args[args.index("-f") + 1] = format_override
        else:
            args += ["-f", format_override]
    return args


def _build_download_args(preset, video_quality, embed_metadata, embed_thumbnail):
    common = ["--no-playlist", "--no-part", "--newline", "--no-warnings",
              "--no-cache-dir"]

    if preset.startswith("video_"):
        # The preset carries the quality ("video_720" means 720p). The
        # separate video_quality setting used to win, so picking "720p" in
        # the app actually downloaded 1080p - the label was a lie.
        m = re.search(r"(\d{3,4})", preset)
        q = int(m.group(1)) if m else int(video_quality or 1080)
        fmt = (
            f"bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a][vcodec=none]/"
            f"bestvideo[height<={q}]+bestaudio[vcodec=none]/"
            f"best[height<={q}][vcodec=none]/best"
        )
        # --no-part lets the video and the audio stream overwrite each other
        # instead of being muxed into one file, so it is not used for video.
        common = [c for c in common if c != "--no-part"]
        common += ["-f", fmt, "--merge-output-format", "mp4"]
        if embed_thumbnail:
            common += ["--embed-thumbnail"]
        if embed_metadata:
            common += ["--embed-metadata"]
        return common

    if preset == "audio_m4a":
        common += ["-f", "bestaudio[ext=m4a][vcodec=none]/bestaudio[vcodec=none]",
                   "--extract-audio", "--audio-format", "m4a",
                   "--audio-quality", "0"]
    elif preset == "audio_opus":
        common += ["-f", "bestaudio[ext=webm][vcodec=none]/bestaudio[vcodec=none]",
                   "--extract-audio", "--audio-format", "opus",
                   "--audio-quality", "160K"]
    elif preset == "audio_mp3":
        if has_ffmpeg():
            common += ["-f", "bestaudio[vcodec=none]/bestaudio",
                       "--extract-audio", "--audio-format", "mp3",
                       "--audio-quality", "320K"]
        else:
            # Without ffmpeg there is no re-encode on this side. The phone
            # has an mp3 encoder of its own, so the sound is handed over as
            # it is and the app makes the mp3.
            common += ["-f", "bestaudio[ext=m4a][vcodec=none]/bestaudio[vcodec=none]"]
    else:  # audio_original
        common += ["-f", "bestaudio[vcodec=none]/bestaudio"]

    if embed_thumbnail:
        common += ["--embed-thumbnail"]
    if embed_metadata:
        common += ["--embed-metadata"]
    return common


def client_sets():
    """The clients to try, one after another.

    YouTube refuses some clients with a 403 and lets others through, so
    this is a list of chances rather than a single choice.
    """
    if CLIENTS_OVERRIDE:
        return ["youtube:player_client=%s" % CLIENTS_OVERRIDE]
    if COOKIES.active:
        # Cookies are the reliable fix - no need to cycle clients.
        return [""]
    return ["", "youtube:player_client=android",
            "youtube:player_client=web",
            "youtube:player_client=mweb",
            "youtube:player_client=tv",
            "youtube:player_client=tv_simply",
            "youtube:player_client=ios",
            "youtube:player_client=android_vr"]


def _cli_search_candidates(query, depth, clients):
    """One search with the command line, with one set of clients."""
    cmd = yt_dlp_bin() + [
        "--flat-playlist", "--dump-json", "--no-warnings", "--no-playlist",
        "--skip-download", "--no-cache-dir",
    ]
    if clients:
        cmd += ["--extractor-args", clients]
    if PO_TOKEN:
        cmd += ["--extractor-args", "youtube:po_token=%s" % PO_TOKEN]
    cmd += COOKIES.cli_args()
    cmd.append("ytsearch%d:%s" % (depth, query))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception:  # noqa: BLE001
        return [], ""
    candidates = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            candidates.append(json.loads(line))
        except ValueError:
            continue
    stderr = (proc.stderr or "").strip()
    reason = stderr.splitlines()[-1] if stderr else ""
    return candidates, reason


def search_candidates(query, depth=SEARCH_DEPTH):
    """Looks for videos that match the query.

    One client is not always enough - YouTube refuses some of them - so
    the search goes down the same list the download uses.
    """
    reason = ""
    for clients in client_sets():
        if EMBEDDED:
            try:
                found = _api_search_candidates(query, depth, clients)
            except Exception as exc:  # noqa: BLE001
                reason = str(exc)
                continue
        else:
            found, reason = _cli_search_candidates(query, depth, clients)
        if found:
            return found
    raise RuntimeError(reason or "search returned nothing")


def _api_search_candidates(query, depth=SEARCH_DEPTH, clients=""):
    """Searches with yt-dlp as a library. This is what the app uses."""
    mod = yt_dlp_module()
    if mod is None:
        raise RuntimeError("yt-dlp is not installed in the app")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "ignoreerrors": True,
        # The candidates are only needed for their title and duration, so
        # the details of every single video are not fetched.
        "extract_flat": True,
    }
    extractor_args = _api_extractor_args(clients)
    if extractor_args:
        opts["extractor_args"] = extractor_args
    opts.update(COOKIES.api_opts())
    ydl = mod.YoutubeDL(opts)
    try:
        info = ydl.extract_info("ytsearch%d:%s" % (depth, query), download=False)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(str(exc))
    entries = (info or {}).get("entries") or []
    candidates = [e for e in entries if e]
    if not candidates:
        raise RuntimeError("search returned nothing")
    return candidates


# --------------------------------------------------------------------------- #
# the in-process path - the bridge that runs inside the app
# --------------------------------------------------------------------------- #
def api_has_ffmpeg():
    """The app cannot start programs, so there is no ffmpeg inside it.

    Joining a video and its sound, and re-encoding to mp3, both need
    ffmpeg. The bridge that runs in Termux still has it.
    """
    if EMBEDDED:
        return False
    return has_ffmpeg()


def api_download_plan(preset, video_quality):
    """What to ask yt-dlp for, and what cannot be done here.

    Returns (format, note). The note is empty when the request can be
    served exactly as it was asked.
    """
    if preset.startswith("video_"):
        # The picture and the sound are two streams. They are fetched
        # apart and joined on the phone, which is not this job's work.
        return None, ("a video is fetched as a picture and a sound, and "
                      "the phone joins them")
    if preset == "audio_mp3":
        # mp3 is a re-encode. The phone does that one itself, with its
        # own encoder, so the sound is fetched as it is.
        return "bestaudio[ext=m4a][vcodec=none]/bestaudio[vcodec=none]", (
            "the sound is fetched as it is, and the phone turns it into "
            "an mp3")
    if preset == "audio_opus":
        return "bestaudio[ext=webm][vcodec=none]/bestaudio[vcodec=none]", ""
    if preset == "audio_original":
        return "bestaudio[vcodec=none]/bestaudio", ""
    return "bestaudio[ext=m4a][vcodec=none]/bestaudio[vcodec=none]", ""



def _stream_flags(info):
    """Tells whether a downloaded file has a picture, and whether it has sound.

    yt-dlp says so in the format it used: "vcodec" and "acodec" are
    "none" when that stream is not there. This matters for videos: a
    match that only has the sound still carries the album cover, and
    saving that as a video gives the user a still picture of the cover
    with the song playing.
    """
    formats = (info or {}).get("requested_formats") or [info or {}]
    has_video = False
    has_audio = False
    for fmt in formats:
        if not fmt:
            continue
        vcodec = fmt.get("vcodec") or ""
        acodec = fmt.get("acodec") or ""
        if vcodec and vcodec != "none":
            has_video = True
        if acodec and acodec != "none":
            has_audio = True
    return has_video, has_audio


def api_download_attempt(url, outdir, preset, video_quality,
                          embed_metadata, embed_thumbnail, clients="",
                          progress=None, fmt_override=None, suffix=""):
    """Downloads one video with yt-dlp as a library.

    This is what the bridge inside the app uses. An app cannot start
    programs, so the command line is not an option there.

    Returns a dict with ok, title, artist, filepath, error and note.
    """
    mod = yt_dlp_module()
    if mod is None:
        return {"ok": False, "title": "", "artist": "", "filepath": "",
                "error": "yt-dlp is not available inside the app", "note": ""}

    fmt, note = api_download_plan(preset, video_quality)
    if fmt is None:
        return {"ok": False, "title": "", "artist": "", "filepath": "",
                "error": note, "note": ""}
    if fmt_override:
        # The last attempt uses a lower quality format, which does not need
        # a proof of origin token - so it often works when the others do not.
        fmt = fmt_override

    finished = {}

    def hook(d):
        if d.get("status") == "finished":
            path = d.get("filename") or ""
            if path:
                finished["path"] = path
        if progress:
            try:
                total = d.get("total_bytes") or 0
                done = d.get("downloaded_bytes") or 0
                if total:
                    progress(int(done * 100 / total))
            except Exception:  # noqa: BLE001
                pass

    opts = {
        "format": fmt,
        # The suffix keeps two streams of the same video apart: the
        # picture lands in "Title.video.mp4" and the sound in
        # "Title.audio.m4a".
        "outtmpl": os.path.join(outdir, "%(title).180s" + suffix + ".%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "cachedir": False,
        "overwrites": True,
        "progress_hooks": [hook],
    }
    extractor_args = _api_extractor_args(clients)
    if PO_TOKEN:
        extractor_args = extractor_args or {}
        youtube = dict(extractor_args.get("youtube") or {})
        youtube["po_token"] = [PO_TOKEN]
        extractor_args["youtube"] = youtube
    if extractor_args:
        opts["extractor_args"] = extractor_args
    opts.update(COOKIES.api_opts())

    try:
        with mod.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "title": "", "artist": "", "filepath": "",
                "error": str(exc), "note": note}

    path = finished.get("path") or (info or {}).get("filepath") or ""
    if not path or not os.path.isfile(path):
        return {"ok": False, "title": "", "artist": "", "filepath": "",
                "error": "yt-dlp finished but produced no file", "note": note}

    title = (info or {}).get("title") or ""
    artist = ((info or {}).get("artist") or (info or {}).get("uploader")
              or (info or {}).get("channel") or "")
    if not note and preset == "audio_m4a" and not path.lower().endswith(".m4a"):
        note = ("YouTube had no M4A for this one - the original format "
                "was saved instead")
    has_video, has_audio = _stream_flags(info)
    # The address of the cover. The phone puts the picture in the mp3's
    # tag, and a session is free to keep its album art to itself - so
    # this is the way to a picture that is always there.
    thumbnail = (info or {}).get("thumbnail") or ""
    return {"ok": True, "title": title, "artist": artist, "filepath": path,
            "error": "", "note": note, "thumbnail": thumbnail,
            "has_video": has_video, "has_audio": has_audio}


def _api_download_part(url, outdir, fmt, fallback_fmt, suffix, clients_list,
                       progress, info):
    """Downloads one stream of a video, trying every client until one works.

    The picture and the sound are two separate downloads, because joining
    them needs ffmpeg - and the phone joins them with MediaMuxer instead.
    """
    attempts = [(c, fmt) for c in clients_list]
    # The last resort: a lower quality format, which does not need a proof
    # of origin token and therefore often works when the others do not.
    attempts.append((clients_list[0] if clients_list else "", fallback_fmt))
    last_error = ""
    for clients, use_fmt in attempts:
        result = api_download_attempt(
            url, outdir, "audio_original", 0, False, False,
            clients=clients, progress=progress, fmt_override=use_fmt,
            suffix=suffix)
        if result.get("ok"):
            if not info.get("title"):
                info["title"] = result.get("title") or ""
                info["artist"] = result.get("artist") or ""
            return result
        last_error = result.get("error") or "the download failed"
        print("[bridge] %s: %s failed: %s"
              % (suffix, clients or "the default client", last_error),
              flush=True)
    return {"ok": False, "error": last_error, "filepath": ""}


def _run_embedded_video_job(job_id, candidates, outdir, preset, video_quality,
                             update):
    """The video path inside the app: two files, joined by the phone.

    Joining the picture and the sound needs ffmpeg, and an app cannot run a
    program. Android has MediaMuxer, which does the same job, so the bridge
    hands the two streams over separately and the phone joins them.

    The matches are tried one after the other. The one whose title fits
    best is often the official audio, and that one has no picture at all -
    but the official video is usually second or third. The picture and the
    sound always come from the same match, so they can never be two
    different songs.
    """
    m = re.search(r"(\d{3,4})", preset)
    q = int(m.group(1)) if m else int(video_quality or 1080)
    clients = client_sets()
    info = {}
    reasons = []

    def progress(p):
        update(percent=15 + int(p * 0.8))

    for number, video_url in enumerate(candidates[:VIDEO_TRIES]):
        update(status="downloading", percent=15,
               note=("downloading the picture" if number == 0
                     else "trying another match - this one has no picture"))
        # The chain stops at the pictures. It must not end in "best":
        # for a match with no picture that is the sound, and the sound
        # carries the album cover - saving that as a video gives the user
        # a still picture of the cover with the song playing.
        video = _api_download_part(
            video_url, outdir,
            "bestvideo[height<=%d][ext=mp4]/bestvideo[height<=%d]" % (q, q),
            "worstvideo[ext=mp4]", ".video", clients, progress, info)
        if not video.get("ok"):
            reasons.append(video.get("error") or "the picture could not be fetched")
            continue
        if not video.get("has_video"):
            # This match has only the sound. Throw the file away so it
            # cannot be mistaken for a picture later.
            try:
                os.remove(video["filepath"])
            except OSError:
                pass
            reasons.append("that match has no picture")
            continue

        update(status="downloading", percent=55, note="downloading the sound")
        audio = _api_download_part(
            video_url, outdir, "bestaudio[ext=m4a][vcodec=none]/bestaudio[vcodec=none]",
            "worstaudio[ext=m4a]", ".audio", clients, progress, info)
        if not audio.get("ok"):
            reasons.append(audio.get("error") or "the sound could not be fetched")
            continue

        title = info.get("title") or ""
        artist = info.get("artist") or ""
        thumbnail = info.get("thumbnail") or ""
        stem = "%s - %s" % (artist, title) if artist else (title or "video")
        base = sanitize(stem)
        video_ext = os.path.splitext(video["filepath"])[1] or ".mp4"
        audio_ext = os.path.splitext(audio["filepath"])[1] or ".m4a"
        video_target = os.path.join(WORKDIR, base + ".video" + video_ext)
        audio_target = os.path.join(WORKDIR, base + ".audio" + audio_ext)
        shutil.move(video["filepath"], video_target)
        shutil.move(audio["filepath"], audio_target)

        update(status="done", percent=100, title=title, artist=artist,
               has_file=True, parts=True, file_video=video_target,
               file_audio=audio_target, audio_ext=audio_ext,
               files=[os.path.basename(video_target),
                      os.path.basename(audio_target)],
               quality=preset, thumbnail=thumbnail)
        return

    update(status="error",
           error="none of the matches has a picture - only the sound"
                 + ((" (%s)" % reasons[0]) if reasons else ""))





# --------------------------------------------------------------------------- #
# job handling
# --------------------------------------------------------------------------- #
def run_job(job_id, query, preset, video_quality, embed_metadata,
            embed_thumbnail, want_title, want_artist, want_duration,
            save="local"):
    """Runs a download, and runs it again with cookies if YouTube asks.

    YouTube sometimes answers with a sign-in demand instead of the video.
    The cure is a cookie jar, and there may be one lying about - next to
    the bridge, in the work folder, in the home folder - that the bridge
    has not looked for yet.

    So the job is run again from the top with that jar: the sign-in can
    land in the search as well as in the download, and a search that was
    refused leaves nothing to download.
    """
    global COOKIES

    _run_job_once(job_id, query, preset, video_quality, embed_metadata,
                  embed_thumbnail, want_title, want_artist, want_duration,
                  save=save)

    with JOBS_LOCK:
        job = dict(JOBS.get(job_id, {}))
    if not job.get("bot_check"):
        return
    # A jar is already in use and it did not help, so trying again with
    # the same jar would only fail the same way.
    if COOKIES.active:
        return

    path, source = find_cookie_source("")
    if not path:
        # Nothing to try. The job already says so, and the app can offer
        # to send a jar.
        return

    print("[bridge] job %s: YouTube asked for a sign-in - retrying with the "
          "cookies %s" % (job_id, source), flush=True)
    COOKIES = CookieSource(path, source)

    # The first attempt may have left files behind. The retry has to make
    # its own, or it hands the leftovers over as if they were the track.
    outdir = os.path.join(WORKDIR, job_id)
    try:
        for name in os.listdir(outdir):
            victim = os.path.join(outdir, name)
            if os.path.isdir(victim):
                shutil.rmtree(victim, ignore_errors=True)
            else:
                try:
                    os.remove(victim)
                except OSError:
                    pass
    except OSError:
        pass

    with JOBS_LOCK:
        JOBS.setdefault(job_id, {}).update(
            status="searching", percent=5,
            note="YouTube asked for a sign-in - trying again with cookies")
    _run_job_once(job_id, query, preset, video_quality, embed_metadata,
                  embed_thumbnail, want_title, want_artist, want_duration,
                  save=save)


def _run_job_once(job_id, query, preset, video_quality, embed_metadata,
                  embed_thumbnail, want_title, want_artist, want_duration,
                  save="local"):
    """One attempt at a download, with whatever cookies are in use now.

    The wrapper around this one retries the whole job with a cookie jar
    when YouTube asks for a sign-in, so this function does not have to
    know about that.
    """
    outdir = os.path.join(WORKDIR, job_id)
    os.makedirs(outdir, exist_ok=True)
    started_at = time.time()

    def update(**kw):
        with JOBS_LOCK:
            JOBS.setdefault(job_id, {}).update(kw)

    # Every attempt starts by forgetting what the last one said. A retry
    # that works must not go on saying that cookies are needed.
    update(status="searching", percent=5, bot_check=False, needs_cookies=False)
    print("[bridge] job %s: searching for %r" % (job_id, query), flush=True)

    try:
        # ---- 1. search for candidates -----------------------------------
        try:
            candidates = search_candidates(query)
            if preset.startswith("video_"):
                # The official video is often not in the results at all,
                # and the official audio - which has no picture - usually
                # is. So the video is asked for by name as well.
                candidates = search_candidates_with_video(query, candidates)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if is_bot_check(msg):
                update(status="error", error="YouTube asked for sign-in (bot check). "
                                             "A cookie jar gets past it - the app "
                                             "can send one, or put cookies.txt next "
                                             "to the bridge.",
                       bot_check=True, needs_cookies=True)
            else:
                update(status="error", error="search failed: %s" % msg)
            return

        # ---- 2. pick the best candidate ---------------------------------
        best = None
        best_score = -1.0
        for cand in candidates:
            if cand.get("ie_key") == "YoutubeTab" or cand.get("live_status"):
                continue
            s = score_candidate(cand, want_title, want_artist, want_duration)
            if s > best_score:
                best_score = s
                best = cand

        if best is None or not best.get("id"):
            update(status="error", error="no matching video found for %r" % query)
            return

        video_id = best["id"]
        update(status="downloading", percent=15,
               title=best.get("title") or "",
               artist=best.get("artist") or best.get("uploader") or "",
               video_id=video_id, match_score=round(best_score, 3))

        # ---- 3. download that one video ---------------------------------
        video_url = "https://www.youtube.com/watch?v=%s" % video_id
        print("[bridge] job %s: downloading %s (%s)" % (job_id, video_id, preset),
              flush=True)
        title = artist = ""
        stderr_tail = []
        returncode = 1

        # YouTube sometimes refuses a specific client ("Sign in to confirm
        # you're not a bot"). Trying another client usually gets past it, so we
        # fall back through a couple of known-good combinations.
        client_list = client_sets()

        # Muxing video and audio needs ffmpeg. Without it yt-dlp either fails
        # or leaves two separate files, so say so before starting.
        if preset.startswith("video_") and not has_ffmpeg() and not EMBEDDED:
            update(status="error",
                   error="ffmpeg is required to mux the video and audio tracks. "
                         "Install it in Termux: pkg install ffmpeg")
            return

        if EMBEDDED and preset.startswith("video_"):
            # Inside the app the picture and the sound come as two files and
            # the phone joins them - MediaMuxer is part of Android, so no
            # ffmpeg is needed here either.
            #
            # Every match is offered, best first: the one whose title fits
            # best is often the official audio, which has no picture at all.
            ranked = sorted(
                [c for c in candidates
                 if c.get("ie_key") != "YoutubeTab" and not c.get("live_status")
                 and c.get("id")],
                key=lambda c: score_candidate(c, want_title, want_artist,
                                              want_duration),
                reverse=True)
            urls = ["https://www.youtube.com/watch?v=%s" % c["id"]
                    for c in ranked]
            _run_embedded_video_job(job_id, urls, outdir, preset,
                                     video_quality, update)
            return

        # The attempts: every client, and at the very end a lower quality
        # format. The high quality formats need a proof of origin token,
        # which YouTube does not always hand out - the low quality ones
        # usually work without one.
        attempts = [(c, None) for c in client_list]
        attempts.append((client_list[0] if client_list else "",
                         FALLBACK_VIDEO_FMT if preset.startswith("video_")
                         else FALLBACK_AUDIO_FMT))

        for clients, fmt_override in attempts:
            if EMBEDDED:
                # Inside the app yt-dlp is a library, not a command. The
                # command line cannot be used there at all: an app is not
                # allowed to start other programs.
                result = api_download_attempt(
                    video_url, outdir, preset, video_quality,
                    embed_metadata, embed_thumbnail, clients=clients,
                    fmt_override=fmt_override,
                    progress=lambda p: update(percent=15 + int(p * 0.8)))
                title = result.get("title") or ""
                artist = result.get("artist") or ""
                thumbnail = result.get("thumbnail") or ""
                produced = [result["filepath"]] if result.get("filepath") else []
                if result.get("note"):
                    update(status="downloading", percent=15,
                           note=result["note"])
                if result.get("ok"):
                    returncode = 0
                    stderr_tail = []
                    tail_lines = [result.get("note") or ""]
                    break
                returncode = 1
                stderr_tail = [result.get("error") or "the download failed"]
                tail_lines = list(stderr_tail)
                print("[bridge] job %s: %s failed: %s"
                      % (job_id, clients or "the default client", stderr_tail[-1]),
                      flush=True)
                continue
            args = yt_dlp_bin() + [
                "-o", os.path.join(outdir, "%(title).180s.%(ext)s"),
                "--newline", "--no-warnings", "--no-cache-dir",
                "--print", "AUTOSONGS_META %(title)s\x1f%(artist)s\x1f%(uploader)s"
                "\x1f%(thumbnail)s",
                # yt-dlp knows the final path; guessing it from the title is
                # unreliable when the title contains path characters.
                # after_move: the path AFTER post-processing and after the file
                # was moved to its final name. Without it yt-dlp reports the
                # pre-merge stream (Title.f137.webm), which is deleted as soon
                # as the mux succeeds - so the bridge would fall back to
                # hunting for the file and could pick up a previous track.
                "--print", "after_move:AUTOSONGS_FILE %(filepath)s",
            ]
            if clients:
                args += ["--extractor-args", clients]
            if PO_TOKEN:
                # YouTube hands out format URLs that expire and need a proof
                # of origin. Without a PO token the download fails with
                # "HTTP Error 403: Forbidden".
                args += ["--extractor-args", "youtube:po_token=%s" % PO_TOKEN]
            args += COOKIES.cli_args()
            args += build_download_args(preset, video_quality, embed_metadata,
                                        embed_thumbnail, fmt_override)
            args += [video_url]

            proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
            title = artist = ""
            produced = []
            stderr_tail = []
            tail_lines = []
            thumbnail = ""
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("AUTOSONGS_META "):
                    parts = line[len("AUTOSONGS_META "):].split("\x1f")
                    title = (parts[0] if parts else "").strip()
                    artist = ((parts[1] if len(parts) > 1 else "").strip() or
                              (parts[2] if len(parts) > 2 else "").strip())
                    thumbnail = (parts[3] if len(parts) > 3 else "").strip()
                m = re.search(r"\[download\]\s+([\d.]+)%", line)
                if m:
                    try:
                        update(percent=int(float(m.group(1))))
                    except ValueError:
                        pass
                if line.startswith("AUTOSONGS_FILE "):
                    produced.append(line[len("AUTOSONGS_FILE "):].strip())
                tail_lines.append(line)
                tail_lines = tail_lines[-8:]
                if line.startswith("ERROR:") or "Traceback" in line:
                    stderr_tail.append(line)
                    stderr_tail = stderr_tail[-4:]
            proc.wait()
            returncode = proc.returncode

            if returncode == 0:
                break
            # Retry on every failure another client might get past. The 403
            # is the important one: YouTube refuses some clients at some
            # moments and serves others a moment later.
            blob = " ".join(stderr_tail)
            retryable = (is_bot_check(blob)
                         or "403" in blob or "Forbidden" in blob
                         or "PO Token" in blob
                         or "unable to download video data" in blob)
            if not retryable:
                break
            if clients:
                update(status="downloading", percent=15,
                       note="retrying with %s" % clients.split("=")[-1])
            else:
                update(status="downloading", percent=15,
                       note="retrying with a lower quality format")

        # A 403 from every client usually means yt-dlp itself is too old,
        # not that YouTube refused this particular video. Updating yt-dlp
        # and trying once more is cheap and fixes the most common failure
        # there is - the phone does not have to be touched by hand.
        if returncode != 0 and not EMBEDDED and yt_dlp_is_outdated():
            update(status="downloading", percent=15,
                   note="yt-dlp is too old - updating it and retrying")
            upgrade_yt_dlp()
            for clients, fmt_override in attempts:
                args = yt_dlp_bin() + [
                    "-o", os.path.join(outdir, "%(title).180s.%(ext)s"),
                    "--newline", "--no-warnings", "--no-cache-dir",
                    "--print",
                    "AUTOSONGS_META %(title)s\x1f%(artist)s\x1f%(uploader)s",
                    "--print", "after_move:AUTOSONGS_FILE %(filepath)s",
                ]
                if clients:
                    args += ["--extractor-args", clients]
                if PO_TOKEN:
                    args += ["--extractor-args", "youtube:po_token=%s" % PO_TOKEN]
                args += COOKIES.cli_args()
                args += build_download_args(preset, video_quality, embed_metadata,
                                            embed_thumbnail, fmt_override)
                args += [video_url]
                proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        bufsize=1)
                title = artist = ""
                produced = []
                stderr_tail = []
                tail_lines = []
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    if line.startswith("AUTOSONGS_META "):
                        parts = line[len("AUTOSONGS_META "):].split("\x1f")
                        title = (parts[0] if parts else "").strip()
                        artist = ((parts[1] if len(parts) > 1 else "").strip() or
                                  (parts[2] if len(parts) > 2 else "").strip())
                    m = re.search(r"\[download\]\s+([\d.]+)%", line)
                    if m:
                        try:
                            update(percent=int(float(m.group(1))))
                        except ValueError:
                            pass
                    if line.startswith("AUTOSONGS_FILE "):
                        produced.append(line[len("AUTOSONGS_FILE "):].strip())
                    tail_lines.append(line)
                    tail_lines = tail_lines[-8:]
                    if line.startswith("ERROR:") or "Traceback" in line:
                        stderr_tail.append(line)
                        stderr_tail = stderr_tail[-4:]
                proc.wait()
                returncode = proc.returncode
                if returncode == 0:
                    break

        if returncode != 0:
            print("[bridge] job %s: every client failed: %s"
                  % (job_id, " | ".join([l for l in stderr_tail[-3:] if l])[:400]),
                  flush=True)
            detail = stderr_tail[-1] if stderr_tail else ("yt-dlp exited with %s" % returncode)
            if is_bot_check(detail):
                detail = ("YouTube asked for sign-in (bot check). A cookie jar gets "
                          "past it - the app can send one, or put cookies.txt next "
                          "to the bridge.")
                update(status="error", error=detail,
                       bot_check=True, needs_cookies=True)
                return
            elif "403" in detail or "Forbidden" in detail or "PO Token" in blob:
                # Name the yt-dlp version. "Update yt-dlp" is useless advice
                # when you cannot see which version is installed - and on the
                # phone that turned out to be the whole problem.
                detail = ("YouTube refused the download (403 - it wants a proof of "
                          "origin token). %d client(s) and a lower quality format "
                          "were tried. yt-dlp %s is installed, %s or newer is "
                          "needed. Update it: pip install -U yt-dlp, or pass "
                          "cookies: --cookies /path/cookies.txt"
                          % (len(attempts), yt_dlp_version() or "unknown",
                             MIN_YTDLP))
            update(status="error", error=detail)
            return

        # Prefer the path yt-dlp itself reported - the last one that exists.
        final = ""
        for path in reversed(produced):
            if path and os.path.isfile(path):
                final = path
                break

        # Only files from THIS job count. Finished downloads live in WORKDIR
        # under their final name, so scanning all of WORKDIR could hand back
        # a previous track's file - the app would then save the same bytes a
        # second time under a different name.
        job_files = []
        for root, _dirs, names in os.walk(outdir):
            for n in names:
                if n.endswith(".part") or n.startswith("."):
                    continue
                path = os.path.join(root, n)
                try:
                    if os.path.getmtime(path) >= started_at - 5:
                        job_files.append(path)
                except OSError:
                    pass
        if not final and job_files:
            final = max(job_files, key=lambda p: os.path.getsize(p))

        if not final:
            detail = " | ".join([l for l in tail_lines[-3:] if l]) or "no output"
            hint = ""
            if not has_ffmpeg() and not EMBEDDED:
                hint = " (ffmpeg missing - run: pkg install ffmpeg)"
            update(status="error",
                   error="yt-dlp produced no file%s. Last output: %s" % (hint, detail))
            return
        # If yt-dlp left several media files behind, the merge failed and the
        # app would otherwise receive only half of the track.
        media = [p for p in job_files
                 if os.path.splitext(p)[1].lower() in MEDIA_EXTS]
        if len(media) > 1:
            update(status="error",
                   error="yt-dlp produced %d separate files (%s) - the merge "
                         "failed. ffmpeg is required: pkg install ffmpeg"
                         % (len(media),
                            ", ".join(sorted(os.path.basename(p) for p in media))))
            return

        # Never hand over something that is not media. An older version of
        # this script fell back to "any recently written file" and once
        # returned its own source code, which the app then saved as
        # "Artist - Title.py.mp3".
        if os.path.splitext(final)[1].lower() not in MEDIA_EXTS:
            update(status="error",
                   error="yt-dlp produced %s, which is not a media file - "
                         "refusing to hand it over"
                         % os.path.basename(final))
            return

        # The preset is a promise: "mp3" has to be an mp3.
        expected = EXPECTED_EXTS.get(preset)
        actual_ext = os.path.splitext(final)[1].lower()
        extra_note = ""
        if expected and actual_ext not in expected:
            if (preset == "audio_mp3" and actual_ext == ".m4a"
                    and not has_ffmpeg()):
                # The phone has an mp3 encoder of its own, so the sound is
                # handed over as it is. Refusing it here would leave the
                # user with nothing at all.
                extra_note = ("this bridge has no ffmpeg, so the sound is "
                              "handed over as m4a - the app turns it into an "
                              "mp3 itself")
                print("[bridge] job %s: %s" % (job_id, extra_note), flush=True)
            else:
                wanted = ", ".join(sorted(e.lstrip(".") for e in expected))
                update(status="error",
                       error="the %s conversion failed - what was produced is a %s "
                             "file. ffmpeg is required: pkg install ffmpeg"
                             % (wanted, actual_ext.lstrip(".") or "unknown"))
                return

        stem = "%s - %s" % (artist, title) if artist else (title or video_id)
        target = os.path.join(WORKDIR, "%s%s" % (sanitize(stem), os.path.splitext(final)[1]))
        if os.path.abspath(final) != os.path.abspath(target):
            shutil.move(final, target)

        if save == "bridge":
            # The song is to live on this machine, not on the phone. It is
            # copied into the library folder and the working copy is left
            # where it is, so the phone can still fetch it if the user
            # changes their mind halfway through.
            try:
                os.makedirs(LIBRARY_DIR, exist_ok=True)
                library = os.path.join(LIBRARY_DIR, os.path.basename(target))
                if os.path.abspath(library) != os.path.abspath(target):
                    shutil.copy2(target, library)
                print("[bridge] job %s: kept on this machine at %s"
                      % (job_id, library), flush=True)
                update(status="done", percent=100, title=title, artist=artist,
                       has_file=True, file=target, video_id=video_id,
                       files=[os.path.basename(target)],
                       quality=preset, note=extra_note, thumbnail=thumbnail,
                       saved_at=library)
                return
            except OSError as exc:
                extra_note = ("the song could not be put in %s: %s"
                              % (LIBRARY_DIR, exc))

        update(status="done", percent=100, title=title, artist=artist,
               has_file=True, file=target, video_id=video_id,
               files=[os.path.basename(target)],
               quality=preset, note=extra_note, thumbnail=thumbnail)
    except Exception as exc:  # noqa: BLE001
        update(status="error", error=str(exc))


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #
class BridgeServer(ThreadingHTTPServer):
    """Threading server that stays quiet when a client hangs up."""

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # The app polls /job/ every 1.5s, so logging every poll floods the
        # terminal. Job state changes are logged explicitly instead.
        if getattr(self, "path", "").startswith("/job/"):
            return
        print("[bridge] " + (fmt % args), flush=True)

    def _auth_ok(self):
        if not TOKEN:
            # No key at all means the bridge is open. That is only
            # sensible on a network the user controls, so when the
            # bridge has been made reachable from outside, an open
            # bridge is refused rather than allowed.
            return not REQUIRE_TOKEN
        given = self.headers.get("X-Auth-Token", "")
        # Compared in constant time, so the time an answer takes does
        # not say how much of the key was right.
        return hmac.compare_digest(given, TOKEN)

    def _json(self, code, payload):
        try:
            body = json.dumps(payload).encode("utf-8")
        except Exception as exc:  # noqa: BLE001
            # A value that cannot be written down must not take the
            # connection down with it. Say what went wrong instead, so the
            # app can show a reason rather than a bridge that went quiet.
            body = json.dumps({
                "error": "the bridge could not write down its answer",
                "detail": "%s: %s" % (type(exc).__name__, exc),
            }).encode("utf-8")
            code = 500
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The client hung up (it cancelled the request, or the app was
            # replaced). That is normal, not an error worth a stack trace.
            self.close_connection = True

    def do_GET(self):
        """Never lets a mistake take the connection down with it.

        A handler that raises used to close the connection with nothing on
        it, and the app could only say "unreachable" - which sends the
        user looking at the network instead of at the bridge. Now the
        bridge says what went wrong.
        """
        try:
            self._do_GET()
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": "the bridge failed",
                             "detail": "%s: %s" % (type(exc).__name__, exc)})

    def do_POST(self):
        """Never lets a mistake take the connection down with it."""
        try:
            self._do_POST()
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": "the bridge failed",
                             "detail": "%s: %s" % (type(exc).__name__, exc)})

    def _do_GET(self):
        path = urlparse(self.path).path
        # The pairing answers are open on purpose. The phone does not have
        # the key yet - that is the whole point of them. What they need is
        # the code, which the bridge is showing on its own screen.
        if path in ("/pair/info", "/pair/claim"):
            self._do_pair_GET(path)
            return
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"})
            return

        if path == "/health":
            ver = yt_dlp_version() or "unknown"
            # "yt_dlp_outdated" lets the app say "your yt-dlp is too old"
            # instead of leaving the user guessing at a 403.
            self._json(200, {"ok": True, "yt_dlp": ver or "unknown",
                             "yt_dlp_outdated": yt_dlp_is_outdated(),
                             "yt_dlp_min": MIN_YTDLP,
                             "cookies": COOKIES.active,
                             "cookie_source": COOKIES.source,
                             "ffmpeg": has_ffmpeg(),
                             # Whether ffmpeg is needed at all. Inside the
                             # app it never is: the phone has its own
                             # encoder and joins video with MediaMuxer.
                             "ffmpeg_needed": not EMBEDDED,
                             "workdir": WORKDIR,
                             "version": BRIDGE_VERSION,
                             "update": UPDATE_STATE.get("state", "unknown"),
                             "update_remote": UPDATE_STATE.get("remote", "")})
            return

        if path == "/cookies":
            # What the bridge knows about cookies, so the app can say where
            # they came from instead of guessing.
            self._json(200, {"cookies": COOKIES.active,
                             "source": COOKIES.source})
            return

        if path.startswith("/job/"):
            job_id = path[len("/job/"):]
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id, {}))
            if not job:
                self._json(404, {"status": "unknown", "error": "no such job"})
                return
            job.setdefault("status", "queued")
            job.setdefault("percent", 0)
            state = job.get("status")
            if JOB_LOGGED.get(job_id) != state:
                JOB_LOGGED[job_id] = state
                # The reason matters. A log that only says "error" makes it
                # impossible to tell a 403 from a missing ffmpeg from a
                # missing file - and the log is the only thing the user can
                # read from the phone.
                detail = job.get("error") or job.get("note") or ""
                if detail:
                    detail = str(detail).replace("\n", " ")[:400]
                    print("[bridge] job %s -> %s: %s" % (job_id, state, detail),
                          flush=True)
                else:
                    print("[bridge] job %s -> %s" % (job_id, state), flush=True)
            self._json(200, job)
            return

        if path.startswith("/file/"):
            job_id = path[len("/file/"):]
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id, {}))
            # A video that was downloaded inside the app has two pieces:
            # the picture and the sound. The phone asks for them one at a
            # time and joins them itself.
            params = parse_qs(urlparse(self.path).query)
            part = (params.get("part") or [""])[0].strip().lower()
            if part == "video":
                target = job.get("file_video")
            elif part == "audio":
                target = job.get("file_audio")
            else:
                target = job.get("file")
            if not target or not os.path.exists(target):
                self._json(404, {"error": "file not ready"})
                return
            self._serve_file(target)
            return

        if path == "/find":
            # Rescue endpoint. The job record lives in memory, so it is gone
            # whenever the bridge restarts - and the app then gets a 404 for a
            # download that actually succeeded. The finished file is still on
            # disk, so it can be found by name.
            params = parse_qs(urlparse(self.path).query)
            name = (params.get("name") or [""])[0]
            part = (params.get("part") or [""])[0].strip().lower()
            found = find_finished_file(name, part=part)
            if not found:
                self._json(404, {"error": "no finished file found"})
                return
            self._serve_file(found)
            return

        self._json(404, {"error": "not found"})

    def _serve_file(self, target):
        """Sends a finished file to the app."""
        size = os.path.getsize(target)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition",
                         'attachment; filename="%s"' % os.path.basename(target))
        self.send_header("X-File-Name", os.path.basename(target))
        self.end_headers()
        try:
            with open(target, "rb") as fh:
                while True:
                    chunk = fh.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _do_pair_GET(self, path):
        """The two answers a phone needs before it has the key."""
        if REQUIRE_TOKEN and not self._auth_ok():
            self._json(401, {"error": "unauthorized"})
            return
        if path == "/pair/info":
            # With a public address the phone is told where the bridge
            # really is, not what it calls itself on this network.
            host, port = lan_address(), self.server.server_address[1]
            scheme, path_prefix = "http", ""
            if PUBLIC_URL:
                scheme, url_host, path_prefix = split_public_url(PUBLIC_URL)
                port = public_port(scheme, url_host, port)
                host = url_host.split(":")[0]
            self._json(200, {
                "h": pair_code_hash(PAIR_CODE) if PAIR_CODE else "",
                "host": host,
                "port": port,
                "scheme": scheme,
                "path": path_prefix,
                "version": BRIDGE_VERSION,
            })
            return

        params = parse_qs(urlparse(self.path).query)
        given = (params.get("code") or [""])[0]
        try:
            right = bool(PAIR_CODE) and normalize_pair_code(given) == PAIR_CODE
        except ValueError:
            right = False
        if not right:
            self._json(403, {"error": "that code is not right"})
            return
        host, port = lan_address(), self.server.server_address[1]
        # The scheme and the path prefix are set here as well as for
        # /pair/info. They used to be set only when there was a public
        # address, so on a plain network they were never set at all and
        # claiming a code failed with "the bridge failed" - the phone
        # could be told the bridge was there and could see its code, but
        # it could never exchange the code for the key.
        scheme, path_prefix = "http", ""
        if PUBLIC_URL:
            scheme, url_host, path_prefix = split_public_url(PUBLIC_URL)
            port = public_port(scheme, url_host, port)
            host = url_host.split(":")[0]
        self._json(200, {"token": TOKEN,
                         "host": host,
                         "port": port,
                         "scheme": scheme,
                         "path": path_prefix})

    def _do_POST(self):
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        if path == "/update":
            # The bridge updates itself and restarts. The answer goes out
            # before the restart, so the app always gets a reply.
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                data = {}
            code = data.get("code") if isinstance(data, dict) else None
            state = dict(UPDATE_STATE)
            if state.get("state") != "updating":
                state = self_update(code=code)
            self._json(200, state)
            return
        if path == "/cookies":
            # The app hands the bridge a cookie jar here. The person using
            # the app chose that file, so the bridge uses it from now on.
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            if data.get("clear"):
                set_cookie_jar("")
                self._json(200, {"ok": True, "cookies": COOKIES.active,
                                 "source": COOKIES.source})
                return
            text = data.get("cookies") or ""
            if not isinstance(text, str) or not text.strip():
                self._json(400, {"error": "no cookies were sent"})
                return
            if "Netscape HTTP Cookie File" not in text:
                # A jar that is not a jar would fail every download in a way
                # that is much harder to explain than this.
                self._json(400, {"error": "that is not a cookies.txt file"})
                return
            try:
                set_cookie_jar(text)
            except OSError as exc:
                self._json(500, {"error": "the cookie jar could not be saved: %s" % exc})
                return
            self._json(200, {"ok": True, "cookies": COOKIES.active,
                             "source": COOKIES.source})
            return

        if path != "/search":
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:
            self._json(400, {"error": "bad json: %s" % exc})
            return

        query = (data.get("query") or "").strip()
        title = (data.get("title") or "").strip()
        artist = (data.get("artist") or "").strip()
        if not query:
            self._json(400, {"error": "query is required"})
            return

        # Where the song is to end up: on the phone, or on this bridge.
        save = (data.get("save") or "local").strip().lower()
        if save not in ("local", "bridge"):
            save = "local"

        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "queued", "percent": 0, "query": query,
                            "save": save}

        thread = threading.Thread(
            target=run_job,
            args=(job_id, query,
                  data.get("preset", "audio_m4a"),
                  data.get("video_quality", 1080),
                  bool(data.get("embed_metadata", True)),
                  bool(data.get("embed_thumbnail", True)),
                  title, artist, data.get("expected_duration") or 0),
            kwargs={"save": save},
            daemon=True,
        )
        thread.start()

        self._json(200, {"id": job_id, "status": "queued"})


def make_server(host="127.0.0.1", port=8765, workdir="", embedded=False,
                token="", po_token="", clients="", cookies="",
                library_dir="", public_url=""):
    """Puts the bridge together and returns the server, ready to serve.

    The app calls this instead of main(), because an app cannot start a
    program - it runs the bridge inside its own Python.
    """
    global TOKEN, WORKDIR, COOKIES, PO_TOKEN, CLIENTS_OVERRIDE, EMBEDDED
    global LIBRARY_DIR, PUBLIC_URL, REQUIRE_TOKEN

    EMBEDDED = bool(embedded)
    PUBLIC_URL = str(public_url or os.environ.get("YTBRIDGE_PUBLIC_URL", "")).strip()
    # A bridge that is reachable from outside has to know the key from
    # the first request. An open bridge on the internet is not a
    # bridge anybody should want.
    REQUIRE_TOKEN = bool(PUBLIC_URL) or os.environ.get(
        "YTBRIDGE_REQUIRE_TOKEN", "").strip() not in ("", "0", "false", "no")
    TOKEN = token or os.environ.get("YTBRIDGE_TOKEN", "")
    LIBRARY_DIR = os.path.expanduser(library_dir or os.environ.get(
        "YTBRIDGE_LIBRARY_DIR",
        os.path.join(os.path.expanduser("~"), "Music", "AutoSongs")))
    WORKDIR = os.path.expanduser(workdir or os.environ.get(
        "YTBRIDGE_WORKDIR", default_workdir()))
    PO_TOKEN = (po_token or os.environ.get("YTBRIDGE_PO_TOKEN", "")).strip()
    CLIENTS_OVERRIDE = (clients or os.environ.get("YTBRIDGE_CLIENTS", "")).strip()
    # A jar the person named wins; otherwise the bridge looks for one.
    wanted = cookies or os.environ.get("YTBRIDGE_COOKIES", "")
    path, source = find_cookie_source(wanted)
    COOKIES = CookieSource(path, source)
    os.makedirs(WORKDIR, exist_ok=True)

    server = BridgeServer((host, int(port)), Handler)
    print("[bridge] yt-dlp bridge listening on %s:%d" % (host, port), flush=True)
    if PUBLIC_URL:
        print("[bridge] reachable from outside at: %s" % PUBLIC_URL, flush=True)
        if not TOKEN:
            print("[bridge] WARNING: no key is set. This bridge is open to "
                  "anyone who can reach it.", flush=True)

    print("[bridge] version: %s" % BRIDGE_VERSION, flush=True)
    print("[bridge] workdir: %s" % WORKDIR, flush=True)
    print("[bridge] cookies: %s" % (COOKIES.path or "none"), flush=True)
    if COOKIES.source:
        print("[bridge] cookies come from: %s" % COOKIES.source, flush=True)
    if EMBEDDED:
        print("[bridge] running inside the app", flush=True)
    return server


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default=os.environ.get("YTBRIDGE_TOKEN", ""))
    ap.add_argument("--library-dir", default=os.environ.get("YTBRIDGE_LIBRARY_DIR", ""),
                    help="where songs are kept when the app asks the bridge to "
                         "save them here instead of on the phone")
    ap.add_argument("--pair", action="store_true",
                    help="make a key, and show the code the phone needs to be "
                         "paired with this bridge")
    ap.add_argument("--workdir",
                    default=os.environ.get("YTBRIDGE_WORKDIR", default_workdir()))
    ap.add_argument("--po-token", default=os.environ.get("YTBRIDGE_PO_TOKEN", ""),
                    help="a YouTube PO token (youtube:po_token=...) - needed since "
                         "YouTube started refusing format URLs without one")
    ap.add_argument("--clients", default=os.environ.get("YTBRIDGE_CLIENTS", ""),
                    help="the yt-dlp player client to use, e.g. android_vr")
    ap.add_argument("--cookies", default=os.environ.get("YTBRIDGE_COOKIES", ""),
                    help="path to a cookies.txt file (helps with YouTube bot checks)")
    ap.add_argument("--public-url", default=os.environ.get("YTBRIDGE_PUBLIC_URL", ""),
                    help="the address this bridge is reachable at from "
                         "outside, e.g. https://bridge.example.com. The "
                         "pairing code carries it, so a phone on another "
                         "network can be pointed at it.")
    ap.add_argument("--tunnel", action="store_true",
                    help="open a tunnel to the internet with cloudflared, so "
                         "a phone that is not on this network can reach this "
                         "bridge. It asks the pairing service for a fixed "
                         "address once, so the address survives a restart.")
    ap.add_argument("--tunnel-reset", action="store_true",
                    help="forget this install's fixed address and ask for a "
                         "new one on the next start")
    args = ap.parse_args()

    # With --pair the bridge makes itself a key and shows the code that
    # carries it. The same key is the auth token, so pairing is all the
    # setup there is.
    global PAIR_CODE
    token = args.token
    if args.pair:
        PAIR_CODE = make_pair_code()
        if not token:
            token = load_or_make_secret()

    # The tunnel is opened first, so the address it hands out can go
    # into the pairing code. The bridge itself is listening on this
    # machine either way; the tunnel is what the internet talks to.
    if args.tunnel_reset:
        if forget_tunnel():
            print("[bridge] the fixed address has been forgotten", flush=True)
        else:
            print("[bridge] there was no fixed address to forget", flush=True)

    public_url = str(args.public_url or "").strip()
    tunnel_proc = None
    if args.tunnel:
        try:
            tunnel_proc, public_url = start_tunnel(args.port)
        except RuntimeError as exc:
            print("[bridge] %s" % exc, flush=True)
            return 1

    server = make_server(args.host, args.port, args.workdir, embedded=False,
                         token=token, po_token=args.po_token,
                         clients=args.clients, cookies=args.cookies,
                         library_dir=args.library_dir,
                         public_url=public_url)

    if args.pair:
        print_pairing_banner(lan_address(), args.port, token,
                             public_url=public_url)
        if public_url:
            # The phone types these eight characters; the service says where
            # this bridge is, and only while this bridge is beating.
            register_pair_code(PAIR_CODE, public_url, token)
        else:
            start_pair_responder(args.port)

    threading.Thread(target=update_watcher, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # The tunnel is a child process. It stops with the bridge, so a
        # closed bridge does not leave a hole open behind it.
        stop_pairing()
        if tunnel_proc is not None:
            try:
                tunnel_proc.terminate()
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main() or 0)
