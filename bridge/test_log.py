"""The bridge log has to say WHY a job failed.

A log that only says "job X -> error" cannot be acted on: a 403 from
YouTube, a missing ffmpeg and a missing file all look the same. This test
fails a job on purpose and checks that the reason is in the log.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


STUB = r'''#!/usr/bin/env bash
for ((i=0;i<=$#;i++)); do
  case "${!i}" in
    --version) echo "2026.10.26-stub"; exit 0;;
  esac
done
ARGS=("$@")
MODE="download"
for ((i=0;i<${#ARGS[@]};i++)); do
  case "${ARGS[$i]}" in
    --flat-playlist) MODE="search";;
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
# The download fails on purpose.
echo "ERROR: unable to download video data: HTTP Error 403: Forbidden"
exit 1
'''


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    tmp = tempfile.mkdtemp(prefix="logtest_")
    try:
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        stub = os.path.join(bindir, "yt-dlp")
        with open(stub, "w") as fh:
            fh.write(STUB)
        os.chmod(stub, 0o755)

        cand = os.path.join(tmp, "candidates.jsonl")
        with open(cand, "w") as fh:
            fh.write(json.dumps({"id": "aaaaaaaaaaa", "title": "Some Song",
                                 "channel": "Some Artist", "duration": 200}) + "\n")

        work = os.path.join(tmp, "work")
        os.makedirs(work, exist_ok=True)
        logpath = os.path.join(tmp, "bridge.log")
        port = free_port()

        env = dict(os.environ)
        env["PATH"] = bindir + os.pathsep + env["PATH"]
        env["CANDIDATES_FILE"] = cand
        env["YTBRIDGE_WORKDIR"] = work

        proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "ytbridge.py"),
             "--port", str(port), "--workdir", work],
            stdout=open(logpath, "w"), stderr=subprocess.STDOUT, env=env)

        for _ in range(60):
            try:
                get("http://127.0.0.1:%d/health" % port)
                break
            except Exception:
                time.sleep(0.25)
        else:
            print("FAIL  the bridge did not start")
            print(open(logpath).read())
            return 1

        job = post("http://127.0.0.1:%d/search" % port,
                   {"query": "Some Artist - Some Song", "title": "Some Song",
                    "artist": "Some Artist", "preset": "audio_m4a"})
        job_id = job.get("id")

        status = {}
        for _ in range(80):
            status = get("http://127.0.0.1:%d/job/%s" % (port, job_id))
            if status.get("status") in ("error", "done"):
                break
            time.sleep(0.25)

        assert status.get("status") == "error", status
        time.sleep(0.6)

        log = open(logpath).read()
        print("--- the bridge log ---")
        print(log.strip())
        print("------------------------")

        assert "-> error" in log, "the log does not say the job failed"

        # The reason has to be in the log, not only in the JSON.
        reason = status.get("error") or ""
        key = reason[:60] if reason else "403"
        assert key in log, ("the log does not say WHY it failed\\n"
                            "expected: %s\\nin the log:\\n%s" % (key, log))

        # And it must not be an empty reason.
        assert "-> error:" in log, "the error line has no reason"

        print("OK  the log says the job failed and why")
        proc.terminate()
        proc.wait(timeout=10)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
