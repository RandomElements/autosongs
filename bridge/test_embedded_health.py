"""The bridge inside the app has to be able to answer.

Inside the app, yt-dlp is a library rather than a program, and the answer
to /health carries the version of that library. Getting that wrong took
the whole bridge down: the version turned out to be a module instead of a
number, the answer could not be written down, the connection closed with
nothing on it, and the app could only say "the bridge has gone quiet" -
which sends the user looking at the network instead of at the bridge.

This test fakes yt-dlp the way the real one is shaped - it has both a
__version__ and a version *module* - and then asks a running bridge for
its health.
"""

import json
import os
import socket
import sys
import tempfile
import threading
import types
import urllib.error
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


class FakeYtDlp(types.ModuleType):
    """Shaped like the real yt_dlp: __version__ plus a version module."""

    def __init__(self):
        super().__init__("yt_dlp")
        self.__version__ = "2026.10.26"
        self.version = types.ModuleType("yt_dlp.version")
        self.version.__version__ = "2026.10.26"


def serve(port):
    workdir = os.path.join(tempfile.mkdtemp(prefix="autosongs-"), "downloads")
    server = ytbridge.make_server("127.0.0.1", port, workdir=workdir, embedded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def get(port, path="/health"):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=15) as r:
        return r.status, r.read().decode("utf-8")


def get_allowing_error(port, path="/health"):
    try:
        return get(port, path)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_the_version_helper_returns_text_not_a_module():
    """The trap: yt_dlp.version is a module, yt_dlp.__version__ is the text."""
    fake = FakeYtDlp()
    sys.modules["yt_dlp"] = fake
    was_embedded = ytbridge.EMBEDDED
    ytbridge.EMBEDDED = True
    try:
        version = ytbridge.yt_dlp_version()
        assert isinstance(version, str), \
            "the version must be text, not %r" % type(version)
        assert version == "2026.10.26", version
    finally:
        ytbridge.EMBEDDED = was_embedded
        del sys.modules["yt_dlp"]


def test_health_answers():
    fake = FakeYtDlp()
    sys.modules["yt_dlp"] = fake
    port = free_port()
    server = serve(port)
    try:
        status, body = get(port)
        assert status == 200, "the bridge answered with %s: %s" % (status, body)
        data = json.loads(body)
        assert isinstance(data["yt_dlp"], str), \
            "the yt-dlp version must be text, not %r" % type(data["yt_dlp"])
        assert data["yt_dlp"] == "2026.10.26", data["yt_dlp"]
        # The whole answer has to be writable, or the bridge dies while it
        # is answering.
        json.dumps(data)
    finally:
        server.shutdown()
        server.server_close()
        del sys.modules["yt_dlp"]


def test_a_broken_bridge_says_why():
    """A mistake must not take the connection down with it."""
    port = free_port()
    server = serve(port)
    original = ytbridge.yt_dlp_version

    def broken():
        raise RuntimeError("the test broke it on purpose")

    ytbridge.yt_dlp_version = broken
    try:
        status, body = get_allowing_error(port)
        assert status == 500, status
        data = json.loads(body)
        assert "the test broke it on purpose" in json.dumps(data), data
    finally:
        ytbridge.yt_dlp_version = original
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print("FAIL %s: %s" % (name, exc))
    if failures:
        sys.exit(1)
    print("embedded health: all good")
