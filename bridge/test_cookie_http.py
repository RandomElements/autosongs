#!/usr/bin/env python3
"""The cookie endpoints have to work over HTTP, not just in a unit test.

The app talks to the bridge over HTTP: it asks what the bridge knows about
cookies, it hands the bridge a jar, and it tells the bridge to forget it
again. These tests start a real bridge and do exactly that.

Run with:  py -3 test_cookie_http.py
"""

import json
import os
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ytbridge  # noqa: E402

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print("   OK %s" % name)
    else:
        print("   FAIL %s" % name)
        FAILED.append(name)
    if not condition and detail:
        print("        %s" % detail)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(port, path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=15) as r:
        return r.status, r.read().decode("utf-8")


def post(port, path, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read().decode("utf-8")


def post_expecting_error(port, path, payload):
    try:
        post(port, path, payload)
        return None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def main():
    workdir = tempfile.mkdtemp(prefix="autosongs-cookie-http-")
    port = free_port()
    server = ytbridge.make_server("127.0.0.1", port, workdir=workdir, embedded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        print("== what the bridge says before anything is sent")
        status, body = get(port, "/cookies")
        answer = json.loads(body)
        check("the endpoint answers", status == 200)
        check("there is no jar yet", answer.get("cookies") is False, body)
        check("and it says so", answer.get("source") == "none", body)

        print("== the health endpoint says the same thing")
        health = json.loads(get(port, "/health")[1])
        check("the health endpoint agrees", health.get("cookies") is False, str(health))
        check("and carries the source", "cookie_source" in health, str(health))

        print("== a jar the app sends is taken")
        jar = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\ttest\tvalue\n"
        status, body = post(port, "/cookies", {"cookies": jar})
        answer = json.loads(body)
        check("the bridge accepts it", status == 200 and answer.get("cookies") is True, body)
        check("and says where it came from",
              answer.get("source") == "the file the app sent", body)

        print("== and it is in use afterwards")
        answer = json.loads(get(port, "/cookies")[1])
        check("the bridge reports the jar", answer.get("cookies") is True, str(answer))
        check("the jar was written where it will be found again",
              os.path.isfile(os.path.join(workdir, "cookies.txt")))
        check("the bridge hands the jar to yt-dlp",
              ytbridge.COOKIES.active is True, repr(ytbridge.COOKIES))
        check("in the shape the library wants",
              ytbridge.COOKIES.api_opts() == {"cookiefile":
                  os.path.join(workdir, "cookies.txt")},
              str(ytbridge.COOKIES.api_opts()))

        print("== a file that is not a jar is refused")
        code, body = post_expecting_error(port, "/cookies", {"cookies": "hello"})
        check("the bridge refuses it", code == 400, "%s %s" % (code, body))

        print("== an empty jar is refused")
        code, body = post_expecting_error(port, "/cookies", {"cookies": ""})
        check("the bridge refuses it", code == 400, "%s %s" % (code, body))

        print("== the jar can be taken away again")
        status, body = post(port, "/cookies", {"clear": True})
        answer = json.loads(body)
        check("the bridge lets it go", answer.get("cookies") is False, body)
        check("and the file is gone",
              not os.path.isfile(os.path.join(workdir, "cookies.txt")))

        print("== a jar that is lying about gets picked up")
        jar_path = os.path.join(workdir, "cookies.txt")
        with open(jar_path, "w", encoding="utf-8") as fh:
            fh.write(jar)
        found, source = ytbridge.find_cookie_source("")
        check("the bridge finds it", found == jar_path, "found %r" % found)
        check("and says where from", source == "in the work folder", source)

    finally:
        server.shutdown()
        server.server_close()

    print()
    if FAILED:
        print("%d FAILURES: %s" % (len(FAILED), "; ".join(FAILED)))
        return 1
    print("cookie endpoints: all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
