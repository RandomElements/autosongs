#!/usr/bin/env python3
"""Tests that the bridge can update itself.

The point of the self-updater is that a fix reaches the phone without the
user installing anything again. So the bridge must be able to fetch a newer
version of itself, swap the file, keep its arguments and come back up.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "ytbridge.py")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode(errors="replace")


def post(url):
    req = urllib.request.Request(url, data=b"{}", method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


class Publisher(BaseHTTPRequestHandler):
    """Serves a newer bridge."""

    payload = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/x-python")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *a):
        pass


def main():
    tmp = tempfile.mkdtemp(prefix="updatetest_")
    work = os.path.join(tmp, "downloads")
    os.makedirs(work, exist_ok=True)

    # the bridge under test runs from a copy, so the real file is untouched
    live = os.path.join(tmp, "ytbridge.py")
    shutil.copy2(BRIDGE, live)

    port = free_port()
    pub_port = free_port()

    # a "newer" bridge: same program, different version
    newer = open(BRIDGE, encoding="utf-8").read()
    newer = re.sub(r'^BRIDGE_VERSION = "[^"]+"', 'BRIDGE_VERSION = "9.9.9"',
                   newer, count=1, flags=re.M)
    assert 'BRIDGE_VERSION = "9.9.9"' in newer
    Publisher.payload = newer.encode("utf-8")

    pub = ThreadingHTTPServer(("127.0.0.1", pub_port), Publisher)
    threading.Thread(target=pub.serve_forever, daemon=True).start()

    env = dict(os.environ)
    env["YTBRIDGE_UPDATE_URLS"] = "http://127.0.0.1:%d/ytbridge.py" % pub_port
    log = open(os.path.join(tmp, "bridge.log"), "wb")
    proc = subprocess.Popen([sys.executable, live, "--port", str(port),
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

        health = json.loads(get(base + "/health"))
        # The bridge reports the version it is running. The test does not
        # pin a number - the number moves with every release, and a test
        # that has to be edited for each one stops being a test.
        import ytbridge
        assert health["version"] == ytbridge.BRIDGE_VERSION, health
        print("OK  the bridge starts and reports its version")

        answer = json.loads(post(base + "/update"))
        print("   the update says:", answer)
        assert answer.get("state") in ("updating", "current"), answer

        # the bridge restarts itself - wait for it to come back
        version = None
        for _ in range(60):
            try:
                health = json.loads(get(base + "/health"))
                version = health.get("version")
                if version == "9.9.9":
                    break
            except Exception:
                pass
            time.sleep(0.5)

        assert version == "9.9.9", \
            "the bridge did not come back as the new version: %s" % version
        print("OK  the bridge replaced itself and restarted")

        on_disk = open(live, encoding="utf-8").read()
        assert 'BRIDGE_VERSION = "9.9.9"' in on_disk, \
            "the file on disk was not replaced"
        print("OK  the file on disk is the new version")

        assert os.path.exists(live + ".bak"), "no backup was kept"
        print("OK  the old file was kept as a backup")

        health = json.loads(get(base + "/health"))
        assert health.get("update") in ("current", "updating"), health
        print("OK  the health endpoint reports the update state")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()
        pub.shutdown()

    print("\nALL UPDATE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
