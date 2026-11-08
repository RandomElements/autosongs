#!/data/data/com.termux/files/usr/bin/bash
# AutoSongs - paste-installer for Termux.
#
# Usage:
#     bash -c "$(curl -fsSL https://<site>/install-termux.sh)"
#
# Every publish of AutoSongs gets a new web address, so this script does not
# point at one fixed address. It asks all of them which one carries the
# newest SETUP SCRIPT and uses that one - so this file never goes stale.
#
# The setup script is what matters here, not the bridge: the setup script is
# what runs on the phone. An address could carry the newest bridge and an
# old setup script, and then the old script would be the one that runs.
set -euo pipefail

WORKDIR="$HOME/autosongs"

# A safe place for temporary files.
#
# Termux does NOT have /tmp by default and "$TMPDIR" is usually unset, so
# "mktemp /tmp/..." fails there - and with "set -e" that kills the script
# before it does anything at all.
AUTOSONGS_TMP="${TMPDIR:-}"
if [ -z "$AUTOSONGS_TMP" ] || [ ! -d "$AUTOSONGS_TMP" ]; then
    AUTOSONGS_TMP="$WORKDIR/tmp"
    mkdir -p "$AUTOSONGS_TMP"
fi

BRIDGE_HOSTS="${YTBRIDGE_HOSTS:-https://autosongs.example}"

echo "==> looking for the newest setup script"
BEST_HOST=""
BEST_VER=""
BEST_FILE=""
for host in $BRIDGE_HOSTS; do
    tmp="$(mktemp "${AUTOSONGS_TMP}/autosongs-setup.XXXXXX")"
    if curl -fsSL --max-time 20 -o "$tmp" "$host/setup-termux.sh" 2>/dev/null; then
        ver="$(sed -n 's/^SETUP_VERSION="\(.*\)"$/\1/p' "$tmp" | head -1)"
        if [ -n "$ver" ]; then
            if [ -z "$BEST_VER" ]; then
                BEST_VER="$ver"; BEST_HOST="$host"; BEST_FILE="$tmp"
            else
                newest="$(printf '%s\n%s\n' "$BEST_VER" "$ver" | sort -V | tail -1)"
                if [ "$newest" = "$ver" ]; then
                    BEST_VER="$ver"; BEST_HOST="$host"
                    rm -f "$BEST_FILE"; BEST_FILE="$tmp"
                else
                    rm -f "$tmp"
                fi
            fi
        else
            rm -f "$tmp"
        fi
    else
        rm -f "$tmp"
    fi
done

if [ -z "$BEST_HOST" ]; then
    echo "!! could not reach any AutoSongs download address - is this phone online?"
    exit 1
fi
echo "    newest setup script: $BEST_VER at $BEST_HOST"

mkdir -p "$WORKDIR"

cp "$BEST_FILE" "$WORKDIR/setup-termux.sh"
chmod +x "$WORKDIR/setup-termux.sh"
rm -f "$BEST_FILE"

echo "==> running the setup"
exec bash "$WORKDIR/setup-termux.sh"
