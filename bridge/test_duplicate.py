#!/usr/bin/env python3
"""
Regression test: the bridge must never hand back a PREVIOUS job's file.

The bug: yt-dlp was asked for the output path with `--print filepath`, which
prints BEFORE the download - so for a muxed video it reported the pre-merge
stream (Title.f137.webm), a file yt-dlp deletes once the mux succeeds. The
bridge then fell back to scanning the whole work folder, and finished
downloads live there under their final name ("Artist - Title.mp4"). The bridge
picked the previous track's file, and the app saved the same bytes a second
time under the new track's name - two files, identical size.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ytbridge.py")

# A stub yt-dlp that behaves like the real one for the part that matters:
# it reports a pre-merge path that does not exist, and writes the real file.
STUB = r'''#!/usr/bin/env bash
ARGS=("$@")
MODE="download"
for ((i=0;i<${#ARGS[@]};i++)); do
  case "${ARGS[$i]}" in
    --flat-playlist) MODE="search";;
    --version) echo "2026.10.21-stub"; exit 0;;
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
  case "$LAST" in
    ytsearch*) ;;
    *) echo "BRIDGE-STUB-ERROR: search used a bare query: $LAST" >&2; exit 1;;
  esac
  cat "$CANDIDATES_FILE"
  exit 0
fi
# The download step.
OUTDIR=""
for ((i=0;i<${#ARGS[@]};i++)); do
  if [ "${ARGS[$i]}" = "-o" ]; then OUTDIR="${ARGS[$((i+1))]}"; fi
done
mkdir -p "$OUTDIR"
echo "[download] 100% of 10.00MiB"
# The pre-merge path: this file does not exist.
echo "AUTOSONGS_FILE $OUTDIR/Title.f137.webm"
if grep -q empty "$MODE_FILE" 2>/dev/null; then
  # yt-dlp finished without leaving a usable file behind - exactly what
  # happened on the phone.
  echo "ERROR: unable to write data"
  exit 0
fi
# The real, finished file.
echo "AUTOSONGS_FILE $OUTDIR/Title.m4a"
printf 'REAL-VIDEO-BYTES-0123456789' > "$OUTDIR/Title.m4a"
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
        return r.read().decode()


def post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


def main():
    tmp = tempfile.mkdtemp(prefix="dupetest_")
    work = os.path.join(tmp, "work")
    os.makedirs(work, exist_ok=True)
    port = free_port()
    stub = os.path.join(tmp, "yt-dlp")
    with open(stub, "w") as fh:
        fh.write(STUB)
    os.chmod(stub, 0o755)

    cand = os.path.join(tmp, "candidates.jsonl")
    with open(cand, "w") as fh:
        fh.write(json.dumps({"id": "aaaaaaaaaaa", "title": "Some Song",
                             "channel": "Some Artist", "duration": 200}) + "\n")

    log = open(os.path.join(tmp, "bridge.log"), "wb")
    env = dict(os.environ)
    env["PATH"] = tmp + os.pathsep + env.get("PATH", "")
    env["CANDIDATES_FILE"] = cand
    mode_file = os.path.join(tmp, "mode.txt")
    with open(mode_file, "w") as fh:
        fh.write("normal")
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

        # ---- a previous track, finished and sitting in the work folder ----
        previous = os.path.join(work, "Previous Artist - Previous Song.mp4")
        with open(previous, "w") as fh:
            fh.write("OLD-DIFFERENT-BYTES")
        old_mtime = time.time() - 3600
        os.utime(previous, (old_mtime, old_mtime))

        job = json.loads(post(base + "/search", {
            "query": "Some Artist - Some Song", "title": "Some Song",
            "artist": "Some Artist", "preset": "audio_m4a"}))
        job_id = job["id"]
        for _ in range(60):
            status = json.loads(get(base + "/job/" + job_id))
            if status.get("status") in ("done", "error"):
                break
            time.sleep(0.3)

        print("job status :", status.get("status"))
        print("file       :", status.get("file"))
        print("error      :", status.get("error"))
        assert status.get("status") == "done", status

        served = get(base + "/file/" + job_id)
        print("served     :", served)
        assert served == "REAL-VIDEO-BYTES-0123456789", \
            "the bridge served the WRONG file: %r" % served

        # The previous track's file must be untouched and not re-used.
        with open(previous) as fh:
            assert fh.read() == "OLD-DIFFERENT-BYTES", "previous file was clobbered"

        # ---- case 2: the download produces nothing at all ------------------
        # The bridge must NOT fall back to the previous track's file. That
        # fallback is what made the app save the same song twice.
        with open(mode_file, "w") as fh:
            fh.write("empty")
        job2 = json.loads(post(base + "/search", {
            "query": "Other Artist - Other Song", "title": "Other Song",
            "artist": "Other Artist", "preset": "audio_m4a"}))
        job2_id = job2["id"]
        for _ in range(60):
            status2 = json.loads(get(base + "/job/" + job2_id))
            if status2.get("status") in ("done", "error"):
                break
            time.sleep(0.3)

        print()
        print("--- case 2: download produced nothing ---")
        print("job status :", status2.get("status"))
        print("error      :", status2.get("error"))
        assert status2.get("status") == "error", \
            "the bridge claimed success with no file: %r" % status2
        assert status2.get("file") is None, \
            "the bridge pointed at a file it did not download: %r" % status2
        assert "OLD-DIFFERENT-BYTES" not in str(status2), \
            "the previous track's file leaked into this job"

        # And the previous file must still be intact on disk.
        with open(previous) as fh:
            assert fh.read() == "OLD-DIFFERENT-BYTES", "previous file was clobbered"

        print()
        print("ALL DUPLICATE-FILE TESTS PASSED")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
