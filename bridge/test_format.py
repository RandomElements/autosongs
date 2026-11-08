#!/usr/bin/env python3
"""Tests that the preset is a promise.

The user picked "Audio - MP3" and the phone produced a webm (or worse, a
Python script). When the audio conversion fails, yt-dlp leaves the source
file behind and never prints the after_move path, so the bridge has to
notice that the file is not the format that was asked for.
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

# A real EBML header (webm) and a real ID3 header (mp3).
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
MP3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 64

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
for ((i=0;i<${#ARGS[@]};i++)); do
  if [ "${ARGS[$i]}" = "-o" ]; then OUTDIR="${ARGS[$((i+1))]}"; fi
done
mkdir -p "$OUTDIR"
echo "[download] 100% of 10.00MiB"
MODE_NOW="$(cat "$MODE_FILE" 2>/dev/null)"
if [ "$MODE_NOW" = "conversion_failed" ]; then
  # yt-dlp could not convert, so it left the source file behind and never
  # printed the after_move path.
  printf '\x1a\x45\xdf\xa3' > "$OUTDIR/Title.webm"
  printf '\x00%.0s' {1..64} >> "$OUTDIR/Title.webm"
  exit 0
fi
echo "AUTOSONGS_FILE $OUTDIR/Title.mp3"
printf 'ID3\x03\x00\x00\x00' > "$OUTDIR/Title.mp3"
printf '\x00%.0s' {1..64} >> "$OUTDIR/Title.mp3"
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


def wait(base, job_id):
    for _ in range(80):
        status = json.loads(get(base + "/job/" + job_id))
        if status.get("status") in ("done", "error"):
            return status
        time.sleep(0.25)
    return status


def main():
    tmp = tempfile.mkdtemp(prefix="fmttest_")
    work = os.path.join(tmp, "work")
    os.makedirs(work, exist_ok=True)
    port = free_port()

    stub = stub_on_path(tmp, "yt-dlp", STUB)

    cand = os.path.join(tmp, "candidates.jsonl")
    with open(cand, "w") as fh:
        fh.write(json.dumps({"id": "aaaaaaaaaaa", "title": "Some Song",
                             "channel": "Some Artist", "duration": 200}) + "\n")

    mode_file = os.path.join(tmp, "mode.txt")
    with open(mode_file, "w") as fh:
        fh.write("conversion_failed")

    log = open(os.path.join(tmp, "bridge.log"), "wb")
    env = dict(os.environ)
    env["PATH"] = tmp + os.pathsep + env.get("PATH", "")
    env["CANDIDATES_FILE"] = cand
    env["MODE_FILE"] = mode_file
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

        # ---- case 1: the mp3 conversion failed ----
        job = json.loads(post(base + "/search", {
            "query": "Some Artist - Some Song", "title": "Some Song",
            "artist": "Some Artist", "preset": "audio_mp3"}))
        status = wait(base, job["id"])
        print("status :", status.get("status"))
        print("error  :", status.get("error"))
        assert status.get("status") == "error", \
            "the bridge handed over a webm and called it an mp3: %s" % status
        err = (status.get("error") or "").lower()
        assert "mp3" in err and "ffmpeg" in err, \
            "the error does not explain the problem: %r" % status.get("error")
        print("OK  a failed mp3 conversion is reported, not passed off as a song")

        # ---- case 2: a working mp3 conversion ----
        with open(mode_file, "w") as fh:
            fh.write("normal")
        job = json.loads(post(base + "/search", {
            "query": "Some Artist - Some Song", "title": "Some Song",
            "artist": "Some Artist", "preset": "audio_mp3"}))
        status = wait(base, job["id"])
        print("status :", status.get("status"))
        print("file   :", status.get("file"))
        assert status.get("status") == "done", status
        assert status.get("file", "").endswith(".mp3"), \
            "the finished file is not an mp3: %s" % status.get("file")
        served = get(base + "/file/" + job["id"])
        assert served.startswith("ID3"), "the served file is not an mp3"
        print("OK  a working mp3 conversion is served as an mp3")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()

    print("\nALL FORMAT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
