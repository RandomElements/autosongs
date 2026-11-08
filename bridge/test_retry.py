#!/usr/bin/env python3
"""Tests that the bridge gets past a 403 by trying another client.

YouTube refuses some clients at some moments and serves others a moment
later. The old bridge only retried on "not a bot", so a 403 ended the job
immediately - and on the phone that failure was then papered over with a
fake file.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from testhelpers import stub_on_path

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "ytbridge.py")

STUB = r'''#!/usr/bin/env bash
ARGS=("$@")
MODE="download"
for ((i=0;i<${#ARGS[@]};i++)); do
  case "${ARGS[$i]}" in
    --flat-playlist) MODE="search";;
    --version) echo "2026.10.26-stub"; exit 0;;
  esac
done
LAST=""
for ((i=${#ARGS[@]}-1;i>=0;i--)); do
  v="${ARGS[$i]}"
  case "$v" in
    -*) continue;;
    http*|ytsearch*) LAST="$v"; break;;
  esac
done
if [ "$MODE" = "search" ]; then
  cat "$CANDIDATES_FILE"
  exit 0
fi
OUTDIR=""
CLIENT=""
for ((i=0;i<${#ARGS[@]};i++)); do
  if [ "${ARGS[$i]}" = "-o" ]; then OUTDIR="${ARGS[$((i+1))]}"; fi
  if [ "${ARGS[$i]}" = "--extractor-args" ]; then CLIENT="${ARGS[$((i+1))]}"; fi
done
mkdir -p "$OUTDIR"
N=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
N=$((N+1))
echo "$N" > "$COUNT_FILE"
echo "attempt $N client=${CLIENT:-default}" >> "$LOG_FILE"
# The first three attempts are refused with a 403, like YouTube does.
if [ "$N" -le 3 ]; then
  echo "ERROR: unable to download video data: HTTP Error 403: Forbidden" >&2
  exit 1
fi
echo "AUTOSONGS_FILE $OUTDIR/Title.m4a"
printf 'ID3' > "$OUTDIR/Title.m4a"
printf '\x00%.0s' {1..64} >> "$OUTDIR/Title.m4a"
exit 0
'''


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode(errors="replace")


def post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def main():
    tmp = tempfile.mkdtemp(prefix="retrytest_")
    work = os.path.join(tmp, "work")
    os.makedirs(work, exist_ok=True)
    port = free_port()

    stub = stub_on_path(tmp, "yt-dlp", STUB)

    cand = os.path.join(tmp, "candidates.jsonl")
    with open(cand, "w") as fh:
        fh.write(json.dumps({"id": "aaaaaaaaaaa", "title": "Some Song",
                             "channel": "Some Artist", "duration": 200}) + "\n")

    count_file = os.path.join(tmp, "count.txt")
    with open(count_file, "w") as fh:
        fh.write("0")
    log_file = os.path.join(tmp, "attempts.log")
    open(log_file, "w").close()

    log = open(os.path.join(tmp, "bridge.log"), "wb")
    env = dict(os.environ)
    env["PATH"] = tmp + os.pathsep + env.get("PATH", "")
    env["CANDIDATES_FILE"] = cand
    env["COUNT_FILE"] = count_file
    env["LOG_FILE"] = log_file
    proc = subprocess.Popen([sys.executable, BRIDGE, "--port", str(port),
                              "--workdir", work],
                             stdout=log, stderr=subprocess.STDOUT, env=env)
    base = "http://127.0.0.1:%d" % port
    try:
        for _ in range(60):
            try:
                get(base + "/health")
                break
            except Exception:
                time.sleep(0.2)

        job = json.loads(post(base + "/search", {
            "query": "Some Artist - Some Song", "title": "Some Song",
            "artist": "Some Artist", "preset": "audio_m4a"}))
        status = {}
        for _ in range(80):
            status = json.loads(get(base + "/job/" + job["id"]))
            if status.get("status") in ("done", "error"):
                break
            time.sleep(0.25)

        attempts = open(log_file).read().strip().splitlines()
        for a in attempts:
            print("  ", a)

        assert status.get("status") == "done", \
            "the bridge gave up on the 403 instead of trying another client: %s" % status
        assert len(attempts) >= 4, \
            "the bridge did not retry: %s" % attempts
        assert "player_client=android" in attempts[1], \
            "the second attempt did not switch client: %s" % attempts[1]
        assert "player_client=web" in attempts[2], \
            "the third attempt did not switch client: %s" % attempts[2]
        print("OK  a 403 is survived by trying other clients")

        served = get(base + "/file/" + job["id"])
        assert served.startswith("ID3"), "the wrong file was served"
        print("OK  the file from the successful attempt is served")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()

    print("\nALL RETRY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
