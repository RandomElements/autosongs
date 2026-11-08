#!/usr/bin/env bash
# The installer must pick the newest SETUP SCRIPT, not just the newest
# bridge.
#
# These are two different numbers. A host can carry the newest bridge and
# an old setup script - and the setup script is the one that actually runs
# on the phone. When the installer chose by the bridge version alone, a
# stale setup script won and the phone got the old behaviour.
#
#     bash test_installer_select.sh
#
set -u
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

FAILED=0
TMP="$(mktemp -d)"
SERVER_PID=""
cleanup() {
    # The server has to be stopped too. A leftover server keeps the port
    # and the next run then talks to the wrong files.
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    rm -rf "$TMP"
}
trap cleanup EXIT

check() {
    if [ "$2" = "1" ]; then
        echo "   OK $1"
    else
        echo "   FAIL $1"
        FAILED=$((FAILED + 1))
    fi
}

# Two fake addresses, served from this machine with a tiny python server.
A="$TMP/a"
B="$TMP/b"
mkdir -p "$A" "$B"

# A: the newest BRIDGE but an OLD setup script.
cat > "$A/ytbridge.py" <<'EOF'
BRIDGE_VERSION = "1.3.99"
EOF
cat > "$A/setup-termux.sh" <<'EOF'
SETUP_VERSION="1.0.0"
EOF

# B: an older bridge but the newest SETUP script.
cat > "$B/ytbridge.py" <<'EOF'
BRIDGE_VERSION = "1.0.1"
EOF
cat > "$B/setup-termux.sh" <<'EOF'
SETUP_VERSION="1.3.20"
EOF

# The two folders are served as /a and /b from one document root.
PORT="$(python3 -c 'import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()')"
mkdir -p "$TMP/www"
ln -sfn "$A" "$TMP/www/a"
ln -sfn "$B" "$TMP/www/b"
(cd "$TMP/www" && exec python3 -m http.server "$PORT" >/dev/null 2>&1) &
SERVER_PID=$!
sleep 2

if ! curl -fsSL --max-time 5 "http://127.0.0.1:$PORT/a/ytbridge.py" >/dev/null 2>&1; then
    echo "FAIL  the test server does not work"
    exit 1
fi

HOSTS="http://127.0.0.1:$PORT/a http://127.0.0.1:$PORT/b"

# ---- the selection rule itself -------------------------------------------
newer() { printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1; }

BEST_HOST=""
BEST_SETUP=""
for host in $HOSTS; do
    v="$(curl -fsSL --max-time 10 "$host/setup-termux.sh" 2>/dev/null \
         | sed -n 's/^SETUP_VERSION="\(.*\)"$/\1/p' | head -1)"
    if [ -n "$v" ]; then
        if [ -z "$BEST_SETUP" ] || [ "$(newer "$BEST_SETUP" "$v")" = "$v" ]; then
            BEST_SETUP="$v"; BEST_HOST="$host"
        fi
    fi
done

if [ "$BEST_SETUP" = "1.3.20" ]; then
    check "the newest setup script wins" 1
else
    check "the newest setup script wins" 0
    echo "   picked $BEST_SETUP from $BEST_HOST"
fi

if printf '%s' "$BEST_HOST" | grep -q "/b$"; then
    check "the host with the newest setup script is chosen" 1
else
    check "the host with the newest setup script is chosen" 0
    echo "   chose $BEST_HOST"
fi

# ---- and the real installer must follow the same rule --------------------
# The installer downloads the setup script from the host it picked. Run it
# with the two fake addresses and see which setup script lands in ~/autosongs.
HOMEDIR="$TMP/home"
mkdir -p "$HOMEDIR"
cp install-termux.sh "$TMP/install-termux.sh"

# The real installer also runs the setup script, so replace the exec with
# a copy so we can look at what it downloaded.
sed 's|^exec bash "\$WORKDIR/setup-termux.sh"|cp "$WORKDIR/setup-termux.sh" "$WORKDIR/chosen-setup.sh" 2>/dev/null \|\| true|' \
    "$TMP/install-termux.sh" > "$TMP/install-copy.sh"

out="$(HOME="$HOMEDIR" YTBRIDGE_HOSTS="$HOSTS" bash "$TMP/install-copy.sh" 2>&1)"
if [ -f "$HOMEDIR/autosongs/chosen-setup.sh" ]; then
    got="$(sed -n 's/^SETUP_VERSION="\(.*\)"$/\1/p' "$HOMEDIR/autosongs/chosen-setup.sh" | head -1)"
    if [ "$got" = "1.3.20" ]; then
        check "the installer downloads the newest setup script" 1
    else
        check "the installer downloads the newest setup script" 0
        echo "   it downloaded setup $got"
    fi
else
    check "the installer downloads the newest setup script" 0
    echo "$out" | tail -10
fi

kill $SERVER_PID 2>/dev/null || true

echo
if [ "$FAILED" -gt 0 ]; then
    echo "FAILED: $FAILED check(s)"
    exit 1
fi
echo "PASS"
