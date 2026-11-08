#!/bin/sh
# AutoSongs bridge - one file, nothing to install.
#
# Run it:
#
#     sh autosongs-bridge.sh
#
# It prints a code. Type that code into AutoSongs on your phone, in
# Settings - The bridge on another machine, and the two are paired.
#
# It needs python 3, and it puts yt-dlp in place for itself if it is not
# there already.

set -u

DIR="${HOME}/.autosongs"
BRIDGE="$DIR/ytbridge.py"
LOG="$DIR/bridge.log"

# A cookie jar next to this launcher is used for the downloads. YouTube
# sometimes answers with "Sign in to confirm you're not a bot" instead of
# the video, and a jar - the file a signed-in browser can export - is what
# gets past it. The bridge looks for one on its own, but saying so here
# means the jar the user put here is the one that is used.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -z "${YTBRIDGE_COOKIES:-}" ] && [ -f "$HERE/cookies.txt" ]; then
    YTBRIDGE_COOKIES="$HERE/cookies.txt"
    export YTBRIDGE_COOKIES
fi

# Where the bridge is fetched from. AutoSongs is published only at
# https://autosongs.example; the old throwaway host names are gone from this
# launcher so it can never pick up an old published copy.
HOSTS="
https://autosongs.example
"

say() { printf '%s\n' "$*"; }

# Pull the declared BRIDGE_VERSION out of a bridge file (empty if none).
bridge_ver() {
    "$PY" - "$1" <<'PYEOF'
import re, sys
try:
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
except OSError:
    sys.exit(0)
m = re.search(r'^BRIDGE_VERSION = "([^"]+)"', text, re.M)
if m:
    print(m.group(1))
PYEOF
}

# Exit 0 when version $1 is strictly newer than version $2.
ver_gt() {
    "$PY" - "$1" "$2" <<'PYEOF'
import sys
def tup(v):
    return tuple(int(p) if p.isdigit() else 0 for p in str(v).split("."))
sys.exit(0 if tup(sys.argv[1]) > tup(sys.argv[2]) else 1)
PYEOF
}

# A candidate replaces the installed bridge only when nothing is installed,
# or it declares a newer version. Never downgrade; never replace a valid
# local copy with a file that declares no version.
bridge_is_newer() {
    [ -s "$BRIDGE" ] || return 0
    rv=$(bridge_ver "$1")
    [ -n "$rv" ] || return 1
    ver_gt "$rv" "$(bridge_ver "$BRIDGE")"
}

# ---------------------------------------------------------------- python
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' 2>/dev/null; then
            PY="$candidate"
            break
        fi
    fi
done
if [ -z "$PY" ]; then
    say "The AutoSongs bridge needs python 3."
    say "  Debian or Ubuntu:   sudo apt install python3 python3-pip"
    say "  Fedora:             sudo dnf install python3"
    say "  Arch:               sudo pacman -S python"
    exit 1
fi

mkdir -p "$DIR" || exit 1

# ---------------------------------------------------------------- yt-dlp
if ! "$PY" -c 'import yt_dlp' >/dev/null 2>&1 && ! command -v yt-dlp >/dev/null 2>&1; then
    say "Putting yt-dlp in place..."
    "$PY" -m pip install --user --upgrade yt-dlp >>"$LOG" 2>&1
    if ! "$PY" -c 'import yt_dlp' >/dev/null 2>&1; then
        say "yt-dlp would not install. The details are in $LOG"
        exit 1
    fi
fi

# ---------------------------------------------------------------- bridge
fetch_bridge() {
    for host in $HOSTS; do
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL --max-time 90 "$host/ytbridge.py" -o "$BRIDGE.new" 2>/dev/null || continue
        elif command -v wget >/dev/null 2>&1; then
            wget -q -T 90 "$host/ytbridge.py" -O "$BRIDGE.new" 2>/dev/null || continue
        else
            return 1
        fi
        # Make sure it is the bridge and not a page that says not found.
        if [ -s "$BRIDGE.new" ] && grep -q "def make_server" "$BRIDGE.new"; then
            if bridge_is_newer "$BRIDGE.new"; then
                mv "$BRIDGE.new" "$BRIDGE"
            else
                say "Keeping the copy of the bridge that is already here."
            fi
            rm -f "$BRIDGE.new"
            return 0
        fi
        rm -f "$BRIDGE.new"
    done
    return 1
}

if ! fetch_bridge; then
    if [ ! -s "$BRIDGE" ]; then
        say "The bridge could not be fetched, and there is no copy here."
        say "Check the network and try again."
        exit 1
    fi
    say "Using the copy of the bridge that is already here."
fi

exec "$PY" "$BRIDGE" --pair "$@"
