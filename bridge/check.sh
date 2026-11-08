#!/data/data/com.termux/files/usr/bin/bash
# AutoSongs — one-shot status check.
#
#     bash check.sh
#
# Prints what is actually running: the bridge, the files it saved, and the
# last lines of its log. Everything here is read-only - it changes nothing.
#
set -uo pipefail

PORT="${YTBRIDGE_PORT:-8765}"
TOKEN="${YTBRIDGE_TOKEN:-}"
HOME_DIR="$HOME/autosongs"
WORKDIR="$HOME_DIR/downloads"
HEALTH_URL="http://127.0.0.1:$PORT/health"

if [ -n "$TOKEN" ]; then
    HEALTH_URL="http://127.0.0.1:$PORT/health?token=$TOKEN"
fi

echo "=============================================="
echo " AutoSongs status"
echo "=============================================="

echo
echo "--- the bridge that is answering right now"
HEALTH="$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
if [ -z "$HEALTH" ]; then
    echo "  NO BRIDGE IS ANSWERING on port $PORT"
    echo "  start it with:  bash setup-termux.sh"
else
    echo "  $HEALTH"
fi

echo
echo "--- the bridge code installed on the phone"
BRIDGE="$HOME_DIR/bin/ytbridge.py"
[ -f "$BRIDGE" ] || BRIDGE="$HOME_DIR/ytbridge.py"
if [ -f "$BRIDGE" ]; then
    echo "  file    : $BRIDGE"
    echo "  version : $(sed -n 's/^BRIDGE_VERSION = "\(.*\)"$/\1/p' "$BRIDGE" | head -1)"
else
    echo "  no bridge file found (run: bash setup-termux.sh)"
fi

echo
echo "--- the tools on the phone"
YTDLP_RAW="$(yt-dlp --version 2>/dev/null || echo 'not installed')"
echo "  yt-dlp : $YTDLP_RAW"
echo "  ffmpeg : $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3 || echo 'not installed')"
if [ -f "$HOME_DIR/cookies.txt" ]; then
    echo "  cookies: $HOME_DIR/cookies.txt (in use - YouTube sees a signed-in browser)"
else
    echo "  cookies: none (a 403 means YouTube wants one)"
fi

# An outdated yt-dlp is THE cause of "HTTP Error 403: Forbidden". YouTube
# breaks yt-dlp every few months and an old one simply cannot download
# anything. This is the first thing to look at, so say it loudly.
YTDLP_OLD=""
# "|| true" so a version that does not match the pattern cannot fail the
# whole status check.
YTDLP_NUM="$(printf '%s' "$YTDLP_RAW" \
    | tr -c '0-9.' '\n' \
    | grep -m1 -E '^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$' || true)"
if [ -n "$YTDLP_NUM" ]; then
    NEWEST="$(printf '%s\n%s\n' "2026.08.19" "$YTDLP_NUM" | sort -V | tail -1)"
    [ "$NEWEST" = "2026.08.19" ] && [ "$YTDLP_NUM" != "2026.08.19" ] && YTDLP_OLD=1
fi
if [ -n "$YTDLP_OLD" ]; then
    echo
    echo "  !! yt-dlp is TOO OLD ($YTDLP_NUM, needs 2026.08.19 or newer)"
    echo "     This is the usual cause of 'HTTP Error 403: Forbidden'."
    echo "     Fix it with:  bash setup-termux.sh"
fi

echo
echo "--- what is running right now"
if command -v pgrep >/dev/null 2>&1; then
    pgrep -af ytbridge.py 2>/dev/null || echo "  no ytbridge.py process"
else
    ps -A 2>/dev/null | grep -i ytbridge || echo "  no ytbridge.py process"
fi

echo
echo "--- finished downloads (a real song is megabytes, not kilobytes)"
if [ -d "$WORKDIR" ]; then
    ls -l "$WORKDIR" 2>/dev/null | tail -15 || true
    TOTAL="$(find "$WORKDIR" -type f 2>/dev/null | wc -l)"
    echo "  $TOTAL file(s) in $WORKDIR"
else
    echo "  $WORKDIR does not exist yet"
fi

echo
echo "--- saved in the phone's music folder"
ls -l "/storage/emulated/0/Music/AutoSongs" 2>/dev/null | tail -15 || \
    echo "  (cannot read it from here - check it in the file manager)"

echo
echo "--- the last lines of the bridge log"
if [ -f "$HOME_DIR/bridge.log" ]; then
    tail -25 "$HOME_DIR/bridge.log"
else
    echo "  no log yet"
fi

echo
echo "=============================================="
echo " What to look for:"
echo "   * \"version\" should be 1.3.18 or newer"
echo "   * \"ffmpeg\": true"
echo "   * yt-dlp should be 2026.08.19 or newer (older ones get 403)"
echo "   * the downloads should be megabytes in size"
echo "   * the log should end with \"job ... -> done\""
echo "=============================================="
