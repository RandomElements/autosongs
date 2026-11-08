#!/usr/bin/env python3
"""Tests the rescue path: the bridge restarts and forgets its job, the app
still has to get its file.

The failure this covers is real: the bridge keeps its job list in memory, so
running setup-termux.sh again (or any restart) throws the job away while the
finished file stays on disk. The app then shows "Transfer failed: HTTP 404"
for a download that actually worked.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "ytbridge.py")

ID3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 64


def start_bridge(workdir, port):
    proc = subprocess.Popen(
        [sys.executable, BRIDGE, "--port", str(port), "--workdir", workdir],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % port, timeout=2) as r:
                if json.loads(r.read().decode()).get("ok"):
                    return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("bridge did not start")


def get(port, path):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d%s" % (port, path), timeout=10) as r:
            return r.status, r.read(), r.headers.get("X-File-Name", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ""


def main():
    tmp = tempfile.mkdtemp(prefix="ytbridge_rescue_")
    work = os.path.join(tmp, "downloads")
    os.makedirs(work)
    port = 8931

    # A finished song and the bridge's own source code, side by side.
    song = os.path.join(work, "Some Artist - Some Song.mp3")
    with open(song, "wb") as fh:
        fh.write(ID3)
    script = os.path.join(work, "ytbridge.py")
    with open(script, "w") as fh:
        fh.write("#!/usr/bin/env python3\nprint('not a song')\n")

    proc = start_bridge(work, port)
    try:
        # 1. the rescue finds the song by name
        status, body, name = get(port, "/find?name=Some%20Artist%20-%20Some%20Song")
        assert status == 200, "rescue failed: %s" % status
        assert body == ID3, "rescue returned the wrong bytes"
        print("OK  the finished song is found by name")

        # 2. the rescue never returns the bridge script
        status, body, name = get(port, "/find?name=ytbridge")
        assert status == 404, "the rescue returned a non-media file: %s" % status
        print("OK  the bridge script is never handed over")

        # 3. after a restart the job record is gone -> the old URL 404s,
        #    which is exactly what the user saw
        proc.terminate()
        proc.wait(timeout=10)
        proc = start_bridge(work, port)
        status, _, _ = get(port, "/file/deadbeef")
        assert status == 404, "a lost job should 404, got %s" % status
        print("OK  a lost job answers 404 (the failure the user hit)")

        # 4. but the file is still reachable by name
        status, body, name = get(port, "/find?name=Some%20Artist%20-%20Some%20Song")
        assert status == 200 and body == ID3, "rescue after restart failed: %s" % status
        print("OK  the song is still reachable after a restart")

        # 5. the health check reports the workdir, so the setup script can
        #    tell whether the running bridge is the right one
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/health" % port, timeout=5) as r:
            health = json.loads(r.read().decode())
        assert health.get("workdir") == work, "health does not report the workdir"
        print("OK  /health reports the workdir")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print("\nALL RESCUE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
