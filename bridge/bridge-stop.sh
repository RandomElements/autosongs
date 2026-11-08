#!/data/data/com.termux/files/usr/bin/bash
# AutoSongs — stop any running yt-dlp bridge.
#
#     bash bridge-stop.sh [port]
#
# Kills EVERY process whose command line mentions ytbridge.py, not just the
# pid in bridge.pid. A bridge that was started by hand leaves no pid file
# behind; then a fresh instance cannot bind the port and the health check
# would talk to the old, stale process and report success.
set -uo pipefail

PORT="${1:-8765}"

STOPPED=0
for PID_DIR in /proc/[0-9]*; do
    PID="${PID_DIR#/proc/}"
    [ "$PID" = "$$" ] && continue
    CMD="$(cat "$PID_DIR/cmdline" 2>/dev/null | tr '\0' ' ' || true)"
    case "$CMD" in
        *ytbridge.py*)
            echo "    stopping bridge pid $PID"
            kill "$PID" 2>/dev/null || true
            STOPPED=1
            ;;
    esac
done

if [ "$STOPPED" = "1" ]; then
    sleep 2
    # Anything that survived SIGTERM gets SIGKILL.
    for PID_DIR in /proc/[0-9]*; do
        PID="${PID_DIR#/proc/}"
        [ "$PID" = "$$" ] && continue
        CMD="$(cat "$PID_DIR/cmdline" 2>/dev/null | tr '\0' ' ' || true)"
        case "$CMD" in
            *ytbridge.py*)
                kill -9 "$PID" 2>/dev/null || true
                ;;
        esac
    done
    sleep 1
fi

# Wait until nothing answers on the port any more.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        sleep 1
    else
        break
    fi
done

if curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "!! something is still listening on port ${PORT}"
    exit 1
fi

echo "    port ${PORT} is free"
exit 0
