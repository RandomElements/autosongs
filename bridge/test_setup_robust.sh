#!/usr/bin/env bash
# The setup script must never die before the bridge is started.
#
# It used to: the yt-dlp version check ran "grep" in a pipeline, and with
# "set -euo pipefail" a grep that matched nothing returned 1 - which
# aborted the whole script. On a phone without yt-dlp the result was NO
# bridge at all, which is worse than an old one.
#
#     bash test_setup_robust.sh
#
set -u
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

FAILED=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

check() {
    if [ "$2" = "1" ]; then
        echo "   OK $1"
    else
        echo "   FAIL $1"
        FAILED=$((FAILED + 1))
    fi
}

# A fake Termux: no yt-dlp, no pip, no pkg.
FAKE="$TMP/bin"
mkdir -p "$FAKE"
cat > "$FAKE/pkg" <<'EOF'
#!/usr/bin/env bash
echo "[stub pkg] $*"
exit 0
EOF
REAL_PYTHON="$(command -v python3)"
cat > "$FAKE/python" <<EOF
#!/usr/bin/env bash
if [ "\$1" = "-m" ] && [ "\$2" = "pip" ]; then
    echo "No module named pip" >&2
    exit 1
fi
exec "$REAL_PYTHON" "\$@"
EOF
chmod +x "$FAKE/pkg" "$FAKE/python"

echo "== the version check must not abort the script"
# The exact construct the setup script uses.
out="$(bash -c '
set -euo pipefail
YTDLP_RAW="$(printf "%s" "unknown")"
YTDLP_NUM="$(printf "%s" "$YTDLP_RAW" \
    | tr -c "0-9." "\n" \
    | grep -m1 -E "^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$" || true)"
echo "reached the end: [$YTDLP_NUM]"
' 2>&1)"
if [ $? -eq 0 ] && printf '%s' "$out" | grep -q "reached the end"; then
    check "a missing yt-dlp does not abort the script" 1
else
    check "a missing yt-dlp does not abort the script" 0
    echo "$out"
fi

echo "== a real version must still be found"
out="$(bash -c '
set -euo pipefail
YTDLP_RAW="2026.06.09"
YTDLP_NUM="$(printf "%s" "$YTDLP_RAW" \
    | tr -c "0-9." "\n" \
    | grep -m1 -E "^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$" || true)"
echo "[$YTDLP_NUM]"
' 2>&1)"
if printf '%s' "$out" | grep -q "\[2026.06.09\]"; then
    check "a real version is still detected" 1
else
    check "a real version is still detected" 0
    echo "$out"
fi

echo "== the setup script must start the bridge even without yt-dlp"
PORT=8899
HOMEDIR="$TMP/home"
mkdir -p "$HOMEDIR"
cp setup-termux.sh "$TMP/setup-termux.sh"
cp ytbridge.py "$TMP/ytbridge.py"
cp bridge-stop.sh "$TMP/bridge-stop.sh" 2>/dev/null || true

out="$(HOME="$HOMEDIR" PATH="$FAKE:$PATH" YTBRIDGE_PORT="$PORT" \
       bash "$TMP/setup-termux.sh" 2>&1)"
rc=$?
if [ $rc -eq 0 ]; then
    check "the setup script finished" 1
else
    check "the setup script finished" 0
    echo "$out" | tail -20
fi

if printf '%s' "$out" | grep -q "AutoSongs bridge is running"; then
    check "the bridge was started" 1
else
    check "the bridge was started" 0
    echo "$out" | tail -20
fi

if [ -f "$HOMEDIR/autosongs/bin/ytbridge.py" ]; then
    check "the bridge file was installed" 1
else
    check "the bridge file was installed" 0
fi

health="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" 2>/dev/null || true)"
if printf '%s' "$health" | grep -q '"ok": true'; then
    check "the bridge answers" 1
else
    check "the bridge answers" 0
    echo "health: $health"
fi

# The health answer must say that yt-dlp is missing rather than crashing.
if printf '%s' "$health" | grep -q '"yt_dlp_outdated"'; then
    check "the health answer reports the yt-dlp state" 1
else
    check "the health answer reports the yt-dlp state" 0
    echo "health: $health"
fi

pkill -f "$HOMEDIR/autosongs/bin/ytbridge.py" 2>/dev/null || true

echo
if [ "$FAILED" -gt 0 ]; then
    echo "FAILED: $FAILED check(s)"
    exit 1
fi
echo "PASS"
