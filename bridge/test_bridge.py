"""
Offline integration test for ytbridge.py.

It fakes `yt-dlp` with a stub that understands the two invocations the bridge
makes:
  1. --flat-playlist --dump-json "ytsearchN:<query>"   -> candidate list
  2. download of a watch?v=<id> URL                     -> a real file

The stub asserts that the search uses the ytsearch: prefix, which was the
original bug.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "ytbridge.py")

CANDIDATES = [
    {"id": "aaaaaaaaaaa", "title": "Blinding Lights (Live Cover)", "artist": "Some Guy",
     "duration": 205},
    {"id": "bbbbbbbbbbb", "title": "Blinding Lights", "artist": "The Weeknd",
     "duration": 200},
    {"id": "ccccccccccc", "title": "Blinding Lights (Official Video)", "artist": "The Weeknd",
     "duration": 200},
    {"id": "ddddddddddd", "title": "Blinding Lights Remix", "artist": "The Weeknd",
     "duration": 240},
]

STUB = r'''#!/usr/bin/env bash
ARGS=("$@")
MODE="download"
SEARCHQ=""
for ((i=0;i<${#ARGS[@]};i++)); do
  case "${ARGS[$i]}" in
    --flat-playlist) MODE="search";;
    --version) echo "2026.10.21-stub"; exit 0;;
  esac
  last="${ARGS[$i]}"
done
for ((i=0;i<${#ARGS[@]};i++)); do
  if [ "${ARGS[$i]}" = "--dump-json" ] || [ "${ARGS[$i]}" = "--print" ]; then
    :
  fi
done
# find the last positional (the query / url)
for ((i=${#ARGS[@]}-1;i>=0;i--)); do
  v="${ARGS[$i]}"
  case "$v" in
    -*) continue;;
    http*|ytsearch*) LAST="$v"; break;;
  esac
done
if [ "$MODE" = "search" ]; then
  case "$LAST" in
    ytsearch*) ;;
    *) echo "BRIDGE-STUB-ERROR: search used a bare query (no ytsearch: prefix): $LAST" >&2; exit 1;;
  esac
  cat "$CANDIDATES_FILE"
  exit 0
fi
# download mode
OUTDIR=""
for ((i=0;i<${#ARGS[@]};i++)); do
  if [ "${ARGS[$i]}" = "-o" ]; then OUTDIR="${ARGS[$((i+1))]}"; fi
done
if [ -z "$OUTDIR" ]; then echo "no -o" >&2; exit 1; fi
mkdir -p "$OUTDIR"
ID="${LAST##*v=}"
echo "[youtube] ${ID}: Downloading"
echo "[download]  0.0% of 3.00MiB"
echo "[download] 100.0% of 3.00MiB"
echo "AUTOSONGS_META Blinding Lights $(printf '\037')The Weeknd"
head -c 1048576 /dev/urandom > "$OUTDIR/Blinding Lights.m4a"
exit 0
'''


def main():
    tmp = tempfile.mkdtemp(prefix="ytbridge_test_")
    try:
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        stub = os.path.join(bindir, "yt-dlp")
        with open(stub, "w") as fh:
            fh.write(STUB)
        os.chmod(stub, 0o755)

        cand_file = os.path.join(tmp, "candidates.jsonl")
        with open(cand_file, "w") as fh:
            for c in CANDIDATES:
                fh.write(json.dumps(c) + "\n")

        workdir = os.path.join(tmp, "work")
        env = dict(os.environ)
        env["PATH"] = bindir + os.pathsep + env["PATH"]
        env["CANDIDATES_FILE"] = cand_file

        # pick a free port so leftover instances cannot collide
        import socket as _socket
        _probe = _socket.socket()
        _probe.bind(("127.0.0.1", 0))
        port = _probe.getsockname()[1]
        _probe.close()
        logpath = os.path.join(tmp, "bridge.log")
        logfile = open(logpath, "w")
        proc = subprocess.Popen([sys.executable, BRIDGE, "--port", str(port),
                                 "--workdir", workdir],
                                env=env, stdout=logfile,
                                stderr=subprocess.STDOUT, text=True)
        time.sleep(2)

        base = "http://127.0.0.1:%d" % port
        health = json.loads(urllib.request.urlopen(base + "/health").read())
        print("health:", health)
        assert health.get("ok") is True, "health check failed"

        payload = json.dumps({
            "query": "The Weeknd - Blinding Lights",
            "title": "Blinding Lights",
            "artist": "The Weeknd",
            "preset": "audio_m4a",
            "embed_metadata": True,
            "embed_thumbnail": True,
            "expected_duration": 200,
        }).encode()
        req = urllib.request.Request(base + "/search", data=payload,
                                     headers={"Content-Type": "application/json"})
        started = json.loads(urllib.request.urlopen(req).read())
        job_id = started["id"]
        print("job:", job_id)

        final = {}
        for _ in range(40):
            time.sleep(0.5)
            final = json.loads(urllib.request.urlopen(base + "/job/" + job_id).read())
            if final.get("status") in ("done", "error"):
                break

        print("final status:", final.get("status"))
        print("chosen title :", final.get("title"))
        print("chosen artist:", final.get("artist"))
        print("match score  :", final.get("match_score"))
        print("error        :", final.get("error", ""))

        assert final.get("status") == "done", "job did not complete: %s" % final.get("error")
        assert final.get("has_file") is True, "no file produced"

        # the bridge must pick the *official* track, not the live cover
        assert final.get("video_id") in ("bbbbbbbbbbb", "ccccccccccc"), \
            "wrong video picked: %s" % final.get("video_id")
        assert final.get("artist") == "The Weeknd", \
            "wrong artist matched: %s" % final.get("artist")

        # fetch the file
        out = os.path.join(tmp, "out.bin")
        urllib.request.urlretrieve(base + "/file/" + job_id, out)
        size = os.path.getsize(out)
        print("downloaded bytes:", size)
        assert size == 1048576, "unexpected file size %s" % size

        print("\nALL BRIDGE TESTS PASSED")
        return 0
    finally:
        try:
            with open(os.path.join(tmp, "bridge.log")) as fh:
                log = fh.read().strip()
            if log:
                print("\n--- bridge log ---")
                print(log)
        except OSError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
