#!/data/data/com.termux/files/usr/bin/bash
# AutoSongs - one-shot setup for Termux on the phone.
#
# IMPORTANT: run it with `bash`, not `./`:
#     bash setup-termux.sh
# Android mounts /sdcard with noexec, so scripts downloaded into the
# Downloads folder cannot be executed directly.
#
# The script installs yt-dlp + ffmpeg, fetches the bridge server (if it is not
# next to this file) and starts the bridge.
#
# Layout (important):
#   ~/autosongs/bin/        the bridge program and helper scripts
#   ~/autosongs/downloads/  finished songs - nothing else lives here
#
# The bridge program used to sit in the same folder as the downloads, which
# meant a fallback that looked for "any recent file" could pick up the bridge
# source code and save it as a song. Keeping them apart makes that
# impossible.
#
set -euo pipefail

# The version of THIS script.
#
# The installer picks the address to download from by this number, and the
# setup script picks the newest bridge by the bridge's number. They are
# separate: an address can carry the newest bridge and an old setup script,
# and the setup script is the one that actually runs on the phone.
SETUP_VERSION="1.3.20"

# A safe place for temporary files.
#
# Termux does NOT have /tmp by default and "$TMPDIR" is usually unset, so
# "mktemp /tmp/..." fails there - and with "set -e" that kills the script
# before it does anything at all.
AUTOSONGS_TMP="${TMPDIR:-}"
if [ -z "$AUTOSONGS_TMP" ] || [ ! -d "$AUTOSONGS_TMP" ]; then
    AUTOSONGS_TMP="$HOME/autosongs/tmp"
    mkdir -p "$AUTOSONGS_TMP"
fi

PORT="${YTBRIDGE_PORT:-8765}"
TOKEN="${YTBRIDGE_TOKEN:-}"
HOME_DIR="$HOME/autosongs"
BIN_DIR="$HOME_DIR/bin"
WORKDIR="$HOME_DIR/downloads"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_SRC="$HERE/ytbridge.py"

# Every publish of AutoSongs gets a new web address. This script does not
# point at one fixed address: it asks all of them which one carries the
# newest bridge and uses that one.
BRIDGE_HOSTS="${YTBRIDGE_HOSTS:-https://autosongs.example}"

pick_newest_bridge() {
    # Prints the address that has the newest bridge, or nothing.
    local best_host="" best_ver="" tmp ver newest
    for host in $BRIDGE_HOSTS; do
        tmp="$(mktemp "${AUTOSONGS_TMP}/autosongs-bridge.XXXXXX")"
        if curl -fsSL --max-time 20 -o "$tmp" "$host/ytbridge.py" 2>/dev/null; then
            ver="$(sed -n 's/^BRIDGE_VERSION = "\(.*\)"$/\1/p' "$tmp" | head -1)"
            if [ -n "$ver" ]; then
                if [ -z "$best_ver" ]; then
                    best_ver="$ver"; best_host="$host"
                else
                    newest="$(printf '%s\n%s\n' "$best_ver" "$ver" | sort -V | tail -1)"
                    [ "$newest" = "$ver" ] && { best_ver="$ver"; best_host="$host"; }
                fi
            fi
        fi
        rm -f "$tmp"
    done
printf '%s' "$best_host"
}

pick_newest_setup() {
    # Prints the address that carries the newest SETUP SCRIPT, or nothing.
    #
    # The setup script is what runs on the phone, so this - and not the
    # bridge version - is what decides which address is used.
    local best_host="" best_ver="" tmp ver newest
    for host in $BRIDGE_HOSTS; do
        tmp="$(mktemp "${AUTOSONGS_TMP}/autosongs-setup.XXXXXX")"
        if curl -fsSL --max-time 20 -o "$tmp" "$host/setup-termux.sh" 2>/dev/null; then
            ver="$(sed -n 's/^SETUP_VERSION="\(.*\)"$/\1/p' "$tmp" | head -1)"
            if [ -n "$ver" ]; then
                if [ -z "$best_ver" ]; then
                    best_ver="$ver"; best_host="$host"
                else
                    newest="$(printf '%s\n%s\n' "$best_ver" "$ver" | sort -V | tail -1)"
                    [ "$newest" = "$ver" ] && { best_ver="$ver"; best_host="$host"; }
                fi
            fi
        fi
        rm -f "$tmp"
    done
    printf '%s' "$best_host"
}

# Which addresses carry the newest bridge and the newest setup script. This
# has to happen before anything else, because the handover below uses it.
NEWEST_HOST="$(pick_newest_bridge)"
NEWEST_SETUP_HOST="$(pick_newest_setup)"

# If a newer setup script is published, hand over to it. A stale copy of
# this script must never continue on the phone.
if [ -n "$NEWEST_SETUP_HOST" ]; then
    REMOTE_SETUP_VER="$(curl -fsSL --max-time 20 "$NEWEST_SETUP_HOST/setup-termux.sh" 2>/dev/null \
        | sed -n 's/^SETUP_VERSION="\(.*\)"$/\1/p' | head -1)"
    if [ -n "$REMOTE_SETUP_VER" ] && [ "$REMOTE_SETUP_VER" != "$SETUP_VERSION" ]; then
        NEWEST_SETUP="$(printf '%s\n%s\n' "$SETUP_VERSION" "$REMOTE_SETUP_VER" | sort -V | tail -1)"
        if [ "$NEWEST_SETUP" = "$REMOTE_SETUP_VER" ]; then
            echo "    a newer setup script is published ($REMOTE_SETUP_VER, this one is $SETUP_VERSION)"
            TMP_SETUP="$(mktemp "${AUTOSONGS_TMP}/autosongs-setup.XXXXXX")"
            if curl -fsSL --max-time 30 -o "$TMP_SETUP" "$NEWEST_SETUP_HOST/setup-termux.sh"; then
                chmod +x "$TMP_SETUP"
                export YTBRIDGE_HOSTS="$BRIDGE_HOSTS"
                exec bash "$TMP_SETUP"
            fi
            rm -f "$TMP_SETUP"
        fi
    fi
fi

echo "==> installing packages"
pkg update -ypkg install -y python ffmpeg unzip curl

echo "==> installing yt-dlp"
# ALWAYS upgrade, not only when it is missing. YouTube changes often enough
# that an old yt-dlp stops being able to download anything - it then fails
# with "HTTP Error 403: Forbidden" because YouTube wants a proof of origin
# token. An outdated yt-dlp is the most common reason a download does not
# work at all.
# Termux marks its python as externally managed, so the first attempt may
# need --break-system-packages.
python -m pip install --upgrade pip -q --break-system-packages 2>/dev/null || \
    python -m pip install --upgrade pip -q || true
python -m pip install -U -q yt-dlp --break-system-packages 2>/dev/null || \
    python -m pip install -U -q yt-dlp || \
    pip install -U -q yt-dlp --break-system-packages || \
    pip install -U -q yt-dlp || true
export PATH="$HOME/.local/bin:$PATH"
# Say it plainly when yt-dlp is still too old. An old yt-dlp cannot download
# from YouTube at all, and the symptom ("HTTP Error 403: Forbidden") looks
# like a network problem rather than a version problem.
YTDLP_RAW="$(yt-dlp --version 2>/dev/null || echo unknown)"
# The "|| true" matters. With "set -euo pipefail" a grep that matches
# nothing returns 1, and that aborted the whole setup script BEFORE it
# started the bridge - so a phone without yt-dlp ended up with nothing
# running at all. A missing yt-dlp must never stop the setup.
YTDLP_NUM="$(printf '%s' "$YTDLP_RAW" \
    | tr -c '0-9.' '\n' \
    | grep -m1 -E '^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$' || true)"
if [ -n "$YTDLP_NUM" ]; then
    NEWEST="$(printf '%s\n%s\n' "2026.08.19" "$YTDLP_NUM" | sort -V | tail -1)"
    if [ "$NEWEST" = "2026.08.19" ] && [ "$YTDLP_NUM" != "2026.08.19" ]; then
        echo "    !! yt-dlp is still $YTDLP_NUM - it is too old for YouTube"
        echo "       downloads will fail with 'HTTP Error 403: Forbidden'"
        echo "       try:  python -m pip install -U yt-dlp --break-system-packages"
    fi
fi
echo "    yt-dlp $YTDLP_RAW"

echo "==> preparing folders"
mkdir -p "$BIN_DIR" "$WORKDIR"

# An old bridge used to hand over its own source code as if it were a song.
# Those leftovers are .py files sitting in the download folder - remove them
# so they can never be served again.
if [ -d "$WORKDIR" ]; then
    STRAY="$(find "$WORKDIR" -maxdepth 2 -name '*.py' -type f 2>/dev/null | head -20)"
    if [ -n "$STRAY" ]; then
        echo "    removing leftover .py files (they were never songs):"
        echo "$STRAY" | sed 's/^/      /'
        find "$WORKDIR" -maxdepth 2 -name '*.py' -type f -delete 2>/dev/null || true
    fi
fi

# The bridge that sits next to this script is used when it is there. If it is
# not - or if a newer one is published - the newest one is fetched.
LOCAL_VER=""
[ -f "$BRIDGE_SRC" ] && \
    LOCAL_VER="$(sed -n 's/^BRIDGE_VERSION = "\(.*\)"$/\1/p' "$BRIDGE_SRC" | head -1)"

# The copy that is already installed is a third candidate. It can be newer
# than the one next to this script, and it is the one that is running - so it
# must never be replaced by an older copy.
INSTALLED_VER=""
[ -f "$BIN_DIR/ytbridge.py" ] && \
    INSTALLED_VER="$(sed -n 's/^BRIDGE_VERSION = "\(.*\)"$/\1/p' "$BIN_DIR/ytbridge.py" | head -1)"

# The newest version that is already here.
HAVE_VER=""
for v in "$LOCAL_VER" "$INSTALLED_VER"; do
    [ -n "$v" ] || continue
    if [ -z "$HAVE_VER" ] || \
       [ "$(printf '%s\n%s\n' "$HAVE_VER" "$v" | sort -V | tail -1)" = "$v" ]; then
        HAVE_VER="$v"
    fi
done

NEWEST_VER=""
if [ -n "$NEWEST_HOST" ]; then
    NEWEST_VER="$(curl -fsSL --max-time 20 "$NEWEST_HOST/ytbridge.py" 2>/dev/null \
        | sed -n 's/^BRIDGE_VERSION = "\(.*\)"$/\1/p' | head -1)"
fi

# True when version $1 is strictly newer than version $2.
is_newer() {
    [ -n "$1" ] || return 1
    [ -n "$2" ] || return 0
    [ "$1" != "$2" ] && \
    [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | tail -1)" = "$1" ]
}

NEWEST=""
if is_newer "$NEWEST_VER" "$HAVE_VER"; then
    echo "    a newer bridge is published ($NEWEST_VER, this one is ${HAVE_VER:-none})"
    if curl -fsSL --max-time 30 -o "$BIN_DIR/ytbridge.py.new" "$NEWEST_HOST/ytbridge.py"; then
        mv "$BIN_DIR/ytbridge.py.new" "$BIN_DIR/ytbridge.py"
        NEWEST="$BIN_DIR/ytbridge.py"
        BRIDGE_SRC="$BIN_DIR/ytbridge.py"
    else
        rm -f "$BIN_DIR/ytbridge.py.new"
        echo "!! could not download the newer bridge - keeping ${HAVE_VER:-the copy that is here}"
    fi
elif [ ! -f "$BRIDGE_SRC" ] && [ ! -f "$BIN_DIR/ytbridge.py" ]; then
    echo "    ytbridge.py not found next to this script, downloading..."
    if [ -n "$NEWEST_HOST" ] && \
       curl -fsSL --max-time 30 -o "$BIN_DIR/ytbridge.py" "$NEWEST_HOST/ytbridge.py"; then
        echo "    downloaded ytbridge.py"
        BRIDGE_SRC="$BIN_DIR/ytbridge.py"
    else
        echo "!! could not download ytbridge.py - copy it manually to $BIN_DIR"
        exit 1
    fi
elif [ -n "$HAVE_VER" ]; then
    echo "    keeping the bridge that is already here ($HAVE_VER)"
fi

# The file that should be installed: the published copy when it was fetched,
# otherwise the installed copy when it is the newer one, otherwise the copy
# that sits next to this script.
if [ -z "$NEWEST" ]; then
    if [ -n "$INSTALLED_VER" ] && ! is_newer "$LOCAL_VER" "$INSTALLED_VER"; then
        BRIDGE_SRC="$BIN_DIR/ytbridge.py"
    fi
fi

if [ "$BRIDGE_SRC" != "$BIN_DIR/ytbridge.py" ]; then
    cp "$BRIDGE_SRC" "$BIN_DIR/ytbridge.py"
fi
chmod +x "$BIN_DIR/ytbridge.py"
echo "    bridge: $BIN_DIR/ytbridge.py"

# The stop helper lives next to this script, or is fetched from the same place.
if [ ! -f "$HERE/bridge-stop.sh" ]; then
    if [ -n "$NEWEST_HOST" ]; then
        curl -fsSL -o "$BIN_DIR/bridge-stop.sh" "$NEWEST_HOST/bridge-stop.sh" \
            && chmod +x "$BIN_DIR/bridge-stop.sh" || true
    fi
fi
STOP_SH="$HERE/bridge-stop.sh"
[ -f "$STOP_SH" ] || STOP_SH="$BIN_DIR/bridge-stop.sh"

# A cookies file makes YouTube treat the phone like a signed-in browser,
# which is the reliable way past a 403. Use one if it is lying around.
if [ -z "${YTBRIDGE_COOKIES:-}" ] && [ -f "$HOME_DIR/cookies.txt" ]; then
    YTBRIDGE_COOKIES="$HOME_DIR/cookies.txt"
    export YTBRIDGE_COOKIES
fi

COOKIES_ARG=""
if [ -n "${YTBRIDGE_COOKIES:-}" ]; then
    COOKIES_ARG="--cookies $YTBRIDGE_COOKIES"
    echo "    using cookies: $YTBRIDGE_COOKIES"
fi

EXPECT_VER="$(sed -n 's/^BRIDGE_VERSION = "\(.*\)"$/\1/p' "$BIN_DIR/ytbridge.py" | head -1)"

echo "==> checking the bridge on port $PORT"
HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" || true)"
GOT_VER="$(printf '%s' "$HEALTH" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')"
GOT_DIR="$(printf '%s' "$HEALTH" | sed -n 's/.*"workdir": *"\([^"]*\)".*/\1/p')"

# If the running bridge is already the right code and uses the right folder,
# leave it alone. Restarting it would throw away every job that is running -
# and the app then fails with "HTTP 404" for a download that worked.
if [ -n "$HEALTH" ] && [ "$GOT_VER" = "$EXPECT_VER" ] && [ "$GOT_DIR" = "$WORKDIR" ]; then
    echo "    bridge $GOT_VER is already running with the right workdir - keeping it"
else
    echo "==> stopping any running bridge"
    bash "$STOP_SH" "$PORT" || {
        echo "!! could not free port $PORT - stop the old bridge and retry"
        exit 1
    }

    if [ -n "$TOKEN" ]; then
        nohup python "$BIN_DIR/ytbridge.py" --port "$PORT" --token "$TOKEN" \
            $COOKIES_ARG --workdir "$WORKDIR" > "$HOME_DIR/bridge.log" 2>&1 &
    else
        nohup python "$BIN_DIR/ytbridge.py" --port "$PORT" \
            $COOKIES_ARG --workdir "$WORKDIR" > "$HOME_DIR/bridge.log" 2>&1 &
    fi
    echo $! > "$HOME_DIR/bridge.pid"
    sleep 3
fi

echo "==> health check"
HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" || true)"
if [ -z "$HEALTH" ]; then
    echo "!! bridge did not answer yet - check $HOME_DIR/bridge.log"
    tail -20 "$HOME_DIR/bridge.log" 2>/dev/null || true
    exit 1
fi
echo "$HEALTH"

# The bridge that answers must be the file we just installed, not a leftover
# process from an earlier run.
GOT_VER="$(printf '%s' "$HEALTH" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')"
if [ -n "$EXPECT_VER" ] && [ "$GOT_VER" != "$EXPECT_VER" ]; then
    echo "!! WRONG BRIDGE IS RUNNING (installed $EXPECT_VER, running ${GOT_VER:-unknown})"
    tail -20 "$HOME_DIR/bridge.log" 2>/dev/null || true
    exit 1
fi

cat <<EOF

AutoSongs bridge is running.

  Health check : curl http://127.0.0.1:$PORT/health
  Logs         : $HOME_DIR/bridge.log
  Downloads    : $WORKDIR
  PID file     : $HOME_DIR/bridge.pid

In the AutoSongs app:
  Settings -> Host: 127.0.0.1, Port: $PORT
EOF
