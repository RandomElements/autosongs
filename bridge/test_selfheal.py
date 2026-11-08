"""The bridge must repair an outdated yt-dlp by itself.

The phone in question ran yt-dlp 2026.06.09, four months old. Every
download failed with "HTTP Error 403: Forbidden" and the only cure was for
a person to open Termux and run pip. The bridge should do that itself: see
that yt-dlp is too old, update it, and try again.

This test drives a real bridge with a stub yt-dlp that reports an old
version and always fails with a 403, and checks that the bridge tried to
update it before giving up.
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ytbridge  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# A stub yt-dlp that claims to be old and always fails with a 403. When the
# bridge runs pip, the stub pip in the same folder reports a new version.
STUB = r'''#!/usr/bin/env bash
for ((i=0;i<=$#;i++)); do
  case "${!i}" in
    --version) echo "$YT_STUB_VERSION"; exit 0;;
  esac
done
if [ "$1" = "--version" ]; then echo "$YT_STUB_VERSION"; exit 0; fi
ARGS=("$@")
MODE="download"
for ((i=0;i<${#ARGS[@]};i++)); do
  case "${ARGS[$i]}" in
    --flat-playlist) MODE="search";;
  esac
done
if [ "$MODE" = "search" ]; then
  cat "$CANDIDATES_FILE"
  exit 0
fi
echo "ERROR: unable to download video data: HTTP Error 403: Forbidden"
exit 1
'''

# The stub pip: it "upgrades" yt-dlp by writing a new version into a file.
STUB_PIP = r'''#!/usr/bin/env bash
if [ "$1" = "--version" ] || [ "$1" = "-V" ]; then
  echo "stub pip 1.0"
  exit 0
fi
# Pretend to install yt-dlp: the stub yt-dlp reads this file.
echo "2026.10.26-stub" > "$YT_STUB_STATE"
echo "Successfully installed yt-dlp-2026.10.26"
exit 0
'''

STUB_YTDLP = r'''#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  cat "$YT_STUB_STATE" 2>/dev/null || echo "2026.06.09-stub"
  exit 0
fi
for ((i=0;i<=$#;i++)); do
  case "${!i}" in
    --version) cat "$YT_STUB_STATE" 2>/dev/null || echo "2026.06.09-stub"; exit 0;;
  esac
done
ARGS=("$@")
MODE="download"
for ((i=0;i<${#ARGS[@]};i++)); do
  case "${ARGS[$i]}" in
    --flat-playlist) MODE="search";;
  esac
done
if [ "$MODE" = "search" ]; then
  cat "$CANDIDATES_FILE"
  exit 0
fi
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
    tmp = tempfile.mkdtemp(prefix="selfheal_")
    try:
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)

        state = os.path.join(tmp, "version.txt")
        with open(state, "w") as fh:
            fh.write("2026.06.09-stub\n")

        stub = os.path.join(bindir, "yt-dlp")
        with open(stub, "w") as fh:
            fh.write(STUB_YTDLP)
        os.chmod(stub, 0o755)

        stub_pip = os.path.join(bindir, "pip")
        with open(stub_pip, "w") as fh:
            fh.write(STUB_PIP)
        os.chmod(stub_pip, 0o755)

        # "python -m pip" is tried first, so python -m pip must also work.
        stub_python = os.path.join(bindir, "python")
        with open(stub_python, "w") as fh:
            fh.write('#!/usr/bin/env bash\nexec "%s/pip" "$@"\n' % bindir)
        os.chmod(stub_python, 0o755)

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
        env["YT_STUB_STATE"] = state
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

        # ---- the health answer must say that yt-dlp is too old ---------
        health = get("http://127.0.0.1:%d/health" % port)
        assert health.get("yt_dlp_outdated") is True, (
            "the bridge did not notice that yt-dlp is too old: %s" % health)
        assert health.get("yt_dlp_min"), "the health answer has no minimum"
        print("OK  /health says yt-dlp is too old")

        # ---- a failed download must trigger the update ------------------
        job = post("http://127.0.0.1:%d/search" % port,
                   {"query": "Some Artist - Some Song", "title": "Some Song",
                    "artist": "Some Artist", "preset": "audio_m4a"})
        job_id = job.get("id")

        status = {}
        for _ in range(160):
            status = get("http://127.0.0.1:%d/job/%s" % (port, job_id))
            if status.get("status") in ("error", "done"):
                break
            time.sleep(0.25)
        time.sleep(0.6)

        log = open(logpath).read()
        print("--- the bridge log ---")
        print(log.strip())
        print("------------------------")

        assert "updating it now" in log, (
            "the bridge did not try to update yt-dlp\\n%s" % log)
        print("OK  the bridge tried to update yt-dlp")

        assert "yt-dlp is now" in log, (
            "the bridge did not say what version it ended up with\\n%s" % log)
        print("OK  the bridge reported the new version")

        # The stub pip must actually have been called.
        with open(state) as fh:
            new_version = fh.read().strip()
        assert new_version == "2026.10.26-stub", (
            "the update did not run: the version is still %s" % new_version)
        print("OK  the update really ran")

        proc.terminate()
        proc.wait(timeout=10)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
