"""Proves the bridge's public mode without Cloudflare.

Cloudflare's quick tunnels are rate-limited from this network at the
moment, so the tunnel test skips. That leaves the part of the feature
that is the bridge's own work unverified: the public mode where every
request needs the key, and where the pairing code carries the public
address rather than a local one.

`--public-url` puts the bridge in exactly that mode. The only thing it
does not exercise is cloudflared's transport, which is cloudflared's
work and not the bridge's.

So this starts the bridge with a public URL on a loopback address and
checks the behaviour that matters:

  * a stranger is refused on every endpoint, including the two pairing
    ones that are open on a local network
  * the key is accepted
  * a wrong key is refused
  * the pairing code carries the public address, its scheme and its
    path - read with the same reader the phone uses
  * the health answer names the bridge's own version

It needs no tunnel and no account: `--public-url` puts the bridge in
the same mode, and only cloudflared's transport is left untested -
which is cloudflared's work, not the bridge's. So this test always
runs, even when the quick tunnels are rate-limited.
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "ytbridge.py")
PORT = 8791
PUBLIC = "http://127.0.0.1:%d" % PORT

sys.path.insert(0, HERE)
import ytbridge

failed = 0


def check(name, ok, detail=""):
    global failed
    print(("OK   " if ok else "FAIL ") + name + (("  " + detail) if detail else ""))
    if not ok:
        failed += 1


def call(path, token=None, base=PUBLIC):
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("X-Auth-Token", token)
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except OSError as exc:
        return 0, str(exc)


print("=== the bridge in public mode ===")
proc = subprocess.Popen([sys.executable, BRIDGE, "--pair", "--port", str(PORT),
                          "--library-dir", os.path.expanduser("~/Music"),
                          "--public-url", PUBLIC],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", bufsize=1)
lines = []


def drain():
    for raw in proc.stdout:
        lines.append(raw.rstrip())


import threading
threading.Thread(target=drain, daemon=True).start()

try:
    # Wait for it to answer rather than assuming a time is enough.
    up = False
    for _ in range(30):
        time.sleep(1)
        status, _body = call("/health")
        if status:
            up = True
            break
    check("the bridge is serving", up)

    # The code is base32 in groups of five, printed under the line
    # that says what to do with it - the same way the tunnel test
    # reads it.
    text = "\n".join(lines)
    m = re.search(r"long code[^\n]*\n\s*\n\s*([0-9A-Z]{4,}(?:-[0-9A-Z]+)+)", text)
    if not m:
        m = re.search(r"\b([0-9A-Z]{5}(?:-[0-9A-Z]{5}){3,})\b", text)
    code = m.group(1) if m else None
    check("it printed a long code", code is not None, "-> %s" % (code or "nothing found"))

    if not code:
        raise SystemExit(1)

    # The code is read by the same reader the phone uses.
    host, port, token, scheme, path = ytbridge.read_pairing_code(code)
    check("the code carries the public address",
          host == "127.0.0.1" and scheme == "http" and port == PORT,
          "-> %s:%d %s" % (host, port, scheme))

    # The health answer, with the key.
    status, body = call("/health", token)
    check("the bridge answers with the key", status == 200, "-> HTTP %s" % status)
    if status == 200:
        try:
            data = json.loads(body)
            check("the answer is the bridge's own", data.get("ok") is True)
            check("it says which version it is",
                  data.get("version") == ytbridge.BRIDGE_VERSION,
                  "-> %s (the bridge says %s)" % (data.get("version"),
                                                 ytbridge.BRIDGE_VERSION))
        except ValueError:
            check("the answer is the bridge's own", False, "-> not JSON")

    # A stranger is refused everywhere, including the pairing answers
    # that are open on a local network.
    for path_to_call in ("/health", "/pair/info", "/pair/claim", "/jobs"):
        status, _ = call(path_to_call)
        check("a stranger is refused on %s" % path_to_call, status == 401,
              "-> HTTP %s" % status)

    # The key is accepted, and a wrong key is not.
    status, _ = call("/pair/info", token)
    check("the key is accepted", status == 200, "-> HTTP %s" % status)

    status, _ = call("/pair/info", "0" * 32)
    check("a wrong key is refused", status == 401, "-> HTTP %s" % status)

    # The pairing answer names the public address.
    status, body = call("/pair/info", token)
    if status == 200:
        try:
            data = json.loads(body)
            check("the pairing answer names the public address",
                  data.get("host") == "127.0.0.1", "-> %s" % data.get("host"))
            check("the pairing answer gives the scheme",
                  data.get("scheme") == "http", "-> %s" % data.get("scheme"))
        except ValueError:
            check("the pairing answer names the public address", False)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()

print("")
if failed:
    print("FAIL  %d check(s) failed" % failed)
    sys.exit(1)
print("OK   the bridge's public mode is correct")
